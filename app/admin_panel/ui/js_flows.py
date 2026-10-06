JS = r"""
// ───────────────────────── Flows: cards and map ─────────────────────────
const FV = { view: 'cards', kind: 'flow', text: '' };       // remembered while you move about the dashboard

// a flow in miniature: the trigger, then one small square per step in the colour of what it does
function flowThumb(w) {
  const shape = w.shape || [], parts = [];
  if ((w.kind || 'workflow') !== 'block') parts.push(h('span', { class: 'tn trg' }, icon('bolt', 'xs')));
  shape.slice(0, 15).forEach((sh, i) => {
    if (parts.length) parts.push(h('span', { class: 'tl2' }));
    parts.push(h('span', { class: 'tn k-' + cvKey({ op: sh.op }) + (sh.op === 'run_workflow' ? ' blk' : '') + (sh.if ? ' cond' : ''), title: describeStep({ op: sh.op, params: {} }) }));
  });
  if (shape.length > 15) parts.push(h('span', { class: 'muted small', style: { marginLeft: '6px' } }, '+' + (shape.length - 15)));
  if (!shape.length) parts.push(h('span', { class: 'muted small', style: { marginLeft: '8px' } }, w.workflow_type === 'read' ? 'A saved report' : 'No steps yet'));
  return h('div', { class: 'thumb', 'aria-hidden': 'true' }, parts);
}

async function renderFlows(root, route) {
  const mine = S.renderId;
  await ensureStudio();
  if (mine !== S.renderId) return;
  const kinds = !!S.boot.caps.workflow_kind;
  if (!kinds) FV.kind = 'flow';
  const body = h('div'), chips = h('div', { class: 'seg', role: 'group', 'aria-label': 'Kind of flow' });
  const again = async () => { await ensureStudio(); draw(); };
  const isBlock = w => w.kind === 'block';
  const deleteBtn = w => w.is_active ? null : h('button', { class: 'btn sm danger', type: 'button', onclick: async e => {
    e.stopPropagation();
    if (!await confirmBox('Delete “' + w.name + '”? It is switched off already. Deleting takes it out of this list for good. A copy is kept in the history.', { ok: 'Delete', danger: true })) return;
    try { await api.del('/workflows/' + w.id); toast('Deleted', 'ok'); again(); } catch (x) { toast(x.message, 'bad'); }
  } }, icon('trash', 'sm'), 'Delete');
  const power = w => {
    const sw = switchEl(w.is_active, async v => { await api.post('/workflows/' + w.id + '/active', { is_active: v }); w.is_active = v; draw(); });
    sw.addEventListener('click', e => e.stopPropagation());
    return sw;
  };
  function card(w) {
    const roles = w.granted_roles || [], party = ((w.settings && w.settings.who_can_use) || []).map(r => PARTY_PLAIN[r] || r);
    const used = w.used_in || [];
    const meta = isBlock(w)
      ? (used.length ? h('div', { class: 'chips' }, used.slice(0, 4).map(u => h('a', { class: 'badge violet', href: '#/workflows?w=' + u.id, onclick: e => e.stopPropagation() }, u.name)), used.length > 4 ? h('span', { class: 'chip sunk' }, '+' + (used.length - 4)) : null)
        : h('div', { class: 'row small' }, badge('Not used yet', 'warn'), h('span', { class: 'muted' }, 'Safe to switch off and delete.')))
      : (roles.length || party.length ? h('div', { class: 'chips' }, roles.map(r => badge(r, 'brand')), party.map(r => h('span', { class: 'chip' }, r))) : h('span', { class: 'muted small' }, 'Nobody can use it yet'));
    const go_ = () => openWorkflow(w.id);
    return h('article', { class: 'card fcard' + (w.is_active ? '' : ' off'), tabindex: 0, role: 'link', 'aria-label': 'Open ' + w.name, onclick: go_, onkeydown: e => { if (e.key === 'Enter' && e.target === e.currentTarget) go_(); } },
      h('div', { class: 'row between flat', style: { alignItems: 'flex-start' } },
        h('div', { class: 'grow' }, h('div', { class: 'bold' }, w.name), h('div', { class: 'muted small', style: { overflowWrap: 'anywhere' } }, w.description || w.intent_key)),
        h('label', { class: 'row small flat', style: { gap: '6px' } }, w.is_active ? 'On' : 'Off', power(w))),
      flowThumb(w), meta,
      h('div', { class: 'row small muted between' },
        h('span', null, w.workflow_type === 'read' ? 'Report' : plural(w.step_count, 'step'), w.slash_command ? ' · /' + w.slash_command : '', ' · ' + (w.last_used ? 'used ' + ago(w.last_used) : 'not used yet')),
        deleteBtn(w)));
  }
  // the whole system as one drawing: how people start things, the flows, and the building blocks they share
  function flowMap() {
    const flows = ST.flows.filter(w => !isBlock(w)), blocks = ST.flows.filter(w => isBlock(w) && w.is_active);   // switched-off blocks stay out of the drawing
    const starts = [
      { key: 'say', label: 'Someone says something', list: flows.filter(w => w.kind !== 'case_action') },
      { key: 'cmd', label: 'Someone types a command', list: flows.filter(w => w.slash_command) },
      { key: 'btn', label: 'A button on a case', list: flows.filter(w => w.kind === 'case_action') },
    ].filter(s => s.list.length);
    const edges = [];
    starts.forEach(s => s.list.forEach(w => edges.push({ a: 's:' + s.key, b: 'f:' + w.id, cls: 'trg' })));
    flows.forEach(w => (w.uses || []).forEach(u => { const b = ST.byKey[u.intent_key]; if (b) edges.push({ a: 'f:' + w.id, b: 'f:' + b.id, cls: '' }); }));
    const node = (id, cls, title, sub, onclick) => h('button', { type: 'button', class: 'mnode' + cls, 'data-n': id, onclick }, h('div', { class: 'bold' }, title), h('div', { class: 'muted small' }, sub));
    const wrap = h('div', { class: 'mapwrap' }), svg = svgEl('svg', { class: 'medges' });
    const colA = h('div', { class: 'mcol' }, h('h4', null, 'How people start it'), starts.map(s => node('s:' + s.key, '', s.label, plural(s.list.length, 'flow'), null)));
    const colB = h('div', { class: 'mcol' }, h('h4', null, 'Flows'), flows.map(w => node('f:' + w.id, '', w.name, (w.workflow_type === 'read' ? 'Report' : plural(w.step_count, 'step')) + (w.is_active ? '' : ' · off'), () => openWorkflow(w.id))));
    const colC = h('div', { class: 'mcol' }, h('h4', null, 'Shared building blocks'), blocks.length ? blocks.map(b => node('f:' + b.id, ' blk' + (b.used_in.length ? '' : ' unused'), b.name, b.used_in.length ? 'Used by ' + plural(b.used_in.length, 'flow') : 'Not used yet', () => openWorkflow(b.id))) : h('div', { class: 'muted small' }, 'No building blocks yet.'));
    wrap.append(svg, colA, colB, colC);
    const paint = () => {
      if (!wrap.isConnected) return;
      const box = wrap.getBoundingClientRect(), pos = {};
      wrap.querySelectorAll('.mnode').forEach(n => { const r = n.getBoundingClientRect(); pos[n.dataset.n] = { l: r.left - box.left, r: r.right - box.left, y: (r.top + r.bottom) / 2 - box.top }; });
      fill(svg, edges.filter(e => pos[e.a] && pos[e.b]).map(e => { const A = pos[e.a], B = pos[e.b], dx = Math.max(30, (B.l - A.r) / 2); return svgEl('path', { class: e.cls, 'data-a': e.a, 'data-b': e.b, d: 'M' + A.r + ' ' + A.y + ' C' + (A.r + dx) + ' ' + A.y + ', ' + (B.l - dx) + ' ' + B.y + ', ' + B.l + ' ' + B.y }); }));
    };
    const light = id => {
      const on = new Set([id]);
      edges.forEach(e => { if (e.a === id) on.add(e.b); if (e.b === id) on.add(e.a); });
      wrap.querySelectorAll('.mnode').forEach(n => n.classList.toggle('dim', !!id && !on.has(n.dataset.n)));
      svg.querySelectorAll('path').forEach(p => { const hit = !!id && (p.dataset.a === id || p.dataset.b === id); p.classList.toggle('hl', hit); p.classList.toggle('dim', !!id && !hit); });
    };
    wrap.addEventListener('mouseover', e => { const n = e.target.closest('.mnode'); light(n ? n.dataset.n : null); });
    wrap.addEventListener('mouseleave', () => light(null));
    requestAnimationFrame(paint);
    window.addEventListener('resize', paint, { once: true });
    return h('div', { class: 'stack' }, notice('Hover a box to light up what it runs or what runs it. A building block used by many flows is a shared part: change it once and every flow with a line to it changes. Dashed boxes are not used by anything yet.'), wrap);
  }
  function drawChips() {
    const n = k => ST.flows.filter(w => k === 'block' ? isBlock(w) && (w.is_active || FV.showOff) : !isBlock(w)).length;   // switched-off blocks are only counted while they are shown
    const b = (k, label) => h('button', { type: 'button', class: FV.kind === k ? 'on' : '', onclick: () => { FV.kind = k; draw(); } }, label + ' (' + n(k) + ')');
    fill(chips, b('flow', 'Flows'), b('block', 'Building blocks'));
  }
  function draw() {
    const match = w => !FV.text || (w.name + ' ' + (w.description || '') + ' ' + w.intent_key).toLowerCase().includes(FV.text);
    drawChips(); chips.style.display = kinds && FV.view === 'cards' ? '' : 'none';
    newLabel.textContent = kinds && FV.kind === 'block' ? 'New building block' : 'New workflow';
    if (FV.view === 'map') { fill(body, flowMap()); return; }
    const ofKind = ST.flows.filter(w => !kinds || (FV.kind === 'block' ? isBlock(w) : !isBlock(w)));
    const parked = FV.kind === 'block' ? ofKind.filter(w => !w.is_active) : [];   // replaced or switched-off blocks: kept, but out of the way
    const list = ofKind.filter(match).filter(w => FV.showOff || !parked.includes(w));
    const hint = FV.kind === 'block' ? 'Small parts other flows are made from, such as Find a case. Change one and every flow that runs it changes.' : 'What people start from the menu, a button, or by typing a command.';
    const offToggle = parked.length ? h('label', { class: 'row small flat', style: { gap: '6px', cursor: 'pointer' } }, h('input', { type: 'checkbox', checked: !!FV.showOff, onchange: e => { FV.showOff = e.target.checked; draw(); } }), 'Show the ' + plural(parked.length, 'switched-off block') + ' too') : null;
    fill(body, list.length || parked.length ? h('div', { class: 'stack' }, h('div', { class: 'row between' }, h('div', { class: 'muted small' }, hint), offToggle), list.length ? h('div', { class: 'fcards' }, list.map(card)) : h('div', { class: 'card' }, empty('None match', '')))
      : h('div', { class: 'card' }, empty(FV.text ? 'None match' : 'None yet', FV.kind === 'block' ? 'Create one with “New building block”, or describe it to the assistant.' : 'Create one with “New workflow”.')));
  }
  const view = h('div', { class: 'seg', role: 'group', 'aria-label': 'How to show flows' },
    h('button', { type: 'button', class: FV.view === 'cards' ? 'on' : '', onclick: () => { FV.view = 'cards'; setView(); } }, icon('board', 'sm'), 'Cards'),
    h('button', { type: 'button', class: FV.view === 'map' ? 'on' : '', onclick: () => { FV.view = 'map'; setView(); } }, icon('map', 'sm'), 'Map'));
  const setView = () => { [...view.children].forEach((b, i) => b.classList.toggle('on', (i === 0) === (FV.view === 'cards'))); draw(); };
  const soon = (label, tip) => h('button', { class: 'tab', type: 'button', disabled: true, 'data-tip': tip }, label, h('span', { class: 'badge' }, 'later'));
  const newLabel = h('span', null, 'New workflow');
  const newBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => newWorkflowModal(kinds, kinds && FV.kind === 'block' ? 'block' : 'workflow') }, icon('plus', 'sm'), newLabel);
  fill(root,
    h('div', { class: 'tabs' }, h('a', { class: 'tab active', href: '#/workflows' }, 'Flows'), soon('Schedules', 'Start a flow at a set time. Comes with the next engine step.'), soon('Runs', 'Every time a flow ran, with its steps. Needs the engine to record each step.'), soon('Templates', 'Ready-made flows to start from.')),
    h('div', { class: 'filters', style: { justifyContent: 'space-between' } },
      h('div', { class: 'row' }, chips, h('div', { class: 'srch', style: { minWidth: '240px' } }, icon('search', 'sm'), search_())),
      h('div', { class: 'row' }, view, newBtn)),
    body);
  function search_() { return h('input', { class: 'input', type: 'search', placeholder: 'Search flows…', value: FV.text, oninput: debounce(e => { FV.text = e.target.value.trim().toLowerCase(); draw(); }, 200) }); }
  draw();
}

// ----- create: say what you are making, then describe it in chat, start blank, or copy one -----
const KIND_HELP = {
  workflow: 'People start it from the menu, a button or by typing a command.',
  block: 'One small step that other workflows run, such as Find a case. It does exactly one thing.',
  case_action: 'A short workflow that runs from a button on an existing case.',
};
const KIND_EXAMPLE = {
  workflow: 'For example: When someone says “close my complaint”, ask for the case number and a note, close the case and tell them.',
  block: 'For example: Add a note to a case. It needs the case number and the note text.',
  case_action: 'For example: A button that passes the case to another person and tells them.',
};
function newWorkflowModal(kinds, startKind) {
  const offered = kinds ? ['workflow', 'block', ...(S.boot.caps.cases ? ['case_action'] : [])] : ['workflow'];
  let kind = offered.includes(startKind) ? startKind : 'workflow', mode = 'chat', proposal = null, history = [], typed = '', typedName = '';
  const body = h('div', { class: 'stack' }), kindRow = h('div', { class: 'stack s8' }), seg = h('div', { class: 'row' });
  const m = modal({ title: kinds ? 'New workflow or building block' : 'New workflow', wide: true, body: h('div', null, kindRow, h('div', { style: { height: '14px' } }), seg, h('div', { style: { height: '12px' } }), body), actions: null });
  const modeBtn = (k, label) => h('button', { class: 'btn sm' + (mode === k ? ' primary' : ''), type: 'button', onclick: () => { mode = k; proposal = null; draw(); } }, label);
  async function created(r, made) {
    FV.kind = made === 'block' ? 'block' : 'flow';             // the Flows list opens on the right tab when you go back to it
    toast(made === 'block' ? 'Building block created.' : 'Created. It is switched off until you turn it on, and nobody can use it yet.', 'ok');
    m.close(); await ensureStudio(); openWorkflow(r.id);
  }
  function draw() {
    fill(kindRow, kinds ? [h('div', { class: 'seg', role: 'group', 'aria-label': 'What are you making?' }, offered.map(k => h('button', { type: 'button', class: kind === k ? 'on' : '', onclick: () => { if (kind === k) return; kind = k; proposal = null; history = []; draw(); } }, KIND_LABEL[k]))),
      h('div', { class: 'muted small' }, KIND_HELP[kind])] : null);
    fill(seg, modeBtn('chat', 'Describe it in chat'), modeBtn('blank', 'Start blank'), modeBtn('copy', 'Copy an existing one'));
    const err = h('div', { class: 'small', style: { color: 'var(--bad)' } });
    if (mode === 'chat') {
      const text = h('textarea', { rows: 4, placeholder: KIND_EXAMPLE[kind] });
      text.value = typed; text.addEventListener('input', () => { typed = text.value; });
      const go_ = h('button', { class: 'btn primary', type: 'button' }, proposal ? 'Draft it again' : 'Draft it');
      go_.addEventListener('click', async () => {
        if (text.value.trim().length < 5) { err.textContent = 'Say what it should do.'; return; }
        go_.disabled = true; err.textContent = ''; go_.textContent = 'Drafting…';
        try {
          const r = await api.post('/studio/chat', { message: text.value.trim(), kind, history });
          history = [{ role: 'user', content: text.value.trim() }, { role: 'assistant', content: r.reply }];
          proposal = r.proposal; draw();
          if (!r.proposal) body.prepend(notice((r.reply || '') + (r.problems && r.problems.length ? ' (' + r.problems.slice(0, 2).join(' ') + ')' : ''), 'warn'));
        } catch (e) { err.textContent = e.message; go_.disabled = false; go_.textContent = 'Draft it'; }
      });
      fill(body, field('What should it do?', text), h('div', { class: 'row' }, go_, err),
        proposal ? h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Drafted: ' + proposal.name, badge(KIND_LABEL[proposal.kind] || pretty(proposal.kind), 'violet')),
          h('div', { class: 'card-b stack' }, proposal.description ? h('div', null, proposal.description) : null,
            Object.keys(proposal.entity_schema).length ? h('div', null, h('b', null, 'Asks for: '), Object.keys(proposal.entity_schema).map(k => pretty(k)).join(', ')) : null,
            h('ol', { style: { margin: 0, paddingLeft: '20px' } }, proposal.steps.map(s => h('li', null, describeStep(s)))),
            proposal.warnings.length ? notice(proposal.warnings.join(' '), 'warn') : null,
            h('div', null, h('button', { class: 'btn primary', type: 'button', onclick: async e => { e.target.disabled = true; try { await created(await api.post('/workflows', { name: proposal.name, kind: proposal.kind, description: proposal.description, entity_schema: proposal.entity_schema, training_phrases: proposal.training_phrases, steps: proposal.steps }), proposal.kind); } catch (x) { toast(x.message, 'bad'); e.target.disabled = false; } } }, 'Create it and open the editor')))) : null);
    } else if (mode === 'blank') {
      const name = h('input', { type: 'text', placeholder: kind === 'block' ? 'e.g. Add a note to a case' : 'e.g. Close a complaint' });
      name.value = typedName; name.addEventListener('input', () => { typedName = name.value; });
      fill(body, field('Name', name), h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: async () => { if (name.value.trim().length < 2) { err.textContent = 'Give it a name.'; return; } try { await created(await api.post('/workflows', { name: name.value.trim(), kind }), kind); } catch (x) { err.textContent = x.message; } } }, 'Create'), err));
    } else {
      const pool = ST.flows.filter(w => w.workflow_type !== 'read' && (!kinds || (w.kind || 'workflow') === kind) && (kind !== 'block' || w.is_active));   // a copy is made of the same kind of thing; switched-off blocks (the old, replaced ones) are not offered
      const src = sel([['', pool.length ? 'Choose one…' : 'None of this kind yet'], ...pool.map(w => [w.id, w.name])], '');
      const name = h('input', { type: 'text', placeholder: 'Name of the copy' });
      src.addEventListener('change', () => { const w = ST.flows.find(x => x.id === src.value); if (w && !name.value) name.value = w.name + ' (copy)'; });
      fill(body, field('Copy which one?', src), field('Name of the copy', name), h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: async () => { if (!src.value) { err.textContent = 'Choose one to copy.'; return; } try { await created(await api.post('/workflows', { name: name.value.trim() || 'Copy', copy_from: src.value, kind }), kind); } catch (x) { err.textContent = x.message; } } }, 'Copy it'), err),
        h('div', { class: 'muted small' }, 'Reports and PDF documents cannot be copied here. ' + (kind === 'block' ? 'The copy is a new building block, switched on. Nothing runs it until you add it to a workflow.' : 'The copy is switched off and nobody can use it until you turn it on.')));
    }
  }
  draw();
}


"""
