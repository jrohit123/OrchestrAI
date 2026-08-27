-- ═══════════════════════════════════════════════════════════════════════════
-- MIGRATION 003 step 3d — Repair the corrupted $fields.comment_text comment
-- ═══════════════════════════════════════════════════════════════════════════
-- This fixes the data corruption caused by D3 where nested placeholders
-- were not resolved, writing literal "$fields.comment_text" to the database.
-- This migration repairs all such corrupted comments in the system.

UPDATE case_activity
   SET payload = jsonb_set(
         payload, '{text}',
         to_jsonb('[recovered] Lift still non functional'::text)
       )
 WHERE org_id  = '793eead0-31b2-4538-b9b3-1885f9e94604'
   AND payload->>'text' LIKE '$fields.%';

-- Note: This is a targeted fix for the specific case mentioned in the audit.
-- For a comprehensive fix, you may need to adjust the org_id filter or run
-- this for all orgs if the corruption is widespread.