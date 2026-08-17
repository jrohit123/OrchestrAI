-- ============================================================
-- APPROVAL GATE FIX — Schema Migration
-- Purpose: Remove hardcoded owner role dependency in approval gate
-- 
-- This adds an is_approver boolean column to the roles table to make
-- the approval gate work for any organization's role structure.
-- ============================================================

-- Add is_approver column to roles table
ALTER TABLE roles ADD COLUMN IF NOT EXISTS is_approver boolean DEFAULT false NOT NULL;

-- Set existing Baanganga owner role as approver (based on the hardcoded UUID)
-- This assumes the owner role exists - you may need to adjust the condition
UPDATE roles 
SET is_approver = true 
WHERE name = 'owner' OR id = '22220000-0000-0000-0000-000000000001';

-- Set Godrej Emerald admin role as approver
UPDATE roles 
SET is_approver = true 
WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604' AND name = 'admin';

-- Verification query
SELECT r.id, r.name, r.is_approver, o.name as org_name
FROM roles r
JOIN orgs o ON r.org_id = o.id
WHERE r.is_approver = true
ORDER BY o.name, r.name;