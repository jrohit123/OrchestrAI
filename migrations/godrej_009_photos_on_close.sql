-- godrej_009_photos_on_close.sql
-- Lets a person send photos while closing a case ("lift working again"), keeps them on the case
-- and sends them to everyone on it with the closed message. Safe to run again.
-- Run it in Railway's query box. The last line shows the result.

-- 1. Close takes photos, and keeps them on the case right after the case is closed
UPDATE workflows SET
  steps = $j$[{"op": "run_workflow", "params": {"workflow": "case_find"}}, {"op": "run_workflow", "params": {"workflow": "case_close", "inputs": {"note": "$fields.comment_text"}}}, {"op": "case.attach_photos", "params": {"case_id": "$case.id"}}, {"op": "run_workflow", "params": {"workflow": "case_tell_parties", "inputs": {"tell_message": "✅ Case {case_case_number} ({case_title}) was closed by {actor_name}.\nClosing note: {comment_text}"}}}]$j$::jsonb,
  settings = settings || '{"photos": true}'::jsonb
WHERE intent_key = 'case_close_with_note';

-- 2. The "tell everyone" block also sends the request's photos when it sends no buttons.
--    Nothing is sent if there are none, so passing a case on is unchanged.
UPDATE workflows SET
  steps = jsonb_set(steps, '{1,params,with_photos}', 'true'::jsonb)
WHERE intent_key = 'case_tell_parties'
  AND steps -> 1 ->> 'op' = 'notify.parties';

SELECT intent_key,
       settings ->> 'photos' AS takes_photos,
       jsonb_array_length(steps) AS steps,
       steps -> 1 -> 'params' ->> 'with_photos' AS sends_photos
  FROM workflows
 WHERE intent_key IN ('case_close_with_note', 'case_tell_parties');
