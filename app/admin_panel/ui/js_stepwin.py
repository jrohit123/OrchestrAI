JS = r"""
// ───────────────────────── the step window: what comes in, the settings, what goes out ─────────────────────────
// It opens over the canvas for one step (double-click a box, press Enter, or Open on the bar above a box).
// The middle is the same form as the side panel, so there is one set of forms and one set of rules.
// "Test this step" rehearses the flow up to that step: whatever only looks things up runs for real, and
// whatever would save or send is only described (the same rehearsal as Try it). Nothing here knows what a
// step means: the words and the settings come from the step catalogue and from the rehearsal.
let SW = null;                                         // the window that is open
let swClosedAt = 0;                                    // when it last closed: the Escape that closed it must not also clear the chosen step

const swTry = () => (CV.try = CV.try || { people: null, as: '', fields: {} });
const swIdx = () => (SW ? idxOf(SW.id) : -1);
const swStep = () => EW.work.steps[swIdx()];
const swSig = i => JSON.stringify([tidySteps(EW.work.steps.slice(0, i + 1)).map(s => ({ op: s.op, params: s.params, when: s.when })), swTry().fields, swTry().as]);

function swOpen(id, o) {
  o = o || {};
  if (isRead()) { toast('This workflow answers with a saved report, so it has no steps to open.'); return; }
  if (idxOf(id) < 0) { toast('Only a step that is in the flow has a window.'); return; }
  if (SW) swClose(true);
  CV.sel = new Set([id]); renderNodes(); renderInspector();
  const scrim = h('div', { class: 'scrim top', onclick: () => swClose() });
  const el = h('div', { class: 'sw', role: 'dialog', 'aria-label': 'Step window' });
  const closer = () => swClose();
  SW = { id, tab: 'set', view: 'table', busy: false, test: null, more: {}, rename: false, el, scrim, closer };
  modalStack.push(closer);
  document.body.append(scrim, el);
  swLoadPeople();
  swDraw();
  if (o.test) swTest();
}
function swClose(quiet) {
  if (!SW) return;
  const { el, scrim, closer } = SW;
  SW = null; swClosedAt = Date.now();
  el.remove(); scrim.remove();
  const k = modalStack.indexOf(closer); if (k >= 0) modalStack.splice(k, 1);
  if (!quiet && EW && CV && CV.el && CV.el.isConnected) { renderNodes(); renderInspector(); }
}
window.addEventListener('hashchange', () => { if (SW) swClose(true); });
function swRefresh() { if (SW) swDraw(); }

function swLoadPeople() {
  const T = swTry();
  if (T.people || T.loading) return;
  T.loading = true;
  api.get('/studio/people').then(r => { T.people = r.people; if (!T.as && r.people.length) T.as = r.people[0].id; })
    .catch(e => { T.people = []; toast(e.message, 'bad'); })
    .finally(() => { T.loading = false; swRefresh(); });
}

// ----- drawing the window -----
function swDraw() {
  if (!SW) return;
  if (!EW || !CV || !CV.el || !CV.el.isConnected) { swClose(true); return; }
  const i = swIdx();
  if (i < 0) { swClose(); return; }
  const s = EW.work.steps[i], keep = ['.sw-pl', '.sw-pm', '.sw-pr'].map(q => { const e = SW.el.querySelector(q); return e ? e.scrollTop : 0; });
  fill(SW.el, swHead(s, i), h('div', { class: 'sw-b' }, swIn(s, i), swMid(s, i), swOut(s, i)), swFoot(i));
  ['.sw-pl', '.sw-pm', '.sw-pr'].forEach((q, n) => { const e = SW.el.querySelector(q); if (e) e.scrollTop = keep[n]; });
}
function swSetName(v) {
  const s = swStep(); if (!s) return;
  v = v.trim();
  if (v) s.name = v; else delete s.name;
  SW.rename = false; commit(false); swDraw();
}
function swHead(s, i) {
  const spec = catalogSpec(s.op), blk = s.op === 'run_workflow', key = cvKey(s);
  const kicker = (blk ? 'Building block' : (spec ? spec.group : 'Step')) + ' · step ' + (i + 1);
  const name = SW.rename
    ? h('input', { class: 'sw-nm', type: 'text', value: s.name || '', placeholder: describeStep(s), 'aria-label': 'Name of this step',
        onkeydown: e => { if (e.key === 'Enter') e.target.blur(); else if (e.key === 'Escape') { e.stopPropagation(); SW.rename = false; swDraw(); } },
        onblur: e => { if (SW && SW.rename) swSetName(e.target.value); } })
    : h('button', { class: 'sw-t', type: 'button', title: 'Rename this step', onclick: () => { SW.rename = true; swDraw(); const inp = SW.el.querySelector('.sw-nm'); if (inp) { inp.focus(); inp.select(); } } },
        h('span', null, s.name || describeStep(s)), icon('edit', 'xs'));
  return h('div', { class: 'sw-h k-' + key },
    h('span', { class: 'gi' }, icon(cvIcon(s.op))),
    h('div', { class: 'grow' }, h('div', { class: 'kicker' }, kicker), name, h('div', { class: 'muted small sw-sub' }, s.name ? describeStep(s) : (spec ? spec.help : ''))),
    h('button', { class: 'btn primary', type: 'button', disabled: SW.busy, onclick: swTest }, icon('play', 'sm'), SW.busy ? 'Testing…' : (SW.test ? 'Test again' : 'Test this step')),
    h('button', { class: 'btn ghost icon', type: 'button', 'aria-label': 'Close', onclick: () => swClose() }, icon('x')));
}

// ----- left: what comes in -----
// what a value would be in the test that was run (nothing until there has been one)
function swSample(path, i) {
  const tst = SW.test;
  if (!tst || tst.err) return undefined;
  const T = swTry(), parts = String(path).replace(/^\$/, '').split('.'), root = parts[0], steps = EW.work.steps;
  const dataOf = j => (tst.lines[j] && tst.lines[j].data) || null;
  if (root === 'fields') {
    const k = parts[1], typed = T.fields[k];
    if (typed !== undefined && String(typed).trim() !== '') return String(typed).trim();
    for (let j = i - 1; j >= 0; j--) {
      const p = steps[j].params || {}, d = dataOf(j);
      if (!d) continue;
      if (steps[j].op === 'derive_field' && p.field === k) return d[k];
      if (steps[j].op === 'resolve_entity' && p.expose && p.expose[k]) return d[p.expose[k]];
    }
    return undefined;
  }
  if (root === 'user') {
    const who = (T.people || []).find(x => x.id === T.as);
    if (!who) return undefined;
    return parts[1] === 'name' ? who.name : parts[1] === 'role' ? who.role : parts[1] === 'user_id' ? String(who.id).slice(0, 8) + '…' : '(hidden)';
  }
  if (root === 'inserted') {
    for (let j = i - 1; j >= 0; j--) {
      if (steps[j].op === 'db.insert_row' && (steps[j].params || {}).table === parts[1]) { const d = dataOf(j); return parts[2] === 'id' ? '(new)' : (d ? d[parts[2]] : undefined); }
    }
    return undefined;
  }
  for (let j = i - 1; j >= 0; j--) {                                   // a record an earlier step found
    const p = steps[j].params || {};
    const into = steps[j].op === 'resolve_entity' ? (p.into || String(p.table || '').replace(/s$/, '')) : steps[j].op === 'case.categorize' ? (p.into || 'category') : steps[j].op === 'case.route' ? (p.into || 'route') : null;
    if (into === root) { const d = dataOf(j); return d ? d[parts[1]] : undefined; }
  }
  return undefined;
}
// a click on a value on the left puts it into the field that was last clicked
function swUse(path) {
  const t = FOCUSED_VALUE;
  if (!t || !t.el.isConnected) { toast('Click the field first, then pick a value on the left.'); return; }
  t.take(path);
}
function swPills(title, opts, i) {
  const folded = opts.length > 7 && !SW.more[title], shown = folded ? opts.slice(0, 6) : opts;
  return h('div', { class: 'sw-grp' }, h('div', { class: 'sw-gt' }, title),
    shown.map(([path, label]) => {
      const v = swSample(path, i);
      return h('button', { class: 'sw-dp', type: 'button', title: 'Put “' + label + '” in the field you clicked', onclick: () => swUse(path) },
        h('span', null, label), v !== undefined && v !== null && v !== '' ? h('small', null, String(v)) : null);
    }),
    folded ? h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { SW.more[title] = true; swDraw(); } }, 'Show ' + (opts.length - 6) + ' more') : null);
}
function swIn(s, i) {
  const T = swTry(), groups = valueOptions(envBefore(i)).filter(g => g[0] !== 'Other');
  const asked = Object.entries(EW.work.entity_schema || {}).filter(([, f]) => f && typeof f === 'object' && !f.computed);
  const who = T.people && T.people.length ? sel(T.people.map(p => [p.id, p.name + ' (' + p.role + ')']), T.as || T.people[0].id, { onchange: e => { T.as = e.target.value; } }) : null;
  if (who && !T.as) T.as = who.value;
  const testWith = h('details', { class: 'sw-tw', open: !SW.test },
    h('summary', null, 'Test with'),
    h('div', { class: 'stack s8' },
      T.people ? (who ? field('As', who) : notice('No one is linked to the chat yet, so there is no one to test as.', 'bad')) : h('span', { class: 'muted small' }, 'Loading people…'),
      asked.map(([k, f]) => field((f.label || pretty(k)) + (f.required ? ' *' : ''),
        Array.isArray(f.enum) && f.enum.length
          ? sel([['', 'Choose…'], ...f.enum.map(x => [x, x])], T.fields[k] || '', { onchange: e => { T.fields[k] = e.target.value; } })
          : h('input', { type: 'text', value: T.fields[k] || '', placeholder: f.question || f.description || '', oninput: e => { T.fields[k] = e.target.value; } })))));
  return h('div', { class: 'sw-p sw-pl' }, h('div', { class: 'sw-ph' }, h('span', null, 'Comes in')), testWith,
    groups.map(([title, opts]) => swPills(title, opts, i)),
    SW.test ? null : h('p', { class: 'muted small' }, 'The values show up here after you test.'));
}

// ----- middle: the settings (the same forms as the side panel) -----
function swNotes(s) {
  const ta = h('textarea', { rows: 5, placeholder: 'Why this step is here, or what to check if it stops.', oninput: e => { const st = swStep(); if (!st) return; if (e.target.value.trim()) st.note = e.target.value; else delete st.note; commit(false); } });
  ta.value = s.note || '';
  return h('div', { class: 'stack' }, field('Note', ta, 'Only people who edit the flow see it. It never changes what the flow does. A small mark shows on the step.'));
}
function swMid(s, i) {
  const tabs = [['set', 'Settings'], ['if', 'Only if'], ['note', 'Notes'], ['tech', 'Technical']];
  const body = SW.tab === 'if' ? onlyIfTab(s, i) : SW.tab === 'tech' ? techTab(s, i) : SW.tab === 'note' ? swNotes(s) : settingsTab(s, i, swDraw);
  const probs = problemsFor(i + 1).map(([t, m]) => h('div', { class: 'prob ' + t }, m.replace(/^Step \d+( \([^)]*\))?:? ?/, '')));
  return h('div', { class: 'sw-p sw-pm' },
    h('div', { class: 'sw-tabs', role: 'tablist' }, tabs.map(([k, l]) => h('button', { class: 'tab', type: 'button', role: 'tab', 'aria-selected': String(SW.tab === k), onclick: () => { SW.tab = k; swDraw(); } }, l, k === 'note' && s.note ? h('i', { class: 'dotn' }) : null))),
    probs.length ? h('div', { class: 'stack s8', style: { marginBottom: '12px' } }, probs) : null, body);
}

// ----- right: what goes out -----
function swData(data) {
  if (SW.view === 'json') return h('pre', { class: 'sw-json' }, JSON.stringify(data, null, 2));
  return h('table', { class: 'sw-kv' }, h('tbody', null, Object.keys(data).map(k => h('tr', null, h('td', null, k), h('td', null, data[k] === null || data[k] === undefined ? h('span', { class: 'muted' }, '—') : String(data[k]))))));
}
function swPlain(msg) {
  const m = /^[\w.]+: no value at '\$?([^']+)'/.exec(String(msg || ''));
  if (!m) return msg;
  const path = m[1].split('.');
  return 'There is nothing to use for “' + pretty(path[path.length - 1]) + '” yet.' + (path[0] === 'fields' ? ' Type one under “Test with” on the left, then test again.' : ' A step before this one has to provide it.');
}
function swResult(i) {
  const t = SW.test;
  if (t.err) return h('div', { class: 'stack' }, notice(t.err, 'bad'));
  const line = t.lines[i], r = t.r, out = [];
  if (t.sig !== swSig(i)) out.push(notice('Something changed since this test. Press Test again.', 'warn'));
  if (!line) {
    const failed = (r.trace || []).find(x => x.status === 'failed');
    out.push(h('div', null, badge('Did not run'), h('p', { class: 'muted small', style: { marginTop: '8px' } }, failed || r.status === 'error' ? 'An earlier step stopped the test. ' + swPlain(r.message || (failed && failed.detail) || '') : 'The test did not get as far as this step.')));
    return h('div', { class: 'stack' }, out);
  }
  const tag = { ran: ['Ran for real', 'ok'], would: ['Would do this', 'info'], skipped: ['Skipped', ''], failed: ['Stopped here', 'bad'] }[line.status] || [line.status, ''];
  out.push(h('div', null, badge(tag[0], tag[1])));
  if (line.status === 'failed') {
    out.push(h('div', { class: 'sw-err' }, swPlain(r.message || line.detail || 'It stopped here.')));
    out.push(h('div', { class: 'sw-kv-w' }, h('table', { class: 'sw-kv' }, h('tbody', null, h('tr', null, h('td', null, 'Step'), h('td', null, line.text)), line.detail ? h('tr', null, h('td', null, 'What it said'), h('td', null, line.detail)) : null))));
    return h('div', { class: 'stack' }, out);
  }
  const note = { ran: 'It only looks things up, so this ran for real.', would: 'Nothing is saved or sent in a test.', skipped: 'Its “only if” is not true with these values.' }[line.status];
  if (note) out.push(h('div', { class: 'muted small' }, note));
  if (line.data) out.push(swData(line.data));
  else out.push(h('div', { class: 'muted small' }, line.detail || (line.status === 'ran' ? 'It passed, and the flow carries on.' : '')));
  return h('div', { class: 'stack' }, out);
}
function swOut(s, i) {
  const head = h('div', { class: 'sw-ph' }, h('span', null, 'Goes out'),
    h('span', { class: 'seg sm' }, [['table', 'Table'], ['json', 'JSON']].map(([v, l]) => h('button', { type: 'button', 'aria-pressed': String(SW.view === v), onclick: () => { SW.view = v; swDraw(); } }, l))));
  const body = SW.busy ? h('div', { class: 'muted' }, 'Testing…')
    : !SW.test ? h('div', { class: 'muted small' }, 'Not tested yet. Press “Test this step” to see what it does. Looking things up runs for real. Saving and sending are only described, so nothing is changed.')
    : swResult(i);
  return h('div', { class: 'sw-p sw-pr' }, head, body);
}
async function swTest() {
  if (!SW || SW.busy) return;
  const i = swIdx(), T = swTry();
  if (i < 0) return;
  if (!T.as) { toast('Pick who to test as first: open “Test with” on the left.', 'bad'); return; }
  const missing = Object.entries(EW.work.entity_schema || {}).filter(([k, f]) => f && typeof f === 'object' && !f.computed && f.required && !String(T.fields[k] || '').trim()).map(([k, f]) => f.label || pretty(k));
  if (missing.length) toast('Nothing typed under “Test with” for: ' + missing.join(', ') + '. The test runs without it.');
  SW.busy = true; swDraw();
  const mine = SW, sig = swSig(i);
  try {
    const fields = {};
    Object.entries(T.fields).forEach(([k, v]) => { if (String(v).trim() !== '') fields[k] = String(v).trim(); });
    const r = await api.post('/studio/try', { steps: tidySteps(EW.work.steps.slice(0, i + 1)), entity_schema: EW.work.entity_schema, fields, as_user: T.as, intent_key: EW.d.intent_key, name: EW.work.name, kind: EW.work.kind });
    if (SW !== mine) return;
    const top = (r.trace || []).filter(t => t.depth === 0), lines = []; let k = 0;
    EW.work.steps.forEach((st, j) => { const t = top[k]; if (t && t.op === st.op) { lines[j] = t; k++; } });
    SW.test = { r, lines, sig };
    CV.run = runFromTrace(r); renderNodes();
  } catch (e) { if (SW === mine) SW.test = { err: e.message || 'The test could not run.', lines: [], sig }; }
  if (SW === mine) { SW.busy = false; swDraw(); }
}

// ----- the foot: the same actions as the side panel -----
function swFoot(i) {
  const n = EW.work.steps.length, id = SW.id;
  const act = (a, ic, label, extra) => h('button', { class: 'btn sm' + (extra || ''), type: 'button', disabled: (a === 'up' && i === 0) || (a === 'down' && i === n - 1), onclick: () => { CV.sel = new Set([id]); stepAct(a); } }, icon(ic, 'sm'), label);
  return h('div', { class: 'sw-f' }, act('up', 'up', 'Move up'), act('down', 'down', 'Move down'), act('dup', 'copy', 'Duplicate'), EW.work.kind === 'block' ? null : act('park', 'unlink', 'Park'),
    h('span', { class: 'grow' }), act('del', 'trash', 'Delete', ' danger'));
}

// ----- rename, and the menu on a right-click -----
function cvRename(id) {
  const i = idxOf(id);
  if (i < 0) return;
  const s = EW.work.steps[i], input = h('input', { type: 'text', value: s.name || '', placeholder: describeStep(s) });
  const m = modal({ title: 'Rename this step', body: h('div', { class: 'stack' }, field('Name on the canvas', input, 'Leave it empty to use the name the step type gives it.')),
    actions: [{ label: 'Cancel' }, { label: 'Rename', primary: true, run: () => { const v = input.value.trim(); if (v) s.name = v; else delete s.name; commit(false); } }] });
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); const b = document.querySelector('.modal .mf .btn.primary'); if (b) b.click(); } });
  input.select();
  return m;
}
function cvMenu(e) {
  e.preventDefault();
  if (!EW || !CV || SW) return;
  const node = e.target.closest && e.target.closest('.nd'), id = node ? node.dataset.id : null;
  const anchor = { getBoundingClientRect: () => ({ left: e.clientX, right: e.clientX, top: e.clientY, bottom: e.clientY, width: 0, height: 0 }) };
  const row = (ic, label, key, fn, cls) => h('button', { class: 'mi' + (cls ? ' ' + cls : ''), type: 'button', onclick: () => { closePop(); fn(); } }, icon(ic, 'sm'), h('span', { class: 'grow' }, label), key ? h('span', { class: 'kbd' }, key) : null);
  const sep = () => h('div', { class: 'msep' });
  const pick = () => { CV.sel = new Set([id]); renderNodes(); renderInspector(); };
  let items;
  if (id && idxOf(id) >= 0) {
    pick();
    items = [row('edit', 'Open', 'Enter', () => swOpen(id)), row('play', 'Test this step', '', () => swOpen(id, { test: true })), row('edit', 'Rename', 'F2', () => cvRename(id)), sep(),
      row('copy', 'Duplicate', 'Ctrl+D', () => cvDup(id)), row('up', 'Move up', '', () => { CV.sel = new Set([id]); stepAct('up'); }), row('down', 'Move down', '', () => { CV.sel = new Set([id]); stepAct('down'); }),
      EW.work.kind === 'block' ? null : row('unlink', 'Park', '', () => cvPark(id)), sep(), row('trash', 'Delete', 'Del', () => cvDel(id), 'danger')];
  } else if (id && isParked(id)) {
    items = [row('undo', 'Put back in the flow', '', () => cvUnpark(id)), sep(), row('trash', 'Delete', 'Del', () => cvDel(id), 'danger')];
  } else if (id === 'trigger' || id === 'report') {
    items = [row('edit', 'Open', '', () => { CV.sel = new Set([id]); renderNodes(); renderInspector(); })];
  } else if (!node) {
    items = [isRead() ? null : row('plus', 'Add a step', 'N', cvNext), row('tidy', 'Tidy up', 'Shift+Alt+T', () => arrange(EW.mode || 'rows')), row('fit', 'Fit everything on screen', '', () => fitView(true))];
  } else return;
  openPop(anchor, items.filter(Boolean), { width: 250 });
}
"""
