-- core-0016: the standard wording of 16 new messages (group "hold", Messages screen: "Messages WhatsApp could not
-- deliver"), used when WhatsApp's 24-hour rule stops the chat bot from starting a message to a person who has not written
-- to it in the last 24 hours (QA-012). The message is kept, emailed to the person, the person who asked is told, and it is
-- sent on WhatsApp the moment the person writes; a PDF or sheet is emailed. Additions only: 16 rows in system_messages
-- (scope 'global', version 1), exactly the words in app/services/messages.py. A client's own version still wins over it.
-- Safe to run twice.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('hold.sender_told_emailed', 'en-IN', 'global', '', 1, $txt$⚠️ {person}'s WhatsApp is closed: they have not written to the chat bot in the last 24 hours, so WhatsApp would not deliver this. I emailed it to them, and I will also send it on WhatsApp as soon as they write to me.$txt$, '["person"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.sender_told_no_email', 'en-IN', 'global', '', 1, $txt$⚠️ {person}'s WhatsApp is closed: they have not written to the chat bot in the last 24 hours, so WhatsApp would not deliver this, and there is no email address on file for them. I will send it as soon as they write to me. Please ask them to send any message to the chat bot.$txt$, '["person"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.email_subject', 'en-IN', 'global', '', 1, $txt$A message from {sender_name} ({org_name})$txt$, '["org_name", "sender_name"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.email_intro', 'en-IN', 'global', '', 1, $txt${sender_name} sent you this message from {org_name}:$txt$, '["org_name", "sender_name"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.email_intro_automatic', 'en-IN', 'global', '', 1, $txt${org_name} sent you this:$txt$, '["org_name"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.email_footer_link', 'en-IN', 'global', '', 1, $txt$WhatsApp could not deliver this, because you have not written to the chat bot in the last 24 hours. To get the next messages on WhatsApp, tap this link and press Send:
{link}$txt$, '["link"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.email_footer_nolink', 'en-IN', 'global', '', 1, $txt$WhatsApp could not deliver this, because you have not written to the chat bot in the last 24 hours. To get the next messages on WhatsApp, send any message to the chat bot.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.ready_text', 'en-IN', 'global', '', 1, $txt$Show my waiting messages$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.waiting_intro', 'en-IN', 'global', '', 1, $txt$📬 You have {count} waiting message(s):$txt$, '["count"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.waiting_item', 'en-IN', 'global', '', 1, $txt$*{sender_name}* ({sent_at}): {held_text}$txt$, '["held_text", "sender_name", "sent_at"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.nothing_waiting', 'en-IN', 'global', '', 1, $txt$You have no waiting messages. 👍$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.delivered_to_sender', 'en-IN', 'global', '', 1, $txt$✅ {person} wrote to me, so I sent them your message on WhatsApp.$txt$, '["person"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.file_emailed', 'en-IN', 'global', '', 1, $txt$⚠️ {person}'s WhatsApp is closed: they have not written to the chat bot in the last 24 hours, so WhatsApp would not deliver this file. I emailed it to them.$txt$, '["person"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.file_no_email', 'en-IN', 'global', '', 1, $txt$⚠️ {person}'s WhatsApp is closed: they have not written to the chat bot in the last 24 hours, so WhatsApp would not deliver this file, and there is no email address on file for them. It was not sent. Please ask them to send any message to the chat bot, then ask me again.$txt$, '["person"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.file_email_failed', 'en-IN', 'global', '', 1, $txt$⚠️ {person}'s WhatsApp is closed: they have not written to the chat bot in the last 24 hours, so WhatsApp would not deliver this file, and the email could not be sent. It was not sent. Please try again in a few minutes, or ask them to send any message to the chat bot first.$txt$, '["person"]'::jsonb, true, 'Standard wording', 'seed'),
    ('hold.got_it_title', 'en-IN', 'global', '', 1, $txt$👍 Got it$txt$, '[]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
