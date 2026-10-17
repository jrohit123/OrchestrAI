// ---------------- Test: walk the flow like a person on WhatsApp. Nothing is sent or saved. ----------------
function openSimulator(ed) {
  const g = clone(ed.g), byId = id => g.nodes.find(n => n.id === id);
  const msgs = h('div', { class: 'msgs' }), input = h('input', { type: 'text', placeholder: 'Type a message' });
  const trace = h('div', { class: 'trace' }), side = h('div', { class: 'col', style: { flex: 1, minWidth: '240px' } });
  let vars = {}, waiting = null, path = [], seq = 142;
  // every value any step can make, with its sample, so a message never shows an empty hole
  g.nodes.forEach(n => STEPS[n.type].gives(n.cfg || {}).forEach(v => vars[v[0]] = v[2]));
  Object.assign(vars, { 'org.name': DB.org.name, 'today.date': '15 Oct 2026', 'today.time': '4:30 pm' });
  const fillT = t => String(t || '').replace(/\{([^}]+)\}/g, (m, k) => vars[k] != null ? vars[k] : m);
  const bub = (cls, text, buttons) => { const b = h('div', { class: 'bub ' + cls }, text, buttons && buttons.length ? h('div', { class: 'bts' }, buttons.map(x => h('button', { onclick: () => { if (waiting) reply(x); } }, x))) : null); msgs.append(b); msgs.scrollTop = 1e6; };
  const sys = t => bub('sys', t);
  const next = (n, out) => { const e = g.edges.filter(x => x.from === n.id && (x.out || 0) === (out || 0)); return e.map(x => byId(x.to)); };
  function mark(n) { path.push(n.id); fill(trace, h('b', { class: 'small' }, 'Steps it went through'), path.map((id, i) => { const m = byId(id); return h('div', { class: i === path.length - 1 ? 'cur' : '' }, STEPS[m.type].icon + ' ' + (m.name || (m.type === 'block' ? (blockById(m.cfg.block) || {}).name : STEPS[m.type].name))); })); }
  async function run(n) {
    if (!n) { sys('— the flow ends here —'); waiting = null; return; }
    mark(n); await new Promise(r => setTimeout(r, 380));
    const c = n.cfg || {}, s = STEPS[n.type];
    switch (n.type) {
      case 'chat': sys('Starts when someone says something like “' + ((c.phrases || [])[0] || 'hello') + '”' + (c.menu && c.menu.group ? ', or taps ' + (uc(c.menu.usecase) || {}).name + ' › ' + c.menu.group + ' in the menu' : '')); waiting = { n, kind: 'start' }; input.placeholder = 'Type how a person would start it…'; if ((c.phrases || [])[0]) bub('in', 'Try it:', [c.phrases[0]]); return;
      case 'ask': bub('in', fillT(c.text) || '(no question yet)', c.answer === 'One of these choices' ? c.choices : c.answer === 'Yes or no' ? ['Yes', 'No'] : c.optional ? ['Skip'] : null); waiting = { n, kind: 'ask' }; input.placeholder = c.answer === 'A photo' ? 'Type “photo” to pretend you sent one' : 'Your answer'; return;
      case 'choices': bub('in', fillT(c.text) || 'Choose:', c.options); waiting = { n, kind: 'choice' }; return;
      case 'say': case 'end': if (c.text) bub('in', fillT(c.text), c.buttons); break;
      case 'tell': sys('📣 Sent to ' + whoWords(c.who, c.record) + ': ' + fillT(c.text)); break;
      case 'create': { const R = DB.records[c.record || 'ticket']; vars['new.number'] = R.prefix + '-26-0' + (seq++); sys('💾 Saved a new ' + R.label.toLowerCase() + ' ' + vars['new.number']); break; }
      case 'update': sys('✏️ Changed the ' + recLabel(c.record).toLowerCase() + (c.status ? ': status → ' + c.status : '')); break;
      case 'find': sys('🔎 Found ' + recLabel(c.record).toLowerCase() + ' ' + (vars[(c.value || '').replace(/[{}]/g, '')] || 'TK-26-0142')); break;
      case 'list': sys('📃 Found ' + vars['list.count'] + ' ' + recLabel(c.record).toLowerCase() + 's'); break;
      case 'assign': sys('👤 Given to ' + vars['handler.name'] + ' (from ' + (c.how || 'Who handles what') + ')'); break;
      case 'ai': sys('✨ AI: ' + (c.task || '') + ' → ' + vars['ai.' + slug(c.into || 'result')]); break;
      case 'approve': sys('✅ Asked ' + whoWords(c.who) + ' to approve. Answer as the approver:'); approverButtons(n); return;
      case 'if': { const v = fillT(c.value), ok = c.op === 'is empty' ? !v : c.op === 'is not' ? v !== c.than : c.op === 'contains' ? v.includes(c.than || '') : (c.op === 'is more than' ? +v > +c.than : c.op === 'is less than' ? +v < +c.than : String(v) === String(c.than)); sys('🔀 ' + v + ' ' + (c.op || 'is') + ' ' + (c.than || '') + ' → ' + (ok ? 'Yes' : 'No')); return run(next(n, ok ? 0 : 1)[0]); }
      case 'block': { const b = blockById(c.block); sys('🧩 ' + (b ? b.name : 'block') + ' ran'); if (b && b.outs) return run(next(n, 0)[0]); break; }
      case 'wait': sys('⏳ Waits ' + (c.for || '') + ' (skipped in a test)'); break;
      case 'schedule': case 'change': case 'button': case 'form': case 'after': sys('▶ Started: ' + subtitle(n)); break;
      default: sys(s.icon + ' ' + s.name);
    }
    const nx = next(n, 0);
    for (let i = 0; i < nx.length; i++) await run(nx[i]);
    if (!nx.length && !waiting) { if (!msgs.lastChild || !/ends here/.test(msgs.lastChild.textContent)) sys('— the flow ends here —'); }
  }
  function approverButtons(n) { side.querySelectorAll('.apr').forEach(x => x.remove()); side.append(h('div', { class: 'card card-b apr col' }, h('b', { class: 'small' }, 'You are the approver'), h('div', { class: 'row' }, h('button', { class: 'btn pri', onclick: e => { e.target.closest('.apr').remove(); vars['approval.note'] = 'Approved'; run(next(n, 0)[0]); } }, 'Approve'), h('button', { class: 'btn danger', onclick: e => { e.target.closest('.apr').remove(); vars['approval.note'] = 'the hall is booked for repairs'; run(next(n, 1)[0]); } }, 'Reject')))); }
  function reply(text) {
    if (!waiting) return; bub('me', text);
    const { n, kind } = waiting; waiting = null; input.placeholder = 'Type a message';
    if (kind === 'start') { vars['message.text'] = text; return run(next(n, 0)[0]); }
    if (kind === 'choice') { const i = Math.max(0, (n.cfg.options || []).indexOf(text)); vars.choice = text; return run(next(n, i)[0]); }
    vars['answer.' + slug(n.cfg.save || 'answer')] = n.cfg.answer === 'A photo' && text !== 'Skip' ? '1 photo' : text;
    run(next(n, 0)[0]);
  }
  const send = () => { const t = input.value.trim(); if (!t) return; input.value = ''; reply(t); };
  input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
  const phone = h('div', { class: 'phone' }, h('div', { class: 'scr' }, h('div', { class: 'bar' }, h('div', { class: 'av', style: { background: '#fff3', color: '#fff' } }, 'GE'), h('div', null, h('b', null, DB.org.name), h('div', { style: { fontSize: '11px', opacity: .8 } }, 'test · nothing is sent'))), msgs, h('div', { class: 'comp' }, input, h('button', { onclick: send }, '➤'))));
  const restart = () => { msgs.replaceChildren(); path = []; trace.replaceChildren(); side.querySelectorAll('.apr').forEach(x => x.remove()); const st = g.nodes.find(n => STEPS[n.type].start) || g.nodes[0]; run(st); };
  add(side, h('div', { class: 'notice' }, 'ℹ️', h('div', null, 'A test uses made-up values for anything not asked here. Nothing is sent to anyone and nothing is saved.')), h('button', { class: 'btn', style: { alignSelf: 'flex-start' }, onclick: restart }, '↺ Start again'), trace);
  modal({ title: 'Test “' + ed.obj.name + '”', size: 'mid', body: h('div', { class: 'row', style: { alignItems: 'flex-start', flexWrap: 'nowrap', gap: '20px' } }, phone, side) });
  restart();
}
