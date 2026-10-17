-- core-0029: the standard wording of 5 new messages (group "announce", Messages screen: "Announcements"), used
-- around a message sent to many people at once from the Announcements screen: the greeting, who it is signed by,
-- the email subject for someone with no WhatsApp number, and the two notes about an attached file when the
-- person's WhatsApp is closed. Additions only: 5 rows in system_messages (scope 'global', version 1), exactly the
-- words in app/services/messages.py. A client's own version still wins over it. Safe to run twice.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('announce.greeting', 'en-IN', 'global', '', 1, $txt$Dear {first_name},$txt$, '["first_name"]'::jsonb, true, 'Standard wording', 'seed'),
    ('announce.sign_off', 'en-IN', 'global', '', 1, $txt$— {org_name} committee$txt$, '["org_name"]'::jsonb, true, 'Standard wording', 'seed'),
    ('announce.email_subject', 'en-IN', 'global', '', 1, $txt$📢 {title} · {org_name}$txt$, '["org_name", "title"]'::jsonb, true, 'Standard wording', 'seed'),
    ('announce.file_emailed', 'en-IN', 'global', '', 1, $txt$📎 The file {file_name} was sent to your email.$txt$, '["file_name"]'::jsonb, true, 'Standard wording', 'seed'),
    ('announce.file_ask', 'en-IN', 'global', '', 1, $txt$📎 This came with a file ({file_name}). Ask the committee for a copy.$txt$, '["file_name"]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
