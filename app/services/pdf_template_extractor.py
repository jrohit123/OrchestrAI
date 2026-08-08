"""
pdf_template_extractor.py — Authoring-time tool.

Takes an uploaded sample PDF (e.g. an existing invoice the business already uses)
and uses GPT-4o vision to reverse-engineer its layout into a pdf_config spec
(render_instructions + theme) that pdf_engine.py can use to regenerate
documents in the same visual style with new data.

Runs ONCE at workflow-authoring time — never on the message-time hot path.
"""
import base64
import json
import os
from openai import AsyncOpenAI

from app.config import required

_client = AsyncOpenAI(api_key=required("OPENAI_API_KEY"))


def _pdf_to_images(pdf_bytes: bytes, max_pages: int = 2) -> list[str]:
    """
    Rasterize first pages of a PDF to base64 PNG strings.
    Uses PyMuPDF (fitz) — no system poppler dependency.
    Falls back gracefully if pymupdf is not installed.
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        images = []
        for i in range(min(max_pages, doc.page_count)):
            pix = doc[i].get_pixmap(dpi=150)
            images.append(base64.b64encode(pix.tobytes("png")).decode())
        return images
    except ImportError:
        # PyMuPDF not installed — return empty list, extractor will skip vision
        print("[PDF_EXTRACTOR] PyMuPDF not installed — cannot rasterize PDF")
        return []
    except Exception as e:
        print(f"[PDF_EXTRACTOR] Could not rasterize PDF: {e}")
        return []


async def extract_pdf_template(pdf_bytes: bytes, doc_type_hint: str = "") -> dict:
    """
    Analyze a sample PDF and extract layout instructions for pdf_engine.py.

    Returns:
        {
            "doc_type_guess": "invoice|quotation|statement|report|orders",
            "theme": {"primary": "#hex", "light_bg": "#hex", "text": "#hex", "muted": "#hex"},
            "render_instructions": "300-500 words describing the layout..."
        }

    The returned dict can be merged directly into a workflow's pdf_config.
    """
    images = _pdf_to_images(pdf_bytes)

    if not images:
        # No images — return a generic fallback
        return {
            "doc_type_guess": doc_type_hint or "report",
            "theme": {
                "primary":  "#185FA5",
                "light_bg": "#EEF4FB",
                "text":     "#1A1A2E",
                "muted":    "#6B7280",
            },
            "render_instructions": (
                "Professional business document. "
                "Blue header with org name. "
                "Clean table with column headers. "
                "Totals block right-aligned. "
                "Footer with generation date."
            ),
        }

    hint_text = f" — this appears to be a {doc_type_hint}" if doc_type_hint else ""

    content = [
        {
            "type": "text",
            "text": (
                f"You are reverse-engineering a business document template{hint_text} "
                "so an AI can regenerate documents in this exact visual style for future data.\n\n"
                "Look at the attached page image(s). Describe the LAYOUT ONLY — "
                "never repeat any specific customer name, amount, invoice number, or other "
                "example value from this sample; those are just placeholder data.\n\n"
                "Return ONLY this JSON (no markdown, no explanation):\n"
                "{\n"
                '  "doc_type_guess": "invoice|quotation|statement|orders|report",\n'
                '  "theme": {"primary": "#hex", "light_bg": "#hex", "text": "#hex", "muted": "#hex"},\n'
                '  "render_instructions": "300-500 words: header/logo placement, title badge '
                "styling, section order (customer block, invoice meta, items table, totals block), "
                "table column layout and alignment, totals block structure, footer/terms style, "
                "colour scheme, distinctive visual elements (borders, dividers, colour blocks). "
                'Written as instructions another AI would follow to rebuild this exact layout."\n'
                "}"
            )
        }
    ]

    # Add page images
    for img_b64 in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
        })

    response = await _client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1500,
        temperature=0.1,
        messages=[{"role": "user", "content": content}]
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if present
    if "```" in raw:
        raw = raw[raw.find("{"):raw.rfind("}") + 1]

    try:
        spec = json.loads(raw)
        # Validate required keys
        if "doc_type_guess" not in spec:
            spec["doc_type_guess"] = doc_type_hint or "report"
        if "theme" not in spec:
            spec["theme"] = {"primary": "#185FA5", "light_bg": "#EEF4FB",
                             "text": "#1A1A2E", "muted": "#6B7280"}
        if "render_instructions" not in spec:
            spec["render_instructions"] = "Standard business document layout."
        return spec
    except json.JSONDecodeError:
        # Return a safe default if parsing fails
        return {
            "doc_type_guess": doc_type_hint or "report",
            "theme": {"primary": "#185FA5", "light_bg": "#EEF4FB",
                      "text": "#1A1A2E", "muted": "#6B7280"},
            "render_instructions": (
                "Professional business document with blue header, "
                "customer details block, items table, totals section, and footer."
            ),
        }
