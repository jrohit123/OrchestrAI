-- ============================================================
-- GODREJ EMERALD — Test Data Seed Plan
-- Purpose: Exercise read/report/PDF paths with realistic variety
-- Scope: Adds test data to existing tables, does not modify schema
-- 
-- IMPORTANT: Run this AFTER godrej_schema.sql and godrej_seed.sql
-- ============================================================

-- NOTE: All UUIDs below are from the actual database dump
-- org_id throughout: 793eead0-31b2-4538-b9b3-1885f9e94604

-- ============================================================
-- 2.1 case_comments — currently completely empty
-- Purpose: Test comment rendering in response templates
-- ============================================================

-- Committee comment on the cat colony case (under_review)
INSERT INTO case_comments (org_id, case_id, user_id, comment) VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604',
 '2570025c-25d9-43d0-97cb-1a4473411a20',   -- CS-26-08-00002
 '00598937-ddf7-40a7-9481-8c86e064bdf5',   -- Priya Desai (committee)
 'Spoke with pest control vendor, visit scheduled for this Friday to relocate the colony humanely.');

-- Staff comment on water leakage (action_taken, critical)
INSERT INTO case_comments (org_id, case_id, user_id, comment) VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604',
 'ad4ac910-6f3d-4f49-962f-e050f76c4256',   -- CS-26-08-00004
 '882d106a-86ff-44c1-be85-82feb8f52054',   -- Suresh Patil (society manager)
 'Plumber confirmed the leak source is a joint failure in flat 304 above. Repair in progress, ETA tomorrow.');

INSERT INTO case_comments (org_id, case_id, user_id, comment) VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604',
 'ad4ac910-6f3d-4f49-962f-e050f76c4256',
 '555c7585-d900-4f8d-9b82-0a29a6ee5ca3',   -- Amit Patel (complainant, member)
 'Thank you, please also check if my ceiling paint needs redoing after this.');

-- Multi-comment thread on the resolved lift case (closed) — tests comment_count on a closed case too
INSERT INTO case_comments (org_id, case_id, user_id, comment) VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604',
 '7c90126b-102f-43ad-a157-c249f01c173a',   -- CS-26-08-00007
 '882d106a-86ff-44c1-be85-82feb8f52054',
 'Technician dispatched immediately, lift restarted manually within 15 minutes.');

INSERT INTO case_comments (org_id, case_id, user_id, comment) VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604',
 '7c90126b-102f-43ad-a157-c249f01c173a',
 '24330df7-b936-4938-8d0f-abb94cc1786d',   -- Neha Kulkarni (complainant)
 'Confirmed working fine since, closing on my end. Thanks for the quick response!');

-- Committee note on the dues dispute (low priority, reported)
INSERT INTO case_comments (org_id, case_id, user_id, comment) VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604',
 '695e8398-a38e-4849-92aa-a159e972c18f',   -- CS-26-08-00006
 '5cac8bbd-3d13-4d46-9851-11ade6635514',   -- Rahul Sharma (committee)
 'Requested accounts team to share the itemized Q2 breakup with the resident.');

-- ============================================================
-- 2.2 case_evidence — currently completely empty
-- Purpose: Test FK relationships and evidence-count queries
-- ============================================================

INSERT INTO case_evidence (org_id, case_id, evidence_type, file_url, description, uploaded_by) VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604',
 '15cf1a0b-f553-46fa-a03e-b526e7f70d25',   -- CS-26-08-00001, stray dog
 'photo', 'https://example-storage/godrej/cs00001-photo1.jpg',
 'Dog near Wing A gate, taken from lobby CCTV still',
 '555c7585-d900-4f8d-9b82-0a29a6ee5ca3');

INSERT INTO case_evidence (org_id, case_id, evidence_type, file_url, description, uploaded_by) VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604',
 'ad4ac910-6f3d-4f49-962f-e050f76c4256',   -- CS-26-08-00004, water leak
 'photo', 'https://example-storage/godrej/cs00004-ceiling.jpg',
 'Water stain and visible drip on flat 204 ceiling',
 '555c7585-d900-4f8d-9b82-0a29a6ee5ca3');

INSERT INTO case_evidence (org_id, case_id, evidence_type, file_url, description, uploaded_by) VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604',
 '953bf799-a64a-466e-b319-6e9f18ee546c',   -- CS-26-08-00003, garbage
 'photo', 'https://example-storage/godrej/cs00003-bins.jpg',
 'Overflowing bins near Wing 3 entrance',
 '3d9acdce-e064-43e3-b8fa-9f6e04907d87');

-- ============================================================
-- 2.3 complaint_cases — add variety, including overdue cases
-- Purpose: Test SLA/overdue query paths with real hits
-- ============================================================

-- Overdue, unassigned, high priority — tests SLA breach query with a real hit
INSERT INTO complaint_cases
  (org_id, case_number, complainant_id, complaint_title, complaint_description,
   status, priority, incident_location, category_id, subcategory_id, due_date, created_at)
VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604', 'CS-26-08-00008',
 'a5acced1-11cf-4723-92f0-7f4a6e66860c',  -- Farid Shaikh
 'AMC renewal overdue for Wing 2 lift',
 'Lift AMC lapsed two weeks ago, no maintenance visit since.',
 'reported', 'critical', 'Wing 2 — Lift',
 '4aa40438-5d36-4e64-8de1-f13152a021e9',   -- Maintenance
 '657692d2-9225-4688-a8cf-eb89d592468c',   -- AMC subcategory, 7-day TAT
 '2026-08-10 09:00:00+00',                  -- clearly overdue vs today (17 Aug)
 '2026-08-08 09:00:00+00');

-- Misc category case, open, medium priority
INSERT INTO complaint_cases
  (org_id, case_number, complainant_id, complaint_title, complaint_description,
   status, priority, incident_location, category_id, due_date, created_at)
VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604', 'CS-26-08-00009',
 '66057167-3d3c-4904-976d-4e53880b61e9',  -- Vikram Rao
 'Request for visitor parking guidelines',
 'Asking committee to clarify visitor parking rules for Wing 4.',
 'reported', 'low', 'Wing 4 — Parking',
 '456abfa8-7223-4b4e-9fdf-68eaa474105b',   -- Misc
 NULL, '2026-08-16 09:00:00+00');

-- Assigned, in-progress, critical, tests "my assigned cases" for committee
INSERT INTO complaint_cases
  (org_id, case_number, complainant_id, complaint_title, complaint_description,
   status, priority, incident_location, assigned_to_id, category_id, subcategory_id, due_date, created_at)
VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604', 'CS-26-08-00010',
 'a0c8806a-a2e6-4e15-ab0f-3233c5593148',  -- Anjali Nair
 'Fire extinguisher missing from Wing 1 corridor',
 'Extinguisher mount is empty on 3rd floor Wing 1, flagged during fire drill.',
 'under_review', 'critical', 'Wing 1, 3rd Floor',
 '00598937-ddf7-40a7-9481-8c86e064bdf5',   -- Priya Desai (committee)
 '4aa40438-5d36-4e64-8de1-f13152a021e9',   -- Maintenance
 '9ba3ea56-abb4-4476-9564-e96b18118eb7',   -- Repair, 2-day TAT
 '2026-08-19 09:00:00+00', '2026-08-17 09:00:00+00');

-- ============================================================
-- 2.4 residents — add variety of residential statuses
-- Purpose: Test sync_resident_status_to_user() trigger
-- ============================================================

INSERT INTO residents
  (org_id, user_id, wing, flat_no, residential_status, first_owner_name, registration_date, status)
VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604', 'a0c8806a-a2e6-4e15-ab0f-3233c5593148',
 '1', '110', 'tenant', 'Deepak Nair', '2026-08-15', 'active');

INSERT INTO residents
  (org_id, user_id, wing, flat_no, residential_status, first_owner_name, registration_date, status)
VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604', '24330df7-b936-4938-8d0f-abb94cc1786d',
 '2', '210', 'second_owner', 'Ravi Kulkarni', '2026-08-15', 'active');

-- ⚠️ WARNING: This will trip trg_sync_resident_status and set users.is_active = false for Farid Shaikh
-- His account will be locked out of chat until residents.status is set back to 'active'
INSERT INTO residents
  (org_id, user_id, wing, flat_no, residential_status, first_owner_name, registration_date, status, suspension_date)
VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604', 'a5acced1-11cf-4723-92f0-7f4a6e66860c',
 '1', '101', 'tenant', 'R B', '2026-08-15', 'suspended', '2026-08-17');

-- ============================================================
-- 2.5 case_subcategories — fill the gap in Misc category
-- Purpose: Enable SLA tracking for Misc category complaints
-- ============================================================

-- Only run these if Misc SHOULD have SLA-tracked subcategories
INSERT INTO case_subcategories (org_id, category_id, name, tat_value, tat_unit) VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604', '456abfa8-7223-4b4e-9fdf-68eaa474105b', 'General Inquiry', 2, 'days');

INSERT INTO case_subcategories (org_id, category_id, name, tat_value, tat_unit) VALUES
('793eead0-31b2-4538-b9b3-1885f9e94604', '456abfa8-7223-4b4e-9fdf-68eaa474105b', 'Policy Clarification', 3, 'days');

-- ============================================================
-- Verification Queries
-- Run these to confirm the data was inserted correctly
-- ============================================================

-- Verify case_comments
SELECT cc.id, cc.comment, u.name as commenter, c.case_number 
FROM case_comments cc
JOIN users u ON cc.user_id = u.id
JOIN complaint_cases c ON cc.case_id = c.id
ORDER BY c.case_number, cc.created_at;

-- Verify case_evidence
SELECT ce.id, ce.evidence_type, ce.description, c.case_number 
FROM case_evidence ce
JOIN complaint_cases c ON ce.case_id = c.id
ORDER BY c.case_number;

-- Verify new complaint cases
SELECT case_number, complaint_title, status, priority, due_date, created_at
FROM complaint_cases
WHERE case_number IN ('CS-26-08-00008', 'CS-26-08-00009', 'CS-26-08-00010')
ORDER BY case_number;

-- Verify residents with different statuses
SELECT r.wing, r.flat_no, r.residential_status, r.status, u.name, u.is_active
FROM residents r
JOIN users u ON r.user_id = u.id
WHERE r.wing IN ('1', '2')
ORDER BY r.wing, r.flat_no;

-- Verify Misc subcategories
SELECT sc.name, sc.tat_value, sc.tat_unit, c.name as category
FROM case_subcategories sc
JOIN case_categories c ON sc.category_id = c.id
WHERE c.name = 'Misc'
ORDER BY sc.name;