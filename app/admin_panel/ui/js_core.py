JS = r"""
// ───────────────────────── core helpers ─────────────────────────
const ORG = document.body.dataset.org;
const BASE = '/admin/' + encodeURIComponent(ORG) + '/api/v2';
const CLASSIC = '/admin/' + encodeURIComponent(ORG) + '/api';
const S = { boot: null, lookups: null };
const SECTIONS = {};

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  const late = {};
  if (props) for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'value' || k === 'checked' || k === 'selected' || k === 'indeterminate') late[k] = v;
    else if (k === 'disabled' || k === 'hidden') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  add(el, kids);
  for (const [k, v] of Object.entries(late)) el[k] = v;   // after children, so <select> finds its options
  return el;
}
function add(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}
function svgEl(tag, attrs, ...kids) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  for (const k of kids.flat()) if (k) el.append(k);
  return el;
}
function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
function fill(el, ...kids) { clear(el); return add(el, kids); }   // like replaceChildren, but accepts null and lists
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

// ───────────────────────── formatting ─────────────────────────
const dtf = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' });
const df = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
const asDate = v => (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) ? new Date(v + 'T00:00:00') : new Date(v);
const fmtDT = v => v ? dtf.format(asDate(v)) : '—';
const fmtD = v => v ? df.format(asDate(v)) : '—';
const pretty = s => s == null || s === '' ? '' : String(s).replace(/[_.]+/g, ' ').replace(/^./, c => c.toUpperCase());
const plural = (n, one, many) => n + ' ' + (n === 1 ? one : (many || one + 's'));
function span(ms) {
  const m = Math.round(Math.abs(ms) / 60000);
  if (m < 1) return 'moments';
  if (m < 60) return m + ' min';
  const hrs = m / 60;
  if (hrs < 24) return (hrs < 10 ? Math.round(hrs * 10) / 10 : Math.round(hrs)) + ' h';
  const d = hrs / 24;
  return (d < 10 ? Math.round(d * 10) / 10 : Math.round(d)) + ' d';
}
const ago = v => v ? span(Date.now() - asDate(v).getTime()) + ' ago' : '—';
function relDue(v) {
  if (!v) return '—';
  const diff = asDate(v).getTime() - Date.now();
  return diff >= 0 ? 'in ' + span(diff) : span(diff) + ' late';
}
function minutes(m) {
  if (m == null) return '—';
  if (m < 60) return m + ' min';
  if (m < 1440) return (m % 60 ? (m / 60).toFixed(1) : m / 60) + ' h';
  return (m % 1440 ? (m / 1440).toFixed(1) : m / 1440) + ' d';
}
const money = n => '₹' + new Intl.NumberFormat('en-IN').format(Number(n || 0));
const num = n => new Intl.NumberFormat('en-IN').format(Number(n || 0));

// ───────────────────────── talking to the server ─────────────────────────
class ApiError extends Error { constructor(msg, status, data) { super(msg); this.status = status; this.data = data || null; } }
function errorText(data, res) {
  const d = data && data.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map(x => (x.loc ? x.loc.slice(1).join('.') + ': ' : '') + x.msg).join('; ');
  if (d && typeof d === 'object') return d.error ? d.error + (d.problems ? ' ' + d.problems.join('; ') : '') : JSON.stringify(d);
  return 'Something went wrong (' + res.status + ').';
}
const getName = () => { try { return localStorage.getItem('panel.name') || ''; } catch (e) { return ''; } };
const setName = v => { try { localStorage.setItem('panel.name', v); } catch (e) { /* private mode */ } };
async function request(url, opts) {
  opts = opts || {};
  const headers = { Accept: 'application/json' };
  const who = getName();
  if (who) headers['X-Admin-Name'] = encodeURIComponent(who);
  let body = opts.body;
  if (body !== undefined && !(body instanceof FormData)) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(body); }
  let res;
  try { res = await fetch(url, { method: opts.method || 'GET', headers, body }); }
  catch (e) { throw new ApiError('Cannot reach the server. Check your connection and try again.', 0); }
  let data = null;
  if ((res.headers.get('content-type') || '').includes('json')) data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorText(data, res), res.status, data);
  return data;
}
function qs(q) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q || {})) if (v !== undefined && v !== null && v !== '' && v !== false) p.set(k, v === true ? 'true' : v);
  const s = p.toString();
  return s ? '?' + s : '';
}
const api = {
  get: (p, q) => request(BASE + p + qs(q)),
  post: (p, b) => request(BASE + p, { method: 'POST', body: b === undefined ? {} : b }),
  put: (p, b) => request(BASE + p, { method: 'PUT', body: b }),
  patch: (p, b) => request(BASE + p, { method: 'PATCH', body: b }),
  del: p => request(BASE + p, { method: 'DELETE' }),
};
const classic = {
  get: (p, q) => request(CLASSIC + p + qs(q)),
  post: (p, b) => request(CLASSIC + p, { method: 'POST', body: b === undefined ? {} : b }),
};
const getLookups = (force) => (!S.lookups || force) ? (S.lookups = api.get('/lookups')) : S.lookups;

// ───────────────────────── small UI pieces ─────────────────────────
function badge(text, tone) { return h('span', { class: 'badge' + (tone ? ' ' + tone : '') }, text); }
function statusTone(s) {
  const e = S.boot.enums, closed = e.closed || [];
  if (closed.includes(s)) return 'ok';
  const open = (e.statuses || []).filter(x => !closed.includes(x));
  return ['warn', 'info', 'violet'][open.indexOf(s)] || (open.indexOf(s) > 2 ? 'violet' : '');
}
const prioTone = p => ['bad', 'warn', 'info'][(S.boot.enums.priorities || []).indexOf(p)] || '';
const statusBadge = s => s ? badge(pretty(s), statusTone(s)) : '—';
const prioBadge = p => p ? badge(pretty(p), prioTone(p)) : '—';
function avatar(name) {
  let hue = 0;
  for (const c of String(name || '?')) hue = (hue * 31 + c.charCodeAt(0)) % 360;
  const initials = String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
  return h('span', { class: 'avatar', style: { background: 'hsl(' + hue + ',45%,42%)' } }, initials || '?');
}
function person(id, name, opts) {
  if (!name) return h('span', { class: 'muted' }, (opts && opts.none) || '—');
  const inner = [avatar(name), h('span', { class: 'nm' }, name)];
  return id ? h('a', { class: 'person', href: href('people', 'people', { person: id }), onclick: e => e.stopPropagation() }, inner)
            : h('span', { class: 'person' }, inner);
}
function empty(title, text) { return h('div', { class: 'empty' }, h('b', null, title), text || ''); }
function notice(text, tone) { return h('div', { class: 'notice' + (tone ? ' ' + tone : '') }, text); }
function field(label, control, hint) { return h('div', { class: 'field' }, h('label', null, label), control, hint ? h('div', { class: 'hint' }, hint) : null); }
function sel(options, value, props) {
  const el = h('select', props, options.map(o => Array.isArray(o) ? h('option', { value: o[0] }, o[1]) : h('option', { value: o.value }, o.label)));
  el.value = value === undefined || value === null ? '' : String(value);
  return el;
}
function switchEl(checked, onChange, disabled) {
  const input = h('input', { type: 'checkbox', checked: !!checked, disabled: !!disabled });
  input.addEventListener('change', async () => {
    input.disabled = true;
    try { await onChange(input.checked); }
    catch (e) { input.checked = !input.checked; toast(e.message, 'bad'); }
    finally { input.disabled = !!disabled; }
  });
  return h('label', { class: 'switch' }, input, h('span'));
}
function bars(items, onClick) {
  const max = Math.max(1, ...items.map(i => i.n));
  return h('div', null, items.length ? items.map(i => h('div', { class: 'bar', style: onClick ? { cursor: 'pointer' } : null, onclick: onClick ? () => onClick(i) : null },
    h('span', { class: 'lbl', title: i.label }, i.label), h('span', { class: 'track' }, h('span', { class: 'fill', style: { width: (i.n / max * 100) + '%' } })), h('span', { class: 'v' }, i.n))) : h('div', { class: 'muted' }, 'Nothing to show yet.'));
}
function table(cols, data, opts) {
  opts = opts || {};
  if (!data.length) return empty(opts.emptyTitle || 'Nothing here yet', opts.emptyText || '');
  const t = h('table', { class: 't ' + (opts.cls || '') },
    h('thead', null, h('tr', null, cols.map(c => h('th', { class: c.cls || '' }, c.label)))),
    h('tbody', null, data.map(row => h('tr', { class: opts.onRow ? 'click' : '', onclick: opts.onRow ? () => opts.onRow(row) : null },
      cols.map(c => h('td', { class: c.cls || '' }, c.render(row)))))));
  return h('div', { class: 'tablewrap' }, t);
}
function pager(total, page, size, onPage) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (pages <= 1) return h('div', { class: 'row', style: { padding: '10px 14px' } }, h('span', { class: 'muted small' }, plural(total, 'result')));
  return h('div', { class: 'row between', style: { padding: '10px 14px' } },
    h('span', { class: 'muted small' }, ((page - 1) * size + 1) + '–' + Math.min(total, page * size) + ' of ' + total),
    h('span', { class: 'row' },
      h('button', { class: 'btn sm', disabled: page <= 1, onclick: () => onPage(page - 1) }, '← Newer'),
      h('span', { class: 'muted small' }, 'Page ' + page + ' of ' + pages),
      h('button', { class: 'btn sm', disabled: page >= pages, onclick: () => onPage(page + 1) }, 'Older →')));
}
const copyBtn = text => h('button', { class: 'btn sm ghost', onclick: () => navigator.clipboard && navigator.clipboard.writeText(text).then(() => toast('Copied', 'ok')) }, 'Copy');

// ───────────────────────── toasts, modals, drawer ─────────────────────────
function toast(msg, tone) {
  let box = document.querySelector('.toasts');
  if (!box) { box = h('div', { class: 'toasts' }); document.body.append(box); }
  const t = h('div', { class: 'toast' + (tone ? ' ' + tone : '') }, msg);
  box.append(t);
  setTimeout(() => t.remove(), tone === 'bad' ? 7000 : 3500);
}
const modalStack = [];
function modal(o) {
  const scrim = h('div', { class: 'scrim top' });
  const err = h('span', { class: 'err' });
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true; scrim.remove(); box.remove();
    const i = modalStack.indexOf(close); if (i >= 0) modalStack.splice(i, 1);
    if (o.onClose) o.onClose();
  };
  const buttons = (o.actions || []).map(a => {
    const b = h('button', { class: 'btn' + (a.primary ? ' primary' : '') + (a.danger ? ' danger' + (a.primary ? ' solid' : '') : '') }, a.label);
    b.addEventListener('click', async () => {
      err.textContent = '';
      if (!a.run) { close(); return; }
      b.disabled = true;
      try { const r = await a.run(); if (r !== false) close(); }
      catch (e) { err.textContent = e.message || String(e); }
      finally { b.disabled = false; }
    });
    return b;
  });
  const box = h('div', { class: 'modal' + (o.wide ? ' wide' : '') },
    h('div', { class: 'mh' }, o.title, h('span', { class: 'sp' }), h('button', { class: 'x', onclick: close }, '×')),
    h('div', { class: 'mb' }, o.body),
    o.actions ? h('div', { class: 'mf' }, err, buttons) : null);
  scrim.addEventListener('click', close);
  modalStack.push(close);
  document.body.append(scrim, box);
  const first = box.querySelector('input,select,textarea');
  if (first) first.focus();
  return { close, setError: m => { err.textContent = m; } };
}
function confirmBox(message, o) {
  o = o || {};
  return new Promise(resolve => {
    let answer = false;
    modal({
      title: o.title || 'Are you sure?', body: h('p', null, message),
      actions: [
        { label: 'Cancel', run: () => { answer = false; } },
        { label: o.ok || 'Yes, do it', primary: true, danger: !!o.danger, run: () => { answer = true; } },
      ],
      onClose: () => resolve(answer),
    });
  });
}
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (modalStack.length) modalStack[modalStack.length - 1]();
  else if (drawer) leaveDrawer();
});
let drawer = null;
function openDrawer(title, body) {
  closeDrawer(true);
  const scrim = h('div', { class: 'scrim', onclick: () => leaveDrawer() });
  const titleEl = h('h2', null, title);
  const bodyEl = h('div', { class: 'db' }, body);
  const el = h('aside', { class: 'drawer' },
    h('div', { class: 'dh' }, h('div', { class: 'sp' }, titleEl), h('button', { class: 'x', onclick: () => leaveDrawer() }, '×')), bodyEl);
  document.body.append(scrim, el);
  drawer = { scrim, el, titleEl, bodyEl };
  return drawer;
}
function closeDrawer(silent) { if (drawer) { drawer.scrim.remove(); drawer.el.remove(); drawer = null; } if (!silent) drawerKey = ''; }
function leaveDrawer() {          // × / scrim: drop ?case= or ?person= from the address
  const r = parseRoute();
  const q = { ...r.q }; delete q.case; delete q.person;
  location.hash = href(r.section, r.tab, q);
}

// person picker: type to search, pick one
function personPicker(o) {
  o = o || {};
  let current = o.initial || null, results = [], on = -1;
  const input = h('input', { type: 'text', placeholder: o.placeholder || 'Type a name…', autocomplete: 'off' });
  const list = h('div', { class: 'results', hidden: true });
  const chosen = h('div', { class: 'picked', hidden: true });
  const wrap = h('div', { class: 'picker' }, input, list, chosen);
  function paint() {
    input.hidden = !!current; chosen.hidden = !current; clear(chosen);
    if (current) chosen.append(avatar(current.name), h('span', { class: 'sp' }, current.name), h('button', { class: 'x', type: 'button', onclick: () => { current = null; paint(); if (o.onChange) o.onChange(null); } }, '×'));
  }
  function pick(p) { current = { id: p.id, name: p.name }; list.hidden = true; paint(); if (o.onChange) o.onChange(current); }
  async function search() {
    try {
      const d = await api.get('/people', { q: input.value, status: o.anyStatus ? '' : 'active', reachable: o.reachable ? true : '', page_size: 8 });
      results = d.rows; on = -1; clear(list);
      if (!results.length) list.append(h('div', { class: 'opt muted' }, 'No one found'));
      results.forEach(p => list.append(h('div', { class: 'opt', onmousedown: e => { e.preventDefault(); pick(p); } },
        h('span', { class: 'person' }, avatar(p.name), h('span', null, p.name)), h('span', { class: 'muted small' }, p.role || ''))));
      list.hidden = false;
    } catch (e) { toast(e.message, 'bad'); }
  }
  const run = debounce(search, 220);
  input.addEventListener('input', run);
  input.addEventListener('focus', () => { if (!current) search(); });
  input.addEventListener('blur', () => setTimeout(() => { list.hidden = true; }, 150));
  paint();
  return { el: wrap, get value() { return current ? current.id : null; }, get person() { return current; }, set(p) { current = p; paint(); } };
}

// ───────────────────────── routing (the address bar) ─────────────────────────
let drawerKey = '', lastSig = '', lastHash = '#/overview';
function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, '');
  const i = raw.indexOf('?');
  const path = i < 0 ? raw : raw.slice(0, i);
  const q = Object.fromEntries(new URLSearchParams(i < 0 ? '' : raw.slice(i + 1)));
  const [section, tab] = path.split('/').filter(Boolean);
  return { section: section || 'overview', tab: tab || '', q };
}
function href(section, tab, q) {
  const s = new URLSearchParams(Object.entries(q || {}).filter(([, v]) => v !== '' && v != null && v !== false)).toString();
  return '#/' + section + (tab ? '/' + tab : '') + (s ? '?' + s : '');
}
const go = (section, tab, q) => { location.hash = href(section, tab, q); };
const sigOf = r => [r.section, r.tab, JSON.stringify(Object.fromEntries(Object.entries(r.q).filter(([k]) => k !== 'case' && k !== 'person')))].join('|');
function setQuery(q) {            // change the filters in the address without redrawing the page
  const r = parseRoute();
  const keep = {}; if (r.q.case) keep.case = r.q.case; if (r.q.person) keep.person = r.q.person;
  const clean = { ...q }; if (String(clean.page) === '1') delete clean.page;
  history.replaceState(null, '', href(r.section, r.tab, { ...clean, ...keep }));
  lastSig = sigOf(parseRoute());
}
const caseLink = id => href('cases', '', { case: id });
"""
