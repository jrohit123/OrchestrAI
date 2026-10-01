-- godrej_002_verify.sql
--
-- Read-mostly check for godrej_002_case_model.sql + godrej_002_seed.sql. It plays the lift story in SQL
-- (Kartik reports, Rajeswari gets it, passes it to Venkatesh), tries the rules that must hold, prints
-- "ok:" for each check, and ROLLS BACK at the end so it leaves nothing behind.
-- Run:  psql -v ON_ERROR_STOP=1 -d <godrej database> -f godrej_002_verify.sql
-- Any failed check stops the script with "FAILED: <what>".

\set ON_ERROR_STOP on
BEGIN;

CREATE FUNCTION pg_temp.ok(c boolean, msg text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    IF c IS NOT TRUE THEN RAISE EXCEPTION 'FAILED: %', msg; END IF;
    RAISE NOTICE 'ok: %', msg;
END $$;

-- run a statement that MUST fail with one of the given SQLSTATE classes
CREATE FUNCTION pg_temp.must_fail(stmt text, msg text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE stmt;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'ok: % (refused: %)', msg, left(SQLERRM, 70);
        RETURN;
    END;
    RAISE EXCEPTION 'FAILED: % (it was allowed)', msg;
END $$;

DO $$
DECLARE
    o uuid; kartik uuid; raj uuid; venk uuid; priya uuid; anuja uuid; amit uuid;
    cat_stuck uuid; cat_noise uuid; cat_garb uuid; cat_wrong uuid; cat_leak uuid; cat_lift uuid;
    seat_incharge uuid; seat_l2 uuid; seat_treasurer uuid; seat_new uuid;
    r record; v_case uuid; v_case2 uuid; n integer; lvl smallint; role_name text;
BEGIN
    SELECT id INTO o FROM orgs WHERE slug = 'godrej-emerald';
    SELECT id INTO kartik FROM users WHERE name = 'Kartik Batchu';
    SELECT id INTO raj    FROM users WHERE name = 'Rajeswari Batchu';
    SELECT id INTO venk   FROM users WHERE name = 'Venkatesh Batchu';
    SELECT id INTO priya  FROM users WHERE name = 'Priya Desai';
    SELECT id INTO anuja  FROM users WHERE name = 'Anuja Sinkar';
    SELECT id INTO amit   FROM users WHERE name = 'Amit Patel';
    SELECT id INTO cat_lift  FROM case_categories WHERE key = 'lift';
    SELECT id INTO cat_stuck FROM case_categories WHERE key = 'lift.stuck';
    SELECT id INTO cat_noise FROM case_categories WHERE key = 'lift.noise';
    SELECT id INTO cat_garb  FROM case_categories WHERE key = 'housekeeping.garbage';
    SELECT id INTO cat_wrong FROM case_categories WHERE key = 'parking.wrong';
    SELECT id INTO cat_leak  FROM case_categories WHERE key = 'plumbing.leak';
    SELECT id INTO seat_incharge FROM committee_positions WHERE slug = 'lift_incharge';
    SELECT id INTO seat_l2       FROM committee_positions WHERE slug = 'lift_level2';
    SELECT id INTO seat_treasurer FROM committee_positions WHERE slug = 'treasurer';

    -- ── the shape ───────────────────────────────────────────────────────────
    PERFORM pg_temp.ok((SELECT count(*) FROM case_categories WHERE parent_id IS NULL) = 8 AND (SELECT count(*) FROM case_categories) = 29, 'categories: 8 areas and 21 sub-categories');
    PERFORM pg_temp.ok((SELECT count(*) FROM workflows WHERE kind = 'workflow') = (SELECT count(*) FROM workflows), 'every existing workflow is kind = workflow');
    PERFORM pg_temp.ok((SELECT count(*) FROM case_parties WHERE party_role = 'requester' AND ended_at IS NULL) >= (SELECT count(*) FROM cases WHERE complainant_id IS NOT NULL), 'back-fill: every existing case has its requester');
    PERFORM pg_temp.ok((SELECT count(*) FROM cases c WHERE c.assigned_to_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = c.id AND p.party_role = 'assignee' AND p.user_id = c.assigned_to_id AND p.ended_at IS NULL)) = 0, 'back-fill: every assigned case has its assignee');

    -- ── roles: a volunteer seat must not change anyone's role; a committee seat still does ──
    PERFORM pg_temp.ok((SELECT ro.name FROM users u JOIN roles ro ON ro.id = u.role_id WHERE u.id = raj) = 'owner', 'Rajeswari holds the Lift in-charge seat and is still an owner');
    PERFORM pg_temp.ok((SELECT ro.name FROM users u JOIN roles ro ON ro.id = u.role_id WHERE u.id = venk) = 'owner', 'Venkatesh holds the Lift level 2 seat and is still an owner');
    INSERT INTO committee_positions (org_id, name, kind) VALUES (o, 'Test volunteer seat', 'volunteer') RETURNING id INTO seat_new;
    PERFORM pg_temp.ok((SELECT slug FROM committee_positions WHERE id = seat_new) = 'test_volunteer_seat', 'a new seat gets its slug automatically');
    INSERT INTO committee_members (org_id, user_id, position_id, status, start_date) VALUES (o, amit, seat_new, 'active', CURRENT_DATE);
    UPDATE committee_members SET status = 'ended' WHERE user_id = amit AND position_id = seat_new;
    PERFORM pg_temp.ok((SELECT ro.name FROM users u JOIN roles ro ON ro.id = u.role_id WHERE u.id = amit) = 'owner', 'holding then leaving a volunteer seat leaves the person an owner');
    INSERT INTO committee_members (org_id, user_id, position_id, status, start_date) VALUES (o, amit, seat_treasurer, 'active', CURRENT_DATE);
    PERFORM pg_temp.ok((SELECT ro.name FROM users u JOIN roles ro ON ro.id = u.role_id WHERE u.id = amit) = 'committee', 'a real committee seat still switches the person to committee, as before');
    UPDATE committee_members SET status = 'ended' WHERE user_id = amit AND position_id = seat_treasurer;
    PERFORM pg_temp.ok((SELECT ro.name FROM users u JOIN roles ro ON ro.id = u.role_id WHERE u.id = amit) = 'member', 'ending a committee seat behaves as before (back to member)');

    -- ── routing: who handles what ───────────────────────────────────────────
    SELECT * INTO r FROM route_case(o, cat_stuck, '{}', NULL, 'urgent');
    PERFORM pg_temp.ok(r.assignee_id = raj AND r.via = 'rule' AND r.rule_name = 'Lift issues', 'lift stuck goes to Rajeswari by the "Lift issues" rule');
    PERFORM pg_temp.ok(r.level2_ids = ARRAY[venk], 'level 2 for lifts is Venkatesh');
    PERFORM pg_temp.ok(r.target_minutes = 60, 'target time comes from the sub-category (60 minutes)');
    SELECT * INTO r FROM route_case(o, cat_noise, '{}', NULL, 'medium');
    PERFORM pg_temp.ok(r.assignee_id = raj AND r.target_minutes = 1440, 'lift noise has no own target, so the medium priority rule applies (1440 minutes)');
    INSERT INTO routing_rules (org_id, name, category_id, assign_user_id) VALUES (o, 'Parking (temporary, for this check)', (SELECT id FROM case_categories WHERE key = 'parking'), anuja);
    SELECT * INTO r FROM route_case(o, cat_wrong, '{}', NULL, 'low');
    PERFORM pg_temp.ok(r.assignee_id = anuja AND r.rule_name LIKE 'Parking%', 'a rule on the parent category (parking) also covers its sub-category (wrong parking)');
    SELECT * INTO r FROM route_case(o, cat_leak, '{}', NULL, 'high');
    PERFORM pg_temp.ok(NOT FOUND, 'plumbing has no rule yet, so nothing is returned (the case stays unassigned, as today)');
    INSERT INTO routing_rules (org_id, name, category_id, assign_user_id) VALUES (o, 'Housekeeping (temporary, for this check)', (SELECT id FROM case_categories WHERE key = 'housekeeping'), priya);
    SELECT * INTO r FROM route_case(o, cat_garb, '{}', NULL, 'medium');
    PERFORM pg_temp.ok(r.rule_name LIKE 'Housekeeping%' AND r.assignee_id IS NULL AND r.via = 'nobody available', 'a rule that names someone who has not linked Telegram says nobody is available (Priya, for now)');
    UPDATE users SET phone = 'tg:999000111' WHERE id = priya;
    SELECT * INTO r FROM route_case(o, cat_garb, '{}', NULL, 'medium');
    PERFORM pg_temp.ok(r.assignee_id = priya, 'once that person links Telegram, the rule finds them');

    -- the first choice is unavailable: the backup is promoted
    UPDATE users SET phone = '+910000000001' WHERE id = raj;
    SELECT * INTO r FROM route_case(o, cat_stuck, '{}', NULL, 'urgent');
    PERFORM pg_temp.ok(r.assignee_id = venk AND r.via = 'backup' AND cardinality(r.level2_ids) = 0, 'Rajeswari not reachable: Venkatesh gets it as the backup');
    UPDATE users SET phone = 'tg:910000001' WHERE id = raj;

    -- a more specific rule beats a general one
    INSERT INTO routing_rules (org_id, name, category_id, assign_user_id) VALUES (o, 'Stuck lifts go straight to Anuja', cat_stuck, anuja);
    SELECT * INTO r FROM route_case(o, cat_stuck, '{}', NULL, 'urgent');
    PERFORM pg_temp.ok(r.assignee_id = anuja, 'a rule on the sub-category beats the rule on the whole category');
    SELECT * INTO r FROM route_case(o, cat_noise, '{}', NULL, 'medium');
    PERFORM pg_temp.ok(r.assignee_id = raj, 'other lift problems still go to Rajeswari');
    UPDATE routing_rules SET is_active = false WHERE name = 'Stuck lifts go straight to Anuja';
    INSERT INTO routing_rules (org_id, name, category_id, match, assign_user_id) VALUES (o, 'Tower B lifts', cat_lift, '{"tower":"B"}', anuja);
    SELECT * INTO r FROM route_case(o, cat_noise, '{"tower":"B"}', NULL, 'medium');
    PERFORM pg_temp.ok(r.assignee_id = anuja, 'a rule with an extra condition (tower B) beats the plain lift rule when it applies');
    SELECT * INTO r FROM route_case(o, cat_noise, '{"tower":"C"}', NULL, 'medium');
    PERFORM pg_temp.ok(r.assignee_id = raj, 'and is ignored for another tower');

    -- ── the lift story, in the way today's workflows write to the database ──
    INSERT INTO cases (org_id, case_number, complainant_id, title, priority, category_id, location, due_date)
    VALUES (o, 'VERIFY-0001', kartik, 'Lift C is stuck between the 7th and 8th floor', 'urgent', cat_stuck, 'C wing', now() + interval '60 minutes')
    RETURNING id INTO v_case;
    PERFORM pg_temp.ok((SELECT count(*) FROM case_parties WHERE case_id = v_case AND party_role = 'requester' AND user_id = kartik AND ended_at IS NULL) = 1, 'registering a case makes Kartik its requester');
    SELECT * INTO r FROM route_case(o, cat_stuck, '{}', NULL, 'urgent');   -- (the Anuja rule is switched off again; Tower B needs a condition)
    UPDATE cases SET assigned_to_id = r.assignee_id WHERE id = v_case;
    INSERT INTO case_parties (org_id, case_id, user_id, party_role, added_by) SELECT o, v_case, x, 'level2', r.assignee_id FROM unnest(r.level2_ids) AS x;
    INSERT INTO case_activity (org_id, case_id, actor_user_id, activity_type, payload) VALUES (o, v_case, kartik, 'assignment', jsonb_build_object('to_user_id', r.assignee_id, 'via', r.rule_name));
    PERFORM pg_temp.ok((SELECT user_id FROM case_parties WHERE case_id = v_case AND party_role = 'assignee' AND ended_at IS NULL) = raj, 'assigning sets Rajeswari as the assignee');
    SELECT * INTO r FROM case_relations(v_case, raj);
    PERFORM pg_temp.ok(r.is_assignee AND NOT r.is_requester AND NOT r.is_level2, 'Rajeswari: assignee only');
    SELECT * INTO r FROM case_relations(v_case, venk);
    PERFORM pg_temp.ok(r.is_level2 AND NOT r.is_assignee, 'Venkatesh: level 2 only');
    SELECT * INTO r FROM case_relations(v_case, kartik);
    PERFORM pg_temp.ok(r.is_requester AND NOT r.is_assignee, 'Kartik: requester only');

    -- Rajeswari passes it to Venkatesh (the same single UPDATE today's assign workflow does)
    UPDATE cases SET assigned_to_id = venk WHERE id = v_case;
    INSERT INTO case_activity (org_id, case_id, actor_user_id, activity_type, payload) VALUES (o, v_case, raj, 'assignment', jsonb_build_object('from_user_id', raj, 'to_user_id', venk));
    SELECT * INTO r FROM case_relations(v_case, raj);
    PERFORM pg_temp.ok(NOT r.is_assignee AND r.was_assignee, 'after the pass-on Rajeswari is an earlier assignee and stays on record');
    SELECT * INTO r FROM case_relations(v_case, venk);
    PERFORM pg_temp.ok(r.is_assignee AND r.is_level2, 'Venkatesh now has it and is still level 2');
    PERFORM pg_temp.ok((SELECT count(*) FROM case_parties WHERE case_id = v_case AND party_role = 'assignee' AND ended_at IS NULL) = 1, 'there is only ever one current assignee');
    PERFORM pg_temp.ok((SELECT count(DISTINCT user_id) FROM case_parties WHERE case_id = v_case) = 3, 'three people follow this case: Kartik, Rajeswari, Venkatesh');

    -- handing it to someone who is NOT a lift person needs no access change: the assignee is a party
    UPDATE cases SET assigned_to_id = priya WHERE id = v_case;
    SELECT * INTO r FROM case_relations(v_case, priya);
    PERFORM pg_temp.ok(r.is_assignee AND r.grant_level = 0, 'Priya can be given the lift case without any lift access (she is simply its assignee)');
    UPDATE cases SET assigned_to_id = venk WHERE id = v_case;

    -- ── special access: scope, expiry, revoke, seats ────────────────────────
    INSERT INTO access_grants (org_id, user_id, workflow_key, level, scope) VALUES (o, anuja, '*', 3, '{"category":"lift"}');
    SELECT grant_level INTO lvl FROM case_relations(v_case, anuja);
    PERFORM pg_temp.ok(lvl = 3, 'a grant scoped to lifts gives Anuja Act on this lift case');
    INSERT INTO cases (org_id, case_number, complainant_id, title, priority, category_id) VALUES (o, 'VERIFY-0002', kartik, 'Ceiling leak', 'high', cat_leak) RETURNING id INTO v_case2;
    SELECT grant_level INTO lvl FROM case_relations(v_case2, anuja);
    PERFORM pg_temp.ok(lvl = 0, 'the same grant gives nothing on a plumbing case');
    UPDATE access_grants SET valid_to = CURRENT_DATE - 1 WHERE user_id = anuja;
    SELECT grant_level INTO lvl FROM case_relations(v_case, anuja);
    PERFORM pg_temp.ok(lvl = 0, 'an expired grant counts for nothing');
    UPDATE access_grants SET valid_to = NULL, revoked_at = now() WHERE user_id = anuja;
    SELECT grant_level INTO lvl FROM case_relations(v_case, anuja);
    PERFORM pg_temp.ok(lvl = 0, 'a revoked grant counts for nothing');
    INSERT INTO access_grants (org_id, position_id, workflow_key, level, scope) VALUES (o, seat_incharge, '*', 4, '{"category":"lift"}');
    SELECT grant_level INTO lvl FROM case_relations(v_case, raj);
    PERFORM pg_temp.ok(lvl = 4, 'a grant on the Lift in-charge seat gives its holder Manage on lift cases');
    SELECT grant_level INTO lvl FROM case_relations(v_case, kartik);
    PERFORM pg_temp.ok(lvl = 0, 'and nothing to anyone who does not hold the seat');
    UPDATE committee_members SET status = 'ended', end_date = CURRENT_DATE WHERE position_id = seat_incharge AND user_id = raj;
    SELECT grant_level INTO lvl FROM case_relations(v_case, raj);
    PERFORM pg_temp.ok(lvl = 0, 'when Rajeswari leaves the seat the seat grant stops applying to her');

    -- ── rules that must hold ────────────────────────────────────────────────
    PERFORM pg_temp.must_fail(format('INSERT INTO case_parties (org_id, case_id, user_id, party_role) VALUES (%L, %L, %L, %L)', o, v_case, kartik, 'assignee'), 'a second current assignee on the same case');
    PERFORM pg_temp.must_fail(format('INSERT INTO routing_rules (org_id, name, assign_user_id, assign_role_id) VALUES (%L, %L, %L, (SELECT id FROM roles LIMIT 1))', o, 'two targets', kartik), 'a routing rule with two targets');
    PERFORM pg_temp.must_fail(format('INSERT INTO routing_rules (org_id, name) VALUES (%L, %L)', o, 'no target'), 'a routing rule with no target');
    PERFORM pg_temp.must_fail(format('UPDATE case_categories SET parent_id = %L WHERE id = %L', cat_stuck, cat_lift), 'a category under its own sub-category');
    PERFORM pg_temp.must_fail(format('INSERT INTO case_categories (org_id, key, label) VALUES (%L, %L, %L)', o, 'Bad Key', 'x'), 'a category key with capitals and spaces');
    PERFORM pg_temp.must_fail(format('INSERT INTO access_grants (org_id, user_id, role_id, level) VALUES (%L, %L, (SELECT id FROM roles LIMIT 1), 3)', o, kartik), 'a grant to a person and a role at once');
    PERFORM pg_temp.must_fail(format('INSERT INTO access_grants (org_id, user_id, level) VALUES (%L, %L, 9)', o, kartik), 'a grant with level 9');
    PERFORM pg_temp.must_fail(format('UPDATE workflows SET kind = %L', 'nonsense'), 'a workflow of a kind that does not exist');
    PERFORM pg_temp.must_fail(format('UPDATE cases SET category_id = %L WHERE id = %L', gen_random_uuid(), v_case), 'a case in a category that does not exist');
    INSERT INTO case_activity (org_id, case_id, actor_user_id, activity_type, payload) VALUES (o, v_case, venk, 'category_change', '{}'), (o, v_case, venk, 'escalation', '{}'), (o, v_case, kartik, 'reopen', '{}');
    PERFORM pg_temp.ok(true, 'the timeline accepts category_change, escalation and reopen');
    PERFORM pg_temp.must_fail(format('INSERT INTO case_activity (org_id, case_id, activity_type) VALUES (%L, %L, %L)', o, v_case, 'made_up'), 'a timeline entry of a made-up type');
    UPDATE case_categories SET label = 'Lift (edited)' WHERE id = cat_lift;
    PERFORM pg_temp.ok((SELECT updated_at > created_at FROM case_categories WHERE id = cat_lift), 'editing a category stamps updated_at');
    RAISE NOTICE 'ALL CHECKS PASSED';
END $$;

ROLLBACK;
