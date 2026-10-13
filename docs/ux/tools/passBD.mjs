// Pass B2 + D: the tasks that did not finish cleanly the first time, and the smaller dashboard an admin gets.
import fs from 'node:fs';
import { BASE, api, clickText, measure, signIn, sleep, PASSWORD } from './lib.mjs';

export const opts = { w: 1280, h: 800, scheme: 'light' };
const OUT = process.env.OUT || '.';

async function settle(b, max = 7000) {
  const t0 = Date.now();
  while (Date.now() - t0 < max) {
    const loading = await b.eval(`return [...document.querySelectorAll('#main .empty, #app .boot')].some(e => /Loading/.test(e.innerText) && e.getBoundingClientRect().height > 0);`);
    if (!loading) break;
    await sleep(120);
  }
  await sleep(400);
}
const fresh = async (b, url) => { await b.goto(url, 50); await b.c.send('Page.reload', {}); await sleep(700); await settle(b); };
const R = {};
let clicks = 0;
async function task(id, title, fn) {
  clicks = 0; const t0 = Date.now();
  try { R[id] = { title, ...(await fn()), clicks, ms: Date.now() - t0 }; } catch (e) { R[id] = { title, error: String(e && e.message || e), clicks, ms: Date.now() - t0 }; }
  fs.writeFileSync(OUT + '/passBD.json', JSON.stringify(R, null, 1));
}
const click = async (b, text, sel) => { const ok = await clickText(b, text, sel); if (ok) clicks++; await sleep(500); return ok; };
const topText = `
  const q = s => [...document.querySelectorAll(s)].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
  const el = q('.modal').pop() || q('.pop, .words, .cmdk, .sw').pop() || q('.drawer').pop() || q('.pal').pop();
  return { cls: el ? el.className : null, text: el ? el.innerText.slice(0, 2200) : '', toasts: q('.toast').map(t => t.innerText) };`;

export default async function (b) {
  await signIn(b, 'kavya.rao@ux.test');
  const S = `${BASE}/admin/sunrise`;
  const wf = (await api(b, '/admin/sunrise/api/v2/workflows')).rows || [];
  const flowId = wf.find(f => f.intent_key === 'approve_expense')?.id;
  const fixedFlow = wf.find(f => f.intent_key === 'close_a_case')?.id;
  const ppl = (await api(b, '/admin/sunrise/api/v2/people?page_size=60')).rows || [];
  const manishId = ppl.find(p => p.name === 'Manish Kapoor')?.id;
  const farah = ppl.find(p => p.name === 'Farah Sheikh');
  R._farah_row = farah ? { role: farah.role, keys: Object.keys(farah) } : null;

  await task('b', 'Mark a resident as moved out (person window)', async () => {
    await fresh(b, `${S}#/people?person=${manishId}`); await sleep(600);
    await b.shot('D_b1_person_clean');
    const home = await b.eval(`const sels = [...document.querySelectorAll('.drawer select')].map(s => ({opts: [...s.options].map(o => o.text), value: s.options[s.selectedIndex]?.text})); return sels;`);
    const text = await b.eval(`return (document.querySelector('.drawer')?.innerText || '').slice(0, 2500);`);
    return { selects: home, text };
  });

  await task('c', 'Replace the treasurer (Change holder)', async () => {
    await fresh(b, `${S}#/access/seats`);
    const p = await b.eval(`const bs = [...document.querySelectorAll('button')].filter(e => e.innerText.trim() === 'Change holder'); const e = bs[2]; if (!e) return {n: bs.length}; e.scrollIntoView({block:'center'}); const r = e.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2, n: bs.length};`);
    if (!p.x) return { note: 'no button', p };
    await b.clickAt(p.x, p.y); clicks++; await sleep(700);
    await b.shot('D_c2_change_holder');
    return { dialog: await b.eval(topText) };
  });

  await task('e', 'Change who approves / second level (step window)', async () => {
    await fresh(b, `${S}#/workflows?w=${flowId}`); await sleep(900);
    const p = await b.eval(`const n = [...document.querySelectorAll('.nd')].find(x => /Ask for approval/i.test(x.innerText)); if (!n) return null; const r = n.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2};`);
    if (!p) return { note: 'step not found' };
    await b.mouse('mouseMoved', p.x, p.y);
    await b.c.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: p.x, y: p.y, button: 'left', buttons: 1, clickCount: 2 });
    await b.c.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: p.x, y: p.y, button: 'left', buttons: 0, clickCount: 2 });
    clicks += 2; await sleep(1000);
    await b.shot('D_e1_step_window');
    return { window: await b.eval(`const w = document.querySelector('.sw'); return w ? w.innerText.slice(0, 2500) : null;`) };
  });

  await task('g', 'Add a step: the palette (building blocks)', async () => {
    await fresh(b, `${S}#/workflows?w=${fixedFlow}`); await sleep(800);
    await click(b, 'Add a step', 'button'); await sleep(700);
    await b.shot('D_g1_palette');
    const pal = await b.eval(`const p = document.querySelector('.pal'); return p ? p.innerText.slice(0, 3000) : null;`);
    return { palette: pal };
  });

  await task('k', 'Turn a flow off: the switch on a card', async () => {
    await fresh(b, `${S}#/workflows`);
    const p = await b.eval(`const a = [...document.querySelectorAll('article')].find(x => /Pre-approve a visitor/.test(x.innerText)); if (!a) return null; const sw = a.querySelector('.switch'); a.scrollIntoView({block:'center'}); const r = sw.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height};`);
    if (!p) return { note: 'no card' };
    await b.clickAt(p.x, p.y); clicks++; await sleep(900);
    await b.shot('D_k1_after_switch');
    const out = await b.eval(topText);
    const state = await b.eval(`const a = [...document.querySelectorAll('article')].find(x => /Pre-approve a visitor/.test(x.innerText)); return a ? a.innerText.replace(/\\n/g, ' | ') : null;`);
    return { target: p, after: out, card: state };
  });

  await task('x', 'Help and words / the search box', async () => {
    await fresh(b, `${S}#/overview`);
    await click(b, 'Help & words', 'button');
    await b.shot('D_x1_help');
    const help = await b.eval(topText);
    await b.key('Escape');
    await b.c.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'k', code: 'KeyK', windowsVirtualKeyCode: 75, modifiers: 2 });
    await b.c.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'k', code: 'KeyK', windowsVirtualKeyCode: 75, modifiers: 2 });
    await sleep(700); await b.shot('D_x2_search');
    return { help, search: await b.eval(topText) };
  });

  await task('d2', 'New flow by chat: describe it and draft it', async () => {
    await fresh(b, `${S}#/workflows`);
    await click(b, 'New flow');
    await b.eval(`const t = document.querySelector('.modal textarea'); t.focus(); return 1;`);
    await b.c.send('Input.insertText', { text: 'When someone sends a PDF bill, read the vendor and the amount, and ask the treasurer to approve it before anything is saved.' });
    await click(b, 'Draft it', '.modal button');
    await sleep(2500);
    await b.shot('D_d2_drafted');
    return { after: await b.eval(topText), page: await b.eval(`return (document.getElementById('main')?.innerText || '').slice(0, 1200);`) };
  });

  await task('try', 'Try it (rehearsal) in the editor', async () => {
    await fresh(b, `${S}#/workflows?w=${fixedFlow}`); await sleep(800);
    await click(b, 'Try it', 'button'); await sleep(900);
    await b.shot('D_try1');
    return { text: await b.eval(`return (document.querySelector('.insp, aside.insp, .inspector')?.innerText || document.body.innerText).slice(0, 1800);`) };
  });

  await task('ai', 'Ask the AI helper to change this flow', async () => {
    await fresh(b, `${S}#/workflows?w=${fixedFlow}`); await sleep(800);
    await click(b, 'Ask the AI helper to change this flow', 'button'); await sleep(900);
    await b.shot('D_ai1');
    return { text: await b.eval(`return [...document.querySelectorAll('aside, .cvchat, .ai, .assist')].map(e => e.className + ' :: ' + e.innerText.slice(0, 900)).slice(-2);`) };
  });

  await task('resp', 'Response times: a Low priority faster than Urgent', async () => {
    await fresh(b, `${S}#/rules/times`);
    // type 5 into the Low target box (should be slower than Urgent's 120) and save
    await b.eval(`const ins = [...document.querySelectorAll('input')].filter(i => i.getBoundingClientRect().width > 0); window.__ins = ins.length; ins[6].focus(); ins[6].select(); return ins.length;`);
    await b.c.send('Input.insertText', { text: '5' });
    await click(b, 'Save response times', 'button'); await sleep(900);
    await b.shot('D_resp1');
    return { toasts: await b.eval(`return [...document.querySelectorAll('.toast')].map(t => t.innerText);`), note: await b.eval(`return [...document.querySelectorAll('#main .notice, #main .err, #main .hint')].map(e => e.innerText).slice(0, 6);`), values: await b.eval(`return [...document.querySelectorAll('#main input')].map(i => i.value);`) };
  });

  // ---------------- the smaller dashboard an admin gets, and what a stranger sees
  const adminRun = async (email, label, url) => {
    await b.goto(BASE + '/admin', 300);
    await b.eval(`await fetch('/admin/_auth/sign-out', {method: 'POST', headers: {'X-Panel': '1'}}); return 1;`);
    await signIn(b, email);
    await fresh(b, BASE + '/admin'); await b.shot(`D_${label}_landing`);
    const landing = await b.eval(`return (document.getElementById('app')?.innerText || '').slice(0, 900);`);
    await fresh(b, url); await b.shot(`D_${label}_dash`);
    const m = await measure(b);
    const nav = await b.eval(`return [...document.querySelectorAll('.nav a')].map(a => a.innerText.trim().replace(/\\s+/g, ' '));`);
    return { landing, nav, h1: m.h1, interactive: m.interactive };
  };
  await task('admin_meena', 'Admin of one society (secretary)', () => adminRun('meena.kulkarni@ux.test', 'meena', `${S}#/overview`));
  await task('admin_meena_cases', 'Admin: cases and assign', async () => {
    await fresh(b, `${S}#/cases`); await b.shot('D_meena_cases');
    await click(b, 'Assign', 'button'); await sleep(700); await b.shot('D_meena_assign');
    return { dialog: await b.eval(topText) };
  });
  await task('admin_sam', 'Admin of two organisations', () => adminRun('sam.thomas@ux.test', 'sam', `${S}#/overview`));
  await task('no_access', 'Admin opens an organisation that is not hers', async () => {
    await signIn(b, 'meena.kulkarni@ux.test');
    await fresh(b, `${BASE}/admin/zari#/overview`); await b.shot('D_noaccess');
    return { text: await b.eval(`return (document.getElementById('app')?.innerText || '').slice(0, 600);`) };
  });
  await task('wrong_address', 'A wrong organisation address', async () => {
    await b.goto(`${BASE}/admin/nosuchplace`, 900); await b.shot('D_404');
    return { text: await b.eval(`return document.body.innerText.slice(0, 300);`) };
  });
  await task('signup_forgot', 'First visit: Sign up and Forgot password screens', async () => {
    await b.goto(BASE + '/admin', 300);
    await b.eval(`await fetch('/admin/_auth/sign-out', {method: 'POST', headers: {'X-Panel': '1'}}); return 1;`);
    await fresh(b, BASE + '/admin');
    await click(b, 'Sign up', 'a, button'); await sleep(500); await b.shot('D_signup');
    const up = await b.eval(`return (document.getElementById('app')?.innerText || '').slice(0, 900);`);
    await fresh(b, BASE + '/admin');
    await click(b, 'Forgot password?', 'a, button'); await sleep(500); await b.shot('D_forgot');
    const fg = await b.eval(`return (document.getElementById('app')?.innerText || '').slice(0, 700);`);
    // a wrong password
    await fresh(b, BASE + '/admin');
    await b.eval(`const i = document.querySelectorAll('input'); i[0].focus(); return 1;`); await b.c.send('Input.insertText', { text: 'meena.kulkarni@ux.test' });
    await b.eval(`const i = document.querySelectorAll('input'); i[1].focus(); return 1;`); await b.c.send('Input.insertText', { text: 'wrong-password-1' });
    await click(b, 'Sign in', 'button'); await sleep(1200); await b.shot('D_wrongpw');
    const wp = await b.eval(`return (document.getElementById('app')?.innerText || '').slice(0, 900);`);
    return { signup: up, forgot: fg, wrong_password: wp };
  });
  return Object.keys(R);
}
