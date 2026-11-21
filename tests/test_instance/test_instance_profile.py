# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================

"""Instance profiles (utils/instance_profile.py), the upload quota, one-time set-password links and the
first-superadmin script of secondary instances (scripts/instance/)."""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HEAVY = ('screening', 'ekyc', 'packs', 'aml', 'amlkyc', 'merchant_kyc', 'faiss', 'torch', 'sentence_transformers',
         'transformers', 'elasticsearch', 'sklearn')

# Runs in a fresh interpreter: the governance app factory, then what it imported and how it answers.
PROBE = r'''
import json, logging, sys
logging.disable(logging.CRITICAL)
import app as appmod
a = appmod.create_app()
from flask import url_for
from access import registry as R, gate
from utils import instance_profile as P
out = {'profile': P.name(), 'blueprints': sorted(a.blueprints),
       'modules_loaded': sorted({m.split('.')[0] for m in sys.modules}),
       'catalog_modules': [m.key for m in R.modules()],
       'features': sorted(f.key for f in R.all_features())}
with a.test_request_context('/'):
    out['url_screening'] = url_for('screening.manual_screen')
    out['url_ops'] = url_for('compliance_operations')            # registered, but outside the profile
    out['url_dashboard'] = url_for('dashboard')
    page = ('<!DOCTYPE html><html><body><ul class="nav"><li><a href="/_off/x.y">menu</a></li></ul>'
            '<div class="row"><div class="col-6" data-cx-widget><a href="/_off/aml.alert_list">AML</a></div>'
            '<div class="col-6" data-cx-widget><a href="/policies/">Policies</a></div></div>'
            '<div data-cx-endpoint="risk_management.dashboard">risk widget</div>'
            '<div data-cx-endpoint="policies.list_policies">policy widget</div>'
            '<p>See <a href="/_off/screening.history">the history</a> here.</p>'
            '<form action="/_off/aml.x" method="post"><button>go</button></form><p>عربي</p></body></html>')
    out['scrubbed'] = P.scrub_html(page)
    out['url_governance'] = url_for('governance.index') if 'governance.index' in a.view_functions else None
    out['ep_enabled'] = {e: P.endpoint_enabled(e) for e in
                         ('screening.manual_screen', 'compliance_operations', 'admin.screening_limits',
                          'dashboard', 'auth.login', 'auth.set_password')}
    html = '<ul><li><a href="/_off/screening.manual_screen">s</a></li><li><a href="/dashboard">d</a></li></ul>'
    out['pruned'] = str(gate.prune_nav(html))
c = a.test_client()
out['status'] = {p: c.get(p).status_code for p in
                 ('/screening/', '/screening/manual', '/vessels/', '/ekyc/', '/dashboard/compliance-operations',
                  '/_off/screening.manual_screen', '/health')}
print('JSON' + json.dumps(out))
'''


def _env(tmp_path, profile):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CX_', 'POSTGRES_', 'DATABASE_'))}
    env.update(CX_INSTANCE_PROFILE=profile, SECRET_KEY='profile-test', FLASK_ENV='default', DB_TYPE='sqlite',
               POSTGRES_DB='cx_profile_test_nodb', POSTGRES_PASSWORD='', REDIS_URL='redis://127.0.0.1:1/0',
               PYTHONPATH=ROOT + os.pathsep + env.get('PYTHONPATH', ''))
    return env


@pytest.fixture(scope='module')
def governance(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('gov')
    r = subprocess.run([sys.executable, '-c', PROBE], cwd=str(tmp), env=_env(tmp, 'governance'),
                       capture_output=True, text=True, timeout=180)
    line = [x for x in r.stdout.splitlines() if x.startswith('JSON')]
    assert line, (r.stdout[-2000:], r.stderr[-4000:])
    return json.loads(line[-1][4:])


def test_governance_app_factory_never_imports_screening_ml_or_search(governance):
    assert governance['profile'] == 'governance'
    loaded = set(governance['modules_loaded'])
    assert not loaded & set(HEAVY), sorted(loaded & set(HEAVY))


def test_governance_registers_only_its_blueprints(governance):
    from utils import instance_profile as P
    bps = set(governance['blueprints'])
    assert {'governance', 'policies', 'coi', 'declarations', 'admin', 'users', 'auth', 'access', 'portal'} <= bps
    assert not bps & {'screening', 'vessels', 'pep_api', 'aml', 'ekyc', 'merchant_kyc', 'blacklist', 'api_v1',
                      'dualuse', 'lending', 'talent', 'academy', 'esg', 'carbon'}
    allowed = set(P.PROFILES['governance']['blueprints']) | {'events', 'ops_status', 'api_admin'} | \
        {'governance', 'policies', 'coi', 'declarations', 'tracker', 'portal', 'admin'}
    assert bps <= allowed, sorted(bps - allowed)


def test_governance_catalog_and_features_follow_the_profile(governance):
    from utils import instance_profile as P
    assert set(governance['catalog_modules']) <= set(P.PROFILES['governance']['modules'])
    feats = set(governance['features'])
    assert 'general.operations' not in feats and 'admin.limits' not in feats
    assert not any(f.startswith(('screening.', 'aml.', 'vessels.', 'ekyc.')) for f in feats)
    assert any(f.startswith('governance.') for f in feats) and any(f.startswith('policies.') for f in feats)


def test_governance_disabled_pages_are_404_and_links_are_pruned(governance):
    st = governance['status']
    for p in ('/screening/', '/screening/manual', '/vessels/', '/ekyc/', '/dashboard/compliance-operations',
              '/_off/screening.manual_screen'):
        assert st[p] == 404, (p, st[p])
    assert governance['url_screening'] == '/_off/screening.manual_screen'
    en = governance['ep_enabled']
    assert en['screening.manual_screen'] is False and en['compliance_operations'] is False
    assert en['admin.screening_limits'] is False
    assert en['dashboard'] and en['auth.login'] and en['auth.set_password']
    assert '/_off/' not in governance['pruned'] and '/dashboard' in governance['pruned']
    assert governance['url_ops'] == '/_off/compliance_operations' and governance['url_dashboard'] == '/dashboard'


def test_governance_scrub_removes_widgets_and_dead_links(governance):
    s = governance['scrubbed']
    assert '/_off/' not in s and s.startswith('<!DOCTYPE html>')
    assert 'AML' not in s and 'menu' not in s and 'risk widget' not in s and '<form' not in s
    assert 'Policies' in s and 'policy widget' in s and 'the history' in s and 'عربي' in s


def test_scrub_leaves_pages_without_marks_untouched():
    from utils import instance_profile as P
    page = '<!DOCTYPE html><html><body><a href="/dashboard">x</a></body></html>'
    assert P.scrub_html(page) is page


def test_superadmin_and_compliance_roles_view_security_pages(monkeypatch):
    from types import SimpleNamespace
    import admin.security_p6 as SEC
    for role, ok in (('superadmin', True), ('admin', True), ('compliance_officer', True), ('compliance_manager', True),
                     ('employee', False), ('manager', False)):
        monkeypatch.setattr(SEC, 'current_user', SimpleNamespace(is_authenticated=True, role=role))
        assert SEC._can_view() is ok, role
    monkeypatch.setattr(SEC, 'current_user', SimpleNamespace(is_authenticated=False, role='superadmin'))
    assert SEC._can_view() is False


def test_full_profile_is_the_default_and_unchanged(monkeypatch):
    from utils import instance_profile as P
    monkeypatch.delenv('CX_INSTANCE_PROFILE', raising=False)
    assert P.name() == 'full' and P.is_full() and P.heavy_enabled() and P.packs_enabled()
    assert P.enabled_blueprints() is None and P.blueprint_enabled('screening')
    assert P.module_enabled('screening') and P.feature_enabled('general.operations')
    assert P.endpoint_enabled('screening.manual_screen')
    assert P.install_import_guard() is False
    monkeypatch.setenv('CX_INSTANCE_PROFILE', 'nonsense')
    assert P.name() == 'full'


def test_import_guard_refuses_blocked_packages(monkeypatch):
    from utils import instance_profile as P
    monkeypatch.setenv('CX_INSTANCE_PROFILE', 'governance')
    blocker = P._Blocker(('cx_fake_heavy_pkg',))
    monkeypatch.setattr(sys, 'meta_path', [blocker] + sys.meta_path)
    with pytest.raises(ImportError, match='instance profile'):
        __import__('cx_fake_heavy_pkg.sub')


def test_template_fallbacks_only_outside_full(monkeypatch):
    from flask import Flask, render_template_string
    from utils import instance_profile as P
    monkeypatch.setenv('CX_INSTANCE_PROFILE', 'full')
    a = Flask(__name__)
    P.install_template_fallbacks(a)
    assert 'ai_level' not in a.jinja_env.globals
    monkeypatch.setenv('CX_INSTANCE_PROFILE', 'governance')
    a.jinja_env.globals['rc_loc'] = lambda en, ar: 'registered'      # a real helper always wins
    P.install_template_fallbacks(a)
    with a.test_request_context('/'):
        out = render_template_string("{{ ai_level() }}|{{ ekyc_enabled() }}|{{ rc_pack_menus()|length }}|"
                                     "{{ rc_loc('a', 'b') }}|{{ vessel_can_db() }}")
    assert out == '0|False|0|registered|False'


# ------------------------------------------------------------------ upload quota
def _quota_app(monkeypatch, tmp_path, quota_mb):
    from flask import Flask
    from utils import instance_profile as P
    monkeypatch.setenv('CX_UPLOAD_QUOTA_MB', str(quota_mb))
    monkeypatch.setenv('CX_UPLOAD_DIR', str(tmp_path))
    P._usage.update(at=0.0, bytes=0, dir=None)
    app = Flask(__name__)
    app.config.update(SECRET_KEY='q', TESTING=True)
    P.install_upload_quota(app)

    @app.route('/up', methods=['POST'])
    def up():
        return 'stored'
    return app


def _post(client, size=10, **kw):
    import io
    return client.post('/up', data={'f': (io.BytesIO(b'x' * size), 'a.txt')},
                       content_type='multipart/form-data', **kw)


def test_quota_allows_uploads_below_the_limit(monkeypatch, tmp_path):
    (tmp_path / 'old.bin').write_bytes(b'x' * 100)
    c = _quota_app(monkeypatch, tmp_path, 1).test_client()
    r = _post(c)
    assert r.status_code == 200 and r.data == b'stored'
    assert c.post('/up', data={'a': 'b'}).status_code == 200     # not an upload: never counted


def test_quota_refuses_uploads_when_full_with_bilingual_message(monkeypatch, tmp_path):
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'big.bin').write_bytes(b'x' * 3000)
    app = _quota_app(monkeypatch, tmp_path, 0.002)                 # ~2 KB
    c = app.test_client()
    r = _post(c, headers={'Accept': 'application/json'})
    assert r.status_code == 413
    body = r.get_json()
    assert body['error'] == 'quota_exceeded'
    assert 'quota' in body['message_en'] and 'مساحة التخزين' in body['message_ar']
    r = _post(c, headers={'Referer': 'http://localhost/form'})
    assert r.status_code == 302 and r.headers['X-CX-Quota'] == 'exceeded'
    assert r.headers['Location'].endswith('/form')
    r = _post(c, headers={'Referer': 'https://elsewhere.example/x'})
    assert r.headers['Location'] in ('/', 'http://localhost/')     # never back to another site


def test_quota_off_when_unset(monkeypatch, tmp_path):
    (tmp_path / 'big.bin').write_bytes(b'x' * 5000)
    app = _quota_app(monkeypatch, tmp_path, 0)
    assert _post(app.test_client()).status_code == 200


# ------------------------------------------------------------------ one-time set-password links
class _FakeUser:
    def __init__(self, uid=7, email='owner@example.org', role='superadmin'):
        self.id, self.email, self.role = uid, email, role
        self.auth_version, self.password_hash, self.is_active = 0, '$2b$12$initialhash', True


@pytest.fixture
def link_app(monkeypatch):
    from flask import Flask
    from auth import set_password as SP
    from auth.routes import auth_bp
    from models.user import User
    users = {}

    def get_by_email(email):
        return next((u for u in users.values() if u.email == email), None)

    def create_user(email, password, first_name, last_name, role='employee', **kw):
        ok, _msg = User.validate_password_strength(password)
        assert ok, 'random password must meet the strength rules'
        u = _FakeUser(len(users) + 1, email, role)
        users[u.id] = u

    monkeypatch.setattr(User, 'get_by_id', staticmethod(lambda uid: users.get(uid)))
    monkeypatch.setattr(User, 'get_by_email', staticmethod(get_by_email))
    monkeypatch.setattr(User, 'create_user', staticmethod(create_user))
    app = Flask(__name__)
    app.config.update(SECRET_KEY='link-test', SERVER_NAME=None)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    return app, users, SP


def test_set_password_link_is_signed_single_use_and_expires(link_app):
    import time
    app, users, SP = link_app
    u = _FakeUser()
    users[u.id] = u
    with app.test_request_context('/'):
        tok = SP.make_token(u, hours=24)
        assert SP.user_for_token(tok) is u
        assert SP.user_for_token(tok + 'x') is None                               # tampered
        assert SP.user_for_token(tok, now=time.time() + 25 * 3600) is None        # expired after 24 h
        assert SP.user_for_token(SP.make_token(u, hours=1000), now=time.time() + 8 * 24 * 3600) is None  # cap
        u.password_hash = '$2b$12$changed'                                        # password set: used up
        assert SP.user_for_token(tok) is None
        u.password_hash = '$2b$12$initialhash'
        u.auth_version = 1                                                         # sessions revoked: used up
        assert SP.user_for_token(tok) is None
    other = app.config['SECRET_KEY']
    app.config['SECRET_KEY'] = 'another-instance'
    with app.test_request_context('/'):
        assert SP.user_for_token(tok) is None                                      # other instance's key
    app.config['SECRET_KEY'] = other


def test_create_superadmin_prints_one_time_link_for_the_instance_host(link_app):
    sys.path.insert(0, os.path.join(ROOT, 'scripts', 'instance'))
    try:
        import create_superadmin as CS
    finally:
        sys.path.pop(0)
    app, users, SP = link_app
    with app.test_request_context('/', base_url='https://gov.example.org'):
        created, link = CS.issue('Owner@Example.org', base_url='https://gov.example.org', hours=24)
        assert created and len(users) == 1
        u = next(iter(users.values()))
        assert u.role == 'superadmin' and u.email == 'owner@example.org'
        assert link.startswith('https://gov.example.org/auth/set-password/')
        assert SP.user_for_token(link.rsplit('/', 1)[1]) is u
        again, link2 = CS.issue('owner@example.org', base_url='https://gov.example.org')
        assert not again and len(users) == 1 and link2.startswith('https://gov.example.org/auth/set-password/')
        users[99] = _FakeUser(99, 'staff@example.org', role='employee')
        with pytest.raises(SystemExit):
            CS.issue('staff@example.org')
    pw = CS.random_password()
    assert len(pw) >= 32 and pw != CS.random_password()
