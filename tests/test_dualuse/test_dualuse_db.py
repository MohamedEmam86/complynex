"""Dual-use goods module against a real database (skipped unless DUALUSE_TEST_DB names a scratch database with
the 20261117_dualuse migration applied and POSTGRES_* pointing at it): pack registration and permissions,
every page as a site administrator, a user with the permission (edit / view) and a user without it, a single
and a batch screening, the mandatory reason and comment, the decision trail, exports, the generic list label
for clients and the importer's version handling."""
import io
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
DBNAME = os.environ.get('DUALUSE_TEST_DB', '')
pytestmark = pytest.mark.skipif(not DBNAME or os.environ.get('POSTGRES_DB') != DBNAME,
                                reason='needs DUALUSE_TEST_DB=<scratch db> and POSTGRES_DB set to it')

LEAK = ('eu_annex1', 'us_ccl', 'chpl', 'EU 2021/821', 'US CCL', 'CWC schedules', 'Common High Priority', 'eCFR',
        'consolidated text', 'OPCW', 'Chemicals register')
PW = 'Str0ng!Passw0rd#x'


@pytest.fixture(scope='module')
def app():
    from app import create_app
    a = create_app()
    a.config['WTF_CSRF_ENABLED'] = False
    with a.app_context():
        from database.db import get_db
        from models.user import User
        from regcontrols import packs
        db = get_db()
        ids = {}
        for email, role, perm in (('du-admin@example.test', 'admin', None), ('du-edit@example.test', 'employee', 'edit'),
                                  ('du-view@example.test', 'employee', 'view'), ('du-none@example.test', 'employee', None),
                                  ('du-super@example.test', 'superadmin', None),
                                  ('du-itadm@example.test', 'it_admin', None)):
            u = User.get_by_email(email) or User.create_user(email, PW, 'Test', 'User', role=role)
            ids[email.split('@')[0][3:]] = u.id
            if perm:
                packs.save_module_perms(u.id, {'modperm_dualuse': perm})
        packs.enable('trade_control', ids['admin'])
        a.du_ids = ids
    # no app context stays pushed: each test-client request must load its own user
    yield a


def _client(app, uid, lang='en'):
    from models.user import User
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = User.session_id_for_app(app, uid)
        s['_fresh'] = True
        s['language'] = lang
    return c


def test_pack_and_permission_are_registered(app):
    from regcontrols import packs
    assert 'trade_control' in packs.PACKS
    assert any(m[0] == 'dualuse' for m in packs.permission_modules())
    with app.app_context():
        from models.user import User
        assert User.get_by_id(app.du_ids['edit']).can_edit('dualuse')
        v = User.get_by_id(app.du_ids['view'])
        assert v.can_view('dualuse') and not v.can_edit('dualuse')
        assert not User.get_by_id(app.du_ids['none']).can_view('dualuse')


def test_screen_decide_and_pages(app):
    ids = app.du_ids
    adm = _client(app, ids['edit'])
    r = adm.post('/dual-use/screen', data={'description': 'Thionyl chloride', 'cas': '7719-09-7',
                                           'supplier': '=HYPERLINK("http://example.invalid")',
                                           'vessel_name': 'OCEAN STAR', 'vessel_imo': '9074729'})
    assert r.status_code == 302
    sid = int(re.search(r'/screenings/(\d+)', r.headers['Location']).group(1))
    with app.app_context():
        from database.db import get_db
        db = get_db()
        s = db.execute("SELECT * FROM dualuse_screenings WHERE id = %s", (sid,)).fetchone()
        assert s['vessel_name'] == 'OCEAN STAR' and s['vessel_result']          # screened or 'unavailable'
        line = db.execute("SELECT * FROM dualuse_screening_lines WHERE screening_id = %s", (sid,)).fetchone()
    # the reason and the comment are mandatory
    adm.post('/dual-use/lines/%d/decide' % line['id'], data={'decision': 'clear', 'reason': '', 'comment': ''})
    with app.app_context():
        from database.db import get_db
        assert get_db().execute("SELECT decision FROM dualuse_screening_lines WHERE id = %s",
                                (line['id'],)).fetchone()['decision'] is None
    r = adm.post('/dual-use/lines/%d/decide' % line['id'],
                 data={'decision': 'hold', 'reason': 'controlled_item', 'comment': 'Listed precursor: licence needed'})
    assert r.status_code == 302
    with app.app_context():
        from database.db import get_db
        trail = get_db().execute("SELECT * FROM dualuse_decisions WHERE line_id = %s", (line['id'],)).fetchall()
        assert len(trail) == 1 and trail[0]['decision'] == 'hold' and trail[0]['decided_by'] == ids['edit']
    # batch upload with column mapping
    data = 'Description,HS,CAS\nThionyl chloride,2812.17,7719-09-7\noffice chairs,9401.30,\n'.encode()
    r = adm.post('/dual-use/batch', data={'file': (io.BytesIO(data), 'invoice.csv')}, content_type='multipart/form-data')
    tok = re.search(r'name="token" value="([0-9a-f]{32})"', r.get_data(as_text=True)).group(1)
    r = adm.post('/dual-use/batch/run', data={'token': tok, 'col_description': '0', 'col_hs_code': '1', 'col_cas': '2'})
    bid = int(re.search(r'/screenings/(\d+)', r.headers['Location']).group(1))
    with app.app_context():
        from database.db import get_db
        lines = get_db().execute("SELECT * FROM dualuse_screening_lines WHERE screening_id = %s ORDER BY line_no",
                                 (bid,)).fetchall()
        assert [l['suggested'] for l in lines] == ['hold', 'clear']
        # nothing is decided automatically, and a line with hold flags never gets a proposal
        assert all(l['decision'] is None for l in lines) and lines[0]['proposal'] is None
    urls = ['/dual-use/', '/dual-use/?q=encryption', '/dual-use/?q=%D9%85%D8%AE%D8%B1%D8%B7%D8%A9',
            '/dual-use/?category=1', '/dual-use/?q=7719097', '/dual-use/api/suggest?q=enc', '/dual-use/api/search?q=1C350',
            '/dual-use/screenings', '/dual-use/screenings/%d' % sid, '/dual-use/screenings/%d' % bid,
            '/dual-use/screenings/%d/export.xlsx' % bid, '/dual-use/screenings/%d/export.pdf' % sid]
    own = ('/dual-use/screenings/%d' % sid, '/dual-use/screenings/%d' % bid,
           '/dual-use/screenings/%d/export.xlsx' % bid, '/dual-use/screenings/%d/export.pdf' % sid)
    for who, expect in (('super', 200), ('itadm', 200), ('admin', 200), ('edit', 200), ('view', 200), ('none', 403)):
        for lang in ('en', 'ar'):
            c = _client(app, ids[who], lang)
            for u in urls:
                r = c.get(u)
                # a view-only user opens only their own screenings (the vessel module's rule)
                want = 403 if (who == 'view' and u in own) else expect
                assert r.status_code == want, (who, lang, u, r.status_code)
                if who != 'super' and r.mimetype in ('text/html', 'application/json'):
                    body = r.get_data(as_text=True)
                    assert not [w for w in LEAK if w in body], (who, u)
    # only the platform superadmin sees the real lists
    body = _client(app, ids['super']).get('/dual-use/api/search?q=1C350').get_data(as_text=True)
    assert 'eu_annex1' in body or 'us_ccl' in body
    hist = _client(app, ids['view']).get('/dual-use/screenings').get_data(as_text=True)
    assert 'Showing your own screenings' in hist or 'عمليات الفحص الخاصة بك فقط' in hist
    for who, code in (('super', 200), ('itadm', 200), ('admin', 200), ('edit', 403), ('view', 403), ('none', 403)):
        assert _client(app, ids[who]).get('/dual-use/admin').status_code == code, who
    for who, code in (('super', 200), ('edit', 200), ('view', 403), ('none', 403)):
        assert _client(app, ids[who]).get('/dual-use/screen').status_code == code
    r = _client(app, ids['edit']).get('/dual-use/screenings/%d/export.pdf' % sid)
    assert r.mimetype == 'application/pdf' and r.data[:4] == b'%PDF'
    # spreadsheet formula injection: the supplier name is written as text
    import openpyxl
    r = _client(app, ids['edit']).get('/dual-use/screenings/%d/export.xlsx' % sid)
    cells = [c.value for row in openpyxl.load_workbook(io.BytesIO(r.data)).active.iter_rows() for c in row]
    assert "'=HYPERLINK(\"http://example.invalid\")" in cells
    assert not any(isinstance(v, str) and v.startswith('=') for v in cells)


def test_versions_carry_arabic_and_mark_stale(app):
    import importlib.util
    spec = importlib.util.spec_from_file_location('du_imp', os.path.join(ROOT, 'scripts', 'dualuse', 'import_lists.py'))
    imp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(imp)
    conn = imp.connect()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO dualuse_lists (code, legal_name) VALUES ('zz_test', 'test') RETURNING id")
        lid = cur.fetchone()['id']
        items = [{'code': 'Z%d' % i, 'text_en': 'text %d' % i, 'params': []} for i in range(3)]
        v1 = imp.new_version(cur, lid, 'v1', None, imp.content_digest(items), 3, {}, {}, 't')
        imp.write_items(cur, v1, items, [])
        imp.make_current(cur, lid, v1)
        cur.execute("UPDATE dualuse_items SET text_ar = 'نص', ar_status = 'reviewed' WHERE version_id = %s", (v1,))
        cur.execute("SELECT * FROM dualuse_items WHERE version_id = %s", (v1,))
        old = cur.fetchall()
        items2 = [dict(i) for i in items]
        items2[0]['text_en'] = 'changed'
        assert imp.content_digest(items2) != imp.content_digest(items)
        v2 = imp.new_version(cur, lid, 'v2', None, imp.content_digest(items2), 3, {}, imp.diff_items(old, items2), 't')
        imp.write_items(cur, v2, items2, old)
        imp.make_current(cur, lid, v2)
        cur.execute("SELECT code, ar_status, text_ar FROM dualuse_items WHERE version_id = %s ORDER BY code", (v2,))
        rows = cur.fetchall()
        assert [(r['code'], r['ar_status']) for r in rows] == [('Z0', 'stale'), ('Z1', 'reviewed'), ('Z2', 'reviewed')]
        assert all(r['text_ar'] == 'نص' for r in rows)
        cur.execute("SELECT id FROM dualuse_list_versions WHERE list_id = %s AND is_current", (lid,))
        assert [r['id'] for r in cur.fetchall()] == [v2]
        assert imp.diff_items(old, items2)['changed'] == 1
    finally:
        conn.rollback()
        conn.close()


def test_arabic_text_carries_the_draft_note(app):
    with app.app_context():
        from database.db import get_db
        row = get_db().execute("""SELECT i.id FROM dualuse_items i JOIN dualuse_list_versions v ON v.id = i.version_id
                                  AND v.is_current JOIN dualuse_lists l ON l.id = v.list_id AND l.code = 'eu_annex1'
                                  WHERE i.text_ar IS NOT NULL AND i.ar_status = 'draft' AND NOT i.not_used
                                  LIMIT 1""").fetchone()
    if not row:
        pytest.skip('no Arabic texts loaded')
    for lang in ('ar', 'en'):
        r = _client(app, app.du_ids['edit'], lang).get('/dual-use/entry/%d' % row['id'])
        body = r.get_data(as_text=True)
        assert r.status_code == 200
        assert 'ترجمة عربية مبدئية — النص الإنجليزي هو المرجع القانوني' in body or \
            'Arabic draft translation — English is the legal reference' in body


def test_reuse_is_a_proposal_confirmed_by_the_current_user(app):
    """Review r2 N-B1: a remembered decision is never applied to a different product (same model, different
    description) nor to a line with hold flags, and on an identical product it is only a proposal."""
    ids = app.du_ids
    a, b = _client(app, ids['edit']), _client(app, ids['super'])

    def screen(c, **line):
        r = c.post('/dual-use/screen', data=line)
        sid = int(re.search(r'/screenings/(\d+)', r.headers['Location']).group(1))
        with app.app_context():
            from database.db import get_db
            return get_db().execute("SELECT * FROM dualuse_screening_lines WHERE screening_id = %s", (sid,)).fetchone()

    chairs = dict(description='Office chairs, black leather', hs_code='940130', model='X-100')
    ln = screen(a, **chairs)
    assert ln['suggested'] == 'clear'
    a.post('/dual-use/lines/%d/decide' % ln['id'], data={'decision': 'clear', 'reason': 'not_controlled',
                                                         'comment': 'Furniture, no control entry', 'remember': '1'})
    # same model, different product: a listed chemical is held and gets no proposal
    tdg = screen(b, description='Thiodiglycol 99% drum', hs_code='9401.30', model='X100')
    assert tdg['suggested'] == 'hold' and tdg['decision'] is None and tdg['proposal'] is None
    # the identical product: a proposal only, decided by nobody until confirmed
    again = screen(b, **chairs)
    assert again['decision'] is None and again['decided_by'] is None and again['proposal']['decision'] == 'clear'
    r = b.post('/dual-use/lines/%d/confirm' % again['id'], data={'comment': 'Same chairs, same supplier'})
    assert r.status_code == 302
    with app.app_context():
        from database.db import get_db
        row = get_db().execute("SELECT * FROM dualuse_screening_lines WHERE id = %s", (again['id'],)).fetchone()
        assert row['decision'] == 'clear' and row['decided_by'] == ids['super'] and row['proposal'] is None
        t = get_db().execute("SELECT * FROM dualuse_decisions WHERE line_id = %s", (again['id'],)).fetchall()
        assert len(t) == 1 and t[0]['decided_by'] == ids['super'] and 'Confirmed the earlier decision' in t[0]['comment']


def test_lists_unavailable_never_clear():
    from packs.trade_control import screening as SC, search as SE
    r = SC.screen_line(SE.Index([], []), {'description': 'Hydrofluoric acid', 'cas': '7664-39-3', 'hs_code': '281111'})
    assert r['suggested'] == 'review' and any(h['flag'] == 'lists_unavailable' for h in r['hard'])


REVIEW_CASES = [  # review r2 N-B2: clear-cut controlled goods must never come out clear
    ({'description': 'Network encryptor AES-256 for government networks'}, ('5A00',), None),
    ({'description': 'Maraging steel bar 350 grade, 100 mm diameter'}, ('1C116', '1C216'), None),
    ({'description': 'طائرة بدون طيار للتصوير الزراعي'}, ('9A012', '9A112', '9A120'), None),
    ({'description': 'حمض الهيدروفلوريك 49%'}, (), 'hold'),
    ({'description': 'Hydrofluoric acid 49% solution', 'hs_code': '281111'}, (), 'hold'),
    ({'description': 'Pressure transducer 0-10 kPa absolute, Inconel', 'hs_code': '902620'}, ('2B230',), None),
    ({'description': 'Quadcopter drone 25 min flight', 'hs_code': '880621'}, ('9A012',), None),
    ({'description': 'Frequency synthesizer 40 GHz'}, ('3A001', '3A002'), None),
    ({'description': 'Pressure transducer 0-10 kPa absolute, Inconel diaphragm', 'hs_code': 9026.2}, ('2B230',), None),
    ({'description': 'Thiodiglycol 99% drum', 'hs_code': '9401.30', 'model': 'X100'}, (), 'hold'),
    ({'description': 'office chairs', 'hs_code': '9401.30'}, (), 'clear'),
    ({'description': 'cotton t-shirts', 'hs_code': '6109.10'}, (), 'clear'),
]


def test_review_cases_on_the_loaded_lists(app):
    with app.app_context():
        from packs.trade_control import service as S, screening as SC
        idx = S.get_index(force=True)
        if not idx.ready:
            pytest.skip('lists not loaded')
        for line, codes, outcome in REVIEW_CASES:
            r = SC.screen_line(idx, line)
            got = [c['code'] for c in r['candidates']]
            if outcome:
                assert r['suggested'] == outcome, (line, r['suggested'], got)
            else:
                assert r['suggested'] != 'clear' and any(g.startswith(codes) for g in got), (line, got)
                # answering "no" to every threshold question never clears a candidate
                no = {q['id']: 'no' for q in r['questions'] if q['type'] == 'threshold'}
                assert SC.evaluate(r['candidates'], r['hard'], r['questions'], no, line)[0] != 'clear'
