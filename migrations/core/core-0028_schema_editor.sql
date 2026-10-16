-- core-0028: the schema editor (Build > Data & schema, super admins only).
--
-- Additions only. Three new tables, all empty until a super admin (or housing-0015) fills them. Nothing reads them until
-- the app is deployed; an old app ignores them. Safe to run twice.
--
--   record_types     the kinds of record an organisation keeps (Ticket, Visitor, Booking ...). One row each:
--                    table_name  the real table that holds the records (the editor makes it; 'cases' for tickets)
--                    statuses    [{"key", "label", "closed"}] in order (empty for tickets: their statuses are set by the
--                                ticket rules, not here)
--                    is_system   true for a kind the platform itself runs (tickets): its fields can be added to, never
--                                changed in the table
--   record_fields    the fields of a record type, as the dashboard shows them. storage 'column' = a real column of
--                    the table; 'custom' = a key inside the record's custom_fields (no table change at all).
--                    A field is never dropped, only switched off (is_active = false), so no data is ever lost.
--   schema_changes   the history: every change the editor applied (or that failed), with the SQL it ran and the SQL
--                    that would undo it (kept for a person to run, never run automatically).

CREATE TABLE IF NOT EXISTS public.record_types (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,
    key           text NOT NULL,
    label         text NOT NULL,
    plural        text NOT NULL,
    table_name    text,
    number_prefix text NOT NULL DEFAULT '',
    statuses      jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_system     boolean NOT NULL DEFAULT false,
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT record_types_key_check CHECK (key ~ '^[a-z][a-z0-9_]{0,39}$'),
    UNIQUE (org_id, key)
);

CREATE TABLE IF NOT EXISTS public.record_fields (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,
    record_type text NOT NULL,
    key         text NOT NULL,
    label       text NOT NULL,
    kind        text NOT NULL DEFAULT 'text',
    required    boolean NOT NULL DEFAULT false,
    options     jsonb NOT NULL DEFAULT '[]'::jsonb,
    storage     text NOT NULL DEFAULT 'column',
    is_system   boolean NOT NULL DEFAULT false,
    sort_order  integer NOT NULL DEFAULT 0,
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT record_fields_key_check CHECK (key ~ '^[a-z][a-z0-9_]{0,39}$'),
    CONSTRAINT record_fields_kind_check CHECK (kind IN ('text', 'number', 'date', 'time', 'datetime', 'choice', 'phone', 'photo', 'person', 'yesno')),
    CONSTRAINT record_fields_storage_check CHECK (storage IN ('column', 'custom')),
    UNIQUE (org_id, record_type, key)
);

CREATE TABLE IF NOT EXISTS public.schema_changes (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,
    summary    text NOT NULL,
    ops        jsonb NOT NULL DEFAULT '[]'::jsonb,
    sql_up     text NOT NULL DEFAULT '',
    sql_down   text NOT NULL DEFAULT '',
    status     text NOT NULL DEFAULT 'applied',
    error      text NOT NULL DEFAULT '',
    by_label   text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT schema_changes_status_check CHECK (status IN ('applied', 'failed'))
);
CREATE INDEX IF NOT EXISTS idx_schema_changes_org ON public.schema_changes (org_id, created_at DESC);

COMMENT ON TABLE public.record_types IS 'The kinds of record an organisation keeps (Ticket, Visitor ...) and the real table each lives in.';
COMMENT ON TABLE public.record_fields IS 'The fields of a record type; never dropped, only switched off.';
COMMENT ON TABLE public.schema_changes IS 'What the schema editor applied: the SQL it ran and the SQL that would undo it.';
