-- housing-0015: tickets are the first record type of the schema editor.
--
-- Needs core-0028. Changes no ticket and nobody's access: it only describes, as data, what a ticket already is
-- (the table `cases`) and the fields the dashboard shows, so the editor can list them and add fields to it.
-- The system fields are read-only; a field a super admin adds to tickets is kept inside `cases.custom_fields`
-- (storage 'custom'), so adding one never changes the table. Safe to run twice.

INSERT INTO public.record_types (org_id, key, label, plural, table_name, number_prefix, statuses, is_system)
SELECT o.id, 'ticket', 'Ticket', 'Tickets', 'cases', 'CS', '[]'::jsonb, true
  FROM public.orgs o
ON CONFLICT (org_id, key) DO NOTHING;

INSERT INTO public.record_fields (org_id, record_type, key, label, kind, required, storage, is_system, sort_order)
SELECT o.id, 'ticket', f.key, f.label, f.kind, f.required, 'column', true, f.sort_order
  FROM public.orgs o
 CROSS JOIN (VALUES
     ('case_number', 'Number',      'text',   true,  1),
     ('title',       'Title',       'text',   true,  2),
     ('description', 'Details',     'text',   false, 3),
     ('priority',    'Urgency',     'text',   false, 4),
     ('location',    'Where',       'text',   false, 5)
 ) AS f (key, label, kind, required, sort_order)
ON CONFLICT (org_id, record_type, key) DO NOTHING;

-- An organisation added later gets the same starting rows (a trigger on orgs, as housing-0014 does for use cases).
CREATE OR REPLACE FUNCTION public.org_ticket_record_type() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.record_types (org_id, key, label, plural, table_name, number_prefix, statuses, is_system)
    VALUES (NEW.id, 'ticket', 'Ticket', 'Tickets', 'cases', 'CS', '[]'::jsonb, true)
    ON CONFLICT (org_id, key) DO NOTHING;
    INSERT INTO public.record_fields (org_id, record_type, key, label, kind, required, storage, is_system, sort_order)
    VALUES (NEW.id, 'ticket', 'case_number', 'Number',  'text', true,  'column', true, 1),
           (NEW.id, 'ticket', 'title',       'Title',   'text', true,  'column', true, 2),
           (NEW.id, 'ticket', 'description', 'Details', 'text', false, 'column', true, 3),
           (NEW.id, 'ticket', 'priority',    'Urgency', 'text', false, 'column', true, 4),
           (NEW.id, 'ticket', 'location',    'Where',   'text', false, 'column', true, 5)
    ON CONFLICT (org_id, record_type, key) DO NOTHING;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_org_ticket_record_type ON public.orgs;
CREATE TRIGGER trg_org_ticket_record_type AFTER INSERT ON public.orgs
    FOR EACH ROW EXECUTE FUNCTION public.org_ticket_record_type();
