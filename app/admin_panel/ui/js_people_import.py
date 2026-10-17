JS = r"""
// ───────────────────────── Import people (and their flats) from a file ─────────────────────────
// Step 1 choose the file. Step 2 check: people already here are found (by number, then email) and only what differs is
// listed, each change with a tick (on, unless it needs a look); new people get a role. Nothing is saved until Save.
// Step 3 the result. The server works the plan out again when saving, so the screen is never trusted.
const IMPORT_SAMPLE = 'Name,Phone,Email,Wing,Flat,Relation,Primary member,Lives here,Role\n' +
  'Asha Rao,+919876543210,asha@example.com,A,101,Owner,Yes,Yes,Owner\n' +
  'Ravi Rao,+919876543211,,A,101,Owner\'s family,No,Yes,Owner\n' +
  'Vikram Shah,+919812345678,vikram@example.com,B,204,Tenant,No,Yes,Tenant\n' +
  'Asha Rao,+919876543210,asha@example.com,C,302,Owner,Yes,No,Owner\n';
const IMP_STATUS = { new: ['New', 'brand'], update: ['Filled in or changed', 'info'], check: ['Please check', 'warn'], same: ['Already the same', 'ok'], skip: ['Left out', 'bad'] };
function importPeopleModal(lk) {
  const byNumber = (S.boot.org.channel || 'telegram') !== 'telegram';
  const flats = !!S.boot.caps.flat_people;
  const body = h('div', { class: 'imp' });
  const m = modal({ xwide: true, title: 'Import people from a file', body });
  const savedCode = (() => { try { return localStorage.getItem('panel.countryCode') || '+91'; } catch (e) { return '+91'; } })();
  let plan = null;

  // ---- step 1: the file ----
  function stepUpload(message) {
    m.setTitle('Import people from a file');
    const file = h('input', { type: 'file', accept: '.csv,.txt,text/csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'aria-label': 'Choose a CSV or Excel file' });
    const paste = h('textarea', { rows: 4, placeholder: 'Or paste the rows here, first row with the column names', 'aria-label': 'Paste CSV text' });
    const code = byNumber ? h('input', { type: 'text', value: savedCode, placeholder: '+91', style: { width: '90px' }, 'aria-label': 'Country code for 10-digit numbers' }) : null;
    const goBtn = h('button', { class: 'btn primary', type: 'button' }, 'Read the file');
    const err = h('div', { class: 'badtx small' }, message || '');
    goBtn.addEventListener('click', async () => {
      err.textContent = '';
      let text = paste.value, xlsx = null;
      const f = file.files[0];
      if (f && /\.xlsx$/i.test(f.name)) {   // an Excel file goes up as it is; the server reads its first sheet
        const bytes = new Uint8Array(await f.arrayBuffer());
        let bin = ''; for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        xlsx = btoa(bin);
      } else if (f && /\.xls$/i.test(f.name)) { err.textContent = 'This is an old Excel file (.xls). Save it as .xlsx or as a CSV, then choose it again.'; return; }
      else if (f) text = await f.text();
      if (!xlsx && !text.trim()) { err.textContent = 'Choose a file or paste the rows first.'; return; }
      goBtn.disabled = true; goBtn.textContent = 'Reading…';
      try {
        if (code) { try { localStorage.setItem('panel.countryCode', code.value.trim()); } catch (e) { /* private mode */ } }
        plan = await api.post('/people/import/preview', xlsx ? { file_b64: xlsx, file_name: f.name, country: code ? code.value.trim() : '' } : { csv_text: text, country: code ? code.value.trim() : '' });
        stepReview();
      } catch (e) { err.textContent = e.message; goBtn.disabled = false; goBtn.textContent = 'Read the file'; }
    });
    const sample = h('a', { href: '#', onclick: e => { e.preventDefault(); const a = h('a', { href: URL.createObjectURL(new Blob([IMPORT_SAMPLE], { type: 'text/csv' })), download: 'people-sample.csv' }); document.body.append(a); a.click(); a.remove(); } }, 'Download a sample file');
    fill(body, h('div', { class: 'stack' },
      h('div', { class: 'small' }, h('b', null, 'One row per person' + (flats ? ' per flat' : '') + '. '),
        'Columns: Name, Phone' + (byNumber ? '' : ' (ignored here)') + ', Email' + (flats ? ', Wing, Flat, Relation (Owner, Co-owner, Owner\'s family, Tenant, Tenant\'s family), Primary member (Yes/No), Lives here (Yes/No)' : '') + ', Role. ',
        flats ? 'Someone with two flats gets two rows with the same number. ' : '', 'A CSV or an Excel (.xlsx) file. ', sample, '.'),
      notice('People already here are found by their number (or email) and only filled in: nobody is added twice, an empty cell never removes anything, and people who are not in the file are left as they are. You check every change before it is saved.', 'info'),
      h('div', null, file),
      paste,
      code ? h('div', { class: 'row small' }, h('span', { class: 'muted' }, 'Country code for 10-digit numbers'), code, h('span', { class: 'muted' }, 'Numbers that already start with + are kept as they are.')) : null,
      err,
      h('div', { class: 'row' }, goBtn)));
  }

  // ---- step 2: check ----
  function stepReview() {
    m.setTitle('Check before saving');
    const skip = new Set(), use = new Set(), roles = {}, relations = {};
    let show = '';
    plan.people.forEach(p => { if (p.role_id) roles[p.key] = p.role_id; });
    const roleOptions = [['', 'Choose a role…'], ...plan.roles.map(r => [r.id, roleLabel(r.name)])];
    const isOn = c => c.needs_relation ? !!relations[c.line] : skip.has(c.id) ? false : (c.use || use.has(c.id));
    const setOn = (c, on) => { if (c.use) { on ? skip.delete(c.id) : skip.add(c.id); } else { on ? use.add(c.id) : use.delete(c.id); } };
    const chips = h('div', { class: 'chips' }), list = h('div', { class: 'stack s8' }), saveBtn = h('button', { class: 'btn primary', type: 'button' }), err = h('span', { class: 'badtx small' });
    const counts = plan.counts;
    const picked = () => plan.people.reduce((n, p) => n + (p.status === 'skip' ? 0 : p.changes.filter(isOn).length), 0);
    const needsRole = () => plan.people.filter(p => !p.match && p.status !== 'skip' && p.changes.some(c => c.kind === 'new' && isOn(c)) && !roles[p.key]);
    function drawChips() {
      const chip = (k, label, n) => h('button', { type: 'button', class: 'chip' + (show === k ? ' on' : ''), onclick: () => { show = k; drawChips(); drawList(); } }, label + ' ', h('span', { style: { opacity: .7 } }, n));
      fill(chips, chip('', 'Everyone', plan.people.length + plan.skipped.length),
        Object.entries(IMP_STATUS).filter(([k]) => counts[k]).map(([k, [label]]) => chip(k, label, counts[k])));
    }
    function drawSave() {
      const n = picked(), missing = needsRole().length;
      saveBtn.textContent = n ? 'Save ' + plural(n, 'change') : 'Nothing to save';
      saveBtn.disabled = !n;
      fill(err, missing ? plural(missing, 'new person', 'new people') + ' still need a role.' : '');
    }
    function changeRow(p, c) {
      const cb = h('input', { type: 'checkbox', checked: isOn(c), disabled: p.status === 'skip' || c.needs_relation, 'aria-label': 'Save: ' + c.label });
      cb.addEventListener('change', () => { setOn(c, cb.checked); drawSave(); });
      let what;
      if (c.needs_relation) {
        const rs = sel([['', 'Pick how they are linked…'], ...(c.relations || plan.relations)], relations[c.line] || '', { 'aria-label': 'Relation for ' + c.label });
        rs.addEventListener('change', () => { if (rs.value) relations[c.line] = rs.value; else delete relations[c.line]; cb.checked = !!rs.value; drawSave(); });
        what = h('div', null, rs, c.warn ? h('div', { class: 'warn' }, c.warn) : null);
      } else {
        what = h('div', null, c.old ? [h('span', { class: 'old' }, c.old), ' → '] : null, h('b', null, c.new || ''), c.old === null && c.kind !== 'new' ? h('span', { class: 'muted' }, c.kind === 'flat' ? ' (new flat)' : ' (was empty)') : null,
          c.warn ? h('div', { class: 'warn' }, c.warn) : null);
      }
      return h('div', { class: 'imp-change' }, cb, h('span', { class: 'muted' }, c.kind === 'flat' ? 'Flat ' + c.label : c.label), what);
    }
    function drawList() {
      const people = plan.people.filter(p => !show || p.status === show);
      const out = people.map(p => {
        const role = !p.match && p.status !== 'skip' ? sel(roleOptions, roles[p.key] || '', { 'aria-label': 'Role for ' + p.name }) : null;
        if (role) role.addEventListener('change', () => { if (role.value) roles[p.key] = role.value; else delete roles[p.key]; drawSave(); });
        return h('div', { class: 'imp-person' + (p.status === 'skip' ? ' off' : '') },
          h('div', { class: 'row' }, h('b', null, p.name || '(no name)'), badge(...IMP_STATUS[p.status]),
            p.match && p.match.name !== p.name ? h('span', { class: 'muted small' }, 'found: ' + p.match.name) : null,
            h('span', { class: 'muted small' }, (p.phone || '') + (p.email ? ' · ' + p.email : '') + ' · line ' + p.lines.join(', ')),
            h('span', { class: 'sp' }), role ? h('span', { class: 'row small' }, 'Role', role) : null),
          p.changes.map(c => changeRow(p, c)),
          p.status === 'same' ? h('div', { class: 'muted small' }, 'Nothing to change.') : null,
          p.problems.map(x => h('div', { class: 'small', style: { color: 'var(--t-bad)' } }, x)),
          p.notes.map(x => h('div', { class: 'muted small' }, x)));
      });
      if (!show || show === 'skip') out.push(...plan.skipped.map(s => h('div', { class: 'imp-person off' }, h('div', { class: 'row' }, h('b', null, s.name), badge('Left out', 'bad'), h('span', { class: 'muted small' }, 'line ' + s.line)), h('div', { class: 'small' }, s.reason))));
      fill(list, out.length ? out : h('div', { class: 'muted' }, 'Nobody here.'));
    }
    saveBtn.addEventListener('click', async () => {
      if (needsRole().length) { toast('Give every new person a role, or untick them.', 'bad'); return; }
      const allSkip = [], allUse = [];
      plan.people.forEach(p => p.changes.forEach(c => { if (c.needs_relation) return; if (c.use && !isOn(c)) allSkip.push(c.id); if (!c.use && isOn(c)) allUse.push(c.id); }));
      saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
      try {
        const r = await api.post('/people/import/commit', { entries: plan.entries, skip: allSkip, use: allUse, roles, relations });
        stepDone(r);
      } catch (e) { fill(err, e.message); drawSave(); }
    });
    fill(body, h('div', { class: 'stack' },
      h('div', { class: 'small' }, plural(plan.entries.length, 'row') + ' read. ', h('b', null, plural(counts.new, 'new person', 'new people')), ', ' + counts.update + ' filled in or changed, ' + counts.same + ' already the same' + (counts.check ? ', ' + counts.check + ' to check' : '') + (counts.skip ? ', ' + counts.skip + ' left out' : '') + '.'),
      plan.flats ? null : (plan.columns.some(c => ['flat', 'wing', 'relation'].includes(c)) ? notice('This organisation does not keep flats yet, so the flat columns are left out.', 'warn') : null),
      h('div', { class: 'muted small' }, 'Ticked changes are saved. A different value in the file wins over the saved one, unless it is marked to check.'),
      chips, h('div', { class: 'imp-list' }, list),
      h('div', { class: 'row between' }, h('button', { class: 'btn', type: 'button', onclick: () => stepUpload() }, 'Choose another file'), h('span', { class: 'row' }, err, saveBtn))));
    drawChips(); drawList(); drawSave();
  }

  // ---- step 3: the result ----
  function stepDone(r) {
    m.setTitle('Import finished');
    fill(body, h('div', { class: 'stack' },
      notice(plural(r.added.length, 'person', 'people') + ' added, ' + plural(r.updated.length, 'person', 'people') + ' filled in or changed' + (r.skipped.length ? ', ' + r.skipped.length + ' left out.' : '.'), r.added.length || r.updated.length ? 'ok' : 'warn'),
      r.skipped.length ? h('div', null, h('b', null, 'Left out'), r.skipped.map(s => h('div', { class: 'small' }, 'Line ' + s.line + ' · ' + s.name + ': ' + s.reason))) : null,
      r.added.length ? h('div', { class: 'muted small' }, byNumber ? 'New people link their chat the first time they write: straight away when you gave a number, or with their email address.' : 'New people link their chat the first time they write, with the email address you gave.') : null,
      h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: () => { m.close(); location.reload(); } }, 'Done'))));
  }
  stepUpload();
}
"""
