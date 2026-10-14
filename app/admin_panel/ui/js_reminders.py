JS = r"""
// ───────────────────────── Tickets → Reminders ─────────────────────────
// When the chat bot reminds, tells the backup, or hands a ticket over: as a share of each ticket's time to fix, so one plan
// works for a 2-hour lift and a 3-month repair alike (app/services/reminder_plans.py). A super admin changes it; an admin
// reads it. Nothing here names a kind, a role or a status: they all come from GET /reminders.
const REM_ONLY = { always: 'whatever happens', no_action: 'nobody has acted on it yet', not_started: 'it is still not started' };
const REM_ACTS = [
  [{ do: 'remind' }, '🔔', 'Remind whoever handles it'],
  [{ do: 'tell', to: 'backup' }, '👀', 'Tell the backup'],
  [{ do: 'reassign', to: 'backup' }, '➡️', 'Give it to the backup'],
  [{ do: 'tell', to: 'raiser' }, '🙋', 'Tell the person who raised it'],
  [{ do: 'tell', to: 'also' }, '📣', 'Tell the people kept informed'],
  [{ do: 'raise_priority' }, '⬆️', 'Make it more urgent'],
];
const REM_EXAMPLES = [['A 2-hour lift problem', 120], ['A 4-day electrical job', 5760], ['A 3-month repair', 129600], ['A suggestion with no time limit', null]];
const remKey = a => a.do + ':' + (a.to || a.role_id || a.user_id || '');
function remActWords(a, roles) {
  if (a.role_id) { const r = roles.find(x => x.id === a.role_id); return ['👥', 'Tell everyone in ' + (r ? roleLabel(r.name) : 'a role')]; }
  const known = REM_ACTS.find(([x]) => remKey(x) === remKey(a));
  return known ? [known[1], known[2]] : ['•', a.do];
}
function remDur(m) {
  if (m >= 43200 && m % 43200 === 0) return plural(m / 43200, 'month');
  if (m >= 1440) { const d = Math.floor(m / 1440), hr = Math.round((m % 1440) / 60); return plural(d, 'day') + (hr ? ' ' + hr + ' h' : ''); }
  if (m >= 60) { const hr = Math.floor(m / 60), mi = Math.round(m % 60); return hr + ' h' + (mi ? ' ' + mi + ' min' : ''); }
  return Math.max(1, Math.round(m)) + ' min';
}

async function renderReminders(root) {
  const mine = S.renderId;
  let d;
  try { d = await api.get('/reminders'); } catch (e) { root.append(errorBox(e)); return; }
  if (mine !== S.renderId) return;
  if (d.available === false) { root.append(notice('This organisation has no time-to-fix clock yet, so there are no reminder plans.', 'warn')); return; }
  const edit = isSuper();
  const box = h('div', { class: 'stack s16' });
  root.append(box);
  const def = () => d.plans.find(p => p.is_default) || d.plans[0];
  const again = async () => { try { d = await api.get('/reminders'); draw(); } catch (e) { toast(e.message, 'bad'); } };

  // ---- one plan: its steps, edited in place, saved together ----
  function planCard(plan) {
    const steps = plan.steps.map(s => ({ ...s, actions: (s.actions || []).map(a => ({ ...a })) }));
    let dirty = false;
    const list = h('div', { class: 'stack s8' });
    const saveRow = h('div', { class: 'row' });
    const mark = () => { dirty = true; paintSave(); };
    function paintSave() {
      fill(saveRow, dirty ? [h('span', { class: 'muted small grow' }, 'Not saved yet.'),
        h('button', { class: 'btn', type: 'button', onclick: () => { draw(); } }, 'Discard'),
        h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save plan')] : null);
    }
    async function save() {
      const body = steps.map((s, i) => ({ sort_order: i, at_percent: s.every_minutes ? null : Number(s.at_percent), every_minutes: s.every_minutes ? Number(s.every_minutes) : null, only_if: s.only_if || 'always', actions: s.actions }));
      try { await api.put('/reminders/plans/' + plan.id + '/steps', { steps: body }); toast('Saved. New reminders follow this plan from the next minute.', 'ok'); again(); }
      catch (e) { toast(e.message, 'bad'); }
    }
    function actionChips(s) {
      const chips = s.actions.map((a, j) => { const [ic, words] = remActWords(a, d.roles); return h('span', { class: 'chip remchip' }, ic + ' ' + words,
        edit ? h('button', { class: 'x', type: 'button', 'aria-label': 'Remove ' + words, onclick: () => { s.actions.splice(j, 1); mark(); paintSteps(); } }, '×') : null); });
      if (!edit) return h('span', { class: 'row' }, chips.length ? chips : h('span', { class: 'muted' }, 'nothing'));
      const have = new Set(s.actions.map(remKey));
      const offers = [...REM_ACTS.map(([a, ic, w]) => [a, ic + ' ' + w]), ...d.roles.map(r => [{ do: 'tell', role_id: r.id }, '👥 Tell everyone in ' + roleLabel(r.name)])].filter(([a]) => !have.has(remKey(a)))
        .filter(([a]) => !(s.every_minutes && a.do === 'reassign'));
      return h('span', { class: 'row' }, chips, offers.length ? h('button', { class: 'btn sm ghost', type: 'button', 'data-popkeep': '1', onclick: e => openPop(e.currentTarget, h('div', { class: 'stack s4', style: { padding: '6px' } },
        offers.map(([a, w]) => h('button', { class: 'mi', type: 'button', onclick: () => { closePop(); s.actions.push(a); mark(); paintSteps(); } }, w)))) }, '+ add') : null);
    }
    function stepRow(s, i) {
      const drop = edit ? h('button', { class: 'btn sm ghost', type: 'button', 'aria-label': 'Remove this step', onclick: () => { steps.splice(i, 1); mark(); paintSteps(); } }, '×') : null;
      if (s.every_minutes) {
        const every = edit ? sel([[1440, 'day'], [10080, 'week'], [20160, '2 weeks'], [43200, 'month']].map(([v, l]) => [String(v), l]), String(s.every_minutes), { 'aria-label': 'How often' }) : h('b', null, remDur(s.every_minutes));
        if (edit) every.addEventListener('change', () => { s.every_minutes = Number(every.value); mark(); });
        return h('div', { class: 'remstep' }, h('div', { class: 'row' }, h('b', null, '♾️ No time limit:'), 'every', every, 'while it is open', h('span', { class: 'grow' }), drop), h('div', { class: 'row' }, '→', actionChips(s)));
      }
      const at = edit ? h('input', { type: 'number', min: 1, max: 1000, value: String(s.at_percent), style: { width: '76px' }, 'aria-label': 'Share of the time to fix' }) : h('b', null, Number(s.at_percent) + '%');
      if (edit) at.addEventListener('change', () => { s.at_percent = Math.max(1, Math.min(1000, Number(at.value) || 1)); mark(); });
      const only = edit ? sel(Object.entries(REM_ONLY), s.only_if || 'always', { 'aria-label': 'Only if' }) : h('span', null, REM_ONLY[s.only_if || 'always']);
      if (edit) only.addEventListener('change', () => { s.only_if = only.value; mark(); });
      const p = Number(s.at_percent);
      return h('div', { class: 'remstep' + (p >= 100 ? ' late' : '') },
        h('div', { class: 'row' }, h('b', null, 'At'), at, edit ? '% of the time to fix' : 'of the time to fix', h('span', { class: 'muted small' }, p === 100 ? '(the moment it is due)' : p > 100 ? '(after it is overdue)' : ''), h('span', { class: 'grow' }), drop),
        h('div', { class: 'row' }, 'if', only, '→', actionChips(s)));
    }
    function paintSteps() {
      const timed = steps.filter(s => !s.every_minutes).sort((a, b) => Number(a.at_percent) - Number(b.at_percent));
      const repeats = steps.filter(s => s.every_minutes);
      fill(list, timed.length || repeats.length ? [...timed, ...repeats].map(s => stepRow(s, steps.indexOf(s))) : h('div', { class: 'muted' }, 'No steps: nobody is reminded.'),
        edit ? h('div', { class: 'row' },
          h('button', { class: 'btn sm', type: 'button', onclick: () => { steps.push({ at_percent: 50, only_if: 'always', actions: [{ do: 'remind' }] }); mark(); paintSteps(); } }, '+ Add a step'),
          !repeats.length ? h('button', { class: 'btn sm ghost', type: 'button', onclick: () => { steps.push({ every_minutes: 10080, only_if: 'always', actions: [{ do: 'remind' }] }); mark(); paintSteps(); } }, '+ A regular nudge for tickets with no time limit') : null) : null);
    }
    const kinds = plan.is_default ? 'Every kind without its own plan' : (plan.kinds || []).map(k => k.label).join(', ') || 'no kind yet';
    const head = h('div', { class: 'card-h' }, edit && !plan.is_default ? h('input', { type: 'text', value: plan.name, 'aria-label': 'Plan name', style: { fontWeight: 600, maxWidth: '240px' }, onchange: async e => { try { await api.patch('/reminders/plans/' + plan.id, { name: e.target.value.trim() }); toast('Renamed', 'ok'); } catch (x) { toast(x.message, 'bad'); } } }) : h('b', null, plan.name),
      badge('For: ' + kinds, plan.is_default ? 'brand' : ''), h('span', { class: 'sp' }),
      edit && !plan.is_default ? h('button', { class: 'btn sm ghost', type: 'button', onclick: async () => { if (!await confirmBox('Remove the plan “' + plan.name + '”? Its kinds go back to the standard plan.', { ok: 'Remove', danger: true })) return; try { await api.del('/reminders/plans/' + plan.id); toast('Removed', 'ok'); again(); } catch (x) { toast(x.message, 'bad'); } } }, 'Remove plan') : null);
    paintSteps(); paintSave();
    return h('div', { class: 'card' }, head, h('div', { class: 'card-b stack s8' }, list, saveRow));
  }

  // ---- the same plan on four very different tickets ----
  function examples() {
    const plan = def();
    const timed = plan ? plan.steps.filter(s => !s.every_minutes).sort((a, b) => Number(a.at_percent) - Number(b.at_percent)) : [];
    const rep = plan ? plan.steps.find(s => s.every_minutes) : null;
    const stepMark = (s, m) => {
      const p = Number(s.at_percent);
      const dot = h('span', { class: 'remexdot' + (p >= 100 ? ' late' : '') });
      const icons = s.actions.map(a => remActWords(a, d.roles)[0]).join(' ');
      const label = h('span', { class: 'remexlab' }, p + '% · ' + remDur(m * p / 100), h('br'), icons);
      return h('div', { class: 'remexstep', style: { left: p + '%' } }, dot, label);
    };
    const barFor = m => {
      if (m == null) return h('div', { class: 'remexbar none' }, h('span', null, rep ? '↻ a nudge every ' + remDur(rep.every_minutes) + ' while open' : 'no reminders'));
      return h('div', { class: 'remexbar' }, timed.filter(s => Number(s.at_percent) <= 100).map(s => stepMark(s, m)));
    };
    const rows = REM_EXAMPLES.map(([name, m]) => {
      const title = h('div', null, h('b', null, name), h('div', { class: 'muted small' }, m ? 'Time to fix ' + remDur(m) : 'Never overdue'));
      return h('div', { class: 'remex' }, title, barFor(m));
    });
    const head = h('div', { class: 'card-h' }, 'How it looks on real tickets', h('span', { class: 'muted small' }, 'The same plan; the steps are a share of each ticket’s own time'));
    return h('div', { class: 'card' }, head, h('div', { class: 'card-b stack' }, rows));
  }

  function draw() {
    const urg = d.by_urgency || [];
    const onSw = h('input', { type: 'checkbox', checked: !!d.enabled, disabled: !edit, 'aria-label': 'Reminder plans on' });
    onSw.addEventListener('change', async () => {
      if (onSw.checked && !await confirmBox('Switch the reminder plans on? From the next minute they remind, tell the backup and hand tickets over as set below, and the older reminders stop.', { ok: 'Switch on' })) { onSw.checked = false; return; }
      try { await api.put('/reminders/settings', { enabled: onSw.checked }); toast(onSw.checked ? 'Reminder plans are on' : 'Reminder plans are off; the older reminders run again', 'ok'); again(); }
      catch (e) { toast(e.message, 'bad'); onSw.checked = !onSw.checked; }
    });
    const switchCard = h('div', { class: 'card' }, h('div', { class: 'card-b row' },
      h('label', { class: 'switch' }, onSw, h('span')), h('div', { class: 'grow' }, h('b', null, d.enabled ? 'Reminder plans are on' : 'Reminder plans are off'),
        h('div', { class: 'muted small' }, d.enabled ? 'Open tickets are reminded, escalated and handed over as below.' : 'Nothing below runs yet. The older reminders keep going until you switch this on.')),
      !edit ? badge('Read only') : null));
    const urgCard = h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Time to fix by urgency', h('span', { class: 'muted small' }, 'For kinds set to “By urgency” in Who handles what')),
      h('div', { class: 'card-b remurg' }, urg.map(u => {
        if (!edit) return h('div', null, h('div', { class: 'muted small' }, pretty(u.priority)), h('b', null, remDur(u.tat_minutes)));
        const opts = TAT_CHOICES.filter(([v]) => v && v !== 'none').map(([v, l]) => [v, l]);
        if (!opts.some(o => Number(o[0]) === u.tat_minutes)) opts.unshift([String(u.tat_minutes), remDur(u.tat_minutes)]);
        const pick = sel(opts, String(u.tat_minutes), { 'aria-label': 'Time to fix for ' + pretty(u.priority) });
        pick.addEventListener('change', async () => { try { await api.put('/reminders/urgency', { [u.priority]: Number(pick.value) }); toast(pretty(u.priority) + ': ' + remDur(Number(pick.value)), 'ok'); again(); } catch (e) { toast(e.message, 'bad'); } });
        return h('label', { class: 'f' }, h('span', { class: 'muted small' }, pretty(u.priority)), pick);
      })));
    const q = d.quiet_hours || null;
    const from = h('input', { type: 'time', value: q ? q.from : '22:00', disabled: !edit || !q, 'aria-label': 'Quiet from' });
    const to = h('input', { type: 'time', value: q ? q.to : '07:00', disabled: !edit || !q, 'aria-label': 'Quiet until' });
    const qOn = h('input', { type: 'checkbox', checked: !!q, disabled: !edit, 'aria-label': 'Quiet hours' });
    const saveQuiet = async () => { try { await api.put('/reminders/settings', { quiet_hours: qOn.checked ? { from: from.value, to: to.value } : null }); toast('Saved', 'ok'); again(); } catch (e) { toast(e.message, 'bad'); } };
    [qOn, from, to].forEach(x => x.addEventListener('change', saveQuiet));
    const pauses = new Set(d.pause_statuses || []);
    const pauseBoxes = (d.statuses || []).filter(s => !(S.boot.enums.closed || []).includes(s)).map(s => {
      const cb = h('input', { type: 'checkbox', checked: pauses.has(s), disabled: !edit });
      cb.addEventListener('change', async () => { cb.checked ? pauses.add(s) : pauses.delete(s); try { await api.put('/reminders/settings', { pause_statuses: [...pauses] }); toast('Saved', 'ok'); } catch (e) { toast(e.message, 'bad'); cb.checked = !cb.checked; } });
      return h('label', { class: 'row small' }, cb, pretty(s));
    });
    const knowCard = h('div', { class: 'card' }, h('div', { class: 'card-h' }, 'Good to know'), h('div', { class: 'card-b stack s8' },
      h('div', { class: 'row' }, h('label', { class: 'switch' }, qOn, h('span')), h('b', null, 'Quiet hours'), from, '–', to, h('span', { class: 'muted small' }, 'Messages that fall in them wait until morning; a hand-over still happens.')),
      pauseBoxes.length ? h('div', null, h('b', null, 'Stop the clock while the status is'), h('div', { class: 'row' }, pauseBoxes), h('div', { class: 'muted small' }, 'For example while waiting for the resident. The due time moves on by the time it was stopped.')) : null));
    const used = new Set(d.plans.flatMap(p => (p.kinds || []).map(k => k.id)));
    const freeKinds = (d.kinds || []).filter(k => !k.parent_id && !used.has(k.id));
    const addPlan = edit ? h('button', { class: 'btn', type: 'button', onclick: () => {
      const name = h('input', { type: 'text', placeholder: 'For example Lifts: faster' });
      const pick = sel([['', 'Choose a kind…'], ...freeKinds.map(k => [k.id, k.label])], '');
      modal({ title: 'A plan for one kind', body: h('div', { class: 'stack' }, field('Kind of ticket', pick, 'Its sub-kinds use this plan too.'), field('Name', name)),
        actions: [{ label: 'Cancel' }, { label: 'Make the plan', primary: true, run: async () => {
          if (!pick.value) throw new Error('Choose a kind.');
          const label = (freeKinds.find(k => k.id === pick.value) || {}).label || 'Kind';
          await api.post('/reminders/plans', { name: name.value.trim() || label + ': own plan', kind_ids: [pick.value] });
          toast('Plan made. Add its steps and save.', 'ok'); again();
        } }] });
    }, disabled: !freeKinds.length }, '+ A plan for one kind') : null;
    fill(box, switchCard, examples(), h('div', { class: 'cols-2' }, urgCard, knowCard),
      h('div', { class: 'row between' }, h('h3', { style: { margin: 0 } }, 'Reminder plans'), addPlan),
      [...d.plans].sort((a, b) => (b.is_default ? 1 : 0) - (a.is_default ? 1 : 0)).map(planCard));
  }
  draw();
}
"""
