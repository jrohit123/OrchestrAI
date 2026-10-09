-- Godrej only: chooses the approved WhatsApp template the chat bot sends to a person whose WhatsApp has closed (they
-- have not written to it in 24 hours) while a message waits for them: orgs.settings -> reach.template, the template's
-- name and language as written in Meta's WhatsApp Manager. The template has no blanks to fill in and one button
-- ("Proceed"); when the person taps it their WhatsApp opens again and the waiting message arrives. The email with the
-- one-tap link stays as the backup. Added only when Godrej has no template chosen yet, so one someone chose is never
-- overwritten, and the rest of settings.reach is kept. To stop using it: remove reach.template from the settings.
-- An older app ignores it. Safe to run twice.

UPDATE public.orgs
   SET settings = jsonb_set(
           COALESCE(settings, '{}'::jsonb),
           '{reach}',
           COALESCE(settings -> 'reach', '{}'::jsonb) || '{"template": {"name": "session_active", "language": "en"}}'::jsonb
       )
 WHERE NOT (COALESCE(settings -> 'reach', '{}'::jsonb) ? 'template');
