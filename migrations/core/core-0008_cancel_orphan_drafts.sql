-- core-0008: close drafts that can never be finished because their workflow was removed.
-- Nothing is deleted.
--
-- 1. A person's OPEN draft (a half-finished task) whose workflow no longer exists is marked
--    'cancelled', the same way the app cancels a draft (stage, updated_at, expires_at).
--    Finished or cancelled drafts, and drafts whose workflow still exists (even switched
--    off), are left alone.
-- 2. A dashboard builder draft marked 'published' that lost its workflow (the link is
--    cleared when a workflow is deleted) becomes 'abandoned', which hides it from the
--    "Continue a draft" list, the way an earlier clean-up did.
--
-- Safe to run twice: the second time nothing matches. When this was written no row matched
-- in either database (checked on practice copies), so today it changes nothing; it only
-- matters if such drafts appear before the real run.

UPDATE public.user_drafts d
SET stage = 'cancelled', updated_at = now(), expires_at = now()
WHERE d.stage NOT IN ('done', 'cancelled')
  AND NOT EXISTS (SELECT 1 FROM public.workflows w
                  WHERE w.org_id = d.org_id AND w.intent_key = d.intent_key);

UPDATE public.workflow_drafts
SET status = 'abandoned', updated_at = now()
WHERE status = 'published' AND published_workflow_id IS NULL;
