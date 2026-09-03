-- ═══════════════════════════════════════════════════════════════════════════
-- MIGRATION 011 — generic constraint "gates" for workflows (BAANGANGA)
--
-- Replaces the two hardcoded scalar columns (otp_threshold, approval_threshold)
-- with an open-ended jsonb array so a workflow can carry any number of safety
-- constraints of any kind — OTP, single- or multi-level approval chains, or a
-- pure permission requirement — instead of exactly one OTP amount and one
-- approval amount.
--
-- gates entry shapes:
--   {"id":"otp1","type":"otp","when":{"field":"$computed.total_amount","gte":50000}}
--
--   {"id":"appr1","type":"approval_chain",
--    "when":{"field":"$computed.total_amount","gte":100000},
--    "levels":[
--      {"level":1,"role":"branch_manager","max_amount":500000},
--      {"level":2,"role":"owner","max_amount":null}
--    ]}
--
--   {"id":"perm1","type":"permission","role_any_of":["finance"]}
--
-- The OLD otp_threshold/approval_threshold/otp_required columns are kept
-- (read-only from the app's perspective going forward) rather than dropped —
-- audit history and any external reporting may still reference them, and
-- app/services/step_interpreter.py falls back to them only when a workflow's
-- gates[] array is empty, so nothing already live breaks mid-rollout.
--
-- pending_approvals gets gate_id/level so a multi-level chain can track which
-- stage is currently pending, instead of a single implicit one-shot approval.
--
-- roles gets approval_max_amount — an optional per-role cap surfaced in the
-- admin panel's "who can approve what, up to how much" view. Not required by
-- the execution engine itself (gates reference roles by name directly), it's
-- informational/administrative.
--
-- Org: Baanganga (data_sources.source_key = 'baanganga')
-- Run this against the Baanganga database directly.
-- ═══════════════════════════════════════════════════════════════════════════
BEGIN;

ALTER TABLE public.workflows
    ADD COLUMN IF NOT EXISTS gates jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE public.workflow_drafts
    ADD COLUMN IF NOT EXISTS gates jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE public.pending_approvals
    ADD COLUMN IF NOT EXISTS gate_id text,
    ADD COLUMN IF NOT EXISTS level integer NOT NULL DEFAULT 1;

ALTER TABLE public.roles
    ADD COLUMN IF NOT EXISTS approval_max_amount numeric(12,2);

-- ── Backfill: convert existing single-threshold workflows into gates[] ──────
-- Idempotent: only touches rows whose gates is still the default '[]' and
-- which actually had a legacy threshold set. Approver role defaults to
-- 'owner' — the same fallback workflow_publisher.py already uses when no
-- roles are explicitly granted, so behaviour for existing workflows doesn't
-- change: the same role that could approve before still can.
UPDATE public.workflows
SET gates = (
    SELECT COALESCE(jsonb_agg(g), '[]'::jsonb)
    FROM (
        SELECT jsonb_build_object(
            'id', 'otp_legacy', 'type', 'otp',
            'when', jsonb_build_object('field', '$computed.total_amount', 'gte', otp_threshold)
        ) AS g
        WHERE otp_required IS TRUE AND otp_threshold IS NOT NULL

        UNION ALL

        SELECT jsonb_build_object(
            'id', 'appr_legacy', 'type', 'approval_chain',
            'when', jsonb_build_object('field', '$computed.total_amount', 'gte', approval_threshold),
            'levels', jsonb_build_array(
                jsonb_build_object('level', 1, 'role', 'owner', 'max_amount', NULL)
            )
        ) AS g
        WHERE approval_threshold IS NOT NULL
    ) sub
)
WHERE gates = '[]'::jsonb
  AND (otp_threshold IS NOT NULL OR approval_threshold IS NOT NULL);

UPDATE public.workflow_drafts
SET gates = (
    SELECT COALESCE(jsonb_agg(g), '[]'::jsonb)
    FROM (
        SELECT jsonb_build_object(
            'id', 'otp_legacy', 'type', 'otp',
            'when', jsonb_build_object('field', '$computed.total_amount', 'gte', otp_threshold)
        ) AS g
        WHERE otp_required IS TRUE AND otp_threshold IS NOT NULL

        UNION ALL

        SELECT jsonb_build_object(
            'id', 'appr_legacy', 'type', 'approval_chain',
            'when', jsonb_build_object('field', '$computed.total_amount', 'gte', approval_threshold),
            'levels', jsonb_build_array(
                jsonb_build_object('level', 1, 'role', 'owner', 'max_amount', NULL)
            )
        ) AS g
        WHERE approval_threshold IS NOT NULL
    ) sub
)
WHERE gates = '[]'::jsonb
  AND (otp_threshold IS NOT NULL OR approval_threshold IS NOT NULL);

COMMIT;

-- ═══════════════════════════════════════════════════════════════════════════
-- POST-DEPLOY VERIFICATION
-- ═══════════════════════════════════════════════════════════════════════════
-- SELECT intent_key, otp_threshold, approval_threshold, gates FROM workflows
--   WHERE otp_threshold IS NOT NULL OR approval_threshold IS NOT NULL;
-- Every row should now show a non-empty gates[] mirroring its old thresholds.
