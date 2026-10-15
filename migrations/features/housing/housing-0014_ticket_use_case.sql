-- housing-0014: tickets become the first use case, and the five kinds of people on a ticket become data.
--
-- Needs core-0027. Changes no ticket and nobody's access: the keys stored on every ticket today (requester, assignee,
-- level2, helper, watcher) become the first rows of record_people_kinds, with the words the dashboard showed until now.
--
--   1. The use case "Tickets" (record type 'ticket'), keeping photos.
--   2. The five kinds of people on a ticket, with what each means to the engine and the order it tells people in.
--   3. Every flow and building block that works on tickets is filed under Tickets (it reads or writes the case tables,
--      runs a case step or a case block, or is a button on a case). Nothing else is touched.
--   4. case_parties no longer has the five keys written into a CHECK: a trigger checks the key is a kind of person of a
--      ticket in this organisation instead, so a super admin can add one (for example "Contractor") without a migration.
--   5. An organisation added later gets the same starting use case and kinds (a trigger on orgs), so it never starts
--      with tickets that have no kinds of people.
--
-- Safe to run twice.

-- 1. the use case
INSERT INTO public.usecases (org_id, key, name, icon, description, record_type, keeps_photos, sort_order)
SELECT o.id, 'tickets', 'Tickets', '🎫', 'Complaints and requests, and who handles them.', 'ticket', true, 1
  FROM public.orgs o
ON CONFLICT (org_id, key) DO NOTHING;

-- 2. the kinds of people on a ticket (the keys tickets already store, so nothing changes on them)
INSERT INTO public.record_people_kinds (org_id, record_type, key, label, description, meaning, added, sort_order)
SELECT o.id, 'ticket', k.key, k.label, k.description, k.meaning, k.added, k.sort_order
  FROM public.orgs o
 CROSS JOIN (VALUES
     ('assignee',  'Handling it', 'The person the ticket is with now.',                              'handler',  false, 1),
     ('level2',    'Also told',   'Kept informed, and the backup when the person handling it does not act.', 'backup', true, 2),
     ('helper',    'Helping',     'Helps with it, such as someone it was passed on to.',             'other',    true,  3),
     ('requester', 'Raised it',   'The person who reported it.',                                     'raiser',   false, 4),
     ('watcher',   'Watching',    'Is kept informed but does not act on it.',                        'informed', true,  5)
 ) AS k (key, label, description, meaning, added, sort_order)
ON CONFLICT (org_id, record_type, key) DO NOTHING;

-- 3. file the ticket flows and blocks under Tickets
UPDATE public.workflows w
   SET usecase_id = u.id
  FROM public.usecases u
 WHERE u.org_id = w.org_id AND u.key = 'tickets' AND w.usecase_id IS NULL
   AND (w.kind = 'case_action'
        OR coalesce(w.steps::text, '') ~ '"op": ?"(case\.|notify\.parties)'
        OR coalesce(w.steps::text, '') ~ '"workflow": ?"case_'
        OR coalesce(w.steps::text, '') ~ '"(table|into|from)": ?"(cases|case_[a-z_]+)"'
        OR coalesce(w.entity_schema::text, '') ~ '"table": ?"(cases|case_[a-z_]+)"'
        OR coalesce(w.sql_template, '') ~* '\m(cases|case_[a-z_]+)\M'
        OR w.intent_key LIKE 'case\_%');

-- 4. the kind of person on a ticket is checked against the data, not a fixed list
ALTER TABLE public.case_parties DROP CONSTRAINT IF EXISTS case_parties_role_check;

CREATE OR REPLACE FUNCTION public.case_party_kind_check() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.record_people_kinds k
                    WHERE k.org_id = NEW.org_id AND k.record_type = 'ticket' AND k.key = NEW.party_role) THEN
        RAISE EXCEPTION '"%" is not a kind of person on a ticket here', NEW.party_role USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_case_party_kind_check ON public.case_parties;
CREATE TRIGGER trg_case_party_kind_check BEFORE INSERT OR UPDATE OF party_role ON public.case_parties
    FOR EACH ROW EXECUTE FUNCTION public.case_party_kind_check();

-- 5. an organisation added later starts with the same use case and kinds
CREATE OR REPLACE FUNCTION public.org_ticket_starting_kinds() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.usecases (org_id, key, name, icon, description, record_type, keeps_photos, sort_order)
    VALUES (NEW.id, 'tickets', 'Tickets', '🎫', 'Complaints and requests, and who handles them.', 'ticket', true, 1)
    ON CONFLICT (org_id, key) DO NOTHING;
    INSERT INTO public.record_people_kinds (org_id, record_type, key, label, description, meaning, added, sort_order)
    VALUES (NEW.id, 'ticket', 'assignee',  'Handling it', 'The person the ticket is with now.', 'handler', false, 1),
           (NEW.id, 'ticket', 'level2',    'Also told',   'Kept informed, and the backup when the person handling it does not act.', 'backup', true, 2),
           (NEW.id, 'ticket', 'helper',    'Helping',     'Helps with it, such as someone it was passed on to.', 'other', true, 3),
           (NEW.id, 'ticket', 'requester', 'Raised it',   'The person who reported it.', 'raiser', false, 4),
           (NEW.id, 'ticket', 'watcher',   'Watching',    'Is kept informed but does not act on it.', 'informed', true, 5)
    ON CONFLICT (org_id, record_type, key) DO NOTHING;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_org_ticket_starting_kinds ON public.orgs;
CREATE TRIGGER trg_org_ticket_starting_kinds AFTER INSERT ON public.orgs
    FOR EACH ROW EXECUTE FUNCTION public.org_ticket_starting_kinds();
