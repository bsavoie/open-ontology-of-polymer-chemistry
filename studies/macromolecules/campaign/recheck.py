"""Check again on Codex the sampled answers whose Claude check was not a pass (owner, 2026-10-11: Claude could not
open many cited sources). The original check is kept; the Codex check is saved beside it as check-NNNN-codex.json,
with the same inputs the first check had.

Ran in `.oopc/loop/harness/2026-10-campaign/` and still reads and writes there; moved to the repository on 2026-10-13
unchanged except imports and paths."""
import glob, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import run_dir  # noqa: E402  (common puts CODE first on sys.path)

BASE = run_dir("2026-10-campaign")
from oopc import engines, reviewer  # noqa: E402
from oopc.util import atomic_json, now, read_json  # noqa: E402

WORK = BASE / "workspace"
tasks = {t["number"]: t for t in json.loads((BASE / "questions.json").read_text())}
for path in sorted(BASE.glob("waves/wave-*/checks/check-0*.json")):
    if path.stem.endswith("-codex"):
        continue
    first = read_json(path)
    target = path.with_name(path.stem + "-codex.json")
    if first.get("verdict") == "pass" or first.get("engine") == engines.CODEX or (target.exists() and "verdict" in read_json(target)):
        continue
    number = int(path.stem.split("-")[1])
    given = read_json(path.with_name("check-input-%04d.json" % number))
    try:
        value = reviewer.check_answer(given["question"], given["answer"], given["sources"], engine=engines.CODEX,
                                      root=WORK, owner=tasks[number]["taskId"])
        atomic_json(target, dict(value, at=now(), engine=engines.CODEX, firstVerdict=first.get("verdict")), private=True)
        print(number, first.get("verdict"), "->", value.get("verdict"), flush=True)
    except engines.EngineError as error:
        atomic_json(target, dict(error=error.summary(), at=now(), engine=engines.CODEX), private=True)
        print(number, "failed", error.reason, flush=True)
