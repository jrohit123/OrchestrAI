JS = r"""
// ───────────────────────── Chat bot: Messages ─────────────────────────
// Every text the chat bot sends by itself. Groups on the left, the messages of one group in the
// middle, and an editor with a phone preview on the right. What is shown comes from the server,
// including the check of what was typed, so the preview is exactly what people will receive.
const MV = { data: null, group: null, key: null };
const encKey = k => encodeURIComponent(k);

// WhatsApp-style *bold* and _italic_, as the person sees them
function chatRich(text) {
  const out = [];
  String(text).split(/(\*[^*\n]+\*|(?<!\w)_[^_\n]+_(?!\w))/g).forEach(p => {
    if (/^\*[^*\n]+\*$/.test(p)) out.push(h('b', null, p.slice(1, -1)));
    else if (/^_[^_\n]+_$/.test(p)) out.push(h('i', null, p.slice(1, -1)));
    else if (p) out.push(p);
  });
  return out;
}
const flat = s => String(s).replace(/\s*\n\s*/g, ' ');
const sourceBadge = m => m.source === 'own' ? badge('Edited', 'brand') : m.source === 'shared' ? badge('Shared') : badge('Built-in');

function messageEditor(m, ready, reload) {
  const ta = h('textarea', { class: 'textarea msgtext', rows: 7, spellcheck: 'true', 'aria-label': 'Text of this message' });
  ta.value = m.text; ta.readOnly = !ready;
  const notes = h('div', { class: 'stack s8' }), bubble = h('div', { class: 'tgb' }, '…');
  const save = h('button', { class: 'btn primary', type: 'button', disabled: true }, 'Save');
  const builtIn = h('button', { class: 'btn', type: 'button', disabled: !ready || m.source !== 'own' }, 'Use built-in wording');
  const hist = h('button', { class: 'btn ghost', type: 'button', 'data-popkeep': true, disabled: !ready }, icon('hist', 'sm'), 'History');
  let seq = 0, verdict = { ok: true, problems: [], warnings: [], preview: null };
  const dirty = () => ta.value.trim() !== m.text.trim();
  const paint = () => {
    fill(bubble, verdict.preview != null ? chatRich(verdict.preview) : '—');
    fill(notes, [...verdict.problems.map(p => notice(p, 'bad')), ...verdict.warnings.map(w => notice(w, 'warn'))]);
    save.disabled = !ready || !dirty() || !verdict.ok;
  };
  const ask = async () => {
    const mine = ++seq;
    try { const v = await api.post('/messages/' + encKey(m.key) + '/check', { text: ta.value }); if (mine === seq) { verdict = v; paint(); } }
    catch (e) { /* saving will say what is wrong */ }
  };
  const later = debounce(ask, 220);
  ta.addEventListener('input', () => { save.disabled = true; later(); });
  const chips = Object.entries(m.values).map(([n, what]) => h('button', { type: 'button', class: 'varchip', title: what, disabled: !ready, onclick: () => {
    ta.setRangeText('{' + n + '}', ta.selectionStart, ta.selectionEnd, 'end'); ta.focus(); ta.dispatchEvent(new Event('input'));
  } }, '{' + n + '}'));
  save.onclick = async () => {
    save.disabled = true;
    try {
      const r = await api.put('/messages/' + encKey(m.key), { text: ta.value });
      toast(!r.changed ? 'Nothing to save' : r.version ? 'Saved as version ' + r.version : 'Back to the built-in wording', 'ok');
      await reload();
    } catch (e) { toast(e.message, 'bad'); paint(); }
  };
  builtIn.onclick = async () => {
    if (!await confirmBox('Go back to the built-in wording of “' + m.name + '”? Your own versions stay in the history.', { ok: 'Use built-in wording' })) return;
    try { await api.del('/messages/' + encKey(m.key)); toast('Back to the built-in wording', 'ok'); await reload(); }
    catch (e) { toast(e.message, 'bad'); }
  };
  hist.onclick = async ev => {
    const anchor = ev.currentTarget;
    try {
      const d = await api.get('/messages/' + encKey(m.key) + '/history');
      const inUse = d.versions.find(v => v.active);
      const rows = d.versions.length ? d.versions.map(v => h('div', { class: 'mi', style: { cursor: 'default' } },
        h('span', null, h('b', null, 'Version ' + v.version), ' ', v === inUse ? badge('in use', 'ok') : !v.active ? badge('off') : null,
          h('small', null, fmtDT(v.created_at) + (v.created_by ? ' · ' + v.created_by : '') + (v.note ? ' · ' + v.note : ''))),
        h('button', { class: 'btn sm', type: 'button', style: { marginLeft: 'auto' }, onclick: () => { closePop(); ta.value = v.text; ta.dispatchEvent(new Event('input')); ta.focus(); } }, 'Use this text')))
        : [h('div', { class: 'muted small', style: { padding: '8px 10px' } }, 'No saved versions yet. This message says what it always said.')];
      openPop(anchor, [h('div', { class: 'ml' }, 'Earlier versions'), ...rows], { width: 360 });
    } catch (e) { toast(e.message, 'bad'); }
  };
  ask();
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, m.name, h('span', { class: 'muted mono small' }, m.key)),
    h('div', { class: 'card-b stack' },
      h('div', { class: 'notice' }, h('div', { class: 'small' }, h('b', null, 'When it is sent: '), m.when)),
      h('div', { class: 'field' }, h('label', null, 'Text'), ta,
        h('div', { class: 'hint' }, Object.keys(m.values).length ? 'Values you can use (click to put one in):' : 'This text has no values to fill in.'),
        h('div', null, chips)),
      notes,
      h('div', { class: 'field' }, h('label', null, 'How it looks to the person'),
        h('div', { class: 'phone' }, h('div', { class: 'pbar' }, h('span', { class: 'logo sm' }, S.boot.org.name[0]), 'Chat bot'), h('div', { class: 'pbody' }, bubble)),
        h('div', { class: 'hint' }, 'Sample values are filled in. *bold* and _italic_ show as they do in the chat.')),
      h('div', { class: 'row' }, save, builtIn, hist,
        h('span', { class: 'muted small' }, m.source === 'own' ? 'Version ' + m.version + (m.updated_by ? ' · by ' + m.updated_by : '') : m.source === 'shared' ? 'A shared wording is in use.' : 'Says what it always said.'))));
}

async function renderMessages(root) {
  const redraw = async () => {
    MV.data = await api.get('/messages');
    fill(root, build());
  };
  const build = () => {
    const d = MV.data;
    const group = d.groups.find(g => g.key === MV.group) || d.groups[0];
    MV.group = group.key;
    const m = group.messages.find(x => x.key === MV.key) || group.messages[0];
    MV.key = m.key;
    const total = d.groups.reduce((n, g) => n + g.messages.length, 0), edited = d.groups.reduce((n, g) => n + g.messages.filter(x => x.source === 'own').length, 0);
    const pick = async (g, key) => {
      const cur = document.querySelector('.msgtext');
      if (cur && cur.value.trim() !== (cur.dataset.saved || '') && !await confirmBox('Leave this message? What you changed is not saved.', { ok: 'Leave without saving' })) return;
      MV.group = g; MV.key = key; fill(root, build());
    };
    return [
      d.ready ? null : notice('This database has not been updated for editable messages yet (migration core-0009). You can read what each message says, but not change it.', 'warn'),
      h('div', { class: 'msgs' },
        h('div', { class: 'card' }, h('div', { class: 'card-b stack s8' },
          d.groups.map(g => h('button', { type: 'button', class: 'mgroup' + (g.key === group.key ? ' on' : ''), onclick: () => pick(g.key, '') }, h('span', null, g.label), h('span', { class: 'c' }, g.messages.length))),
          h('div', { class: 'muted small msgtotal' }, total + ' texts · ' + edited + ' changed by you'))),
        h('div', { class: 'card' }, h('div', { class: 'card-h' }, group.label, h('span', { class: 'muted small' }, group.messages.length + ' texts')),
          h('div', { class: 'muted small msgabout' }, group.about),
          h('div', null, group.messages.map(x => h('button', { type: 'button', class: 'mi2' + (x.key === m.key ? ' on' : ''), onclick: () => pick(group.key, x.key) },
            h('div', { class: 'row between flat' }, h('b', null, x.name), sourceBadge(x)), h('div', { class: 'muted small ell' }, flat(x.text)))))),
        (() => { const card = messageEditor(m, d.ready, redraw); const ta = card.querySelector('.msgtext'); ta.dataset.saved = m.text.trim(); return card; })()),
    ];
  };
  await redraw();
}

// ───────────────────────── Chat bot: AI notes ─────────────────────────
// The notes the chat bot's AI reads before every message, in parts that are put one after the other.
// Only the organisation's own notes are meant to be changed, so they come first and in plain words;
// the shared rules and the industry text wait under Advanced. Edit a part, compare it with an
// earlier version, go back. See everything the AI reads shows the parts put together.
const IV = { data: null, key: null };
const botApp = () => ((S.boot.org && S.boot.org.channel) === 'whatsapp' ? 'WhatsApp' : 'Telegram');

// which lines were added or removed between two texts (plain longest-common-lines)
function lineDiff(a, b) {
  const x = String(a).split('\n'), y = String(b).split('\n'), n = x.length, m = y.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) { out.push({ t: 'same', s: x[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ t: 'del', s: x[i++] });
    else out.push({ t: 'add', s: y[j++] });
  }
  while (i < n) out.push({ t: 'del', s: x[i++] });
  while (j < m) out.push({ t: 'add', s: y[j++] });
  return out;
}
// the changed lines with two lines around each, and "n unchanged lines" where the rest was left out
function diffRows(a, b) {
  const d = lineDiff(a, b), keep = new Array(d.length).fill(false);
  d.forEach((r, i) => { if (r.t !== 'same') for (let k = Math.max(0, i - 2); k <= Math.min(d.length - 1, i + 2); k++) keep[k] = true; });
  const rows = []; let skipped = 0;
  d.forEach((r, i) => {
    if (keep[i]) {
      if (skipped) { rows.push(h('div', { class: 'dl gap' }, skipped + ' unchanged line' + (skipped === 1 ? '' : 's'))); skipped = 0; }
      rows.push(h('div', { class: 'dl ' + (r.t === 'same' ? '' : r.t) }, (r.t === 'add' ? '+ ' : r.t === 'del' ? '− ' : '  ') + r.s));
    } else skipped++;
  });
  if (skipped) rows.push(h('div', { class: 'dl gap' }, skipped + ' unchanged line' + (skipped === 1 ? '' : 's')));
  return { rows, changed: d.some(r => r.t !== 'same') };
}
const instructionBadge = L => L.source === 'own' ? badge('Edited · version ' + L.version, 'brand') : L.source === 'industry' ? badge('Industry text') : L.source === 'shared' ? badge('Shared text') : L.can_be_empty && !String(L.text).trim() ? badge('Nothing written yet') : badge('Built-in');

// own = the organisation's own notes: plain words, a short box, Clear notes instead of Use built-in text
function instructionEditor(L, ready, reload, own) {
  const ta = h('textarea', { class: 'textarea promptbox' + (own ? ' an-short' : ''), spellcheck: own ? 'true' : 'false', 'aria-label': (own ? 'Notes for the AI: ' : 'Text of ') + L.name });
  ta.value = L.text; ta.readOnly = !ready; ta.dataset.saved = L.text.trim();
  if (L.can_be_empty) ta.placeholder = 'Write your notes here, one idea per line.';
  const counts = h('span', { class: 'muted small' }), notes = h('div', { class: 'stack s8 an-notes' });
  const save = h('button', { class: 'btn primary', type: 'button', disabled: true }, 'Save');
  const builtIn = h('button', { class: 'btn', type: 'button', disabled: !ready || L.source !== 'own' }, own ? 'Clear notes' : 'Use built-in text');
  const hist = h('button', { class: 'btn ghost', type: 'button', 'data-popkeep': true, disabled: !ready }, icon('hist', 'sm'), 'History');
  const reads = own ? h('button', { class: 'btn ghost', type: 'button' }, icon('spark', 'sm'), 'See everything the AI reads') : null;
  let seq = 0, verdict = { ok: true, problems: [], warnings: [], characters: L.text.length, lines: L.text.split('\n').length };
  const dirty = () => ta.value.trim() !== L.text.trim();
  const paint = () => {
    counts.textContent = verdict.characters.toLocaleString() + ' characters · ' + verdict.lines.toLocaleString() + ' lines';
    fill(notes, [...verdict.problems.map(p => notice(p, 'bad')), ...verdict.warnings.map(w => notice(w, 'warn'))]);
    save.disabled = !ready || !dirty() || !verdict.ok;
  };
  const ask = async () => {
    const mine = ++seq;
    try { const v = await api.post('/instructions/' + encKey(L.key) + '/check', { text: ta.value }); if (mine === seq) { verdict = v; paint(); } }
    catch (e) { /* saving will say what is wrong */ }
  };
  const later = debounce(ask, 300);
  ta.addEventListener('input', () => { save.disabled = true; later(); });
  save.onclick = async () => {
    save.disabled = true;
    try {
      const r = await api.put('/instructions/' + encKey(L.key), { text: ta.value });
      toast(!r.changed ? 'Nothing to save' : r.version ? 'Saved as version ' + r.version : 'Back to the built-in text', 'ok');
      ta.dataset.saved = ta.value.trim();
      await reload();
    } catch (e) { toast(e.message, 'bad'); paint(); }
  };
  builtIn.onclick = async () => {
    const question = own ? 'Clear these notes? The chat bot goes back to having none. Earlier versions stay in the history.' : 'Go back to the built-in text of “' + L.name + '”? Your own versions stay in the history.';
    if (!await confirmBox(question, { ok: own ? 'Clear notes' : 'Use built-in text' })) return;
    try { await api.del('/instructions/' + encKey(L.key)); toast(own ? 'Notes cleared' : 'Back to the built-in text', 'ok'); ta.dataset.saved = ta.value.trim(); await reload(); }
    catch (e) { toast(e.message, 'bad'); }
  };
  if (reads) reads.onclick = async () => {
    try {
      const d = await api.get('/instructions/assembled');
      modal({ title: 'What the AI reads', wide: true, body: h('div', { class: 'stack' },
        h('div', { class: 'muted small' }, 'All the parts put together, in this order, as saved now (' + d.characters.toLocaleString() + ' characters). On every message the system adds today’s date, the person’s role and what they may do, the flows they can start and the tables it may read.'),
        h('pre', { class: 'promptview' }, d.text || '(nothing)')), actions: [{ label: 'Close' }] });
    } catch (e) { toast(e.message, 'bad'); }
  };
  hist.onclick = async ev => {
    const anchor = ev.currentTarget;
    try {
      const d = await api.get('/instructions/' + encKey(L.key) + '/history');
      const inUse = d.versions.find(v => v.active);
      const rows = d.versions.length ? d.versions.map(v => h('div', { class: 'mi', style: { cursor: 'default' } },
        h('span', null, h('b', null, 'Version ' + v.version), ' ', v === inUse ? badge('in use', 'ok') : !v.active ? badge('off') : null,
          h('small', null, fmtDT(v.created_at) + (v.created_by ? ' · ' + v.created_by : '') + (v.note ? ' · ' + v.note : ''))),
        h('span', { class: 'row flat', style: { marginLeft: 'auto' } },
          h('button', { class: 'btn sm', type: 'button', onclick: () => { closePop(); const x = diffRows(v.text, L.text); modal({ title: 'Version ' + v.version + ' compared with what is in use now', wide: true, body: h('div', { class: 'stack s8' },
            h('div', { class: 'muted small' }, '− only in version ' + v.version + ' · + only in what is in use now'),
            x.changed ? h('div', { class: 'difflist' }, x.rows) : h('div', { class: 'muted' }, 'They are the same.')), actions: [{ label: 'Close' }] }); } }, 'Compare'),
          h('button', { class: 'btn sm', type: 'button', onclick: () => { closePop(); ta.value = v.text; ta.dispatchEvent(new Event('input')); ta.focus(); } }, 'Use this text'))))
        : [h('div', { class: 'muted small', style: { padding: '8px 10px' } }, own ? 'No saved versions yet. You have not written any notes.' : 'No saved versions yet. This is the built-in text.')];
      openPop(anchor, [h('div', { class: 'ml' }, 'Earlier versions'), ...rows], { width: 420 });
    } catch (e) { toast(e.message, 'bad'); }
  };
  paint();
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, L.name, instructionBadge(L)),
    h('div', { class: 'card-b stack' },
      own ? h('div', { class: 'stack s8' },
        h('div', null, h('b', null, 'Tell the chat bot about your place. '), 'Its AI reads these notes before every message, right after the shared rules. Things worth writing:'),
        h('ul', { class: 'an-ideas' }, h('li', null, 'Different names people use for the same thing, like two names for one building.'), h('li', null, 'Rules of your place the chat bot should respect.'), h('li', null, 'How it should sound, formal or friendly.')))
        : h('div', { class: 'muted small' }, L.about),
      h('div', { class: 'field' }, ta, h('div', { class: 'hint' }, counts)),
      notes,
      h('div', { class: 'row' }, save, builtIn, hist, reads,
        h('span', { class: 'muted small' }, L.source === 'own' && L.updated_by ? 'Last saved by ' + L.updated_by : '')),
      own ? notice('The AI only understands and words things. Looking up, saving and calculating are done by code, so these notes never change a number.', 'teal') : null));
}

async function renderInstructions(root) {
  const mainBox = h('div'), advBox = h('div');
  const unsaved = box => { const t = box.querySelector('.promptbox'); return !!t && t.value.trim() !== (t.dataset.saved || ''); };
  const reload = async () => { IV.data = await api.get('/instructions'); if (!unsaved(mainBox)) drawMain(); if (!unsaved(advBox)) drawAdv(); };
  // the organisation's own notes: the one part meant to be changed
  const drawMain = () => {
    const own = IV.data.layers.find(x => x.key === 'agent.client');
    fill(mainBox, own ? instructionEditor(own, IV.data.ready, reload, true) : null);
  };
  // the parts that come built in with the product, tucked away
  const drawAdv = () => {
    const d = IV.data, rest = d.layers.filter(x => x.key !== 'agent.client'), L = rest.find(x => x.key === IV.key) || rest[0];
    if (!L) { fill(advBox, null); return; }
    IV.key = L.key;
    const pick = async key => {
      const cur = advBox.querySelector('.promptbox');
      if (cur && cur.value.trim() !== (cur.dataset.saved || '') && !await confirmBox('Leave this text? What you changed is not saved.', { ok: 'Leave without saving' })) return;
      IV.key = key; drawAdv();
    };
    const stack = [];
    d.layers.forEach((x, i) => {
      if (i) stack.push(h('div', { class: 'lplus' }, '+'));
      const inner = [h('span', { class: 'ln' }, String(i + 1)), h('div', { class: 'grow' }, h('b', null, x.name), h('div', { class: 'muted small' }, x.key === 'agent.client' ? 'Your own notes, written in the box above.' : x.about)), instructionBadge(x)];
      stack.push(x.key === 'agent.client' ? h('div', { class: 'lyr auto l' + (i + 1) }, inner) : h('button', { type: 'button', class: 'lyr l' + (i + 1) + (x.key === L.key ? ' on' : ''), onclick: () => pick(x.key) }, inner));
    });
    stack.push(h('div', { class: 'lplus' }, '+'));
    stack.push(h('div', { class: 'lyr auto l4' }, h('span', { class: 'ln' }, '4'),
      h('div', { class: 'grow' }, h('b', null, 'Today’s facts ', badge('automatic')), h('div', { class: 'muted small' }, 'The date, the person’s role and what they may do, the flows they can start, the tables it may read. Filled in by the system, not written by anyone.'))));
    fill(advBox, h('div', { class: 'aiwrap' },
      h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'The parts, in the order the AI reads them'), h('div', { class: 'card-b lyrs' }, stack)),
      instructionEditor(L, d.ready, reload, false)));
  };
  IV.data = await api.get('/instructions');
  fill(root, [
    IV.data.ready ? null : notice('This database has not been updated for editable AI notes yet (migration core-0009). You can read the built-in text, but not change it.', 'warn'),
    h('div', { class: 'stack' }, mainBox,
      h('details', { class: 'an-adv' }, h('summary', null, 'Advanced: the shared rules and the industry text'),
        h('div', { class: 'muted small an-advnote' }, 'Built in with the product, the same starting point for every client of the same kind. Change them with care.'), advBox)),
  ]);
  drawMain(); drawAdv();
}

SECTIONS.assistant = {
  heading: (sec, r) => ({ title: sec.label, sub: r.tab === 'instructions' ? 'The chat bot’s AI reads these notes before every message. Most days you do not need to change anything here.' : 'The chat bot is what people talk to on ' + botApp() + '. These are the texts it sends by itself, like a welcome or an error. Pick one and change the words.' }),
  async render(root, route) { return route.tab === 'instructions' ? renderInstructions(root) : renderMessages(root); },
};
"""
