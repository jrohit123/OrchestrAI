JS = r"""
// ───────────────────────── Import people from a CSV file ─────────────────────────
// Step 1 choose the file, step 2 check every row and set each person's role and seats in a list (nothing is saved yet),
// step 3 the result. The same screen for a super admin and an admin; the server checks every row again.
const IMPORT_SAMPLE = 'Name,Email,Phone,Role,Seat\nAsha Rao,asha@example.com,+919876543210,Tenant,\nVikram Shah,vikram@example.com,+919812345678,Committee,Secretary\n';
function importPeopleModal(lk) {
  const byNumber = (S.boot.org.channel || 'telegram') !== 'telegram';
  const hasSeats = (lk.seats || []).length > 0;
  const body = h('div', { class: 'imp' });
  const m = modal({ xwide: true, title: 'Import people from a file', body });
  let rows = [], holders = {}, replace = false;
  const savedCode = (() => { try { return localStorage.getItem('panel.countryCode') || ''; } catch (e) { return ''; } })();

  // ---- step 1: the file ----
  function stepUpload(message) {
    const file = h('input', { type: 'file', accept: '.csv,.txt,text/csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'aria-label': 'Choose a CSV or Excel file' });
    const paste = h('textarea', { rows: 5, placeholder: 'Or paste the rows here, first row with the column names', 'aria-label': 'Paste CSV text' });
    const code = byNumber ? h('input', { type: 'text', value: savedCode, placeholder: '+91', style: { width: '90px' }, 'aria-label': 'Country code for 10-digit numbers' }) : null;
    const go = h('button', { class: 'btn primary', type: 'button' }, 'Read the file');
    const err = h('div', { class: 'badtx small' }, message || '');
    go.addEventListener('click', async () => {
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
      go.disabled = true; go.textContent = 'Reading…';
      try {
        if (code) { try { localStorage.setItem('panel.countryCode', code.value.trim()); } catch (e) { /* private mode */ } }
        const r = await api.post('/people/import/preview', xlsx ? { file_b64: xlsx, file_name: f.name, country: code ? code.value.trim() : '' } : { csv_text: text, country: code ? code.value.trim() : '' });
        rows = r.rows.map(x => ({ ...x, use: x.ok })); holders = r.holders || {};
        stepReview();
      } catch (e) { err.textContent = e.message; go.disabled = false; go.textContent = 'Read the file'; }
    });
    const sample = h('a', { href: '#', onclick: e => { e.preventDefault(); const a = h('a', { href: URL.createObjectURL(new Blob([IMPORT_SAMPLE], { type: 'text/csv' })), download: 'people-sample.csv' }); document.body.append(a); a.click(); a.remove(); } }, 'Download a sample file');
    fill(body,
      h('div', { class: 'stack' },
        h('div', { class: 'muted small' }, 'One person per row. The first row names the columns: Name and Email are needed; Phone' + (byNumber ? '' : ' (ignored here)') + ' and Role are optional. A CSV or an Excel (.xlsx) file. ', sample, '.'),
        h('div', null, file),
        paste,
        code ? h('div', { class: 'row small' }, h('span', { class: 'muted' }, 'Country code for 10-digit numbers'), code, h('span', { class: 'muted' }, 'Numbers that already start with + are kept as they are.')) : null,
        err,
        h('div', { class: 'row' }, go)));
  }

  // ---- step 2: check and assign ----
  function seatButton(r) {
    const b = h('button', { class: 'btn sm', type: 'button', 'data-popkeep': '1' });
    const label = () => { b.textContent = r.seat_ids.length ? r.seat_ids.map(id => (lk.seats.find(s => s.id === id) || {}).name).filter(Boolean).join(', ') : 'No seat'; };
    b.addEventListener('click', e => {
      const list = h('div', { class: 'stack', style: { padding: '6px', maxHeight: '260px', overflow: 'auto' } }, lk.seats.map(s => {
        const cb = h('input', { type: 'checkbox', checked: r.seat_ids.includes(s.id) });
        cb.addEventListener('change', () => { r.seat_ids = cb.checked ? [...r.seat_ids, s.id] : r.seat_ids.filter(x => x !== s.id); label(); });
        return h('label', { class: 'row small' }, cb, h('span', null, s.name), holders[s.id] ? h('span', { class: 'muted' }, ' · held by ' + holders[s.id]) : null);
      }));
      openPop(e.currentTarget, list, { width: 280 });
    });
    label();
    return b;
  }
  function stepReview() {
    const roleOptions = [['', 'Choose a role…'], ...lk.roles.map(r => [r.id, roleLabel(r.name)])];
    const bulkRole = sel(roleOptions, '', { 'aria-label': 'Role to give' });
    const summary = h('div', { class: 'muted small' });
    const tbody = h('tbody');
    const countReady = () => rows.filter(r => r.use && r.role_id).length;
    const addBtn = h('button', { class: 'btn primary', type: 'button' });
    const refreshSummary = () => {
      const bad = rows.filter(r => !r.ok).length, noRole = rows.filter(r => r.use && !r.role_id).length;
      fill(summary, rows.length + ' rows read. ' + (bad ? bad + ' have a problem and are left out. ' : '') + (noRole ? noRole + ' still need a role.' : ''));
      addBtn.textContent = 'Add ' + countReady() + ' ' + (countReady() === 1 ? 'person' : 'people'); addBtn.disabled = !countReady();
    };
    const drawRows = () => {
      fill(tbody, rows.map(r => {
        const use = h('input', { type: 'checkbox', checked: r.use, disabled: !r.ok, 'aria-label': 'Add ' + r.name });
        use.addEventListener('change', () => { r.use = use.checked; refreshSummary(); });
        const role = sel(roleOptions, r.role_id || '', { 'aria-label': 'Role for ' + r.name, disabled: !r.ok });
        role.addEventListener('change', () => { r.role_id = role.value || null; refreshSummary(); tr.classList.toggle('needs', r.use && !r.role_id); });
        const flags = [...r.problems.map(p => badge(p, 'bad')), ...r.notes.map(n => h('div', { class: 'muted small' }, n))];
        const tr = h('tr', { class: r.ok ? (r.use && !r.role_id ? 'needs' : '') : 'off' },
          h('td', null, use), h('td', { class: 'muted' }, r.line),
          h('td', null, h('b', null, r.name || '—'), h('div', { class: 'muted small' }, r.email + (r.phone ? ' · ' + r.phone : ''))),
          h('td', null, r.ok ? role : h('span', { class: 'muted' }, '—')),
          hasSeats ? h('td', null, r.ok ? seatButton(r) : h('span', { class: 'muted' }, '—')) : null,
          h('td', null, flags.length ? flags : badge('Ready', 'ok')));
        return tr;
      }));
    };
    const apply = (onlyEmpty) => {
      if (!bulkRole.value) { toast('Choose the role to give first.', 'bad'); return; }
      rows.forEach(r => { if (r.ok && r.use && (!onlyEmpty || !r.role_id)) r.role_id = bulkRole.value; });
      drawRows(); refreshSummary();
    };
    const all = h('input', { type: 'checkbox', checked: true, 'aria-label': 'Select every row' });
    all.addEventListener('change', () => { rows.forEach(r => { if (r.ok) r.use = all.checked; }); drawRows(); refreshSummary(); });
    const rep = hasSeats ? h('label', { class: 'row small' }, h('input', { type: 'checkbox', onchange: e => { replace = e.target.checked; } }), h('span', null, 'If a seat already has someone, replace them (the earlier holder is kept in the history).')) : null;
    const err = h('span', { class: 'badtx small' });
    addBtn.addEventListener('click', async () => {
      err.textContent = '';
      const send = rows.filter(r => r.use && r.role_id);
      if (rows.some(r => r.use && !r.role_id)) { err.textContent = 'Give every ticked person a role, or untick them.'; return; }
      addBtn.disabled = true; addBtn.textContent = 'Adding…';
      try {
        const r = await api.post('/people/import/commit', { rows: send.map(x => ({ line: x.line, name: x.name, email: x.email, phone: x.phone, role_id: x.role_id, seat_ids: x.seat_ids })), replace_seats: replace });
        stepDone(r);
      } catch (e) { err.textContent = e.message; refreshSummary(); }
    });
    fill(body, h('div', { class: 'stack' },
      summary,
      h('div', { class: 'row' }, h('span', { class: 'small muted' }, 'Give everyone ticked'), bulkRole,
        h('button', { class: 'btn sm', type: 'button', onclick: () => apply(true) }, 'only those without a role'), h('button', { class: 'btn sm', type: 'button', onclick: () => apply(false) }, 'all ticked rows')),
      h('div', { class: 'tablewrap' }, h('table', { class: 't imp-t' },
        h('thead', null, h('tr', null, h('th', null, all), h('th', null, 'Line'), h('th', null, 'Person'), h('th', null, 'Role'), hasSeats ? h('th', null, 'Seats') : null, h('th', null, 'Check'))), tbody)),
      rep,
      h('div', { class: 'row between' }, h('button', { class: 'btn', type: 'button', onclick: () => stepUpload() }, 'Choose another file'), h('span', { class: 'row' }, err, addBtn))));
    drawRows(); refreshSummary();
  }

  // ---- step 3: the result ----
  function stepDone(r) {
    m.setTitle('Import finished');
    fill(body, h('div', { class: 'stack' },
      notice(r.added.length + ' ' + (r.added.length === 1 ? 'person was' : 'people were') + ' added.' + (r.skipped.length ? ' ' + r.skipped.length + ' were skipped.' : ''), r.added.length ? 'ok' : 'warn'),
      r.skipped.length ? h('div', null, h('b', null, 'Skipped'), r.skipped.map(s => h('div', { class: 'small' }, 'Line ' + s.line + ' · ' + s.name + ': ' + s.reason))) : null,
      r.added.some(a => a.notes.length) ? h('div', null, h('b', null, 'About seats'), r.added.filter(a => a.notes.length).map(a => h('div', { class: 'small' }, a.name + ': ' + a.notes.join(' ')))) : null,
      h('div', { class: 'muted small' }, byNumber ? 'They link their chat the first time they write: with the email address you gave, or straight away when you gave a number.' : 'They link their chat the first time they write, with the email address you gave.'),
      h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: () => { m.close(); location.reload(); } }, 'Done'))));
  }
  stepUpload();
}
"""
