-- core-0001: make the tables Godrej and Baanganga share look the same (additions only).
--
-- Safe to run twice. Nothing is dropped, renamed or changed. Every new column has a
-- default or may be empty, so the app works the same before and after. Where a database
-- already has an item, the line does nothing.

-- Baanganga was missing these columns (Godrej has them) -------------------------------
ALTER TABLE public.user_drafts       ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.workflows         ADD COLUMN IF NOT EXISTS kind       text        NOT NULL DEFAULT 'workflow';
ALTER TABLE public.workflows         ADD COLUMN IF NOT EXISTS settings   jsonb       NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.workflow_drafts   ADD COLUMN IF NOT EXISTS kind       text        NOT NULL DEFAULT 'workflow';
ALTER TABLE public.workflow_drafts   ADD COLUMN IF NOT EXISTS settings   jsonb       NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.workflow_versions ADD COLUMN IF NOT EXISTS kind       text;
ALTER TABLE public.workflow_versions ADD COLUMN IF NOT EXISTS settings   jsonb;

-- Godrej was missing this column (Baanganga has it; the app does not read it) ----------
ALTER TABLE public.scheduled_reports ADD COLUMN IF NOT EXISTS source_key varchar(255) DEFAULT 'platform';

-- The allowed values of "kind" (Godrej already has these three rules). Existing rows all
-- carry the default 'workflow', so they pass. ------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'workflows_kind_check'
                     AND conrelid = 'public.workflows'::regclass) THEN
        ALTER TABLE public.workflows ADD CONSTRAINT workflows_kind_check
            CHECK (kind IN ('workflow', 'block', 'case_action'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'workflow_drafts_kind_check'
                     AND conrelid = 'public.workflow_drafts'::regclass) THEN
        ALTER TABLE public.workflow_drafts ADD CONSTRAINT workflow_drafts_kind_check
            CHECK (kind IN ('workflow', 'block', 'case_action'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'workflow_versions_kind_check'
                     AND conrelid = 'public.workflow_versions'::regclass) THEN
        ALTER TABLE public.workflow_versions ADD CONSTRAINT workflow_versions_kind_check
            CHECK (kind IS NULL OR kind IN ('workflow', 'block', 'case_action'));
    END IF;
END $$;

-- The dashboard's "who changed what" log. Godrej has it, Baanganga did not. Once it
-- exists, Baanganga's dashboard starts showing its Activity log (the dashboard checks
-- whether this table is there). Same columns, keys and indexes as Godrej. --------------
CREATE TABLE IF NOT EXISTS public.admin_events (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    actor_user_id uuid REFERENCES public.users (id) ON DELETE SET NULL,
    actor_label   text,
    area          text NOT NULL,
    action        text NOT NULL,
    target_type   text,
    target_id     text,
    summary       text NOT NULL,
    before_state  jsonb,
    after_state   jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_admin_events_org_time ON public.admin_events (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_events_target   ON public.admin_events (org_id, target_type, target_id);
COMMENT ON TABLE public.admin_events IS 'Who changed what in the admin dashboard. Chat turns are in audit_log.';
