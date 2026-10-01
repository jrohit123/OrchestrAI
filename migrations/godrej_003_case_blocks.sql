-- godrej_003_case_blocks.sql
--
-- The first set of building blocks for cases, and three case actions built from them.
-- Run it AFTER godrej_002_case_model.sql (or on its own: without the case model the blocks
-- are saved as ordinary workflows that nobody is given, so they never reach a menu).
-- Safe to run twice: a workflow that already exists is left alone.
--
-- Blocks (small steps other workflows run):
--   Find a case, Create a case, Give the case to someone, Add a note to a case,
--   Change a case's status, Change a case's priority, Close a case,
--   Tell the person who now has the case, Tell the person who raised the case
-- Case actions (switched OFF and given to nobody until you turn them on):
--   Pass to someone, Add an update, Close with a note
--
-- Not here yet because the assistant cannot do them yet: looking up who a category routes to,
-- saving a Telegram photo, telling everyone on a case at once, and the check that a person on
-- the case may act. Check Status and All Cases already do the two read-only ones.
-- Change any of it afterwards from Workflows in the dashboard.

BEGIN;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_find', $j$Find a case$j$, $j$Turns a case number (any format) into the case, so later steps can use it.$j$, 'action', $j$[{"op": "resolve_entity", "params": {"table": "cases", "into": "case", "name_from": "$fields.case_number", "match_column": "case_number", "normalize": "identifier"}}]$j$::jsonb, $j${"case_number": {"type": "string", "required": true, "description": "The case number, for example CS-26-08-00017. Any format is accepted."}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, true, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_create', $j$Create a case$j$, $j$Saves a new case, gives it a case number and works out its due time from the priority.$j$, 'action', $j$[{"op": "resolve_entity", "params": {"table": "priority_tat_rules", "into": "tat", "name_from": "$fields.priority", "match_column": "priority", "expose": {"tat_minutes": "tat_minutes"}}}, {"op": "derive_field", "params": {"field": "due_date", "expr": "due_from_tat(tat_minutes, \"minutes\")"}}, {"op": "db.insert_row", "params": {"table": "cases", "values": {"title": "$fields.title", "status": "reported", "due_date": "$fields.due_date", "location": "$fields.location", "priority": "$fields.priority", "description": "$fields.description", "complainant_id": "$user.user_id"}, "sequence": {"field": "case_number", "prefix": "CS-{YY}-{MM}-", "pad": 5, "start": 1}}}, {"op": "db.update_row", "when": {"field": "$fields.category_id", "exists": true}, "params": {"table": "cases", "set": {"category_id": "$fields.category_id"}, "where": {"id": "$inserted.cases.id"}}}, {"op": "db.insert_row", "params": {"table": "case_activity", "values": {"case_id": "$inserted.cases.id", "activity_type": "status_change", "actor_user_id": "$user.user_id", "payload": {"to": "reported"}}}}]$j$::jsonb, $j${"title": {"type": "string", "required": true, "description": "A short title for the problem."}, "description": {"type": "string", "required": false, "description": "What happened, in the person's words."}, "location": {"type": "string", "required": false, "description": "Where it is."}, "priority": {"type": "string", "required": true, "description": "How urgent it is.", "enum": ["urgent", "high", "medium", "low"]}, "category_id": {"type": "string", "required": false, "description": "The category's id, if one was chosen."}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, true, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_assign', $j$Give the case to someone$j$, $j$Hands the case to one person and records it on the timeline. Needs the case found first.$j$, 'action', $j$[{"op": "resolve_entity", "params": {"table": "users", "into": "assignee", "name_from": "$fields.assignee_name", "match_column": "name"}}, {"op": "db.update_row", "params": {"table": "cases", "set": {"assigned_to_id": "$assignee.id"}, "where": {"id": "$case.id"}}}, {"op": "db.insert_row", "params": {"table": "case_activity", "values": {"case_id": "$case.id", "activity_type": "assignment", "actor_user_id": "$user.user_id", "payload": {"to_name": "$assignee.name", "to_user_id": "$assignee.id"}}}}]$j$::jsonb, $j${"assignee_name": {"type": "string", "required": true, "description": "Who the case goes to. If the person says me or myself, use their own name."}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, true, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_comment', $j$Add a note to a case$j$, $j$Puts a note on the case's timeline. Needs the case found first.$j$, 'action', $j$[{"op": "db.insert_row", "params": {"table": "case_activity", "values": {"case_id": "$case.id", "activity_type": "comment", "actor_user_id": "$user.user_id", "payload": {"text": "$fields.comment_text"}}}}]$j$::jsonb, $j${"comment_text": {"type": "string", "required": true, "description": "The note to record."}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, true, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_set_status', $j$Change a case's status$j$, $j$Moves the case to another status and records it. Needs the case found first.$j$, 'action', $j$[{"op": "db.update_row", "params": {"table": "cases", "set": {"status": "$fields.status"}, "where": {"id": "$case.id"}}}, {"op": "db.update_row", "when": {"field": "$fields.status", "equals": "closed"}, "params": {"table": "cases", "set": {"closed_at": "NOW()"}, "where": {"id": "$case.id"}}}, {"op": "db.update_row", "when": {"field": "$fields.status", "not_equals": "closed"}, "params": {"table": "cases", "set": {"closed_at": null}, "where": {"id": "$case.id"}}}, {"op": "db.insert_row", "params": {"table": "case_activity", "values": {"case_id": "$case.id", "activity_type": "status_change", "actor_user_id": "$user.user_id", "payload": {"to": "$fields.status", "note": "$fields.note"}}}}]$j$::jsonb, $j${"status": {"type": "string", "required": true, "description": "The new status.", "enum": ["reported", "under_review", "action_taken", "closed"]}, "note": {"type": "string", "required": false, "description": "An optional note."}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, true, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_set_priority', $j$Change a case's priority$j$, $j$Changes the priority and restarts the due time for the new priority. Needs the case found first.$j$, 'action', $j$[{"op": "resolve_entity", "params": {"table": "priority_tat_rules", "into": "tat", "name_from": "$fields.priority", "match_column": "priority", "expose": {"tat_minutes": "tat_minutes"}}}, {"op": "derive_field", "params": {"field": "due_date", "expr": "due_from_tat(tat_minutes, \"minutes\")"}}, {"op": "db.update_row", "params": {"table": "cases", "set": {"priority": "$fields.priority", "due_date": "$fields.due_date"}, "where": {"id": "$case.id"}}}, {"op": "db.insert_row", "params": {"table": "case_activity", "values": {"case_id": "$case.id", "activity_type": "priority_change", "actor_user_id": "$user.user_id", "payload": {"to": "$fields.priority"}}}}]$j$::jsonb, $j${"priority": {"type": "string", "required": true, "description": "The new priority.", "enum": ["urgent", "high", "medium", "low"]}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, true, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_close', $j$Close a case$j$, $j$Closes the case with a closing note and records it. Needs the case found first.$j$, 'action', $j$[{"op": "db.update_row", "params": {"table": "cases", "set": {"status": "closed", "closed_at": "NOW()"}, "where": {"id": "$case.id"}}}, {"op": "db.insert_row", "params": {"table": "case_activity", "values": {"case_id": "$case.id", "activity_type": "status_change", "actor_user_id": "$user.user_id", "payload": {"to": "closed", "closing_note": "$fields.note"}}}}]$j$::jsonb, $j${"note": {"type": "string", "required": true, "description": "The closing note. Compulsory, so everyone knows what was done."}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, true, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_tell_assignee', $j$Tell the person who now has the case$j$, $j$Sends the new handler a message about the case. Needs the case found and the person chosen first.$j$, 'action', $j$[{"op": "notify.user", "params": {"to": "$assignee.phone", "message_template": "📋 Case {case_case_number} is now with you\n\n{case_title}\n\nReply to check status or add updates."}}]$j$::jsonb, $j${}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, true, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_tell_requester', $j$Tell the person who raised the case$j$, $j$Sends the person who raised the case a message. Give it tell_text, for example who has it now.$j$, 'action', $j$[{"op": "resolve_entity", "when": {"field": "$case.complainant_id", "exists": true}, "params": {"table": "users", "into": "requester", "name_from": "$case.complainant_id", "match_column": "id"}}, {"op": "notify.user", "when": {"field": "$requester.phone", "exists": true}, "params": {"to": "$requester.phone", "message_template": "ℹ️ Case {case_case_number} ({case_title}) is now with {tell_text}."}}]$j$::jsonb, $j${"tell_text": {"type": "string", "required": true, "description": "What to tell them."}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, true, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_pass_on', $j$Pass to someone$j$, $j$Hands a case to another person, keeps a note, and tells them and whoever raised it.$j$, 'action', $j$[{"op": "run_workflow", "params": {"workflow": "case_find"}}, {"op": "run_workflow", "params": {"workflow": "case_assign"}}, {"op": "run_workflow", "when": {"field": "$fields.comment_text", "exists": true}, "params": {"workflow": "case_comment"}}, {"op": "run_workflow", "params": {"workflow": "case_tell_assignee"}}, {"op": "run_workflow", "params": {"workflow": "case_tell_requester", "inputs": {"tell_text": "$assignee.name"}}}]$j$::jsonb, $j${"case_number": {"type": "string", "required": true, "description": "The case number, for example CS-26-08-00017. Any format is accepted."}, "assignee_name": {"type": "string", "required": true, "description": "Who the case goes to."}, "comment_text": {"type": "string", "required": false, "description": "An optional note for them."}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, false, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_add_update', $j$Add an update$j$, $j$Adds a note to a case.$j$, 'action', $j$[{"op": "run_workflow", "params": {"workflow": "case_find"}}, {"op": "run_workflow", "params": {"workflow": "case_comment"}}]$j$::jsonb, $j${"case_number": {"type": "string", "required": true, "description": "The case number, for example CS-26-08-00017. Any format is accepted."}, "comment_text": {"type": "string", "required": true, "description": "The note to add."}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, false, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section)
SELECT o.id, 'case_close_with_note', $j$Close with a note$j$, $j$Closes a case. The closing note is compulsory.$j$, 'action', $j$[{"op": "run_workflow", "params": {"workflow": "case_find"}}, {"op": "run_workflow", "params": {"workflow": "case_close", "inputs": {"note": "$fields.comment_text"}}}]$j$::jsonb, $j${"case_number": {"type": "string", "required": true, "description": "The case number, for example CS-26-08-00017. Any format is accepted."}, "comment_text": {"type": "string", "required": true, "description": "The closing note."}}$j$::jsonb, '[]'::jsonb, '[]'::jsonb, 1, false, 'other'
  FROM orgs o WHERE o.slug = 'godrej-emerald'
ON CONFLICT (org_id, intent_key) DO NOTHING;

-- mark which are blocks and which are case actions, when the database knows about kinds
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'workflows' AND column_name = 'kind') THEN
        UPDATE workflows SET kind = 'block' WHERE intent_key IN ('case_find', 'case_create', 'case_assign', 'case_comment', 'case_set_status', 'case_set_priority', 'case_close', 'case_tell_assignee', 'case_tell_requester');
        UPDATE workflows SET kind = 'case_action' WHERE intent_key IN ('case_pass_on', 'case_add_update', 'case_close_with_note');
    END IF;
END $$;

COMMIT;
