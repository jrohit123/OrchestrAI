-- Godrej only: people are reached on WhatsApp from now on, not Telegram.
-- 1. The people table's default channel becomes 'whatsapp' (the dashboard reads this default to know how this client
--    reaches people: it asks for a WhatsApp number, optional, instead of nothing).
-- 2. Everyone's channel is set to 'whatsapp'. A person who is still linked on Telegram ("tg:...") keeps working on
--    Telegram until they link their WhatsApp number (they message the chat bot, send their email and enter the code);
--    that link replaces the Telegram one.
-- 3. The database's list of "people who can be reached" (route_targets, used when a case rule picks someone) counts a
--    person as reachable when they have any chat linked, and no longer counts an empty number as one.
-- No person, case, rule or message is changed. Safe to run twice.

ALTER TABLE public.users ALTER COLUMN channel SET DEFAULT 'whatsapp';

UPDATE public.users SET channel = 'whatsapp' WHERE channel IS DISTINCT FROM 'whatsapp';

CREATE OR REPLACE FUNCTION public.route_targets(p_org uuid, p_user uuid, p_position uuid, p_role uuid)
RETURNS uuid[]
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(array_agg(u.id ORDER BY u.name, u.id), '{}'::uuid[])
      FROM users u
     WHERE u.org_id = p_org
       AND u.is_active
       AND ((u.channel = 'telegram' AND u.phone LIKE 'tg:%')
            OR (COALESCE(u.channel, '') <> 'telegram' AND COALESCE(u.phone, '') <> ''))
       AND (
            (p_user IS NOT NULL AND u.id = p_user)
         OR (p_position IS NOT NULL AND EXISTS (
                SELECT 1 FROM committee_members m
                 WHERE m.user_id = u.id AND m.position_id = p_position AND m.status = 'active'
                   AND (m.start_date IS NULL OR m.start_date <= CURRENT_DATE)
                   AND (m.end_date   IS NULL OR m.end_date   >= CURRENT_DATE)))
         OR (p_role IS NOT NULL AND u.role_id = p_role)
       );
$$;
