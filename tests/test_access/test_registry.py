"""Per-user access control: the registry (modules x features as data), the old rules it derives from the
code's own guards, and the effective-access rules. No database: users are built in memory."""
import fnmatch
import itertools
import os
import re

import pytest

from models.user import User

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope='module')
def reg():
    from config import config
    old = os.environ.get('FLASK_ENV')
    if old not in config:            # importing app builds one app from FLASK_ENV
        os.environ['FLASK_ENV'] = 'development'
    try:
        from app import create_app
        app = create_app('development')
    finally:
        if old is None:
            os.environ.pop('FLASK_ENV', None)
        else:
            os.environ['FLASK_ENV'] = old
    from access import registry as R
    return app, R


ROLES = ('superadmin', 'admin', 'it_admin', 'compliance_officer', 'compliance_manager', 'manager', 'analyst', 'employee')
LEVELS = ('none', 'view', 'edit', 'admin')


def _user(role, level, cms='none', pack_modules=()):
    perms = {c: level for c in (
        'perm_governance', 'perm_aml', 'perm_policies', 'perm_reports', 'perm_pdpl', 'perm_training', 'perm_screening',
        'perm_config', 'perm_cyber', 'perm_consumer_protection', 'perm_whistleblowing', 'perm_ghe', 'perm_coi',
        'perm_cobec', 'perm_merchant_kyc', 'perm_tm', 'perm_ekyc', 'perm_risk_management', 'perm_internal_audit',
        'perm_esg', 'perm_carbon')}
    u = User(id=None, email='t@example.test', password_hash='x', first_name='T', last_name='U', role=role,
             cms_access_level=cms, **perms)
    for c in ('perm_ongoing_screening', 'perm_academy', 'perm_regcontrols', 'perm_prudential', 'perm_ai', 'perm_vessels',
              'perm_vessels_db', 'perm_phishing'):
        setattr(u, c, level)
    u._module_perms = {m: level for m in pack_modules}
    return u


def _grid(R):
    packs = {m.key for m in R.MODULES.values() if m.pack}
    packs |= {mod for f in R.FEATURES.values() for mod, _l in f.write_perms.items()}
    return [_user(r, lv, cms, packs) for r, lv, cms in itertools.product(ROLES, LEVELS, ('none', 'view'))]


def test_owner_examples_are_separate_features(reg):
    _app, R = reg
    for key in ('screening.name.screen', 'screening.name.bulk', 'screening.name.export', 'screening.name.decide',
                'vessels.screen', 'vessels.bulk', 'vessels.decide', 'vessels.database', 'dualuse.search',
                'dualuse.screen', 'dualuse.batch', 'dualuse.decide', 'dualuse.admin', 'portal.coi', 'portal.cobec',
                'portal.learning', 'portal.policies', 'aml.str.manage', 'governance.meetings.manage', 'admin.users'):
        assert key in R.FEATURES, key
        assert R.FEATURES[key].endpoints, key
    assert R.feature_for('vessels.screen') == 'vessels.screen'
    assert R.feature_for('screening.manual_screen') == 'screening.name.screen'
    assert R.feature_for('dualuse.batch_run') == 'dualuse.batch'
    assert R.feature_for('portal.annual_cobec') == 'portal.cobec'
    assert R.feature_for('training.take_quiz') == 'portal.learning'
    assert R.feature_for('governance.add_member') == 'governance.board.manage'
    assert R.feature_for('governance.view_member') == 'governance.board.view'


def test_every_module_page_is_mapped(reg):
    """Everything outside a module is sign-in, public, API-key or personal pages — nothing else."""
    app, R = reg
    allowed = ('auth.*', 'static', 'api_v1.*', 'fra_nbfi_lending_api.*', 'academy.*', 'public_coi.*', 'public_ghe.*',
               'talent_public.*', 'legal.*', 'users.profile', 'users.update_profile', 'users.upload_avatar',
               'users.download_avatar', 'users.change_password', 'users.password_change_required', 'set_language',
               'favicon', 'health', 'index', 'dashboard', 'prometheus_metrics', 'access.workspace', 'access.workspace_login') + tuple(R.PUBLIC)
    unmapped = sorted({r.endpoint for r in app.url_map.iter_rules()} - set(R.ENDPOINT_FEATURE))
    stray = [e for e in unmapped if not any(fnmatch.fnmatchcase(e, p) for p in allowed)]
    assert not stray, stray


def test_old_rule_of_a_feature_never_refuses_what_a_page_guard_allows(reg):
    """Backfill safety: whoever passes a page's own guard also gets the feature that page belongs to.
    (Pages whose check sits inside the view body carry no recorded guard; their feature states the rule
    and the before/after crawl of every route proves it — scripts/access_equivalence.py.)"""
    _app, R = reg
    users = _grid(R)
    bad = []
    for f in R.FEATURES.values():
        for ep in f.endpoints:
            spec = R.ENDPOINT_SPEC[ep]
            if spec == 'auth' and f.legacy is not None:
                continue
            for u in users:
                if R.allows(u, spec) and not R.allows(u, f.old_rule):
                    bad.append((f.key, ep, u.role))
    assert not bad, bad[:20]


def test_write_through_levels_cover_every_page_guard(reg):
    """Granting a feature raises perm_* enough for the pages' own guards to let the user in."""
    _app, R = reg
    bad = []
    for f in R.FEATURES.values():
        for ep in f.endpoints:
            for mod, lvl in R.perm_leaves(R.ENDPOINT_SPEC[ep]):
                need = R.RANK.get(lvl, 1)
                if f.legacy is None and R.RANK.get(f.write_perms.get(mod, 'none'), 0) < min(need, 2) and \
                        R.ENDPOINT_SPEC[ep][0] != 'any':
                    bad.append((f.key, ep, mod, lvl, f.write_perms))
    assert not bad, bad[:20]


def test_core_catalogue_names_no_pack():
    src = ''.join(open(os.path.join(ROOT, 'access', n), encoding='utf-8').read()
                  for n in os.listdir(os.path.join(ROOT, 'access')) if n.endswith('.py'))
    for code in ('trade_control', 'fra_nbfi', 'talent_pool', 'dualuse', "'talent", "'lending"):
        assert code not in src, code


def test_effective_access_rules(reg):
    _app, R = reg
    from access import service as S
    emp = _user('employee', 'none')
    emp.id = 5
    # nobody edited this user: the old rules
    a = S.compute(emp, explicit={})
    assert a.mode == 'portal' and a.has('portal.coi') and not a.has('screening.name.view')
    # restricted: only what was ticked, never the portal
    a = S.compute(emp, mode='restricted', explicit={'vessels.screen': True, 'vessels.view': True, 'portal.coi': True})
    assert a.granted == {'vessels.screen', 'vessels.view'}
    assert S.endpoint_allowed(a, 'vessels.screen') and S.endpoint_allowed(a, 'auth.logout')
    for ep in ('dashboard', 'portal.annual_coi', 'screening.manual_screen', 'notifications_list', 'api_v1.v1_docs',
               'whistleblowing.submit_case', 'support'):
        assert not S.endpoint_allowed(a, ep), ep
    # cms / portal: pages outside every module keep their old behaviour
    a = S.compute(emp, mode='portal', explicit={'portal.coi': False})
    assert not S.endpoint_allowed(a, 'portal.annual_coi') and S.endpoint_allowed(a, 'portal.annual_cobec')
    assert S.endpoint_allowed(a, 'api_v1.v1_docs')
    # the superadmin is unrestricted
    sup = _user('superadmin', 'none')
    sup.id = 1
    a = S.compute(sup, mode='restricted', explicit={})
    assert a.unrestricted and S.endpoint_allowed(a, 'admin.edit_user')


def test_requires_are_added(reg):
    _app, R = reg
    from access import service as S
    assert S.expand_requires({'vessels.decide'}) == {'vessels.decide', 'vessels.view'}
    assert S.expand_requires({'nonexistent'}) == set()


def test_guards_record_their_rule():
    from utils.decorators import permission_required, admin_required
    f = permission_required('aml', 'edit')(lambda: None)
    assert f._cx_access == [('perm', 'aml', 'edit')]
    g = permission_required('aml', 'admin')(lambda: None)
    assert g._cx_access[0][0] == 'role'
    assert admin_required(lambda: None)._cx_access == [('role', ('admin',))]


def test_matrix_template_is_csp_safe():
    for name in ('_matrix.html', 'workspace.html', '_bar.html', 'denied.html', 'user.html', 'audit.html', '_copy_form.html'):
        html = open(os.path.join(ROOT, 'templates', 'access', name), encoding='utf-8').read()
        assert not re.search(r'\son[a-z]+=', html), name
        for tag in re.findall(r'<script[^>]*>', html):
            assert 'nonce=' in tag, name
