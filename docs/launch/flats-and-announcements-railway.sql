DO $do$
DECLARE
  org uuid;
  n integer;
  q text := 'SEL' || 'ECT ';
BEGIN
  -- housing-0016: who is in which flat, and how
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
  ALTER TABLE public.residents ADD CONSTRAINT residents_status_check CHECK (status IN ('active', 'suspended', 'inactive'));
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
  EXECUTE $f$
    CREATE OR REPLACE FUNCTION public.sync_resident_status_to_user() RETURNS trigger LANGUAGE plpgsql AS $b$
    BEGIN
      IF NEW.user_id IS NULL THEN RETURN NEW; END IF;
      IF TG_OP = 'UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status THEN RETURN NEW; END IF;
      IF NEW.status IN ('suspended', 'inactive') THEN
        IF NOT EXISTS ($f$ || q || $f$ 1 FROM public.residents r WHERE r.user_id = NEW.user_id AND r.id <> NEW.id
                        AND r.status NOT IN ('suspended', 'inactive')) THEN
          UPDATE public.users SET is_active = false WHERE id = NEW.user_id;
        END IF;
      ELSIF NEW.status = 'active' AND TG_OP = 'UPDATE' THEN
        UPDATE public.users SET is_active = true WHERE id = NEW.user_id;
      END IF;
      RETURN NEW;
    END;
    $b$
  $f$;
  UPDATE public.orgs
     SET settings = jsonb_set(COALESCE(settings, '{}'::jsonb), '{labels}',
         '{"co_owner": "Co-owner", "owner_family": "Owner''s family", "tenant_family": "Tenant''s family"}'::jsonb
           || COALESCE(settings -> 'labels', '{}'::jsonb))
   WHERE NOT (COALESCE(settings -> 'labels', '{}'::jsonb) ?& ARRAY['co_owner', 'owner_family', 'tenant_family']);

  -- housing-0017: announcements
  CREATE TABLE IF NOT EXISTS public.announcement_audiences (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
      name text NOT NULL, hint text NOT NULL DEFAULT '', filters jsonb NOT NULL,
      sort_order integer NOT NULL DEFAULT 0, created_by text, created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, name));
  CREATE TABLE IF NOT EXISTS public.announcements (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      org_id uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
      title text NOT NULL DEFAULT '', body text NOT NULL, greet boolean NOT NULL DEFAULT true,
      filters jsonb NOT NULL, audience_text text NOT NULL DEFAULT '', audience_name text NOT NULL DEFAULT '',
      file_name text, file_type text, file_data bytea,
      status text NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'sending', 'sent', 'cancelled')),
      send_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, finished_at timestamptz,
      created_by text, created_at timestamptz NOT NULL DEFAULT now());
  CREATE INDEX IF NOT EXISTS idx_announcements_due ON public.announcements (status, send_at);
  CREATE INDEX IF NOT EXISTS idx_announcements_org ON public.announcements (org_id, created_at DESC);
  CREATE TABLE IF NOT EXISTS public.announcement_recipients (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      announcement_id uuid NOT NULL REFERENCES public.announcements (id) ON DELETE CASCADE,
      user_id uuid REFERENCES public.users (id) ON DELETE SET NULL,
      name text NOT NULL, flats text NOT NULL DEFAULT '',
      channel text NOT NULL CHECK (channel IN ('whatsapp', 'telegram', 'email', 'none')),
      status text NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting', 'sending', 'sent', 'kept', 'delivered',
          'read', 'got_it', 'emailed', 'failed')),
      emailed boolean NOT NULL DEFAULT false, wamid text, note text,
      sent_at timestamptz, delivered_at timestamptz, read_at timestamptz, got_it_at timestamptz,
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (announcement_id, user_id));
  CREATE INDEX IF NOT EXISTS idx_announcement_recipients_todo ON public.announcement_recipients (announcement_id, status);
  CREATE INDEX IF NOT EXISTS idx_announcement_recipients_wamid ON public.announcement_recipients (wamid) WHERE wamid IS NOT NULL;
  EXECUTE q || 'id FROM public.orgs ORDER BY created_at LIMIT 1' INTO org;
  EXECUTE q || 'count(*) FROM public.announcement_audiences' INTO n;
  IF n = 0 AND org IS NOT NULL THEN
    INSERT INTO public.announcement_audiences (org_id, name, hint, filters, sort_order, created_by) VALUES
      (org, 'Everyone who lives here', 'e.g. flag hoisting, water cut',
       '{"lives": ["here"], "relations": ["owner", "co_owner", "owner_family", "tenant", "tenant_family"], "primary": "any", "wings": [], "roles": []}', 1, 'seed'),
      (org, 'AGM: primary members', 'living here or not',
       '{"lives": ["here", "away"], "relations": ["owner", "co_owner", "owner_family"], "primary": "only", "wings": [], "roles": []}', 2, 'seed'),
      (org, 'Tenants who live here', '',
       '{"lives": ["here"], "relations": ["tenant"], "primary": "any", "wings": [], "roles": []}', 3, 'seed'),
      (org, 'Owners'' side who live here, not primary', 'co-owners and family',
       '{"lives": ["here"], "relations": ["owner", "co_owner", "owner_family"], "primary": "not", "wings": [], "roles": []}', 4, 'seed'),
      (org, 'Everyone on the list', 'living here or not',
       '{"lives": ["here", "away"], "relations": ["owner", "co_owner", "owner_family", "tenant", "tenant_family"], "primary": "any", "wings": [], "roles": []}', 5, 'seed');
  END IF;

  -- core-0029: the standard words around an announcement (Messages screen > Announcements)
  INSERT INTO public.system_messages (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by) VALUES
    ('announce.greeting', 'en-IN', 'global', '', 1, 'Dear {first_name},', '["first_name"]'::jsonb, true, 'Standard wording', 'seed'),
    ('announce.sign_off', 'en-IN', 'global', '', 1, '— {org_name} committee', '["org_name"]'::jsonb, true, 'Standard wording', 'seed'),
    ('announce.email_subject', 'en-IN', 'global', '', 1, '📢 {title} · {org_name}', '["org_name", "title"]'::jsonb, true, 'Standard wording', 'seed'),
    ('announce.file_emailed', 'en-IN', 'global', '', 1, '📎 The file {file_name} was sent to your email.', '["file_name"]'::jsonb, true, 'Standard wording', 'seed'),
    ('announce.file_ask', 'en-IN', 'global', '', 1, '📎 This came with a file ({file_name}). Ask the committee for a copy.', '["file_name"]'::jsonb, true, 'Standard wording', 'seed')
  ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
END
$do$