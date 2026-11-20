"""Dual-use goods, round 3, against a real database (same switch as test_dualuse_db.py): explosives precursors
with their limit value, the guidance layer (data, versions, matching, generic wording for clients), the
landing / catalogue / guidance pages, the decision memo, and the superadmin list-update pages (check now,
upload, what changed, stale flag)."""
import io
import os
import re

import pytest

from tests.test_dualuse.test_dualuse_db import DBNAME, LEAK, _client, app  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not DBNAME or os.environ.get('POSTGRES_DB') != DBNAME,
                                reason='needs DUALUSE_TEST_DB=<scratch db> and POSTGRES_DB set to it')
CLIENT_LEAK = LEAK + ('2019/1148', 'CHPL', 'Australia Group', 'ECCN', 'eur-lex', 'publications.europa.eu', 'bis.gov')


def _precursors_loaded(app):
    with app.app_context():
        from database.db import get_db
        r = get_db().execute("""SELECT v.record_count FROM dualuse_list_versions v JOIN dualuse_lists l ON l.id = v.list_id
                                WHERE l.code = 'eu_expl_precursors' AND v.is_current""").fetchone()
        return bool(r and r['record_count'])


def url_ok(body):
    return '/dual-use/browse/5' in body and '/dual-use/screen' in body


def _line(app, sid):
    with app.app_context():
        from database.db import get_db
        return get_db().execute("SELECT * FROM dualuse_screening_lines WHERE screening_id = %s", (sid,)).fetchone()


def test_ammonium_nitrate_below_the_limit_is_outside_the_restriction(app):
    if not _precursors_loaded(app):
        pytest.skip('explosives precursors list not loaded')
    c = _client(app, app.du_ids['edit'])
    r = c.post('/dual-use/screen', data={'description': 'Ammonium nitrate fertiliser', 'cas': '6484-52-2'})
    sid = int(re.search(r'/screenings/(\d+)', r.headers['Location']).group(1))
    ln = _line(app, sid)
    cand = {x['code']: x for x in ln['candidates']}
    assert 'XP-I.6484-52-2' in cand
    q = next(q for q in ln['questions'] if q.get('complete'))
    assert q['code'] == 'XP-I.6484-52-2' and q['operator'] == '>' and q['value'] == 16
    c.post('/dual-use/lines/%d/answers' % ln['id'], data={'v_' + q['id']: '15', 'u_' + q['id']: '%'})
    st = {x['code']: x['state'] for x in _line(app, sid)['candidates']}
    assert st['XP-I.6484-52-2'] == 'outside'
    c.post('/dual-use/lines/%d/answers' % ln['id'], data={'v_' + q['id']: '20', 'u_' + q['id']: '%'})
    ln2 = _line(app, sid)
    assert {x['code']: x['state'] for x in ln2['candidates']}['XP-I.6484-52-2'] == 'controlled'
    assert ln2['suggested'] == 'hold'
    # the interactive check gives the same answer
    with app.app_context():
        from packs.trade_control import service as S
        d = S.get_index().get('eu_expl_precursors', 'XP-I.6484-52-2')
    j = c.get('/dual-use/api/check?d=%s&n=0&v=15&u=%%25' % d.id).get_json()
    assert j['result'] == 'below' and 'outside this restriction' in j['en']
    assert c.get('/dual-use/api/check?d=%s&n=0&v=45&u=%%25' % d.id).get_json()['result'] == 'above'
    assert c.get('/dual-use/api/check?d=%s&n=0&v=3&u=kg' % d.id).get_json()['result'] == 'unknown'


def test_guidance_is_data_versioned_and_matched(app):
    with app.app_context():
        from database.db import get_db
        from packs.trade_control import guidance as G
        cats = G.categories(force=True)
        by = {c['category']: c for c in cats}
        assert len(cats) >= 13 and 'general' in by
        assert G.match('eu_annex1', '5A002.a', [], {}, cats)['category'] == 'telecom_encryption'
        assert G.match('eu_expl_precursors', 'XP-I.x', [], {'annex': 'I'}, cats)['category'] == \
            'explosives_precursors_fertilisers'
        assert G.match('chemicals', '7719-09-7', [], {'cwc_schedule': 3}, cats)['category'] == 'chemical_precursors'
        assert G.match('chpl', '8542.31', ['854231'], {'tier': '1'}, cats)['category'] == 'electronics_computers'
        assert G.match('eu_annex1', '9Z999', [], {}, cats)['category'] == 'general'
        # clients never read the names of the source lists in the guidance
        v = G.view(by['electronics_computers'], 'en', sources=False)
        text = ' '.join(x if isinstance(x, str) else ' '.join(x) for x in (v[f] for f in G.FIELDS))
        assert not re.search(r'CHPL|ECCN|2021/821|\bEAR\b', text)
        assert 'CHPL' in ' '.join(G.view(by['electronics_computers'], 'en', sources=True)['red_flags'])
        # an edit is a new version; the previous one stays
        db = get_db()
        cur = by['marine']
        data = {'label_en': cur['label_en'], 'label_ar': cur['label_ar'], 'keys': cur['keys'],
                'sources': cur['sources'], 'confidence': cur['confidence'], 'en': dict(cur['en']), 'ar': dict(cur['ar'])}
        data['en']['why_it_matters'] = cur['en']['why_it_matters'] + ' (edited)'
        ver = G.save(db, 'marine', data, None, 'test edit')
        hist = G.history('marine', db)
        assert hist[0]['version'] == ver and hist[0]['origin'] == 'edited' and len(hist) >= 2
        assert G.categories(force=True) and next(c for c in G.categories() if c['category'] == 'marine')['version'] == ver
        # a later seed never overwrites an edited category
        assert G.install(db)['updated'] == 0
        db.rollback()


def test_pages_for_each_role_and_no_list_names_for_clients(app):
    ids = app.du_ids
    c = _client(app, ids['edit'])
    r = c.post('/dual-use/screen', data={'description': 'Router with AES-256 encryption', 'hs_code': '8517.62'})
    sid = int(re.search(r'/screenings/(\d+)', r.headers['Location']).group(1))
    ln = _line(app, sid)
    r = c.post('/dual-use/lines/%d/guidance' % ln['id'], data={'category': 'telecom_encryption', 'asked': ['0', '1'],
                                                              'docs': ['2'], 'flags': ['0'], 'notes': 'Datasheet received'})
    assert r.status_code == 302
    g = _line(app, sid)['guidance']['telecom_encryption']
    assert g['asked'] == [0, 1] and g['docs'] == [2] and g['notes'] == 'Datasheet received'
    pages = ['/dual-use/', '/dual-use/?q=encryption+router', '/dual-use/browse', '/dual-use/browse/5',
             '/dual-use/browse/5?group=A', '/dual-use/browse/chemicals', '/dual-use/browse/precursors',
             '/dual-use/browse/priority', '/dual-use/screenings/%d' % sid]
    for who in ('edit', 'admin', 'itadm'):
        for lang in ('en', 'ar'):
            cl = _client(app, ids[who], lang)
            for u in pages:
                r = cl.get(u)
                assert r.status_code == 200, (who, u)
                body = r.get_data(as_text=True)
                assert not [w for w in CLIENT_LEAK if w in body], (who, u, [w for w in CLIENT_LEAK if w in body])
    body = _client(app, ids['edit']).get('/dual-use/screenings/%d' % sid).get_data(as_text=True)
    assert 'du-guide' in body and 'du-authority' in body and 'Datasheet received' in body
    assert 'Controlled item – international export-control list' in body or 'صنف خاضع للرقابة – قائمة دولية' in body
    landing = _client(app, ids['edit']).get('/dual-use/').get_data(as_text=True)
    assert 'du-hero' in landing and url_ok(landing)
    r = _client(app, ids['edit']).get('/dual-use/screenings/%d/export_memo.pdf' % sid)
    assert r.status_code == 200 and r.mimetype in ('application/pdf', 'text/html')
    assert _client(app, ids['none']).get('/dual-use/browse').status_code == 403
    assert _client(app, ids['view']).post('/dual-use/lines/%d/guidance' % ln['id'],
                                          data={'category': 'telecom_encryption'}).status_code == 403


def test_list_updates_are_for_the_superadmin_only(app, monkeypatch):
    ids = app.du_ids
    for who in ('admin', 'itadm', 'edit'):
        cl = _client(app, ids[who])
        for u in ('/dual-use/admin/lists', '/dual-use/admin/guidance', '/dual-use/admin/guidance/marine'):
            assert cl.get(u).status_code == 403, (who, u)
        assert cl.post('/dual-use/admin/lists/check').status_code == 403
        assert cl.post('/dual-use/admin/lists/upload', data={'list': 'chpl'}).status_code == 403
    from packs.trade_control import service as S
    started = []
    monkeypatch.setattr(S, '_spawn', lambda cmd, cwd: started.append(cmd))
    su = _client(app, ids['super'])
    with app.app_context():
        from database.db import get_db
        get_db().execute("UPDATE dualuse_update_runs SET status = 'failed' WHERE status = 'running'")
        get_db().commit()
    r = su.post('/dual-use/admin/lists/check')
    assert r.status_code == 302 and started and '--run-id' in started[0] and '--apply' in started[0]
    su.post('/dual-use/admin/lists/check')
    assert len(started) == 1                          # never two checks at once
    with app.app_context():
        from database.db import get_db
        get_db().execute("UPDATE dualuse_update_runs SET status = 'failed', finished_at = now() WHERE status = 'running'")
        get_db().commit()
    body = su.get('/dual-use/admin/lists').get_data(as_text=True)
    assert '/dual-use/admin/lists/check' in body and '/dual-use/admin/lists/upload' in body
    r = su.post('/dual-use/admin/lists/upload', data={'list': 'chpl', 'file': (io.BytesIO(b'x' * 600), 'list.html')},
                content_type='multipart/form-data', follow_redirects=True)
    assert 'expected a .pdf file' in r.get_data(as_text=True)
    with app.app_context():
        from database.db import get_db
        run = get_db().execute("SELECT * FROM dualuse_update_runs WHERE mode = 'upload' ORDER BY id DESC LIMIT 1").fetchone()
    assert run is None or run['status'] in ('ok', 'failed', 'blocked')
    with app.app_context():
        from database.db import get_db
        vid = get_db().execute("SELECT max(id) AS m FROM dualuse_list_versions").fetchone()['m']
    assert su.get('/dual-use/admin/versions/%d' % vid).status_code == 200
    assert su.get('/dual-use/admin/guidance/marine').status_code == 200


def test_stale_flag(app, monkeypatch):
    with app.app_context():
        from packs.trade_control import service as S
        monkeypatch.setattr(S, 'STALE_DAYS', 100000)
        assert not any(r['stale'] for r in S.list_overview() if r.get('version_id'))
        monkeypatch.setattr(S, 'STALE_DAYS', -1)
        assert all(r['stale'] for r in S.list_overview() if r['code'] != 'chemicals')


def test_1c997_exclusion_on_the_loaded_list(app):
    """Review r4 M3: the 'except ... dry fertilizers containing less than 15 %' clause is an exclusion."""
    with app.app_context():
        from packs.trade_control import service as S
        d = S.get_index(force=True).get('us_ccl', '1C997')
        an = S.get_index().get('eu_expl_precursors', 'XP-I.6484-52-2')
    if d is None:
        pytest.skip('US list not loaded')
    roles = [p.get('role') for p in d.params]
    assert 'exclusion' in roles, 'reload the lists after migration 20261122_dualuse_param_role'
    n_excl, n_ctrl = roles.index('exclusion'), roles.index('control')
    c = _client(app, app.du_ids['edit'])

    def check(doc, n, v):
        return c.get('/dual-use/api/check?d=%s&n=%d&v=%s&u=%%25' % (doc.id, n, v)).get_json()['result']
    assert check(d, n_excl, 10) == 'excluded' and check(d, n_excl, 20) == 'not_excluded'
    assert check(d, n_ctrl, 10) == 'below' and check(d, n_ctrl, 20) == 'above'
    if an is not None:
        assert [check(an, 0, v) for v in (15, 16, 20)] == ['below', 'below', 'above']
    page = c.get('/dual-use/guide/%s' % d.id).get_data(as_text=True)
    assert 'exclusion' in page.lower() or 'استثناء' in page
