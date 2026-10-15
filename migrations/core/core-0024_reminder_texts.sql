-- core-0024: the standard wording of 14 new messages (group "reminder"): the texts the reminder plans send at a share of a ticket's
-- time to fix. Additions only: rows in system_messages (scope 'global', version 1), exactly the words in app/services/messages.py.
-- A client's own version still wins over it. Safe to run twice.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('reminder.remind', 'en-IN', 'global', '', 1, $txt$⏰ Reminder: {ticket} has used {percent}% of its time to fix. Due {due}.$txt$, '["ticket", "percent", "due"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.overdue', 'en-IN', 'global', '', 1, $txt$🔴 {ticket} was due {due} and is still open. Please act on it.$txt$, '["ticket", "due"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.open_nudge', 'en-IN', 'global', '', 1, $txt$⏰ Reminder: {ticket} is still open after {open_for}. It has no time limit; this is a regular nudge.$txt$, '["ticket", "open_for"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.backup', 'en-IN', 'global', '', 1, $txt$👀 For your information: {ticket} is with {handler} and has used {percent}% of its time. You are the backup.$txt$, '["ticket", "handler", "percent"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.backup_open', 'en-IN', 'global', '', 1, $txt$👀 For your information: {ticket} is with {handler} and still open after {open_for}. You are the backup.$txt$, '["ticket", "handler", "open_for"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.handed_to_you', 'en-IN', 'global', '', 1, $txt$➡️ {ticket} is now with you: nobody had acted on it in time. Due {due}.$txt$, '["ticket", "due"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.handed_to_you_open', 'en-IN', 'global', '', 1, $txt$➡️ {ticket} is now with you: nobody had acted on it in time.$txt$, '["ticket"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.handed_away', 'en-IN', 'global', '', 1, $txt$ℹ️ {ticket} has moved to {handler} because nobody acted on it in time.$txt$, '["ticket", "handler"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.raiser', 'en-IN', 'global', '', 1, $txt$👍 Your ticket {ticket} is being followed up. It is with {handler}.$txt$, '["ticket", "handler"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.raiser_late', 'en-IN', 'global', '', 1, $txt$🙏 Your ticket {ticket} is taking longer than planned. It is being followed up with {handler}.$txt$, '["ticket", "handler"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.watcher', 'en-IN', 'global', '', 1, $txt$📋 {ticket} has used {percent}% of its time. It is with {handler}.$txt$, '["ticket", "percent", "handler"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.watcher_open', 'en-IN', 'global', '', 1, $txt$📋 {ticket} is still open after {open_for}. It is with {handler}.$txt$, '["ticket", "open_for", "handler"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.role', 'en-IN', 'global', '', 1, $txt$🔴 {ticket} has used {percent}% of its time and is still open. It is with {handler}.$txt$, '["ticket", "percent", "handler"]'::jsonb, true, 'Standard wording', 'seed'),
    ('reminder.role_open', 'en-IN', 'global', '', 1, $txt$🔴 {ticket} is still open after {open_for}. It is with {handler}.$txt$, '["ticket", "open_for", "handler"]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
