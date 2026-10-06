"""The step window on the flow canvas: its pieces are in the page, and it only ever rehearses."""

from app.admin_panel.ui import APP_CSS, APP_JS, js_stepwin
from app.main import app


def test_the_step_window_is_part_of_the_page():
    for piece in [
        "function swOpen",
        "function swTest",
        "function cvMenu",
        "function cvRename",
        "Test this step",
        "Comes in",
        "Goes out",
    ]:
        assert piece in APP_JS, piece
    assert ".sw{" in APP_CSS


def test_the_window_can_only_rehearse():
    # it asks for the same rehearsal as "Try it": reads run, saving and sending are only described
    assert "/studio/try" in js_stepwin.JS
    assert "dry_run" not in js_stepwin.JS
    posts = {
        r.path for r in app.routes if "POST" in (getattr(r, "methods", None) or ())
    }
    assert any(p.endswith("/studio/try") for p in posts)


def test_there_is_a_way_in_from_every_side():
    assert "swOpen(idAt(i))" in APP_JS  # the button in the side panel
    assert "Open in a bigger window" in APP_JS
    assert "'Test this step'" in APP_JS  # the bar above a box and the right-click menu
    assert "'contextmenu'" in APP_JS
    assert "e.key === 'F2'" in APP_JS or "'F2'" in APP_JS


def test_escape_only_closes_the_window():
    # the Escape that closes the window must not also clear the chosen step
    assert "swClosedAt" in js_stepwin.JS
    assert "Date.now() - swClosedAt" in APP_JS


def test_a_missing_value_is_told_plainly_and_the_engines_words_stay_in_the_table():
    assert "function swPlain" in js_stepwin.JS
    assert "Type one under" in js_stepwin.JS
    assert "What it said" in js_stepwin.JS


def test_the_window_is_one_column_on_a_narrow_screen_with_the_settings_first():
    assert ".sw-pm{order:1" in APP_CSS
