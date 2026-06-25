import os
import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from app.db import fetch_all, fetch_one, execute
from openai import AsyncOpenAI

router = APIRouter()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "orchestrai_admin_2024")
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _check_token(request: Request):
    token = request.query_params.get("token") or \
            request.headers.get("X-Admin-Token")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    _check_token(request)
    token = request.query_params.get("token", "")
    return HTMLResponse(content=_build_html(token))


@router.get("/admin/api/data")
async def admin_data(request: Request):
    _check_token(request)

    org = await fetch_one("SELECT id, name FROM orgs WHERE is_active = true LIMIT 1")
    if not org:
        return {"error": "No active org found"}

    org_id = str(org["id"])

    workflows = await fetch_all("""
        SELECT id, name, intent_key, is_active, otp_required,
               otp_threshold, approval_threshold, last_run
        FROM workflows WHERE org_id = $1
        ORDER BY created_at
    """, org_id)

    stats = await fetch_one("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'approved') AS total_invoices,
            COALESCE(SUM(amount) FILTER (WHERE status = 'overdue'), 0) AS total_overdue,
            COUNT(*) FILTER (WHERE status = 'pending') AS pending_approvals
        FROM invoices WHERE org_id = $1
    """, org_id)

    low_stock = await fetch_all("""
        SELECT name, qty, reorder_level FROM inventory
        WHERE org_id = $1 AND qty <= reorder_level
    """, org_id)

    recent_logs = await fetch_all("""
        SELECT a.intent_key, a.outcome, a.otp_used,
               a.created_at, u.name as user_name
        FROM audit_log a
        LEFT JOIN users u ON u.id = a.user_id
        WHERE a.org_id = $1
        ORDER BY a.created_at DESC LIMIT 8
    """, org_id)

    return {
        "org": dict(org),
        "workflows": [dict(w) for w in workflows],
        "stats": dict(stats),
        "low_stock": [dict(r) for r in low_stock],
        "recent_logs": [dict(r) for r in recent_logs]
    }


@router.post("/admin/api/workflow/{workflow_id}/toggle")
async def toggle_otp(workflow_id: str, request: Request):
    _check_token(request)
    row = await fetch_one(
        "SELECT otp_required FROM workflows WHERE id = $1", workflow_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    new_val = not row["otp_required"]
    await execute(
        "UPDATE workflows SET otp_required = $1 WHERE id = $2",
        new_val, workflow_id
    )
    return {"otp_required": new_val}


@router.post("/admin/api/workflow/{workflow_id}/threshold")
async def update_threshold(workflow_id: str, request: Request):
    _check_token(request)
    body = await request.json()
    threshold = float(body.get("threshold", 50000))
    await execute(
        "UPDATE workflows SET otp_threshold = $1 WHERE id = $2",
        threshold, workflow_id
    )
    return {"otp_threshold": threshold}


@router.post("/admin/api/workflow/{workflow_id}/approval_threshold")
async def update_approval_threshold(workflow_id: str, request: Request):
    _check_token(request)
    body = await request.json()
    threshold = float(body.get("threshold", 100000))
    await execute(
        "UPDATE workflows SET approval_threshold = $1 WHERE id = $2",
        threshold, workflow_id
    )
    return {"approval_threshold": threshold}


@router.get("/admin/api/roles")
async def get_roles(request: Request):
    _check_token(request)
    roles = await fetch_all("SELECT name FROM roles ORDER BY name")
    return [{"name": r["name"], "selected": r["name"] == "owner"} for r in roles]


@router.get("/admin/api/security")
async def get_security_settings(request: Request):
    _check_token(request)
    org = await fetch_one(
        "SELECT session_ttl_minutes FROM orgs WHERE is_active = true LIMIT 1"
    )
    return {"session_ttl_minutes": org["session_ttl_minutes"] or 480}


@router.post("/admin/api/security/ttl")
async def update_session_ttl(request: Request):
    _check_token(request)
    body = await request.json()
    minutes = int(body.get("minutes", 480))
    if minutes < 5 or minutes > 10080:  # 5 min to 7 days
        raise HTTPException(status_code=400, detail="TTL must be between 5 and 10080 minutes")
    await execute(
        "UPDATE orgs SET session_ttl_minutes = $1 WHERE is_active = true", minutes
    )
    return {"session_ttl_minutes": minutes}


@router.post("/admin/api/sessions/clear")
async def admin_clear_sessions(request: Request):
    _check_token(request)
    from app.redis_client import clear_all_sessions
    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1")
    await clear_all_sessions(str(org["id"]))
    return {"cleared": True, "message": "All sessions cleared"}


@router.post("/admin/api/workflow/generate")
async def generate_workflow_config(request: Request):
    _check_token(request)
    body = await request.json()
    description = body.get("description", "")
    
    if not description:
        raise HTTPException(status_code=400, detail="Description is required")
    
    prompt = f"""You are a workflow configuration generator for a WhatsApp business automation system.

User wants to add this workflow:
"{description}"

Generate ONLY this JSON structure with no other text:
{{
  "name": "2-4 word name",
  "intent_key": "exact_function_name_from_adapter_method",
  "description": "Rich description with examples, keywords, entity_type, business context",
  "adapter_method": "module.function format",
  "trigger_patterns": ["pattern1", "pattern2", "pattern3", "pattern4"],
  "steps": ["step1", "step2", "step3"]
}}

Rules:
- name: 2-4 words
- intent_key: MUST match the function name from adapter_method exactly (e.g., if adapter_method is "inventory.check_stock", intent_key MUST be "check_stock")
- description: Rich text block containing:
  * What the workflow does (1 sentence)
  * 4 example user queries in quotes
  * Keywords that signal this intent
  * Entity type (product/customer/order/invoice/quotation)
  * Business context (who uses it and when)
  Example: "Check stock level of a specific product. Examples: 'stock gold ring', 'how many diamond bangles', 'inventory silver chain', 'what is the stock of platinum necklace'. Keywords: stock, inventory, quantity, how many, available. Entity type: product. Output: product name, quantity, location, reorder status. Used by sales/warehouse to check availability before promising to customers."
- adapter_method: must be in "module.function" format (e.g., "crm.get_credit_limit", "inventory.check_stock", "quotation.create_quotation", "orders.create_order", "accounting.create_invoice")
- trigger_patterns: 4-6 regex patterns users would type
  * If entity_type is product/customer/order, include (.+) capture group: "stock (.+)", "dues (.+)"
  * If no entity needed, no capture group: "show all inventory", "dues report"
  * Use simple patterns: "stock (.+)", "how many (.+)", "(.+) available", "inventory (.+)"
- steps: 3-5 step-by-step description of what the workflow does:
  * Step 1: What input it needs (entity extraction)
  * Step 2: What operation it performs (DB query, calculation)
  * Step 3: What output it returns (formatted message, PDF, etc.)
  * Step 4: Any special handling (OTP, approval, disambiguation)
  Example: ["Extract product name from user query", "Query inventory database for product stock", "Return product details: name, quantity, location, reorder status", "Handle fuzzy matching if exact product not found"]

IMPORTANT: The intent_key MUST be the exact function name from adapter_method, not a new name.

Return ONLY the JSON. No explanations, no markdown, no extra text."""

    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    content = response.choices[0].message.content.strip()
    
    # Clean up if AI adds markdown code blocks or extra text
    if "```json" in content:
        # Extract content between ```json and ```
        start = content.find("```json") + 7
        end = content.find("```", start)
        if end != -1:
            content = content[start:end].strip()
    elif "```" in content:
        # Extract content between first ``` and next ```
        start = content.find("```") + 3
        end = content.find("```", start)
        if end != -1:
            content = content[start:end].strip()
    
    # Try to find JSON object boundaries
    if content.startswith("{") and content.endswith("}"):
        # Already looks like JSON
        pass
    else:
        # Try to extract JSON from mixed content
        start_idx = content.find("{")
        end_idx = content.rfind("}") + 1
        if start_idx != -1 and end_idx > start_idx:
            content = content[start_idx:end_idx]
    
    try:
        config = json.loads(content)
        return config
    except json.JSONDecodeError as e:
        # Return the raw content for debugging
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to parse AI response. Error: {str(e)}. Raw response: {content[:500]}"
        )


@router.post("/admin/api/workflow/save")
async def save_generated_workflow(request: Request):
    _check_token(request)
    body = await request.json()
    
    # Use AI-generated adapter_method
    adapter_method = body.get("adapter_method", "generic")
    
    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1")
    if not org:
        raise HTTPException(status_code=404, detail="No active org found")
    
    org_id = str(org["id"])
    
    # Check if intent_key already exists
    existing = await fetch_one(
        "SELECT id FROM workflows WHERE org_id = $1 AND intent_key = $2",
        org_id, body.get("intent_key")
    )
    if existing:
        raise HTTPException(status_code=400, detail="Intent key already exists")
    
    await execute("""
        INSERT INTO workflows (
            org_id, name, intent_key, description, trigger_patterns, steps, adapter_method,
            otp_required, otp_threshold, approval_threshold, is_active
        ) VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb[], $7, $8, $9, $10, true)
    """, 
        org_id,
        body.get("name"),
        body.get("intent_key"),
        body.get("description"),
        json.dumps(body.get("trigger_patterns", [])),  # Save actual patterns from AI
        body.get("steps", []),  # Pass as Python list for jsonb[] type
        adapter_method,
        body.get("otp_required", False),
        body.get("otp_threshold"),
        body.get("approval_threshold")
    )
    
    # Add permission to selected roles
    intent_key = body.get("intent_key")
    selected_roles = body.get("roles", ["owner"])  # Default to owner if none selected
    for role_name in selected_roles:
        await execute("""
            UPDATE roles 
            SET permissions = array_append(permissions, $1)
            WHERE name = $2 AND NOT $1 = ANY(permissions)
        """, intent_key, role_name)
    
    # Invalidate classifier cache so new patterns are active immediately
    from app.classifier.classifier import invalidate_patterns_cache
    invalidate_patterns_cache(org_id)
    
    return {"success": True, "message": f"Workflow saved and permission added to {len(selected_roles)} role(s)"}


@router.get("/admin/api/metal-rates")
async def get_metal_rates(request: Request):
    _check_token(request)
    org = await fetch_one("SELECT id, gst_rate FROM orgs WHERE is_active = true LIMIT 1")
    rates = await fetch_all(
        "SELECT metal_type, rate_per_gram, making_charge_pct, updated_at "
        "FROM metal_rates WHERE org_id = $1 ORDER BY metal_type",
        str(org["id"])
    )
    return {
        "gst_rate": float(org["gst_rate"]) if org["gst_rate"] else 3.0,
        "rates": [dict(r) for r in rates]
    }


@router.post("/admin/api/metal-rates/{metal_type}")
async def update_metal_rate(metal_type: str, request: Request):
    _check_token(request)
    body = await request.json()
    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1")
    org_id = str(org["id"])

    rate = float(body.get("rate_per_gram", 0))
    making = float(body.get("making_charge_pct", 15))

    await execute("""
        INSERT INTO metal_rates (org_id, metal_type, rate_per_gram, making_charge_pct)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (org_id, metal_type) DO UPDATE
        SET rate_per_gram = $3, making_charge_pct = $4, updated_at = NOW()
    """, org_id, metal_type, rate, making)
    return {"success": True}


@router.post("/admin/api/gst-rate")
async def update_gst_rate(request: Request):
    _check_token(request)
    body = await request.json()
    gst = float(body.get("gst_rate", 3.0))
    await execute(
        "UPDATE orgs SET gst_rate = $1 WHERE is_active = true", gst
    )
    return {"gst_rate": gst}


def _build_html(token: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OrchestrAI Admin</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#f0f4f8;color:#1a1a2e;font-size:14px}}
.header{{background:#185FA5;color:#fff;padding:16px 28px;
  display:flex;justify-content:space-between;align-items:center}}
.header h1{{font-size:20px;font-weight:600}}
.header span{{font-size:12px;opacity:0.8}}
.container{{max-width:1100px;margin:0 auto;padding:24px 20px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:16px;margin-bottom:24px}}
.stat-card{{background:#fff;border-radius:10px;padding:18px 20px;
  border-left:4px solid #185FA5;box-shadow:0 1px 4px rgba(0,0,0,0.08)}}
.stat-label{{font-size:11px;color:#888;text-transform:uppercase;
  letter-spacing:0.8px;margin-bottom:6px}}
.stat-value{{font-size:26px;font-weight:600;color:#185FA5}}
.stat-sub{{font-size:11px;color:#aaa;margin-top:3px}}
.card{{background:#fff;border-radius:10px;padding:20px;margin-bottom:20px;
  box-shadow:0 1px 4px rgba(0,0,0,0.08)}}
.card-title{{font-size:14px;font-weight:600;color:#185FA5;margin-bottom:16px;
  padding-bottom:10px;border-bottom:1px solid #e8edf5}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;font-size:11px;text-transform:uppercase;
  letter-spacing:0.6px;color:#888;padding:0 0 10px 0;font-weight:500}}
td{{padding:10px 0;border-bottom:1px solid #f0f4f8;font-size:13px;vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
.badge{{display:inline-block;padding:2px 8px;border-radius:4px;
  font-size:11px;font-weight:500}}
.badge-active{{background:#dcfce7;color:#16a34a}}
.badge-inactive{{background:#fee2e2;color:#dc2626}}
.badge-success{{background:#dbeafe;color:#185FA5}}
.badge-pending{{background:#fef9c3;color:#854d0e}}
.badge-failed{{background:#fee2e2;color:#dc2626}}
.toggle-wrap{{display:flex;align-items:center;gap:10px}}
.toggle{{position:relative;width:42px;height:24px}}
.toggle input{{opacity:0;width:0;height:0}}
.slider{{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;
  background:#ccc;border-radius:24px;transition:.3s}}
.slider:before{{position:absolute;content:"";height:18px;width:18px;
  left:3px;bottom:3px;background:white;border-radius:50%;transition:.3s}}
input:checked+.slider{{background:#185FA5}}
input:checked+.slider:before{{transform:translateX(18px)}}
.threshold-input{{border:1px solid #e8edf5;border-radius:6px;
  padding:4px 8px;width:100px;font-size:12px;color:#1a1a2e}}
.threshold-input:focus{{outline:none;border-color:#185FA5}}
.save-btn{{background:#185FA5;color:#fff;border:none;border-radius:6px;
  padding:5px 12px;font-size:12px;cursor:pointer}}
.save-btn:hover{{background:#1250a0}}
.low-stock-item{{color:#dc2626;font-weight:500}}
.loading{{text-align:center;padding:40px;color:#888}}
</style>
</head>
<body>
<div class="header">
  <h1>🎛 OrchestrAI Admin</h1>
  <span id="orgName">Loading...</span>
</div>
<div class="container">
  <div id="loading" class="loading">Loading dashboard...</div>
  <div id="content" style="display:none">

    <div class="stats" id="statsGrid"></div>

    <div class="card" style="border-left:4px solid #8b5cf6;margin-bottom:20px">
      <div class="card-title" style="color:#8b5cf6">🤖 AI Workflow Builder</div>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div>
          <div class="stat-label">Describe the workflow you want to add</div>
          <textarea id="workflowDescription" rows="2" placeholder="e.g., I want users to check customer credit limits"
            style="width:100%;border:1px solid #e8edf5;border-radius:6px;padding:8px;font-size:13px;
                   margin-top:6px;font-family:inherit;resize:vertical"></textarea>
        </div>
        <button onclick="generateWorkflow()" 
          style="background:#8b5cf6;color:#fff;border:none;border-radius:6px;
                 padding:8px 16px;cursor:pointer;font-size:13px;font-weight:500;width:fit-content">
          ✨ Generate Config
        </button>
      </div>
      
      <div id="workflowForm" style="display:none;margin-top:16px;padding-top:16px;
                                   border-top:1px solid #e8edf5">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
          <div>
            <div class="stat-label">Workflow Name</div>
            <input class="threshold-input" type="text" id="wfName" style="width:100%" readonly>
          </div>
          <div>
            <div class="stat-label">Intent Key</div>
            <input class="threshold-input" type="text" id="wfIntentKey" style="width:100%" readonly>
          </div>
        </div>
        <div style="margin-bottom:12px">
          <div class="stat-label">Description</div>
          <textarea id="wfDescription" rows="2" readonly
            style="width:100%;border:1px solid #e8edf5;border-radius:6px;padding:8px;font-size:13px;
                   font-family:inherit;resize:vertical"></textarea>
        </div>
        <div style="display:flex;gap:20px;align-items:center;margin-bottom:12px">
          <label style="display:flex;align-items:center;gap:6px;font-size:13px">
            <input type="checkbox" id="wfOtpRequired">
            <span>Require OTP verification</span>
          </label>
          <div style="display:flex;align-items:center;gap:6px">
            <span style="font-size:13px">OTP Threshold:</span>
            <input class="threshold-input" type="number" id="wfOtpThreshold" style="width:80px">
          </div>
          <div style="display:flex;align-items:center;gap:6px">
            <span style="font-size:13px">Approval Threshold:</span>
            <input class="threshold-input" type="number" id="wfApprovalThreshold" style="width:80px">
          </div>
        </div>
        <div style="margin-bottom:12px">
          <div class="stat-label">Allowed Roles</div>
          <div id="roleCheckboxes" style="display:flex;gap:12px;flex-wrap:wrap;margin-top:6px">
            <!-- Role checkboxes loaded dynamically -->
          </div>
        </div>
        <div style="display:flex;gap:8px">
          <button onclick="saveWorkflow()" 
            style="background:#8b5cf6;color:#fff;border:none;border-radius:6px;
                   padding:8px 16px;cursor:pointer;font-size:13px;font-weight:500">
            💾 Save Workflow
          </button>
          <button onclick="cancelWorkflow()" 
            style="background:#e5e7eb;color:#374151;border:none;border-radius:6px;
                   padding:8px 16px;cursor:pointer;font-size:13px;font-weight:500">
            Cancel
          </button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">💰 Metal Rates & Making Charges</div>
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:16px;flex-wrap:wrap">
        <div style="font-size:13px;color:#555">GST Rate:</div>
        <input class="threshold-input" type="number" id="gst_rate_input"
          value="3" step="0.5" style="width:60px">
        <span style="font-size:12px;color:#888">%</span>
        <button class="save-btn" onclick="saveGST()">Save GST</button>
      </div>
      <div style="margin-bottom:12px">
        <div style="font-size:13px;color:#555">Add New Metal Type:</div>
        <div style="display:flex;gap:8px;align-items:center;margin-top:6px">
          <input class="threshold-input" type="text" id="new_metal_type" placeholder="e.g., 22kt" style="width:80px;text-transform:lowercase">
          <input class="threshold-input" type="number" id="new_rate" placeholder="Rate/g" style="width:100px">
          <input class="threshold-input" type="number" id="new_making" placeholder="Making %" style="width:80px" step="0.5">
          <button class="save-btn" onclick="addNewMetal()">Add</button>
        </div>
      </div>
      <table id="ratesTable">
        <thead>
          <tr>
            <th>Metal</th>
            <th>Rate per gram (Rs.)</th>
            <th>Making Charges (%)</th>
            <th>Last Updated</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="ratesBody"></tbody>
      </table>
    </div>

    <div class="card" style="border-left:4px solid #dc2626;margin-bottom:20px">
      <div class="card-title" style="color:#dc2626">🔒 Security — Session Management</div>
      <div style="display:flex;align-items:flex-start;gap:32px;flex-wrap:wrap">
        <div>
          <div class="stat-label">Session Timeout</div>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap">
            <input class="threshold-input" type="number" id="ttl_value"
              value="8" min="1" max="10080" style="width:70px">
            <select id="ttl_unit" style="border:1px solid #e8edf5;border-radius:6px;
              padding:4px 8px;font-size:12px;color:#555;background:#fff">
              <option value="minutes">minutes</option>
              <option value="hours">hours</option>
            </select>
            <button class="save-btn" onclick="saveTTL()">Save</button>
          </div>
          <div style="font-size:11px;color:#aaa;margin-top:4px">
            Users re-verify via email OTP after this duration of inactivity
          </div>
        </div>
        <div style="margin-left:auto;text-align:right">
          <button onclick="clearSessions()"
            style="background:#dc2626;color:#fff;border:none;border-radius:6px;
                   padding:10px 20px;cursor:pointer;font-size:13px;font-weight:500">
            🔒 Clear All Sessions
          </button>
          <div style="font-size:11px;color:#aaa;margin-top:4px">
            Emergency: forces all users to re-authenticate immediately
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">⚙️ Workflow Configuration</div>
      <table>
        <thead>
          <tr>
            <th>Workflow</th>
            <th>Intent Key</th>
            <th>Status</th>
            <th>OTP Required</th>
            <th>OTP Threshold (Rs.)</th>
            <th>Approval Threshold (Rs.)</th>
            <th>Last Run</th>
          </tr>
        </thead>
        <tbody id="workflowsTable"></tbody>
      </table>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
      <div class="card">
        <div class="card-title">⚠️ Low Stock Alerts</div>
        <table>
          <thead><tr><th>Item</th><th>Current</th><th>Reorder</th></tr></thead>
          <tbody id="lowStockTable"></tbody>
        </table>
      </div>
      <div class="card">
        <div class="card-title">📋 Recent Activity</div>
        <table>
          <thead><tr><th>User</th><th>Action</th><th>OTP</th><th>Status</th></tr></thead>
          <tbody id="activityTable"></tbody>
        </table>
      </div>
    </div>

  </div>
</div>

<script>
const TOKEN = "{token}";
const API = (path) => `/admin/api${{path}}?token=${{TOKEN}}`;

async function saveTTL() {{
  const val = parseInt(document.getElementById('ttl_value').value);
  const unit = document.getElementById('ttl_unit').value;
  const minutes = unit === 'hours' ? val * 60 : val;
  await fetch(API('/security/ttl'), {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{minutes: minutes}})
  }});
  const label = unit === 'hours' ? `${{val}} hour${{val > 1 ? 's' : ''}}` : `${{val}} minute${{val > 1 ? 's' : ''}}`;
  alert(`✅ Session timeout set to ${{label}}`);
}}

async function clearSessions() {{
  if (!confirm('⚠️ This will immediately log out ALL users.\\nThey must re-verify on next message.\\n\\nProceed?')) return;
  const resp = await fetch(API('/sessions/clear'), {{method: 'POST'}});
  const data = await resp.json();
  alert('🔒 All sessions cleared. Every user must re-authenticate.');
}}

async function loadRates() {{
  try {{
    const data = await fetch(API('/metal-rates')).then(r => r.json());
    document.getElementById('gst_rate_input').value = data.gst_rate || 3;
    const html = data.rates.map(r => `
      <tr>
        <td><strong>${{r.metal_type.toUpperCase()}}</strong></td>
        <td>
          <input class="threshold-input" type="number"
            id="rate_${{r.metal_type}}" value="${{r.rate_per_gram}}" step="50">
        </td>
        <td>
          <input class="threshold-input" type="number"
            id="making_${{r.metal_type}}" value="${{r.making_charge_pct}}" step="0.5"
            style="width:70px">
          <span style="font-size:11px;color:#888">%</span>
        </td>
        <td style="font-size:11px;color:#888">
          ${{r.updated_at ? new Date(r.updated_at).toLocaleDateString('en-IN') : '—'}}
        </td>
        <td>
          <button class="save-btn" onclick="saveRate('${{r.metal_type}}')">Save</button>
        </td>
      </tr>`).join('');
    document.getElementById('ratesBody').innerHTML = html;
  }} catch(e) {{}}
}}

async function saveRate(metalType) {{
  const rate = parseFloat(document.getElementById('rate_' + metalType).value);
  const making = parseFloat(document.getElementById('making_' + metalType).value);
  await fetch(API('/metal-rates/' + metalType), {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{rate_per_gram: rate, making_charge_pct: making}})
  }});
  alert(`✅ ${{metalType.toUpperCase()}} rate updated: Rs.${{rate.toLocaleString('en-IN')}}/g | Making: ${{making}}%`);
}}

async function saveGST() {{
  const gst = parseFloat(document.getElementById('gst_rate_input').value);
  await fetch(API('/gst-rate'), {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{gst_rate: gst}})
  }});
  alert(`✅ GST rate updated to ${{gst}}%`);
}}

async function addNewMetal() {{
  const metalType = document.getElementById('new_metal_type').value.trim().toLowerCase();
  const rate = parseFloat(document.getElementById('new_rate').value);
  const making = parseFloat(document.getElementById('new_making').value);
  
  if (!metalType || isNaN(rate) || isNaN(making)) {{
    alert('Please fill in all fields');
    return;
  }}
  
  await fetch(API('/metal-rates/' + metalType), {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{rate_per_gram: rate, making_charge_pct: making}})
  }});
  
  document.getElementById('new_metal_type').value = '';
  document.getElementById('new_rate').value = '';
  document.getElementById('new_making').value = '';
  
  loadRates();
  alert(`✅ ${{metalType.toUpperCase()}} added: Rs.${{rate.toLocaleString('en-IN')}}/g | Making: ${{making}}%`);
}}

async function generateWorkflow() {{
  const desc = document.getElementById('workflowDescription').value.trim();
  if (!desc) {{
    alert('Please describe the workflow first');
    return;
  }}
  
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = '⏳ Generating...';
  
  try {{
    // Load roles first
    const rolesResp = await fetch(API('/roles'));
    const roles = await rolesResp.json();
    
    const roleCheckboxes = document.getElementById('roleCheckboxes');
    roleCheckboxes.innerHTML = roles.map(r => `
      <label style="display:flex;align-items:center;gap:6px;font-size:13px">
        <input type="checkbox" value="${{r.name}}" ${{r.selected ? 'checked' : ''}}>
        <span>${{r.name}}</span>
      </label>
    `).join('');
    
    const resp = await fetch(API('/workflow/generate'), {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{description: desc}})
    }});
    const config = await resp.json();
    
    // Store the full config for save
    window.generatedConfig = config;
    
    document.getElementById('wfName').value = config.name || '';
    document.getElementById('wfIntentKey').value = config.intent_key || '';
    document.getElementById('wfDescription').value = config.description || '';
    document.getElementById('wfOtpRequired').checked = config.otp_required || false;
    document.getElementById('wfOtpThreshold').value = config.otp_threshold || '';
    document.getElementById('wfApprovalThreshold').value = config.approval_threshold || '';
    
    document.getElementById('workflowForm').style.display = 'block';
  }} catch(e) {{
    alert('Failed to generate workflow: ' + e.message);
  }} finally {{
    btn.disabled = false;
    btn.textContent = '✨ Generate Config';
  }}
}}

async function saveWorkflow() {{
  const config = {{
    name: document.getElementById('wfName').value.trim(),
    intent_key: document.getElementById('wfIntentKey').value.trim(),
    description: document.getElementById('wfDescription').value.trim(),
    trigger_patterns: (window.generatedConfig && window.generatedConfig.trigger_patterns) || [],
    steps: (window.generatedConfig && window.generatedConfig.steps) || [],
    adapter_method: (window.generatedConfig && window.generatedConfig.adapter_method) || 'generic',
    otp_required: document.getElementById('wfOtpRequired').checked,
    otp_threshold: parseFloat(document.getElementById('wfOtpThreshold').value) || null,
    approval_threshold: parseFloat(document.getElementById('wfApprovalThreshold').value) || null,
    roles: Array.from(document.querySelectorAll('#roleCheckboxes input:checked')).map(cb => cb.value)
  }};
  
  if (!config.name || !config.intent_key || !config.description) {{
    alert('Please fill in name, intent key, and description');
    return;
  }}
  
  if (config.roles.length === 0) {{
    alert('Please select at least one role');
    return;
  }}
  
  try {{
    const resp = await fetch(API('/workflow/save'), {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(config)
    }});
    const result = await resp.json();
    
    if (result.success) {{
      alert('✅ ' + result.message);
      cancelWorkflow();
      loadData();
    }} else {{
      alert('Failed to save: ' + (result.message || 'Unknown error'));
    }}
  }} catch(e) {{
    alert('Failed to save workflow: ' + e.message);
  }}
}}

function cancelWorkflow() {{
  document.getElementById('workflowDescription').value = '';
  document.getElementById('workflowForm').style.display = 'none';
}}

async function loadData() {{
  try {{
    const resp = await fetch(API('/data'));
    const data = await resp.json();

    document.getElementById('orgName').textContent = data.org.name;

    try {{
      const sec = await fetch(API('/security')).then(r => r.json());
      const mins = sec.session_ttl_minutes || 480;
      if (mins >= 60 && mins % 60 === 0) {{
        document.getElementById('ttl_value').value = mins / 60;
        document.getElementById('ttl_unit').value = 'hours';
      }} else {{
        document.getElementById('ttl_value').value = mins;
        document.getElementById('ttl_unit').value = 'minutes';
      }}
    }} catch(e) {{}}

    loadRates();

    // Stats
    const s = data.stats;
    document.getElementById('statsGrid').innerHTML = `
      <div class="stat-card">
        <div class="stat-label">Total Invoices</div>
        <div class="stat-value">${{s.total_invoices || 0}}</div>
        <div class="stat-sub">Approved & issued</div>
      </div>
      <div class="stat-card" style="border-color:#dc2626">
        <div class="stat-value" style="color:#dc2626">Rs.${{Number(s.total_overdue||0).toLocaleString('en-IN')}}</div>
        <div class="stat-label">Total Overdue</div>
        <div class="stat-sub">Across all customers</div>
      </div>
      <div class="stat-card" style="border-color:#f59e0b">
        <div class="stat-value" style="color:#f59e0b">${{s.pending_approvals || 0}}</div>
        <div class="stat-label">Pending Approvals</div>
        <div class="stat-sub">Awaiting MD action</div>
      </div>
      <div class="stat-card" style="border-color:#ef4444">
        <div class="stat-value" style="color:#ef4444">${{data.low_stock.length}}</div>
        <div class="stat-label">Low Stock Items</div>
        <div class="stat-sub">Below reorder level</div>
      </div>
    `;

    // Workflows
    const wfHtml = data.workflows.map(w => `
      <tr>
        <td><strong>${{w.name}}</strong></td>
        <td><code style="font-size:11px;color:#888">${{w.intent_key}}</code></td>
        <td><span class="badge ${{w.is_active ? 'badge-active' : 'badge-inactive'}}">
          ${{w.is_active ? 'Active' : 'Inactive'}}</span></td>
        <td>
          <div class="toggle-wrap">
            <label class="toggle">
              <input type="checkbox" ${{w.otp_required ? 'checked' : ''}}
                onchange="toggleOtp('${{w.id}}', this.checked)">
              <span class="slider"></span>
            </label>
            <span style="font-size:12px;color:#888">${{w.otp_required ? 'ON' : 'OFF'}}</span>
          </div>
        </td>
        <td>
          <div style="display:flex;gap:6px;align-items:center">
            <input class="threshold-input" type="number" id="thr_${{w.id}}"
              value="${{w.otp_threshold || 50000}}" step="1000">
            <button class="save-btn" onclick="saveThreshold('${{w.id}}')">Save</button>
          </div>
        </td>
        <td>
          ${{w.intent_key === 'create_invoice' ? `
          <div style="display:flex;gap:6px;align-items:center">
            <input class="threshold-input" type="number" id="apr_${{w.id}}"
              value="${{w.approval_threshold || 100000}}" step="1000">
            <button class="save-btn" onclick="saveApprovalThreshold('${{w.id}}')">Save</button>
          </div>` : '—'}}
        </td>
        <td style="color:#888;font-size:12px">
          ${{w.last_run ? new Date(w.last_run).toLocaleDateString('en-IN') : '—'}}</td>
      </tr>
    `).join('');
    document.getElementById('workflowsTable').innerHTML = wfHtml;

    // Low stock
    const lsHtml = data.low_stock.length
      ? data.low_stock.map(r => `
          <tr>
            <td class="low-stock-item">${{r.name}}</td>
            <td>${{r.qty}}</td>
            <td style="color:#888">${{r.reorder_level}}</td>
          </tr>`).join('')
      : '<tr><td colspan="3" style="color:#888;padding:12px 0">✅ All stock levels normal</td></tr>';
    document.getElementById('lowStockTable').innerHTML = lsHtml;

    // Activity
    const actHtml = data.recent_logs.map(r => `
      <tr>
        <td style="font-size:12px">${{r.user_name || '—'}}</td>
        <td style="font-size:11px;color:#555">${{r.intent_key}}</td>
        <td>${{r.otp_used ? '🔐' : '—'}}</td>
        <td><span class="badge ${{
          r.outcome === 'success' ? 'badge-success' :
          r.outcome === 'pending_approval' ? 'badge-pending' : 'badge-failed'
        }}">${{r.outcome}}</span></td>
      </tr>`).join('');
    document.getElementById('activityTable').innerHTML = actHtml;

    document.getElementById('loading').style.display = 'none';
    document.getElementById('content').style.display = 'block';
  }} catch(e) {{
    document.getElementById('loading').textContent = 'Error loading data: ' + e.message;
  }}
}}

async function toggleOtp(id, enabled) {{
  await fetch(API(`/workflow/${{id}}/toggle`), {{method:'POST'}});
  const label = event.target.closest('.toggle-wrap').querySelector('span');
  if(label) label.textContent = enabled ? 'ON' : 'OFF';
}}

async function saveThreshold(id) {{
  const val = document.getElementById('thr_' + id).value;
  await fetch(API(`/workflow/${{id}}/threshold`), {{
    method:'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{threshold: parseFloat(val)}})
  }});
  alert('Threshold updated to Rs.' + Number(val).toLocaleString('en-IN'));
}}

async function saveApprovalThreshold(id) {{
  const val = document.getElementById('apr_' + id).value;
  await fetch(API(`/workflow/${{id}}/approval_threshold`), {{
    method:'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{threshold: parseFloat(val)}})
  }});
  alert('Approval threshold updated to Rs.' + Number(val).toLocaleString('en-IN'));
}}

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""
