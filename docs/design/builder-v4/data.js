// Everything the builder shows comes from here. Nothing on screen is written into the screens themselves:
// use cases, record types, their fields, statuses and the kinds of people on a record, roles, step types,
// flows and building blocks are all data that a super admin can change.

const DB = {
  org: { name: 'Godrej Emerald', short: 'GE' },

  // ---------------- use cases: the top level of everything ----------------
  usecases: [
    { id: 'tickets', name: 'Tickets', icon: '🎫', color: '#e8590c', record: 'ticket', desc: 'Complaints and requests from residents, handled by staff.', menu: ['Raise', 'My tickets', 'Reports'] },
    { id: 'bookings', name: 'Bookings', icon: '📅', color: '#1c7ed6', record: 'booking', desc: 'Clubhouse, party hall, courts. Two bookings can never overlap.', menu: ['Book', 'My bookings'] },
    { id: 'visitors', name: 'Visitors', icon: '🚪', color: '#2f9e44', record: 'visitor', desc: 'Guests approved by residents, checked in by the guard.', menu: ['Pre-approve', 'At the gate'] },
  ],

  // ---------------- record types (the "schema"): fields, statuses, people on a record ----------------
  records: {
    ticket: {
      label: 'Ticket', plural: 'Tickets', prefix: 'TK',
      fields: [
        { key: 'number', label: 'Number', type: 'text', system: true, sample: 'TK-26-0142' },
        { key: 'title', label: 'Title', type: 'text', required: true, sample: 'Water leaking from the ceiling' },
        { key: 'kind', label: 'Kind', type: 'choice', options: ['Plumbing', 'Electrical', 'Lift', 'Housekeeping', 'Security', 'Something else'], required: true, sample: 'Plumbing' },
        { key: 'priority', label: 'Urgency', type: 'choice', options: ['Low', 'Medium', 'High', 'Urgent'], sample: 'High' },
        { key: 'place', label: 'Where', type: 'text', sample: 'T7 1104 bathroom' },
        { key: 'photos', label: 'Photos', type: 'photo', sample: '2 photos' },
        { key: 'due', label: 'Due by', type: 'date', system: true, sample: '17 Oct, 7:00 pm' },
      ],
      statuses: ['Reported', 'Under review', 'Action taken', 'Closed'],
      people: [
        { key: 'raiser', label: 'Raised it', sample: 'Venkatesh Batchu' },
        { key: 'handler', label: 'Handling it', sample: 'Anuja Sinkar' },
        { key: 'backup', label: 'Backup', sample: 'Chetan B.' },
        { key: 'told', label: 'Also told', sample: 'Rohit J.' },
        { key: 'watcher', label: 'Watching', sample: 'Kartik B.' },
      ],
    },
    booking: {
      label: 'Booking', plural: 'Bookings', prefix: 'BK',
      fields: [
        { key: 'number', label: 'Number', type: 'text', system: true, sample: 'BK-26-0031' },
        { key: 'facility', label: 'Facility', type: 'choice', options: ['Clubhouse', 'Party hall', 'Squash court', 'Swimming pool'], required: true, sample: 'Party hall' },
        { key: 'date', label: 'Date', type: 'date', required: true, sample: 'Sat 18 Oct' },
        { key: 'from', label: 'From', type: 'time', required: true, sample: '6:00 pm' },
        { key: 'until', label: 'Until', type: 'time', required: true, sample: '10:00 pm' },
        { key: 'guests', label: 'Guests', type: 'number', sample: '40' },
      ],
      statuses: ['Pending', 'Confirmed', 'Cancelled', 'Rejected'],
      people: [
        { key: 'booker', label: 'Booked it', sample: 'Rajeswari Batchu' },
        { key: 'approver', label: 'Approves it', sample: 'Secretary' },
      ],
    },
    visitor: {
      label: 'Visitor', plural: 'Visitors', prefix: 'VS',
      fields: [
        { key: 'number', label: 'Number', type: 'text', system: true, sample: 'VS-26-0207' },
        { key: 'name', label: 'Visitor name', type: 'text', required: true, sample: 'Ramesh Kumar' },
        { key: 'phone', label: 'Visitor phone', type: 'phone', sample: '+91 98•••• 4410' },
        { key: 'purpose', label: 'Purpose', type: 'choice', options: ['Guest', 'Delivery', 'Cab', 'Service'], sample: 'Guest' },
        { key: 'expected', label: 'Expected at', type: 'datetime', sample: 'Today 7:30 pm' },
        { key: 'pass', label: 'Gate pass', type: 'text', system: true, sample: '4821' },
      ],
      statuses: ['Expected', 'At the gate', 'Inside', 'Left', 'Turned away'],
      people: [
        { key: 'host', label: 'Host resident', sample: 'Venkatesh Batchu' },
        { key: 'guard', label: 'Guard on duty', sample: 'Suresh (Gate 1)' },
      ],
    },
  },

  // ---------------- roles, in groups ----------------
  roleGroups: [
    { id: 'residents', name: 'Residents', roles: ['Primary resident', 'Joint member', 'Other resident', 'Tenant'] },
    { id: 'committee', name: 'Committee', roles: ['Chairman', 'Secretary', 'Treasurer', 'Committee member'] },
    { id: 'staff', name: 'Staff', roles: ['Executive', 'Manager', 'Sr. manager', 'Facility manager', 'Guard'] },
  ],
  // what a role may do in each use case. see: none / own / flat / all
  abilities: [
    { key: 'see', label: 'See', kind: 'scope' },
    { key: 'raise', label: 'Raise / create', kind: 'tick' },
    { key: 'assign', label: 'Give to someone', kind: 'tick' },
    { key: 'close', label: 'Close / finish', kind: 'tick' },
    { key: 'manage', label: 'Change its settings', kind: 'tick' },
  ],
  scopes: { none: 'Nothing', own: 'Their own', flat: "Their flat's", all: 'Everything' },
  permissions: {}, // filled in below

  people: [
    { name: 'Venkatesh Batchu', role: 'Primary resident', flat: 'T7 1104' },
    { name: 'Rajeswari Batchu', role: 'Joint member', flat: 'T7 1104' },
    { name: 'Anuja Sinkar', role: 'Facility manager', flat: '' },
    { name: 'Rohit J.', role: 'Secretary', flat: 'T2 0603' },
    { name: 'Chetan B.', role: 'Executive', flat: '' },
    { name: 'Suresh', role: 'Guard', flat: '' },
    { name: 'Meena Kulkarni', role: 'Manager', flat: '' },
    { name: 'Farah Sheikh', role: 'Tenant', flat: 'T3 0402' },
  ],

  forms: ['Complaint form', 'Visitor entry form (guard)', 'Booking request form'],
  templates: ['Awaiting your response', 'Visitor at the gate', 'Booking approved'],
};

// default permissions: residents see their flat's, committee and managers see all
(function () {
  const P = DB.permissions;
  DB.usecases.forEach(u => {
    P[u.id] = {};
    DB.roleGroups.forEach(g => g.roles.forEach(r => {
      const res = g.id === 'residents', com = g.id === 'committee', guard = r === 'Guard';
      P[u.id][r] = {
        see: res ? (r === 'Tenant' || r === 'Other resident' ? 'own' : 'flat') : guard ? (u.id === 'visitors' ? 'all' : 'none') : 'all',
        raise: !guard || u.id === 'visitors',
        assign: com || ['Manager', 'Sr. manager', 'Facility manager'].includes(r),
        close: !res && !(guard && u.id !== 'visitors'),
        manage: ['Chairman', 'Secretary', 'Sr. manager'].includes(r),
      };
    }));
  });
})();

// ---------------- the step types (nodes). Settings are described as data, the window draws them ----------------
// kind -> colour group; fields -> settings; outs -> branches; gives(cfg) -> values the step makes for later steps
const KINDS = {
  start: { label: 'How it starts', color: 'var(--k-start)' },
  talk: { label: 'Talk to the person', color: 'var(--k-talk)' },
  data: { label: 'Records', color: 'var(--k-data)' },
  decide: { label: 'Decide and wait', color: 'var(--k-decide)' },
  people: { label: 'People', color: 'var(--k-people)' },
  ai: { label: 'AI', color: 'var(--k-ai)' },
  block: { label: 'Building blocks', color: 'var(--k-block)' },
  adv: { label: 'Advanced (super admin)', color: 'var(--k-adv)' },
};

const STEPS = {
  // ----- how it starts -----
  chat: { kind: 'start', icon: '💬', name: 'Someone asks in chat', help: 'A phrase, a menu choice or a /command starts it.', start: true,
    fields: [
      { key: 'menu', label: 'Show it in the menu under', type: 'menuplace' },
      { key: 'phrases', label: 'Things people might say', type: 'chips', hint: 'Press Enter after each. The AI also understands similar words.' },
      { key: 'command', label: 'Command', type: 'text', hint: 'Optional. People type /' , prefix: '/' },
    ],
    gives: () => [['person.name', 'Their name', 'Venkatesh Batchu'], ['person.flat', 'Their flat', 'T7 1104'], ['person.role', 'Their role', 'Primary resident'], ['person.phone', 'Their phone', '+91 98•••• 2996'], ['message.text', 'What they wrote', 'my bathroom ceiling is leaking']] },
  form: { kind: 'start', icon: '📝', name: 'A WhatsApp form is sent', help: 'Someone fills in a WhatsApp form and taps Send.', start: true,
    fields: [{ key: 'form', label: 'Which form', type: 'select', options: () => DB.forms }],
    gives: () => [['person.name', 'Their name', 'Suresh'], ['form.answers', 'Every answer in the form', '4 answers']] },
  schedule: { kind: 'start', icon: '⏰', name: 'On a schedule', help: 'Runs by itself: every day, week or month.', start: true,
    fields: [
      { key: 'every', label: 'Every', type: 'seg', options: ['Day', 'Week', 'Month'] },
      { key: 'days', label: 'On', type: 'days', show: c => c.every === 'Week' },
      { key: 'time', label: 'At', type: 'time' },
      { key: 'working', label: 'Only on working days', type: 'switch' },
    ],
    gives: () => [['today.date', "Today's date", '15 Oct 2026']] },
  after: { kind: 'start', icon: '🔗', name: 'After another flow', help: 'Starts when another flow finishes.', start: true,
    fields: [{ key: 'flow', label: 'After this flow finishes', type: 'select', options: () => DB_FLOWS().map(f => f.name) }],
    gives: () => [['previous.result', 'What the other flow ended with', 'Saved']] },
  change: { kind: 'start', icon: '⚡', name: 'When a record changes', help: 'A ticket is raised, a status changes, a booking is due…', start: true,
    fields: [
      { key: 'record', label: 'Record', type: 'record' },
      { key: 'when', label: 'When', type: 'select', options: c => ['it is created', 'its status changes', 'it is given to someone', 'it is overdue', 'a field changes'] },
      { key: 'to', label: 'To', type: 'status', show: c => c.when === 'its status changes' },
    ],
    gives: c => recordVars(c.record || 'ticket', 'record') },
  button: { kind: 'start', icon: '🔘', name: 'A button on a record', help: 'A button on a ticket, booking or visitor, in chat or on the dashboard.', start: true,
    fields: [
      { key: 'record', label: 'On which record', type: 'record' },
      { key: 'label', label: 'Button text', type: 'text' },
      { key: 'where', label: 'Show the button', type: 'seg', options: ['In chat', 'On the dashboard', 'Both'] },
    ],
    gives: c => recordVars(c.record || 'ticket', 'record').concat([['person.name', 'Who tapped it', 'Anuja Sinkar']]) },

  // ----- talk -----
  ask: { kind: 'talk', icon: '❓', name: 'Ask a question', help: 'Asks and waits for the answer.',
    fields: [
      { key: 'text', label: 'Question', type: 'rich' },
      { key: 'answer', label: 'Expect', type: 'select', options: () => ['Words', 'A number', 'A date', 'A photo', 'Yes or no', 'One of these choices', 'A person', 'A flat'] },
      { key: 'choices', label: 'Choices', type: 'chips', show: c => c.answer === 'One of these choices' },
      { key: 'save', label: 'Save the answer as', type: 'text', hint: 'Later steps use this name.' },
      { key: 'optional', label: 'They may skip it', type: 'switch' },
    ],
    gives: c => [[`answer.${slug(c.save || 'answer')}`, c.save || 'The answer', c.answer === 'One of these choices' && (c.choices || [])[0] ? c.choices[0] : sampleFor(c.answer)]] },
  say: { kind: 'talk', icon: '💬', name: 'Send a message', help: 'Sends a message. Drag values in.',
    fields: [{ key: 'text', label: 'Message', type: 'rich' }, { key: 'buttons', label: 'Buttons under it', type: 'chips', hint: 'Optional, up to 3.' }],
    gives: () => [] },
  choices: { kind: 'talk', icon: '🔢', name: 'Offer choices', help: 'A list or buttons. Each choice can go its own way.',
    fields: [{ key: 'text', label: 'Message above the choices', type: 'rich' }, { key: 'options', label: 'Choices', type: 'chips', hint: 'Each choice gets its own way out on the canvas.' }],
    outs: c => (c.options && c.options.length ? c.options : ['Choice 1']),
    gives: () => [['choice', 'What they chose', 'Allow']] },
  sendform: { kind: 'talk', icon: '📋', name: 'Send a WhatsApp form', help: 'Opens a form inside WhatsApp.',
    fields: [{ key: 'form', label: 'Form', type: 'select', options: () => DB.forms }],
    gives: () => [['form.answers', 'The answers', '4 answers']] },
  template: { kind: 'talk', icon: '📨', name: 'Send an approved template', help: 'For people who have not written in 24 hours.',
    fields: [{ key: 'template', label: 'Template', type: 'select', options: () => DB.templates }, { key: 'to', label: 'To', type: 'who' }],
    gives: () => [] },

  // ----- records -----
  find: { kind: 'data', icon: '🔎', name: 'Find a record', help: 'Finds a ticket, booking or visitor.',
    fields: [
      { key: 'record', label: 'Record', type: 'record' },
      { key: 'by', label: 'Find it by', type: 'select', options: () => ['its number (from an answer)', 'the latest one of this person', 'a field value'] },
      { key: 'value', label: 'Number', type: 'value', show: c => (c.by || '').startsWith('its number') },
      { key: 'into', label: 'Call it', type: 'text', hint: 'Later steps use this name.' },
    ],
    outs: () => ['Found', 'Not found'],
    gives: c => recordVars(c.record || 'ticket', slug(c.into || recLabel(c.record || 'ticket'))) },
  create: { kind: 'data', icon: '💾', name: 'Save a new record', help: 'Creates a ticket, booking or visitor from the answers.',
    fields: [{ key: 'record', label: 'Record', type: 'record' }, { key: 'map', label: 'Fill in', type: 'map' }],
    gives: c => recordVars(c.record || 'ticket', 'new') },
  update: { kind: 'data', icon: '✏️', name: 'Change a record', help: 'Changes fields or the status.',
    fields: [{ key: 'record', label: 'Record', type: 'record' }, { key: 'status', label: 'New status', type: 'status' }, { key: 'map', label: 'Also change', type: 'map' }],
    gives: () => [] },
  list: { kind: 'data', icon: '📃', name: 'List records', help: 'Many records at once, for a report or a reminder.',
    fields: [{ key: 'record', label: 'Record', type: 'record' }, { key: 'filter', label: 'Which', type: 'select', options: () => ['Open ones', 'Overdue ones', "This person's", 'Created today', 'All'] }],
    gives: c => [['list.count', 'How many', '12'], ['list.lines', 'One line each', 'TK-26-0142 · Leak · High …']] },

  // ----- decide -----
  if: { kind: 'decide', icon: '🔀', name: 'Check something', help: 'Goes one way or the other.',
    fields: [{ key: 'value', label: 'If', type: 'value' }, { key: 'op', label: '', type: 'select', options: () => ['is', 'is not', 'is empty', 'is more than', 'is less than', 'contains'] }, { key: 'than', label: 'This', type: 'text', show: c => c.op !== 'is empty' }],
    outs: () => ['Yes', 'No'], gives: () => [] },
  approve: { kind: 'decide', icon: '✅', name: 'Ask for approval', help: 'Someone says yes or no before it goes on.',
    fields: [{ key: 'who', label: 'Who approves', type: 'who' }, { key: 'text', label: 'What they see', type: 'rich' }],
    outs: () => ['Approved', 'Rejected'], gives: () => [['approval.by', 'Who answered', 'Rohit J.'], ['approval.note', 'Their note', 'Fine, keep noise low']] },
  wait: { kind: 'decide', icon: '⏳', name: 'Wait', help: 'Waits for a time, then goes on.',
    fields: [{ key: 'for', label: 'Wait for', type: 'select', options: () => ['10 minutes', '1 hour', '1 day', 'until the record changes'] }], gives: () => [] },

  // ----- people -----
  tell: { kind: 'people', icon: '📣', name: 'Tell someone', help: 'Messages people by role or by their place on the record.',
    fields: [{ key: 'who', label: 'Tell', type: 'who' }, { key: 'text', label: 'Message', type: 'rich' }], gives: () => [] },
  assign: { kind: 'people', icon: '👤', name: 'Give it to someone', help: 'Uses "Who handles what", or a role, or a person.',
    fields: [{ key: 'record', label: 'Record', type: 'record' }, { key: 'how', label: 'Give it to', type: 'seg', options: ['Who handles what', 'A role', 'A person'] }],
    gives: () => [['handler.name', 'Who has it now', 'Anuja Sinkar']] },
  addperson: { kind: 'people', icon: '➕', name: 'Add someone to the record', help: 'A watcher, a backup, an approver…',
    fields: [{ key: 'record', label: 'Record', type: 'record' }, { key: 'as', label: 'As', type: 'peoplekind' }, { key: 'person', label: 'Person', type: 'value' }], gives: () => [] },

  // ----- AI -----
  ai: { kind: 'ai', icon: '✨', name: 'Ask AI', help: 'Sort, summarise or pull out details.',
    fields: [{ key: 'task', label: 'Task', type: 'select', options: () => ['Sort it into a kind', 'Summarise it', 'Pull out details', 'Write a polite reply'] }, { key: 'from', label: 'From', type: 'value' }, { key: 'into', label: 'Save as', type: 'text' }],
    gives: c => [[`ai.${slug(c.into || 'result')}`, c.into || 'AI result', 'Plumbing']] },

  // ----- building block (one node type, many blocks) -----
  block: { kind: 'block', icon: '🧩', name: 'Building block', help: '', fields: [{ key: 'block', label: 'Block', type: 'blockpick' }, { key: 'needs', label: 'It needs', type: 'needs' }],
    outs: c => { const b = blockById(c.block); return b && b.outs ? b.outs : null; },
    gives: c => { const b = blockById(c.block); return b ? b.gives.map(g => [g[0], g[1], g[2]]) : []; } },

  // ----- advanced -----
  webhook: { kind: 'adv', icon: '🌐', name: 'Call a web address', help: 'Sends data to another system.', superOnly: true,
    fields: [{ key: 'url', label: 'Address', type: 'text' }, { key: 'method', label: 'Method', type: 'seg', options: ['GET', 'POST'] }], gives: () => [['web.reply', 'Its answer', '{ ok: true }']] },
  sql: { kind: 'adv', icon: '🗄️', name: 'Run a database query', help: 'For super admins only.', superOnly: true,
    fields: [{ key: 'query', label: 'Query', type: 'code' }], gives: () => [['query.rows', 'Rows', '3 rows']] },

  // ----- block inner start / end -----
  gets: { kind: 'block', icon: '📥', name: 'Gets', help: 'What this block needs to start.', start: true, fields: [{ key: 'needs', label: 'It needs', type: 'needlist' }],
    gives: c => (c.needs || []).map(n => [`needs.${slug(n)}`, n, 'sample']) },
  gives: { kind: 'block', icon: '📤', name: 'Gives back', help: 'What it hands back to the flow.', fields: [{ key: 'gives', label: 'Gives back', type: 'chips' }], gives: () => [] },
  end: { kind: 'talk', icon: '🏁', name: 'Finish', help: 'Ends the flow, with an optional last message.', fields: [{ key: 'text', label: 'Last message (optional)', type: 'rich' }], gives: () => [] },
};

function slug(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'value'; }
function recLabel(r) { return (DB.records[r] || {}).label || r; }
function sampleFor(a) { return ({ 'A number': '40', 'A date': 'Sat 18 Oct', 'A photo': '1 photo', 'Yes or no': 'Yes', 'One of these choices': 'Plumbing', 'A person': 'Anuja Sinkar', 'A flat': 'T7 1104' })[a] || 'water leaking from the ceiling'; }
function recordVars(r, as) {
  const R = DB.records[r]; if (!R) return [];
  return R.fields.map(f => [`${as}.${f.key}`, `${R.label} ${f.label.toLowerCase()}`, f.sample || '…'])
    .concat([[`${as}.status`, `${R.label} status`, R.statuses[0]]])
    .concat(R.people.map(p => [`${as}.${p.key}`, `${R.label}: ${p.label.toLowerCase()}`, p.sample]));
}

// ---------------- building blocks (each belongs to a use case, or is shared) ----------------
DB.blocks = [
  { id: 'b_find_ticket', usecase: 'tickets', name: 'Find a ticket by its number', desc: 'Accepts any format (TK-26-142, 142, tk142). Stops politely if there is none.',
    needs: ['Ticket number'], gives: [['ticket.number', 'Ticket number', 'TK-26-0142'], ['ticket.title', 'Ticket title', 'Water leaking'], ['ticket.status', 'Ticket status', 'Reported'], ['ticket.handler', 'Ticket: handling it', 'Anuja Sinkar']], outs: ['Found', 'Not found'], version: 4,
    graph: { nodes: [{ id: 'g', type: 'gets', x: 60, y: 120, cfg: { needs: ['Ticket number'] } }, { id: 'f', type: 'find', x: 330, y: 120, cfg: { record: 'ticket', by: 'its number (from an answer)', value: '{needs.ticket_number}', into: 'ticket' } }, { id: 'o', type: 'gives', x: 610, y: 80, cfg: { gives: ['ticket'] } }, { id: 'n', type: 'say', x: 610, y: 230, cfg: { text: 'I could not find ticket {needs.ticket_number}. Please check the number.' } }], edges: [{ from: 'g', to: 'f' }, { from: 'f', out: 0, to: 'o' }, { from: 'f', out: 1, to: 'n' }] } },
  { id: 'b_pass_on', usecase: 'tickets', name: 'Pass a ticket on', desc: 'Gives the ticket to someone else and tells both people.', needs: ['Ticket', 'New person'], gives: [['handler.name', 'Who has it now', 'Chetan B.']], version: 2,
    graph: { nodes: [{ id: 'g', type: 'gets', x: 60, y: 120, cfg: { needs: ['Ticket', 'New person'] } }, { id: 'a', type: 'assign', x: 330, y: 120, cfg: { record: 'ticket', how: 'A person' } }, { id: 't', type: 'tell', x: 600, y: 120, cfg: { who: { kinds: ['handler'] }, text: 'Ticket {needs.ticket} is now with you.' } }, { id: 'o', type: 'gives', x: 870, y: 120, cfg: { gives: ['handler'] } }], edges: [{ from: 'g', to: 'a' }, { from: 'a', to: 't' }, { from: 't', to: 'o' }] } },
  { id: 'b_slot_free', usecase: 'bookings', name: 'Check a slot is free', desc: 'Says whether the facility is free for that time. Never allows two bookings to overlap.', needs: ['Facility', 'Date', 'From', 'Until'], gives: [['slot.free', 'Is it free', 'Yes'], ['slot.next_free', 'Next free time', '8:00 pm']], outs: ['Free', 'Taken'], version: 1,
    graph: { nodes: [{ id: 'g', type: 'gets', x: 60, y: 120, cfg: { needs: ['Facility', 'Date', 'From', 'Until'] } }, { id: 'l', type: 'list', x: 330, y: 120, cfg: { record: 'booking', filter: 'All' } }, { id: 'i', type: 'if', x: 600, y: 120, cfg: { value: '{list.count}', op: 'is', than: '0' } }, { id: 'o', type: 'gives', x: 880, y: 120, cfg: { gives: ['slot.free'] } }], edges: [{ from: 'g', to: 'l' }, { from: 'l', to: 'i' }, { from: 'i', out: 0, to: 'o' }] } },
  { id: 'b_gate_pass', usecase: 'visitors', name: 'Make a gate pass', desc: 'Makes a 4-digit pass the guard checks at the gate.', needs: ['Visitor'], gives: [['pass.code', 'Pass code', '4821']], version: 1,
    graph: { nodes: [{ id: 'g', type: 'gets', x: 60, y: 120, cfg: { needs: ['Visitor'] } }, { id: 'u', type: 'update', x: 330, y: 120, cfg: { record: 'visitor', status: 'Expected' } }, { id: 'o', type: 'gives', x: 600, y: 120, cfg: { gives: ['pass.code'] } }], edges: [{ from: 'g', to: 'u' }, { from: 'u', to: 'o' }] } },
  { id: 'b_flat_of', usecase: '', name: "Look up a person's flat", desc: 'Shared by every use case.', needs: ['Person'], gives: [['flat.number', 'Flat', 'T7 1104'], ['flat.members', 'Members', '3 people']], version: 3,
    graph: { nodes: [{ id: 'g', type: 'gets', x: 60, y: 120, cfg: { needs: ['Person'] } }, { id: 'o', type: 'gives', x: 340, y: 120, cfg: { gives: ['flat'] } }], edges: [{ from: 'g', to: 'o' }] } },
];
function blockById(id) { return DB.blocks.find(b => b.id === id); }

// ---------------- flows ----------------
const ALL = { everyone: true };
DB.flows = [
  { id: 'f_raise', usecase: 'tickets', name: 'Raise a ticket', on: true, access: { everyone: false, roles: ['Primary resident', 'Joint member', 'Other resident', 'Tenant', 'Committee member', 'Secretary', 'Chairman', 'Treasurer'], kinds: [] }, lastUsed: '12 min ago',
    graph: { nodes: [
      { id: 'n1', type: 'chat', x: 40, y: 160, cfg: { menu: { usecase: 'tickets', group: 'Raise' }, phrases: ['raise a complaint', 'something is broken', 'leak in my flat'], command: 'complaint' } },
      { id: 'n2', type: 'ai', x: 300, y: 160, cfg: { task: 'Sort it into a kind', from: '{message.text}', into: 'kind' } },
      { id: 'n3', type: 'ask', x: 560, y: 160, cfg: { text: 'Thanks {person.name}. Where exactly is the problem?', answer: 'Words', save: 'place' } },
      { id: 'n4', type: 'ask', x: 820, y: 160, cfg: { text: 'Can you send a photo? You can also skip.', answer: 'A photo', save: 'photo', optional: true } },
      { id: 'n5', type: 'create', x: 1080, y: 160, cfg: { record: 'ticket', map: [['title', '{message.text}'], ['kind', '{ai.kind}'], ['place', '{answer.place}'], ['photos', '{answer.photo}']] } },
      { id: 'n6', type: 'assign', x: 1340, y: 160, cfg: { record: 'ticket', how: 'Who handles what' } },
      { id: 'n7', type: 'tell', x: 1600, y: 70, cfg: { who: { kinds: ['handler', 'backup'] }, text: 'New ticket {new.number}: {new.title} at {answer.place}.' } },
      { id: 'n8', type: 'say', x: 1600, y: 260, cfg: { text: '✅ Ticket {new.number} is raised. {handler.name} will look at it.' } },
    ], edges: [{ from: 'n1', to: 'n2' }, { from: 'n2', to: 'n3' }, { from: 'n3', to: 'n4' }, { from: 'n4', to: 'n5' }, { from: 'n5', to: 'n6' }, { from: 'n6', to: 'n7' }, { from: 'n6', to: 'n8' }] } },
  { id: 'f_close', usecase: 'tickets', name: 'Close a ticket', on: true, access: { everyone: false, roles: ['Manager', 'Facility manager', 'Executive'], kinds: ['handler'] }, lastUsed: '2 h ago',
    graph: { nodes: [
      { id: 'a', type: 'button', x: 40, y: 140, cfg: { record: 'ticket', label: 'Close it', where: 'Both' } },
      { id: 'b', type: 'ask', x: 300, y: 140, cfg: { text: 'What was done to fix it?', answer: 'Words', save: 'note' } },
      { id: 'c', type: 'update', x: 560, y: 140, cfg: { record: 'ticket', status: 'Closed' } },
      { id: 'd', type: 'tell', x: 820, y: 140, cfg: { who: { kinds: ['raiser'] }, text: 'Your ticket {record.number} is closed: {answer.note}' } },
    ], edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }, { from: 'c', to: 'd' }] } },
  { id: 'f_daily', usecase: 'tickets', name: 'Morning open-tickets report', on: false, access: { everyone: false, roles: ['Secretary', 'Chairman'], kinds: [] }, lastUsed: 'never',
    graph: { nodes: [
      { id: 'a', type: 'schedule', x: 40, y: 140, cfg: { every: 'Day', time: '08:30', working: true } },
      { id: 'b', type: 'list', x: 300, y: 140, cfg: { record: 'ticket', filter: 'Open ones' } },
      { id: 'c', type: 'tell', x: 560, y: 140, cfg: { who: { roles: ['Secretary', 'Chairman'] }, text: 'Good morning. {list.count} tickets are open:\n{list.lines}' } },
    ], edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }] } },
  { id: 'f_book', usecase: 'bookings', name: 'Book a facility', on: true, access: { everyone: false, roles: ['Primary resident', 'Joint member', 'Tenant'], kinds: [] }, lastUsed: 'yesterday',
    graph: { nodes: [
      { id: 'a', type: 'chat', x: 40, y: 170, cfg: { menu: { usecase: 'bookings', group: 'Book' }, phrases: ['book the clubhouse', 'reserve party hall'], command: 'book' } },
      { id: 'b', type: 'ask', x: 300, y: 170, cfg: { text: 'Which facility?', answer: 'One of these choices', choices: ['Clubhouse', 'Party hall', 'Squash court', 'Swimming pool'], save: 'facility' } },
      { id: 'c', type: 'ask', x: 560, y: 170, cfg: { text: 'Which date, and from when until when?', answer: 'A date', save: 'when' } },
      { id: 'd', type: 'block', x: 820, y: 170, cfg: { block: 'b_slot_free', needs: { Facility: '{answer.facility}', Date: '{answer.when}' } } },
      { id: 'e', type: 'approve', x: 1080, y: 80, cfg: { who: { roles: ['Secretary'] }, text: '{person.name} ({person.flat}) wants the {answer.facility} on {answer.when}.' } },
      { id: 'f', type: 'say', x: 1080, y: 300, cfg: { text: 'Sorry, the {answer.facility} is taken then. Next free time: {slot.next_free}.' } },
      { id: 'g', type: 'create', x: 1340, y: 40, cfg: { record: 'booking', map: [['facility', '{answer.facility}'], ['date', '{answer.when}']] } },
      { id: 'h', type: 'say', x: 1600, y: 40, cfg: { text: '🎉 Booked: {answer.facility} on {answer.when}. Booking {new.number}.' } },
      { id: 'i', type: 'say', x: 1340, y: 200, cfg: { text: 'The committee could not approve this booking: {approval.note}' } },
    ], edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }, { from: 'c', to: 'd' }, { from: 'd', out: 0, to: 'e' }, { from: 'd', out: 1, to: 'f' }, { from: 'e', out: 0, to: 'g' }, { from: 'e', out: 1, to: 'i' }, { from: 'g', to: 'h' }] } },
  { id: 'f_preapprove', usecase: 'visitors', name: 'Pre-approve a visitor', on: true, access: { everyone: false, roles: ['Primary resident', 'Joint member', 'Other resident', 'Tenant'], kinds: [] }, lastUsed: '40 min ago',
    graph: { nodes: [
      { id: 'a', type: 'chat', x: 40, y: 140, cfg: { menu: { usecase: 'visitors', group: 'Pre-approve' }, phrases: ['guest coming', 'my friend is visiting'], command: 'visitor' } },
      { id: 'b', type: 'ask', x: 300, y: 140, cfg: { text: "What is your visitor's name?", answer: 'Words', save: 'visitor name' } },
      { id: 'c', type: 'ask', x: 560, y: 140, cfg: { text: 'When will they come?', answer: 'A date', save: 'expected' } },
      { id: 'd', type: 'create', x: 820, y: 140, cfg: { record: 'visitor', map: [['name', '{answer.visitor_name}'], ['expected', '{answer.expected}']] } },
      { id: 'e', type: 'block', x: 1080, y: 140, cfg: { block: 'b_gate_pass', needs: { Visitor: '{new.number}' } } },
      { id: 'f', type: 'say', x: 1340, y: 140, cfg: { text: 'Done. Share this pass with {answer.visitor_name}: *{pass.code}*' } },
    ], edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }, { from: 'c', to: 'd' }, { from: 'd', to: 'e' }, { from: 'e', to: 'f' }] } },
  { id: 'f_gate', usecase: 'visitors', name: 'Visitor at the gate', on: true, access: { everyone: false, roles: ['Guard'], kinds: [] }, lastUsed: '5 min ago',
    graph: { nodes: [
      { id: 'a', type: 'form', x: 40, y: 150, cfg: { form: 'Visitor entry form (guard)' } },
      { id: 'b', type: 'tell', x: 300, y: 150, cfg: { who: { kinds: ['host'] }, text: '{form.answers} is at the gate for you.' } },
      { id: 'c', type: 'choices', x: 560, y: 150, cfg: { text: 'Let them in?', options: ['Allow', 'Deny'] } },
      { id: 'd', type: 'update', x: 820, y: 60, cfg: { record: 'visitor', status: 'Inside' } },
      { id: 'e', type: 'update', x: 820, y: 260, cfg: { record: 'visitor', status: 'Turned away' } },
    ], edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }, { from: 'c', out: 0, to: 'd' }, { from: 'c', out: 1, to: 'e' }] } },
];
function DB_FLOWS() { return DB.flows; }

// ---------------- lists shown to admins (made-up records) ----------------
DB.items = {
  tickets: [
    ['TK-26-0142', 'Water leaking from the ceiling', 'T7 1104', 'High', 'Reported', 'Anuja Sinkar', 62],
    ['TK-26-0139', 'Lift door closes too fast', 'Tower 2 lift', 'Medium', 'Under review', 'Chetan B.', 35],
    ['TK-26-0131', 'Street light near gate 2 off', 'Gate 2', 'Low', 'Action taken', 'Anuja Sinkar', 104],
    ['TK-26-0128', 'Garbage not collected', 'T3', 'Medium', 'Reported', '—', 18],
  ],
  bookings: [
    ['BK-26-0031', 'Party hall', 'Sat 18 Oct, 6–10 pm', 'Rajeswari Batchu', 'Pending'],
    ['BK-26-0029', 'Squash court', 'Thu 16 Oct, 7–8 am', 'Farah Sheikh', 'Confirmed'],
  ],
  visitors: [
    ['VS-26-0207', 'Ramesh Kumar', 'T7 1104', 'Today 7:30 pm', 'Expected'],
    ['VS-26-0206', 'Swiggy delivery', 'T3 0402', 'Today 1:10 pm', 'Left'],
  ],
};
