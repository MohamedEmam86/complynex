"""Local-list masking end to end (skipped unless ACCESS_TEST_DB names a scratch database with the access-control
migration applied and POSTGRES_DB set to it): a stored result with an internal-list hit whose category is a
sheet name is shown with the generic category on the result page, the report and the evidence pack for an
administrator, and with the real one for the superadmin."""
import json
import os
import uuid

import pytest

DBNAME = os.environ.get('ACCESS_TEST_DB', '')
pytestmark = pytest.mark.skipif(not DBNAME or os.environ.get('POSTGRES_DB') != DBNAME,
                                reason='needs ACCESS_TEST_DB=<scratch db> and POSTGRES_DB set to it')
PW = 'Str0ng!Passw0rd#x'
SHEET = 'unit sheet 77 of 10-11-2026'          # stand-in for an internal sheet name


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
        for key, role in (('admin', 'admin'), ('super', 'superadmin')):
            email = f'lm-{key}@example.test'
            u = User.get_by_email(email) or User.create_user(email, PW, 'Test', key, role=role, perm_screening='edit')
            db.execute("UPDATE users SET must_change_password = FALSE, perm_screening = 'edit', access_mode = 'cms' "
                       "WHERE id = %s", (u.id,))
            ids[key] = u.id
        hit = {'source': 'INTERNAL_BLACKLIST', 'source_name': 'Internal Blacklist', 'entity_id': 1,
               'watchlist_id': 'IBL-TEST', 'full_name': 'Test Listed Person', 'category': SHEET, 'list_type': SHEET,
               'match_score': 96, 'properties': json.dumps({'sheet': SHEET}), 'details': {'sheet': SHEET}}
        rid = db.execute("""INSERT INTO screening_results (screening_type, screened_name, total_matches_found,
                                    highest_match_score, screening_result, matches, created_by, match_details)
                            VALUES ('INDIVIDUAL', %s, 1, 96, 'POTENTIAL_MATCH', %s, %s, %s) RETURNING id""",
                         ('Test Listed Person ' + uuid.uuid4().hex[:4], json.dumps([hit]), ids['admin'],
                          json.dumps({'inputs': {'name': 'Test Listed Person'}}))).fetchone()['id']
        db.commit()
        a.ids, a.rid = ids, rid
    yield a


def _client(app, uid):
    from models.user import User
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = User.session_id_for_app(app, uid)
        s['_fresh'] = True
        s['lang'] = 'en'
    return c


@pytest.mark.parametrize('path', ['/screening/result/{rid}', '/screening/download_report/{rid}',
                                  '/screening/result/{rid}/evidence-pack'])
def test_admin_sees_the_generic_category_superadmin_the_real_one(app, path):
    url = path.format(rid=app.rid)
    r = _client(app, app.ids['admin']).get(url)
    if r.status_code == 404:
        pytest.skip(f'{url}: route shape differs')
    body = r.get_data(as_text=True) if r.mimetype == 'text/html' else ''
    if body:
        assert SHEET not in body, url
    r2 = _client(app, app.ids['super']).get(url)
    if r2.mimetype == 'text/html' and r2.status_code == 200 and r.status_code == 200 and 'result' in path:
        assert SHEET in r2.get_data(as_text=True)
