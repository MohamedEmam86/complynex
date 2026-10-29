"""Thresholds are one source of truth, validated, and applied to the matching code (Phase 2)."""
from screening import thresholds as T
from screening import match_intel as mi


def test_validate_bounds_and_order():
    assert T.validate({'low': 75, 'potential': 80, 'confirmed': 95}) == []
    assert T.validate({'low': 80, 'potential': 75, 'confirmed': 95})          # inverted
    assert T.validate({'low': 50, 'potential': 80, 'confirmed': 95})          # below the floor
    assert T.validate({'low': 75, 'potential': 80, 'confirmed': 85})          # confirmed too low


def test_apply_pushes_values(monkeypatch):
    monkeypatch.setattr(T, 'current', lambda force=False: {'low': 72.0, 'potential': 82.0, 'confirmed': 96.0})

    class E:
        pass
    e = E()
    T.apply(e)
    try:
        assert (mi.LOW, mi.POTENTIAL, mi.CONFIRMED) == (72.0, 82.0, 96.0)
        assert E.LOW_MATCH_THRESHOLD == 72.0 and E.CONFIRMED_HIT_THRESHOLD == 96.0
    finally:
        mi.LOW, mi.POTENTIAL, mi.CONFIRMED = 75.0, 80.0, 95.0


def test_invalid_db_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setattr(T, '_read_db', lambda: {'low': 90.0, 'potential': 70.0, 'confirmed': 95.0})
    assert T.current(force=True) == T.DEFAULTS
