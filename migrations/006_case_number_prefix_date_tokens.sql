-- ═══════════════════════════════════════════════════════════════════════════
-- MIGRATION 006 — self-dating, zero-padded case numbers
--
-- Pairs with the step_interpreter.py change that now expands {YYYY}/{YY}/
-- {MM}/{DD} tokens in a sequence prefix and honours a "pad" width. Before
-- this, register_complaint's prefix was a literal "CS-26-08-" frozen at
-- authoring time — every case created after August 2026 would still say
-- "08", and case numbers were unpadded (CS-26-08-14 next to CS-26-08-00013).
--
-- This migration only changes how FUTURE case numbers are generated. It
-- does NOT rewrite existing case_number values — residents and committee
-- members already have the old numbers in their WhatsApp/Telegram history.
-- Migration 007 (case_number_norm) is what makes both formats resolvable.
--
-- Run against: Godrej Emerald (org_id 793eead0-31b2-4538-b9b3-1885f9e94604)
-- ═══════════════════════════════════════════════════════════════════════════
BEGIN;

-- Locate the db.insert_row step inside register_complaint's steps[] and
-- replace only its "sequence" object. Written with jsonb path matching
-- instead of a hardcoded array index, so it doesn't silently corrupt the
-- workflow if the steps array is ever reordered.
WITH target AS (
    SELECT id, steps
      FROM workflows
     WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604'
       AND intent_key = 'register_complaint'
),
idx AS (
    SELECT id, (elem.ordinality - 1) AS step_index
      FROM target, jsonb_array_elements(steps) WITH ORDINALITY AS elem(value, ordinality)
     WHERE elem.value->>'op' = 'db.insert_row'
       AND elem.value->'params'->>'table' = 'cases'
)
UPDATE workflows w
   SET steps = jsonb_set(
         w.steps,
         array[idx.step_index::text, 'params', 'sequence'],
         '{"field": "case_number", "prefix": "CS-{YY}-{MM}-", "start": 1, "pad": 5}'::jsonb
       )
  FROM idx
 WHERE w.id = idx.id;

-- Verify exactly one workflow step was updated before committing manually
-- if running this by hand:
--   SELECT steps->0->'params'->'sequence' FROM workflows
--    WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604'
--      AND intent_key = 'register_complaint';

COMMIT;
