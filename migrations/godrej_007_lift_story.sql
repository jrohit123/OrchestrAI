-- 1. the Lift seats, categories and routing rule (safe to run again: each insert skips what exists)
WITH o AS (SELECT id FROM orgs WHERE slug = 'godrej-emerald')
INSERT INTO case_categories (org_id, key, label, default_priority, target_minutes, keywords, extra_fields, sort_order)
SELECT o.id, v.key, v.label, v.prio, v.tm::integer, v.kw, v.extra::jsonb, v.ord
  FROM o CROSS JOIN (VALUES
    ('lift',               'Lift',                        NULL,     NULL, ARRAY['lift','elevator','buzzer','overload'],                '[{"key":"lift_id","label":"Which lift?","type":"choice","options":["Lift A","Lift B","Lift C","Service lift"]}]', 10),
    ('plumbing',           'Plumbing',                    NULL,     NULL, ARRAY['plumb','pipe','tap','water','flush','toilet'],        '[]', 20),
    ('electrical',         'Electrical',                  NULL,     NULL, ARRAY['electric','power','switch','wiring','mcb','fuse','light'], '[]', 30),
    ('housekeeping',       'Housekeeping',                NULL,     NULL, ARRAY['clean','garbage','dust','sweep','pest','mosquito'],   '[]', 40),
    ('security',           'Security',                    NULL,     NULL, ARRAY['guard','gate','cctv','visitor','security'],           '[]', 50),
    ('parking',            'Parking',                     NULL,     NULL, ARRAY['parking','vehicle','car','bike','sticker'],           '[]', 60),
    ('common',             'Common areas',                NULL,     NULL, ARRAY['clubhouse','garden','pool','gym','terrace','playground'], '[]', 70),
    ('other',              'Something else',              'medium', NULL, ARRAY[]::text[],                                             '[]', 90)
  ) AS v(key, label, prio, tm, kw, extra, ord)
ON CONFLICT (org_id, key) DO NOTHING;
WITH o AS (SELECT id FROM orgs WHERE slug = 'godrej-emerald')
INSERT INTO case_categories (org_id, parent_id, key, label, default_priority, target_minutes, keywords, extra_fields, sort_order)
SELECT o.id, p.id, v.key, v.label, v.prio, v.tm::integer, v.kw, v.extra::jsonb, v.ord
  FROM o CROSS JOIN (VALUES
    ('lift',         'lift.stuck',          'Stuck or entrapment',   'urgent', 60,   ARRAY['stuck','trapped','entrap','not moving','between floors'], '[]', 11),
    ('lift',         'lift.noise',          'Noise or vibration',    'medium', NULL, ARRAY['noise','vibrat','jerk','sound','rattl'],                  '[]', 12),
    ('lift',         'lift.door',           'Door or buttons',       'medium', NULL, ARRAY['door','button','display','panel'],                        '[]', 13),
    ('plumbing',     'plumbing.leak',       'Leakage or seepage',    'high',   NULL, ARRAY['leak','seep','drip','ceiling','damp'],                    '[]', 21),
    ('plumbing',     'plumbing.block',      'Blockage or drainage',  'high',   NULL, ARRAY['block','choke','clog','drain','overflow','sewage'],       '[]', 22),
    ('plumbing',     'plumbing.pressure',   'Low water pressure',    'medium', NULL, ARRAY['pressure','low water','no water','supply'],               '[]', 23),
    ('electrical',   'electrical.lights',   'Lights in common areas','low',    NULL, ARRAY['light','bulb','lamp','dim','flicker','tube'],             '[]', 31),
    ('electrical',   'electrical.outage',   'Power outage',          'urgent', NULL, ARRAY['power cut','outage','no power','no electricity','tripped'],'[]', 32),
    ('electrical',   'electrical.wiring',   'Wiring or sparks',      'urgent', NULL, ARRAY['spark','short circuit','shock','burning smell','wiring'], '[]', 33),
    ('housekeeping', 'housekeeping.cleaning','Cleaning',             'low',    NULL, ARRAY['clean','dirty','sweep','mop','dust'],                     '[]', 41),
    ('housekeeping', 'housekeeping.garbage','Garbage collection',    'medium', NULL, ARRAY['garbage','waste','dustbin','trash','smell'],              '[]', 42),
    ('housekeeping', 'housekeeping.pest',   'Pest control',          'medium', NULL, ARRAY['pest','cockroach','rat','mosquito','ants'],               '[]', 43),
    ('security',     'security.gate',       'Gate or visitors',      'medium', NULL, ARRAY['gate','visitor','entry','barrier'],                       '[]', 51),
    ('security',     'security.cctv',       'CCTV',                  'medium', NULL, ARRAY['cctv','camera','footage'],                                '[]', 52),
    ('security',     'security.threat',     'Suspicious activity',   'urgent', NULL, ARRAY['suspicious','theft','stranger','intruder','fight'],       '[]', 53),
    ('parking',      'parking.wrong',       'Wrong parking or blocking','low', NULL, ARRAY['blocking','wrong park','double park','parked','debris'],  '[]', 61),
    ('parking',      'parking.sticker',     'Sticker or permit',     'low',    NULL, ARRAY['sticker','permit','pass','second car'],                   '[{"key":"vehicle_no","label":"Vehicle number","type":"text"}]', 62),
    ('parking',      'parking.charging',    'EV charging point',     'low',    NULL, ARRAY['charging','ev '],                                         '[]', 63),
    ('common',       'common.club',         'Clubhouse or gym',      'low',    NULL, ARRAY['clubhouse','gym','hall'],                                 '[]', 71),
    ('common',       'common.garden',       'Garden or play area',   'low',    NULL, ARRAY['garden','playground','lawn','tree'],                      '[]', 72),
    ('common',       'common.pool',         'Swimming pool',         'medium', NULL, ARRAY['pool','swim'],                                            '[]', 73)
  ) AS v(parent_key, key, label, prio, tm, kw, extra, ord)
  JOIN case_categories p ON p.org_id = o.id AND p.key = v.parent_key
ON CONFLICT (org_id, key) DO NOTHING;
WITH o AS (SELECT id FROM orgs WHERE slug = 'godrej-emerald')
INSERT INTO committee_positions (org_id, name, slug, kind, description, default_permissions)
SELECT o.id, v.name, v.slug, 'volunteer', v.descr, '{}'
  FROM o CROSS JOIN (VALUES
    ('Lift in-charge',                   'lift_incharge', 'Gets every lift complaint first. A resident volunteer, not on the committee.'),
    ('Lift level 2 (LiftCare liaison)',  'lift_level2',   'Kept in the loop on lift complaints and takes over when needed. In direct touch with the lift vendor.')
  ) AS v(name, slug, descr)
ON CONFLICT (org_id, name) DO NOTHING;
INSERT INTO committee_members (org_id, user_id, position_id, status, start_date)
SELECT p.org_id, u.id, p.id, 'active', CURRENT_DATE
  FROM committee_positions p
  JOIN users u ON u.org_id = p.org_id
 WHERE ((p.slug = 'lift_incharge' AND u.name = 'Rajeswari Batchu')
     OR (p.slug = 'lift_level2'   AND u.name = 'Venkatesh Batchu'))
   AND NOT EXISTS (SELECT 1 FROM committee_members m WHERE m.position_id = p.id AND m.status = 'active');
INSERT INTO routing_rules (org_id, name, category_id, assign_position_id, backup_position_id, sort_order)
SELECT o.id, 'Lift issues', cat.id, seat1.id, seat2.id, 10
  FROM orgs o
  JOIN case_categories cat ON cat.org_id = o.id AND cat.key = 'lift'
  JOIN committee_positions seat1 ON seat1.org_id = o.id AND seat1.slug = 'lift_incharge'
  JOIN committee_positions seat2 ON seat2.org_id = o.id AND seat2.slug = 'lift_level2'
 WHERE o.slug = 'godrej-emerald'
   AND NOT EXISTS (SELECT 1 FROM routing_rules r WHERE r.org_id = o.id AND r.name = 'Lift issues');

-- 2. building blocks
UPDATE workflows SET steps = $j$[{"op": "resolve_entity", "params": {"table": "cases", "into": "case", "name_from": "$fields.case_number", "match_column": "case_number", "normalize": "identifier", "expose": {"resolved_case_number": "case_number"}}}, {"op": "case.authorize", "params": {"case": "$case"}}]$j$::jsonb, description = $j$Finds the case from its number (any format) and stops unless the person may act on it.$j$ WHERE intent_key = 'case_find';
UPDATE workflows SET steps = $j$[{"op": "resolve_entity", "params": {"table": "priority_tat_rules", "into": "tat", "name_from": "$fields.priority", "match_column": "priority", "expose": {"tat_minutes": "tat_minutes"}}}, {"op": "derive_field", "params": {"field": "due_date", "expr": "due_from_tat(tat_minutes, \"minutes\")"}}, {"op": "derive_field", "when": {"field": "$fields.route_minutes", "exists": true}, "params": {"field": "due_date", "expr": "due_from_tat(route_minutes, \"minutes\")"}}, {"op": "db.insert_row", "params": {"table": "cases", "values": {"title": "$fields.title", "status": "reported", "due_date": "$fields.due_date", "location": "$fields.location", "priority": "$fields.priority", "description": "$fields.description", "complainant_id": "$user.user_id"}, "sequence": {"field": "case_number", "prefix": "CS-{YY}-{MM}-", "pad": 5, "start": 1}}}, {"op": "db.update_row", "when": {"field": "$fields.category_id", "exists": true}, "params": {"table": "cases", "set": {"category_id": "$fields.category_id"}, "where": {"id": "$inserted.cases.id"}}}, {"op": "db.insert_row", "params": {"table": "case_activity", "values": {"case_id": "$inserted.cases.id", "activity_type": "status_change", "actor_user_id": "$user.user_id", "payload": {"to": "reported"}}}}]$j$::jsonb, description = $j$Saves a new case with its number, category and due time (the time the category allows, else from the priority).$j$ WHERE intent_key = 'case_create';
UPDATE workflows SET steps = $j$[{"op": "resolve_entity", "params": {"table": "priority_tat_rules", "into": "tat", "name_from": "$fields.priority", "match_column": "priority", "expose": {"tat_minutes": "tat_minutes"}}}, {"op": "derive_field", "params": {"field": "due_date", "expr": "due_from_tat(tat_minutes, \"minutes\", case_created_at)"}}, {"op": "db.update_row", "params": {"table": "cases", "set": {"priority": "$fields.priority", "due_date": "$fields.due_date"}, "where": {"id": "$case.id"}}}, {"op": "db.insert_row", "params": {"table": "case_activity", "values": {"case_id": "$case.id", "activity_type": "priority_change", "actor_user_id": "$user.user_id", "payload": {"to": "$fields.priority"}}}}]$j$::jsonb, description = $j$Changes the priority and works out the due time again from when the case was raised.$j$ WHERE intent_key = 'case_set_priority';
INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section, kind)
SELECT o.id, 'case_apply_route', $j$Send the case to whoever handles it$j$, $j$Gives a new case to the person the routing rules name, records it, and adds level 2 to the case. Needs Find who handles it first.$j$, 'action', $j$[{"op": "db.update_row", "when": {"field": "$route.assignee_id", "exists": true}, "params": {"table": "cases", "set": {"assigned_to_id": "$route.assignee_id"}, "where": {"id": "$inserted.cases.id"}}}, {"op": "db.insert_row", "when": {"field": "$route.assignee_id", "exists": true}, "params": {"table": "case_activity", "values": {"case_id": "$inserted.cases.id", "activity_type": "assignment", "actor_user_id": "$user.user_id", "payload": {"to_name": "$route.assignee_name", "to_user_id": "$route.assignee_id", "by": "routing rule"}}}}, {"op": "case.add_parties", "when": {"field": "$route.level2_ids", "exists": true}, "params": {"case_id": "$inserted.cases.id", "users_from": "$route.level2_ids", "role": "level2"}}]$j$::jsonb, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, 1, true, 'other', 'block'
  FROM orgs o WHERE o.slug = 'godrej-emerald' ON CONFLICT (org_id, intent_key) DO NOTHING;
INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section, kind)
SELECT o.id, 'case_tell_parties', $j$Tell everyone on the case$j$, $j$Messages everyone on the case except the person doing this, once each. The caller gives the wording.$j$, 'action', $j$[{"op": "notify.parties", "when": {"field": "$fields.tell_buttons", "equals": "yes"}, "params": {"case": "$case", "message_template": "$fields.tell_message", "role_templates": {"assignee": "$fields.tell_message_assignee"}, "buttons": {"📝 Add update": "/update {case_case_number}", "👤 Pass on": "/assign {case_case_number}", "✅ Close": "/close {case_case_number}"}, "with_photos": true}}, {"op": "notify.parties", "when": {"field": "$fields.tell_buttons", "not_equals": "yes"}, "params": {"case": "$case", "message_template": "$fields.tell_message", "role_templates": {"assignee": "$fields.tell_message_assignee"}}}]$j$::jsonb, $j${"tell_message": {"type": "string", "required": true, "description": "The message. Use {case_case_number}, {case_title}, {actor_name} or a field name in braces."}, "tell_message_assignee": {"type": "string", "required": false, "description": "A different message for the person who now has the case. Leave out to send everyone the same."}, "tell_buttons": {"type": "string", "required": false, "description": "Say yes to put Add update, Pass on and Close buttons under the message."}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, true, 'other', 'block'
  FROM orgs o WHERE o.slug = 'godrej-emerald' ON CONFLICT (org_id, intent_key) DO NOTHING;

-- 3. the workflows people start
UPDATE workflows SET steps = $j$[{"op": "case.categorize", "params": {"text_from": ["$fields.title", "$fields.description"]}}, {"op": "case.route", "params": {}}, {"op": "run_workflow", "params": {"workflow": "case_create"}}, {"op": "run_workflow", "params": {"workflow": "case_apply_route"}}, {"op": "case.attach_photos", "params": {"case_id": "$inserted.cases.id"}}, {"op": "notify.parties", "params": {"case": "$inserted.cases", "message_template": "🆕 New case {case_case_number}: {case_title}\nWhere: {case_location} · Priority: {case_priority}\nCategory: {category_label}\nRaised by {actor_name}.", "role_templates": {"assignee": "🆕 A new case is with you: {case_case_number} — {case_title}\nWhere: {case_location} · Priority: {case_priority}\nRaised by {actor_name}."}, "buttons": {"📝 Add update": "/update {case_case_number}", "👤 Pass on": "/assign {case_case_number}", "✅ Close": "/close {case_case_number}"}, "with_photos": true}}, {"op": "notify.whatsapp", "params": {"attach_pdf": false}}]$j$::jsonb, response_template = $j$✅ *Complaint Registered*

Case #: *{case_number}*
Title: {title}
Category: {category_label}
Handled by: {assigned_name}
Status: reported

_Your complaint has been recorded._$j$, settings = settings || '{"photos": true}'::jsonb WHERE intent_key = 'file_a_complaint';
UPDATE workflows SET steps = $j$[{"op": "run_workflow", "params": {"workflow": "case_find"}}, {"op": "case.add_parties", "when": {"field": "$case.assigned_to_id", "exists": true}, "params": {"case_id": "$case.id", "users_from": "$case.assigned_to_id", "role": "helper"}}, {"op": "run_workflow", "params": {"workflow": "case_assign"}}, {"op": "run_workflow", "when": {"field": "$fields.comment_text", "exists": true}, "params": {"workflow": "case_comment"}}, {"op": "run_workflow", "params": {"workflow": "case_tell_parties", "inputs": {"tell_message": "ℹ️ Case {case_case_number} ({case_title}) is now with {assignee_name}.", "tell_message_assignee": "📋 Case {case_case_number} is now with you\n\n{case_title}\nWhere: {case_location}\nPassed on by {actor_name}.", "tell_buttons": "yes"}}}]$j$::jsonb, settings = settings || '{"who_can_use": ["assignee", "level2"]}'::jsonb WHERE intent_key = 'case_pass_on';
UPDATE workflows SET steps = $j$[{"op": "run_workflow", "params": {"workflow": "case_find"}}, {"op": "run_workflow", "params": {"workflow": "case_comment"}}, {"op": "case.attach_photos", "params": {"case_id": "$case.id"}}, {"op": "run_workflow", "params": {"workflow": "case_tell_parties", "inputs": {"tell_message": "📝 Case {case_case_number} ({case_title}): update from {actor_name}\n{comment_text}", "tell_buttons": "yes"}}}]$j$::jsonb, settings = settings || '{"who_can_use": ["requester", "assignee", "level2", "helper"], "photos": true}'::jsonb WHERE intent_key = 'case_add_update';
UPDATE workflows SET steps = $j$[{"op": "run_workflow", "params": {"workflow": "case_find"}}, {"op": "run_workflow", "params": {"workflow": "case_close", "inputs": {"note": "$fields.comment_text"}}}, {"op": "run_workflow", "params": {"workflow": "case_tell_parties", "inputs": {"tell_message": "✅ Case {case_case_number} ({case_title}) was closed by {actor_name}.\nClosing note: {comment_text}"}}}]$j$::jsonb, settings = settings || '{"who_can_use": ["assignee", "level2"]}'::jsonb WHERE intent_key = 'case_close_with_note';
UPDATE workflows SET sql_template = replace(replace(replace($j$SELECT cc.case_number, cc.title, cc.status, cc.priority, cc.location, cc.due_date, u2.name AS assigned_name FROM cases cc LEFT JOIN users u2 ON u2.id = cc.assigned_to_id WHERE cc.org_id = #1 AND cc.case_number ILIKE #2 AND (EXISTS (SELECT 1 FROM users me JOIN roles r ON r.id = me.role_id WHERE me.id = #3 AND 'check_case_status' = ANY(r.permissions)) OR EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = cc.id AND p.user_id = #3 AND p.ended_at IS NULL))$j$, '#1', chr(36) || '1'), '#2', chr(36) || '2'), '#3', chr(36) || '3'), sql_params_order = '["case_number", "$current_user"]'::jsonb, settings = settings || '{"who_can_use": ["requester", "assignee", "level2", "helper", "watcher"]}'::jsonb WHERE intent_key = 'check_case_status';
INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, sql_template, sql_params_order, response_format, gates, training_phrases, version, is_active, menu_section, kind, slash_command, command_description)
SELECT o.id, 'my_cases', $j$My cases$j$, $j$The open cases you raised or are on.$j$, 'read', '[]'::jsonb, '{}'::jsonb, replace(replace(replace($j$SELECT cc.case_number, cc.title, cc.status, cc.priority, cc.location, cc.due_date, string_agg(DISTINCT p.party_role, ', ') AS my_role FROM case_parties p JOIN cases cc ON cc.id = p.case_id WHERE cc.org_id = #1 AND p.user_id = #2 AND p.ended_at IS NULL AND cc.status <> 'closed' GROUP BY cc.id ORDER BY cc.created_at DESC LIMIT 20$j$, '#1', chr(36) || '1'), '#2', chr(36) || '2'), '#3', chr(36) || '3'), '["$current_user"]'::jsonb, 'list', '[]'::jsonb, '["my cases", "cases I am on", "what is with me"]'::jsonb, 1, true, 'reports', 'workflow', 'mycases', $j$Open cases you are on$j$
  FROM orgs o WHERE o.slug = 'godrej-emerald' ON CONFLICT (org_id, intent_key) DO NOTHING;
UPDATE workflows SET settings = settings || '{"who_can_use": ["requester", "assignee", "level2", "helper", "watcher"]}'::jsonb WHERE intent_key = 'my_cases';
SELECT intent_key, kind, is_active, slash_command, (settings -> 'who_can_use') AS who_can_use FROM workflows WHERE kind <> 'block' OR intent_key IN ('case_find', 'case_create', 'case_apply_route', 'case_tell_parties') ORDER BY kind, intent_key;
