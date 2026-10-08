-- Godrej only: the word the dashboard shows for the resident status not_residing is "Moved out" (UX-028).
-- Stored as orgs.settings.labels.not_residing: the organisation's own word for a stored value. The stored value
-- itself does not change (flows, rules and the database check rule still say not_residing); only what the
-- dashboard calls it. Added only when Godrej has no word for it yet, so a word someone chose is never overwritten,
-- and the rest of settings.labels is kept. An older app ignores it. Safe to run twice.

UPDATE public.orgs
   SET settings = jsonb_set(
           COALESCE(settings, '{}'::jsonb),
           '{labels}',
           COALESCE(settings -> 'labels', '{}'::jsonb) || '{"not_residing": "Moved out"}'::jsonb
       )
 WHERE NOT (COALESCE(settings -> 'labels', '{}'::jsonb) ? 'not_residing');
