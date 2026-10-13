"""Making and publishing WhatsApp Flows through Meta's Flows API, so the dashboard can do it and nobody opens Meta.

A published Flow cannot be changed, so every change is a new Flow: it is made, checked by Meta, published, and then the
organisation's setting (whatsapp_flows.complaint.flow_id) points at it and the old one is retired. If Meta finds
anything wrong the new Flow is thrown away and the old one keeps working; nobody is left without a form."""

import json
import os
import time

import httpx

from app.logging_config import get_context_logger
from app.services import whatsapp

logger = get_context_logger(__name__)

GRAPH = "https://graph.facebook.com/v22.0"


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


async def status_of(flow_id: str) -> str | None:
    try:
        return (await _call("GET", str(flow_id), params={"fields": "status"})).get(
            "status"
        )
    except MetaError:
        return None


def _problems(result: dict) -> list[str]:
    out = []
    for e in result.get("validation_errors") or []:
        where = e.get("pointers") or []
        at = (
            where[0].get("path") if where and isinstance(where[0], dict) else ""
        ) or ""
        out.append(
            (
                str(
                    e.get("message")
                    or e.get("error")
                    or "Meta did not accept the layout"
                )
                + (f" ({at})" if at else "")
            )[:300]
        )
    return out


async def publish_new(account: str, name: str, layout: dict) -> str:
    """Make, check and publish a new Flow; its id. Raises MetaError with Meta's reasons, leaving no half-made Flow."""
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    made = await _call(
        "POST",
        f"{account}/flows",
        data={
            "name": f"{name}_{stamp}"[:200],
            "categories": json.dumps(["OTHER"]),
            "flow_json": json.dumps(layout),
        },
    )
    flow_id = str(made.get("id") or "")
    if not flow_id:
        raise MetaError("Meta did not make the Flow.")
    problems = _problems(made)
    if problems:
        await discard(flow_id)
        raise MetaError("Meta did not accept the form: " + "; ".join(problems))
    try:
        await _call("POST", f"{flow_id}/publish")
    except MetaError:
        await discard(flow_id)
        raise
    return flow_id


async def discard(flow_id: str) -> None:
    """Throw away a Flow that was never published. Never raises."""
    try:
        await _call("DELETE", str(flow_id))
    except MetaError as e:
        logger.warning(f"flow admin: could not remove the unused Flow: {e}")


async def retire(flow_id: str) -> None:
    """Take an old published Flow out of use (people who still hold its message keep a working form until then). Never raises."""
    try:
        await _call("POST", f"{flow_id}/deprecate")
    except MetaError as e:
        logger.warning(f"flow admin: could not retire the old Flow: {e}")
