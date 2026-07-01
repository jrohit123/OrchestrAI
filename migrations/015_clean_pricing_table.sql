-- Migration 015: Clean pricing table — remove quotation-storage columns
--
-- The pricing table was being abused as both:
--   (a) a metal rate card (rate_per_gram, making_charge_pct per metal_type) — KEEP
--   (b) a quotation record store (quotation_number, weight_grams, subtotal, etc.) — REMOVE
--
-- Quotation records are now stored exclusively in the quotations table,
-- created by action_executor._create_quotation via the draft/confirm flow.
--
-- This migration removes the quotation-specific columns from pricing and
-- drops any quotation rows that were inserted there previously.

-- Step 1: Delete quotation rows from pricing (those have quotation_number set)
DELETE FROM pricing WHERE quotation_number IS NOT NULL;

-- Step 2: Drop the quotation-specific columns
ALTER TABLE pricing
    DROP COLUMN IF EXISTS quotation_number,
    DROP COLUMN IF EXISTS weight_grams,
    DROP COLUMN IF EXISTS making_charges,
    DROP COLUMN IF EXISTS subtotal,
    DROP COLUMN IF EXISTS gst_pct,
    DROP COLUMN IF EXISTS gst_amount,
    DROP COLUMN IF EXISTS total_amount,
    DROP COLUMN IF EXISTS status,
    DROP COLUMN IF EXISTS valid_until,
    DROP COLUMN IF EXISTS created_by;

-- After this migration, pricing table has only:
--   id, org_id, metal_type, rate_per_gram, making_charge_pct, updated_by, updated_at
-- which is its correct purpose: org-level metal rate card.
