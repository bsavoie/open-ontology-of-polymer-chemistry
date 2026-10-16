# Macromolecules study code

The code behind the Macromolecules study (`docs/exec-plans/active/macromolecules-study-plan.md`) and the
self-improvement tests (`docs/exec-plans/active/self-improvement-test-plan.md`). Until 2026-10-13 it lived only in
git-ignored run folders under `.oopc/`; it was copied here that day unchanged except imports and paths. Each script
still reads and writes the private folder it ran in, every `prepare` still refuses to rebuild a frozen workspace, and
the question generators still write their question files there.

Nothing in this folder is data. Questions, stores, answers, checks, traces, reports and logs stay private under
`.oopc/` until a release; never commit them. The only analysis inputs tracked here are the property map's
`rules.py`, `manual.json` and `vocabulary.json`. The question sets are not tracked: their generators are deterministic,
and on 2026-10-13 the tracked generators reproduced the private files byte for byte.

## Pins

| Pin | Value |
| --- | --- |
| Code of the controlled runs (E4, E5, test 2, E9, the test 1 recheck) | tag `study-freeze` = `cd692b8`, checked out as the worktree `.oopc/study/freeze` |
| Researcher prompt | `002364de09a8` |
| Research, review and checker model | Codex `gpt-6.1-sol` |
| Test 2's improver | Claude Code `claude-opus-5-5` |
| Graph release | `oopc-76ae33828dd011e2a0326644` |
| K3 | test 1's frozen copy of the store adopted 2026-10-12 (knowledge snapshot `oopc-knowledge-0f0a0104a3f9e15a08b94bf7`) |

`common.py` resolves the paths every script uses:

- `ROOT`: the repository root, for data (`.oopc/` records, `releases/`, the plans).
- `CODE`: the `oopc` code imported: `$OOPC_STUDY_CODE` if set, else `.oopc/study/freeze` if it exists, else `ROOT`.
  Recorded git revisions and the "worktree moved" checks use `CODE`. To recreate the freeze:
  `git worktree add --detach .oopc/study/freeze study-freeze`.
- `run_dir(name)` = `ROOT/.oopc/loop/harness/<name>`; `analysis_dir(name)` = `ROOT/.oopc/study/analysis/<name>`.
- `Guard` and `emit`, moved from the campaign driver: every engine call goes through a guard (Codex reserve floor,
  stop file, deadline, raw streams), and its stop file, streams and activity log are in the run folder passed as
  `base`.

Run scripts with `python -B` (or `PYTHONDONTWRITEBYTECODE=1`) so no `__pycache__` lands in the freeze worktree. A
`STOP` file in a run folder stops that run at the next boundary.

## The experiments, in the order they ran

Times are UTC. Private folders are under `.oopc/loop/harness/` unless noted.

**1. 200-task observation** (`observation_200/`, `2026-10-03-200/`; 2026-10-04 03:32–12:32, revision `7f8a59d`,
prompt `49be90eba54b`). The loop as it stood, observed on 200 standard-depth tasks: 160 distinct questions (40
polymer topics, four angles each) and 40 exact repeats, on a private snapshot of the store, with deposits, reviews and
40 whole-answer checks covering 20 first/repeat pairs. The baseline of Fig. 4e and the store cut K200.

```
python -B studies/macromolecules/observation_200/prepare.py   # rewrites questions.json, then refuses: the workspace exists
python -B studies/macromolecules/observation_200/run.py       # refuses: the run has started
```

**2. Campaign** (`campaign/`, `2026-10-campaign/`; wave 1 2026-10-10 23:47 to 10-11 07:10, wave 2 10-11 07:41–17:40,
wave 3 10-11 23:02 to 10-12 18:38). 800 standard-depth tasks in three waves (150, 250, 400) through the core loop on
one private workspace whose knowledge grows: five kinds of first ask (property, method, effect, assessment,
comparison) and revisits (exact, paraphrase, sibling) of earlier waves' questions, 8% sampled for whole-answer checks.
The researcher prompt changed between waves by owner-approved commits (`42a0717` → `4376dbf` → `fabbcd8` →
`002364de`). Its knowledge, adopted into the main store on 2026-10-12, is K3 (test 1 froze a copy). `recheck.py` checked again on Codex the sampled answers whose
Claude check was not a pass. Fig. 3, 4b, 4d, 4e.

```
python -B studies/macromolecules/campaign/make_questions.py   # questions.json
python -B studies/macromolecules/campaign/campaign.py prepare|status|run --wave N [--limit N]
python -B studies/macromolecules/campaign/report.py [--wave N]
python -B studies/macromolecules/campaign/recheck.py
```

**3. Test 1, the memory ablation, E1** (`ablation/`, `2026-10-ablation/`; 2026-10-13 02:02–05:20, revision
`735beef`; recheck 11:09–12:53 with the `cd692b8` checker). 60 held-out questions never asked before (20 near, 20 mid,
20 far) answered read-only by a plain session (P) and by the researcher with the store of 2026-10-01 (K0, 150
findings) and of 2026-10-12 (K3, 8,905 findings), the three arms at the same moment and checked together right after.
The pre-registered rule (near cheaper, far flat, near passes kept) was missed by one pass; the saving where memory
applies was large. `recheck.py` checked the same 180 answers again with a checker given each session's knowledge
searches (`check2`). Fig. 4a–c.

```
python -B studies/macromolecules/ablation/make_heldout.py     # heldout.json
python -B studies/macromolecules/ablation/ablation.py prepare|run
python -B studies/macromolecules/ablation/recheck.py
python -B studies/macromolecules/ablation/analyze.py [--checks check2]
```

**4. Scaling and memory alone, E4 and E5** (`scaling/`, `2026-10-scaling/`; 2026-10-13 11:17–18:39, freeze). Test
1's 60 questions answered against K3 cut at the end of each stage (K200 532, K1 2,170, K2 5,021 findings; the same
cut at 2026-10-02 must reproduce K0 or nothing runs), the researcher with web search off on K1 and K3 (M1, M3), and
test 1's K0 and K3 answers checked again the same day, so every store size is judged by one checker on one day.
Pre-registered and descriptive. Fig. 4a, 4c.

```
python -B studies/macromolecules/scaling/scaling.py prepare|run
python -B studies/macromolecules/scaling/analyze.py
```

**5. Test 2, the recursive test, E7** (`recursive/`, `2026-10-recursive/`; started 2026-10-13 12:52, freeze; running
when this code was moved, with its process importing the private copies). Three rounds: 100 new tasks through the
normal loop on a workspace that starts as K3; a snapshot (S1–S3); one Claude Code session reads the round's records
and proposes one edit to the researcher prompt; current and proposed prompts answer a 30-question dev set and the edit
is adopted by the owner's rule (no more contradicted statements, no fewer complete answers or sourced results, median
token ratio at most 1.10); the adopted prompt answers the 60 held-out questions. Then the final crossing of first and
last prompt with first and last store. Fig. 2e, 4e.

```
python -B studies/macromolecules/recursive/make_tasks.py      # dev.json and rounds.json
python -B studies/macromolecules/recursive/recursive.py prepare|run|status
```

**6. Records analyses, E2 and E3** (`analysis/`, `.oopc/study/analysis/<name>/`; 2026-10-13 13:10–13:40, no engine
calls). `dataset_build.py` (Fig. 3: growth, polymer coverage, sources with Crossref metadata, record completeness;
only DOIs leave the machine, and `--offline` builds from the cache), `loop_build.py` (Fig. 4b, 4d, 4e: reuse from
traces, revisit ratios, the scaffold trajectory, the memory curve), `properties/build.py` (E3: each finding's property
string to one of 183 classes, stored manual assignments first, then the ordered rules), and `properties_check.py`
(agreement of the map with a blind second classification of 600 strings; written when the code moved, it reproduces
the recorded `agreement.json` exactly). `polymer_filter.py` (CL-15, P1-9: the share of findings saved for a
single-polymer question that a search naming that polymer keeps; the 2026-10-12 figure, 98.9% of 7,179, was computed
with unsaved inline scripts, and this reconstruction gives the same figure on that store; read-only, any store), and
`review_agreement.py` (P0-5: a fixed sample of 100 reviewed findings reviewed again in fresh sessions, agreement on
content verdicts against the 95% target; it never changes a finding's status).

```
python -B studies/macromolecules/analysis/dataset_build.py [--offline | --fetch-only]   # -> analysis/dataset
python -B studies/macromolecules/analysis/loop_build.py                                 # -> analysis/loop
python -B studies/macromolecules/analysis/properties/build.py [store]                   # -> analysis/properties
python -B studies/macromolecules/analysis/properties_check.py [--write]                 # -> analysis/properties-check
python -B studies/macromolecules/analysis/polymer_filter.py [--store PATH] [--from-questions]  # prints the shares
python -B studies/macromolecules/analysis/review_agreement.py prepare|run|report      # -> analysis/review-agreement
```

**7. Planted wrong findings, E9** (`planted/`, `2026-10-planted/`; prepared 2026-10-13 13:01, ran 18:35–18:54 after
the scaling run, freeze). Five Reviewed findings in a copy of K3 replaced by wrong versions (a gross decimal slip, a
wrong unit, the other phase's Tg, the right value under the wrong load, a subtly wrong number) and filed as Added,
waiting for their spot check, without excerpts. One question each, answered on the untouched store (once), before
review (twice) and after one normal review (twice); every answer checked. Fig. 4f.

```
python -B studies/macromolecules/planted/planted.py prepare|run|report
```

## Known issues in the code as it ran

Found when the code was moved here; left as it ran, because the recorded results came from it. None changes a
reported number, except as noted.

- `recursive/recursive.py`, `validate`: accepts an `old` of up to 700 and a `new` of up to 1,100 characters, while the
  improver's instructions and the pre-registration say 600 and 1,000. Check every adopted edit against 600 and 1,000
  when reporting test 2 (round 1's edit is well inside both).
- `recursive/recursive.py`, `records`: the two passing answers added last can repeat an answer already chosen, so
  the improver may read one answer twice.
- `recursive/make_tasks.py`, `found`: runs `knowledge.search` on test 1's frozen K3 store, which opens it for writing
  and runs schema setup (a no-op under the freeze's code).
- `scaling/scaling.py`: the rechecks of test 1's answers reached test 1's traces through symbolic links, and reading a
  trace opens its `trace.sqlite` for writing. The tracked test copies the traces instead.
- `ablation/make_heldout.py`: opens the live store for writing rather than read-only.
- `observation_200/prepare.py`: rewrites `questions.json` before refusing because the workspace exists.
- `ablation/recheck.py`: if it stops early, `done` records the question it stopped at, not the count finished.
- `campaign/recheck.py`: calls engines at import.
- `analysis/properties_check.py`: the key `disagreeingTop50` holds 30 entries.
- Changed while test 2 ran (2026-10-14, harness only): two failed Codex quota readings in a row stopped round 2's
  held-out evaluation, so `recursive.py` now allows up to six readings a minute apart (`codex_ready`) before
  stopping; the running copy and this one were changed alike. No measurement changes.
- The freeze's engine layer reports HTTP 429 (too many requests) as `quota` and does not retry it. On 2026-10-14
  two hours of 429s, at 74% quota, failed 159 answers and checks in test 2's round-3 held-out run and final
  crossing, and the driver still reported completed. `recursive.py fill` redoes only failed results, two
  sessions at a time with pauses between passes; some crossing arms were therefore answered hours apart.
  `oopc/engines.py` on `main` now names this `rate-limited` and retries it once after a pause.
- Fixed here, analysis only: `analysis/dataset_build.py` chose example review reasons with ties in hash order, so
  the examples (not the counts) changed between runs; ties are now broken by text.

Run scripts with `python -B` so no `__pycache__` lands in the freeze worktree.

## The shared driver

`driver.py` is what every new case study runs from (pre-publication plan P1-13): a study supplies its questions, arms
and analysis, not another guard, resume loop or token count. The drivers above stay as they ran.

```
import driver
arms = [{"name": "P", "kind": "plain"},
        {"name": "K3", "kind": "researcher", "root": driver.workspace(BASE, "K3", releases=ROOT, store=K3_ROOT)}]
driver.prepare(BASE, "2026-11-example", questions, arms)   # plan.json, fixed once written
driver.run(BASE)                                           # resumable; a STOP file in BASE stops it
```

- Arms answer read-only on copies of their stores (`workspace`): a researcher arm as `parity.answer_ontology` does, a
  plain arm as `parity.answer_direct`. The plan records the prompt version, the models and each store's fingerprint,
  and `run` refuses to start if any changed.
- Question i is answered by every arm in turn, starting at arm i mod n, then all its answers are checked one right
  after the other by one checker; each answer and check records its UTC time and local hour (P0-4).
- Each (question, arm) item is saved with every attempt under `items/`; a rerun skips what is done and tries failures
  again, and a question missing a check has all its arms checked again together.
- A research timeout or a `RETRYABLE` failure is tried once more; quota, not-signed-in, the stop file and the deadline
  stop the run with that reason (P1-11). An attempt during which wall-clock time ran more than 60 s ahead of monotonic
  time slept (a closed lid) and is tried once more; `driver.Guard`, a `common.Guard`, also stops such a session as soon
  as the machine wakes (P1-10).
- Every call is recorded in the arm's token ledger with phase `study:<name>:<arm>:research` or `:check`. `report.json`
  and `report.md` give per arm the answers, contradicted statements, complete answers and sourced results first, then
  passes and access-uncertain statements, then new tokens from that ledger, total and median (P1-12).

`tests/test_driver.py` builds its own graph release and store in a temporary folder, so it runs on a fresh clone.

## Layout

| Path | Lines | What |
| --- | --- | --- |
| `common.py` | 149 | ROOT, CODE, run and analysis folders; the shared Guard and emit |
| `driver.py` | 389 | the shared driver every new case study runs from |
| `observation_200/guard.py`, `prepare.py`, `run.py` | 195, 88, 185 | the 200-task run's own guard, preparer and runner |
| `campaign/campaign.py`, `make_questions.py`, `report.py`, `recheck.py` | 279, 344, 243, 35 | the campaign |
| `ablation/make_heldout.py`, `ablation.py`, `analyze.py`, `recheck.py` | 118, 145, 135, 51 | test 1 |
| `scaling/scaling.py`, `analyze.py` | 225, 150 | E4, E5 |
| `recursive/make_tasks.py`, `recursive.py` | 227, 698 | test 2 |
| `planted/planted.py` | 246 | E9 |
| `analysis/dataset_build.py`, `loop_build.py` | 1324, 867 | E2 |
| `analysis/properties/build.py`, `rules.py`, `manual.json`, `vocabulary.json` | 473, 764, 1636, 1411 | E3, with its tracked inputs |
| `analysis/properties_check.py` | 90 | E3's blind-check agreement |
| `analysis/polymer_filter.py`, `review_agreement.py` | 79, 105 | what a polymer-named search keeps (P1-9); reviewer agreement (P0-5) |
| `tests/` | 1110 | offline tests (10 files, 27 tests) |

## Tests

```
python -B -m unittest discover -s studies/macromolecules/tests
```

The tests use scripted engines and temporary folders; `oopc` refuses host engines under `unittest`. Each skips when
the private records it reads are absent (test 1's held-out questions and frozen stores, the 200-task run's workspace,
test 2's task sets, the campaign report, a graph release), so on a fresh clone only the guard, driver, polymer-filter and
review-agreement tests run, which build what they need in temporary folders.
They read private records but never write under `.oopc/`; the scaling test copies the three traces it needs rather
than opening test 1's. They are not part of `tools/run_tests.py`.

Which `oopc` a test imports matters. The tests of the frozen runs (ablation, scaling, recursive, planted, campaign,
200-task) exercise the code as it ran, under the default `CODE` (the freeze worktree). The driver and case-study tests
exercise today's code, so run them with `OOPC_STUDY_CODE` set to the repository:

```
OOPC_STUDY_CODE=$PWD python -B -m unittest discover -s studies/macromolecules/tests -p "test_driver.py"
OOPC_STUDY_CODE=$PWD python -B -m unittest discover -s studies/macromolecules/tests -p "test_case_studies.py"
```

| Test | Was |
| --- | --- |
| `test_observation_200_guard.py`, `test_observation_200_harness.py` | `2026-10-03-200/test_guard.py`, `test_harness.py` |
| `test_campaign.py`, `test_ablation.py`, `test_scaling.py`, `test_recursive.py`, `test_planted.py` | the `test_*.py` beside each script |
| `test_driver.py`, `test_polymer_filter.py`, `test_review_agreement.py` | new 2026-10-14 (pre-publication cleanup) |
