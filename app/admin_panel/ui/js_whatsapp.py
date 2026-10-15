JS = r"""
// ───────────────────────── WhatsApp Flows ─────────────────────────
// A list of the Flows in Meta; open one to edit its JSON, see it as a phone (drawn from the JSON itself, nothing fixed), save the
// draft, send a test to a phone, and publish. A published Flow cannot be changed: make a copy to change it.

// ---- the preview: draws whatever the JSON says ----
function wfExample(screen, key) {
  const d = screen && screen.data && screen.data[key];
  return d && d.__example__ !== undefined ? d.__example__ : undefined;
}
function wfValue(v, screen) {            // "${data.x}" becomes the example value of x
  if (typeof v !== 'string') return v;
  const m = v.match(/^\$\{data\.([^}]+)\}$/);
  if (m) { const e = wfExample(screen, m[1]); return e === undefined ? v : e; }
  return v.replace(/\$\{data\.([^}]+)\}/g, (all, k) => { const e = wfExample(screen, k); return e === undefined ? all : String(e); });
}
function wfText(v, screen) {
  const x = wfValue(v, screen);
  return Array.isArray(x) ? x.join(' ') : (x === undefined || x === null ? '' : String(x));
}
function wfChoices(node, screen) {
  const x = wfValue(node['data-source'], screen);
  return Array.isArray(x) ? x : [];
}
function wfPreview(flow, screenId, go, done) {
  const screen = (flow.screens || []).find(s => s.id === screenId) || (flow.screens || [])[0];
  if (!screen) return h('div', { class: 'wf-empty' }, 'No screen yet.');
  const q = (label, req, ctl, help) => h('div', { class: 'wf-q' }, label ? h('div', { class: 'wf-l' }, wfText(label, screen) + (req ? '' : ' (optional)')) : null, ctl, help ? h('div', { class: 'wf-h' }, wfText(help, screen)) : null);
  const act = (a) => () => {
    if (!a) return;
    if (a.name === 'navigate' && a.next && a.next.name) go(a.next.name);
    else if (a.name === 'complete') done(a.payload || {});
  };
  const draw = (n) => {
    if (!n || typeof n !== 'object') return null;
    switch (n.type) {
      case 'TextHeading': return h('div', { class: 'wf-th' }, wfText(n.text, screen));
      case 'TextSubheading': return h('div', { class: 'wf-ts' }, wfText(n.text, screen));
      case 'TextBody': return h('div', { class: 'wf-tb' }, wfText(n.text, screen));
      case 'TextCaption': return h('div', { class: 'wf-tc' }, wfText(n.text, screen));
      case 'RichText': return h('div', { class: 'wf-tb' }, wfText(n.text, screen));
      case 'TextInput': return q(n.label, n.required, h('div', { class: 'wf-in' }, h('span', { class: 'ph' }, '')), n['helper-text']);
      case 'TextArea': return q(n.label, n.required, h('div', { class: 'wf-in tall' }, ''), n['helper-text']);
      case 'Dropdown': { const c = wfChoices(n, screen); return q(n.label, n.required, h('div', { class: 'wf-in' }, h('span', null, c[0] ? wfText(c[0].title) : 'Choose'), h('span', null, '⌄')), n['helper-text'] || n.description); }
      case 'RadioButtonsGroup': case 'CheckboxGroup': case 'ChipsSelector': {
        const box = n.type === 'CheckboxGroup';
        return q(n.label, n.required, h('div', { class: 'wf-radios' }, wfChoices(n, screen).map((p, i) => h('div', { class: 'wf-radio' }, h('span', { class: 'dot' + (box ? ' sq' : '') + (i === 0 && !box ? ' on' : '') }), wfText(p.title)))), n['helper-text'] || n.description);
      }
      case 'DatePicker': case 'CalendarPicker': case 'TimePicker': return q(n.label, n.required, h('div', { class: 'wf-in' }, h('span', null, n.type === 'TimePicker' ? 'hh:mm' : 'dd/mm/yyyy'), h('span', null, '▾')), n['helper-text']);
      case 'PhotoPicker': case 'DocumentPicker': return q(n.label, true, h('div', { class: 'wf-photo' }, h('b', null, '＋ ' + (n.type === 'PhotoPicker' ? 'Add photos' : 'Add files')), n.description ? h('span', null, wfText(n.description, screen)) : null));
      case 'OptIn': return h('div', { class: 'wf-radio' }, h('span', { class: 'dot sq' }), wfText(n.label, screen));
      case 'EmbeddedLink': return h('div', { class: 'wf-link' }, wfText(n.text, screen));
      case 'Image': return h('div', { class: 'wf-img' }, n.src && String(n.src).length > 200 ? h('img', { src: 'data:image/png;base64,' + n.src, alt: '' }) : 'Image');
      case 'NavigationList': return h('div', { class: 'wf-nav' }, wfChoices({ 'data-source': n['list-items'] }, screen).map(it => {
        const mc = it['main-content'] || {};
        return h('div', { class: 'wf-item', role: 'button', tabindex: '0', onclick: act(it['on-click-action']) }, h('div', null, h('b', null, wfText(mc.title)), mc.description ? h('div', { class: 'wf-h' }, wfText(mc.description)) : null), h('span', null, '›'));
      }));
      case 'If': return h('div', null, (n.then || []).map(draw));
      case 'Switch': return h('div', null, Object.values(n.cases || {})[0] ? Object.values(n.cases)[0].map(draw) : null);
      case 'Footer': return null;
      default: return h('div', { class: 'wf-unk' }, n.type || 'unknown');
    }
  };
  const kids = (((screen.layout || {}).children) || []);
  const foot = kids.find(k => k && k.type === 'Footer');
  return h('div', { class: 'wf-sheet' },
    h('div', { class: 'wf-bar' }, h('span', { class: 'x' }, '✕'), h('b', null, wfText(screen.title, screen) || screen.id)),
    h('div', { class: 'wf-body' }, kids.map(draw)),
    foot ? h('div', { class: 'wf-foot' }, h('div', { class: 'wf-go', role: 'button', tabindex: '0', onclick: act(foot['on-click-action']) }, wfText(foot.label, screen))) : null,
    h('div', { class: 'wf-managed' }, 'Managed by the business.'));
}

// ---- the list ----
async function renderWhatsappFlows(root) {
  const box = h('div', { class: 'stack s16' });
  root.append(box);
  const show = async () => {
    fill(box, h('div', { class: 'muted' }, 'Asking Meta for your Flows…'));
    let d;
    try { d = await api.get('/whatsapp-flows'); } catch (e) { fill(box, errorBox(e, show)); return; }
    const open = id => wfEditor(box, id, show);
    const badgeOf = s => badge(pretty(String(s || '').toLowerCase()), s === 'PUBLISHED' ? 'ok' : (s === 'DRAFT' ? 'warn' : ''));
    const usedBy = id => Object.entries(d.used).filter(([, v]) => v === id).map(([k]) => badge('Chat bot ' + (k === 'menu' ? 'menu' : 'complaint form'), 'ok'));
    let accountBox = null;
    if (!d.account_known) {
      const inp = h('input', { type: 'text', inputmode: 'numeric', placeholder: 'For example 2213186559167420', 'aria-label': 'WhatsApp business account number' });
      accountBox = h('div', { class: 'card' }, h('div', { class: 'card-b stack' },
        notice('One thing is needed first: Meta’s number for your WhatsApp business account. It is in the address of WhatsApp Manager (the number after “asset_id=”). Paste it once.', 'warn'),
        h('div', { class: 'row' }, inp, h('button', { class: 'btn', type: 'button', onclick: async () => { try { await api.put('/whatsapp-flows/account', { account_id: inp.value }); toast('Saved', 'ok'); show(); } catch (e) { toast(e.message, 'bad'); } } }, 'Save number'))));
    }
    const create = () => {
      const name = h('input', { type: 'text', placeholder: 'For example complaint_form_v2', 'aria-label': 'Flow name' });
      const start = h('select', { 'aria-label': 'Start from' }, h('option', { value: 'sample' }, 'A sample test Flow (2 screens, ready to send)'), h('option', { value: 'blank' }, 'A blank screen'));
      modal({ title: 'Create a Flow', body: h('div', { class: 'stack' }, h('div', null, h('div', { class: 'muted small' }, 'Name'), name), h('div', null, h('div', { class: 'muted small' }, 'Start from'), start)),
        actions: [{ label: 'Cancel' }, { label: 'Create', primary: true, run: async () => {
          const r = await api.post('/whatsapp-flows', { name: name.value, start: start.value });
          toast('Created as a draft', 'ok'); open(r.id); } }] });
    };
    fill(box, accountBox,
      h('div', { class: 'row between' }, h('span', { class: 'muted small' }, 'These are the Flows in your WhatsApp business account.'), h('span', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: show }, 'Refresh'), h('button', { class: 'btn primary', type: 'button', onclick: create, disabled: !d.account_known }, 'Create Flow'))),
      h('div', { class: 'card' }, d.flows.length ? table([
        { label: 'Flow name', render: f => h('b', null, f.name) },
        { label: 'Flow ID', render: f => h('span', { class: 'muted' }, f.id) },
        { label: 'Status', render: f => badgeOf(f.status) },
        { label: 'Used by', render: f => h('span', { class: 'row' }, usedBy(f.id)) },
        { label: '', render: f => h('span', { class: 'row' }, h('button', { class: 'btn sm', type: 'button', onclick: () => open(f.id) }, 'Edit'),
          h('button', { class: 'btn sm danger', type: 'button', onclick: async () => {
            if (!await confirmBox(f.status === 'PUBLISHED' ? 'Retire “' + f.name + '”? Meta cannot delete a published Flow, so it is switched off for good. Messages already sent with it stop working.' : 'Delete the draft “' + f.name + '”?', { ok: f.status === 'PUBLISHED' ? 'Retire' : 'Delete', danger: true })) return;
            try { await api.del('/whatsapp-flows/' + f.id); toast('Done', 'ok'); show(); } catch (e) { toast(e.message, 'bad'); } } }, f.status === 'PUBLISHED' ? 'Retire' : 'Delete')) },
      ], d.flows) : h('div', { class: 'card-b' }, empty('No Flows yet', 'Press Create Flow to start from the sample.'))));
  };
  show();
}

// ---- one Flow ----
async function wfEditor(box, id, back) {
  fill(box, h('div', { class: 'muted' }, 'Opening the Flow…'));
  let d;
  try { d = await api.get('/whatsapp-flows/' + id); } catch (e) { fill(box, errorBox(e, () => wfEditor(box, id, back))); return; }
  const live = d.status === 'PUBLISHED';
  let savedText = d.json_text, errors = d.errors || [], screenId = null, flow = null, parseError = '', last = null;
  const area = h('textarea', { class: 'wf-code', spellcheck: 'false', 'aria-label': 'Flow JSON' });
  area.value = d.json_text;
  const gutter = h('pre', { class: 'wf-gut', 'aria-hidden': 'true' });
  const phone = h('div', { class: 'wf-phone' });
  const screenSel = h('select', { 'aria-label': 'Screen to preview' });
  const errBox = h('div', { class: 'wf-errs' });
  const stat = h('span', { class: 'row' });
  const result = h('div', { class: 'wf-result' });
  const builderBox = h('div', { class: 'wfb stack s12' });
  let mode = 'questions';
  const modeBtn = (key, text) => h('button', { type: 'button', 'aria-pressed': String(mode === key), onclick: () => { mode = key; drawMode(); } }, text);
  const modeBar = h('div', { class: 'seg sm' });
  const codeWrap = h('div', { class: 'wf-codewrap' }, gutter, area);
  const drawMode = () => {
    fill(modeBar, modeBtn('questions', 'Questions'), modeBtn('json', 'JSON (advanced)'));
    builderBox.hidden = mode !== 'questions'; codeWrap.hidden = mode !== 'json';
    if (mode === 'questions') drawBuilder();
  };
  // the builder reads the JSON fresh for every change and writes it back, so the two never drift apart
  const builderIo = {
    flow: () => { parse(); return parseError ? null : flow; },
    apply: (fn, redraw) => {
      parse(); if (parseError || !flow) return;
      fn(flow);
      area.value = JSON.stringify(flow, null, 2);
      lines(); parse(); drawErrors(); drawStat(); drawPhone();
      if (redraw) drawBuilder();
    },
  };
  const drawBuilder = () => wfbDraw(builderBox, builderIo);

  const lines = () => { gutter.textContent = Array.from({ length: area.value.split('\n').length }, (_, i) => i + 1).join('\n'); gutter.scrollTop = area.scrollTop; };
  const parse = () => {
    try { flow = JSON.parse(area.value); parseError = ''; } catch (e) { parseError = String(e.message || e); }
  };
  const drawErrors = () => {
    const mine = parseError ? [{ message: parseError }] : errors;
    fill(errBox, h('div', { class: 'wf-eh' }, 'Flow JSON errors ', badge(String(mine.length), mine.length ? 'bad' : 'ok')),
      mine.length ? mine.map(e => h('div', { class: 'wf-e' }, (e.line ? 'Line ' + e.line + (e.column ? ':' + e.column : '') + '  ' : '') + e.message)) : h('div', { class: 'muted small' }, 'Nothing wrong found. Save to let Meta check it.'));
  };
  const drawStat = () => {
    fill(stat, badge(pretty(String(d.status || '').toLowerCase()), live ? 'ok' : 'warn'),
      d.used_for.map(k => badge('Chat bot ' + (k === 'menu' ? 'menu' : 'complaint form'), 'ok')),
      area.value !== savedText ? badge('Changes not saved', 'warn') : null);
  };
  const drawPhone = () => {
    if (!flow || !Array.isArray(flow.screens)) { fill(phone, h('div', { class: 'wf-top' }, h('b', null, 'WhatsApp')), h('div', { class: 'wf-empty' }, parseError ? 'Fix the JSON to see the preview.' : 'Add a screens list to see the preview.')); return; }
    const ids = flow.screens.map(s => s.id);
    if (!ids.includes(screenId)) screenId = ids[0];
    fill(screenSel, ids.map(i => h('option', { value: i }, i))); screenSel.value = screenId;
    fill(phone, h('div', { class: 'wf-top' }, h('b', null, 'WhatsApp'), h('span', null, 'preview')),
      wfPreview(flow, screenId, n => { if (ids.includes(n)) { screenId = n; drawPhone(); } }, payload => { fill(result, h('b', null, 'The chat would receive:'), h('pre', null, JSON.stringify(payload, null, 2))); }));
  };
  screenSel.addEventListener('change', () => { screenId = screenSel.value; drawPhone(); });
  let timer = null;
  area.addEventListener('input', () => { lines(); drawStat(); clearTimeout(timer); timer = setTimeout(() => { parse(); drawErrors(); drawPhone(); if (mode === 'questions') drawBuilder(); }, 250); });
  area.addEventListener('scroll', () => { gutter.scrollTop = area.scrollTop; });
  area.addEventListener('keydown', e => { if (e.key === 'Tab') { e.preventDefault(); const s = area.selectionStart; area.setRangeText('  ', s, area.selectionEnd, 'end'); area.dispatchEvent(new Event('input')); } });

  const save = async (quiet) => {
    if (live) {   // Meta does not let a published Flow change: the edits become a new draft
      if (area.value === savedText) { if (!quiet) toast('Nothing has changed.', 'ok'); return true; }
      try { const r = await api.post('/whatsapp-flows/' + id + '/copy', { json_text: area.value }); toast('Saved as a new draft (the published one is unchanged until you publish this)', 'ok'); wfEditor(box, r.id, back); } catch (e) { toast(e.message, 'bad'); }
      return false;
    }
    try {
      const r = await api.put('/whatsapp-flows/' + id + '/json', { json_text: area.value });
      savedText = area.value; errors = r.errors || []; drawErrors(); drawStat();
      if (!quiet) toast(errors.length ? 'Saved as a draft, but Meta found ' + errors.length + ' problem' + (errors.length === 1 ? '' : 's') : 'Saved as a draft. Meta found no problems.', errors.length ? 'warn' : 'ok');
      return true;
    } catch (e) { toast(e.message, 'bad'); return false; }
  };
  const sendTest = async () => {
    if (live && area.value !== savedText) { toast('Press “Save as new draft” first, then send the draft.', 'bad'); return; }
    if (!await save(true)) return;
    parse(); if (parseError || !flow || !flow.screens) { toast('Fix the JSON first.', 'bad'); return; }
    const phoneIn = h('input', { type: 'tel', inputmode: 'numeric', placeholder: '919876543210', 'aria-label': 'Phone number with country code' });
    const msg = h('input', { type: 'text', value: 'Testing a WhatsApp Flow', maxlength: 1000 });
    const btn = h('input', { type: 'text', value: 'Open', maxlength: 20 });
    const scr = h('select', null, flow.screens.map(s => h('option', { value: s.id }, s.id)));
    const dataBox = h('textarea', { class: 'wf-code small', spellcheck: 'false', rows: 5 });
    const example = () => { const s = flow.screens.find(x => x.id === scr.value) || {}; const o = {}; Object.entries(s.data || {}).forEach(([k, v]) => { if (v && v.__example__ !== undefined) o[k] = v.__example__; }); dataBox.value = JSON.stringify(o, null, 2); };
    scr.addEventListener('change', example); example();
    modal({ wide: true, title: 'Send a test to a phone', body: h('div', { class: 'stack' },
      notice(live ? 'This Flow is published.' : 'This Flow is a draft: it is sent in test mode, only for testing.', null),
      h('div', null, h('div', { class: 'muted small' }, 'Phone number, with country code'), phoneIn),
      h('div', { class: 'wf-grid' }, h('div', null, h('div', { class: 'muted small' }, 'Message'), msg), h('div', null, h('div', { class: 'muted small' }, 'Button words'), btn)),
      h('div', null, h('div', { class: 'muted small' }, 'First screen'), scr),
      h('div', null, h('div', { class: 'muted small' }, 'Data for that screen (filled from the examples in the JSON)'), dataBox),
      h('div', { class: 'muted small' }, 'WhatsApp only delivers this if that phone wrote to the bot in the last 24 hours.')),
      actions: [{ label: 'Cancel' }, { label: 'Send test', primary: true, run: async () => {
        let data = {}; try { data = JSON.parse(dataBox.value || '{}'); } catch (e) { throw new Error('The data is not valid JSON.'); }
        await api.post('/whatsapp-flows/' + id + '/send-test', { phone: phoneIn.value, message: msg.value, button: btn.value, screen: scr.value, data });
        toast('Sent. Check the phone.', 'ok'); } }] });
  };
  const publish = async () => {
    if (!await save(true)) return;
    if (errors.length) { toast('Fix the errors first. Meta will not publish a Flow with problems.', 'bad'); return; }
    if (!await confirmBox('Publish this Flow? After this it cannot be changed (you can make a copy and change that).', { ok: 'Publish' })) return;
    try { await api.post('/whatsapp-flows/' + id + '/publish'); toast('Published', 'ok'); wfEditor(box, id, back); } catch (e) { toast(e.message, 'bad'); }
  };
  const use = (kind, word) => async () => {
    if (!await confirmBox('Make the chat bot use this Flow for its ' + word + '? People get it from the next message on.', { ok: 'Use it' })) return;
    try { await api.put('/whatsapp-flows/use', { kind, flow_id: id }); toast('Done', 'ok'); wfEditor(box, id, back); } catch (e) { toast(e.message, 'bad'); }
  };
  const remove = async () => {
    if (!await confirmBox(live ? 'Retire this published Flow? Messages already sent with it stop working.' : 'Delete this draft?', { ok: live ? 'Retire' : 'Delete', danger: true })) return;
    try { await api.del('/whatsapp-flows/' + id); toast('Done', 'ok'); back(); } catch (e) { toast(e.message, 'bad'); }
  };
  const format = () => { try { area.value = JSON.stringify(JSON.parse(area.value), null, 2); area.dispatchEvent(new Event('input')); } catch (e) { toast('Not valid JSON yet.', 'bad'); } };

  const top = h('div', { class: 'row between' },
    h('span', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: back }, '← Flows'), h('b', null, d.name), h('span', { class: 'muted small' }, id), stat),
    h('span', { class: 'row' },
      h('button', { class: 'btn', type: 'button', onclick: () => save(false) }, live ? 'Save as new draft' : 'Save'),
      h('button', { class: 'btn', type: 'button', onclick: sendTest }, 'Send test'),
      live ? null : h('button', { class: 'btn primary', type: 'button', onclick: publish }, 'Publish'),
      h('button', { class: 'btn', type: 'button', 'aria-haspopup': 'menu', onclick: e => {
        const items = [
          live ? { label: 'Use as the chat bot’s menu', run: use('menu', 'menu') } : null,
          live ? { label: 'Use as the chat bot’s complaint form', run: use('complaint', 'complaint form') } : null,
          { label: 'Tidy the JSON', run: format },
          d.preview_url ? { label: 'Open Meta’s own preview', run: () => window.open(d.preview_url, '_blank', 'noopener') } : null,
        ].filter(Boolean);
        openPop(e.currentTarget, h('div', { class: 'wf-menu' }, items.map(it => h('button', { class: 'btn ghost', type: 'button', onclick: () => { closePop(); it.run(); } }, it.label))), { width: 260, align: 'right' });
      } }, '⋯'),
      h('button', { class: 'btn danger', type: 'button', onclick: remove }, live ? 'Retire' : 'Delete')));
  fill(box, top,
    live ? notice('This Flow is published. Meta never changes a published Flow, so your edits are saved as a new draft (press Save as new draft). Publish that draft, then use it as the chat bot’s menu or form from the ⋯ menu.', null) : null,
    h('div', { class: 'wf-edit' },
      h('div', { class: 'card' }, h('div', { class: 'card-h row between' }, h('span', null, 'Editor'), modeBar), builderBox, codeWrap, errBox),
      h('div', { class: 'wf-side' }, h('div', { class: 'row between', style: { marginBottom: '8px' } }, h('b', null, 'Preview'), screenSel), phone, result)));
  lines(); parse(); drawErrors(); drawStat(); drawPhone(); drawMode();
}
"""
