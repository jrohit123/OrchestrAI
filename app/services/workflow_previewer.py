"""
workflow_previewer.py — Generate a preview PDF from a compiled draft.

Uses synthetic placeholder data run through the EXACT same calc_engine + pdf_engine
path that production uses. This IS the consistency guarantee — not a separate check
that might drift, the same function call with fake data.
"""
import json
from app.services.calc_engine import compute_draft, CalcError
from app.services.pdf_engine import generate_pdf
from app.db import fetch_one


def _parse(val, default=None):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return val if val is not None else default


def _sample_value(field_spec: dict, field_name: str, idx: int = 0):
    """Generate a realistic placeholder value for a field."""
    t = field_spec.get("type", "string")
    if t == "float":
        return round(45000.0 + idx * 10000, 2)
    if t == "integer":
        return idx + 1
    # For common field names, use realistic samples
    samples = {
        "customer_name": "Sample Customer Pvt Ltd",
        "description":   f"Sample Item {idx + 1}",
        "metal_type":    "22kt Gold",
        "design_code":   f"DC-{idx+1:03d}",
        "design_name":   "Sample Design",
        "invoice_number": "PREVIEW-001",
        "quotation_number": "PREVIEW-001",
        "order_number":  "PREVIEW-001",
    }
    return samples.get(field_name, f"Sample {field_name.replace('_', ' ').title()}")


def build_sample_fields(entity_schema: dict) -> dict:
    """Build a sample fields dict from entity_schema, skipping computed fields."""
    fields = {}
    for name, spec in (entity_schema or {}).items():
        if not isinstance(spec, dict):
            continue
        if spec.get("computed"):
            continue
        if name == "items" and spec.get("type") == "array":
            item_schema = spec.get("item_schema") or {}
            fields["items"] = [
                {
                    n: _sample_value(s, n, i)
                    for n, s in item_schema.items()
                    if isinstance(s, dict) and not s.get("computed")
                }
                for i in range(2)
            ]
            continue
        fields[name] = _sample_value(spec, name)
    return fields


async def generate_preview_pdf(spec: dict, org_id: str, source_key: str) -> bytes:
    """
    Generate a preview PDF for a workflow spec using placeholder data.
    Returns PDF bytes.
    """
    entity_schema = _parse(spec.get("entity_schema"), {}) or {}
    calc_rules    = _parse(spec.get("calc_rules"), {}) or {}
    pdf_config    = _parse(spec.get("pdf_config"), {}) or {}

    sample_fields = build_sample_fields(entity_schema)

    # Run calc_engine with org context — same as production
    if calc_rules:
        org = await fetch_one("SELECT * FROM orgs WHERE id = $1", org_id, source_key=source_key)
        context = {
            k: (float(v) if hasattr(v, '__float__') and not isinstance(v, (str, bool)) else v)
            for k, v in dict(org or {}).items()
            if v is not None and k not in ("id", "slug", "created_at", "is_active", "plan")
        }
        try:
            sample_fields = compute_draft(calc_rules, sample_fields, context)
        except CalcError as e:
            print(f"[PREVIEWER] calc error (non-fatal): {e}")
            # Non-fatal — show the PDF with un-computed values

    # Build title
    title_tmpl = pdf_config.get("title_template") or spec.get("name", "Sample Document")
    try:
        title = title_tmpl.format(**sample_fields, invoice_number="PREVIEW-001",
                                   quotation_number="PREVIEW-001")
    except (KeyError, IndexError):
        title = title_tmpl

    # Merge sample fields into extra_context (same as _op_generate_pdf does)
    extra = {
        **sample_fields,
        "invoice_number":    "PREVIEW-001",
        "quotation_number":  "PREVIEW-001",
        "customer_name":     sample_fields.get("customer_name", "Sample Customer"),
        "customer_city":     "Sample City",
        "customer_gstin":    "27SAMPLE1234A1ZX",
        "status":            "pending",
        "due_date":          "2026-08-01",
    }

    row_data = {**sample_fields}
    rows = [row_data]

    return await generate_pdf(
        rows=rows,
        title=f"[PREVIEW] {title}",
        org_name="(Preview — Sample Data)",
        subtitle="Placeholder data only — not a real document",
        doc_type=pdf_config.get("doc_type", "report"),
        extra_context=extra,
        pdf_config=pdf_config,
    )
