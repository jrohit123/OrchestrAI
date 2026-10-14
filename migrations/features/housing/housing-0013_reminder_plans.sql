-- Godrej only: the time to fix (TAT) of a ticket, and reminder plans that act at a share of it.
--
-- A plan is a list of steps such as "at 25% of the time to fix, remind the handler and tell the backup" or "at 40%, if
-- nobody has acted, give it to the backup". A share works for every ticket, whether it has 2 hours or 3 months. One plan is
-- the default; a kind of ticket may have its own. A step with every_minutes instead repeats, for tickets with no time limit.
--
-- What this file adds:
--   case_categories.no_time_limit   a kind (and the kinds under it) can have no time to fix: its tickets get no due time
--   cases: tat_started_at, assigned_at, tat_paused_at, tat_paused_minutes, tat_cycle
--                                   kept by a trigger, so no flow has to change: when the clock started, when the current
--                                   handler got it, a pause while the status is one of reminders.pause_statuses, and a fresh
--                                   clock (and fresh reminders) when a closed ticket is reopened
--   reminder_plans, reminder_plan_categories, reminder_plan_steps, case_reminder_log (one row per step per ticket, so a
--                                   step never runs twice)
--   case_activity may say 'reminder'
--   orgs.settings.reminders = {"enabled": false, ...} and a starting "Standard plan"
--
-- Nothing changes for anybody until orgs.settings.reminders.enabled is set to true: until then the plans are not run and
-- today's case_reminders job goes on as before. Safe to run twice.

-- ── 1. a kind of ticket can have no time limit ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.case_categories ADD COLUMN IF NOT EXISTS no_time_limit boolean NOT NULL DEFAULT false;

-- The nearest kind up the chain (itself first) that says something decides: no limit, or a number of minutes.
CREATE OR REPLACE FUNCTION public.case_category_no_limit(p_category uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE chain AS (
        SELECT c.id, c.parent_id, c.target_minutes, c.no_time_limit, 0 AS hop
          FROM public.case_categories c WHERE c.id = p_category
        UNION ALL
        SELECT p.id, p.parent_id, p.target_minutes, p.no_time_limit, ch.hop + 1
          FROM public.case_categories p JOIN chain ch ON p.id = ch.parent_id
         WHERE ch.hop < 10
    )
    SELECT COALESCE((SELECT no_time_limit FROM chain
                      WHERE no_time_limit OR target_minutes IS NOT NULL
                      ORDER BY hop LIMIT 1), false)
$$;

-- ── 2. the clock on each ticket ────────────────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.cases ADD COLUMN IF NOT EXISTS tat_started_at timestamptz;
ALTER TABLE public.cases ADD COLUMN IF NOT EXISTS assigned_at timestamptz;
ALTER TABLE public.cases ADD COLUMN IF NOT EXISTS tat_paused_at timestamptz;
ALTER TABLE public.cases ADD COLUMN IF NOT EXISTS tat_paused_minutes integer NOT NULL DEFAULT 0;
ALTER TABLE public.cases ADD COLUMN IF NOT EXISTS tat_cycle integer NOT NULL DEFAULT 0;

-- tickets that exist already: the clock started when they were raised; the handler got it at the last hand-over
UPDATE public.cases SET tat_started_at = COALESCE(created_at, now()) WHERE tat_started_at IS NULL;
UPDATE public.cases c
   SET assigned_at = COALESCE((SELECT max(a.created_at) FROM public.case_activity a
                                WHERE a.case_id = c.id AND a.activity_type = 'assignment'), c.created_at)
 WHERE c.assigned_at IS NULL AND c.assigned_to_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.cases_tat_clock() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    cfg         jsonb;
    pause_list  jsonb;
    closed_list jsonb;
    mins        integer;
BEGIN
    SELECT o.settings INTO cfg FROM public.orgs o WHERE o.id = NEW.org_id;
    pause_list  := COALESCE(cfg #> '{reminders,pause_statuses}', '[]'::jsonb);
    closed_list := COALESCE(cfg #> '{case_reminders,closed_values}', '["closed"]'::jsonb);
    IF jsonb_typeof(pause_list) IS DISTINCT FROM 'array' THEN pause_list := '[]'::jsonb; END IF;
    IF jsonb_typeof(closed_list) IS DISTINCT FROM 'array' THEN closed_list := '["closed"]'::jsonb; END IF;

    IF TG_OP = 'INSERT' THEN
        NEW.tat_started_at := COALESCE(NEW.tat_started_at, NEW.created_at, now());
        IF NEW.assigned_to_id IS NOT NULL THEN
            NEW.assigned_at := COALESCE(NEW.assigned_at, now());
        END IF;
    ELSE
        IF NEW.assigned_to_id IS DISTINCT FROM OLD.assigned_to_id THEN
            NEW.assigned_at := CASE WHEN NEW.assigned_to_id IS NULL THEN NULL ELSE now() END;
        END IF;
        IF closed_list ? OLD.status::text AND NOT closed_list ? NEW.status::text THEN
            -- reopened: a fresh clock of the same length, and the reminder steps may run again (next cycle)
            IF OLD.due_date IS NOT NULL AND OLD.tat_started_at IS NOT NULL THEN
                NEW.due_date := now() + ((OLD.due_date - OLD.tat_started_at) - make_interval(mins => OLD.tat_paused_minutes));
            END IF;
            NEW.tat_started_at := now();
            NEW.tat_paused_minutes := 0;
            NEW.tat_paused_at := NULL;
            NEW.tat_cycle := OLD.tat_cycle + 1;
        ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
            IF pause_list ? NEW.status::text THEN
                IF OLD.tat_paused_at IS NULL THEN
                    NEW.tat_paused_at := now();      -- waiting for someone else: the clock stops
                END IF;
            ELSIF OLD.tat_paused_at IS NOT NULL THEN
                -- the clock runs again, and the due time moves on by the time it was stopped
                mins := ceil(extract(epoch FROM now() - OLD.tat_paused_at) / 60)::integer;
                NEW.tat_paused_minutes := OLD.tat_paused_minutes + mins;
                IF NEW.due_date IS NOT NULL THEN
                    NEW.due_date := NEW.due_date + make_interval(mins => mins);
                END IF;
                NEW.tat_paused_at := NULL;
            END IF;
        END IF;
    END IF;

    -- a kind with no time limit gives its tickets no due time, whatever the flow worked out
    IF NEW.category_id IS NOT NULL AND NEW.due_date IS NOT NULL
       AND (TG_OP = 'INSERT' OR NEW.category_id IS DISTINCT FROM OLD.category_id OR NEW.due_date IS DISTINCT FROM OLD.due_date)
       AND public.case_category_no_limit(NEW.category_id) THEN
        NEW.due_date := NULL;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_cases_tat_clock ON public.cases;
CREATE TRIGGER trg_cases_tat_clock BEFORE INSERT OR UPDATE ON public.cases
    FOR EACH ROW EXECUTE FUNCTION public.cases_tat_clock();

-- ── 3. reminder plans ──────────────────────────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.reminder_plans (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    name         text NOT NULL,
    record_type  text NOT NULL DEFAULT 'cases',
    is_default   boolean NOT NULL DEFAULT false,
    is_active    boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reminder_plans_record_type_check CHECK (record_type IN ('cases')),
    CONSTRAINT reminder_plans_name_key UNIQUE (org_id, record_type, name)
);
-- one default plan per organisation and kind of record
CREATE UNIQUE INDEX IF NOT EXISTS reminder_plans_one_default ON public.reminder_plans (org_id, record_type) WHERE is_default;

-- kinds of ticket that have their own plan; a kind belongs to at most one plan
CREATE TABLE IF NOT EXISTS public.reminder_plan_categories (
    plan_id      uuid NOT NULL REFERENCES public.reminder_plans (id) ON DELETE CASCADE,
    category_id  uuid NOT NULL REFERENCES public.case_categories (id) ON DELETE CASCADE,
    org_id       uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    PRIMARY KEY (plan_id, category_id),
    CONSTRAINT reminder_plan_categories_one_plan UNIQUE (org_id, category_id)
);

-- at_percent: a share of the time to fix (25, 40, 100, 150…), for tickets with a due time.
-- every_minutes: repeats while the ticket is open, for tickets with no time limit.
-- actions, a list such as [{"do": "remind"}, {"do": "tell", "to": "backup"}, {"do": "reassign", "to": "backup"},
--   {"do": "tell", "to": "raiser"}, {"do": "tell", "to": "also"}, {"do": "tell", "role_id": "…"}, {"do": "raise_priority"}]
CREATE TABLE IF NOT EXISTS public.reminder_plan_steps (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    plan_id        uuid NOT NULL REFERENCES public.reminder_plans (id) ON DELETE CASCADE,
    sort_order     integer NOT NULL DEFAULT 0,
    at_percent     numeric(6, 2),
    every_minutes  integer,
    only_if        text NOT NULL DEFAULT 'always',
    actions        jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_active      boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reminder_plan_steps_when_check CHECK (num_nonnulls(at_percent, every_minutes) = 1),
    CONSTRAINT reminder_plan_steps_percent_check CHECK (at_percent IS NULL OR (at_percent > 0 AND at_percent <= 1000)),
    CONSTRAINT reminder_plan_steps_every_check CHECK (every_minutes IS NULL OR every_minutes >= 60),
    CONSTRAINT reminder_plan_steps_only_if_check CHECK (only_if IN ('always', 'no_action', 'not_started')),
    CONSTRAINT reminder_plan_steps_actions_check CHECK (jsonb_typeof(actions) = 'array')
);
CREATE INDEX IF NOT EXISTS idx_reminder_plan_steps_plan ON public.reminder_plan_steps (plan_id, sort_order);

-- what each step did to each ticket: done, skipped (its condition was not met) or failed (nobody could be reached)
CREATE TABLE IF NOT EXISTS public.case_reminder_log (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    case_id    uuid NOT NULL REFERENCES public.cases (id) ON DELETE CASCADE,
    step_id    uuid REFERENCES public.reminder_plan_steps (id) ON DELETE SET NULL,
    tat_cycle  integer NOT NULL DEFAULT 0,
    repeat_no  integer NOT NULL DEFAULT 0,
    fired_at   timestamptz NOT NULL DEFAULT now(),
    outcome    text NOT NULL,
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT case_reminder_log_outcome_check CHECK (outcome IN ('done', 'skipped', 'failed'))
);
CREATE UNIQUE INDEX IF NOT EXISTS case_reminder_log_once
    ON public.case_reminder_log (case_id, step_id, tat_cycle, repeat_no) WHERE step_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_case_reminder_log_case ON public.case_reminder_log (case_id, fired_at);

-- ── 4. the ticket's timeline can say "reminder" ────────────────────────────────────────────────────────────────────────
ALTER TABLE public.case_activity DROP CONSTRAINT IF EXISTS case_activity_type_check;
ALTER TABLE public.case_activity ADD CONSTRAINT case_activity_type_check
    CHECK (activity_type IN ('comment', 'evidence', 'status_change', 'assignment', 'priority_change',
                             'category_change', 'escalation', 'reopen', 'reminder'));

-- ── 5. the switch (off) and a starting plan ────────────────────────────────────────────────────────────────────────────
UPDATE public.orgs
   SET settings = COALESCE(settings, '{}'::jsonb) || jsonb_build_object('reminders', jsonb_build_object(
           'enabled', false,
           'quiet_hours', jsonb_build_object('from', '22:00', 'to', '07:00'),
           'pause_statuses', '[]'::jsonb))
 WHERE NOT (COALESCE(settings, '{}'::jsonb) ? 'reminders');

INSERT INTO public.reminder_plans (org_id, name, is_default)
SELECT o.id, 'Standard plan', true
  FROM public.orgs o
 WHERE NOT EXISTS (SELECT 1 FROM public.reminder_plans p WHERE p.org_id = o.id AND p.record_type = 'cases');

INSERT INTO public.reminder_plan_steps (org_id, plan_id, sort_order, at_percent, every_minutes, only_if, actions)
SELECT p.org_id, p.id, s.sort_order, s.at_percent, s.every_minutes, s.only_if, s.actions::jsonb
  FROM public.reminder_plans p
 CROSS JOIN (VALUES
     (1, 25::numeric, NULL::integer, 'always',    '[{"do": "remind"}, {"do": "tell", "to": "backup"}]'),
     (2, 40,          NULL,          'no_action', '[{"do": "reassign", "to": "backup"}, {"do": "tell", "to": "raiser"}]'),
     (3, 100,         NULL,          'always',    '[{"do": "remind"}, {"do": "tell", "to": "backup"}, {"do": "tell", "to": "raiser"}]'),
     (4, NULL,        10080,         'always',    '[{"do": "remind"}]')
 ) AS s (sort_order, at_percent, every_minutes, only_if, actions)
 WHERE p.is_default AND p.name = 'Standard plan'
   AND NOT EXISTS (SELECT 1 FROM public.reminder_plan_steps x WHERE x.plan_id = p.id);
