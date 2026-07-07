-- ============================================================================
-- OrchestrAI — Fresh Start Migration
-- Run as a single transaction. Safe to run once on the existing database.
-- What it does:
--   1. Drops all wrong single-column UNIQUE constraints (multi-tenant fixes)
--   2. Fixes column defects (defaults, timestamptz, missing FKs, trgm indexes)
--   3. Adds: menu/command columns, user_drafts table, org config columns,
--      roles.readable_tables, workflow_drafts additions
--   4. Wipes: workflows, workflow_drafts, pending_approvals, otp_tokens,
--      audit_log; resets role permissions to {general_read}
-- ============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─────────────────────────────────────────────────────────────────────────
-- 1. DROP WRONG SINGLE-COLUMN UNIQUE CONSTRAINTS
--    Dynamically finds and drops every 1-column UNIQUE on the listed tables,
--    regardless of what the export tool named them.
--    Exceptions kept: users.phone (resolve_identity assumes global unique),
--    orgs.slug (intentionally global).
-- ─────────────────────────────────────────────────────────────────────────
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.conrelid::regclass::text AS tbl, c.conname, a.attname
    FROM pg_constraint c
    JOIN pg_attribute a
      ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
    WHERE c.contype = 'u'
      AND array_length(c.conkey, 1) = 1
      AND c.conrelid::regclass::text = ANY (ARRAY[
        'credentials','inventory','invoices','orders',
        'roles','users','workflows','quotations'
      ])
  LOOP
    IF r.tbl = 'users' AND r.attname = 'phone' THEN
      CONTINUE;  -- keep: code resolves identity by phone alone
    END IF;
    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', r.tbl, r.conname);
    RAISE NOTICE 'Dropped bad unique: %.%  (%)', r.tbl, r.conname, r.attname;
  END LOOP;
END $$;

-- Belt-and-braces: standalone unique indexes with the conventional names
DROP INDEX IF EXISTS credentials_org_id_key;
DROP INDEX IF EXISTS credentials_adapter_name_key;
DROP INDEX IF EXISTS inventory_org_id_key;
DROP INDEX IF EXISTS inventory_sku_key;
DROP INDEX IF EXISTS invoices_org_id_key;
DROP INDEX IF EXISTS invoices_invoice_number_key;
DROP INDEX IF EXISTS orders_org_id_key;
DROP INDEX IF EXISTS orders_order_number_key;
DROP INDEX IF EXISTS roles_org_id_key;
DROP INDEX IF EXISTS roles_name_key;
DROP INDEX IF EXISTS users_org_id_key;
DROP INDEX IF EXISTS workflows_org_id_key;
DROP INDEX IF EXISTS workflows_intent_key_key;
DROP INDEX IF EXISTS quotations_quotation_number_key;

-- Quotation numbers unique per org (replaces the global unique just dropped)
ALTER TABLE quotations
  ADD CONSTRAINT quotations_org_id_quotation_number_key
  UNIQUE (org_id, quotation_number);

-- ─────────────────────────────────────────────────────────────────────────
-- 2. FIX DEFECTS
-- ─────────────────────────────────────────────────────────────────────────

-- workflows: broken string default, remove opinionated default, drop dead cols
ALTER TABLE workflows ALTER COLUMN otp_threshold DROP DEFAULT;
ALTER TABLE workflows ALTER COLUMN approval_threshold DROP DEFAULT;
ALTER TABLE workflows DROP COLUMN IF EXISTS trigger_patterns;
ALTER TABLE workflows DROP COLUMN IF EXISTS adapter_method;

-- quotations: align timestamps with the rest of the schema
ALTER TABLE quotations
  ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE 'Asia/Kolkata',
  ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE 'Asia/Kolkata';

-- otp_tokens: add org scoping (table is wiped below, so NOT NULL is safe)
TRUNCATE otp_tokens;
ALTER TABLE otp_tokens
  ADD COLUMN IF NOT EXISTS org_id uuid NOT NULL
  REFERENCES orgs(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_otp_org ON otp_tokens (org_id);

-- audit_log: real FKs (wiping old rows so orphans can't block the FK add)
TRUNCATE audit_log;
ALTER TABLE audit_log
  ADD CONSTRAINT audit_log_org_id_fkey
  FOREIGN KEY (org_id) REFERENCES orgs(id) ON DELETE CASCADE;
ALTER TABLE audit_log
  ADD CONSTRAINT audit_log_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;

-- orders: missing FK to quotations
ALTER TABLE orders
  ADD CONSTRAINT orders_quotation_id_fkey
  FOREIGN KEY (quotation_id) REFERENCES quotations(id) ON DELETE SET NULL;

-- trigram indexes: recreate with the correct operator class
DROP INDEX IF EXISTS idx_customers_name_trgm;
DROP INDEX IF EXISTS idx_inventory_name_trgm;
CREATE INDEX idx_customers_name_trgm ON customers USING gin (name gin_trgm_ops);
CREATE INDEX idx_inventory_name_trgm ON inventory USING gin (name gin_trgm_ops);

-- pending_approvals: "my pending requests" lookups
CREATE INDEX IF NOT EXISTS idx_approvals_org_requester
  ON pending_approvals (org_id, requester_id);

-- ─────────────────────────────────────────────────────────────────────────
-- 3. ADDITIONS
-- ─────────────────────────────────────────────────────────────────────────

-- orgs: tunable config (columns for common knobs, jsonb for everything else)
ALTER TABLE orgs
  ADD COLUMN IF NOT EXISTS context_message_limit integer NOT NULL DEFAULT 12,
  ADD COLUMN IF NOT EXISTS settings jsonb NOT NULL DEFAULT '{}';

-- workflows: menu + command registry (the DB *is* the menu)
ALTER TABLE workflows
  ADD COLUMN IF NOT EXISTS slash_command varchar(32),
  ADD COLUMN IF NOT EXISTS command_description varchar(80),
  ADD COLUMN IF NOT EXISTS menu_section varchar(30) NOT NULL DEFAULT 'other';
CREATE UNIQUE INDEX IF NOT EXISTS workflows_org_slash_cmd
  ON workflows (org_id, slash_command)
  WHERE slash_command IS NOT NULL AND is_active;

-- workflow_drafts: mirror the new columns + traceability to published row
ALTER TABLE workflow_drafts
  ADD COLUMN IF NOT EXISTS slash_command varchar(32),
  ADD COLUMN IF NOT EXISTS command_description varchar(80),
  ADD COLUMN IF NOT EXISTS menu_section varchar(30),
  ADD COLUMN IF NOT EXISTS published_workflow_id uuid REFERENCES workflows(id) ON DELETE SET NULL;

-- roles: data-driven table access (replaces hardcoded ROLE_READ_ACCESS dict)
ALTER TABLE roles
  ADD COLUMN IF NOT EXISTS readable_tables text[] NOT NULL DEFAULT '{}';

-- user_drafts: end-user in-progress actions — Postgres is source of truth,
-- Redis is just a cache. Fixes the "TTL expiry wipes half-collected invoice" bug.
CREATE TABLE IF NOT EXISTS user_drafts (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id               uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  user_id              uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  intent_key           text NOT NULL,
  fields               jsonb NOT NULL DEFAULT '{}',
  stage                varchar(30) NOT NULL DEFAULT 'collecting',
  conversation_summary text,
  updated_at           timestamptz NOT NULL DEFAULT now(),
  expires_at           timestamptz NOT NULL DEFAULT now() + interval '24 hours',
  CONSTRAINT user_drafts_stage_check CHECK (stage IN
    ('collecting','awaiting_confirmation','awaiting_otp',
     'awaiting_approval','done','cancelled'))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_draft_per_user
  ON user_drafts (org_id, user_id)
  WHERE stage NOT IN ('done','cancelled');
CREATE INDEX IF NOT EXISTS idx_user_drafts_expiry ON user_drafts (expires_at);

-- ─────────────────────────────────────────────────────────────────────────
-- 4. WIPE + RESEED BASELINE
-- ─────────────────────────────────────────────────────────────────────────

DELETE FROM pending_approvals;          -- references workflows
DELETE FROM workflow_drafts;
DELETE FROM workflows;

-- Every role: can ask ad-hoc read questions, cannot trigger any workflow.
-- Workflow intent_keys are re-granted automatically at publish time.
UPDATE roles SET permissions = '{general_read}';

-- Data-driven table access per role (was ROLE_READ_ACCESS in identity.py)
UPDATE roles SET readable_tables =
  '{customers,invoices,inventory,orders,quotations}' WHERE name = 'owner';
UPDATE roles SET readable_tables =
  '{customers,invoices,inventory,orders,quotations}' WHERE name = 'accountant';
UPDATE roles SET readable_tables =
  '{customers,inventory,orders,quotations}'          WHERE name = 'sales';
UPDATE roles SET readable_tables =
  '{inventory}'                                      WHERE name = 'warehouse';

COMMIT;

-- ── Post-run sanity checks (read-only, run manually) ──
-- SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--   WHERE conrelid='workflows'::regclass AND contype='u';   -- expect ONLY (org_id,intent_key)
-- SELECT name, permissions, readable_tables FROM roles;
-- SELECT count(*) FROM workflows;                            -- expect 0
