JS = r"""
// ───────────────────────── the super admin page, and asking a super admin ─────────────────────────
// A super admin signs in at /admin and sees every organisation here; each organisation's own
// dashboard (what an admin sees, plus the set-up sections) opens from the Organisations tab.
const SUPER_TABS = [['overview', 'Overview', 'home'], ['orgs', 'Organisations', 'globe'], ['accounts', 'Dashboard access', 'usercheck'], ['activity', 'Sign-in log', 'hist']];
const AUDIT_WORDS = {
  sign_in: 'Signed in', sign_in_failed: 'Failed to sign in', sign_in_refused: 'Refused: the account is off', locked_out: 'Tried to sign in while locked',
  sign_out: 'Signed out', sign_up: 'Signed up', sign_up_failed: 'Sign-up code was wrong', sign_up_unknown: 'Asked to sign up without an invitation',
  code_sent: 'A code was emailed', password_reset: 'Chose a new password', reset_failed: 'Reset code was wrong', reset_unknown: 'Asked for a reset for an unknown address',
  access_given: 'Access given', access_taken: 'Access taken away', switched_on: 'Switched on', switched_off: 'Switched off', super_added: 'Made a super admin',
  signed_out_everywhere: 'Signed out everywhere', invite_again: 'Invitation sent again', ask: 'Asked the super admins',
};
const auditNote = r => r.detail && r.detail.trim().toLowerCase() !== (AUDIT_WORDS[r.action] || '').toLowerCase() ? r.detail : '';
const accountState = a => a.locked ? badge('Locked for a while', 'bad') : a.status === 'active' ? badge('Active', 'ok') : a.status === 'invited' ? badge('Has not signed up yet', 'info') : badge('Switched off');
const orgNameOf = (orgs, key) => (orgs.find(o => o.key === key) || {}).name || key;
const auditLine = r => h('div', { class: 'sa-line' }, h('div', { class: 't' }, h('b', null, r.who), ' · ', AUDIT_WORDS[r.action] || pretty(r.action), r.ok === false ? [' ', badge('failed', 'bad')] : null, auditNote(r) ? h('div', { class: 'muted small' }, auditNote(r).length > 180 ? auditNote(r).slice(0, 180) + '…' : auditNote(r)) : null), h('span', { class: 'muted small' }, ago(r.at)));

// pick a person of one organisation, to give them dashboard access
function orgPersonPicker(orgKey, onPick) {
  const input = h('input', { type: 'text', placeholder: 'Start typing a name', autocomplete: 'off' });
  const list = h('div', { class: 'sa-pick' });
  let chosen = null;
  async function search() {
    try {
      const d = await request('/admin/' + encodeURIComponent(orgKey) + '/api/v2/people' + qs({ q: input.value, status: 'active', page_size: 8 }));
      fill(list, d.rows.length ? d.rows.map(p => h('button', { class: 'opt' + (chosen && chosen.id === p.id ? ' on' : ''), type: 'button', onclick: () => { chosen = p; onPick(p); search(); } },
        h('span', { class: 'person' }, avatar(p.name), h('span', null, p.name)), h('span', { class: 'muted small' }, p.email || 'no email on file'))) : h('div', { class: 'muted small' }, 'No one found.'));
    } catch (e) { fill(list, notice(e.message, 'bad')); }
  }
  input.addEventListener('input', debounce(search, 250));
  search();
  return { el: h('div', { class: 'stack s8' }, input, list) };
}
function giveAccessDone(r, person) {
  const who = firstName(person.name);
  toast(r.created ? (r.emailed ? 'Invitation sent to ' + person.email : 'Access given, but the email could not be sent. Ask ' + who + ' to open the dashboard address and choose Sign up.') : who + ' can sign in to this organisation now.', r.created && !r.emailed ? 'bad' : 'ok');
}
async function giveAccessDialog(o) {
  o = o || {};
  const orgs = o.orgs || (await authApi.get('/orgs')).orgs;
  const org = sel(orgs.map(x => [x.key, x.name]), o.orgKey || (orgs[0] && orgs[0].key));
  const slot = h('div');
  let pick = null;
  const draw = () => { pick = null; fill(slot, field('Who', orgPersonPicker(org.value, p => { pick = p; }).el, 'Only people already added to that organisation can be given access. Add someone under People first.')); };
  org.addEventListener('change', draw); draw();
  modal({
    title: 'Give dashboard access',
    body: h('div', { class: 'stack' }, h('p', { class: 'muted' }, 'They sign in as an admin of one organisation: Home, Cases and People, and they can assign cases and change roles. We email them an invitation.'), field('Organisation', org), slot),
    actions: [{ label: 'Cancel' }, { label: 'Give access', primary: true, run: async () => {
      if (!pick) throw new Error('Choose a person.');
      const r = await authApi.post('/accounts/give-access', { source_key: org.value, user_id: pick.id });
      giveAccessDone(r, pick);
      if (o.done) o.done();
    } }],
  });
}
function addSuperDialog(done) {
  const name = h('input', { type: 'text', placeholder: 'Full name', maxlength: 120 });
  const email = h('input', { type: 'text', placeholder: 'name@example.com', maxlength: 300 });
  modal({
    title: 'Add a super admin',
    body: h('div', { class: 'stack' }, notice('A super admin can open every organisation and change everything, including who else can sign in. Only add someone you trust fully.', 'warn'), field('Name', name), field('Email', email, 'We email an invitation. They sign up with a code we email, then choose their own password.')),
    actions: [{ label: 'Cancel' }, { label: 'Add super admin', primary: true, run: async () => {
      if (name.value.trim().length < 2) throw new Error('Write the name.');
      const r = await authApi.post('/super-admins', { email: email.value.trim(), name: name.value.trim() });
      toast(r.emailed ? 'Invitation sent to ' + r.account.email : 'Added, but the email could not be sent.', r.emailed ? 'ok' : 'bad');
      if (done) done();
    } }],
  });
}
// an admin asks the super admins for something they cannot do themselves
function askDialog(start) {
  const text = h('textarea', { rows: 4, maxlength: 2000, placeholder: 'What do you need? For example: please add Zoya Khan as a committee member.' });
  text.value = start || '';
  modal({
    title: 'Ask a super admin',
    body: h('div', { class: 'stack' }, h('p', { class: 'muted' }, 'We email every super admin. Say what you need and who it is for.'), field('Your message', text)),
    actions: [{ label: 'Cancel' }, { label: 'Send', primary: true, run: async () => {
      if (text.value.trim().length < 3) throw new Error('Write a few words first.');
      await api.post('/ask', { text: text.value.trim() });
      toast('Sent to the super admins.', 'ok');
    } }],
  });
}

// the card in an admin's menu that says who to ask
function adminHelpCard() {
  return h('div', { class: 'pr-help' }, h('b', null, 'Need a person added, or something changed?'),
    h('span', null, 'Flows, chat bot messages and rules are looked after by a super admin.'),
    h('button', { class: 'btn sm', type: 'button', onclick: () => askDialog() }, 'Ask a super admin'));
}
// from a person's page in People: let them sign in to this organisation's dashboard
async function giveAccessTo(p, done) {
  if (!p.email) { toast('Add an email address for ' + p.name + ' first.', 'bad'); return; }
  if (!await confirmBox('Let ' + p.name + ' sign in to the ' + S.boot.org.name + ' dashboard as an admin? We email ' + p.email + ' an invitation. They will see Home, Cases and People, and can assign cases and change roles.', { title: 'Give dashboard access', ok: 'Give access' })) return;
  try {
    const r = await authApi.post('/accounts/give-access', { source_key: ORG, user_id: p.id });
    giveAccessDone(r, p);
    if (done) done();
  } catch (e) { toast(e.message, 'bad'); }
}
// a person's dashboard sign-in, as one row in their account card
function dashboardAccess(p, reload) {
  const d = p.dashboard, label = h('span', { class: 'muted', style: { width: '90px' } }, 'Dashboard');
  if (!isSuper()) {
    return h('div', { class: 'row' }, label, d ? badge(d.level === 'super' ? 'Super admin' : d.status === 'invited' ? 'Invited, has not signed up yet' : d.status === 'off' ? 'Switched off' : 'Can sign in as admin', d.status === 'active' ? 'ok' : '') : h('span', { class: 'muted' }, 'No sign-in'));
  }
  if (d && d.level === 'super') return h('div', { class: 'row' }, label, badge('Super admin', 'brand'), h('span', { class: 'muted small' }, 'Opens every organisation. Managed under Dashboard access.'));
  if (!d) {
    return h('div', { class: 'row' }, label,
      h('button', { class: 'btn sm', type: 'button', disabled: !p.email, onclick: () => giveAccessTo(p, reload) }, icon('usercheck', 'sm'), 'Give dashboard access'),
      h('span', { class: 'muted small' }, p.email ? 'They sign in as an admin of ' + S.boot.org.name + '.' : 'Add an email address first.'));
  }
  const state = d.status === 'active' ? badge('Can sign in as admin', 'ok') : d.status === 'invited' ? badge('Invited, has not signed up yet', 'info') : badge('Switched off');
  return h('div', { class: 'row' }, label, state,
    d.status === 'invited' ? h('button', { class: 'btn sm', type: 'button', onclick: async () => {
      try { const r = await authApi.post('/accounts/' + d.account_id + '/invite-again'); toast(r.emailed ? 'Invitation sent again.' : 'The email could not be sent.', r.emailed ? 'ok' : 'bad'); } catch (e) { toast(e.message, 'bad'); }
    } }, 'Send the invitation again') : null,
    h('button', { class: 'btn sm danger', type: 'button', onclick: async () => {
      if (!await confirmBox(p.name + ' will no longer be able to open the ' + S.boot.org.name + ' dashboard.', { title: 'Take away dashboard access', ok: 'Take away', danger: true })) return;
      try { await authApi.post('/accounts/' + d.account_id + '/take-access', { source_key: ORG }); toast('Access taken away.', 'ok'); reload(); } catch (e) { toast(e.message, 'bad'); }
    } }, 'Take away access'));
}

async function superOverview(root) {
  const d = await authApi.get('/overview'), n = d.numbers;
  const needs = [];
  d.waiting.forEach(a => needs.push(h('div', { class: 'sa-line' }, h('div', { class: 't' }, h('b', null, a.name), ' has not signed up yet', h('div', { class: 'muted small' }, a.email + ' · ' + (a.level === 'super' ? 'Super admin' : 'Admin of ' + a.orgs.join(', ')))),
    h('button', { class: 'btn sm', type: 'button', onclick: async e => { e.currentTarget.disabled = true; try { const r = await authApi.post('/accounts/' + a.id + '/invite-again'); toast(r.emailed ? 'Sent to ' + a.email : 'The email could not be sent.', r.emailed ? 'ok' : 'bad'); } catch (x) { toast(x.message, 'bad'); } } }, 'Send the email again'))));
  d.locked.forEach(a => needs.push(h('div', { class: 'sa-line' }, h('div', { class: 't' }, h('b', null, a.name), ' is locked after wrong tries', h('div', { class: 'muted small' }, 'It opens again by itself after a few minutes.')), badge('Locked', 'bad'))));
  root.append(
    h('div', { class: 'kpis' }, kpiTile('Organisations', n.organisations, '', '#/orgs'), kpiTile('People in the chat bots', n.people, '', '#/orgs'), kpiTile('Admins who can sign in', n.admins, '', '#/accounts'), kpiTile('Super admins', n.super_admins, '', '#/accounts')),
    h('div', { class: 'card', style: { marginBottom: '16px' } }, h('div', { class: 'card-h' }, 'Needs you'), needs.length ? needs : h('div', { class: 'card-b muted' }, 'Nothing needs you right now.')),
    h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Recently', h('a', { class: 'small', href: '#/activity' }, 'See everything')), d.recent.length ? d.recent.map(auditLine) : h('div', { class: 'card-b muted' }, 'Nothing yet.')));
}
async function superOrgs(root) {
  const d = await authApi.get('/orgs');
  root.append(d.orgs.length ? h('div', { class: 'sa-orgs' }, d.orgs.map(o => h('div', { class: 'card sa-org' }, h('div', { class: 'card-b' },
    h('div', { class: 'top' }, h('span', { class: 'logo' }, o.name[0]), h('div', null, h('b', null, o.name), h('span', { class: 'muted small' }, (o.channel ? ({ telegram: 'Telegram', whatsapp: 'WhatsApp' }[o.channel] || pretty(o.channel)) : 'No chat channel') + (o.people != null ? ' · ' + plural(o.people, 'person', 'people') : '')))),
    h('div', null, h('div', { class: 'muted small', style: { marginBottom: '6px' } }, 'Admins who can sign in'),
      o.admins.length ? h('div', { class: 'sa-who' }, o.admins.map(a => h('span', { class: 'badge ' + (a.status === 'active' ? 'ok' : a.status === 'invited' ? 'info' : '') }, a.name + (a.status === 'invited' ? ' · invited' : a.status === 'off' ? ' · off' : '')))) : h('span', { class: 'muted' }, 'Nobody yet. Give someone access.')),
    h('div', { class: 'row' }, h('a', { class: 'btn primary', href: '/admin/' + encodeURIComponent(o.key) }, 'Open dashboard', icon('arrowr', 'sm')), h('button', { class: 'btn', type: 'button', onclick: () => giveAccessDialog({ orgs: d.orgs, orgKey: o.key, done: () => { lastSig = ''; superRoute(); } }) }, 'Give access…')))))) : empty('No organisations', ''));
}
function accountMenu(a, orgs, again, anchor) {
  const item = (ic, text, run, danger) => h('button', { class: 'mi', type: 'button', style: danger ? { color: 'var(--bad)' } : null, onclick: async () => {
    closePop();
    try { if ((await run()) !== false) again(); } catch (e) { toast(e.message, 'bad'); }
  } }, icon(ic), text);
  const items = [];
  if (a.status === 'invited') items.push(item('send', 'Send the invitation again', async () => { const r = await authApi.post('/accounts/' + a.id + '/invite-again'); toast(r.emailed ? 'Sent to ' + a.email : 'The email could not be sent.', r.emailed ? 'ok' : 'bad'); return false; }));
  if (a.status === 'active') items.push(item('lock', 'Sign out everywhere', async () => { await authApi.post('/accounts/' + a.id + '/sign-out'); toast(a.name + ' was signed out everywhere.', 'ok'); return false; }));
  if (a.level === 'admin') a.orgs.forEach(k => items.push(item('minus', 'Take away access to ' + orgNameOf(orgs, k), async () => {
    if (!await confirmBox(a.name + ' will no longer be able to open ' + orgNameOf(orgs, k) + '.' + (a.orgs.length === 1 ? ' It is the only one, so the account is switched off.' : ''), { title: 'Take away access', ok: 'Take away', danger: true })) return false;
    await authApi.post('/accounts/' + a.id + '/take-access', { source_key: k }); toast('Done.', 'ok');
  }, true)));
  items.push(a.status === 'off'
    ? item('ok', 'Switch on', async () => { await authApi.post('/accounts/' + a.id + '/switch', { on: true }); toast(a.name + ' can sign in again.', 'ok'); })
    : item('stop', 'Switch off', async () => {
      if (!await confirmBox(a.name + ' is signed out at once and cannot sign in until you switch the account on again.', { title: 'Switch off ' + a.name, ok: 'Switch off', danger: true })) return false;
      await authApi.post('/accounts/' + a.id + '/switch', { on: false }); toast(a.name + ' was switched off.', 'ok');
    }, true));
  openPop(anchor, items, { align: 'right', width: 290 });
}
async function superAccounts(root) {
  const [d, o] = await Promise.all([authApi.get('/accounts'), authApi.get('/orgs')]);
  const again = () => { clear(root); superAccounts(root); };
  setTopAction({ label: 'Give access', run: () => giveAccessDialog({ orgs: o.orgs, done: again }) });
  root.append(h('div', { class: 'row between', style: { marginBottom: '12px' } }, h('span', { class: 'muted' }, 'Everyone who can sign in to a dashboard. A person who is not here yet is added from an organisation’s People, or with Give access.'),
    h('button', { class: 'btn', type: 'button', onclick: () => addSuperDialog(again) }, icon('shield', 'sm'), 'Add a super admin')));
  root.append(h('div', { class: 'card' }, table([
    { label: 'Person', cls: 'wide', render: a => h('div', { class: 'person' }, avatar(a.name), h('div', null, h('b', null, a.name), h('div', { class: 'muted small' }, a.email))) },
    { label: 'Level', render: a => badge(a.level === 'super' ? 'Super admin' : 'Admin', a.level === 'super' ? 'brand' : '') },
    { label: 'Can open', render: a => a.level === 'super' ? 'Every organisation' : (a.orgs.length ? a.orgs.map(k => orgNameOf(o.orgs, k)).join(', ') : h('span', { class: 'muted' }, 'Nothing')) },
    { label: 'State', render: accountState },
    { label: 'Last signed in', render: a => a.last_sign_in ? ago(a.last_sign_in) : h('span', { class: 'muted' }, 'Never') },
    { label: '', render: a => h('button', { class: 'btn sm ghost icon', type: 'button', 'aria-label': 'More for ' + a.name, 'data-popkeep': '1', onclick: e => accountMenu(a, o.orgs, again, e.currentTarget) }, icon('dots', 'sm')) },
  ], d.accounts, { emptyTitle: 'Nobody yet' })));
}
// The sign-in log: quick buttons by topic, a search, one organisation and a range. The numbers on the
// buttons come from the server and follow the other filters, so they always match what a click shows.
const LOG_VIEWS = [['all', 'All'], ['messages', 'Messages from admins'], ['sign_in', 'Sign-ins'], ['problems', 'Problems'], ['sign_up', 'Sign-ups and codes'], ['access', 'Access changes']];
const LOG_RANGES = [['all', 'All time'], ['today', 'Today'], ['7d', 'Last 7 days'], ['30d', 'Last 30 days']];
async function superActivity(root, r) {
  const mine = S.renderId;
  const q = { ...r.q };
  if (!LOG_VIEWS.some(v => v[0] === q.view)) q.view = 'all';        // a made-up address falls back to everything
  if (!LOG_RANGES.some(v => v[0] === q.range)) q.range = 'all';
  q.page = Number(q.page || 1) || 1;
  const bar = h('div', { class: 'filters' }), chips = h('div', { class: 'chips', style: { marginBottom: '12px' } }), out = h('div', { class: 'card' });
  root.append(bar, chips, out);
  const update = patch => { Object.assign(q, patch); if (!('page' in patch)) q.page = 1; load(); };
  const search = h('input', { type: 'search', placeholder: 'Search a name, an email, or words in a message', value: q.q || '', style: { flex: 1, minWidth: '240px', maxWidth: '420px' }, 'aria-label': 'Search the sign-in log' });
  search.addEventListener('input', debounce(() => update({ q: search.value }), 300));
  const orgSel = sel([['', 'All organisations']], '', { class: 'select sm', style: { width: 'auto' }, 'aria-label': 'Organisation', onchange: e => update({ org: e.target.value }) });
  const rangeSel = sel(LOG_RANGES, q.range, { class: 'select sm', style: { width: 'auto' }, 'aria-label': 'How far back', onchange: e => update({ range: e.target.value }) });
  const clearBtn = h('button', { class: 'btn ghost sm', type: 'button', onclick: () => { search.value = ''; orgSel.value = ''; rangeSel.value = 'all'; update({ q: '', org: '', range: 'all', view: 'all' }); } }, 'Clear filters');
  add(bar, [search, orgSel, rangeSel, h('span', { class: 'sp' }), clearBtn]);
  let orgsReady = false, latest = 0;
  async function load() {
    if (mine !== S.renderId) return;
    const turn = ++latest;                                           // an older answer must never replace a newer one
    setQuery({ ...q, view: q.view === 'all' ? '' : q.view, range: q.range === 'all' ? '' : q.range });
    clearBtn.style.display = q.q || q.org || q.view !== 'all' || q.range !== 'all' ? '' : 'none';
    fill(out, h('div', { class: 'empty' }, 'Loading…'));
    try {
      const d = await authApi.get('/activity' + qs({ page: q.page, page_size: 40, view: q.view, q: q.q, org: q.org, range: q.range }));
      if (mine !== S.renderId || turn !== latest) return;
      if (!orgsReady) { orgsReady = true; d.orgs.forEach(o => orgSel.append(h('option', { value: o.key }, o.name))); orgSel.value = q.org || ''; }
      const nameOf = k => orgNameOf(d.orgs, k);
      fill(chips, LOG_VIEWS.map(([key, label]) => h('button', { type: 'button', class: 'chip' + (q.view === key ? ' on' : ''), 'aria-pressed': String(q.view === key), onclick: () => update({ view: key }) }, label + ' ', h('span', { style: { opacity: .7 } }, d.counts[key]))));
      const asked = x => h('div', null, AUDIT_WORDS.ask, h('div', { class: 'sa-ask' }, x.message),
        h('div', { class: 'muted small' }, 'Emailed to ' + (x.emails_sent === x.emails_tried ? plural(x.emails_sent, 'super admin') : x.emails_sent + ' of ' + plural(x.emails_tried, 'super admin'))));
      fill(out, table([
        { label: 'When', render: x => h('span', { class: 'muted' }, fmtDT(x.at)) },
        { label: 'Who', cls: 'wide', render: x => h('div', null, h('b', null, x.who), x.email && x.email !== x.who ? h('div', { class: 'muted small' }, x.email) : null) },
        { label: 'What', cls: 'wide', render: x => x.message != null ? asked(x) : h('div', null, AUDIT_WORDS[x.action] || pretty(x.action), auditNote(x) ? h('div', { class: 'muted small' }, auditNote(x)) : null) },
        { label: 'Organisation', render: x => x.orgs.length ? x.orgs.map(nameOf).join(', ') : h('span', { class: 'muted' }, '—') },
        { label: 'Result', render: x => x.ok ? badge('OK', 'ok') : badge('Failed', 'bad') },
        { label: 'From', render: x => h('span', { class: 'muted small' }, x.ip || '') },
      ], d.rows, { cls: 'logt', emptyTitle: 'Nothing matches', emptyText: 'Try another button, a wider range, or clear the filters.' }), pager(d.total, d.page, d.page_size, p => update({ page: p })));
    } catch (e) { if (turn === latest) fill(out, notice(e.message, 'bad')); }
  }
  await load();
}
const SUPER_SCREENS = { overview: superOverview, orgs: superOrgs, accounts: superAccounts, activity: superActivity };
async function superRoute() {
  const r = parseRoute();
  const key = SUPER_SCREENS[r.section] ? r.section : 'overview';
  const tab = SUPER_TABS.find(t => t[0] === key);
  const mine = ++S.renderId;
  document.querySelectorAll('.nav a').forEach(a => a.classList.toggle('active', a.dataset.key === key));
  document.body.classList.remove('menu-open');
  closePop(); setTopAction(null);
  setCrumbs([h('span', null, tab[1])]);
  document.title = tab[1] + ' · OrchestrAI';
  const sub = { overview: 'Every organisation at a glance', orgs: 'Open any organisation’s dashboard, or give someone access to it', accounts: 'Who can sign in, and to what', activity: 'Every sign-in, every message from an admin, and every change of access' }[key];
  const loading = h('div', { class: 'empty' }, 'Loading…'), content = h('div');
  fill(document.getElementById('main'), h('div', { class: 'screen' }, h('div', { class: 'ph' }, h('div', null, h('h1', null, key === 'overview' ? greeting() + ', ' + firstName(S.me.name) : tab[1]), h('div', { class: 'sub' }, sub))), loading, content));
  try { await SUPER_SCREENS[key](content, r); }
  catch (e) { if (mine === S.renderId) fill(content, errorBox(e, () => superRoute())); }
  loading.remove();
  if (mine === S.renderId) window.scrollTo(0, 0);
}
function superShell() {
  const nav = h('nav', { class: 'nav', 'aria-label': 'Sections' }, h('div', { class: 'navlabel' }, 'OrchestrAI'),
    SUPER_TABS.map(([k, label, ic]) => h('a', { href: '#/' + k, 'data-key': k }, icon(ic), h('span', { class: 'tx' }, label))));
  const side = h('aside', { class: 'side', id: 'side', 'aria-label': 'Main menu' },
    h('div', { class: 'sbrand' }, h('span', { class: 'logo' }, 'O'), h('div', null, h('b', null, 'OrchestrAI'), h('small', null, 'Super admin'))),
    nav, h('div', { class: 'grow' }),
    h('div', { class: 'sidefoot' }, accountChip(),
      h('button', { type: 'button', onclick: () => { S.userRail = !S.userRail; applyRail(); } }, icon('panel'), h('span', { class: 'tx' }, 'Collapse menu')),
      h('button', { type: 'button', onclick: () => applyTheme(currentTheme() === 'dark' ? 'light' : 'dark') }, icon('moon'), h('span', { class: 'tx' }, 'Light / dark'))));
  const top = h('header', { class: 'topbar' },
    h('button', { class: 'iconbtn menubtn', type: 'button', 'aria-label': 'Menu', onclick: () => document.body.classList.toggle('menu-open') }, icon('list')),
    h('div', { class: 'crumbs', id: 'crumbs' }), h('div', { class: 'sp' }), h('span', { id: 'topact' }));
  window.addEventListener('resize', applyRail);
  return h('div', { class: 'app' }, side, h('div', { class: 'col' }, top, h('main', { class: 'main', id: 'main' })));
}
async function startSuperPage(me) {
  if (me.level !== 'super') return startAdminLanding(me);
  fill(document.getElementById('app'), superShell());
  window.addEventListener('hashchange', superRoute);
  await superRoute();
}
// someone who is not a super admin opened /admin: take them to their organisation, or let them choose
function startAdminLanding(me) {
  if (me.orgs.length === 1) { location.replace('/admin/' + encodeURIComponent(me.orgs[0].key)); return; }
  mountAuth(h('div', { class: 'lgn-card' },
    h('h2', null, me.orgs.length ? 'Choose an organisation' : 'No organisation yet'),
    h('p', { class: 'sub' }, me.orgs.length ? 'Signed in as ' + me.name + '.' : 'Your account is not connected to an organisation yet. Ask a super admin.'),
    h('div', { class: 'stack' }, me.orgs.map(o => h('a', { class: 'btn', href: '/admin/' + encodeURIComponent(o.key) }, o.name, icon('arrowr', 'sm')))),
    h('div', { class: 'lgn-back' }, h('a', { href: '#', onclick: e => { e.preventDefault(); signOut(); } }, 'Sign out'))), 'OrchestrAI');
}
// signed in, but this account may not open this organisation
function showNoAccess(me) {
  mountAuth(h('div', { class: 'lgn-card' },
    h('div', { class: 'lgn-hd' }, icon('lock')),
    h('h2', null, 'This account cannot open this organisation'),
    h('p', { class: 'sub' }, 'You are signed in as ' + me.name + ' (' + me.email + ').' + (me.orgs.length ? ' You can open:' : ' Ask a super admin to give you access.')),
    h('div', { class: 'stack' }, me.orgs.map(o => h('a', { class: 'btn', href: '/admin/' + encodeURIComponent(o.key) }, o.name, icon('arrowr', 'sm')))),
    h('div', { class: 'lgn-back' }, h('a', { href: '#', onclick: e => { e.preventDefault(); signOut(); } }, 'Sign out'))), 'OrchestrAI');
}
"""
