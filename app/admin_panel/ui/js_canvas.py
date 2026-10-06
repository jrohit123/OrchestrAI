JS = r"""
// ───────────────────────── the flow canvas ─────────────────────────
// Every step is a box you can drag anywhere. The wires and the numbers say what runs when, so where a
// box sits never changes the flow. What is shown comes from the workflow being edited (EW) and the
// step catalogue (ST); nothing about what a step means is written here.
const CV_GAP = 84, CV_TOP = 48, CV_CX = 380;
let CV = null;                                          // the view of the flow that is open (zoom, selection, what is expanded)
const CV_KIND = { 'Look up and check': 'look', 'Save changes': 'save', 'Tell people': 'tell', 'Approvals': 'approve', 'Other': 'other' };
const CV_ICON = { resolve_entity: 'search', conflict_check: 'stop', require_permission: 'shield', derive_field: 'bolt', compute: 'calc', 'db.insert_row': 'plus', 'db.update_row': 'edit', 'db.upsert_row': 'refresh', 'db.delete_row': 'trash', 'notify.user': 'mail', 'notify.whatsapp': 'chat', 'pdf.generate': 'file', otp_gate: 'key', approval_gate: 'usercheck', ai_price_interpret: 'spark', run_workflow: 'layers', 'case.categorize': 'tag', 'case.route': 'route', 'case.authorize': 'shield', 'case.add_parties': 'users', 'case.attach_photos': 'camera', 'notify.parties': 'send' };
// steps that stop the whole workflow with a message the person sees, and where that message is kept
const CV_STOPS = {
  conflict_check: ['error_message', 'It already exists, so it stops.'],
  require_permission: ['denied_message', 'The person is not allowed, so it stops.'],
  'case.authorize': ['denied_message', 'The person is not on the case, so it stops.'],
};
const CV_WAITS = { otp_gate: 'Waits for a one-time code', approval_gate: 'Waits for an approver' };
const CV_ST = { ran: '✓', would: '✎', skipped: '↷', failed: '✕', nr: '' };
const cvKey = s => s.op === 'run_workflow' ? 'block' : (CV_KIND[(catalogSpec(s.op) || {}).group] || 'other');
const cvIcon = op => CV_ICON[op] || 'bolt';
const cvStopText = s => { const k = CV_STOPS[s.op]; return k ? ((s.params || {})[k[0]] || k[1]) : null; };
const nodeW = () => parseInt(getComputedStyle(document.documentElement).getPropertyValue('--nw'), 10) || 392;
const idAt = i => String(EW.ids[i]);
const idxOf = id => EW.ids.findIndex(x => String(x) === id);
const isRead = () => EW.d.workflow_type === 'read';
const chain = () => isRead() ? ['trigger', 'report'] : ['trigger', ...EW.ids.map(String)];
const wireIds = () => [...chain(), 'end'];
const primary = () => CV.sel.size === 1 ? [...CV.sel][0] : null;
function newCanvas() {
  return { for: EW, zoom: 1, auto: true, hm: {}, wm: {}, sel: new Set(), panel: 'insp', itab: 'set', ttab: 'start', open: new Set(), peek: {}, loading: new Set(),
    palOpen: new Set(['act', 'act:Look up and check']), tech: false, run: null, justAdded: null, G: null, frame: false, plusPts: [], inspKey: '' };
}

// ----- where things sit -----
function posOf(id) {
  if (id === 'end') {
    const ids = chain(), last = ids[ids.length - 1], p = EW.pos[last];
    if (!p) return null;
    return { x: p.x + (CV.wm[last] || nodeW()) / 2 - (CV.wm.end || 190) / 2, y: p.y + (CV.hm[last] || 100) + CV_GAP * 0.75 };
  }
  return EW.pos[id] || null;
}
const outPt = id => { const p = posOf(id); return { x: p.x + (CV.wm[id] || nodeW()) / 2, y: p.y + (CV.hm[id] || 100) }; };
const inPt = id => { const p = posOf(id); return { x: p.x + (CV.wm[id] || nodeW()) / 2, y: p.y }; };
const toStage = (cx, cy) => { const r = CV.sizer.getBoundingClientRect(); return { x: (cx - r.left) / CV.zoom, y: (cy - r.top) / CV.zoom }; };

// ----- the boxes -----
const cvSec = (title, body) => h('div', { class: 'nd-tsec' }, h('div', { class: 'nd-tl' }, title), body);
function cvTriggerNode() {
  const w = EW.work, d = EW.d, block = w.kind === 'block', action = w.kind === 'case_action';
  const phrases = w.training_phrases || [];
  const who = d.granted_roles || [], party = ((w.settings && w.settings.who_can_use) || []).map(r => PARTY_PLAIN[r] || r);
  const asks = Object.entries(w.entity_schema || {}).filter(([, f]) => f && typeof f === 'object' && !f.computed);
  const title = block ? 'Run by other workflows' : action ? 'A button on a case' : 'Someone says something like';
  const body = [];
  if (block) body.push(h('div', { class: 'nd-tsec muted small' }, d.used_in.length ? 'Used by: ' + d.used_in.map(u => u.name).join(', ') + '. Change it and they all change.' : 'Nothing runs it yet.'));
  else {
    if (phrases.length) body.push(h('div', { class: 'nd-tsec' }, h('div', { class: 'chips' }, phrases.slice(0, 5).map(t => h('span', { class: 'chip' }, '“' + t + '”')), phrases.length > 5 ? h('span', { class: 'chip sunk' }, '+' + (phrases.length - 5) + ' more') : null)));
    if (w.slash_command) body.push(cvSec('Or types', h('div', null, h('span', { class: 'chip mono' }, '/' + w.slash_command))));
    body.push(cvSec('Who can start it', who.length || party.length ? h('div', { class: 'chips' }, who.map(r => badge(r, 'brand')), party.map(r => h('span', { class: 'chip' }, r))) : h('span', { class: 'muted small' }, 'Nobody yet')));
    body.push(cvSec('Asks for', asks.length ? h('div', { class: 'chips' }, asks.map(([k, f]) => h('span', { class: 'chip' }, (f.label || pretty(k)) + (f.required || f.required_if ? ' *' : '')))) : h('span', { class: 'muted small' }, 'Nothing')));
    const gates = (w.gates || []).map(gateText);
    if (gates.length) body.push(cvSec('Safeguards', h('div', { class: 'chips' }, gates.map(t => h('span', { class: 'badge pink' }, icon('shield', 'xs'), t)))));
  }
  return h('div', { class: 'nd trig k-trigger' + (CV.sel.has('trigger') ? ' sel' : ''), 'data-id': 'trigger', style: { visibility: 'hidden' }, tabindex: 0, role: 'button', 'aria-label': 'What starts this flow' },
    h('span', { class: 'nd-ord trg' }, icon('bolt', 'xs')), h('span', { class: 'nd-port out' }),
    h('div', { class: 'nd-h' }, h('span', { class: 'nd-gi' }, icon('bolt')), h('div', { class: 'grow' }, h('div', { class: 'nd-kind' }, 'When…'), h('div', { class: 'nd-t' }, title)), h('div', { class: 'nd-tags' }, h('span', { class: 'tag' }, 'Starts it'))),
    ...body, h('div', { style: { height: '4px' } }));
}
function cvStepNode(s, i) {
  const id = idAt(i), spec = catalogSpec(s.op), key = cvKey(s), blk = s.op === 'run_workflow';
  const flow = blk ? ST.byKey[(s.params || {}).workflow] : null, n = flow ? flow.step_count : 0;
  const open = !!(flow && CV.open.has(flow.id)), wait = CV_WAITS[s.op];
  const st = CV.run && CV.run.states[id];
  const problems = problemsFor(i + 1).filter(p => p[0] === 'bad').length;
  const stops = [cvStopText(s), ...((flow && CV.peek[flow.id]) || []).map(cvStopText)].filter(Boolean);
  const tag = blk ? h('span', { class: 'tag blk' }, 'Block') : isAiStep(s) ? h('span', { class: 'tag ai' }, '✦ AI') : h('span', { class: 'tag tcode' }, 'Code');
  const sub = blk ? ((flow && flow.description) || 'Runs the steps of another workflow') : (spec ? spec.label : s.op);
  return h('div', { class: 'nd k-' + key + (blk ? ' blk' : '') + (CV.sel.has(id) ? ' sel' : ''), 'data-id': id, 'data-st': st || null, style: { visibility: 'hidden' }, tabindex: 0, role: 'button', 'aria-label': describeStep(s) },
    h('span', { class: 'nd-ord' }, i + 1), h('span', { class: 'nd-port in' }), h('span', { class: 'nd-port out' }), h('span', { class: 'nd-stb' }, st ? CV_ST[st] || '' : ''),
    problems ? h('span', { class: 'nd-bad', title: 'This step has a problem to fix' }, '!') : null,
    h('div', { class: 'nd-h' },
      h('span', { class: 'nd-gi' }, icon(cvIcon(s.op))),
      h('div', { class: 'grow' }, h('div', { class: 'nd-kind' }, blk ? 'Building block' : (spec ? spec.group : 'Step')), h('div', { class: 'nd-t' }, describeStep(s)), CV.tech ? null : h('div', { class: 'nd-s' }, sub)),
      h('div', { class: 'nd-tags' }, tag)),
    CV.tech ? h('pre', { class: 'nd-tech' }, JSON.stringify({ op: s.op, params: s.params || {}, ...(s.when ? { when: s.when } : {}) }, null, 1).replace(/\n\s*/g, ' ')) : null,
    s.when ? h('div', { class: 'nd-cond' }, icon('branch', 'sm'), 'only if ' + condText(s.when)) : null,
    wait ? h('div', { class: 'nd-wait' }, icon('pause', 'sm'), wait) : null,
    flow ? h('div', { class: 'nd-foot' },
      n ? h('button', { class: 'nd-exp', type: 'button', onclick: e => { e.stopPropagation(); cvToggle(flow); } }, icon(open ? 'chevd' : 'chevr', 'xs'), 'Inside · ' + plural(n, 'step')) : h('span', null, 'No steps yet'),
      h('span', null, '·'), h('a', { href: '#/workflows?w=' + flow.id, onclick: e => e.stopPropagation(), 'data-tip': 'Open the building block to change it' }, 'Open this block')) : null,
    open ? h('div', { class: 'nd-inside' }, CV.peek[flow.id]
      ? CV.peek[flow.id].map(x => h('div', { class: 'nd-irow k-' + cvKey(x) }, h('i'), h('span', null, describeStep(x)), cvStopText(x) ? h('em', null, 'can stop') : null, x.when ? h('em', { class: 'when' }, 'only if') : null))
      : h('div', { class: 'muted small' }, 'Loading…')) : null,
    stops.length ? h('div', { class: 'nd-exit' + (st === 'failed' ? ' lit' : '') }, h('div', { class: 'nd-xp' }, h('b', null, icon('stop', 'xs'), 'Stops'), stops.slice(0, 3).map(t => h('div', null, t)))) : null);
}
function cvReportNode() {
  return h('div', { class: 'nd k-look' + (CV.sel.has('report') ? ' sel' : ''), 'data-id': 'report', style: { visibility: 'hidden' }, tabindex: 0, role: 'button' },
    h('span', { class: 'nd-ord' }, '1'), h('span', { class: 'nd-port in' }), h('span', { class: 'nd-port out' }),
    h('div', { class: 'nd-h' }, h('span', { class: 'nd-gi' }, icon('table')), h('div', { class: 'grow' }, h('div', { class: 'nd-kind' }, 'A saved report'), h('div', { class: 'nd-t' }, 'Looks things up with a saved query'), h('div', { class: 'nd-s' }, EW.work.response_format === 'list' ? 'Every row shown exactly as stored' : 'The assistant words the answer')),
      h('div', { class: 'nd-tags' }, EW.work.response_format === 'list' ? h('span', { class: 'tag tcode' }, 'Code') : h('span', { class: 'tag ai' }, '✦ AI'))));
}
function cvEndNode() {
  return h('div', { class: 'nd end', 'data-id': 'end', style: { visibility: 'hidden' } }, h('span', { class: 'nd-port in' }), icon('check', 'sm'),
    EW.work.kind === 'block' ? 'Done: carries on with the workflow that ran it' : 'Done: tells the person');
}
// opening a block shows the steps inside it (fetched once)
async function cvToggle(flow) {
  if (CV.open.has(flow.id)) CV.open.delete(flow.id); else CV.open.add(flow.id);
  renderNodes();
  if (CV.open.has(flow.id) && !CV.peek[flow.id]) await cvPeek(flow);
}
async function cvPeek(flow) {
  if (CV.peek[flow.id] || CV.loading.has(flow.id)) return;
  CV.loading.add(flow.id);
  const mine = CV;
  try { mine.peek[flow.id] = (await api.get('/workflows/' + flow.id)).steps || []; }
  catch (e) { mine.peek[flow.id] = []; }
  mine.loading.delete(flow.id);
  if (mine === CV) renderNodes();
}
// the steps inside blocks can stop the whole workflow, so they are fetched up front to draw the red "Stops" label
function prefetchBlocks() {
  EW.work.steps.forEach(s => { const f = s.op === 'run_workflow' ? ST.byKey[(s.params || {}).workflow] : null; if (f && f.step_count) cvPeek(f); });
}

function renderNodes() {
  if (!CV || !CV.nodesEl) return;
  const prev = { ...CV.hm }, els = [cvTriggerNode()];
  if (isRead()) els.push(cvReportNode()); else EW.work.steps.forEach((s, i) => els.push(cvStepNode(s, i)));
  els.push(cvEndNode());
  fill(CV.nodesEl, els);
  layoutAfterRender(prev);
}
function layoutAfterRender(prev) {
  const NW = nodeW(), ids = chain(), clean = snapJSON() === EW.last;
  [...CV.nodesEl.children].forEach(el => { CV.hm[el.dataset.id] = el.offsetHeight; CV.wm[el.dataset.id] = el.offsetWidth; });
  ids.forEach((id, k) => {                                   // a new box goes under the one before it
    if (EW.pos[id]) return;
    if (k === 0) EW.pos[id] = { x: CV_CX - NW / 2, y: CV_TOP };
    else { const p = EW.pos[ids[k - 1]]; EW.pos[id] = { x: p.x, y: p.y + (CV.hm[ids[k - 1]] || 100) + CV_GAP }; }
  });
  if (CV.justAdded) {                                        // a box added in the middle pushes the ones below it down
    const k = ids.indexOf(CV.justAdded);
    if (k > 0 && k < ids.length - 1) {
      const n = EW.pos[ids[k]], m = EW.pos[ids[k + 1]], need = n.y + CV.hm[ids[k]] + CV_GAP;
      if (Math.abs(m.x - n.x) < NW && m.y < need) { const d = need - m.y; for (let j = k + 1; j < ids.length; j++) EW.pos[ids[j]].y += d; }
    }
    CV.justAdded = null;
  }
  ids.forEach((id, k) => {                                   // a box that grew or shrank (opened block, technical view) moves the ones below it
    const old = prev[id], now = CV.hm[id];
    if (old == null || old === now) return;
    const d = now - old, p = EW.pos[id];
    for (let j = k + 1; j < ids.length; j++) { const q = EW.pos[ids[j]]; if (q.y >= p.y + old - 4 && Math.abs(q.x - p.x) < NW) q.y += d; }
  });
  if (clean) EW.last = snapJSON();                           // where boxes were first put is not a change
  positionNodes(); drawWires(); applyZoom();
}
function positionNodes() {
  [...CV.nodesEl.children].forEach(el => { const p = posOf(el.dataset.id); if (!p) return; el.style.left = p.x + 'px'; el.style.top = p.y + 'px'; el.style.visibility = 'visible'; });
}
function drawWires() {
  const ids = wireIds(), run = CV.run, okSt = ['ran', 'would', 'skipped'];
  const stateOf = id => run && run.states[id];
  const completed = id => id === 'trigger' || okSt.includes(stateOf(id));
  const began = id => id === 'end' ? !run.stopped : ['ran', 'would', 'skipped', 'failed'].includes(stateOf(id));
  const paths = [], labels = [];
  CV.plusPts = [];
  for (let i = 0; i < ids.length - 1; i++) {
    const a = ids[i], b = ids[i + 1];
    if (!posOf(a) || !posOf(b)) continue;
    const A = outPt(a), B = inPt(b), dy = Math.max(40, Math.min(160, Math.abs(B.y - A.y) / 2));
    const lit = run && completed(a) && began(b);
    paths.push(svgEl('path', { class: 'wire' + (lit ? ' done' : ''), d: 'M' + A.x + ' ' + A.y + ' C' + A.x + ' ' + (A.y + dy) + ', ' + B.x + ' ' + (B.y - dy) + ', ' + B.x + ' ' + B.y, 'marker-end': 'url(#' + (lit ? 'ah-ok' : 'ah') + ')' }));
    if (!run && !isRead() && !oneStepOnly()) {
      const at = a === 'trigger' ? 0 : (b === 'end' ? EW.ids.length : idxOf(b)), mx = (A.x + B.x) / 2, my = (A.y + B.y) / 2;
      CV.plusPts.push({ at, x: mx, y: my });
      labels.push(h('button', { class: 'plus', type: 'button', 'data-popkeep': '1', 'aria-label': 'Add a step here', style: { left: (mx - 11) + 'px', top: (my - 11) + 'px' }, onclick: e => { e.stopPropagation(); cvOpenAdd(at, e.currentTarget); } }, icon('plus', 'xs')));
    }
  }
  const bulge = nodeW() / 2 + 110;                           // "only if": a dashed way around the box
  EW.work.steps.forEach((s, i) => {
    if (!s.when) return;
    const k = ids.indexOf(idAt(i)), a = ids[k - 1], b = ids[k + 1];
    if (!a || !b || !posOf(a) || !posOf(b)) return;
    const A = outPt(a), B = inPt(b);
    paths.push(svgEl('path', { class: 'wire skipw', d: 'M' + A.x + ' ' + A.y + ' C' + (A.x - bulge) + ' ' + (A.y + 50) + ', ' + (B.x - bulge) + ' ' + (B.y - 50) + ', ' + B.x + ' ' + B.y, 'marker-end': 'url(#ah)' }));
    labels.push(h('span', { class: 'skiptxt', style: { left: ((A.x + B.x) / 2 - bulge * 0.75 - 6) + 'px', top: ((A.y + B.y) / 2) + 'px' } }, 'otherwise skipped'));
  });
  fill(CV.wg, paths); fill(CV.labels, labels);
}
function applyZoom() {
  const z = CV.zoom, cv = CV.el; let R = 0, B = 0;
  [...CV.nodesEl.children].forEach(el => { const p = posOf(el.dataset.id); if (!p) return; R = Math.max(R, p.x + el.offsetWidth + (el.querySelector('.nd-exit') ? 290 : 30)); B = Math.max(B, p.y + el.offsetHeight); });
  const W = Math.max(R + 140, cv.clientWidth / z), H = Math.max(B + 300, cv.clientHeight / z);
  CV.stage.style.width = W + 'px'; CV.stage.style.height = H + 'px'; CV.stage.style.transform = 'scale(' + z + ')';
  CV.sizer.style.width = W * z + 'px'; CV.sizer.style.height = H * z + 'px'; CV.sizer.style.backgroundSize = (22 * z) + 'px ' + (22 * z) + 'px';
  CV.zval.textContent = Math.round(z * 100) + '%';
}
function setZoom(z, cx, cy) {
  const cv = CV.el, r = cv.getBoundingClientRect(), z0 = CV.zoom;
  z = Math.max(0.4, Math.min(1.6, Math.round(z * 100) / 100));
  const px = (cx == null ? r.left + r.width / 2 : cx) - r.left, py = (cy == null ? r.top + r.height / 2 : cy) - r.top;
  const sx = (cv.scrollLeft + px) / z0, sy = (cv.scrollTop + py) / z0;
  CV.zoom = z; CV.auto = false; applyZoom(); cv.scrollLeft = sx * z - px; cv.scrollTop = sy * z - py;
}
function bounds() {
  let L = 1e9, T = 1e9, R = 0, B = 0;
  [...CV.nodesEl.children].forEach(el => { const p = posOf(el.dataset.id); if (!p) return; L = Math.min(L, p.x); T = Math.min(T, p.y); R = Math.max(R, p.x + el.offsetWidth + (el.querySelector('.nd-exit') ? 270 : 0)); B = Math.max(B, p.y + el.offsetHeight); });
  return { L, T, R, B };
}
// Fit: everything on screen. Opening a flow only fits the width, so the text stays readable and a long flow scrolls.
function fitView(whole) {
  const cv = CV.el, b = bounds();
  if (b.L > 1e8) return;
  const byWidth = cv.clientWidth / (b.R - b.L + 120), byHeight = cv.clientHeight / (b.B - b.T + 200);
  const z = Math.max(0.4, Math.min(1.1, whole ? Math.min(byWidth, byHeight) : Math.min(1, byWidth)));
  CV.zoom = Math.round(z * 100) / 100; CV.auto = true; applyZoom();
  cv.scrollLeft = Math.max(0, (b.L - 60) * CV.zoom); cv.scrollTop = Math.max(0, (b.T - 90) * CV.zoom);
}
function schedFrame() {
  if (document.hidden) { positionNodes(); drawWires(); applyZoom(); return; }
  if (CV.frame) return;
  CV.frame = true;
  requestAnimationFrame(() => { CV.frame = false; if (CV && CV.nodesEl) { positionNodes(); drawWires(); applyZoom(); } });
}
// on a phone-sized screen the panel covers the lower part of the canvas: bring the chosen box into the upper part
function revealAbove(id) {
  if (innerWidth > 700 || !CV.el) return;
  const p = posOf(id);
  if (p) CV.el.scrollTo({ top: Math.max(0, p.y * CV.zoom - 24), behavior: 'smooth' });
}
function scrollToNode(id) {
  const el = CV.nodesEl && CV.nodesEl.querySelector('[data-id="' + id + '"]');
  if (el) el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
}

// ----- Tidy up: one neat column, in the order the steps run -----
function tidy() {
  const NW = nodeW(), ids = chain(), to = {}; let y = CV_TOP;
  ids.forEach(id => { to[id] = { x: CV_CX - NW / 2, y }; y += (CV.hm[id] || 100) + CV_GAP; });
  if (ids.every(id => EW.pos[id] && Math.abs(EW.pos[id].x - to[id].x) < 1 && Math.abs(EW.pos[id].y - to[id].y) < 1)) { toast('Already tidy.'); return; }
  animateTo(to);
}
function animateTo(to) {
  const from = {}; Object.keys(to).forEach(id => { from[id] = { ...EW.pos[id] }; });
  const done = () => { commitLayout(); CV.el.scrollTo({ left: 0, top: 0, behavior: 'smooth' }); toast('Tidied up. The flow still runs in the same order.'); };
  const set = e => { Object.keys(to).forEach(id => { EW.pos[id] = { x: from[id].x + (to[id].x - from[id].x) * e, y: from[id].y + (to[id].y - from[id].y) * e }; }); positionNodes(); drawWires(); applyZoom(); };
  if (document.hidden) { set(1); done(); return; }
  const t0 = performance.now(), dur = 420;
  const step = now => { const t = Math.min(1, (now - t0) / dur); set(1 - Math.pow(1 - t, 3)); if (t < 1) requestAnimationFrame(step); else done(); };
  requestAnimationFrame(step);
}

// ----- moving boxes, moving the canvas, drawing wires -----
function wireCanvas(cv) {
  cv.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    if (e.target.closest('.plus,button,input,select,textarea,a')) return;
    const node = e.target.closest('.nd');
    if (node && e.target.closest('.nd-port.out') && node.dataset.id !== 'end') { startWire(e, node); return; }
    if (node && node.dataset.id !== 'end') {
      const id = node.dataset.id, multi = e.shiftKey || e.ctrlKey || e.metaKey, group = CV.sel.has(id) ? [...CV.sel] : [id];
      CV.G = { type: 'node', id, sx: e.clientX, sy: e.clientY, moved: false, multi, wasSel: CV.sel.has(id), group, orig: Object.fromEntries(group.map(g => [g, { ...EW.pos[g] }])) };
      cv.setPointerCapture(e.pointerId); e.preventDefault(); return;
    }
    if (!node) { CV.G = { type: 'pan', sx: e.clientX, sy: e.clientY, sl: cv.scrollLeft, st: cv.scrollTop, moved: false }; cv.setPointerCapture(e.pointerId); }
  });
  cv.addEventListener('pointermove', e => {
    const G = CV.G;
    if (!G) return;
    if (G.type === 'pan') {
      const dx = e.clientX - G.sx, dy = e.clientY - G.sy;
      if (Math.hypot(dx, dy) > 3) G.moved = true;
      cv.scrollLeft = G.sl - dx; cv.scrollTop = G.st - dy; cv.classList.toggle('panning', G.moved); return;
    }
    if (G.type === 'node') {
      const dx = (e.clientX - G.sx) / CV.zoom, dy = (e.clientY - G.sy) / CV.zoom;
      if (!G.moved) {
        if (Math.hypot(dx, dy) * CV.zoom < 4) return;
        G.moved = true;
        if (!G.wasSel && !G.multi) { CV.sel = new Set([G.id]); G.group = [G.id]; G.orig = { [G.id]: { ...EW.pos[G.id] } }; }
        [...CV.nodesEl.children].forEach(el => { el.classList.toggle('sel', CV.sel.has(el.dataset.id)); if (G.group.includes(el.dataset.id)) el.classList.add('dragging'); });
      }
      G.group.forEach(id => { const o = G.orig[id], p = EW.pos[id]; p.x = Math.max(8, o.x + dx); p.y = Math.max(8, o.y + dy); });
      schedFrame(); return;
    }
    if (G.type === 'wire') {
      if (Math.hypot(e.clientX - G.sx, e.clientY - G.sy) > 6) G.moved = true;
      const sp = toStage(e.clientX, e.clientY), A = outPt(G.from);
      G.tmp.setAttribute('d', 'M' + A.x + ' ' + A.y + ' C' + A.x + ' ' + (A.y + 60) + ', ' + sp.x + ' ' + (sp.y - 60) + ', ' + sp.x + ' ' + sp.y);
      const el = document.elementFromPoint(e.clientX, e.clientY), n = el && el.closest && el.closest('.nd');
      CV.nodesEl.querySelectorAll('.drop').forEach(x => x.classList.remove('drop'));
      if (n && n.dataset.id !== G.from && !['trigger', 'end', 'report'].includes(n.dataset.id)) { n.classList.add('drop'); G.target = n.dataset.id; } else G.target = null;
    }
  });
  cv.addEventListener('pointerup', e => {
    const g = CV.G;
    if (!g) return;
    CV.G = null;
    try { cv.releasePointerCapture(e.pointerId); } catch (_) { /* already released */ }
    cv.classList.remove('panning');
    if (g.type === 'pan') { if (!g.moved && CV.sel.size) { CV.sel = new Set(); renderNodes(); renderInspector(); } return; }
    if (g.type === 'node') {
      CV.nodesEl.querySelectorAll('.dragging').forEach(n => n.classList.remove('dragging'));
      if (!g.moved) {
        if (g.multi) { CV.sel.has(g.id) ? CV.sel.delete(g.id) : CV.sel.add(g.id); } else CV.sel = new Set([g.id]);
        if (CV.panel !== 'try') { CV.panel = 'insp'; CV.itab = 'set'; }
        renderNodes(); renderInspector(); revealAbove(g.id);
      } else commitLayout();
      return;
    }
    if (g.type === 'wire') endWire(e, g);
  });
  cv.addEventListener('pointercancel', () => { if (CV.G && CV.G.tmp) CV.G.tmp.remove(); CV.G = null; cv.classList.remove('panning'); });
  cv.addEventListener('wheel', e => { if (!(e.ctrlKey || e.metaKey)) return; e.preventDefault(); setZoom(CV.zoom * (e.deltaY < 0 ? 1.1 : 0.9), e.clientX, e.clientY); }, { passive: false });
  // a step dragged in from the list on the left: dropped near a "+" it goes there, anywhere else it goes to that spot
  cv.addEventListener('dragover', e => { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'; });
  cv.addEventListener('drop', e => {
    e.preventDefault();
    let d; try { d = JSON.parse(e.dataTransfer.getData('text/plain')); } catch (_) { return; }
    if (!d) return;
    const sp = toStage(e.clientX, e.clientY); let at = null, best = 80;
    CV.plusPts.forEach(p => { const dist = Math.hypot(p.x - sp.x, p.y - sp.y); if (dist < best) { best = dist; at = p.at; } });
    usePalItem(d, at, at == null ? { x: Math.max(8, sp.x - nodeW() / 2), y: Math.max(8, sp.y - 30) } : null);
  });
  cv.addEventListener('keydown', e => {
    const n = e.target.closest && e.target.closest('.nd');
    if (!n || e.key !== 'Enter' || n.dataset.id === 'end') return;
    CV.sel = new Set([n.dataset.id]); CV.panel = 'insp'; CV.itab = 'set'; renderNodes(); renderInspector();
  });
}
function startWire(e, node) {
  const p = svgEl('path', { class: 'wire tmpw' });
  CV.wg.append(p);
  CV.G = { type: 'wire', from: node.dataset.id, moved: false, sx: e.clientX, sy: e.clientY, tmp: p, target: null };
  CV.el.setPointerCapture(e.pointerId); e.preventDefault();
}
function endWire(e, g) {
  g.tmp.remove(); CV.nodesEl.querySelectorAll('.drop').forEach(x => x.classList.remove('drop'));
  if (g.target) { reorderAfter(g.from, g.target); return; }
  if (!g.moved) { toast('Drag from this dot onto another box to change what runs next.'); return; }
  if (isRead()) return;
  const sp = toStage(e.clientX, e.clientY), at = g.from === 'trigger' ? 0 : idxOf(g.from) + 1;
  const anchor = { getBoundingClientRect: () => ({ left: e.clientX, right: e.clientX, top: e.clientY, bottom: e.clientY, width: 0, height: 0 }) };
  cvOpenAdd(at, anchor, { x: Math.max(8, sp.x - nodeW() / 2), y: Math.max(8, sp.y) });
}
// drag from a box's dot onto another box: that box now runs right after this one
function reorderAfter(aId, bId) {
  const bi = idxOf(bId);
  if (bi < 0) return;
  const before = EW.ids.join();
  const [s] = EW.work.steps.splice(bi, 1), [id] = EW.ids.splice(bi, 1);
  const ai = aId === 'trigger' ? -1 : idxOf(aId);
  EW.work.steps.splice(ai + 1, 0, s); EW.ids.splice(ai + 1, 0, id);
  if (EW.ids.join() === before) { toast('“' + describeStep(s) + '” already runs right after that.'); return; }
  CV.run = null; commit(true);
  toast('“' + describeStep(s) + '” now runs right after the one you picked. Boxes stay where they are.');
}

// ----- adding, removing, re-ordering steps -----
const ONE_STEP = 'A building block is one step. To do several things, make a building block for each and run them one after another in a flow.';
const oneStepOnly = () => EW.work.kind === 'block' && EW.work.steps.length >= 1;
function cvAddStep(op, at, given, pos) {
  if (oneStepOnly()) { toast(ONE_STEP, 'bad'); return; }
  const spec = catalogSpec(op), step = { op, params: {} };
  (spec ? spec.params : []).forEach(p => { if (p.default !== undefined && p.kind !== 'column') step.params[p.key] = p.default; });
  Object.assign(step.params, given || {});
  const idx = at == null ? EW.work.steps.length : at, id = String(EW.nextId);
  EW.work.steps.splice(idx, 0, step); EW.ids.splice(idx, 0, EW.nextId++);
  if (pos) EW.pos[id] = pos; else if (idx < EW.work.steps.length - 1) CV.justAdded = id;
  CV.sel = new Set([id]); if (CV.panel !== 'try') CV.panel = 'insp'; CV.itab = 'set'; CV.run = null;
  commit(true);
  toast('Added “' + (op === 'run_workflow' || !spec ? describeStep(step) : spec.label) + '”. Save when you are happy with it.');
  if (CV.pal && innerWidth <= 1180) CV.pal.classList.add('closed');   // on a narrow screen the list covers the canvas
  scrollToNode(id);
}
async function removeSelected() {
  const ids = [...CV.sel].filter(id => id !== 'trigger' && id !== 'report');
  if (!ids.length) { toast('The first box cannot be removed. Every flow starts somewhere.'); return; }
  const names = ids.map(id => describeStep(EW.work.steps[idxOf(id)]));
  if (!await confirmBox('Remove ' + (ids.length === 1 ? 'this step? “' + names[0] + '”' : ids.length + ' steps?') + ' Undo brings it back.', { ok: 'Remove', danger: true })) return;
  ids.forEach(id => {                                         // the boxes below move up to close the gap
    const p = EW.pos[id], hh = CV.hm[id] || 100;
    chain().forEach(o => { const q = EW.pos[o]; if (o !== id && !ids.includes(o) && q && p && q.y > p.y && Math.abs(q.x - p.x) < nodeW()) q.y -= hh + CV_GAP; });
  });
  ids.forEach(id => { const i = idxOf(id); if (i >= 0) { EW.work.steps.splice(i, 1); EW.ids.splice(i, 1); } });
  CV.sel = new Set(); CV.run = null; commit(true);
}
function stepAct(act) {
  const id = primary(), i = idxOf(id);
  if (act === 'del') { removeSelected(); return; }
  if (i < 0) return;
  if (act === 'up' || act === 'down') {
    const j = act === 'up' ? i - 1 : i + 1;
    if (j < 0 || j >= EW.work.steps.length) return;
    const a = idAt(i), b = idAt(j), pa = EW.pos[a], pb = EW.pos[b];
    [EW.work.steps[i], EW.work.steps[j]] = [EW.work.steps[j], EW.work.steps[i]];
    [EW.ids[i], EW.ids[j]] = [EW.ids[j], EW.ids[i]];
    const first = idAt(Math.min(i, j)), second = idAt(Math.max(i, j)), top = Math.min(pa.y, pb.y);
    if (Math.abs(pa.x - pb.x) < nodeW()) { const x = Math.min(pa.x, pb.x); EW.pos[first] = { x, y: top }; EW.pos[second] = { x, y: top + (CV.hm[first] || 100) + CV_GAP }; }
    else { EW.pos[a] = pb; EW.pos[b] = pa; }
  }
  if (act === 'dup') {
    if (oneStepOnly()) { toast(ONE_STEP, 'bad'); return; }
    const c = clone(EW.work.steps[i]), nid = String(EW.nextId);
    EW.work.steps.splice(i + 1, 0, c); EW.ids.splice(i + 1, 0, EW.nextId++);
    CV.sel = new Set([nid]); if (i + 1 < EW.work.steps.length - 1) CV.justAdded = nid;
  }
  CV.run = null; commit(true);
}

// ----- keys: Tidy up, Undo, Delete, Escape (only while a flow is open and nothing is being typed) -----
document.addEventListener('keydown', e => {
  if (!EW || !CV || !CV.el || !CV.el.isConnected) return;
  const t = e.target;
  if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
  if (modalStack.length) return;
  if (e.shiftKey && e.altKey && e.key.toLowerCase() === 't') { e.preventDefault(); tidy(); }
  else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
  else if ((e.key === 'Delete' || e.key === 'Backspace') && CV.sel.size) { e.preventDefault(); removeSelected(); }
  else if (e.key === 'Escape' && CV.sel.size) { CV.sel = new Set(); renderNodes(); renderInspector(); }
});
window.addEventListener('resize', () => { if (CV && CV.el && CV.el.isConnected) applyZoom(); });
"""
