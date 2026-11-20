"""Vessel screening round 4: renamed ships (identifier confirms, name differs), names known before the lists
publish them, word counterparts in multi-word names, IMO conflicts with former names / port-inspection IMOs,
generic one-word names of banned ships, update status and schedule. DB-backed tests run only with
VESSELS_TEST_DB=<scratch database> (skipped otherwise)."""
import os
from datetime import datetime

import pytest

from screening import vessel_engine as VE
from screening import vessel_guidance as VG
from screening import vessel_provenance as VP
from screening import vessel_store as VS


def _c(wid, name, imo=None, prov=VP.SANCTION, **kw):
    names = [name] + kw.pop('alt', [])
    return dict(watchlist_id=wid, group_key=('IMO:' + imo) if imo else 'WL:%d' % wid, source='ofac', parties=[],
                risk_score=0, list_type='SANCTIONS', name=name, names=names, previous_names=kw.pop('prev', []),
                imo=imo, mmsi=None, call_sign=None, flag=None, flags_past=[], type=None, year_built=None, measures=[],
                owners=[], gross_tonnage=None, legal_status=None, provenance=prov, datasets=[], risk_datasets=[],
                regimes=[])


def _run(cands, **kw):
    idx = {}
    for c in cands:
        if c['imo']:
            idx.setdefault(('IMO', c['imo']), []).append((c['watchlist_id'], True))
    VE._PF.clear()
    return VE.screen_vessel(candidates=cands, id_index=idx, flags={}, links={}, whitelist={}, **kw)


def codes(items):
    return [e['code'] for e in items]


# --------------------------------------------------------------------------- renamed ship
def test_identifier_confirms_under_another_name():
    r = _run([_c(1, 'OCEAN GLORY', '9074729')], imo='9074729', name='NORTHERN LUMEN')
    h = r['hits'][0]
    assert h['tier'] == 'CONFIRMED' and 'renamed' in codes(h['explanation'])
    assert h['entered_name_differs'] == {'entered': 'NORTHERN LUMEN', 'listed': 'OCEAN GLORY', 'identifier': 'IMO'}
    assert 'r_name_differs' in codes(r['risk']['lines'])
    assert 'renamed' in VG.situations(r)
    # the listed name (or a close spelling) entered: nothing to flag
    for n in ('OCEAN GLORY', 'OCEAN GLORI'):
        h = _run([_c(1, 'OCEAN GLORY', '9074729')], imo='9074729', name=n)['hits'][0]
        assert 'renamed' not in codes(h['explanation']) and not h.get('entered_name_differs')


def test_known_name_found_by_name_screening():
    cands = [_c(1, 'OCEAN GLORY', '9074729')]
    VS.add_known_names(cands, [{'group_key': 'IMO:9074729', 'name': 'NORTHERN LUMEN', 'kind': 'new_name'}])
    r = _run(cands, name='NORTHERN LUMEN')
    h = r['hits'][0]
    assert h['imo'] == '9074729' and h['tier'] == 'POTENTIAL' and 'known_name' in codes(h['explanation'])
    # with the IMO: confirmed, and no "listed under another name" (the name is known)
    h = _run(cands, imo='9074729', name='NORTHERN LUMEN')['hits'][0]
    assert h['tier'] == 'CONFIRMED' and 'renamed' not in codes(h['explanation'])


# --------------------------------------------------------------------------- engine quality (production-like data)
def test_every_word_needs_a_counterpart():
    assert VE.name_score('BALTIC DAWN', 'ATLANTIC DAWN')[0] < 75
    assert VE.name_score('SINAI SPIRIT 8', 'NAVIG8 SPIRIT')[0] < 75
    assert VE.name_score('CHON MA ASN', 'CHON MA SAN')[0] >= 75          # one keying error is still that word
    assert VE.name_score('GOLDEN HORIZPN', 'GOLDEN HORIZON')[0] >= 90
    assert VE.name_score('OCEAN STAR 1', 'OCEANSTAR 1')[0] == 100


def test_imo_conflict_on_an_alias_is_another_ship():
    # the screened IMO is on no list; the name is only an alias / former name of the listed ship: another hull
    cands = [_c(1, 'SKY RIDER', '9074729', alt=['BALTIC CARRIER'])]
    r = _run(cands, name='BALTIC CARRIER', imo='9387425')
    assert VE.decision(r)[0] == 'no_match'
    # the listed ship's own name with an unlisted IMO: possibly a false IMO - review
    r = _run([_c(1, 'TIAN XIANG 7', '9074729')], name='TIAN XIANG 7', imo='9387425')
    assert VE.decision(r)[0] == 'review'


def test_imo_known_only_from_port_inspections_is_not_listed():
    cands = [_c(1, 'TIAN XIANG 7', '9074729'), _c(2, 'CHAO TIAN MEN', '9387425', prov=VP.RISK)]
    r = _run(cands, name='TIAN XIANG 7', imo='9387425')
    assert VE.decision(r)[0] == 'review' and r['hits'][0]['imo'] == '9074729'


def test_banned_ship_never_alerts_on_a_common_one_word_name():
    cands = [_c(1, 'ATLANTIC', '9074729', prov=VP.BAN)]
    r = _run(cands, name='ATLANTIC')
    assert not r['ban_hits'] and VE.decision(r)[0] == 'no_match'
    assert any(n['name'] == 'ATLANTIC' for n in r['near'])
    # its IMO still finds it (review: a ban is not a sanctions listing)
    r = _run(cands, imo='9074729')
    assert r['ban_hits'] and VE.decision(r)[0] == 'review'


# --------------------------------------------------------------------------- update status
def test_next_update_follows_the_schedule():
    now = datetime(2026, 11, 20, 2, 0)
    assert VS.next_update(None, now) == datetime(2026, 11, 20, 3, 30)
    assert VS.next_update(None, datetime(2026, 11, 20, 4, 0)) == datetime(2026, 11, 21, 3, 30)


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
    c.rollback()
    c.close()


@needs_db
def test_db_known_name_and_observation_queue(conn):
    gk = 'IMO:9436941'
    try:
        kid = VS.add_known_name(conn, gk, 'TEST NEW NAME ZZ', 'unit test', None, imo='9436941')
        assert kid and VS.add_known_name(conn, gk, 'Test new name zz', 'dup', None) is None
        VS._CACHE.clear()
        r = VE.screen_vessel(conn=conn, name='TEST NEW NAME ZZ', whitelist={})
        assert r['hits'] and r['hits'][0]['imo'] == '9436941'
        res = VE.screen_vessel(conn=conn, imo='9436941', name='ANOTHER TEST NAME QQ', whitelist={})
        assert VS.record_name_observations(conn, res) == 1 and VS.record_name_observations(conn, res) == 1
        with conn.cursor() as cur:
            cur.execute("SELECT seen_count FROM vessel_name_observations WHERE entered_norm = 'ANOTHER TEST NAME QQ'")
            assert cur.fetchone()['seen_count'] == 2
        st = VS.update_status(conn)
        assert st['next_update'] > datetime.now() and 'SANCTION' in st['ships']
    finally:
        conn.rollback()
        VS._CACHE.clear()
