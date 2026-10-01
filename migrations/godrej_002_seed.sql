-- godrej_002_seed.sql
--
-- Starting data for the new case model, for Godrej Emerald only. Run AFTER godrej_002_case_model.sql.
-- Everything here is editable later from the dashboard. Safe to re-run: each insert skips what exists.
--
-- What it creates
--   * a starter set of categories and sub-categories, with default priority and keywords
--   * two volunteer seats: Lift in-charge and Lift level 2 (LiftCare liaison)
--   * Rajeswari Batchu in the Lift in-charge seat, Venkatesh Batchu in the Lift level 2 seat
--   * one routing rule: Lift -> Lift in-charge (level 2: Lift level 2)
-- Every other category has no rule yet, so those cases stay unassigned, as today, until an admin
-- assigns them or you add a rule from the dashboard (housekeeping, parking and so on come later).
-- No role is changed: the seats are volunteer seats.

BEGIN;

-- ── categories ──────────────────────────────────────────────────────────────
WITH o AS (SELECT id FROM orgs WHERE slug = 'godrej-emerald')
INSERT INTO case_categories (org_id, key, label, default_priority, target_minutes, keywords, extra_fields, sort_order)
SELECT o.id, v.key, v.label, v.prio, v.tm::integer, v.kw, v.extra::jsonb, v.ord
  FROM o CROSS JOIN (VALUES
    ('lift',               'Lift',                        NULL,     NULL, ARRAY['lift','elevator','buzzer','overload'],                '[{"key":"lift_id","label":"Which lift?","type":"choice","options":["Lift A","Lift B","Lift C","Service lift"]}]', 10),
    ('plumbing',           'Plumbing',                    NULL,     NULL, ARRAY['plumb','pipe','tap','water','flush','toilet'],        '[]', 20),
    ('electrical',         'Electrical',                  NULL,     NULL, ARRAY['electric','power','switch','wiring','mcb','fuse','light'], '[]', 30),
    ('housekeeping',       'Housekeeping',                NULL,     NULL, ARRAY['clean','garbage','dust','sweep','pest','mosquito'],   '[]', 40),
    ('security',           'Security',                    NULL,     NULL, ARRAY['guard','gate','cctv','visitor','security'],           '[]', 50),
    ('parking',            'Parking',                     NULL,     NULL, ARRAY['parking','vehicle','car','bike','sticker'],           '[]', 60),
    ('common',             'Common areas',                NULL,     NULL, ARRAY['clubhouse','garden','pool','gym','terrace','playground'], '[]', 70),
    ('other',              'Something else',              'medium', NULL, ARRAY[]::text[],                                             '[]', 90)
  ) AS v(key, label, prio, tm, kw, extra, ord)
ON CONFLICT (org_id, key) DO NOTHING;

WITH o AS (SELECT id FROM orgs WHERE slug = 'godrej-emerald')
INSERT INTO case_categories (org_id, parent_id, key, label, default_priority, target_minutes, keywords, extra_fields, sort_order)
SELECT o.id, p.id, v.key, v.label, v.prio, v.tm::integer, v.kw, v.extra::jsonb, v.ord
  FROM o CROSS JOIN (VALUES
    ('lift',         'lift.stuck',          'Stuck or entrapment',   'urgent', 60,   ARRAY['stuck','trapped','entrap','not moving','between floors'], '[]', 11),
    ('lift',         'lift.noise',          'Noise or vibration',    'medium', NULL, ARRAY['noise','vibrat','jerk','sound','rattl'],                  '[]', 12),
    ('lift',         'lift.door',           'Door or buttons',       'medium', NULL, ARRAY['door','button','display','panel'],                        '[]', 13),
    ('plumbing',     'plumbing.leak',       'Leakage or seepage',    'high',   NULL, ARRAY['leak','seep','drip','ceiling','damp'],                    '[]', 21),
    ('plumbing',     'plumbing.block',      'Blockage or drainage',  'high',   NULL, ARRAY['block','choke','clog','drain','overflow','sewage'],       '[]', 22),
    ('plumbing',     'plumbing.pressure',   'Low water pressure',    'medium', NULL, ARRAY['pressure','low water','no water','supply'],               '[]', 23),
    ('electrical',   'electrical.lights',   'Lights in common areas','low',    NULL, ARRAY['light','bulb','lamp','dim','flicker','tube'],             '[]', 31),
    ('electrical',   'electrical.outage',   'Power outage',          'urgent', NULL, ARRAY['power cut','outage','no power','no electricity','tripped'],'[]', 32),
    ('electrical',   'electrical.wiring',   'Wiring or sparks',      'urgent', NULL, ARRAY['spark','short circuit','shock','burning smell','wiring'], '[]', 33),
    ('housekeeping', 'housekeeping.cleaning','Cleaning',             'low',    NULL, ARRAY['clean','dirty','sweep','mop','dust'],                     '[]', 41),
    ('housekeeping', 'housekeeping.garbage','Garbage collection',    'medium', NULL, ARRAY['garbage','waste','dustbin','trash','smell'],              '[]', 42),
    ('housekeeping', 'housekeeping.pest',   'Pest control',          'medium', NULL, ARRAY['pest','cockroach','rat','mosquito','ants'],               '[]', 43),
    ('security',     'security.gate',       'Gate or visitors',      'medium', NULL, ARRAY['gate','visitor','entry','barrier'],                       '[]', 51),
    ('security',     'security.cctv',       'CCTV',                  'medium', NULL, ARRAY['cctv','camera','footage'],                                '[]', 52),
    ('security',     'security.threat',     'Suspicious activity',   'urgent', NULL, ARRAY['suspicious','theft','stranger','intruder','fight'],       '[]', 53),
    ('parking',      'parking.wrong',       'Wrong parking or blocking','low', NULL, ARRAY['blocking','wrong park','double park','parked','debris'],  '[]', 61),
    ('parking',      'parking.sticker',     'Sticker or permit',     'low',    NULL, ARRAY['sticker','permit','pass','second car'],                   '[{"key":"vehicle_no","label":"Vehicle number","type":"text"}]', 62),
    ('parking',      'parking.charging',    'EV charging point',     'low',    NULL, ARRAY['charging','ev '],                                         '[]', 63),
    ('common',       'common.club',         'Clubhouse or gym',      'low',    NULL, ARRAY['clubhouse','gym','hall'],                                 '[]', 71),
    ('common',       'common.garden',       'Garden or play area',   'low',    NULL, ARRAY['garden','playground','lawn','tree'],                      '[]', 72),
    ('common',       'common.pool',         'Swimming pool',         'medium', NULL, ARRAY['pool','swim'],                                            '[]', 73)
  ) AS v(parent_key, key, label, prio, tm, kw, extra, ord)
  JOIN case_categories p ON p.org_id = o.id AND p.key = v.parent_key
ON CONFLICT (org_id, key) DO NOTHING;

-- ── two volunteer seats, held by Rajeswari and Venkatesh ────────────────────
WITH o AS (SELECT id FROM orgs WHERE slug = 'godrej-emerald')
INSERT INTO committee_positions (org_id, name, slug, kind, description, default_permissions)
SELECT o.id, v.name, v.slug, 'volunteer', v.descr, '{}'
  FROM o CROSS JOIN (VALUES
    ('Lift in-charge',                   'lift_incharge', 'Gets every lift complaint first. A resident volunteer, not on the committee.'),
    ('Lift level 2 (LiftCare liaison)',  'lift_level2',   'Kept in the loop on lift complaints and takes over when needed. In direct touch with the lift vendor.')
  ) AS v(name, slug, descr)
ON CONFLICT (org_id, name) DO NOTHING;

INSERT INTO committee_members (org_id, user_id, position_id, status, start_date)
SELECT p.org_id, u.id, p.id, 'active', CURRENT_DATE
  FROM committee_positions p
  JOIN users u ON u.org_id = p.org_id
 WHERE ((p.slug = 'lift_incharge' AND u.name = 'Rajeswari Batchu')
     OR (p.slug = 'lift_level2'   AND u.name = 'Venkatesh Batchu'))
   AND NOT EXISTS (SELECT 1 FROM committee_members m WHERE m.position_id = p.id AND m.status = 'active');

-- ── routing rules ───────────────────────────────────────────────────────────
INSERT INTO routing_rules (org_id, name, category_id, assign_position_id, backup_position_id, sort_order)
SELECT o.id, 'Lift issues', cat.id, seat1.id, seat2.id, 10
  FROM orgs o
  JOIN case_categories cat ON cat.org_id = o.id AND cat.key = 'lift'
  JOIN committee_positions seat1 ON seat1.org_id = o.id AND seat1.slug = 'lift_incharge'
  JOIN committee_positions seat2 ON seat2.org_id = o.id AND seat2.slug = 'lift_level2'
 WHERE o.slug = 'godrej-emerald'
   AND NOT EXISTS (SELECT 1 FROM routing_rules r WHERE r.org_id = o.id AND r.name = 'Lift issues');

INSERT INTO admin_events (org_id, actor_label, area, action, summary)
SELECT o.id, 'migration godrej_002_seed.sql', 'routing', 'seed',
       'Created starter categories, the Lift in-charge and Lift level 2 seats, and the routing rule for lifts'
  FROM orgs o
 WHERE o.slug = 'godrej-emerald'
   AND NOT EXISTS (SELECT 1 FROM admin_events e WHERE e.org_id = o.id AND e.actor_label = 'migration godrej_002_seed.sql');

COMMIT;
