-- ═══════════════════════════════════════════════════════════════════════════
-- MIGRATION 009 — per-org OTP configuration + drop orphaned schedule columns
--
-- Part 1: OTP behaviour (expiry, max attempts, digit length, resend cooldown)
-- was previously hardcoded as module-level constants in
-- app/services/otp_service.py. This adds per-org columns so each tenant can
-- tune OTP behaviour independently, matching the existing pattern of
-- session_ttl_minutes / context_message_limit / gst_rate on this table.
--
-- Part 2: workflows.is_scheduled / workflows.schedule_cron are populated by
-- migration 002 but are never read anywhere in app/ — all real scheduling
-- goes through the separate scheduled_reports table instead. Dropping them
-- to remove the orphaned/ambiguous config surface.
--
-- Applies to: BOTH tenant databases (baanganga, godrej_emerald) — each has
-- its own `orgs` and `workflows` tables per the routing_db.data_sources
-- mapping. Run this migration against each database separately.
-- ═══════════════════════════════════════════════════════════════════════════
BEGIN;

ALTER TABLE public.orgs
    ADD COLUMN IF NOT EXISTS otp_expiry_minutes integer NOT NULL DEFAULT 3,
    ADD COLUMN IF NOT EXISTS otp_max_attempts integer NOT NULL DEFAULT 3,
    ADD COLUMN IF NOT EXISTS otp_length integer NOT NULL DEFAULT 4,
    ADD COLUMN IF NOT EXISTS otp_resend_cooldown_seconds integer NOT NULL DEFAULT 60;

ALTER TABLE public.workflows
    DROP COLUMN IF EXISTS is_scheduled,
    DROP COLUMN IF EXISTS schedule_cron;

COMMIT;
