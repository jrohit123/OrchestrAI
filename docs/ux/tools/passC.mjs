// Pass C: other screen sizes, dark mode, zoom 200% and 400%, keyboard tab order, axe-core, load timing, offline.
import fs from 'node:fs';
import { BASE, api, measure, signIn, sleep } from './lib.mjs';

export const opts = { w: 1280, h: 800, scheme: 'light' };
const OUT = process.env.OUT || '.';
const AXE = fs.readFileSync(process.env.AXE_JS, 'utf8');

async function settle(b, max = 7000) {
  const t0 = Date.now();
  while (Date.now() - t0 < max) {
    const loading = await b.eval(`return [...document.querySelectorAll('#main .empty, #app .boot')].some(e => /Loading/.test(e.innerText) && e.getBoundingClientRect().height > 0);`);
    if (!loading) break;
    await sleep(120);
  }
  await sleep(350);
}

async function setView(b, w, h, scheme, dpr = 1) {
  await b.c.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: dpr, mobile: false });
  await b.c.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme }] });
}

async function tabKey(b, shift = false) {
  const p = { key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9, modifiers: shift ? 8 : 0 };
  await b.c.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...p });
  await b.c.send('Input.dispatchKeyEvent', { type: 'keyUp', ...p });
  await sleep(40);
}

const ACTIVE = `
  const e = document.activeElement; if (!e || e === document.body) return null;
  const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
  const name = (e.getAttribute('aria-label') || e.innerText || e.value || e.title || e.placeholder || '').trim().replace(/\\s+/g,' ').slice(0, 40);
  const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
  const shadow = cs.boxShadow !== 'none';
  return { tag: e.tagName.toLowerCase() + (e.getAttribute('role') ? '[' + e.getAttribute('role') + ']' : ''), name, x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height), outline, shadow, inView: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth, inMain: !!e.closest('#main, main') , inNav: !!e.closest('nav, aside') };
`;

async function tabOrder(b, stops) {
  await b.eval(`document.activeElement && document.activeElement.blur(); window.scrollTo(0,0); document.body.focus && document.body.focus(); return 1;`);
  const seq = [];
  for (let i = 0; i < stops; i++) {
    await tabKey(b);
    const a = await b.eval(ACTIVE);
    seq.push(a);
  }
  return seq;
}

export default async function (b) {
  const res = { views: {}, axe: {}, tab: {}, load: {}, offline: {} };
  await signIn(b, 'kavya.rao@ux.test');
  const caseId = (await api(b, '/admin/sunrise/api/v2/cases?page_size=3')).rows?.[0]?.id;
  const wf = (await api(b, '/admin/sunrise/api/v2/workflows')).rows || [];
  const flowId = wf.find(f => f.intent_key === 'approve_expense')?.id;
  const S = `${BASE}/admin/sunrise`;
  const routes = [
    ['home', `${S}#/overview`], ['cases', `${S}#/cases`], ['case_drawer', `${S}#/cases?case=${caseId}`], ['people', `${S}#/people`],
    ['flows', `${S}#/workflows`], ['flow_editor', `${S}#/workflows?w=${flowId}`], ['rules_times', `${S}#/rules/times`], ['access_seats', `${S}#/access/seats`],
    ['settings', `${S}#/settings`], ['chatbot_messages', `${S}#/assistant`], ['conversations', `${S}#/conversations`], ['super_orgs', `${BASE}/admin`],
  ];
  const sizes = [
    ['768x1024_light', 768, 1024, 'light', 1], ['1920x1080_light', 1920, 1080, 'light', 1], ['1280x800_dark', 1280, 800, 'dark', 1],
    ['360x640_dark', 360, 640, 'dark', 1], ['zoom200_640x400', 640, 400, 'light', 2], ['zoom400_320x256', 320, 256, 'light', 4],
  ];
  for (const [tag, w, h, scheme, dpr] of sizes) {
    await setView(b, w, h, scheme, dpr);
    for (const [label, url] of routes) {
      try {
        await b.goto(url, 50); await settle(b);
        const m = await measure(b);
        await b.shot(`${label}_${tag}`);
        res.views[`${label}_${tag}`] = m;
      } catch (e) { res.views[`${label}_${tag}`] = { error: String(e) }; }
    }
  }
  fs.writeFileSync(OUT + '/passC.json', JSON.stringify(res, null, 1));

  // ---- axe-core at 1280 (and four screens at 360)
  for (const [tag, w, h] of [['1280', 1280, 800], ['360', 360, 640]]) {
    await setView(b, w, h, 'light', 1);
    for (const [label, url] of routes) {
      if (tag === '360' && !['home', 'cases', 'flows', 'people'].includes(label)) continue;
      try {
        await b.goto(url, 50); await settle(b);
        await b.eval(AXE + ';return 1;');
        const out = await b.eval(`
          const r = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] } });
          return { violations: r.violations.map(v => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length, tags: v.tags.filter(t => /^wcag\\d/.test(t)).slice(0, 2), examples: v.nodes.slice(0, 3).map(n => n.target.join(' ').slice(0, 90)) })), passes: r.passes.length, incomplete: r.incomplete.length };`);
        res.axe[`${label}_${tag}`] = out;
      } catch (e) { res.axe[`${label}_${tag}`] = { error: String(e) }; }
    }
  }
  fs.writeFileSync(OUT + '/passC.json', JSON.stringify(res, null, 1));

  // ---- keyboard: tab order on four screens at 1280
  await setView(b, 1280, 800, 'light', 1);
  for (const [label, url] of routes.filter(r => ['home', 'cases', 'flows', 'people', 'flow_editor'].includes(r[0]))) {
    await b.goto(url, 50); await settle(b);
    const total = await b.eval(`return [...document.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,summary,[tabindex]:not([tabindex="-1"])')].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !e.disabled; }).length;`);
    const seq = await tabOrder(b, 45);
    const firstMain = seq.findIndex(s => s && s.inMain);
    res.tab[label] = { focusable_controls: total, first_stop_in_main: firstMain + 1, stops_in_nav_before_main: seq.slice(0, Math.max(firstMain, 0)).filter(s => s && s.inNav).length, no_visible_focus: seq.filter(s => s && !s.outline && !s.shadow).length, off_screen: seq.filter(s => s && !s.inView).length, first_12: seq.slice(0, 12).map(s => s ? `${s.tag} "${s.name}" ${s.w}x${s.h}${s.outline || s.shadow ? '' : ' NOFOCUS'}` : null) };
  }
  fs.writeFileSync(OUT + '/passC.json', JSON.stringify(res, null, 1));

  // ---- load timing: a real reload of the home screen, plain and on a slow network
  await setView(b, 1280, 800, 'light', 1);
  for (const [tag, net] of [['normal', null], ['slow3g', { offline: false, latency: 400, downloadThroughput: 50 * 1024, uploadThroughput: 50 * 1024 }]]) {
    if (net) { await b.c.send('Network.enable'); await b.c.send('Network.emulateNetworkConditions', net); }
    await b.c.send('Network.setCacheDisabled', { cacheDisabled: true });
    const t0 = Date.now();
    await b.goto(`${S}#/overview`, 50);
    await b.c.send('Page.reload', {});
    let ready = null;
    for (let i = 0; i < 160 && ready === null; i++) {
      await sleep(250);
      ready = await b.eval(`const h = document.querySelector('#main .screen h1'); const l = [...document.querySelectorAll('#main .empty')].some(e => /Loading/.test(e.innerText)); return h && !l ? Math.round(performance.now()) : null;`);
    }
    const m = await b.eval(`
      const nav = performance.getEntriesByType('navigation')[0];
      const paint = Object.fromEntries(performance.getEntriesByType('paint').map(p => [p.name, Math.round(p.startTime)]));
      const res = performance.getEntriesByType('resource').map(r => ({ f: r.name.split('/').pop().split('?')[0], kb: Math.round((r.encodedBodySize || r.transferSize) / 1024), ms: Math.round(r.duration) })).sort((a, b) => b.kb - a.kb).slice(0, 6);
      let cls = 0; await new Promise(done => { new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) cls += e.value; }).observe({ type: 'layout-shift', buffered: true }); setTimeout(done, 250); });
      return { dcl: Math.round(nav.domContentLoadedEventEnd), load: Math.round(nav.loadEventEnd), paint, cls: Math.round(cls * 1000) / 1000, heapMb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null, res };`);
    res.load[tag] = { content_ready_ms: ready, ...m, wall_ms: Date.now() - t0 };
    if (net) await b.c.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  }
  await b.c.send('Network.setCacheDisabled', { cacheDisabled: false });
  fs.writeFileSync(OUT + '/passC.json', JSON.stringify(res, null, 1));

  // ---- offline: the app is open, the network drops, then someone moves to another screen
  await b.goto(`${S}#/overview`, 50); await settle(b);
  await b.c.send('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
  await b.goto(`${S}#/cases`, 50); await sleep(2500);
  res.offline.cases_text = await b.eval(`return (document.getElementById('main')?.innerText || '').slice(0, 400);`);
  await b.shot('offline_cases_1280x800');
  await b.c.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  fs.writeFileSync(OUT + '/passC.json', JSON.stringify(res, null, 1));
  return { views: Object.keys(res.views).length, axe: Object.keys(res.axe).length, tab: Object.keys(res.tab) };
}
