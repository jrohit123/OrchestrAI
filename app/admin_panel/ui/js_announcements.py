JS = r"""
// ───────────────────────── Announcements ─────────────────────────
// One message to many people: write it, tick who gets it (the server says exactly who that is and how each person
// is reached), see what they will see, send now or later; then what happened to each person.
const ANN_HOW = {
  whatsapp: ['💬', 'WhatsApp, now', 'They wrote to the chat bot in the last 24 hours, so it arrives at once.'],
  whatsapp_closed: ['⏳', 'WhatsApp, after one tap', 'Quiet for more than 24 hours: they first get your approved WhatsApp template; it arrives when they tap its button or write.'],
  telegram: ['✈️', 'Telegram', 'Arrives at once.'],
  email: ['✉️', 'Email', 'No WhatsApp number on file.'],
  none: ['⚠️', 'Cannot be reached', 'No number and no email on file.'],
};
const ANN_STATE = {
  waiting: ['Waiting', ''], sending: ['Sending…', 'info'], kept: ['Waiting for them to open WhatsApp', 'warn'],
  sent: ['Sent', 'info'], emailed: ['Emailed', 'info'], delivered: ['Delivered', 'info'], read: ['Read', 'ok'],
  got_it: ['Tapped Got it', 'ok'], failed: ['Not reached', 'bad'],
};
const ANN_STATUS = { planned: ['Planned', 'info'], sending: ['Sending', 'warn'], sent: ['Sent', 'ok'], cancelled: ['Cancelled', ''] };

function annFirst(name) { return String(name || '').split(' ')[0] || name || ''; }
function waHtml(text) {   // WhatsApp's *bold* and _italic_, and line breaks
  return h('span', { class: 'ann-wa' }, String(text).split('\n').map((line, i) => [i ? h('br') : null,
    line.split(/(\*[^*\n]+\*|_[^_\n]+_)/g).map(p => /^\*[^*]+\*$/.test(p) ? h('b', null, p.slice(1, -1)) : /^_[^_]+_$/.test(p) ? h('i', null, p.slice(1, -1)) : p)]));
}
function annText(st, setup, name) {
  const parts = [];
  if (st.greet) parts.push(setup.texts.greeting.replace('{first_name}', annFirst(name)));
  if (st.title.trim()) parts.push('*' + st.title.trim() + '*');
  parts.push(st.body.trim() || '(your message)');
  parts.push(setup.texts.sign_off);
  return parts.join('\n\n');
}

async function renderAnnouncements(root, route) {
  if (route.q.id) return annReport(root, route.q.id);
  if (route.q.new) return annCompose(root);
  return annList(root);
}

// ----- the list -----
async function annList(root) {
  const mine = S.renderId;
  setTopAction({ label: 'New announcement', icon: 'megaphone', run: () => go('announcements', '', { new: 1 }) });
  const [d, setup] = await Promise.all([api.get('/announcements'), api.get('/announcements/setup')]);
  if (mine !== S.renderId) return;
  if (!setup.linked.people) root.append(notice(h('span', null, h('b', null, 'Nobody is linked to a flat yet. '), 'Announcements choose people by their flat (owner or tenant, lives here or not). Go to ', h('a', { href: href('people') }, 'People'), ', press “Import from file” and upload your list with the Wing, Flat, Relation, Primary member and Lives here columns.'), 'warn'));
  if (!d.rows.length) {
    root.append(h('div', { class: 'card' }, h('div', { class: 'card-b' }, empty('No announcements yet', 'Send one message to many people at once: everyone who lives here, only tenants, or the AGM minutes to every primary member.'),
      h('div', { class: 'row', style: { justifyContent: 'center' } }, h('button', { class: 'btn primary', type: 'button', onclick: () => go('announcements', '', { new: 1 }) }, icon('megaphone', 'sm'), 'Write an announcement')))));
    return;
  }
  const total = c => Object.values(c || {}).reduce((a, n) => a + n, 0);
  const seen = c => (c.read || 0) + (c.got_it || 0);
  root.append(h('div', { class: 'card' }, table([
    { label: 'When', render: a => h('div', null, a.status === 'planned' ? h('div', null, 'Goes ' + fmtDT(a.send_at)) : fmtDT(a.started_at || a.send_at), h('div', { class: 'muted small' }, a.created_by ? String(a.created_by).replace(/^dashboard · /, '') : '')) },
    { label: 'Message', cls: 'wide', render: a => h('div', null, h('b', null, a.title || String(a.body).split('\n')[0].slice(0, 60)), a.file_name ? h('span', { class: 'muted small' }, '  📎 ' + a.file_name) : null, h('div', { class: 'muted small' }, a.audience_name || a.audience_text)) },
    { label: 'People', render: a => a.status === 'planned' ? h('span', { class: 'muted' }, 'when it goes') : String(total(a.counts)) },
    { label: 'Seen', render: a => a.status === 'planned' || !total(a.counts) ? h('span', { class: 'muted' }, '—') : h('span', null, seen(a.counts) + ' read', (a.counts.kept ? h('div', { class: 'muted small' }, a.counts.kept + ' waiting to open WhatsApp') : null), (a.counts.failed ? h('div', { class: 'small', style: { color: 'var(--t-bad)' } }, a.counts.failed + ' not reached') : null)) },
    { label: '', render: a => badge(...(ANN_STATUS[a.status] || [a.status])) },
  ], d.rows, { onRow: a => go('announcements', '', { id: a.id }) })));
}

// ----- write and choose -----
async function annCompose(root) {
  const mine = S.renderId;
  const setup = await api.get('/announcements/setup');
  if (mine !== S.renderId) return;
  setTopAction(null);
  const allRels = setup.relations.map(r => r[0]);
  const first = setup.audiences[0];
  const st = {
    title: '', body: '', greet: true, file: null, mode: 'now', when: '',
    filters: first ? JSON.parse(JSON.stringify(first.filters)) : { by_flat: true, lives: ['here'], relations: allRels, primary: 'any', wings: [], roles: [] },
    audience: first ? first.id : '', preview: null, pick: null, showLeft: false,
  };
  st.filters.by_flat = st.filters.by_flat !== false;
  st.filters.roles = st.filters.roles || []; st.filters.wings = st.filters.wings || [];
  if (!setup.linked.people) root.append(notice(h('span', null, h('b', null, 'Nobody is linked to a flat yet, '), 'so choosing by flat finds nobody. Import your list on ', h('a', { href: href('people') }, 'People'), ' first, or choose by role below.'), 'warn'));

  // left: write + who; right: what they see + send
  const left = h('div', { class: 'stack s16' }), right = h('div', { class: 'stack s16 ann-side' });
  root.append(h('div', { class: 'ann-grid' }, left, right));

  // 1. write
  const title = h('input', { type: 'text', maxlength: 120, placeholder: 'e.g. Flag hoisting' });
  const body = h('textarea', { rows: 6, maxlength: 3000, placeholder: 'Type the announcement…' });
  const count = h('span', { class: 'muted small' });
  const greet = h('input', { type: 'checkbox', checked: true });
  const fileIn = h('input', { type: 'file', accept: '.pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx', class: 'hidden' });
  const fileLine = h('span', { class: 'small' });
  const drawFile = () => fill(fileLine, st.file ? [h('span', null, '📎 ' + st.file.name + ' '), h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { st.file = null; drawFile(); drawPhone(); } }, 'Remove')] : h('span', { class: 'muted' }, 'No file'));
  fileIn.addEventListener('change', async () => {
    const f = fileIn.files[0]; fileIn.value = '';
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) { toast('The file is too big (8 MB at most).', 'bad'); return; }
    const bytes = new Uint8Array(await f.arrayBuffer());
    let bin = ''; for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    st.file = { name: f.name, type: f.type || 'application/octet-stream', b64: btoa(bin) };
    drawFile(); drawPhone();
  });
  const onText = () => { st.title = title.value; st.body = body.value; fill(count, body.value.length + ' / 3000'); drawPhone(); drawSend(); };
  title.addEventListener('input', onText); body.addEventListener('input', onText);
  greet.addEventListener('change', () => { st.greet = greet.checked; drawPhone(); });
  left.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, '1. Write the message'), h('div', { class: 'card-b stack' },
    field('Heading (optional)', title), field('Message', body, h('span', null, 'Put *stars* around words to make them bold on WhatsApp. ', count)),
    h('div', { class: 'row' }, h('label', { class: 'row small ann-tickline' }, greet, h('span', null, 'Start with “' + setup.texts.greeting.replace('{first_name}', 'first name') + '”')),
      h('span', { class: 'sp' }), h('label', { class: 'btn sm' }, icon('plus', 'xs'), 'Attach a file', fileIn), fileLine))));
  drawFile();

  // 2. who gets it
  const choices = h('div', { class: 'ann-choices' });
  const ticks = h('div', { class: 'stack s8' });
  const sentence = h('div', { class: 'ann-sentence' });
  const big = h('div', { class: 'ann-count' }), sub = h('div', { class: 'muted small' });
  const chans = h('div', { class: 'stack s8' });
  const list = h('div'), leftBtn = h('button', { class: 'btn sm ghost', type: 'button' }), leftList = h('div');
  left.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, '2. Who gets it'), h('div', { class: 'card-b stack' },
    h('div', { class: 'muted small' }, 'Pick a ready choice, or change the ticks.'), choices, ticks,
    h('div', { class: 'notice info' }, sentence),
    h('div', { class: 'row' }, h('button', { class: 'btn sm ghost', type: 'button', onclick: () => saveChoice() }, 'Keep these ticks as a ready choice…')))));
  left.append(h('div', { class: 'card' }, h('div', { class: 'card-b stack' }, h('div', null, big, sub), chans, h('div', null, h('b', null, 'Who gets it')), list, h('div', null, leftBtn), leftList)));
  leftBtn.addEventListener('click', () => { st.showLeft = !st.showLeft; drawPeople(); });

  const same = (a, b) => JSON.stringify(norm(a)) === JSON.stringify(norm(b));
  const norm = f => ({ by_flat: f.by_flat !== false, lives: [...(f.lives || [])].sort(), relations: [...(f.relations || [])].sort(), primary: f.primary || 'any', wings: [...(f.wings || [])].sort(), roles: [...(f.roles || [])].sort() });
  function drawChoices() {
    const hit = setup.audiences.find(a => same(a.filters, st.filters));
    st.audience = hit ? hit.id : '';
    fill(choices, setup.audiences.map(a => h('span', { class: 'ann-choice' + (a.id === st.audience ? ' on' : '') },
      h('button', { type: 'button', onclick: () => { st.filters = { ...JSON.parse(JSON.stringify(a.filters)), by_flat: a.filters.by_flat !== false, roles: a.filters.roles || [], wings: a.filters.wings || [] }; changed(); } },
        h('b', null, a.name), a.hint ? h('span', { class: 'muted small' }, a.hint) : null),
      a.own ? h('button', { class: 'x', type: 'button', 'aria-label': 'Remove the ready choice ' + a.name, onclick: async () => {
        if (!await confirmBox('Remove the ready choice “' + a.name + '”? Announcements already sent are not changed.', { ok: 'Remove', danger: true })) return;
        try { await api.del('/announcement-audiences/' + a.id); setup.audiences = setup.audiences.filter(x => x.id !== a.id); drawChoices(); toast('Removed', 'ok'); } catch (e) { toast(e.message, 'bad'); } } }, '×') : null)));
  }
  const tick = (label, on, set, kind) => {
    const cb = h('input', { type: kind || 'checkbox', checked: !!on });
    cb.addEventListener('change', () => { set(cb.checked); changed(); });
    return h('label', { class: 'ann-tick' + (on ? ' on' : '') }, cb, h('span', null, label));
  };
  const toggle = (arr, v, yes) => yes ? [...new Set([...arr, v])] : arr.filter(x => x !== v);
  function drawTicks() {
    const f = st.filters;
    const byRole = !f.by_flat;
    const rows = [];
    rows.push(h('div', { class: 'row' }, tick('By flat', !byRole, v => { if (v) f.by_flat = true; }, 'radio'), tick('Only by role (flats do not matter)', byRole, v => { if (v) f.by_flat = false; }, 'radio')));
    if (!byRole) {
      rows.push(h('div', { class: 'ann-group' }, h('span', { class: 'ann-lbl' }, 'Living'),
        tick('Lives here', f.lives.includes('here'), v => { f.lives = toggle(f.lives, 'here', v); }),
        tick('Lives elsewhere', f.lives.includes('away'), v => { f.lives = toggle(f.lives, 'away', v); })));
      rows.push(h('div', { class: 'ann-group' }, h('span', { class: 'ann-lbl' }, 'Relation to the flat'),
        setup.relations.map(([v, label]) => tick(label, f.relations.includes(v), yes => { f.relations = toggle(f.relations, v, yes); }))));
      rows.push(h('div', { class: 'ann-group' }, h('span', { class: 'ann-lbl' }, 'Primary member'),
        [['any', 'Does not matter'], ['only', '★ Only the primary member'], ['not', 'Only people who are not']].map(([v, label]) => tick(label, f.primary === v, yes => { if (yes) f.primary = v; }, 'radio'))));
      if (setup.wings.length) rows.push(h('div', { class: 'ann-group' }, h('span', { class: 'ann-lbl' }, 'Wing'),
        tick('All wings', !f.wings.length, yes => { if (yes) f.wings = []; }, 'checkbox'),
        setup.wings.map(w => tick('Wing ' + w, f.wings.includes(w), yes => { f.wings = toggle(f.wings, w, yes); }))));
    }
    rows.push(h('div', { class: 'ann-group' }, h('span', { class: 'ann-lbl' }, byRole ? 'Roles' : 'Role (optional)'),
      byRole ? null : tick('Any role', !f.roles.length, yes => { if (yes) f.roles = []; }),
      setup.roles.filter(r => r.people).map(r => tick(roleLabel(r.name) + ' (' + r.people + ')', f.roles.includes(r.id), yes => { f.roles = toggle(f.roles, r.id, yes); }))));
    fill(ticks, rows);
  }
  const askPreview = debounce(async () => {
    const asked = JSON.stringify(st.filters);
    try {
      const p = await api.post('/announcements/preview', { filters: st.filters });
      if (asked !== JSON.stringify(st.filters)) return;
      st.preview = p; st.error = '';
    } catch (e) { st.preview = null; st.error = e.message; }
    drawPeople(); drawPhone(); drawSend();
  }, 250);
  function changed() { drawChoices(); drawTicks(); fill(sentence, h('span', { class: 'muted' }, 'Working out who that is…')); askPreview(); }

  function drawPeople() {
    const p = st.preview;
    if (!p) { fill(sentence, st.error ? h('span', { style: { color: 'var(--t-bad)' } }, st.error) : ''); fill(big, ''); fill(sub, ''); fill(chans, ''); fill(list, ''); fill(leftList, ''); leftBtn.hidden = true; return; }
    fill(sentence, p.words);
    fill(big, 'Goes to ' + plural(p.people.length, 'person', 'people'));
    fill(sub, p.people.length ? 'in ' + plural(p.flats, 'flat') + '. Someone who matches through two flats gets it once.' : 'Nobody matches these ticks.');
    fill(chans, Object.keys(ANN_HOW).filter(k => p.counts[k]).map(k => h('div', { class: 'ann-chan' }, h('span', { class: 'ic' }, ANN_HOW[k][0]), h('div', null, h('b', null, p.counts[k] + ' · ' + ANN_HOW[k][1]), h('div', { class: 'muted small' }, ANN_HOW[k][2])))));
    if (!p.people.some(x => x.id === st.pick)) st.pick = p.people[0] ? p.people[0].id : null;
    fill(list, p.people.length ? table([
      { label: 'Name', render: x => h('b', null, x.name) },
      { label: 'Flat', render: x => h('span', { class: 'small' }, x.flats || '—') },
      { label: 'How', render: x => h('span', { class: 'small' }, ANN_HOW[x.how][0] + ' ' + ANN_HOW[x.how][1]) },
      { label: '', render: x => h('button', { class: 'btn sm ghost', type: 'button', onclick: e => { e.stopPropagation(); st.pick = x.id; drawPhone(); right.scrollIntoView({ behavior: 'smooth', block: 'start' }); } }, 'See') },
    ], p.people) : null);
    leftBtn.hidden = !p.left_out.length;
    fill(leftBtn, st.showLeft ? 'Hide the ' + p.left_out.length + ' people left out' : 'Show the ' + p.left_out.length + ' people left out, and why');
    fill(leftList, st.showLeft ? table([{ label: 'Name', render: x => x.name }, { label: 'Flat', render: x => h('span', { class: 'small muted' }, x.flats || '—') }, { label: 'Why', render: x => h('span', { class: 'small' }, x.why) }], p.left_out) : null);
  }

  async function saveChoice() {
    const name = h('input', { type: 'text', maxlength: 80, placeholder: 'e.g. Wing A residents' });
    const hint = h('input', { type: 'text', maxlength: 120, placeholder: 'A few words to remind you (optional)' });
    modal({ title: 'Keep these ticks as a ready choice', body: h('div', null, h('p', { class: 'muted' }, st.preview ? st.preview.words : ''), field('Name', name), field('Note', hint)),
      actions: [{ label: 'Cancel' }, { label: 'Keep it', primary: true, run: async () => {
        if (name.value.trim().length < 2) throw new Error('Give it a name.');
        const r = await api.post('/announcement-audiences', { name: name.value.trim(), hint: hint.value.trim(), filters: st.filters });
        setup.audiences.push({ id: r.id, name: name.value.trim(), hint: hint.value.trim(), filters: JSON.parse(JSON.stringify(st.filters)), own: true });
        drawChoices(); toast('Kept as a ready choice', 'ok');
      } }] });
  }

  // 3. what they see
  const pickSel = h('select', { 'aria-label': 'Whose screen to show' });
  pickSel.addEventListener('change', () => { st.pick = pickSel.value; drawPhone(); });
  const phone = h('div');
  right.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, '3. What they see'), h('div', { class: 'card-b stack s8' }, pickSel, phone)));
  function drawPhone() {
    const p = st.preview, who = p && p.people.find(x => x.id === st.pick);
    fill(pickSel, p && p.people.length ? p.people.map(x => h('option', { value: x.id, selected: x.id === st.pick }, x.name + (x.flats ? ' · ' + x.flats : ''))) : h('option', null, 'Nobody yet'));
    if (!who) { fill(phone, h('div', { class: 'muted small' }, 'Pick who gets it to see their screen.')); return; }
    let text = annText(st, setup, who.name);
    const closed = who.how === 'whatsapp_closed';
    if (st.file && closed) text += '\n\n' + (who.has_email ? setup.texts.file_emailed : setup.texts.file_ask).replace('{file_name}', st.file.name);
    if (who.how === 'email' || who.how === 'none') {
      fill(phone, who.how === 'none' ? notice(who.name + ' has no number and no email on file, so they cannot be reached. Add one on People.', 'bad') : h('div', { class: 'ann-mail' },
        h('div', { class: 'mh' }, h('div', null, h('b', null, 'Email to '), who.name), h('div', null, h('b', null, 'Subject: '), '📢 ' + (st.title.trim() || st.body.split('\n')[0].slice(0, 70) || '…'))),
        h('div', { class: 'mb' }, waHtml(text), st.file ? h('div', { class: 'ann-doc' }, h('span', { class: 'pdf' }, 'FILE'), st.file.name) : null)));
      return;
    }
    const bubble = (kids, extra) => h('div', { class: 'ann-bub' + (extra || '') }, kids, h('span', { class: 'tm' }, 'now'));
    const items = [h('div', { class: 'ann-day' }, h('span', null, 'Today'))];
    if (closed) {
      items.push(bubble([h('div', { class: 'muted small' }, 'Your approved WhatsApp template' + (setup.template ? ' (' + setup.template + ')' : '')), h('div', null, 'The message that asks them to open their WhatsApp, with its button.')], ' tpl'));
      items.push(h('div', { class: 'ann-btn' }, 'Its button'));
      items.push(h('div', { class: 'ann-day' }, h('span', null, 'after they tap it, or write')));
    }
    if (st.file && !closed) items.push(bubble(h('div', { class: 'ann-doc' }, h('span', { class: 'pdf' }, 'FILE'), st.file.name)));
    items.push(bubble(waHtml(text)));
    if (who.how !== 'telegram') items.push(h('div', { class: 'ann-btn' }, setup.texts.got_it));
    fill(phone, h('div', { class: 'ann-phone' + (who.how === 'telegram' ? ' tg' : '') }, h('div', { class: 'ph-head' }, h('div', { class: 'av' }, (S.boot.org.name || '?')[0]), h('div', null, h('b', null, S.boot.org.name), h('div', { class: 'small' }, who.how === 'telegram' ? 'Telegram' : 'WhatsApp'))),
      h('div', { class: 'ph-body' }, items)),
      h('div', { class: 'muted small' }, ANN_HOW[who.how][2]),
      closed && !setup.template ? notice('No WhatsApp template is chosen for this organisation, so people who have been quiet only get it when they next write to the chat bot (or by email).', 'warn') : null);
  }

  // 4. send
  const sendBox = h('div', { class: 'stack s8' });
  right.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, '4. Send'), h('div', { class: 'card-b' }, sendBox)));
  const when = h('input', { type: 'datetime-local' });
  when.addEventListener('input', () => { st.when = when.value; drawSend(); });
  function drawSend() {
    const n = st.preview ? st.preview.people.length : 0;
    const ready = n && st.body.trim() && (st.mode === 'now' || st.when);
    const btn = h('button', { class: 'btn primary', type: 'button', disabled: !ready, style: { width: '100%', justifyContent: 'center' }, onclick: () => confirmSend() },
      !st.body.trim() ? 'Write the message first' : !n ? 'Nobody to send to' : st.mode === 'now' ? 'Send to ' + plural(n, 'person', 'people') : 'Plan it for ' + plural(n, 'person', 'people'));
    fill(sendBox, h('div', { class: 'row' }, tick('Send now', st.mode === 'now', v => { if (v) st.mode = 'now'; drawSend(); }, 'radio'), tick('Send later', st.mode === 'later', v => { if (v) st.mode = 'later'; drawSend(); }, 'radio')),
      st.mode === 'later' ? field('When', when, 'Who gets it is worked out again at that moment, so people added before then are included.') : null,
      btn, h('div', { class: 'muted small' }, 'You see the list once more before anything goes out.'));
  }
  async function confirmSend() {
    const p = st.preview, n = p.people.length;
    const later = st.mode === 'later', at = later ? new Date(st.when) : null;
    if (later && !(at > new Date())) { toast('Pick a time that has not passed yet.', 'bad'); return; }
    const lines = Object.keys(ANN_HOW).filter(k => p.counts[k]).map(k => h('div', null, ANN_HOW[k][0] + ' ' + p.counts[k] + ' · ' + ANN_HOW[k][1]));
    modal({ title: later ? 'Plan this announcement?' : 'Send this announcement now?',
      body: h('div', { class: 'stack s8' }, h('div', null, h('b', null, st.title.trim() || '(no heading)'), h('div', { class: 'muted' }, st.body.trim().slice(0, 160) + (st.body.trim().length > 160 ? '…' : ''))),
        st.file ? h('div', null, '📎 ' + st.file.name) : null, h('div', null, p.words), h('div', null, h('b', null, plural(n, 'person', 'people'))), lines,
        later ? h('div', null, 'Goes out on ', h('b', null, fmtDT(at.toISOString())), '.') : notice('Once sent, it cannot be taken back.', 'warn')),
      actions: [{ label: 'Go back' }, { label: later ? 'Yes, plan it' : 'Yes, send it', primary: true, run: async () => {
        const hit = setup.audiences.find(a => a.id === st.audience);
        const r = await api.post('/announcements', { title: st.title.trim(), body: st.body.trim(), greet: st.greet, filters: st.filters, audience_name: hit ? hit.name : '',
          send_at: later ? at.toISOString() : null, file_name: st.file ? st.file.name : null, file_type: st.file ? st.file.type : null, file_b64: st.file ? st.file.b64 : null });
        toast(later ? 'Planned' : 'Sending to ' + plural(r.people, 'person', 'people'), 'ok');
        go('announcements', '', { id: r.id });
      } }] });
  }

  onText(); changed(); drawSend();
}

// ----- what happened -----
async function annReport(root, id) {
  const mine = S.renderId;
  setTopAction({ label: 'New announcement', icon: 'megaphone', run: () => go('announcements', '', { new: 1 }) });
  const head = h('div'), kpis = h('div', { class: 'kpis' }), people = h('div', { class: 'card' });
  root.append(h('div', { class: 'row', style: { marginBottom: '12px' } }, h('a', { class: 'btn sm ghost', href: href('announcements') }, '← All announcements')), head, kpis, people);
  async function load() {
    if (mine !== S.renderId) return;
    const d = await api.get('/announcements/' + id);
    if (mine !== S.renderId) return;
    const a = d.announcement, c = d.counts;
    fill(head, h('div', { class: 'card' }, h('div', { class: 'card-b stack s8' },
      h('div', { class: 'row' }, h('b', { style: { fontSize: '16px' } }, a.title || String(a.body).split('\n')[0].slice(0, 80)), badge(...(ANN_STATUS[a.status] || [a.status]))),
      h('div', { class: 'muted small' }, a.status === 'planned' ? 'Goes ' + fmtDT(a.send_at) : 'Sent ' + fmtDT(a.started_at || a.send_at), a.created_by ? ' · by ' + String(a.created_by).replace(/^dashboard · /, '') : ''),
      h('div', { class: 'small' }, a.audience_name ? h('b', null, a.audience_name + ': ') : null, a.audience_text),
      h('details', null, h('summary', { class: 'small' }, 'The message'), h('div', { class: 'ann-msg' }, waHtml(a.body))),
      a.file_name ? h('div', { class: 'small' }, '📎 ', h('a', { href: BASE + '/announcements/' + id + '/file' }, a.file_name)) : null,
      a.status === 'planned' ? h('div', { class: 'row' },
        h('button', { class: 'btn primary sm', type: 'button', onclick: async () => { if (!await confirmBox('Send it now instead of at its planned time?', { ok: 'Send now' })) return; try { await api.post('/announcements/' + id + '/send-now'); toast('Sending', 'ok'); setTimeout(load, 1500); } catch (e) { toast(e.message, 'bad'); } } }, 'Send now instead'),
        h('button', { class: 'btn sm danger', type: 'button', onclick: async () => { if (!await confirmBox('Cancel this announcement? It will not go out.', { ok: 'Cancel it', danger: true })) return; try { await api.post('/announcements/' + id + '/cancel'); toast('Cancelled', 'ok'); load(); } catch (e) { toast(e.message, 'bad'); } } }, 'Cancel it')) : null)));
    const total = d.people.length;
    const k = (label, n, tone) => h('div', { class: 'kpi', style: { cursor: 'default' } }, h('div', { class: 'muted small' }, label), h('div', { style: { fontSize: '22px', fontWeight: 700, color: tone ? 'var(--t-' + tone + ')' : '' } }, n));
    fill(kpis, a.status === 'planned' ? null : [
      k('People', total), k('Sent', c.sent + c.delivered + c.read + c.got_it + c.emailed), k('Delivered', c.delivered + c.read + c.got_it), k('Read', c.read + c.got_it, 'ok'),
      k('Tapped Got it', c.got_it, 'ok'), k('Waiting for them to open WhatsApp', c.kept, 'warn'), k('Not reached', c.failed, 'bad')]);
    fill(people, a.status === 'planned' ? h('div', { class: 'card-b muted' }, 'Who gets it is worked out at the moment it goes, so people added before then are included.') : table([
      { label: 'Name', render: p => p.user_id ? person(p.user_id, p.name) : p.name },
      { label: 'Flat', render: p => h('span', { class: 'small' }, p.flats || '—') },
      { label: 'By', render: p => h('span', { class: 'small' }, { whatsapp: '💬 WhatsApp', telegram: '✈️ Telegram', email: '✉️ Email', none: '—' }[p.channel] || p.channel) },
      { label: 'Now', render: p => h('div', null, badge(...(ANN_STATE[p.status] || [p.status])), p.emailed && p.channel === 'whatsapp' ? h('span', { class: 'muted small' }, ' · also emailed') : null, p.note ? h('div', { class: 'muted small' }, p.note) : null) },
      { label: 'When', render: p => h('span', { class: 'small muted' }, p.got_it_at ? 'Got it ' + fmtDT(p.got_it_at) : p.read_at ? 'Read ' + fmtDT(p.read_at) : p.delivered_at ? 'Delivered ' + fmtDT(p.delivered_at) : p.sent_at ? fmtDT(p.sent_at) : '') },
    ], d.people, { emptyTitle: 'Nobody yet', emptyText: 'It is being worked out.' }));
    if (a.status === 'planned' || a.status === 'sending' || c.kept || c.sent || c.delivered) setTimeout(load, a.status === 'sending' ? 3000 : 15000);
  }
  await load();
}

SECTIONS.announcements = {
  title: 'Announcements', sub: 'One message to many people: everyone who lives here, only tenants, the AGM minutes to primary members…',
  async render(root, route) { return renderAnnouncements(root, route); },
};
"""
