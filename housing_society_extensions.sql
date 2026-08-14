-- ── Housing Society Extensions Schema & Seed Data ──
-- This file adds category/subcategory with TAT, residents table, staff designation,
-- and comprehensive seed data for testing housing society complaint management.
-- ────────────────────────────────────────────────────────

-- ── PART 1: SCHEMA ADDITIONS ────────────────────────────────────────────────

-- ── 1. Case categories (Primary Categories) ──
CREATE TABLE IF NOT EXISTS "case_categories" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "name" text NOT NULL,
  "created_at" timestamptz DEFAULT now(),
  CONSTRAINT "case_categories_org_name_key" UNIQUE("org_id","name")
);

-- ── 2. Case subcategories (Sub Categories with TAT/SLA) ──
CREATE TABLE IF NOT EXISTS "case_subcategories" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "category_id" uuid NOT NULL REFERENCES case_categories(id) ON DELETE CASCADE,
  "name" text NOT NULL,
  "tat_value" integer NOT NULL,
  "tat_unit" varchar(10) NOT NULL DEFAULT 'hours',
  "created_at" timestamptz DEFAULT now(),
  CONSTRAINT "case_subcategories_org_name_key" UNIQUE("org_id","category_id","name"),
  CONSTRAINT "case_subcategories_tat_unit_check" CHECK (tat_unit IN ('minutes','hours','days'))
);

-- ── 3. Extend complaint_cases with category/SLA fields ──
ALTER TABLE complaint_cases
  ADD COLUMN IF NOT EXISTS category_id uuid REFERENCES case_categories(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS subcategory_id uuid REFERENCES case_subcategories(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS due_date timestamptz,
  ADD COLUMN IF NOT EXISTS preferred_time text;

-- ── 4. Residents table (Wing/Flat/Owner metadata — separate from users) ──
CREATE TABLE IF NOT EXISTS "residents" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "user_id" uuid REFERENCES users(id) ON DELETE SET NULL,
  "wing" text,
  "flat_no" text NOT NULL,
  "gender" varchar(10),
  "residential_status" varchar(20) NOT NULL DEFAULT 'tenant',
  "brokers_name" text,
  "first_owner_name" text,
  "first_owner_mobile" text,
  "registration_date" date DEFAULT CURRENT_DATE,
  "status" varchar(20) NOT NULL DEFAULT 'active',
  "approved_by" uuid REFERENCES users(id) ON DELETE SET NULL,
  "suspension_date" date,
  "created_at" timestamptz DEFAULT now(),
  CONSTRAINT "residents_residential_status_check"
    CHECK (residential_status IN ('tenant','first_owner','second_owner','other')),
  CONSTRAINT "residents_status_check"
    CHECK (status IN ('active','suspended','inactive','not_residing'))
);

-- ── 5. Staff designation on users (Security Guard, Society Manager, etc.) ──
ALTER TABLE users ADD COLUMN IF NOT EXISTS designation text;

-- ── 6. Indexes ──
CREATE INDEX IF NOT EXISTS idx_subcategories_category ON case_subcategories(category_id);
CREATE INDEX IF NOT EXISTS idx_cases_category ON complaint_cases(category_id);
CREATE INDEX IF NOT EXISTS idx_cases_subcategory ON complaint_cases(subcategory_id);
CREATE INDEX IF NOT EXISTS idx_residents_org ON residents(org_id);
CREATE INDEX IF NOT EXISTS idx_residents_user ON residents(user_id);
CREATE INDEX IF NOT EXISTS idx_residents_wing_flat ON residents(org_id, wing, flat_no);

-- ── PART 2: SEED DATA ────────────────────────────────────────────────────────

DO $$
DECLARE
  v_org_id          uuid;
  v_admin_role      uuid;
  v_committee_role  uuid;
  v_member_role     uuid;
  v_staff_role      uuid;
  v_cat_cleanliness uuid;
  v_cat_maintenance uuid;
  v_cat_accounts    uuid;
  v_cat_misc        uuid;
  v_sub_waste       uuid;
  v_sub_spill       uuid;
  v_sub_structure   uuid;
  v_sub_wear        uuid;
  v_sub_repair      uuid;
  v_sub_amc         uuid;
  v_sub_dues        uuid;
  v_sub_share       uuid;
BEGIN
  -- Get org and existing roles
  SELECT id INTO v_org_id FROM orgs WHERE slug = 'godrej-emerald';

  IF v_org_id IS NULL THEN
    RAISE NOTICE 'Org godrej-emerald not found, skipping seed data';
    RETURN;
  END IF;

  SELECT id INTO v_admin_role     FROM roles WHERE org_id = v_org_id AND name = 'admin';
  SELECT id INTO v_committee_role FROM roles WHERE org_id = v_org_id AND name = 'committee';
  SELECT id INTO v_member_role    FROM roles WHERE org_id = v_org_id AND name = 'member';

  IF v_admin_role IS NULL OR v_committee_role IS NULL OR v_member_role IS NULL THEN
    RAISE NOTICE 'Required roles not found, skipping seed data';
    RETURN;
  END IF;

  -- ── New role: staff (guards, supervisors, managers) ──
  INSERT INTO roles (org_id, name, permissions, readable_tables)
  VALUES (
    v_org_id, 'staff',
    ARRAY['general_read','add_case_comment','view_my_cases'],
    ARRAY['complaint_cases','case_comments']
  ) ON CONFLICT (org_id, name) DO NOTHING
  RETURNING id INTO v_staff_role;

  -- Get staff role ID if it already existed
  IF v_staff_role IS NULL THEN
    SELECT id INTO v_staff_role FROM roles WHERE org_id = v_org_id AND name = 'staff';
  END IF;

  -- ── More members across different wings (for realistic testing) ──
  INSERT INTO users (org_id, role_id, name, email, phone, channel, is_active)
  VALUES
    (v_org_id, v_member_role, 'Farid Shaikh',   'farid.shaikh@example.com',   NULL, 'telegram', true),
    (v_org_id, v_member_role, 'Neha Kulkarni',  'neha.kulkarni@example.com',  NULL, 'telegram', true),
    (v_org_id, v_member_role, 'Vikram Rao',     'vikram.rao@example.com',     NULL, 'telegram', true),
    (v_org_id, v_member_role, 'Anjali Nair',    'anjali.nair@example.com',    NULL, 'telegram', true)
  ON CONFLICT (org_id, email) DO NOTHING;

  -- ── Staff (Security Guard, Society Manager) ──
  INSERT INTO users (org_id, role_id, name, email, phone, channel, is_active, designation)
  VALUES
    (v_org_id, v_staff_role, 'Ramesh Kumar', 'ramesh.security@example.com', NULL, 'telegram', true, 'Security Guard'),
    (v_org_id, v_staff_role, 'Suresh Patil', 'suresh.manager@example.com',  NULL, 'telegram', true, 'Society Manager')
  ON CONFLICT (org_id, email) DO NOTHING;

  -- ── Categories ──
  INSERT INTO case_categories (org_id, name) VALUES (v_org_id, 'Cleanliness')
  ON CONFLICT (org_id, name) DO NOTHING
  RETURNING id INTO v_cat_cleanliness;

  IF v_cat_cleanliness IS NULL THEN
    SELECT id INTO v_cat_cleanliness FROM case_categories WHERE org_id = v_org_id AND name = 'Cleanliness';
  END IF;

  INSERT INTO case_categories (org_id, name) VALUES (v_org_id, 'Maintenance')
  ON CONFLICT (org_id, name) DO NOTHING
  RETURNING id INTO v_cat_maintenance;

  IF v_cat_maintenance IS NULL THEN
    SELECT id INTO v_cat_maintenance FROM case_categories WHERE org_id = v_org_id AND name = 'Maintenance';
  END IF;

  INSERT INTO case_categories (org_id, name) VALUES (v_org_id, 'Accounts')
  ON CONFLICT (org_id, name) DO NOTHING
  RETURNING id INTO v_cat_accounts;

  IF v_cat_accounts IS NULL THEN
    SELECT id INTO v_cat_accounts FROM case_categories WHERE org_id = v_org_id AND name = 'Accounts';
  END IF;

  INSERT INTO case_categories (org_id, name) VALUES (v_org_id, 'Misc')
  ON CONFLICT (org_id, name) DO NOTHING
  RETURNING id INTO v_cat_misc;

  IF v_cat_misc IS NULL THEN
    SELECT id INTO v_cat_misc FROM case_categories WHERE org_id = v_org_id AND name = 'Misc';
  END IF;

  -- ── Subcategories with TAT ──
  INSERT INTO case_subcategories (org_id, category_id, name, tat_value, tat_unit)
  VALUES (v_org_id, v_cat_cleanliness, 'Waste Collection', 6, 'hours')
  ON CONFLICT (org_id, category_id, name) DO NOTHING
  RETURNING id INTO v_sub_waste;

  IF v_sub_waste IS NULL THEN
    SELECT id INTO v_sub_waste FROM case_subcategories WHERE org_id = v_org_id AND category_id = v_cat_cleanliness AND name = 'Waste Collection';
  END IF;

  INSERT INTO case_subcategories (org_id, category_id, name, tat_value, tat_unit)
  VALUES (v_org_id, v_cat_cleanliness, 'Liquid Spill', 30, 'minutes')
  ON CONFLICT (org_id, category_id, name) DO NOTHING
  RETURNING id INTO v_sub_spill;

  IF v_sub_spill IS NULL THEN
    SELECT id INTO v_sub_spill FROM case_subcategories WHERE org_id = v_org_id AND category_id = v_cat_cleanliness AND name = 'Liquid Spill';
  END IF;

  INSERT INTO case_subcategories (org_id, category_id, name, tat_value, tat_unit)
  VALUES (v_org_id, v_cat_cleanliness, 'Structure Cleaning', 14, 'days')
  ON CONFLICT (org_id, category_id, name) DO NOTHING
  RETURNING id INTO v_sub_structure;

  IF v_sub_structure IS NULL THEN
    SELECT id INTO v_sub_structure FROM case_subcategories WHERE org_id = v_org_id AND category_id = v_cat_cleanliness AND name = 'Structure Cleaning';
  END IF;

  INSERT INTO case_subcategories (org_id, category_id, name, tat_value, tat_unit)
  VALUES (v_org_id, v_cat_maintenance, 'Wear-n-Tear', 3, 'days')
  ON CONFLICT (org_id, category_id, name) DO NOTHING
  RETURNING id INTO v_sub_wear;

  IF v_sub_wear IS NULL THEN
    SELECT id INTO v_sub_wear FROM case_subcategories WHERE org_id = v_org_id AND category_id = v_cat_maintenance AND name = 'Wear-n-Tear';
  END IF;

  INSERT INTO case_subcategories (org_id, category_id, name, tat_value, tat_unit)
  VALUES (v_org_id, v_cat_maintenance, 'Repair', 2, 'days')
  ON CONFLICT (org_id, category_id, name) DO NOTHING
  RETURNING id INTO v_sub_repair;

  IF v_sub_repair IS NULL THEN
    SELECT id INTO v_sub_repair FROM case_subcategories WHERE org_id = v_org_id AND category_id = v_cat_maintenance AND name = 'Repair';
  END IF;

  INSERT INTO case_subcategories (org_id, category_id, name, tat_value, tat_unit)
  VALUES (v_org_id, v_cat_maintenance, 'AMC', 7, 'days')
  ON CONFLICT (org_id, category_id, name) DO NOTHING
  RETURNING id INTO v_sub_amc;

  IF v_sub_amc IS NULL THEN
    SELECT id INTO v_sub_amc FROM case_subcategories WHERE org_id = v_org_id AND category_id = v_cat_maintenance AND name = 'AMC';
  END IF;

  INSERT INTO case_subcategories (org_id, category_id, name, tat_value, tat_unit)
  VALUES (v_org_id, v_cat_accounts, 'Dues', 5, 'days')
  ON CONFLICT (org_id, category_id, name) DO NOTHING
  RETURNING id INTO v_sub_dues;

  IF v_sub_dues IS NULL THEN
    SELECT id INTO v_sub_dues FROM case_subcategories WHERE org_id = v_org_id AND category_id = v_cat_accounts AND name = 'Dues';
  END IF;

  INSERT INTO case_subcategories (org_id, category_id, name, tat_value, tat_unit)
  VALUES (v_org_id, v_cat_accounts, 'Share Certificate', 10, 'days')
  ON CONFLICT (org_id, category_id, name) DO NOTHING
  RETURNING id INTO v_sub_share;

  IF v_sub_share IS NULL THEN
    SELECT id INTO v_sub_share FROM case_subcategories WHERE org_id = v_org_id AND category_id = v_cat_accounts AND name = 'Share Certificate';
  END IF;

  -- ── Residents (Wing/Flat data, one linked to existing admin user) ──
  INSERT INTO residents (org_id, user_id, wing, flat_no, residential_status, brokers_name,
    first_owner_name, first_owner_mobile, status)
  VALUES
    (v_org_id, (SELECT id FROM users WHERE email = 'kartik@orchestrai.com' AND org_id = v_org_id),
     '1', '101', 'tenant', 'Farid Shaikh', 'R B', '9820098201', 'active'),
    (v_org_id, NULL, '1', '101', 'first_owner', 'Munna Joshi', 'R B', '9820098201', 'not_residing'),
    (v_org_id, (SELECT id FROM users WHERE email = 'amit.patel@example.com' AND org_id = v_org_id),
     '2', '204', 'first_owner', NULL, 'Amit Patel', NULL, 'active'),
    (v_org_id, (SELECT id FROM users WHERE email = 'sunita.mehta@example.com' AND org_id = v_org_id),
     '3', '305', 'tenant', 'Munna Joshi', 'Ravi Mehta', NULL, 'active'),
    (v_org_id, (SELECT id FROM users WHERE email = 'vikram.rao@example.com' AND org_id = v_org_id),
     '4', '412', 'tenant', NULL, 'Vikram Rao', NULL, 'suspended')
  ON CONFLICT DO NOTHING;

  -- ── More complaint cases across statuses/priorities/categories (with SLA due_date) ──
  INSERT INTO complaint_cases (org_id, case_number, complaint_title, complaint_description,
    status, priority, category_id, subcategory_id, incident_location, due_date,
    complainant_id, assigned_to_id)
  VALUES
    (v_org_id, 'CS-26-08-00003', 'Garbage not collected Wing 3',
     'Waste bins overflowing near Wing 3 for 2 days.', 'reported', 'high',
     v_cat_cleanliness, v_sub_waste, 'Wing 3, Flat 305',
     now() + interval '6 hours',
     (SELECT id FROM users WHERE email = 'sunita.mehta@example.com' AND org_id = v_org_id),
     (SELECT id FROM users WHERE email = 'ramesh.security@example.com' AND org_id = v_org_id)),

    (v_org_id, 'CS-26-08-00004', 'Water leakage from ceiling',
     'Leak in flat 204 ceiling, suspect pipe issue from floor above.', 'action_taken', 'critical',
     v_cat_maintenance, v_sub_repair, 'Wing 2, Flat 204',
     now() - interval '1 day',  -- deliberately overdue, for testing SLA-breach queries
     (SELECT id FROM users WHERE email = 'amit.patel@example.com' AND org_id = v_org_id),
     (SELECT id FROM users WHERE email = 'suresh.manager@example.com' AND org_id = v_org_id)),

    (v_org_id, 'CS-26-08-00005', 'Annual lift AMC due',
     'Lift AMC renewal pending for Tower 1.', 'under_review', 'medium',
     v_cat_maintenance, v_sub_amc, 'Wing 1 — Lift',
     now() + interval '7 days',
     (SELECT id FROM users WHERE email = 'kartik@orchestrai.com' AND org_id = v_org_id),
     (SELECT id FROM users WHERE email = 'rahul@godrejemerald.com' AND org_id = v_org_id)),

    (v_org_id, 'CS-26-08-00006', 'Maintenance dues clarification',
     'Resident disputing maintenance dues amount for Q2.', 'reported', 'low',
     v_cat_accounts, v_sub_dues, 'Wing 4, Flat 412',
     now() + interval '5 days',
     (SELECT id FROM users WHERE email = 'vikram.rao@example.com' AND org_id = v_org_id),
     NULL),  -- unassigned, for testing assign_case flow

    (v_org_id, 'CS-26-08-00007', 'Lift stuck between floors — resolved',
     'Lift T1 stuck for 20 mins, technician called, resolved same day.', 'closed', 'critical',
     v_cat_maintenance, v_sub_repair, 'Tower 1 Lift',
     now() - interval '3 days',
     (SELECT id FROM users WHERE email = 'neha.kulkarni@example.com' AND org_id = v_org_id),
     (SELECT id FROM users WHERE email = 'suresh.manager@example.com' AND org_id = v_org_id))
  ON CONFLICT (org_id, case_number) DO NOTHING;

  -- Backfill due_date on the original two seeded cases too (optional)
  UPDATE complaint_cases
  SET category_id = v_cat_cleanliness,
      subcategory_id = v_sub_waste,
      due_date = created_at + interval '6 hours'
  WHERE org_id = v_org_id AND case_number = 'CS-26-08-00001';

  -- Close CS-26-08-00007 properly (set closed_at, since we backdated it as already closed)
  UPDATE complaint_cases
  SET closed_at = created_at + interval '1 day'
  WHERE case_number = 'CS-26-08-00007';

  RAISE NOTICE 'Housing society extensions seed data inserted successfully';
END $$;

-- ── SUMMARY OF CHANGES ──────────────────────────────────────────────────────
-- New Tables:
--   - case_categories: Primary complaint categories
--   - case_subcategories: Subcategories with TAT/SLA settings
--   - residents: Wing/Flat/Owner metadata (separate from users)
--
-- Modified Tables:
--   - complaint_cases: Added category_id, subcategory_id, due_date, preferred_time
--   - users: Added designation field
--
-- New Indexes:
--   - idx_subcategories_category, idx_cases_category, idx_cases_subcategory
--   - idx_residents_org, idx_residents_user, idx_residents_wing_flat
--
-- New Role:
--   - staff: For guards, supervisors, managers with limited permissions
--
-- Seed Data Added:
--   - 4 new member users across different wings
--   - 2 staff users (Security Guard, Society Manager)
--   - 4 categories (Cleanliness, Maintenance, Accounts, Misc)
--   - 8 subcategories with varied TAT units (minutes/hours/days)
--   - 5 residents with mixed status (including one suspended)
--   - 5 new complaint cases spanning all statuses, priorities, and categories
--   - One deliberately overdue case for SLA testing
--   - One unassigned case for assignment flow testing
--   - One already closed case for historical testing
