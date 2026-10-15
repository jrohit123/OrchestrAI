JS = r"""
// ───────────────────────── WhatsApp forms: the Questions builder ─────────────────────────
// Edits the Flow JSON in plain words. The JSON stays the one truth: every change here is made on the parsed JSON and written back,
// and every change in the JSON redraws this. Anything the builder does not know is left exactly as it is and named in a notice.

const WFB_KINDS = [
  { key: 'short', label: 'Short text', type: 'TextInput', input: 'text', help: 'helper-text' },
  { key: 'number', label: 'Number', type: 'TextInput', input: 'number', help: 'helper-text' },
  { key: 'email', label: 'Email address', type: 'TextInput', input: 'email', help: 'helper-text' },
  { key: 'phone', label: 'Phone number', type: 'TextInput', input: 'phone', help: 'helper-text' },
  { key: 'long', label: 'Long text', type: 'TextArea', help: 'helper-text' },
  { key: 'dropdown', label: 'Dropdown list', type: 'Dropdown', choices: true, help: 'description' },
  { key: 'single', label: 'Pick one (buttons)', type: 'RadioButtonsGroup', choices: true, help: 'description' },
  { key: 'multi', label: 'Pick several (ticks)', type: 'CheckboxGroup', choices: true, help: 'description' },
  { key: 'date', label: 'Date', type: 'DatePicker', help: 'helper-text' },
  { key: 'photo', label: 'Photos', type: 'PhotoPicker', help: 'description', files: true },
  { key: 'file', label: 'Documents', type: 'DocumentPicker', help: 'description', files: true },
  { key: 'heading', label: 'Big heading', type: 'TextHeading', text: true },
  { key: 'subheading', label: 'Smaller heading', type: 'TextSubheading', text: true },
  { key: 'paragraph', label: 'Paragraph', type: 'TextBody', text: true },
  { key: 'small', label: 'Small print', type: 'TextCaption', text: true },
];
const WFB_BY_KEY = Object.fromEntries(WFB_KINDS.map(k => [k.key, k]));
const WFB_FAMILIES = [['short', 'number', 'email', 'phone'], ['dropdown', 'single', 'multi'], ['heading', 'subheading', 'paragraph', 'small']];

function wfbKindOf(n) {            // the builder's name for a component, or null when it does not know it
  if (!n || typeof n !== 'object') return null;
  if (n.type === 'TextInput') { const t = n['input-type'] || 'text'; return ['text', 'number', 'email', 'phone'].includes(t) ? (t === 'text' ? 'short' : t) : null; }
  const k = WFB_KINDS.find(x => x.type === n.type && x.key !== 'short' && x.key !== 'number' && x.key !== 'email' && x.key !== 'phone');
  if (!k) return null;
  if (k.choices && !Array.isArray(n['data-source']) && typeof n['data-source'] !== 'string') return null;
  return k.key;
}
const wfbIsAnswer = n => { const k = WFB_BY_KEY[wfbKindOf(n)]; return !!(k && !k.text && typeof n.name === 'string'); };
const wfbFooter = s => (((s.layout || {}).children) || []).find(c => c && c.type === 'Footer') || null;
const wfbEditable = s => !!(s && s.layout && s.layout.type === 'SingleColumnLayout' && Array.isArray(s.layout.children));
const wfbMany = k => k === 'multi' || k === 'photo' || k === 'file';

function wfbSlug(text, fallback) { return String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40) || fallback || 'answer'; }
function wfbAllNames(flow) {
  const out = new Set();
  (flow.screens || []).forEach(s => (((s.layout || {}).children) || []).forEach(c => { if (c && typeof c.name === 'string') out.add(c.name); }));
  return out;
}
function wfbUniqueName(flow, base) {
  const used = wfbAllNames(flow); let name = wfbSlug(base), i = 2;
  while (used.has(name)) name = wfbSlug(base) + '_' + (i++);
  return name;
}
function wfbLetters(i) { let s = ''; i += 1; while (i > 0) { const r = (i - 1) % 26; s = String.fromCharCode(65 + r) + s; i = Math.floor((i - 1) / 26); } return s; }
function wfbScreenId(flow, title) {      // Meta wants letters and underscores only
  const used = new Set((flow.screens || []).map(s => s.id));
  const base = String(title || '').toUpperCase().replace(/[^A-Z]+/g, '_').replace(/^_+|_+$/g, '') || 'SCREEN';
  if (!used.has(base)) return base;
  for (let i = 0; ; i++) { const id = base + '_' + wfbLetters(i); if (!used.has(id)) return id; }
}

// ---- choices ----
function wfbChoicesText(n) { return Array.isArray(n['data-source']) ? n['data-source'].map(c => c && c.title !== undefined ? String(c.title) : '').join('\n') : ''; }
function wfbSetChoices(n, text) {         // keeps the id of a choice whose words did not change
  const old = Array.isArray(n['data-source']) ? n['data-source'] : [];
  const titles = String(text || '').split('\n').map(t => t.trim()).filter(Boolean);
  const used = new Set(), out = [];
  titles.forEach(t => {
    const was = old.find(c => c && String(c.title) === t && !used.has(c.id));
    let id = was ? was.id : wfbSlug(t, 'option'), i = 2;
    while (used.has(id)) id = wfbSlug(t, 'option') + '_' + (i++);
    used.add(id); out.push(Object.assign({}, was || {}, { id, title: t }));
  });
  n['data-source'] = out;
}

// ---- the answers a screen sends on ----
function wfbSetPayload(flow, si, name, kind, on, seen) {
  seen = seen || new Set();
  const s = flow.screens[si];
  if (!s || seen.has(s.id)) return; seen.add(s.id);
  const f = wfbFooter(s), a = f && f['on-click-action'];
  if (!a || (a.name !== 'complete' && a.name !== 'navigate')) return;
  const own = ((s.layout || {}).children || []).some(c => c && c.name === name);
  const ref = own ? '${form.' + name + '}' : '${data.' + name + '}';
  a.payload = a.payload && typeof a.payload === 'object' ? a.payload : {};
  if (on) {
    if (a.payload[name] === undefined) a.payload[name] = ref;
    if (!own) {
      s.data = s.data && typeof s.data === 'object' ? s.data : {};
      if (!s.data[name]) s.data[name] = wfbMany(kind) ? { type: 'array', items: { type: 'string' }, __example__: [] } : { type: 'string', __example__: 'Example' };
    }
  } else {
    if (a.payload[name] === ref || own === false) delete a.payload[name];
    if (!own && s.data) delete s.data[name];
  }
  if (a.name === 'navigate' && a.next && a.next.name) {
    const nx = flow.screens.findIndex(x => x.id === a.next.name);
    if (nx >= 0) wfbSetPayload(flow, nx, name, kind, on, seen);
  }
}
function wfbPayloadHere(s, name, on) {   // only this screen's own button: add or take out one answer
  const f = wfbFooter(s), a = f && f['on-click-action'];
  if (!a || !a.payload || typeof a.payload !== 'object') return;
  if (on) { if (a.payload[name] === undefined) a.payload[name] = '${form.' + name + '}'; } else delete a.payload[name];
}

// ---- changes (each takes the parsed flow and changes it in place) ----
function wfbNewNode(flow, key, label) {
  const k = WFB_BY_KEY[key];
  if (k.text) return { type: k.type, text: label || (key === 'heading' ? 'A heading' : key === 'subheading' ? 'A smaller heading' : key === 'small' ? 'Some small print' : 'Some words for the person filling this in') };
  const n = { type: k.type, name: wfbUniqueName(flow, label || k.label), label: label || (k.label === 'Photos' ? 'Add photos' : k.label === 'Documents' ? 'Add documents' : 'Your question') };
  if (k.input) n['input-type'] = k.input;
  if (k.choices) n['data-source'] = [{ id: 'option_1', title: 'First choice' }, { id: 'option_2', title: 'Second choice' }];
  if (k.type === 'PhotoPicker') Object.assign(n, { 'photo-source': 'camera_gallery', 'max-file-size-kb': 5120, 'min-uploaded-photos': 0, 'max-uploaded-photos': 3 });
  else if (k.type === 'DocumentPicker') Object.assign(n, { 'max-file-size-kb': 5120, 'min-uploaded-documents': 0, 'max-uploaded-documents': 3 });
  else n.required = true;
  return n;
}
function wfbAdd(flow, si, key, label) {
  const s = flow.screens[si], kids = s.layout.children, node = wfbNewNode(flow, key, label);
  const f = wfbFooter(s), at = f ? kids.indexOf(f) : kids.length;
  kids.splice(at < 0 ? kids.length : at, 0, node);
  if (wfbIsAnswer(node)) wfbSetPayload(flow, si, node.name, key, true);
  return node;
}
function wfbRemove(flow, si, ci) {
  const s = flow.screens[si], node = s.layout.children[ci];
  s.layout.children.splice(ci, 1);
  if (node && typeof node.name === 'string' && wfbIsAnswer(node)) wfbSetPayload(flow, si, node.name, wfbKindOf(node), false);
}
function wfbMove(flow, si, ci, dir) {          // among the things before the button
  const kids = flow.screens[si].layout.children, to = ci + dir;
  const f = wfbFooter(flow.screens[si]), last = f ? kids.indexOf(f) : kids.length;
  if (to < 0 || to >= last) return false;
  const [x] = kids.splice(ci, 1); kids.splice(to, 0, x); return true;
}
function wfbRenameAnswer(flow, si, node, next) {
  const old = node.name; next = wfbSlug(next, old);
  if (next === old || wfbAllNames(flow).has(next)) return false;
  const kind = wfbKindOf(node);
  wfbSetPayload(flow, si, old, kind, false);
  node.name = next;
  wfbSetPayload(flow, si, next, kind, true);
  return true;
}
function wfbChangeKind(node, key) {             // within a family (short ↔ number ↔ email…, dropdown ↔ pick one ↔ pick several)
  const k = WFB_BY_KEY[key];
  node.type = k.type;
  if (k.type === 'TextInput') node['input-type'] = k.input;
}
function wfbSetRequired(n, on) {
  if (n.type === 'PhotoPicker') n['min-uploaded-photos'] = on ? Math.max(1, n['min-uploaded-photos'] || 1) : 0;
  else if (n.type === 'DocumentPicker') n['min-uploaded-documents'] = on ? Math.max(1, n['min-uploaded-documents'] || 1) : 0;
  else n.required = !!on;
}
const wfbIsRequired = n => n.type === 'PhotoPicker' ? (n['min-uploaded-photos'] || 0) > 0 : n.type === 'DocumentPicker' ? (n['min-uploaded-documents'] || 0) > 0 : n.required === true;
function wfbSetHelp(n, text) {
  const key = WFB_BY_KEY[wfbKindOf(n)].help;
  if (text) n[key] = text; else delete n[key];
}
function wfbNextOf(flow, s) {
  const f = wfbFooter(s), a = f && f['on-click-action'];
  return a && a.name === 'navigate' && a.next && a.next.name ? a.next.name : null;
}
function wfbAddScreen(flow, title) {
  const last = flow.screens[flow.screens.length - 1];
  const id = wfbScreenId(flow, title);
  const screen = { id, title: title || 'New screen', terminal: true, success: true, data: {},
    layout: { type: 'SingleColumnLayout', children: [ { type: 'TextBody', text: 'Some words for the person filling this in' },
      { type: 'Footer', label: 'Done', 'on-click-action': { name: 'complete', payload: {} } } ] } };
  if (last) {
    const f = wfbFooter(last), a = f && f['on-click-action'];
    if (a && a.name === 'complete') {
      const own = new Map(); flow.screens.forEach(s => (s.layout.children || []).forEach(c => { if (wfbIsAnswer(c)) own.set(c.name, wfbKindOf(c)); }));
      const payload = a.payload && typeof a.payload === 'object' ? a.payload : {};
      f['on-click-action'] = { name: 'navigate', next: { type: 'screen', name: id }, payload };
      if (f.label === 'Submit' || f.label === 'Done' || f.label === 'Finish') f.label = 'Continue';
      delete last.terminal; delete last.success;
      const out = screen.layout.children[1]['on-click-action'].payload;
      Object.keys(payload).forEach(k => {
        screen.data[k] = wfbMany(own.get(k)) ? { type: 'array', items: { type: 'string' }, __example__: [] } : { type: 'string', __example__: 'Example' };
        out[k] = '${data.' + k + '}';
      });
    }
  }
  flow.screens.push(screen);
  return screen;
}
function wfbRemoveScreen(flow, si) {
  if (flow.screens.length < 2) return false;
  const gone = flow.screens[si], after = wfbNextOf(flow, gone);
  flow.screens.forEach((s, i) => {
    if (i === si) return;
    const f = wfbFooter(s), a = f && f['on-click-action'];
    if (!a || a.name !== 'navigate' || !a.next || a.next.name !== gone.id) return;
    if (after && after !== s.id) a.next.name = after;
    else {                                          // the end of the form now: finish here, sending only what this screen knows
      f['on-click-action'] = { name: 'complete', payload: Object.fromEntries(Object.entries(a.payload || {}).filter(([, v]) => !String(v).startsWith('${data.'))) };
      s.terminal = true; s.success = true;
    }
  });
  flow.screens.splice(si, 1);
  return true;
}

// ---- what the builder can and cannot show ----
function wfbReport(flow) {
  const notes = []; let ok = true;
  if (!flow || typeof flow !== 'object' || !Array.isArray(flow.screens)) return { ok: false, notes: ['The JSON has no list of screens yet.'] };
  flow.screens.forEach(s => {
    if (!wfbEditable(s)) { notes.push('Screen “' + (s.title || s.id) + '” is laid out in a way the builder cannot change, so it is shown but left alone. Use the JSON for it.'); return; }
    const odd = s.layout.children.filter(c => c && c.type !== 'Footer' && !wfbKindOf(c));
    if (odd.length) notes.push('Screen “' + (s.title || s.id) + '” has ' + odd.length + (odd.length === 1 ? ' thing' : ' things') + ' the builder does not understand (' + [...new Set(odd.map(c => c.type || 'unknown'))].join(', ') + '). ' + (odd.length === 1 ? 'It stays' : 'They stay') + ' exactly as ' + (odd.length === 1 ? 'it is' : 'they are') + '.');
  });
  return { ok, notes };
}

// ---- drawing ----
function wfbDraw(box, io) {
  const flow = io.flow();
  if (!flow) { fill(box, notice('The JSON has a mistake in it, so the questions cannot be shown yet. Fix it on the JSON tab, or undo your last change there.', 'warn')); return; }
  const rep = wfbReport(flow);
  if (!rep.ok) { fill(box, notice(rep.notes[0] + ' Use the JSON tab to start the form, or press Create Flow on the list for a sample.', 'warn')); return; }
  const change = (fn, redraw) => io.apply(fl => fn(fl), redraw);
  const text = (value, on, props) => { const i = h('input', Object.assign({ type: 'text', value: value || '' }, props || {})); i.addEventListener('input', () => on(i.value)); return i; };
  const small = (t, ctl) => h('label', { class: 'wfb-f' }, h('span', { class: 'muted small' }, t), ctl);
  const kindSelect = (n, si, ci) => {
    const key = wfbKindOf(n), fam = WFB_FAMILIES.find(f => f.includes(key));
    if (!fam) return h('b', null, WFB_BY_KEY[key].label);
    const s = sel(fam.map(k => [k, WFB_BY_KEY[k].label]), key, { 'aria-label': 'Kind of question' });
    s.addEventListener('change', () => change(fl => wfbChangeKind(fl.screens[si].layout.children[ci], s.value), true));
    return s;
  };
  const screens = flow.screens.map((s, si) => {
    const head = h('div', { class: 'row between' },
      h('span', { class: 'row' }, h('b', null, 'Screen ' + (si + 1)), h('span', { class: 'muted small' }, s.id)),
      flow.screens.length > 1 ? h('button', { class: 'btn sm danger', type: 'button', onclick: async () => {
        if (!await confirmBox('Remove the screen “' + (s.title || s.id) + '” and its questions?', { ok: 'Remove', danger: true })) return;
        change(fl => wfbRemoveScreen(fl, si), true); } }, 'Remove screen') : null);
    if (!wfbEditable(s)) return h('div', { class: 'card' }, h('div', { class: 'card-b stack' }, head, h('div', { class: 'wfb-lock' }, 'Kept as it is. The builder cannot change this screen; use the JSON tab.')));
    const kids = s.layout.children, foot = wfbFooter(s), lastAt = foot ? kids.indexOf(foot) : kids.length;
    const items = kids.map((n, ci) => {
      if (n === foot) return null;
      const key = wfbKindOf(n);
      const tools = h('span', { class: 'row wfb-tools' },
        h('button', { class: 'btn sm', type: 'button', 'aria-label': 'Move up', disabled: ci === 0, onclick: () => change(fl => wfbMove(fl, si, ci, -1), true) }, '↑'),
        h('button', { class: 'btn sm', type: 'button', 'aria-label': 'Move down', disabled: ci >= lastAt - 1, onclick: () => change(fl => wfbMove(fl, si, ci, 1), true) }, '↓'),
        key ? h('button', { class: 'btn sm danger', type: 'button', 'aria-label': 'Remove', onclick: () => change(fl => wfbRemove(fl, si, ci), true) }, '✕') : null);
      if (!key) return h('div', { class: 'wfb-q wfb-lock' }, h('span', null, 'Kept as it is: “' + (n.type || 'unknown') + '”. The builder does not understand this one.'), tools);
      const k = WFB_BY_KEY[key], node = () => flow.screens[si].layout.children[ci];
      const set = (fn, redraw) => change(fl => fn(fl.screens[si].layout.children[ci], fl), redraw);
      if (k.text) return h('div', { class: 'wfb-q' }, h('div', { class: 'row between' }, kindSelect(n, si, ci), tools),
        small('Words', text(n.text, v => set(x => { x.text = v; }, false))));
      const dynamic = k.choices && typeof n['data-source'] === 'string';
      return h('div', { class: 'wfb-q' },
        h('div', { class: 'row between' }, kindSelect(n, si, ci), tools),
        small('Question', text(n.label, v => set(x => { x.label = v; }, false))),
        small('Helper text (optional)', text(n[k.help], v => set(x => wfbSetHelp(x, v), false))),
        k.choices ? (dynamic
          ? h('div', { class: 'muted small' }, 'The choices come from the chat bot (' + n['data-source'] + '). Change them in the JSON.')
          : small('Choices (one on each line)', (() => { const t = h('textarea', { rows: 4, 'aria-label': 'Choices' }); t.value = wfbChoicesText(n); t.addEventListener('input', () => set(x => wfbSetChoices(x, t.value), false)); return t; })())) : null,
        k.type === 'PhotoPicker' ? small('Most photos', text(String(n['max-uploaded-photos'] || 3), v => set(x => { x['max-uploaded-photos'] = Math.max(1, Math.min(30, parseInt(v, 10) || 1)); }, false), { type: 'number', min: 1, max: 30 })) : null,
        h('div', { class: 'row between' },
          h('label', { class: 'row small' }, (() => { const c = h('input', { type: 'checkbox', checked: wfbIsRequired(n) }); c.addEventListener('change', () => set(x => wfbSetRequired(x, c.checked), false)); return c; })(), ' The person must answer'),
          h('label', { class: 'row small', title: 'The chat bot receives the answer under this name. Change it only if the workflow expects another name.' }, h('span', { class: 'muted' }, 'Answer name'),
            (() => { const i = text(n.name, () => {}, { class: 'wfb-name', 'aria-label': 'Answer name' }); i.addEventListener('change', () => { change(fl => { if (!wfbRenameAnswer(fl, si, fl.screens[si].layout.children[ci], i.value)) { i.value = node().name; toast('That name is already used or empty.', 'bad'); } }, true); }); return i; })())));
    });
    const add = sel([['', 'Add a question or text…'], ...WFB_KINDS.filter(k => !k.text).map(k => [k.key, k.label]), ...WFB_KINDS.filter(k => k.text).map(k => [k.key, 'Text: ' + k.label])], '', { 'aria-label': 'Add to this screen' });
    add.addEventListener('change', () => { const key = add.value; if (key) change(fl => wfbAdd(fl, si, key), true); });
    const next = wfbNextOf(flow, s);
    return h('div', { class: 'card' }, h('div', { class: 'card-b stack' }, head,
      small('Screen title', text(s.title, v => change(fl => { fl.screens[si].title = v; }, false))),
      h('div', { class: 'stack s8' }, items),
      add,
      foot ? small('Button at the bottom', text(foot.label, v => change(fl => { wfbFooter(fl.screens[si]).label = v; }, false))) : h('div', { class: 'muted small' }, 'This screen has no button.'),
      h('div', { class: 'muted small' }, foot ? (next ? 'The button goes on to “' + ((flow.screens.find(x => x.id === next) || {}).title || next) + '”.' : 'The button ends the form and sends the answers to the chat bot.') : '')));
  });
  fill(box,
    rep.notes.length ? notice(rep.notes.join(' '), 'warn') : null,
    h('div', { class: 'muted small' }, 'Changes here are written into the JSON, and changes in the JSON show up here. Settings the builder does not show (like a hidden question) are kept.'),
    screens,
    h('div', null, h('button', { class: 'btn', type: 'button', onclick: () => change(fl => wfbAddScreen(fl, 'Screen ' + (fl.screens.length + 1)), true) }, 'Add a screen')));
}
"""
