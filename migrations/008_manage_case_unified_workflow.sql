-- ═══════════════════════════════════════════════════════════════════════════
-- MIGRATION 008 — fold close_case and add_case_comment into assign_case
--
-- Final workflow count for this org: exactly 3 active workflows —
--   view_all_cases (untouched), register_complaint (untouched),
--   assign_case (expanded to handle assign / comment / close).
--
-- assign_case KEEPS its existing intent_key, id, and slash_command ("assign")
-- — it is not replaced by a new workflow. close_case and add_case_comment
-- are deactivated; their capabilities move into assign_case's own steps.
--
-- Permissions are UNCHANGED: roles already hold assign_case / close_case /
-- add_case_comment as separate permission strings. That granularity is kept
-- and enforced by a require_permission step inside assign_case itself
-- (mapped by the `action` field), so staff who only ever had
-- add_case_comment still cannot close a case just because the workflow
-- merged — no role/permission UPDATE is needed for this migration.
--
-- Requires (already deployed in this repo):
--   - step_interpreter.py: _step_enabled with "and" support (for the
--     "notify assignee only when action=close AND case had an assignee")
--   - step_interpreter.py: _op_require_permission
--   - step_interpreter.py: normalize: "identifier" in _op_resolve_entity
--   - qa_verifier.py / agent.py: required_if support
--   - MIGRATION 007 (case_number_norm) must run BEFORE this one.
--
-- Org: Godrej Emerald (793eead0-31b2-4538-b9b3-1885f9e94604)
-- ═══════════════════════════════════════════════════════════════════════════
BEGIN;

UPDATE workflows
   SET
     name                = 'Assign / Update Case',
     description          = 'Assign a case, add an optional progress comment, or close it. Closing always records a comment so both the assignee and the original complainant know the outcome.',
     command_description  = 'Assign, comment on, or close a case',
     training_phrases = '["assign {case_number} to {name}", "{name} ko {case_number} assign karo",
  "give case to {name}", "hand this case over to {name}", "assign to myself",
  "close {case_number}", "{case_number} band karo", "resolve {case_number}",
  "mark {case_number} as closed", "issue fixed {case_number}",
  "comment on {case_number}", "add update to {case_number}",
  "{case_number} mein note likho", "remarks daalo {case_number}",
  "update case {case_number}"]'::jsonb,
     entity_schema = $es${
       "action": {
         "type": "string",
         "required": true,
         "enum": ["assign", "comment", "close"],
         "description": "What to do with the case. assign = give it to someone; comment = add an optional progress note; close = resolve and close it."
       },
       "case_number": {
         "type": "string",
         "required": true,
         "description": "The case number, e.g. CS-26-08-00017. Accept whatever format the user types — the system normalises it."
       },
       "assignee_name": {
         "type": "string",
         "required_if": {"field": "action", "equals": "assign"},
         "description": "Who the case goes to. If the user says 'me'/'myself', use their own name."
       },
       "comment_text": {
         "type": "string",
         "required_if": {"field": "action", "in": ["close", "comment"]},
         "description": "The note to record. Optional when assigning. MANDATORY when closing — this is the closing note so both the assignee and the complainant know what was done."
       }
     }$es$::jsonb,
     steps = $steps$[
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
         "when": {"field": "$fields.action", "equals": "close"},
         "params": {
           "to": "$complainant.phone",
           "message_template": "✅ Your case {resolved_case_number} has been closed.\n\n{case_title}\n\nClosing note: {comment_text}"
         }
       }
     ]$steps$::jsonb,
     response_template = '✅ Case {resolved_case_number} updated.
{case_title}',
     business_glossary = '{"band karo": "close the case", "solved": "close the case",
  "resolve": "close the case", "de do": "assign", "dedo": "assign",
  "note": "comment", "remarks": "comment", "update": "comment",
  "handle karo": "assign to self"}'::jsonb,
     llm_system_prompt = $lsp$Single entry point for every change to an EXISTING case. Do not use this
to create a new case — that is register_complaint.

FIRST decide `action` from the user's words:
  "assign X to Y", "give to", "de do", "hand over"     -> action = "assign"
  "close", "band karo", "resolve", "fixed", "done"     -> action = "close"
  "comment", "note", "update", "remarks", "add"        -> action = "comment"

If the user's wording is genuinely ambiguous between two actions, ask which
one they mean. Never guess between close and comment — they are not
reversible in the same way.

CLOSING ALWAYS NEEDS A NOTE. When action = "close" and comment_text is
empty, you MUST ask before calling confirm_action, e.g.:
  "Before I close CS-26-08-00017 — what was done to resolve it? I'll let
   both the assignee and the original complainant know."
Do not accept "closed"/"done"/"ok" as the note; ask again for a real
description of the resolution.

ASSIGNING never requires a comment — only ask for one if the user
volunteers one.

CASE NUMBERS: accept whatever the user types — "cs260817", "CS 26 08 17",
"case 17" all resolve. Never tell a user a case does not exist because of
formatting. Pass their text through unchanged as case_number.

SELF-ASSIGNMENT: "assign to me"/"myself"/"mujhe" -> set assignee_name to the
current user's own name; the engine resolves it deterministically.

CONFIRMATION: details{} must contain ONLY user-facing values — action,
case_number, comment_text, assignee_name. NEVER include ids, org_id,
status internals, or any $-prefixed value.$lsp$
 WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604'
   AND intent_key = 'assign_case';

-- Retire the two absorbed workflows (deactivate, not delete — audit_log
-- and case_activity keep historical references to these intent_keys).
UPDATE workflows
   SET is_active = false
 WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604'
   AND intent_key IN ('close_case', 'add_case_comment');

-- Repair any comment corrupted by the D3 resolver bug before it was fixed
UPDATE case_activity
   SET payload = jsonb_set(
         payload, '{text}',
         to_jsonb('[recovered — original text lost to a resolver bug before it was fixed]'::text)
       )
 WHERE payload->>'text' LIKE '$fields.%';

-- Backfill a status_change row for any case closed with no history
INSERT INTO case_activity (org_id, case_id, actor_user_id, activity_type, payload, created_at)
SELECT c.org_id, c.id, c.assigned_to_id, 'status_change',
       jsonb_build_object(
         'to', 'closed',
         'closing_note', '[backfilled] Closed before closing notes were mandatory.'
       ),
       c.closed_at
  FROM cases c
 WHERE c.org_id = '793eead0-31b2-4538-b9b3-1885f9e94604'
   AND c.status = 'closed'
   AND c.closed_at IS NOT NULL
   AND NOT EXISTS (
        SELECT 1 FROM case_activity a
         WHERE a.case_id = c.id AND a.activity_type = 'status_change'
   );

COMMIT;

-- ═══════════════════════════════════════════════════════════════════════════
-- POST-DEPLOY VERIFICATION
-- ═══════════════════════════════════════════════════════════════════════════
-- Exactly 3 active workflows should remain:
--   SELECT intent_key FROM workflows
--    WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604' AND is_active
--    ORDER BY intent_key;
--   -> assign_case, register_complaint, view_all_cases
--
-- Zero rows expected: no unresolved placeholders anywhere
--   SELECT id FROM case_activity WHERE payload::text LIKE '%$fields.%';
--
-- Zero rows expected: every closed case has a closing note on record
--   SELECT c.case_number FROM cases c WHERE c.status='closed'
--    AND NOT EXISTS (SELECT 1 FROM case_activity a WHERE a.case_id=c.id
--                    AND a.activity_type='status_change');
