-- Migration: Add workflow intelligence columns
-- Removes hardcoded domain knowledge from codebase
-- All domain intelligence now lives in workflow records

-- Add new columns to workflows table
ALTER TABLE workflows
  ADD COLUMN IF NOT EXISTS workflow_type varchar(20) NOT NULL DEFAULT 'action',
  ADD COLUMN IF NOT EXISTS training_phrases jsonb NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS entity_schema jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS sql_template text,
  ADD COLUMN IF NOT EXISTS sql_params_order jsonb NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS response_format varchar(50) NOT NULL DEFAULT 'generic',
  ADD COLUMN IF NOT EXISTS business_glossary jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS llm_system_prompt text;

-- Migrate existing data: mark all current workflows as 'action' type
UPDATE workflows SET workflow_type = 'action' WHERE workflow_type IS NULL OR workflow_type = 'action';

-- Add check constraint
ALTER TABLE workflows ADD CONSTRAINT workflow_type_check
  CHECK (workflow_type IN ('action', 'read'));

-- Index for fast loading of org workflows
CREATE INDEX IF NOT EXISTS idx_workflows_org_type
  ON workflows (org_id, workflow_type, is_active);
