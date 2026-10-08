"""Synthetic data for the QA worlds. Nothing here is real: names, phones, emails, amounts are made up."""

from __future__ import annotations

import json
from types import SimpleNamespace

VOCAB = {
    "confirm_words": [
        "yes",
        "y",
        "haan",
        "ha",
        "ok",
        "okay",
        "sure",
        "confirm",
        "thik hai",
        "theek hai",
    ],
    "cancel_words": ["no", "nahi", "nope", "cancel", "stop"],
    "cancel_tokens": ["cancel", "/cancel", "stop"],
    "self_reference_words": ["me", "myself", "mujhe"],
    "retry_words": ["retry", "resend"],
}

# workflows used by many tests; every step is a real primitive of step_interpreter
CASE_STEP = {
    "op": "db.insert_row",
    "params": {
        "table": "cases",
        "sequence": {
            "field": "case_number",
            "prefix": "QA-{YY}-",
            "pad": 3,
            "start": 1,
        },
        "values": {
            "title": "$fields.title",
            "description": "$fields.description",
            "status": "reported",
            "priority": "medium",
            "complainant_id": "$user.user_id",
        },
    },
}
SCHEMA_TITLE = {
    "title": {"type": "string", "required": True, "label": "Title"},
    "description": {"type": "string", "label": "Details"},
}

# a step that writes a row into a table with NO unique rule, so a double run shows as two rows
NOTE_STEP = {
    "op": "db.insert_row",
    "params": {
        "table": "routing_rules",
        "values": {
            "name": "$fields.title",
            "assign_user_id": "$user.user_id",
            "is_active": False,
        },
    },
}
BIG_GATE = {
    "id": "g1",
    "type": "approval_chain",
    "when": {"field": "$fields.amount", "gte": 50000},
    "levels": [{"level": 1, "role": "approver", "max_amount": None}],
}

WORKFLOWS = {
    "qa_case_file": dict(
        name="QA file a case", steps=[CASE_STEP], entity_schema=SCHEMA_TITLE, gates=[]
    ),
    "qa_big_spend": dict(
        name="QA big spend",
        steps=[
            {"op": "approval_gate", "params": {"amount_field": "$fields.amount"}},
            CASE_STEP,
        ],
        entity_schema={**SCHEMA_TITLE, "amount": {"type": "number", "required": True}},
        gates=[
            {
                "id": "g1",
                "type": "approval_chain",
                "when": {"field": "$fields.amount", "gte": 50000},
                "levels": [{"level": 1, "role": "approver", "max_amount": None}],
            }
        ],
    ),
    "qa_otp_spend": dict(
        name="QA spend with a code",
        steps=[
            {"op": "otp_gate", "params": {"amount_field": "$fields.amount"}},
            CASE_STEP,
        ],
        entity_schema={**SCHEMA_TITLE, "amount": {"type": "number", "required": True}},
        gates=[
            {
                "id": "o1",
                "type": "otp",
                "when": {"field": "$fields.amount", "gte": 1000},
            }
        ],
    ),
    "qa_note": dict(
        name="QA note", steps=[NOTE_STEP], entity_schema=SCHEMA_TITLE, gates=[]
    ),
    "qa_note_big": dict(
        name="QA note with approval",
        steps=[
            {"op": "approval_gate", "params": {"amount_field": "$fields.amount"}},
            NOTE_STEP,
        ],
        entity_schema={**SCHEMA_TITLE, "amount": {"type": "number", "required": True}},
        gates=[BIG_GATE],
    ),
    # the second insert breaks the unique rule on case_number AFTER the first one was written
    "qa_partial_fail": dict(
        name="QA two steps, second fails",
        steps=[
            {
                "op": "db.insert_row",
                "params": {
                    "table": "cases",
                    "values": {
                        "case_number": "QA-PARTIAL-1",
                        "title": "$fields.title",
                        "status": "reported",
                    },
                },
            },
            {
                "op": "db.insert_row",
                "params": {
                    "table": "cases",
                    "values": {
                        "case_number": "QA-PARTIAL-1",
                        "title": "second",
                        "status": "reported",
                    },
                },
            },
        ],
        entity_schema=SCHEMA_TITLE,
        gates=[],
    ),
}

ROLE_PERMS = {
    "admin": [
        "qa_case_file",
        "qa_big_spend",
        "qa_otp_spend",
        "qa_partial_fail",
        "qa_note",
        "qa_note_big",
    ],
    "member": ["qa_case_file", "qa_note", "qa_partial_fail"],
    "approver": ["approve", "qa_case_file", "qa_note", "qa_note_big"],
    "staff": ["qa_case_file", "qa_big_spend", "qa_otp_spend", "qa_note", "qa_note_big"],
}

PEOPLE = {  # key -> (name, phone, email, role)
    "admin": ("Asha Admin", "+919000000001", "asha@example.test", "admin"),
    "member": ("Meera Member", "+919000000002", "meera@example.test", "member"),
    "approver": ("Arun Approver", "+919000000003", "arun@example.test", "approver"),
    "staff": ("Sam Staff", "+919000000004", "sam@example.test", "staff"),
}


async def insert_workflow(
    pool, org_id, intent_key: str, spec: dict, *, is_active: bool = True
):
    return await pool.fetchrow(
        """INSERT INTO workflows (org_id, intent_key, name, steps, entity_schema, gates, is_active, workflow_type, slash_command)
           VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7, 'action', $8) RETURNING id""",
        org_id,
        intent_key,
        spec["name"],
        json.dumps(spec["steps"]),
        json.dumps(spec["entity_schema"]),
        json.dumps(spec["gates"]),
        is_active,
        intent_key.replace("qa_", "")[:30],
    )


async def seed_housing(world) -> None:
    pool = world.pools["housing"]
    org_id = await pool.fetchval(
        "INSERT INTO orgs (name, slug, industry, settings) VALUES ($1, $2, 'housing', $3::jsonb) RETURNING id",
        "QA Housing Society",
        "qa-housing",
        json.dumps({"vocabulary": VOCAB}),
    )
    ids = world.ids
    ids.org_id = str(org_id)
    ids.org_name = "QA Housing Society"
    ids.role = {}
    for role, perms in ROLE_PERMS.items():
        ids.role[role] = str(
            await pool.fetchval(
                "INSERT INTO roles (org_id, name, permissions, is_approver, readable_tables) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                org_id,
                role,
                perms,
                role == "approver",
                ["cases"],
            )
        )
    ids.user = {}
    for key, (name, phone, email, role) in PEOPLE.items():
        ids.user[key] = str(
            await pool.fetchval(
                "INSERT INTO users (org_id, role_id, name, phone, email, channel) VALUES ($1, $2, $3, $4, $5, 'whatsapp') RETURNING id",
                org_id,
                ids.role[role],
                name,
                phone,
                email,
            )
        )
        setattr(ids, f"phone_{key}", phone)
        setattr(ids, f"email_{key}", email)
    # someone added to People by an admin who has not linked a chat yet
    ids.user["unlinked"] = str(
        await pool.fetchval(
            "INSERT INTO users (org_id, role_id, name, phone, email, channel) VALUES ($1, $2, 'Neha Newcomer', NULL, 'neha@example.test', 'telegram') RETURNING id",
            org_id,
            ids.role["member"],
        )
    )
    ids.workflow = {}
    for key, spec in WORKFLOWS.items():
        ids.workflow[key] = str((await insert_workflow(pool, org_id, key, spec))["id"])


async def seed_jewellery(world) -> None:
    pool = world.pools["jewellery"]
    ids = SimpleNamespace()
    org_id = await pool.fetchval(
        "INSERT INTO orgs (name, slug, industry, settings) VALUES ($1, $2, 'jewellery', $3::jsonb) RETURNING id",
        "QA Jewellers",
        "qa-jewellers",
        json.dumps({"vocabulary": VOCAB}),
    )
    ids.org_id = str(org_id)
    role_id = await pool.fetchval(
        "INSERT INTO roles (org_id, name, permissions) VALUES ($1, 'owner', $2) RETURNING id",
        org_id,
        ["qa_case_file"],
    )
    ids.user = str(
        await pool.fetchval(
            "INSERT INTO users (org_id, role_id, name, phone, email, channel) VALUES ($1, $2, 'Jay Jeweller', '+919100000001', 'jay@example.test', 'whatsapp') RETURNING id",
            org_id,
            role_id,
        )
    )
    ids.phone = "+919100000001"
    world.jewellery = ids
