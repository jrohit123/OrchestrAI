# CURRENT WORKFLOW ARCHITECTURE

## 1. Executive Summary

### What This Application Does
OrchestrAI is a multi-tenant WhatsApp/Telegram ERP assistant that allows organizations to define conversational workflows for business operations. Users interact with the system via chat messages to perform actions (create invoices, file complaints, generate reports) and query data. The system uses LLM-powered intent detection, entity extraction, and a database-driven workflow execution engine.

### What the Workflow System Is Intended To Do
The workflow system enables non-technical administrators to create, manage, and execute business processes through conversational interfaces. Workflows define:
- How user requests are interpreted (intent detection)
- What data needs to be collected (entity schema)
- How data is validated and computed (calc_rules)
- What actions are taken (steps)
- How results are formatted (response templates, PDF generation)
- Security controls (OTP, approval gates)

### What Currently Exists
- **Database-driven workflow definitions**: All workflow logic stored in PostgreSQL `workflows` table
- **Conversational workflow builder**: Admin chat interface (`workflow_builder_agent.py`) for creating workflows via natural language
- **Tool-calling agent**: LLM-powered agent (`agent.py`) that interprets user messages and executes workflows
- **Step interpreter**: Generic execution engine (`step_interpreter.py`) that runs workflow steps without code changes
- **Multi-channel support**: WhatsApp and Telegram integration via `messaging.py`
- **PDF generation**: LLM-powered PDF engine (`pdf_engine.py`) using WeasyPrint
- **Security gates**: OTP verification and approval workflows
- **Role-based permissions**: Database-driven access control via `roles` table

### Where Workflows Are Stored
- **Live workflows**: `workflows` table (PostgreSQL)
- **Draft workflows**: `workflow_drafts` table (PostgreSQL)
- **User drafts**: `user_drafts` table (PostgreSQL) - stores in-progress user data collection
- **Schema**: JSONB fields for flexible configuration (steps, entity_schema, calc_rules, pdf_config, etc.)

### How Workflows Are Created
**Primary Method - Conversational Builder**:
1. Admin accesses admin panel chat interface at `/admin/api/workflow-builder/chat`
2. Converses with `workflow_builder_agent.py` (GPT-4o) to describe the workflow
3. Agent uses tools: `update_builder_draft`, `compile_and_summarize`, `revise_draft`, `mark_ready_for_review`
4. `compile_workflow_spec()` converts draft to full workflow JSON
5. Admin reviews summary in publish panel
6. POST to `/admin/api/workflow-builder/publish/{draft_id}` with roles, OTP/approval settings
7. Draft promoted to live `workflows` table, permissions granted to selected roles

**Secondary Method - Direct SQL**:
- Workflows can be inserted directly via SQL migrations (e.g., `002_insert_godrej_workflows.sql`)

### How Workflows Are Selected When a User Sends a Request
**Routing Flow**:
1. User message received via webhook (`webhook.py`)
2. Identity resolved via `resolve_identity()` - phone → user record with org, role, permissions
3. Slash command check: If message starts with `/`, `resolve_slash_command()` in `menu.py` matches to workflow.slash_command
4. If not slash command, message sent to `run_agent()` in `agent.py`
5. Agent's system prompt includes all active workflows' entity_schema, business_glossary, and llm_system_prompt
6. Agent uses tool-calling to either:
   - Call `query_database` for read requests
   - Call `update_draft` + `confirm_action` for action workflows
7. For action workflows, `execute_pending_action()` fetches workflow by intent_key from `workflows` table
8. `run_workflow_steps()` executes the workflow's steps array

**Intent Detection**: No separate intent classifier. The LLM agent directly maps user intent to workflow intent_key based on training_phrases, entity_schema, and business_glossary injected into the system prompt.

### How Workflows Are Executed
**Execution Flow**:
1. User confirms action via `confirm_action` tool
2. Webhook calls `execute_pending_action()` in `action_executor.py`
3. Fetches workflow from `workflows` table by intent_key
4. Calls `run_workflow_steps()` in `step_interpreter.py`
5. Steps executed sequentially from `resume_step` (0 for new execution)
6. Each step operation (resolve_entity, compute, otp_gate, approval_gate, db.insert_row, etc.) runs in order
7. Context (`ctx`) accumulates: fields, computed, generated, inserted, user, org_id, phone
8. If gate (otp_gate, approval_gate) triggers, execution halts with status
9. On completion, draft closed via `close_draft()`
10. PDF generated if workflow has pdf_config
11. Notification sent via `notify.whatsapp` step

### How Workflow Results Are Returned
**Response Channels**:
- **WhatsApp/Telegram**: Primary channel via `messaging.py` (routes to whatsapp.py or telegram.py)
- **Email**: Via Brevo API when `delivery='email'` or `delivery='both'` in generate_pdf tool
- **PDF attachments**: Generated by `pdf_engine.py` using WeasyPrint, sent as document

**Response Formats**:
- **Text response**: From workflow.response_template or agent's natural language response
- **PDF**: Generated from pdf_config.render_instructions or doc_type defaults
- **Interactive menus**: WhatsApp list messages or Telegram inline keyboards
- **Buttons**: For approval workflows (approve/reject buttons)

### What Role the LLM Currently Plays
**Multiple LLM Roles**:
1. **Workflow Builder** (GPT-4o): Conversational agent in `workflow_builder_agent.py` for admin workflow creation
2. **User Agent** (Gemini/Groq/OpenAI/Cerebras fallback): Tool-calling agent in `agent.py` for interpreting user messages
3. **PDF Generator** (Gemini/Groq/OpenAI/Cerebras fallback): Generates HTML for PDF in `pdf_engine.py`
4. **Price Interpreter** (Dual LLM): Gemini + OpenAI for ambiguous price interpretation in `llm_qa_reviewer.py`

**LLM Router** (`llm_router.py`): Centralized multi-provider client with fallback order:
1. Gemini (3 keys, round-robin: gemini-2.5-flash → gemini-2.0-flash → gemini-2.5-flash-lite)
2. Groq (llama-3.1-8b-instant)
3. OpenAI (gpt-4o-mini)
4. Cerebras (gpt-oss-120b)

---

## 2. Repository / System Architecture

### Repository Structure

```
d:\Orchestrator AI\
├── app\
│   ├── db.py                          # Database connection and query functions
│   ├── main.py                        # FastAPI application entry point
│   ├── config.py                      # Configuration and environment variables
│   ├── logging_config.py              # Logging setup
│   ├── redis_client.py                # Redis client for session management
│   ├── routers\
│   │   ├── admin.py                   # Admin panel API endpoints + HTML UI
│   │   ├── webhook.py                 # WhatsApp/Telegram webhook handlers
│   │   └── scheduler.py               # Scheduled report execution (if present)
│   ├── services\
│   │   ├── agent.py                   # Tool-calling LLM agent for user messages
│   │   ├── workflow_builder_agent.py  # Conversational agent for workflow creation
│   │   ├── workflow_compiler.py       # Compiles draft to workflow spec
│   │   ├── workflow_publisher.py      # Publishes draft to live workflows
│   │   ├── workflow_validator.py      # Validates workflow configuration
│   │   ├── workflow_previewer.py      # Generates preview PDFs from drafts
│   │   ├── step_interpreter.py        # Generic workflow step executor
│   │   ├── action_executor.py         # Thin wrapper over step_interpreter
│   │   ├── draft_store.py             # User draft management
│   │   ├── qa_verifier.py             # Draft validation and computation
│   │   ├── calc_engine.py             # Calculated field computation
│   │   ├── pdf_engine.py              # PDF generation (WeasyPrint + LLM)
│   │   ├── pdf_template_extractor.py  # Extracts layout from sample PDFs
│   │   ├── pdf_preprocessor.py        # Preprocesses data for PDF
│   │   ├── llm_router.py              # Multi-provider LLM client with fallback
│   │   ├── llm_qa_reviewer.py         # Dual-LLM price interpretation
│   │   ├── prompt_loader.py           # Loads domain-specific prompts
│   │   ├── query_engine.py            # SQL safety validator
│   │   ├── identity.py                # User identity resolution
│   │   ├── otp_service.py             # OTP generation and verification
│   │   ├── messaging.py               # Channel-agnostic message dispatcher
│   │   ├── whatsapp.py               # WhatsApp API integration
│   │   ├── telegram.py                # Telegram Bot API integration
│   │   ├── menu.py                    # Menu building and slash command resolution
│   │   └── sheets_client.py           # Google Sheets integration
│   ├── executor\
│   │   └── workflow_executor.py       # Legacy OTP/approval resumption
│   └── scheduler\
│       └── report_scheduler.py        # Scheduled report runner
├── migrations\
│   ├── 002_insert_godrej_workflows.sql
│   ├── 003_fix_register_complaint_prompt.sql
│   └── 004_fix_complaint_prompt_defaults.sql
├── godrej_schema.sql                 # Database schema definition
├── godrej_seed.sql                   # Seed data (orgs, roles, users)
├── godrej_test_data_seed.sql         # Test data for workflows
└── housing_society_extensions.sql     # Domain-specific tables
```

### Architecture Table

| Area | Location | Purpose | Important Files |
|------|----------|---------|-----------------|
| **Backend** | `app/` | FastAPI application, business logic | `main.py`, `db.py`, `config.py` |
| **Database** | PostgreSQL | Multi-tenant data storage | `godrej_schema.sql`, `app/db.py` |
| **AI/LLM** | `app/services/` | LLM integration, prompts, routing | `llm_router.py`, `agent.py`, `workflow_builder_agent.py`, `prompt_loader.py` |
| **Workflow Core** | `app/services/` | Workflow definition, execution | `step_interpreter.py`, `action_executor.py`, `workflow_compiler.py`, `workflow_validator.py` |
| **Workflow Builder** | `app/services/` | Admin workflow creation interface | `workflow_builder_agent.py`, `workflow_publisher.py`, `workflow_previewer.py` |
| **Authentication** | `app/services/` | User identity, permissions | `identity.py`, `app/routers/webhook.py` |
| **Integrations** | `app/services/` | External service connections | `whatsapp.py`, `telegram.py`, `sheets_client.py`, `otp_service.py` |
| **PDF Generation** | `app/services/` | Document generation | `pdf_engine.py`, `pdf_template_extractor.py`, `pdf_preprocessor.py` |
| **Notification** | `app/services/` | Message dispatch | `messaging.py`, `whatsapp.py`, `telegram.py` |
| **Admin UI** | `app/routers/admin.py` | Admin panel endpoints + embedded HTML | `admin.py` (contains `_build_html()`) |
| **Scheduling** | `app/scheduler/` | Background job execution | `report_scheduler.py` |
| **State Management** | `app/redis_client.py` + `user_drafts` table | Session and draft persistence | `redis_client.py`, `draft_store.py` |

### Major Request/Data Flows

**Workflow Creation Flow**:
```
Admin (Browser) → POST /admin/api/workflow-builder/chat
  → workflow_builder_agent.py (GPT-4o)
  → Tools: update_builder_draft, compile_and_summarize
  → workflow_compiler.py (LLM generates spec)
  → workflow_validator.py (validates)
  → Admin reviews summary
  → POST /admin/api/workflow-builder/publish/{draft_id}
  → workflow_publisher.py (promotes to workflows table)
  → Roles granted permissions
```

**User Message Flow**:
```
User (WhatsApp/Telegram) → POST /webhook/whatsapp
  → webhook.py (handle_message)
  → identity.py (resolve_identity)
  → Redis session check
  → Security OTP if session expired
  → agent.py (run_agent)
  → LLM (Gemini/Groq/OpenAI/Cerebras)
  → Tool calls: query_database OR update_draft + confirm_action
  → If confirm_action: execute_pending_action
  → action_executor.py → step_interpreter.py
  → Execute workflow steps
  → messaging.py (send response)
```

**PDF Generation Flow**:
```
Workflow step: pdf.generate
  → step_interpreter.py (_op_generate_pdf)
  → pdf_preprocessor.py (preprocess data)
  → pdf_engine.py (generate_pdf)
  → LLM generates HTML
  → WeasyPrint converts to PDF bytes
  → notify.whatsapp step
  → messaging.py (send_document)
  → whatsapp.py or telegram.py
```

---

## 3. Workflow Data Model

### Database Schema

#### `workflows` Table

| Column | Type | Nullable | Default | Purpose | Example |
|--------|------|----------|---------|---------|---------|
| `id` | uuid | NOT NULL | uuid_generate_v4() | Primary key | `550e8400-e29b-41d4-a716-446655440000` |
| `org_id` | uuid | NOT NULL | - | Organization (tenant) | `793eead0-31b2-4538-b9b3-1885f9e94604` |
| `intent_key` | text | NOT NULL | - | Unique workflow identifier per org | `register_complaint` |
| `name` | text | NOT NULL | - | Human-readable name | `Register Complaint` |
| `steps` | jsonb | - | `'[]'` | Sequential step operations | `[{"op":"db.insert_row","params":{...}}]` |
| `is_active` | boolean | - | `true` | Whether workflow is enabled | `true` |
| `otp_required` | boolean | - | `false` | OTP verification needed | `false` |
| `otp_threshold` | numeric(12,2) | - | NULL | Amount threshold for OTP | `50000.00` |
| `version` | integer | - | `1` | Workflow version | `1` |
| `last_run` | timestamptz | - | NULL | Last execution timestamp | `2026-08-17 10:30:00+00` |
| `created_at` | timestamptz | - | `now()` | Creation timestamp | `2026-08-01 00:00:00+00` |
| `is_scheduled` | boolean | - | `false` | Whether workflow is scheduled | `false` |
| `schedule_cron` | text | - | NULL | Cron expression for schedule | `0 9 * * *` |
| `scheduled_by` | uuid | - | NULL | User who scheduled it | `550e8400-...` |
| `approval_threshold` | numeric(12,2) | - | NULL | Amount threshold for approval | `100000.00` |
| `description` | text | - | NULL | Workflow description | `Files a new complaint/case` |
| `workflow_type` | varchar(20) | NOT NULL | `'action'` | 'action' or 'read' | `action` |
| `training_phrases` | jsonb | NOT NULL | `'[]'` | Example phrases for intent | `["complaint register karo", "file a case"]` |
| `entity_schema` | jsonb | NOT NULL | `'{}'` | Field definitions | `{"title":{"type":"string","required":true}}` |
| `sql_template` | text | - | NULL | SQL for read workflows | `SELECT * FROM cases WHERE org_id=$1` |
| `sql_params_order` | jsonb | NOT NULL | `'[]'` | Parameter order for SQL | `[]` |
| `response_format` | varchar(50) | NOT NULL | `'generic'` | Response format | `generic` |
| `business_glossary` | jsonb | NOT NULL | `'{}'` | Term mappings | `{"shikayat":"complaint"}` |
| `llm_system_prompt` | text | - | NULL | Workflow-specific instructions | `Registers a new case...` |
| `pdf_config` | jsonb | - | NULL | PDF generation config | `{"doc_type":"report","title_template":"..."}` |
| `response_template` | text | - | NULL | Response text template | `✅ Complaint Registered\nCase #: {case_number}` |
| `calc_rules` | jsonb | - | `'{}'` | Calculation rules | `{"total":{"expr":"amount * (1 + gst_rate/100)"}}` |
| `slash_command` | varchar(32) | - | NULL | Quick command | `complaint` |
| `command_description` | varchar(80) | - | NULL | Menu description | `File a new complaint or case` |
| `menu_section` | varchar(30) | NOT NULL | `'other'` | Menu grouping | `create` |

**Constraints**:
- `UNIQUE(org_id, intent_key)` - Each org has unique intent keys
- `CHECK (workflow_type IN ('action','read'))` - Only two workflow types

**Storage**: JSONB fields allow flexible nested JSON storage with GIN indexing support.

#### `workflow_drafts` Table

| Column | Type | Nullable | Default | Purpose | Example |
|--------|------|----------|---------|---------|---------|
| `id` | uuid | NOT NULL | gen_random_uuid() | Draft ID | `550e8400-...` |
| `org_id` | uuid | NOT NULL | - | Organization | `793eead0-...` |
| `intent_key` | text | - | NULL | Workflow identifier | `register_complaint` |
| `status` | varchar(20) | NOT NULL | `'chatting'` | Draft status | `ready_for_review` |
| `purpose` | text | - | NULL | Plain English description | `File complaints from residents` |
| `workflow_type` | varchar(20) | - | NULL | 'action' or 'read' | `action` |
| `raw_fields` | jsonb | - | `'[]'` | Field names from conversation | `["title", "description", "location"]` |
| `business_rules` | text | - | NULL | Business rules text | `Priority defaults to medium` |
| `pdf_sample_analysis` | jsonb | - | NULL | Extracted PDF layout | `{"doc_type_guess":"invoice",...}` |
| `name` | text | - | NULL | Workflow name | `Register Complaint` |
| `description` | text | - | NULL | Workflow description | `Files a new complaint` |
| `training_phrases` | jsonb | - | `'[]'` | Training phrases | `["complaint register karo"]` |
| `entity_schema` | jsonb | - | `'{}'` | Compiled entity schema | `{"title":{"type":"string"}}` |
| `calc_rules` | jsonb | - | `'{}'` | Computation rules | `{}` |
| `steps` | jsonb | - | `'[]'` | Compiled steps | `[{"op":"db.insert_row",...}]` |
| `sql_template` | text | - | NULL | SQL template | NULL |
| `sql_params_order` | jsonb | - | `'[]'` | SQL parameter order | `[]` |
| `response_format` | varchar(50) | - | NULL | Response format | `generic` |
| `business_glossary` | jsonb | - | `'{}'` | Business glossary | `{}` |
| `llm_system_prompt` | text | - | NULL | LLM instructions | NULL |
| `pdf_config` | jsonb | - | NULL | PDF config | NULL |
| `response_template` | text | - | NULL | Response template | `✅ Complaint Registered` |
| `otp_required` | boolean | - | `false` | OTP needed | `false` |
| `otp_threshold` | numeric(12,2) | - | NULL | OTP threshold | NULL |
| `approval_threshold` | numeric(12,2) | - | NULL | Approval threshold | NULL |
| `plain_english_summary` | text | - | NULL | Compiled summary | `This workflow files complaints...` |
| `chat_history` | jsonb | - | `'[]'` | Conversation with builder | `[{"role":"user","content":"..."}]` |
| `created_at` | timestamptz | - | `now()` | Creation time | `2026-08-17 10:00:00+00` |
| `updated_at` | timestamptz | - | `now()` | Last update | `2026-08-17 10:30:00+00` |
| `slash_command` | varchar(32) | - | NULL | Slash command | `complaint` |
| `command_description` | varchar(80) | - | NULL | Command description | `File a complaint` |
| `menu_section` | varchar(30) | - | NULL | Menu section | `create` |
| `published_workflow_id` | uuid | - | NULL | Reference to published workflow | `550e8400-...` |
| `granted_roles` | text[] | - | `'{}'` | Roles granted access | `["admin", "committee"]` |

**Constraints**:
- `CHECK (status IN ('chatting','ready_for_review','published','abandoned'))`

#### `user_drafts` Table

| Column | Type | Nullable | Default | Purpose | Example |
|--------|------|----------|---------|---------|---------|
| `id` | uuid | NOT NULL | gen_random_uuid() | Draft ID | `550e8400-...` |
| `org_id` | uuid | NOT NULL | - | Organization | `793eead0-...` |
| `user_id` | uuid | NOT NULL | - | User ID | `550e8400-...` |
| `intent_key` | text | NOT NULL | - | Workflow being filled | `register_complaint` |
| `fields` | jsonb | NOT NULL | `'{}'` | Collected field values | `{"title":"Garbage issue","location":"Wing 3"}` |
| `stage` | varchar(30) | NOT NULL | `'collecting'` | Collection stage | `awaiting_confirmation` |
| `conversation_summary` | text | - | NULL | Summary of conversation | `User wants to file complaint about garbage` |
| `updated_at` | timestamptz | NOT NULL | `now()` | Last update | `2026-08-17 10:15:00+00` |
| `expires_at` | timestamptz | NOT NULL | `now() + 24h` | Expiration | `2026-08-18 10:15:00+00` |

**Constraints**:
- `CHECK (stage IN ('collecting','awaiting_confirmation','awaiting_otp','awaiting_approval','done','cancelled'))`
- `UNIQUE(org_id, user_id)` - One active draft per user

#### Supporting Tables

**`roles` Table**:
- `id` (uuid, PK)
- `org_id` (uuid, FK)
- `name` (text) - e.g., 'admin', 'committee', 'member'
- `permissions` (text[]) - Array of intent_keys
- `readable_tables` (text[]) - Tables this role can query
- `is_approver` (boolean) - Whether this role can approve

**`users` Table**:
- `id` (uuid, PK)
- `org_id` (uuid, FK)
- `role_id` (uuid, FK)
- `name` (text)
- `phone` (text) - WhatsApp number or `tg:<chat_id>` for Telegram
- `email` (text)
- `channel` (text) - 'telegram' or 'whatsapp'
- `is_active` (boolean)

**`pending_approvals` Table**:
- `id` (uuid, PK)
- `org_id` (uuid, FK)
- `workflow_id` (uuid, FK)
- `requester_id` (uuid, FK)
- `approver_role` (text)
- `intent_key` (text)
- `context` (jsonb) - Pending action data
- `status` (text) - 'pending', 'approved', 'rejected'
- `decided_by` (uuid, FK)
- `decided_at` (timestamptz)

**`otp_tokens` Table**:
- `id` (uuid, PK)
- `user_id` (uuid, FK)
- `otp_hash` (text) - SHA256 hash of OTP
- `action_context` (jsonb)
- `expires_at` (timestamptz)
- `used` (boolean)
- `attempts` (integer)
- `org_id` (uuid, FK)

**`audit_log` Table**:
- `id` (uuid, PK)
- `org_id` (uuid, FK)
- `user_id` (uuid, FK)
- `intent_key` (text)
- `tier` (integer)
- `input_text` (text)
- `outcome` (text)
- `otp_used` (boolean)
- `steps_taken` (jsonb)
- `created_at` (timestamptz)
- `due_date` (date)
- `pdf_url` (text)

**`scheduled_reports` Table**:
- `id` (uuid, PK)
- `org_id` (uuid, FK)
- `user_id` (uuid, FK)
- `phone` (text)
- `email` (text)
- `query_text` (text)
- `report_label` (text)
- `schedule_type` (varchar) - 'minutely', 'hourly', 'daily', 'weekly', 'monthly'
- `interval_minutes` (integer)
- `hour` (integer)
- `minute` (integer)
- `day_of_week` (varchar)
- `day_of_month` (integer)
- `delivery` (varchar) - 'whatsapp', 'email', 'both'
- `is_active` (boolean)
- `last_run_at` (timestamptz)
- `next_run_at` (timestamptz)
- `run_count` (integer)

---

## 4. Actual Workflow Examples

### Example 1: Register Complaint (Action Workflow)

**Source**: `migrations/002_insert_godrej_workflows.sql`

**Intent**: File a new complaint/case for residents against a category (cleanliness, maintenance, accounts, misc).

**Trigger**: 
- Slash command: `/complaint`
- Training phrases: "complaint register karo", "case file karo", "register a complaint", "new complaint about {title}", "shikayat darz karo"
- Natural language: "register a complaint about garbage not collected in Wing 3"

**Workflow Configuration**:
```json
{
  "intent_key": "register_complaint",
  "name": "Register Complaint",
  "workflow_type": "action",
  "description": "Files a new complaint/case for the resident against a category (cleanliness, maintenance, accounts, misc).",
  "training_phrases": ["complaint register karo", "case file karo", "register a complaint", "new complaint about {title}", "shikayat darz karo", "report an issue", "file a case", "complaint karna hai", "issue report karo {title}", "book a complaint"],
  "entity_schema": {},
  "steps": [
    {
      "op": "db.insert_row",
      "params": {
        "table": "cases",
        "values": {
          "complainant_id": "$user.user_id",
          "title": "$fields.title",
          "description": "$fields.description",
          "location": "$fields.location",
          "priority": "$fields.priority",
          "status": "reported"
        },
        "sequence": {
          "field": "case_number",
          "prefix": "CS-26-08-",
          "start": 1
        }
      }
    },
    {
      "op": "notify.whatsapp",
      "params": {
        "attach_pdf": false
      }
    }
  ],
  "response_template": "✅ *Complaint Registered*\n\nCase #: *{case_number}*\nTitle: {title}\nStatus: reported\n\n_The committee has been notified._",
  "llm_system_prompt": "Registers a new case in the cases table for this housing society. Required: title (short summary), optional: description, location, priority (urgent/high/medium/low). NEVER auto-fill or invent default values for optional fields — if the user does not provide a value, explicitly ask them for it. Example: \"register a complaint about garbage not collected in Wing 3\" -> title=\"Garbage not collected\", location=\"Wing 3\". This workflow is NOT for checking status of an existing case (that is a read query) and NOT for adding a comment to an existing case. CRITICAL: When calling confirm_action, the \"details\" object must ONLY contain user-facing fields the user actually provided or should review: title, description, location, priority. NEVER include complainant_id, status, org_id, or any other system-set/internal field in details — those are set automatically and must never be shown to the user.",
  "slash_command": "complaint",
  "command_description": "File a new complaint or case",
  "menu_section": "create",
  "otp_required": false,
  "approval_threshold": null
}
```

**Entity Extraction**: 
- No entity_schema defined (empty `{}`)
- LLM agent extracts: title (required), description (optional), location (optional), priority (optional)
- Agent uses `update_draft` to accumulate fields
- Agent uses `confirm_action` to show summary before execution

**Validation**: 
- Performed by `qa_verifier.verify_draft()` during `compute` step
- Checks required fields are present
- Validates field types

**Permissions**: 
- Granted to roles: admin, committee, member (via roles.permissions array)
- Readable tables: complaint_cases, case_comments, case_evidence

**Steps Execution**:
1. **db.insert_row**: Inserts into `cases` table with sequence-generated case_number (CS-26-08-00001, etc.)
2. **notify.whatsapp**: Sends response template via WhatsApp

**Database Operations**:
- Table: `cases` (note: schema uses `complaint_cases` but workflow uses `cases` - potential inconsistency)
- Sequence: Auto-incrementing case_number with prefix

**Notifications**: 
- WhatsApp message with case number and confirmation

**Approval/OTP**: Not configured (otp_required=false, no approval_threshold)

**Output Formatting**: 
- Response template with case_number, title, status

**PDF**: Not generated (attach_pdf=false)

**Error Handling**: 
- If insert fails, step_interpreter raises StepError
- Error message returned to user via webhook

### Example 2: View All Cases (Read Workflow)

**Source**: `migrations/002_insert_godrej_workflows.sql`

**Intent**: List the most recent cases/complaints for the society, newest first.

**Trigger**:
- Slash command: `/cases`
- Training phrases: "show all cases", "sab cases dikhao", "list complaints", "open complaints", "recent complaints", "case list", "sab shikayat dikhao", "show recent cases", "all complaints dikhao", "complaints list"
- Natural language: "show me all complaints"

**Workflow Configuration**:
```json
{
  "intent_key": "view_all_cases",
  "name": "All Cases",
  "workflow_type": "read",
  "description": "Lists the most recent cases/complaints for this society, newest first.",
  "training_phrases": ["show all cases", "sab cases dikhao", "list complaints", "open complaints", "recent complaints", "case list", "sab shikayat dikhao", "show recent cases", "all complaints dikhao", "complaints list"],
  "entity_schema": {},
  "sql_template": "SELECT cc.case_number, cc.title, cc.status, cc.priority, cc.location,\n            cc.created_at, u1.name AS complainant_name, u2.name AS assigned_name\n     FROM cases cc\n     LEFT JOIN users u1 ON u1.id = cc.complainant_id\n     LEFT JOIN users u2 ON u2.id = cc.assigned_to_id\n     WHERE cc.org_id = $1\n     ORDER BY cc.created_at DESC\n     LIMIT 20",
  "sql_params_order": [],
  "response_format": "generic",
  "business_glossary": {"baaki":"pending cases","band":"closed cases","khula":"open cases"},
  "llm_system_prompt": "Lists recent cases/complaints for the society, most recent first, including status, priority, location, who reported it and who it is assigned to. Use this for any general \"show me cases/complaints\" request with no specific filter. For a single case by number, or filtered by animal type/location/category, write a fresh query against the cases table instead of using this fixed template.",
  "pdf_config": {
    "doc_type": "report",
    "title_template": "All Cases — Godrej Emerald",
    "aging_analysis": false,
    "show_key_insights": true,
    "insight_focus": "Flag any urgent/high priority cases still in reported status."
  },
  "slash_command": "cases",
  "command_description": "Show recent complaints/cases",
  "menu_section": "reports"
}
```

**Entity Extraction**: 
- Empty entity_schema - no field collection
- Direct SQL execution without LLM entity extraction

**Validation**: 
- SQL validated by `query_engine._safe()` - only SELECT allowed
- Table access checked against roles.readable_tables

**Permissions**: 
- Granted to roles: admin, committee, member
- Readable tables: complaint_cases, case_comments, case_evidence, users

**Steps**: 
- Empty steps array `[]` - no step execution
- Direct SQL execution via `query_engine.execute_query()`

**Database Operations**:
- Fixed SQL template with org_id parameter
- Joins users table for complainant and assignee names
- LIMIT 20 for result size

**Notifications**: 
- Text response with formatted results
- PDF available via "pdf" reply

**Output Formatting**: 
- Generic JSON format from query_engine
- PDF with report doc_type if requested

**PDF Configuration**:
- doc_type: "report"
- title_template: "All Cases — Godrej Emerald"
- show_key_insights: true
- insight_focus: urgent/high priority cases in reported status

---

## 5. Workflow Creation / Generation System

### Workflow Creation Flow

**Entry Point**: Admin Panel Chat Interface

**API Endpoint**: `POST /admin/api/workflow-builder/chat`

**Request Body**:
```json
{
  "message": "I want a workflow to file complaints",
  "draft_id": "optional-existing-draft-id",
  "attachment": "base64-encoded-pdf",
  "pdf_analysis": {...}
}
```

**Flow Diagram**:
```
Admin Message
  ↓
POST /admin/api/workflow-builder/chat
  ↓
run_builder_agent() in workflow_builder_agent.py
  ↓
Get or create workflow_drafts row
  ↓
Load chat_history from DB
  ↓
Append new message to chat_history
  ↓
Inject draft state into system prompt
  ↓
Call GPT-4o with tools
  ↓
Tool Execution Loop:
  ├─ list_existing_workflows
  ├─ update_builder_draft (saves purpose, workflow_type, raw_fields, etc.)
  ├─ analyze_sample_pdf (if PDF attached)
  ├─ compile_and_summarize (calls workflow_compiler.py)
  └─ revise_draft (for changes)
  ↓
compile_workflow_spec() in workflow_compiler.py
  ├─ Loads business schema from schema_utils.py
  ├─ Constructs LLM prompt with draft data + schema
  ├─ Calls LLM to generate full workflow spec
  ├─ Returns: intent_key, name, entity_schema, calc_rules, steps, etc.
  └─ Calls workflow_validator.py to validate
  ↓
Save compiled spec to workflow_drafts
  ↓
Return summary to admin
  ↓
Admin reviews and confirms
  ↓
POST /admin/api/workflow-builder/publish/{draft_id}
  ↓
publish_workflow() in workflow_publisher.py
  ├─ Validates draft status = 'ready_for_review'
  ├─ Validates roles subset
  ├─ Validates slash_command uniqueness
  ├─ Inserts into workflows table
  ├─ Grants permissions to roles
  └─ Marks draft as 'published'
```

### Key Functions

#### `run_builder_agent()` 
- **File**: `app/services/workflow_builder_agent.py`
- **Purpose**: Conversational agent for admin workflow creation
- **Inputs**: message, org_id, draft_id (optional), attachment_b64 (optional), pre_extracted_pdf (optional)
- **Outputs**: {reply, draft_id, summary_card, has_pdf_preview, published, published_intent_key}
- **Called by**: Admin panel chat endpoint
- **Calls**: `_execute_tool()` which calls various tool handlers
- **Important logic**: 
  - Maintains server-side chat history in workflow_drafts.chat_history
  - Uses GPT-4o with tool-calling
  - Injects current draft state into system prompt to avoid re-asking
  - Supports PDF upload and analysis
  - Handles workflow modification via load_existing_workflow
- **Failure conditions**: 
  - LLM API failure
  - Database write failure
  - Invalid tool calls

#### `compile_workflow_spec()`
- **File**: `app/services/workflow_compiler.py`
- **Purpose**: Convert draft data to full workflow JSON specification
- **Inputs**: draft dict, org_id, source_key
- **Outputs**: Complete workflow spec dict with all fields
- **Called by**: workflow_builder_agent (compile_and_summarize tool)
- **Calls**: 
  - `schema_utils.get_schema()` for business context
  - LLM (via llm_router) to generate spec
  - `workflow_validator.validate_workflow_config()` for validation
- **Important logic**:
  - Constructs prompt with draft.purpose, raw_fields, business_rules, pdf_sample_analysis
  - Injects database schema for context
  - LLM generates: intent_key, name, entity_schema, calc_rules, steps, training_phrases, etc.
  - Auto-fixes common issues
  - Validates before returning
- **Failure conditions**: 
  - LLM generates invalid JSON
  - Validation fails
  - Missing required fields

#### `validate_workflow_config()`
- **File**: `app/services/workflow_validator.py`
- **Purpose**: Deterministic consistency checker for workflow configs
- **Inputs**: workflow spec dict
- **Outputs**: List of problems (empty if valid)
- **Called by**: workflow_compiler, workflow_publisher, admin.py validation endpoint
- **Calls**: None (pure validation logic)
- **Important logic**:
  - Checks entity_schema: required fields, computed fields not marked required
  - Checks calc_rules: references exist in entity_schema, no circular dependencies
  - Checks steps: valid operations, parameter references valid
  - Checks workflow_type consistency with steps
- **Failure conditions**: 
  - Returns non-empty problems list
  - Throws exception if critical issue

#### `publish_draft()`
- **File**: `app/services/workflow_publisher.py`
- **Purpose**: Promote draft to live workflows table
- **Inputs**: draft_id, roles array, otp_required, otp_threshold, approval_threshold, slash_command
- **Outputs**: workflow_id
- **Called by**: Admin publish endpoint
- **Calls**: 
  - Database INSERT into workflows
  - Database UPDATE of roles.permissions
  - Database UPDATE of workflow_drafts status
- **Important logic**:
  - Transactional: insert workflow + grant permissions + mark draft published
  - ON CONFLICT DO UPDATE for existing workflows (versioning)
  - Validates slash_command uniqueness
  - Validates OTP/approval not set for read workflows
- **Failure conditions**: 
  - Draft not in 'ready_for_review' status
  - Invalid roles
  - Slash command conflict
  - Database constraint violation

#### `update_builder_draft()` (Tool Handler)
- **File**: `app/services/workflow_builder_agent.py` (_execute_tool function)
- **Purpose**: Save draft state during conversation
- **Inputs**: purpose, workflow_type, raw_fields, otp_threshold, approval_threshold, business_rules, slash_command, command_description, menu_section
- **Outputs**: {saved: [field_names]}
- **Called by**: LLM tool-calling
- **Important logic**:
  - Merges new values with existing draft
  - Converts numbers (lakh=100000, k=1000) for thresholds
  - Updates workflow_drafts table
  - Refreshes local draft dict for subsequent tool calls
- **Failure conditions**: Database update failure

#### `compile_and_summarize()` (Tool Handler)
- **File**: `app/services/workflow_builder_agent.py` (_execute_tool function)
- **Purpose**: Compile draft and show plain-English summary
- **Inputs**: None
- **Outputs**: {summary, intent_key, _show_confirm_buttons: true, has_pdf_preview}
- **Called by**: LLM when admin requests summary
- **Important logic**:
  - Calls compile_workflow_spec()
  - Saves compiled spec to workflow_drafts
  - Sets status to 'ready_for_review'
  - Returns plain_english_summary for display
- **Failure conditions**: Compilation failure, validation failure

#### `mark_ready_for_review()` (Tool Handler)
- **File**: `app/services/workflow_builder_agent.py` (_execute_tool function)
- **Purpose**: Mark draft ready for publish panel
- **Inputs**: None
- **Outputs**: {_show_publish_panel: true, draft_id, message}
- **Called by**: LLM after admin confirms summary
- **Important logic**:
  - Validates draft has compiled spec
  - Sets status to 'ready_for_review'
  - Triggers publish panel display in admin UI
- **Failure conditions**: No compiled spec exists

### LLM Prompts for Workflow Creation

**System Prompt** (workflow_builder_agent.py):
```
You are helping a non-technical business owner describe a business process
so it becomes a working WhatsApp workflow. They think in plain terms — not schemas, not JSON, not code.
Never show them any technical details.

EXTRACTION-FIRST RULE (highest priority):
Before replying, extract EVERYTHING from the user's message: purpose,
workflow type, use cases, fields, rules, thresholds — whatever is present.
Save all of it via update_builder_draft in ONE call. Then your reply must:
1. Briefly play back what you understood (so they can correct you)
2. Ask ONLY about what is genuinely still unknown — never anything
   already stated or already in the draft
Asking about something the user already told you is the worst failure
mode of this system.

PROPOSE, DON'T INTERROGATE:
When a detail is missing but has an obvious sensible default, propose it
and ask for confirmation instead of asking open-ended questions.

SILENT STATE CHECKS:
Check for existing drafts silently. Mention a draft ONLY if one exists.

LANGUAGE MIRRORING:
Reply in the user's language mix. Hinglish in → Hinglish out. Numbers:
understand 50k = 50,000, 2L / 2 lakh = 2,00,000.

READ-WORKFLOW SHORTCUT:
If the workflow is clearly read-only, don't ask about OTP or approval
thresholds — state "no OTP/approval needed since this only shows data"
in the summary and move on.

Ask ONE question at a time. Cover these topics:
1. What does this do — what will people type or ask to trigger it?
2. What information needs to be collected or looked up?
3. Should anything be CALCULATED automatically?
4. Any safety rules — verification code or someone's approval above a certain amount?
5. Does this produce a document? If yes, ask for sample PDF.
6. What short command should trigger this?

Once you have enough information, call compile_and_summarize.
Show the summary in plain English and ask if it's correct.
If they want changes, call revise_draft, then show the new summary.
Only call mark_ready_for_review after an explicit "yes" on a summary.
```

**Compilation Prompt** (workflow_compiler.py):
```
You are a workflow compiler. Convert this draft into a complete workflow specification.

DRAFT DATA:
{purpose}
{workflow_type}
{raw_fields}
{business_rules}
{pdf_sample_analysis}

DATABASE SCHEMA:
{schema}

OUTPUT JSON STRUCTURE:
{
  "intent_key": "snake_case_identifier",
  "name": "Human Readable Name",
  "description": "One-line description",
  "workflow_type": "action" or "read",
  "training_phrases": ["phrase1", "phrase2"],
  "entity_schema": {
    "field_name": {
      "type": "string|number|boolean|array|object",
      "required": true|false,
      "description": "Field description",
      "computed": true|false
    }
  },
  "calc_rules": {
    "computed_field": {
      "expr": "arithmetic expression",
      "depends_on": ["field1", "field2"]
    }
  },
  "steps": [
    {
      "op": "operation_name",
      "params": {...}
    }
  ],
  "response_template": "Template with {placeholders}",
  "llm_system_prompt": "Instructions for the agent",
  "pdf_config": {...},
  "plain_english_summary": "Summary in plain English"
}
```

---

## 6. LLM / Prompt Architecture

### LLM Provider Configuration

**LLM Router** (`app/services/llm_router.py`):

**Provider Order (with fallback)**:
1. **Gemini** (3 keys, round-robin):
   - Models: gemini-2.5-flash → gemini-2.0-flash → gemini-2.5-flash-lite
   - Base URL: https://generativelanguage.googleapis.com/v1beta/openai/
   - Keys: GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3

2. **Groq**:
   - Model: llama-3.1-8b-instant
   - Base URL: https://api.groq.com/openai/v1
   - Key: GROQ_API_KEY

3. **OpenAI**:
   - Model: gpt-4o-mini
   - Key: OPENAI_API_KEY

4. **Cerebras**:
   - Model: gpt-oss-120b
   - Base URL: https://api.cerebras.ai/v1
   - Key: CEREBRAS_API_KEY

**Fallback Logic**: Try each provider in order, if all fail raise combined error message.

**Settings**:
- max_tokens: 8192 (default)
- temperature: 0.1 (low temperature for deterministic outputs)
- parallel_tool_calls: false (disabled for compatibility)

### Prompt Locations

**1. Agent System Prompt** (`app/services/agent.py` - `_build_system_prompt()`)

**Location**: Dynamically constructed at runtime

**Components**:
- Database schema (from information_schema)
- User info (name, role, permissions)
- Org defaults (GST rate, making charges)
- Workflow schemas (entity_schema, business_glossary, llm_system_prompt from DB)
- Domain-specific prompts (from prompt_loader.py)
- Google Sheets schema (if configured)
- Entity extraction rules
- Draft validation rules
- PDF generation rules

**Injected Variables**:
- `user["org_name"]`
- `user["user_name"]`
- `user["role"]`
- `user["permissions"]`
- `user["readable_tables"]`
- `today` (current date)
- Schema text (table/column listing)
- Workflow-specific entity_schema for each active workflow
- Workflow-specific business_glossary
- Workflow-specific llm_system_prompt

**Expected Output**: Tool calls (query_database, update_draft, confirm_action, etc.) or text response

**Output Format**: OpenAI tool-calling format

**Validation**: Tool parameters validated by _execute_tool()

**Failure/Retry**: LLM router handles provider fallback

**Where Result Goes**: Tool results returned to agent, which formats response for user

**2. Workflow Builder System Prompt** (`app/services/workflow_builder_agent.py`)

**Location**: Hardcoded constant `_SYSTEM_PROMPT`

**Purpose**: Guide admin through workflow creation conversation

**Injected Variables**:
- Current draft state (purpose, workflow_type, raw_fields, thresholds, etc.)
- Chat history from DB

**Expected Output**: Tool calls (update_builder_draft, compile_and_summarize, etc.)

**Output Format**: OpenAI tool-calling format

**Validation**: Tool handlers validate inputs

**Where Result Goes**: Draft saved to workflow_drafts table, summary returned to admin

**3. PDF Generation Prompt** (`app/services/pdf_engine.py` - `_build_html()`)

**Location**: Dynamically constructed

**Components**:
- Document details (org_name, doc_type, title, subtitle, date)
- Data rows (JSON)
- Pre-computed context (extra_context)
- Canonical totals (to prevent recalculation)
- Fonts and colors
- Workflow-configured render_instructions (if present) OR doc-type-specific instructions
- WeasyPrint compatibility rules

**Injected Variables**:
- `org_name`
- `doc_type`
- `title`
- `subtitle`
- `today_long`
- Data rows (first 100)
- `extra_context` (computed values, generated values, analysis)
- `pdf_config.render_instructions` (if present)
- Theme colors (primary, light_bg, text, muted)

**Expected Output**: Complete HTML document starting with <!DOCTYPE html>

**Output Format**: Raw HTML (no markdown fences)

**Validation**: None (HTML validated by WeasyPrint)

**Where Result Goes**: WeasyPrint converts to PDF bytes

**4. Domain-Specific Prompts** (`app/services/prompt_loader.py`)

**Location**: Loaded from files based on org.industry or org.slug

**Purpose**: Industry-specific business rules and terminology

**Examples**:
- Jewelry domain: Gold/silver pricing, making charges, GST rules
- Housing society: Complaint categories, maintenance rules

**Injected Variables**: None (static per domain)

**Expected Output**: Text appended to agent system prompt

**5. Compilation Prompt** (`app/services/workflow_compiler.py`)

**Location**: Dynamically constructed

**Purpose**: Convert draft to workflow spec

**Injected Variables**:
- Draft data (purpose, workflow_type, raw_fields, business_rules)
- PDF sample analysis (if present)
- Database schema

**Expected Output**: Complete workflow JSON specification

**Output Format**: JSON

**Validation**: workflow_validator.validate_workflow_config()

**Where Result Goes**: Saved to workflow_drafts table

### Structured Output / JSON Mode

**Agent Tools**: Use OpenAI function-calling format with structured parameters

**PDF Generation**: No JSON mode - expects raw HTML

**Workflow Compilation**: Expects JSON output from LLM

### Tool/Function Calling

**Agent Tools** (`app/services/agent.py` - TOOLS array):

1. **query_database**: Run SELECT queries
2. **query_sheet**: Read from Google Sheets
3. **update_draft**: Update user draft
4. **clarify**: Ask clarifying questions
5. **show_menu**: Show interactive menu
6. **generate_pdf**: Generate and send PDF
7. **confirm_action**: Show confirmation before action
8. **manage_schedule**: Create/list/pause/delete scheduled reports
9. **send_to_user**: Forward results to another user
10. **cancel_draft**: Cancel current draft

**Builder Tools** (`app/services/workflow_builder_agent.py` - _TOOLS array):

1. **list_existing_workflows**: List live workflows and drafts
2. **update_builder_draft**: Save draft state
3. **analyze_sample_pdf**: Extract PDF layout
4. **compile_and_summarize**: Compile and show summary
5. **revise_draft**: Apply changes and recompile
6. **mark_ready_for_review**: Mark ready for publish
7. **load_existing_workflow**: Load existing workflow for editing

### Context Injection

**Agent Context**:
- Database schema (information_schema)
- User permissions and readable tables
- All active workflows' entity_schema, business_glossary, llm_system_prompt
- Conversation history (last 15 messages)
- Pending action (if any)
- Org defaults (GST rate, making charges)

**Builder Context**:
- Current draft state (all fields)
- Chat history (full conversation)
- Existing workflows (for reference)

**PDF Context**:
- Data rows (up to 100)
- Computed values
- Generated values (doc numbers)
- Analysis (risk buckets, totals)
- PDF config (render_instructions, theme)

### Conversation History Handling

**Agent History**:
- Stored in Redis session: `{org_id}:{phone}`
- Key: `conversation_history`
- Limit: Last 15 messages
- Sanitization: Tool messages removed before sending to LLM (prevents corruption)

**Builder History**:
- Stored in PostgreSQL: `workflow_drafts.chat_history` (JSONB)
- Full conversation retained
- Server-side storage (not round-tripped through browser)

---

## 7. Workflow Intent Detection / Routing

### Routing Flow

**No Separate Intent Classifier**: The LLM agent directly maps user messages to workflows based on context injection.

**Routing Mechanisms**:

1. **Slash Commands** (Fast Path):
   - User sends `/command`
   - `menu.resolve_slash_command()` matches to `workflows.slash_command`
   - Exact match first, then unique prefix match
   - Returns workflow with that intent_key
   - Message passed to agent as intent_key directly

2. **Natural Language** (LLM Path):
   - User sends natural message
   - Agent's system prompt includes all active workflows:
     - intent_key
     - entity_schema (required fields)
     - business_glossary (term mappings)
     - llm_system_prompt (workflow-specific instructions)
   - LLM selects appropriate workflow based on:
     - Training phrases (injected into prompt)
     - Entity schema matching
     - Business glossary terms
   - LLM calls `update_draft` with intent_key
   - Or calls `query_database` for read requests

3. **Menu Selection**:
   - User taps menu item
   - Menu item ID = intent_key
   - Passed to agent as intent_key

### Intent Classification

**Method**: Context injection + LLM reasoning (not semantic search or embeddings)

**Training Phrases**: Stored in `workflows.training_phrases` (JSONB array)
- Example: `["complaint register karo", "case file karo", "register a complaint"]`
- Injected into agent system prompt as examples
- LLM uses these to pattern-match user input

**Business Glossary**: Stored in `workflows.business_glossary` (JSONB object)
- Example: `{"shikayat":"complaint", "case":"complaint"}`
- Injected into agent system prompt
- Helps LLM understand domain-specific terminology

**Workflow-Specific Prompts**: Stored in `workflows.llm_system_prompt` (text)
- Example: "Registers a new case in the cases table..."
- Injected into agent system prompt per workflow
- Guides LLM on workflow-specific behavior

### Conflict Handling

**Multiple Workflows Match**:
- LLM uses `clarify` tool to ask user to disambiguate
- Presents options to user
- User selection resolves conflict

**No Workflow Matches**:
- LLM falls back to `query_database` for general data queries
- Or asks clarifying question
- Or suggests available workflows via `show_menu`

### Organization/Tenant Filtering

**All Queries Filtered by org_id**:
- `WHERE org_id = $1` in all SQL queries
- $1 = user["org_id"]
- Enforced at database level
- Cross-tenant data isolation guaranteed

**Active/Inactive Workflows**:
- Agent only loads `is_active = true` workflows
- Inactive workflows excluded from system prompt
- Cannot be triggered

### Permission Checking

**Before Routing**:
- User identity resolved with role and permissions
- `roles.permissions` array contains allowed intent_keys
- Agent system prompt includes user's permissions
- LLM only considers workflows user has permission for

**After Routing**:
- `execute_pending_action()` checks workflow is_active
- `check_permission()` validates intent_key in user.permissions
- Fail-closed: unknown intents denied

### Fallback Behavior

**Unknown Intent**:
- LLM may call `query_database` for general queries
- Or call `show_menu` to display available options
- Or ask clarifying question

**General Read Query**:
- If no specific workflow matches, LLM can construct SQL query
- Uses `query_database` tool
- Subject to readable_tables permission check

---

## 8. Entity Extraction and Input Schema

### Entity Schema Structure

**Location**: `workflows.entity_schema` (JSONB)

**Structure**:
```json
{
  "field_name": {
    "type": "string|number|boolean|array|object",
    "required": true|false,
    "description": "Human-readable description",
    "computed": true|false,
    "enum": ["option1", "option2"]
  }
}
```

**Supported Field Types**:
- **string**: Text values
- **number**: Numeric values (integers, decimals)
- **boolean**: true/false
- **array**: List of objects (e.g., line items)
- **object**: Nested structure

**Required/Optional Behavior**:
- `required: true` - Field must be present before execution
- `required: false` - Optional field
- Computed fields must NOT be marked required (validated by workflow_validator)

**Defaults**:
- No default values in schema
- LLM may ask for optional fields
- System does not auto-fill optional fields (per llm_system_prompt instruction)

**Validation**:
- Performed by `qa_verifier.verify_draft()`
- Checks required fields present
- Validates field types
- Validates computed fields not marked required

**Enums**:
- `enum` array specifies allowed values
- Used for validation

**Computed Fields**:
- Marked with `"computed": true`
- Calculated by `calc_engine.py` using calc_rules
- Not filled by user or LLM
- Automatically populated during `compute` step

**System-Generated Fields**:
- `org_id`: Auto-injected from user context
- `user_id` / `created_by`: Auto-injected from user context
- Sequence-generated fields (e.g., invoice_number): Generated by db.insert_row

**User-Provided Fields**:
- All non-computed fields
- Extracted by LLM from user message
- Accumulated via `update_draft` tool

### Multi-Turn Slot Accumulation

**Process**:
1. User sends incomplete message: "create invoice"
2. LLM calls `update_draft(intent_key="create_sales_invoice", fields={})`
3. LLM asks for missing fields
4. User provides: "Jain Gold Works"
5. LLM calls `update_draft(fields={"customer_name": "Jain Gold Works"})`
6. LLM asks for remaining fields
7. User provides: "92000"
8. LLM calls `update_draft(fields={..., "amount": 92000}, stage="awaiting_confirmation")`
9. LLM calls `confirm_action()`

**Storage**:
- Fields stored in `user_drafts.fields` (JSONB)
- Stage tracked in `user_drafts.stage`
- Expires after 24 hours

### Missing Field Handling

**LLM Behavior**:
- Checks WORKFLOW SCHEMAS section of system prompt
- Identifies required fields
- Asks for missing fields one at a time
- Proposes sensible defaults when appropriate

**Validation**:
- `qa_verifier.verify_draft()` called during `compute` step
- Returns missing_fields and invalid_fields
- Error message returned to user if validation fails

### Follow-up Questions

**LLM decides** based on:
- Entity schema required fields
- What user has provided so far
- Business context

**No hardcoded follow-up logic** - entirely LLM-driven based on injected schema.

### Field Representation

**Internal Representation**:
- Stored as JSONB in `user_drafts.fields`
- Example: `{"customer_name": "Jain Gold Works", "amount": 92000, "items": [...]}`

**Computed Fields**:
- Stored in separate `ctx["computed"]` during execution
- Merged with fields for downstream steps
- Not persisted to user_drafts

---

## 9. Workflow Execution Engine

### Execution Entrypoint

**Primary Entry**: `execute_pending_action()` in `app/services/action_executor.py`

**Called By**: 
- Webhook after user confirms action
- OTP verification success
- Approval approval success

**Inputs**:
- `pending_action`: {intent_key, fields, stage, resume_step}
- `user`: User context dict
- `phone`: User's phone number
- `otp_verified`: Boolean (for resume after OTP)
- `approved`: Boolean (for resume after approval)

**Outputs**:
```json
{
  "success": true|false,
  "message": "User-facing message",
  "pdf_bytes": bytes|null,
  "stage": "awaiting_otp"|"awaiting_approval"|null,
  "resume_step": integer|null,
  "invoice_number": "...",
  "quotation_number": "...",
  ...
}
```

### Step Execution

**Main Function**: `run_workflow_steps()` in `app/services/step_interpreter.py`

**Process**:
1. Build context `ctx` with fields, computed, generated, inserted, user, org_id, phone, workflow
2. Parse workflow.steps from JSONB
3. Execute steps sequentially from `resume_step`
4. For each step:
   - Get step.op and step.params
   - Look up operation function in PRIMITIVES dict
   - Call operation function with params and ctx
   - Update ctx with results
   - Check if ctx["_halt"] is set (gate triggered)
   - If halt, return with status
5. If all steps complete, return status="done"

**Context Structure**:
```python
ctx = {
    "fields": {},        # User-provided fields
    "computed": {},      # Calculated fields
    "generated": {},     # System-generated values (doc numbers)
    "inserted": {},      # Inserted DB rows
    "updated": {},       # Updated DB rows
    "deleted": {},       # Deleted DB rows
    "user": {},          # User context
    "org_id": "",        # Organization ID
    "phone": "",         # User phone
    "workflow": {},      # Full workflow record
    "otp_verified": bool,
    "approved": bool,
    "source_key": ""
}
```

### Supported Operations

| Operation | Implementation | Inputs | Output | Where Defined |
|-----------|----------------|--------|--------|---------------|
| **resolve_entity** | `_op_resolve_entity()` | table, match_column, name_from, into, expose | Resolved row in ctx | step_interpreter.py |
| **ai_price_interpret** | `_op_ai_price_interpret()` | items with rate_text | items with unit_price | step_interpreter.py |
| **compute** | `_op_compute()` | None | Verified fields with computed values | step_interpreter.py |
| **otp_gate** | `_op_otp_gate()` | amount_field | Halt or continue | step_interpreter.py |
| **approval_gate** | `_op_approval_gate()` | amount_field | Halt or continue | step_interpreter.py |
| **db.insert_row** | `_op_insert_row()` | table, values, sequence | Inserted row in ctx | step_interpreter.py |
| **db.update_row** | `_op_update_row()` | table, set, where | Updated row in ctx | step_interpreter.py |
| **db.upsert_row** | `_op_upsert_row()` | table, values, conflict_columns | Upserted row in ctx | step_interpreter.py |
| **db.delete_row** | `_op_delete_row()` | table, where | Deleted row in ctx | step_interpreter.py |
| **sheets.insert_row** | `_op_insert_row()` (table="sheet:TabName") | table, values, sequence | Inserted row in ctx | step_interpreter.py |
| **sheets.update_row** | `_op_update_row()` (table="sheet:TabName") | table, set, where | Updated row in ctx | step_interpreter.py |
| **sheets.delete_row** | `_op_delete_row()` (table="sheet:TabName") | table, where | Deleted row in ctx | step_interpreter.py |
| **pdf.generate** | `_op_generate_pdf()` | None | PDF bytes in ctx | step_interpreter.py |
| **notify.whatsapp** | `_op_notify_whatsapp()` | attach_pdf | Message sent | step_interpreter.py |

### Parameter Interpolation

**Path Resolution**: `_resolve_path()` and `_resolve_values()`

**Syntax**:
- `$fields.field_name` → User-provided field
- `$computed.field_name` → Computed field
- `$generated.field_name` → System-generated value
- `$entity_name.column` → Resolved entity column
- `$user.user_id` → User ID
- `$org_id` → Organization ID
- Literal values → Used as-is

**Example**:
```json
{
  "values": {
    "customer_id": "$customer.id",
    "amount": "$fields.amount",
    "created_by": "$user.user_id",
    "org_id": "$org_id",
    "status": "pending"
  }
}
```

### Conditions

**No explicit conditional steps** in current implementation.

**Conditional behavior achieved via**:
- Gates (otp_gate, approval_gate) that halt execution based on conditions
- LLM decides which workflow to route to
- resolve_entity can raise ambiguity error

### Branching

**No explicit branching** in step execution.

**Branching achieved via**:
- LLM routing to different workflows
- Gates that halt execution
- Error handling that returns different statuses

### Loops

**No loop constructs** in step execution.

**Array processing**:
- Items arrays processed as single JSON value
- calc_rules can apply expressions to array elements
- No per-item iteration in steps

### Database Operations

**Security**:
- All table/column names validated against information_schema allowlist (AP-10)
- Identifier regex: `^[a-z_][a-z0-9_]*$`
- org_id forced in all WHERE clauses
- SQL injection prevention via parameterized queries

**Operations**:
- **INSERT**: `db.insert_row` with sequence support
- **UPDATE**: `db.update_row` with parameterized WHERE
- **UPSERT**: `db.upsert_row` with ON CONFLICT DO UPDATE
- **DELETE**: `db.delete_row` with parameterized WHERE
- **SELECT**: Via query_database tool (agent) or sql_template (read workflows)

**Sequence Generation**:
- Advisory lock prevents duplicates
- Prefix + incrementing number
- Prefix digits not stripped (fixes compound bug)

### API Calls

**External APIs**:
- **Brevo**: Email sending (OTP, PDF attachments)
- **WhatsApp Cloud API**: Message sending
- **Telegram Bot API**: Message sending
- **Google Sheets API**: Sheet operations

**No direct HTTP calls from steps** - all via service modules.

### Notifications

**notify.whatsapp**:
- Sends PDF if attach_pdf=true and pdf_bytes present
- Sends text message if _final_message set
- Routes to WhatsApp or Telegram via messaging.py

### Human Approval

**approval_gate**:
- Checks amount against approval_threshold
- Bypasses if user in approver role
- Creates pending_approvals record
- Sends interactive buttons to approver
- Halts execution with status="awaiting_approval"
- Resumes via handle_approval_response()

### OTP

**otp_gate**:
- Checks amount against otp_threshold
- Generates OTP via otp_service
- Sends email via Brevo
- Halts execution with status="awaiting_otp"
- Resumes via resume_after_otp()

### PDF Generation

**pdf.generate**:
- Uses workflow.pdf_config
- Calls pdf_engine.generate_pdf()
- LLM generates HTML
- WeasyPrint converts to PDF
- Stores bytes in ctx["pdf_bytes"]

### Calculations

**compute step**:
- Calls qa_verifier.verify_draft()
- Validates required fields
- Executes calc_rules via calc_engine
- Returns verified fields with computed values
- Stores in ctx["computed"]

### State Management

**Execution State**:
- resume_step tracks which step to resume from after gate
- otp_verified flag bypasses otp_gate on resume
- approved flag bypasses approval_gate on resume

**Draft State**:
- user_drafts table tracks collection stage
- Redis session tracks pending_action
- Both updated during execution

### Retries

**No automatic retry** in step execution.

**Manual retry**:
- User can send message again after error
- Draft preserved for 24 hours

### Timeouts

**No step-level timeouts**.

**Session timeout**:
- org.session_ttl_minutes (default 480)
- Redis session expires after TTL
- Draft expires after 24 hours

### Error Handling

**StepError**: Raised by step operations
- Returns status="error" with message
- Draft closed (stage="cancelled")
- User sees friendly error message

**VerificationError**: Raised by qa_verifier
- Returns status="error" with missing_fields
- Shows what fields are missing

**Ambiguity Error**: Raised by resolve_entity
- Returns status="ambiguous" with candidates
- User asked to disambiguate

**Non-fatal PDF/Notification Failure**:
- If DB write succeeded but PDF/notify failed
- Returns success=true with message about PDF not sent
- Suggests user ask to resend

### Rollback/Transaction Behavior

**No explicit transaction management** in step_interpreter.

**Database transactions**:
- Each operation is a separate query
- No multi-step transaction
- Failure mid-execution leaves partial state

**Note**: This is a current limitation - no rollback capability.

### Idempotency

**Not idempotent** by default.

**Idempotency achieved via**:
- Sequence generation uses advisory locks
- UPSERT operations (db.upsert_row)
- No automatic retry means user must retry manually

### Logging

**Structured logging** via logging_config.py:
- Context binding: org_id, user_id
- Step execution logged with operation name
- Errors logged with stack traces

---

## 10. Database Interaction

### Direct SQL

**Agent Tool**: `query_database`

**Implementation**: `app/services/agent.py` - `_execute_tool()`

**Process**:
1. Validate SQL via `query_engine._safe()`
2. Check readable_tables permission
3. Validate table/column names against information_schema
4. Inject org_id as $1
5. Bind additional params as $2, $3...
6. Execute via `fetch_all()`
7. Strip sensitive columns
8. Return results

**Safety Rules** (`query_engine._safe()`):
- Only SELECT allowed
- No DROP, DELETE, INSERT, UPDATE, TRUNCATE, ALTER, GRANT
- No EXECUTE
- No multiple statements (semicolon blocked)
- No pg_* functions
- No information_schema access

**Sensitive Columns** (`query_engine.SENSITIVE_COLS`):
- org_id, user_id, role_id, customer_id, invoice_id, etc.
- otp_hash, config, phone, email
- UUID-like strings
- Stripped from results before returning to LLM

### SQL Templates

**Location**: `workflows.sql_template` (text field)

**Purpose**: Pre-defined SQL for read workflows

**Usage**: 
- Used by `query_engine.execute_query()`
- Parameterized with $1 for org_id, $2, $3... for additional params
- sql_params_order defines parameter order

**Example** (view_all_cases):
```sql
SELECT cc.case_number, cc.title, cc.status, cc.priority, cc.location,
       cc.created_at, u1.name AS complainant_name, u2.name AS assigned_name
FROM cases cc
LEFT JOIN users u1 ON u1.id = cc.complainant_id
LEFT JOIN users u2 ON u2.id = cc.assigned_to_id
WHERE cc.org_id = $1
ORDER BY cc.created_at DESC
LIMIT 20
```

### Parameter Binding

**Positional Parameters**: $1, $2, $3...

**Binding Order**:
1. $1 = org_id (auto-injected)
2. $2, $3... = params from sql_params_order or tool call

**Validation**:
- Parameter count checked against placeholders
- Under-supply: Error message
- Over-supply: Extras truncated (harmless)

### Dynamic SQL

**Agent-Generated SQL**:
- LLM constructs SQL in query_database tool
- Validated by _safe()
- Table access checked against readable_tables
- Column names validated against information_schema

**No Dynamic SQL in Steps**:
- Step operations use fixed table names
- Values parameterized
- No SQL string concatenation

### CRUD Abstractions

**Step Operations**:
- **db.insert_row**: Insert with sequence support
- **db.update_row**: Parameterized UPDATE
- **db.upsert_row**: INSERT ... ON CONFLICT DO UPDATE
- **db.delete_row**: Parameterized DELETE

**No ORM**: Direct SQL with asyncpg

### Table Restrictions

**readable_tables**:
- Defined in roles table
- Array of table names role can query
- Enforced in query_database and query_engine
- Fail-closed: empty array = no access

**Write Restrictions**:
- No explicit write_permissions
- All writes via workflow steps
- org_id forced in all writes
- Table/column validation via information_schema

### Query Validation

**Two Layers**:
1. **query_engine._safe()**: Pattern-based blocking
2. **Schema validation**: Table/column must exist in information_schema

**Both must pass** for query execution.

### Organization/Tenant Isolation

**org_id in WHERE clause**:
- All queries include `WHERE org_id = $1`
- $1 = user["org_id"]
- Enforced at database level
- Cross-tenant access impossible

**org_id in INSERT/UPDATE**:
- Forced in step_interpreter operations
- Cannot be overridden by workflow config

### Transaction Handling

**No explicit transaction management**:
- Each operation is separate
- No multi-step transactions
- No rollback on failure

**Note**: Current limitation - partial writes possible on mid-execution failure.

### Permissions

**Read Permissions**:
- roles.readable_tables array
- Checked before query execution
- Fail-closed

**Write Permissions**:
- No explicit write permissions
- All users with workflow permission can execute
- Workflow permission checked before execution

### SQL Injection Protection

**Three Layers**:
1. **Parameterized queries**: All values bound as parameters
2. **Identifier validation**: Table/column names validated against allowlist
3. **Pattern blocking**: Dangerous SQL patterns blocked

**No string concatenation** for user input.

### Generated SQL

**Agent-Generated**:
- LLM writes SQL in query_database tool
- Subject to all validation layers
- No special privileges

**Workflow-Defined**:
- sql_template field
- Fixed per workflow
- Validated at workflow creation

### Connection Handling

**Connection Pool**: asyncpg pool in `app/db.py`

**Multi-Source Support**:
- get_all_source_keys() returns all configured databases
- Identity resolution loops through sources
- Each operation uses source_key parameter

---

## 11. Permissions / Roles / Access Control

### Roles

**Table**: `roles`

**Fields**:
- `id` (uuid, PK)
- `org_id` (uuid, FK)
- `name` (text) - e.g., 'admin', 'committee', 'member'
- `permissions` (text[]) - Array of intent_keys
- `readable_tables` (text[]) - Array of table names
- `is_approver` (boolean) - Whether role can approve

**Example** (godrej_seed.sql):
```sql
INSERT INTO roles (org_id, name, permissions, readable_tables)
VALUES (
  '793eead0-...',
  'admin',
  ARRAY['general_read','register_complaint','assign_case','close_case',
        'add_case_comment','view_all_cases','view_my_cases'],
  ARRAY['complaint_cases','case_comments','case_evidence','users']
)
```

### Workflow-Level Permissions

**Mechanism**: intent_key in roles.permissions array

**Granting**:
- When workflow published, admin selects roles
- publish_workflow() appends intent_key to roles.permissions
- Uses array_append with NOT @> check to avoid duplicates

**Checking**:
- `check_permission(user, intent)` in identity.py
- Returns true if intent in user["permissions"]
- Fail-closed: unknown intent returns false

**Example**:
- User with role 'member' has permissions: ['general_read', 'register_complaint', 'add_case_comment', 'view_my_cases']
- Can execute: register_complaint workflow
- Cannot execute: assign_case workflow (not in permissions)

### Action Permissions

**Same as workflow permissions**:
- All actions are workflows
- intent_key in permissions array
- Checked before execution

**Approval Actions**:
- action:approve and action:reject also checked
- Must be in permissions

### Row-Level Restrictions

**No explicit row-level security**:
- All rows in org accessible to users with table permission
- No per-row ownership checks
- No per-row ACLs

**Implicit isolation**:
- org_id filtering provides tenant isolation
- No cross-org data access

### Organization Isolation

**Database-level**:
- org_id foreign key on all tables
- WHERE org_id = $1 in all queries
- Cross-org queries impossible

**Application-level**:
- User identity includes org_id
- All operations scoped to org_id
- Multi-tenant via separate org_id values

### Who Can Create Workflows

**Admin panel access**:
- No explicit permission check for workflow creation
- Admin panel has its own authentication (token-based)
- Anyone with admin panel token can create workflows

**In practice**:
- Admin users (role='admin') expected to create workflows
- No role-based restriction on workflow creation UI

### Who Can Edit Workflows

**Same as creation**:
- Admin panel access required
- No role-based restriction
- Workflow modification via builder or direct SQL

### Who Can Activate/Deactivate

**Admin panel**:
- Toggle is_active in admin UI
- No permission check
- Anyone with admin access can toggle

### Who Can Execute Workflows

**Permission-based**:
- User must have intent_key in roles.permissions
- Checked by check_permission()
- Fail-closed

**Example**:
- Member role: can execute register_complaint, view_my_cases
- Committee role: can execute register_complaint, assign_case, close_case, view_all_cases
- Admin role: can execute all workflows

### Permission Enforcement

**Locations**:
1. **identity.check_permission()**: Function-level check
2. **agent.py**: System prompt includes user permissions
3. **action_executor.py**: Checks workflow is_active and user has permission
4. **query_engine**: Checks readable_tables for queries

**Fail-Closed**:
- Unknown intents denied
- Missing permissions denied
- Empty readable_tables = no query access

### Hardcoded vs Database-Driven

**Database-Driven**:
- All permissions in roles table
- No hardcoded permission lists
- No role-specific code paths

**Exception**:
- Admin panel authentication (token-based, not role-based)

### Workflow-Configured Permissions

**No workflow-level permission config**:
- Permissions at role level only
- Workflows reference intent_keys
- No workflow-specific permission rules

### Role-Based

**Yes**:
- All permissions role-based
- Users have one role
- Roles have permissions array

### LLM-Generated Permissions

**No**:
- LLM does not generate permissions
- Permissions set by admin during publish
- LLM only suggests which roles might need access

### Runtime Enforcement

**Yes**:
- Permissions checked before execution
- Checked during query execution
- Checked during tool execution

---

## 12. Approval and OTP Architecture

### Approval

**Configuration**:
- `workflows.approval_threshold` (numeric) - Amount above which approval required
- `roles.is_approver` (boolean) - Which roles can approve

**Implementation**: `step_interpreter.py` - `_op_approval_gate()`

**Process**:
1. Check if amount >= approval_threshold
2. Check if user in approver role (bypass if yes)
3. Find active approver user (is_approver=true, is_active=true, phone not null)
4. Create pending_approvals record with:
   - requester_id
   - approver_role
   - intent_key
   - context (pending_action data)
   - status='pending'
5. Send interactive buttons to approver via WhatsApp:
   - "✅ Approve" button with id="action:approve:{approval_id}"
   - "❌ Reject" button with id="action:reject:{approval_id}"
6. Halt execution with status="awaiting_approval"
7. Store resume_step for resuming after approval

**Resumption**: `workflow_executor.py` - `handle_approval_response()`

**Process**:
1. User (approver) taps approve/reject button
2. Webhook receives button id
3. Parse action and approval_id
4. Fetch pending_approvals record
5. If approve:
   - Update pending_approvals status='approved', decided_by, decided_at
   - Execute pending_action with approved=true
6. If reject:
   - Update pending_approvals status='rejected'
   - Notify requester of rejection
7. Delete pending_approvals record

**State Persistence**:
- pending_approvals table stores approval state
- Context includes full pending_action for resumption
- No expiration (current limitation)

**Notifications**:
- Approver receives WhatsApp buttons
- Requester notified of approval/rejection result

**Security Checks**:
- Only users in approver role receive approval requests
- Approver role checked before sending buttons
- Approval decision logged with decided_by

### OTP

**Configuration**:
- `workflows.otp_required` (boolean)
- `workflows.otp_threshold` (numeric) - Amount above which OTP required

**Implementation**: `step_interpreter.py` - `_op_otp_gate()`

**Process**:
1. Check if amount >= otp_threshold
2. Check if already verified (bypass if yes)
3. Generate OTP via `otp_service.generate_and_send_otp()`:
   - Random 4-digit number
   - SHA256 hash stored in otp_tokens table
   - Expires in 3 minutes
   - Max 3 attempts
   - Send via Brevo email
4. Halt execution with status="awaiting_otp"
5. Store resume_step for resuming after OTP

**OTP Service**: `app/services/otp_service.py`

**generate_and_send_otp()**:
- Generate random 4-digit OTP
- Hash with SHA256
- Invalidate previous unused OTPs for user
- Insert into otp_tokens table
- Send email via Brevo with HTML template
- Return success/failure

**verify_otp()**:
- Fetch latest unused OTP for user
- Check attempts (max 3)
- Check expiry (3 minutes)
- Increment attempts
- Compare hash
- If valid: mark used, return action_context
- If invalid: return remaining attempts

**Resumption**: `workflow_executor.py` - `resume_after_otp()`

**Process**:
1. User replies with OTP code
2. Webhook calls verify_otp()
3. If valid:
   - Execute pending_action with otp_verified=true
4. If invalid:
   - Show error with remaining attempts
   - Allow 'retry' to generate new OTP

**State Persistence**:
- otp_tokens table stores OTP state
- action_context stores pending_action
- 3-minute expiry
- 3 attempt limit

**Notifications**:
- Email via Brevo with OTP code
- WhatsApp message for verification result

**Security Checks**:
- OTP hashed before storage
- Single-use (marked used after verification)
- Expiry prevents replay attacks
- Attempt limit prevents brute force

### Who Approves

**Approver Roles**:
- Roles with `is_approver = true`
- Configured in roles table
- Multiple approvers possible

**Selection**:
- First active approver with phone number
- No load balancing or round-robin
- If no approver found, approval not sent (current limitation)

### When Approval Occurs

**Trigger**: During workflow execution at approval_gate step

**Condition**: amount >= approval_threshold AND user not in approver role

**Position**: Before database write (typically before db.insert_row)

### Where Execution Pauses

**Approval**: After approval_gate step, before next step

**OTP**: After otp_gate step, before next step

**Storage**:
- pending_action in Redis session with resume_step
- pending_approvals record (approval only)
- user_drafts record with stage

### How Execution Resumes

**Approval**:
- Approver taps button
- handle_approval_response() called
- pending_action executed with approved=true
- Resumes from resume_step

**OTP**:
- User sends OTP code
- verify_otp() called
- If valid, pending_action executed with otp_verified=true
- Resumes from resume_step

### State Persistence

**Redis Session**:
- Key: `{org_id}:{phone}`
- Fields: pending_action, conversation_history, state
- TTL: org.session_ttl_minutes (default 480)

**Database**:
- user_drafts: fields, stage, expires_at
- pending_approvals: context, status, decided_by, decided_at
- otp_tokens: otp_hash, action_context, expires_at, used, attempts

### Expiration/Timeouts

**OTP**: 3 minutes (OTP_EXPIRY_MINUTES constant)

**Approval**: No expiration (current limitation)

**Draft**: 24 hours (user_drafts.expires_at)

**Session**: org.session_ttl_minutes (default 480 minutes = 8 hours)

**Confirmation Window**: 10 minutes for awaiting_confirmation stage (agent.py _CONFIRM_STALE_MINUTES)

**Collection Window**: 30 minutes for collecting stage (agent.py _DRAFT_STALE_MINUTES)

### Notifications

**OTP**:
- Email via Brevo
- HTML template with code
- Org name in subject

**Approval**:
- WhatsApp interactive buttons
- Approver sees requester name, action, amount
- Requester sees approval/rejection result

### Security Checks

**OTP**:
- Hash comparison (not plain text)
- Single-use enforcement
- Expiry check
- Attempt limit
- Action context validated

**Approval**:
- Approver role check
- Active user check
- Phone number check
- Decision logged with decided_by

---

## 13. PDF / Report / Image Generation

### PDF Configuration

**Location**: `workflows.pdf_config` (JSONB)

**Structure**:
```json
{
  "doc_type": "report|invoice|quotation|statement|orders",
  "title_template": "Template with {placeholders}",
  "subtitle_template": "Template with {placeholders}",
  "render_instructions": "Custom layout instructions (LLM prompt)",
  "theme": {
    "primary": "#185FA5",
    "light_bg": "#EEF4FB",
    "text": "#1A1A2E",
    "muted": "#6B7280"
  },
  "aging_analysis": true|false,
  "show_key_insights": true|false,
  "insight_focus": "Custom insight instructions"
}
```

**Doc Types**:
- **report**: Multi-row table (default)
- **invoice**: Single tax invoice
- **quotation**: Price quotation
- **statement**: Account statement
- **orders**: Production orders list

### Report Generation

**Trigger**: 
- User says "pdf" after data response
- Agent calls generate_pdf tool
- Or workflow step: pdf.generate

**Implementation**: `app/services/pdf_engine.py` - `generate_pdf()`

**Process**:
1. Build HTML prompt with:
   - Document details (org, type, title, date)
   - Data rows (first 100)
   - Pre-computed context (totals, analysis)
   - Canonical totals (prevent recalculation)
   - Theme colors
   - Layout instructions (render_instructions OR doc-type defaults)
   - WeasyPrint compatibility rules
2. Call LLM (via llm_router) to generate HTML
3. Strip markdown fences if present
4. Force CSS wrapping for table layout
5. Convert to PDF via WeasyPrint
6. Return PDF bytes

**WeasyPrint**: HTML → PDF conversion library

**CSS Support**: Full CSS3 including flexbox, border-radius

**External URLs**: Blocked (security)

### Templates

**Two Paths**:

**1. DB-Configured (New)**:
- pdf_config.render_instructions used
- LLM follows custom layout
- Full control over PDF layout

**2. Hardcoded Defaults (Legacy)**:
- Doc-type-specific instructions in pdf_engine.py
- Fallback for workflows without render_instructions
- Predefined layouts for invoice, quotation, statement, orders, report

**Example Hardcoded Invoice Layout**:
- TAX INVOICE badge
- BILL TO section (customer details)
- Invoice meta (number, date, due date, status)
- Items table
- Totals block
- Payment terms
- Total in words

### Image Generation

**No image generation**:
- No AI image generation
- PDFs only (text + tables + styling)
- No image processing

### Attachments

**PDF Attachments**:
- Generated PDF sent as document
- Via WhatsApp Cloud API or Telegram Bot API
- Filename based on doc number

**Email Attachments**:
- PDF attached to email via Brevo
- When delivery='email' or 'both' in generate_pdf tool

### Output Storage

**No persistent storage**:
- PDFs generated on-demand
- Not stored in database or S3
- Generated fresh each time
- URL not stored (except audit_log.pdf_url for some workflows)

### Delivery Mechanisms

**WhatsApp**:
- Document message via whatsapp.send_document()
- Phone number from user.phone or forward_to

**Telegram**:
- Document message via telegram.send_document()
- Chat ID from user.phone (tg:chat_id format)

**Email**:
- Brevo API with PDF attachment
- When delivery='email' or 'both'

**Forwarding**:
- generate_pdf tool supports forward_to parameter
- Sends PDF to another user
- Looks up recipient phone from users table

### Workflow PDF Configuration

**Example** (view_all_cases):
```json
{
  "doc_type": "report",
  "title_template": "All Cases — Godrej Emerald",
  "aging_analysis": false,
  "show_key_insights": true,
  "insight_focus": "Flag any urgent/high priority cases still in reported status."
}
```

**Example** (invoice workflow would have):
```json
{
  "doc_type": "invoice",
  "title_template": "Tax Invoice — {invoice_number}",
  "render_instructions": "Custom layout instructions..."
}
```

---

## 14. Notifications and Integrations

### Integrations

| Integration | Triggered By | Function | Input | Output | Failure Handling |
|------------|--------------|----------|-------|--------|------------------|
| **WhatsApp** | All user messages, workflow results | Message sending, document sending, interactive buttons | Phone, message, PDF bytes, buttons | Message delivered to WhatsApp | Error logged, user notified |
| **Telegram** | User messages, workflow results | Message sending, document sending, interactive buttons | Chat ID, message, PDF bytes, buttons | Message delivered to Telegram | Error logged, user notified |
| **Brevo Email** | OTP generation, PDF delivery | Email sending with HTML templates | Email, OTP code, PDF bytes, subject | Email delivered via Brevo API | Returns success/failure, retry not automatic |
| **Google Sheets** | Sheet-based workflows | Read/write operations | Tab name, filters, values | Sheet rows read/written | Error raised to step_interpreter |

### WhatsApp

**Implementation**: `app/services/whatsapp.py`

**Functions**:
- `send_text(to, message)`: Send text message
- `send_document(to, pdf_bytes, filename, caption)`: Send PDF
- `send_buttons(to, body, buttons)`: Send interactive buttons
- `send_list(to, body, button_label, sections)`: Send list menu

**API**: WhatsApp Cloud API

**Authentication**: WHATSAPP_PHONE_ID, WHATSAPP_APP_SECRET

**Webhook**: POST /webhook/whatsapp receives inbound messages

**Signature Verification**: HMAC-SHA256 of request body

**Deduplication**: Redis-based message ID tracking

### Telegram

**Implementation**: `app/services/telegram.py`

**Functions**:
- `send_text(chat_id, message)`: Send text message
- `send_document(chat_id, pdf_bytes, filename, caption)`: Send PDF
- `send_buttons(chat_id, body, buttons)`: Send inline keyboard
- `send_list(chat_id, body, button_label, sections)`: Send list menu

**API**: Telegram Bot API

**Authentication**: BOT_TOKEN (environment variable)

**Phone Format**: `tg:{chat_id}` stored in users.phone

**Linking Flow**:
- User sends email to link Telegram account
- OTP sent to email
- OTP verification binds chat_id to user

### Email (Brevo)

**Implementation**: `app/services/otp_service.py`

**Functions**:
- `generate_and_send_otp()`: Send OTP email
- `send_email_with_pdf()`: Send PDF attachment

**API**: Brevo SMTP API (https://api.brevo.com/v3/smtp/email)

**Authentication**: BREVO_API_KEY, SENDER_EMAIL, SENDER_NAME

**OTP Email Template**:
- HTML with verification code
- 4-digit code in large font
- Expiry warning
- Security warning

**PDF Email Template**:
- HTML with subject and body
- PDF as base64 attachment
- Org branding

### Google Sheets

**Implementation**: `app/services/sheets_client.py`

**Functions**:
- `get_all_tab_headers()`: Get sheet structure
- `sheet_fetch_filtered(tab, filters)`: Read rows
- `sheet_insert_row(tab, values)`: Insert row
- `sheet_update_row(tab, where, set)`: Update row
- `sheet_delete_row(tab, where)`: Delete row
- `sheet_count_rows(tab)`: Count rows

**API**: Google Sheets API v4

**Authentication**: OAuth2 via GOOGLE_SHEETS_CREDENTIALS

**Usage**:
- Sheet tables prefixed with "sheet:" in step operations
- Example: table="sheet:Suppliers"
- Fuzzy matching on filters (case-insensitive partial match)

### Channel Routing

**Implementation**: `app/services/messaging.py`

**Logic**:
- Check if phone starts with "tg:"
- If yes: route to telegram functions
- If no: route to whatsapp functions

**Purpose**: Channel-agnostic API for upper layers

---

## 15. Admin UI for Workflows

### Admin UI Architecture

**Implementation**: Embedded HTML in `app/routers/admin.py`

**No Separate Frontend**:
- Admin UI is server-rendered HTML
- Embedded in Python file as `_build_html()` function
- Single-page application with vanilla JavaScript
- No React, Vue, or other frontend framework

### Workflow List

**Endpoint**: `GET /admin/`

**Display**:
- Table of all workflows
- Columns: Name, Type, Active, Slash Command, Menu Section, Actions
- Toggle for is_active
- Edit button
- Delete button

**Data Fetched**: 
- `SELECT * FROM workflows WHERE org_id = $1 ORDER BY name`

**API Called**: None (server-rendered)

**User Actions**:
- Toggle active/inactive
- Click edit to load workflow builder
- Click delete to remove workflow

**State Handling**: Form submission to POST /admin/api/workflows/{id}/toggle

### Workflow Detail Page

**Endpoint**: `GET /admin/workflow/{id}`

**Display**:
- Full workflow configuration
- JSON editor for all fields
- Save button

**Data Fetched**: 
- `SELECT * FROM workflows WHERE id = $1`

**API Called**: None (server-rendered)

**User Actions**:
- Edit JSON fields
- Save changes

**State Handling**: Form submission to POST /admin/api/workflows/{id}

### Workflow Creation UI

**Endpoint**: `GET /admin/workflow-builder`

**Display**:
- Chat interface with LLM
- Message history
- Draft status indicator
- PDF upload button

**Data Fetched**: 
- Existing drafts (if any)

**API Called**: 
- POST /admin/api/workflow-builder/chat (for each message)
- POST /admin/api/workflow-builder/pdf-extract (for PDF upload)

**User Actions**:
- Type messages to describe workflow
- Upload sample PDF
- Review summary
- Publish workflow

**State Handling**:
- Chat history stored in workflow_drafts.chat_history
- Draft state stored in workflow_drafts fields
- Draft ID passed between requests

### Editing UI

**Two Modes**:

**1. JSON Editor**:
- Direct JSON editing of workflow record
- GET /admin/workflow/{id}
- POST /admin/api/workflows/{id}

**2. Conversational Editor**:
- Chat-based editing via workflow_builder_agent
- Load existing workflow with load_existing_workflow tool
- Modify via conversation
- Republish

### Activation/Deactivation

**UI**: Toggle switch in workflow list

**API**: POST /admin/api/workflows/{id}/toggle

**Implementation**:
- UPDATE workflows SET is_active = NOT is_active
- Immediate effect

### Testing

**No Built-in Testing UI**:
- No test execution interface in admin panel
- Testing done via WhatsApp/Telegram directly
- No sandbox mode

### Configuration Forms

**JSON Editor**:
- Textarea with JSON
- All workflow fields editable
- No validation in UI (validation on save)

**Publish Panel**:
- Role selection (checkboxes)
- OTP toggle and threshold input
- Approval toggle and threshold input
- Slash command input
- Menu section dropdown
- Publish button

### JSON Editors

**Location**: Workflow detail page

**Implementation**: Simple textarea

**Features**:
- No syntax highlighting
- No validation
- No auto-formatting
- Raw JSON editing

### Chat Interfaces

**Workflow Builder Chat**:
- **File**: Embedded in admin.py
- **Route**: GET /admin/workflow-builder
- **API**: POST /admin/api/workflow-builder/chat
- **Features**:
  - Message history display
  - Typing indicator
  - PDF upload button
  - Summary card display
  - Publish panel overlay

### Previews

**PDF Preview**:
- **Trigger**: After compile_and_summarize
- **API**: POST /admin/api/workflow-builder/preview-pdf
- **Implementation**: workflow_previewer.generate_preview_pdf()
- **Process**:
  - Load draft with compiled spec
  - Generate synthetic placeholder data
  - Run calc_engine with placeholder data
  - Generate PDF via pdf_engine
  - Return PDF bytes
- **Display**: PDF viewer in browser

### Permissions UI

**Publish Panel**:
- Role checkboxes
- Select which roles can use workflow
- Visual representation of roles table

**No Separate Permissions Management**:
- Roles managed via direct SQL or separate interface
- Not part of workflow builder UI

### Report/PDF Configuration UI

**In Workflow Builder**:
- LLM asks about document format
- Admin uploads sample PDF
- PDF analysis extracted automatically
- LLM generates pdf_config

**In JSON Editor**:
- Manual pdf_config JSON editing
- No visual PDF builder

---

## 16. API Endpoints

### Workflow-Related Endpoints

| Method | Route | Purpose | Request | Response | Auth | File |
|--------|-------|---------|---------|----------|------|------|
| GET | /admin/ | Admin dashboard with workflow list | None | HTML page | Token | admin.py |
| POST | /admin/api/workflows/{id}/toggle | Toggle workflow active/inactive | None | {ok: true} | Token | admin.py |
| POST | /admin/api/workflows/{id} | Update workflow | Workflow JSON | {ok: true} | Token | admin.py |
| DELETE | /admin/api/workflows/{id} | Delete workflow | None | {ok: true} | Token | admin.py |
| GET | /admin/workflow-builder | Workflow builder chat UI | None | HTML page | Token | admin.py |
| POST | /admin/api/workflow-builder/chat | Send message to builder | {message, draft_id, attachment} | {reply, draft_id, summary_card, ...} | Token | admin.py |
| POST | /admin/api/workflow-builder/pdf-extract | Analyze uploaded PDF | FormData with pdf_file | PDF analysis JSON | Token | admin.py |
| GET | /admin/api/workflow-builder/draft/{draft_id}/publish-info | Get publish panel data | None | {summary, roles, prefill} | Token | admin.py |
| POST | /admin/api/workflow-builder/publish/{draft_id} | Publish draft to live | {roles, otp_required, otp_threshold, ...} | {ok: true, workflow_id} | Token | admin.py |
| POST | /admin/api/workflow-builder/preview-pdf | Generate preview PDF | draft_id | PDF bytes | Token | admin.py (not implemented in code) |
| POST | /admin/api/validate-workflow | Validate workflow config | Workflow JSON | {valid: true, problems: []} | Token | admin.py |
| GET | /webhook/whatsapp | WhatsApp webhook verification | Query params | Challenge token | None | webhook.py |
| POST | /webhook/whatsapp | WhatsApp webhook (messages) | JSON body | {status: ok} | Signature | webhook.py |

### Execution Endpoints

| Method | Route | Purpose | Request | Response | Auth | File |
|--------|-------|---------|---------|----------|------|------|
| (Implicit) | (via webhook) | Execute workflow | User message | Text/PDF response | Phone/OTP | webhook.py + agent.py |

### Admin Chat Endpoint

**POST /admin/api/workflow-builder/chat**

**Request**:
```json
{
  "message": "I want a workflow to file complaints",
  "draft_id": "optional-uuid",
  "attachment": "base64-pdf",
  "pdf_analysis": {...}
}
```

**Response**:
```json
{
  "reply": "I'll help you create a complaint workflow...",
  "draft_id": "uuid",
  "summary_card": "This workflow files complaints...",
  "has_pdf_preview": true,
  "published": false,
  "published_intent_key": null
}
```

### Workflow Generation Endpoint

**POST /admin/api/workflow-builder/publish/{draft_id}**

**Request**:
```json
{
  "roles": ["admin", "committee"],
  "otp_required": false,
  "otp_threshold": null,
  "approval_required": false,
  "approval_threshold": null,
  "slash_command": "complaint"
}
```

**Response**:
```json
{
  "ok": true,
  "workflow_id": "uuid"
}
```

### Validation Endpoint

**POST /admin/api/validate-workflow**

**Request**: Workflow JSON

**Response**:
```json
{
  "valid": true,
  "problems": []
}
```

### Approval/OTP Endpoints

**Approval**: Handled via webhook button clicks
- Button ID format: `action:approve:{approval_id}` or `action:reject:{approval_id}`
- Webhook parses and calls handle_approval_response()

**OTP**: Handled via webhook text message
- User replies with OTP code
- Webhook calls verify_otp()

---

## 17. Workflow Scheduling

### Scheduler

**Implementation**: `app/scheduler/report_scheduler.py`

**Purpose**: Execute scheduled reports at specified intervals

**Table**: `scheduled_reports`

**Configuration**:
- schedule_type: 'minutely', 'hourly', 'daily', 'weekly', 'monthly'
- interval_minutes: For minutely schedules
- hour, minute: For daily/weekly/monthly
- day_of_week: For weekly (mon, tue, wed, thu, fri, sat, sun)
- day_of_month: For monthly (1-31)
- delivery: 'whatsapp', 'email', 'both'

### Cron Parsing

**No cron library used**:
- Custom scheduling logic in report_scheduler.py
- Not standard cron expression
- schedule_cron field exists in workflows table but not used by scheduler

### Storage

**Table**: `scheduled_reports`

**Fields**:
- id, org_id, user_id, phone, email
- query_text (the query to run)
- report_label (human-readable name)
- schedule_type, interval_minutes, hour, minute, day_of_week, day_of_month
- delivery, is_active
- last_run_at, next_run_at, run_count

### Execution

**Process**:
1. Scheduler runs periodically (via external cron or systemd timer)
2. Queries scheduled_reports where next_run_at <= now AND is_active = true
3. For each due report:
   - Execute query_text via agent
   - Generate PDF if requested
   - Send via WhatsApp/Email based on delivery setting
   - Update last_run_at, calculate next_run_at, increment run_count

**Note**: Scheduler implementation not fully visible in provided code - may be external or incomplete.

### Timezone Handling

**IST Timezone**:
- Hardcoded Asia/Kolkata in agent.py for greetings
- No explicit timezone handling in scheduler (likely uses server time)

### Ownership

**scheduled_by field**:
- Exists in workflows table
- Not used in scheduled_reports table
- scheduled_reports.user_id indicates owner

### Enable/Disable Behavior

**is_active flag**:
- true: schedule runs
- false: schedule skipped

**UI**: No visible UI in admin panel for managing scheduled reports

### Failure/Retry Behavior

**Not visible in code**:
- No retry logic visible
- No error handling visible
- Likely fails silently or logs error

---

## 18. State and Conversation Management

### Session IDs

**Format**: `{org_id}:{phone}`

**Storage**: Redis

**Purpose**: Maintain conversation state and pending actions

**TTL**: org.session_ttl_minutes (default 480 minutes = 8 hours)

### User IDs

**Format**: UUID

**Storage**: users table

**Purpose**: Identify user across sessions

### Organization IDs

**Format**: UUID

**Storage**: orgs table

**Purpose**: Tenant isolation

### Conversation History

**Agent History**:
- **Storage**: Redis session key `conversation_history`
- **Format**: Array of {role, content} objects
- **Limit**: Last 15 messages
- **Sanitization**: Tool messages removed before sending to LLM

**Builder History**:
- **Storage**: workflow_drafts.chat_history (JSONB)
- **Format**: Array of {role, content} objects
- **Limit**: No limit (full conversation retained)
- **Purpose**: Server-side storage for workflow builder

### Pending Workflows

**Storage**: 
- Redis session: `pending_action`
- user_drafts table

**Structure**:
```json
{
  "intent_key": "register_complaint",
  "fields": {...},
  "stage": "collecting" | "awaiting_confirmation" | "awaiting_otp" | "awaiting_approval",
  "resume_step": 0,
  "created_at": "timestamp"
}
```

**Stages**:
- collecting: Gathering field values
- awaiting_confirmation: Waiting for user confirmation
- awaiting_otp: Waiting for OTP verification
- awaiting_approval: Waiting for approval
- done: Successfully completed
- cancelled: Cancelled by user

### Pending Confirmations

**Storage**: Redis session pending_action with stage="awaiting_confirmation"

**Timeout**: 10 minutes (_CONFIRM_STALE_MINUTES in agent.py)

**Behavior**: After timeout, draft cleared and user asked to restart

### Pending Approvals

**Storage**: pending_approvals table

**Fields**:
- id, org_id, workflow_id, requester_id, approver_role
- intent_key, context (JSONB), status
- decided_by, decided_at, created_at

**Status**: pending, approved, rejected

**No Expiration**: Current limitation

### Unfinished Workflows

**Detection**: 
- Rehydration from user_drafts table
- If Redis has no pending_action but DB has active draft

**Behavior**: 
- User notified of unfinished draft
- Can continue or /cancel

### Resume Behavior

**After OTP**:
- User sends OTP code
- verify_otp() called
- If valid, execute_pending_action(otp_verified=true)
- Resumes from resume_step

**After Approval**:
- Approver taps button
- handle_approval_response() called
- If approved, execute_pending_action(approved=true)
- Resumes from resume_step

**After Timeout**:
- Draft cleared
- User asked to restart

### Human-in-the-Loop State

**OTP Gate**:
- Execution halts
- OTP sent via email
- State stored in otp_tokens + Redis
- Resume on OTP verification

**Approval Gate**:
- Execution halts
- Approval request sent to approver
- State stored in pending_approvals + Redis
- Resume on approval/rejection

**Confirmation**:
- Execution halts before database write
- Confirmation shown to user
- State stored in Redis
- Resume on "yes" response

---

## 19. Workflow Lifecycle

### Actual Lifecycle

```
Draft Creation (workflow_drafts table, status='chatting')
  ↓
Conversational Building (workflow_builder_agent.py)
  ├─ update_builder_draft (accumulate data)
  ├─ analyze_sample_pdf (if PDF uploaded)
  └─ compile_and_summarize (generate spec)
  ↓
Compilation (workflow_compiler.py)
  ├─ LLM generates full workflow spec
  └─ workflow_validator validates
  ↓
Ready for Review (workflow_drafts.status='ready_for_review')
  ↓
Admin Review (plain_english_summary displayed)
  ├─ revise_draft (if changes needed)
  └─ recompile
  ↓
Publish (workflow_publisher.py)
  ├─ Insert into workflows table
  ├─ Grant permissions to roles
  └─ Mark draft as 'published'
  ↓
Active (workflows.is_active=true)
  ↓
Triggered (by user message or slash command)
  ↓
Entity Extraction (agent.py via update_draft)
  ↓
Validation (qa_verifier during compute step)
  ↓
Confirmation (confirm_action tool)
  ↓
Execution (step_interpreter.py)
  ├─ resolve_entity (if needed)
  ├─ compute (calc_rules)
  ├─ otp_gate (if threshold met)
  ├─ approval_gate (if threshold met)
  ├─ db.insert_row / update_row / upsert_row
  ├─ pdf.generate (if configured)
  └─ notify.whatsapp
  ↓
Completion (user_drafts.status='done')
  ↓
Result Delivery (WhatsApp/Telegram/Email + PDF)
```

### Lifecycle States

**workflow_drafts.status**:
- chatting: In conversation with builder
- ready_for_review: Compiled, awaiting admin review
- published: Successfully published to workflows table
- abandoned: Cancelled or abandoned

**user_drafts.stage**:
- collecting: Gathering field values
- awaiting_confirmation: Waiting for user confirmation
- awaiting_otp: Waiting for OTP verification
- awaiting_approval: Waiting for approval
- done: Successfully completed
- cancelled: Cancelled by user

**workflows.is_active**:
- true: Workflow can be triggered
- false: Workflow disabled

---

## Summary

The OrchestrAI workflow system is a database-driven, LLM-powered conversational workflow engine. Workflows are defined entirely in the `workflows` table with JSONB configuration fields. The system uses a tool-calling LLM agent to interpret user messages, extract entities, and execute workflows via a generic step interpreter. Workflows can be created through a conversational admin interface or direct SQL insertion. Execution supports database operations, PDF generation, OTP verification, and approval gates. Multi-tenant isolation is enforced via org_id filtering. The system supports WhatsApp and Telegram channels with role-based permissions.
