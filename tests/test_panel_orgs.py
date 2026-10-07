"""The Organisations page: a super admin sees every organisation, an admin only her own, with a way
to open the dashboard and a way back.

The first test needs no database. The second calls the dashboard in-process on the throwaway
databases of test_migrate.py (see test_panel_login.py)."""

from app.admin_panel.ui import js_auth, js_boot, js_super
from tests.test_migrate import needs_pg
from tests.test_panel_login import GOOD, run


def test_the_screens_give_an_admin_the_organisations_page_and_a_way_back():
    # the page reads her own list, not the super admins' list
    assert "authApi.get(isSuper() ? '/orgs' : '/my-orgs')" in js_super.JS
    # an admin has that one page of the super admin's menu and no other
    assert "SUPER_TABS.filter(t => t[0] === 'orgs')" in js_super.JS
    assert "allowed.includes(r.section) ? r.section : allowed[0]" in js_super.JS
    # who else can sign in, and giving access, stay with super admins
    assert "isSuper() ? admins(o) : null" in js_super.JS
    assert "isSuper() ? h('button'" in js_super.JS
    # signing in at /admin no longer sends an admin straight into her organisation
    assert "account.orgs.length === 1" not in js_auth.JS
    # and from inside an organisation there is a way back to the page, for both levels
    word = "isSuper() ? 'All organisations' : 'My organisations'"
    assert word in js_auth.JS and word in js_boot.JS


@needs_pg
def test_the_organisations_an_account_may_open_are_listed_and_no_others(
    world, monkeypatch
):
    async def scenario(p):
        await p.add_account("kartik@x.test", "Kartik", "super", (), "active", GOOD)
        anuja = await p.add_account(
            "anuja@x.test", "Anuja", "admin", ["alpha"], "active", GOOD
        )
        await p.add_account(
            "zoya@x.test", "Zoya", "admin", ["alpha", "beta"], "active", GOOD
        )
        await p.add_account(
            "ghost@x.test", "Ghost", "admin", ["nowhere"], "active", GOOD
        )

        async with p.client() as anon:
            assert (await anon.get("/admin/_auth/my-orgs")).status_code == 401

        async def orgs_of(who):
            async with p.client() as c:
                assert (await p.sign_in(c, who)).status_code == 200
                r = await c.get("/admin/_auth/my-orgs")
                assert r.status_code == 200
                return r.json()["orgs"]

        everything = await orgs_of("kartik@x.test")
        assert [o["key"] for o in everything] == ["alpha", "beta"]
        assert [o["name"] for o in everything] == ["Alpha Co", "Beta Co"]

        mine = await orgs_of("anuja@x.test")
        assert [o["key"] for o in mine] == ["alpha"] and mine[0]["name"] == "Alpha Co"
        assert "people" in mine[0] and "channel" in mine[0]
        assert "admins" not in mine[0]  # who else can sign in is for super admins
        assert [o["key"] for o in await orgs_of("zoya@x.test")] == ["alpha", "beta"]
        assert await orgs_of("ghost@x.test") == []  # an organisation that is not there

        async with p.client() as s, p.client() as a:
            await p.sign_in(s, "kartik@x.test")
            await p.sign_in(a, "anuja@x.test")
            # the super admins' own list still names the admins, and an admin may not read it
            sup = (await s.get("/admin/_auth/orgs")).json()["orgs"]
            assert all("admins" in o for o in sup)
            assert {x["name"] for x in sup[0]["admins"]} == {"Anuja", "Zoya"}
            assert (await a.get("/admin/_auth/orgs")).status_code == 403
            # switching her off closes the page at once
            assert (await a.get("/admin/_auth/my-orgs")).status_code == 200
            r = await s.post(
                f"/admin/_auth/accounts/{anuja}/switch", json={"on": False}
            )
            assert r.status_code == 200
            assert (await a.get("/admin/_auth/my-orgs")).status_code == 401

    run(world, monkeypatch, scenario)
