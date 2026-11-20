"""List-management pages are platform-superadmin only; clients get 'Lists status' under our names; profile links
carry an opaque reference. Skipped unless ACCESS_TEST_DB names a scratch database and POSTGRES_DB is set to it."""
import os
import re
import uuid

import pytest

DBNAME = os.environ.get('ACCESS_TEST_DB', '')
pytestmark = pytest.mark.skipif(not DBNAME or os.environ.get('POSTGRES_DB') != DBNAME,
                                reason='needs ACCESS_TEST_DB=<scratch db> and POSTGRES_DB set to it')
PW = 'Str0ng!Passw0rd#x'
REAL = re.compile(r'opensanctions|OFAC|HM Treasury|OFSI|EMLCU|treasury\.gov|https?://(?!localhost)', re.I)


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
        ids = {}
        for key, role in (('admin', 'admin'), ('super', 'superadmin'), ('officer', 'compliance_officer')):
            u = User.create_user(f'ls-{key}-{uuid.uuid4().hex[:6]}@example.test', PW, 'Test', key, role=role,
                                 perm_screening='edit')
            db.execute("UPDATE users SET must_change_password = FALSE, access_mode = 'cms' WHERE id = %s", (u.id,))
            ids[key] = u.id
        db.commit()
        a.ids = ids
    yield a


def _client(app, key):
    from models.user import User
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = User.session_id_for_app(app, app.ids[key])
        s['_fresh'] = True
        s['lang'] = 'en'
    return c


@pytest.mark.parametrize('path', ['/screening/sources', '/screening/urls', '/screening/lists/versions',
                                  '/screening/lists/local-import', '/screening/audit-log'])
def test_list_management_is_superadmin_only(app, path):
    for key in ('admin', 'officer'):
        assert _client(app, key).get(path).status_code == 403, (key, path)
    assert _client(app, 'super').get(path).status_code in (200, 302)


def test_lists_status_shows_only_our_names(app):
    for key in ('admin', 'officer'):
        r = _client(app, key).get('/screening/lists/status')
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert 'Lists status' in html
        body = html.split('<main', 1)[-1]
        assert not REAL.search(re.sub(r'<script.*?</script>|<link[^>]*>|<a [^>]*href="https?://[^"]*complynex[^"]*"', '', body, flags=re.S))
    assert _client(app, 'super').get('/screening/lists/status').status_code == 200


def test_profile_reference_is_opaque_and_old_links_redirect(app):
    from screening import list_display as LD
    with app.test_request_context():
        tok = LD.profile_ref('OFAC', '123')
        assert 'OFAC' not in tok and '123' not in tok
        assert LD.resolve_profile_ref(tok) == ('OFAC', '123')
        assert LD.resolve_profile_ref('garbage') == (None, None)
    r = _client(app, 'officer').get('/screening/result/999999999/profile?src=OFAC&rec=1')
    assert r.status_code == 302 and 'src=' not in r.headers['Location'] and 'p=' in r.headers['Location']
    # the superadmin's old link is used as it is (no redirect to the opaque form)
    r = _client(app, 'super').get('/screening/result/999999999/profile?src=OFAC&rec=1')
    assert 'p=' not in r.headers.get('Location', '')
    assert _client(app, 'officer').get('/screening/result/999999999/profile?p=bad').status_code == 404
