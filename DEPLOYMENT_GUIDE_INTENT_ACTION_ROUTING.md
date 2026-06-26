# Intent+Action Routing - Deployment Guide

## Overview
This guide covers the complete implementation of Intent+Action routing system, replacing the brittle regex-based classification with LLM-powered intent analysis.

## Architecture Changes

### Before (Regex-Based)
- DB-stored `trigger_patterns` (regex)
- Classifier loads patterns from DB
- Fuzzy matching with similarity thresholds
- No ad-hoc query support

### After (Intent+Action Routing)
- LLM analyzes intent + action directly
- Two paths: `general_read` (ad-hoc queries) and `workflow` (mutations)
- No regex patterns needed
- Multi-language support via LLM

---

## Code Changes Summary

### 1. New Files Created

#### `app/services/intent_analyzer.py`
- **Purpose**: LLM-based intent+action classification
- **Key Function**: `analyze_intent(text, org_id, user_role)`
- **Output**: 
  ```json
  {
    "route_type": "general_read|workflow|clarify|unknown",
    "action": "Read|Create|Update|Delete|Execute",
    "intent": "description",
    "workflow_key": "function_name",
    "parameters": {"customer_name": "...", "product_name": "..."},
    "clarification_question": "..."
  }
  ```
- **LLM Prompt**: Tiered classification with workflow context

#### `app/services/query_engine.py`
- **Purpose**: Safe ad-hoc DB queries for `general_read` path
- **Key Function**: `execute_read(org_id, intent, parameters)`
- **Features**:
  - Allowlisted SQL templates (no injection risk)
  - LLM picks template + fills parameters
  - WhatsApp-formatted output
- **Templates**: Top N customers, overdue invoices, low stock, etc.

### 2. Modified Files

#### `app/classifier/classifier.py`
- **Removed**: DB pattern loading, embedding logic
- **Kept**: System intents (greet, menu, retry_otp, manage_schedule, clear_sessions)
- **New Flow**:
  1. Tier 1: Exact matches (hi, help, menu)
  2. Tier 2: System intents regex only
  3. Tier 3: Intent Analyzer (LLM)
- **Returns**: Full analysis dict with `route_type`, `action`, `parameters`

#### `app/services/identity.py`
- **Added**: `check_route_permission(user, analysis)` function
- **New Constants**: `ROLE_READ_ACCESS`, `WORKFLOW_ACTIONS`
- **Permission Logic**:
  - `general_read`: Check permission or fallback to owner
  - `workflow`: Check workflow_key in permissions
  - `clarify`: Always allowed
  - `system`: Use existing `check_permission`

#### `app/routers/webhook.py`
- **Import**: Added `check_route_permission`
- **Routing Changes**:
  - Pass `user_role` to classifier
  - Use `check_route_permission` instead of `check_permission`
  - Handle `route_type` branches:
    - `clarify`: Ask question
    - `general_read`: Call `execute_read`
    - `workflow`: Call `execute_intent` with `parameters`
- **Session**: Store `last_parameters` for context

#### `app/executor/workflow_executor.py`
- **Modified**: `_dispatch_dynamic_intent()` accepts `parameters` dict
- **Modified**: `execute_intent()` accepts `parameters` kwarg
- **Modified**: `manage_schedule` auto-creates `weekly_dues_report` workflow if missing
- **Context**: LLM-extracted parameters merged into adapter context

#### `app/routers/admin.py`
- **Modified**: `generate_workflow_config()` prompt
  - Removed `trigger_patterns` from output
  - Added `steps` array
  - Updated instructions for Intent+Action routing
- **Modified**: `save_generated_workflow()`
  - Always saves empty `trigger_patterns`
  - Saves `steps` array
  - Removed cache invalidation (not needed)
- **Modified**: JavaScript `saveWorkflow()`
  - Always sends empty `trigger_patterns`
  - Sends `steps` array

#### `app/scheduler/jobs.py`
- **Modified**: `send_weekly_dues_report()`
  - No longer depends on `workflows.scheduled_by`
  - Queries orgs directly with owner phone
  - Checks for `is_scheduled` flag in workflows table

---

## Database Changes

### 1. Add `general_read` Permission to Roles

Run this SQL in Neon:

```sql
-- Add general_read to all roles
UPDATE roles 
SET permissions = array_append(permissions, 'general_read')
WHERE org_id = '11111111-0000-0000-0000-000000000001'
  AND NOT 'general_read' = ANY(permissions);
```

**Verification**:
```sql
SELECT name, permissions FROM roles 
WHERE org_id = '11111111-0000-0000-0000-000000000001';
```

Expected output includes `general_read` in all role permissions arrays.

### 2. Delete Existing Workflows (One-Time Cleanup)

```sql
DELETE FROM workflows
WHERE org_id = '11111111-0000-0000-0000-000000000001';
```

**Why**: Old workflows have `trigger_patterns` which are no longer used. New workflows will be created via admin panel with empty patterns.

---

## Admin Panel Usage

### Creating New Workflows

1. Go to Admin Panel → Workflow Configuration
2. Click "Add Workflow"
3. Enter description (e.g., "Check credit limit for a customer")
4. Click "✨ Generate Config"
5. Review auto-generated fields:
   - `name`: 2-4 word name
   - `intent_key`: Function name (must match adapter)
   - `description`: Rich description with examples
   - `adapter_method`: Module.function format
   - `steps`: Array of step descriptions
6. Configure thresholds (optional):
   - OTP Required: Yes/No
   - OTP Threshold: Amount in Rs.
   - Approval Threshold: Amount in Rs.
7. Select roles that can use this workflow
8. Click "💾 Save Workflow"

**Note**: `trigger_patterns` will always be empty (Intent+Action routing uses LLM).

### Example Workflows to Create

#### 1. Check Stock
```
Description: Check stock level of a specific product
Generated Config:
- name: Check Product Stock
- intent_key: check_stock
- adapter_method: inventory.check_stock
- steps: ["Search product by name", "Return quantity and location"]
```

#### 2. Create Invoice
```
Description: Create sales invoice for customer
Generated Config:
- name: Create Sales Invoice
- intent_key: create_invoice
- adapter_method: accounting.create_invoice
- steps: ["Validate customer", "Calculate amount", "Create invoice record"]
```

#### 3. Check Outstanding
```
Description: Check outstanding dues for customer
Generated Config:
- name: Check Outstanding Dues
- intent_key: get_outstanding
- adapter_method: crm.get_outstanding
- steps: ["Find customer", "Sum unpaid invoices", "Return total"]
```

#### 4. Send Invoice PDF
```
Description: Send PDF of existing invoice to customer
Generated Config:
- name: Send Invoice PDF
- intent_key: send_invoice_pdf
- adapter_method: accounting.send_invoice_pdf
- steps: ["Find invoice", "Generate PDF", "Send via WhatsApp"]
```

#### 5. Create Order
```
Description: Create production order for manufacturing
Generated Config:
- name: Create Production Order
- intent_key: create_order
- adapter_method: orders.create_order
- steps: ["Validate customer", "Create order record", "Set status to confirmed"]
```

---

## Test Queries (Based on Existing Data)

### General Read Queries (Ad-hoc)

**Top 3 customers by credit limit**:
```
"show me top 3 customers by credit limit"
"who are my highest credit limit customers"
"top 3 customers with most credit"
```

**Overdue invoices summary**:
```
"show overdue invoices"
"list all overdue payments"
"which invoices are past due"
```

**Low stock items**:
```
"show low stock items"
"which products need reorder"
"items below reorder level"
```

**Recent invoices**:
```
"show recent invoices"
"last 5 invoices"
"recent sales"
```

### Workflow Queries (Mutations)

**Check Stock**:
```
"stock gold ring"
"how many diamond bangles"
"inventory silver chain"
"what is the stock of platinum necklace"
```

**Check Outstanding**:
```
"dues Mehta Jewellers"
"outstanding for Patel Fine Jewellery"
"how much does Sharma Gold House owe"
"balance for Agarwal Ornaments"
```

**Create Invoice** (requires customer + amount + item):
```
"invoice Mehta Jewellers 45000 22kt Gold Ring"
"create invoice for Patel 125000 18kt Diamond Bangle"
"bill Sharma 62000 22kt Gold Chain"
```

**Send Invoice PDF**:
```
"send PDF for invoice INV-001"
"invoice PDF for customer Mehta"
"send me the invoice as a PDF"
```

**Create Order**:
```
"create order for Mehta Jewellers gold necklace"
"new order for Patel diamond pendant"
"I want to order silver anklet for Kapoor"
```

**Update Order Status**:
```
"update order ORD-001 to shipped"
"mark order ORD-002 as delivered"
"change status of order ORD-003 to in progress"
```

### System Commands

**Schedule Dues Report**:
```
"schedule dues report every Monday 9 AM"
"send report every Tuesday 2 PM"
"schedule report daily at 5 PM"
```

**Check Schedule**:
```
"when is the dues report scheduled"
"what time does the report run"
"schedule status"
```

**Stop Schedule**:
```
"stop dues report"
"cancel scheduled report"
"pause report"
```

**Clear Sessions**:
```
"clear all sessions"
"emergency lockdown"
"force everyone to re-auth"
```

---

## Testing Procedure

### 1. Test General Read Path

Use these WhatsApp messages (as any role with `general_read` permission):

```
"show top 3 customers by credit limit"
"list overdue invoices"
"show low stock items"
```

**Expected**: Formatted WhatsApp response with data from DB.

### 2. Test Workflow Path

Use these messages (as role with workflow permission):

```
"stock gold ring"
"dues Mehta Jewellers"
"send PDF for invoice INV-001"
```

**Expected**: Adapter function called with LLM-extracted parameters.

### 3. Test Clarification Path

Use ambiguous query:

```
"show me data"
```

**Expected**: Bot asks for clarification.

### 4. Test Unknown Path

Use nonsense query:

```
"xyz abc def"
```

**Expected**: "Didn't understand that" message.

### 5. Test Scheduler

1. Send: `schedule dues report every Monday 9 AM`
2. Verify workflow auto-created in DB
3. Check scheduler status: `when is the dues report scheduled`
4. Stop: `stop dues report`

---

## Deployment Checklist

- [x] Created `app/services/intent_analyzer.py`
- [x] Created `app/services/query_engine.py`
- [x] Updated `app/classifier/classifier.py`
- [x] Updated `app/services/identity.py`
- [x] Updated `app/routers/webhook.py`
- [x] Updated `app/executor/workflow_executor.py`
- [x] Updated `app/routers/admin.py`
- [x] Updated `app/scheduler/jobs.py`
- [ ] Run SQL to add `general_read` permission
- [ ] Run SQL to delete existing workflows
- [ ] Test general read queries
- [ ] Test workflow queries
- [ ] Test scheduler commands
- [ ] Push changes to Railway
- [ ] Verify production deployment

---

## Troubleshooting

### Issue: "You don't have permission for general_read"
**Fix**: Run the SQL to add `general_read` to role permissions.

### Issue: "Didn't understand that" for valid queries
**Fix**: Check `OPENAI_API_KEY` is set. Verify Intent Analyzer is being called.

### Issue: Scheduler not running
**Fix**: Check `weekly_dues_report` workflow exists in DB. Send `schedule dues report every Monday 9 AM` to auto-create.

### Issue: Admin panel shows old trigger_patterns
**Fix**: Delete old workflows from DB. Create new ones via admin panel.

---

## Rollback Plan

If issues arise, revert to previous commit and restore workflows from backup:

```sql
-- Restore from backup (you should have exported before delete)
-- Or manually re-create workflows with trigger_patterns
```

---

## Notes

- **No pgvector needed**: Intent+Action routing uses LLM directly, no embeddings.
- **No schema migration**: Only workflows table cleanup and role permission update.
- **Multi-language**: LLM handles English, Hindi, Hinglish automatically.
- **Performance**: LLM call adds ~500ms latency, acceptable for WhatsApp use case.
