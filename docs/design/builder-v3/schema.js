// =====================================================================================================
// Data & schema (super admin only): what each use case keeps, and how it changes.
// Two ways: change the fields by hand, or describe the change and let the AI draft a plan you check.
// Every change is validated, tried in a transaction that is rolled back, backed up, then applied and logged.
// =====================================================================================================
const SB = { log: [{ v: 'housing-0013', by: 'kartik', sum: 'Time to fix and reminder plans' }, { v: 'core-0026', by: 'kartik', sum: 'Flows that start by themselves' }], pending: {} };

function screenSchema(root, r) {
  if (!isSuper()) { go('home'); return; }
  drawTop([h('b', null, 'Data & schema')]);
  const tab = r.a === 'ai' ? 'ai' : r.a === 'log' ? 'log' : 'records';
  const recKey = DB.records[r.a] ? r.a : (DB.records[r.b] ? r.b : Object.keys(DB.records)[0]);
  add(root, head('Data & schema', 'What each use case keeps. Only super admins see this. Every change is checked against the live database, tried and rolled back first, and backed up before it is applied.'),
    h('div', { class: 'tabs' }, [['records', 'Record types'], ['ai', '✨ Describe a change'], ['log', 'History']].map(([k, l]) => h('button', { class: 'tab' + (tab === k ? ' on' : ''), onclick: () => go('schema', k === 'records' ? recKey : k) }, l))));
  if (tab === 'records') schemaRecords(root, recKey);
  else if (tab === 'ai') aiBuilder(root);
  else schemaLog(root);
}

// ---------------- by hand ----------------
const TYPES = { text: 'Words', number: 'Number', date: 'Date', time: 'Time', datetime: 'Date and time', choice: 'One of a list', phone: 'Phone number', photo: 'Photos', person: 'A person', yesno: 'Yes / no' };
const SQLTYPE = { text: 'text', number: 'integer', date: 'date', time: 'time', datetime: 'timestamptz', choice: 'text', phone: 'text', photo: 'jsonb', person: 'uuid REFERENCES public.users(id)', yesno: 'boolean' };
function schemaRecords(root, key) {
  const R = DB.records[key], usedBy = DB.usecases.filter(u => u.record === key);
  const pend = SB.pending[key] = SB.pending[key] || [];
  const list = h('div', { class: 'card' }), side = h('div', { class: 'col', style: { gap: '14px' } });
  function draw() {
    fill(list, h('div', { class: 'card-h' }, R.plural, usedBy.map(u => pill(u.icon + ' ' + u.name)), h('span', { class: 'sp' }), h('button', { class: 'btn sm pri', onclick: addField }, '+ Add a field')),
      h('div', { class: 'card-b' },
        h('div', { class: 'fld head' }, h('span', null, 'Field'), h('span', null, 'Kind'), h('span', null, 'Required'), h('span', null, 'Used in'), h('span')),
        R.fields.map(f => { const isNew = pend.some(p => p.key === f.key); const uses = DB.flows.filter(fl => JSON.stringify(fl.graph).includes('.' + f.key + '}')).length;
          return h('div', { class: 'fld' + (isNew ? ' new' : '') }, h('div', null, h('b', null, f.label), f.system ? h('span', { class: 'tiny muted' }, ' · made by the system') : null, f.options ? h('div', { class: 'tiny muted' }, f.options.join(' · ')) : null),
            h('span', { class: 'small' }, TYPES[f.type] || f.type), h('span', null, f.required ? '✓' : '—'), h('span', { class: 'small muted' }, uses ? uses + ' flow' + (uses > 1 ? 's' : '') : '—'),
            f.system ? h('span') : h('button', { class: 'btn sm ghost', title: 'Remove', onclick: async () => { if (uses && !(await confirmBox('“' + f.label + '” is used in ' + uses + ' flow(s). Removing it breaks them until they are changed. Remove it anyway?', 'Remove'))) return; R.fields.splice(R.fields.indexOf(f), 1); pend.push({ drop: f.key, label: f.label }); draw(); } }, '×')); })));
    const sql = pend.map(p => p.drop ? `ALTER TABLE public.${key}s DROP COLUMN ${p.drop};` : `ALTER TABLE public.${key}s ADD COLUMN ${p.key} ${SQLTYPE[p.type]}${p.required ? ' NOT NULL DEFAULT ' + (p.type === 'number' ? '0' : p.type === 'yesno' ? 'false' : "''") : ''};` + (p.type === 'choice' ? `\nALTER TABLE public.${key}s ADD CONSTRAINT ${key}s_${p.key}_check CHECK (${p.key} IN (${(p.options || []).map(o => "'" + o.replace(/'/g, "''") + "'").join(', ')}));` : '')).join('\n');
    fill(side,
      h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Record types'), h('div', { class: 'card-b col' }, Object.entries(DB.records).map(([k, x]) => h('button', { class: 'ni' + (k === key ? ' on' : ''), onclick: () => go('schema', k) }, x.plural, h('span', { class: 'ct' }, x.fields.length))), h('button', { class: 'btn sm', onclick: () => go('schema', 'ai') }, '✨ A new record type: describe it'))),
      h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Waiting changes', pend.length ? pill(pend.length, 'warn') : null), h('div', { class: 'card-b col' },
        pend.length ? [h('pre', { class: 'code', style: { minHeight: '0' } }, '-- drafted from your changes\nBEGIN;\n' + sql + '\nCOMMIT;'), applyPipeline(sql, () => { SB.log.push({ v: 'core-00' + (27 + SB.log.length - 2), by: 'kartik', sum: pend.map(p => (p.drop ? 'removed ' : 'added ') + (p.label || p.key)).join(', ') + ' on ' + R.plural.toLowerCase() }); SB.pending[key] = []; schemaScreenAgain(); })]
          : h('div', { class: 'small muted' }, 'Add or remove a field and the database change appears here, to check and apply.'))),
      h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Also part of ' + R.plural.toLowerCase()), h('div', { class: 'card-b small col' },
        h('div', null, h('b', null, 'Statuses: '), R.statuses.join(' → ')), h('div', null, h('b', null, 'People on it: '), R.people.map(p => p.label).join(', ')),
        usedBy[0] ? h('a', { href: '#/uc/' + usedBy[0].id + '/setup' }, 'Change these in ' + usedBy[0].name + ' › How it is set up →') : null)));
  }
  function addField() {
    const label = h('input', { type: 'text', placeholder: 'e.g. Vehicle number' }), type = h('select', null, Object.entries(TYPES).map(([k, l]) => h('option', { value: k }, l)));
    const opts = h('input', { type: 'text', placeholder: 'Choices, comma separated' }), req = h('input', { type: 'checkbox' });
    modal({ title: 'Add a field to ' + R.plural.toLowerCase(), body: h('div', { class: 'col' }, h('label', { class: 'f' }, 'Name', label), h('label', { class: 'f' }, 'Kind', type), h('label', { class: 'f' }, 'Choices (for "One of a list")', opts), h('label', { class: 'row small' }, req, 'People must fill it in'),
      h('div', { class: 'notice' }, 'ℹ️', 'Flows can use it straight away: it shows up in “Fill in”, in “What it can use”, and in the WhatsApp form builder.')),
      actions: [{ label: 'Cancel' }, { label: 'Add field', primary: true, run: () => {
        const l = label.value.trim(); if (!l) { toast('Give it a name'); return false; }
        const f = { key: slug(l), label: l, type: type.value, required: req.checked, sample: '…', options: type.value === 'choice' ? opts.value.split(',').map(x => x.trim()).filter(Boolean) : undefined };
        R.fields.push(f); pend.push(f); draw();
      } }] });
  }
  add(root, h('div', { class: 'grid', style: { gridTemplateColumns: 'minmax(0,1fr) 380px', alignItems: 'start' } }, list, side));
  draw();
}
function schemaScreenAgain() { render(); }

// the same pipeline for both ways: check → try and roll back → back up → apply → log
function applyPipeline(sql, onApplied) {
  const steps = [['Check it against the live database', 'Tables, columns, flows and roles it touches'], ['Try it, then undo it', 'BEGIN; run every statement; ROLLBACK'], ['Back up the database', 'A full copy before anything changes'], ['Apply it', 'BEGIN; apply; COMMIT'], ['Write it in the history', 'schema_migrations and the change log']];
  const st = steps.map(() => 'idle');
  const box = h('div');
  const btn = h('button', { class: 'btn pri', onclick: run }, 'Check and apply');
  function draw() { fill(box, steps.map(([t, d], i) => h('div', { class: 'step ' + st[i] }, h('div', { class: 'si' }, st[i] === 'ok' ? '✓' : st[i] === 'fail' ? '!' : i + 1), h('div', null, h('b', { class: 'small' }, t), h('small', null, d)))), btn); }
  async function run() {
    btn.disabled = true;
    for (let i = 0; i < steps.length; i++) {
      st[i] = 'run'; draw(); await new Promise(r => setTimeout(r, 650));
      if (i === 0 && /DROP COLUMN/.test(sql)) { st[i] = 'ok'; steps[i][1] = 'Warning: removing a column deletes its data. Kept in the backup.'; }
      st[i] = 'ok'; draw();
      if (i === 2 && !(await confirmBox('Backup saved (godrej_2026-10-15_1630.dump, simulated). Apply the change to the live database now?', 'Apply'))) { btn.disabled = false; st[3] = st[4] = 'idle'; draw(); return; }
    }
    toast('Applied and logged (simulated in this prototype)'); onApplied && onApplied();
  }
  draw(); return box;
}

// ---------------- describe a change: the AI change builder ----------------
const SCEN = {
  bookings: { re: /book|hall|court|clubhouse|facility|slot/i, name: 'Facility booking',
    read: [['Book a facility for a time', 'New table facility_bookings, overlap blocked by the database', 'new'], ['Facilities list', 'New table facilities', 'new'], ['Who may book', 'Roles you already have', 'reuse'], ['Committee approval', 'The “Ask for approval” step', 'reuse']],
    qs: [['How long is one slot?', ['30 minutes', '1 hour', '2 hours']], ['Does the committee approve each booking?', ['Yes', 'No, confirm straight away']], ['Which facilities?', ['Clubhouse, party hall, courts', 'Only the clubhouse']]] },
  parking: { re: /park|vehicle|car|bike|sticker/i, name: 'Parking and vehicles',
    read: [['Vehicles of a flat', 'New table vehicles (number, kind, flat)', 'new'], ['Parking slots', 'New table parking_slots', 'new'], ['Guards check a number', 'A “Find a record” step by vehicle number', 'reuse']],
    qs: [['How many vehicles may a flat register?', ['2', '3', 'No limit']], ['Do guards need to see them?', ['Yes', 'No']]] },
  generic: { re: /./, name: 'A new kind of record',
    read: [['Keep the records', 'A new record type with a number, a status and people on it', 'new'], ['Flows to create and list them', 'Two starter flows', 'new']],
    qs: [['Who creates them?', ['Residents', 'Staff', 'Both']], ['Does someone approve them?', ['Yes', 'No']]] },
};
function aiBuilder(root) {
  const st = { stage: 'idle', sc: null, qi: 0, ans: [], draft: null, tab: 'summary' };
  const log = h('div', { class: 'log' }), ta = h('input', { type: 'text', placeholder: 'e.g. Residents should register their vehicles for parking' });
  const planBox = h('div', { class: 'card' }), pipeBox = h('div', { class: 'card' });
  const say = (html, chips) => { const m = h('div', { class: 'cm ai', html }); if (chips) m.append(h('div', { class: 'chipbox', style: { marginTop: '6px' } }, chips.map((c, i) => h('span', { class: 'chip', onclick: () => answer(i) }, c)))); log.append(m); log.scrollTop = 1e6; };
  const me = t => { log.append(h('div', { class: 'cm me' }, t)); log.scrollTop = 1e6; };
  const tool = t => { log.append(h('div', { class: 'cm tool' }, '› ' + t)); };
  async function send(text) {
    text = (text || ta.value).trim(); if (!text) return; ta.value = ''; me(text);
    if (st.stage === 'idle') {
      st.sc = Object.entries(SCEN).find(([k, s]) => s.re.test(text))[0]; const S2 = SCEN[st.sc];
      tool('read_schema() → ' + Object.keys(DB.records).length + ' record types, ' + DB.roleGroups.flatMap(g => g.roles).length + ' roles, ' + DB.flows.length + ' flows, ' + Object.keys(STEPS).length + ' step types');
      await new Promise(r => setTimeout(r, 400));
      log.append(h('div', { class: 'cm ai' }, h('b', { class: 'small' }, 'How I read it against what you have'), h('table', { class: 't', style: { marginTop: '6px' } }, S2.read.map(r2 => h('tr', null, h('td', { class: 'small' }, r2[0]), h('td', { class: 'small muted' }, r2[1]), h('td', null, pill(r2[2] === 'new' ? 'NEW' : 'REUSE', r2[2] === 'new' ? 'warn' : 'ok')))))));
      st.stage = 'asking'; st.qi = 0; say('A few questions so I do not guess.'); ask();
    } else if (st.stage === 'asking') { answer(-1, text); }
    else say('Change anything in the plan on the right, or press the buttons there. In the real tool this message would revise the plan.');
  }
  function ask() { const q = SCEN[st.sc].qs[st.qi]; say(esc(q[0]), q[1]); }
  async function answer(i, typed) {
    const q = SCEN[st.sc].qs[st.qi]; if (!q || st.stage !== 'asking') return;
    const v = typed != null ? (q[1].find(o => o.toLowerCase().includes(typed.toLowerCase())) || typed) : q[1][i];
    if (typed == null) me(v); st.ans.push(v); st.qi++;
    if (st.qi < SCEN[st.sc].qs.length) { ask(); return; }
    tool('draft_change_plan(' + st.ans.map(a => JSON.stringify(a)).join(', ') + ')'); await new Promise(r => setTimeout(r, 500));
    st.draft = makePlan(st.sc, st.ans); st.stage = 'drafted';
    say('The plan is ready on the right. Read <b>Summary</b> first, then the tables, flows and access. Change anything you disagree with, then <b>Check and apply</b>.');
    drawPlan();
  }
  function drawPlan() {
    if (!st.draft) { fill(planBox, h('div', { class: 'card-h' }, 'The plan'), h('div', { class: 'empty' }, 'Describe what a client needs on the left. After a few questions the plan appears here, and every part of it can be edited.')); fill(pipeBox, h('div', { class: 'card-h' }, 'Check and apply'), h('div', { class: 'card-b small muted' }, 'Nothing to apply yet.')); return; }
    const tabs = [['summary', 'Summary'], ['sql', 'Tables (SQL)'], ['flows', 'Flows'], ['access', 'Access'], ['rollback', 'Way back']];
    const body = h('div', { class: 'card-b' });
    if (st.tab === 'summary') add(body, h('div', { class: 'col small' }, h('div', null, st.draft.intro), h('b', null, 'New'), h('ul', { style: { margin: 0 } }, st.draft.news.map(x => h('li', null, x))), h('b', null, 'Reused'), h('ul', { style: { margin: 0 } }, st.draft.reuse.map(x => h('li', null, x))), h('b', null, 'Check before you trust it'), h('ul', { style: { margin: 0 } }, st.draft.notes.map(x => h('li', null, x)))));
    else { const t = h('textarea', { class: 'code', spellcheck: false }); t.value = st.draft[st.tab]; t.addEventListener('input', () => { st.draft[st.tab] = t.value; }); add(body, t); }
    fill(planBox, h('div', { class: 'card-h' }, 'The plan: ' + SCEN[st.sc].name, pill('draft, editable', 'warn')), h('div', { class: 'tabs', style: { padding: '0 12px', margin: 0 } }, tabs.map(([k, l]) => h('button', { class: 'tab' + (st.tab === k ? ' on' : ''), onclick: () => { st.tab = k; drawPlan(); } }, l))), body);
    fill(pipeBox, h('div', { class: 'card-h' }, 'Check and apply'), h('div', { class: 'card-b' }, applyPipeline(st.draft.sql, () => {
      SB.log.push({ v: 'feature-' + st.sc, by: 'kartik', sum: SCEN[st.sc].name + ' (from a description)' });
      if (st.sc === 'parking' && !DB.records.vehicle) { DB.records.vehicle = { label: 'Vehicle', plural: 'Vehicles', prefix: 'VH', fields: [{ key: 'number', label: 'Vehicle number', type: 'text', required: true, sample: 'MH 01 AB 1234' }, { key: 'kind', label: 'Kind', type: 'choice', options: ['Car', 'Bike'], sample: 'Car' }], statuses: ['Registered', 'Removed'], people: [{ key: 'owner', label: 'Owner', sample: 'Venkatesh Batchu' }] }; DB.usecases.push({ id: 'parking', name: 'Parking', icon: '🅿️', color: '#495057', record: 'vehicle', desc: 'Vehicles of each flat, checked by guards.', menu: ['Register', 'My vehicles'] }); DB.items.parking = []; DB.permissions.parking = clone(DB.permissions.tickets); drawSide(); toast('New use case “Parking” is in the menu'); }
    })));
  }
  const input = h('div', { class: 'in' }, ta, h('button', { class: 'btn pri', onclick: () => send() }, 'Send'));
  ta.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
  add(root, h('div', { class: 'sb3' },
    h('div', { class: 'card chat' }, h('div', { class: 'card-h' }, '1 · Describe it'), log, h('div', { class: 'chipbox', style: { padding: '0 10px 8px' } }, ['Facility booking with committee approval', 'Residents register vehicles for parking', 'A notice board'].map(x => h('span', { class: 'chip', onclick: () => st.stage === 'idle' && send(x) }, x))), input),
    planBox, pipeBox));
  say('Tell me what the client needs, in plain words. I read your current tables, flows and roles first, reuse what fits, and draft only what is new. You check and change everything before it is applied.');
  drawPlan();
}
function makePlan(sc, ans) {
  if (sc === 'parking') return {
    intro: 'Each flat registers up to ' + ans[0] + ' vehicles. Guards ' + (ans[1] === 'Yes' ? 'can look a number up at the gate.' : 'do not see them.') + ' This adds a Parking use case with two flows.',
    news: ['Table vehicles (number, kind, flat, owner)', 'Use case Parking with menu groups Register and My vehicles', 'Flows: Register a vehicle, My vehicles'], reuse: ['Roles and flats you already have', 'The Find a record step for guards'], notes: ['Vehicle numbers are kept in capitals without spaces so a lookup always matches.', ans[0] === 'No limit' ? 'No limit is set: check this with the committee.' : 'The limit is checked in the flow, not in the database.'],
    sql: "CREATE TABLE public.vehicles (\n    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,\n    org_id uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,\n    number text NOT NULL,\n    kind text NOT NULL CHECK (kind IN ('Car','Bike')),\n    flat text NOT NULL,\n    owner_id uuid REFERENCES public.users(id) ON DELETE SET NULL,\n    status text DEFAULT 'Registered' NOT NULL,\n    created_at timestamptz DEFAULT now() NOT NULL,\n    UNIQUE (org_id, number)\n);\nCREATE INDEX idx_vehicles_flat ON public.vehicles (org_id, flat);",
    flows: '[\n  { "name": "Register a vehicle", "starts": "chat: Parking › Register", "steps": ["Ask: vehicle number", "Ask: car or bike", "Check: fewer than ' + ans[0] + ' for this flat", "Save a new vehicle", "Send: registered"] },\n  { "name": "My vehicles", "starts": "chat: Parking › My vehicles", "steps": ["List vehicles of this flat", "Send the list"] }\n]',
    access: '{ "Register a vehicle": ["Primary resident", "Joint member", "Tenant"],\n  "Find a vehicle": ["Guard"] }', rollback: 'DROP TABLE public.vehicles;' };
  if (sc === 'bookings') return {
    intro: 'Residents book ' + ans[2].toLowerCase() + ' in ' + ans[0] + ' slots. ' + (ans[1] === 'Yes' ? 'The committee approves each booking.' : 'Bookings are confirmed straight away.') + ' The database itself refuses two bookings that overlap.',
    news: ['Table facilities', 'Table facility_bookings with an overlap rule'], reuse: ['Bookings use case and its flows', ans[1] === 'Yes' ? 'The Ask for approval step' : 'No approval'], notes: ['Overlap is blocked by an exclusion rule, so two people booking at once cannot both win.'],
    sql: "CREATE EXTENSION IF NOT EXISTS btree_gist;\nCREATE TABLE public.facilities (id uuid DEFAULT gen_random_uuid() PRIMARY KEY, org_id uuid NOT NULL REFERENCES public.orgs(id), name text NOT NULL, slot_minutes integer DEFAULT " + (parseInt(ans[0]) === 30 ? 30 : parseInt(ans[0]) * 60) + " NOT NULL, UNIQUE (org_id, name));\nCREATE TABLE public.facility_bookings (\n    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,\n    facility_id uuid NOT NULL REFERENCES public.facilities(id),\n    starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL,\n    status text DEFAULT '" + (ans[1] === 'Yes' ? 'pending' : 'confirmed') + "' NOT NULL,\n    EXCLUDE USING gist (facility_id WITH =, tstzrange(starts_at, ends_at) WITH &&) WHERE (status IN ('pending','confirmed'))\n);",
    flows: '[ { "name": "Book a facility", "steps": ["Ask facility", "Ask date and time", "Block: Check a slot is free"' + (ans[1] === 'Yes' ? ', "Ask for approval: Secretary"' : '') + ', "Save a new booking", "Send: booked"] } ]', access: '{ "Book a facility": ["Residents"] }', rollback: 'DROP TABLE public.facility_bookings;\nDROP TABLE public.facilities;' };
  return { intro: 'A new record type that ' + ans[0].toLowerCase() + ' create' + (ans[1] === 'Yes' ? ', approved by the committee.' : '.'), news: ['A record type with number, title, status and people on it', 'Flows: Create, My list'], reuse: ['Roles, approval step, reminders'], notes: ['Name the record and its statuses before applying.'],
    sql: "CREATE TABLE public.notices (\n    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,\n    org_id uuid NOT NULL REFERENCES public.orgs(id),\n    title text NOT NULL,\n    body text,\n    status text DEFAULT 'Draft' NOT NULL,\n    created_by uuid REFERENCES public.users(id),\n    created_at timestamptz DEFAULT now() NOT NULL\n);", flows: '[ { "name": "Post a notice" }, { "name": "Notices" } ]', access: '{ "Post a notice": ["Committee"] }', rollback: 'DROP TABLE public.notices;' };
}

function schemaLog(root) {
  add(root, h('div', { class: 'card' }, h('table', { class: 't' }, h('tr', null, h('th', null, 'Change'), h('th', null, 'By'), h('th', null, 'What')), SB.log.slice().reverse().map(l => h('tr', null, h('td', null, h('code', null, l.v)), h('td', null, l.by), h('td', { class: 'small' }, l.sum))))));
}
