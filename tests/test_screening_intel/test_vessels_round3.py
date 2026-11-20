"""Vessel screening round 3: provenance classes (only sanctions and bans alert), generic regimes, the
verdict and data-driven next steps, ship news relevance (no network), the Vessels Database permission and
the change log. DB-backed tests run only with VESSELS_TEST_DB=<scratch database> (skipped otherwise)."""
import os
from types import SimpleNamespace

import pytest

from screening import vessel_engine as VE
from screening import vessel_guidance as VG
from screening import vessel_news as VN
from screening import vessel_provenance as VP
from screening import vessel_regimes as VR
from screening import vessel_utils as VU


# --------------------------------------------------------------------------- provenance
def test_official_list_is_always_sanction():
    assert VP.classify('ofac', [], [])['class'] == VP.SANCTION
    assert VP.classify('hmt', ['whatever'], [])['class'] == VP.SANCTION


def test_aggregated_classes():
    assert VP.classify('opensanctions', ['tokyo_mou_detention'], [])['class'] == VP.RISK
    assert VP.classify('opensanctions', ['ext_tokyo_mou_psc', 'black_sea_mou_detention'], [])['class'] == VP.RISK
    assert VP.classify('opensanctions', ['us_ofac_sdn', 'tokyo_mou_detention'], [])['class'] == VP.SANCTION
    assert VP.classify('opensanctions', ['paris_mou_banned'], [])['class'] == VP.BAN
    assert VP.classify('opensanctions', ['us_sam_exclusions'], [])['class'] == VP.BAN
    assert VP.classify('opensanctions', ['kp_rusi_reports'], [])['class'] == VP.INTEL


def test_topics_never_upgrade_a_ban_and_unknown_is_risk():
    assert VP.classify('opensanctions', ['paris_mou_banned'], ['sanction'])['class'] == VP.BAN
    r = VP.classify('opensanctions', ['some_new_dataset_xyz'], [])
    assert r['class'] == VP.RISK and r['unclassified'] == ['some_new_dataset_xyz']


def test_only_sanctions_and_bans_alert():
    assert VP.alerts(VP.SANCTION) and VP.alerts(VP.BAN)
    assert not VP.alerts(VP.RISK) and not VP.alerts(VP.INTEL)


def _c(wid, name, imo=None, prov=VP.SANCTION, **kw):
    d = dict(watchlist_id=wid, group_key=('IMO:' + imo) if imo else 'WL:%d' % wid, source=kw.pop('source', 'opensanctions'),
             parties=[], risk_score=0, list_type='SANCTIONS', name=name, names=[name], previous_names=[], imo=imo,
             mmsi=None, call_sign=None, flag=None, flags_past=[], type=None, year_built=None, measures=[], owners=[],
             gross_tonnage=None, legal_status=None, provenance=prov, datasets=[], risk_datasets=kw.pop('risk_ds', []),
             regimes=kw.pop('regimes', []))
    return d


def _run(cands, **kw):
    idx = {}
    for c in cands:
        if c['imo']:
            idx.setdefault(('IMO', c['imo']), []).append((c['watchlist_id'], True))
    VE._PF.clear()
    return VE.screen_vessel(candidates=cands, id_index=idx, flags={}, links={}, whitelist={}, **kw)


def test_detention_only_ship_is_no_hit_but_a_risk_line():
    cands = [_c(1, 'HARBOUR QUEEN', '9074729', prov=VP.RISK, risk_ds=['tokyo_mou_detention'])]
    r = _run(cands, imo='9074729')
    assert not r['hits'] and not r.get('ban_hits')
    assert any(x.get('code') == 'r_psc' for x in (r.get('risk') or {}).get('lines') or [])
    assert VE.decision(r)[0] != 'match'


def test_ban_only_goes_to_review_never_confirmed():
    cands = [_c(1, 'HARBOUR QUEEN', '9074729', prov=VP.BAN)]
    r = _run(cands, imo='9074729')
    assert r.get('ban_hits') and not r['hits']
    assert r['tier'] not in ('CONFIRMED', 'POTENTIAL')
    assert VE.decision(r)[0] == 'review'
    assert VG.verdict(r)['code'] == 'ban'


def test_sanctioned_ship_carries_regimes_and_provenance():
    cands = [_c(1, 'HARBOUR QUEEN', '9074729', regimes=['RUSSIA'])]
    r = _run(cands, imo='9074729')
    h = r['hits'][0]
    assert h['tier'] == 'CONFIRMED' and h['provenance'] == VP.SANCTION and h['regimes'] == ['RUSSIA']
    v = VG.verdict(r, 'ar')
    assert v['code'] == 'confirmed' and v['level'] == 'danger' and v['text']


# --------------------------------------------------------------------------- regimes
def test_regimes_are_generic_never_the_authority():
    assert VR.regimes_of(['RUSSIA-EO14024']) == ['RUSSIA']
    assert VR.regimes_of('The Russia (Sanctions) (EU Exit) Regulations 2019') == ['RUSSIA']
    assert VR.regimes_of(['IRAN', 'SDGT']) == ['IRAN', 'TERRORISM']
    assert VR.regimes_of('UN-SC1718') == ['DPRK']
    assert VR.regimes_of('CA-SEMA') == [] and VR.regimes_of('') == []
    assert VR.regimes_of([], topics=['crime.terror']) == ['TERRORISM']
    for code in VR.REGIMES:
        en, ar = VR.label(code), VR.label(code, 'ar')
        assert en and ar and en != ar
        for authority in ('OFAC', 'UK', 'EU', 'UN ', 'HMT', 'Treasury'):
            assert authority not in en


# --------------------------------------------------------------------------- guidance
def test_next_steps_data_driven_and_bilingual():
    res = {'tier': 'LOW', 'hits': [{'tier': 'LOW'}], 'owner_hits': [], 'ban_hits': [],
           'risk': {'lines': [{'code': 'r_psc'}]}}
    assert VG.situations(res) == ['name_only', 'risk']
    en, ar = VG.next_steps(res, 'en'), VG.next_steps(res, 'ar')
    assert [s['code'] for s in en] == ['name_only', 'risk'] and all(s['steps'] for s in en)
    assert en[0]['title'] != ar[0]['title']
    assert VG.verdict(res)['code'] == 'possible'
    clear = {'tier': 'CLEAR', 'hits': [], 'owner_hits': [], 'ban_hits': [], 'risk': {}}
    assert VG.situations(clear) == ['clear'] and VG.verdict(clear)['level'] == 'success'
    assert 'hull_number' in VG.situations(dict(clear, related_hulls=[{'name': 'DREAM 1'}]))


# --------------------------------------------------------------------------- news
def test_news_relevance_rules():
    imo = {'title': 'Tanker seized', 'description': 'The ship (IMO 9074729) was boarded.'}
    assert VN.relevant(imo, name='X', imo='9074729')['why'] == 'imo'
    assert VN.relevant({'title': 'IMO 90747290 rules'}, imo='9074729') is None
    two = {'title': 'Eagle S tanker held after cable damage'}
    assert VN.relevant(two, name='EAGLE S')['why'] == 'name'
    assert VN.relevant({'title': 'Eagle S wins award'}, name='EAGLE S') is None          # no maritime context
    one_far = {'title': 'Attica region fires', 'description': 'A ship was spotted at the port later in the week.'}
    assert VN.relevant(one_far, name='ATTICA') is None                                   # ship word not next to it
    assert VN.relevant({'title': 'The tanker Attica was detained'}, name='ATTICA')['why'] == 'name'


def test_news_for_filters_dedups_and_degrades():
    arts = [{'title': 'Tanker Attica detained at port', 'url': 'https://example.test/a', 'source': 'S'},
            {'title': 'Tanker Attica detained at port', 'url': 'https://example.test/a', 'source': 'S'},
            {'title': 'Attica holidays', 'url': 'javascript:alert(1)'}]
    out = VN.news_for(None, name='ATTICA', search=lambda q: (arts, ['google_news'], []))
    assert len(out['items']) == 1 and out['items'][0]['url'] == 'https://example.test/a' and not out['error']

    def boom(q):
        raise RuntimeError('offline')
    out = VN.news_for(None, name='ATTICA', search=boom)
    assert out['items'] == [] and out['error'] == 'unavailable'


# --------------------------------------------------------------------------- permission
def test_vessels_database_permission(monkeypatch):
    from screening import vessel_routes as R
    for role, perm, ok in (('superadmin', 'none', True), ('admin', 'none', False), ('compliance_officer', 'view', True),
                           ('compliance_officer', 'none', False), ('compliance_officer', None, False)):
        assert R.can_db(SimpleNamespace(is_authenticated=True, role=role, perm_vessels_db=perm)) is ok, (role, perm)


def test_user_model_loads_and_saves_the_permission():
    import inspect
    from models import user as U
    assert 'perm_vessels_db' in inspect.getsource(U.User._from_row)
    assert 'perm_vessels_db' in inspect.getsource(U.User.create_user)


def test_hull_numbers_and_typos():
    cands = [_c(1, 'DREAM 1', '9074729'), _c(2, 'DREAM 2', '9387425'), _c(3, 'GOLDEN HORIZON', '9191553')]
    r = _run(cands, name='DREAM')
    assert not r['hits'] and {x['name'] for x in r['related_hulls']} == {'DREAM 1', 'DREAM 2'}
    r = _run(cands, name='GOLDEN HORIZPN')
    assert r['hits'] and r['hits'][0]['name'] == 'GOLDEN HORIZON' and r['hits'][0]['tier'] != 'CONFIRMED'
    assert VU.imo_valid('9074729')


# --------------------------------------------------------------------------- DB
DBNAME = os.environ.get('VESSELS_TEST_DB', '')
needs_db = pytest.mark.skipif(not DBNAME, reason='needs VESSELS_TEST_DB=<scratch database with real lists>')


@pytest.fixture(scope='module')
def conn():
    import psycopg2
    import psycopg2.extras
    from config import Config
    cfg = dict(Config.POSTGRES_CONFIG, dbname=DBNAME)
    cfg.pop('database', None)
    c = psycopg2.connect(**cfg, cursor_factory=psycopg2.extras.RealDictCursor)
    yield c
    c.close()


@needs_db
def test_db_sync_logs_a_run_and_stamps_the_version(conn):
    from screening import vessel_store as VS
    before = VS.data_stamp(conn)
    s = VS.sync(conn, trigger='manual')
    assert set(s['by_class']) <= {VP.SANCTION, VP.BAN, VP.RISK, VP.INTEL}
    assert {'added', 'removed', 'changed'} <= set(s)
    with conn.cursor() as cur:
        cur.execute("SELECT trigger, status FROM vessel_update_runs ORDER BY id DESC LIMIT 1")
        run = cur.fetchone()
    assert run['trigger'] == 'manual' and run['status'] in ('ok', 'done', 'success')
    assert VS.data_stamp(conn) != before or before is None


@needs_db
def test_db_no_detention_only_ship_alerts(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT imo FROM vessel_profile WHERE provenance = 'RISK' AND imo IS NOT NULL
                       AND imo NOT IN (SELECT imo FROM vessel_profile WHERE provenance IN ('SANCTION', 'BAN')
                                       AND imo IS NOT NULL) LIMIT 3""")
        rows = cur.fetchall()
    for r in rows:
        res = VE.screen_vessel(conn=conn, imo=r['imo'], whitelist={})
        assert not res['hits'] and not res.get('ban_hits'), r['imo']
