"""Daily screening limits (skipped unless ACCESS_TEST_DB names a scratch database with the
20261123_screening_daily_limits migration applied and POSTGRES_DB set to it)."""
import os
import uuid

import pytest

DBNAME = os.environ.get('ACCESS_TEST_DB', '')
pytestmark = pytest.mark.skipif(not DBNAME or os.environ.get('POSTGRES_DB') != DBNAME,
                                reason='needs ACCESS_TEST_DB=<scratch db> and POSTGRES_DB set to it')
PW = 'Str0ng!Passw0rd#x'


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
            email = f'dl-{key}-{uuid.uuid4().hex[:6]}@example.test'
            u = User.create_user(email, PW, 'Test', key, role=role, perm_screening='edit', perm_vessels='edit')
            db.execute("UPDATE users SET must_change_password = FALSE, access_mode = 'cms' WHERE id = %s", (u.id,))
            ids[key] = u.id
        db.commit()
        a.ids = ids
    yield a


def _u(app, key):
    from models.user import User
    return User.get_by_id(app.ids[key])


def _client(app, key):
    from models.user import User
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = User.session_id_for_app(app, app.ids[key])
        s['_fresh'] = True
        s['lang'] = 'en'
    return c


def test_default_is_unlimited_and_counting_still_happens(app):
    from screening import limits as L
    with app.app_context():
        assert L.default_limit() == 0
        u = _u(app, 'officer')
        assert L.limit_for(u) is None and L.remaining(u) is None
        L.consume(3, 'name', user=u)
        assert L.used(u.id) == 3


def test_limit_refuses_and_bulk_is_all_or_nothing(app):
    from screening import limits as L
    with app.app_context():
        L.set_user_limit(app.ids['officer'], 5, app.ids['admin'], note='test')
        u = _u(app, 'officer')
        L.reset_today(u.id, app.ids['admin'])
        assert L.remaining(u) == 5
        L.consume(1, 'vessel', user=u)
        with pytest.raises(L.DailyLimitReached) as e:
            L.consume(10, 'dualuse', user=u)          # a batch of 10: refused whole
        assert e.value.remaining == 4 and 'only 4' in e.value.message('en') and 'المتبقي' in e.value.message('ar')
        assert L.used(u.id) == 1
        job = f'name:test-{uuid.uuid4().hex}'
        L.consume_job(job, 4, 'name', user=u)
        L.consume_job(job, 4, 'name', user=u)    # resumed: not counted twice
        assert L.remaining(u) == 0
        with pytest.raises(L.DailyLimitReached) as e2:
            L.consume(1, 'name', user=u)
        assert 'You reached your daily screening limit (5)' in e2.value.message('en')
        # the superadmin has no limit
        s = _u(app, 'super')
        L.set_user_limit(s.id, 1, app.ids['admin'])
        assert L.limit_for(_u(app, 'super')) is None
        L.consume(50, 'name', user=_u(app, 'super'))


def test_pages_show_the_bilingual_message(app):
    """Over the limit: the JSON screening endpoint answers 429 (bilingual), the form redirects with the message."""
    c = _client(app, 'officer')
    r = c.post('/screening/api/screen/person', json={'name': 'Test Person'})
    assert r.status_code == 429
    j = r.get_json()
    assert j['error'] == 'daily_limit_reached' and 'لقد وصلت' in j['message_ar'] and j['limit'] == 5
    r = c.post('/screening/manual', data={'name': 'Test Person', 'entity_type': 'INDIVIDUAL', 'threshold': '75'},
               headers={'Referer': 'http://localhost/screening/manual'})
    if r.status_code != 404:
        assert r.status_code == 302
        with c.session_transaction() as s:
            msgs = ' '.join(m for _cat, m in s.get('_flashes', []))
        assert 'daily screening limit' in msgs
    r = c.post('/screening/vessels/screen', data={'name': 'HERA'}, headers={'Referer': 'http://localhost/screening/vessels/screen'})
    assert r.status_code == 302


def test_admin_page_reset_and_raise_are_audited(app):
    from database.db import get_db
    from screening import limits as L
    a = _client(app, 'admin')
    page = a.get('/admin/screening-limits').get_data(as_text=True)
    assert 'Usage today' in page and 'Default daily limit per user' in page
    uid = app.ids['officer']
    r = a.post(f'/admin/screening-limits/user/{uid}', data={'action': 'reset', 'note': 'test'})
    assert r.status_code == 302
    r = a.post(f'/admin/screening-limits/user/{uid}', data={'action': 'limit', 'limit': '20'})
    assert r.status_code == 302
    with app.app_context():
        assert L.used(uid) == 0 and L.limit_for(_u(app, 'officer')) == 20
        acts = [r['action'] for r in get_db().execute(
            "SELECT action FROM screening_limit_events WHERE user_id = %s ORDER BY id", (uid,)).fetchall()]
        assert 'reset' in acts and acts[-1] == 'limit_set'
        assert get_db().execute("SELECT count(*) AS n FROM audit_logs WHERE action LIKE 'Screening Limit%%' "
                                "AND item_id = %s", (uid,)).fetchone()['n'] >= 2
    # non-administrators cannot use the page
    assert _client(app, 'officer').get('/admin/screening-limits').status_code in (302, 403)
    # the user page field
    r = a.post(f'/admin/access/users/{uid}', data={'cx_mode': 'cms', 'cx_feature': ['screening.name.view'],
                                                    'cx_daily_limit': '7'})
    with app.app_context():
        assert L.limit_for(_u(app, 'officer')) == 7
        L.set_user_limit(uid, None, app.ids['admin'])          # back to the default (unlimited)
