-- core-0015: the standard wording of one new message, onboarding.closed ("No account found for that email, and
-- sign-up by chat is not open. Please ask your admin to add you..."), said to a stranger on Telegram when this
-- organisation does not let people register themselves in the chat (QA-001). Additions only: one row in
-- system_messages (scope 'global', version 1), exactly the words in app/services/messages.py. A client's own
-- version still wins over it. Safe to run twice.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('onboarding.closed', 'en-IN', 'global', '', 1, $txt$No account found for that email, and sign-up by chat is not open. Please ask your admin to add you, then send your email here again.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
