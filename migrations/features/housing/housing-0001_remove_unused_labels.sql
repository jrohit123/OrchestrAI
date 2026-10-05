-- housing-0001: remove two permission labels that nothing uses (Godrej only).
--
-- get_resident_cases_status and view_my_cases are held by Godrej roles, but no workflow has
-- those keys, no workflow step asks for them, and no code checks them (searched app/ and
-- checked a practice copy with tools/orphans.py). The only thing they do is show up in the
-- "Permissions: ..." line the AI is told on every turn. general_read is deliberately NOT removed.
--
-- Safe to run twice: the second time no role holds them. To put one back, add it to the roles
-- that had it (your backup lists them), for example:
--   UPDATE roles SET permissions = permissions || ARRAY['view_my_cases'] WHERE name = 'owner';

UPDATE public.roles
SET permissions = array_remove(array_remove(permissions, 'get_resident_cases_status'), 'view_my_cases')
WHERE permissions && ARRAY['get_resident_cases_status', 'view_my_cases'];
