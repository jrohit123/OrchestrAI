# Database inventory

## 0. Sources and limits

Sections 1 to 9 come from three SQL dumps in `C:\Users\karti\Downloads`, parsed by script. **Section 10 is a read-only scan of the live Railway databases on 2026-10-03**, run afterwards at your request. Where the two disagree, section 10 wins.

| Dump | Taken | Role |
|---|---|---|
| `godrej (11).sql` | 2026-10-03 11:13 (file time, 2026-10-03) | Godrej Emerald tenant DB, after migrations 002–010 (case model, Lift story, photos on close, plumbing rule) |
| `baanganga (3).sql` | 2026-09-23 11:30 (2026-09-23) | Baanganga tenant DB; **10 days older**, so some drift below is age, not design |
| `routing_db (3).sql` | 2026-09-23 11:30 (2026-09-23) | Control/routing DB. It contains raw connection strings with passwords: every one is **[REDACTED]** here |

What a dump cannot give (dead tuples, sizes, index usage) is answered in section 10. The six catalog queries are listed in section 9; the live scan ran equivalents of all six. Counts are exact rows in each dump. Personal data, message text and secrets are not printed anywhere in this file.

## 1. Control DB (`routing_db`)

One table, `data_sources`, 2 rows (**VERIFIED** in dump).

| column | type | note |
|---|---|---|
| id | uuid |  |
| source_key | text | also the URL slug of the admin dashboard |
| database_url | text | raw connection string incl. password, stored in plain text. [REDACTED]; user in both is the superuser `postgres` |
| description | text |  |
| created_at | timestamp with |  |
| messaging_channel | text | free text; `get_source_key_for_channel` requires exactly ONE row per channel (db.py:92-110) |

Needed by the target and **missing**: `status` (active, suspended), `industry_pack` and `pack_version`, `schema_version` (applied core migration), `timezone`, `locale`, feature `flags` (jsonb), a **secret reference** instead of the raw URL, per-tenant `channel` config (WhatsApp number id, Telegram bot) and a phone/chat-id → tenant map (today identity scans every tenant DB: `services/identity.py:25`). No migration history for the control DB exists in the repo (no `routing.sql`; the repo docs refer to one).

## 2. Table classification and row counts

### godrej

| table | rows | cols | PK | FKs | class | note | `app/` references |
|---|---|---|---|---|---|---|---|
| access_grants | 0 | 14 | yes | 5 | CONFIG | client capability, 0 rows | 6 |
| admin_events | 5 | 12 | yes | 2 | AUDIT |  | 8 |
| audit_log | 595 | 14 | yes | 2 | AUDIT |  | 24 |
| case_activity | 37 | 7 | yes | 3 | RUNTIME | case timeline | 7 |
| case_categories | 29 | 13 | yes | 2 | CONFIG | category tree | 28 |
| case_parties | 46 | 9 | yes | 4 | RUNTIME | who is on a case | 10 |
| cases | 29 | 19 | yes | 5 | CLIENT-SPECIFIC | business entity of the housing model | 141 |
| committee_members | 4 | 9 | yes | 3 | CLIENT-SPECIFIC | seat holders | 11 |
| committee_positions | 5 | 8 | yes | 1 | CLIENT-SPECIFIC | seats | 21 |
| entity_records | 0 | 10 | yes | 1 | CLIENT-SPECIFIC | generic record store, 0 rows | 30 |
| orgs | 1 | 17 | yes | 0 | CORE | tenant row | 70 |
| otp_tokens | 69 | 9 | yes | 2 | RUNTIME | 69/69 expired, never purged = DEBRIS | 10 |
| pending_approvals | 0 | 13 | yes | 4 | RUNTIME | 0 rows | 11 |
| priority_tat_rules | 4 | 6 | yes | 1 | CONFIG | response times by priority | 11 |
| residents | 9 | 17 | yes | 3 | CLIENT-SPECIFIC | housing people | 24 |
| roles | 6 | 9 | yes | 1 | CORE | also holds permissions = config | 217 |
| routing_rules | 2 | 17 | yes | 8 | CONFIG |  | 12 |
| scheduled_reports | 2 | 19 | yes | 2 | RUNTIME |  | 17 |
| staff | 2 | 14 | yes | 3 | CLIENT-SPECIFIC |  | 4 |
| staff_attendance | 0 | 10 | yes | 3 | CLIENT-SPECIFIC | 0 rows, 0 code references | 0 |
| user_drafts | 84 | 10 | yes | 2 | RUNTIME | 84/84 expired, never purged = DEBRIS | 10 |
| users | 17 | 9 | yes | 2 | CORE |  | 86 |
| workflow_drafts | 8 | 39 | yes | 2 | RUNTIME | builder drafts; 5 of 8 abandoned = DEBRIS | 70 |
| workflow_versions | 4 | 17 | yes | 0 | CONFIG | history; 4 rows for 19 workflows | 8 |
| workflows | 19 | 31 | yes | 1 | CONFIG | definitions | 256 |

### baanganga

| table | rows | cols | PK | FKs | class | note | `app/` references |
|---|---|---|---|---|---|---|---|
| audit_log | 115 | 14 | yes | 2 | AUDIT |  | 24 |
| credentials | 0 | 5 | yes | 1 | CORE | adapter config, 0 rows | 1 |
| customers | 10 | 9 | yes | 1 | CLIENT-SPECIFIC |  | 24 |
| inventory | 22 | 9 | yes | 1 | CLIENT-SPECIFIC |  | 10 |
| invoices | 25 | 12 | yes | 3 | CLIENT-SPECIFIC |  | 32 |
| orders | 13 | 18 | yes | 4 | CLIENT-SPECIFIC |  | 31 |
| orgs | 1 | 17 | yes | 0 | CORE |  | 70 |
| otp_tokens | 35 | 9 | yes | 2 | RUNTIME | 35 rows | 10 |
| pending_approvals | 0 | 13 | yes | 4 | RUNTIME | 0 rows | 11 |
| quotations | 0 | 11 | yes | 3 | CLIENT-SPECIFIC | 0 rows | 11 |
| roles | 4 | 9 | yes | 1 | CORE |  | 217 |
| scheduled_reports | 3 | 20 | yes | 2 | RUNTIME |  | 17 |
| user_drafts | 1 | 9 | yes | 2 | RUNTIME |  | 10 |
| users | 5 | 9 | yes | 2 | CORE |  | 86 |
| workflow_drafts | 3 | 37 | yes | 2 | RUNTIME |  | 70 |
| workflow_versions | 0 | 15 | yes | 0 | CONFIG | 0 rows: nothing ever snapshotted | 8 |
| workflows | 8 | 29 | yes | 1 | CONFIG | 8 definitions | 256 |

Correction: an earlier quick count I gave in chat for Baanganga (1 workflow, 13 versions) was wrong. The parser result above is right: **8 workflows, 0 versions**.

## 3. Columns

### godrej
- **access_grants** (0 rows): id uuid NN, org_id uuid NN, user_id uuid, role_id uuid, position_id uuid, workflow_key text NN, level smallint NN, scope jsonb NN, valid_from date, valid_to date, note text, granted_by uuid, created_at timestamp with NN, revoked_at timestamp with
- **admin_events** (5 rows): id uuid NN, org_id uuid NN, actor_user_id uuid, actor_label text, area text NN, action text NN, target_type text, target_id text, summary text NN, before_state jsonb, after_state jsonb, created_at timestamp with NN
- **audit_log** (595 rows): id uuid NN, org_id uuid NN, user_id uuid, intent_key text, tier integer, input_text text, outcome text, otp_used boolean, steps_taken jsonb, created_at timestamp with, due_date date, pdf_url text, response_text text, session_id text
- **case_activity** (37 rows): id uuid NN, org_id uuid NN, case_id uuid NN, actor_user_id uuid, activity_type character varying(20) NN, payload jsonb NN, created_at timestamp with
- **case_categories** (29 rows): id uuid NN, org_id uuid NN, parent_id uuid, key text NN, label text NN, default_priority character varying(10), target_minutes integer, keywords text[] NN, extra_fields jsonb NN, is_active boolean NN, sort_order integer NN, created_at timestamp with NN, updated_at timestamp with NN
- **case_parties** (46 rows): id uuid NN, org_id uuid NN, case_id uuid NN, user_id uuid NN, party_role text NN, added_by uuid, added_at timestamp with NN, ended_at timestamp with, note text
- **cases** (29 rows): id uuid NN, org_id uuid NN, case_number text NN, complainant_id uuid, title text NN, description text, status character varying(20) NN, priority character varying(10), location text, assigned_to_id uuid, created_at timestamp with, closed_at timestamp with, due_date timestamp with, custom_fields jsonb NN, workflow_id uuid, reminder_sent_at timestamp with, tat_breach_sent_at timestamp with, case_number_norm text, category_id uuid
- **committee_members** (4 rows): id uuid NN, org_id uuid NN, user_id uuid NN, position_id uuid NN, status character varying(20) NN, start_date date, end_date date, access_overrides text[], created_at timestamp with
- **committee_positions** (5 rows): id uuid NN, org_id uuid NN, name text NN, default_permissions text[], created_at timestamp with, slug text, kind text NN, description text
- **entity_records** (0 rows): id uuid NN, org_id uuid NN, entity_type text NN, name text, status text, ref_date date, linked_id uuid, fields jsonb NN, created_at timestamp with NN, updated_at timestamp with NN
- **orgs** (1 rows): id uuid NN, name text NN, slug text NN, industry text, plan text, is_active boolean, created_at timestamp with, session_ttl_minutes integer, context_message_limit integer NN, settings jsonb NN, otp_expiry_minutes integer NN, otp_max_attempts integer NN, otp_length integer NN, otp_resend_cooldown_seconds integer NN, gst_rate numeric(5,2), default_making_charge_pct numeric(5,2), logo_url text
- **otp_tokens** (69 rows): id uuid NN, user_id uuid NN, otp_hash text NN, action_context jsonb, expires_at timestamp with NN, used boolean, attempts integer, created_at timestamp with, org_id uuid NN
- **pending_approvals** (0 rows): id uuid NN, org_id uuid NN, workflow_id uuid, requester_id uuid, approver_role text NN, intent_key text NN, context jsonb, status text, decided_by uuid, decided_at timestamp with, created_at timestamp with, gate_id text, level integer NN
- **priority_tat_rules** (4 rows): id uuid NN, org_id uuid NN, priority character varying(10) NN, tat_minutes integer NN, reminder_threshold_minutes integer NN, created_at timestamp with
- **residents** (9 rows): id uuid NN, org_id uuid NN, user_id uuid, wing text, flat_no text NN, gender character varying(10), residential_status character varying(20) NN, brokers_name text, first_owner_name text, first_owner_mobile text, registration_date date, status character varying(20) NN, approved_by uuid, suspension_date date, created_at timestamp with, name text, custom_fields jsonb NN
- **roles** (6 rows): id uuid NN, org_id uuid NN, name text NN, permissions text[], created_at timestamp with, readable_tables text[] NN, is_approver boolean NN, approval_max_amount numeric(12,2), readable_entity_types text[] NN
- **routing_rules** (2 rows): id uuid NN, org_id uuid NN, name text NN, intent_key text, category_id uuid, match jsonb NN, assign_user_id uuid, assign_position_id uuid, assign_role_id uuid, backup_user_id uuid, backup_position_id uuid, backup_role_id uuid, target_minutes integer, is_active boolean NN, sort_order integer NN, created_at timestamp with NN, updated_at timestamp with NN
- **scheduled_reports** (2 rows): id uuid NN, org_id uuid NN, user_id uuid NN, phone text NN, email text, query_text text NN, report_label text NN, schedule_type character varying(20) NN, interval_minutes integer, hour integer, minute integer, day_of_week character varying(10), day_of_month integer, delivery character varying(20) NN, is_active boolean NN, last_run_at timestamp with, next_run_at timestamp with NN, run_count integer, created_at timestamp with
- **staff** (2 rows): id uuid NN, org_id uuid NN, user_id uuid, name text NN, gender character varying(10), department text, designation text, vendor_name text, status character varying(20) NN, start_date date, end_date date, approved_by uuid, created_at timestamp with, custom_fields jsonb NN
- **staff_attendance** (0 rows): id uuid NN, org_id uuid NN, staff_id uuid NN, attendance_date date NN, check_in timestamp with, check_out timestamp with, status character varying(20) NN, marked_by uuid, custom_fields jsonb NN, created_at timestamp with
- **user_drafts** (84 rows): id uuid NN, org_id uuid NN, user_id uuid NN, intent_key text NN, fields jsonb NN, stage character varying(30) NN, conversation_summary text, updated_at timestamp with NN, expires_at timestamp with NN, created_at timestamp with NN
- **users** (17 rows): id uuid NN, org_id uuid NN, role_id uuid, name text NN, phone text, email text NN, channel text, is_active boolean, created_at timestamp with
- **workflow_drafts** (8 rows): id uuid NN, org_id uuid NN, intent_key text, status character varying(20) NN, purpose text, workflow_type character varying(20), raw_fields jsonb, business_rules text, pdf_sample_analysis jsonb, name text, description text, training_phrases jsonb, entity_schema jsonb, calc_rules jsonb, steps jsonb, sql_template text, sql_params_order jsonb, response_format character varying(50), business_glossary jsonb, llm_system_prompt text, pdf_config jsonb, response_template text, otp_required boolean, otp_threshold numeric(12,2), approval_threshold numeric(12,2), plain_english_summary text, chat_history jsonb, created_at timestamp with, updated_at timestamp with, slash_command character varying(32), command_description character varying(80), menu_section character varying(30), published_workflow_id uuid, granted_roles text[], gates jsonb NN, based_on_version integer, chat_summary text, kind text NN, settings jsonb NN
- **workflow_versions** (4 rows): id uuid NN, workflow_id uuid NN, org_id uuid NN, version integer NN, intent_key text NN, name text, entity_schema jsonb, gates jsonb, granted_roles text[], steps jsonb, calc_rules jsonb, sql_template text, slash_command text, source_draft_id uuid, published_at timestamp with NN, kind text, settings jsonb
- **workflows** (19 rows): id uuid NN, org_id uuid NN, intent_key text NN, name text NN, steps jsonb, is_active boolean, otp_required boolean, otp_threshold numeric(12,2), version integer, last_run timestamp with, created_at timestamp with, scheduled_by uuid, approval_threshold numeric(12,2), description text, workflow_type character varying(20) NN, training_phrases jsonb NN, entity_schema jsonb NN, sql_template text, sql_params_order jsonb NN, response_format character varying(50) NN, business_glossary jsonb NN, llm_system_prompt text, pdf_config jsonb, response_template text, calc_rules jsonb, slash_command character varying(32), command_description character varying(80), menu_section character varying(30) NN, gates jsonb NN, kind text NN, settings jsonb NN

### baanganga
- **audit_log** (115 rows): id uuid NN, org_id uuid NN, user_id uuid, intent_key text, tier integer, input_text text, outcome text, otp_used boolean, steps_taken jsonb, created_at timestamp with, due_date date, pdf_url text, response_text text, session_id text
- **credentials** (0 rows): id uuid NN, org_id uuid NN, adapter_name text NN, config jsonb, created_at timestamp with
- **customers** (10 rows): id uuid NN, org_id uuid NN, name text NN, phone text, email text, gst_number text, city text, credit_limit numeric(12,2), created_at timestamp with
- **inventory** (22 rows): id uuid NN, org_id uuid NN, sku text NN, name text NN, qty integer NN, location text, reorder_level integer, unit_price numeric(12,2), updated_at timestamp with
- **invoices** (25 rows): id uuid NN, org_id uuid NN, invoice_number text NN, customer_id uuid, created_by uuid, items jsonb, amount numeric(12,2) NN, status text, due_date date, paid_at timestamp with, pdf_url text, created_at timestamp with
- **orders** (13 rows): id uuid NN, org_id uuid NN, order_number text NN, quotation_id uuid, customer_id uuid, customer_name text NN, description text NN, metal_type character varying(20), weight_estimate numeric(8,3), estimated_amount numeric(12,2), advance_paid numeric(12,2), status character varying(30), status_history jsonb, expected_delivery date, notes text, created_by uuid, status_updated_at timestamp with, created_at timestamp with
- **orgs** (1 rows): id uuid NN, name text NN, slug text NN, industry text, plan text, is_active boolean, created_at timestamp with, session_ttl_minutes integer, gst_rate numeric(5,2), context_message_limit integer NN, settings jsonb NN, default_making_charge_pct numeric(5,2), otp_expiry_minutes integer NN, otp_max_attempts integer NN, otp_length integer NN, otp_resend_cooldown_seconds integer NN, logo_url text
- **otp_tokens** (35 rows): id uuid NN, user_id uuid NN, otp_hash text NN, action_context jsonb, expires_at timestamp with NN, used boolean, attempts integer, created_at timestamp with, org_id uuid NN
- **pending_approvals** (0 rows): id uuid NN, org_id uuid NN, workflow_id uuid, requester_id uuid, approver_role text NN, intent_key text NN, context jsonb, status text, decided_by uuid, decided_at timestamp with, created_at timestamp with, gate_id text, level integer NN
- **quotations** (0 rows): id uuid NN, org_id uuid NN, quotation_number character varying(50) NN, customer_id uuid NN, items jsonb NN, total_amount numeric(12,2) NN, status character varying(20) NN, valid_until date, created_at timestamp with NN, created_by uuid, updated_at timestamp with
- **roles** (4 rows): id uuid NN, org_id uuid NN, name text NN, permissions text[], created_at timestamp with, readable_tables text[] NN, is_approver boolean NN, approval_max_amount numeric(12,2), readable_entity_types text[] NN
- **scheduled_reports** (3 rows): id uuid NN, org_id uuid NN, user_id uuid NN, phone text NN, email text, query_text text NN, report_label text NN, schedule_type character varying(20) NN, interval_minutes integer, hour integer, minute integer, day_of_week character varying(10), day_of_month integer, delivery character varying(20) NN, is_active boolean NN, last_run_at timestamp with, next_run_at timestamp with NN, run_count integer, created_at timestamp with, source_key character varying(255)
- **user_drafts** (1 rows): id uuid NN, org_id uuid NN, user_id uuid NN, intent_key text NN, fields jsonb NN, stage character varying(30) NN, conversation_summary text, updated_at timestamp with NN, expires_at timestamp with NN
- **users** (5 rows): id uuid NN, org_id uuid NN, role_id uuid, name text NN, phone text, email text NN, channel text, is_active boolean, created_at timestamp with
- **workflow_drafts** (3 rows): id uuid NN, org_id uuid NN, intent_key text, status character varying(20) NN, purpose text, workflow_type character varying(20), raw_fields jsonb, business_rules text, pdf_sample_analysis jsonb, name text, description text, training_phrases jsonb, entity_schema jsonb, calc_rules jsonb, steps jsonb, sql_template text, sql_params_order jsonb, response_format character varying(50), business_glossary jsonb, llm_system_prompt text, pdf_config jsonb, response_template text, otp_required boolean, otp_threshold numeric(12,2), approval_threshold numeric(12,2), plain_english_summary text, chat_history jsonb, created_at timestamp with, updated_at timestamp with, slash_command character varying(32), command_description character varying(80), menu_section character varying(30), published_workflow_id uuid, granted_roles text[], gates jsonb NN, based_on_version integer, chat_summary text
- **workflow_versions** (0 rows): id uuid NN, workflow_id uuid NN, org_id uuid NN, version integer NN, intent_key text NN, name text, entity_schema jsonb, gates jsonb, granted_roles text[], steps jsonb, calc_rules jsonb, sql_template text, slash_command text, source_draft_id uuid, published_at timestamp with NN
- **workflows** (8 rows): id uuid NN, org_id uuid NN, intent_key text NN, name text NN, steps jsonb, is_active boolean, otp_required boolean, otp_threshold numeric(12,2), version integer, last_run timestamp with, created_at timestamp with, scheduled_by uuid, approval_threshold numeric(12,2), description text, workflow_type character varying(20) NN, training_phrases jsonb NN, entity_schema jsonb NN, sql_template text, sql_params_order jsonb NN, response_format character varying(50) NN, business_glossary jsonb NN, llm_system_prompt text, pdf_config jsonb, response_template text, calc_rules jsonb, slash_command character varying(32), command_description character varying(80), menu_section character varying(30) NN, gates jsonb NN

## 4. Constraints

### godrej
- **access_grants**: PRIMARY KEY `access_grants_pkey` PRIMARY KEY (id); FOREIGN KEY `access_grants_granted_by_fkey` FOREIGN KEY (granted_by) REFERENCES public.users(id) ON DELETE SET NULL; FOREIGN KEY `access_grants_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `access_grants_position_id_fkey` FOREIGN KEY (position_id) REFERENCES public.committee_positions(id) ON DELETE CASCADE; FOREIGN KEY `access_grants_role_id_fkey` FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE; FOREIGN KEY `access_grants_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; CHECK `access_grants_dates_check` CONSTRAINT access_grants_dates_check CHECK (((valid_from IS NULL) OR (valid_to IS NULL) OR (valid_to >= valid_from))); CHECK `access_grants_level_check` CONSTRAINT access_grants_level_check CHECK (((level >= 1) AND (level <= 4))); CHECK `access_grants_one_subject` CONSTRAINT access_grants_one_subject CHECK ((num_nonnulls(user_id, role_id, position_id) = 1))
- **admin_events**: PRIMARY KEY `admin_events_pkey` PRIMARY KEY (id); FOREIGN KEY `admin_events_actor_user_id_fkey` FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL; FOREIGN KEY `admin_events_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE
- **audit_log**: PRIMARY KEY `audit_log_pkey` PRIMARY KEY (id); FOREIGN KEY `audit_log_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `audit_log_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL
- **case_activity**: PRIMARY KEY `case_activity_pkey` PRIMARY KEY (id); FOREIGN KEY `case_activity_actor_user_id_fkey` FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL; FOREIGN KEY `case_activity_case_id_fkey` FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE; FOREIGN KEY `case_activity_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; CHECK `case_activity_type_check` CONSTRAINT case_activity_type_check CHECK (((activity_type) = ANY ((ARRAY['comment', 'evidence', 'status_change', 'assignment', 'priority_change', 'ca
- **case_categories**: UNIQUE `case_categories_org_key_key` UNIQUE (org_id, key); PRIMARY KEY `case_categories_pkey` PRIMARY KEY (id); FOREIGN KEY `case_categories_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `case_categories_parent_id_fkey` FOREIGN KEY (parent_id) REFERENCES public.case_categories(id) ON DELETE RESTRICT; CHECK `case_categories_key_check` CONSTRAINT case_categories_key_check CHECK ((key ~ '^[a-z0-9_]+(\.[a-z0-9_]+)*$')); CHECK `case_categories_not_self` CONSTRAINT case_categories_not_self CHECK (((parent_id IS NULL) OR (parent_id <> id))); CHECK `case_categories_priority_check` CONSTRAINT case_categories_priority_check CHECK (((default_priority IS NULL) OR ((default_priority) = ANY ((ARRAY['urgent', 'high', 'medium', 'low'])[; CHECK `case_categories_target_check` CONSTRAINT case_categories_target_check CHECK (((target_minutes IS NULL) OR (target_minutes > 0)))
- **case_parties**: PRIMARY KEY `case_parties_pkey` PRIMARY KEY (id); FOREIGN KEY `case_parties_added_by_fkey` FOREIGN KEY (added_by) REFERENCES public.users(id) ON DELETE SET NULL; FOREIGN KEY `case_parties_case_id_fkey` FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE; FOREIGN KEY `case_parties_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `case_parties_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; CHECK `case_parties_dates_check` CONSTRAINT case_parties_dates_check CHECK (((ended_at IS NULL) OR (ended_at >= added_at))); CHECK `case_parties_role_check` CONSTRAINT case_parties_role_check CHECK ((party_role = ANY (ARRAY['requester', 'assignee', 'level2', 'helper', 'watcher'])))
- **cases**: UNIQUE `complaint_cases_org_case_number_key` UNIQUE (org_id, case_number); PRIMARY KEY `complaint_cases_pkey` PRIMARY KEY (id); FOREIGN KEY `cases_category_id_fkey` FOREIGN KEY (category_id) REFERENCES public.case_categories(id) ON DELETE SET NULL; FOREIGN KEY `cases_workflow_id_fkey` FOREIGN KEY (workflow_id) REFERENCES public.workflows(id); FOREIGN KEY `complaint_cases_assigned_to_id_fkey` FOREIGN KEY (assigned_to_id) REFERENCES public.users(id) ON DELETE SET NULL; FOREIGN KEY `complaint_cases_complainant_id_fkey` FOREIGN KEY (complainant_id) REFERENCES public.users(id) ON DELETE SET NULL; FOREIGN KEY `complaint_cases_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; CHECK `cases_priority_check` CONSTRAINT cases_priority_check CHECK (((priority) = ANY (ARRAY[('urgent'), ('high'), ('medium'), ('low')]))); CHECK `complaint_cases_status_check` CONSTRAINT complaint_cases_status_check CHECK (((status) = ANY (ARRAY[('reported'), ('under_review'), ('action_taken'), ('closed')])))
- **committee_members**: PRIMARY KEY `committee_members_pkey` PRIMARY KEY (id); FOREIGN KEY `committee_members_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `committee_members_position_id_fkey` FOREIGN KEY (position_id) REFERENCES public.committee_positions(id); FOREIGN KEY `committee_members_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; CHECK `committee_members_status_check` CONSTRAINT committee_members_status_check CHECK (((status) = ANY (ARRAY[('active'), ('ended')])))
- **committee_positions**: UNIQUE `committee_positions_org_id_name_key` UNIQUE (org_id, name); PRIMARY KEY `committee_positions_pkey` PRIMARY KEY (id); FOREIGN KEY `committee_positions_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; CHECK `committee_positions_kind_check` CONSTRAINT committee_positions_kind_check CHECK ((kind = ANY (ARRAY['committee', 'volunteer', 'staff', 'security', 'other'])))
- **entity_records**: PRIMARY KEY `entity_records_pkey` PRIMARY KEY (id); FOREIGN KEY `entity_records_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE
- **orgs**: PRIMARY KEY `orgs_pkey` PRIMARY KEY (id); UNIQUE `orgs_slug_key` UNIQUE (slug)
- **otp_tokens**: PRIMARY KEY `otp_tokens_pkey` PRIMARY KEY (id); FOREIGN KEY `otp_tokens_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `otp_tokens_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id)
- **pending_approvals**: PRIMARY KEY `pending_approvals_pkey` PRIMARY KEY (id); FOREIGN KEY `pending_approvals_decided_by_fkey` FOREIGN KEY (decided_by) REFERENCES public.users(id); FOREIGN KEY `pending_approvals_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `pending_approvals_requester_id_fkey` FOREIGN KEY (requester_id) REFERENCES public.users(id); FOREIGN KEY `pending_approvals_workflow_id_fkey` FOREIGN KEY (workflow_id) REFERENCES public.workflows(id)
- **priority_tat_rules**: UNIQUE `priority_tat_rules_org_priority_key` UNIQUE (org_id, priority); PRIMARY KEY `priority_tat_rules_pkey` PRIMARY KEY (id); FOREIGN KEY `priority_tat_rules_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; CHECK `priority_tat_rules_priority_check` CONSTRAINT priority_tat_rules_priority_check CHECK (((priority) = ANY (ARRAY[('urgent'), ('high'), ('medium'), ('low')])))
- **residents**: PRIMARY KEY `residents_pkey` PRIMARY KEY (id); FOREIGN KEY `residents_approved_by_fkey` FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL; FOREIGN KEY `residents_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `residents_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL; CHECK `residents_residential_status_check` CONSTRAINT residents_residential_status_check CHECK (((residential_status) = ANY (ARRAY[('tenant'), ('first_owner'), ('second_owner'), ('other')]))); CHECK `residents_status_check` CONSTRAINT residents_status_check CHECK (((status) = ANY (ARRAY[('active'), ('suspended'), ('inactive'), ('not_residing')])))
- **roles**: UNIQUE `roles_org_id_name_key` UNIQUE (org_id, name); PRIMARY KEY `roles_pkey` PRIMARY KEY (id); FOREIGN KEY `roles_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE
- **routing_rules**: PRIMARY KEY `routing_rules_pkey` PRIMARY KEY (id); FOREIGN KEY `routing_rules_assign_position_id_fkey` FOREIGN KEY (assign_position_id) REFERENCES public.committee_positions(id) ON DELETE RESTRICT; FOREIGN KEY `routing_rules_assign_role_id_fkey` FOREIGN KEY (assign_role_id) REFERENCES public.roles(id) ON DELETE RESTRICT; FOREIGN KEY `routing_rules_assign_user_id_fkey` FOREIGN KEY (assign_user_id) REFERENCES public.users(id) ON DELETE RESTRICT; FOREIGN KEY `routing_rules_backup_position_id_fkey` FOREIGN KEY (backup_position_id) REFERENCES public.committee_positions(id) ON DELETE SET NULL; FOREIGN KEY `routing_rules_backup_role_id_fkey` FOREIGN KEY (backup_role_id) REFERENCES public.roles(id) ON DELETE SET NULL; FOREIGN KEY `routing_rules_backup_user_id_fkey` FOREIGN KEY (backup_user_id) REFERENCES public.users(id) ON DELETE SET NULL; FOREIGN KEY `routing_rules_category_id_fkey` FOREIGN KEY (category_id) REFERENCES public.case_categories(id) ON DELETE CASCADE; FOREIGN KEY `routing_rules_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; CHECK `routing_rules_one_backup` CONSTRAINT routing_rules_one_backup CHECK ((num_nonnulls(backup_user_id, backup_position_id, backup_role_id) <= 1)); CHECK `routing_rules_one_target` CONSTRAINT routing_rules_one_target CHECK ((num_nonnulls(assign_user_id, assign_position_id, assign_role_id) = 1)); CHECK `routing_rules_target_check` CONSTRAINT routing_rules_target_check CHECK (((target_minutes IS NULL) OR (target_minutes > 0)))
- **scheduled_reports**: PRIMARY KEY `scheduled_reports_pkey` PRIMARY KEY (id); FOREIGN KEY `scheduled_reports_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `scheduled_reports_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; CHECK `scheduled_reports_delivery_check` CONSTRAINT scheduled_reports_delivery_check CHECK (((delivery) = ANY (ARRAY[('whatsapp'), ('email'), ('both')]))); CHECK `scheduled_reports_schedule_type_check` CONSTRAINT scheduled_reports_schedule_type_check CHECK (((schedule_type) = ANY (ARRAY[('minutely'), ('hourly'), ('daily'), ('weekly'), ('monthly')])))
- **staff**: PRIMARY KEY `staff_pkey` PRIMARY KEY (id); FOREIGN KEY `staff_approved_by_fkey` FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL; FOREIGN KEY `staff_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `staff_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL; CHECK `staff_status_check` CONSTRAINT staff_status_check CHECK (((status) = ANY (ARRAY[('active'), ('suspended'), ('inactive')])))
- **staff_attendance**: PRIMARY KEY `staff_attendance_pkey` PRIMARY KEY (id); UNIQUE `staff_attendance_staff_date_key` UNIQUE (staff_id, attendance_date); FOREIGN KEY `staff_attendance_marked_by_fkey` FOREIGN KEY (marked_by) REFERENCES public.users(id) ON DELETE SET NULL; FOREIGN KEY `staff_attendance_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `staff_attendance_staff_id_fkey` FOREIGN KEY (staff_id) REFERENCES public.staff(id) ON DELETE CASCADE; CHECK `staff_attendance_status_check` CONSTRAINT staff_attendance_status_check CHECK (((status) = ANY (ARRAY[('present'), ('absent'), ('half_day'), ('on_leave')])))
- **user_drafts**: PRIMARY KEY `user_drafts_pkey` PRIMARY KEY (id); FOREIGN KEY `user_drafts_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `user_drafts_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; CHECK `user_drafts_stage_check` CONSTRAINT user_drafts_stage_check CHECK (((stage) = ANY (ARRAY[('collecting'), ('awaiting_confirmation'), ('awaiting_otp'), ('awaiting_approval'), ('
- **users**: UNIQUE `users_org_id_email_key` UNIQUE (org_id, email); UNIQUE `users_org_id_phone_key` UNIQUE (org_id, phone); PRIMARY KEY `users_pkey` PRIMARY KEY (id); FOREIGN KEY `users_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `users_role_id_fkey` FOREIGN KEY (role_id) REFERENCES public.roles(id)
- **workflow_drafts**: PRIMARY KEY `workflow_drafts_pkey` PRIMARY KEY (id); FOREIGN KEY `workflow_drafts_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `workflow_drafts_published_workflow_id_fkey` FOREIGN KEY (published_workflow_id) REFERENCES public.workflows(id) ON DELETE SET NULL; CHECK `workflow_drafts_kind_check` CONSTRAINT workflow_drafts_kind_check CHECK ((kind = ANY (ARRAY['workflow', 'block', 'case_action']))); CHECK `workflow_drafts_status_check` CONSTRAINT workflow_drafts_status_check CHECK (((status) = ANY (ARRAY[('chatting'), ('ready_for_review'), ('published'), ('abandoned')])))
- **workflow_versions**: PRIMARY KEY `workflow_versions_pkey` PRIMARY KEY (id); CHECK `workflow_versions_kind_check` CONSTRAINT workflow_versions_kind_check CHECK (((kind IS NULL) OR (kind = ANY (ARRAY['workflow', 'block', 'case_action']))))
- **workflows**: UNIQUE `workflows_org_id_intent_key_key` UNIQUE (org_id, intent_key); PRIMARY KEY `workflows_pkey` PRIMARY KEY (id); FOREIGN KEY `workflows_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; CHECK `workflow_type_check` CONSTRAINT workflow_type_check CHECK (((workflow_type) = ANY (ARRAY[('action'), ('read')]))); CHECK `workflows_kind_check` CONSTRAINT workflows_kind_check CHECK ((kind = ANY (ARRAY['workflow', 'block', 'case_action'])))

### baanganga
- **audit_log**: PRIMARY KEY `audit_log_pkey` PRIMARY KEY (id); FOREIGN KEY `audit_log_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `audit_log_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL
- **credentials**: UNIQUE `credentials_org_id_adapter_name_key` UNIQUE (org_id, adapter_name); PRIMARY KEY `credentials_pkey` PRIMARY KEY (id); FOREIGN KEY `credentials_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE
- **customers**: PRIMARY KEY `customers_pkey` PRIMARY KEY (id); FOREIGN KEY `customers_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE
- **inventory**: UNIQUE `inventory_org_id_sku_key` UNIQUE (org_id, sku); PRIMARY KEY `inventory_pkey` PRIMARY KEY (id); FOREIGN KEY `inventory_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE
- **invoices**: UNIQUE `invoices_org_id_invoice_number_key` UNIQUE (org_id, invoice_number); PRIMARY KEY `invoices_pkey` PRIMARY KEY (id); FOREIGN KEY `invoices_created_by_fkey` FOREIGN KEY (created_by) REFERENCES public.users(id); FOREIGN KEY `invoices_customer_id_fkey` FOREIGN KEY (customer_id) REFERENCES public.customers(id); FOREIGN KEY `invoices_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE
- **orders**: UNIQUE `orders_org_id_order_number_key` UNIQUE (org_id, order_number); PRIMARY KEY `orders_pkey` PRIMARY KEY (id); FOREIGN KEY `orders_created_by_fkey` FOREIGN KEY (created_by) REFERENCES public.users(id); FOREIGN KEY `orders_customer_id_fkey` FOREIGN KEY (customer_id) REFERENCES public.customers(id); FOREIGN KEY `orders_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `orders_quotation_id_fkey` FOREIGN KEY (quotation_id) REFERENCES public.quotations(id) ON DELETE SET NULL
- **orgs**: PRIMARY KEY `orgs_pkey` PRIMARY KEY (id); UNIQUE `orgs_slug_key` UNIQUE (slug)
- **otp_tokens**: PRIMARY KEY `otp_tokens_pkey` PRIMARY KEY (id); FOREIGN KEY `otp_tokens_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `otp_tokens_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id)
- **pending_approvals**: PRIMARY KEY `pending_approvals_pkey` PRIMARY KEY (id); FOREIGN KEY `pending_approvals_decided_by_fkey` FOREIGN KEY (decided_by) REFERENCES public.users(id); FOREIGN KEY `pending_approvals_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `pending_approvals_requester_id_fkey` FOREIGN KEY (requester_id) REFERENCES public.users(id); FOREIGN KEY `pending_approvals_workflow_id_fkey` FOREIGN KEY (workflow_id) REFERENCES public.workflows(id)
- **quotations**: UNIQUE `quotations_org_id_quotation_number_key` UNIQUE (org_id, quotation_number); PRIMARY KEY `quotations_pkey` PRIMARY KEY (id); FOREIGN KEY `fk_quotations_created_by` FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL; FOREIGN KEY `fk_quotations_customer` FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE CASCADE; FOREIGN KEY `fk_quotations_org` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE
- **roles**: UNIQUE `roles_org_id_name_key` UNIQUE (org_id, name); PRIMARY KEY `roles_pkey` PRIMARY KEY (id); FOREIGN KEY `roles_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE
- **scheduled_reports**: PRIMARY KEY `scheduled_reports_pkey` PRIMARY KEY (id); FOREIGN KEY `scheduled_reports_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `scheduled_reports_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; CHECK `scheduled_reports_delivery_check` CONSTRAINT scheduled_reports_delivery_check CHECK (((delivery) = ANY (ARRAY[('whatsapp'), ('email'), ('both')]))); CHECK `scheduled_reports_schedule_type_check` CONSTRAINT scheduled_reports_schedule_type_check CHECK (((schedule_type) = ANY (ARRAY[('minutely'), ('hourly'), ('daily'), ('weekly'), ('monthly')])))
- **user_drafts**: PRIMARY KEY `user_drafts_pkey` PRIMARY KEY (id); FOREIGN KEY `user_drafts_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `user_drafts_user_id_fkey` FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; CHECK `user_drafts_stage_check` CONSTRAINT user_drafts_stage_check CHECK (((stage) = ANY (ARRAY[('collecting'), ('awaiting_confirmation'), ('awaiting_otp'), ('awaiting_approval'), ('
- **users**: UNIQUE `users_org_id_phone_key` UNIQUE (org_id, phone); PRIMARY KEY `users_pkey` PRIMARY KEY (id); FOREIGN KEY `users_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `users_role_id_fkey` FOREIGN KEY (role_id) REFERENCES public.roles(id)
- **workflow_drafts**: PRIMARY KEY `workflow_drafts_pkey` PRIMARY KEY (id); FOREIGN KEY `workflow_drafts_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; FOREIGN KEY `workflow_drafts_published_workflow_id_fkey` FOREIGN KEY (published_workflow_id) REFERENCES public.workflows(id) ON DELETE SET NULL; CHECK `workflow_drafts_status_check` CONSTRAINT workflow_drafts_status_check CHECK (((status) = ANY (ARRAY[('chatting'), ('ready_for_review'), ('published'), ('abandoned')])))
- **workflow_versions**: PRIMARY KEY `workflow_versions_pkey` PRIMARY KEY (id)
- **workflows**: UNIQUE `workflows_org_id_intent_key_key` UNIQUE (org_id, intent_key); PRIMARY KEY `workflows_pkey` PRIMARY KEY (id); FOREIGN KEY `workflows_org_id_fkey` FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE; CHECK `workflow_type_check` CONSTRAINT workflow_type_check CHECK (((workflow_type) = ANY (ARRAY[('action'), ('read')])))

## 5. Indexes, triggers, functions

### godrej indexes
- **access_grants**: idx_access_grants_position, idx_access_grants_role, idx_access_grants_user
- **admin_events**: idx_admin_events_org_time, idx_admin_events_target
- **audit_log**: idx_audit_created, idx_audit_org_id
- **case_activity**: idx_case_activity_case, idx_case_activity_type
- **case_categories**: idx_case_categories_parent
- **case_parties**: case_parties_one_active_assignee_key (unique), case_parties_one_active_role_key (unique), idx_case_parties_case, idx_case_parties_user
- **cases**: idx_cases_assigned, idx_cases_category, idx_cases_complainant, idx_cases_custom_fields, idx_cases_number_norm, idx_cases_number_norm_trgm, idx_cases_org, idx_cases_org_status
- **committee_members**: idx_committee_members_org, idx_committee_one_active_per_position (unique)
- **committee_positions**: committee_positions_org_slug_key (unique)
- **entity_records**: entity_records_fields_gin_idx, entity_records_org_type_idx
- **otp_tokens**: idx_otp_org, idx_otp_user_expiry
- **pending_approvals**: idx_approvals_org_requester, idx_approvals_org_status
- **residents**: idx_residents_custom_fields, idx_residents_org, idx_residents_user, idx_residents_wing_flat
- **routing_rules**: idx_routing_rules_org_category
- **scheduled_reports**: idx_scheduled_reports_next_run, idx_scheduled_reports_org, idx_scheduled_reports_user
- **staff**: idx_staff_custom_fields, idx_staff_org, idx_staff_user
- **staff_attendance**: idx_staff_attendance_custom_fields, idx_staff_attendance_org
- **user_drafts**: idx_user_drafts_expiry, one_active_draft_per_user (unique)
- **users**: idx_users_org_id, idx_users_phone
- **workflow_drafts**: idx_workflow_drafts_org_intent_active (unique), idx_workflow_drafts_org_status, idx_workflow_drafts_org_updated
- **workflow_versions**: idx_workflow_versions_workflow
- **workflows**: idx_workflows_org_intent, idx_workflows_org_kind, idx_workflows_org_type

### baanganga indexes
- **audit_log**: idx_audit_created, idx_audit_org_id
- **customers**: idx_customers_name_trgm
- **inventory**: idx_inventory_name_trgm
- **user_drafts**: one_active_draft_per_user (unique)
- **workflow_drafts**: idx_workflow_drafts_org_intent_active (unique)
- **workflow_versions**: idx_workflow_versions_workflow
- **workflows**: workflows_org_slash_cmd (unique)

### godrej triggers
- `trg_case_categories_guard` on **case_categories** → `public.case_categories_guard`
- `trg_case_categories_updated` on **case_categories** → `public.set_updated_at`
- `trg_committee_positions_default_slug` on **committee_positions** → `public.committee_positions_default_slug`
- `trg_routing_rules_updated` on **routing_rules** → `public.set_updated_at`
- `trg_sync_case_parties` on **cases** → `public.sync_case_parties_from_case`
- `trg_sync_committee_role` on **committee_members** → `public.sync_committee_role_to_user`
- `trg_sync_resident_status` on **residents** → `public.sync_resident_status_to_user`
- `trg_sync_staff_status` on **staff** → `public.sync_staff_status_to_user`

### godrej functions (logic that lives in the database)
- `case_categories_guard()` returns trigger, 497 chars of body
- `case_relations(p_case uuid, p_user uuid)` returns TABLE(is_requester boolean, is_assignee , 2399 chars of body
- `committee_positions_default_slug()` returns trigger, 183 chars of body
- `route_case(p_org uuid, p_category uuid, p_context jsonb DEFAULT '{}'::jsonb, p_in)` returns TABLE(rule_id uuid, rule_name text, assi, 2558 chars of body
- `route_targets(p_org uuid, p_user uuid, p_position uuid, p_role uuid)` returns uuid[], 767 chars of body
- `set_updated_at()` returns trigger, 57 chars of body
- `sync_case_parties_from_case()` returns trigger, 1606 chars of body
- `sync_committee_role_to_user()` returns trigger, 767 chars of body
- `sync_resident_status_to_user()` returns trigger, 302 chars of body
- `sync_staff_status_to_user()` returns trigger, 301 chars of body

### baanganga triggers and functions
- none
- `uuid_generate_v7()` returns uuid, 426 chars of body

Extensions: godrej pg_trgm; baanganga pg_trgm, pgcrypto.

## 6. JSONB key frequency

Key names and counts only (**VERIFIED**: parsed from the dump rows). Columns with no rows are omitted.

### godrej
| column | rows | non-null | JSON type | distinct key-sets | most frequent keys (count) |
|---|---|---|---|---|---|
| admin_events.before_state | 5 | 2 | {'dict': 2, 'NULL': 3} | 1 | id:2, kind:2, name:2, gates:2, steps:2, org_id:2, version:2, last_run:2 |
| admin_events.after_state | 5 | 2 | {'NULL': 3, 'dict': 2} | 1 | name:2, match:2, assign:2, backup:2, is_active:2, intent_key:2, category_id:2, target_minutes:2 |
| audit_log.steps_taken | 595 | 595 | {'list': 595} | 0 | — |
| case_activity.payload | 37 | 37 | {'dict': 37} | 6 | to:12, to_name:11, to_user_id:11, text:7, closing_note:7, telegram_file_id:7, by:4 |
| case_categories.extra_fields | 29 | 29 | {'list': 29} | 0 | key:2, type:2, label:2, options:1 |
| cases.custom_fields | 29 | 29 | {'dict': 29} | 1 | — |
| orgs.settings | 1 | 1 | {'dict': 1} | 1 | vocabulary:1, case_reminders:1 |
| otp_tokens.action_context | 69 | 69 | {'dict': 69} | 1 | type:69 |
| residents.custom_fields | 9 | 9 | {'dict': 9} | 1 | — |
| routing_rules.match | 2 | 2 | {'dict': 2} | 1 | — |
| staff.custom_fields | 2 | 2 | {'dict': 2} | 1 | — |
| user_drafts.fields | 84 | 84 | {'dict': 84} | 15 | title:36, location:35, priority:35, case_number:33, action:21, comment_text:19, description:16, assignee_name:14 |
| workflow_drafts.raw_fields | 8 | 8 | {'list': 8} | 0 | — |
| workflow_drafts.pdf_sample_analysis | 8 | 0 | {'NULL': 8} | 0 | — |
| workflow_drafts.training_phrases | 8 | 8 | {'list': 8} | 0 | — |
| workflow_drafts.entity_schema | 8 | 8 | {'dict': 8} | 3 | priority:5, case_number:5, status:3, assigned_to:3, title:2, due_date:2, location:2, description:2 |
| workflow_drafts.calc_rules | 8 | 8 | {'dict': 8} | 1 | — |
| workflow_drafts.steps | 8 | 8 | {'list': 8} | 0 | op:8, params:8 |
| workflow_drafts.sql_params_order | 8 | 8 | {'list': 8} | 0 | — |
| workflow_drafts.business_glossary | 8 | 8 | {'dict': 8} | 3 | status:3, priority:3, assigned_to:3, case_number:3, band:3, baaki:3, khula:3, case:2 |
| workflow_drafts.pdf_config | 8 | 6 | {'NULL': 2, 'dict': 6} | 2 | doc_type:6, title_template:6, theme:3, render_instructions:3, insight_focus:3, aging_analysis:3, show_key_insights:3 |
| workflow_drafts.chat_history | 8 | 8 | {'list': 8} | 0 | role:12, content:12 |
| workflow_drafts.gates | 8 | 8 | {'list': 8} | 0 | — |
| workflow_drafts.settings | 8 | 8 | {'dict': 8} | 1 | — |
| workflow_versions.entity_schema | 4 | 4 | {'dict': 4} | 3 | case_number:4, priority:3, status:2, assigned_to:2, action:1, comment_text:1, assignee_name:1, title:1 |
| workflow_versions.gates | 4 | 4 | {'list': 4} | 0 | — |
| workflow_versions.steps | 4 | 4 | {'list': 4} | 0 | op:17, params:17, when:11 |
| workflow_versions.calc_rules | 4 | 4 | {'dict': 4} | 1 | — |
| workflow_versions.settings | 4 | 2 | {'NULL': 2, 'dict': 2} | 1 | — |
| workflows.steps | 19 | 19 | {'list': 19} | 0 | op:52, params:52, when:15 |
| workflows.training_phrases | 19 | 19 | {'list': 19} | 0 | — |
| workflows.entity_schema | 19 | 19 | {'dict': 19} | 13 | case_number:5, comment_text:4, priority:3, assignee_name:2, tell_text:2, tell_prefix:2, note:2, title:2 |
| workflows.sql_params_order | 19 | 19 | {'list': 19} | 0 | — |
| workflows.business_glossary | 19 | 19 | {'dict': 19} | 3 | band:1, baaki:1, khula:1, status:1, priority:1, assigned_to:1, case_number:1 |
| workflows.pdf_config | 19 | 2 | {'NULL': 17, 'dict': 2} | 2 | doc_type:2, title_template:2, insight_focus:1, aging_analysis:1, show_key_insights:1, theme:1, render_instructions:1 |
| workflows.calc_rules | 19 | 19 | {'dict': 19} | 1 | — |
| workflows.gates | 19 | 19 | {'list': 19} | 0 | — |
| workflows.settings | 19 | 19 | {'dict': 19} | 4 | who_can_use:5, photos:3 |

### baanganga
| column | rows | non-null | JSON type | distinct key-sets | most frequent keys (count) |
|---|---|---|---|---|---|
| audit_log.steps_taken | 115 | 115 | {'list': 115} | 0 | — |
| invoices.items | 25 | 25 | {'list': 25} | 0 | gst:21, qty:21, total:21, unit_price:21, description:21 |
| orders.status_history | 13 | 13 | {'list': 13} | 0 | status:37, updated_at:20, updated_by:3 |
| orgs.settings | 1 | 1 | {'dict': 1} | 1 | vocabulary:1, dashboard_stats:1 |
| otp_tokens.action_context | 35 | 35 | {'dict': 35} | 1 | type:35 |
| user_drafts.fields | 1 | 1 | {'dict': 1} | 1 | items:1, amount:1, customer_city:1, customer_name:1, customer_gstin:1 |
| workflow_drafts.raw_fields | 3 | 3 | {'list': 3} | 0 | — |
| workflow_drafts.pdf_sample_analysis | 3 | 0 | {'NULL': 3} | 0 | — |
| workflow_drafts.training_phrases | 3 | 3 | {'list': 3} | 0 | — |
| workflow_drafts.entity_schema | 3 | 3 | {'dict': 3} | 3 | customer_name:1, item_name:1 |
| workflow_drafts.calc_rules | 3 | 3 | {'dict': 3} | 1 | — |
| workflow_drafts.steps | 3 | 3 | {'list': 3} | 0 | — |
| workflow_drafts.sql_params_order | 3 | 3 | {'list': 3} | 0 | — |
| workflow_drafts.business_glossary | 3 | 3 | {'dict': 3} | 3 | aging:1, baaki:1, udhaar:1, risk report:1, purana baaki:1, collection report:1, SKU:1, stock:1 |
| workflow_drafts.pdf_config | 3 | 1 | {'dict': 1, 'NULL': 2} | 1 | doc_type:1, insight_focus:1, aging_analysis:1, title_template:1, show_key_insights:1 |
| workflow_drafts.chat_history | 3 | 3 | {'list': 3} | 0 | role:9, content:9 |
| workflow_drafts.gates | 3 | 3 | {'list': 3} | 0 | — |
| workflows.steps | 8 | 8 | {'list': 8} | 0 | op:24, params:24 |
| workflows.training_phrases | 8 | 8 | {'list': 8} | 0 | — |
| workflows.entity_schema | 8 | 8 | {'dict': 8} | 7 | customer_name:3, po_id:2, items:2, subtotal:2, gst_amount:2, total_amount:2, making_charges_total:2, new_status:1 |
| workflows.sql_params_order | 8 | 8 | {'list': 8} | 0 | — |
| workflows.business_glossary | 8 | 8 | {'dict': 8} | 8 | rate:2, making charges:2, pending:1, received:1, invoice:1, PO:1, bhav:1, raw material:1 |
| workflows.pdf_config | 8 | 4 | {'NULL': 4, 'dict': 3, 'NoneType': 1} | 2 | doc_type:3, title_template:3, insight_focus:1, aging_analysis:1, show_key_insights:1 |
| workflows.calc_rules | 8 | 8 | {'dict': 8} | 3 | aggregate_rules:3, item_rules:2 |
| workflows.gates | 8 | 8 | {'list': 8} | 0 | — |

## 7. Analysis

### 7.1 Classification

CORE (should be identical): `orgs`, `users`, `roles`, `otp_tokens`, `scheduled_reports`, `user_drafts`, `pending_approvals`, `credentials`. CONFIG (should be versioned JSON): `workflows`, `workflow_versions`, `routing_rules`, `case_categories`, `priority_tat_rules`, `access_grants`, `orgs.settings`. AUDIT: `audit_log`, `admin_events`. DEBRIS: `user_drafts` (84 of 84 expired), `otp_tokens` (69 of 69 expired in godrej), `workflow_drafts` (5 of 8 abandoned). CLIENT-SPECIFIC: godrej `cases`, `case_*`, `committee_*`, `residents`, `staff`, `staff_attendance`, `entity_records`; baanganga `customers`, `inventory`, `invoices`, `orders`, `quotations`.

The brief says client differences must live in JSON, never in per-client tables. Today **20 tables exist in only one DB** (14 in godrej, 6 in baanganga); 11 are shared. The engine can write to any table, so this works, but the claim 'one shared schema everywhere' is false today.

### 7.2 Cross-tenant diff (godrej vs baanganga)

- Tables only in godrej: access_grants, admin_events, case_activity, case_categories, case_parties, cases, committee_members, committee_positions, entity_records, priority_tat_rules, residents, routing_rules, staff, staff_attendance.
- Tables only in baanganga: credentials, customers, inventory, invoices, orders, quotations.
- Columns that differ in the 11 shared platform tables: `scheduled_reports`: +source_key (baanganga); `user_drafts`: +created_at (godrej); `workflow_drafts`: +kind (godrej), +settings (godrej); `workflow_versions`: +kind (godrej), +settings (godrej); `workflows`: +kind (godrej), +settings (godrej).
- `scheduled_reports.source_key` exists **only** in baanganga; `users (org_id,email)` unique and `user_drafts.created_at` only in godrej.
- Indexes on shared tables present in godrej and absent in baanganga: idx_approvals_org_requester, idx_approvals_org_status, idx_otp_org, idx_otp_user_expiry, idx_scheduled_reports_next_run, idx_scheduled_reports_org, idx_scheduled_reports_user, idx_user_drafts_expiry, idx_users_org_id, idx_users_phone, idx_workflow_drafts_org_status, idx_workflow_drafts_org_updated, idx_workflows_org_intent, idx_workflows_org_kind, idx_workflows_org_type. Baanganga has **no index on `users.phone`** although `identity.py:25` filters on it for every incoming message, and none on `otp_tokens`, `pending_approvals` or `scheduled_reports`. It is small today, so nobody noticed.
- Functions: godrej has 10 (case routing, party sync, seat→role sync); baanganga has 1 (`uuid_generate_v7`). Triggers: godrej 8, baanganga 0. Extensions: baanganga has `pgcrypto`, godrej does not.
- **Migration history table: none in either DB** (no `schema_migrations`, no `alembic_version`). Migrations are hand-run SQL files in `migrations/`, named per client. Drift is therefore present and undetectable except by diffing, as I just did. Part of it is simply that baanganga's dump is 10 days older, which proves the point.

### 7.3 Columns and JSON

- **Move into JSON attributes (client-specific or sparse):** `orgs.gst_rate`, `orgs.default_making_charge_pct` (godrej NULL, baanganga set; jewellery concepts on the shared tenant table; read at `agent.py:873`). Housing columns `residents.wing`, `flat_no`, `brokers_name`, `first_owner_*` are fine as a client table but are the reason an 'extra field on people' is not generic.
- **Duplicated rule:** `workflows.otp_required/otp_threshold/approval_threshold` duplicate the `gates` JSON. Live data: `gates` is empty in all 27 workflows of both tenants, so the **multi-level approval chain has zero live definitions**. Baanganga has 2 `approval_gate` and 2 `otp_gate` steps, but every `otp_required`, `otp_threshold` and `approval_threshold` is NULL/false, so the gate finds no queue and passes (`step_interpreter.py:868-881`): approval and OTP exist on paper only in both tenants as dumped.
- **Promote JSON to columns:** none justified yet. The hot JSON reads are `workflows.settings` (photos, who_can_use) and `orgs.settings`, both small. Do not promote. Instead stop the `to_jsonb(w)` indirection (`party_access.py:30`) once every tenant has the column.
- **JSON that is never used:** `cases.custom_fields`, `residents.custom_fields`, `staff.custom_fields`, `routing_rules.match`, `workflows.calc_rules` have **0 keys in every row** (godrej: 29, 9, 2, 2 and 19 rows). Five GIN indexes cover empty JSON (`idx_cases_custom_fields`, `idx_residents_custom_fields`, `idx_staff_custom_fields`, `idx_staff_attendance_custom_fields`, `entity_records_fields_gin_idx`). `audit_log.steps_taken` is an empty list in all 595 rows.
- **JSON without validation:** all of it. No JSON-Schema or CHECK on `steps`, `entity_schema`, `gates`, `settings`, `orgs.settings`. Shapes vary: `workflows.entity_schema` has 13 distinct key-sets across 19 rows; `user_drafts.fields` has 15 across 84.
- **Status/type lists enforced as CHECK that are really data:** `cases.status` (reported, under_review, action_taken, closed: `complaint_cases_status_check`), `cases.priority` and `priority_tat_rules.priority` (urgent, high, medium, low), `case_activity.activity_type`, `case_parties.party_role`, `committee_positions.kind`, `residents.status`, `residents.residential_status`. Meanwhile `orgs.settings.case_reminders.closed_values` pretends statuses are configurable. A client who wants a fifth status needs a core migration.

### 7.4 Integrity

- FK count: godrej 62, baanganga 31; every table has a primary key. 34 of 62 godrej FKs `ON DELETE CASCADE` (an org or user delete reaches far).
- Columns named `*_id` with no FK in godrej: admin_events.target_id, audit_log.session_id, entity_records.linked_id, pending_approvals.gate_id, workflow_versions.workflow_id, workflow_versions.org_id, workflow_versions.source_draft_id.
- Columns named `*_id` with no FK in baanganga: audit_log.session_id, pending_approvals.gate_id, workflow_versions.workflow_id, workflow_versions.org_id, workflow_versions.source_draft_id.
- **Soft references by name (no FK possible):** `user_drafts.intent_key` → 64 godrej drafts point at workflows that no longer exist (`register_complaint` 31, `assign_case` 21, `release_meeting_minutes` 8, `add_new_resident` 4). `roles.permissions` (text[] of workflow keys) names workflows that do not exist: `general_read` (6 roles), `view_my_cases` (6), `get_resident_cases_status` (2); none of these strings is in the code. `workflow_versions` has 2 orphan snapshots (their workflow was deleted). `audit_log.intent_key` is a free string.
- `workflows` has both `UNIQUE (org_id, intent_key)` and a duplicate non-unique index `idx_workflows_org_intent` on the same columns (godrej).
- Orphans through FKs: none found (`case_activity` → `cases`: 0 orphans).
- Indexes the code actually needs but lacks: `audit_log(session_id)` (the Activity transcript and the chat list group by it: `admin_panel/activity.py:46-57`, `routers/admin.py` session endpoint); `users(phone)` in baanganga.

### 7.5 Versioning

- Versioned: `workflows` → `workflow_versions` (godrej 4 rows for 19 workflows; baanganga 0 for 8). Version column values in godrej: 18 workflows at version 1, one at 3.
- **History is incomplete by design:** `workflow_versions` has no description, training phrases, response format, response template, PDF config, glossary, LLM prompt, thresholds, menu section or command description (18 columns of `workflows` are not snapshotted).
- **Runs are not pinned:** `user_drafts`, `pending_approvals`, `audit_log` and `cases.workflow_id` carry no version. `action_executor.py:48` loads the latest definition by `intent_key`.
- **Bypass paths:** all of `migrations/godrej_002…010` edit live definitions with SQL and no version bump or snapshot; `admin_events` (5 rows) records none of them; baanganga's classic admin path writes without `admin_events`.

### 7.6 Unused objects (zero rows AND no code references; both shown)

| object | rows | references in `app/` | verdict |
|---|---|---|---|
| godrej.staff_attendance | 0 | 0 (and 0 workflow definitions) | **candidate for removal**, after confirming with the client that attendance is not planned |
| godrej.access_grants | 0 | 6 (admin screens only; the bot never reads it) | feature unused; keep, finish or hide (decision) |
| godrej.entity_records | 0 | 30 | in use by code; empty, keep |
| godrej/baanganga.pending_approvals | 0 / 0 | 11 | in use by code; empty because no gate has ever been triggered in these dumps |
| baanganga.quotations | 0 | 11 | in use by code; empty |
| baanganga.credentials | 0 | 1 | keep (adapter config) |
| godrej `workflows.calc_rules`, `gates`, `audit_log.steps_taken` (columns) | all empty | referenced | features with no live data |

### 7.7 Control DB vs needs

See section 1. Gaps: status, pack, pack version, schema version, timezone, locale, flags, secret reference, channel config, identity map.

### 7.8 Data quality (counts only)

| check | result |
|---|---|
| godrej.user_drafts: expired and still stored | 84 |
| godrej.otp_tokens: expired | 69 |
| godrej.cases: no category | 24 |
| godrej.cases: open | 22 |
| godrej.cases: open and unassigned | 19 |
| godrej.cases: open and past due (as of dump) | 22 |
| godrej.audit_log: outcome values | {'success': 595} |
| godrej.audit_log: steps_taken non-empty | 0 |
| godrej.audit_log: user_id null | 26 |
| godrej.workflows: version values | {'1': 18, '3': 1} |
| godrej.workflows: with a snapshot in workflow_versions (distinct) | 3 |
| godrej.workflow_drafts: status | {'abandoned': 5, 'published': 2, 'ready_for_review': 1} |
| godrej.priority_tat_rules: ordering contradiction (urgent<=high<=medium<=low expected) | {'urgent': 120, 'high': 480, 'medium': 1440, 'low': 10} |
| godrej.case_categories: with own target_minutes | 1/29 |
| godrej.users: phone null | 11 |
| baanganga.otp_tokens | 35 |
| baanganga.workflow_versions | 0 |

Readings: no job purges drafts or OTPs (`draft_store.py` only updates stage); all 595 audit outcomes are 'success' even where a workflow failed, so the column means 'the turn was handled'; Low priority gets 10 minutes while Urgent gets 120; 22 of 22 open cases are past due and 19 of 22 are unassigned (mostly pre-routing test cases).

## 8. Hidden behaviour in the database

- `sync_committee_role_to_user` (trigger on `committee_members`) changes a user's role to or from 'committee' when a seat is taken or left. Correct design for 'DB holds logic', but it is a side effect no workflow shows and no audit row records.
- `sync_case_parties_from_case` keeps requester and assignee rows in `case_parties` in step with `cases`. `route_case` and `case_relations` carry the routing and access rules in SQL; their bodies contain only the literals 'backup', 'nobody available', 'rule' (no business constants).
- `sync_resident_status_to_user`, `sync_staff_status_to_user` mirror status into `users.is_active`.

## 9. Read-only catalog queries to run on the live databases

Not run. Start each session with `SET default_transaction_read_only = on;`.

```sql
SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='public' ORDER BY 1, ordinal_position;
SELECT conrelid::regclass, conname, contype, pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace='public'::regnamespace;
SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname='public';
SELECT event_object_table, trigger_name, action_statement FROM information_schema.triggers;
SELECT proname, pg_get_functiondef(oid) FROM pg_proc WHERE pronamespace='public'::regnamespace;
SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, pg_total_relation_size(relid) FROM pg_stat_user_tables;
```

## 10. Live scan of the Railway databases (read-only, 2026-10-03)

**Method (VERIFIED).** The Railway project `OrchestrAI - Sep26` (environment `production`) has four services: the app and three Postgres 18.6 databases `godrej`, `baanganga`, `routing_db`. I ran one script through the Railway CLI with the app's own environment. Every session was `default_transaction_read_only = on` with a 20 s statement timeout; the connection strings were read from the environment and never printed. Only structure, counts, dates and key names were selected: no names, phone numbers, message text or tokens. The script and its output were deleted from the scratch folder afterwards. The Redis used for sessions is not a Railway service in this project and was **not inspected**.

| | routing_db | baanganga | godrej |
|---|---|---|---|
| Size | 7.9 MB | 9.3 MB | 11.8 MB |
| Tables | 1 | 17 | 25 |
| Login role | `postgres` **superuser** | `postgres` **superuser** | `postgres` **superuser** |
| Other roles | none | none | none |
| Extensions | plpgsql | pg_trgm, pgcrypto | pg_trgm, uuid-ossp |
| Migration-history table | none | none | none |
| Database timezone | UTC (the app forces IST per connection) | UTC | UTC |
| `max_connections` / open now | 500 / 3 | 500 / 3 | 500 / 3 |

### 10.1 What the live scan confirms
- **The Godrej dump is exactly current.** Every row count matches the 3 Oct dump (595 audit rows, 84 drafts, 19 workflows, 29 cases, 46 case-party rows…). Question 5 in the summary is therefore answered for Godrej.
- **Baanganga has moved on since its dump**: `audit_log` 120 rows (115 in the dump), `otp_tokens` 37 (35); last activity 2026-09-28.
- **Superuser everywhere (VERIFIED live).** There is no application role, no read-only role, no migrator. The 'read-only' guard is a session flag on a superuser login.
- **No migration history anywhere** (no `schema_migrations`, `alembic_version`).
- Live schema equals the dump schema for both tenants (same tables, same user triggers: 8 in Godrej, 0 in Baanganga; same 10 user functions in Godrej). Drift confirmed: Baanganga has no index on `users(phone)` and `user_drafts` has no `created_at`; neither tenant has an index on `audit_log(session_id)`.
- Dead permission strings: Godrej `general_read` (6 roles), `view_my_cases` (6), `get_resident_cases_status` (2); Baanganga `general_read` (4 roles).
- Live JSON that is empty: `cases/residents/staff.custom_fields`, `routing_rules.match`, `workflows.calc_rules` and `gates` in Godrej, `gates` in Baanganga, `audit_log.steps_taken` in both. Baanganga's `calc_rules` is the one live use of that column (`aggregate_rules` in 3 workflows, `item_rules` in 2).

### 10.2 New findings the dumps could not show
1. **`workflows.last_run` is NULL on all 27 workflows** (0 of 19 Godrej, 0 of 8 Baanganga) although workflows have created 25 invoices, 13 orders and 29 cases. No code writes it: `grep last_run` finds only reads (`admin_panel/workflows.py:72`, `routers/admin.py:238`). It is a dead column, which is why the old dashboard showed 'never' for every workflow.
2. **Only 1 of the 19 live Godrej workflows has any version snapshot** (`check_case_status`, 2 snapshots). The other 2 snapshots belong to deleted workflows (`assign_case`, `register_complaint`) and are the 2 orphans. Baanganga has 0.
3. **Every-minute jobs scan whole tables.** Sequential-scan counts since stats began: `cases` 45,583 (1 index scan), `orgs` 32,722 (Godrej) and 21,272 (Baanganga), `scheduled_reports` about 20,580 on both, `users` 22,386 (Godrej). That is the scheduler's two passes plus per-message org lookups. Harmless at 29 rows; it is the first thing that will hurt at 100 times the data. Partial indexes (see `proposed-schema.sql` P1-03) fix it.
4. **Index usage is mostly zero because the tables are tiny.** 43 of 90 Godrej indexes and 14 of 34 Baanganga indexes have 0 scans. I did not capture when the statistics were reset, so I make **no drop recommendation from this** except for the five GIN indexes over JSON that holds no keys.
5. **Autovacuum has barely run.** Godrej: `audit_log` and `otp_tokens` on 18 Sept; `cases`, `user_drafts`, `workflows` on 2 Oct; the rest never. Dead rows exceed live rows on several small tables (Godrej `roles` 25 dead / 6 live, `users` 33 / 17, `workflow_drafts` 41 / 8; Baanganga `scheduled_reports` 19 / 3, `user_drafts` 14 / 1). Every table is under 300 KB, so this does not matter yet; it is the footprint of per-minute updates and draft churn.
6. **Older audit rows cannot be grouped.** 420 of 595 Godrej and 97 of 120 Baanganga audit rows have no `session_id`, so the Chats screen shows each as a separate conversation. 26 Godrej rows also have no user.
7. **The 2 Oct confirm-logging fix works live.** Godrej `audit_log` now has `file_a_complaint` 4, `case_add_update` 3, `case_close_with_note` 3, `case_pass_on` 2. Everything else is still `agent` 502 or `menu` 81, and every outcome is still 'success'.
8. **The SLA job really fires, and has no escalation.** 27 of 29 cases have a reminder sent and 23 a breach notice. With Low = 10 minutes (and a 5-minute reminder), every Low case breaches almost immediately.
9. **Live case state:** 29 cases, 22 open, 19 open and unassigned, 22 open and overdue, 24 with no category (the 5 categorised are from the 2 Oct tests). Active parties: requester 29, assignee 9 (3 ended), level 2: 2, helper: 3. 0 orphans in `case_activity` or `case_parties`.
10. **Live config:** 2 routing rules (Lift issues → a seat with a backup seat; Water and plumbing → a user, no backup); seats: chairman 1, secretary 1, lift in-charge 1, lift level 2 1, treasurer 0 holders; `access_grants` 0 rows; 29 categories (8 roots, 28 with keywords, 1 with its own response time); 5 `admin_events`.
11. **Roles and users:** Godrej 17 users (16 active, 11 with no phone, 6 Telegram-linked); `member` role has 0 users. Baanganga 5 users (4 owner, 1 sales); `accountant` and `warehouse` have 0.
12. **Baanganga approvals and codes are still inert live:** 2 approval and 2 one-time-code steps, but `otp_required` false, no thresholds, `gates` empty, `pending_approvals` empty. 3 builder drafts are left behind (1 chatting, 2 ready for review). 3 scheduled reports are active (daily WhatsApp, weekly email, weekly WhatsApp).
13. **Control DB:** one table, 2 rows, no extra columns, no history table, superuser login. Nothing was changed.

### 10.3 What I still could not determine
Redis contents and hosting; whether the app runs more than one replica; when Postgres statistics were last reset; LLM cost and latency (nothing records them).
