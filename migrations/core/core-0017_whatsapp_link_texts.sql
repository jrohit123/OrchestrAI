-- core-0017: the standard wording of 3 new messages (group "onboarding") for a person who links their WhatsApp number to
-- their account by sending their email and the code emailed to them: the welcome, the "code sent" and the "linked" texts,
-- the same as the Telegram ones but naming WhatsApp. Additions only: 3 rows in system_messages (scope 'global',
-- version 1), exactly the words in app/services/messages.py. A client's own version still wins over it. Safe to run twice.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('onboarding.welcome_whatsapp', 'en-IN', 'global', '', 1, $txt$👋 Welcome to OrchestrAI!

Your WhatsApp number isn't linked to an account yet.
Reply with your *email address* — the one your admin added — and we'll send you a code to link it.

_Example: john@example.com_$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.code_sent_whatsapp', 'en-IN', 'global', '', 1, $txt$🔐 A verification code has been sent to *{email}*.
Reply with the code to link your WhatsApp number.

_Code expires in {expiry_minutes} minutes. Reply 'retry' to cancel and restart._$txt$, '["email", "expiry_minutes"]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.linked_whatsapp', 'en-IN', 'global', '', 1, $txt$✅ *Linked!* Welcome, {name}.
Your WhatsApp number is now connected to OrchestrAI.
Send *menu* to see what you can do.$txt$, '["name"]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
