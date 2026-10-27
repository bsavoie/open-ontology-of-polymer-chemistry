"""Structure strategy 1, source records (`structure/sources.py`), offline: page addresses and source keys, failed opens
classed in time order (a copy opened elsewhere, a copy in a KF note, a URL failed before, the same answer, none), the
other-questions and used-copies variants, web calls saved net of the opens added back, the fixed-effects cost of a web
call, the known-blocked rule, and a whole run on a tiny world of records in a temporary folder. Run with today's code:

    OOPC_STUDY_CODE=$PWD python -B -m unittest discover -s studies/macromolecules/tests -p "test_structure_*.py"
"""
import datetime as dt, json, random, sqlite3, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules
import common  # noqa: E402,F401  (puts the code under test first on sys.path)
from structure import sources as S  # noqa: E402

T0 = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
D, E = "10.3390/polym16162304", "10.1016/j.e.2020.1"
PMC = "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/"
MDPI = "https://www.mdpi.com/2073-4360/16/16/2304"
MDPI_PDF = "https://mdpi-res.com/d_attachment/polymers/polymers-16-02304/article_deploy/polymers-16-02304.pdf"
Y, Z = "https://journal.org/y", "https://journal.org/z"
E_PAGE, E_READ = "https://publisher.org/e", "https://repo.org/e.pdf"


def at(minutes):
    return T0 + dt.timedelta(minutes=minutes)


def answer(ident, group, question, start, end, opens, *, sources=(), cited=(), tokens=None, seconds=None):
    calls = [{"action": "open", "url": url, "outcome": outcome} for url, outcome in opens]
    return S._answer(ident, group, question, arm=group.split("/")[-1], engine="codex", start=at(start), end=at(end),
                     tokens=tokens, seconds=seconds, calls_=calls, sources=list(sources), findings=[],
                     cited=list(cited))


class Pages(unittest.TestCase):
    def test_address(self):
        self.assertEqual(S.address("https://www.Example.com/a/b/?utm_source=x#top"), "url:example.com/a/b")
        self.assertEqual(S.address("https://doi.org/10.1000/ABC"), "doi:10.1000/abc")
        self.assertEqual(S.address("https://www.scielo.org.mx/scielo.php?pid=S1&script=sci_arttext&tlng=en"),
                         "url:scielo.org.mx/scielo.php?pid=s1&script=sci_arttext")
        self.assertEqual(S.address("https://x.org/view.html?doi=10.1/2&lang=en"), "url:x.org/view.html?doi=10.1%2F2")
        self.assertEqual(S.address(PMC + "?pdf=1"), S.address(PMC))

    def test_keys(self):
        found = S.Sources([(PMC, D)])
        self.assertTrue({"pmc:123", "doi:" + D} <= found.keys(PMC + "?pdf=1"))
        self.assertIn("mdpi:polymers-16-2304", found.keys(MDPI))
        self.assertIn("mdpi:polymers-16-2304", found.keys(MDPI_PDF))
        self.assertIn("doi:10.1002/app.1", found.keys("https://onlinelibrary.wiley.com/doi/full/10.1002/app.1"))
        self.assertIn("pii:s0032386103000831",
                      found.keys("https://www.sciencedirect.com/science/article/abs/pii/S0032386103000831"))
        self.assertIn("patent:US20030214715A1", found.keys("https://patents.google.com/patent/US20030214715A1/en"))
        listing = S.Sources([("https://a.org/list", "10.1/%s" % x) for x in "abc"])
        self.assertEqual(listing.keys("https://a.org/list"), frozenset({"url:a.org/list"}))
        self.assertEqual(listing.listings, ["url:a.org/list"])

    def test_pattern(self):
        self.assertEqual(S.pattern(PMC + "?pdf=1"), "pmc.ncbi.nlm.nih.gov/articles/PMC#? [pdf]")
        self.assertEqual(S.pattern(MDPI), "mdpi.com/#-#/#")


class Classify(unittest.TestCase):
    """A opens D's PMC copy and fails at Y; C, running while A runs, fails at D's MDPI page; B, later, fails at D's
    MDPI page, at Y twice, at Z twice and at E's publisher page, whose KF note has a read_url."""

    def world(self, b_question="qb", a_cites=True):
        a = answer("A", "pool/loop", "qa", 0, 10, [(PMC, "opened"), (Y, "refused")],
                   sources=[{"url": PMC, "doi": D}] if a_cites else [])
        c = answer("C", "pool/loop", "qc", 5, 20, [(MDPI, "refused")])
        b = answer("B", "screen/B", b_question, 30, 40, [(MDPI, "refused"), (Y, "refused"), (Y, "refused"),
                                                         (Z, "refused"), (Z, "refused"), (E_PAGE, "refused")])
        notes = [{"id": "n1", "question_id": "n", "url": E_PAGE, "doi": E, "read_url": E_READ,
                  "created_at": at(20).isoformat()}]
        answers = [a, c, b]
        found = S.Sources(list(S.doi_pairs(answers, notes, [])) + [(MDPI, D), (PMC, D)])
        return answers, notes, found

    def reasons(self, rows, ident):
        return [r["reason"] for r in rows if r["id"] == ident]

    def test_main(self):
        answers, notes, found = self.world()
        rows = S.classify(answers, notes, found)
        self.assertEqual(self.reasons(rows, "A"), ["none"])
        self.assertEqual(self.reasons(rows, "C"), ["none"])  # A had not ended when C started
        self.assertEqual(self.reasons(rows, "B"), ["copy-opened-elsewhere", "url-failed-before", "url-failed-before",
                                                   "none", "same-answer", "copy-in-note"])
        rest = {(r["id"], r["n"]): r["rest"] for r in rows}
        self.assertEqual(rest[("A", 1)], "never-opened")
        self.assertEqual(rest[("C", 0)], "opened-only-later")
        self.assertEqual(rest[("B", 3)], "never-opened")
        self.assertEqual(rest[("B", 4)], "same-answer-retry")
        saved = S.savings(answers, rows, found)
        # B: D's page (1, never opened: added back, a copy gained), Y twice (net 1, another try added back), Z not
        # credited, E's page (1, a copy gained from the note)
        self.assertEqual({k: saved[2][k] for k in ("failed", "credited", "upper", "net", "added", "gained")},
                         {"failed": 6, "credited": 4, "upper": 4, "net": 1, "added": 3, "gained": 2})
        self.assertEqual(saved[0]["upper"], 0)

    def test_other_questions(self):
        answers, notes, found = self.world(b_question="qa")
        rows = S.classify(answers, notes, found, other_questions=True)
        # A's copy and A's failure at Y no longer count; C's failure at D's page (another question) does
        self.assertEqual(self.reasons(rows, "B"), ["url-failed-before", "none", "same-answer", "none", "same-answer",
                                                   "copy-in-note"])

    def test_used_copies(self):
        answers, notes, found = self.world(a_cites=False)
        rows = S.classify(answers, notes, found, used_only=True)
        self.assertEqual(self.reasons(rows, "B")[0], "url-failed-before")
        self.assertEqual(self.reasons(S.classify(answers, notes, found), "B")[0], "copy-opened-elsewhere")

    def test_savings_when_the_source_opened_anyway(self):
        a = answer("A", "pool/loop", "qa", 0, 10, [(Y, "refused")])
        b = answer("B", "pool/loop", "qb", 20, 30, [(Y, "refused"), (Y, "refused"), (Y + "/full.pdf", "opened")])
        found = S.Sources([(Y, D), (Y + "/full.pdf", D)])
        rows = S.classify([a, b], [], found)
        saved = S.savings([a, b], rows, found)
        self.assertEqual((saved[1]["upper"], saved[1]["net"], saved[1]["gained"]), (2, 2, 0))


class Cost(unittest.TestCase):
    def test_fixed_effects_recover_the_costs(self):
        weights = {"failed": 1000, "opened": 5000, "search": 7000, "other": 4000}
        answers, rng = [], random.Random(1)
        for q in range(6):
            for a, arm in enumerate(("B0", "B", "Oplus") * 2):  # two replicates
                kinds = {k: rng.randint(0, 3) for k in weights}
                tokens = 10000 * q + sum(weights[k] * n for k, n in kinds.items()) + 2000 * (arm == "B")
                calls = ([{"action": "open", "url": "https://h.org/f", "outcome": "refused"}] * kinds["failed"]
                         + [{"action": "open", "url": "https://h.org/o", "outcome": "opened"}] * kinds["opened"]
                         + [{"action": "search", "url": "", "outcome": "searched"}] * kinds["search"]
                         + [{"action": "other", "url": "", "outcome": ""}] * kinds["other"])
                answers.append(S._answer("%d-%s" % (q, arm), "screen/" + arm, "q%d" % q, arm=arm, engine="codex",
                                         start=at(0), end=at(1), tokens=tokens, seconds=10 * len(calls), calls_=calls,
                                         sources=[], findings=[], cited=[]))
        cost = S.marginal_cost(answers, reps=20)
        by_kind = cost["models"]["newTokens|kinds+arm"]["coefficients"]
        for kind, value in weights.items():
            self.assertAlmostEqual(by_kind[kind], value, places=3)
        self.assertAlmostEqual(by_kind["arm:B"], 2000, places=3)
        self.assertAlmostEqual(cost["models"]["seconds|web"]["coefficients"]["web"], 10, places=3)
        self.assertEqual(len(cost["models"]["newTokens|web"]["draws"]["web"]), 20)
        self.assertEqual(cost["questions"], 6)

    def test_interval_and_solve(self):
        self.assertEqual(S.interval([None, 3, 1, 2]), [1, 3])
        self.assertIsNone(S.interval([None]))
        self.assertEqual(S._solve([[2, 0], [0, 4]], [2, 8]), [1, 2])
        self.assertIsNone(S._solve([[1, 1], [1, 1]], [1, 1]))


class Blocked(unittest.TestCase):
    def test_rule_in_time_order(self):
        answers = [answer("a%d" % i, "pool/loop", "q%d" % i, 2 * i, 2 * i + 1,
                          [("https://blocked.org/p%d" % i, "refused")]) for i in range(10)]
        answers.append(answer("late", "pool/loop", "ql", 30, 31, [("https://blocked.org/x", "refused"),
                                                                 ("https://blocked.org/y", "opened"),
                                                                 ("https://fine.org/z", "refused")]))
        skipped, counts = S.blocked(answers)
        self.assertEqual(skipped, {(10, 0)})
        self.assertEqual((counts["failedSkipped"], counts["openedSkipped"]), (1, 1))
        self.assertEqual(counts["top"], [("blocked.org", 1)])


class Run(unittest.TestCase):
    """The whole estimate on a tiny world of records: a loop answer and a Part A answer in the pool, three screen
    answers and two case answers, and a KF store."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.paths = {"root": base / "root", "pool_folder": base / "mine", "screen": base / "screen",
                      "cases": base / "cases", "kf": base / "kf.sqlite", "harness": base / "harness"}
        question = self.paths["root"] / ".oopc/loop/questions/qa"
        question.mkdir(parents=True)
        (question / "question.json").write_text(json.dumps({"question": "Question A?", "startedAt": at(0).isoformat(),
                                                            "finishedAt": at(10).isoformat()}))
        (question / "result.json").write_text(json.dumps({"answer": {"usage": {
            "input_tokens": 50000, "cached_input_tokens": 20000, "output_tokens": 2000}}}))
        item = self.paths["harness"] / "2026-10-kf-ladder/r1-s1/items/0000-KF.json"
        item.parent.mkdir(parents=True)
        item.write_text(json.dumps({"answer": {"at": at(15).isoformat(), "engine": "codex",
                                               "metrics": {"seconds": 120, "newTokens": 20000}}}))
        records = [
            {"id": "loop/qa", "origin": "loop", "questionId": "qa", "question": "Question A?",
             "detail": {"engine": "codex"}, "startedAt": at(0).isoformat(),
             "steps": [{"type": "store"}, {"type": "web-search", "query": "x"},
                       {"type": "open", "url": PMC, "outcome": "opened"},
                       {"type": "open", "url": Y, "outcome": "refused"}],
             "sources": [{"title": "D", "url": PMC, "doi": D, "readUrl": ""}], "reported": [], "cited": {"urls": []}},
            {"id": "2026-10-kf-ladder/r1-s1/0000-KF", "origin": "A4", "questionId": "x", "question": "Question X?",
             "detail": {"folder": "2026-10-kf-ladder/r1-s1", "item": "0000-KF", "arm": "KF"},
             "steps": [{"type": "open", "url": MDPI, "outcome": "refused"}], "sources": [], "reported": [],
             "cited": {"urls": []}}]
        mine = self.paths["pool_folder"]
        mine.mkdir()
        (mine / "answers.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        (mine / "pool.json").write_text(json.dumps({"answers": [r["id"] for r in records], "digest": "d"}))
        for kind, run, arms in (("screen", "s1", ("B0", "B", "Oplus")), ("cases", "r1", ("B0", "B"))):
            folder = self.paths[kind] / run / "items"
            folder.mkdir(parents=True)
            plan = {"questions": [{"id": "q1", "question": "Question B?"}]}
            (folder.parent / "plan.json").write_text(json.dumps(plan))
            for n, arm in enumerate(arms):
                actions = [{"action": "search", "outcome": "searched", "query": "q"}] + [
                    {"action": "open", "outcome": "refused", "url": MDPI}] * (n + 1)
                (folder / ("0000-%s.json" % arm)).write_text(json.dumps({"arm": arm, "question": "q1", "answer": {
                    "at": at(60 + 10 * n + (100 if kind == "cases" else 0)).isoformat(), "engine": "codex",
                    "metrics": {"newTokens": 30000 + 4000 * len(actions), "seconds": 60, "webCalls": len(actions)},
                    "webActions": actions, "answer": {"answer": "text", "sources": [], "findings": [],
                                                      "citations": []}}}))
        db = sqlite3.connect(self.paths["kf"])
        db.execute("CREATE TABLE notes (id, question_id, url, doi, read_url, created_at)")
        db.execute("CREATE TABLE findings (source_url, source_doi)")
        db.execute("INSERT INTO notes VALUES ('n1', 'qa', ?, ?, ?, ?)", (E_PAGE, E, E_READ, at(5).isoformat()))
        db.execute("INSERT INTO findings VALUES (?, ?)", (MDPI, D))
        db.commit()
        db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_build(self):
        answers, notes, found, info = S.load(**self.paths)
        self.assertEqual([a["group"] for a in answers], ["pool/loop", "pool/A4", "screen/B", "screen/B0",
                                                         "screen/Oplus", "cases/B", "cases/B0"])  # items by name
        self.assertEqual(answers[0]["newTokens"], 32000)
        self.assertEqual(answers[1]["start"], at(13))
        self.assertEqual(answers[0]["kinds"], {"failed": 1, "opened": 1, "search": 1, "other": 0})
        self.assertEqual(info["kfReadUrls"], 1)
        result, rows = S.build(reps=10, **self.paths)
        main = result["variants"]["main"]["groups"]
        # A4's failure at D's MDPI page: the loop answer opened D at PMC before it started
        self.assertEqual(main["pool/A4"]["reasons"]["copy-opened-elsewhere"], 1)
        self.assertEqual(main["all"]["failedOpens"], 1 + 1 + 6 + 3)
        self.assertEqual(main["screen"]["reasons"]["copy-opened-elsewhere"], 6)  # every failure at D's MDPI page
        self.assertEqual(main["screen"]["netPerAnswer"], (0 + 1 + 2) / 3)  # one open added back per answer
        self.assertAlmostEqual(result["cost"]["models"]["newTokens|web"]["coefficients"]["web"], 4000, places=3)
        self.assertIn("pool", result["variants"]["main"]["verdicts"])
        json.dumps(result)
        self.assertIn("## Prediction 1", S.render(result))


if __name__ == "__main__":
    unittest.main()
