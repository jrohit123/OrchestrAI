-- Case Assignment + Priority-Based TAT Reminders Implementation
-- Run this file to set up the complete feature for Godrej Emerald

-- ============================================================
-- 1. Schema Changes
-- ============================================================

-- Create priority_tat_rules table
CREATE TABLE IF NOT EXISTS public.priority_tat_rules (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,
    priority character varying(10) NOT NULL,
    tat_minutes integer NOT NULL,
    reminder_threshold_minutes integer NOT NULL,
    created_at timestamptz DEFAULT now(),
    CONSTRAINT priority_tat_rules_priority_check
        CHECK (priority IN ('urgent','high','medium','low')),
    CONSTRAINT priority_tat_rules_org_priority_key UNIQUE (org_id, priority)
);

-- Add reminder_sent_at column to cases table (if not exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'cases' AND column_name = 'reminder_sent_at'
    ) THEN
        ALTER TABLE public.cases ADD COLUMN reminder_sent_at timestamptz;
    END IF;
END $$;

-- ============================================================
-- 2. Seed priority_tat_rules for Godrej Emerald
-- ============================================================

INSERT INTO priority_tat_rules (org_id, priority, tat_minutes, reminder_threshold_minutes) VALUES
  ('793eead0-31b2-4538-b9b3-1885f9e94604'::uuid, 'urgent', 120,   30),
  ('793eead0-31b2-4538-b9b3-1885f9e94604'::uuid, 'high',   480,   120),
  ('793eead0-31b2-4538-b9b3-1885f9e94604'::uuid, 'medium', 1440,  360),
  ('793eead0-31b2-4538-b9b3-1885f9e94604'::uuid, 'low',    2880,  720)
ON CONFLICT (org_id, priority) DO NOTHING;

-- ============================================================
-- 3. Update register_complaint workflow to compute due_date
-- ============================================================

UPDATE workflows
SET steps = '[
  {"op":"resolve_entity","params":{"table":"priority_tat_rules","match_column":"priority","name_from":"$fields.priority","into":"tat","expose":{"tat_minutes":"tat_minutes"}}},
  {"op":"derive_field","params":{"field":"due_date","expr":"due_from_tat(tat_minutes, \"minutes\")"}},
  {"op":"db.insert_row","params":{"table":"cases","values":{"title":"$fields.title","status":"reported","location":"$fields.location","priority":"$fields.priority","description":"$fields.description","complainant_id":"$user.user_id","due_date":"$fields.due_date"},"sequence":{"field":"case_number","start":1,"prefix":"CS-26-08-"}}},
  {"op":"notify.whatsapp","params":{"attach_pdf":false}}
]'::jsonb,
    calc_rules = '{}'::jsonb,
    entity_schema = entity_schema || '{"due_date": {"type":"string","required":false,"computed":true,"description":"Auto-computed from priority TAT — never collected from the user"}}'::jsonb
WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604'::uuid
  AND intent_key = 'register_complaint';

-- ============================================================
-- 4. Seed case_reminders config in orgs.settings
-- ============================================================

UPDATE orgs
SET settings = settings || '{
  "case_reminders": {
    "enabled": true,
    "table": "cases",
    "case_number_column": "case_number",
    "title_column": "title",
    "priority_column": "priority",
    "status_column": "status",
    "created_at_column": "created_at",
    "reminder_sent_column": "reminder_sent_at",
    "assignee_id_column": "assigned_to_id",
    "complainant_id_column": "complainant_id",
    "closed_values": ["closed"],
    "assignee_message_template": "\u23f0 *Reminder — Case {case_number}*\n{title}\nPriority: {priority} | Status: {status}\nThis case is still open past its reminder threshold.",
    "complainant_message_template": "\u23f0 Update on your case *{case_number}* — still being worked on (status: {status})."
  }
}'::jsonb
WHERE id = '793eead0-31b2-4538-b9b3-1885f9e94604'::uuid;

-- ============================================================
-- 5. Insert assign_case workflow
-- ============================================================

INSERT INTO workflows (
  org_id, intent_key, name, workflow_type, is_active,
  training_phrases, entity_schema, steps,
  business_glossary, llm_system_prompt, response_template,
  menu_section, slash_command, command_description
) VALUES (
  '793eead0-31b2-4538-b9b3-1885f9e94604'::uuid,
  'assign_case', 'Assign Case', 'action', true,
  '["assign {case_number} to {name}", "{name} ko {case_number} assign karo",
    "give this case to {name}", "assign case to {name}", "{case_number} de do {name} ko",
    "hand this over to {name}", "assign to myself", "self assign {case_number}"]'::jsonb,
  '{
    "case_number": {"type":"string","required":true,"description":"Case number to assign, e.g. CS-26-08-00011"},
    "assignee_name": {"type":"string","required":true,"description":"Name of the person the case should go to. If the user says \"myself\"/\"me\", use their own name."}
  }'::jsonb,
  '[
    {"op":"resolve_entity","params":{"table":"cases","match_column":"case_number","name_from":"$fields.case_number","into":"case"}},
    {"op":"resolve_entity","params":{"table":"users","match_column":"name","name_from":"$fields.assignee_name","into":"assignee"}},
    {"op":"db.update_row","params":{"table":"cases","set":{"assigned_to_id":"$assignee.id"},"where":{"case_number":"$fields.case_number"}}},
    {"op":"notify.user","params":{"to":"$assignee.phone","message_template":"\ud83d\udccb *Case Assigned To You*\n\nCase #: {case_number}\nYou have been assigned this case. Reply to check status or add updates."}}
  ]'::jsonb,
  '{"assign":"assign the case","dedo":"assign","handle karo":"assign to self"}'::jsonb,
  'Assigns an existing case to a user. Resolves case_number against cases table and assignee_name against users table (both by name/case_number match). If the user says "assign to myself" or similar, assignee_name should be set to the current user''s own name. Requires assign_case permission.',
  '\u2705 *Case Assigned*\n\nCase #: *{case_number}*\nAssigned to: {assignee_name}',
  'other', 'assign', 'Assign a case to someone'
)
ON CONFLICT (org_id, intent_key) DO NOTHING;

-- ============================================================
-- 6. Insert close_case workflow
-- ============================================================

INSERT INTO workflows (
  org_id, intent_key, name, workflow_type, is_active,
  training_phrases, entity_schema, steps,
  business_glossary, llm_system_prompt, response_template,
  menu_section, slash_command, command_description
) VALUES (
  '793eead0-31b2-4538-b9b3-1885f9e94604'::uuid,
  'close_case', 'Close Case', 'action', true,
  '["close {case_number}", "{case_number} band karo", "resolve {case_number}",
    "mark {case_number} as closed", "issue fixed {case_number}", "case solved {case_number}"]'::jsonb,
  '{"case_number": {"type":"string","required":true,"description":"Case number to close"}}'::jsonb,
  '[
    {"op":"resolve_entity","params":{"table":"cases","match_column":"case_number","name_from":"$fields.case_number","into":"case"}},
    {"op":"db.update_row","params":{"table":"cases","set":{"status":"closed","closed_at":"NOW()"},"where":{"case_number":"$fields.case_number"}}},
    {"op":"resolve_entity","params":{"table":"users","match_column":"id","name_from":"$case.complainant_id","into":"complainant"}},
    {"op":"notify.user","params":{"to":"$complainant.phone","message_template":"\u2705 Your case *{case_number}* has been closed."}}
  ]'::jsonb,
  '{"band":"closed","resolve":"close","solved":"closed"}'::jsonb,
  'Marks an existing case as closed and sets closed_at. Resolve case_number against cases table first. Requires close_case permission.',
  '\u2705 *Case Closed*\n\nCase #: *{case_number}*',
  'other', 'close', 'Close a case'
)
ON CONFLICT (org_id, intent_key) DO NOTHING;

-- ============================================================
-- 7. Insert add_case_comment workflow
-- ============================================================

INSERT INTO workflows (
  org_id, intent_key, name, workflow_type, is_active,
  training_phrases, entity_schema, steps,
  business_glossary, llm_system_prompt, response_template,
  menu_section, slash_command, command_description
) VALUES (
  '793eead0-31b2-4538-b9b3-1885f9e94604'::uuid,
  'add_case_comment', 'Add Case Comment', 'action', true,
  '["comment on {case_number}", "{case_number} mein note likho", "add update to {case_number}",
    "update {case_number}: {comment}", "remarks daalo {case_number}"]'::jsonb,
  '{
    "case_number": {"type":"string","required":true,"description":"Case number to comment on"},
    "comment_text": {"type":"string","required":true,"description":"The comment/update text"}
  }'::jsonb,
  '[
    {"op":"resolve_entity","params":{"table":"cases","match_column":"case_number","name_from":"$fields.case_number","into":"case"}},
    {"op":"db.insert_row","params":{"table":"case_activity","values":{"case_id":"$case.id","actor_user_id":"$user.user_id","activity_type":"comment","payload":{"text":"$fields.comment_text"}}}}
  ]'::jsonb,
  '{"note":"comment","update":"comment","remarks":"comment"}'::jsonb,
  'Adds a comment/note to an existing case activity log. Resolve case_number first, then insert into case_activity with activity_type=comment.',
  '\u2705 Comment added to case *{case_number}*.',
  'other', 'comment', 'Add a note to a case'
)
ON CONFLICT (org_id, intent_key) DO NOTHING;

-- ============================================================
-- 8. For testing: Shrink TAT for low priority to minute-scale
-- ============================================================

-- Uncomment the following to enable fast testing (5-minute reminder threshold)
-- UPDATE priority_tat_rules
-- SET tat_minutes = 10, reminder_threshold_minutes = 5
-- WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604'::uuid AND priority = 'low';

-- ============================================================
-- Verification Queries
-- ============================================================

-- Check priority_tat_rules
-- SELECT * FROM priority_tat_rules WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604';

-- Check cases table has reminder_sent_at column
-- SELECT column_name, data_type FROM information_schema.columns 
-- WHERE table_name = 'cases' AND column_name = 'reminder_sent_at';

-- Check orgs.settings has case_reminders config
-- SELECT settings->'case_reminders' FROM orgs WHERE id = '793eead0-31b2-4538-b9b3-1885f9e94604';

-- Check new workflows exist
-- SELECT intent_key, name FROM workflows WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604' AND intent_key IN ('assign_case', 'close_case', 'add_case_comment');
