JS = r"""
// ───────────────────────── Settings ─────────────────────────
// A menu on the left, one card per topic. Every number comes from the server with its built-in
// default, so a box never hides what the app does when nothing is set.
const themeChoice = () => { const s = store.get('panel.theme'); return s === 'dark' || s === 'light' ? s : 'auto'; };
function chooseTheme(c) {
  if (c === 'auto') { try { localStorage.removeItem('panel.theme'); } catch (e) { /* private mode */ } delete document.documentElement.dataset.theme; }
  else applyTheme(c);
}
function zoneLabel(tz) {
  let off = '';
  try { off = new Intl.DateTimeFormat('en', { timeZone: tz, timeZoneName: 'shortOffset' }).formatToParts(new Date()).find(p => p.type === 'timeZoneName').value.replace('GMT', 'UTC'); } catch (e) { /* unknown zone */ }
  return String(tz).replace(/_/g, ' ') + (off ? ' (' + off + ')' : '');
}
function setCard(id, title, ...kids) { return h('div', { class: 'card', id: 'set-' + id }, h('div', { class: 'card-h' }, title), h('div', { class: 'card-b' }, ...kids)); }
function setRow(label, help, ...controls) { return h('div', { class: 'srow' }, h('div', null, h('b', null, label), help ? h('div', { class: 'muted small' }, help) : null), h('div', { class: 'sctl' }, ...controls)); }

async function settingsOrgCard(info) {
  const lg = await classic.get('/settings/logo').catch(() => ({}));
  const file = h('input', { type: 'file', accept: 'image/*' });
  const mark = h('span', { class: 'logo lg' }, lg.logo_url ? h('img', { src: lg.logo_url, alt: '' }) : (S.boot.org.name || '?')[0]);
  return setCard('org', 'Organisation',
    setRow('Name', 'Shown in the menu and on the PDFs your flows make.', h('b', null, info.org.name), S.boot.org.industry ? badge(pretty(S.boot.org.industry)) : null),
    setRow('Logo', 'Also appears on those PDFs. Up to 2 MB.', mark, file, h('button', { class: 'btn sm primary', onclick: async () => {
      if (!file.files[0]) { toast('Choose an image first.', 'bad'); return; }
      const fd = new FormData(); fd.append('logo_file', file.files[0]);
      try { await classic.post('/settings/logo', fd); toast('Logo saved', 'ok'); location.reload(); } catch (e) { toast(e.message, 'bad'); } } }, 'Upload')));
}
function settingsTimeCard(info) {
  return setCard('time', 'Time & language',
    setRow('Time zone', 'Used by schedules, reminders, “due in” and every date on screen.', h('b', null, zoneLabel(info.org.timezone)), h('span', { class: 'badge', 'data-tip': 'Everything runs on this time zone today. Choosing another one is planned.' }, 'Fixed for now')),
    setRow('Language of messages', 'The words the assistant uses come from its instructions and message texts.', h('b', null, 'English')));
}

// one number: a box, its unit, the built-in value, and a way back to it
function numberRow(f) {
  const input = h('input', { type: 'number', min: f.min, max: f.max, step: 1, value: String(f.value), 'aria-label': f.label });
  const about = h('span', { class: 'dflt' }), back = h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { input.value = String(f.default); input.dispatchEvent(new Event('input')); } }, 'Use built-in');
  const r = {
    f, input, el: null, onChange: () => {},
    val() { const t = input.value.trim(); return /^\d+$/.test(t) ? Number(t) : NaN; },
    valid() { const v = r.val(); return Number.isInteger(v) && v >= f.min && v <= f.max; },
    dirty() { return r.val() !== f.value; },
    payload() { return f.section === 'column' ? r.val() : (r.val() === f.default ? null : r.val()); },
    set disabled(x) { input.disabled = x; back.disabled = x; },
  };
  const paint = () => {
    const v = r.val(), ok = r.valid();
    input.classList.toggle('bad', !ok);
    back.style.display = ok && v !== f.default ? '' : 'none';
    about.textContent = !ok ? 'Between ' + f.min + ' and ' + f.max : 'Built-in: ' + f.default + (f.unit.startsWith('minutes') && v >= 60 ? ' · now ≈ ' + minutes(v) : '');
    about.classList.toggle('badtx', !ok);
  };
  input.addEventListener('input', () => { paint(); r.onChange(); });
  paint();
  r.el = setRow(f.label, f.help, input, h('span', { class: 'muted' }, f.unit), back, about);
  return r;
}
function settingsGroupCard(g, onSaved) {
  const rows = g.fields.map(numberRow);
  const sw = g.key === 'retention' ? h('input', { type: 'checkbox', checked: g.enabled }) : null;
  const save = h('button', { class: 'btn primary', type: 'button', disabled: true }, 'Save');
  const refresh = () => {
    if (sw) rows.forEach(r => { r.disabled = !sw.checked; });
    const changed = rows.some(r => r.dirty()) || (sw && sw.checked !== g.enabled);
    save.disabled = !(changed && rows.every(r => r.valid()));
  };
  rows.forEach(r => { r.onChange = refresh; });
  if (sw) sw.addEventListener('change', refresh);
  save.onclick = async () => {
    const body = { limits: {}, retention: {} };
    rows.forEach(r => { if (r.f.section === 'column') body.session_ttl_minutes = r.val(); else body[r.f.section][r.f.key] = r.payload(); });
    if (sw) body.retention.enabled = sw.checked ? null : false;
    save.disabled = true;
    try { await api.put('/org-settings', body); toast('Saved', 'ok'); await onSaved(g.key); } catch (e) { toast(e.message, 'bad'); refresh(); }
  };
  refresh();
  return setCard(g.key, g.label,
    h('div', { class: 'muted small', style: { marginBottom: '4px' } }, g.intro),
    sw ? h('div', { class: 'srow' }, h('div', null, h('b', null, 'Clear out leftovers every night'), h('div', { class: 'muted small' }, 'Switch off only if you want everything kept exactly as it is.')), h('div', { class: 'sctl' }, h('label', { class: 'switch' }, sw, h('span')))) : null,
    rows.map(r => r.el),
    h('div', { class: 'row', style: { paddingTop: '12px' } }, save, h('span', { class: 'muted small' }, 'Each box shows the built-in number, so you can always go back to it.')));
}
function settingsBrowserCard() {
  const cur = themeChoice();
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Appearance' }, [['auto', 'Match my computer'], ['light', 'Light'], ['dark', 'Dark']].map(([k, l]) => h('button', { type: 'button', 'aria-pressed': String(cur === k), onclick: e => {
    chooseTheme(k); seg.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === e.currentTarget)));
  } }, l)));
  return setCard('you', 'This browser',
    setRow('Your name', 'Written next to every change you make, so the change log shows who did it. It is a label, not a login.', h('input', { type: 'text', value: getName(), placeholder: 'e.g. Kartik', onchange: e => { setName(e.target.value.trim()); toast('Saved on this browser', 'ok'); } })),
    setRow('Appearance', 'Only changes how this browser looks.', seg));
}
async function settingsSupportCard() {
  const d = await api.get('/status').catch(() => null);
  const LABELS = { cases: 'Cases', categories: 'Categories', routing: 'Routing rules', parties: 'People on a case', grants: 'Special access', events: 'Change log', seats: 'Seats', residents: 'Residents', audit: 'Chat log', targets: 'Response times', workflow_kind: 'Workflow kinds' };
  return setCard('support', 'For support',
    d ? h('details', null, h('summary', { class: 'muted small', style: { cursor: 'pointer' } }, 'What this database supports'), h('div', { class: 'stack', style: { marginTop: '10px' } },
      d.caps.cases && !d.case_model_installed ? notice('The case model (categories, routing, seats, special access) is not fully installed in this database, so those screens are hidden. Missing: ' + d.case_model_missing.map(pretty).join(', ') + '.', 'warn') : null,
      h('div', { class: 'chips' }, Object.entries(LABELS).map(([k, l]) => h('span', { class: 'badge ' + (d.caps[k] ? 'ok' : '') }, (d.caps[k] ? '✓ ' : '✗ ') + l))),
      h('div', { class: 'muted small' }, 'Cases count as finished when their status is: ' + d.closed_values.join(', ') + '. ' + plural(d.counts.users, 'person', 'people') + ', ' + plural(d.counts.workflows, 'workflow') + '.'))) : null,
    setRow('End every ongoing conversation', 'People can simply start again.', h('button', { class: 'btn danger', onclick: async () => {
      if (!await confirmBox('End every ongoing conversation with the assistant? People can simply start again.', { ok: 'End them all', danger: true })) return;
      try { await classic.post('/sessions/clear'); toast('Cleared', 'ok'); } catch (e) { toast(e.message, 'bad'); } } }, 'End them all now')));
}

SECTIONS.settings = {
  title: 'Settings', sub: 'Your organisation and how the assistant behaves, each setting in one place.',
  async render(root) {
    const info = await api.get('/org-settings');
    const cards = {};
    const onSaved = async key => {
      const fresh = await api.get('/org-settings');
      const g = fresh.groups.find(x => x.key === key);
      const next = settingsGroupCard(g, onSaved);
      cards[key].replaceWith(next); cards[key] = next;
    };
    const parts = await Promise.all([settingsOrgCard(info), settingsSupportCard()]);
    cards.org = parts[0]; cards.time = settingsTimeCard(info);
    info.groups.forEach(g => { cards[g.key] = settingsGroupCard(g, onSaved); });
    cards.you = settingsBrowserCard(); cards.support = parts[1];
    const order = [['org', 'Organisation'], ['time', 'Time & language'], ...info.groups.map(g => [g.key, g.label]), ['you', 'This browser'], ['support', 'For support']];
    const go = k => { const t = cards[k]; if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
    const links = order.map(([k, l]) => h('a', { role: 'button', tabindex: '0', 'data-k': k, onclick: () => go(k), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(k); } } }, l));
    root.append(h('div', { class: 'setgrid' }, h('nav', { class: 'setnav', 'aria-label': 'Settings sections' }, links), h('div', { class: 'stack s16' }, order.map(([k]) => cards[k]))));
    links[0].classList.add('on');
    if (window.IntersectionObserver) {
      // the menu shows the topmost card that is in view
      const inView = new Set();
      const seen = new IntersectionObserver(es => {
        es.forEach(e => { if (e.isIntersecting) inView.add(e.target); else inView.delete(e.target); });
        const first = order.find(([k]) => inView.has(cards[k]));
        if (first) links.forEach(a => a.classList.toggle('on', a.dataset.k === first[0]));
      }, { rootMargin: '-72px 0px -65% 0px' });
      Object.values(cards).forEach(c => seen.observe(c));
    }
  },
};
"""
