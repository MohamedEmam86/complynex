"""Phase 6 security (P6-5 / P6-6): pure-logic tests (no database)."""
import json
from datetime import datetime, timedelta, timezone

from auth import guard, mfa_policy as mp, session_policy as sp, password_policy as pp


def test_lock_backoff_doubles_and_caps():
    assert guard.lock_minutes(0) == guard.LOCK_MINUTES
    assert guard.lock_minutes(1) == guard.LOCK_MINUTES * 2
    assert guard.lock_minutes(2) == guard.LOCK_MINUTES * 4
    assert guard.lock_minutes(50) == guard.LOCK_MAX_MINUTES
    assert guard.lock_minutes(None) == guard.LOCK_MINUTES


def test_grace_privileged_none_by_default(monkeypatch):
    monkeypatch.delenv('MFA_ENROLL_GRACE_DAYS_PRIVILEGED', raising=False)
    monkeypatch.delenv('MFA_ENROLL_GRACE_DAYS', raising=False)
    now = datetime.now(timezone.utc)
    for role in ('admin', 'compliance_manager', 'compliance_officer'):
        assert mp.can_defer(now, role) is False
    assert mp.can_defer(now, 'manager') is True
    assert mp.can_defer(now - timedelta(days=8), 'manager') is False
    assert mp.days_left(now - timedelta(days=2), 'manager') in (5, 6)


def test_grace_configurable(monkeypatch):
    monkeypatch.setenv('MFA_ENROLL_GRACE_DAYS', '0')
    assert mp.can_defer(datetime.now(timezone.utc), 'employee') is False
    monkeypatch.setenv('MFA_ENROLL_GRACE_DAYS_PRIVILEGED', '3')
    assert mp.can_defer(datetime.now(timezone.utc), 'admin') is True


def test_backup_codes_hashed_and_single_use():
    shown, stored = mp.new_backup_codes(4)
    assert len(shown) == 4 and all(len(c) == 11 and c[5] == '-' for c in shown)
    assert all(mp.is_hashed(e) for e in json.loads(stored))
    assert shown[0].replace('-', '') not in stored
    ok, rest = mp.consume_backup_code(stored, shown[1].lower())
    assert ok and mp.remaining(rest) == 3
    ok2, _ = mp.consume_backup_code(rest, shown[1])
    assert not ok2                                   # used once only
    assert not mp.consume_backup_code(rest, 'WRONG-CODE0')[0]


def test_legacy_clear_codes_still_work_once_and_get_hashed():
    legacy = json.dumps(['AB12CD34', 'EF56AB78'])
    ok, rest = mp.consume_backup_code(legacy, 'ab12-cd34')
    assert ok and mp.remaining(rest) == 1
    assert all(mp.is_hashed(e) for e in json.loads(rest))
    assert mp.consume_backup_code(rest, 'EF56AB78')[0]
    h = mp.hash_legacy(legacy)
    assert h and all(mp.is_hashed(e) for e in json.loads(h))
    assert mp.hash_legacy(h) is None


def test_absolute_session_expiry(monkeypatch):
    monkeypatch.setenv('SESSION_ABSOLUTE_HOURS', '12')
    assert sp.absolute_seconds() == 12 * 3600
    assert not sp.expired(None)
    assert not sp.expired(1000.0, now=1000.0 + 11 * 3600)
    assert sp.expired(1000.0, now=1000.0 + 13 * 3600)


def test_password_identity_rule():
    assert pp.contains_identity('Blue#Harbor2026x', 'mohamed.emam@example.com') is False
    assert pp.contains_identity('Mohamed.Emam2026!', 'mohamed.emam@example.com') is True
    assert pp.contains_identity('xxMohamedEmam!!99', 'mohamed.emam@example.com') is True
    assert pp.contains_identity('Abc!1234567xyz', 'ab@x.com') is False                    # short local part ignored


def test_audit_rows_reads_wrapped_cursor():
    from utils.audit_chain import _rows

    class Raw:
        description = [('broken_id',), ('checked',)]
        def execute(self, q, a=()): pass
        def fetchall(self): return [(None, 7)]

    class Wrapped:                       # the app's DictCursor has no .description of its own
        def __init__(self): self._cursor = Raw()
        def execute(self, q, a=()): return self
        def fetchall(self): return self._cursor.fetchall()

    class DB:
        def cursor(self): return Wrapped()

    assert _rows(DB(), 'x') == [{'broken_id': None, 'checked': 7}]
