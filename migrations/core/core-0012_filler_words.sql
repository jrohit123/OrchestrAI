-- Every client: stores the polite words that may stand around a yes or a no, as
-- orgs.settings.vocabulary.filler_words: "yes please", "ok thanks", "haan ji", "yes save it".
-- The chat bot now accepts a yes or a no only when it is the WHOLE message (a confirm / cancel word, plus
-- at most these polite words), so "yes but make it 5000" and "no problem, go ahead" are no longer taken as
-- a yes or a cancel. Without this list "yes please" would go to the AI as a change request instead of saving.
-- The words are the organisation's own and can be edited later; the code has no list of its own.
-- Only added when the organisation has no filler_words yet, so a list someone wrote is never overwritten.
-- Nothing else in settings is touched. Safe to run twice.

UPDATE public.orgs
   SET settings = jsonb_set(
           COALESCE(settings, '{}'::jsonb),
           '{vocabulary}',
           COALESCE(settings -> 'vocabulary', '{}'::jsonb)
               || '{"filler_words": ["please", "pls", "plz", "thanks", "thank you", "thx", "ji", "sir", "madam", "mam", "save it", "do it", "now", "kar do", "kardo", "karo"]}'::jsonb
       )
 WHERE NOT (COALESCE(settings -> 'vocabulary', '{}'::jsonb) ? 'filler_words');
