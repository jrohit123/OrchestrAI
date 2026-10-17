// =====================================================================================================
// The canvas: flows and building blocks are drawn and edited the same way.
// Add a step: drag it from the left, press "+" on a step's way out, or drop a line on empty space.
// Connect: drag from a step's dot to another step. Click a line to put a step in between or remove it.
// Open a step (double-click) for its settings: what it can use (drag in) | its settings | what it gives.
// =====================================================================================================
const NODE_W = 210, HEAD_H = 50, OUT_H = 22;
let E = null; // the editor's state

function screenFlowEditor(root, r) {
  const f = DB.flows.find(x => x.id === r.a); if (!f) return go('flows');
  const u = uc(f.usecase);
  drawTop([h('a', { href: '#/uc/' + u.id + '/flows' }, u.icon + ' ' + u.name), '›', h('a', { href: '#/uc/' + u.id + '/flows' }, 'Flows'), '›', h('b', null, f.name)]);
  openEditor(root, { mode: 'flow', obj: f, usecase: u.id });
}
function screenBlockEditor(root, r) {
  const b = blockById(r.a); if (!b) return go('blocks');
  const u = uc(b.usecase);
  drawTop([h('a', { href: '#/blocks' }, 'Building blocks'), '›', u ? u.icon + ' ' + u.name : '🌐 Shared', '›', h('b', null, b.name)]);
  openEditor(root, { mode: 'block', obj: b, usecase: b.usecase || DB.usecases[0].id });
}

function openEditor(root, opt) {
  root.className = 'full';
  E = { ...opt, g: clone(opt.obj.graph), sel: null, selEdge: null, zoom: 1, pan: { x: 30, y: 40 }, undo: [], dirty: false };
  const pal = h('div', { class: 'cv-pal' }), cv = h('div', { class: 'cv' }), world = h('div', { class: 'cv-world' });
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  world.append(svg); cv.append(world);
  E.el = { cv, world, svg, pal };
  add(root, h('div', { class: 'cv-wrap' }, pal, cv));
  drawPalette(); drawTopBar(); wireCanvas(); draw(); fit();
}

// ---------------- the left: every step, by kind, draggable ----------------
function paletteItems() {
  const items = [];
  Object.entries(STEPS).forEach(([k, s]) => {
    if (['gets', 'gives', 'block'].includes(k)) return;
    if (s.superOnly && !isSuper()) return;
    items.push({ type: k, kind: s.kind, icon: s.icon, name: s.name, help: s.help });
  });
  DB.blocks.filter(b => (!b.usecase || b.usecase === E.usecase) && !(E.mode === 'block' && b.id === E.obj.id))
    .forEach(b => items.push({ type: 'block', kind: 'block', icon: '🧩', name: b.name, help: 'Needs ' + b.needs.join(', '), cfg: { block: b.id } }));
  return items;
}
function drawPalette() {
  const q = h('input', { type: 'search', placeholder: 'Search steps…', style: { marginBottom: '6px' } });
  const list = h('div');
  const drawList = () => {
    const t = q.value.toLowerCase(), items = paletteItems().filter(i => !t || (i.name + ' ' + i.help).toLowerCase().includes(t));
    const kinds = Object.keys(KINDS).filter(k => !(E.mode === 'block' && k === 'start'));
    fill(list, kinds.map(k => { const l = items.filter(i => i.kind === k); return l.length ? [h('h4', null, KINDS[k].label), l.map(paletteRow)] : null; }));
  };
  q.addEventListener('input', drawList);
  fill(E.el.pal, q, h('div', { class: 'tiny muted', style: { margin: '0 2px 4px' } }, 'Drag a step onto the canvas, or click it to add it after the selected step.'), list);
  drawList();
}
function paletteRow(i) {
  return h('div', { class: 'pi', draggable: 'true', title: i.help,
    ondragstart: e => { e.dataTransfer.setData('application/x-step', JSON.stringify({ type: i.type, cfg: i.cfg || {} })); e.dataTransfer.effectAllowed = 'copy'; },
    onclick: () => addAfterSelected(i.type, i.cfg) },
    h('span', { class: 'dot', style: { background: KINDS[i.kind].color } }, i.icon), h('div', null, i.name, h('small', null, i.help)));
}

// ---------------- the bar above the canvas ----------------
function drawTopBar() {
  const o = E.obj, isFlow = E.mode === 'flow';
  const users = !isFlow ? DB.flows.filter(f => f.graph.nodes.some(n => n.type === 'block' && n.cfg.block === o.id)) : [];
  const bar = h('div', { class: 'cv-top' },
    h('div', { class: 'cv-title' }, h('span', null, isFlow ? '🔀' : '🧩'), h('input', { type: 'text', value: o.name, oninput: e => { o.name = e.target.value; markDirty(); } }),
      isFlow ? h('label', { class: 'row small', style: { gap: '6px' } }, sw(o.on, v => { o.on = v; toast(v ? 'Switched on: people can use it now' : 'Switched off'); }), 'On') : pill('v' + o.version)),
    isFlow ? h('button', { class: 'btn', onclick: accessModal, title: 'Who can use this flow' }, '👥 ', accessWords(o.access)) : h('div', { class: 'cv-title small' }, users.length ? ['Used by ', h('b', null, users.length + ' flow' + (users.length > 1 ? 's' : '')), ': ', users.map(f => f.name).join(', ')] : 'Not used by any flow yet'),
    h('div', { class: 'sp' }),
    h('button', { class: 'btn', onclick: () => openSimulator(E) }, '▶ Test'),
    E.saveBtn = h('button', { class: 'btn pri', onclick: save, disabled: true }, 'Saved'));
  const tools = h('div', { class: 'cv-tools' },
    h('button', { class: 'btn', onclick: fit, title: 'Fit to screen' }, '⤢'), h('button', { class: 'btn', onclick: () => zoomBy(1.15), title: 'Zoom in' }, '+'), h('button', { class: 'btn', onclick: () => zoomBy(1 / 1.15), title: 'Zoom out' }, '−'),
    h('button', { class: 'btn', onclick: undo, title: 'Undo (Ctrl+Z)' }, '↶ Undo'), h('button', { class: 'btn', onclick: tidy, title: 'Line the steps up neatly' }, '🧹 Tidy up'));
  E.el.cv.append(bar, tools);
}
function markDirty() { E.dirty = true; if (E.saveBtn) { E.saveBtn.disabled = false; E.saveBtn.textContent = 'Save'; } }
function snapshot() { E.undo.push(JSON.stringify(E.g)); if (E.undo.length > 40) E.undo.shift(); markDirty(); }
function undo() { if (!E.undo.length) return toast('Nothing to undo'); E.g = JSON.parse(E.undo.pop()); E.sel = null; E.selEdge = null; draw(); }
async function save() {
  if (E.mode === 'block') {
    const users = DB.flows.filter(f => f.graph.nodes.some(n => n.type === 'block' && n.cfg.block === E.obj.id));
    if (users.length && !(await confirmBox('This building block is used by ' + users.length + ' flow' + (users.length > 1 ? 's' : '') + ': ' + users.map(f => f.name).join(', ') + '. They all change when you save. Save it?', 'Save for all of them'))) return;
    E.obj.version++;
  }
  E.obj.graph = clone(E.g); E.dirty = false; E.saveBtn.disabled = true; E.saveBtn.textContent = 'Saved';
  toast(E.mode === 'block' ? 'Saved as version ' + E.obj.version : 'Saved. Switch it on when it is ready.');
  E.el.cv.querySelectorAll('.cv-top,.cv-tools').forEach(x => x.remove()); drawTopBar();
}

// ---------------- geometry ----------------
function outsOf(n) { const s = STEPS[n.type]; const o = s.outs ? s.outs(n.cfg || {}) : null; return o && o.length ? o : null; }
function nodeH(n) { const o = outsOf(n); return HEAD_H + (o ? o.length * OUT_H + 8 : 0); }
function inPt(n) { return { x: n.x, y: n.y + 25 }; }
function outPt(n, i) { const o = outsOf(n); return o ? { x: n.x + NODE_W, y: n.y + HEAD_H + 4 + OUT_H * (i || 0) + OUT_H / 2 } : { x: n.x + NODE_W, y: n.y + 25 }; }
function nodeById(id) { return E.g.nodes.find(n => n.id === id); }
function curve(a, b) { const dx = Math.max(40, Math.abs(b.x - a.x) / 2); return `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`; }
function toWorld(ev) { const r = E.el.cv.getBoundingClientRect(); return { x: (ev.clientX - r.left - E.pan.x) / E.zoom, y: (ev.clientY - r.top - E.pan.y) / E.zoom }; }
function applyView() { E.el.world.style.transform = `translate(${E.pan.x}px,${E.pan.y}px) scale(${E.zoom})`; E.el.cv.style.backgroundPosition = `${E.pan.x}px ${E.pan.y}px`; E.el.cv.style.backgroundSize = `${22 * E.zoom}px ${22 * E.zoom}px`; }
function zoomBy(k, cx, cy) {
  const r = E.el.cv.getBoundingClientRect(); cx = cx == null ? r.width / 2 : cx; cy = cy == null ? r.height / 2 : cy;
  const z = Math.min(1.8, Math.max(0.35, E.zoom * k)); E.pan.x = cx - (cx - E.pan.x) * (z / E.zoom); E.pan.y = cy - (cy - E.pan.y) * (z / E.zoom); E.zoom = z; applyView();
}
function fit() {
  const ns = E.g.nodes; if (!ns.length) return;
  const r = E.el.cv.getBoundingClientRect();
  const minX = Math.min(...ns.map(n => n.x)), maxX = Math.max(...ns.map(n => n.x + NODE_W + 40)), minY = Math.min(...ns.map(n => n.y)), maxY = Math.max(...ns.map(n => n.y + nodeH(n)));
  const z = Math.min(1.1, Math.max(0.35, Math.min((r.width - 80) / (maxX - minX), (r.height - 150) / (maxY - minY))));
  E.zoom = z; E.pan.x = (r.width - (maxX - minX) * z) / 2 - minX * z; E.pan.y = 70 + (r.height - 150 - (maxY - minY) * z) / 2 - minY * z; applyView();
}

// ---------------- draw ----------------
function problemsOf(n) {
  const c = n.cfg || {}, p = [];
  if (['ask', 'say', 'tell'].includes(n.type) && !c.text) p.push('The message is empty');
  if (n.type === 'tell' && !(c.who && (c.who.everyone || (c.who.roles || []).length || (c.who.kinds || []).length))) p.push('Nobody is chosen to be told');
  if (n.type === 'chat' && !(c.phrases || []).length && !c.menu && !c.command) p.push('Nothing starts it yet');
  if (n.type === 'block' && !c.block) p.push('Pick a building block');
  if (n.type === 'if' && !c.value) p.push('What should it check?');
  return p;
}
function draw() {
  const { world, svg } = E.el;
  world.querySelectorAll('.node,.edge-add,.edge-del,.cv-hint').forEach(x => x.remove());
  svg.replaceChildren();
  // lines
  E.g.edges.forEach((ed, i) => {
    const a = nodeById(ed.from), b = nodeById(ed.to); if (!a || !b) return;
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', curve(outPt(a, ed.out), inPt(b))); p.setAttribute('class', 'edge' + (E.selEdge === i ? ' hot' : ''));
    p.addEventListener('mousedown', ev => { ev.stopPropagation(); E.selEdge = i; E.sel = null; draw(); });
    svg.append(p);
    if (E.selEdge === i) {
      const A = outPt(a, ed.out), B = inPt(b), m = { x: (A.x + B.x) / 2, y: (A.y + B.y) / 2 };
      world.append(h('div', { class: 'edge-add', title: 'Put a step in between', style: { left: m.x + 'px', top: m.y + 'px' }, onmousedown: ev => ev.stopPropagation(), onclick: ev => openPicker(ev.clientX, ev.clientY, { between: i }) }, '+'),
        h('div', { class: 'edge-del', title: 'Remove this line', style: { left: m.x + 'px', top: m.y + 'px' }, onmousedown: ev => ev.stopPropagation(), onclick: () => { snapshot(); E.g.edges.splice(i, 1); E.selEdge = null; draw(); } }, '×'));
    }
  });
  if (E.temp) { const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', curve(E.temp.a, E.temp.b)); p.setAttribute('class', 'edge-temp'); svg.append(p); }
  // steps
  E.g.nodes.forEach(n => world.append(nodeEl(n)));
  if (E.g.nodes.length <= 1) world.append(h('div', { class: 'cv-hint', style: { left: (E.g.nodes[0] ? E.g.nodes[0].x + 420 : 300) + 'px', top: (E.g.nodes[0] ? E.g.nodes[0].y + 30 : 200) + 'px', position: 'absolute' } }, '👈 Drag a step from the left,', h('br'), 'or press + on the step to add what happens next.'));
  applyView();
}
function nodeEl(n) {
  const s = STEPS[n.type], k = KINDS[s.kind], outs = outsOf(n), c = n.cfg || {};
  const blk = n.type === 'block' ? blockById(c.block) : null;
  const title = n.name || (blk ? blk.name : s.name);
  const sub = subtitle(n);
  const probs = problemsOf(n);
  const el = h('div', { class: 'node' + (s.start ? ' start' : '') + (E.sel === n.id ? ' sel' : ''), style: { left: n.x + 'px', top: n.y + 'px' }, 'data-id': n.id },
    h('div', { class: 'ntools' },
      h('button', { title: 'Open its settings', onclick: ev => { ev.stopPropagation(); openNode(n.id); } }, '⚙'),
      h('button', { title: 'Copy this step', onclick: ev => { ev.stopPropagation(); snapshot(); const m = clone(n); m.id = uid(); m.x += 30; m.y += 40; E.g.nodes.push(m); draw(); } }, '⧉'),
      h('button', { title: 'Delete this step', onclick: ev => { ev.stopPropagation(); removeNode(n.id); } }, '🗑')),
    probs.length ? h('div', { class: 'warn-b', title: probs.join('\n') }, '!') : null,
    h('div', { class: 'nh2' }, h('div', { class: 'nic', style: { background: k.color } }, blk ? '🧩' : s.icon), h('div', { style: { minWidth: 0 } }, h('div', { class: 'nt' }, title), h('div', { class: 'ns' }, sub))),
    outs ? h('div', { class: 'outs' }, outs.map((o, i) => h('div', { class: 'orow' }, o))) : null,
    s.start ? null : h('div', { class: 'port in', style: { top: '18px' } }));
  // ways out: a dot to drag from, and a "+" to add the next step
  (outs || [null]).forEach((o, i) => {
    const y = outs ? HEAD_H + 4 + OUT_H * i + OUT_H / 2 : 25;
    const used = E.g.edges.some(ed => ed.from === n.id && (ed.out || 0) === i);
    el.append(h('div', { class: 'port out', style: { top: (y - 6.5) + 'px' }, title: 'Drag to connect', onmousedown: ev => startLink(ev, n, i) }));
    if (!used && n.type !== 'gives' && n.type !== 'end') el.append(h('div', { class: 'addp', style: { top: (y - 10) + 'px' }, title: 'Add what happens next', onmousedown: ev => ev.stopPropagation(), onclick: ev => { ev.stopPropagation(); openPicker(ev.clientX, ev.clientY, { from: n.id, out: i }); } }, '+'));
  });
  el.addEventListener('mousedown', ev => startMove(ev, n));
  el.addEventListener('dblclick', () => openNode(n.id));
  return el;
}
function subtitle(n) {
  const c = n.cfg || {}, s = STEPS[n.type];
  const short = t => (t || '').replace(/\{([^}]+)\}/g, (m, k) => '‹' + k.split('.').pop() + '›');
  switch (n.type) {
    case 'chat': return [c.menu ? 'Menu: ' + ((uc(c.menu.usecase) || {}).name || '') + ' › ' + c.menu.group : '', c.command ? '/' + c.command : ''].filter(Boolean).join(' · ') || 'Not set yet';
    case 'schedule': return 'Every ' + (c.every || 'day').toLowerCase() + ' at ' + (c.time || '—');
    case 'ask': return short(c.text) || 'No question yet';
    case 'say': case 'end': return short(c.text) || (n.type === 'end' ? 'Ends here' : 'No message yet');
    case 'tell': return 'To ' + whoWords(c.who, c.record) + (c.text ? ': ' + short(c.text) : '');
    case 'create': case 'update': case 'find': case 'list': return recLabel(c.record || 'ticket') + (c.status ? ' → ' + c.status : '') + (c.filter ? ' · ' + c.filter.toLowerCase() : '');
    case 'assign': return c.how || 'Who handles what';
    case 'if': return c.value ? short(c.value) + ' ' + (c.op || 'is') + ' ' + (c.than || '') : 'Not set yet';
    case 'approve': return 'By ' + whoWords(c.who);
    case 'ai': return (c.task || 'Pick a task') + (c.into ? ' → ' + c.into : '');
    case 'block': { const b = blockById(c.block); return b ? 'Needs ' + b.needs.join(', ') : 'Pick a block'; }
    case 'gets': return 'Needs: ' + ((c.needs || []).join(', ') || 'nothing');
    case 'gives': return 'Gives: ' + ((c.gives || []).join(', ') || 'nothing');
    case 'button': return '“' + (c.label || '…') + '” on a ' + recLabel(c.record || 'ticket').toLowerCase();
    case 'change': return recLabel(c.record || 'ticket') + ' ' + (c.when || '…');
    case 'after': return c.flow ? 'After “' + c.flow + '”' : 'Pick a flow';
    case 'form': case 'sendform': return c.form || 'Pick a form';
    case 'choices': return (c.options || []).join(' / ') || 'No choices yet';
    case 'wait': return c.for || 'Pick a time';
    default: return s.help;
  }
}
function whoWords(w, rec) {
  if (!w) return 'nobody yet';
  if (w.everyone) return 'everyone';
  const R = DB.records[rec || (uc(E && E.usecase) || {}).record || 'ticket'] || DB.records.ticket;
  const k = (w.kinds || []).map(x => (R.people.find(p => p.key === x) || {}).label || x);
  const parts = (w.roles || []).concat(k.length ? ['on the ' + R.label.toLowerCase() + ': ' + k.join(', ').toLowerCase()] : []);
  return parts.length ? parts.join(', ') : 'nobody yet';
}

// ---------------- mouse: pan, zoom, move, connect, drop ----------------
function wireCanvas() {
  const cv = E.el.cv;
  cv.addEventListener('mousedown', ev => {
    if (ev.target !== cv && ev.target !== E.el.world && ev.target !== E.el.svg) return;
    E.sel = null; E.selEdge = null; draw();
    const s = { x: ev.clientX, y: ev.clientY, px: E.pan.x, py: E.pan.y }; cv.classList.add('panning');
    const mv = e => { E.pan.x = s.px + e.clientX - s.x; E.pan.y = s.py + e.clientY - s.y; applyView(); };
    const up = () => { cv.classList.remove('panning'); removeEventListener('mousemove', mv); removeEventListener('mouseup', up); };
    addEventListener('mousemove', mv); addEventListener('mouseup', up);
  });
  cv.addEventListener('wheel', ev => { ev.preventDefault(); const r = cv.getBoundingClientRect(); zoomBy(ev.deltaY < 0 ? 1.08 : 1 / 1.08, ev.clientX - r.left, ev.clientY - r.top); }, { passive: false });
  cv.addEventListener('dragover', ev => { if (ev.dataTransfer.types.includes('application/x-step')) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'copy'; } });
  cv.addEventListener('drop', ev => {
    const raw = ev.dataTransfer.getData('application/x-step'); if (!raw) return; ev.preventDefault();
    const { type, cfg } = JSON.parse(raw), p = toWorld(ev);
    const n = makeNode(type, cfg, p.x - NODE_W / 2, p.y - 25);
    // dropped on a step's right side with nothing after it: connect it
    const near = E.g.nodes.filter(m => m.id !== n.id && !E.g.edges.some(e => e.from === m.id) && Math.abs(m.x + NODE_W - n.x) < 160 && Math.abs(m.y - n.y) < 80)[0];
    if (near && !STEPS[type].start) E.g.edges.push({ from: near.id, to: n.id });
    E.sel = n.id; draw();
  });
  const key = ev => {
    if (!document.body.contains(cv)) { removeEventListener('keydown', key); return; }
    if ($('#layer').children.length || ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'z') { ev.preventDefault(); undo(); }
    if (ev.key === 'Delete' || ev.key === 'Backspace') { if (E.sel) removeNode(E.sel); else if (E.selEdge != null) { snapshot(); E.g.edges.splice(E.selEdge, 1); E.selEdge = null; draw(); } }
  };
  addEventListener('keydown', key);
  addEventListener('resize', () => document.body.contains(cv) && applyView());
}
function startMove(ev, n) {
  if (ev.button !== 0 || ev.target.closest('.port,.addp,.ntools')) return;
  ev.stopPropagation();
  const s = { x: ev.clientX, y: ev.clientY, nx: n.x, ny: n.y }; let moved = false;
  if (E.sel !== n.id) { E.sel = n.id; E.selEdge = null; E.el.world.querySelectorAll('.node').forEach(x => x.classList.toggle('sel', x.dataset.id === n.id)); }
  const mv = e => {
    const dx = (e.clientX - s.x) / E.zoom, dy = (e.clientY - s.y) / E.zoom;
    if (!moved && Math.abs(dx) + Math.abs(dy) < 3) return;
    if (!moved) { snapshot(); moved = true; }
    n.x = Math.round((s.nx + dx) / 10) * 10; n.y = Math.round((s.ny + dy) / 10) * 10; draw();
  };
  const up = () => { removeEventListener('mousemove', mv); removeEventListener('mouseup', up); };
  addEventListener('mousemove', mv); addEventListener('mouseup', up);
}
function startLink(ev, n, out) {
  ev.stopPropagation(); ev.preventDefault();
  const a = outPt(n, out);
  E.temp = { a, b: a };
  const mv = e => { E.temp.b = toWorld(e); draw(); };
  const up = e => {
    removeEventListener('mousemove', mv); removeEventListener('mouseup', up);
    E.temp = null;
    const t = document.elementFromPoint(e.clientX, e.clientY), target = t && t.closest('.node');
    if (target && target.dataset.id !== n.id) {
      const to = nodeById(target.dataset.id);
      if (STEPS[to.type].start) { toast('A start can only begin a flow, nothing leads into it.'); draw(); return; }
      if (!E.g.edges.some(x => x.from === n.id && (x.out || 0) === out && x.to === to.id)) { snapshot(); E.g.edges.push({ from: n.id, out, to: to.id }); }
      draw();
    } else if (!target) { draw(); openPicker(e.clientX, e.clientY, { from: n.id, out, at: toWorld(e) }); }
    else draw();
  };
  addEventListener('mousemove', mv); addEventListener('mouseup', up);
}
function makeNode(type, cfg, x, y) {
  snapshot();
  const base = defaultsFor(type);
  const n = { id: uid(), type, x: Math.round(x / 10) * 10, y: Math.round(y / 10) * 10, cfg: Object.assign(base, clone(cfg || {})) };
  E.g.nodes.push(n); return n;
}
function defaultsFor(type) {
  const rec = (uc(E.usecase) || {}).record || 'ticket';
  return ({ ask: { answer: 'Words' }, find: { record: rec, by: 'its number (from an answer)' }, create: { record: rec, map: [] }, update: { record: rec }, list: { record: rec, filter: 'Open ones' }, assign: { record: rec, how: 'Who handles what' },
    tell: { record: rec, who: { roles: [], kinds: [] } }, approve: { who: { roles: [], kinds: [] } }, if: { op: 'is' }, schedule: { every: 'Day', time: '09:00' }, change: { record: rec, when: 'it is created' }, button: { record: rec, where: 'Both' }, choices: { options: ['Yes', 'No'] }, chat: { menu: { usecase: E.usecase, group: (uc(E.usecase) || { menu: [''] }).menu[0] }, phrases: [] } })[type] || {};
}
function addAfterSelected(type, cfg) {
  const from = E.sel ? nodeById(E.sel) : E.g.nodes.filter(n => !E.g.edges.some(e => e.from === n.id)).slice(-1)[0];
  if (STEPS[type].start || !from) { const n = makeNode(type, cfg, 60, (E.g.nodes.length ? Math.max(...E.g.nodes.map(m => m.y)) + 140 : 160)); E.sel = n.id; draw(); return; }
  placeAfter(from.id, 0, type, cfg);
}
function placeAfter(fromId, out, type, cfg, at) {
  const a = nodeById(fromId);
  const taken = E.g.edges.filter(e => e.from === fromId).length;
  const pos = at ? { x: at.x - 20, y: at.y - 25 } : { x: a.x + NODE_W + 60, y: a.y + (outsOf(a) ? (out || 0) * 110 - 40 : taken * 120) };
  const n = makeNode(type, cfg, pos.x, pos.y);
  E.g.edges.push({ from: fromId, out: out || 0, to: n.id });
  E.sel = n.id; draw();
  if (needsSetup(n)) setTimeout(() => openNode(n.id), 120);
}
function needsSetup(n) { return ['ask', 'say', 'tell', 'if', 'choices', 'block', 'approve'].includes(n.type); }
function removeNode(id) {
  const n = nodeById(id); if (!n) return;
  snapshot();
  // keep the flow joined up: what came in goes on to what came after
  const ins = E.g.edges.filter(e => e.to === id), outs = E.g.edges.filter(e => e.from === id);
  E.g.edges = E.g.edges.filter(e => e.to !== id && e.from !== id);
  if (ins.length === 1 && outs.length === 1) E.g.edges.push({ from: ins[0].from, out: ins[0].out, to: outs[0].to });
  E.g.nodes = E.g.nodes.filter(x => x.id !== id); E.sel = null; draw();
  toast('Step deleted. Ctrl+Z brings it back.');
}
function tidy() {
  snapshot();
  const depth = {}, starts = E.g.nodes.filter(n => !E.g.edges.some(e => e.to === n.id));
  const q = starts.map(n => [n.id, 0]);
  while (q.length) { const [id, d] = q.shift(); if (depth[id] != null && depth[id] >= d) continue; depth[id] = d; E.g.edges.filter(e => e.from === id).forEach(e => { if (d < 40) q.push([e.to, d + 1]); }); }
  const cols = {}; E.g.nodes.forEach(n => (cols[depth[n.id] || 0] = cols[depth[n.id] || 0] || []).push(n));
  Object.entries(cols).forEach(([d, l]) => { const tot = l.reduce((s, n) => s + nodeH(n) + 50, -50); let y = 220 - tot / 2; l.forEach(n => { n.x = 60 + d * (NODE_W + 60); n.y = Math.round(y / 10) * 10; y += nodeH(n) + 50; }); });
  draw(); fit();
}

// ---------------- "What happens next?" ----------------
function openPicker(x, y, ctx) {
  document.querySelectorAll('.picker').forEach(p => p.remove());
  const startOnly = ctx.start;
  let cat = null;
  const q = h('input', { type: 'search', placeholder: 'Search, e.g. ask, tell, approve, booking…' });
  const list = h('div', { class: 'list' });
  const pk = h('div', { class: 'picker' }, h('div', { class: 'ph2' }, h('b', null, startOnly ? 'What starts this flow?' : 'What happens next?'), h('div', { style: { marginTop: '8px' } }, q)), list);
  const items = paletteItems().filter(i => startOnly ? i.kind === 'start' : i.kind !== 'start');
  function choose(i) {
    pk.remove();
    if (ctx.between != null) { const ed = E.g.edges[ctx.between], a = nodeById(ed.from), b = nodeById(ed.to); snapshot(); E.g.edges.splice(ctx.between, 1); E.selEdge = null; const n = makeNode(i.type, i.cfg, (a.x + b.x) / 2, (a.y + b.y) / 2 + 60); E.g.edges.push({ from: a.id, out: ed.out, to: n.id }, { from: n.id, to: b.id }); E.sel = n.id; draw(); if (needsSetup(n)) setTimeout(() => openNode(n.id), 120); return; }
    if (ctx.from) return placeAfter(ctx.from, ctx.out, i.type, i.cfg, ctx.at);
    const n = makeNode(i.type, i.cfg, 60, 160); E.sel = n.id; draw();
  }
  function drawList() {
    const t = q.value.toLowerCase();
    if (t) { fill(list, items.filter(i => (i.name + ' ' + i.help).toLowerCase().includes(t)).map(i => pickRow(i, () => choose(i)))); return; }
    if (cat) { fill(list, h('div', { class: 'pk', onclick: () => { cat = null; drawList(); } }, '← ', KINDS[cat].label), items.filter(i => i.kind === cat).map(i => pickRow(i, () => choose(i)))); return; }
    const kinds = Object.keys(KINDS).filter(k => items.some(i => i.kind === k));
    const blurb = { talk: 'Ask, reply, offer choices, send a form', data: 'Find, save, change or list tickets, bookings…', decide: 'Check something, ask for approval, wait', people: 'Tell people, give it to someone', ai: 'Sort, summarise, pull out details', block: 'Ready-made steps of this use case', adv: 'Web address, database query', start: 'Chat, schedule, button, change, form, another flow' };
    fill(list, kinds.map(k => h('div', { class: 'pk', onclick: () => { cat = k; drawList(); } }, h('span', { class: 'dot', style: { background: KINDS[k].color } }, (items.find(i => i.kind === k) || {}).icon), h('div', null, h('b', null, KINDS[k].label), h('small', null, blurb[k])), h('span', { class: 'chev' }, '›'))),
      !startOnly && E.mode === 'flow' ? h('div', { class: 'pk', onclick: () => { pk.remove(); openPicker(x, y, { start: true }); } }, h('span', { class: 'dot', style: { background: KINDS.start.color } }, '⚡'), h('div', null, h('b', null, 'Add another way to start'), h('small', null, 'A flow can start from chat and from a schedule, for example.'))) : null);
  }
  q.addEventListener('input', drawList);
  q.addEventListener('keydown', e => { if (e.key === 'Enter') { const f = list.querySelector('.pk[data-pick]'); f && f.click(); } if (e.key === 'Escape') pk.remove(); });
  drawList();
  document.body.append(pk);
  const w = 340, hh = Math.min(innerHeight * .7, 520);
  pk.style.left = Math.min(x + 12, innerWidth - w - 10) + 'px'; pk.style.top = Math.max(10, Math.min(y - 40, innerHeight - hh - 10)) + 'px';
  setTimeout(() => { q.focus(); const off = e => { if (!pk.contains(e.target)) { pk.remove(); removeEventListener('mousedown', off); } }; addEventListener('mousedown', off); });
}
function pickRow(i, fn) { return h('div', { class: 'pk', 'data-pick': '1', onclick: fn }, h('span', { class: 'dot', style: { background: KINDS[i.kind].color } }, i.icon), h('div', null, h('b', null, i.name), h('small', null, i.help))); }

// =====================================================================================================
// A step's window: what it can use (drag it in) | its settings | what it gives
// =====================================================================================================
function upstreamVars(id) {
  const seen = new Set(), order = [], q = [id];
  while (q.length) { const cur = q.shift(); E.g.edges.filter(e => e.to === cur).forEach(e => { if (!seen.has(e.from)) { seen.add(e.from); order.push(e.from); q.push(e.from); } }); }
  const groups = order.reverse().map(nid => { const n = nodeById(nid), s = STEPS[n.type]; const v = s.gives(n.cfg || {}); return v.length ? { title: (n.name || (n.type === 'block' ? (blockById(n.cfg.block) || {}).name : s.name)), icon: s.icon, vars: v } : null; }).filter(Boolean);
  groups.push({ title: 'Organisation', icon: '🏢', vars: [['org.name', 'Organisation name', DB.org.name], ['today.date', "Today's date", '15 Oct 2026'], ['today.time', 'Time now', '4:30 pm']] });
  return groups;
}
function allSamples(id) { const m = {}; upstreamVars(id).forEach(g => g.vars.forEach(v => m[v[0]] = v[2])); return m; }
function withSamples(text, samples) {
  return esc(text || '').replace(/\{([^}]+)\}/g, (m, k) => samples[k] != null ? `<span class="tok">${esc(samples[k])}</span>` : `<span class="tok" style="background:var(--bad-soft);color:var(--bad)" title="Nothing earlier in the flow makes this">{${esc(k)}}</span>`);
}

let LAST_FIELD = null; // the field a click on a value goes into
function openNode(id) {
  const n = nodeById(id); if (!n) return;
  const before = JSON.stringify(n), gBefore = JSON.stringify(E.g);
  const s = STEPS[n.type];
  const left = h('div', { class: 'ndv-in' }), mid = h('div', { class: 'ndv-mid' }), right = h('div', { class: 'ndv-out' });
  const groups = upstreamVars(id), samples = allSamples(id);
  LAST_FIELD = null;
  const redrawRight = () => {
    const gives = s.gives(n.cfg || {});
    fill(right, h('h5', null, 'What it gives to later steps'),
      gives.length ? gives.map(g => h('div', { class: 'outrow' }, h('span', null, g[1], h('div', null, h('code', { class: 'tiny', style: { color: 'var(--brand)' } }, '{' + g[0] + '}'))), h('span', { class: 'muted small' }, g[2]))) : h('div', { class: 'small muted' }, 'Nothing new. Later steps can still use everything that came before.'),
      outsOf(n) ? [h('h5', { style: { marginTop: '16px' } }, 'Ways out'), outsOf(n).map(o => pill(o, 'brand'))] : null,
      h('h5', { style: { marginTop: '16px' } }, 'Try this step'),
      h('button', { class: 'btn', onclick: () => testStep(n, samples, right) }, '▶ Test with sample values'),
      h('div', { class: 'tst' }));
  };
  // left: values, grouped by the step that makes them; drag one into any box, or click it to put it in the last box you used
  const vq = h('input', { type: 'search', placeholder: 'Find a value…', style: { marginBottom: '10px' } });
  const vlist = h('div');
  const drawVars = () => { const t = vq.value.toLowerCase(); fill(vlist, groups.map(g => { const vs = g.vars.filter(v => !t || (v[1] + v[0]).toLowerCase().includes(t)); return vs.length ? h('div', { class: 'vgrp' }, h('b', null, g.icon + ' ' + g.title), vs.map(v => varChip(v))) : null; })); };
  vq.addEventListener('input', drawVars);
  fill(left, h('h5', null, 'What it can use'), h('div', { class: 'tiny muted', style: { marginBottom: '8px' } }, 'Drag a value into a box, or click it.'), vq, vlist);
  drawVars();
  // middle: the settings
  const nameIn = h('input', { type: 'text', value: n.name || '', placeholder: (n.type === 'block' ? (blockById(n.cfg.block) || {}).name : s.name), oninput: e => { n.name = e.target.value; } });
  fill(mid, h('div', { class: 'row', style: { marginBottom: '12px' } }, h('div', { class: 'nic', style: { width: '34px', height: '34px', borderRadius: '9px', display: 'grid', placeItems: 'center', color: '#fff', background: KINDS[s.kind].color } }, s.icon), h('div', { style: { flex: 1 } }, nameIn, h('div', { class: 'tiny muted', style: { marginTop: '3px' } }, s.help))),
    settingsFor(n, samples, () => { redrawRight(); }),
    s.start && E.mode === 'flow' ? accessSection(E.obj) : null,
    n.type === 'chat' ? h('div', { class: 'sec' }, h('div', { class: 'sh' }, '📷 Photos'), h('div', { class: 'sb' }, h('label', { class: 'row small' }, sw(!!E.obj.photos, v => E.obj.photos = v), 'Keep photos people send while this flow is running, on the ' + recLabel((uc(E.usecase) || {}).record).toLowerCase() + ' it makes'))) : null,
    h('div', { class: 'sec' }, h('div', { class: 'sh' }, '📝 Note for other builders'), h('div', { class: 'sb' }, h('textarea', { placeholder: 'Why this step is here (optional)', oninput: e => n.note = e.target.value }, n.note || ''))));
  redrawRight();
  const m = modal({ title: h('div', { class: 'row' }, h('b', null, 'Step settings'), pill(KINDS[s.kind].label)), size: 'wide', body: h('div', { class: 'ndv' }, left, mid, right),
    actions: [{ label: 'Delete step', danger: true, run: () => { removeNode(id); } }, { label: 'Done', primary: true }],
    onClose: () => { if (JSON.stringify(n) !== before) { E.undo.push(gBefore); markDirty(); } draw(); } });
  m.el.querySelector('.modal-b').style.padding = '0';
}
function varChip(v) {
  return h('div', { class: 'var', draggable: 'true', title: 'Drag into a box, or click to add it to the last box you used',
    ondragstart: e => { e.dataTransfer.setData('text/plain', '{' + v[0] + '}'); e.dataTransfer.effectAllowed = 'copy'; document.querySelectorAll('.ndv-mid textarea,.ndv-mid input.vin').forEach(t => t.classList.add('drop-hot')); },
    ondragend: () => document.querySelectorAll('.drop-hot').forEach(t => t.classList.remove('drop-hot')),
    onclick: () => { if (!LAST_FIELD) return toast('Click into a box first, then click the value'); insertAt(LAST_FIELD, '{' + v[0] + '}'); } },
    h('span', null, v[1], h('div', null, h('code', null, '{' + v[0] + '}'))), h('span', { class: 's' }, v[2]));
}
function insertAt(el, text) {
  const a = el.selectionStart ?? el.value.length, b = el.selectionEnd ?? el.value.length;
  el.value = el.value.slice(0, a) + text + el.value.slice(b); el.focus(); el.selectionStart = el.selectionEnd = a + text.length;
  el.dispatchEvent(new Event('input'));
}
function testStep(n, samples, right) {
  const box = right.querySelector('.tst'), c = n.cfg || {};
  const out = c.text ? h('div', { class: 'prev', html: withSamples(c.text, samples) }) : null;
  fill(box, h('div', { class: 'notice ok', style: { marginTop: '8px' } }, '✓', h('div', null, 'Ran with sample values. Nothing was sent or saved.')), out);
}

// ---- the settings form, drawn from the step's field list ----
function settingsFor(n, samples, changed) {
  const s = STEPS[n.type], c = n.cfg = n.cfg || {};
  const box = h('div', { class: 'sec' }, h('div', { class: 'sh' }, '⚙ Settings'));
  const body = h('div', { class: 'sb' });
  box.append(body);
  const redraw = () => { fill(body, s.fields.filter(f => !f.show || f.show(c)).map(f => field(f, n, samples, () => { changed(); }, redraw))); };
  redraw();
  return box;
}
function field(f, n, samples, changed, redraw) {
  const c = n.cfg, set = v => { c[f.key] = v; changed(); };
  const lab = (...kids) => h('label', { class: 'f' }, f.label, kids, f.hint ? h('span', { class: 'hint' }, f.hint) : null);
  const rec = c.record || (uc(E.usecase) || {}).record || 'ticket', R = DB.records[rec] || DB.records.ticket;
  switch (f.type) {
    case 'text': return lab(h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, f.prefix ? h('span', { class: 'muted' }, f.prefix) : null, h('input', { type: 'text', value: c[f.key] || '', oninput: e => set(e.target.value) })));
    case 'time': return lab(h('input', { type: 'time', value: c[f.key] || '09:00', oninput: e => set(e.target.value), style: { width: '140px' } }));
    case 'code': return lab(h('textarea', { class: 'code', style: { minHeight: '140px' }, oninput: e => set(e.target.value) }, c[f.key] || 'SELECT …'));
    case 'switch': return h('label', { class: 'row small' }, sw(c[f.key], v => set(v)), f.label);
    case 'select': { const opts = f.options(c); return lab(h('select', { onchange: e => { set(e.target.value); redraw(); } }, h('option', { value: '' }, 'Choose…'), opts.map(o => h('option', { value: o, selected: c[f.key] === o }, o)))); }
    case 'seg': return lab(h('div', { class: 'seg', style: { alignSelf: 'flex-start' } }, f.options.map(o => h('button', { type: 'button', class: (c[f.key] || f.options[0]) === o ? 'on' : '', onclick: () => { set(o); redraw(); } }, o))));
    case 'days': { const d = c.days = c.days || ['Mon']; return lab(h('div', { class: 'chipbox' }, ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(x => h('span', { class: 'chip' + (d.includes(x) ? ' on' : ''), onclick: () => { d.includes(x) ? d.splice(d.indexOf(x), 1) : d.push(x); changed(); redraw(); } }, x)))); }
    case 'chips': { const l = c[f.key] = c[f.key] || []; return lab(chipEditor(l, () => { changed(); redraw(); E && draw(); })); }
    case 'needlist': { const l = c[f.key] = c[f.key] || []; return lab(chipEditor(l, () => { changed(); })); }
    case 'record': return lab(h('select', { onchange: e => { set(e.target.value); redraw(); } }, Object.entries(DB.records).map(([k, r]) => h('option', { value: k, selected: rec === k }, r.label))));
    case 'status': return lab(h('select', { onchange: e => set(e.target.value) }, h('option', { value: '' }, 'Keep as it is'), R.statuses.map(st => h('option', { value: st, selected: c[f.key] === st }, st))));
    case 'peoplekind': return lab(h('select', { onchange: e => set(e.target.value) }, R.people.map(p => h('option', { value: p.key, selected: c[f.key] === p.key }, p.label))));
    case 'value': return lab(valueBox(c[f.key] || '', v => set(v), samples, false));
    case 'rich': return lab(valueBox(c[f.key] || '', v => { set(v); }, samples, true));
    case 'menuplace': {
      const m = c.menu = c.menu || { usecase: E.usecase, group: '' }; const U = uc(m.usecase) || DB.usecases[0];
      return lab(h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, h('select', { onchange: e => { m.usecase = e.target.value; m.group = (uc(e.target.value).menu || [])[0]; changed(); redraw(); } }, DB.usecases.map(u => h('option', { value: u.id, selected: u.id === m.usecase }, u.icon + ' ' + u.name))), '›',
        h('select', { onchange: e => { m.group = e.target.value; changed(); } }, h('option', { value: '' }, 'Not in the menu'), U.menu.map(g => h('option', { value: g, selected: g === m.group }, g)))),
        h('span', { class: 'hint' }, 'The groups come from the use case. Add one in ', h('a', { href: '#/uc/' + U.id + '/setup' }, U.name + ' › How it is set up'), '.'));
    }
    case 'who': return lab(whoPicker(c[f.key] = c[f.key] || { roles: [], kinds: [] }, rec, changed));
    case 'map': {
      const rows = c.map = c.map || [];
      const wrap = h('div', { class: 'col' });
      const drawRows = () => fill(wrap, rows.map((r2, i) => h('div', { class: 'row', style: { flexWrap: 'nowrap', alignItems: 'flex-start' } },
        h('select', { style: { width: '160px', flex: 'none' }, onchange: e => { r2[0] = e.target.value; changed(); } }, R.fields.filter(x => !x.system).map(x => h('option', { value: x.key, selected: r2[0] === x.key }, x.label))), '←',
        h('div', { style: { flex: 1 } }, valueBox(r2[1] || '', v => { r2[1] = v; changed(); }, samples, false)),
        h('button', { class: 'btn sm ghost', onclick: () => { rows.splice(i, 1); drawRows(); changed(); } }, '×'))),
        h('button', { class: 'btn sm', style: { alignSelf: 'flex-start' }, onclick: () => { rows.push([R.fields.filter(x => !x.system)[0].key, '']); drawRows(); } }, '+ Fill in another field'),
        h('div', { class: 'tiny muted' }, 'Fields come from ' + R.label + ' in Data & schema. Required: ' + R.fields.filter(x => x.required).map(x => x.label).join(', ') + '.'));
      drawRows(); return lab(wrap);
    }
    case 'blockpick': return lab(h('select', { onchange: e => { set(e.target.value); c.needs = {}; redraw(); E && draw(); } }, h('option', { value: '' }, 'Choose a block…'), DB.blocks.filter(b => !b.usecase || b.usecase === E.usecase).map(b => h('option', { value: b.id, selected: c.block === b.id }, b.name))),
      c.block ? h('span', { class: 'hint' }, blockById(c.block).desc, ' ', h('a', { href: '#/block/' + c.block }, 'Open the block →')) : null);
    case 'needs': { const b = blockById(c.block); if (!b) return null; const nd = c.needs = c.needs || {}; return lab(h('div', { class: 'col' }, b.needs.map(k => h('div', null, h('div', { class: 'tiny muted' }, k), valueBox(nd[k] || '', v => { nd[k] = v; changed(); }, samples, false))))); }
    default: return null;
  }
}
function chipEditor(list, changed) {
  const box = h('div', { class: 'chipbox' });
  const draw2 = () => fill(box, list.map((v, i) => h('span', { class: 'chip' }, v, h('span', { class: 'x', onclick: () => { list.splice(i, 1); draw2(); changed(); } }, '×'))),
    h('input', { type: 'text', placeholder: 'Type and press Enter', style: { width: '190px', padding: '3px 9px', borderRadius: '99px' }, onkeydown: e => { if (e.key === 'Enter' && e.target.value.trim()) { e.preventDefault(); list.push(e.target.value.trim()); draw2(); changed(); box.querySelector('input').focus(); } } }));
  draw2(); return box;
}
// a text box that takes values: drag a value in (it lands where you drop it), or "{ } Insert a value"
function valueBox(value, onChange, samples, rich) {
  const ta = rich ? h('textarea', { rows: 4 }) : h('input', { type: 'text', class: 'vin', placeholder: 'Type, or drag a value here' });
  ta.value = value;
  const prev = rich ? h('div', { class: 'prev' }) : h('div', { class: 'tiny muted', style: { marginTop: '3px' } });
  const upd = () => { onChange(ta.value); prev.innerHTML = rich ? (ta.value ? withSamples(ta.value, samples) : '<span style="opacity:.5">How it will look in WhatsApp</span>') : (ta.value && /\{/.test(ta.value) ? 'e.g. ' + withSamples(ta.value, samples) : ''); };
  ta.addEventListener('input', upd);
  ta.addEventListener('focus', () => LAST_FIELD = ta);
  ta.addEventListener('drop', () => setTimeout(() => { document.querySelectorAll('.drop-hot').forEach(t => t.classList.remove('drop-hot')); upd(); LAST_FIELD = ta; }, 0));
  const ins = h('button', { type: 'button', class: 'btn sm', onclick: ev => insertMenu(ev, ta, samples) }, '{ } Insert a value');
  const emo = rich ? h('button', { type: 'button', class: 'btn sm', onclick: ev => emojiMenu(ev, ta) }, '😀') : null;
  upd();
  return h('div', { class: 'col', style: { gap: '4px' } }, ta, h('div', { class: 'row' }, ins, emo, rich ? h('span', { class: 'tiny muted' }, 'Bold: *text* · new line: Enter') : null), prev);
}
function insertMenu(ev, ta, samples) {
  document.querySelectorAll('.picker').forEach(p => p.remove());
  const groups = upstreamVars(E.sel || (E.g.nodes[0] || {}).id);
  const q = h('input', { type: 'search', placeholder: 'Find a value…' }), list = h('div', { class: 'list' });
  const pk = h('div', { class: 'picker', style: { width: '320px' } }, h('div', { class: 'ph2' }, q), list);
  const drawL = () => { const t = q.value.toLowerCase(); fill(list, groups.map(g => { const vs = g.vars.filter(v => !t || (v[1] + v[0]).toLowerCase().includes(t)); return vs.length ? [h('div', { class: 'tiny muted', style: { padding: '6px 8px 2px' } }, g.icon + ' ' + g.title), vs.map(v => h('div', { class: 'pk', 'data-pick': 1, onclick: () => { pk.remove(); insertAt(ta, '{' + v[0] + '}'); } }, h('div', null, h('b', null, v[1]), h('small', null, 'e.g. ' + v[2]))))] : null; })); };
  q.addEventListener('input', drawL); drawL();
  document.body.append(pk);
  const r = ev.target.getBoundingClientRect(); pk.style.left = Math.min(r.left, innerWidth - 330) + 'px'; pk.style.top = Math.min(r.bottom + 4, innerHeight - 380) + 'px';
  setTimeout(() => { q.focus(); const off = e => { if (!pk.contains(e.target)) { pk.remove(); removeEventListener('mousedown', off); } }; addEventListener('mousedown', off); });
}
function emojiMenu(ev, ta) {
  document.querySelectorAll('.picker').forEach(p => p.remove());
  const pk = h('div', { class: 'picker', style: { width: '250px', padding: '8px', flexDirection: 'row', flexWrap: 'wrap' } }, '✅ ⚠️ 🎫 📅 🚪 🔧 💧 ⚡ 🧹 🙏 👍 🎉 ⏰ 📍 📷 🔔 ❌ 👋'.split(' ').map(e => h('button', { class: 'btn ghost', style: { padding: '4px 6px' }, onclick: () => { pk.remove(); insertAt(ta, e); } }, e)));
  document.body.append(pk); const r = ev.target.getBoundingClientRect(); pk.style.left = r.left + 'px'; pk.style.top = (r.bottom + 4) + 'px';
  setTimeout(() => { const off = e => { if (!pk.contains(e.target)) { pk.remove(); removeEventListener('mousedown', off); } }; addEventListener('mousedown', off); });
}

// ---- who: roles (with "everyone" and select-all per group) and people on the record ----
function whoPicker(w, rec, changed) {
  w.roles = w.roles || []; w.kinds = w.kinds || [];
  const R = DB.records[rec] || DB.records.ticket;
  const box = h('div', { class: 'col' });
  const draw2 = () => {
    fill(box,
      h('label', { class: 'row small' }, sw(w.everyone, v => { w.everyone = v; changed(); draw2(); }), h('b', null, 'Everyone'), h('span', { class: 'muted' }, '(every person in the organisation)')),
      w.everyone ? null : [
        h('div', { class: 'small', style: { fontWeight: 600 } }, 'People on the ' + R.label.toLowerCase()),
        h('div', { class: 'chipbox' }, R.people.map(p => h('span', { class: 'chip' + (w.kinds.includes(p.key) ? ' on' : ''), onclick: () => { toggle(w.kinds, p.key); changed(); draw2(); } }, p.label))),
        h('div', { class: 'small', style: { fontWeight: 600, marginTop: '4px' } }, 'Everyone in a role'),
        DB.roleGroups.map(g => { const all = g.roles.every(r => w.roles.includes(r));
          return h('div', { class: 'rolegrp' }, h('div', { class: 'rh' }, h('input', { type: 'checkbox', checked: all, onchange: () => { g.roles.forEach(r => { const i = w.roles.indexOf(r); if (all && i >= 0) w.roles.splice(i, 1); if (!all && i < 0) w.roles.push(r); }); changed(); draw2(); } }), g.name, h('span', { class: 'sp' }), h('a', { onclick: () => { g.roles.forEach(r => { if (!w.roles.includes(r)) w.roles.push(r); }); changed(); draw2(); } }, 'all'), h('a', { onclick: () => { w.roles = w.roles.filter(r => !g.roles.includes(r)); changed(); draw2(); } }, 'none')),
            h('div', { class: 'chipbox' }, g.roles.map(r => h('span', { class: 'chip' + (w.roles.includes(r) ? ' on' : ''), onclick: () => { toggle(w.roles, r); changed(); draw2(); } }, r)))); })],
      h('div', { class: 'sentence' }, '→ ', whoWords(w, rec)));
  };
  draw2(); return box;
}
function toggle(l, v) { const i = l.indexOf(v); i >= 0 ? l.splice(i, 1) : l.push(v); }

// ---- who can use this flow ----
function accessSection(f) {
  const a = f.access = f.access || { everyone: false, roles: [], kinds: [] };
  const u = uc(f.usecase), R = DB.records[u.record];
  const box = h('div', { class: 'sb' });
  const draw2 = () => fill(box,
    h('label', { class: 'row small' }, sw(a.everyone, v => { a.everyone = v; draw2(); refreshBar(); }), h('b', null, 'Everyone can use it')),
    a.everyone ? null : [
      DB.roleGroups.map(g => { const all = g.roles.every(r => a.roles.includes(r));
        return h('div', { class: 'rolegrp' }, h('div', { class: 'rh' }, h('input', { type: 'checkbox', checked: all, onchange: () => { if (all) a.roles = a.roles.filter(r => !g.roles.includes(r)); else g.roles.forEach(r => a.roles.includes(r) || a.roles.push(r)); draw2(); refreshBar(); } }), 'All ' + g.name.toLowerCase(), h('span', { class: 'sp' }), h('span', { class: 'tiny muted' }, g.roles.filter(r => a.roles.includes(r)).length + ' of ' + g.roles.length)),
          h('div', { class: 'chipbox' }, g.roles.map(r => h('span', { class: 'chip' + (a.roles.includes(r) ? ' on' : ''), onclick: () => { toggle(a.roles, r); draw2(); refreshBar(); } }, r)))); }),
      h('div', { class: 'rolegrp' }, h('div', { class: 'rh' }, 'People on a ' + R.label.toLowerCase(), h('span', { class: 'sp' }), h('span', { class: 'tiny muted' }, 'only on their own ' + R.plural.toLowerCase())),
        h('div', { class: 'chipbox' }, R.people.map(p => h('span', { class: 'chip' + (a.kinds.includes(p.key) ? ' on' : ''), onclick: () => { toggle(a.kinds, p.key); draw2(); refreshBar(); } }, p.label))),
        h('div', { class: 'tiny muted', style: { marginTop: '6px' } }, 'These kinds come from ', h('a', { href: '#/uc/' + u.id + '/setup' }, u.name + ' › How it is set up'), '.'))],
    h('div', { class: 'sentence' }, '→ ', accessWords(a)));
  draw2();
  return h('div', { class: 'sec' }, h('div', { class: 'sh' }, '👥 Who can use this flow'), box);
}
function refreshBar() { if (!E) return; markDirty(); E.el.cv.querySelectorAll('.cv-top,.cv-tools').forEach(x => x.remove()); drawTopBar(); }
function accessModal() { modal({ title: 'Who can use “' + E.obj.name + '”', size: 'mid', body: accessSection(E.obj), actions: [{ label: 'Done', primary: true }] }); }
