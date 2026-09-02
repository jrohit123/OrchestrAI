-- ═══════════════════════════════════════════════════════════════════════════
-- MIGRATION 010 — don't double-notify a self-assigned case on close
--
-- assign_case's close steps unconditionally send TWO notify.user messages:
-- one to the prior assignee, one to the complainant. When a user assigned a
-- case to themselves (assignee == complainant), closing it sent them two
-- near-identical "closed" messages plus the normal action-confirmation reply
-- — three messages for one event. scheduler/jobs.py's reminder pass already
-- guards against this exact same_person case; assign_case's own close steps
-- never got the equivalent guard.
--
-- Requires (already deployed): step_interpreter.py's _eval_when_condition
-- now resolves a "$..." comparison value dynamically (via _when_value),
-- so a guard can compare two resolved entities against each other instead
-- of only ever comparing against a fixed literal.
--
-- Org: Godrej Emerald (793eead0-31b2-4538-b9b3-1885f9e94604)
-- ═══════════════════════════════════════════════════════════════════════════
BEGIN;

UPDATE workflows
   SET steps = $steps$[
       {
         "op": "require_permission",
         "params": {
           "from": "$fields.action",
           "map": {
             "assign":  "assign_case",
             "close":   "close_case",
             "comment": "add_case_comment"
           },
           "denied_message": "You don't have permission for that action on a case. You can still add a comment, or ask a committee member."
         }
       },
       {
         "op": "resolve_entity",
         "params": {
           "into": "case",
           "table": "cases",
           "name_from": "$fields.case_number",
           "match_column": "case_number",
           "normalize": "identifier",
           "expose": {
             "resolved_case_number": "case_number",
             "case_title": "title"
           }
         }
       },
       {
         "op": "resolve_entity",
         "when": {"field": "$fields.action", "equals": "assign"},
         "params": {
           "into": "assignee",
           "table": "users",
           "name_from": "$fields.assignee_name",
           "match_column": "name",
           "expose": {"resolved_assignee_name": "name"}
         }
       },
       {
         "op": "db.insert_row",
         "when": {"field": "$fields.comment_text", "exists": true},
         "params": {
           "table": "case_activity",
           "values": {
             "case_id": "$case.id",
             "actor_user_id": "$user.user_id",
             "activity_type": "comment",
             "payload": {"text": "$fields.comment_text"}
           }
         }
       },
       {
         "op": "db.update_row",
         "when": {"field": "$fields.action", "equals": "assign"},
         "params": {
           "table": "cases",
           "set": {"assigned_to_id": "$assignee.id"},
           "where": {"id": "$case.id"}
         }
       },
       {
         "op": "db.insert_row",
         "when": {"field": "$fields.action", "equals": "assign"},
         "params": {
           "table": "case_activity",
           "values": {
             "case_id": "$case.id",
             "actor_user_id": "$user.user_id",
             "activity_type": "assignment",
             "payload": {"to_user_id": "$assignee.id", "to_name": "$assignee.name"}
           }
         }
       },
       {
         "op": "db.update_row",
         "when": {"field": "$fields.action", "equals": "close"},
         "params": {
           "table": "cases",
           "set": {"status": "closed", "closed_at": "NOW()"},
           "where": {"id": "$case.id"}
         }
       },
       {
         "op": "db.insert_row",
         "when": {"field": "$fields.action", "equals": "close"},
         "params": {
           "table": "case_activity",
           "values": {
             "case_id": "$case.id",
             "actor_user_id": "$user.user_id",
             "activity_type": "status_change",
             "payload": {"to": "closed", "closing_note": "$fields.comment_text"}
           }
         }
       },
       {
         "op": "notify.user",
         "when": {"field": "$fields.action", "equals": "assign"},
         "params": {
           "to": "$assignee.phone",
           "message_template": "📋 Case Assigned To You\n\nCase #: {resolved_case_number}\n{case_title}\n\nReply to check status or add updates."
         }
       },
       {
         "op": "resolve_entity",
         "when": {"and": [{"field": "$fields.action", "equals": "close"},
                          {"field": "$case.assigned_to_id", "exists": true}]},
         "params": {
           "into": "prior_assignee",
           "table": "users",
           "name_from": "$case.assigned_to_id",
           "match_column": "id"
         }
       },
       {
         "op": "notify.user",
         "when": {"and": [{"field": "$fields.action", "equals": "close"},
                          {"field": "$case.assigned_to_id", "exists": true}]},
         "params": {
           "to": "$prior_assignee.phone",
           "message_template": "✅ Case {resolved_case_number} closed.\n\n{case_title}\n\nClosing note: {comment_text}"
         }
       },
       {
         "op": "resolve_entity",
         "when": {"field": "$fields.action", "equals": "close"},
         "params": {
           "into": "complainant",
           "table": "users",
           "name_from": "$case.complainant_id",
           "match_column": "id"
         }
       },
       {
         "op": "notify.user",
         "when": {"and": [{"field": "$fields.action", "equals": "close"},
                          {"field": "$complainant.phone", "not_equals": "$prior_assignee.phone"}]},
         "params": {
           "to": "$complainant.phone",
           "message_template": "✅ Your case {resolved_case_number} has been closed.\n\n{case_title}\n\nClosing note: {comment_text}"
         }
       }
     ]$steps$::jsonb
 WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604'
   AND intent_key = 'assign_case';

COMMIT;

-- ═══════════════════════════════════════════════════════════════════════════
-- POST-DEPLOY VERIFICATION
-- ═══════════════════════════════════════════════════════════════════════════
-- Close a case where assignee == complainant (self-assigned) and confirm
-- only ONE "closed" WhatsApp/Telegram message arrives, not two — the
-- deterministic "✅ Case {n} updated." reply to the actor's own "yes" is
-- separate and still expected once.
