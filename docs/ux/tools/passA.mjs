// Pass A: every screen at 1280x800 and 360x640 (light), signed in as a super admin, then the admin's smaller dashboard.
import fs from 'node:fs';
import { BASE, api, clickText, measure, saveJson, signIn, sleep } from './lib.mjs';

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
  return Date.now() - t0;
}

async function visit(b, label, url, size, scheme, store, extra = {}) {
  const [w, h] = size;
  await b.view(w, h, scheme);
  const t0 = Date.now();
  await b.goto(url, 50);
  const ms = await settle(b);
  const m = await measure(b);
  const text = await b.eval(`return (document.getElementById('app')?.innerText || document.body.innerText || '').slice(0, 7000);`);
  const key = `${label}_${w}x${h}_${scheme}`;
  await b.shot(key);
  store[key] = { label, url, size: [w, h], scheme, settle_ms: ms, ...m, text, ...extra };
  return m;
}

export default async function (b) {
  const results = {};
  const base = BASE;
  // ---- first load, signed out
  for (const [label, path] of [['signed_out_admin', '/admin'], ['signed_out_org', '/admin/sunrise']]) {
    for (const size of [[1280, 800], [360, 640]]) await visit(b, label, base + path, size, 'light', results);
  }
  // wrong password message
  await b.view(1280, 800, 'light');
  await b.goto(base + '/admin', 800);
  await b.eval(`const i = document.querySelectorAll('input'); return i.length;`);
  // ---- sign in as a super admin
  const status = await signIn(b, 'kavya.rao@ux.test');
  results._signin_status = status;
  const caseId = (await api(b, '/admin/sunrise/api/v2/cases?page_size=3')).rows?.[0]?.id;
  const personId = (await api(b, '/admin/sunrise/api/v2/people?page_size=3')).rows?.[0]?.id;
  const wf = (await api(b, '/admin/sunrise/api/v2/workflows')).rows || [];
  const flowId = wf.find(f => f.intent_key === 'approve_expense')?.id;
  const blockId = wf.find(f => f.kind === 'block')?.id;
  results._ids = { caseId, personId, flowId, blockId };
  const S = `${base}/admin/sunrise`;
  const routes = [
    ['super_orgs', `${base}/admin`],
    ['home', `${S}#/overview`],
    ['cases', `${S}#/cases`],
    ['cases_filtered', `${S}#/cases?status=reported&assigned=none`],
    ['case_drawer', `${S}#/cases?case=${caseId}`],
    ['conversations', `${S}#/conversations`],
    ['people', `${S}#/people`],
    ['person_drawer', `${S}#/people?person=${personId}`],
    ['flows', `${S}#/workflows`],
    ['flow_editor', `${S}#/workflows?w=${flowId}`],
    ['block_editor', `${S}#/workflows?w=${blockId}`],
    ['chatbot_messages', `${S}#/assistant`],
    ['chatbot_ainotes', `${S}#/assistant/instructions`],
    ['rules_who', `${S}#/rules`],
    ['rules_kinds', `${S}#/rules/categories`],
    ['rules_times', `${S}#/rules/times`],
    ['access_roles', `${S}#/access`],
    ['access_seats', `${S}#/access/seats`],
    ['access_special', `${S}#/access/special`],
    ['settings', `${S}#/settings`],
    ['settings_history', `${S}#/settings/history`],
    ['jewellery_home', `${base}/admin/zari#/overview`],
  ];
  for (const size of [[1280, 800], [360, 640]]) {
    for (const [label, url] of routes) {
      try { await visit(b, label, url, size, 'light', results); } catch (e) { results[`${label}_${size.join('x')}_err`] = String(e); }
    }
  }
  fs.writeFileSync(OUT + '/passA_super.json', JSON.stringify(results, null, 1));
  // ---- sign-in log and accounts live on the organisations page: try the tabs
  await b.view(1280, 800, 'light');
  await b.goto(base + '/admin', 900); await settle(b);
  const tabs = await b.eval(`return [...document.querySelectorAll('#app a, #app button')].map(e => (e.innerText||'').trim()).filter(Boolean).slice(0, 40);`);
  results._super_page_links = tabs;
  fs.writeFileSync(OUT + '/passA_super.json', JSON.stringify(results, null, 1));
  return { done: Object.keys(results).length, tabs };
}
