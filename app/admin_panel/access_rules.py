"""Which dashboard calls an admin may make. A super admin may make all of them.

Every call under /admin/{org}/api/v2 is listed here once, as (method, path after that prefix), in
exactly one of two sets. A call that is in neither is refused for an admin (deny by default), and
tests/test_panel_access.py fails when a real call is missing from both sets, so a new call can never
be added without somebody deciding who may use it.
"""

from fastapi import Request

PREFIX = "/admin/{org_slug}/api/v2"

# What an admin needs for Home, Cases and People.
ADMIN_CALLS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/bootstrap"),
        ("GET", "/nav-hints"),
        ("GET", "/lookups"),
        ("GET", "/overview"),
        ("GET", "/logo"),
        ("GET", "/cases"),
        ("GET", "/cases/{case_id}"),
        ("GET", "/cases/{case_id}/photos/{photo_id}"),
        ("POST", "/cases/{case_id}/assign"),
        ("GET", "/people"),
        ("GET", "/people/{user_id}"),
        ("PATCH", "/people/{user_id}"),
        ("POST", "/people/import/preview"),
        ("POST", "/people/import/commit"),
        ("POST", "/ask"),
    }
)

# Everything else: flows, the chat bot, rules, roles and access, settings, the chat log, adding people.
SUPER_CALLS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/activity"),
        ("GET", "/activity/session"),
        ("GET", "/categories"),
        ("POST", "/categories"),
        ("DELETE", "/categories/{category_id}"),
        ("PATCH", "/categories/{category_id}"),
        ("GET", "/chats"),
        ("GET", "/events"),
        ("GET", "/grants"),
        ("POST", "/grants"),
        ("POST", "/grants/{grant_id}/revoke"),
        ("GET", "/instructions"),
        ("GET", "/instructions/assembled"),
        ("DELETE", "/instructions/{key}"),
        ("PUT", "/instructions/{key}"),
        ("POST", "/instructions/{key}/check"),
        ("GET", "/instructions/{key}/history"),
        ("POST", "/logo"),
        ("GET", "/messages"),
        ("DELETE", "/messages/{key}"),
        ("PUT", "/messages/{key}"),
        ("POST", "/messages/{key}/check"),
        ("GET", "/messages/{key}/history"),
        ("GET", "/org-settings"),
        ("PUT", "/org-settings"),
        ("POST", "/people"),
        ("PATCH", "/people/{user_id}/homes/{resident_id}"),
        ("GET", "/roles"),
        ("POST", "/roles"),
        ("DELETE", "/roles/{role_id}"),
        ("PATCH", "/roles/{role_id}"),
        ("GET", "/rules"),
        ("POST", "/rules"),
        ("POST", "/rules/test"),
        ("DELETE", "/rules/{rule_id}"),
        ("PUT", "/rules/{rule_id}"),
        ("POST", "/rules/{rule_id}/active"),
        ("GET", "/seats"),
        ("POST", "/seats"),
        ("DELETE", "/seats/{seat_id}"),
        ("PATCH", "/seats/{seat_id}"),
        ("GET", "/seats/{seat_id}/history"),
        ("PUT", "/seats/{seat_id}/holder"),
        ("POST", "/sessions/clear"),
        ("GET", "/status"),
        ("GET", "/whatsapp-flows"),
        ("POST", "/whatsapp-flows"),
        ("PUT", "/whatsapp-flows/account"),
        ("PUT", "/whatsapp-flows/use"),
        ("GET", "/whatsapp-flows/{flow_id}"),
        ("DELETE", "/whatsapp-flows/{flow_id}"),
        ("PUT", "/whatsapp-flows/{flow_id}/json"),
        ("POST", "/whatsapp-flows/{flow_id}/send-test"),
        ("POST", "/whatsapp-flows/{flow_id}/publish"),
        ("POST", "/whatsapp-flows/{flow_id}/copy"),
        ("GET", "/studio/catalog"),
        ("POST", "/studio/chat"),
        ("GET", "/studio/people"),
        ("POST", "/studio/technical"),
        ("POST", "/studio/try"),
        ("POST", "/studio/validate"),
        ("GET", "/targets"),
        ("PUT", "/targets"),
        ("GET", "/workflows"),
        ("POST", "/workflows"),
        ("DELETE", "/workflows/{workflow_id}"),
        ("GET", "/workflows/{workflow_id}"),
        ("POST", "/workflows/{workflow_id}/active"),
        ("PUT", "/workflows/{workflow_id}/definition"),
        ("PUT", "/workflows/{workflow_id}/layout"),
        ("POST", "/workflows/{workflow_id}/restore"),
        ("PUT", "/workflows/{workflow_id}/roles"),
        ("GET", "/workflows/{workflow_id}/versions/{version}"),
    }
)


def call_of(request: Request) -> tuple[str, str] | None:
    """(method, path after the prefix) of the call being made, or None when it cannot be told."""
    route = request.scope.get("route")
    path = getattr(route, "path", "") or ""
    if not path.startswith(PREFIX):
        return None
    return request.method, path[len(PREFIX) :]


def admin_may(request: Request) -> bool:
    return call_of(request) in ADMIN_CALLS
