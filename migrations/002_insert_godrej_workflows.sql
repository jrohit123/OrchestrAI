-- ═══════════════════════════════════════════════════════════════
-- Godrej Emerald Workflows - INSERT Statements
-- 
-- This file inserts two workflows for the Godrej Emerald housing society:
-- 1. register_complaint - Action workflow to file new complaints
-- 2. view_all_cases - Read workflow to list recent cases
-- 
-- Both workflows use intent_keys that are already granted in roles.permissions
-- for this org, so no role/permission changes are needed.
-- ═══════════════════════════════════════════════════════════════

-- ═══════════════════════════════════════════════════════════════
-- 1) ACTION WORKFLOW — register_complaint
--    Triggerable via: /complaint, or natural language ("register a
--    complaint about ..."), or by sending the exact text
--    "register_complaint" (fast-path in agent.py).
-- ═══════════════════════════════════════════════════════════════
INSERT INTO workflows (
    org_id, intent_key, name, steps, is_active, otp_required, otp_threshold,
    version, last_run, created_at, is_scheduled, schedule_cron, scheduled_by,
    approval_threshold, description, workflow_type, training_phrases, entity_schema,
    sql_template, sql_params_order, response_format, business_glossary,
    llm_system_prompt, pdf_config, response_template, calc_rules,
    slash_command, command_description, menu_section
) VALUES (
    '793eead0-31b2-4538-b9b3-1885f9e94604',   -- Godrej Emerald org_id
    'register_complaint',
    'Register Complaint',
    '[
        {"op":"db.insert_row","params":{
            "table":"cases",
            "values":{
                "complainant_id":"$user.user_id",
                "title":"$fields.title",
                "description":"$fields.description",
                "location":"$fields.location",
                "priority":"$fields.priority",
                "status":"reported"
            },
            "sequence":{"field":"case_number","prefix":"CS-26-08-","start":1}
        }},
        {"op":"notify.whatsapp","params":{"attach_pdf": false}}
    ]'::jsonb,
    true,
    false,
    NULL,
    1,
    NULL,
    now(),
    false,
    NULL,
    NULL,
    NULL,
    'Files a new complaint/case for the resident against a category (cleanliness, maintenance, accounts, misc).',
    'action',
    '["complaint register karo", "case file karo", "register a complaint", "new complaint about {title}", "shikayat darz karo", "report an issue", "file a case", "complaint karna hai", "issue report karo {title}", "book a complaint"]'::jsonb,
    '{}'::jsonb,
    NULL,
    '[]'::jsonb,
    'generic',
    '{"shikayat":"complaint","case":"complaint","issue":"complaint","band karo":"close the case"}'::jsonb,
    'Registers a new case in the cases table for this housing society. Required: title (short summary), optional: description, location, priority (urgent/high/medium/low, default medium). Example: "register a complaint about garbage not collected in Wing 3" -> title="Garbage not collected", location="Wing 3". This workflow is NOT for checking status of an existing case (that is a read query) and NOT for adding a comment to an existing case.',
    NULL,
    '✅ *Complaint Registered*

Case #: *{case_number}*
Title: {title}
Status: reported

_The committee has been notified._',
    '{}'::jsonb,
    'complaint',
    'File a new complaint or case',
    'create'
);

-- ═══════════════════════════════════════════════════════════════
-- 2) READ WORKFLOW — view_all_cases
--    Triggerable via: /cases, or the exact text "view_all_cases"
--    (fast-path direct execution — entity_schema is empty so this
--    skips the LLM entirely and formats real rows).
-- ═══════════════════════════════════════════════════════════════
INSERT INTO workflows (
    org_id, intent_key, name, steps, is_active, otp_required, otp_threshold,
    version, last_run, created_at, is_scheduled, schedule_cron, scheduled_by,
    approval_threshold, description, workflow_type, training_phrases, entity_schema,
    sql_template, sql_params_order, response_format, business_glossary,
    llm_system_prompt, pdf_config, response_template, calc_rules,
    slash_command, command_description, menu_section
) VALUES (
    '793eead0-31b2-4538-b9b3-1885f9e94604',
    'view_all_cases',
    'All Cases',
    '[]'::jsonb,
    true,
    false,
    NULL,
    1,
    NULL,
    now(),
    false,
    NULL,
    NULL,
    NULL,
    'Lists the most recent cases/complaints for this society, newest first.',
    'read',
    '["show all cases", "sab cases dikhao", "list complaints", "open complaints", "recent complaints", "case list", "sab shikayat dikhao", "show recent cases", "all complaints dikhao", "complaints list"]'::jsonb,
    '{}'::jsonb,
    'SELECT cc.case_number, cc.title, cc.status, cc.priority, cc.location,
            cc.created_at, u1.name AS complainant_name, u2.name AS assigned_name
     FROM cases cc
     LEFT JOIN users u1 ON u1.id = cc.complainant_id
     LEFT JOIN users u2 ON u2.id = cc.assigned_to_id
     WHERE cc.org_id = $1
     ORDER BY cc.created_at DESC
     LIMIT 20',
    '[]'::jsonb,
    'generic',
    '{"baaki":"pending cases","band":"closed cases","khula":"open cases"}'::jsonb,
    'Lists recent cases/complaints for the society, most recent first, including status, priority, location, who reported it and who it is assigned to. Use this for any general "show me cases/complaints" request with no specific filter. For a single case by number, or filtered by animal type/location/category, write a fresh query against the cases table instead of using this fixed template.',
    '{"doc_type":"report","title_template":"All Cases — Godrej Emerald","aging_analysis":false,"show_key_insights":true,"insight_focus":"Flag any urgent/high priority cases still in reported status."}'::jsonb,
    NULL,
    '{}'::jsonb,
    'cases',
    'Show recent complaints/cases',
    'reports'
);

-- ═══════════════════════════════════════════════════════════════
-- NOTE ON case_number SEQUENCE PREFIX
-- ═══════════════════════════════════════════════════════════════
-- The prefix "CS-26-08-" is correct for August 2026.
-- If testing in a later month, update the prefix in the first INSERT:
-- - September 2026: "CS-26-09-"
-- - October 2026: "CS-26-10-"
-- etc.
--
-- Or run: UPDATE workflows SET steps = jsonb_set(steps, '{0,params,sequence,prefix}',
-- '"CS-26-MM-"') WHERE intent_key = 'register_complaint';
-- where MM is the two-digit month.
