# OrchestrAI launch: UX priority test script (manual)

> **For the owner.** You do these tests yourself, one use case at a time, and mark each one. About **70 minutes** for the P0 tests and **45 minutes** for the P1 tests.
> **Then** send me the filled result table (section 5). I fix only what failed, in the order of section 6.

| | |
|---|---|
| Prepared | 2026-10-08 |
| Based on | `docs/ux/OrchestrAI-UX-Audit.md` (57 findings), the two live database copies, the sign-in and dashboard as live on Railway (commit `16a1637`) |
| Rule of the launch | Test what **real people will do first**. Leave the rest for later. |

---

## 1. Why these use cases (from your live data)

| What the data says | So we test |
|---|---|
| Godrej has **16 open cases that nobody has** (of 24 open) | Home → Cases → **Assign** (T02 to T05) |
| Only **6 of 17 people** are linked to Telegram. The other 11 cannot be told about anything | **Add a person and get them linked** (T06) |
| Godrej has 6 residents active, 2 suspended, 1 not residing | **Moved out** (T07) |
| The dashboard has so far been used by **you** (28 changes in 6 days, all to flows and rules). **No client admin has used it yet** | The admin's three screens first (Home, Cases, People), then **flow safety** for super admins (T09) |
| Flows on the live organisations are edited, switched on and off, and deleted every day | A mistake here breaks live chats: **Try it, Undo, history** (T09) |
| An admin can ask a super admin for help once (1 message so far) | **Ask a super admin** (T10) |
| Admins will open the dashboard on a **phone** | The same jobs at phone size (T08) |

**Priority words.** **P0** = a real person will do it in the first week. **P1** = soon after, or only for some people. **P2** = skip for now.

---

## 2. Before you start

### Where to test

| Mode | Use it for | Safe? |
|---|---|---|
| **L: the made-up society** on this computer (Sunrise Heights, 44 cases, fake people) | Everything that **changes** data, and the **admin's** view | ✅ Click anything |
| **P: your live dashboard** (your own super-admin sign-in) | Looking, searching, signing in, the phone check | ⚠ Only the tests marked ✅. A marked ⚠ test changes real data or messages a real person |

You cannot see an **admin's** smaller view with your super-admin account. Use mode L for that.

### Start mode L (copy and paste, PowerShell, in the project folder)

```powershell
$env:UX_PASSWORD = "Pick-Any-Made-Up-Password-1"
python docs/ux/tools/ux_seed.py
python -m uvicorn ux_server:app --app-dir docs/ux/tools --host 127.0.0.1 --port 8780
```
Then open `http://127.0.0.1:8780/admin`. The practice Postgres must be running (port 55432). **Or just tell me "start the test society" and I will do it.**

| Made-up account | Level | Password |
|---|---|---|
| `kavya.rao@ux.test` | Super admin | what you set above |
| `meena.kulkarni@ux.test` | Admin of Sunrise Heights (the society secretary) | same |
| `sam.thomas@ux.test` | Admin of two organisations | same |
| `lata.pillai@ux.test` | Admin of the shop (Zari Jewellers) | same |

In mode L, 14 made-up people are "linked to Telegram", so **Assign** has people to choose from. The others are not linked, on purpose, to show both states.

### How to mark

`✅` it worked and was clear · `⚠` it worked but something was confusing or wrong · `❌` I could not finish. Write **one line** of what you saw, and the screenshot name if you took one.

---

## 3. P0 tests: do these first (about 70 minutes)

### T01 · Sign in, sign out, wrong password, forgot password &nbsp; ⏱ 5 min &nbsp; ✅ live-safe

**Why.** The first thing every person does. A bad first screen loses them.
**Steps**
1. Open `/admin` while signed out. Read the page. Is it clear what to do?
2. Type a **wrong** password. Read the message.
3. Click **Forgot password?**. Read the screen (do not send the code).
4. Sign in with the right password. Where do you land?
5. Click **Sign out** (in the menu, under your name). Where do you land?

**Pass if.** Every message is in plain words and tells you what to do next. Sign-out lands on the sign-in page.
**Known today.** The "Forgot password?" and "Sign up" links are small (about 20 px high). An admin with one organisation sees a one-card list first (one extra click). *(UX-008, UX-048)*
**Result** ☐ ✅ ☐ ⚠ ☐ ❌ &nbsp; Note: ______________________

### T02 · Home: what needs me today? &nbsp; ⏱ 3 min &nbsp; ✅ live-safe

**Why.** The page every admin sees first. It must answer "what do I do now?" in about 5 seconds.
**Steps**
1. Open an organisation's dashboard. Start a stopwatch.
2. Look at the page. Say out loud what you would do first. Stop the stopwatch.
3. Click **See them** on "cases have no one handling them".

**Pass if.** You named the right first job in about 5 seconds, and **See them** opens the cases nobody has.
**Known today.** The words "Getting set up · 4 of 5" look like a status but are a checklist. *(UX-019)*
**Result** ☐ ✅ ☐ ⚠ ☐ ❌ &nbsp; Note: ______________________

### T03 · Cases: find a case &nbsp; ⏱ 4 min &nbsp; ✅ live-safe

**Why.** Admins live in this list.
**Steps**
1. Open **Cases**. Click **Open**, then **All**.
2. Search for a **case number**, then for a **word** from a title, then for a **person**.
3. Change **Sort**. Open **Filters** and filter by status.
4. Find a case that is **late**. Is it easy to see which are late?

**Pass if.** Each search finds the right case. Late cases are easy to spot (red "late" text).
**Known today.** On a phone the **Status** column is cut off (see T08). *(UX-011, UX-012)*
**Result** ☐ ✅ ☐ ⚠ ☐ ❌ &nbsp; Note: ______________________

### T04 · Assign a case &nbsp; ⏱ 6 min &nbsp; ⚠ mode L (on live it messages a real person)

**Why.** This is the main daily job: 16 open cases at Godrej have nobody.
**Steps**
1. In **Cases**, find a case with **Not assigned** and click **Assign** on its row.
2. In the window, click **Give it to** and type the first letters of a name. Choose a person.
3. Add a short note. Click **Assign**.
4. Read the message that appears. Look at the row: does it show the person now?
5. Open the case. Does the **timeline** say who it was handed to, with your note?

**Pass if.** You can finish in under a minute without help. The row, the case window and the timeline all agree.
**Known today.** If nobody is linked to the chat bot the list says "No one found". The small line under the box explains why, but it does not say how to fix it. *(related: T06)*
**Result** ☐ ✅ ☐ ⚠ ☐ ❌ &nbsp; Note: ______________________

### T05 · Why is this case still open? &nbsp; ⏱ 3 min &nbsp; ✅ live-safe

**Why.** An admin must be able to answer "why is this not closed?" for a resident.
**Steps**
1. Open a case that is **late**.
2. Find, in the window: who has it, when it was due, how late it is, what happened so far.
3. Read the box "What the case rules say".
4. Say the reason in **one sentence** out loud.

**Pass if.** You can give the reason in one sentence without scrolling around.
**Known today.** The timeline is at the bottom. There is no one-line "why it is open". "What the case rules say" is written for super admins. *(UX-050)*
**Result** ☐ ✅ ☐ ⚠ ☐ ❌ &nbsp; Note: ______________________

### T06 · Add a person and get them linked &nbsp; ⏱ 8 min &nbsp; ⚠ mode L (on live it creates a real person)

**Why.** 11 of 17 people at Godrej are not linked, so they hear nothing from the bot. Linking must be easy.
**Steps**
1. **People → Add person**. Type a name and an e-mail. Choose the role **Tenant**. Click **Add person**.
2. Click the new person in the list. Find the **Messaging** section.
3. Click **Copy the message to send**. Read the message. Would a resident understand it?
4. (Mode P only, with a real person.) Send it. When they reply to the bot with their e-mail, check that the person shows as linked.
5. Now try to **write the flat number** (for example B-402). Where would you look?

**Pass if.** Steps 1 to 3 take under 2 minutes and the message is clear. For step 5 you find a place to record the flat.
**Known today.** There is **no place to enter the flat** when adding a person, and no screen creates a home. *(UX-027)* Adding the same e-mail twice shows "… is already here with that email." (good).
**Result** ☐ ✅ ☐ ⚠ ☐ ❌ &nbsp; Note: ______________________

### T07 · Mark a resident as moved out &nbsp; ⏱ 5 min &nbsp; ⚠ mode L

**Why.** It happens every month in a society.
**Steps**
1. **People** → search a tenant → click the row.
2. Look for "moved out". Where do you click? Count your clicks.
3. Scroll to **Home**. Open the status list. What choices are there?
4. Choose the one you think means moved out. Click **Save home**.
5. Go back to the list. Does it show?

**Pass if.** You find it in 6 clicks or fewer **and** you are sure you picked the right word.
**Known today.** The word is **"Not residing"**, and there is a second "Active / Inactive" in the Account section. Many people will pick "Inactive". *(UX-028)*
**Result** ☐ ✅ ☐ ⚠ ☐ ❌ &nbsp; Note: ______________________

### T08 · The same jobs on a phone &nbsp; ⏱ 8 min &nbsp; ✅ live-safe (look only)

**Why.** Admins and shop owners will open it on a phone.
**Steps.** Use your phone, or in Chrome press `F12`, then the phone icon, then choose a **360 × 640** screen. Repeat T02, T03 and the **People** list.
1. Open the menu (the three-line button). Does it open and close?
2. On Cases: can you read the **Status** and **Who has it** without sideways scrolling?
3. Tap **Assign**, a filter chip and a menu item. Do you miss any?
4. Does anything run off the right edge of the screen?

**Pass if.** You can do the jobs without pinching or sideways scrolling.
**Known today.** Tables are cut off (Status, Role). Buttons are 27 to 37 px high (the guideline is 44). Four screens spill sideways by 6 to 19 px. The flow editor is cramped. *(UX-008, UX-011, UX-012, UX-038)*
**Result** ☐ ✅ ☐ ⚠ ☐ ❌ &nbsp; Note: ______________________

### T09 · Super admin: change a flow without breaking it &nbsp; ⏱ 12 min &nbsp; ⚠ mode L (on live: use a copy)

**Why.** Live flows are edited every day. One wrong click can break a chat.
**Steps**
1. **Flows** → open **Close a case with a note** (mode L) or a **copy** of a live flow (mode P: *Copy one you have*, name it "ZZ test").
2. Click **Try it**. Choose a person. Run the rehearsal. Does it say that nothing is saved?
3. Change a message text. Does an **Unsaved** tag appear? Click **Discard**. Is the change gone?
4. Change it again. Click **Save changes**. Open the **history** icon. Can you see the older version?
5. Delete a step with its `···` menu. Click **Undo** in the message.
6. Go back to **Flows**. Switch a flow **Off**, then **On**. Does anything tell you what it does?
7. Mode P only: delete your "ZZ test" copy.

**Pass if.** Every mistake can be undone, and you always know whether it is saved.
**Known today.** Switching a flow off gives **no message** and says nothing about what changes. *(UX-035)* The "Saved" button looks like a disabled button. *(UX-037)*
**Result** ☐ ✅ ☐ ⚠ ☐ ❌ &nbsp; Note: ______________________

### T10 · Admin asks a super admin for help &nbsp; ⏱ 4 min &nbsp; ✅ live-safe (sends an e-mail)

**Why.** Admins can only see three screens. This is how they get anything else done.
**Steps**
1. Sign in as an **admin** (mode L: `meena.kulkarni@ux.test`).
2. In the menu, find the box "Need a person added, or something changed?". Click **Ask a super admin**.
3. Write a clear request. Send it. What do you see after?
4. Sign in as a **super admin**. Open the **Sign-in log**, filter **Messages from admins**. Is it there, in full?

**Pass if.** The admin gets a clear "sent" message and the super admin finds the full text.
**Known today.** The words "super admin" mean nothing to a client. Suggested: "Ask OrchestrAI support". *(UX-026)*
**Result** ☐ ✅ ☐ ⚠ ☐ ❌ &nbsp; Note: ______________________

---

## 4. P1 tests: the next 45 minutes

| ID | Use case | ⏱ | Steps in short | Pass if | Known today |
|---|---|---|---|---|---|
| **T11** | **Keyboard only**: Home → Cases → Assign → close | 6 | Unplug the mouse idea: use `Tab`, `Shift+Tab`, `Enter`, `Space`, `Esc`. Open the Assign window, choose a person, close it | You can finish, always see where the focus is, and `Esc` closes the window and returns you to where you were | No "skip to content" link (15 Tab stops through the menu). Focus **leaves** the window after 5 Tab presses and does **not** return when it closes. *(UX-002, UX-003, UX-009)* |
| **T12** | **200% zoom and dark mode** on Home, Cases, People | 5 | `Ctrl` and `+` to 200%, then `Light / dark` in the menu | Nothing is cut off or unreadable | Menu group labels are too pale (2.6:1). Avatar letters 3.3:1. *(UX-007)* |
| **T13** | **Screen reader** quick look on sign-in and Add person | 8 | Windows: `Win+Ctrl+Enter` starts Narrator. Tab through the sign-in form and the Add person window | It says "Email", "Password", "Sign in"; the window announces its title; the **×** says "Close" | Labels are not tied to fields; the window has no dialog role; the **×** is read as "times". *(UX-001, UX-002)* |
| **T14** | **Slow and offline** | 5 | In `F12` → Network, choose "Slow 3G" and reload. Then choose "Offline" and click **Cases** | You see something moving while it loads; offline shows "Try again" | 12.5 s to first content on slow 3G, only the word "Loading…". *(UX-046)* Offline works. |
| **T15** | **Chat bot texts**: edit one message and see the preview | 6 | **Chat bot → Messages** → pick a text → change a word → read "How it looks to the person" → **Save**, then use **History** | You can see the change before saving and go back | Variables like `{email}` look like code but are explained in the text |
| **T16** | **Case rules**: who gets a case | 6 | **Case rules → Who gets them** → "Try it: who would get a case like this?" Then **Response times**: set Low faster than Urgent | The test names the right person; the warning appears for the odd time | "Specificity 10" on each rule is not explained. *(UX-024)* |
| **T17** | **Replace the treasurer** | 5 | **Roles & access → Seats → Change holder** (Treasurer) → pick a person → **Save holder** | The window tells you the role will change and that the old holder is kept in the history | Good today. Super admin only. |
| **T18** | **Find what someone said** | 3 | **Conversations** → search a word → click the row | The whole chat opens | Date boxes are the browser's own `dd-mm-yyyy`. *(UX-044)* |

### P2: skip for now

Changing **who approves** (needs JSON today, and the approval step crashes until QA-032 is fixed) · **creating a flow with the real AI** (needs a real AI and a real document) · **adding many people at once** (not offered) · flows with 30 or more steps.

---

## 5. Your results

Copy this table, fill it, and send it to me.

| Test | P | Result (✅ ⚠ ❌) | What you saw (one line) | Screenshot |
|---|---|---|---|---|
| T01 Sign in and out | P0 | | | |
| T02 Home | P0 | | | |
| T03 Find a case | P0 | | | |
| T04 Assign a case | P0 | | | |
| T05 Why still open | P0 | | | |
| T06 Add and link a person | P0 | | | |
| T07 Moved out | P0 | | | |
| T08 Phone | P0 | | | |
| T09 Change a flow safely | P0 | | | |
| T10 Ask a super admin | P0 | | | |
| T11 Keyboard | P1 | | | |
| T12 Zoom and dark | P1 | | | |
| T13 Screen reader | P1 | | | |
| T14 Slow and offline | P1 | | | |
| T15 Chat bot texts | P1 | | | |
| T16 Case rules | P1 | | | |
| T17 Seats | P1 | | | |
| T18 Find what someone said | P1 | | | |

**Launch bar.** All ten P0 tests are ✅ or ⚠ with a workaround you accept. A ❌ on **T04** or **T06** stops the launch for the admin screens.

---

## 6. What I fix after your results

Only what failed. In this order. Small changes, nothing redesigned (except the top of the person window).

**P0 fixes** (each under a day; about 3 days in all)

| # | Fix | From test | Audit ID |
|---|---|---|---|
| 1 | Tie every label to its field; name the flow switches | T01, T13 | UX-001, UX-006 |
| 2 | Messages (saved, deleted, errors) announced to screen readers; errors stay until closed; Undo for 15 s | T09, T13 | UX-004 |
| 3 | Name the icon-only controls in the flow editor's menu | T09, T13 | UX-005 |
| 4 | Darker menu labels and avatar colours (contrast 4.5:1) | T12 | UX-007 |
| 5 | "Skip to main content" link | T11 | UX-009 |
| 6 | A message with **Undo** when a flow is switched on or off, saying what changes | T09 | UX-035 |
| 7 | Call the status **"Moved out"** (label only) | T07 | UX-028 |
| 8 | Compress the script and styles; add frame, content and referrer headers | T14 | UX-046, UX-054 |
| 9 | A friendly page for a wrong organisation address | T01 | UX-045 |
| 10 | Plain subtitles on flow steps instead of "entity records" and "to user id" | T09 | UX-021 |

**P1 fixes** (a few days each)

| # | Fix | From test | Audit ID |
|---|---|---|---|
| 11 | A real dialog for windows: role, label, "Close", focus in and back | T11, T13 | UX-002, UX-003 |
| 12 | Phone: cards instead of cut-off tables; 44 px buttons | T08 | UX-008, UX-011, UX-012 |
| 13 | Add person: optional **wing and flat** for housing organisations | T06 | UX-027 |
| 14 | Person window: the three common jobs first ("Moved out", "Change role", "Flat"), the rest folded | T07 | UX-028, UX-029 |
| 15 | Change who approves with a small form instead of JSON (after QA-032) | P2 | UX-034 |
| 16 | The flow editor on a phone: show the hint once, collapse the problem list | T08 | UX-038 |
| 17 | "Ask OrchestrAI support" instead of "Ask a super admin" | T10 | UX-026 |

The matching code fixes for the chat bot and the server are in `docs/launch/QA-priority-work-order.md`. The two lists are independent; Claude Code can work on both.
