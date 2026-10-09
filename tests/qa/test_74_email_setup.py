"""A person an admin added with only a name and a number has no email yet. Their number is known, so there is no
sign-up: on their first message the chat bot asks for their email, sends a code to it, and saves it when the code
comes back. Email and the model are fake, as everywhere in this harness."""

from app.services.identity import resolve_identity
from tests.qa.harness import llm_message, needs_qa, qa_run

NUMBER = "+919000009955"
MAIL = "chetan@example.test"


async def added_with_only_a_number(w, name="Chetan Bhandare"):
    role = await w.one("SELECT id FROM roles WHERE name = 'member' LIMIT 1")
    await w.run(
        "INSERT INTO users (org_id, role_id, name, phone, email, channel) VALUES ($1, $2, $3, $4, NULL, 'whatsapp')",
        w.ids.org_id,
        role["id"],
        name,
        NUMBER,
    )


async def say_to(w, text):
    before = len(w.sent)
    await w.say(NUMBER, text)
    return [m["text"] for m in w.sent[before:] if m["to"] == NUMBER and m.get("text")]


@needs_qa
def test_a_person_added_with_only_a_number_is_asked_for_their_email_by_name():
    async def scenario(w):
        await added_with_only_a_number(w)
        told = await say_to(w, "hi")
        assert (
            len(told) == 1
            and "Welcome, Chetan!" in told[0]
            and "email address" in told[0]
        )

    qa_run(scenario)


@needs_qa
def test_the_email_is_confirmed_with_a_code_and_then_saved_on_their_account():
    async def scenario(w):
        await added_with_only_a_number(w)
        await say_to(w, "hi")
        sent = await say_to(w, f"my email is {MAIL}")
        assert len(sent) == 1 and MAIL in sent[0] and "verification code" in sent[0]
        code = w.last_otp(MAIL)
        assert code, "no code was emailed"
        assert not (await w.one("SELECT email FROM users WHERE phone = $1", NUMBER))[
            "email"
        ]  # not yet
        done = await say_to(w, code)
        assert len(done) == 1 and "All set, Chetan" in done[0]
        assert (await w.one("SELECT email FROM users WHERE phone = $1", NUMBER))[
            "email"
        ] == MAIL
        assert (await resolve_identity(NUMBER))["email"] == MAIL

    qa_run(scenario)


@needs_qa
def test_after_that_the_person_is_not_asked_again_and_is_not_asked_for_a_second_code():
    async def scenario(w):
        await added_with_only_a_number(w)
        await say_to(w, MAIL)
        await say_to(w, w.last_otp(MAIL))
        w.llm.handler(lambda *a, **k: llm_message(content="Hello there"))
        told = await say_to(w, "hello")
        assert told == [
            "Hello there"
        ]  # an ordinary answer: no email question, no security code

    qa_run(scenario)


@needs_qa
def test_a_wrong_code_saves_nothing():
    async def scenario(w):
        await added_with_only_a_number(w)
        await say_to(w, MAIL)
        real = w.last_otp(MAIL)
        told = await say_to(w, "000000" if real != "000000" else "111111")
        assert told and "Incorrect" in told[0]
        assert not (await w.one("SELECT email FROM users WHERE phone = $1", NUMBER))[
            "email"
        ]

    qa_run(scenario)


@needs_qa
def test_an_email_that_someone_else_here_already_uses_is_refused():
    async def scenario(w):
        await added_with_only_a_number(w)
        member = await w.user("member")
        told = await say_to(w, member["email"])
        assert told and "already used by someone else" in told[0]
        assert not w.last_otp(member["email"])  # no code went to that person's inbox

    qa_run(scenario)


@needs_qa
def test_a_message_without_an_email_asks_again_and_retry_starts_over():
    async def scenario(w):
        await added_with_only_a_number(w)
        first = await say_to(w, "what is this?")
        assert "email address" in first[0]
        await say_to(w, MAIL)
        again = await say_to(w, "retry")
        assert "email address" in again[0]
        assert not (await w.one("SELECT email FROM users WHERE phone = $1", NUMBER))[
            "email"
        ]

    qa_run(scenario)
