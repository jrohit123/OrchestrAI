-- Godrej only: the personal-data columns of the residents table that the AI may never use in a question it
-- writes itself: first_owner_mobile (a flat owner's mobile number) and brokers_name. Stored as
-- orgs.settings.ai_sql.hidden_columns (QA-033). first_owner_mobile is also covered by the *mobile* pattern of
-- core-0014; it is listed here too so it does not depend on a pattern. Owners can read the residents table
-- through the bot, so before this a flat owner could ask for other residents' mobile numbers.
-- Only added when Godrej has no such list yet; nothing else in settings is touched. Safe to run twice.

UPDATE public.orgs
   SET settings = jsonb_set(
           COALESCE(settings, '{}'::jsonb),
           '{ai_sql}',
           COALESCE(settings -> 'ai_sql', '{}'::jsonb)
               || '{"hidden_columns": ["first_owner_mobile", "brokers_name"]}'::jsonb
       )
 WHERE NOT (COALESCE(settings -> 'ai_sql', '{}'::jsonb) ? 'hidden_columns');
