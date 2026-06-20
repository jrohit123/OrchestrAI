import os
import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from app.db import fetch_all, fetch_one, execute

router = APIRouter()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "orchestrai_admin_2024")


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
               otp_threshold, last_run
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

async function loadData() {{
  try {{
    const resp = await fetch(API('/data'));
    const data = await resp.json();

    document.getElementById('orgName').textContent = data.org.name;

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

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""
