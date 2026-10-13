# Making the dashboard calmer, clearer and fully editable

Study notes, 7 October 2026. Written in plain words. The picture of the idea is in
`docs/design/ux-proposal.html` (open it in a browser; click around; "Why this design?" explains each choice).

## 1. What was asked

- The dashboard feels confusing: too much on every screen, hard to find things.
- Someone who opens Flows should understand what a flow, a building block, a trigger and a step are.
- Every part should be editable and connected to the database, so the admin feels in control.
  Example: there are 6 roles today; the admin should be able to add one, such as "second owner".
- Flows: it should be easy to see what you can do with a step (open, test, add, delete, ask the assistant).

## 2. Where we stand today

Measured on the practice copy at 1440 x 900 (what is visible without scrolling):

| Screen | Clickable things | Words | What gets in the way |
|---|---|---|---|
| Home | 12 | 206 | 9 boxes at once: 4 alert cards, 6 numbers, a chart, 3 lists, a set-up card |
| Cases | 18 | 202 | 8 filter controls; 4 tabs, 3 of them are settings, not daily work |
| Kinds of complaint | 37 | 191 | 4 buttons on every row (+Sub, Edit, Hide, Delete) |
| People | 9 | 155 | 8 columns, 5 filters; tabs: People, Seats, "Special access (not active yet)", Roles |
| Roles | 52 | 204 | a grid of ticks; no way to add, rename or delete a role |
| Flows | 10 | 293 | 3 greyed tabs ("later"), cards with technical footers like "Report · /cases · not used yet" |

Root causes, in order of how much they hurt:

1. **The menu follows how we built it, not how an admin thinks.** Daily work (cases) and set-up
   (who gets cases, kinds, response times) share one screen and one set of tabs.
2. **Every screen shows everything.** Nothing is hidden until asked for.
3. **Words are ours, not theirs.** Seats, Special access, Who gets them, Kinds of complaint, Building block,
   Case button, v2, Tidy up, Legend. "Workflow" and "Flow" are both used for the same thing.
4. **Nothing teaches.** The first time someone meets "flow" or "trigger" nothing says what it is.
5. **Dead ends are shown.** Connections "Soon", Schedules / Runs / Templates "later", "not active yet".
6. **One big "New workflow / building block" button on every screen**, even where it makes no sense.
7. **Not everything can be changed** (see the table in section 5).

Good things to keep: the Settings screen (short menu on the left, each row = name + one line + control),
the step window, the Try it test, the assistant box on the canvas.

## 3. What n8n and UpScaleUp.io do well

n8n (studied twice, hands-on; nothing was changed):
- A very small menu: Overview, Personal, Shared, Chat; Templates, Help, Settings at the bottom.
- Every page = title + one line + ONE main button whose label follows the tab.
- The step picker groups steps and gives each a one-line plain description.
- Help menu: Quickstart video, Docs, Forum, Course, "Report a bug" with the version filled in.
- Locked features are shown as a calm box with one button, not as broken screens.

UpScaleUp.io (from your saved builder page, and the Home page; nothing was changed):
- Menu in labelled groups; secondary items open in a small fly-out instead of crowding the list.
- A global Create menu where each choice is a verb plus one line ("Campaign: Send a broadcast message").
- One nudge card with progress ("profile 31%: Complete profile / Remind me later") instead of many alerts.
- Empty states that give the next two steps. Error cards with a Retry button.
- Builder: steps in plain verbs ("Send A Message", "Ask A Question"), each with a "?" that explains it;
  big boxes with a visible delete; a floating bar Undo / Save Draft / Test / Publish; a dismissible tip
  ("Chatbot stuck? send start over"); a docs page that explains it in 5 numbered steps.
- Limit of this study: the account logged in had no plan, so a pricing wall covered every page and only
  the Home page could be read. No plan was clicked.

## 4. The rules behind the advice

- Fewer choices on screen decide faster (Hick's law, choice overload). Group them in chunks (Miller's law).
- Use words people already know (Jakob's law, "match the real world").
- Show things instead of making people remember them (recognition over recall).
- Hide the rare and advanced behind one click (progressive disclosure: novices make fewer mistakes,
  experts pay one click).
- Group the menu by what the person is doing, keep daily items on top and rare ones below.
- Say what is happening, prevent mistakes, and give a way out (visibility of status, error prevention,
  user control).

Sources: [Laws of UX](https://lawsofux.com/), [NN/g 10 usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/),
[NN/g progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/),
[SaaS navigation patterns](https://www.saasui.design/blog/saas-navigation-ux-patterns).

## 5. What I propose

### The menu: two groups

```
EVERY DAY                      SET UP
  Home                           Flows            what the assistant can do
  Cases        (19)              Assistant        what it says and how it answers
  Conversations                  Case rules   (!) who gets cases, kinds, response times
  People                         Roles & access   roles, seats, special access
                                 Settings         (the activity log moves inside as "History of changes")
```

- Daily screens hold only daily work. A link on each leads to its set-up ("How cases are handled",
  "Manage roles").
- A red dot on a Set-up item says something needs attention.
- Removed: Connections "Soon", the three "later" tabs, "(not active yet)".

### One page pattern

Title, ONE sentence, ONE main button that belongs to this screen (Add person, New role, New flow).
No global "New workflow" button.

### Screen by screen

- **Home**: "Needs you" (3 things, each with one button) + 4 numbers + one health line. The rest one click away.
- **Cases**: search, Open / Closed, one Filters button, chips for what is filtered; 4 columns.
- **People**: Add person; role chips with counts; 5 columns; the rest inside the person's panel.
- **Roles & access**: list of roles on the left; on the right the editor: a new role starts as a copy of an
  existing one; "What they can do" (the flows, in plain words); "What the assistant may look up for them";
  Approvals; the people who have it. Built-in roles are protected and say why. Delete says why it cannot.
- **Flows**: a sentence that says what a flow is; a 3-picture strip (starts when, steps, tells the person);
  "Learn the words"; cards without technical footers; building blocks keep their name, with a sentence
  that says you rarely need them; "New flow" gives three starts (describe it, example, blank).
- **Flow canvas**: a hint bar that teaches the three gestures once; a visible ⋯ on every step; the palette
  grouped by what steps do, each with a line and a "?"; "Technical" view tucked into ⋯ More.
- **Case rules**: the three case set-up tabs together; rules read as sentences; the warning has a fix button.

### One list of words (shown in "Help & words")

Flow, Trigger, Step, Building block, Role, Seat.

### Everything editable: today and proposed

| Thing | Today | Proposed |
|---|---|---|
| Roles | tick which flows a role may use | create from a copy, rename, delete (with guards), what it may look up, approver limit |
| People | change role / switch off | + Add person (name, email, role; Telegram links by email) |
| Cases | view only, by design (actions stay in flows) | later: case buttons in the case panel (needs a login first) |
| Case rules, kinds, response times | editable | same, moved to Case rules |
| Seats, special access | editable | same, moved to Roles & access |
| Flows, messages, AI instructions | editable | same |
| Case statuses, priorities, resident types, seat kinds | fixed by the database (CHECK rules) | later: a lookup table so they can be edited |
| Home cards | fixed per organisation | later: choose which cards show |

Facts the role editor must respect (found in the database dumps):
- Two role names are used by the database itself: `committee` and `member` (a trigger moves people between them
  when they take or leave a committee seat). They can change what they allow, but not their name, and cannot
  be deleted.
- A role can only be deleted when no one has it and no rule or special access uses it.
- "Second owner" as a flat relationship is a resident type (tenant, first owner, second owner, other), a fixed
  list in the database, not a role. Making that list editable is the "lookup table" item above.

### Build order

1. Menu, page pattern, removing dead items, words, glossary. (screens only, low risk)
2. Home, Cases, People simplified. (screens only)
3. Flows landing + "Building blocks" tab + new-flow dialog + canvas hints and palette help. (screens only)
4. Roles & access editor and Add person. (new endpoints that write to the database: with tests, guards and
   change-log entries, like the other editors)
5. Later: a login for the dashboard (still open), case buttons, editable lists, Home cards.

## 6. Things to know

- The dashboard has no login yet (decision deferred). Roles for admins only become real once there is one.
- `routing_db (2).sql` in Downloads holds the live database passwords in plain text. Rotate them, and delete the file.
