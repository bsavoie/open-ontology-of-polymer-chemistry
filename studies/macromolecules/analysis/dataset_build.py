#!/usr/bin/env python3
"""Figure 3 data: the knowledge base as a polymer dataset (study plan, Figure 3 and E2).

Reads the frozen knowledge store K3, the pinned graph release, the question records and the campaign
records, all read-only, and writes growth.json, coverage.json, sources.json and completeness.json next to
this script, plus SUMMARY.md. The only network use is the public Crossref REST API
(https://api.crossref.org/works/{doi}) for DOI metadata: no email or personal identifier is sent, requests
are throttled to at most three a second, each response is cached under cache/crossref/, and a rerun only
asks for DOIs not yet cached (404s are cached; timeouts and server errors are not, so they are retried).

    python build.py              # fetch missing Crossref records, then build everything
    python build.py --offline    # build from the cache only
    python build.py --fetch-only # only fill the Crossref cache

Standard library only. Outputs carry ids, counts, source titles, URLs and DOIs; never question text,
excerpts or local paths.

Ran as `.oopc/study/analysis/dataset/build.py`; moved to the repository on 2026-10-13 unchanged except imports and
paths. It still writes its outputs and Crossref cache to `.oopc/study/analysis/dataset/`, not beside this file.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never write __pycache__ into the frozen worktree

import argparse
import collections
import datetime as dt
import hashlib
import json
import random
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import unicodedata
import urllib.request
import html as html_lib
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import ROOT, analysis_dir, run_dir  # noqa: E402  (common puts CODE first on sys.path)

OUT = analysis_dir("dataset")  # the private folder it ran in and writes to
STORE = run_dir("2026-10-ablation") / "workspaces/K3/.oopc/loop/knowledge.sqlite"
RELEASE_ID = "oopc-76ae33828dd011e2a0326644"
RELEASE = ROOT / "releases" / RELEASE_ID
QUESTIONS = ROOT / ".oopc/loop/questions"
CAMPAIGN = run_dir("2026-10-campaign")
RUN200 = run_dir("2026-10-03-200")
CACHE = OUT / "cache" / "crossref"
SNAPSHOT_ID = "oopc-knowledge-0f0a0104a3f9e15a08b94bf7"

from oopc.knowledge import source_key  # noqa: E402  (frozen worktree at tag study-freeze)

STATUS = {"supported": "Reviewed", "accepted": "Added", "uncertain": "Needs checking", "unsupported": "Rejected"}
STATUS_ORDER = ["Reviewed", "Added", "Needs checking", "Rejected"]
LOCAL_PATH = re.compile(r"file:|(?<![\w.])(/Users/|/home/|/private/|/var/folders/|/tmp/)|\b[A-Za-z]:\\")


def read_only(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def write_json(name, data):
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if LOCAL_PATH.search(text):
        raise SystemExit("%s would contain a local path; nothing written" % name)
    (OUT / name).write_text(text + "\n", encoding="utf-8")


def host_of(url):
    try:
        host = urlsplit((url or "").strip()).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


# ----------------------------------------------------------------------------------------------- loading

def load_store():
    db = read_only(STORE)
    findings = [dict(r) for r in db.execute("SELECT * FROM findings ORDER BY id")]
    for f in findings:
        f["detail"] = json.loads(f["detail"] or "{}")
        f["statusLabel"] = STATUS[f["status"]]
        f["key"] = source_key(f["source_doi"], f["source_url"])
    notes = [dict(r) for r in db.execute("SELECT id, question_id, origin, title, url, doi, read_url, created_at FROM notes ORDER BY id")]
    for n in notes:
        n["key"] = source_key(n["doi"], n["url"])
    deposits = [dict(r) for r in db.execute("SELECT * FROM deposits ORDER BY deposited_at, question_id")]
    reviews = [dict(r) for r in db.execute("SELECT id, question_id, engine, status FROM reviews")]
    db.close()
    return findings, notes, deposits, reviews


def load_graph():
    db = read_only(RELEASE / "graph.sqlite")
    facets = {r["id"]: (json.loads(r["json"])["axis"], r["label"]) for r in db.execute("SELECT id, label, json FROM records WHERE type='Facet'")}
    polymers = {}
    for r in db.execute("SELECT id, label, json FROM records WHERE type='PolymerConcept' ORDER BY id"):
        d = json.loads(r["json"])
        polymers[r["id"]] = {"id": r["id"], "label": r["label"], "entryKind": d.get("entryKind"),
                             "abbreviations": d.get("abbreviations") or [], "class": None, "marketTier": [],
                             "broader": [], "narrower": []}
    for r in db.execute("SELECT subject, object, json FROM edges WHERE predicate='hasFacet'"):
        if r["subject"] not in polymers:
            continue
        axis, label = facets[r["object"]]
        if axis == "primaryClass":
            polymers[r["subject"]]["class"] = label
        elif axis == "marketTiers":
            polymers[r["subject"]]["marketTier"].append(label)
    for r in db.execute("SELECT subject, predicate, object FROM edges WHERE predicate IN ('broader','narrower')"):
        if r["subject"] in polymers:
            polymers[r["subject"]][r["predicate"]].append(r["object"])
    db.close()
    for p in polymers.values():
        p["broader"].sort(), p["narrower"].sort(), p["marketTier"].sort()
    return polymers


def load_question_meta(ids):
    meta = {}
    for qid in ids:
        folder = QUESTIONS / qid
        q = json.loads((folder / "question.json").read_text()) if (folder / "question.json").exists() else {}
        r = json.loads((folder / "result.json").read_text()) if (folder / "result.json").exists() else {}
        meta[qid] = {"origin": q.get("origin"), "engine": r.get("engine") or q.get("engine"), "model": r.get("model"),
                     "promptVersion": r.get("promptVersion"), "submittedAt": q.get("submittedAt"),
                     "finishedAt": q.get("finishedAt"), "depth": q.get("depth")}
    return meta


def load_runs():
    """Run membership by question id: the 200-task run and the three campaign waves; times from state files."""
    member = {}
    for row in json.loads((RUN200 / "rows.json").read_text()):
        member[row["taskId"]] = "200-task run"
    for row in json.loads((CAMPAIGN / "questions.json").read_text()):
        member[row["taskId"]] = "wave %s" % row["wave"]
    states = {"200-task run": json.loads((RUN200 / "state.json").read_text())}
    for wave in (1, 2, 3):
        states["wave %d" % wave] = json.loads((CAMPAIGN / "waves" / ("wave-%d" % wave) / "state.json").read_text())
    runs = {name: {"startedAt": s.get("startedAt"), "finishedAt": s.get("finishedAt"), "planned": s.get("planned"),
                   "completed": s.get("completed"), "promptVersion": s.get("promptVersion"), "engine": s.get("engine")}
            for name, s in states.items()}
    return member, runs


# ----------------------------------------------------------------------------------------------- Crossref

def cache_path(doi):
    return CACHE / (hashlib.sha1(doi.encode("utf-8")).hexdigest() + ".json")


def fetch_crossref(dois, log=print):
    """Fill the cache for DOIs not yet cached. At most 3 requests a second, one at a time."""
    CACHE.mkdir(parents=True, exist_ok=True)
    todo = [d for d in sorted(dois) if not cache_path(d).exists()]
    log("Crossref: %d DOIs, %d cached, %d to fetch" % (len(dois), len(dois) - len(todo), len(todo)))
    last, failed = 0.0, []
    for i, doi in enumerate(todo, 1):
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/")
        outcome = None
        for attempt in range(3):
            wait = last + 0.34 - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            request = urllib.request.Request(url, headers={"User-Agent": "oopc-study-dataset/1.0", "Accept": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    body = json.loads(response.read().decode("utf-8"))
                outcome = {"doi": doi, "status": 200, "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                           "message": body.get("message", {})}
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    outcome = {"doi": doi, "status": 404, "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
                    break
                retry_after = e.headers.get("Retry-After") if e.headers else None
                time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2.0 * (attempt + 1) ** 2)
                outcome = {"error": "HTTP %d" % e.code}
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                time.sleep(2.0 * (attempt + 1) ** 2)
                outcome = {"error": type(e).__name__}
        if outcome and "status" in outcome:
            tmp = cache_path(doi).with_suffix(".partial")
            tmp.write_text(json.dumps(outcome, ensure_ascii=False), encoding="utf-8")
            tmp.rename(cache_path(doi))
        else:
            failed.append((doi, (outcome or {}).get("error")))
        if i % 100 == 0:
            log("  %d/%d fetched, %d failed so far" % (i, len(todo), len(failed)))
    log("Crossref: done, %d not fetched this run (retried on the next run)" % len(failed))
    return failed


def crossref_record(doi):
    path = cache_path(doi)
    if not path.exists():
        return {"crossrefStatus": "not-fetched"}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") != 200:
        return {"crossrefStatus": "not-found"}
    m = data.get("message") or {}
    year = None
    for field in ("published", "published-print", "published-online", "issued", "created"):
        parts = ((m.get(field) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            year = int(parts[0])
            break
    titles = m.get("title") or []
    containers = m.get("container-title") or []
    return {"crossrefStatus": "found", "year": year, "publisher": m.get("publisher"),
            "containerTitle": containers[0] if containers else None, "crossrefType": m.get("type"),
            "crossrefSubtype": m.get("subtype"), "crossrefTitle": titles[0] if titles else None,
            "licenseUrls": sorted({l.get("URL") for l in m.get("license") or [] if l.get("URL")}),
            "licenses": sorted(({"url": l.get("URL"), "contentVersion": l.get("content-version"),
                                 "delayInDays": l.get("delay-in-days")} for l in m.get("license") or [] if l.get("URL")),
                               key=lambda l: (l["url"], l["contentVersion"] or ""))}



# ----------------------------------------------------------------------------------------------- source types
# One type per source, first rule that fires wins. A DOI found in Crossref is typed by its Crossref record
# (rule group A); every other source (URL-only, or a DOI Crossref does not know) by its DOI prefix, cited
# URL host, URL path and title (rule group B). The rules are listed in SUMMARY.md.

TYPES = ["journal article", "patent", "technical data sheet/manufacturer", "thesis", "standard", "book/chapter",
         "preprint", "government/report", "other web"]

CROSSREF_TYPES = {
    "journal-article": "journal article", "proceedings-article": "journal article", "journal-issue": "journal article",
    "journal": "journal article", "journal-volume": "journal article",
    "book-chapter": "book/chapter", "book": "book/chapter", "monograph": "book/chapter", "edited-book": "book/chapter",
    "reference-book": "book/chapter", "reference-entry": "book/chapter", "book-part": "book/chapter",
    "book-section": "book/chapter", "book-series": "book/chapter", "book-set": "book/chapter", "book-track": "book/chapter",
    "dissertation": "thesis", "standard": "standard", "standard-series": "standard",
    "report": "government/report", "report-component": "government/report", "report-series": "government/report",
    "posted-content": "preprint",
}
PREPRINT_PREFIXES = {"10.26434": "ChemRxiv", "10.48550": "arXiv", "10.1101": "bioRxiv/medRxiv", "10.20944": "Preprints.org",
                     "10.21203": "Research Square", "10.2139": "SSRN", "10.31224": "OSF", "10.22541": "Authorea"}
DATA_PREFIXES = {"10.5281": "Zenodo", "10.6084": "figshare", "10.17632": "Mendeley Data"}
THESIS_PREFIXES = {"10.6100": "TU Eindhoven research portal"}
# Encyclopedia entries Crossref may type as "other": Ullmann's, Kirk-Othmer, Encyclopedia of Polymer Science and Technology.
REFERENCE_DOI = re.compile(r"^10\.1002/(14356007|0471238961|0471440264|9780471440260)\.")

PATENT_HOSTS = ("patents.google.com", "patents.justia.com", "freepatentsonline.com", "patentimages.storage.googleapis.com",
                "data.epo.org", "worldwide.espacenet.com", "patentscope.wipo.int", "eureka.patsnap.com", "ppubs.uspto.gov",
                "patft.uspto.gov", "uspto.gov", "trea.com", "patents.com", "patentguru.com")
PATENT_TITLE = re.compile(r"\bpatent\b|^(US|EP|WO|CN|JP|KR|DE|GB|FR|CA)\s?\d{4,}", re.I)
PATENT_PATH = re.compile(r"/patent(s|app)?/|/patentapp", re.I)

STANDARD_HOSTS = ("astm.org", "store.astm.org", "iso.org", "standards.iteh.ai", "pdfstandards.net", "din.de", "beuth.de",
                  "bsigroup.com", "webstore.ansi.org", "ansi.org", "iec.ch", "webstore.iec.ch", "jsa.or.jp", "sae.org",
                  "standards.globalspec.com", "global.ihs.com")
STANDARD_TITLE = re.compile(r"\bStandard (Test Method|Specification|Practice|Guide|Terminology|Classification)s?\b|"
                            r"^\s*(ASTM|ISO|DIN|IEC|JIS|BS|EN|UL|ANSI|DEF ?STAN|Defence Standard)\b[\s-]*(EN\s*|ISO\s*)?[A-Z]?\s?\d{2,}", re.I)

PREPRINT_HOSTS = ("arxiv.org", "chemrxiv.org", "biorxiv.org", "medrxiv.org", "preprints.org", "researchsquare.com",
                  "ssrn.com", "papers.ssrn.com", "authorea.com", "osf.io", "techrxiv.org", "engrxiv.org")

THESIS_CUE = re.compile(r"(?<![a-z])thes[ie]s(?![a-z])|dissertation|\bph\.?\s?d\b|phd\.pdf|doctoral|master'?s|\bmsc\b|\betd\b|\btesis\b|"
                        r"phdthesis|/etd[./]|etheses|theses\.|/theses/|graduate_manual|/tesis/|/outputs/graduate/|"
                        r"diplomarbeit|habilitation|\d{2}phd\.pdf|collectionscanada\.gc\.ca", re.I)
THESIS_HOSTS = ("etd.ohiolink.edu", "etda.libraries.psu.edu", "etheses.bham.ac.uk", "etheses.dur.ac.uk", "theses.ncl.ac.uk",
                "theses.lib.polyu.edu.hk", "collectionscanada.gc.ca", "bac-lac.on.worldcat.org", "elischolar.library.yale.edu",
                "proquest.com", "search.proquest.com", "dspacemainprd01.lib.uwaterloo.ca", "uwspace.uwaterloo.ca",
                "escholarship.mcgill.ca", "hbni.ac.in", "s-space.snu.ac.kr", "ujcontent.uj.ac.za", "stag.utb.cz",
                "vtechworks.lib.vt.edu")

BOOK_HOSTS = ("books.google.com", "books.google.co.uk", "catalogimages.wiley.com", "epdf.pub", "dokumen.pub", "vdoc.pub",
              "ebin.pub", "silo.pub", "studylib.es")
BOOK_CUE = re.compile(r"\bhandbook\b|encyclopedia|encyclopaedia|compendium|textbook|/chapters?/|\bchapter \d|\bbook\b|\.excerpt\.pdf", re.I)

ARTICLE_HOSTS = ("pmc.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "europepmc.org", "sciencedirect.com",
                 "linkinghub.elsevier.com", "onlinelibrary.wiley.com", "pubs.acs.org", "pubs.rsc.org", "link.springer.com",
                 "springer.com", "nature.com", "mdpi.com", "mdpi-res.com", "frontiersin.org", "tandfonline.com",
                 "journals.sagepub.com", "iopscience.iop.org", "journals.plos.org", "hindawi.com", "downloads.hindawi.com",
                 "biomedcentral.com", "scielo.br", "scielo.org", "scielo.org.mx", "jstage.jst.go.jp", "semanticscholar.org",
                 "pdfs.semanticscholar.org", "researchgate.net", "academia.edu", "citeseerx.ist.psu.edu", "core.ac.uk",
                 "electronicsandbooks.com", "bioresources.cnr.ncsu.edu", "cellulosechemtechnol.ro", "meridian.allenpress.com",
                 "dialnet.unirioja.es", "m.earticle.net", "scispace.com", "pubs.aip.org", "aip.scitation.org", "journals.aps.org",
                 "cambridge.org", "academic.oup.com", "degruyter.com", "degruyterbrill.com", "karger.com", "thieme-connect.com",
                 "jstor.org", "koreascience.kr", "koreascience.or.kr", "cir.nii.ac.jp", "ci.nii.ac.jp",
                 "par.nsf.gov", "scirp.org", "matec-conferences.org", "e3s-conferences.org", "epj-conferences.org",
                 "media.springernature.com", "rsc.org", "acs.org", "sci-hub", "expresspolymlett.com", "polymer-korea.or.kr",
                 "journal.polymer-korea.or.kr", "cjps.org", "fracturae.com", "iasj.rdd.edu.iq", "iasj.net", "sciengine.com",
                 "sphinxsai.com", "tsijournals.com", "primescholars.com", "orientjchem.org", "walshmedicalmedia.com",
                 "arkat-usa.org", "bch.ro", "bjp-bg.com", "rmf.smf.mx", "plantnutrifert.org", "pjps.pk", "ichp.vot.pl",
                 "journal.uctm.edu", "ejchem.journals.ekb.eg", "oam-rc.inoe.ro", "nopr.niscpr.res.in", "acta.fih.upt.ro",
                 "briefs.techconnect.org", "digitallibrarynasampe.org", "4spepublications.onlinelibrary.wiley.com",
                 "chemistry-europe.onlinelibrary.wiley.com", "aiche.onlinelibrary.wiley.com", "advanced.onlinelibrary.wiley.com",
                 "ijiset.com", "ijasrm.com", "ijses.com", "inpressco.com", "worldresearchlibrary.org", "thefibersociety.org",
                 "resources.inmm.org", "titan.ijs.si", "lib3.dss.go.th", "sta.uwi.edu")
ARTICLE_CUE = re.compile(r"journal|/ojs/|/article[s/_-]|/articles?/|/doi/|/publ(ications?|ikac|/)|/papers?/|/manuscripts?/|"
                         r"proceedings|/jres/|/abs/|conference|/vol\d|/volumes?/", re.I)
REPOSITORY_CUE = re.compile(r"repository|repositorio|eprints?|\bpure\b|pure\.|pureadmin|dspace|diva-portal|/handle/|"
                            r"bitstream|\bcris\.|orca\.|scholarworks|escholarship|researchonline|research\.|hal\.|"
                            r"\.repo\.nii\.ac\.jp|qucosa|publica|preserve\.|re\.public|opus|digital ?commons|"
                            r"vtechworks|deepblue|scholar|\.edu$|\.edu\.[a-z]{2}$|\.ac\.[a-z]{2}$|\buni-|univ|"
                            r"exlibrisgroup|pstorage-", re.I)
REPOSITORY_PATH = re.compile(r"/handle/\d|/bitstreams?/|/eprint/|/server/api/core/", re.I)

GOV_HOST = re.compile(r"(\.gov|\.gov\.[a-z]{2}|\.mil|\.europa\.eu|\.gc\.ca|\.gouv\.fr|\.go\.jp|\.gov\.cn)$|"
                      r"^(ntrs\.nasa\.gov|osti\.gov|nvlpubs\.nist\.gov|nist\.gov|govinfo\.gov|nepis\.epa\.gov|"
                      r"apps\.dtic\.mil|discover\.dtic\.mil|info\.ornl\.gov|sarjaweb\.vtt\.fi)$", re.I)
GOV_ARTICLE_PATH = re.compile(r"/jres/", re.I)  # NIST's Journal of Research: articles on a government host
GOV_NOT = ("pmc.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "par.nsf.gov")
REPORT_CUE = re.compile(r"technical report|\breport\b|\bnistir\b|SAND\d{4}|\bTR[- ]\d|annual report|jahresbericht|"
                        r"technical activities|quarterly report|internal-reports", re.I)

MANUFACTURER_HOSTS = (
    "basf.com", "download.basf.com", "polystyrol.basf.com", "dupont.com", "dupont.co.in", "dupont.com.au", "solvay.com",
    "syensqo.com", "celanese.com", "covestro.com", "solutions.covestro.com", "sabic.com", "sabic-specialties.com",
    "materialfinder.sabic-specialties.com", "dow.com", "arkema.com", "evonik.com", "products.evonik.com",
    "evonik.daicel.com", "victrex.com", "kuraray.com", "kuraray.eu", "genestar.kuraray.com", "lanxess.com",
    "exxonmobilchemical.com", "lyondellbasell.com", "ineos.com", "ineosstyrolutionindia.com", "borealisgroup.com",
    "ensinger-online.com", "ensingerplastics.com", "mcam.com", "mitsui.com", "mgc.co.jp", "toray.com", "films.toray",
    "toray-research.co.jp", "teijin-resin.com", "teijin-frontier-usa.com", "teijin.com", "ube.co.jp", "sumitomo-chem.co.jp",
    "sumichem-at.com", "toyobo-global.com", "unitika.co.jp", "zeon.co.jp", "zeonchemicals.com", "zeonsmi.com", "kraton.com",
    "avient.com", "polyplastics.com", "daikin.com", "agc-chemicals.com", "chemours.com", "teflon.com", "viton.com",
    "delrin.com", "kapton.com", "3m.com", "wacker.com", "momentive.com", "shinetsu.co.jp", "stratasys.com",
    "stratasys.co.in", "aerospace.stratasys.com", "polymaker.com", "protolabs.com", "curbellplastics.com",
    "professionalplastics.com", "plasticsintl.com", "boedeker.com", "hongrunplastics.com", "sushengpolymer.com",
    "mgiintl.com", "lookpolymers.com", "matweb.com", "materialdatacenter.com", "omnexus.specialchem.com", "specialchem.com",
    "ulprospector.com", "campusplastics.com", "plasticsfinder.envalior.com", "envalior.com", "netzsch.com",
    "analyzing-testing.netzsch.com", "tainstruments.com", "shimadzu.com", "shimadzu.com.sg", "hitachi-hightech.com",
    "perkinelmer.com", "mt.com", "mettler-toledo.com", "malvernpanalytical.com", "anton-paar.com", "intertek.com",
    "madisongroup.com", "topas.com", "poketone.com", "plexiglas-polymers.com", "perspex.co.uk", "lgchem.com",
    "versalis.eni.com", "synthomer.com", "kuredux.com", "bada.de", "gehr.de", "rct-online.de", "roechling.com",
    "schmidt-bartl.de", "kuhn-marsberg.de", "tekuma.de", "plastum.cz", "plastore.it", "nevicolor.it", "aplast.fr",
    "aikolon.fi", "isokon.si", "lanema.es", "proplastik.lv", "prizma-ind.co.il", "mtm-petro.com", "lrf.com.qa",
    "bahrainpipes.com", "b3d.com.au", "primaeam.com", "genesismedicalplastics.com", "aiplastics.com", "epectec.com",
    "fluorolab.com", "fluorotherm.com", "fostercomp.com", "gallagherseals.com", "products.fst.com", "coruba.co.uk",
    "mnrubber.com", "sealseastern.com", "cancarb.com", "castrocompositesshop.com", "fslplymouth.co.uk", "interplastic.com",
    "mulfordplastics.com", "nordonplastics.com", "ogfilm.co.jp", "spartech.com", "textilescoated.com", "theplasticshop.co.uk",
    "usplastic.com", "centralsteelfab.com", "rdabbott.com", "r-g.de", "media.easycomposites.eu", "aitechnology.com",
    "scscoatings.com", "sipol.com", "tetrachim.com", "ledil.com", "lesker.com", "neg.co.jp", "propolymers.com",
    "fuelcellearth.com", "polympart.com", "ranking-wise.com.tw", "cdn.komachine.com", "pub-mediabox-storage.rxweb-prd.com",
    "exhibitorsearch.messefrankfurt.com", "plasticportal.eu", "ecoease.co.uk", "cms.mkhoster.com", "cdn1.npcdn.net",
    "bpf.co.uk", "engineerlive.com", "compositeskn.org", "kit-technology.de", "polymerdatabase.com")
MANUFACTURER_CUE = re.compile(r"data ?sheet|datasheet|data[_-]sheet|\btds\b|[/_-]tds[-_.]|technical data|technical information|"
                              r"technical (guide|note|bulletin|manual|handbook|guidebook)|product (data|information|guide|"
                              r"bulletin|brochure|list|selection|sheet)|selection guide|design (& |and )?(processing )?guide|"
                              r"processing guide|compounding guide|extrusion (guide|manual)|brochure|properties bulletin|"
                              r"summary of properties|typical properties|application ?notes?|applications-notes|"
                              r"/material-?data|/datasheets?/|/products?/|/grades?/|catalog(ue)?\b|leaflet|\bpis\b|"
                              r"/tds-documents/|design guide|fluid resistance guide", re.I)
TRADEMARK = re.compile(r"[®™]")


def on(hosts, table):
    """Any host equal to, or a subdomain of, a host in the table."""
    return any(h == t or h.endswith("." + t) for h in hosts for t in table)


def classify(doi, hosts, urls, title, cr):
    """(type, rule) for one source. hosts: cited hosts, most common first; urls: cited and read URLs; title: best title."""
    text = " ".join([title or ""] + list(urls))
    host = hosts[0] if hosts else ""
    prefix = doi.split("/")[0] if doi else ""
    if doi and REFERENCE_DOI.match(doi):
        return "book/chapter", "A0 DOI of an encyclopedia entry (Ullmann's, Kirk-Othmer, EPST)"
    if cr.get("crossrefStatus") == "found":
        ctype = cr.get("crossrefType")
        if prefix in PREPRINT_PREFIXES:
            return "preprint", "A1 DOI prefix of a preprint server (%s)" % PREPRINT_PREFIXES[prefix]
        if ctype in CROSSREF_TYPES:
            return CROSSREF_TYPES[ctype], "A2 Crossref type %s" % ctype
        if ctype in ("dataset", "database", "component", "peer-review", "other", "grant"):
            pass  # fall through to the host and title rules
    if prefix in PREPRINT_PREFIXES:
        return "preprint", "B1 DOI prefix of a preprint server (%s)" % PREPRINT_PREFIXES[prefix]
    if prefix in DATA_PREFIXES:
        return "other web", "B2 DOI prefix of a data repository (%s)" % DATA_PREFIXES[prefix]
    if prefix in THESIS_PREFIXES:
        return "thesis", "B2 DOI prefix of a thesis repository (%s)" % THESIS_PREFIXES[prefix]
    if on(hosts, PATENT_HOSTS) or any(PATENT_PATH.search(u) for u in urls) or PATENT_TITLE.search(title or ""):
        return "patent", "B3 patent host, patent path or patent number/word in title"
    if on(hosts, STANDARD_HOSTS) or STANDARD_TITLE.search(title or ""):
        return "standard", "B4 standards host or standard designation in title"
    if on(hosts, PREPRINT_HOSTS):
        return "preprint", "B5 preprint server host"
    if on(hosts, THESIS_HOSTS) or THESIS_CUE.search(text):
        return "thesis", "B6 thesis host or thesis/dissertation cue in title or URL"
    if on(hosts, ARTICLE_HOSTS):
        return "journal article", "B7 publisher, journal or article-aggregator host"
    if any(GOV_HOST.search(h) and h not in GOV_NOT for h in hosts) and not any(GOV_ARTICLE_PATH.search(u) for u in urls):
        return "government/report", "B8 government or national-laboratory host"
    if on(hosts, BOOK_HOSTS) or (BOOK_CUE.search(text) and not MANUFACTURER_CUE.search(text)
                                and not on(hosts, MANUFACTURER_HOSTS)):
        return "book/chapter", "B9 book host or handbook/encyclopedia/chapter cue"
    if on(hosts, MANUFACTURER_HOSTS):
        return "technical data sheet/manufacturer", "B10 manufacturer, distributor, materials-database or instrument-maker host"
    if any(REPOSITORY_CUE.search(h) for h in hosts) or any(REPOSITORY_PATH.search(u) for u in urls):
        return "journal article", "B11 academic or institutional repository copy without a thesis cue"
    if MANUFACTURER_CUE.search(text) or TRADEMARK.search(title or ""):
        return "technical data sheet/manufacturer", "B12 data-sheet/brochure/product cue or trademark symbol in title"
    if REPORT_CUE.search(text):
        return "government/report", "B13 report cue in title or URL"
    if ARTICLE_CUE.search(text):
        return "journal article", "B14 article cue in URL or title"
    if doi:
        return "journal article", "B15 DOI not typed by Crossref: default journal article"
    return "other web", "B16 none of the above"


OPEN_PUBLISHERS = re.compile(r"\bMDPI\b|Frontiers Media|Public Library of Science|\bPLOS\b|Hindawi|BioMed Central|"
                             r"Copernicus|PeerJ|eLife|Beilstein|SciELO|Pensoft|Scientific Research Publishing|IntechOpen|"
                             r"Dove Medical|Oxford Open|AIMS Press|Bentham Open", re.I)
OPEN_HOSTS = ("mdpi.com", "mdpi-res.com", "frontiersin.org", "journals.plos.org", "hindawi.com", "downloads.hindawi.com",
              "biomedcentral.com", "scielo.br", "scielo.org", "scielo.org.mx", "intechopen.com", "scirp.org", "peerj.com",
              "beilstein-journals.org")
PMC_HOSTS = ("pmc.ncbi.nlm.nih.gov", "europepmc.org")


def open_access(hosts_all, urls_all, cr, stype):
    basis = []
    if on(hosts_all, PMC_HOSTS) or any("ncbi.nlm.nih.gov/pmc" in u.lower() for u in urls_all):
        basis.append("PubMed Central copy")
    if cr.get("publisher") and OPEN_PUBLISHERS.search(cr["publisher"]):
        basis.append("open-access publisher")
    elif on(hosts_all, OPEN_HOSTS):
        basis.append("open-access publisher host")
    if any("creativecommons.org" in (l["url"] or "") and l.get("contentVersion") in ("vor", "unspecified", None)
           for l in cr.get("licenses") or []):
        basis.append("Creative Commons licence (version of record)")
    elif any("creativecommons.org" in (l["url"] or "") for l in cr.get("licenses") or []):
        basis.append("Creative Commons licence (accepted manuscript only)")
    if stype == "preprint":
        basis.append("preprint server")
    strict = [b for b in basis if b != "Creative Commons licence (accepted manuscript only)"]
    return bool(strict), basis


STOP = {"the", "of", "and", "a", "an", "in", "on", "for", "by", "with", "to", "its", "at", "from", "via", "as", "or"}
CITATION_STYLE = re.compile(r"\bdoi\b|\bet al\b|^\s*(ASTM|ISO|DIN|IEC)\b|\(\d{4}\)", re.I)


def title_tokens(text):
    text = unicodedata.normalize("NFKC", html_lib.unescape(re.sub(r"<[^>]+>", " ", text or ""))).lower()
    return set(re.findall(r"[a-z0-9]+", text)) - STOP


def doi_title_check(store_title, crossref_title):
    """Does the title the researcher recorded match Crossref's title for the DOI? Containment of the smaller token set."""
    if not store_title or not crossref_title:
        return "not compared (no title)"
    if CITATION_STYLE.search(store_title):
        return "not compared (citation-style title)"
    a, b = title_tokens(store_title), title_tokens(crossref_title)
    if not a or not b:
        return "not compared (no title)"
    return "match" if len(a & b) / min(len(a), len(b)) >= 0.6 else "mismatch"


def publisher_group(name):
    if not name:
        return None
    rules = [("Elsevier", r"elsevier"), ("Wiley", r"wiley"), ("Springer Nature", r"springer|nature|biomed central"),
             ("American Chemical Society", r"american chemical society"), ("Royal Society of Chemistry", r"royal society of chemistry"),
             ("MDPI", r"\bmdpi\b"), ("SAGE", r"\bsage\b"), ("Taylor & Francis", r"taylor|informa"), ("Hindawi", r"hindawi"),
             ("Frontiers", r"frontiers"), ("IOP Publishing", r"iop publishing"), ("AIP Publishing", r"aip publishing|american institute of physics"),
             ("De Gruyter", r"gruyter"), ("ASTM International", r"astm")]
    for group, pattern in rules:
        if re.search(pattern, name, re.I):
            return group
    return name


# ----------------------------------------------------------------------------------------------- helpers

def by_status(items):
    counts = collections.Counter(f["statusLabel"] for f in items)
    return {s: counts.get(s, 0) for s in STATUS_ORDER}


def median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def share(part, whole, digits=4):
    return round(part / whole, digits) if whole else None


def run_of(member, deposited):
    """Run label for a question id: the 200-task run, a campaign wave, earlier answers, or the one-time import."""
    def label(qid):
        if qid in member:
            return member[qid]
        return "before the 200-task run" if qid in deposited else "imported (0.11 records)"
    return label


RUN_ORDER = ["imported (0.11 records)", "before the 200-task run", "200-task run", "wave 1", "wave 2", "wave 3"]


# ----------------------------------------------------------------------------------------------- sources

def gather_sources(findings, notes):
    src = {}

    def entry(key):
        return src.setdefault(key, {"key": key, "findings": [], "notes": 0, "cited": collections.Counter(),
                                    "read": collections.Counter(), "titles": collections.Counter(),
                                    "polymers": set(), "questions": set()})
    for f in findings:
        e = entry(f["key"])
        e["findings"].append(f)
        if (f["source_url"] or "").strip():
            e["cited"][f["source_url"].strip()] += 1
        if (f["source_title"] or "").strip():
            e["titles"][f["source_title"].strip()] += 1
        if f["subject"]:
            e["polymers"].add(f["subject"])
        e["questions"].add(f["question_id"])
    for n in notes:
        e = entry(n["key"])
        e["notes"] += 1
        if (n["url"] or "").strip():
            e["cited"][n["url"].strip()] += 1
        if (n["read_url"] or "").strip():
            e["read"][n["read_url"].strip()] += 1
        if (n["title"] or "").strip():
            e["titles"][n["title"].strip()] += 1
        e["questions"].add(n["question_id"])
    src.pop("", None)
    return src


def build_sources(findings, notes):
    src = gather_sources(findings, notes)
    cited_hosts_all = {host_of(u) for f in findings for u in [f["source_url"]]} | {host_of(n["url"]) for n in notes}
    cited_hosts_all.discard("")
    rows = []
    for key in sorted(src):
        e = src[key]
        doi = key[4:] if key.startswith("doi:") else None
        doi_hosts = ("doi.org", "dx.doi.org")
        cited = [host_of(u) for u, _ in e["cited"].most_common()]
        hosts = list(dict.fromkeys(h for h in cited if h and h not in doi_hosts))
        read_hosts = list(dict.fromkeys(h for h in (host_of(u) for u, _ in e["read"].most_common()) if h and h not in doi_hosts))
        host = hosts[0] if hosts else (read_hosts[0] if read_hosts else ("doi.org" if doi else ""))
        hosts_for_rules = hosts or read_hosts or ([host] if host else [])
        urls = [u for u, _ in e["cited"].most_common()] + [u for u, _ in e["read"].most_common()]
        url = next((u for u, _ in e["cited"].most_common() if host_of(u) not in doi_hosts), None) or \
            (e["cited"].most_common(1)[0][0] if e["cited"] else None)
        read_url = e["read"].most_common(1)[0][0] if e["read"] else None
        title = e["titles"].most_common(1)[0][0] if e["titles"] else None
        cr = crossref_record(doi) if doi else {"crossrefStatus": "no DOI"}
        stype, rule = classify(doi, hosts_for_rules, urls, title or cr.get("crossrefTitle") or "", cr)
        is_open, basis = open_access(set(hosts) | set(read_hosts), urls, cr, stype)
        row = {"key": key, "doi": doi, "hasDoi": bool(doi), "title": title, "url": url,
               "readUrl": read_url if read_url and read_url != url else None, "host": host,
               "type": stype, "typeRule": rule, "yieldedFindings": bool(e["findings"]), "findings": len(e["findings"]),
               "findingsByStatus": by_status(e["findings"]), "notes": e["notes"], "polymers": len(e["polymers"]),
               "questions": len(e["questions"]), "crossrefStatus": cr.get("crossrefStatus"),
               "year": cr.get("year"), "publisher": cr.get("publisher"), "publisherGroup": publisher_group(cr.get("publisher")),
               "containerTitle": cr.get("containerTitle"), "crossrefType": cr.get("crossrefType"),
               "crossrefTitle": cr.get("crossrefTitle"), "licenseUrls": cr.get("licenseUrls") or [],
               "openAccess": is_open, "openAccessBasis": basis,
               "doiTitleCheck": doi_title_check(title, cr.get("crossrefTitle")) if doi and cr.get("crossrefStatus") == "found"
               else ("DOI not in Crossref" if doi else None)}
        rows.append(row)

    def table(rows_, key_fn, top=None):
        groups = collections.defaultdict(list)
        for r in rows_:
            k = key_fn(r)
            if k is not None:
                groups[k].append(r)
        out = [{"name": k, "sources": len(v), "withDoi": sum(r["hasDoi"] for r in v),
                "yieldedFindings": sum(r["yieldedFindings"] for r in v), "findings": sum(r["findings"] for r in v),
                "notes": sum(r["notes"] for r in v), "openAccess": sum(r["openAccess"] for r in v),
                "types": dict(collections.Counter(r["type"] for r in v).most_common())}
               for k, v in groups.items()]
        out.sort(key=lambda g: (-g["sources"], -g["findings"], str(g["name"])))
        return out[:top] if top else out

    by_type = {t["name"]: t for t in table(rows, lambda r: r["type"])}
    by_type = [by_type.get(t, {"name": t, "sources": 0, "withDoi": 0, "yieldedFindings": 0, "findings": 0, "notes": 0,
                               "openAccess": 0, "types": {}}) for t in TYPES]
    for t in by_type:
        t.pop("types", None)
    by_rule = dict(sorted(collections.Counter(r["typeRule"] for r in rows).items()))
    years = collections.Counter(r["year"] for r in rows if r["year"])
    year_rows = [{"year": y, "sources": years[y],
                  "yieldedFindings": sum(1 for r in rows if r["year"] == y and r["yieldedFindings"]),
                  "findings": sum(r["findings"] for r in rows if r["year"] == y)} for y in sorted(years)]
    decades = collections.Counter((r["year"] // 10) * 10 for r in rows if r["year"])
    pubs = table([r for r in rows if r["publisherGroup"]], lambda r: r["publisherGroup"], top=25)
    for p in pubs:
        p["crossrefNames"] = sorted({r["publisher"] for r in rows if r["publisherGroup"] == p["name"]})
        p.pop("types", None)
    oa_basis = collections.Counter(b for r in rows for b in r["openAccessBasis"])
    per_source = [r["findings"] for r in rows]
    bins = [("0", 0, 0), ("1", 1, 1), ("2-4", 2, 4), ("5-9", 5, 9), ("10-19", 10, 19), ("20-49", 20, 49), ("50+", 50, 10 ** 9)]
    yielded = [r for r in rows if r["yieldedFindings"]]

    def oa_block(subset):
        return {"sources": len(subset), "openAccess": sum(r["openAccess"] for r in subset),
                "share": share(sum(r["openAccess"] for r in subset), len(subset)),
                "findingsFromOpenSources": sum(r["findings"] for r in subset if r["openAccess"]),
                "findings": sum(r["findings"] for r in subset)}
    summary = {
        "sources": len(rows), "withDoi": sum(r["hasDoi"] for r in rows), "withoutDoi": sum(not r["hasDoi"] for r in rows),
        "yieldedFindings": len(yielded), "readWithoutFindings": len(rows) - len(yielded),
        "readWithoutFindingsWithNote": sum(1 for r in rows if not r["yieldedFindings"] and r["notes"]),
        "yieldedFindingsWithoutNote": sum(1 for r in rows if r["yieldedFindings"] and not r["notes"]),
        "hostsOfCitedUrls": len(cited_hosts_all),
        "hostsOfCitedUrlsExcludingDoiOrg": len(cited_hosts_all - {"doi.org", "dx.doi.org"}),
        "hostsIncludingReadUrls": len((cited_hosts_all | {host_of(n["read_url"]) for n in notes}) - {""}),
        "primaryHosts": len({r["host"] for r in rows if r["host"]}),
        "crossref": dict(collections.Counter(r["crossrefStatus"] for r in rows if r["hasDoi"])),
        "crossrefTypes": dict(collections.Counter(r["crossrefType"] for r in rows if r["crossrefType"]).most_common()),
        "findingsPerSource": {"median": median(per_source), "medianOfYielding": median([r["findings"] for r in yielded]),
                              "mean": round(sum(per_source) / len(per_source), 2), "max": max(per_source),
                              "histogram": [{"findings": name, "sources": sum(1 for v in per_source if lo <= v <= hi)}
                                            for name, lo, hi in bins]},
        "notesPerSource": {"median": median([r["notes"] for r in rows]), "max": max(r["notes"] for r in rows)},
        "yearRange": [min(years), max(years)] if years else None, "medianYear": median([r["year"] for r in rows if r["year"]]),
        "sourcesWithYear": sum(years.values()),
        "doiTitleCheck": dict(collections.Counter(r["doiTitleCheck"] for r in rows if r["hasDoi"]).most_common()),
    }
    out = {
        "about": "One row per distinct source key (a DOI and its doi.org URL are one source) over findings and source notes "
                 "of K3. Types from the rules in SUMMARY.md; Crossref metadata for DOIs; openAccess is a rough indicator "
                 "(PubMed Central copy, open-access publisher, Creative Commons licence on the version of record, or "
                 "preprint server).",
        "summary": summary,
        "byType": by_type,
        "byTypeRule": by_rule,
        "byHost": table(rows, lambda r: r["host"] or None, top=25),
        "byPublisher": pubs,
        "publicationYear": year_rows,
        "publicationDecade": [{"decade": d, "sources": decades[d]} for d in sorted(decades)],
        "openAccess": {"all": oa_block(rows), "withDoi": oa_block([r for r in rows if r["hasDoi"]]),
                       "journalArticles": oa_block([r for r in rows if r["type"] == "journal article"]),
                       "yieldedFindings": oa_block(yielded),
                       "byBasis": dict(oa_basis.most_common()),
                       "byType": {t: oa_block([r for r in rows if r["type"] == t]) for t in TYPES}},
        "doiProblems": {"about": "DOIs Crossref does not know, and DOIs whose Crossref title does not match the title the "
                                 "researcher recorded (token containment < 0.6; citation-style titles not compared). Either "
                                 "may be a wrong DOI in the record or a DOI registered elsewhere (DataCite, JaLC, CNKI).",
                        "rows": [{k: r[k] for k in ("doi", "title", "crossrefTitle", "host", "findings", "notes", "doiTitleCheck")}
                                 for r in rows if r["doiTitleCheck"] in ("mismatch", "DOI not in Crossref")]},
        "topSourcesByFindings": [{k: r[k] for k in ("key", "title", "type", "findings", "notes", "polymers")}
                                 for r in sorted(rows, key=lambda r: (-r["findings"], r["key"]))[:15]],
        "rows": rows,
    }
    return out


# ----------------------------------------------------------------------------------------------- growth

def build_growth(findings, notes, deposits, member, runs, qmeta):
    deposited = {d["question_id"] for d in deposits}
    f_by_q, n_by_q = collections.defaultdict(list), collections.defaultdict(list)
    for f in findings:
        f_by_q[f["question_id"]].append(f)
    for n in notes:
        n_by_q[n["question_id"]].append(n)
    label = run_of(member, deposited)
    status = collections.Counter()
    sources, doi_sources, polymers = set(), set(), set()
    n_notes = 0

    def add(fs, ns):
        nonlocal n_notes
        for f in fs:
            status[f["statusLabel"]] += 1
            if f["key"]:
                sources.add(f["key"])
                if f["key"].startswith("doi:"):
                    doi_sources.add(f["key"])
            if f["subject"]:
                polymers.add(f["subject"])
        for n in ns:
            n_notes += 1
            if n["key"]:
                sources.add(n["key"])
                if n["key"].startswith("doi:"):
                    doi_sources.add(n["key"])

    def point(i, **extra):
        return dict(answer=i, **extra, findings=dict(**{s: status.get(s, 0) for s in STATUS_ORDER}, total=sum(status.values())),
                    notes=n_notes, sources=len(sources), sourcesWithDoi=len(doi_sources), polymers=len(polymers))

    imported_f = [f for f in findings if f["question_id"] not in deposited]
    imported_n = [n for n in notes if n["question_id"] not in deposited]
    add(imported_f, imported_n)
    points = [point(0, questionId=None, depositedAt=None, run="imported (0.11 records)", origin="import", engine=None,
                    model=None, promptVersion=None, newFindings=len(imported_f), newNotes=len(imported_n))]
    for i, d in enumerate(deposits, 1):
        qid = d["question_id"]
        add(f_by_q[qid], n_by_q[qid])
        m = qmeta.get(qid, {})
        points.append(point(i, questionId=qid, depositedAt=d["deposited_at"], run=label(qid), origin=d["origin"],
                            engine=m.get("engine") or d["engine"], model=m.get("model"), promptVersion=m.get("promptVersion"),
                            newFindings=len(f_by_q[qid]), newNotes=len(n_by_q[qid])))
    markers = []
    for name in ["before the 200-task run", "200-task run", "wave 1", "wave 2", "wave 3"]:
        idx = [p["answer"] for p in points if p["run"] == name]
        if idx:
            markers.append({"kind": "run start", "label": name + " starts", "run": name, "answer": min(idx),
                            "afterAnswers": min(idx) - 1, "lastAnswer": max(idx), "answers": len(idx),
                            "startedAt": (runs.get(name) or {}).get("startedAt") or points[min(idx)]["depositedAt"],
                            "finishedAt": (runs.get(name) or {}).get("finishedAt") or points[max(idx)]["depositedAt"]})
    prev = "unset"
    for p in points[1:]:
        if p["promptVersion"] and p["promptVersion"] != prev:
            markers.append({"kind": "prompt version", "label": "prompt %s" % p["promptVersion"], "answer": p["answer"],
                            "afterAnswers": p["answer"] - 1, "promptVersion": p["promptVersion"], "at": p["depositedAt"]})
            prev = p["promptVersion"]
    prev = None
    for p in points[1:]:
        if p["engine"] == "codex" and p["model"]:
            if prev and p["model"] != prev:
                markers.append({"kind": "model change", "label": "Codex %s → %s" % (prev, p["model"]), "answer": p["answer"],
                                "afterAnswers": p["answer"] - 1, "from": prev, "to": p["model"], "at": p["depositedAt"]})
            prev = p["model"]
    markers.sort(key=lambda m: (m["answer"], m["kind"]))
    by_run = []
    for name in RUN_ORDER:
        sel = [p for p in points if p["run"] == name]
        if not sel:
            continue
        by_run.append({"run": name, "answers": len(sel) if name != RUN_ORDER[0] else 0,
                       "firstAnswer": sel[0]["answer"], "lastAnswer": sel[-1]["answer"],
                       "newFindings": sum(p["newFindings"] for p in sel), "newNotes": sum(p["newNotes"] for p in sel),
                       "answersWithFindings": sum(1 for p in sel if p["newFindings"] and p["questionId"]),
                       "engines": dict(collections.Counter("%s %s" % (p["engine"], p["model"]) for p in sel if p["questionId"])),
                       "promptVersions": dict(collections.Counter(p["promptVersion"] or "unversioned" for p in sel if p["questionId"])),
                       "endState": {k: sel[-1][k] for k in ("findings", "notes", "sources", "sourcesWithDoi", "polymers")}})
    return {
        "about": "Answers in deposit order (deposits.deposited_at of K3). Point 0 holds the findings and notes imported "
                 "once from the retired 0.11 records. After each answer: cumulative findings by their final status, "
                 "source notes, distinct sources (source key over findings and notes), sources with a DOI, and graph "
                 "polymers with at least one finding (final polymer id).",
        "runs": {k: v for k, v in runs.items()},
        "byRun": by_run,
        "markers": markers,
        "points": points,
    }


# ----------------------------------------------------------------------------------------------- coverage

CLASS_ORDER = ["commodity thermoplastic", "engineering thermoplastic", "high performance polymer", "elastomer",
               "thermoplastic elastomer", "thermoset", "fiber and textile", "natural and semisynthetic",
               "biodegradable and biomedical", "water soluble and hydrogel", "functional and specialty"]


def build_coverage(findings, notes, polymers):
    f_by_p = collections.defaultdict(list)
    for f in findings:
        if f["subject"]:
            f_by_p[f["subject"]].append(f)
    notes_by_key = collections.Counter(n["key"] for n in notes)
    unknown = sorted(set(f_by_p) - set(polymers))
    rows = []
    for pid, p in polymers.items():
        fs = f_by_p.get(pid, [])
        keys = {f["key"] for f in fs if f["key"]}
        rows.append({"id": pid, "label": p["label"], "entryKind": p["entryKind"], "class": p["class"],
                     "marketTier": p["marketTier"], "broader": p["broader"], "narrower": p["narrower"],
                     "findings": len(fs), "findingsByStatus": by_status(fs), "sources": len(keys),
                     "sourcesWithDoi": sum(1 for k in keys if k.startswith("doi:")),
                     "notes": sum(notes_by_key[k] for k in keys),
                     "questions": len({f["question_id"] for f in fs})})
    order = {c: i for i, c in enumerate(CLASS_ORDER)}
    rows.sort(key=lambda r: (order.get(r["class"], 99), -r["findings"], r["label"]))
    classes = []
    for c in CLASS_ORDER + sorted({r["class"] for r in rows} - set(CLASS_ORDER), key=str):
        sel = [r for r in rows if r["class"] == c]
        if not sel:
            continue
        classes.append({"class": c, "polymers": len(sel), "withFindings": sum(1 for r in sel if r["findings"]),
                        "atLeast10": sum(1 for r in sel if r["findings"] >= 10),
                        "atLeast50": sum(1 for r in sel if r["findings"] >= 50),
                        "findings": sum(r["findings"] for r in sel),
                        "findingsByStatus": {s: sum(r["findingsByStatus"][s] for r in sel) for s in STATUS_ORDER},
                        "medianFindingsOfCovered": median([r["findings"] for r in sel if r["findings"]])})
    no_id = [f for f in findings if not f["subject"]]
    counts = [r["findings"] for r in rows]
    top_share = sorted(counts, reverse=True)
    with_id = sum(counts)
    summary = {
        "polymers": len(rows), "withFindings": sum(1 for c in counts if c >= 1), "atLeast10": sum(1 for c in counts if c >= 10),
        "atLeast50": sum(1 for c in counts if c >= 50), "atLeast100": sum(1 for c in counts if c >= 100),
        "findingsWithPolymerId": with_id, "findingsWithoutPolymerId": len(no_id),
        "shareWithoutPolymerId": share(len(no_id), len(findings)),
        "subjectsNotInGraph": unknown,
        "byEntryKind": {k: {"polymers": sum(1 for r in rows if r["entryKind"] == k),
                            "withFindings": sum(1 for r in rows if r["entryKind"] == k and r["findings"]),
                            "findings": sum(r["findings"] for r in rows if r["entryKind"] == k)}
                        for k in sorted({r["entryKind"] for r in rows}, key=str)},
        "medianFindingsOfCovered": median([c for c in counts if c]),
        "maxFindings": max(counts), "top10ShareOfFindingsWithId": share(sum(top_share[:10]), with_id),
        "top40ShareOfFindingsWithId": share(sum(top_share[:40]), with_id),
    }
    return {
        "about": "All graph polymers of release %s with findings filed under them in K3 (findings.subject). Class is the "
                 "graph's primaryClass facet (one per polymer; marked browsingOnly in the graph). sources: distinct "
                 "source keys of the polymer's findings; notes: source notes whose source is one of those; questions: "
                 "distinct questions that saved a finding on the polymer. Sorted by class, then findings." % RELEASE_ID,
        "classAxis": "primaryClass", "classOrder": CLASS_ORDER,
        "summary": summary, "classes": classes,
        "withoutPolymerId": {"findings": len(no_id), "byStatus": by_status(no_id),
                             "topMaterials": [{"material": m, "findings": n} for m, n in
                                              collections.Counter((f["material"] or "").strip() for f in no_id).most_common(15)]},
        "polymers": rows,
    }


# ----------------------------------------------------------------------------------------------- completeness

NUMBER = re.compile(r"^\s*[<>≤≥~≈]?\s*[-−+]?\d+(?:[.,]\d+)?(?:\s*[eE]\s*[-−+]?\d+|\s*[×x]\s*10\^?[-−]?\d+)?\s*$")
REASON_RULES = [
    ("no reason recorded", None),
    ("source blocked (HTTP 4xx, login, browser challenge, paywall)",
     re.compile(r"\b40[0-9]\b|forbidden|log ?in|sign[- ]in|paywall|subscription|challenge|captcha|verification|blocked|bot[- ]check|"
                r"access (was )?denied|access errors?|redirect", re.I)),
    ("file unreadable (compressed, binary, scanned or image-only)",
     re.compile(r"compress|binary|scanned|image-only|no text layer|extract|unreadable|too large|garbled|empty", re.I)),
    ("value only in a figure the reviewer could not read",
     re.compile(r"\bimage\b|only in (the )?fig|from (the )?fig|read from a fig|fig(ure)?\.? ?\S{0,6} (plot|graph|curve)", re.I)),
    ("only an abstract or snippet available", re.compile(r"abstract|snippet|search-engine|indexed excerpt|summary", re.I)),
    ("source could not be opened (other)",
     re.compile(r"could ?n[o']t (be )?(open|read|access|load|retriev|reach|check|confirm|verif)|unable to|inaccessible|"
                r"not (be )?accessible|failed|timed? ?out|no accessible|none of the copies|wouldn't|returned errors|"
                r"prevent", re.I)),
    ("value or condition contradicted by the source",
     re.compile(r"contradict|differs?\b|instead|mismatch|inconsistent|incorrect|wrong|rather than|does not match|"
                r"doesn't match|not match", re.I)),
    ("detail not stated in the source",
     re.compile(r"not (explicitly )?(specif|state|report|establish|given|mention|found|locat|identif|show|appear|includ)|"
                r"does(n't| not) (explicitly )?(specify|state|report|give|mention|show|include|say)|never says|"
                r"includes no|no .{0,40}(given|stated|reported)", re.I)),
    ("other", re.compile(r".", re.S)),
]
ACCESS_CATEGORIES = {REASON_RULES[i][0] for i in (1, 2, 3, 4, 5)}
# The save step's own flag (retired with prompt 002364de): an excerpt that does not show the value went to review.
AUTO_EXCERPT_FLAG = "The excerpt does not show the reported value"


def reason_category(text):
    text = (text or "").strip()
    if not text:
        return REASON_RULES[0][0]
    for name, pattern in REASON_RULES[1:]:
        if pattern.search(text):
            return name
    return "other"


def build_completeness(findings, label):
    n = len(findings)

    def present(field):
        return lambda f: bool((f[field] or "").strip())
    checks = {
        "statement": present("statement"), "material": present("material"), "property": present("property"),
        "value": present("value"),
        "numericValue": lambda f: bool(re.search(r"\d", f["value"] or "")),
        "singleNumberValue": lambda f: bool(NUMBER.match(f["value"] or "")),
        "unit": present("unit"), "conditions": present("conditions"), "locator": present("locator"),
        "excerpt": present("excerpt"), "polymerId": present("subject"), "sourceDoi": lambda f: bool(f["key"].startswith("doi:")),
        "sourceUrl": present("source_url"), "sourceTitle": present("source_title"),
    }

    def fields(subset):
        m = len(subset)
        return {k: {"count": sum(1 for f in subset if fn(f)), "share": share(sum(1 for f in subset if fn(f)), m)}
                for k, fn in checks.items()}
    runs = [r for r in RUN_ORDER if any(label(f["question_id"]) == r for f in findings)]
    campaign = {"wave 1", "wave 2", "wave 3"}

    def crosstab(subset, key):
        table = collections.defaultdict(collections.Counter)
        for f in subset:
            table[key(f)][f["statusLabel"]] += 1
        return {k: {**{s: v.get(s, 0) for s in STATUS_ORDER}, "total": sum(v.values())} for k, v in sorted(table.items())}

    spot = [f for f in findings if "spotCheck" in f["detail"]]
    flagged = [f for f in findings if f["detail"].get("needsReview") is True]
    automatic = [f for f in flagged if f["detail"].get("reviewFlag") == AUTO_EXCERPT_FLAG]
    unflagged = [f for f in findings if f["detail"].get("needsReview") is False]
    reasons = {}
    examples = []
    for status, wanted in (("Rejected", 4), ("Needs checking", 6)):
        sel = [f for f in findings if f["statusLabel"] == status]
        cats = collections.Counter(reason_category(f["review_reason"]) for f in sel)
        reasons[status] = {"findings": len(sel), "categories": dict(cats.most_common()),
                           "accessProblems": sum(v for k, v in cats.items() if k in ACCESS_CATEGORIES),
                           "byReviewer": dict(collections.Counter(f["reviewer_engine"] or "none" for f in sel).most_common())}
        rng = random.Random(20261013)
        picked = 0
        for cat, _ in cats.most_common():
            pool = sorted({(f["review_reason"] or "").strip() for f in sel if reason_category(f["review_reason"]) == cat} - {""},
                          key=len)
            pool = [r for r in pool if len(r) <= 220] or pool[:1]
            if not pool or picked >= wanted:
                continue
            text = rng.choice(pool[: max(1, len(pool) // 2)])
            examples.append({"status": status, "category": cat, "reason": text if len(text) <= 220 else text[:217] + "..."})
            picked += 1
        while picked < wanted:
            pool = sorted({(f["review_reason"] or "").strip() for f in sel} - {""} - {e["reason"] for e in examples},
                          key=lambda reason: (len(reason), reason))  # ties broken by text, not hash order
            pool = [r for r in pool if len(r) <= 220]
            if not pool:
                break
            text = rng.choice(pool)
            examples.append({"status": status, "category": reason_category(text), "reason": text})
            picked += 1
    return {
        "about": "Field presence over the findings of K3 (presence only; no excerpt text). numericValue: the value contains a "
                 "digit; singleNumberValue: the value is one number. Spot checks: findings the researcher did not flag and "
                 "the reviewer sampled (detail.spotCheck), by final status. Flagged: detail.needsReview true, either by the researcher "
                 "or by the save step's automatic excerpt check (reviewFlag 'The excerpt does not show the reported value', "
                 "removed after the campaign). Campaign = "
                 "waves 1-3. Review reasons categorised by keyword rules (first match in the listed order).",
        "findings": n,
        "fields": fields(findings),
        "fieldsByRun": {r: dict(findings=sum(1 for f in findings if label(f["question_id"]) == r),
                                **{k: v["share"] for k, v in fields([f for f in findings if label(f["question_id"]) == r]).items()})
                        for r in runs},
        "fieldsByStatus": {s: {k: v["share"] for k, v in fields([f for f in findings if f["statusLabel"] == s]).items()}
                           for s in STATUS_ORDER},
        "statusMix": {s: {"count": c, "share": share(c, n)} for s, c in by_status(findings).items()},
        "statusMixByRun": {r: by_status([f for f in findings if label(f["question_id"]) == r]) for r in runs},
        "flagged": {"needsReviewTrue": len(flagged), "automaticExcerptFlag": len(automatic),
                    "researcherFlag": len(flagged) - len(automatic), "needsReviewFalse": len(unflagged),
                    "noFlagRecorded": n - len(flagged) - len(unflagged),
                    "flaggedShare": share(len(flagged), len(flagged) + len(unflagged)),
                    "flaggedShareByRun": {r: share(sum(1 for f in flagged if label(f["question_id"]) == r),
                                                   sum(1 for f in flagged + unflagged if label(f["question_id"]) == r)) for r in runs},
                    "researcherFlagShareByRun": {r: share(sum(1 for f in flagged if label(f["question_id"]) == r
                                                              and f["detail"].get("reviewFlag") != AUTO_EXCERPT_FLAG),
                                                          sum(1 for f in flagged + unflagged if label(f["question_id"]) == r))
                                                 for r in runs},
                    "automaticOutcomes": by_status(automatic)},
        "spotChecksOfAdded": {
            "about": "Rows: the spot-check outcome recorded on the finding; columns: its final status.",
            "all": crosstab(spot, lambda f: f["detail"]["spotCheck"]),
            "campaign": crosstab([f for f in spot if label(f["question_id"]) in campaign], lambda f: f["detail"]["spotCheck"]),
            "byRun": {r: crosstab([f for f in spot if label(f["question_id"]) == r], lambda f: f["detail"]["spotCheck"]) for r in runs},
            "sampledShareOfUnflagged": share(len(spot), len(unflagged)),
        },
        "flaggedOutcomes": {
            "about": "Findings the researcher flagged (needsReview true), by final status.",
            "all": by_status(flagged),
            "campaign": by_status([f for f in flagged if label(f["question_id"]) in campaign]),
            "byRun": {r: by_status([f for f in flagged if label(f["question_id"]) == r]) for r in runs},
            "byReviewer": crosstab(flagged, lambda f: f["reviewer_engine"] or "none"),
        },
        "reviewReasons": {"rules": [name for name, _ in REASON_RULES], "accessCategories": sorted(ACCESS_CATEGORIES),
                          **reasons, "examples": examples},
    }


# ----------------------------------------------------------------------------------------------- summary

TYPE_RULES_TEXT = """\
First rule that fires wins. Host lists were curated from the hosts present in K3 (rules, not a model); counts per
rule are in `sources.json` -> `byTypeRule`.

A. DOIs, typed first by the DOI itself and then by the Crossref record:
- A0 DOI of an encyclopedia entry (Ullmann's 10.1002/14356007, Kirk-Othmer, Encyclopedia of Polymer Science and
  Technology) -> book/chapter.
- A1 (DOI found in Crossref) DOI prefix of a preprint server (10.26434 ChemRxiv, 10.48550 arXiv, 10.1101
  bioRxiv/medRxiv, 10.20944 Preprints.org, 10.21203 Research Square, 10.2139 SSRN, 10.31224 OSF, 10.22541 Authorea)
  -> preprint.
- A2 (DOI found in Crossref) Crossref type: journal-article, proceedings-article, journal-issue/volume -> journal
  article (conference papers are counted as articles); book, book-chapter, monograph, edited-book,
  reference-book/entry, book-part/section/series/set/track -> book/chapter; dissertation -> thesis; standard ->
  standard; report, report-component/series -> government/report; posted-content -> preprint. Other Crossref types
  (dataset, component, peer-review, other) fall through to group B.

B. URL-only sources, and DOIs Crossref does not know or types as "other" (judged on the cited hosts, all cited and
read URLs, and the recorded title):
- B1 preprint DOI prefix (as A1) -> preprint. B2 data-repository DOI prefix (Zenodo, figshare, Mendeley Data) -> other
  web; thesis-repository DOI prefix (10.6100 TU Eindhoven) -> thesis.
- B3 patent host (Google Patents, Justia, FreePatentsOnline, EPO publication server, Espacenet, Patentscope, PatSnap,
  USPTO, TREA), a /patent/ path, or a patent number or the word "patent" in the title -> patent.
- B4 standards host (ASTM, ISO, iTeh, DIN/Beuth, BSI, ANSI, IEC, SAE, pdfstandards) or a standard designation in the
  title ("Standard Test Method/Specification/Practice/Guide", or a title starting "ASTM D570", "ISO 1183",
  "Defence Standard 00-35") -> standard.
- B5 preprint-server host (arXiv, ChemRxiv, bioRxiv, Preprints.org, Research Square, SSRN, ...) -> preprint.
- B6 thesis host (ETD and e-theses servers, national thesis archives, VTechWorks) or a thesis cue in title or URL
  (thesis, dissertation, PhD, doctoral, master's, /etd/, etheses, tesis) -> thesis.
- B7 publisher, journal or article-aggregator host (PMC, PubMed, ScienceDirect, Wiley, ACS, RSC, Springer, Nature,
  MDPI, Frontiers, Taylor & Francis, SAGE, IOP, PLOS, Hindawi, SciELO, J-STAGE, CiNii, Semantic Scholar,
  ResearchGate, CORE, CiteSeerX, NSF-PAR, and about 40 small journals and proceedings hosts by name) -> journal
  article.
- B8 government or national-laboratory host (.gov, .mil, .europa.eu, .gc.ca, NASA NTRS, OSTI, NIST, EPA, ORNL, VTT;
  NCBI and NSF-PAR excluded, they host articles; NIST's Journal of Research path excluded) -> government/report.
- B9 book host (Google Books, publisher book excerpts, e-book mirrors) or a handbook/encyclopedia/compendium/chapter
  cue without a data-sheet cue or manufacturer host -> book/chapter.
- B10 manufacturer, distributor, materials-database or instrument-maker host (BASF, DuPont, Solvay, Celanese,
  Covestro, SABIC, Kuraray, Ensinger, MCAM, Toray, Teijin, Unitika, Kraton, Chemours/Teflon/Viton, plastics
  distributors and resellers, MatWeb/Material Data Center/SpecialChem/CAMPUS, NETZSCH, TA Instruments, Shimadzu,
  Hitachi, Intertek, about 170 hosts) -> technical data sheet/manufacturer (instrument application notes and
  test-lab pages are counted here).
- B11 academic or institutional repository host or path without a thesis cue (eprints, pure, DSpace, DiVA,
  handle/bitstream paths, .edu, .ac.xx and university hosts) -> journal article (a repository copy is
  assumed to be a paper).
- B12 data-sheet cue in title or URL (data sheet, TDS, technical data/information/guide, product
  information/brochure, design or processing guide, application note, /datasheets/, /products/, /grades/) or a
  trademark symbol (® or ™) in the title -> technical data sheet/manufacturer.
- B13 report cue in title or URL (technical report, NISTIR, SAND number, annual report) -> government/report.
- B14 article cue in the URL or title (journal, /article/, /ojs/, /doi/, /publications/, /papers/, proceedings,
  conference, /vol...) -> journal article.
- B15 a DOI with no usable Crossref type -> journal article.
- B16 anything else -> other web (document mirrors such as Scribd, SlideShare, doczz or pdfcoffee, wikis, trade
  magazines, lab home pages)."""


def fmt(n):
    return "{:,}".format(n) if isinstance(n, int) else str(n)


def pct(x, digits=1):
    return "—" if x is None else ("%." + str(digits) + "f%%") % (100 * x)


def write_summary(growth, coverage, sources, completeness, findings, notes, deposits, reviews, failed):
    cs, ss = coverage["summary"], sources["summary"]
    status = by_status(findings)
    end = growth["points"][-1]
    fields = completeness["fields"]
    spot_c = completeness["spotChecksOfAdded"]["campaign"]
    spot_a = completeness["spotChecksOfAdded"]["all"]
    flag_c = completeness["flaggedOutcomes"]["campaign"]
    flag_a = completeness["flaggedOutcomes"]["all"]

    def spot_count(table, outcome, status_=None):
        row = table.get(outcome, {})
        return row.get("total", 0) if status_ is None else row.get(status_, 0)

    L = []
    w = L.append
    w("# Figure 3 dataset: the knowledge base as a polymer dataset")
    w("")
    w("Built by `build.py` (standard library only) on %s from the frozen store K3 (knowledge snapshot `%s`), graph "
      "release `%s`, the question records, and the records of the 200-task run and the campaign. All inputs were "
      "opened read-only; the only network use was Crossref's public REST API, one request per DOI, no contact "
      "details sent, cached under `cache/crossref/`." % (dt.date.today().isoformat(), SNAPSHOT_ID, RELEASE_ID))
    w("")
    w("## Headline numbers")
    w("")
    w("- **%s findings** from **%s answers with deposits** (plus %d findings and %d notes imported once from the 0.11 "
      "records): %s Reviewed, %s Added, %s Needs checking, %s Rejected." % (
          fmt(len(findings)), fmt(len(deposits)), growth["points"][0]["newFindings"], growth["points"][0]["newNotes"],
          fmt(status["Reviewed"]), fmt(status["Added"]), fmt(status["Needs checking"]), fmt(status["Rejected"])))
    w("- **%s source notes**, **%s distinct sources** (%s with a DOI, %s URL only); %s yielded findings and %s were read "
      "without yielding any (known only from a source note); %s." % (
          fmt(len(notes)), fmt(ss["sources"]), fmt(ss["withDoi"]), fmt(ss["withoutDoi"]), fmt(ss["yieldedFindings"]),
          fmt(ss["readWithoutFindings"]), "every source with findings also has a source note"
          if not ss["yieldedFindingsWithoutNote"] else "%s sources with findings have no source note" % fmt(ss["yieldedFindingsWithoutNote"])))
    w("- Hosts: %s distinct hosts in the cited URLs (%s without doi.org); %s distinct primary hosts, one per source." % (
        fmt(ss["hostsOfCitedUrls"]), fmt(ss["hostsOfCitedUrlsExcludingDoiOrg"]), fmt(ss["primaryHosts"])))
    w("- **%s of %s graph polymers** have findings; %s have ≥ 10 and %s ≥ 50 (%s ≥ 100). %s findings (%s) have no "
      "polymer id." % (fmt(cs["withFindings"]), fmt(cs["polymers"]), fmt(cs["atLeast10"]), fmt(cs["atLeast50"]),
                        fmt(cs["atLeast100"]), fmt(cs["findingsWithoutPolymerId"]), pct(cs["shareWithoutPolymerId"])))
    w("- %s reviewer calls in the reviews table (%s)." % (fmt(len(reviews)), ", ".join(
        "%s %s" % (fmt(v), k) for k, v in collections.Counter(r["status"] for r in reviews).most_common())))
    w("")
    w("## Growth (growth.json)")
    w("")
    w("| Segment | Answers | Answer index | New findings | New notes | Engine/model | Prompt | Store at end: findings / notes / sources / polymers |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in growth["byRun"]:
        e = r["endState"]
        w("| %s | %s | %s–%s | %s | %s | %s | %s | %s / %s / %s / %s |" % (
            r["run"], fmt(r["answers"]), r["firstAnswer"], r["lastAnswer"], fmt(r["newFindings"]), fmt(r["newNotes"]),
            "; ".join("%s ×%d" % (k, v) for k, v in r["engines"].items()) or "—",
            "; ".join("%s ×%d" % (k, v) for k, v in r["promptVersions"].items()) or "—",
            fmt(e["findings"]["total"]), fmt(e["notes"]), fmt(e["sources"]), fmt(e["polymers"])))
    w("")
    w("Markers (answer index = first answer after the change): " + "; ".join(
        "%s at %d" % (m["label"], m["answer"]) for m in growth["markers"]) + ".")
    w("")
    w("## Coverage (coverage.json)")
    w("")
    w("Class axis: the graph's `primaryClass` facet (one class per polymer, 11 classes; the graph marks it browsing-only). "
      "Polymer-level and family-level concepts are both counted; findings are counted on the id they are filed under, "
      "not rolled up to families.")
    w("")
    w("| Class | Polymers | With findings | ≥ 10 | ≥ 50 | Findings |")
    w("| --- | --- | --- | --- | --- | --- |")
    for c in coverage["classes"]:
        w("| %s | %d | %d | %d | %d | %s |" % (c["class"], c["polymers"], c["withFindings"], c["atLeast10"], c["atLeast50"],
                                             fmt(c["findings"])))
    w("")
    w("Median findings per covered polymer %s, maximum %s; the 10 best-covered polymers hold %s and the top 40 %s of "
      "findings with an id." % (cs["medianFindingsOfCovered"], fmt(cs["maxFindings"]), pct(cs["top10ShareOfFindingsWithId"]),
                                 pct(cs["top40ShareOfFindingsWithId"])))
    w("")
    w("## Sources (sources.json)")
    w("")
    w("| Type | Sources | With DOI | Yielded findings | Findings | Notes | Open (rough) |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for t in sources["byType"]:
        w("| %s | %s | %s | %s | %s | %s | %s |" % (t["name"], fmt(t["sources"]), fmt(t["withDoi"]), fmt(t["yieldedFindings"]),
                                                  fmt(t["findings"]), fmt(t["notes"]), fmt(t["openAccess"])))
    w("")
    w("Top hosts (sources): " + ", ".join("%s %d" % (h["name"], h["sources"]) for h in sources["byHost"][:12]) + ".")
    w("")
    w("Top publishers (Crossref, grouped; sources): " + ", ".join("%s %d" % (p["name"], p["sources"]) for p in sources["byPublisher"][:10]) + ".")
    w("")
    oa = sources["openAccess"]
    w("Open access (rough indicator): %s of %s sources (%s); %s of %s DOI sources (%s); %s of %s journal articles (%s). "
      "Basis counts: %s." % (fmt(oa["all"]["openAccess"]), fmt(oa["all"]["sources"]), pct(oa["all"]["share"]),
                            fmt(oa["withDoi"]["openAccess"]), fmt(oa["withDoi"]["sources"]), pct(oa["withDoi"]["share"]),
                            fmt(oa["journalArticles"]["openAccess"]), fmt(oa["journalArticles"]["sources"]),
                            pct(oa["journalArticles"]["share"]), "; ".join("%s %d" % kv for kv in oa["byBasis"].items())))
    w("")
    w("Publication years (Crossref, %s sources): %s–%s, median %s. Crossref lookups: %s. Findings per source: median %s "
      "(%s among sources that yielded findings), mean %s, maximum %s." % (
          fmt(ss["sourcesWithYear"]), *(ss["yearRange"] or ["—", "—"]), ss["medianYear"],
          ", ".join("%s %d" % kv for kv in ss["crossref"].items()), ss["findingsPerSource"]["median"],
          ss["findingsPerSource"]["medianOfYielding"], ss["findingsPerSource"]["mean"], ss["findingsPerSource"]["max"]))
    dp = sources["doiProblems"]["rows"]
    w("")
    w("DOI checks: %s. %d DOIs are unknown to Crossref (%s of them under Crossref-member prefixes 10.1021 or 10.3390, so "
      "probably wrong DOIs in the record: %s; the rest are registered elsewhere, e.g. CNKI, DataCite or JaLC), and %d "
      "recorded titles do not match Crossref's title for their DOI (%s; all on sources with notes only, no findings)." % (
          ", ".join("%s %s" % kv for kv in ss["doiTitleCheck"].items()),
          sum(1 for r in dp if r["doiTitleCheck"] == "DOI not in Crossref"),
          sum(1 for r in dp if r["doiTitleCheck"] == "DOI not in Crossref" and r["doi"].split("/")[0] in ("10.1021", "10.3390")),
          ", ".join("%s (%d findings)" % (r["doi"], r["findings"]) for r in dp
                    if r["doiTitleCheck"] == "DOI not in Crossref" and r["doi"].split("/")[0] in ("10.1021", "10.3390")),
          sum(1 for r in dp if r["doiTitleCheck"] == "mismatch"),
          ", ".join(r["doi"] for r in dp if r["doiTitleCheck"] == "mismatch")))
    if failed:
        w("")
        w("Crossref: %d DOIs could not be fetched on the last run (timeouts or server errors); rerun to retry them." % len(failed))
    w("")
    w("## Record quality (completeness.json)")
    w("")
    w("Field presence: conditions %s, locator %s, excerpt %s (presence only), unit %s, numeric value %s (value holds a digit; "
      "a single number: %s), property %s, polymer id %s, DOI %s." % tuple(pct(fields[k]["share"]) for k in (
          "conditions", "locator", "excerpt", "unit", "numericValue", "singleNumberValue", "property", "polymerId", "sourceDoi")))
    w("")
    w("Spot checks of Added findings (outcome recorded on the finding): all %s — supported %s, uncertain %s, unsupported %s, "
      "failed %s, not assessed %s; campaign only: supported %s, uncertain %s, unsupported %s." % (
          fmt(sum(v["total"] for v in spot_a.values())), *(fmt(spot_count(spot_a, k)) for k in
                                                           ("supported", "uncertain", "unsupported", "failed", "not-assessed")),
          *(fmt(spot_count(spot_c, k)) for k in ("supported", "uncertain", "unsupported"))))
    w("")
    fl = completeness["flagged"]
    w("Flagged findings by final status: all %s; campaign %s. Of the %s flagged, %s were flagged by the save step's "
      "automatic excerpt check (outcomes: %s) and %s by the researcher. Researcher-flagged share by segment: %s." % (
        ", ".join("%s %s" % (k, fmt(v)) for k, v in flag_a.items()), ", ".join("%s %s" % (k, fmt(v)) for k, v in flag_c.items()),
        fmt(fl["needsReviewTrue"]), fmt(fl["automaticExcerptFlag"]),
        ", ".join("%s %s" % (k, fmt(v)) for k, v in fl["automaticOutcomes"].items()), fmt(fl["researcherFlag"]),
        ", ".join("%s %s" % (k, pct(v)) for k, v in fl["researcherFlagShareByRun"].items() if v is not None)))
    w("")
    rr = completeness["reviewReasons"]
    for s in ("Rejected", "Needs checking"):
        w("Review reasons, %s (%d): %s; access problems %d." % (s, rr[s]["findings"], "; ".join(
            "%s %d" % kv for kv in rr[s]["categories"].items()), rr[s]["accessProblems"]))
        w("")
    w("## Source-type rules")
    w("")
    w(TYPE_RULES_TEXT)
    w("")
    w("Open access is rough: a PubMed Central or Europe PMC copy, "
      "a Crossref publisher in a list of fully open publishers (MDPI, Frontiers, PLOS, Hindawi, BMC, Copernicus, PeerJ, "
      "eLife, Beilstein, SciELO, SCIRP, IntechOpen ...) or such a publisher's host for URL-only sources, a Creative "
      "Commons licence URL in Crossref on the version of record (a CC licence on the accepted manuscript only is listed "
      "as a basis but not counted), or a preprint server. Free author copies (ResearchGate, repositories) are not counted.")
    w("")
    w("A check on 2026-10-13 of 60 randomly drawn URL-only sources (seeded) against their titles and URLs agreed with "
      "the assigned type in 59 (one debatable: a DuPont presentation on a university wiki, typed other web). The host "
      "lists were curated on the same data, so this is in-sample agreement, not an independent validation. DOI "
      "sources are typed by Crossref.")
    w("")
    w("## Notes and surprises")
    w("")
    w("- Every expected total is reproduced exactly (table below), including the snapshot cut sizes used by the "
      "scaling run (store after the import and after each segment: %s findings)." % ", ".join(fmt(r["endState"]["findings"]["total"])
                                                                       for r in growth["byRun"]))
    new = {r["run"]: r["newFindings"] for r in growth["byRun"]}
    w("- The campaign plan's results table gives 2,922 and 3,813 new findings for waves 2 and 3; the records (and the "
      "campaign's own report.json) give %s and %s (same total, %s), so the plan's table moves 71 findings between "
      "the two waves." % (fmt(new.get("wave 2", 0)), fmt(new.get("wave 3", 0)),
                           fmt(sum(v for k, v in new.items() if k.startswith("wave")))))
    w("- The plan's flagged share for wave 2 (7.9%%) matches the researcher's own flags (%s), not all flagged findings "
      "(%s), which include the save step's automatic excerpt flag." % (
          pct(completeness["flagged"]["researcherFlagShareByRun"].get("wave 2")),
          pct(completeness["flagged"]["flaggedShareByRun"].get("wave 2"))))
    nc = completeness["reviewReasons"]["Needs checking"]
    w("- A spot-checked Added finding the reviewer found uncertain ends as Needs checking (%s of %s such findings), so "
      "%s of the Needs-checking findings are sampled Added findings rather than flagged ones; %s of %s Needs-checking "
      "reasons are source-access problems (Claude Code reviewed %s of the %s)." % (
          fmt(spot_count(spot_a, "uncertain", "Needs checking")), fmt(spot_count(spot_a, "uncertain")),
          pct(share(spot_count(spot_a, "uncertain", "Needs checking"), nc["findings"])), fmt(nc["accessProblems"]),
          fmt(nc["findings"]), fmt(nc["byReviewer"].get("claude-code", 0)), fmt(nc["findings"])))
    yields = {t_["name"]: share(t_["yieldedFindings"], t_["sources"]) for t_ in sources["byType"]}
    w("- %s of %s sources (%s) were read without yielding a finding. Share of sources that yielded findings: journal "
      "articles %s, patents %s, data sheets/manufacturer documents %s, government/reports %s, theses %s; patents and "
      "data sheets carry %s of all findings." % (
          fmt(ss["readWithoutFindings"]), fmt(ss["sources"]), pct(share(ss["readWithoutFindings"], ss["sources"])),
          pct(yields["journal article"]), pct(yields["patent"]), pct(yields["technical data sheet/manufacturer"]),
          pct(yields["government/report"]), pct(yields["thesis"]),
          pct(share(sum(t_["findings"] for t_ in sources["byType"] if t_["name"] in ("patent", "technical data sheet/manufacturer")),
                    len(findings)))))
    w("")
    w("## Sanity check against the expected numbers")
    w("")
    rows = sanity_rows(growth, coverage, sources, completeness, findings, notes, deposits, reviews)
    w("| Quantity | Expected | Computed | | Note |")
    w("| --- | --- | --- | --- | --- |")
    for name, expected, got, ok, note in rows:
        w("| %s | %s | %s | %s | %s |" % (name, expected, got, "match" if ok else "**differs**", note))
    w("")
    w("## Files")
    w("")
    w("- `growth.json`: one point per answer (0 = import), byRun table, run times, markers.")
    w("- `coverage.json`: all %d graph polymers with class, family links and counts; class table; findings without an id." % cs["polymers"])
    w("- `sources.json`: %s source rows with type, host, Crossref fields and open-access basis; tables by type, rule, "
      "host, publisher, year, decade; open-access blocks; top sources." % fmt(ss["sources"]))
    w("- `completeness.json`: field presence (overall, by run, by status), status mix, spot checks and flagged outcomes "
      "by final status (all, campaign, by run), review-reason categories with %d short examples." % len(rr["examples"]))
    w("- `build.py`: regenerates everything (`--offline` to skip Crossref); `cache/crossref/`: one JSON per DOI.")
    text = "\n".join(L) + "\n"
    if LOCAL_PATH.search(text):
        raise SystemExit("SUMMARY.md would contain a local path; nothing written")
    (OUT / "SUMMARY.md").write_text(text, encoding="utf-8")


def sanity_rows(growth, coverage, sources, completeness, findings, notes, deposits, reviews):
    cs, ss = coverage["summary"], sources["summary"]
    status = by_status(findings)
    fields = completeness["fields"]
    spot_c = completeness["spotChecksOfAdded"]["campaign"]
    flag_c = completeness["flaggedOutcomes"]["campaign"]
    rows = []

    def add(name, expected, got, tolerance=0, note_ok="", note_bad=""):
        ok = abs(got - expected) <= tolerance if isinstance(expected, (int, float)) else expected == got
        rows.append((name, fmt(expected) if not isinstance(expected, float) else pct(expected, 0),
                     fmt(got) if not isinstance(got, float) else pct(got, 1), ok, note_ok if ok else note_bad))
    add("Findings", 8905, len(findings))
    for s, e in (("Added", 5537), ("Reviewed", 2932), ("Needs checking", 429), ("Rejected", 7)):
        add("  " + s, e, status[s])
    add("Source notes", 2195, len(notes))
    add("Answers with deposits", 1063, len(deposits))
    add("Reviews", 742, len(reviews))
    add("Graph polymers", 262, cs["polymers"])
    add("Polymers with ≥ 1 finding", 158, cs["withFindings"])
    add("Polymers with ≥ 10 findings", 143, cs["atLeast10"])
    add("Polymers with ≥ 50 findings", 84, cs["atLeast50"])
    add("Findings without a polymer id", 474, cs["findingsWithoutPolymerId"])
    add("Distinct sources (export: 1,679)", 1679, ss["sources"], tolerance=0, note_bad="expected about 1,680")
    add("Sources with a DOI (about 1,000)", 1000, ss["withDoi"], tolerance=25,
        note_ok="within 'about 1,000'")
    add("Hosts (plan: 369, about 370)", 369, ss["hostsOfCitedUrls"], tolerance=0,
        note_ok="distinct hosts over cited URLs (findings' source URL and notes' URL, doi.org included); %s without doi.org; "
                "%s distinct primary hosts (one per source, doi.org replaced by the publisher host when one is cited); "
                "%s with the URLs notes were actually read at" % (fmt(ss["hostsOfCitedUrlsExcludingDoiOrg"]), fmt(ss["primaryHosts"]),
                                                                  fmt(ss["hostsIncludingReadUrls"])))
    for k, e in (("conditions", 0.99), ("locator", 1.0), ("excerpt", 0.92), ("unit", 0.83), ("numericValue", 0.92)):
        add("Field: " + k, e, fields[k]["share"], tolerance=0.005)
    add("Campaign spot checks: supported", 1085, spot_c.get("supported", {}).get("total", 0),
        note_bad="see the discrepancy notes below")
    add("Campaign spot checks: rejected", 5, spot_c.get("unsupported", {}).get("total", 0), note_bad="see below")
    add("Campaign spot checks: uncertain", 204, spot_c.get("uncertain", {}).get("total", 0), note_bad="see below")
    add("Campaign flagged: supported (Reviewed)", 1665, flag_c["Reviewed"], note_bad="see below")
    add("Campaign flagged: rejected", 1, flag_c["Rejected"], note_bad="see below")
    ends = {r["run"]: r["endState"]["findings"]["total"] for r in growth["byRun"]}
    for run, expected, name in (("before the 200-task run", 150, "K0"), ("200-task run", 532, "K200"), ("wave 1", 2170, "K1"),
                                ("wave 2", 5021, "K2"), ("wave 3", 8905, "K3")):
        add("Store at end of segment '%s' (%s)" % (run, name), expected, ends.get(run, 0), note_ok="snapshot size in the plan (Fig. 4c)")
    return rows


# ----------------------------------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="Build the Figure 3 dataset from K3 (read-only).")
    parser.add_argument("--offline", action="store_true", help="use cached Crossref records only")
    parser.add_argument("--fetch-only", action="store_true", help="only fill the Crossref cache")
    args = parser.parse_args()
    findings, notes, deposits, reviews = load_store()
    dois = {k[4:] for k in [f["key"] for f in findings] + [n["key"] for n in notes] if k.startswith("doi:")}
    failed = [] if args.offline else fetch_crossref(dois, log=lambda s: print(s, flush=True))
    if args.fetch_only:
        return
    polymers = load_graph()
    member, runs = load_runs()
    qmeta = load_question_meta([d["question_id"] for d in deposits])
    label = run_of(member, {d["question_id"] for d in deposits})
    growth = build_growth(findings, notes, deposits, member, runs, qmeta)
    coverage = build_coverage(findings, notes, polymers)
    sources = build_sources(findings, notes)
    completeness = build_completeness(findings, label)
    meta = {"store": "K3", "knowledgeSnapshot": SNAPSHOT_ID, "graphRelease": RELEASE_ID,
            "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "builder": "build.py"}
    for name, data in (("growth.json", growth), ("coverage.json", coverage), ("sources.json", sources),
                       ("completeness.json", completeness)):
        write_json(name, {"meta": meta, **data})
    write_summary(growth, coverage, sources, completeness, findings, notes, deposits, reviews, failed)
    print("wrote growth.json, coverage.json, sources.json, completeness.json, SUMMARY.md")


if __name__ == "__main__":
    main()
