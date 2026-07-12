# Google Sheets ↔ WhatsApp Integration for OrchestrAI

**Goal:** Let WhatsApp users read and write data that lives in a Google Sheet — not Postgres — through the exact same agent, `update_draft → confirm_action → execute_pending_action` flow, and `workflows.steps[]` discipline you already use for Postgres-backed workflows. Zero new architecture, zero hardcoding — Sheets becomes a second "table source" the existing engine already knows how to talk to.

**Use case chosen for this doc:** Baanganga doesn't yet track **raw material purchasing** (gold/silver/gemstones bought from suppliers before manufacturing) in Postgres — that currently lives in someone's personal spreadsheet. We'll digitize exactly that into a Google Sheet with 3 tabs: `Suppliers`, `RawMaterialStock`, `PurchaseOrders`. This is deliberately different data from your existing `customers`/`inventory`/`orders` Postgres tables, so you can test the integration in isolation without touching production data.

By the end you'll be able to do all 4 CRUD operations over WhatsApp:
- **Read** — "22kt gold stock kitna hai"
- **Create** — "PO banao Rajesh Bullion Traders se 500g gold @ 6200"
- **Update** — "mark PO-1002 as received"
- **Delete** — "cancel PO-1003"

---

## 0. Architecture — how this fits what you already have

```
WhatsApp ──▶ webhook.py ──▶ agent.py (run_agent)
                               │
                 ┌─────────────┴─────────────┐
                 ▼                             ▼
          query_database                  query_sheet   ◄── NEW tool, read-only
        (Postgres, existing)          (Google Sheets, new)
                 │                             │
         update_draft → confirm_action → execute_pending_action
                               │
                    step_interpreter.run_workflow_steps()
                               │
              table="customers" ──▶ Postgres          (existing)
              table="sheet:PurchaseOrders" ──▶ Sheets  (NEW — prefix dispatch)
```

Nothing about `agent.py`'s decision-making changes conceptually. You're adding:
1. One new **read tool** (`query_sheet`) parallel to `query_database`.
2. A **`sheet:` table-name prefix convention** inside `step_interpreter.py`'s existing `db.insert_row` / `db.update_row` / new `db.delete_row` ops, so the same generic step primitives work against either backend.
3. Three new **`workflows` rows** (the same pattern as `create_sales_invoice`) whose `steps[]` reference `sheet:PurchaseOrders` instead of `invoices`.

This preserves your core principle: *domain knowledge belongs to workflows, not the codebase.*

---

## 1. Google Cloud setup (one-time, ~10 minutes)

### 1.1 Create a project
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Top-left project dropdown → **New Project**
3. Name it `orchestrai-sheets-integration` → **Create**

### 1.2 Enable the APIs
1. In the search bar, type **"Google Sheets API"** → open it → **Enable**
2. Search **"Google Drive API"** → open it → **Enable**
   (Drive API is needed because `gspread` uses it to open the spreadsheet by ID.)

### 1.3 Create a service account
A service account is a robot identity — no OAuth consent screen, no browser login needed. Perfect for a server-side bot.

1. Left sidebar → **IAM & Admin → Service Accounts**
2. **+ Create Service Account**
3. Name: `orchestrai-sheets-bot` → **Create and Continue**
4. Skip the "Grant this service account access to project" step (not needed) → **Continue** → **Done**

### 1.4 Generate a JSON key
1. Click the new service account → **Keys** tab
2. **Add Key → Create new key → JSON** → downloads `orchestrai-sheets-integration-xxxxx.json`
3. Open it and note the `client_email` field — looks like:
   `orchestrai-sheets-bot@orchestrai-sheets-integration.iam.gserviceaccount.com`
   You'll need this exact address in step 2.2.

**⚠️ Never commit this JSON file to git.** Add it to `.gitignore` right now:
```bash
echo "*.json" >> .gitignore   # or be more specific: echo "orchestrai-sheets-*.json" >> .gitignore
```

---

## 2. Create the test Google Sheet + mock data

### 2.1 Create the spreadsheet
1. Go to [sheets.google.com](https://sheets.google.com) → **Blank spreadsheet**
2. Rename it: `OrchestrAI - Raw Materials Ledger`
3. Rename `Sheet1` → `Suppliers`. Add two more tabs: `RawMaterialStock`, `PurchaseOrders` (right-click tab bar → Insert sheet).

### 2.2 Share it with the service account
Click **Share** (top right) → paste the `client_email` from step 1.4 → set role to **Editor** → **Send** (uncheck "notify" — it's a robot).

**This is the #1 cause of failures.** If you skip this, every API call returns `403 PERMISSION_DENIED`.

### 2.3 Get the Spreadsheet ID
Look at the URL:
```
https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz1234567890/edit
                                        └──────────── this part ────────────┘
```
Copy that ID — you'll set it as an env var in step 3.

### 2.4 Paste in the mock data

**Tab: `Suppliers`** — row 1 is the header, exactly as written (case-sensitive):

| supplier_id | name | phone | city | material_type | payment_terms |
|---|---|---|---|---|---|
| SUP-001 | Rajesh Bullion Traders | +919820011122 | Mumbai | Gold | 15 days credit |
| SUP-002 | Chennai Silver Hub | +914433221100 | Chennai | Silver | Advance payment |
| SUP-003 | Surat Diamond Source | +912612345678 | Surat | Diamond | 30 days credit |
| SUP-004 | Jaipur Gemstone Co | +911412345678 | Jaipur | Coloured Gemstones | 7 days credit |
| SUP-005 | Kolkata Gold Refinery | +913322334455 | Kolkata | Gold | Cash on delivery |

**Tab: `RawMaterialStock`:**

| material_id | material_name | unit | qty_available | reorder_level | last_purchase_rate | supplier_name |
|---|---|---|---|---|---|---|
| RM-001 | 22kt Gold Bar | grams | 1200 | 500 | 6180 | Rajesh Bullion Traders |
| RM-002 | 92.5 Sterling Silver | grams | 8000 | 2000 | 82 | Chennai Silver Hub |
| RM-003 | Polished Diamond 0.5ct | pieces | 45 | 20 | 32000 | Surat Diamond Source |
| RM-004 | Ruby Natural 2mm | pieces | 300 | 100 | 450 | Jaipur Gemstone Co |
| RM-005 | 24kt Gold Bar | grams | 600 | 300 | 6350 | Kolkata Gold Refinery |
| RM-006 | Emerald Natural 3mm | pieces | 120 | 50 | 900 | Jaipur Gemstone Co |

**Tab: `PurchaseOrders`** (start with just 2 rows — you'll create more live via WhatsApp during testing):

| po_id | supplier_name | material_name | qty | rate | total | status | order_date | expected_delivery |
|---|---|---|---|---|---|---|---|---|
| PO-1001 | Rajesh Bullion Traders | 22kt Gold Bar | 500 | 6180 | 3090000 | received | 2026-06-20 | 2026-06-25 |
| PO-1002 | Chennai Silver Hub | 92.5 Sterling Silver | 5000 | 82 | 410000 | pending | 2026-07-05 | 2026-07-10 |

**Formatting tip:** Select the `qty`, `rate`, `total`, `qty_available`, `reorder_level`, `last_purchase_rate` columns → **Format → Number → Number** (not "Automatic" / "Plain text"). If these render as text, `gspread`'s auto-numericising can misbehave and your `calc_engine` math downstream will choke on strings.

---

## 3. Environment variables

You need the JSON key **base64-encoded** so it survives as a single-line env var on Railway (no multiline secrets headaches).

**Mac/Linux:**
```bash
base64 -i orchestrai-sheets-integration-xxxxx.json | tr -d '\n' > sheets_creds_b64.txt
cat sheets_creds_b64.txt   # copy this whole string
```

**Windows (PowerShell):**
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("orchestrai-sheets-integration-xxxxx.json")) | Set-Content sheets_creds_b64.txt
```

**Or in Python (cross-platform), if you'd rather not use shell tools:**
```python
import base64
with open("orchestrai-sheets-integration-xxxxx.json", "rb") as f:
    print(base64.b64encode(f.read()).decode())
```

Add to your local `.env`:
```bash
GOOGLE_SHEETS_CREDENTIALS_B64=<paste the long base64 string here>
GOOGLE_SHEETS_SPREADSHEET_ID=<the spreadsheet ID from step 2.3>
```

And on **Railway**: Project → Variables → add the same two keys. Restart the deploy after adding them.

---

## 4. Install dependencies

```bash
pip install gspread google-auth --break-system-packages
```

Add to `requirements.txt`:
```
gspread==6.1.2
google-auth==2.29.0
```

---

## 5. New file: `app/services/sheets_client.py`

This mirrors the shape of `app/db.py` (`fetch_all`/`fetch_one`/`execute`) so the rest of the codebase treats a Sheet tab like it treats a Postgres table — same discipline. `gspread` calls are synchronous, so every function wraps its blocking call in `asyncio.to_thread` to avoid stalling the FastAPI event loop.

```python
"""
sheets_client.py — Generic Google Sheets CRUD client.

Mirrors the shape of app/db.py's fetch_all/fetch_one/execute so that
step_interpreter.py and agent.py can treat a Sheet tab exactly like a
Postgres table — same discipline, same "zero domain hardcoding" principle.

Auth: service account (no user OAuth flow, no browser consent needed).
The service account's client_email must be added as an Editor on the
target spreadsheet (see setup doc, section 2.2).
"""
import os
import json
import base64
import asyncio
from functools import lru_cache

import gspread
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


@lru_cache(maxsize=1)
def _get_client() -> gspread.Client:
    b64 = os.getenv("GOOGLE_SHEETS_CREDENTIALS_B64")
    if not b64:
        raise RuntimeError(
            "GOOGLE_SHEETS_CREDENTIALS_B64 is not set. "
            "See integration doc, section 3."
        )
    info = json.loads(base64.b64decode(b64))
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


@lru_cache(maxsize=1)
def _get_spreadsheet():
    sheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    if not sheet_id:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID is not set.")
    return _get_client().open_by_key(sheet_id)


def _ws(tab: str):
    return _get_spreadsheet().worksheet(tab)


# ── Read ──────────────────────────────────────────────────────────────────

async def get_all_tab_headers() -> dict[str, list[str]]:
    """{'Suppliers': ['supplier_id','name',...], ...} — feeds the schema
    block the LLM sees in the system prompt."""
    def _sync():
        ss = _get_spreadsheet()
        return {ws.title: ws.row_values(1) for ws in ss.worksheets()}
    return await asyncio.to_thread(_sync)


async def sheet_fetch_all(tab: str) -> list[dict]:
    """All rows in a tab as a list of dicts, keyed by header row."""
    def _sync():
        return _ws(tab).get_all_records()
    return await asyncio.to_thread(_sync)


async def sheet_fetch_filtered(tab: str, filters: dict) -> list[dict]:
    """Case-insensitive partial match on every filter key (ILIKE-style)."""
    rows = await sheet_fetch_all(tab)
    if not filters:
        return rows
    out = []
    for r in rows:
        if all(
            str(v).strip().lower() in str(r.get(k, "")).strip().lower()
            for k, v in filters.items()
        ):
            out.append(r)
    return out


async def sheet_count_rows(tab: str) -> int:
    rows = await sheet_fetch_all(tab)
    return len(rows)


# ── Write ─────────────────────────────────────────────────────────────────

async def sheet_insert_row(tab: str, values: dict) -> dict:
    """Appends one row. Missing header columns are left blank; extra keys
    in `values` that don't match a header are silently dropped."""
    def _sync():
        ws = _ws(tab)
        header = ws.row_values(1)
        row = [values.get(col, "") for col in header]
        ws.append_row(row, value_input_option="USER_ENTERED")
    await asyncio.to_thread(_sync)
    return values


async def sheet_update_row(tab: str, where: dict, set_values: dict) -> dict | None:
    """Finds the first row matching ALL `where` columns (exact match) and
    updates `set_values` on it. Returns the updated row dict, or None if
    no row matched."""
    def _sync():
        ws = _ws(tab)
        header = ws.row_values(1)
        all_values = ws.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            row_dict = dict(zip(header, row))
            if all(str(row_dict.get(k, "")).strip() == str(v).strip()
                   for k, v in where.items()):
                for col, val in set_values.items():
                    if col in header:
                        ws.update_cell(idx, header.index(col) + 1, val)
                row_dict.update(set_values)
                return row_dict
        return None
    return await asyncio.to_thread(_sync)


async def sheet_delete_row(tab: str, where: dict) -> bool:
    """Finds the first row matching ALL `where` columns and deletes it."""
    def _sync():
        ws = _ws(tab)
        header = ws.row_values(1)
        all_values = ws.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            row_dict = dict(zip(header, row))
            if all(str(row_dict.get(k, "")).strip() == str(v).strip()
                   for k, v in where.items()):
                ws.delete_rows(idx)
                return True
        return False
    return await asyncio.to_thread(_sync)
```

---

## 6. Changes to `app/services/step_interpreter.py`

Three edits: (a) `_op_resolve_entity` gains sheet dispatch, (b) `_op_insert_row` and `_op_update_row` gain sheet dispatch, (c) a brand-new `_op_delete_row` primitive is added (you don't have a generic delete today — Postgres workflows haven't needed one, but `cancel_purchase_order` does).

### 6.1 Replace `_op_resolve_entity` with:

```python
async def _op_resolve_entity(params: dict, ctx: dict) -> dict:
    table      = params["table"]
    match_col  = params.get("match_column", "name")
    into       = params.get("into", table.rstrip("s"))
    name_path  = params["name_from"]
    name_val   = _resolve_path(ctx, name_path)

    if not name_val:
        raise StepError(f"resolve_entity: no value at '{name_path}'")

    # NEW: table="sheet:TabName" routes to Google Sheets instead of Postgres
    if table.startswith("sheet:"):
        from app.services.sheets_client import sheet_fetch_filtered
        tab = table.split(":", 1)[1]
        rows = await sheet_fetch_filtered(tab, {match_col: name_val})
    else:
        raw_rows = await fetch_all(
            f"SELECT * FROM {table} WHERE org_id = $1 AND {match_col} ILIKE $2 LIMIT 5",
            ctx["org_id"], f"%{name_val}%"
        )
        rows = [dict(r) for r in raw_rows]

    if len(rows) == 0:
        raise StepError(f"No {table} record found matching '{name_val}'")
    if len(rows) > 1:
        raise StepError(f"AMBIGUOUS:{table}:{json.dumps(rows, default=str)}")

    resolved = dict(rows[0])
    ctx[into] = resolved

    for alias, column in (params.get("expose") or {}).items():
        ctx["fields"][alias] = resolved.get(column)

    return ctx
```

### 6.2 Replace `_op_insert_row` with:

```python
async def _op_insert_row(params: dict, ctx: dict) -> dict:
    table  = params["table"]
    values = _resolve_values(params.get("values", {}), ctx)

    # Resolve special date literals
    import datetime as _dt
    for k, v in list(values.items()):
        if v == "TODAY+30":
            values[k] = (_dt.date.today() + _dt.timedelta(days=30)).isoformat()
        elif v == "TODAY+7":
            values[k] = (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
        elif v == "TODAY":
            values[k] = _dt.date.today().isoformat()
        elif v == "NOW()":
            values[k] = _dt.datetime.now(_dt.timezone.utc)

    # NEW: sheet-backed insert
    if table.startswith("sheet:"):
        from app.services.sheets_client import sheet_insert_row, sheet_count_rows
        tab = table.split(":", 1)[1]

        if "sequence" in params:
            seq = params["sequence"]
            count = await sheet_count_rows(tab)
            doc_number = seq["prefix"] + str(seq.get("start", 1000) + count)
            values[seq["field"]] = doc_number
            ctx.setdefault("generated", {})[seq["field"]] = doc_number

        # Serialize lists/dicts same as Postgres path, for consistency
        for k, v in list(values.items()):
            if isinstance(v, (list, dict)):
                values[k] = json.dumps(v)

        await sheet_insert_row(tab, values)
        ctx.setdefault("inserted", {})[tab] = values
        return ctx

    # ── existing Postgres path (unchanged below this line) ──
    if "sequence" in params:
        seq       = params["sequence"]
        count_row = await fetch_one(
            f"SELECT COUNT(*) as cnt FROM {table} WHERE org_id = $1",
            ctx["org_id"]
        )
        doc_number = seq["prefix"] + str(seq.get("start", 100) + int(count_row["cnt"]))
        values[seq["field"]] = doc_number
        ctx.setdefault("generated", {})[seq["field"]] = doc_number

    cols        = list(values.keys())
    sql_values  = [json.dumps(v) if isinstance(v, (list, dict)) else v for v in values.values()]
    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *"

    row = await fetch_one(sql, *sql_values)
    ctx.setdefault("inserted", {})[table] = dict(row)
    return ctx
```

### 6.3 Replace `_op_update_row` with:

```python
async def _op_update_row(params: dict, ctx: dict) -> dict:
    import datetime as _dt
    table       = params["table"]
    set_vals    = _resolve_values(params.get("set", {}), ctx)
    where_vals  = _resolve_values(params.get("where", {}), ctx)

    def _resolve_now(v):
        return _dt.datetime.now(_dt.timezone.utc) if v == "NOW()" else v

    set_vals   = {k: _resolve_now(v) for k, v in set_vals.items()}
    where_vals = {k: _resolve_now(v) for k, v in where_vals.items()}

    # NEW: sheet-backed update
    if table.startswith("sheet:"):
        from app.services.sheets_client import sheet_update_row
        tab = table.split(":", 1)[1]
        updated = await sheet_update_row(tab, where_vals, set_vals)
        if not updated:
            raise StepError(f"db.update_row: no matching row in sheet '{tab}'")
        ctx.setdefault("updated", {})[tab] = updated
        return ctx

    # ── existing Postgres path (unchanged below this line) ──
    set_cols   = list(set_vals.keys())
    where_cols = list(where_vals.keys())
    set_clause   = ", ".join(f"{c} = ${i+1}" for i, c in enumerate(set_cols))
    where_clause = " AND ".join(
        f"{c} = ${i+1+len(set_cols)}" for i, c in enumerate(where_cols)
    )
    sql_values = (
        [json.dumps(v) if isinstance(v, (list, dict)) else v for v in set_vals.values()]
        + list(where_vals.values())
    )
    sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause} RETURNING *"

    row = await fetch_one(sql, *sql_values)
    if not row:
        raise StepError(f"db.update_row: no matching row in {table}")
    ctx.setdefault("updated", {})[table] = dict(row)
    return ctx
```

### 6.4 Add this brand-new function (anywhere near the other `_op_*` functions):

```python
async def _op_delete_row(params: dict, ctx: dict) -> dict:
    """
    Delete one row matching `where`. Supports table="sheet:TabName" and
    plain Postgres tables. NEW primitive — not in the original set.
    """
    table      = params["table"]
    where_vals = _resolve_values(params.get("where", {}), ctx)

    if table.startswith("sheet:"):
        from app.services.sheets_client import sheet_delete_row
        tab = table.split(":", 1)[1]
        ok = await sheet_delete_row(tab, where_vals)
        if not ok:
            raise StepError(f"db.delete_row: no matching row in sheet '{tab}'")
        ctx.setdefault("deleted", {})[tab] = where_vals
        return ctx

    where_cols   = list(where_vals.keys())
    where_clause = " AND ".join(f"{c} = ${i+1}" for i, c in enumerate(where_cols))
    sql = f"DELETE FROM {table} WHERE {where_clause} RETURNING *"
    row = await fetch_one(sql, *where_vals.values())
    if not row:
        raise StepError(f"db.delete_row: no matching row in {table}")
    ctx.setdefault("deleted", {})[table] = dict(row)
    return ctx
```

### 6.5 Update the `PRIMITIVES` registry:

```python
PRIMITIVES = {
    "resolve_entity":    _op_resolve_entity,
    "compute":           _op_compute,
    "otp_gate":          _op_otp_gate,
    "approval_gate":     _op_approval_gate,
    "db.insert_row":     _op_insert_row,
    "db.update_row":     _op_update_row,
    "db.upsert_row":     _op_upsert_row,
    "db.delete_row":     _op_delete_row,    # NEW
    "sheets.insert_row": _op_insert_row,    # NEW — alias, dispatches on "sheet:" prefix
    "sheets.update_row": _op_update_row,    # NEW — alias
    "sheets.delete_row": _op_delete_row,    # NEW — alias
    "pdf.generate":      _op_generate_pdf,
    "notify.whatsapp":   _op_notify_whatsapp,
}
```

> `sheets.insert_row` and `db.insert_row` point at the *same function* — the routing happens on the `table` value's `sheet:` prefix, not the op name. Both aliases exist purely so a workflow's `steps[]` reads naturally either way; use whichever name makes the JSON self-documenting.

---

## 7. Changes to `app/services/agent.py`

### 7.1 Add a schema-loader for Sheets, next to `_get_schema`:

```python
_sheets_schema_cache: str | None = None

async def _get_sheets_schema() -> str:
    """Cached tab/column listing for the Sheets side — same idea as
    _get_schema() but for Google Sheets instead of Postgres."""
    global _sheets_schema_cache
    if _sheets_schema_cache is not None:
        return _sheets_schema_cache
    if not os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID"):
        _sheets_schema_cache = ""
        return ""
    from app.services.sheets_client import get_all_tab_headers
    try:
        tabs = await get_all_tab_headers()
    except Exception as e:
        print(f"[AGENT] Could not load Sheets schema: {e}")
        return ""
    parts = [f"- {tab} (Google Sheets tab): {', '.join(cols)}" for tab, cols in tabs.items()]
    _sheets_schema_cache = "\n".join(parts)
    return _sheets_schema_cache
```

### 7.2 Add the new tool to the `TOOLS` list (alongside `query_database`):

```python
    {
        "type": "function",
        "function": {
            "name": "query_sheet",
            "description": (
                "Read rows from a Google Sheets tab. Use this ONLY for tabs listed under "
                "'GOOGLE SHEETS DATA' in the system prompt — this is a SEPARATE data source "
                "from Postgres (query_database). Never use query_database for these tabs, "
                "and never use query_sheet for customers/invoices/orders/inventory (those "
                "are Postgres — use query_database).\n\n"
                "filters does a case-insensitive PARTIAL match on each column given — "
                "similar to ILIKE '%value%'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tab": {
                        "type": "string",
                        "description": "Exact tab name, e.g. 'Suppliers', 'RawMaterialStock', 'PurchaseOrders'"
                    },
                    "filters": {
                        "type": "object",
                        "description": "Column:value pairs to filter rows by (partial match). Omit to fetch all rows."
                    }
                },
                "required": ["tab"]
            }
        }
    },
```

### 7.3 Handle it in `_execute_tool` (add alongside the `query_database` branch):

```python
    elif tool_name == "query_sheet":
        from app.services.sheets_client import sheet_fetch_filtered
        tab     = tool_input.get("tab", "")
        filters = tool_input.get("filters", {}) or {}
        try:
            rows = await sheet_fetch_filtered(tab, filters)
            if not rows:
                return "EMPTY: No rows returned"
            return json.dumps(rows[:50], default=str)
        except Exception as e:
            return f"ERROR: {str(e)}"
```

### 7.4 Include the Sheets schema in the system prompt

Inside `_build_system_prompt`, right after `schema = await _get_schema(user["org_id"])`, add:

```python
    sheets_schema = await _get_sheets_schema()
```

Then, in the returned prompt string, add a new block right after the `DATABASE SCHEMA` block:

```python
DATABASE SCHEMA (for reference only - use the table/column list above):
{schema}

GOOGLE SHEETS DATA (separate source — use query_sheet tool, NEVER query_database, for these):
{sheets_schema if sheets_schema else "(none configured)"}

RULE S1 — Sheets vs Postgres: PurchaseOrders/Suppliers/RawMaterialStock live in Google
Sheets. Everything else (customers, invoices, orders, inventory) lives in Postgres.
Pick the right tool by which schema block the tab/table name appears under.

RULE S2 — Sheet reads use query_sheet(tab, filters). filters values do partial,
case-insensitive matching automatically — do not add wildcard characters yourself.

{workflow_schema_text}
```

That's it — no other agent.py changes needed. `update_draft` / `confirm_action` / `execute_pending_action` are already fully generic; they don't know or care whether the workflow's `steps[]` touch Postgres or Sheets.

---

## 8. Register the 3 new workflows

These follow the exact same pattern as `create_sales_invoice` — only the `steps[]` differ (they use `sheet:` table names). Run these directly in your Neon SQL console.

### 8.1 `create_purchase_order`

```sql
INSERT INTO workflows (
    org_id, name, intent_key, description, workflow_type,
    training_phrases, entity_schema, calc_rules, steps,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt, pdf_config,
    response_template, otp_required, otp_threshold, approval_threshold,
    adapter_method, version, is_active, trigger_patterns,
    slash_command, command_description, menu_section
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Create Purchase Order',
    'create_purchase_order',
    'Creates a raw-material purchase order against a supplier, stored in the Raw Materials Google Sheet.',
    'action',
    '["create purchase order", "PO banao", "order raw material from {supplier_name}", "raw material order {supplier_name}", "{supplier_name} se material order karo", "purchase order for {supplier_name}", "buy gold from {supplier_name}", "PO {supplier_name}", "naya purchase order banao", "raw material PO"]'::jsonb,
    '{
      "supplier_name": {"type":"string","required":true,"table":"sheet:Suppliers","column":"name","match":"ILIKE","format":"wildcard"},
      "material_name": {"type":"string","required":true},
      "qty":            {"type":"float","required":true},
      "rate":           {"type":"float","required":true},
      "total":            {"type":"float","required":false,"computed":true},
      "status":           {"type":"string","required":false,"computed":true},
      "order_date":       {"type":"string","required":false,"computed":true},
      "expected_delivery":{"type":"string","required":false,"computed":true}
    }'::jsonb,
    '{
      "aggregate_rules": { "total": "round(qty * rate, 2)" }
    }'::jsonb,
    '[
      {"op":"resolve_entity","params":{"table":"sheet:Suppliers","name_from":"$fields.supplier_name","into":"supplier","match_column":"name"}},
      {"op":"compute","params":{}},
      {"op":"sheets.insert_row","params":{
          "table":"sheet:PurchaseOrders",
          "values":{
            "supplier_name":"$fields.supplier_name",
            "material_name":"$fields.material_name",
            "qty":"$fields.qty",
            "rate":"$fields.rate",
            "total":"$computed.total",
            "status":"pending",
            "order_date":"TODAY",
            "expected_delivery":"TODAY+7"
          },
          "sequence":{"field":"po_id","prefix":"PO-","start":1003}
      }},
      {"op":"notify.whatsapp","params":{"attach_pdf": false}}
    ]'::jsonb,
    NULL, '[]'::jsonb, NULL,
    '{"PO":"Purchase Order — a request to a supplier to deliver raw material", "raw material":"gold, silver, diamonds, gemstones purchased before manufacturing", "bhav":"the rate per gram/piece being paid to the supplier"}'::jsonb,
    'Creates a new row in the PurchaseOrders Google Sheet tab. Needs supplier_name (must match a row in the Suppliers sheet), material_name, qty, rate. total is auto-computed (qty * rate) — never ask the user for it. Example: "PO banao Rajesh Bullion Traders se 500 grams 22kt gold @ 6200". intent_key: create_purchase_order. This is NOT for sales invoices/quotations to customers — those stay in Postgres.',
    NULL,
    '✅ *Purchase Order Created*\n\nPO #: *{po_id}*\nSupplier: {supplier_name}\nMaterial: {material_name}\nQty: {qty}\nTotal: Rs.{total}\n\n_Status: pending_',
    false, NULL, NULL,
    'generic', 1, true, '[]'::jsonb,
    'po', 'Create a raw-material purchase order (Sheets)', 'create'
);

UPDATE roles SET permissions = array_append(permissions, 'create_purchase_order')
WHERE org_id = '11111111-0000-0000-0000-000000000001' AND name = 'owner'
  AND NOT 'create_purchase_order' = ANY(permissions);
```

### 8.2 `update_purchase_order_status`

```sql
INSERT INTO workflows (
    org_id, name, intent_key, description, workflow_type,
    training_phrases, entity_schema, calc_rules, steps,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt, pdf_config,
    response_template, otp_required, otp_threshold, approval_threshold,
    adapter_method, version, is_active, trigger_patterns,
    slash_command, command_description, menu_section
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Update Purchase Order Status',
    'update_purchase_order_status',
    'Updates the status of an existing purchase order in the Raw Materials Google Sheet.',
    'action',
    '["mark PO-{po_id} as {new_status}", "update PO {po_id} status", "{po_id} ko {new_status} karo", "PO {po_id} received hai", "change status of {po_id}", "{po_id} status update karo", "mark {po_id} received", "mark {po_id} delivered"]'::jsonb,
    '{
      "po_id":      {"type":"string","required":true},
      "new_status": {"type":"string","required":true}
    }'::jsonb,
    '{}'::jsonb,
    '[
      {"op":"sheets.update_row","params":{
          "table":"sheet:PurchaseOrders",
          "set":{"status":"$fields.new_status"},
          "where":{"po_id":"$fields.po_id"}
      }},
      {"op":"notify.whatsapp","params":{"attach_pdf": false}}
    ]'::jsonb,
    NULL, '[]'::jsonb, NULL,
    '{"received":"material has physically arrived from the supplier", "pending":"order placed, not yet arrived"}'::jsonb,
    'Updates the status column of one row in the PurchaseOrders Google Sheet by po_id. Needs po_id (e.g. PO-1002) and new_status (e.g. received, pending, cancelled). Example: "mark PO-1002 as received". intent_key: update_purchase_order_status.',
    NULL,
    '✅ *PO Updated*\n\n{po_id} status changed to *{new_status}*.',
    false, NULL, NULL,
    'generic', 1, true, '[]'::jsonb,
    'postatus', 'Update a purchase order status (Sheets)', 'create'
);

UPDATE roles SET permissions = array_append(permissions, 'update_purchase_order_status')
WHERE org_id = '11111111-0000-0000-0000-000000000001' AND name = 'owner'
  AND NOT 'update_purchase_order_status' = ANY(permissions);
```

### 8.3 `cancel_purchase_order`

```sql
INSERT INTO workflows (
    org_id, name, intent_key, description, workflow_type,
    training_phrases, entity_schema, calc_rules, steps,
    sql_template, sql_params_order, response_format,
    business_glossary, llm_system_prompt, pdf_config,
    response_template, otp_required, otp_threshold, approval_threshold,
    adapter_method, version, is_active, trigger_patterns,
    slash_command, command_description, menu_section
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'Cancel Purchase Order',
    'cancel_purchase_order',
    'Deletes a purchase order row from the Raw Materials Google Sheet.',
    'action',
    '["cancel PO-{po_id}", "cancel purchase order {po_id}", "{po_id} cancel karo", "delete {po_id}", "remove {po_id}", "PO {po_id} galat hai hata do", "{po_id} wrong order cancel it"]'::jsonb,
    '{
      "po_id": {"type":"string","required":true}
    }'::jsonb,
    '{}'::jsonb,
    '[
      {"op":"sheets.delete_row","params":{
          "table":"sheet:PurchaseOrders",
          "where":{"po_id":"$fields.po_id"}
      }},
      {"op":"notify.whatsapp","params":{"attach_pdf": false}}
    ]'::jsonb,
    NULL, '[]'::jsonb, NULL,
    '{"cancel":"remove the purchase order entirely, it never happened"}'::jsonb,
    'Deletes one row from the PurchaseOrders Google Sheet by po_id. Needs po_id only. This is a hard delete — confirm clearly before executing. Example: "cancel PO-1003". intent_key: cancel_purchase_order.',
    NULL,
    '🗑️ *Purchase Order Cancelled*\n\n{po_id} has been removed.',
    false, NULL, NULL,
    'generic', 1, true, '[]'::jsonb,
    'pocancel', 'Cancel/delete a purchase order (Sheets)', 'create'
);

UPDATE roles SET permissions = array_append(permissions, 'cancel_purchase_order')
WHERE org_id = '11111111-0000-0000-0000-000000000001' AND name = 'owner'
  AND NOT 'cancel_purchase_order' = ANY(permissions);
```

> Note: **reads** (`query_sheet`) need no `workflows` row and no permission grant at all — exactly like `query_database`, they're available to the agent the moment the tool exists and the schema is in the prompt. Only **writes** need a formal workflow because `execute_pending_action` looks up `workflows` by `intent_key`.

---

## 9. Deploy

1. Commit `sheets_client.py` and the `step_interpreter.py` / `agent.py` diffs.
2. Confirm `GOOGLE_SHEETS_CREDENTIALS_B64` and `GOOGLE_SHEETS_SPREADSHEET_ID` are set on Railway.
3. Push / redeploy.
4. Run the 3 `INSERT INTO workflows` statements + permission grants from section 8 against your Neon DB (once — not on every deploy).
5. Since `_schema_cache` and `_sheets_schema_cache` are in-memory, a fresh deploy naturally picks up the new schema. If you add sheet tabs later without redeploying, call `invalidate_schema_cache` equivalent — for now just restart the service.

---

## 10. Test scenarios via WhatsApp

Send these to your bot number one at a time, in order (later ones depend on earlier ones).

### Scenario 1 — Read: simple stock check
> **You:** `22kt gold stock kitna hai`

Expected: agent calls `query_sheet(tab="RawMaterialStock", filters={"material_name": "22kt Gold"})`, replies with qty_available = 1200 grams, reorder_level, last_purchase_rate.

### Scenario 2 — Read: filtered lookup
> **You:** `show me all gold suppliers`

Expected: `query_sheet(tab="Suppliers", filters={"material_type": "Gold"})` → returns Rajesh Bullion Traders (Mumbai) and Kolkata Gold Refinery.

### Scenario 3 — Create (full CRUD write #1)
> **You:** `PO banao Rajesh Bullion Traders se 500 grams 22kt gold bar rate 6200`

Expected flow:
1. Agent resolves "Rajesh Bullion Traders" → 1 match in `Suppliers` sheet.
2. `update_draft(intent_key="create_purchase_order", fields={supplier_name, material_name: "22kt Gold Bar", qty: 500, rate: 6200}, stage="awaiting_confirmation")`
3. `confirm_action` — shows total = Rs.31,00,000 (computed, not LLM-typed)
4. **You:** `yes`
5. Bot: `✅ Purchase Order Created — PO #: PO-1003 ...`
6. Open the Google Sheet — a new row appears in `PurchaseOrders` with `po_id = PO-1003`, `status = pending`, `order_date` = today, `expected_delivery` = today+7.

### Scenario 4 — Update (full CRUD write #2)
> **You:** `mark PO-1002 as received`

Expected: `update_draft → confirm_action → yes` → bot confirms; in the Sheet, `PO-1002`'s `status` cell flips from `pending` to `received`. `PO-1001`/other rows untouched.

### Scenario 5 — Delete (full CRUD write #3)
> **You:** `cancel PO-1003, wrong order`

Expected: confirm → `yes` → bot: `🗑️ Purchase Order Cancelled — PO-1003 has been removed.` The row physically disappears from the Sheet (not just status-flagged).

### Scenario 6 — Ambiguity handling
> **You:** `gold stock`

Expected: two rows match ("22kt Gold Bar" and "24kt Gold Bar") — agent should call `clarify` rather than guessing, listing both options.

### Scenario 7 — Cross-source sanity check
> **You:** `Mehta Enterprises ka baaki` (an existing Postgres query)

Expected: still works exactly as before — proves adding Sheets support didn't disturb the Postgres path. The system prompt's RULE S1 is what keeps the LLM routing correctly.

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `403 PERMISSION_DENIED` | Sheet not shared with the service account | Re-check step 2.2 — share with the exact `client_email`, role **Editor** |
| `SpreadsheetNotFound` | Wrong `GOOGLE_SHEETS_SPREADSHEET_ID` | Re-copy the ID from the URL (between `/d/` and `/edit`) |
| `WorksheetNotFound: Suppliers` | Tab name typo or trailing space | Tab names are case- and space-sensitive; rename to match exactly |
| Numbers show up as strings, `calc_engine` errors on `qty * rate` | Sheet columns formatted as Text | Select the numeric columns → Format → Number → **Number** |
| `RuntimeError: GOOGLE_SHEETS_CREDENTIALS_B64 is not set` | Env var missing or app not restarted after adding it | Re-check Railway Variables tab, redeploy |
| Writes succeed but reads still show old data | `lru_cache` on `_get_client`/`_get_spreadsheet` — this is fine, connections are meant to be reused. If *rows* look stale, it's Google's own caching layer (rare) — retry once. | N/A, self-resolves |
| `APIError: Quota exceeded` (HTTP 429) | Google Sheets API default quota is ~300 read requests/min per project (shared, plenty for testing) | Space out rapid-fire test messages; for production-scale sheet reads consider caching `sheet_fetch_all` results for a few seconds |
| Agent uses `query_database` instead of `query_sheet` for a Sheets tab | `_sheets_schema_cache` empty (spreadsheet ID missing at first boot) or RULE S1 unclear | Confirm env vars were set *before* the process started; check logs for `[AGENT] Could not load Sheets schema` |

---

## 12. Security checklist

- [ ] `orchestrai-sheets-integration-xxxxx.json` is in `.gitignore`, never committed
- [ ] `GOOGLE_SHEETS_CREDENTIALS_B64` only exists as an env var (local `.env`, Railway Variables) — never hardcoded in source
- [ ] Service account has **Editor** access to only this one spreadsheet, not your whole Drive
- [ ] `cancel_purchase_order` (a hard delete) still goes through `confirm_action` like every other write — never skip the confirmation step even for "simple" sheet ops
- [ ] Consider adding `otp_threshold` to `create_purchase_order` later if purchase amounts can get large, exactly like you do for `create_sales_invoice` — the `otp_gate` step primitive already works unchanged against `$computed.total` regardless of backend

---

## 13. What this doesn't cover yet (future work)

- **Admin chat workflow builder** (`workflow_builder_agent.py` / `workflow_compiler.py`) doesn't know about the `sheet:` prefix convention yet — the 3 workflows above were registered by hand-written SQL. Teaching the compiler to recognize `"data_source": "sheet"` in a draft and emit `sheet:` table names automatically would let you build Sheets-backed workflows conversationally, same as Postgres ones.
- **`workflow_validator.py`** doesn't currently distinguish sheet vs Postgres tables in any of its checks — it doesn't need to (its checks are about `calc_rules`/`entity_schema` consistency, backend-agnostic), but if you add sheet-specific constraints later (e.g. required tabs existing) that validator is the right place.
- **Scheduled reports** (`jobs.py`) call `run_agent` with a plain text query — since `query_sheet` is just another tool the agent can pick, a scheduled report like `"raw material stock summary"` should already work through the existing scheduler without any changes, but hasn't been tested here — worth a quick manual check.
- **PDF generation from Sheets data** — `generate_pdf` already accepts arbitrary `rows`/`extra_context`, so a "Purchase Order PDF" is just a matter of adding `pdf.generate` + `notify.whatsapp{attach_pdf:true}` to `create_purchase_order`'s steps, reusing your existing `pdf_engine.py` untouched.
