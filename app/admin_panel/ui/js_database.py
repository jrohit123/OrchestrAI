JS = r"""
// ───────────────────────── Data & schema → Your databases ─────────────────────────
// Every table of a database, with its columns and links, read live (GET /db/schema). Read-only.
const DBV = { source: 'org', q: '', open: new Set() };
async function renderDatabase(root) {
  const mine = S.renderId;
  let d;
  try { d = await api.get('/db/schema', { source: DBV.source }); } catch (e) { fill(root, errorBox(e)); return; }
  if (mine !== S.renderId) return;
  setTopAction(null);
  const list = h('div', { class: 'stack s8' });
  const stat = (n, label) => h('div', { class: 'card card-b dbstat' }, h('b', null, n == null ? '—' : n), h('span', { class: 'muted small' }, label));
  const drawList = () => {
    const q = DBV.q.toLowerCase();
    const shown = d.tables.filter(t => !q || t.name.includes(q) || t.columns.some(c => c.name.includes(q)));
    fill(list, h('div', { class: 'muted small' }, shown.length + ' of ' + d.tables.length + ' tables'),
      shown.map(t => {
        const open = DBV.open.has(t.name);
        return h('div', { class: 'card dbt' },
          h('button', { type: 'button', class: 'dbt-h', onclick: () => { open ? DBV.open.delete(t.name) : DBV.open.add(t.name); drawList(); } },
            h('b', null, t.name), h('span', { class: 'muted small' }, t.columns.length + ' columns' + (t.rows != null ? ' · about ' + t.rows.toLocaleString() + ' rows' : '')),
            t.links.length ? h('span', { class: 'muted small' }, '→ ' + [...new Set(t.links)].join(', ')) : null, h('span', { class: 'sp' }), icon(open ? 'chevd' : 'chevr', 'sm')),
          open ? h('table', { class: 'tbl dbcols' }, h('tr', null, h('th', null, 'Column'), h('th', null, 'Kind'), h('th', null, 'Can be empty'), h('th', null, 'Starts as')),
            t.columns.map(c => h('tr', null, h('td', null, h('code', null, c.name)), h('td', { class: 'small' }, c.type), h('td', { class: 'small' }, c.null ? 'yes' : 'no'), h('td', { class: 'small muted' }, c.default || '—')))) : null);
      }));
  };
  const search = h('input', { type: 'search', placeholder: 'Find a table or a column…', value: DBV.q, oninput: debounce(e => { DBV.q = e.target.value.trim(); drawList(); }, 150) });
  const pick = sel(d.sources.map(s => [s.key, s.label]), DBV.source, { 'aria-label': 'Which database' });
  pick.addEventListener('change', () => { DBV.source = pick.value; DBV.open.clear(); renderDatabase(root); });
  const hist = h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Changes made to it', h('span', { class: 'muted small' }, 'latest first')),
    h('div', { class: 'card-b stack s8' },
      d.changes.map(c => h('details', { class: 'dbhist' }, h('summary', null, badge(c.status === 'applied' ? 'Applied' : 'Failed', c.status === 'applied' ? 'ok' : 'bad'), ' ', c.summary, h('span', { class: 'muted small' }, ' · ' + fmtDT(c.created_at) + (c.by_label ? ' · ' + c.by_label : ''))),
        c.sql_up ? h('pre', { class: 'code' }, c.sql_up) : null, c.sql_down ? [h('div', { class: 'muted small' }, 'The way back'), h('pre', { class: 'code' }, c.sql_down)] : null)),
      d.migrations.length ? h('div', { class: 'stack s4' }, h('b', { class: 'small' }, 'Migrations (schema_migrations)'),
        d.migrations.slice(0, 25).map(m => h('div', { class: 'row small' }, h('code', null, m.version), h('span', { class: 'muted' }, fmtDT(m.applied_at) + ' · ' + (m.applied_by || ''))))) : null,
      !d.changes.length && !d.migrations.length ? h('div', { class: 'muted small' }, 'Nothing recorded yet.') : null));
  fill(root,
    h('div', { class: 'row', style: { marginBottom: '12px' } }, h('b', null, 'Database'), pick, h('span', { class: 'sp' }), h('a', { class: 'btn sm', href: href('schema', 'builder') }, icon('spark', 'sm'), 'Describe a change')),
    h('div', { class: 'dbstats' }, stat(d.stats.tables, 'tables'), stat(d.stats.workflows, 'flows'), stat(d.stats.roles, 'roles'), stat(d.stats.migrations, 'migrations')),
    h('div', { class: 'dbgrid' }, h('div', { class: 'stack s8' }, search, list), hist));
  drawList();
}

// ───────────────────────── Data & schema → AI change builder ─────────────────────────
// A client's need in plain words → how the AI reads it against the real database → a few questions → a plan in tabs
// (every tab can be edited) → checked against the live database and tried in a transaction that is rolled back →
// applied only by a super admin, after a backup, and written down. The AI only drafts (POST /db/builder/*).
const DBB = { chat: [], plan: null, tab: 'summary', check: null, steps: null };
const DBB_TABS = [['summary', 'Summary'], ['sql', 'Tables (SQL)'], ['workflows', 'Flows'], ['permissions', 'Who may use them'], ['seed', 'Starting rows'], ['rollback', 'Way back']];
const DBB_EXAMPLES = ['Facility booking with committee approval', 'Visitors approved by residents, checked in by the guard', 'Maintenance bills for every flat', 'A notice board for the society'];
function dbbSteps() {
  return DBB.steps || (DBB.steps = [['read', 'Read the database', 'Tables, roles, flows and steps'], ['draft', 'Draft the plan', 'SQL, flows, who may use them'], ['check', 'Check it against the live database', 'Every name, every rule'], ['try', 'Try it, then undo it', 'BEGIN; every statement; ROLLBACK'], ['backup', 'Backup', 'Taken before anything changes'], ['apply', 'Apply and write it down', 'One transaction, then the history']].map(s => ({ key: s[0], title: s[1], note: s[2], state: 'idle' })));
}
function dbbSet(key, state, note) { const s = dbbSteps().find(x => x.key === key); s.state = state; if (note != null) s.note = note; }
async function renderBuilder(root) {
  setTopAction(null);
  const log = h('div', { class: 'dbb-log' }), input = h('input', { type: 'text', placeholder: 'What does the client need? In plain words.' });
  const planBox = h('div', { class: 'card dbb-plan' }), pipeBox = h('div', { class: 'card dbb-pipe' });
  const say = (who, content, extra) => { const m = h('div', { class: 'dbb-msg ' + who }, content, extra || null); log.append(m); log.scrollTop = 1e6; return m; };
  const replay = () => { log.replaceChildren(); if (!DBB.chat.length) say('ai', 'Tell me what a client needs. I read your real tables, roles and flows first, reuse what fits, and draft only what is new. You check and change every part of the plan. Nothing is applied until a super admin applies it.'); DBB.chat.forEach(m => m.html ? log.append(m.html) : say(m.role === 'user' ? 'me' : 'ai', m.content)); };
  const reading = rd => h('table', { class: 'tbl dbb-read' }, h('tr', null, h('th', null, 'Needed'), h('th', null, 'How it fits'), h('th', null, '')), rd.map(r => h('tr', null, h('td', { class: 'small' }, r[0]), h('td', { class: 'small muted' }, r[1]), h('td', null, badge(r[2] === 'reuse' ? 'Reuse' : r[2] === 'engine' ? 'Engine' : 'New', r[2] === 'reuse' ? 'ok' : r[2] === 'engine' ? 'info' : 'warn')))));
  async function send(text) {
    text = (text || input.value).trim(); if (!text) return; input.value = '';
    DBB.chat.push({ role: 'user', content: text }); say('me', text);
    if (!DBB.plan) { dbbSet('read', 'run'); drawPipe(); }
    const wait = say('ai muted', 'Reading your database and thinking…');
    let r;
    try { r = await api.post('/db/builder/chat', { messages: DBB.chat.filter(m => m.content).map(m => ({ role: m.role, content: m.content })) }); }
    catch (e) { wait.remove(); say('ai', e.message); return; }
    wait.remove();
    dbbSet('read', 'ok');
    const parts = [];
    if (r.reading && r.reading.length) parts.push(h('div', null, h('b', { class: 'small' }, 'How I read it against your database'), reading(r.reading)));
    if (r.questions && r.questions.length) parts.push(...r.questions.map(q => h('div', { class: 'dbb-q' }, h('div', null, q.text), h('div', { class: 'row' }, q.options.map(o => h('button', { class: 'btn sm', type: 'button', onclick: () => send(q.text + ' → ' + o) }, o))))));
    const node = h('div', { class: 'dbb-msg ai' }, r.say || (r.plan ? 'The plan is ready.' : ''), parts);
    log.append(node); log.scrollTop = 1e6;
    DBB.chat.push({ role: 'assistant', content: JSON.stringify({ say: r.say, questions: r.questions, plan: r.plan ? '(the plan is in the tabs)' : null }), html: node });
    if (r.plan) {
      DBB.plan = r.plan; DBB.tab = 'summary'; DBB.check = null;
      dbbSet('draft', 'ok', 'Ready. Read it, change anything, then check it.'); ['check', 'try', 'backup', 'apply'].forEach(k => dbbSet(k, 'idle'));
      drawPlan(); drawPipe();
    }
  }
  function drawPlan() {
    const p = DBB.plan;
    if (!p) { fill(planBox, h('div', { class: 'card-h' }, 'The plan'), h('div', { class: 'card-b' }, empty('No plan yet', 'Describe a need on the left. After a few questions the plan appears here, and every part of it can be changed.'))); return; }
    const tabs = h('div', { class: 'tabs', style: { padding: '0 12px', margin: 0 } }, DBB_TABS.map(([k, l]) => {
      const n = DBB.check ? DBB.check.issues.filter(i => i.tab === k && i.level === 'error').length : 0;
      return h('button', { type: 'button', class: 'tab' + (DBB.tab === k ? ' active' : ''), onclick: () => { DBB.tab = k; drawPlan(); } }, l, n ? h('span', { class: 'badge bad' }, n) : null);
    }));
    let body;
    if (DBB.tab === 'summary') {
      const ul = (title, l) => l && l.length ? [h('b', { class: 'small' }, title), h('ul', { class: 'small', style: { margin: '4px 0 10px' } }, l.map(x => h('li', null, x)))] : null;
      const intro = h('textarea', { rows: 3, oninput: e => { p.intro = e.target.value; } }); intro.value = p.intro;
      body = h('div', { class: 'card-b stack s8' }, field('What you tell the client', intro), ul('New', p.new), ul('Reused from what you have', p.reuse), ul('Engine work still needed', p.engine), ul('Check before you trust it', p.notes));
    } else {
      const ta = h('textarea', { class: 'code dbb-code', spellcheck: false }); ta.value = p[DBB.tab] || '';
      ta.addEventListener('input', () => { p[DBB.tab] = ta.value; if (DBB.check) { DBB.check = null; ['check', 'try', 'backup', 'apply'].forEach(k => dbbSet(k, 'idle')); drawPipe(); } });
      body = h('div', { class: 'card-b' }, ta, h('div', { class: 'muted small', style: { marginTop: '6px' } }, 'Any change clears the last check, so nothing unchecked can be applied.'));
    }
    fill(planBox, h('div', { class: 'card-h' }, 'The plan', badge(DBB.check && DBB.check.ok ? 'Checked' : 'Draft', DBB.check && DBB.check.ok ? 'ok' : 'warn'), h('span', { class: 'sp' }), h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { DBB.plan = null; DBB.check = null; DBB.chat = []; DBB.steps = null; replay(); drawPlan(); drawPipe(); } }, 'Start again')), tabs, body);
  }
  function drawPipe() {
    const st = dbbSteps();
    const glyph = { idle: '', run: '…', ok: '✓', fail: '!' };
    const c = DBB.check;
    const backup = h('input', { type: 'checkbox' });
    const btnCheck = h('button', { class: 'btn', type: 'button', disabled: !DBB.plan, onclick: check }, 'Check the plan');
    const btnApply = h('button', { class: 'btn primary', type: 'button', disabled: !(c && c.ok), onclick: () => apply(backup.checked) }, 'Apply to the database');
    fill(pipeBox, h('div', { class: 'card-h' }, 'Pipeline', h('span', { class: 'sp' }), h('button', { class: 'btn sm ghost', type: 'button', onclick: showContext }, 'What the AI sees')),
      h('div', { class: 'card-b stack s8' },
        st.map((s, i) => h('div', { class: 'dbb-step ' + s.state }, h('span', { class: 'dbb-si' }, glyph[s.state] || i + 1), h('div', null, h('b', { class: 'small' }, s.title), h('div', { class: 'muted small' }, s.note)))),
        h('div', { class: 'row' }, btnCheck),
        c ? h('div', { class: 'stack s4' }, h('b', { class: 'small' }, c.issues.filter(i => i.level === 'error').length + ' problem(s), ' + c.issues.filter(i => i.level === 'warn').length + ' warning(s)'),
          c.issues.map(i => h('div', { class: 'dbb-issue ' + i.level, onclick: () => { DBB.tab = i.tab; drawPlan(); } }, h('b', null, i.level === 'error' ? 'Problem' : 'Check'), ' ', i.msg)),
          c.ran.length ? h('details', null, h('summary', { class: 'muted small' }, c.ran.length + ' statement(s) ran, then were undone'), c.ran.map(x => h('div', { class: 'small' }, h('code', null, x)))) : null) : null,
        c && c.ok ? h('div', { class: 'stack s8' }, h('label', { class: 'row small' }, backup, 'A backup of this database was taken today'), btnApply,
          h('div', { class: 'muted small' }, 'Applying adds only. The flows it makes start switched off and reach nobody until you check them.')) : null));
  }
  async function check() {
    dbbSet('check', 'run'); dbbSet('try', 'idle'); drawPipe();
    let r;
    try { r = await api.post('/db/builder/validate', planBody()); } catch (e) { dbbSet('check', 'fail', e.message); drawPipe(); return; }
    DBB.check = r;
    const errs = r.issues.filter(i => i.level === 'error').length;
    dbbSet('check', errs && !r.tried ? 'fail' : 'ok', errs && !r.tried ? errs + ' problem(s): fix them in the plan' : 'Passed' + (r.issues.length ? ' with ' + r.issues.length + ' note(s)' : ''));
    dbbSet('try', r.tried ? (r.ok ? 'ok' : 'fail') : 'idle', r.tried ? (r.ok ? r.ran.length + ' statement(s) ran, then all were undone' : 'The database refused a statement') : 'Waits for the check to pass');
    drawPlan(); drawPipe();
  }
  async function apply(backupTaken) {
    if (!backupTaken) { toast('Take a backup of this database first, then tick the box.', 'bad'); return; }
    if (!await confirmBox('Apply this change to ' + S.boot.org.name + '’s database now? It only adds, and it is written down with its way back.', { ok: 'Apply' })) return;
    dbbSet('backup', 'ok', 'Confirmed by ' + (S.boot.me.name || 'you')); dbbSet('apply', 'run'); drawPipe();
    try {
      const r = await api.post('/db/builder/apply', { ...planBody(), fingerprint: DBB.check.fingerprint, backup_taken: true });
      dbbSet('apply', 'ok', 'Applied as ' + r.version + (r.flows.length ? '; flows made (switched off): ' + r.flows.join(', ') : ''));
      if (r.flow_problems.length) toast('Applied. Some flows were not made: ' + r.flow_problems.join('; '), 'bad'); else toast('Applied and written down', 'ok');
      S.lookups = null;
    } catch (e) { dbbSet('apply', 'fail', e.message); }
    drawPipe();
  }
  function planBody() { const p = DBB.plan; return { sql: p.sql || '', seed: p.seed || '', rollback: p.rollback || '', workflows: p.workflows || '[]', permissions: p.permissions || '{}', summary: p.intro || '' }; }
  async function showContext() {
    let t; try { t = (await api.get('/db/builder/context')).text; } catch (e) { toast(e.message, 'bad'); return; }
    modal({ title: 'What the AI sees', wide: true, body: h('div', null, h('div', { class: 'muted small', style: { marginBottom: '8px' } }, 'This is everything the AI is told about this database before it drafts. It never sees any record.'), h('pre', { class: 'code', style: { maxHeight: '60vh' } }, t)), actions: [{ label: 'Close' }] });
  }
  input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
  fill(root, h('div', { class: 'dbb' },
    h('div', { class: 'card dbb-chat' }, h('div', { class: 'card-h' }, '1 · The need'), log,
      h('div', { class: 'row dbb-ex' }, DBB_EXAMPLES.map(x => h('button', { class: 'btn sm ghost', type: 'button', onclick: () => send(x) }, x))),
      h('div', { class: 'row dbb-in' }, input, h('button', { class: 'btn primary', type: 'button', onclick: () => send() }, 'Send'))),
    planBox, pipeBox));
  replay(); drawPlan(); drawPipe();
}
"""
