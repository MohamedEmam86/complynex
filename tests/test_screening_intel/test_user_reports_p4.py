"""P4-10 / G11: screening work by user and hits by list / country (screening/user_reports.py)."""
import io
import json
from datetime import datetime, date

from screening import user_reports as UR


class FakeQ:
    """Returns canned rows by matching a fragment of the SQL; records the params."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, sql, params=()):
        self.calls.append((sql, params))
        for frag, rows in self.table:
            if frag in sql:
                return rows(params) if callable(rows) else rows
        return []


def _users(params):
    ids = params[0]
    names = {1: ('Mona Analyst', 'm@x'), 2: ('Omar MLRO', 'o@x'), 3: ('', 'nofirst@x')}
    return [{'id': i, 'name': names[i][0], 'email': names[i][1]} for i in ids if i in names]


def _fake():
    return FakeQ([
        ('FROM screening_history h', [
            {'uid': 1, 'res': 'CLEAR', 'again': False},
            {'uid': 1, 'res': 'INCOMPLETE', 'again': True},
            {'uid': 2, 'res': 'POTENTIAL_MATCH', 'again': False},
            {'uid': None, 'res': 'CLEAR', 'again': False},
        ]),
        ('q.resolved_by AS uid', [
            {'uid': 1, 'resolution': 'False Positive', 'created_at': datetime(2026, 10, 1, 10),
             'resolved_date': '2026-10-01 12:00:00'},
            {'uid': 1, 'resolution': 'True Match - Block', 'created_at': datetime(2026, 10, 1, 10),
             'resolved_date': '2026-10-03 10:00:00'},
            {'uid': 1, 'resolution': 'False Positive (Bulk)', 'created_at': datetime(2026, 10, 1, 10),
             'resolved_date': ''},
        ]),
        ('r.requested_by AS uid', [
            {'uid': 1, 'status': 'approved', 'requested_at': datetime(2026, 10, 2, 9)},
            {'uid': 1, 'status': 'rejected', 'requested_at': datetime(2026, 10, 2, 9)},
            {'uid': 1, 'status': 'pending', 'requested_at': datetime(2026, 10, 2, 9)},
        ]),
        ('r.decided_by AS uid', [
            {'uid': 2, 'status': 'approved', 'requested_at': datetime(2026, 10, 2, 9),
             'decided_at': datetime(2026, 10, 2, 11)},
            {'uid': 2, 'status': 'rejected', 'requested_at': datetime(2026, 10, 2, 9),
             'decided_at': datetime(2026, 10, 4, 9)},
        ]),
        ('FROM screening_evidence_packs', [{'uid': 2, 'n': 3}]),
        ('FROM users WHERE id = ANY', _users),
    ])


def test_period_defaults_and_bad_input():
    df, dt, dx = UR.period('2026-10-01', '2026-10-31')
    assert (df, dt, dx) == ('2026-10-01', '2026-10-31', '2026-11-01')
    df, dt, dx = UR.period("x'; drop", None, today=date(2026, 10, 31))
    assert dt == '2026-10-31' and df == '2026-10-02'
    df, dt, _ = UR.period('2026-10-31', '2026-10-01')          # swapped
    assert (df, dt) == ('2026-10-01', '2026-10-31')


def test_user_stats_team():
    rows = UR.user_stats(_fake(), '2026-10-01', '2026-11-01', sla_hours=24,
                         now=datetime(2026, 10, 5, 9))
    by = {r['user_id']: r for r in rows}
    a, m = by[1], by[2]
    assert a['name'] == 'Mona Analyst' and m['name'] == 'Omar MLRO'
    assert (a['screenings'], a['incomplete'], a['rescreens']) == (2, 1, 1)
    assert (a['hits_handled'], a['true_matches'], a['false_positives'], a['bulk_resolved']) == (3, 1, 2, 1)
    assert a['avg_hit_hours'] == 25.0 and a['hits_overdue'] == 1      # 2h and 48h; '' ignored
    assert (a['proposed'], a['proposed_approved'], a['proposed_rejected'], a['proposed_pending']) == (1 + 2, 1, 1, 1)
    assert a['proposed_pending_overdue'] == 1 and a['override_rate'] == 50.0
    assert (m['decided'], m['approved'], m['rejected'], m['decided_overdue']) == (2, 1, 1, 1)
    assert m['avg_decision_hours'] == 25.0 and m['evidence_packs'] == 3
    assert None not in by                                           # rows with no user are skipped
    tot = UR.totals(rows)
    assert tot['screenings'] == 3 and tot['decided'] == 2


def test_user_stats_analyst_sees_only_own_rows():
    fq = _fake()
    rows = UR.user_stats(fq, '2026-10-01', '2026-11-01', user_id=1)
    # every work query is filtered to the user (param appended) ...
    work = [c for c in fq.calls if 'FROM users' not in c[0]]
    assert work and all(c[1][-1] == 1 and '= %s' in c[0].split('WHERE')[-1] for c in work)
    # ... and an analyst with no work still gets their own (empty) row
    rows = UR.user_stats(FakeQ([('FROM users WHERE id = ANY', _users)]), '2026-10-01', '2026-11-01', user_id=3)
    assert len(rows) == 1 and rows[0]['screenings'] == 0 and rows[0]['name'] == 'nofirst@x'


def test_list_breakdown_rates_categories_and_countries():
    md_os = json.dumps({'source': 'opensanctions', 'list_type': 'SANCTIONS', 'topics': ['sanction'],
                        'dataset': 'us_ofac_sdn', 'nationality': 'Syria'})
    md_pep = json.dumps({'source': 'opensanctions_pep', 'topics': ['role.pep'], 'countries': ['eg']})
    md_int = json.dumps({'source': 'internal_blacklist', 'nationality': 'Egyptian'})
    res_in = json.dumps({'inputs': {'nationality': 'Egypt'}})
    fq = FakeQ([
        ('FROM screening_queue q', [
            {'list_source': 'opensanctions', 'status': 'Resolved', 'resolution': 'False Positive',
             'match_details': md_os, 'source_module': 'API', 'source_record_id': None, 'result_details': res_in},
            {'list_source': 'opensanctions', 'status': 'Resolved', 'resolution': 'True Match - Block',
             'match_details': md_os, 'source_module': 'API', 'source_record_id': None, 'result_details': None},
            {'list_source': 'opensanctions_pep', 'status': 'Pending', 'resolution': None,
             'match_details': md_pep, 'source_module': 'Customer KYC', 'source_record_id': 7, 'result_details': '{}'},
            {'list_source': 'INTERNAL_BLACKLIST', 'status': 'Resolved', 'resolution': 'False Positive (Bulk)',
             'match_details': md_int, 'source_module': 'Bulk Upload', 'source_record_id': 1, 'result_details': 'not json'},
            {'list_source': 'internal_blacklist', 'status': 'Resolved', 'resolution': 'False Positive',
             'match_details': '{broken', 'source_module': 'Bulk Upload', 'source_record_id': 2, 'result_details': None},
        ]),
        ('FROM customers', [{'id': 7, 'nationality': 'Jordan'}]),
    ])
    bd = UR.list_breakdown(fq, '2026-10-01', '2026-11-01')
    assert bd['total'] == 5
    lists = {r['list']: r for r in bd['by_list']}
    assert lists['opensanctions']['fp_rate'] == 50.0
    assert lists['internal_blacklist']['hits'] == 2 and lists['internal_blacklist']['fp_rate'] == 100.0
    assert lists['opensanctions_pep']['pending'] == 1 and lists['opensanctions_pep']['fp_rate'] is None
    cats = {r['category']: r['hits'] for r in bd['by_category']}
    assert cats.get('PEP') == 1 and cats.get('LOCAL_LIST') == 2
    cc = {r['country']: r['hits'] for r in bd['by_customer_country']}
    assert cc.get('EG') == 1 and cc.get('JO') == 1           # Customer KYC -> customer record
    lc = {r['country']: r['hits'] for r in bd['by_listed_country']}
    assert lc.get('SY') == 2 and lc.get('EG', 0) >= 1


def test_workbook_and_formula_injection():
    from openpyxl import load_workbook
    rows = [dict(UR._blank(1), name='=HYPERLINK("x")', avg_hit_hours=None, avg_decision_hours=None,
                 override_rate=None)]
    data = UR.workbook(users=rows, breakdown={'by_list': [{'list': '+cmd', 'hits': 1, 'true_matches': 0,
                                                            'false_positives': 1, 'pending': 0, 'fp_rate': 100.0}]},
                       meta={'Period': '2026-10-01 - 2026-10-31'})
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames[:3] == ['Info', 'Users', 'By list']
    assert wb['Users']['A2'].value.startswith("'=")
    assert wb['By list']['A2'].value == "'+cmd"
    assert wb['By list']['F2'].value == 100.0


def test_hours_handles_bad_values():
    assert UR._hours(None, datetime.now()) is None
    assert UR._hours('garbage', '2026-10-01 10:00:00') is None
    assert UR._hours('2026-10-02 10:00:00', '2026-10-01 10:00:00') is None   # negative
    assert UR._hours(datetime(2026, 10, 1, 10), '2026-10-01T12:30:00') == 2.5
