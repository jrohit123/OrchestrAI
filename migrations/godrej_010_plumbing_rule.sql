-- godrej_010_plumbing_rule.sql
-- Water and plumbing complaints go to Venkatesh. Lift stays with Rajeswari (Lift in-charge seat).
-- One rule on the main kind "Plumbing" covers every kind under it (leaks, blockages, pressure).
-- No level 2 and no backup on this one, so a complaint is only with Venkatesh until he passes it on.
-- Safe to run again. Run it in Railway's query box. The last line shows the rules.

INSERT INTO routing_rules (org_id, name, category_id, assign_user_id, sort_order)
SELECT o.id, 'Water and plumbing', cat.id, u.id, 20
  FROM orgs o
  JOIN case_categories cat ON cat.org_id = o.id AND cat.key = 'plumbing'
  JOIN users u ON u.org_id = o.id AND u.name = 'Venkatesh Batchu'
 WHERE o.slug = 'godrej-emerald'
   AND NOT EXISTS (SELECT 1 FROM routing_rules r WHERE r.org_id = o.id AND r.name = 'Water and plumbing');

SELECT r.name AS rule, c.label AS kind_of_complaint,
       COALESCE(u.name, p.name) AS goes_to, r.is_active AS on_now
  FROM routing_rules r
  LEFT JOIN case_categories c ON c.id = r.category_id
  LEFT JOIN users u ON u.id = r.assign_user_id
  LEFT JOIN committee_positions p ON p.id = r.assign_position_id
 ORDER BY r.sort_order;
