-- core-0026: flows that start by themselves.
--
-- Additions only. Three new tables, empty. A flow can start in one of three ways: someone does it
-- (nothing is stored for that, as today), it runs on a schedule, or it runs after another flow
-- finishes.
--
--   flow_schedules  one row per scheduled flow: the cadence (every day / week / month at a time,
--                   optionally only on working days), when it runs next and when it last ran. The
--                   every-minute job in app/scheduler/jobs.py moves next_run_at on BEFORE it runs the
--                   flow, so a flow never runs twice for one slot, and a missed slot runs once.
--   flow_chains     one row per flow that starts after another flow finishes. A flow has at most one
--                   "after" flow, which also makes a loop easy to see and refuse.
--   flow_runs       a plain log of what the two above (and "Run it now") did: when, how it started,
--                   success / failed / skipped, and the words that say why.
--
-- Nothing reads or writes these tables until the app is deployed; an old app ignores them. Safe to
-- run twice.

CREATE TABLE IF NOT EXISTS public.flow_schedules (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,
    workflow_id  uuid NOT NULL UNIQUE REFERENCES public.workflows(id) ON DELETE CASCADE,
    cadence      jsonb NOT NULL,
    is_active    boolean NOT NULL DEFAULT true,
    next_run_at  timestamptz,
    last_run_at  timestamptz,
    created_by   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_flow_schedules_due
    ON public.flow_schedules (next_run_at)
    WHERE is_active;

CREATE TABLE IF NOT EXISTS public.flow_chains (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,
    workflow_id       uuid NOT NULL UNIQUE REFERENCES public.workflows(id) ON DELETE CASCADE,
    after_workflow_id uuid NOT NULL REFERENCES public.workflows(id) ON DELETE CASCADE,
    created_by        text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT flow_chains_not_itself CHECK (workflow_id <> after_workflow_id)
);

CREATE INDEX IF NOT EXISTS idx_flow_chains_after
    ON public.flow_chains (after_workflow_id);

CREATE TABLE IF NOT EXISTS public.flow_runs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,
    workflow_id   uuid NOT NULL REFERENCES public.workflows(id) ON DELETE CASCADE,
    how_started   text NOT NULL,
    status        text NOT NULL,
    message       text,
    caused_by_id  uuid,
    depth         integer NOT NULL DEFAULT 0,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    CONSTRAINT flow_runs_how_check CHECK (how_started IN ('schedule', 'manual', 'after_flow')),
    CONSTRAINT flow_runs_status_check CHECK (status IN ('success', 'failed', 'skipped'))
);

CREATE INDEX IF NOT EXISTS idx_flow_runs_flow
    ON public.flow_runs (workflow_id, started_at DESC);
