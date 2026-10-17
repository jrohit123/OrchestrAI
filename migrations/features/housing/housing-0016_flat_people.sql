-- Godrej only: who is in which flat, and how. One residents row = one person in one flat (a person with two flats has
-- two rows; a flat with four people has four rows). Name, phone and email stay only on users; a residents row points
-- at its person through user_id, so the two can never disagree.
--   relation     owner / co_owner / owner_family / tenant / tenant_family: how the person is linked to the flat.
--   is_primary   the primary member of the flat (first name on the share certificate; gets AGM notices). At most one
--                per flat, and never a tenant.
--   lives_here   whether the person lives in that flat now. Separate from status, which stays the account state
--                (active / suspended / inactive). The old status not_residing becomes lives_here = false.
-- residential_status (first_owner / second_owner / tenant / other: how the flat was bought) is kept as it was but is
-- no longer required; new rows leave it empty. The same person cannot be linked to the same flat twice.
-- The trigger that switches a person off when their home is suspended now only does so when none of their other
-- homes is still in use, and only a change of status (not a new row) switches someone back on.
-- The dashboard words for the new values go into orgs.settings.labels (an existing word is never overwritten).
-- Safe to run twice.

ALTER TABLE public.residents ADD COLUMN IF NOT EXISTS relation text;
ALTER TABLE public.residents ADD COLUMN IF NOT EXISTS is_primary boolean NOT NULL DEFAULT false;
ALTER TABLE public.residents ADD COLUMN IF NOT EXISTS lives_here boolean NOT NULL DEFAULT true;

UPDATE public.residents
   SET relation = CASE residential_status WHEN 'tenant' THEN 'tenant' WHEN 'other' THEN 'owner_family' ELSE 'owner' END
 WHERE relation IS NULL;

UPDATE public.residents SET lives_here = false, status = 'active' WHERE status = 'not_residing';

ALTER TABLE public.residents ALTER COLUMN relation SET DEFAULT 'tenant';
ALTER TABLE public.residents ALTER COLUMN relation SET NOT NULL;
ALTER TABLE public.residents DROP CONSTRAINT IF EXISTS residents_relation_check;
ALTER TABLE public.residents ADD CONSTRAINT residents_relation_check
    CHECK (relation IN ('owner', 'co_owner', 'owner_family', 'tenant', 'tenant_family'));
ALTER TABLE public.residents DROP CONSTRAINT IF EXISTS residents_tenant_not_primary;
ALTER TABLE public.residents ADD CONSTRAINT residents_tenant_not_primary
    CHECK (NOT (is_primary AND relation IN ('tenant', 'tenant_family')));

ALTER TABLE public.residents DROP CONSTRAINT IF EXISTS residents_status_check;
ALTER TABLE public.residents ADD CONSTRAINT residents_status_check
    CHECK (status IN ('active', 'suspended', 'inactive'));

ALTER TABLE public.residents ALTER COLUMN residential_status DROP NOT NULL;
ALTER TABLE public.residents ALTER COLUMN residential_status DROP DEFAULT;

UPDATE public.residents SET wing = NULLIF(upper(btrim(wing)), ''), flat_no = upper(btrim(flat_no))
 WHERE wing IS DISTINCT FROM NULLIF(upper(btrim(wing)), '') OR flat_no <> upper(btrim(flat_no));

CREATE UNIQUE INDEX IF NOT EXISTS residents_person_flat_key
    ON public.residents (org_id, user_id, COALESCE(wing, ''), flat_no) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS residents_one_primary_key
    ON public.residents (org_id, COALESCE(wing, ''), flat_no) WHERE is_primary;

COMMENT ON COLUMN public.residents.relation IS 'How the person is linked to the flat: owner, co_owner, owner_family, tenant or tenant_family.';
COMMENT ON COLUMN public.residents.is_primary IS 'The primary member of the flat (first name on the share certificate, gets AGM notices). At most one per flat.';
COMMENT ON COLUMN public.residents.lives_here IS 'True when the person lives in this flat now.';
COMMENT ON COLUMN public.residents.residential_status IS 'Old: how the flat was bought (first_owner, second_owner). Use relation for owner or tenant.';
COMMENT ON COLUMN public.residents.user_id IS 'The person (users.id). Name, phone and email are read from users.';

CREATE OR REPLACE FUNCTION public.sync_resident_status_to_user()
RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.user_id IS NULL THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status THEN
    RETURN NEW;
  END IF;
  IF NEW.status IN ('suspended', 'inactive') THEN
    IF NOT EXISTS (SELECT 1 FROM public.residents r
                    WHERE r.user_id = NEW.user_id AND r.id <> NEW.id
                      AND r.status NOT IN ('suspended', 'inactive')) THEN
      UPDATE public.users SET is_active = false WHERE id = NEW.user_id;
    END IF;
  ELSIF NEW.status = 'active' AND TG_OP = 'UPDATE' THEN
    UPDATE public.users SET is_active = true WHERE id = NEW.user_id;
  END IF;
  RETURN NEW;
END;
$$;

UPDATE public.orgs
   SET settings = jsonb_set(
           COALESCE(settings, '{}'::jsonb),
           '{labels}',
           '{"co_owner": "Co-owner", "owner_family": "Owner''s family", "tenant_family": "Tenant''s family"}'::jsonb
               || COALESCE(settings -> 'labels', '{}'::jsonb)
       )
 WHERE NOT (COALESCE(settings -> 'labels', '{}'::jsonb) ?& ARRAY['co_owner', 'owner_family', 'tenant_family']);
