-- core-0005 (optional): make Baanganga's one-draft-per-person rule the same as Godrej's.
--
-- The app saves a draft with:  ON CONFLICT (org_id, user_id) WHERE stage NOT IN ('done','cancelled')
-- That is written for Godrej's rule, which only counts OPEN drafts. Baanganga's index of the same
-- name counts every draft, so a new draft reuses the old closed row and carries its old answers
-- into the new draft (tried on a practice copy: the second draft kept the first one's answers).
--
-- This replaces that one index, inside one transaction, so there is never a moment without the
-- protection. The new rule is looser, so it cannot fail on existing rows. Safe to run twice:
-- a database that already has the open-drafts-only version is left alone.

DO $$
DECLARE
    counts_every_draft boolean;
BEGIN
    -- true: the old "every draft" index; false: already the open-drafts-only one;
    -- null: no such index at all.
    SELECT i.indpred IS NULL INTO counts_every_draft
    FROM pg_index i
    WHERE i.indexrelid = to_regclass('public.one_active_draft_per_user');

    IF counts_every_draft IS TRUE THEN
        DROP INDEX public.one_active_draft_per_user;
    END IF;
    IF counts_every_draft IS NOT FALSE THEN
        CREATE UNIQUE INDEX one_active_draft_per_user
            ON public.user_drafts (org_id, user_id)
            WHERE stage NOT IN ('done', 'cancelled');
    END IF;
END $$;
