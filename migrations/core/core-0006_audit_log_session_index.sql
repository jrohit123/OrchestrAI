-- no-transaction
-- core-0006: an index for opening one chat on the dashboard (the Chats screen asks for
-- "every turn of this session, oldest first").
--
-- Without it the database reads the whole chat log to find one conversation. That is quick
-- today (a few hundred rows) but the log grows with every message. CONCURRENTLY builds it
-- without blocking the app, so this file cannot run inside a transaction (first line above).
-- Safe to run twice: IF NOT EXISTS skips an index that is already there.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_log_session
    ON public.audit_log (session_id, created_at);
