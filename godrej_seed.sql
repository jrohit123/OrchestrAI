-- ============================================================
-- GODREJ EMERALD — Seed Data (self-contained, no placeholders)
-- Run on the Godrej Emerald Railway Postgres database
-- ============================================================

DO $$
DECLARE
  v_org_id        uuid;
  v_admin_role    uuid;
  v_committee_role uuid;
  v_member_role   uuid;
BEGIN

  -- ── 1. Org ──────────────────────────────────────────────────
  INSERT INTO orgs (name, slug, industry, plan, is_active, session_ttl_minutes, context_message_limit)
  VALUES ('Godrej Emerald', 'godrej-emerald', 'housing_society', 'trial', true, 480, 12)
  RETURNING id INTO v_org_id;

  RAISE NOTICE 'Created org: %', v_org_id;

  -- ── 2. Roles ─────────────────────────────────────────────────
  INSERT INTO roles (org_id, name, permissions, readable_tables)
  VALUES (
    v_org_id, 'admin',
    ARRAY['general_read','register_complaint','assign_case','close_case',
          'add_case_comment','view_all_cases','view_my_cases'],
    ARRAY['complaint_cases','case_comments','case_evidence','users']
  ) RETURNING id INTO v_admin_role;

  INSERT INTO roles (org_id, name, permissions, readable_tables)
  VALUES (
    v_org_id, 'committee',
    ARRAY['general_read','register_complaint','assign_case','close_case',
          'add_case_comment','view_all_cases','view_my_cases'],
    ARRAY['complaint_cases','case_comments','case_evidence']
  ) RETURNING id INTO v_committee_role;

  INSERT INTO roles (org_id, name, permissions, readable_tables)
  VALUES (
    v_org_id, 'member',
    ARRAY['general_read','register_complaint','add_case_comment','view_my_cases'],
    ARRAY['complaint_cases','case_comments']
  ) RETURNING id INTO v_member_role;

  RAISE NOTICE 'Created roles — admin: %, committee: %, member: %',
    v_admin_role, v_committee_role, v_member_role;

  -- ── 3. Users ─────────────────────────────────────────────────
  -- phone = NULL so they self-link via Telegram email flow
  -- ⚠️  REPLACE names and emails below with real data before running

  INSERT INTO users (org_id, role_id, name, email, phone, channel, is_active)
  VALUES
    (v_org_id, v_admin_role,     'Kartik Batchu',   'kartik@orchestrai.com',       'tg:8572134702', 'telegram', true),
    (v_org_id, v_admin_role,     'Society Admin',   'admin@godrejemerald.com',     NULL, 'telegram', true),
    (v_org_id, v_committee_role, 'Rahul Sharma',    'rahul@godrejemerald.com',     NULL, 'telegram', true),
    (v_org_id, v_committee_role, 'Priya Desai',     'priya@godrejemerald.com',     NULL, 'telegram', true),
    (v_org_id, v_member_role,    'Amit Patel',      'amit.patel@example.com',      NULL, 'telegram', true),
    (v_org_id, v_member_role,    'Sunita Mehta',    'sunita.mehta@example.com',    NULL, 'telegram', true);

  RAISE NOTICE 'Created users';

  -- ── 4. Sample complaint cases (optional — remove if not needed) ──
  INSERT INTO complaint_cases (org_id, case_number, complaint_title, complaint_description,
    status, priority, animal_type, incident_location,
    complainant_id, assigned_to_id)
  SELECT
    v_org_id,
    'CS-26-08-00001',
    'Stray dog near Wing A entrance',
    'A stray dog has been aggressive near the Wing A entrance gate for the past 3 days.',
    'reported', 'high', 'dog', 'Wing A entrance',
    (SELECT id FROM users WHERE org_id = v_org_id AND email = 'amit.patel@example.com'),
    (SELECT id FROM users WHERE org_id = v_org_id AND email = 'rahul@godrejemerald.com');

  INSERT INTO complaint_cases (org_id, case_number, complaint_title, complaint_description,
    status, priority, animal_type, incident_location,
    complainant_id, assigned_to_id)
  SELECT
    v_org_id,
    'CS-26-08-00002',
    'Cat colony in basement parking',
    'Large number of stray cats in B2 basement parking. Residents are concerned.',
    'under_review', 'medium', 'cat', 'B2 Basement Parking',
    (SELECT id FROM users WHERE org_id = v_org_id AND email = 'sunita.mehta@example.com'),
    (SELECT id FROM users WHERE org_id = v_org_id AND email = 'priya@godrejemerald.com');

  RAISE NOTICE 'Created sample cases';

END $$;

-- ── 5. Verify everything ─────────────────────────────────────
SELECT o.name AS org, r.name AS role, u.name AS user_name, u.email, u.phone
FROM users u
JOIN roles r ON r.id = u.role_id
JOIN orgs  o ON o.id = u.org_id
ORDER BY r.name, u.name;

SELECT case_number, complaint_title, status, priority, animal_type, incident_location
FROM complaint_cases
ORDER BY case_number;
  true
);

-- Resident / Member 1
INSERT INTO users (org_id, role_id, name, email, phone, channel, is_active)
VALUES (
  '<ORG_ID>',
  '<MEMBER_ROLE_ID>',
  'Amit Patel',
  'amit@example.com',
  NULL,
  'telegram',
  true
);

-- Add more members as needed — same pattern

-- ── 4. Verify ────────────────────────────────────────────────
SELECT o.name as org, r.name as role, u.name as user_name, u.email
FROM users u
JOIN roles r ON r.id = u.role_id
JOIN orgs o ON o.id = u.org_id
ORDER BY r.name, u.name;
