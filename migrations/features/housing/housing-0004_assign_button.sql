-- Godrej only: tells the dashboard which flow its "Assign" button runs: the flow "Assign a case"
-- (key case_pass_on), the one people already use from the chat bot. It writes one setting,
-- orgs.settings.case_buttons.assign, and only when no choice was made yet, so a different choice
-- is never overwritten.
-- Nothing else in settings is touched. The button works only while that flow is switched ON under
-- Flows; while it is off the dashboard says so instead. Safe to run twice.

UPDATE public.orgs
   SET settings = jsonb_set(
           COALESCE(settings, '{}'::jsonb),
           '{case_buttons}',
           COALESCE(settings -> 'case_buttons', '{}'::jsonb) || '{"assign": "case_pass_on"}'::jsonb
       )
 WHERE NOT (COALESCE(settings -> 'case_buttons', '{}'::jsonb) ? 'assign');
