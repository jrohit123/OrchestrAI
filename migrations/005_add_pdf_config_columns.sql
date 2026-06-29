-- Migration: Add pdf_config and response_template columns to workflows table
-- Enables workflow-driven PDF formatting and WhatsApp response templates

ALTER TABLE workflows
  ADD COLUMN IF NOT EXISTS pdf_config jsonb DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS response_template text DEFAULT NULL;

COMMENT ON COLUMN workflows.pdf_config IS
  'PDF formatting instructions: doc_type, title_template, aging_analysis, show_key_insights, insight_focus';

COMMENT ON COLUMN workflows.response_template IS
  'WhatsApp response format template with {variable} placeholders';
