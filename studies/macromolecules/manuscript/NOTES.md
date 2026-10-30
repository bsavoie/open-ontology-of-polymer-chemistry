# Macromolecules manuscript: drafting notes

The main text is `main.tex` (ACS `achemso`, `journal=mamobx`) and the Supporting Information `si.tex`
(`manuscript=suppinfo`), both with `refs.bib`. Compile on Overleaf (the group default) or locally with Tectonic
(`brew install tectonic`), which fetches the packages it needs and runs BibTeX itself:

    tectonic main.tex
    tectonic si.tex
    tectonic preprint.tex

Since 2026-10-29 (owner) `main.tex` and `si.tex` both print the OOPC wordmark at the bottom right of every page,
level with the page number, so `preprint.tex` gives the same document as `main.tex`. For a submission without the mark,
delete the `\providecommand` and the hook marked "OOPC mark" in each file. The wordmark files (`figures/oopc-wordmark*`,
SVG and PDF, letters as outlines) are drawn by `../figures/wordmark.py` from the app's font and colours:
`oopc-wordmark-paper` for a white page, which the preprint uses, and `oopc-wordmark`, the app's dark-tile icon.

History: abstract, introduction and methods 2026-10-19; results, discussion and conclusions 2026-10-21; strategic
revision 2026-10-27 (below). On 2026-10-29 the owner set the title, the abstract was rebuilt from the owner's notes, the
introduction gained a paragraph on agent memory and harnesses, the section on the released code was cut (one sentence
in Section 2.1 now points to SI S3.1 and S12), and the conclusions were revised: accumulation is the present advantage,
the cross-engine result is read as portable memory, and the reflection result is scoped to tests with little room or
power, with four hypotheses for when the ontology's vocabulary should matter. Later that day the owner wrote the abstract and
conclusions and an AI statement (in the acknowledgement) in the Word redline; they were copied into `main.tex` verbatim,
with only LaTeX escapes, straight apostrophes and one sentence per line. Section 2.1 now says the harness includes the ontology
reflection as an optional job, off by default; that is true once branch `claude/funny-leakey-71a826` (the reflection
job) is merged and published, so do not submit before then, or revert that sentence.

## The 2026-10-27 revision

- **Structure.** Modelled on the group's recent papers: no main-text Methods section. Results and Discussion opens
  with an overview of the loop (Section 2.1: accumulation, review, retrieval and the two reflection heuristics) and a
  short experimental design (2.2), then the results. The main text is about 6,000 words with a 150-word abstract; the
  previous draft was about 11,200.
- **Moved to the SI** (`si.tex`, Sections S1–S16, cited literally from `main.tex`, so keep the order): every former
  Methods subsection, Table 1 (now Table S1), the extended results (reuse details, passes model, ladder details, web-off
  and cross-engine, case-study replicate numbers, restarts' build and edits), and the prompts verbatim
  (`si/prompt-*.txt`, exported from the freeze-2 and freeze-4 worktrees).
- **Added.** Section 2.8 and Figure 6 on the ontology refinement (Part C), from
  `docs/exec-plans/active/ontology-refinement-plan.md` and `.oopc/study/analysis/refinement/results.json`
  (Figure 6 is drawn by `studies/macromolecules/figures/fig6.py`); SI S3.1 on the released two-turn
  code (0.13.0), from `app-latency-plan.md`; SI S12 and Table S5 on the confirmation run (`confirmation-plan.md`,
  "Result — 2026-10-27"). Figures S1 and S2 are the restarts' figures (`fig_restarts_build`, `fig_restarts_final`).
- **Checked.** An independent session checked every number in both files against its source; its corrections are in.
  A second independent session checked every tracked-change rationale against its change; its corrections are in, and
  it found three defects in the text (undefined Tg, DSC and DMA; the unnamed stores behind "53 to 55 of 60"; Figure
  1d's undefined "recursive test"), now fixed.
- **Tracked changes.** The Word redline of `main.tex` (raw LaTeX, one rationale comment per change) is built outside
  the repository from `main.tex` at `73684a1` and this revision.

## Author actions (red `\tbd{}` in the PDF)

| Where | What |
| --- | --- |
| Author list | co-authors and affiliations |
| Supporting information | the DOI; the SI's own author list once co-authors are known |
| Data availability | repository and DOI for the seed release and knowledge snapshot (the code's public repository is in since 2026-10-29) |
| Acknowledgement | funding (it already says the figures were drawn by scripts Claude Opus 5.5 wrote; the owner's AI statement sits after the abstract, by the owner's choice, although ACS asks for it in the acknowledgement) |

## Where the numbers come from

- **The confirmation run** (one sentence in Section 2.1; SI S3.1, S12, S15): `docs/exec-plans/active/confirmation-plan.md`, "Result —
  2026-10-27", from `.oopc/study/analysis/confirm/results.json`. All five predictions were met, so the text describes
  0.13.0; the release's higher token cost per answer (about 1.27 of the frozen code's) is reported beside it.

- **Results and the filled placeholders**: the study's result sections on `main` at `6f25730`, each written against its
  pre-registered predictions with every headline number recomputed by a second session:
  `docs/exec-plans/active/macromolecules-study-plan.md` ("Run accounting — 2026-10-21", "A1 result", "A5 result",
  "A4 result", "A2, A3 and E8 result") and `docs/exec-plans/active/restart-study-plan.md` ("Result — the build",
  "Result — the final evaluation"). Limits and defects behind several sentences are tracker items CL-18, CL-20 and
  CL-23 to CL-26 (`docs/exec-plans/tech-debt-tracker.md`). Every number in the new text was checked against those
  sources and the figure manifest; the four not found verbatim are derived (63.2% from 0.632, 156 °C from the Tg
  table, and 1,874 and 3,443 as totals of the review outcomes in Figure 3f).
- **The cautions the study orchestrator listed are in the text**: quality is source support from a Codex checker, led
  by contradicted statements, completeness and sourced results, with passes second (3.3); E8's six artefacts removed,
  41 contradicted against Codex's 0, cost claimed and quality parity not (3.5); E9's "0 presented" qualified by the 9
  hedged repeats of 12.27 MPa and the 25 of 50 after review (3.8); the causes of contradicted statements (CL-24
  conversions, CL-25 page number, CL-18 silence read as the source's); the not-met and partly-met predictions,
  including the mid-question cost and sourced-result drop, the unreproduced one-web-call saving, the edited prompts'
  277 against 295, and Part B prediction 4's strict miss (3.3, 3.7); and the cut stores' six undone merges (2.9) and
  the saturating dose (3.6).
- **Methods and records**: the frozen knowledge base KF (A1), and the pinned code at tag `study-freeze-2` (`1c06a7f`)
  for the prompt, reviewer and checker instructions, depth budgets and the search and deposit rules.
- **Tg comparison**: the median over the 15 polymers of (median DMA − median DSC), 12.0 °C. The text names the two
  largest differences (TPU +142 °C, ionomer −156 °C) as likely different transitions, phases or grades.
- **Question bank**: the campaign's bank names 135 polymers (40 from the 200-task run's topics and 95 new), counted from
  `studies/macromolecules/campaign/make_questions.py`.

## Figures

- **Figures 1 and 2 and the TOC graphic** are the PDF exports in `figures/`, copied from
  `studies/macromolecules/figures/schematics/` (SVG masters, `draw.py`, `SOURCES.md`), merged here from branch
  `claude/quirky-wilbur-32c810` on 2026-10-27. Until then the manuscript carried the older drawings of `18c73ad`
  (Fig. 1b a six-step loop with Measure; Fig. 1c dots; Fig. 2 with explanations in the panels). The branches of
  Fig. 1b and Fig. 2c and 2d now show the released code: the answer shown at once, then the second turn, deposit
  and review in the background. Redraw with `OOPC_STUDY_ROOT=<main checkout> python -B draw.py` and copy the three
  PDFs into `figures/`.
- **Figures 3–5** are the script-drawn renders from `.oopc/study/analysis/figures/` in the main checkout (private,
  drawn by `studies/macromolecules/figures/`; the owner allowed any answer or trace in the figures). Their captions are
  rewritten from `manifest.json`: Figure 4's 1,000-word caption is cut to about 190 words, its numbers now in the text.
- **Layout**: single-spaced throughout since 2026-10-29 (owner), main text and SI; `\AtBeginDocument{\singlespacing}`
  overrides the class's double spacing. The figures stay capped at 0.5–0.62 of the text height. If the journal wants a
  double-spaced submission, delete those two lines. The title is pulled up by three lines and the abstract widened
  (owner, 2026-10-29) so that the abstract and the AI statement fit on page 1; both are the two preamble lines after
  the spacing.

## Choices to confirm

- **Title**: the owner's (2026-10-29), which names the project and its memory mechanisms; the SI's title follows it.
  The earlier working titles were "Research Agents That Remember: Provenance-Tracked Accumulation of Polymer Property
  Knowledge" and the one kept as a comment.
- **Abstract and conclusions**: written by the owner (2026-10-29) and kept in the owner's words; do not revise them
  without being asked. The abstract is about 435 words, above the 100–150-word limit that a search result gave for
  Macromolecules; the live ACS page sits behind a bot check, so confirm the limit. The introduction's third paragraph
  (added 2026-10-29) argues the memory and lock-in point, with seven new references.
- **No main-text Methods** (since 2026-10-27): the loop is explained in Section 2.1 and the design in 2.2, with the full
  methods in the SI. If a reviewer or the journal wants a Methods section, SI S1–S8 can return as one.
- **Results and discussion combined**, in eight subsections; interpretation is marked with "we" and kept next to the
  evidence. Experiment labels (A2–A5, E8, Part C) are used only in the SI; the main text describes each experiment.
- **Six figures**: Figure 6 (ontology refinement) is new. If the journal limits figures, Figure 6 can move to the SI
  with Tables S2–S4, and Section 2.8 keeps its numbers in the text.
- **Trade names**: nine were approved by a reviewer in the seed migration `d945a28`; the final seed pin added
  POKETONE and Carilon, so the seed holds 11. SI Section S2 says "trade names recorded in the seed".
- **Engines** are named as products and model identifiers (Codex `gpt-6.1-sol`, Claude Code `claude-opus-5-5`).

## References

`refs.bib` has 60 entries, 50 of them cited (seven added 2026-10-29 for agent memory and harnesses; see
`refs_notes.md`). 52 were checked on 2026-10-19 against Crossref (by DOI), the arXiv page,
the NeurIPS proceedings or the W3C page; `WOP2026Wiki` (the wiki repository) was not. `refs_notes.md` says what each
supports and how it was checked. Things to know before submission:

- Five cited works had no retrievable abstract (publisher bot challenges), so their use rests on title and
  bibliographic metadata: `Chen2021Polymer`, `McCusker2020NanoMine`, `Hutchinson2009Glass`, `Muramatsu2003Oxygen` and
  `GraciaFernandez2010Comparative`. Each supports only a general statement; check the full text.
- `GraciaFernandez2010Comparative` compares DMA with temperature-modulated DSC. It is cited in Results only for the
  general point that a dynamic Tg from a mechanical loss peak lies above the calorimetric value.
- PaperQA, PaperQA2, MemGPT, Voyager, DSPy, OPRO and the Darwin Gödel Machine are cited as arXiv preprints; no
  published version was found on Crossref.
- Aucejo 1999 measures how humidity lowers EVOH's Tg, not its oxygen permeability, so it is not cited (Muramatsu 2003
  and the Mokwena 2012 review are). It stays in the .bib with the other uncited, verified alternates.
- The intro cites `Tchoua2016Blending` for labor-intensive curation; it is the paper usually cited for PPPDB, but its
  abstract does not name PPPDB.
