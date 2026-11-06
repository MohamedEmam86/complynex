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
    h = c.get('/governance/register?sample=1&q=' + 'تعيين مراقب حسابات').get_data(as_text=True)
    assert '<mark>' in h and 'NFC-BOD-' in h and '%' in h
    h = c.get('/governance/register?q=' + 'تعيين مراقب حسابات').get_data(as_text=True)
    assert 'NFC-BOD-' not in h                                      # sample records only when asked for


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
    c.post(f"/governance/register/meeting/{m['id']}/attendance", data=form)       # proxy without its document: refused
    db.commit()
    assert db.one("SELECT quorum_met FROM board_meetings WHERE id = %s", (m['id'],))['quorum_met'] == 0
    form[f'proxydoc_{ids[3]}'] = 'Written proxy dated 2026-09-28'
    c.post(f"/governance/register/meeting/{m['id']}/attendance", data=form)
    db.commit()
    assert db.one("SELECT quorum_met FROM board_meetings WHERE id = %s", (m['id'],))['quorum_met'] == 1
    assert db.one("SELECT rule_snapshot FROM board_meetings WHERE id = %s", (m['id'],))['rule_snapshot']['quorum_min'] == 3
    c.post(f"/governance/register/meeting/{m['id']}/agenda", data={'item_title': 'ZZ lease from a related company'})
    db.commit()
    ai = db.one("SELECT id FROM meeting_agenda_items WHERE meeting_id = %s", (m['id'],))['id']
    c.post(f"/governance/register/meeting/{m['id']}/conflicts", data={'member_id': ids[1], 'agenda_item_id': ai, 'nature': 'ZZ interest'})
    votes = {f'vote_{i}': 'FOR' for i in ids}
    votes[f'vote_{ids[2]}'] = 'AGAINST'
    votes[f'dissent_{ids[2]}'] = 'ZZ reason'
    data = dict(votes, agenda_item_id=ai, decision_title='ZZ lease', decision_text='ZZ lease text', category_code='RELATED_PARTY')
    c.post(f"/governance/register/meeting/{m['id']}/resolutions", data=dict(data, **{f'vote_{ids[4]}': ''}))
    db.commit()
    assert not db.one("SELECT 1 AS x FROM board_decisions WHERE meeting_id = %s", (m['id'],))   # a present member without a vote
    c.post(f"/governance/register/meeting/{m['id']}/resolutions", data=data)
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
    rv = c.post(f"/governance/register/meeting/{m['id']}/resolutions", data=dict(data, decision_title='ZZ after signing'))
    db.commit()
    assert db.one("SELECT COUNT(*) AS n FROM board_decisions WHERE meeting_id = %s", (m['id'],))['n'] == 1          # locked
    # every write route refuses a signed record (and nothing is signed twice)
    before = db.one("SELECT * FROM board_meetings WHERE id = %s", (m['id'],))
    mid = m['id']
    c.post(f"/governance/register/meeting/{mid}/formalities", data={'meeting_date': '2026-10-02', 'location': 'ZZ moved'})
    c.post(f"/governance/register/meeting/{mid}/attendance", data={f'att_{ids[0]}': 'ABSENT_UNEXCUSED'})
    c.post(f"/governance/register/meeting/{mid}/attendance", data={'add_member_id': ids[0]})
    c.post(f"/governance/register/meeting/{mid}/agenda", data={'item_title': 'ZZ late item'})
    c.post(f"/governance/register/meeting/{mid}/agenda/{ai}/objection", data={'objection_note': 'ZZ'})
    c.post(f"/governance/register/meeting/{mid}/conflicts", data={'member_id': ids[0], 'agenda_item_id': ai, 'nature': 'ZZ late'})
    c.post(f"/governance/register/meeting/{mid}/tellers", data={'name': 'ZZ teller'})
    c.post(f"/governance/register/meeting/{mid}/minutes-state", data={'action': 'sign_chair', 'name': 'Somebody else'})
    c.post(f"/governance/register/meeting/{mid}/minutes-state", data={'action': 'approve'})
    c.post(f"/governance/register/resolution/{d['id']}/update", data=dict(data, reason='ZZ'))
    c.post(f"/governance/meeting/{mid}/resolutions/{d['id']}/edit", data={'decision_text': 'ZZ legacy', 'reason': 'x'})
    c.post(f"/governance/meeting/{mid}/attendance", data={f'member_id_{ids[0]}': ids[0]})
    c.post(f"/governance/meeting/{mid}/minutes/save", data={'body': 'ZZ new minutes'})
    db.commit()
    after = db.one("SELECT * FROM board_meetings WHERE id = %s", (mid,))
    assert (after['meeting_date'], after['location'], after['chair_signed_name'], after['chair_signed_at']) == \
        (before['meeting_date'], before['location'], before['chair_signed_name'], before['chair_signed_at'])
    assert db.one("SELECT attended FROM meeting_attendance WHERE meeting_id = %s AND member_id = %s", (mid, ids[0]))['attended'] == 1
    assert db.one("SELECT COUNT(*) AS n FROM meeting_agenda_items WHERE meeting_id = %s", (mid,))['n'] == 1
    assert db.one("SELECT COUNT(*) AS n FROM gov_conflict_declarations WHERE meeting_id = %s", (mid,))['n'] == 1
    assert db.one("SELECT COUNT(*) AS n FROM gov_meeting_officers WHERE meeting_id = %s", (mid,))['n'] == 0
    assert db.one("SELECT COUNT(*) AS n FROM meeting_minutes WHERE meeting_id = %s", (mid,))['n'] == 0
    assert db.one("SELECT decision_text FROM board_decisions WHERE id = %s", (d['id'],))['decision_text'] == 'ZZ lease text'
    c.post(f"/governance/register/meeting/{mid}/minutes-state", data={'action': 'filed', 'filed_on': '2026-10-05'})
    db.commit()
    assert str(db.one("SELECT filed_on FROM board_meetings WHERE id = %s", (mid,))['filed_on']) == '2026-10-05'   # filing still possible
    # the number stays issued: cleaning up through --reset removes this meeting with the sample board
    seed.remove(db)
    assert not db.one("SELECT 1 AS x FROM board_meetings WHERE id = %s", (m['id'],))
    seed.seed(db)


def test_rule_snapshot_and_frozen_rule(seed, client):
    app, c = client
    db = seed.DB(DBNAME)
    m3 = db.one("SELECT * FROM board_meetings WHERE is_sample AND meeting_kind = 'EXTRAORDINARY'")
    rule = db.one("SELECT * FROM gov_meeting_rules WHERE id = %s", (m3['meeting_rule_id'],))
    form = {k: ('1' if v is True else ('' if v in (None, False) else str(v))) for k, v in rule.items()
            if k in ('name_en', 'name_ar', 'applies_to', 'quorum_basis', 'quorum_type', 'quorum_fraction', 'majority_rule',
                     'count_proxies', 'count_remote', 'chair_casting_vote', 'circulation_requires_all', 'is_active',
                     'sort_order', 'legal_ref', 'filing_days', 'filing_authority', 'notice_days', 'quorum_min')}
    c.post(f"/governance/settings/meeting-rules/{rule['id']}/update", data=dict(form, quorum_min='6', name_en=rule['name_en'] + ' ZZ'))
    db.commit()
    r2 = db.one("SELECT * FROM gov_meeting_rules WHERE id = %s", (rule['id'],))
    assert r2['quorum_min'] == rule['quorum_min'] and r2['name_en'].endswith(' ZZ')       # in use: values kept, name changed
    db.execute("UPDATE gov_meeting_rules SET name_en = %s, quorum_min = 7 WHERE id = %s", (rule['name_en'], rule['id']))
    db.commit()
    with c.session_transaction() as s:
        s['lang'] = 'en'
    h = c.get(f"/governance/register/meeting/{m3['id']}").get_data(as_text=True)
    assert 'needed 4' in h and 'Quorum present' in h                                       # the meeting keeps its own values
    db.execute("UPDATE gov_meeting_rules SET quorum_min = %s WHERE id = %s", (rule['quorum_min'], rule['id']))
    db.commit()


def test_circulation_freeze_and_sequence(seed, client):
    app, c = client
    db = seed.DB(DBNAME)
    m5 = db.one("SELECT * FROM board_meetings WHERE is_sample AND meeting_kind = 'CIRCULATION'")
    h = c.get(f"/governance/register/meeting/{m5['id']}").get_data(as_text=True)
    assert 'Resolutions by circulation' in h
    m6 = db.one("SELECT * FROM board_meetings WHERE is_sample AND meeting_date = '2026-04-21'")
    db.execute("UPDATE board_meetings SET secretary_signed_at = NULL, minutes_state = 'APPROVED' WHERE id = %s", (m6['id'],))
    db.commit()
    c.post(f"/governance/register/meeting/{m6['id']}/formalities", data={'meeting_date': '2026-05-01', 'sequence_no': '2'})
    db.commit()
    assert db.one("SELECT meeting_date FROM board_meetings WHERE id = %s", (m6['id'],))['meeting_date'] == '2026-04-21'
    seqs = [r['sequence_no'] for r in db.execute("""SELECT sequence_no FROM board_meetings WHERE is_sample AND committee_id IS NULL
               AND left(meeting_date, 4) = '2025'""").fetchall()]
    assert sorted(seqs) == [1, 2, 3, 4]
    import psycopg2
    with pytest.raises(psycopg2.Error):
        db.execute("UPDATE board_meetings SET sequence_no = 1 WHERE is_sample AND meeting_date = '2025-06-24'")
    db.rollback()


def test_default_board_and_short_code(seed, client):
    app, c = client
    db = seed.DB(DBNAME)
    d = db.one("SELECT id FROM gov_entities WHERE is_default")['id']
    c.post(f'/governance/settings/entities/{d}/delete')
    db.commit()
    assert db.one("SELECT is_active FROM gov_entities WHERE id = %s", (d,))['is_active'] is True
    c.post('/governance/settings/entities/add', data={'name_en': 'ZZ board without code', 'is_active': '1'})
    db.commit()
    assert not db.one("SELECT 1 AS x FROM gov_entities WHERE name_en = 'ZZ board without code'")


def test_search_version_and_query_cap(seed):
    from governance import resolution_search as S
    db = seed.DB(DBNAME)
    v0 = db.one("SELECT version FROM gov_search_state WHERE id = 1")['version']
    db.execute("INSERT INTO gov_search_synonyms (group_code, term) VALUES ('ZZTEST', 'zzword')")
    db.commit()
    assert db.one("SELECT version FROM gov_search_state WHERE id = 1")['version'] > v0
    db.execute("DELETE FROM gov_search_synonyms WHERE group_code = 'ZZTEST'")
    r = db.one("SELECT id, agenda_item_id FROM board_decisions WHERE is_sample AND agenda_item_id IS NOT NULL LIMIT 1")
    db.execute("UPDATE meeting_agenda_items SET item_title = item_title WHERE id = %s", (r['agenda_item_id'],))
    db.execute("UPDATE meeting_agenda_items SET item_title = item_title || ' ' WHERE id = %s", (r['agenda_item_id'],))
    db.commit()
    assert db.one("SELECT search_version FROM board_decisions WHERE id = %s", (r['id'],))['search_version'] == 0
    db.execute("UPDATE meeting_agenda_items SET item_title = rtrim(item_title) WHERE id = %s", (r['agenda_item_id'],))
    db.commit()
    c = S.corpus(db)
    assert len(c.concepts(' '.join(f'word{i}' for i in range(30)))) <= S.MAX_QUERY_WORDS


def test_remove_refuses_real_rows_linked_to_sample(seed):
    db = seed.DB(DBNAME)
    mem = db.one("SELECT id FROM board_members WHERE is_sample LIMIT 1")['id']
    opt = db.one("SELECT id FROM gov_capacity_options WHERE code = 'EXPERT'")['id']
    cid = db.ins('gov_member_capacities', member_id=mem, option_id=opt, is_sample=False)
    db.commit()
    with pytest.raises(seed.LinkedRows):
        seed.remove(db)
    db.rollback()
    assert db.one("SELECT COUNT(*) AS n FROM board_members WHERE is_sample")['n'] == 7       # nothing deleted
    db.execute("DELETE FROM gov_member_capacities WHERE id = %s", (cid,))
    db.commit()
    counts = seed.remove(db, dry_run=True)
    assert counts['members'] == 7 and db.one("SELECT COUNT(*) AS n FROM board_members WHERE is_sample")['n'] == 7
