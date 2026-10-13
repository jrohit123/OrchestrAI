import fs from 'node:fs';
import { BASE, api, clickText, signIn, sleep } from './lib.mjs';
export const opts = { w: 1280, h: 800, scheme: 'light' };
export default async function (b) {
  const R = {};
  await signIn(b, 'kavya.rao@ux.test');
  const wf = (await api(b, '/admin/sunrise/api/v2/workflows')).rows || [];
  const flowId = wf.find(f => f.intent_key === 'approve_expense')?.id;
  await b.goto(`${BASE}/admin/sunrise#/workflows?w=${flowId}`, 50); await b.c.send('Page.reload', {}); await sleep(1800);
  const p = await b.eval(`const n = [...document.querySelectorAll('.nd')].find(x => /Starts when/i.test(x.innerText)); const r = n.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2};`);
  await b.mouse('mouseMoved', p.x, p.y);
  await b.c.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: p.x, y: p.y, button: 'left', buttons: 1, clickCount: 2 });
  await b.c.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: p.x, y: p.y, button: 'left', buttons: 0, clickCount: 2 });
  await sleep(900);
  R.tabs = await b.eval(`return [...document.querySelectorAll('.insp [role=tab], .insp .tab, .insp button')].map(e => e.innerText.trim()).filter(Boolean).slice(0, 30);`);
  R.clicked_safeguards = await clickText(b, 'Safeguards', '.insp button, .insp a, .insp [role=tab], .insp *'); await sleep(600);
  await b.shot('E2_safeguards');
  R.safeguards = await b.eval(`const w = document.querySelector('.insp'); return w ? w.innerText.slice(0, 1500) : null;`);
  R.clicked_json = await clickText(b, 'JSON', '.insp button, .insp a, .insp [role=tab], .insp *'); await sleep(600);
  await b.shot('E2_json');
  R.json = await b.eval(`const w = document.querySelector('.insp'); return w ? w.innerText.slice(0, 1200) : null;`);
  return R;
}
