UPDATE workflows SET is_active = false, slash_command = NULL WHERE intent_key IN ('file_a_complaint', 'case_pass_on', 'case_add_update', 'case_close_with_note');
UPDATE roles SET permissions = array_remove(permissions, 'file_a_complaint') WHERE 'file_a_complaint' = ANY(permissions);
UPDATE roles SET permissions = array_remove(permissions, 'case_pass_on') WHERE 'case_pass_on' = ANY(permissions);
UPDATE roles SET permissions = array_remove(permissions, 'case_add_update') WHERE 'case_add_update' = ANY(permissions);
UPDATE roles SET permissions = array_remove(permissions, 'case_close_with_note') WHERE 'case_close_with_note' = ANY(permissions);
UPDATE workflows SET is_active = true, slash_command = 'complaint' WHERE intent_key = 'register_complaint';
UPDATE workflows SET is_active = true, slash_command = 'assign' WHERE intent_key = 'assign_case';
SELECT intent_key, kind, is_active, slash_command FROM workflows WHERE kind = 'workflow' ORDER BY intent_key;
