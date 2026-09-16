-- baanganga.sql
--
-- One-shot schema migration for Baanganga's database. Run this once, top
-- to bottom, against Baanganga's database only (see routing.sql's
-- data_sources row for baanganga — source_key='baanganga').
--
-- Safe to re-run in full: every schema statement is IF NOT EXISTS.

-- ════════════════════════════════════════════════════════════════════
-- STEP 1 — SCHEMA CHANGES
-- Identical to what's needed on Godrej's database — both orgs share the
-- exact same workflow_drafts/workflows/roles column layout (checked
-- directly against both dumps). Backs: draft resumability
-- (based_on_version), the optimistic-concurrency publish check, a minimal
-- version history, and chat-history compaction for long-running drafts.
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
-- STEP 2 — data cleanup: nothing to do, checked directly against the dump
--
-- workflow_drafts has ZERO rows in this database — every one of this
-- org's 8 live workflows (create_purchase_order,
-- update_purchase_order_status, cancel_purchase_order,
-- generate_price_quotation, create_sales_invoice, generate_aging_report,
-- pending_orders, check_stock) exists with no draft/chat history behind it
-- at all — a stronger version of the same "entered directly" pattern
-- Godrej also had, just with no draft trail left behind here to clean up.
-- Every role's permissions[] already matches a real live
-- workflows.intent_key, except general_read — granted identically to all
-- four roles, the same deliberate baseline flag seen in Godrej, not a
-- leftover.
-- ════════════════════════════════════════════════════════════════════

-- (nothing to run in this step)


-- ════════════════════════════════════════════════════════════════════
-- STEP 3 — verify (read-only, safe to re-run any time as this org starts
-- actually using the chat builder)
-- ════════════════════════════════════════════════════════════════════

SELECT id, intent_key, name, updated_at FROM workflow_drafts
WHERE status = 'published' AND published_workflow_id IS NULL;
-- expect: 0 rows

SELECT r.name AS role, p AS orphaned_permission
FROM roles r, unnest(r.permissions) AS p
WHERE p NOT IN (SELECT intent_key FROM workflows WHERE org_id = r.org_id)
  AND p <> 'general_read';
-- expect: 0 rows
