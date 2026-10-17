-- Godrej only: announcements (a message to many people at once, for example "Flag hoisting starts in 15 minutes" to
-- everyone who lives here, or the AGM minutes to every primary member). Three new tables, nothing else changes:
--   announcement_audiences   ready choices of who gets one (the ticks of the Announcements screen, as data).
--                            Five are added once: everyone who lives here, AGM primary members, tenants who live
--                            here, the non-primary owner side who live here, everyone on the list.
--   announcements            what was written, to whom (the ticks and the same in words), when it goes, its state.
--   announcement_recipients  one row per person it went to: how (WhatsApp, Telegram, email), and what happened
--                            (sent, kept until they open their WhatsApp, delivered, read, tapped Got it, emailed,
--                            could not be reached). The name and flats are copied so the record stays as it was sent.
-- An attached file (the AGM minutes as a PDF) is kept in announcements.file_data.
-- Who gets it is worked out from residents (relation, is_primary, lives_here, wing; housing-0016) and users.role_id
-- at the moment it is sent. Safe to run twice.

CREATE TABLE IF NOT EXISTS public.announcement_audiences (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    name        text NOT NULL,
    hint        text NOT NULL DEFAULT '',
    filters     jsonb NOT NULL,
    sort_order  integer NOT NULL DEFAULT 0,
    created_by  text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS public.announcements (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    title          text NOT NULL DEFAULT '',
    body           text NOT NULL,
    greet          boolean NOT NULL DEFAULT true,
    filters        jsonb NOT NULL,
    audience_text  text NOT NULL DEFAULT '',
    audience_name  text NOT NULL DEFAULT '',
    file_name      text,
    file_type      text,
    file_data      bytea,
    status         text NOT NULL DEFAULT 'planned'
                   CHECK (status IN ('planned', 'sending', 'sent', 'cancelled')),
    send_at        timestamptz NOT NULL DEFAULT now(),
    started_at     timestamptz,
    finished_at    timestamptz,
    created_by     text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_announcements_due ON public.announcements (status, send_at);
CREATE INDEX IF NOT EXISTS idx_announcements_org ON public.announcements (org_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.announcement_recipients (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    announcement_id  uuid NOT NULL REFERENCES public.announcements (id) ON DELETE CASCADE,
    user_id          uuid REFERENCES public.users (id) ON DELETE SET NULL,
    name             text NOT NULL,
    flats            text NOT NULL DEFAULT '',
    channel          text NOT NULL CHECK (channel IN ('whatsapp', 'telegram', 'email', 'none')),
    status           text NOT NULL DEFAULT 'waiting'
                     CHECK (status IN ('waiting', 'sending', 'sent', 'kept', 'delivered', 'read', 'got_it',
                                       'emailed', 'failed')),
    emailed          boolean NOT NULL DEFAULT false,
    wamid            text,
    note             text,
    sent_at          timestamptz,
    delivered_at     timestamptz,
    read_at          timestamptz,
    got_it_at        timestamptz,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (announcement_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_announcement_recipients_todo
    ON public.announcement_recipients (announcement_id, status);
CREATE INDEX IF NOT EXISTS idx_announcement_recipients_wamid
    ON public.announcement_recipients (wamid) WHERE wamid IS NOT NULL;

COMMENT ON TABLE public.announcement_audiences IS 'Ready choices of who gets an announcement (filters on residents and roles), editable as data.';
COMMENT ON TABLE public.announcements IS 'Messages sent to many people at once from the Announcements screen.';
COMMENT ON TABLE public.announcement_recipients IS 'One row per person an announcement went to, and what happened to it.';

INSERT INTO public.announcement_audiences (org_id, name, hint, filters, sort_order, created_by)
SELECT o.id, a.name, a.hint, a.filters::jsonb, a.sort_order, 'seed'
  FROM public.orgs o
 CROSS JOIN (VALUES
    ('Everyone who lives here', 'e.g. flag hoisting, water cut',
     '{"lives": ["here"], "relations": ["owner", "co_owner", "owner_family", "tenant", "tenant_family"], "primary": "any", "wings": [], "roles": []}', 1),
    ('AGM: primary members', 'living here or not',
     '{"lives": ["here", "away"], "relations": ["owner", "co_owner", "owner_family"], "primary": "only", "wings": [], "roles": []}', 2),
    ('Tenants who live here', '',
     '{"lives": ["here"], "relations": ["tenant"], "primary": "any", "wings": [], "roles": []}', 3),
    ('Owners'' side who live here, not primary', 'co-owners and family',
     '{"lives": ["here"], "relations": ["owner", "co_owner", "owner_family"], "primary": "not", "wings": [], "roles": []}', 4),
    ('Everyone on the list', 'living here or not',
     '{"lives": ["here", "away"], "relations": ["owner", "co_owner", "owner_family", "tenant", "tenant_family"], "primary": "any", "wings": [], "roles": []}', 5)
 ) AS a (name, hint, filters, sort_order)
 WHERE NOT EXISTS (SELECT 1 FROM public.announcement_audiences x WHERE x.org_id = o.id);
