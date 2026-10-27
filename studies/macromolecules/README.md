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

**On KF (Part A, experiment A1; 2026-10-18).** The same analyses retargeted to KF, the frozen knowledge base, from the
code of tag `study-freeze-2`. `analysis/kf.py` holds KF's pins and makes one frozen copy of the live store, through a
read-only backup, at `.oopc/study/analysis/kf/workspaces/KF`; every build refuses a copy whose fingerprint is not KF's,
and every output carries the pins and the analysis code's revision. `--kf` switches each script to that copy and to a
`-kf` output folder (`--out` writes elsewhere); without it they build K3's outputs as before. On KF the trajectory reads
excerpts as the researcher saved them (`kf.as_written`), and the cleanup's `upkeep` deposits are not answers. Property
strings no rule or stored assignment covers stay unclassified. `tg_landscape.py` writes Fig. 3d's one row per Tg and Tm
finding with one readable temperature, its method read from the property string, else the conditions (its rules are in
its output); `figure_data.py` writes the panel index, with each panel's headline numbers on KF beside K3's and the
definitions of counts that can be read two ways, and Table 1.

```
export OOPC_STUDY_ROOT=$PWD OOPC_STUDY_CODE=$PWD/.oopc/study/freeze-2   # from a worktree: the main checkout's path
python -B studies/macromolecules/analysis/dataset_build.py --kf          # -> analysis/dataset-kf
python -B studies/macromolecules/analysis/properties/build.py --kf       # -> analysis/properties-kf
python -B studies/macromolecules/analysis/properties_check.py --kf       # -> analysis/properties-check-kf
python -B studies/macromolecules/analysis/tg_landscape.py                # -> analysis/tg-landscape
python -B studies/macromolecules/analysis/loop_build.py --kf             # -> analysis/loop-kf
python -B studies/macromolecules/analysis/figure_data.py                 # -> analysis/figures-kf, analysis/table1
```

Its tests run on today's code (`OOPC_STUDY_CODE=$PWD ... -p "test_records_kf.py"`); with `OOPC_STUDY_ROOT` naming a
checkout that has KF's frozen copy and K3's records analyses they also run the KF builds into temporary folders. They
never make the copy.

**7. Planted wrong findings, E9** (`planted/`, `2026-10-planted/`; prepared 2026-10-13 13:01, ran 18:35–18:54 after
the scaling run, freeze). Five Reviewed findings in a copy of K3 replaced by wrong versions (a gross decimal slip, a
wrong unit, the other phase's Tg, the right value under the wrong load, a subtly wrong number) and filed as Added,
waiting for their spot check, without excerpts. One question each, answered on the untouched store (once), before
review (twice) and after one normal review (twice); every answer checked. Fig. 4f.

```
python -B studies/macromolecules/planted/planted.py prepare|run|report
```

## Figures and the closing analyses

`figures/` draws the paper's records panels from A1's outputs only (`dataset-kf`, `properties-kf`, `tg-landscape`,
`loop-kf`; no store, trace or engine), each panel as its own PDF and SVG with a 200 dpi PNG preview, plus the assembled
figure, into `.oopc/study/analysis/figures/` (private, like its inputs). `style.py` holds what every figure shares: one
fixed colour per status (Reviewed, Added, Needs checking, Rejected) and per arm (P; the K and KF stores as one blue ramp
by size; the web-off M and MF arms orange; A3's resampled stores a magenta ramp), checked for colour-vision safety with
the dataviz skill's validator (results in its docstring), the ACS widths (7 and 3.33 in), Arial at 5.5–9 pt, and the
pins. Every file carries the pins in its metadata: KF's snapshot and fingerprint, the graph release, prompt and code
tag, the inputs' analysis revision, and the figure script's own revision (commit before rendering, or it ends in
`-dirty`). An input whose pins are not KF's is refused, as are revisit medians that disagree with `revisits.json`'s
summary. `figures/manifest.json` lists every file with its sources, pins and a caption whose numbers come from the data.
Fig. 4a and 4c are drawn by `fig4ac.py` from `analysis/a2a3e8/results.json` (`part_a/a2a3e8_results.py`, A2, A3 and
E8), the similarity ladder by `fig4b.py` (`fig4b_ladder.*`) from `analysis/a4/results.json` (`part_a/a4_results.py`), and
Part B's figures by `fig_restarts_build.py` and `fig_restarts_final.py` from `analysis/restarts-build/` and
`analysis/restarts-final/` (`recursive/build_results.py`, `recursive/final_results.py`). **`fig4.py` assembles the
paper's Figure 4** (a memory ablation with E8's Claude Code arms; b the ladder; c scaling; d reuse; e the campaign's
trajectory beside Part B's crossing) from those panel functions and results files; the separate panel files and the
campaign-revisit panel (`fig4b.*`) are for the SI.

Two closing analyses read the run records only: `analysis/accounting.py` (answers, checks, engine sessions, failed
attempts by named reason and how each ended, new tokens by engine and phase, harness revisions, and the supervisor's
timeline; `analysis/accounting/`) and `analysis/e8_provenance.py` (E8's contradicted statements against the raw Claude
Code streams: the engine layer records a WebFetch as opened even when it returned unreadable PDF bytes or a redirect
notice, CL-26; `analysis/e8-provenance/`; it needs `OOPC_STUDY_CODE` at the freeze-2 worktree, whose stream parsers it
uses).

Fig. 5 (the case studies and E9, experiment A5) is drawn by `fig5.py` from `analysis/a5/results.json`, which
`part_a/a5_results.py` computes from the A5 records alone (each replicate's driver items and checks, cs4's first
askings, the blind scores joined to their keys, E9's `review.json`, and the 2026-10-13 E9 run with its blind scores),
cross-checked against the harness's own reports; it also writes `results.md`, each A5 prediction judged with its
numbers. The blind scoring keeps counts per answer, not each value, so panels a–c draw those counts, not the values.

```
export OOPC_STUDY_ROOT=$PWD    # from a worktree: the main checkout's path
python -B studies/macromolecules/figures/fig3.py           # fig3a … fig3f, fig3
python -B studies/macromolecules/figures/fig4_records.py   # fig4b, fig4d, fig4e, fig4_records
python -B studies/macromolecules/part_a/a5_results.py      # analysis/a5/results.json, results.md
python -B studies/macromolecules/figures/fig5.py           # fig5a … fig5e, fig5
python -B studies/macromolecules/figures/fig4.py           # the assembled Figure 4 (after fig4ac, fig4b and Part B's results)
python -B studies/macromolecules/analysis/accounting.py    # analysis/accounting/results.json, results.md
python -B -m unittest discover -s studies/macromolecules/tests -p "test_figures.py"
```

The test draws every panel from small synthetic inputs in a temporary folder; with `OOPC_STUDY_ROOT` naming a checkout
that has A1's outputs it also renders both figures from them into a temporary folder and checks the captions against
`figures-kf/panels.json`. Fig. 5's test builds small synthetic A5 records, runs `a5_results.py` on them and draws
the figure from its output. It needs matplotlib and numpy and skips without them.

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
- `driver.py`, left as it ran: a source's captured text is stored in the arm's workspace when it is first fetched
  (`reviewer.capture_sources`), and every later check of that arm that cites the source is given that capture, even
  one fetched days earlier, rather than fetching it again. So it ran in the 2026-10-16 case studies; a check's statements
  record `evidence: captured` when they were judged on such text.
- `driver.py`, changed 2026-10-18 after an independent review (no case-study result changes): a check timeout is now
  tried once more, as a research timeout was; a run gives the questions with a failed item one more pass, 10 minutes
  after the others, and counts what still failed (`failedItems`); a question stopped part-way whose answers are more
  than 12 hours old has every arm answered again (`previousAnswers`); and `driver.Guard` keeps each session's start for
  sleep detection per calling thread, since the restarts' research and audit worker share one guard. A failed answer
  that keeps its error does not count as unanswered there, so an arm that keeps failing does not make every resume
  answer its question again.
- cs4's first askings (`case_studies.py`) run their reviews through freeze-2's own background review, which counts a
  review attempt that failed for a transient reason towards the two a deposit gets (there is no `forgive` there, unlike
  E9 and the restarts). It matters only when a first asking saves a flagged or sampled finding; 2026-10-16's saved
  none.

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

## Part A: the controlled runs on KF (study-freeze-2)

`part_a/` holds the harness of Part A's runs A2–A5 and E8 (`macromolecules-study-plan.md`, "Plan of record —
2026-10-18" and "Part A harness and predictions"). Every run goes through the shared driver from tag `study-freeze-2`: set
`OOPC_STUDY_CODE` to the worktree `.oopc/study/freeze-2` (and, from another worktree, `OOPC_STUDY_ROOT` to the main
checkout). `prepare` and `run` refuse unless the code is the tag (`case_studies.frozen`), the researcher prompt, both
models (Codex and Claude Code), the graph release and KF's fingerprint are the pins (`part_a.PINS`), and neither
freeze-2's `oopc` and `config` nor the harness's own `studies/` has uncommitted changes (`dirty`). The harness revision
is that of the repository holding `part_a.py`, so runs launched from a worktree of the harness commit with
`OOPC_STUDY_ROOT` at the main checkout record the right one. KF, the live store, is read only through read-only copies;
every arm answers on its own copy.

```
python -B studies/macromolecules/part_a/part_a.py prepare A2|A3|A4|A5|E8 [--shards N] [--into DIR]
python -B studies/macromolecules/part_a/part_a.py run 2026-10-kf-scaling/r1-s1 [--hours H]   # one folder per process
python -B studies/macromolecules/part_a/part_a.py status
python -B studies/macromolecules/part_a/part_a.py report A2|A3|A4|A5|E8
python -B studies/macromolecules/part_a/part_a.py questions A2|A4|E8
python -B studies/macromolecules/part_a/part_a.py score-e9-2026-10-13      # a Claude session, read-only on that run
python -B studies/macromolecules/part_a/stores.py cuts|resample OUT        # the store builders alone, into OUT
```

- An experiment's folder holds its stores (`stores/`), its layout (`experiment.json`) and its run folders
  `r<replicate>-s<shard>`: each a driver plan with every arm for its questions, dealt round robin from the experiment's
  fixed order, so several can run side by side and a question's arms are still answered in turn and checked together.
  The shard count is fixed once prepared. Each run folder records the pins, its stores' fingerprints and the harness's
  git revision and cleanliness (`pins.json`), and each `run` appends the revision it ran from (`runs.jsonl`).
- A2 `2026-10-kf-scaling`: test 1's held-out questions in test 1's order; P, K0 (test 1's frozen store as it is), KF200,
  KF1, KF2 (`stores.cut`: scaling's cut rule on KF, with KF's merges undone and the cleanup's re-reviews returned to
  their latest review made by the cut), KF, and MF1, MF (web off); three replicates. The 2026-10-02 cut is compared with
  K0 in `stores/cuts.json` and reported, not gated on.
- A3 `2026-10-kf-resampled`: 20 resampled stores (`stores.resample`: nested random subsets of KF's 953 questions at 100,
  200, 400 and 800 under five seeds; records without a question, the "legacy" import, in every store), with K0 and KF
  answered beside them as same-day anchors.
- A4 `2026-10-kf-ladder`: 30 campaign first asks with at least 3 findings in KF, never revisited in the campaign, alone on
  their polymer–property pair among its first asks (`candidates`), each asked exactly, in other words and as a sibling
  with the campaign's own revisit wording, none but the exact one word for word a campaign question (`ladder`); K0 and
  KF; two replicates.
- A5: case studies `2026-10-case-studies-r2` … `-r5` (`case_studies.py`, parameterized by folder) and E9
  `2026-10-planted-kf-r1` … `-r5` (`planted.py`'s replicate functions: fresh KF copies, the plan `before` with C, A1,
  A2, one review on Codex, then `after` with B1, B2). A cs4 first asking that failed for a transient reason is asked
  again on a fresh trace run, one that failed otherwise is final and the replicate goes on; the E9 review is done once
  its deposit is reviewed (a plant left unassessed is recorded as skipped), a transient failure is taken back and
  another tried once more. A STOP file in a replicate's folder stops whichever part runs. Once every item is settled,
  `run` scores the replicate blind (`score.py`; E9 with its own rubric of 2026-10-18); a group whose result leaves out a
  code is scored once more, and a second failure is final, so it costs no session on a relaunch.
  `score-e9-2026-10-13` scores the 2026-10-13 E9 answers by the same rubric. The combined report, with 2026-10-16's
  run as the first case-study replicate, goes to `2026-10-kf-a5/report.json`.
- E8 `2026-10-kf-e8` (owner, 2026-10-18: runs): test 1's 20 near questions in test 1's order; K0c and KFc, the
  researcher on Claude Code (`engine: claude-code`, web on) on copies of K0 and KF, checked by the same Codex checker
  as every other run; one replicate. The driver's Guard lets Claude start while its quota is above 0.
- `report` writes `rows.json` (one row per answer: costs, citations, the check's measures, the store's size, and whether
  the question's parent is in the arm's store) and `report.json`: per stratum or rung each arm's counts and its pairing
  with the reference, the further pairs, and the estimators the predictions use (`estimate.py`: paired ratios and
  differences, the KF2 parent split, the within-question scaling slope, A3's coverage model and seed spread, pass on
  store size by mixed logistic regression).

`tests/test_part_a.py` builds its own release and stores in a temporary folder (on today's code, like the driver test:
`OOPC_STUDY_CODE=$PWD`); its last test reads the real inputs read-only and skips without them.

## Part B: five fresh restarts (built 2026-10-18)

`recursive/restart.py` runs the restart study (`docs/exec-plans/active/restart-study-plan.md`): five restarts R1–R5,
each building an ontology from an empty store over five rounds with the self-improvement heuristics on, then one final
evaluation. It runs only from tag `study-freeze-2` (`case_studies.frozen()`) and asserts the pins at prepare and at every
run: prompt `0b7bb1483235`, Codex `gpt-6.1-sol`, Claude Code `claude-opus-5-5`, release
`oopc-6ad56d8b354d053bcc3cf3a1`. It reuses test 2's steps (`recursive.configure` points `recursive.py` at a restart's
folder; called as before, `recursive.py` runs test 2 as it ran):

- **tasks**: `make_tasks.py --restart N` (seed `oopc-restart-2026-10-18-R<N>`) draws 5 × 100 tasks with test 2's mix;
  round 1's revisits ask round 1's first asks again, later rounds' ask earlier rounds'. What every restart excludes is
  decided in `make_tasks.restart_exclusions`: test 1's held-out and test 2's dev polymer–property pairs, counted as
  asked when the property shares a significant word (so the bank's comparison groups, which name properties in their
  own words, are screened too), and their far polymers; and its one exception (owner, 2026-10-18): the 20 campaign
  questions test 1's near held-out questions were drawn from are first asks of every restart, 4 per round within the
  mix, revisited only exactly or in other words, never as a sibling (which would ask the held-out question's angle).
- **a round's tasks** go through freeze-2's own loop on Codex: `ask.Questions` (deposits by the narrow review policy),
  then `ask.after_answer` (Crossref titles, source captures) and `reviewer.review` in a fresh Codex session, as the app
  does once an answer is delivered; 12 per round get `parity.check` with the session record. No app server.
- **snapshot** S1…S5; **improver** (`recursive.improve`, held to 600 and 1,000 characters); **dev** through `driver.py`,
  the current and candidate prompts as arms with their own prompt files on copies of the snapshot, in two shard
  folders at once (`--dev-sessions`); **adoption** by `recursive.decide`.
- **failures**: a task, review, check, dev answer or improver call that fails for quota, rate-limited, not-signed-in or
  interrupted stops the phase and stays to do; a rerun resumes it, and no dev decision is taken while such a failure
  remains. Two harness-level repairs of freeze-2's behaviour keep this so: a review attempt that failed that way is
  taken back (the store would count it towards the two a review gets), and a task failed that way is retried on a
  fresh trace run (freeze-2's `Questions.retry` reuses the failed attempt's finished run and crashes).
- **refusals** (after the 2026-10-18 review): nothing prepares or runs if the code under test (`oopc`, `config`) or
  the harness's own `studies/` has uncommitted changes, if a pin changed, or if a snapshot changed since it was taken
  (`snapshots.json` holds each one's `driver.fingerprint`, checked before a run, before each dev evaluation and at
  `final-prepare`). A refusal exits non-zero before `state.json` is touched, so the supervisor holds the stream. Each
  run appends the code's and the harness's commits and the Codex floor to `runs.jsonl` in its folder; the harness
  commit is read from the repository `restart.py` runs from, which may be a worktree with `OOPC_STUDY_ROOT` set.

```
python -B studies/macromolecules/recursive/make_tasks.py --restart N [--out FOLDER]   # optional; prepare draws them too
python -B studies/macromolecules/recursive/restart.py prepare --restart N             # -> .oopc/loop/harness/2026-10-restarts/R<N>/
python -B studies/macromolecules/recursive/restart.py run --restart N                 # resumable; STOP in R<N>/ stops it
python -B studies/macromolecules/recursive/restart.py status --restart N
python -B studies/macromolecules/recursive/restart.py final-prepare [--shards 6]       # refused until R1–R5 have finished
python -B studies/macromolecules/recursive/restart.py final-run --shard J             # -> 2026-10-restarts/final/shard-<J>/
python -B studies/macromolecules/recursive/restart.py final-status
```

with `OOPC_STUDY_CODE=.oopc/study/freeze-2` (and `OOPC_STUDY_ROOT` set to the main checkout when the code runs from
another worktree). Each restart is one process with its own folder and no app server, so the five run at once. The final
evaluation's shards each hold every arm (E0, then per restart P0 × S1–S5, Pk × Sk unless Pk is P0, P5 × S0 unless P5 is
P0) for test 1's questions j, j + shards, …; a STOP in `final/` stops every shard.

For the evolved prompts, a `driver.py` researcher arm may carry `"prompt"`, the path of an instructions file used in
place of the code's `ask.RESEARCHER`. The plan records its version (the first 12 hex digits of its SHA-256, as
`ask.prompt_version` gives the code's), `run` refuses if the file's text changed, and the prompt is rendered as
`ask.researcher_prompt` renders the code's (`prepare` checks that the two agree). Arms without one, and every plan
written before (the 2026-10-16 case studies), are unchanged.

Files: `recursive/restart.py` (new), `recursive/make_tasks.py` (the round draw split into helpers; test 2's files are
drawn again byte for byte), `recursive/recursive.py` (`configure`, and `run`, `run_tasks` and `dev` taking their
phases, round class and dev evaluation), `driver.py` (the per-arm prompt). Tests: `tests/test_restart.py` (a whole
restart of two tiny rounds through every phase, resumed after a task, a review and a dev answer fail for transient
reasons; the five task sets on the real held-out and dev questions; the final plans) and additions to
`test_driver.py` (the per-arm prompt) and `test_recursive.py` (`AsItRan`: test 2's phases, limits and task sets).
`test_restart.py` exercises freeze-2's code and skips under test 2's freeze:

```
OOPC_STUDY_CODE=$PWD python -B -m unittest discover -s studies/macromolecules/tests -p "test_restart.py"
```

## The supervisor of the 2026-10-18 runs

`supervise.py` keeps Part A's and Part B's streams going in the background (launch brief, Phase 2). A stream is one
resumable harness command (a restart, a Part A folder, a final-evaluation shard), listed in priority order in a private
`streams.json` with a cap on how many run at once. The supervisor launches a stream while fewer than the cap run and
Codex is above its floor, never launches one whose lock another process holds, leaves a completed one alone, holds one
that crashed, was refused or carries a STOP file, and reruns any other stopped one after a cooldown (15 min after
rate-limited, 30 min after quota, 5 min otherwise, doubled while it keeps stopping quickly). It only reruns the
harness's own command, so what is done stays done. Launches and exits, with the git revision, go to `activity.jsonl`
beside `streams.json`.

It runs from a dedicated worktree of the harness commit that nobody edits (`.oopc/study/harness`), and every command
it launches runs from there too, so an edit in the shared checkout never changes what a relaunch runs; the data root is
the main checkout (`OOPC_STUDY_ROOT`). A stream may carry its own environment: E8's runs carry
`OOPC_STUDY_CLAUDE_FLOOR`, so its Claude Code researcher stops above the Claude quota Part B's improver needs.

```
git worktree add --detach .oopc/study/harness <harness commit>
OOPC_STUDY_ROOT=$PWD OOPC_STUDY_CODE=$PWD/.oopc/study/freeze-2 OOPC_STUDY_CODEX_FLOOR=0 caffeinate -i \
  python -B .oopc/study/harness/studies/macromolecules/supervise.py .oopc/loop/harness/supervisor/streams.json
```

## Part C: ontology refinement (study-freeze-3)

`refinement/` holds the harness of Part C (`docs/exec-plans/active/ontology-refinement-plan.md`, approved 2026-10-21,
Stage 1 only): a curator reads the researcher's traces on KF and proposes ontology edits from a closed list, an
independent reviewer approves them, and the refined ontology (release O and the annotated store copy) is tested on 180
withheld questions (H, N, L) and the case studies C1–C8. `refinement/pins.py` names what every step shares: the pins
(tag `study-freeze-3`, prompt `0b7bb1483235`, Codex `gpt-6.1-sol`, Claude Code `claude-opus-5-5`, the seed release, KF's
fingerprint), the inputs, the question sets, the edit list and its groups, the arms, the case studies' seeds and each
session's time limit. Everything is written under the private run folder `.oopc/loop/harness/2026-10-refinement/`, one
subfolder per step. Every step runs from the main checkout with this environment (the Codex floor at 0: the owner's
2026-10-18 approval to max out Codex extends to Part C):

```
export OOPC_STUDY_ROOT=$PWD                              # the data: the main checkout
export OOPC_STUDY_CODE=$PWD/.oopc/study/freeze-3         # the code under test: tag study-freeze-3
export OOPC_STUDY_CODEX_FLOOR=0
```

The steps, in the order they run (each refuses to run out of order, and each is resumable unless it says otherwise):

| # | Command (`python -B studies/macromolecules/refinement/…`) | What it does | Engine |
| --- | --- | --- | --- |
| 1 | `mine.py check` | freeze-3's replay check: every recorded search of Part A's KF arms, replayed on a copy of KF under freeze-3, must return exactly the recorded ids (`mine/replay-check.json`) | none |
| 2 | `questions.py build` | H (test 1's held-out set) and N (60 new first asks) | none |
| 3 | `questions.py write-L` | L: one session per batch of 10 KF pairs writes the questions, web on | Codex |
| 4 | `questions.py hashes` | `questions/hashes.json`, written once all three sets exist | none |
| 5 | `questions.py commit --write`, then commit `refinement/commitments.json` | the sets' hashes committed before mining and curation (`propose.py curate` refuses otherwise) | none |
| 6 | `mine.py mine` | the check again, then the derivation pool (pinned in `mine/pool.json`), misses, hops and the dossier, with ids an edit cites; refused unless the hashes fix H, N and L | none |
| 7 | `propose.py curate` | one session per dossier batch proposes edits from the closed list, each screened | Claude Code |
| 8 | `propose.py review` | one fresh session per batch approves or rejects each screened edit | Codex |
| 9 | `propose.py assemble` | `overlay/edits.json` and the graph and store overlays, written once | none |
| 10 | `overlay.py check` | the deterministic checks; an edit a check refuses goes into `overlay/excluded.json` by hand, then check again | none |
| 11 | `mine.py effects` | the drop step: each edit alone on its own root, replayed on the pool; an edit that loses more results than it fixes misses and hops is excluded; the group totals | none |
| 12 | `overlay.py build` | the seed root, release O and the stores KF, KF-refined, K0, K0-refined, fingerprinted; refused unless `mine/effects.json` matches the inputs in force | none |
| 13 | `run.py commit --write`, then commit `refinement/commitments.json` | the overlay, releases, stores and pool committed before any withheld task is answered (`run.py` refuses otherwise) | none |
| 14 | `run.py pilot` | the first question of each set on the screen's arms; checked by hand, then `touch .oopc/loop/harness/2026-10-refinement/pilot/CHECKED` | Codex (researcher, checker) |
| 15 | `run.py prepare-screen --shards N`, then `run.py run-screen --shard K` per shard | the screen: 180 questions on B0, B and O+ (540 answers and checks) | Codex (researcher, checker) |
| 16 | `lookup.py judge`, then `lookup.py report` | the offline lookup measure: the blind relevance judge, one session per question (no web), then recall, results lost, wrong-polymer results and the hops removed | Codex (judge only) |
| 17 | `cases.py select` | the case studies C1–C8 by mechanism, from the replay and B's traces only (`cases/selection.json`), and for each case short of three the pairs its rule qualifies (`cases/pairs.json`) | none |
| 18 | `questions.py write-C`, then `questions.py commit --write` and commit `refinement/commitments.json` | the questions written for the purpose for the cases short of three (`questions/C.json`), from `cases/pairs.json`, fixed by hash and committed | Codex |
| 19 | `run.py prepare-cases`, then `run.py run-cases --replicate R` for R = 1…5 | the case studies on B0, O0, B and O+ | Codex (researcher, checker) |
| 20 | the analysis (Measures, Attribution, Figure) | from the records only; not in the harness yet | none |

- **The drop step** (`mine.py effects`, plan Procedure step 4) builds one root per approved edit in force
  (`overlay.edit_root`: a release of the seed plus that graph edit, or a KF copy with that store edit, with upkeep's
  polymer-id rule against its release) under `mine/effects-roots/`, deletes it after its replay, and replays only the
  pool searches the edit can change: those whose query mentions, as whole words, a name whose graph entry the edit
  changes, a name of a polymer whose lineage it changes or under whose lineage it refiles a finding, or a name of a
  property term it adds; and those that return on the base a source it links or a finding it re-indexes. Every other
  search returns on the root exactly what it returns on the base. Fixes are misses fixed plus held-unreached hops made
  reachable, losses are results lost (a finding a search returned and its answer cited, which the same call no longer
  returns); an edit whose losses exceed its fixes goes to `overlay/excluded.json` with its numbers. The group roots'
  totals (`overlay.root_for` per group and all together) follow, for the attribution. `mine/effects.json` names the
  hashes of its inputs and the code's commit, and `overlay.py build` refuses unless they are the inputs in force.
- **Commitments.** `refinement/commitments.json` is tracked: `questions.py commit` and `run.py commit` print its
  entries from the private files (the question sets' hashes; the overlay files, both releases, each store's
  fingerprint and table hash; `mine/pool.json`; the case questions), and with `--write` put them in it for a person to
  commit. A committed entry is never replaced, and curation and every run check the private files against it.
- **Refusals.** Nothing calls an engine or searches a refined root unless the code under test is the tag
  (`pins.frozen`); `run.py` also refuses uncommitted changes in the code or `studies/`, an entry of commitments.json
  missing or other than the private files, a store or table that is not the one recorded, and a refined ontology that
  changes nothing; the screen waits for `pilot/CHECKED`; a question set that is not its hash is refused everywhere. A
  STOP file in a run folder stops that run at a boundary.
- **Status**: `propose.py status`, `overlay.py status`, `questions.py status`, `run.py status`, `mine.py summary`.

The tests (`tests/test_refinement_*.py`) build their own seeds, releases, stores, traces and run folders and use
scripted engines. Run them on today's code, and once more on freeze-3, where the tests of what freeze-3's search reads
(links and property terms) also run:

```
OOPC_STUDY_CODE=$PWD python3 -B -m unittest discover -s studies/macromolecules/tests -p "test_refinement_*.py"
OOPC_STUDY_CODE=$PWD/.oopc/study/freeze-3 python3 -B -m unittest discover -s studies/macromolecules/tests \
  -p "test_refinement_*.py"
```

## Confirmation run (study-freeze-4)

`confirm/confirm.py` runs the confirmation of Part A's headline results on the released code, 0.13.0
(`docs/exec-plans/active/confirmation-plan.md`; predictions written before any run): A2 confirmed (test 1's 60
held-out questions in test 1's order, K0 and KF, one replicate, researcher and checker on Codex) and the case studies
confirmed (cs1–cs4 once, as a sixth replicate of A5, scored blind by `case_studies/score.py` on Claude Code). It reuses
Part A's harness: `confirm.configure()` points `part_a.py` and `case_studies.py` at this run's pins, stores and folders
for its own process, as `recursive.configure` does for a restart; the finished studies' files are unchanged. KF is read
only from its frozen copy `.oopc/study/analysis/kf/workspaces/KF` (store and graph release), never from the live store;
K0 is test 1's store. Nothing prepares or runs unless the code under test is tag `study-freeze-4` (`918a64c`), the
researcher prompt (`86404bf073ce`), both models (Codex `gpt-6.1-sol`, Claude Code `claude-opus-5-5`) and the graph
release (`oopc-6ad56d8b354d053bcc3cf3a1`) are the pins, KF's copy and K0 have their fingerprints, and neither the code
nor the harness's `studies/` has uncommitted changes. Every command runs from the main checkout with:

```
export OOPC_STUDY_ROOT=$PWD                              # the data: the main checkout
export OOPC_STUDY_CODE=$PWD/.oopc/study/freeze-4         # the code under test: tag study-freeze-4
```

In order (each resumable; a STOP file in a run folder stops it at a boundary):

```
python -B studies/macromolecules/confirm/confirm.py prepare-a2 [--shards N]  # -> .oopc/loop/harness/2026-10-confirm-a2/r1-s1 … r1-sN
python -B studies/macromolecules/confirm/confirm.py run-a2 [--shard K]       # Codex; one process per shard folder
python -B studies/macromolecules/confirm/confirm.py prepare-cs               # -> .oopc/loop/harness/2026-10-confirm-cs/
python -B studies/macromolecules/confirm/confirm.py run-cs                   # Codex, then the blind scoring on Claude Code
python -B studies/macromolecules/confirm/confirm.py score-cs                 # Claude Code: only what is still to score
python -B studies/macromolecules/confirm/confirm.py status
python -B studies/macromolecules/confirm/confirm.py report                   # -> .oopc/study/analysis/confirm/results.json, results.md
```

- `2026-10-confirm-a2` holds `experiment.json` (the layout) and one driver folder per shard, `r1-s<k>` (one by
  default), each with both arms' store copies, its plan, `pins.json`, `runs.jsonl`, items, streams and the driver's
  report. On this code a researcher arm runs through `parity.answer_ontology`, both turns, saving nothing; its metrics
  record `newTokens` over both turns, `seconds` to the answer, `depositSeconds` and `totalSeconds`.
- `2026-10-confirm-cs` holds a case-study replicate as Part A's did: `pins.json`, the four studies' driver folders,
  `cs4-first` (the first askings through the normal loop on a KF copy, saved and reviewed there), `cs4-repeat`, and
  `scoring/`. `run-cs` scores blind once every item is settled; `score-cs` scores only what is left.
- `report` reads the records only and writes the plan's predictions 1–5, each with its numbers and met or not met,
  against Part A's recorded values (`analysis/a2a3e8/results.json`, `analysis/a5/results.json`, and
  `2026-10-kf-scaling/rows.json` for Part A's KF seconds on the same questions), and the plan's rule for the
  manuscript. KF/K0 is paired per question as in Part A (`part_a/estimate.py`). `--into DIR` runs any step on folders
  under DIR instead (a dry run on the real inputs).

Its test builds its own release and stores, runs both parts with a scripted engine and judges the predictions on a
hand-made example; run it on today's code and on freeze-4:

```
OOPC_STUDY_CODE=$PWD python3 -B -m unittest discover -s studies/macromolecules/tests -p "test_confirm.py"
OOPC_STUDY_CODE=$PWD/.oopc/study/freeze-4 python3 -B -m unittest discover -s studies/macromolecules/tests -p "test_confirm.py"
```

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
| `confirm/confirm.py` | 823 | the confirmation run on study-freeze-4 (A2 and the case studies, and its report) |
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
200-task) exercise the code as it ran, under the default `CODE` (the freeze worktree). The driver, case-study,
case-study scoring and reviewer-agreement tests exercise today's code, so run them with `OOPC_STUDY_CODE` set to the
repository:

```
OOPC_STUDY_CODE=$PWD python -B -m unittest discover -s studies/macromolecules/tests -p "test_driver.py"
OOPC_STUDY_CODE=$PWD python -B -m unittest discover -s studies/macromolecules/tests -p "test_case_stud*.py"
OOPC_STUDY_CODE=$PWD python -B -m unittest discover -s studies/macromolecules/tests -p "test_part_a*.py"
OOPC_STUDY_CODE=$PWD python -B -m unittest discover -s studies/macromolecules/tests -p "test_review_agreement.py"
```

The case studies (`case_studies/case_studies.py`, run from tag `study-freeze-2`) are scored blind by
`case_studies/score.py`: one fresh Claude Code session per study, without web access, reads the answers with their
arms and citations hidden and counts what the study plan's rubric asks.

| Test | Was |
| --- | --- |
| `test_observation_200_guard.py`, `test_observation_200_harness.py` | `2026-10-03-200/test_guard.py`, `test_harness.py` |
| `test_campaign.py`, `test_ablation.py`, `test_scaling.py`, `test_recursive.py`, `test_planted.py` | the `test_*.py` beside each script |
| `test_driver.py`, `test_polymer_filter.py`, `test_review_agreement.py` | new 2026-10-14 (pre-publication cleanup) |
