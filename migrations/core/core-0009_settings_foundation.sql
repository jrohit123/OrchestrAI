-- core-0009: the foundation for settings, message texts and AI instructions kept in the database.
--
-- Additions only. Nothing reads these yet, and when the app does, an empty table changes
-- nothing: it falls back to the text that is built into the code and the prompt files.
--
-- 1. orgs.timezone and orgs.locale: the time zone and the language of a client. They default to
--    what the code assumes today (Asia/Kolkata, en-IN), so no client changes.
-- 2. prompts: the written instructions the assistant follows (AI instructions). One row is one
--    version of one text. A client's own text (scope 'tenant') wins over its industry's (scope
--    'pack', scope_ref = the industry) over the shared one (scope 'global'), and of those the
--    newest active version wins. Going back to an old version means saving it again as a new
--    one, so the history only ever grows.
-- 3. system_messages: the texts the assistant sends by itself (welcome, one-time codes, errors).
--    Same layers and versions, plus a locale.
--
-- Safe to run twice: IF NOT EXISTS skips what is already there.

ALTER TABLE public.orgs ADD COLUMN IF NOT EXISTS timezone text NOT NULL DEFAULT 'Asia/Kolkata';
ALTER TABLE public.orgs ADD COLUMN IF NOT EXISTS locale   text NOT NULL DEFAULT 'en-IN';

CREATE TABLE IF NOT EXISTS public.prompts (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key        text NOT NULL,
    scope      text NOT NULL DEFAULT 'tenant' CHECK (scope IN ('global', 'pack', 'tenant')),
    scope_ref  text NOT NULL DEFAULT '',
    version    integer NOT NULL CHECK (version >= 1),
    body       text NOT NULL,
    variables  jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_active  boolean NOT NULL DEFAULT true,
    note       text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text,
    UNIQUE (key, scope, scope_ref, version)
);

CREATE INDEX IF NOT EXISTS idx_prompts_lookup
    ON public.prompts (key, scope, scope_ref, version DESC) WHERE is_active;

CREATE TABLE IF NOT EXISTS public.system_messages (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key        text NOT NULL,
    locale     text NOT NULL DEFAULT 'en-IN',
    scope      text NOT NULL DEFAULT 'tenant' CHECK (scope IN ('global', 'pack', 'tenant')),
    scope_ref  text NOT NULL DEFAULT '',
    version    integer NOT NULL CHECK (version >= 1),
    body       text NOT NULL,
    variables  jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_active  boolean NOT NULL DEFAULT true,
    note       text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text,
    UNIQUE (key, locale, scope, scope_ref, version)
);

CREATE INDEX IF NOT EXISTS idx_system_messages_lookup
    ON public.system_messages (key, locale, scope, scope_ref, version DESC) WHERE is_active;
