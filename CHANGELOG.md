# Changelog

## 0.13.0: answers first, findings after (2026-10-26)

- An answer is shown as soon as the research turn ends; the same engine session
  is then resumed in the background to write the findings and source notes it
  read, which are saved and reviewed as before. With almost nothing saved, the
  answer turn writes 38% fewer output tokens (the findings, 30–100 s of
  generation on research-heavy questions, come after it); a resumed turn reuses
  the prompt cache (97% cached). Parity holds (owner-approved plan of
  2026-10-25, `docs/exec-plans/active/app-latency-plan.md`).
- A saved session lives only in a private working folder outside the repository;
  Codex's state databases are kept there too, so nothing of a question reaches
  `~/.codex`, and every saved session is deleted when its last turn ends. Even
  unsaved, a Claude Code session's fetched files are deleted with it.
- A question asked right after another still waits for the last answer's
  findings to be saved, so a follow-up reads them (letting it start sooner was
  tried and made that a race).
- Robustness: a failed question retried by hand gets a new trace (its old one
  refused every knowledge search); an expired Claude Code sign-in fails as
  `not-signed-in`, not `crashed`; findings left "saving" by a stopped process
  are settled without a restart; Claude Code's unreported quota is named so.
- The Mac app builder (prototype) builds from committed code only and records
  the commit in the bundle.

## 0.12.0: the core loop, frozen for the case studies (tag `study-freeze-2`, 2026-10-16)

Pre-publication cleanup (owner's plan of 2026-10-13):

- After each answer the cited sources' open copies are fetched and their text
  kept privately; reviewers and answer checkers read it first and the live page
  second. Checks lead with measures that do not depend on a page opening that
  day (contradicted statements, completeness, whether the result was given),
  and parity checks both arms in the same run. Canaries cover a changed value,
  an added condition, another paper's source, a mistyped title, and true
  controls, one with its method only in the methods section.
- Review policy: figure readings, conversions and combined values wait for a
  reviewer; other findings are added on the researcher's judgement, with a spot
  sample reviewed. Reviewers read the methods section, check titles, and quote
  a labelled excerpt.
- Researcher prompt `0b7bb1483235`: test 2's two adopted edits (open HTML
  copies; a patent example or data sheet answers "a published study"), an
  added finding with an implausible or unshown value is a lead, and excerpts
  carry a label.
- Polymer names a source could misread (PEI, PFA, PPO, MC, MF) are written out
  from context when a finding is saved, or sent to review. The seed is the
  wiki at `ba38b87`: 274 polymers with reviewed trade names and family links.
- DOI titles come from Crossref. `oopc upkeep` cleans the store once before a
  freeze (access requeues, excerpts quoted by reviewers, titles, polymer ids,
  duplicates); an approved polymer id is never changed again.
- Codex is the default engine; rate limits are named apart from quota; an idle
  watchdog stops stalled review and check sessions; SQLite connections open and
  close in turn (a deadlock in SQLite 3.51.0).
- One tested driver runs the case studies (sleep detection, retries, ledger
  costs, a store fingerprint over every field).

The core loop:


- Replace the milestone evaluation machinery with one loop: ask, answer with
  citations, save findings, review each finding against its source, reuse
  reviewed findings first. Reviewer qualification panels, calibrations,
  tranches, protected audits, weekly campaigns and successor protocols are
  retired; they remain at tag `v0.11.6` and their recorded data stays on disk.
- One engine layer runs Codex or Claude Code sessions. Every call returns a
  valid answer or fails with a named reason; transient failures retry once.
- The researcher app gains a Knowledge page (loop counts, findings by review
  status, Run review now, research queue) and shows each answer's findings with
  the reviewer's reason. Weekly research-time setup is gone.
- `oopc import-legacy` copies the 0.11 admitted findings, their sources, source
  notes and earlier questions into the new store without changing them.
- The codebase shrinks from 138 modules (61.7k lines) to 24 (6.7k lines).

## 0.11.6

- Write trace-reader subprocess results explicitly as UTF-8, preserving Unicode
  event content when the host uses a non-UTF-8 locale. This supersedes the 0.11.5
  packages, which were held before publication after the locale failure was found.

## 0.11.5

- Read contributed terminal trace events from a bounded private SQLite snapshot,
  preserving committed WAL rows while leaving original databases and sidecars
  unchanged. Isolate raw file reads from the caller’s SQLite locks and reject
  observed source changes without automatic retries.
- Derive authorized contribution agents from the same verified event snapshot,
  preserving existing contribution hashes, permissions and scientific judgments.

## 0.11.4

- Give newly created ordinary research tasks a versioned proposal contract with
  exact Observation and experimental Recipe field locations. Add field-specific
  correction hints while preserving admission rules, archived rejection reasons,
  and all existing task requests and judgments.
- Find the bundled Codex CLI in the nested ChatGPT app layout before falling
  back to older app or PATH installations; explicit overrides keep precedence.
- Allow explicit continuation of another existing ordinary campaign job when
  a different job has an unresolved worker outcome. Preserve the unresolved
  outcome, charges, retry limits and campaign publication gates.
- Allow an operator to remove a head-to-head cohort from automatic scheduling
  without changing its registration, answers, judgments or completion status.

## 0.11.3

- Keep private and out-of-scope consolidation leads from blocking ordinary
  public research on an irrelevant live trace read. Reconstruct their frozen
  candidate and reviewer receipts before routing, and require exact contribution
  authority before every new eligible assignment.
- Store mutable campaign state as compact private JSON and measure private-task
  allocation against that representation. Preserve all retained records and the
  existing storage limits, so formatting overhead does not block new questions.

## 0.11.2

- Retain the exact payload returned by local-knowledge tools in private task
  traces, so later inspection can distinguish returned content from a count or
  identifier summary.
- Preserve available Codex web-action metadata in private worker records.
  Historical fields that were not captured remain unknown; a recorded action
  does not establish source-body delivery or scientific support.

## 0.11.1

- Finish independent deposit review before acquiring the admission lease, so
  admission avoids a nested campaign lock and preserves the settled stage charge
  and accepted records when both operations use the same campaign.
- Decode retained reviewer verdict and source-check fields from their wire
  representation before ordinary admission, preserving the original review.
  Version new receipts and expected-use registrations while retaining exact
  verification of historical registrations.
- Let ordinary research proceed when optional recovered-baseline feedback
  requires the intact historical 0.6.4 adapter. Keep the old baseline blocked
  from execution under 0.6.5, and retain all identity and tamper checks.

## 0.11.0

- Add an explicitly selected 1,200-second measured-review condition shared by
  fresh qualification panels, controls and comparisons, preserving historical
  requests, time limits and judgments.
- Distinguish fresh admitted assertions from assertions with reviewed expected
  uses. Bound prospective expected-use input to complete focal assertions and
  qualified dependencies without traversing an identity's entire seed neighborhood.
- Correct Ask and Settings review/privacy notices, refresh the quota hint when
  switching engines, and keep live elapsed time advancing between worker events.

- Ship a short tester guide covering offline installation, subscription sign-in,
  Ask, live progress, unreviewed deposits and privacy. Keep the finite eight-row
  coverage inventory explicit about retained reviewed components and unresolved
  worked-example gaps; this software release establishes no scientific gain.

- Tranche readiness is blocked only by pending source-maintenance items that touch
  the candidate's own changed records or their sources; publication keeps the
  global gate (owner decision D4). Owner dispositions
  (`oopc/owner_disposition.py`) close quarantined, review-uncertain access-gap
  items without any scientific finding or record-status change; eight such items
  were closed on 2026-09-27.

- Settle an evolution stage's charge after its worker exit is verified: the
  observed stage time plus 60 s is charged and the unused reservation refunded
  once (receipt `settlement`, owner decision D1). Scheduler stages default to
  1,900 s, and every third tick runs the coordinator's own stages.

- Ask runs the researcher only (private task protocol v4). Answers say they were
  not independently checked; the independent reviewer runs in the improvement
  loop, which alone can admit findings. v3 answers keep their recorded reviews.
- Deposit what each question found as unreviewed local knowledge: source notes
  with short verbatim excerpts in a private full-text store, and local draft
  records. Later questions search both before the web; polymer pages list the
  drafts as unreviewed. The coordinator's new `deposits` stage reviews them and
  runs the ordinary admission gate.
- Show live progress while a question runs: ontology lookups, graph hops,
  local-knowledge checks, web searches, pages read and sites, the latest action
  and elapsed time; finished answers keep an effort and token summary.
- Let a waiting private question make scheduled stages pause at their next call
  boundary, so Ask no longer waits for a whole scheduler stage.
- Read reviewer claim verdicts given as a list of `{id, verdict, rationale}` like
  the equivalent ID-keyed object (claim-verdict interpretation v2). A Claude
  reviewer returned that form and its whole review was discarded; answer pages
  now show such a retained independent reply, labelled as recovered, without
  changing the task's recorded status.
- Add the head-to-head baseline `oopc evolution efficiency`: the ontology
  researcher against a fresh direct Claude Code (or Codex) session on topics the
  local knowledge covers, with token, time and tool use beside independent
  answer checks.

## 0.10.0

- Run the improvement loop from an engine-neutral local launchd job
  (`oopc schedule install|tick|status|uninstall`). Ticks recover only proven
  worker exits, advance explicitly pinned reviewer qualifications, then run one
  `evolution advance --live`, logging statuses and each engine's quota reading.
- Pool weekly research across Codex and Claude Code for campaigns created from
  now on: each job binds one signed-in engine above the reserve before its first
  dispatch and keeps it for every phase. Earlier campaigns keep Codex.
- Add fixed-answer reviewer qualification protocol v2 with preparation wire v3:
  a separate 1,800-second preparation limit stated to the model, coordinator-bound
  criterion order, canonical reading of native arrays and single-key unit-ID
  objects, and one fresh session after a mechanical preparation failure. Adverse
  adjudications stay terminal; measured reviews are unchanged.
- Verify distillation-derived memory admissions against their frozen
  specification, grounding and originating task rubric. Before this, every
  candidate containing one failed admission reconstruction.
- Reuse pure verification results within one operation, re-checking every file
  they read. Warm preparation on the standard fixture falls from 5.2 to 1.6
  seconds (p95); the full test suite from about 240 to 140 seconds.
- Report each protocol's items by latest status in `tools/protocol_inventory.py`.
- Check macOS and Windows installations on pull requests and manual runs only.

## Earlier unreleased changes, included in 0.10.0

- Add a researcher application as the inspector's home page: **Ask**, **Polymers**,
  **Improvement** and **History**. Answers lead with the answer, numbered sources,
  one review status and retrieval effort; polymer pages draw canonical structures
  with repeat-unit brackets and keep imported drafts labelled as unreviewed.
- The improvement page reads the existing recorded learning status. It shows no
  measured gain until a comparison records one, and never reports rejected controls
  or missing counts as results.
- Add Claude Code as a second subscription research engine alongside Codex.
  Both share one worker contract, trace store and history; responses record
  their runtime and model, and private tasks freeze the engine they were
  authorized with (`oopc-private-interactive-task-v3`). Sign-in uses the
  official `claude auth login` flow; quota is read from `/usage` and keeps the
  same 30% reserve. Trace review follows the selected engine; model-pinned
  evaluation stages keep their registered Codex runtime.
- State the memory parameter naming rule that `validate_proposal` already
  enforces in a second consolidation producer contract. Frozen contract-1
  requests, their outcomes and verification are unchanged; the Improvement
  page counts staged trace-review proposals under Propose.
- Move the unchanged developer inspector to `/operator.html`, unlinked from the
  researcher application. Bundle OpenChemLib JS 9.25.0 (BSD 3-Clause) for offline
  structure drawing.

## 0.9.54

- Freeze explicit substantive-publication witness instructions for new document
  contracts. Preserve historical instructions, outcomes, source checks and
  separate scientific admission gates.
- Add bounded PDF text and image batches with exact page-to-payload mapping,
  independent role acquisition, explicit partial gaps and unchanged session
  budgets. Pin the helper runtime prospectively; old transport-only authority
  does not authorize the new tools.
- Preserve the remaining live review qualification, calibration, meaningful
  tranche comparison and full-path performance requirements.

## 0.9.53

- Use scoped native OS certificate trust for the approved ordinary PDF route;
  retain hostname checks, strict source bounds and sanitized failure diagnostics.
- Add an explicit transport-only successor for the retained fourth document's
  unstarted first correction, preserving original outcomes and exact charges.
  No reviewer qualification, additional allowance or scientific approval follows
  from this software repair.

## 0.9.52

- Allocate private UI requests on demand within the existing campaign hours, quota and task budgets. Preserve automatic jobs, older private receipts and frozen continuation allowances; bound registrations and campaign storage.
- Freeze a narrowly approved PDF route for new eligible document tasks. Acquire independently for producer and reviewer, return bounded page text and actual page images, and record exact private tool returns without inferring scientific support.
- Share the existing source-request ceiling, prohibit implicit redirects, supervise parsing/rendering and preserve unknown worker ownership and observed final responses. Keep historical task specifications and the registered qualification runtime unchanged.
- Retain the outstanding live-task, reviewer-qualification, calibration, first-tranche comparison and performance acceptance requirements.

## 0.9.51

- Let a nonempty queue containing only publication-inspection jobs proceed without preparing unrelated ordinary-task development leads.
- Preserve genuine recent-publication discovery, source qualification, independent review, admission and existing campaign allowances. Reject a concurrently reopened ordinary task before its worker starts.
- Preserve the interrupted public PLA task and its original charge; document inspection is separate work, not a retry or scientific reinterpretation of that failure.

## 0.9.50

- Keep verified public research assignments independent of unrelated development-feedback preparation when every unfinished ordinary research task has its own public assignment. Preserve the existing preparation path for mixed and unassigned campaigns.
- Preserve genuine planning, source research, independent review, admission, current quota and campaign budgets; no historical benchmark conditions are reinterpreted.
- Supply the bounded public PLA annealing comparison request for two published processing–property studies. Registration and a pre-worker startup failure grant no scientific admission or tranche credit.
- Preserve the subsequent research interruption and report all six completed memory-diagnostic operations without claiming scientific or performance acceptance.

## Public C4 synthesis checkpoint (0.9.49)

- Prepare one experiment-scoped PLA synthesis dossier with explicit monomer, initiator, catalyst, carrier and product identities using existing vocabulary.
- Retain the selected measured molecular mass, method and uncertainty limits; distinguish author-corrected and theoretical context without inventing source units or conversion/yield results.
- Supply a frozen public question and request while retaining candidate status. Cached publisher text was inspected; direct downloads returned HTTP 403, so fresh source verification and independent scientific admission remain pending.
- Preserve the published graph, earlier examples, software 0.9.49 and the registered reviewer runtime.

## 0.9.49

- Assign an explicit public research question and unreviewed source leads to an untouched ordinary campaign slot. Preserve genuine planning, independent research review, admission, queue order and existing budgets; registration starts no model.
- Bind each assignment to its original request, slot and release. Recheck before worker startup, preserve valid carry/rebase history, and settle known local pre-worker failures without holding an unused model reservation.
- Add a public C6 request and retain a read-only audit of the earlier PLA admission and retrieval evidence. Neither artifact establishes a new live answer, production tranche, calibration or scientific gain.
- Keep the registered reviewer runtime, existing performance implementation and published scientific graph unchanged. The finite MVP and live self-improvement acceptance remain pending.

- Add 23 candidate records for one source-qualified PLA degradation condition and its directly reported mass-loss endpoint, using existing vocabulary with explicit source and scope limits.
- Freeze a public worked question, rubric and answer claims; preserve pending scientific review and admission. The published graph, earlier tensile example and qualification runtime are unchanged.
- Advance the finite C6 inventory to candidate prepared; no admitted science, successful live answer, calibration or A/B benefit is claimed.
- Verify canonical records, coexistence with the prior example, an immutable candidate preview, eight graph traversals and exact observation readback; editorial source and contract reviews are complete.

## 0.9.48

- Reuse bounded lexical file and ancestor layouts attached to verified release snapshots. Every reuse still performs fresh file-type, strict parent-resolution and file/ancestor identity checks; no filesystem result or scientific authority is cached.
- Restrict the optimization to canonical native POSIX paths. Unsupported spellings, platforms and oversized layouts use the existing fingerprint algorithm; an observed path change invalidates the snapshot before revalidation.
- Retain the existing two-snapshot lifetime and cleanup boundaries, with additional per-layout file, path and metadata limits. Reviewer qualification and the complete scientific improvement cycle remain outstanding.
- Reduce retained-fixture median preparation by 25.2% in fresh processes and 26.6% for second operations, with identical complete inputs. Preserve the earlier fallback-only diagnostic; the warm and memory targets remain unmet.

## 0.9.47

- Reuse one bounded suite-wide Evidence projection during source-feasibility reconstruction. Keep the original per-case selector and 600-record rejection; unsupported scopes or unions above 600 Evidence records retain the ordinary path.
- Bind the projection to the selected snapshot manifest, compare current case/source metadata on every call and freshly verify the release before returning. Preserve operation cleanup, detached results and all source/session/review authority checks.
- Reduce median preparation on the retained synthetic fixture by 16.8% in fresh processes and 16.4% for second operations in a process, with identical complete inputs. Preserve the measured post-operation memory discrepancy and the unmet warm target.
- Keep reviewer qualification, valid controls, the real task-to-tranche comparison and performance acceptance outstanding.

## 0.9.46

- Add a development-only synthetic fixture builder and full-preparation diagnostic runner. Preserve the actual eight-case archive/correction history and failed first pair, while keeping fake construction judgments separate from unmocked reconstruction.
- Provide small and record-count-scaled fixtures with sealed file inventories, original absolute path bindings, declared dimensions and exact expected inputs. Treat construction code as provenance and freeze measurement code separately for later comparisons.
- Give every timed operation a fresh verification scope. Retain process time, incomplete samples, failures and changed-input rejections; report sparse observed statistics without granting scientific or performance acceptance.
- Keep the scientific learning cycle and full performance acceptance outstanding. No scientific runtime or policy changes are introduced.

## 0.9.45

- Derive archive readiness and source-preparation session exclusions from one full source verification pass within the same operation. Recheck current source material after intervening batch/context work, preserving exact requests, history, failures and session independence.
- Reduce median full eight-case preparation from 33.645 to 29.804 seconds in three alternating diagnostic pairs with identical inputs. These shared-host observations do not establish cold/warm percentile acceptance or scientific improvement.
- Keep reviewer qualification, valid controls, live task-to-tranche comparison and full performance acceptance outstanding.

## 0.9.44

- Add an immutable private reference-bank coverage registry and explicit CLI registration, annotation revision and journal-observation commands. Preserve original candidates, qualifications, pool versions and draws.
- Report nominated and recorded-qualified coverage, distinct task/publication lineages, declared or unknown material/template clusters, and separately deduplicated historical versus matching lifecycle observations. Retain failures and stale records without inferring execution or current scientific eligibility.
- Bound all registry reads and reuse comparison reconstruction only within one operation with final freshness checks. Read-only reports perform no model calls, writes or implicit observations.
- Keep independent cluster review, scientific reviewer qualification, valid controls and the complete live improvement cycle outstanding.

## 0.9.43

- Show bounded recorded reviewer preparations and their retained failed parents, current-incumbent tranche consumption and fresh-change shortfalls, current-campaign allowance, and publication blockers in Learning & evaluation. Missing, changed or over-limit records remain unknown; reading status cannot dispatch work or authorize publication.
- Derive the next-stage hint from an exactly bound pending reviewer preparation before historical control failures, preserving the earlier outcomes.
- Build shared ancestor chains once per release fingerprint while retaining every fresh file and ancestor identity check. Copy a smaller source-incumbent projection within the existing verification scope, preserving all identity collisions, exact record hashes and independent source authority checks.
- Scientific qualification, valid controls, the real improvement cycle and performance acceptance remain outstanding; the scientific release and registered qualification condition are unchanged.

## 0.9.42

- Show each task's recorded scientific, recipe and experimental-vocabulary admission decisions with retained reasons, limitations and reported worker time. Bind the read-only view to the local run, original independent review and exact saved admission; unavailable records remain unknown and private interactive tasks cannot acquire admission authority.
- Load replay admission details separately from the graph. Preserve the selected task or event when delayed requests finish, including rapid switches between private tasks. Browsing performs no model calls or trace writes.
- Reuse an already verified ordinary accepted packet when deriving its exact source outcome in the same archive operation. Keep current source/access/context checks and full reconstruction for interpreted, rejected, missing or unmatched material.
- Scientific qualification, valid calibration, the complete live improvement cycle and performance acceptance remain outstanding. The scientific release and registered qualification condition are unchanged.

## 0.9.41

- Add official ChatGPT/Codex account connection in the private task dialog, with background status, sign-in and cancellation. Keep credentials in Codex-managed storage and task execution separately authorized within existing budgets.
- Protect connection requests with local-origin and CSRF checks, preserve existing saved accounts, and coordinate pending sign-in with workspace task/reservation activity. Keep account status informational; workers still authenticate and check quota afresh.
- Reuse freshly verified archive packet material within one operation while retaining exact receipt presence, original bytes, source/reference journals and rejected-session exclusions. One full eight-case observation fell from 71.9 to 44.0 seconds with identical inputs; repeated performance acceptance remains pending.
- Update the finite MVP plan with account connection and explicit vocabulary, scientific-edge and retrieval-shortcut heuristics. Scientific reviewer qualification and the complete live improvement cycle remain outstanding.

## 0.9.40

- Add one explicit, bounded interpretation successor for the known failed qualification preparation. Preserve the original final, failure, exact source reads and charge; prohibit replacement authors, new seeds and recovery chains. All independent adjudication and 48 measured reviews remain required.
- Clarify nested JSON-string fields prospectively. The recovery contract alone recognizes the three exact historical coordinator defects, with canonical lossless projection and unchanged ordinary scientific validation.
- Reuse a freshly verified staged descriptor and archive-correction parent within the same operation. Keep later calls, changed inputs, source rights and mutable authority freshly checked. One full eight-case preparation observation fell from 197.2 to 71.9 seconds with identical inputs; repeated performance acceptance remains pending.
- Keep reviewer qualification, calibration, scientific admission and publication pending. Software validation and recovery eligibility do not establish scientific approval.

## 0.9.39

- Generate concrete expected uses from exact admitted records and independently review each mapping in a separate, confined session. Preserve explicit no-use, failed and uncertain dispositions without inventing objective coverage.
- Automatically register a reviewed tranche after the unchanged five-assertion, two-publication and two-objective gate passes. Keep historical operator declarations and coordinator cursor meanings intact.
- Bind declarations to source, admission, runtime, session and worker receipts. Charge preparation and both calls to existing allowances; retain unknown outcomes and reservations until verified recovery without redrawing exposed work.
- Require a fresh five-assertion, two-publication and two-objective tranche between candidate comparisons. Atomically consume the whole admitted delta before drawing tasks, preserve failed exposure, and retain exact legacy and interrupted-comparison continuation through public commands.
- Bound aggregate history bytes before parsing and bind every consumption entry to its admission, declarations and comparison. Make the stronger scientific-shadow requirement explicit in publication policy version 2.
- Correct captured-source receipt routing for all three scientific qualification roles, matching their declared JSON response field. Preserve the rejected panel and its full cost; further scientific qualification requires a prospective repair contract.
- Remove contradictory reviewer-output instructions from qualification author requests while preserving exact author parsing, critical criteria and all historical responses.
- Live task-to-tranche evidence, scientific reviewer qualification and full performance acceptance remain required.

## 0.9.38

- Add a prospective ordered exact-text answer declaration; the coordinator derives Unicode spans without repairing text or changing historical scoring conditions.
- Preregister bounded formatting diagnostics and an independent fixed-answer scientific reviewer panel using the production source access, parser and scorer. Retain all attempts and keep software validation separate from live qualification.
- Require qualified reviewer evidence before registering one distinct successor to the failed staged-core bridge, preserving original tasks, references, outcomes and undispatched arms.
- Preserve captured final responses and exact partial output when worker receipts are lost; only positively established pre-launch failures permit a transport retry. Retain uncertain reservations until verified recovery.
- Keep historical read-only blocked reports inspectable. Require bound worker cleanup before settling legacy baseline charges, and stop recovered terminal experiments from consuming a new reservation or review.
- Freeze complete reviewer delivery conditions, use full per-call allowances after fresh quota checks, and reuse sealed requests during continuation while retaining fresh source and authority checks.
- Charge qualification source preparation inside the existing stage allowance. Reuse the enclosing operation's verified comparison plan for retained-arm reconstruction while rechecking exact registration, release, reference qualification and availability.
- Reuse a freshly checked charter within one source-access validation while keeping current session and source checks. Record identical full inputs and a 57.3% lower elapsed time in a single before/after observation; full performance acceptance remains pending.
- Display private-task review criteria as readable findings instead of raw data records.

## 0.9.37

- Integrate prospective fixed answer-unit and citation responsibilities through real solver/source-review scoring, comparison conditions and protected audit reconstruction. Preserve historical v4 scores and require separate empirical reviewer qualification.
- Gate new candidate scheduling on frozen meaningful accepted changes: five distinct assertions, two independent publications and two declared objectives. Preserve original campaign/review provenance and require explicit expected-use registration; this grants no scientific or publication authority.
- Route registered projects exclusively through the current evolution publication gate. Private campaign assembly no longer reconstructs unrelated legacy readiness after each task.
- Add private question/task submission and independent reviewed answers in the local UI using untouched ordinary weekly slots, existing budget/quota controls and durable traces. Submission grants no automatic learning or publication permission.
- Reuse up to two checked releases within the unchanged aggregate memory limits, preserving fresh fingerprint checks and mutation/worker boundaries. Measure the improvement on synthetic paired-release preparation, separately from scientific gains.

## 0.9.36

- Add a pure, diagnostic review-contract builder and validator that bind exact answer spans, declared claim types, citation responsibilities, complete criterion mappings and input hashes. It performs no model calls and grants no scoring, admission or publication authority; production v4 scoring and historical controls remain unchanged.
- Document a polymer-specific path through fixed-answer reviewer qualification, reference-bank expansion, measured performance, meaningful accepted-change tranches, new controls and candidate comparisons. Distinguish existing gates from planned integration and scientific validation.
- Clarify project identity and keep private transfer material out of Git staging. Preserve the existing polymer history, source seed and separate reaction project.
- Open newly staged release files with writable handles for the final durability flush, fixing Windows release construction while preserving release bytes, error propagation and publication only after every flush succeeds.
- Normalize the supplied project root before constructing reference-barrier read paths, supporting Windows temporary-directory aliases without resolving untrusted child paths or weakening containment and symlink checks.

## 0.9.35

- Preserve a terminal rejection when verified same-release controls cannot satisfy the frozen variability ceiling, including a mathematical lower bound before all planned pairs run. Retain every measured outcome and unexecuted-arm gap; do not create a calibrated policy or authorize publication.
- Stop further control dispatch through the existing coordinator and show excessive variability separately from failed source preparation. Dashboard reads verify the recorded result without replaying source qualification; qualified tasks and historical evaluations remain unchanged.

## 0.9.34

- Execute an already registered staged control comparison through the existing comparison runner. Reserve curation for qualification, registration and activation, avoiding reconstruction of completed construction before the runner's required fresh evidence verification.
- Accept an author's canonical availability envelope only when reconstructing it from the frozen corpus produces exact equality, including every witness and metadata hash. Preserve the original response and require its first independent review; this changes no scientific classifications or retry policy.

## 0.9.33

- Allow one registered availability amendment before an initial core's first solver exposure. Preserve its tasks, source references, rejected review and qualified exchanges; require a changed classification proposal and fresh independent review before the complete controls can proceed.
- Keep the amended preparation in the existing coordinator, activation and progress paths. Its immutable identity is separate from the quarterly task-revision schedule; it grants no additional resources or publication approval.
- Remove duplicate source-packet and charter reconstruction within an operation, share exact freshly checked bridge qualifications with plan loading, and resolve repeated parent paths once per release fingerprint. Public and model-access boundaries retain fresh verification.

## 0.9.32

- Protect feasible task completion separately from scientific coverage in newly prepared paired comparisons. Derive its regression tolerance from the same controls, retain the existing quality-variability ceiling, and preserve historical protocols and scored failures.
- Derive historical JSON and byte receipts from one fresh checked read. Reuse a verified plan within measurement reconstruction instead of immediately reconstructing it again. Evidence, source-access and reviewer checks remain required.
- Update the implementation checkpoint to distinguish eight qualified source references, seven qualified corpus-availability checks, and no completed learning cycle.

## 0.9.31

- Record independently rejected corpus-availability preparation as a terminal, unscorable comparison before solving. Verify the original exchange and all preceding qualifications, preserve the negative judgment, and reuse the existing summary and successor-retirement paths. Normal rejection closes budget accounting; corrupt or incomplete artifacts remain errors.
- Show availability qualification counts separately from source-qualified references and completed comparisons, without grades for work that never reached a solver. Reuse the existing inspector presentation.
- Remove the unused full-plan reconstruction before comparison preparation, which retains its own fresh validation. No model, scoring or evidence-access policy changes.

## 0.9.30

- Resolve exact evidence witnesses against the supplied ontology terms as well as scientific records, matching the solver's vocabulary access. Reject ambiguous identifiers and retain exact field, value and corpus binding checks. An unchanged saved author response can continue to its first independent review; scientific judgments and frozen requests remain unchanged.
- Give text retrieval access to the same vocabulary and include it in the bounded long-context payload. Pin new comparisons to adapter 0.6.5, preserving all historical 0.6.4 checks and receipts.

## 0.9.29

- Reuse bounded, checked release and captured-source data within one verification operation. Check current file and path identity before reuse, clear at mutation/model boundaries, and retain independent evidence, session, journal and admission checks. Source-context verification now copies only the case evidence instead of the entire graph.
- Remove duplicate successor reconstruction during control registration and loading, preserving the same qualification and bridge checks.
- Count comparison preflight and plan verification against the continuation deadline without changing the frozen solver limit. Captured-source dispatch retains its full runtime checks.
- Distinguish staged, active and historical cores in the inspector. Show staged reference qualification and registered versus completed controls separately, with the next required action.

## 0.9.28

- Reuse the verified source packet and legacy read interpretation within one reference qualification operation. Retain independent role checks, source and journal integrity, and fresh verification on subsequent operations without a persistent authority cache.
- Read checksum-bound published records for progress counts instead of repeating complete release verification on every inspector refresh. This display projection grants no scientific or execution authority.
- Prioritize the authorized initial core and its pending controls through the existing coordinator, after unfinished paired experiments. Preserve terminal outcomes, the normal scheduling cursor, and the applicable campaign limits.

## 0.9.27

- Align typed captured-source locator observations with their read receipts. New receipts bind the exact Evidence identity and content hashes to complete observed reads while allowing a descriptive inspected-passage locator; historical receipts retain their original binding rules.
- Continue a demonstrably complete legacy reference-author read through one explicitly registered, append-only interpretation. Preserve the answer, original rejection and observation time, require fresh independent review, and reject scientific negatives, incomplete reads or prior reviewer exposure. No extra author attempt or resource grant is created.

## 0.9.26

- Reconstruct each captured JATS representation once per source reader, while still checking the exact current manifest, wire, XML and projection bytes and path permissions on every access. Independent readers verify separately; changed descriptors and failed reconstructions cannot reuse a prior check. This removes repeated parsing during evidence-access verification without changing payloads or scientific admission rules.

## 0.9.25

- Let the existing archive workflow register one independently reviewed source correction after a source-only failure. Preserve the rejected parent, seven qualified objectives, pinned corpus and resource allowance; require a distinct occurrence of the same article with a materially corrected locator.
- Reconstruct the ordinary source-review receipts before accepting the correction. Continue through the shared task/reference qualification, assembly and control stages; the corrected source alone grants no benchmark or publication approval.
- Show both the rejected and corrected preparation attempts in progress, and retain both source occurrences in audit exclusions.

## 0.9.24

- Make the inspector, `readiness` and `evolution status` use one recorded-progress view. Separate qualified objectives, candidate changes, controls, completed comparisons and measured gains from setup rejections and source-access gaps. Show receipt timestamps and integrity gaps without rerunning full provenance verification on every refresh; execution and admission retain their checks.
- Retire the former prototype scheduler and its repetitive scheduling tests. Keep its command as an alias for the registered core-and-rotating coordinator, preserving historical journals and explicit legacy inspection.
- Share source-packet/reference qualification across the existing setup episodes and continue only the newest registered episode. Reconstruct each prepared batch under one authenticated charter read without retaining authority across operations or changing frozen histories.

## 0.9.23

- Add a separate, bounded archive-first episode for remaining initial core objectives, preserving qualified cases and every prior judgment. Acquire and independently qualify supported PMC source representations before preparing new tasks.
- Connect exact private source snapshots to scoped task and reference review, with role-bound capabilities and verified read receipts. Keep source access, identity/rights and scientific findings distinct; source bodies never become solver inputs.
- Pin reviewer source conditions identically across paired release arms, retain scientific reference barriers, and exclude all adaptation source leads from fresh audits. Derive new candidate labels from their pinned material identities.

## 0.9.22

- Add one prospectively registered, finite construction pool for the unmeasured initial core. Preserve five qualified anchors and all rejected drafts; freeze two new drafts per missing objective before independent review and select in precommitted order.
- Bind explicit public material leads and require useful corpus evidence for each task’s main objective. Resolve witness selectors canonically, assess scoped signal claims against both corpus and source, and require independent availability checks for every reference conclusion.
- Retain preparation exposure from rejected and unselected drafts in fresh-audit exclusions. Construction grants no resources, regrades no historical result, and preserves full-suite assembly, measured controls and publication gates.
- Fix false release-change reports caused by unrelated sibling directories during verification. Retain file and symlink integrity checks, and keep operational verification failures separate from scientific rejection.

## 0.9.21

- Reuse verified release data and corpus selections within one curation operation, eliminating repeated parsing of the same immutable graph. Recheck file identities and metadata before reuse, isolate execution contexts and return independent copies.
- Discard cached release reads at model and journal-write boundaries. Current quota, eligibility, source warnings and scientific judgments remain uncached; graph contents, task inputs and historical outcomes do not change.

## 0.9.20

- Use typed source-inspection responses for new commissioning packets and references. Distinguish an article landing page from its pinned full-content address, retain reported date precision, and bind inspection dates to recorded dispatch provenance.
- Separate malformed source-response contracts from adverse scientific findings. Keep exact Evidence identity, all independent source checks and full reference qualification requirements.
- Permit an append-only deterministic interpretation of a fully positive saved packet review rejected by the earlier URL/date decoder. Preserve original requests, responses and rejection receipts; no researcher or reviewer is rerun, and no scientific judgment is overridden.

## 0.9.19

- Treat source-check locator wording as a passage description in new commissioning packets, while retaining pinned source metadata, exact Evidence IDs/content URLs and all six independent source checks.
- Add a no-model locator-repair registration for a v1 packet rejected solely by literal locator mismatch, with all producer checks positive and no prior packet review. Preserve its original request and outcome, reuse the unchanged producer response through verified ancestry, and allow the first independent packet review in a separate child journal. Genuine scientific failures remain terminal.
- Clarify that 1–10 grades apply to qualified benchmark evaluations. Ordinary research reviews remain categorical; unscorable evaluations receive no grade, and strict scientific-admission gates remain separate.

## 0.9.18

- Add separately authorized, once-only initial core commissioning under an existing setup grant. Preserve qualified anchors and historical judgments while preparing new current-source tasks for at most three frozen objective contracts; no historical correction is required to select a new source occurrence.
- Require independent source preparation, packet review, reference authoring and reference review, with exact source qualifications and substantive evidence available in the pinned solver corpus. Terminal slot outcomes cannot purchase another task or scientific judgment.
- Require complete independent assembly and measured controls across all eight cases before activating a successor. Keep commissioning journals private and preparation exposure in future audit exclusions. No ontology improvement or publication authority is inferred from commissioning.

## 0.9.17

- Select the latest independently checked source-metadata revision within each investigation; retain earlier records and reject conflicting identities across different investigations. A newer withdrawal cannot fall back to an older positive review.
- Check source snapshot consistency before freezing curator requests. Preserve an undispatched malformed preparation through one deterministic, linked repair journal; any prior dispatch or judgment forbids that repair. Scientific findings, scoring and publication gates remain unchanged.

## 0.9.16

- Let a new, explicitly authorized initial-core curator consider authenticated source-verification limitations when selecting genuinely different usable inputs. An inaccessible source does not establish scientific falsity or qualify a replacement.
- Preserve all existing qualification judgments and five-case overlap; independent source checks, new references, measured calibration and publication gates still apply. Frozen earlier bootstrap requests retain their original protocol.

## 0.9.15

- Clarify prospective task ownership: researchers produce source-grounded reports, evidence and proposals; the coordinator subsequently invokes independent review and deterministic admission. New success criteria must assess work the producer can perform.
- Distinguish reviewer-only output guidance from producer deliverables. Preserve saved planning/research/review requests, legacy source-feedback identities and historical task outcomes.
- This repairs a circular requirement observed in one source-investigation task. Its separate source-edition uncertainty remains valid; the repair does not reinterpret historical failure labels or establish performance improvement.

## 0.9.14

- Record explicit operator setup grants for the actual campaign, extending aggregate work and source-request capacity without resetting charges, changing per-case experimental budgets, or extending future weekly defaults. Actual account exhaustion and unknown quota still pause execution.
- Append a bounded, immutable set of public-core source investigations. Original jobs, judgments and contribution scope remain intact; interrupted registration resumes the same plan.
- Permit one separately authorized, source-correction-only repair of the unmeasured initial core after the investigations finish. Preserve the earlier monthly review, qualified cases, actual quarterly successor slot, independent references, calibration and activation requirements.
- Include dispatched bootstrap source metadata in future audit exclusions. Setup capacity is not scientific validation, a new weekly pilot campaign, or evidence of improvement.

## 0.9.13

- Connect explicitly assigned public-core source investigations to future core curation through independently checked, bounded source metadata. A bibliographic correction can qualify without inventing a scientific claim or first publishing a candidate graph.
- Freeze the source metadata and its reconstructed producer/reviewer authority with a new monthly request. Only an independently accepted, exact replacement case can receive the corresponding reference-only source bundle; the solver corpus remains separately pinned.
- Preserve source-exposure exclusions for fresh audits, including interrupted or unsuccessful curation and reference work. Keep historical requests, terminal references, the curation calendar, measured bridges and publication gates unchanged.
- This connection does not qualify existing rejected references, demonstrate an A/B gain or authorize automatic publication.

## 0.9.12

- Clarify the existing source boundary for future reference authors: cite supplied source identifiers, verify every cited source, and record newly discovered sources as unadmitted leads. Putting a source record in notes cannot add it to a frozen reference's eligible sources.
- Distinguish reference authoring against the supplied frozen corpus from executing the solver's graph-access task. Missing solver tooling is not itself a reference source-verification failure.
- Resume saved requests with their exact known historical instructions. Preserve terminal references, source checks, scoring, admission and retry rules; this clarification neither qualifies rejected references nor establishes ontology improvement.

## 0.9.11

- Interpret supported structured claim-review judgments consistently before new admission receipts are created. Preserve reviewer rationales and the original verdict representations; reject ambiguous or malformed judgments without another scientific attempt.
- Keep scientific claim admission separate from overall task completeness. A supported claim can be eligible even when the task fails, while source checks, scope, provenance and all other admission requirements remain mandatory.
- Preserve historical reviews, admissions and benchmark scores. This repair does not establish measured ontology improvement or authorize publication.
- Keep the inspector usable when an older review contains an unsupported verdict representation; leave that finding unclassified rather than deriving a new historical grade.

## 0.9.10

- Preserve a durable queue for rotating reference qualification so newly arriving candidates cannot repeatedly overtake existing pending cases. Prioritize already-started reference exchanges without changing their frozen inputs or authorizing another judgment.
- Queue order is independent of scientific scores and sampling categories. Qualified and rejected outcomes, contribution permissions, and all publication gates retain their existing meaning.

## 0.9.9

- Show recorded benchmark coverage judgments in the task review panel, including supported answers, scoped abstentions, missed evidence and their rationales. Keep ordinary campaign criteria separate; do not report missing coverage when the benchmark review contains it.
- Label ordinary verdict-only task reviews as having no recorded numeric grade rather than suggesting that all review qualification is unknown.
- Preserve the original numeric scores, strict verdicts and qualification status. This is a display repair, not a new evaluation or evidence of ontology improvement.

## 0.9.8

- Preserve the exact frozen source scope supplied to a task planner when preparing future researcher and reviewer requests. Bind it to the original planning exchange and completed producer, including weekly carryover; keep legacy requests and historical outcomes unchanged.
- Display supplied task scope as a separate replay artifact. It does not create graph-access, traversal, delivery-confirmation, citation, scientific-validation or memory-utility events.
- Preserve the distinction between qualified knowledge enrichment and demonstrated performance improvement. Science-only publication uses the active compact policy; default-memory promotion still requires recipe-specific reuse evidence.

## 0.9.7

- Supply future research revisions and reviewers with a bounded, independently reconstructable history of accepted scientific predecessors from the same task. Keep private admission, pinned-graph presence and current scientific support distinct; retain fresh source review and ordinary admission gates.
- Preserve saved requests and terminal outcomes. A missing historical receipt in a completed review does not authorize another judgment or promote a quarantined recipe.
- The rotating pool has six nominees, including two representative tasks; PA1010 and PPS references have independently qualified. Core qualification, calibration, matched comparisons and the unattended pilot remain incomplete.

## 0.9.6

- Give future task nominators a frozen aggregate view of representative and novel pool coverage, including distinct task lineages. Prefer a justified underfilled category without inventing novelty, relabeling earlier cases, or requiring a nomination.
- Keep existing nomination identities, frozen requests and terminal outcomes unchanged as the pool grows. Coverage counts describe nominations, not independent qualification or measured performance.
- One rotating reference has now qualified through separate live author and reviewer sessions. The pool, compact core, calibration and pilot remain incomplete; no ontology improvement is claimed.

## 0.9.5

- Route unresolved public-core source contexts into the existing development-feedback queue as unscored verification leads. Carry public source metadata and verified authority hashes, without reference answers or reviewer prose; preserve frozen task assignments and use only future matching slots within the ordinary campaign limits.
- Clarify future reference-author requests with an explicit flat availability-map example and current-session inspection requirements for every cited source. Preserve exact known earlier author requests on durable resume and retain terminal malformed or unqualified results without another scientific attempt.
- These changes support reference preparation and ongoing research. They do not qualify the remaining core cases, calibrate comparisons or establish measured improvement.

## 0.9.4

- Display verified empty scientific-claim and supporting-citation assessments explicitly instead of presenting their arithmetic convention as a perfect grade. Show completion and research coverage alongside the task headline; unknown denominators remain unknown. Preserve original scores and strict judgments.
- Add one prospective reference-correction episode for a verified same-source locator or unsupported-qualifier defect before solver exposure. Preserve the task, rubric, corpus, source identities, original rejection and coverage; require a materially changed proposal and fresh independent correction/source review. Edition-only and access-only failures retain their separate constraints.
- Refresh authorized scheduled-public contribution intake before nomination, allowing newly completed research into the same week's rotating pool without reopening a frozen consolidation batch. Reuse verified receipts, exclude uncontributed private tasks and report cached consolidation outcomes as unchanged.
- These repairs do not establish measured ontology improvement or enable automatic publication. Actual reference qualification, controls, candidate comparisons and the pilot remain required.

## 0.9.3

- Add one separately recorded qualification episode for an unchanged, rejected public core task before comparison registration, only after later coordinator-observed and independently confirmed restoration of the exact original source. Preserve the original rejection, source editions, all relevant citations, fresh-session separation and the campaign budget. Locator-, edition- and runtime-only uncertainty cannot use this access-recovery route.
- Pin reference episodes in new comparisons and explicitly resolve the original episode for historical plans. Retain earlier exposed core source lineages in fresh-audit exclusions and show both original and successor diagnostic outcomes.
- Preserve uncertain continuous recipe reviews as experimental observations without reuse credit, instead of raising an exception while constructing an invalid positive receipt. Historical strict experiments remain unchanged.
- These repairs do not establish empirical improvement: five of eight live core references remain qualified, and calibration, paired candidate evaluation and the unattended pilot remain incomplete.

## 0.9.2

- Give future independent core curators verified qualification diagnostics, including source-access gaps and exact artifact hashes, without reference answers, reviewer prose, private task content or audit cases. Preserve frozen curator requests and terminal outcomes.
- Route verified core-reference access gaps into the existing bounded source-probe and independent maintenance queue. Match exact source occurrences, preserve earlier development witnesses and retain request limits; a successful fetch does not qualify a reference or authorize another scientific judgment.
- Keep the live qualification and calibration gaps explicit. Unchanged core tasks still require a separate evidence-backed recovery protocol before a rejected reference can have a new qualification episode.

## 0.9.1

- Repair prospective improvement gates so an unchanged residual answer error does not count as a new scientific regression. Frozen, blinded critical-criterion reviews identify new or widened errors with source and corpus witnesses; incomplete reviews retain candidates experimentally. Calibrated continuous-score tolerances govern ordinary variation.
- Apply the same marked review condition to new release comparisons and fresh audits, requiring a matching calibration. Preserve historical condition hashes, strict judgments and already exposed comparisons.
- Permit qualified partial success in newly registered exact-recipe tests without pretending the answer strictly passed. Keep evidence lineage, no-loss requirements, exact candidate isolation and independent scientific admission. Public recipe receipts contain compact verified certificates rather than private reviewer prose.
- Scope new reference reviews to scientific evidence, task answerability and the rubric; deterministic coordinator checks retain responsibility for graph and harness integrity. Preserve frozen requests and uncertain outcomes, including source-access and edition mismatches.

## 0.9.0

- Add a separately registered prospective protocol with eight stable core tasks, four frozen rotating cases, independently checked references, and same-release controls that calibrate variation before candidate evaluation. Preserve all historical four-method studies and judgments.
- Aggregate authorized trajectories into reviewed retrieval heuristics, scientific hypotheses and experimental vocabulary leads. Retain partial and failed task signals without converting frequent co-access into scientific truth. Private user contributions require explicit local consent.
- Drive bounded research, nomination, reference qualification, paired comparison, source maintenance and core curation through a fair scheduler. Monthly review and measured quarterly bridges preserve the meaning of the core's history.
- Keep scientific admission, measured performance, fresh protected audits and automatic publication separate. Routine evaluations use production defaults; experimental recipes need their own qualified reuse experiments before becoming default memory.
- Expose aggregate progress in the offline inspector. Package the initial core descriptor with the library; private references, task traces, source captures and audit cases remain excluded.
- Show qualified task scores on a transparent 1–10 scale, separately from strict acceptance and unscorable reviews. Paired comparisons retain dimension-wise scores and visible missing observations; historical judgments are unchanged.
- Isolate a proposed recipe against the same graph-memory harness and existing default recipes. Preserve historical experiments and require independently reconstructed, source-qualified three-task/two-bundle evidence before default admission.
- Software verification does not establish scientific improvement or complete the live pilot. Automatic publication remains conditional on actual qualifying evidence.

## 0.8.2

- Restore the original 30% remaining-quota reserve for all new model work, including evaluations, reference preparation and withheld audits. The previous 20% evaluation exception was an implementation deviation from the requested defaults.
- Apply the same default in the shipped configuration, campaign coordinator and library fallback. Unknown quota still stops dispatch; exactly 30% is eligible. Explicit configuration overrides remain available to other operators.
- Preserve campaign accounting, completed judgments, selected experiments and public graph data. Boundary tests exercise deferral without model dispatch, reservations or charges; positive fixtures retain their intended scientific and transport checks.

## 0.8.1

- Reject unknown relationship filters in the regular Python, CLI and MCP readers, with guidance to inspect the pinned vocabulary. A declared relation with no matching assertions remains a valid empty result.
- Record invalid agent queries as failed access events without returned records or invented traversals. Inspector queries remain outside task traces; existing replay payloads remain unchanged.
- Offer the same validation to new bounded benchmark experiments through an explicit v3 retrieval condition. Preserve v1/v2 observations, default conditions, existing cohorts and call/response allowances.
- Keep software reliability improvements separate from scientific progress: this repair supplies no new claim, qualifying recipe reuse or successful withheld audit.

## 0.8.0

- Freeze the exact assigned publication and source-inspection criteria before new literature tasks start. Unassigned new slots wait without model calls; unknown protocol markers fail closed.
- Separate completed inspection with accepted claims, completed inspection with no justified additions, and unavailable/incomplete inspection. Preserve the raw review and independent scientific admission gates.
- Bind ingestion credit to immutable task, source, reviewer and admission records, including existing evidence from the pinned graph. Legacy tasks do not receive retrospective completion credit.
- Record the coordinator's inspection outcome separately in the inspector and offline replay. Resuming an interrupted finalization does not repeat research or review, invent graph access, or overwrite earlier events.
- Keep inspected outcomes, accepted candidates and demonstrated improvement distinct. The live baseline remains incomplete and no research-memory benefit or withheld-audit milestone is credited by this release.

## 0.7.9

- Deduplicate literature discovery using the publication actually present in independently checked, admitted evidence. Completing a task about another paper no longer suppresses its unused assigned lead in later weekly searches.
- Preserve completed task artifacts, scientific judgments, source occurrence identities, correction handling and campaign limits. Missing or inconsistent ingestion evidence cannot establish that a publication was ingested.

## 0.7.8

- Connect eligible terminal maintenance notices to exact official-source acquisition, including pinned private Evidence occurrences absent from the public release.
- Add a separately scoped scientific successor with fresh qualified captures, complete independent source reads and findings for every affected assertion. Preserve original-URL warnings, suspended recipes and immutable earlier reviews.
- Share one scientific review opportunity across duplicate notices for the same source and target records. Preserve negative and uncertain results; budget or quota deferral before dispatch does not spend that opportunity.
- Keep baseline recovery, research-memory admission and publication gates separate. No live representation-based scientific resolution or measured improvement is claimed by these software changes.

## 0.7.7

- Connect fully qualified source-recovery development comparisons to future research planning through coordinator-issued metadata attestations. Keep reference answers, source archives, private tasks and withheld cases out of the adapting feedback collector.
- Preserve generic rejection of unknown experiment conditions, exact recovery activation and report identity, immutable earlier judgments, and once-only assignment to untouched research tasks. Negative scientific results remain useful research leads, never proof of improvement.
- Build the source archive offline and test its wheel in a second clean environment; check graph access, inspector serving, replay, Unicode MCP pipes and console entry points for both distributions. Reject archive paths that could escape on Windows or POSIX.

## 0.7.6

- Use UTF-8 for MCP pipes independently of the computer's default text encoding, preserving Greek symbols and other Unicode in requests, evidence and errors.
- Exercise real installed MCP stdio with deliberately non-UTF-8 wrappers in the cross-platform distribution check. Keep custom text streams and existing UTF-8 reviewer connections compatible.
- Preserve the current baseline, historical outcomes and scientific admission gates; this portability repair establishes no measured research improvement.

## 0.7.5

- Register one immutable representation-recovery policy across the existing 24-case baseline, preserving its tasks, resources and all earlier outcomes.
- Require fresh qualified captures for every relevant source before activating a case successor; prepare a new independent reference and run all four fresh solver/reviewer arms under an explicit reviewer source condition.
- Reconstruct source-read receipts in readiness, prevent alternate-path or repeated-campaign retries, and stop later arms after incomplete source review without treating missing verification as scientific falsity.
- Keep captures and prior answers private. No live recovery, recipe benefit, withheld audit or publication milestone is credited by software tests.

## 0.7.4

- Capture official PMC full-text representations in owned, bounded workers while preserving original Evidence identity, exact encoded/decoded bytes, rights and extraction gaps.
- Share request accounting with source probes, reject implicit redirects and old-week budget reuse, and inspect captures through a separately scoped offline reviewer with complete-read receipts.
- Preserve completed failures and historical experiments. Representation qualification does not restore an original URL, validate scientific claims or authorize another baseline judgment.

## 0.7.3

- Stop unstarted comparison work when an independently reviewed frozen reference is inadequate, using exact private evidence receipts while preserving every completed outcome.
- Prepare one unexposed development reference at a time under the existing campaign budget; preserve cached judgments and refuse unknown interrupted authoring attempts.
- Keep skipped solver work distinct from measured task results, and prevent a blocked reference from generating new recipe-benefit receipts.

## 0.7.2

- Scope new reviews of precisely witnessed HTTP access loss to availability, without asking the reviewer to judge inaccessible scientific assertions. Capture the scope before dispatch and reject scientific findings in that operational review.
- Preserve historical uncertain reviews. Permit a separate scientific successor only after a validated new restoration episode, requiring fresh full-source checks and exhaustive qualified assertion findings before an old blocker can be handled.
- Keep source availability, scientific support, baseline measurements and publication permission separate. No source warning or restoration receipt establishes measured task improvement.

## 0.7.1

- Explicitly preregister a complete 24-case, four-mode baseline under the bounded retrieval condition before dispatch. Freeze the source release, cases, model, scoring, resources and condition in one immutable experiment.
- Resume the selected experiment without substituting more favorable historical measurements. Keep older outcomes in a separate history; invalid selection or mismatched reports stop qualification.
- Preserve source-blocked reference caches, negative judgments, terminal attempts, campaign budgets and all reuse, withheld-audit and publication requirements. Registration starts no model calls and is not evidence of scientific improvement.

## 0.7.0

- Add opt-in budget-packed retrieval with stable continuation, exact record fragments, and explicit paths supported only by returned qualified assertions.
- Preserve the frozen 0.6.4/v4 baseline. New learning and paired audit experiments bind the separate retrieval condition in plans, reports, comparisons and admission receipts; legacy experiments keep their original behavior.
- Distinguish run execution, source-checked task judgments, individual claim findings, actual recipe returns, relationship access, traversal and source-capture gaps in the inspector.
- Retain prior negative and unscorable outcomes. Software verification does not establish measured research improvement or satisfy the remaining reuse, audit and publication gates.

## 0.6.6

- Page dense inspector neighborhoods without changing agent traversal, and retain assertion-to-evidence and memory relationships with canonical record identities.
- Preserve failed and paused replay outcomes; mark active snapshots and legacy outcome gaps explicitly and disable live follow on imported snapshots.
- Require recorded solver time, tool calls and original resource limits before current comparison receipts can qualify. Existing live measurements and scientific scores are unchanged.
- Protect direct research and evaluation commands from overwriting outstanding worker reservations across campaigns.
- Deduplicate successfully ingested publication versions across overlapping weekly discovery windows.
- Retain the 0.6.4/v4 comparison cohort. One of 24 baseline cases is complete; no qualifying reuse, paired withheld audit or autonomous publication pilot has passed.

## 0.6.5

- Tighten source-recovery freshness against coordinator-observed failures across all retrieval modes; model-supplied dates cannot authorize an earlier source confirmation. Historical judgments remain unchanged.
- Bound ordinary source-maintenance HTTP requests with the existing owned worker supervisor and record their preflight reservation before dispatch. Unknown outcomes remain operational gaps.
- Preserve the 0.6.4 solver condition and v4 scientific scoring. This maintenance repair does not start another baseline cohort.

## 0.6.4

- Advance past known terminal completed-response failures without spending repeated empty continuations. Finish all runnable sibling modes and reviews first; retain bounded transport retries, source-block priority and original reports, scores, costs and retry history.
- Remove the unintended empty MCP server from long-context solvers and enforce supplied-context-only execution. Freeze a new 0.6.4 solver-interface condition across baseline, paired reuse and withheld audit protocols; preserve v4 scoring, source references and all earlier results.
- Keep completed failures and legacy interruption gaps terminal across version changes. Do not whitelist unexpected resource-discovery calls.
- Preserve failure archives on platforms without POSIX descriptor chmod or directory fsync. File flush, checksums and no-overwrite guarantees remain required; Windows ACLs are inherited, not independently verified.
- Exercise private failure capture in the clean installed-package smoke test.

## 0.6.3

- Preserve future completed-but-refused benchmark responses in private immutable archives, with metadata-only receipts in reports and traces. Capture observed tool identities and confinement findings without guessing aliases.
- Stop after interruption during failure preservation; retain explicit storage gaps and terminal attempts. Old missing responses cannot be reconstructed or redrawn.
- Bind baseline readiness to coordinator-registered cohort reports and qualified recovery history; expose measured judgments and missing measurements separately.
- Keep the 0.6.1/v4 evaluator and original scientific outcomes unchanged. Continuous scientific improvement remains unproven.

## 0.6.2

- Route verified, unscored transfer source gaps into existing new research slots; preserve recipe scope, private provenance boundaries and already dispatched planning inputs.
- Record separately qualified access-only dispositions without changing original uncertain source judgments or scientific status. Combine only compatible availability warnings and retain substantive conflict gates.
- Add bounded macOS idle-sleep protection for owned inference workers, with explicit operational gaps and unchanged historical timing and scientific protocols.
- Make exact evidence access/reuse identifiers explicit for future researcher calls; preserve original rejected records, independent source checks and benchmark reviewer prompts.
- Retain the 0.6.1/v4 benchmark adapter and its frozen cohort. Software release numbering does not reopen earlier comparisons.

## 0.6.1

- Keep future audit questions, answers and reviewer drafts inside protected audit storage, pinned by the protocol.
- Host research and maintenance MCP access in the coordinator; deny direct reads of private operational state, disable scheduled shell execution and unrelated connectors, and retain graph plus public web access.
- Preserve completed reviewer judgments across transport cleanup faults and checkpoint before stopping on interruption. Journal method responses for exact local replay after phase-write failures; settle time charges once and block unknown-outcome redispatch.

- Give future ordinary-source reviewers exact allowed-corpus witness lookup and bounded draft-format validation inside their existing isolated session. Keep scientific judgments, scoring rules and prior reports unchanged.
- Bind the changed reviewer capability to a distinct prospective evaluation condition; retain the separate captured-source condition and its source-reader interface.
- Preserve immutable source references and historical 0.6.0/v4 observations while requiring a coherent current-adapter cohort for automatic readiness.

## 0.6.0

- Distinguish credit-bearing claims from independently valid context in coverage scoring. New v4 comparisons preserve prior v3 reports and unchanged source-reference/availability contracts.
- Measure reuse breadth from actually supported source lineages, preserving occurrence IDs and excluding attribution, access mentions and missing capture from promotion.
- Feed frozen public-development weaknesses into new task planning without exposing audit answers or rerating failed tests. Preserve concurrent campaign progress and prevent bookkeeping-only changes from creating new assignments.
- Skip unchanged rejected transfer generations so later recipes can progress. Preserve all scientific rejection and one-time correction conditions.
- Probe sources with bounded anonymous HTTP, supervised worker lifetime, immutable byte/access witnesses and independent maintenance review. Transport failures do not become scientific source-loss claims.
- Capture future benchmark interruptions before allowing verified bounded retries. Keep legacy incomplete capture explicitly blocked and retain all original costs and outputs.
- Include every new runtime module and guide in the explicit portable distribution manifest. Continuous scientific improvement and the unattended pilot remain unproven.

## 0.5.1

- Recover one documented lossless reference-copy encoding from its original durable response without repeating the author. Preserve the rejected state, bind every input and decoded result, and require fresh source review before solving.
- Specify expanded reference arrays in future correction requests. Keep existing requests immutable.
- Reject comparisons containing a scientific record that cannot be returned intact under a selected retrieval mode. The evidence-relative evaluator policy remains unchanged.

## 0.5.0

- Freeze exact allowed evidence and solver capabilities before evaluations. Distinguish scientific truth, accurate corpus attribution, feasible completion, and full research coverage. Retain historical scores without counting the older protocol toward current readiness.
- Qualify development transfers and both withheld-audit corpora prospectively; keep scientific references common while preventing candidate-only facts from being treated as baseline evidence. Reconstruct source, corpus, session and review receipts before audit admission.
- Precommit correctness and research coverage improvement endpoints for fresh paired audits, with no per-case loss across scientific and completion dimensions.
- Permit one narrowly scoped prereview transfer correction tied to explicit independent reviewer findings. Preserve rejected predecessors and require fresh editing, source review and qualification before any solver.

## 0.4.3

- Add optional private source archives and bounded reviewer-only access to exact
  captured projections. Preserve bytes, access/reuse records, extraction gaps
  and independent source checks; keep default experiments unchanged.
- Bind the new reviewer condition to references, comparison protocols and
  readiness cohorts. Different reviewer conditions cannot form one baseline.
- Retain private source-access receipts separately from graph trajectories and
  exclude operational archives from public downloads.

## 0.4.2

- State the scheduling-horizon enum in transfer task requests. Recover only the
  documented legacy prereview format failure from its original durable response,
  preserving authored questions, scope, output and the rejected state. Scientific
  reviews and comparison results remain immutable.

## 0.4.1

- Freeze three distinct development transfer tasks, separately authored references,
  and independent source/scope review before testing a narrow experimental recipe.
  Preserve recipe applicability, the original public baseline, and unfavorable results.
- Resume only verified transport failures inside the original case resource budget;
  preserve every attempt, aggregate costs, and reject replacement scientific judgments.
  Bound and account for interrupted reviewer calls as well as solver calls.
- Compare canonical evidence echoes consistently during candidate assembly while
  continuing to reject changed source metadata and locators.
- Recover run summaries from committed trace events after interruption; refresh live
  lifecycle metadata even when completion adds no access event.
- Protect transfer and source-recovery references from research workers and include
  the new portable runtime through the explicit public-file manifest.

## 0.4.0

- Separate inclusive 20% evaluation and 30% research quota reserves.
- Fair, checkpointed research/evaluation coordination with actual weekly budget rollover.
- Trace-grounded recipe distillation, fixed-applicability reuse tests, and preserved experiment origins.
- Private independent fresh cohort authoring and renewal after withheld-case consumption.
- Reference-grounded scoring of failed answers without credit for unsupported citations.
- Deny research-worker access to partial audit outputs and unsealed cohort drafts.


## 0.3.0 — Auditable learning and portable technical preview

- Bind withheld audits to paired baseline/candidate releases and common frozen,
  source-checked references. Preserve resumable sealed experiments and separate
  measured improvement from no detected regression. Add fresh cohort admission
  and safe aggregate export; legacy completion flags no longer unlock release.
- Match recipe comparisons on case, source bundle, reference, rubric, model
  configuration, resource budget and adapter version. Score abstention and
  completion, preserve missing usage as unknown, and count actually cited
  evidence toward the three-task/two-bundle promotion threshold.
- Preserve failed reviews, require changed corrective submissions, limit
  corrections to two, and keep original tasks, rubrics and trajectories intact.
  Milestone audit continuations share the campaign budget.
- Support replay-only inspection without the original full graph. Fix MCP
  pagination beyond 500 records. Guard local inspector origins and release paths.
- Admit public distribution files explicitly, reject symlinks and private
  extras, and exercise wheel, source and portable ZIP installation offline.
  Add cross-platform distribution CI and local storage portability repairs.
- Publish the specification review and explicit empirical limitations. No
  completed learning benchmark or autonomous scientific improvement is claimed.

## 0.2.0 — Scientific candidate example and evidence-access repairs

- Add a source-qualified PLA example spanning two grades, four specimen series,
  four preparation histories, ten tensile observations and four datasets.
  Preserve endpoint differences, dispersion, unknown conditions and source scope.
  Candidate preparation and scripted replay are offline; isolated source review
  and scientific admission remain separate.
- Add material-to-concept and specimen-to-material relationships, dimensional
  checks and original-to-normalized unit conversion validation. Test RDF and
  JSON-LD projection equivalence.
- Rebuild the default seed with the corrected vocabulary and projections while
  preserving all 262 identities, 243 structures and 26,128 seed records. This is
  a representation update, not new scientific validation.
- Preserve external evidence metadata, inspection receipts, permitted captured
  text and explicit content gaps in checksummed replay attachments. Attachments
  do not claim observed browser access or model delivery.
- Resolve each answer citation only to successful access before its citing
  event. Expose individual answer claims, mixed reviewer findings, source
  locators and original-content availability. Keep returned candidate-preview
  records visible independently of proposed overlays.
- Record MCP argument-validation failures and distinguish empty accesses,
  candidate proposals, source attachments, review events and confirmed delivery.
- Add corpus preflight with a 512,000-character long-context limit; failed or
  incomplete mode comparisons cannot count as completed evaluations.
- Require empirical readiness in addition to three shadow campaigns before
  automatic publication: full development baselines, tested memory, a fresh
  sealed audit and resolved source changes.
- Rank current domain-relevant publication leads, resume discovery cursors and
  add bounded, independently reviewed source maintenance with durable revisions.
- Reserve worker time before launch and stop owned worker processes after
  timeout or coordinator termination. Preserve comparison checkpoints and
  bounded retry counts across restarts.
- Permit compatible ontology extensions for untouched campaign jobs while
  retaining historical releases, benchmark cohorts and aggregate budgets.
- Recover overlapping source revisions through a fresh, hash-bound combined
  review. Persist oversized review deferrals without starving smaller items.
- Package immutable releases by release identity even when the build checkout
  reaches the selected release through a filesystem link.

The public default data remains the 26,128-record seed. The shipped scientific
example is candidate data; its corrected answer and source groups passed
isolated reviews locally. No completed live baseline campaign, default-enabled
learned recipe, expert validation or successful unattended pilot is claimed.

## 0.1.0 — Portable seed, inspection and guarded research

- Preserve all 262 wiki polymer identities and 243 canonical V3000 structures.
- Distribute 26,128 canonical records, qualified assertion identities, source
  occurrences, independent publication identities and overlapping taxonomy axes.
- Add offline ontology browsing, bounded graph/table exploration, release
  comparison, live access, replay, parallel lanes, exact payloads and citations.
- Provide Python, CLI and MCP access with immutable release pins and independent
  returned, traversed, delivered, cited, supported and reuse-tested labels.
- Add separate scientific, experimental-vocabulary and research-memory gates,
  subscription-only Astra workers, isolated review, quota reserve, retries and
  durable campaign checkpoints.
- Add 24 development cases, 24 private audit cases, fixed-corpus baseline modes,
  independently prepared references, measured recipe admission and sealed audits.
- Keep automatic scientific publication behind three real shadow campaigns.

The initial data release is a seed import. Benchmark references require source
verification before scoring. This release does not claim demonstrated scientific
improvement, expert validation or completion of the three-campaign pilot.
