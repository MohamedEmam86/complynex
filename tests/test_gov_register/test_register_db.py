"""Database checks on a DEMO database only (set P8GOV_TEST_DB to its name and
POSTGRES_* to its credentials; skipped otherwise): the sample seed is idempotent
and --remove deletes exactly its rows; quorum / numbering / votes as seeded; the
search engine on the seeded register; every new or changed governance page
renders in English and Arabic; configurable lists can be added, edited and removed."""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
DBNAME = os.environ.get('P8GOV_TEST_DB', '')
pytestmark = pytest.mark.skipif('demo' not in DBNAME, reason='needs P8GOV_TEST_DB=<a demo database>')

SAMPLE_TABLES = ('gov_entities', 'board_members', 'board_committees', 'board_meetings', 'board_decisions', 'gov_officers',
                 'gov_member_capacities', 'gov_resolution_numbers', 'gov_committee_types')


@pytest.fixture(scope='module')
def seed():
    import importlib.util
    spec = importlib.util.spec_from_file_location('seed_board_sample', os.path.join(ROOT, 'scripts', 'seed_board_sample.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def counts(db):
    return {t: db.one(f"SELECT COUNT(*) AS n FROM {t} WHERE is_sample")['n'] for t in SAMPLE_TABLES}


def totals(db):
    return {t: db.one(f"SELECT COUNT(*) AS n FROM {t}")['n'] for t in
            ('board_members', 'board_meetings', 'board_decisions', 'meeting_attendance', 'gov_resolution_votes',
             'committee_memberships', 'meeting_agenda_items', 'gov_member_capacities')}


def test_seed_idempotent_and_remove_exact(seed):
    db = seed.DB(DBNAME)
    seed.remove(db)
    before = totals(db)
    seed.seed(db)
    c1, t1 = counts(db), totals(db)
    assert c1['board_members'] == 7 and c1['board_meetings'] == 7 and c1['board_committees'] == 3
    assert c1['board_decisions'] >= 30 and c1['gov_officers'] == 5
    seed.seed(db)                                     # second run: nothing added
    assert counts(db) == c1 and totals(db) == t1
    seed.remove(db)
    assert all(v == 0 for v in counts(db).values())
    assert totals(db) == before                       # nothing else touched
    seed.seed(db)


def test_seeded_meeting_rules(seed):
    db = seed.DB(DBNAME)
    m3 = db.one("SELECT * FROM board_meetings WHERE is_sample AND meeting_kind = 'EXTRAORDINARY'")
    assert m3['call_no'] == 2 and m3['first_call_present'] == 3 and m3['quorum_met'] == 1 and m3['quorum_required'] == 4
    kinds = {r['meeting_kind'] for r in db.execute("SELECT meeting_kind FROM board_meetings WHERE is_sample").fetchall()}
    assert kinds == {'ORDINARY', 'EXTRAORDINARY', 'CIRCULATION'}
    nums = [r['res_no'] for r in db.execute("SELECT res_no FROM board_decisions WHERE is_sample").fetchall()]
    assert len(nums) == len(set(nums)) and all(re.match(r'^NFC-(BOD|AUD)-20\d\d-\d\d-\d\d$', n) for n in nums)
    rej = db.one("SELECT * FROM board_decisions WHERE is_sample AND outcome = 'REJECTED'")
    assert rej and rej['votes_against'] == 3 and rej['dissent_notes']
    rec = db.one("""SELECT COUNT(*) AS n FROM gov_resolution_votes v JOIN board_decisions d ON d.id = v.resolution_id
                    WHERE d.is_sample AND v.vote = 'RECUSED'""")['n']
    assert rec == 1
    assert db.one("SELECT COUNT(*) AS n FROM meeting_attendance a JOIN board_meetings m ON m.id = a.meeting_id "
                  "WHERE m.is_sample AND a.proxy_holder_member_id IS NOT NULL")['n'] == 1
    outcomes = {r['outcome'] for r in db.execute("SELECT outcome FROM board_decisions WHERE is_sample").fetchall()}
    assert outcomes == {'APPROVED', 'REJECTED', 'DEFERRED', 'GA_RATIFICATION', 'RECOMMENDATION'}
    links = {r['link_type'] for r in db.execute("""SELECT l.link_type FROM gov_resolution_links l JOIN board_decisions d
              ON d.id = l.from_resolution_id WHERE d.is_sample""").fetchall()}
    assert {'AMENDS', 'SUPERSEDES', 'REVOKES', 'RATIFIES'} <= links


def test_search_on_seeded_register(seed):
    from governance import resolution_search as S
    db = seed.DB(DBNAME)
    c = S.corpus(db)
    title = {r['id']: r['decision_title'] for r in db.execute("SELECT id, decision_title FROM board_decisions").fetchall()}

    def first(q):
        r = S.rank(c, q)
        return title[r[0][0]] if r else ''
    assert 'مراقب' in first('تعيين مراقب حسابات')
    assert 'تمويل' in first('قرض') or 'التسهيل' in first('قرض')
    assert 'غسل الأموال' in first('سياسة غسل الاموال')
    assert 'الموازنة' in first('approve budget') or 'budget' in first('approve budget').lower()
    sample = {r['id'] for r in db.execute("SELECT id FROM board_decisions WHERE is_sample").fetchall()}
    top = [title[rid] for rid, _s, _m in S.rank(c, 'approve budget', ids=sample)][:1]
    assert top and 'الموازنة' in top[0]                     # cross-script: English query, Arabic title
    assert 'مراقب' in first('مراقب حسبات')
    assert 'طرف ذي علاقة' in first('related party lease')


@pytest.fixture(scope='module')
def client():
    from app import create_app
    from models.user import User
    from database.db import get_db
    app = create_app()
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        uid = get_db().execute("SELECT id FROM users WHERE role = 'admin' AND is_active = 1 ORDER BY id LIMIT 1").fetchone()['id']
        c = app.test_client()
        with c.session_transaction() as s:
            s['_user_id'] = User.session_id_for_app(app, uid)
            s['_fresh'] = True
        yield app, c


def _pages(seed):
    db = seed.DB(DBNAME)
    ent = db.one("SELECT id FROM gov_entities WHERE is_sample")['id']
    meetings = [r['id'] for r in db.execute("SELECT id FROM board_meetings WHERE is_sample ORDER BY id").fetchall()]
    members = [r['id'] for r in db.execute("SELECT id FROM board_members WHERE is_sample ORDER BY id").fetchall()]
    res = [r['id'] for r in db.execute("SELECT id FROM board_decisions WHERE is_sample ORDER BY id LIMIT 6").fetchall()]
    com = db.one("SELECT id FROM board_committees WHERE is_sample ORDER BY id LIMIT 1")['id']
    sec = db.one("SELECT id FROM gov_officers WHERE is_sample ORDER BY id LIMIT 1")['id']
    urls = ['/governance/', f'/governance/?entity={ent}', '/governance/register', '/governance/register?q=%D9%82%D8%B1%D8%B6',
            f'/governance/register?q=approve+budget&entity={ent}&body=BOARD', '/governance/register?q=xx&kind=CIRCULATION',
            f'/governance/register?member={members[0]}&outcome=APPROVED&date_from=2025-01-01&date_to=2026-12-31',
            '/governance/register/meetings', f'/governance/register/meetings?entity={ent}',
            '/governance/register/secretaries', f'/governance/register/secretaries?officer={sec}',
            f'/governance/register/reports/attendance?entity={ent}&year=2025', '/governance/register/reports/attendance',
            f'/governance/register/reports/board-list?entity={ent}', '/governance/register/reports/follow-up?show=all',
            '/governance/register/reports/follow-up?show=overdue', '/governance/settings', '/governance/composition',
            '/governance/committees', '/governance/committee/add', f'/governance/committee/edit/{com}', '/governance/meetings',
            f'/governance/members/view/{members[0]}']
    from governance.config_lists import LISTS
    urls += [f'/governance/settings/{k}' for k in LISTS]
    urls += [f'/governance/register/meeting/{m}' for m in meetings]
    urls += [f'/governance/meeting/summary/{meetings[0]}', f'/governance/meeting/{meetings[0]}/attendance']
    urls += [f'/governance/register/member/{m}' for m in members]
    urls += [f'/governance/register/resolution/{r}' for r in res]
    return urls


@pytest.mark.parametrize('lang', ['en', 'ar'])
def test_pages_render(seed, client, lang):
    app, c = client
    with c.session_transaction() as s:
        s['lang'] = lang
    bad = []
    for u in _pages(seed):
        rv = c.get(u)
        h = rv.get_data(as_text=True)
        if rv.status_code != 200 or 'Traceback' in h:
            bad.append((u, rv.status_code))
        elif lang == 'ar' and 'dir="rtl"' not in h:
            bad.append((u, 'not rtl'))
        if re.search(r'<script(?![^>]*nonce=)', re.sub(r'(?is)<script[^>]*src=[^>]*>', '', h)):
            bad.append((u, 'script without nonce'))
    assert bad == []


def test_record_page_shows_quorum_and_people(seed, client):
    app, c = client
    db = seed.DB(DBNAME)
    m3 = db.one("SELECT id FROM board_meetings WHERE is_sample AND meeting_kind = 'EXTRAORDINARY'")['id']
    with c.session_transaction() as s:
        s['lang'] = 'en'
    h = c.get(f'/governance/register/meeting/{m3}').get_data(as_text=True)
    assert 'Quorum present' in h and 'First call' in h and 'Ahmed Samir Lotfy' in h and 'Mahmoud Reda Hassan' in h
    h = c.get('/governance/register?q=' + 'تعيين مراقب حسابات').get_data(as_text=True)
    assert '<mark>' in h and 'NFC-BOD-' in h and '%' in h


def test_config_list_roundtrip(seed, client):
    app, c = client
    db = seed.DB(DBNAME)
    rv = c.post('/governance/settings/synonyms/add', data={'group_code': 'test grp', 'term': 'zz-test-term', 'is_active': '1'})
    assert rv.status_code == 302
    row = db.one("SELECT * FROM gov_search_synonyms WHERE term = 'zz-test-term'")
    assert row and row['group_code'] == 'TEST_GRP'
    c.post(f"/governance/settings/synonyms/{row['id']}/update", data={'group_code': 'TEST_GRP', 'term': 'zz-test-term2', 'is_active': '1'})
    db.commit()
    assert db.one("SELECT term FROM gov_search_synonyms WHERE id = %s", (row['id'],))['term'] == 'zz-test-term2'
    c.post(f"/governance/settings/synonyms/{row['id']}/delete")
    db.commit()
    assert not db.one("SELECT 1 AS x FROM gov_search_synonyms WHERE id = %s", (row['id'],))
    # a capacity in use is deactivated, not deleted
    opt = db.one("""SELECT o.id FROM gov_capacity_options o JOIN gov_member_capacities mc ON mc.option_id = o.id LIMIT 1""")['id']
    c.post(f'/governance/settings/capacity-options/{opt}/delete')
    db.commit()
    assert db.one("SELECT is_active FROM gov_capacity_options WHERE id = %s", (opt,))['is_active'] is False
    db.execute("UPDATE gov_capacity_options SET is_active = TRUE WHERE id = %s", (opt,))
    db.commit()
    # a committee with any name and a new type typed on the form
    rv = c.post('/governance/committee/add', data={'committee_name': 'ZZ Test Sustainability Panel', 'committee_type': '',
                                                   'new_type_name_en': 'ZZ Sustainability panel', 'min_members': '4'})
    assert rv.status_code == 302
    cm = db.one("SELECT * FROM board_committees WHERE committee_name = 'ZZ Test Sustainability Panel'")
    assert cm and cm['committee_type'] == 'ZZ_SUSTAINABILITY_PANEL' and cm['min_members'] == 4
    db.execute("DELETE FROM board_committees WHERE id = %s", (cm['id'],))
    db.execute("DELETE FROM gov_committee_types WHERE code = 'ZZ_SUSTAINABILITY_PANEL'")
    db.commit()


def test_record_flow_on_a_new_meeting(seed, client):
    """New meeting -> attendance -> conflict -> resolution with votes -> sign; then cleaned up."""
    app, c = client
    db = seed.DB(DBNAME)
    ent = db.one("SELECT id FROM gov_entities WHERE is_sample")['id']
    c.post('/governance/register/meetings/new', data={'entity_id': ent, 'body': 'BOARD', 'meeting_kind': 'ORDINARY',
                                                      'meeting_date': '2026-10-01', 'mode': 'IN_PERSON'})
    db.commit()
    m = db.one("SELECT * FROM board_meetings WHERE entity_id = %s AND meeting_date = '2026-10-01'", (ent,))
    assert m and m['sequence_no'] == 3                            # 2026: circulation #1, April #2
    rows = db.execute("SELECT member_id FROM meeting_attendance WHERE meeting_id = %s ORDER BY member_id", (m['id'],)).fetchall()
    assert len(rows) == 7
    ids = [r['member_id'] for r in rows]
    form = {f'att_{i}': 'IN_PERSON' for i in ids[:3]}
    form.update({f'att_{i}': 'ABSENT_EXCUSED' for i in ids[3:]})
    c.post(f"/governance/register/meeting/{m['id']}/attendance", data=form)
    db.commit()
    assert db.one("SELECT quorum_met FROM board_meetings WHERE id = %s", (m['id'],))['quorum_met'] == 0
    rv = c.post(f"/governance/register/meeting/{m['id']}/resolutions", data={'decision_title': 'ZZ test', 'decision_text': 'x'})
    db.commit()
    assert not db.one("SELECT 1 AS x FROM board_decisions WHERE meeting_id = %s", (m['id'],))      # no quorum: refused
    form.update({f'att_{ids[3]}': 'PROXY', f'holder_{ids[3]}': ids[0], f'att_{ids[4]}': 'REMOTE'})
    c.post(f"/governance/register/meeting/{m['id']}/attendance", data=form)
    db.commit()
    assert db.one("SELECT quorum_met FROM board_meetings WHERE id = %s", (m['id'],))['quorum_met'] == 1
    c.post(f"/governance/register/meeting/{m['id']}/agenda", data={'item_title': 'ZZ lease from a related company'})
    db.commit()
    ai = db.one("SELECT id FROM meeting_agenda_items WHERE meeting_id = %s", (m['id'],))['id']
    c.post(f"/governance/register/meeting/{m['id']}/conflicts", data={'member_id': ids[1], 'agenda_item_id': ai, 'nature': 'ZZ interest'})
    votes = {f'vote_{i}': 'FOR' for i in ids}
    votes[f'vote_{ids[2]}'] = 'AGAINST'
    votes[f'dissent_{ids[2]}'] = 'ZZ reason'
    c.post(f"/governance/register/meeting/{m['id']}/resolutions",
           data=dict(votes, agenda_item_id=ai, decision_title='ZZ lease', decision_text='ZZ lease text', category_code='RELATED_PARTY'))
    db.commit()
    d = db.one("SELECT * FROM board_decisions WHERE meeting_id = %s", (m['id'],))
    assert d['res_no'] == 'NFC-BOD-2026-03-01' and d['outcome'] == 'APPROVED'
    v = {r['member_id']: r['vote'] for r in db.execute("SELECT * FROM gov_resolution_votes WHERE resolution_id = %s", (d['id'],)).fetchall()}
    assert v[ids[1]] == 'RECUSED' and v[ids[2]] == 'AGAINST' and v[ids[5]] == 'ABSENT'
    c.post(f"/governance/register/meeting/{m['id']}/minutes-state", data={'action': 'sign_chair', 'name': 'X'})
    db.commit()
    assert db.one("SELECT chair_signed_at FROM board_meetings WHERE id = %s", (m['id'],))['chair_signed_at'] is None   # not approved yet
    for a in ({'action': 'approve'}, {'action': 'sign_chair', 'name': 'X'}, {'action': 'sign_secretary', 'name': 'Y'}):
        c.post(f"/governance/register/meeting/{m['id']}/minutes-state", data=a)
    db.commit()
    assert db.one("SELECT minutes_state FROM board_meetings WHERE id = %s", (m['id'],))['minutes_state'] == 'SIGNED'
    rv = c.post(f"/governance/register/meeting/{m['id']}/resolutions", data={'decision_title': 'ZZ after signing', 'decision_text': 'x'})
    db.commit()
    assert db.one("SELECT COUNT(*) AS n FROM board_decisions WHERE meeting_id = %s", (m['id'],))['n'] == 1          # locked
    # the number stays issued: cleaning up through --reset removes this meeting with the sample board
    seed.remove(db)
    assert not db.one("SELECT 1 AS x FROM board_meetings WHERE id = %s", (m['id'],))
    seed.seed(db)
