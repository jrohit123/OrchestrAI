"""Managing WhatsApp Flows through Meta's Flows API, so the dashboard can list, write, check, test and publish them and nobody
opens Meta. A Flow starts as a draft whose layout (Flow JSON) can be saved again and again; publishing makes it final, and a
published Flow cannot be changed (to change it, make a copy, which is a new draft)."""

import json
import os

import httpx

from app.logging_config import get_context_logger
from app.services import whatsapp

logger = get_context_logger(__name__)

GRAPH = "https://graph.facebook.com/v22.0"

# Something to start from: two short screens that ask a question and say thanks. It needs no data and no server.
SAMPLE = {
    "version": "6.2",
    "screens": [
        {
            "id": "WELCOME",
            "title": "Test form",
            "layout": {
                "type": "SingleColumnLayout",
                "children": [
                    {"type": "TextHeading", "text": "Hello from the dashboard"},
                    {
                        "type": "TextBody",
                        "text": "This is a test Flow. Fill it in and press Continue.",
                    },
                    {
                        "type": "TextInput",
                        "name": "full_name",
                        "label": "Your name",
                        "input-type": "text",
                        "required": True,
                    },
                    {
                        "type": "Dropdown",
                        "name": "colour",
                        "label": "Favourite colour",
                        "required": True,
                        "data-source": [
                            {"id": "red", "title": "Red"},
                            {"id": "green", "title": "Green"},
                            {"id": "blue", "title": "Blue"},
                        ],
                    },
                    {
                        "type": "TextArea",
                        "name": "note",
                        "label": "A note",
                        "helper-text": "Anything you like",
                        "required": False,
                    },
                    {
                        "type": "Footer",
                        "label": "Continue",
                        "on-click-action": {
                            "name": "navigate",
                            "next": {"type": "screen", "name": "THANKS"},
                            "payload": {
                                "full_name": "${form.full_name}",
                                "colour": "${form.colour}",
                                "note": "${form.note}",
                            },
                        },
                    },
                ],
            },
        },
        {
            "id": "THANKS",
            "title": "Thank you",
            "terminal": True,
            "success": True,
            "data": {
                "full_name": {"type": "string", "__example__": "Asha"},
                "colour": {"type": "string", "__example__": "green"},
                "note": {"type": "string", "__example__": "Looks good"},
            },
            "layout": {
                "type": "SingleColumnLayout",
                "children": [
                    {"type": "TextHeading", "text": "All done"},
                    {
                        "type": "TextBody",
                        "text": "Press Finish to send your answers back to the chat.",
                    },
                    {
                        "type": "Footer",
                        "label": "Finish",
                        "on-click-action": {
                            "name": "complete",
                            "payload": {
                                "full_name": "${data.full_name}",
                                "colour": "${data.colour}",
                                "note": "${data.note}",
                            },
                        },
                    },
                ],
            },
        },
    ],
}
BLANK = {
    "version": "6.2",
    "screens": [
        {
            "id": "START",
            "title": "My screen",
            "terminal": True,
            "success": True,
            "layout": {
                "type": "SingleColumnLayout",
                "children": [
                    {"type": "TextBody", "text": "Hello"},
                    {
                        "type": "Footer",
                        "label": "Done",
                        "on-click-action": {"name": "complete", "payload": {}},
                    },
                ],
            },
        }
    ],
}


class MetaError(Exception):
    """Something Meta refused, in words for the person at the dashboard."""


def _say_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        err = {}
    text = (
        err.get("error_user_msg")
        or err.get("message")
        or f"Meta answered {resp.status_code}"
    )
    if err.get("code") in (10, 200, 190) or resp.status_code in (401, 403):
        text += " (the WhatsApp access token may lack permission to manage Flows)"
    return str(text)[:400]


async def _call(method: str, path: str, **kw) -> dict:
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.request(
            method,
            f"{GRAPH}/{path}",
            headers={"Authorization": f"Bearer {whatsapp.WHATSAPP_TOKEN}"},
            **kw,
        )
    if resp.status_code >= 400:
        logger.warning(
            f"flow admin: {method} {path.split('/')[-1]} failed ({resp.status_code})"
        )
        raise MetaError(_say_error(resp))
    try:
        return resp.json()
    except ValueError:
        return {}


async def find_account(configured: str | None) -> str | None:
    """The WhatsApp business account id: the one saved in settings, the WHATSAPP_WABA_ID variable, or whatever Meta says
    owns the number."""
    for known in (configured, os.getenv("WHATSAPP_WABA_ID")):
        if known and str(known).strip().isdigit():
            return str(known).strip()
    if not whatsapp.WHATSAPP_PHONE_ID:
        return None
    try:
        found = await _call(
            "GET",
            whatsapp.WHATSAPP_PHONE_ID,
            params={"fields": "whatsapp_business_account"},
        )
    except MetaError:
        return None
    account = (found.get("whatsapp_business_account") or {}).get("id")
    return str(account) if account else None


def problems(result: dict) -> list[dict]:
    """Meta's complaints about a layout as [{message, line, column}]."""
    out = []
    for e in result.get("validation_errors") or []:
        out.append(
            {
                "message": str(
                    e.get("message")
                    or e.get("error")
                    or "Meta did not accept the layout"
                )[:300],
                "line": e.get("line_start"),
                "column": e.get("column_start"),
            }
        )
    return out


async def list_flows(account: str) -> list[dict]:
    found = await _call(
        "GET", f"{account}/flows", params={"fields": "id,name,status", "limit": 100}
    )
    return [
        {"id": str(f.get("id")), "name": f.get("name"), "status": f.get("status")}
        for f in found.get("data") or []
    ]


async def details(flow_id: str) -> dict:
    found = await _call(
        "GET",
        flow_id,
        params={
            "fields": "id,name,status,categories,validation_errors,json_version,preview.invalidate(false)"
        },
    )
    return {
        "id": str(found.get("id") or flow_id),
        "name": found.get("name"),
        "status": found.get("status"),
        "errors": problems(found),
        "preview_url": (found.get("preview") or {}).get("preview_url"),
    }


async def read_json(flow_id: str) -> str:
    """The layout text of a Flow, as Meta keeps it. Empty when there is none yet."""
    assets = (await _call("GET", f"{flow_id}/assets")).get("data") or []
    link = next(
        (a.get("download_url") for a in assets if a.get("asset_type") == "FLOW_JSON"),
        None,
    )
    if not link:
        return ""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(link)
    if resp.status_code >= 400:
        raise MetaError("Meta would not hand over the Flow JSON.")
    return resp.text


async def create(account: str, name: str, layout: dict) -> tuple[str, list[dict]]:
    """A new draft Flow with this layout: (its id, Meta's complaints about the layout, if any)."""
    made = await _call(
        "POST",
        f"{account}/flows",
        data={
            "name": name[:200],
            "categories": json.dumps(["OTHER"]),
            "flow_json": json.dumps(layout),
        },
    )
    flow_id = str(made.get("id") or "")
    if not flow_id:
        raise MetaError("Meta did not make the Flow.")
    return flow_id, problems(made)


async def save_json(flow_id: str, text: str) -> list[dict]:
    """Keep this layout in the draft. Meta saves it even when it has mistakes; they come back as the list."""
    result = await _call(
        "POST",
        f"{flow_id}/assets",
        data={"name": "flow.json", "asset_type": "FLOW_JSON"},
        files={"file": ("flow.json", text.encode("utf-8"), "application/json")},
    )
    return problems(result)


async def publish(flow_id: str) -> None:
    await _call("POST", f"{flow_id}/publish")


async def discard(flow_id: str) -> None:
    """Delete a draft Flow."""
    await _call("DELETE", flow_id)


async def retire(flow_id: str) -> None:
    """Take a published Flow out of use. Never raises."""
    try:
        await _call("POST", f"{flow_id}/deprecate")
    except MetaError as e:
        logger.warning(f"flow admin: could not retire the old Flow: {e}")
