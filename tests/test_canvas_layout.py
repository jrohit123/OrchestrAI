"""The saved canvas layout: where the boxes sit, and how they were arranged with Tidy up."""

import pytest
from pydantic import ValidationError

from app.admin_panel.studio import Layout

STEPS = [[0.0, 0.0], [100.0, 0.0], [0.0, 200.0]]


def test_a_layout_saved_before_arrangements_existed_is_still_valid():
    out = Layout(v=1, n=3, steps=STEPS).model_dump(exclude_none=True)
    assert "mode" not in out and "cols" not in out


@pytest.mark.parametrize("mode", ["column", "rows", "stage"])
def test_the_arrangement_and_the_boxes_per_row_are_kept(mode):
    out = Layout(v=1, n=3, steps=STEPS, mode=mode, cols=4).model_dump(exclude_none=True)
    assert out["mode"] == mode and out["cols"] == 4


@pytest.mark.parametrize(
    "extra",
    [{"mode": "spiral"}, {"cols": 0}, {"cols": 9}, {"mode": "rows", "colour": "red"}],
)
def test_anything_that_is_not_an_arrangement_is_refused(extra):
    with pytest.raises(ValidationError):
        Layout(v=1, n=3, steps=STEPS, **extra)
