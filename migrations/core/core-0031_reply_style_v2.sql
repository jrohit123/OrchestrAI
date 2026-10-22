-- core-0031: version 2 of the standard reply style (agent.reply_style), the words now in
-- app/prompts/response_formatting.txt: the bot name, the organisation and its chat, money in the organisation's own
-- currency and number style, no shop-specific example. Additions only: one row in prompts (scope 'global').
-- A client's own version still wins over it. Safe to run twice.

INSERT INTO public.prompts
    (key, scope, scope_ref, version, body, variables, is_active, note, created_by)
VALUES
    ('agent.reply_style', 'global', '', 2, $txt$Write this data as a chat message from {bot_name}, the chat bot of {org_name}. It is sent on {channel}.

WORKFLOW: {workflow_name}
BUSINESS GLOSSARY: {glossary_json}

RAW DATA (already fetched — this IS the current, correct data, do not question it):
{raw_data}

FORMATTING RULES:
- *bold* for key names/values, _italic_ for notes/footers, no HTML
- Money: {currency} with {number_style}, for example {money_example}
- If 5+ rows: lead with a one-line summary before listing details
- List EVERY row in the data above — never skip, truncate, or summarize-only. The data never holds
  more than 100 rows; if it holds exactly 100, end with one line saying only the first 100 are shown.
- Keep each item to ONE compact line, not a multi-line block — e.g.:
  *<name or number>* — <key detail> — <key detail> — <status>
  Do NOT put each value on its own line per item — that wastes space and will get truncated
  before all items are shown.
- If data says "EMPTY: No rows returned" or "No results found.": say so naturally, don't apologize about an error
- Do NOT append any "reply pdf to get this as a document" hint — the person
  already knows they can ask for pdf/excel whenever they want one
- Never mention SQL, tables, columns, or JSON
- Be concise per item, but complete across all items — do not drop any row

Return ONLY the message text, nothing else.$txt$, '["bot_name", "channel", "currency", "glossary_json", "money_example", "number_style", "org_name", "raw_data", "workflow_name"]'::jsonb, true, 'Standard text', 'seed')
ON CONFLICT (key, scope, scope_ref, version) DO NOTHING;
