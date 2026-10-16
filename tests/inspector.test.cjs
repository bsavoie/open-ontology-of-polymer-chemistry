const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ui = require('../oopc/web/app.js');

const graph = {
  nodes: [{ '@id': 'wop-000001', '@type': 'Polymer', label: 'Material A' }, { '@id': 'source:1', '@type': 'Document', label: 'Evidence' }],
  edges: [{ '@id': 'claim:1', subject: 'wop-000001', predicate: 'hasEvidence', object: 'source:1', status: 'seed' }]
};

test('returned relationships are not falsely rendered as traversals', () => {
  const elements = ui.buildElements(graph, null, { returned: ['claim:1'], traversed: [] });
  const edge = elements.find(e => e.data.record_id === 'claim:1');
  assert.match(edge.classes, /returned/);
  assert.doesNotMatch(edge.classes, /traversed/);
  assert.equal(ui.eventKind({operation: 'search', result_ids: ['claim:1']}), 'returned');
});

test('disconnected results retain their topology and orphan edges are not invented', () => {
  const g = ui.normalizeGraph({ ...graph, nodes: [...graph.nodes, {'@id': 'unrelated'}], edges: [...graph.edges, {'@id': 'orphan', subject: 'absent', object: 'unrelated'}] });
  assert.equal(g.nodes.length, 3);
  assert.equal(g.edges.length, 1);
  assert.equal(ui.buildElements(g).filter(e=>e.data.source || e.data.target).length, 1);
});

test('parallel assertions preserve identity and scope when neighborhoods expand', () => {
  const second = {...graph, edges:[{...graph.edges[0], '@id':'claim:2', context:{temperature:'23 °C'}}]};
  const merged = ui.mergeGraphs(graph, second);
  assert.equal(merged.nodes.length, 2);
  assert.equal(merged.edges.length, 2);
  assert.deepEqual(merged.edges[1].context, {temperature:'23 °C'});
});

test('addressable assertion endpoints preserve all scientific, provenance, and memory edges', () => {
  const assertion={'@id':'claim:measurement','@type':'Claim',label:'Qualified measurement',subject:'material',object:'observation',predicate:'measuredProperty',context:{temperature:'23 °C'}};
  const support={'@id':'claim:support','@type':'Claim',subject:assertion['@id'],object:'evidence',predicate:'supportedBy'};
  const memory={'@id':'claim:recipe','@type':'Claim',subject:'recipe',object:assertion['@id'],predicate:'usesEvidence'};
  const input={nodes:['material','observation','evidence','recipe'].map(id=>({'@id':id})),edges:[assertion,support,memory]};
  const before=JSON.stringify(input), normalized=ui.normalizeGraph(input);
  assert.deepEqual(normalized.edges,input.edges);
  assert.strictEqual(normalized.nodes.find(n=>n['@id']===assertion['@id']),assertion);
  assert.equal(JSON.stringify(input),before);
  const elements=ui.buildElements(normalized,assertion['@id'],{returned:[assertion['@id']],traversed:[support['@id']]});
  assert.equal(new Set(elements.map(e=>e.data.id)).size,elements.length);
  assert.equal(elements.filter(e=>e.data.source).length,3,'No display connector invents an extra scientific edge');
  const views=elements.filter(e=>e.data.record_id===assertion['@id']);
  assert.equal(views.length,2);
  views.forEach(e=>{assert.strictEqual(e.data.record,assertion);assert.match(e.classes,/returned/);assert.doesNotMatch(e.classes,/traversed/);});
  const node=views.find(e=>!e.data.source), edge=views.find(e=>e.data.source);
  assert.match(node.data.label,/^Assertion:/);
  assert.notEqual(node.data.id,edge.data.id);
  assert.equal(elements.find(e=>e.data.record_id===support['@id']).data.source,node.data.id);
  assert.equal(elements.find(e=>e.data.record_id===memory['@id']).data.target,node.data.id);
});

test('bundled Cytoscape loads assertion nodes and edges without duplicate IDs and resolves both by record identity', () => {
  const cytoscape=require('../oopc/web/vendor/cytoscape.min.js');
  const assertion={'@id':'claim:measurement','@type':'Claim',label:'Assertion',subject:'material',object:'observation',predicate:'measuredProperty'};
  const support={'@id':'claim:support','@type':'Claim',subject:assertion['@id'],object:'evidence',predicate:'supportedBy'};
  // A canonical ID that resembles a display ID still must not collide.
  const lookalike=ui.graphElementId('edge',assertion['@id']);
  const graph={nodes:['material','observation','evidence',lookalike].map(id=>({'@id':id})),edges:[assertion,support]};
  const elements=ui.buildElements(graph), cy=cytoscape({headless:true,elements});
  try {
    assert.equal(cy.elements().length,elements.length);
    assert.equal(cy.edges().length,2);
    const views=ui.recordElements(cy,assertion['@id']);
    assert.equal(views.length,2);
    views.addClass('event-focus');
    assert.equal(cy.elements('.event-focus').length,2);
    views.forEach(e=>assert.equal(e.data('record')['@id'],assertion['@id']));
    assert.equal(ui.recordElements(cy,support['@id']).source().data('record_id'),assertion['@id']);
    assert.equal(ui.recordElements(cy,lookalike).length,1);
  } finally {cy.destroy();}
});

test('later neighborhood merges replace an unobserved assertion endpoint only with a supplied record', () => {
  const evidence={'@id':'evidence'}, missing={'@id':'claim:measurement','@type':'Unobserved'};
  const support={'@id':'claim:support','@type':'Claim',subject:missing['@id'],object:evidence['@id'],predicate:'supportedBy'};
  const early={nodes:[evidence,missing],edges:[support]};
  const assertion={'@id':missing['@id'],'@type':'Claim',subject:'material',object:'observation',predicate:'measuredProperty'};
  const before=JSON.stringify(early);
  const merged=ui.mergeGraphs(early,{nodes:[{'@id':'material'},{'@id':'observation'}],edges:[assertion]});
  assert.strictEqual(merged.nodes.find(n=>n['@id']===assertion['@id']),assertion);
  assert.equal(merged.edges.length,2);
  assert.equal(JSON.stringify(early),before);
  assert.equal(ui.normalizeGraph(early).nodes.find(n=>n['@id']===missing['@id'])['@type'],'Unobserved');
});

test('failed operations, delivery, citations, support, and reuse remain distinct', () => {
  assert.equal(ui.eventKind({operation:'traverse', status:'failed', result_ids:['claim:1']}), 'failed');
  assert.equal(ui.eventKind({operation:'delivery_confirmed', result_ids:['claim:1']}), 'delivered');
  assert.equal(ui.eventKind({operation:'citation', result_ids:['claim:1']}), 'cited');
  assert.equal(ui.eventKind({operation:'reviewer_supported', result_ids:['claim:1']}), 'supported');
  assert.equal(ui.eventKind({operation:'reuse_tested', result_ids:['claim:1']}), 'reuse-tested');
  assert.equal(ui.eventKind({operation:'traverse', traversed_edges:['claim:1']}), 'traversed');
});

test('candidate relationships retain their separate visual status', () => {
  const elements = ui.buildElements({...graph, edges:[{...graph.edges[0], status:'candidate'}]});
  assert.match(elements.find(e=>e.data.record_id === 'claim:1').classes, /candidate/);
});

test('untrusted records cannot inject markup or active links', () => {
  assert.equal(ui.escapeHTML('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
  assert.equal(ui.safeURL('javascript:alert(1)'), null);
  assert.equal(ui.safeURL('data:text/html,bad'), null);
  assert.equal(ui.safeURL('https://example.org/paper'), 'https://example.org/paper');
});

test('offline distribution includes the actual pinned graph library and its license', () => {
  const vendor = path.join(__dirname, '../oopc/web/vendor');
  assert.ok(fs.statSync(path.join(vendor,'cytoscape.min.js')).size > 100000);
  assert.match(fs.readFileSync(path.join(vendor,'cytoscape.LICENSE'),'utf8'), /MIT/);
  const html = fs.readFileSync(path.join(__dirname,'../oopc/web/index.html'),'utf8');
  assert.doesNotMatch(html, /<script[^>]+src=["']https?:/);
  assert.doesNotMatch(html, /<link[^>]+href=["']https?:/);
});

test('citation navigation selects an earlier successful access, never an artifact or later retrieval', () => {
  const events=[
    {event_id:'get-first',sequence:1,kind:'access',status:'ok',result_ids:['evidence:1']},
    {event_id:'proposal',sequence:2,kind:'candidate',status:'ok',result_ids:['external:1']},
    {event_id:'answer',sequence:3,kind:'artifact',status:'ok',result_ids:['evidence:1','external:1']},
    {event_id:'review',sequence:4,kind:'review',status:'ok',result_ids:['external:1']},
    {event_id:'get-later',sequence:5,kind:'access',status:'ok',result_ids:['external:1']},
    {event_id:'get-failed',sequence:6,kind:'access',status:'error',result_ids:['external:2']},
  ];
  assert.equal(ui.resolveCitationAccess(events,'evidence:1','answer').event_id,'get-first');
  assert.equal(ui.resolveCitationAccess(events,'external:1','answer'),null);
  assert.equal(ui.resolveCitationAccess(events,'external:1','review'),null);
  assert.equal(ui.resolveCitationAccess(events,'external:2'),null);
  assert.equal(ui.resolveCitationAccess(events,'external:1','get-later').event_id,'get-later');
});

test('empty searches, candidates, attachments and mixed reviews keep truthful timeline labels', () => {
  assert.equal(ui.eventKind({kind:'access',operation:'search',result_ids:[],status:'ok'}),'returned');
  assert.equal(ui.eventKind({kind:'access',operation:'traverse',traversed_edges:[],status:'ok'}),'returned');
  assert.equal(ui.eventKind({kind:'candidate',operation:'attach_candidate',result_ids:['claim:1']}),'candidate');
  assert.equal(ui.eventKind({kind:'artifact',artifact_type:'external_evidence',result_ids:[]}),'attachment');
  assert.equal(ui.eventKind({kind:'review',result_ids:['passed-source']}),'review');
  assert.equal(ui.eventKind({kind:'review',result_ids:[]}),'review');
  const highlights=ui.trajectoryHighlights([
    {kind:'candidate',result_ids:['candidate:1']},
    {kind:'delivery',result_ids:['delivered-only']},
    {kind:'review',result_ids:['passed-source']},
  ]);
  assert.deepEqual(highlights.returned,[]);
  assert.deepEqual(highlights.delivered,['delivered-only']);
  assert.deepEqual(highlights['reviewer-supported'],['passed-source']);
});

test('the rendered answer exposes every individual claim and its own citation navigation', () => {
  const html=ui.renderClaimCards({event_id:'answer-event',claims:[
    {id:'claim-A',text:'A qualified measurement <23 °C>',citations:['evidence-A']},
    {id:'claim-B',text:'A contradictory observation',citations:['evidence-B']},
  ]});
  assert.match(html,/claim-A/);
  assert.match(html,/A qualified measurement &lt;23 °C&gt;/);
  assert.match(html,/data-citation="evidence-A" data-citation-event="answer-event"/);
  assert.match(html,/claim-B/);
  assert.match(html,/data-citation="evidence-B" data-citation-event="answer-event"/);
  assert.equal((html.match(/class="answer-claim"/g) || []).length,2);
});

test('preview candidates remain visible when newly proposed overlays are hidden', () => {
  const candidate={ '@id':'material:preview','@type':'Material',status:'candidate' };
  const overlay={...candidate,'@id':'candidate:event:material:preview',candidate_event_id:'event'};
  const filtered=ui.hideProposalOverlays({nodes:[candidate,overlay],edges:[],highlights:{candidates:[overlay['@id']]}});
  assert.deepEqual(filtered.nodes,[candidate]);
  assert.match(ui.buildElements(filtered)[0].classes,/candidate/);
  assert.equal(ui.isCandidatePreview({sourceReviewRequired:true,purpose:'Scientific candidate example'}),true);
  assert.equal(ui.isCandidatePreview({purpose:'Published seed release'}),false);
});

test('historical baseline task questions render without changing immutable run metadata', () => {
  const run={task:{case:{caseId:'dev-1',question:'Compare qualified PLA <grades>.',rubric:['Preserve conditions']},mode:'graph'}};
  const before=JSON.stringify(run);
  const html=ui.renderTaskSpecification(run);
  assert.match(html,/Compare qualified PLA &lt;grades&gt;\./);
  assert.match(html,/Case: dev-1 · Mode: graph/);
  assert.match(html,/Preserve conditions/);
  assert.doesNotMatch(html,/No description recorded/);
  assert.equal(JSON.stringify(run),before);
  assert.match(ui.renderTaskSpecification({task:{case:{specification:{question:'Historical specification question'}}}}),/Historical specification question/);
  assert.match(ui.renderTaskSpecification({task:{specification:'A saved task specification'}}),/A saved task specification/);
  assert.match(ui.renderTaskSpecification({task:{question:'New top-level question',case:{question:'Old fallback'}}}),/New top-level question/);
});

test('live follow refreshes metadata-only completion without fabricating access events', async () => {
  const calls=[];
  const events={events:[],last_sequence:7};
  const run={run_id:'run-live',status:'completed',last_sequence:7,finished_at:'2026-09-13T12:00:00Z'};
  const update=await ui.readLiveUpdate(async (url,params)=>{
    calls.push({url,params});
    if(url.endsWith('/events')) {assert.deepEqual(params,{after:7});return events;}
    assert.equal(url,'/api/runs/run-live');
    return run;
  },'run-live',7);
  assert.equal(update.run.status,'completed');
  assert.deepEqual(update.result.events,[]);
  assert.equal(update.artifacts,null);
  assert.equal(calls.length,2);
  assert.deepEqual(events,{events:[],last_sequence:7});
});

test('live follow retrieves new artifacts and capture capabilities with the event delta', async () => {
  const event={event_id:'delivery-1',sequence:2,kind:'delivery'};
  const run={run_id:'run-live',status:'running',capabilities:{context_delivery:true}};
  const artifact={id:'answer',event_id:'answer-event',text:'Qualified answer'};
  const update=await ui.readLiveUpdate(async url=>{
    if(url.endsWith('/events')) return {events:[event],last_sequence:2};
    if(url.endsWith('/artifacts')) return {artifacts:[artifact]};
    return run;
  },'run-live',1);
  assert.equal(update.run.capabilities.context_delivery,true);
  assert.deepEqual(update.result.events,[event]);
  assert.deepEqual(update.artifacts.artifacts,[artifact]);
});
