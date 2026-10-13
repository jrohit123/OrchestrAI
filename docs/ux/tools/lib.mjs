// Helpers for the UX audit run (local fake data only).
import fs from 'node:fs';

export const BASE = 'http://127.0.0.1:8780';
export const PASSWORD = process.env.UX_PASSWORD || '';
export const sleep = ms => new Promise(r => setTimeout(r, ms));

export async function signIn(b, email) {
  await b.goto(BASE + '/admin', 900);
  const r = await b.eval(`const res = await fetch('/admin/_auth/sign-in', {method:'POST', headers:{'X-Panel':'1','Content-Type':'application/json'}, body: JSON.stringify({email: ${JSON.stringify(email)}, password: ${JSON.stringify(PASSWORD)}})}); return res.status;`);
  return r;
}

export async function api(b, path) {
  return b.eval(`const r = await fetch(${JSON.stringify(path)}, {headers:{'X-Panel':'1'}}); return await r.json();`);
}

// click the first visible control whose text (or aria-label) equals `text`
export async function clickText(b, text, sel = 'button, a, [role=button], [role=tab], summary, label') {
  const p = await b.eval(`
    const want = ${JSON.stringify(text.toLowerCase())};
    const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; };
    const els = [...document.querySelectorAll(${JSON.stringify(sel)})].filter(e => vis(e) && ((e.innerText || '').trim().toLowerCase() === want || (e.getAttribute('aria-label') || '').trim().toLowerCase() === want || (e.title || '').trim().toLowerCase() === want));
    const e = els[0]; if (!e) return null;
    e.scrollIntoView({block: 'center'});
    const r = e.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2};`);
  if (!p) return false;
  await b.clickAt(p.x, p.y);
  return true;
}

// one measuring function, run inside the page: sizes, names, contrast, overflow
export const MEASURE = `
(() => {
  const out = {};
  const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0'; };
  const sel = (e) => { let s = e.tagName.toLowerCase(); if (e.id) s += '#' + e.id; const c = (e.getAttribute('class') || '').trim().split(/\\s+/).filter(Boolean).slice(0, 3).join('.'); if (c) s += '.' + c; return s; };
  const nameOf = e => (e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') && document.getElementById(e.getAttribute('aria-labelledby'))?.innerText || e.innerText || e.value || e.getAttribute('title') || e.getAttribute('placeholder') || '').trim().replace(/\\s+/g, ' ').slice(0, 60);
  out.dom_nodes = document.getElementsByTagName('*').length;
  out.title = document.title;
  out.lang = document.documentElement.lang;
  out.h1 = [...document.querySelectorAll('h1')].filter(vis).map(h => h.innerText.trim());
  out.headings = [...document.querySelectorAll('h1,h2,h3,h4')].filter(vis).map(h => h.tagName + ':' + h.innerText.trim().slice(0, 40));
  out.landmarks = [...document.querySelectorAll('main,nav,aside,header,footer,[role=main],[role=navigation],[role=banner],[role=dialog]')].filter(vis).map(e => e.tagName.toLowerCase() + (e.getAttribute('aria-label') ? '[' + e.getAttribute('aria-label') + ']' : ''));
  const q = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=tab],[role=switch],[role=menuitem],[tabindex]:not([tabindex="-1"])';
  const items = [...document.querySelectorAll(q)].filter(e => vis(e) && !e.disabled);
  out.interactive = items.length;
  const small24 = [], small44 = [], noName = [];
  for (const e of items) {
    const r = e.getBoundingClientRect();
    const w = Math.round(r.width), h = Math.round(r.height);
    const info = sel(e) + ' ' + w + 'x' + h + ' "' + nameOf(e).slice(0, 28) + '"';
    if (w < 24 || h < 24) small24.push(info);
    if (w < 44 || h < 44) small44.push(info);
    if (!nameOf(e)) noName.push(sel(e) + ' ' + w + 'x' + h);
  }
  out.targets_under_24 = small24.length; out.targets_under_44 = small44.length;
  out.targets_under_24_examples = [...new Set(small24)].slice(0, 6);
  out.targets_under_44_examples = [...new Set(small44)].slice(0, 6);
  out.controls_without_name = noName.length; out.controls_without_name_examples = [...new Set(noName)].slice(0, 6);
  out.inputs_without_label = [...document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]),select,textarea')].filter(vis).filter(e => !(e.id && document.querySelector('label[for="' + e.id + '"]')) && !e.closest('label') && !e.getAttribute('aria-label') && !e.getAttribute('aria-labelledby')).map(e => sel(e) + ' placeholder="' + (e.placeholder || '') + '"').slice(0, 8);
  out.scroll_x = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
  out.scroll_x_by = out.scroll_x ? document.documentElement.scrollWidth - document.documentElement.clientWidth : 0;
  // smallest text on screen
  let minFont = 99, minEl = '';
  const textEls = [...document.querySelectorAll('body *')].filter(e => vis(e) && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1));
  out.text_elements = textEls.length;
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const parse = s => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const blend = (fg, bg) => [0, 1, 2].map(i => fg[i] * fg[3] + bg[i] * (1 - fg[3]));
  const bgOf = e => { let layers = []; let n = e; while (n && n.nodeType === 1) { const cs = getComputedStyle(n); if (cs.backgroundImage && cs.backgroundImage !== 'none') return null; const c = parse(cs.backgroundColor); if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } n = n.parentElement; } let base = [255, 255, 255]; if (!layers.length || layers[layers.length - 1][3] < 1) { const t = document.documentElement.dataset.theme; const dark = t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; const bc = parse(getComputedStyle(document.body).backgroundColor); base = bc && bc[3] > 0 ? bc.slice(0, 3) : (dark ? [0, 0, 0] : [255, 255, 255]); } for (let i = layers.length - 1; i >= 0; i--) base = blend(layers[i], base); return base; };
  const seen = new Map();
  for (const e of textEls.slice(0, 2500)) {
    const cs = getComputedStyle(e);
    const fs = parseFloat(cs.fontSize);
    if (fs < minFont) { minFont = fs; minEl = sel(e) + ' "' + e.innerText.trim().slice(0, 24) + '"'; }
    const fg = parse(cs.color); const bg = bgOf(e);
    if (!fg || !bg) continue;
    const f = blend(fg, bg);
    const L1 = lum(f), L2 = lum(bg), hi = Math.max(L1, L2), lo = Math.min(L1, L2);
    const ratio = (hi + 0.05) / (lo + 0.05);
    const large = fs >= 24 || (fs >= 18.66 && parseInt(cs.fontWeight, 10) >= 700);
    const need = large ? 3 : 4.5;
    if (ratio < need) {
      const key = cs.color + '|' + cs.backgroundColor + '|' + fs;
      if (!seen.has(key)) seen.set(key, { ratio: Math.round(ratio * 100) / 100, need, size: fs, where: sel(e), text: e.innerText.trim().replace(/\\s+/g, ' ').slice(0, 30), count: 1 });
      else seen.get(key).count++;
    }
  }
  out.min_font_px = minFont === 99 ? null : minFont; out.min_font_where = minEl;
  out.low_contrast_pairs = seen.size;
  out.low_contrast_elements = [...seen.values()].reduce((a, v) => a + v.count, 0);
  out.low_contrast_worst = [...seen.values()].sort((a, b) => a.ratio - b.ratio).slice(0, 6);
  out.imgs_without_alt = [...document.querySelectorAll('img')].filter(i => vis(i) && !i.hasAttribute('alt')).length;
  out.hover_title_only = [...document.querySelectorAll('[title]')].filter(vis).length;
  return out;
})()
`;

export async function measure(b) {
  return b.eval(`return ${MEASURE.trim()};`);
}

export function saveJson(path, data) { fs.writeFileSync(path, JSON.stringify(data, null, 1)); }
