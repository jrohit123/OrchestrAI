-- Migration: Backfill items for seeded invoices
-- Uses amount as GST-inclusive total, back-calculates subtotal at 3% GST
-- This fixes empty items arrays that cause Tax Invoice PDFs to show no line items

UPDATE invoices
SET items = jsonb_build_array(jsonb_build_object(
    'description', CASE invoice_number
        WHEN 'INV-301' THEN '22kt Gold Necklace Set, 45g'
        WHEN 'INV-302' THEN '22kt Gold Bangle Set, 30g'
        WHEN 'INV-303' THEN '18kt Diamond Pendant Set, 12g'
        WHEN 'INV-304' THEN '22kt Gold Necklace with Ruby, 60g'
        WHEN 'INV-305' THEN '14kt Gold Ring with Solitaire, 8g'
        WHEN 'INV-306' THEN '22kt Gold Earrings Set, 18g'
        WHEN 'INV-201' THEN '22kt Gold Mangalsutra, 25g'
        WHEN 'INV-202' THEN '22kt Gold Chain, 30g'
        WHEN 'INV-203' THEN 'Silver Payal with Bells, 60g'
        WHEN 'INV-204' THEN '18kt Diamond Pendant, 10g'
        WHEN 'INV-205' THEN '22kt Gold Ring, Plain Band, 6g'
        WHEN 'INV-206' THEN '22kt Gold Bangle, Traditional Round, 40g'
        WHEN 'INV-207' THEN '14kt Gold Ring with Diamond Cut, 8g'
        WHEN 'INV-208' THEN 'Silver Anklet, Bell Design, 50g'
        WHEN 'INV-209' THEN '22kt Gold Bangle, 35g'
        WHEN 'INV-210' THEN '22kt Gold Necklace, Heritage Set, 28g'
        ELSE 'Jewellery As Per Order'
    END,
    'qty', 1,
    'unit_price', ROUND(amount / 1.03, 2)::numeric,
    'gst', ROUND(amount - amount / 1.03, 2)::numeric,
    'total', amount
))
WHERE org_id = '11111111-0000-0000-0000-000000000001'
  AND (items = '[]'::jsonb OR items IS NULL)
  AND status NOT IN ('draft');  -- leave draft invoices alone
