-- Godrej only: a place for the photos people send on WhatsApp. WhatsApp keeps a photo for about 30 days only, so the
-- chat bot saves its own copy the moment the photo arrives (Telegram keeps its photos itself and only a reference
-- is stored, so nothing changes for those).
-- One new table, kept apart from the cases table so cases stay light:
--   data / mime_type / size_bytes  the picture itself and what it is
--   case_id                        the case it was put on (empty until the request that carries it is saved)
--   user_id                        who sent it
--   source / source_ref            where it came from (whatsapp) and the sender's own reference (Meta's media id)
-- A photo that never reaches a case is cleared by the nightly cleanup after the client's retention setting
-- (settings -> retention -> photos_days), leaving a copy of its row (without the picture) in archived_rows.
-- Additions only: nothing existing is changed. Safe to run twice.

CREATE TABLE IF NOT EXISTS public.case_photos (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL REFERENCES public.orgs (id) ON DELETE CASCADE,
    case_id     uuid REFERENCES public.cases (id) ON DELETE CASCADE,
    user_id     uuid REFERENCES public.users (id) ON DELETE SET NULL,
    source      text NOT NULL DEFAULT 'whatsapp',
    source_ref  text,
    mime_type   text NOT NULL,
    size_bytes  integer NOT NULL,
    data        bytea NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_case_photos_case ON public.case_photos (case_id) WHERE case_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_case_photos_loose ON public.case_photos (org_id, created_at) WHERE case_id IS NULL;
