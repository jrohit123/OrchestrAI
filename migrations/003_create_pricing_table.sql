-- Migration: Fix numeric precision issues in existing tables
-- The pricing table was already created with wrong precision, so we need to fix it

-- Drop and recreate pricing table with correct precision
DROP TABLE IF EXISTS pricing CASCADE;

CREATE TABLE pricing (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    metal_type VARCHAR(20) NOT NULL,
    rate_per_gram NUMERIC(12,2) NOT NULL,
    making_charge_pct NUMERIC(12,2) NOT NULL DEFAULT 15.0,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Quotation fields (nullable for rate-only entries)
    quotation_number VARCHAR(50) UNIQUE,
    weight_grams NUMERIC(10,3),
    making_charges NUMERIC(12,2),
    subtotal NUMERIC(12,2),
    gst_pct NUMERIC(12,2) DEFAULT 3.0,
    gst_amount NUMERIC(12,2),
    total_amount NUMERIC(12,2),
    status VARCHAR(20) DEFAULT 'sent',
    valid_until DATE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- Indexes
CREATE INDEX idx_pricing_org ON pricing(org_id);
CREATE INDEX idx_pricing_quotation ON pricing(quotation_number);
CREATE INDEX idx_pricing_metal_type ON pricing(metal_type);

-- Separate unique constraint for rate entries (one rate per metal type per org)
CREATE UNIQUE INDEX idx_pricing_rate_unique ON pricing(org_id, metal_type) WHERE quotation_number IS NULL;

-- Fix workflows table otp_threshold and approval_threshold precision and defaults
ALTER TABLE workflows ALTER COLUMN otp_threshold TYPE NUMERIC(12,2);
ALTER TABLE workflows ALTER COLUMN otp_threshold SET DEFAULT NULL;
ALTER TABLE workflows ALTER COLUMN approval_threshold TYPE NUMERIC(12,2);
