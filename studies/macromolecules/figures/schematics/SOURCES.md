# Schematic figures: sources and captions

Figures 1 and 2 of the Macromolecules manuscript and the TOC graphic, drawn by `draw.py` with `kit.py`:

| File | Size | Use |
| --- | --- | --- |
| `fig1.svg` / `.pdf` / `.png` | 7.0 x 4.88 in | Figure 1, overview |
| `fig2.svg` / `.pdf` / `.png` | 7.0 x 4.68 in | Figure 2, methods |
| `toc.svg` / `.pdf` / `.png` | 3.25 x 1.75 in | TOC graphic: the loops of Fig. 1b, the counts, one finding |

The SVG is the editable master: 1 unit = 1 pt, every label is a `<text>` in Arial, each panel is a `<g id="panel-x">`,
arrowheads are polygons (no markers), so it opens cleanly in Illustrator or Inkscape. The PDF is printed from the SVG by
headless Chrome at the exact page size, with Arial embedded as TrueType. The PNG is that PDF at 600 dpi (ACS line art and
combination figures). Redraw with

    OOPC_STUDY_ROOT=<main checkout> python -B studies/macromolecules/figures/schematics/draw.py

It needs Chrome and `pdftoppm` (poppler). It opens the seed release read-only and parses the frozen code; it never
imports `oopc` or calls an engine.

## Style

The colours, sizes and line widths come from `../style.py`, parsed rather than imported.

- **Colour.** One colour per status (Reviewed `#0a7e3a`, Added `#15b194`, Needs checking `#eda100`, Rejected
  `#e34948`), used only for findings and their statuses, with one exception at the owner's request (2026-10-19):
  the "initial WOP seed" arrow in Fig. 1b and the TOC graphic is Reviewed's green. The seed is not reviewed (its
  claims keep status `seed`), so the arrow always carries its label. The ontology, its arrows, the growth curve and
  the prompt versions use the blue of the K arms (`#0b5bae`). The plain session uses P's neutral (`#52514e`).
  Everything else is neutral ink.
- **Type.** Arial at 9 pt (panel letters, headline counts), 7 pt (titles, stage names) and 6.5 pt (labels). Nothing
  is smaller except the subscript of T<sub>g</sub>. Panels carry names and key parameters, not explanations; the
  caption explains.
- **No people.** The researcher and the reviewer are sessions of the scaffold, not people. They appear as the branches
  of Fig. 1b, and Fig. 2c and 2d expand those branches under the same names, "each question" and "after each answer".
  The plain session is a pill.
- **Lines.** 1.0 pt for main arrows and boxes, 0.5 pt for secondary ones.
- **Panels.** Each panel sits in a thin rounded frame (0.5 pt, `LIGHT`) whose top edge breaks for the panel letter and
  title (`Canvas.frame` in `kit.py`; the layout is `page()` in `draw.py`). The TOC graphic has no panels and no
  frames.
- **Panel letters.** Bold lowercase without parentheses (**a**, **b**, …), as `style.letter` draws them in Figures 3
  and 4. To use "(a)" instead, change the letter text in `Canvas.frame`.

## What each element rests on

Every number and example is read at draw time. `draw.py` stops if a file disagrees with the manuscript (`facts()`).

**Figure 1**

- **a** The question is illustrative. Each value is a PVC Tg finding in knowledge snapshot
  `oopc-knowledge-db1fc22ca88a0c0b45b9218b`:
  - film, DMA at 1 and 10 Hz: `finding:7944458e3bee-19`, `-20` (doi:10.3390/ma15134658)
  - DSC application note, neat PVC and 20 wt% DOP: `finding:7944458e3bee-2`, `-12` (Hitachi application brief)
  - SG-5 study, pure PVC and 50 phr DEHP: `finding:b9585bbac0ca-2`, `-1` (doi:10.1186/s42825-019-0006-8)

  "The plain session rereads and keeps nothing" is arm P (`docs/core-loop.md`, Measure; manuscript §2.4).
- **b** Two branches around the ontology, which closes the cycle between them (`loops()` in `draw.py`, also drawn
  in the TOC graphic).
  - **Layout.** Each branch sits on a shaded, dotted background named for when it runs. Bubbles in a column share a
    width, and the two backgrounds are equally tall. The gaps around the ontology take the rest of the panel's
    height.
  - **As the released code runs them** (0.13.0, tag `study-freeze-4`; 2026-10-27). The experiments' frozen code
    returned the findings with the answer and deposited them before the answer was marked done; the released code
    answers first and saves second (manuscript §2.1, SI S3.1), so the lower branch is named "after each answer, in the
    background".
  - **Each question.** Ask, then Web (optional, dashed) and Reuse side by side, then Answer. Reuse reads the ontology
    (`search_knowledge` first, `RESEARCHER` step 1). Web covers only what saved knowledge lacks (step 2). "Shown at
    once": `ask.Questions._run` marks the question completed when turn 1 returns, before anything is saved.
  - **After each answer, in the background.** Answer, then Deposit, then Review, in one background thread
    (`_deposit_in_background`), while the queue's next question may already run.
    - Deposit: `_save_findings` resumes the saved session for turn 2 (`deposit_turn`, the `DEPOSIT` instructions),
      and `_store` writes its findings and source notes to the ontology (`knowledge.deposit`). Each finding is Added
      or Needs checking by how its value was obtained.
    - The arrow to Review is dashed because only some findings go on. After the deposit, `_review` files titles,
      captures the cited sources and, when something waits, runs `reviewer.review`, which reads that answer's waiting
      findings back from the store (`findings_to_review`: Needs checking, or Added with a pending 1-in-5 spot check).
    - The verdicts go back to the ontology (`knowledge.record_review`). The arrow is blue: like Deposit's, it
      writes to the ontology.
  - **No return arrows.** The cycle runs through the ontology: Deposit writes to it, and the next question's Reuse
    reads it.
  - **No ontology → Answer arrow.** The answer is finished before it reaches the lower branch. The ontology is also
    read at Ask (ambiguous names) and at Deposit (duplicate check, polymer filing); that detail is left to Figure 2.
  - **Ontology.** It starts from the initial WOP seed: 274 polymer identities, which findings are filed under. The
    store of findings itself starts empty (Part B restarts begin from "an empty knowledge store").
  - **Not drawn.** Measure (the parity set) is on neither branch.
- **c** The family, members and abbreviations come from the seed release `oopc-6ad56d8b354d053bcc3cf3a1`
  (`graph.sqlite`, `broader` edges): PAEK family `wop-000081`; PEEK `-082`, PEKK `-083`, SPEEK `-235`.
  - Bars and counts (76, 52, 82) are the snapshot's findings by `polymer`, stacked by status.
  - The grades "Kepstan 6002" and "Kimya PEKK-A" are named in the `material` of PEKK findings. They are not seed
    records.
  - The card is `finding:7ec2dd2b46e7-1` exactly as the snapshot carries it. The snapshot has no excerpt.
- **d**
  - The curve joins the end of each build stage in `dataset-kf/growth.json` (`byRun`, findings in KF credited to each
    answer). It ends at 8,899.
  - The four counts come from `table1/table1.json` (`completedAnswers`) and the snapshot manifest.
  - The three edit decisions (adopted, adopted, not adopted) are the recursive test's
    `eval/round-{1,2,3}/dev/decision.json`.

**Figure 2**

- **a**
  - Seed record counts by type come from `graph.sqlite` and equal Table 1.
  - The claim count is the sum of the graph's edges. Every edge is a Claim record. Concepts link to structures,
    facets, processes and sections; sections to evidence (`supportedBy`); evidence to documents (`evidenceFrom`). The
    single bracket stands for all of these, direct or not.
  - The four statuses are `STATUS_LABELS` in `oopc/knowledge.py`. A finding's `subject` (`wop-NNNNNN`) links it to a
    concept ("polymer id"). Findings and source notes from one document share `source_key` (the double arrow).
    Reviews attach to findings by id.
  - The field lists are left to the caption and to Fig. 1c's card: `FINDING_FIELDS`, `NOTE_FIELDS` (+ `read_url`),
    `record_review`.
- **b**
  - EVOH44 resolving to ethylene–vinyl alcohol copolymer by grade number is from `docs/core-loop.md`. "Ultem" is a
    seed `tradeNames` entry. HDPE and PEI (two seed polymers) come from seed `abbreviations`.
  - The lineage rule (HDPE keeps the polyethylene family, not LDPE or LLDPE) is `knowledge.lineage`.
  - The search steps follow `knowledge.search` and `_relevant`. Names are expanded by `expand`; the index is FTS5;
    the polymer's lineage only. The tool's limit runs 10–25, with polymer-only matches filling to `FILL` = 10. Then
    come `SAME_SOURCE` = 12 and 3 notes in the tool's compact mode. Results are grouped Reviewed, Added and Needs
    checking (the three dots); Rejected are excluded.
- **c**
  - The branch is Fig. 1b's.
  - The prompt is `86404bf073ce`, the released prompt's version (`ask.prompt_version` at freeze-4: the SHA-256 of
    `RESEARCHER` and `DEPOSIT`), recomputed by `draw.py` and checked against the confirmation run's pins. The
    experiments' frozen prompt was `0b7bb1483235` (`RESEARCHER` at freeze-2), also checked.
  - The budget is `DEPTHS["standard"]`, the same at freeze-2 and freeze-4 (checked, as are the search limits, the
    spot-check rate and the review time limit).
  - The three kinds of statement come from `RESEARCHER` and `ANSWER_SCHEMA`. "Shown at once" as in Fig. 1b: turn 1
    returns the answer alone, and its findings and source notes come in turn 2 (panel d).
- **d**
  - "Turn 2" is `deposit_turn`: the saved session resumed with `DEPOSIT`, whose findings and source notes replace
    turn 1's, which are to be empty (`Questions._deposit`). The pill keeps Answer's width, so the row is as before.
  - Validity is `clean_finding` ("dropped" findings are counted); "new" is `same_fact` / `_known_match`.
  - "read" means `derivation` read. "derived" means figure, converted or combined. A name the context cannot settle
    also waits for review (`settle_names`), which is left to the caption.
  - The dashed arrows are the review sample: every Needs checking finding, and 1 in 5 Added ones (`spot_check_rate`
    0.2).
  - The verdicts are supported → Reviewed and unsupported → Rejected; uncertain → Needs checking is the arrow back up
    (`docs/core-loop.md`, "What researchers see").
- **e** The steps, the improver's inputs (`IMPROVER`), the edit limits (600 / 1,000, `restart.EDIT_LIMITS`), the rule
  (`recursive.decide`, `TOKEN_LIMIT` = 1.10, `MIN_PAIRS` = 27), 30 development questions (`dev.json`) and 100 tasks
  per round (`rounds.json`).

## Captions

The captions of Figures 1 and 2 are in `main.tex` on branch `manuscript-revision`. They were written on 2026-10-27
from the proposals once kept here, for the released code: Fig. 1b and Fig. 2c and 2d describe the answer shown at
once and the second turn in the background.

## Noticed while checking (not changed)

- Manuscript §2.2 and §2.6 say "nine reviewer-approved trade names". Seed release `oopc-6ad56d8b354d053bcc3cf3a1` has
  **11** trade names on **nine** polymers: Surlyn; Ultem; Teflon FEP; Hyflon PFA, Teflon PFA and Chemours 340X; Exxon
  Butyl; Viton; Nafion; POKETONE and Carilon. "Trade names for nine polymers" would be exact.
- The step table in `docs/core-loop.md` says the researcher has "two knowledge tools". Its text, the code and the
  manuscript all say one (`search_knowledge`).
