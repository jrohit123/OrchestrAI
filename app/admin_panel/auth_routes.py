"""The sign-in endpoints, under /admin/_auth, and what a super admin does with accounts.

Sign up is only for people a super admin has invited (an account that is "invited"). A person
types their email, gets a 6-digit code by email, and chooses a password. Every later sign-in, admin
or super admin, is email and password only; a code is asked for again only at "Forgot password".
A code request always gets the same answer, whether or not the address is known."""

from __future__ import annotations

import time
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
)
from pydantic import BaseModel, Field

from app.admin_panel import auth, auth_accounts, auth_mail
from app.admin_panel.auth import (
    CODE_MINUTES,
    CODE_WINDOW,
    SESSION_COOKIE,
    SIGNIN_WINDOW,
    WRONG,
    Account,
    audit,
    check_code,
    check_password,
    clean_code,
    clean_email,
    clear_session_cookie,
    find_by_email,
    issue_code,
    need_panel_header,
    note_signed_in,
    register_failure,
    require_account,
    require_super,
    set_session_cookie,
    start_session,
    throttle,
    verify_password,
)
from app.admin_panel.auth_log import LOG_RANGE_PATTERN, LOG_VIEW_PATTERN, read_log
from app.db import fetch_one, get_all_source_keys, routing_pool
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)


def _no_store(response: Response) -> None:
    """Nothing the sign-in endpoints say is kept by a browser or a proxy."""
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/admin/_auth", tags=["admin-sign-in"], dependencies=[Depends(_no_store)]
)

Super = Annotated[Account, Depends(require_super)]

# ── organisation names (public: the sign-in page shows them) ─────────────────

_NAME_SECONDS = 300
_names: dict[str, tuple[float, str]] = {}


async def org_name(source_key: str) -> str:
    hit = _names.get(source_key)
    if hit and time.monotonic() - hit[0] < _NAME_SECONDS:
        return hit[1]
    try:
        row = await fetch_one(
            "SELECT name FROM orgs WHERE is_active = true LIMIT 1",
            source_key=source_key,
        )
        name = row["name"] if row else source_key
    except Exception as e:
        logger.warning(f"could not read the name of '{source_key}': {e!r}")
        return source_key
    _names[source_key] = (time.monotonic(), name)
    return name


def public_base(request: Request) -> str:
    proto = (
        request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        or request.url.scheme
    )
    host = (
        request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        or request.headers.get("host")
        or request.url.netloc
    )
    return f"{proto}://{host}"


async def me_of(account: Account) -> dict:
    known = await get_all_source_keys()
    keys = known if account.is_super else [k for k in account.source_keys if k in known]
    return {
        "id": account.id,
        "name": account.name,
        "email": account.email,
        "level": account.level,
        "orgs": [{"key": k, "name": await org_name(k)} for k in sorted(keys)],
    }


@router.get("/org/{org_slug}")
async def org_info(org_slug: str):
    """Only what the sign-in page shows: the organisation's name."""
    if org_slug not in await get_all_source_keys():
        raise HTTPException(status_code=404, detail="We do not know that organisation.")
    return {"key": org_slug, "name": await org_name(org_slug)}


@router.get("/me")
async def me(account: Annotated[Account, Depends(require_account)]):
    return {"account": await me_of(account)}


# ── sign in ──────────────────────────────────────────────────────────────────


class SignInBody(BaseModel):
    email: str = Field(max_length=300)
    password: str = Field(max_length=1000)


@router.post("/sign-in")
async def sign_in(body: SignInBody, request: Request, response: Response):
    need_panel_header(request)
    throttle(SIGNIN_WINDOW, request)
    email = clean_email(body.email)
    found = await find_by_email(email) if email else None
    if found is not None and found["locked"]:
        minutes = max(1, -(-found["lock_seconds"] // 60))
        await audit(
            "locked_out",
            request=request,
            account_id=str(found["id"]),
            email=email,
            ok=False,
            detail="Tried to sign in while locked",
        )
        raise HTTPException(
            status_code=429,
            detail=f"Too many wrong tries. This account is locked for {minutes} more minute(s).",
        )
    right = await verify_password(
        found["password_hash"] if found else None, body.password
    )
    if found is None or not right:
        locked = False
        if found is not None:
            locked = await register_failure(str(found["id"]))
        await audit(
            "sign_in_failed",
            request=request,
            account_id=str(found["id"]) if found else None,
            email=email or (body.email or "")[:200],
            ok=False,
            detail="Wrong password" if found else "Unknown email",
        )
        if locked:
            raise HTTPException(
                status_code=429,
                detail=f"Too many wrong tries. This account is locked for {auth.LOCK_MINUTES} minutes.",
            )
        raise HTTPException(status_code=401, detail=WRONG)
    account_id = str(found["id"])
    if found["status"] != "active":
        await audit(
            "sign_in_refused",
            request=request,
            account_id=account_id,
            email=email,
            ok=False,
            detail=f"Account is {found['status']}",
        )
        raise HTTPException(
            status_code=403,
            detail="This account is switched off. Ask a super admin to switch it on.",
        )
    await note_signed_in(account_id)
    token = await start_session(account_id, request)
    set_session_cookie(response, request, token)
    await audit(
        "sign_in",
        request=request,
        account_id=account_id,
        email=email,
        detail="Signed in",
    )
    account = Account(
        id=account_id,
        email=found["email"],
        name=found["name"],
        level=found["level"],
        source_keys=tuple(found["source_keys"] or ()),
        status=found["status"],
    )
    return {"ok": True, "account": await me_of(account)}


@router.post("/sign-out")
async def sign_out(request: Request, response: Response):
    need_panel_header(request)
    token = request.cookies.get(SESSION_COOKIE)
    account = await auth.account_for_session(token)
    await auth.end_session(token)
    clear_session_cookie(response)
    if account is not None:
        await audit(
            "sign_out",
            request=request,
            account_id=account.id,
            email=account.email,
            detail="Signed out",
        )
    return {"ok": True}


# ── sign up and forgot password ──────────────────────────────────────────────

ASKED = {
    "ok": True,
    "message": "If that address is on the list, a code is on its way. It works for "
    f"{CODE_MINUTES} minutes.",
}


class EmailBody(BaseModel):
    email: str = Field(max_length=300)


class FinishBody(BaseModel):
    email: str = Field(max_length=300)
    code: str = Field(max_length=40)
    password: str = Field(max_length=1000)


async def _mail_code(email: str, name: str, kind: str, code: str) -> None:
    await auth_mail.send_code(email, name, kind, code, CODE_MINUTES)


@router.post("/sign-up/code")
async def sign_up_code(body: EmailBody, request: Request, later: BackgroundTasks):
    need_panel_header(request)
    throttle(CODE_WINDOW, request)
    email = clean_email(body.email)
    found = await find_by_email(email) if email else None
    if found is None or found["status"] == "off":
        await audit(
            "sign_up_unknown",
            request=request,
            email=email or (body.email or "")[:200],
            ok=False,
            detail="Asked for a sign-up code without an invitation",
        )
        return ASKED
    account_id = str(found["id"])
    if found["status"] == "invited":
        code, _ = await issue_code(account_id, "signup")
        if code is not None:
            later.add_task(_mail_code, email, found["name"], "signup", code)
            await audit(
                "code_sent",
                request=request,
                account_id=account_id,
                email=email,
                detail="Sign-up code emailed",
            )
    else:  # already has a password: tell the owner of the address, quietly
        code, _ = await issue_code(account_id, "signup")
        if code is not None:
            later.add_task(auth_mail.send_already_signed_up, email, found["name"])
    return ASKED


GENERIC_CODE = "That code is not right, or it has expired. Ask for a new one."


async def _refuse_code(outcome: str) -> HTTPException:
    """One answer for every way a code can fail (wrong, expired, never sent, address not known),
    so nobody can learn from it whether an address was invited."""
    return HTTPException(status_code=400, detail=GENERIC_CODE)


@router.post("/sign-up")
async def sign_up(body: FinishBody, request: Request, response: Response):
    need_panel_header(request)
    throttle(SIGNIN_WINDOW, request)
    email = clean_email(body.email)
    found = await find_by_email(email) if email else None
    code = clean_code(body.code)
    if found is None or found["status"] != "invited" or code is None:
        raise await _refuse_code("none")
    account_id = str(found["id"])
    # the code is checked first, without using it up, so the password rules below are only
    # ever shown to the person who holds the code (a stranger learns nothing about the address)
    outcome = await check_code(account_id, "signup", code, consume=False)
    if outcome != "ok":
        await audit(
            "sign_up_failed",
            request=request,
            account_id=account_id,
            email=email,
            ok=False,
            detail=f"Code: {outcome}",
        )
        raise await _refuse_code(outcome)
    problem = check_password(body.password, found["email"], found["name"])
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    await check_code(account_id, "signup", code)  # now it is used up
    await auth_accounts.set_password(account_id, body.password)
    token = await start_session(account_id, request)
    set_session_cookie(response, request, token)
    await note_signed_in(account_id)
    await audit(
        "sign_up",
        request=request,
        account_id=account_id,
        email=email,
        detail="Chose a password and signed in",
    )
    account = Account(
        id=account_id,
        email=found["email"],
        name=found["name"],
        level=found["level"],
        source_keys=tuple(found["source_keys"] or ()),
        status="active",
    )
    return {"ok": True, "account": await me_of(account)}


@router.post("/forgot/code")
async def forgot_code(body: EmailBody, request: Request, later: BackgroundTasks):
    need_panel_header(request)
    throttle(CODE_WINDOW, request)
    email = clean_email(body.email)
    found = await find_by_email(email) if email else None
    if found is None or found["status"] != "active":
        await audit(
            "reset_unknown",
            request=request,
            email=email or (body.email or "")[:200],
            ok=False,
            detail="Asked for a reset code for an unknown or inactive address",
        )
        return ASKED
    code, _ = await issue_code(str(found["id"]), "reset")
    if code is not None:
        later.add_task(_mail_code, email, found["name"], "reset", code)
        await audit(
            "code_sent",
            request=request,
            account_id=str(found["id"]),
            email=email,
            detail="Reset code emailed",
        )
    return ASKED


@router.post("/forgot")
async def forgot(body: FinishBody, request: Request):
    need_panel_header(request)
    throttle(SIGNIN_WINDOW, request)
    email = clean_email(body.email)
    found = await find_by_email(email) if email else None
    code = clean_code(body.code)
    if found is None or found["status"] != "active" or code is None:
        raise await _refuse_code("none")
    account_id = str(found["id"])
    outcome = await check_code(account_id, "reset", code, consume=False)
    if outcome != "ok":
        await audit(
            "reset_failed",
            request=request,
            account_id=account_id,
            email=email,
            ok=False,
            detail=f"Code: {outcome}",
        )
        raise await _refuse_code(outcome)
    problem = check_password(body.password, found["email"], found["name"])
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    await check_code(account_id, "reset", code)  # now it is used up
    await auth_accounts.set_password(account_id, body.password)
    await audit(
        "password_reset",
        request=request,
        account_id=account_id,
        email=email,
        detail="Chose a new password; every browser was signed out",
    )
    return {"ok": True}


# ── super admins: organisations, accounts, activity ──────────────────────────


@router.get("/orgs")
async def orgs(_: Super):
    sources = await routing_pool().fetch(
        "SELECT source_key, messaging_channel FROM data_sources ORDER BY source_key"
    )
    accounts = await auth_accounts.list_accounts()
    out = []
    for s in sources:
        key = s["source_key"]
        people = None
        try:
            row = await fetch_one(
                "SELECT count(*) AS n FROM users WHERE is_active", source_key=key
            )
            people = row["n"]
        except Exception as e:
            logger.warning(f"could not count the people of '{key}': {e!r}")
        out.append(
            {
                "key": key,
                "name": await org_name(key),
                "channel": s["messaging_channel"],
                "people": people,
                "admins": [
                    {"id": a["id"], "name": a["name"], "status": a["status"]}
                    for a in accounts
                    if a["level"] == "admin" and key in a["orgs"]
                ],
            }
        )
    return {"orgs": out}


@router.get("/accounts")
async def accounts(_: Super):
    return {"accounts": await auth_accounts.list_accounts()}


@router.get("/overview")
async def overview(_: Super):
    orgs_found = await orgs(_)
    people = [o["people"] for o in orgs_found["orgs"] if o["people"] is not None]
    listed = await auth_accounts.list_accounts()
    recent = await routing_pool().fetch(
        "SELECT p.at, COALESCE(a.name, p.email, 'Someone') AS who, p.action, p.ok, p.detail "
        "FROM panel_audit p LEFT JOIN panel_accounts a ON a.id = p.account_id "
        "ORDER BY p.id DESC LIMIT 8"
    )
    return {
        "numbers": {
            "organisations": len(orgs_found["orgs"]),
            "people": sum(people),
            "admins": sum(
                1 for a in listed if a["level"] == "admin" and a["status"] == "active"
            ),
            "super_admins": sum(
                1 for a in listed if a["level"] == "super" and a["status"] == "active"
            ),
        },
        "waiting": [a for a in listed if a["status"] == "invited"],
        "locked": [a for a in listed if a["locked"]],
        "recent": [
            {
                "at": r["at"].isoformat(),
                "who": r["who"],
                "action": r["action"],
                "ok": r["ok"],
                "detail": r["detail"],
            }
            for r in recent
        ],
    }


@router.get("/activity")
async def activity(
    _: Super,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 40,
    view: Annotated[str, Query(pattern=LOG_VIEW_PATTERN)] = "all",
    q: Annotated[str, Query(max_length=100)] = "",
    org: Annotated[str, Query(max_length=100)] = "",
    range_: Annotated[str, Query(alias="range", pattern=LOG_RANGE_PATTERN)] = "all",
):
    """The sign-in log, newest first. The buttons (view), the search, the organisation and the range
    narrow it; counts say how many lines each button would show under the same search, organisation
    and range."""
    got = await read_log(
        routing_pool(),
        view=view,
        q=q,
        org=org.strip(),
        range_=range_,
        page=page,
        page_size=page_size,
    )
    keys = await get_all_source_keys()
    return {
        **got,
        "page": page,
        "page_size": page_size,
        "orgs": [{"key": k, "name": await org_name(k)} for k in sorted(keys)],
    }


class GiveBody(BaseModel):
    source_key: str = Field(max_length=100)
    user_id: UUID


@router.post("/accounts/give-access")
async def give_access(body: GiveBody, request: Request, by: Super):
    if body.source_key not in await get_all_source_keys():
        raise HTTPException(status_code=404, detail="We do not know that organisation.")
    person = await fetch_one(
        "SELECT name, email, is_active FROM users WHERE id = $1",
        body.user_id,
        source_key=body.source_key,
    )
    if person is None:
        raise HTTPException(status_code=404, detail="That person was not found.")
    email = clean_email(person["email"])
    if email is None:
        raise HTTPException(
            status_code=400,
            detail="This person has no email address on file. Add one under People first.",
        )
    if not person["is_active"]:
        raise HTTPException(
            status_code=409, detail="This person is switched off. Switch them on first."
        )
    where = await org_name(body.source_key)
    account, created = await auth_accounts.give_access(
        body.source_key, email, person["name"], by, request, where
    )
    emailed = created and await auth_mail.send_invite(
        email,
        person["name"],
        by.name,
        where,
        f"{public_base(request)}/admin/{body.source_key}",
    )
    return {"account": account, "created": created, "emailed": bool(emailed)}


class OrgBody(BaseModel):
    source_key: str = Field(max_length=100)


@router.post("/accounts/{account_id}/take-access")
async def take_access(account_id: UUID, body: OrgBody, request: Request, by: Super):
    return {
        "account": await auth_accounts.take_access(
            str(account_id), body.source_key, by, request
        )
    }


class SwitchBody(BaseModel):
    on: bool


@router.post("/accounts/{account_id}/switch")
async def switch(account_id: UUID, body: SwitchBody, request: Request, by: Super):
    return {
        "account": await auth_accounts.switch(str(account_id), body.on, by, request)
    }


@router.post("/accounts/{account_id}/sign-out")
async def sign_out_everywhere(account_id: UUID, request: Request, by: Super):
    return {
        "account": await auth_accounts.sign_out_everywhere(str(account_id), by, request)
    }


@router.post("/accounts/{account_id}/invite-again")
async def invite_again(account_id: UUID, request: Request, by: Super):
    listed = {a["id"]: a for a in await auth_accounts.list_accounts()}
    found = listed.get(str(account_id))
    if found is None:
        raise HTTPException(status_code=404, detail="That account was not found.")
    if found["status"] != "invited":
        raise HTTPException(
            status_code=409, detail="This person has already signed up."
        )
    if found["level"] == "super" or not found["orgs"]:
        where, link = "OrchestrAI", f"{public_base(request)}/admin"
    else:
        where = await org_name(found["orgs"][0])
        link = f"{public_base(request)}/admin/{found['orgs'][0]}"
    emailed = await auth_mail.send_invite(
        found["email"], found["name"], by.name, where, link
    )
    await audit(
        "invite_again",
        request=request,
        account_id=found["id"],
        email=found["email"],
        ok=bool(emailed),
        detail=f"{by.name} sent the invitation again",
    )
    return {"account": found, "emailed": bool(emailed)}


class SuperBody(BaseModel):
    email: str = Field(max_length=300)
    name: str = Field(min_length=1, max_length=120)


@router.post("/super-admins")
async def add_super_admin(body: SuperBody, request: Request, by: Super):
    email = clean_email(body.email)
    if email is None:
        raise HTTPException(
            status_code=400, detail="That email address does not look right."
        )
    account = await auth_accounts.add_super(email, body.name.strip(), by, request)
    emailed = await auth_mail.send_invite(
        email, account["name"], by.name, "OrchestrAI", f"{public_base(request)}/admin"
    )
    return {"account": account, "emailed": bool(emailed)}
