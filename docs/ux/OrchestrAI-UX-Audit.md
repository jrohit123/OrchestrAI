# OrchestrAI admin panel: UX audit (expert and heuristic evaluation)

Prepared 2026-10-08 on commit `16a1637` (the version live on Railway at that time). Nothing in the application was changed. Nothing ran against production. Everything below was seen or measured on this computer, on **made-up data** (a made-up housing society and a made-up jewellery shop; fake names, `example.test` e-mails).

**This is an expert and heuristic evaluation by one reviewer. It is not user research.** No real person used the panel. Section 13 is the script for the five-person test that would show what really happens.

---

## PASTE-BACK SUMMARY

**What was checked.** 22 screens at phone and desktop size, plus dark mode, 200% and 400% zoom, a keyboard pass, an accessibility checker (axe-core 4.10.2 on 12 screens at desktop size and 4 at phone size), Lighthouse 12.6.1 (two runs), load timing, a dropped network, and the 11 tasks from the brief done step by step. The brief's 14 use-case areas are written out as **146 numbered test cases** in section 5 (all results there).

**Scores (1 = poor, 5 = excellent)**

| Area | Score | In one line |
|---|---|---|
| Navigation | **4** | Two clear menu groups, breadcrumbs, page titles, search. Loses its labels in the flow editor; no skip link. |
| Clarity of language | **4** | Plain words and a glossary. A few technical words leak onto the canvas and into messages. |
| Workflow editing | **3** | Safe (undo, Unsaved/Discard, rehearsal, history) but heavy for a first-timer, and changing who approves needs JSON. |
| People management | **3** | Adding and finding people is easy. Recording a flat, and "moved out", are not. |
| Accessibility | **2** | Labels not tied to fields, dialogs and messages not announced, low contrast in the menu, small targets. |
| Mobile | **3** | Reflows well on most screens; tables are cut off, four screens overflow, the editor is cramped. |
| Consistency | **4** | One set of helpers, one main button per screen. Same fact edited in two places in a few spots. |

**The 10 worst problems**

1. **Who approves cannot be changed without editing JSON** (UX-034). The step "Ask for approval" only offers "Amount to check"; the Safeguards tab says "edit them as JSON under Advanced", and the tab is really called "JSON".
2. **Add person cannot record the flat** (UX-027). Name, e-mail, role only. No screen can add a flat to a person, so "new tenant in B-402" cannot be finished here.
3. **"Moved out" takes 6 clicks and is not called that** (UX-028). It is "Not residing" in a list inside the person window, next to a second "Active/Inactive" control.
4. **Form labels are not tied to their fields** (UX-001). axe: 22 form controls with no name on 5 screens, including every on/off switch on the Flows page.
5. **Dialogs and side windows are not real dialogs** (UX-002, UX-003). No dialog role, the "×" has no name, Tab walks out of the dialog, focus does not return.
6. **Saved, Deleted, Undo and error messages are silent to a screen reader** and disappear after 3.5 to 9 seconds (UX-004).
7. **Icon-only controls with no name** in the flow editor's menu rail, and switches inside clickable cards (UX-005, UX-006).
8. **Contrast and size**: the menu group labels are 2.6:1 (needs 4.5:1), avatar letters 3.3:1, the smallest text is 11 px, and every screen has 15 to 45 controls under 44 px (UX-007, UX-008, UX-010).
9. **Switching a flow off gives no warning and no message** (UX-035). It happens at once, silently. (Deleting an off flow does explain itself.)
10. **First load is heavy on a slow network**: a 411 KB script, not compressed here, 12.5 s to first content at 50 KB/s, and only the word "Loading…" meanwhile (UX-046). A wrong organisation address shows raw JSON (UX-045).

**15 quick wins (each under a day)**

1. Give `field()` an id and `for`; name the 22 unlabelled controls and the flow switches (UX-001, UX-006).
2. In `modal()` and the side window: `role="dialog"`, a label, "Close" on the ×, focus in and back (UX-002, UX-003).
3. Toast box `role="status"`; keep errors until closed; Undo for 15 s (UX-004).
4. `aria-label` on the editor's icon menu (UX-005).
5. Darken the menu group label and the avatar colours to 4.5:1 (UX-007).
6. Add a "Skip to main content" link (UX-009).
7. Raise the smallest text from 11 px to 12 px (UX-010).
8. Make scrollable tables focusable (UX-012).
9. Turn on gzip or brotli for `panel.js` and `panel.css` (about 363 KiB less; UX-046).
10. A friendly page for an unknown organisation address (UX-045).
11. A message with Undo when a flow is switched on or off, saying what changes (UX-035).
12. Show "Moved out" in the status list (label only) (UX-028).
13. Fix the Safeguards text ("under JSON") and hide the `approval_chain` tag (UX-023).
14. Show the editor hint once and not on phones (UX-038).
15. Plain subtitles on canvas steps instead of "entity records" and "to user id" (UX-021).

**Verdict: how a novice would cope.** A society secretary can use **Home, Cases and People** with little help: the words are plain, each screen has one main button, "Needs you" says what to do next, and nearly every slip can be undone. An admin sees only those three screens, plus a card that says "Ask a super admin". She would get stuck on four things: recording a flat, marking a resident as moved out, changing who approves, and anything that needs a screen reader or a keyboard. The set-up screens (Flows, rules, roles) are well written for a trained super admin; a first-timer would need a guide for the flow editor. No redesign is justified. Small, consistent fixes close almost every gap; the one exception is the **person window**, where a redesign of the top section is worth it (wireframe W1).

---

## 1. About this audit

### 1.1 What was done

| Step | How | Where the results are |
|---|---|---|
| Static | Read the front end (`app/admin_panel/ui/*.py`, 6,179 lines; the page and its two assets are served by `app/admin_panel/pages.py`) and the endpoints behind it | sections 3, 8, 12 |
| Dynamic | Ran the real panel on this computer against three throwaway databases built from the QA schema dumps and filled with made-up data (Sunrise Heights CHS, 28 people, 44 cases, 10 flows and 3 building blocks; Zari Jewellers, 3 people). Drove it with headless Edge over the DevTools protocol | sections 4 to 7 |
| Screens | 22 routes at 1280×800 and 360×640 (light); 12 key routes at 768×1024, 1920×1080, dark mode (1280 and 360), 200% zoom (640×400 at 2×) and 400% zoom (320×256 at 4×). About 170 screenshots in `docs/ux/screens/` | evidence paths below |
| Checks | axe-core 4.10.2 on 12 screens at 1280 and 4 at 360; Lighthouse 12.6.1 on Home (phone) and Cases (desktop); own script for target sizes, contrast, smallest text, overflow, names, tab order, load timing, layout shift, offline | section 7 |
| Tasks | The 11 tasks (a to k) done as a novice would, clicks counted | section 4 |
| Test cases | The 14 use-case areas written out as numbered cases with a result each | section 5 |

### 1.2 Labels used

* **VERIFIED**: seen in the running panel, or measured by a script. Evidence is a screenshot name (`docs/ux/screens/<name>.png`), a selector, or numbers from the run.
* **SUSPECTED**: read from the code (file and line), not seen running.
* **Severity** (Nielsen, 0 to 4): 0 not a problem, 1 cosmetic, 2 minor, 3 major, 4 catastrophe (none found).
* **Effort**: S under a day, M a few days, L a week or more.
* **Heuristics**: N1 visibility of status, N2 match with the real world, N3 user control and freedom, N4 consistency, N5 error prevention, N6 recognition over recall, N7 flexibility and efficiency, N8 minimal design, N9 help with errors, N10 help and documentation. WCAG 2.2 AA criteria are written as "WCAG 1.4.3" and so on.
* **Personas**: SEC = a 65-year-old society secretary, SHOP = a shop owner on a phone, KB = keyboard or screen-reader user, DEV = a developer, SUPER = an OrchestrAI super admin.

### 1.3 Differences from the brief, and limits

* **The "classic" admin pages no longer exist.** `app/routers/admin.py` is gone (removed with the classic dashboard); only the redesigned panel remains. So "classic against v2" duplication is not an issue today (test case 11.01).
* **Sign-in now exists.** The brief says authentication is deferred. It was built on 7 Oct 2026, so the first-visit screens (sign in, sign up, forgot password, no access, wrong address) are covered in section 5, group 1.
* **Admins and super admins see different panels.** A client admin sees Home, Cases and People only. Everything else (Flows, Chat bot, Case rules, Roles & access, Settings, Conversations) is for super admins. Most of this audit looks at the super admin view, because that is where the "workflow builder" is; the admin view is covered in tasks a, b, i and group 1.
* **The chat builder was tested with a pretend AI** (it always returns the same draft), so the quality of drafts is not judged, only the screens around it.
* **Made-up data causes two things that are not product faults**: the People list shows "Not yet" in "On Telegram" for everyone, and the Assign window says "No one found". Both are because no made-up person has a linked chat.
* **Not done**: no real users; no real screen reader (NVDA, VoiceOver) was run; no real phone (360 px was emulated in desktop Edge, with mouse clicks, so touch drag on the canvas is untested); Lighthouse was run twice only; the live server's compression and headers were **not** checked (production is off limits), so the compression finding is about the local server and needs one check on Railway; text resizing in the browser settings was not tried.
* **Automated accessibility checks find only part of the problems** (axe-core finds roughly a third to a half of WCAG issues). Passing them is not proof of accessibility.

---

## 2. What works well (keep these)

These are things a novice benefits from today. The fixes in this file should not disturb them.

| # | What | Evidence |
|---|---|---|
| W1 | **Plain product words, said once**: flow, step, trigger, building block, role, seat, chat bot, AI helper, with a "Help & words" window and a "How a flow works" strip. The word "assistant" appears nowhere in the page text (0 hits on all 22 screens); the web address of the Chat bot screen still reads `#/assistant` (UX-057). | VERIFIED: `D_x1_help.png`, text search of all 22 screens |
| W2 | **One main button per screen**, always top right (New flow, Add person, New role, New seat, New rule). | VERIFIED: every 1280 screenshot |
| W3 | **Home answers "what do I do today?" in about 5 seconds**: "Needs you" lists 3 things with a button each, then four numbers, a 14-day chart, and "Is the chat bot working?". | VERIFIED: `home_1280x800_light.png` |
| W4 | **Cases list shows the whole story on one line**: number, title, priority dot, kind, place, who raised it, status, who has it, due or "7 h late" in red, and an Assign button where nobody has it. | VERIFIED: `cases_1280x800_light.png` |
| W5 | **Undo instead of "Are you sure?"**: deleting a step shows "Deleted “Save a new record”. Undo" and the step count goes 3 → 2 → 3 on Undo. The flow shows an "Unsaved" tag with Discard and Save changes, and the browser's leave-page warning is set. | VERIFIED: steps 3, 2, 3; `F`-pass `unsaved_guard`; `B_f2_after_delete.png` |
| W6 | **Draft, try, activate**: New flow → three starts (Describe it is first and marked "Easiest"), then a draft card, then "Create it and open the editor". In the editor, **Try it** rehearses with "Try it as" a chosen person; nothing is saved or sent. | VERIFIED: `B_d1_new_flow.png`, `D_d2_drafted.png`, `D_try1.png` |
| W7 | **Reorder without dragging**: the step window has Move up, Move down, Duplicate, Park (switch the step off) and Delete. | VERIFIED: `D_e1_step_window.png` |
| W8 | **Seat changes say what else happens**: "The earlier holder is kept in the history, not deleted. This is a committee seat: the system also switches the person's role when they take or leave it." | VERIFIED: `D_c2_change_holder.png` |
| W9 | **Response times warn about unrealistic values**: setting Low to 5 minutes (faster than Urgent's 120) shows "Check these: Low gets less time than a more urgent priority…" plus a message; each box shows "≈ 2 h". | VERIFIED: `D_resp1.png` |
| W10 | **Duplicate people are caught in plain words**: "Aarav Shah is already here with that email." | VERIFIED: `F_duplicate.png` |
| W11 | **The case window explains the routing decision** ("What the case rules say: Rule … would send it to …"), and Messages shows "How it looks to the person" beside the text. | VERIFIED: `case_drawer_1280x800_light.png`, `chatbot_messages_1280x800_light.png` |
| W12 | **Admins get a way out of their limits**: a sidebar card "Need a person added, or something changed? … Ask a super admin". | VERIFIED: `D_meena_dash.png` |
| W13 | **Back and Escape work with windows**: the case and person windows live in the address (`?case=…`), so Back closes them; Escape closes dialogs and windows. | VERIFIED: pass F (`drawer_open_after_back = false`) |
| W14 | **A dropped network is handled**: "Cannot reach the server. Check your connection and try again." with a Try again button. | VERIFIED: `offline_cases_1280x800.png` |
| W15 | **Safe by construction**: no `innerHTML` anywhere in the panel's script (names and messages are shown as text), and no outside hosts are loaded (no CDN, no web fonts). | VERIFIED: `grep` over `ui/js_*.py` (0 uses) |
| W16 | **Canvas boxes are keyboard-reachable** (`tabindex=0`, `role=button`, labelled) and the editor has an `N` shortcut to add a step. | SUSPECTED: `js_canvas.py:83-104, 147-163` (tab order of boxes not walked) |

---

## 3. Screen inventory

Routes are the address after the organisation name. Code is where the screen is built. Screenshots are in `docs/ux/screens/`.

| # | Screen and route | Code | What it is for | Primary action | Other actions | Main parts | Screenshot |
|---|---|---|---|---|---|---|---|
| 1 | **Sign in** `/admin` (and `/admin/<org>` when signed out) | `ui/js_auth.py` | Get into the dashboard | Sign in | Forgot password?, Sign up, show password, Light/dark | Two-pane page: product pitch, form | `signed_out_admin_1280x800_light` |
| 2 | **Sign up** | `ui/js_auth.py` | First-time account for people a super admin invited | Send me a code | Back to sign in | Same page, e-mail field, then code and password | `D_signup` |
| 3 | **Forgot password** | `ui/js_auth.py` | New password through a 6-digit code | Send me a code | Back to sign in | Same page | `D_forgot` |
| 4 | **No access** | `ui/js_auth.py` | Signed in, but not for this organisation | none (lists organisations she can open) | Sign out | Message and list | `D_noaccess` |
| 5 | **Organisations** (admins) / **Overview, Organisations, Dashboard access, Sign-in log** (super admins) `/admin` | `ui/js_super.py` | Choose an organisation; super admins also manage who can sign in | Open dashboard | Send the email again, search the log, switch access on or off | Cards or tables | `super_orgs_*`, `D_meena_landing`, `D_sam_landing` |
| 6 | **Home** `#/overview` | `ui/js_home.py:41` | What needs me today | See them | Refresh, Getting set up | "Needs you" list, 4 number tiles, 14-day chart, bot health | `home_*` |
| 7 | **Cases** `#/cases` | `ui/js_overview_cases.py:130` | Find a case and see who has it | Assign (on a row) | Search, All/Open/Closed, Filters, Sort, How cases are handled | Table (cut off on a phone) | `cases_*` |
| 8 | **Case window** `#/cases?case=<id>` | `ui/js_overview_cases.py` | One case in full | Assign | Open the people on the case | Details, "What the case rules say", People on this case, What was reported, timeline | `case_drawer_*` |
| 9 | **Conversations** `#/conversations` | `ui/js_rest.py:120` | What people asked the chat bot | Open a conversation | Filter by person, text, dates | List, transcript window | `conversations_*`, `h2_*` |
| 10 | **People** `#/people` | `ui/js_people.py:315` | Everyone who can use the chat bot | Add person | Search, role chips, Filters, Manage roles | Table | `people_*` |
| 11 | **Person window** `#/people?person=<id>` | `ui/js_people.py` | One person in full | Save role / Save home | Give dashboard access, Give access, View chats, Manage seats | 10 stacked sections | `person_drawer_*`, `D_b1_person_clean` |
| 12 | **Flows** `#/workflows` | `ui/js_studio.py:397` | The things the chat bot can do | New flow | Search, Cards/Map, Flows/Building blocks, On/Off, Delete (when off) | Cards | `flows_*` |
| 13 | **New flow** (dialog) | `ui/js_studio.py` | Start a flow | Draft it | Copy one you have, Start blank, a building block, a case button | Three choice cards, text box | `B_d1_new_flow`, `D_d2_drafted` |
| 14 | **Flow editor** `#/workflows?w=<id>` | `ui/js_canvas.py`, `js_canvas_panels.py`, `js_stepwin.py`, `js_studio.py` | Build or change a flow | Save changes | Add a step, Try it, history, undo, Tidy up, Simple/Detailed, AI helper, step window, trigger window | Canvas of boxes, side windows | `flow_editor_*`, `D_e1_step_window`, `E_trigger_window`, `D_g1_palette` |
| 15 | **Chat bot → Messages** `#/assistant` | `ui/js_assistant.py:287` | Edit what the chat bot says by itself | Save | Group list, history, preview | 3 columns | `chatbot_messages_*` |
| 16 | **Chat bot → AI notes** `#/assistant/instructions` | `ui/js_assistant.py` | Notes the AI reads | Save | Clear notes, History, See everything the AI reads, Advanced | One text box | `chatbot_ainotes_*` |
| 17 | **Case rules → Who gets them** `#/rules` | `ui/js_routing.py:154` | Which person or seat gets which kind of case | New rule | Try it (who would get a case like this?), Edit, Delete, On/Off | Rule cards | `rules_who_*` |
| 18 | **Case rules → Kinds of complaint** `#/rules/categories` | `ui/js_routing.py` | The kinds of complaint | New kind | Edit, hide | Table | `rules_kinds_*` |
| 19 | **Case rules → Response times** `#/rules/times` | `ui/js_routing.py` | How long each priority gets | Save response times | none | Table of numbers | `rules_times_*` |
| 20 | **Roles & access → Roles** `#/access` | `ui/js_people.py:319`, `ui/js_roles.py` | What each role may do | New role | Rename, switch flows on or off per role | List and editor | `access_roles_*` |
| 21 | **Roles & access → Seats** `#/access/seats` | `ui/js_people.py` | Named jobs and who holds them | New seat | Change holder, Edit, history | Cards | `access_seats_*`, `D_c2_change_holder` |
| 22 | **Roles & access → Special access** `#/access/special` | `ui/js_people.py` | Temporary extra permission for one person | Give access | Revoke | Table | `access_special_*` |
| 23 | **Settings** `#/settings` | `ui/js_settings.py:105` | Organisation, time, chat sessions, photos, old records, this browser, support | Save | Upload logo | Side list and cards | `settings_*` |
| 24 | **Settings → History of changes** `#/settings/history` | `ui/js_settings.py` | Who changed what in the dashboard | none | Filter | List | `settings_history_*` |
| 25 | **Everywhere**: Search or jump to… (Ctrl K), Help & words, account and Sign out, Collapse menu, Light/dark | `ui/js_boot.py:161-189` | Move around, get help, leave | none | none | Menu, pop-ups | `D_x1_help`, `D_x2_search` |
| 26 | **Wrong organisation address** `/admin/<nothing>` | `pages.py:50-51` | none | none | none | Raw JSON text | `D_404` |

Screens 5 (Dashboard access, Sign-in log) were audited when they were built and are not part of the screenshots here.

---

## 4. Task walkthroughs (a to k)

The "Clicks" column was **counted in the running panel** (VERIFIED) from the sidebar. "Time budget" is an **ESTIMATE** for a first-time user (not measured); a person who needs more than this has probably stopped. "Result": **Pass** = can be done and is clear, **Hard** = can be done but is easy to get wrong, **Cannot** = cannot be finished in the panel.

| Task | Path | Clicks | Time budget | Where they would stop or err | Result |
|---|---|---|---|---|---|
| **a** Add a new tenant who joined flat B-402 | People → Add person → type name → type e-mail → choose Tenant → Add person | 3 clicks, 2 typed fields, 1 choice | 90 s | The form has **no place for the flat** (no wing, flat or home type). A person's "Home" section only exists when a home was already recorded; no screen creates one. | **Cannot** (UX-027). Screenshots `B_a1_add_person`, `B_a2_add_empty` |
| **b** Mark a resident as moved out | People → search (click, type) → the row → scroll to **Home** → status list → "Not residing" → Save home | 6 clicks and a scroll | 3 min | No "Moved out" anywhere. Two status controls: "Active / Inactive" under Account and "Active / Suspended / Inactive / Not residing" under Home, with the note "Changing the status also updates whether the person is active." People pick "Inactive" and the home stays "Active". | **Hard** (UX-028). `D_b1_person_clean` |
| **c** Replace the treasurer | Roles & access → Seats → Change holder (Treasurer) → pick the new holder → Save holder | 5 to 6 | 2 min | "Seats" is a new word (the glossary explains it). Super admin only; a client admin has to ask. The dialog is clear about the role switch. | **Pass** (super admin). `D_c2_change_holder` |
| **d** Create a flow by chat that reads a PDF and needs approval | Flows → New flow → (Describe it is already chosen) → type → Draft it → Create it and open the editor | 4 clicks and typing | 5 to 10 min | No way to give a sample PDF (the dialog has only a text box). The step list has no "read a PDF" step (only "Make a PDF"). The approval levels need JSON afterwards (task e). Judging the draft needs knowing what each step does. Tested with a pretend AI. | **Cannot** as described (UX-036); the first four clicks work. `D_d2_drafted` |
| **e** Change who approves, and add a second level | Flows → the flow → double-click "Starts when…" → Safeguards → read the note → JSON → edit Safeguards → Apply → Save changes | 8 clicks and JSON | 10 min or never | "Ask for approval" only offers "Amount to check". The Safeguards tab shows the sentence "Needs approval from Committee member then Admin when amount is at least 10000" with a tag `approval_chain`, then says "edit them as JSON under “Advanced”". The tab is called **JSON**, not Advanced. | **Cannot** for a novice (UX-034). `E_trigger_window`, `E2_safeguards`, `E2_json` |
| **f** Delete a step and undo it | Flows → the flow → ··· on the step → Delete → Undo | 5 | 30 s | Nothing. The toast stays 9 seconds; the top-left undo arrow also works. | **Pass** (steps 3 → 2 → 3). `B_f1_step_menu`, `B_f2_after_delete` |
| **g** Reuse an existing flow inside a new one | Flows → New flow → Start blank → Add a step → Building blocks → choose | 6 to 7 (the palette part was run; Start blank was not) | 2 min | "Building blocks" is the last group in a long list (Triggers 3, Actions 20, Building blocks 3). The term must be learnt. | **Pass** with scrolling (UX-040). `D_g1_palette` |
| **h** Find what a user said yesterday and open the whole chat | Conversations → click search and type (or set From) → click the row | 3 plus typing | 1 min | The person filter has no accessible name; the dates are the browser's own `dd-mm-yyyy` controls. | **Pass**. `B_h1_search`, `B_h2_transcript` |
| **i** Understand why one complaint is not closed | Cases → search or scroll → click the row | 3 | 1 min | The window shows status, who has it, "Was due", the case rules and a timeline at the bottom, but no one-line "why it is open". | **Pass** |
| **j** Change a reminder time | Case rules → Response times → edit "Remind after" → Save response times | 4 | 1 min | Super admin only. Nothing to reset to the standard values. | **Pass**. `rules_times_*`, `D_resp1` |
| **k** Turn a flow off safely | Flows → the switch on the card | 2 | 20 s | It switches **at once**: no confirmation, no message, no statement of what changes (people can no longer use `/visitor`). The card then shows "Off" and a Delete link. A building block that live flows use is refused with a clear message (server). | **Hard**: quick, but not "safe" (UX-035). `D_k1_after_switch` |

**Clicks to common tasks from the sidebar** (target: 3 or fewer). Within target: h (3), i (3), a (3 to the form). Over target but with plain steps: c (5 to 6), f (5), j (4), g (6 to 7). Over target and unclear: b (6), e (8 plus JSON).

---

## 5. Use-case catalogue and test cases (groups 1 to 14)

The brief's 14 use-case areas, written as numbered test cases. Every case says what to do, what should happen, and what was found.

**Result words**

| Result | Meaning |
|---|---|
| `PASS` | Done in the running panel (or measured); behaves as a novice needs. |
| `FAIL` | Done in the running panel (or measured); it does not. A finding is linked. |
| `PARTIAL` | Works in part. The finding says which part. |
| `NOT RUN` | Designed, not tried yet. Where the code says something, it is noted. |

**Coverage by group**

| Group | Cases | Tried | PASS | FAIL | PARTIAL | NOT RUN |
|---|---|---|---|---|---|---|
| 1. First load | 15 | 13 | 9 | 3 | 1 | 2 |
| 2. Shell and navigation | 15 | 15 | 8 | 2 | 5 | 0 |
| 3. Dashboard (Home) | 7 | 7 | 4 | 0 | 3 | 0 |
| 4. Flows list | 11 | 8 | 5 | 2 | 1 | 3 |
| 5. Flow editor | 20 | 16 | 9 | 2 | 5 | 4 |
| 6. Chat builder (the AI helper) | 8 | 5 | 4 | 1 | 0 | 3 |
| 7. People, roles and seats | 13 | 11 | 5 | 4 | 2 | 2 |
| 8. Activity, chats and audit | 7 | 7 | 4 | 1 | 2 | 0 |
| 9. Settings and forms | 8 | 8 | 4 | 2 | 2 | 0 |
| 10. Language and terminology | 6 | 6 | 3 | 0 | 3 | 0 |
| 11. Redundancy | 6 | 6 | 2 | 3 | 1 | 0 |
| 12. Accessibility | 14 | 13 | 3 | 6 | 4 | 1 |
| 13. Resilience of the interface | 9 | 6 | 5 | 1 | 0 | 3 |
| 14. Code health from the front-end side | 7 | 7 | 3 | 2 | 2 | 0 |
| **All** | **146** | **128** | **68** | **29** | **31** | **18** |

Of 146 cases, 128 were tried in the running panel or measured: 68 pass, 29 fail, 31 work in part. 18 were not tried (mostly things that need a real phone, a screen reader, a real AI, or a second person); each says what the code suggests.


### 1. First load
*What does a visitor see, where are they, what is the first action? Also: tenant choice, loading, API down, empty tenant, session timeout.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 1.01 | Open `/admin` signed out | A sign-in page: e-mail, password, sign up, forgot | PASS | `signed_out_admin_1280x800_light` |
| 1.02 | Open `/admin/<organisation>` signed out | The sign-in page, no data shown | PASS | `signed_out_org_1280x800_light` |
| 1.03 | Sign in with a wrong password | A plain message that says what to do next | PASS | "Wrong email or password. First time here? Choose Sign up." `D_wrongpw` |
| 1.04 | Open Sign up | Says who may sign up and what happens | PASS | "Only people a super admin has added can sign up…" `D_signup` |
| 1.05 | Open Forgot password | Says a code is sent and a new password is chosen | PASS | `D_forgot` |
| 1.06 | Signed in, open an organisation that is not hers | Says so, and offers the ones she can open | PASS | `D_noaccess` |
| 1.07 | Open an organisation address that does not exist | A friendly page with a way back | FAIL | raw JSON `{"detail":"Unknown org 'nosuchplace'"}` (UX-045) `D_404` |
| 1.08 | An admin with one organisation signs in | Goes straight to her dashboard | PARTIAL | lands on a one-card list first, one extra click (UX-048) `D_meena_landing` |
| 1.09 | Watch the loading state | A skeleton or progress | FAIL | only the word "Loading…" (UX-046) |
| 1.10 | Load Home on a slow network (400 ms delay, 50 KB/s) | Content in 5 seconds or less | FAIL | 12.5 s; `panel.js` alone took 10 s (UX-046) |
| 1.11 | Drop the network after the page is open, then move to Cases | A message and a retry button | PASS | "Cannot reach the server. Check your connection and try again." `offline_cases_1280x800` |
| 1.12 | Drop the network before the page starts | A message and a retry button | NOT RUN | code shows a message without a retry button (`js_boot.py:195, 201`, UX-047) |
| 1.13 | Open a small organisation with no cases (the shop) | Menu and Home adapt, no empty case screens | PASS | `jewellery_home_1280x800_light` |
| 1.14 | Let the session end while the page is open | Back to sign-in on the same screen, with a message | NOT RUN | code: `showSignIn(message)` keeps the screen (`js_auth.py`) |
| 1.15 | Is the first action obvious? | One main button | PASS | "Sign in" is the only filled button |

### 2. Shell and navigation
*Names, order, grouping, jargon, icon-only items, active state, depth, mobile, titles, breadcrumbs, search, help, "where am I".*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 2.01 | Read the page title of each screen | Screen name and organisation | PASS | "Home · Sunrise Heights CHS" |
| 2.02 | Look at the active menu item | Clearly marked | PASS | filled row in every screenshot |
| 2.03 | Look at the breadcrumb | Group, section, tab | PASS | "Set up / Case rules / Response times" |
| 2.04 | Read the two menu groups | Names a novice understands | PASS | "Every day" and "Set up" |
| 2.05 | Check the order against how often things are used | Most used first | PASS | Home, Cases, Conversations, People first |
| 2.06 | Read every menu and tab name for jargon | None | PARTIAL | "Case rules", "Seats", "Special access" need the glossary (UX-018) |
| 2.07 | Find the icon-only items and read their names | Every one has a name | FAIL | the editor's menu rail has 12 unnamed controls (UX-005) |
| 2.08 | Press Ctrl K and type | Finds screens, then people and cases | PARTIAL | screens listed (`D_x2_search`); people and cases not typed |
| 2.09 | Where is the organisation's name? | Always visible | PASS | top of the menu and in the page title |
| 2.10 | Phone width: open the menu | A menu button that opens and closes the menu | PARTIAL | the menu button is there at 360 px (`home_360x640_light`); not clicked |
| 2.11 | Press Tab once on a new page | A "skip to main content" link | FAIL | first stop is "Search or jump to"; 15 stops before the content on Home (UX-009) |
| 2.12 | Find help from any page | One obvious place | PASS | "Help & words" in the menu foot |
| 2.13 | In the editor, how do I know where I am? | Breadcrumb and title | PASS | "Set up / Flows / Approve a society expense" |
| 2.14 | Count levels in Settings | Three or fewer | PARTIAL | Settings, then the Settings tab, then a 7-item side list (UX-020) |
| 2.15 | Compare "Conversations" and "Chat bot" | Clearly different | PARTIAL | both about the chat bot (UX-018) |

### 3. Dashboard (Home)
*What questions does it answer in 5 seconds? Definitions, drill-down, zero states, density, overlap.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 3.01 | Look at Home for 5 seconds | I know what to do first | PASS | "Needs you: 12 cases have no one handling them" `home_1280x800_light` |
| 3.02 | Click a number or a "See them" | Opens the matching list | PASS | buttons on each line |
| 3.03 | Read a number's name | Plain, defined | PARTIAL | "Past target time" has no one-line definition (response times decide it) |
| 3.04 | A small organisation with nothing to show | A calm empty Home | PASS | `jewellery_home_*` |
| 3.05 | Count the blocks | Seven or fewer | PASS | four blocks plus the checklist pill |
| 3.06 | Does it repeat another screen? | Little | PARTIAL | "Is the chat bot working?" repeats Conversations (UX-051) |
| 3.07 | The "Getting set up · 4 of 5" pill | Says what it is | PARTIAL | looks like a status, is a checklist (UX-019) |

### 4. Flows list
*Finding one, status, creating, duplicating, deleting (impact), dependencies, naming.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 4.01 | Find a flow | Search and plain cards | PASS | `flows_1280x800_light` |
| 4.02 | Read a flow's status | On or Off in words | PASS | "On" / "Off" beside the switch |
| 4.03 | Start a new flow | The choice between chat and manual is clear | PASS | three cards, "Easiest" on the first (`B_d1_new_flow`) |
| 4.04 | Copy an existing flow | Offered | PASS | "Copy one you have" |
| 4.05 | Delete a flow | Impact explained | PARTIAL | only when off; text says "Deleting takes it out of this list for good. A copy is kept in the history." The title is the generic "Are you sure?" `F_delete_dialog` |
| 4.06 | Switch a flow off | The effect is explained, with Undo | FAIL | switches at once, no message (UX-035) `D_k1_after_switch` |
| 4.07 | Switch off a building block that live flows use | Refused with the names | NOT RUN | server returns 409 with the names (`workflows.py`) |
| 4.08 | See what uses a block | "Used by" is shown | NOT RUN | code shows "Used by: … Change it and they all change." in the editor (`js_canvas.py:95`) |
| 4.09 | Read the card's small print | Plain | PASS | "2 steps · /complaint · used 8.7 h ago" |
| 4.10 | Open the Flows page with a flow whose name is very long | Name does not break the page | NOT RUN | in the editor the header cuts the name and the breadcrumb shows it in full (`F_long_flow_1280`) |
| 4.11 | Flow cards: keyboard and screen reader | Card, switch and link are separate, named | FAIL | switch inside a clickable card, no name (UX-006) |

### 5. Flow editor
*Create, build, change, delete steps; add-step discovery; reorder; undo; validation; conditions; reuse; try it; activate; history; conflict; unsaved warning; 30+ steps; zoom; touch; JSON.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 5.01 | Find "add a step" | Obvious | PASS | dashed "Add a step" box, bottom bar, `N` key, palette (`D_g1_palette`) |
| 5.02 | Read the step type names | Plain sentences | PASS | "Find a record", "Stop if it already exists", "Ask for approval" |
| 5.03 | Move a step up or down without dragging | Buttons | PASS | Move up, Move down in the step window (`D_e1_step_window`) |
| 5.04 | Undo a delete | One click | PASS | toast Undo, steps 3, 2, 3; also the top-left arrow |
| 5.05 | Redo | Available | NOT RUN | |
| 5.06 | Make a change | Clear what is saved and what is not | PASS | "Unsaved" tag with Discard and Save changes; "Saved" when clean (`B_f2_after_delete`) |
| 5.07 | Cause a problem | A specific message, near the step, saying how to fix it | PARTIAL | specific and linked, but a banner above the canvas, and it quotes `'$user.user_id'` (UX-022, UX-039) |
| 5.08 | Add a condition ("only if") | No code | NOT RUN | an "Only if" tab exists in the step window |
| 5.09 | Reuse a shared step | Easy to find | PASS | "Building blocks" group (UX-040 for its place in the list) |
| 5.10 | Try a flow before it goes live | A rehearsal | PASS | "Try it as" a chosen person; "nothing is saved and nobody is messaged" (`D_try1`) |
| 5.11 | See older versions | A history | PARTIAL | history icon and a versions list with Restore (code); not opened |
| 5.12 | Two people save the same flow | A clear message | NOT RUN | code: "Someone else saved this" with Keep editing and Reload their version (`js_studio.py:143`) |
| 5.13 | Leave the page with unsaved changes | A warning | PASS | `onbeforeunload` set, tag shown (pass F) |
| 5.14 | Open a flow with 35 steps | Usable | PARTIAL | opened and drawn within 2.4 s, 1,699 DOM nodes; shown at 54% zoom, text about 6 px (estimate); Tidy up and fit exist (UX-041) `F_long_flow_1280` |
| 5.15 | Zoom and move around | Controls | PASS | zoom −/+, fit, Tidy up in the bottom bar |
| 5.16 | Use the editor on a phone | Possible | PARTIAL | opens, zooms to 60%, two banners fill 40% of the screen (UX-038); drag not tried |
| 5.17 | See technical detail | Behind a tab, plain by default | PARTIAL | step window: "Technical" tab (good); Safeguards and JSON tabs show raw JSON (UX-023) |
| 5.18 | Change who approves | Plain form | FAIL | JSON only (UX-034) |
| 5.19 | Read the canvas subtitles | Plain | FAIL | "entity records", "to user id" (UX-021) |
| 5.20 | Rename a step or the flow | Easy | NOT RUN | a "Rename this step" button and a name field exist |

### 6. Chat builder (the AI helper)
*How to start, examples, readable replies, review and apply, long waits and failures, history, chat versus manual edits.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 6.01 | Find how to start | Obvious | PASS | "Describe it" first and marked "Easiest" |
| 6.02 | Look for example prompts | Shown | PASS | example in the box; the editor's helper says Try: "When a case is closed, also message the person who raised it." |
| 6.03 | Read a draft | Plain | PASS | "Drafted: Add a note to a case" with the steps listed (pretend AI) `D_d2_drafted` |
| 6.04 | Apply or discard a draft | Both possible | PASS | "Create it and open the editor" and "Draft it again" |
| 6.05 | A long wait, a failure, a cancel | Progress, a message, a way to stop | NOT RUN | pretend AI answers at once |
| 6.06 | Earlier chat messages | Kept | NOT RUN | |
| 6.07 | Give it a sample PDF | Possible | FAIL | no upload in the dialog (UX-036) |
| 6.08 | Chat edits against manual edits | The two agree | NOT RUN | code matches steps by id (`proposalIds` in `js_studio.py`) |

### 7. People, roles and seats
*Adding a person, status, seats and their side effects, bulk add, search, special access, destructive actions, what a person can do.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 7.01 | Open Add person | Few, clear fields | PASS | Name, Email, Role (`B_a1_add_person`) |
| 7.02 | Type a phone number badly (a WhatsApp organisation) | A format hint | NOT RUN | code: "Write the number with its country code, like +91 98765 43210." |
| 7.03 | Add someone who is already there | Caught, in plain words | PASS | "Aarav Shah is already here with that email." `F_duplicate` |
| 7.04 | Add a tenant with a flat | Possible | FAIL | no flat field, no screen to add a home (UX-027) |
| 7.05 | Mark someone as moved out | Easy, in the user's words | PARTIAL | 6 clicks, "Not residing" (UX-028) |
| 7.06 | Change a seat holder | The role effect is disclosed | PASS | `D_c2_change_holder` |
| 7.07 | See who held a seat before | History kept | PASS | "The earlier holder is kept in the history" |
| 7.08 | Add many people at once | Paste or import | FAIL | not offered (UX-031) |
| 7.09 | Search and filter | Name, e-mail, flat; role chips | PASS | `people_1280x800_light` |
| 7.10 | See what one person can do now | One place | PARTIAL | role, "What can this role do?", seats, special access, spread over the window (UX-029) |
| 7.11 | Give someone special access | Clear | NOT RUN | |
| 7.12 | Read the two "access" buttons | Different meanings are clear | FAIL | "Give dashboard access" and "Give access" in one window (UX-030) |
| 7.13 | Pick "No role" for a person | Warned | FAIL | allowed with no warning (UX-033) |

### 8. Activity, chats and audit
*Finding an entry, opening the full conversation, filters, time formats, redundant sections, personal data.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 8.01 | Find what someone said | Search | PASS | "Search what was said…" `B_h1_search` |
| 8.02 | Open the whole chat | One click | PASS | transcript window "Conversation" with the chat bot's answers labelled `B_h2_transcript` |
| 8.03 | Filter by person and dates | Possible | PASS | person list and From / To |
| 8.04 | Read the time | Clear and local | PARTIAL | "8 Oct 2026, 2:55 am"; the time zone is stated only in Settings |
| 8.05 | Spot a failed chat | Marked | PASS | "Something failed" badge |
| 8.06 | Count the "history" screens | One or two | FAIL | four (UX-051) |
| 8.07 | Is personal data shown more than needed? | Little | PARTIAL | phones are hidden (••••1234, `common.py:316`); full names, e-mails and message text are shown to every admin of the organisation |

### 9. Settings and forms
*Grouping, defaults, units, unrealistic values, reset, help text, labels, error placement.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 9.01 | Read the Settings groups | Sensible | PASS | Organisation, Time & language, Chat sessions, Photos, Keeping old records, This browser, For support |
| 9.02 | Check units | Stated | PASS | "Target (minutes)" with "≈ 2 h" under each box (`rules_times_1280x800_light`) |
| 9.03 | Make Low faster than Urgent | Warned | PASS | notice and message (`D_resp1`) |
| 9.04 | Look for "reset to the standard" | Available | FAIL | none (UX-043) |
| 9.05 | Read help text | Plain | PASS | each setting has a sentence |
| 9.06 | Are labels tied to fields? | Yes | FAIL | UX-001 |
| 9.07 | Submit an empty form | The error is next to the field | PARTIAL | "Write the person's name." shows at the dialog foot, field not marked (UX-013) |
| 9.08 | Upload a logo | Styled control | PARTIAL | the browser's own "Choose File" (UX-044) |

### 10. Language and terminology
*Every jargon term with a plain replacement; consistent names; verbs; capitals; formats.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 10.01 | Scan all screens for jargon | None | PARTIAL | about 8 terms (section 9): "entity records", "user id", `approval_chain`, "Specificity", "Park", "Safeguards", "Seat" |
| 10.02 | Same thing, same word | Yes | PARTIAL | "no one handling them" / "Not assigned yet" / "Not assigned"; "Handled by" / "Who has it" / "Handling it" (UX-025) |
| 10.03 | Button verbs | Specific | PASS | Add person, Save role, Save home, Save holder, Draft it |
| 10.04 | Capitalisation | One style | PASS | sentence case |
| 10.05 | Dates, times, numbers, money | One style, local | PASS | "8 Oct 2026", "2:55 am", minutes with "≈ h"; lakh style not tested |
| 10.06 | The word "assistant" | Not used | PARTIAL | not on screen, but the Chat bot screen's address is `#/assistant` (UX-057) |

### 11. Redundancy
*Duplicate screens, repeated forms, one action in many places, dead sections, inconsistent patterns.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 11.01 | Classic and new panel side by side | One only | PASS | the classic pages are gone (`app/routers/admin.py` does not exist) |
| 11.02 | Who may use a flow | Edited in one place | FAIL | Roles & access and the flow's trigger window (UX-049) |
| 11.03 | A response time | One source, shown | FAIL | priority table, kind of complaint, and rule (UX-050) |
| 11.04 | History of what happened | One place | FAIL | UX-051 |
| 11.05 | Help | A few clear places | PARTIAL | five surfaces (UX-052) |
| 11.06 | A dead or empty section | None | PASS | none seen (sections hide when a database cannot use them) |

### 12. Accessibility
*Contrast, focus, order, labels, errors announced, hover-only, motion, reflow, text size, colour-only, icon names.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 12.01 | Run axe-core on 12 screens | No violations | FAIL | 8 rules at desktop size (9 with the phone view), 3 of them critical (section 7) |
| 12.02 | Run Lighthouse | Accessibility 90 or more | PASS | Home on a phone 100; Cases on a desktop 96 (colour contrast fails there) |
| 12.03 | Keyboard only through a screen | Everything reachable | PARTIAL | focus is visible on every stop tried; no skip link; dialogs let focus out (UX-002, UX-009) |
| 12.04 | Contrast of all text | 4.5:1 | FAIL | menu group labels 2.6:1, avatar letters 3.3:1 (UX-007) |
| 12.05 | Visible focus | On every control | PASS | 0 stops without an indicator on the four screens walked; 1 in the editor (the flow name box) |
| 12.06 | Labels and names | Every control | FAIL | UX-001, UX-005, UX-006 |
| 12.07 | Errors announced | Yes | FAIL | UX-004, UX-013 |
| 12.08 | Hover-only features | None needed | PARTIAL | tips are extra; the "More for this step" button has a name |
| 12.09 | Reduced motion | Respected | PARTIAL | one rule in `css.py` and one in `css_login.py`; none in `css_redesign.py` (UX-014) |
| 12.10 | Zoom to 200% | No sideways scroll | PASS | none on 12 screens |
| 12.11 | Zoom to 400% (320 px wide) | No sideways scroll | FAIL | Response times 47 px, Seats 29, Flows 6, editor 46 (UX-011) |
| 12.12 | Browser text size larger | Layout holds | NOT RUN | |
| 12.13 | Meaning by colour only | Never | PARTIAL | status badges carry words; the Home chart's "new" and "closed" bars differ by colour with a legend (UX-015) |
| 12.14 | Touch targets of 44 px | Yes | FAIL | every screen has controls under 44 px; some under 24 (UX-008) |

### 13. Resilience of the interface
*Slow network, failed request, double-click on save, back button, refresh mid-edit, two tabs, long names, empty and huge lists.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 13.01 | Slow network | Usable | FAIL | UX-046 |
| 13.02 | A failed request | Message and "Try again" | PASS | `offline_cases_1280x800` |
| 13.03 | Click Save twice | One save | NOT RUN | code disables the button while it runs (`js_core.py:204-207`) |
| 13.04 | Press Back after opening a case | The window closes | PASS | pass F |
| 13.05 | Refresh in the middle of an edit | A warning | PASS | `onbeforeunload` set (the browser draws its own prompt) |
| 13.06 | Two tabs, same flow | A clear message | NOT RUN | 409 handling exists (see 5.12) |
| 13.07 | A very long name | Does not break the layout | PASS | a person with a 70-letter name wraps over four lines at 360 px (`F_long_person_360`); the flow name is cut in the header and shown in full in the breadcrumb |
| 13.08 | An empty list | A calm message | PASS | "Holds no seat right now", "None. They can do what their role allows." |
| 13.09 | A list of thousands | Paging, still fast | NOT RUN | pager exists in the code |

### 14. Code health from the front-end side
*Components, duplication, consistency, escaping, what a security policy would break, a path without a rewrite.*

| ID | What to do | Expected | Result | Evidence |
|---|---|---|---|---|
| 14.01 | Count `innerHTML` in the script | None | PASS | 0 |
| 14.02 | Load anything from outside | Nothing | PASS | no CDN, no web fonts; only the SVG namespace string |
| 14.03 | Shared building blocks | Reused | PASS | `field`, `modal`, `toast`, `table`, `badge`, `empty` used on every screen |
| 14.04 | One type scale | A few sizes | FAIL | 14 different font sizes from 10 to 28 px (UX-055) |
| 14.05 | Security headers on the page | A content policy and frame protection | FAIL | none sent by the local server (UX-054) |
| 14.06 | Would a strict content policy break it? | Little | PARTIAL | two string `style:` values in the Home chart (`js_home.py:13-14`, UX-056); no inline script |
| 14.07 | Where the code lives | Real files | PARTIAL | HTML, CSS and JS are Python strings, 6,179 lines (UX-053) |

---

## 6. Findings register

57 findings. The same table is in `docs/ux/findings.csv`. "VERIFIED" means seen or measured in the running panel; "SUSPECTED" means read from the code. Screenshot names are files in `docs/ux/screens/`.

By severity: **9 major (3)**, **22 minor (2)**, **26 cosmetic (1)**, none at 4. By evidence: **53 VERIFIED**, **4 SUSPECTED**.

| ID | Screen | Heuristic | Sev | Persona | Evidence | Fix | Effort |
|---|---|---|---|---|---|---|---|
| UX-001 | All forms, sign-in | N4, WCAG 1.3.1, 3.3.2, 4.1.2 | 3 | KB | VERIFIED: axe "label" 22 controls on 5 screens at 1280 px (Flows 9, Response times 8, Settings 2, Conversations 2, editor 1); the two sign-in boxes are not tied to their labels; `js_core.py:138` builds the label with no `for` | `field()` gives the control an id and the label a `for`; give switch inputs an `aria-label` | S |
| UX-002 | Dialogs (Add person, New flow, confirm) | N4, WCAG 4.1.2, 2.4.3 | 3 | KB | VERIFIED: the dialog has no role, no aria-modal, no label; the × has no name; Tab leaves the dialog after 5 stops; focus goes to the page body on close (pass F `F_duplicate`); `js_core.py:215-224` | One dialog helper: `role="dialog"`, `aria-labelledby`, "Close" on the ×, keep Tab inside, give focus back | M |
| UX-003 | Case and person windows | WCAG 4.1.2, 2.4.3 | 3 | KB | VERIFIED: no role or label; focus stays on the page after opening; Tab goes to the page behind; `js_core.py:247-258` | Same helper, move focus in on open | M |
| UX-004 | Messages (Saved, Deleted, Undo, errors) | N1, WCAG 4.1.3 | 3 | KB, SEC | VERIFIED: the message and its box have no role or aria-live; Undo vanishes after 9 s, errors after 7 s, others after 3.5 s; `js_core.py:181-190` | `role="status"` on the box; errors stay until closed; Undo for 15 s | S |
| UX-005 | Flow editor menu (icon rail) | WCAG 2.4.4, 4.1.2 | 3 | KB | VERIFIED: axe link-name 9 and button-name 4; 12 controls with no name in the rail; the text is hidden by CSS in rail mode | `aria-label` on rail links and buttons (or hide the text visually, not with display none) | S |
| UX-006 | Flows cards | WCAG 4.1.2 | 3 | KB | VERIFIED: axe nested-interactive 3 and aria-allowed-role 9 (an article with role button holds the switch); the switch input has no name | Card = heading and link; switch labelled "Switch off File a complaint" | S |
| UX-007 | All screens (menu, avatars, chips) | WCAG 1.4.3 | 2 | SEC, SHOP | VERIFIED: menu group labels 2.6:1 (11 px capitals); avatar letters 3.3 to 3.5:1; the "Open 33" chip 4.33:1; axe color-contrast 26 nodes on 11 screens; Lighthouse fails contrast on Cases (desktop) | Darker label colour and avatar palette (4.5:1) | S |
| UX-008 | All screens | WCAG 2.5.8, 44 px guideline | 2 | SHOP, SEC | VERIFIED: every screen has 15 to 45 controls under 44 px (typical button 27 to 37 px high); under 24 px: breadcrumb links 21 px, "Sign up" 45×18, "Forgot password?" 102×20, "More for this step" 20×20, count links on Kinds of complaint 64×19 (12 of them) | Minimum 44 px height on touch widths; padding on links | S to M |
| UX-009 | Every page | WCAG 2.4.1 | 2 | KB | VERIFIED (Home): the first Tab stop is "Search or jump to"; 15 stops in the menu before the content; no skip link | A "Skip to main content" link | S |
| UX-010 | All screens | WCAG 1.4.4 (practice) | 1 | SEC | VERIFIED: the smallest text is 11 px on all screens (menu group labels, chips, hints); 15 rules at 11 px in `css.py` | 12 px minimum | S |
| UX-011 | Response times, Seats, Flows, editor, History | WCAG 1.4.10 | 2 | SHOP | VERIFIED: at 400% zoom (320 px wide) Response times is 47 px wider than the screen, editor 46, Seats 29, Flows 6; at 360 px: History 19, Kinds of complaint 11, Response times 7, editor 6 | Let tables wrap or scroll inside a labelled box; `min-width: 0` | S to M |
| UX-012 | People (and other tables) on a phone | WCAG 2.1.1 | 2 | KB | VERIFIED: axe scrollable-region-focusable on People at 360 px; the Role column is cut off `people_360x640_light` | `tabindex="0"` and a label on the table wrapper, or stack rows as cards | S |
| UX-013 | Dialog forms | N9, WCAG 3.3.1 | 2 | KB, SEC | VERIFIED: "Write the person's name." shows at the foot of the dialog; the field is not marked invalid; nothing announces it `B_a2_add_empty`; `js_core.py:205-209` | Show the message under the field with `aria-describedby`; mark `aria-invalid` | S |
| UX-014 | Animations | WCAG 2.3.3 | 1 | KB | SUSPECTED: a reduced-motion rule appears once in `css.py` and once in `css_login.py`, not in `css_redesign.py` | Check every animation honours it | S |
| UX-015 | Home chart | WCAG 1.4.1 | 1 | SEC | SUSPECTED: "new" and "closed" bars differ by colour with a legend, and show no values | Add a pattern or value labels | S |
| UX-016 | Flow editor, sign-in | WCAG 1.3.1 | 1 | KB | VERIFIED: axe page-has-heading-one on the editor; the only h1 on the sign-in page is the product pitch, "Welcome back" is an h2 | One h1 that names the page | S |
| UX-017 | Flow editor | N6 | 2 | SEC | VERIFIED: the menu turns into unlabelled icons while editing, so only the breadcrumb names the screen; two ways back (the "‹" by the name, and "All organisations") `flow_editor_1280x800_light` | Tooltip labels on the rail; keep one back control | S |
| UX-018 | Menu | N2 | 1 | SEC | VERIFIED: "Conversations" (history of chats) and "Chat bot" (what it says) sit next to each other; "Case rules" and "Roles & access" both set who does what | "Chat history" and "What the chat bot says" | S |
| UX-019 | Home | N6, N10 | 1 | SEC | VERIFIED: "Getting set up · 4 of 5" looks like a status; it is a checklist that opens on click `B_x2_setup` | "Set-up checklist: 4 of 5 done" | S |
| UX-020 | Settings | N8 | 1 | SEC | VERIFIED: three levels: Settings, the "Settings" tab, then a 7-item side list `settings_1280x800_light` | Fold the tab bar into the side list | S |
| UX-021 | Flow editor canvas | N2 | 2 | SEC | VERIFIED: step subtitles read "entity records" and "to user id" `flow_editor_1280x800_light` | Friendly names ("Expense records", "to the person who asked") | S |
| UX-022 | Flow editor, problem banner | N9 | 2 | SEC | VERIFIED: "'Send to' must be a phone number. Pick the person's phone, not '$user.user_id'." (my made-up flow held that value; the wording is the product's) `B_f1_step_menu` | "Choose who gets the message from the list." | S |
| UX-023 | Trigger window, Safeguards | N2, N4 | 2 | SUPER | VERIFIED: a raw tag `approval_chain`; the text says "edit them as JSON under “Advanced”" but the tab is named "JSON" `E2_safeguards`; `js_studio.py:310-312` | Plain tag ("Approval"); name the tab the same | S |
| UX-024 | Case rules, Who gets them | N2 | 1 | SUPER | VERIFIED: each rule shows "Specificity 10" with no explanation; "(seat)" after names `rules_who_1280x800_light`; `js_routing.py:75` | "Priority of this rule" with a tip, or drop it (the order is already said above the list) | S |
| UX-025 | Home, Cases, case window | N4 | 1 | SEC | VERIFIED: one state, three phrases ("no one handling them", "Not assigned yet", "Not assigned"); "Handled by", "Who has it" and "Handling it" for the same person | One phrase each ("Nobody has it yet", "Who has it") | S |
| UX-026 | Admin sidebar card | N2 | 2 | SEC | VERIFIED: "…are looked after by a super admin. [Ask a super admin]" `D_meena_dash`; a client may not know who that is | "Ask OrchestrAI support" (or the name the client knows) | S |
| UX-027 | People, Add person | N7 (task a) | 3 | SEC | VERIFIED: the form has Name, Email, Role only `B_a1_add_person`; the server takes the same (`people.py:358-363`); no code inserts a home (no `INSERT INTO residents` in `people.py`); the Home section appears only for an existing home | Optional Wing, Flat, Type (housing organisations) | M |
| UX-028 | Person window | N2, N5 (task b) | 3 | SEC | VERIFIED: 6 clicks; the status list reads "Active, Suspended, Inactive, Not residing" under Home; a second "Active / Inactive" under Account; note "Changing the status also updates whether the person is active." `D_b1_person_clean` | A top action "Moved out" with a date and the effect in words; label "Not residing" as "Moved out" | M (label S) |
| UX-029 | Person window | N8 | 2 | SEC | VERIFIED: 10 stacked sections (Account, Dashboard, Messaging, Added, Chats, Home, Seats, Special access, Handling now, Raised by them) | Show the 3 common jobs first; fold the rest | M |
| UX-030 | Person window | N2, N4 | 2 | SEC | VERIFIED: "Give dashboard access" and "Give access" in one window mean different things | "Let them sign in to this dashboard" and "Give temporary access to a flow" | S |
| UX-031 | People | N7 | 2 | SEC | VERIFIED: no bulk add or import on the screen | Paste a list or upload a sheet | L |
| UX-032 | People list | N10 | 1 | SEC | VERIFIED: the columns "On Telegram: Not yet" and "Dashboard: —" are not explained | Header tips ("linked to the chat bot yet?") | S |
| UX-033 | Person window | N5 | 1 | SEC | VERIFIED: the Role list offers "No role" without a warning | Warn that the person can then do nothing | S |
| UX-034 | Flow editor (approvals) | N7, "no JSON for common jobs" (task e) | 3 | SEC, SUPER | VERIFIED: the "Ask for approval" step shows only "Amount to check" `D_e1_step_window`; the approvers appear as a sentence in Safeguards; changing them means editing JSON `E2_json`; `js_studio.py:310-312` | A small form in Safeguards: levels (role, up to amount) | M |
| UX-035 | Flows (switch) | N1, N5 (task k) | 2 | SEC | VERIFIED: the switch changes at once, with no message, and nothing says what changes `D_k1_after_switch` | A message: "Switched off. People can no longer use /visitor. Undo." | S |
| UX-036 | New flow, step list | N7 (task d) | 2 | SEC, SUPER | VERIFIED: no upload in the "Describe it" dialog `B_d1_new_flow`; the step list has no "read a PDF" step (only "Make a PDF"); the data model keeps `pdf_sample_analysis` for drafts | A sample upload, or say what is possible | M |
| UX-037 | Flow editor | N1 | 1 | SEC | VERIFIED: the clean "Saved" button looks like a disabled primary button `flow_editor_1280x800_light` | Show "All changes saved" as text | S |
| UX-038 | Flow editor on a phone | N8 | 2 | SHOP | VERIFIED: the hint banner and the problem banner fill about 40% of a 360×640 screen `flow_editor_360x640_light` | Show the hint once and never on phones; collapse the problem list | S |
| UX-039 | Flow editor | N9 | 1 | SEC | VERIFIED: the problem list sits above the canvas; the step shows only a red "!" `B_f1_step_menu` | Open the step when the message is clicked; mark the field | S |
| UX-040 | Add a step list | N6 (Hick) | 1 | SEC | VERIFIED: Triggers 3, Actions 20 in 6 groups, Building blocks 3 last `D_g1_palette` | "Most used" and "Building blocks" first | S |
| UX-041 | Flow editor, large flows | N8 | 1 | SUPER | VERIFIED: 35 steps drawn at 54% zoom, text about 6 px; Tidy up and fit exist `F_long_flow_1280` | Fold runs of similar steps | M |
| UX-042 | Flow editor on touch | WCAG 2.5.7 | 2 | SHOP | SUSPECTED: connecting steps is drag-based; buttons exist for move and add; touch drag not tried | Try on a real phone | M |
| UX-043 | Response times | N3 | 1 | SUPER | VERIFIED: no "reset to the standard values" `rules_times_1280x800_light` | Add the button | S |
| UX-044 | Settings, Conversations | N4 | 1 | SEC | VERIFIED: the browser's own "Choose File" button and `dd-mm-yyyy` date boxes `settings_1280x800_light` | Style the file chooser; show dates the Indian way | S |
| UX-045 | Wrong organisation address | N9 | 2 | SEC | VERIFIED: `/admin/nosuchplace` shows raw JSON `{"detail":"Unknown org 'nosuchplace'"}` `D_404`; `pages.py:50-51` | A friendly page with a link to sign in (the QA file's QA-031 is about the same route) | S |
| UX-046 | First load | N1 | 2 | SHOP, SEC | VERIFIED: `panel.js` is 411 KB and was sent uncompressed here; 12.5 s to content at 50 KB/s; only "Loading…" shown; Lighthouse (phone): performance 80, first paint 3.5 s, biggest paint 4.0 s, text compression would save 363 KiB, unused script 335 KiB | Compress at the server or the edge (check Railway first); show a skeleton; later split by screen | S (compression) |
| UX-047 | Start-up error | N9 | 1 | SEC | SUSPECTED: "The dashboard could not start: …" with no retry (`js_boot.py:195, 201`) | Add "Try again" | S |
| UX-048 | Admin landing | N7 | 1 | SEC | VERIFIED: an admin with one organisation sees a list with one card first `D_meena_landing` | Open her only organisation directly | S |
| UX-049 | Roles & access, flow editor | N4 | 1 | SUPER | VERIFIED: "who may use a flow" is edited in two places: the toggles per role, and "Who can use it" in the trigger window | Keep both; link them ("also set under …") | S |
| UX-050 | Case rules, case window | N6 | 2 | SUPER | VERIFIED: a response time can come from the priority table, the kind of complaint, or the rule; the case window says "Response target from the rule: 4 h"; the page says a kind "uses that instead" | Show on each case which one applied and why | M |
| UX-051 | Conversations, Settings, editor, Sign-in log | N8 | 1 | SUPER | VERIFIED: four histories in four places | One "Activity" area with filters | M |
| UX-052 | Everywhere | N10 | 1 | SEC | VERIFIED: five help surfaces (Help & words, the "How a flow works" strip, the editor hint, "Getting set up", "How cases are handled") | Keep; make "Learn the words" open the same window everywhere | S |
| UX-053 | Whole front end | maintainability | 1 | DEV | VERIFIED: HTML, CSS and JS are Python strings, 6,179 lines in `app/admin_panel/ui/*.py`; the script is checked only by running `node --check` on a dump | Move to real `.js` and `.css` files served as they are | M |
| UX-054 | Page response | security | 2 | DEV | VERIFIED (local server): no Content-Security-Policy, frame protection, nosniff or referrer-policy header; only `cache-control: no-cache` | Add the four headers; the page loads nothing from outside | S |
| UX-055 | CSS | consistency | 1 | DEV | VERIFIED: 14 different font sizes (10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14, 15, 16, 18, 25, 28 px) and 13 uses of `!important` | A type scale as tokens | M |
| UX-056 | Home chart | security | 1 | DEV | VERIFIED: two string `style:` values (`js_home.py:13-14`) would be blocked by a strict style policy | Use SVG attributes instead | S |
| UX-057 | Chat bot screen | N2 | 1 | SEC | VERIFIED: the address is `#/assistant` while the screen is called "Chat bot" (`js_boot.py:6`); the word is never used on screen | Use `#/chatbot` and keep the old address working (the code already maps old addresses) | S |

### 6.1 Heuristic scores (0 = fails, 4 = excellent)

| Heuristic | Score | Why |
|---|---|---|
| N1 Visibility of system status | 3 | Unsaved and Saved tags, messages, counts, badges. The flow switch is silent (UX-035) and messages are not announced (UX-004). |
| N2 Match with the real world | 3 | Plain words and a glossary. "Not residing", "entity records", "Seat", "Specificity" are not the user's words. |
| N3 User control and freedom | 3 | Undo, Discard, history, Escape, Back. No reset to standard values; no undo for switching off. |
| N4 Consistency and standards | 3 | One set of building blocks. The same fact edited in two places; native controls mixed in. |
| N5 Error prevention | 3 | Duplicate and unrealistic-value checks; a flow can be deleted only when off. No warning when switching off or choosing "No role". |
| N6 Recognition over recall | 3 | Labelled menu, cards, previews. The editor's menu loses its labels; "Building blocks" is last. |
| N7 Flexibility and efficiency | 2 | Ctrl K, `N`, filters, Move up and down. No bulk add; approvals need JSON. |
| N8 Minimal design | 3 | Calm layout, few colours. The person window is long; Settings has three levels. |
| N9 Recognise, diagnose, recover from errors | 3 | Plain messages that say what to do. Raw JSON on a wrong address; errors not next to the field. |
| N10 Help and documentation | 3 | Words window, strips, examples, previews. Five help surfaces that do not point at each other. |

Misc points (Miller, Hick, Fitts): choices per screen are mostly seven or fewer; the exceptions are the step list (20 actions in 6 groups, UX-040) and the person window (10 sections, UX-029). Target size (Fitts) is the weak point on phones (UX-008). Progressive disclosure is used well in the step window (Settings, Only if, Technical) and badly in Safeguards (JSON in the open, UX-023). Reading level of the screen text is plain (short sentences, everyday words); the long sentences are in the Messages texts, which are the chat bot's own wording.

---

## 7. Accessibility, performance and resilience (what was measured)

All numbers are from the made-up society on this computer. Screenshots: `docs/ux/screens/`.

### 7.1 axe-core (4.10.2): 12 screens at 1280 px and 4 at 360 px

Tags: WCAG 2.0 A and AA, 2.1 A and AA, 2.2 AA, and best practice. The table counts the 12 screens at 1280 px; the list below it also shows the four phone-size runs. "Elements" counts the page elements that break the rule.

| Rule | Impact | Elements | Screens | What it means | Example |
|---|---|---|---|---|---|
| `label` | critical | 22 | 5 | A form control has no label | `article[aria-label="Open File a complaint"] > .between.flat.row > labe` |
| `button-name` | critical | 4 | 1 | A button has no name | `button[data-popkeep="1"][type="button"]:nth-child(3)` |
| `select-name` | critical | 1 | 1 | A select has no name | `select` |
| `color-contrast` | serious | 26 | 11 | Text colour too close to its background | `.navlabel:nth-child(1)` |
| `link-name` | serious | 9 | 1 | A link has no name | `a[href$="#/overview"]` |
| `nested-interactive` | serious | 3 | 1 | A control sits inside another control | `div[data-id="0"]` |
| `page-has-heading-one` | moderate | 1 | 1 | The page has no top heading | `html` |
| `aria-allowed-role` | minor | 9 | 1 | A role that does not fit the element | `article[aria-label="Open File a complaint"]` |

Per screen (rule:elements):

* `home_1280`: color-contrast:2
* `cases_1280`: color-contrast:2
* `case_drawer_1280`: color-contrast:7
* `people_1280`: color-contrast:2
* `flows_1280`: aria-allowed-role:9, color-contrast:2, label:9
* `flow_editor_1280`: button-name:4, label:1, link-name:9, nested-interactive:3, page-has-heading-one:1
* `rules_times_1280`: color-contrast:2, label:8
* `access_seats_1280`: color-contrast:2
* `settings_1280`: color-contrast:2, label:2
* `chatbot_messages_1280`: color-contrast:2
* `conversations_1280`: color-contrast:2, label:2, select-name:1
* `super_orgs_1280`: color-contrast:1
* `home_360`: none
* `cases_360`: none
* `people_360`: button-name:1, scrollable-region-focusable:1
* `flows_360`: aria-allowed-role:9, button-name:1, label:9

Reading it: the three **critical** rules (a control with no label, a button with no name, a select with no name) are the ones that stop a screen-reader user from doing something at all. Lighthouse's own accessibility score hides this (Home on a phone 100, Cases on a desktop 96) because it checks a smaller set on the screen as first shown.

### 7.2 Measured on every screen (1280×800, light)

"Controls" are visible links, buttons, inputs and switches. "Failing contrast pairs" are distinct text and background colour pairs below 4.5:1 (or 3:1 for large text). "Overflow at 360" is how many pixels the page is wider than a 360 px phone.

| Screen | Page elements | Controls | Under 44 px | Under 24 px | Unnamed | Failing contrast pairs | Smallest text (px) | Overflow at 360 (px) |
|---|---|---|---|---|---|---|---|---|
| Sign in | 310 | 7 | 4 | 2 | 0 | 0 | 11.5 | 0 |
| Sign in (organisation address) | 311 | 7 | 4 | 2 | 0 | 0 | 11.5 | 0 |
| Organisations (super admin overview) | 349 | 15 | 11 | 1 | 0 | 1 | 11 | 0 |
| Home | 450 | 26 | 22 | 0 | 0 | 1 | 11 | 0 |
| Cases | 708 | 30 | 30 | 0 | 0 | 3 | 11 | 0 |
| Cases, filtered | 539 | 37 | 37 | 1 | 0 | 2 | 11 | 0 |
| Case window | 801 | 35 | 35 | 0 | 0 | 3 | 11 | 0 |
| Conversations | 577 | 21 | 21 | 0 | 2 | 8 | 11 | 0 |
| People | 826 | 25 | 25 | 0 | 0 | 13 | 11 | 0 |
| Person window | 920 | 39 | 39 | 3 | 0 | 13 | 11 | 0 |
| Flows | 515 | 34 | 25 | 0 | 0 | 2 | 11 | 0 |
| Flow editor (flow) | 807 | 39 | 34 | 4 | 12 | 2 | n/a | 6 |
| Flow editor (block) | 736 | 34 | 32 | 2 | 12 | 3 | n/a | 2 |
| Chat bot: Messages | 488 | 48 | 27 | 0 | 0 | 4 | 11 | 0 |
| Chat bot: AI notes | 428 | 29 | 23 | 1 | 4 | 3 | 11 | 0 |
| Case rules: Who gets them | 489 | 39 | 39 | 1 | 1 | 1 | 11 | 0 |
| Case rules: Kinds of complaint | 584 | 43 | 43 | 12 | 0 | 1 | 11 | 11 |
| Case rules: Response times | 388 | 29 | 29 | 1 | 0 | 1 | 11 | 7 |
| Roles & access: Roles | 489 | 34 | 33 | 3 | 0 | 1 | 11 | 0 |
| Roles & access: Seats | 438 | 44 | 44 | 1 | 0 | 3 | 11 | 0 |
| Roles & access: Special access | 365 | 24 | 24 | 1 | 0 | 2 | 11 | 0 |
| Settings | 525 | 42 | 42 | 2 | 1 | 2 | 11 | 0 |
| Settings: History of changes | 408 | 23 | 23 | 1 | 0 | 2 | 11 | 19 |
| Home (the shop) | 336 | 15 | 15 | 0 | 0 | 1 | 11 | 0 |

The editor's smallest text shows as n/a because the canvas draws some labels as graphics. Worst contrast pairs seen: menu group labels 2.6:1; avatar letters 3.3 to 3.5:1; the count chips 4.33:1.

### 7.3 Other sizes, dark mode and zoom (12 key screens each)

| View | Screens that spill sideways (px) | Most failing contrast pairs on one screen | Controls under 24 px (all 12 screens) |
|---|---|---|---|
| 768×1024, light | none | 13 | 9 |
| 1920×1080, light | none | 13 | 9 |
| 1280×800, dark | none | 14 | 9 |
| 360×640, dark | Flow editor (flow) 6, Case rules: Response times 7 | 14 | 7 |
| 200% zoom (640×400 at 2×) | none | 13 | 9 |
| 400% zoom (320×256 at 4×) | Flows 6, Flow editor (flow) 46, Case rules: Response times 47, Roles & access: Seats 29 | 13 | 7 |

Reading it: dark mode is not better than light for contrast (14 pairs against 13). 200% zoom is clean. At 400% (the WCAG reflow test, 320 px wide) four screens spill sideways. The editor (a canvas) is allowed to scroll in two directions under WCAG 1.4.10, but Response times and Seats are ordinary screens and should not.

### 7.4 Keyboard pass

* **Home** (walked from the top): the first stop is "Search or jump to", then the nine menu links, the account button, Sign out, Help, Collapse and Light/dark: **15 stops before the page content**. There is no skip link.
* **Focus indicator**: on the five screens walked (45 Tab presses each) every stop showed an outline or shadow, except the **flow name box in the editor**.
* On Cases, People and Flows the browser started inside the page content (the starting point was left over from an earlier click), so only the focus-indicator result is reliable there.
* **Dialog (Add person)**: focus lands in the first box (good). After 5 more Tab presses focus leaves the dialog and walks the page behind. On close, focus goes to the page body, not back to the button that opened it. (`F_duplicate`)
* **Side window (person)**: focus does not move into it on opening; Tab goes to the page behind. Escape closes it and the address goes back to `#/people`.
* **Editor boxes**: `tabindex=0`, `role=button`, labelled (code); an `N` shortcut adds a step. The icon-only menu rail has controls with no names.

### 7.5 Lighthouse 12.6.1

| | Home, phone | Cases, desktop |
|---|---|---|
| Performance | 80 | 99 |
| Accessibility | 100 | 96 (colour contrast fails) |
| Best practices | 100 | 100 |
| First paint | 3.5 s | 0.7 s |
| Biggest paint | 4.0 s | 0.8 s |
| Blocking time | 40 ms | 0 ms |
| Layout shift | 0 | 0.059 |
| Transfer size | 501 KiB | 505 KiB |
| Page elements | 442 | 700 |
| Text compression would save | 363 KiB | 367 KiB |
| Unused script | 335 KiB | 337 KiB |
| Unminified script | 84 KiB | 84 KiB |

The phone run simulates a slow mobile network and a slower processor; the server itself is on this computer. The compression point is true for the local server; the live server on Railway was not checked (production is off limits), so check its response headers once.

### 7.6 Load, shift, size and the network

| Measure | Result |
|---|---|
| Content visible after a reload (local, no throttling) | 265 ms |
| Same, with 400 ms delay and 50 KB/s (a slow phone connection) | 12.5 s (`panel.js` alone 10.1 s, `panel.css` 3.6 s) |
| Script and style size | `panel.js` 411,197 bytes, `panel.css` about 80 KB; the answer carries no `content-encoding` |
| Layout shift on load | 0 |
| Page elements | 336 to 920 per screen; editor 807; a 35-step flow 1,699 |
| Memory after loading Home | about 35 MB |
| Network drops while using Cases | "Cannot reach the server. Check your connection and try again." and a Try again button |
| Back button after opening a case | closes the window, address returns to `#/cases` |
| Leaving the editor with unsaved changes | the browser's leave-page warning is armed |

### 7.7 How the numbers were made

* **Target size**: the box of every visible link, button, input, select, switch and tab.
* **Contrast**: the computed text colour against the nearest opaque background, blended where the colour has transparency, with the WCAG formula. Text on gradients or pictures was skipped.
* **Smallest text**: the smallest computed font size of any visible text element.
* **Names**: aria-label, aria-labelledby, visible text, value, title or placeholder; anything with none is counted as unnamed.
* **Tab walk**: real key presses through the browser, 45 per screen.

---

## 8. Redundancy matrix

One job, one place is the rule of thumb. Where a job has several places, the matrix says where, and what to do.

| Job or fact | Where it appears | Places | Verdict and advice |
|---|---|---|---|
| Hand a case to someone | Cases list (Assign), case window (Assign), the chat bot's own "Assign a case" flow | 3 | Fine: same flow behind all three. Say so in the dialog ("runs the flow Assign a case"). |
| Change a person's role | Person window (Role, Save role); a committee seat (changes the role as a side effect); Roles shows counts only | 2 | Fine; the seat dialog already says it. |
| Who may use a flow | Roles & access → Roles (one switch per flow); the flow's trigger window ("Who can use it"); Special access (one person) | 3 | Link them: each place says "also set in …". (UX-049) |
| A response time | Response times (per priority); Kinds of complaint (per kind); Who gets them (per rule) | 3 | Show on each case which one applied. (UX-050) |
| Whether a person is active | Person window, Account ("Active / Inactive"); Home status ("Active, Suspended, Inactive, Not residing") | 2 | One "Moved out / Suspended" control; derive the other. (UX-028) |
| Dashboard access for a person | Person window ("Give dashboard access"); super admin page "Dashboard access"; sign-up invite | 3 | Name them differently. (UX-030) |
| History of what happened | Conversations; Settings → History of changes; the flow's History; the Sign-in log; Messages and AI notes each have History | 5 | One "Activity" area with filters. (UX-051) |
| Help | Help & words; "How a flow works" strip; editor hint; "Getting set up"; "How cases are handled" | 5 | Keep, but let "Learn the words" open the same window everywhere. (UX-052) |
| Switch a flow on or off | Card on Flows; switch in the editor header | 2 | Consistent. Keep. |
| Search | Ctrl K; a search box on Cases, People, Conversations, Flows | 5 | Expected. Keep. |
| Sign out | The visible button; the account chip | 2 | Fine. |
| Open the people list | Menu; Home ("25 of 25 people cannot be messaged yet → Open People"); Roles ("Manage roles" goes the other way) | 3 | Fine. |
| Classic panel and new panel | only the new panel exists | 1 | Done. |

Dead or empty sections: none seen. A section shows only when the organisation's database can use it (for the shop: no Cases, no Case rules).

---

## 9. Terminology glossary (what is said now, what to say instead)

Words the panel already defines in "Help & words" are marked "defined". The replacement is a suggestion; the screens use "flow", "step", "chat bot" and "AI helper" consistently today and that should stay.

| Now on screen | Where | Say instead | Note |
|---|---|---|---|
| entity records | step subtitle in the editor | the table's friendly name ("Expense records") | UX-021 |
| to user id | step subtitle in the editor | "to the person who asked" | UX-021 |
| `'$user.user_id'` | problem banner | "the person who asked" | UX-022 |
| approval_chain | tag in Safeguards | "Approval" | UX-023 |
| Advanced / JSON | Safeguards text and tab | one word for both: "JSON" | UX-023 |
| Safeguards | trigger window tab | "Approvals and checks" | the text says "who may run it, one-time codes, approvals" |
| Specificity 10 | rule cards | "Priority of this rule" with a tip | UX-024 |
| (seat) | rule cards | "(position)" or drop | |
| Seat | menu tab, cards | "Position" (a job someone holds) | defined: "A job someone holds, like Secretary" |
| Special access | tab | "Temporary access" | it has dates |
| Building block | flows, palette | "Shared step" | defined |
| Trigger / Starts when… / Starts it | flows, editor | "What starts it" | defined |
| Park | step window | "Switch this step off" | the screen already explains "stays here but does not run" |
| Tidy up | editor bar | "Arrange steps" | |
| Simple / Detailed | editor bar | "Compact / Detailed" | |
| Try it / REHEARSAL | editor | "Try it" in both places | two words for one thing |
| Technical | step window tab | "Technical details" | |
| Case rules | menu | "Case handling" | three tabs: who gets them, kinds, response times |
| Who gets them | tab | "Who handles which kind" | |
| Conversations | menu | "Chat history" | UX-018 |
| Chat bot (as a menu item) | menu | "What the chat bot says" | UX-018; the word "chat bot" stays for the thing people talk to |
| Messages / AI notes | tabs | "Chat bot texts" / "Notes for the AI" | |
| No one handling them / Not assigned yet / Not assigned | Home, tile, Cases | "Nobody has it yet" | UX-025 |
| Handled by / Who has it / Handling it | case window, list, badge | "Who has it" | UX-025 |
| Past target time | Home tile | "Late" | the tile can carry the target in a tip |
| Not residing / Inactive | person window | "Moved out" / "Switched off" | UX-028 |
| On Telegram: Not yet | People column | "Chat bot linked: no" | UX-032 |
| Give dashboard access / Give access | person window | "Let them sign in here" / "Give temporary access" | UX-030 |
| Super admin | admin sidebar card | "OrchestrAI support" | UX-026 |
| Are you sure? | confirm dialog title | the action ("Delete Dues reminder?") | `js_core.py:231` |
| `#/assistant` | address of the Chat bot screen | `#/chatbot` | UX-057 |

No other jargon was found on any screen: SQL, DSL, schema, gate, intent_key, slug, UUID and similar words appear nowhere in the text of the 22 screens (the word "gate" appeared only in made-up case titles).

---

## 10. Information architecture, before and after

### Before (as built; super admin)

```
OrchestrAI (/admin)                      Organisation (/admin/<org>)
  Overview                                 EVERY DAY
  Organisations                              Home
  Dashboard access                           Cases
  Sign-in log                                Conversations
                                             People
Admin (client) sees:                       SET UP
  Organisations (cards)                      Flows            (Flows | Building blocks)
  then, per organisation:                    Chat bot         (Messages | AI notes)
    Home, Cases, People                      Case rules       (Who gets them | Kinds of complaint | Response times)
    + card "Ask a super admin"               Roles & access   (Roles | Seats | Special access)
                                             Settings         (Settings | History of changes)
                                           + Search or jump to (Ctrl K), Help & words
```

### After (small, consistent changes; no redesign)

```
Organisation (/admin/<org>)
  EVERY DAY
    Home
    Cases
    People
    Chat history            (was Conversations)
  SET UP
    Flows                   (Flows | Shared steps)
    What the chat bot says  (was Chat bot: Chat bot texts | Notes for the AI)
    Case handling           (was Case rules: Who handles which kind | Kinds of complaint | Response times)
    Roles & positions       (was Roles & access: Roles | Positions | Temporary access)
    Settings                (Settings | Who changed what)
  Always there: Skip link, Search or jump to, Help & words, Sign out
Admin (client): Home, Cases, People, and "Ask OrchestrAI support"
If an admin has one organisation: sign in goes straight to her Home
```

Why: the menu keeps its two groups and its order, so nobody who knows it has to learn it again. Only names change, to stop two neighbours sounding alike ("Conversations" beside "Chat bot"), to use the user's words ("position", "temporary access", "who changed what"), and to stop "rules" meaning three things. Two moves are worth the effort later: one "Activity" area for the four histories (UX-051), and a shortcut from a person's window straight to their seat.

---

## 11. Wireframes of the three worst screens

The three screens a novice is most likely to be stopped by, in order: the **person window** (tasks a and b), the **approvals pane** (task e), and the **flow card switch** (task k). Plain ASCII; widths are approximate.

### W1. Person window (UX-027, UX-028, UX-029, UX-030)

Today: ten sections stacked under each other, "Moved out" hidden inside a status list, two "access" buttons, no way to record a flat.

```
TODAY                                         PROPOSED (top part only)
+---------------------------------+           +----------------------------------------+
| Manish Kapoor        [x]        |           | Manish Kapoor                      [x] |
| Tenant  Active  Cannot be msg'd |           | Tenant . C-204 . Active                |
+---------------------------------+           | Chat bot: not linked yet               |
| Account                         |           +----------------------------------------+
|  Role [Tenant v] [Save role]    |           | What do you want to do?                |
|  Active  (Inactive people ...)  |           | [ Moved out ] [ Change role ] [ Flat ] |
|  Email ...                      |           +----------------------------------------+
| Dashboard                       |           | > Contact and chat bot link            |
|  [Give dashboard access]        |           | > Seats and temporary access           |
| Messaging  ...                  |           | > Cases: has 0, raised 3               |
| Added ... Chats ...             |           | > Chats: 12 messages  [View chats]     |
| Home                            |           +----------------------------------------+
|  [C][204][Tenant v][Active v]   |
|  [Save home]  (status note)     |           "Moved out" opens a small dialog:
| Seats ... Special access ...    |           +----------------------------------------+
| Handling now ... Raised ...     |           | Manish Kapoor has moved out            |
+---------------------------------+           | Date moved out  [ 08 Oct 2026 ]        |
                                              | What happens:                          |
                                              |  - they can no longer use the chat bot |
                                              |  - cases they hold stay until you hand |
                                              |    them to someone                     |
                                              |  - you can bring them back from here   |
                                              | [Cancel]            [Mark as moved out]|
                                              +----------------------------------------+
"Flat" (and Add person for housing organisations) takes Wing, Flat, Owner or Tenant.
```

### W2. Approvals pane in the trigger window (UX-034, UX-023)

Today: a sentence, a raw tag, and "edit them as JSON".

```
TODAY
+--------------------------------------------------------------+
| Starts it | Asks for | Safeguards | History | JSON           |
| Rules that stop or slow a flow down ...                      |
| Needs approval from Committee member then Admin when amount |
| is at least 10000                         [approval_chain]  |
| To change safeguards, edit them as JSON under "Advanced".    |
+--------------------------------------------------------------+

PROPOSED
+--------------------------------------------------------------+
| Starts it | Asks for | Approvals and checks | History | JSON  |
| Ask for approval when  [Amount v] [is at least v] [ 10,000 ] |
|                                                              |
|  Level 1  Who approves [Committee member v]  up to [50,000]  |
|  Level 2  Who approves [Admin v]             above that      |
|  [+ Add a level]                                             |
|                                                              |
|  In words: "Over Rs 10,000 the committee approves. Over      |
|  Rs 50,000 an admin approves as well."                       |
|                                                              |
|  [Save]                         > Show as JSON (for experts) |
+--------------------------------------------------------------+
```

### W3. Flow card: switching off, and what it says (UX-035, UX-006)

Today: the switch inside a clickable card flips at once and says nothing.

```
PROPOSED
+--------------------------------------------------+
| Pre-approve a visitor              [ ( ) Off  ]  |   <- the switch has its own name:
| Lets the security guard know a visitor ...       |      "Switch off Pre-approve a visitor"
| Admin, Owner, Security guard +1                  |
| 2 steps . /visitor . used 9 h ago     [Open]     |   <- the card is a heading and one link
+--------------------------------------------------+

After the click, a message that screen readers also read (role=status), 15 seconds:
+-------------------------------------------------------------------------------+
| Switched off "Pre-approve a visitor". People can no longer use /visitor. [Undo]|
+-------------------------------------------------------------------------------+

If other flows run this one:
+--------------------------------------------------+
| "Dues reminder" uses this flow.                  |
| Switch those off first, or open them.            |
| [Open Dues reminder]                   [Close]   |
+--------------------------------------------------+
```

---

## 12. Design-system gaps, and a minimal path for the code

### 12.1 What exists

Buttons (default, primary, ghost, danger, small), badges, notices, cards, field, select, switch, table, pager, tabs, empty state, modal, confirm box, side window, pop-over, message (toast), avatar, icons, search box (Ctrl K), colour variables (`--k-*`). They are shared on every screen, which is why one fix in one helper repairs many screens.

### 12.2 What is missing

| Gap | Today | What to add |
|---|---|---|
| **Dialog primitive** | `modal()`, the side window and pop-overs each do their own thing; no role, no label, no focus handling (`js_core.py:193-258`) | One helper: `role="dialog"`, `aria-modal`, `aria-labelledby`, a named "Close", focus in, Tab kept inside, focus back |
| **Form field** | `field()` makes a `<label>` with no `for` (`js_core.py:138`); errors go to the dialog foot | Label, control, hint and error tied by ids; `aria-describedby`, `aria-invalid`; error under the field |
| **Icon button** | many buttons are an icon with no name (the editor rail) | A helper that refuses to build without an accessible name, and shows a tip |
| **Messages (toasts)** | no live region; 3.5 to 9 s | `role="status"` box; errors stay until closed; one Undo time (15 s) |
| **Loading state** | the word "Loading…" | Skeleton rows and cards; a busy state on buttons (`aria-busy`) |
| **Empty state** | `empty(title, text)` exists | Add a next action ("Add your first person") |
| **Confirmation pattern** | title "Are you sure?", button "Yes, do it" by default (`js_core.py:226-232`) | State the action in the title and on the button; prefer Undo to asking |
| **Tokens** | colours are variables; type, spacing, target size, motion, focus ring are not | Type scale (14 sizes down to 6), minimum text 12 px, minimum target 44 px, spacing scale, focus ring, reduced-motion rule |
| **Responsive table** | a wide table cut off on a phone | Rows as cards under 480 px, or a focusable scroll wrapper |
| **Colour pairs** | avatar and label colours fail 4.5:1 | A checked palette (a test that fails below 4.5:1) |
| **Skip link and landmarks** | landmarks exist; no skip link | "Skip to main content" |
| **Date and file inputs** | the browser's own | Styled, Indian date order |
| **Back pattern** | two ways back in the editor | One |

### 12.3 A minimal path (no rewrite)

1. **Fix the five helpers** (dialog, field, icon button, toast, table wrapper). About 3 to 4 days, and it removes most of the axe findings on every screen at once (UX-001 to UX-006, UX-012, UX-013).
2. **Tokens** for type, spacing, minimum target and focus; replace the 14 font sizes by about 6 (UX-007, UX-008, UX-010, UX-055).
3. **Put the front end in real files.** Move the HTML, CSS and JS strings in `app/admin_panel/ui/*.py` into `.js` and `.css` files that the page serves as they are. A linter and a formatter then work, and so does an editor (UX-053).
4. **Send security headers** (content policy, frame protection, nosniff, referrer policy) and change the two string `style:` values on the Home chart to SVG attributes so a strict policy does not break it (UX-054, UX-056). Nothing is loaded from outside, so `default-src 'self'` is enough.
5. **Compress** `panel.js` and `panel.css` (UX-046).
6. **Add checks**: run axe on six screens with the browser driver in `docs/ux/tools/` on every push, and a small test that fails if a colour pair drops below 4.5:1.

**Where a redesign is justified**: only the top of the **person window** (W1). Everything else is small fixes.

---

## 13. Five-person usability test script

The real test the brief asks for. This audit could not use real people.

### 13.1 Goal and set-up

* **Goal**: find out where first-time users stop or err on the jobs in section 4, and whether they feel safe.
* **Where**: a copy of the panel on made-up data (the same Sunrise Heights society used here). Never real residents or messages.
* **How**: 45 minutes each, one at a time, in person or by video, screen and voice recorded with permission. One moderator, one note-taker. Participants 1, 2, 4 and 5 use a laptop; participant 3 uses their own phone.
* **Think aloud**: "Please say what you are looking at and thinking. We are testing the screens, not you."

### 13.2 Who to recruit

| # | Who | Why |
|---|---|---|
| P1 | A society secretary or committee member, 60 or older, uses WhatsApp daily, no admin tool experience | The brief's main persona |
| P2 | A treasurer or accountant in their 50s who uses spreadsheets or Tally | Approvals and money tasks |
| P3 | A shop owner who will use an Android phone | 360 px screens, touch |
| P4 | A volunteer in their 30s, comfortable with apps, never used a workflow tool | The "average" new user |
| P5 | A developer or IT person | A control: what experts find easy and novices do not |

At least one of the five should use zoom, magnification or a screen reader, and one should have glasses-level vision trouble. Exclude anyone who works for OrchestrAI.

**Screening questions** (ask on the phone): your age band; your role; which devices you use for work; do you use a screen reader, magnifier or large text; have you used a chat bot to run work (WhatsApp or Telegram); have you used a workflow or automation tool; are you happy to be recorded.

### 13.3 Running order

| Minutes | What |
|---|---|
| 0 to 5 | Welcome, consent, "we test the screens, not you" |
| 5 to 8 | Warm-up: how do you run requests and approvals today? |
| 8 to 38 | Tasks T1 to T7 (P4 and P5 also T8) |
| 38 to 45 | One-question confidence rating after each task (1 to 7), then the 10-question SUS form, then the debrief |

### 13.4 Tasks (read them in the user's words, not the screen's)

| Task | Say this | Success | Time limit | Watch for |
|---|---|---|---|---|
| **T1** | "You have just signed in. What needs your attention today?" | Names the cases with nobody on them and opens them in 60 s | 2 min | Do they read "Needs you"? Do they press "See them"? |
| **T2** | "A new tenant, Isha Nair, has moved into flat B-402. Add her." | Person added with the right name, e-mail and role. Also ask: "Where would you write the flat number?" | 3 min | Where they look for the flat (the panel has no place: UX-027) |
| **T3** | "Manish Kapoor has left the society. Show that he has moved out." | "Not residing" saved under Home (success); only "Inactive" (partial) | 3 min | The word they search for; do they find the Home section; do they scroll |
| **T4** | "The treasurer has changed. Farah is replaced by Sanjay." (super admin view) | Seats, Change holder, new person, Save; says the role will change | 3 min | Do they read the warning; do they know what a seat is |
| **T5** | "A resident wrote about a visitor yesterday. Find it and read the whole chat." | Opens the full conversation | 2 min | Search or date first; do they find the row to click |
| **T6** | "Case SH-26-034 is still open. Tell me why." | Says who has it (or that nobody does), that it is late, and what the timeline shows | 3 min | Do they read the timeline; do they understand "What the case rules say" |
| **T7** | "In the flow Approve a society expense, remove the step that saves the record. Then change your mind." | Delete, then Undo within 9 s (or the undo arrow); then "Switch off the Dues reminder so nobody can use it" and say what they expect to happen | 4 min | Do they hesitate; do they look for consequences when switching off (UX-035) |
| **T8** (P4, P5) | "Make approvals need a second person above Rs 50,000." | Edits the approvals (JSON) or asks the AI helper, and says how sure they are | 5 min | Do they find Safeguards; what do they do at "edit them as JSON" (UX-034) |

**Help rule for the moderator**: after 60 seconds of silence ask "What are you looking for?"; after 2 minutes give one hint ("Try looking in …"); after 3 minutes stop and mark as failed. Write down every hint.

### 13.5 What to record on each task

* Completion: **unaided**, **with one hint**, **with more than one hint**, **failed**.
* Time on task against the budget in section 4.
* Errors: wrong menu, wrong button, backing out, re-reading, asking what a word means.
* The exact words they say for things (moved out, flat, approve) and what they call "Flows", "Seat", "Building block".
* Where they look first; whether they use search, Help & words, Back, Escape, zoom or pinch.
* On the phone: mis-taps, reading small text, sideways scrolling, the editor.
* Moments of fear: "I don't want to break it".
* Confidence rating (1 to 7) after each task.

### 13.6 Success criteria for the panel as a whole

* **T1, T5 and T6**: at least 4 of 5 unaided.
* **T3**: at least 3 of 5 unaided (today it is expected to fail this).
* **T2**: the flat question must have an answer that is not "I cannot".
* **T7**: all complete the delete and Undo; at least 3 of 5 say that switching off affects the people who use the flow.
* **SUS**: an average of 68 or more.
* Nobody is stopped for more than 2 minutes by a word they do not know.

### 13.7 Debrief questions

1. What was the hardest thing? What was the easiest?
2. In your own words, what is a "flow"? A "seat"? A "building block"?
3. Where would you look to change who approves a bill?
4. Did you feel you might break something? When?
5. What would you call "Not residing"?
6. If you could change one thing, what?

### 13.8 After the sessions

Mark each finding in section 6 as confirmed, changed or new; re-rate severity by how many of the five were stopped (all five = 3, three or four = 2, one or two = 1); write the quotes next to the finding. Re-run the checks in section 7 after the quick wins are done.

---

## 14. Files, and how to repeat the measurements

### 14.1 Where the deliverables from the brief are

| Brief asked for | Where |
|---|---|
| ux-audit.md with a paste-back summary | the start of this file |
| screen-inventory.md | section 3 |
| task-walkthroughs.md | section 4 (and the test cases in section 5) |
| findings.csv | `docs/ux/findings.csv` (same as section 6) |
| redundancy-matrix.md | section 8 |
| terminology-glossary.md | section 9 |
| accessibility-report.md | section 7 |
| Proposed sidebar, before and after | section 10 |
| Wireframes of the three worst screens | section 11 |
| Design-system gap list | section 12 |
| Five-participant usability script | section 13 |

### 14.2 Files added

* `docs/ux/OrchestrAI-UX-Audit.md`: this file.
* `docs/ux/findings.csv`: the findings table.
* `docs/ux/screens/`: about 170 screenshots (made-up data only). Names: `<screen>_<width>x<height>_<light or dark>`, `zoom200_…`, `zoom400_…`, and `B_`, `D_`, `E_`, `F_` for the task and check passes.
* `docs/ux/tools/`: the seed, the local server and the browser scripts used here.

No application file was changed.

### 14.3 To repeat

1. Start a Postgres on this computer (port 55432) and run the QA harness once, so the template databases `qa_tmpl_housing`, `qa_tmpl_jewellery` and `qa_tmpl_routing` exist (see the QA file, section 11).
2. Set `UX_PASSWORD` to any made-up password (the seed uses it for every made-up account, and the browser scripts sign in with it). `python docs/ux/tools/ux_seed.py` builds `ux_routing`, `ux_housing`, `ux_jewellery` with made-up data. `python docs/ux/tools/ux_extra.py` adds a long name and a 35-step flow. The made-up accounts are `kavya.rao@ux.test` (super admin), `meena.kulkarni@ux.test` (admin of the society) and `sam.thomas@ux.test` (admin of both).
3. `python -m uvicorn ux_server:app --app-dir docs/ux/tools --host 127.0.0.1 --port 8780`. The server never reads `.env`, uses dummy values only, refuses any database that is not on this computer, and sends nothing out.
4. `SHOTS=<folder> OUT=<folder> node docs/ux/tools/cdp.mjs docs/ux/tools/passA.mjs` (and `passB`, `passBD`, `passC`, `passE`, `passF`). `passC` needs `AXE_JS=<path to axe.min.js>` (axe-core 4.10.2 from npm). The paths to Edge and `psql` in the scripts may need changing.
5. Lighthouse: `lighthouse <url> --extra-headers '{"Cookie":"panel_session=…"}'` after signing in once.

