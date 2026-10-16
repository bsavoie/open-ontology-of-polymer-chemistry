"""The one-time import reads a synthetic 0.11 layout and brings over only what is useful."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from oopc import knowledge
from oopc.ask import Questions
from oopc.legacy_import import FAITHFUL_SCHEMA, REWRITE_SCHEMA, rewrite_statements, run

TASK = "c" * 32


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class LegacyImportTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="oopc-legacy-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        legacy = self.root / ".oopc"
        evidence = {"@id": "evidence:new:pla", "@type": "Evidence", "citation": "Doe et al., PLA annealing, doi:10.1234/pla.5",
                    "url": "https://example.org/pla", "locator": "Table 2"}
        accepted = {"kind": "claim", "record": {"@id": "claim:pla-45", "@type": "Claim", "label": "PLA crystallinity",
                    "claim": "Annealed PLA reached 45% crystallinity.", "subject": "wop-000217",
                    "context": {"materialScope": "PLA 4032D film", "conditions": {"temperature": "100 °C", "agitation": "unknown"},
                                "method": "DSC", "originalValue": "45%", "units": "%"}, "evidence": ["evidence:new:pla"]}}
        rejected = {"kind": "claim", "record": {"@id": "claim:bad", "@type": "Claim", "claim": "Not admitted.",
                                                "evidence": ["evidence:new:pla"]}}
        sourceless = {"kind": "claim", "record": {"@id": "claim:nosource", "@type": "Claim", "claim": "No source.",
                                                  "evidence": ["evidence:missing"]}}
        recipe = {"kind": "memory", "record": {"@id": "recipe:x", "@type": "Recipe", "label": "Retrieve the PLA claim",
                                               "evidence": ["evidence:new:pla"]}}
        for name, proposal, ok in (("p1", accepted, True), ("p2", rejected, False), ("p3", sourceless, True),
                                   ("p4", recipe, True)):
            write(legacy / "proposals" / (name + ".json"), proposal)
            write(legacy / "admissions" / (name + ".json"), {"accepted": ok, "reviewId": "r-" + name})
        write(legacy / "reviews/p1.json", {"sourceChecks": [{"evidenceId": "evidence:new:pla", "notes": "Table 2 confirms 45%."}]})
        write(legacy / "campaigns/week-2026-09-27/state.json", {"campaignId": "week-2026-09-27", "jobs": [
            {"jobId": "private-" + TASK, "question": "How crystalline does annealed PLA get?",
             "interactiveTask": {"taskId": TASK, "runtime": "codex", "budgetSeconds": 600, "submittedAt": "2026-09-27T10:00:00+00:00",
                                 "protocol": "oopc-private-interactive-task-v4"}},
            {"jobId": "private-" + "d" * 32, "question": "A question that never finished",
             "interactiveTask": {"taskId": "d" * 32, "submittedAt": "2026-09-27T11:00:00+00:00"}},
            {"jobId": "task-1", "question": "Campaign research is not user history"}]})
        write(legacy / "campaigns/week-2026-09-27" / ("private-" + TASK) / "result.json",
              {"answer": "About 45% [evidence:new:pla](https://example.org/pla).", "citations": ["evidence:new:pla"],
               "limitations": ["One grade only"], "evidenceRecords": [evidence]})
        db_path = legacy / "knowledge/knowledge.sqlite"
        db_path.parent.mkdir(parents=True)
        db = sqlite3.connect(db_path)
        db.executescript("CREATE TABLE notes (id TEXT, task_id TEXT, status TEXT, json TEXT);"
                         "CREATE TABLE drafts (id TEXT, task_id TEXT, status TEXT, type TEXT, json TEXT);")
        note = {"source": {"url": "https://example.org/pla", "title": "PLA annealing"}, "locator": "Table 2",
                "excerpts": ["45% after 1 h"], "supports": "crystallinity", "conditions": "100 °C"}
        db.execute("INSERT INTO notes VALUES (?,?,?,?)", ("note:%s:1" % TASK, TASK, "reviewed", json.dumps(note)))
        db.execute("INSERT INTO notes VALUES (?,?,?,?)", ("note:%s:2" % TASK, TASK, "rejected", json.dumps(note)))
        db.execute("INSERT INTO drafts VALUES (?,?,?,?,?)", ("claim:pla-45", TASK, "accepted", "Claim", "{}"))
        db.commit()
        db.close()
        self.before = sorted((p, p.stat().st_mtime_ns) for p in legacy.rglob("*") if p.is_file())

    def test_preview_changes_nothing_and_apply_imports_only_useful_items(self):
        preview = run(self.root)
        self.assertEqual((preview["reviewedFindings"], preview["sourceNotes"], preview["questions"], preview["applied"]),
                         (1, 1, 2, False))
        self.assertEqual(preview["skippedAdmissions"], [{"recordId": "claim:nosource", "reason": "no openable source"}])
        self.assertFalse(knowledge.database(self.root).exists())

        report = run(self.root, apply=True)
        self.assertEqual(report["answeredQuestions"], 1)
        [finding] = knowledge.recent(self.root, "supported")
        self.assertEqual((finding["statement"], finding["value"], finding["subject"]),
                         ("Annealed PLA reached 45% crystallinity.", "45%", "wop-000217"))
        self.assertEqual(finding["source"], {"title": "Doe et al., PLA annealing, doi:10.1234/pla.5",
                                             "url": "https://example.org/pla", "doi": "10.1234/pla.5"})
        self.assertIn("Table 2 confirms 45%.", finding["review"]["reason"])
        self.assertEqual(knowledge.get(self.root, "evidence:new:pla")["url"], "https://example.org/pla")
        self.assertEqual(knowledge.search(self.root, "PLA crystallinity")["reviewed"][0]["id"], finding["id"])

        history = Questions(self.root).get(TASK)
        self.assertEqual((history["status"], history["origin"], history["canRetry"]), ("completed", "legacy", False))
        self.assertEqual(history["result"]["citations"], ["evidence:new:pla"])
        self.assertEqual([f["id"] for f in history["findings"]], [finding["id"]])
        self.assertEqual(Questions(self.root).get("d" * 32)["status"], "failed")

        again = run(self.root, apply=True)
        self.assertEqual(again["reviewedFindings"], 1)
        self.assertEqual(knowledge.summary(self.root)["findings"], {"supported": 1})
        self.assertEqual(len(knowledge.search(self.root, "PLA annealing")["notes"]), 2)
        after = sorted((p, p.stat().st_mtime_ns) for p in (self.root / ".oopc").rglob("*")
                       if p.is_file() and "loop" not in p.relative_to(self.root / ".oopc").parts)
        self.assertEqual(after, self.before)

    def test_label_statements_are_rewritten_only_when_faithful_to_the_record(self):
        legacy = self.root / ".oopc"
        process = {"@id": "process:x", "@type": "Process", "context": {"conditions": "100 °C for 60 min", "method": "annealing"}}
        for name, label in (("p5", "Reported PLA annealing"), ("p6", "PLA annealing time"), ("p7", "PLA annealing effect")):
            write(legacy / "proposals" / (name + ".json"), {"kind": "claim", "entities": [process], "record": {
                "@id": "claim:" + name, "@type": "Claim", "label": label, "evidence": ["evidence:new:pla"]}})
            write(legacy / "admissions" / (name + ".json"), {"accepted": True, "reviewId": "r-" + name})
        run(self.root, apply=True)
        ids = {f["statement"]: f["id"] for f in knowledge.recent(self.root, "supported")}
        good, extra, unfaithful = ids["Reported PLA annealing"], ids["PLA annealing time"], ids["PLA annealing effect"]
        calls = []

        def engine(name, prompt, schema, **options):
            calls.append((name, schema, options.get("web")))
            if schema is REWRITE_SCHEMA:
                answer = {"rewrites": [{"id": good, "statement": "PLA was annealed at 100 °C for 60 min."},
                                       {"id": extra, "statement": "PLA was annealed at 120 °C."},
                                       {"id": unfaithful, "statement": "Annealing always raises PLA crystallinity."}]}
            else:
                answer = {"verdicts": [{"id": good, "faithful": True, "reason": "Matches the Process entity."},
                                       {"id": unfaithful, "faithful": False, "reason": "Generalises beyond the record."}]}
            return {"engine": name, "answer": answer}

        preview = rewrite_statements(self.root, runner=engine)
        self.assertEqual((preview["candidates"], len(preview["rewritten"]), preview["applied"]), (3, 1, False))
        self.assertEqual({r["id"]: r["reason"] for r in preview["refused"]},
                         {extra: "numbers not in the record: 120", unfaithful: "Generalises beyond the record."})
        self.assertEqual(calls, [("claude-code", REWRITE_SCHEMA, False), ("codex", FAITHFUL_SCHEMA, False)])
        self.assertEqual(knowledge.get(self.root, good)["statement"], "Reported PLA annealing")  # A preview changes nothing.

        rewrite_statements(self.root, runner=engine, apply=True)
        finding = knowledge.get(self.root, good)
        self.assertEqual((finding["statement"], finding["originalStatement"], finding["status"]),
                         ("PLA was annealed at 100 °C for 60 min.", "Reported PLA annealing", "supported"))
        self.assertEqual(knowledge.get(self.root, extra)["statement"], "PLA annealing time")
        self.assertIn(good, [f["id"] for f in knowledge.search(self.root, "annealed 60 min")["reviewed"]])
        self.assertEqual(rewrite_statements(self.root, runner=engine)["candidates"], 2)  # Done ones are not redone.


if __name__ == "__main__":
    unittest.main()
