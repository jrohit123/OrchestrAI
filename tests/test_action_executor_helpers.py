"""Unit tests for action_executor helpers (no DB required)."""
import pytest
from app.services.action_executor import _resolve_amount, _is_valid_uuid


def test_resolve_amount_from_items():
    fields = {
        "items": [
            {"total": 339900},
            {"total": 10000},
        ]
    }
    assert _resolve_amount(fields) == 349900.0


def test_resolve_amount_top_level():
    assert _resolve_amount({"amount": 45000}) == 45000.0


def test_resolve_amount_empty():
    assert _resolve_amount({}) == 0.0


def test_is_valid_uuid():
    assert _is_valid_uuid("cc111111-0000-0000-0000-000000000006") is True
    assert _is_valid_uuid("uuid") is False
    assert _is_valid_uuid(None) is False
