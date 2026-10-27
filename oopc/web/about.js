/* About page: theme, the animated figure of the two loops, and live counts.
   Browsing it issues read-only GETs and never starts agent work. The figure illustrates
   the mechanism; it is not data, and its network is drawn from a fixed seed. */
(function () {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const isCount = value => Number.isSafeInteger(value) && value >= 0;

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

  // ----- The two loops -----
  // A question (the yellow comet) goes round the ring once per lap. At Save its findings fly into the
  // network of polymers and attach to the one they describe, lighting it (expansion); at Review some are
  // checked; at Reuse the lit polymers feed the next question (accumulation).
  const SVG = "http://www.w3.org/2000/svg";
  const CENTRE = 320, RING = 236, LAP = 9000, STAGES = ["Ask", "Answer", "Save", "Review", "Reuse"];
  const angleOf = phase => (phase * 360 - 90) * Math.PI / 180;
  const onRing = (phase, radius = RING) => [CENTRE + radius * Math.cos(angleOf(phase)), CENTRE + radius * Math.sin(angleOf(phase))];
  const ease = t => t < .5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
  const mix = (a, b, t) => a + (b - a) * t;
  function draw(name, attributes, parent) {
    const element = document.createElementNS(SVG, name);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
    parent?.append(element);
    return element;
  }
  /** A small seeded generator, so the network and its story are the same on every visit. */
  function seeded(seed) {
    return () => {
      seed = seed + 0x6d2b79f5 | 0;
      let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  /** Polymers scattered in a disc, joined by family links (a spanning tree) and a few cross-links. */
  function network(random) {
    const nodes = [{x: CENTRE, y: CENTRE, r: 7}];
    for (let tries = 0; nodes.length < 26 && tries < 5000; tries++) {
      const angle = random() * Math.PI * 2, distance = 46 + Math.sqrt(random()) * 128;
      const x = CENTRE + distance * Math.cos(angle), y = CENTRE + distance * Math.sin(angle);
      if (nodes.every(n => Math.hypot(n.x - x, n.y - y) > 40)) nodes.push({x, y, r: 3.6 + random() * 2.4});
    }
    const gap = (a, b) => Math.hypot(nodes[a].x - nodes[b].x, nodes[a].y - nodes[b].y);
    const edges = [], joined = new Set([0]);
    while (joined.size < nodes.length) {
      let best = null;
      for (const a of joined) for (let b = 0; b < nodes.length; b++) {
        if (!joined.has(b) && (!best || gap(a, b) < best.d)) best = {a, b, d: gap(a, b)};
      }
      edges.push([best.a, best.b]);
      joined.add(best.b);
    }
    for (let a = 0; a < nodes.length; a++) for (let b = a + 1; b < nodes.length; b++) {
      if (gap(a, b) < 62 && !edges.some(([p, q]) => p === a && q === b || p === b && q === a) && random() < .3) edges.push([a, b]);
    }
    for (const node of nodes) Object.assign(node, {links: [], findings: [], incoming: 0, turn: random() * Math.PI * 2, lit: false});
    for (const [a, b] of edges) { nodes[a].links.push(b); nodes[b].links.push(a); }
    return {nodes, edges};
  }

  function loopFigure(svg) {
    const random = seeded(11), {nodes, edges} = network(random);
    const layer = name => draw("g", {class: name}, svg);
    const ringLayer = layer("ring-layer"), edgeLayer = layer("edges"), lineLayer = layer("lines"),
          nodeLayer = layer("nodes"), findingLayer = layer("findings"), motionLayer = layer("motion");
    draw("circle", {class: "ring", cx: CENTRE, cy: CENTRE, r: RING}, ringLayer);
    const progress = draw("path", {class: "ring-glow", d: ""}, ringLayer);
    const stageDots = [], stageLabels = [];
    STAGES.forEach((name, index) => {
      const phase = index / STAGES.length, [x, y] = onRing(phase), [lx, ly] = onRing(phase, RING + 26), cos = Math.cos(angleOf(phase));
      stageDots.push(draw("circle", {class: "stage-dot", cx: x, cy: y, r: 4.5}, ringLayer));
      const label = draw("text", {class: "stage-label", x: lx, y: ly, "text-anchor": cos > .3 ? "start" : cos < -.3 ? "end" : "middle", "dominant-baseline": "middle"}, ringLayer);
      label.textContent = name;
      stageLabels.push(label);
    });
    const edgeLines = edges.map(([a, b]) => draw("line", {class: "edge", x1: nodes[a].x, y1: nodes[a].y, x2: nodes[b].x, y2: nodes[b].y}, edgeLayer));
    nodes.forEach((node, index) => { node.el = draw("circle", {class: index ? "node" : "node root", cx: node.x, cy: node.y, r: node.r}, nodeLayer); });
    const trail = Array.from({length: 14}, (_, i) => draw("circle", {class: "comet", r: (5.4 - i * .3).toFixed(2), opacity: ((1 - i / 14) * .5).toFixed(2)}, motionLayer));
    const glow = draw("circle", {class: "comet-glow", r: 15}, motionLayer), head = draw("circle", {class: "comet", r: 6}, motionLayer);

    let findings = [], motions = [], clock = 0, last = null, fired = -1, fullSince = null, comet = onRing(0);
    const animate = (duration, step, delay = 0) => motions.push({start: clock + delay, duration, step});
    const pick = items => items[Math.floor(random() * items.length)];
    const fade = (element, t) => element.setAttribute("opacity", Math.sin(Math.PI * t).toFixed(3));

    function light(index, quiet) {
      const node = nodes[index];
      if (node.lit) return;
      node.lit = true;
      node.el.classList.add("lit");
      edges.forEach(([a, b], k) => edgeLines[k].classList.toggle("lit", nodes[a].lit && nodes[b].lit));
      if (quiet) return;
      const halo = draw("circle", {class: "halo", cx: node.x, cy: node.y, r: node.r}, motionLayer);
      animate(1400, t => { halo.setAttribute("r", (node.r + 24 * ease(t)).toFixed(2)); halo.setAttribute("opacity", (1 - t).toFixed(3)); if (t === 1) halo.remove(); });
    }
    /** Where a polymer's next finding sits: on a small golden-angle spiral around it. */
    function slot(node, k) {
      const angle = node.turn + k * 2.4, distance = node.r + 6 + k % 3 * 3.5;
      return [node.x + distance * Math.cos(angle), node.y + distance * Math.sin(angle)];
    }
    function attach(index, status, quiet) {
      const node = nodes[index], [x, y] = slot(node, node.findings.length);
      const finding = {status, el: draw("circle", {class: `finding ${status}`, cx: x.toFixed(2), cy: y.toFixed(2), r: 2.6}, findingLayer)};
      node.findings.push(finding);
      findings.push(finding);
      light(index, quiet);
    }
    function review(finding) {
      finding.status = "reviewed";
      finding.el.setAttribute("class", "finding reviewed");
    }
    /** Mostly the frontier next to what is known (expansion), otherwise a polymer already lit (accumulation). */
    function target() {
      const all = nodes.map((_, i) => i);
      const frontier = all.filter(i => !nodes[i].lit && nodes[i].links.some(j => nodes[j].lit));
      const roomy = all.filter(i => nodes[i].lit && nodes[i].findings.length + nodes[i].incoming < 9);
      if (frontier.length && (random() < .75 || !roomy.length)) return pick(frontier);
      return roomy.length ? pick(roomy) : null;
    }
    const newStatus = () => random() < .3 ? "checking" : "added";

    const events = {
      Ask() {
        const ring = draw("circle", {class: "halo", cx: comet[0], cy: comet[1], r: 6}, motionLayer);
        animate(1100, t => { ring.setAttribute("r", (6 + 22 * ease(t)).toFixed(2)); ring.setAttribute("opacity", (1 - t).toFixed(3)); if (t === 1) ring.remove(); });
        if (fullSince !== null && fired / STAGES.length - fullSince >= 2) restart();
      },
      Answer() {
        // Open sources flow in from outside the ring.
        for (let k = 0; k < 3; k++) {
          const [sx, sy] = onRing(.2 + (k - 1) * .035 + .03, RING + 58 + random() * 16);
          const dot = draw("circle", {class: "flight", r: 2.4, opacity: 0}, motionLayer);
          animate(900, t => {
            dot.setAttribute("cx", mix(sx, comet[0], ease(t)).toFixed(2));
            dot.setAttribute("cy", mix(sy, comet[1], ease(t)).toFixed(2));
            fade(dot, t);
            if (t === 1) dot.remove();
          }, k * 140);
        }
      },
      Save() {
        const count = 2 + Math.floor(random() * 1.6);
        for (let k = 0; k < count; k++) {
          const index = target();
          if (index === null) continue;
          const node = nodes[index], status = newStatus(), [tx, ty] = slot(node, node.findings.length + node.incoming++);
          const [fx, fy] = comet, cx = mix((fx + tx) / 2, CENTRE, .35), cy = mix((fy + ty) / 2, CENTRE, .35);
          const dot = draw("circle", {class: "flight", r: 3, cx: fx, cy: fy}, motionLayer);
          animate(1500, t => {
            const e = ease(t), u = 1 - e;
            dot.setAttribute("cx", (u * u * fx + 2 * u * e * cx + e * e * tx).toFixed(2));
            dot.setAttribute("cy", (u * u * fy + 2 * u * e * cy + e * e * ty).toFixed(2));
            if (t === 1) { dot.remove(); node.incoming--; attach(index, status); }
          }, k * 170);
        }
        if (fullSince === null && nodes.every(n => n.lit || n.incoming)) fullSince = fired / STAGES.length;
      },
      Review() {
        // Everything that needs checking, and now and then a spot check of an added finding.
        const due = findings.filter(f => f.status === "checking").slice(0, 2);
        const added = findings.filter(f => f.status === "added");
        if (due.length < 2 && added.length && random() < .5) due.push(pick(added));
        for (const finding of due) {
          const line = draw("line", {class: "check", opacity: 0}, lineLayer);
          const [x, y] = [finding.el.getAttribute("cx"), finding.el.getAttribute("cy")];
          animate(1300, t => {
            line.setAttribute("x1", comet[0].toFixed(2)); line.setAttribute("y1", comet[1].toFixed(2));
            line.setAttribute("x2", x); line.setAttribute("y2", y);
            fade(line, t);
            if (t > .5 && finding.status !== "reviewed") review(finding);
            if (t === 1) line.remove();
          });
        }
      },
      Reuse() {
        // The next question reads what is known first.
        const known = nodes.filter(n => n.lit && n.findings.length).sort((a, b) => b.findings.length - a.findings.length + random() - .5).slice(0, 4);
        for (const node of known) {
          const line = draw("line", {class: "reuse", x1: node.x, y1: node.y, opacity: 0}, lineLayer);
          animate(LAP / STAGES.length + 500, t => {
            line.setAttribute("x2", comet[0].toFixed(2)); line.setAttribute("y2", comet[1].toFixed(2));
            line.setAttribute("opacity", (.5 * Math.min(1, t * 5, (1 - t) * 5)).toFixed(3));
            if (t === 1) line.remove();
          });
        }
      },
    };

    /** Once the whole network is lit, let it settle and begin again from one polymer. */
    function restart() {
      fullSince = null;
      svg.classList.add("fading");
      for (const node of nodes) { node.lit = false; node.el.classList.remove("lit"); }
      for (const line of edgeLines) line.classList.remove("lit");
      const old = findings;
      findings = [];
      for (const node of nodes) node.findings = [];
      animate(1500, t => { if (t === 1) { old.forEach(f => f.el.remove()); svg.classList.remove("fading"); } });
      seed(true);
    }
    function seed(quiet) {
      attach(0, "reviewed", quiet);
      attach(0, "added", quiet);
    }

    function fire(step) {
      const index = step % STAGES.length, dot = stageDots[index];
      dot.classList.add("hit");
      animate(700, t => { if (t === 1) dot.classList.remove("hit"); });
      stageLabels.forEach((label, i) => label.classList.toggle("now", i === index));
      events[STAGES[index]]();
    }
    function place(phase) {
      comet = onRing(phase);
      for (const [element, [x, y]] of [[head, comet], [glow, comet]]) { element.setAttribute("cx", x.toFixed(2)); element.setAttribute("cy", y.toFixed(2)); }
      trail.forEach((element, i) => { const [x, y] = onRing(phase - (i + 1) * .0045); element.setAttribute("cx", x.toFixed(2)); element.setAttribute("cy", y.toFixed(2)); });
      const [x0, y0] = onRing(0);
      progress.setAttribute("d", phase > .004 ? `M${x0.toFixed(2)} ${y0.toFixed(2)}A${RING} ${RING} 0 ${phase > .5 ? 1 : 0} 1 ${comet[0].toFixed(2)} ${comet[1].toFixed(2)}` : "");
    }
    function frame(now) {
      clock += last === null ? 0 : Math.min(50, now - last);
      last = now;
      const lap = Math.floor(clock / LAP), phase = clock % LAP / LAP;
      place(phase);
      const due = lap * STAGES.length + Math.floor(phase * STAGES.length);
      while (fired < due) fire(++fired);
      const running = motions;
      motions = [];
      for (const motion of running) {
        if (clock < motion.start) { motions.push(motion); continue; }
        const t = Math.min(1, (clock - motion.start) / motion.duration);
        motion.step(t);
        if (t < 1) motions.push(motion);
      }
    }

    seed(true);
    attach(nodes[0].links[0], "reviewed", true);
    place(0);
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      // A still picture: the state after a few questions, with the next one at Ask.
      for (let lap = 0; lap < 6; lap++) {
        for (let k = 2 + Math.floor(random() * 1.6); k > 0; k--) { const index = target(); if (index !== null) attach(index, newStatus(), true); }
        findings.filter(f => f.status === "checking").slice(0, 2).forEach(review);
      }
      place(0);
      stageLabels[0].classList.add("now");
      return;
    }
    let running = false, visible = true;
    const loop = now => { if (!running) return; frame(now); requestAnimationFrame(loop); };
    const update = () => {
      const play = visible && !document.hidden;
      if (play && !running) { running = true; last = null; requestAnimationFrame(loop); }
      if (!play) running = false;
    };
    new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; update(); }).observe(svg);
    document.addEventListener("visibilitychange", update);
    update();
  }

  // ----- Live numbers: the same read-only status the Knowledge tab uses -----
  async function loadCounts() {
    const strip = $("#live");
    if (!strip) return;
    try {
      const response = await fetch("/api/loop", {headers: {Accept: "application/json"}});
      if (!response.ok) return;
      const loop = await response.json();
      const findings = loop?.knowledge?.findings || {}, reuse = loop?.reuse || {};
      const counts = {usable: (findings.supported || 0) + (findings.accepted || 0), reviewed: findings.supported || 0,
                      answered: reuse.answered, reused: reuse.citingReviewed};
      for (const cell of strip.querySelectorAll("[data-count]")) {
        const value = counts[cell.dataset.count];
        cell.textContent = isCount(value) ? value.toLocaleString("en-US") : "—";
      }
      strip.hidden = false;
    } catch { /* A static copy has no API: the numbers stay hidden. */ }
  }

  const art = $("#loop-art");
  if (art) loopFigure(art);
  loadCounts();
})();
