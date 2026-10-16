/* Offline inspector. All graph reads are ordinary GETs, never agent trace writes. */
(function () {
  "use strict";

  const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const list = value => value == null ? [] : Array.isArray(value) ? value : [value];
  const idOf = value => typeof value === "object" && value !== null ? value["@id"] || value.id || value.record_id || "" : String(value ?? "");
  const localName = value => String(value ?? "").split(/[\/#:]/).pop();
  const typeOf = record => localName(list(record?.["@type"] || record?.type)[0] || "Record");
  const labelOf = record => record?.label || record?.name || record?.title || localName(idOf(record)) || "Untitled record";
  const graphLabel = record => {
    const text=typeOf(record)==="Section" && record.sectionKey ? humanize(record.sectionKey) : typeOf(record)==="Facet" && record.axis ? `${labelOf(record)} · ${humanize(record.axis).toLowerCase()}` : labelOf(record);
    return text.length>54 ? text.slice(0,51)+"…" : text;
  };
  const humanize = value => String(value ?? "").replace(/[_-]/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2");
  const safeURL = value => { try { const u = new URL(value); return ["https:", "http:"].includes(u.protocol) ? u.href : null; } catch { return null; } };
  const isCandidatePreview = release => release?.sourceReviewRequired === true && /candidate/i.test(release.purpose || "");
  const isReplaySnapshot = run => !!(run?.imported || run?.immutable_replay);
  const runStatusLabel = run => isReplaySnapshot(run) ? (run.recorded_status && run.recorded_status !== "unknown" ? `Replay · recorded ${humanize(run.recorded_status)}` : "Replay · original outcome unknown") : humanize(run?.status || "recorded");
  const replayStatusNote = run => !isReplaySnapshot(run) ? "" : run.replay_status_note || (run.recorded_status && run.recorded_status !== "unknown" ? "This is an immutable replay snapshot. Live follow is unavailable." : "This older import did not preserve the original task outcome. Completion cannot be inferred.");
  const grade = value => typeof value === "number" && Number.isFinite(value) && value>=0 && value<=1 ? (1+9*value).toFixed(1)+" / 10" : null;
  const assessmentCount = (evaluation, key) => Number.isSafeInteger(evaluation?.assessmentCounts?.[key]) && evaluation.assessmentCounts[key]>=0 ? evaluation.assessmentCounts[key] : null;
  const evaluationDenominators = evaluation => {
    const counts={scientificClaims:null,scientificSupportLinks:null}, claims=evaluation.answerClaimAssessments;
    if(evaluation.independentlySourceChecked!==true || evaluation.completeAnswerCoverage!==true || !Array.isArray(claims) || !claims.length) return counts;
    if(claims.some(c=>!c || typeof c.claimId!=="string" || !c.claimId || !["scientific-claim","corpus-attribution","abstention"].includes(c.kind) || !["pass","fail","uncertain"].includes(c.verdict)) || new Set(claims.map(c=>c.claimId)).size!==claims.length) return counts;
    counts.scientificClaims=claims.filter(c=>c.kind==="scientific-claim").length;
    let links=0;
    for(const claim of claims) {
      if(!Array.isArray(claim.citations)) return counts;
      const ids=[];
      for(const citation of claim.citations) {
        if(!citation || typeof citation.evidenceId!=="string" || !citation.evidenceId || !["support","access-gap","corpus-attribution"].includes(citation.role) || citation.role==="support" && claim.kind!=="scientific-claim") return counts;
        ids.push(citation.evidenceId);
        if(citation.role==="support") links++;
      }
      if(new Set(ids).size!==ids.length) return counts;
    }
    if(Object.hasOwn(evaluation,"supportLinks") && (!Number.isSafeInteger(evaluation.supportLinks) || evaluation.supportLinks!==links)) return counts;
    counts.scientificSupportLinks=links;
    return counts;
  };
  const evaluationLabel = summary => {
    const evaluation=summary?.evaluation || {};
    if(evaluation.qualification==="source-checked") {
      const score=grade(evaluation.scores?.supportedCorrectness), claims=assessmentCount(evaluation,"scientificClaims"), links=assessmentCount(evaluation,"scientificSupportLinks");
      const parts=claims===0 ? ["No scientific claims assessed"] : score ? [`Supported correctness: ${score}${claims===null ? " (claim count unavailable)" : ` (${claims} assessed)`}`] : [];
      if(links===0) parts.push("No scientific-support citations assessed");
      for(const [key,label] of [["taskCompletionScore","Feasible completion"],["fullResearchCoverage","Full coverage"]]) {
        const value=grade(evaluation.scores?.[key]);
        if(value) parts.push(`${label}: ${value}`);
      }
      return parts.length ? [...parts,`strict gate: ${evaluation.verdict || "not recorded"}`].join(" · ") : evaluation.verdict ? `Task evaluation: ${evaluation.verdict}` : "Task evaluation: verdict not recorded";
    }
    if(evaluation.qualification==="unscorable") return "Task evaluation: unscorable";
    if(evaluation.qualification==="unqualified-review") return `Task review: ${evaluation.reportedVerdict} · numeric grade not recorded`;
    return "Task evaluation: not recorded";
  };
  const publicationInspectionLabel = summary => {
    const inspection=summary?.publicationInspection;
    if(!inspection || inspection.status==="not-recorded") return "";
    if(inspection.status==="pending") return "Assigned paper: inspection pending";
    if(inspection.status!=="recorded") return "Assigned paper: outcome unavailable";
    if(inspection.disposition==="completed" && inspection.taskComplete===true) return "Assigned paper: inspected with accepted claims";
    if(inspection.disposition==="inspected-no-additions" && inspection.taskComplete===true) return "Assigned paper: inspected, no new claims";
    if(inspection.disposition==="unavailable-incomplete" && inspection.taskComplete===false) return "Assigned paper: inspection incomplete";
    return "Assigned paper: outcome unavailable";
  };
  const runOutcomeLabel = run => [publicationInspectionLabel(run?.inspectorSummary),evaluationLabel(run?.inspectorSummary)].filter(Boolean).join(" · ");
  const reviewEvaluation = evaluation => ({qualification:evaluation.independentlySourceChecked===true ? "source-checked" : "unscorable",verdict:evaluation.independentlySourceChecked===true && ["pass","fail","uncertain"].includes(evaluation.reviewVerdict) ? evaluation.reviewVerdict : null,scores:evaluation.independentlySourceChecked===true ? evaluation : {},assessmentCounts:evaluationDenominators(evaluation)});
  const renderReviewCoverage = review => {
    const badge=value=>value ? `<span class="badge ${escapeHTML(String(value).replace(/[^a-z-]/gi,""))}">${escapeHTML(humanize(value))}</span>` : "";
    const criteria=list(review.taskCriteria);
    if(criteria.length) return `<h4>Task coverage</h4>${criteria.map(c=>`<div class="status-message">${badge(c.verdict)}<p class="record-id">${escapeHTML(c.criterionId)}</p><p>${escapeHTML(c.rationale || "No rationale recorded")}</p></div>`).join("")}`;
    const checks=review.evaluation?.taskCoverageChecks;
    const entries=checks && typeof checks==="object" && !Array.isArray(checks) ? Object.entries(checks).filter(([,check])=>check && typeof check==="object" && !Array.isArray(check)) : [];
    if(entries.length) return `<h4>Task coverage</h4>${review.evaluation.independentlySourceChecked===true ? "" : '<p class="event-note">Recorded coverage judgments; this evaluation is unscorable. These judgments do not establish a qualified score.</p>'}${entries.map(([reference,check])=>`<div class="status-message">${badge(check.outcome || "Outcome not recorded")}<p class="record-id">${escapeHTML(reference)}</p><p>Mapped answer claims: ${escapeHTML(list(check.answerClaimIds).join(", ") || "None recorded")}</p><p>${escapeHTML(check.rationale || "No rationale recorded")}</p></div>`).join("")}`;
    return '<p class="event-note">This review did not record separate task-coverage judgments. Inspect its scope and limitations.</p>';
  };
  const renderGrades = evaluation => {
    if(evaluation?.qualification!=="source-checked") return "";
    const fields=[["supportedCorrectness","Supported correctness"],["qualificationScore","Material and test qualifications"],["citationEntailment","Citation support"],["taskCompletionScore","Feasible task completion"],["abstentionScore","Appropriate abstention"],["fullResearchCoverage","Full research coverage"]];
    const values=fields.filter(([key])=>grade(evaluation.scores?.[key])!==null);
    if(!values.length) return '<p class="event-note">This review did not record graded scores.</p>';
    const coverage=Object.entries(evaluation.coverageOutcomes || {}).filter(([,count])=>Number.isInteger(count) && count>0).map(([key,count])=>`${count} ${humanize(key)}`).join(" · ");
    const denominators={supportedCorrectness:["scientificClaims","scientific claims"],citationEntailment:["scientificSupportLinks","scientific-support citations"]}, arithmetic=[];
    const rows=values.map(([key,label])=>{
      let shown=grade(evaluation.scores[key]);
      if(denominators[key]) {
        const [field,unit]=denominators[key], count=assessmentCount(evaluation,field);
        if(count===0) {
          arithmetic.push(`${label}: recorded arithmetic ${shown}; no ${unit} were assessed, so this is not an assessed success grade.`);
          shown=`No ${unit} assessed`;
        } else shown+=count===null ? " (assessed count unavailable)" : ` (${count} assessed)`;
      }
      return `<div><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(shown)}</dd></div>`;
    }).join("");
    return `<section class="evaluation-grades"><h4>Graded assessment</h4><dl>${rows}</dl>${arithmetic.length ? `<p class="event-note">${escapeHTML(arithmetic.join(" "))} Recorded scores and strict decisions are unchanged.</p>` : ""}<p class="event-note">Scale: 1 = no credit, 10 = full credit; each grade is 1 + 9 × the recorded score. These dimensions, not the binary gate, supply the A/B signal. The strict gate can fail despite partial success.</p><p class="event-note">Feasible completion gives credit for justified abstention when evidence is unavailable. Full research coverage counts supported answers to the original research question.</p>${coverage ? `<p class="event-note">${escapeHTML(coverage)}</p>` : ""}</section>`;
  };
  const renderOutcomeSummary = run => {
    const summary=run?.inspectorSummary || {}, evaluation=summary.evaluation || {}, findings=summary.claimFindings || {}, retrieval=summary.retrieval, condition=summary.condition || {};
    const row=(label,value)=>`<div><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value)}</dd></div>`;
    const count=Object.values(findings).reduce((total,value)=>total+value,0);
    const qualification=evaluation.qualification==="source-checked" ? "Qualified, independently source-checked evaluation." : evaluation.qualification==="unscorable" ? "Source verification or evaluation qualification is incomplete. A reported verdict is not a usable task score." : "Evaluation qualification was not recorded.";
    const claimText=count ? `${findings.pass || 0} pass · ${findings.fail || 0} fail · ${findings.uncertain || 0} uncertain${findings.unclassified ? ` · ${findings.unclassified} unclassified` : ""}` : "No claim findings recorded";
    const retrievalText=retrieval ? `${retrieval.returnedRelationships} returned · ${retrieval.traversedRelationships} explicitly traversed (${retrieval.traversalCalls} traversal calls)` : "Not recorded";
    const recipeText=retrieval ? `${retrieval.returnedRecipes} returned · ${retrieval.deliveredRecipes} delivered · ${retrieval.citedRecipes} cited (${retrieval.recipeLookupCalls} recipe lookups)` : "Not recorded";
    const inspection=publicationInspectionLabel(summary);
    return `<div class="outcome-summary"><dl>${row("Execution",runStatusLabel(run))}${inspection ? row("Assigned publication",inspection) : ""}${row(inspection ? "Task review" : "Overall task",evaluationLabel(summary))}</dl>${renderGrades(evaluation)}<p class="event-note">Execution completion does not establish scientific success. ${escapeHTML(qualification)}</p>${inspection ? '<p class="event-note">Assigned-paper inspection, reviewer findings and scientific claim admission are separate outcomes.</p>' : ""}${evaluation.reportedVerdict && evaluation.qualification!=="source-checked" ? `<p class="event-note">Reviewer-reported verdict: ${escapeHTML(evaluation.reportedVerdict)}.</p>` : ""}<dl>${row("Claim findings · latest review",claimText)}</dl><p class="event-note">Passing claim findings can coexist with a failed overall task.</p><dl>${row("Relationships",retrievalText)}${row("Recipes",recipeText)}</dl>${retrieval?.returnedRecipes===0 ? '<p class="event-note">No recipe was returned in the recorded access events. Graph-memory mode alone does not establish recipe use.</p>' : '<p class="event-note">Retrieval, delivery and citation are separate observations; recipe influence on reasoning is not observed.</p>'}${retrieval?.returnedProjections ? `<p class="event-note">${retrieval.returnedProjections} partial record projections were returned. A projection is not the full record or a relationship.</p>` : ""}<dl>${row("Experiment condition",condition.recorded ? "Condition recorded" : "Not recorded in this trace")}${condition.adapterVersion ? row("Adapter version",condition.adapterVersion) : ""}${condition.recorded ? row("Retrieval protocol",condition.retrievalProtocol || "Not recorded") : ""}${row("Current cohort membership","Not established by this trace")}</dl></div>`;
  };
  const graphTopologyNote = graph => {
    const nodes=list(graph?.nodes), edges=list(graph?.edges);
    if(!nodes.length) return "";
    const projections=nodes.filter(node=>["RecordFragment","RecordProjection"].includes(typeOf(node))).length;
    const endpoints=new Set(edges.flatMap(edge=>[idOf(edge.subject || edge.source),idOf(edge.object || edge.target)]));
    const isolated=nodes.filter(node=>!endpoints.has(idOf(node))).length;
    const neighbors=new Map(nodes.map(node=>[idOf(node),[]]));
    edges.forEach(edge=>{const a=idOf(edge.subject || edge.source), b=idOf(edge.object || edge.target);if(neighbors.has(a) && neighbors.has(b)){neighbors.get(a).push(b);neighbors.get(b).push(a);}});
    const visited=new Set();let groups=0;
    neighbors.forEach((_,id)=>{if(visited.has(id))return;groups++;const pending=[id];while(pending.length){const next=pending.pop();if(visited.has(next))continue;visited.add(next);neighbors.get(next).forEach(other=>{if(!visited.has(other))pending.push(other);});}});
    const topology=!edges.length ? "Records only: no relationships are present in this view. Layout does not imply connections." : groups>1 ? `${groups} disconnected groups in this view.${isolated ? ` ${isolated} records have no connecting relationship.` : ""} Layout does not imply connections.` : "";
    return [topology,projections ? `${projections} partial record projections; full records and relationships are not implied.` : ""].filter(Boolean).join(" ");
  };
  const neighborhoodPageKey = (id, filters) => JSON.stringify([id, Object.entries(filters).sort(([a],[b])=>a.localeCompare(b))]);
  const category = record => /Polymer|Material|Specimen/i.test(typeOf(record)) ? "material" : /Source|Document|Publication|Evidence|Dataset|Work|Section/i.test(typeOf(record)) ? "evidence" : /Process|Property|Class|Taxon|Concept|Environment|Application|Method|Facet/i.test(typeOf(record)) ? "process" : "material";
  const eventKind = event => {
    const op = `${event.kind || ""} ${event.operation || ""}`.toLowerCase();
    if (["error", "failed", "failure"].includes(event.status || event.outcome)) return "failed";
    if (event.kind === "candidate") return "candidate";
    if (event.artifact_type === "external_evidence") return "attachment";
    // Review events may contain a mixture of pass, fail and uncertain findings.
    // Only their separate supported record IDs are eligible for highlights.
    if (event.kind === "review") return "review";
    if (event.kind === "reuse") return list(event.result_ids).length ? "reuse-tested" : "reuse";
    if (event.kind === "artifact") return list(event.result_ids).length ? "cited" : "artifact";
    if (event.kind === "lifecycle") return "lifecycle";
    if (event.kind === "delivery") return "delivered";
    if (event.kind === "access") return list(event.traversed_edges).length ? "traversed" : "returned";
    if (/review|supported|validation/.test(op)) return "supported";
    if (/reuse/.test(op)) return "reuse-tested";
    if (/cit|artifact/.test(op)) return "cited";
    if (list(event.traversed_edges).length || /traverse/.test(op)) return "traversed";
    if (/deliver/.test(op)) return "delivered";
    if (list(event.result_ids).length) return "returned";
    return "lifecycle";
  };
  const resolveCitationAccess = (events, recordId, eventId) => {
    const origin = events.find(e=>e.event_id === eventId);
    const eligible = events.filter(e=>e.kind === "access" && e.status === "ok" &&
      (!origin || e.sequence <= origin.sequence) && list(e.result_ids).includes(recordId));
    return eligible.find(e=>e.event_id === eventId) || eligible.at(-1) || null;
  };
  const citationButton = (citation, eventId="") => {
    const id = typeof citation === "string" ? citation : citation.record_id || citation.source_id || citation.claim_id || citation["@id"] || "";
    return `<button class="citation-button" data-citation="${escapeHTML(id)}" data-citation-event="${escapeHTML(citation.event_id || eventId)}">${escapeHTML(citation.label || citation.title || id)} ↗</button>`;
  };
  const taskArtifactGroups = (events, artifacts) => {
    const reviewEvents=new Set(list(events).filter(e=>e.kind==="review").map(e=>e.event_id));
    const candidateEvents=new Set(list(events).filter(e=>e.kind==="candidate").map(e=>e.event_id));
    const inspections=list(artifacts).filter(a=>a.type==="publication_inspection");
    const ordinary=list(artifacts).filter(a=>!inspections.includes(a));
    const reviews=ordinary.filter(a=>reviewEvents.has(a.event_id) || Array.isArray(a.findings));
    const proposals=ordinary.filter(a=>candidateEvents.has(a.event_id));
    const attachments=ordinary.filter(a=>a.type==="external_evidence");
    return {inspections,reviews,proposals,attachments,deliverables:ordinary.filter(a=>!reviews.includes(a) && !proposals.includes(a) && !attachments.includes(a))};
  };
  const renderPublicationInspection = (run, artifacts=[]) => {
    const inspection=run?.inspectorSummary?.publicationInspection, label=publicationInspectionLabel(run?.inspectorSummary);
    if(!label) return "";
    const artifact=list(artifacts).find(a=>a.type==="publication_inspection" && a.event_id===inspection.eventId);
    const job=run.task?.specification || {}, specification=job.specification || job;
    const publication=artifact?.assignedPublication || specification.publicationIngestion?.assignedPublication || {};
    const url=safeURL(publication.url), date=typeof publication.publication==="string" ? publication.publication : list(publication.publication?.["date-parts"]?.[0]).join("-");
    const recorded=inspection.status==="recorded", completed=recorded && inspection.taskComplete===true;
    const note=inspection.status==="pending" ? "No completed inspection receipt has been recorded for this assignment." : inspection.status!=="recorded" ? "The recorded outcome could not be interpreted. Inspection completion is not established." : completed ? "The assigned-paper inspection is complete. Claim admission is shown separately below." : "The assigned-paper inspection is incomplete. Reviewer findings and individual claim admissions remain separate.";
    const sources=recorded ? list(inspection.sourceIds) : [], claims=recorded ? list(inspection.acceptedClaimIds) : [];
    const issues=list(inspection.issues).map(issue=>`<li>${escapeHTML(issue)}</li>`).join("");
    return `<article class="artifact"><h4>${escapeHTML(publication.title || "Assigned publication")}</h4>${publication.doi || date ? `<p class="record-id">${escapeHTML([publication.doi ? `DOI: ${publication.doi}` : "",date].filter(Boolean).join(" · "))}</p>` : ""}${url ? `<p><a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">Publication page ↗</a></p>` : ""}<p><strong>${escapeHTML(label)}</strong></p><p class="event-note">${escapeHTML(note)}</p>${issues ? `<div class="scope-callout"><strong>Inspection issues</strong><ul>${issues}</ul></div>` : ""}${sources.length ? `<h4>Inspected sources</h4>${sources.map(id=>`<div class="source-link">${citationButton(id,inspection.eventId)}</div>`).join("")}<p class="event-note">Source links retain any gaps in recorded access. This receipt does not establish an observed source read or model delivery.</p>` : recorded ? '<p class="muted">No inspected source identifiers recorded.</p>' : ""}${recorded ? `<h4>Scientific claim admission</h4>${claims.length ? `<p>${claims.length} accepted claim proposal${claims.length===1 ? "" : "s"} from the assigned paper.</p>${claims.map(id=>`<div class="source-link">${citationButton(id,inspection.eventId)}</div>`).join("")}` : '<p>No accepted claim proposals from the assigned paper are recorded in this receipt.</p>'}<p class="event-note">Admission does not establish public release or measured improvement.</p>` : ""}${artifact ? `<details class="raw-data"><summary>Recorded inspection receipt</summary><pre>${escapeHTML(JSON.stringify(artifact.inspection,null,2))}</pre></details>` : ""}</article>`;
  };
  const renderClaimCards = artifact => list(artifact.claims).map(claim=>`<article class="answer-claim"><h4>${escapeHTML(claim.id || claim["@id"] || "Answer claim")}</h4><p>${escapeHTML(claim.text || claim.claim || claim.statement || claim.answer || "Claim text was not recorded.")}</p>${list(claim.citations).map(c=>citationButton(c,artifact.event_id)).join("")}${!list(claim.citations).length ? '<p class="muted">No citations attached to this claim.</p>' : ""}</article>`).join("");
  const renderTaskSpecification = run => {
    const task=run.task || run.specification || {}, caseSpec=task.case || {}, specification=task.specification || {};
    const publicationSpecification=specification.specification?.publicationIngestion ? specification.specification : specification.publicationIngestion ? specification : null;
    const describe=value=>typeof value==="string" ? value : value?.description || value?.question || value?.prompt;
    const description=describe(publicationSpecification) || describe(task) || describe(caseSpec) || describe(caseSpec.specification) || describe(specification) || run.description || "No description recorded.";
    const rubric=task.rubric || caseSpec.rubric || specification.rubric;
    const metadata=[caseSpec.caseId ? `Case: ${caseSpec.caseId}` : "", task.mode ? `Mode: ${task.mode}` : ""].filter(Boolean).join(" · ");
    return `<p>${escapeHTML(description)}</p>${publicationSpecification?.deliverable ? `<p>${escapeHTML(publicationSpecification.deliverable)}</p>` : ""}${publicationSpecification ? `<h4>Frozen inspection criteria</h4><ul>${list(publicationSpecification.publicationIngestion.criteria).map(item=>`<li>${escapeHTML(item.requirement || item)}</li>`).join("")}</ul>` : ""}${metadata ? `<p class="record-id">${escapeHTML(metadata)}</p>` : ""}${task.notice ? `<div class="scope-callout">${escapeHTML(task.notice)}</div>` : ""}${rubric ? `<pre>${escapeHTML(typeof rubric==="string" ? rubric : JSON.stringify(rubric,null,2))}</pre>` : ""}`;
  };
  const normalizeGraph = graph => {
    const nodes = new Map(), edges = new Map();
    list(graph?.nodes).forEach(n => { if (idOf(n)) nodes.set(idOf(n), n); });
    const suppliedEdges = new Map(list(graph?.edges).filter(e=>idOf(e)).map(e=>[idOf(e),e]));
    // An assertion may also be the identified subject/object of another edge.
    // Its returned record can therefore appear as both a node and an edge.
    // These are views of one record, not a newly inferred scientific relation.
    suppliedEdges.forEach(e=>[idOf(e.subject || e.source),idOf(e.object || e.target)].forEach(id=>{
      const record=suppliedEdges.get(id);
      if(typeOf(record)==="Claim" && (!nodes.has(id) || typeOf(nodes.get(id))==="Unobserved")) nodes.set(id,record);
    }));
    list(graph?.edges).forEach(e => {
      const source = idOf(e.subject || e.source), target = idOf(e.object || e.target);
      if (idOf(e) && nodes.has(source) && nodes.has(target)) edges.set(idOf(e), e);
    });
    return {nodes: [...nodes.values()], edges: [...edges.values()], highlights: graph?.highlights || {}, truncated: !!graph?.truncated};
  };
  const mergeGraphs = (a, b) => normalizeGraph({nodes: [...list(a?.nodes), ...list(b?.nodes)], edges: [...list(a?.edges), ...list(b?.edges)], truncated: !!a?.truncated || !!b?.truncated, highlights: b?.highlights || a?.highlights});
  const eventRecordIds = event => [...new Set([...list(event.result_ids).map(idOf), ...list(event.record_ids).map(idOf), ...list(event.citations).map(c => idOf(c.record_id || c.source_id || c))].filter(Boolean))];
  const graphElementId = (kind, recordId) => JSON.stringify([kind,recordId]);
  const recordElements = (graph, recordId) => graph.elements().filter(element=>element.data("record_id")===recordId);
  const buildElements = (graph, selectedId, highlight = {}) => {
    const g = normalizeGraph(graph);
    const flags = id => Object.entries(highlight).filter(([, ids]) => list(ids).map(idOf).includes(id)).map(([key]) => key.replaceAll("_", "-")).join(" ");
    return [...g.nodes.map(n => ({data: {id:graphElementId("node",idOf(n)), record_id:idOf(n), label:typeOf(n)==="Claim" ? `Assertion: ${graphLabel(n)}` : graphLabel(n), category:typeOf(n)==="Claim" ? "evidence" : category(n), record:n}, classes:`${flags(idOf(n))} ${idOf(n) === selectedId ? "focus-node" : ""} ${typeOf(n) === "Unobserved" ? "unobserved" : ""} ${n.status === "candidate" || n.status === "experimental" ? "candidate" : ""}`})), ...g.edges.map(e => ({data:{id:graphElementId("edge",idOf(e)), record_id:idOf(e), source:graphElementId("node",idOf(e.subject || e.source)), target:graphElementId("node",idOf(e.object || e.target)), label:humanize(localName(e.predicate)), record:e}, classes:`${flags(idOf(e))} ${idOf(e) === selectedId ? "focus-node" : ""} ${e.status === "candidate" || e.status === "experimental" ? "candidate" : ""}`}))];
  };
  const hideProposalOverlays = graph => {
    const candidateIds = new Set(list(graph.highlights?.candidates).map(idOf));
    return {...graph,nodes:list(graph.nodes).filter(n=>!n.candidate_event_id && !candidateIds.has(idOf(n))),
      edges:list(graph.edges).filter(e=>!e.candidate_event_id && !candidateIds.has(idOf(e)))};
  };
  async function readLiveUpdate(read, runId, after) {
    const base = `/api/runs/${encodeURIComponent(runId)}`;
    // Completion updates run metadata without inventing a new access event.
    // Always refresh it, including polls that return an empty event delta.
    const [result, run] = await Promise.all([read(`${base}/events`, {after}), read(base)]);
    const artifacts = list(result.events).length ? await read(`${base}/artifacts`) : null;
    return {result, run, artifacts};
  }

  // These helpers are also exercised by the no-browser contract tests.
  if (typeof module !== "undefined" && module.exports) module.exports = {escapeHTML, idOf, typeOf, labelOf, humanize, safeURL, eventKind, normalizeGraph, mergeGraphs, eventRecordIds, graphElementId, recordElements, buildElements, resolveCitationAccess, renderClaimCards, renderTaskSpecification, trajectoryHighlights, isCandidatePreview, hideProposalOverlays, readLiveUpdate};
  if (typeof module !== "undefined" && module.exports) Object.assign(module.exports, {isReplaySnapshot, runStatusLabel, replayStatusNote, neighborhoodPageKey, evaluationLabel, reviewEvaluation, renderReviewCoverage, publicationInspectionLabel, runOutcomeLabel, renderOutcomeSummary, renderPublicationInspection, taskArtifactGroups, graphTopologyNote, renderPairedGrades});
  if (typeof document === "undefined") return;


  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const esc = escapeHTML;
  const state = {
    mode: "graph", view: "graph", layer: "", meta: {}, terms: [], records: [], total: 0,
    graph: {nodes:[], edges:[]}, selected: null, term: null, cache: new Map(), neighborhoodPages: new Map(),
    run: null, runs: [], events: [], position: -1, live: false, playing: false,
    agent: "", cumulative: true, showCandidates: false, artifacts: [], runOntology: null,
    searchVersion: 0, graphVersion: 0, detailVersion: 0, runVersion: 0, modeVersion: 0, pollBusy: false,
    timer: null, firstSearch: true, filterTimer: null, networkCount: 0, detailType: ""
  };
  let cy;
  const emptyMarkup = $("#empty-stage").innerHTML;
  const detailEmpty = $("#detail-panel").innerHTML;
  const shortId = id => { const value = localName(id); return value.length > 36 ? `${value.slice(0, 31)}…` : value; };
  const pretty = value => typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const badges = (...values) => values.flat().map(v=>v && typeof v === "object" ? v.contentMaturity || v.status || v.label : v).filter(Boolean).map(v => `<span class="badge ${esc(String(v).replace(/[^a-z-]/gi, ""))}">${esc(humanize(v))}</span>`).join("");
  const recordButton = (id, label) => `<button class="inline-record" data-record="${esc(idOf(id))}">${esc(label || (state.cache.has(idOf(id)) ? labelOf(state.cache.get(idOf(id))) : shortId(idOf(id))))}</button>`;
  const field = (key, value) => value == null || value === "" || (Array.isArray(value) && !value.length) ? "" : `<div><dt>${esc(humanize(key))}</dt><dd>${renderValue(value)}</dd></div>`;
  const section = (title, html) => html ? `<section class="detail-section"><h3 class="section-title">${esc(title)}</h3>${html}</section>` : "";
  const raw = (record, title = "Complete record") => `<details class="raw-data"><summary>${esc(title)}</summary><pre>${esc(JSON.stringify(record, null, 2))}</pre></details>`;
  const timeLabel = value => { if (!value) return ""; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"}); };
  const dateLabel = value => { if (!value) return ""; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(); };

  function renderValue(value) {
    if (value == null) return '<span class="muted">Unknown</span>';
    if (Array.isArray(value)) return value.length ? value.map(renderValue).join("<br>") : '<span class="muted">None recorded</span>';
    if (typeof value === "object") {
      if (idOf(value)) return recordButton(idOf(value), value.label || shortId(idOf(value)));
      return `<span class="raw-inline">${esc(JSON.stringify(value, null, 2))}</span>`;
    }
    const url = safeURL(value);
    if (url) return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(value)} ↗</a>`;
    return esc(value);
  }

  async function get(path, params = {}) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") query.set(k, String(v)); });
    const response = await fetch(`${path}${query.size ? `?${query}` : ""}`, {headers:{Accept:"application/json"}, cache:"no-store"});
    if (!response.ok) {
      let message = "";
      try { const err = await response.json(); message = err.error?.message || err.error || err.message || ""; } catch { /* The status remains useful for non-JSON server failures. */ }
      throw new Error(message || `The local server returned ${response.status}.`);
    }
    return response.json();
  }
  function showError(error) { $("#error-message").textContent = error?.message || String(error); $("#error-banner").hidden = false; }
  function guard(action) { return (...args) => Promise.resolve().then(() => action(...args)).catch(showError); }
  function setStatus(text) { $("#stage-status").textContent = text; }
  function remember(records) { list(records).forEach(record => { if (idOf(record)) state.cache.set(idOf(record), record); }); }
  function currentFilters() {
    return {q:$("#search").value.trim(),type:$("#type-filter").value,status:$("#status-filter").value,predicate:$("#predicate-filter").value,layer:state.layer,
      ...Object.fromEntries(["property","process","application","environment","source"].map(k => [k,$(`#${k}-filter`).value.trim()]))};
  }
  function termFor(id) { return state.terms.find(t => idOf(t) === id || localName(idOf(t)) === localName(id)); }

  function initGraph() {
    if (!window.cytoscape) { showError(new Error("The bundled graph library is unavailable. Table view remains available.")); setView("table"); return; }
    cy = window.cytoscape({container:$("#graph"),elements:[],minZoom:.15,maxZoom:3,layout:{name:"preset"},style:graphStyle()});
    cy.on("tap", "node", guard(async event => {
      const id = event.target.data("record_id");
      if (state.mode === "ontology") await selectTerm(id);
      else await selectRecord(id, {loadGraph:false});
    }));
    cy.on("dbltap", "node", guard(async event => { if (state.mode === "graph") await loadNeighborhood(event.target.data("record_id"), true, true); }));
    cy.on("tap", "edge", guard(async event => { if(state.mode === "ontology") await selectTerm(event.target.data("record").definition); else await selectRecord(event.target.data("record_id"), {loadGraph:false}); }));
    new ResizeObserver(() => cy.resize()).observe($("#graph"));
  }
  function graphStyle() {
    const colors = getComputedStyle(document.documentElement), color = key => colors.getPropertyValue(key).trim();
    return [
      {selector:"node",style:{"background-color":color("--accent"),"background-opacity":.16,"border-color":color("--accent"),"border-width":1.3,"width":34,"height":34,"label":"data(label)","font-family":"-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif","font-size":10,"color":color("--ink"),"text-valign":"bottom","text-halign":"center","text-margin-y":8,"text-wrap":"wrap","text-max-width":145,"text-background-color":color("--canvas"),"text-background-opacity":.88,"text-background-padding":3}},
      {selector:'node[category="evidence"]',style:{"background-color":color("--gold"),"border-color":color("--gold"),"shape":"round-rectangle","width":29,"height":29}},
      {selector:'node[category="process"]',style:{"background-color":color("--violet"),"border-color":color("--violet"),"shape":"diamond","width":32,"height":32}},
      {selector:"edge",style:{"width":1,"line-color":color("--faint"),"target-arrow-color":color("--faint"),"target-arrow-shape":"triangle","arrow-scale":.7,"curve-style":"bezier","label":"data(label)","font-size":8,"color":color("--subtle"),"text-rotation":"autorotate","text-margin-y":-7,"text-background-color":color("--canvas"),"text-background-opacity":.9,"text-background-padding":2,"opacity":.7}},
      {selector:"node.focus-node, node:selected",style:{"width":46,"height":46,"border-width":2.4,"background-opacity":.35,"font-weight":"bold","font-size":11}},
      {selector:"edge.focus-node, edge:selected",style:{"width":3,"line-color":color("--accent"),"target-arrow-color":color("--accent"),"opacity":1,"font-size":10}},
      {selector:"node.returned",style:{"border-color":color("--blue"),"border-width":2.8}},
      {selector:"edge.returned",style:{"line-color":color("--blue"),"target-arrow-color":color("--blue"),"line-style":"dotted","width":1.8}},
      {selector:"edge.traversed",style:{"line-color":color("--accent"),"target-arrow-color":color("--accent"),"line-style":"solid","width":3.2,"opacity":1}},
      {selector:".cited",style:{"border-color":color("--violet"),"border-width":3.8,"line-color":color("--violet"),"target-arrow-color":color("--violet"),"width":42,"height":42}},
      {selector:".reviewer-supported, .supported, .reuse-tested",style:{"border-color":color("--accent"),"border-width":4,"border-style":"double","line-color":color("--accent")}},
      {selector:".candidate, .candidates",style:{"border-color":color("--gold"),"border-style":"dashed","line-color":color("--gold"),"target-arrow-color":color("--gold"),"line-style":"dashed","opacity":.8}},
      {selector:"node.unobserved",style:{"background-opacity":.04,"border-color":color("--faint"),"border-style":"dashed","border-width":1.3,"color":color("--subtle")}},
      {selector:"node.event-focus",style:{"width":48,"height":48,"background-opacity":.5,"font-weight":"bold","font-size":12,"opacity":1}},
      {selector:"edge.event-focus",style:{"width":5,"opacity":1,"font-size":10}},
      {selector:".labels-hidden",style:{"label":""}}
    ];
  }
  function setGraph(graph, {merge = false, highlights = {}, truncated} = {}) {
    state.graph = merge ? mergeGraphs(state.graph, graph) : normalizeGraph(graph);
    if(truncated !== undefined) state.graph.truncated=truncated;
    remember([...state.graph.nodes, ...state.graph.edges]);
    if (cy) {
      const oldPositions = new Map(cy.nodes().map(n => [n.id(), n.position()]));
      const elements = buildElements(state.graph, idOf(state.selected), {...state.graph.highlights,...highlights});
      cy.elements().remove(); cy.add(elements);
      const preserve=(merge || state.mode==="replay") && oldPositions.size>0;
      if (preserve) cy.nodes().forEach(n => { if (oldPositions.has(n.id())) n.position(oldPositions.get(n.id())); });
      if(!state.graph.edges.length) cy.layout({name:"grid",fit:true,padding:32,avoidOverlap:true,nodeDimensionsIncludeLabels:true,condense:false,cols:Math.max(1,Math.ceil(Math.sqrt(state.graph.nodes.length*$("#graph").clientWidth/Math.max(180,$("#graph").clientHeight))))}).run();
      else cy.layout({name:"cose",animate:false,randomize:!preserve,fit:true,padding:state.mode==="replay"?18:40,nodeRepulsion:() => state.mode==="replay"?4000:10000,idealEdgeLength:() => state.mode==="replay"?65:105,edgeElasticity:() => 65,numIter:700,componentSpacing:45,gravity:.18}).run();
      cy.elements().toggleClass("labels-hidden", !$("#show-labels").checked);
    }
    const count = state.graph.nodes.length;
    $("#empty-stage").hidden = count > 0 || state.view === "table";
    $("#graph-summary").hidden = !count || state.view === "table";
    $("#graph-legend").hidden = !count || state.view === "table" || state.mode === "replay";
    $("#graph-summary").innerHTML = `${count.toLocaleString()} nodes <span aria-hidden="true">·</span> ${state.graph.edges.length.toLocaleString()} relationships${state.graph.truncated ? '<span class="bounded-note">Bounded view · expand to explore</span>' : ""}${graphTopologyNote(state.graph) ? `<span class="topology-note">${esc(graphTopologyNote(state.graph))}</span>` : ""}`;
    renderTable();
  }
  async function loadNeighborhood(id, merge = false, asRecord = false) {
    const requestVersion = ++state.graphVersion;
    $("#graph-loading").hidden = false;
    try {
      const filters = currentFilters(); delete filters.q; delete filters.type;
      const selected = state.cache.get(id), graphId = selected?.predicate && !asRecord ? idOf(selected.subject) : id;
      const key = neighborhoodPageKey(graphId, filters), previous = merge ? state.neighborhoodPages.get(key) : null;
      if (previous && previous.nextOffset === null) { setStatus("All matching relationships for this record are already loaded."); return; }
      const graph = await get("/api/graph", {id:graphId,depth:1,limit:150,offset:previous?.nextOffset || 0,...filters});
      if (requestVersion !== state.graphVersion || state.mode !== "graph") return;
      if (!merge) state.neighborhoodPages.clear();
      state.neighborhoodPages.set(key, {id:graphId,label:labelOf(state.cache.get(graphId) || {"@id":graphId}),nextOffset:graph.next_offset,total:graph.total});
      const truncated = [...state.neighborhoodPages.values()].some(page=>page.nextOffset != null);
      setGraph(graph, {merge, truncated}); renderNeighborhoodPages();
      setStatus(`${merge ? "Expanded" : "Showing"} a bounded neighborhood · Inspector reads do not create task events`);
    } finally { if (requestVersion === state.graphVersion) $("#graph-loading").hidden = true; }
  }

  function renderNeighborhoodPages() {
    const panel = $("#neighborhood-pages"), select = $("#neighborhood-page-select"), previous = select.value;
    const pages = [...state.neighborhoodPages.entries()].filter(([,page])=>page.nextOffset != null);
    panel.hidden = state.mode !== "graph" || !pages.length;
    select.innerHTML = pages.map(([key,page])=>`<option value="${esc(key)}">${esc(page.label)} · ${page.nextOffset} / ${page.total}</option>`).join("");
    if(pages.some(([key])=>key===previous)) select.value=previous;
  }

  async function setMode(mode, {autoLoad=true}={}) {
    if (!["graph","ontology","replay"].includes(mode)) return;
    const transition=++state.modeVersion;
    state.mode = mode; state.searchVersion++; state.graphVersion++; state.detailVersion++;
    state.neighborhoodPages.clear(); renderNeighborhoodPages();
    $("#graph-loading").hidden = true;
    $("#workspace").classList.toggle("replay",mode==="replay");
    $("#run-layer-filter").value=state.layer;
    $$("[data-layer]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.layer===state.layer)));
    stopReplay(); state.live = false;
    $$("[data-mode]").forEach(b => b.toggleAttribute("aria-current", b.dataset.mode === mode));
    $$("[data-mode]").forEach(b => { if (b.dataset.mode === mode) b.setAttribute("aria-current","page"); });
    $("#graph-filters").hidden = mode !== "graph";
    $("#ontology-filters").hidden = mode !== "ontology";
    $("#replay-filters").hidden = mode !== "replay";
    $("#graph-toolbar").hidden = mode === "ontology";
    $("#run-toolbar").hidden = mode !== "replay" || !state.run;
    $("#timeline").hidden = mode !== "replay" || !state.run;
    $("#capture-notice").hidden = mode !== "replay" || !state.run;
    $("#load-more").hidden = true;
    $("#search").value = "";
    $("#search").placeholder = mode === "ontology" ? "Find a class or relationship" : mode === "replay" ? "Find a task run" : "Find a polymer, source, or concept";
    $("#sidebar-eyebrow").textContent = mode === "ontology" ? "The shared vocabulary" : mode === "replay" ? "Research trajectories" : "Explore the collection";
    $("#stage-eyebrow").textContent = mode === "ontology" ? "Ontology reference" : mode === "replay" ? "Evidence-access trajectory" : "Evidence graph";
    $("#stage-title").textContent = mode === "ontology" ? "A vocabulary for polymer data" : mode === "replay" ? "Follow the research" : "Explore polymer knowledge";
    $("#stage-subtitle").textContent = mode === "ontology" ? "Definitions, constraints, and examples connect the vocabulary to its evidence-backed instances." : mode === "replay" ? "Inspect the evidence returned to an agent and the relationships it explicitly followed." : "Select a record to follow its relationships and inspect the supporting evidence.";
    $("#stage-hint").textContent = mode === "ontology" ? "Choose a definition · View its instances" : mode === "replay" ? "Observable access · No inferred reasoning paths" : "Click a record to inspect · Double-click a node to expand";
    $("#empty-stage").innerHTML = emptyMarkup;
    if (mode === "ontology") {
      state.selected = null; renderTerms(); setView("table");
      if (state.term) await selectTerm(idOf(state.term));
    } else if (mode === "replay") {
      setView("graph"); setGraph({nodes:[],edges:[]});
      await loadRuns();
      if(transition!==state.modeVersion)return;
      if (state.run) await openRun(state.run.run_id);
      else { $("#detail-panel").innerHTML = detailEmpty; setEmpty("No task selected", "Select a recorded run to inspect its evidence-access trajectory."); }
    } else {
      setView("graph");
      if(!autoLoad)return;
      await searchRecords();
      if(transition!==state.modeVersion)return;
      if (state.selected && state.cache.has(idOf(state.selected))) await selectRecord(idOf(state.selected));
      else if (state.records.length) await selectRecord(idOf(state.records[0]));
    }
    updatePlayback();
  }
  function setView(view) {
    state.view = view;
    $$("[data-view]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
    $("#graph").hidden = view !== "graph";
    $("#table-view").hidden = view !== "table";
    $("#empty-stage").hidden = view === "table" || state.graph.nodes.length > 0;
    $("#graph-summary").hidden = view === "table" || !state.graph.nodes.length;
    $("#graph-legend").hidden = view === "table" || !state.graph.nodes.length || state.mode === "replay";
    if (view === "table") renderTable(); else if (cy) { cy.resize(); cy.fit(undefined, 60); }
  }
  function setEmpty(title, text) {
    $("#empty-stage").innerHTML = `<svg viewBox="0 0 160 112" aria-hidden="true"><path d="M28 55 75 22 126 50 92 91 28 55"/><circle cx="28" cy="55" r="8"/><circle cx="75" cy="22" r="7"/><circle cx="126" cy="50" r="12"/><circle cx="92" cy="91" r="6"/></svg><h2>${esc(title)}</h2><p>${esc(text)}</p>`;
    $("#empty-stage").hidden = state.view === "table";
  }
  async function searchRecords(append = false) {
    if(state.mode !== "graph")return;
    const requestVersion = ++state.searchVersion;
    if (!append) $("#result-list").innerHTML = '<div class="loading-list"><span class="spinner"></span>Searching the local release</div>';
    const filters = currentFilters(), activeFilters = Object.values(filters).filter(Boolean).length - (filters.q ? 1 : 0);
    $("#filter-count").textContent = activeFilters ? `(${activeFilters})` : "";
    const result = await get("/api/search", {...filters,limit:50,offset:append ? state.records.length : 0});
    if (requestVersion !== state.searchVersion || state.mode !== "graph") return;
    state.records = append ? [...state.records,...list(result.records)] : list(result.records);
    state.total = result.total ?? state.records.length; remember(state.records);
    renderRecords();
    $("#load-more").hidden = state.records.length >= state.total;
    setStatus(`${state.total.toLocaleString()} matching records · ${state.meta.release?.release_id || "Local release"}`);
    if (!state.records.length) { state.neighborhoodPages.clear(); renderNeighborhoodPages(); setGraph({nodes:[],edges:[]}); setEmpty("No matching records", "Adjust the search or clear a filter to broaden the result."); }
    if (state.firstSearch && state.records.length) { state.firstSearch = false; await selectRecord(idOf(state.records[0])); }
  }
  function renderRecords() {
    $("#list-heading").textContent = "Records";
    $("#collection-count").textContent=state.meta.release?.counts?.PolymerConcept ? `${state.meta.release.counts.PolymerConcept} polymers` : "";
    $("#result-count").textContent = `${state.records.length} / ${state.total.toLocaleString()}`;
    $("#result-list").innerHTML = state.records.length ? state.records.map(record => `<button class="result-button ${idOf(state.selected) === idOf(record) ? "selected" : ""}" data-select-record="${esc(idOf(record))}"><span class="result-top"><span class="record-dot ${category(record)}"></span><strong>${esc(labelOf(record))}</strong></span><span class="result-meta"><span>${esc(humanize(typeOf(record)))}</span><span class="id">${esc(shortId(idOf(record)))}</span></span></button>`).join("") : '<div class="empty-list"><strong>No records found</strong>Try a broader term, an alias, or fewer filters.</div>';
  }
  async function selectRecord(id, {loadGraph = true} = {}) {
    if (!id) return;
    const version = ++state.detailVersion, mode=state.mode;
    let record = state.cache.get(id);
    if (state.mode === "replay" && state.run) {
      try {
        record = await get(`/api/runs/${encodeURIComponent(state.run.run_id)}/record`,{id,sequence:state.events[state.position]?.sequence || 0,agent:state.agent});
      } catch (error) {
        if (version!==state.detailVersion || mode!==state.mode) return;
        return jumpCitation(id,state.events[state.position]?.event_id);
      }
      if (typeOf(record)==="Unobserved") return jumpCitation(id,state.events[state.position]?.event_id);
    } else if (!record || record._partial) record = await get("/api/record", {id});
    else {
      // Graph nodes may contain only a display projection; retrieve the canonical record.
      try { record = await get("/api/record", {id}); } catch (error) { if (!record) throw error; }
    }
    if (version !== state.detailVersion || mode !== state.mode) return;
    remember(record);
    if(state.mode === "graph" && list(record.evidence).length) {
      try {const evidence=await get("/api/evidence",{id}); if(version !== state.detailVersion)return;remember(evidence.records);} catch { /* Preserve a usable canonical record if extra evidence lookup is unavailable. */ }
    }
    if(version !== state.detailVersion || mode !== state.mode)return;
    state.selected=record;renderRecordDetail(record);
    if (state.mode === "graph") {
      renderRecords();
      $("#stage-title").textContent = labelOf(record);
      $("#stage-subtitle").textContent = `${humanize(typeOf(record))} · ${shortId(idOf(record))} · Open a relationship to inspect its qualifiers and evidence.`;
      if (loadGraph) await loadNeighborhood(id);
      else if (cy) { cy.elements().removeClass("focus-node"); recordElements(cy,id).addClass("focus-node"); }
    }
  }
  function renderRecordDetail(record) {
    state.detailType="record";
    const id = idOf(record), isClaim = !!record.predicate && !!record.subject, term = termFor(isClaim ? record.predicate : list(record["@type"] || record.type)[0]);
    const context = record.context || record.qualifiers || {};
    const evidence = list(record.evidence || record.sources || record.supportingEvidence);
    const definitionId=isClaim ? record.predicate : list(record["@type"] || record.type)[0];
    const definitions = state.mode === "replay" && definitionId && definitionId!=="Unobserved" ? `<button class="secondary-button" data-run-term="${esc(definitionId)}">View definition ↗</button>` : term ? `<button class="secondary-button" data-term="${esc(idOf(term))}">View definition ↗</button>` : "";
    const sourceURL = safeURL(record.url || record.accessUrl || record.source_url || record.landingPage);
    const excluded = new Set(["@id","@type","id","type","label","name","title","status","layer","context","qualifiers","evidence","sources","supportingEvidence","history","revisions","seedRecord","originalRecord","v3000","molblock","molfile","subject","predicate","object","description","definition","sourceText","text","content","sections","canonicalMolfile"]);
    const fields = Object.entries(record).filter(([key]) => !excluded.has(key) && !key.startsWith("_")).map(([key,value]) => field(key,value)).join("");
    const description = record.description || record.definition || record.text || record.sourceText;
    $("#detail-panel").innerHTML = `<header class="detail-header"><span class="eyebrow">${isClaim ? "Scientific assertion" : esc(humanize(typeOf(record)))}</span><h2>${esc(labelOf(record))}</h2><div class="record-id">${esc(id)}</div><div class="detail-badges">${badges(record.status,record.layer,record.scope,record.maturity)}</div><div class="detail-actions">${definitions}${state.mode === "graph" ? `<button class="secondary-button" data-expand="${esc(id)}">Expand neighborhood</button>` : ""}${sourceURL ? `<a class="secondary-button" href="${esc(sourceURL)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : ""}</div></header>
      ${record.capture_note ? `<div class="scope-callout"><strong>Referenced endpoint only</strong>${esc(record.capture_note)}</div>` : ""}
      ${isClaim ? section("Relationship",`<div class="record-chain">${recordButton(record.subject)}<span class="relation-label">${esc(humanize(localName(record.predicate)))}</span>${recordButton(record.object)}</div>`) : ""}
      ${description ? section("Description",`<p>${esc(typeof description === "object" ? pretty(description) : description)}</p>`) : ""}
      ${Object.keys(context).length ? section("Scientific context",`<dl class="detail-fields">${Object.entries(context).map(([k,v])=>field(k,v)).join("")}</dl>`) : isClaim ? '<div class="scope-callout"><strong>Context has not been fully qualified.</strong>This relationship retains its seed or candidate scope. Missing conditions are unknown, not evidence of general applicability.</div>' : ""}
      ${evidence.length ? section(`Supporting evidence · ${evidence.length}`,evidence.map(item => {
        const eid = idOf(item), r = state.cache.get(eid);
        return `<div class="source-link">${eid ? recordButton(eid,labelOf(r || (typeof item === "object" ? item : {label:shortId(eid)}))) : renderValue(item)}${item.locator ? `<small>${esc(pretty(item.locator))}</small>` : ""}</div>`;
      }).join("")) : isClaim ? section("Supporting evidence",'<p class="muted">No atomic evidence link recorded. Inspect the seed record and its validation status before using this relationship as a scientific claim.</p>') : ""}
      ${fields ? section("Record details",`<dl class="detail-fields">${fields}</dl>`) : ""}
      ${record.sections ? section("Seed article sections", Object.entries(record.sections).map(([key,value])=>`<details class="raw-data"><summary>${esc(humanize(key))}</summary><p>${esc(pretty(value))}</p></details>`).join("")) : ""}
      ${section("Revision history",list(record.history || record.revisions).map(item=>`<div class="history-item"><time>${esc(item.timestamp || item.date || item.release_id || "")}</time><p>${esc(typeof item === "object" ? item.description || item.action || pretty(item) : item)}</p></div>`).join(""))}${raw(record)}`;
    $("#detail-panel").scrollTop=0;
  }

  function filteredTerms() {
    const q = $("#search").value.trim().toLowerCase(), kind = $("#term-kind").value;
    return state.terms.filter(t => (!kind || t.kind === kind) && (!q || `${labelOf(t)} ${idOf(t)} ${t.definition || ""}`.toLowerCase().includes(q)));
  }
  function renderTerms() {
    const terms = filteredTerms();
    $("#list-heading").textContent = "Definitions"; $("#result-count").textContent = terms.length;
    $("#collection-count").textContent = `${state.terms.length} terms`;
    $("#result-list").innerHTML = terms.length ? terms.map(t=>`<button class="result-button ${idOf(state.term) === idOf(t) ? "selected" : ""}" data-term="${esc(idOf(t))}"><span class="result-top"><span class="record-dot ${t.kind === "relation" ? "process" : ""}"></span><strong>${esc(labelOf(t))}</strong></span><span class="result-meta">${esc(t.kind === "relation" ? "Relationship" : "Entity class")} <span>· ${esc(t.status || "stable")}</span></span></button>`).join("") : '<div class="empty-list"><strong>No definitions found</strong>Try a broader concept or select all definition kinds.</div>';
    renderOntologyTable(terms);
    const displayed=new Map(terms.filter(t=>t.kind==="class").map(t=>[idOf(t),t]));
    terms.filter(t=>t.kind==="relation").forEach(t=>[...list(t.domain),...list(t.range)].forEach(id=>{const endpoint=termFor(idOf(id));if(endpoint)displayed.set(idOf(endpoint),endpoint);}));
    const classNodes = [...displayed.values()].map(t=>({"@id":idOf(t),"@type":"Concept",label:humanize(labelOf(t))}));
    const classIds = new Set(classNodes.map(idOf));
    const relationEdges = [];
    terms.filter(t=>t.kind === "relation").forEach(t=> list(t.domain).forEach(d=>list(t.range).forEach(r=> {
      if (classIds.has(idOf(d)) && classIds.has(idOf(r))) relationEdges.push({"@id":`${idOf(t)}:${idOf(d)}:${idOf(r)}`,subject:idOf(d),predicate:idOf(t),object:idOf(r),label:labelOf(t),status:t.status,layer:"ontology",definition:idOf(t)});
    })));
    setGraph({nodes:classNodes,edges:relationEdges});
    setStatus(`${terms.length} vocabulary definitions · Class and relationship constraints`);
  }
  async function selectTerm(id) {
    let term = termFor(id);
    if (!term) { const record = state.cache.get(id); if (record?.definition) term = termFor(record.definition); }
    if (!term) return;
    state.term = term;
    if (state.mode !== "ontology") { await setMode("ontology"); return; }
    renderTerms();
    const mappings = list(term.mappings).map(m=>typeof m === "string" ? renderValue(m) : `<div class="term-mapping">${renderValue(m.url || m["@id"] || m.target || m)}</div>`).join("<br>");
    $("#detail-panel").innerHTML = `<header class="detail-header"><span class="eyebrow">${term.kind === "relation" ? "Relationship definition" : "Entity class"}</span><h2>${esc(labelOf(term))}</h2><div class="record-id">${esc(idOf(term))}</div><div class="detail-badges">${badges(term.status || "stable",term.kind)}</div><div class="detail-actions"><button class="primary-button" data-instances="${esc(idOf(term))}">View instances ↗</button></div></header>${section("Definition",`<p>${esc(term.definition || "No definition recorded.")}</p>`)}${section("Constraints",`<dl class="detail-fields">${field("Allowed subjects",term.domain)}${field("Allowed objects",term.range)}${field("Required context",term.requiredContext || term.required_context)}</dl>`)}${list(term.examples).length ? section("Examples",`<ul>${list(term.examples).map(x=>`<li>${esc(pretty(x))}</li>`).join("")}</ul>`) : ""}${list(term.counterexamples).length ? section("Counterexamples",`<ul>${list(term.counterexamples).map(x=>`<li>${esc(pretty(x))}</li>`).join("")}</ul>`) : ""}${section("External mappings",mappings)}${section("Definition history",list(term.history).map(x=>`<div class="history-item">${esc(pretty(x))}</div>`).join(""))}${raw(term,"Complete definition")}`;
    $("#detail-panel").scrollTop=0;
  }
  async function showInstances(id) {
    const term = termFor(id); if (!term) return;
    state.selected = null; await setMode("graph",{autoLoad:false});
    const transition=state.modeVersion;clearFilters(false);
    if (term.kind === "relation") $("#predicate-filter").value = idOf(term);
    else {
      const select = $("#type-filter"), value = localName(idOf(term));
      if (![...select.options].some(o=>o.value===value)) select.add(new Option(labelOf(term),value));
      select.value = value;
    }
    await searchRecords();
    if(state.mode!=="graph" || transition!==state.modeVersion)return;
    if (state.records.length) await selectRecord(idOf(state.records[0]));
    if(state.mode!=="graph" || transition!==state.modeVersion)return;
    $("#stage-eyebrow").textContent = "Vocabulary instances";
    $("#stage-title").textContent = labelOf(term);
    $("#stage-subtitle").textContent = `${state.total.toLocaleString()} records using this ${term.kind === "relation" ? "relationship" : "class"}. Select a record to inspect its evidence.`;
  }
  function renderOntologyTable(terms) {
    $("#table-view").innerHTML = `<table class="ontology-table"><caption>Vocabulary definitions<span class="table-subtitle">Stable and experimental terms remain distinct.</span></caption><thead><tr><th scope="col">Term</th><th scope="col">Definition</th><th scope="col">Status</th></tr></thead><tbody>${terms.map(t=>`<tr><td><button class="inline-record" data-term="${esc(idOf(t))}">${esc(labelOf(t))}</button><span class="table-subtitle">${esc(t.kind === "relation" ? "Relationship" : "Entity class")}</span></td><td class="definition-cell">${esc(t.definition || "")}</td><td>${badges(t.status || "stable")}</td></tr>`).join("")}</tbody></table>`;
  }
  function renderTable() {
    if (state.mode === "ontology") { renderOntologyTable(filteredTerms()); return; }
    const graph = state.graph;
    if (!graph.nodes.length) { $("#table-view").innerHTML = '<div class="empty-list"><strong>No records in this view</strong>Select a record or a task event to populate the table.</div>'; return; }
    const nodeRows = graph.nodes.map(r=>`<tr><td>${recordButton(idOf(r),labelOf(r))}<span class="table-subtitle">${esc(shortId(idOf(r)))}</span></td><td>${esc(humanize(typeOf(r)))}</td><td>${badges(r.status || "seed")}</td></tr>`).join("");
    const edgeRows = graph.edges.map(r=>`<tr><td>${recordButton(idOf(r),humanize(localName(r.predicate)))}<span class="table-subtitle">${esc(shortId(idOf(r)))}</span></td><td>${recordButton(r.subject)} <span class="muted">→</span> ${recordButton(r.object)}</td><td>${badges(r.status || "seed")}<span class="table-subtitle">${esc(Object.keys(r.context || {}).length ? pretty(r.context) : "Context not recorded")}</span></td></tr>`).join("");
    $("#table-view").innerHTML = `${graph.truncated ? '<p class="table-filters-note">This is a bounded neighborhood. Expand a record to inspect additional connections.</p>' : ""}<table><caption>Records · ${graph.nodes.length}</caption><thead><tr><th scope="col">Record</th><th scope="col">Type</th><th scope="col">Status</th></tr></thead><tbody>${nodeRows}</tbody></table>${graph.edges.length ? `<table><caption>Directed relationships · ${graph.edges.length}</caption><thead><tr><th scope="col">Relationship</th><th scope="col">From → to</th><th scope="col">Scope &amp; status</th></tr></thead><tbody>${edgeRows}</tbody></table>` : ""}`;
  }

  async function loadRuns() {
    const result = await get("/api/runs"); state.runs = list(result.runs); if(state.mode==="replay")renderRuns();
  }
  function renderRuns() {
    const q = $("#search").value.trim().toLowerCase();
    const runs = state.runs.filter(r=>`${r.title || r.task?.title || ""} ${r.run_id} ${r.status}`.toLowerCase().includes(q));
    $("#list-heading").textContent = "Task runs"; $("#result-count").textContent = runs.length;
    $("#collection-count").textContent = `${state.runs.length} runs`;
    $("#result-list").innerHTML = runs.length ? runs.map(run=>`<button class="result-button ${state.run?.run_id === run.run_id ? "selected" : ""}" data-run="${esc(run.run_id)}"><span class="result-top"><span class="record-dot"></span><strong>${esc(run.title || run.task?.title || run.run_id)}</strong></span><span class="result-meta">Execution: ${esc(runStatusLabel(run))}</span><span class="result-excerpt outcome-label">${esc(runOutcomeLabel(run))}</span><span class="result-meta">${esc(shortId(run.run_id))}</span>${run.created_at ? `<span class="result-excerpt">${esc(dateLabel(run.created_at))}</span>` : ""}</button>`).join("") : '<div class="empty-list"><strong>No recorded runs yet</strong>Run a task through the instrumented Python, CLI, or MCP interface. Its trace will appear here.</div>';
  }
  async function openRun(runId) {
    stopReplay(); state.live = false; state.events = []; state.position = -1; state.agent = ""; state.artifacts = [];
    const version = ++state.runVersion;
    const [run, result, artifacts] = await Promise.all([get(`/api/runs/${encodeURIComponent(runId)}`),get(`/api/runs/${encodeURIComponent(runId)}/events`,{after:0}),get(`/api/runs/${encodeURIComponent(runId)}/artifacts`)]);
    if (version !== state.runVersion || state.mode !== "replay") return;
    state.run = run; state.events = list(result.events).sort((a,b)=>a.sequence-b.sequence); state.artifacts = list(artifacts.artifacts || artifacts);
    state.position = state.events.length - 1;
    $("#stage-title").textContent = run.title || run.task?.title || runId;
    $("#stage-subtitle").textContent = `Execution: ${runStatusLabel(run)} · ${runOutcomeLabel(run)} · ${state.events.length} recorded events`;
    $("#timeline").hidden = false; $("#run-toolbar").hidden = false; $("#capture-notice").hidden = false;
    renderCaptureNotice(); renderAgentOptions(); renderRuns(); updatePlayback(); renderTaskDetail();
    if (state.position >= 0) await selectEvent(state.position, {detail:false});
    else { setGraph({nodes:[],edges:[]}); setEmpty(isReplaySnapshot(run) ? "No events in this snapshot" : "Waiting for the first event", isReplaySnapshot(run) ? replayStatusNote(run) : "Follow live to see access events as the agent records them."); }
  }
  function renderCaptureNotice() {
    const capabilities = state.run?.capabilities || {}, caps = Array.isArray(capabilities) ? Object.fromEntries(capabilities.map(v=>[v,true])) : capabilities;
    const details = Object.entries(caps).filter(([,v])=>v===true).map(([key])=>humanize(key));
    const hasDelivery = Object.entries(caps).some(([k,v])=>v && /deliver/i.test(k));
    const incomplete = caps.complete !== true || caps.direct_access === false || caps.direct_file_access !== true || caps.external_source_access !== true || !hasDelivery;
    const gaps=[replayStatusNote(state.run),hasDelivery ? "Delivery confirmations are shown only when recorded." : "Model delivery is not confirmed.",
      caps.external_source_access === false || caps.external_web === false ? "External source access was not recorded." : caps.external_source_access !== true ? "External source capture is unspecified." : "",
      caps.direct_file_access === false ? "Direct file access was not recorded." : "",
      state.run?.inspectorSummary?.capture?.missingSourceContentCount ? `${state.run.inspectorSummary.capture.missingSourceContentCount} attached sources lack captured content.` : "",
      state.run?.inspectorSummary?.capture?.externalSourceCount ? "Source attachments and reviewer receipts do not establish observed access or model delivery." : ""].filter(Boolean);
    $("#capture-notice").classList.toggle("warning", incomplete);
    $("#capture-notice").innerHTML = `<strong>${incomplete ? "Capture limits visible." : "Instrumented access recorded."}</strong> ${esc(details.length ? details.join(" · ") : "This run did not declare its capture capabilities")}. ${esc(gaps.join(" "))}${state.run?.task?.notice ? `<p class="task-capture-notice">${esc(state.run.task.notice)}</p>` : ""}`;
  }
  function renderAgentOptions() {
    const agents = [...new Set([...list(state.run?.agents).map(a=>typeof a === "object" ? a.agent_id || a.id : a),...state.events.map(e=>e.agent_id || "agent")].filter(Boolean))];
    $("#agent-filter").innerHTML = '<option value="">All agents</option>' + agents.map(id=>`<option value="${esc(id)}">${esc(id)}</option>`).join("");
    $("#agent-filter").value = state.agent;
  }
  function visibleEvents() { return state.events.filter(event=>!state.agent || (event.agent_id || "agent") === state.agent); }
  function nextPosition(direction) {
    const indices=state.events.map((e,i)=>(!state.agent || (e.agent_id || "agent")===state.agent)?i:-1).filter(i=>i>=0);
    return direction>0 ? indices.find(i=>i>state.position) ?? -1 : indices.reverse().find(i=>i<state.position) ?? -1;
  }
  function trajectoryHighlights(events) {
    const flags = {returned:[],traversed:[],cited:[],delivered:[],"reviewer-supported":[],"reuse-tested":[],candidates:[]};
    events.forEach(event=>{
      const kind = eventKind(event), ids = eventRecordIds(event);
      if (kind === "returned" || kind === "traversed") flags.returned.push(...ids);
      if (kind === "delivered") flags.delivered.push(...ids);
      if (kind === "traversed") flags.traversed.push(...list(event.traversed_edges).map(idOf));
      if (kind === "cited") flags.cited.push(...ids);
      if (kind === "supported" || kind === "review") flags["reviewer-supported"].push(...ids);
      if (kind === "reuse-tested") flags["reuse-tested"].push(...ids);
      if (/propos|candidate/i.test(event.kind || event.operation || "")) flags.candidates.push(...ids);
    });
    Object.keys(flags).forEach(key=>flags[key]=[...new Set(flags[key])]); return flags;
  }
  async function selectEvent(position, {detail = true} = {}) {
    if (!state.run || !state.events.length) return;
    state.position = Math.max(0,Math.min(position,state.events.length-1));
    if(state.agent && (state.events[state.position].agent_id || "agent")!==state.agent) {
      const matches=state.events.map((e,i)=>(e.agent_id || "agent")===state.agent?i:-1).filter(i=>i>=0);
      if(!matches.length){setGraph({nodes:[],edges:[]});setEmpty("No events from this agent", "Select another agent or follow live for new events.");return;}
      state.position=matches.filter(i=>i<=state.position).at(-1) ?? matches[0];
    }
    const event = state.events[state.position], runId = state.run.run_id, version = ++state.graphVersion;
    updatePlayback();
    const graph = await get(`/api/runs/${encodeURIComponent(runId)}/graph`,{sequence:event.sequence,cumulative:state.cumulative,agent:state.agent,candidates:state.showCandidates});
    if (version !== state.graphVersion || state.mode !== "replay") return;
    const selectedEvents = (state.cumulative ? state.events.slice(0,state.position+1) : [event]).filter(e=>!state.agent || (e.agent_id || "agent")===state.agent);
    const highlights = trajectoryHighlights(selectedEvents);
    let filteredGraph = graph;
    if (!state.showCandidates) {
      // A candidate already present in a pinned preview is still an actually
      // returned record. Only newly proposed overlay identities are hidden.
      filteredGraph = hideProposalOverlays(graph);
    }
    if(state.layer) {
      const edges = list(filteredGraph.edges).filter(e=>e.layer===state.layer), endpoints=new Set(edges.flatMap(e=>[idOf(e.subject),idOf(e.object)]));
      filteredGraph={...filteredGraph,edges,nodes:list(filteredGraph.nodes).filter(n=>n.layer===state.layer || endpoints.has(idOf(n)))};
    }
    setGraph(filteredGraph,{highlights:{...highlights,...graph.highlights}});
    if (cy && event.kind==="access" && event.status==="ok") eventRecordIds(event).forEach(id=>recordElements(cy,id).addClass("event-focus"));
    if (!state.graph.nodes.length) setEmpty("No graph records at this point", "This event may record task lifecycle, a failed operation, or evidence without a graph record.");
    setStatus(`Event ${event.sequence} · ${humanize(event.operation || event.kind || "access")} · ${state.cumulative ? "Cumulative returned evidence" : "Selected event only"}`);
    if (detail) await renderEventDetail(event);
  }
  function updatePlayback() {
    const length = state.events.length, event = state.events[state.position];
    $("#timeline-scrubber").max = String(Math.max(0,length-1)); $("#timeline-scrubber").value = String(Math.max(0,state.position)); $("#timeline-scrubber").disabled = !length;
    $("#step-back").disabled = nextPosition(-1)<0; $("#step-next").disabled = nextPosition(1)<0; $("#play-pause").disabled = visibleEvents().length < 2;
    $("#play-pause").textContent = state.playing ? "Ⅱ" : "▶"; $("#play-pause").setAttribute("aria-label",state.playing ? "Pause replay" : "Play replay");
    $("#live-follow").disabled = isReplaySnapshot(state.run);
    $("#live-follow").title = replayStatusNote(state.run);
    $("#live-follow").setAttribute("aria-pressed",String(state.live));
    $("#event-position").textContent = event ? `Event ${event.sequence} / ${state.events[length-1].sequence}` : "No events";
    $("#event-clock").textContent = event ? timeLabel(event.timestamp) : "";
    const events = visibleEvents(), agents = [...new Set(events.map(e=>e.agent_id || "agent"))];
    $("#event-lanes").innerHTML = agents.map(agent=>`<div class="event-lane"><span class="lane-label" title="${esc(agent)}">${esc(agent)}</span><div class="lane-events">${events.filter(e=>(e.agent_id || "agent")===agent).map(e=>{
      const index=state.events.findIndex(x=>x.event_id===e.event_id), kind=eventKind(e);
      return `<button class="event-chip ${esc(kind)} ${index===state.position ? "selected" : ""} ${index>state.position ? "future" : ""}" data-event-position="${index}" aria-label="Event ${esc(e.sequence)}: ${esc(humanize(e.operation || e.kind || "access"))} by ${esc(agent)}" aria-pressed="${index===state.position}" title="${esc(`${e.sequence} · ${e.operation || e.kind} · ${kind}`)}"></button>`;
    }).join("")}</div></div>`).join("");
  }
  async function renderEventDetail(event) {
    state.detailType="event";
    const version=++state.detailVersion, runId=state.run.run_id, kind=eventKind(event);
    const notes = {returned:"This access operation returned the recorded payload, possibly with no matching records. Access alone does not establish support for a scientific conclusion.",traversed:"These edges were explicitly followed by a graph traversal. Other returned relationships are not inferred traversals.",cited:"The deliverable cited these records. Reviewer support is recorded separately.",supported:"The reviewer recorded a support finding. Inspect the linked claim, evidence, and judgment.",review:"Review recorded. Individual claims may pass, fail or remain uncertain; only records in passing findings receive a support highlight.",candidate:"Proposed changes are separate from released records. A proposal is neither a returned record nor an accepted scientific assertion.",attachment:"External source metadata and inspection receipts were attached. The adapter did not observe the source access or model delivery. Missing source content remains an explicit gap.",artifact:"An artifact was attached without citing graph records.",reuse:"A reuse evaluation was recorded without demonstrated benefit.",delivered:"The adapter recorded delivery into a model request. This does not establish continued presence in later context.","reuse-tested":"A subsequent evaluation recorded reuse of this evidence or research memory.",failed:"This operation failed. It remains in the trajectory without fabricated results.",lifecycle:"This event records task lifecycle or an artifact; it may not access any graph record."};
    const payloadHash = event.payload_hash || event.payload?.hash || event.payload_ref?.sha256 || event.payload_ref;
    $("#detail-panel").innerHTML = `<header class="detail-header"><span class="eyebrow">${event.kind === "access" ? "Access event" : "Recorded event"} ${esc(event.sequence)}</span><h2>${esc(humanize(event.operation || event.kind || "Recorded event"))}</h2><div class="record-id">${esc(event.event_id)}</div><div class="detail-badges">${badges(kind,event.status || event.outcome,event.agent_id)}</div></header><p class="event-note">${esc(notes[kind] || notes.lifecycle)}</p>${section("Operation",`<dl class="detail-fields">${field("Time",dateLabel(event.timestamp))}${field("Agent",event.agent_id)}${field("Duration",event.duration_ms != null ? `${event.duration_ms} ms` : event.duration)}${field("Causal parent",event.parent_event_id || event.parent_id || event.causal_parent)}${field("Graph release",event.release_id || state.run.release_id)}${field("Retrieval index",event.index_version || event.retrieval_index_version)}</dl>`)}${section("Request & filters",`<pre>${esc(pretty(event.request || {}))}</pre>`)}${eventRecordIds(event).length ? section("Returned or referenced records",eventRecordIds(event).map(id=>`<div class="source-link">${recordButton(id)}</div>`).join("")) : ""}${list(event.traversed_edges).length ? section("Explicitly traversed edges",list(event.traversed_edges).map(id=>`<div class="source-link">${recordButton(id)}</div>`).join("")) : ""}${event.truncated || event.pagination ? section("Completeness",`<div class="scope-callout">${event.truncated ? "The operation returned a truncated result. Unreturned records are not part of this access event." : ""}${event.pagination ? `<pre>${esc(pretty(event.pagination))}</pre>` : ""}</div>`) : ""}${section(event.kind === "access" ? "Exact returned payload" : "Exact recorded payload",`<div id="event-payload">${payloadHash ? '<p class="muted">Loading the recorded payload…</p>' : '<p class="muted">No payload was captured for this event.</p>'}</div>`)}${raw(event,"Complete trace event")}`;
    $("#detail-panel").scrollTop=0;
    if (payloadHash) {
      try {
        const payload = await get(`/api/runs/${encodeURIComponent(runId)}/payload`,{hash:payloadHash});
        if (version!==state.detailVersion) return;
        $("#event-payload").innerHTML = `<p class="record-id">${esc(payloadHash)}</p><pre>${esc(JSON.stringify(payload,null,2))}</pre>`;
      } catch (error) {
        if (version===state.detailVersion && $("#event-payload")) $("#event-payload").innerHTML = `<div class="scope-callout"><strong>Payload unavailable</strong>${esc(error.message)} This gap does not alter the recorded access event.</div>`;
      }
    }
  }
  function renderTaskDetail() {
    if (!state.run) return;
    state.detailType="task";
    const version=++state.detailVersion;
    const run=state.run, task=run.task || run.specification || {}, artifacts=state.artifacts;
    const {reviews,proposals,attachments,deliverables}=taskArtifactGroups(state.events,artifacts);
    const claimIndex=new Map(deliverables.flatMap(a=>list(a.claims).map(c=>[c.id || c["@id"],c])));
    const reviewHTML=reviews.map(a=>`<article class="artifact"><h3>${esc(a.title || "Independent review")}</h3>${badges(a.verdict ? `Reviewer-reported ${a.verdict}` : "")}${a.evaluation ? `<p class="event-note">${esc(evaluationLabel({evaluation:reviewEvaluation(a.evaluation)}))}. Individual claim findings below are separate.</p>${renderGrades(reviewEvaluation(a.evaluation))}` : ""}${renderReviewCoverage(a)}${list(a.findings).map(f=>{
      const claimId=f.claimId || f.claim_id || f.claim, claim=claimIndex.get(claimId);
      return `<div class="status-message">${badges(f.verdict)}<p class="record-id">${esc(claimId || "Unidentified claim")}</p>${claim ? `<p>${esc(claim.text || claim.claim || claim.statement || "")}</p>` : ""}${f.reason || f.rationale || f.explanation ? `<p>${esc(f.reason || f.rationale || f.explanation)}</p>` : ""}${list(f.citations).map(c=>citationButton(c,a.event_id)).join("")}</div>`;
    }).join("")}${list(a.notes).map(note=>`<p class="event-note">${esc(pretty(note))}</p>`).join("")}${raw(a,"Review artifact")}</article>`).join("");
    const proposalHTML=proposals.map(a=>`<article class="artifact"><h3>${esc(a.title || "Candidate proposal")}</h3><p class="muted small">${list(a.records).length} proposed records · isolated from the pinned release</p>${raw(a,"Proposal artifact")}</article>`).join("");
    const attachmentHTML=attachments.map(a=>`<article class="artifact"><h3>${esc(a.title || "External source evidence")}</h3><p class="event-note">${esc(a.capture_note)}</p>${list(a.records).map(r=>`<div class="source-link">${citationButton({record_id:idOf(r),label:labelOf(r)},a.event_id)}<small>${esc(pretty(r.locator || "No source locator recorded"))}</small><small>Source content: ${esc(a.content?.[idOf(r)]?.status || "unavailable")}</small></div>`).join("")}${raw(a,"Source metadata and inspection receipts")}</article>`).join("");
    const artifactHTML=deliverables.map((a,index)=>`<article class="artifact"><h3>${esc(a.title || a.name || a.kind || `Deliverable ${index+1}`)}</h3><div class="detail-badges">${badges(a.status,a.type)}</div>${a.text || a.content || a.body || a.answer ? `<div class="artifact-text">${esc(pretty(a.text || a.content || a.body || a.answer))}</div>` : ""}${renderClaimCards(a)}${list(a.citations).length ? `<p class="muted small">Artifact citations</p>${list(a.citations).map(c=>citationButton(c,a.event_id)).join("")}` : ""}${list(a.limitations).length ? `<div class="scope-callout"><strong>Limitations</strong>${list(a.limitations).map(x=>`<p>${esc(pretty(x))}</p>`).join("")}</div>` : ""}${raw(a,"Artifact record")}</article>`).join("");
    $("#detail-panel").innerHTML=`<header class="detail-header"><span class="eyebrow">Research task</span><h2>${esc(run.title || task.title || run.run_id)}</h2><div class="record-id">${esc(run.run_id)}</div><div class="detail-badges">${badges(`Execution: ${runStatusLabel(run)}`,run.capture_status)}${replayStatusNote(run) ? `<p class="event-note">${esc(replayStatusNote(run))}</p>` : ""}</div><div class="detail-actions"><a class="secondary-button" href="/api/runs/${encodeURIComponent(run.run_id)}/export" download>Export private replay ↗</a></div><p class="event-note">Private replay export includes task text and captured evidence. Review its contents and source rights before sharing.</p></header>${section("Outcome & observed retrieval",renderOutcomeSummary(run))}${section("Assigned publication inspection",renderPublicationInspection(run,artifacts))}${section("Task specification",renderTaskSpecification(run))}${section("Pinned context",`<dl class="detail-fields">${field("Graph release",run.release_id)}${field("Created",dateLabel(run.created_at))}${field("Execution finished",dateLabel(run.completed_at || run.finished_at))}${field("Capture capabilities",run.capabilities)}${field("Agents",run.agents)}</dl>`)}${section("Deliverables & claims",artifactHTML || '<p class="muted">No deliverable artifacts have been recorded yet.</p>')}${section("External sources & capture gaps",attachmentHTML)}${section("Claim findings & task review",reviewHTML || '<p class="muted">No validator findings recorded in this run.</p>')}${section("Proposed graph changes",proposalHTML || '<p class="muted">No proposed changes recorded. Proposals do not change the pinned release.</p>')}`;
    $("#detail-panel").scrollTop=0;
  }
  async function jumpCitation(recordId,eventId) {
    if (!recordId || !state.run) return;
    const access=resolveCitationAccess(state.events,recordId,eventId);
    const origin=state.events.find(e=>e.event_id===eventId);
    // Select the actual access, or the citing/attachment event for a gap. The
    // latter never receives an access label or an invented graph connection.
    const selected=access || origin;
    if (selected) {
      state.live=false;stopReplay();state.agent="";$("#agent-filter").value="";
      await selectEvent(state.events.indexOf(selected),{detail:false});
    }
    const version=++state.detailVersion;
    state.detailType="citation";
    const resolved=await get(`/api/runs/${encodeURIComponent(state.run.run_id)}/citation`,{id:recordId,event:eventId || undefined});
    if (version!==state.detailVersion) return;
    const record=resolved.record, attachments=list(resolved.attachments);
    if (cy && record) {
      cy.elements().removeClass("event-focus focus-node");
      recordElements(cy,recordId).addClass("event-focus focus-node");
    }
    const metadata=attachments.map(item=>{
      const r=item.record, sourceURL=safeURL(r.contentUrl || r.url), content=item.content || {};
      return `<article class="artifact"><h3>${esc(labelOf(r))}</h3><p class="record-id">Attached at event ${esc(item.sequence)} · ${esc(item.agent_id)}</p><dl class="detail-fields">${field("Source locator",r.locator)}${field("Access status",r.accessStatus)}${field("Reuse status",r.reuseStatus)}${field("Permission basis",r.permissionBasis)}</dl>${sourceURL ? `<a href="${esc(sourceURL)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : ""}<div class="scope-callout"><strong>Source content: ${esc(content.status || "unavailable")}</strong>${esc(content.reason || content.permission_basis || "")}</div>${content.status==="included" ? `<p class="record-id">Content SHA-256: ${esc(content.sha256)}</p><pre>${esc(content.text)}</pre>` : ""}${raw(r,"Exact attached metadata")}${raw(item.source_checks,"Matching inspection receipts")}${raw({payload_hash:item.payload_hash,event_id:item.event_id},"Attachment checksum and event")}</article>`;
    }).join("");
    $("#detail-panel").innerHTML=`<header class="detail-header"><span class="eyebrow">Citation evidence</span><h2>${esc(labelOf(record || attachments[0]?.record || {label:recordId}))}</h2><div class="record-id">${esc(recordId)}</div></header>${resolved.capture_gap ? `<div class="scope-callout"><strong>Access capture gap</strong>${esc(resolved.capture_gap)}</div>` : `<p class="event-note">Returned at access event ${esc(resolved.access_event.sequence)}. ${resolved.access_events.length} matching access event(s) were recorded before this citation.</p>${raw(resolved.access_event,"Supporting access event")}${raw(record,"Exact returned record")}`} ${section("Attached external evidence",metadata || '<p class="muted">No external source attachment is available at this point.</p>')}${list(resolved.findings).length ? section("Recorded claim judgments",list(resolved.findings).map(f=>`<div class="status-message">${badges(f.verdict)}<p>${esc(f.claimId || f.claim_id || f.claim || "")}</p>${f.reason || f.rationale ? `<p>${esc(f.reason || f.rationale)}</p>` : ""}</div>`).join("")) : ""}`;
    $("#detail-panel").scrollTop=0;
    if (access) setStatus(`Citation → evidence → access event ${access.sequence}`);
    else setStatus("Citation → attached evidence or explicit gap. No source access was recorded.");
  }
  function stopReplay() { clearInterval(state.timer);state.timer=null;state.playing=false;updatePlayback(); }
  function playReplay() {
    if (state.playing) { stopReplay(); return; }
    if (visibleEvents().length<2) return;
    state.live=false;state.playing=true;
    if (nextPosition(1)<0) state.position=-1;
    updatePlayback();
    let busy=false;
    state.timer=setInterval(async()=>{
      if (busy) return;
      if (nextPosition(1)<0) { stopReplay();return; }
      busy=true;
      try { await selectEvent(nextPosition(1)); } catch(e) {showError(e);stopReplay();} finally {busy=false;}
    },Number($("#replay-speed").value));
  }
  async function pollEvents() {
    if (!state.live || !state.run || isReplaySnapshot(state.run) || state.mode!=="replay" || state.pollBusy || document.hidden) return;
    state.pollBusy=true;
    const runId=state.run.run_id;
    try {
      const {result,run,artifacts}=await readLiveUpdate(get,runId,state.events.at(-1)?.sequence || 0);
      if (state.run?.run_id!==runId || !state.live) return;
      const metadataChanged=JSON.stringify(state.run)!==JSON.stringify(run);
      const showingTask=state.detailType==="task";
      state.run=run;
      if(artifacts) state.artifacts=list(artifacts.artifacts || artifacts);
      if (list(result.events).length) {
        const events=new Map(state.events.map(e=>[e.event_id,e])); result.events.forEach(e=>events.set(e.event_id,e));
        state.events=[...events.values()].sort((a,b)=>a.sequence-b.sequence);renderAgentOptions();
        await selectEvent(state.events.length-1,{detail:!showingTask});
      }
      if (state.run?.run_id!==runId || !state.live) return;
      $("#stage-subtitle").textContent=`Execution: ${runStatusLabel(run)} · ${runOutcomeLabel(run)} · ${state.events.length} recorded events`;
      if(metadataChanged) {
        state.runs=state.runs.map(item=>item.run_id===runId ? run : item);
        renderRuns();renderCaptureNotice();
      }
      if((metadataChanged || artifacts) && state.detailType==="task") renderTaskDetail();
    } catch(error) {showError(error);state.live=false;updatePlayback();} finally {state.pollBusy=false;}
  }

  function releaseId(release) {return release.release_id || release.id || "Unknown release";}
  function renderPairedGrades(quality) {
    if(!quality || !Object.keys(quality.scores || {}).length) return "";
    const labels={supportedCorrectness:"Supported correctness",qualificationPreservation:"Qualifications",citationSupport:"Citation support",completion:"Full research coverage",abstention:"Appropriate abstention"};
    const rows=Object.entries(labels).filter(([key])=>grade(quality.scores[key]?.baseline) && grade(quality.scores[key]?.candidate));
    return `<p class="event-note">${escapeHTML(quality.measuredPairs)} / ${escapeHTML(quality.expectedPairs ?? "?")} matched pairs · ${quality.calibrationRejected ? "Observed controls; calibration rejected" : quality.completeComparison ? "Complete comparison" : "Partial observations; no complete comparison"}. Scores are dimension-wise means on the 1–10 scale; baseline → candidate.</p><dl class="detail-fields">${rows.map(([key,label])=>`<div><dt>${escapeHTML(label)}</dt><dd>${grade(quality.scores[key].baseline)} → ${grade(quality.scores[key].candidate)}</dd></div>`).join("")}</dl>`;
  }
  /** Parity (run on demand with `oopc parity run`) and this week's loop numbers, for maintainers. */
  async function openLoopHealth() {
    $("#loop-health-dialog").showModal();
    const [parity, week] = await Promise.all([get("/api/parity").then(r => r.report).catch(() => null), get("/api/improvement").then(r => r.summary).catch(() => null)]);
    const pct = v => typeof v === "number" ? `${Math.round(v * 100)}%` : "—", num = v => Number.isFinite(v) ? Math.round(v).toLocaleString("en-US") : "—";
    const all = parity?.summary?.all || {}, covered = parity?.summary?.covered || {}, g = parity?.guardrail || {};
    const row = (label, direct, ontology) => `<tr><td>${esc(label)}</td><td>${esc(direct)}</td><td>${esc(ontology)}</td></tr>`;
    const of = (arm, key) => `${num(all[key]?.[arm])} of ${num(all.checked)}`;
    const parityHTML = parity ? `<p class="small">${g.holds === true ? "Within the parity guardrail." : g.holds === false ? "Outside the parity guardrail." : "Too few checked pairs to judge."} Run ${esc(parity.run)} on ${esc(parity.meta?.engine)}, checked by ${esc(parity.meta?.checker)}, prompt ${esc(parity.meta?.prompt || "—")}. Both arms checked in the same run. Eight questions: one or two either way is noise.</p>
      <table class="data-table"><thead><tr><th></th><th>Plain session</th><th>Ontology</th></tr></thead><tbody>
      ${row("Statements contradicted by their source", num(all.contradicted?.direct), num(all.contradicted?.ontology))}
      ${row("Complete answers", of("direct", "complete"), of("ontology", "complete"))}
      ${row("Answers giving a sourced result", of("direct", "resultsGiven"), of("ontology", "resultsGiven"))}
      ${row("Answers that passed the source check", of("direct", "passes"), of("ontology", "passes"))}
      ${row("Statements left uncertain for source access", num(all.accessUncertain?.direct), num(all.accessUncertain?.ontology))}
      ${row("Reported facts with a citation (median / lowest)", `${pct(all.medianCited?.direct)} / ${pct(all.minCited?.direct)}`, `${pct(all.medianCited?.ontology)} / ${pct(all.minCited?.ontology)}`)}
      ${row("Median new tokens", num(all.medianNewTokens?.direct), num(all.medianNewTokens?.ontology))}
      ${row("Web calls, covered questions (median)", num(covered.medianWebCalls?.direct), num(covered.medianWebCalls?.ontology))}</tbody></table>`
      : '<p class="muted small">No parity run yet. Run <code>oopc parity run --engine codex</code>; compare two runs with <code>oopc parity compare A B</code>.</p>';
    const w = week || {}, reviews = w.reviews || {}, spot = w.spotChecks || {};
    const weekHTML = `<dl class="detail-fields">${field("Answers this week", w.answered)}${field("Reused saved findings", w.reusedSavedFindings)}${field("Needed no web", w.answeredWithoutWeb)}${field("Median new tokens per answer", num(w.medianNewTokens))}${field("Reviews waiting / given up", `${num(reviews.waiting)} / ${num(reviews.givenUp)}`)}${field("Same-engine reviews", pct(reviews.sameEngineFraction))}${field("Sampled added findings rejected", spot.checked ? `${spot.unsupported} of ${spot.checked}` : "—")}${field("Checking share of new tokens", pct(w.loopCosts?.checkingTokenFraction))}</dl>`;
    $("#loop-health").innerHTML = `<h3>Parity</h3>${parityHTML}<h3>This week</h3>${weekHTML}`;
  }

  function openReleaseDialog() {
    const release=state.meta.release || {}, releases=list(state.meta.releases).length ? state.meta.releases : [release];
    $("#release-details").innerHTML=`<dl class="detail-fields">${field("Current release",releaseId(release))}${field("Created",release.created_at || release.created)}${field("Source snapshot",release.seed_sha256 || release.snapshot_sha256 || release.source_sha256)}${field("Record counts",release.counts)}</dl><p class="muted small">Task replays remain pinned to their original release. Comparing versions does not modify either release.</p>`;
    const options=releases.map(r=>`<option value="${esc(releaseId(r))}">${esc(releaseId(r))}</option>`).join("");
    $("#compare-from").innerHTML=options;$("#compare-to").innerHTML=options;
    $("#compare-to").value=releaseId(release);
    if(releases.length>1) $("#compare-from").value=releaseId(releases.find(r=>releaseId(r)!==releaseId(release)) || releases[0]);
    $("#diff-results").innerHTML=releases.length<2 ? '<p class="muted small">One release is available. Comparing it with itself will show no changes.</p>' : "";
    $("#release-dialog").showModal();
  }
  async function compareReleases() {
    $("#compare-releases").disabled=true;
    try {
      const result=await get("/api/diff",{from:$("#compare-from").value,to:$("#compare-to").value});
      const groups=["added","removed","changed"],count=value=>Array.isArray(value) ? value.length : typeof value==="number" ? value : Object.keys(value || {}).length;
      $("#diff-results").innerHTML=`<div class="diff-summary">${groups.map(k=>`<div><strong>${count(result[k])}</strong>${esc(humanize(k))}</div>`).join("")}</div><div class="diff-records">${groups.flatMap(k=>list(result[k]).filter(v=>typeof v!=="number").map(r=>`<div>${badges(k)}<span>${esc(typeof r === "string" ? r : r.label || idOf(r) || r.record_id || pretty(r))}</span></div>`)).join("")}</div>${raw(result,"Complete release comparison")}`;
    } finally {$("#compare-releases").disabled=false;}
  }
  function clearFilters(runSearch=true) {
    ["type","status","predicate","property","process","application","environment","source"].forEach(k=>$(`#${k}-filter`).value="");
    state.layer="";$$("[data-layer]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.layer==="")));
    if(runSearch) return filtersChanged();
  }
  async function filtersChanged() {await searchRecords(); if(state.selected && state.records.length) await loadNeighborhood(idOf(state.selected));}
  function setTheme(theme) {document.documentElement.dataset.theme=theme;localStorage.setItem("oopc-theme",theme);$("#theme-toggle").setAttribute("aria-label",`Switch to ${theme==="dark" ? "light" : "dark"} theme`);if(cy)cy.style(graphStyle());}
  function bindEvents() {
    $("#neighborhood-load-more").addEventListener("click",guard(async()=>{const page=state.neighborhoodPages.get($("#neighborhood-page-select").value);if(page)await loadNeighborhood(page.id,true,true);}));
    document.addEventListener("click",guard(async event=>{
      const target=event.target.closest("button,a");if(!target)return;
      if(target.dataset.mode) await setMode(target.dataset.mode);
      else if(target.dataset.view) setView(target.dataset.view);
      else if(target.hasAttribute("data-layer")) {state.layer=target.dataset.layer;$$("[data-layer]").forEach(b=>b.setAttribute("aria-pressed",String(b===target)));if(state.mode==="graph")await filtersChanged();else if(state.run)await selectEvent(state.position);}
      else if(target.dataset.selectRecord) await selectRecord(target.dataset.selectRecord);
      else if(target.dataset.record) await selectRecord(target.dataset.record,{loadGraph:state.mode==="graph"});
      else if(target.dataset.expand) await loadNeighborhood(target.dataset.expand,true);
      else if(target.dataset.term) await selectTerm(target.dataset.term);
      else if(target.dataset.runTerm) {
        const ontology=await get(`/api/runs/${encodeURIComponent(state.run.run_id)}/ontology`);
        const term=list(ontology.terms).find(t=>idOf(t)===target.dataset.runTerm);
        if(!term)throw new Error("This term is absent from the run's pinned ontology.");
        state.detailVersion++;
        state.detailType="term";
        $("#detail-panel").innerHTML=`<header class="detail-header"><span class="eyebrow">Pinned ontology definition</span><h2>${esc(labelOf(term))}</h2><div class="record-id">${esc(state.run.release_id)}</div>${badges(term.kind,term.status)}</header>${section("Definition",`<p>${esc(term.definition)}</p>`)}${section("Constraints",`<dl class="detail-fields">${field("Subjects",term.domain)}${field("Objects",term.range)}${field("Required context",term.requiredContext)}</dl>`)}${section("Examples",renderValue(term.examples))}${section("Counterexamples",renderValue(term.counterexamples))}${raw(term)}<button class="text-button" id="return-to-task">Return to task ↗</button>`;
        $("#return-to-task").addEventListener("click",renderTaskDetail);
      }
      else if(target.dataset.instances) await showInstances(target.dataset.instances);
      else if(target.dataset.run) await openRun(target.dataset.run);
      else if(target.hasAttribute("data-event-position")) {state.live=false;stopReplay();await selectEvent(Number(target.dataset.eventPosition));}
      else if(target.hasAttribute("data-citation")) await jumpCitation(target.dataset.citation,target.dataset.citationEvent);
      else if(target.hasAttribute("data-close-dialog")) target.closest("dialog").close();
    }));
    $("#search").addEventListener("input",()=>{clearTimeout(state.filterTimer);state.filterTimer=setTimeout(guard(async()=>{if(state.mode==="graph")await searchRecords();else if(state.mode==="ontology")renderTerms();else renderRuns();}),180);});
    ["type","status","predicate"].forEach(k=>$(`#${k}-filter`).addEventListener("change",guard(filtersChanged)));
    ["property","process","application","environment","source"].forEach(k=>$(`#${k}-filter`).addEventListener("input",()=>{clearTimeout(state.filterTimer);state.filterTimer=setTimeout(guard(filtersChanged),300);}));
    $("#term-kind").addEventListener("change",renderTerms);
    $("#clear-filters").addEventListener("click",guard(()=>clearFilters()));
    $("#load-more").addEventListener("click",guard(()=>searchRecords(true)));
    $("#refresh-runs").addEventListener("click",guard(loadRuns));
    document.addEventListener("oopc:open-task-run", guard(async event => {
      if (typeof event.detail !== "string") return;
      await setMode("replay"); await openRun(event.detail);
    }));
    $("#show-labels").addEventListener("change",()=>cy?.elements().toggleClass("labels-hidden",!$("#show-labels").checked));
    $("#fit-graph").addEventListener("click",()=>cy?.fit(undefined,65));
    $("#theme-toggle").addEventListener("click",()=>setTheme(document.documentElement.dataset.theme==="dark" ? "light" : "dark"));
    $("#release-button").addEventListener("click",openReleaseDialog);
    $("#loop-health-button").addEventListener("click",guard(openLoopHealth));
    $("#help-button").addEventListener("click",()=>$("#help-dialog").showModal());
    $("#compare-releases").addEventListener("click",guard(compareReleases));
    $("#error-dismiss").addEventListener("click",()=>$("#error-banner").hidden=true);
    $("#task-details").addEventListener("click",renderTaskDetail);
    $("#agent-filter").addEventListener("change",guard(async()=>{state.agent=$("#agent-filter").value;updatePlayback();await selectEvent(state.position);}));
    $("#run-layer-filter").addEventListener("change",guard(async()=>{state.layer=$("#run-layer-filter").value;await selectEvent(state.position);}));
    $("#fit-replay").addEventListener("click",()=>cy?.fit(undefined,18));
    $("#cumulative").addEventListener("change",guard(async()=>{state.cumulative=$("#cumulative").checked;await selectEvent(state.position);}));
    $("#candidate-overlay").addEventListener("change",guard(async()=>{state.showCandidates=$("#candidate-overlay").checked;await selectEvent(state.position);}));
    $("#step-back").addEventListener("click",guard(async()=>{state.live=false;stopReplay();await selectEvent(nextPosition(-1));}));
    $("#step-next").addEventListener("click",guard(async()=>{state.live=false;stopReplay();await selectEvent(nextPosition(1));}));
    $("#play-pause").addEventListener("click",playReplay);
    $("#replay-speed").addEventListener("change",()=>{if(state.playing){stopReplay();playReplay();}});
    $("#timeline-scrubber").addEventListener("input",guard(async()=>{state.live=false;stopReplay();await selectEvent(Number($("#timeline-scrubber").value));}));
    $("#live-follow").addEventListener("click",guard(async()=>{if(isReplaySnapshot(state.run))return;stopReplay();state.live=!state.live;updatePlayback();if(state.live){if(state.events.length)await selectEvent(state.events.length-1);await pollEvents();}}));
    document.addEventListener("keydown",event=>{if(event.key==="/" && !["INPUT","TEXTAREA","SELECT"].includes(document.activeElement?.tagName) && !$("dialog[open]")){event.preventDefault();$("#search").focus();}});
    $$("dialog").forEach(dialog=>dialog.addEventListener("click",event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}}));
    window.addEventListener("beforeunload",()=>clearInterval(state.timer));
    setInterval(pollEvents,1000);
  }
  async function init() {
    setTheme(localStorage.getItem("oopc-theme") || "light");bindEvents();initGraph();
    state.meta=await get("/api/meta");state.terms=list(state.meta.ontology?.terms || state.meta.terms);
    state.meta.releases=list(state.meta.releases);
    $("#release-label").textContent=state.meta.release?.release_id || "Local release";
    const counts=state.meta.release?.counts || {}, count=counts.polymers || counts.PolymerConcept || counts.PolymerFamily || counts.Polymer || counts.entities || counts.records;
    $("#collection-count").textContent=count ? `${Number(count).toLocaleString()} records` : "";
    const types=list(state.meta.types).length ? state.meta.types : state.terms.filter(t=>t.kind==="class").map(t=>({id:localName(idOf(t)),label:labelOf(t)}));
    $("#type-filter").innerHTML='<option value="">All types</option>'+types.map(t=>{const id=typeof t==="string" ? t : localName(idOf(t));return `<option value="${esc(id)}">${esc(typeof t==="string" ? humanize(t) : labelOf(t))}</option>`;}).join("");
    $("#predicate-filter").innerHTML='<option value="">All relationships</option>'+state.terms.filter(t=>t.kind==="relation").map(t=>`<option value="${esc(idOf(t))}">${esc(labelOf(t))}</option>`).join("");
    if (isCandidatePreview(state.meta.release)) {
      $(".local-badge").textContent="Candidate preview · Scientific review pending";
      $(".local-badge").title=state.meta.release.purpose;
      $("#status-filter").value="candidate";
      if (counts.Material) $("#type-filter").value="Material";
    }
    if (state.meta.replayOnly) {
      $("#release-label").textContent="Offline replay";
      $(".local-badge").textContent="Replay bundle · Pinned evidence";
      $$("[data-mode]").forEach(button=>{if(button.dataset.mode!=="replay")button.disabled=true;});
      $("#release-button").disabled=true;
      await setMode("replay");
      setStatus("Select an imported run to inspect its pinned evidence and timeline.");
    } else await searchRecords();
  }
  guard(init)();
})();
