"""Per-user access control against a real database (skipped unless ACCESS_TEST_DB names a scratch database
with database/migrations/20261122_access_control.sql applied and POSTGRES_DB set to it):

* a restricted user with only vessel screening and dual-use goods: EVERY GET route of app.url_map is refused
  (403 from the gate, or a redirect to the workspace / sign-in) except those two modules and the personal
  pages (sign-in, profile, language); the CMS and the portal home lead to the workspace;
* a portal user with vessel screening only: no COI / COBEC / learning on the portal, and refused by URL;
* backfill equivalence on generated users of every role: the gate decides exactly as the old rules did;
* write-through to perm_* columns, the audit trail, copy-from-user, self-lockout guard, the matrix on the
  user edit page, the editor-only pages, and API-key requests left to their own scope checks."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
DBNAME = os.environ.get('ACCESS_TEST_DB', '')
pytestmark = pytest.mark.skipif(not DBNAME or os.environ.get('POSTGRES_DB') != DBNAME,
                                reason='needs ACCESS_TEST_DB=<scratch db> and POSTGRES_DB set to it')
PW = 'Str0ng!Passw0rd#x'
ROLES = ('admin', 'it_admin', 'compliance_officer', 'compliance_manager', 'manager', 'analyst', 'viewer', 'employee')


@pytest.fixture(scope='module')
def app():
    from config import config
    if os.environ.get('FLASK_ENV') not in config:
        os.environ['FLASK_ENV'] = 'development'
    from app import create_app
    a = create_app()
    a.config['WTF_CSRF_ENABLED'] = False
    with a.app_context():
        from database.db import get_db
        from models.user import User
        db = get_db()
        db.execute("INSERT INTO rc_packs (code, enabled) VALUES ('trade_control', TRUE) "
                   "ON CONFLICT (code) DO UPDATE SET enabled = TRUE")
        db.commit()
        ids = {}
        for key, role, kw in (('admin', 'admin', {}), ('super', 'superadmin', {}),
                              ('ext', 'employee', {}), ('portal', 'employee', {}), ('copy', 'employee', {}),
                              *[(f'r_{r}', r, {'perm_screening': 'view', 'perm_aml': 'edit', 'perm_governance': 'view',
                                               'perm_vessels': 'view', 'cms_access_level': 'view' if r == 'analyst' else 'none'})
                                for r in ROLES]):
            email = f'acx-{key}@example.test'
            u = User.get_by_email(email) or User.create_user(email, PW, 'Test', key, role=role, **kw)
            db.execute("DELETE FROM user_access_grants WHERE user_id = %s", (u.id,))
            db.execute("UPDATE users SET access_mode = NULL WHERE id = %s", (u.id,))
            ids[key] = u.id
        db.commit()
        a.ids = ids
    yield a


def _client(app, uid):
    from models.user import User
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = User.session_id_for_app(app, uid)
        s['_fresh'] = True
    return c


def _user(app, key):
    from models.user import User
    with app.app_context():
        return User.get_by_id(app.ids[key])


def _save(app, key, mode, keys, actor='super'):
    from access import service as S
    with app.app_context():
        return S.save(_user(app, key), mode, set(keys), actor_id=app.ids[actor])


def _url(app, endpoint):
    return app.url_map.bind('localhost').build(endpoint, {})


def _urls(app):
    adapter = app.url_map.bind('localhost')
    out, seen = [], set()
    for r in sorted(app.url_map.iter_rules(), key=lambda r: r.endpoint):
        if 'GET' not in r.methods or r.endpoint in seen or r.endpoint in ('static', 'auth.logout', 'academy.logout'):
            continue
        vals = {a: (1 if 'Integer' in type(r._converters.get(a)).__name__ else 'x') for a in r.arguments}
        try:
            out.append((r.endpoint, adapter.build(r.endpoint, vals)))
            seen.add(r.endpoint)
        except Exception:
            pass
    return out


def _mine(R, S, ep):
    f = R.FEATURES.get(R.feature_for(ep) or '')
    return (f is not None and f.key.startswith(('vessels.', 'dualuse.')) and not f.platform) or S._always(ep)


def _refused(r):
    loc = r.headers.get('Location', '')
    return r.status_code == 403 or (r.status_code in (301, 302) and ('/workspace' in loc or '/login' in loc))


def _post_urls(app):
    adapter = app.url_map.bind('localhost')
    out, seen = [], set()
    for r in sorted(app.url_map.iter_rules(), key=lambda r: r.endpoint):
        if 'POST' not in r.methods or r.endpoint in seen:
            continue
        vals = {a: (1 if 'Integer' in type(r._converters.get(a)).__name__ else 'x') for a in r.arguments}
        try:
            out.append((r.endpoint, adapter.build(r.endpoint, vals)))
            seen.add(r.endpoint)
        except Exception:
            pass
    return out


@pytest.mark.parametrize('headers', [{}, {'X-API-Key': 'x'}, {'X-API-Key': 'cx_live_bogus', 'Authorization': 'Bearer x'}],
                         ids=['plain', 'api-key-header', 'api-key-and-bearer'])
def test_restricted_user_reaches_only_the_granted_modules(app, headers):
    """Every GET and POST route outside vessels + dual-use is refused — also when the request carries an
    API-key header (a header never skips the gate for a signed-in session)."""
    from access import registry as R, service as S
    keys = [k for k in R.FEATURES if k.startswith(('vessels.', 'dualuse.')) and not R.FEATURES[k].platform]
    _save(app, 'ext', 'restricted', keys)
    c = _client(app, app.ids['ext'])
    allowed, refused = [], []
    for ep, url in _urls(app):
        if _mine(R, S, ep):
            try:                     # a granted page may still fail on a scratch database without its tables
                r = c.get(url, headers={'Accept': 'text/html', **headers})
                assert r.headers.get('X-CX-Gate') != 'denied', ep
            except AssertionError:
                raise
            except Exception:
                pass
            allowed.append(ep)
            continue
        r = c.get(url, headers={'Accept': 'text/html', **headers})
        assert _refused(r), (ep, url, r.status_code, r.headers.get('Location'))
        refused.append(ep)
    assert len(refused) > 500 and any(e.startswith('vessels.') for e in allowed)
    posts = 0
    for ep, url in _post_urls(app):
        if _mine(R, S, ep):
            continue
        r = c.post(url, data={'x': '1'}, headers=headers)
        assert _refused(r), ('POST', ep, url, r.status_code, r.headers.get('Location'))
        posts += 1
    assert posts > 300
    for url in ('/', '/dashboard', '/portal/', '/portal/dashboard'):
        r = c.get(url, headers=headers)
        assert r.status_code == 302 and r.headers['Location'].endswith('/workspace'), url
    page = c.get('/workspace').get_data(as_text=True)
    assert '/screening/vessels/screen' in page and '/dual-use/' in page
    assert 'class="cnx-sidebar"' not in page and '/screening/manual' not in page and '/portal/' not in page


def test_portal_user_with_vessels_only(app):
    from access import registry as R
    keys = ['portal.home'] + [k for k in R.FEATURES if k.startswith('vessels.') and k not in ('vessels.database', 'vessels.updates')]
    _save(app, 'portal', 'portal', keys)
    c = _client(app, app.ids['portal'])
    page = c.get('/portal/dashboard').get_data(as_text=True)
    for ep in ('portal.annual_coi', 'portal.annual_cobec', 'portal.training_list'):
        assert f'href="{_url(app, ep)}"' not in page, ep
    assert '/screening/vessels/screen' in page             # "My modules"
    for ep in ('portal.annual_coi', 'portal.annual_cobec', 'portal.training_list', 'training.my_certificates'):
        assert c.get(_url(app, ep)).status_code == 403, ep
    assert c.get('/screening/vessels/screen').status_code == 200
    assert c.get('/dashboard').headers['Location'].endswith('/portal/dashboard')
    side = c.get('/screening/vessels/screen').get_data(as_text=True)
    start = side.index('class="cnx-sidebar"')
    nav = side[start:side.index('</nav>', start)]
    assert '/coi/' not in nav and '/cobec/' not in nav and '/screening/vessels/screen' in nav
    assert '/screening/vessels/database' not in nav
    with app.app_context():
        u = _user(app, 'portal')
        assert u.perm_vessels == 'edit' and (u.perm_vessels_db or 'none') == 'none' and not u.can_access_cms()


def test_backfill_keeps_every_decision(app):
    from access import service as S
    from database.db import get_db
    with app.app_context():
        users = {k: _user(app, k) for k in app.ids if k.startswith('r_')}
        before = {k: S.compute(u, explicit={}) for k, u in users.items()}
        cols = {k: {c: getattr(u, c, None) for c in ('perm_screening', 'perm_aml', 'perm_governance', 'perm_vessels',
                                                      'cms_access_level')} for k, u in users.items()}
        def _audits():
            return get_db().execute("SELECT count(*) AS n FROM user_access_audit WHERE action = 'backfill'").fetchone()['n']
        n0 = _audits()
        S.backfill(only_user_ids={u.id for u in users.values()})
        n1 = _audits()
        assert S.backfill(only_user_ids={u.id for u in users.values()}) == []      # idempotent
        assert _audits() == n1 == n0 + len(users)
        eps = sorted({r.endpoint for r in app.url_map.iter_rules()})
        for k, u in users.items():
            u2 = _user(app, k)
            after = S.compute(u2)
            assert after.managed and after.mode == before[k].mode, k
            assert after.granted == before[k].granted, k
            assert [S.endpoint_allowed(after, e) for e in eps] == [S.endpoint_allowed(before[k], e) for e in eps], k
            assert {c: getattr(u2, c, None) for c in cols[k]} == cols[k], k
        # compliance roles keep the CMS, the others keep the portal (analyst with a CMS level keeps the CMS)
        assert before['r_compliance_officer'].mode == 'cms' and before['r_employee'].mode == 'portal'
        assert before['r_analyst'].mode == 'cms'


def test_saving_unchanged_matrix_changes_nothing(app):
    from access import service as S
    with app.app_context():
        u = _user(app, 'r_compliance_manager')
        acc = S.compute(u)
        cols = {c: getattr(u, c, None) for c in ('perm_screening', 'perm_aml', 'perm_governance', 'perm_vessels')}
        added, removed = S.save(u, acc.mode, acc.granted, actor_id=app.ids['admin'])
        assert added == [] and removed == []
        u2 = _user(app, 'r_compliance_manager')
        assert {c: getattr(u2, c, None) for c in cols} == cols


def test_audit_copy_and_self_lockout(app):
    from access import service as S
    from database.db import get_db
    _save(app, 'copy', 'restricted', ['dualuse.search'])
    with app.app_context():
        S.copy_from(_user(app, 'ext'), _user(app, 'copy'), actor_id=app.ids['admin'])
        from access import registry as R
        locked = {k for k, f in R.FEATURES.items() if f.grant_by}     # superadmin-only: an admin copies around them
        assert S.compute(_user(app, 'copy')).granted == S.compute(_user(app, 'ext')).granted - locked
        rows = S.history(app.ids['copy'])
        assert rows[0]['action'] == 'copy' and rows[0]['actor_id'] == app.ids['admin']
        assert any('dualuse.search' in r['added'] for r in rows)
        with pytest.raises(S.AccessError):
            S.save(_user(app, 'admin'), 'portal', set(), actor_id=app.ids['admin'])
        with pytest.raises(S.AccessError):
            S.save(_user(app, 'super'), 'cms', set(), actor_id=app.ids['admin'])
        assert get_db().execute("SELECT count(*) AS n FROM audit_logs WHERE action = 'Update Access Rights'").fetchone()['n']


def test_matrix_pages_and_edit_form(app):
    c = _client(app, app.ids['admin'])
    uid = app.ids['r_viewer']
    page = c.get(f'/admin/users/edit/{uid}').get_data(as_text=True)
    assert 'data-cx-matrix' in page and 'name="cx_feature"' in page and 'id="cxCopyForm"' in page
    r = c.post(f'/admin/users/edit/{uid}', data={
        'email': 'acx-r_viewer@example.test', 'first_name': 'Test', 'last_name': 'r_viewer', 'role': 'viewer',
        'is_active': '1', 'cx_mode': 'restricted', 'cx_feature': ['vessels.screen'], 'cx_note': 'external'})
    assert r.status_code == 302
    from access import service as S
    with app.app_context():
        u = _user(app, 'r_viewer')
        acc = S.compute(u)
        assert u.access_mode == 'restricted' and acc.granted == {'vessels.screen', 'vessels.view'}
        assert u.perm_screening == 'none' and u.perm_vessels == 'view' and u.perm_aml == 'none'
    assert c.get(f'/admin/access/users/{uid}').status_code == 200
    assert c.get('/admin/access/audit').status_code == 200
    pv = c.get(f'/admin/access/users/{uid}/preview?mode=restricted&f=dualuse.search').get_json()
    assert pv['pages'] > 0 and len(pv['modules']) == 1
    # only administrators edit access
    other = _client(app, app.ids['r_compliance_officer'])
    assert other.get(f'/admin/access/users/{uid}').status_code == 403
    assert other.post(f'/admin/access/users/{uid}', data={'cx_mode': 'cms'}).status_code == 403


def test_api_key_requests_keep_their_own_checks(app):
    # a real API client has no session: the API authenticates the key itself (here: refused, unknown key)
    r = app.test_client().get('/api/v1/screenings', headers={'X-API-Key': 'not-a-key'})
    assert r.headers.get('X-CX-Gate') is None and r.status_code == 401 and r.get_json() is not None
    r = app.test_client().post('/api/v1/screenings', json={'name': 'x'}, headers={'X-API-Key': 'not-a-key'})
    assert r.headers.get('X-CX-Gate') is None and r.status_code == 401
    # a signed-in restricted session does not get past the gate by adding the header
    c = _client(app, app.ids['ext'])
    r = c.get('/api/v1/screenings', headers={'X-API-Key': 'not-a-key'})
    assert r.status_code == 403 and r.headers.get('X-CX-Gate') == 'denied'


def _crawl_refused_except(app, c, prefixes):
    from access import registry as R, service as S
    for ep, url in _urls(app):
        f = R.FEATURES.get(R.feature_for(ep) or '')
        if (f is not None and f.key.startswith(prefixes) and not f.platform) or S._always(ep):
            continue
        r = c.get(url, headers={'Accept': 'text/html'})
        loc = r.headers.get('Location', '')
        assert r.status_code == 403 or (r.status_code in (301, 302) and ('/workspace' in loc or '/login' in loc)), \
            (ep, r.status_code, loc)


def test_owner_scenario_external_customer_end_to_end(app, monkeypatch):
    """Admin creates a restricted user with only dual-use + vessels on the ADD page (access type + two module
    tick-alls), the welcome e-mail carries the workspace sign-in link (never the password), the user signs in
    there, replaces the temporary password, lands on /workspace with exactly two tiles, and every other GET
    route is refused."""
    import re
    import uuid
    from access import registry as R, service as S
    sent = []
    monkeypatch.setattr('utils.email.send_mail_async', lambda msg, to_email=None: sent.append(msg) or True)
    admin = _client(app, app.ids['admin'])
    page = admin.get('/admin/users/add').get_data(as_text=True)
    assert 'data-cx-matrix' in page and 'value="restricted"' in page and 'data-cx-copy-src' in page
    email = f'acx-cust-{uuid.uuid4().hex[:8]}@example.test'
    feats = [k for k in R.FEATURES if R.FEATURES[k].module.key in ('vessels', 'dualuse')     # "tick all" twice
             and not R.FEATURES[k].platform and R.FEATURES[k].workspace   # (not offered / disabled for this access type,
             and not R.FEATURES[k].grant_by]                              #  or only the superadmin may tick them)
    r = admin.post('/admin/users/add', data={
        'email': email, 'first_name': 'Cust', 'last_name': 'Omer', 'role': 'employee', 'is_active': '1',
        'authority_level': 'group', 'cx_mode': 'restricted', 'cx_feature': feats, 'cx_welcome': '1'})
    assert r.status_code == 200, r.status_code
    html = r.get_data(as_text=True)
    import html as _h
    pw = _h.unescape(re.search(r'<code class="user-select-all">([^<]+)</code>', html).group(1))
    assert '/workspace/login' in html
    # the welcome e-mail: workspace link, the modules, never the password
    body = sent[-1].html
    assert sent[-1].recipients == [email] and '/workspace/login' in body and pw not in body
    assert 'Vessel screening' in body and 'Dual-use goods screening' in body
    with app.app_context():
        from models.user import User
        u = User.get_by_email(email)
        acc = S.compute(u)
        assert u.access_mode == 'restricted' and acc.granted == set(feats) and acc.managed
        assert u.perm_vessels == 'edit' and (u.perm_vessels_db or 'none') == 'none'     # database: superadmin only
        assert u.module_permissions().get('dualuse') == 'admin'
        assert u.perm_screening == 'none' and not u.can_access_cms()
        assert any(h['action'] == 'save' for h in S.history(u.id))
    # the customer signs in from the link
    c = app.test_client()
    assert c.get('/workspace/login').status_code == 200
    r = c.post('/auth/portal/login', data={'email': email, 'password': pw, 'ws': '1'})
    assert r.status_code == 302, re.findall(r'alert-[a-z]+[^>]*>([^<]+)', r.get_data(as_text=True))
    r = c.get(r.headers['Location'])
    assert r.status_code == 302 and 'change-required' in r.headers['Location']
    new_pw = 'Cust0mer!Workspace#2026'
    r = c.post('/users/password/change-required', data={'current_password': pw, 'new_password': new_pw,
                                                          'confirm_password': new_pw})
    assert r.status_code == 302
    r = c.get(r.headers['Location'])
    assert r.status_code == 302 and r.headers['Location'].endswith('/workspace')
    ws = c.get('/workspace').get_data(as_text=True)
    assert ws.count('class="cx-ws-tile"') == 2
    assert '/screening/vessels/screen' in ws and '/dual-use/' in ws and 'class="cnx-sidebar"' not in ws
    _crawl_refused_except(app, c, ('vessels.', 'dualuse.'))


def test_add_user_without_matrix_fields_gets_explicit_grants(app):
    """Any other way of creating a user (old clients, CSV upload) still writes explicit grants."""
    import uuid
    from access import service as S
    from models.user import User
    with app.app_context():
        u = User.create_user(f'acx-csv-{uuid.uuid4().hex[:8]}@example.test', PW, 'C', 'S', role='employee',
                             perm_aml='view')
        acc = S.compute(u)
        assert acc.managed and u.access_mode == 'portal' and acc.has('aml.monitoring.view') and acc.has('portal.coi')


def test_portal_user_with_no_portal_feature_sees_a_message(app):
    _save(app, 'portal', 'portal', ['portal.home'])
    page = _client(app, app.ids['portal']).get('/portal/dashboard').get_data(as_text=True)
    assert 'cx-portal-mods' not in page
    assert 'bi-inboxes' in page


def _vessel_rows(app, owner_id, marker):
    """A screening and a whitelist clearance made by `owner_id` (minimal rows; enough for lists and refusals)."""
    import json as _j
    from database.db import get_db
    with app.app_context():
        db = get_db()
        sid = db.execute("""INSERT INTO vessel_screenings (user_id, customer_ref, query, result, tier)
                            VALUES (%s, %s, %s, %s, 'CLEAR') RETURNING id""",
                         (owner_id, marker, _j.dumps({'name': marker}), _j.dumps({'query': {'name': marker}, 'hits': []}))
                         ).fetchone()['id']
        wid = db.execute("""INSERT INTO vessel_whitelist (query_key, listed_key, listed_fp, query_fp, query_label, reason,
                                                          comment, created_by)
                            VALUES (%s, 'x', repeat('a', 40), repeat('b', 40), %s, 'false_positive', 'test', %s)
                            RETURNING id""", (marker, marker, owner_id)).fetchone()['id']
        db.commit()
    return sid, wid


def test_restricted_customer_sees_only_own_vessel_records(app):
    """A restricted user with every vessel feature (incl. decide/bulk -> perm_vessels 'edit') never sees
    colleagues' screenings, PDFs or clearances; a CMS editor keeps today's team view."""
    import uuid
    from access import registry as R, service as S
    keys = [k for k in R.FEATURES if k.startswith('vessels.') and not R.FEATURES[k].platform]
    _save(app, 'ext', 'restricted', keys)
    marker = f'INTERNAL-{uuid.uuid4().hex[:8]}'
    sid, wid = _vessel_rows(app, app.ids['r_compliance_officer'], marker)
    with app.app_context():
        assert _user(app, 'ext').perm_vessels == 'edit'
        assert 'vessels.team' not in S.compute(_user(app, 'ext')).granted
    c = _client(app, app.ids['ext'])
    assert marker not in c.get('/screening/vessels/history').get_data(as_text=True)
    assert c.get(f'/screening/vessels/result/{sid}').status_code == 403
    assert c.get(f'/screening/vessels/result/{sid}/pdf').status_code == 403
    assert marker not in c.get('/screening/vessels/whitelist').get_data(as_text=True)
    c.post(f'/screening/vessels/whitelist/{wid}/revoke', data={'reason': 'not mine but trying'})
    from database.db import get_db
    with app.app_context():
        assert get_db().execute("SELECT status FROM vessel_whitelist WHERE id = %s", (wid,)).fetchone()['status'] == 'active'
    # a CMS user with the vessel edit level (old rule) still sees the team's records
    from models.user import User
    with app.app_context():
        mgr = User.create_user(f'acx-mgr-{uuid.uuid4().hex[:8]}@example.test', PW, 'M', 'G', role='manager',
                               cms_access_level='view', perm_vessels='edit')
        app.ids['mgr'] = mgr.id
        from database.db import get_db as g
        g().execute("UPDATE users SET must_change_password = FALSE WHERE id = %s", (mgr.id,))
        g().commit()
        assert S.team_view(_user(app, 'mgr'), 'vessels.team', False)
    m = _client(app, app.ids['mgr'])
    assert marker in m.get('/screening/vessels/history').get_data(as_text=True)
    assert marker in m.get('/screening/vessels/whitelist').get_data(as_text=True)
    # and loses it when the administrator unticks "team view"
    with app.app_context():
        acc = S.compute(_user(app, 'mgr'))
    _save(app, 'mgr', acc.mode, acc.granted - {'vessels.team'})
    assert marker not in m.get('/screening/vessels/history').get_data(as_text=True)


def test_dualuse_team_view_follows_the_matrix(app):
    from access import service as S
    with app.app_context():
        ext = _user(app, 'ext')
        assert S.compute(ext).mode == 'restricted'
        assert S.team_view(ext, 'dualuse.team', True) is False          # restricted: own screenings only
        sup = _user(app, 'super')
        assert S.team_view(sup, 'dualuse.team', False) is True


def test_no_self_escalation_and_superadmin_only_features(app):
    from access import service as S
    from database.db import get_db
    admin = _client(app, app.ids['admin'])
    # own access: read-only in the matrix, refused by the service
    page = admin.get(f"/admin/access/users/{app.ids['admin']}").get_data(as_text=True)
    assert 'read-only' in page or 'للقراءة فقط' in page
    r = admin.post(f"/admin/access/users/{app.ids['admin']}",
                   data={'cx_mode': 'cms', 'cx_feature': ['admin.users', 'vessels.database']})
    with app.app_context():
        assert not S.compute(_user(app, 'admin')).explicit.get('vessels.database')
        with pytest.raises(S.AccessError):
            S.save(_user(app, 'admin'), 'cms', {'admin.users', 'vessels.database'}, actor_id=app.ids['admin'])
    # an administrator cannot grant the Vessels Database to someone else either (kept as it was)
    uid = app.ids['r_analyst']
    _save(app, 'r_analyst', 'cms', {'vessels.view'}, actor='super')        # start without it
    admin.post(f'/admin/access/users/{uid}', data={'cx_mode': 'cms', 'cx_feature': ['vessels.view', 'vessels.database',
                                                                                     'vessels.updates']})
    with app.app_context():
        acc = S.compute(_user(app, 'r_analyst'))
        assert not acc.has('vessels.database') and not acc.has('vessels.updates') and acc.has('vessels.view')
        assert (_user(app, 'r_analyst').perm_vessels_db or 'none') == 'none'
    page = admin.get(f'/admin/access/users/{uid}').get_data(as_text=True)
    assert 'value="vessels.database"' in page and 'bi-lock-fill' in page
    assert 'value="vessels.lists"' not in page and 'value="dualuse.lists"' not in page
    # the superadmin can, and it is written to the audit log
    _save(app, 'r_analyst', 'cms', {'vessels.view', 'vessels.database'}, actor='super')
    with app.app_context():
        assert S.compute(_user(app, 'r_analyst')).has('vessels.database')
        assert get_db().execute("SELECT count(*) AS n FROM audit_logs WHERE action = 'Restricted Feature Granted' "
                                "AND item_id = %s", (uid,)).fetchone()['n'] >= 1


def test_matrix_next_is_local_only(app):
    admin = _client(app, app.ids['admin'])
    uid = app.ids['r_viewer']
    for bad in ('https://evil.example/x', '//evil.example/x', '/\\evil.example'):
        r = admin.post(f'/admin/access/users/{uid}', data={'cx_mode': 'portal', 'cx_feature': ['portal.home'],
                                                           'next': bad})
        assert r.status_code == 302 and 'evil' not in r.headers['Location'], bad


def test_gate_refusals_of_sensitive_features_are_audited(app):
    from database.db import get_db
    from access import gate as G
    G._REFUSALS.clear()
    c = _client(app, app.ids['r_employee'])
    def n():
        with app.app_context():
            return get_db().execute("SELECT count(*) AS n FROM audit_logs WHERE action = 'Access Refused' AND user_id = %s",
                                    (app.ids['r_employee'],)).fetchone()['n']
    before = n()
    for _ in range(3):
        assert c.get('/screening/vessels/database').status_code == 403
    assert n() == before + 1                      # once per user and feature in the window
    c.get('/notifications')                       # not sensitive: not audited
    assert n() == before + 1


def test_superadmin_is_cms_and_unrestricted(app):
    from access import service as S
    with app.app_context():
        sup = _user(app, 'super')
        assert S.mode_of(sup) == 'cms' and sup.can_access_cms() and S.compute(sup).unrestricted
