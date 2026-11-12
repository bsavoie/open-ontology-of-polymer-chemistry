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

  // TeX names the converter knows; each kind sets the spacing TeX would give it.
  const TEX = {
    ord: {alpha:"α", beta:"β", gamma:"γ", delta:"δ", epsilon:"ε", varepsilon:"ε", zeta:"ζ", eta:"η", theta:"θ", vartheta:"ϑ", iota:"ι", kappa:"κ", lambda:"λ", mu:"μ", nu:"ν", xi:"ξ", pi:"π", rho:"ρ", varrho:"ϱ", sigma:"σ", varsigma:"ς", tau:"τ", upsilon:"υ", phi:"φ", varphi:"φ", chi:"χ", psi:"ψ", omega:"ω",
      Gamma:"Γ", Delta:"Δ", Theta:"Θ", Lambda:"Λ", Xi:"Ξ", Pi:"Π", Sigma:"Σ", Upsilon:"Υ", Phi:"Φ", Psi:"Ψ", Omega:"Ω",
      infty:"∞", partial:"∂", nabla:"∇", ell:"ℓ", hbar:"ℏ", circ:"∘", degree:"°", prime:"′", cdots:"⋯", ldots:"…", dots:"…", permil:"‰", AA:"Å", langle:"⟨", rangle:"⟩", lbrace:"{", rbrace:"}", vert:"|", Vert:"‖"},
    op: {sum:"∑", prod:"∏", int:"∫", oint:"∮"},
    bin: {times:"×", cdot:"·", pm:"±", mp:"∓", div:"÷", ast:"∗"},
    rel: {le:"≤", leq:"≤", ge:"≥", geq:"≥", ll:"≪", gg:"≫", ne:"≠", neq:"≠", approx:"≈", sim:"∼", simeq:"≃", equiv:"≡", propto:"∝", lt:"<", gt:">", in:"∈",
      to:"→", rightarrow:"→", longrightarrow:"⟶", leftarrow:"←", Rightarrow:"⇒", leftrightarrow:"↔", rightleftharpoons:"⇌"},
    space: {quad:"\u2003", qquad:"\u2003\u2003", ",":"\u2009", ":":"\u2005", ";":"\u2005", "!":"", " ":"\u00a0"},
    accent: {dot:"\u0307", ddot:"\u0308", bar:"\u0304", hat:"\u0302", tilde:"\u0303", vec:"\u20d7"},
  };
  const TEX_FUNCTION = /^(?:ln|log|lg|exp|sin|cos|tan|sinh|cosh|tanh|min|max|lim|det)$/;

  /** A TeX subset (scripts, fractions, roots, accents, upright text, Greek, common symbols) as escaped HTML; any other command stays as written. */
  function renderMath(tex) {
    const s = String(tex ?? "");
    let i = 0;
    const control = () => { i++; const name = /^[A-Za-z]+/.exec(s.slice(i))?.[0] || s[i] || ""; i += name.length; return name; };
    const argument = mode => { while (/\s/.test(s[i] || "")) i++; if (s[i] === "{") { i++; return sequence(mode, true); } return i < s.length ? item(mode).html : ""; };
    const item = mode => {
      const c = s[i];
      if (c === "{") { i++; return {html: sequence(mode, true), kind: "ord"}; }
      if (c === "_" || c === "^") { i++; const tag = c === "_" ? "sub" : "sup"; return {html: `<${tag}>${argument({...mode, script: true})}</${tag}>`, kind: "script"}; }
      if (c === "\\") return command(mode);
      i++;
      if (/\s/.test(c)) return {html: mode.text ? " " : "", kind: "space"};
      if (/[A-Za-z]/.test(c)) return {html: mode.upright ? c : `<i>${c}</i>`, kind: "ord"};
      if (mode.text) return {html: escapeHTML(c), kind: "ord"};
      const kind = "+-*".includes(c) ? "bin" : "=<>".includes(c) ? "rel" : "([".includes(c) ? "open" : "ord";
      return {html: escapeHTML(({"-": "−", "*": "∗", "'": "′"})[c] || c), kind};
    };
    const command = mode => {
      const name = control();
      for (const kind of ["ord", "op", "bin", "rel", "space"]) if (Object.hasOwn(TEX[kind], name)) return {html: escapeHTML(TEX[kind][name]), kind};
      if (name === "\\") return {html: "<br>", kind: "space"};
      if (/^[^A-Za-z]$/.test(name)) return {html: escapeHTML(name), kind: "ord"};
      if (["frac", "dfrac", "tfrac"].includes(name)) { const num = argument(mode); return {html: `<span class="math-frac"><span>${num}</span><span class="visually-hidden">/</span><span>${argument(mode)}</span></span>`, kind: "ord"}; }
      if (name === "sqrt") {
        const end = s[i] === "[" ? s.indexOf("]", i) : -1, index = end > i ? `<sup>${renderMath(s.slice(i + 1, end))}</sup>` : "";
        if (index) i = end + 1;
        return {html: `${index}√<span class="math-sqrt">${argument(mode)}</span>`, kind: "ord"};
      }
      if (["mathrm", "text", "textrm", "mathup"].includes(name)) return {html: argument({...mode, upright: true, text: name.startsWith("text")}), kind: "ord"};
      if (["mathbf", "textbf", "boldsymbol"].includes(name)) return {html: `<b>${argument({...mode, upright: name !== "boldsymbol"})}</b>`, kind: "ord"};
      if (["mathit", "textit"].includes(name)) return {html: argument({...mode, upright: false}), kind: "ord"};
      if (name === "overline") return {html: `<span class="math-over">${argument(mode)}</span>`, kind: "ord"};
      if (Object.hasOwn(TEX.accent, name)) { const arg = argument(mode), mark = TEX.accent[name]; return {html: arg.endsWith("</i>") ? `${arg.slice(0, -4)}${mark}</i>` : arg + mark, kind: "ord"}; }
      if (/^(?:left|right|[bB]igg?[lr]?)$/.test(name)) { while (/\s/.test(s[i] || "")) i++; if (s[i] === ".") i++; return {html: "", kind: "space"}; }
      if (TEX_FUNCTION.test(name)) return {html: name, kind: "op"};
      return {html: escapeHTML(`\\${name}`), kind: "ord"};
    };
    // Relations and binary signs get TeX's spacing outside scripts; a sign that opens an expression, a bracket or a script stays tight.
    const sequence = (mode, braced) => {
      let html = "", prev = "open";
      while (i < s.length) {
        if (s[i] === "}") { i++; if (braced) break; html += "}"; prev = "ord"; continue; }
        const {html: piece, kind} = item(mode);
        if (kind === "space" || kind === "script") { html += piece; continue; }
        const spaced = !mode.script && !mode.text && (kind === "rel" || (kind === "bin" && prev === "ord"));
        html += (prev === "op" && kind === "ord" ? "\u2009" : "") + (spaced ? `\u2005${piece}\u2005` : piece);
        prev = ["open", "rel", "bin"].includes(kind) ? "open" : kind;
      }
      return html;
    };
    return sequence({}, false).replace(/<\/i><i>/g, "");
  }

  /** Inline markdown on raw text; every literal piece is escaped and only http(s) links survive. */
  function renderInline(text, options = {}) {
    const pattern = /(`[^`\n]+`)|\[([^\]\n]+)\]\(([^)\s]+)\)|\*\*([^*\n]+)\*\*|(?<![\w*])\*([^*\s][^*\n]*?)\*(?![\w*])|\\\((.+?)\\\)|\\\[(.+?)\\\]|\$\$(.+?)\$\$/g;
    let html = "", last = 0, match;
    const source = String(text ?? "");
    while ((match = pattern.exec(source))) {
      html += escapeHTML(source.slice(last, match.index));
      last = pattern.lastIndex;
      if (match[1]) {
        const code = match[1].slice(1, -1), number = options.cite?.(code), record = !number && options.record?.(code);
        html += number ? citationLink(number, options.prefix) : record ? `<a href="${escapeHTML(record.href)}">${escapeHTML(record.label)}</a>` : `<code>${escapeHTML(code)}</code>`;
      } else if (match[2]) {
        const url = safeURL(match[3]), label = match[2];
        const cited = /^(evidence:[^\s,;]+)(.*)$/.exec(label), number = cited && options.cite?.(cited[1]);
        const inner = number ? `[${number}${escapeHTML(cited[2])}]` : renderInline(label, {...options, noLinks: true});
        html += url && !options.noLinks ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${inner}</a>` : inner;
      } else if (match[4]) html += `<strong>${renderInline(match[4], options)}</strong>`;
      else if (match[5]) html += `<em>${renderInline(match[5], options)}</em>`;
      else html += `<span class="math">${renderMath(match[6] || match[7] || match[8])}</span>`;
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
  /** A citation number; `prefix` keeps one answer's sources apart from another's on a conversation's page. */
  const citationLink = (number, prefix = "") => `<a class="cite" href="#source-${prefix}${number}" data-source="${prefix}${number}">[${number}]</a>`;

  /** A small, safe markdown subset: headings, lists, tables, display math and paragraphs. */
  function renderMarkdown(text, options = {}) {
    const lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    const cells = row => row.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
    const display = /^\s*(\\\[|\$\$)/;
    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      const math = display.exec(line);
      if (math) {
        // \[ … \] or $$ … $$ may span lines; text after the closing delimiter starts the next block.
        const close = math[1] === "$$" ? "$$" : "\\]";
        let body = line.slice(math[0].length), j = i;
        while (!body.includes(close) && j + 1 < lines.length && lines[j + 1].trim()) body += "\n" + lines[++j];
        const end = body.indexOf(close);
        if (end >= 0) {
          out.push(`<div class="math math-display">${renderMath(body.slice(0, end))}</div>`);
          const rest = body.slice(end + close.length);
          if (rest.trim()) lines[j] = rest; else j++;
          i = j;
          continue;
        }
      }
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
      // The first line always belongs to the paragraph, so a line no other block took (a lone "| x |" row, an unclosed "\[") cannot stall the loop.
      const paragraph = [lines[i++]];
      while (i < lines.length && lines[i].trim() && !/^(#{1,4})\s/.test(lines[i]) && !bullet.test(lines[i]) && !numbered.test(lines[i]) && !/^\s*\|.*\|\s*$/.test(lines[i]) && !display.test(lines[i])) paragraph.push(lines[i++]);
      out.push(`<p>${paragraph.map(p => renderInline(p, options)).join("<br>")}</p>`);
    }
    return out.join("");
  }

  /** One plain status per record or finding; imported seed drafts are never presented as reviewed. */
  function recordStatus(record) {
    const status = String(record?.status || "").toLowerCase();
    if (status === "unsupported" && record?.review?.engine === "person") return {label: "Rejected", tone: "bad", note: "A person rejected this finding after a reviewer found it conflicts with another. Researchers no longer see it."};
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
    // The answer comes first; the research agent then writes the findings it read, in the background.
    const saving = task.depositState;
    if (saving?.status === "saving") return {label: "Saving findings…", tone: "neutral", note: "The answer is ready. The findings and source notes behind it are being saved for later questions." + reusedText};
    if (saving?.status === "skipped") return {label: "Outside scope: not saved", tone: "neutral", note: OUTSIDE_SCOPE + reusedText};
    if (saving?.status === "failed") {
      const why = DEPOSIT_FAILURES[saving.reason] || ["did not finish", "saving them did not finish"];
      return {label: `Findings not saved: ${why[0]}`, tone: "warn", note: `The answer stands, but the findings and source notes it read were not saved: ${why[1]}. Later questions will not reuse them.` + reusedText};
    }
    const known = deposit?.duplicates ? ` ${plural(deposit.duplicates, "finding")} ${deposit.duplicates === 1 ? "was" : "were"} already known and not saved again.` : "";
    if (!deposit || !deposit.findings) return {label: "Nothing new saved", tone: "neutral", note: "This answer cites its sources but found nothing new to save." + known + reusedText};
    const added = counts.accepted || 0, flagged = counts.unreviewed || 0, waiting = deposit.waitingReview || 0, byPerson = deposit.rejectedByPerson || 0;
    const checked = [[counts.supported, "confirmed"], [(counts.unsupported || 0) - byPerson, "rejected"], [counts.uncertain, "inconclusive"]].filter(([n]) => n > 0);
    const parts = [];
    if (added) parts.push(`added ${plural(added, "finding")} on the research agent's judgement`);
    if (flagged) parts.push(`sent ${plural(flagged, "finding")} for review`);
    if (checked.length) parts.push(`a separate reviewer checked ${checked.reduce((n, [c]) => n + c, 0)}: ${checked.map(([n, w]) => `${n} ${w}`).join(", ")}`);
    if (byPerson) parts.push(`a person rejected ${byPerson} after a reviewer found ${byPerson === 1 ? "it conflicts" : "them in conflict"} with saved findings`);
    const joined = parts.join("; "), note = joined ? joined[0].toUpperCase() + joined.slice(1) + "." : "";
    if (waiting && deposit.reviewStatus !== "failed") return {label: `${plural(waiting, "finding")} waiting for review`, tone: "neutral", note: note + known + reusedText};
    if (deposit.consistency?.waiting && deposit.reviewStatus !== "failed") return {label: "Being compared with saved findings", tone: "neutral", note: note + known + reusedText};
    if (deposit.reviewStatus === "failed") return {label: "Review did not finish", tone: "warn", note: note + (deposit.reviewAttempts >= 2 ? " No automatic retries remain." : " One automatic retry remains.") + known + reusedText};
    return {label: added && !checked.length ? "Findings added" : "Findings saved", tone: counts.unsupported ? "warn" : "good", note: note + known + reusedText};
  }

  /** What an answer outside the workspace's scope says about its findings (`depositState` `skipped`). */
  const OUTSIDE_SCOPE = "The question is outside this assistant’s scope, so it was answered but its findings were not saved for later questions.";
  /** Why an answer's findings were not saved, in researcher language: a short label and the reason in the note. */
  const DEPOSIT_FAILURES = {
    timeout: ["out of time", "writing them reached its time limit"],
    quota: ["usage limit reached", "your subscription reached its usage limit"],
    "rate-limited": ["engine busy", "the engine was receiving too many requests"],
    "not-signed-in": ["not signed in", "the engine was not signed in"],
    rejected: ["request rejected", "the provider rejected the request"],
    "invalid-output": ["no usable reply", "the engine finished without a usable list of findings, twice"],
    crashed: ["session stopped", "the session stopped unexpectedly"],
    interrupted: ["app stopped", "the app stopped while they were being saved"],
  };
  /** What an answer's section on what it saved says: that it is saving, then what was added, waits for review or was
      already known. The section is there from the moment the answer is, so its absence never reads as "nothing".
      `groups` are its sources (`savedBySource`): the ones findings came from are counted, and the rest mentioned. */
  function savedSummary(task, groups = []) {
    if (!task?.result) return null;
    if (task.origin === "legacy") return {tone: "neutral", headline: "Imported with an earlier answer", detail: "Answered before the current loop. Its reviewed findings were imported; the answer itself was not re-checked."};
    const saving = task.depositState, deposit = task.deposit, counts = deposit?.counts || {};
    if (saving?.status === "saving") return {tone: "neutral", busy: true, headline: "Saving what this answer read…",
      detail: "The answer is ready. The research agent is now writing down the values and sources it read, so later questions can use them; any that need checking then go to a separate reviewer. They will appear here once saved, and you can leave this page."};
    if (saving?.status === "skipped") return {tone: "neutral", headline: "Not saved: outside this assistant’s scope",
      detail: `${saving.message ? saving.message.trim().replace(/([^.!?])$/, "$1.") + " " : ""}${OUTSIDE_SCOPE} The owner can save such answers in Settings, under Scope.`};
    if (saving?.status === "failed") {
      const why = DEPOSIT_FAILURES[saving.reason] || ["did not finish", "saving them did not finish"];
      return {tone: "warn", headline: `Findings not saved: ${why[0]}`, detail: `The answer stands, but the values and sources it read were not saved: ${why[1]}. Later questions will not reuse them.`};
    }
    const duplicates = deposit?.duplicates || 0, were = duplicates === 1 ? "was" : "were";
    const known = duplicates ? ` ${plural(duplicates, "fact")} it read ${were} already in the knowledge base and ${were} not saved again.` : "";
    const notes = deposit?.notes ? ` It saved a note on each of the ${plural(deposit.notes, "source")} it read.` : "";
    if (!deposit?.findings) return {tone: "neutral", headline: "Nothing new to save", detail: ("The research agent found no new values to save." + known + notes).trim()};
    const byPerson = deposit.rejectedByPerson || 0;
    const checked = [[counts.supported, "confirmed"], [(counts.unsupported || 0) - byPerson, "rejected"], [counts.uncertain, "inconclusive"]].filter(([n]) => n > 0);
    const spot = list(task.findings).filter(f => f.status === "accepted" && f.spotCheck === "pending").length;
    const parts = [];
    if (counts.accepted) parts.push(`${formatCount(counts.accepted)} added on the research agent's reading of the source`);
    if (counts.unreviewed) parts.push(`${formatCount(counts.unreviewed)} waiting for a separate reviewer before later questions rely on them`);
    if (checked.length) parts.push(`${formatCount(checked.reduce((n, [c]) => n + c, 0))} checked by a separate reviewer: ${checked.map(([n, w]) => `${formatCount(n)} ${w}`).join(", ")}`);
    if (byPerson) parts.push(`${formatCount(byPerson)} rejected by a person after a reviewer found ${byPerson === 1 ? "it conflicts" : "them in conflict"} with saved findings`);
    const joined = parts.join("; "), sampled = spot ? ` A reviewer is also spot-checking ${formatCount(spot)} of the added ones.` : "";
    const sources = groups.filter(g => g.findings.length).length, empty = groups.length - sources;
    const others = empty ? ` Nothing was saved from ${plural(empty, "other source")} it read; ${empty === 1 ? "its note says" : "their notes say"} why.` : "";
    const waiting = deposit.waitingReview || 0, failed = deposit.reviewStatus === "failed", comparing = !!deposit.consistency?.waiting;
    const compared = consistencyText(deposit.consistency);
    return {tone: failed ? "warn" : "neutral", busy: (waiting > 0 || comparing) && !failed,
      headline: `${plural(deposit.findings, "finding")} saved${sources ? ` from ${plural(sources, "source")}` : ""}`,
      review: failed ? "Review did not finish" : waiting ? `${plural(waiting, "finding")} waiting for review` : comparing ? "Being compared with saved findings" : "",
      detail: ((joined ? joined[0].toUpperCase() + joined.slice(1) + "." : "") + sampled + compared + known + others
        + (failed ? (deposit.reviewAttempts >= 2 ? " The review did not finish and no automatic retries remain." : " The review did not finish; the loop will try it once more.") : "")).trim()};
  }

  /** What the review's comparison with saved knowledge found, as a sentence (empty when there was none). */
  function consistencyText(value) {
    if (!value || value.state !== "checked") return value?.waiting ? " Some values differ from saved ones; a reviewer is comparing them." : "";
    const found = value.conflicts ? `found ${plural(value.conflicts, "conflict")}` : "found no conflict";
    const open = value.open ? ` ${value.open === 1 ? "One waits" : `${formatCount(value.open)} wait`} for you in the Knowledge tab.` : "";
    return ` A reviewer compared them with ${plural(value.compared, "related saved finding")} and ${found}.${open}`;
  }
  /** Link parameters that name the document itself (`knowledge.DOCUMENT_PARAMETERS`). */
  const DOCUMENT_PARAMETERS = new Set(["doi", "dockey", "docid", "documentid", "id", "fid", "file", "filename", "path",
    "contentkey", "paperid", "articleid", "partnumber"]);
  /** One key per document, as the knowledge base files sources: its DOI (also from a doi.org URL), else its URL without
      scheme or fragment, and without query parameters other than those that name the document (`knowledge.source_key`). */
  function sourceKey(doi, url) {
    const clean = value => String(value || "").trim().toLowerCase();
    const named = clean(doi).replace(/^https:\/\/doi\.org\//, "").replace(/^doi:/, "");
    const key = named || (/^https?:\/\/(?:dx\.)?doi\.org\/(.+)$/.exec(clean(url)) || [])[1];
    if (key) return "doi:" + key;
    const address = clean(url).replace(/^https?:\/\/(www\.)?/, "").split("#")[0];
    const cut = address.indexOf("?");
    const bare = (cut < 0 ? address : address.slice(0, cut)).replace(/\/+$/, "");
    if (!bare) return "";
    const kept = cut < 0 ? [] : [...new URLSearchParams(address.slice(cut + 1))]
      .filter(([name, value]) => DOCUMENT_PARAMETERS.has(name) && value).map(([name, value]) => `${name}=${value}`).sort();
    return "url:" + bare + (kept.length ? "?" + kept.join("&") : "");
  }

  /** What an answer saved, one group per source: its notes and the findings read in it. Sources it read but saved no
      finding from (it lacked the value, or would not open) come last. */
  function savedBySource(findings, notes) {
    const groups = new Map();
    const group = (key, title, url) => {
      if (!groups.has(key)) groups.set(key, {key, title: "", url: "", readUrl: "", notes: [], findings: []});
      const found = groups.get(key);
      found.title ||= title || ""; found.url ||= url || "";
      return found;
    };
    list(findings).forEach((f, i) => group(sourceKey(f.source?.doi, f.source?.url) || `finding:${i}`, f.source?.title, f.source?.url).findings.push(f));
    list(notes).forEach((n, i) => { const found = group(sourceKey(n.doi, n.url) || `note:${i}`, n.title, n.url); found.notes.push(n); found.readUrl ||= n.readUrl || ""; });
    return [...groups.values()].sort((a, b) => (b.findings.length > 0) - (a.findings.length > 0));
  }

  /** Whether a saved answer still has a review coming: findings waiting for one, or values in tension with saved ones. */
  const reviewPending = task => !!task?.deposit?.waitingReview || !!task?.deposit?.consistency?.waiting;
  const savingFindings = task => task?.depositState?.status === "saving";
  /** History and Recent list conversations: a question with its follow-ups is one entry, under its first question, its
      follow-ups in the order they follow one another, most recently asked first. `tasks` is the task list. */
  function conversations(tasks) {
    const groups = new Map(), time = task => String(task.submittedAt || "");
    for (const task of list(tasks)) {
      const key = task.threadId || task.taskId;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(task);
    }
    return [...groups.values()].map(turns => {
      const ids = new Set(turns.map(t => t.taskId)), follows = new Map(turns.filter(t => t.parentId).map(t => [t.parentId, t]));
      const byTime = turns.slice().sort((a, b) => time(a).localeCompare(time(b)));
      const line = [];
      for (let at = byTime.find(t => !t.parentId || !ids.has(t.parentId)); at && !line.includes(at); at = follows.get(at.taskId)) line.push(at);
      const ordered = [...line, ...byTime.filter(t => !line.includes(t))];
      return {first: ordered[0], latest: ordered[ordered.length - 1], count: ordered.length, ids: ordered.map(t => t.taskId),
              asked: ordered.map(time).sort().pop()};
    }).sort((a, b) => b.asked.localeCompare(a.asked));
  }

  /** Whether a follow-up can be asked after the latest answer of a conversation, and what to say: none after a question
      that failed; not yet while it runs; at once while its findings are saved or reviewed, saying it waits for them. */
  function followGate(task) {
    if (!task || task.status === "failed") return null;
    if (task.outOfScope && !task.parentId) return null;  // Not researched, and no conversation to continue.
    if (taskState(task).busy) return {ready: false, message: "You can ask a follow-up once this answer is ready."};
    if (savingFindings(task) || reviewPending(task)) return {ready: true, note: "A follow-up asked now starts once this answer's findings are saved and checked, so it can use them."};
    return {ready: true, note: ""};
  }

  /** What an answer says when a reviewer has since rejected findings behind it: ones it cited, or ones it saved. */
  function rejectedNotice(saved, cited) {
    const parts = [];
    if (cited) parts.push(`${plural(cited, "saved finding")} this answer cites ${cited === 1 ? "was" : "were"} rejected after it was written`);
    if (saved) parts.push(`${formatCount(saved)} of the findings it saved ${saved === 1 ? "was" : "were"} rejected on review`);
    if (!parts.length) return "";
    const text = parts.join("; and ");
    return `${text[0].toUpperCase()}${text.slice(1)}, so a value it reports may be wrong. Check those before relying on it.`;
  }

  /** A question's row in History and Recent says what its answer saved, or that it is still saving. */
  function savedTag(task) {
    if (savingFindings(task)) return "Saving findings";
    if (task?.depositState?.status === "failed") return "Findings not saved";
    if (task?.depositState?.status === "skipped") return "Outside scope · not saved";
    const saved = task?.deposit?.findings ? `${plural(task.deposit.findings, "finding")} saved` : "";
    return reviewPending(task) ? (saved ? saved + " · review pending" : "Review pending") : saved;
  }
  /** What, once changed, redraws an answer whose findings are being saved or reviewed. */
  const depositKey = task => JSON.stringify([task?.depositState || null, task?.deposit || null]);

  /** Question progress for the answer view and history list. */
  function taskState(task) {
    const status = task?.status;
    if (status === "completed" && task.outOfScope) return {label: "Outside scope", tone: "neutral", busy: false};
    if (status === "completed") return {label: "Answered", tone: "good", busy: false};
    if (status === "running") {
      const p = task.progress;
      return {label: !p || (!p.waiting && progressDetail(task).stage === "question") ? "Reading the question…" : "Researching…", tone: "neutral", busy: true};
    }
    if (status === "queued") return {label: "Waiting to start…", tone: "neutral", busy: true};
    if (status === "failed") return {label: "Could not finish", tone: "bad", busy: false};
    return {label: sentenceCase(status || "unknown"), tone: "neutral", busy: false};
  }

  /** A question outside the workspace's scope was not researched: what it asks about, and a link to ask it elsewhere
      (`redirectUrl`: the owner's choice, else the chat of the engine that ran it). */
  function scopeNotice(task) {
    const url = safeURL(task?.redirectUrl);
    const host = url ? new URL(url).hostname.replace(/^www\./, "") : "";
    return `<div class="callout warn out-of-scope" role="note"><p><strong>Outside this assistant’s scope, so it was not researched.</strong> ${escapeHTML(task?.outOfScope || "")}</p>`
      + `<p class="muted small">Nothing was searched or saved.</p><div class="settings-actions">${url ? `<a class="primary-button" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">Ask it at ${escapeHTML(host)} ↗</a>` : ""}`
      + `<button type="button" class="secondary-button" data-copy-question>Copy the question</button></div></div>`;
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
    const activity = {knowledge: counts.knowledge + counts.lookups, web: counts.searches + counts.pages, writing: 0};
    // Until its first search, the session is reading the question (and deciding whether it is in scope at all): a
    // question declined as outside the scope never looks as if it was researched.
    const researching = activity.knowledge + activity.web > 0 || /^(checking local knowledge|searching|reading (?!the question)|using the web|following links)/.test(lower);
    const stage = !researching ? "question"
      : lower.startsWith("writing") ? "writing"
      : /web|^reading/.test(lower) || activity.web ? "web" : "knowledge";
    const at = STAGES.findIndex(([key]) => key === stage);
    const stages = STAGES.map(([key, label], index) => ({key, label,
      state: index === at ? "current" : index > at ? "pending" : activity[key] ? "done" : "skipped"}));
    const recorded = Number(p.elapsedSeconds) || 0, started = Date.parse(p.startedAt);
    const elapsed = task.status === "running" && Number.isFinite(started) ? Math.max(recorded, (currentTime - started) / 1000) : recorded;
    const limit = Number(p.budgetSeconds) || Number(task.budgetSeconds) || 0;
    // Waiting for the engine's turn (the last answer's findings, say): nothing has started, so no clock runs.
    const waiting = p.waiting === true;
    return {stage, stages, action, counts, sites: (p.sites || []).slice(0, 8), clock: formatClock(waiting ? 0 : elapsed), waiting,
            limit: limit ? formatDuration(limit) : "", percent: limit && !waiting ? Math.min(100, Math.round(elapsed / limit * 100)) : 0,
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
  const RUNTIME_ORDER = ["codex", "claude-code"];
  const LOGIN_HOSTS = {"codex": ["auth.openai.com", "auth0.openai.com", "chatgpt.com"], "claude-code": ["claude.ai", "claude.com", "console.anthropic.com", "platform.claude.com"]};
  /** Only the provider's own https sign-in pages become links. */
  function loginLink(value, runtime) {
    try {
      const url = new URL(value);
      return url.protocol === "https:" && (LOGIN_HOSTS[runtime] || []).includes(url.hostname) && !url.username && !url.password && !url.port ? url.href : null;
    } catch { return null; }
  }
  const runtimeLabel = runtime => RUNTIME_LABELS[runtime] || RUNTIME_LABELS.codex;

  const api = {progressDetail, formatClock, effortStats, failureMessage, quotaHint, loginLink, runtimeLabel, croppedViewBox, sectionTitle, escapeHTML, safeURL, sentenceCase, recordReference, formatDuration, formatCount, renderMath, renderInline, renderMarkdown, recordStatus, provenanceSummary, savedSummary, sourceKey, savedBySource, savedTag, conversations, followGate, scopeNotice, rejectedNotice, reviewPending, savingFindings, depositKey, taskState, knowledgeSummary, parseMolfile, fitTransform, bracketGeometry};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;

  // ---------------------------------------------------------------------------
  // Browser application
  // ---------------------------------------------------------------------------
  const $ = selector => document.querySelector(selector);
  const view = $("#view");
  const state = {routeToken: 0, csrf: "", status: null, account: null, pending: null, polymers: null, polymerQuery: "", timers: new Set(), meta: null, person: null, people: false};

  async function get(path, params = {}) {
    const url = new URL(path, location.origin);
    for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
    const response = await fetch(url, {headers: {Accept: "application/json"}, cache: "no-store"});
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && data.signIn) { showSignIn(); throw Object.assign(new Error(data.error), {signIn: true}); }
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    if (data.csrfToken) state.csrf = data.csrfToken;
    return data;
  }
  async function post(path, body) {
    const response = await fetch(path, {method: "POST", cache: "no-store", headers: {"Content-Type": "application/json", "X-OOPC-CSRF": state.csrf}, body: JSON.stringify(body)});
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && data.signIn) { showSignIn(); throw Object.assign(new Error(data.error), {signIn: true, data}); }
    if (!response.ok) throw Object.assign(new Error(data.error || "The request could not be completed"), {data});
    if (data.csrfToken) state.csrf = data.csrfToken;
    return data;
  }
  function showError(error) {
    if (error?.signIn) error = null;  // The sign-in form says it; no banner above it.
    $("#error-message").textContent = error?.message || String(error || "");
    $("#error-banner").hidden = !error;
  }
  const badge = (info, extra = "") => info ? `<span class="badge ${escapeHTML(info.tone)}" ${extra}>${escapeHTML(info.label)}</span>` : "";
  const dateLabel = value => { const d = new Date(value); return Number.isNaN(d.valueOf()) ? "" : d.toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"}); };
  function later(token, fn, ms) {
    const id = setTimeout(() => { state.timers.delete(id); if (token === state.routeToken) fn(); }, ms);
    state.timers.add(id);
  }

  // ----- People: a computer several people share (`oopc people`) asks each to sign in -----
  function showSignIn(message = "") {
    for (const id of state.timers) clearTimeout(id);
    state.timers.clear();
    recent.hidden = true;
    view.innerHTML = `<section class="sign-in"><h1>Sign in</h1>
      <p class="muted">Several people share this computer’s research knowledge. Your questions and answers stay yours; the findings they save are shared.</p>
      <form id="sign-in-form" class="sign-in-form">
        <label>Name<input name="name" autocomplete="username" required maxlength="40"></label>
        <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
        <p class="inline-error" role="alert"${message ? "" : " hidden"}>${escapeHTML(message)}</p>
        <button type="submit" class="primary-button">Sign in</button>
      </form></section>`;
    $("#sign-in-form").addEventListener("submit", async event => {
      event.preventDefault();
      const form = new FormData(event.target);
      try {
        if (!state.csrf) await get("/api/session");
        await post("/api/session", {name: String(form.get("name") || ""), password: String(form.get("password") || "")});
        location.reload();
      } catch (error) { showSignIn(error.message); }
    });
    $("#sign-in-form [name=name]").focus();
  }
  async function loadSession() {
    const value = await get("/api/session");
    state.people = Boolean(value.people);
    state.person = value.person || null;
    $("#person-section").hidden = !state.person;
    if (state.person) $("#person-name").textContent = `Signed in as ${state.person.name}${state.person.owner ? " (owner)" : ""}.`;
    // Settings, the loop and background research are the owner's.
    $("#knowledge-section").hidden = $("#scope-section").hidden = Boolean(state.person && !state.person.owner);
    return value;
  }

  // ----- Routing -----
  const TABS = ["ask", "polymers", "knowledge", "history", "about"];
  function route() {
    state.routeToken++;
    for (const id of state.timers) clearTimeout(id);
    state.timers.clear();
    showError(null);
    const [section = "ask", id] = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
    const tab = TABS.includes(section) ? section : "ask";
    recent.hidden = tab !== "ask";
    if (recent.hidden) showRecent(false);
    for (const link of document.querySelectorAll(".tabs a")) {
      if (link.dataset.tab === tab) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    }
    const token = state.routeToken;
    const render = {ask: () => id ? renderAnswer(id, token) : renderAsk(token), polymers: () => renderPolymers(id, token), knowledge: () => renderKnowledge(token), history: () => renderHistory(token),
                    about: () => window.OOPCAbout.render(view)}[tab];
    Promise.resolve(render()).catch(error => { if (token === state.routeToken) showError(error); });
    window.scrollTo(0, 0);
  }

  // ----- Recent questions: a drawer beside Ask and every answer, so it stays open from one answer to the next -----
  const recent = $("#recent"), recentTab = $("#recent .recent-tab");
  const recentOpen = () => recentTab.getAttribute("aria-expanded") === "true";
  const showRecent = open => recentTab.setAttribute("aria-expanded", open);
  /** Whether the open drawer covers the page's text, as on narrower screens, where it closes once used. */
  const recentCovers = () => recent.getBoundingClientRect().right > view.getBoundingClientRect().left + parseFloat(getComputedStyle(view).paddingLeft);
  let recentLoad = 0;
  async function refreshRecent(currentId) {
    const load = ++recentLoad, listing = await get("/api/tasks").catch(() => null);
    if (load !== recentLoad) return;
    if (!listing) { if (!$("#recent-list .task-row")) $("#recent-list").innerHTML = `<p class="muted">Recent questions could not be loaded.</p>`; return; }
    $("#recent-list").innerHTML = listing.tasks.length ? conversations(listing.tasks).slice(0, 8).map(group => conversationRow(group, currentId)).join("")
      : `<p class="muted">Questions you ask will appear here.</p>`;
  }
  function wireRecent() {
    recentTab.addEventListener("click", () => showRecent(!recentOpen()));
    recent.addEventListener("keydown", event => { if (event.key === "Escape" && recentOpen()) { showRecent(false); recentTab.focus(); } });
    recent.addEventListener("click", event => {
      const link = event.target.closest("a");
      if (!link) return;
      if (recentCovers()) showRecent(false);
      if (!link.matches("[data-new-question]")) return;
      // A new question starts from an empty box, ready to type in.
      state.prefill = null; state.pending = null; state.focusQuestion = true;
      const field = $("#question");
      if (location.hash === "#/ask" && field) { field.value = ""; field.dispatchEvent(new Event("input", {bubbles: true})); field.focus(); state.focusQuestion = false; }
    });
    view.addEventListener("click", () => { if (recentOpen() && recentCovers()) showRecent(false); });
  }

  // ----- Ask -----
  async function loadTaskStatus() {
    const [status, runtimes] = await Promise.all([get("/api/tasks/status"), get("/api/runtimes").catch(() => null)]);
    state.status = status; state.runtimes = runtimes;
    state.account = runtimes?.runtimes?.[runtimes.selected]?.account || {status: "error"};
    adoptDepths(status.depths);
    return {status, runtimes};
  }
  /** The server's depth table (oopc/ask.py) is the one in force; the copy here only labels them until it loads. */
  function adoptDepths(depths) {
    for (const [key, depth] of Object.entries(depths || {})) {
      if (DEPTHS[key] && isCount(depth?.searches) && isCount(depth?.sources)) Object.assign(DEPTHS[key], {searches: depth.searches, sources: depth.sources});
    }
  }
  const selectedRuntime = () => state.runtimes?.selected || "codex";
  function readiness() {
    const {status, account} = state, label = runtimeLabel(selectedRuntime());
    if (!status || !account || account.status === "checking") return {ready: false, message: `Checking your ${label} connection…`};
    if (account.status === "login-pending") return {ready: false, message: `Finish signing in to ${label} to ask questions.`};
    if (account.status !== "connected") return {ready: false, message: account.status === "unavailable" || account.status === "unsupported" ? `${account.message || `${label} is unavailable.`} Choose another engine.` : `Sign in to ${label} to ask questions.`};
    if (!status.available) return {ready: false, message: status.reason || "Questions are unavailable right now."};
    return {ready: true, message: status.queued ? `${plural(status.queued, "question")} ahead of yours` : ""};
  }
  /** One chip per engine under the ask box: a signed-in engine is chosen with a click; one that is not opens its sign-in in Settings. */
  function engineChips() {
    const runtimes = state.runtimes?.runtimes || {}, selected = selectedRuntime();
    return RUNTIME_ORDER.filter(id => runtimes[id]).map(id => {
      const status = runtimes[id].account?.status;
      const note = {connected: "", checking: "Checking…", "login-pending": "Finish sign-in", disconnected: "Sign in"}[status] ?? "Unavailable";
      const action = status === "connected" ? `data-engine="${id}"` : status === "checking" ? "disabled" : `data-open-settings="${id}"`;
      return `<button type="button" class="engine${status === "connected" ? " ready" : ""}" data-runtime="${id}" ${action} aria-pressed="${id === selected}">${escapeHTML(runtimeLabel(id))}${note ? ` <b>${note}</b>` : ""}</button>`;
    }).join("");
  }

  // Pre-submit hint only; the engine enforces its own limits.
  function quotaHint(quota, reserve, label) {
    if (!quota) return "";
    if (typeof quota.remainingPercent !== "number") return quota.reason === "unrecognized-report" ? `${label} usage could not be read (its usage report changed format).` : quota.reason === "not-reported" ? `${label} does not report its usage limits to this app.` : "";
    const left = `${label} has ${Math.round(quota.remainingPercent)}% of its usage window left`;
    return typeof reserve === "number" && quota.remainingPercent < reserve ? `${left}; background review waits until it is above ${reserve}%.` : `${left}.`;
  }

  /** The question box: the Ask page's, or a follow-up's under the latest answer of a conversation. */
  const askFormHTML = (followUp = false) => `
        <form id="ask-form" class="ask-form" novalidate>
          <label class="visually-hidden" for="question">${followUp ? "Your follow-up question" : "Your question"}</label>
          <textarea id="question" rows="${followUp ? 2 : 4}" minlength="10" maxlength="8000" required placeholder="${followUp ? "Ask a follow-up about this answer…" : "How does annealing temperature affect the tensile modulus of PLA films?"}"></textarea>
          <div class="ask-bar">
            <fieldset class="depth-choice"><legend class="visually-hidden">Depth</legend>${Object.entries(DEPTHS).map(([key, depth]) =>
              `<label title="About ${depth.searches} web searches and ${depth.sources} sources"><input type="radio" name="depth" value="${key}"${key === "standard" ? " checked" : ""}><span>${depth.label}</span></label>`).join("")}</fieldset>
            <button id="ask-submit" class="primary-button" type="submit" disabled>${followUp ? "Ask follow-up" : "Ask"}</button>
          </div>
        </form>
        <div class="ask-status"><span id="engines-label" class="muted small">Runs on</span><span id="ask-engines" class="engines" role="group" aria-labelledby="engines-label"></span><span id="ask-readiness" class="muted small" role="status"></span></div>
        ${followUp ? `<p id="ask-note" class="muted small" hidden></p>` : ""}
        <p id="ask-quota" class="muted small" role="status" hidden></p>
        <p id="ask-error" class="inline-error" role="alert" hidden></p>`;

  async function renderAsk(token) {
    view.innerHTML = `
      <section class="ask">
        <p class="full-name"><b>O</b>pen <b>O</b>ntology of <b>P</b>olymer <b>C</b>hemistry</p>
        <h1>Ask your knowledge base, improve your knowledge base</h1>${askFormHTML()}
      </section>`;
    refreshRecent(null);
    await wireAskForm(token);
  }

  /** Wires the question box. A follow-up's has `follow`: the question it continues (`parent()`) and whether it can be
      asked yet (`gate()`, `followGate`). */
  async function wireAskForm(token, follow = null) {
    state.pending = null;
    const form = $("#ask-form"), submit = $("#ask-submit"), depthValue = () => form.elements.depth.value;
    const askError = error => { $("#ask-error").textContent = error?.message || ""; $("#ask-error").hidden = !error; };
    $("#ask-engines").addEventListener("click", event => {
      const chip = event.target.closest("[data-engine]");
      if (chip && chip.dataset.engine !== selectedRuntime()) chooseRuntime(chip.dataset.engine, askError);
    });
    let shownChips = "";
    const update = () => {
      for (const choice of form.querySelectorAll("[name=depth]")) {
        const known = DEPTHS[choice.value];
        choice.closest("label").title = `About ${known.searches} web searches and ${known.sources} sources`;
      }
      const gate = follow?.gate(), ready = gate && !gate.ready ? {ready: false, message: gate.message} : readiness();
      const depth = DEPTHS[depthValue()];
      const chips = engineChips();
      if (chips !== shownChips) {
        // Redrawing the chips keeps keyboard focus on the one that had it.
        const focused = document.activeElement?.closest?.("#ask-engines [data-runtime]")?.dataset.runtime;
        $("#ask-engines").innerHTML = shownChips = chips;
        if (focused) $(`#ask-engines [data-runtime="${focused}"]`)?.focus();
      }
      $("#ask-readiness").textContent = ready.ready ? [`about ${depth.sources} sources`, ready.message].filter(Boolean).join(" · ") : ready.message;
      if ($("#ask-note")) { $("#ask-note").textContent = gate?.note || ""; $("#ask-note").hidden = !gate?.note; }
      submit.disabled = !ready.ready || $("#question").value.trim().length < 10 || state.submitting;
    };
    if (state.prefill && !follow) { $("#question").value = state.prefill.question; state.prefill = null; }
    if (state.focusQuestion && !follow) { $("#question").focus(); state.focusQuestion = false; }
    state.updateAsk = () => { if (token === state.routeToken && form.isConnected) update(); };
    form.addEventListener("input", () => { state.pending = null; update(); });
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (submit.disabled) return;
      const error = $("#ask-error"); error.hidden = true;
      state.submitting = true; update();
      state.pending ||= {taskId: crypto.randomUUID().replaceAll("-", ""), question: $("#question").value.trim(),
        depth: depthValue(), authorizeSubscription: true, runtime: selectedRuntime(), ...(follow ? {parentId: follow.parent()} : {})};
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
      if (!hint) return;
      hint.hidden = true;
      try {
        const quota = await get("/api/runtimes/quota");
        if (token !== state.routeToken || quota.runtime !== selectedRuntime()) return;
        hint.textContent = quotaHint(quota, undefined, runtimeLabel(quota.runtime));
        hint.hidden = !hint.textContent;
      } catch { /* A hint only. */ }
    };
    state.refreshAskQuota();
  }
  /** One conversation in History and Recent: its first question, its latest follow-up when it has one, and the latest
      question's state and what its answer saved. It opens at the latest question; `currentId` marks the one shown. */
  function conversationRow(group, currentId = null) {
    const {first, latest, count} = group, status = taskState(latest);
    const origin = first.origin === "research" ? `<span class="tag">Research queue</span>` : first.origin === "legacy" ? `<span class="tag">Earlier</span>` : "";
    return `<a class="task-row" href="#/ask/${encodeURIComponent(latest.taskId)}"${group.ids.includes(currentId) ? ' aria-current="page"' : ""}><span class="task-question">${escapeHTML(first.question)}</span>${count > 1 ? `<span class="task-latest">${escapeHTML(latest.question)}</span>` : ""}<span class="task-meta">${origin}${count > 1 ? `<span class="tag">${plural(count, "question")}</span>` : ""}${badge(status)}${savedTag(latest) ? `<span class="tag">${escapeHTML(savedTag(latest))}</span>` : ""}<time>${escapeHTML(dateLabel(latest.submittedAt))}</time></span></a>`;
  }

  /** An answer's page is its whole conversation: each question with its answer, sources and what it saved, first
      question first, then a box for a follow-up to the latest. With `quiet`, the conversation is redrawn in place (an
      answer arrived, or findings were saved or reviewed) and the follow-up box is left as it is. */
  async function renderAnswer(taskId, token, quiet = false) {
    refreshRecent(taskId);
    if (!quiet || !view.querySelector(".conversation")) view.innerHTML = `<a class="back-link" href="#/ask">← Ask another question</a><div class="conversation"><article class="answer"><p class="muted">Loading…</p></article></div><div class="follow-up-slot"></div>`;
    const [task, polymers] = await Promise.all([get(`/api/tasks/${encodeURIComponent(taskId)}`), loadPolymers().catch(() => [])]);
    if (token !== state.routeToken) return;
    const ids = list(task.thread).map(turn => turn.taskId);
    const turns = ids.length > 1 ? await Promise.all(ids.map(id => id === task.taskId ? task : get(`/api/tasks/${encodeURIComponent(id)}`))) : [task];
    if (token !== state.routeToken) return;
    const names = new Map(polymers.map(p => [p.id, p.name])), record = code => recordReference(code, names);
    // Each drawing starts its own watchers; a newer drawing retires the older one's.
    const drawing = state.answerDrawing = (state.answerDrawing || 0) + 1;
    const live = () => token === state.routeToken && drawing === state.answerDrawing;
    const redraw = () => { if (live()) renderAnswer(taskId, token, true); };
    const conversation = view.querySelector(".conversation");
    conversation.classList.toggle("thread", turns.length > 1);
    conversation.innerHTML = turns.map(turn => `<article class="answer" data-task="${escapeHTML(turn.taskId)}"></article>`).join("");
    turns.forEach((turn, index) => renderTurn(turn, conversation.children[index], {index, record, token, live, redraw}));
    const latest = turns[turns.length - 1];
    state.followParent = latest.taskId;
    state.followGate = followGate(latest);
    const slot = view.querySelector(".follow-up-slot");
    if (!state.followGate) slot.innerHTML = "";
    else if (!slot.firstChild) {
      slot.innerHTML = `<section class="follow-up" aria-labelledby="follow-up-title"><h2 id="follow-up-title">Ask a follow-up</h2>${askFormHTML(true)}</section>`;
      wireAskForm(token, {parent: () => state.followParent, gate: () => state.followGate});
    } else state.updateAsk?.();
    if (!quiet && task.taskId !== turns[0].taskId) conversation.querySelector(`[data-task="${CSS.escape(task.taskId)}"]`)?.scrollIntoView({block: "start"});
  }

  /** One question of a conversation and its answer. `index` numbers its sources and section ids apart from the others'. */
  function renderTurn(task, article, {index, record, token, live, redraw}) {
    const prefix = `t${index + 1}-`, follow = index > 0;
    const status = taskState(task), provenance = provenanceSummary(task), result = task.result;
    const citations = list(result?.citations).filter(c => typeof c === "string");
    const cite = id => { const at = citations.indexOf(id); return at >= 0 ? at + 1 : null; };
    const inline = {cite, record, prefix};
    const limitations = list(result?.limitations).filter(Boolean);
    const openQuestions = list(result?.openQuestions).filter(Boolean);
    const findings = list(task.findings), groups = savedBySource(findings, task.notes), known = list(task.alreadyKnown);
    const saved = savedSummary(task, groups), heading = follow ? "h2" : "h1";
    const rejectedSaved = findings.filter(f => f.status === "unsupported").length;
    article.innerHTML = `
      <header class="answer-header">
        <p class="eyebrow">${follow ? "Follow-up" : task.origin === "research" ? "Research queue" : task.origin === "legacy" ? "Earlier question" : "Question"} · ${escapeHTML(dateLabel(task.submittedAt))} · ${escapeHTML(runtimeLabel(task.workerRuntime))}</p>
        <${heading} class="question-text${String(task.question).length > 180 ? " long" : ""}">${escapeHTML(task.question)}</${heading}>
        ${status.busy ? "" : `<div class="answer-state">${result && provenance && !task.outOfScope ? `<button type="button" class="state-jump" data-jump="saved-${prefix}" title="${escapeHTML(provenance.note || "")}" aria-label="${escapeHTML(provenance.label)}: see what this answer saved">${badge(provenance)}<span class="jump-arrow" aria-hidden="true">↓</span></button>` : badge(status)}</div>`}
      </header>
      ${status.busy ? activityBlock(task, status) : ""}
      ${task.status === "failed" ? `<div class="callout bad"><p>${escapeHTML(failureMessage(task.error))}</p>${task.canRetry ? `<button type="button" class="secondary-button" data-retry>Try again</button><p class="inline-error retry-error" role="alert" hidden></p>` : `<button type="button" class="secondary-button" data-reask>Ask this again</button>`}</div>` : ""}
      ${task.outOfScope ? scopeNotice(task) : result ? `
        <div class="callout warn rejected-notice" role="note"${rejectedSaved ? "" : " hidden"}>${escapeHTML(rejectedNotice(rejectedSaved, 0))}</div>
        <div class="answer-body prose">${renderMarkdown(result.answer, inline)}</div>
        ${limitations.length ? `<details class="limitations"><summary>Limitations noted with this answer (${limitations.length})</summary><ul>${limitations.map(item => `<li>${renderInline(item, inline)}</li>`).join("")}</ul></details>` : ""}
        <section class="sources" aria-labelledby="sources-${prefix}title"><h2 id="sources-${prefix}title">Sources</h2>${citations.length ? `<ol>${citations.map((id, i) => `<li id="source-${prefix}${i + 1}" data-record="${escapeHTML(id)}">${safeURL(id) ? sourceLink(id) : `<span class="muted small">Loading…</span>`}</li>`).join("")}</ol>` : `<p class="muted">This answer cites no sources.</p>`}</section>
        ${saved ? `<section class="saved" id="saved-${prefix}" aria-labelledby="saved-${prefix}title"><h2 id="saved-${prefix}title">What this answer saved</h2>
          <div class="saved-status${saved.tone === "warn" ? " warn" : ""}" role="status"><p class="saved-headline">${saved.busy ? `<span class="pulse" aria-hidden="true"></span>` : ""}<strong>${escapeHTML(saved.headline)}</strong>${saved.review ? `<span class="tag">${escapeHTML(saved.review)}</span>` : ""}</p>${saved.detail ? `<p class="saved-detail">${escapeHTML(saved.detail)}</p>` : ""}</div>
          ${groups.length && !savingFindings(task) ? `<ol class="saved-sources">${groups.map(group => savedGroup(group, record)).join("")}</ol>` : ""}
          ${known.length ? `<details class="already-known"><summary>Already in the knowledge base (${formatCount(known.length)})</summary><p class="muted small">Facts this answer read that an earlier question had saved; they were not saved again.</p><ul class="finding-list">${known.map(f => findingItem(f, {record, origin: true})).join("")}</ul></details>` : ""}
        </section>` : ""}
        ${openQuestions.length && task.origin !== "legacy" ? `<section class="open-questions" aria-labelledby="open-${prefix}title"><h2 id="open-${prefix}title">Worth researching later</h2><ul>${openQuestions.map((q, i) => `<li><span>${escapeHTML(q)}</span> ${list(task.queuedResearch).includes(q) ? `<span class="tag">In the research queue</span>` : `<button type="button" class="text-button" data-research="${i}">Add to research queue</button>`}</li>`).join("")}</ul><p class="muted small research-status" role="status">${list(task.queuedResearch).length ? `Added to the <a href="#/knowledge">research queue</a> automatically.` : ""}</p></section>` : ""}
        <section class="how-found" aria-labelledby="how-${prefix}title"><h2 id="how-${prefix}title">How this answer was found</h2><div>${howFound(task, citations)}</div></section>` : ""}`;
    if (status.busy) watchActivity(task, article, {token, live, redraw});
    else if (savingFindings(task) || reviewPending(task)) watchDeposit(task, {token, live, redraw});
    article.querySelector("[data-reask]")?.addEventListener("click", () => { state.prefill = {question: task.question}; location.hash = "#/ask"; });
    article.querySelector("[data-copy-question]")?.addEventListener("click", async event => {
      try { await navigator.clipboard.writeText(task.question); event.target.textContent = "Copied"; }
      catch { event.target.textContent = "Select the question above to copy it"; }
    });
    article.querySelector("[data-retry]")?.addEventListener("click", async event => {
      event.target.disabled = true;
      try { if (!state.csrf) await loadTaskStatus(); await post(`/api/tasks/${encodeURIComponent(task.taskId)}/retry`, {authorizeSubscription: true}); redraw(); }
      catch (error) { const note = article.querySelector(".retry-error"); note.textContent = error.message; note.hidden = false; event.target.disabled = false; }
    });
    for (const button of article.querySelectorAll("[data-research]")) button.addEventListener("click", async () => {
      button.disabled = true;
      try { if (!state.csrf) await loadTaskStatus(); await post("/api/research", {question: openQuestions[Number(button.dataset.research)], fromQuestion: task.taskId}); button.textContent = "Added"; }
      catch (error) { article.querySelector(".research-status").textContent = error.message; button.disabled = false; }
    });
    if (!result || task.outOfScope) return;
    // Cited findings load with their status now; one a reviewer has rejected since is said at the top of the answer.
    Promise.all(citations.map(async (id, at) => {
      if (safeURL(id)) return null;
      const item = article.querySelector(`#source-${prefix}${at + 1}`);
      try {
        const source = await get("/api/record", {id});
        if (!live() || !item) return null;
        item.innerHTML = sourceEntry(source);
        return source;
      } catch { if (item && live()) item.innerHTML = `<span>${escapeHTML(id)}</span>`; return null; }
    })).then(sources => {
      const rejectedCited = sources.filter(source => source?.statement && source.status === "unsupported").length;
      const notice = article.querySelector(".rejected-notice");
      if (!live() || !notice || !rejectedCited) return;
      notice.textContent = rejectedNotice(rejectedSaved, rejectedCited);
      notice.hidden = false;
    });
  }
  function howFound(task, citations) {
    const stats = effortStats(task.effort), reused = task.reusedFindings || {}, sites = list(task.effort?.sites);
    if (!stats.length) return `<p class="muted small">Retrieval was not recorded for this answer.</p>`;
    // Tokens belong to the developer inspector; the researcher sees what was reused, searched and cited.
    const shown = [{value: (reused.supported || 0) + (reused.added || 0), label: "saved findings reused", lead: true},
      ...stats.filter(s => s.label !== "tokens"), {value: citations.length, label: `source${citations.length === 1 ? "" : "s"} cited`}];
    return `<ul class="stat-row">${shown.map(s => `<li${s.lead ? ` class="lead"` : ""}><strong>${formatCount(s.value)}</strong><span>${escapeHTML(s.label)}</span></li>`).join("")}</ul>${sites.length ? `<p class="muted small">Sites read: ${sites.map(escapeHTML).join(", ")}</p>` : ""}`;
  }
  /** One finding. `grouped`: listed under its source, so only its location is given; `record` links its polymer, which
      adds the details it was saved with (material, conditions, the quote); `origin` links the question that saved it. */
  function findingItem(finding, {grouped = false, record = null, origin = false} = {}) {
    const status = recordStatus(finding), source = finding.source || {}, url = safeURL(source.url);
    const quantity = [finding.value, finding.unit].filter(Boolean).join(" ");
    // Saved by another person's question on a shared computer: their name, never a link to their question.
    const theirs = finding.savedBy && finding.savedBy !== state.person?.name;
    const saver = theirs ? ` · saved by ${escapeHTML(finding.savedBy)}` : origin && /^[a-f0-9]{32}$/.test(finding.questionId || "") ? ` · saved by <a href="#/ask/${finding.questionId}">an earlier question</a>` : "";
    const place = grouped ? escapeHTML(finding.locator || "")
      : `${url ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(source.title || url)} ↗</a>` : escapeHTML(source.title || "")}${finding.locator ? ` · ${escapeHTML(finding.locator)}` : ""}`;
    const polymer = record && finding.subject ? record(finding.subject) : null;
    const details = record ? [["Material", escapeHTML(finding.material)], ["Property", escapeHTML(finding.property)],
      ["Conditions", escapeHTML(finding.conditions)], ["Filed under", polymer ? `<a href="${escapeHTML(polymer.href)}">${escapeHTML(polymer.label)}</a>` : ""],
      ["Quote", finding.excerpt ? `<q>${escapeHTML(finding.excerpt)}</q>` : ""]].filter(([, value]) => value) : [];
    const disagrees = list(finding.conflictsWith).length;
    const conflictTag = disagrees ? ` <span class="tag conflict-tag" title="A reviewer compared it with saved knowledge and found it disagrees with ${disagrees === 1 ? "another finding" : "other findings"}; report both with their sources.">Disagrees with ${plural(disagrees, "saved finding")}</span>` : "";
    return `<li class="finding">${badge(status, `title="${escapeHTML(status.note)}"`)}${finding.status === "accepted" && finding.spotCheck === "pending" ? ` <span class="tag">Being spot-checked</span>` : ""}${conflictTag} <span class="finding-statement">${escapeHTML(finding.statement)}</span>${quantity ? ` <span class="finding-value">${escapeHTML(quantity)}</span>` : ""}
      ${place || saver ? `<span class="finding-source muted small">${place}${saver}</span>` : ""}
      ${finding.review?.reason ? `<span class="finding-reason small">${finding.review.engine === "person" ? "Settled by a person" : "Reviewer"}: ${renderInline(finding.review.reason)}</span>` : finding.status === "unreviewed" && finding.reviewFlag ? `<span class="finding-reason small">Sent for review: ${escapeHTML(finding.reviewFlag)}</span>` : ""}${finding.originalStatement ? `<span class="finding-reason small">Reworded from the earlier record, imported as “${escapeHTML(finding.originalStatement)}”.</span>` : ""}
      ${details.length ? `<details class="finding-details"><summary>Details</summary><dl>${details.map(([term, value]) => `<dt>${term}</dt><dd>${value}</dd>`).join("")}</dl></details>` : ""}</li>`;
  }
  /** One source an answer read, with its notes and the findings saved from it. */
  function savedGroup(group, record) {
    const url = safeURL(group.url), read = safeURL(group.readUrl), title = group.title || group.url || "Source";
    const host = read && read !== url ? (() => { try { return new URL(read).hostname.replace(/^www\./, ""); } catch { return ""; } })() : "";
    return `<li class="saved-source"><div class="saved-source-head"><span class="source-title">${url ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(title)} ↗</a>` : escapeHTML(title)}</span>${group.findings.length ? `<span class="muted small">${plural(group.findings.length, "finding")}</span>` : `<span class="tag">Nothing saved from it</span>`}</div>
      ${group.notes.map(note => note.supports ? `<p class="saved-note">${escapeHTML(note.supports)}</p>` : "").join("")}${host ? `<p class="muted small">Read at <a href="${escapeHTML(read)}" target="_blank" rel="noopener noreferrer">${escapeHTML(host)} ↗</a></p>` : ""}
      ${group.findings.length ? `<ul class="finding-list">${group.findings.map(f => findingItem(f, {grouped: true, record})).join("")}</ul>` : ""}</li>`;
  }
  function activityBlock(task, status) {
    const live = progressDetail(task);
    return `<section class="progress-card" aria-live="polite">${live ? activityInner(live) : `<div class="progress-head"><span class="pulse" aria-hidden="true"></span><strong>${escapeHTML(status.label)}</strong><span class="progress-clock muted">up to ${Number(task.budgetSeconds) / 60} min</span></div>`}
      <p class="progress-foot muted small">You can leave this page; the answer will be in History.</p></section>`;
  }
  function activityInner(live) {
    if (live.waiting) return `<div class="progress-head"><span class="pulse waiting" aria-hidden="true"></span><strong>Waiting for its turn</strong>${live.limit ? `<span class="progress-clock muted">${escapeHTML(live.limit)} limit starts when it begins</span>` : ""}</div>
      <p class="progress-now">${escapeHTML(live.action)}</p>`;
    if (live.stage === "question") return `<div class="progress-head"><span class="pulse" aria-hidden="true"></span><strong>Reading the question</strong><span class="progress-clock muted" data-clock>${escapeHTML(live.clock)}${live.limit ? ` / ${escapeHTML(live.limit)}` : ""}</span></div>
      <div class="progress-bar" aria-hidden="true"><span data-bar style="width:${live.percent}%"></span></div>
      <p class="progress-now">Checking that it is within this assistant’s scope before researching it.</p>`;
    const meter = (used, cap, word) => cap ? `<span class="meter"><span class="meter-label">${formatCount(used)} of ${formatCount(cap)} ${word}</span><span class="meter-track"><span style="width:${Math.min(100, Math.round(used / cap * 100))}%"></span></span></span>` : `<span class="meter"><span class="meter-label">${formatCount(used)} ${word}</span></span>`;
    return `<div class="progress-head"><span class="pulse" aria-hidden="true"></span><strong>${escapeHTML(STAGES.find(([k]) => k === live.stage)[1])}</strong><span class="progress-clock muted" data-clock>${escapeHTML(live.clock)}${live.limit ? ` / ${escapeHTML(live.limit)}` : ""}</span></div>
      <div class="progress-bar" aria-hidden="true"><span data-bar style="width:${live.percent}%"></span></div>
      <ol class="stage-track">${live.stages.map(s => `<li class="${s.state}"><span class="stage-dot" aria-hidden="true"></span>${escapeHTML(s.label)}</li>`).join("")}</ol>
      ${live.action ? `<p class="progress-now">${escapeHTML(live.action)}</p>` : ""}
      <div class="meters">${meter(live.counts.knowledge + live.counts.lookups, 0, "knowledge lookups")}${meter(live.counts.searches, live.budget?.searches, "web searches")}${meter(live.counts.sources, live.budget?.sources, "sources")}</div>
      ${live.sites.length ? `<p class="sites">${live.sites.map(site => `<span class="site">${escapeHTML(site)}</span>`).join("")}</p>` : ""}`;
  }
  /** While an answer's findings are saved or reviewed, poll quietly; redraw the conversation only when they change. */
  function watchDeposit(task, {token, live, redraw}) {
    const shown = depositKey(task), every = savingFindings(task) ? 5000 : 10000;
    const poll = async () => {
      if (!live()) return;
      try {
        const next = await get(`/api/tasks/${encodeURIComponent(task.taskId)}`);
        if (!live()) return;
        if (depositKey(next) !== shown) { redraw(); return; }
      } catch { /* Try again on the next poll. */ }
      later(token, poll, every);
    };
    later(token, poll, every);
  }
  /** While a question runs, refresh only its progress card: the clock each second, the rest every 3 s. */
  function watchActivity(task, article, {token, live, redraw}) {
    let current = task, started = Date.now(), shown = null;
    const box = () => article.querySelector(".progress-card");
    const tick = () => {
      if (!live() || !box()) return;
      const detail = progressDetail(current);
      const clock = box().querySelector("[data-clock]"), bar = box().querySelector("[data-bar]");
      if (detail && clock && !detail.waiting) { clock.textContent = detail.clock + (detail.limit ? ` / ${detail.limit}` : ""); bar.style.width = detail.percent + "%"; }
      later(token, tick, 1000);
    };
    const poll = async () => {
      if (!live()) return;
      try {
        const next = await get(`/api/tasks/${encodeURIComponent(task.taskId)}`);
        if (!live()) return;
        if (!taskState(next).busy) { redraw(); return; }
        current = next;
        const detail = progressDetail(current), head = box();
        const key = detail && JSON.stringify([detail.stage, detail.action, detail.counts, detail.sites]);
        if (detail && head && key !== shown) {  // Re-render only on change, so animations run smoothly.
          shown = key;
          head.innerHTML = activityInner(detail) + `<p class="progress-foot muted small">You can leave this page; the answer will be in History.</p>`;
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
    $("#history-list").innerHTML = listing.tasks.length ? conversations(listing.tasks).map(group => conversationRow(group)).join("") + (listing.omitted ? `<p class="muted small">${formatCount(listing.omitted)} older questions are not shown.</p>` : "")
      : `<p class="muted">You haven’t asked anything yet. <a href="#/ask">Ask a question</a>.</p>`;
    if (listing.tasks.some(task => taskState(task).busy || savingFindings(task) || reviewPending(task))) later(token, () => renderHistory(token), 5000);
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
      ${list(claims.findings).length ? `<section class="record-section findings"><h2>Findings from questions</h2><p class="muted small">Facts that answered questions read in their sources. Reviewed ones were checked against the source by a separate reviewer.</p><ul class="finding-list">${list(claims.findings).map(f => findingItem(f)).join("")}</ul></section>` : ""}
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
    const [loop, listing, open] = await Promise.all([get("/api/loop"), get("/api/knowledge", {status: filter, limit: 100}),
      get("/api/conflicts", {status: "open", limit: 50}).catch(() => ({conflicts: []}))]);
    if (token !== state.routeToken) return;
    const summary = knowledgeSummary(loop), research = loop.research || {}, researching = loop.settings?.researchPerWeek > 0;
    const counts = {supported: summary.supported, accepted: summary.accepted, "needs-checking": summary.unreviewed + summary.uncertain, unsupported: summary.unsupported};
    const last = list(loop.log)[0];
    // On a computer several people share, the loop, its log and the research queue are the owner's.
    const owner = !state.person || state.person.owner;
    view.querySelector(".knowledge").innerHTML = `
      <h1>What the memory knows</h1>
      <div class="status-card"><p class="headline">${escapeHTML(summary.headline)}</p>${summary.spotText ? `<p>${escapeHTML(summary.spotText)}</p>` : ""}</div>
      <section aria-labelledby="loop-title"><h2 id="loop-title">The loop</h2>
        <ol class="loop">${summary.stages.map((stage, i) => `<li class="loop-stage reached"><span class="loop-number">${i + 1}</span><span class="loop-title">${escapeHTML(stage.title)}</span><strong class="loop-value">${formatCount(stage.value)}</strong><span class="loop-text">${escapeHTML(stage.text)}</span></li>`).join("")}</ol>
        ${owner ? `<div class="loop-actions">
          <button type="button" id="loop-run" class="secondary-button"${loop.running ? " disabled" : ""}>${loop.running ? "Running…" : "Run the loop now"}</button>
          <p class="muted small">Reviews ${formatCount(summary.pending)} answer${summary.pending === 1 ? "" : "s"} waiting${researching ? ", then asks one queued question if this week's limit allows" : ""}.</p>
          <p id="loop-status" class="muted small" role="status">${loop.running ? "The loop is running." : last ? `Last run ${escapeHTML(dateLabel(last.finishedAt))}: ${escapeHTML(loopRunText(last))}` : "The loop has not run yet."}${loop.schedule?.installed ? " It also runs hourly in the background." : " It runs only when you start it."}</p>
        </div>` : ""}
      </section>
      <section aria-labelledby="findings-title"><h2 id="findings-title">Findings</h2>
        <div class="filter-row" role="tablist">${FILTERS.map(([key, label]) => `<button type="button" role="tab" class="filter${key === filter ? " selected" : ""}" aria-selected="${key === filter}" data-filter="${key}">${escapeHTML(label)} <span class="muted">${formatCount(counts[key])}</span></button>`).join("")}</div>
        ${list(listing.findings).length ? `<ul class="finding-list">${list(listing.findings).map(f => findingItem(f)).join("")}</ul>` : `<p class="muted">No findings here yet.</p>`}
      </section>
      ${conflictSection(list(open.conflicts), loop.settings?.conflictResolution)}
      ${owner ? `<section aria-labelledby="research-title"><h2 id="research-title">Research queue</h2>
        <p class="muted small">${researching ? `Gaps from your answers. The loop asks up to ${formatCount(research.weeklyLimit)} a week (${formatCount(research.askedThisWeek)} so far this week).` : "Background research is off. Set a weekly number in Settings and the loop will ask these, and your answers' open questions will join the queue."}</p>
        ${list(research.queue).length ? `<ul class="research-list">${list(research.queue).slice().reverse().map(item => `<li>${badge({label: item.status === "asked" ? "Asked" : "Waiting", tone: item.status === "asked" ? "good" : "neutral"})} ${item.questionId ? `<a href="#/ask/${encodeURIComponent(item.questionId)}">${escapeHTML(item.question)}</a>` : escapeHTML(item.question)}</li>`).join("")}</ul>` : `<p class="muted">Nothing queued. Add gaps from an answer's “Worth researching later” list.</p>`}
      </section>` : ""}`;
    for (const button of view.querySelectorAll("[data-filter]")) button.addEventListener("click", () => { state.knowledgeFilter = button.dataset.filter; renderKnowledge(token); });
    for (const button of view.querySelectorAll("[data-settle]")) button.addEventListener("click", async () => {
      const item = button.closest("[data-conflict]"), status = item.querySelector("[role=status]");
      for (const other of item.querySelectorAll("[data-settle]")) other.disabled = true;
      try { if (!state.csrf) await loadTaskStatus(); await post("/api/conflicts/settle", {id: item.dataset.conflict, resolution: button.dataset.settle}); renderKnowledge(token); }
      catch (error) { status.textContent = error.message; for (const other of item.querySelectorAll("[data-settle]")) other.disabled = false; }
    });
    const run = $("#loop-run");
    run?.addEventListener("click", async () => {
      run.disabled = true;
      try { if (!state.csrf) await loadTaskStatus(); await post("/api/loop/tick", {authorizeSubscription: true}); $("#loop-status").textContent = "The loop is running."; later(token, () => renderKnowledge(token), 4000); }
      catch (error) { $("#loop-status").textContent = error.message; run.disabled = false; }
    });
    if (loop.running) later(token, () => renderKnowledge(token), 5000);
  }
  /** How a reviewer read a conflict between a new finding and a saved one, and what a person can settle it as. */
  const READINGS = {"new-misread": "the new finding misstates its source", "saved-misread": "the saved finding misstates its source",
    "sources-disagree": "both findings read their sources correctly; the sources disagree", unresolved: "it could not settle it"};
  const SETTLE = [["new-misread", "New one is wrong"], ["saved-misread", "Saved one is wrong"], ["sources-disagree", "Sources disagree"], ["no-conflict", "Not a conflict"]];
  /** Conflicts waiting for a person: each pair, the reviewer's reading, and the four ways to settle it. */
  function conflictSection(conflicts, resolution) {
    if (!conflicts.length && resolution !== "person") return "";
    const item = c => `<li class="conflict" data-conflict="${escapeHTML(c.id)}">
        <p class="small"><strong>Reviewer’s reading:</strong> ${escapeHTML(READINGS[c.reading] || c.reading)}. ${c.reason ? renderInline(c.reason) : ""}</p>
        <p class="conflict-label muted small">New finding</p><ul class="finding-list">${c.finding ? findingItem(c.finding, {origin: true}) : `<li class="finding muted">No longer saved</li>`}</ul>
        <p class="conflict-label muted small">Saved finding</p><ul class="finding-list">${c.other ? findingItem(c.other, {origin: true}) : `<li class="finding muted">No longer saved</li>`}</ul>
        <div class="settings-actions">${SETTLE.map(([key, label]) => `<button type="button" class="secondary-button" data-settle="${key}">${label}</button>`).join("")}</div>
        <p class="muted small" role="status"></p></li>`;
    return `<section aria-labelledby="conflicts-title"><h2 id="conflicts-title">Conflicts to settle</h2>
      <p class="muted small">${conflicts.length ? "A reviewer compared new findings with saved ones and found these disagree. A finding you mark wrong is rejected; nothing you decide marks a finding reviewed." : "No conflicts are waiting for you. When a reviewer finds a new finding disagrees with a saved one, it waits here."}</p>
      ${conflicts.length ? `<ul class="conflict-list">${conflicts.map(item).join("")}</ul>` : ""}</section>`;
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
      return `<div class="runtime-option${id === selected ? " selected" : ""}" data-runtime="${escapeHTML(id)}">
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
      const depth = $("#consistency-depth"), level = String(value.consistencyDepth);
      if (![...depth.options].some(option => option.value === level)) depth.add(new Option(`Custom: ${level} for each`, level));
      depth.value = level;
      for (const input of settings.querySelectorAll("[name=conflict-resolution]")) input.checked = input.value === value.conflictResolution;
      $("#research-per-week").value = String(value.researchPerWeek);
      const parallel = $("#parallel-questions"), count = String(value.parallelQuestions || 1);
      if (![...parallel.options].some(option => option.value === count)) parallel.add(new Option(`${count} at once`, count));
      parallel.value = count;
      const scope = $("#scope-text");
      scope.value = value.scope || ""; scope.placeholder = value.defaultScope || "";
      $("#redirect-url").value = value.redirectUrl || "";
      $("#save-outside").value = String(Boolean(value.saveOutsideScope));
      $("#knowledge-error").hidden = $("#scope-error").hidden = true;
    } catch (error) { $("#knowledge-error").textContent = error.message; $("#knowledge-error").hidden = false; }
  }
  async function saveKnowledgeSetting(change, where = "#knowledge-error") {
    try { if (!state.csrf) await loadTaskStatus(); await post("/api/settings", change); $(where).hidden = true; }
    catch (error) { $(where).textContent = error.message; $(where).hidden = false; return; }  // What was typed stays.
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
  async function chooseRuntime(runtime, report = settingsError) {
    try {
      if (!state.csrf) await loadTaskStatus();
      await post("/api/runtimes/select", {runtime, authorizeRuntimeSelection: true});
      state.pending = null;
      report(null);
    } catch (error) { report(error); }
    await refreshSettings();
    await state.refreshAskQuota?.();
  }
  async function openSettings(runtime) {
    settings.showModal(); renderSettings(); loadKnowledgeSettings();
    await refreshSettings();
    // A sign-in chip on the Ask page lands on its engine's own button.
    if (runtime) settings.querySelector(`.runtime-option[data-runtime="${CSS.escape(runtime)}"]`)?.querySelector("[data-connect],a,[data-cancel]")?.focus();
  }

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
    $("#settings-button").addEventListener("click", () => openSettings());
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
      else if (event.target.id === "consistency-depth") saveKnowledgeSetting({consistencyDepth: Math.round(Number(event.target.value))});
      else if (event.target.id === "parallel-questions") saveKnowledgeSetting({parallelQuestions: Math.round(Number(event.target.value))});
      else if (event.target.name === "conflict-resolution") saveKnowledgeSetting({conflictResolution: event.target.value});
      else if (event.target.id === "research-per-week") saveKnowledgeSetting({researchPerWeek: Math.round(Number(event.target.value))});
      else if (event.target.id === "scope-text") saveKnowledgeSetting({scope: event.target.value}, "#scope-error");
      else if (event.target.id === "redirect-url") saveKnowledgeSetting({redirectUrl: event.target.value.trim()}, "#scope-error");
      else if (event.target.id === "save-outside") saveKnowledgeSetting({saveOutsideScope: event.target.value === "true"}, "#scope-error");
    });
    $("#error-dismiss").addEventListener("click", () => showError(null));
    wireRecent();
    document.addEventListener("click", event => {
      const settingsLink = event.target.closest("[data-open-settings]");
      if (settingsLink) openSettings(settingsLink.dataset.openSettings);
      const jump = event.target.closest("[data-jump]");
      if (jump) document.getElementById(jump.dataset.jump)?.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start"});
      const cite = event.target.closest("a.cite");
      if (cite) {
        event.preventDefault();
        const target = document.getElementById(`source-${cite.dataset.source}`);
        if (target) { target.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center"}); target.classList.add("flash"); setTimeout(() => target.classList.remove("flash"), 1600); }
      }
    });
    $("#sign-out").addEventListener("click", async () => {
      try { await post("/api/session/end", {signOut: true}); } catch { /* Signed out either way. */ }
      location.reload();
    });
    window.addEventListener("hashchange", route);
    if (!location.hash || location.hash.startsWith("#/improvement")) history.replaceState(null, "", location.hash.startsWith("#/improvement") ? "#/knowledge" : "#/ask");
    loadSession().then(session => {
      if (session.people && !session.person) showSignIn();
      else route();
    }).catch(() => route());
  }
  init();
})();
