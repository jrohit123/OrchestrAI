"""Managing WhatsApp message templates through Meta's Graph API, so the dashboard can list them with their approval status,
make a new one in plain words, send it to Meta for approval and delete it, and nobody opens WhatsApp Manager.

A template is the one kind of message WhatsApp lets the chat bot start with a person who has not written in the last 24 hours.
Meta checks every template before it can be used (pending, then approved or rejected with a reason); an approved one cannot be
edited freely, so changing one means making a new one.

This module talks to Meta the same way app/services/flow_admin.py does (same access token, same business account number), and
every call goes through the one thin function `call`, so tests replace that single function and never reach Meta.

The plain form of a template ("spec") is what the dashboard edits:
    {name, language, category, header: {text, example}, body, examples: [..], footer, buttons: [{kind, text, url, example, phone}],
     labels: [..]}
`labels` (what each blank is for) are only kept on our side; Meta has no place for them."""

import re

from app.logging_config import get_context_logger
from app.services import flow_admin

logger = get_context_logger(__name__)

MetaError = flow_admin.MetaError

CATEGORIES = ("UTILITY", "MARKETING", "AUTHENTICATION")
BUTTON_KINDS = ("quick_reply", "url", "phone")
LIMITS = {
    "name": 512,
    "header": 60,
    "body": 1024,
    "footer": 60,
    "button": 25,
    "example": 150,
    "quick_reply": 10,
    "url": 2,
    "phone": 1,
    "buttons": 10,
}
BLANK = re.compile(r"\{\{\s*(\d+)\s*\}\}")


class TemplateError(ValueError):
    """The template is not ready to send, in words for the person at the dashboard."""


async def call(method: str, path: str, **kw) -> dict:
    """The one door to Meta for templates. Same token and error handling as the Flows calls."""
    return await flow_admin._call(method, path, **kw)


def slug(text: str) -> str:
    """A template name Meta accepts: lower-case letters, digits and underscores."""
    out = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return out[: LIMITS["name"]]


def blanks_of(text: str) -> list[int]:
    return [int(n) for n in BLANK.findall(text or "")]


def _clean(text) -> str:
    return str(text or "").strip()


def _need_in_order(numbers: list[int], where: str) -> None:
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        raise TemplateError(
            f"The blanks in the {where} must be numbered {{{{1}}}}, {{{{2}}}}, {{{{3}}}} in order, each used once."
        )


def clean_spec(raw: dict) -> dict:
    """Check a template written in the dashboard and return it tidied, or raise TemplateError in plain words."""
    raw = raw if isinstance(raw, dict) else {}
    name = slug(raw.get("name"))
    if not name:
        raise TemplateError(
            "Give the template a name (letters, digits and underscores)."
        )
    language = _clean(raw.get("language")) or "en"
    if not re.fullmatch(r"[a-z]{2,3}(_[A-Z]{2})?", language):
        raise TemplateError(
            "The language looks like en, hi or en_US. Pick one from the list."
        )
    category = _clean(raw.get("category")).upper() or "UTILITY"
    if category not in CATEGORIES:
        raise TemplateError("Pick a kind: utility, marketing or authentication.")

    spec: dict = {
        "name": name,
        "language": language,
        "category": category,
        "header": None,
        "body": "",
        "examples": [],
        "footer": "",
        "buttons": [],
        "labels": [],
    }
    if category == "AUTHENTICATION":
        # Meta writes the message itself (the one-time code); only an expiry note and the copy button are ours
        return spec

    header = raw.get("header")
    header_text = _clean(header.get("text")) if isinstance(header, dict) else ""
    if header_text:
        if len(header_text) > LIMITS["header"]:
            raise TemplateError(
                f"The headline can be {LIMITS['header']} letters at most."
            )
        found = blanks_of(header_text)
        if found not in ([], [1]):
            raise TemplateError("The headline can have one blank, written {{1}}.")
        example = _clean(header.get("example"))
        if found and not example:
            raise TemplateError("Type an example for the blank in the headline.")
        spec["header"] = {"text": header_text, "example": example if found else ""}

    body = _clean(raw.get("body"))
    if not body:
        raise TemplateError("Write the message itself (the body).")
    if len(body) > LIMITS["body"]:
        raise TemplateError(f"The message can be {LIMITS['body']} letters at most.")
    found = blanks_of(body)
    _need_in_order(found, "message")
    if found and (BLANK.match(body) or re.search(r"\{\{\s*\d+\s*\}\}$", body)):
        raise TemplateError(
            "A message cannot start or end with a blank. Put a few words before and after it."
        )
    examples = [_clean(e) for e in (raw.get("examples") or [])][: len(found)]
    examples += [""] * (len(found) - len(examples))
    for i, e in enumerate(examples, 1):
        if not e:
            raise TemplateError(
                f"Type an example for blank {{{{{i}}}}}. Meta asks for one so it can check the message."
            )
        if len(e) > LIMITS["example"]:
            raise TemplateError(
                f"An example can be {LIMITS['example']} letters at most."
            )
    labels = [_clean(x)[:60] for x in (raw.get("labels") or [])][: len(found)]
    labels += [""] * (len(found) - len(labels))
    spec.update(body=body, examples=examples, labels=labels)

    footer = _clean(raw.get("footer"))
    if footer:
        if len(footer) > LIMITS["footer"]:
            raise TemplateError(
                f"The small print can be {LIMITS['footer']} letters at most."
            )
        if blanks_of(footer):
            raise TemplateError("The small print cannot have blanks.")
        spec["footer"] = footer

    counts = {k: 0 for k in BUTTON_KINDS}
    for b in raw.get("buttons") or []:
        b = b if isinstance(b, dict) else {}
        kind = _clean(b.get("kind"))
        if kind not in BUTTON_KINDS:
            raise TemplateError("A button is a quick reply, a link or a phone number.")
        text = _clean(b.get("text"))
        if not text:
            raise TemplateError("Every button needs the words on it.")
        if len(text) > LIMITS["button"]:
            raise TemplateError(
                f"The words on a button can be {LIMITS['button']} letters at most."
            )
        item = {"kind": kind, "text": text, "url": "", "example": "", "phone": ""}
        if kind == "url":
            url = _clean(b.get("url"))
            if not re.match(r"https?://", url):
                raise TemplateError(
                    "A link button needs an address that starts with https://"
                )
            tail = blanks_of(url)
            if tail not in ([], [1]) or (tail and not url.endswith("{{1}}")):
                raise TemplateError(
                    "A link can end with one blank, written {{1}}, for example https://example.com/track/{{1}}"
                )
            example = _clean(b.get("example"))
            if tail and not example:
                raise TemplateError(
                    "Type an example for the blank at the end of the link."
                )
            item.update(url=url, example=example if tail else "")
        if kind == "phone":
            phone = re.sub(r"[^\d+]", "", _clean(b.get("phone")))
            if not re.fullmatch(r"\+?\d{8,15}", phone):
                raise TemplateError(
                    "A phone button needs the number with its country code, for example +919876543210."
                )
            item["phone"] = phone
        counts[kind] += 1
        if counts[kind] > LIMITS[kind]:
            raise TemplateError(
                {
                    "quick_reply": "At most 10 quick-reply buttons.",
                    "url": "At most 2 link buttons.",
                    "phone": "At most 1 phone button.",
                }[kind]
            )
        spec["buttons"].append(item)
    if len(spec["buttons"]) > LIMITS["buttons"]:
        raise TemplateError("At most 10 buttons in all.")
    quick = [i for i, b in enumerate(spec["buttons"]) if b["kind"] == "quick_reply"]
    if quick and len(quick) < len(spec["buttons"]):
        together = quick == list(range(quick[0], quick[-1] + 1))
        if not (together and (quick[0] == 0 or quick[-1] == len(spec["buttons"]) - 1)):
            raise TemplateError(
                "Put the quick replies together: either all before or all after the link and phone buttons."
            )
    return spec


def build_payload(spec: dict) -> dict:
    """The body of Meta's "create a message template" call, from a checked spec."""
    spec = clean_spec(spec)
    components: list[dict] = []
    if spec["category"] == "AUTHENTICATION":
        components.append({"type": "BODY", "add_security_recommendation": True})
        components.append(
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "OTP", "otp_type": "COPY_CODE", "text": "Copy code"}
                ],
            }
        )
    else:
        if spec["header"]:
            head = {"type": "HEADER", "format": "TEXT", "text": spec["header"]["text"]}
            if spec["header"]["example"]:
                head["example"] = {"header_text": [spec["header"]["example"]]}
            components.append(head)
        body = {"type": "BODY", "text": spec["body"]}
        if spec["examples"]:
            body["example"] = {"body_text": [list(spec["examples"])]}
        components.append(body)
        if spec["footer"]:
            components.append({"type": "FOOTER", "text": spec["footer"]})
        if spec["buttons"]:
            out = []
            for b in spec["buttons"]:
                if b["kind"] == "quick_reply":
                    out.append({"type": "QUICK_REPLY", "text": b["text"]})
                elif b["kind"] == "url":
                    item = {"type": "URL", "text": b["text"], "url": b["url"]}
                    if b["example"]:
                        item["example"] = [b["url"].replace("{{1}}", b["example"])]
                    out.append(item)
                else:
                    out.append(
                        {
                            "type": "PHONE_NUMBER",
                            "text": b["text"],
                            "phone_number": b["phone"],
                        }
                    )
            components.append({"type": "BUTTONS", "buttons": out})
    return {
        "name": spec["name"],
        "language": spec["language"],
        "category": spec["category"],
        "components": components,
    }


def to_spec(item: dict) -> dict:
    """Meta's description of a template, as the plain form. Parts the form cannot show (a picture header, a catalogue button)
    are named in `extras` and left out."""
    spec: dict = {
        "id": str(item.get("id") or ""),
        "name": item.get("name") or "",
        "language": item.get("language") or "en",
        "category": str(item.get("category") or "").upper(),
        "status": str(item.get("status") or "").upper(),
        "reason": _reason(item),
        "header": None,
        "body": "",
        "examples": [],
        "footer": "",
        "buttons": [],
        "labels": [],
        "extras": [],
    }
    for c in item.get("components") or []:
        kind = str(c.get("type") or "").upper()
        if kind == "HEADER":
            if str(c.get("format") or "TEXT").upper() == "TEXT":
                ex = (c.get("example") or {}).get("header_text") or [""]
                spec["header"] = {"text": c.get("text") or "", "example": str(ex[0])}
            else:
                spec["extras"].append(f"a {str(c.get('format')).lower()} headline")
        elif kind == "BODY":
            spec["body"] = c.get("text") or ""
            rows = (c.get("example") or {}).get("body_text") or [[]]
            spec["examples"] = [str(x) for x in (rows[0] if rows else [])]
            if c.get("add_security_recommendation"):
                spec["body"] = "A one-time code (Meta writes this message)"
        elif kind == "FOOTER":
            spec["footer"] = c.get("text") or ""
        elif kind == "BUTTONS":
            for b in c.get("buttons") or []:
                t = str(b.get("type") or "").upper()
                if t == "QUICK_REPLY":
                    spec["buttons"].append(
                        {"kind": "quick_reply", "text": b.get("text") or ""}
                    )
                elif t == "URL":
                    ex = b.get("example") or [""]
                    url = b.get("url") or ""
                    spec["buttons"].append(
                        {
                            "kind": "url",
                            "text": b.get("text") or "",
                            "url": url,
                            "example": _tail_example(url, str(ex[0])),
                        }
                    )
                elif t == "PHONE_NUMBER":
                    spec["buttons"].append(
                        {
                            "kind": "phone",
                            "text": b.get("text") or "",
                            "phone": b.get("phone_number") or "",
                        }
                    )
                else:
                    spec["extras"].append(f"a “{b.get('text') or t.lower()}” button")
    spec["labels"] = [""] * len(spec["examples"])
    return spec


def _tail_example(url: str, example_url: str) -> str:
    """The example Meta kept for a link with a blank is the whole address; the form wants only what stands in the blank."""
    head = url.split("{{1}}")[0]
    return example_url.removeprefix(head)


def _reason(item: dict) -> str:
    reason = str(item.get("rejected_reason") or "").strip()
    return "" if reason.upper() in ("", "NONE") else reason


async def list_templates(account: str) -> list[dict]:
    found = await call(
        "GET",
        f"{account}/message_templates",
        params={
            "fields": "id,name,status,category,language,components,rejected_reason",
            "limit": 200,
        },
    )
    return [to_spec(t) for t in found.get("data") or []]


async def create(account: str, spec: dict) -> dict:
    """Send a template to Meta for approval. Returns {id, status, category} as Meta answers."""
    payload = build_payload(spec)
    made = await call("POST", f"{account}/message_templates", json=payload)
    return {
        "id": str(made.get("id") or ""),
        "status": str(made.get("status") or "PENDING").upper(),
        "category": str(made.get("category") or payload["category"]).upper(),
    }


async def remove(account: str, name: str, template_id: str | None = None) -> None:
    """Delete a template (all its languages when no id is given)."""
    params = {"name": name}
    if template_id:
        params["hsm_id"] = template_id
    await call("DELETE", f"{account}/message_templates", params=params)
