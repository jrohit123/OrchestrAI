-- housing-0002: every building block does one step (Godrej only).
--
-- A building block is one small step that other workflows run. Eight blocks had grown several
-- steps each (Create a case had six). This file cuts each of them into one-step blocks, and makes
-- every workflow that ran the big block run the small ones one after another, in the same order,
-- with the same inputs and the same "only if" conditions. Blocks share the workflow's memory, so
-- what a person sees and what gets saved does not change.
--
--   * Nothing is deleted. The eight old blocks are switched off and their title ends with
--     "(replaced)". Two old, unused blocks (Tell the person who has the case, Tell the person who
--     raised the case) are just switched off.
--   * Every changed workflow gets a new version, and the version it had before is kept in its
--     history, exactly as when it is saved on the dashboard.
--   * It only touches a block that is switched on and still has exactly the steps it had when
--     this file was written. A block that already has one step, or is switched off, is left
--     alone. It stops and changes nothing if a block has several steps but not those (it was
--     edited after this file was written) or a workflow still runs a block that is to be
--     switched off, so a newer edit is never overwritten.
--   * Safe to run twice: the second time there is nothing left to cut.
--
-- To go back: restore the backup (docs/runbook-migrations.md, step 6). By hand: switch the old
-- blocks on again and put each workflow back to its earlier version from its History.

CREATE TEMP TABLE _cut (
    old_key         text NOT NULL,
    idx             integer NOT NULL,
    new_key         text NOT NULL,
    new_name        text NOT NULL,
    new_description text NOT NULL
) ON COMMIT DROP;

INSERT INTO _cut (old_key, idx, new_key, new_name, new_description) VALUES
    ('case_find', 0, 'case_find_by_number', 'Find a case by its number',
     'Finds the case from its number (any format) and keeps it for the steps after. Stops if there is no such case.'),
    ('case_find', 1, 'case_check_access', 'Check the person may act on the case',
     'Stops unless the person may act on the case that was found. Needs the case found first.'),

    ('case_create', 0, 'case_look_up_response_time', 'Look up the response time of the priority',
     'Finds how long the priority gets, from the response-time table, for the steps after.'),
    ('case_create', 1, 'case_due_from_priority', 'Work out the due time from the priority',
     'Sets the due time of a new case from the response time of its priority. Needs the response time looked up first.'),
    ('case_create', 2, 'case_due_from_route', 'Work out the due time from the routing rule',
     'When the routing rule gave a time, uses it instead of the one from the priority.'),
    ('case_create', 3, 'case_save_new', 'Save the new case',
     'Saves a new case with its number, title, place, priority and due time.'),
    ('case_create', 4, 'case_set_category', 'Put the new case in its category',
     'Puts the case in the category that was found, when there is one. Needs the case saved first.'),
    ('case_create', 5, 'case_record_reported', 'Record that the case was reported',
     'Writes "reported" on the case timeline. Needs the case saved first.'),

    ('case_set_priority', 0, 'case_look_up_response_time', 'Look up the response time of the priority',
     'Finds how long the priority gets, from the response-time table, for the steps after.'),
    ('case_set_priority', 1, 'case_due_from_new_priority', 'Work out the due time again for the new priority',
     'Works out the due time again, counting from when the case was raised. Needs the case found and the response time looked up first.'),
    ('case_set_priority', 2, 'case_save_priority', 'Save the new priority and due time',
     'Changes the priority and the due time of the case. Needs the case found first.'),
    ('case_set_priority', 3, 'case_record_priority', 'Record the priority change',
     'Writes the new priority on the case timeline. Needs the case found first.'),

    ('case_set_status', 0, 'case_save_status', 'Save the new status',
     'Moves the case to another status. Needs the case found first.'),
    ('case_set_status', 1, 'case_stamp_closed_time', 'Note the time the case was closed',
     'When the new status is closed, writes the closing time. Needs the case found first.'),
    ('case_set_status', 2, 'case_clear_closed_time', 'Clear the closing time',
     'When the new status is not closed, clears the closing time. Needs the case found first.'),
    ('case_set_status', 3, 'case_record_status', 'Record the status change',
     'Writes the status change on the case timeline. Needs the case found first.'),

    ('case_apply_route', 0, 'case_give_to_routed_person', 'Give the new case to the person the routing rule names',
     'Gives a new case to the person the routing rules name, when they named one. Needs the case saved and the routing rule found first.'),
    ('case_apply_route', 1, 'case_record_routed_assignment', 'Record the routing assignment',
     'Writes on the case timeline that the routing rule gave the case to that person. Runs only when the rule named one.'),
    ('case_apply_route', 2, 'case_add_level2_people', 'Add the level 2 people from the routing rule',
     'Adds the level 2 people to the case, when the routing rule named some.'),

    ('case_assign', 0, 'case_find_new_handler', 'Find the person to give the case to',
     'Finds the person by name, among the people who are active.'),
    ('case_assign', 1, 'case_save_handler', 'Give the case to that person',
     'Hands the case to the person that was found. Needs the case and the person found first.'),
    ('case_assign', 2, 'case_record_assignment', 'Record the assignment',
     'Writes the hand-over on the case timeline. Needs the case and the person found first.'),

    ('case_close', 0, 'case_save_closed', 'Mark the case closed',
     'Sets the case to closed and notes the time. Needs the case found first.'),
    ('case_close', 1, 'case_record_closed', 'Record the closing and its note',
     'Writes the closing, with its note, on the case timeline. Needs the case found first.'),

    ('case_tell_parties', 0, 'case_tell_everyone_with_buttons', 'Tell everyone on the case, with buttons',
     'Messages everyone on the case except the person doing this, once each, with Add update, Pass on and Close buttons. Runs only when tell_buttons is yes. The caller gives the wording.'),
    ('case_tell_parties', 1, 'case_tell_everyone', 'Tell everyone on the case, without buttons',
     'Messages everyone on the case except the person doing this, once each, without buttons. Runs unless tell_buttons is yes. The caller gives the wording.');

-- old, unused blocks with several steps: nothing runs them, so they are only switched off
CREATE TEMP TABLE _retire (old_key text NOT NULL, steps integer NOT NULL) ON COMMIT DROP;
INSERT INTO _retire (old_key, steps) VALUES ('case_tell_handler', 2), ('case_tell_requester', 2);

-- the number of steps each of these blocks had when this file was written
CREATE TEMP TABLE _expect ON COMMIT DROP AS
SELECT old_key, count(*)::integer AS steps FROM _cut GROUP BY old_key
UNION ALL
SELECT old_key, steps FROM _retire;

-- the blocks this file acts on: switched on, and still with exactly those steps.
-- A block that already has one step, or is switched off, is not touched.
CREATE TEMP TABLE _old ON COMMIT DROP AS
SELECT w.id, w.org_id, w.intent_key AS old_key
FROM public.workflows w
JOIN _expect e ON e.old_key = w.intent_key
WHERE w.is_active
  AND jsonb_array_length((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) = e.steps;

-- 1. Look before changing anything: stop if something is not as expected.
DO $$
DECLARE
    bad record;
BEGIN
    -- several steps, but not the ones this file knows: it was edited after this file was written
    FOR bad IN
        SELECT w.intent_key, jsonb_array_length((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) AS have, e.steps AS want
        FROM public.workflows w
        JOIN _expect e ON e.old_key = w.intent_key
        WHERE w.is_active
          AND jsonb_array_length((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) > 1
          AND jsonb_array_length((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) <> e.steps
    LOOP
        RAISE EXCEPTION 'housing-0002: the block "%" has % steps but % were expected; it was edited after this file was written. Nothing was changed.',
            bad.intent_key, bad.have, bad.want;
    END LOOP;

    -- a step shared by two blocks must be the same step in both
    FOR bad IN
        SELECT o.org_id, c.new_key
        FROM _cut c
        JOIN _old o ON o.old_key = c.old_key
        JOIN public.workflows w ON w.id = o.id
        GROUP BY o.org_id, c.new_key
        HAVING count(DISTINCT (w.steps -> c.idx)) > 1
    LOOP
        RAISE EXCEPTION 'housing-0002: the blocks that share "%" no longer have the same step in it. Nothing was changed.', bad.new_key;
    END LOOP;

    -- a new key must not belong to something else ...
    FOR bad IN
        SELECT n.intent_key
        FROM public.workflows n
        WHERE n.org_id IN (SELECT org_id FROM _old)
          AND n.intent_key IN (SELECT new_key FROM _cut)
          AND (n.kind <> 'block' OR jsonb_array_length((CASE WHEN jsonb_typeof(n.steps) = 'array' THEN n.steps ELSE '[]'::jsonb END)) <> 1)
    LOOP
        RAISE EXCEPTION 'housing-0002: a workflow called "%" already exists and is not a one-step block. Nothing was changed.', bad.intent_key;
    END LOOP;

    -- ... and a one-step block that already has the key must hold the very step this file would put there
    FOR bad IN
        SELECT n.intent_key
        FROM _cut c
        JOIN _old o ON o.old_key = c.old_key
        JOIN public.workflows w ON w.id = o.id
        JOIN public.workflows n ON n.org_id = o.org_id AND n.intent_key = c.new_key
        WHERE n.steps IS DISTINCT FROM jsonb_build_array(w.steps -> c.idx)
    LOOP
        RAISE EXCEPTION 'housing-0002: a block called "%" already exists and holds a different step. Nothing was changed.', bad.intent_key;
    END LOOP;

    -- a block that is only switched off must not be run by anything
    FOR bad IN
        SELECT o.old_key, w.intent_key AS used_by
        FROM _old o
        JOIN _retire r ON r.old_key = o.old_key
        JOIN public.workflows w ON w.org_id = o.org_id AND w.intent_key <> o.old_key
        CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END) s(step)
        WHERE s.step ->> 'op' = 'run_workflow' AND s.step -> 'params' ->> 'workflow' = o.old_key
    LOOP
        RAISE EXCEPTION 'housing-0002: "%" is run by "%", so it is not switched off. Nothing was changed.', bad.old_key, bad.used_by;
    END LOOP;
END
$$;

-- 2. The one-step blocks. Each takes its step, its inputs and its settings from the block it was cut from.
INSERT INTO public.workflows
    (org_id, intent_key, name, description, steps, is_active, version, workflow_type, kind,
     entity_schema, gates, training_phrases, settings, response_format, menu_section)
SELECT DISTINCT ON (w.org_id, c.new_key)
    w.org_id, c.new_key, c.new_name, c.new_description,
    jsonb_build_array(w.steps -> c.idx), true, 1, w.workflow_type, 'block',
    w.entity_schema, w.gates, w.training_phrases, w.settings, w.response_format, w.menu_section
FROM _cut c
JOIN _old o ON o.old_key = c.old_key
JOIN public.workflows w ON w.id = o.id
ORDER BY w.org_id, c.new_key, c.old_key, c.idx
ON CONFLICT (org_id, intent_key) DO NOTHING;

-- 3. What each workflow that ran a big block will run instead: the small blocks, in the same place,
--    with everything else about the step (inputs, "only if") kept.
CREATE TEMP TABLE _flow_new ON COMMIT DROP AS
SELECT w.id, w.org_id,
       (SELECT jsonb_agg(e.item ORDER BY e.pos, e.sub)
        FROM (
            SELECT s.pos, 0 AS sub, s.step AS item
            FROM jsonb_array_elements((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) WITH ORDINALITY s(step, pos)
            WHERE NOT (s.step ->> 'op' = 'run_workflow'
                       AND EXISTS (SELECT 1 FROM _cut c
                                   JOIN _old ob ON ob.org_id = w.org_id AND ob.old_key = c.old_key
                                   WHERE c.old_key = s.step -> 'params' ->> 'workflow'))
            UNION ALL
            SELECT s.pos, c.idx + 1, jsonb_set(s.step, '{params,workflow}', to_jsonb(c.new_key))
            FROM jsonb_array_elements((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) WITH ORDINALITY s(step, pos)
            JOIN _cut c ON s.step ->> 'op' = 'run_workflow' AND c.old_key = s.step -> 'params' ->> 'workflow'
            WHERE EXISTS (SELECT 1 FROM _old ob
                          WHERE ob.org_id = w.org_id AND ob.old_key = c.old_key)
        ) e) AS new_steps
FROM public.workflows w
WHERE jsonb_typeof(w.steps) = 'array'
  AND w.intent_key NOT IN (SELECT old_key FROM _cut)
  AND EXISTS (
        SELECT 1
        FROM jsonb_array_elements((CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END)) s(step)
        JOIN _cut c ON s.step ->> 'op' = 'run_workflow' AND c.old_key = s.step -> 'params' ->> 'workflow'
        JOIN _old ob ON ob.org_id = w.org_id AND ob.old_key = c.old_key);

-- 4. Keep a copy of every workflow as it stands now (the dashboard does the same before a save).
INSERT INTO public.workflow_versions
    (workflow_id, org_id, version, intent_key, name, entity_schema, gates, granted_roles, steps,
     calc_rules, sql_template, slash_command, published_at, kind, settings)
SELECT w.id, w.org_id, w.version, w.intent_key, w.name, w.entity_schema, w.gates,
       ARRAY(SELECT r.name FROM public.roles r WHERE r.org_id = w.org_id AND w.intent_key = ANY (r.permissions) ORDER BY r.name),
       w.steps, w.calc_rules, w.sql_template, w.slash_command, w.created_at, w.kind, w.settings
FROM public.workflows w
WHERE (w.id IN (SELECT id FROM _flow_new) OR w.id IN (SELECT id FROM _old))
  AND NOT EXISTS (SELECT 1 FROM public.workflow_versions v WHERE v.workflow_id = w.id AND v.version = w.version);

-- 5. The workflows now run the small blocks.
UPDATE public.workflows w
SET steps = f.new_steps, version = w.version + 1
FROM _flow_new f
WHERE w.id = f.id;

-- 6. The old blocks are switched off (and the ones that were cut say so in their title).
UPDATE public.workflows w
SET is_active = false,
    version = w.version + 1,
    name = CASE WHEN w.intent_key IN (SELECT old_key FROM _cut) THEN w.name || ' (replaced)' ELSE w.name END
WHERE w.id IN (SELECT id FROM _old);

-- 7. Keep a copy of what they are now, and of the new blocks.
INSERT INTO public.workflow_versions
    (workflow_id, org_id, version, intent_key, name, entity_schema, gates, granted_roles, steps,
     calc_rules, sql_template, slash_command, published_at, kind, settings)
SELECT w.id, w.org_id, w.version, w.intent_key, w.name, w.entity_schema, w.gates,
       ARRAY(SELECT r.name FROM public.roles r WHERE r.org_id = w.org_id AND w.intent_key = ANY (r.permissions) ORDER BY r.name),
       w.steps, w.calc_rules, w.sql_template, w.slash_command, now(), w.kind, w.settings
FROM public.workflows w
WHERE (w.id IN (SELECT id FROM _flow_new)
       OR w.id IN (SELECT id FROM _old)
       OR (w.intent_key IN (SELECT new_key FROM _cut) AND w.org_id IN (SELECT org_id FROM _old)))
  AND NOT EXISTS (SELECT 1 FROM public.workflow_versions v WHERE v.workflow_id = w.id AND v.version = w.version);

-- 8. Look again: nothing that is switched on may still run an old block, and every new block has one step.
DO $$
DECLARE
    bad record;
BEGIN
    FOR bad IN
        SELECT w.intent_key, s.step -> 'params' ->> 'workflow' AS runs
        FROM public.workflows w
        CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(w.steps) = 'array' THEN w.steps ELSE '[]'::jsonb END) s(step)
        JOIN _old o ON o.org_id = w.org_id AND o.old_key = s.step -> 'params' ->> 'workflow'
        WHERE w.is_active AND s.step ->> 'op' = 'run_workflow'
    LOOP
        RAISE EXCEPTION 'housing-0002: "%" still runs the switched-off block "%". Everything was undone.', bad.intent_key, bad.runs;
    END LOOP;
    FOR bad IN
        SELECT n.intent_key, jsonb_array_length((CASE WHEN jsonb_typeof(n.steps) = 'array' THEN n.steps ELSE '[]'::jsonb END)) AS n
        FROM public.workflows n
        WHERE n.org_id IN (SELECT org_id FROM _old)
          AND n.intent_key IN (SELECT new_key FROM _cut)
          AND (n.kind <> 'block' OR NOT n.is_active OR jsonb_array_length((CASE WHEN jsonb_typeof(n.steps) = 'array' THEN n.steps ELSE '[]'::jsonb END)) <> 1)
    LOOP
        RAISE EXCEPTION 'housing-0002: the new block "%" does not hold exactly one step (it has %). Everything was undone.', bad.intent_key, bad.n;
    END LOOP;

    IF to_regclass('public.admin_events') IS NOT NULL THEN
        INSERT INTO public.admin_events (org_id, actor_label, area, action, target_type, summary)
        SELECT DISTINCT o.org_id, 'migration housing-0002', 'workflows', 'cut_blocks', 'workflow',
               'Cut the building blocks into one-step blocks (migration housing-0002)'
        FROM _old o
        WHERE NOT EXISTS (SELECT 1 FROM public.admin_events e
                          WHERE e.org_id = o.org_id AND e.actor_label = 'migration housing-0002');
    END IF;
END
$$;
