# Tester guide

Browsing works offline; asking questions also needs a signed-in ChatGPT (Codex)
or Claude Code subscription. This is a technical preview: a finished answer and a
reviewed finding are different things.

## Install and open

Install Python 3.9 or later with SQLite FTS5, open a terminal in the project or
portable-release folder, and run:

```sh
python3 -m oopc verify
python3 -m oopc inspect --open
```

Keep the terminal running. The app opens at `http://127.0.0.1:8765`. See
[installation](installation.md) for the wheel, checksums and platform details.

## Connect and ask

1. Open **Settings → Research engine**, select ChatGPT (Codex) or Claude Code
   and use its **Connect** button if needed. The provider's own CLI stores the
   credentials; connecting starts no research. See [Codex sign-in](openai-connection.md)
   or [Claude Code sign-in](claude-connection.md) if it is unavailable.
2. On **Ask**, enter a bounded question, choose a depth (Quick, Standard or
   Thorough caps time, web searches and sources read, which is what drives token
   use; the line under it says what the chosen depth allows) and submit. Name the material, property and conditions
   you care about, for example: “How does annealing temperature change the
   crystallinity of PLA films measured by DSC? Keep grade and conditions explicit.”

## Read the answer

While it runs, the page shows which stage the researcher is in (checking what
we know, reading sources, writing), the clock against the
time limit, and web searches and pages read against the depth's budget. These are activity counts, not
evidence that a conclusion is correct. You can leave and come back from **History**.

A finished answer shows its numbered sources and, under **What this answer
added**, the findings it saved: each fact it read in a source, with the locator
and a short excerpt. By default facts the research agent read directly in a
source's text or a table are **Added** at once, and ones it read off a figure,
converted or combined **Need checking**, saying which. Its own reasoning is labelled
"Interpretation:" and textbook background "Background:"; everything else it
reports is cited. To require review of every
finding, choose **Review every finding first** under Settings → Adding findings. Imported polymer pages
keep their seed status; citing an imported source does not verify it.

If a question fails, the page says why (time limit, usage limit, sign-in, or a
session that stopped twice) and offers **Try again**.

## Review and reuse

After the answer, a separate reviewer session opens the source of each finding
waiting for review, and of a sample of the added ones, and marks it **Reviewed**,
**Rejected** or leaves it **Needs checking** (could not confirm), with a
one-sentence reason. If a review could not run, **Run the loop now** on
**Knowledge** retries it. The most relevant reviewed and added findings are what
the next question finds first; rejected ones are hidden from the researcher.

To see reuse, ask a related question after a review. Its **How this answer was
found** section counts the saved findings it reused, and its sources list them. Reuse is likely on a covered topic, not guaranteed.

With background research on (Settings: a number of questions a week), an
answer's open questions join the research queue and the loop asks up to that
many a week. See [the core loop](core-loop.md) for details.

## What stays private

Questions, answers, findings, source excerpts and traces stay in the workspace's
`.oopc/` folder and are excluded from public bundles. Questions and reviews are
sent to the selected subscription provider; later questions may read earlier
findings and send them to their provider. Replay sharing is a separate explicit
action, and a replay can contain private content. Public access to a source does
not imply permission to redistribute it.
