-- ── Update register_complaint workflow for category/subcategory/SLA support ──
-- This updates the existing register_complaint workflow to include:
-- - Category and subcategory selection with TAT/SLA
-- - Automatic due_date calculation from subcategory TAT
-- - Enhanced response template with SLA information
-- ────────────────────────────────────────────────────────────────────────────────

UPDATE workflows
SET
  entity_schema = '{
    "complaint_title": {"type":"string","required":true},
    "complaint_description": {"type":"string","required":false},
    "priority": {"type":"string","required":false,"default":"medium"},
    "incident_location": {"type":"string","required":true},
    "animal_type": {"type":"string","required":false},
    "category_name": {"type":"string","required":true,
      "table":"case_categories","column":"name","match":"ILIKE","format":"wildcard"},
    "subcategory_name": {"type":"string","required":true,
      "table":"case_subcategories","column":"name","match":"ILIKE","format":"wildcard"},
    "tat_value": {"type":"integer","required":false,"computed":true},
    "tat_unit": {"type":"string","required":false,"computed":true},
    "due_date": {"type":"string","required":false,"computed":true}
  }'::jsonb,

  calc_rules = '{
    "aggregate_rules": {
      "due_date": "due_from_tat(tat_value, tat_unit)"
    }
  }'::jsonb,

  steps = '[
    {"op":"resolve_entity","params":{
      "table":"case_categories","name_from":"$fields.category_name",
      "into":"category","match_column":"name"
    }},
    {"op":"resolve_entity","params":{
      "table":"case_subcategories","name_from":"$fields.subcategory_name",
      "into":"subcategory","match_column":"name",
      "expose":{"tat_value":"tat_value","tat_unit":"tat_unit"}
    }},
    {"op":"compute","params":{}},
    {"op":"db.insert_row","params":{
      "table":"complaint_cases",
      "values":{
        "org_id":"$org_id",
        "complaint_title":"$fields.complaint_title",
        "complaint_description":"$fields.complaint_description",
        "priority":"$fields.priority",
        "incident_location":"$fields.incident_location",
        "animal_type":"$fields.animal_type",
        "category_id":"$category.id",
        "subcategory_id":"$subcategory.id",
        "due_date":"$computed.due_date",
        "complainant_id":"$user.user_id",
        "status":"reported"
      },
      "sequence":{"field":"case_number","prefix":"CS-26-08-","start":1}
    }},
    {"op":"notify.whatsapp","params":{"attach_pdf":false}}
  ]'::jsonb,

  response_template = '✅ *Complaint Registered*

Case #: *{case_number}*
Title: {complaint_title}
Category: {category_name} — {subcategory_name}
Priority: {priority}
Due by: {due_date}

_Committee has been notified._',

  business_glossary = business_glossary || '{
    "AMC": "Annual Maintenance Contract renewal",
    "wear and tear": "general maintenance category",
    "dues": "accounts category — outstanding payments"
  }'::jsonb

WHERE intent_key = 'register_complaint'
  AND org_id = (SELECT id FROM orgs WHERE slug = 'godrej-emerald');

-- ── NOTES ───────────────────────────────────────────────────────────────────
-- This update assumes:
-- 1. register_complaint workflow already exists in the workflows table
-- 2. case_categories and case_subcategories tables exist (created by housing_society_extensions.sql)
-- 3. The org slug is 'godrej-emerald' (update if different)
--
-- Key changes:
-- - Added category_name and subcategory_name as required fields with entity resolution
-- - Added tat_value and tat_unit as computed fields from subcategory
-- - Added due_date as computed field using due_from_tat function
-- - Updated db.insert_row to include category_id, subcategory_id, and due_date
-- - Removed case_number from values (handled by sequence parameter)
-- - Enhanced response template to show category and due date
-- - Added business glossary terms for AMC, wear and tear, dues
