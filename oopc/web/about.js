/* About page: theme, inline figures, double-click definitions and live counts.
   Browsing it issues read-only GETs and never starts agent work. The glossary in
   the page is the only source of definitions; the card is built from it. */
(function () {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const isCount = value => Number.isSafeInteger(value) && value >= 0;
  const TERM = "[data-term][role=button]";

  // ----- Theme, shared with the app through the same preference -----
  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("oopc-theme", theme); } catch { /* Preference is optional. */ }
    $("#theme-toggle")?.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} theme`);
  }
  let stored = null;
  try { stored = localStorage.getItem("oopc-theme"); } catch { /* Preference is optional. */ }
  setTheme(stored || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  $("#theme-toggle")?.addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));

  // ----- Glossary -----
  const glossary = new Map($$(".glossary .entry").map(entry => [entry.id.replace(/^term-/, ""), entry]));

  /** Make every known term outside the glossary focusable and announce that it opens a definition. */
  function prepareTerms(root) {
    for (const term of $$("[data-term]", root)) {
      if (!glossary.has(term.dataset.term)) { console.warn(`No glossary entry for "${term.dataset.term}"`); continue; }
      term.setAttribute("role", "button");
      term.setAttribute("tabindex", "0");
      term.setAttribute("aria-haspopup", "dialog");
      if (term instanceof HTMLElement) term.title = "Double-click for a definition";
    }
  }

  // ----- Figures: inlined so the page's tokens colour them and their labels open definitions -----
  async function inline(holder, name, className) {
    const response = await fetch(`about/${name}.svg`);
    if (!response.ok) throw new Error(`${name}: ${response.status}`);
    const parsed = new DOMParser().parseFromString(await response.text(), "image/svg+xml").documentElement;
    if (parsed.nodeName !== "svg") throw new Error(`${name}: not SVG`);
    const wrap = document.createElement("div");
    wrap.className = className;
    wrap.append(document.importNode(parsed, true));
    return wrap;
  }
  function loadFigures() {
    for (const holder of $$("[data-figure]")) {
      const parts = [inline(holder, holder.dataset.figure, "art-wide")];
      if (holder.dataset.narrow) parts.push(inline(holder, holder.dataset.narrow, "art-narrow"));
      Promise.all(parts)
        .then(wraps => { holder.replaceChildren(...wraps); prepareTerms(holder); })
        .catch(() => holder.classList.add("failed"));
    }
  }

  // ----- Definition card -----
  const card = document.createElement("div");
  card.className = "definition-card";
  card.hidden = true;
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-modal", "false");
  card.setAttribute("aria-labelledby", "definition-title");
  card.innerHTML = `<div class="definition-head"><p class="definition-group"></p><button type="button" class="definition-close" aria-label="Close definition">×</button></div>
    <h3 id="definition-title" tabindex="-1"></h3><div class="definition-body"></div>
    <div class="definition-related"></div>
    <div class="definition-foot"><button type="button" class="text-button definition-back" hidden>← Back</button></div>`;
  document.body.append(card);
  const sheet = matchMedia("(max-width: 640px)");
  let opener = null, trail = [], current = null;

  function show(id) {
    const entry = glossary.get(id);
    if (!entry) return;
    current = id;
    $(".definition-group", card).textContent = entry.closest(".glossary-group")?.querySelector("h3")?.textContent || "";
    $("h3", card).textContent = $("dt", entry).textContent;
    $(".definition-body", card).replaceChildren(...$$(".definition, .example", entry).map(node => node.cloneNode(true)));
    const related = $$(".see-also a", entry);
    const box = $(".definition-related", card);
    box.replaceChildren();
    if (related.length) {
      const label = document.createElement("span");
      label.textContent = "Related";
      box.append(label, ...related.map(link => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "text-button";
        button.dataset.related = link.getAttribute("href").replace(/^#term-/, "");
        button.textContent = link.textContent;
        return button;
      }));
    }
    box.hidden = !related.length;
    $(".definition-back", card).hidden = !trail.length;
  }
  function place() {
    if (sheet.matches || !opener) { card.style.left = card.style.top = ""; return; }
    const rect = opener.getBoundingClientRect(), width = card.offsetWidth, height = card.offsetHeight;
    const left = Math.min(Math.max(16, rect.left), innerWidth - width - 16);
    let top = rect.bottom + 8;
    if (top + height > innerHeight - 8 && rect.top - height - 8 > 8) top = rect.top - height - 8;
    card.style.left = `${Math.round(left + scrollX)}px`;
    card.style.top = `${Math.round(top + scrollY)}px`;
  }
  function open(term) {
    if (!glossary.has(term.dataset.term)) return;
    opener?.classList.remove("is-open");
    opener = term;
    opener.classList.add("is-open");
    trail = [];
    show(term.dataset.term);
    card.hidden = false;
    place();
    $("h3", card).focus({preventScroll: true});
  }
  function close(returnFocus) {
    if (card.hidden) return;
    card.hidden = true;
    const term = opener;
    opener?.classList.remove("is-open");
    opener = null;
    if (returnFocus) term?.focus({preventScroll: true});
  }

  function turnTo(id) {
    show(id);
    place();
    $("h3", card).focus({preventScroll: true});
  }
  card.addEventListener("click", event => {
    const related = event.target.closest("[data-related]");
    if (related) { trail.push(current); turnTo(related.dataset.related); return; }
    if (event.target.closest(".definition-back") && trail.length) { turnTo(trail.pop()); return; }
    if (event.target.closest(".definition-close")) close(true);
  });
  card.addEventListener("focusout", event => {
    if (event.relatedTarget && !card.contains(event.relatedTarget) && event.relatedTarget !== opener) close(false);
  });

  const termAt = event => event.target instanceof Element ? event.target.closest(TERM) : null;
  // A double-click opens a definition without selecting the word; text elsewhere stays selectable.
  document.addEventListener("mousedown", event => { if (event.detail > 1 && termAt(event)) event.preventDefault(); });
  document.addEventListener("dblclick", event => {
    const term = termAt(event);
    if (!term) return;
    getSelection()?.removeAllRanges();
    open(term);
  });
  // On touch screens a double tap zooms, so one tap opens the definition.
  document.addEventListener("pointerup", event => {
    const term = event.pointerType === "touch" && termAt(event);
    if (term) open(term);
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !card.hidden) { event.preventDefault(); close(true); return; }
    const term = termAt(event);
    if (term && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); open(term); }
  });
  // A click with no pointer behind it (detail 0) comes from a screen reader or switch device activating the
  // button: open the definition. A real single click on a term still does nothing, so reading is undisturbed.
  // The event path, not the target, decides "outside": a related-term button is replaced as it is clicked.
  document.addEventListener("click", event => {
    const term = termAt(event);
    if (term && event.detail === 0) { open(term); return; }
    if (!card.hidden && !event.composedPath().includes(card) && !term) close(false);
  });
  addEventListener("resize", () => { if (!card.hidden) place(); });
  // Print the whole glossary even when it is folded away on screen.
  addEventListener("beforeprint", () => { const glossaryBox = $(".glossary details"); if (glossaryBox) glossaryBox.open = true; });

  // ----- Live numbers: the same read-only status the Knowledge tab uses -----
  async function loadCounts() {
    const strip = $("#live");
    if (!strip) return;
    try {
      const response = await fetch("/api/loop", {headers: {Accept: "application/json"}});
      if (!response.ok) return;
      const loop = await response.json();
      const findings = loop?.knowledge?.findings || {}, reuse = loop?.reuse || {};
      const counts = {
        answered: reuse.answered,
        reviewed: findings.supported || 0,
        added: findings.accepted || 0,
        checking: (findings.unreviewed || 0) + (findings.uncertain || 0),
        reused: reuse.citingReviewed,
      };
      for (const cell of $$("[data-count]", strip)) {
        const value = counts[cell.dataset.count];
        cell.textContent = isCount(value) ? value.toLocaleString("en-US") : "—";
      }
      strip.hidden = false;
    } catch { /* A static copy has no API: the strip stays hidden. */ }
  }

  prepareTerms(document.querySelector("main"));
  loadFigures();
  loadCounts();
})();
