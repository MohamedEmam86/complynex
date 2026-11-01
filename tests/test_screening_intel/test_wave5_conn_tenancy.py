"""Wave 5: the screening engine's per-greenlet DB connection is returned at request end."""
import sys, types


def test_release_returns_connection_and_is_cheap_when_idle(monkeypatch):
    import app as appmod
    returned = []

    class Inner:
        def __init__(self):
            self.db_conn = object()

    class Eng:
        def __init__(self):
            self.local_engine = Inner()

        def close(self):
            returned.append(self.local_engine.db_conn)
            self.local_engine.db_conn = None

    fake = types.ModuleType('screening.routes')
    fake._engine_instance = Eng()
    monkeypatch.setitem(sys.modules, 'screening.routes', fake)
    assert appmod.release_screening_db_conn() is True
    assert len(returned) == 1
    # nothing held any more: no second close
    assert appmod.release_screening_db_conn() is False
    assert len(returned) == 1


def test_release_without_engine_does_nothing(monkeypatch):
    import app as appmod
    fake = types.ModuleType('screening.routes')
    fake._engine_instance = None
    monkeypatch.setitem(sys.modules, 'screening.routes', fake)
    assert appmod.release_screening_db_conn() is False


def test_tenancy_bind_skipped_when_flag_off(monkeypatch):
    monkeypatch.delenv('TENANCY_ENFORCED', raising=False)
    from database import tenancy as T
    calls = []
    monkeypatch.setattr(T, 'bind', lambda *a, **k: calls.append(a) or True)
    import flask
    app = flask.Flask('t')
    with app.test_request_context('/'):
        flask.g.db = types.SimpleNamespace(_conn=object())
        T.set_request_tenant(5)
        assert flask.g.tenant_id == 5
    assert calls == []
