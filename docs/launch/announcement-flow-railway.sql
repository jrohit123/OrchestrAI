DO $do$
DECLARE
  org uuid;
  uc uuid;
  q text := 'SEL' || 'ECT ';
BEGIN
  EXECUTE q || 'id FROM public.orgs ORDER BY created_at LIMIT 1' INTO org;
  IF org IS NULL THEN
    RETURN;
  END IF;
  EXECUTE q || 'id FROM public.usecases WHERE org_id = $1 AND key = ''broadcasting''' INTO uc USING org;
  IF uc IS NULL THEN
    EXECUTE q || 'id FROM public.usecases WHERE org_id = $1 AND key = ''announcements''' INTO uc USING org;
  END IF;
  IF uc IS NULL THEN
    INSERT INTO public.usecases (org_id, key, name, icon, description, record_type, keeps_photos, sort_order, is_active)
    VALUES (org, 'announcements', 'Announcements', '📢', 'One message to many people at once.', 'messages', false, 5, true)
    RETURNING id INTO uc;
  END IF;

  INSERT INTO public.workflows (org_id, intent_key, name, description, workflow_type, kind, steps, entity_schema,
      training_phrases, gates, is_active, version, menu_section, usecase_id, settings)
  VALUES (org, 'find_people', 'Find people by flat or role',
      'Finds the people of a ready choice (for example Everyone who lives here) and keeps them, with how many they are, for the steps after.',
      'action', 'block',
      $j$[{"op": "people.find", "params": {"audience": "$fields.audience", "into": "people"}}]$j$::jsonb,
      $j${"audience": {"type": "string", "required": true, "description": "The name of a ready choice, for example Everyone who lives here."}}$j$::jsonb,
      '[]'::jsonb, '[]'::jsonb, true, 1, 'other', uc, '{}'::jsonb)
  ON CONFLICT (org_id, intent_key) DO NOTHING;

  INSERT INTO public.workflows (org_id, intent_key, name, description, workflow_type, kind, steps, entity_schema,
      training_phrases, gates, is_active, version, menu_section, usecase_id, settings)
  VALUES (org, 'send_to_group', 'Send to a group',
      'Sends the message to the people found, in the background. WhatsApp''s 24-hour rule and the approved template are handled; who got it shows on the Announcements screen.',
      'action', 'block',
      $j$[{"op": "notify.group", "params": {"people": "$people", "message": "$fields.message"}}]$j$::jsonb,
      $j${"message": {"type": "string", "required": true, "description": "The announcement."}}$j$::jsonb,
      '[]'::jsonb, '[]'::jsonb, true, 1, 'other', uc, '{}'::jsonb)
  ON CONFLICT (org_id, intent_key) DO NOTHING;

  INSERT INTO public.workflows (org_id, intent_key, name, description, workflow_type, kind, steps, entity_schema,
      training_phrases, gates, is_active, version, menu_section, usecase_id, settings, response_template,
      slash_command, command_description)
  VALUES (org, 'send_announcement', 'Send an announcement',
      'Sends one message to many people at once: everyone who lives here, only tenants, the AGM minutes to the primary members. Shows how many people it goes to before sending.',
      'action', 'workflow',
      $j$[{"op": "run_workflow", "params": {"workflow": "find_people"}}, {"op": "run_workflow", "params": {"workflow": "send_to_group"}}]$j$::jsonb,
      $j${"audience": {"type": "string", "label": "Who gets it", "read_by": "typed", "required": true,
                       "question": "Who should get it? Reply with a ready choice, for example “Everyone who lives here”, “AGM: primary members” or “Tenants who live here”.",
                       "description": "The name of a ready choice from the Announcements screen."},
          "message": {"type": "string", "label": "Message", "read_by": "typed", "required": true,
                      "question": "What should the announcement say?",
                      "description": "The announcement, as it should be sent."}}$j$::jsonb,
      $j$["send an announcement", "make an announcement", "announce {message}", "broadcast a message", "send a message to all residents", "tell everyone who lives here"]$j$::jsonb,
      '[]'::jsonb, true, 1, 'create', uc, '{}'::jsonb,
      E'📢 *Announcement sent*\n\nIt goes to {people_count} people. You can see who got it on the dashboard, under Announcements.',
      'announce', 'Send an announcement')
  ON CONFLICT (org_id, intent_key) DO NOTHING;

  UPDATE public.roles SET permissions = array_append(permissions, 'send_announcement')
   WHERE org_id = org AND name IN ('admin', 'committee') AND NOT ('send_announcement' = ANY(permissions));
END
$do$
