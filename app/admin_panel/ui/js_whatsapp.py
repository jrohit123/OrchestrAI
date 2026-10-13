JS = r"""
// ───────────────────────── WhatsApp form ─────────────────────────
// Left: the questions of the complaint form, to edit. Right: a phone showing how the form looks in WhatsApp, redrawn on every
// keystroke. "Publish to WhatsApp" makes the form live without opening Meta. What the Category and urgency lists offer comes from
// the kinds of complaint and the complaint flow, so the preview only shows them.
async function renderWhatsappForm(root) {
  const d = await api.get('/whatsapp-form');
  const L = d.limits;
  let saved = JSON.stringify(d.form);          // what is saved in the dashboard
  let live = d.published ? JSON.stringify(d.published) : null;   // what was last published from here
  const st = JSON.parse(saved);
  let sheet = true;                            // the form panel is open in the preview
  const phone = h('div', { class: 'wf-phone' });
  const status = h('div', { class: 'wf-status' });
  const listBox = h('div', { class: 'stack' });
  const NAMES = { location: 'Where (tower and flat)', problem: 'What is wrong', category: 'Kind of complaint (a list)', priority: 'How urgent (buttons)', photos: 'Photos' };
  const lab = (f) => f.label + (f.required ? '' : ' (optional)');

  function drawPhone() {
    const rows = st.fields.filter(f => f.show).map(f => {
      const t = f.name;
      let ctl;
      if (t === 'category') ctl = h('div', { class: 'wf-in sel' }, h('span', null, d.choices.categories[0] || 'Choose'), h('span', null, '⌄'));
      else if (t === 'priority') ctl = h('div', { class: 'wf-radios' }, d.choices.priorities.map((p, i) => h('div', { class: 'wf-radio' }, h('span', { class: 'dot' + (i === 0 ? ' on' : '') }), p)));
      else if (t === 'photos') ctl = h('div', { class: 'wf-photo' }, h('b', null, '＋ ' + 'Add photos'), h('span', null, 'Up to ' + st.photos_max + ' photo' + (st.photos_max === 1 ? '' : 's')));
      else ctl = h('div', { class: 'wf-in' + (t === 'problem' ? ' tall' : '') }, h('span', { class: 'ph' }, ''));
      return h('div', { class: 'wf-q' }, t === 'photos' ? h('div', { class: 'wf-l' }, f.label + (f.required ? '' : ' (optional)')) : h('div', { class: 'wf-l' }, lab(f)), ctl, f.help && (t === 'location' || t === 'problem') ? h('div', { class: 'wf-h' }, f.help) : null);
    });
    const chat = h('div', { class: 'wf-chat' },
      h('div', { class: 'wf-bubble' }, h('div', null, d.intro), h('div', { class: 'wf-open', role: 'button', tabindex: '0', onclick: () => { sheet = true; drawPhone(); } }, '📝 ' + d.button)));
    fill(phone,
      h('div', { class: 'wf-top' }, h('b', null, 'WhatsApp'), h('span', null, 'chat bot')),
      chat,
      sheet ? h('div', { class: 'wf-sheet' },
        h('div', { class: 'wf-bar' }, h('span', { role: 'button', tabindex: '0', class: 'x', onclick: () => { sheet = false; drawPhone(); } }, '✕'), h('b', null, st.title)),
        h('div', { class: 'wf-body' }, rows),
        h('div', { class: 'wf-foot' }, h('div', { class: 'wf-go' }, st.button))) : null);
  }

  function drawStatus() {
    const now = JSON.stringify(st);
    const dirty = now !== saved;
    const unpub = now !== live;
    fill(status,
      h('span', { class: 'badge ' + (d.flow_id ? 'ok' : '') }, d.flow_id ? 'In use on WhatsApp' + (d.flow_status ? ' · ' + pretty(String(d.flow_status).toLowerCase()) : '') : 'Not switched on'),
      dirty ? badge('Changes not saved', 'warn') : (unpub ? badge('Saved, not published yet', 'warn') : badge('Published, up to date', 'ok')));
  }

  function field(f, i) {
    const must = L.always.includes(f.name);
    const redraw = () => { drawPhone(); drawStatus(); };
    const label = h('input', { type: 'text', value: f.label, maxlength: L.label[f.name], 'aria-label': 'Words for ' + NAMES[f.name] });
    label.addEventListener('input', () => { f.label = label.value; redraw(); });
    const showSw = sw(f.show, v => { f.show = v; drawList(); redraw(); }, 'Show ' + NAMES[f.name], must);
    const reqSw = sw(f.required, v => { f.required = v; redraw(); }, 'Required: ' + NAMES[f.name], must);
    const help = (f.name === 'location' || f.name === 'problem') ? h('input', { type: 'text', value: f.help, maxlength: L.help, placeholder: 'A hint under the box', 'aria-label': 'Hint for ' + NAMES[f.name] }) : null;
    if (help) help.addEventListener('input', () => { f.help = help.value; redraw(); });
    const move = (by) => { const j = i + by; if (j < 0 || j >= st.fields.length) return; [st.fields[i], st.fields[j]] = [st.fields[j], st.fields[i]]; refresh(); };
    return h('div', { class: 'wf-field' + (f.show ? '' : ' off') },
      h('div', { class: 'row between' }, h('b', null, NAMES[f.name]), h('span', { class: 'row' },
        h('button', { class: 'btn sm ghost', type: 'button', disabled: i === 0, 'aria-label': 'Move up', onclick: () => move(-1) }, '↑'),
        h('button', { class: 'btn sm ghost', type: 'button', disabled: i === st.fields.length - 1, 'aria-label': 'Move down', onclick: () => move(1) }, '↓'))),
      f.show ? h('div', { class: 'wf-grid' }, h('div', null, h('div', { class: 'muted small' }, 'Words people see'), label), help ? h('div', null, h('div', { class: 'muted small' }, 'Hint'), help) : null) : null,
      h('div', { class: 'row' },
        h('label', { class: 'row small' }, showSw, ' Show it'), f.show ? h('label', { class: 'row small' }, reqSw, ' Required') : null,
        must ? h('span', { class: 'muted small' }, 'The chat bot needs this one.') : null));
  }
  function sw(on, onChange, name, locked) {
    const input = h('input', { type: 'checkbox', role: 'switch', 'aria-label': name, checked: !!on, disabled: !!locked });
    input.addEventListener('change', () => onChange(input.checked));
    return h('label', { class: 'switch' }, input, h('span'));
  }
  function drawList() { fill(listBox, st.fields.map(field)); }
  function refresh() { drawList(); drawPhone(); drawStatus(); }

  const title = h('input', { type: 'text', value: st.title, maxlength: L.title, 'aria-label': 'Form title' });
  title.addEventListener('input', () => { st.title = title.value; drawPhone(); drawStatus(); });
  const button = h('input', { type: 'text', value: st.button, maxlength: L.button, 'aria-label': 'Submit button words' });
  button.addEventListener('input', () => { st.button = button.value; drawPhone(); drawStatus(); });
  const photos = h('input', { type: 'number', min: 1, max: L.photos, value: String(st.photos_max), 'aria-label': 'Most photos' });
  photos.addEventListener('input', () => { st.photos_max = Math.max(1, Math.min(L.photos, parseInt(photos.value, 10) || 1)); drawPhone(); drawStatus(); });

  const body = () => ({ title: st.title.trim(), button: st.button.trim(), photos_max: st.photos_max, fields: st.fields });
  const saveBtn = h('button', { class: 'btn', type: 'button' }, 'Save');
  const pubBtn = h('button', { class: 'btn primary', type: 'button' }, 'Publish to WhatsApp');
  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    try { const r = await api.put('/whatsapp-form', body()); saved = JSON.stringify(r.form); toast('Saved. People still see the published form until you publish.', 'ok'); drawStatus(); }
    catch (e) { toast(e.message, 'bad'); } finally { saveBtn.disabled = false; }
  });
  pubBtn.addEventListener('click', async () => {
    if (!await confirmBox('Make this the form people get on WhatsApp now? The old form is switched off a moment later.', { ok: 'Publish' })) return;
    pubBtn.disabled = true; pubBtn.textContent = 'Publishing…';
    try {
      const r = await api.post('/whatsapp-form/publish', body());
      saved = live = JSON.stringify(st); d.flow_id = r.flow_id; d.flow_status = 'PUBLISHED';
      toast('Published. New complaints on WhatsApp use this form.', 'ok'); drawStatus();
    } catch (e) { toast(e.message, 'bad'); } finally { pubBtn.disabled = false; pubBtn.textContent = 'Publish to WhatsApp'; }
  });

  let account = null;
  if (!d.account_known) {
    const box = h('input', { type: 'text', inputmode: 'numeric', placeholder: 'For example 2213186559167420', 'aria-label': 'WhatsApp business account number' });
    account = h('div', { class: 'card' }, h('div', { class: 'card-b stack' },
      notice('One thing is needed before you can publish: Meta’s number for your WhatsApp business account. It is in the address of WhatsApp Manager, after “business_id=…&asset_id=”. Paste it once.', 'warn'),
      h('div', { class: 'row' }, box, h('button', { class: 'btn', type: 'button', onclick: async () => {
        try { await api.put('/whatsapp-form/account', { account_id: box.value }); toast('Saved', 'ok'); account.remove(); } catch (e) { toast(e.message, 'bad'); } } }, 'Save number'))));
  }

  const editor = h('div', { class: 'stack s16' },
    account,
    h('div', { class: 'card' }, h('div', { class: 'card-b stack' },
      h('div', { class: 'row between' }, status, h('span', { class: 'row' }, saveBtn, pubBtn)),
      h('div', { class: 'wf-grid' }, h('div', null, h('div', { class: 'muted small' }, 'Title at the top of the form'), title), h('div', null, h('div', { class: 'muted small' }, 'Words on the submit button'), button)),
      h('div', { class: 'row' }, h('span', { class: 'muted small' }, 'Most photos in one complaint'), photos))),
    h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Questions, in the order people see them'), h('div', { class: 'card-b' }, listBox)),
    notice('The Category list comes from Case rules → Kinds of complaint, and the urgency buttons from the complaint flow, so they are not typed here. WhatsApp adds “(optional)” by itself to every question that is not required.', null));
  root.append(h('div', { class: 'wf-wrap' }, editor, h('div', { class: 'wf-side' }, h('div', { class: 'muted small', style: { marginBottom: '8px' } }, 'How it looks in WhatsApp'), phone)));
  refresh();
}
"""
