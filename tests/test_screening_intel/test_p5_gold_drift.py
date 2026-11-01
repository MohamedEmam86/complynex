"""P5-1 Gold Set v2 generators and P5-5 drift report (invented names only)."""
import io
import json
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import gold_set_v2 as G  # noqa: E402
from screening import drift as D  # noqa: E402


# ---------------------------------------------------------------- P5-1
@pytest.mark.parametrize('d', ['lev', 'gulf', 'maghreb', 'persian', 'turkish'])
def test_respell_changes_name_and_is_deterministic(d):
    a = G.respell('Mohamed Gamal Ragab', d, random.Random(1))
    b = G.respell('Mohamed Gamal Ragab', d, random.Random(1))
    assert a and a == b and a.lower() != 'mohamed gamal ragab'


def test_turkish_and_persian_forms():
    assert G.respell('Mohamed Hussein', 'turkish', random.Random(3)).split()[0] == 'Mehmet'
    assert 'Hossein' in G.respell('Ali Hussein', 'persian', random.Random(3))


def test_franco_uses_arabic_letters():
    r = G.franco(['حمدان', 'عبير'], 'Hamdan Abeer', random.Random(2))
    assert r and '7' in r and '3' in r


class FakeB:
    def __init__(self):
        self.pairs = []

    def fill(self, cat, label, items, fn, src, n=100, tier='core', real_query=False):
        got = 0
        for it in list(items):
            if got >= n:
                break
            r = fn(it)
            if r and r[0] and r[0] != r[1]:
                self.pairs.append((cat, label, tier, r[0], r[1]))
                got += 1
        return got


def _units(n):
    out = []
    for w in n.split():
        if out and (out[-1] in ('عبد', 'ابو') or w in ('الدين', 'الله')):
            out[-1] += ' ' + w
        else:
            out.append(w)
    return out


EG = {'حمدان': 'Hamdan', 'جابر': 'Gaber', 'رجب': 'Ragab', 'شاكر': 'Shaker', 'كامل': 'Kamel', 'جلال': 'Galal'}


def _eg(us):
    return ' '.join(EG[u] for u in us) if all(u in EG for u in us) else None


def test_v2_build_labels_and_tier():
    names = ['حمدان جابر رجب شاكر', 'جلال كامل رجب شاكر', 'ميرنال جابر رجب', 'سيلفان كامل جلال',
             'رجب نصر الله جابر', 'ابو جلال كامل رجب']
    src = {'units': _units, 'translit': lambda n: _eg(_units(n)), 'eg_latin': _eg, 'tokens': lambda n: n.split(),
           'four_lat': names[:2], 'xs': [('شاكر رجب', 'Shaker Ragab')], 'lat': [('Paolo de Rossi Bianchi', None)],
           'org_ar': ['مصرف النيل للتجارة'], 'org_lat': ['Nile Trading International Company'],
           'org_x': [('النيل للتجارة', 'Nile Trading'), ('النيل للمقاولات', 'Nile Contracting')],
           'ar_names': names, 'common': ['حمدان', 'جلال', 'جابر'], 'lookalike': {}, 'EG_LATIN': EG}
    B = FakeB()
    counts = G.build(B, random.Random(5), src)
    cats = {p[0] for p in B.pairs}
    assert all(p[2] == G.TIER for p in B.pairs)
    assert all(p[1] == 0 for p in B.pairs if p[0].startswith('x_neg_'))
    assert all(p[1] == 1 for p in B.pairs if not p[0].startswith('x_neg_'))
    for c in ('x_lev_spelling', 'x_neg_lev_sibling', 'x_long_vowel', 'x_allah_glued_ar', 'x_neg_allah_head_only',
              'x_bin_chain_ar', 'x_neg_kunya', 'x_company_abbrev', 'x_particle_dropped_lat', 'x_neg_particle_only'):
        assert c in cats, c
    assert counts['x_lev_spelling'] >= 1


def test_no_gold_tables_in_the_matcher():
    """The Gold Set generators must never be used by the screening code (test leakage)."""
    for dirpath, _, files in os.walk(os.path.join(ROOT, 'screening')):
        for f in files:
            if f.endswith('.py'):
                t = open(os.path.join(dirpath, f), encoding='utf-8').read()
                assert 'gold_set_v2' not in t and 'gold_set_build' not in t, f


# ---------------------------------------------------------------- P5-5
def test_month_helpers():
    assert D.month_bounds('2026-12') == ('2026-12-01', '2027-01-01')
    assert D.month_before('2026-01') == '2025-12'
    import datetime
    assert D.previous_month(datetime.date(2026, 3, 15)) == '2026-02'


def _m(fp=10.0, decided=40, hits=60, inc=0.0, recall=97.0, core=0.5):
    return {'lists': {'ofac': {'runs': 30, 'failures': 0, 'blocked': 0, 'added': 1, 'updated': 2, 'delisted': 0,
                               'relisted': 0, 'active': 1000, 'delisted_pct': 0.0}},
            'hits_by_list': {'ofac': {'hits': hits, 'true_matches': 2, 'false_positives': 38, 'pending': 20,
                                      'decided': decided, 'fp_rate': fp, 'avg_score': 80}},
            'hits_by_category': {},
            'screening': {'screenings': 100, 'incomplete': int(inc), 'incomplete_rate': inc},
            'gold': {'v1': {'runs': 3, 'core_miss_rate': core, 'core_fp_rate': 0.2}},
            'e2e': {'runs': 4, 'avg_recall': recall}}


def test_compare_quiet_month():
    assert D.compare(_m(), _m()) == []


def test_compare_alerts():
    al = D.compare(_m(fp=30.0, hits=200, inc=3.0, recall=93.0, core=1.5), _m())
    codes = {a['code'] for a in al}
    assert {'fp_rate', 'hit_volume', 'incomplete', 'e2e_recall', 'gold'} <= codes
    assert all(a['en'] and a['ar'] for a in al)


def test_compare_first_report_and_small_samples():
    assert [a['code'] for a in D.compare(_m(inc=5.0), None)] == ['incomplete']
    assert D.compare(_m(fp=90.0, decided=5), _m(decided=5)) == []


def test_compare_list_failures_and_delisting():
    cur = _m()
    cur['lists']['ofac'].update({'failures': 2, 'blocked': 1, 'delisted': 80, 'delisted_pct': 8.0})
    codes = [a['code'] for a in D.compare(cur, _m())]
    assert 'list_updates' in codes and 'list_delisted' in codes


def test_collect_with_fake_queries(tmp_path):
    (tmp_path / '20261005_120000_abc.json').write_text(json.dumps(
        {'gold_version': 1, 'commit': 'abc', 'core_miss_rate': 0.5, 'core_fp_rate': 0.2,
         'categories': {'x': {'rate': 1.0}}, 'holdout': {'n': 1}}))
    (tmp_path / '20260930_120000_abc.json').write_text(json.dumps({'gold_version': 1, 'core_miss_rate': 9}))

    def q(sql, params):
        if 'screening_list_update_log' in sql:
            return [{'source': 'OFAC', 'status': 'ok', 'added': 1, 'updated': 2, 'delisted': 3, 'relisted': 0},
                    {'source': 'ofac', 'status': 'failed', 'added': 0, 'updated': 0, 'delisted': 0, 'relisted': 0},
                    {'source': 'ofac', 'status': 'skipped', 'added': 0, 'updated': 0, 'delisted': 0, 'relisted': 0}]
        if 'screening_list_versions' in sql:
            return [{'source': 'ofac', 'n': 1}]
        if 'FROM screening_watchlist' in sql:
            return [{'source': 'ofac', 'n': 300}]
        if 'screening_queue' in sql:
            return [{'list_source': 'ofac', 'status': 'Resolved', 'resolution': 'False Positive', 'match_score': 80,
                     'match_details': '{}'},
                    {'list_source': 'OFAC', 'status': 'Resolved', 'resolution': 'True Match - Block',
                     'match_score': 99, 'match_details': '{}'},
                    {'list_source': 'ofac', 'status': 'Pending', 'resolution': None, 'match_score': None,
                     'match_details': None}]
        if 'screening_results' in sql:
            return [{'screening_result': 'INCOMPLETE', 'total_matches_found': 0, 'highest_match_score': 0},
                    {'screening_result': 'CLEAR', 'total_matches_found': 0, 'highest_match_score': 10},
                    {'screening_result': 'POTENTIAL_MATCH', 'total_matches_found': 2, 'highest_match_score': 86}]
        if 'screening_quality_runs' in sql:
            return [{'summary': {'recall': 97.0, 'false_alert_rate': 0.0}}, {'summary': '{"recall": 95.0}'}]
        return []
    m = D.collect(q, '2026-10', gold_dir=str(tmp_path))
    o = m['lists']['ofac']
    assert (o['runs'], o['failures'], o['blocked'], o['delisted'], o['active']) == (3, 1, 1, 3, 300)
    h = m['hits_by_list']['ofac']
    assert (h['hits'], h['false_positives'], h['true_matches'], h['pending'], h['fp_rate']) == (3, 1, 1, 1, 50.0)
    s = m['screening']
    assert (s['screenings'], s['incomplete'], s['with_hits']) == (3, 1, 1)
    assert m['gold']['v1']['runs'] == 1 and m['gold']['v1']['core_miss_rate'] == 0.5
    assert m['e2e'] == {'runs': 2, 'avg_recall': 96.0, 'min_recall': 95.0, 'avg_false_alert_rate': 0.0}


def test_workbook_is_formula_safe():
    from openpyxl import load_workbook
    m = _m()
    m['hits_by_list'] = {'=HYPERLINK("x")': m['hits_by_list']['ofac']}
    data = D.workbook('2026-10', m, [{'subject': '+cmd', 'en': '-x', 'ar': 'x', 'code': 'c'}])
    wb = load_workbook(io.BytesIO(data))
    vals = [c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
    assert not any(v[:1] in '=+-@' for v in vals)
