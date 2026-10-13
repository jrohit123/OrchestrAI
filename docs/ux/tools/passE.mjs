// Pass E: where does a novice change who approves? (trigger window, the "..." menu, Technical tab)
import fs from 'node:fs';
import { BASE, api, clickText, signIn, sleep } from './lib.mjs';

export const opts = { w: 1280, h: 800, scheme: 'light' };
const OUT = process.env.OUT || '.';
const R = {};
async function settle(b) { await sleep(900); }
async function dbl(b, sel, textRe) {
  const p = await b.eval(`const n = [...document.querySelectorAll(${JSON.stringify(sel)})].find(x => ${textRe}.test(x.innerText)); if (!n) return null; const r = n.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2};`);
  if (!p) return false;
  await b.mouse('mouseMoved', p.x, p.y);
  await b.c.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: p.x, y: p.y, button: 'left', buttons: 1, clickCount: 2 });
  await b.c.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: p.x, y: p.y, button: 'left', buttons: 0, clickCount: 2 });
  await sleep(900);
  return true;
}
export default async function (b) {
  await signIn(b, 'kavya.rao@ux.test');
  const wf = (await api(b, '/admin/sunrise/api/v2/workflows')).rows || [];
  const flowId = wf.find(f => f.intent_key === 'approve_expense')?.id;
  const S = `${BASE}/admin/sunrise`;
  await b.goto(`${S}#/workflows?w=${flowId}`, 50); await b.c.send('Page.reload', {}); await sleep(1800);
  // 1. the trigger window
  R.trigger_opened = await dbl(b, '.nd', '/Starts when/i');
  await b.shot('E_trigger_window');
  R.trigger_window = await b.eval(`const w = document.querySelector('.sw'); return w ? w.innerText.slice(0, 2500) : document.querySelector('.insp')?.innerText.slice(0, 2500) || null;`);
  // 2. the "..." menu in the bottom bar
  await b.key('Escape');
  const p = await b.eval(`const bs = [...document.querySelectorAll('.cvbar button, button')].filter(e => (e.innerText || '').trim() === '' && e.getBoundingClientRect().top > 700 && e.getBoundingClientRect().left > 400 && e.getBoundingClientRect().left < 800); const e = bs[bs.length - 1]; if (!e) return null; const r = e.getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2};`);
  if (p) { await b.clickAt(p.x, p.y); await sleep(600); }
  await b.shot('E_more_menu');
  R.more_menu = await b.eval(`const m = [...document.querySelectorAll('.pop, .popover, .menu, .ctx')].filter(e => e.getBoundingClientRect().width > 0).pop(); return m ? m.innerText.slice(0, 800) : null;`);
  await b.key('Escape');
  // 3. the approval step: Only if / Technical
  await dbl(b, '.nd', '/Ask for approval/i');
  await clickText(b, 'Technical', '.sw button, .sw a, .sw [role=tab]'); await sleep(500);
  await b.shot('E_approval_technical');
  R.approval_technical = await b.eval(`const w = document.querySelector('.sw'); return w ? w.innerText.slice(0, 1500) : null;`);
  await clickText(b, 'Only if', '.sw button, .sw a, .sw [role=tab]'); await sleep(500);
  await b.shot('E_approval_onlyif');
  R.approval_onlyif = await b.eval(`const w = document.querySelector('.sw'); return w ? w.innerText.slice(0, 1200) : null;`);
  // 4. keyboard: focus the first step by Tab and press Enter
  await b.key('Escape');
  fs.writeFileSync(OUT + '/passE.json', JSON.stringify(R, null, 1));
  return Object.keys(R);
}
