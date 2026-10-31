"""P2-6 / G5: linking the same person across lists (never on a name alone)."""
import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from screening import entity_links as EL          # noqa: E402
from screening.country_codes import to_iso2       # noqa: E402


def _builder():
    spec = importlib.util.spec_from_file_location('bel', os.path.join(ROOT, 'scripts', 'build_entity_links.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ country codes
@pytest.mark.parametrize('v,exp', [
    ('Egyptian', {'eg'}), ('مصرية', {'eg'}), ('IRAN (ISLAMIC REPUBLIC OF)', {'ir'}), ('Russia; Syria', {'ru', 'sy'}),
    ('["mx", "us"]', {'mx', 'us'}), ('Korea, North', {'kp'}), ('Bosnia and Herzegovina', {'ba'}),
    (None, set()), ('', set()), ('somewhere unknown', set()),
])
def test_to_iso2(v, exp):
    assert to_iso2(v) == exp


# ------------------------------------------------------------------ builder helpers
def test_builder_helpers():
    b = _builder()
    assert b.norm_id('29001011234567') == '29001011234567'
    assert b.norm_id('123') is None                    # too short
    assert b.norm_id('00000000') is None               # placeholder
    assert b.full_dates('1980-01-01') == set()         # 1 Jan = year only, never a full date
    assert b.full_dates('1980-05-17;1981-02-03') == {'1980-05-17', '1981-02-03'}
    assert b.kind('INDIVIDUAL') == 'P' and b.kind('ENTITY') == 'E'
    assert b.rank('emlcu') < b.rank('ofac') < b.rank('opensanctions')


# ------------------------------------------------------------------ runtime grouping
class FakeCur:
    """links: (watchlist_id, cluster_id, source, source_id); members: (cluster_id, watchlist_id, source,
    basis, list_type, dataset). Answers the one CTE query of lookup()."""
    def __init__(self, links, members, tables=True):
        self.links, self.members, self.tables = links, members, tables
        self.rows = []

    def execute(self, sql, params=None):
        if 'to_regclass' in sql:
            self.rows = [(self.tables,)]
        elif 'WITH hit AS' in sql:
            ids = set(params[0])
            cids = {r[1] for r in self.links if r[0] in ids}
            src = {(r[0]): (r[2], r[3]) for r in self.links}
            self.rows = [(m[0], m[1], m[2], src.get(m[1], (None, None))[1], m[3], m[4], m[5])
                         for m in self.members if m[0] in cids]
        else:
            self.rows = []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    EL._TABLES['ok'], EL._TABLES['at'] = None, 0.0
    import screening.match_classifier as mc
    monkeypatch.setattr(mc, 'classify_match',
                        lambda m: 'PEP' if 'PEP' in str(m.get('list_type')) else 'SANCTIONS')
    yield
    EL._TABLES['ok'] = None


def _hits():
    return [
        {'id': 10, 'source': 'ofac', 'list_type': 'SANCTIONS', 'match_score': 91.0, 'full_name': 'Person A'},
        {'id': 11, 'source': 'opensanctions', 'list_type': 'SANCTIONS', 'match_score': 96.0, 'full_name': 'Person A'},
        {'id': 12, 'source': 'opensanctions_pep', 'list_type': 'PEP', 'match_score': 88.0, 'full_name': 'Person A'},
        {'id': 20, 'source': 'eu', 'list_type': 'SANCTIONS', 'match_score': 80.0, 'full_name': 'Someone Else'},
    ]


def _cur():
    links = [(10, 7, 'ofac', 'OFAC-1'), (11, 7, 'opensanctions', 'OS-x'), (12, 7, 'opensanctions_pep', 'OS-x')]
    members = [(7, 10, 'ofac', 'lead', 'SANCTIONS', 'ofac'),
               (7, 11, 'opensanctions', 'os_referent', 'SANCTIONS', 'us_ofac_sdn'),
               (7, 12, 'opensanctions_pep', 'os_id', 'PEP', 'peps'),
               (7, 13, 'un', 'os_id', 'SANCTIONS', 'un_sc_sanctions')]
    return FakeCur(links, members)


def _strip(hits):
    return [{k: v for k, v in h.items() if k not in EL.ANNOTATION_KEYS} for h in hits]


def test_annotate_never_removes_or_changes_a_hit():
    import copy
    before = _hits()
    out = EL.annotate(copy.deepcopy(before), cur=_cur())
    assert len(out) == len(before)                      # queue rows, counts, ongoing screening, API: every hit
    assert _strip(out) == before                       # same hits, same order, same fields
    assert set(k for h in out for k in h) - set(k for h in before for k in h) <= set(EL.ANNOTATION_KEYS)


def test_same_cluster_same_kind_is_tagged_not_dropped():
    out = EL.annotate(_hits(), cur=_cur())
    by = {m['id']: m for m in out}
    assert by[10]['grouped_under'] == 'OPENSANCTIONS:11'   # the best-scored sanctions hit leads ...
    assert [g['ref'] for g in by[11]['grouped_hits']] == ['OFAC:10']
    assert 'grouped_under' not in by[11]
    assert by[11]['cluster']['other_kinds'] == ['PEP']
    assert by[10]['cluster']['id'] == by[11]['cluster']['id'] == 7


def test_other_kind_kept_and_points_back():
    out = EL.annotate(_hits(), cur=_cur())
    pep = next(m for m in out if m['id'] == 12)        # a PEP record is never folded into a sanctions hit
    assert pep['cluster']['other_kinds'] == ['SANCTIONS'] and 'grouped_under' not in pep
    assert next(m for m in out if m['id'] == 20).get('cluster') is None   # unlinked hit untouched


def test_fold_views_is_display_only_and_keeps_orphans():
    views = [{'ref': 'OPENSANCTIONS:11'}, {'ref': 'OFAC:10', 'grouped_under': 'OPENSANCTIONS:11'},
             {'ref': 'EMLCU:5', 'grouped_under': 'OPENSANCTIONS:99'}]          # its primary is not on the page
    shown = [v['ref'] for v in EL.fold_views(views)]
    assert shown == ['OPENSANCTIONS:11', 'EMLCU:5']


def test_nothing_lost_without_tables_or_on_error():
    h = _hits()
    assert EL.annotate(h, cur=FakeCur([], [], tables=False)) == _hits()

    class Boom(FakeCur):
        def execute(self, sql, params=None):
            raise RuntimeError('db down')
    assert EL.annotate(_hits(), cur=Boom([], [])) == _hits()


def test_tables_missing_is_rechecked(monkeypatch):
    cur = FakeCur([], [], tables=False)
    assert EL._tables_ok(cur) is False
    cur.tables = True
    assert EL._tables_ok(cur) is False                 # cached for a while ...
    EL._TABLES['at'] -= EL._RECHECK + 1
    assert EL._tables_ok(cur) is True                  # ... but not forever


def test_internal_hit_maps_to_watchlist_copy():
    assert EL.watchlist_sid('internal_blacklist', 'IBL-ABC', 'x') == 'IBL-ABC'
    import hashlib
    exp = 'IBL-' + hashlib.md5('اسم تجريبي'.encode()).hexdigest()[:12].upper()
    assert EL.watchlist_sid('internal_blacklist', 'INTERNAL-9', ' اسم تجريبي ') == exp
    assert EL._hit_key({'source': 'INTERNAL_BLACKLIST', 'entity_id': 5, 'source_id': 'INTERNAL-9'}) == \
        ('int', 'internal_blacklist', 5)


def test_differences_report():
    rows = [{'label': 'OFAC', 'date_of_birth': '1970-03-02', 'nationality': 'Iraq', 'national_id_numbers': '["A1234567"]',
             'passport_numbers': None},
            {'label': 'UK', 'date_of_birth': '1971', 'nationality': 'Iraqi', 'national_id_numbers': '["A1234567"]',
             'passport_numbers': None},
            {'label': 'EU', 'date_of_birth': '1985-01-01', 'nationality': 'Syria', 'national_id_numbers': '["B7654321"]',
             'passport_numbers': None}]
    fields = {d['field'] for d in EL.differences(rows)}
    assert fields == {'Date of birth', 'Nationality', 'National / official ID'}
    assert EL.differences(rows[:2]) == []              # 1970 vs 1971 (±1 year) and Iraq = Iraqi agree


def test_unlink_needs_a_reason():
    with pytest.raises(ValueError):
        EL.unlink(object(), 1, 1, 'too short')


class _UConn:
    """Fake connection for unlink(): build lock result and the cluster of the record."""
    def __init__(self, lock_ok=True, cluster=7):
        self.lock_ok, self.cluster, self.rolled, self.committed, self.sql = lock_ok, cluster, 0, 0, []

    def cursor(self):
        conn = self

        class C:
            rows = []

            def execute(self, sql, params=None):
                conn.sql.append(sql)
                if 'pg_try_advisory_xact_lock' in sql:
                    self.rows = [(conn.lock_ok,)]
                elif 'SELECT cluster_id FROM screening_entity_links' in sql:
                    self.rows = [(conn.cluster,)] if conn.cluster else []
                elif 'SELECT watchlist_id FROM screening_entity_links' in sql:
                    self.rows = [(1,), (2,)]
                elif 'SELECT lead_watchlist_id' in sql:
                    self.rows = [(1,)]
                else:
                    self.rows = []

            def fetchone(self):
                return self.rows[0] if self.rows else None

            def fetchall(self):
                return list(self.rows)
        return C()

    def rollback(self):
        self.rolled += 1

    def commit(self):
        self.committed += 1


def test_unlink_refused_while_a_rebuild_runs():
    c = _UConn(lock_ok=False)
    with pytest.raises(ValueError):
        EL.unlink(c, 3, 1, 'not the same person at all')
    assert c.rolled and not c.committed


def test_unlink_only_for_a_cluster_of_this_result():
    c = _UConn(cluster=7)
    with pytest.raises(PermissionError):
        EL.unlink(c, 3, 1, 'not the same person at all', allowed_clusters={8})
    assert c.rolled and not c.committed


def test_unlink_audits_in_the_same_transaction():
    c = _UConn(cluster=7)
    assert EL.unlink(c, 3, 1, 'not the same person at all', allowed_clusters={7}, ip_address='127.0.0.1') == 7
    assert c.committed == 1
    i_audit = next(i for i, q in enumerate(c.sql) if 'INSERT INTO audit_logs' in q)
    i_unl = next(i for i, q in enumerate(c.sql) if 'INSERT INTO screening_entity_unlinks' in q)
    assert i_unl < i_audit                              # both before the single commit
    assert any('lock_timeout' in q for q in c.sql)


# ------------------------------------------------------------------ builder: no contradiction through a third record
class _BConn:
    """Fake DB for build(): three OFAC / UK / EU records share one official ID number."""
    def __init__(self, rows):
        self.rows_ids = rows

    def cursor(self, name=None, **kw):
        conn = self

        class C:
            itersize = 0
            rows = []

            def execute(self, sql, params=None):
                if 'to_regclass' in sql:
                    self.rows = [(False,)]
                elif 'national_id_numbers, passport_numbers' in sql:
                    self.rows = conn.rows_ids
                elif 'date_of_birth ~' in sql:
                    self.rows = []
                elif 'SELECT id, date_of_birth, nationality, national_id_numbers' in sql:
                    self.rows = [(r[0], r[7], r[5], r[3]) for r in conn.rows_ids]
                else:
                    self.rows = []

            def __iter__(self):
                return iter(self.rows)

            def fetchone(self):
                return self.rows[0] if self.rows else None

            def fetchall(self):
                return list(self.rows)

            def close(self):
                pass
        return C()


def _id_row(wid, src, dob, nat):
    # id, source, entity_type, national_id_numbers, passport_numbers, nationality, countries, date_of_birth
    return (wid, src, 'INDIVIDUAL', '["X12345678"]', None, nat, None, dob)


def test_official_id_no_contradiction_through_a_third_record():
    b = _builder()
    rows = [_id_row(1, 'ofac', '1970-03-02', 'Iraq'), _id_row(2, 'hmt', None, None), _id_row(3, 'eu', '1990-07-07', 'Iraq')]
    clusters, stats = b.build(_BConn(rows), log=lambda m: None)
    groups = [sorted(c['members']) for c in clusters]
    assert [1, 2] in groups and not any(1 in g and 3 in g for g in groups)
    assert stats['official_id_refused_contradiction'] == 1


def test_official_id_agreeing_records_are_linked():
    b = _builder()
    rows = [_id_row(1, 'ofac', '1970-03-02', 'Iraq'), _id_row(2, 'hmt', '1971', 'Iraqi'), _id_row(3, 'eu', None, 'Iraq')]
    clusters, _ = b.build(_BConn(rows), log=lambda m: None)
    assert [sorted(c['members']) for c in clusters] == [[1, 2, 3]]
