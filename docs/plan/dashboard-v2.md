# Dashboard v2: the plan

The look and the way it works come from the prototype the user approved: `docs/design/dashboard-v2-prototype.html`
(open it in a browser; it is a local file, not in git). It is built on the existing dashboard (same sign-in, organisation
lock, admin / super admin rules, router, search, dark mode), screen by screen. Nothing goes live until the user says deploy.

## Who sees what (decided 2026-10-15)

| Screen | Super admin | Admin |
|---|---|---|
| Home | yes | yes |
| Tickets: list, ticket page with its clock, assign (through the org's flow) | yes | yes |
| Tickets: Who handles what, Reminders | edit | read only |
| Tickets: Kinds, Rules in detail | edit | no |
| Conversations | yes | yes |
| People: add, import, give a role | yes | yes |
| Roles | edit | no |
| Chat bot: menu, WhatsApp forms, templates, messages, AI notes | yes | no |
| Build: flows, building blocks | yes | no |
| Settings | yes | no |

## Phases

| # | What | State |
|---|---|---|
| 1 | Time to fix in the database: `housing-0013_reminder_plans.sql` (no-limit kinds, clock, pause, reopen, plan tables) | done, tests pass (commit 37a8e4b) |
| 2 | The reminder job `app/services/reminder_plans.py`, its messages, the scheduler switch | done, tests pass (37a8e4b) |
| 3 | Dashboard calls for reminders, kinds' time to fix, a ticket's clock (`app/admin_panel/reminders.py`) | in progress |
| 4A | Menu by the prototype: Your work (Tickets, Conversations), Your team (People, Roles), Chat bot, Build, Settings; Cases called Tickets on screen; admin scope above | next |
| 4B | Tickets list with time bars; ticket page with the clock, the steps, the messages sent, the timeline | |
| 4C | Who handles what as one grid (kind, goes first to, backup, also told, time to fix) with Try it | |
| 4D | Reminders tab (plans, % steps, quiet hours, pause, examples) | |
| 4E | Home: set-up checklist, needs attention, time-to-fix card | |
| 4F | People with role, job and what they handle; Roles as ticks per use case | |
| 4G | Flows and Building blocks screens and the plain builder (When → Ask, Decide, Do, Tell, Use; Test; versions) | |
| 4H | WhatsApp forms (question builder) and Message templates (Meta template API) | |
| 4I | Chat menu by use case; more use cases (Bookings, Visitors) need a generic records layer | later |

## Going live

Live database step (needs the user to name it): backup, then `python -m tools.migrate --apply --allow-remote --backup-taken`
for housing-0013. The reminder plans stay off until `orgs.settings.reminders.enabled` is set to true on the Reminders screen.
