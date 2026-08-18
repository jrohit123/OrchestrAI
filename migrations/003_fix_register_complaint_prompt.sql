-- Fix register_complaint workflow to prevent internal fields from leaking into confirm_action details
-- This prevents complainant_id (UUID) and status (system-set) from showing to users

UPDATE workflows
SET llm_system_prompt = 'Registers a new case in the cases table for this housing society. Required: title (short summary), optional: description, location, priority (urgent/high/medium/low, default medium). Example: "register a complaint about garbage not collected in Wing 3" -> title="Garbage not collected", location="Wing 3". This workflow is NOT for checking status of an existing case (that is a read query) and NOT for adding a comment to an existing case. CRITICAL: When calling confirm_action, the "details" object must ONLY contain user-facing fields the user actually provided or should review: title, description, location, priority. NEVER include complainant_id, status, org_id, or any other system-set/internal field in details — those are set automatically and must never be shown to the user.'
WHERE org_id = '793eead0-31b2-4538-b9b3-1885f9e94604'
  AND intent_key = 'register_complaint';
