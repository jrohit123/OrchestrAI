-- no-transaction
-- core-0002: indexes Godrej has and Baanganga is missing (faster searches only; no rule changes).
--
-- CONCURRENTLY builds each index without blocking the app, so this file cannot run inside a
-- transaction (the first line above tells the tool). Safe to run twice: IF NOT EXISTS skips an
-- index that is already there. Godrej already has all of them, so nothing happens there.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_otp_org                   ON public.otp_tokens (org_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_otp_user_expiry           ON public.otp_tokens (user_id, expires_at);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_approvals_org_requester   ON public.pending_approvals (org_id, requester_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_approvals_org_status      ON public.pending_approvals (org_id, status);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scheduled_reports_next_run ON public.scheduled_reports (next_run_at, is_active);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scheduled_reports_org     ON public.scheduled_reports (org_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scheduled_reports_user    ON public.scheduled_reports (user_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_drafts_expiry        ON public.user_drafts (expires_at)
    WHERE stage NOT IN ('done', 'cancelled');

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_org_id              ON public.users (org_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_phone               ON public.users (phone);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_workflow_drafts_org_status  ON public.workflow_drafts (org_id, status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_workflow_drafts_org_updated ON public.workflow_drafts (org_id, updated_at);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_workflows_org_intent      ON public.workflows (org_id, intent_key);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_workflows_org_kind        ON public.workflows (org_id, kind, is_active);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_workflows_org_type        ON public.workflows (org_id, workflow_type, is_active);
