-- core-0030: the standard wording of 4 new messages (group "approval") for the builder's "Get approval" step
-- (op ask_approval), which carries on after either answer: the note to the person who asked while it waits, the
-- request when the step has no wording of its own, the answer when nobody can approve, and the thank-you to the
-- approver. Additions only: 4 rows in system_messages (scope 'global', version 1), exactly the words in
-- app/services/messages.py. A client's own version still wins over it. Safe to run twice.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('approval.waiting', 'en-IN', 'global', '', 1, $txt$⏳ I have asked {approver} to approve. I will tell you the answer.$txt$, '["approver"]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.request_plain', 'en-IN', 'global', '', 1, $txt$📋 *Approval Request*

From: {requester}
For: {intent}

Please approve or reject:$txt$, '["intent", "requester"]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.nobody', 'en-IN', 'global', '', 1, $txt$Sorry, there is nobody I can ask to approve “{intent}” right now. Please tell the office.$txt$, '["intent"]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.answer_ack', 'en-IN', 'global', '', 1, $txt$Thank you. Your answer “{answer}” is recorded.$txt$, '["answer"]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;
