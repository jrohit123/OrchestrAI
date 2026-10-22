JS = r"""
// ───────────────────────── Build with AI: chat on the left, the flow as a simple chart on the right ─────────────────────────
// #/workflows?build=new (or =<id>). The plain flow (questions and steps in words) is what the AI edits and the chart
// draws; saving turns it into engine steps on the server (build.py, flow_plain.py).
const BD = { id: null, version: null, name: '', plain: null, history: [], log: [], pending: [], problems: [], ctx: null, busy: false, dirty: false };
const BD_EMPTY = () => ({ start: { type: 'chat', words: '' }, asks: [], steps: [] });
const bdKeep = () => { try { sessionStorage.setItem('build:' + (BD.id || 'new'), JSON.stringify({ name: BD.name, plain: BD.plain, history: BD.history, log: BD.log, pending: BD.pending })); } catch (e) {} };

SECTIONS.build = {
  title: 'Build with AI', sub: 'Make a flow by chatting with the AI. It asks you the choices, makes the lists it needs and shows the flow as a simple chart.',
  async render(root, route) {
    S.leaveGuard = null; window.onbeforeunload = null;
    if (route.q.f) return renderBuild(root, route);
    setTopAction({ label: 'New flow', icon: 'spark', run: () => go('build', '', { f: 'new' }) });
    const d = await api.get('/build');
    if (!d.rows.length) { fill(root, h('div', { class: 'card' }, h('div', { class: 'card-b stack' }, h('b', null, 'No flows made here yet.'), h('div', { class: 'muted' }, 'Press New flow and tell the AI what the chat bot should do, for example “residents should be able to book the clubhouse”.'), h('div', null, h('button', { class: 'btn primary', type: 'button', onclick: () => go('build', '', { f: 'new' }) }, 'New flow'))))); return; }
    fill(root, h('div', { class: 'bd-cards' }, d.rows.map(w => h('a', { class: 'card bd-card', href: href('build', '', { f: w.id }) },
      h('b', null, w.name), h('div', { class: 'muted small' }, (w.start && w.start.type === 'time' ? 'Runs by itself' : 'When someone writes' + (w.start && w.start.words ? ' “' + String(w.start.words).split(',')[0].trim() + '”' : ''))),
      h('div', null, badge(w.is_active ? 'On' : 'Off', w.is_active ? 'ok' : ''))))));
  },
};

async function renderBuild(root, r) {
  const mine = S.renderId;
  Object.assign(BD, { id: r.q.f === 'new' ? null : r.q.f, version: null, name: '', plain: BD_EMPTY(), history: [], log: [], pending: [], problems: [], busy: false, dirty: false });
  BD.ctx = await api.get('/build/context');
  if (BD.id) {
    const f = await api.get('/build/' + BD.id);
    Object.assign(BD, { name: f.name, version: f.version, plain: f.plain });
  }
  try {
    const kept = JSON.parse(sessionStorage.getItem('build:' + (BD.id || 'new')) || 'null');
    if (kept && (!BD.id || kept.plain)) Object.assign(BD, kept, { dirty: !!BD.id && JSON.stringify(kept.plain) !== JSON.stringify(BD.plain) });
  } catch (e) {}
  if (mine !== S.renderId) return;
  const crumb = document.getElementById('crumbname'); if (crumb) crumb.textContent = BD.name || 'Build with AI';
  S.leaveGuard = () => !BD.dirty || confirm('Leave without saving? The changes since the last save are lost.');
  const chatBox = h('div', { class: 'bd-chat' }), side = h('div', { class: 'bd-side' });
  fill(root, h('div', { class: 'bd' }, bdTop(), h('div', { class: 'bd-grid' }, chatBox, side)));
  BD.paint = () => { bdChat(chatBox); bdSide(side); bdKeep(); };
  BD.paint();
}

function bdTop() {
  const name = h('input', { type: 'text', class: 'bd-name', value: BD.name, placeholder: 'Name of the flow', 'aria-label': 'Name of the flow',
    oninput: e => { BD.name = e.target.value; BD.dirty = true; bdKeep(); } });
  const saveBtn = h('button', { class: 'btn primary', type: 'button', id: 'bd-save', onclick: bdSave }, 'Save');
  return h('div', { class: 'bd-top' }, h('a', { class: 'btn ghost sm', href: href('build') }, '← All'), name, h('span', { class: 'bd-sp' }), saveBtn);
}

function bdChat(box) {
  const say = t => bdSend(t);
  const log = BD.log.length ? BD.log.map((m, i) => m.who === 'you' ? h('div', { class: 'bd-msg you' }, m.text) :
    h('div', { class: 'bd-msg ai' + (m.warn ? ' warn' : '') }, m.text,
      m.changes && m.changes.length ? h('ul', null, m.changes.map(c => h('li', null, c))) : null,
      m.questions && m.questions.length ? h('div', { class: 'bd-qs' }, m.questions.map(q => h('div', { class: 'bd-q' }, h('div', null, q.text),
        q.options && q.options.length && i === BD.log.length - 1 ? h('div', { class: 'bd-opts' }, q.options.map((o, k) => h('button', { type: 'button', class: 'btn sm' + (k === 0 ? ' primary' : ''), onclick: () => say(o) }, o))) : null))) : null))
    : [h('div', { class: 'bd-hello' }, h('b', null, 'Tell the AI what this flow should do.'), h('div', { class: 'muted' }, 'One thing at a time, like a WhatsApp message. It asks you when there is a choice to make, and draws the flow on the right.'),
       h('div', { class: 'bd-opts' }, ['Residents should be able to book the clubhouse', 'Visitors: a resident tells security who is coming', 'Every month remind flats with unpaid dues'].map(e => h('button', { type: 'button', class: 'btn sm', onclick: () => say(e) }, e))))];
  const input = h('textarea', { rows: 2, placeholder: BD.log.length ? 'Your next message' : 'For example: residents should be able to book the clubhouse for functions', disabled: BD.busy,
    onkeydown: e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go_(); } } });
  const go_ = () => { const t = input.value.trim(); if (t && !BD.busy) say(t); };
  const list = h('div', { class: 'bd-log' }, log, BD.busy ? h('div', { class: 'bd-msg ai muted' }, 'Thinking…') : null);
  fill(box, list, h('div', { class: 'bd-in' }, input, h('button', { class: 'btn primary', type: 'button', disabled: BD.busy, onclick: go_ }, BD.busy ? '…' : 'Send')));
  list.scrollTop = list.scrollHeight;
  if (!BD.busy) setTimeout(() => input.focus(), 0);
}

async function bdSend(text) {
  BD.log.push({ who: 'you', text }); BD.busy = true; BD.paint();
  try {
    const r = await api.post('/build/chat', { message: text, history: BD.history.slice(-12), flow: BD.plain, pending_lists: BD.pending });
    BD.history.push({ role: 'user', content: text }, { role: 'assistant', content: [r.reply, ...(r.questions || []).map(q => q.text)].filter(Boolean).join('\n') });
    if (r.flow) { BD.plain = r.flow; BD.dirty = true; }
    BD.pending = r.new_lists || [];
    BD.problems = r.problems || [];
    BD.log.push({ who: 'ai', text: r.reply || (r.flow ? 'Done.' : 'Nothing changed.'), changes: r.changes, questions: r.questions, warn: (r.questions || []).length > 0 || BD.problems.length > 0 });
    if (!BD.name && r.flow) BD.name = text.length > 60 ? text.slice(0, 58) + '…' : text.charAt(0).toUpperCase() + text.slice(1);
  } catch (e) { BD.log.push({ who: 'ai', text: 'The AI could not answer: ' + e.message, warn: true }); }
  BD.busy = false; BD.paint();
  const nm = document.querySelector('.bd-name'); if (nm && !nm.value && BD.name) nm.value = BD.name;
}

// ----- the right side: new lists to create, the chart, what does not fit yet -----
function bdSide(box) {
  const lists = BD.pending.map((op, i) => h('div', { class: 'bd-list' },
    h('div', null, h('b', null, 'New list: ' + (op.plural || op.label)), op.about ? h('div', { class: 'muted small' }, op.about) : null,
      h('div', { class: 'small' }, (op.fields || []).map(f => f.label + (f.kind === 'choice' && f.options ? ' (' + f.options.join(', ') + ')' : f.kind && f.kind !== 'text' ? ' (' + f.kind + ')' : '')).join(' · '))),
    h('button', { class: 'btn sm primary', type: 'button', onclick: async e => {
      e.target.disabled = true;
      try {
        await api.post('/schema/apply', { ops: [op] });
        BD.pending.splice(i, 1); BD.ctx = await api.get('/build/context');
        toast('Created the list ' + (op.plural || op.label) + '.', 'ok'); BD.paint();
      } catch (x) { toast(x.message, 'bad'); e.target.disabled = false; }
    } }, 'Create it')));
  const problems = BD.problems.length ? h('div', { class: 'bd-probs' }, h('b', null, 'Not ready yet'), h('ul', null, BD.problems.map(p => h('li', null, p.text))), h('div', { class: 'muted small' }, 'Tell the AI how to fix it' + (BD.problems[0].path && BD.problems[0].need ? ', for example: ask for ' + BD.problems[0].need : ', in your own words') + '.')) : null;
  fill(box, lists.length ? h('div', { class: 'bd-lists' }, h('div', { class: 'muted small' }, 'The flow needs these lists. Create them to save the flow.'), lists) : null, problems, bdChart(BD.plain));
  const btn = document.getElementById('bd-save');
  if (btn) {
    const why = !BD.plain.steps.length && !(BD.plain.before || []).length ? 'Nothing to save yet' : BD.pending.length ? 'Create the new lists first' : BD.problems.length ? 'Fix what is not ready first' : '';
    btn.disabled = !!why || BD.busy; btn.title = why;
  }
}

// ----- the simple chart: one plain line per box, checks as Yes / No side by side -----
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
  return ({ say: 'Reply to them: “' + (s.text || '').slice(0, 70) + ((s.text || '').length > 70 ? '…' : '') + '”', tell: 'Tell ' + (s.role || '?'), set: (s.name || '?') + ' = ' + (s.value || ''),
    _ask: 'Ask: ' + BD.plain.asks.map(a => a.label).join(', '), find: 'Look in ' + (s.list || '?'), save: 'Save in ' + (s.list || '?'), approve: 'Ask ' + (s.role || '?') + ' to approve', block: 'Run “' + (blocks[s.key] || s.key) + '”' })[s.a] || s.a;
}
function bdChart(plain) {
  const A = () => h('div', { class: 'ch-arrow' }, '↓');
  const box = (t, cls) => h('div', { class: 'ch-box' + (cls ? ' ' + cls : '') }, t);
  const ends = l => l && l.length && l[l.length - 1].a === 'stop';
  const lane = (label, cls, kids) => h('div', { class: 'ch-lane' }, h('span', { class: cls }, label), kids);
  const seq = (arr, end) => {
    const out = [];
    for (let i = 0; i < (arr || []).length; i++) {
      const s = arr[i], rest = arr.slice(i + 1);
      if (s.a === 'if') {
        const ys = ends(s.yes), ns = ends(s.no);
        out.push(A(), h('div', { class: 'ch-q' }, bdQ(s)));
        if (ys !== ns) { out.push(h('div', { class: 'ch-split' }, lane('Yes', 'ch-yes', seq(ys ? s.yes : (s.yes || []).concat(rest), !ys && end)), lane('No', 'ch-no', seq(ns ? s.no : (s.no || []).concat(rest), !ns && end)))); return out; }
        out.push(h('div', { class: 'ch-split' }, lane('Yes', 'ch-yes', seq(s.yes, false).length ? seq(s.yes, false) : h('div', { class: 'ch-join' }, 'nothing extra')),
          lane('No', 'ch-no', seq(s.no, false).length ? seq(s.no, false) : h('div', { class: 'ch-join' }, 'nothing extra'))), h('div', { class: 'ch-join' }, 'then both go on'));
        continue;
      }
      if (s.a === 'approve') { out.push(A(), h('div', { class: 'ch-q' }, bdWords(s) + ': approved?'), h('div', { class: 'ch-split' }, lane('Yes', 'ch-yes', seq(rest, end)), lane('No', 'ch-no', [A(), box('End', 'ch-end')]))); return out; }
      if (s.a === 'stop') { out.push(A(), box('End', 'ch-end')); return out; }
      out.push(A(), box(bdWords(s)));
    }
    if (end) out.push(A(), box('Done', 'ch-end'));
    return out;
  };
  const st = plain.start || {};
  const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const when = st.every === 'week' && (st.days || []).length ? ' on ' + st.days.map(d => DAYS[d] || d).join(', ') : st.every === 'month' && st.day_of_month ? ' on day ' + st.day_of_month : '';
  const startText = st.type === 'time' ? 'By itself, every ' + (st.every || 'day') + when + (st.time ? ' at ' + st.time : '') : 'When someone writes' + (st.words ? ' “' + String(st.words).split(',')[0].trim() + '”' : '');
  if (!plain.asks.length && !plain.steps.length && !(plain.before || []).length) return h('div', { class: 'chart' }, h('div', { class: 'ch-title' }, 'Your flow will appear here'), h('div', { class: 'muted' }, 'Start by telling the AI what it should do.'));
  // the checks before the questions, then the questions, then the steps: one sequence, so a stop on one side
  // of an early check carries the questions and the rest into the other side
  const all = [...(plain.before || []), ...(plain.asks.length ? [{ a: '_ask' }] : []), ...plain.steps];
  return h('div', { class: 'chart' }, h('div', { class: 'ch-title' }, 'Your flow at a glance'), box('▶ ' + startText, 'ch-start'), seq(all, true));
}

async function bdSave() {
  if (!BD.name.trim() || BD.name.trim().length < 2) { toast('Give the flow a name first.', 'bad'); document.querySelector('.bd-name').focus(); return; }
  const btn = document.getElementById('bd-save'); btn.disabled = true;
  try {
    const r = await api.post('/build/save', { name: BD.name.trim(), plain: BD.plain, workflow_id: BD.id, base_version: BD.version });
    const first = !BD.id;
    try { sessionStorage.removeItem('build:' + (BD.id || 'new')); } catch (e) {}
    BD.id = r.id; BD.version = r.version; BD.dirty = false; bdKeep();
    history.replaceState(null, '', href('build', '', { f: r.id }));
    const next = isSuper() ? 'It is switched off until you switch it on and choose who can use it.' : 'A super admin switches it on and chooses who can use it.';
    toast(first ? 'Saved. ' + next : 'Saved.', 'ok', isSuper() ? { label: 'Who can use it', run: () => openWorkflow(r.id) } : undefined);
  } catch (x) { toast(x.message, 'bad'); }
  BD.paint();
}
"""
