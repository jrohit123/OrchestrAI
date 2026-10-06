# Run the database changes by hand

You paste one step at a time into the SQL box of the database in Railway (the same place where you ran
`godrej_006` and the other loose files) and look at what comes back. No tool needed.
**Claude never runs these. You do.**

Every step is **safe to run twice**: it only adds things, or does nothing when they are already there.
The SQL comes straight from the files in `migrations/`. Every step was first run on practice copies of
both databases, and they ended exactly like the migration tool's result. (The same changes with the
migration tool are in `docs/runbook-migrations.md`. Either way works; this file is the by-hand way.)

| | Database | Steps | What changes |
|---|---|---|---|
| [Part 1](#part-1-baanganga) | Baanganga | 9 | adds columns, indexes and tables. Nothing that exists is changed |
| [Part 2](#part-2-godrej) | Godrej | 9 | the same kind of additions, and in step 9 the building blocks |
| | routing database | none | nothing to run |

## Rules

1. One database at a time, and the steps in order. Check the database name first (step 0).
2. Copy the whole block. A step that changes something starts with `SET lock_timeout = '5s';`: that line
   makes it give up after 5 seconds if a table is busy, so your app can never be made to wait.
3. If a step shows an error, **stop**. Copy the message and send it to Claude. Do not paste the next
   step. Pasting the same step again is always safe.
4. `canceling statement due to lock timeout` is not a problem: the table was busy, the step gave up on
   purpose and changed nothing. Wait a minute and paste the same step again.

## Before you start

**Back up. Never skip.** By hand, this backup is the only way back. In PowerShell:

```powershell
cd "D:\Orchestrator AI"
$railway = "$env:APPDATA\npm\railway.cmd"
& $railway run python -m tools.backup --allow-remote
```

You should see three `saved:` lines and no `PROBLEM`. If any database is not saved, do not go on.
Pick a quiet time. Nothing here needs the app to stop.


## Part 1: Baanganga

Open the SQL box of the **Baanganga** database in Railway.

### Step 0: are you in the right database? (changes nothing)

```sql
SELECT name, industry FROM orgs;
```

**You should see:** one row, `Baanganga Gold And Diamond (I) Ltd.` and `jewellery`. Anything else: stop.

### Step 1 of 9: the columns Baanganga was missing, and the activity table

From `core-0001_align`. Adds 7 columns, 3 rules about what kind a workflow can be, and a new table `admin_events` (who changed what on the dashboard). After this, Baanganga's dashboard shows an Activity log. Nothing that exists is changed.

```sql
SET lock_timeout = '5s';

-- Baanganga was missing these columns (Godrej has them) -------------------------------
ALTER TABLE public.user_drafts       ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.workflows         ADD COLUMN IF NOT EXISTS kind       text        NOT NULL DEFAULT 'workflow';
ALTER TABLE public.workflows         ADD COLUMN IF NOT EXISTS settings   jsonb       NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.workflow_drafts   ADD COLUMN IF NOT EXISTS kind       text        NOT NULL DEFAULT 'workflow';
ALTER TABLE public.workflow_drafts   ADD COLUMN IF NOT EXISTS settings   jsonb       NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.workflow_versions ADD COLUMN IF NOT EXISTS kind       text;
ALTER TABLE public.workflow_versions ADD COLUMN IF NOT EXISTS settings   jsonb;

-- Godrej was missing this column (Baanganga has it; the app does not read it) ----------
ALTER TABLE public.scheduled_reports ADD COLUMN IF NOT EXISTS source_key varchar(255) DEFAULT 'platform';

-- The allowed values of "kind" (Godrej already has these three rules). Existing rows all
-- carry the default 'workflow', so they pass. ------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'workflows_kind_check'
                     AND conrelid = 'public.workflows'::regclass) THEN
        ALTER TABLE public.workflows ADD CONSTRAINT workflows_kind_check
            CHECK (kind IN ('workflow', 'block', 'case_action'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'workflow_drafts_kind_check'
                     AND conrelid = 'public.workflow_drafts'::regclass) THEN
        ALTER TABLE public.workflow_drafts ADD CONSTRAINT workflow_drafts_kind_check
            CHECK (kind IN ('workflow', 'block', 'case_action'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'workflow_versions_kind_check'
                     AND conrelid = 'public.workflow_versions'::regclass) THEN
        ALTER TABLE public.workflow_versions ADD CONSTRAINT workflow_versions_kind_check
            CHECK (kind IS NULL OR kind IN ('workflow', 'block', 'case_action'));
    END IF;
END $$;

-- The dashboard's "who changed what" log. Godrej has it, Baanganga did not. Once it
-- exists, Baanganga's dashboard starts showing its Activity log (the dashboard checks
-- whether this table is there). Same columns, keys and indexes as Godrej. --------------
CREATE TABLE IF NOT EXISTS public.admin_events (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    actor_user_id uuid REFERENCES public.users (id) ON DELETE SET NULL,
    actor_label   text,
    area          text NOT NULL,
    action        text NOT NULL,
    target_type   text,
    target_id     text,
    summary       text NOT NULL,
    before_state  jsonb,
    after_state   jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_admin_events_org_time ON public.admin_events (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_events_target   ON public.admin_events (org_id, target_type, target_id);
COMMENT ON TABLE public.admin_events IS 'Who changed what in the admin dashboard. Chat turns are in audit_log.';
```

**You should see:** No error.

### Step 2 of 9: the missing indexes

From `core-0002_align_indexes`. Adds 15 indexes. An index only makes searches faster. The tables are tiny, so this takes a moment.

```sql
SET lock_timeout = '5s';

CREATE INDEX IF NOT EXISTS idx_otp_org                   ON public.otp_tokens (org_id);
CREATE INDEX IF NOT EXISTS idx_otp_user_expiry           ON public.otp_tokens (user_id, expires_at);

CREATE INDEX IF NOT EXISTS idx_approvals_org_requester   ON public.pending_approvals (org_id, requester_id);
CREATE INDEX IF NOT EXISTS idx_approvals_org_status      ON public.pending_approvals (org_id, status);

CREATE INDEX IF NOT EXISTS idx_scheduled_reports_next_run ON public.scheduled_reports (next_run_at, is_active);
CREATE INDEX IF NOT EXISTS idx_scheduled_reports_org     ON public.scheduled_reports (org_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_reports_user    ON public.scheduled_reports (user_id);

CREATE INDEX IF NOT EXISTS idx_user_drafts_expiry        ON public.user_drafts (expires_at)
    WHERE stage NOT IN ('done', 'cancelled');

CREATE INDEX IF NOT EXISTS idx_users_org_id              ON public.users (org_id);
CREATE INDEX IF NOT EXISTS idx_users_phone               ON public.users (phone);

CREATE INDEX IF NOT EXISTS idx_workflow_drafts_org_status  ON public.workflow_drafts (org_id, status);
CREATE INDEX IF NOT EXISTS idx_workflow_drafts_org_updated ON public.workflow_drafts (org_id, updated_at);

CREATE INDEX IF NOT EXISTS idx_workflows_org_intent      ON public.workflows (org_id, intent_key);
CREATE INDEX IF NOT EXISTS idx_workflows_org_kind        ON public.workflows (org_id, kind, is_active);
CREATE INDEX IF NOT EXISTS idx_workflows_org_type        ON public.workflows (org_id, workflow_type, is_active);
```

**You should see:** No error.

### Step 3 of 9: check (changes nothing)

From `core-0003_baseline_check`. Looks that steps 1 and 2 left nothing out. If something is missing it stops and lists it.

```sql
DO $$
DECLARE
    item    record;
    missing text[] := ARRAY[]::text[];
BEGIN
    FOR item IN
        SELECT * FROM (VALUES
            ('user_drafts', 'created_at'),
            ('workflows', 'kind'), ('workflows', 'settings'),
            ('workflow_drafts', 'kind'), ('workflow_drafts', 'settings'),
            ('workflow_versions', 'kind'), ('workflow_versions', 'settings'),
            ('scheduled_reports', 'source_key')
        ) AS c (tbl, col)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public'
                         AND table_name = item.tbl AND column_name = item.col) THEN
            missing := missing || ('column ' || item.tbl || '.' || item.col);
        END IF;
    END LOOP;

    FOR item IN
        SELECT * FROM (VALUES
            ('workflows', 'workflows_kind_check'),
            ('workflow_drafts', 'workflow_drafts_kind_check'),
            ('workflow_versions', 'workflow_versions_kind_check')
        ) AS k (tbl, name)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = item.name
                         AND conrelid = ('public.' || item.tbl)::regclass) THEN
            missing := missing || ('rule ' || item.name);
        END IF;
    END LOOP;

    IF to_regclass('public.admin_events') IS NULL THEN
        missing := missing || 'table admin_events'::text;
    END IF;

    FOR item IN
        SELECT * FROM (VALUES
            ('idx_otp_org'), ('idx_otp_user_expiry'),
            ('idx_approvals_org_requester'), ('idx_approvals_org_status'),
            ('idx_scheduled_reports_next_run'), ('idx_scheduled_reports_org'),
            ('idx_scheduled_reports_user'), ('idx_user_drafts_expiry'),
            ('idx_users_org_id'), ('idx_users_phone'),
            ('idx_workflow_drafts_org_status'), ('idx_workflow_drafts_org_updated'),
            ('idx_workflows_org_intent'), ('idx_workflows_org_kind'), ('idx_workflows_org_type'),
            ('idx_admin_events_org_time'), ('idx_admin_events_target')
        ) AS i (name)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_index x
                       JOIN pg_class c ON c.oid = x.indexrelid
                       JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname = 'public' AND c.relname = item.name AND x.indisvalid) THEN
            missing := missing || ('index ' || item.name);
        END IF;
    END LOOP;

    IF cardinality(missing) > 0 THEN
        RAISE EXCEPTION 'baseline check failed, missing: %', array_to_string(missing, ', ');
    END IF;
END $$;
```

**You should see:** No error. If you see `baseline check failed, missing: ...`, send me that line and stop.

### Step 4 of 9: one draft rule, made the same as Godrej's

From `core-0005_fix_draft_index`. Replaces one index, in one go, so a new draft no longer starts with the answers of an old closed one.

```sql
SET lock_timeout = '5s';

DO $$
DECLARE
    counts_every_draft boolean;
BEGIN
    -- true: the old "every draft" index; false: already the open-drafts-only one;
    -- null: no such index at all.
    SELECT i.indpred IS NULL INTO counts_every_draft
    FROM pg_index i
    WHERE i.indexrelid = to_regclass('public.one_active_draft_per_user');

    IF counts_every_draft IS TRUE THEN
        DROP INDEX public.one_active_draft_per_user;
    END IF;
    IF counts_every_draft IS NOT FALSE THEN
        CREATE UNIQUE INDEX one_active_draft_per_user
            ON public.user_drafts (org_id, user_id)
            WHERE stage NOT IN ('done', 'cancelled');
    END IF;
END $$;
```

**You should see:** No error.

### Step 5 of 9: an index on the chat log (1 of 2)

From `core-0006_audit_log_session_index`. Opening one chat on the dashboard gets faster.

```sql
SET lock_timeout = '5s';

CREATE INDEX IF NOT EXISTS idx_audit_log_session
    ON public.audit_log (session_id, created_at);
```

**You should see:** No error.

### Step 6 of 9: an index on the chat log (2 of 2)

From `core-0007_audit_log_intent_index`. The Workflows screen's "Last used" column gets faster.

```sql
SET lock_timeout = '5s';

CREATE INDEX IF NOT EXISTS idx_audit_log_intent
    ON public.audit_log (org_id, intent_key, created_at);
```

**You should see:** No error.

### Step 7 of 9: close drafts of removed workflows

From `core-0008_cancel_orphan_drafts`. Cancels half-finished drafts whose workflow was removed. Nothing is deleted. On the practice copy it matched no row, so it changes nothing today.

```sql
SET lock_timeout = '5s';

UPDATE public.user_drafts d
SET stage = 'cancelled', updated_at = now(), expires_at = now()
WHERE d.stage NOT IN ('done', 'cancelled')
  AND NOT EXISTS (SELECT 1 FROM public.workflows w
                  WHERE w.org_id = d.org_id AND w.intent_key = d.intent_key);

UPDATE public.workflow_drafts
SET status = 'abandoned', updated_at = now()
WHERE status = 'published' AND published_workflow_id IS NULL;
```

**You should see:** No error.

### Step 8 of 9: places for settings, messages and AI instructions

From `core-0009_settings_foundation`. Adds 2 columns on `orgs` (time zone and language, already set to what the app uses today) and 2 empty tables where message texts and AI instructions will be kept. With empty tables the app uses its built-in text, so nothing changes.

```sql
SET lock_timeout = '5s';

ALTER TABLE public.orgs ADD COLUMN IF NOT EXISTS timezone text NOT NULL DEFAULT 'Asia/Kolkata';
ALTER TABLE public.orgs ADD COLUMN IF NOT EXISTS locale   text NOT NULL DEFAULT 'en-IN';

CREATE TABLE IF NOT EXISTS public.prompts (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key        text NOT NULL,
    scope      text NOT NULL DEFAULT 'tenant' CHECK (scope IN ('global', 'pack', 'tenant')),
    scope_ref  text NOT NULL DEFAULT '',
    version    integer NOT NULL CHECK (version >= 1),
    body       text NOT NULL,
    variables  jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_active  boolean NOT NULL DEFAULT true,
    note       text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text,
    UNIQUE (key, scope, scope_ref, version)
);

CREATE INDEX IF NOT EXISTS idx_prompts_lookup
    ON public.prompts (key, scope, scope_ref, version DESC) WHERE is_active;

CREATE TABLE IF NOT EXISTS public.system_messages (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key        text NOT NULL,
    locale     text NOT NULL DEFAULT 'en-IN',
    scope      text NOT NULL DEFAULT 'tenant' CHECK (scope IN ('global', 'pack', 'tenant')),
    scope_ref  text NOT NULL DEFAULT '',
    version    integer NOT NULL CHECK (version >= 1),
    body       text NOT NULL,
    variables  jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_active  boolean NOT NULL DEFAULT true,
    note       text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text,
    UNIQUE (key, locale, scope, scope_ref, version)
);

CREATE INDEX IF NOT EXISTS idx_system_messages_lookup
    ON public.system_messages (key, locale, scope, scope_ref, version DESC) WHERE is_active;
```

**You should see:** No error.

### Step 9 of 9: a place for the nightly cleanup's copies

From `core-0010_archived_rows`. Adds one empty table, `archived_rows`. The nightly cleanup keeps a copy of every row it removes there. Nothing writes to it until the new app is live.

```sql
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.archived_rows (
    id           bigserial PRIMARY KEY,
    source_table text NOT NULL,
    row_id       text,
    org_id       uuid,
    row_data     jsonb NOT NULL,
    reason       text,
    archived_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_archived_rows_age
    ON public.archived_rows (org_id, archived_at);
CREATE INDEX IF NOT EXISTS idx_archived_rows_source
    ON public.archived_rows (source_table, archived_at);
```

**You should see:** No error.

### Final check for Baanganga (changes nothing)

```sql
SELECT
  to_regclass('public.admin_events')          IS NOT NULL AS admin_events,
  to_regclass('public.prompts')               IS NOT NULL AS prompts,
  to_regclass('public.system_messages')       IS NOT NULL AS system_messages,
  to_regclass('public.archived_rows')         IS NOT NULL AS archived_rows,
  to_regclass('public.idx_audit_log_session') IS NOT NULL AS chat_index_1,
  to_regclass('public.idx_audit_log_intent')  IS NOT NULL AS chat_index_2,
  EXISTS (SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'orgs' AND column_name = 'timezone') AS orgs_timezone,
  EXISTS (SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'orgs' AND column_name = 'locale')   AS orgs_locale;
```

**You should see:** one row with 8 columns, all `true` (or `t`). A `false` means a step was missed: send me the row.


## Part 2: Godrej

Open the SQL box of the **Godrej** database in Railway.

Two files from Part 1 are not here, `core-0002` and `core-0005`: Godrej already has what they add (step 2 checks this). Steps 1 to 7 only add things (step 5 can also cancel half-finished drafts of removed workflows; on my practice copy there were none). Step 8 takes two unused labels off some roles. **Step 9 changes how Godrej's case flows are built.** You can stop after step 8 and do step 9 another day.

### Step 0: are you in the right database? (changes nothing)

```sql
SELECT name, industry FROM orgs;
```

**You should see:** one row, `Godrej Emerald` and `housing_society`. Anything else: stop.

### Step 1 of 9: one missing column

From `core-0001_align`. Godrej already has everything in this file except one column, `scheduled_reports.source_key`, which this adds. The rest does nothing here.

```sql
SET lock_timeout = '5s';

-- Baanganga was missing these columns (Godrej has them) -------------------------------
ALTER TABLE public.user_drafts       ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.workflows         ADD COLUMN IF NOT EXISTS kind       text        NOT NULL DEFAULT 'workflow';
ALTER TABLE public.workflows         ADD COLUMN IF NOT EXISTS settings   jsonb       NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.workflow_drafts   ADD COLUMN IF NOT EXISTS kind       text        NOT NULL DEFAULT 'workflow';
ALTER TABLE public.workflow_drafts   ADD COLUMN IF NOT EXISTS settings   jsonb       NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.workflow_versions ADD COLUMN IF NOT EXISTS kind       text;
ALTER TABLE public.workflow_versions ADD COLUMN IF NOT EXISTS settings   jsonb;

-- Godrej was missing this column (Baanganga has it; the app does not read it) ----------
ALTER TABLE public.scheduled_reports ADD COLUMN IF NOT EXISTS source_key varchar(255) DEFAULT 'platform';

-- The allowed values of "kind" (Godrej already has these three rules). Existing rows all
-- carry the default 'workflow', so they pass. ------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'workflows_kind_check'
                     AND conrelid = 'public.workflows'::regclass) THEN
        ALTER TABLE public.workflows ADD CONSTRAINT workflows_kind_check
            CHECK (kind IN ('workflow', 'block', 'case_action'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'workflow_drafts_kind_check'
                     AND conrelid = 'public.workflow_drafts'::regclass) THEN
        ALTER TABLE public.workflow_drafts ADD CONSTRAINT workflow_drafts_kind_check
            CHECK (kind IN ('workflow', 'block', 'case_action'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'workflow_versions_kind_check'
                     AND conrelid = 'public.workflow_versions'::regclass) THEN
        ALTER TABLE public.workflow_versions ADD CONSTRAINT workflow_versions_kind_check
            CHECK (kind IS NULL OR kind IN ('workflow', 'block', 'case_action'));
    END IF;
END $$;

-- The dashboard's "who changed what" log. Godrej has it, Baanganga did not. Once it
-- exists, Baanganga's dashboard starts showing its Activity log (the dashboard checks
-- whether this table is there). Same columns, keys and indexes as Godrej. --------------
CREATE TABLE IF NOT EXISTS public.admin_events (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    actor_user_id uuid REFERENCES public.users (id) ON DELETE SET NULL,
    actor_label   text,
    area          text NOT NULL,
    action        text NOT NULL,
    target_type   text,
    target_id     text,
    summary       text NOT NULL,
    before_state  jsonb,
    after_state   jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_admin_events_org_time ON public.admin_events (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_events_target   ON public.admin_events (org_id, target_type, target_id);
COMMENT ON TABLE public.admin_events IS 'Who changed what in the admin dashboard. Chat turns are in audit_log.';
```

**You should see:** No error.

### Step 2 of 9: check (changes nothing)

From `core-0003_baseline_check`. Looks that Godrej has every column, rule, table and index the files in Part 1 add. If something is missing it stops and lists it.

```sql
DO $$
DECLARE
    item    record;
    missing text[] := ARRAY[]::text[];
BEGIN
    FOR item IN
        SELECT * FROM (VALUES
            ('user_drafts', 'created_at'),
            ('workflows', 'kind'), ('workflows', 'settings'),
            ('workflow_drafts', 'kind'), ('workflow_drafts', 'settings'),
            ('workflow_versions', 'kind'), ('workflow_versions', 'settings'),
            ('scheduled_reports', 'source_key')
        ) AS c (tbl, col)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public'
                         AND table_name = item.tbl AND column_name = item.col) THEN
            missing := missing || ('column ' || item.tbl || '.' || item.col);
        END IF;
    END LOOP;

    FOR item IN
        SELECT * FROM (VALUES
            ('workflows', 'workflows_kind_check'),
            ('workflow_drafts', 'workflow_drafts_kind_check'),
            ('workflow_versions', 'workflow_versions_kind_check')
        ) AS k (tbl, name)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = item.name
                         AND conrelid = ('public.' || item.tbl)::regclass) THEN
            missing := missing || ('rule ' || item.name);
        END IF;
    END LOOP;

    IF to_regclass('public.admin_events') IS NULL THEN
        missing := missing || 'table admin_events'::text;
    END IF;

    FOR item IN
        SELECT * FROM (VALUES
            ('idx_otp_org'), ('idx_otp_user_expiry'),
            ('idx_approvals_org_requester'), ('idx_approvals_org_status'),
            ('idx_scheduled_reports_next_run'), ('idx_scheduled_reports_org'),
            ('idx_scheduled_reports_user'), ('idx_user_drafts_expiry'),
            ('idx_users_org_id'), ('idx_users_phone'),
            ('idx_workflow_drafts_org_status'), ('idx_workflow_drafts_org_updated'),
            ('idx_workflows_org_intent'), ('idx_workflows_org_kind'), ('idx_workflows_org_type'),
            ('idx_admin_events_org_time'), ('idx_admin_events_target')
        ) AS i (name)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_index x
                       JOIN pg_class c ON c.oid = x.indexrelid
                       JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname = 'public' AND c.relname = item.name AND x.indisvalid) THEN
            missing := missing || ('index ' || item.name);
        END IF;
    END LOOP;

    IF cardinality(missing) > 0 THEN
        RAISE EXCEPTION 'baseline check failed, missing: %', array_to_string(missing, ', ');
    END IF;
END $$;
```

**You should see:** No error. If you see `baseline check failed, missing: ...`, send me that line and stop.

### Step 3 of 9: an index on the chat log (1 of 2)

From `core-0006_audit_log_session_index`. Opening one chat on the dashboard gets faster.

```sql
SET lock_timeout = '5s';

CREATE INDEX IF NOT EXISTS idx_audit_log_session
    ON public.audit_log (session_id, created_at);
```

**You should see:** No error.

### Step 4 of 9: an index on the chat log (2 of 2)

From `core-0007_audit_log_intent_index`. The Workflows screen's "Last used" column gets faster.

```sql
SET lock_timeout = '5s';

CREATE INDEX IF NOT EXISTS idx_audit_log_intent
    ON public.audit_log (org_id, intent_key, created_at);
```

**You should see:** No error.

### Step 5 of 9: close drafts of removed workflows

From `core-0008_cancel_orphan_drafts`. Cancels half-finished drafts whose workflow was removed. Nothing is deleted. On the practice copy it matched no row.

```sql
SET lock_timeout = '5s';

UPDATE public.user_drafts d
SET stage = 'cancelled', updated_at = now(), expires_at = now()
WHERE d.stage NOT IN ('done', 'cancelled')
  AND NOT EXISTS (SELECT 1 FROM public.workflows w
                  WHERE w.org_id = d.org_id AND w.intent_key = d.intent_key);

UPDATE public.workflow_drafts
SET status = 'abandoned', updated_at = now()
WHERE status = 'published' AND published_workflow_id IS NULL;
```

**You should see:** No error.

### Step 6 of 9: places for settings, messages and AI instructions

From `core-0009_settings_foundation`. Adds 2 columns on `orgs` (time zone and language, already set to what the app uses today) and 2 empty tables where message texts and AI instructions will be kept. With empty tables the app uses its built-in text, so nothing changes.

```sql
SET lock_timeout = '5s';

ALTER TABLE public.orgs ADD COLUMN IF NOT EXISTS timezone text NOT NULL DEFAULT 'Asia/Kolkata';
ALTER TABLE public.orgs ADD COLUMN IF NOT EXISTS locale   text NOT NULL DEFAULT 'en-IN';

CREATE TABLE IF NOT EXISTS public.prompts (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key        text NOT NULL,
    scope      text NOT NULL DEFAULT 'tenant' CHECK (scope IN ('global', 'pack', 'tenant')),
    scope_ref  text NOT NULL DEFAULT '',
    version    integer NOT NULL CHECK (version >= 1),
    body       text NOT NULL,
    variables  jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_active  boolean NOT NULL DEFAULT true,
    note       text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text,
    UNIQUE (key, scope, scope_ref, version)
);

CREATE INDEX IF NOT EXISTS idx_prompts_lookup
    ON public.prompts (key, scope, scope_ref, version DESC) WHERE is_active;

CREATE TABLE IF NOT EXISTS public.system_messages (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key        text NOT NULL,
    locale     text NOT NULL DEFAULT 'en-IN',
    scope      text NOT NULL DEFAULT 'tenant' CHECK (scope IN ('global', 'pack', 'tenant')),
    scope_ref  text NOT NULL DEFAULT '',
    version    integer NOT NULL CHECK (version >= 1),
    body       text NOT NULL,
    variables  jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_active  boolean NOT NULL DEFAULT true,
    note       text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text,
    UNIQUE (key, locale, scope, scope_ref, version)
);

CREATE INDEX IF NOT EXISTS idx_system_messages_lookup
    ON public.system_messages (key, locale, scope, scope_ref, version DESC) WHERE is_active;
```

**You should see:** No error.

### Step 7 of 9: a place for the nightly cleanup's copies

From `core-0010_archived_rows`. Adds one empty table, `archived_rows`. The nightly cleanup keeps a copy of every row it removes there. Nothing writes to it until the new app is live.

```sql
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.archived_rows (
    id           bigserial PRIMARY KEY,
    source_table text NOT NULL,
    row_id       text,
    org_id       uuid,
    row_data     jsonb NOT NULL,
    reason       text,
    archived_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_archived_rows_age
    ON public.archived_rows (org_id, archived_at);
CREATE INDEX IF NOT EXISTS idx_archived_rows_source
    ON public.archived_rows (source_table, archived_at);
```

**You should see:** No error.

### Step 8 of 9: take two unused permission labels off the roles

From `housing-0001_remove_unused_labels`. `get_resident_cases_status` and `view_my_cases` are held by some roles, but nothing uses them. They only show up in the line that tells the AI what a person may do. This takes them off. `general_read` stays. To put one back later, ask Claude, or add it to the roles that had it (your backup lists them).

```sql
SET lock_timeout = '5s';

UPDATE public.roles
SET permissions = array_remove(array_remove(permissions, 'get_resident_cases_status'), 'view_my_cases')
WHERE permissions && ARRAY['get_resident_cases_status', 'view_my_cases'];
```

**You should see:** No error.

### Step 9 of 9: every building block does one step

From `housing-0002_one_step_blocks`. **Godrej only.** A building block should do one thing. Eight blocks had grown several steps each (Create a case had six). This cuts them into 25 one-step blocks, and makes the four flows that used the big blocks (File a complaint, Add an update, Close with a note, Pass on) run the small blocks one after another: same order, same inputs, same "only if" conditions. Blocks share the flow's memory, so what a person sees and what gets saved does not change.

- **Nothing is deleted.** The 8 old blocks are switched off and their title ends with "(replaced)". Two old blocks that nothing uses (Tell the person who has the case, Tell the person who raised the case) are only switched off.
- Each of the 4 flows gets a new version. Its old version stays in its History.
- **It looks first.** If a block was edited after this was written, or something still runs a block that would be switched off, it stops with a message and changes nothing.
- **Tested:** 17 cases (new complaints, updates, closes, pass-ons, and two that must fail) were run on a practice copy before and after. The result was the same every time (137 lines compared).
- **Keep the "(replaced)" blocks for a few days** before you delete any: the way back below needs them.
- It takes effect at once. It changes how the flows are built, not what they do.

**9a. First test the query box (changes nothing).** This step needs the box to keep a helper table from one line to the next. This tiny test shows whether it does:

```sql
CREATE TEMP TABLE _probe (x integer) ON COMMIT DROP;
INSERT INTO _probe VALUES (1);
SELECT x FROM _probe;
```

**You should see:** a table with one row, `1`. If you see an error (`relation "_probe" does not exist`), stop and tell Claude: your box sends each line on its own and this step needs another way.

**9b. The step itself.** Paste all of it as one piece:

```sql
SET lock_timeout = '5s';

CREATE TEMP TABLE _cut (
    old_key         text NOT NULL,
    idx             integer NOT NULL,
    new_key         text NOT NULL,
    new_name        text NOT NULL,
    new_description text NOT NULL
) ON COMMIT DROP;

INSERT INTO _cut (old_key, idx, new_key, new_name, new_description) VALUES
    ('case_find', 0, 'case_find_by_number', 'Find a case by its number',
     'Finds the case from its number (any format) and keeps it for the steps after. Stops if there is no such case.'),
    ('case_find', 1, 'case_check_access', 'Check the person may act on the case',
     'Stops unless the person may act on the case that was found. Needs the case found first.'),

    ('case_create', 0, 'case_look_up_response_time', 'Look up the response time of the priority',
     'Finds how long the priority gets, from the response-time table, for the steps after.'),
    ('case_create', 1, 'case_due_from_priority', 'Work out the due time from the priority',
     'Sets the due time of a new case from the response time of its priority. Needs the response time looked up first.'),
    ('case_create', 2, 'case_due_from_route', 'Work out the due time from the routing rule',
     'When the routing rule gave a time, uses it instead of the one from the priority.'),
    ('case_create', 3, 'case_save_new', 'Save the new case',
     'Saves a new case with its number, title, place, priority and due time.'),
    ('case_create', 4, 'case_set_category', 'Put the new case in its category',
     'Puts the case in the category that was found, when there is one. Needs the case saved first.'),
    ('case_create', 5, 'case_record_reported', 'Record that the case was reported',
     'Writes "reported" on the case timeline. Needs the case saved first.'),

    ('case_set_priority', 0, 'case_look_up_response_time', 'Look up the response time of the priority',
     'Finds how long the priority gets, from the response-time table, for the steps after.'),
    ('case_set_priority', 1, 'case_due_from_new_priority', 'Work out the due time again for the new priority',
     'Works out the due time again, counting from when the case was raised. Needs the case found and the response time looked up first.'),
    ('case_set_priority', 2, 'case_save_priority', 'Save the new priority and due time',
     'Changes the priority and the due time of the case. Needs the case found first.'),
    ('case_set_priority', 3, 'case_record_priority', 'Record the priority change',
     'Writes the new priority on the case timeline. Needs the case found first.'),

    ('case_set_status', 0, 'case_save_status', 'Save the new status',
     'Moves the case to another status. Needs the case found first.'),
    ('case_set_status', 1, 'case_stamp_closed_time', 'Note the time the case was closed',
     'When the new status is closed, writes the closing time. Needs the case found first.'),
    ('case_set_status', 2, 'case_clear_closed_time', 'Clear the closing time',
     'When the new status is not closed, clears the closing time. Needs the case found first.'),
    ('case_set_status', 3, 'case_record_status', 'Record the status change',
     'Writes the status change on the case timeline. Needs the case found first.'),

    ('case_apply_route', 0, 'case_give_to_routed_person', 'Give the new case to the person the routing rule names',
     'Gives a new case to the person the routing rules name, when they named one. Needs the case saved and the routing rule found first.'),
    ('case_apply_route', 1, 'case_record_routed_assignment', 'Record the routing assignment',
     'Writes on the case timeline that the routing rule gave the case to that person. Runs only when the rule named one.'),
    ('case_apply_route', 2, 'case_add_level2_people', 'Add the level 2 people from the routing rule',
     'Adds the level 2 people to the case, when the routing rule named some.'),

    ('case_assign', 0, 'case_find_new_handler', 'Find the person to give the case to',
     'Finds the person by name, among the people who are active.'),
    ('case_assign', 1, 'case_save_handler', 'Give the case to that person',
     'Hands the case to the person that was found. Needs the case and the person found first.'),
    ('case_assign', 2, 'case_record_assignment', 'Record the assignment',
     'Writes the hand-over on the case timeline. Needs the case and the person found first.'),

    ('case_close', 0, 'case_save_closed', 'Mark the case closed',
     'Sets the case to closed and notes the time. Needs the case found first.'),
    ('case_close', 1, 'case_record_closed', 'Record the closing and its note',
     'Writes the closing, with its note, on the case timeline. Needs the case found first.'),

    ('case_tell_parties', 0, 'case_tell_everyone_with_buttons', 'Tell everyone on the case, with buttons',
     'Messages everyone on the case except the person doing this, once each, with Add update, Pass on and Close buttons. Runs only when tell_buttons is yes. The caller gives the wording.'),
    ('case_tell_parties', 1, 'case_tell_everyone', 'Tell everyone on the case, without buttons',
     'Messages everyone on the case except the person doing this, once each, without buttons. Runs unless tell_buttons is yes. The caller gives the wording.');

-- old, unused blocks with several steps: nothing runs them, so they are only switched off
CREATE TEMP TABLE _retire (old_key text NOT NULL, steps integer NOT NULL) ON COMMIT DROP;
INSERT INTO _retire (old_key, steps) VALUES ('case_tell_handler', 2), ('case_tell_requester', 2);

-- the number of steps each of these blocks had when this file was written
CREATE TEMP TABLE _expect ON COMMIT DROP AS
SELECT old_key, count(*)::integer AS steps FROM _cut GROUP BY old_key
UNION ALL
SELECT old_key, steps FROM _retire;

-- the blocks this file acts on: switched on, and still with exactly those steps.
-- A block that already has one step, or is switched off, is not touched.
CREATE TEMP TABLE _old ON COMMIT DROP AS
SELECT w.id, w.org_id, w.intent_key AS old_key
FROM public.workflows w
JOIN _expect e ON e.old_key = w.intent_key
WHERE w.is_active
  AND jsonb_array_length((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) = e.steps;

-- 1. Look before changing anything: stop if something is not as expected.
DO $$
DECLARE
    bad record;
BEGIN
    -- several steps, but not the ones this file knows: it was edited after this file was written
    FOR bad IN
        SELECT w.intent_key, jsonb_array_length((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) AS have, e.steps AS want
        FROM public.workflows w
        JOIN _expect e ON e.old_key = w.intent_key
        WHERE w.is_active
          AND jsonb_array_length((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) > 1
          AND jsonb_array_length((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) <> e.steps
    LOOP
        RAISE EXCEPTION 'housing-0002: the block "%" has % steps but % were expected; it was edited after this file was written. Nothing was changed.',
            bad.intent_key, bad.have, bad.want;
    END LOOP;

    -- a step shared by two blocks must be the same step in both
    FOR bad IN
        SELECT o.org_id, c.new_key
        FROM _cut c
        JOIN _old o ON o.old_key = c.old_key
        JOIN public.workflows w ON w.id = o.id
        GROUP BY o.org_id, c.new_key
        HAVING count(DISTINCT (w.steps -> c.idx)) > 1
    LOOP
        RAISE EXCEPTION 'housing-0002: the blocks that share "%" no longer have the same step in it. Nothing was changed.', bad.new_key;
    END LOOP;

    -- a new key must not belong to something else ...
    FOR bad IN
        SELECT n.intent_key
        FROM public.workflows n
        WHERE n.org_id IN (SELECT org_id FROM _old)
          AND n.intent_key IN (SELECT new_key FROM _cut)
          AND (n.kind <> 'block' OR jsonb_array_length((CASE WHEN jsonb_typeof(n.steps) = 'array' THEN n.steps ELSE '[]'::jsonb END)) <> 1)
    LOOP
        RAISE EXCEPTION 'housing-0002: a workflow called "%" already exists and is not a one-step block. Nothing was changed.', bad.intent_key;
    END LOOP;

    -- ... and a one-step block that already has the key must hold the very step this file would put there
    FOR bad IN
        SELECT n.intent_key
        FROM _cut c
        JOIN _old o ON o.old_key = c.old_key
        JOIN public.workflows w ON w.id = o.id
        JOIN public.workflows n ON n.org_id = o.org_id AND n.intent_key = c.new_key
        WHERE n.steps IS DISTINCT FROM jsonb_build_array(w.steps -> c.idx)
    LOOP
        RAISE EXCEPTION 'housing-0002: a block called "%" already exists and holds a different step. Nothing was changed.', bad.intent_key;
    END LOOP;

    -- a block that is only switched off must not be run by anything
    FOR bad IN
        SELECT o.old_key, w.intent_key AS used_by
        FROM _old o
        JOIN _retire r ON r.old_key = o.old_key
        JOIN public.workflows w ON w.org_id = o.org_id AND w.intent_key <> o.old_key
        CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END) s(step)
        WHERE s.step ->> 'op' = 'run_workflow' AND s.step -> 'params' ->> 'workflow' = o.old_key
    LOOP
        RAISE EXCEPTION 'housing-0002: "%" is run by "%", so it is not switched off. Nothing was changed.', bad.old_key, bad.used_by;
    END LOOP;
END
$$;

-- 2. The one-step blocks. Each takes its step, its inputs and its settings from the block it was cut from.
INSERT INTO public.workflows
    (org_id, intent_key, name, description, steps, is_active, version, workflow_type, kind,
     entity_schema, gates, training_phrases, settings, response_format, menu_section)
SELECT DISTINCT ON (w.org_id, c.new_key)
    w.org_id, c.new_key, c.new_name, c.new_description,
    jsonb_build_array(w.steps -> c.idx), true, 1, w.workflow_type, 'block',
    w.entity_schema, w.gates, w.training_phrases, w.settings, w.response_format, w.menu_section
FROM _cut c
JOIN _old o ON o.old_key = c.old_key
JOIN public.workflows w ON w.id = o.id
ORDER BY w.org_id, c.new_key, c.old_key, c.idx
ON CONFLICT (org_id, intent_key) DO NOTHING;

-- 3. What each workflow that ran a big block will run instead: the small blocks, in the same place,
--    with everything else about the step (inputs, "only if") kept.
CREATE TEMP TABLE _flow_new ON COMMIT DROP AS
SELECT w.id, w.org_id,
       (SELECT jsonb_agg(e.item ORDER BY e.pos, e.sub)
        FROM (
            SELECT s.pos, 0 AS sub, s.step AS item
            FROM jsonb_array_elements((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) WITH ORDINALITY s(step, pos)
            WHERE NOT (s.step ->> 'op' = 'run_workflow'
                       AND EXISTS (SELECT 1 FROM _cut c
                                   JOIN _old ob ON ob.org_id = w.org_id AND ob.old_key = c.old_key
                                   WHERE c.old_key = s.step -> 'params' ->> 'workflow'))
            UNION ALL
            SELECT s.pos, c.idx + 1, jsonb_set(s.step, '{params,workflow}', to_jsonb(c.new_key))
            FROM jsonb_array_elements((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) WITH ORDINALITY s(step, pos)
            JOIN _cut c ON s.step ->> 'op' = 'run_workflow' AND c.old_key = s.step -> 'params' ->> 'workflow'
            WHERE EXISTS (SELECT 1 FROM _old ob
                          WHERE ob.org_id = w.org_id AND ob.old_key = c.old_key)
        ) e) AS new_steps
FROM public.workflows w
WHERE jsonb_typeof(w.steps) = 'array'
  AND w.intent_key NOT IN (SELECT old_key FROM _cut)
  AND EXISTS (
        SELECT 1
        FROM jsonb_array_elements((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) s(step)
        JOIN _cut c ON s.step ->> 'op' = 'run_workflow' AND c.old_key = s.step -> 'params' ->> 'workflow'
        JOIN _old ob ON ob.org_id = w.org_id AND ob.old_key = c.old_key);

-- 4. Keep a copy of every workflow as it stands now (the dashboard does the same before a save).
INSERT INTO public.workflow_versions
    (workflow_id, org_id, version, intent_key, name, entity_schema, gates, granted_roles, steps,
     calc_rules, sql_template, slash_command, published_at, kind, settings)
SELECT w.id, w.org_id, w.version, w.intent_key, w.name, w.entity_schema, w.gates,
       ARRAY(SELECT r.name FROM public.roles r WHERE r.org_id = w.org_id AND w.intent_key = ANY (r.permissions) ORDER BY r.name),
       w.steps, w.calc_rules, w.sql_template, w.slash_command, w.created_at, w.kind, w.settings
FROM public.workflows w
WHERE (w.id IN (SELECT id FROM _flow_new) OR w.id IN (SELECT id FROM _old))
  AND NOT EXISTS (SELECT 1 FROM public.workflow_versions v WHERE v.workflow_id = w.id AND v.version = w.version);

-- 5. The workflows now run the small blocks.
UPDATE public.workflows w
SET steps = f.new_steps, version = w.version + 1
FROM _flow_new f
WHERE w.id = f.id;

-- 6. The old blocks are switched off (and the ones that were cut say so in their title).
UPDATE public.workflows w
SET is_active = false,
    version = w.version + 1,
    name = CASE WHEN w.intent_key IN (SELECT old_key FROM _cut) THEN w.name || ' (replaced)' ELSE w.name END
WHERE w.id IN (SELECT id FROM _old);

-- 7. Keep a copy of what they are now, and of the new blocks.
INSERT INTO public.workflow_versions
    (workflow_id, org_id, version, intent_key, name, entity_schema, gates, granted_roles, steps,
     calc_rules, sql_template, slash_command, published_at, kind, settings)
SELECT w.id, w.org_id, w.version, w.intent_key, w.name, w.entity_schema, w.gates,
       ARRAY(SELECT r.name FROM public.roles r WHERE r.org_id = w.org_id AND w.intent_key = ANY (r.permissions) ORDER BY r.name),
       w.steps, w.calc_rules, w.sql_template, w.slash_command, now(), w.kind, w.settings
FROM public.workflows w
WHERE (w.id IN (SELECT id FROM _flow_new)
       OR w.id IN (SELECT id FROM _old)
       OR (w.intent_key IN (SELECT new_key FROM _cut) AND w.org_id IN (SELECT org_id FROM _old)))
  AND NOT EXISTS (SELECT 1 FROM public.workflow_versions v WHERE v.workflow_id = w.id AND v.version = w.version);

-- 8. Look again: nothing that is switched on may still run an old block, and every new block has one step.
DO $$
DECLARE
    bad record;
BEGIN
    FOR bad IN
        SELECT w.intent_key, s.step -> 'params' ->> 'workflow' AS runs
        FROM public.workflows w
        CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END) s(step)
        JOIN _old o ON o.org_id = w.org_id AND o.old_key = s.step -> 'params' ->> 'workflow'
        WHERE w.is_active AND s.step ->> 'op' = 'run_workflow'
    LOOP
        RAISE EXCEPTION 'housing-0002: "%" still runs the switched-off block "%". Everything was undone.', bad.intent_key, bad.runs;
    END LOOP;
    FOR bad IN
        SELECT n.intent_key, jsonb_array_length((CASE WHEN jsonb_typeof(n.steps) = 'array' THEN n.steps ELSE '[]'::jsonb END)) AS n
        FROM public.workflows n
        WHERE n.org_id IN (SELECT org_id FROM _old)
          AND n.intent_key IN (SELECT new_key FROM _cut)
          AND (n.kind <> 'block' OR NOT n.is_active OR jsonb_array_length((CASE WHEN jsonb_typeof(n.steps) = 'array' THEN n.steps ELSE '[]'::jsonb END)) <> 1)
    LOOP
        RAISE EXCEPTION 'housing-0002: the new block "%" does not hold exactly one step (it has %). Everything was undone.', bad.intent_key, bad.n;
    END LOOP;

    IF to_regclass('public.admin_events') IS NOT NULL THEN
        INSERT INTO public.admin_events (org_id, actor_label, area, action, target_type, summary)
        SELECT DISTINCT o.org_id, 'migration housing-0002', 'workflows', 'cut_blocks', 'workflow',
               'Cut the building blocks into one-step blocks (migration housing-0002)'
        FROM _old o
        WHERE NOT EXISTS (SELECT 1 FROM public.admin_events e
                          WHERE e.org_id = o.org_id AND e.actor_label = 'migration housing-0002');
    END IF;
END
$$;
```

**You should see:** No error. If you see a line starting `housing-0002:` it is the step refusing to go on, and nothing was changed. Send me the line.

**9c. Check (changes nothing).**

```sql
SELECT count(*) AS blocks_on, max(jsonb_array_length(steps)) AS most_steps_in_one_block
FROM workflows
WHERE kind = 'block' AND is_active;
```

**You should see:** `blocks_on` 27 and `most_steps_in_one_block` 1. The important part is the 1: no block has more than one step. (27 is what my practice copy gave. If you made new blocks yourself it can be more.)

```sql
SELECT intent_key, version, jsonb_array_length(steps) AS steps
FROM workflows
WHERE intent_key IN ('file_a_complaint', 'case_add_update', 'case_close_with_note', 'case_pass_on')
ORDER BY intent_key;
```

**You should see:** 4 rows. On my practice copy the steps are `case_add_update` 6, `case_close_with_note` 7, `case_pass_on` 9, `file_a_complaint` 14, and each version went up by 1.

**9d. Try it for real.** On the Godrej bot (Telegram) file one test complaint, add an update to it, then close it. You should get the same messages as before.

**Way back from step 9 only.** Use it only if something is wrong, right after step 9 and before anyone edits a flow. It puts the 4 flows back exactly as they were and switches the 10 old blocks on again. The 25 small blocks stay, unused. Nothing is deleted. If you paste it twice, the second time changes nothing.

```sql
SET lock_timeout = '5s';

-- 1. The four flows get back the steps they had before step 9, but only a flow that still runs the new
--    small blocks. (Their History keeps both versions; nothing is deleted.)
UPDATE workflows w
SET steps = v.steps, version = w.version + 1
FROM workflow_versions v
WHERE v.workflow_id = w.id
  AND v.version = w.version - 1
  AND w.intent_key IN ('file_a_complaint', 'case_add_update', 'case_close_with_note', 'case_pass_on')
  AND EXISTS (
        SELECT 1
        FROM jsonb_array_elements(CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END) s(step)
        WHERE s.step -> 'params' ->> 'workflow' IN (
              'case_find_by_number', 'case_check_access', 'case_look_up_response_time', 'case_due_from_priority',
              'case_due_from_route', 'case_save_new', 'case_set_category', 'case_record_reported',
              'case_due_from_new_priority', 'case_save_priority', 'case_record_priority', 'case_save_status',
              'case_stamp_closed_time', 'case_clear_closed_time', 'case_record_status', 'case_give_to_routed_person',
              'case_record_routed_assignment', 'case_add_level2_people', 'case_find_new_handler', 'case_save_handler',
              'case_record_assignment', 'case_save_closed', 'case_record_closed', 'case_tell_everyone_with_buttons',
              'case_tell_everyone'));

-- 2. The ten old blocks are switched on again, with their old titles.
UPDATE workflows
SET is_active = true,
    version = version + 1,
    name = regexp_replace(name, ' \(replaced\)$', '')
WHERE NOT is_active
  AND intent_key IN ('case_find', 'case_create', 'case_set_priority', 'case_set_status',
                     'case_apply_route', 'case_assign', 'case_close', 'case_tell_parties',
                     'case_tell_handler', 'case_tell_requester');
```

**You should see:** No error. Then run 9c again: `blocks_on` will be 37 and `most_steps_in_one_block` 6, like before step 9 plus the 25 unused small blocks.

### Final check for Godrej (changes nothing)

```sql
SELECT
  to_regclass('public.admin_events')          IS NOT NULL AS admin_events,
  to_regclass('public.prompts')               IS NOT NULL AS prompts,
  to_regclass('public.system_messages')       IS NOT NULL AS system_messages,
  to_regclass('public.archived_rows')         IS NOT NULL AS archived_rows,
  to_regclass('public.idx_audit_log_session') IS NOT NULL AS chat_index_1,
  to_regclass('public.idx_audit_log_intent')  IS NOT NULL AS chat_index_2,
  EXISTS (SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'orgs' AND column_name = 'timezone') AS orgs_timezone,
  EXISTS (SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'orgs' AND column_name = 'locale')   AS orgs_locale;
```

**You should see:** one row with 8 columns, all `true` (or `t`). A `false` means a step was missed: send me the row.


## If something goes wrong

- A step shows an error: stop, send the message to Claude. Pasting the same step again is safe.
- Step 9 only: use "Way back from step 9 only" above.
- Anything else: put the backup back. It returns that one database to exactly how it was when you
  backed up, so anything written after the backup is lost. In PowerShell, first look (changes nothing),
  then do it by typing the database name again. Use `baanganga` the same way:

```powershell
& $railway run python -m tools.restore --tenant godrej --allow-remote
& $railway run python -m tools.restore --tenant godrej --allow-remote --yes-restore godrej
```

More on this: `docs/runbook-migrations.md`, step 6.

## When you are done

1. Run the final check on both databases.
2. Tell Claude. The next thing is deploying the new app version (the new dashboard screens, the settings,
   the editable messages, the nightly cleanup). That is separate and only on your word. **Order: this SQL
   first, then the app.**
3. The migration tool does not know you ran these by hand, so it will list them as "waiting". That is
   harmless because every file is safe to run twice. Ask Claude to mark them as done when you want it tidy.
