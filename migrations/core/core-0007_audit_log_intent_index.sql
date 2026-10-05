-- no-transaction
-- core-0007: an index for the "Last used" column on the dashboard's Workflows screen, which
-- asks the chat log for the newest row of every workflow (one lookup per workflow).
--
-- Without it each lookup reads every chat-log row of the business, so the screen slows down
-- as the log grows. CONCURRENTLY builds it without blocking the app, so this file cannot
-- run inside a transaction (first line above). Safe to run twice (IF NOT EXISTS).

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_intent
    ON public.audit_log (org_id, intent_key, created_at);
