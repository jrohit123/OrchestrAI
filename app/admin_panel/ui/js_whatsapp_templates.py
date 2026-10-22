JS = r"""
// ───────────────────────── Message templates ─────────────────────────
// WhatsApp message templates are the only messages the chat bot may start with a person who has not written for 24 hours. Meta checks
// each one before it can be used. This screen lists them with Meta's verdict, writes new ones in plain words, shows a bubble
// preview, sends them to Meta and says which approved one is the 24-hour reminder.

const TPL_STATUS = {
  APPROVED: ['Approved', 'ok'], PENDING: ['Waiting for Meta', 'warn'], IN_APPEAL: ['In appeal', 'warn'], REJECTED: ['Rejected', 'bad'],
  PAUSED: ['Paused by Meta', 'warn'], DISABLED: ['Switched off', 'bad'], FLAGGED: ['Flagged', 'warn'], DRAFT: ['Draft, not sent', ''],
  PENDING_DELETION: ['Being deleted', ''], LIMIT_EXCEEDED: ['Over the limit', 'warn'],
};
const TPL_WHY = {
  INCORRECT_CATEGORY: 'Meta thinks the kind is wrong. Try “marketing” if the message promotes something.',
  INVALID_FORMAT: 'Meta did not like the format. Check the blanks and their examples.',
  ABUSIVE_CONTENT: 'Meta found the words abusive or not allowed.',
  SCAM: 'Meta thinks the message looks like a scam.',
  TAG_CONTENT_MISMATCH: 'The words do not match the kind you chose.',
};
const TPL_KINDS = [
  ['UTILITY', 'Utility: about something that already happened (a ticket, an order)'],
  ['MARKETING', 'Marketing: offers, news, anything that promotes'],
  ['AUTHENTICATION', 'Authentication: one-time codes'],
];
const TPL_LANGS = [['en', 'English'], ['en_US', 'English (US)'], ['en_GB', 'English (UK)'], ['hi', 'Hindi'], ['mr', 'Marathi'], ['gu', 'Gujarati'], ['bn', 'Bengali'], ['ta', 'Tamil'], ['te', 'Telugu'], ['kn', 'Kannada'], ['ml', 'Malayalam'], ['pa', 'Punjabi'], ['ur', 'Urdu']];

function tplBlanks(text) {                // the numbers of the {{1}} blanks in the text, in order of appearance
  return [...String(text || '').matchAll(/\{\{\s*(\d+)\s*\}\}/g)].map(m => parseInt(m[1], 10));
}
function tplFill(text, examples) {        // the text with each blank replaced by its example (or left as {{n}})
  return String(text || '').replace(/\{\{\s*(\d+)\s*\}\}/g, (all, n) => { const e = (examples || [])[parseInt(n, 10) - 1]; return e ? e : all; });
}
function tplSlug(text) { return String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, ''); }
function tplEmpty() { return { name: '', language: 'en', category: 'UTILITY', header: null, body: '', examples: [], labels: [], footer: '', buttons: [] }; }
function tplStatus(t) { return TPL_STATUS[t.status] || [pretty(String(t.status || '').toLowerCase()), '']; }

// ---- the bubble ----
function tplBubble(spec) {
  const auth = spec.category === 'AUTHENTICATION';
  const bold = (t) => h('div', { class: 'tpl-h' }, t);
  const btn = (b) => h('div', { class: 'tpl-b' }, (b.kind === 'url' ? '↗ ' : b.kind === 'phone' ? '✆ ' : '↩ ') + (b.text || 'Button'));
  const body = auth ? '123456 is your verification code. (WhatsApp writes this message itself.)' : tplFill(spec.body, spec.examples) || 'Your message shows here.';
  return h('div', { class: 'wf-phone tpl-phone' },
    h('div', { class: 'wf-top' }, h('b', null, 'WhatsApp'), h('span', null, 'preview')),
    h('div', { class: 'wf-chat' }, h('div', { class: 'wf-bubble' },
      !auth && spec.header && spec.header.text ? bold(tplFill(spec.header.text, [spec.header.example])) : null,
      h('div', null, body),
      !auth && spec.footer ? h('div', { class: 'tpl-f' }, spec.footer) : null,
      h('div', { class: 'tpl-t' }, '10:42'),
      auth ? h('div', { class: 'tpl-b' }, '⧉ Copy code') : null,
      !auth ? (spec.buttons || []).map(btn) : null)));
}

// ---- the list ----
async function renderWhatsappTemplates(root) {
  const box = h('div', { class: 'stack s16' });
  root.append(box);
  const show = async () => {
    fill(box, h('div', { class: 'muted' }, 'Asking Meta for your templates…'));
    let d;
    try { d = await api.get('/whatsapp-templates'); } catch (e) { fill(box, errorBox(e, show)); return; }
    if (!d.account_known) { fill(box, notice('Meta’s number for your WhatsApp business account is needed first. Open the WhatsApp Forms tab and paste it once; it is used here too.', 'warn')); return; }
    const reasonOf = t => t.reason ? (TPL_WHY[t.reason] || pretty(String(t.reason).toLowerCase())) : '';
    const act = async (fn, ok) => { try { await fn(); if (ok) toast(ok, 'ok'); show(); } catch (e) { toast(e.message, 'bad'); } };
    const remove = async t => {
      if (!await confirmBox(t.source === 'draft' ? 'Delete the draft “' + t.name + '”?' : 'Delete “' + t.name + '” from Meta? Every language of it goes, and messages that use it stop working.', { ok: 'Delete', danger: true })) return;
      await act(() => t.source === 'draft' ? api.del('/whatsapp-templates/drafts/' + t.draft_id) : api.del('/whatsapp-templates/' + encodeURIComponent(t.name)), 'Deleted');
    };
    const useReminder = t => act(() => api.put('/whatsapp-templates/reminder', { name: t.name, language: t.language }), 'The chat bot will use it for the 24-hour reminder');
    const stopReminder = () => act(() => api.put('/whatsapp-templates/reminder', { name: null }), 'Stopped');
    const open = (t, asCopy) => tplEditor(box, d, t, asCopy, show);
    const reminder = d.reminder;
    fill(box,
      h('div', { class: 'row between' }, h('span', { class: 'muted small' }, 'Meta checks every template before it can be used. A verdict takes a few minutes, sometimes a day.'),
        h('span', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: show }, 'Refresh status'), h('button', { class: 'btn primary', type: 'button', onclick: () => open(null) }, 'New template'))),
      notice(reminder ? 'The 24-hour reminder: when a person’s WhatsApp is closed, the chat bot sends the template “' + reminder.name + '” (' + reminder.language + ') so they can open it again.' : 'No template is chosen for the 24-hour reminder. Pick an approved one without blanks with “Use for the 24-hour reminder”.', reminder ? null : 'warn'),
      reminder ? h('div', null, h('button', { class: 'btn sm', type: 'button', onclick: stopReminder }, 'Stop using it for the reminder')) : null,
      h('div', { class: 'card' }, d.templates.length ? table([
        { label: 'Template', render: t => h('div', null, h('b', null, t.name), h('div', { class: 'muted small' }, t.language + ' · ' + pretty(String(t.category || '').toLowerCase()))) },
        { label: 'Status', render: t => h('div', null, badge(tplStatus(t)[0], tplStatus(t)[1]), t.reminder ? badge('24-hour reminder', 'ok') : null, reasonOf(t) ? h('div', { class: 'small', style: { color: 'var(--bad)' } }, reasonOf(t)) : null) },
        { label: 'Message', render: t => h('span', { class: 'small' }, (tplFill(t.body, t.examples) || '').slice(0, 110)) },
        { label: '', render: t => h('span', { class: 'row' },
          t.source === 'draft' ? h('button', { class: 'btn sm', type: 'button', onclick: () => open(t) }, 'Edit') : h('button', { class: 'btn sm', type: 'button', onclick: () => open(t, true) }, 'Use as a start'),
          t.can_remind && !t.reminder ? h('button', { class: 'btn sm', type: 'button', onclick: () => useReminder(t) }, 'Use for the 24-hour reminder') : null,
          h('button', { class: 'btn sm danger', type: 'button', disabled: t.reminder, title: t.reminder ? 'The 24-hour reminder uses it' : null, onclick: () => remove(t) }, 'Delete')) },
      ], d.templates) : h('div', { class: 'card-b' }, empty('No templates yet', 'Press New template to write one.'))));
  };
  show();
}

// ---- one template ----
function tplEditor(box, d, start, asCopy, back) {
  const spec = Object.assign(tplEmpty(), JSON.parse(JSON.stringify(start || {})));
  if (asCopy) { spec.name = tplSlug(spec.name) + '_v2'; delete spec.id; }
  spec.examples = spec.examples || []; spec.labels = spec.labels || []; spec.buttons = spec.buttons || [];
  const preview = h('div'), blanksBox = h('div', { class: 'stack s8' }), buttonsBox = h('div', { class: 'stack s8' }), nameNote = h('div', { class: 'hint' });
  const lim = d.limits || {};
  const redraw = () => fill(preview, tplBubble(spec));
  const text = (get, set, props) => { const i = h('input', Object.assign({ type: 'text', value: get() || '' }, props || {})); i.addEventListener('input', () => { set(i.value); redraw(); }); return i; };
  const drawName = () => fill(nameNote, spec.name ? 'Saved as: ' + tplSlug(spec.name) : 'Letters, digits and underscores; spaces are turned into underscores.');
  const drawBlanks = () => {
    const nums = tplBlanks(spec.body);
    spec.examples.length = nums.length; spec.labels.length = nums.length;
    for (let i = 0; i < nums.length; i++) { if (spec.examples[i] === undefined) spec.examples[i] = ''; if (spec.labels[i] === undefined) spec.labels[i] = ''; }
    fill(blanksBox, nums.length ? h('div', { class: 'muted small' }, 'Each blank is filled in by the chat bot when it sends the message. Meta needs an example for each, to check the message.') : null,
      nums.map((n, i) => h('div', { class: 'wf-grid' },
        field('Blank {{' + n + '}} is for', text(() => spec.labels[i], v => { spec.labels[i] = v; }, { placeholder: 'For example customer name' })),
        field('Example for {{' + n + '}}', text(() => spec.examples[i], v => { spec.examples[i] = v; }, { placeholder: 'For example Asha' })))));
  };
  const drawButtons = () => fill(buttonsBox, spec.buttons.map((b, i) => h('div', { class: 'wfb-q' },
    h('div', { class: 'row between' }, h('b', null, { quick_reply: 'Quick reply', url: 'Link', phone: 'Phone call' }[b.kind]), h('button', { class: 'btn sm danger', type: 'button', onclick: () => { spec.buttons.splice(i, 1); drawButtons(); redraw(); } }, '✕')),
    field('Words on the button', text(() => b.text, v => { b.text = v; }, { maxlength: lim.button || 25 })),
    b.kind === 'url' ? field('Address (it may end with {{1}})', text(() => b.url, v => { b.url = v; }, { placeholder: 'https://example.com/track/{{1}}' })) : null,
    b.kind === 'url' ? field('Example for the end of the address (only if it has {{1}})', text(() => b.example, v => { b.example = v; })) : null,
    b.kind === 'phone' ? field('Phone number with country code', text(() => b.phone, v => { b.phone = v; }, { placeholder: '+919876543210' })) : null)));
  const addButton = sel([['', 'Add a button…'], ['quick_reply', 'Quick reply (one tap sends the words back)'], ['url', 'Link (opens a web page)'], ['phone', 'Phone call']], '', { 'aria-label': 'Add a button' });
  addButton.addEventListener('change', () => { if (addButton.value) { spec.buttons.push({ kind: addButton.value, text: '', url: '', example: '', phone: '' }); addButton.value = ''; drawButtons(); redraw(); } });
  const body = h('textarea', { rows: 6, maxlength: lim.body || 1024, 'aria-label': 'Message' }); body.value = spec.body || '';
  body.addEventListener('input', () => { spec.body = body.value; drawBlanks(); redraw(); });
  const addBlank = () => { const n = Math.max(0, ...tplBlanks(spec.body)) + 1; body.setRangeText('{{' + n + '}}', body.selectionStart, body.selectionEnd, 'end'); body.dispatchEvent(new Event('input')); body.focus(); };
  const headerText = text(() => spec.header && spec.header.text, v => { spec.header = Object.assign(spec.header || { example: '' }, { text: v }); }, { maxlength: lim.header || 60, placeholder: 'A short headline' });
  const headerEx = text(() => spec.header && spec.header.example, v => { spec.header = Object.assign(spec.header || { text: '' }, { example: v }); }, { placeholder: 'Example for {{1}} in the headline', 'aria-label': 'Example for the headline blank' });
  const kind = sel(TPL_KINDS, spec.category, { 'aria-label': 'Kind' });
  const lang = sel(TPL_LANGS.some(l => l[0] === spec.language) ? TPL_LANGS : [...TPL_LANGS, [spec.language, spec.language]], spec.language, { 'aria-label': 'Language' });
  const plain = h('div', { class: 'stack s12' });
  const drawKind = () => { plain.hidden = spec.category === 'AUTHENTICATION'; authNote.hidden = spec.category !== 'AUTHENTICATION'; };
  const authNote = notice('For authentication templates WhatsApp writes the message itself (a code and a Copy code button). Only the name and language are yours.', null);
  kind.addEventListener('change', () => { spec.category = kind.value; drawKind(); redraw(); });
  lang.addEventListener('change', () => { spec.language = lang.value; });
  const wire = () => {
    const out = JSON.parse(JSON.stringify(spec));
    out.header = out.header && String(out.header.text || '').trim() ? out.header : null;
    ['id', 'status', 'reason', 'source', 'draft_id', 'reminder', 'can_remind', 'extras'].forEach(k => delete out[k]);
    return out;
  };
  const save = async () => { try { await api.post('/whatsapp-templates/drafts', wire()); toast('Draft saved', 'ok'); back(); } catch (e) { toast(e.message, 'bad'); } };
  const send = async () => {
    if (!await confirmBox('Send “' + (tplSlug(spec.name) || 'this template') + '” to Meta for approval? Once sent it cannot be edited; to change it you make a new one.', { ok: 'Send for approval' })) return;
    try { const r = await api.post('/whatsapp-templates', wire()); toast('Sent. Meta says: ' + tplStatus(r)[0].toLowerCase() + '. Press Refresh status later.', 'ok'); back(); } catch (e) { toast(e.message, 'bad'); }
  };
  fill(plain,
    field('Headline (optional)', headerText, 'Plain words only. It may have one blank, written {{1}}.'),
    h('div', null, headerEx),
    field('Message', body, 'Write the words. Press “Add a blank” where the chat bot fills in a name, a number or a date.'),
    h('div', null, h('button', { class: 'btn sm', type: 'button', onclick: addBlank }, 'Add a blank')),
    blanksBox,
    field('Small print at the bottom (optional)', text(() => spec.footer, v => { spec.footer = v; }, { maxlength: lim.footer || 60 })),
    h('div', null, h('b', null, 'Buttons (optional)')), buttonsBox, addButton);
  fill(box,
    h('div', { class: 'row between' }, h('span', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: back }, '← Templates'), h('b', null, start && !asCopy ? 'Edit the draft' : 'New template')),
      h('span', { class: 'row' }, d.drafts_available ? h('button', { class: 'btn', type: 'button', onclick: save }, 'Save draft') : null, h('button', { class: 'btn primary', type: 'button', onclick: send }, 'Send for approval'))),
    asCopy ? notice('This is a copy of an existing template to start from. Give it a new name; the original stays as it is.', null) : null,
    h('div', { class: 'wf-edit' },
      h('div', { class: 'card' }, h('div', { class: 'card-b stack' },
        field('Name', text(() => spec.name, v => { spec.name = v; drawName(); }, { placeholder: 'For example ticket_update' }), null), nameNote,
        h('div', { class: 'wf-grid' }, field('Kind', kind), field('Language', lang)),
        authNote, plain)),
      h('div', { class: 'wf-side' }, h('b', null, 'How it looks'), preview)));
  drawName(); drawBlanks(); drawButtons(); drawKind(); redraw();
}
"""
