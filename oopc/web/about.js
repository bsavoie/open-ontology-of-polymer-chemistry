/* The About tab: researcher.js routes #/about here, and render() copies the page from index.html's
   <template id="about-view"> into the view and animates its figures while they are on screen.
   Browsing it issues read-only GETs and never starts agent work. The figures illustrate the
   mechanisms; they are not data, and their networks are drawn from fixed seeds. */
(function () {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const isCount = value => Number.isSafeInteger(value) && value >= 0;
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const seg = (t, a, b) => t <= a ? 0 : t >= b ? 1 : (t - a) / (b - a);
  const easeOut = t => 1 - (1 - t) ** 3;

  // ----- Playing while shown -----
  let active = [];
  /** Calls step(ms) every frame, with the time since the last one, while the element is on screen and the page
      is visible; the clock does not run while it is hidden. Stops once the element leaves the document or
      render() runs again. Returns the stop function. */
  function whileShown(element, step) {
    let running = false, visible = false, last = null;
    const loop = now => {
      if (!element.isConnected) { stop(); return; }
      if (!running) return;
      step(last === null ? 0 : Math.min(250, now - last));
      last = now;
      if (running) requestAnimationFrame(loop);
    };
    const update = () => {
      const show = visible && !document.hidden && element.isConnected;
      if (show && !running) { running = true; last = null; requestAnimationFrame(loop); }
      if (!show) running = false;
    };
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; update(); }, {threshold: .3});
    function stop() { running = false; observer.disconnect(); document.removeEventListener("visibilitychange", update); }
    observer.observe(element);
    document.addEventListener("visibilitychange", update);
    active.push(stop);
    return stop;
  }
  /** Draws draw(t), t in seconds from 0 to `length`, while the element is shown: once, or again after
      `hold` seconds on the last frame. With reduced motion only the last frame is drawn. */
  function timeline(element, length, draw, hold = null) {
    if (REDUCED) { draw(length); return; }
    let t = 0;
    draw(0);
    const stop = whileShown(element, ms => {
      t += ms / 1000;
      if (hold !== null && t > length + hold) t = 0;
      draw(Math.min(t, length));
      if (hold === null && t >= length) stop();
    });
  }

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
  function network(random, {cx = CENTRE, cy = CENTRE, count = 26, inner = 46, spread = 128, spacing = 40} = {}) {
    const nodes = [{x: cx, y: cy, r: 7}];
    for (let tries = 0; nodes.length < count && tries < 5000; tries++) {
      const angle = random() * Math.PI * 2, distance = inner + Math.sqrt(random()) * spread;
      const x = cx + distance * Math.cos(angle), y = cy + distance * Math.sin(angle);
      if (nodes.every(n => Math.hypot(n.x - x, n.y - y) > spacing)) nodes.push({x, y, r: 3.6 + random() * 2.4});
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

    let findings = [], motions = [], clock = 0, fired = -1, fullSince = null, comet = onRing(0);
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
    function frame(ms) {
      clock += ms;
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
    if (REDUCED) {
      // A still picture: the state after a few questions, with the next one at Ask.
      for (let lap = 0; lap < 6; lap++) {
        for (let k = 2 + Math.floor(random() * 1.6); k > 0; k--) { const index = target(); if (index !== null) attach(index, newStatus(), true); }
        findings.filter(f => f.status === "checking").slice(0, 2).forEach(review);
      }
      place(0);
      stageLabels[0].classList.add("now");
      return;
    }
    whileShown(svg, frame);
  }

  // ----- 1 · The seed: wiki pages become a network of polymers, joined to their families -----
  const SEED_NAMES = ["PE", "PP", "PS", "PLA", "PET", "PVC", "PMMA", "PCL"];
  function seedFigure(svg, counts) {
    const random = seeded(7), {nodes, edges} = network(random, {cx: 392, cy: 165, count: 24, inner: 34, spread: 104, spacing: 34});
    const source = [150, 165];
    const pages = draw("g", {class: "wiki"}, svg);
    [16, 8, 0].forEach(offset => draw("rect", {class: "wiki-page", x: 40 + offset, y: 92 - offset, width: 104, height: 138, rx: 8}, pages));
    for (let k = 0; k < 6; k++) draw("rect", {class: "wiki-line", x: 56, y: 112 + k * 18, width: k % 3 === 2 ? 46 : 72, height: 5, rx: 2.5}, pages);
    const caption = draw("text", {class: "wiki-label", x: 100, y: 262, "text-anchor": "middle"}, pages);
    ["Wiki of Open", "Polymer Data"].forEach((words, k) => { draw("tspan", {x: 100, dy: k ? "1.25em" : 0}, caption).textContent = words; });
    // Families grow outward from the first polymer, so the order is breadth first.
    const order = [0], seen = new Set([0]);
    for (let k = 0; k < order.length; k++) for (const next of nodes[order[k]].links) if (!seen.has(next)) { seen.add(next); order.push(next); }
    order.forEach((index, k) => { nodes[index].land = .55 + k * .11 + .5; nodes[index].start = .55 + k * .11; });
    const lines = edges.map(([a, b]) => draw("line", {class: "seed-edge", x1: nodes[a].x, y1: nodes[a].y, x2: nodes[b].x, y2: nodes[b].y, opacity: 0}, svg));
    const named = order.filter(i => i).filter((_, k) => k % 3 === 1).slice(0, SEED_NAMES.length);
    nodes.forEach((node, index) => {
      node.el = draw("circle", {class: index ? "seed-node" : "seed-node root", r: node.r, opacity: 0}, svg);
      const k = named.indexOf(index);
      if (k < 0) return;
      const left = node.x > 460;  // names near the right edge sit on the node's left, inside the drawing
      node.label = draw("text", {class: "seed-name", x: node.x + (left ? -1 : 1) * (node.r + 4), y: node.y + 4, "text-anchor": left ? "end" : "start", opacity: 0}, svg);
      node.label.textContent = SEED_NAMES[k];
    });
    const targets = [...counts.querySelectorAll("[data-to]")].map(cell => [cell, Number(cell.dataset.to)]);
    timeline(svg, nodes.reduce((end, n) => Math.max(end, n.land), 0) + .6, t => {
      pages.setAttribute("opacity", seg(t, 0, .45).toFixed(3));
      for (const node of nodes) {
        const fly = easeOut(seg(t, node.start, node.land));
        node.el.setAttribute("cx", mix(source[0], node.x, fly).toFixed(2));
        node.el.setAttribute("cy", mix(source[1], node.y, fly).toFixed(2));
        node.el.setAttribute("opacity", (t >= node.start ? Math.min(1, .4 + fly) : 0).toFixed(3));
        node.label?.setAttribute("opacity", seg(t, node.land, node.land + .4).toFixed(3));
      }
      edges.forEach(([a, b], k) => lines[k].setAttribute("opacity", seg(t, Math.max(nodes[a].land, nodes[b].land), Math.max(nodes[a].land, nodes[b].land) + .35).toFixed(3)));
      const share = easeOut(seg(t, .55, 4));
      for (const [cell, to] of targets) cell.textContent = Math.round(to * share).toLocaleString("en-US");
    });
  }

  // ----- 2 · Findings: saved by an answer, then checked by a reviewer -----
  function findingsFigure(figure) {
    const card = key => $(`[data-card="${key}"]`, figure);
    const [a, b] = [card("a"), card("b")];
    const set = (element, start, reviewedAt, t) => {
      element.classList.toggle("in", t >= start);
      element.classList.toggle("scanning", t >= reviewedAt - 1 && t < reviewedAt);
      const reviewed = t >= reviewedAt, badge = $("[data-badge]", element);
      badge.className = reviewed ? "badge good" : element === b ? "badge warn" : "badge";
      badge.textContent = reviewed ? "Reviewed" : element === b ? "Needs checking" : "Added";
      element.classList.toggle("reviewed", reviewed);
    };
    // The figure reading is checked first; the added finding gets a spot check after it.
    timeline(figure, 6.4, t => { set(a, .15, 5.6, t); set(b, .6, 3.3, t); }, 3);
  }

  // ----- 4 · Reflect: one edit, from a missed search to an edit in force -----
  function reflectFigure(figure) {
    const steps = [...figure.querySelectorAll("[data-step]")];
    timeline(figure, .3 + steps.length * 1.35, t => steps.forEach((step, k) => {
      step.classList.toggle("on", t >= .3 + k * 1.35);
      step.classList.toggle("done", t >= .3 + (k + 1) * 1.35 && k < steps.length - 1);
    }), 3);
  }

  // ----- 5 · Engines: findings from either engine flow into one knowledge base -----
  function enginesFigure(svg) {
    const engines = [["ChatGPT", "through Codex", 54], ["Claude", "through Claude Code", 186]];
    const store = {x: 372, y: 88, w: 160, h: 124};
    const paths = engines.map(([name, via, y]) => {
      const box = draw("g", {class: "engine-box"}, svg);
      draw("rect", {x: 24, y, width: 196, height: 62, rx: 12}, box);
      const title = draw("text", {class: "engine-name", x: 44, y: y + 27}, box); title.textContent = name;
      const sub = draw("text", {class: "engine-via", x: 44, y: y + 46}, box); sub.textContent = via;
      return draw("path", {class: "engine-path", d: `M220 ${y + 31}C300 ${y + 31} 300 150 ${store.x} 150`}, svg);
    });
    const body = draw("g", {class: "store"}, svg);
    draw("path", {d: `M${store.x} ${store.y + 14}v${store.h - 28}a${store.w / 2} 14 0 0 0 ${store.w} 0v${-(store.h - 28)}`}, body);
    draw("ellipse", {cx: store.x + store.w / 2, cy: store.y + 14, rx: store.w / 2, ry: 14}, body);
    const label = draw("text", {class: "store-name", x: store.x + store.w / 2, y: store.y + store.h + 30, "text-anchor": "middle"}, svg);
    label.textContent = "One knowledge base";
    const where = draw("text", {class: "engine-via", x: store.x + store.w / 2, y: store.y + store.h + 48, "text-anchor": "middle"}, svg);
    where.textContent = "on this computer";
    const CYCLE = 1.6, ARRIVALS = 10;
    const slots = Array.from({length: ARRIVALS}, (_, k) => draw("circle", {class: k % 3 === 2 ? "stored reviewed" : "stored",
      cx: store.x + 30 + (k % 5) * 25, cy: store.y + store.h - 26 - Math.floor(k / 5) * 22, r: 5, opacity: 0}, svg));
    const flyer = draw("circle", {class: "flight", r: 5, opacity: 0}, svg);
    const lengths = paths.map(path => path.getTotalLength());
    timeline(svg, CYCLE * ARRIVALS, t => {
      const k = Math.min(ARRIVALS - 1, Math.floor(t / CYCLE)), u = (t - k * CYCLE) / CYCLE, along = easeOut(seg(u, 0, .75));
      const path = paths[k % 2], point = path.getPointAtLength(lengths[k % 2] * along);
      flyer.setAttribute("cx", point.x.toFixed(2)); flyer.setAttribute("cy", point.y.toFixed(2));
      flyer.setAttribute("opacity", (t < CYCLE * ARRIVALS && u < .78 ? 1 : 0).toFixed(2));
      slots.forEach((slot, j) => slot.setAttribute("opacity", (j < k || j === k && u >= .75 ? 1 : 0).toFixed(2)));
    }, 1.2);
  }

  // ----- 6 · Share: the download link, to copy or share -----
  const PITCH = "OOPC (say “oopsie”), the Open Ontology of Polymer Chemistry: a polymer knowledge base that gets better as you use it. It runs on your Claude or ChatGPT subscription.";
  function shareCard(figure) {
    const field = $("[data-share-url]", figure), url = field.value;
    field.addEventListener("focus", () => field.select());
    $("[data-share-copy]", figure).addEventListener("click", async event => {
      const button = event.currentTarget;
      try { await navigator.clipboard.writeText(url); button.textContent = "Copied"; }
      catch { field.select(); button.textContent = "Couldn’t copy; the link is selected"; }
      setTimeout(() => { button.textContent = "Copy link"; }, 1800);
    });
    // The system share sheet, where the browser has one.
    if (navigator.share) {
      $(".share-actions", figure).hidden = false;
      $("[data-share-native]", figure).addEventListener("click", () => navigator.share({title: "OOPC", text: PITCH, url}).catch(() => { /* Closed without sharing. */ }));
    }
    timeline(figure, .05, t => figure.classList.toggle("in", t > 0));
  }

  // ----- 3 · Live numbers: the same read-only status the Knowledge tab uses -----
  async function loadCounts(strip) {
    try {
      const response = await fetch("/api/loop", {headers: {Accept: "application/json"}});
      if (!response.ok) return;
      const loop = await response.json();
      const findings = loop?.knowledge?.findings || {}, reuse = loop?.reuse || {};
      const counts = {usable: (findings.supported || 0) + (findings.accepted || 0), reviewed: findings.supported || 0,
                      answered: reuse.answered, reused: reuse.citingReviewed};
      const cells = [...strip.querySelectorAll("[data-count]")].map(cell => [cell, counts[cell.dataset.count]]);
      strip.hidden = false;
      timeline(strip, 1.2, t => {
        for (const [cell, value] of cells) cell.textContent = isCount(value) ? Math.round(value * easeOut(t / 1.2)).toLocaleString("en-US") : "—";
      });
    } catch { /* No API (a static copy): the numbers stay hidden. */ }
  }

  function render(view) {
    for (const stop of active) stop();
    active = [];
    view.replaceChildren($("#about-view").content.cloneNode(true));
    loopFigure($("#loop-art", view));
    seedFigure($("#seed-art", view), $(".seed-counts", view));
    findingsFigure($("#findings-art", view));
    reflectFigure($("#reflect-art", view));
    enginesFigure($("#engines-art", view));
    shareCard($("#share-art", view));
    loadCounts($("#live", view));
  }
  window.OOPCAbout = {render};
})();
