UPDATE orgs SET settings = jsonb_set(jsonb_set(COALESCE(settings, '{}'::jsonb), '{whatsapp_flows,forms}', '{
  "send_announcement": {"enabled": true, "flow_id": "2023888304987024", "screen": "ANNOUNCEMENT", "button": "Write announcement",
                        "data": {"audiences": "ready_choices"}},
  "book_facility": {"enabled": true, "flow_id": "994468930362341", "screen": "BOOKING", "button": "Book now",
                    "data": {"facilities": "choices:facility", "times": "times", "today": "today"}},
  "preapprove_visitor": {"enabled": true, "flow_id": "2192328288329755", "screen": "VISITOR", "button": "Approve a visitor",
                         "data": {"times": "times", "today": "today"}, "join": {"visit_time": ["visit_date", "visit_hour"]}},
  "case_pass_on": {"enabled": true, "flow_id": "1091855190225230", "screen": "ASSIGN", "button": "Assign ticket",
                   "data": {"tickets": "open_tickets", "people": "people:case_add_update"}},
  "case_add_update": {"enabled": true, "flow_id": "1786998502504088", "screen": "TICKET_UPDATE", "button": "Update ticket",
                      "data": {"tickets": "my_tickets"}},
  "case_close_with_note": {"enabled": true, "flow_id": "1786998502504088", "screen": "TICKET_UPDATE", "button": "Update ticket",
                           "data": {"tickets": "my_tickets"}}
}'::jsonb), '{whatsapp_flows,time_slots}',
'["07:00","08:00","09:00","10:00","11:00","12:00","13:00","14:00","15:00","16:00","17:00","18:00","19:00","20:00","21:00"]'::jsonb)
WHERE settings ? 'whatsapp_flows'
