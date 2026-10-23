JS = r"""
// ───────────────────────── Flows: the plain editor ("Build with AI") ─────────────────────────
// #/workflows?f=new or =<id>: one flow (an admin's #/workflows lists them). On the left the chat with the AI; on the right the
// progress bar, draft / live, and four views of the same plain flow: Card (edit every step), Map, Simple chart and
// Try it (a rehearsal on the real engine). The plain flow is what the AI and the admin edit; "Make it live" turns it
// into engine steps on the server (build.py, flow_plain.py).
const BD = { id: null, version: null, name: '', live: null, plain: null, versions: [], isActive: false, talk: [], log: [], pending: [],
  problems: [], notes: [], info: {}, ctx: null, busy: false, view: 'flow', tech: false, sel: null, chat: false, undo: [], redo: [], open: new Set(), tried: null, draftSaved: true };
const BD_EMPTY = () => ({ start: { type: 'chat', words: '' }, before: [], asks: [], steps: [] });
const BD_KINDS = [['text', 'Words'], ['number', 'A number'], ['choice', 'Pick one'], ['date', 'A date'], ['time', 'A time'], ['yesno', 'Yes or no']];
const BD_OPS = [['is', 'is'], ['not', 'is not'], ['oneof', 'is one of'], ['empty', 'is empty'], ['filled', 'is filled in'], ['more', 'is more than'], ['less', 'is less than']];
const BD_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const BD_STEP = {
  say: { icon: '💬', label: 'Reply to the person', hint: 'In the chat they wrote from', g: 'Actions' },
  tell: { icon: '📣', label: 'Tell everyone in a role', hint: 'Committee, Security guard…', g: 'Actions' },
  find: { icon: '🔎', label: 'Look in a list', hint: 'Is there a row like this? Gives yes or no', g: 'Actions' },
  save: { icon: '🗂️', label: 'Save in a list', hint: 'Adds a row, with a number', g: 'Actions' },
  set: { icon: '✏️', label: 'Set a value', hint: 'Like Where = Wing [Wing]', g: 'Actions' },
  approve: { icon: '✅', label: 'Ask for approval', hint: 'Everyone in a role; gives Approve or Reject', g: 'Actions' },
  block: { icon: '🧩', label: 'Use a building block', hint: 'A ready-made part, like the ticket steps', g: 'Actions' },
  if: { icon: '🔀', label: 'Check something', hint: 'Yes does one thing, otherwise another', g: 'Logic' },
  stop: { icon: '⛔', label: 'Stop here', hint: 'Nothing after it runs', g: 'Logic' },
  engine: { icon: '⚙️', label: 'A step from the Flows editor', hint: '', g: '' },
};
const bdKey = () => 'build:' + (BD.id || 'new');
const bdKeep = () => { try { sessionStorage.setItem(bdKey(), JSON.stringify({ name: BD.name, plain: BD.id ? null : BD.plain, talk: BD.talk, log: BD.log, pending: BD.pending, tried: BD.tried })); } catch (e) {} };
const bdGet = (o, p) => p.split('.').reduce((x, k) => x == null ? x : x[k], o);
function bdSetPath(o, p, v) { const ks = p.split('.'), last = ks.pop(); bdGet(o, ks.join('.'))[last] = v; }
const bdLabelKey = s => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

// An admin's Flows screen (a super admin's is the Flows boxes, js_usecases.py / js_flows.py): every flow, opened in the
// plain editor; a flow from the canvas editor is opened in plain words the first time, without changing it.
async function renderBuildList(root) {
    setTopAction({ label: 'New flow', icon: 'spark', run: () => go('workflows', '', { f: 'new' }) });
    const d = await api.get('/build');
    const card = w => h('a', { class: 'card bd-card', href: href('workflows', '', { f: w.id }) },
      h('b', null, w.name), h('div', { class: 'muted small' }, (w.start && w.start.type === 'time' ? 'Runs by itself' : 'When someone writes' + (w.start && w.start.words ? ' “' + String(w.start.words).split(',')[0].trim() + '”' : ''))),
      h('div', null, badge(w.is_active ? 'On' : 'Off', w.is_active ? 'ok' : '')));
    // a flow made in the Flows editor opens here after one check: its steps stay exactly as they are
    const other = w => h('div', { class: 'card bd-card' + (w.ok ? '' : ' bd-card-off') }, h('b', null, w.name),
      w.ok ? h('div', { class: 'muted small' }, 'Opening it changes nothing it does.') : h('div', { class: 'muted small' }, w.why),
      h('div', { class: 'row' }, badge(w.is_active ? 'On' : 'Off', w.is_active ? 'ok' : ''), w.ok ? h('button', { class: 'btn sm primary', type: 'button', onclick: () => go('workflows', '', { f: w.id }) }, 'Open') : null));
    fill(root, h('div', { class: 'stack' },
      d.rows.length ? h('div', { class: 'bd-cards' }, d.rows.map(card))
        : h('div', { class: 'card' }, h('div', { class: 'card-b stack' }, h('b', null, 'No flows yet.'), h('div', { class: 'muted' }, 'Press New flow and tell the AI what the chat bot should do.'))),
      (d.others || []).length ? [h('h3', { class: 'bd-h3' }, 'More flows'), h('div', { class: 'muted small' }, 'Open one to see it as a flow, try it, and change it by hand or with the AI.'),
        h('div', { class: 'bd-cards' }, d.others.map(other))] : null));
}

async function renderBuild(root, r) {
  const mine = S.renderId;
  Object.assign(BD, { id: r.q.f === 'new' ? null : r.q.f, version: null, name: '', live: null, plain: BD_EMPTY(), versions: [], isActive: false, talk: [], log: [], pending: [],
    problems: [], notes: [], info: {}, busy: false, view: 'flow', sel: null, chat: r.q.f === 'new', undo: [], redo: [], open: new Set(), tried: null, draftSaved: true });
  BD.ctx = await api.get('/build/context');
  if (BD.id) {
    try { await api.post('/build/' + BD.id + '/convert'); }
    catch (e) {
      if (mine !== S.renderId) return;
      if (isSuper()) { location.replace(href('workflows', '', { w: BD.id })); return; }
      fill(root, h('div', { class: 'card' }, h('div', { class: 'card-b stack' }, h('b', null, 'This flow cannot be opened here yet.'), h('div', { class: 'muted' }, e.message), h('div', null, h('a', { class: 'btn', href: href('workflows') }, '← Flows')))));
      return;
    }
    const f = await api.get('/build/' + BD.id);
    Object.assign(BD, { name: f.name, version: f.version, live: f.plain, plain: JSON.parse(JSON.stringify(f.draft || f.plain)), versions: f.history || [], isActive: f.is_active });
  }
  try {
    const kept = JSON.parse(sessionStorage.getItem(bdKey()) || 'null');
    if (kept) { Object.assign(BD, { talk: kept.talk || [], log: kept.log || [], pending: kept.pending || [], tried: kept.tried || null }); if (!BD.id) { BD.name = kept.name || ''; if (kept.plain) BD.plain = kept.plain; } }
  } catch (e) {}
  BD.plain.before = BD.plain.before || [];
  if (mine !== S.renderId) return;
  const crumb = document.getElementById('crumbname'); if (crumb) crumb.textContent = BD.name || 'New flow';
  S.leaveGuard = () => BD.draftSaved || confirm('Leave now? The last change is still being kept.');
  const chatBox = h('div', { class: 'bd-chat' }), side = h('div', { class: 'bd-side' }), top = h('div');
  const grid = h('div', { class: 'bd-grid' }, chatBox, side);
  fill(root, h('div', { class: 'bd' }, top, grid));
  BD.paint = () => { grid.classList.toggle('nochat', !BD.chat); chatBox.hidden = !BD.chat; bdTop(top); if (BD.chat) bdChat(chatBox); bdSide(side); bdKeep(); };
  BD.paintSide = () => { bdTop(top); bdSide(side); bdKeep(); };
  BD.paint();
  bdCheck();
}

// ----- every change: undo, check, keep the draft -----
function bdChange(fn, quiet) {
  BD.undo.push(JSON.stringify(BD.plain)); if (BD.undo.length > 60) BD.undo.shift();
  BD.redo = [];
  fn(BD.plain);
  bdAfter(quiet);
}
function bdAfter(quiet) {
  bdCheck(); bdDraftSoon();
  if (!quiet) BD.paintSide();
}
let bdCheckSeq = 0, bdDraftTimer = null;
async function bdCheck() {
  const mine = ++bdCheckSeq;
  try {
    const r = await api.post('/build/check', { plain: BD.plain, pending_lists: BD.pending });
    if (mine !== bdCheckSeq) return;
    BD.problems = r.problems || []; BD.info = r.info || {}; BD.notes = r.notes || [];
    BD.paintSide();
  } catch (e) {}
}
function bdDraftSoon() {
  if (!BD.id) return;   // a new flow is kept in this browser until it is made live the first time
  BD.draftSaved = false; clearTimeout(bdDraftTimer);
  bdDraftTimer = setTimeout(async () => {
    try {
      if (JSON.stringify(BD.plain) === JSON.stringify(BD.live)) await api.del('/build/' + BD.id + '/draft');
      else await api.put('/build/' + BD.id + '/draft', { plain: BD.plain });
      BD.draftSaved = true; BD.paintSide();
    } catch (e) { toast('The draft could not be kept: ' + e.message, 'bad'); }
  }, 700);
}
const bdIsDraft = () => !BD.id || JSON.stringify(BD.plain) !== JSON.stringify(BD.live);

// ----- the top: name, progress bar, draft / live -----
function bdTop(box) {
  const name = h('input', { type: 'text', class: 'bd-name', value: BD.name, placeholder: 'Name of the flow', 'aria-label': 'Name of the flow',
    onchange: e => { BD.name = e.target.value; bdKeep(); BD.paintSide(); } });
  const st = BD.plain.start || {}, nSteps = BD.plain.report ? 1 : bdCount(BD.plain.steps) + bdCount(BD.plain.before), tried = BD.tried === JSON.stringify(BD.plain);
  const ready = !BD.problems.length && !BD.pending.length && nSteps > 0;
  const items = [
    { k: 'start', cls: 'ok', t: 'When it starts', s: bdStartWords(st) },
    { k: 'asks', cls: BD.plain.asks.length || st.type !== 'chat' || BD.plain.report ? 'ok' : 'todo', t: 'What it asks', s: BD.plain.asks.length ? BD.plain.asks.map(a => a.label).join(', ') : st.type === 'time' ? 'Nothing (it runs by itself)' : st.type !== 'chat' || BD.plain.report ? 'Nothing' : 'Add the questions' },
    { k: 'steps', cls: !nSteps ? 'todo' : BD.problems.length || BD.pending.length ? 'bad' : 'ok', t: 'What happens', s: BD.plain.report ? 'Looks up and replies' : !nSteps ? 'Add the steps' : nSteps + ' steps' + (BD.problems.length ? ' · ' + BD.problems.length + ' to fix' : BD.pending.length ? ' · lists to create' : ' · all fit') },
    { k: 'try', cls: tried ? 'ok' : 'todo', t: 'Try it', s: tried ? 'Tried this version' : 'Run it once' },
    { k: 'live', cls: !bdIsDraft() ? 'ok' : ready ? 'todo' : 'bad', t: 'Make it live', s: !bdIsDraft() ? 'Live, version ' + BD.version + (BD.isActive ? '' : ' (switched off)') : ready ? 'Ready' : 'Not ready yet' },
  ];
  const spine = h('div', { class: 'bd-spine' }, items.map((x, i) => h('button', { type: 'button', class: 'bd-sp-i ' + x.cls, onclick: () => {
    if (x.k === 'live') return bdPublish();
    if (x.k === 'try') { BD.view = 'try'; return BD.paintSide(); }
    if (x.k === 'start') return bdSelect('start');
    if (x.k === 'asks') return BD.plain.asks.length ? bdSelect('asks.0') : (BD.view = 'flow', BD.paintSide(), bdFlash('fx-asks'));
    const bad = BD.problems.find(pb => pb.path && bdGet(BD.plain, pb.path));
    return bad ? bdSelect(bad.path) : (BD.view = 'flow', BD.sel = null, BD.paintSide());
  } }, h('b', null, h('span', { class: 'd' }, x.cls === 'ok' ? '✓' : x.cls === 'bad' ? '!' : String(i + 1)), x.t), h('span', null, x.s))));
  let banner;
  if (!BD.id) banner = h('div', { class: 'bd-banner draft' }, h('span', null, '✏️ ', h('b', null, 'New draft.'), ' Nobody can use it until you make it live.'), h('span', { class: 'bd-sp' }), bdLiveBtn(ready));
  else if (bdIsDraft()) banner = h('div', { class: 'bd-banner draft' }, h('span', null, '✏️ ', h('b', null, 'Draft' + (BD.draftSaved ? '' : ' (keeping…)') + '.'), ' People still get live version ' + BD.version + '.'), h('span', { class: 'bd-sp' }),
    h('button', { class: 'btn sm', type: 'button', onclick: bdDiscard }, 'Throw away draft'), bdLiveBtn(ready));
  else banner = h('div', { class: 'bd-banner live' }, h('span', null, '✅ ', h('b', null, 'Live, version ' + BD.version + '.'), BD.isActive ? ' People use this one. Any change starts a draft.' : ' It is switched off: ' + (isSuper() ? 'switch it on and choose who can use it (Who can use it).' : 'a super admin switches it on.')),
    h('span', { class: 'bd-sp' }), isSuper() ? h('button', { class: 'btn sm', type: 'button', onclick: () => openAdvanced(BD.id) }, 'Who can use it') : null);
  const tools = h('div', { class: 'bd-tools' },
    h('button', { class: 'btn sm', type: 'button', disabled: !BD.undo.length, onclick: bdUndo }, 'Undo'),
    h('button', { class: 'btn sm', type: 'button', disabled: !BD.redo.length, onclick: bdRedo }, 'Redo'),
    h('button', { class: 'btn sm', type: 'button', onclick: bdExplain }, 'Explain this flow'),
    BD.id ? h('button', { class: 'btn sm', type: 'button', onclick: bdVersions }, 'Versions (' + BD.versions.length + ')') : null);
  fill(box, h('div', { class: 'bd-top' }, h('a', { class: 'btn ghost sm', href: href('workflows') }, '← Flows'), name, tools), spine, banner);
}
function bdLiveBtn(ready) {
  const why = !BD.plain.report && !bdCount(BD.plain.steps) && !bdCount(BD.plain.before) ? 'Nothing to make live yet' : BD.pending.length ? 'Create the new lists first' : BD.problems.length ? 'Fix what is not ready first' : '';
  return h('button', { class: 'btn sm primary', type: 'button', disabled: !!why || BD.busy, title: why, onclick: bdPublish }, 'Make it live');
}
const bdCount = l => (l || []).reduce((n, s) => n + 1 + bdCount(s.yes) + bdCount(s.no), 0);
function bdStartWords(st) {
  if (st.type === 'block') return 'Runs inside other flows (a building block)';
  if (st.type === 'button') return 'When someone taps its button on a ticket';
  if (st.type === 'time') {
    const when = st.every === 'week' && (st.days || []).length ? ' on ' + st.days.map(d => BD_DAYS[d] || d).join(', ') : st.every === 'month' && st.day_of_month ? ' on day ' + st.day_of_month : '';
    return 'By itself, every ' + (st.every || 'day') + when + (st.time ? ' at ' + st.time : '');
  }
  return 'When someone writes' + (st.words ? ' “' + String(st.words).split(',')[0].trim() + '”' : '');
}
function bdUndo() { if (!BD.undo.length) return; BD.redo.push(JSON.stringify(BD.plain)); BD.plain = JSON.parse(BD.undo.pop()); bdAfter(); toast('Undone.', 'ok'); }
function bdRedo() { if (!BD.redo.length) return; BD.undo.push(JSON.stringify(BD.plain)); BD.plain = JSON.parse(BD.redo.pop()); bdAfter(); toast('Done again.', 'ok'); }
// the whole flow as numbered sentences, made from the steps themselves (no AI)
function bdExplain() {
  const p = BD.plain;
  const lines = (list, path) => (list || []).map((s, i) => {
    const sp = path + '.' + i, B = bdBlockOf(s), note = BD.notes.find(n => n.path === sp);
    const when = s.a === 'engine' && s.when_words ? 'Only when ' + s.when_words + ': ' : '';
    const text = B ? B.name + (B.about ? '. ' + B.about : '') : s.a === 'engine' ? (s.words || 'A step') : s.a === 'if' ? bdQ(s) : bdWords(s);
    return h('li', null, when + text, note ? h('span', { class: 'bd-x-warn' }, ' ⚠ This never does anything here.') : null,
      s.a === 'if' ? h('ul', null, h('li', null, h('b', null, 'If yes: '), (s.yes || []).length ? h('ol', null, lines(s.yes, sp + '.yes')) : 'nothing extra'),
        h('li', null, h('b', null, 'Otherwise: '), (s.no || []).length ? h('ol', null, lines(s.no, sp + '.no')) : 'nothing extra')) : null);
  });
  modal({ title: 'This flow in plain words', wide: true, body: h('div', { class: 'stack bd-explain' },
    h('div', null, h('b', null, 'Starts: '), bdStartWords(p.start || {})),
    p.asks.length ? h('div', null, h('b', null, 'Asks: '), p.asks.map(a => a.label + (a.optional ? ' (can skip)' : '')).join(', ')) : null,
    (p.before || []).length ? [h('b', null, 'Before the questions:'), h('ol', null, lines(p.before, 'before'))] : null,
    p.report ? h('div', null, h('b', null, 'Then: '), 'looks up ' + p.report.words + ' and replies with it.') : [h('b', null, 'Then, top to bottom:'), h('ol', null, lines(p.steps, 'steps'))],
    BD.problems.length ? notice(BD.problems.length + ' thing(s) to fix: ' + BD.problems.map(x => x.text).join(' '), 'warn') : null,
    h('div', { class: 'muted small' }, 'Made from the steps themselves, without AI.')), actions: [{ label: 'Close' }] });
}
async function bdDiscard() {
  if (!await confirmBox('Throw away the draft? The flow goes back to live version ' + BD.version + '.', { ok: 'Throw it away', danger: true })) return;
  try { await api.del('/build/' + BD.id + '/draft'); } catch (e) {}
  BD.undo.push(JSON.stringify(BD.plain)); BD.plain = JSON.parse(JSON.stringify(BD.live)); BD.draftSaved = true; bdCheck(); BD.paintSide();
}
function bdVersions() {
  const rows = BD.versions.slice().reverse();
  const m = modal({ title: 'Versions', body: h('div', { class: 'stack' }, h('div', { class: 'muted small' }, 'Restore copies an old version into the draft. Nothing changes for people until you make it live.'),
    rows.length ? rows.map(v => h('div', { class: 'bd-ver' }, h('b', null, 'v' + v.v), h('span', { class: 'muted small' }, v.at || ''), h('span', { class: 'grow' }, v.note || ''),
      v.v === BD.version ? badge('live', 'ok') : h('button', { class: 'btn sm', type: 'button', onclick: async () => {
        const r = await api.post('/build/' + BD.id + '/restore', { v: v.v });
        BD.undo.push(JSON.stringify(BD.plain)); BD.plain = r.plain; BD.plain.before = BD.plain.before || []; m.close(); bdAfter(); toast('Version ' + v.v + ' is now the draft.', 'ok');
      } }, 'Restore'))) : h('div', { class: 'muted' }, 'Not made live yet.')), actions: [{ label: 'Close' }] });
}
function bdPublish() {
  if (BD.pending.length) { toast('Create the new lists first.', 'bad'); return; }
  if (BD.problems.length) { toast('Fix what is not ready first.', 'bad'); const bad = BD.problems.find(pb => pb.path && bdGet(BD.plain, pb.path)); bad ? bdSelect(bad.path) : (BD.view = 'flow', BD.paintSide()); return; }
  if (!BD.name.trim() || BD.name.trim().length < 2) { toast('Give the flow a name first.', 'bad'); document.querySelector('.bd-name').focus(); return; }
  const ch = [], d = BD.plain, l = BD.live;
  if (!l) ch.push('It is made for the first time' + (isSuper() ? '' : '; a super admin switches it on.'));
  else {
    if (JSON.stringify(d.start) !== JSON.stringify(l.start)) ch.push('When it starts: ' + bdStartWords(d.start));
    const qa = d.asks.map(a => a.label), ql = (l.asks || []).map(a => a.label);
    qa.filter(q => !ql.includes(q)).forEach(q => ch.push('New question: ' + q)); ql.filter(q => !qa.includes(q)).forEach(q => ch.push('Question removed: ' + q));
    if (JSON.stringify([d.before, d.steps]) !== JSON.stringify([l.before || [], l.steps])) ch.push('What happens has changed (see the Map)');
    if (!ch.length) ch.push('Nothing is different from the live version');
  }
  const tried = BD.tried === JSON.stringify(BD.plain), note = h('input', { type: 'text', placeholder: 'A short note (optional)', style: { width: '100%' } });
  modal({ title: 'Make it live?', body: h('div', { class: 'stack' },
    h('div', { class: 'muted small' }, BD.id ? 'This becomes version ' + (BD.version + 1) + '. The old version is kept and can be restored.' : 'The flow is saved as version 1.'),
    h('b', null, 'What changes for people'), h('ul', null, ch.map(c => h('li', null, c))),
    tried ? notice('✓ You tried this version.', 'ok') : notice('You have not tried this version yet. Open “Try it” first, to be safe.', 'warn'), note),
    actions: [{ label: 'Cancel' }, { label: 'Make it live', primary: true, run: async () => {
      const first = !BD.id;
      const r = await api.post('/build/save', { name: BD.name.trim(), plain: BD.plain, workflow_id: BD.id, base_version: BD.version, note: note.value.trim() });
      if (first) { try { sessionStorage.removeItem(bdKey()); } catch (e) {} }
      BD.id = r.id; BD.version = r.version; BD.live = JSON.parse(JSON.stringify(BD.plain)); BD.draftSaved = true;
      const f = await api.get('/build/' + r.id); BD.versions = f.history || []; BD.isActive = f.is_active;
      history.replaceState(null, '', href('workflows', '', { f: r.id })); bdKeep(); BD.paintSide();
      toast(first ? 'Saved as version 1. ' + (isSuper() ? 'Switch it on and choose who can use it.' : 'A super admin switches it on.') : 'Live: version ' + r.version + '.', 'ok');
    } }] });
}

// ----- the chat -----
function bdChat(box) {
  const say = t => bdSend(t);
  const log = BD.log.length ? BD.log.map((m, i) => m.who === 'you' ? h('div', { class: 'bd-msg you' }, m.text) :
    h('div', { class: 'bd-msg ai' + (m.warn ? ' warn' : '') }, m.text,
      m.changes && m.changes.length ? h('ul', null, m.changes.map(c => h('li', null, c))) : null,
      m.questions && m.questions.length ? h('div', { class: 'bd-qs' }, m.questions.map(q => h('div', { class: 'bd-q' }, h('div', null, q.text),
        q.options && q.options.length && i === BD.log.length - 1 ? h('div', { class: 'bd-opts' }, q.options.map((o, k) => h('button', { type: 'button', class: 'btn sm' + (k === 0 ? ' primary' : ''), onclick: () => say(o) }, o))) : null))) : null,
      m.undo && i === BD.log.length - 1 ? h('div', null, h('button', { class: 'btn sm', type: 'button', onclick: () => { m.undo = false; bdUndo(); BD.paint(); } }, 'Undo this')) : null))
    : [h('div', { class: 'bd-hello' }, h('b', null, 'Tell the AI what this flow should do.'), h('div', { class: 'muted' }, 'One thing at a time, like a WhatsApp message. It asks you when there is a choice to make. You can also change anything yourself: click a box in the flow.'),
       h('div', { class: 'bd-opts' }, ['Residents should be able to book the clubhouse', 'Visitors: a resident tells security who is coming', 'Every month remind flats with unpaid dues'].map(e => h('button', { type: 'button', class: 'btn sm', onclick: () => say(e) }, e))))];
  const input = h('textarea', { rows: 2, placeholder: BD.log.length ? 'Your next message' : 'For example: residents should be able to book the clubhouse for functions', disabled: BD.busy,
    onkeydown: e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go_(); } } });
  const go_ = () => { const t = input.value.trim(); if (t && !BD.busy) say(t); };
  const list = h('div', { class: 'bd-log' }, log, BD.busy ? h('div', { class: 'bd-msg ai muted' }, 'Thinking…') : null);
  fill(box, list, h('div', { class: 'bd-in' }, input, h('button', { class: 'btn primary', type: 'button', disabled: BD.busy, onclick: go_ }, BD.busy ? '…' : 'Send')));
  list.scrollTop = list.scrollHeight;
  if (!BD.busy) setTimeout(() => input.focus(), 0);
}

// text: what the admin wrote. at: "+ Add a step" was pressed at this list (the AI writes the new step(s) there)
async function bdSend(text, at, idx) {
  BD.log.forEach(m => { m.undo = false; });
  BD.log.push({ who: 'you', text: at ? '(new step) ' + text : text }); BD.busy = true; BD.paint();
  let flow = BD.plain, message = text;
  if (at) {
    flow = JSON.parse(JSON.stringify(BD.plain)); const list = bdGet(flow, at); list.splice(idx == null ? list.length : idx, 0, { a: 'HERE' });
    message = 'The admin pressed "+ Add a step" where the flow has {"a": "HERE"}. Replace that one item with what they describe (one step, or a few if needed); keep everything else. They say: ' + text;
  }
  try {
    const r = await api.post('/build/chat', { message, history: BD.talk.slice(-12), flow, pending_lists: BD.pending });
    BD.talk.push({ role: 'user', content: text }, { role: 'assistant', content: [r.reply, ...(r.questions || []).map(q => q.text)].filter(Boolean).join('\n') });
    if (r.flow) { BD.undo.push(JSON.stringify(BD.plain)); BD.plain = r.flow; BD.plain.before = BD.plain.before || []; }
    BD.pending = r.new_lists || [];
    BD.problems = r.problems || []; BD.info = r.info || {};
    BD.log.push({ who: 'ai', text: r.reply || (r.flow ? 'Done.' : 'Nothing changed.'), changes: r.changes, questions: r.questions, warn: (r.questions || []).length > 0 || BD.problems.length > 0, undo: !!r.flow });
    if (!BD.name && r.flow) BD.name = text.length > 60 ? text.slice(0, 58) + '…' : text.charAt(0).toUpperCase() + text.slice(1);
    if (r.flow) bdDraftSoon();
  } catch (e) { BD.log.push({ who: 'ai', text: 'The AI could not answer: ' + e.message, warn: true }); }
  BD.busy = false; BD.paint();
}

// ----- the right side: lists to create, what is not ready, the four views -----
function bdSide(box) {
  const lists = BD.pending.map((op, i) => h('div', { class: 'bd-list' },
    h('div', null, h('b', null, 'New list: ' + (op.plural || op.label)), op.about ? h('div', { class: 'muted small' }, op.about) : null,
      h('div', { class: 'small' }, (op.fields || []).map(f => f.label + (f.kind === 'choice' && f.options ? ' (' + f.options.join(', ') + ')' : f.kind && f.kind !== 'text' ? ' (' + f.kind + ')' : '')).join(' · '))),
    h('button', { class: 'btn sm primary', type: 'button', onclick: async e => {
      e.target.disabled = true;
      try {
        await api.post('/schema/apply', { ops: [op] });
        BD.pending.splice(i, 1); BD.ctx = await api.get('/build/context');
        toast('Created the list ' + (op.plural || op.label) + '.', 'ok'); bdCheck(); BD.paintSide();
      } catch (x) { toast(x.message, 'bad'); e.target.disabled = false; }
    } }, 'Create it')));
  const loose = BD.problems.filter(p => !p.path || !bdGet(BD.plain, p.path));
  const tabs = h('div', { class: 'bd-tabs' }, [['flow', '🧭 The flow'], ['try', '📱 Try it']].map(([k, l]) =>
    h('button', { type: 'button', class: BD.view === k ? 'on' : '', onclick: () => { BD.view = k; BD.paintSide(); } }, l)),
    h('span', { class: 'bd-sp' }), h('button', { type: 'button', class: BD.chat ? 'on' : '', title: 'Build or change it by chatting with the AI', onclick: () => { BD.chat = !BD.chat; BD.paint(); } }, BD.chat ? '🤖 Hide the AI chat' : '🤖 Build with the AI'));
  const view = BD.view === 'try' ? bdTry() : bdFlowView();
  fill(box, lists.length ? h('div', { class: 'bd-lists' }, h('div', { class: 'muted small' }, 'The flow needs these lists. Create them to make it live.'), lists) : null,
    loose.length ? h('div', { class: 'bd-probs' }, h('b', null, 'Not ready yet'), h('ul', null, loose.map(p => h('li', null, p.text))), h('div', { class: 'muted small' }, 'Click the red box in the flow to fix it, or tell the AI.')) : null,
    tabs, view);
}
function bdFlash(id) {
  setTimeout(() => { const el = document.getElementById(id); if (!el) return; el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.classList.add('bd-flash'); setTimeout(() => el.classList.remove('bd-flash'), 1500); }, 30);
}
const bdGo = p => bdSelect(p === 'asks' ? (BD.plain.asks.length ? 'asks.0' : 'start') : p);

// ----- small parts the editor uses -----
const bdSel = (opts, value, on, attrs) => h('select', { ...(attrs || {}), onchange: e => on(e.target.value) }, (opts.some(o => String(o[0]) === String(value)) || value == null || value === '' ? opts : [...opts, [value, value]]).map(([v, l]) => h('option', { value: v, selected: String(v) === String(value) }, l)));
const bdInp = (value, on, attrs) => h('input', { type: 'text', value: value == null ? '' : value, onchange: e => on(e.target.value), ...(attrs || {}) });
function bdLists() {
  const out = {};
  Object.entries((BD.ctx && BD.ctx.lists) || {}).forEach(([k, t]) => { out[t.label] = { label: t.label, plural: t.plural, cols: Object.values(t.fields || {}).map(f => f.label) }; });
  BD.pending.forEach(op => { out[op.label] = { label: op.label, plural: op.plural, cols: (op.fields || []).map(f => f.label), pending: true }; });
  return out;
}
function bdListOf(name) { const L = bdLists(), low = String(name || '').toLowerCase(); return Object.values(L).find(t => [t.label, t.plural].some(x => String(x).toLowerCase() === low)) || null; }
function bdKnownAt(listPath) {     // what is known at the end of a list of steps: for "+ Add a step" and the value chips
  const list = bdGet(BD.plain, listPath) || [];
  if (list.length) { const last = BD.info[listPath + '.' + (list.length - 1)]; if (last) return [...new Set([...(last.known || []), ...(last.gives || [])])]; }
  const parent = listPath.replace(/\.(yes|no)$/, '');
  if (parent !== listPath && BD.info[parent]) return BD.info[parent].known || [];
  return (BD.info[listPath] && BD.info[listPath].known) || [];
}
function bdChips(path, field, known) {
  return h('div', { class: 'bd-ins' }, h('span', { class: 'muted small' }, 'Put in:'), (known || []).map(v => h('button', { type: 'button', onclick: () => bdChange(d => { const s = bdGet(d, path); s[field] = (s[field] || '') + '[' + v + ']'; }) }, v)));
}
function bdRename(d, old, now) {   // renaming an answer renames it wherever it is used
  if (!old || old === now) return;
  const swap = l => (l || []).forEach(s => {
    ['text', 'value'].forEach(k => { if (typeof s[k] === 'string') s[k] = s[k].split('[' + old + ']').join('[' + now + ']'); });
    ['match', 'values'].forEach(k => { if (s[k]) Object.keys(s[k]).forEach(c => { if (s[k][c] === '[' + old + ']') s[k][c] = '[' + now + ']'; }); });
    (s.tests || []).forEach(t => { if (t.q === old) t.q = now; });
    swap(s.yes); swap(s.no);
  });
  swap(d.before); swap(d.steps);
}
// one colour per kind of step, always shown with its word (the key sits above the steps)
const BD_CATS = { info: ['#2563eb', 'Asks / finds', 'gets information'], decide: ['#ea580c', 'Decides', 'checks something'], calc: ['#ca8a04', 'Works out', 'sets or counts a value'],
  save: ['#16a34a', 'Saves', 'adds or changes a record'], message: ['#db2777', 'Messages', 'tells someone'], stop: ['#dc2626', 'Stops', 'ends the flow'], block: ['#0d9488', 'Building block', 'shared steps'] };
const BD_OPCAT = { run_workflow: 'block', 'flow.stop': 'stop', 'flow.decide': 'decide', require_permission: 'decide', 'case.authorize': 'decide', conflict_check: 'decide',
  approval_gate: 'decide', otp_gate: 'decide', ask_approval: 'decide', derive_field: 'calc', compute: 'calc', 'flow.set': 'calc', ai_price_interpret: 'calc',
  'flow.say': 'message', 'flow.tell': 'message', 'pdf.generate': 'message', 'case.route': 'info' };
function bdCat(s) {
  if (s.a === 'engine') { const op = (s.step || {}).op || ''; return BD_OPCAT[op] || (/^notify\./.test(op) ? 'message' : /^(db|case)\./.test(op) ? 'save' : 'info'); }
  return { say: 'message', tell: 'message', find: 'info', save: 'save', set: 'calc', approve: 'decide', block: 'block', if: 'decide', stop: 'stop' }[s.a] || 'info';
}
function bdBlockOf(s) {    // a building block step (made here, or kept from the older editor): its name, what it does, its steps
  const prm = s.a === 'engine' && (s.step || {}).op === 'run_workflow' ? (s.step.params || {}) : null;
  const key = s.a === 'block' ? s.key : prm ? prm.workflow || prm.intent_key : null;
  if (!key) return null;
  const B = ((BD.ctx && BD.ctx.block_info) || {})[key];
  return B ? { key, inputs: prm && prm.inputs || {}, ...B } : { key, inputs: prm && prm.inputs || {}, name: (BD.ctx.blocks || {})[key] || key, about: '', steps: [], used_by: 0 };
}
const bdPretty = k => String(k || '').replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
const bdLegend = () => h('div', { class: 'bd-legend' }, Object.values(BD_CATS).map(([c, w, m]) => h('span', { style: '--c:' + c, title: m }, h('i'), w)));
// when a step runs, in words: its own "only when", and for a building block what its steps wait for
function bdRunsWords(s, B) {
  const parts = [];
  if (s.a === 'engine' && s.when_words) parts.push('Only when ' + s.when_words);
  if (B && B.steps.length && B.steps.every(x => x.when_words)) parts.push('Inside, it only acts when ' + [...new Set(B.steps.map(x => x.when_words))].join(', or '));
  return parts.length ? parts.join('. ') : 'Always';
}
function bdBlockBody(s, p, B) {
  const open = BD.open.has(p), others = Math.max(0, (B.used_by || 0) - 1), given = Object.entries(B.inputs || {});
  const short = v => { const t = typeof v === 'string' ? v : JSON.stringify(v); return t.length > 60 ? t.slice(0, 58) + '…' : t; };
  return [h('div', { class: 'bd-sentence' }, h('b', null, B.name)), B.about ? h('div', { class: 'muted small' }, B.about) : null,
    given.length ? h('div', { class: 'bd-given' }, h('b', null, 'This flow gives it: '), given.map(([k, v]) => bdPretty(k) + ' = ' + short(v)).join(' · ')) : null,
    B.steps.length ? h('button', { type: 'button', class: 'bd-toggle', onclick: () => { open ? BD.open.delete(p) : BD.open.add(p); BD.paintSide(); } },
      (open ? '▾ Hide' : '▸ Show') + ' its ' + B.steps.length + ' step' + (B.steps.length > 1 ? 's' : '') + ' · shared with ' + others + ' other flow' + (others === 1 ? '' : 's')) : null,
    open ? h('ol', { class: 'bd-inside' }, B.steps.map(x => h('li', { style: '--c:' + BD_CATS[BD_OPCAT[x.op] || (/^notify\./.test(x.op || '') ? 'message' : /^(db|case)\./.test(x.op || '') ? 'save' : 'info')][0] },
      x.when_words ? h('span', { class: 'bd-only' }, 'only when ' + x.when_words + ': ') : null, x.words))) : null,
    open ? h('div', { class: 'muted small' }, isSuper() ? 'These steps are shared: changing them changes every flow that uses this block. ' : 'These steps are shared between flows: a super admin changes them.',
      isSuper() && B.id ? h('a', { href: href('workflows', '', { f: B.id }) }, 'Open the building block') : null) : null];
}
function bdMove(p, by) { bdChange(d => { const ks = p.split('.'), i = +ks.pop(), arr = bdGet(d, ks.join('.')), j = i + by; if (j < 0 || j >= arr.length) return; [arr[i], arr[j]] = [arr[j], arr[i]]; }); }
function bdRemove(p) { bdChange(d => { const ks = p.split('.'), i = +ks.pop(); bdGet(d, ks.join('.')).splice(i, 1); }); }

// what does not fit, in words, with the fixes that make sense (the first is the suggested one)
function bdProblem(pb, p) {
  const ks = p.split('.'), idx = +ks.pop(), lp = ks.join('.'), list = bdGet(BD.plain, lp) || [], fixes = [];
  const later = list.findIndex((x, i) => i > idx && ((BD.info[lp + '.' + i] || {}).gives || []).includes(pb.need));
  if (later >= 0) fixes.push({ label: 'Move this step below “' + bdShort(list[later]) + '”', run: () => bdChange(d => { const arr = bdGet(d, lp); const [x] = arr.splice(idx, 1); arr.splice(later, 0, x); }) });
  else if (pb.need && /nothing before it gives/.test(pb.text) && !/ found$|^Approval$| number$/.test(pb.need) && !lp.startsWith('before')) fixes.push({ label: 'Ask the person: “' + pb.need + '”', run: () => bdChange(d => { d.asks.push({ label: pb.need, q: pb.need + '?', kind: 'text' }); }) });
  fixes.push({ label: 'Ask the AI to fix it', run: () => { BD.chat = true; BD.paint(); bdSend('Please fix this: ' + pb.text); } });
  fixes.push({ label: 'Remove this step', run: () => { bdRemove(p); BD.sel = null; BD.paintSide(); } });
  return h('div', { class: 'bd-prob' }, '⚠️ ' + pb.text, h('div', { class: 'bd-row' }, fixes.map((f, i) => h('button', { type: 'button', class: 'btn sm' + (i === 0 ? ' primary' : ''), onclick: f.run }, (i === 0 ? '🤖 Fix it: ' : '') + f.label))));
}
const bdShort = s => (BD_STEP[s.a] || {}).label || s.a;

// "+ Add a step": describe it to the AI, or pick one
function bdPick(listPath, idx) {
  const at = idx == null ? (bdGet(BD.plain, listPath) || []).length : idx;
  const known = bdKnownAt(listPath), before = listPath.startsWith('before');
  const words = h('input', { type: 'text', placeholder: 'For example: if the place is taken, tell them and stop', style: { flex: '1' } });
  const defaults = {
    say: { a: 'say', text: 'Done. Thank you!' }, tell: { a: 'tell', role: (BD.ctx.roles || [])[0] || '', text: '' },
    find: { a: 'find', list: (Object.values(bdLists())[0] || {}).label || '', match: {}, name: 'Found' }, save: { a: 'save', list: (Object.values(bdLists())[0] || {}).label || '', values: {} },
    set: { a: 'set', name: 'Value', value: '' }, approve: { a: 'approve', role: (BD.ctx.roles || [])[0] || '', text: 'Please approve.' },
    block: { a: 'block', key: Object.keys(BD.ctx.blocks || {})[0] || '' }, if: { a: 'if', match: 'all', tests: [{ q: known[0] || 'Role', op: 'is', value: '' }], yes: [], no: [] }, stop: { a: 'stop' },
  };
  let m;
  const groups = [['Actions', 'Actions: what it does'], ['Logic', 'Logic: checks and stopping']].map(([g, label]) => h('div', null, h('div', { class: 'bd-grp' }, label),
    h('div', { class: 'bd-acts' }, Object.entries(BD_STEP).filter(([kk, x]) => x.g === g && !(kk === 'block' && !Object.keys(BD.ctx.blocks || {}).length)).map(([kk, x]) =>
      h('button', { type: 'button', onclick: () => { m.close(); bdChange(d => { bdGet(d, listPath).splice(at, 0, JSON.parse(JSON.stringify(defaults[kk]))); }); bdSelect(listPath + '.' + at); } },
        x.icon + ' ', h('b', null, x.label), h('small', null, x.hint))))));
  m = modal({ title: 'Add a step', wide: true, body: h('div', { class: 'stack' },
    h('div', { class: 'bd-aibox' }, h('b', null, '🤖 Describe the step'), h('div', { class: 'bd-row' }, words, h('button', { class: 'btn primary', type: 'button', onclick: () => { const t = words.value.trim(); if (!t) return; m.close(); BD.chat = true; BD.paint(); bdSend(t, listPath, at); } }, 'Add it'))),
    h('div', { class: 'muted small' }, 'Or pick one. Known here: ' + (known.join(', ') || 'nothing yet') + (before ? '. (Before the questions, no answers are known.)' : '.')), groups),
    actions: [{ label: 'Cancel' }] });
  words.addEventListener('keydown', e => { if (e.key === 'Enter') { const t = words.value.trim(); if (t) { m.close(); BD.chat = true; BD.paint(); bdSend(t, listPath, at); } } });
}

// ----- a check, and a step, in a few words -----
const BD_YESNO = { 'Approval': { approve: 'Approved?', reject: 'Not approved?' } };
function bdQ(s) {
  return (s.tests || []).map(t => {
    const v = String(t.value || ''), low = v.toLowerCase(), q = t.q || '';
    if (/ found$/.test(q) && t.op === 'is' && (low === 'yes' || low === 'no')) return (low === 'yes' ? '' : 'No ') + (low === 'yes' ? q : q.replace(/ found$/, '').toLowerCase() + ' found');
    if (BD_YESNO[q] && BD_YESNO[q][low] && t.op === 'is') return BD_YESNO[q][low].replace(/\?$/, '');
    const op = { is: 'is', not: 'is not', oneof: 'is one of', empty: 'is empty', filled: 'is filled in', more: 'is more than', less: 'is less than' }[t.op] || 'is';
    return q + ' ' + op + (['empty', 'filled'].includes(t.op) ? '' : ' ' + v);
  }).join(s.match === 'any' ? ' or ' : ' and ') + '?';
}
function bdWords(s) {
  const blocks = (BD.ctx && BD.ctx.blocks) || {};
  return ({ say: 'Reply to them: “' + (s.text || '').slice(0, 70) + ((s.text || '').length > 70 ? '…' : '') + '”', tell: 'Tell everyone who is ' + (s.role || '?') + (s.text ? ': “' + s.text.slice(0, 60) + (s.text.length > 60 ? '…' : '') + '”' : ''), set: (s.name || '?') + ' = ' + (s.value || ''),
    _look: 'Look up: ' + ((BD.plain.report || {}).words || 'the saved question'),
    _reply: (BD.plain.report || {}).format === 'list' ? 'Reply with the list it found' : 'Reply with what it found (written up by the AI)',
    engine: (s.words || 'A step') + (s.when_words ? ' (only when ' + s.when_words + ')' : ''),
    _ask: 'Ask: ' + BD.plain.asks.map(a => a.label).join(', '), find: 'Look in ' + (s.list || '?'), save: 'Save in ' + (s.list || '?'), approve: 'Ask ' + (s.role || '?') + ' to approve', block: 'Run “' + (blocks[s.key] || s.key) + '”' })[s.a] || s.a;
}
// ----- the flow as one chart (like the prototype): coloured boxes top to bottom, + on every line, checks split
// into Yes / Otherwise, "only if" groups, building blocks in a teal frame. Click a box: its editor opens beside it.
const bdIsOnly = s => s && s.a === 'if' && (s.yes || []).length > 0 && !(s.no || []).length;
function bdSelect(p) {
  BD.sel = p; BD.view = 'flow'; BD.paintSide();
  setTimeout(() => { const el = document.getElementById('fx-' + p); if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }, 30);
}
function bdGlow(p, on) { const el = p && document.getElementById('fx-' + p); if (el) el.classList.toggle('fx-glow', on); }
// where a value comes from: the question, or the step before that gives it
function bdSourceOf(name, path) {
  const i = BD.plain.asks.findIndex(a => a.label === name);
  if (i >= 0) return 'asks.' + i;
  if (name === 'Name' || name === 'Phone' || name === 'Role' || name === 'Flat') return 'start';
  const hit = Object.keys(BD.info).filter(k => k !== path && ((BD.info[k] || {}).gives || []).includes(name));
  return hit[0] || null;
}
function fxConn(listPath, idx, plain) {
  return h('div', { class: 'fx-conn' + (plain ? ' short' : '') }, listPath ? h('button', { type: 'button', class: 'fx-plus', title: 'Add a step here', onclick: () => bdPick(listPath, idx) }, '+') : null);
}
function fxChips(p, s) {
  const inf = BD.info[p] || {}, needs = inf.needs || [], gives = inf.gives || [];
  if (!needs.length && !gives.length) return null;
  return h('div', { class: 'fx-chips' },
    needs.map(x => { const src = bdSourceOf(x.n, p); return h('span', { class: 'fx-chip ' + (x.ok ? 'need' : 'bad'), title: (x.ok ? 'Uses this.' : 'Not known at this point.') + (src ? ' Hover to see where it comes from.' : ''),
      onmouseenter: () => bdGlow(src, true), onmouseleave: () => bdGlow(src, false) }, (x.ok ? '← ' : '⚠ ') + x.n); }),
    gives.slice(0, 5).map(g => h('span', { class: 'fx-chip give', title: 'Later steps can use this' }, '→ ' + g)),
    gives.length > 5 ? h('span', { class: 'fx-chip give', title: gives.slice(5).join(', ') }, '+' + (gives.length - 5) + ' more') : null);
}
// one box. o: {cat, title, words, icon, band, warn}
function fxBox(p, s, o) {
  const [color, catWord] = BD_CATS[o.cat] || [o.cat === 'start' ? '#1e40af' : '#475569', o.catWord || ''];
  const probs = BD.problems.filter(x => x.path === p), note = BD.notes.find(x => x.path === p);
  return h('div', { class: 'fx-card' + (BD.sel === p ? ' sel' : '') + (probs.length ? ' bad' : ''), id: 'fx-' + p, style: '--c:' + color, onclick: () => bdSelect(p) },
    o.num ? h('span', { class: 'fx-num' }, o.num) : null,
    note ? h('div', { class: 'fx-band never' }, '✗ Never does anything here') : o.band ? h('div', { class: 'fx-band' }, '⚡ ' + o.band) : null,
    h('div', { class: 'fx-head' }, h('span', { class: 'bd-cat' }, o.catWord || catWord), h('span', { class: 'fx-kind' }, (o.icon || '') + ' ' + (o.title || ''))),
    h('div', { class: 'fx-words' + (o.words ? '' : ' empty') }, o.words || 'Click to fill this in'),
    o.extra || null,
    s ? fxChips(p, s) : null,
    probs.length ? h('div', { class: 'fx-warn' }, '⚠ ' + probs[0].text + (probs.length > 1 ? ' (+' + (probs.length - 1) + ')' : '')) : note ? h('div', { class: 'fx-warn' }, '⚠ ' + note.text) : null,
    fxTip(p, s, o, probs, note));
}
// hover: what it does, what it uses and gives, when it runs, and what is wrong (with the fixes)
function fxTip(p, s, o, probs, note) {
  const inf = BD.info[p] || {}, B = s ? bdBlockOf(s) : null, k = s ? BD_STEP[s.a] || {} : {};
  const what = o.what || (B ? (B.about || B.name) : !s ? '' : s.a === 'engine' ? (s.words || 'A step') : s.a === 'if' ? 'Checks: ' + bdQ(s) : (k.label || '') + (k.hint ? ': ' + k.hint.toLowerCase() : ''));
  const row = (a, b) => h('tr', null, h('td', null, a), h('td', null, b));
  return h('div', { class: 'fx-tip', onclick: e => e.stopPropagation() }, h('div', { class: 'fx-tipbox' },
    h('table', null, row('What it does', what),
      s ? row('Uses', (inf.needs || []).length ? inf.needs.map(x => (x.ok ? '' : '⚠ ') + x.n).join(', ') : 'nothing from earlier steps') : null,
      s ? row('Gives', (inf.gives || []).length ? inf.gives.join(', ') : 'nothing new') : null,
      s ? row('Runs', o.runs || 'Always') : null,
      B ? row('Shared', 'Used by ' + (B.used_by || 0) + ' flow' + (B.used_by === 1 ? '' : 's') + '. ' + (isSuper() ? 'Changing its steps changes all of them.' : 'A super admin changes its steps; you can make a copy just for this flow.')) : null),
    note ? h('div', { class: 'bd-prob warn' }, '⚠️ ' + note.text, h('div', { class: 'bd-row' }, h('button', { type: 'button', class: 'btn sm primary', onclick: () => { bdRemove(p); BD.sel = null; toast('Removed. Undo puts it back.', 'ok', { label: 'Undo', run: bdUndo }); } }, '🔧 Remove this step'))) : null,
    probs.map(pb => bdProblem(pb, p)),
    h('div', { class: 'muted small', style: { marginTop: '6px' } }, 'Click the box to change it.')));
}
function fxStep(s, p, num) {
  const B = bdBlockOf(s), runs = bdRunsWords(s, B), k = BD_STEP[s.a] || { icon: '•', label: s.a };
  const cat = B ? 'block' : bdCat(s);
  const words = B ? B.name : s.a === 'engine' ? (s.words || 'A step') : s.a === 'stop' ? 'Stop here: nothing after this runs' : bdWords(s);
  const title = B ? 'Building block' : s.a === 'engine' ? (BD_CATS[cat] || [])[1] || 'A step' : k.label;
  const given = B ? Object.entries(B.inputs || {}) : [];
  const extra = B ? [B.about ? h('div', { class: 'fx-about' }, B.about) : null,
    given.length ? h('div', { class: 'bd-given' }, h('b', null, 'This flow gives it: '), given.map(([kk, v]) => bdPretty(kk) + ' = ' + (String(typeof v === 'string' ? v : JSON.stringify(v)).slice(0, 50))).join(' · ')) : null,
    B.steps.length ? h('button', { type: 'button', class: 'bd-toggle', onclick: e => { e.stopPropagation(); BD.open.has(p) ? BD.open.delete(p) : BD.open.add(p); BD.paintSide(); } },
      (BD.open.has(p) ? '▾ Hide' : '▸ Show') + ' its ' + B.steps.length + ' step' + (B.steps.length > 1 ? 's' : '') + ' · shared with ' + Math.max(0, (B.used_by || 0) - 1) + ' other flow' + ((B.used_by || 0) - 1 === 1 ? '' : 's')) : null] : null;
  const box = fxBox(p, s, { cat, title, icon: B ? '🧩' : k.icon, words, band: runs !== 'Always' ? runs : '', runs, extra, num });
  if (!B) return box;
  return h('div', { class: 'fx-block' }, box, BD.open.has(p) ? h('ol', { class: 'bd-inside' }, B.steps.map(x => h('li', { style: '--c:' + BD_CATS[BD_OPCAT[x.op] || (/^notify\./.test(x.op || '') ? 'message' : /^(db|case)\./.test(x.op || '') ? 'save' : 'info')][0] },
    x.when_words ? h('span', { class: 'bd-only' }, 'only when ' + x.when_words + ': ') : null, x.words))) : null);
}
function fxSeq(list, path, root) {
  const out = [];
  (list || []).forEach((s, i) => {
    const p = path + '.' + i;
    out.push(fxConn(path, i));
    if (bdIsOnly(s)) {   // "only if": one band, the steps inside run only when it is true
      out.push(h('div', { class: 'fx-only' + (BD.sel === p ? ' sel' : ''), id: 'fx-' + p },
        h('button', { type: 'button', class: 'fx-only-h', onclick: () => bdSelect(p) }, root ? h('span', { class: 'fx-num' }, i + 1) : null, '⚡ Only if ' + bdQ(s).replace(/\?$/, ''),
          BD.problems.some(x => x.path === p) ? h('span', { class: 'fx-warn' }, ' ⚠') : null),
        fxSeq(s.yes, p + '.yes', false)));
    } else if (s.a === 'if') {
      out.push(fxBox(p, s, { cat: 'decide', title: 'Check', icon: '🔀', words: bdQ(s), runs: 'Always', num: root ? i + 1 : null }), h('div', { class: 'fx-conn short' }),
        h('div', { class: 'fx-split' }, h('div', { class: 'fx-lane yes' }, h('div', { class: 'lh' }, '✓ Yes'), fxSeq(s.yes, p + '.yes', false), h('div', { class: 'fx-end' }, bdEnds(s.yes) ? '■ ends here' : '↓ then carries on')),
          h('div', { class: 'fx-lane no' }, h('div', { class: 'lh' }, '✗ Otherwise'), fxSeq(s.no, p + '.no', false), h('div', { class: 'fx-end' }, bdEnds(s.no) ? '■ ends here' : '↓ then carries on'))));
    } else out.push(fxStep(s, p, root ? i + 1 : null));
  });
  out.push(fxConn(path, (list || []).length));
  return out;
}
const bdEnds = l => (l || []).some(s => s.a === 'stop');
function bdFlowView() {
  const p = BD.plain, st = p.start || {}, fixed = st.type === 'block' || st.type === 'button';
  const asks = p.asks.map((a, i) => fxBox('asks.' + i, null, { cat: 'info', title: 'Ask a question', icon: '❓', words: a.q + (a.optional ? ' (they may skip it)' : ''),
    what: 'The chat bot asks this and keeps the answer as “' + a.label + '”.', extra: h('div', { class: 'fx-chips' }, h('span', { class: 'fx-chip give' }, '→ ' + a.label)) }));
  const chart = h('div', { class: 'fx' }, bdLegend(),
    h('div', { class: 'muted small', style: { margin: '-2px 0 10px' } }, 'Click a box to change it. Hover it to see what it does. The ＋ on a line adds a step there.'),
    h('div', { class: 'fx-flow' },
      fxBox('start', null, { cat: 'start', catWord: 'Start', title: 'When it starts', icon: '⚡', words: bdStartWords(st), what: 'What sets the flow off.' }),
      (p.before || []).length ? [h('div', { class: 'fx-conn short' }), h('div', { class: 'fx-group' }, h('div', { class: 'fx-gh' }, 'Checks before the questions'), fxSeq(p.before, 'before', false))] : null,
      fixed || p.report ? null : [h('div', { class: 'fx-conn short' }), h('div', { class: 'fx-group asks', id: 'fx-asks' }, h('div', { class: 'fx-gh' }, 'The chat bot asks'),
        asks.length ? asks.map((b, i) => [i ? h('div', { class: 'fx-conn short' }) : null, b]) : h('div', { class: 'muted small' }, 'No questions: it uses what it already knows.'),
        h('button', { type: 'button', class: 'bd-add', style: { marginTop: '8px' }, onclick: () => { bdChange(d => { d.asks.push({ label: 'New answer', q: 'Your question?', kind: 'text' }); }); bdSelect('asks.' + (BD.plain.asks.length - 1)); } }, '+ Add a question'))],
      p.report ? [h('div', { class: 'fx-conn short' }), fxBox('report', null, { cat: 'info', title: 'Looks up', icon: '🔎', words: p.report.words, what: 'A report: it answers one saved question.' }),
        h('div', { class: 'fx-conn short' }), fxBox('report', null, { cat: 'message', title: 'Replies', icon: '💬', words: p.report.format === 'list' ? 'With the list it found' : 'With what it found, written up by the AI' })]
        : fxSeq(p.steps, 'steps', true),
      h('div', { class: 'fx-done' }, '■ Done')));
  return h('div', { class: 'fx-wrap' + (BD.sel ? ' with-ed' : '') }, chart, BD.sel ? h('div', { class: 'fx-ed' }, bdEditor()) : null);
}

// ----- the editor beside the chart: everything about the box that was clicked -----
function bdEditor() {
  const p = BD.sel, close = h('button', { type: 'button', class: 'btn ghost sm', onclick: () => { BD.sel = null; BD.paintSide(); } }, '✕');
  const head = (cat, title, sub) => [h('div', { class: 'fx-ed-h' }, h('span', { class: 'bd-cat', style: '--c:' + (BD_CATS[cat] || ['#1e3a8a'])[0] }, (BD_CATS[cat] || [0, 'Start'])[1]), h('b', { class: 'grow' }, title), close), sub ? h('div', { class: 'muted small' }, sub) : null];
  if (p === 'start') return [head('start', 'When it starts', 'What sets the flow off.'), bdStartEdit()];
  if (p === 'report') return [head('info', 'A report', 'It answers one saved question.'), h('div', null, h('b', null, 'Looks up: '), BD.plain.report.words),
    h('div', { class: 'muted small' }, 'What it looks up is a saved question.' + (isSuper() ? ' Change it in the Advanced editor.' : ' A super admin changes it.')),
    isSuper() && BD.id ? h('button', { type: 'button', class: 'bd-pill', onclick: () => openAdvanced(BD.id) }, 'Open in the Advanced editor') : null];
  if (/^asks\.\d+$/.test(p)) { const i = +p.split('.')[1]; if (!BD.plain.asks[i]) { BD.sel = null; return null; } return [head('info', 'Ask a question', 'The chat bot asks this and keeps the answer.'), bdAskEdit(i)]; }
  const s = bdGet(BD.plain, p);
  if (!s) { BD.sel = null; return h('div', { class: 'muted' }, 'Click a box to change it.'); }
  const ks = p.split('.'), idx = +ks.pop(), lp = ks.join('.'), list = bdGet(BD.plain, lp) || [], B = bdBlockOf(s), inf = BD.info[p] || {};
  const k = BD_STEP[s.a] || {}, cat = B ? 'block' : bdCat(s), note = BD.notes.find(x => x.path === p);
  const parentOnly = /\.yes\.0$/.test(p) && bdIsOnly(bdGet(BD.plain, p.replace(/\.yes\.0$/, ''))) && bdGet(BD.plain, p.replace(/\.yes\.0$/, '')).yes.length === 1 ? p.replace(/\.yes\.0$/, '') : null;
  const acts = h('div', { class: 'bd-row' },
    h('button', { type: 'button', class: 'btn sm', disabled: !idx, onclick: () => { bdMove(p, -1); BD.sel = lp + '.' + (idx - 1); BD.paintSide(); } }, '↑'),
    h('button', { type: 'button', class: 'btn sm', disabled: idx >= list.length - 1, onclick: () => { bdMove(p, 1); BD.sel = lp + '.' + (idx + 1); BD.paintSide(); } }, '↓'),
    h('button', { type: 'button', class: 'btn sm', onclick: () => bdPick(lp, idx) }, '+ Add above'),
    h('button', { type: 'button', class: 'btn sm', onclick: () => bdPick(lp, idx + 1) }, '+ Add below'),
    h('button', { type: 'button', class: 'btn sm danger', onclick: () => { bdRemove(p); BD.sel = null; BD.paintSide(); toast('Removed. Undo puts it back.', 'ok', { label: 'Undo', run: bdUndo }); } }, '🗑 Delete'));
  const contract = (inf.needs || []).length || (inf.gives || []).length ? h('div', { class: 'bd-contract' },
    (inf.needs || []).length ? [h('span', { class: 'k' }, 'Uses'), inf.needs.map(x => h('span', { class: 'need ' + (x.ok ? 'ok' : 'bad') }, (x.ok ? '✓ ' : '✗ ') + x.n))] : null,
    (inf.gives || []).length ? [h('span', { class: 'k' }, 'Gives'), inf.gives.map(g => h('span', { class: 'give' }, g))] : null) : null;
  return [head(cat, B ? B.name : s.a === 'engine' ? 'A step kept from the Advanced editor' : s.a === 'if' && bdIsOnly(s) ? 'Only if…' : k.label, B ? 'A building block: shared steps.' : k.hint),
    acts, note ? h('div', { class: 'bd-prob warn' }, '⚠️ ' + note.text, h('div', { class: 'bd-row' }, h('button', { type: 'button', class: 'btn sm primary', onclick: () => { bdRemove(p); BD.sel = null; BD.paintSide(); } }, '🔧 Remove this step'))) : null,
    BD.problems.filter(x => x.path === p).map(pb => bdProblem(pb, p)),
    h('div', { class: 'fx-ed-b' }, bdBody(s, p)), contract,
    s.a === 'if' ? null : bdRunEdit(s, p, parentOnly),
    s.a === 'engine' && !B ? null : bdAskAI(p, s),
    h('label', { class: 'small muted', style: { display: 'block', marginTop: '10px' } }, h('input', { type: 'checkbox', checked: BD.tech, onchange: e => { BD.tech = e.target.checked; BD.paintSide(); } }), ' Show technical names'),
    BD.tech ? h('div', { class: 'bd-tech' }, JSON.stringify({ ...s, yes: undefined, no: undefined })) : null];
}
// "When does this step run?" Always, or only if something is true (an "only if" is a check with nothing otherwise)
function bdRunEdit(s, p, parentOnly) {
  if (s.a === 'engine') return h('div', { class: 'fx-run' }, h('b', null, '⚡ When it runs: '), s.when_words ? 'only when ' + s.when_words + ' (set in the Advanced editor).' : 'always.');
  const only = parentOnly ? bdGet(BD.plain, parentOnly) : null;
  return h('div', { class: 'fx-run' }, h('b', null, '⚡ When does this step run?'),
    h('div', { class: 'bd-row' },
      h('label', null, h('input', { type: 'radio', name: 'fxrun', checked: !only, onchange: () => { if (parentOnly) bdUnwrapOnly(parentOnly); } }), ' Always'),
      h('label', null, h('input', { type: 'radio', name: 'fxrun', checked: !!only, onchange: () => { if (!parentOnly) bdWrapOnly(p); } }), ' Only if…')),
    only ? bdTestsEdit(only, parentOnly) : h('div', { class: 'muted small' }, 'It runs every time the flow gets here.'));
}
function bdWrapOnly(p) {
  const known = (BD.info[p] || {}).known || [];
  bdChange(d => { const ks = p.split('.'), i = +ks.pop(), arr = bdGet(d, ks.join('.')); arr[i] = { a: 'if', match: 'all', tests: [{ q: known.filter(x => !['Name', 'Phone', 'Role', 'Flat'].includes(x)).pop() || 'Role', op: 'filled', value: '' }], yes: [arr[i]], no: [] }; });
  BD.sel = p + '.yes.0'; BD.paintSide();
}
function bdUnwrapOnly(ifPath) {
  bdChange(d => { const ks = ifPath.split('.'), i = +ks.pop(), arr = bdGet(d, ks.join('.')); arr.splice(i, 1, ...arr[i].yes); });
  BD.sel = ifPath; BD.paintSide();
}
function bdAskAI(p, s) {
  const ta = h('textarea', { rows: 2, placeholder: 'e.g. “also tell the committee” or “only if they say it is urgent”' });
  const send = () => { const t = ta.value.trim(); if (!t || BD.busy) return; BD.chat = true; BD.paint(); bdSend('Change only the step “' + (bdBlockOf(s) ? bdBlockOf(s).name : s.a === 'engine' ? s.words : bdWords(s)) + '” (at ' + p + '): ' + t); };
  return h('div', { class: 'bd-aibox', style: { marginTop: '10px' } }, h('b', null, '🤖 Ask the AI to change this step'), ta,
    h('div', { class: 'bd-row' }, h('button', { type: 'button', class: 'btn sm primary', onclick: send }, 'Ask'), h('span', { class: 'muted small' }, 'It shows what it changed; Undo puts it back.')));
}
// the fields of one step
function bdBody(s, p) {
  const inf = BD.info[p] || {}, known = inf.known || [], B = bdBlockOf(s);
  const at = (field, fn) => v => bdChange(d => fn(bdGet(d, p), v));
  const lists = Object.values(bdLists()), roles = (BD.ctx.roles || []).map(r => [r, r]);
  const msg = label => [h('div', { class: 'bd-flab' }, label), h('textarea', { class: 'bd-msgtxt', rows: 3, value: s.text || '', onchange: e => at('text', (x, v) => { x.text = v; })(e.target.value) }), bdChips(p, 'text', known)];
  if (s.a === 'say') return msg('What the chat bot replies');
  if (s.a === 'tell') return [h('div', { class: 'bd-sentence' }, h('b', null, 'Tell everyone who is'), bdSel(roles, s.role, at('role', (x, v) => { x.role = v; }))), msg('The message')];
  if (s.a === 'approve') return [h('div', { class: 'bd-sentence' }, h('b', null, 'Ask everyone who is'), bdSel(roles, s.role, at('role', (x, v) => { x.role = v; })), h('span', null, 'to approve')), msg('What they are asked')];
  if (s.a === 'set') return [h('div', { class: 'bd-sentence' }, h('b', null, 'Set'), bdInp(s.name, at('name', (x, v) => { x.name = v; }), { style: { width: '140px' } }), h('span', null, 'to'), bdInp(s.value, at('value', (x, v) => { x.value = v; }), { style: { flex: '1', minWidth: '140px' } })), bdChips(p, 'value', known)];
  if (s.a === 'stop') return [h('div', { class: 'muted small' }, 'Nothing after this runs. Put a “Reply to the person” just before it to tell them why.')];
  if (s.a === 'block') return [h('div', { class: 'bd-sentence' }, h('b', null, 'Use the building block'), bdSel(Object.entries(BD.ctx.blocks || {}).map(([kk, nm]) => [kk, nm]), s.key, at('key', (x, v) => { x.key = v; }))), B ? bdBlockBody(s, p, B).slice(1) : null];
  if (s.a === 'engine') return B ? bdBlockBody(s, p, B) : [h('div', { class: 'bd-sentence' }, h('b', null, s.words || 'A step')),
    h('div', { class: 'muted small' }, 'Kept exactly as it was made in the Advanced editor. You can move or remove it here' + (isSuper() ? '; its settings change in the Advanced editor.' : '.')),
    isSuper() && BD.id ? h('button', { type: 'button', class: 'bd-pill', onclick: () => openAdvanced(BD.id) }, 'Open in the Advanced editor') : null];
  if (s.a === 'if') return [bdTestsEdit(s, p), bdIsOnly(s) ? h('div', { class: 'bd-row', style: { marginTop: '8px' } },
      h('button', { type: 'button', class: 'btn sm', onclick: () => bdUnwrapOnly(p) }, 'Make the steps inside always run'),
      h('button', { type: 'button', class: 'btn sm', onclick: () => bdPick(p + '.no', 0) }, '+ Add what happens otherwise'))
    : h('div', { class: 'muted small' }, 'Add steps under “Yes” and “Otherwise” in the chart.')];
  if (s.a === 'find' || s.a === 'save') {
    const L = bdListOf(s.list), key = s.a === 'find' ? 'match' : 'values', vals = s[key] || {};
    const cols = L ? L.cols : Object.keys(vals);
    const rows = (s.a === 'save' ? cols : Object.keys(vals)).map(c => h('div', { class: 'bd-row' }, h('span', { class: 'bd-col' }, c),
      h('span', { class: 'muted small' }, s.a === 'find' ? 'is' : '←'), bdInp(vals[c], at(key, (x, v) => { x[key] = x[key] || {}; if (v === '' && s.a === 'save') delete x[key][c]; else x[key][c] = v; }), { placeholder: s.a === 'save' ? '(leave empty)' : 'a value or [Answer]', style: { flex: '1', minWidth: '120px' } }),
      bdSel([['', '+ value'], ...known.map(v => ['[' + v + ']', v])], '', v => { if (v) at(key, x => { x[key] = x[key] || {}; x[key][c] = v; })(v); }, { class: 'bd-pickval', 'aria-label': 'Put in a value' }),
      s.a === 'find' ? h('button', { type: 'button', class: 'bd-pill', onclick: () => bdChange(d => { delete bdGet(d, p).match[c]; }) }, '×') : null));
    const addCol = s.a === 'find' && L ? bdSel([['', '+ another column'], ...L.cols.filter(c => !(c in vals)).map(c => [c, c])], '', v => { if (v) bdChange(d => { const x = bdGet(d, p); x.match = { ...(x.match || {}), [v]: '' }; }); }) : null;
    return [h('div', { class: 'bd-sentence' }, h('b', null, s.a === 'find' ? 'Look in' : 'Save in'), bdSel(lists.map(t => [t.label, t.plural + (t.pending ? ' (new)' : '')]), s.list, at('list', (x, v) => { x.list = v; })),
      s.a === 'find' ? [h('span', null, 'and call it'), bdInp(s.name, at('name', (x, v) => { x.name = v; }), { style: { width: '130px' } }), h('span', { class: 'muted small' }, 'for rows where')] : h('span', { class: 'muted small' }, 'with')),
      h('div', { class: 'bd-map' }, rows, addCol)];
  }
  return null;
}
function bdTestsEdit(s, p) {
  const known = (BD.info[p] || {}).known || [], roles = (BD.ctx.roles || []).map(r => [r, r]);
  const tests = (s.tests || []).map((t, j) => {
    const ask = BD.plain.asks.find(a => a.label === t.q), yn = / found$/.test(t.q || '');
    const vals = yn ? [['yes', 'yes'], ['no', 'no']] : t.q === 'Approval' ? [['Approve', 'Approve'], ['Reject', 'Reject']] : t.q === 'Role' ? roles : ask && ask.kind === 'choice' ? (ask.options || []).map(o => [o, o]) : ask && ask.kind === 'yesno' ? [['Yes', 'Yes'], ['No', 'No']] : null;
    const val = ['empty', 'filled'].includes(t.op) ? null : vals && t.op !== 'oneof' ? bdSel([['', '…'], ...vals], t.value, v => bdChange(d => { bdGet(d, p).tests[j].value = v; })) : bdInp(t.value, v => bdChange(d => { bdGet(d, p).tests[j].value = v; }), { placeholder: t.op === 'oneof' ? 'A, B, C' : 'value' });
    return h('div', { class: 'bd-row' }, j ? h('span', { class: 'muted small' }, s.match === 'any' ? 'or' : 'and') : null,
      bdSel(known.map(v => [v, v]), t.q, v => bdChange(d => { bdGet(d, p).tests[j].q = v; })), bdSel(BD_OPS, t.op || 'is', v => bdChange(d => { bdGet(d, p).tests[j].op = v; })), val,
      (s.tests || []).length > 1 ? h('button', { type: 'button', class: 'bd-pill', onclick: () => bdChange(d => { bdGet(d, p).tests.splice(j, 1); }) }, '×') : null);
  });
  return h('div', null, h('div', { class: 'bd-sentence' }, h('b', null, 'Check:'), (s.tests || []).length > 1 ? ['if', bdSel([['all', 'all'], ['any', 'any']], s.match || 'all', v => bdChange(d => { bdGet(d, p).match = v; })), 'of these are true'] : 'if'),
    tests, h('button', { type: 'button', class: 'bd-pill', onclick: () => bdChange(d => { const x = bdGet(d, p); x.tests = [...(x.tests || []), { q: (x.tests[0] || {}).q || known[0], op: 'is', value: '' }]; }) }, '+ another check'),
    h('div', { class: 'muted small' }, 'Checked once, here. Nothing after it can move it to the other path.'));
}
function bdStartEdit() {
  const st = BD.plain.start || {};
  if (st.type === 'block' || st.type === 'button') return [h('b', null, bdStartWords(st)), st.type === 'block' ? h('div', { class: 'muted small' }, 'Changing it changes every flow that uses it.') : null];
  return h('div', { class: 'bd-sentence' }, h('span', null, 'Start when'),
    bdSel([['chat', 'someone writes to the chat bot'], ['time', 'it is time (a schedule)']], st.type || 'chat', v => bdChange(d => { d.start = v === 'time' ? { type: 'time', every: 'day', time: '09:00' } : { type: 'chat', words: '' }; })),
    st.type === 'time' ? [h('span', null, ': every'), bdSel([['day', 'day'], ['week', 'week'], ['month', 'month']], st.every || 'day', v => bdChange(d => { d.start.every = v; if (v === 'week') d.start.days = d.start.days || [0]; if (v === 'month') d.start.day_of_month = d.start.day_of_month || 1; })),
      st.every === 'week' ? h('span', { class: 'bd-days' }, BD_DAYS.map((dn, i) => h('label', { class: 'small' }, h('input', { type: 'checkbox', checked: (st.days || []).includes(i), onchange: e => bdChange(d => { const ss = new Set(d.start.days || []); e.target.checked ? ss.add(i) : ss.delete(i); d.start.days = [...ss].sort(); }) }), dn.slice(0, 3)))) : null,
      st.every === 'month' ? [h('span', null, 'on day'), bdSel(Array.from({ length: 28 }, (_, i) => [i + 1, String(i + 1)]), st.day_of_month || 1, v => bdChange(d => { d.start.day_of_month = +v; }))] : null,
      h('span', null, 'at'), h('input', { type: 'time', value: st.time || '09:00', onchange: e => bdChange(d => { d.start.time = e.target.value; }) })]
    : [h('span', null, ', with words like'), bdInp(st.words, v => bdChange(d => { d.start.words = v; delete d.start.phrases; }), { placeholder: 'book clubhouse, club house', style: { minWidth: '200px', flex: '1' } }),
       h('div', { class: 'muted small', style: { width: '100%' } }, 'Separate them with commas. Their name, phone, role and flat are known already.')]);
}
function bdAskEdit(i) {
  const a = BD.plain.asks[i], used = new Set();
  const scan = l => (l || []).forEach(s => { JSON.stringify(s).replace(/\[([^\[\]]+)\]/g, (m, k) => used.add(k)); (s.tests || []).forEach(t => used.add(t.q)); scan(s.yes); scan(s.no); });
  scan(BD.plain.before); scan(BD.plain.steps);
  return h('div', { class: 'stack' },
    h('label', { class: 'bd-flab' }, 'The question'), bdInp(a.q, v => bdChange(d => { d.asks[i].q = v; }), { 'aria-label': 'Question' }),
    h('label', { class: 'bd-flab' }, 'A short name for the answer (other steps use it)'), bdInp(a.label, v => bdChange(d => { const old = d.asks[i].label; d.asks[i].label = v; bdRename(d, old, v); }), { 'aria-label': 'Short name' }),
    h('div', { class: 'bd-row' }, bdSel(BD_KINDS, a.kind || 'text', v => bdChange(d => { d.asks[i].kind = v; })),
      h('label', { class: 'small' }, h('input', { type: 'checkbox', checked: !!a.optional, onchange: e => bdChange(d => { d.asks[i].optional = e.target.checked; }) }), ' they may skip it')),
    a.kind === 'choice' ? h('div', { class: 'bd-row' }, h('span', { class: 'small muted' }, 'Choices:'), bdInp((a.options || []).join(', '), v => bdChange(d => { d.asks[i].options = v.split(',').map(x => x.trim()).filter(Boolean); }), { style: { flex: '1' } })) : null,
    used.has(a.label) || JSON.stringify(BD.plain.steps).includes('"' + (a.key || bdLabelKey(a.label)) + '"') ? null : h('div', { class: 'muted small' }, 'No step uses this answer yet.'),
    h('div', { class: 'bd-row' }, h('button', { type: 'button', class: 'btn sm', disabled: !i, onclick: () => { bdChange(d => { [d.asks[i - 1], d.asks[i]] = [d.asks[i], d.asks[i - 1]]; }); BD.sel = 'asks.' + (i - 1); BD.paintSide(); } }, '↑'),
      h('button', { type: 'button', class: 'btn sm', disabled: i >= BD.plain.asks.length - 1, onclick: () => { bdChange(d => { [d.asks[i + 1], d.asks[i]] = [d.asks[i], d.asks[i + 1]]; }); BD.sel = 'asks.' + (i + 1); BD.paintSide(); } }, '↓'),
      h('button', { type: 'button', class: 'btn sm danger', onclick: () => { bdChange(d => { d.asks.splice(i, 1); }); BD.sel = null; BD.paintSide(); } }, '🗑 Remove the question')),
    BD.tech ? h('div', { class: 'bd-tech' }, '$fields.' + (a.key || bdLabelKey(a.label))) : null);
}

// ----- Try it: the real engine, as one of your people; nothing is saved and nobody is messaged -----
const BT = { as: null, msgs: [], btns: null, waiter: null, tok: 0, auto: false, running: false };
function bdTry() {
  const people = (BD.ctx.people || []);
  if (!BT.as && people.length) BT.as = (people.find(p => /owner|tenant|resident|member/i.test(p.role || '')) || people[0]).id;
  const box = h('div', { class: 'bt-msgs', id: 'bt-msgs' });
  const input = h('input', { type: 'text', placeholder: 'Type a message', 'aria-label': 'Message', onkeydown: e => { if (e.key === 'Enter' && input.value.trim()) { btAnswer(input.value.trim()); input.value = ''; } } });
  const phone = h('div', { class: 'bt' }, h('div', { class: 'bt-h' }, h('b', null, '📱 Try it'), h('span', { class: 'small' }, 'as'),
      bdSel(people.map(p => [p.id, p.name + (p.flat ? ' · ' + p.flat : '') + (p.role ? ' · ' + p.role : '')]), BT.as, v => { BT.as = v; btStart(); }, { 'aria-label': 'Try it as' }),
      h('span', { class: 'bd-sp' }), h('button', { type: 'button', onclick: () => { btStart(true); } }, '⚡ Sample answers'), h('button', { type: 'button', onclick: () => btStart() }, 'Restart')),
    box, h('div', { class: 'bt-in' }, input, h('button', { type: 'button', onclick: () => { if (input.value.trim()) { btAnswer(input.value.trim()); input.value = ''; } } }, '➤')),
    h('div', { class: 'muted small', style: { padding: '6px 10px' } }, 'The real engine runs, and your lists are really looked in. Nothing is saved and nobody is messaged.'));
  // a redraw of the screen keeps the chat; it starts again only when the flow or the person changed
  setTimeout(() => { if (!BT.running && BT.key !== JSON.stringify(BD.plain) + BT.as) btStart(); else btDraw(); }, 0);
  return phone;
}
const btSay = (c, t) => { BT.msgs.push({ c, t }); btDraw(); };
function btDraw() {
  const box = document.getElementById('bt-msgs'); if (!box) return;
  fill(box, BT.msgs.map(m => h('div', { class: 'bt-b ' + m.c }, m.t)), BT.btns ? h('div', { class: 'bt-btns' }, BT.btns.map(b => h('button', { type: 'button', onclick: () => btAnswer(b) }, b))) : null);
  box.scrollTop = box.scrollHeight;
}
function btAsk(btns, sample) {
  BT.btns = btns; btDraw();
  const t = BT.tok;
  if (BT.auto && sample != null) setTimeout(() => { if (t === BT.tok && BT.waiter) btAnswer(sample); }, 200);
  return new Promise(r => { BT.waiter = r; });
}
function btAnswer(text) { if (!BT.waiter) return; BT.msgs.push({ c: 'me', t: text }); const w = BT.waiter; BT.waiter = null; BT.btns = null; btDraw(); w(text); }
function btDates() {
  const d = new Date(), iso = x => x.toISOString().slice(0, 10), t = new Date(d); t.setDate(d.getDate() + 1);
  const sat = new Date(d); sat.setDate(d.getDate() + ((6 - d.getDay() + 7) % 7 || 7));
  return [iso(t), iso(sat)];
}
async function btStart(auto) {
  const tok = ++BT.tok; Object.assign(BT, { msgs: [], btns: null, waiter: null, auto: !!auto, running: true, key: JSON.stringify(BD.plain) + BT.as }); btDraw();
  const chk = () => { if (tok !== BT.tok) throw 'stale'; };
  const plain = JSON.parse(JSON.stringify(BD.plain)), st = plain.start || {};
  try {
    if (BD.problems.length || BD.pending.length) { btSay('sys', BD.pending.length ? 'Create the new lists first, then try it.' : 'Fix what is not ready first: ' + BD.problems[0].text); BT.running = false; return; }
    if (!BT.as) { btSay('sys', 'There is nobody to try it as yet. Add people first.'); BT.running = false; return; }
    if (st.type === 'time' || st.type === 'block' || st.type === 'button') { btSay('sys', bdStartWords(st) + '.'); await btAsk(['▶ Run it now (rehearsal)'], '▶ Run it now (rehearsal)'); chk(); }
    else { const w = String(st.words || 'hi').split(',')[0].trim() || 'hi'; btSay('sys', 'Write something like “' + w + '”, or press ⚡ Sample answers.'); await btAsk(null, w); chk(); btSay('bot', 'Sure, I can help with “' + (BD.name || 'this') + '”.'); }
    if ((plain.before || []).length) {
      const r = await api.post('/build/try', { plain, as_user: BT.as, part: 'before' }); chk();
      if (btShow(r, true)) { BT.running = false; return; }
    }
    const fields = {}, [d1, d2] = btDates();
    for (const a of plain.asks) {
      btSay('bot', a.q + (a.optional ? '\n(you can say skip)' : ''));
      const opts = a.kind === 'choice' ? (a.options || []) : a.kind === 'date' ? [d1, d2] : a.kind === 'time' ? ['10 am', '6 pm'] : a.kind === 'yesno' ? ['Yes', 'No'] : a.optional ? ['Skip'] : null;
      const sample = opts && opts.length ? opts[a.kind === 'time' ? 1 : 0] : a.kind === 'number' ? '2' : 'A sample answer';
      const v = await btAsk(opts, sample); chk();
      if (!/^skip$/i.test(v)) fields[a.label] = v;
    }
    btSay('sys', 'Running the flow…');
    const r = await api.post('/build/try', { plain, as_user: BT.as, fields, part: 'all', workflow_id: BD.id }); chk();
    BT.msgs.pop();
    btShow(r);
    if (r.status === 'preview') { BD.tried = JSON.stringify(BD.plain); bdKeep(); const top = document.querySelector('.bd-spine'); if (top) BD.paintSide(); }
  } catch (e) { if (e !== 'stale') btSay('sys', 'It could not be tried: ' + (e.message || e)); }
  BT.running = false;
}
function btShow(r, early) {           // true when the flow stopped; early: only the checks before the questions
  if (r.status === 'not_ready' || r.status === 'error') { btSay('sys', r.message || 'It stopped.'); return true; }
  (r.facts || []).forEach(f => {
    if (/^Reply: /.test(f)) btSay('bot', f.slice(7));
    else if (/^Would tell /.test(f)) btSay('other', f.replace(/^Would tell /, 'What ').replace(/^What ([^:]+): /, 'What $1 get:\n'));
    else if (/^would send the person the result/i.test(f)) btSay('sys', '📨 Would send them the confirmation');
    else btSay('sys', f.replace(/^Looked in ([a-z_]+):/, (m, t) => '🔎 Looked in ' + t.replace(/_/g, ' ') + ':').replace(/^would save: /, '🗂️ Would save: '));
  });
  if (r.stopped) { btSay('sys', '⛔ The flow stopped here.'); return true; }
  if (!early && r.status === 'preview' && !(r.facts || []).some(f => /^Reply: |send the person|would message|would tell/i.test(f))) btSay('sys', 'Done. (It did not say anything to the person.)');
  return false;
}
"""
