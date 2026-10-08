-- Every client: the personal-data column patterns the AI may never use in a question it writes itself, kept
-- as orgs.settings.ai_sql.hidden_column_patterns: *phone*, *mobile*, *email*, password*, *otp*.
-- The guard now refuses a column that matches one of these ANYWHERE in the query (not only in what it returns):
-- in a filter, a join, a sort or a group too, because a yes/no question about a phone number finds it out one
-- digit at a time (QA-008). The code keeps a very small minimum of its own (phone, email, otp_hash) and adds
-- this list to it, never the other way round, so an empty or wrong list can never expose those.
-- Only added when the client has no such list yet, so a list someone wrote is never overwritten; the rest of
-- settings.ai_sql (enabled, roles) is kept. Nothing reads it until the app is deployed, and an old app ignores
-- it. Safe to run twice.

UPDATE public.orgs
   SET settings = jsonb_set(
           COALESCE(settings, '{}'::jsonb),
           '{ai_sql}',
           COALESCE(settings -> 'ai_sql', '{}'::jsonb)
               || '{"hidden_column_patterns": ["*phone*", "*mobile*", "*email*", "password*", "*otp*"]}'::jsonb
       )
 WHERE NOT (COALESCE(settings -> 'ai_sql', '{}'::jsonb) ? 'hidden_column_patterns');
