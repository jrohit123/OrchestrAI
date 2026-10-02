-- godrej_008_plain_labels.sql
-- Descriptions that still say what the workflows did before the Lift story, and two blocks with
-- the same name. Only text changes. Nothing else is touched. Safe to run again.
-- Run it in Railway's query box. The last line shows the result.

UPDATE workflows SET description =
  'Files a new complaint. It is put in a category, sent to whoever the routing rules name, and everyone on the case is told.'
 WHERE intent_key = 'file_a_complaint';

UPDATE workflows SET description =
  'Adds a note to a case, with photos if you send them, and tells everyone on the case.'
 WHERE intent_key = 'case_add_update';

UPDATE workflows SET description =
  'Gives a case to one person, keeps an optional note, and tells everyone on the case.'
 WHERE intent_key = 'case_pass_on';

UPDATE workflows SET description =
  'Closes a case. The closing note is compulsory. Tells everyone on the case.'
 WHERE intent_key = 'case_close_with_note';

-- three older "tell" blocks that nothing uses any more: say so, and stop two of them looking identical
UPDATE workflows SET name = 'Tell the person who now has the case (old, unused)'
 WHERE intent_key = 'case_tell_assignee';
UPDATE workflows SET name = 'Tell the person who has the case (old, unused)'
 WHERE intent_key = 'case_tell_handler';
UPDATE workflows SET name = 'Tell the person who raised the case (old, unused)'
 WHERE intent_key = 'case_tell_requester';

SELECT intent_key, name, left(description, 70) AS description
  FROM workflows
 WHERE intent_key IN ('file_a_complaint', 'case_add_update', 'case_pass_on', 'case_close_with_note',
                      'case_tell_assignee', 'case_tell_handler', 'case_tell_requester')
 ORDER BY intent_key;
