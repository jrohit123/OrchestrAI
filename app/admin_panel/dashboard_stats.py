"""The stat cards and the low-stock table some organisations show on Home.

There is no code here that knows "jewellery orgs have invoices" or "housing societies have cases".
A card is entirely described by orgs.settings -> 'dashboard_stats', and every table and column in it
is checked against the organisation's own live schema before it reaches SQL (the same allowlist the
steps use when they write).

Example, set once per organisation as data:
  {"dashboard_stats": {
    "cards": [
      {"key": "total_invoices", "label": "Paid Invoices", "table": "invoices",
       "agg": "count", "where": {"status": "paid"}},
      {"key": "total_amount", "label": "Total Revenue", "table": "invoices",
       "agg": "sum", "column": "amount", "where": {"status": "paid"},
       "format": "currency_inr", "color": "#16a34a"}
    ],
    "low_stock": {"label": "Low Stock Alert", "table": "inventory",
                  "qty_column": "qty", "reorder_column": "reorder_level",
                  "display_columns": ["name", "qty", "reorder_level"]}
  }}
label, format and color only change how a card looks. An organisation with no dashboard_stats gets
nothing (null, never a zero): "0 invoices" and "does not track invoices" are different facts.
"""

from app.admin_panel.common import Ctx, jb
from app.db import fetch_all, fetch_one
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)


async def compute_stats(cfg: dict, org_id: str, source_key: str) -> list | None:
    from app.services.step_interpreter import (
        StepError,
        _load_schema_allowlist,
        _validate_identifier,
    )

    cards = cfg.get("cards") or []
    if not cards:
        return None

    allowlist = await _load_schema_allowlist(source_key)
    out: list = []
    for card in cards:
        try:
            table = card["table"]
            key = card["key"]
            agg = card.get("agg", "count")
            column = card.get("column")
            where = card.get("where") or {}

            _validate_identifier(table, "table name")
            if table not in allowlist:
                continue
            if column:
                _validate_identifier(column, "column name")
                if column not in allowlist[table]:
                    continue
            for col in where:
                _validate_identifier(col, "column name")
                if col not in allowlist[table]:
                    raise StepError(f"unknown column '{col}' on '{table}'")

            where_cols = list(where.keys())
            where_clause = " AND ".join(
                f"{c} = ${i + 2}" for i, c in enumerate(where_cols)
            )
            where_sql = (
                f"WHERE org_id = $1 AND {where_clause}"
                if where_clause
                else "WHERE org_id = $1"
            )

            if agg == "sum" and column:
                sql = (
                    f"SELECT COALESCE(SUM({column}), 0) AS val FROM {table} {where_sql}"
                )
            else:
                sql = f"SELECT COUNT(*) AS val FROM {table} {where_sql}"

            row = await fetch_one(sql, org_id, *where.values(), source_key=source_key)
            # a self-describing list (key, label, value, format, color): the page draws
            # whatever cards this organisation set up and knows nothing about them in advance
            out.append(
                {
                    "key": key,
                    "label": card.get("label") or key.replace("_", " ").title(),
                    "value": row["val"] if row else 0,
                    "format": card.get("format", "number"),
                    "color": card.get("color"),
                }
            )
        except (KeyError, StepError) as e:
            logger.warning(f"dashboard_stats: skipping malformed card {card}: {e}")
            continue

    return out or None


async def compute_low_stock(cfg: dict, org_id: str, source_key: str) -> dict | None:
    from app.services.step_interpreter import (
        StepError,
        _load_schema_allowlist,
        _validate_identifier,
    )

    ls = cfg.get("low_stock")
    if not ls:
        return None

    try:
        table = ls["table"]
        qty_col = ls["qty_column"]
        reorder_col = ls["reorder_column"]
        display_cols = ls.get("display_columns") or [qty_col, reorder_col]

        allowlist = await _load_schema_allowlist(source_key)
        _validate_identifier(table, "table name")
        if table not in allowlist:
            return None
        for c in {qty_col, reorder_col, *display_cols}:
            _validate_identifier(c, "column name")
            if c not in allowlist[table]:
                return None

        cols_sql = ", ".join(display_cols)
        found = await fetch_all(
            f"SELECT {cols_sql} FROM {table} WHERE org_id = $1 AND {qty_col} <= {reorder_col}",
            org_id,
            source_key=source_key,
        )
        # row-shaped output the page draws generically: a title, ordered {key, label}
        # columns, and rows keyed by those same names
        return {
            "title": ls.get("label", "Low Stock Alert"),
            "columns": [
                {"key": c, "label": c.replace("_", " ").title()} for c in display_cols
            ],
            "rows": [dict(r) for r in found],
        }
    except (KeyError, StepError) as e:
        logger.warning(
            f"dashboard_stats.low_stock: skipping malformed config {ls}: {e}"
        )
        return None


async def home_extras(ctx: Ctx) -> dict:
    """The two optional extras for Home. Never raises: Home opens without them if anything is off."""
    empty: dict = {"stats": None, "low_stock": None}
    try:
        org = await fetch_one(
            "SELECT settings FROM orgs WHERE id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
        settings = jb(org["settings"], {}) if org else {}
        cfg = settings.get("dashboard_stats") if isinstance(settings, dict) else None
        if not isinstance(cfg, dict):
            return empty
        return {
            "stats": await compute_stats(cfg, ctx.org_id, ctx.source_key),
            "low_stock": await compute_low_stock(cfg, ctx.org_id, ctx.source_key),
        }
    except Exception as e:
        logger.warning(f"home: the optional stat cards were skipped: {e!r}")
        return empty
