"""The harness itself: it must be local, closed to the outside, and deterministic."""

import httpx
import pytest

from tests.qa.harness import ADMIN_DSN, NetworkBlocked, needs_qa, qa_run, require_local


def test_a_database_that_is_not_on_this_computer_is_refused():
    with pytest.raises(RuntimeError):
        require_local("postgresql://u:p@db.example.com:5432/x")
    require_local("postgresql://u@127.0.0.1:5432/x")
    require_local("postgresql://u@localhost/x")


@needs_qa
def test_the_world_is_local_seeded_and_closed_to_the_network():
    assert "127.0.0.1" in ADMIN_DSN or "localhost" in ADMIN_DSN

    async def scenario(w):
        # every pool the app can reach is a database made for this test
        from app import db

        assert set(db._pools) == {w.key}
        assert all(name.startswith("qa_") for name in w.dbs.values())
        # synthetic people can be found by their phone
        admin = await w.user("admin")
        assert admin["role"] == "admin" and "qa_case_file" in admin["permissions"]
        # a message to the bot goes through the whole handler without the outside world
        await w.login("admin")
        await w.say(w.ids.phone_admin, "/status")
        assert w.texts_to(w.ids.phone_admin), "the bot answered nothing"
        # the network is shut
        async with httpx.AsyncClient() as client:
            with pytest.raises(NetworkBlocked):
                await client.get("https://example.com/")
        # the model is shut unless the test gives it an answer
        from app.services import llm_router

        with pytest.raises(AssertionError):
            await llm_router.chat_completion(messages=[])

    qa_run(scenario)
