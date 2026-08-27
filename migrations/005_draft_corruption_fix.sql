-- ═══════════════════════════════════════════════════════════════════════════
-- MIGRATION 005 — one ACTIVE draft per user (not one draft per user, ever)
-- ═══════════════════════════════════════════════════════════════════════════
BEGIN;

-- Existing done/cancelled rows currently occupy the single slot per user.
-- Nothing reads them; drop them so the partial index can be created cleanly.
DELETE FROM user_drafts WHERE stage IN ('done', 'cancelled');

ALTER TABLE user_drafts DROP CONSTRAINT IF EXISTS one_active_draft_per_user;

CREATE UNIQUE INDEX one_active_draft_per_user
    ON user_drafts (org_id, user_id)
    WHERE stage NOT IN ('done', 'cancelled');

-- Track when a draft was started, so _is_draft_stale can actually work.
ALTER TABLE user_drafts
    ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_user_drafts_expiry
    ON user_drafts (expires_at) WHERE stage NOT IN ('done','cancelled');

COMMIT;