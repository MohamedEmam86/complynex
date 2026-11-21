"""Client sites (client_sites/service.py): host resolution, host-header validation, per-host session cookie,
sign-in binding, the monthly organisation cap, the logo checks and the access registry. No database: the
active sites and the counters are replaced in memory (the database tests are test_client_sites_db.py)."""
import os

import pytest

os.environ.setdefault('SECRET_KEY', 'test-only-secret-key-not-used-in-production')   # config.py needs one to import

from client_sites import service as CS  # noqa: E402
from client_sites.service import Site

SITE_HOST = 'acme.example.test'
OTHER_HOST = 'other.example.test'


def _site(i, host, **kw):
    d = dict(id=i, host=host, name_en='Example Client', name_ar='عميل تجريبي', welcome_en='Welcome, team.',
             welcome_ar='مرحباً بفريقنا.', logo_path=None, allowed_access_modes=['restricted'],
             default_access_mode='restricted', contact_email=None, default_daily_screening_limit=None,
             monthly_org_cap=0, active=True)
    d.update(kw)
    return Site(d)


SITES = {SITE_HOST: _site(7, SITE_HOST), OTHER_HOST: _site(8, OTHER_HOST, name_en='Second Client')}


@pytest.fixture(scope='module')
def app():
    from config import config
    old = os.environ.get('FLASK_ENV')
    if old not in config:
        os.environ['FLASK_ENV'] = 'development'
    try:
        from app import create_app
        a = create_app('development')
    finally:
        if old is None:
            os.environ.pop('FLASK_ENV', None)
        else:
            os.environ['FLASK_ENV'] = old
    a.config['WTF_CSRF_ENABLED'] = False
    a.config['TESTING'] = True
    return a


@pytest.fixture(autouse=True)
def sites(monkeypatch):
    monkeypatch.setattr(CS, 'active_sites', lambda: SITES)
    yield SITES


class U:
    def __init__(self, uid, site_id=None, role='employee', mode='restricted'):
        self.id, self.site_id, self.role, self.access_mode = uid, site_id, role, mode
        self._site_loaded = True
        self.is_authenticated = True


def test_main_hosts_default_and_extra(app):
    hosts = CS.main_hosts(app)
    for h in ('complynex.online', 'www.complynex.online', 'localhost', '127.0.0.1'):
        assert h in hosts
    assert SITE_HOST not in hosts
    assert CS.normalise_host('ACME.Example.test:443') == SITE_HOST
    assert CS.normalise_host('[::1]:8000') == '[::1]'


def test_host_resolution(app):
    with app.test_request_context('/', base_url='http://' + SITE_HOST):
        assert CS.site_for_request()['id'] == 7
    with app.test_request_context('/', base_url='http://localhost'):
        assert CS.site_for_request() is None
    with app.test_request_context('/', base_url='http://acme.example.test:8443'):
        assert CS.site_for_request()['id'] == 7


def test_unknown_host_404_main_host_unchanged(app):
    c = app.test_client()
    r = c.get('/auth/login', base_url='http://unknown.example.test')
    assert r.status_code == 404
    r = c.get('/health', base_url='http://unknown.example.test')
    assert r.status_code == 404
    r = c.get('/auth/login', base_url='http://localhost')
    assert r.status_code == 200
    assert b'ComplyNex for' not in r.data


def test_host_validation_switch(app):
    app.config['HOST_VALIDATION'] = '0'
    try:
        r = app.test_client().get('/auth/login', base_url='http://unknown.example.test')
        assert r.status_code == 200
    finally:
        app.config.pop('HOST_VALIDATION', None)


def test_branded_login_on_site_host(app):
    c = app.test_client()
    for path in ('/auth/login', '/auth/portal/login', '/workspace/login'):
        r = c.get(path, base_url='http://' + SITE_HOST)
        assert r.status_code == 200, path
        body = r.get_data(as_text=True)
        assert ('Example Client' in body and 'Welcome, team.' in body) or \
            ('عميل تجريبي' in body and 'مرحباً بفريقنا.' in body)
        assert 'ComplyNex' in body and 'cx-site-foot' in body and '/auth/site-logo/' not in body   # no logo stored
        assert ' onclick=' not in body and ' onload=' not in body
        assert 'name="ws" value="1"' in body


def test_cookie_name_per_host(app):
    base = app.config.get('SESSION_COOKIE_NAME') or 'session'
    with app.test_request_context('/', base_url='http://' + SITE_HOST):
        assert app.session_interface.get_cookie_name(app) == 'cx_session_7'
    with app.test_request_context('/', base_url='http://' + OTHER_HOST):
        assert app.session_interface.get_cookie_name(app) == 'cx_session_8'
    with app.test_request_context('/', base_url='http://localhost'):
        assert app.session_interface.get_cookie_name(app) == base
    # a real response on the site host sets the site's own cookie (the sign-in page stores the CSRF token)
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        r = app.test_client().get('/auth/login', base_url='http://' + SITE_HOST)
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
    cookies = r.headers.getlist('Set-Cookie')
    assert any(h.startswith('cx_session_7=') for h in cookies), cookies
    assert not any(h.startswith(base + '=') for h in cookies)
    assert all('HttpOnly' in h for h in cookies if h.startswith('cx_session_7='))


def test_cross_host_login_refusal(app):
    site_user, main_user, other_user = U(1, 7), U(2, None), U(3, 8)
    sa = U(4, None, role='superadmin')
    with app.test_request_context('/', base_url='http://' + SITE_HOST):
        assert CS.user_allowed_here(site_user)
        assert not CS.user_allowed_here(main_user)
        assert not CS.user_allowed_here(other_user)
        assert CS.user_allowed_here(sa)
        assert CS.login_user_for_host(main_user) is None
        assert CS.login_user_for_host(site_user) is site_user
    with app.test_request_context('/', base_url='http://localhost'):
        assert CS.user_allowed_here(main_user)
        assert not CS.user_allowed_here(site_user)
        assert CS.user_allowed_here(sa)
        assert CS.login_user_for_host(site_user) is None


def test_access_mode_must_be_allowed_on_site(app, monkeypatch):
    monkeypatch.setattr(CS, '_mode_of', lambda u: u.access_mode)
    with app.test_request_context('/', base_url='http://' + SITE_HOST):
        assert CS.login_user_for_host(U(1, 7, mode='restricted')) is not None
        assert CS.login_user_for_host(U(1, 7, mode='cms')) is None
        assert CS.login_user_for_host(U(4, None, role='superadmin', mode='cms')) is not None


def test_site_user_refused_on_main_host_sign_in(app, monkeypatch):
    """The sign-in form answers exactly like a wrong password (no account enumeration)."""
    from models.user import User
    calls = []

    class Fake(U):
        def check_password(self, pw):
            calls.append(pw)
            return True
    monkeypatch.setattr(User, 'get_by_email', staticmethod(lambda e: Fake(11, 7)))
    from auth import guard
    monkeypatch.setattr(guard, 'is_locked', lambda uid: False)
    monkeypatch.setattr(guard, 'register_failure', lambda uid: False)
    from models.audit import AuditLog
    monkeypatch.setattr(AuditLog, 'log', staticmethod(lambda *a, **k: None))
    r = app.test_client().post('/auth/portal/login', data={'email': 'x@example.test', 'password': 'pw'},
                               base_url='http://localhost')
    assert r.status_code == 200
    assert b'Invalid email or password' in r.data or 'غير صحيح'.encode() in r.data
    assert calls == []          # the password is never even checked for an account of another host


class FakeDB:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        return self

    def fetchone(self):
        return {'n': 0, 'counted': 0, 'screening_daily_limit': None}

    def fetchall(self):
        return []

    def commit(self):
        pass

    def rollback(self):
        pass


def test_monthly_cap(monkeypatch):
    from screening import limits as L
    monkeypatch.setattr(L, 'limit_for', lambda user, db=None: None)
    monkeypatch.setattr(L, '_site_cap', lambda user, db: (7, 10))
    monkeypatch.setattr(CS, 'month_used', lambda sid, day, db=None: 9)
    user = U(1, 7)
    db = FakeDB()
    with pytest.raises(L.MonthlyCapReached) as e:
        L.consume(2, 'vessel', user=user, db=db)
    assert e.value.limit == 10 and e.value.used == 9 and e.value.remaining == 1
    assert e.value.code == 'monthly_cap_reached'
    assert 'monthly' in e.value.message('en') and 'الشهري' in e.value.message('ar')
    assert isinstance(e.value, L.DailyLimitReached)       # the screening error handler answers it
    with pytest.raises(L.MonthlyCapReached):
        L.consume(2, 'dualuse', user=user, db=db)
    assert L.consume(1, 'vessel', user=user, db=FakeDB()) is None       # 9 + 1 = 10: still allowed
    # name screenings are not part of the cap
    monkeypatch.setattr(CS, 'month_used', lambda sid, day, db=None: 10_000)
    assert L.consume(5, 'name', user=user, db=FakeDB()) is None


def test_site_default_daily_limit(monkeypatch):
    from screening import limits as L
    monkeypatch.setattr(L, '_site_default', lambda user, db: 25)
    monkeypatch.setattr(L, 'default_limit', lambda db=None: 100)
    u = U(1, 7)
    u.screening_daily_limit, u._sdl_loaded = None, True
    assert L.limit_for(u, FakeDB()) == 25
    u.screening_daily_limit = 3
    assert L.limit_for(u, FakeDB()) == 3          # the user's own limit wins
    monkeypatch.setattr(L, '_site_default', lambda user, db: None)
    u.screening_daily_limit = None
    assert L.limit_for(u, FakeDB()) == 100        # no site default: the platform default


def test_month_bounds():
    from datetime import date
    assert CS.month_bounds(date(2026, 12, 9)) == (date(2026, 12, 1), date(2027, 1, 1))
    assert CS.month_bounds(date(2026, 2, 28)) == (date(2026, 2, 1), date(2026, 3, 1))


def test_logo_checks():
    png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 10
    with pytest.raises(ValueError):
        CS.check_logo('logo.png', b'')
    with pytest.raises(ValueError) as e:
        CS.check_logo('logo.png', b'\x89PNG\r\n\x1a\n' + b'0' * (CS.LOGO_MAX_BYTES + 1))
    assert str(e.value) == 'too_big'
    with pytest.raises(ValueError):
        CS.check_logo('logo.gif', b'GIF89a....')
    with pytest.raises(ValueError):
        CS.check_logo('logo.png', png)            # not a readable image
    bad = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" onload="alert(1)">'
           b'<script>alert(1)</script><foreignObject><p>x</p></foreignObject>'
           b'<rect width="10" height="10" fill="#123E5F" onclick="x()" style="background:url(http://e.test/a)"/>'
           b'<use xlink:href="http://e.test/s.svg#a"/><a href="javascript:alert(1)"><circle r="2"/></a></svg>')
    ext, out = CS.check_logo('logo.svg', bad)
    s = out.decode()
    assert ext == 'svg' and '<rect' in s and 'fill="#123E5F"' in s
    for needle in ('script', 'onload', 'onclick', 'foreignObject', 'http://e.test', 'javascript', 'style='):
        assert needle not in s, needle
    with pytest.raises(ValueError):
        CS.check_logo('x.svg', b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]><svg>&x;</svg>')
    with pytest.raises(ValueError):
        CS.check_logo('x.svg', b'<html><body/></html>')


def test_parse_form_validation(app, monkeypatch):
    from werkzeug.datastructures import MultiDict

    class NoDup(FakeDB):
        def fetchone(self):
            return None
    with app.test_request_context('/'):
        data, errs = CS.parse_form(MultiDict([('host', 'Client.Example.test'), ('name_en', 'Example Client'),
                                              ('allowed_access_modes', 'restricted'), ('allowed_access_modes', 'bogus'),
                                              ('default_access_mode', 'cms'), ('monthly_org_cap', '500'),
                                              ('default_daily_screening_limit', ''), ('active', '1')]), db=NoDup())
        assert not errs, errs
        assert data['host'] == 'client.example.test' and data['allowed_access_modes'] == ['restricted']
        assert data['default_access_mode'] == 'restricted' and data['monthly_org_cap'] == 500
        assert data['default_daily_screening_limit'] is None and data['active'] is True
        _d, errs = CS.parse_form(MultiDict([('host', 'complynex.online'), ('name_en', 'X'),
                                            ('allowed_access_modes', 'cms')]), db=NoDup())
        assert errs
        _d, errs = CS.parse_form(MultiDict([('host', 'https://bad host/'), ('name_en', ''),
                                            ('monthly_org_cap', '-1')]), db=NoDup())
        assert len(errs) >= 3


def test_registry_superadmin_only(app):
    from access import registry as R
    eps = sorted(ep for ep in app.view_functions if ep.startswith('admin.client_site'))
    assert {'admin.client_sites', 'admin.client_site_new', 'admin.client_site_edit', 'admin.client_site_users',
            'admin.client_site_user_add', 'admin.client_site_user_remove', 'admin.client_site_usage'} <= set(eps)
    f = R.FEATURES['admin.client_sites']
    assert f.platform and f.legacy == ('role', ('superadmin',))
    for ep in eps:
        assert R.ENDPOINT_FEATURE.get(ep) == 'admin.client_sites', ep
        assert getattr(app.view_functions[ep], '_cx_access', None) == [('role', ('superadmin',))], ep
    assert 'auth.site_logo' in app.view_functions
