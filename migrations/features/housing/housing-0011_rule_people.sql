-- Godrej only: a case rule can name a TEAM, not just one person, one seat or one role.
-- One new table, routing_rule_people: for each rule, the people on it and their level (1 or 2).
--   Level 1  the owner and the others who are primarily responsible. The first Level 1 person who can be messaged
--            (in the order of sort_order, then name) is the case's owner (assignee).
--   Level 2  supporting people.
--   Everyone else on the rule, Level 1 or 2, is put on the case as "level 2" and told (that is how a case already treats
--   the people behind its owner).
-- A rule with no people in this table works exactly as before (assign to / backup). A rule that has people uses them;
-- if none of them can be messaged right now, the old assign-to / backup of the rule is used as before.
-- route_case() is replaced by a version that knows about the table; its answer has the same shape as before.
-- A rule may now have no single target when it has a team (the old rule "exactly one target" becomes "at most one").
-- Seats and roles are not touched. Safe to run twice.

CREATE TABLE IF NOT EXISTS public.routing_rule_people (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    rule_id     uuid NOT NULL REFERENCES public.routing_rules (id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES public.users (id) ON DELETE CASCADE,
    level       smallint NOT NULL CHECK (level IN (1, 2)),
    sort_order  integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (rule_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_routing_rule_people_rule ON public.routing_rule_people (rule_id, level, sort_order);

ALTER TABLE public.routing_rules DROP CONSTRAINT IF EXISTS routing_rules_one_target;
ALTER TABLE public.routing_rules DROP CONSTRAINT IF EXISTS routing_rules_at_most_one_target;
ALTER TABLE public.routing_rules ADD CONSTRAINT routing_rules_at_most_one_target
    CHECK (num_nonnulls(assign_user_id, assign_position_id, assign_role_id) <= 1);

-- the people of one level on a rule who can be messaged today, in the order they are asked
CREATE OR REPLACE FUNCTION public.team_targets(p_rule uuid, p_level integer)
RETURNS uuid[]
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(array_agg(p.user_id ORDER BY p.sort_order, u.name, p.user_id), '{}'::uuid[])
      FROM routing_rule_people p
      JOIN users u ON u.id = p.user_id
     WHERE p.rule_id = p_rule
       AND p.level = p_level
       AND cardinality(public.route_targets(p.org_id, p.user_id, NULL, NULL)) > 0;
$$;

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
    team1       uuid[];
    team2       uuid[];
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

    -- a team on the rule first: Level 1 owns it, everyone else on the team is kept in the loop
    team1 := public.team_targets(r.rid, 1);
    team2 := public.team_targets(r.rid, 2);
    IF cardinality(team1) > 0 OR cardinality(team2) > 0 THEN
        first_ids  := team1;
        backup_ids := COALESCE(team1[2:cardinality(team1)], '{}'::uuid[]) || team2;
    ELSE
        first_ids  := public.route_targets(p_org, r.assign_user_id, r.assign_position_id, r.assign_role_id);
        backup_ids := public.route_targets(p_org, r.backup_user_id, r.backup_position_id, r.backup_role_id);
    END IF;

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
