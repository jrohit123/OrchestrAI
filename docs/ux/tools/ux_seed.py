"""UX audit: builds three throwaway databases (ux_routing, ux_housing, ux_jewellery) on the practice
Postgres of THIS computer and fills them with MADE-UP data only (a made-up housing society, a made-up
shop, fake phones and e-mails on example.test). Nothing here touches a real database or a real person.

Usage:  python ux_seed.py
"""

import asyncio
import json
import os
import random
import subprocess
import sys
import datetime as dt
from urllib.parse import urlsplit

for _k, _v in dict(
    ROUTING_DATABASE_URL="postgresql://postgres@127.0.0.1:9/none", ADMIN_TOKEN="x", BREVO_API_KEY="x", OPENAI_API_KEY="x",
    REDIS_URL="redis://127.0.0.1:9/0", SENDER_EMAIL="x@example.invalid", SENDER_NAME="x", TELEGRAM_BOT_TOKEN="0:x",
    WHATSAPP_APP_SECRET="x", WHATSAPP_TOKEN="x", WHATSAPP_VERIFY_TOKEN="x",
).items():
    os.environ.setdefault(_k, _v)
sys.path.insert(0, r"D:\Orchestrator AI")

import asyncpg  # noqa: E402

from app.admin_panel.auth import hash_password_sync  # noqa: E402

PORT = int(os.environ.get("PRACTICE_PG_PORT", "55432"))
PSQL = os.path.expanduser("~/scoop/apps/postgresql/current/bin/psql.exe")
PASSWORD = os.environ.get("UX_PASSWORD") or sys.exit("Set UX_PASSWORD to any made-up password first (it is used for every made-up account on this computer).")
rnd = random.Random(11)
NOW = dt.datetime.now(dt.timezone.utc)
VOCAB = {
    "confirm_words": ["yes", "y", "haan", "ok", "okay", "confirm"],
    "cancel_words": ["no", "nahi", "cancel", "stop"],
    "cancel_tokens": ["cancel", "/cancel", "stop"],
    "self_reference_words": ["me", "myself"],
    "retry_words": ["retry", "resend"],
}


def dsn(db: str) -> str:
    return f"postgresql://postgres@127.0.0.1:{PORT}/{db}"


def ago(days=0.0, hours=0.0, minutes=0.0):
    return NOW - dt.timedelta(days=days, hours=hours, minutes=minutes)


def local_only(db_dsn: str) -> None:
    if urlsplit(db_dsn).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("STOP: not a database on this computer")


async def recreate(admin, name: str, template: str) -> None:
    await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')


def run_sql_file(db: str, path: str) -> None:
    r = subprocess.run([PSQL, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", dsn(db), "-f", path], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print("  (seed file skipped:", os.path.basename(path), r.stderr.strip()[-200:], ")")


# ─────────────────────────────────────────── the flows of the made-up society
def case_row(prefix="SH-{YY}-"):
    return {
        "op": "db.insert_row",
        "params": {
            "table": "cases",
            "sequence": {"field": "case_number", "prefix": prefix, "pad": 3, "start": 1},
            "values": {
                "title": "$fields.title", "description": "$fields.description", "location": "$fields.location",
                "status": "reported", "priority": "medium", "complainant_id": "$user.user_id",
            },
        },
    }


FIND_CASE = {"op": "resolve_entity", "params": {"table": "cases", "into": "case", "name_from": "$fields.case_number", "match_column": "case_number", "normalize": "identifier"}}
S_STR = lambda label, required=False: {"type": "string", "label": label, **({"required": True} if required else {})}  # noqa: E731

FLOWS = [
    dict(key="file_a_complaint", name="File a complaint", kind="workflow", menu="create", slash="complaint", cmd="File a complaint or request",
         desc="Files a new complaint for the resident. The due time comes from the priority.",
         phrases=["file a complaint", "raise a complaint", "something is not working", "report a problem"],
         schema={"title": S_STR("What is the problem?", True), "description": S_STR("Details"), "location": S_STR("Where is it?")},
         steps=[case_row(), {"op": "notify.whatsapp", "params": {}}], gates=[], perms=["Admin", "Committee member", "Owner", "Tenant"],
         response="Your complaint is recorded.\nCase: {case_number}\nTitle: {title}"),
    dict(key="case_pass_on", name="Assign a case", kind="workflow", menu="update", slash="assign", cmd="Give a case to someone",
         desc="Gives a case to one person and tells them and whoever raised it.",
         phrases=["assign case", "give this case to", "pass on the case"],
         schema={"case_number": S_STR("Case number", True), "assignee_name": S_STR("Give it to", True), "comment_text": S_STR("Note")},
         steps=[FIND_CASE,
                {"op": "resolve_entity", "params": {"table": "users", "into": "assignee_user", "name_from": "$fields.assignee_name", "match_column": "name"}},
                {"op": "db.update_row", "params": {"table": "cases", "set": {"assigned_to_id": "$assignee_user.id", "status": "under_review"}, "where": {"id": "$case.id"}}}],
         gates=[], perms=["Admin", "Committee member"]),
    dict(key="add_case_update", name="Add an update to a case", kind="workflow", menu="update", slash="update", cmd="Add a note to a case",
         desc="Adds a note to a case and tells the person who has it and the person who raised it.",
         phrases=["add a note to a case", "update the case", "work started on"],
         schema={"case_number": S_STR("Case number", True), "note": S_STR("What is the update?", True)},
         steps=[FIND_CASE, {"op": "notify.parties", "params": {"case": "$case.id", "message_template": "Update on {case_number}: {note}"}}],
         gates=[], perms=["Admin", "Committee member", "Security guard", "Maintenance staff"]),
    dict(key="close_a_case", name="Close a case with a note", kind="workflow", menu="update", slash="close", cmd="Close a case",
         desc="Closes a case. The closing note is compulsory.",
         phrases=["close case", "mark the case done", "problem is fixed"],
         schema={"case_number": S_STR("Case number", True), "closing_note": S_STR("What was done?", True)},
         steps=[FIND_CASE, {"op": "db.update_row", "params": {"table": "cases", "set": {"status": "closed"}, "where": {"id": "$case.id"}}},
                {"op": "notify.parties", "params": {"case": "$case.id", "message_template": "Case {case_number} is closed. {closing_note}"}}],
         gates=[], perms=["Admin", "Committee member", "Maintenance staff"]),
    dict(key="approve_expense", name="Approve a society expense", kind="workflow", menu="create", slash="expense", cmd="Ask for an expense to be approved",
         desc="Collects the bill details and asks the committee to approve. Over Rs 50,000 needs a second approval.",
         phrases=["approve expense", "pay a vendor", "raise a payment request"],
         schema={"vendor": S_STR("Vendor", True), "amount": {"type": "number", "required": True, "label": "Amount"}, "purpose": S_STR("What is it for?", True)},
         steps=[{"op": "approval_gate", "params": {"amount_field": "$fields.amount"}},
                {"op": "db.insert_row", "params": {"table": "entity_records", "values": {"entity_type": "expense", "name": "$fields.vendor", "status": "approved"}}},
                {"op": "notify.user", "params": {"to": "$user.user_id", "message_template": "Your expense of Rs {amount} for {vendor} is approved."}}],
         gates=[{"id": "g1", "type": "approval_chain", "when": {"field": "$fields.amount", "gte": 10000},
                 "levels": [{"level": 1, "role": "Committee member", "max_amount": 50000}, {"level": 2, "role": "Admin", "max_amount": None}]}],
         perms=["Admin", "Committee member"]),
    dict(key="read_a_bill", name="Read a bill and send it for approval", kind="workflow", menu="create", slash="bill", cmd="Send a bill for approval",
         desc="Takes the bill details from the PDF that was sent, then asks the treasurer to approve.",
         phrases=["here is a bill", "vendor invoice", "pay this invoice"],
         schema={"vendor": S_STR("Vendor", True), "amount": {"type": "number", "required": True, "label": "Amount"}, "invoice_no": S_STR("Invoice number")},
         steps=[{"op": "derive_field", "params": {"field": "amount_in_words", "expr": "$fields.amount"}},
                {"op": "approval_gate", "params": {"amount_field": "$fields.amount"}}, {"op": "notify.whatsapp", "params": {}}],
         gates=[{"id": "g1", "type": "approval_chain", "when": {"field": "$fields.amount", "gte": 1},
                 "levels": [{"level": 1, "role": "Committee member", "max_amount": None}]}], perms=["Admin", "Committee member"]),
    dict(key="send_notice", name="Send a notice to all residents", kind="workflow", menu="create", slash="notice", cmd="Send a notice to everyone",
         desc="Sends the same message to every resident.",
         phrases=["send a notice", "announce", "tell everyone"],
         schema={"subject": S_STR("Subject", True), "message": S_STR("Message", True)},
         steps=[{"op": "notify.user", "params": {"to": "$fields.everyone", "message_template": "{subject}: {message}"}}], gates=[], perms=["Admin", "Committee member"]),
    dict(key="visitor_pass", name="Pre-approve a visitor", kind="workflow", menu="create", slash="visitor", cmd="Tell the gate a visitor is coming",
         desc="Lets the security guard know a visitor is expected.",
         phrases=["visitor coming", "guest at the gate", "pre approve visitor"],
         schema={"visitor_name": S_STR("Visitor name", True), "date": {"type": "date", "label": "Date"}, "vehicle": S_STR("Vehicle number")},
         steps=[{"op": "db.insert_row", "params": {"table": "entity_records", "values": {"entity_type": "visitor", "name": "$fields.visitor_name", "status": "expected"}}},
                {"op": "notify.user", "params": {"to": "$user.user_id", "message_template": "Visitor {visitor_name} is on the gate list."}}],
         gates=[], perms=["Admin", "Owner", "Tenant", "Security guard"]),
    dict(key="monthly_dues", name="Dues reminder", kind="workflow", menu="other", slash="dues", cmd="Remind a flat about dues",
         desc="Sends a polite reminder about the month's maintenance dues.",
         phrases=["dues reminder", "maintenance due"],
         schema={"flat": S_STR("Flat", True)}, steps=[{"op": "notify.user", "params": {"to": "$user.user_id", "message_template": "Maintenance for {flat} is due."}}], gates=[], perms=["Admin"]),
    # building blocks (small steps other flows reuse)
    dict(key="block_find_case", name="Find a case by its number", kind="block", menu="other", desc="Finds the case from its number (any format) and keeps it for the steps after. Stops if there is no such case.",
         phrases=[], schema={}, steps=[FIND_CASE], gates=[], perms=[]),
    dict(key="block_tell_raiser", name="Tell the person who raised the case", kind="block", menu="other", desc="Sends the person who raised the case a message.",
         phrases=[], schema={}, steps=[{"op": "notify.parties", "params": {"case": "$case.id", "message_template": "{message}", "roles": ["requester"]}}], gates=[], perms=[]),
    dict(key="block_due_from_priority", name="Work out the due time from the priority", kind="block", menu="other", desc="Works out when a case is due from the response-time table.",
         phrases=[], schema={}, steps=[{"op": "derive_field", "params": {"field": "due_at", "expr": "$fields.priority"}}], gates=[], perms=[]),
]

ROLES = {  # name -> (is_approver, approval_max, readable tables)
    "Admin": (True, 500000, ["cases", "users", "residents"]),
    "Committee member": (True, 50000, ["cases", "users"]),
    "Owner": (False, None, ["cases"]),
    "Tenant": (False, None, ["cases"]),
    "Security guard": (False, None, []),
    "Maintenance staff": (False, None, ["cases"]),
}

SEATS = [  # name, kind, slug, description
    ("Chairperson", "committee", "chairperson", "Leads the committee and signs off big decisions."),
    ("Secretary", "committee", "secretary", "Runs day-to-day matters and gets most complaints."),
    ("Treasurer", "committee", "treasurer", "Approves expenses and watches the accounts."),
    ("Maintenance supervisor", "staff", "maintenance", "Looks after lifts, water and electrical work."),
    ("Security supervisor", "security", "security", "Runs the gate and the guards."),
    ("Volunteer coordinator", "volunteer", "volunteers", "Organises festival and clean-up volunteers."),
]

CATEGORIES = [  # key, label, parent key, default priority, target minutes, keywords
    ("lift", "Lift & elevators", None, "high", 240, ["lift", "elevator"]),
    ("water", "Water & plumbing", None, "high", 480, ["water", "leak", "tap", "tank"]),
    ("water.leak", "Leakage", "water", "high", 480, ["leakage", "seepage"]),
    ("water.tank", "Water tank", "water", "medium", 720, ["tank", "overflow"]),
    ("electrical", "Electrical & lights", None, "medium", 720, ["light", "power", "electric"]),
    ("parking", "Parking", None, "low", 2880, ["parking", "car", "slot"]),
    ("security", "Security & gate", None, "high", 240, ["gate", "guard", "cctv"]),
    ("housekeeping", "Housekeeping & garbage", None, "medium", 1440, ["garbage", "cleaning"]),
    ("noise", "Noise & nuisance", None, "low", 2880, ["noise", "music"]),
    ("amenities", "Clubhouse & gym", None, "low", 4320, ["gym", "club", "pool"]),
    ("other", "Something else", None, "medium", None, []),
]

RULES = [  # name, category key, seat name
    ("Lift problems go to the Secretary", "lift", "Secretary"),
    ("Water problems go to the Maintenance supervisor", "water", "Maintenance supervisor"),
    ("Electrical problems go to the Maintenance supervisor", "electrical", "Maintenance supervisor"),
    ("Parking goes to the Security supervisor", "parking", "Security supervisor"),
    ("Gate matters go to the Security supervisor", "security", "Security supervisor"),
    ("Garbage goes to the Secretary", "housekeeping", "Secretary"),
    ("Noise goes to the Chairperson", "noise", "Chairperson"),
]

# (name, role, seat or None, wing, flat, status, residential_status, channel)
PEOPLE = [
    ("Rajiv Menon", "Committee member", "Chairperson", "A", "101", "active", "first_owner", "telegram"),
    ("Meena Kulkarni", "Committee member", "Secretary", "A", "203", "active", "first_owner", "telegram"),
    ("Farah Sheikh", "Committee member", "Treasurer", "B", "301", "active", "first_owner", "telegram"),
    ("Dinesh Patil", "Maintenance staff", "Maintenance supervisor", None, None, "active", None, "telegram"),
    ("Karan Bhatt", "Security guard", "Security supervisor", None, None, "active", None, "telegram"),
    ("Joseph Pinto", "Security guard", None, None, None, "active", None, "telegram"),
    ("Imran Khan", "Security guard", None, None, None, "active", None, "telegram"),
    ("Aarav Shah", "Owner", None, "A", "102", "active", "first_owner", "telegram"),
    ("Isha Nair", "Tenant", None, "A", "204", "active", "tenant", "telegram"),
    ("Vikram Rao", "Owner", None, "A", "304", "active", "second_owner", "telegram"),
    ("Neha Joshi", "Tenant", None, "A", "402", "active", "tenant", "telegram"),
    ("Kabir Mehta", "Owner", None, "B", "101", "active", "first_owner", "telegram"),
    ("Tara Iyer", "Tenant", None, "B", "205", "active", "tenant", "telegram"),
    ("Sanjay Gupta", "Owner", None, "B", "302", "active", "first_owner", "telegram"),
    ("Ritu Verma", "Tenant", None, "B", "402", "not_residing", "tenant", "telegram"),
    ("Pooja Deshmukh", "Owner", None, "C", "102", "active", "first_owner", "telegram"),
    ("Manish Kapoor", "Tenant", None, "C", "204", "active", "tenant", "telegram"),
    ("Anita Das", "Owner", None, "C", "305", "active", "first_owner", "telegram"),
    ("Rahul Khanna", "Tenant", None, "C", "401", "suspended", "tenant", "telegram"),
    ("Sunita Reddy", "Owner", None, "C", "503", "active", "first_owner", "telegram"),
    ("Omkar Jadhav", "Owner", None, "A", "501", "active", "first_owner", "telegram"),
    ("Priyanka Sethi", "Tenant", None, "B", "103", "active", "tenant", "telegram"),
    ("Harish Bhalla", "Owner", None, "B", "504", "active", "first_owner", "telegram"),
    ("Lakshmi Narayan", "Owner", None, "C", "202", "active", "first_owner", "telegram"),
    ("Yusuf Ansari", "Tenant", None, "A", "403", "active", "tenant", "telegram"),
    ("Devika Rane", "Tenant", None, "C", "104", "active", "tenant", "telegram"),
    ("Kavya Rao", "Admin", None, None, None, "active", None, "telegram"),
]

CASE_TEMPLATES = [  # title, category key, description, location
    ("Lift in Wing B not working", "lift", "The lift stopped between the 3rd and 4th floor this morning.", "Wing B lift lobby"),
    ("Lift door closes too fast", "lift", "Elderly residents are being hit by the door.", "Wing A lift"),
    ("Water leaking from the ceiling", "water.leak", "Water drips from the ceiling of the bathroom since two days.", "Flat above the bathroom"),
    ("Water tank overflowing at night", "water.tank", "The terrace tank overflows between 2 and 4 am.", "Terrace, Wing C"),
    ("No water on the 5th floor", "water", "Low pressure since Monday evening.", "Wing A, 5th floor"),
    ("Street light near gate 2 is off", "electrical", "The area is dark after 8 pm.", "Gate 2"),
    ("Corridor light flickering", "electrical", "Flickers all evening and gives a headache.", "Wing C, 2nd floor corridor"),
    ("Outsider car in my parking slot", "parking", "A white car has been parked in slot 14 for two days.", "Parking slot 14"),
    ("Parking slot markings faded", "parking", "Visitors park on resident slots.", "Basement"),
    ("Visitor entered without a pass", "security", "A delivery person was let in without an entry.", "Main gate"),
    ("CCTV not covering the lobby", "security", "Camera 4 shows a black screen.", "Wing A lobby"),
    ("Garbage not collected on Tuesday", "housekeeping", "The bins on every floor were full by evening.", "All wings"),
    ("Stairwell not cleaned", "housekeeping", "Dust and old leaves on the stairs.", "Wing B stairwell"),
    ("Loud music after 11 pm", "noise", "Party music until 1 am on a weekday.", "Wing C"),
    ("Drilling noise on Sunday morning", "noise", "Renovation work is going on during rest hours.", "Wing B"),
    ("Clubhouse air conditioner not cooling", "amenities", "The AC runs but the room stays warm.", "Clubhouse"),
    ("Gym treadmill is broken", "amenities", "Belt does not move.", "Gym"),
    ("Intercom not working in B-205", "electrical", "Cannot receive calls from the gate.", "Flat B-205"),
    ("Terrace door lock is broken", "security", "Anyone can walk onto the terrace.", "Terrace, Wing A"),
    ("Pest control request for the basement", "housekeeping", "Rats seen near the bins.", "Basement"),
    ("Fire extinguisher expired", "security", "The tag shows last year's date.", "Wing D corridor"),
    ("Need a new notice board", "other", "The old one is torn.", "Entrance"),
    ("Pool filter is making noise", "amenities", "A grinding sound while it runs.", "Swimming pool"),
    ("Flat sign board fallen", "other", "The metal plate fell near the entrance.", "Wing A entrance"),
]

SESSION_LINES = [
    ("hi", "Hello! How can I help? You can file a complaint, check a case, or send a visitor to the gate."),
    ("my lift is not working", "I'm sorry about that. Shall I file a complaint for the lift? Reply YES to confirm."),
    ("yes", "Done. Your complaint is recorded. Case: {case}."),
    ("status of {case}", "Case {case} is under review and is with {who}."),
    ("is anyone coming to fix it today", "The Maintenance supervisor has been told. You will get a message when work starts."),
    ("visitor coming tomorrow 5 pm ramesh", "Done. Ramesh is on the gate list for tomorrow."),
    ("water leaking from ceiling in b 205", "I'm sorry to hear that. I have recorded a complaint, Case: {case}."),
    ("what is the maintenance due for my flat", "Your maintenance for this month is Rs 3,200. It is due on the 10th."),
]


async def seed_housing() -> dict:
    c = await asyncpg.connect(dsn("ux_housing"))
    ids: dict = {"role": {}, "user": {}, "seat": {}, "cat": {}, "flow": {}, "case": []}
    try:
        org = await c.fetchval(
            "INSERT INTO orgs (name, slug, industry, settings, plan) VALUES ('Sunrise Heights CHS', 'sunrise-heights', 'housing', $1::jsonb, 'trial') RETURNING id",
            json.dumps({"vocabulary": VOCAB, "case_reminders": {"closed_values": ["closed"]}, "case_buttons": {"assign": "case_pass_on"}}),
        )
        ids["org"] = org
        for name, (appr, mx, tables) in ROLES.items():
            perms = [f["key"] for f in FLOWS if name in f["perms"]] + (["approve"] if appr else [])
            ids["role"][name] = await c.fetchval(
                "INSERT INTO roles (org_id, name, permissions, is_approver, approval_max_amount, readable_tables) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                org, name, perms, appr, mx, tables,
            )
        for name, kind, slug, desc in SEATS:
            ids["seat"][name] = await c.fetchval(
                "INSERT INTO committee_positions (org_id, name, slug, kind, description, default_permissions) VALUES ($1, $2, $3, $4, $5, '{}') RETURNING id",
                org, name, slug, kind, desc,
            )
        n = 0
        for name, role, seat, wing, flat, status, rstatus, channel in PEOPLE:
            n += 1
            domain = "ux.test" if name in ("Meena Kulkarni", "Kavya Rao") else "example.test"  # same e-mail as the dashboard account, so Assign can act as her
            email = name.lower().replace(" ", ".") + "@" + domain
            uid = await c.fetchval(
                "INSERT INTO users (org_id, role_id, name, phone, email, channel, is_active, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
                org, ids["role"][role], name, (f"tg:{900000 + n}" if n <= 14 else f"+9190000{n:05d}"), email, channel, status in ("active",), ago(days=rnd.randint(40, 300)),
            )
            ids["user"][name] = uid
            if flat:
                await c.execute(
                    "INSERT INTO residents (org_id, user_id, wing, flat_no, residential_status, status, name, registration_date) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                    org, uid, wing, flat, rstatus, status, name, (ago(days=rnd.randint(60, 900))).date(),
                )
            if seat:
                await c.execute(
                    "INSERT INTO committee_members (org_id, user_id, position_id, status, start_date) VALUES ($1, $2, $3, 'active', $4)",
                    org, uid, ids["seat"][seat], ago(days=rnd.randint(100, 500)).date(),
                )
            if role in ("Security guard", "Maintenance staff"):
                await c.execute(
                    "INSERT INTO staff (org_id, user_id, name, department, designation, vendor_name, status, start_date) VALUES ($1, $2, $3, $4, $5, 'Shield Services (made up)', 'active', $6)",
                    org, uid, name, "Security" if role == "Security guard" else "Maintenance", role, ago(days=300).date(),
                )
        await c.execute(
            "UPDATE users u SET role_id = $1 WHERE u.id IN (SELECT user_id FROM committee_members WHERE status = 'active' AND position_id IN (SELECT id FROM committee_positions WHERE kind = 'committee'))",
            ids["role"]["Committee member"],
        )
        # one person who held a seat before and left it, so the seat has a history
        await c.execute(
            "INSERT INTO committee_members (org_id, user_id, position_id, status, start_date, end_date) VALUES ($1, $2, $3, 'ended', $4, $5)",
            org, ids["user"]["Sanjay Gupta"], ids["seat"]["Treasurer"], ago(days=900).date(), ago(days=400).date(),
        )
        # a newcomer who was added by an admin and has not linked a chat yet
        await c.execute(
            "INSERT INTO users (org_id, role_id, name, phone, email, channel, is_active) VALUES ($1, $2, 'Zoya Fernandes', NULL, 'zoya.fernandes@example.test', 'telegram', true)",
            org, ids["role"]["Tenant"],
        )
        # categories, rules, response times
        for key, label, parent, prio, mins, kw in CATEGORIES:
            ids["cat"][key] = await c.fetchval(
                "INSERT INTO case_categories (org_id, parent_id, key, label, default_priority, target_minutes, keywords, sort_order) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
                org, ids["cat"].get(parent) if parent else None, key, label, prio, mins, kw, len(ids["cat"]),
            )
        for i, (name, cat, seat) in enumerate(RULES):
            await c.execute(
                "INSERT INTO routing_rules (org_id, name, category_id, assign_position_id, sort_order) VALUES ($1, $2, $3, $4, $5)",
                org, name, ids["cat"][cat], ids["seat"][seat], i,
            )
        for prio, mins, rem in (("urgent", 120, 30), ("high", 480, 120), ("medium", 1440, 240), ("low", 4320, 720)):
            await c.execute("INSERT INTO priority_tat_rules (org_id, priority, tat_minutes, reminder_threshold_minutes) VALUES ($1, $2, $3, $4)", org, prio, mins, rem)
        # flows (+ a little history for three of them)
        for f in FLOWS:
            wid = await c.fetchval(
                """INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section, kind, slash_command, command_description, response_template)
                   VALUES ($1, $2, $3, $4, 'action', $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10, $11, $12, $13, $14, $15) RETURNING id""",
                org, f["key"], f["name"], f["desc"], json.dumps(f["steps"]), json.dumps(f["schema"]), json.dumps(f["gates"]), json.dumps(f["phrases"]),
                3 if f["key"] in ("file_a_complaint", "approve_expense", "close_a_case") else 1, f["key"] != "monthly_dues", f["menu"], f["kind"],
                f.get("slash"), f.get("cmd"), f.get("response"),
            )
            ids["flow"][f["key"]] = wid
            if f["key"] in ("file_a_complaint", "approve_expense", "close_a_case"):
                for v in (1, 2, 3):
                    await c.execute(
                        "INSERT INTO workflow_versions (workflow_id, org_id, version, intent_key, name, entity_schema, gates, granted_roles, steps, slash_command, kind, published_at) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9::jsonb, $10, $11, $12)",
                        wid, org, v, f["key"], f["name"], json.dumps(f["schema"]), json.dumps(f["gates"]), f["perms"], json.dumps(f["steps"]), f.get("slash"), f["kind"], ago(days=40 - v * 9),
                    )
        # cases
        people_ids = [uid for name, uid in ids["user"].items()]
        resident_ids = [ids["user"][p[0]] for p in PEOPLE if p[3]]
        seat_holder = {seat: ids["user"][p[0]] for p in PEOPLE if (seat := p[2])}
        route_to = {cat: seat_holder[seat] for _, cat, seat in RULES}
        for i in range(44):
            title, cat, desc, loc = CASE_TEMPLATES[i % len(CASE_TEMPLATES)]
            key = cat.split(".")[0]
            created = ago(days=rnd.uniform(0.1, 42))
            status = rnd.choices(["reported", "under_review", "action_taken", "closed"], weights=[22, 28, 16, 34])[0]
            prio = rnd.choices(["urgent", "high", "medium", "low"], weights=[8, 28, 44, 20])[0]
            assignee = None if status == "reported" and rnd.random() < 0.75 else route_to.get(key)
            if status in ("under_review", "action_taken", "closed") and not assignee:
                assignee = seat_holder["Secretary"]
            tat = {"urgent": 120, "high": 480, "medium": 1440, "low": 4320}[prio]
            closed_at = created + dt.timedelta(hours=rnd.uniform(3, 90)) if status == "closed" else None
            if closed_at and closed_at > NOW:
                closed_at = NOW - dt.timedelta(minutes=30)
            cid = await c.fetchval(
                """INSERT INTO cases (org_id, case_number, complainant_id, title, description, status, priority, location, assigned_to_id, created_at, closed_at, due_date, category_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) RETURNING id""",
                org, f"SH-26-{i + 1:03d}", rnd.choice(resident_ids), title, desc, status, prio, loc, assignee, created, closed_at,
                created + dt.timedelta(minutes=tat), ids["cat"][cat],
            )
            ids["case"].append(cid)
            actor = assignee or seat_holder["Secretary"]
            if status != "reported":
                await c.execute(
                    "INSERT INTO case_activity (org_id, case_id, actor_user_id, activity_type, payload, created_at) VALUES ($1, $2, $3, 'assignment', $4::jsonb, $5)",
                    org, cid, seat_holder["Secretary"], json.dumps({"to_name": next(k for k, v in ids["user"].items() if v == assignee), "note": "Please take a look today."}), created + dt.timedelta(minutes=40),
                )
                await c.execute(
                    "INSERT INTO case_activity (org_id, case_id, actor_user_id, activity_type, payload, created_at) VALUES ($1, $2, $3, 'status_change', $4::jsonb, $5)",
                    org, cid, actor, json.dumps({"from": "reported", "to": "under_review"}), created + dt.timedelta(minutes=45),
                )
            if status in ("action_taken", "closed"):
                await c.execute(
                    "INSERT INTO case_activity (org_id, case_id, actor_user_id, activity_type, payload, created_at) VALUES ($1, $2, $3, 'comment', $4::jsonb, $5)",
                    org, cid, actor, json.dumps({"text": "Vendor visited and checked. Work is in progress."}), created + dt.timedelta(hours=6),
                )
            if status == "closed":
                await c.execute(
                    "INSERT INTO case_activity (org_id, case_id, actor_user_id, activity_type, payload, created_at) VALUES ($1, $2, $3, 'status_change', $4::jsonb, $5)",
                    org, cid, actor, json.dumps({"from": "action_taken", "to": "closed", "closing_note": "Fixed and checked with the resident."}), closed_at or NOW,
                )
        # conversations (what people wrote to the chat bot)
        sess = 0
        for d in range(0, 16):
            for _ in range(rnd.randint(1, 3)):
                sess += 1
                who = rnd.choice(resident_ids)
                sid = f"ux-session-{sess:03d}"
                start = ago(days=d, hours=rnd.uniform(0, 14))
                case_no = f"SH-26-{rnd.randint(1, 44):03d}"
                for j, (text, reply) in enumerate(rnd.sample(SESSION_LINES, rnd.randint(2, 4))):
                    await c.execute(
                        "INSERT INTO audit_log (org_id, user_id, intent_key, tier, input_text, outcome, response_text, session_id, created_at) VALUES ($1, $2, $3, 1, $4, $5, $6, $7, $8)",
                        org, who, rnd.choice(["agent", "agent", "file_a_complaint", "visitor_pass"]), text.format(case=case_no, who="the Secretary"),
                        "error" if rnd.random() < 0.05 else "success", reply.format(case=case_no, who="the Secretary"), sid, start + dt.timedelta(minutes=j * 2),
                    )
        # what was changed from the dashboard
        for days, area, action, summary, label in (
            (30, "people", "update", "Meena Kulkarni now holds the Secretary seat", "Kavya Rao"),
            (22, "roles", "update", "Changed what the Committee member role can do", "Kavya Rao"),
            (15, "rules", "create", "Added a rule: Noise goes to the Chairperson", "Meena Kulkarni"),
            (9, "workflows", "update", "Edited the flow Close a case with a note", "Kavya Rao"),
            (5, "settings", "update", "Changed settings: session minutes 480 -> 240", "Kavya Rao"),
            (2, "people", "create", "Added Zoya Fernandes as Tenant", "Meena Kulkarni"),
        ):
            await c.execute(
                "INSERT INTO admin_events (org_id, actor_label, area, action, summary, created_at) VALUES ($1, $2, $3, $4, $5, $6)",
                org, label, area, action, summary, ago(days=days),
            )
        await c.execute(
            "INSERT INTO access_grants (org_id, user_id, workflow_key, level, note, valid_from, valid_to) VALUES ($1, $2, 'send_notice', 2, 'Festival volunteer, notices only until the event ends', $3, $4)",
            org, ids["user"]["Omkar Jadhav"], ago(days=3).date(), (NOW + dt.timedelta(days=20)).date(),
        )
        await c.execute(
            "INSERT INTO scheduled_reports (org_id, user_id, phone, query_text, report_label, schedule_type, hour, minute, day_of_month, delivery, next_run_at, source_key) VALUES ($1, $2, '+9190000000002', 'open cases by category', 'Open cases summary', 'monthly', 9, 0, 1, 'whatsapp', $3, 'sunrise')",
            org, ids["user"]["Meena Kulkarni"], NOW + dt.timedelta(days=22),
        )
    finally:
        await c.close()
    return ids


async def seed_jewellery() -> None:
    c = await asyncpg.connect(dsn("ux_jewellery"))
    try:
        org = await c.fetchval("INSERT INTO orgs (name, slug, industry, settings) VALUES ('Zari Jewellers', 'zari-jewellers', 'jewellery', $1::jsonb) RETURNING id", json.dumps({"vocabulary": VOCAB}))
        owner = await c.fetchval("INSERT INTO roles (org_id, name, permissions) VALUES ($1, 'Owner', $2) RETURNING id", org, ["price_quote"])
        staff = await c.fetchval("INSERT INTO roles (org_id, name, permissions) VALUES ($1, 'Salesperson', $2) RETURNING id", org, ["price_quote"])
        for i, (name, role) in enumerate((("Lata Pillai", owner), ("Vivek Anand", staff), ("Rekha Soni", staff))):
            await c.execute(
                "INSERT INTO users (org_id, role_id, name, phone, email, channel) VALUES ($1, $2, $3, $4, $5, 'whatsapp')",
                org, role, name, f"+9191000{i:05d}", name.lower().replace(" ", ".") + "@example.test",
            )
        await c.execute(
            """INSERT INTO workflows (org_id, intent_key, name, description, workflow_type, steps, entity_schema, gates, training_phrases, version, is_active, menu_section, kind)
               VALUES ($1, 'price_quote', 'Quote a price', 'Works out a price from the weight and the day''s rate.', 'action', $2::jsonb, $3::jsonb, '[]'::jsonb, $4::jsonb, 1, true, 'create', 'workflow')""",
            org, json.dumps([{"op": "compute", "params": {}}, {"op": "notify.whatsapp", "params": {}}]),
            json.dumps({"item": S_STR("Item", True), "weight_grams": {"type": "number", "required": True, "label": "Weight (grams)"}}), json.dumps(["price of a chain", "quote a ring"]),
        )
    finally:
        await c.close()


async def seed_routing(ids: dict) -> None:
    c = await asyncpg.connect(dsn("ux_routing"))
    try:
        await c.execute(
            "INSERT INTO data_sources (source_key, database_url, description, messaging_channel) VALUES ('sunrise', $1, 'Sunrise Heights CHS (made up)', 'telegram'), ('zari', $2, 'Zari Jewellers (made up)', 'whatsapp')",
            dsn("ux_housing"), dsn("ux_jewellery"),
        )
        pw = hash_password_sync(PASSWORD)
        accounts = [
            ("kavya.rao@ux.test", "Kavya Rao", "super", [], "active", pw),
            ("arjun.bose@ux.test", "Arjun Bose", "super", [], "invited", None),
            ("meena.kulkarni@ux.test", "Meena Kulkarni", "admin", ["sunrise"], "active", pw),
            ("sam.thomas@ux.test", "Sam Thomas", "admin", ["sunrise", "zari"], "active", pw),
            ("lata.pillai@ux.test", "Lata Pillai", "admin", ["zari"], "active", pw),
            ("venkat.rao@ux.test", "Venkat Rao", "admin", ["sunrise"], "invited", None),
            ("old.account@ux.test", "Old Account", "admin", ["sunrise"], "off", pw),
        ]
        acc = {}
        for email, name, level, keys, status, h in accounts:
            acc[email] = await c.fetchval(
                "INSERT INTO panel_accounts (email, name, level, source_keys, status, password_hash, last_sign_in) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
                email, name, level, keys, status, h, ago(days=1) if status == "active" else None,
            )
        # a month of sign-in log lines: made up
        asks = [
            ("meena.kulkarni@ux.test", "sunrise", "Please add Venkat Rao as an admin for Sunrise Heights. His email is venkat.rao@ux.test"),
            ("lata.pillai@ux.test", "zari", "How do I change the price flow? I can't find it."),
            ("sam.thomas@ux.test", "sunrise", "Can you switch off the Dues reminder flow until next month?"),
        ]
        rows = []
        for d in range(0, 25):
            for email, level in (("kavya.rao@ux.test", "super"), ("meena.kulkarni@ux.test", "admin"), ("sam.thomas@ux.test", "admin"), ("lata.pillai@ux.test", "admin")):
                if rnd.random() < 0.55:
                    rows.append((ago(days=d, hours=rnd.uniform(0, 10)), acc[email], email, "sign_in", True, None, None))
            if rnd.random() < 0.18:
                rows.append((ago(days=d, hours=rnd.uniform(0, 10)), None, "meena.kulkarni@ux.test", "sign_in_failed", False, None, "wrong password"))
        for i, (email, key, text) in enumerate(asks):
            rows.append((ago(days=2 + i * 5, hours=3), acc[email], email, "ask", True, key, text))
        rows += [
            (ago(days=14), acc["meena.kulkarni@ux.test"], "meena.kulkarni@ux.test", "sign_up", True, None, None),
            (ago(days=14, hours=-0.1), acc["meena.kulkarni@ux.test"], "meena.kulkarni@ux.test", "code_sent", True, None, None),
            (ago(days=13), acc["kavya.rao@ux.test"], "meena.kulkarni@ux.test", "access_given", True, "sunrise", "Meena Kulkarni can open Sunrise Heights"),
            (ago(days=4), None, "stranger@example.test", "sign_up_unknown", False, None, "not invited"),
        ]
        for at, aid, email, action, ok, key, detail in rows:
            await c.execute(
                "INSERT INTO panel_audit (at, account_id, email, action, ok, source_key, detail, ip, agent) VALUES ($1, $2, $3, $4, $5, $6, $7, '203.0.113.7', 'ux-seed')",
                at, aid, email, action, ok, key, detail,
            )
    finally:
        await c.close()


async def main() -> None:
    local_only(dsn("postgres"))
    admin = await asyncpg.connect(dsn("postgres"))
    try:
        for name, tmpl in (("ux_routing", "qa_tmpl_routing"), ("ux_housing", "qa_tmpl_housing"), ("ux_jewellery", "qa_tmpl_jewellery")):
            await recreate(admin, name, tmpl)
    finally:
        await admin.close()
    repo = r"D:\Orchestrator AI\migrations"
    run_sql_file("ux_housing", repo + r"\core\core-0011_standard_texts.sql")
    run_sql_file("ux_housing", repo + r"\features\housing\housing-0003_industry_text.sql")
    run_sql_file("ux_jewellery", repo + r"\core\core-0011_standard_texts.sql")
    run_sql_file("ux_jewellery", repo + r"\features\jewellery\jewellery-0001_industry_text.sql")
    ids = await seed_housing()
    await seed_jewellery()
    await seed_routing(ids)
    print("ready. The made-up accounts use the password you set in UX_PASSWORD.")
    print("cases:", len(ids["case"]), "| people:", len(ids["user"]), "| flows:", len(ids["flow"]))


asyncio.run(main())
