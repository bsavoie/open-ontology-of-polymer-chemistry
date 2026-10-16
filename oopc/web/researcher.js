/* Researcher application: ask questions, read polymer records, see what the memory knows.
   Browsing issues read-only GETs and never creates agent trace events; only an explicit,
   authorized question starts work. */
(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Pure helpers (exported for tests)
  // ---------------------------------------------------------------------------
  const list = value => value == null ? [] : Array.isArray(value) ? value : [value];
  const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const safeURL = value => { try { const u = new URL(value); return ["https:", "http:"].includes(u.protocol) ? u.href : null; } catch { return null; } };
  const isCount = value => Number.isSafeInteger(value) && value >= 0;
  const formatCount = value => isCount(value) ? value.toLocaleString("en-US") : "—";
  const sum = values => values.every(isCount) ? values.reduce((a, b) => a + b, 0) : null;

  /** "mechanicalProperties" / "healthSafetyAndRegulation" / "open_sources" → sentence case. */
  function sentenceCase(key) {
    const words = String(key ?? "").replace(/[_-]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").trim().toLowerCase();
    return words ? words[0].toUpperCase() + words.slice(1) : "";
  }

  const sectionTitle = key => ({healthSafetyAndRegulation: "Health, safety and regulation"})[key] || sentenceCase(key);

  /** Minutes as "5 h 38 min" or "12 min". */
  function formatDuration(seconds) {
    if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "—";
    const minutes = Math.floor(seconds / 60), hours = Math.floor(minutes / 60);
    return hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`;
  }

  /** Inline markdown on raw text; every literal piece is escaped and only http(s) links survive. */
  function renderInline(text, options = {}) {
    const pattern = /(`[^`\n]+`)|\[([^\]\n]+)\]\(([^)\s]+)\)|\*\*([^*\n]+)\*\*|(?<![\w*])\*([^*\s][^*\n]*?)\*(?![\w*])/g;
    let html = "", last = 0, match;
    const source = String(text ?? "");
    while ((match = pattern.exec(source))) {
      html += escapeHTML(source.slice(last, match.index));
      last = pattern.lastIndex;
      if (match[1]) {
        const code = match[1].slice(1, -1), number = options.cite?.(code), record = !number && options.record?.(code);
        html += number ? citationLink(number) : record ? `<a href="${escapeHTML(record.href)}">${escapeHTML(record.label)}</a>` : `<code>${escapeHTML(code)}</code>`;
      } else if (match[2]) {
        const url = safeURL(match[3]), label = match[2];
        const cited = /^(evidence:[^\s,;]+)(.*)$/.exec(label), number = cited && options.cite?.(cited[1]);
        const inner = number ? `[${number}${escapeHTML(cited[2])}]` : renderInline(label, {...options, noLinks: true});
        html += url && !options.noLinks ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${inner}</a>` : inner;
      } else if (match[4]) html += `<strong>${renderInline(match[4], options)}</strong>`;
      else if (match[5]) html += `<em>${renderInline(match[5], options)}</em>`;
    }
    return html + escapeHTML(source.slice(last));
  }
  /** Polymer and section identifiers become readable links to the polymer page. */
  function recordReference(code, names = new Map()) {
    const polymer = /^(wop-\d{6})$/.exec(code), section = /^section:(wop-\d{6}):([A-Za-z]+)$/.exec(code);
    if (polymer) return {href: `#/polymers/${polymer[1]}`, label: names.get(polymer[1]) || polymer[1]};
    if (section) return {href: `#/polymers/${section[1]}`, label: `${names.get(section[1]) || section[1]} — ${sectionTitle(section[2]).toLowerCase()}`};
    return null;
  }
  const citationLink = number => `<a class="cite" href="#source-${number}" data-source="${number}">[${number}]</a>`;

  /** A small, safe markdown subset: headings, lists, tables and paragraphs. */
  function renderMarkdown(text, options = {}) {
    const lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    const cells = row => row.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      const heading = /^(#{1,4})\s+(.*)$/.exec(line);
      if (heading) { const level = Math.min(heading[1].length + 2, 5); out.push(`<h${level}>${renderInline(heading[2], options)}</h${level}>`); i++; continue; }
      if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] || "")) {
        const head = cells(line); i += 2;
        const body = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) body.push(cells(lines[i++]));
        out.push(`<div class="table-wrap"><table><thead><tr>${head.map(c => `<th scope="col">${renderInline(c, options)}</th>`).join("")}</tr></thead><tbody>${body.map(r => `<tr>${r.map(c => `<td>${renderInline(c, options)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      const bullet = /^\s*[-*]\s+/, numbered = /^\s*\d+[.)]\s+/;
      if (bullet.test(line) || numbered.test(line)) {
        const ordered = numbered.test(line), marker = ordered ? numbered : bullet, items = [];
        while (i < lines.length && marker.test(lines[i])) items.push(lines[i++].replace(marker, ""));
        out.push(`<${ordered ? "ol" : "ul"}>${items.map(item => `<li>${renderInline(item, options)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`);
        continue;
      }
      const paragraph = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,4})\s/.test(lines[i]) && !bullet.test(lines[i]) && !numbered.test(lines[i]) && !/^\s*\|.*\|\s*$/.test(lines[i])) paragraph.push(lines[i++]);
      out.push(`<p>${paragraph.map(p => renderInline(p, options)).join("<br>")}</p>`);
    }
    return out.join("");
  }

  /** One plain status per record or finding; imported seed drafts are never presented as reviewed. */
  function recordStatus(record) {
    const status = String(record?.status || "").toLowerCase();
    return ({
      "seed": {label: "Imported draft", tone: "neutral", note: "Imported from the Wiki of Open Polymer Data. Not yet independently reviewed; check the cited sources before relying on it."},
      "supported": {label: "Reviewed", tone: "good", note: "A separate reviewer checked this finding against its source and found it supported."},
      "accepted": {label: "Added", tone: "neutral", note: "Added on the research agent's judgement: it read this in the source. Not independently reviewed."},
      "unreviewed": {label: "Needs checking", tone: "warn", note: "The research agent was not fully confident in this finding; it is waiting for a separate reviewer. Treat it as a lead."},
      "uncertain": {label: "Needs checking", tone: "warn", note: "A reviewer could not confirm this finding from its source. Treat it as a lead."},
      "unsupported": {label: "Rejected", tone: "bad", note: "The reviewer found that the source does not support this finding. Researchers no longer see it."},
      "agent-validated": {label: "Source-reviewed", tone: "good", note: "Admitted after a separate review against its cited sources."},
      "candidate": {label: "Proposed", tone: "warn", note: "A proposed addition that has not been admitted."},
      "experimental": {label: "Experimental", tone: "warn", note: "Experimental content that has not been admitted."},
      "disputed": {label: "Disputed", tone: "bad", note: "Reviewers disagree about this content."},
      "superseded": {label: "Superseded", tone: "neutral", note: "Replaced by a newer record."},
    })[status] || {label: "Status unknown", tone: "neutral", note: "This record has no recorded review status."};
  }

  /** What is known about an answer's provenance, in researcher language. */
  function provenanceSummary(task) {
    if (!task?.result) return null;
    const deposit = task.deposit, counts = deposit?.counts || {}, reused = task.reusedFindings || {};
    const reusedCount = (reused.supported || 0) + (reused.added || 0);
    const reusedText = reusedCount > 0 ? ` It reused ${plural(reusedCount, "saved finding")}.` : "";
    if (task.origin === "legacy") return {label: "Earlier answer", tone: "neutral", note: "Answered before the current loop. Its reviewed findings were imported; the answer itself was not re-checked."};
    const known = deposit?.duplicates ? ` ${plural(deposit.duplicates, "finding")} ${deposit.duplicates === 1 ? "was" : "were"} already known and not saved again.` : "";
    if (!deposit || !deposit.findings) return {label: "Nothing new saved", tone: "neutral", note: "This answer cites its sources but found nothing new to save." + known + reusedText};
    const added = counts.accepted || 0, flagged = counts.unreviewed || 0, waiting = deposit.waitingReview || 0;
    const checked = [[counts.supported, "confirmed"], [counts.unsupported, "rejected"], [counts.uncertain, "inconclusive"]].filter(([n]) => n > 0);
    const parts = [];
    if (added) parts.push(`added ${plural(added, "finding")} on the research agent's judgement`);
    if (flagged) parts.push(`sent ${plural(flagged, "finding")} for review`);
    if (checked.length) parts.push(`a separate reviewer checked ${checked.reduce((n, [c]) => n + c, 0)}: ${checked.map(([n, w]) => `${n} ${w}`).join(", ")}`);
    const joined = parts.join("; "), note = joined ? joined[0].toUpperCase() + joined.slice(1) + "." : "";
    if (waiting && deposit.reviewStatus !== "failed") return {label: `${plural(waiting, "finding")} waiting for review`, tone: "neutral", note: note + known + reusedText};
    if (deposit.reviewStatus === "failed") return {label: "Review did not finish", tone: "warn", note: note + (deposit.reviewAttempts >= 2 ? " No automatic retries remain." : " One automatic retry remains.") + known + reusedText};
    return {label: added && !checked.length ? "Findings added" : "Findings saved", tone: counts.unsupported ? "warn" : "good", note: note + known + reusedText};
  }

  const reviewPending = task => !!task?.deposit?.waitingReview;

  /** Question progress for the answer view and history list. */
  function taskState(task) {
    const status = task?.status;
    if (status === "completed") return {label: "Answered", tone: "good", busy: false};
    if (status === "running") return {label: "Researching…", tone: "neutral", busy: true};
    if (status === "queued") return {label: "Waiting to start…", tone: "neutral", busy: true};
    if (status === "failed") return {label: "Could not finish", tone: "bad", busy: false};
    return {label: sentenceCase(status || "unknown"), tone: "neutral", busy: false};
  }

  /** Why a question failed, in researcher language. */
  function failureMessage(error) {
    const reason = error?.reason;
    return ({
      timeout: "The research reached its time limit before producing an answer. Try again with a longer limit or a narrower question.",
      quota: "Your subscription reached its usage limit. Try again after the usage window resets.",
      "rate-limited": "The engine was receiving too many requests and was still busy after a pause. Try again in a few minutes.",
      "not-signed-in": "The engine is not signed in. Connect it in Settings, then try again.",
      rejected: "The provider rejected the request. This is usually fixed by updating the app that provides the engine.",
      "invalid-output": "The engine finished without a usable answer, twice.",
      crashed: "The research session stopped unexpectedly, twice.",
      interrupted: "The research was interrupted, twice (for example, the app was closed).",
    })[reason] || error?.message || "The research stopped before it finished.";
  }

  const plural = (count, word) => `${formatCount(count)} ${word}${count === 1 ? "" : "s"}`;

  const DEPTHS = {quick: {label: "Quick", searches: 6, sources: 4}, standard: {label: "Standard", searches: 10, sources: 8},
                  thorough: {label: "Thorough", searches: 25, sources: 20}};
  const STAGES = [["knowledge", "Checking what we know"], ["web", "Reading sources"], ["writing", "Writing the answer"]];
  /** "2:05" for a running clock. */
  const formatClock = seconds => { const s = Math.max(0, Math.floor(Number(seconds) || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

  /** Live activity of a running question, from the worker's reported events. */
  function progressDetail(task, currentTime = Date.now()) {
    const p = task?.progress;
    if (!p) return null;
    const graph = p.graph || {}, web = p.web || {};
    const counts = {knowledge: graph.knowledge || 0, lookups: (graph.searches || 0) + (graph.records || 0) + (graph.vocabulary || 0),
                    hops: graph.hops || 0, searches: (web.searches || 0) + (web.unclassified || 0), pages: web.pages || 0,
                    sources: isCount(p.sourcesOpened) ? p.sourcesOpened : web.pages || 0};
    const action = String(p.lastAction || ""), lower = action.toLowerCase();
    const stage = lower.startsWith("writing") ? "writing"
      : /web|^reading/.test(lower) ? "web"
      : counts.searches + counts.pages ? "web" : "knowledge";
    const activity = {knowledge: counts.knowledge + counts.lookups, web: counts.searches + counts.pages, writing: 0};
    const at = STAGES.findIndex(([key]) => key === stage);
    const stages = STAGES.map(([key, label], index) => ({key, label,
      state: index === at ? "current" : index > at ? "pending" : activity[key] ? "done" : "skipped"}));
    const recorded = Number(p.elapsedSeconds) || 0, started = Date.parse(p.startedAt);
    const elapsed = task.status === "running" && Number.isFinite(started) ? Math.max(recorded, (currentTime - started) / 1000) : recorded;
    const limit = Number(p.budgetSeconds) || Number(task.budgetSeconds) || 0;
    return {stage, stages, action, counts, sites: (p.sites || []).slice(0, 8), clock: formatClock(elapsed),
            limit: limit ? formatDuration(limit) : "", percent: limit ? Math.min(100, Math.round(elapsed / limit * 100)) : 0,
            budget: DEPTHS[task.depth] || null, depth: DEPTHS[task.depth]?.label || ""};
  }

  /** Effort a finished answer took, from its retained worker result. Missing counts stay missing. */
  function effortStats(effort) {
    if (!effort) return [];
    const known = values => values.filter(v => v !== null && v !== undefined);
    const tokens = known([effort.inputTokens, effort.outputTokens]);
    const stats = [
      {value: effort.knowledgeLookups, label: "knowledge lookups"},
      {value: effort.graphLookups || null, label: "ontology lookups"},  // Only answers from before 2026-10-02 used the graph.
      {value: effort.webSearches, label: "web searches"},
      {value: effort.pagesRead, label: "pages read"},
      {value: tokens.length ? sum(tokens) : null, label: "tokens"},
    ].filter(item => isCount(item.value));
    if (effort.unclassifiedWebCalls > 0) stats.push({value: effort.unclassifiedWebCalls, label: "web calls (type not reported)"});
    return stats;
  }

  /** The loop in numbers: asked, saved, reviewed, reused. Unknown counts stay unknown. */
  function knowledgeSummary(loop) {
    const k = loop?.knowledge || {}, f = k.findings || {}, reuse = loop?.reuse || {};
    const reviewed = sum([f.supported || 0, f.unsupported || 0, f.uncertain || 0]);
    const saved = sum([reviewed, f.unreviewed || 0, f.accepted || 0]);
    const stages = [
      {key: "ask", title: "Ask", value: reuse.answered ?? null, text: "questions answered"},
      {key: "deposit", title: "Save", value: saved, text: `findings saved from answers${f.accepted ? ` · ${formatCount(f.accepted)} added on the research agent's judgement` : ""}`},
      {key: "review", title: "Review", value: reviewed, text: `findings checked by a separate reviewer${k.pendingReviews ? ` · ${plural(k.pendingReviews, "answer")} waiting` : ""}`},
      {key: "reuse", title: "Reuse", value: reuse.citingReviewed ?? null, text: "answers that cited saved findings"},
    ];
    const supported = f.supported || 0, accepted = f.accepted || 0;
    const usable = supported + accepted;
    const headline = usable ? `${plural(usable, "finding")} ${usable === 1 ? "is" : "are"} available to every new question${supported && accepted ? ` (${formatCount(supported)} reviewed, ${formatCount(accepted)} added)` : ""}.`
      : "Nothing saved yet. Ask a question to start the knowledge base.";
    const spot = loop?.spotChecks || {};
    const spotText = spot.checked ? `Spot checks: a reviewer also checked a sample of ${plural(spot.checked, "added finding")}; ${formatCount(spot.unsupported)} ${spot.unsupported === 1 ? "was" : "were"} rejected (${Math.round((spot.unsupportedRate || 0) * 100)}%)${spot.uncertain ? ` and ${formatCount(spot.uncertain)} inconclusive` : ""}.`
      : "";
    return {headline, stages, supported, accepted, unsupported: f.unsupported || 0, uncertain: f.uncertain || 0,
            unreviewed: f.unreviewed || 0, pending: k.pendingReviews || 0, notes: k.notes || 0, spotText};
  }



  /** Parse the parts of an MDL V3000 molfile needed for drawing annotations. */
  function parseMolfile(text) {
    const raw = String(text ?? "").split(/\r?\n/), lines = [];
    for (let i = 0; i < raw.length; i++) {
      let line = raw[i];
      while (line.startsWith("M  V30 ") && line.endsWith("-") && i + 1 < raw.length) line = line.slice(0, -1) + raw[++i].replace(/^M {2}V30 /, "");
      lines.push(line);
    }
    const atoms = [], sgroups = [];
    let section = null;
    for (const line of lines) {
      if (!line.startsWith("M  V30 ")) continue;
      const body = line.slice(7).trim();
      if (body.startsWith("BEGIN ")) { section = body.split(/\s+/)[1]; continue; }
      if (body.startsWith("END ")) { section = null; continue; }
      if (section === "ATOM") {
        const parts = body.split(/\s+/), rgroup = /RGROUPS=\(\d+\s+(\d+)/.exec(body);
        atoms.push({element: parts[1], x: Number(parts[2]), y: Number(parts[3]), rgroup: rgroup ? Number(rgroup[1]) : null});
      } else if (section === "SGROUP") {
        const parts = body.split(/\s+/);
        if (parts.length < 3) continue;
        const numbers = key => { const m = new RegExp(`${key}=\\(([^)]*)\\)`).exec(body); return m ? m[1].trim().split(/\s+/).map(Number).slice(1) : []; };
        const brackets = [...body.matchAll(/BRKXYZ=\(([^)]*)\)/g)].map(m => m[1].trim().split(/\s+/).map(Number).slice(1)).filter(v => v.length >= 6).map(v => [v[0], v[1], v[3], v[4]]);
        const label = /LABEL=("([^"]*)"|\S+)/.exec(body);
        sgroups.push({type: parts[1], atoms: numbers("ATOMS").map(n => n - 1), brackets, label: label ? (label[2] ?? label[1]) : ""});
      }
    }
    return {atoms, sgroups};
  }

  /** Fit pixel = s·(x, −y) + t from molfile to drawn atom positions; null when it does not fit. */
  function fitTransform(points, pixels) {
    const n = Math.min(points.length, pixels.length);
    if (n < 2) return null;
    const axis = (u, v) => {
      const mu = u.reduce((a, b) => a + b, 0) / n, mv = v.reduce((a, b) => a + b, 0) / n;
      let cov = 0, variance = 0;
      for (let i = 0; i < n; i++) { cov += (u[i] - mu) * (v[i] - mv); variance += (u[i] - mu) ** 2; }
      return variance > 1e-9 ? {s: cov / variance, mu, mv} : null;
    };
    const x = axis(points.slice(0, n).map(p => p.x), pixels.slice(0, n).map(p => p.x));
    const y = axis(points.slice(0, n).map(p => -p.y), pixels.slice(0, n).map(p => p.y));
    const scale = x?.s ?? y?.s;
    if (!scale || scale <= 0 || (x && y && Math.abs(x.s - y.s) > 0.03 * Math.abs(scale))) return null;
    const transform = {s: scale, tx: x ? x.mv - scale * x.mu : pixels[0].x - scale * points[0].x, ty: y ? y.mv - scale * y.mu : pixels[0].y + scale * points[0].y};
    for (let i = 0; i < n; i++) {
      if (Math.hypot(scale * points[i].x + transform.tx - pixels[i].x, -scale * points[i].y + transform.ty - pixels[i].y) > 2) return null;
    }
    return transform;
  }

  /** Repeat-unit bracket polylines in pixel space, with serifs turned toward the repeat unit. */
  function bracketGeometry(sgroup, atoms, transform) {
    if (!transform || !sgroup.brackets.length) return null;
    const map = (x, y) => ({x: transform.s * x + transform.tx, y: -transform.s * y + transform.ty});
    const members = sgroup.atoms.map(i => atoms[i]).filter(Boolean);
    const centre = members.length ? map(members.reduce((a, p) => a + p.x, 0) / members.length, members.reduce((a, p) => a + p.y, 0) / members.length) : null;
    const brackets = sgroup.brackets.map(([x1, y1, x2, y2]) => {
      const a = map(x1, y1), b = map(x2, y2), length = Math.hypot(b.x - a.x, b.y - a.y) || 1;
      let nx = -(b.y - a.y) / length, ny = (b.x - a.x) / length;
      const mid = {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2};
      if (centre && (centre.x - mid.x) * nx + (centre.y - mid.y) * ny < 0) { nx = -nx; ny = -ny; }
      const serif = Math.max(4, Math.min(8, length * 0.18));
      return {points: [[a.x + nx * serif, a.y + ny * serif], [a.x, a.y], [b.x, b.y], [b.x + nx * serif, b.y + ny * serif]], a, b};
    });
    const last = brackets.reduce((best, item) => Math.max(item.a.x, item.b.x) > Math.max(best.a.x, best.b.x) ? item : best, brackets[0]);
    const low = last.a.y > last.b.y ? last.a : last.b;
    return {brackets: brackets.map(item => item.points), label: sgroup.label ? {text: sgroup.label, x: low.x + 3, y: low.y + 10} : null};
  }

  /** Crop a drawing to its content, keeping a minimum size so small molecules are not over-enlarged. */
  function croppedViewBox(points, {width, height, pad = 18, minWidth = 170, minHeight = 90} = {}) {
    if (!points.length) return `0 0 ${width} ${height}`;
    const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
    let x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
    if (x1 - x0 < minWidth) { const grow = (minWidth - (x1 - x0)) / 2; x0 -= grow; x1 += grow; }
    if (y1 - y0 < minHeight) { const grow = (minHeight - (y1 - y0)) / 2; y0 -= grow; y1 += grow; }
    return [x0, y0, x1 - x0, y1 - y0].map(v => v.toFixed(1)).join(" ");
  }

  const RUNTIME_LABELS = {"codex": "ChatGPT (Codex)", "claude-code": "Claude Code"};
  const LOGIN_HOSTS = {"codex": ["auth.openai.com", "auth0.openai.com", "chatgpt.com"], "claude-code": ["claude.ai", "claude.com", "console.anthropic.com", "platform.claude.com"]};
  /** Only the provider's own https sign-in pages become links. */
  function loginLink(value, runtime) {
    try {
      const url = new URL(value);
      return url.protocol === "https:" && (LOGIN_HOSTS[runtime] || []).includes(url.hostname) && !url.username && !url.password && !url.port ? url.href : null;
    } catch { return null; }
  }
  const runtimeLabel = runtime => RUNTIME_LABELS[runtime] || RUNTIME_LABELS.codex;

  const api = {progressDetail, formatClock, effortStats, failureMessage, quotaHint, loginLink, runtimeLabel, croppedViewBox, sectionTitle, escapeHTML, safeURL, sentenceCase, recordReference, formatDuration, formatCount, renderInline, renderMarkdown, recordStatus, provenanceSummary, reviewPending, taskState, knowledgeSummary, parseMolfile, fitTransform, bracketGeometry};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;

  // ---------------------------------------------------------------------------
  // Browser application
  // ---------------------------------------------------------------------------
  const $ = selector => document.querySelector(selector);
  const view = $("#view");
  const state = {routeToken: 0, csrf: "", status: null, account: null, pending: null, polymers: null, polymerQuery: "", timers: new Set(), meta: null};

  async function get(path, params = {}) {
    const url = new URL(path, location.origin);
    for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
    const response = await fetch(url, {headers: {Accept: "application/json"}, cache: "no-store"});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    if (data.csrfToken) state.csrf = data.csrfToken;
    return data;
  }
  async function post(path, body) {
    const response = await fetch(path, {method: "POST", cache: "no-store", headers: {"Content-Type": "application/json", "X-OOPC-CSRF": state.csrf}, body: JSON.stringify(body)});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(data.error || "The request could not be completed"), {data});
    if (data.csrfToken) state.csrf = data.csrfToken;
    return data;
  }
  function showError(error) {
    $("#error-message").textContent = error?.message || String(error || "");
    $("#error-banner").hidden = !error;
  }
  const badge = (info, extra = "") => info ? `<span class="badge ${escapeHTML(info.tone)}" ${extra}>${escapeHTML(info.label)}</span>` : "";
  const dateLabel = value => { const d = new Date(value); return Number.isNaN(d.valueOf()) ? "" : d.toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"}); };
  function later(token, fn, ms) {
    const id = setTimeout(() => { state.timers.delete(id); if (token === state.routeToken) fn(); }, ms);
    state.timers.add(id);
  }

  // ----- Routing -----
  const TABS = ["ask", "polymers", "knowledge", "history"];
  function route() {
    state.routeToken++;
    for (const id of state.timers) clearTimeout(id);
    state.timers.clear();
    showError(null);
    const [section = "ask", id] = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
    const tab = TABS.includes(section) ? section : "ask";
    for (const link of document.querySelectorAll(".tabs a")) {
      if (link.dataset.tab === tab) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    }
    const token = state.routeToken;
    const render = {ask: () => id ? renderAnswer(id, token) : renderAsk(token), polymers: () => renderPolymers(id, token), knowledge: () => renderKnowledge(token), history: () => renderHistory(token)}[tab];
    Promise.resolve(render()).catch(error => { if (token === state.routeToken) showError(error); });
    window.scrollTo(0, 0);
  }

  // ----- Ask -----
  async function loadTaskStatus() {
    const [status, runtimes] = await Promise.all([get("/api/tasks/status"), get("/api/runtimes").catch(() => null)]);
    state.status = status; state.runtimes = runtimes;
    state.account = runtimes?.runtimes?.[runtimes.selected]?.account || {status: "error"};
    return {status, runtimes};
  }
  const selectedRuntime = () => state.runtimes?.selected || "codex";
  function readiness() {
    const {status, account} = state, label = runtimeLabel(selectedRuntime());
    if (!status || !account || account.status === "checking") return {ready: false, message: `Checking your ${label} connection…`};
    if (account.status === "login-pending") return {ready: false, message: `Finish signing in to ${label} to ask questions.`, action: "settings"};
    if (account.status !== "connected") return {ready: false, message: account.status === "unavailable" || account.status === "unsupported" ? `${account.message || `${label} is unavailable.`} Choose another engine in Settings.` : `Connect your ${label} account to ask questions.`, action: "settings"};
    if (!status.available) return {ready: false, message: status.reason || "Questions are unavailable right now."};
    return {ready: true, message: status.queued ? `${plural(status.queued, "question")} ahead of yours.` : `Runs on ${label}.`};
  }

  // Pre-submit hint only; the engine enforces its own limits.
  function quotaHint(quota, reserve, label) {
    if (!quota) return "";
    if (typeof quota.remainingPercent !== "number") return quota.reason === "unrecognized-report" ? `${label} usage could not be read (its usage report changed format).` : "";
    const left = `${label} has ${Math.round(quota.remainingPercent)}% of its usage window left`;
    return typeof reserve === "number" && quota.remainingPercent < reserve ? `${left}; background review waits until it is above ${reserve}%.` : `${left}.`;
  }

  async function renderAsk(token) {
    view.innerHTML = `
      <section class="ask">
        <h1>Ask the polymer memory</h1>
        <p class="lede">The research agent reads saved findings first, uses open sources for the rest, and cites every reported fact. Values read directly in a source are added on the researcher’s judgement; figure readings, conversions and combined values go to a separate reviewer. Later questions read reviewed and added knowledge first.</p>
        <form id="ask-form" class="ask-form" novalidate>
          <label class="visually-hidden" for="question">Your question</label>
          <textarea id="question" rows="5" minlength="10" maxlength="8000" required placeholder="e.g. How does annealing temperature affect the tensile modulus of PLA films? Keep specimen and test conditions explicit."></textarea>
          <div class="ask-options">
            <label>Depth<select id="depth"><option value="quick">Quick · up to 5 min, ~4 sources</option><option value="standard" selected>Standard · up to 10 min, ~8 sources</option><option value="thorough">Thorough · up to 20 min, ~20 sources</option></select></label>
            <p class="depth-note muted small">Depth sets the time and source budget. Reading another section of the same source does not count as a new source, but still uses tokens. The agent may go slightly over to finish an answer.</p>
          </div>
          <p id="budget-text" class="muted small"></p>
          <div class="ask-actions"><button id="ask-submit" class="primary-button" type="submit" disabled>Ask</button><p id="ask-readiness" class="muted small" role="status"></p></div>
          <p id="ask-quota" class="muted small" role="status" hidden></p>
          <p id="ask-error" class="inline-error" role="alert" hidden></p>
        </form>
      </section>
      <section class="recent" aria-labelledby="recent-title"><div class="section-heading"><h2 id="recent-title">Recent questions</h2><a href="#/history">See all</a></div><div id="recent-list" class="task-list"><p class="muted">Loading…</p></div></section>`;
    const form = $("#ask-form"), submit = $("#ask-submit");
    const budgetText = () => {
      const depth = DEPTHS[$("#depth").value], minutes = {quick: 5, standard: 10, thorough: 20}[$("#depth").value];
      $("#budget-text").textContent = `Runs on your ${runtimeLabel(selectedRuntime())} subscription: up to ${minutes} minutes, about ${depth.searches} web searches and ${depth.sources} sources. What it finds is saved to your local knowledge.`;
    };
    const update = () => {
      budgetText();
      const ready = readiness();
      $("#ask-readiness").innerHTML = escapeHTML(ready.message) + (ready.action === "settings" ? ` <button type="button" class="text-button" data-open-settings>Open settings</button>` : "");
      submit.disabled = !ready.ready || $("#question").value.trim().length < 10 || state.submitting;
    };
    if (state.prefill) { $("#question").value = state.prefill.question; state.prefill = null; }
    state.updateAsk = () => { if (token === state.routeToken) update(); };
    form.addEventListener("input", () => { state.pending = null; update(); });
    $("#depth").addEventListener("change", budgetText);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (submit.disabled) return;
      const error = $("#ask-error"); error.hidden = true;
      state.submitting = true; update();
      state.pending ||= {taskId: crypto.randomUUID().replaceAll("-", ""), question: $("#question").value.trim(),
        depth: $("#depth").value, authorizeSubscription: true, runtime: selectedRuntime()};
      try {
        const task = await post("/api/tasks", state.pending);
        state.pending = null;
        location.hash = `#/ask/${encodeURIComponent(task.taskId)}`;
      } catch (err) {
        const choice = err.data?.clarify?.[0];
        error.innerHTML = escapeHTML(err.message) + (choice ? " " + choice.options.map((option, index) =>
          `<button type="button" class="text-button" data-clarify="${index}">${escapeHTML(option.label)}</button>`).join(" ") : "");
        error.hidden = false;
        // Choosing names the polymer in the question; asking again then runs it.
        error.querySelectorAll("[data-clarify]").forEach(button => button.addEventListener("click", () => {
          const option = choice.options[Number(button.dataset.clarify)], field = $("#question");
          const pattern = new RegExp(`(^|[^\\w-])(${choice.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})(?![\\w-])`, "i");
          field.value = field.value.replace(pattern, (match, before, name) => `${before}${name} (${option.label.toLowerCase()})`);
          state.pending = null; error.hidden = true; update(); submit.focus();
        }));
      }
      finally { state.submitting = false; if (token === state.routeToken) update(); }
    });
    update();
    const refresh = async () => {
      try { await loadTaskStatus(); } catch { state.status = {available: false, reason: "Availability could not be checked."}; state.account ||= {status: "error"}; }
      if (token !== state.routeToken) return;
      update();
      if (["checking", "login-pending"].includes(state.account?.status)) later(token, refresh, 1500);
    };
    await refresh();
    state.refreshAskQuota = async () => {
      if (token !== state.routeToken) return;
      const hint = $("#ask-quota");
      hint.hidden = true;
      try {
        const quota = await get("/api/runtimes/quota");
        if (token !== state.routeToken || quota.runtime !== selectedRuntime()) return;
        hint.textContent = quotaHint(quota, undefined, runtimeLabel(quota.runtime));
        hint.hidden = !hint.textContent;
      } catch { /* A hint only. */ }
    };
    state.refreshAskQuota();
    const listing = await get("/api/tasks").catch(() => ({tasks: []}));
    if (token !== state.routeToken) return;
    $("#recent-list").innerHTML = listing.tasks.length ? listing.tasks.slice(0, 5).map(taskRow).join("") : `<p class="muted">Questions you ask will appear here.</p>`;
  }
  function taskRow(task) {
    const status = taskState(task);
    const origin = task.origin === "research" ? `<span class="tag">Research queue</span>` : task.origin === "legacy" ? `<span class="tag">Earlier</span>` : "";
    return `<a class="task-row" href="#/ask/${encodeURIComponent(task.taskId)}"><span class="task-question">${escapeHTML(task.question)}</span><span class="task-meta">${origin}${badge(status)}${reviewPending(task) ? `<span class="tag">Review pending</span>` : ""}<time>${escapeHTML(dateLabel(task.submittedAt))}</time></span></a>`;
  }

  async function renderAnswer(taskId, token) {
    view.innerHTML = `<a class="back-link" href="#/ask">← Ask another question</a><article class="answer"><p class="muted">Loading…</p></article>`;
    const [task, polymers] = await Promise.all([get(`/api/tasks/${encodeURIComponent(taskId)}`), loadPolymers().catch(() => [])]);
    if (token !== state.routeToken) return;
    const names = new Map(polymers.map(p => [p.id, p.name])), record = code => recordReference(code, names);
    const status = taskState(task), provenance = provenanceSummary(task), result = task.result;
    const citations = list(result?.citations).filter(c => typeof c === "string");
    const cite = id => { const index = citations.indexOf(id); return index >= 0 ? index + 1 : null; };
    const inline = {cite, record};
    const limitations = list(result?.limitations).filter(Boolean);
    const openQuestions = list(result?.openQuestions).filter(Boolean);
    const findings = list(task.findings);
    const article = view.querySelector(".answer");
    article.innerHTML = `
      <header class="answer-header">
        <p class="eyebrow">${task.origin === "research" ? "Research queue" : task.origin === "legacy" ? "Earlier question" : "Question"} · ${escapeHTML(dateLabel(task.submittedAt))} · ${escapeHTML(runtimeLabel(task.workerRuntime))}</p>
        <h1 class="question-text${String(task.question).length > 180 ? " long" : ""}">${escapeHTML(task.question)}</h1>
        ${status.busy ? "" : `<div class="answer-state">${result ? badge(provenance, `title="${escapeHTML(provenance?.note || "")}"`) : badge(status)}</div>`}
      </header>
      ${status.busy ? activityBlock(task, status) : ""}
      ${task.status === "failed" ? `<div class="callout bad"><p>${escapeHTML(failureMessage(task.error))}</p>${task.canRetry ? `<button type="button" class="secondary-button" data-retry>Try again</button><p id="retry-error" class="inline-error" role="alert" hidden></p>` : `<button type="button" class="secondary-button" data-reask>Ask this again</button>`}</div>` : ""}
      ${result ? `
        ${provenance ? `<p class="review-note">${escapeHTML(provenance.note)}</p>` : ""}
        <div class="answer-body prose">${renderMarkdown(result.answer, inline)}</div>
        ${limitations.length ? `<details class="limitations"><summary>Limitations noted with this answer (${limitations.length})</summary><ul>${limitations.map(item => `<li>${renderInline(item, inline)}</li>`).join("")}</ul></details>` : ""}
        <section class="sources" aria-labelledby="sources-title"><h2 id="sources-title">Sources</h2>${citations.length ? `<ol id="source-list">${citations.map((id, i) => `<li id="source-${i + 1}" data-record="${escapeHTML(id)}">${safeURL(id) ? sourceLink(id) : `<span class="muted small">Loading…</span>`}</li>`).join("")}</ol>` : `<p class="muted">This answer cites no sources.</p>`}</section>
        ${findings.length ? `<section class="findings" aria-labelledby="findings-title"><h2 id="findings-title">What this answer added</h2><p class="muted small">Findings saved from the sources this answer read. Added findings rely on the researcher’s judgement; Reviewed findings were checked in a separate source-review session.</p><ul class="finding-list">${findings.map(findingItem).join("")}</ul></section>` : ""}
        ${openQuestions.length && task.origin !== "legacy" ? `<section class="open-questions" aria-labelledby="open-title"><h2 id="open-title">Worth researching later</h2><ul>${openQuestions.map((q, i) => `<li><span>${escapeHTML(q)}</span> ${list(task.queuedResearch).includes(q) ? `<span class="tag">In the research queue</span>` : `<button type="button" class="text-button" data-research="${i}">Add to research queue</button>`}</li>`).join("")}</ul><p id="research-status" class="muted small" role="status">${list(task.queuedResearch).length ? `Added to the <a href="#/knowledge">research queue</a> automatically.` : ""}</p></section>` : ""}
        <section class="how-found" aria-labelledby="how-title"><h2 id="how-title">How this answer was found</h2><div id="how-found">${howFound(task, citations)}</div></section>` : ""}`;
    if (status.busy) watchActivity(task, taskId, token);
    else if (reviewPending(task)) later(token, () => renderAnswer(taskId, token), 10000);
    else if (reviewPending(task)) later(token, () => renderAnswer(taskId, token), 15000);
    article.querySelector("[data-reask]")?.addEventListener("click", () => { state.prefill = {question: task.question}; location.hash = "#/ask"; });
    article.querySelector("[data-retry]")?.addEventListener("click", async event => {
      event.target.disabled = true;
      try { if (!state.csrf) await loadTaskStatus(); await post(`/api/tasks/${encodeURIComponent(task.taskId)}/retry`, {authorizeSubscription: true}); if (token === state.routeToken) renderAnswer(task.taskId, token); }
      catch (error) { const note = $("#retry-error"); note.textContent = error.message; note.hidden = false; event.target.disabled = false; }
    });
    for (const button of article.querySelectorAll("[data-research]")) button.addEventListener("click", async () => {
      button.disabled = true;
      try { if (!state.csrf) await loadTaskStatus(); await post("/api/research", {question: openQuestions[Number(button.dataset.research)], fromQuestion: task.taskId}); button.textContent = "Added"; }
      catch (error) { $("#research-status").textContent = error.message; button.disabled = false; }
    });
    if (!result) return;
    citations.forEach(async (id, index) => {
      if (safeURL(id)) return;
      const item = document.getElementById(`source-${index + 1}`);
      try {
        const source = await get("/api/record", {id});
        if (token !== state.routeToken || !item) return;
        item.innerHTML = sourceEntry(source);
      } catch { if (item && token === state.routeToken) item.innerHTML = `<span>${escapeHTML(id)}</span>`; }
    });
  }
  function howFound(task, citations) {
    const stats = effortStats(task.effort), reused = task.reusedFindings || {}, sites = list(task.effort?.sites);
    if (!stats.length) return `<p class="muted small">Retrieval was not recorded for this answer.</p>`;
    return `<ul class="stat-row">${stats.map(s => `<li><strong>${formatCount(s.value)}</strong><span>${escapeHTML(s.label)}</span></li>`).join("")}<li><strong>${formatCount((reused.supported || 0) + (reused.added || 0))}</strong><span>saved findings reused</span></li><li><strong>${formatCount(citations.length)}</strong><span>source${citations.length === 1 ? "" : "s"} cited</span></li></ul>${sites.length ? `<p class="muted small">Sites read: ${sites.map(escapeHTML).join(", ")}</p>` : ""}${task.runId ? `<p class="muted small">Every lookup into the memory was recorded for this answer.</p>` : ""}`;
  }
  function findingItem(finding) {
    const status = recordStatus(finding), source = finding.source || {}, url = safeURL(source.url);
    const quantity = [finding.value, finding.unit].filter(Boolean).join(" ");
    return `<li class="finding">${badge(status, `title="${escapeHTML(status.note)}"`)} <span class="finding-statement">${escapeHTML(finding.statement)}</span>${quantity ? ` <span class="finding-value">${escapeHTML(quantity)}</span>` : ""}
      <span class="finding-source muted small">${url ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(source.title || url)} ↗</a>` : escapeHTML(source.title || "")}${finding.locator ? ` · ${escapeHTML(finding.locator)}` : ""}</span>
      ${finding.review?.reason ? `<span class="finding-reason small">Reviewer: ${renderInline(finding.review.reason)}</span>` : finding.status === "unreviewed" && finding.reviewFlag ? `<span class="finding-reason small">Sent for review: ${escapeHTML(finding.reviewFlag)}</span>` : ""}${finding.originalStatement ? `<span class="finding-reason small">Reworded from the earlier record, imported as “${escapeHTML(finding.originalStatement)}”.</span>` : ""}</li>`;
  }
  function activityBlock(task, status) {
    const live = progressDetail(task);
    return `<section class="progress-card" id="activity" aria-live="polite">${live ? activityInner(live) : `<div class="progress-head"><span class="pulse" aria-hidden="true"></span><strong>${escapeHTML(status.label)}</strong><span class="progress-clock muted">up to ${Number(task.budgetSeconds) / 60} min</span></div>`}
      <p class="progress-foot muted small">You can leave this page; the answer will be in History.</p></section>`;
  }
  function activityInner(live) {
    const meter = (used, cap, word) => cap ? `<span class="meter"><span class="meter-label">${formatCount(used)} of ${formatCount(cap)} ${word}</span><span class="meter-track"><span style="width:${Math.min(100, Math.round(used / cap * 100))}%"></span></span></span>` : `<span class="meter"><span class="meter-label">${formatCount(used)} ${word}</span></span>`;
    return `<div class="progress-head"><span class="pulse" aria-hidden="true"></span><strong>${escapeHTML(STAGES.find(([k]) => k === live.stage)[1])}</strong><span class="progress-clock muted" data-clock>${escapeHTML(live.clock)}${live.limit ? ` / ${escapeHTML(live.limit)}` : ""}</span></div>
      <div class="progress-bar" aria-hidden="true"><span data-bar style="width:${live.percent}%"></span></div>
      <ol class="stage-track">${live.stages.map(s => `<li class="${s.state}"><span class="stage-dot" aria-hidden="true"></span>${escapeHTML(s.label)}</li>`).join("")}</ol>
      ${live.action ? `<p class="progress-now">${escapeHTML(live.action)}</p>` : ""}
      <div class="meters">${meter(live.counts.knowledge + live.counts.lookups, 0, "knowledge lookups")}${meter(live.counts.searches, live.budget?.searches, "web searches")}${meter(live.counts.sources, live.budget?.sources, "sources")}</div>
      ${live.sites.length ? `<p class="sites">${live.sites.map(site => `<span class="site">${escapeHTML(site)}</span>`).join("")}</p>` : ""}`;
  }
  /** While a question runs, refresh only its progress card: the clock each second, the rest every 3 s. */
  function watchActivity(task, taskId, token) {
    let current = task, started = Date.now(), shown = null;
    const box = () => document.getElementById("activity");
    const tick = () => {
      if (token !== state.routeToken || !box()) return;
      const live = progressDetail(current);
      const clock = box().querySelector("[data-clock]"), bar = box().querySelector("[data-bar]");
      if (live && clock) { clock.textContent = live.clock + (live.limit ? ` / ${live.limit}` : ""); bar.style.width = live.percent + "%"; }
      later(token, tick, 1000);
    };
    const poll = async () => {
      try {
        const next = await get(`/api/tasks/${encodeURIComponent(taskId)}`);
        if (token !== state.routeToken) return;
        if (!taskState(next).busy) { renderAnswer(taskId, token); return; }
        current = next;
        const live = progressDetail(current), head = box();
        const key = live && JSON.stringify([live.stage, live.action, live.counts, live.sites]);
        if (live && head && key !== shown) {  // Re-render only on change, so animations run smoothly.
          shown = key;
          head.innerHTML = activityInner(live) + `<p class="progress-foot muted small">You can leave this page; the answer will be in History.</p>`;
        }
      } catch { /* Try again on the next poll. */ }
      later(token, poll, Date.now() - started < 60000 ? 2000 : 3000);
    };
    later(token, tick, 1000);
    later(token, poll, 2000);
  }
  const sourceLink = value => { const url = safeURL(value); return url ? `<span class="source-title"><a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(url)} ↗</a></span>` : escapeHTML(value); };
  function sourceEntry(record) {
    if (record.statement) {
      const status = recordStatus(record), source = record.source || {}, url = safeURL(source.url);
      return `${badge(status, `title="${escapeHTML(status.note)}"`)} <span class="source-title">${escapeHTML(record.statement)}</span><span class="source-locator">${url ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(source.title || url)} ↗</a>` : escapeHTML(source.title || "")}${record.locator ? ` · ${escapeHTML(record.locator)}` : ""}</span>`;
    }
    const url = safeURL(record.url || record.contentUrl || record.accessUrl || record.source?.url);
    const title = record.citation || record.label || record.title || record["@id"] || record.id;
    return `<span class="source-title">${url ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(title)} ↗</a>` : escapeHTML(title)}</span>${record.locator ? `<span class="source-locator">${escapeHTML(typeof record.locator === "string" ? record.locator : JSON.stringify(record.locator))}</span>` : ""}`;
  }


  // ----- History -----
  async function renderHistory(token) {
    view.innerHTML = `<section class="history"><h1>Your questions</h1><div id="history-list" class="task-list"><p class="muted">Loading…</p></div></section>`;
    const listing = await get("/api/tasks");
    if (token !== state.routeToken) return;
    $("#history-list").innerHTML = listing.tasks.length ? listing.tasks.map(taskRow).join("") + (listing.omitted ? `<p class="muted small">${formatCount(listing.omitted)} older questions are not shown.</p>` : "")
      : `<p class="muted">You haven’t asked anything yet. <a href="#/ask">Ask a question</a>.</p>`;
    if (listing.tasks.some(task => taskState(task).busy || reviewPending(task))) later(token, () => renderHistory(token), 5000);
  }

  // ----- Polymers -----
  async function loadPolymers() {
    if (state.polymers) return state.polymers;
    const result = await get("/api/search", {type: "PolymerConcept", limit: 500});
    state.polymers = list(result.records).map(r => ({id: r["@id"], name: r.label || r.canonicalName || r["@id"], abbreviations: list(r.abbreviations), alternate: list(r.alternateNames)}))
      .sort((a, b) => a.name.localeCompare(b.name));
    return state.polymers;
  }
  const polymerEmpty = `<div class="polymer-empty"><h1>Polymers in memory</h1><p>Choose a polymer to read its structure, properties, processing and sources.</p></div>`;
  const matches = (polymer, query) => !query || [polymer.name, ...polymer.abbreviations, ...polymer.alternate].some(text => String(text).toLowerCase().includes(query));

  async function renderPolymers(id, token) {
    const layout = view.querySelector(".polymers-layout");
    if (layout && state.polymers) {
      // Keep the list and its scroll position; replace only the selection and the page.
      layout.classList.toggle("has-selection", !!id);
      for (const link of layout.querySelectorAll(".polymer-list a")) {
        if (link.getAttribute("href") === `#/polymers/${encodeURIComponent(id)}`) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
      }
      $("#polymer-page").innerHTML = id ? `<p class="muted">Loading…</p>` : polymerEmpty;
      if (id) await renderPolymer(id, token);
      return;
    }
    view.innerHTML = `<div class="polymers-layout${id ? " has-selection" : ""}">
      <aside class="polymer-index" aria-label="Polymer list">
        <label class="search"><span class="visually-hidden">Find a polymer</span><input id="polymer-search" type="search" placeholder="Find a polymer" autocomplete="off" value="${escapeHTML(state.polymerQuery)}"></label>
        <p id="polymer-count" class="muted small"></p>
        <ul id="polymer-list" class="polymer-list"><li class="muted">Loading…</li></ul>
      </aside>
      <section id="polymer-page" class="polymer-page">${id ? `<p class="muted">Loading…</p>` : polymerEmpty}</section>
    </div>`;
    const polymers = await loadPolymers();
    if (token !== state.routeToken) return;
    const renderList = () => {
      const query = state.polymerQuery.trim().toLowerCase(), shown = polymers.filter(p => matches(p, query));
      $("#polymer-count").textContent = `${formatCount(shown.length)} of ${formatCount(polymers.length)} polymers`;
      $("#polymer-list").innerHTML = shown.map(p => `<li><a href="#/polymers/${encodeURIComponent(p.id)}"${p.id === id ? ' aria-current="page"' : ""}>${escapeHTML(p.name)}${p.abbreviations.length ? ` <span class="muted">${escapeHTML(p.abbreviations.join(", "))}</span>` : ""}</a></li>`).join("") || `<li class="muted">No polymers match.</li>`;
    };
    $("#polymer-search").addEventListener("input", event => { state.polymerQuery = event.target.value; renderList(); });
    renderList();
    if (id) await renderPolymer(id, token);
  }

  async function renderPolymer(id, token) {
    const page = $("#polymer-page");
    const [record, claims, incoming] = await Promise.all([get("/api/record", {id}), get("/api/claims", {subject: id, limit: 200}).catch(() => ({records: []})), get("/api/claims", {object: id, limit: 200}).catch(() => ({records: []}))]);
    if (token !== state.routeToken) return;
    const status = recordStatus(record);
    const evidenceIds = list(record.evidence).filter(e => typeof e === "string");
    const sourceNumber = new Map(evidenceIds.map((e, i) => [e, i + 1]));
    const numberFor = evidenceId => { if (!sourceNumber.has(evidenceId)) { evidenceIds.push(evidenceId); sourceNumber.set(evidenceId, evidenceIds.length); } return sourceNumber.get(evidenceId); };
    const refs = ids => list(ids).filter(e => typeof e === "string").map(e => citationLink(numberFor(e))).join("");
    const taxonomy = record.taxonomy || {};
    const tags = [...new Set([taxonomy.primaryClass, ...list(taxonomy.chemistryClasses), ...list(taxonomy.functionalTags), ...list(taxonomy.origins)].filter(Boolean).map(sentenceCase))];
    const depictions = list(record.structuralDepictions?.items);
    const relations = [...list(claims.records), ...list(incoming.records)].filter(c => ["broader", "narrower", "related"].includes(c.predicate));
    const related = relations.map(c => {
      const outgoing = c.subject === id, other = outgoing ? c.object : c.subject;
      const kind = c.predicate === "related" ? "Related" : (c.predicate === "broader") === outgoing ? "Broader family" : "More specific";
      return {id: other, kind};
    }).filter((r, i, all) => r.id && r.id !== id && all.findIndex(o => o.id === r.id) === i);
    const names = new Map((state.polymers || []).map(p => [p.id, p.name]));
    const sectionIds = list(record.sectionIds);
    page.innerHTML = `
      <a class="back-link mobile-only" href="#/polymers">← All polymers</a>
      <header class="polymer-header">
        <h1>${escapeHTML(record.canonicalName || record.label)}</h1>
        ${list(record.abbreviations).length || list(record.alternateNames).length ? `<p class="aka">${escapeHTML([...list(record.abbreviations), ...list(record.alternateNames)].join(" · "))}</p>` : ""}
        <div class="tag-row">${badge(status, `title="${escapeHTML(status.note)}"`)}${tags.map(t => `<span class="tag">${escapeHTML(t)}</span>`).join("")}</div>
        <p class="status-note">${escapeHTML(status.note)}</p>
      </header>
      ${depictions.length ? `<section class="structures" aria-label="Structure">${depictions.map((d, i) => `<figure class="structure"><div class="structure-drawing" data-structure="structure:${escapeHTML(d.structureId)}" data-alt="${escapeHTML(d.altText || d.label || "Chemical structure")}" id="structure-${i}"><span class="muted small">Drawing structure…</span></div><figcaption><strong>${escapeHTML(d.label || "")}</strong>${d.fidelity ? ` <span class="tag">${escapeHTML(d.fidelity === "exact" ? "Exact repeat unit" : sentenceCase(d.fidelity))}</span>` : ""}${d.caption ? `<br>${escapeHTML(d.caption)}` : ""}</figcaption></figure>`).join("")}</section>` : ""}
      <div id="sections" class="sections">${sectionIds.map((sid, i) => `<section class="record-section" id="sec-${i}" data-section="${escapeHTML(sid)}"><h2>${escapeHTML(sectionTitle(String(sid).split(":").pop()))}</h2><div class="prose"><p class="muted small">Loading…</p></div></section>`).join("")}</div>
      ${list(record.synthesisRoutes).length ? `<section class="record-section routes"><h2>Synthesis routes</h2>${list(record.synthesisRoutes).map(route => synthesisRoute(route, record.wopId || id, refs, new Set(evidenceIds))).join("")}</section>` : ""}
      ${list(claims.findings).length ? `<section class="record-section findings"><h2>Findings from questions</h2><p class="muted small">Facts that answered questions read in their sources. Reviewed ones were checked against the source by a separate reviewer.</p><ul class="finding-list">${list(claims.findings).map(findingItem).join("")}</ul></section>` : ""}
      ${related.length ? `<section class="record-section"><h2>Related polymers</h2><ul class="related">${related.map(r => `<li><span class="muted small">${escapeHTML(r.kind)}</span> <a href="#/polymers/${encodeURIComponent(r.id)}">${escapeHTML(names.get(r.id) || r.id)}</a></li>`).join("")}</ul></section>` : ""}
      <section class="record-section" aria-labelledby="refs-title"><h2 id="refs-title">Sources</h2><ol id="references" class="references"></ol></section>`;
    const fillReferences = () => { const target = $("#references"); if (target) target.innerHTML = evidenceIds.map((e, i) => `<li id="source-${i + 1}" data-record="${escapeHTML(e)}"><span class="muted small">Loading…</span></li>`).join(""); };
    // Sections, in their recorded order; empty sections are omitted.
    await Promise.all(sectionIds.map(async (sid, i) => {
      const element = document.getElementById(`sec-${i}`);
      try {
        const section = await get("/api/record", {id: sid});
        if (token !== state.routeToken) return;
        if (!section.text || section.empty === true) { element.remove(); return; }
        element.querySelector(".prose").innerHTML = `${String(section.text).split(/\n{2,}/).map(p => `<p>${escapeHTML(p)}</p>`).join("")}${list(section.evidence).length ? `<p class="section-sources">Sources ${refs(section.evidence)}</p>` : ""}`;
      } catch { if (element) element.remove(); }
    }));
    if (token !== state.routeToken) return;
    fillReferences();
    evidenceIds.forEach(async (e, i) => {
      try {
        const source = await get("/api/record", {id: e});
        const item = document.getElementById(`source-${i + 1}`);
        if (token === state.routeToken && item) item.innerHTML = sourceEntry(source);
      } catch { const item = document.getElementById(`source-${i + 1}`); if (item) item.textContent = e; }
    });
    for (const drawing of page.querySelectorAll("[data-structure]")) drawStructureFor(drawing, token);
  }
  function synthesisRoute(route, wopId, refs, known) {
    const evidence = ids => list(ids).map(s => `evidence:${wopId}:${s}`).filter(e => known.has(e));
    const inputs = list(route.inputs).map(i => i.label).filter(Boolean), reagents = list(route.reagents);
    return `<article class="route">
      ${route.conditions ? `<h3>${escapeHTML(route.conditions)}</h3>` : ""}
      ${inputs.length ? `<p><strong>Inputs:</strong> ${escapeHTML(inputs.join(", "))}</p>` : ""}
      ${reagents.length ? `<p><strong>Reagents:</strong> ${reagents.map(r => escapeHTML(`${r.name}${r.role ? ` (${r.role})` : ""}`)).join(", ")}</p>` : ""}
      ${route.mechanism ? `<p>${escapeHTML(route.mechanism)}</p>` : ""}
      ${list(route.steps).length ? `<ol class="steps">${list(route.steps).map(s => `<li><strong>${escapeHTML(s.title || "")}</strong> ${escapeHTML(s.body || "")} ${refs(evidence(s.sourceIds))}</li>`).join("")}</ol>` : ""}
      ${route.limitations ? `<p class="muted small">${escapeHTML(route.limitations)}</p>` : ""}
    </article>`;
  }

  // ----- Structure drawing (OpenChemLib, loaded on first use) -----
  let chemistry = null, drawingCount = 0;
  const loadChemistry = () => chemistry ||= import("/vendor/openchemlib.js").then(module => module.default || module);
  async function drawStructureFor(element, token) {
    try {
      const record = await get("/api/record", {id: element.dataset.structure});
      if (token !== state.routeToken) return;
      const molfile = record.molfileV3000 || record.molfile;
      if (!molfile) { element.innerHTML = `<span class="muted small">No drawing is available.</span>`; return; }
      const OCL = await loadChemistry();
      if (token !== state.routeToken) return;
      element.replaceChildren(drawMolecule(OCL, molfile, element.dataset.alt));
    } catch { element.innerHTML = `<span class="muted small">The structure could not be drawn.</span>`; }
  }
  function drawMolecule(OCL, molfile, alt) {
    const parsed = parseMolfile(molfile), molecule = OCL.Molecule.fromMolfile(molfile);
    parsed.atoms.forEach((atom, i) => {
      if (i >= molecule.getAllAtoms()) return;
      if (atom.element === "*") molecule.setAtomCustomLabel(i, "*");
      else if (atom.element === "R#" || atom.element === "R") molecule.setAtomCustomLabel(i, `R${atom.rgroup ?? ""}`);
    });
    const id = `molecule-${++drawingCount}`, width = 420, height = 240;
    const markup = molecule.toSVG(width, height, id, {suppressChiralText: true, noStereoProblem: true, noColorOnESRAndCIP: true}).replace(/rgb\(0,0,0\)/g, "currentColor");
    const svg = document.importNode(new DOMParser().parseFromString(markup, "image/svg+xml").documentElement, true);
    const ns = "http://www.w3.org/2000/svg";
    svg.removeAttribute("width"); svg.removeAttribute("height");
    svg.setAttribute("role", "img"); svg.setAttribute("aria-label", alt || "Chemical structure");
    const pixels = parsed.atoms.map((_, i) => { const c = svg.querySelector(`circle[id="${id}:Atom:${i}"]`); return c ? {x: Number(c.getAttribute("cx")), y: Number(c.getAttribute("cy"))} : null; });
    const extent = pixels.filter(Boolean).map(p => [p.x, p.y]);
    if (pixels.every(Boolean)) {
      const transform = fitTransform(parsed.atoms, pixels);
      for (const sgroup of parsed.sgroups.filter(s => s.type === "SRU")) {
        const geometry = bracketGeometry(sgroup, parsed.atoms, transform);
        if (!geometry) continue;
        extent.push(...geometry.brackets.flat());
        if (geometry.label) extent.push([geometry.label.x + 8, geometry.label.y + 2]);
        for (const points of geometry.brackets) {
          const line = document.createElementNS(ns, "polyline");
          line.setAttribute("points", points.map(p => p.map(v => v.toFixed(2)).join(",")).join(" "));
          line.setAttribute("class", "bracket");
          svg.append(line);
        }
        if (geometry.label) {
          const text = document.createElementNS(ns, "text");
          Object.entries({x: geometry.label.x.toFixed(2), y: geometry.label.y.toFixed(2), class: "bracket-label"}).forEach(([k, v]) => text.setAttribute(k, v));
          text.textContent = geometry.label.text;
          svg.append(text);
        }
      }
    }
    svg.setAttribute("viewBox", croppedViewBox(extent, {width, height, pad: 18}));
    return svg;
  }

  // ----- Knowledge -----
  const FILTERS = [["supported", "Reviewed"], ["accepted", "Added"], ["needs-checking", "Needs checking"], ["unsupported", "Rejected"]];
  async function renderKnowledge(token) {
    view.innerHTML = `<section class="knowledge"><h1>What the memory knows</h1><p class="muted">Loading…</p></section>`;
    const filter = state.knowledgeFilter || "supported";
    const [loop, listing] = await Promise.all([get("/api/loop"), get("/api/knowledge", {status: filter, limit: 100})]);
    if (token !== state.routeToken) return;
    const summary = knowledgeSummary(loop), research = loop.research || {}, researching = loop.settings?.researchPerWeek > 0;
    const counts = {supported: summary.supported, accepted: summary.accepted, "needs-checking": summary.unreviewed + summary.uncertain, unsupported: summary.unsupported};
    const last = list(loop.log)[0];
    view.querySelector(".knowledge").innerHTML = `
      <h1>What the memory knows</h1>
      <div class="status-card"><p class="headline">${escapeHTML(summary.headline)}</p><p>Each answer saves the facts it read, with their source, locator and a short excerpt. ${loop.settings?.reviewMode === "all" ? "A separate reviewer checks every finding against its source before later questions use it." : "Values the research agent read directly in a source are added at once; ones it read off a figure, converted or combined go to a separate reviewer first. You can require review of every finding in Settings."}${summary.spotText ? ` ${escapeHTML(summary.spotText)}` : ""}</p></div>
      <section aria-labelledby="loop-title"><h2 id="loop-title">The loop</h2>
        <ol class="loop">${summary.stages.map((stage, i) => `<li class="loop-stage reached"><span class="loop-number">${i + 1}</span><span class="loop-title">${escapeHTML(stage.title)}</span><strong class="loop-value">${formatCount(stage.value)}</strong><span class="loop-text">${escapeHTML(stage.text)}</span></li>`).join("")}</ol>
        <div class="loop-actions">
          <button type="button" id="loop-run" class="secondary-button"${loop.running ? " disabled" : ""}>${loop.running ? "Running…" : "Run the loop now"}</button>
          <p class="muted small">Reviews ${formatCount(summary.pending)} answer${summary.pending === 1 ? "" : "s"} waiting${researching ? ", then asks one queued question if this week's limit allows" : ""}, using your signed-in subscriptions.</p>
          <p id="loop-status" class="muted small" role="status">${loop.running ? "The loop is running." : last ? `Last run ${escapeHTML(dateLabel(last.finishedAt))}: ${escapeHTML(loopRunText(last))}` : "The loop has not run yet."}${loop.schedule?.installed ? " It also runs hourly in the background." : " It runs only when you start it."}</p>
        </div>
      </section>
      <section aria-labelledby="findings-title"><h2 id="findings-title">Findings</h2>
        <div class="filter-row" role="tablist">${FILTERS.map(([key, label]) => `<button type="button" role="tab" class="filter${key === filter ? " selected" : ""}" aria-selected="${key === filter}" data-filter="${key}">${escapeHTML(label)} <span class="muted">${formatCount(counts[key])}</span></button>`).join("")}</div>
        ${list(listing.findings).length ? `<ul class="finding-list">${list(listing.findings).map(findingItem).join("")}</ul>` : `<p class="muted">No findings here yet.</p>`}
      </section>
      <section aria-labelledby="research-title"><h2 id="research-title">Research queue</h2>
        <p class="muted small">${researching ? `Gaps from your answers. The loop asks up to ${formatCount(research.weeklyLimit)} a week (${formatCount(research.askedThisWeek)} so far this week).` : "Background research is off. Set a weekly number in Settings and the loop will ask these, and your answers' open questions will join the queue."}</p>
        ${list(research.queue).length ? `<ul class="research-list">${list(research.queue).slice().reverse().map(item => `<li>${badge({label: item.status === "asked" ? "Asked" : "Waiting", tone: item.status === "asked" ? "good" : "neutral"})} ${item.questionId ? `<a href="#/ask/${encodeURIComponent(item.questionId)}">${escapeHTML(item.question)}</a>` : escapeHTML(item.question)}</li>`).join("")}</ul>` : `<p class="muted">Nothing queued. Add gaps from an answer's “Worth researching later” list.</p>`}
      </section>`;
    for (const button of view.querySelectorAll("[data-filter]")) button.addEventListener("click", () => { state.knowledgeFilter = button.dataset.filter; renderKnowledge(token); });
    const run = $("#loop-run");
    run.addEventListener("click", async () => {
      run.disabled = true;
      try { if (!state.csrf) await loadTaskStatus(); await post("/api/loop/tick", {authorizeSubscription: true}); $("#loop-status").textContent = "The loop is running."; later(token, () => renderKnowledge(token), 4000); }
      catch (error) { $("#loop-status").textContent = error.message; run.disabled = false; }
    });
    if (loop.running) later(token, () => renderKnowledge(token), 5000);
  }
  function loopRunText(entry) {
    if (entry.status === "skipped-another-tick-running") return "skipped, another run was in progress.";
    const reviews = list(entry.reviews), done = reviews.filter(r => r.status === "reviewed").length, failed = reviews.filter(r => r.status === "failed");
    const research = entry.research?.status === "asked" ? " One research question asked." : "";
    if (!reviews.length) return "nothing was waiting for review." + research;
    return `${plural(done, "answer")} reviewed${failed.length ? `, ${failed.length} failed (${failed[0].reason})` : ""}.` + research;
  }

  // ----- Settings -----
  const settings = $("#settings-dialog");
  let accountTimer = null;
  const RUNTIME_ORDER = ["codex", "claude-code"];
  const accountPaths = runtime => runtime === "claude-code"
    ? {login: "/api/runtimes/claude-code/login", cancel: "/api/runtimes/claude-code/cancel"}
    : {login: "/api/account/login", cancel: "/api/account/cancel"};
  function renderSettings() {
    const runtimes = state.runtimes?.runtimes || {}, selected = selectedRuntime();
    $("#runtime-list").innerHTML = state.runtimes ? RUNTIME_ORDER.filter(id => runtimes[id]).map(id => {
      const entry = runtimes[id], account = entry.account || {}, pending = account.status === "login-pending";
      const identity = [account.account?.email, account.account?.planType].filter(Boolean).join(" · ");
      const text = account.status === "connected" ? `Connected${identity ? ` · ${identity}` : ""}` : account.message || "Checking…";
      const link = pending && account.loginUrl ? loginLink(account.loginUrl, id) : null;
      return `<div class="runtime-option${id === selected ? " selected" : ""}">
        <label><input type="radio" name="runtime" value="${escapeHTML(id)}"${id === selected ? " checked" : ""}><span><strong>${escapeHTML(entry.label)}</strong> <span class="muted small">${escapeHTML(entry.model)}</span></span></label>
        <p class="small runtime-status">${badge({label: ({connected: "Connected", "login-pending": "Signing in", disconnected: "Not connected"})[account.status] || "Unavailable", tone: account.status === "connected" ? "good" : pending ? "warn" : "neutral"})} ${escapeHTML(text)}</p>
        <div class="settings-actions">
          ${account.status === "disconnected" ? `<button type="button" class="secondary-button" data-connect="${escapeHTML(id)}">Connect ${escapeHTML(entry.label)}</button>` : ""}
          ${link ? `<a href="${escapeHTML(link)}" target="_blank" rel="noopener noreferrer">Continue to sign-in ↗</a>` : ""}
          ${pending ? `<button type="button" class="text-button" data-cancel="${escapeHTML(id)}">Cancel</button>` : ""}
        </div></div>`;
    }).join("") : `<p class="muted small">Checking…</p>`;
  }
  async function loadKnowledgeSettings() {
    try {
      const value = await get("/api/settings");
      for (const input of settings.querySelectorAll("[name=review-mode]")) input.checked = input.value === value.reviewMode;
      $("#spot-rate").value = String(value.spotCheckRate);
      $("#research-per-week").value = String(value.researchPerWeek);
      $("#knowledge-error").hidden = true;
    } catch (error) { $("#knowledge-error").textContent = error.message; $("#knowledge-error").hidden = false; }
  }
  async function saveKnowledgeSetting(change) {
    try { if (!state.csrf) await loadTaskStatus(); await post("/api/settings", change); $("#knowledge-error").hidden = true; }
    catch (error) { $("#knowledge-error").textContent = error.message; $("#knowledge-error").hidden = false; }
    await loadKnowledgeSettings();
  }
  const settingsError = error => { $("#account-error").textContent = error?.message || ""; $("#account-error").hidden = !error; };
  async function refreshSettings() {
    clearTimeout(accountTimer);
    try { await loadTaskStatus(); settingsError(null); } catch (error) { settingsError(error); }
    renderSettings();
    state.updateAsk?.();
    const pending = Object.values(state.runtimes?.runtimes || {}).some(entry => entry.account?.status === "login-pending");
    if (settings.open) accountTimer = setTimeout(refreshSettings, pending ? 1500 : 30000);
  }
  async function accountAction(runtime, action) {
    for (const button of settings.querySelectorAll("[data-connect],[data-cancel]")) button.disabled = true;
    try {
      if (!state.csrf) await loadTaskStatus();
      await post(accountPaths(runtime)[action], action === "login" ? {authorizeAccountConnection: true} : {cancelAccountConnection: true});
      settingsError(null);
    } catch (error) { settingsError(error); }
    finally { clearTimeout(accountTimer); await refreshSettings(); }
  }
  async function chooseRuntime(runtime) {
    try {
      if (!state.csrf) await loadTaskStatus();
      await post("/api/runtimes/select", {runtime, authorizeRuntimeSelection: true});
      state.pending = null;
      settingsError(null);
    } catch (error) { settingsError(error); }
    await refreshSettings();
    await state.refreshAskQuota?.();
  }
  function openSettings() { settings.showModal(); renderSettings(); refreshSettings(); loadKnowledgeSettings(); }

  // ----- Theme and global events -----
  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("oopc-theme", theme); } catch { /* Preference is optional. */ }
    $("#theme-toggle").setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} theme`);
  }
  function init() {
    let theme = null;
    try { theme = localStorage.getItem("oopc-theme"); } catch { /* Preference is optional. */ }
    setTheme(theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
    $("#theme-toggle").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
    $("#settings-button").addEventListener("click", openSettings);
    settings.addEventListener("close", () => { clearTimeout(accountTimer); state.updateAsk?.(); });
    settings.querySelector("[data-close]").addEventListener("click", () => settings.close());
    settings.addEventListener("click", event => {
      const connect = event.target.closest("[data-connect]"), cancel = event.target.closest("[data-cancel]");
      if (connect) accountAction(connect.dataset.connect, "login");
      else if (cancel) accountAction(cancel.dataset.cancel, "cancel");
    });
    settings.addEventListener("change", event => {
      if (event.target.name === "runtime") chooseRuntime(event.target.value);
      else if (event.target.name === "review-mode") saveKnowledgeSetting({reviewMode: event.target.value});
      else if (event.target.id === "spot-rate") saveKnowledgeSetting({spotCheckRate: Number(event.target.value)});
      else if (event.target.id === "research-per-week") saveKnowledgeSetting({researchPerWeek: Math.round(Number(event.target.value))});
    });
    $("#error-dismiss").addEventListener("click", () => showError(null));
    document.addEventListener("click", event => {
      if (event.target.closest("[data-open-settings]")) openSettings();
      const cite = event.target.closest("a.cite");
      if (cite) {
        event.preventDefault();
        const target = document.getElementById(`source-${cite.dataset.source}`);
        if (target) { target.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center"}); target.classList.add("flash"); setTimeout(() => target.classList.remove("flash"), 1600); }
      }
    });
    window.addEventListener("hashchange", route);
    if (!location.hash || location.hash.startsWith("#/improvement")) history.replaceState(null, "", location.hash.startsWith("#/improvement") ? "#/knowledge" : "#/ask");
    route();
  }
  init();
})();
