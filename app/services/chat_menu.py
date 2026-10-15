"""The chat menu by use case: the menu people see in the chat, organised the way the organisation chose.

Without this, the menu lists every flow flat, in the sections a flow was filed under (Reports, Create, More). With it, the top of
the menu is the organisation's use cases (Tickets, and later Bookings, Visitors ...), under each the flows that belong to it, and
under a use case optionally one more level of groups (Tickets > Raise / My tickets / Reports): at most 3 levels in all.

The tree is setting data, not code: orgs.settings -> chat_menu, written by the dashboard (Chat bot > Menu):

    {"enabled": true,
     "nodes": [                                        # level 1: use cases
        {"id": "tickets", "label": "Tickets", "description": "Complaints and cases", "hidden": false,
         "children": [                                 # level 2: flows and groups
            {"flow": "my_cases", "label": "My tickets"},
            {"id": "raise", "label": "Raise", "children": [{"flow": "file_a_complaint"}]}]}],   # level 3: flows
     "show_unplaced": true, "other_label": "More",     # flows nobody placed go under a last use case with this name
     "only_roles": ["admin"],                          # optional: only these roles see it, everyone else keeps today's menu
     "back_label": "Back", "more_label": "More", "button_label": "Choose"}

Nothing is shown to a person that their role may not use: the tree is walked against the flows the existing check
(menu.get_menu_workflows) lets them use, and a group left with nothing is not shown. A flow that is hidden, switched off or
not allowed is simply absent. With no chat_menu setting (or enabled off) every function here says "not set" (None) and the
callers keep today's flat menu exactly as it was.

A list message holds 10 rows: a longer group is paged with a "More" row. Rows that open a group have the id "menu:<id>" (and
"menu:<id>:p2" for page 2); the chat bot answers such a tap with that group's list (see open_view). Flows keep their key as
the row id, as before. A published WhatsApp Flow gets the same tree as nested data (flow_data) and its layout can be made
from the tree (flow_layout); nothing is ever sent to Meta from here."""

import json
import re
import uuid

from app.logging_config import get_context_logger
from app.services import config_store, menu

logger = get_context_logger(__name__)

PREFIX = "menu:"
MAX_USE_CASES = 10
MAX_CHILDREN = 20
MAX_LEVELS = 3  # use case > group > flows
ROW_TITLE, ROW_DESCRIPTION, LABEL_MAX = 24, 72, 24  # what a list row holds
PAGE_ROWS = 10  # WhatsApp's limit for one list message
FLOW_TITLE, FLOW_DESCRIPTION = 30, 20  # what a Flow list item holds
FLOW_DATA_MAX_BYTES = 30000  # a menu panel bigger than this falls back to the list menu
OTHER_ID = "_other"
TOP = ""  # the id of the top of the menu
ID_OK = re.compile(r"^[a-z0-9][a-z0-9_]{0,19}$")
DEFAULT_WORDS = {
    "other_label": "More",
    "back_label": "Back",
    "more_label": "More",
    "button_label": "Choose",
}
WORD_MAX = {"other_label": 24, "back_label": 24, "more_label": 24, "button_label": 20}
FLOW_SCREENS = (
    "MENU",
    "SECTION",
    "SUBSECTION",
)  # the list screens of a Flow, one per level


def _one_line(text, size: int) -> str:
    return " ".join(str(text or "").split())[:size]


def _cut(text, size: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


# ───────────────────────── the saved tree ─────────────────────────


def config(settings: dict | None) -> dict | None:
    """The saved menu when it is switched on and has something in it; else None (today's menu)."""
    chosen = config_store.setting(settings, "chat_menu", None)
    if not isinstance(chosen, dict) or chosen.get("enabled") is not True:
        return None
    nodes = chosen.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None
    return chosen


def words(cfg: dict | None) -> dict:
    """The few words the menu itself uses (Back, More, ...), the organisation's own or the built-in ones."""
    out = dict(DEFAULT_WORDS)
    for k, size in WORD_MAX.items():
        v = _one_line((cfg or {}).get(k), size)
        if v:
            out[k] = v
    return out


def _fail(message: str):
    raise ValueError(message)


def clean(raw, known_flows: set[str] | None = None) -> dict:
    """What the dashboard sends, checked and put in its stored shape. Raises ValueError with a plain sentence.
    `known_flows` (the keys of the organisation's flows) is checked when given."""
    if not isinstance(raw, dict):
        _fail("The menu is not in the form the chat bot expects.")
    nodes = raw.get("nodes")
    if not isinstance(nodes, list):
        _fail("The menu has no list of use cases.")
    if len(nodes) > MAX_USE_CASES:
        _fail(f"A menu can have at most {MAX_USE_CASES} use cases.")
    seen_ids: set[str] = set()
    seen_flows: set[str] = set()

    def group(n: dict, depth: int) -> dict:
        label = _one_line(n.get("label"), LABEL_MAX)
        if not label:
            _fail(
                "Every use case and group needs a name."
                if depth > 1
                else "Every use case needs a name."
            )
        gid = str(n.get("id") or "").strip().lower()
        if not gid:
            gid = "g" + uuid.uuid4().hex[:8]
        if not ID_OK.match(gid):
            _fail(f"“{label}” has an internal id that is not allowed.")
        if gid in seen_ids:
            _fail(f"Two places in the menu are both called “{gid}” inside.")
        seen_ids.add(gid)
        out = {
            "id": gid,
            "label": label,
            "description": _one_line(n.get("description"), ROW_DESCRIPTION),
            "hidden": n.get("hidden") is True,
            "children": [],
        }
        kids = n.get("children") if n.get("children") is not None else []
        if not isinstance(kids, list):
            _fail(f"“{label}” has an unreadable list inside.")
        if len(kids) > MAX_CHILDREN:
            _fail(f"“{label}” can hold at most {MAX_CHILDREN} entries.")
        for k in kids:
            if not isinstance(k, dict):
                _fail(f"“{label}” has an entry that cannot be read.")
            if "children" in k and "flow" not in k:
                if depth + 1 >= MAX_LEVELS:
                    _fail(
                        f"“{label}” cannot hold another group: the menu goes three levels deep (use case, group, flow)."
                    )
                out["children"].append(group(k, depth + 1))
            else:
                out["children"].append(flow(k, label))
        return out

    def flow(n: dict, where: str) -> dict:
        key = str(n.get("flow") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{1,80}", key):
            _fail(f"“{where}” has a flow that is not valid.")
        if known_flows is not None and key not in known_flows:
            _fail(f"The flow “{key}” does not exist in this organisation.")
        if key in seen_flows:
            _fail(f"The flow “{key}” is placed twice. Put each flow in one place only.")
        seen_flows.add(key)
        out = {"flow": key, "hidden": n.get("hidden") is True}
        label = _one_line(n.get("label"), LABEL_MAX)
        if label:
            out["label"] = label
        desc = _one_line(n.get("description"), ROW_DESCRIPTION)
        if desc:
            out["description"] = desc
        return out

    for n in nodes:
        if not isinstance(n, dict) or "flow" in n:
            _fail("The top of the menu holds use cases; put flows inside one.")
    result = {
        "enabled": raw.get("enabled") is True,
        "nodes": [group(n, 1) for n in nodes],
        "show_unplaced": raw.get("show_unplaced") is not False,
    }
    only = raw.get("only_roles") or []
    if not isinstance(only, list) or not all(
        isinstance(r, str) and r.strip() for r in only
    ):
        _fail("The roles that see the menu must be a list of role names.")
    if only:
        result["only_roles"] = sorted({r.strip() for r in only})
    for k, size in WORD_MAX.items():
        v = _one_line(raw.get(k), size)
        if v:
            result[k] = v
    if result["enabled"] and not result["nodes"]:
        _fail("Add at least one use case before switching the menu on.")
    return result


def placed_flows(nodes) -> set[str]:
    """Every flow key named anywhere in the tree (hidden ones too: hiding is a choice, not 'not placed')."""
    found: set[str] = set()
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        if n.get("flow"):
            found.add(str(n["flow"]))
        found |= placed_flows(n.get("children"))
    return found


# ───────────────────────── what one person sees ─────────────────────────


def resolve(cfg: dict, allowed: list[dict]) -> list[dict]:
    """The tree for one person: `allowed` are the flows their role may use (menu.get_menu_workflows). Hidden entries, flows
    they may not use and groups left empty are gone. Each node: {"kind": "flow"|"group", "id", "title", "description",
    "children"?}. Flows nobody placed go under a last use case when the organisation wants that (show_unplaced)."""
    by_key = {w["intent_key"]: w for w in allowed}

    def build(nodes) -> list[dict]:
        out = []
        for n in nodes or []:
            if not isinstance(n, dict) or n.get("hidden"):
                continue
            if n.get("flow"):
                w = by_key.get(str(n["flow"]))
                if not w:
                    continue
                out.append(
                    {
                        "kind": "flow",
                        "id": w["intent_key"],
                        "title": _cut(n.get("label") or w["name"], ROW_TITLE),
                        "description": _cut(
                            n.get("description") or w.get("command_description"),
                            ROW_DESCRIPTION,
                        ),
                    }
                )
            else:
                kids = build(n.get("children"))
                if kids:
                    out.append(
                        {
                            "kind": "group",
                            "id": str(n.get("id") or ""),
                            "title": _cut(n.get("label"), ROW_TITLE),
                            "description": _cut(n.get("description"), ROW_DESCRIPTION),
                            "children": kids,
                        }
                    )
        return out

    tree = build(cfg.get("nodes"))
    if cfg.get("show_unplaced", True) is not False:
        placed = placed_flows(cfg.get("nodes"))
        extra = [
            {
                "kind": "flow",
                "id": w["intent_key"],
                "title": _cut(w["name"], ROW_TITLE),
                "description": _cut(w.get("command_description"), ROW_DESCRIPTION),
            }
            for w in allowed
            if w["intent_key"] not in placed
        ][:MAX_CHILDREN]
        if extra:
            tree.append(
                {
                    "kind": "group",
                    "id": OTHER_ID,
                    "title": _cut(words(cfg)["other_label"], ROW_TITLE),
                    "description": "",
                    "children": extra,
                }
            )
    return tree


def _find(nodes: list[dict], node_id: str, parent: str = TOP):
    for n in nodes:
        if n["kind"] == "group":
            if n["id"] == node_id:
                return n, parent
            hit = _find(n["children"], node_id, n["id"])
            if hit:
                return hit
    return None


def _collapsed(tree: list[dict]) -> bool:
    """One use case only: its list is the top of the menu, there is nothing to choose between."""
    return len(tree) == 1 and tree[0]["kind"] == "group"


def _row(n: dict) -> dict:
    return {
        "id": (PREFIX + n["id"]) if n["kind"] == "group" else n["id"],
        "title": n["title"],
        "description": n["description"],
        "opens": n["kind"] == "group",
    }


def _paged(
    rows: list[dict], page: int, node_id: str, more_label: str, taken: int
) -> tuple[list[dict], int, int]:
    """The rows of one page (10 in a message, `taken` of them already used by the Back row), with a More row when more
    follow. Returns (rows, page used, number of pages)."""
    room = PAGE_ROWS - taken
    if len(rows) <= room:
        return rows, 1, 1
    pages, start = [], 0
    while len(rows) - start > room:
        pages.append(rows[start : start + room - 1])
        start += room - 1
    pages.append(rows[start:])
    page = min(max(page, 1), len(pages))
    shown = list(pages[page - 1])
    if page < len(pages):
        shown.append(
            {
                "id": f"{PREFIX}{node_id}:p{page + 1}",
                "title": _cut(more_label, ROW_TITLE),
                "description": "",
                "opens": True,
            }
        )
    return shown, page, len(pages)


def view(tree: list[dict], cfg: dict, node_id: str = TOP, page: int = 1) -> dict | None:
    """One list message: {"title", "description", "rows", "page", "pages", "node"}; None when node_id is not a group of
    this person's tree. The top of the menu is node_id "" (a lone use case is shown straight away)."""
    w = words(cfg)
    if node_id == TOP and _collapsed(tree):
        node_id = tree[0]["id"]
    if node_id == TOP:
        title, description, nodes, back = "", "", tree, None
    else:
        hit = _find(tree, node_id)
        if not hit:
            return None
        node, parent = hit
        title, description, nodes = node["title"], node["description"], node["children"]
        back = None if (parent == TOP and _collapsed(tree)) else parent
    rows = [_row(n) for n in nodes]
    taken = 0
    if back is not None:
        taken = 1
    shown, page, pages = _paged(rows, page, node_id, w["more_label"], taken)
    if back is not None:
        shown = shown + [
            {
                "id": PREFIX + back,
                "title": _cut(w["back_label"], ROW_TITLE),
                "description": "",
                "opens": True,
                "back": True,
            }
        ]
    return {
        "node": node_id,
        "title": title,
        "description": description,
        "rows": shown,
        "page": page,
        "pages": pages,
        "button": w["button_label"],
    }


def sections_of(v: dict) -> list[dict]:
    """The sections a list message needs (the shape menu.build_menu_sections gives): one section of rows."""
    rows = [
        {"id": r["id"], "title": r["title"], "description": r["description"][:72]}
        for r in v["rows"]
    ]
    return (
        [{"title": _cut(v["title"] or "Menu", ROW_TITLE), "rows": rows}] if rows else []
    )


def parse(text: str) -> tuple[str, int] | None:
    """'menu:tickets:p2' -> ('tickets', 2); 'menu:' -> ('', 1); anything else None."""
    t = (text or "").strip()
    if not t.startswith(PREFIX):
        return None
    parts = t[len(PREFIX) :].split(":")
    node_id = parts[0]
    if node_id and not (ID_OK.match(node_id) or node_id == OTHER_ID):
        return None
    page = 1
    if len(parts) > 1:
        m = re.fullmatch(r"p(\d{1,3})", parts[1])
        if not m or len(parts) > 2:
            return None
        page = int(m.group(1))
    return node_id, page


# ───────────────────────── reading what is saved, for one person ─────────────────────────


async def _tree_for(user: dict, settings: dict | None = None):
    """(cfg, tree) for this person, or None when no menu is set up."""
    if settings is None:
        settings = await config_store.org_settings(user["source_key"], user["org_id"])
    cfg = config(settings)
    if not cfg:
        return None
    only = cfg.get("only_roles") or []
    if only and (user.get("role") or "") not in only:
        return None  # shown to some roles first (to try it out): everyone else keeps today's menu
    allowed = await menu.get_menu_workflows(user["org_id"], user)
    return cfg, resolve(cfg, allowed)


async def sections_for(user: dict) -> list[dict] | None:
    """The list menu (sections of rows) for the top of the menu, or None when no menu is set up (keep today's)."""
    try:
        found = await _tree_for(user)
        if found is None:
            return None
        cfg, tree = found
        v = view(tree, cfg, TOP)
        return sections_of(v) if v else []
    except Exception as e:  # today's menu is the fallback
        logger.warning(f"chat menu: could not be built ({type(e).__name__}): {e}")
        return None


async def open_view(user: dict, text: str) -> dict | None:
    """The answer to a tap on a row that opens a group: {"body", "button", "sections"}. None when the text is not such a
    tap or no menu is set up (the caller then carries on as usual). A group that is gone shows the top of the menu."""
    asked = parse(text)
    if asked is None:
        return None
    try:
        found = await _tree_for(user)
        if found is None:
            return None
        cfg, tree = found
        node_id, page = asked
        v = view(tree, cfg, node_id, page) or view(tree, cfg, TOP, 1)
        if not v:
            return None
        return {
            "body": v["description"] or v["title"] or "Menu",
            "button": v["button"],
            "sections": sections_of(v),
        }
    except Exception as e:
        logger.warning(f"chat menu: could not open a group ({type(e).__name__}): {e}")
        return None


# ───────────────────────── the WhatsApp Flow panel ─────────────────────────


def _flow_item(n: dict, level: int) -> dict:
    """One item of a Flow list on screen `level` (1 = MENU). A group opens the next list with its items as the payload."""
    item = {
        "id": n["id"],
        "main-content": {
            "title": _cut(n["title"], FLOW_TITLE),
            "description": _cut(n["description"], FLOW_DESCRIPTION),
        },
    }
    if n["kind"] == "flow":
        item["on-click-action"] = {
            "name": "navigate",
            "next": {"type": "screen", "name": "DONE"},
            "payload": {"workflow": n["id"]},
        }
    else:
        item["on-click-action"] = {
            "name": "navigate",
            "next": {"type": "screen", "name": FLOW_SCREENS[level]},
            "payload": {
                "items": [
                    _flow_item(c, level + 1) for c in n["children"][:MAX_CHILDREN]
                ]
            },
        }
    return item


def flow_data_for(tree: list[dict]) -> tuple[str, dict]:
    """(first screen, its data) for a person's tree in the nested shape the menu Flow's layout reads. ("", {}) when
    there is nothing to show or it would be too big for a panel (the caller sends the list menu instead)."""
    if not tree:
        return "", {}
    if _collapsed(tree):
        first, level, nodes = FLOW_SCREENS[1], 2, tree[0]["children"]
    else:
        first, level, nodes = FLOW_SCREENS[0], 1, tree
    data = {"items": [_flow_item(n, level) for n in nodes[:MAX_CHILDREN]]}
    if len(json.dumps(data, ensure_ascii=False)) > FLOW_DATA_MAX_BYTES:
        logger.warning("chat menu: too big for a panel, the list menu is used")
        return "", {}
    return first, data


async def flow_data(user: dict, settings: dict):
    """For flows.menu_data: None when no menu is set up; else (first screen, data), or ("", {}) for 'send the list menu'."""
    found = await _tree_for(user, settings)
    if found is None:
        return None
    try:
        return flow_data_for(found[1])
    except Exception as e:  # a hand-edited setting nested too deep: send the list menu
        logger.warning(f"chat menu: the panel data could not be made ({e})")
        return "", {}


def _lists(nodes: list[dict]) -> int:
    """How many list screens are needed to show these nodes and everything under their groups."""
    return 1 + max(
        (_lists(n["children"]) for n in nodes if n["kind"] == "group"), default=0
    )


def _item_schema(levels_left: int) -> dict:
    payload: dict = {"workflow": {"type": "string"}}
    if levels_left > 1:
        payload = {"items": {"type": "array", "items": _item_schema(levels_left - 1)}}
        payload["workflow"] = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "main-content": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
            "on-click-action": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "next": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "name": {"type": "string"},
                        },
                    },
                    "payload": {"type": "object", "properties": payload},
                },
            },
        },
    }


def _trim(items: list[dict], keep: int = 2) -> list[dict]:
    """A short example for a Flow screen: the first entries, and inside them the first entries again."""
    out = []
    for it in items[:keep]:
        it = json.loads(json.dumps(it))
        pl = it["on-click-action"]["payload"]
        if "items" in pl:
            pl["items"] = _trim(pl["items"], keep)
        out.append(it)
    return out


def flow_layout(cfg: dict, workflows: list[dict]) -> dict:
    """The Meta Flow layout (JSON) for this menu: one list screen per level the tree needs (MENU, then SECTION, then
    SUBSECTION) and a last screen, DONE, that hands the chosen flow back to the chat bot. The items themselves are not
    in it: they are sent with each person's menu (flow_data), so a person only sees what their role allows. `workflows` are
    all the organisation's flows (for the examples). Nothing is sent to Meta; the dashboard shows the JSON to copy."""
    full = resolve(cfg, workflows)
    first, example = flow_data_for(full)
    start = FLOW_SCREENS.index(first) if first else 0
    nodes = (full[0]["children"] if _collapsed(full) else full) if full else []
    count = min(_lists(nodes), len(FLOW_SCREENS) - start) if nodes else 1
    items = example.get("items") or [
        {
            "id": "example",
            "main-content": {"title": "Example", "description": "Replace me"},
            "on-click-action": {
                "name": "navigate",
                "next": {"type": "screen", "name": "DONE"},
                "payload": {"workflow": "example"},
            },
        }
    ]
    screens = []
    for idx in range(count):
        name = FLOW_SCREENS[start + idx]
        screens.append(
            {
                "id": name,
                "title": "Menu" if start + idx == 0 else "Choose",
                "data": {
                    "items": {
                        "type": "array",
                        "items": _item_schema(count - idx),
                        "__example__": _example_for_level(items, idx),
                    }
                },
                "layout": {
                    "type": "SingleColumnLayout",
                    "children": [
                        {
                            "type": "NavigationList",
                            "name": "choices",
                            "list-items": "${data.items}",
                        }
                    ],
                },
            }
        )
    screens.append(
        {
            "id": "DONE",
            "title": "Start",
            "terminal": True,
            "success": True,
            "data": {"workflow": {"type": "string", "__example__": "example"}},
            "layout": {
                "type": "SingleColumnLayout",
                "children": [
                    {"type": "TextBody", "text": "Ready to start this?"},
                    {
                        "type": "Footer",
                        "label": "Start",
                        "on-click-action": {
                            "name": "complete",
                            "payload": {"workflow": "${data.workflow}"},
                        },
                    },
                ],
            },
        }
    )
    return {"version": "6.2", "screens": screens}


def _example_for_level(items: list[dict], depth: int) -> list[dict]:
    """The example items one `depth` levels down the first group of `items` (a screen's own example)."""
    cur = _trim(items)
    for _ in range(depth):
        nxt = None
        for it in cur:
            pl = it["on-click-action"]["payload"]
            if pl.get("items"):
                nxt = pl["items"]
                break
        if nxt is None:
            break
        cur = nxt
    return cur
