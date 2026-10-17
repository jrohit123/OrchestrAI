// =====================================================================================================
// Flows and Building blocks: one box per use case.
// A flow or block lives in the box it was made in. Click its name (or Edit) to open it on the canvas.
// The box's switch decides whether the use case is in the chat menu. The settings of a use case
// (name, icon, people on a record, menu groups...) sit behind the box's ⚙ button, so there is no
// separate "Use cases" screen. The phone shows the chat menu these switches produce.
// =====================================================================================================
DB.usecases.forEach(u => { if (u.on === undefined) u.on = true; });
const BX = { open: {} };   // use case id -> settings open

function redraw() { const y = $('#screen').scrollTop; render(); $('#screen').scrollTop = y; }
function flowUsers(b) { return DB.flows.filter(f => f.graph.nodes.some(n => n.type === 'block' && n.cfg.block === b.id)); }

// Move a flow or block to another use case (or, for a block, to "shared by every use case")
function moveTo(item, kind, to) {
  item.usecase = to;
  if (kind === 'flow') item.graph.nodes.forEach(n => { if (n.type === 'chat' && n.cfg.menu) { n.cfg.menu.usecase = to; n.cfg.menu.group = ((uc(to) || {}).menu || [''])[0]; } });
  const where = to ? uc(to).name : 'Shared by every use case';
  const stranded = kind === 'block' && to ? flowUsers(item).filter(f => f.usecase !== to) : [];
  toast(stranded.length ? 'Moved to ' + where + '. ' + stranded.map(f => f.name).join(', ') + ' (another use case) still use it: move it to Shared to keep it for them.' : 'Moved to ' + where);
  redraw();
}
function moveSel(item, kind) {
  const here = item.usecase || '';
  const opts = DB.usecases.filter(u => u.id !== here).map(u => h('option', { value: u.id }, u.icon + ' ' + u.name));
  if (kind === 'block' && here) opts.push(h('option', { value: '__shared' }, '🌐 Shared by every use case'));
  return h('select', { class: 'mv', 'aria-label': 'Move to another use case', onchange: e => { if (e.target.value) moveTo(item, kind, e.target.value === '__shared' ? '' : e.target.value); } },
    h('option', { value: '' }, 'Move to…'), opts);
}

function flowRow(f) {
  const s = startOf(f);
  return h('div', { class: 'bx-row' + (f.on ? '' : ' off') },
    h('a', { class: 'nm', href: '#/flow/' + f.id }, f.name),
    h('span', { class: 'tiny muted trg' }, (s ? STEPS[s.type].icon : ''), ' ', triggerWords(f)),
    moveSel(f, 'flow'),
    h('button', { class: 'btn sm', onclick: () => go('flow', f.id) }, 'Edit'),
    sw(f.on, v => { f.on = v; toast(f.name + (v ? ' is on' : ' is off')); redraw(); }, f.name));
}
function blockRow(b) {
  const users = flowUsers(b);
  return h('div', { class: 'bx-row' },
    h('a', { class: 'nm', href: '#/block/' + b.id }, '🧩 ', b.name),
    h('span', { class: 'tiny muted trg' }, users.length ? 'Used by ' + users.map(f => f.name).join(', ') : 'Not used yet'),
    moveSel(b, 'block'),
    h('button', { class: 'btn sm', onclick: () => go('block', b.id) }, 'Edit'),
    pill('v' + b.version));
}

function boxHead(u, counts) {
  const open = !!BX.open[u.id];
  return h('div', { class: 'bx-h' },
    h('span', { class: 'ic', style: { background: u.color + '22' } }, u.icon), h('b', null, u.name), h('span', { class: 'tiny muted' }, counts),
    h('span', { class: 'sp' }),
    isSuper() ? h('button', { class: 'btn sm ghost', onclick: () => { BX.open[u.id] = !open; redraw(); } }, open ? 'Hide settings' : '⚙ Settings') : null,
    h('span', { class: 'tiny muted' }, u.on ? 'In the menu' : 'Off: not in the menu'),
    sw(u.on, v => { u.on = v; toast(u.name + (v ? ' is in the menu again' : ' left the menu; nothing is deleted')); redraw(); }, u.name));
}
function settingsIn(u) {
  const wrap = h('div', { class: 'bx-set' }, h('div', { class: 'tiny muted', style: { marginBottom: '8px' } }, 'The settings of the use case ' + u.name + ': its name, the people on a ' + recLabel(u.record).toLowerCase() + ', its statuses and the groups in the chat menu. Changes save as you type.'));
  const inner = h('div'); ucSetup(inner, u, DB.records[u.record]); wrap.append(inner);
  return wrap;
}

function flowBox(u) {
  const flows = DB.flows.filter(f => f.usecase === u.id), blocks = DB.blocks.filter(b => b.usecase === u.id);
  return h('section', { class: 'card bx' + (u.on ? '' : ' offbox') },
    boxHead(u, flows.length + ' flow' + (flows.length === 1 ? '' : 's') + ' · ' + blocks.length + ' block' + (blocks.length === 1 ? '' : 's')),
    BX.open[u.id] ? settingsIn(u) : null,
    flows.length ? flows.map(flowRow) : h('div', { class: 'bx-row muted small' }, 'No flows yet.'),
    blocks.length ? h('details', { class: 'bx-det' }, h('summary', null, 'Building blocks (' + blocks.length + ')'), blocks.map(blockRow)) : null,
    h('div', { class: 'bx-add' }, h('button', { class: 'btn sm', onclick: () => newFlowModal(u.id) }, '＋ New flow in ' + u.name), h('button', { class: 'btn sm ghost', onclick: () => newBlockModal(u.id) }, '＋ New building block')));
}
function blockBox(u) {
  const blocks = DB.blocks.filter(b => (b.usecase || '') === u.id);
  if (!u.id && !blocks.length) return null;
  return h('section', { class: 'card bx' + (u.id && !u.on ? ' offbox' : '') },
    u.id ? boxHead(u, blocks.length + ' building block' + (blocks.length === 1 ? '' : 's'))
         : h('div', { class: 'bx-h' }, h('span', { class: 'ic' }, '🌐'), h('b', null, 'Shared by every use case'), h('span', { class: 'tiny muted' }, blocks.length + ' building blocks · any flow can use them')),
    u.id && BX.open[u.id] ? settingsIn(u) : null,
    blocks.length ? blocks.map(blockRow) : h('div', { class: 'bx-row muted small' }, 'No building blocks yet.'),
    u.id ? h('div', { class: 'bx-add' }, h('button', { class: 'btn sm', onclick: () => newBlockModal(u.id) }, '＋ New building block in ' + u.name)) : null);
}

// what people see in the chat menu: the use cases that are on, with their flows that are on and start from chat
function menuPhone() {
  const groups = DB.usecases.filter(u => u.on).map(u => ({ u, fl: DB.flows.filter(f => f.usecase === u.id && f.on && (startOf(f) || {}).type === 'chat') })).filter(g => g.fl.length);
  return h('aside', { class: 'bx-phone' },
    h('b', { class: 'small' }, 'What people see on WhatsApp'),
    h('div', { class: 'tiny muted' }, 'It builds itself from the switches. Turn a use case or a flow off and it leaves.'),
    h('div', { class: 'ph-dev' },
      h('div', { class: 'ph-bar' }, DB.org.name),
      h('div', { class: 'ph-chat' },
        h('div', { class: 'ph-b' }, 'Hi Kartik, what would you like to do?'),
        h('div', { class: 'ph-menu' }, '☰ Menu'),
        groups.length ? groups.map(g => h('div', { class: 'ph-sec' }, h('b', null, g.u.icon + ' ' + g.u.name), g.fl.map(f => h('div', null, f.name)))) : h('div', { class: 'ph-sec' }, 'Nothing is switched on.'))));
}

function screenFlows(root) {
  drawTop([h('b', null, 'Flows')]);
  add(root, head('Flows', 'A flow is one thing the chat bot can do for people. Each sits in the box of the use case it was made in. Click one to open it on the canvas.',
      h('button', { class: 'btn pri', onclick: () => newUsecaseModal() }, '＋ New use case')),
    h('div', { class: 'bx-layout' }, h('div', { class: 'bx-main' }, DB.usecases.map(flowBox)), menuPhone()));
}
function screenBlocks(root) {
  drawTop([h('b', null, 'Building blocks')]);
  add(root, head('Building blocks', 'Small steps with a name that many flows reuse. Change one and every flow that uses it changes. Each sits in its use case, or is shared by every use case.',
      h('button', { class: 'btn pri', onclick: () => newUsecaseModal() }, '＋ New use case')),
    h('div', { class: 'bx-main' }, DB.usecases.concat([{ id: '', name: 'Shared', icon: '🌐' }]).map(blockBox)));
}
