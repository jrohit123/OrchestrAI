-- core-0027: use cases, and the kinds of people a record can have.
--
-- Additions only. Two new tables and one new column, all empty until housing-0014 (or a super admin) fills them.
--
--   usecases              what an organisation does with the chat bot: Tickets, Bookings, Visitors ... Each one keeps one
--                         kind of record (record_type: 'ticket', 'booking', 'visitor' ...). The chat menu, the flows and the
--                         building blocks are grouped by it.
--   record_people_kinds   the kinds of people one kind of record can have, as data instead of a fixed list in the code:
--                         a ticket has "Raised it", "Handling it", "Also told" ...; a visitor would have "Host resident".
--                         key      stays the same for ever (it is what is stored on each record), the label can change;
--                         meaning  what the engine may rely on: raiser (who asked), handler (who has it), backup (steps in
--                                  when the handler does not), informed (is told), other;
--                         added    true when a flow may put people on a record as this kind; false when the system sets it
--                                  itself (who raised it, who handles it);
--                         sort_order  who comes first when one person is on a record in several ways.
--   workflows.usecase_id  the use case a flow or building block belongs to (empty = shared by every use case).
--
-- Nothing reads these until the app is deployed; an old app ignores them. Safe to run twice.

CREATE TABLE IF NOT EXISTS public.usecases (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,
    key          text NOT NULL,
    name         text NOT NULL,
    icon         text NOT NULL DEFAULT '',
    description  text NOT NULL DEFAULT '',
    record_type  text NOT NULL,
    keeps_photos boolean NOT NULL DEFAULT false,
    sort_order   integer NOT NULL DEFAULT 0,
    is_active    boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT usecases_key_check CHECK (key ~ '^[a-z][a-z0-9_]{0,39}$'),
    CONSTRAINT usecases_record_type_check CHECK (record_type ~ '^[a-z][a-z0-9_]{0,39}$'),
    UNIQUE (org_id, key)
);

CREATE TABLE IF NOT EXISTS public.record_people_kinds (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,
    record_type text NOT NULL,
    key         text NOT NULL,
    label       text NOT NULL,
    description text NOT NULL DEFAULT '',
    meaning     text NOT NULL DEFAULT 'other',
    added       boolean NOT NULL DEFAULT true,
    sort_order  integer NOT NULL DEFAULT 0,
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT record_people_kinds_key_check CHECK (key ~ '^[a-z][a-z0-9_]{0,39}$'),
    CONSTRAINT record_people_kinds_meaning_check CHECK (meaning IN ('raiser', 'handler', 'backup', 'informed', 'other')),
    UNIQUE (org_id, record_type, key)
);

ALTER TABLE public.workflows ADD COLUMN IF NOT EXISTS usecase_id uuid REFERENCES public.usecases(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_workflows_usecase ON public.workflows (usecase_id) WHERE usecase_id IS NOT NULL;

COMMENT ON TABLE public.usecases IS 'What an organisation does with the chat bot (Tickets, Bookings, Visitors); each keeps one kind of record.';
COMMENT ON TABLE public.record_people_kinds IS 'The kinds of people a kind of record can have (Raised it, Handling it ...): labels, meaning and order as data.';
