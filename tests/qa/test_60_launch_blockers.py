"""The launch blockers (P0 in docs/launch/QA-priority-work-order.md): tests written for them.

Each test fails before its fix and passes after it. They run on throwaway databases like the rest of tests/qa.
"""

from tests.qa.harness import _patch, needs_qa, qa_run

# ───────────────────────────── P0-1 · the open doors (QA-015, QA-002) ─────────────────────────────


@needs_qa
def test_I02_the_debug_routes_are_gone():
    async def scenario(w):
        async with w.client() as c:
            for path in ("/debug/schema/" + w.key, "/debug/clear-schema-cache"):
                answer = await c.get(path)
                assert answer.status_code in (401, 403, 404, 405), (
                    f"{path} answered {answer.status_code}"
                )
                assert "tables" not in answer.text

    qa_run(scenario)


@needs_qa
def test_I03_health_makes_no_paid_calls():
    async def scenario(w):
        from app import main

        class Boom:
            made = 0

            def __init__(self, *a, **k):
                Boom.made += 1
                raise AssertionError(
                    "/health created an AI client: that is a paid call on every visit"
                )

        _patch(w, main, "AsyncOpenAI", Boom)
        async with w.client() as c:
            answer = await c.get("/health")
        assert answer.status_code == 200
        body = answer.json()
        assert Boom.made == 0
        outside = [u for u in w.http_calls if "testserver" not in u]
        assert not outside, f"/health reached out to {outside}"
        assert {"database", "redis"} <= set(body["dependencies"])
        assert not ({"openai", "cerebras", "llm_ladder"} & set(body["dependencies"]))

    qa_run(scenario)


@needs_qa
def test_I04_the_deep_health_check_needs_a_super_admin_sign_in():
    async def scenario(w):
        async with w.client() as c:
            answer = await c.get("/health/deep")
        assert answer.status_code == 401

    qa_run(scenario)
