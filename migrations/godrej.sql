-- godrej.sql
--
-- One-shot schema migration + data cleanup for Godrej's database. Run this
-- once, top to bottom, against Godrej's database only (see routing.sql's
-- data_sources row for godrej — source_key='godrej').
--
-- Safe to re-run in full: every schema statement is IF NOT EXISTS, and the
-- one UPDATE in step 2 only ever matches rows still in the exact
-- inconsistent state it fixes — nothing left to touch on a second run.

-- ════════════════════════════════════════════════════════════════════
-- STEP 1 — SCHEMA CHANGES
-- Backs: draft resumability (based_on_version), the optimistic-concurrency
-- publish check, a minimal version history, and chat-history compaction
-- for long-running drafts.
-- ════════════════════════════════════════════════════════════════════

ALTER TABLE workflow_drafts ADD COLUMN IF NOT EXISTS based_on_version integer;
ALTER TABLE workflow_drafts ADD COLUMN IF NOT EXISTS chat_summary text;

CREATE TABLE IF NOT EXISTS workflow_versions (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id      uuid NOT NULL,
    org_id           uuid NOT NULL,
    version          integer NOT NULL,
    intent_key       text NOT NULL,
    name             text,
    entity_schema    jsonb,
    gates            jsonb,
    granted_roles    text[],
    steps            jsonb,
    calc_rules       jsonb,
    sql_template     text,
    slash_command    text,
    source_draft_id  uuid,
    published_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workflow_versions_workflow
    ON workflow_versions (workflow_id, version);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_drafts_org_intent_active
    ON workflow_drafts (org_id, intent_key)
    WHERE status IN ('chatting', 'ready_for_review') AND intent_key IS NOT NULL;


-- ════════════════════════════════════════════════════════════════════
-- STEP 2 — SAFE DATA FIX (always OK to run)
-- 13 workflow_drafts rows are marked status='published' but have no
-- linked live workflow (published_workflow_id IS NULL). The app only ever
-- sets both together in the same write (see
-- workflow_publisher.publish_draft), so this combination is a pure
-- inconsistency — these drafts never actually made it live. Relabeling to
-- 'abandoned' doesn't delete anything (same status the app's own "Clear
-- unfinished drafts" button already uses) and stops them cluttering the
-- new "Continue a draft" list with entries that lead nowhere.
-- ════════════════════════════════════════════════════════════════════

UPDATE workflow_drafts
SET status = 'abandoned', updated_at = now()
WHERE status = 'published' AND published_workflow_id IS NULL;


-- ════════════════════════════════════════════════════════════════════
-- STEP 3 — NOT auto-applied — read, confirm, then uncomment what you
-- agree with
--
-- Two role permissions match no live workflows.intent_key AND are not
-- referenced anywhere in the Python code (grepped app/ for both strings —
-- zero hits):
--
--   get_resident_cases_status   granted to: owner, tenant
--   view_my_cases                granted to: staff, owner, tenant, member, committee
--
-- Both are almost certainly leftovers from workflow attempts that never
-- went live (the same intent_key-drift bug documented in
-- workflow_builder_agent.py). A resident with owner/tenant who's granted
-- get_resident_cases_status today gets nothing when they try to use it —
-- it's already silently dead; this just makes that official.
--
-- general_read is ALSO unmatched but deliberately left OUT below: it's
-- granted identically across every role in this org, which reads as a
-- deliberate baseline flag rather than a leftover. Don't remove it here
-- without checking with whoever owns this app first.
-- ════════════════════════════════════════════════════════════════════

-- UPDATE roles SET permissions = array_remove(permissions, 'get_resident_cases_status')
--   WHERE org_id = (SELECT id FROM orgs WHERE is_active = true LIMIT 1)
--     AND 'get_resident_cases_status' = ANY(permissions);

-- UPDATE roles SET permissions = array_remove(permissions, 'view_my_cases')
--   WHERE org_id = (SELECT id FROM orgs WHERE is_active = true LIMIT 1)
--     AND 'view_my_cases' = ANY(permissions);


-- ════════════════════════════════════════════════════════════════════
-- STEP 4 — verify (read-only, safe to run any time after the above)
-- ════════════════════════════════════════════════════════════════════

-- Orphaned "published" drafts (expect 0 rows now that step 2 ran):
SELECT id, intent_key, name, updated_at FROM workflow_drafts
WHERE status = 'published' AND published_workflow_id IS NULL;

-- Role permissions matching no live workflow, excluding the known
-- baseline flag (expect only the two named in step 3, until you
-- uncomment and run those):
SELECT r.name AS role, p AS orphaned_permission
FROM roles r, unnest(r.permissions) AS p
WHERE p NOT IN (SELECT intent_key FROM workflows WHERE org_id = r.org_id)
  AND p <> 'general_read';
