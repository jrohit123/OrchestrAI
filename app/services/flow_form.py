"""The complaint form as a WhatsApp Flow, built from a plain description kept in the database.

The description (orgs.settings -> whatsapp_flows.complaint.form) says which questions the form asks, their words, whether
each is required and in what order. From it this module makes the Flow layout Meta needs, so the dashboard can edit the form
and publish it without anyone opening Meta. What the dropdown and the urgency buttons offer is not here: it is sent with
each message from the database (see flows.form_data), so the Flow only declares where that data goes.

Meta's own limits are kept here so a mistake is told on the dashboard before anything is sent."""

import copy

LAYOUT_VERSION = "6.2"
SCREEN_ID = "COMPLAINT"
TITLE_MAX, BUTTON_MAX, HELP_MAX = 30, 35, 80
LABEL_MAX = {
    "location": 20,
    "problem": 20,
    "category": 20,
    "priority": 30,
    "photos": 80,
}
PHOTOS_MAX = 10
# Questions the chat needs, so they cannot be hidden or made optional
ALWAYS = {"location": True, "problem": True}
KINDS = {
    "location": "TextInput",
    "problem": "TextArea",
    "category": "Dropdown",
    "priority": "RadioButtonsGroup",
    "photos": "PhotoPicker",
}

DEFAULT_FORM: dict = {
    "title": "Raise a complaint",
    "button": "Submit",
    "photos_max": 3,
    "fields": [
        {
            "name": "location",
            "label": "Tower and flat",
            "help": "For example T5-901",
            "required": True,
            "show": True,
        },
        {
            "name": "problem",
            "label": "What is the problem?",
            "help": "For example Leakage in bathroom",
            "required": True,
            "show": True,
        },
        {
            "name": "category",
            "label": "Category",
            "help": "",
            "required": False,
            "show": True,
        },
        {
            "name": "priority",
            "label": "How urgent is it?",
            "help": "",
            "required": True,
            "show": True,
        },
        {
            "name": "photos",
            "label": "Add photos",
            "help": "",
            "required": False,
            "show": True,
        },
    ],
}


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _strip_optional(label: str) -> str:
    """Meta adds "(optional)" to every question that is not required, so it is never typed into a label."""
    low = label.lower()
    for tail in ("(optional)", "optional"):
        if low.endswith(tail):
            return label[: len(label) - len(tail)].rstrip(" -:")
    return label


def normalise(raw) -> dict:
    """A form description cleaned up and checked. Raises ValueError with a sentence for the person editing."""
    base = copy.deepcopy(DEFAULT_FORM)
    raw = raw if isinstance(raw, dict) else {}
    title = _text(raw.get("title", base["title"]), 200)
    button = _text(raw.get("button", base["button"]), 200)
    if not title or len(title) > TITLE_MAX:
        raise ValueError(f"The form title needs 1 to {TITLE_MAX} letters.")
    if not button or len(button) > BUTTON_MAX:
        raise ValueError(f"The submit button needs 1 to {BUTTON_MAX} letters.")
    try:
        photos_max = int(raw.get("photos_max", base["photos_max"]))
    except (TypeError, ValueError):
        raise ValueError("The number of photos must be a number.") from None
    if not 1 <= photos_max <= PHOTOS_MAX:
        raise ValueError(f"Photos can be between 1 and {PHOTOS_MAX}.")
    given = raw.get("fields")
    by_name = {f["name"]: f for f in base["fields"]}
    order = []
    for f in given if isinstance(given, list) else base["fields"]:
        name = f.get("name") if isinstance(f, dict) else None
        if name in by_name and name not in order:
            order.append(name)
    order += [n for n in by_name if n not in order]
    given_by_name = {f.get("name"): f for f in given or [] if isinstance(f, dict)}
    fields = []
    for name in order:
        src, mine = given_by_name.get(name, {}), by_name[name]
        label = _strip_optional(_text(src.get("label", mine["label"]), 200))
        helper = _text(src.get("help", mine["help"]), 200)
        if not label or len(label) > LABEL_MAX[name]:
            raise ValueError(
                f"The words for “{mine['label']}” need 1 to {LABEL_MAX[name]} letters."
            )
        if len(helper) > HELP_MAX:
            raise ValueError(
                f"The hint under “{label}” can be {HELP_MAX} letters at most."
            )
        must = ALWAYS.get(name)
        fields.append(
            {
                "name": name,
                "label": label,
                "help": "" if name in ("photos", "priority") else helper,
                "required": True
                if must
                else src.get("required", mine["required"]) is True,
                "show": True if must else src.get("show", True) is not False,
            }
        )
    if not any(f["show"] for f in fields):
        raise ValueError("The form needs at least one question.")
    return {
        "title": title,
        "button": button,
        "photos_max": photos_max,
        "fields": fields,
    }


def _choices(name: str) -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "title": {"type": "string"}},
        },
        "__example__": [{"id": name + "_example", "title": name.title()}],
    }


def build(form: dict) -> dict:
    """The Flow layout for a (normalised) description."""
    form = normalise(form)
    children, payload = [], {}
    for f in form["fields"]:
        payload[f["name"]] = "${form." + f["name"] + "}"
        if not f["show"]:
            continue
        kind, name = KINDS[f["name"]], f["name"]
        item: dict = {"type": kind, "name": name, "label": f["label"]}
        if kind == "TextInput":
            item["input-type"] = "text"
        if kind in ("Dropdown", "RadioButtonsGroup"):
            item["data-source"] = (
                "${data." + ("categories" if name == "category" else "priorities") + "}"
            )
        if kind == "PhotoPicker":
            item.update(
                {
                    "description": f"Up to {form['photos_max']} photo"
                    + ("" if form["photos_max"] == 1 else "s"),
                    "photo-source": "camera_gallery",
                    "max-file-size-kb": 5120,
                    "min-uploaded-photos": 1 if f["required"] else 0,
                    "max-uploaded-photos": form["photos_max"],
                }
            )
        else:
            item["required"] = f["required"]
            if f["help"] and kind in ("TextInput", "TextArea"):
                item["helper-text"] = f["help"]
        children.append(item)
    children.append(
        {
            "type": "Footer",
            "label": form["button"],
            "on-click-action": {
                "name": "complete",
                "payload": {k: v for k, v in payload.items() if _shown(form, k)},
            },
        }
    )
    return {
        "version": LAYOUT_VERSION,
        "screens": [
            {
                "id": SCREEN_ID,
                "title": form["title"],
                "terminal": True,
                "success": True,
                "data": {
                    "categories": _choices("category"),
                    "priorities": _choices("priority"),
                },
                "layout": {"type": "SingleColumnLayout", "children": children},
            }
        ],
    }


def _shown(form: dict, name: str) -> bool:
    return any(f["name"] == name and f["show"] for f in form["fields"])
