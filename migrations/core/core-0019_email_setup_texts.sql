-- core-0019: the standard wording of 4 new messages (group "onboarding") for a person an admin added with only a name
-- and a number: the chat bot asks for their email on their first message, sends a code to it, and saves it when the
-- code comes back. Additions only: 4 rows in system_messages (scope 'global', version 1), exactly the words in
-- app/services/messages.py. A client's own version still wins over it. Safe to run twice.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('onboarding.email_ask', 'en-IN', 'global', '', 1, $txt$👋 Welcome, {name}! To finish setting up, reply with your *email address*. We'll send you a code to confirm it.$txt$, '["name"]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.email_taken', 'en-IN', 'global', '', 1, $txt$That email address is already used by someone else here. Please send your own email address.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.email_code_sent', 'en-IN', 'global', '', 1, $txt$🔐 A verification code has been sent to *{email}*.
Reply with the code to finish setting up.

_Code expires in {expiry_minutes} minutes. Reply 'retry' to start again._$txt$, '["email", "expiry_minutes"]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.email_done', 'en-IN', 'global', '', 1, $txt$✅ *All set, {name}!* Your email is saved.
Send *menu* to see what you can do.$txt$, '["name"]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
