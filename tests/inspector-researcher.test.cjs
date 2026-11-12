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

test('TeX in answers reads as math, inline and on its own line', () => {
  // Relations and binary signs are set off by four-per-em spaces; read them as plain spaces here.
  const math = tex => ui.renderMath(tex).replace(/\u2005/g, ' ');
  const html = ui.renderMarkdown('The Flory–Fox relation is\n\\[\nT_g=T_{g,\\infty}-\\frac{K}{M_n},\n\\]\n`finding:a-1`\nwhere \\(M_n\\) is in \\(\\mathrm{g\\,mol^{-1}}\\).\n\n$$\\Delta H_m=w\\,\\Delta H_m^0$$').replace(/\u2005/g, ' ');
  assert.equal(html.split('<div class="math math-display">').length, 3);
  assert.match(html, /^<p>The Flory–Fox relation is<\/p><div class="math math-display"><i>T<\/i><sub><i>g<\/i><\/sub> = <i>T<\/i><sub><i>g<\/i>,∞<\/sub> − <span class="math-frac"><span><i>K<\/i><\/span><span class="visually-hidden">\/<\/span><span><i>M<\/i><sub><i>n<\/i><\/sub><\/span><\/span>,<\/div><p><code>finding:a-1<\/code><br>where /);
  assert.match(html, /where <span class="math"><i>M<\/i><sub><i>n<\/i><\/sub><\/span> is in <span class="math">g\u2009mol<sup>−1<\/sup><\/span>\.<\/p>/);
  assert.match(html, /Δ<i>H<\/i><sub><i>m<\/i><\/sub> = <i>w<\/i>\u2009Δ<i>H<\/i><sub><i>m<\/i><\/sub><sup>0<\/sup><\/div>$/);
  assert.doesNotMatch(html, /\\/);
  // Greek, \times, scripts, a unary minus, function names, accents and spacing commands.
  assert.equal(math('K=7.7\\times10^{4}\\ \\mathrm{cm^2}'), '<i>K</i> = 7.7 × 10<sup>4</sup>\u00a0cm<sup>2</sup>');
  assert.equal(math('A=-\\log_{10}T'), '<i>A</i> = −log<sub>10</sub>\u2009<i>T</i>');
  assert.equal(math('\\dot V_{\\mathrm{STP}}\\,l,\\qquad \\alpha\\beta'), '<i>V\u0307</i><sub>STP</sub>\u2009<i>l</i>,\u2003\u2003αβ');
  assert.equal(math('\\left(\\frac{dp}{dt}\\right)\\sqrt{x}'), '(<span class="math-frac"><span><i>dp</i></span><span class="visually-hidden">/</span><span><i>dt</i></span></span>)√<span class="math-sqrt"><i>x</i></span>');
  // An unknown command stays as written; code spans and an unclosed display stay as text, and a lone table row no longer stalls the renderer.
  assert.equal(ui.renderMath('\\mathcal{L}'), '\\mathcal<i>L</i>');
  assert.equal(ui.renderInline('`\\(x\\)`'), '<code>\\(x\\)</code>');
  assert.equal(ui.renderMarkdown('\\[x\n\nnext'), '<p>\\[x</p><p>next</p>');
  assert.equal(ui.renderMarkdown('\\[x\\] then text'), '<div class="math math-display"><i>x</i></div><p> then text</p>');
  assert.equal(ui.renderMarkdown('a\n| x |\nb'), '<p>a</p><p>| x |<br>b</p>');
});

test('math keeps every literal piece escaped and makes only its own tags', () => {
  const allowed = /^<\/?(?:p|br|div|span|i|b|sub|sup)(?: class="(?:math|math math-display|math-frac|math-sqrt|math-over|visually-hidden)")?>$/;
  for (const source of ['\\(<img src=x onerror=alert(1)>\\)', '\\(\\text{<script>alert(1)</script>}\\)', '\\[\\href{javascript:alert(1)}{x}\\]',
    '$$\\mathrm{"><svg onload=alert(1)>}$$', '\\(\\sqrt[<b onclick=x>]{a & b}\\)', '\\(\\frac{[x](https://example.org)}{\'}\\)']) {
    const html = ui.renderMarkdown(source);
    for (const tag of html.match(/<[^>]*>/g)) assert.match(tag, allowed, `${source} → ${html}`);
  }
  assert.equal(ui.renderMath('a<b&c'), '<i>a</i>\u2005&lt;\u2005<i>b</i>&amp;<i>c</i>');
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

test('an answer says what it saved from the moment it is shown, saving first', () => {
  assert.equal(ui.savedSummary({}), null);
  const saving = ui.savedSummary({result: {}, depositState: {status: 'saving'}});
  assert.deepEqual([saving.headline, saving.busy], ['Saving what this answer read…', true]);
  assert.match(saving.detail, /will appear here once saved/);
  const failed = ui.savedSummary({result: {}, depositState: {status: 'failed', reason: 'quota'}});
  assert.deepEqual([failed.headline, failed.tone], ['Findings not saved: usage limit reached', 'warn']);
  const none = ui.savedSummary({result: {}, depositState: {status: 'saved'}, deposit: {findings: 0, notes: 2, duplicates: 3, counts: {}}});
  assert.equal(none.headline, 'Nothing new to save');
  assert.match(none.detail, /3 facts it read were already in the knowledge base/);
  assert.match(none.detail, /a note on each of the 2 sources it read/);
  const reviewing = ui.savedSummary({result: {}, depositState: {status: 'saved'},
    deposit: {findings: 12, notes: 6, reviewStatus: 'pending', waitingReview: 5, counts: {accepted: 9, unreviewed: 3}},
    findings: [{status: 'accepted', spotCheck: 'pending'}, {status: 'accepted', spotCheck: 'pending'}, {status: 'accepted'}]},
    [{findings: [1, 2]}, {findings: [3]}, {findings: []}, {findings: []}]);
  assert.deepEqual([reviewing.headline, reviewing.review, reviewing.busy], ['12 findings saved from 2 sources', '5 findings waiting for review', true]);
  assert.match(reviewing.detail, /Nothing was saved from 2 other sources it read; their notes say why\.$/);
  assert.match(reviewing.detail, /^9 added on the research agent's reading of the source; 3 waiting for a separate reviewer/);
  assert.match(reviewing.detail, /spot-checking 2 of the added ones\./);
  const done = ui.savedSummary({result: {}, deposit: {findings: 3, reviewStatus: 'reviewed', counts: {accepted: 1, supported: 1, unsupported: 1}}}, [{findings: [1, 2, 3]}]);
  assert.deepEqual([done.headline, done.review, done.busy], ['3 findings saved from 1 source', '', false]);
  assert.match(done.detail, /2 checked by a separate reviewer: 1 confirmed, 1 rejected\./);
  const stalled = ui.savedSummary({result: {}, deposit: {findings: 1, reviewStatus: 'failed', reviewAttempts: 2, waitingReview: 0, counts: {unreviewed: 1}}});
  assert.deepEqual([stalled.review, stalled.tone], ['Review did not finish', 'warn']);
  assert.match(stalled.detail, /no automatic retries remain/);
});

test('saved findings are grouped under the source they were read in', () => {
  assert.equal(ui.sourceKey('https://doi.org/10.1/ABC', ''), 'doi:10.1/abc');
  assert.equal(ui.sourceKey('', 'https://dx.doi.org/10.1/abc'), 'doi:10.1/abc');
  assert.equal(ui.sourceKey('', 'https://www.Example.org/paper/?x=1#t'), 'url:example.org/paper');
  assert.equal(ui.sourceKey('', ''), '');
  // A parameter that names the document stays (CL-23); one that only changes the view does not.
  const sheet = name => `https://www.ensinger-online.com/modules/public/sheet/createsheet.php?FILENAME=${name}&FL=0&ZOOM=1.2`;
  assert.equal(ui.sourceKey('', sheet('TECAFINE_PMP.PDF')), 'url:ensinger-online.com/modules/public/sheet/createsheet.php?filename=tecafine_pmp.pdf');
  assert.notEqual(ui.sourceKey('', sheet('TECAFINE_PMP.PDF')), ui.sourceKey('', sheet('TECASON_S.PDF')));
  assert.equal(ui.sourceKey('', 'https://www.centralsteelfab.com/download.asp?name=&path=/assets/ISS888CL+Datasheet.pdf'),
    'url:centralsteelfab.com/download.asp?path=/assets/iss888cl datasheet.pdf');
  assert.equal(ui.sourceKey('', 'https://example.org/a/data-sheet/?lang=en&v=3'), 'url:example.org/a/data-sheet');
  const groups = ui.savedBySource(
    [{id: 'f1', source: {title: 'A', url: 'https://example.org/a'}}, {id: 'f2', source: {doi: '10.1/b', url: 'https://doi.org/10.1/b'}},
     {id: 'f3', source: {url: 'https://example.org/a/'}}],
    [{title: 'Unopened', url: 'https://example.org/c', supports: 'Could not be opened (HTTP 404).'},
     {title: 'B', doi: '10.1/B', url: 'https://pubs.example/b', readUrl: 'https://pmc.example/b', supports: 'Table 1'}]);
  assert.deepEqual(groups.map(g => [g.key, g.findings.map(f => f.id), g.notes.length]),
    [['url:example.org/a', ['f1', 'f3'], 0], ['doi:10.1/b', ['f2'], 1], ['url:example.org/c', [], 1]]);
  assert.deepEqual([groups[1].title, groups[1].readUrl], ['B', 'https://pmc.example/b']);
});

test('a question and its follow-ups are one conversation, dated by its latest question', () => {
  const tasks = [  // Newest first, as the task list gives them.
    {taskId: 'c', threadId: 'a', parentId: 'b', question: 'Third?', submittedAt: '2026-10-30T03:00:00Z'},
    {taskId: 'x', question: 'On its own?', submittedAt: '2026-10-30T02:30:00Z'},
    {taskId: 'b', threadId: 'a', parentId: 'a', question: 'Second?', submittedAt: '2026-10-30T02:00:00Z'},
    {taskId: 'a', threadId: 'a', question: 'First?', submittedAt: '2026-10-30T01:00:00Z'}];
  const groups = ui.conversations(tasks);
  assert.deepEqual(groups.map(g => [g.first.taskId, g.latest.taskId, g.count, g.ids]),
    [['a', 'c', 3, ['a', 'b', 'c']], ['x', 'x', 1, ['x']]]);
  assert.deepEqual(ui.conversations([]), []);
  // Follow-ups are ordered by what they follow, not by their clocks.
  const skewed = ui.conversations([{taskId: 'a', threadId: 'a', submittedAt: '2026-10-30T01:00:00Z'},
    {taskId: 'b', threadId: 'a', parentId: 'a', submittedAt: '2026-10-30T09:00:00Z'},
    {taskId: 'c', threadId: 'a', parentId: 'b', submittedAt: '2026-10-30T05:00:00Z'}]);
  assert.deepEqual([skewed[0].ids, skewed[0].latest.taskId], [['a', 'b', 'c'], 'c']);
});

test('a follow-up can be asked once the latest answer is ready, and waits for its findings', () => {
  assert.equal(ui.followGate(null), null);
  assert.equal(ui.followGate({status: 'failed'}), null);
  assert.deepEqual(ui.followGate({status: 'running'}), {ready: false, message: 'You can ask a follow-up once this answer is ready.'});
  assert.match(ui.followGate({status: 'completed', depositState: {status: 'saving'}}).note, /starts once this answer's findings are saved and checked/);
  assert.equal(ui.followGate({status: 'completed', deposit: {waitingReview: 2}}).ready, true);
  assert.deepEqual(ui.followGate({status: 'completed', deposit: {waitingReview: 0}}), {ready: true, note: ''});
});

test('a question outside the scope says what it asks about and links to another assistant', () => {
  const declined = {status: 'completed', question: 'A banana bread recipe?', outOfScope: 'It asks for a <b>recipe</b>.',
                    redirectUrl: 'https://chatgpt.com/'};
  assert.deepEqual(ui.taskState(declined), {label: 'Outside scope', tone: 'neutral', busy: false});
  assert.equal(ui.followGate(declined), null);  // Nothing to follow up on its own,
  assert.equal(ui.followGate({...declined, parentId: 'a'}).ready, true);  // but a conversation can go on.
  const notice = ui.scopeNotice(declined);
  assert.match(notice, /Outside this assistant’s scope, so it was not researched\.<\/strong> It asks for a &lt;b&gt;recipe&lt;\/b&gt;\./);
  assert.match(notice, /<a class="primary-button" href="https:\/\/chatgpt\.com\/" target="_blank" rel="noopener noreferrer">Ask it at chatgpt\.com ↗<\/a>/);
  assert.match(ui.scopeNotice({...declined, redirectUrl: 'https://www.example.org/other'}), />Ask it at example\.org ↗</);
  assert.doesNotMatch(ui.scopeNotice({...declined, redirectUrl: 'javascript:alert(1)'}), /<a /);
  assert.equal(ui.savedTag(declined), '');
});

test('an answer outside the scope stands but says its findings were not saved', () => {
  const aside = {status: 'completed', result: {answer: 'Graphite anodes reach about 372 mAh/g.'},
                 depositState: {status: 'skipped', reason: 'outside-scope', message: 'It asks about <b>graphite</b> anodes'}};
  assert.deepEqual(ui.taskState(aside), {label: 'Answered', tone: 'good', busy: false});
  assert.equal(ui.provenanceSummary(aside).label, 'Outside scope: not saved');
  const saved = ui.savedSummary(aside);
  assert.equal(saved.headline, 'Not saved: outside this assistant’s scope');
  assert.match(saved.detail, /^It asks about <b>graphite<\/b> anodes\. The question is outside this assistant’s scope, so it was answered but its findings were not saved/);
  assert.equal(ui.savedTag(aside), 'Outside scope · not saved');
  assert.deepEqual(ui.followGate(aside), {ready: true, note: ''});  // A conversation can go on from it.
});

test('an answer says when findings behind it were rejected after it was written', () => {
  assert.equal(ui.rejectedNotice(0, 0), '');
  assert.equal(ui.rejectedNotice(0, 1), '1 saved finding this answer cites was rejected after it was written, so a value it reports may be wrong. Check those before relying on it.');
  assert.match(ui.rejectedNotice(2, 0), /^2 of the findings it saved were rejected on review, so/);
  assert.match(ui.rejectedNotice(1, 2), /^2 saved findings this answer cites were rejected .*; and 1 of the findings it saved was rejected on review/);
  // A conversation's answers number their sources apart.
  assert.match(ui.renderInline('PLA `finding:a-1`', {cite: () => 3, prefix: 't2-'}), /href="#source-t2-3" data-source="t2-3">\[3\]/);
  assert.match(ui.renderInline('PLA `finding:a-1`', {cite: () => 3}), /href="#source-3" data-source="3"/);
});

test('history rows say what each answer saved', () => {
  assert.equal(ui.savedTag({depositState: {status: 'saving'}}), 'Saving findings');
  assert.equal(ui.savedTag({depositState: {status: 'failed'}}), 'Findings not saved');
  assert.equal(ui.savedTag({deposit: {findings: 12, waitingReview: 3}}), '12 findings saved · review pending');
  assert.equal(ui.savedTag({deposit: {findings: 1, waitingReview: 0}}), '1 finding saved');
  assert.equal(ui.savedTag({deposit: {findings: 0}}), '');
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
  assert.deepEqual(ui.taskState({status: 'running'}), {label: 'Reading the question…', tone: 'neutral', busy: true});
  assert.equal(ui.taskState({status: 'running', progress: {lastAction: 'Reading the question'}}).label, 'Reading the question…');
  assert.equal(ui.taskState({status: 'running', progress: {graph: {knowledge: 1}, lastAction: 'Checking local knowledge for “x”'}}).label, 'Researching…');
  assert.equal(ui.taskState({status: 'running', progress: {waiting: true, lastAction: 'Waiting for its turn'}}).label, 'Researching…');
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
  assert.equal(ui.progressDetail({progress: {lastAction: 'Writing the answer', graph: {knowledge: 1}}}).stage, 'writing');
  assert.equal(ui.progressDetail({progress: {lastAction: 'Checking local knowledge for “x”'}}).stage, 'knowledge');
  // Until its first search, a session is reading the question: one declined as outside the scope never looks researched.
  for (const lastAction of ['Reading the question', 'Writing the answer']) {
    const reading = ui.progressDetail({progress: {lastAction, elapsedSeconds: 4, budgetSeconds: 300}});
    assert.equal(reading.stage, 'question');
    assert.deepEqual(reading.stages.map(s => s.state), ['pending', 'pending', 'pending']);
  }
  assert.equal(ui.progressDetail({}), null);
  assert.equal(ui.formatClock(3725), '62:05');
});

test('a question waiting for its engine shows why, with no clock or progress yet', () => {
  const live = ui.progressDetail({status: 'running', budgetSeconds: 600, depth: 'standard',
    progress: {waiting: true, startedAt: null, elapsedSeconds: 0, budgetSeconds: 600, lastAction: "Waiting for the last answer's findings to be saved"}},
    Date.parse('2026-09-27T16:00:00Z'));
  assert.deepEqual([live.waiting, live.clock, live.percent, live.limit], [true, '0:00', 0, '10 min']);
  assert.equal(live.action, "Waiting for the last answer's findings to be saved");
  assert.equal(ui.progressDetail({progress: {lastAction: 'Reading example.org'}}).waiting, false);
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

test('an answer whose values a reviewer is still comparing with saved ones keeps polling, then says what it found', () => {
  const task = {result: {}, depositState: {status: 'saved'}, deposit: {findings: 2, counts: {accepted: 2}, reviewStatus: 'nothing-to-review', waitingReview: 0,
    consistency: {state: 'tension', compared: 0, conflicts: 0, open: 0, waiting: true}}};
  assert.equal(ui.reviewPending(task), true);
  assert.equal(ui.provenanceSummary(task).label, 'Being compared with saved findings');
  assert.equal(ui.savedSummary(task).busy, true);
  assert.equal(ui.savedSummary(task).review, 'Being compared with saved findings');
  assert.match(ui.followGate(task).note, /starts once/);
  task.deposit.consistency = {state: 'checked', compared: 6, conflicts: 1, open: 1, waiting: false};
  assert.equal(ui.reviewPending(task), false);
  assert.match(ui.savedSummary(task).detail, /compared them with 6 related saved findings and found 1 conflict\. One waits for you/);
  task.deposit.consistency = {state: 'tension', compared: 0, conflicts: 0, open: 0, waiting: false};  // Its attempts used up.
  assert.equal(ui.reviewPending(task), false);
});

test('a finding a person rejected is never said to be a reviewer\'s rejection', () => {
  const finding = {status: 'unsupported', review: {engine: 'person', reason: 'A person judged that it conflicts.'}};
  assert.match(ui.recordStatus(finding).note, /A person rejected/);
  assert.match(ui.recordStatus({status: 'unsupported', review: {engine: 'codex'}}).note, /reviewer found/);
  const task = {result: {}, deposit: {findings: 3, reviewStatus: 'reviewed', rejectedByPerson: 1, counts: {accepted: 1, supported: 1, unsupported: 2}}};
  const detail = ui.savedSummary(task, [{findings: [1, 2, 3]}]).detail;
  assert.match(detail, /2 checked by a separate reviewer: 1 confirmed, 1 rejected/);
  assert.match(detail, /1 rejected by a person after a reviewer found it conflicts/);
  assert.match(ui.provenanceSummary(task).note, /a person rejected 1/);
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
