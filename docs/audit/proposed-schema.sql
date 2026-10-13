-- ============================================================================
-- PROPOSED SCHEMA CHANGES — PROPOSALS ONLY. NOTHING IN THIS FILE HAS BEEN RUN.
-- Do not execute against any database. Review, take a backup, and run each step
-- on one tenant first.  Evidence refers to docs/audit/db-inventory.md and
-- docs/audit/architecture-audit.md (dumps: godrej 2026-10-03, baanganga and
-- routing 2026-09-23; live may differ).
--
-- Order: every step is additive or reversible and none breaks the running
-- system if the code is not yet using it. Steps marked [CODE] need an app
-- change before they matter. Steps marked [DECISION] need the owner's answer.
-- ============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- P1-01  Migration history table, in every tenant DB and the control DB
-- Evidence: no schema_migrations/alembic table in godrej, baanganga or routing dumps;
--           drift found (db-inventory 7.2): baanganga lacks 15 indexes, godrej has 3 columns baanganga lacks.
-- Risk: none (new table). Rollback: DROP TABLE schema_migrations;
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,           -- e.g. 'core-0001'
    applied_at  timestamptz NOT NULL DEFAULT now(),
    checksum    text,
    applied_by  text
);
-- Backfill: record what is already there as a baseline, per tenant, after diffing it.
-- INSERT INTO schema_migrations (version, applied_by) VALUES ('core-0000-baseline', 'audit');

-- ─────────────────────────────────────────────────────────────────────────────
-- P1-02  Purge expired runtime debris (scheduled job, not a migration)
-- Evidence: godrej user_drafts 84/84 expired, otp_tokens 69/69 expired; no DELETE in code
--           (app/services/draft_store.py only updates stage).
-- Risk: deletes rows; drafts are done/cancelled so no live request is lost. Take a backup first.
-- Rollback: restore from backup (data deletion cannot be undone in SQL).
-- ─────────────────────────────────────────────────────────────────────────────
-- DELETE FROM user_drafts WHERE expires_at < now() - interval '7 days' AND stage IN ('done','cancelled');
-- DELETE FROM otp_tokens  WHERE expires_at < now() - interval '1 day';
-- DELETE FROM workflow_drafts WHERE status = 'abandoned' AND updated_at < now() - interval '30 days';

-- ─────────────────────────────────────────────────────────────────────────────
-- P1-03  Indexes the code needs; remove one duplicate
-- Evidence: audit_log has no index on session_id although the Activity screens group and filter by it
--           (admin_panel/activity.py:46-57); baanganga has no users(phone) index although identity.py:25
--           filters on it for every message; godrej has idx_workflows_org_intent duplicating UNIQUE(org_id,intent_key).
-- Risk: index build locks writes briefly on small tables; use CONCURRENTLY outside a transaction.
-- Rollback: DROP INDEX the new ones; re-create the dropped one.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_session ON audit_log (session_id, created_at);
-- baanganga only:
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_phone ON users (phone);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_otp_user_expiry ON otp_tokens (user_id, expires_at);
-- godrej only, after confirming the unique constraint's index is used:
-- DROP INDEX CONCURRENTLY IF EXISTS idx_workflows_org_intent;

-- ─────────────────────────────────────────────────────────────────────────────
-- P1-04  Tenant timezone and locale instead of a hard-coded IST   [CODE]
-- Evidence: db.py:38 SET timezone='Asia/Kolkata'; scheduler/jobs.py:22; agent.py:1923,1946.
-- Risk: none while default stays Asia/Kolkata. Rollback: ALTER TABLE orgs DROP COLUMN timezone, DROP COLUMN locale;
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE orgs ADD COLUMN IF NOT EXISTS timezone text NOT NULL DEFAULT 'Asia/Kolkata';
ALTER TABLE orgs ADD COLUMN IF NOT EXISTS locale   text NOT NULL DEFAULT 'en-IN';

-- ─────────────────────────────────────────────────────────────────────────────
-- P1-05  Prompts and system messages as tenant config   [CODE]
-- Evidence: 19 prompt files (~2,500 lines) loaded by prompt_loader.py:19-35; 77 literal user messages
--           (routers/webhook.py 62, executor 12, interpreter 2, telegram_webhook 1). A stale prompt caused the live
--           'assign_case' failure (fixed in commit 327a9a3).
-- Risk: none until the loader reads them (files stay as fallback). Rollback: DROP TABLE prompts, system_messages;
-- Precedence at read time: tenant > pack > global.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prompts (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key        text NOT NULL,                       -- 'agent.system', 'builder.creator', 'domain'
    scope      text NOT NULL CHECK (scope IN ('global','pack','tenant')),
    scope_ref  text NOT NULL DEFAULT '',            -- pack name or '' (tenant DB is its own tenant)
    version    integer NOT NULL,
    body       text NOT NULL,
    variables  jsonb NOT NULL DEFAULT '[]',         -- declared {placeholders}
    is_active  boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text,
    UNIQUE (key, scope, scope_ref, version)
);
CREATE TABLE IF NOT EXISTS system_messages (
    key        text NOT NULL,
    locale     text NOT NULL DEFAULT 'en-IN',
    scope      text NOT NULL DEFAULT 'global' CHECK (scope IN ('global','pack','tenant')),
    scope_ref  text NOT NULL DEFAULT '',
    body       text NOT NULL,
    variables  jsonb NOT NULL DEFAULT '[]',
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (key, locale, scope, scope_ref)
);
-- Backfill: tools/load_pack.py reads app/prompts/*.txt and the webhook literals once. No SQL backfill.

-- ─────────────────────────────────────────────────────────────────────────────
-- P1-06  Move jewellery columns out of the shared orgs table   [CODE]
-- Evidence: orgs.gst_rate, orgs.default_making_charge_pct (baanganga set, godrej NULL); read at agent.py:873.
-- Risk: low; keep the columns for one release. Rollback: nothing to undo (columns are kept).
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE orgs SET settings = settings || jsonb_build_object('prompt_vars',
        jsonb_strip_nulls(jsonb_build_object('gst_rate', gst_rate, 'default_making_charge_pct', default_making_charge_pct)))
 WHERE gst_rate IS NOT NULL OR default_making_charge_pct IS NOT NULL;
-- Later (P3): ALTER TABLE orgs DROP COLUMN gst_rate, DROP COLUMN default_making_charge_pct;

-- ─────────────────────────────────────────────────────────────────────────────
-- P1-07  A column nothing writes, and logs that cannot be grouped   [CODE for the first]
-- Evidence (LIVE scan 2026-10-03): workflows.last_run is NULL on 27 of 27 workflows although they created 25 invoices,
--           13 orders and 29 cases; no code writes it (reads only: admin_panel/workflows.py:72, routers/admin.py:238).
--           audit_log.session_id is NULL on 420 of 595 Godrej rows and 97 of 120 Baanganga rows, so the Chats screen shows
--           each as its own conversation.
-- Risk: low. Rollback for the backfill is given; the column decision is yours.
-- ─────────────────────────────────────────────────────────────────────────────
-- Option A (recommended): write it on every successful run (engine change) from workflow_runs.finished_at, then keep.
-- Option B: drop it:  ALTER TABLE workflows DROP COLUMN last_run;   (the classic admin reads it: retire that first)
-- Backfill grouping for old audit rows, one pseudo-conversation per person per day:
-- UPDATE audit_log SET session_id = 'legacy:' || coalesce(user_id::text, 'anon') || ':' || created_at::date WHERE session_id IS NULL;
-- Rollback:   UPDATE audit_log SET session_id = NULL WHERE session_id LIKE 'legacy:%';

-- ─────────────────────────────────────────────────────────────────────────────
-- P1-08  Partial indexes for the every-minute jobs, and Baanganga drift
-- Evidence (LIVE): sequential scans since stats began: cases 45,583 (1 index scan), scheduled_reports ~20,580 on both tenants,
--           orgs 32,722 / 21,272; the two scheduler passes run each minute (jobs.py:230-305). Harmless at 29 rows.
--           Baanganga lacks user_drafts.created_at (a live query using it failed) and users(phone), otp_tokens and
--           scheduled_reports indexes that Godrej has.
-- Risk: low (CONCURRENTLY). Rollback: DROP INDEX.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scheduled_reports_due ON scheduled_reports (next_run_at) WHERE is_active;
-- godrej only (case tables):
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cases_open_due ON cases (org_id, due_date) WHERE status <> 'closed';
-- baanganga only:
-- ALTER TABLE user_drafts ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scheduled_reports_next_run ON scheduled_reports (next_run_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- P2-01  Immutable, complete definition versions and a pin for every run   [CODE]
-- Evidence: workflow_versions snapshots 12 columns of ~30 (no description, training phrases, response format/template,
--           pdf_config, glossary, llm_system_prompt, thresholds, menu section); godrej has 4 snapshots for 19 workflows,
--           baanganga 0 for 8; 18 of 19 godrej workflows still version 1 after migrations 006-010 edited them in place;
--           user_drafts/pending_approvals/audit_log carry no version; action_executor.py:48 loads the latest by key.
-- Risk: medium (dual-write period). Rollback: stop reading the new table; old columns remain authoritative until cut-over.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_definitions (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    key            text NOT NULL,                  -- the intent_key
    version        integer NOT NULL,
    schema_version integer NOT NULL DEFAULT 1,     -- version of the DEFINITION FORMAT
    definition     jsonb NOT NULL,                 -- steps, entity_schema, gates, settings, templates, thresholds, prompts
    change_note    text,
    created_by     text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, key, version)
);
CREATE OR REPLACE FUNCTION workflow_definitions_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION 'workflow_definitions rows are immutable; insert a new version'; END $$;
DROP TRIGGER IF EXISTS trg_workflow_definitions_immutable ON workflow_definitions;
CREATE TRIGGER trg_workflow_definitions_immutable BEFORE UPDATE OR DELETE ON workflow_definitions
    FOR EACH ROW EXECUTE FUNCTION workflow_definitions_immutable();

ALTER TABLE workflows ADD COLUMN IF NOT EXISTS current_version integer;
ALTER TABLE workflows ADD COLUMN IF NOT EXISTS schema_version  integer NOT NULL DEFAULT 1;
-- Backfill (one version per existing workflow, built from the live row):
INSERT INTO workflow_definitions (org_id, key, version, definition, change_note, created_by)
SELECT w.org_id, w.intent_key, w.version,
       jsonb_build_object('name', w.name, 'description', w.description, 'workflow_type', w.workflow_type,
           'steps', w.steps, 'entity_schema', w.entity_schema, 'gates', w.gates, 'settings', COALESCE(to_jsonb(w) -> 'settings', '{}'),
           'training_phrases', w.training_phrases, 'sql_template', w.sql_template, 'sql_params_order', w.sql_params_order,
           'response_format', w.response_format, 'response_template', w.response_template, 'pdf_config', w.pdf_config,
           'calc_rules', w.calc_rules, 'business_glossary', w.business_glossary, 'llm_system_prompt', w.llm_system_prompt,
           'slash_command', w.slash_command, 'command_description', w.command_description, 'menu_section', w.menu_section,
           'otp_required', w.otp_required, 'otp_threshold', w.otp_threshold, 'approval_threshold', w.approval_threshold),
       'backfill from live row', 'audit'
  FROM workflows w
ON CONFLICT (org_id, key, version) DO NOTHING;
UPDATE workflows SET current_version = version WHERE current_version IS NULL;

-- Pin runs now (nullable stepping stone), so new rows can start carrying a version before workflow_runs exists:
ALTER TABLE user_drafts       ADD COLUMN IF NOT EXISTS workflow_version integer;
ALTER TABLE pending_approvals ADD COLUMN IF NOT EXISTS workflow_version integer;

-- ─────────────────────────────────────────────────────────────────────────────
-- P2-02  Runs table (replaces stage handling in user_drafts over time)   [CODE]
-- Evidence: resume_step indexes into the CURRENT steps (step_interpreter.py:1937, action_executor.py:48); no
--           idempotency key; steps write on separate connections so a failed run leaves partial rows.
-- Risk: medium. Rollback: stop writing it; user_drafts keeps working.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_runs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    workflow_key     text NOT NULL,
    workflow_version integer NOT NULL,
    user_id          uuid REFERENCES users(id) ON DELETE SET NULL,
    state            text NOT NULL CHECK (state IN ('collecting','awaiting_confirmation','awaiting_otp','awaiting_approval','running','done','failed','cancelled')),
    step_index       integer NOT NULL DEFAULT 0,
    fields           jsonb NOT NULL DEFAULT '{}',
    idempotency_key  text,
    error_step       integer,
    error_message    text,
    started_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz,
    FOREIGN KEY (org_id, workflow_key, workflow_version) REFERENCES workflow_definitions (org_id, key, version),
    UNIQUE (org_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_user_state ON workflow_runs (org_id, user_id, state);

-- ─────────────────────────────────────────────────────────────────────────────
-- P2-03  Audit log that says what happened   [CODE]
-- Evidence: godrej audit_log 595 rows, outcome always 'success', steps_taken empty in 595/595, intent_key 'agent'/'menu'
--           for most; a permission refusal on 2 Oct was logged as success.
-- Risk: low. Rollback: drop the added columns/constraint.
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS workflow_key     text;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS workflow_version integer;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS run_id           uuid;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS error_step       integer;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS error_message    text;
-- After the code writes real outcomes:
-- ALTER TABLE audit_log ADD CONSTRAINT audit_outcome_check CHECK (outcome IN ('success','failed','blocked','cancelled','error')) NOT VALID;

-- ─────────────────────────────────────────────────────────────────────────────
-- P2-04  Integrity: references that should be keys
-- Evidence: workflow_versions has no FK on workflow_id/org_id (2 orphan snapshots in godrej);
--           user_drafts.intent_key points at deleted workflows (64 rows: register_complaint 31, assign_case 21,
--           release_meeting_minutes 8, add_new_resident 4); roles.permissions names workflows that do not exist
--           (general_read 6 roles, view_my_cases 6, get_resident_cases_status 2).
-- Risk: low if done as NOT VALID then VALIDATE after cleaning. Rollback: drop the constraint.
-- ─────────────────────────────────────────────────────────────────────────────
-- Clean dead permission strings (back up roles first):
-- UPDATE roles SET permissions = array_remove(array_remove(array_remove(permissions,'general_read'),'view_my_cases'),'get_resident_cases_status');
-- Orphan snapshots: keep as history; make the link soft-safe:
-- ALTER TABLE workflow_versions ALTER COLUMN workflow_id DROP NOT NULL;
-- ALTER TABLE workflow_versions ADD CONSTRAINT workflow_versions_workflow_fk FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE SET NULL NOT VALID;
-- UPDATE workflow_versions v SET workflow_id = NULL WHERE NOT EXISTS (SELECT 1 FROM workflows w WHERE w.id = v.workflow_id);
-- ALTER TABLE workflow_versions VALIDATE CONSTRAINT workflow_versions_workflow_fk;

-- ─────────────────────────────────────────────────────────────────────────────
-- P2-05  Response times: ordering rule and per-category policy   [CODE]
-- Evidence: priority_tat_rules live values urgent 120, high 480, medium 1440, LOW 10 minutes; only 1 of 29
--           categories has its own target_minutes; scheduler does exactly two passes (jobs.py:230-305).
-- Risk: low. Rollback: drop the trigger / tables.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION priority_tat_order_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM priority_tat_rules p
     WHERE p.org_id = NEW.org_id AND p.priority <> NEW.priority
       AND ((array_position(ARRAY['urgent','high','medium','low'], p.priority) < array_position(ARRAY['urgent','high','medium','low'], NEW.priority) AND p.tat_minutes > NEW.tat_minutes)
         OR (array_position(ARRAY['urgent','high','medium','low'], p.priority) > array_position(ARRAY['urgent','high','medium','low'], NEW.priority) AND p.tat_minutes < NEW.tat_minutes)))
  THEN RAISE EXCEPTION 'a lower priority cannot get less time than a more urgent one'; END IF;
  RETURN NEW;
END $$;
-- Do NOT attach until the live Low=10 value is corrected, or the trigger will block the fix:
-- CREATE TRIGGER trg_priority_tat_order BEFORE INSERT OR UPDATE ON priority_tat_rules FOR EACH ROW EXECUTE FUNCTION priority_tat_order_guard();

CREATE TABLE IF NOT EXISTS sla_policies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    name text NOT NULL, applies_to jsonb NOT NULL DEFAULT '{}',   -- {workflow, category, priority}
    target_minutes integer NOT NULL CHECK (target_minutes > 0),
    is_active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS escalation_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id uuid NOT NULL REFERENCES sla_policies(id) ON DELETE CASCADE,
    after_minutes integer NOT NULL CHECK (after_minutes >= 0),
    action jsonb NOT NULL,                                       -- {notify: seat|user|role, template_key, ...}
    sort_order integer NOT NULL DEFAULT 0
);

-- ─────────────────────────────────────────────────────────────────────────────
-- P3-01  Named, parameterised queries instead of free-form sql_template   [CODE]
-- Evidence: query_engine.py:51-60,135 regex guard and regex table extraction on stored SQL; workflows.sql_template in 3 godrej
--           and 3 baanganga workflows; AI-written SQL already goes through sqlglot (sql_guard.py).
-- Risk: medium (rewrite 6 reports). Rollback: keep sql_template until all reports are migrated.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS named_queries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    key text NOT NULL, version integer NOT NULL,
    sql text NOT NULL, params jsonb NOT NULL DEFAULT '[]',         -- [{name,type,source}]
    allowed_roles text[] NOT NULL DEFAULT '{}',
    max_rows integer NOT NULL DEFAULT 100, timeout_ms integer NOT NULL DEFAULT 5000,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, key, version)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- P3-02  Statuses and types as data, not CHECK lists   [DECISION]
-- Evidence: cases.status CHECK (reported, under_review, action_taken, closed), priority CHECK, case_activity.activity_type,
--           case_parties.party_role, committee_positions.kind; yet orgs.settings.case_reminders.closed_values suggests
--           statuses are configurable.
-- Risk: medium; touches the live case model. Only if a second client needs different statuses.
-- Rollback: re-add the CHECKs (definitions in db-inventory section 4).
-- ─────────────────────────────────────────────────────────────────────────────
-- CREATE TABLE case_statuses (org_id uuid REFERENCES orgs(id), key text, label text, is_closed boolean, sort_order int, PRIMARY KEY (org_id, key));
-- ALTER TABLE cases ADD CONSTRAINT cases_status_fk FOREIGN KEY (org_id, status) REFERENCES case_statuses (org_id, key) NOT VALID;
-- ALTER TABLE cases DROP CONSTRAINT complaint_cases_status_check;

-- ─────────────────────────────────────────────────────────────────────────────
-- P3-03  Retire duplicated approval/OTP thresholds   [CODE]
-- Evidence: workflows.otp_required/otp_threshold/approval_threshold duplicate gates JSON; gates are empty in 27 of 27
--           workflows; baanganga has 2 approval_gate + 2 otp_gate steps with NULL thresholds, so they never halt.
-- Risk: medium; changes behaviour only if a threshold is set. Rollback: keep columns until verified.
-- ─────────────────────────────────────────────────────────────────────────────
-- UPDATE workflows SET gates = gates || jsonb_build_array(jsonb_build_object('type','approval_chain','levels',
--        jsonb_build_array(jsonb_build_object('level',1,'role','owner','max_amount',NULL)),'when',...)) WHERE approval_threshold > 0;
-- (write per-workflow; do not run generically)

-- ─────────────────────────────────────────────────────────────────────────────
-- P3-04  Unused empty JSON indexes and candidate unused table   [DECISION — show both pieces of evidence first]
-- Evidence: 5 GIN indexes on JSON that has no keys in any row (cases/residents/staff/staff_attendance custom_fields,
--           entity_records.fields); godrej.staff_attendance: 0 rows and 0 references in app/ or in any workflow definition
--           (it had 71 rows in the 1 Oct dump, so a client may have cleared test data on purpose).
-- Risk: low for the indexes; the table needs the client's confirmation. Rollback: re-create from db-inventory section 5 / backup.
-- ─────────────────────────────────────────────────────────────────────────────
-- DROP INDEX CONCURRENTLY IF EXISTS idx_cases_custom_fields, idx_residents_custom_fields, idx_staff_custom_fields, idx_staff_attendance_custom_fields;
-- DROP TABLE staff_attendance;   -- only after the client confirms; take a pg_dump of the table first

-- ============================================================================
-- CONTROL DB (routing_db). Same rules: proposals only.
-- ============================================================================

-- C-01  Tenant status, pack, versions, timezone, flags, secret reference.
-- Evidence: data_sources has id, source_key, database_url (raw string incl. password, superuser), description, created_at,
--           messaging_channel; exactly one tenant per channel is enforced in code (db.py:92-110).
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','provisioning'));
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS industry_pack  text;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS pack_version   text;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS schema_version text;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS timezone       text NOT NULL DEFAULT 'Asia/Kolkata';
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS locale         text NOT NULL DEFAULT 'en-IN';
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS flags          jsonb NOT NULL DEFAULT '{}';
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS secret_ref     text;   -- name of an env/secret-manager entry holding the URL
-- Backfill: UPDATE data_sources SET industry_pack = CASE source_key WHEN 'godrej' THEN 'housing_society' WHEN 'baanganga' THEN 'jewellery' END;
-- After the app resolves secret_ref: ALTER TABLE data_sources DROP COLUMN database_url;   (rotate the passwords first)

-- C-02  Channels per tenant (replaces one-tenant-per-channel and the single global WhatsApp number/Telegram bot).   [CODE]
CREATE TABLE IF NOT EXISTS tenant_channels (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key text NOT NULL REFERENCES data_sources(source_key),
    channel text NOT NULL CHECK (channel IN ('whatsapp','telegram')),
    external_id text NOT NULL,          -- WhatsApp phone_number_id, or Telegram bot id
    secret_ref text NOT NULL,           -- token name, never the token
    is_active boolean NOT NULL DEFAULT true,
    UNIQUE (channel, external_id)
);

-- C-03  Who is who across tenants (stops identity scanning every tenant DB per message).   [CODE]
CREATE TABLE IF NOT EXISTS identity_map (
    channel text NOT NULL, external_id text NOT NULL,      -- phone number or 'tg:<chat_id>'
    source_key text NOT NULL REFERENCES data_sources(source_key),
    user_ref uuid NOT NULL,
    PRIMARY KEY (channel, external_id)
);

-- C-04  Admin users and their sessions (the dashboard has no login today: routers/admin.py:20-27 is not applied).   [CODE]
CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash text PRIMARY KEY, source_key text NOT NULL, user_ref uuid, role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL
);

-- ============================================================================
-- DATABASE ROLES (outside SQL files; listed so they are not forgotten)
-- Evidence: both DSNs in the routing dump use user 'postgres' (superuser); CONFIRMED LIVE on 2026-10-03: 'postgres' is the only role on routing_db, godrej and baanganga, all superuser. fetch_all_readonly (db.py:125-131) is a
--           read-only TRANSACTION on that same login, not a read-only role.
-- Propose: app_rw (DML on tenant tables, no DDL), app_ro (SELECT only; used by the SQL guard and named queries),
--          migrator (DDL, used only by tools/migrate.py).
-- ============================================================================
