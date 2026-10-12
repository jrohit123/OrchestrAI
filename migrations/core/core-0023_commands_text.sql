-- core-0023: the standard wording of 1 new message (group "menu"): the line under /menu in the list of commands that
-- WhatsApp shows when someone types a slash. Additions only: 1 row in system_messages (scope 'global', version 1), exactly
-- the words in app/services/messages.py. A client's own version still wins over it. Safe to run twice.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('commands.menu_hint', 'en-IN', 'global', '', 1, $txt$Show what I can do$txt$, '[]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
