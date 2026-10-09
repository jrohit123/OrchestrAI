--
-- PostgreSQL database dump
--

\restrict AzrPznaKsh9ILVFJXfO42uuX1pHv92LIMxQ62bx1AmiCP3d3s0tVHrASX6MXs4W

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
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: case_categories_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.case_categories_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    cur  uuid := NEW.parent_id;
    hops integer := 0;
BEGIN
    WHILE cur IS NOT NULL LOOP
        IF cur = NEW.id THEN
            RAISE EXCEPTION 'A category cannot sit under itself or under one of its own sub-categories.';
        END IF;
        hops := hops + 1;
        IF hops > 8 THEN
            RAISE EXCEPTION 'Categories can be at most 8 levels deep.';
        END IF;
        SELECT parent_id INTO cur FROM case_categories WHERE id = cur;
    END LOOP;
    RETURN NEW;
END;
$$;


--
-- Name: case_relations(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.case_relations(p_case uuid, p_user uuid) RETURNS TABLE(is_requester boolean, is_assignee boolean, is_level2 boolean, is_helper boolean, was_assignee boolean, grant_level smallint)
    LANGUAGE sql STABLE
    AS $$
    WITH c AS (
        SELECT cs.id, cs.org_id, cs.category_id, cs.custom_fields, w.intent_key
          FROM cases cs LEFT JOIN workflows w ON w.id = cs.workflow_id
         WHERE cs.id = p_case
    ), chain AS (
        WITH RECURSIVE up AS (
            SELECT k.id, k.parent_id, k.key, 1 AS hop FROM case_categories k JOIN c ON k.id = c.category_id
            UNION ALL
            SELECT k.id, k.parent_id, k.key, up.hop + 1 FROM case_categories k JOIN up ON k.id = up.parent_id WHERE up.hop < 8
        )
        SELECT key FROM up
    ), me AS (
        SELECT u.id, u.role_id FROM users u WHERE u.id = p_user
    ), seats AS (
        SELECT m.position_id
          FROM committee_members m JOIN me ON m.user_id = me.id
         WHERE m.status = 'active'
           AND (m.start_date IS NULL OR m.start_date <= CURRENT_DATE)
           AND (m.end_date   IS NULL OR m.end_date   >= CURRENT_DATE)
    ), g AS (
        SELECT max(a.level) AS lvl
          FROM access_grants a, c, me
         WHERE a.org_id = c.org_id AND a.revoked_at IS NULL
           AND (a.valid_from IS NULL OR a.valid_from <= CURRENT_DATE)
           AND (a.valid_to   IS NULL OR a.valid_to   >= CURRENT_DATE)
           AND (a.user_id = me.id OR a.role_id = me.role_id OR a.position_id IN (SELECT position_id FROM seats))
           AND (a.workflow_key = '*' OR a.workflow_key = c.intent_key)
           AND ((a.scope ->> 'category') IS NULL OR (a.scope ->> 'category') IN (SELECT key FROM chain))
           AND ((a.scope - 'category') = '{}'::jsonb OR c.custom_fields @> (a.scope - 'category'))
    )
    SELECT
        EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = p_case AND p.user_id = p_user AND p.party_role = 'requester' AND p.ended_at IS NULL),
        EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = p_case AND p.user_id = p_user AND p.party_role = 'assignee'  AND p.ended_at IS NULL),
        EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = p_case AND p.user_id = p_user AND p.party_role = 'level2'    AND p.ended_at IS NULL),
        EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = p_case AND p.user_id = p_user AND p.party_role = 'helper'    AND p.ended_at IS NULL),
        EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = p_case AND p.user_id = p_user AND p.party_role = 'assignee'  AND p.ended_at IS NOT NULL),
        COALESCE((SELECT lvl FROM g), 0)::smallint;
$$;


--
-- Name: committee_positions_default_slug(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.committee_positions_default_slug() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.slug IS NULL OR NEW.slug = '' THEN
        NEW.slug := trim(both '_' from regexp_replace(lower(NEW.name), '[^a-z0-9]+', '_', 'g'));
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: route_case(uuid, uuid, jsonb, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.route_case(p_org uuid, p_category uuid, p_context jsonb DEFAULT '{}'::jsonb, p_intent_key text DEFAULT NULL::text, p_priority text DEFAULT NULL::text) RETURNS TABLE(rule_id uuid, rule_name text, assignee_id uuid, level2_ids uuid[], target_minutes integer, via text)
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
    r           record;
    first_ids   uuid[];
    backup_ids  uuid[];
    cat_minutes integer;
    prio_minutes integer;
BEGIN
    WITH RECURSIVE up AS (
        SELECT c.id, c.parent_id, c.target_minutes AS tm, 1 AS hop
          FROM case_categories c WHERE c.id = p_category
        UNION ALL
        SELECT c.id, c.parent_id, c.target_minutes, up.hop + 1
          FROM case_categories c JOIN up ON c.id = up.parent_id WHERE up.hop < 8
    ), chain AS (
        SELECT up.id, up.tm, up.hop, (SELECT max(hop) FROM up) - up.hop + 1 AS depth FROM up
    )
    SELECT ru.id AS rid, ru.name AS rname,
           ru.assign_user_id, ru.assign_position_id, ru.assign_role_id,
           ru.backup_user_id, ru.backup_position_id, ru.backup_role_id,
           ru.target_minutes AS rule_tm,
           (SELECT ch2.tm FROM chain ch2 WHERE ch2.tm IS NOT NULL ORDER BY ch2.hop LIMIT 1) AS cat_tm,
           COALESCE(ch.depth, 0) * 10
             + (SELECT count(*) FROM jsonb_object_keys(ru.match)) * 5
             + (CASE WHEN ru.intent_key IS NOT NULL THEN 3 ELSE 0 END) AS score
      INTO r
      FROM routing_rules ru
      LEFT JOIN chain ch ON ch.id = ru.category_id
     WHERE ru.org_id = p_org AND ru.is_active
       AND (ru.intent_key IS NULL OR ru.intent_key = p_intent_key)
       AND (ru.category_id IS NULL OR ch.id IS NOT NULL)
       AND COALESCE(p_context, '{}'::jsonb) @> ru.match
     ORDER BY score DESC, ru.sort_order, ru.created_at
     LIMIT 1;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    first_ids  := public.route_targets(p_org, r.assign_user_id, r.assign_position_id, r.assign_role_id);
    backup_ids := public.route_targets(p_org, r.backup_user_id, r.backup_position_id, r.backup_role_id);

    IF p_priority IS NOT NULL THEN
        SELECT t.tat_minutes INTO prio_minutes FROM priority_tat_rules t WHERE t.org_id = p_org AND t.priority = p_priority;
    END IF;

    rule_id := r.rid;
    rule_name := r.rname;
    IF cardinality(first_ids) > 0 THEN
        assignee_id := first_ids[1];
        via := 'rule';
        level2_ids := ARRAY(SELECT x FROM unnest(backup_ids) AS x WHERE x <> first_ids[1]);
    ELSIF cardinality(backup_ids) > 0 THEN
        assignee_id := backup_ids[1];
        via := 'backup';
        level2_ids := ARRAY(SELECT x FROM unnest(backup_ids) AS x WHERE x <> backup_ids[1]);
    ELSE
        assignee_id := NULL;
        via := 'nobody available';
        level2_ids := '{}'::uuid[];
    END IF;
    target_minutes := COALESCE(r.rule_tm, r.cat_tm, prio_minutes);
    RETURN NEXT;
END;
$$;


--
-- Name: route_targets(uuid, uuid, uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.route_targets(p_org uuid, p_user uuid, p_position uuid, p_role uuid) RETURNS uuid[]
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(array_agg(u.id ORDER BY u.name, u.id), '{}'::uuid[])
      FROM users u
     WHERE u.org_id = p_org
       AND u.is_active
       AND ((u.channel = 'telegram' AND u.phone LIKE 'tg:%')
            OR (COALESCE(u.channel, '') <> 'telegram' AND COALESCE(u.phone, '') <> ''))
       AND (
            (p_user IS NOT NULL AND u.id = p_user)
         OR (p_position IS NOT NULL AND EXISTS (
                SELECT 1 FROM committee_members m
                 WHERE m.user_id = u.id AND m.position_id = p_position AND m.status = 'active'
                   AND (m.start_date IS NULL OR m.start_date <= CURRENT_DATE)
                   AND (m.end_date   IS NULL OR m.end_date   >= CURRENT_DATE)))
         OR (p_role IS NOT NULL AND u.role_id = p_role)
       );
$$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;


--
-- Name: sync_case_parties_from_case(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sync_case_parties_from_case() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- if this ran because another trigger touched cases, there is nothing to mirror
    IF pg_trigger_depth() > 1 THEN
        RETURN NEW;
    END IF;

    -- requester
    IF TG_OP = 'INSERT' OR NEW.complainant_id IS DISTINCT FROM OLD.complainant_id THEN
        IF TG_OP = 'UPDATE' THEN
            UPDATE case_parties SET ended_at = now()
             WHERE case_id = NEW.id AND party_role = 'requester' AND ended_at IS NULL
               AND user_id IS DISTINCT FROM NEW.complainant_id;
        END IF;
        IF NEW.complainant_id IS NOT NULL THEN
            INSERT INTO case_parties (org_id, case_id, user_id, party_role, added_by)
            VALUES (NEW.org_id, NEW.id, NEW.complainant_id, 'requester', NEW.complainant_id)
            ON CONFLICT (case_id, user_id, party_role) WHERE ended_at IS NULL DO NOTHING;
        END IF;
    END IF;

    -- assignee: a hand-over ends the old row and starts a new one
    IF (TG_OP = 'INSERT' AND NEW.assigned_to_id IS NOT NULL)
       OR (TG_OP = 'UPDATE' AND NEW.assigned_to_id IS DISTINCT FROM OLD.assigned_to_id) THEN
        UPDATE case_parties SET ended_at = now()
         WHERE case_id = NEW.id AND party_role = 'assignee' AND ended_at IS NULL
           AND user_id IS DISTINCT FROM NEW.assigned_to_id;
        IF NEW.assigned_to_id IS NOT NULL THEN
            INSERT INTO case_parties (org_id, case_id, user_id, party_role)
            VALUES (NEW.org_id, NEW.id, NEW.assigned_to_id, 'assignee')
            ON CONFLICT (case_id, user_id, party_role) WHERE ended_at IS NULL DO NOTHING;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: sync_committee_role_to_user(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sync_committee_role_to_user() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  committee_role_id uuid;
  member_role_id uuid;
  seat_kind text;
BEGIN
  -- Only real committee seats switch a person's role. A volunteer, staff or other seat never does.
  SELECT kind INTO seat_kind FROM committee_positions WHERE id = NEW.position_id;
  IF seat_kind IS DISTINCT FROM 'committee' THEN
    RETURN NEW;
  END IF;

  SELECT id INTO committee_role_id FROM roles WHERE org_id = NEW.org_id AND name = 'committee';
  SELECT id INTO member_role_id   FROM roles WHERE org_id = NEW.org_id AND name = 'member';

  IF NEW.status = 'active' THEN
    UPDATE users SET role_id = committee_role_id WHERE id = NEW.user_id;
  ELSIF NEW.status = 'ended' THEN
    UPDATE users SET role_id = member_role_id WHERE id = NEW.user_id;
  END IF;
  RETURN NEW;
END;
$$;


--
-- Name: sync_resident_status_to_user(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sync_resident_status_to_user() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.status IN ('suspended', 'inactive') AND NEW.user_id IS NOT NULL THEN
    UPDATE users SET is_active = false WHERE id = NEW.user_id;
  ELSIF NEW.status = 'active' AND NEW.user_id IS NOT NULL THEN
    UPDATE users SET is_active = true WHERE id = NEW.user_id;
  END IF;
  RETURN NEW;
END;
$$;


--
-- Name: sync_staff_status_to_user(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sync_staff_status_to_user() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.status IN ('suspended','inactive') AND NEW.user_id IS NOT NULL THEN
    UPDATE users SET is_active = false WHERE id = NEW.user_id;
  ELSIF NEW.status = 'active' AND NEW.user_id IS NOT NULL THEN
    UPDATE users SET is_active = true WHERE id = NEW.user_id;
  END IF;
  RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: access_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.access_grants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    user_id uuid,
    role_id uuid,
    position_id uuid,
    workflow_key text DEFAULT '*'::text NOT NULL,
    level smallint NOT NULL,
    scope jsonb DEFAULT '{}'::jsonb NOT NULL,
    valid_from date,
    valid_to date,
    note text,
    granted_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked_at timestamp with time zone,
    CONSTRAINT access_grants_dates_check CHECK (((valid_from IS NULL) OR (valid_to IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT access_grants_level_check CHECK (((level >= 1) AND (level <= 4))),
    CONSTRAINT access_grants_one_subject CHECK ((num_nonnulls(user_id, role_id, position_id) = 1))
);


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
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
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
-- Name: case_activity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_activity (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    case_id uuid NOT NULL,
    actor_user_id uuid,
    activity_type character varying(20) NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT case_activity_type_check CHECK (((activity_type)::text = ANY (ARRAY[('comment'::character varying)::text, ('evidence'::character varying)::text, ('status_change'::character varying)::text, ('assignment'::character varying)::text, ('priority_change'::character varying)::text, ('category_change'::character varying)::text, ('escalation'::character varying)::text, ('reopen'::character varying)::text])))
);


--
-- Name: case_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_categories (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    parent_id uuid,
    key text NOT NULL,
    label text NOT NULL,
    default_priority character varying(10),
    target_minutes integer,
    keywords text[] DEFAULT '{}'::text[] NOT NULL,
    extra_fields jsonb DEFAULT '[]'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT case_categories_key_check CHECK ((key ~ '^[a-z0-9_]+(\.[a-z0-9_]+)*$'::text)),
    CONSTRAINT case_categories_not_self CHECK (((parent_id IS NULL) OR (parent_id <> id))),
    CONSTRAINT case_categories_priority_check CHECK (((default_priority IS NULL) OR ((default_priority)::text = ANY (ARRAY[('urgent'::character varying)::text, ('high'::character varying)::text, ('medium'::character varying)::text, ('low'::character varying)::text])))),
    CONSTRAINT case_categories_target_check CHECK (((target_minutes IS NULL) OR (target_minutes > 0)))
);


--
-- Name: case_parties; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_parties (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    case_id uuid NOT NULL,
    user_id uuid NOT NULL,
    party_role text NOT NULL,
    added_by uuid,
    added_at timestamp with time zone DEFAULT now() NOT NULL,
    ended_at timestamp with time zone,
    note text,
    CONSTRAINT case_parties_dates_check CHECK (((ended_at IS NULL) OR (ended_at >= added_at))),
    CONSTRAINT case_parties_role_check CHECK ((party_role = ANY (ARRAY['requester'::text, 'assignee'::text, 'level2'::text, 'helper'::text, 'watcher'::text])))
);


--
-- Name: cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cases (
    id uuid DEFAULT gen_random_uuid() CONSTRAINT complaint_cases_id_not_null NOT NULL,
    org_id uuid CONSTRAINT complaint_cases_org_id_not_null NOT NULL,
    case_number text CONSTRAINT complaint_cases_case_number_not_null NOT NULL,
    complainant_id uuid,
    title text CONSTRAINT complaint_cases_complaint_title_not_null NOT NULL,
    description text,
    status character varying(20) DEFAULT 'reported'::character varying CONSTRAINT complaint_cases_status_not_null NOT NULL,
    priority character varying(10) DEFAULT 'medium'::character varying,
    location text,
    assigned_to_id uuid,
    created_at timestamp with time zone DEFAULT now(),
    closed_at timestamp with time zone,
    due_date timestamp with time zone,
    custom_fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    workflow_id uuid,
    reminder_sent_at timestamp with time zone,
    tat_breach_sent_at timestamp with time zone,
    case_number_norm text GENERATED ALWAYS AS (regexp_replace(upper(case_number), '[^A-Z0-9]'::text, ''::text, 'g'::text)) STORED,
    category_id uuid,
    CONSTRAINT cases_priority_check CHECK (((priority)::text = ANY (ARRAY[('urgent'::character varying)::text, ('high'::character varying)::text, ('medium'::character varying)::text, ('low'::character varying)::text]))),
    CONSTRAINT complaint_cases_status_check CHECK (((status)::text = ANY (ARRAY[('reported'::character varying)::text, ('under_review'::character varying)::text, ('action_taken'::character varying)::text, ('closed'::character varying)::text])))
);


--
-- Name: committee_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.committee_members (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    user_id uuid NOT NULL,
    position_id uuid NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    start_date date DEFAULT CURRENT_DATE,
    end_date date,
    access_overrides text[],
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT committee_members_status_check CHECK (((status)::text = ANY (ARRAY[('active'::character varying)::text, ('ended'::character varying)::text])))
);


--
-- Name: committee_positions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.committee_positions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    default_permissions text[] DEFAULT '{}'::text[],
    created_at timestamp with time zone DEFAULT now(),
    slug text,
    kind text DEFAULT 'committee'::text NOT NULL,
    description text,
    CONSTRAINT committee_positions_kind_check CHECK ((kind = ANY (ARRAY['committee'::text, 'volunteer'::text, 'staff'::text, 'security'::text, 'other'::text])))
);


--
-- Name: entity_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entity_records (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    entity_type text NOT NULL,
    name text,
    status text,
    ref_date date,
    linked_id uuid,
    fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: orgs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orgs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    industry text,
    plan text DEFAULT 'trial'::text,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    session_ttl_minutes integer DEFAULT 480,
    context_message_limit integer DEFAULT 12 NOT NULL,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL,
    otp_expiry_minutes integer DEFAULT 3 NOT NULL,
    otp_max_attempts integer DEFAULT 3 NOT NULL,
    otp_length integer DEFAULT 4 NOT NULL,
    otp_resend_cooldown_seconds integer DEFAULT 60 NOT NULL,
    gst_rate numeric(5,2) DEFAULT NULL::numeric,
    default_making_charge_pct numeric(5,2) DEFAULT NULL::numeric,
    logo_url text,
    timezone text DEFAULT 'Asia/Kolkata'::text NOT NULL,
    locale text DEFAULT 'en-IN'::text NOT NULL
);


--
-- Name: otp_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.otp_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
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
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
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
-- Name: priority_tat_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.priority_tat_rules (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    priority character varying(10) NOT NULL,
    tat_minutes integer NOT NULL,
    reminder_threshold_minutes integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT priority_tat_rules_priority_check CHECK (((priority)::text = ANY (ARRAY[('urgent'::character varying)::text, ('high'::character varying)::text, ('medium'::character varying)::text, ('low'::character varying)::text])))
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
-- Name: residents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.residents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    user_id uuid,
    wing text,
    flat_no text NOT NULL,
    gender character varying(10),
    residential_status character varying(20) DEFAULT 'tenant'::character varying NOT NULL,
    brokers_name text,
    first_owner_name text,
    first_owner_mobile text,
    registration_date date DEFAULT CURRENT_DATE,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    approved_by uuid,
    suspension_date date,
    created_at timestamp with time zone DEFAULT now(),
    name text,
    custom_fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT residents_residential_status_check CHECK (((residential_status)::text = ANY (ARRAY[('tenant'::character varying)::text, ('first_owner'::character varying)::text, ('second_owner'::character varying)::text, ('other'::character varying)::text]))),
    CONSTRAINT residents_status_check CHECK (((status)::text = ANY (ARRAY[('active'::character varying)::text, ('suspended'::character varying)::text, ('inactive'::character varying)::text, ('not_residing'::character varying)::text])))
);


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
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
-- Name: routing_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.routing_rules (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    intent_key text,
    category_id uuid,
    match jsonb DEFAULT '{}'::jsonb NOT NULL,
    assign_user_id uuid,
    assign_position_id uuid,
    assign_role_id uuid,
    backup_user_id uuid,
    backup_position_id uuid,
    backup_role_id uuid,
    target_minutes integer,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT routing_rules_one_backup CHECK ((num_nonnulls(backup_user_id, backup_position_id, backup_role_id) <= 1)),
    CONSTRAINT routing_rules_one_target CHECK ((num_nonnulls(assign_user_id, assign_position_id, assign_role_id) = 1)),
    CONSTRAINT routing_rules_target_check CHECK (((target_minutes IS NULL) OR (target_minutes > 0)))
);


--
-- Name: scheduled_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_reports (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
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
-- Name: staff; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staff (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    user_id uuid,
    name text NOT NULL,
    gender character varying(10),
    department text,
    designation text,
    vendor_name text,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    start_date date DEFAULT CURRENT_DATE,
    end_date date,
    approved_by uuid,
    created_at timestamp with time zone DEFAULT now(),
    custom_fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT staff_status_check CHECK (((status)::text = ANY (ARRAY[('active'::character varying)::text, ('suspended'::character varying)::text, ('inactive'::character varying)::text])))
);


--
-- Name: staff_attendance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staff_attendance (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    staff_id uuid NOT NULL,
    attendance_date date DEFAULT CURRENT_DATE NOT NULL,
    check_in timestamp with time zone,
    check_out timestamp with time zone,
    status character varying(20) DEFAULT 'present'::character varying NOT NULL,
    marked_by uuid,
    custom_fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT staff_attendance_status_check CHECK (((status)::text = ANY (ARRAY[('present'::character varying)::text, ('absent'::character varying)::text, ('half_day'::character varying)::text, ('on_leave'::character varying)::text])))
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
    id uuid DEFAULT gen_random_uuid() NOT NULL,
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
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    org_id uuid NOT NULL,
    role_id uuid,
    name text NOT NULL,
    phone text,
    email text NOT NULL,
    channel text DEFAULT 'telegram'::text,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: workflow_drafts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_drafts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
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
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
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
-- Name: access_grants access_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_pkey PRIMARY KEY (id);


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
-- Name: case_activity case_activity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_activity
    ADD CONSTRAINT case_activity_pkey PRIMARY KEY (id);


--
-- Name: case_categories case_categories_org_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_categories
    ADD CONSTRAINT case_categories_org_key_key UNIQUE (org_id, key);


--
-- Name: case_categories case_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_categories
    ADD CONSTRAINT case_categories_pkey PRIMARY KEY (id);


--
-- Name: case_parties case_parties_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_parties
    ADD CONSTRAINT case_parties_pkey PRIMARY KEY (id);


--
-- Name: committee_members committee_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_members
    ADD CONSTRAINT committee_members_pkey PRIMARY KEY (id);


--
-- Name: committee_positions committee_positions_org_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_positions
    ADD CONSTRAINT committee_positions_org_id_name_key UNIQUE (org_id, name);


--
-- Name: committee_positions committee_positions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_positions
    ADD CONSTRAINT committee_positions_pkey PRIMARY KEY (id);


--
-- Name: cases complaint_cases_org_case_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT complaint_cases_org_case_number_key UNIQUE (org_id, case_number);


--
-- Name: cases complaint_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT complaint_cases_pkey PRIMARY KEY (id);


--
-- Name: entity_records entity_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_records
    ADD CONSTRAINT entity_records_pkey PRIMARY KEY (id);


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
-- Name: priority_tat_rules priority_tat_rules_org_priority_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.priority_tat_rules
    ADD CONSTRAINT priority_tat_rules_org_priority_key UNIQUE (org_id, priority);


--
-- Name: priority_tat_rules priority_tat_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.priority_tat_rules
    ADD CONSTRAINT priority_tat_rules_pkey PRIMARY KEY (id);


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
-- Name: residents residents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.residents
    ADD CONSTRAINT residents_pkey PRIMARY KEY (id);


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
-- Name: routing_rules routing_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_rules
    ADD CONSTRAINT routing_rules_pkey PRIMARY KEY (id);


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
-- Name: staff_attendance staff_attendance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_attendance
    ADD CONSTRAINT staff_attendance_pkey PRIMARY KEY (id);


--
-- Name: staff_attendance staff_attendance_staff_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_attendance
    ADD CONSTRAINT staff_attendance_staff_date_key UNIQUE (staff_id, attendance_date);


--
-- Name: staff staff_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff
    ADD CONSTRAINT staff_pkey PRIMARY KEY (id);


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
-- Name: users users_org_id_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_org_id_email_key UNIQUE (org_id, email);


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
-- Name: case_parties_one_active_assignee_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX case_parties_one_active_assignee_key ON public.case_parties USING btree (case_id) WHERE ((party_role = 'assignee'::text) AND (ended_at IS NULL));


--
-- Name: case_parties_one_active_role_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX case_parties_one_active_role_key ON public.case_parties USING btree (case_id, user_id, party_role) WHERE (ended_at IS NULL);


--
-- Name: committee_positions_org_slug_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX committee_positions_org_slug_key ON public.committee_positions USING btree (org_id, slug);


--
-- Name: entity_records_fields_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX entity_records_fields_gin_idx ON public.entity_records USING gin (fields);


--
-- Name: entity_records_org_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX entity_records_org_type_idx ON public.entity_records USING btree (org_id, entity_type, status);


--
-- Name: idx_access_grants_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_access_grants_position ON public.access_grants USING btree (org_id, position_id) WHERE (revoked_at IS NULL);


--
-- Name: idx_access_grants_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_access_grants_role ON public.access_grants USING btree (org_id, role_id) WHERE (revoked_at IS NULL);


--
-- Name: idx_access_grants_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_access_grants_user ON public.access_grants USING btree (org_id, user_id) WHERE (revoked_at IS NULL);


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
-- Name: idx_case_activity_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_activity_case ON public.case_activity USING btree (case_id, created_at);


--
-- Name: idx_case_activity_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_activity_type ON public.case_activity USING btree (org_id, activity_type);


--
-- Name: idx_case_categories_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_categories_parent ON public.case_categories USING btree (org_id, parent_id);


--
-- Name: idx_case_parties_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_parties_case ON public.case_parties USING btree (case_id);


--
-- Name: idx_case_parties_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_parties_user ON public.case_parties USING btree (org_id, user_id) WHERE (ended_at IS NULL);


--
-- Name: idx_cases_assigned; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_assigned ON public.cases USING btree (assigned_to_id);


--
-- Name: idx_cases_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_category ON public.cases USING btree (org_id, category_id);


--
-- Name: idx_cases_complainant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_complainant ON public.cases USING btree (complainant_id);


--
-- Name: idx_cases_custom_fields; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_custom_fields ON public.cases USING gin (custom_fields);


--
-- Name: idx_cases_number_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_number_norm ON public.cases USING btree (org_id, case_number_norm);


--
-- Name: idx_cases_number_norm_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_number_norm_trgm ON public.cases USING gin (case_number_norm public.gin_trgm_ops);


--
-- Name: idx_cases_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_org ON public.cases USING btree (org_id);


--
-- Name: idx_cases_org_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_org_status ON public.cases USING btree (org_id, status);


--
-- Name: idx_committee_members_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_committee_members_org ON public.committee_members USING btree (org_id);


--
-- Name: idx_committee_one_active_per_position; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_committee_one_active_per_position ON public.committee_members USING btree (org_id, position_id) WHERE ((status)::text = 'active'::text);


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
-- Name: idx_residents_custom_fields; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_residents_custom_fields ON public.residents USING gin (custom_fields);


--
-- Name: idx_residents_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_residents_org ON public.residents USING btree (org_id);


--
-- Name: idx_residents_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_residents_user ON public.residents USING btree (user_id);


--
-- Name: idx_residents_wing_flat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_residents_wing_flat ON public.residents USING btree (org_id, wing, flat_no);


--
-- Name: idx_routing_rules_org_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_routing_rules_org_category ON public.routing_rules USING btree (org_id, category_id) WHERE is_active;


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
-- Name: idx_staff_attendance_custom_fields; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_staff_attendance_custom_fields ON public.staff_attendance USING gin (custom_fields);


--
-- Name: idx_staff_attendance_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_staff_attendance_org ON public.staff_attendance USING btree (org_id);


--
-- Name: idx_staff_custom_fields; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_staff_custom_fields ON public.staff USING gin (custom_fields);


--
-- Name: idx_staff_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_staff_org ON public.staff USING btree (org_id);


--
-- Name: idx_staff_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_staff_user ON public.staff USING btree (user_id);


--
-- Name: idx_system_messages_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_system_messages_lookup ON public.system_messages USING btree (key, locale, scope, scope_ref, version DESC) WHERE is_active;


--
-- Name: idx_user_drafts_expiry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_drafts_expiry ON public.user_drafts USING btree (expires_at) WHERE ((stage)::text <> ALL (ARRAY[('done'::character varying)::text, ('cancelled'::character varying)::text]));


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

CREATE UNIQUE INDEX one_active_draft_per_user ON public.user_drafts USING btree (org_id, user_id) WHERE ((stage)::text <> ALL (ARRAY[('done'::character varying)::text, ('cancelled'::character varying)::text]));


--
-- Name: case_categories trg_case_categories_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_case_categories_guard BEFORE INSERT OR UPDATE OF parent_id ON public.case_categories FOR EACH ROW EXECUTE FUNCTION public.case_categories_guard();


--
-- Name: case_categories trg_case_categories_updated; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_case_categories_updated BEFORE UPDATE ON public.case_categories FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: committee_positions trg_committee_positions_default_slug; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_committee_positions_default_slug BEFORE INSERT ON public.committee_positions FOR EACH ROW EXECUTE FUNCTION public.committee_positions_default_slug();


--
-- Name: routing_rules trg_routing_rules_updated; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_routing_rules_updated BEFORE UPDATE ON public.routing_rules FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: cases trg_sync_case_parties; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_sync_case_parties AFTER INSERT OR UPDATE OF assigned_to_id, complainant_id ON public.cases FOR EACH ROW EXECUTE FUNCTION public.sync_case_parties_from_case();


--
-- Name: committee_members trg_sync_committee_role; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_sync_committee_role AFTER INSERT OR UPDATE OF status ON public.committee_members FOR EACH ROW EXECUTE FUNCTION public.sync_committee_role_to_user();


--
-- Name: residents trg_sync_resident_status; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_sync_resident_status AFTER INSERT OR UPDATE OF status ON public.residents FOR EACH ROW EXECUTE FUNCTION public.sync_resident_status_to_user();


--
-- Name: staff trg_sync_staff_status; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_sync_staff_status AFTER INSERT OR UPDATE OF status ON public.staff FOR EACH ROW EXECUTE FUNCTION public.sync_staff_status_to_user();


--
-- Name: access_grants access_grants_granted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: access_grants access_grants_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: access_grants access_grants_position_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_position_id_fkey FOREIGN KEY (position_id) REFERENCES public.committee_positions(id) ON DELETE CASCADE;


--
-- Name: access_grants access_grants_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: access_grants access_grants_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


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
-- Name: case_activity case_activity_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_activity
    ADD CONSTRAINT case_activity_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: case_activity case_activity_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_activity
    ADD CONSTRAINT case_activity_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: case_activity case_activity_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_activity
    ADD CONSTRAINT case_activity_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: case_categories case_categories_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_categories
    ADD CONSTRAINT case_categories_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: case_categories case_categories_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_categories
    ADD CONSTRAINT case_categories_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.case_categories(id) ON DELETE RESTRICT;


--
-- Name: case_parties case_parties_added_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_parties
    ADD CONSTRAINT case_parties_added_by_fkey FOREIGN KEY (added_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: case_parties case_parties_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_parties
    ADD CONSTRAINT case_parties_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: case_parties case_parties_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_parties
    ADD CONSTRAINT case_parties_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: case_parties case_parties_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_parties
    ADD CONSTRAINT case_parties_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: cases cases_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.case_categories(id) ON DELETE SET NULL;


--
-- Name: cases cases_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id);


--
-- Name: committee_members committee_members_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_members
    ADD CONSTRAINT committee_members_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: committee_members committee_members_position_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_members
    ADD CONSTRAINT committee_members_position_id_fkey FOREIGN KEY (position_id) REFERENCES public.committee_positions(id);


--
-- Name: committee_members committee_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_members
    ADD CONSTRAINT committee_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: committee_positions committee_positions_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_positions
    ADD CONSTRAINT committee_positions_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: cases complaint_cases_assigned_to_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT complaint_cases_assigned_to_id_fkey FOREIGN KEY (assigned_to_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: cases complaint_cases_complainant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT complaint_cases_complainant_id_fkey FOREIGN KEY (complainant_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: cases complaint_cases_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT complaint_cases_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: entity_records entity_records_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_records
    ADD CONSTRAINT entity_records_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


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
-- Name: priority_tat_rules priority_tat_rules_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.priority_tat_rules
    ADD CONSTRAINT priority_tat_rules_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: residents residents_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.residents
    ADD CONSTRAINT residents_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: residents residents_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.residents
    ADD CONSTRAINT residents_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: residents residents_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.residents
    ADD CONSTRAINT residents_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: roles roles_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: routing_rules routing_rules_assign_position_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_rules
    ADD CONSTRAINT routing_rules_assign_position_id_fkey FOREIGN KEY (assign_position_id) REFERENCES public.committee_positions(id) ON DELETE RESTRICT;


--
-- Name: routing_rules routing_rules_assign_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_rules
    ADD CONSTRAINT routing_rules_assign_role_id_fkey FOREIGN KEY (assign_role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;


--
-- Name: routing_rules routing_rules_assign_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_rules
    ADD CONSTRAINT routing_rules_assign_user_id_fkey FOREIGN KEY (assign_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: routing_rules routing_rules_backup_position_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_rules
    ADD CONSTRAINT routing_rules_backup_position_id_fkey FOREIGN KEY (backup_position_id) REFERENCES public.committee_positions(id) ON DELETE SET NULL;


--
-- Name: routing_rules routing_rules_backup_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_rules
    ADD CONSTRAINT routing_rules_backup_role_id_fkey FOREIGN KEY (backup_role_id) REFERENCES public.roles(id) ON DELETE SET NULL;


--
-- Name: routing_rules routing_rules_backup_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_rules
    ADD CONSTRAINT routing_rules_backup_user_id_fkey FOREIGN KEY (backup_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: routing_rules routing_rules_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_rules
    ADD CONSTRAINT routing_rules_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.case_categories(id) ON DELETE CASCADE;


--
-- Name: routing_rules routing_rules_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routing_rules
    ADD CONSTRAINT routing_rules_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


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
-- Name: staff staff_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff
    ADD CONSTRAINT staff_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: staff_attendance staff_attendance_marked_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_attendance
    ADD CONSTRAINT staff_attendance_marked_by_fkey FOREIGN KEY (marked_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: staff_attendance staff_attendance_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_attendance
    ADD CONSTRAINT staff_attendance_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: staff_attendance staff_attendance_staff_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff_attendance
    ADD CONSTRAINT staff_attendance_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES public.staff(id) ON DELETE CASCADE;


--
-- Name: staff staff_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff
    ADD CONSTRAINT staff_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: staff staff_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staff
    ADD CONSTRAINT staff_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


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

\unrestrict AzrPznaKsh9ILVFJXfO42uuX1pHv92LIMxQ62bx1AmiCP3d3s0tVHrASX6MXs4W

