-- core-0022: the standard wording of 3 new messages (group "menu") for the WhatsApp panels: the button that opens the
-- menu panel, the message above the complaint form, and the button that opens the form. Additions only: 3 rows in
-- system_messages (scope 'global', version 1), exactly the words in app/services/messages.py. A client's own version
-- still wins over it. Safe to run twice.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('flow.menu_button', 'en-IN', 'global', '', 1, $txt$Open menu$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('flow.complaint_intro', 'en-IN', 'global', '', 1, $txt$Fill in the form and I will show you a summary to confirm before anything is saved.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('flow.complaint_button', 'en-IN', 'global', '', 1, $txt$Raise a complaint$txt$, '[]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
