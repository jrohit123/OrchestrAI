"""Dashboard sign-in: accounts, passwords, emailed codes, sessions and the log.

Everything here lives in the routing (control) database (migrations/control/control-0001_panel_login.sql)
and never touches a client database. The routes are in auth_routes.py. The one place that turns a
request into a signed-in person is `require_account`; `get_ctx` (common.py) depends on it, so every
dashboard data call is behind it.

What is stored: a password only as a slow salted hash; a session secret and an emailed code only as
a hash. The browser keeps the session secret in an HttpOnly cookie.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

from app.db import routing_pool
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

# ── the rules, in one place ──────────────────────────────────────────────────

SESSION_COOKIE = "panel_session"
SESSION_DAYS = 7  # a session never lasts longer than this
IDLE_HOURS = {"admin": 12, "super": 4}  # ...and ends sooner when it is not used
CODE_MINUTES = 10
CODE_TRIES = 5
CODE_WAIT_SECONDS = 60  # between two codes for the same person
WRONG_TRIES = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 10
MAX_PASSWORD = 200
TOUCH_SECONDS = 60  # "last used" is written at most this often
CODE_KINDS = ("signup", "reset", "signin")

WRONG = "Wrong email or password. First time here? Choose Sign up."

# ── people ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    name: str
    level: str  # 'super' or 'admin'
    source_keys: tuple[str, ...]
    status: str

    @property
    def is_super(self) -> bool:
        return self.level == "super"

    def may_open(self, source_key: str) -> bool:
        return self.is_super or source_key in self.source_keys


def account_from(row) -> Account:
    return Account(
        id=str(row["id"]),
        email=row["email"],
        name=row["name"],
        level=row["level"],
        source_keys=tuple(row["source_keys"] or ()),
        status=row["status"],
    )


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_email(text: str | None) -> str | None:
    email = (text or "").strip().lower()
    if not email or len(email) > 254 or not _EMAIL.match(email):
        return None
    return email


def mask_email(email: str) -> str:
    """Enough to recognise your own address, not enough to learn someone else's."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}•••@{domain}"


# ── passwords ────────────────────────────────────────────────────────────────

_SCRYPT = (15, 8, 1)  # log2 of N, r, p: about 32 MiB and 0.1 second for one hash
_SCRYPT_SLOTS = threading.BoundedSemaphore(3)  # at most three at once (memory)
_COMMON = {
    "password",
    "password1",
    "password12",
    "password123",
    "password1234",
    "1234567890",
    "12345678910",
    "qwertyuiop",
    "qwerty12345",
    "iloveyou123",
    "welcome123",
    "admin12345",
    "letmein1234",
    "orchestrai",
    "orchestrai1",
    "orchestrai123",
}


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _scrypt(password: str, salt: bytes, log_n: int, r: int, p: int) -> bytes:
    with _SCRYPT_SLOTS:
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=1 << log_n,
            r=r,
            p=p,
            maxmem=128 * 1024 * 1024,
            dklen=32,
        )


def hash_password_sync(password: str) -> str:
    log_n, r, p = _SCRYPT
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, log_n, r, p)
    return f"scrypt${log_n}${r}${p}${_b64(salt)}${_b64(digest)}"


def verify_password_sync(stored: str | None, password: str) -> bool:
    """True when the password matches. With nothing stored it does the same amount of work and
    says no, so an unknown address and a wrong password take equally long."""
    if not stored:
        _scrypt(password, b"\0" * 16, *_SCRYPT)
        return False
    try:
        scheme, log_n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        candidate = _scrypt(
            password, base64.b64decode(salt), int(log_n), int(r), int(p)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(hash_password_sync, password)


async def verify_password(stored: str | None, password: str) -> bool:
    return await asyncio.to_thread(verify_password_sync, stored, password[:1000])


def check_password(password: str, email: str = "", name: str = "") -> str | None:
    """A plain sentence when the password is not acceptable, else None."""
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return f"Use at most {MAX_PASSWORD} characters."
    lowered = password.strip().lower()
    mine = {email.lower(), email.split("@")[0].lower(), name.strip().lower()} - {""}
    if lowered in _COMMON or lowered in mine:
        return "That password is too easy to guess. Choose another."
    if len(set(lowered)) < 4:
        return "That password is too easy to guess. Choose another."
    return None


# ── slowing people down ──────────────────────────────────────────────────────


class _Window:
    """At most `limit` hits per `seconds` for each key (kept in memory, per copy of the app)."""

    def __init__(self, limit: int, seconds: int):
        self.limit, self.seconds = limit, seconds
        self.hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        if len(self.hits) > 5000:
            self.hits = {
                k: q for k, q in self.hits.items() if q and now - q[-1] < self.seconds
            }
        queue = self.hits.setdefault(key, deque())
        while queue and now - queue[0] > self.seconds:
            queue.popleft()
        if len(queue) >= self.limit:
            return False
        queue.append(now)
        return True


SIGNIN_WINDOW = _Window(30, 600)  # sign-in attempts per address
CODE_WINDOW = _Window(10, 600)  # code requests per address


def reset_limits() -> None:
    SIGNIN_WINDOW.hits.clear()
    CODE_WINDOW.hits.clear()


def client_info(request: Request) -> tuple[str, str]:
    """The caller's address and browser, for the log. Behind the host's proxy the last entry of
    X-Forwarded-For is the one the proxy itself saw."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        ip = forwarded.split(",")[-1].strip()
    else:
        ip = request.client.host if request.client else ""
    return ip[:64], (request.headers.get("user-agent") or "")[:200]


def throttle(window: _Window, request: Request) -> None:
    ip, _ = client_info(request)
    if not window.allow(ip or "unknown"):
        raise HTTPException(
            status_code=429, detail="Too many tries from here. Wait a few minutes."
        )


# ── the log ──────────────────────────────────────────────────────────────────


async def audit(
    action: str,
    *,
    request: Request | None = None,
    account_id: str | None = None,
    email: str | None = None,
    ok: bool = True,
    source_key: str | None = None,
    detail: str | None = None,
) -> None:
    """One line in panel_audit. A failure to write it is logged, never raised: the log must not
    be the reason someone cannot sign in."""
    ip, agent = client_info(request) if request is not None else (None, None)
    try:
        await routing_pool().execute(
            "INSERT INTO panel_audit (account_id, email, action, ok, source_key, detail, ip, agent) "
            "VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8)",
            account_id,
            email,
            action,
            ok,
            source_key,
            detail,
            ip,
            agent,
        )
    except Exception as e:
        logger.error(f"panel audit write failed: {e!r}")


# ── accounts ─────────────────────────────────────────────────────────────────

_SIGNIN_ROW = (
    "SELECT id, email, name, level, source_keys, status, password_hash, "
    "(locked_until IS NOT NULL AND locked_until > now()) AS locked, "
    "GREATEST(0, EXTRACT(EPOCH FROM (locked_until - now())))::int AS lock_seconds "
    "FROM panel_accounts "
)


async def find_by_email(email: str) -> dict | None:
    row = await routing_pool().fetchrow(_SIGNIN_ROW + "WHERE email = $1", email)
    return dict(row) if row else None


async def get_account(account_id: str) -> Account | None:
    row = await routing_pool().fetchrow(
        "SELECT id, email, name, level, source_keys, status FROM panel_accounts WHERE id = $1::uuid",
        account_id,
    )
    return account_from(row) if row else None


async def register_failure(account_id: str) -> bool:
    """Count a wrong password or code. True when this try locked the account."""
    async with routing_pool().acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT wrong_tries FROM panel_accounts WHERE id = $1::uuid FOR UPDATE",
            account_id,
        )
        if row is None:
            return False
        tries = row["wrong_tries"] + 1
        locked = tries >= WRONG_TRIES
        await conn.execute(
            "UPDATE panel_accounts SET wrong_tries = $2, updated_at = now(), "
            "locked_until = CASE WHEN $3 THEN now() + make_interval(mins => $4) ELSE NULL END "
            "WHERE id = $1::uuid",
            account_id,
            0 if locked else tries,
            locked,
            LOCK_MINUTES,
        )
        return locked


async def note_signed_in(account_id: str) -> None:
    await routing_pool().execute(
        "UPDATE panel_accounts SET wrong_tries = 0, locked_until = NULL, "
        "last_sign_in = now(), updated_at = now() WHERE id = $1::uuid",
        account_id,
    )


# ── emailed codes ────────────────────────────────────────────────────────────


def new_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def _code_hash(account_id: str, kind: str, code: str) -> str:
    return hashlib.sha256(f"{account_id}:{kind}:{code}".encode()).hexdigest()


def clean_code(text: str | None) -> str | None:
    digits = re.sub(r"\D", "", text or "")
    return digits if len(digits) == 6 else None


async def issue_code(account_id: str, kind: str) -> tuple[str | None, int]:
    """A fresh 6-digit code that replaces any earlier one of this kind. Returns (code, 0), or
    (None, seconds) when a code was sent too recently."""
    assert kind in CODE_KINDS
    async with routing_pool().acquire() as conn, conn.transaction():
        wait = await conn.fetchval(
            "SELECT GREATEST(0, $3::int - EXTRACT(EPOCH FROM (now() - max(created_at))))::int "
            "FROM panel_keys WHERE account_id = $1::uuid AND kind = $2",
            account_id,
            kind,
            CODE_WAIT_SECONDS,
        )
        if wait:
            return None, wait
        await conn.execute(
            "DELETE FROM panel_keys WHERE account_id = $1::uuid AND kind = $2",
            account_id,
            kind,
        )
        code = new_code()
        await conn.execute(
            "INSERT INTO panel_keys (account_id, kind, key_hash, expires_at) "
            "VALUES ($1::uuid, $2, $3, now() + make_interval(mins => $4))",
            account_id,
            kind,
            _code_hash(account_id, kind, code),
            CODE_MINUTES,
        )
        return code, 0


async def check_code(
    account_id: str, kind: str, code: str, *, consume: bool = True
) -> str:
    """'ok' (and the code is used up, unless consume is False), 'wrong', 'expired', 'none' or
    'too_many'. A wrong code counts as a try; five tries kill the code."""
    assert kind in CODE_KINDS
    async with routing_pool().acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT id, key_hash, tries, expires_at > now() AS fresh FROM panel_keys "
            "WHERE account_id = $1::uuid AND kind = $2 AND used_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
            account_id,
            kind,
        )
        if row is None:
            return "none"
        if not row["fresh"]:
            return "expired"
        if row["tries"] >= CODE_TRIES:
            return "too_many"
        if hmac.compare_digest(row["key_hash"], _code_hash(account_id, kind, code)):
            if consume:
                await conn.execute(
                    "UPDATE panel_keys SET used_at = now() WHERE id = $1", row["id"]
                )
            return "ok"
        await conn.execute(
            "UPDATE panel_keys SET tries = tries + 1 WHERE id = $1", row["id"]
        )
        return "wrong"


# ── sessions ─────────────────────────────────────────────────────────────────


def _session_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def start_session(account_id: str, request: Request) -> str:
    token = secrets.token_urlsafe(32)
    ip, agent = client_info(request)
    await routing_pool().execute(
        "INSERT INTO panel_keys (account_id, kind, key_hash, expires_at, last_used, ip, agent) "
        "VALUES ($1::uuid, 'session', $2, now() + make_interval(days => $3), now(), $4, $5)",
        account_id,
        _session_hash(token),
        SESSION_DAYS,
        ip,
        agent,
    )
    return token


async def account_for_session(token: str | None) -> Account | None:
    """Who this cookie belongs to, or None. The account is read fresh every time, so switching
    someone off or taking an organisation away works on their very next click."""
    if not token or len(token) > 200:
        return None
    row = await routing_pool().fetchrow(
        "SELECT k.id AS key_id, k.expires_at > now() AS fresh, "
        "now() - COALESCE(k.last_used, k.created_at) AS idle, "
        "now() - COALESCE(k.last_used, k.created_at) > make_interval(secs => $2::int) AS stale, "
        "a.id, a.email, a.name, a.level, a.source_keys, a.status "
        "FROM panel_keys k JOIN panel_accounts a ON a.id = k.account_id "
        "WHERE k.kind = 'session' AND k.key_hash = $1",
        _session_hash(token),
        TOUCH_SECONDS,
    )
    if row is None or not row["fresh"] or row["status"] != "active":
        return None
    idle_limit = IDLE_HOURS[row["level"]] * 3600
    if row["idle"].total_seconds() > idle_limit:
        return None
    if row["stale"]:
        await routing_pool().execute(
            "UPDATE panel_keys SET last_used = now() WHERE id = $1", row["key_id"]
        )
    return account_from(row)


async def end_session(token: str | None) -> None:
    if token:
        await routing_pool().execute(
            "DELETE FROM panel_keys WHERE kind = 'session' AND key_hash = $1",
            _session_hash(token),
        )


async def end_sessions(account_id: str) -> int:
    done = await routing_pool().execute(
        "DELETE FROM panel_keys WHERE account_id = $1::uuid AND kind = 'session'",
        account_id,
    )
    return int(done.split()[-1])


async def tidy_keys() -> int:
    """Remove what can never be used again: old codes and sessions that ended. Called by the
    nightly cleanup. Accounts and the log are never touched."""
    done = await routing_pool().execute(
        "DELETE FROM panel_keys WHERE expires_at < now() - interval '1 day' "
        "OR (kind = 'session' AND COALESCE(last_used, created_at) < now() - interval '2 days')"
    )
    return int(done.split()[-1])


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        secure=https,
        samesite="lax",
        path="/admin",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/admin")


# ── the request check every panel call goes through ──────────────────────────

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def need_panel_header(request: Request) -> None:
    """A call that changes something must carry a header only our own page sends. A page on
    another site cannot add it without our permission, so it cannot act in a signed-in browser."""
    if request.method not in _SAFE_METHODS and not request.headers.get("x-panel"):
        raise HTTPException(
            status_code=403, detail="This call did not come from the dashboard."
        )


async def require_account(request: Request) -> Account:
    need_panel_header(request)
    account = await account_for_session(request.cookies.get(SESSION_COOKIE))
    if account is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return account


async def require_super(request: Request) -> Account:
    account = await require_account(request)
    if not account.is_super:
        raise HTTPException(status_code=403, detail="Only a super admin can do that.")
    return account
