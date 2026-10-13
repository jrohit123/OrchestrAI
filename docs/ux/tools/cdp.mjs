// A tiny browser driver for checking the dashboard: opens it in headless Edge, clicks, drags, takes screenshots.
// Usage: node cdp.mjs scenario.mjs      (the scenario exports: export default async (b) => { ... })
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const SHOTS = process.env.SHOTS || path.join(path.dirname(new URL(import.meta.url).pathname.slice(1)), 'shots');
const PORT = 9333 + Math.floor(Math.random() * 500);
const sleep = ms => new Promise(r => setTimeout(r, ms));
fs.mkdirSync(SHOTS, { recursive: true });

class CDP {
  constructor(url) { this.ws = new WebSocket(url); this.id = 0; this.cb = new Map(); this.logs = []; this.ws.onmessage = e => this.on(JSON.parse(e.data)); }
  open() { return new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = rej; }); }
  on(m) {
    if (m.id) { const f = this.cb.get(m.id); if (f) { this.cb.delete(m.id); f(m); } return; }
    if (m.method === 'Page.javascriptDialogOpening') { this.send('Page.handleJavaScriptDialog', { accept: true }); return; }
    if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(m.params.type)) this.logs.push(m.params.type + ': ' + m.params.args.map(a => a.value ?? a.description ?? '').join(' '));
    if (m.method === 'Runtime.exceptionThrown') this.logs.push('exception: ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') this.logs.push('log: ' + m.params.entry.text + ' ' + (m.params.entry.url || ''));
  }
  send(method, params = {}) { const id = ++this.id; this.ws.send(JSON.stringify({ id, method, params })); return new Promise(res => this.cb.set(id, m => res(m.error ? { error: m.error } : m.result))); }
}

export async function run(scenario, opts = {}) {
  const w = opts.w || 1440, h = opts.h || 900, scheme = opts.scheme || 'light';
  const profile = path.join(SHOTS, 'cdp-profile-' + Date.now());
  const proc = spawn(EDGE, ['--headless=new', '--disable-gpu', '--hide-scrollbars', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, `--window-size=${w},${h}`, 'about:blank'], { stdio: 'ignore', windowsHide: true });
  let target = null;
  for (let i = 0; i < 60 && !target; i++) {
    try { const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); target = list.find(t => t.type === 'page'); } catch (e) { /* not up yet */ }
    if (!target) await sleep(250);
  }
  if (!target) { proc.kill(); throw new Error('browser did not start'); }
  const c = new CDP(target.webSocketDebuggerUrl); await c.open();
  await c.send('Page.enable'); await c.send('Runtime.enable'); await c.send('Log.enable');
  const b = {
    c, w, h,
    async view(width, height, sch) {
      await c.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      await c.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: sch || scheme }] });
    },
    async goto(url, wait = 1800) { await c.send('Page.navigate', { url }); await sleep(wait); },
    async eval(expr) {
      const r = await c.send('Runtime.evaluate', { expression: `(async () => { ${expr} })()`, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) return { error: r.exceptionDetails.exception?.description || r.exceptionDetails.text };
      return r.result?.value;
    },
    async center(sel) { return b.eval(`const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; e.scrollIntoView({block:'nearest'}); const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height };`); },
    async mouse(type, x, y, extra = {}) { await c.send('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons: type === 'mouseReleased' ? 0 : 1, clickCount: 1, ...extra }); },
    async click(sel, off = {}) { const p = await b.center(sel); if (!p) throw new Error('no element ' + sel); const x = p.x + (off.dx || 0), y = p.y + (off.dy || 0); await b.mouse('mouseMoved', x, y); await b.mouse('mousePressed', x, y); await b.mouse('mouseReleased', x, y); await sleep(250); return p; },
    async clickAt(x, y) { await b.mouse('mouseMoved', x, y); await b.mouse('mousePressed', x, y); await b.mouse('mouseReleased', x, y); await sleep(250); },
    async drag(x1, y1, x2, y2, steps = 12) { await b.mouse('mouseMoved', x1, y1); await b.mouse('mousePressed', x1, y1); for (let i = 1; i <= steps; i++) await b.mouse('mouseMoved', x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps); await b.mouse('mouseReleased', x2, y2); await sleep(300); },
    async key(key, mods = 0) { await c.send('Input.dispatchKeyEvent', { type: 'keyDown', key, modifiers: mods }); await c.send('Input.dispatchKeyEvent', { type: 'keyUp', key, modifiers: mods }); await sleep(200); },
    async shot(name) { const r = await c.send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(path.join(SHOTS, name + '.png'), Buffer.from(r.data, 'base64')); return name; },
    wait: sleep,
  };
  if (process.env.TRACE) for (const k of Object.keys(b)) if (typeof b[k] === 'function' && !['wait', 'center', 'mouse'].includes(k)) { const f = b[k]; b[k] = async (...a) => { console.error('>', k, String(a[0]).slice(0, 80)); const t0 = Date.now(); const r = await f(...a); console.error('<', k, Date.now() - t0, 'ms'); return r; }; }
  await b.view(w, h, scheme);
  let out;
  try { out = await scenario(b); } finally { try { await c.send('Browser.close'); } catch (e) { /* closing */ } try { proc.kill(); } catch (e) { /* gone */ } }
  return { out, logs: c.logs };
}

if (process.argv[2]) {
  const mod = await import(pathToFileURL(path.resolve(process.argv[2])).href);
  const r = await run(mod.default, mod.opts || {});
  if (r.out !== undefined) console.log(JSON.stringify(r.out, null, 1));
  if (r.logs.length) console.log('CONSOLE:', [...new Set(r.logs)].join('\n'));
  process.exit(0);
}
