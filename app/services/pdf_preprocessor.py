"""
pdf_preprocessor.py
Enriches query result rows with computed fields for smarter PDF generation.
Called from agent.py _execute_tool → generate_pdf BEFORE sending to pdf_engine.
"""
from datetime import date, datetime
from typing import Any


def preprocess_rows(rows: list[dict], doc_type: str | None = None) -> tuple[list[dict], dict]:
    """
    Analyse rows and return (enriched_rows, analysis_summary).

    analysis_summary is passed as extra_context to pdf_engine so the
    LLM knows the computed totals without re-deriving them.
    """
    if not rows:
        return rows, {}

    rows = [dict(r) for r in rows]  # make mutable copies

    # ── Normalize date fields ──────────────────────────────────────────────
    for row in rows:
        for k, v in list(row.items()):
            if isinstance(v, datetime):
                row[k] = v.date()

    # CRITICAL: Tax Invoices and Quotations must never receive aging enrichment.
    # The risk_bucket/days_overdue fields they'd gain cause risk_mode=True in
    # pdf_engine, which completely overwrites the invoice/quotation formatting
    # with the aging report template regardless of doc_type.
    if doc_type in ("invoice", "quotation"):
        return rows, {}

    # ── Aging / risk analysis (invoices + due_date) ───────────────────────
    has_due_date = any("due_date" in r and r["due_date"] for r in rows)
    has_amount   = any("amount" in r for r in rows)

    analysis: dict[str, Any] = {}

    if has_due_date and has_amount:
        today = date.today()
        buckets = {"HIGH": [], "MEDIUM": [], "LOW": [], "UPCOMING": []}

        for row in rows:
            raw_due = row.get("due_date")
            if raw_due:
                if isinstance(raw_due, str):
                    try:
                        raw_due = date.fromisoformat(raw_due[:10])
                    except ValueError:
                        raw_due = None

            if raw_due:
                days = (today - raw_due).days          # positive = overdue
                row["days_overdue"] = max(0, days)
                row["days_label"]   = f"{days}d overdue" if days > 0 else "due soon"

                if days > 90:
                    bucket = "HIGH"
                elif days > 30:
                    bucket = "MEDIUM"
                elif days > 0:
                    bucket = "LOW"
                else:
                    bucket = "UPCOMING"
            else:
                row["days_overdue"] = 0
                row["days_label"]   = "no due date"
                bucket = "UPCOMING"

            row["risk_bucket"] = bucket
            row["risk_label"]  = {
                "HIGH":     "HIGH RISK",
                "MEDIUM":   "MEDIUM RISK",
                "LOW":      "LOW RISK",
                "UPCOMING": "UPCOMING",
            }[bucket]
            buckets[bucket].append(row)

        # Compute per-bucket totals
        for bkt, bkt_rows in buckets.items():
            total = sum(float(r.get("amount", 0)) for r in bkt_rows)
            analysis[f"{bkt.lower()}_risk_total"]   = total
            analysis[f"{bkt.lower()}_risk_count"]   = len(bkt_rows)

        analysis["grand_total"]   = sum(float(r.get("amount", 0)) for r in rows)
        analysis["total_invoices"] = len(rows)

        # Sort: HIGH risk first, then MEDIUM, then LOW, then UPCOMING
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UPCOMING": 3}
        rows.sort(key=lambda r: (order.get(r.get("risk_bucket", "UPCOMING"), 4),
                                  -r.get("days_overdue", 0)))

        # Top debtors for key insights
        customer_totals: dict[str, float] = {}
        for r in rows:
            cname = (r.get("customer_name") or r.get("name") or "Unknown")
            customer_totals[cname] = customer_totals.get(cname, 0) + float(r.get("amount", 0))
        top3 = sorted(customer_totals.items(), key=lambda x: -x[1])[:3]
        analysis["top_debtors"] = [{"name": n, "total": t} for n, t in top3]

    # ── Inventory analysis ─────────────────────────────────────────────────
    has_qty = any("qty" in r for r in rows)
    has_reorder = any("reorder_level" in r for r in rows)

    if has_qty and has_reorder:
        for row in rows:
            qty     = int(row.get("qty", 0))
            reorder = int(row.get("reorder_level", 0))
            below   = qty <= reorder
            row["stock_status"]    = "🔴 CRITICAL" if qty == 0 else ("⚠️ LOW" if below else "✅ OK")
            row["shortage_units"]  = max(0, reorder - qty) if below else 0

        analysis["critical_count"]  = sum(1 for r in rows if r.get("qty", 0) == 0)
        analysis["low_stock_count"] = sum(1 for r in rows if 0 < r.get("qty", 0) <= r.get("reorder_level", 0))
        analysis["total_items"]     = len(rows)

    return rows, analysis
