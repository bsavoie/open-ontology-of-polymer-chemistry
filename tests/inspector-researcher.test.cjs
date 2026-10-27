const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ui = require('../oopc/web/researcher.js');

const web = path.join(__dirname, '../oopc/web');
const PCL = `polycaprolactone-unit
     RDKit          2D

  0  0  0  0  0  0  0  0  0  0999 V3000
M  V30 BEGIN CTAB
M  V30 COUNTS 10 9 1 0 0
M  V30 BEGIN ATOM
M  V30 1 * -5.196152 0.000000 0.000000 0
M  V30 2 O -3.897114 0.750000 0.000000 0
M  V30 3 C -2.598076 -0.000000 0.000000 0
M  V30 4 C -1.299038 0.750000 0.000000 0
M  V30 5 C 0.000000 -0.000000 0.000000 0
M  V30 6 C 1.299038 0.750000 0.000000 0
M  V30 7 C 2.598076 0.000000 0.000000 0
M  V30 8 C 3.897114 0.750000 0.000000 0
M  V30 9 O 3.897114 2.250000 0.000000 0
M  V30 10 * 5.196152 0.000000 0.000000 0
M  V30 END ATOM
M  V30 BEGIN BOND
M  V30 1 1 1 2
M  V30 2 1 2 3
M  V30 3 1 3 4
M  V30 4 1 4 5
M  V30 5 1 5 6
M  V30 6 1 6 7
M  V30 7 1 7 8
M  V30 8 2 8 9
M  V30 9 1 8 10
M  V30 END BOND
M  V30 BEGIN SGROUP
M  V30 1 SRU 0 ATOMS=(8 2 3 4 5 6 7 8 9) XBONDS=(2 1 9) CONNECT=HT LABEL=n BRKXYZ=(9 -4.5466 -0.224981 0 -4.5466 0.975019 0 0 0 0) BRKXYZ=(9 4.5466 -0.224981 0 4.5466 0.975019 0 0 0 0)
M  V30 END SGROUP
M  V30 END CTAB
M  END`;

test('answer markdown escapes markup and keeps only http(s) links', () => {
  const html = ui.renderMarkdown('<img src=x onerror=alert(1)> **bold** [bad](javascript:alert(1)) [good](https://example.org/a?b=1&c=2)');
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(html, /<strong>bold<\/strong>/);
  assert.doesNotMatch(html, /href="javascript:/);
  assert.match(html, /<a href="https:\/\/example\.org\/a\?b=1&amp;c=2" target="_blank" rel="noopener noreferrer">good<\/a>/);
});

test('answer markdown renders tables and lists, and numbers cited evidence', () => {
  const cite = id => id === 'evidence:wop-000217:study' ? 1 : null;
  const html = ui.renderMarkdown('| Series | Modulus |\n|---|---|\n| A | 4400 MPa |\n\n- first\n- second\n\nSee [evidence:wop-000217:study, §2](https://example.org/p) and `evidence:wop-000217:study`.', {cite});
  assert.match(html, /<table><thead><tr><th scope="col">Series<\/th>/);
  assert.match(html, /<td>4400 MPa<\/td>/);
  assert.match(html, /<ul><li>first<\/li><li>second<\/li><\/ul>/);
  assert.match(html, />\[1, §2\]<\/a>/);
  assert.match(html, /<a class="cite" href="#source-1" data-source="1">\[1\]<\/a>/);
  assert.doesNotMatch(html, /evidence:wop-000217:study/);
});

test('polymer and section identifiers become readable polymer links', () => {
  const names = new Map([['wop-000217', 'Polylactide']]);
  assert.deepEqual(ui.recordReference('wop-000217', names), {href: '#/polymers/wop-000217', label: 'Polylactide'});
  assert.deepEqual(ui.recordReference('section:wop-000217:mechanicalProperties', names), {href: '#/polymers/wop-000217', label: 'Polylactide — mechanical properties'});
  assert.equal(ui.recordReference('claim:abc', names), null);
  assert.match(ui.renderInline('`wop-000217`', {record: code => ui.recordReference(code, names)}), /<a href="#\/polymers\/wop-000217">Polylactide<\/a>/);
});

test('imported seed records are never presented as reviewed; findings say how they were checked', () => {
  assert.equal(ui.recordStatus({status: 'seed'}).label, 'Imported draft');
  assert.match(ui.recordStatus({status: 'seed'}).note, /Not yet independently reviewed/);
  assert.deepEqual(['supported', 'unreviewed', 'uncertain', 'unsupported'].map(status => ui.recordStatus({status}).tone), ['good', 'warn', 'warn', 'bad']);
  assert.match(ui.recordStatus({status: 'supported'}).note, /separate reviewer/);
  assert.equal(ui.recordStatus({}).label, 'Status unknown');
});

test('an answer states what happened to its findings, in plain words', () => {
  assert.equal(ui.provenanceSummary({}), null);
  assert.equal(ui.provenanceSummary({result: {answer: 'x'}}).label, 'Nothing new saved');
  const added = ui.provenanceSummary({result: {}, deposit: {findings: 3, reviewStatus: 'nothing-to-review', counts: {accepted: 3}}});
  assert.deepEqual([added.label, added.tone], ['Findings added', 'good']);
  assert.equal(added.note, "Added 3 findings on the research agent's judgement.");
  const mixed = ui.provenanceSummary({result: {}, deposit: {findings: 3, reviewStatus: 'pending', waitingReview: 2,
    counts: {accepted: 2, unreviewed: 1}}, reusedFindings: {cited: 2, supported: 1, added: 1}});
  assert.equal(mixed.label, '2 findings waiting for review');  // The flagged one and a sampled added one.
  assert.match(mixed.note, /sent 1 finding for review/);
  assert.match(mixed.note, /reused 2 saved findings\./);
  const reviewed = ui.provenanceSummary({result: {}, deposit: {findings: 3, reviewStatus: 'reviewed', counts: {accepted: 1, supported: 1, unsupported: 1}}});
  assert.deepEqual([reviewed.label, reviewed.tone], ['Findings saved', 'warn']);
  assert.match(reviewed.note, /a separate reviewer checked 2: 1 confirmed, 1 rejected/);
  assert.equal(ui.provenanceSummary({result: {}, deposit: {findings: 1, reviewStatus: 'failed', counts: {}}}).label, 'Review did not finish');
  assert.equal(ui.provenanceSummary({result: {}, origin: 'legacy'}).label, 'Earlier answer');
  assert.equal(ui.recordStatus({status: 'accepted'}).label, 'Added');
  assert.deepEqual(['unreviewed', 'uncertain', 'unsupported'].map(status => ui.recordStatus({status}).label),
    ['Needs checking', 'Needs checking', 'Rejected']);
});

test('already known findings and spot checks are reported plainly', () => {
  const repeat = ui.provenanceSummary({result: {}, deposit: {findings: 0, duplicates: 2, counts: {}}});
  assert.equal(repeat.label, 'Nothing new saved');
  assert.match(repeat.note, /2 findings were already known and not saved again\./);
  const one = ui.provenanceSummary({result: {}, deposit: {findings: 1, duplicates: 1, reviewStatus: 'nothing-to-review', counts: {accepted: 1}}});
  assert.match(one.note, /1 finding was already known/);
  assert.equal(ui.knowledgeSummary({spotChecks: {checked: 10, unsupported: 1, uncertain: 2, unsupportedRate: 0.1}}).spotText,
    'Spot checks: a reviewer also checked a sample of 10 added findings; 1 was rejected (10%) and 2 inconclusive.');
  assert.equal(ui.knowledgeSummary({spotChecks: {checked: 0, pending: 3}}).spotText, '');
  assert.equal(ui.knowledgeSummary({}).spotText, '');
});

test('question state and failures use plain, truthful labels', () => {
  assert.deepEqual(ui.taskState({status: 'running'}), {label: 'Researching…', tone: 'neutral', busy: true});
  assert.equal(ui.taskState({status: 'queued'}).busy, true);
  assert.equal(ui.taskState({status: 'completed'}).label, 'Answered');
  assert.equal(ui.taskState({status: 'failed'}).busy, false);
  assert.match(ui.failureMessage({reason: 'timeout'}), /time limit/);
  assert.match(ui.failureMessage({reason: 'quota'}), /usage limit/);
  assert.match(ui.failureMessage({reason: 'crashed'}), /twice/);
  assert.equal(ui.failureMessage({reason: 'other', message: 'Specific'}), 'Specific');
  assert.equal(ui.failureMessage(null), 'The research stopped before it finished.');
});

test('quota hints and sign-in links use researcher language and provider hosts', () => {
  assert.equal(ui.quotaHint({remainingPercent: 64.4}, undefined, 'Claude Code'), 'Claude Code has 64% of its usage window left.');
  assert.match(ui.quotaHint({remainingPercent: 12}, 30, 'Claude Code'), /background review waits until it is above 30%/);
  assert.match(ui.quotaHint({remainingPercent: null, reason: 'unrecognized-report'}, undefined, 'Claude Code'), /changed format/);
  assert.equal(ui.quotaHint({remainingPercent: null}, undefined, 'Claude Code'), '');
  assert.equal(ui.quotaHint(null, 30, 'Claude Code'), '');
  assert.equal(ui.loginLink('https://claude.ai/oauth/authorize?a=1', 'claude-code'), 'https://claude.ai/oauth/authorize?a=1');
  assert.equal(ui.loginLink('https://claude.ai/oauth/authorize', 'codex'), null);
  assert.equal(ui.loginLink('https://auth.openai.com/x', 'codex'), 'https://auth.openai.com/x');
  assert.equal(ui.loginLink('http://claude.ai/', 'claude-code'), null);
  assert.equal(ui.runtimeLabel('claude-code'), 'Claude Code');
  assert.equal(ui.runtimeLabel(undefined), 'ChatGPT (Codex)');
});

test('the knowledge summary counts the loop and keeps unknown counts unknown', () => {
  const summary = ui.knowledgeSummary({knowledge: {findings: {supported: 30, accepted: 10, unsupported: 2, uncertain: 1, unreviewed: 4}, pendingReviews: 2, notes: 50},
    reuse: {answered: 12, citingReviewed: 3}});
  assert.deepEqual(summary.stages.map(s => [s.key, s.value]), [['ask', 12], ['deposit', 47], ['review', 33], ['reuse', 3]]);
  assert.match(summary.stages[1].text, /10 added on the research agent's judgement/);
  assert.match(summary.stages[2].text, /2 answers waiting/);
  assert.equal(summary.headline, '40 findings are available to every new question (30 reviewed, 10 added).');
  const empty = ui.knowledgeSummary({});
  assert.deepEqual(empty.stages.map(s => s.value), [null, 0, 0, null]);
  assert.match(empty.headline, /Nothing saved yet/);
  assert.equal(ui.formatCount(null), '—');
});

test('repeat-unit brackets are placed from the molfile and face the repeat unit', () => {
  const parsed = ui.parseMolfile(PCL);
  assert.equal(parsed.atoms.length, 10);
  assert.equal(parsed.atoms[0].element, '*');
  assert.deepEqual(parsed.sgroups[0].atoms, [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.equal(parsed.sgroups[0].label, 'n');
  assert.equal(parsed.sgroups[0].brackets.length, 2);
  const pixels = parsed.atoms.map(a => ({x: 16 * a.x + 150, y: -16 * a.y + 118}));
  const transform = ui.fitTransform(parsed.atoms, pixels);
  assert.ok(Math.abs(transform.s - 16) < 1e-9 && Math.abs(transform.tx - 150) < 1e-9 && Math.abs(transform.ty - 118) < 1e-9);
  const geometry = ui.bracketGeometry(parsed.sgroups[0], parsed.atoms, transform);
  const [left, right] = geometry.brackets;
  assert.ok(left[0][0] > left[1][0], 'left bracket serif points right, into the repeat unit');
  assert.ok(right[0][0] < right[1][0], 'right bracket serif points left, into the repeat unit');
  assert.equal(geometry.label.text, 'n');
  assert.ok(geometry.label.x > right[1][0]);
});

test('bracket placement is skipped when drawn atoms do not match the molfile', () => {
  const parsed = ui.parseMolfile(PCL);
  const pixels = parsed.atoms.map((a, i) => ({x: 16 * a.x + (i === 3 ? 40 : 0), y: -16 * a.y}));
  assert.equal(ui.fitTransform(parsed.atoms, pixels), null);
  assert.equal(ui.bracketGeometry(parsed.sgroups[0], parsed.atoms, null), null);
});

test('drawings are cropped to content with a minimum size', () => {
  assert.equal(ui.croppedViewBox([[100, 100], [300, 140]], {width: 420, height: 240, pad: 10}), '90.0 75.0 220.0 90.0');
  assert.equal(ui.croppedViewBox([], {width: 420, height: 240}), '0 0 420 240');
});

test('researcher app is offline, and the developer page stays unlinked from it', () => {
  const index = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const operator = fs.readFileSync(path.join(web, 'operator.html'), 'utf8');
  for (const html of [index, operator]) {
    assert.doesNotMatch(html, /<script[^>]+src=["']https?:/);
    assert.doesNotMatch(html, /<link[^>]+href=["']https?:/);
  }
  assert.match(index, /src="\/researcher\.js"/);
  assert.match(operator, /src="\/app\.js"/);
  for (const source of [index, fs.readFileSync(path.join(web, 'researcher.js'), 'utf8')]) assert.doesNotMatch(source, /operator/);
  assert.ok(fs.statSync(path.join(web, 'vendor/openchemlib.js')).size > 500000);
  assert.match(fs.readFileSync(path.join(web, 'vendor/openchemlib.LICENSE'), 'utf8'), /Redistribution and use in source and binary forms/);
});

test('live progress shows the stage, clock, budget and sites', () => {
  const live = ui.progressDetail({budgetSeconds: 600, depth: 'standard', progress: {phase: 'research', elapsedSeconds: 75, budgetSeconds: 600,
    graph: {searches: 2, records: 3, hops: 1, knowledge: 1, vocabulary: 0, recipes: 0}, web: {searches: 1, pages: 4, unclassified: 1},
    sourcesOpened: 2, sites: ['example.org'], turns: 6, lastAction: 'Reading example.org'}});
  assert.equal(live.stage, 'web');
  assert.deepEqual(live.stages.map(s => [s.key, s.state]), [['knowledge', 'done'], ['web', 'current'], ['writing', 'pending']]);
  assert.deepEqual(live.counts, {knowledge: 1, lookups: 5, hops: 1, searches: 2, pages: 4, sources: 2});
  assert.deepEqual([live.clock, live.limit, live.percent], ['1:15', '10 min', 13]);
  assert.deepEqual([live.budget.searches, live.budget.sources, live.depth], [10, 8, 'Standard']);
  assert.equal(ui.progressDetail({progress: {web: {pages: 3}}}).counts.sources, 3);  // Older progress: pages stand in.
  assert.deepEqual(live.sites, ['example.org']);
  assert.equal(ui.progressDetail({progress: {lastAction: 'Writing the answer'}}).stage, 'writing');
  assert.equal(ui.progressDetail({progress: {lastAction: 'Checking local knowledge for “x”'}}).stage, 'knowledge');
  assert.equal(ui.progressDetail({}), null);
  assert.equal(ui.formatClock(3725), '62:05');
});

test('the running clock advances between worker events without changing the record', () => {
  const start = Date.parse('2026-09-27T16:00:00Z');
  const task = {status: 'running', progress: {startedAt: new Date(start).toISOString(), elapsedSeconds: 0, budgetSeconds: 600}};
  const original = JSON.stringify(task);
  assert.equal(ui.progressDetail(task, start + 180000).clock, '3:00');
  assert.equal(ui.progressDetail(task, start + 180000).percent, 30);
  assert.equal(JSON.stringify(task), original);
  assert.equal(ui.progressDetail({...task, status: 'completed'}, start + 180000).clock, '0:00');
  assert.equal(ui.progressDetail({...task, progress: {...task.progress, startedAt: 'invalid', elapsedSeconds: 120}}, start + 180000).clock, '2:00');
});

test('effort counts are summed when known and omitted when missing', () => {
  const stats = ui.effortStats({graphLookups: 3, knowledgeLookups: 1, webSearches: 0, pagesRead: 2, inputTokens: 1000, outputTokens: 20, graphHops: null});
  assert.deepEqual(stats.map(s => [s.label, s.value]),
    [['knowledge lookups', 1], ['ontology lookups', 3], ['web searches', 0], ['pages read', 2], ['tokens', 1020]]);
  assert.deepEqual(ui.effortStats({knowledgeLookups: 2, graphLookups: 0}).map(s => s.label), ['knowledge lookups']);
  assert.deepEqual(ui.effortStats({webSearches: 1, pagesRead: 0, unclassifiedWebCalls: 3}).map(s => s.label),
    ['web searches', 'pages read', 'web calls (type not reported)']);
  assert.deepEqual(ui.effortStats(null), []);
});


test('an answer with findings waiting for review keeps polling until they are reviewed', () => {
  const task = {result: {}, deposit: {findings: 2, counts: {accepted: 2}, reviewStatus: 'pending', waitingReview: 1}};
  assert.equal(ui.reviewPending(task), true);
  assert.equal(ui.provenanceSummary(task).label, '1 finding waiting for review');
  task.deposit.waitingReview = 0;
  assert.equal(ui.reviewPending(task), false);
});

test('an answer shows its findings being saved after it, or why they were not saved', () => {
  const saving = {result: {}, depositState: {status: 'saving'}, reusedFindings: {supported: 1}};
  assert.deepEqual([ui.provenanceSummary(saving).label, ui.provenanceSummary(saving).tone], ['Saving findings…', 'neutral']);
  assert.match(ui.provenanceSummary(saving).note, /The answer is ready.*reused 1 saved finding\./);
  assert.equal(ui.savingFindings(saving), true);  // Keeps polling until they are saved.
  const failed = {result: {}, depositState: {status: 'failed', reason: 'timeout', message: 'Stopped at the 300-second limit'}};
  // The reason in plain words, as other failures are, never the raw code.
  assert.deepEqual([ui.provenanceSummary(failed).label, ui.provenanceSummary(failed).tone], ['Findings not saved: out of time', 'warn']);
  assert.match(ui.provenanceSummary(failed).note, /The answer stands, .*not saved: writing them reached its time limit\./);
  assert.equal(ui.savingFindings(failed), false);
  const stopped = ui.provenanceSummary({result: {}, depositState: {status: 'failed', reason: 'interrupted'}});
  assert.equal(stopped.label, 'Findings not saved: app stopped');
  assert.doesNotMatch(ui.provenanceSummary({result: {}, depositState: {status: 'failed', reason: 'new-reason'}}).label, /new-reason/);
  // Once saved, the deposit is described as before.
  const saved = {result: {}, depositState: {status: 'saved'}, deposit: {findings: 3, reviewStatus: 'nothing-to-review', counts: {accepted: 3}}};
  assert.equal(ui.provenanceSummary(saved).label, 'Findings added');
  assert.equal(ui.savingFindings(saved), false);
});

test('an answer is redrawn only when its saved findings or their review change', () => {
  const saving = {result: {}, status: 'completed', depositState: {status: 'saving'}, effort: {seconds: 30}};
  assert.equal(ui.depositKey(saving), ui.depositKey({...saving, effort: {seconds: 31}}));  // Unrelated detail: no redraw.
  const saved = {...saving, depositState: {status: 'saved'}, deposit: {findings: 2, waitingReview: 1, counts: {accepted: 2}}};
  assert.notEqual(ui.depositKey(saving), ui.depositKey(saved));
  assert.notEqual(ui.depositKey(saved), ui.depositKey({...saved, deposit: {...saved.deposit, waitingReview: 0}}));
});

test('exhausted reviews stop polling and retain the failure explanation', () => {
  const task = {result: {}, deposit: {findings: 1, counts: {unreviewed: 1}, reviewStatus: 'failed', reviewAttempts: 2}};
  assert.equal(ui.reviewPending(task), false);
  assert.equal(ui.provenanceSummary(task).label, 'Review did not finish');
  assert.match(ui.provenanceSummary(task).note, /No automatic retries remain/);
});
