-- core-0003: baseline check. Changes nothing.
--
-- If this file is recorded as applied, the database had every column, "kind" rule, index and
-- table that core-0001 and core-0002 add, and no index was left half-built. If anything is
-- missing it stops with the list, and the whole run for this database is undone.

DO $$
DECLARE
    item    record;
    missing text[] := ARRAY[]::text[];
BEGIN
    FOR item IN
        SELECT * FROM (VALUES
            ('user_drafts', 'created_at'),
            ('workflows', 'kind'), ('workflows', 'settings'),
            ('workflow_drafts', 'kind'), ('workflow_drafts', 'settings'),
            ('workflow_versions', 'kind'), ('workflow_versions', 'settings'),
            ('scheduled_reports', 'source_key')
        ) AS c (tbl, col)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public'
                         AND table_name = item.tbl AND column_name = item.col) THEN
            missing := missing || ('column ' || item.tbl || '.' || item.col);
        END IF;
    END LOOP;

    FOR item IN
        SELECT * FROM (VALUES
            ('workflows', 'workflows_kind_check'),
            ('workflow_drafts', 'workflow_drafts_kind_check'),
            ('workflow_versions', 'workflow_versions_kind_check')
        ) AS k (tbl, name)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = item.name
                         AND conrelid = ('public.' || item.tbl)::regclass) THEN
            missing := missing || ('rule ' || item.name);
        END IF;
    END LOOP;

    IF to_regclass('public.admin_events') IS NULL THEN
        missing := missing || 'table admin_events'::text;
    END IF;

    FOR item IN
        SELECT * FROM (VALUES
            ('idx_otp_org'), ('idx_otp_user_expiry'),
            ('idx_approvals_org_requester'), ('idx_approvals_org_status'),
            ('idx_scheduled_reports_next_run'), ('idx_scheduled_reports_org'),
            ('idx_scheduled_reports_user'), ('idx_user_drafts_expiry'),
            ('idx_users_org_id'), ('idx_users_phone'),
            ('idx_workflow_drafts_org_status'), ('idx_workflow_drafts_org_updated'),
            ('idx_workflows_org_intent'), ('idx_workflows_org_kind'), ('idx_workflows_org_type'),
            ('idx_admin_events_org_time'), ('idx_admin_events_target')
        ) AS i (name)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_index x
                       JOIN pg_class c ON c.oid = x.indexrelid
                       JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname = 'public' AND c.relname = item.name AND x.indisvalid) THEN
            missing := missing || ('index ' || item.name);
        END IF;
    END LOOP;

    IF cardinality(missing) > 0 THEN
        RAISE EXCEPTION 'baseline check failed, missing: %', array_to_string(missing, ', ');
    END IF;
END $$;
