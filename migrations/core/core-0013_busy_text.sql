-- core-0013: the standard wording of one new message, draft.busy ("One moment, I'm still working on your
-- last message"), sent when a person writes again before the chat bot has answered the last message and the
-- wait ran out. Additions only: one row in system_messages (scope 'global', version 1), exactly the words in
-- app/services/messages.py. A client's own version still wins over it. Safe to run twice.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('draft.busy', 'en-IN', 'global', '', 1, $txt$⏳ One moment, I'm still working on your last message. Please send this again in a few seconds.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
