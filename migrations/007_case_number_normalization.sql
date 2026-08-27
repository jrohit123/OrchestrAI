-- ═══════════════════════════════════════════════════════════════════════════
-- MIGRATION 007 — normalised case-number lookup
--
-- Pairs with the `normalize: "identifier"` option added to _op_resolve_entity
-- in step_interpreter.py. Case numbers are typed inconsistently by users
-- ("Cs260817", "CS 26 08 17", "cs-26-08-17", "case 17") and the old ILIKE
-- lookup only matched a literal substring, so most of those failed with
-- "case does not exist" even though the case was present.
--
-- case_number_norm is a STORED generated column so it's indexable and
-- requires no application-side backfill — it's computed for every existing
-- row the moment the column is added.
-- ═══════════════════════════════════════════════════════════════════════════
BEGIN;

ALTER TABLE cases
  ADD COLUMN IF NOT EXISTS case_number_norm text
  GENERATED ALWAYS AS (regexp_replace(upper(case_number), '[^A-Z0-9]', '', 'g')) STORED;

CREATE INDEX IF NOT EXISTS idx_cases_number_norm
    ON cases (org_id, case_number_norm);

-- Trigram index to support the tier-3 "bare digits" suffix match
-- (`normalize: "identifier"` tier 3 in step_interpreter.py) efficiently.
-- pg_trgm is already installed in this database (see CREATE EXTENSION at
-- the top of the schema dump).
CREATE INDEX IF NOT EXISTS idx_cases_number_norm_trgm
    ON cases USING gin (case_number_norm gin_trgm_ops);

COMMIT;
