# The dashboard sign-in: how it works and how to look after it

Plain words. Everything here is about who may open the dashboard. The chat bots (Telegram and
WhatsApp) never use this sign-in.

## The two levels

| | Super admin | Admin |
|---|---|---|
| Signs in at | `/admin` (or any organisation's address) | their organisation's address, like `/admin/godrej` |
| Sign-in | email + password + a 6-digit code sent by email, every time | email + password |
| Can open | every organisation, all screens | only the organisations listed on the account: Home, Cases (and Assign), People (and change a role) |
| Can do | add people, give or take access, switch accounts off, edit flows, rules, roles, settings | assign a case, change a role (not their own), ask a super admin |

Sign up is only for people a super admin already added. Nobody can create an account by themselves.

## Where things live

- Three tables in the **routing database** (file `migrations/control/control-0001_panel_login.sql`):
  `panel_accounts` (who may sign in), `panel_keys` (signed-in browsers and emailed codes, only as
  hashes) and `panel_audit` (a log). Godrej's and Baanganga's databases are not touched.
- A password is kept only as a slow hash. Nobody, including us, can read it back.
- The rules (5 wrong tries lock an account for 15 minutes, a code works for 10 minutes and 5 tries,
  a session ends after 12 hours unused for an admin and 4 for a super admin) are constants at the top
  of `app/admin_panel/auth.py`.
- Which calls an admin may make is the list in `app/admin_panel/access_rules.py`. Everything not on
  it is for super admins only. `tests/test_panel_login.py` fails if a call is on neither list.
- The Assign button runs the flow named in `orgs.settings.case_buttons.assign` (Godrej:
  `case_pass_on`, "Assign a case"), as the signed-in person's own record, found by email. It works
  only while that flow is switched on under Flows. A dashboard account's email must be the same as the
  person's email under People, or Assign says so.

## Everyday jobs (all from the dashboard)

- **Give someone dashboard access:** open the organisation, People, the person, "Give dashboard
  access". They get an email, open the address, choose Sign up, type the code, choose a password.
  Or, on the super admin page: Dashboard access, Give access.
- **Take it away, switch an account off, sign someone out everywhere:** Dashboard access, the
  three dots on their row. Switching off works on their very next click.
- **Add a super admin:** Dashboard access, Add a super admin.
- **See what happened:** Sign-in log (every sign-in, failure, lock, sign-up, change of access).

## When something goes wrong (SQL for Railway's query box on the routing database)

Look at the last 50 events:

```sql
SELECT at, email, action, ok, detail, ip FROM panel_audit ORDER BY id DESC LIMIT 50;
```

Unlock an account now (it also opens by itself after 15 minutes):

```sql
UPDATE panel_accounts SET wrong_tries = 0, locked_until = NULL WHERE email = 'name@example.com';
```

Someone lost their password: they choose "Forgot password?" on the sign-in page and use the code
sent to their email. If their email no longer works, put them back to "invited" so they can sign up
again with a new address (the address must still be the one on their People record):

```sql
UPDATE panel_accounts SET status = 'invited', password_hash = NULL, email = 'new@example.com'
 WHERE email = 'old@example.com';
DELETE FROM panel_keys WHERE account_id = (SELECT id FROM panel_accounts WHERE email = 'new@example.com');
```

Add the very first super admins (before anyone can sign in), then each person uses Sign up:

```sql
INSERT INTO panel_accounts (email, name, level, status)
VALUES ('first@example.com', 'First Name', 'super', 'invited'),
       ('second@example.com', 'Second Name', 'super', 'invited');
```

Emails must be written in small letters. A super admin has no organisation list.

Sign everyone out at once (for example after losing a laptop):

```sql
DELETE FROM panel_keys WHERE kind = 'session';
```

## The way back

The dashboard sign-in is part of the app. If it ever has to go, redeploy the deployment from before
it (on Railway: Deployments, the earlier one, Redeploy). The dashboard is then open again as it was.
The three tables stay and do no harm. The nightly cleanup (03:40) removes only codes and sessions
that have ended; accounts and the log are never removed.
