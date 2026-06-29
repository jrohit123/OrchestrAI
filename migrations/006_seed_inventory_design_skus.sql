-- Migration: Seed inventory with design SKUs for quotation workflow
-- Adds jewellery designs with proper SKU codes for the quotation system

INSERT INTO inventory (org_id, sku, name, qty, location, reorder_level, unit_price)
VALUES
-- 22kt Gold designs (rate: Rs.7,000/g base)
('11111111-0000-0000-0000-000000000001', 'GC-22K-001', '22kt Gold Chain — Classic Box Link',        8,  'Design Vault A1', 2, 7000.00),
('11111111-0000-0000-0000-000000000001', 'GN-22K-001', '22kt Gold Necklace — Heritage Kundan Set',  4,  'Design Vault A2', 1, 7000.00),
('11111111-0000-0000-0000-000000000001', 'GB-22K-001', '22kt Gold Bangle — Traditional Round',      10, 'Design Vault A3', 2, 7000.00),
('11111111-0000-0000-0000-000000000001', 'GE-22K-001', '22kt Gold Earrings — Jhumka Tops',         12, 'Design Vault A4', 3, 7000.00),
('11111111-0000-0000-0000-000000000001', 'GM-22K-001', '22kt Gold Mangalsutra — South Style',       6,  'Design Vault A5', 1, 7000.00),
-- 18kt Gold designs (rate: Rs.5,800/g base)
('11111111-0000-0000-0000-000000000001', 'GP-18K-001', '18kt Gold Pendant — Leaf Motif',            7,  'Design Vault B1', 1, 5800.00),
('11111111-0000-0000-0000-000000000001', 'GR-18K-001', '18kt Gold Ring — Diamond Cut Band',         15, 'Design Vault B2', 3, 5800.00),
('11111111-0000-0000-0000-000000000001', 'DP-18K-001', '18kt Diamond Pendant — Solitaire Round',    4,  'Design Vault B3', 1, 5800.00),
('11111111-0000-0000-0000-000000000001', 'DB-18K-001', '18kt Diamond Bangle — Eternity Band',       3,  'Design Vault B4', 1, 5800.00),
-- 14kt Gold designs (rate: Rs.4,800/g base)
('11111111-0000-0000-0000-000000000001', 'DC-14K-001', '14kt Diamond Chain — Tennis Style',         5,  'Design Vault C1', 1, 4800.00),
('11111111-0000-0000-0000-000000000001', 'GR-14K-001', '14kt Gold Ring — Solitaire Setting',        8,  'Design Vault C2', 2, 4800.00),
-- Silver designs (rate: Rs.750/g base)
('11111111-0000-0000-0000-000000000001', 'SA-SLV-001', 'Silver Anklet — Ghungroo Bell Design',      20, 'Display Rack 1',  5, 750.00),
('11111111-0000-0000-0000-000000000001', 'SC-SLV-001', 'Silver Chain — Box Link 60cm',              18, 'Display Rack 2',  5, 680.00),
('11111111-0000-0000-0000-000000000001', 'SP-SLV-001', 'Silver Payal — Traditional Ghungroo',       14, 'Display Rack 3',  3, 720.00),
('11111111-0000-0000-0000-000000000001', 'SR-SLV-001', 'Silver Ring — Plain Band with Engraving',   25, 'Display Rack 4',  5, 620.00)
ON CONFLICT (org_id, sku) DO NOTHING;
