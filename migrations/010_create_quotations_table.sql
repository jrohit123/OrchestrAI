-- Create quotations table for storing actual quotation records
-- Similar structure to invoices table for consistency

CREATE TABLE quotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    quotation_number VARCHAR(50) UNIQUE NOT NULL,
    customer_id UUID NOT NULL,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    total_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    valid_until DATE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by UUID,
    updated_at TIMESTAMP,
    CONSTRAINT fk_quotations_org FOREIGN KEY (org_id) REFERENCES orgs(id) ON DELETE CASCADE,
    CONSTRAINT fk_quotations_customer FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    CONSTRAINT fk_quotations_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

-- Indexes for performance
CREATE INDEX idx_quotations_org_id ON quotations(org_id);
CREATE INDEX idx_quotations_customer_id ON quotations(customer_id);
CREATE INDEX idx_quotations_status ON quotations(status);
CREATE INDEX idx_quotations_quotation_number ON quotations(quotation_number);

-- Comment
COMMENT ON TABLE quotations IS 'Stores price quotation records with items, similar to invoices table';
COMMENT ON COLUMN quotations.items IS 'Array of line items with description, qty, unit_price, gst, total';
COMMENT ON COLUMN quotations.status IS 'draft, sent, accepted, rejected, expired';
