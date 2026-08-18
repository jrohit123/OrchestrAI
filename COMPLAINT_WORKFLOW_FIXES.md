# Complaint Workflow Multi-Turn Flow Fixes

## Issues Identified

### 1. "register_complaint" treated as correction instead of new intent
**Problem:** When user types "register_complaint" while a draft is active, it's treated as a correction hint instead of starting a new draft.

**Root Cause:** In `webhook.py` lines 497-537, any unrecognised reply while `stage == "awaiting_confirmation"` is treated as a correction. No check for explicit intent restart keywords.

**Fix:** Add intent restart detection before treating as correction.

### 2. "yes I confirm" execution failure
**Problem:** Confirmation fails with generic error message.

**Root Cause:** The workflow steps are failing silently in `step_interpreter.py`. The `db.insert_row` step may be failing due to missing required fields or validation errors.

**Fix:** Add better error logging and validation in step execution.

### 3. Default value auto-filling (priority auto-set to "medium")
**Problem:** LLM invents default values instead of asking user.

**Root Cause:** In `agent.py` line 1719, the draft context says "Only ask for fields NOT listed above" but doesn't explicitly forbid inventing defaults. The workflow's `llm_system_prompt` says "default medium" which the LLM interprets as permission to auto-fill.

**Fix:** Update workflow prompt to explicitly forbid auto-filling defaults.

### 4. Correction handling for field updates
**Problem:** User can't say "change this to low" to update a field.

**Root Cause:** The correction hint logic in `webhook.py` just passes the raw text to the agent. The agent needs to parse "change X to Y" patterns and call `update_draft` with the specific field.

**Fix:** Add correction pattern detection in agent's draft handling.

---

## Exact Code Changes

### Fix 1: Add intent restart detection in webhook.py

**File:** `app/routers/webhook.py`

**Location:** Lines 497-537 (awaiting_confirmation handling)

**Change:**
```python
# Add this list after _CANCEL_WORDS (around line 38)
_RESTART_WORDS = frozenset({
    "restart", "start over", "new", "fresh", "cancel", "stop",
    "register_complaint", "complaint", "case", "file", "register"
})

# Replace the existing else block (lines 514-536) with:
else:
    # Check if user wants to restart with a new intent
    text_lower_for_restart = text.strip().lower()
    if any(word in text_lower_for_restart for word in _RESTART_WORDS):
        # Clear existing draft and start fresh
        logger.info(f"Intent restart detected — clearing draft")
        session.pop("pending_action", None)
        await set_session(session_id, session, ttl=session_ttl)
        await send_text(phone,
            "_⏱️ Previous draft cleared. Starting fresh..._"
        )
        # fall through to agent with pending_action=None
        pending_action = None
    else:
        # Still fresh — treat as a correction to the existing draft.
        # Downgrade stage so the agent re-enters collection mode.
        # NOTE: reprompt_count is incremented once, later, by the
        # collecting-stage check further down — do NOT increment it
        # here too, or corrections get double-counted and hit the
        # cap in half the intended number of turns.
        current_reprompt_count = pending_action.get("reprompt_count", 0)
        if current_reprompt_count >= _MAX_REPROMPT_COUNT:
            # Cap hit — the user and the bot are going in circles. Force a clean restart.
            logger.warning(f"Reprompt cap ({_MAX_REPROMPT_COUNT}) reached — clearing draft")
            session.pop("pending_action", None)
            await set_session(session_id, session, ttl=session_ttl)
            await send_text(phone,
                "🤔 I'm having trouble understanding the details for this request. "
                "Let's start fresh — please send your request again with all the details "
                "in one message, e.g. *\"invoice Mehta Enterprises Rs.92,000\"*."
            )
            return
        pending_action["stage"] = "collecting"
        pending_action["correction_hint"] = text
        session["pending_action"] = pending_action
        await set_session(session_id, session, ttl=session_ttl)
        # fall through to agent — step 10 below will increment reprompt_count once
```

### Fix 2: Update workflow prompt to forbid auto-filling defaults

**File:** `migrations/002_insert_godrej_workflows.sql` (line 62)

**Change:**
```sql
-- Replace the existing llm_system_prompt with:
'Registers a new case in the cases table for this housing society. Required: title (short summary), optional: description, location, priority (urgent/high/medium/low). NEVER auto-fill or invent default values for optional fields — if the user does not provide a value, explicitly ask them for it. Example: "register a complaint about garbage not collected in Wing 3" -> title="Garbage not collected", location="Wing 3". This workflow is NOT for checking status of an existing case (that is a read query) and NOT for adding a comment to an existing case. CRITICAL: When calling confirm_action, the "details" object must ONLY contain user-facing fields the user actually provided or should review: title, description, location, priority. NEVER include complainant_id, status, org_id, or any other system-set/internal field in details — those are set automatically and must never be shown to the user.'
```

**Also update:** `migrations/003_fix_register_complaint_prompt.sql` with the same change.

### Fix 3: Add correction pattern detection in agent.py

**File:** `app/services/agent.py`

**Location:** Lines 1704-1721 (_format_pending_action_context function)

**Change:**
```python
# Replace the entire _format_pending_action_context function with:
def _format_pending_action_context(pending_action: dict | None) -> str:
    if not pending_action:
        return ""
    fields = pending_action.get("fields") or {}
    correction = pending_action.get("correction_hint", "")
    
    # Detect correction patterns like "change priority to low", "make it urgent", etc.
    correction_instruction = ""
    if correction:
        correction_lower = correction.lower()
        # Pattern: "change X to Y" or "make it Y" or "set X to Y"
        if re.search(r'(change|make|set)\s+\w+\s+(to|as)\s+\w+', correction_lower):
            correction_instruction = (
                f"\nUser just said: \"{correction}\" — this is a FIELD UPDATE. "
                "Parse the pattern to identify which field to update and the new value. "
                "Call update_draft with ONLY the changed field. Keep all other fields intact.\n"
            )
        else:
            correction_instruction = (
                f"\nUser just said: \"{correction}\" — treat this as a correction to the draft above. "
                "Update only the relevant field(s), keep everything else.\n"
            )
    
    return (
        "\n=== ACTIVE DRAFT (from this conversation — do NOT discard or replace unless user changes it) ===\n"
        f"Intent: {pending_action.get('intent_key')}\n"
        f"Stage: {pending_action.get('stage', 'collecting')}\n"
        f"Collected fields: {json.dumps(fields, default=str)}\n"
        f"{correction_instruction}"
        "Only ask for fields NOT listed above. NEVER invent default values for missing optional fields — "
        "explicitly ask the user if they don't provide a value.\n"
        "=== END ACTIVE DRAFT ===\n"
    )
```

### Fix 4: Add better error logging in step_interpreter.py

**File:** `app/services/step_interpreter.py`

**Location:** Lines 306-386 (_op_insert_row function)

**Change:**
```python
# After line 384 (row = await fetch_one...), add error handling:
try:
    row = await fetch_one(sql, *sql_values, source_key=ctx["source_key"])
    if not row:
        raise StepError(f"db.insert_row failed: INSERT returned no rows for table '{table}'")
    ctx.setdefault("inserted", {})[table] = dict(row)
    return ctx
except Exception as e:
    logger.error(f"db.insert_row failed for table '{table}': {e}", exc_info=True)
    logger.error(f"SQL: {sql}")
    logger.error(f"Values: {sql_values}")
    raise StepError(f"Failed to insert into {table}: {str(e)}")
```

### Fix 5: Update draft context in agent.py to forbid default invention

**File:** `app/services/agent.py`

**Location:** Lines 1784-1799 (draft message injection)

**Change:**
```python
# Replace the draft_msg block with:
draft_msg = (
    f"[ACTIVE DRAFT — intent: {pending_action.get('intent_key')}, stage: {stage}]\n"
    f"Already collected: {json.dumps(fields, default=str)}\n"
    f"{correction_line}"
    "Only ask for fields NOT listed above. NEVER invent default values for missing optional fields — "
    "explicitly ask the user if they don't provide a value. Never re-ask for already-collected data."
)
```

---

## Additional SQL Migration

Create a new migration file to apply the workflow prompt fix:

**File:** `migrations/004_fix_complaint_prompt_defaults.sql`

```sql
-- Fix register_complaint workflow to prevent auto-filling default values
-- This ensures the LLM asks for optional fields instead of inventing them

UPDATE workflows
SET llm_system_prompt = 'Registers a new case in the cases table for this housing society. Required: title (short summary), optional: description, location, priority (urgent/high/medium/low). NEVER auto-fill or invent default values for optional fields — if the user does not provide a value, explicitly ask them for it. Example: "register a complaint about garbage not collected in Wing 3" -> title="Garbage not collected", location="Wing 3". This workflow is NOT for checking status of an existing case (that is a read query) and NOT for adding a comment to an existing case. CRITICAL: When calling confirm_action, the "details" object must ONLY contain user-facing fields the user actually provided or should review: title, description, location, priority. NEVER include complainant_id, status, org_id, or any other system-set/internal field in details — those are set automatically and must never be shown to the user.'
WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604'
  AND intent_key = 'register_complaint';
```

---

## Testing Steps

After applying all fixes:

1. **Test intent restart:**
   ```
   /complaint
   water leakage
   register_complaint
   ```
   Should clear previous draft and start fresh.

2. **Test no auto-filling:**
   ```
   /complaint
   water leakage
   ```
   Should ask for location/priority explicitly, not auto-fill "medium".

3. **Test correction:**
   ```
   /complaint
   water leakage
   Wing 2 basement
   change priority to high
   ```
   Should update priority field and re-show confirmation.

4. **Test confirmation:**
   ```
   /complaint
   water leakage
   Wing 2 basement
   high
   yes I confirm
   ```
   Should successfully register the complaint.

---

## Summary of Changes

1. **webhook.py**: Added `_RESTART_WORDS` detection to clear draft on explicit intent restart
2. **agent.py**: Updated draft context to forbid default value invention
3. **agent.py**: Added correction pattern detection for "change X to Y" patterns
4. **step_interpreter.py**: Added better error logging for insert failures
5. **002_insert_godrej_workflows.sql**: Updated workflow prompt to forbid auto-filling
6. **003_fix_register_complaint_prompt.sql**: Updated with same prompt fix
7. **004_fix_complaint_prompt_defaults.sql**: New migration for production
