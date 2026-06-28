# Seed Data, Test Queries, PDF System & Write Operations Guide

---

## PART 1 — Seed Data SQL

Run this entire block against your database.
Existing rows are skipped with ON CONFLICT — safe to re-run.

### 1A — New Customers (10 rows)

Three extra Mehtas, two extra Sharmas, five new names across different cities.
This creates realistic disambiguation scenarios for testing.

```sql
-- ── EXTRA MEHTAS ──────────────────────────────────────────────────────────────
INSERT INTO customers (id, org_id, name, phone, gst_number, city, credit_limit)
VALUES ('cc111111-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001',
        'Mehta Enterprises', '+912222222210', '27MEHTE1111A1ZX', 'Pune', 350000.00)
ON CONFLICT (org_id, phone) DO NOTHING;

INSERT INTO customers (id, org_id, name, phone, gst_number, city, credit_limit)
VALUES ('cc111111-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001',
        'Mehta Diamond Palace', '+912222222211', '27MEHTD2222A1ZX', 'Nagpur', 250000.00)
ON CONFLICT (org_id, phone) DO NOTHING;

INSERT INTO customers (id, org_id, name, phone, gst_number, city, credit_limit)
VALUES ('cc111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000001',
        'Mehta & Sons Jewellers', '+912222222212', '27MEHTS3333A1ZX', 'Nashik', 180000.00)
ON CONFLICT (org_id, phone) DO NOTHING;

-- ── EXTRA SHARMAS ─────────────────────────────────────────────────────────────
INSERT INTO customers (id, org_id, name, phone, gst_number, city, credit_limit)
VALUES ('cc111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000001',
        'Sharma Ornaments', '+912222222213', '07SHARMO4444B1ZP', 'Jaipur', 220000.00)
ON CONFLICT (org_id, phone) DO NOTHING;

INSERT INTO customers (id, org_id, name, phone, gst_number, city, credit_limit)
VALUES ('cc111111-0000-0000-0000-000000000005', '11111111-0000-0000-0000-000000000001',
        'Sharma Fine Jewels', '+912222222214', '07SHARFJ5555B1ZP', 'Lucknow', 175000.00)
ON CONFLICT (org_id, phone) DO NOTHING;

-- ── NEW NAMES ─────────────────────────────────────────────────────────────────
INSERT INTO customers (id, org_id, name, phone, gst_number, city, credit_limit)
VALUES ('cc111111-0000-0000-0000-000000000006', '11111111-0000-0000-0000-000000000001',
        'Jain Gold Works', '+912222222215', '08JAINGG6666C1ZQ', 'Ahmedabad', 300000.00)
ON CONFLICT (org_id, phone) DO NOTHING;

INSERT INTO customers (id, org_id, name, phone, gst_number, city, credit_limit)
VALUES ('cc111111-0000-0000-0000-000000000007', '11111111-0000-0000-0000-000000000001',
        'Gupta Jewellery House', '+912222222216', '09GUPTAJ7777D1ZR', 'Bhopal', 120000.00)
ON CONFLICT (org_id, phone) DO NOTHING;

INSERT INTO customers (id, org_id, name, phone, gst_number, city, credit_limit)
VALUES ('cc111111-0000-0000-0000-000000000008', '11111111-0000-0000-0000-000000000001',
        'Singh Bullion Mart', '+912222222217', '03SINGBM8888E1ZS', 'Amritsar', 450000.00)
ON CONFLICT (org_id, phone) DO NOTHING;

INSERT INTO customers (id, org_id, name, phone, gst_number, city, credit_limit)
VALUES ('cc111111-0000-0000-0000-000000000009', '11111111-0000-0000-0000-000000000001',
        'Desai Gold & Silver', '+912222222218', '24DESAIG9999F1ZT', 'Vadodara', 90000.00)
ON CONFLICT (org_id, phone) DO NOTHING;

INSERT INTO customers (id, org_id, name, phone, gst_number, city, credit_limit)
VALUES ('cc111111-0000-0000-0000-000000000010', '11111111-0000-0000-0000-000000000001',
        'Reddy Jewellery Shoppe', '+912222222219', '36REDDYJ0000G1ZU', 'Hyderabad', 275000.00)
ON CONFLICT (org_id, phone) DO NOTHING;
```

---

### 1B — New Invoices (25 rows, all statuses, all customers)

Covers: paid, pending, overdue, draft — across old and new customers.
Due dates are deliberately spread across past and future to create realistic aging.

```sql
-- ── PAID INVOICES (closed, historical) ───────────────────────────────────────
INSERT INTO invoices (id, org_id, invoice_number, customer_id, amount, status, due_date, created_at)
VALUES
  ('ii000001-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001',
   'INV-101', '0c9db436-2164-4bc7-b77d-c5112f7da2fa', -- Mehta Jewellers
   92000.00, 'paid', '2026-05-10', '2026-04-25 10:00:00+05:30'),

  ('ii000001-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001',
   'INV-102', '48947061-ac86-46b1-8d44-32026b3ddefc', -- Sharma Gold House
   47500.00, 'paid', '2026-05-15', '2026-04-30 11:00:00+05:30'),

  ('ii000001-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000001',
   'INV-103', 'addc6b0e-395e-41e6-a68b-699fdd427fa8', -- Kapoor Trading Co
   138000.00, 'paid', '2026-05-20', '2026-05-05 09:00:00+05:30'),

  ('ii000001-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000001',
   'INV-104', 'cc111111-0000-0000-0000-000000000006', -- Jain Gold Works
   65000.00, 'paid', '2026-05-25', '2026-05-10 14:00:00+05:30'),

  ('ii000001-0000-0000-0000-000000000005', '11111111-0000-0000-0000-000000000001',
   'INV-105', 'cc111111-0000-0000-0000-000000000008', -- Singh Bullion Mart
   210000.00, 'paid', '2026-06-01', '2026-05-17 10:00:00+05:30')
ON CONFLICT (org_id, invoice_number) DO NOTHING;

-- ── PENDING INVOICES (sent, awaiting payment) ─────────────────────────────────
INSERT INTO invoices (id, org_id, invoice_number, customer_id, amount, status, due_date, created_at)
VALUES
  ('ii000002-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001',
   'INV-201', 'cc111111-0000-0000-0000-000000000001', -- Mehta Enterprises
   145000.00, 'pending', '2026-07-10', '2026-06-10 10:00:00+05:30'),

  ('ii000002-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001',
   'INV-202', 'cc111111-0000-0000-0000-000000000002', -- Mehta Diamond Palace
   88000.00, 'pending', '2026-07-15', '2026-06-15 11:00:00+05:30'),

  ('ii000002-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000001',
   'INV-203', 'cc111111-0000-0000-0000-000000000003', -- Mehta & Sons
   52000.00, 'pending', '2026-07-20', '2026-06-20 09:00:00+05:30'),

  ('ii000002-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000001',
   'INV-204', 'cc111111-0000-0000-0000-000000000004', -- Sharma Ornaments
   73000.00, 'pending', '2026-07-05', '2026-06-05 14:00:00+05:30'),

  ('ii000002-0000-0000-0000-000000000005', '11111111-0000-0000-0000-000000000001',
   'INV-205', 'cc111111-0000-0000-0000-000000000005', -- Sharma Fine Jewels
   39000.00, 'pending', '2026-07-25', '2026-06-25 10:00:00+05:30'),

  ('ii000002-0000-0000-0000-000000000006', '11111111-0000-0000-0000-000000000001',
   'INV-206', 'cc111111-0000-0000-0000-000000000006', -- Jain Gold Works
   185000.00, 'pending', '2026-07-30', '2026-06-27 10:00:00+05:30'),

  ('ii000002-0000-0000-0000-000000000007', '11111111-0000-0000-0000-000000000001',
   'INV-207', 'cc111111-0000-0000-0000-000000000007', -- Gupta Jewellery House
   28000.00, 'pending', '2026-07-08', '2026-06-08 11:00:00+05:30'),

  ('ii000002-0000-0000-0000-000000000008', '11111111-0000-0000-0000-000000000001',
   'INV-208', 'cc111111-0000-0000-0000-000000000009', -- Desai Gold & Silver
   44000.00, 'pending', '2026-07-12', '2026-06-12 09:00:00+05:30'),

  ('ii000002-0000-0000-0000-000000000009', '11111111-0000-0000-0000-000000000001',
   'INV-209', 'cc111111-0000-0000-0000-000000000010', -- Reddy Jewellery
   97000.00, 'pending', '2026-07-18', '2026-06-18 14:00:00+05:30'),

  ('ii000002-0000-0000-0000-000000000010', '11111111-0000-0000-0000-000000000001',
   'INV-210', '0e3e78c5-811d-49d4-98e9-fe5540219542', -- Patel Fine Jewellery
   62000.00, 'pending', '2026-07-22', '2026-06-22 10:00:00+05:30')
ON CONFLICT (org_id, invoice_number) DO NOTHING;

-- ── OVERDUE INVOICES (past due date, not paid) ────────────────────────────────
INSERT INTO invoices (id, org_id, invoice_number, customer_id, amount, status, due_date, created_at)
VALUES
  ('ii000003-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001',
   'INV-301', 'cc111111-0000-0000-0000-000000000001', -- Mehta Enterprises
   230000.00, 'overdue', '2026-05-01', '2026-04-01 10:00:00+05:30'),

  ('ii000003-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001',
   'INV-302', 'cc111111-0000-0000-0000-000000000002', -- Mehta Diamond Palace
   115000.00, 'overdue', '2026-04-15', '2026-03-16 11:00:00+05:30'),

  ('ii000003-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000001',
   'INV-303', 'cc111111-0000-0000-0000-000000000004', -- Sharma Ornaments
   78000.00, 'overdue', '2026-05-20', '2026-04-20 09:00:00+05:30'),

  ('ii000003-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000001',
   'INV-304', 'cc111111-0000-0000-0000-000000000008', -- Singh Bullion Mart
   340000.00, 'overdue', '2026-04-30', '2026-03-31 14:00:00+05:30'),

  ('ii000003-0000-0000-0000-000000000005', '11111111-0000-0000-0000-000000000001',
   'INV-305', 'cc111111-0000-0000-0000-000000000007', -- Gupta Jewellery House
   55000.00, 'overdue', '2026-06-01', '2026-05-02 10:00:00+05:30'),

  ('ii000003-0000-0000-0000-000000000006', '11111111-0000-0000-0000-000000000001',
   'INV-306', 'cc111111-0000-0000-0000-000000000003', -- Mehta & Sons
   92000.00, 'overdue', '2026-05-10', '2026-04-10 10:00:00+05:30')
ON CONFLICT (org_id, invoice_number) DO NOTHING;

-- ── DRAFT INVOICES (not yet sent) ─────────────────────────────────────────────
INSERT INTO invoices (id, org_id, invoice_number, customer_id, amount, status, due_date, created_at)
VALUES
  ('ii000004-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001',
   'INV-401', 'cc111111-0000-0000-0000-000000000010', -- Reddy Jewellery
   128000.00, 'draft', '2026-07-27', '2026-06-27 10:00:00+05:30'),

  ('ii000004-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001',
   'INV-402', 'cc111111-0000-0000-0000-000000000005', -- Sharma Fine Jewels
   49000.00, 'draft', '2026-07-28', '2026-06-27 11:00:00+05:30'),

  ('ii000004-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000001',
   'INV-403', 'cc111111-0000-0000-0000-000000000009', -- Desai Gold & Silver
   33000.00, 'draft', '2026-07-29', '2026-06-27 14:00:00+05:30'),

  ('ii000004-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000001',
   'INV-404', '8c61b172-ee38-4e0a-b0ac-4b791ab2c413', -- Agarwal Ornaments (existing)
   76000.00, 'draft', '2026-07-30', '2026-06-27 15:00:00+05:30')
ON CONFLICT (org_id, invoice_number) DO NOTHING;
```

---

### 1C — New Orders (15 rows, all statuses)

Covers every production stage across multiple customers including
duplicate-name customers so you can test "which Mehta's orders".

```sql
-- ── CONFIRMED (just placed, not started) ──────────────────────────────────────
INSERT INTO orders (id, org_id, order_number, customer_id, customer_name,
                    description, metal_type, estimated_amount, status, status_history, created_by)
VALUES
  ('oo000001-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001',
   'ORD-1003', 'cc111111-0000-0000-0000-000000000001', 'Mehta Enterprises',
   '22kt gold bangle set, 45g', '22kt', 285000.00, 'confirmed',
   '[{"status":"confirmed","updated_at":"2026-06-20T08:00:00+00:00","updated_by":"3164c542-ccc6-4de9-bcd8-bb8e03d35de3"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3'),

  ('oo000001-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001',
   'ORD-1004', 'cc111111-0000-0000-0000-000000000004', 'Sharma Ornaments',
   '18kt diamond pendant set, 12g', '18kt', 95000.00, 'confirmed',
   '[{"status":"confirmed","updated_at":"2026-06-22T08:00:00+00:00","updated_by":"3164c542-ccc6-4de9-bcd8-bb8e03d35de3"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3'),

  ('oo000001-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000001',
   'ORD-1005', 'cc111111-0000-0000-0000-000000000006', 'Jain Gold Works',
   '22kt gold chain, 30g', '22kt', 190000.00, 'confirmed',
   '[{"status":"confirmed","updated_at":"2026-06-24T08:00:00+00:00","updated_by":"3164c542-ccc6-4de9-bcd8-bb8e03d35de3"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3')
ON CONFLICT (org_id, order_number) DO NOTHING;

-- ── IN PRODUCTION ─────────────────────────────────────────────────────────────
INSERT INTO orders (id, org_id, order_number, customer_id, customer_name,
                    description, metal_type, estimated_amount, status, status_history, created_by)
VALUES
  ('oo000002-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001',
   'ORD-1006', 'cc111111-0000-0000-0000-000000000002', 'Mehta Diamond Palace',
   '22kt gold necklace with ruby, 60g', '22kt', 390000.00, 'in_production',
   '[{"status":"confirmed","updated_at":"2026-06-15T08:00:00+00:00"},{"status":"in_production","updated_at":"2026-06-17T08:00:00+00:00"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3'),

  ('oo000002-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001',
   'ORD-1007', '8c61b172-ee38-4e0a-b0ac-4b791ab2c413', 'Agarwal Ornaments',
   'silver anklet pair, 80g', 'silver', 42000.00, 'in_production',
   '[{"status":"confirmed","updated_at":"2026-06-18T08:00:00+00:00"},{"status":"in_production","updated_at":"2026-06-20T08:00:00+00:00"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3'),

  ('oo000002-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000001',
   'ORD-1008', 'cc111111-0000-0000-0000-000000000008', 'Singh Bullion Mart',
   '22kt gold coin set, 100g', '22kt', 640000.00, 'in_production',
   '[{"status":"confirmed","updated_at":"2026-06-10T08:00:00+00:00"},{"status":"in_production","updated_at":"2026-06-12T08:00:00+00:00"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3')
ON CONFLICT (org_id, order_number) DO NOTHING;

-- ── QUALITY CHECK ─────────────────────────────────────────────────────────────
INSERT INTO orders (id, org_id, order_number, customer_id, customer_name,
                    description, metal_type, estimated_amount, status, status_history, created_by)
VALUES
  ('oo000003-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001',
   'ORD-1009', 'cc111111-0000-0000-0000-000000000003', 'Mehta & Sons Jewellers',
   '22kt gold earrings set, 18g', '22kt', 115000.00, 'quality_check',
   '[{"status":"confirmed","updated_at":"2026-06-05T08:00:00+00:00"},{"status":"in_production","updated_at":"2026-06-07T08:00:00+00:00"},{"status":"quality_check","updated_at":"2026-06-22T08:00:00+00:00"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3'),

  ('oo000003-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001',
   'ORD-1010', 'cc111111-0000-0000-0000-000000000009', 'Desai Gold & Silver',
   '18kt gold bracelet, 22g', '18kt', 78000.00, 'quality_check',
   '[{"status":"confirmed","updated_at":"2026-06-08T08:00:00+00:00"},{"status":"in_production","updated_at":"2026-06-10T08:00:00+00:00"},{"status":"quality_check","updated_at":"2026-06-24T08:00:00+00:00"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3')
ON CONFLICT (org_id, order_number) DO NOTHING;

-- ── READY FOR DELIVERY ────────────────────────────────────────────────────────
INSERT INTO orders (id, org_id, order_number, customer_id, customer_name,
                    description, metal_type, estimated_amount, status, status_history, created_by)
VALUES
  ('oo000004-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001',
   'ORD-1011', 'cc111111-0000-0000-0000-000000000005', 'Sharma Fine Jewels',
   '22kt gold mangalsutra, 25g', '22kt', 158000.00, 'ready',
   '[{"status":"confirmed"},{"status":"in_production"},{"status":"quality_check"},{"status":"ready","updated_at":"2026-06-26T08:00:00+00:00"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3'),

  ('oo000004-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001',
   'ORD-1012', '0e3e78c5-811d-49d4-98e9-fe5540219542', 'Patel Fine Jewellery',
   '14kt gold ring with solitaire, 8g', '14kt', 195000.00, 'ready',
   '[{"status":"confirmed"},{"status":"in_production"},{"status":"quality_check"},{"status":"ready","updated_at":"2026-06-26T10:00:00+00:00"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3'),

  ('oo000004-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000001',
   'ORD-1013', 'cc111111-0000-0000-0000-000000000010', 'Reddy Jewellery Shoppe',
   '22kt gold bangle, 35g', '22kt', 221000.00, 'ready',
   '[{"status":"confirmed"},{"status":"in_production"},{"status":"quality_check"},{"status":"ready","updated_at":"2026-06-25T08:00:00+00:00"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3')
ON CONFLICT (org_id, order_number) DO NOTHING;

-- ── DELIVERED (completed) ─────────────────────────────────────────────────────
INSERT INTO orders (id, org_id, order_number, customer_id, customer_name,
                    description, metal_type, estimated_amount, status, status_history, created_by)
VALUES
  ('oo000005-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001',
   'ORD-1014', '0c9db436-2164-4bc7-b77d-c5112f7da2fa', 'Mehta Jewellers',
   '22kt gold necklace set, 55g', '22kt', 345000.00, 'delivered',
   '[{"status":"confirmed"},{"status":"in_production"},{"status":"quality_check"},{"status":"ready"},{"status":"delivered","updated_at":"2026-06-20T08:00:00+00:00"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3'),

  ('oo000005-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001',
   'ORD-1015', 'cc111111-0000-0000-0000-000000000007', 'Gupta Jewellery House',
   'silver payal with bells, 60g', 'silver', 28000.00, 'delivered',
   '[{"status":"confirmed"},{"status":"in_production"},{"status":"quality_check"},{"status":"ready"},{"status":"delivered","updated_at":"2026-06-23T08:00:00+00:00"}]'::jsonb,
   '3164c542-ccc6-4de9-bcd8-bb8e03d35de3')
ON CONFLICT (org_id, order_number) DO NOTHING;
```

---

## PART 2 — Test Queries

Run these in WhatsApp to verify the agent handles every category correctly.
Expected behaviour is noted for each group.

### Identity (no DB call needed)
```
who am i
what is my role
what can i ask you
what are my permissions
```
> Expected: Instant reply from system prompt. No tool call.

---

### Simple single-table reads
```
show me all customers
which city has the most customers
customers in Mumbai
customers with credit limit above 3 lakh
gold rate kya hai
22kt ka bhav batao
show me all metal rates
low stock items
kaun sa maal khatam ho raha hai
stock of gold necklace
18kt diamond bangle kitna bacha hai
```
> Expected: One query_database call, clean formatted response.

---

### Disambiguation — multiple Mehtas (clarify tool expected)
```
Mehta ka outstanding kitna hai
Mehta ke orders dikhao
Mehta ka invoice status
```
> Expected: Agent queries customers WHERE name ILIKE '%Mehta%',
> finds 4 rows, calls clarify tool with all four options.
> Do NOT skip this — it proves the disambiguation path works.

---

### Specific customer when full name given (no clarify)
```
Mehta Enterprises ka baaki kitna hai
Mehta Diamond Palace ke orders
Sharma Gold House ka outstanding
Singh Bullion Mart ke saare invoices
```
> Expected: Direct query, no clarify needed.

---

### All-Mehtas aggregate (user asks for all, not one)
```
show me all Mehta customers with their outstanding dues
which Mehta has the highest dues
all Mehtas ke orders kya chal rahe hain
compare all Sharma customers by outstanding
```
> Expected: Agent understands "all Mehtas" means GROUP BY, not
> single customer. Returns table of all matching names with totals.

---

### Invoice status queries
```
show me all overdue invoices
pending invoices above 1 lakh
all paid invoices from last month
draft invoices pending to be sent
invoices due this week
which customers have not paid yet
total outstanding across all customers
```
> Expected: Correct status filter, correct date logic, correct JOIN.

---

### Order pipeline queries
```
how many orders are in production right now
orders ready for delivery
kaun se orders quality check mein hain
ORD-1006 ka status kya hai
Mehta Diamond Palace ka order kahan tak pahuncha
all confirmed orders
orders that were delivered this month
```
> Expected: Correct status filter on orders table.

---

### Cross-table queries (LLM must JOIN)
```
customers with overdue invoices
which customers have both pending orders and pending invoices
show me Mehta Enterprises — all invoices and all orders
top 5 customers by total outstanding
customers in Delhi with any dues
Sharma customers — invoices and order status together
```
> Expected: LLM writes correct JOIN between invoices and customers.

---

### Aggregation and ranking
```
top 3 customers by credit limit
which customer has the most orders
average invoice amount
total value of all ready orders
how much is outstanding in Mumbai
which city owes the most
```
> Expected: GROUP BY, SUM/AVG, ORDER BY, correct numeric output.

---

### Multi-step — query + PDF
```
give me an invoice summary for all Mehta customers as PDF
Sharma aur Agarwal ka outstanding PDF mein do
generate aging report PDF
Singh Bullion Mart ke saare invoices PDF mein chahiye
all overdue invoices as a PDF report
ready orders ka PDF bana do
```
> Expected: Two tool calls — query_database first, then generate_pdf.
> PDF sent to WhatsApp. Response confirms title and row count.

---

### Write operations — confirm_action expected
```
create order for Jain Gold Works — 22kt gold ring 15g
new order Gupta Jewellery House diamond earrings
update ORD-1006 to quality check
mark ORD-1011 as delivered
```
> Expected: Agent calls confirm_action first.
> Shows summary of what will happen.
> Only executes after user replies "yes".

---

### Edge cases
```
show me invoices from 2025
orders above 5 lakh
customers with zero outstanding
items in Safe A-2
inventory sorted by price high to low
which items have unit price above 1 lakh
```
> Expected: Correct date/numeric filters. No hallucinated columns.

---

## PART 3 — Unified PDF System

### The design principle

Your current PDF system has three separate hardcoded generators:
`generate_invoice_pdf()`, `generate_dues_statement_pdf()`,
`generate_quotation_pdf()`. Each one knows exactly which columns
to render and how to lay them out. This is fine for those fixed
document types — invoices and quotations have regulatory formats
that must look a specific way.

But for flexible user-driven reports ("give me Mehta's invoices as PDF",
"aging report PDF", "stock report for 22kt items") you need one
generic renderer that takes any data and makes it presentable.

The architecture is:

```
User request
    ↓
Agent queries DB (fresh SQL for whatever user asked)
    ↓
Agent calls generate_pdf(rows, title, subtitle, pdf_type)
    ↓
pdf_type router decides which renderer to use:
  "invoice"    → existing generate_invoice_pdf()   (regulatory format)
  "quotation"  → existing generate_quotation_pdf() (regulatory format)
  "dues"       → existing generate_dues_statement_pdf() (regulatory format)
  "report"     → _generate_generic_pdf()           (flexible, any data)
    ↓
PDF bytes → send_document() → WhatsApp
```

The key insight: regulatory documents (invoice, quotation) stay
hardcoded because they MUST look a certain way legally. Everything
else goes through the generic renderer.

---

### Change 1 — Add pdf_type to the generate_pdf tool

In `agent.py`, update the generate_pdf tool definition to include
a `pdf_type` parameter:

```python
{
    "type": "function",
    "function": {
        "name": "generate_pdf",
        "description": (
            "Generate a PDF from query results and send it to the user. "
            "Use ONLY when the user explicitly asks for a PDF, report, or statement. "
            "Call query_database first to get the data, then call this. "
            "pdf_type options: 'report' for any general report or summary, "
            "'dues' for customer outstanding statement, "
            "'invoice' for a specific invoice document."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "description": "The data rows to include in the PDF"
                },
                "title": {
                    "type": "string",
                    "description": "PDF title shown at the top"
                },
                "subtitle": {
                    "type": "string",
                    "description": "Optional subtitle, date range, or customer name"
                },
                "pdf_type": {
                    "type": "string",
                    "enum": ["report", "dues", "invoice"],
                    "description": "report = generic table, dues = outstanding statement, invoice = invoice doc"
                }
            },
            "required": ["rows", "title"]
        }
    }
}
```

---

### Change 2 — Update _execute_tool for generate_pdf

Replace the generate_pdf block in `_execute_tool()` in `agent.py`:

```python
elif tool_name == "generate_pdf":
    from app.services.pdf_service import (
        _generate_generic_pdf,
        generate_dues_statement_pdf
    )
    from app.services.whatsapp import send_document

    rows     = tool_input.get("rows", [])
    title    = tool_input.get("title", "Report")
    subtitle = tool_input.get("subtitle", "")
    pdf_type = tool_input.get("pdf_type", "report")

    if not rows:
        return "ERROR: No data to generate PDF from"

    try:
        org_row  = await fetch_one(
            "SELECT name FROM orgs WHERE id = $1", user["org_id"]
        )
        org_name = org_row["name"] if org_row else user["org_name"]

        if pdf_type == "dues":
            # Structured dues statement — uses the existing formal renderer
            # Expects rows to have: name/customer_name, invoice_number,
            # amount, status, due_date
            total     = sum(float(r.get("amount", 0) or 0) for r in rows)
            overdue   = sum(
                float(r.get("amount", 0) or 0)
                for r in rows
                if str(r.get("status", "")).lower() == "overdue"
            )
            cust_name = (
                rows[0].get("customer_name")
                or rows[0].get("name")
                or title
            )
            pdf_bytes = generate_dues_statement_pdf(
                customer_name=cust_name,
                customer_city=rows[0].get("city", ""),
                customer_gstin=rows[0].get("gst_number", ""),
                invoices=rows,
                total_outstanding=total,
                overdue_total=overdue,
                org_name=org_name
            )
        else:
            # Generic report — works for any data shape
            pdf_bytes = _generate_generic_pdf(
                title=title,
                subtitle=subtitle,
                rows=rows,
                org_name=org_name
            )

        filename = f"{title.replace(' ', '_')[:40]}.pdf"
        await send_document(
            to=phone,
            pdf_bytes=pdf_bytes,
            filename=filename,
            caption=f"📄 {title}"
        )
        return f"PDF_SENT: {title} ({len(rows)} rows)"

    except Exception as e:
        return f"ERROR generating PDF: {str(e)}"
```

---

### Change 3 — Add _generate_generic_pdf to pdf_service.py

Add this function at the bottom of `pdf_service.py`.
It renders any data the agent returns — no hardcoded column names.

```python
def _generate_generic_pdf(
    title: str,
    rows: list,
    org_name: str = "",
    subtitle: str = ""
) -> bytes:
    """
    Universal PDF renderer. Accepts any rows, any columns.
    Column headers derived from dict keys — no hardcoding.
    """
    pdf = InvoicePDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(14, 14, 14)

    from datetime import datetime
    today = datetime.now()
    W = 182
    L = 14

    # ── Header ────────────────────────────────────────────────────
    pdf.set_xy(L, 14)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*BLUE)
    pdf.cell(W, 9, org_name, align="L")

    pdf.set_xy(L, 24)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*DARKTEXT)
    pdf.cell(W, 8, title, align="L")

    if subtitle:
        pdf.set_xy(L, 33)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(W, 5, subtitle, align="L")

    pdf.set_xy(L, 39)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(W, 5,
             f"Generated: {today.strftime('%d %b %Y  %I:%M %p')}",
             align="R")

    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.8)
    pdf.line(L, 46, L + W, 46)
    pdf.set_line_width(0.2)

    if not rows:
        pdf.set_xy(L, 56)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*MUTED)
        pdf.cell(W, 8, "No data found.", align="C")
        return bytes(pdf.output())

    # ── Derive columns from data (skip internal IDs) ──────────────
    skip_cols = {"id", "org_id", "created_by", "updated_by",
                 "otp_hash", "config", "customer_id", "role_id"}
    cols = [k for k in rows[0].keys() if k not in skip_cols]
    if not cols:
        cols = list(rows[0].keys())

    # ── Column widths ─────────────────────────────────────────────
    col_w    = W // len(cols)
    leftover = W - col_w * len(cols)

    y = 52
    # Table header row
    pdf.set_xy(L, y)
    pdf.set_fill_color(*BLUE)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 8)
    for i, col in enumerate(cols):
        w     = col_w + (leftover if i == len(cols) - 1 else 0)
        label = col.replace("_", " ").title()[:20]
        pdf.cell(w, 8, label, fill=True, align="L", border=0)
    pdf.ln(8)

    # Data rows
    row_fill = False
    for row in rows:
        pdf.set_fill_color(*LIGHTBG) if row_fill else pdf.set_fill_color(*WHITE)
        pdf.set_text_color(*DARKTEXT)
        pdf.set_font("Helvetica", "", 8)
        for i, col in enumerate(cols):
            w   = col_w + (leftover if i == len(cols) - 1 else 0)
            val = str(row.get(col, "") or "")
            # Format money columns nicely
            try:
                if any(x in col for x in
                       ("amount","total","price","limit","rate","charges","subtotal")):
                    if row.get(col) is not None:
                        val = f"\u20b9{float(row[col]):,.0f}"
            except (ValueError, TypeError):
                pass
            pdf.cell(w, 7, val[:30], fill=True, align="L", border=0)
        pdf.ln(7)
        row_fill = not row_fill

    # Footer row count
    pdf.set_xy(L, pdf.get_y() + 6)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(W, 5, f"Total records: {len(rows)}", align="R")

    return bytes(pdf.output())
```

---

### How the PDF system handles each user scenario

**"Sharma aur Agarwal ka invoice summary PDF mein do"**

Agent steps:
1. `query_database` → `SELECT c.name, i.invoice_number, i.amount, i.status, i.due_date FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.org_id = $1 AND c.name ILIKE ANY(ARRAY['%Sharma%','%Agarwal%']) ORDER BY c.name`
2. `generate_pdf(rows, "Invoice Summary — Sharma & Agarwal", pdf_type="report")`
3. PDF sent. Generic renderer shows all columns neatly.

**"Generate dues statement for Mehta Jewellers"**

Agent steps:
1. `query_database` → invoices for Mehta Jewellers where status IN (pending, overdue)
2. `generate_pdf(rows, "Dues Statement — Mehta Jewellers", pdf_type="dues")`
3. Formal dues statement PDF sent using `generate_dues_statement_pdf()`.

**"All overdue invoices as PDF"**

Agent steps:
1. `query_database` → all invoices + customer names where status = overdue
2. `generate_pdf(rows, "Overdue Invoices Report", subtitle="As of 27 Jun 2026", pdf_type="report")`
3. Generic report PDF with all rows.

**"Ready orders PDF"**

Agent steps:
1. `query_database` → orders WHERE status = ready
2. `generate_pdf(rows, "Orders Ready for Delivery", pdf_type="report")`
3. Generic PDF showing order numbers, customer names, items, amounts.

**"Low stock items PDF"**

Agent steps:
1. `query_database` → inventory WHERE qty <= reorder_level
2. `generate_pdf(rows, "Low Stock Alert", subtitle="Items below reorder level", pdf_type="report")`
3. Generic PDF with SKU, name, qty, reorder_level columns.

---

## PART 4 — Write Operations: What Needs a Workflow and What Doesn't

### The clear rule

A write operation needs a **workflow record** only when it involves
one or more of: OTP verification, multi-party approval, or a
scheduled/recurring trigger.

Everything else — simple writes that just need user confirmation
before executing — are handled by the agent's `confirm_action` tool
followed by calling the existing adapter directly.

---

### Category A — Agent handles directly (no workflow record needed)

These use `confirm_action` → user says yes → agent calls adapter:

| User says | What agent does |
|-----------|----------------|
| "create order for Jain Gold Works, 22kt ring 15g" | confirm_action → orders.create_order() |
| "update ORD-1006 to quality check" | confirm_action → orders.update_order_status() |
| "mark ORD-1011 as delivered" | confirm_action → orders.update_order_status() |
| "add new customer Verma Jewels, Mumbai" | confirm_action → INSERT into customers |

For these, the agent flow in `agent.py` already handles them via
`confirm_action`. When user replies "yes", the webhook's
`pending_confirm` handler re-runs the agent with `confirmed=True`
in user context. The agent then calls the appropriate adapter.

To enable this cleanly, add this check inside `_execute_tool()`
for the `confirm_action` handler — store the pending action
in the session so the webhook can resume it:

```python
elif tool_name == "confirm_action":
    action_desc = tool_input.get("action_description", "")
    details     = tool_input.get("details", {})

    lines = [f"⚠️ *Confirm Action*\n\n{action_desc}"]
    if details:
        for k, v in details.items():
            lines.append(f"  • {k}: {v}")
    lines.append("\nReply *yes* to confirm or *no* to cancel.")

    # Signal to the caller that we need to pause here
    return "CONFIRM_PENDING:" + json.dumps({
        "description": action_desc,
        "details": details
    })
```

---

### Category B — Workflow record needed (OTP or approval)

These three cases genuinely need a workflow entry in the DB:

**1. create_invoice with OTP threshold**
Amounts above the OTP threshold (e.g. ₹50,000) require
OTP verification before the invoice is created.
This is already implemented in `workflow_executor.py`.
Keep it exactly as-is.

**2. create_invoice with approval threshold**
Amounts above the approval threshold (e.g. ₹1,00,000) require
the owner to tap Approve in WhatsApp.
Already implemented. Keep as-is.

**3. scheduled dues report**
The `manage_schedule` intent triggers a cron job.
This needs a workflow record with `is_scheduled=true`.
Already implemented. Keep as-is.

---

### Category C — Quotation generation (agent + existing adapter)

Quotation generation is interesting because it involves:
1. Looking up item details (from inventory by SKU or name)
2. Fetching current metal rate
3. Calculating the quote
4. Generating the formal quotation PDF
5. Sending it

The agent handles steps 1–2 via `query_database`. For steps 3–5
it calls the existing `create_quotation()` adapter. No new workflow
needed — the adapter already handles calculation and PDF generation.

Example:
```
User: "quote for Sharma Fine Jewels, 22kt ring, SKU 22kt-gold-ring"
```

Agent:
1. `query_database` → gets SKU details from inventory (weight, unit_price)
2. `query_database` → gets current 22kt rate from pricing table
3. Calls `confirm_action` showing: customer, item, weight, rate, calculated total
4. User says yes
5. Agent calls existing `create_quotation()` with extracted params
6. PDF generated and sent

This works today with the current codebase — no changes needed.

---

## PART 5 — System Prompt Addition for Write Operations

Add this block to `_build_system_prompt()` in `agent.py`,
after the existing RULES section:

```python
WRITE OPERATIONS — HOW TO HANDLE THEM:
- For creating orders: collect customer name, item description,
  metal type. Call confirm_action showing full summary. On user
  confirmation, the webhook will re-invoke you with confirmed=True.
  Then call orders.create_order via the execute_adapter tool.
- For updating order status: confirm the order number and new status,
  call confirm_action, then execute.
- For creating invoices: ALWAYS check the amount. If above the OTP
  threshold stored in the workflows table, do NOT proceed — tell the
  user "This amount requires OTP verification — please send 'invoice
  [customer] [amount]' and the OTP system will handle it."
- For adding new customers: collect name, city, phone, credit limit.
  confirm_action first.
- NEVER call UPDATE, INSERT, DELETE, or DROP directly in query_database.
  query_database is SELECT only.
```

---

## Summary of What This Document Covers

| # | What | Status |
|---|------|--------|
| 1 | 10 new customers with duplicate Mehta/Sharma names | SQL ready above |
| 2 | 5 paid invoices across customers | SQL ready above |
| 3 | 10 pending invoices across all customers | SQL ready above |
| 4 | 6 overdue invoices with past due dates | SQL ready above |
| 5 | 4 draft invoices | SQL ready above |
| 6 | 3 confirmed orders | SQL ready above |
| 7 | 3 in-production orders | SQL ready above |
| 8 | 2 quality-check orders | SQL ready above |
| 9 | 3 ready-for-delivery orders | SQL ready above |
| 10 | 2 delivered orders | SQL ready above |
| 11 | 50+ test queries across all categories | Listed above |
| 12 | Unified PDF system with pdf_type routing | Code above |
| 13 | _generate_generic_pdf() function | Code above |
| 14 | generate_pdf tool updated with pdf_type param | Code above |
| 15 | Write operations — what needs workflow vs what doesn't | Explained above |
| 16 | System prompt addition for write operations | Code above |
