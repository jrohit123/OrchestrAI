// Pass F: small checks that turn "read from code" into "seen in the running screen".
import fs from 'node:fs';
import { BASE, api, clickText, signIn, sleep } from './lib.mjs';

export const opts = { w: 1280, h: 800, scheme: 'light' };
const OUT = process.env.OUT || '.';
const R = {};
async function settle(b, max = 7000) {
  const t0 = Date.now();
  while (Date.now() - t0 < max) {
    const l = await b.eval(`return [...document.querySelectorAll('#main .empty, #app .boot')].some(e => /Loading/.test(e.innerText) && e.getBoundingClientRect().height > 0);`);
    if (!l) break; await sleep(120);
  }
  await sleep(400);
  return Date.now() - t0;
}
const fresh = async (b, url) => { await b.goto(url, 50); await b.c.send('Page.reload', {}); await sleep(700); return settle(b); };
async function tab(b, n) {
  const seq = [];
  for (let i = 0; i < n; i++) {
    const p = { key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 };
    await b.c.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...p }); await b.c.send('Input.dispatchKeyEvent', { type: 'keyUp', ...p }); await sleep(40);
    seq.push(await b.eval(`const e = document.activeElement; return { tag: e.tagName.toLowerCase(), inModal: !!e.closest('.modal'), inDrawer: !!e.closest('.drawer'), name: (e.innerText || e.getAttribute('aria-label') || e.placeholder || '').trim().slice(0, 24) };`));
  }
  return seq;
}
const attrs = sel => `const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; return { role: e.getAttribute('role'), ariaModal: e.getAttribute('aria-modal'), labelledby: e.getAttribute('aria-labelledby'), label: e.getAttribute('aria-label'), live: e.getAttribute('aria-live'), closeLabel: (e.querySelector('.x') || {}).getAttribute ? e.querySelector('.x').getAttribute('aria-label') : null, active: document.activeElement.tagName.toLowerCase() + '.' + (document.activeElement.className || '') };`;

export default async function (b) {
  await signIn(b, 'kavya.rao@ux.test');
  const S = `${BASE}/admin/sunrise`;
  const wf = (await api(b, '/admin/sunrise/api/v2/workflows')).rows || [];
  const longFlow = wf.find(f => f.intent_key === 'long_flow')?.id;
  const closeId = wf.find(f => f.intent_key === 'close_a_case')?.id;
  const ppl = (await api(b, '/admin/sunrise/api/v2/people?page_size=60')).rows || [];
  const aarav = ppl.find(p => p.name === 'Aarav Shah')?.id;

  // 1. the Add person dialog: what a screen reader and the keyboard get
  await fresh(b, `${S}#/people`);
  await clickText(b, 'Add person'); await sleep(600);
  R.modal_attrs = await b.eval(attrs('.modal'));
  R.modal_tab_trap = (await tab(b, 14)).map(s => (s.inModal ? 'in' : 'OUT') + ':' + s.tag);
  // duplicate e-mail
  await b.eval(`const m = document.querySelector('.modal'); const i = m.querySelectorAll('input'); i[0].focus(); return 1;`); await b.c.send('Input.insertText', { text: 'Dup Test' });
  await b.eval(`const m = document.querySelector('.modal'); const i = m.querySelectorAll('input'); i[1].focus(); return 1;`); await b.c.send('Input.insertText', { text: 'aarav.shah@example.test' });
  await b.eval(`const s = document.querySelector('.modal select'); s.value = [...s.options].find(o => o.text === 'Tenant').value; s.dispatchEvent(new Event('change')); return 1;`);
  await clickText(b, 'Add person', '.modal .mf button'); await sleep(900);
  R.duplicate_message = await b.eval(`return document.querySelector('.modal .err')?.innerText || null;`);
  await b.shot('F_duplicate');
  await b.key('Escape'); await sleep(400);
  R.focus_after_close = await b.eval(`return document.activeElement.tagName.toLowerCase() + ':' + (document.activeElement.innerText || '').trim().slice(0, 20);`);

  // 2. the person window (drawer) and the Back button
  await fresh(b, `${S}#/people?person=${aarav}`); await sleep(500);
  R.drawer_attrs = await b.eval(attrs('.drawer'));
  R.drawer_tab = (await tab(b, 10)).map(s => (s.inDrawer ? 'in' : 'OUT') + ':' + s.tag);
  await b.key('Escape'); await sleep(500);
  R.after_escape_hash = await b.eval(`return location.hash;`);
  await fresh(b, `${S}#/cases`);
  const firstRow = await b.eval(`const r = [...document.querySelectorAll('#main .row, #main tr')].filter(e => e.getBoundingClientRect().height > 40 && /SH-26/.test(e.innerText))[0]; if (!r) return null; const q = r.getBoundingClientRect(); return {x: q.left + 200, y: q.top + q.height / 2};`);
  if (firstRow) { await b.clickAt(firstRow.x, firstRow.y); await sleep(900); }
  R.drawer_open_after_click = await b.eval(`return !!document.querySelector('.drawer') && location.hash;`);
  await b.eval(`history.back(); return 1;`); await sleep(900);
  R.drawer_open_after_back = await b.eval(`return !!document.querySelector('.drawer') + ' ' + location.hash;`);

  // 3. a message toast: save the response times unchanged
  await fresh(b, `${S}#/rules/times`);
  await clickText(b, 'Save response times', 'button'); await sleep(700);
  R.toast = await b.eval(`const t = document.querySelector('.toast'); const box = document.querySelector('.toasts'); return t ? { text: t.innerText, role: t.getAttribute('role'), live: t.getAttribute('aria-live'), boxRole: box && box.getAttribute('role'), boxLive: box && box.getAttribute('aria-live') } : null;`);

  // 4. the editor: unsaved changes warning, and a flow with 35 steps
  await fresh(b, `${S}#/workflows?w=${closeId}`); await sleep(700);
  const p = await b.eval(`const m = document.querySelectorAll('.nd .nd-more')[1]; if (!m) return null; const r = m.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2};`);
  if (p) { await b.clickAt(p.x, p.y); await sleep(400); await clickText(b, 'Delete', 'button, a, [role=menuitem], div'); await sleep(600); }
  R.unsaved_guard = await b.eval(`return { onbeforeunload: typeof window.onbeforeunload, badge: [...document.querySelectorAll('.badge, span')].some(e => /Unsaved/.test(e.innerText)) };`);
  const t0 = Date.now();
  const ms = await fresh(b, `${S}#/workflows?w=${longFlow}`); await sleep(1200);
  R.long_flow = await b.eval(`return { nodes: document.querySelectorAll('.nd').length, dom: document.getElementsByTagName('*').length, zoom: (document.querySelector('.cvbar, .zoomlbl, [class*=zoom]') || {}).innerText || null };`);
  R.long_flow_ms = Date.now() - t0;
  await b.shot('F_long_flow_1280');
  await b.view(360, 640, 'light'); await sleep(600); await b.shot('F_long_flow_360');
  await b.view(1280, 800, 'light');

  // 5. very long names in the lists
  await fresh(b, `${S}#/people`);
  await b.eval(`const i = document.querySelector('input[placeholder^="Search"]'); i.focus(); return 1;`); await b.c.send('Input.insertText', { text: 'Venkateswaran' }); await sleep(900);
  await b.shot('F_long_person_1280');
  await b.view(360, 640, 'light'); await sleep(500); await b.shot('F_long_person_360'); await b.view(1280, 800, 'light');
  await fresh(b, `${S}#/workflows`);
  await clickText(b, 'Building blocks', 'button, a, .tab'); await sleep(700);
  R.blocks_text = await b.eval(`return (document.getElementById('main')?.innerText || '').slice(0, 900);`);
  await b.shot('F_blocks_tab');
  // delete a flow that is switched off: what does the screen say?
  await clickText(b, 'Flows', '.tabs button, .tabs a, .tab'); await sleep(600);
  const del = await b.eval(`const a = [...document.querySelectorAll('article')].find(x => /Dues reminder/.test(x.innerText)); if (!a) return null; const btn = [...a.querySelectorAll('button, a')].find(x => /Delete/.test(x.innerText)); if (!btn) return {nobtn: a.innerText}; btn.scrollIntoView({block:'center'}); const r = btn.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2};`);
  if (del && del.x) { await b.clickAt(del.x, del.y); await sleep(700); R.delete_dialog = await b.eval(`const m = document.querySelector('.modal'); return m ? m.innerText : null;`); await b.shot('F_delete_dialog'); await b.key('Escape'); }
  fs.writeFileSync(OUT + '/passF.json', JSON.stringify(R, null, 1));
  return Object.keys(R);
}
