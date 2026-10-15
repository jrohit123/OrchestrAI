JS = r"""
// ───────────────────────── Chat bot → Menu ─────────────────────────
// The menu people see in the chat, organised by use case: use cases (Tickets, Bookings ...) at the top, under each the flows that
// belong to it, and under a use case optionally one more level of groups. The tree is kept in the organisation's settings
// (GET/PUT /chat-menu). What a person sees (and the layout of a WhatsApp Flow panel) is worked out by the server, the same code
// the chat bot runs (POST /chat-menu/preview), so nothing about the menu is repeated here.
const cmRand = () => Math.random().toString(16).slice(2, 6);
const cmCopy = o => JSON.parse(JSON.stringify(o));

async function renderChatMenu(root) {
  const mine = S.renderId;
  let d;
  try { d = await api.get('/chat-menu'); } catch (e) { root.append(errorBox(e)); return; }
  if (mine !== S.renderId) return;
  const L = d.limits;
  let cfg = cmCopy(d.config), saved = JSON.stringify(cfg);
  const flowOf = key => d.flows.find(f => f.intent_key === key);
  const nameOf = key => { const f = flowOf(key); return f ? f.name : key; };
  const pv = { data: null, err: '', tab: 'chat', role: '', at: '', page: 1 };

  const wrap = h('div', { class: 'cm-wrap' });
  const editor = h('div', { class: 'stack s16 cm-edit' });
  const side = h('div', { class: 'cm-side stack' });
  const saveBar = h('div', { class: 'cm-save' });
  wrap.append(editor, side);
  root.append(wrap, saveBar);

  // ---- the tree: small helpers ----
  const placed = (nodes = cfg.nodes, found = new Set()) => { nodes.forEach(n => { if (n.flow) found.add(n.flow); else placed(n.children || [], found); }); return found; };
  const everyId = (nodes = cfg.nodes, found = new Set()) => { nodes.forEach(n => { if (!n.flow) { found.add(n.id); everyId(n.children || [], found); } }); return found; };
  const newId = label => {
    const base = (label || 'group').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 12) || 'group';
    const used = everyId(); let id = base;
    while (used.has(id)) id = base + '_' + cmRand();
    return id;
  };
  // every group a flow can be put in: [{ node, path }]
  const groups = () => {
    const out = [];
    cfg.nodes.forEach(u => { out.push({ node: u, path: u.label || 'Unnamed' });
      (u.children || []).filter(c => !c.flow).forEach(g => out.push({ node: g, path: (u.label || 'Unnamed') + ' › ' + (g.label || 'Unnamed') })); });
    return out;
  };
  const changed = redraw => { if (redraw) draw(); paintSave(); preview(); };
  const swap = (list, i, j) => { if (j < 0 || j >= list.length) return; [list[i], list[j]] = [list[j], list[i]]; changed(true); };
  const full = g => (g.children || []).length >= L.entries;
  const putIn = (entry, from, to) => {
    if (full(to)) { toast('“' + (to.label || 'That group') + '” can hold at most ' + L.entries + ' entries.', 'bad'); draw(); return; }
    if (from) from.splice(from.indexOf(entry), 1);
    to.children.push(entry); changed(true);
  };

  // ---- one row for a flow ----
  function flowRow(entry, list) {
    const f = flowOf(entry.flow), i = list.indexOf(entry);
    const here = groups().find(g => g.node.children === list);
    const label = h('input', { type: 'text', value: entry.label || '', placeholder: nameOf(entry.flow), maxlength: L.label, 'aria-label': 'Name in the menu for ' + nameOf(entry.flow) });
    label.addEventListener('input', () => { entry.label = label.value; changed(); });
    const moveTo = sel([['', 'Move to…'], ...groups().filter(g => !here || g.node !== here.node).map(g => [g.node.id, g.path])], '', { 'aria-label': 'Move ' + nameOf(entry.flow) + ' to another place' });
    moveTo.addEventListener('change', () => { const to = groups().find(g => g.node.id === moveTo.value); if (to) putIn(entry, list, to.node); });
    return h('div', { class: 'cm-entry' + (entry.hidden ? ' off' : '') },
      h('div', { class: 'cm-name' }, h('b', null, nameOf(entry.flow)), !f ? badge('no longer exists', 'bad') : (!f.is_active ? badge('switched off', 'warn') : null)),
      label, moveTo,
      h('span', { class: 'cm-shown' }, switchEl(!entry.hidden, on => { entry.hidden = !on; changed(true); }, false, 'Show ' + nameOf(entry.flow) + ' in the menu'), h('span', { class: 'muted small' }, 'Shown')),
      h('span', { class: 'row flat' },
        h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Move up', disabled: i === 0, onclick: () => swap(list, i, i - 1) }, '↑'),
        h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Move down', disabled: i === list.length - 1, onclick: () => swap(list, i, i + 1) }, '↓'),
        h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Take ' + nameOf(entry.flow) + ' out of the menu', onclick: () => { list.splice(i, 1); changed(true); } }, '×')));
  }

  // ---- a use case or a group: its name, its entries, what can be added ----
  function addFlowPicker(g) {
    const free = d.flows.filter(f => !placed().has(f.intent_key));
    if (!free.length || full(g)) return null;
    const pick = sel([['', '＋ Add a flow…'], ...free.map(f => [f.intent_key, f.name + (f.is_active ? '' : ' (switched off)')])], '', { 'aria-label': 'Add a flow to ' + (g.label || 'this group') });
    pick.addEventListener('change', () => { if (pick.value) putIn({ flow: pick.value, hidden: false }, null, g); });
    return pick;
  }
  function groupBox(g, list, level) {
    const i = list.indexOf(g);
    const label = h('input', { type: 'text', value: g.label || '', maxlength: L.label, placeholder: level === 1 ? 'For example Tickets' : 'For example Raise', 'aria-label': (level === 1 ? 'Use case' : 'Group') + ' name' });
    label.addEventListener('input', () => { g.label = label.value; changed(); });
    const desc = h('input', { type: 'text', value: g.description || '', maxlength: L.description, placeholder: 'A few words under the name (optional)', 'aria-label': 'Words under the name' });
    desc.addEventListener('input', () => { g.description = desc.value; changed(); });
    const move = level === 2 ? sel([['', 'Move to…'], ...cfg.nodes.filter(u => !u.children.includes(g)).map(u => [u.id, u.label || 'Unnamed'])], '', { 'aria-label': 'Move this group to another use case' }) : null;
    if (move) move.addEventListener('change', () => { const to = cfg.nodes.find(u => u.id === move.value); if (to) putIn(g, list, to); });
    const addGroup = level === 1 ? h('button', { class: 'btn sm', type: 'button', onclick: () => { if (full(g)) return toast('This use case is full.', 'bad'); const n = { id: newId('group'), label: '', description: '', hidden: false, children: [] }; g.children.push(n); changed(true); } }, '＋ Add a group') : null;
    const kids = g.children.map(c => c.flow ? flowRow(c, g.children) : groupBox(c, g.children, level + 1));
    return h('div', { class: 'cm-group l' + level + (g.hidden ? ' off' : '') },
      h('div', { class: 'cm-ghead' },
        h('div', { class: 'cm-gname' }, label, desc),
        move,
        h('span', { class: 'cm-shown' }, switchEl(!g.hidden, on => { g.hidden = !on; changed(true); }, false, 'Show ' + (g.label || 'this') + ' in the menu'), h('span', { class: 'muted small' }, 'Shown')),
        h('span', { class: 'row flat' },
          h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Move up', disabled: i === 0, onclick: () => swap(list, i, i - 1) }, '↑'),
          h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Move down', disabled: i === list.length - 1, onclick: () => swap(list, i, i + 1) }, '↓'),
          h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Remove ' + (g.label || 'this'), onclick: async () => {
            const n = (function count(x) { return (x.children || []).reduce((a, c) => a + (c.flow ? 1 : count(c)), 0); })(g);
            if (n && !await confirmBox('Remove “' + (g.label || 'this') + '”? Its ' + plural(n, 'flow') + ' will be left out of the menu until you place them again.', { ok: 'Remove', danger: true })) return;
            list.splice(i, 1); changed(true); } }, '×'))),
      h('div', { class: 'cm-kids' }, kids.length ? kids : h('div', { class: 'muted small' }, level === 1 ? 'Nothing in here yet. Add a flow or a group.' : 'Nothing in this group yet.')),
      h('div', { class: 'row cm-add' }, addFlowPicker(g), addGroup));
  }

  // ---- the whole editor ----
  function draw() {
    const free = d.flows.filter(f => !placed().has(f.intent_key));
    const gs = groups();
    const top = h('div', { class: 'card' }, h('div', { class: 'card-b stack' },
      h('div', { class: 'row between' },
        h('div', null, h('b', null, 'Use this menu in the chat'), h('div', { class: 'muted small' }, 'Off: the chat bot shows the menu it always has, every flow in its section.')),
        switchEl(cfg.enabled, on => { cfg.enabled = on; changed(); }, false, 'Use this menu in the chat')),
      h('div', { class: 'muted small' }, 'People only see the flows their role can use, and a group with nothing for them is left out. The menu goes three levels deep: use case, group, flow.'),
      h('div', { class: 'stack s8' }, h('b', { class: 'small' }, 'Who sees this menu'),
        h('div', { class: 'row' }, h('label', { class: 'row' }, h('input', { type: 'radio', name: 'cm-who', checked: !(cfg.only_roles || []).length, onchange: () => { delete cfg.only_roles; changed(true); } }), 'Everyone'),
          h('label', { class: 'row' }, h('input', { type: 'radio', name: 'cm-who', checked: !!(cfg.only_roles || []).length, onchange: () => { cfg.only_roles = [(d.roles[0] || {}).name].filter(Boolean); changed(true); } }), 'Only some roles, to try it out first')),
        (cfg.only_roles || []).length ? h('div', { class: 'row' }, d.roles.map(r => h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: cfg.only_roles.includes(r.name), onchange: e => { cfg.only_roles = e.target.checked ? [...cfg.only_roles, r.name] : cfg.only_roles.filter(x => x !== r.name); changed(true); } }), roleLabel(r.name)))) : null,
        (cfg.only_roles || []).length ? h('div', { class: 'muted small' }, 'Everyone else keeps the menu they have today.') : null),
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', onclick: async () => {
          if (cfg.nodes.length && !await confirmBox('Replace what is here with today’s menu?', { ok: 'Replace' })) return;
          try { const r = await api.post('/chat-menu/suggest'); cfg.nodes = r.config.nodes; changed(true); toast('Started from today’s menu. Rename and move things, then save.', 'ok'); }
          catch (e) { toast(e.message, 'bad'); } } }, 'Start from today’s menu'))));
    const cases = cfg.nodes.map(u => groupBox(u, cfg.nodes, 1));
    const addCase = cfg.nodes.length >= L.use_cases ? h('div', { class: 'muted small' }, 'A menu can have at most ' + L.use_cases + ' use cases.')
      : h('button', { class: 'btn' + (cfg.nodes.length ? '' : ' primary'), type: 'button', onclick: () => { cfg.nodes.push({ id: newId('use_case'), label: '', description: '', hidden: false, children: [] }); changed(true); } }, '＋ Add a use case');
    const unplaced = free.length ? h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('b', null, 'Not placed yet'), h('span', { class: 'muted small' }, cfg.show_unplaced === false ? 'These are left out of the menu.' : 'These show under “' + (cfg.other_label || d.words.other_label) + '” at the end of the menu until you place them.')),
      h('div', { class: 'card-b stack s8' }, free.map(f => {
        const put = sel([['', 'Put under…'], ...gs.map(g => [g.node.id, g.path])], '', { 'aria-label': 'Put ' + f.name + ' under a use case or group' });
        put.addEventListener('change', () => { const to = gs.find(g => g.node.id === put.value); if (to) putIn({ flow: f.intent_key, hidden: false }, null, to.node); });
        return h('div', { class: 'cm-entry' }, h('div', { class: 'cm-name' }, h('b', null, f.name), f.is_active ? null : badge('switched off', 'warn'), f.command_description ? h('div', { class: 'muted small' }, f.command_description) : null), gs.length ? put : h('span', { class: 'muted small' }, 'Add a use case first'));
      }))) : null;
    const word = (key, title, hint) => {
      const inp = h('input', { type: 'text', value: cfg[key] || '', placeholder: d.words[key], maxlength: d.word_max[key] });
      inp.addEventListener('input', () => { if (inp.value.trim()) cfg[key] = inp.value; else delete cfg[key]; changed(); });
      return field(title, inp, hint);
    };
    const wordsCard = h('details', { class: 'card cm-words' }, h('summary', { class: 'card-h' }, h('b', null, 'Words in the chat')),
      h('div', { class: 'card-b stack' },
        h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: cfg.show_unplaced !== false, onchange: e => { cfg.show_unplaced = e.target.checked; changed(true); } }), 'Show flows I have not placed at the end of the menu'),
        word('other_label', 'Name of that last use case', 'Shown only when there are flows not placed.'),
        word('back_label', 'Row that goes back', 'The last row of a group’s list.'),
        word('more_label', 'Row that shows more', 'A list holds ' + L.rows_per_message + ' rows, so a longer one goes over several lists.'),
        word('button_label', 'Button that opens a group’s list', 'At most ' + d.word_max.button_label + ' letters.')));
    fill(editor, top, cases.length ? cases : h('div', { class: 'card' }, h('div', { class: 'card-b' }, empty('No use cases yet', 'Add one, like Tickets, or start from today’s menu.'))), addCase, unplaced, wordsCard);
  }

  // ---- save ----
  const dirty = () => JSON.stringify(cfg) !== saved;
  function paintSave() {
    fill(saveBar, dirty() ? [h('span', { class: 'muted small grow' }, 'Not saved yet.'),
      h('button', { class: 'btn', type: 'button', onclick: () => { cfg = JSON.parse(saved); draw(); paintSave(); preview(); } }, 'Discard'),
      h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save menu')] : null);
    saveBar.className = 'cm-save' + (dirty() ? ' on' : '');
  }
  async function save() {
    try {
      const r = await api.put('/chat-menu', { config: cfg });
      cfg = cmCopy(r.config); saved = JSON.stringify(cfg);
      toast(cfg.enabled ? 'Saved. The chat bot uses this menu now.' : 'Saved. The menu is switched off, so the chat bot shows its usual menu.', 'ok');
      draw(); paintSave(); preview();
    } catch (e) { toast(e.message, 'bad'); }
  }

  // ---- the preview: what the server would show in the chat ----
  const preview = debounce(async () => {
    try { pv.data = await api.post('/chat-menu/preview', { config: cfg, role_id: pv.role || null }); pv.err = ''; }
    catch (e) { pv.data = null; pv.err = e.message; }
    if (mine === S.renderId) drawPreview();
  }, 350);
  const openRow = r => {
    if (!r.opens) { toast('This starts “' + r.title + '”.', 'ok'); return; }
    const parts = r.id.slice(5).split(':');
    pv.at = parts[0]; pv.page = parts[1] ? Number(parts[1].slice(1)) : 1; drawPreview();
  };
  function phone() {
    const screens = (pv.data && pv.data.screens) || [];
    const s = screens.find(x => x.id === pv.at) || screens[0];
    if (!s) return h('div', { class: 'muted small' }, pv.data && pv.data.empty ? 'Nothing to show yet. Add a use case and some flows.' : 'Nothing to show.');
    const p = s.pages[Math.min(Math.max(pv.page, 1), s.pages.length) - 1];
    return h('div', { class: 'cm-phone' },
      h('div', { class: 'cm-bubble' }, p.body, h('div', { class: 'cm-open' }, '☰ ' + p.button)),
      h('div', { class: 'cm-sheet' }, h('div', { class: 'cm-sheet-h' }, s.path + (s.pages.length > 1 ? ' (' + p.page + '/' + s.pages.length + ')' : '')),
        p.rows.map(r => h('div', { class: 'cm-row' + (r.back ? ' back' : ''), role: 'button', tabindex: '0', onclick: () => openRow(r), onkeydown: e => { if (e.key === 'Enter') openRow(r); } },
          h('div', null, h('b', null, (r.back ? '← ' : '') + r.title), r.description ? h('div', { class: 'muted small' }, r.description) : null), r.opens && !r.back ? h('span', { class: 'muted' }, '›') : null))));
  }
  function drawPanel() {
    const p = pv.data && pv.data.panel;
    const text = pv.data ? pv.data.flow_json : '';
    return h('div', { class: 'stack s8' },
      p ? notice(p.fits ? 'As a panel this menu is ' + p.bytes + ' of the ' + p.max_bytes + ' bytes WhatsApp can take for the most generous role.' : 'This menu is too big (or empty) for a panel, so the chat shows the lists above instead.', p.fits ? '' : 'warn') : null,
      h('div', { class: 'muted small' }, 'To show the menu as a panel inside WhatsApp: copy this layout, open WhatsApp Flows, create a Flow with it, send yourself a test, publish it, and choose it as the chat bot’s menu there. Nothing is sent to Meta from this page. The items are filled in for each person when the panel is sent, so people only see what their role allows.'),
      h('textarea', { class: 'wf-code small', readonly: true, rows: 14, 'aria-label': 'WhatsApp Flow layout' }, text),
      h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: async () => { try { await navigator.clipboard.writeText(text); toast('Copied', 'ok'); } catch (e) { toast('Select the text and copy it by hand.', 'bad'); } } }, 'Copy the layout')));
  }
  function drawPreview() {
    const as = sel([['', 'Everyone (every active flow)'], ...d.roles.map(r => [r.id, 'Someone with the role ' + roleLabel(r.name)])], pv.role, { 'aria-label': 'See the menu as' });
    as.addEventListener('change', () => { pv.role = as.value; pv.at = ''; pv.page = 1; preview(); });
    const tab = (k, t) => h('button', { class: 'btn sm' + (pv.tab === k ? ' primary' : ''), type: 'button', onclick: () => { pv.tab = k; drawPreview(); } }, t);
    fill(side, h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('b', null, 'How it looks')),
      h('div', { class: 'card-b stack' },
        field('See it as', as),
        h('div', { class: 'row' }, tab('chat', 'In the chat'), tab('panel', 'As a WhatsApp panel')),
        pv.err ? notice(pv.err, 'warn') : (pv.tab === 'chat' ? h('div', { class: 'stack s8' },
          pv.at ? h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { pv.at = ''; pv.page = 1; drawPreview(); } }, '← Back to the top') : null, phone(),
          h('div', { class: 'muted small' }, 'Click a row to open it. This is the list the chat bot would send for this menu.')) : drawPanel()))));
  }

  draw(); paintSave(); drawPreview(); preview();
}
"""
