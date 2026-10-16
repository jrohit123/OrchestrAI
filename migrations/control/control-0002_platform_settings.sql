-- Settings shared by every organisation, kept in the routing (control) database: for now the common footer note that the
-- chat bot adds under its WhatsApp messages (each organisation can use it, write its own, or have none).
-- Goes to the routing (control) database only. One new table, empty; nothing that exists is altered. Safe to run twice.
--
--   platform_settings  key -> value (jsonb). 'footer' = {"text": "...", "plain": true|false}

CREATE TABLE IF NOT EXISTS public.platform_settings (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_by text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.platform_settings IS 'Settings shared by every organisation (the common footer note ...), changed by super admins.';
