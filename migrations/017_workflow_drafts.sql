-- Migration 017: Workflow drafts table for conversational builder
-- workflow_drafts = in-progress authoring sessions (never read by message-time code)
-- workflows = live only (what the bot reads on every message)

CREATE TABLE IF NOT EXISTS workflow_drafts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    intent_key      TEXT,               -- null until admin confirms the name
    status          VARCHAR(20) NOT NULL DEFAULT 'chatting'
                        CHECK (status IN ('chatting','ready_for_review','published','abandoned')),

    -- Raw conversational inputs collected during chat
    purpose         TEXT,
    workflow_type   VARCHAR(20),
    raw_fields      JSONB DEFAULT '[]',         -- plain-language fields mentioned
    business_rules  TEXT,                       -- "OTP above 50000, approval above 1 lakh"
    pdf_sample_analysis JSONB,                  -- output of pdf_template_extractor

    -- Compiled output (filled by compile_and_summarize)
    name            TEXT,
    description     TEXT,
    training_phrases JSONB DEFAULT '[]',
    entity_schema   JSONB DEFAULT '{}',
    calc_rules      JSONB DEFAULT '{}',
    steps           JSONB DEFAULT '[]',
    sql_template    TEXT,
    sql_params_order JSONB DEFAULT '[]',
    response_format VARCHAR(50),
    business_glossary JSONB DEFAULT '{}',
    llm_system_prompt TEXT,
    pdf_config      JSONB,
    response_template TEXT,
    otp_required    BOOLEAN DEFAULT false,
    otp_threshold   NUMERIC(12,2),
    approval_threshold NUMERIC(12,2),

    -- Plain English summary shown to admin before publish
    plain_english_summary TEXT,

    -- Chat history stored server-side (not round-tripped through browser)
    chat_history    JSONB DEFAULT '[]',

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_workflow_drafts_org_status ON workflow_drafts(org_id, status);
CREATE INDEX idx_workflow_drafts_org_updated ON workflow_drafts(org_id, updated_at DESC);
