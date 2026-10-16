const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('../oopc/web/app.js');



test('A/B grade means keep incomplete comparisons visibly incomplete', () => {
  const html=ui.renderPairedGrades({measuredPairs:1,expectedPairs:12,completeComparison:false,
    scores:{supportedCorrectness:{baseline:.5,candidate:.75}}});
  assert.match(html,/1 \/ 12 matched pairs/);
  assert.match(html,/Partial observations; no complete comparison/);
  assert.match(html,/5.5 \/ 10 → 7.8 \/ 10/);
  assert.doesNotMatch(html,/demonstrated improvement/);
  assert.equal(ui.renderPairedGrades({scores:{}}),'');
});

test('graded partial success remains visible separately from a strict failure', () => {
  const evaluation={qualification:'source-checked',verdict:'fail',scores:{supportedCorrectness:1,
    qualificationScore:0.5,citationEntailment:0,taskCompletionScore:2/3,fullResearchCoverage:1/3}};
  assert.equal(ui.evaluationLabel({evaluation}),'Supported correctness: 10.0 / 10 (claim count unavailable) · Feasible completion: 7.0 / 10 · Full coverage: 4.0 / 10 · strict gate: fail');
  const html=ui.renderOutcomeSummary({inspectorSummary:{evaluation}});
  assert.match(html,/Material and test qualifications<\/dt><dd>5.5 \/ 10/);
  assert.match(html,/Citation support<\/dt><dd>1.0 \/ 10/);
  assert.match(html,/Feasible task completion<\/dt><dd>7.0 \/ 10/);
  assert.match(html,/Full research coverage<\/dt><dd>4.0 \/ 10/);
  assert.match(html,/not the binary gate/);
  assert.match(html,/strict gate can fail despite partial success/);
});

test('zero claim and support denominators cannot headline a perfect success grade', () => {
  const raw={independentlySourceChecked:true,completeAnswerCoverage:true,reviewVerdict:'fail',
    supportedCorrectness:1,citationEntailment:1,taskCompletionScore:2/3,fullResearchCoverage:0,
    supportLinks:0,answerClaimAssessments:[{claimId:'gap',kind:'abstention',verdict:'pass',citations:[]},
      {claimId:'attribution',kind:'corpus-attribution',verdict:'pass',citations:[{evidenceId:'source',role:'corpus-attribution'}]}]};
  const original=structuredClone(raw), evaluation=ui.reviewEvaluation(raw);
  assert.deepEqual(evaluation.assessmentCounts,{scientificClaims:0,scientificSupportLinks:0});
  const label=ui.evaluationLabel({evaluation}), html=ui.renderOutcomeSummary({inspectorSummary:{evaluation}});
  assert.match(label,/No scientific claims assessed/);
  assert.match(label,/No scientific-support citations assessed/);
  assert.match(label,/Feasible completion: 7.0 \/ 10 · Full coverage: 1.0 \/ 10/);
  assert.doesNotMatch(label,/10\.0 \/ 10/);
  assert.match(html,/Supported correctness<\/dt><dd>No scientific claims assessed/);
  assert.match(html,/Citation support<\/dt><dd>No scientific-support citations assessed/);
  assert.match(html,/recorded arithmetic 10\.0 \/ 10/);
  assert.match(html,/not an assessed success grade/);
  assert.match(html,/Recorded scores and strict decisions are unchanged/);
  assert.deepEqual(raw,original);
});

test('positive claim counts retain grades and count repeated support links individually', () => {
  const raw={independentlySourceChecked:true,completeAnswerCoverage:true,reviewVerdict:'fail',supportedCorrectness:.5,citationEntailment:.5,
    supportLinks:2,answerClaimAssessments:['one','two'].map(claimId=>({claimId,kind:'scientific-claim',verdict:'uncertain',citations:[{evidenceId:'same',role:'support'}]}))};
  const evaluation=ui.reviewEvaluation(raw);
  assert.deepEqual(evaluation.assessmentCounts,{scientificClaims:2,scientificSupportLinks:2});
  assert.match(ui.evaluationLabel({evaluation}),/Supported correctness: 5\.5 \/ 10 \(2 assessed\)/);
  assert.match(ui.renderOutcomeSummary({inspectorSummary:{evaluation}}),/Citation support<\/dt><dd>5\.5 \/ 10 \(2 assessed\)/);
  raw.supportLinks=0;
  assert.deepEqual(ui.reviewEvaluation(raw).assessmentCounts,{scientificClaims:2,scientificSupportLinks:null});
});

test('missing incomplete or inconsistent denominator evidence stays unknown', () => {
  const claim={claimId:'one',kind:'abstention',verdict:'pass',citations:[]};
  for(const extra of [{},{answerClaimAssessments:[]},{answerClaimAssessments:[claim,claim]},
    {answerClaimAssessments:[{...claim,kind:'unknown'}]},
    {answerClaimAssessments:[claim],completeAnswerCoverage:false},
    {answerClaimAssessments:[claim],independentlySourceChecked:false}]) {
    const evaluation=ui.reviewEvaluation({independentlySourceChecked:true,completeAnswerCoverage:true,supportedCorrectness:1,...extra});
    assert.deepEqual(evaluation.assessmentCounts,{scientificClaims:null,scientificSupportLinks:null});
    assert.doesNotMatch(ui.evaluationLabel({evaluation}),/No scientific/);
  }
  const evaluation={qualification:'source-checked',scores:{supportedCorrectness:1,citationEntailment:1}};
  assert.match(ui.evaluationLabel({evaluation}),/claim count unavailable/);
  assert.match(ui.renderOutcomeSummary({inspectorSummary:{evaluation}}),/assessed count unavailable/);
});

test('invalid or unqualified numbers cannot receive a grade', () => {
  for(const value of [true,NaN,Infinity,-0.1,1.1,'0.8']) {
    const evaluation={qualification:'source-checked',verdict:'fail',scores:{supportedCorrectness:value}};
    assert.doesNotMatch(ui.evaluationLabel({evaluation}),/\/ 10/);
    assert.doesNotMatch(ui.renderOutcomeSummary({inspectorSummary:{evaluation}}),/\/ 10/);
  }
  const evaluation={qualification:'unscorable',scores:{supportedCorrectness:1}};
  assert.equal(ui.evaluationLabel({evaluation}),'Task evaluation: unscorable');
  assert.doesNotMatch(ui.renderOutcomeSummary({inspectorSummary:{evaluation}}),/\/ 10/);
});

test('benchmark review coverage renders recorded reference outcomes and mapped answer claims', () => {
  const review={evaluation:{independentlySourceChecked:true,taskCoverageChecks:{
    'reference-1':{outcome:'supported-answer',answerClaimIds:['a1','a9'],rationale:'Source-qualified route established.'},
    'reference-2':{outcome:'correctly-scoped-abstention',answerClaimIds:['a4'],rationale:'Required values absent from the allowed corpus.'},
    'reference-3':{outcome:'missed-available-evidence',answerClaimIds:[],rationale:'An available result was omitted.'}}}};
  const before=structuredClone(review), html=ui.renderReviewCoverage(review);
  assert.match(html,/<h4>Task coverage<\/h4>/);
  assert.match(html,/supported answer/);
  assert.match(html,/correctly scoped abstention/);
  assert.match(html,/missed available evidence/);
  assert.match(html,/reference-1/);
  assert.match(html,/Mapped answer claims: a1, a9/);
  assert.match(html,/Mapped answer claims: None recorded/);
  assert.match(html,/Required values absent from the allowed corpus/);
  assert.doesNotMatch(html,/did not record|unscorable|\/ 10/);
  assert.deepEqual(review,before);
});

test('ordinary task criteria retain priority and their recorded verdicts', () => {
  const html=ui.renderReviewCoverage({taskCriteria:[{criterionId:'criterion-1',verdict:'uncertain',rationale:'The comparison remains incomplete.'}],
    evaluation:{taskCoverageChecks:{'reference-unused':{outcome:'supported-answer'}}}});
  assert.match(html,/class="badge uncertain">uncertain/);
  assert.match(html,/criterion-1/);
  assert.match(html,/The comparison remains incomplete/);
  assert.doesNotMatch(html,/reference-unused|Mapped answer claims|unscorable|\/ 10/);
});

test('coverage fallback only claims missing judgments when neither representation has entries', () => {
  for(const review of [{},{taskCriteria:[]},{evaluation:{}},{evaluation:{taskCoverageChecks:{}}},
    {evaluation:{taskCoverageChecks:[]}},{evaluation:{taskCoverageChecks:{bad:null}}}]) {
    const html=ui.renderReviewCoverage(review);
    assert.match(html,/did not record separate task-coverage judgments/);
    assert.doesNotMatch(html,/<h4>Task coverage|\/ 10/);
  }
});

test('coverage judgments preserve an unscorable evaluation without generating grades', () => {
  const raw={independentlySourceChecked:false,reviewVerdict:'pass',supportedCorrectness:1,
    taskCoverageChecks:{'reference-1':{outcome:'supported-answer',answerClaimIds:['a1'],rationale:'Reviewer-reported outcome.'}}};
  const before=structuredClone(raw), html=ui.renderReviewCoverage({evaluation:raw});
  assert.match(html,/this evaluation is unscorable/);
  assert.match(html,/do not establish a qualified score/);
  assert.match(html,/supported answer/);
  assert.doesNotMatch(html,/\/ 10/);
  assert.equal(ui.evaluationLabel({evaluation:ui.reviewEvaluation(raw)}),'Task evaluation: unscorable');
  assert.deepEqual(raw,before);
});

test('both coverage representations escape recorded text without creating claim links', () => {
  const benchmark=ui.renderReviewCoverage({evaluation:{independentlySourceChecked:true,taskCoverageChecks:{
    '<reference>':{outcome:'<outcome>',answerClaimIds:['a<script>','"quoted"'],rationale:'<img src=x onerror="bad()"> & text'}}}});
  const ordinary=ui.renderReviewCoverage({taskCriteria:[{criterionId:'<criterion>',verdict:'<verdict>',rationale:'<script>bad()</script>'}]});
  assert.match(benchmark,/&lt;reference&gt;/);
  assert.match(benchmark,/&lt;outcome&gt;/);
  assert.match(benchmark,/a&lt;script&gt;, &quot;quoted&quot;/);
  assert.match(benchmark,/&lt;img src=x onerror=&quot;bad\(\)&quot;&gt; &amp; text/);
  assert.match(ordinary,/&lt;criterion&gt;/);
  assert.match(ordinary,/&lt;verdict&gt;/);
  assert.match(ordinary,/&lt;script&gt;bad\(\)&lt;\/script&gt;/);
  for(const html of [benchmark,ordinary]) assert.doesNotMatch(html,/<script|<img|data-citation|href=/);
});

test('execution completion, overall failure and passing claims are independently labeled', () => {
  const run={status:'completed',inspectorSummary:{evaluation:{qualification:'source-checked',verdict:'fail'},claimFindings:{pass:3,fail:0,uncertain:0}}};
  const html=ui.renderOutcomeSummary(run);
  assert.match(html, /Execution<\/dt><dd>completed/);
  assert.match(html, /Task evaluation: fail/);
  assert.match(html, /3 pass · 0 fail/);
  assert.match(html, /Passing claim findings can coexist with a failed overall task/);
});

test('an unscorable raw pass cannot look like a qualified task pass', () => {
  const summary={evaluation:{qualification:'unscorable',reportedVerdict:'pass'}};
  assert.equal(ui.evaluationLabel(summary),'Task evaluation: unscorable');
  const html=ui.renderOutcomeSummary({status:'completed',inspectorSummary:summary});
  assert.match(html,/Reviewer-reported verdict: pass/);
  assert.doesNotMatch(html,/Task evaluation: pass/);
  assert.match(html,/not a usable task score/);
});

test('verdict-only task reviews identify missing numeric grades without claiming source qualification', () => {
  const summary={evaluation:{qualification:'unqualified-review',reportedVerdict:'uncertain'}};
  assert.equal(ui.evaluationLabel(summary),'Task review: uncertain · numeric grade not recorded');
  const html=ui.renderOutcomeSummary({status:'completed',inspectorSummary:summary});
  assert.match(html,/Evaluation qualification was not recorded/);
  assert.doesNotMatch(html,/qualification unknown|Qualified, independently source-checked|\/ 10/);
});

test('missing evaluation and memory-mode recipe absence remain explicit', () => {
  const summary={retrieval:{returnedRelationships:4,traversedRelationships:0,traversalCalls:1,returnedRecipes:0,deliveredRecipes:0,citedRecipes:0,recipeLookupCalls:2},condition:{mode:'graph-memory'}};
  const html=ui.renderOutcomeSummary({status:'completed',inspectorSummary:summary});
  assert.match(html,/Task evaluation: not recorded/);
  assert.match(html,/No claim findings recorded/);
  assert.match(html,/4 returned · 0 explicitly traversed/);
  assert.match(html,/No recipe was returned/);
  assert.match(html,/Current cohort membership<\/dt><dd>Not established/);
});

test('record-only and disconnected views explain topology without inventing edges', () => {
  assert.match(ui.graphTopologyNote({nodes:[{'@id':'one'}],edges:[]}), /Records only: no relationships/);
  const graph={nodes:[{'@id':'a'},{'@id':'b'},{'@id':'c'}],edges:[{subject:'a',object:'b'}]};
  assert.match(ui.graphTopologyNote(graph),/1 records have no connecting relationship/);
  assert.equal(graph.edges.length,1);
  assert.match(ui.graphTopologyNote({nodes:['a','b','c','d'].map(id=>({'@id':id})),edges:[{subject:'a',object:'b'},{subject:'c',object:'d'}]}),/2 disconnected groups/);
  assert.match(ui.graphTopologyNote({nodes:[{'@id':'partial','@type':'RecordFragment'}],edges:[]}),/partial record projections/);
  assert.equal(ui.graphTopologyNote({nodes:[],edges:[]}), '');
});

test('explicit experiment version is escaped and never presented as current-cohort proof', () => {
  const html=ui.renderOutcomeSummary({inspectorSummary:{condition:{recorded:true,adapterVersion:'<tag>',retrievalProtocol:'v2'}}});
  assert.match(html,/Condition recorded/);
  assert.match(html,/&lt;tag&gt;/);
  assert.doesNotMatch(html,/<tag>/);
  assert.match(html,/Not established by this trace/);
});

const inspectionRun = (disposition='inspected-no-additions', taskComplete=true) => ({
  status:'completed',
  inspectorSummary:{
    evaluation:{qualification:'source-checked',verdict:'pass'},
    publicationInspection:{status:'recorded',disposition,taskComplete,eventId:'inspection-event',
      issues:[],sourceIds:['evidence:assigned'],acceptedClaimIds:disposition==='completed' ? ['claim:accepted'] : []},
  },
});

test('assigned inspection outcome remains distinct from a passing raw task review', () => {
  const run=inspectionRun('unavailable-incomplete',false);
  run.inspectorSummary.claimFindings={pass:1};
  const label=ui.runOutcomeLabel(run), html=ui.renderOutcomeSummary(run);
  assert.match(label,/Assigned paper: inspection incomplete/);
  assert.match(label,/Task evaluation: pass/);
  assert.match(html,/Assigned publication<\/dt>/);
  assert.match(html,/Task review<\/dt>/);
  assert.doesNotMatch(html,/Overall task<\/dt>/);
  assert.match(html,/1 pass · 0 fail/);
  assert.match(html,/inspection, reviewer findings and scientific claim admission are separate/);
});

test('pending, invalid, no-additions and accepted-claim outcomes have distinct labels', () => {
  assert.equal(ui.publicationInspectionLabel({publicationInspection:{status:'pending'}}),'Assigned paper: inspection pending');
  assert.equal(ui.publicationInspectionLabel({publicationInspection:{status:'invalid'}}),'Assigned paper: outcome unavailable');
  assert.equal(ui.publicationInspectionLabel(inspectionRun().inspectorSummary),'Assigned paper: inspected, no new claims');
  assert.equal(ui.publicationInspectionLabel(inspectionRun('completed').inspectorSummary),'Assigned paper: inspected with accepted claims');
  assert.equal(ui.publicationInspectionLabel(inspectionRun('completed',false).inspectorSummary),'Assigned paper: outcome unavailable');
});

test('legacy runs receive no retrospective inspection label or section', () => {
  const before={status:'completed',inspectorSummary:{evaluation:{qualification:'unqualified-review',reportedVerdict:'pass'}}};
  const after={...before,inspectorSummary:{...before.inspectorSummary,publicationInspection:{status:'not-recorded'}}};
  assert.equal(ui.runOutcomeLabel(after),ui.evaluationLabel(before.inspectorSummary));
  assert.equal(ui.renderOutcomeSummary(after),ui.renderOutcomeSummary(before));
  assert.equal(ui.renderPublicationInspection(after,[]),'');
});

test('inspection section keeps source access gaps and the raw receipt collapsed', () => {
  const run=inspectionRun();
  const receipt={disposition:'inspected-no-additions',taskComplete:true,sourceInspectionBasis:'Isolated review only'};
  const artifact={type:'publication_inspection',event_id:'inspection-event',inspection:receipt,
    assignedPublication:{title:'A polymer paper',doi:'10.9999/paper',url:'https://example.org/paper',publication:{'date-parts':[[2026,9,12]]}}};
  const html=ui.renderPublicationInspection(run,[artifact]);
  assert.match(html,/A polymer paper/);
  assert.match(html,/DOI: 10.9999\/paper · 2026-9-12/);
  assert.match(html,/href="https:\/\/example.org\/paper"/);
  assert.match(html,/data-citation="evidence:assigned" data-citation-event="inspection-event"/);
  assert.match(html,/gaps in recorded access/);
  assert.match(html,/does not establish an observed source read or model delivery/);
  assert.match(html,/No accepted claim proposals from the assigned paper/);
  assert.match(html,/<details class="raw-data"><summary>Recorded inspection receipt<\/summary>/);
  assert.doesNotMatch(html,/<details[^>]* open/);
  const event={kind:'artifact',artifact_type:'publication_inspection',agent_id:'coordinator',event_id:'inspection-event',sequence:1,status:'ok',result_ids:[]};
  assert.equal(ui.eventKind(event),'artifact');
  assert.equal(ui.resolveCitationAccess([event],'evidence:assigned','inspection-event'),null);
});

test('inspection issues, metadata, source IDs and receipt content are escaped', () => {
  const run=inspectionRun('unavailable-incomplete',false);
  run.inspectorSummary.publicationInspection.issues=['Missing <table> & figure'];
  run.inspectorSummary.publicationInspection.sourceIds=['evidence:"<source>'];
  const html=ui.renderPublicationInspection(run,[{type:'publication_inspection',event_id:'inspection-event',
    assignedPublication:{title:'<img src=x onerror="bad()">',url:'javascript:bad()'},inspection:{note:'<script>bad()</script>'}}]);
  assert.match(html,/Missing &lt;table&gt; &amp; figure/);
  assert.match(html,/&lt;img src=x onerror=&quot;bad\(\)&quot;&gt;/);
  assert.match(html,/data-citation="evidence:&quot;&lt;source&gt;"/);
  assert.doesNotMatch(html,/<img|<script|href="javascript:/);
});

test('accepted claims are separately linked without implying public release or improvement', () => {
  const html=ui.renderPublicationInspection(inspectionRun('completed'),[]);
  assert.match(html,/Scientific claim admission/);
  assert.match(html,/1 accepted claim proposal from the assigned paper/);
  assert.match(html,/data-citation="claim:accepted"/);
  assert.match(html,/Admission does not establish public release or measured improvement/);
});

test('publication outcome artifacts are excluded from ordinary deliverables and reviews', () => {
  const inspection={type:'publication_inspection',event_id:'inspection-event',findings:[],inspection:{}};
  const answer={event_id:'answer-event',answer:'Digest'}, review={event_id:'review-event',findings:[]};
  const groups=ui.taskArtifactGroups([{kind:'review',event_id:'review-event'}],[inspection,answer,review]);
  assert.deepEqual(groups.inspections,[inspection]);
  assert.deepEqual(groups.deliverables,[answer]);
  assert.deepEqual(groups.reviews,[review]);
});

test('nested prospective specification shows frozen assignment and criteria', () => {
  const specification={question:'Inspect the assigned paper <one>.',deliverable:'A qualified digest.',
    publicationIngestion:{assignedPublication:{title:'Assigned title'},criteria:[{criterionId:'identity',requirement:'Verify the assigned <source>.'}]}};
  const run={task:{specification:{question:'Generic old document question',specification}},inspectorSummary:{publicationInspection:{status:'pending'}}};
  const html=ui.renderTaskSpecification(run);
  assert.match(html,/Inspect the assigned paper &lt;one&gt;/);
  assert.match(html,/A qualified digest/);
  assert.match(html,/Frozen inspection criteria/);
  assert.match(html,/Verify the assigned &lt;source&gt;/);
  assert.doesNotMatch(html,/Generic old document question/);
  assert.match(ui.renderPublicationInspection(run),/Assigned title/);
  assert.match(ui.renderPublicationInspection(run),/No completed inspection receipt/);
});
