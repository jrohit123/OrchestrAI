-- Every client: the chat bot may read phone numbers, mobile numbers and emails when it answers a question
-- (the owner's decision: urgent questions must get an answer; how to limit it by person comes later).
-- core-0014 stored the patterns *phone*, *mobile*, *email*, password*, *otp* as orgs.settings.ai_sql.hidden_column_patterns.
-- This keeps only the two that hold secrets, password* and *otp*, and drops the personal-data ones. Only touches a
-- client that has such a list; nothing else in settings changes. To block a column again, add its pattern to that
-- list. Safe to run twice.

UPDATE public.orgs
   SET settings = jsonb_set(
           settings,
           '{ai_sql,hidden_column_patterns}',
           '["password*", "*otp*"]'::jsonb
       )
 WHERE settings -> 'ai_sql' ? 'hidden_column_patterns';
