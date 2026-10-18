JS = r"""
// ───────────────────────── signing in ─────────────────────────
// Who is signed in is decided by the server, with a cookie this page cannot read. This part draws the
// sign-in, sign-up and forgot-password pages and the small account menu. The pages are the same for
// every organisation; the address (/admin/godrej) only decides which name they show.
const AUTH = '/admin/_auth';
const authApi = {
  get: p => request(AUTH + p, { quiet401: true }),
  post: (p, b) => request(AUTH + p, { method: 'POST', body: b === undefined ? {} : b, quiet401: true }),
};
async function authMe() {
  try { return (await request(AUTH + '/me', { quiet401: true })).account; }
  catch (e) { if (e.status === 401) return null; throw e; }
}
const isSuper = () => !!(S.me && S.me.level === 'super');
const hasSection = key => !!(S.boot && S.boot.sections.some(s => s.key === key));
const q1 = (sel, root) => (root || document).querySelector(sel);
const firstName = n => String(n || '').split(/\s+/)[0] || '';

const A = { view: 'signin', email: '', password: '', code: '', pw1: '', pw2: '', error: '', info: '', busy: false, org: null, stay: false };
let heroNode = null, storyTimers = [], storyOn = false;

function themeButton() { return h('button', { class: 'btn ghost sm lgn-theme', type: 'button', onclick: () => applyTheme(currentTheme() === 'dark' ? 'light' : 'dark') }, icon('moon', 'sm'), 'Light / dark'); }

// the little story on the left: someone writes to the chat bot, the request is logged and handed to a person
function stopStory() { storyTimers.forEach(clearTimeout); storyTimers = []; storyOn = false; }
function startStory(stage) {
  const body = q1('.bd', stage), n = q1('.n', stage), chip = q1('.lgn-chip', stage);
  const later = (ms, fn) => storyTimers.push(setTimeout(fn, ms));
  const say = (cls, kids) => { const b = h('div', { class: 'b ' + cls }, kids); body.append(b); return b; };
  const typing = () => say('out typing', [h('i'), h('i'), h('i')]);
  const noTyping = () => { const t = q1('.typing', body); if (t) t.remove(); };
  const asked = () => say('in', 'My order has not arrived yet.');
  const filed = () => say('out', ['✅ Request ', h('b', null, 'R-1042'), ' logged. Priority: high.']);
  const given = () => say('out', ['👷 Passed to ', h('b', null, 'Sunita Joshi'), '. She will get back to you today.']);
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { asked(); filed(); given(); n.textContent = '3'; chip.classList.add('on'); return; }
  const run = () => {
    clear(body); n.textContent = '4'; chip.classList.remove('on'); n.classList.remove('tick');
    later(600, asked); later(1600, typing);
    later(3000, () => { noTyping(); filed(); });
    later(4300, typing);
    later(5700, () => { noTyping(); given(); n.textContent = '3'; n.classList.add('tick'); chip.classList.add('on'); });
    later(11500, run);
  };
  run();
}
function authHero() {
  if (heroNode) return heroNode;
  const org = A.org;
  const stage = h('div', { class: 'lgn-stage', 'aria-hidden': 'true' },
    h('div', { class: 'lgn-phone' }, h('div', { class: 'hd' }, h('span', { class: 'av' }, org ? org.name[0] : 'O'), h('div', null, h('b', null, org ? org.name : 'Your chat bot'), h('small', null, 'chat bot · online'))), h('div', { class: 'bd' })),
    h('div', { class: 'lgn-glass lgn-needs' }, h('span', { class: 'ic' }, icon('usercheck')), h('div', null, h('b', null, h('span', { class: 'n' }, '4'), ' requests have no one handling them'), h('small', null, 'They wait until someone takes them.'))),
    h('div', { class: 'lgn-glass lgn-chip' }, icon('ok', 'sm'), h('span', null, 'R-1042 is now with ', h('b', null, 'Sunita Joshi'))));
  heroNode = h('section', { class: 'lgn-hero', 'aria-label': 'About OrchestrAI' },
    h('span', { class: 'lgn-orb a' }), h('span', { class: 'lgn-orb b' }),
    h('div', { class: 'lgn-brand' }, h('span', { class: 'lgn-mark' }, icon('spark')), 'OrchestrAI'),
    h('div', null, h('h1', null, 'Your chat bot, ', h('em', null, 'under your control.')), h('p', { class: 'lgn-lead' }, 'People talk to it on Telegram and WhatsApp. You run everything from here: who can do what, and every request.')),
    stage,
    h('div', { class: 'lgn-points' }, h('div', null, icon('shield', 'sm'), 'Two levels of access'), h('div', null, icon('hist', 'sm'), 'Every sign-in recorded'), h('div', null, icon('usercheck', 'sm'), 'Hand work to a person in one click')),
    h('div', { class: 'lgn-orgs' }, org ? [h('span', { class: 'logo' }, org.name[0]), 'The dashboard for ' + org.name] : 'The control room for every organisation'));
  return heroNode;
}

const authError = () => A.error ? h('div', { class: 'notice bad', role: 'alert' }, icon('warn', 'sm'), A.error) : null;
const authInfo = () => A.info ? h('div', { class: 'notice ok', role: 'status' }, icon('ok', 'sm'), A.info) : null;
const authLink = (text, view, extra) => h('a', { href: '#', onclick: e => { e.preventDefault(); Object.assign(A, { view, error: '', info: '', code: '', pw1: '', pw2: '' }, extra || {}); renderAuth(); } }, text);
async function submitAuth(btn, label, run) {
  if (A.busy) return;                       // Enter pressed twice must not send twice
  A.busy = true; btn.disabled = true; btn.classList.add('busy'); btn.firstChild.textContent = label;
  try { await run(); }
  catch (e) { A.error = e.message || 'Something went wrong. Try again.'; A.info = ''; renderAuth(); }
  finally { A.busy = false; }
}
const goButton = text => h('button', { class: 'btn primary lgn-go', type: 'submit' }, h('span', null, text), icon('arrowr', 'sm'));
function passwordInput(value, onInput, o) {
  o = o || {};
  const pw = h('input', { type: 'password', value, autocomplete: o.autocomplete || 'current-password', placeholder: o.placeholder || 'Your password', 'data-focus': o.focus ? '1' : null, oninput: e => onInput(e.target.value) });
  const eye = h('button', { class: 'lgn-eye', type: 'button', 'aria-label': 'Show or hide the password', onclick: () => { pw.type = pw.type === 'password' ? 'text' : 'password'; pw.focus(); } }, icon('eye', 'sm'));
  return { el: h('div', { class: 'lgn-in' }, icon('lock', 'sm'), pw, eye), input: pw };
}
function emailInput(focus) {
  return h('div', { class: 'lgn-in' }, icon('mail', 'sm'), h('input', { type: 'email', value: A.email, autocomplete: 'username', placeholder: 'you@example.com', 'data-focus': focus ? '1' : null, oninput: e => { A.email = e.target.value; } }));
}
// "choose a password": two boxes and the rules ticking as you type
function newPasswordFields() {
  const a = passwordInput(A.pw1, v => { A.pw1 = v; paint(); }, { autocomplete: 'new-password', placeholder: 'At least 10 characters' });
  const b = passwordInput(A.pw2, v => { A.pw2 = v; paint(); }, { autocomplete: 'new-password', placeholder: 'Type it again' });
  const rules = h('div', { class: 'lgn-rules' });
  function paint() {
    const ok = [[A.pw1.length >= 10, 'At least 10 characters'], [!!A.pw2 && A.pw1 === A.pw2, 'Both boxes match']];
    fill(rules, ok.map(([good, text]) => h('div', { class: good ? 'ok' : '' }, icon(good ? 'ok' : 'minus', 'sm'), text)));
  }
  paint();
  return [field('New password', a.el), field('Repeat it', b.el), rules];
}
function checkNewPassword() {
  if (A.pw1.length < 10) throw new Error('Use at least 10 characters.');
  if (A.pw1 !== A.pw2) throw new Error('The two passwords are not the same.');
}
function codeInput(focus) {
  return h('input', { type: 'text', class: 'lgn-code', inputmode: 'numeric', maxlength: '6', autocomplete: 'one-time-code', value: A.code, placeholder: '••••••', 'aria-label': '6-digit code', 'data-focus': focus ? '1' : null,
    oninput: e => { A.code = e.target.value.replace(/\D/g, '').slice(0, 6); e.target.value = A.code; } });
}
// An admin who signs in from an organisation's own address lands on the Organisations page, so she sees
// which organisations her account may open. A session that only ended returns to where she was.
function signedIn(account) {
  stopStory();
  if (ORG && account.level !== 'super' && !A.stay) { location.href = '/admin'; return; }
  location.reload();
}

function signInCard() {
  const pw = passwordInput(A.password, v => { A.password = v; }, { focus: !!A.email });
  const go = goButton('Sign in');
  return h('form', { class: 'lgn-card', novalidate: true, onsubmit: e => { e.preventDefault(); submitAuth(go, 'Signing in…', async () => {
    A.error = ''; A.info = '';
    const r = await authApi.post('/sign-in', { email: A.email, password: A.password });
    signedIn(r.account);
  }); } },
    h('h2', null, 'Welcome back'),
    h('p', { class: 'sub' }, A.org ? 'Sign in to continue to ' + A.org.name + '.' : 'Sign in to continue.'),
    authInfo(), authError(),
    field('Email', emailInput(!A.email)),
    field('Password', pw.el),
    h('div', { class: 'lgn-row' }, h('span'), authLink('Forgot password?', 'forgot1')),
    go,
    h('div', { class: 'lgn-secure' }, icon('lock', 'sm'), 'Protected sign-in. Every sign-in is recorded.'),
    h('div', { class: 'lgn-swap' }, 'First time here? ', authLink('Sign up', 'signup1')));
}
function signUp1Card() {
  const go = goButton('Send me a code');
  return h('form', { class: 'lgn-card', novalidate: true, onsubmit: e => { e.preventDefault(); submitAuth(go, 'Sending…', async () => {
    const r = await authApi.post('/sign-up/code', { email: A.email });
    Object.assign(A, { view: 'signup2', code: '', pw1: '', pw2: '', error: '', info: r.message });
    renderAuth();
  }); } },
    h('div', { class: 'lgn-steps' }, h('i', { class: 'on' }), h('i'), h('i')),
    h('div', { class: 'lgn-hd' }, icon('usercheck')),
    h('h2', null, 'Sign up'),
    h('p', { class: 'sub' }, 'Only people a super admin has added can sign up. Use the email address they gave. We email you a code, then you choose a password.'),
    authError(),
    field('Your email', emailInput(true)),
    go,
    h('div', { class: 'lgn-back' }, authLink('← Back to sign in', 'signin')));
}
function signUp2Card() {
  const go = goButton('Create my account');
  return h('form', { class: 'lgn-card', novalidate: true, onsubmit: e => { e.preventDefault(); submitAuth(go, 'Saving…', async () => {
    checkNewPassword();
    const r = await authApi.post('/sign-up', { email: A.email, code: A.code, password: A.pw1 });
    signedIn(r.account);
  }); } },
    h('div', { class: 'lgn-steps' }, h('i', { class: 'on' }), h('i', { class: 'on' }), h('i')),
    h('div', { class: 'lgn-hd' }, icon('key')),
    h('h2', null, 'Check your email'),
    h('p', { class: 'sub' }, 'Type the 6-digit code we sent to ' + (A.email || 'you') + ', then choose your password.'),
    authInfo(), authError(),
    field('6-digit code', codeInput(true)),
    newPasswordFields(),
    go,
    h('div', { class: 'lgn-back' }, authLink('← Start again', 'signup1')));
}
function forgot1Card() {
  const go = goButton('Send me a code');
  return h('form', { class: 'lgn-card', novalidate: true, onsubmit: e => { e.preventDefault(); submitAuth(go, 'Sending…', async () => {
    const r = await authApi.post('/forgot/code', { email: A.email });
    Object.assign(A, { view: 'forgot2', code: '', pw1: '', pw2: '', error: '', info: r.message });
    renderAuth();
  }); } },
    h('div', { class: 'lgn-hd' }, icon('key')),
    h('h2', null, 'Forgot your password?'),
    h('p', { class: 'sub' }, 'Type your email. We send you a 6-digit code, and you choose a new password.'),
    authError(),
    field('Your email', emailInput(true)),
    go,
    h('div', { class: 'lgn-back' }, authLink('← Back to sign in', 'signin')));
}
function forgot2Card() {
  const go = goButton('Save the new password');
  return h('form', { class: 'lgn-card', novalidate: true, onsubmit: e => { e.preventDefault(); submitAuth(go, 'Saving…', async () => {
    checkNewPassword();
    await authApi.post('/forgot', { email: A.email, code: A.code, password: A.pw1 });
    Object.assign(A, { view: 'signin', password: '', code: '', pw1: '', pw2: '', error: '', info: 'Your password was changed. Sign in with the new one.' });
    renderAuth();
  }); } },
    h('div', { class: 'lgn-hd' }, icon('key')),
    h('h2', null, 'Choose a new password'),
    h('p', { class: 'sub' }, 'Type the 6-digit code we sent to ' + (A.email || 'you') + ', then the new password. Every browser that was signed in will be signed out.'),
    authInfo(), authError(),
    field('6-digit code', codeInput(true)),
    newPasswordFields(),
    go,
    h('div', { class: 'lgn-back' }, authLink('← Back to sign in', 'signin')));
}
const AUTH_CARDS = { signin: signInCard, signup1: signUp1Card, signup2: signUp2Card, forgot1: forgot1Card, forgot2: forgot2Card };
// the page around a card: the story on the left (a plain banner on a phone), the card on the right
function mountAuth(card, name) {
  const mini = h('div', { class: 'lgn-mini' }, h('span', { class: 'lgn-mark' }, icon('spark')), h('div', null, h('b', null, name), h('small', null, 'Your chat bot, under your control.')));
  fill(document.getElementById('app'), h('div', { class: 'lgn' }, authHero(), h('main', { class: 'lgn-main' }, themeButton(), mini, card, poweredBy('lgn-by'))));
  if (!storyOn) { storyOn = true; startStory(q1('.lgn-stage', heroNode)); }
  const target = q1('[data-focus]'); if (target) target.focus();
}
function renderAuth() {
  const name = A.org ? A.org.name : 'OrchestrAI';
  document.title = 'Sign in · ' + name;
  mountAuth(AUTH_CARDS[A.view](), name);
}
async function showSignIn(message) {
  Object.assign(A, { view: 'signin', password: '', code: '', pw1: '', pw2: '', error: '', info: message || '', stay: !!message });
  if (ORG && !A.org) { try { A.org = await authApi.get('/org/' + encodeURIComponent(ORG)); } catch (e) { /* the page works without the name */ } }
  renderAuth();
}
// a call came back "not signed in": the session ended (idle too long, switched off, signed out elsewhere)
let sessionIsOver = false;
function sessionEnded() {
  if (sessionIsOver) return;
  sessionIsOver = true;
  closePop(); closeDrawer(true);
  showSignIn('Your session ended. Please sign in again.');
}
async function signOut() {
  try { await authApi.post('/sign-out'); } catch (e) { /* the cookie ends on its own */ }
  location.href = '/admin';
}

// a plain, labelled Sign out button in the menu (it is also in the account menu)
// "Powered by aitamate": under the sign-in card and at the bottom of the menu
const poweredBy = cls => h('a', { class: cls, href: 'https://aitamate.com/', target: '_blank', rel: 'noopener', title: 'aitamate.com' }, h('span', { class: 'tx' }, 'Powered by'), h('span', { class: 'brandchip' }, h('img', { src: '/admin-assets/aitamate-logo.png', alt: 'aitamate', height: 24 })));
const signOutButton = () => h('button', { type: 'button', title: 'Sign out', onclick: signOut }, icon('signout'), h('span', { class: 'tx' }, 'Sign out'));
// the person's button at the bottom of the menu
function accountChip() {
  const m = S.me, word = isSuper() ? 'Super admin' : 'Admin';
  return h('button', { class: 'acct', type: 'button', 'data-popkeep': '1', 'aria-label': 'Your account', onclick: e => openPop(e.currentTarget, h('div', { class: 'acctpop' },
    h('div', { class: 'me' }, h('b', null, m.name), h('small', null, m.email), h('div', { style: { marginTop: '6px' } }, badge(word, 'brand'))),
    ORG ? h('a', { class: 'mi', href: '/admin' }, icon('globe'), isSuper() ? 'All organisations' : 'My organisations') : null,
    h('button', { class: 'mi', type: 'button', onclick: signOut }, icon('lock'), 'Sign out')), { up: true, width: 250 }) },
    avatar(m.name), h('span', { class: 'who tx' }, h('b', null, m.name), h('small', null, word)));
}
"""
