"""
pdf_engine.py — LLM-powered PDF generator using WeasyPrint.

When a workflow has pdf_config.render_instructions, those instructions drive the layout.
When not, the default per-doc_type templates in the ===ALL_DOCTYPES=== section of
app/prompts/pdf_generation_instructions.txt are used instead.
This way existing behaviour is preserved and new DB-configured workflows get custom layouts.
"""
import asyncio
import json
from io import BytesIO
from datetime import datetime
from openai import AsyncOpenAI

from app.config import required
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

from app.services.llm_router import chat_completion as _llm_chat
from app.services.prompt_loader import PROMPTS_DIR


def _load_doctype_templates(raw: str) -> dict:
    """
    Parses the ===ALL_DOCTYPES=== section of pdf_generation_instructions.txt
    into {doctype_name: template_text}. Each section is introduced by a
    "===DOCTYPE:<name>===" marker; the text up to the next marker (or EOF)
    is that doctype's template, verbatim (including its own leading/trailing
    whitespace) — deliberately NOT using prompt_loader._read()'s whole-file
    .strip(), which would corrupt the last section's trailing newline.
    """
    templates: dict[str, str] = {}
    for part in raw.split("===DOCTYPE:")[1:]:
        name, _, body = part.partition("===")
        templates[name.strip()] = body
    return templates


_RAW_PDF_PROMPT = (PROMPTS_DIR / "pdf_generation_instructions.txt").read_text(encoding="utf-8")
_GENERATION_PROMPT, _, _DOCTYPE_RAW = _RAW_PDF_PROMPT.partition("\n===ALL_DOCTYPES===\n")
_DOCTYPE_TEMPLATES = _load_doctype_templates(_DOCTYPE_RAW)

_client = AsyncOpenAI(api_key=required("OPENAI_API_KEY"))

BRAND_BLUE   = "#185FA5"
BRAND_LIGHT  = "#EEF4FB"
BRAND_DARK   = "#1A1A2E"
BRAND_MUTED  = "#6B7280"

RISK_COLORS = {
    "HIGH":     {"bg": "#B71C1C", "row": "#FFEBEE", "text": "#FFFFFF"},
    "MEDIUM":   {"bg": "#E65100", "row": "#FFF3E0", "text": "#FFFFFF"},
    "LOW":      {"bg": "#2E7D32", "row": "#F1F8E9", "text": "#FFFFFF"},
    "UPCOMING": {"bg": "#1565C0", "row": "#E3F2FD", "text": "#FFFFFF"},
}


async def generate_pdf(
    rows: list,
    title: str,
    org_name: str,
    subtitle: str = "",
    doc_type: str = "report",
    extra_context: dict = None,
    pdf_config: dict = None,
) -> bytes:
    """Generate a professional A4 PDF. Returns bytes. Raises on error."""
    html = await _build_html(
        rows=rows,
        title=title,
        org_name=org_name,
        subtitle=subtitle,
        doc_type=doc_type,
        extra_context=extra_context or {},
        pdf_config=pdf_config or {},
    )
    logger.info(f"Final HTML for PDF: {len(html)} chars, title={title}")
    # WeasyPrint's HTML→PDF render is synchronous and CPU-bound — running it
    # directly here blocks the event loop for every other in-flight
    # WhatsApp/Telegram request for however long a multi-row invoice takes to
    # lay out. Push it to a thread so the loop stays free.
    return await asyncio.to_thread(_html_to_pdf, html)


def _fill(template: str, primary: str, light_bg: str, today_long: str) -> str:
    return (
        template
        .replace("{primary}", primary)
        .replace("{light_bg}", light_bg)
        .replace("{today_long}", today_long)
    )


def _build_doctype_instructions(doc_type: str, risk_mode: bool,
                                 extra_context: dict, today_long: str,
                                 org_name: str, primary: str, light_bg: str) -> str:
    """Build the doc-type specific section of the PDF prompt (default/fallback path).
    Templates live in the ===ALL_DOCTYPES=== section of
    app/prompts/pdf_generation_instructions.txt."""

    if risk_mode:
        return _fill(_DOCTYPE_TEMPLATES["risk_mode"], primary, light_bg, today_long)

    template = _DOCTYPE_TEMPLATES.get(doc_type, _DOCTYPE_TEMPLATES["generic"])
    return _fill(template, primary, light_bg, today_long)


async def _build_html(rows, title, org_name, subtitle, doc_type,
                       extra_context, pdf_config=None) -> str:
    today      = datetime.now().strftime("%d %b %Y")
    today_long = datetime.now().strftime("%d %B %Y")

    pdf_config = pdf_config or {}
    render_instructions = pdf_config.get("render_instructions")
    theme     = pdf_config.get("theme") or {}
    primary   = theme.get("primary",  BRAND_BLUE)
    light_bg  = theme.get("light_bg", BRAND_LIGHT)
    text_col  = theme.get("text",     BRAND_DARK)
    muted_col = theme.get("muted",    BRAND_MUTED)

    data_for_prompt = rows[:100]
    trunc_note = f"\n(Note: showing first 100 of {len(rows)} rows)" if len(rows) > 100 else ""
    data_json  = json.dumps(data_for_prompt, default=str, indent=2)
    ctx_json   = json.dumps(extra_context,   default=str, indent=2)

    # Calculate column count for landscape/auto-layout
    col_count = len(data_for_prompt[0].keys()) if data_for_prompt else 0
    page_orientation = "A4 landscape" if col_count > 6 else "A4"
    wide_table_note = ""
    if col_count > 6:
        wide_table_note = (
            f"\n⚠️ WIDE TABLE ({col_count} columns): This page is already set to LANDSCAPE "
            f"orientation to fit. Still use table-layout: fixed with explicit column widths "
            f"(%) summing to 100%. Abbreviate long headers. Use 9pt font on table cells if needed."
        )

    has_risk_buckets = any("risk_bucket" in r for r in data_for_prompt)
    has_days_overdue = any("days_overdue" in r for r in data_for_prompt)
    risk_mode = (has_risk_buckets or has_days_overdue) and doc_type not in ("invoice", "quotation")

    # Choose layout instructions: DB-configured (new path) vs hardcoded defaults (legacy path)
    if render_instructions:
        layout_section = f"""===== WORKFLOW-CONFIGURED LAYOUT =====
(These instructions override the defaults — follow them exactly.)
{render_instructions}
"""
    else:
        layout_section = f"""===== DOC-TYPE SPECIFIC INSTRUCTIONS =====
{_build_doctype_instructions(doc_type, risk_mode, extra_context, today_long, org_name, primary, light_bg)}
"""

    # Build canonical totals block — explicit values to prevent the LLM from
    # guessing or recalculating amounts that are already correct
    canonical_keys  = ("subtotal", "gst_amount", "total_amount", "grand_total", "amount",
                       "metal_cost", "making_charges")
    canonical_lines = [
        f"  {k} = {extra_context[k]}"
        for k in canonical_keys
        if extra_context.get(k) is not None
    ]
    if canonical_lines:
        canonical_block = (
            "===== CANONICAL TOTALS — use these EXACT values verbatim, never recalculate =====\n"
            + "\n".join(canonical_lines)
            + "\n===== END CANONICAL TOTALS ====="
        )
    else:
        canonical_block = (
            "===== NOTE: no pre-computed total fields supplied. "
            "Derive totals ONLY by summing the per-row values in DATA above — "
            "do not assume a tax rate or invent a formula. ====="
        )

    prompt = _GENERATION_PROMPT.format(
        org_name=org_name,
        doc_type=doc_type,
        title=title,
        subtitle=subtitle or "(none)",
        today_long=today_long,
        total_rows=len(rows),
        trunc_note=trunc_note,
        data_json=data_json,
        ctx_json=ctx_json,
        canonical_block=canonical_block,
        text_col=text_col,
        page_orientation=page_orientation,
        primary=primary,
        light_bg=light_bg,
        muted_col=muted_col,
        today=today,
        layout_section=layout_section,
        wide_table_note=wide_table_note,
    )

    # Route through central LLM router (Gemini x3 → Groq → Cerebras → OpenAI)
    response = await _llm_chat(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=8192,
        temperature=0.1,
    )

    if not response:
        raise Exception("No response from any LLM provider for PDF generation")

    html = response.choices[0].message.content.strip()
    if html.startswith("```"):
        lines = html.split("\n")
        start = 1 if lines[0].startswith("```") else 0
        end   = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        html  = "\n".join(lines[start:end]).strip()

    # ── Safety net: force wrapping/fixed layout regardless of what the LLM wrote ──
    forced_css = """
<style>
  * { box-sizing: border-box; }
  body { max-width: 100%; overflow-x: hidden; }
  table { width: 100% !important; table-layout: fixed !important; border-collapse: collapse; }
  th, td { word-break: break-word !important; overflow-wrap: break-word !important;
           white-space: normal !important; padding: 5px 6px; }
</style>
"""
    if "</head>" in html:
        html = html.replace("</head>", forced_css + "</head>", 1)
    else:
        html = forced_css + html

    # ── Debug logging so blank/cut-off PDFs are diagnosable, not guessed at ──
    logger.info(f"Generated HTML: {len(html)} chars, doc_type={doc_type}, columns={col_count}")
    if len(html) < 800:
        logger.warning(f"Suspiciously short HTML for '{title}'. Preview: {html[:500]}")
    import re as _re
    big_px = [int(p) for p in _re.findall(r'width:\s*(\d{3,5})px', html) if int(p) > 750]
    if big_px:
        logger.warning(f"HTML contains oversized fixed-px widths {big_px} — likely overflow cause for '{title}'")

    return html


def _html_to_pdf(html: str) -> bytes:
    """WeasyPrint: HTML string → PDF bytes. Raises ValueError on failure."""
    from weasyprint import HTML

    def custom_url_fetcher(url):
        """Block all external URLs — fonts are inlined, no external fetching needed."""
        raise ValueError(f"Blocked external URL: {url}")

    try:
        buf = BytesIO()
        HTML(string=html, base_url=None, url_fetcher=custom_url_fetcher).write_pdf(buf)
        return buf.getvalue()
    except Exception as e:
        raise ValueError(f"WeasyPrint conversion failed: {e}")
