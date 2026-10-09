-- Godrej only: a WhatsApp number that is not on the people list is no longer asked for an email and a code. It is told
-- "Your number isn't registered, contact your admin", and nothing else happens (no code is emailed to anyone). People are
-- added by an admin with their name and number (the committee list was loaded that way); on their first message they give
-- their email and confirm it with a code. Stored as orgs.settings.onboarding.whatsapp_link = false.
-- To let unknown numbers link themselves by email again, remove that setting or set it to true.
-- Only added when Godrej has no choice yet, so a choice someone made is never overwritten, and the rest of
-- settings.onboarding is kept. Safe to run twice.

UPDATE public.orgs
   SET settings = jsonb_set(
           COALESCE(settings, '{}'::jsonb),
           '{onboarding}',
           COALESCE(settings -> 'onboarding', '{}'::jsonb) || '{"whatsapp_link": false}'::jsonb
       )
 WHERE NOT (COALESCE(settings -> 'onboarding', '{}'::jsonb) ? 'whatsapp_link');
