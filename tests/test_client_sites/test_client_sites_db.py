"""Client sites against a real database (skipped unless CLIENT_SITES_TEST_DB names a scratch database with
database/migrations/20261121_client_sites.sql applied and POSTGRES_DB set to it): sign-in per host, the session
cookie per host, sessions refused on the wrong host, the superadmin pages (render, create, users, usage, logo),
other roles refused, the site's default daily limit and the monthly organisation cap."""
import io
import os
import re

import pytest

DBNAME = os.environ.get('CLIENT_SITES_TEST_DB', '')
pytestmark = pytest.mark.skipif(not DBNAME or os.environ.get('POSTGRES_DB') != DBNAME,
                                reason='needs CLIENT_SITES_TEST_DB=<scratch db> and POSTGRES_DB set to it')
PW = 'Str0ng!Passw0rd#x'
HOST = 'cxt.example.test'
MAIN = 'http://localhost'
SITE = 'http://' + HOST


@pytest.fixture(scope='module')
def app(tmp_path_factory):
    from config import config
    if os.environ.get('FLASK_ENV') not in config:
        os.environ['FLASK_ENV'] = 'development'
    from app import create_app
    a = create_app()
    a.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=str(tmp_path_factory.mktemp('uploads')))
    from client_sites import service as CS
    with a.app_context():
        from database.db import get_db
        from models.user import User
        db = get_db()
        db.execute("UPDATE users SET site_id = NULL WHERE email LIKE 'cst-%%@example.test'")
        db.execute("DELETE FROM screening_daily_usage WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'cst-%%@example.test')")
        db.execute("DELETE FROM client_sites WHERE host LIKE '%%.example.test'")
        db.commit()
        sid = CS.save_site({'host': HOST, 'name_en': 'Example Client', 'name_ar': 'عميل تجريبي', 'welcome_en': 'Welcome',
                            'welcome_ar': 'مرحباً', 'allowed_access_modes': ['restricted'], 'default_access_mode': 'restricted',
                            'contact_email': 'help@example.test', 'default_daily_screening_limit': 50,
                            'monthly_org_cap': 3, 'active': True})
        ids = {}
        for key, role in (('site', 'employee'), ('site2', 'employee'), ('main', 'employee'), ('admin', 'admin'),
                          ('super', 'superadmin')):
            email = f'cst-{key}@example.test'
            u = User.get_by_email(email) or User.create_user(email, PW, 'Test', key, role=role)
            db.execute('UPDATE users SET must_change_password = FALSE, mfa_required_override = FALSE, '
                       'screening_daily_limit = NULL WHERE id = %s', (u.id,))
            ids[key] = u.id
        db.commit()
        for key in ('site', 'site2'):
            assert CS.assign_user(sid, ids[key])
        a.ids, a.site_id = ids, sid
    CS.invalidate()
    yield a
    CS.invalidate()


def _session(app, uid, base_url):
    from models.user import User
    c = app.test_client()
    with c.session_transaction(base_url=base_url) as s:
        s['_user_id'] = User.session_id_for_app(app, uid)
        s['_fresh'] = True
    return c


def _login(app, key, base_url):
    return app.test_client().post('/auth/portal/login', base_url=base_url,
                                  data={'email': f'cst-{key}@example.test', 'password': PW, 'ws': '1'})


def test_site_user_signs_in_on_site_host_only(app):
    r = _login(app, 'site', SITE)
    assert r.status_code == 302, r.data[:300]
    assert '/workspace' in r.headers['Location'] or '/portal' in r.headers['Location']
    cookies = r.headers.getlist('Set-Cookie')
    assert any(h.startswith(f'cx_session_{app.site_id}=') for h in cookies), cookies
    r = _login(app, 'site', MAIN)
    assert r.status_code == 200 and b'cx-site-foot' not in r.data
    r = _login(app, 'main', SITE)
    assert r.status_code == 200 and b'cx-site-foot' in r.data        # the site's page, the usual refusal message


def test_sessions_never_cross_hosts(app):
    c = _session(app, app.ids['site'], SITE)
    assert c.get('/workspace', base_url=SITE).status_code == 200
    c = _session(app, app.ids['site'], MAIN)          # a site user's identity presented on the main host
    r = c.get('/workspace', base_url=MAIN)
    assert r.status_code == 302 and '/auth/login' in r.headers['Location']
    c = _session(app, app.ids['main'], SITE)
    r = c.get('/workspace', base_url=SITE)
    assert r.status_code == 302 and '/auth/login' in r.headers['Location']


def test_superadmin_pages(app):
    c = _session(app, app.ids['super'], MAIN)
    sid = app.site_id
    for path in ('/admin/client-sites', '/admin/client-sites/new', f'/admin/client-sites/{sid}/edit',
                 f'/admin/client-sites/{sid}/users', f'/admin/client-sites/{sid}/usage'):
        r = c.get(path, base_url=MAIN)
        assert r.status_code == 200, (path, r.status_code)
        body = r.get_data(as_text=True)
        assert ' onclick=' not in body and ' onsubmit=' not in body
        inline = [s for s in re.findall(r'<script[^>]*>', body) if 'src=' not in s and 'application/json' not in s]
        assert all('nonce=' in s for s in inline), (path, [s for s in inline if 'nonce=' not in s])
    assert 'cst-site@example.test' in c.get(f'/admin/client-sites/{sid}/users', base_url=MAIN).get_data(as_text=True)
    # the superadmin works on a client host too
    c2 = _session(app, app.ids['super'], SITE)
    assert c2.get('/admin/client-sites', base_url=SITE).status_code == 200


def test_other_roles_refused(app):
    for key in ('admin', 'main'):
        c = _session(app, app.ids[key], MAIN)
        for path in ('/admin/client-sites', f'/admin/client-sites/{app.site_id}/usage'):
            assert c.get(path, base_url=MAIN).status_code == 403, (key, path)
        assert c.post(f'/admin/client-sites/{app.site_id}/users/add', base_url=MAIN,
                      data={'user_id': app.ids['main']}).status_code == 403


def test_create_edit_logo_and_users(app):
    from PIL import Image
    c = _session(app, app.ids['super'], MAIN)
    r = c.post('/admin/client-sites/new', base_url=MAIN, data={
        'host': 'second.example.test', 'name_en': 'Second Client', 'allowed_access_modes': ['restricted', 'portal'],
        'default_access_mode': 'portal', 'monthly_org_cap': '0', 'active': '1'})
    assert r.status_code == 302, r.data[:500]
    new_id = int(re.search(r'/client-sites/(\d+)/edit', r.headers['Location']).group(1))
    bad = c.post('/admin/client-sites/new', base_url=MAIN, data={'host': HOST, 'name_en': 'Dup',
                                                                 'allowed_access_modes': 'restricted'})
    assert bad.status_code == 400
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), (18, 62, 95)).save(buf, 'PNG')
    r = c.post(f'/admin/client-sites/{new_id}/edit', base_url=MAIN, content_type='multipart/form-data', data={
        'host': 'second.example.test', 'name_en': 'Second Client', 'name_ar': 'العميل الثاني',
        'allowed_access_modes': 'restricted', 'default_access_mode': 'restricted', 'monthly_org_cap': '10',
        'active': '1', 'logo': (io.BytesIO(buf.getvalue()), 'logo.png')})
    assert r.status_code == 302
    from client_sites import service as CS
    with app.app_context():
        s = CS.site_by_id(new_id)
        assert s['logo_path'] == f'client_sites/site_{new_id}.png' and s['monthly_org_cap'] == 10
    CS.invalidate()
    r = app.test_client().get(f'/auth/site-logo/{new_id}', base_url='http://second.example.test')
    assert r.status_code == 200 and r.mimetype == 'image/png'
    assert app.test_client().get(f'/auth/site-logo/{new_id}', base_url=MAIN).status_code == 404
    assert app.test_client().get(f'/auth/site-logo/{new_id}', base_url=SITE).status_code == 404
    assert c.get(f'/auth/site-logo/{new_id}', base_url=MAIN).status_code == 200     # superadmin preview
    r = app.test_client().get('/auth/login', base_url='http://second.example.test')
    assert f'/auth/site-logo/{new_id}'.encode() in r.data
    # bind / unbind a user (POST only)
    assert c.post(f'/admin/client-sites/{new_id}/users/add', base_url=MAIN,
                  data={'user_id': app.ids['main']}).status_code == 302
    with app.app_context():
        from database.db import get_db
        assert get_db().execute('SELECT site_id FROM users WHERE id = %s', (app.ids['main'],)).fetchone()['site_id'] == new_id
    assert c.post(f'/admin/client-sites/{new_id}/users/{app.ids["main"]}/remove', base_url=MAIN).status_code == 302
    with app.app_context():
        from database.db import get_db
        db = get_db()
        assert db.execute('SELECT site_id FROM users WHERE id = %s', (app.ids['main'],)).fetchone()['site_id'] is None
        db.execute("DELETE FROM client_sites WHERE id = %s", (new_id,))
        db.commit()
    CS.invalidate()
    assert app.test_client().get('/auth/login', base_url='http://second.example.test').status_code == 404


def test_site_default_limit_and_monthly_cap(app):
    from models.user import User
    from screening import limits as L
    with app.test_request_context('/', base_url=SITE):
        from database.db import get_db
        db = get_db()
        u1, u2 = User.get_by_id(app.ids['site']), User.get_by_id(app.ids['site2'])
        assert L.limit_for(u1, db) == 50                # the site's default daily limit
        db.execute("DELETE FROM screening_daily_usage WHERE user_id IN (%s, %s)", (u1.id, u2.id))
        db.commit()
        L.consume(2, 'vessel', user=u2, db=db)          # 2 of the cap of 3
        L.consume(4, 'name', user=u1, db=db)            # names are not capped
        with pytest.raises(L.MonthlyCapReached) as e:
            L.consume(2, 'dualuse', user=u1, db=db)     # 2 + 2 > 3, refused whole
        assert e.value.remaining == 1
        L.consume(1, 'dualuse', user=u1, db=db)         # exactly the cap
        with pytest.raises(L.MonthlyCapReached):
            L.consume(1, 'vessel', user=u1, db=db)
        from client_sites import service as CS
        rows, total, _start = CS.usage_by_user(app.site_id, L.today(), db)
        assert total == 3 and {r['email']: r['capped'] for r in rows}['cst-site2@example.test'] == 2
    c = _session(app, app.ids['super'], MAIN)
    body = c.get(f'/admin/client-sites/{app.site_id}/usage', base_url=MAIN).get_data(as_text=True)
    assert 'cst-site@example.test' in body and 'cst-site2@example.test' in body
