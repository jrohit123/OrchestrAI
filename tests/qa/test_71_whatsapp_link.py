"""A person links their WhatsApp number to the account an admin added for them: they write to the chat bot, send
their email, and enter the code emailed to them. Same steps as on Telegram. Email and the model are fake."""

import json

from tests.qa.harness import needs_qa, qa_run

NEWCOMER = "neha@example.test"  # added by an admin (seeded), no chat linked yet
NUMBER = "+919000009901"  # a WhatsApp number nobody has


async def say_to(w, phone, text):
    before = len(w.sent)
    await w.say(phone, text)
    return [m["text"] for m in w.sent[before:] if m["to"] == phone and m.get("text")]


@needs_qa
def test_an_added_person_links_their_whatsapp_number_with_their_email_and_a_code():
    async def scenario(w):
        welcome = await say_to(w, NUMBER, "hi")
        assert len(welcome) == 1 and "WhatsApp number isn't linked" in welcome[0]
        sent = await say_to(w, NUMBER, f"my email is {NEWCOMER}")
        assert (
            len(sent) == 1
            and "link your WhatsApp number" in sent[0]
            and NEWCOMER in sent[0]
        )
        code = w.last_otp(NEWCOMER)
        assert code, "no code was emailed"
        done = await say_to(w, NUMBER, code)
        assert (
            len(done) == 1
            and "Linked" in done[0]
            and "WhatsApp number is now connected" in done[0]
        )
        row = await w.one("SELECT phone, channel FROM users WHERE email = $1", NEWCOMER)
        assert row["phone"] == NUMBER and row["channel"] == "whatsapp"
        # from now on the number is a person: no more welcome
        from app.services.identity import resolve_identity

        assert (await resolve_identity(NUMBER))["user_name"] == "Neha Newcomer"

    qa_run(scenario)


@needs_qa
def test_a_wrong_code_does_not_link_the_number():
    async def scenario(w):
        await w.say(NUMBER, NEWCOMER)
        real = w.last_otp(NEWCOMER)
        wrong = "000000" if real != "000000" else "111111"
        told = await say_to(w, NUMBER, wrong)
        assert told and "Incorrect" in told[0]
        row = await w.one("SELECT phone FROM users WHERE email = $1", NEWCOMER)
        assert not row["phone"]

    qa_run(scenario)


@needs_qa
def test_a_person_moves_from_telegram_to_whatsapp_with_the_same_steps():
    async def scenario(w):
        await w.run(
            "UPDATE users SET phone = 'tg:777', channel = 'telegram' WHERE email = $1",
            NEWCOMER,
        )
        await w.say(NUMBER, NEWCOMER)
        code = w.last_otp(NEWCOMER)
        assert code, "a person on Telegram could not ask for the move"
        await w.say(NUMBER, code)
        row = await w.one("SELECT phone, channel FROM users WHERE email = $1", NEWCOMER)
        assert row["phone"] == NUMBER and row["channel"] == "whatsapp"

    qa_run(scenario)


@needs_qa
def test_a_person_who_is_already_on_whatsapp_cannot_be_taken_over_by_another_number():
    async def scenario(w):
        member = await w.user("member")
        told = await say_to(w, NUMBER, member["email"])
        assert not w.last_otp(member["email"]), (
            "a code went out for a person who is already linked on WhatsApp"
        )
        assert told and "No account found" in told[0]
        row = await w.one("SELECT phone FROM users WHERE email = $1", member["email"])
        assert row["phone"] == member["phone"]

    qa_run(scenario)


@needs_qa
def test_an_email_nobody_added_is_refused_when_sign_up_by_chat_is_closed():
    async def scenario(w):
        told = await say_to(w, NUMBER, "stranger@example.test")
        assert told and "sign-up by chat is not open" in told[0]
        assert not w.last_otp("stranger@example.test")

    qa_run(scenario)


@needs_qa
def test_the_whatsapp_link_can_be_switched_off_for_the_client_that_owns_whatsapp():
    async def scenario(w):
        await w.run(
            "UPDATE orgs SET settings = coalesce(settings, '{}'::jsonb) || $1::jsonb",
            json.dumps({"onboarding": {"whatsapp_link": False}}),
            kind="jewellery",
        )
        told = await say_to(w, NUMBER, NEWCOMER)
        assert told == [
            "👋 Your number isn't registered with OrchestrAI.\nContact your admin to get access."
        ]
        assert not w.last_otp(NEWCOMER)

    qa_run(scenario, kinds=("housing", "jewellery"))


@needs_qa
def test_a_person_who_is_in_two_clients_links_to_the_one_that_owns_whatsapp():
    async def scenario(w):
        role = await w.one("SELECT id FROM roles LIMIT 1", kind="jewellery")
        org = await w.one("SELECT id FROM orgs LIMIT 1", kind="jewellery")
        await w.run(
            "INSERT INTO users (org_id, role_id, name, phone, email, channel) VALUES ($1, $2, 'Neha Newcomer', NULL, $3, 'whatsapp')",
            org["id"],
            role["id"],
            NEWCOMER,
            kind="jewellery",
        )
        await w.say(NUMBER, NEWCOMER)
        await w.say(NUMBER, w.last_otp(NEWCOMER))
        mine = await w.one(
            "SELECT phone FROM users WHERE email = $1", NEWCOMER, kind="jewellery"
        )
        other = await w.one(
            "SELECT phone FROM users WHERE email = $1", NEWCOMER, kind="housing"
        )
        assert mine["phone"] == NUMBER and not other["phone"]

    qa_run(scenario, kinds=("housing", "jewellery"))
