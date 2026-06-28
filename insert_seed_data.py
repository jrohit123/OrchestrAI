import asyncio
import sys
import uuid
from datetime import datetime, date
sys.path.insert(0, 'd:\\Orchestrator AI')

from app.db import init_db, execute, close_db

async def insert_seed_data():
    await init_db()
    org_id = '11111111-0000-0000-0000-000000000001'
    
    print("Inserting seed data...")
    
    # ── CUSTOMERS ──────────────────────────────────────────────────────────────
    print("Inserting customers...")
    
    customers = [
        ('cc111111-0000-0000-0000-000000000001', 'Mehta Enterprises', '+912222222210', '27MEHTE1111A1ZX', 'Pune', 350000.00),
        ('cc111111-0000-0000-0000-000000000002', 'Mehta Diamond Palace', '+912222222211', '27MEHTD2222A1ZX', 'Nagpur', 250000.00),
        ('cc111111-0000-0000-0000-000000000003', 'Mehta & Sons Jewellers', '+912222222212', '27MEHTS3333A1ZX', 'Nashik', 180000.00),
        ('cc111111-0000-0000-0000-000000000004', 'Sharma Ornaments', '+912222222213', '07SHARMO4444B1ZP', 'Jaipur', 220000.00),
        ('cc111111-0000-0000-0000-000000000005', 'Sharma Fine Jewels', '+912222222214', '07SHARFJ5555B1ZP', 'Lucknow', 175000.00),
        ('cc111111-0000-0000-0000-000000000006', 'Jain Gold Works', '+912222222215', '08JAINGG6666C1ZQ', 'Ahmedabad', 300000.00),
        ('cc111111-0000-0000-0000-000000000007', 'Gupta Jewellery House', '+912222222216', '09GUPTAJ7777D1ZR', 'Bhopal', 120000.00),
        ('cc111111-0000-0000-0000-000000000008', 'Singh Bullion Mart', '+912222222217', '03SINGBM8888E1ZS', 'Amritsar', 450000.00),
        ('cc111111-0000-0000-0000-000000000009', 'Desai Gold & Silver', '+912222222218', '24DESAIG9999F1ZT', 'Vadodara', 90000.00),
        ('cc111111-0000-0000-0000-000000000010', 'Reddy Jewellery Shoppe', '+912222222219', '36REDDYJ0000G1ZU', 'Hyderabad', 275000.00),
    ]
    
    for cust in customers:
        await execute(
            "INSERT INTO customers (id, org_id, name, phone, gst_number, city, credit_limit) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            cust[0], org_id, cust[1], cust[2], cust[3], cust[4], cust[5]
        )
    
    print(f"Inserted {len(customers)} customers")
    
    # ── INVOICES ──────────────────────────────────────────────────────────────
    print("Inserting invoices...")
    
    invoices = [
        # PAID
        (uuid.uuid4(), 'INV-101', 'cc111111-0000-0000-0000-000000000001', 92000.00, 'paid', date.fromisoformat('2026-05-10'), datetime.fromisoformat('2026-04-25 10:00:00+05:30')),
        (uuid.uuid4(), 'INV-102', 'cc111111-0000-0000-0000-000000000004', 47500.00, 'paid', date.fromisoformat('2026-05-15'), datetime.fromisoformat('2026-04-30 11:00:00+05:30')),
        (uuid.uuid4(), 'INV-103', 'cc111111-0000-0000-0000-000000000006', 138000.00, 'paid', date.fromisoformat('2026-05-20'), datetime.fromisoformat('2026-05-05 09:00:00+05:30')),
        (uuid.uuid4(), 'INV-104', 'cc111111-0000-0000-0000-000000000006', 65000.00, 'paid', date.fromisoformat('2026-05-25'), datetime.fromisoformat('2026-05-10 14:00:00+05:30')),
        (uuid.uuid4(), 'INV-105', 'cc111111-0000-0000-0000-000000000008', 210000.00, 'paid', date.fromisoformat('2026-06-01'), datetime.fromisoformat('2026-05-17 10:00:00+05:30')),
        # PENDING
        (uuid.uuid4(), 'INV-201', 'cc111111-0000-0000-0000-000000000001', 145000.00, 'pending', date.fromisoformat('2026-07-10'), datetime.fromisoformat('2026-06-10 10:00:00+05:30')),
        (uuid.uuid4(), 'INV-202', 'cc111111-0000-0000-0000-000000000002', 88000.00, 'pending', date.fromisoformat('2026-07-15'), datetime.fromisoformat('2026-06-15 11:00:00+05:30')),
        (uuid.uuid4(), 'INV-203', 'cc111111-0000-0000-0000-000000000003', 52000.00, 'pending', date.fromisoformat('2026-07-20'), datetime.fromisoformat('2026-06-20 09:00:00+05:30')),
        (uuid.uuid4(), 'INV-204', 'cc111111-0000-0000-0000-000000000004', 73000.00, 'pending', date.fromisoformat('2026-07-05'), datetime.fromisoformat('2026-06-05 14:00:00+05:30')),
        (uuid.uuid4(), 'INV-205', 'cc111111-0000-0000-0000-000000000005', 39000.00, 'pending', date.fromisoformat('2026-07-25'), datetime.fromisoformat('2026-06-25 10:00:00+05:30')),
        (uuid.uuid4(), 'INV-206', 'cc111111-0000-0000-0000-000000000006', 185000.00, 'pending', date.fromisoformat('2026-07-30'), datetime.fromisoformat('2026-06-27 10:00:00+05:30')),
        (uuid.uuid4(), 'INV-207', 'cc111111-0000-0000-0000-000000000007', 28000.00, 'pending', date.fromisoformat('2026-07-08'), datetime.fromisoformat('2026-06-08 11:00:00+05:30')),
        (uuid.uuid4(), 'INV-208', 'cc111111-0000-0000-0000-000000000009', 44000.00, 'pending', date.fromisoformat('2026-07-12'), datetime.fromisoformat('2026-06-12 09:00:00+05:30')),
        (uuid.uuid4(), 'INV-209', 'cc111111-0000-0000-0000-000000000010', 97000.00, 'pending', date.fromisoformat('2026-07-18'), datetime.fromisoformat('2026-06-18 14:00:00+05:30')),
        (uuid.uuid4(), 'INV-210', 'cc111111-0000-0000-0000-000000000005', 62000.00, 'pending', date.fromisoformat('2026-07-22'), datetime.fromisoformat('2026-06-22 10:00:00+05:30')),
        # OVERDUE
        (uuid.uuid4(), 'INV-301', 'cc111111-0000-0000-0000-000000000001', 230000.00, 'overdue', date.fromisoformat('2026-05-01'), datetime.fromisoformat('2026-04-01 10:00:00+05:30')),
        (uuid.uuid4(), 'INV-302', 'cc111111-0000-0000-0000-000000000002', 115000.00, 'overdue', date.fromisoformat('2026-04-15'), datetime.fromisoformat('2026-03-16 11:00:00+05:30')),
        (uuid.uuid4(), 'INV-303', 'cc111111-0000-0000-0000-000000000004', 78000.00, 'overdue', date.fromisoformat('2026-05-20'), datetime.fromisoformat('2026-04-20 09:00:00+05:30')),
        (uuid.uuid4(), 'INV-304', 'cc111111-0000-0000-0000-000000000008', 340000.00, 'overdue', date.fromisoformat('2026-04-30'), datetime.fromisoformat('2026-03-31 14:00:00+05:30')),
        (uuid.uuid4(), 'INV-305', 'cc111111-0000-0000-0000-000000000007', 55000.00, 'overdue', date.fromisoformat('2026-06-01'), datetime.fromisoformat('2026-05-02 10:00:00+05:30')),
        (uuid.uuid4(), 'INV-306', 'cc111111-0000-0000-0000-000000000003', 92000.00, 'overdue', date.fromisoformat('2026-05-10'), datetime.fromisoformat('2026-04-10 10:00:00+05:30')),
        # DRAFT
        (uuid.uuid4(), 'INV-401', 'cc111111-0000-0000-0000-000000000010', 128000.00, 'draft', date.fromisoformat('2026-07-27'), datetime.fromisoformat('2026-06-27 10:00:00+05:30')),
        (uuid.uuid4(), 'INV-402', 'cc111111-0000-0000-0000-000000000005', 49000.00, 'draft', date.fromisoformat('2026-07-28'), datetime.fromisoformat('2026-06-27 11:00:00+05:30')),
        (uuid.uuid4(), 'INV-403', 'cc111111-0000-0000-0000-000000000009', 33000.00, 'draft', date.fromisoformat('2026-07-29'), datetime.fromisoformat('2026-06-27 14:00:00+05:30')),
        (uuid.uuid4(), 'INV-404', 'cc111111-0000-0000-0000-000000000006', 76000.00, 'draft', date.fromisoformat('2026-07-30'), datetime.fromisoformat('2026-06-27 15:00:00+05:30')),
    ]
    
    for inv in invoices:
        await execute(
            "INSERT INTO invoices (id, org_id, invoice_number, customer_id, amount, status, due_date, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            inv[0], org_id, inv[1], inv[2], inv[3], inv[4], inv[5], inv[6]
        )
    
    print(f"Inserted {len(invoices)} invoices")
    
    # ── ORDERS ────────────────────────────────────────────────────────────────
    print("Inserting orders...")
    
    user_id = '3164c542-ccc6-4de9-bcd8-bb8e03d35de3'
    
    orders = [
        # CONFIRMED
        (uuid.uuid4(), 'ORD-1003', 'cc111111-0000-0000-0000-000000000001', 'Mehta Enterprises', '22kt gold bangle set, 45g', '22kt', 285000.00, 'confirmed', '[{"status":"confirmed","updated_at":"2026-06-20T08:00:00+00:00","updated_by":"3164c542-ccc6-4de9-bcd8-bb8e03d35de3"}]'),
        (uuid.uuid4(), 'ORD-1004', 'cc111111-0000-0000-0000-000000000004', 'Sharma Ornaments', '18kt diamond pendant set, 12g', '18kt', 95000.00, 'confirmed', '[{"status":"confirmed","updated_at":"2026-06-22T08:00:00+00:00","updated_by":"3164c542-ccc6-4de9-bcd8-bb8e03d35de3"}]'),
        (uuid.uuid4(), 'ORD-1005', 'cc111111-0000-0000-0000-000000000006', 'Jain Gold Works', '22kt gold chain, 30g', '22kt', 190000.00, 'confirmed', '[{"status":"confirmed","updated_at":"2026-06-24T08:00:00+00:00","updated_by":"3164c542-ccc6-4de9-bcd8-bb8e03d35de3"}]'),
        # IN PRODUCTION
        (uuid.uuid4(), 'ORD-1006', 'cc111111-0000-0000-0000-000000000002', 'Mehta Diamond Palace', '22kt gold necklace with ruby, 60g', '22kt', 390000.00, 'in_production', '[{"status":"confirmed","updated_at":"2026-06-15T08:00:00+00:00"},{"status":"in_production","updated_at":"2026-06-17T08:00:00+00:00"}]'),
        (uuid.uuid4(), 'ORD-1007', 'cc111111-0000-0000-0000-000000000006', 'Jain Gold Works', 'silver anklet pair, 80g', 'silver', 42000.00, 'in_production', '[{"status":"confirmed","updated_at":"2026-06-18T08:00:00+00:00"},{"status":"in_production","updated_at":"2026-06-20T08:00:00+00:00"}]'),
        (uuid.uuid4(), 'ORD-1008', 'cc111111-0000-0000-0000-000000000008', 'Singh Bullion Mart', '22kt gold coin set, 100g', '22kt', 640000.00, 'in_production', '[{"status":"confirmed","updated_at":"2026-06-10T08:00:00+00:00"},{"status":"in_production","updated_at":"2026-06-12T08:00:00+00:00"}]'),
        # QUALITY CHECK
        (uuid.uuid4(), 'ORD-1009', 'cc111111-0000-0000-0000-000000000003', 'Mehta & Sons Jewellers', '22kt gold earrings set, 18g', '22kt', 115000.00, 'quality_check', '[{"status":"confirmed","updated_at":"2026-06-05T08:00:00+00:00"},{"status":"in_production","updated_at":"2026-06-07T08:00:00+00:00"},{"status":"quality_check","updated_at":"2026-06-22T08:00:00+00:00"}]'),
        (uuid.uuid4(), 'ORD-1010', 'cc111111-0000-0000-0000-000000000009', 'Desai Gold & Silver', '18kt gold bracelet, 22g', '18kt', 78000.00, 'quality_check', '[{"status":"confirmed","updated_at":"2026-06-08T08:00:00+00:00"},{"status":"in_production","updated_at":"2026-06-10T08:00:00+00:00"},{"status":"quality_check","updated_at":"2026-06-24T08:00:00+00:00"}]'),
        # READY
        (uuid.uuid4(), 'ORD-1011', 'cc111111-0000-0000-0000-000000000005', 'Sharma Fine Jewels', '22kt gold mangalsutra, 25g', '22kt', 158000.00, 'ready', '[{"status":"confirmed"},{"status":"in_production"},{"status":"quality_check"},{"status":"ready","updated_at":"2026-06-26T08:00:00+00:00"}]'),
        (uuid.uuid4(), 'ORD-1012', 'cc111111-0000-0000-0000-000000000005', 'Sharma Fine Jewels', '14kt gold ring with solitaire, 8g', '14kt', 195000.00, 'ready', '[{"status":"confirmed"},{"status":"in_production"},{"status":"quality_check"},{"status":"ready","updated_at":"2026-06-26T10:00:00+00:00"}]'),
        (uuid.uuid4(), 'ORD-1013', 'cc111111-0000-0000-0000-000000000010', 'Reddy Jewellery Shoppe', '22kt gold bangle, 35g', '22kt', 221000.00, 'ready', '[{"status":"confirmed"},{"status":"in_production"},{"status":"quality_check"},{"status":"ready","updated_at":"2026-06-25T08:00:00+00:00"}]'),
        # DELIVERED
        (uuid.uuid4(), 'ORD-1014', 'cc111111-0000-0000-0000-000000000001', 'Mehta Enterprises', '22kt gold necklace set, 55g', '22kt', 345000.00, 'delivered', '[{"status":"confirmed"},{"status":"in_production"},{"status":"quality_check"},{"status":"ready"},{"status":"delivered","updated_at":"2026-06-20T08:00:00+00:00"}]'),
        (uuid.uuid4(), 'ORD-1015', 'cc111111-0000-0000-0000-000000000007', 'Gupta Jewellery House', 'silver payal with bells, 60g', 'silver', 28000.00, 'delivered', '[{"status":"confirmed"},{"status":"in_production"},{"status":"quality_check"},{"status":"ready"},{"status":"delivered","updated_at":"2026-06-23T08:00:00+00:00"}]'),
    ]
    
    for ord in orders:
        await execute(
            "INSERT INTO orders (id, org_id, order_number, customer_id, customer_name, description, metal_type, estimated_amount, status, status_history, created_by) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)",
            ord[0], org_id, ord[1], ord[2], ord[3], ord[4], ord[5], ord[6], ord[7], ord[8], user_id
        )
    
    print(f"Inserted {len(orders)} orders")
    
    print("Seed data insertion complete!")
    await close_db()

if __name__ == "__main__":
    asyncio.run(insert_seed_data())
