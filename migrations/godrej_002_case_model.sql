-- godrej_002_case_model.sql
--
-- Schema for the new case model: categories, routing rules, people on a case, special access,
-- a dashboard change log, workflow kinds (workflow / block / case action), and two lookup
-- functions (who handles a case, what may this person do on it).
--
-- Run once, top to bottom, against Godrej's database only. It is one transaction: if anything
-- fails, nothing is applied. Safe to re-run: every statement is IF NOT EXISTS, CREATE OR REPLACE,
-- or guarded, and the backfill only inserts rows that are missing.
--
-- It does NOT delete or change any existing rows, except:
--   * committee_positions gets two new columns (slug, kind) and existing rows get a slug.
--   * the trigger function sync_committee_role_to_user() is replaced by a version that behaves
--     exactly as before for committee seats and ignores every other kind of seat (see STEP 1).
--   * case_parties is back-filled from cases (requester and current assignee).
--
-- Seed data (categories, the Lift seats, routing rules) is in godrej_002_seed.sql.
-- A read-only check you can run afterwards is in godrej_002_verify.sql.
-- A rollback is at the bottom of this file, commented out.

BEGIN;

-- ═════════════════════════════════════════════════════════════════════════════
-- STEP 0 — a tiny shared helper
-- ═════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- ═════════════════════════════════════════════════════════════════════════════
-- STEP 1 — seats: reuse committee_positions / committee_members for every named job
--          (Chairman, Secretary, and now Lift in-charge, Lift level 2, ...)
--
-- Why a "kind": the existing trigger sync_committee_role_to_user() sets users.role_id to
-- 'committee' when a seat becomes active and to 'member' when it ends. That is right for the
-- real committee and wrong for a volunteer seat: giving Rajeswari the Lift in-charge seat would
-- turn an owner into a committee member. The new function below does the role switch only for
-- seats whose kind is 'committee'. Nothing changes for the existing Chairman and Secretary rows.
-- The existing unique index idx_committee_one_active_per_position already limits every seat to
-- one active holder, which is what routing needs.
-- ═════════════════════════════════════════════════════════════════════════════
ALTER TABLE committee_positions ADD COLUMN IF NOT EXISTS slug        text;
ALTER TABLE committee_positions ADD COLUMN IF NOT EXISTS kind        text NOT NULL DEFAULT 'committee';
ALTER TABLE committee_positions ADD COLUMN IF NOT EXISTS description text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'committee_positions_kind_check') THEN
        ALTER TABLE committee_positions
            ADD CONSTRAINT committee_positions_kind_check
            CHECK (kind IN ('committee', 'volunteer', 'staff', 'security', 'other'));
    END IF;
END $$;

UPDATE committee_positions
   SET slug = trim(both '_' from regexp_replace(lower(name), '[^a-z0-9]+', '_', 'g'))
 WHERE slug IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS committee_positions_org_slug_key ON committee_positions (org_id, slug);

CREATE OR REPLACE FUNCTION public.committee_positions_default_slug() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.slug IS NULL OR NEW.slug = '' THEN
        NEW.slug := trim(both '_' from regexp_replace(lower(NEW.name), '[^a-z0-9]+', '_', 'g'));
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_committee_positions_default_slug ON committee_positions;
CREATE TRIGGER trg_committee_positions_default_slug BEFORE INSERT ON committee_positions
    FOR EACH ROW EXECUTE FUNCTION public.committee_positions_default_slug();

CREATE OR REPLACE FUNCTION public.sync_committee_role_to_user() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  committee_role_id uuid;
  member_role_id uuid;
  seat_kind text;
BEGIN
  -- Only real committee seats switch a person's role. A volunteer, staff or other seat never does.
  SELECT kind INTO seat_kind FROM committee_positions WHERE id = NEW.position_id;
  IF seat_kind IS DISTINCT FROM 'committee' THEN
    RETURN NEW;
  END IF;

  SELECT id INTO committee_role_id FROM roles WHERE org_id = NEW.org_id AND name = 'committee';
  SELECT id INTO member_role_id   FROM roles WHERE org_id = NEW.org_id AND name = 'member';

  IF NEW.status = 'active' THEN
    UPDATE users SET role_id = committee_role_id WHERE id = NEW.user_id;
  ELSIF NEW.status = 'ended' THEN
    UPDATE users SET role_id = member_role_id WHERE id = NEW.user_id;
  END IF;
  RETURN NEW;
END;
$$;

-- ═════════════════════════════════════════════════════════════════════════════
-- STEP 2 — case categories (a tree: Lift > Stuck or entrapment)
-- ═════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS case_categories (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    parent_id         uuid REFERENCES case_categories(id) ON DELETE RESTRICT,
    key               text NOT NULL,
    label             text NOT NULL,
    default_priority  varchar(10),
    target_minutes    integer,
    keywords          text[] NOT NULL DEFAULT '{}',
    extra_fields      jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_active         boolean NOT NULL DEFAULT true,
    sort_order        integer NOT NULL DEFAULT 0,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT case_categories_org_key_key UNIQUE (org_id, key),
    CONSTRAINT case_categories_key_check CHECK (key ~ '^[a-z0-9_]+(\.[a-z0-9_]+)*$'),
    CONSTRAINT case_categories_priority_check CHECK (default_priority IS NULL OR default_priority IN ('urgent', 'high', 'medium', 'low')),
    CONSTRAINT case_categories_target_check CHECK (target_minutes IS NULL OR target_minutes > 0),
    CONSTRAINT case_categories_not_self CHECK (parent_id IS NULL OR parent_id <> id)
);
CREATE INDEX IF NOT EXISTS idx_case_categories_parent ON case_categories (org_id, parent_id);

CREATE OR REPLACE FUNCTION public.case_categories_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    cur  uuid := NEW.parent_id;
    hops integer := 0;
BEGIN
    WHILE cur IS NOT NULL LOOP
        IF cur = NEW.id THEN
            RAISE EXCEPTION 'A category cannot sit under itself or under one of its own sub-categories.';
        END IF;
        hops := hops + 1;
        IF hops > 8 THEN
            RAISE EXCEPTION 'Categories can be at most 8 levels deep.';
        END IF;
        SELECT parent_id INTO cur FROM case_categories WHERE id = cur;
    END LOOP;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_case_categories_guard ON case_categories;
CREATE TRIGGER trg_case_categories_guard BEFORE INSERT OR UPDATE OF parent_id ON case_categories
    FOR EACH ROW EXECUTE FUNCTION public.case_categories_guard();
DROP TRIGGER IF EXISTS trg_case_categories_updated ON case_categories;
CREATE TRIGGER trg_case_categories_updated BEFORE UPDATE ON case_categories
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- the case gets a real category column; anything extra a category asks still goes in custom_fields
ALTER TABLE cases ADD COLUMN IF NOT EXISTS category_id uuid;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cases_category_id_fkey') THEN
        ALTER TABLE cases
            ADD CONSTRAINT cases_category_id_fkey FOREIGN KEY (category_id) REFERENCES case_categories(id) ON DELETE SET NULL;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_cases_category ON cases (org_id, category_id);

-- ═════════════════════════════════════════════════════════════════════════════
-- STEP 3 — routing rules: category (+ optional conditions) -> who handles it, who is level 2
--   A rule names a person, a seat or a role. Naming a seat means a change of person is one edit
--   in the seat table and the rule stays. The most specific matching rule wins (see route_case).
-- ═════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS routing_rules (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    name                text NOT NULL,
    intent_key          text,
    category_id         uuid REFERENCES case_categories(id) ON DELETE CASCADE,
    match               jsonb NOT NULL DEFAULT '{}'::jsonb,
    assign_user_id      uuid REFERENCES users(id) ON DELETE RESTRICT,
    assign_position_id  uuid REFERENCES committee_positions(id) ON DELETE RESTRICT,
    assign_role_id      uuid REFERENCES roles(id) ON DELETE RESTRICT,
    backup_user_id      uuid REFERENCES users(id) ON DELETE SET NULL,
    backup_position_id  uuid REFERENCES committee_positions(id) ON DELETE SET NULL,
    backup_role_id      uuid REFERENCES roles(id) ON DELETE SET NULL,
    target_minutes      integer,
    is_active           boolean NOT NULL DEFAULT true,
    sort_order          integer NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT routing_rules_one_target CHECK (num_nonnulls(assign_user_id, assign_position_id, assign_role_id) = 1),
    CONSTRAINT routing_rules_one_backup CHECK (num_nonnulls(backup_user_id, backup_position_id, backup_role_id) <= 1),
    CONSTRAINT routing_rules_target_check CHECK (target_minutes IS NULL OR target_minutes > 0)
);
CREATE INDEX IF NOT EXISTS idx_routing_rules_org_category ON routing_rules (org_id, category_id) WHERE is_active;
DROP TRIGGER IF EXISTS trg_routing_rules_updated ON routing_rules;
CREATE TRIGGER trg_routing_rules_updated BEFORE UPDATE ON routing_rules
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ═════════════════════════════════════════════════════════════════════════════
-- STEP 4 — special access beyond a person's role: who, what, how much, where, until when
--   level: 1 view, 2 start, 3 act, 4 manage.   scope: {"category": "lift"} or {"tower": "B"}.
--   Live when revoked_at is empty and today is inside valid_from..valid_to.
--   workflow_key is an intent_key (or '*' for all) and not a foreign key on purpose: workflows
--   can be deleted and rebuilt without taking the grants with them.
-- ═════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS access_grants (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    user_id       uuid REFERENCES users(id) ON DELETE CASCADE,
    role_id       uuid REFERENCES roles(id) ON DELETE CASCADE,
    position_id   uuid REFERENCES committee_positions(id) ON DELETE CASCADE,
    workflow_key  text NOT NULL DEFAULT '*',
    level         smallint NOT NULL,
    scope         jsonb NOT NULL DEFAULT '{}'::jsonb,
    valid_from    date,
    valid_to      date,
    note          text,
    granted_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    revoked_at    timestamptz,
    CONSTRAINT access_grants_one_subject CHECK (num_nonnulls(user_id, role_id, position_id) = 1),
    CONSTRAINT access_grants_level_check CHECK (level BETWEEN 1 AND 4),
    CONSTRAINT access_grants_dates_check CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX IF NOT EXISTS idx_access_grants_user ON access_grants (org_id, user_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_access_grants_role ON access_grants (org_id, role_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_access_grants_position ON access_grants (org_id, position_id) WHERE revoked_at IS NULL;

-- ═════════════════════════════════════════════════════════════════════════════
-- STEP 5 — who is on a case, and why
--   requester and assignee rows are kept up to date by a trigger from cases (so today's workflows,
--   which only set cases.assigned_to_id, fill this table with no change). level2, helper and
--   watcher rows are written directly. Nobody is removed when a case is handed on: the earlier
--   assignee's row gets an ended_at and they can still be told about updates.
-- ═════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS case_parties (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    case_id     uuid NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    party_role  text NOT NULL,
    added_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    added_at    timestamptz NOT NULL DEFAULT now(),
    ended_at    timestamptz,
    note        text,
    CONSTRAINT case_parties_role_check CHECK (party_role IN ('requester', 'assignee', 'level2', 'helper', 'watcher')),
    CONSTRAINT case_parties_dates_check CHECK (ended_at IS NULL OR ended_at >= added_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS case_parties_one_active_role_key ON case_parties (case_id, user_id, party_role) WHERE ended_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS case_parties_one_active_assignee_key ON case_parties (case_id) WHERE party_role = 'assignee' AND ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_case_parties_case ON case_parties (case_id);
CREATE INDEX IF NOT EXISTS idx_case_parties_user ON case_parties (org_id, user_id) WHERE ended_at IS NULL;

CREATE OR REPLACE FUNCTION public.sync_case_parties_from_case() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- if this ran because another trigger touched cases, there is nothing to mirror
    IF pg_trigger_depth() > 1 THEN
        RETURN NEW;
    END IF;

    -- requester
    IF TG_OP = 'INSERT' OR NEW.complainant_id IS DISTINCT FROM OLD.complainant_id THEN
        IF TG_OP = 'UPDATE' THEN
            UPDATE case_parties SET ended_at = now()
             WHERE case_id = NEW.id AND party_role = 'requester' AND ended_at IS NULL
               AND user_id IS DISTINCT FROM NEW.complainant_id;
        END IF;
        IF NEW.complainant_id IS NOT NULL THEN
            INSERT INTO case_parties (org_id, case_id, user_id, party_role, added_by)
            VALUES (NEW.org_id, NEW.id, NEW.complainant_id, 'requester', NEW.complainant_id)
            ON CONFLICT (case_id, user_id, party_role) WHERE ended_at IS NULL DO NOTHING;
        END IF;
    END IF;

    -- assignee: a hand-over ends the old row and starts a new one
    IF (TG_OP = 'INSERT' AND NEW.assigned_to_id IS NOT NULL)
       OR (TG_OP = 'UPDATE' AND NEW.assigned_to_id IS DISTINCT FROM OLD.assigned_to_id) THEN
        UPDATE case_parties SET ended_at = now()
         WHERE case_id = NEW.id AND party_role = 'assignee' AND ended_at IS NULL
           AND user_id IS DISTINCT FROM NEW.assigned_to_id;
        IF NEW.assigned_to_id IS NOT NULL THEN
            INSERT INTO case_parties (org_id, case_id, user_id, party_role)
            VALUES (NEW.org_id, NEW.id, NEW.assigned_to_id, 'assignee')
            ON CONFLICT (case_id, user_id, party_role) WHERE ended_at IS NULL DO NOTHING;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_sync_case_parties ON cases;
CREATE TRIGGER trg_sync_case_parties AFTER INSERT OR UPDATE OF assigned_to_id, complainant_id ON cases
    FOR EACH ROW EXECUTE FUNCTION public.sync_case_parties_from_case();

-- back-fill from the cases that already exist (only inserts what is missing)
INSERT INTO case_parties (org_id, case_id, user_id, party_role, added_by, added_at)
SELECT c.org_id, c.id, c.complainant_id, 'requester', c.complainant_id, c.created_at
  FROM cases c
 WHERE c.complainant_id IS NOT NULL
ON CONFLICT (case_id, user_id, party_role) WHERE ended_at IS NULL DO NOTHING;

INSERT INTO case_parties (org_id, case_id, user_id, party_role, added_at)
SELECT c.org_id, c.id, c.assigned_to_id, 'assignee',
       COALESCE((SELECT max(a.created_at) FROM case_activity a WHERE a.case_id = c.id AND a.activity_type = 'assignment'), c.created_at)
  FROM cases c
 WHERE c.assigned_to_id IS NOT NULL
ON CONFLICT (case_id, user_id, party_role) WHERE ended_at IS NULL DO NOTHING;

-- the timeline can now say more than five things
ALTER TABLE case_activity DROP CONSTRAINT IF EXISTS case_activity_type_check;
ALTER TABLE case_activity
    ADD CONSTRAINT case_activity_type_check
    CHECK (activity_type IN ('comment', 'evidence', 'status_change', 'assignment', 'priority_change', 'category_change', 'escalation', 'reopen'));

-- ═════════════════════════════════════════════════════════════════════════════
-- STEP 6 — who changed what in the dashboard (chat turns stay in audit_log)
--   actor_user_id stays empty until the dashboard has a login; actor_label says where it came from.
-- ═════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS admin_events (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    actor_user_id  uuid REFERENCES users(id) ON DELETE SET NULL,
    actor_label    text,
    area           text NOT NULL,
    action         text NOT NULL,
    target_type    text,
    target_id      text,
    summary        text NOT NULL,
    before_state   jsonb,
    after_state    jsonb,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_admin_events_org_time ON admin_events (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_events_target ON admin_events (org_id, target_type, target_id);

-- ═════════════════════════════════════════════════════════════════════════════
-- STEP 7 — workflows can be a user-facing workflow, a building block, or a case action
--   kind      : 'workflow'    people start it from the Telegram menu (today's behaviour)
--               'block'       one small step other workflows use; never granted to a role
--               'case_action' a short workflow run on a case that exists (Pass to someone, Add update)
--   settings  : free JSON for what only some kinds need, for example for a case action
--               {"button": "Add update", "who_can_use": ["requester", "assignee"], "needs_level2": false}
--               and for a block {"group": "Case changes", "params": [...]}.
--   workflow_type (action / read) is unchanged and still says what the engine runs.
-- ═════════════════════════════════════════════════════════════════════════════
ALTER TABLE workflows         ADD COLUMN IF NOT EXISTS kind     text  NOT NULL DEFAULT 'workflow';
ALTER TABLE workflows         ADD COLUMN IF NOT EXISTS settings jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE workflow_drafts   ADD COLUMN IF NOT EXISTS kind     text  NOT NULL DEFAULT 'workflow';
ALTER TABLE workflow_drafts   ADD COLUMN IF NOT EXISTS settings jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE workflow_versions ADD COLUMN IF NOT EXISTS kind     text;
ALTER TABLE workflow_versions ADD COLUMN IF NOT EXISTS settings jsonb;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'workflows_kind_check') THEN
        ALTER TABLE workflows ADD CONSTRAINT workflows_kind_check CHECK (kind IN ('workflow', 'block', 'case_action'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'workflow_drafts_kind_check') THEN
        ALTER TABLE workflow_drafts ADD CONSTRAINT workflow_drafts_kind_check CHECK (kind IN ('workflow', 'block', 'case_action'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'workflow_versions_kind_check') THEN
        ALTER TABLE workflow_versions ADD CONSTRAINT workflow_versions_kind_check CHECK (kind IS NULL OR kind IN ('workflow', 'block', 'case_action'));
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_workflows_org_kind ON workflows (org_id, kind, is_active);

-- ═════════════════════════════════════════════════════════════════════════════
-- STEP 8 — two lookups the workflow steps call. Plain SQL: no AI decides who gets a case.
-- ═════════════════════════════════════════════════════════════════════════════

-- the people a rule's target means today: active, reachable on their channel, in a stable order.
CREATE OR REPLACE FUNCTION public.route_targets(p_org uuid, p_user uuid, p_position uuid, p_role uuid)
RETURNS uuid[]
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(array_agg(u.id ORDER BY u.name, u.id), '{}'::uuid[])
      FROM users u
     WHERE u.org_id = p_org
       AND u.is_active
       AND ((u.channel = 'telegram' AND u.phone LIKE 'tg:%')
            OR (COALESCE(u.channel, '') <> 'telegram' AND u.phone IS NOT NULL))
       AND (
            (p_user IS NOT NULL AND u.id = p_user)
         OR (p_position IS NOT NULL AND EXISTS (
                SELECT 1 FROM committee_members m
                 WHERE m.user_id = u.id AND m.position_id = p_position AND m.status = 'active'
                   AND (m.start_date IS NULL OR m.start_date <= CURRENT_DATE)
                   AND (m.end_date   IS NULL OR m.end_date   >= CURRENT_DATE)))
         OR (p_role IS NOT NULL AND u.role_id = p_role)
       );
$$;

-- who handles a new case. The most specific matching active rule wins:
--   score = depth of the rule's category x 10  +  5 for each extra condition  +  3 if tied to one workflow.
-- Returns no row when no rule matches. If the first choice is unavailable the backup is promoted.
-- target_minutes: the rule's own, else the category's (nearest parent that has one), else the priority rule.
CREATE OR REPLACE FUNCTION public.route_case(
    p_org uuid, p_category uuid, p_context jsonb DEFAULT '{}'::jsonb,
    p_intent_key text DEFAULT NULL, p_priority text DEFAULT NULL)
RETURNS TABLE (rule_id uuid, rule_name text, assignee_id uuid, level2_ids uuid[], target_minutes integer, via text)
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
    r           record;
    first_ids   uuid[];
    backup_ids  uuid[];
    cat_minutes integer;
    prio_minutes integer;
BEGIN
    WITH RECURSIVE up AS (
        SELECT c.id, c.parent_id, c.target_minutes AS tm, 1 AS hop
          FROM case_categories c WHERE c.id = p_category
        UNION ALL
        SELECT c.id, c.parent_id, c.target_minutes, up.hop + 1
          FROM case_categories c JOIN up ON c.id = up.parent_id WHERE up.hop < 8
    ), chain AS (
        SELECT up.id, up.tm, up.hop, (SELECT max(hop) FROM up) - up.hop + 1 AS depth FROM up
    )
    SELECT ru.id AS rid, ru.name AS rname,
           ru.assign_user_id, ru.assign_position_id, ru.assign_role_id,
           ru.backup_user_id, ru.backup_position_id, ru.backup_role_id,
           ru.target_minutes AS rule_tm,
           (SELECT ch2.tm FROM chain ch2 WHERE ch2.tm IS NOT NULL ORDER BY ch2.hop LIMIT 1) AS cat_tm,
           COALESCE(ch.depth, 0) * 10
             + (SELECT count(*) FROM jsonb_object_keys(ru.match)) * 5
             + (CASE WHEN ru.intent_key IS NOT NULL THEN 3 ELSE 0 END) AS score
      INTO r
      FROM routing_rules ru
      LEFT JOIN chain ch ON ch.id = ru.category_id
     WHERE ru.org_id = p_org AND ru.is_active
       AND (ru.intent_key IS NULL OR ru.intent_key = p_intent_key)
       AND (ru.category_id IS NULL OR ch.id IS NOT NULL)
       AND COALESCE(p_context, '{}'::jsonb) @> ru.match
     ORDER BY score DESC, ru.sort_order, ru.created_at
     LIMIT 1;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    first_ids  := public.route_targets(p_org, r.assign_user_id, r.assign_position_id, r.assign_role_id);
    backup_ids := public.route_targets(p_org, r.backup_user_id, r.backup_position_id, r.backup_role_id);

    IF p_priority IS NOT NULL THEN
        SELECT t.tat_minutes INTO prio_minutes FROM priority_tat_rules t WHERE t.org_id = p_org AND t.priority = p_priority;
    END IF;

    rule_id := r.rid;
    rule_name := r.rname;
    IF cardinality(first_ids) > 0 THEN
        assignee_id := first_ids[1];
        via := 'rule';
        level2_ids := ARRAY(SELECT x FROM unnest(backup_ids) AS x WHERE x <> first_ids[1]);
    ELSIF cardinality(backup_ids) > 0 THEN
        assignee_id := backup_ids[1];
        via := 'backup';
        level2_ids := ARRAY(SELECT x FROM unnest(backup_ids) AS x WHERE x <> backup_ids[1]);
    ELSE
        assignee_id := NULL;
        via := 'nobody available';
        level2_ids := '{}'::uuid[];
    END IF;
    target_minutes := COALESCE(r.rule_tm, r.cat_tm, prio_minutes);
    RETURN NEXT;
END;
$$;

-- what this person is to this case, and the best standing access they hold for it.
--   grant_level: 0 none, 1 view, 2 start, 3 act, 4 manage. A grant counts when it is live (not revoked,
--   inside its dates), belongs to the person, their role, or a seat they hold now, matches the case's
--   workflow (or '*'), and its scope matches (category anywhere up the tree, other keys inside custom_fields).
CREATE OR REPLACE FUNCTION public.case_relations(p_case uuid, p_user uuid)
RETURNS TABLE (is_requester boolean, is_assignee boolean, is_level2 boolean, is_helper boolean, was_assignee boolean, grant_level smallint)
    LANGUAGE sql STABLE
    AS $$
    WITH c AS (
        SELECT cs.id, cs.org_id, cs.category_id, cs.custom_fields, w.intent_key
          FROM cases cs LEFT JOIN workflows w ON w.id = cs.workflow_id
         WHERE cs.id = p_case
    ), chain AS (
        WITH RECURSIVE up AS (
            SELECT k.id, k.parent_id, k.key, 1 AS hop FROM case_categories k JOIN c ON k.id = c.category_id
            UNION ALL
            SELECT k.id, k.parent_id, k.key, up.hop + 1 FROM case_categories k JOIN up ON k.id = up.parent_id WHERE up.hop < 8
        )
        SELECT key FROM up
    ), me AS (
        SELECT u.id, u.role_id FROM users u WHERE u.id = p_user
    ), seats AS (
        SELECT m.position_id
          FROM committee_members m JOIN me ON m.user_id = me.id
         WHERE m.status = 'active'
           AND (m.start_date IS NULL OR m.start_date <= CURRENT_DATE)
           AND (m.end_date   IS NULL OR m.end_date   >= CURRENT_DATE)
    ), g AS (
        SELECT max(a.level) AS lvl
          FROM access_grants a, c, me
         WHERE a.org_id = c.org_id AND a.revoked_at IS NULL
           AND (a.valid_from IS NULL OR a.valid_from <= CURRENT_DATE)
           AND (a.valid_to   IS NULL OR a.valid_to   >= CURRENT_DATE)
           AND (a.user_id = me.id OR a.role_id = me.role_id OR a.position_id IN (SELECT position_id FROM seats))
           AND (a.workflow_key = '*' OR a.workflow_key = c.intent_key)
           AND ((a.scope ->> 'category') IS NULL OR (a.scope ->> 'category') IN (SELECT key FROM chain))
           AND ((a.scope - 'category') = '{}'::jsonb OR c.custom_fields @> (a.scope - 'category'))
    )
    SELECT
        EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = p_case AND p.user_id = p_user AND p.party_role = 'requester' AND p.ended_at IS NULL),
        EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = p_case AND p.user_id = p_user AND p.party_role = 'assignee'  AND p.ended_at IS NULL),
        EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = p_case AND p.user_id = p_user AND p.party_role = 'level2'    AND p.ended_at IS NULL),
        EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = p_case AND p.user_id = p_user AND p.party_role = 'helper'    AND p.ended_at IS NULL),
        EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = p_case AND p.user_id = p_user AND p.party_role = 'assignee'  AND p.ended_at IS NOT NULL),
        COALESCE((SELECT lvl FROM g), 0)::smallint;
$$;

-- ═════════════════════════════════════════════════════════════════════════════
-- Plain-language notes that travel with the schema
-- ═════════════════════════════════════════════════════════════════════════════
COMMENT ON TABLE case_categories IS 'Complaint categories as a tree (Lift > Stuck or entrapment). Defaults and keywords live here; the case stores category_id.';
COMMENT ON TABLE routing_rules   IS 'Category (+ optional conditions) -> who handles it and who is level 2. Names a person, a seat or a role. See route_case().';
COMMENT ON TABLE case_parties    IS 'Who is on a case and why. requester and assignee are maintained from cases by trigger; level2, helper, watcher are written directly.';
COMMENT ON TABLE access_grants   IS 'Special access beyond a role: who (user, role or seat), which workflow, level 1-4, scope, expiry.';
COMMENT ON TABLE admin_events    IS 'Who changed what in the admin dashboard. Chat turns are in audit_log.';
COMMENT ON COLUMN committee_positions.kind IS 'committee seats switch a person to the committee role while held; volunteer, staff, security and other seats never touch roles.';
COMMENT ON COLUMN workflows.kind IS 'workflow = started from the menu; block = a small step other workflows use; case_action = a short workflow run on an existing case.';
COMMENT ON COLUMN cases.category_id IS 'Real category column. Extra answers a category asks for are kept in custom_fields.';

COMMIT;

-- ═════════════════════════════════════════════════════════════════════════════
-- ROLLBACK (commented out). Run inside a transaction if you ever need to undo this file.
-- It removes only what this file added. The back-filled case_parties rows go with the table.
--
-- BEGIN;
-- DROP TRIGGER IF EXISTS trg_sync_case_parties ON cases;
-- DROP FUNCTION IF EXISTS public.sync_case_parties_from_case();
-- DROP FUNCTION IF EXISTS public.case_relations(uuid, uuid);
-- DROP FUNCTION IF EXISTS public.route_case(uuid, uuid, jsonb, text, text);
-- DROP FUNCTION IF EXISTS public.route_targets(uuid, uuid, uuid, uuid);
-- DROP TABLE IF EXISTS case_parties, admin_events, access_grants, routing_rules;
-- ALTER TABLE cases DROP COLUMN IF EXISTS category_id;
-- DROP TABLE IF EXISTS case_categories;
-- DROP FUNCTION IF EXISTS public.case_categories_guard();
-- ALTER TABLE case_activity DROP CONSTRAINT IF EXISTS case_activity_type_check;
-- ALTER TABLE case_activity ADD CONSTRAINT case_activity_type_check
--     CHECK (activity_type IN ('comment', 'evidence', 'status_change', 'assignment', 'priority_change'));
-- DROP INDEX IF EXISTS idx_workflows_org_kind;
-- ALTER TABLE workflows DROP CONSTRAINT IF EXISTS workflows_kind_check, DROP COLUMN IF EXISTS kind, DROP COLUMN IF EXISTS settings;
-- ALTER TABLE workflow_drafts DROP CONSTRAINT IF EXISTS workflow_drafts_kind_check, DROP COLUMN IF EXISTS kind, DROP COLUMN IF EXISTS settings;
-- ALTER TABLE workflow_versions DROP CONSTRAINT IF EXISTS workflow_versions_kind_check, DROP COLUMN IF EXISTS kind, DROP COLUMN IF EXISTS settings;
-- DROP TRIGGER IF EXISTS trg_committee_positions_default_slug ON committee_positions;
-- DROP FUNCTION IF EXISTS public.committee_positions_default_slug();
-- DROP INDEX IF EXISTS committee_positions_org_slug_key;
-- ALTER TABLE committee_positions DROP CONSTRAINT IF EXISTS committee_positions_kind_check,
--     DROP COLUMN IF EXISTS slug, DROP COLUMN IF EXISTS kind, DROP COLUMN IF EXISTS description;
-- CREATE OR REPLACE FUNCTION public.sync_committee_role_to_user() RETURNS trigger LANGUAGE plpgsql AS $f$
-- DECLARE committee_role_id uuid; member_role_id uuid;
-- BEGIN
--   SELECT id INTO committee_role_id FROM roles WHERE org_id = NEW.org_id AND name = 'committee';
--   SELECT id INTO member_role_id   FROM roles WHERE org_id = NEW.org_id AND name = 'member';
--   IF NEW.status = 'active' THEN UPDATE users SET role_id = committee_role_id WHERE id = NEW.user_id;
--   ELSIF NEW.status = 'ended' THEN UPDATE users SET role_id = member_role_id WHERE id = NEW.user_id; END IF;
--   RETURN NEW;
-- END; $f$;
-- DROP FUNCTION IF EXISTS public.set_updated_at();   -- only if nothing else uses it
-- COMMIT;
