"""What super admins do with sign-in accounts, and what a person does to their own password.

Every function that changes something writes a line in panel_audit. Problems a person can fix
come back as plain sentences (HTTP 4xx), never as a database message."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.admin_panel.auth import (
    Account,
    audit,
    end_sessions,
    hash_password,
)
from app.db import routing_pool


def shape(row) -> dict:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "name": row["name"],
        "level": row["level"],
        "orgs": list(row["source_keys"] or ()),
        "status": row["status"],
        "last_sign_in": row["last_sign_in"].isoformat()
        if row["last_sign_in"]
        else None,
        "locked": bool(row["locked"]),
        "invited_by": row["invited_by_name"],
    }


async def list_accounts() -> list[dict]:
    found = await routing_pool().fetch(
        "SELECT a.id, a.email, a.name, a.level, a.source_keys, a.status, a.last_sign_in, "
        "(a.locked_until IS NOT NULL AND a.locked_until > now()) AS locked, "
        "b.name AS invited_by_name "
        "FROM panel_accounts a LEFT JOIN panel_accounts b ON b.id = a.invited_by "
        "ORDER BY a.level DESC, lower(a.name)"
    )
    return [shape(r) for r in found]


async def _one(account_id: str) -> dict:
    row = await routing_pool().fetchrow(
        "SELECT a.id, a.email, a.name, a.level, a.source_keys, a.status, a.last_sign_in, "
        "(a.locked_until IS NOT NULL AND a.locked_until > now()) AS locked, "
        "b.name AS invited_by_name "
        "FROM panel_accounts a LEFT JOIN panel_accounts b ON b.id = a.invited_by "
        "WHERE a.id = $1::uuid",
        account_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="That account was not found.")
    return shape(row)


async def give_access(
    source_key: str, email: str, name: str, by: Account, request: Request, org_name: str
) -> tuple[dict, bool]:
    """Let a person of an organisation sign in to its dashboard as an admin. Returns the account
    and whether it is new."""
    async with routing_pool().acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT id, level, source_keys, status, password_hash FROM panel_accounts "
            "WHERE email = $1 FOR UPDATE",
            email,
        )
        if row is None:
            account_id = str(
                await conn.fetchval(
                    "INSERT INTO panel_accounts (email, name, level, source_keys, status, invited_by) "
                    "VALUES ($1, $2, 'admin', $3, 'invited', $4::uuid) RETURNING id",
                    email,
                    name,
                    [source_key],
                    by.id,
                )
            )
            created = True
        else:
            if row["level"] == "super":
                raise HTTPException(
                    status_code=409,
                    detail=f"{name} is a super admin already and can open every organisation.",
                )
            keys = list(row["source_keys"] or ())
            if source_key in keys and row["status"] != "off":
                raise HTTPException(
                    status_code=409,
                    detail=f"{name} can already sign in to the {org_name} dashboard.",
                )
            if source_key not in keys:
                keys.append(source_key)
            status = row["status"]
            if status == "off":
                status = "active" if row["password_hash"] else "invited"
            await conn.execute(
                "UPDATE panel_accounts SET source_keys = $2, status = $3, updated_at = now() "
                "WHERE id = $1",
                row["id"],
                keys,
                status,
            )
            account_id = str(row["id"])
            created = False
    await audit(
        "access_given",
        request=request,
        account_id=account_id,
        email=email,
        source_key=source_key,
        detail=f"{by.name} gave {name} access to {org_name}",
    )
    return await _one(account_id), created


async def take_access(
    account_id: str, source_key: str, by: Account, request: Request
) -> dict:
    async with routing_pool().acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT id, email, name, level, source_keys, status FROM panel_accounts "
            "WHERE id = $1::uuid FOR UPDATE",
            account_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="That account was not found.")
        if row["level"] == "super":
            raise HTTPException(
                status_code=409,
                detail="A super admin opens every organisation. Switch the account off instead.",
            )
        keys = [k for k in (row["source_keys"] or ()) if k != source_key]
        if len(keys) == len(row["source_keys"] or ()):
            raise HTTPException(
                status_code=409,
                detail=f"{row['name']} had no access to that dashboard.",
            )
        status = "off" if not keys else row["status"]
        await conn.execute(
            "UPDATE panel_accounts SET source_keys = $2, status = $3, updated_at = now() "
            "WHERE id = $1::uuid",
            account_id,
            keys,
            status,
        )
        if status == "off" and row["status"] != "off":
            await conn.execute(
                "DELETE FROM panel_keys WHERE account_id = $1::uuid AND kind = 'session'",
                account_id,
            )
    await audit(
        "access_taken",
        request=request,
        account_id=account_id,
        email=row["email"],
        source_key=source_key,
        detail=f"{by.name} took away {row['name']}'s access to {source_key}"
        + (" (no organisation left, so the account is off)" if status == "off" else ""),
    )
    return await _one(account_id)


async def switch(account_id: str, on: bool, by: Account, request: Request) -> dict:
    async with routing_pool().acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT id, email, name, level, source_keys, status, password_hash FROM panel_accounts "
            "WHERE id = $1::uuid FOR UPDATE",
            account_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="That account was not found.")
        if not on:
            if str(row["id"]) == by.id:
                raise HTTPException(
                    status_code=409, detail="You cannot switch off your own account."
                )
            if row["level"] == "super" and row["status"] == "active":
                others = await conn.fetchval(
                    "SELECT count(*) FROM panel_accounts WHERE level = 'super' "
                    "AND status = 'active' AND id <> $1::uuid",
                    account_id,
                )
                if not others:
                    raise HTTPException(
                        status_code=409,
                        detail="There must always be one super admin who can sign in.",
                    )
            status = "off"
        else:
            if row["level"] == "admin" and not (row["source_keys"] or ()):
                raise HTTPException(
                    status_code=409,
                    detail="Give this person an organisation first, then switch the account on.",
                )
            status = "active" if row["password_hash"] else "invited"
        await conn.execute(
            "UPDATE panel_accounts SET status = $2, updated_at = now() WHERE id = $1::uuid",
            account_id,
            status,
        )
        if status == "off":
            await conn.execute(
                "DELETE FROM panel_keys WHERE account_id = $1::uuid AND kind = 'session'",
                account_id,
            )
    await audit(
        "switched_on" if on else "switched_off",
        request=request,
        account_id=account_id,
        email=row["email"],
        detail=f"{by.name} switched {row['name']} {'on' if on else 'off'}",
    )
    return await _one(account_id)


async def add_super(email: str, name: str, by: Account, request: Request) -> dict:
    async with routing_pool().acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT id, level FROM panel_accounts WHERE email = $1 FOR UPDATE", email
        )
        if row is None:
            account_id = str(
                await conn.fetchval(
                    "INSERT INTO panel_accounts (email, name, level, source_keys, status, invited_by) "
                    "VALUES ($1, $2, 'super', '{}', 'invited', $3::uuid) RETURNING id",
                    email,
                    name,
                    by.id,
                )
            )
        else:
            if row["level"] == "super":
                raise HTTPException(
                    status_code=409, detail=f"{name} is a super admin already."
                )
            account_id = str(row["id"])
            await conn.execute(
                "UPDATE panel_accounts SET level = 'super', source_keys = '{}', "
                "updated_at = now() WHERE id = $1::uuid",
                account_id,
            )
    await audit(
        "super_added",
        request=request,
        account_id=account_id,
        email=email,
        detail=f"{by.name} made {name} a super admin",
    )
    return await _one(account_id)


async def sign_out_everywhere(account_id: str, by: Account, request: Request) -> dict:
    account = await _one(account_id)
    ended = await end_sessions(account_id)
    await audit(
        "signed_out_everywhere",
        request=request,
        account_id=account_id,
        email=account["email"],
        detail=f"{by.name} signed {account['name']} out everywhere ({ended} browser(s))",
    )
    return account


async def set_password(account_id: str, password: str) -> None:
    """Save a new password, end every session of the person, and make an invited account active.
    A switched-off account stays off."""
    hashed = await hash_password(password)
    async with routing_pool().acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE panel_accounts SET password_hash = $2, wrong_tries = 0, locked_until = NULL, "
            "status = CASE WHEN status = 'off' THEN 'off' ELSE 'active' END, updated_at = now() "
            "WHERE id = $1::uuid",
            account_id,
            hashed,
        )
        await conn.execute(
            "DELETE FROM panel_keys WHERE account_id = $1::uuid AND kind = 'session'",
            account_id,
        )
