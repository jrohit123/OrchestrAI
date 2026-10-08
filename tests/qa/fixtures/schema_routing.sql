--
-- PostgreSQL database dump
--

\restrict ylgKMczi7BcBhLep2Px1zOHUh2lOZe0McsCKycMKgBcZZtfkXbLQgV2ZS5ERb1r

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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: data_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_sources (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_key text NOT NULL,
    database_url text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now(),
    messaging_channel text
);


--
-- Name: panel_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.panel_accounts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email text NOT NULL,
    name text NOT NULL,
    level text NOT NULL,
    source_keys text[] DEFAULT '{}'::text[] NOT NULL,
    status text DEFAULT 'invited'::text NOT NULL,
    password_hash text,
    wrong_tries integer DEFAULT 0 NOT NULL,
    locked_until timestamp with time zone,
    last_sign_in timestamp with time zone,
    invited_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT panel_accounts_email_check CHECK (((email <> ''::text) AND (email = lower(btrim(email))))),
    CONSTRAINT panel_accounts_level_check CHECK ((level = ANY (ARRAY['super'::text, 'admin'::text]))),
    CONSTRAINT panel_accounts_name_check CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT panel_accounts_orgs_check CHECK ((((level = 'super'::text) AND (cardinality(source_keys) = 0)) OR ((level = 'admin'::text) AND ((status = 'off'::text) OR (cardinality(source_keys) > 0))))),
    CONSTRAINT panel_accounts_password_check CHECK (((status <> 'active'::text) OR (password_hash IS NOT NULL))),
    CONSTRAINT panel_accounts_status_check CHECK ((status = ANY (ARRAY['invited'::text, 'active'::text, 'off'::text]))),
    CONSTRAINT panel_accounts_tries_check CHECK ((wrong_tries >= 0))
);


--
-- Name: panel_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.panel_audit (
    id bigint NOT NULL,
    at timestamp with time zone DEFAULT now() NOT NULL,
    account_id uuid,
    email text,
    action text NOT NULL,
    ok boolean DEFAULT true NOT NULL,
    source_key text,
    detail text,
    ip text,
    agent text
);


--
-- Name: panel_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.panel_audit ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.panel_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: panel_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.panel_keys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    account_id uuid NOT NULL,
    kind text NOT NULL,
    key_hash text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    last_used timestamp with time zone,
    used_at timestamp with time zone,
    tries integer DEFAULT 0 NOT NULL,
    ip text,
    agent text,
    CONSTRAINT panel_keys_kind_check CHECK ((kind = ANY (ARRAY['session'::text, 'signup'::text, 'reset'::text, 'signin'::text]))),
    CONSTRAINT panel_keys_tries_check CHECK ((tries >= 0))
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
-- Name: data_sources data_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_sources
    ADD CONSTRAINT data_sources_pkey PRIMARY KEY (id);


--
-- Name: data_sources data_sources_source_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_sources
    ADD CONSTRAINT data_sources_source_key_key UNIQUE (source_key);


--
-- Name: panel_accounts panel_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.panel_accounts
    ADD CONSTRAINT panel_accounts_pkey PRIMARY KEY (id);


--
-- Name: panel_audit panel_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.panel_audit
    ADD CONSTRAINT panel_audit_pkey PRIMARY KEY (id);


--
-- Name: panel_keys panel_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.panel_keys
    ADD CONSTRAINT panel_keys_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: panel_accounts_email_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX panel_accounts_email_key ON public.panel_accounts USING btree (email);


--
-- Name: panel_audit_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX panel_audit_account ON public.panel_audit USING btree (account_id, at DESC);


--
-- Name: panel_audit_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX panel_audit_time ON public.panel_audit USING btree (at DESC);


--
-- Name: panel_keys_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX panel_keys_account ON public.panel_keys USING btree (account_id, kind, created_at DESC);


--
-- Name: panel_keys_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX panel_keys_expires ON public.panel_keys USING btree (expires_at);


--
-- Name: panel_keys_session_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX panel_keys_session_key ON public.panel_keys USING btree (key_hash) WHERE (kind = 'session'::text);


--
-- Name: panel_accounts panel_accounts_invited_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.panel_accounts
    ADD CONSTRAINT panel_accounts_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES public.panel_accounts(id) ON DELETE SET NULL;


--
-- Name: panel_audit panel_audit_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.panel_audit
    ADD CONSTRAINT panel_audit_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.panel_accounts(id) ON DELETE SET NULL;


--
-- Name: panel_keys panel_keys_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.panel_keys
    ADD CONSTRAINT panel_keys_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.panel_accounts(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict ylgKMczi7BcBhLep2Px1zOHUh2lOZe0McsCKycMKgBcZZtfkXbLQgV2ZS5ERb1r

