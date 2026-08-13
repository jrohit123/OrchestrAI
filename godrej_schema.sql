-- ============================================================
-- GODREJ EMERALD — OrchestrAI Database Schema
-- Run this on the new Railway Postgres instance
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ── ENGINE TABLES (identical to Baanganga — do not modify) ──

CREATE TABLE "orgs" (
  "id" uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  "name" text NOT NULL,
  "slug" text NOT NULL CONSTRAINT "orgs_slug_key" UNIQUE,
  "industry" text,
  "plan" text DEFAULT 'trial',
  "is_active" boolean DEFAULT true,
  "created_at" timestamptz DEFAULT now(),
  "session_ttl_minutes" integer DEFAULT 480,
  "gst_rate" numeric(5,2) DEFAULT NULL,
  "context_message_limit" integer DEFAULT 12 NOT NULL,
  "settings" jsonb DEFAULT '{}' NOT NULL,
  "default_making_charge_pct" numeric(5,2) DEFAULT NULL
);

CREATE TABLE "roles" (
  "id" uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "name" text NOT NULL,
  "permissions" text[] DEFAULT '{}',
  "created_at" timestamptz DEFAULT now(),
  "readable_tables" text[] DEFAULT '{}' NOT NULL,
  CONSTRAINT "roles_org_id_name_key" UNIQUE("org_id","name")
);

CREATE TABLE "users" (
  "id" uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "role_id" uuid REFERENCES roles(id),
  "name" text NOT NULL,
  "phone" text,
  "email" text NOT NULL,
  "channel" text DEFAULT 'telegram',
  "is_active" boolean DEFAULT true,
  "created_at" timestamptz DEFAULT now(),
  CONSTRAINT "users_org_id_phone_key" UNIQUE("org_id","phone")
);

CREATE TABLE "credentials" (
  "id" uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "adapter_name" text NOT NULL,
  "config" jsonb DEFAULT '{}',
  "created_at" timestamptz DEFAULT now(),
  CONSTRAINT "credentials_org_id_adapter_name_key" UNIQUE("org_id","adapter_name")
);

CREATE TABLE "workflows" (
  "id" uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "intent_key" text NOT NULL,
  "name" text NOT NULL,
  "steps" jsonb DEFAULT '[]',
  "is_active" boolean DEFAULT true,
  "otp_required" boolean DEFAULT false,
  "otp_threshold" numeric(12,2),
  "version" integer DEFAULT 1,
  "last_run" timestamptz,
  "created_at" timestamptz DEFAULT now(),
  "is_scheduled" boolean DEFAULT false,
  "schedule_cron" text,
  "scheduled_by" uuid,
  "approval_threshold" numeric(12,2),
  "description" text,
  "workflow_type" varchar(20) DEFAULT 'action' NOT NULL,
  "training_phrases" jsonb DEFAULT '[]' NOT NULL,
  "entity_schema" jsonb DEFAULT '{}' NOT NULL,
  "sql_template" text,
  "sql_params_order" jsonb DEFAULT '[]' NOT NULL,
  "response_format" varchar(50) DEFAULT 'generic' NOT NULL,
  "business_glossary" jsonb DEFAULT '{}' NOT NULL,
  "llm_system_prompt" text,
  "pdf_config" jsonb,
  "response_template" text,
  "calc_rules" jsonb DEFAULT '{}',
  "slash_command" varchar(32),
  "command_description" varchar(80),
  "menu_section" varchar(30) DEFAULT 'other' NOT NULL,
  CONSTRAINT "workflows_org_id_intent_key_key" UNIQUE("org_id","intent_key"),
  CONSTRAINT "workflow_type_check" CHECK (workflow_type IN ('action','read'))
);

CREATE TABLE "workflow_drafts" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "intent_key" text,
  "status" varchar(20) DEFAULT 'chatting' NOT NULL,
  "purpose" text,
  "workflow_type" varchar(20),
  "raw_fields" jsonb DEFAULT '[]',
  "business_rules" text,
  "pdf_sample_analysis" jsonb,
  "name" text,
  "description" text,
  "training_phrases" jsonb DEFAULT '[]',
  "entity_schema" jsonb DEFAULT '{}',
  "calc_rules" jsonb DEFAULT '{}',
  "steps" jsonb DEFAULT '[]',
  "sql_template" text,
  "sql_params_order" jsonb DEFAULT '[]',
  "response_format" varchar(50),
  "business_glossary" jsonb DEFAULT '{}',
  "llm_system_prompt" text,
  "pdf_config" jsonb,
  "response_template" text,
  "otp_required" boolean DEFAULT false,
  "otp_threshold" numeric(12,2),
  "approval_threshold" numeric(12,2),
  "plain_english_summary" text,
  "chat_history" jsonb DEFAULT '[]',
  "created_at" timestamptz DEFAULT now(),
  "updated_at" timestamptz DEFAULT now(),
  "slash_command" varchar(32),
  "command_description" varchar(80),
  "menu_section" varchar(30),
  "published_workflow_id" uuid REFERENCES workflows(id) ON DELETE SET NULL,
  "granted_roles" text[] DEFAULT '{}',
  CONSTRAINT "workflow_drafts_status_check" CHECK (status IN ('chatting','ready_for_review','published','abandoned'))
);

CREATE TABLE "user_drafts" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "user_id" uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  "intent_key" text NOT NULL,
  "fields" jsonb DEFAULT '{}' NOT NULL,
  "stage" varchar(30) DEFAULT 'collecting' NOT NULL,
  "conversation_summary" text,
  "updated_at" timestamptz DEFAULT now() NOT NULL,
  "expires_at" timestamptz DEFAULT (now() + interval '24 hours') NOT NULL,
  CONSTRAINT "user_drafts_stage_check" CHECK (stage IN ('collecting','awaiting_confirmation','awaiting_otp','awaiting_approval','done','cancelled')),
  CONSTRAINT "one_active_draft_per_user" UNIQUE("org_id","user_id")
);

CREATE TABLE "otp_tokens" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "user_id" uuid NOT NULL REFERENCES users(id),
  "otp_hash" text NOT NULL,
  "action_context" jsonb,
  "expires_at" timestamptz NOT NULL,
  "used" boolean DEFAULT false,
  "attempts" integer DEFAULT 0,
  "created_at" timestamptz DEFAULT now(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE
);

CREATE TABLE "pending_approvals" (
  "id" uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "workflow_id" uuid REFERENCES workflows(id),
  "requester_id" uuid REFERENCES users(id),
  "approver_role" text NOT NULL,
  "intent_key" text NOT NULL,
  "context" jsonb DEFAULT '{}',
  "status" text DEFAULT 'pending',
  "decided_by" uuid REFERENCES users(id),
  "decided_at" timestamptz,
  "created_at" timestamptz DEFAULT now()
);

CREATE TABLE "audit_log" (
  "id" uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "user_id" uuid REFERENCES users(id) ON DELETE SET NULL,
  "intent_key" text,
  "tier" integer,
  "input_text" text,
  "outcome" text,
  "otp_used" boolean DEFAULT false,
  "steps_taken" jsonb DEFAULT '[]',
  "created_at" timestamptz DEFAULT now(),
  "due_date" date,
  "pdf_url" text
);

CREATE TABLE "scheduled_reports" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "user_id" uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  "phone" text NOT NULL,
  "email" text,
  "query_text" text NOT NULL,
  "report_label" text NOT NULL,
  "schedule_type" varchar(20) NOT NULL,
  "interval_minutes" integer,
  "hour" integer,
  "minute" integer DEFAULT 0,
  "day_of_week" varchar(10),
  "day_of_month" integer,
  "delivery" varchar(20) DEFAULT 'whatsapp' NOT NULL,
  "is_active" boolean DEFAULT true NOT NULL,
  "last_run_at" timestamptz,
  "next_run_at" timestamptz NOT NULL,
  "run_count" integer DEFAULT 0,
  "created_at" timestamptz DEFAULT now(),
  CONSTRAINT "scheduled_reports_delivery_check" CHECK (delivery IN ('whatsapp','email','both')),
  CONSTRAINT "scheduled_reports_schedule_type_check" CHECK (schedule_type IN ('minutely','hourly','daily','weekly','monthly'))
);

-- ── DOMAIN TABLES (Godrej Emerald — Housing Society) ──

CREATE TABLE "complaint_cases" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "case_number" text NOT NULL,
  "complainant_id" uuid REFERENCES users(id) ON DELETE SET NULL,
  "complaint_title" text NOT NULL,
  "complaint_description" text,
  "status" varchar(20) DEFAULT 'reported' NOT NULL,
  "priority" varchar(10) DEFAULT 'medium',
  "animal_type" text,
  "incident_location" text,
  "assigned_to_id" uuid REFERENCES users(id) ON DELETE SET NULL,
  "created_at" timestamptz DEFAULT now(),
  "closed_at" timestamptz,
  CONSTRAINT "complaint_cases_org_case_number_key" UNIQUE("org_id","case_number"),
  CONSTRAINT "complaint_cases_status_check" CHECK (status IN ('reported','under_review','action_taken','closed')),
  CONSTRAINT "complaint_cases_priority_check" CHECK (priority IN ('critical','high','medium','low'))
);

CREATE TABLE "case_comments" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "case_id" uuid NOT NULL REFERENCES complaint_cases(id) ON DELETE CASCADE,
  "user_id" uuid REFERENCES users(id) ON DELETE SET NULL,
  "comment" text NOT NULL,
  "created_at" timestamptz DEFAULT now()
);

CREATE TABLE "case_evidence" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id" uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  "case_id" uuid NOT NULL REFERENCES complaint_cases(id) ON DELETE CASCADE,
  "evidence_type" varchar(20),
  "file_url" text,
  "description" text,
  "uploaded_by" uuid REFERENCES users(id) ON DELETE SET NULL,
  "created_at" timestamptz DEFAULT now()
);

-- ── INDEXES ──

CREATE INDEX idx_audit_org_id ON audit_log(org_id);
CREATE INDEX idx_audit_created ON audit_log(org_id, created_at);
CREATE INDEX idx_users_org_id ON users(org_id);
CREATE INDEX idx_users_phone ON users(phone);
CREATE INDEX idx_otp_user_expiry ON otp_tokens(user_id, expires_at);
CREATE INDEX idx_otp_org ON otp_tokens(org_id);
CREATE INDEX idx_approvals_org_status ON pending_approvals(org_id, status);
CREATE INDEX idx_approvals_org_requester ON pending_approvals(org_id, requester_id);
CREATE INDEX idx_workflows_org_intent ON workflows(org_id, intent_key);
CREATE INDEX idx_workflows_org_type ON workflows(org_id, workflow_type, is_active);
CREATE INDEX idx_workflow_drafts_org_status ON workflow_drafts(org_id, status);
CREATE INDEX idx_workflow_drafts_org_updated ON workflow_drafts(org_id, updated_at);
CREATE INDEX idx_scheduled_reports_org ON scheduled_reports(org_id);
CREATE INDEX idx_scheduled_reports_user ON scheduled_reports(user_id);
CREATE INDEX idx_scheduled_reports_next_run ON scheduled_reports(next_run_at, is_active);
CREATE INDEX idx_cases_org ON complaint_cases(org_id);
CREATE INDEX idx_cases_org_status ON complaint_cases(org_id, status);
CREATE INDEX idx_cases_complainant ON complaint_cases(complainant_id);
CREATE INDEX idx_cases_assigned ON complaint_cases(assigned_to_id);
CREATE INDEX idx_comments_case ON case_comments(case_id);
CREATE INDEX idx_evidence_case ON case_evidence(case_id);
