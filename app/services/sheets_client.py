"""
sheets_client.py — Generic Google Sheets CRUD client.

Mirrors the shape of app/db.py's fetch_all/fetch_one/execute so that
step_interpreter.py and agent.py can treat a Sheet tab exactly like a
Postgres table — same discipline, same "zero domain hardcoding" principle.

Auth: service account (no user OAuth flow, no browser consent needed).
The service account's client_email must be added as an Editor on the
target spreadsheet (see setup doc, section 2.2).
"""
import os
import json
import base64
import asyncio
from functools import lru_cache

import gspread
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


@lru_cache(maxsize=1)
def _get_client() -> gspread.Client:
    b64 = os.getenv("GOOGLE_SHEETS_CREDENTIALS_B64")
    if not b64:
        raise RuntimeError(
            "GOOGLE_SHEETS_CREDENTIALS_B64 is not set. "
            "See integration doc, section 3."
        )
    info = json.loads(base64.b64decode(b64))
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


@lru_cache(maxsize=1)
def _get_spreadsheet():
    sheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    if not sheet_id:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID is not set.")
    return _get_client().open_by_key(sheet_id)


def _ws(tab: str):
    return _get_spreadsheet().worksheet(tab)


# ── Read ──────────────────────────────────────────────────────────────────

async def get_all_tab_headers() -> dict[str, list[str]]:
    """{'Suppliers': ['supplier_id','name',...], ...} — feeds the schema
    block the LLM sees in the system prompt."""
    def _sync():
        ss = _get_spreadsheet()
        return {ws.title: ws.row_values(1) for ws in ss.worksheets()}
    return await asyncio.to_thread(_sync)


async def sheet_fetch_all(tab: str) -> list[dict]:
    """All rows in a tab as a list of dicts, keyed by header row."""
    def _sync():
        return _ws(tab).get_all_records()
    return await asyncio.to_thread(_sync)


async def sheet_fetch_filtered(tab: str, filters: dict) -> list[dict]:
    """Case-insensitive partial match on every filter key (ILIKE-style)."""
    rows = await sheet_fetch_all(tab)
    if not filters:
        return rows
    out = []
    for r in rows:
        if all(
            str(v).strip().lower() in str(r.get(k, "")).strip().lower()
            for k, v in filters.items()
        ):
            out.append(r)
    return out


async def sheet_count_rows(tab: str) -> int:
    rows = await sheet_fetch_all(tab)
    return len(rows)


# ── Write ─────────────────────────────────────────────────────────────────

async def sheet_insert_row(tab: str, values: dict) -> dict:
    """Appends one row. Missing header columns are left blank; extra keys
    in `values` that don't match a header are silently dropped."""
    def _sync():
        ws = _ws(tab)
        header = ws.row_values(1)
        row = [values.get(col, "") for col in header]
        ws.append_row(row, value_input_option="USER_ENTERED")
    await asyncio.to_thread(_sync)
    return values


async def sheet_update_row(tab: str, where: dict, set_values: dict) -> dict | None:
    """Finds the first row matching ALL `where` columns (exact match) and
    updates `set_values` on it. Returns the updated row dict, or None if
    no row matched."""
    def _sync():
        ws = _ws(tab)
        header = ws.row_values(1)
        all_values = ws.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            row_dict = dict(zip(header, row))
            if all(str(row_dict.get(k, "")).strip() == str(v).strip()
                   for k, v in where.items()):
                for col, val in set_values.items():
                    if col in header:
                        ws.update_cell(idx, header.index(col) + 1, val)
                row_dict.update(set_values)
                return row_dict
        return None
    return await asyncio.to_thread(_sync)


async def sheet_delete_row(tab: str, where: dict) -> bool:
    """Finds the first row matching ALL `where` columns and deletes it."""
    def _sync():
        ws = _ws(tab)
        header = ws.row_values(1)
        all_values = ws.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            row_dict = dict(zip(header, row))
            if all(str(row_dict.get(k, "")).strip() == str(v).strip()
                   for k, v in where.items()):
                ws.delete_rows(idx)
                return True
        return False
    return await asyncio.to_thread(_sync)
