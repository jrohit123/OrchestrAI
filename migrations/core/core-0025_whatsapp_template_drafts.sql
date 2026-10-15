-- core-0025: a place for WhatsApp message templates that are written on the dashboard but not sent to Meta yet.
--
-- Additions only: one new table. Meta keeps the real templates (and their approval); this table keeps the half-written ones,
-- and, after a template was sent for approval, what each blank is for ("customer name"), which Meta has no place for.
-- Nothing reads it until the dashboard code is deployed. Safe to run twice.

CREATE TABLE IF NOT EXISTS public.whatsapp_template_drafts (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    name             text NOT NULL,
    language         text NOT NULL DEFAULT 'en',
    category         text NOT NULL DEFAULT 'UTILITY',
    spec             jsonb NOT NULL DEFAULT '{}'::jsonb,
    meta_template_id text,
    submitted_at     timestamptz,
    created_by       text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_whatsapp_template_drafts_name
    ON public.whatsapp_template_drafts (org_id, name, language);
COMMENT ON TABLE public.whatsapp_template_drafts IS 'Message templates written on the dashboard: drafts not sent to Meta yet, and the labels of the blanks of those that were.';
