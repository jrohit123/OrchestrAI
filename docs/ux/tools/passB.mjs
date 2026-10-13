// Pass B: the eleven novice tasks, driven through the real screens on the made-up society. Records what each screen says and shows.
import fs from 'node:fs';
import { BASE, api, clickText, measure, signIn, sleep } from './lib.mjs';

export const opts = { w: 1280, h: 800, scheme: 'light' };
const OUT = process.env.OUT || '.';

async function settle(b, max = 7000) {
  const t0 = Date.now();
  while (Date.now() - t0 < max) {
    const loading = await b.eval(`return [...document.querySelectorAll('#main .empty, #app .boot')].some(e => /Loading/.test(e.innerText) && e.getBoundingClientRect().height > 0);`);
    if (!loading) break;
    await sleep(120);
  }
  await sleep(350);
}
const TOP = `
  const q = s => [...document.querySelectorAll(s)].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
  const modal = q('.modal').pop(); const pop = q('.pop, .popover, .menu, .ctx').pop(); const drawer = q('.drawer').pop();
  const el = modal || pop || drawer;
  const fields = el ? [...el.querySelectorAll('label, input, select, textarea, button')].filter(e => e.getBoundingClientRect().width > 0).map(e => e.tagName.toLowerCase() + (e.type && e.tagName === 'INPUT' ? '[' + e.type + ']' : '') + ':' + ((e.innerText || e.placeholder || e.value || e.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 50))) : [];
  return { kind: modal ? 'modal' : pop ? 'popup' : drawer ? 'drawer' : 'none', text: el ? el.innerText.slice(0, 1800) : '', fields: fields.slice(0, 60), toasts: q('.toast').map(t => t.innerText) };`;

const R = {};
let clicks = 0;
async function task(b, id, title, fn) {
  clicks = 0;
  const t0 = Date.now();
  try { R[id] = { title, ...(await fn()), clicks, ms: Date.now() - t0 }; }
  catch (e) { R[id] = { title, error: String(e && e.message || e), clicks, ms: Date.now() - t0 }; }
  fs.writeFileSync(OUT + '/passB.json', JSON.stringify(R, null, 1));
}
const click = async (b, text, sel) => { const ok = await clickText(b, text, sel); if (ok) clicks++; await sleep(450); return ok; };
const snap = async (b, name) => { await b.shot('B_' + name); return b.eval(TOP); };

export default async function (b) {
  await signIn(b, 'kavya.rao@ux.test');
  const S = `${BASE}/admin/sunrise`;
  const wf = (await api(b, '/admin/sunrise/api/v2/workflows')).rows || [];
  const flowId = wf.find(f => f.intent_key === 'approve_expense')?.id;
  const visitorId = wf.find(f => f.intent_key === 'visitor_pass')?.id;
  const peopleRows = (await api(b, '/admin/sunrise/api/v2/people?page_size=60')).rows || [];
  const manishId = peopleRows.find(p => p.name === 'Manish Kapoor')?.id;

  // a) add a new tenant who joined flat B-402
  await task(b, 'a', 'Add a tenant who joined flat B-402', async () => {
    await b.goto(`${S}#/overview`, 50); await settle(b);
    await click(b, 'People', 'nav a'); await settle(b);
    await click(b, 'Add person');
    const form = await snap(b, 'a1_add_person');
    // submit empty to see the message
    const submit = await b.eval(`const m = [...document.querySelectorAll('.modal')].pop(); const btns = [...m.querySelectorAll('.mf .btn')]; return btns.map(x => x.innerText);`);
    await b.eval(`const m = [...document.querySelectorAll('.modal')].pop(); const btn = [...m.querySelectorAll('.mf .btn')].find(x => x.classList.contains('primary')); btn && btn.click(); return 1;`); clicks++;
    await sleep(500);
    const empty = await snap(b, 'a2_add_empty');
    return { form, buttons: submit, empty_submit: empty };
  });

  // b) mark a resident as moved out
  await task(b, 'b', 'Mark a resident as moved out', async () => {
    await b.goto(`${S}#/people`, 50); await settle(b);
    await b.goto(`${S}#/people?person=${manishId}`, 50); await settle(b); await sleep(600); clicks += 2;
    const drawer = await snap(b, 'b1_person_drawer');
    const buttons = await b.eval(`return [...document.querySelectorAll('.drawer button, .drawer a')].filter(e => e.getBoundingClientRect().width > 0).map(e => (e.innerText || e.getAttribute('aria-label') || '').trim()).filter(Boolean);`);
    return { drawer, buttons };
  });

  // c) replace the treasurer
  await task(b, 'c', 'Replace the treasurer', async () => {
    await b.goto(`${S}#/overview`, 50); await settle(b);
    await click(b, 'Roles & access', 'nav a'); await settle(b);
    await click(b, 'Seats', '.tabs a'); await settle(b);
    const seats = await snap(b, 'c1_seats');
    // the third "Change holder" button is the Treasurer's
    const p = await b.eval(`const bs = [...document.querySelectorAll('button')].filter(e => e.innerText.trim() === 'Change holder'); const e = bs[2]; if (!e) return null; e.scrollIntoView({block:'center'}); const r = e.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2};`);
    await b.clickAt(p.x, p.y); clicks++; await sleep(600);
    const dlg = await snap(b, 'c2_change_holder');
    return { dialog: dlg };
  });

  // d) create a flow by chat that reads a PDF and needs approval
  await task(b, 'd', 'Create a flow by chat (reads a PDF, needs approval)', async () => {
    await b.goto(`${S}#/overview`, 50); await settle(b);
    await click(b, 'Flows', 'nav a'); await settle(b);
    await click(b, 'New flow');
    const dlg = await snap(b, 'd1_new_flow');
    return { dialog: dlg };
  });

  // e) change who approves, and add a second level (open the step)
  await task(b, 'e', 'Change who approves and add a second level', async () => {
    await b.goto(`${S}#/workflows?w=${flowId}`, 50); await settle(b); await sleep(700);
    const p = await b.eval(`const n = [...document.querySelectorAll('.nd.k-approve, .nd')].find(x => /approval/i.test(x.innerText)); if (!n) return null; n.scrollIntoView({block:'center'}); const r = n.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2};`);
    if (!p) return { note: 'approval step not found' };
    await b.mouse('mouseMoved', p.x, p.y); await b.mouse('mousePressed', p.x, p.y); await b.mouse('mouseReleased', p.x, p.y);
    await b.mouse('mousePressed', p.x, p.y, { clickCount: 2 }); await b.mouse('mouseReleased', p.x, p.y, { clickCount: 2 }); clicks += 2; await sleep(900);
    const win = await b.eval(`const w = [...document.querySelectorAll('aside, .sw, .stepwin, .panel, .nd-win')].filter(e => e.getBoundingClientRect().width > 200).map(e => e.className + ' :: ' + e.innerText.slice(0, 1500)); return win.slice(0, 3);`);
    await b.shot('B_e1_step_window');
    return { windows: win };
  });

  // f) delete a step and undo it
  await task(b, 'f', 'Delete a step and undo it', async () => {
    await b.goto(`${S}#/workflows?w=${flowId}`, 50); await settle(b); await sleep(700);
    const before = await b.eval(`return document.querySelectorAll('.nd:not(.trig):not(.nc-end)').length;`);
    const p = await b.eval(`const m = document.querySelectorAll('.nd .nd-more')[1]; if (!m) return null; const r = m.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2};`);
    await b.clickAt(p.x, p.y); clicks++; await sleep(500);
    const menu = await snap(b, 'f1_step_menu');
    const ok = await click(b, 'Delete', 'button, a, .mi, [role=menuitem], div');
    await sleep(700);
    const after = await b.eval(`return document.querySelectorAll('.nd:not(.trig):not(.nc-end)').length;`);
    const afterTop = await snap(b, 'f2_after_delete');
    let undone = null;
    const hasUndo = await b.eval(`return !![...document.querySelectorAll('.toast button, .tact')].find(e => /undo/i.test(e.innerText));`);
    if (hasUndo) { await click(b, 'Undo', 'button'); await sleep(700); undone = await b.eval(`return document.querySelectorAll('.nd:not(.trig):not(.nc-end)').length;`); }
    return { steps_before: before, menu, clicked_delete: ok, steps_after_delete: after, after: afterTop, undo_button_found: hasUndo, steps_after_undo: undone };
  });

  // g) reuse an existing flow inside a new one: the step picker
  await task(b, 'g', 'Reuse an existing flow (building block) in a flow', async () => {
    await b.goto(`${S}#/workflows?w=${flowId}`, 50); await settle(b); await sleep(700);
    await click(b, 'Add a step', 'button');
    await sleep(500);
    const picker = await snap(b, 'g1_add_step');
    const items = await b.eval(`return [...document.querySelectorAll('.pop button, .popover button, .menu button, .picker button, .pop [role=option]')].map(e => (e.innerText||'').trim().replace(/\\s+/g,' ').slice(0,70)).filter(Boolean).slice(0, 40);`);
    return { picker, items };
  });

  // h) find what someone said and open the whole chat
  await task(b, 'h', 'Find what a user said and open the whole chat', async () => {
    await b.goto(`${S}#/overview`, 50); await settle(b);
    await click(b, 'Conversations', 'nav a'); await settle(b);
    await b.eval(`const i = document.querySelector('input[placeholder^="Search"]'); i.focus(); return 1;`);
    await b.c.send('Input.insertText', { text: 'visitor' }); clicks += 1; await sleep(900);
    const list = await snap(b, 'h1_search');
    const p = await b.eval(`const r0 = [...document.querySelectorAll('#main .row, #main .chatrow, #main li, #main .cv')].filter(e => e.getBoundingClientRect().height > 40)[0]; if (!r0) return null; const r = r0.getBoundingClientRect(); return {x: r.left + 200, y: r.top + r.height / 2, cls: r0.className};`);
    if (p) { await b.clickAt(p.x, p.y); clicks++; await sleep(900); }
    const open = await snap(b, 'h2_transcript');
    return { list_rows_hint: p, list, open };
  });

  // k) turn a flow off safely: what does the switch say?
  await task(b, 'k', 'Turn a flow off safely', async () => {
    await b.goto(`${S}#/workflows`, 50); await settle(b);
    const before = await b.eval(`return [...document.querySelectorAll('#main .card, #main [class*=flowcard], #main article')].slice(0, 3).map(e => e.innerText.slice(0, 120));`);
    // the switch of the "Pre-approve a visitor" card
    const p = await b.eval(`const c = [...document.querySelectorAll('#main *')].find(e => e.children.length > 2 && /Pre-approve a visitor/.test(e.innerText) && e.innerText.length < 400); if (!c) return null; const sw = c.querySelector('.switch, [role=switch], input[type=checkbox], label.sw'); if (!sw) return {noswitch: c.className}; const r = sw.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2, cls: sw.className};`);
    if (p && p.x) { await b.clickAt(p.x, p.y); clicks++; await sleep(700); }
    const after = await snap(b, 'k1_switch_off');
    return { switch_hint: p, before, after };
  });

  // extras: help popover, search box, "Getting set up" pill
  await task(b, 'x', 'Help and words / Search / Getting set up', async () => {
    await b.goto(`${S}#/overview`, 50); await settle(b);
    await click(b, 'Help & words', 'button'); const help = await snap(b, 'x1_help');
    await b.key('Escape');
    await click(b, 'Getting set up · 4 of 5', 'button, a, span'); await sleep(400); const setup = await snap(b, 'x2_setup');
    await b.key('Escape');
    await b.key('k', 2); await sleep(500); const cmd = await snap(b, 'x3_search');
    return { help, setup, cmd };
  });

  return Object.keys(R);
}
