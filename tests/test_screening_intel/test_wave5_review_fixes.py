"""Wave 5 review fixes: tenancy inert when off, payment greenlet releases its connection,
remember-me cannot bypass the absolute session limit, MFA grace rules, idempotency take-over,
webhook SSRF (public addresses only, pinned connection)."""
import sys, types
from datetime import datetime, timezone, timedelta

import flask
import pytest


def test_before_request_does_not_touch_db_when_tenancy_off(monkeypatch):
    monkeypatch.delenv('TENANCY_ENFORCED', raising=False)
    from database import tenancy as T
    calls = []
    monkeypatch.setattr(T, 'bind', lambda *a, **k: calls.append(a) or True)
    monkeypatch.setattr(T, 'current_tenant_id', lambda: 1)
    app = flask.Flask('t5')
    T.init_app(app)

    @app.route('/x')
    def x():
        return 'ok'
    with app.test_request_context('/x'):
        flask.g.db = types.SimpleNamespace(_conn=object())
        for fn in app.before_request_funcs[None]:
            fn()
        assert flask.g.tenant_id == 1
    assert calls == []
    monkeypatch.setenv('TENANCY_ENFORCED', '1')
    with app.test_request_context('/x'):
        flask.g.db = types.SimpleNamespace(_conn=object())
        for fn in app.before_request_funcs[None]:
            fn()
    assert len(calls) == 1


def test_payment_evidence_greenlet_releases_connection(monkeypatch):
    from api import screening_v1 as S
    released = []
    fake_app = types.ModuleType('app')
    fake_app.release_screening_db_conn = lambda: released.append(1) or True
    monkeypatch.setitem(sys.modules, 'app', fake_app)
    fake_css = types.ModuleType('screening.customer_screening_service')
    fake_css.screen_and_save = lambda **kw: (_ for _ in ()).throw(RuntimeError('engine down'))
    monkeypatch.setitem(sys.modules, 'screening.customer_screening_service', fake_css)
    ran = []

    class _G:
        @staticmethod
        def spawn(fn):
            ran.append(1)
            fn()
    monkeypatch.setitem(sys.modules, 'gevent', _G)
    app = flask.Flask('t5b')
    with app.app_context():
        S._persist_hits_in_background(7, [{'name': 'X', 'entity_type': 'INDIVIDUAL', 'country': None}], 1)
    assert ran == [1] and released == [1]


def test_absolute_session_limit_also_clears_remember_me(monkeypatch):
    from auth import session_policy as SP
    app = flask.Flask('t5c')
    app.secret_key = 'x'
    bp = flask.Blueprint('b', __name__)
    SP.register(bp)
    app.register_blueprint(bp)
    user = types.SimpleNamespace(is_authenticated=True, id=1, can_access_cms=lambda: True)
    monkeypatch.setattr(SP, 'current_user', user, raising=False)
    monkeypatch.setattr(SP, 'logout_user', lambda: None, raising=False)
    monkeypatch.setattr(SP, 'expired', lambda started: True)
    monkeypatch.setattr(SP, 'redirect', lambda u: ('redirect', 302), raising=False)
    monkeypatch.setattr(SP, 'url_for', lambda e: '/login', raising=False)
    monkeypatch.setattr(SP, 'flash', lambda *a, **k: None, raising=False)
    monkeypatch.setattr(SP, '_', lambda s, **k: s, raising=False)
    with app.test_request_context('/anything'):
        flask.session[SP.KEY] = 1.0
        for fn in app.before_request_funcs[None]:
            fn()
        assert flask.session.get('_remember') == 'clear'


def test_mfa_grace_rules():
    from auth import mfa_policy as mp
    now = datetime.now(timezone.utc)
    assert mp.can_defer(now, 'manager') is True
    assert mp.can_defer(now, 'manager', override=True) is False       # required by an admin
    assert mp.can_defer(None, 'manager') is False                     # no recorded prompt time
    assert mp.days_left(now - timedelta(days=1), 'manager', override=True) == 0


class _IdemDB:
    """Just enough of get_db() for the idempotent() decorator."""
    def __init__(self, stale):
        self.stale = stale
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        s = ' '.join(sql.split())
        row = None
        if s.startswith('INSERT INTO api_idempotency'):
            row = None                                   # key already there
        elif s.startswith('UPDATE api_idempotency SET created_at'):
            row = {'id': 9} if self.stale else None      # take-over only when stale
        elif s.startswith('SELECT request_hash'):
            row = {'request_hash': params and 'h', 'status_code': None, 'response': None}
        return types.SimpleNamespace(fetchone=lambda: row)

    def commit(self): pass
    def rollback(self): pass


@pytest.mark.parametrize('stale,expect', [(True, 200), (False, 409)])
def test_idempotency_takes_over_stale_in_progress_rows(monkeypatch, stale, expect):
    from api import screening_v1 as S
    db = _IdemDB(stale)
    monkeypatch.setattr(S, 'get_db', lambda: db)
    monkeypatch.setattr(S.C, 'request_hash', lambda *a: 'h')
    app = flask.Flask('t5d')

    @S.idempotent
    def view():
        r = flask.jsonify({'ok': True})
        r.status_code = 200
        return r
    with app.test_request_context('/x', method='POST', headers={'Idempotency-Key': 'k1'}, data=b'{}'):
        flask.g.api_client = 1
        resp = view()
        code = resp.status_code if hasattr(resp, 'status_code') else resp[1]
    assert code == expect


def test_webhook_addresses_must_be_public(monkeypatch):
    from api import v1_common as C
    for ip in ('10.0.0.1', '127.0.0.1', '100.64.1.1', '169.254.169.254', '192.0.2.10', '::1',
               '::ffff:10.1.2.3', 'fc00::1', '224.0.0.1'):
        assert C._ip_blocked(ip), ip
    assert not C._ip_blocked('8.8.8.8')
    monkeypatch.setattr(C.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('8.8.8.8', 443)),
                                                                   (0, 0, 0, '', ('10.0.0.5', 443))])
    with pytest.raises(ValueError):
        C.resolve_public_ip('example.com')
    monkeypatch.setattr(C.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('8.8.4.4', 443))])
    assert C.resolve_public_ip('example.com') == '8.8.4.4'


def test_webhook_post_is_pinned_to_the_checked_address(monkeypatch):
    from api import webhooks as W
    import urllib3
    seen = {}
    monkeypatch.setattr(W.C, 'resolve_public_ip', lambda host, port=443: '8.8.4.4')

    class Pool:
        def __init__(self, host, **kw):
            seen['ip'] = host
            seen.update(kw)

        def urlopen(self, method, path, **kw):
            seen['path'] = path
            seen['headers'] = kw['headers']
            return types.SimpleNamespace(status=204)

        def close(self): pass
    monkeypatch.setattr(urllib3, 'HTTPSConnectionPool', Pool)
    r = W._post('https://hooks.example.com/in?x=1', b'{}', {'Content-Type': 'application/json'})
    assert r.status_code == 204
    assert seen['ip'] == '8.8.4.4' and seen['server_hostname'] == 'hooks.example.com'
    assert seen['assert_hostname'] == 'hooks.example.com' and seen['headers']['Host'] == 'hooks.example.com'
    assert seen['path'] == '/in?x=1'
