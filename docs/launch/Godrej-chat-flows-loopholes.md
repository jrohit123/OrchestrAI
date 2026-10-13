# Godrej Emerald — chat flows: what breaks, and why

Tested on **8 Oct 2026**, on a throw-away copy of the live Godrej data, on this computer only.
Nothing real was touched. **Nothing is fixed yet** — this is the list for you to read first.

---

## 1. In short

| | |
|---|---|
| What exists | 7 flows, 37 building blocks (27 on, 10 off), 3 prompt layers, 29 complaint categories, 2 routing rules |
| What I ran | ~45 ways of typing a case number · 16 people × 16 ways of typing a name · ~100 yes / no words · 52 complaint sentences · 27 typed commands (`/assign`, `/close`, `/update`) · ~25 flow runs end to end |
| Result | **17 loopholes**: 5 must-fix (P0), 9 should-fix (P1), 3 later (P2) |
| Do this first | **WF-01** (a permission hole, one data change, no code). Then **one shared "smart find"** for case numbers and names (WF-03 + WF-06): it fixes 5 flows at once |

**Your two examples, answered**

- `cs-08-0006` style numbers **do not work today** (WF-03). `12` alone works, `CS-26-09-00012` works, but the middle forms (`CS-26-09-12`, `cs-09-0012`, `09-12`) all say "not found".
- "Assign all unassigned cases to Anuja" **cannot work today** (WF-02). The chat bot has no way to do many cases. It shows a card as if it can, then fails after you say yes.

**On using LIKE:** plain `LIKE '%12%'` would also match 112, 120, 212. Better: split what the person typed into numbers (year, month, sequence), compare as numbers (`9 = 09`, `12 = 00012`), and use LIKE only for the part they left out. If more than one case fits, ask which one.

---

## 2. How I tested, and what I could not test

| Tested (ran it) | Tested (read the code) | **Not tested** |
|---|---|---|
| The real lookup code on real case numbers and people · the yes / no word lists · the complaint keyword sorter · the real flows end to end (assign, close, update, file a complaint) with sending switched off | How a message becomes a plan · confirm card · cancel gate · what happens after "yes" · who may do what · all 3 prompt layers | What the AI model *decides* on free text (for example how it words a bulk request). That needs a live run on Telegram. I only know what it did from your chat |

---

## 3. P0 — fix before more people use it

### WF-01 · Owners, tenants and staff can assign ANY case `P0`
- **What happens:** the roles *owner, tenant, member, staff* all have the right to use **Assign a case**. The check "are you on this case?" is skipped for anyone who has the right through their role. So they can hand any case to anyone.
- **Proof (ran it):** an owner, a tenant and a staff user each assigned a case they are **not** on. It worked and a chat message went out. Closing is safe (they were refused).
- **Also (code reading):** for these roles the case lookup is not limited to their own cases, so the card shows them the title of any case they type.
- **Today:** 2 owners are linked to Telegram, so this is possible right now.
- **Fix idea:** remove `case_pass_on` from those 4 roles. The rule "assignee / level 2 of the case may pass it on" already covers the right people. One data change, no code.

### WF-02 · "Assign all …", "close these 3", "move all of Ravi's cases to Anuja" `P0`
- **What happens:** every flow works on **one** case. There is no "for each" building block and no "find many cases" block. The AI puts the whole list into the single case field, the card looks fine, then after **yes** it fails with: `No cases record found matching 'CS-26-09-00012, CS-26-09-00008, …'` and the request is thrown away.
- **Proof (ran it):** a list of 20 numbers in the case field → not found. Two numbers (`… and …`, `… , …`) → not found.
- **Cost today:** one case = 4 messages and one yes. 16 unassigned cases = 64 messages.
- **Fix idea (my recommendation):** two new building blocks: **Find cases** (by status / person / place / date) and **Do this for each case** (with a cap, for example 25). The card says *"16 cases will go to Anuja"* with the list, ONE yes, and the answer says *"done 16, failed 0"*.

### WF-03 · Case number typed short, or without zeros `P0`
Target used: `CS-26-09-00012` (the sequence restarts every month, so `00002` exists in Sept and Oct).

| Typed | Result |
|---|---|
| exact · lowercase · spaces · no dashes · slashes · dots · `#` · phone dashes · `case no. …` | works |
| `12` · `0012` · `00012` · `#12` | works (asks which one if two months have it) |
| **`CS-26-09-12`** · `cs 26 09 12` · `CS-26-9-12` · `CS-26-09-0012` | **not found** |
| **`cs-09-12`** · **`cs-09-0012`** (your style) · **`09-12`** · `9-12` | **not found** |
| `twelve` · letter O for zero · Hindi digits | not found |
| `this case` · `the last one` · `it` | not found (no "current case" memory) |

- **Why:** the 4-step guess in `resolve_entity` (`step_interpreter.py:644-713`) compares text, and the date part and the zero-padding are glued together. The last step was meant to fix this but compares the whole digit run as one number, so it never fires for this number format.
- **Fix idea:** the "structural" rule above. One shared block, used by all 4 flows and by Check status (WF-10).

### WF-04 · Yes / no / cancel words `P0` *(same family as QA-007, QA-024)*
Tested against Godrej's own word list.

| Said to a waiting card | What the bot does |
|---|---|
| `okay` · `yeah` · `yep` · `yup` · `sure` · `done` · `do it` · `kar do` · `kardo` · `haanji` · `bilkul` · `save it` · `हाँ` · `ठीक है` · `✅` · `👌` | **not recognised as yes** |
| `👍` (it IS in the list) | **does not work**: the match rule needs a letter after it |
| `yes but make it Ravi` · `ok wait` · `ok but change the name` · `haan wait` | **executes the old card** — the change they asked for is lost |
| `no wait, make it Ravi` · `no issue` · `no problem` · `no change` · `nahi, doosra case` | **cancels the whole request** |
| `nope` · `nah` · `don't` · `do not save` · `not now` · `mat karo` · `❌` · `👎` · `नहीं` | not recognised as no |
| `don't cancel` · `please cancel` (cancel gate) | **wipes the request** (the opposite of what was said) |

- **Why it hurts:** a word that is not recognised is treated as "a change request" and sent to the AI. After 3 such tries the request is wiped and they start over (by code reading, `webhook.py:1431-1480`, `reprompt_max = 3`; not run).
- **Fix idea:** whole-message match for yes / no (plus a short list with `okay, yeah, sure, kar do, ✅, 👍…`); if a yes-word is followed by more words, **do not execute**: ask "Do you want to save as shown, or change it?". Fix the emoji match. Cancel gate: ignore negations.

### WF-05 · Complaint sorting and routing `P0`
**Sorting by keywords** (52 realistic complaints, English + Hinglish):

| Problem | Examples |
|---|---|
| **Not sorted** (10 of 52) | `paani nahi aa raha` · `kachra nahi uthaya` · `dogs barking all night` · `cracks in the wall` · `paint peeling` · `fire extinguisher expired` · `neighbour playing loud music` · `children play area swing broken` · `plastering needed` · `maintenance bill` |
| **Wrong place** | `dustbin overflowing` → Plumbing (word *overflow*) · `car blocking my way` → Plumbing (*block*) · `noise from the construction` → Lift (*noise*) · `terrace door lock broken` → Lift (*door*) |
| **Urgent sub-category missed** | `electric shock from switch` → plain Electrical · `lift me log fase hain` → plain Lift |
| No Hindi words at all | paani, pani, kachra, bijli, safai, ganda, shor, kutta, gaadi… |

**Who gets it** (ran `route_case` for all 29 categories): only **8 of 29** name a person (Lift + 3 sub, Plumbing + 3 sub). The other 21 — Electrical, Housekeeping, Security, Parking, Common areas, *Something else* — **start with nobody**. (The 16 open cases with no owner today are all from September, before sorting existed. From now on every complaint in those 21 categories will start the same way.)

- **What the resident sees:** `Category: not sorted yet · Handled by: not assigned yet`. A wrongly sorted complaint goes to the wrong person (the "dustbin" one went to the plumbing handler).
- **Same complaint twice = two cases** (ran it). There is no duplicate check.
- **Fix idea:** (1) add Hindi/Hinglish words; (2) when nothing matches, show 5–6 category buttons instead of "not sorted"; (3) the more specific word wins (*dustbin* beats *overflow*); (4) a handler for every category, with a fallback person for anything unsorted; (5) kinder words for the resident. **(4) needs your input: who handles what.**

---

## 4. P1 — should fix

| ID | Scenario | What happens (proof) | Fix idea |
|---|---|---|---|
| **WF-06** | **Person typed in a different way** | Ran 16 people × 16 forms. Found: full name, first name, UPPER, lower, `Name S`, double space. **Not found:** `Anuja ji` · `Anuja madam` · `Ms. Anuja` · `@anuja` · `AnujaSinkar`. **Typos: no typo form found the right person**, and one typo matched a **different person**. A last name shared by 3 people: on the AI path the bot asks *after* "yes", lists names, and says "reply with the full number". `nobody` / `unassign` → not found. On the typed-command path `assign to me`, `my self`, `mere naam` → not found (only the one word `me`, `myself`, `self`, `mujhe`, `khud`, `mera`, `apne aap` works) | Strip ji / sir / madam / Mr / Ms / @; if no exact hit, offer "Did you mean Anuja Sinkar?" (never accept a fuzzy hit silently); ask which one **before** the card, with numbers; add `unassign` |
| **WF-07** | **Closed case, or same person again** | Ran it: **assign a closed case works**, no warning, a chat message goes out. **Close an already closed case works** (note `done`, everyone told again). **Update on a closed case works.** Assign to the same person: they become assignee **and** helper on their own case | Add a "stop if the case is closed" check to Assign and Close; "already with Anuja" instead of redoing; ask first for Update on closed; add a **Reopen** flow |
| **WF-08** | **Assign to someone who is not on Telegram** | Ran it: success message, but the new person gets nothing. **10 of 16** active people are not linked (committee 0/2, staff 0/2). 1 open case is with such a person right now | Warn on the card: "Amit is not on Telegram, they will not be told. Continue?" |
| **WF-09** | **Typed answers swallow anything** | While the bot waits for a typed answer (closing note, update note, problem title, place), `menu` · `help` · `hi` · `show my cases` · `wait which case is this?` · `.` are **saved as the answer** (ran it). The rule "do not accept *done / fixed* as a closing note" exists only in the AI prompt; the code path accepts `done`, `ok`, `yes`, `no`. In `/assign 12 13 anuja` the second case becomes the **note**; same for `all`, `Ms`, a second person | If it looks like a command or question, answer it first and ask again; reject one-word closing notes; if the leftover looks like a case or a name, ask |
| **WF-10** | **Check status by number** | The stored report uses exact match: `CS-26-09-00012` works, `cs260900012`, `12`, `CS-26-09-12` give **0 rows**, yet the field says "any format is accepted" (ran it) | Use the same smart find as WF-03 |
| **WF-11** | **Questions about the cases** | "All Cases" returns **20 of 32** and says nothing about the rest (stored `LIMIT 20`; same for My cases). Every other question (unassigned, open, urgent, overdue, by person, by wing, by date, how many) is SQL written fresh by the AI each time: different wording and different answers each time | Build ~6 stored, parameterised reports (status / person / priority / overdue / place / date range / part of a case number, using LIKE); say "showing 20 of 32, say *more*" |
| **WF-12** | **Follow-ups ("the next one", "same for 13", "this case")** | The bot remembers only the last **12 messages**. One assign = 4 messages, so after ~3 cases it forgets the list. No "current case" memory | Keep "the last list I showed" and "the current case" as a small saved note per person |
| **WF-13** | **The card and the messages** | The AI-made card shows only `Case: CS-…` — no title, not who has it now. The done message repeats what was **typed** (`now with Anuja`), not the real full name. Errors read like a database: `No cases record found matching '…'` / `No users record found matching 'Anuja ji'`; the whole input is echoed back. After **any** error the request is thrown away and must be typed again. An ambiguous name is found only after yes and the draft is dropped (read, not run) | Build every card from code: `Case CS-26-09-00012 — Lift stuck (now with Ravi) → Anuja Sinkar`; plain error words; keep the request after "not found" and ask again |
| **WF-14** | **Missing flows, unused blocks** | No flow can **change status** (only *reported* and *closed* ever exist: `under_review`, `action_taken` are unreachable), **change priority**, **reopen**, **unassign**, **add a watcher or level 2**, or **withdraw a complaint**. **8 blocks are on but used by nobody**: `case_save_status`, `case_record_status`, `case_clear_closed_time`, `case_stamp_closed_time`, `case_save_priority`, `case_record_priority`, `case_due_from_new_priority`, `case_tell_assignee` | Build *Change status* and *Change priority* from the blocks already there; add Reopen / Unassign |

---

## 5. P2 — later

| ID | Scenario | Note |
|---|---|---|
| **WF-15** | **Phrases the AI matches on** | See the table below. English only (except *All Cases*). Hinglish works only if the AI guesses it. "update on 12" can mean *ask* or *add a note* |
| **WF-16** | **Clean-up** | 10 switched-off "(replaced)" blocks; `case_tell_assignee` is marked "old, unused" but is on; `retry_words` is missing from the word list; `/mystatus` asks "Which case?" although the name sounds like "my status" |
| **WF-17** | **Too many messages** | Every update goes to everyone on the case. There is no private note |

**Phrases per flow (what is there, what is missing)**

| Flow | Has | Missing |
|---|---|---|
| Assign | assign / give / hand over / pass on / "assign to myself" | transfer · reassign · forward · allot · *kisko de do* · *ko assign karo* · "to me" |
| Close | close / resolve / mark closed / "issue is fixed" | solved · completed · *band karo* · *case khatam* |
| Add update | comment / add a note / update case / remark | "work started" · "plumber visited" · *update daalo* · *note likho* |
| Check status | 8 long English sentences | short forms: `status 12` · `12?` · *kya hua 12 ka* |
| File complaint | register / file / report an issue / new complaint | "there is a leak", "lift stuck" with no verb (only the glossary has these) |
| My cases | my cases / cases I am on / what is with me | *meri complaints* · "cases assigned to me" (the glossary says one thing, this report another) |
| All cases | 10 phrases incl. Hindi | fine |

---

## 6. Decisions I need from you

| # | Question | My recommendation |
|---|---|---|
| 1 | Should owners / tenants / staff be able to assign cases? (WF-01) | **No.** Remove it from those 4 roles |
| 2 | Bulk: how many cases at most in one go? (WF-02) | **25**, always with a preview and one yes |
| 3 | Who handles each of the 21 categories with nobody? (WF-05) | You tell me; plus one fallback person for "not sorted" |
| 4 | Assigning to a person who is not on Telegram: warn or refuse? (WF-08) | **Warn**, let the admin continue |
| 5 | Closed cases: assign / close again / update? (WF-07) | Block assign and close; allow update after a warning; add **Reopen** |
| 6 | Hindi words: do you want me to propose the list, you check it? (WF-05, WF-15) | **Yes** — I write, you check |

---

## 7. Order I suggest

1. **WF-01** — one data change, no code, closes the only security hole.
2. **Smart find** (WF-03 + WF-06 + WF-10) — one shared block; fixes Assign, Close, Update and Check status together.
3. **Words** (WF-04) — small, safe, and every person feels it.
4. **Bulk** (WF-02) — new blocks; needs decision 2.
5. **Complaint sorting and routing** (WF-05) — needs decision 3 and the Hindi list.
6. Then P1 in the order of the table.

I will not change anything until you say. When you approve, I turn the test scripts into permanent tests, so each fix is proven and stays fixed.
