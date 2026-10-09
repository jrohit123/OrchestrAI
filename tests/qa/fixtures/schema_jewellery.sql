--
-- PostgreSQL database dump
--

\restrict 0MDhyJidIVcu6Dp0CMco8rlQpIVsSez9WYgChYzocUX2DFNGhonkbfPAh1bUa8s

-- Dumped from database version 18.6
-- Dumped by pg_dump version 18.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: uuid_generate_v7(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.uuid_generate_v7() RETURNS uuid
    LANGUAGE plpgsql
    AS $$
DECLARE
  unix_ts_ms bytea;
  uuid_bytes bytea;
BEGIN
  unix_ts_ms := substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3 FOR 6);

  uuid_bytes := unix_ts_ms || gen_random_bytes(10);

  uuid_bytes := set_byte(uuid_bytes, 6, (get_byte(uuid_bytes, 6) & 15) | 112);
  uuid_bytes := set_byte(uuid_bytes, 8, (get_byte(uuid_bytes, 8) & 63) | 128);

  RETURN encode(uuid_bytes, 'hex')::uuid;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: admin_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    actor_user_id uuid,
    actor_label text,
    area text NOT NULL,
    action text NOT NULL,
    target_type text,
    target_id text,
    summary text NOT NULL,
    before_state jsonb,
    after_state jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: archived_rows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.archived_rows (
    id bigint NOT NULL,
    source_table text NOT NULL,
    row_id text,
    org_id uuid,
    row_data jsonb NOT NULL,
    reason text,
    archived_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: archived_rows_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.archived_rows_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: archived_rows_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.archived_rows_id_seq OWNED BY public.archived_rows.id;


--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    user_id uuid,
    intent_key text,
    tier integer,
    input_text text,
    outcome text,
    otp_used boolean DEFAULT false,
    steps_taken jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    due_date date,
    pdf_url text,
    response_text text,
    session_id text
);


--
-- Name: credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credentials (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    adapter_name text NOT NULL,
    config jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: customers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customers (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    phone text,
    email text,
    gst_number text,
    city text,
    credit_limit numeric(12,2) DEFAULT '0'::numeric,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: inventory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    sku text NOT NULL,
    name text NOT NULL,
    qty integer DEFAULT 0 NOT NULL,
    location text,
    reorder_level integer DEFAULT 50,
    unit_price numeric(12,2),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: invoices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invoices (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    invoice_number text NOT NULL,
    customer_id uuid,
    created_by uuid,
    items jsonb DEFAULT '[]'::jsonb,
    amount numeric(12,2) NOT NULL,
    status text DEFAULT 'draft'::text,
    due_date date,
    paid_at timestamp with time zone,
    pdf_url text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orders (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    order_number text NOT NULL,
    quotation_id uuid,
    customer_id uuid,
    customer_name text NOT NULL,
    description text NOT NULL,
    metal_type character varying(20),
    weight_estimate numeric(8,3),
    estimated_amount numeric(12,2),
    advance_paid numeric(12,2) DEFAULT '0'::numeric,
    status character varying(30) DEFAULT 'confirmed'::character varying,
    status_history jsonb DEFAULT '[]'::jsonb,
    expected_delivery date,
    notes text,
    created_by uuid,
    status_updated_at timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: orgs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orgs (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    industry text,
    plan text DEFAULT 'trial'::text,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    session_ttl_minutes integer DEFAULT 480,
    gst_rate numeric(5,2) DEFAULT 3.0,
    context_message_limit integer DEFAULT 12 NOT NULL,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL,
    default_making_charge_pct numeric(5,2) DEFAULT 12.00,
    otp_expiry_minutes integer DEFAULT 3 NOT NULL,
    otp_max_attempts integer DEFAULT 3 NOT NULL,
    otp_length integer DEFAULT 4 NOT NULL,
    otp_resend_cooldown_seconds integer DEFAULT 60 NOT NULL,
    logo_url text,
    timezone text DEFAULT 'Asia/Kolkata'::text NOT NULL,
    locale text DEFAULT 'en-IN'::text NOT NULL
);


--
-- Name: otp_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.otp_tokens (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    user_id uuid NOT NULL,
    otp_hash text NOT NULL,
    action_context jsonb,
    expires_at timestamp with time zone NOT NULL,
    used boolean DEFAULT false,
    attempts integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    org_id uuid NOT NULL
);


--
-- Name: pending_approvals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pending_approvals (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    workflow_id uuid,
    requester_id uuid,
    approver_role text NOT NULL,
    intent_key text NOT NULL,
    context jsonb DEFAULT '{}'::jsonb,
    status text DEFAULT 'pending'::text,
    decided_by uuid,
    decided_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    gate_id text,
    level integer DEFAULT 1 NOT NULL
);


--
-- Name: prompts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prompts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    key text NOT NULL,
    scope text DEFAULT 'tenant'::text NOT NULL,
    scope_ref text DEFAULT ''::text NOT NULL,
    version integer NOT NULL,
    body text NOT NULL,
    variables jsonb DEFAULT '[]'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by text,
    CONSTRAINT prompts_scope_check CHECK ((scope = ANY (ARRAY['global'::text, 'pack'::text, 'tenant'::text]))),
    CONSTRAINT prompts_version_check CHECK ((version >= 1))
);


--
-- Name: quotations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotations (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    quotation_number character varying(50) NOT NULL,
    customer_id uuid NOT NULL,
    items jsonb DEFAULT '[]'::jsonb NOT NULL,
    total_amount numeric(12,2) DEFAULT '0'::numeric NOT NULL,
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    valid_until date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by uuid,
    updated_at timestamp with time zone
);


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    permissions text[] DEFAULT '{}'::text[],
    created_at timestamp with time zone DEFAULT now(),
    readable_tables text[] DEFAULT '{}'::text[] NOT NULL,
    is_approver boolean DEFAULT false NOT NULL,
    approval_max_amount numeric(12,2),
    readable_entity_types text[] DEFAULT '{}'::text[] NOT NULL
);


--
-- Name: scheduled_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_reports (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    user_id uuid NOT NULL,
    phone text NOT NULL,
    email text,
    query_text text NOT NULL,
    report_label text NOT NULL,
    schedule_type character varying(20) NOT NULL,
    interval_minutes integer,
    hour integer,
    minute integer DEFAULT 0,
    day_of_week character varying(10),
    day_of_month integer,
    delivery character varying(20) DEFAULT 'whatsapp'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    last_run_at timestamp with time zone,
    next_run_at timestamp with time zone NOT NULL,
    run_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    source_key character varying(255) DEFAULT 'platform'::character varying,
    CONSTRAINT scheduled_reports_delivery_check CHECK (((delivery)::text = ANY (ARRAY[('whatsapp'::character varying)::text, ('email'::character varying)::text, ('both'::character varying)::text]))),
    CONSTRAINT scheduled_reports_schedule_type_check CHECK (((schedule_type)::text = ANY (ARRAY[('minutely'::character varying)::text, ('hourly'::character varying)::text, ('daily'::character varying)::text, ('weekly'::character varying)::text, ('monthly'::character varying)::text])))
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL,
    checksum text NOT NULL,
    applied_by text NOT NULL
);


--
-- Name: system_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    key text NOT NULL,
    locale text DEFAULT 'en-IN'::text NOT NULL,
    scope text DEFAULT 'tenant'::text NOT NULL,
    scope_ref text DEFAULT ''::text NOT NULL,
    version integer NOT NULL,
    body text NOT NULL,
    variables jsonb DEFAULT '[]'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by text,
    CONSTRAINT system_messages_scope_check CHECK ((scope = ANY (ARRAY['global'::text, 'pack'::text, 'tenant'::text]))),
    CONSTRAINT system_messages_version_check CHECK ((version >= 1))
);


--
-- Name: user_drafts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_drafts (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    user_id uuid NOT NULL,
    intent_key text NOT NULL,
    fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    stage character varying(30) DEFAULT 'collecting'::character varying NOT NULL,
    conversation_summary text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone DEFAULT (now() + '24:00:00'::interval) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT user_drafts_stage_check CHECK (((stage)::text = ANY (ARRAY[('collecting'::character varying)::text, ('awaiting_confirmation'::character varying)::text, ('awaiting_otp'::character varying)::text, ('awaiting_approval'::character varying)::text, ('done'::character varying)::text, ('cancelled'::character varying)::text])))
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    role_id uuid,
    name text NOT NULL,
    phone text,
    email text,
    channel text DEFAULT 'whatsapp'::text,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: workflow_drafts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_drafts (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    intent_key text,
    status character varying(20) DEFAULT 'chatting'::character varying NOT NULL,
    purpose text,
    workflow_type character varying(20),
    raw_fields jsonb DEFAULT '[]'::jsonb,
    business_rules text,
    pdf_sample_analysis jsonb,
    name text,
    description text,
    training_phrases jsonb DEFAULT '[]'::jsonb,
    entity_schema jsonb DEFAULT '{}'::jsonb,
    calc_rules jsonb DEFAULT '{}'::jsonb,
    steps jsonb DEFAULT '[]'::jsonb,
    sql_template text,
    sql_params_order jsonb DEFAULT '[]'::jsonb,
    response_format character varying(50),
    business_glossary jsonb DEFAULT '{}'::jsonb,
    llm_system_prompt text,
    pdf_config jsonb,
    response_template text,
    otp_required boolean DEFAULT false,
    otp_threshold numeric(12,2),
    approval_threshold numeric(12,2),
    plain_english_summary text,
    chat_history jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    slash_command character varying(32),
    command_description character varying(80),
    menu_section character varying(30),
    published_workflow_id uuid,
    granted_roles text[] DEFAULT '{}'::text[],
    gates jsonb DEFAULT '[]'::jsonb NOT NULL,
    based_on_version integer,
    chat_summary text,
    kind text DEFAULT 'workflow'::text NOT NULL,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT workflow_drafts_kind_check CHECK ((kind = ANY (ARRAY['workflow'::text, 'block'::text, 'case_action'::text]))),
    CONSTRAINT workflow_drafts_status_check CHECK (((status)::text = ANY (ARRAY[('chatting'::character varying)::text, ('ready_for_review'::character varying)::text, ('published'::character varying)::text, ('abandoned'::character varying)::text])))
);


--
-- Name: workflow_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workflow_id uuid NOT NULL,
    org_id uuid NOT NULL,
    version integer NOT NULL,
    intent_key text NOT NULL,
    name text,
    entity_schema jsonb,
    gates jsonb,
    granted_roles text[],
    steps jsonb,
    calc_rules jsonb,
    sql_template text,
    slash_command text,
    source_draft_id uuid,
    published_at timestamp with time zone DEFAULT now() NOT NULL,
    kind text,
    settings jsonb,
    CONSTRAINT workflow_versions_kind_check CHECK (((kind IS NULL) OR (kind = ANY (ARRAY['workflow'::text, 'block'::text, 'case_action'::text]))))
);


--
-- Name: workflows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflows (
    id uuid DEFAULT public.uuid_generate_v7() NOT NULL,
    org_id uuid NOT NULL,
    intent_key text NOT NULL,
    name text NOT NULL,
    steps jsonb DEFAULT '[]'::jsonb,
    is_active boolean DEFAULT true,
    otp_required boolean DEFAULT false,
    otp_threshold numeric(12,2),
    version integer DEFAULT 1,
    last_run timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    scheduled_by uuid,
    approval_threshold numeric(12,2),
    description text,
    workflow_type character varying(20) DEFAULT 'action'::character varying NOT NULL,
    training_phrases jsonb DEFAULT '[]'::jsonb NOT NULL,
    entity_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    sql_template text,
    sql_params_order jsonb DEFAULT '[]'::jsonb NOT NULL,
    response_format character varying(50) DEFAULT 'generic'::character varying NOT NULL,
    business_glossary jsonb DEFAULT '{}'::jsonb NOT NULL,
    llm_system_prompt text,
    pdf_config jsonb,
    response_template text,
    calc_rules jsonb DEFAULT '{}'::jsonb,
    slash_command character varying(32),
    command_description character varying(80),
    menu_section character varying(30) DEFAULT 'other'::character varying NOT NULL,
    gates jsonb DEFAULT '[]'::jsonb NOT NULL,
    kind text DEFAULT 'workflow'::text NOT NULL,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT workflow_type_check CHECK (((workflow_type)::text = ANY (ARRAY[('action'::character varying)::text, ('read'::character varying)::text]))),
    CONSTRAINT workflows_kind_check CHECK ((kind = ANY (ARRAY['workflow'::text, 'block'::text, 'case_action'::text])))
);


--
-- Name: archived_rows id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archived_rows ALTER COLUMN id SET DEFAULT nextval('public.archived_rows_id_seq'::regclass);


--
-- Name: admin_events admin_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_events
    ADD CONSTRAINT admin_events_pkey PRIMARY KEY (id);


--
-- Name: archived_rows archived_rows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archived_rows
    ADD CONSTRAINT archived_rows_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: credentials credentials_org_id_adapter_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credentials
    ADD CONSTRAINT credentials_org_id_adapter_name_key UNIQUE (org_id, adapter_name);


--
-- Name: credentials credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credentials
    ADD CONSTRAINT credentials_pkey PRIMARY KEY (id);


--
-- Name: customers customers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (id);


--
-- Name: inventory inventory_org_id_sku_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_org_id_sku_key UNIQUE (org_id, sku);


--
-- Name: inventory inventory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_pkey PRIMARY KEY (id);


--
-- Name: invoices invoices_org_id_invoice_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_org_id_invoice_number_key UNIQUE (org_id, invoice_number);


--
-- Name: invoices invoices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_pkey PRIMARY KEY (id);


--
-- Name: orders orders_org_id_order_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_org_id_order_number_key UNIQUE (org_id, order_number);


--
-- Name: orders orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);


--
-- Name: orgs orgs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orgs
    ADD CONSTRAINT orgs_pkey PRIMARY KEY (id);


--
-- Name: orgs orgs_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orgs
    ADD CONSTRAINT orgs_slug_key UNIQUE (slug);


--
-- Name: otp_tokens otp_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.otp_tokens
    ADD CONSTRAINT otp_tokens_pkey PRIMARY KEY (id);


--
-- Name: pending_approvals pending_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pending_approvals
    ADD CONSTRAINT pending_approvals_pkey PRIMARY KEY (id);


--
-- Name: prompts prompts_key_scope_scope_ref_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompts
    ADD CONSTRAINT prompts_key_scope_scope_ref_version_key UNIQUE (key, scope, scope_ref, version);


--
-- Name: prompts prompts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompts
    ADD CONSTRAINT prompts_pkey PRIMARY KEY (id);


--
-- Name: quotations quotations_org_id_quotation_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotations
    ADD CONSTRAINT quotations_org_id_quotation_number_key UNIQUE (org_id, quotation_number);


--
-- Name: quotations quotations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotations
    ADD CONSTRAINT quotations_pkey PRIMARY KEY (id);


--
-- Name: roles roles_org_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_org_id_name_key UNIQUE (org_id, name);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: scheduled_reports scheduled_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_reports
    ADD CONSTRAINT scheduled_reports_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: system_messages system_messages_key_locale_scope_scope_ref_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_messages
    ADD CONSTRAINT system_messages_key_locale_scope_scope_ref_version_key UNIQUE (key, locale, scope, scope_ref, version);


--
-- Name: system_messages system_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_messages
    ADD CONSTRAINT system_messages_pkey PRIMARY KEY (id);


--
-- Name: user_drafts user_drafts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_drafts
    ADD CONSTRAINT user_drafts_pkey PRIMARY KEY (id);


--
-- Name: users users_org_id_phone_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_org_id_phone_key UNIQUE (org_id, phone);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: workflow_drafts workflow_drafts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_drafts
    ADD CONSTRAINT workflow_drafts_pkey PRIMARY KEY (id);


--
-- Name: workflow_versions workflow_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_versions
    ADD CONSTRAINT workflow_versions_pkey PRIMARY KEY (id);


--
-- Name: workflows workflows_org_id_intent_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflows
    ADD CONSTRAINT workflows_org_id_intent_key_key UNIQUE (org_id, intent_key);


--
-- Name: workflows workflows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflows
    ADD CONSTRAINT workflows_pkey PRIMARY KEY (id);


--
-- Name: idx_admin_events_org_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_admin_events_org_time ON public.admin_events USING btree (org_id, created_at DESC);


--
-- Name: idx_admin_events_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_admin_events_target ON public.admin_events USING btree (org_id, target_type, target_id);


--
-- Name: idx_approvals_org_requester; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_org_requester ON public.pending_approvals USING btree (org_id, requester_id);


--
-- Name: idx_approvals_org_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_org_status ON public.pending_approvals USING btree (org_id, status);


--
-- Name: idx_archived_rows_age; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_archived_rows_age ON public.archived_rows USING btree (org_id, archived_at);


--
-- Name: idx_archived_rows_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_archived_rows_source ON public.archived_rows USING btree (source_table, archived_at);


--
-- Name: idx_audit_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_created ON public.audit_log USING btree (org_id, created_at);


--
-- Name: idx_audit_log_intent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_intent ON public.audit_log USING btree (org_id, intent_key, created_at);


--
-- Name: idx_audit_log_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_session ON public.audit_log USING btree (session_id, created_at);


--
-- Name: idx_audit_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_org_id ON public.audit_log USING btree (org_id);


--
-- Name: idx_customers_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_customers_name_trgm ON public.customers USING gin (name public.gin_trgm_ops);


--
-- Name: idx_inventory_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_inventory_name_trgm ON public.inventory USING gin (name public.gin_trgm_ops);


--
-- Name: idx_otp_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_otp_org ON public.otp_tokens USING btree (org_id);


--
-- Name: idx_otp_user_expiry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_otp_user_expiry ON public.otp_tokens USING btree (user_id, expires_at);


--
-- Name: idx_prompts_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_prompts_lookup ON public.prompts USING btree (key, scope, scope_ref, version DESC) WHERE is_active;


--
-- Name: idx_scheduled_reports_next_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduled_reports_next_run ON public.scheduled_reports USING btree (next_run_at, is_active);


--
-- Name: idx_scheduled_reports_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduled_reports_org ON public.scheduled_reports USING btree (org_id);


--
-- Name: idx_scheduled_reports_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduled_reports_user ON public.scheduled_reports USING btree (user_id);


--
-- Name: idx_system_messages_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_system_messages_lookup ON public.system_messages USING btree (key, locale, scope, scope_ref, version DESC) WHERE is_active;


--
-- Name: idx_user_drafts_expiry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_drafts_expiry ON public.user_drafts USING btree (expires_at) WHERE ((stage)::text <> ALL ((ARRAY['done'::character varying, 'cancelled'::character varying])::text[]));


--
-- Name: idx_users_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_org_id ON public.users USING btree (org_id);


--
-- Name: idx_users_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_phone ON public.users USING btree (phone);


--
-- Name: idx_workflow_drafts_org_intent_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_workflow_drafts_org_intent_active ON public.workflow_drafts USING btree (org_id, intent_key) WHERE (((status)::text = ANY (ARRAY[('chatting'::character varying)::text, ('ready_for_review'::character varying)::text])) AND (intent_key IS NOT NULL));


--
-- Name: idx_workflow_drafts_org_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_drafts_org_status ON public.workflow_drafts USING btree (org_id, status);


--
-- Name: idx_workflow_drafts_org_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_drafts_org_updated ON public.workflow_drafts USING btree (org_id, updated_at);


--
-- Name: idx_workflow_versions_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_versions_workflow ON public.workflow_versions USING btree (workflow_id, version);


--
-- Name: idx_workflows_org_intent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_org_intent ON public.workflows USING btree (org_id, intent_key);


--
-- Name: idx_workflows_org_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_org_kind ON public.workflows USING btree (org_id, kind, is_active);


--
-- Name: idx_workflows_org_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_org_type ON public.workflows USING btree (org_id, workflow_type, is_active);


--
-- Name: one_active_draft_per_user; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX one_active_draft_per_user ON public.user_drafts USING btree (org_id, user_id) WHERE ((stage)::text <> ALL ((ARRAY['done'::character varying, 'cancelled'::character varying])::text[]));


--
-- Name: workflows_org_slash_cmd; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX workflows_org_slash_cmd ON public.workflows USING btree (org_id, slash_command);


--
-- Name: admin_events admin_events_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_events
    ADD CONSTRAINT admin_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: admin_events admin_events_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_events
    ADD CONSTRAINT admin_events_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: audit_log audit_log_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: audit_log audit_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: credentials credentials_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credentials
    ADD CONSTRAINT credentials_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: customers customers_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: quotations fk_quotations_created_by; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotations
    ADD CONSTRAINT fk_quotations_created_by FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: quotations fk_quotations_customer; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotations
    ADD CONSTRAINT fk_quotations_customer FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE CASCADE;


--
-- Name: quotations fk_quotations_org; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotations
    ADD CONSTRAINT fk_quotations_org FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: inventory inventory_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: invoices invoices_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: invoices invoices_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id);


--
-- Name: invoices invoices_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: orders orders_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: orders orders_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id);


--
-- Name: orders orders_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: orders orders_quotation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_quotation_id_fkey FOREIGN KEY (quotation_id) REFERENCES public.quotations(id) ON DELETE SET NULL;


--
-- Name: otp_tokens otp_tokens_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.otp_tokens
    ADD CONSTRAINT otp_tokens_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: otp_tokens otp_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.otp_tokens
    ADD CONSTRAINT otp_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: pending_approvals pending_approvals_decided_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pending_approvals
    ADD CONSTRAINT pending_approvals_decided_by_fkey FOREIGN KEY (decided_by) REFERENCES public.users(id);


--
-- Name: pending_approvals pending_approvals_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pending_approvals
    ADD CONSTRAINT pending_approvals_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: pending_approvals pending_approvals_requester_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pending_approvals
    ADD CONSTRAINT pending_approvals_requester_id_fkey FOREIGN KEY (requester_id) REFERENCES public.users(id);


--
-- Name: pending_approvals pending_approvals_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pending_approvals
    ADD CONSTRAINT pending_approvals_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id);


--
-- Name: roles roles_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: scheduled_reports scheduled_reports_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_reports
    ADD CONSTRAINT scheduled_reports_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: scheduled_reports scheduled_reports_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_reports
    ADD CONSTRAINT scheduled_reports_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_drafts user_drafts_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_drafts
    ADD CONSTRAINT user_drafts_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: user_drafts user_drafts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_drafts
    ADD CONSTRAINT user_drafts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: users users_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: users users_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id);


--
-- Name: workflow_drafts workflow_drafts_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_drafts
    ADD CONSTRAINT workflow_drafts_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: workflow_drafts workflow_drafts_published_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_drafts
    ADD CONSTRAINT workflow_drafts_published_workflow_id_fkey FOREIGN KEY (published_workflow_id) REFERENCES public.workflows(id) ON DELETE SET NULL;


--
-- Name: workflows workflows_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflows
    ADD CONSTRAINT workflows_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict 0MDhyJidIVcu6Dp0CMco8rlQpIVsSez9WYgChYzocUX2DFNGhonkbfPAh1bUa8s

