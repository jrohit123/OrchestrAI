-- core-0018: the standard wording of 3 new messages (group "photo") for photos and other kinds of message sent on
-- WhatsApp: a photo that could not be saved, a photo that is too big, and a voice note, video, document, location or
-- contact the chat bot cannot read. Additions only: 3 rows in system_messages (scope 'global', version 1), exactly the
-- words in app/services/messages.py. A client's own version still wins over it. Safe to run twice.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('photo.failed', 'en-IN', 'global', '', 1, $txt$⚠️ I couldn't save that photo. Please send it again, or tell me about it in words.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('photo.too_big', 'en-IN', 'global', '', 1, $txt$⚠️ That photo is too big to save (the limit is {limit_mb} MB). Please send a smaller one.$txt$, '["limit_mb"]'::jsonb, true, 'Standard wording', 'seed'),
    ('photo.unsupported', 'en-IN', 'global', '', 1, $txt$I can only read text and photos here. Please type your message or send a photo.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
