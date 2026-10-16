"""Source text and DOI metadata, fetched from this machine (outside the engines) and kept privately.

- `capture`: after an answer, the open copy of each cited source is fetched once and its text kept under
  `.oopc/loop/sources/`, so every later review or check reads the same text whether or not the page opens that day.
  The engines' own streams carry no source text (Codex reports an opened page as "Total lines: N"; Claude's fetch
  returns a summary), and the researcher's excerpt is not independent evidence. Candidates, in order: the URL the
  researcher read it at, its URL, Europe PMC's full text when the source is in PubMed Central, and its DOI.
- `passages`: the parts of a captured text around the values and locator a claim names; that is what a reviewer or
  checker is given, not the whole document.
- `metadata`: a DOI's Crossref title, authors and year, cached under `.oopc/loop/crossref/`; a deposit files findings
  under that title rather than the one the researcher typed.

Network use is plain HTTPS with this tool's own user agent and no personal identifier. A page that refuses (an HTTP
error, a browser challenge) stays uncaptured; nothing works around it. Captured text is private and never exported.
Under `unittest` no request leaves the machine unless `OOPC_ALLOW_NETWORK=1`.
"""
from __future__ import annotations

import bisect
import gzip
import hashlib
import html
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from .util import atomic_json, now, read_json

AGENT = "oopc-source-capture/1.0 (Open Ontology of Polymer Chemistry)"
MAX_BYTES = 25_000_000
MAX_CHARS = 1_000_000
MIN_CHARS = 1500  # Less than this is an abstract stub, an error page or a cookie wall, not the document.
RETRY_DAYS = 7
EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
CROSSREF = "https://api.crossref.org/works/"
REFUSED = re.compile(r"just a moment|checking your browser|client challenge|access denied|attention required|"
                     r"captcha|are you a robot|not a bot|request blocked|forbidden|enable javascript and cookies", re.I)
_PACE = threading.Lock()
_LAST = {}


def network_allowed():
    """Tests never reach the network unless explicitly allowed."""
    return "unittest" not in sys.modules or os.environ.get("OOPC_ALLOW_NETWORK") == "1"


def _paced(host, gap):
    """At most one request per `gap` seconds to one host (Crossref asks for no more than a few a second)."""
    with _PACE:
        wait = _LAST.get(host, 0.0) + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _LAST[host] = time.monotonic()


def get(url, *, accept="*/*", timeout=20):
    """One GET. Returns (status, content type, body, final URL); an HTTP error is a status, not an exception."""
    if not network_allowed():
        raise OSError("Network access is disabled while tests run")
    _paced(urllib.parse.urlsplit(url).hostname or "", 0.34)
    request = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": accept, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return response.status, response.headers.get("Content-Type", ""), body[:MAX_BYTES], response.geturl()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", "") if error.headers else "", b"", url


# ---------------------------------------------------------------------------
# Text from what a server returns

class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "button", "form"}
    BREAK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article",
             "caption", "figcaption", "dd", "dt", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skipping, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag in self.BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BREAK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skipping:
            self.parts.append(data)


def _tidy(text):
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def html_text(body):
    parser = _Text()
    parser.feed(body.decode("utf-8", errors="replace"))
    return _tidy("".join(parser.parts)), " ".join(parser.title.split())


def pdf_text(body):
    """A PDF's text through `pdftotext` (poppler) when installed; None without it."""
    tool = shutil.which("pdftotext")
    if not tool:
        return None
    try:
        done = subprocess.run([tool, "-layout", "-enc", "UTF-8", "-", "-"], input=body, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _tidy(done.stdout.decode("utf-8", errors="replace")) if done.returncode == 0 else None


def xml_text(body):
    """Europe PMC's JATS full text: paragraphs, headings, table cells and captions on their own lines."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return ""
    lines = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in ("title", "p", "caption", "label", "article-title"):
            lines.append(" ".join("".join(element.itertext()).split()))
        elif tag == "tr":
            lines.append(" | ".join(" ".join("".join(cell.itertext()).split()) for cell in element))
    return _tidy("\n".join(line for line in lines if line))


def document_text(content_type, body):
    """(text, method, why not) for one response body."""
    kind = (content_type or "").split(";")[0].strip().lower()
    if kind == "application/pdf" or body[:5] == b"%PDF-":
        text = pdf_text(body)
        return (text, "pdf", "") if text is not None else ("", "pdf", "no-pdftotext")
    if "xml" in kind and b"<article" in body[:5000]:
        return xml_text(body), "jats", ""
    if "html" in kind or body.lstrip()[:1] == b"<":
        text, title = html_text(body)
        if REFUSED.search(title) or (len(text) < MIN_CHARS and REFUSED.search(text[:600])):
            return "", "html", "browser-challenge"
        return text, "html", ""
    if kind.startswith("text/"):
        return _tidy(body.decode("utf-8", errors="replace")), "text", ""
    return "", kind or "unknown", "unsupported-type"


# ---------------------------------------------------------------------------
# Which copies of a source to try

PMCID = re.compile(r"\b(PMC\d{4,9})\b", re.I)
DOI_IN_URL = re.compile(r"(?:doi\.org/|/doi/(?:abs/|full/|pdf/|epdf/)?)(10\.\d{4,9}/[^\s?#]+)", re.I)


def doi_of(url):
    """The DOI a URL names (doi.org and publisher /doi/ paths), else ""."""
    found = DOI_IN_URL.search(urllib.parse.unquote(url or ""))
    return found.group(1).rstrip(".,;)") if found else ""


def clean_doi(doi):
    doi = urllib.parse.unquote((doi or "").strip())
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", doi, flags=re.I)
    return doi if re.match(r"^10\.\d{4,9}/\S+$", doi) else ""


def _europepmc_for_doi(doi, fetch):
    """The PubMed Central id of an open-access article with this DOI, from Europe PMC's search."""
    query = urllib.parse.quote('DOI:"%s" AND OPEN_ACCESS:y' % doi)
    status, _, body, _ = fetch(EUROPE_PMC + "search?format=json&resultType=lite&pageSize=1&query=" + query,
                               accept="application/json")
    if status != 200:
        return ""
    try:
        hits = json.loads(body.decode("utf-8")).get("resultList", {}).get("result", [])
    except ValueError:
        return ""
    return next((h.get("pmcid") for h in hits if h.get("pmcid")), "")


def candidates(source, fetch=None):
    """The URLs to try for one source, best first."""
    urls = [u for u in (source.get("readUrl"), source.get("url")) if isinstance(u, str) and u.startswith("http")]
    pmcid = next((m.group(1).upper() for m in map(PMCID.search, urls) if m), "")
    doi = clean_doi(source.get("doi")) or next((d for d in map(doi_of, urls) if d), "")
    if not pmcid and doi and fetch is not None:
        try:
            pmcid = _europepmc_for_doi(doi, fetch)
        except (OSError, http.client.HTTPException):
            pmcid = ""
    found = list(urls)
    if pmcid:
        found.insert(0, EUROPE_PMC + pmcid + "/fullTextXML")
    if doi:
        found.append("https://doi.org/" + doi)
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------------------
# Captures

def key(source):
    """One key per document, as the knowledge store keys sources (its DOI, else its URL)."""
    from .knowledge import source_key
    return source_key(source.get("doi"), source.get("url")) or source_key("", source.get("readUrl"))


def _path(root, identity):
    from .knowledge import folder
    return folder(root) / "sources" / (hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32] + ".json")


def captured(root, source):
    """The stored capture of a source, or None (also when the last attempt failed)."""
    identity = key(source)
    path = _path(root, identity) if identity else None
    if not path or not path.exists():
        return None
    value = read_json(path)
    return value if value.get("text") else None


def capture(root, source, *, fetch=None, retry_days=RETRY_DAYS):
    """Fetch and keep the text of one source's open copy, once. Returns the stored record: with `text` when a copy
    gave the document, else the attempts and why each failed. A copy that failed is tried again after `retry_days`;
    one not tried yet (an open copy a later note names) is tried at once."""
    identity = key(source)
    if not identity:
        return {"attempts": [], "reason": "no-source"}
    path = _path(root, identity)
    fetch = fetch or get
    tried = set()
    if path.exists():
        value = read_json(path)
        if value.get("text"):
            return value
        if (value.get("attemptedAt") or "") > (datetime.now(timezone.utc) - timedelta(days=retry_days)).isoformat():
            tried = {a.get("url") for a in value.get("attempts") or []}
    # Europe PMC was searched for the DOI when the copies were first tried.
    todo = [url for url in candidates(source, None if tried else fetch) if url not in tried]
    if not todo and path.exists():
        return read_json(path)
    attempts, record = (read_json(path).get("attempts", []) if tried else []), None
    for url in todo:
        try:
            status, kind, body, final = fetch(url)
        except (OSError, ValueError, http.client.HTTPException) as error:  # IncompleteRead is not an OSError.
            attempts.append({"url": url, "reason": type(error).__name__})
            continue
        if status != 200:
            attempts.append({"url": url, "status": status, "reason": "http-%d" % status})
            continue
        text, method, why = document_text(kind, body)
        if not why and len(text) < MIN_CHARS:
            why = "too-short"
        attempts.append({k: v for k, v in {"url": url, "status": status, "method": method, "chars": len(text),
                                           "reason": why}.items() if v not in ("", None)})
        if not why:
            record = {"url": final or url, "method": method, "text": text[:MAX_CHARS], "chars": len(text)}
            break
    value = {"key": identity, "source": {k: source.get(k) for k in ("title", "url", "doi", "readUrl") if source.get(k)},
             "attempts": attempts, "attemptedAt": now()}
    if record:
        value.update(record, capturedAt=value["attemptedAt"])
    atomic_json(path, value, private=True)
    return value


def capture_all(root, sources, *, fetch=None):
    """Capture each distinct source once; returns how many have text. Nothing is tried while the network is off."""
    if fetch is None and not network_allowed():
        return {"sources": 0, "captured": 0}
    seen, have = set(), 0
    for source in sources:
        identity = key(source) if isinstance(source, dict) else ""
        if not identity or identity in seen:
            continue
        seen.add(identity)
        have += bool(capture(root, source, fetch=fetch).get("text"))
    return {"sources": len(seen), "captured": have}


# ---------------------------------------------------------------------------
# Passages: what a reviewer or checker is given

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
LOCATOR = re.compile(r"\b(table|tab\.|figure|fig\.|scheme|section|eq\.|equation)\s*(S?\d+[a-z]?)", re.I)


def needles(*texts):
    """The numbers and table, figure or section labels named in `texts`, to look for in a source."""
    found = []
    for text in texts:
        text = str(text or "")
        for match in LOCATOR.finditer(text):
            word = {"tab.": "table", "fig.": "fig"}.get(match.group(1).lower(), match.group(1).lower())
            found.append((word[:3], match.group(2)))
        for number in NUMBER.findall(text):
            if len(number.replace(",", "").replace(".", "")) >= 2 or "." in number or "," in number:
                found.append(("number", number))
    return list(dict.fromkeys(found))


def _pattern(needle):
    kind, value = needle
    if kind == "number":
        variants = {value, value.replace(",", "."), value.replace(",", "")}
        return r"(?<![\d.,])(?:" + "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True)) + r")(?![\d])"
    prefix = {"tab": r"tab(?:le|\.)", "fig": r"fig(?:ure|\.)", "sec": r"section", "sch": r"scheme",
              "eq.": r"eq(?:uation|\.)", "equ": r"eq(?:uation|\.)"}.get(kind, re.escape(kind))
    return r"\b" + prefix + r"\s*" + re.escape(value) + r"(?![\d])"


def passages(text, wanted, *, limit=3000, window=320):
    """The parts of `text` around `wanted` (from `needles`), the windows naming the most distinct needles first,
    merged where they overlap and cut to `limit` characters in all."""
    if not text or not wanted:
        return []
    window = min(window, limit // 2)
    hits = []
    for index, needle in enumerate(wanted):
        for count, match in enumerate(re.finditer(_pattern(needle), text, flags=re.I)):
            if count == 200:  # A common number ("10") recurs throughout a long document.
                break
            hits.append((match.start(), index))
    if not hits:
        return []
    hits.sort()
    positions = [position for position, _ in hits]
    windows = []
    for start in positions:
        low, high = max(0, start - window), min(len(text), start + window)
        names = {i for _, i in hits[bisect.bisect_left(positions, low):bisect.bisect_left(positions, high)]}
        windows.append((-len(names), low, high))
    chosen, total = [], 0
    for _, low, high in sorted(windows):
        if any(low < b and a < high for a, b in chosen):
            continue
        if total + (high - low) > limit:
            break
        chosen.append((low, high))
        total += high - low
    pieces = []
    for low, high in sorted(chosen):
        piece = " ".join(text[low:high].split())
        pieces.append(("…" if low else "") + piece + ("…" if high < len(text) else ""))
    return pieces


def evidence(root, source, *texts, limit=3000):
    """What a reviewer or checker gets for one source: where and when its text was captured, and the passages
    around the values and labels in `texts`. None when the source has no capture."""
    value = captured(root, source)
    if not value:
        return None
    found = passages(value["text"], needles(*texts), limit=limit)
    return {"from": value.get("url"), "capturedAt": (value.get("capturedAt") or "")[:10],
            "passages": found or ["(No passage of the captured text names these values or labels.)"]}


# ---------------------------------------------------------------------------
# DOI metadata

def _metadata_path(root, doi):
    from .knowledge import folder
    return folder(root) / "crossref" / (hashlib.sha1(doi.lower().encode("utf-8")).hexdigest() + ".json")


def _summary(message):
    year = None
    for field in ("published", "published-print", "published-online", "issued", "created"):
        parts = ((message.get(field) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            year = int(parts[0])
            break
    authors = ["%s, %s" % (a.get("family"), a.get("given")) if a.get("given") else a.get("family") or a.get("name")
               for a in message.get("author") or []]
    titles = [t for t in message.get("title") or [] if isinstance(t, str) and t.strip()]
    # Crossref titles carry markup (<i>, <sub>) and entities; the stored title is plain text, with a subscript or
    # superscript joined to what it belongs to ("SiO<sub>2</sub>" is "SiO2", not "SiO 2").
    title = re.sub(r"\s*\n\s*(?=-)|(?<=-)\s*\n\s*", "", titles[0]) if titles else ""  # "butyrate-\n<i>co</i>\n-3"
    title = re.sub(r"(?<=-)(<[^>]+>)\s*\n\s*|\s*\n\s*(</[^>]+>)(?=-)", r"\1\2", title)
    title = re.sub(r"\s*<(?:sub|sup|inf)>\s*([^<]*?)\s*</(?:sub|sup|inf)>", r"\1", title)
    title = " ".join(html.unescape(re.sub(r"<[^>]+>", "", title)).split())
    return {k: v for k, v in {"title": title, "authors": [a for a in authors if a][:30], "year": year,
                              "container": (message.get("container-title") or [""])[0]}.items() if v}


def metadata(root, doi, *, fetch=None, cached_only=False):
    """Crossref's title, authors, year and journal for a DOI, cached; None when unknown or not reachable."""
    doi = clean_doi(doi)
    if not doi:
        return None
    path = _metadata_path(root, doi)
    if path.exists():
        value = read_json(path)
        return _summary(value["message"]) if value.get("status") == 200 and value.get("message") else None
    if cached_only:
        return None
    try:
        status, _, body, _ = (fetch or get)(CROSSREF + urllib.parse.quote(doi, safe="/"), accept="application/json")
    except (OSError, ValueError, http.client.HTTPException):
        return None  # Not cached: tried again next time.
    if status == 200:
        try:
            message = json.loads(body.decode("utf-8")).get("message") or {}
        except ValueError:
            return None
        atomic_json(path, {"doi": doi, "status": 200, "fetchedAt": now(), "message": message}, private=True)
        return _summary(message)
    if status == 404:
        atomic_json(path, {"doi": doi, "status": 404, "fetchedAt": now()}, private=True)
    return None


def title_words(title):
    return set(re.findall(r"[a-z0-9]+", re.sub(r"<[^>]+>", " ", (title or "").lower()))) - {"the", "of", "and", "a", "an",
                                                                                            "in", "on", "for", "with"}


def same_title(a, b):
    """Whether two titles name one work, allowing case, punctuation, markup and small word-order changes."""
    first, second = title_words(a), title_words(b)
    return bool(first and second) and first == second
