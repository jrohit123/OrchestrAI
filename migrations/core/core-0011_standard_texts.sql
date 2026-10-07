-- core-0011: the standard wording of every message, and the standard reply style, kept in the database.
--
-- Additions only: rows in the two tables core-0009 made. The text of every row is exactly what the code
-- has always said (app/services/messages.py and app/prompts/response_formatting.txt), so nothing changes
-- for anyone. What changes is where the wording lives: the dashboard shows it as the standard wording,
-- and an organisation's own version (scope 'tenant') still wins over it. The code keeps its own copy as
-- the last fallback, for a database that has no such row.
--
-- To change the standard wording later, never edit this file: add a new numbered file that inserts the
-- next version (python -m tools.seed_texts). tests/test_standard_texts.py checks that the newest stored
-- text is the one in the code.
--
-- Safe to run twice: a row that is already there is skipped.

INSERT INTO public.system_messages
    (key, locale, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('onboarding.welcome', 'en-IN', 'global', '', 1, $txt$👋 Welcome to OrchestrAI!

Your Telegram account isn't linked yet.
Reply with your *email address* — if you already have an account, we'll link it; if not, we'll help you register as a new member.

_Example: john@example.com_$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.not_registered', 'en-IN', 'global', '', 1, $txt$👋 Your number isn't registered with OrchestrAI.
Contact your admin to get access.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.inactive', 'en-IN', 'global', '', 1, $txt$❌ Your account is inactive. Contact admin.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.code_sent', 'en-IN', 'global', '', 1, $txt$🔐 A verification code has been sent to *{email}*.
Reply with the code to link your Telegram account.

_Code expires in {expiry_minutes} minutes. Reply 'retry' to cancel and restart._$txt$, '["email", "expiry_minutes"]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.no_account', 'en-IN', 'global', '', 1, $txt$No existing account found for that email.

Want to register as a new member? Reply with your *full name* to get started — or contact your admin if you already have an account under a different email.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.unavailable', 'en-IN', 'global', '', 1, $txt$❌ Registration isn't available right now. Please contact your admin.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.not_a_name', 'en-IN', 'global', '', 1, $txt$That doesn't look like a name — please reply with your full name.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.pick_role', 'en-IN', 'global', '', 1, $txt$Thanks, {name}! Which role are you?

{role_list}

Reply with the number.$txt$, '["name", "role_list"]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.pick_role_again', 'en-IN', 'global', '', 1, $txt$Didn't recognise that — please reply with the number:

{role_list}$txt$, '["role_list"]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.pick_role_again_edit', 'en-IN', 'global', '', 1, $txt$Didn't catch which role you meant — please reply with the number:

{role_list}$txt$, '["role_list"]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.confirm_details', 'en-IN', 'global', '', 1, $txt$📝 Confirm your details:
  • Name: {name}
  • Email: {email}
  • Role: {role}

Reply *yes* to create your account, *no* to cancel, or tell me what to change (e.g. "change role to tenant").$txt$, '["email", "name", "role"]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.details_updated', 'en-IN', 'global', '', 1, $txt$📝 Updated. Confirm your details:
  • Name: {name}
  • Email: {email}
  • Role: {role}

Reply *yes* to create your account, *no* to cancel, or tell me what to change (e.g. "change role to tenant").$txt$, '["email", "name", "role"]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.cancelled', 'en-IN', 'global', '', 1, $txt$❌ Registration cancelled.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.unclear_confirm', 'en-IN', 'global', '', 1, $txt$I didn't quite catch that — reply *yes* to confirm, *no* to cancel, or tell me what to change (e.g. "change role to tenant").$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.create_failed', 'en-IN', 'global', '', 1, $txt$❌ Something went wrong creating your account. Please try again.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.account_created', 'en-IN', 'global', '', 1, $txt$✅ Account created! A verification code has been sent to *{email}*.
Reply with the code to activate your account.

_Code expires in {expiry_minutes} minutes._$txt$, '["email", "expiry_minutes"]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.email_failed_register', 'en-IN', 'global', '', 1, $txt$❌ Could not send verification email. Please contact your admin.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.link_restart', 'en-IN', 'global', '', 1, $txt$🔄 Cancelled. Please send your email again to restart linking.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.linked', 'en-IN', 'global', '', 1, $txt$✅ *Linked!* Welcome, {name}.
Your Telegram account is now connected to OrchestrAI.
Send /help to see available commands.$txt$, '["name"]'::jsonb, true, 'Standard wording', 'seed'),
    ('onboarding.link_failed', 'en-IN', 'global', '', 1, $txt$❌ Something went wrong linking your account. Please try again.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('otp.cooldown', 'en-IN', 'global', '', 1, $txt$⏳ Please wait {wait_seconds}s before requesting another code.$txt$, '["wait_seconds"]'::jsonb, true, 'Standard wording', 'seed'),
    ('otp.email_failed', 'en-IN', 'global', '', 1, $txt$❌ Could not send verification email. Contact admin.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('otp.not_a_code', 'en-IN', 'global', '', 1, $txt$That doesn't look like a code — please check your email and reply with just the digits.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('otp.many_numbers', 'en-IN', 'global', '', 1, $txt$I found more than one number in that message — please reply with just the code from your email.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('otp.rejected', 'en-IN', 'global', '', 1, $txt$❌ {reason}$txt$, '["reason"]'::jsonb, true, 'Standard wording', 'seed'),
    ('otp.none_active', 'en-IN', 'global', '', 1, $txt$No active OTP found. Reply 'retry' to get a new code.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('otp.too_many', 'en-IN', 'global', '', 1, $txt$Too many attempts. Reply 'retry' to get a new code.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('otp.expired', 'en-IN', 'global', '', 1, $txt$Code has expired. Reply 'retry' to get a new code.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('otp.wrong', 'en-IN', 'global', '', 1, $txt$Incorrect code. {remaining} attempt(s) remaining.$txt$, '["remaining"]'::jsonb, true, 'Standard wording', 'seed'),
    ('otp.wrong_last', 'en-IN', 'global', '', 1, $txt$Incorrect code. 0 attempts remaining. Reply 'retry' to get a new code.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('security.new_code', 'en-IN', 'global', '', 1, $txt$🔐 A new verification code has been sent to *{email}*.
Reply with the code to continue.$txt$, '["email"]'::jsonb, true, 'Standard wording', 'seed'),
    ('security.verified', 'en-IN', 'global', '', 1, $txt$✅ Identity verified!
_Session active for {ttl}. Processing your request..._$txt$, '["ttl"]'::jsonb, true, 'Standard wording', 'seed'),
    ('security.required', 'en-IN', 'global', '', 1, $txt$🔐 *Security Verification Required*

Your session has expired.
A verification code has been sent to *{email}*.
Reply with the code to continue.

_Required every {ttl} for security._$txt$, '["email", "ttl"]'::jsonb, true, 'Standard wording', 'seed'),
    ('security.verified_resend', 'en-IN', 'global', '', 1, $txt$✅ Identity verified! Session active for 4h. Please resend your request.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('security.verified_resend_short', 'en-IN', 'global', '', 1, $txt$✅ Verified! Please resend your original request.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.status', 'en-IN', 'global', '', 1, $txt$📋 *Draft Status*
Workflow: {intent}
Stage: {stage}
Fields collected: {count}

Tap /cancel to clear this draft.$txt$, '["count", "intent", "stage"]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.in_progress', 'en-IN', 'global', '', 1, $txt$📝 In progress: *{intent}* (started {age_min} min ago)
{field_lines}

Reply *cancel* to discard it, or continue where you left off.$txt$, '["age_min", "field_lines", "intent"]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.none', 'en-IN', 'global', '', 1, $txt$✅ No active draft. You're ready to start fresh.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.unfinished', 'en-IN', 'global', '', 1, $txt$You have an unfinished *{intent}* — continue, or tap /cancel.$txt$, '["intent"]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.waiting_confirm', 'en-IN', 'global', '', 1, $txt$You already have a *{intent}* draft waiting for confirmation:
{details}

Reply *yes* to confirm, *no* to cancel, or tell me what to change.$txt$, '["details", "intent"]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.filling', 'en-IN', 'global', '', 1, $txt$You're already filling out *{intent}*. So far:
{details}

Please continue with the remaining details, or /cancel to start over.$txt$, '["details", "intent"]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.cleared', 'en-IN', 'global', '', 1, $txt$🔄 Cleared. What would you like to do?

_Type *menu* to see your options._$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.nothing_in_progress', 'en-IN', 'global', '', 1, $txt$✅ Nothing in progress. Type *menu* to see your options.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.action_cancelled', 'en-IN', 'global', '', 1, $txt$❌ Action cancelled.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.confirm_timed_out', 'en-IN', 'global', '', 1, $txt$_⏱️ Your previous confirmation timed out and was cleared. Let me help with your new request._$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.reprompt_restart', 'en-IN', 'global', '', 1, $txt$🤔 I'm having trouble understanding the details for this request. Let's start fresh — please send your request again with all the details in one message.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.session_cleared', 'en-IN', 'global', '', 1, $txt$🔄 Session cleared. Please resend your original request.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.none_to_cancel', 'en-IN', 'global', '', 1, $txt$✅ No active draft to cancel.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.cancelled_count', 'en-IN', 'global', '', 1, $txt$🔄 Draft for *{intent}* cancelled ({count} field(s) discarded).$txt$, '["count", "intent"]'::jsonb, true, 'Standard wording', 'seed'),
    ('draft.cancelled', 'en-IN', 'global', '', 1, $txt$🔄 Draft cancelled.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('photo.held', 'en-IN', 'global', '', 1, $txt$📎 Got the photo. Now tell me what it is for, for example start /complaint, /update or /close. I keep it for {minutes} minutes.$txt$, '["minutes"]'::jsonb, true, 'Standard wording', 'seed'),
    ('photo.added', 'en-IN', 'global', '', 1, $txt$📎 Photo added ({count} attached).$txt$, '["count"]'::jsonb, true, 'Standard wording', 'seed'),
    ('photo.added_confirm', 'en-IN', 'global', '', 1, $txt$📎 Photo added ({count} attached). Reply *yes* to save.$txt$, '["count"]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.not_found', 'en-IN', 'global', '', 1, $txt$No pending approval found or already handled.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.already_handled', 'en-IN', 'global', '', 1, $txt$This request was already handled.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.not_allowed', 'en-IN', 'global', '', 1, $txt$You are not authorised to approve this request.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.own_request', 'en-IN', 'global', '', 1, $txt$You cannot approve your own request.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.rejected_ack', 'en-IN', 'global', '', 1, $txt$❌ Action rejected.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.rejected_notice', 'en-IN', 'global', '', 1, $txt$❌ Your request was *rejected* by {approver}.$txt$, '["approver"]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.escalated', 'en-IN', 'global', '', 1, $txt$✅ Your approval is recorded. Escalating to the next approver.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.request', 'en-IN', 'global', '', 1, $txt$📋 *Approval Request*

From: {requester}
Action: {intent}
Amount: Rs.{amount}

Please approve or reject:$txt$, '["amount", "intent", "requester"]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.request_level', 'en-IN', 'global', '', 1, $txt$📋 *Approval Request* — level {level} of {total}

From: {requester}
Action: {intent}
Amount: Rs.{amount}

Please approve or reject:$txt$, '["amount", "intent", "level", "requester", "total"]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.approved_nothing_to_run', 'en-IN', 'global', '', 1, $txt$✅ Approved, but no pending action found to execute.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.approved_ack', 'en-IN', 'global', '', 1, $txt$✅ Approved.

{message}$txt$, '["message"]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.approved_notice', 'en-IN', 'global', '', 1, $txt$✅ Your request was *approved* by {approver}.

{message}$txt$, '["approver", "message"]'::jsonb, true, 'Standard wording', 'seed'),
    ('approval.approved_failed', 'en-IN', 'global', '', 1, $txt$✅ Approved but execution failed: {message}$txt$, '["message"]'::jsonb, true, 'Standard wording', 'seed'),
    ('menu.intro', 'en-IN', 'global', '', 1, $txt$📋 Here's what I can help with:$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('menu.unknown_command', 'en-IN', 'global', '', 1, $txt$Didn't recognise that command — here's what's available:$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('error.generic', 'en-IN', 'global', '', 1, $txt$❌ Something went wrong. Please try again.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('error.with_id', 'en-IN', 'global', '', 1, $txt$❌ Something went wrong. Error ID: {correlation_id}. Please try again or contact support.$txt$, '["correlation_id"]'::jsonb, true, 'Standard wording', 'seed'),
    ('error.after_verification', 'en-IN', 'global', '', 1, $txt$❌ Something went wrong after verification. Please try again.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('error.document', 'en-IN', 'global', '', 1, $txt$❌ Something went wrong creating the document. Please try again.$txt$, '[]'::jsonb, true, 'Standard wording', 'seed'),
    ('action.completed', 'en-IN', 'global', '', 1, $txt$Action completed successfully$txt$, '[]'::jsonb, true, 'Standard wording', 'seed')
ON CONFLICT (key, locale, scope, scope_ref, version) DO NOTHING;

INSERT INTO public.prompts
    (key, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('agent.reply_style', 'global', '', 1, $txt$Format this data as a WhatsApp reply for a business ERP assistant.

WORKFLOW: {workflow_name}
BUSINESS GLOSSARY: {glossary_json}

RAW DATA (already fetched — this IS the current, correct data, do not question it):
{raw_data}

FORMATTING RULES:
- *bold* for key names/values, _italic_ for notes/footers, no HTML
- Indian comma format for money: Rs.1,45,000 (not Rs.145000, not ₹)
- If 5+ rows: lead with a one-line summary before listing details
- CRITICAL: You MUST list EVERY row in the data above — never skip, truncate,
  or summarize-only. Missing items is a serious error.
- Keep each item to ONE compact line, not a multi-line block — e.g.:
  *22kt Gold Ring* — 41 pcs — Rack B-3 (reorder at 50)
  Do NOT put SKU, location, qty, price each on their own line per item —
  that wastes space and will get truncated before all items are shown.
- If data says "EMPTY: No rows returned": say so naturally, don't apologize about an error
- If data says "No results found.": same as above
- Do NOT append any "reply pdf to get this as a document" hint — the user
  already knows they can ask for pdf/excel whenever they want one
- Never mention SQL, tables, columns, or JSON — this is a WhatsApp message to a business owner
- Be concise per item, but complete across all items — do not drop any row

Return ONLY the WhatsApp message text, nothing else.$txt$, '["glossary_json", "raw_data", "workflow_name"]'::jsonb, true, 'Standard text', 'seed')
ON CONFLICT (key, scope, scope_ref, version) DO NOTHING;
