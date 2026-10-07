-- Dashboard sign-in: the people who may sign in, their short-lived keys, and a log.
-- Goes to the routing (control) database only. Nothing in a client database changes and
-- nothing that already exists is altered: three new tables. Safe to run twice.
--
--   panel_accounts  one row per person who may sign in (never deleted: switched off instead)
--   panel_keys      signed-in browsers and the codes sent by email; only hashes are kept
--   panel_audit     what happened: sign-ins, failures, locks, access given or taken

CREATE TABLE IF NOT EXISTS public.panel_accounts (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text NOT NULL,
    name          text NOT NULL,
    level         text NOT NULL,
    source_keys   text[] NOT NULL DEFAULT '{}',
    status        text NOT NULL DEFAULT 'invited',
    password_hash text,
    wrong_tries   integer NOT NULL DEFAULT 0,
    locked_until  timestamptz,
    last_sign_in  timestamptz,
    invited_by    uuid REFERENCES public.panel_accounts (id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT panel_accounts_email_check  CHECK (email <> '' AND email = lower(btrim(email))),
    CONSTRAINT panel_accounts_name_check   CHECK (btrim(name) <> ''),
    CONSTRAINT panel_accounts_level_check  CHECK (level IN ('super', 'admin')),
    CONSTRAINT panel_accounts_status_check CHECK (status IN ('invited', 'active', 'off')),
    -- a super admin may open every organisation, so the list stays empty; an admin that is
    -- not switched off must have at least one organisation to open
    CONSTRAINT panel_accounts_orgs_check   CHECK (
        (level = 'super' AND cardinality(source_keys) = 0)
        OR (level = 'admin' AND (status = 'off' OR cardinality(source_keys) > 0))
    ),
    CONSTRAINT panel_accounts_password_check CHECK (status <> 'active' OR password_hash IS NOT NULL),
    CONSTRAINT panel_accounts_tries_check  CHECK (wrong_tries >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS panel_accounts_email_key ON public.panel_accounts (email);
COMMENT ON TABLE public.panel_accounts IS 'People who may sign in to the dashboard. level super = every organisation, admin = only the ones in source_keys. status invited = added but no password yet, off = cannot sign in.';
COMMENT ON COLUMN public.panel_accounts.password_hash IS 'Slow salted hash (scrypt$...), never the password itself.';

CREATE TABLE IF NOT EXISTS public.panel_keys (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id  uuid NOT NULL REFERENCES public.panel_accounts (id) ON DELETE CASCADE,
    kind        text NOT NULL,
    key_hash    text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    last_used   timestamptz,
    used_at     timestamptz,
    tries       integer NOT NULL DEFAULT 0,
    ip          text,
    agent       text,
    CONSTRAINT panel_keys_kind_check  CHECK (kind IN ('session', 'signup', 'reset', 'signin')),
    CONSTRAINT panel_keys_tries_check CHECK (tries >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS panel_keys_session_key ON public.panel_keys (key_hash) WHERE kind = 'session';
CREATE INDEX IF NOT EXISTS panel_keys_account ON public.panel_keys (account_id, kind, created_at DESC);
CREATE INDEX IF NOT EXISTS panel_keys_expires ON public.panel_keys (expires_at);
COMMENT ON TABLE public.panel_keys IS 'Short-lived things, only as hashes: kind session = a signed-in browser (the cookie holds the secret), signup / reset / signin = a 6-digit code sent by email.';

CREATE TABLE IF NOT EXISTS public.panel_audit (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    account_id  uuid REFERENCES public.panel_accounts (id) ON DELETE SET NULL,
    email       text,
    action      text NOT NULL,
    ok          boolean NOT NULL DEFAULT true,
    source_key  text,
    detail      text,
    ip          text,
    agent       text
);
CREATE INDEX IF NOT EXISTS panel_audit_time ON public.panel_audit (at DESC);
CREATE INDEX IF NOT EXISTS panel_audit_account ON public.panel_audit (account_id, at DESC);
COMMENT ON TABLE public.panel_audit IS 'Who signed in, who failed, who was locked, who was given or lost access. Only added to. Changes inside an organisation are in that organisation''s admin_events.';
