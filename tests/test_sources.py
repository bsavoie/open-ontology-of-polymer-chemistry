"""Captured source text and DOI metadata, with a scripted network: what is tried, kept and given to a reviewer."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oopc import reviewer, sources

ARTICLE = ("<html><head><title>PLA crystallization</title><script>var x = 1;</script></head><body><nav>Menu</nav>"
           "<h2>2. Experimental</h2><p>DSC scans were run at 10 °C/min under nitrogen on 5 mg samples.</p>"
           + "<p>Filler text about polymers and their processing history in general.</p>" * 40 +
           "<table><caption>Table 2. Thermal properties</caption><tr><th>Sample</th><th>Tg (°C)</th><th>Xc (%)</th></tr>"
           "<tr><td>PLA-1</td><td>61.5</td><td>44</td></tr></table></body></html>").encode()
CHALLENGE = b"<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"
JATS = ("<article><front><article-meta><title-group><article-title>PVDF fibres</article-title></title-group>"
        "</article-meta></front><body><sec><title>Results</title>" + "<p>The beta phase fraction was 81% in fibres.</p>" * 60
        + "</sec></body></article>").encode()


class Network:
    """Answers by URL; records what was asked."""

    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def __call__(self, url, accept="*/*", timeout=20):
        self.asked.append(url)
        for prefix, (status, kind, body) in self.pages.items():
            if url.startswith(prefix):
                return status, kind, body, url
        return 404, "text/html", b"", url


class CaptureTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-sources-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_the_open_copy_is_captured_once_and_kept_privately(self):
        network = Network({"https://open.example.org/pla": (200, "text/html; charset=utf-8", ARTICLE)})
        source = {"url": "https://publisher.example.com/pla", "readUrl": "https://open.example.org/pla"}
        value = sources.capture(self.root, source, fetch=network)
        self.assertEqual((value["url"], value["method"]), ("https://open.example.org/pla", "html"))
        self.assertIn("PLA-1 | 61.5 | 44", value["text"])
        self.assertNotIn("var x", value["text"])
        self.assertNotIn("Menu", value["text"])
        sources.capture(self.root, source, fetch=network)
        self.assertEqual(network.asked, ["https://open.example.org/pla"])  # Captured once.
        stored = list((self.root / ".oopc/loop/sources").glob("*.json"))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].stat().st_mode & 0o777, 0o600)

    def test_a_refusal_is_recorded_and_the_next_copy_tried(self):
        network = Network({"https://publisher.example.com/": (403, "text/html", b""),
                           "https://mirror.example.org/": (200, "text/html", CHALLENGE),
                           "https://doi.org/10.1234/x": (200, "text/html", ARTICLE)})
        value = sources.capture(self.root, {"url": "https://publisher.example.com/x", "doi": "10.1234/x",
                                            "readUrl": "https://mirror.example.org/x"}, fetch=network)
        self.assertEqual([a.get("reason") for a in value["attempts"]], ["browser-challenge", "http-403", None])
        self.assertEqual(value["url"], "https://doi.org/10.1234/x")

    def test_pubmed_central_is_read_through_europe_pmc(self):
        search = json.dumps({"resultList": {"result": [{"pmcid": "PMC7601985"}]}}).encode()
        network = Network({sources.EUROPE_PMC + "search": (200, "application/json", search),
                           sources.EUROPE_PMC + "PMC7601985/fullTextXML": (200, "application/xml", JATS),
                           "https://www.mdpi.com/": (403, "text/html", b"")})
        value = sources.capture(self.root, {"url": "https://www.mdpi.com/2073-4360/12/10/2344",
                                            "doi": "10.3390/polym12102344"}, fetch=network)
        self.assertEqual((value["method"], value["url"]), ("jats", sources.EUROPE_PMC + "PMC7601985/fullTextXML"))
        self.assertIn("beta phase fraction was 81%", value["text"])
        pmc = sources.candidates({"url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC123456/"})
        self.assertEqual(pmc[0], sources.EUROPE_PMC + "PMC123456/fullTextXML")

    def test_a_failed_capture_waits_before_it_is_tried_again(self):
        network = Network({})
        sources.capture(self.root, {"url": "https://gone.example.org/a"}, fetch=network)
        sources.capture(self.root, {"url": "https://gone.example.org/a"}, fetch=network)
        self.assertEqual(network.asked, ["https://gone.example.org/a"])
        self.assertIsNone(sources.captured(self.root, {"url": "https://gone.example.org/a"}))
        sources.capture(self.root, {"url": "https://gone.example.org/a"}, fetch=network, retry_days=0)
        self.assertEqual(len(network.asked), 2)

    def test_an_open_copy_named_later_is_tried_at_once(self):
        # A finding's source is captured first; the note that names the open copy the researcher read comes after.
        network = Network({"https://publisher.example.com/": (403, "text/html", b""),
                           "https://open.example.org/x": (200, "text/html", ARTICLE)})
        sources.capture(self.root, {"url": "https://publisher.example.com/x"}, fetch=network)
        value = sources.capture(self.root, {"url": "https://publisher.example.com/x",
                                            "readUrl": "https://open.example.org/x"}, fetch=network)
        self.assertEqual(network.asked, ["https://publisher.example.com/x", "https://open.example.org/x"])
        self.assertEqual([a.get("reason") for a in value["attempts"]], ["http-403", None])
        self.assertTrue(value["text"])

    def test_a_broken_response_is_a_failed_attempt(self):
        import http.client

        def broken(url, accept="*/*", timeout=20):
            raise http.client.IncompleteRead(b"partial")
        value = sources.capture(self.root, {"url": "https://slow.example.org/a"}, fetch=broken)
        self.assertEqual(value["attempts"][0]["reason"], "IncompleteRead")

    def test_tests_never_reach_the_network(self):
        with self.assertRaises(OSError):
            sources.get("https://example.org/")
        value = sources.capture(self.root, {"url": "https://example.org/a"})
        self.assertEqual(value["attempts"][0]["reason"], "OSError")

    def test_dois_are_found_in_urls(self):
        self.assertEqual(sources.doi_of("https://pubs.acs.org/doi/full/10.1021/ma0123456?ref=x"), "10.1021/ma0123456")
        self.assertEqual(sources.doi_of("https://doi.org/10.1002/app.12345"), "10.1002/app.12345")
        self.assertEqual(sources.clean_doi("https://doi.org/10.1234/X"), "10.1234/X")
        self.assertEqual(sources.doi_of("https://example.org/paper"), "")


class PassageTests(unittest.TestCase):
    def test_passages_surround_the_values_and_labels_a_claim_names(self):
        text = sources.html_text(ARTICLE)[0]
        found = sources.passages(text, sources.needles("PLA-1 had a Tg of 61.5 °C", "Table 2", "DSC at 10 °C/min"),
                                 limit=900)
        joined = " ".join(found)
        self.assertIn("61.5", joined)
        self.assertIn("10 °C/min", joined)  # The method, stated in the experimental section.
        self.assertLessEqual(sum(len(p) for p in found), 900 + 2 * len(found))
        self.assertEqual(sources.passages(text, sources.needles("99.9"), limit=500), [])

    def test_a_number_is_not_found_inside_another(self):
        found = sources.passages("Values were 161.5 and 61.50 and 61.5 here." + " pad" * 100,
                                 [("number", "61.5")], limit=60)
        self.assertEqual(len(found), 1)
        self.assertIn("61.5 here", found[0])


class MetadataTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-crossref-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_crossref_metadata_is_cached_and_a_missing_doi_remembered(self):
        message = {"title": ["Poly(1-vinylimidazole) <i>brushes</i>"], "author": [{"family": "Doe", "given": "A."}],
                   "issued": {"date-parts": [[2021, 3]]}, "container-title": ["Macromolecules"]}
        network = Network({sources.CROSSREF + "10.1234/known": (200, "application/json", json.dumps({"message": message}).encode())})
        value = sources.metadata(self.root, "https://doi.org/10.1234/known", fetch=network)
        self.assertEqual(value, {"title": "Poly(1-vinylimidazole) brushes", "authors": ["Doe, A."], "year": 2021,
                                 "container": "Macromolecules"})
        self.assertEqual(sources.metadata(self.root, "10.1234/known", fetch=network), value)
        self.assertIsNone(sources.metadata(self.root, "10.1234/unknown", fetch=network))
        self.assertIsNone(sources.metadata(self.root, "10.1234/unknown", fetch=network))
        self.assertEqual(len(network.asked), 2)  # Each DOI asked once, the unknown one too.
        self.assertTrue(sources.same_title("Poly(1-vinylimidazole) brushes", value["title"]))
        self.assertFalse(sources.same_title("Poly(1-vinimidazole) brushes", value["title"]))


class ReviewerEvidenceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-evidence-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        sources.capture(self.root, {"url": "https://open.example.org/pla"},
                        fetch=Network({"https://open.example.org/pla": (200, "text/html", ARTICLE)}))

    def test_a_reviewer_gets_the_captured_passages_first(self):
        finding = {"id": "finding:a", "statement": "PLA-1 had a Tg of 61.5 °C.", "value": "61.5", "unit": "°C",
                   "conditions": "DSC at 10 °C/min", "locator": "Table 2", "source": {"url": "https://open.example.org/pla"}}
        prompt = reviewer.review_prompt([finding], self.root)
        given = json.loads(prompt[prompt.index("{"):])["findings"][0]["capturedText"]
        self.assertEqual(given["from"], "https://open.example.org/pla")
        self.assertIn("61.5", " ".join(given["passages"]))
        self.assertNotIn("capturedText", reviewer.review_prompt([finding])[len(reviewer.INSTRUCTION):])

    def test_a_checker_gets_passages_around_what_the_answer_says_of_each_source(self):
        answer = "PLA-1 crystallinity was 44% `https://open.example.org/pla`. Background: PLA is a polyester."
        given = reviewer.with_captures(self.root, [{"url": "https://open.example.org/pla"}, {"url": "https://other.example"}],
                                       answer)
        self.assertIn("44", " ".join(given[0]["capturedText"]["passages"]))
        self.assertNotIn("capturedText", given[1])

    def test_measures_lead_and_do_not_count_source_access(self):
        check = {"verdict": "fail", "resultGiven": True, "statements": [
            {"verdict": "unsupported", "kind": "source-fact", "category": "contradiction"},
            {"verdict": "uncertain", "kind": "source-fact", "category": "source-access"},
            {"verdict": "unsupported", "kind": "source-fact", "category": "source-access", "evidence": "live"},
            {"verdict": "supported", "kind": "source-fact", "category": "none", "evidence": "captured"},
            {"verdict": "supported", "kind": "completeness", "category": "none"}]}
        self.assertEqual(reviewer.measures(check), {"contradicted": 1, "complete": True, "resultGiven": True, "pass": False,
                                                    "accessUncertain": 2, "statements": 5, "onCapturedText": 1})
        self.assertIsNone(reviewer.measures({"error": {"reason": "quota"}}))


if __name__ == "__main__":
    unittest.main()
