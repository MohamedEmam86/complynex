# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Phase 8 review fixes of the TM engine (B2, B3, should-fix 3-11, nits): pure tests,
the database replaced by a recording fake."""
import json
import random
from datetime import datetime, timedelta

import pytest

from aml import tm_backtest as B
from aml import tm_engine as E
from aml import tm_service as S

T0 = datetime(2025, 6, 1, 10, 0, 0)
_id = [5000]


def tx(cust, days=0, hours=0, minutes=0, amount=1000, ttype='PAYMENT', **kw):
    _id[0] += 1
    d = dict(id=_id[0], customer_id=cust, amount=amount, transaction_type=ttype, currency='EGP',
             transaction_date=(T0 + timedelta(days=days, hours=hours, minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S'))
    d.update(kw)
    return d


def rule(code, **kw):
    r = {'id': abs(hash(code)) % 1000, 'rule_code': code, 'version': 1}
    r.update(kw)
    return r


def run(code, txs, target, ctx=None, cust=None, hist=None, **rule_kw):
    h = hist or E.History(txs)
    return E.evaluate(rule(code, **rule_kw), target, h, cust or {}, ctx or E.Context())


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeDB:
    """Records every statement; `answer(sql, args)` returns the rows (or raises)."""

    def __init__(self, answer=None):
        self.sql, self.commits, self.rollbacks = [], 0, 0
        self.answer = answer or (lambda sql, args: [])

    def execute(self, sql, args=()):
        self.sql.append((' '.join(sql.split()), args))
        return FakeCursor(self.answer(sql, args))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


# ---------------------------------------------------------------- B2: dates
@pytest.mark.parametrize('raw,expected', [
    ('2025-06-01 10:00:00', datetime(2025, 6, 1, 10)),
    ('2025-06-01T10:00', datetime(2025, 6, 1, 10)),
    ('2025-06-01', datetime(2025, 6, 1)),
    ('01/06/2025', datetime(2025, 6, 1)),               # DD/MM/YYYY
    ('01/06/2025 10:30', datetime(2025, 6, 1, 10, 30)),
    ('2025/06/01', datetime(2025, 6, 1)),               # YYYY/MM/DD
    ('01-06-2025', datetime(2025, 6, 1)),               # DD-MM-YYYY
    ('2025-06-01T10:00:00.123', datetime(2025, 6, 1, 10)),
    ('2025-06-01T07:00:00+03', datetime(2025, 6, 1, 7)),   # +HH (Cairo is UTC+3 in June)
])
def test_parse_ts_formats(raw, expected):
    assert E.parse_ts(raw) == expected


def test_parse_ts_converts_offsets_to_local_time():
    # Africa/Cairo is UTC+3 in June 2025 (summer time): all three are the same moment
    a = E.parse_ts('2025-06-01T07:00:00Z')
    b = E.parse_ts('2025-06-01T09:00:00+02:00')
    c = E.parse_ts('2025-06-01T07:00:00+0000')
    assert a == b == c and a.tzinfo is None
    assert E.parse_ts('garbage') is None and E.parse_ts('') is None


def test_rules_without_a_window_still_run_when_the_date_is_unreadable():
    bad = dict(tx(1, amount=20000, ttype='CASH_DEPOSIT', pep_involvement=1, counterparty_country='Iran'),
               transaction_date='31/31/2025')
    ctx = E.Context({'Iran'})
    assert E.evaluate(rule('TM005'), dict(bad), E.History([]), {}, ctx)            # PEP / sanctions flag
    assert E.evaluate(rule('TM004'), dict(bad), E.History([]), {}, ctx)            # high-risk country
    assert E.evaluate(rule('TM001', threshold_value=10000), dict(bad), E.History([]), {}, ctx)
    assert E.evaluate(rule('TM003', threshold_value=0), dict(bad), E.History([]), {}, ctx) is None
    assert E.needs('TM005') == set() and E.needs('TM002') == {'date', 'amount'}


def test_live_monitoring_runs_dateless_rules_and_records_the_issue(monkeypatch):
    bad = {'id': 77, 'customer_id': 9, 'transaction_date': 'n/a', 'amount': 5, 'transaction_type': 'PAYMENT',
           'currency': 'EGP', 'pep_involvement': 1, 'sanctions_hit': 0, 'counterparty_country': 'Iran',
           'counterparty_account': None}

    def answer(sql, args):
        if 'FROM transactions WHERE id = %s' in sql:
            return [dict(bad)]
        if 'FROM customers' in sql:
            return [{'id': 9}]
        return []
    db = FakeDB(answer)
    monkeypatch.setattr(S, 'get_active_rules', lambda db: [
        rule('TM005', id=5, severity='HIGH'), rule('TM003', id=3, severity='LOW', threshold_value=0)])
    monkeypatch.setattr(E, 'load_high_risk', lambda db, fresh=False: {'Iran'})
    made = []
    monkeypatch.setattr(S, 'create_alert', lambda db, r, c, t, d, trig: made.append(r['rule_code']) or 'ALT-1')
    out = S._evaluate(db, 77)
    assert made == ['TM005'] and out[0]['rule'] == 'TM005'
    assert any('INSERT INTO tm_monitoring_issues' in q and a[1] == 'date_unreadable' for q, a in db.sql)
    assert not any('substr' in q for q, a in db.sql)


# ---------------------------------------------------------------- B3: look-back loading
def test_load_history_uses_iso_ranges_and_one_exists_query_for_dormancy():
    t = {'id': 1, 'customer_id': 4, 'transaction_date': '2025-06-01 10:00:00', 'counterparty_account': '5123456789012345'}
    t['_ts'] = E.parse_ts(t['transaction_date'])

    def answer(sql, args):
        if 'EXISTS' in sql:
            return [{'e': True}]
        return []
    db = FakeDB(answer)
    rules = [rule('TM006', time_period_days=90), rule('TM016'), rule('TM001')]
    txs, prior = S.load_history(db, t, rules)
    q = [x for x, _ in db.sql]
    assert not any('substr' in x for x in q)
    cust = next(a for x, a in db.sql if 'customer_id = %s AND transaction_date >= %s' in x)
    assert cust[1] == '2025-03-02' and cust[2] == '2025-06-03'            # 90 days (+1 spare each side), not 455
    card = next(a for x, a in db.sql if 'counterparty_account = %s' in x)
    assert card[1] == '2025-05-31'                                       # TM016: 60 minutes (+1 spare day), not 2 days
    assert sum('EXISTS' in x for x in q) == 1
    ex = next(a for x, a in db.sql if 'EXISTS' in x)
    assert ex[1] == (T0 - timedelta(days=91)).strftime('%Y-%m-%d')        # the spare day is in memory
    assert prior == {(4, (T0 - timedelta(days=90)).date()): True}


def test_no_card_query_without_card_rules():
    t = {'id': 1, 'customer_id': 4, 'transaction_date': '2025-06-01 10:00:00', 'counterparty_account': '5123456789012345'}
    t['_ts'] = E.parse_ts(t['transaction_date'])
    db = FakeDB()
    S.load_history(db, t, [rule('TM001')])
    assert not any('counterparty_account = %s' in x for x, _ in db.sql)


def test_dormant_rule_uses_prior_answer_and_first_seen():
    back = tx(50, amount=9000)
    back['_ts'] = E.parse_ts(back['transaction_date'])
    day = (back['_ts'] - timedelta(days=90)).date()
    assert not run('TM006', [back], back, threshold_value=5000, time_period_days=90)
    h = E.History([back], prior={(50, day): True})
    assert run('TM006', [back], back, hist=h, threshold_value=5000, time_period_days=90)
    h = E.History([back], first_seen={50: back['_ts'] - timedelta(days=400)})
    assert run('TM006', [back], back, hist=h, threshold_value=5000, time_period_days=90)


# ---------------------------------------------------------------- should-fix 3: alert merge
def test_alert_merge_by_rule_code_and_transaction_dates():
    rows = [{'id': 10, 'triggered_transactions': json.dumps([501]), 'alert_date': '2026-11-05 09:00:00'}]

    def answer(sql, args):
        if 'FROM tm_alerts' in sql:
            assert args[2] == 'TM012' and 'SAR_CREATED' in args[1]
            return rows
        if 'FROM transactions WHERE id = ANY' in sql:
            return [{'id': 501, 'transaction_date': '2025-06-01 08:00:00'}]
        return []
    db = FakeDB(answer)
    r = rule('TM012', id=999)                     # a newer version: other rule_id, same code
    assert S._open_alert_for(db, r, 1, datetime(2025, 6, 1, 20)) is rows[0]        # 12 h after its first tx
    assert S._open_alert_for(db, r, 1, datetime(2025, 6, 3, 8)) is None             # 48 h later: new alert
    assert 'SAR_CREATED' in S.NO_MERGE_STATUSES


# ---------------------------------------------------------------- should-fix 4/5: card look-back, currency
def test_card_lookback_from_rule_windows():
    assert E.card_lookback_days([rule('TM016')]) == pytest.approx(60 / 1440)
    assert E.card_lookback_days([rule('TM011', parameters='{"hours": 72}')]) == 3
    assert E.card_lookback_days([rule('TM001')]) == 0


def test_other_currency_is_compared_unconverted_never_skipped():
    # fail safe: with no exchange-rate table a USD 100k cash deposit still alerts on an EGP rule
    usd = tx(60, amount=100000, ttype='CASH_DEPOSIT', currency='USD')
    assert run('TM001', [usd], usd, threshold_value=10000, threshold_currency='EGP')
    assert E.other_currency(rule('TM001', threshold_currency='EGP'), usd)
    assert not E.other_currency(rule('TM003', threshold_currency='EGP'), usd)
    a = [tx(61, hours=i, amount=8000, ttype='CASH_DEPOSIT', currency='USD' if i else 'EGP') for i in range(3)]
    assert run('TM002', a, a[-1], threshold_value=9000, threshold_currency='EGP', time_period_days=3)
    # count rules are not currency rules
    assert not E.is_currency_rule('TM009') and not E.is_currency_rule('TM003') and E.is_currency_rule('TM008')


def test_backtest_reports_excluded_currencies():
    txs = [tx(62, amount=60000, currency='USD'), tx(62, days=2, amount=60000)]
    r = rule('TM012', threshold_value=50000, threshold_currency='EGP')
    res = B.replay([r], txs, {}, E.Context())[r['id']]
    assert res['alerts'] == 2 and res['other_currency'] == {'USD': 1}


# ---------------------------------------------------------------- should-fix 8: running counts
def test_running_distinct_count_matches_a_full_window():
    rnd = random.Random(7)
    txs = [tx(70, hours=rnd.randint(0, 24 * 30), currency=rnd.choice(['EGP', 'USD', 'EUR', 'GBP', 'SAR']))
           for _ in range(300)]
    h = E.History(txs)
    lst = h.by_customer[70][0]
    for t in lst:
        start = t['_ts'] - timedelta(days=7)
        naive = len({x['currency'] for x in h.customer_window(t, start)})
        assert h.distinct_count(t, start, ('k',), lambda x: x['currency']) == naive


def test_running_filtered_sum_and_psp02_zero_threshold():
    from packs.psp_tm import rules as P  # noqa: F401  (registers PSP rules)
    flow = [tx(71, amount=30000, ttype='TRANSFER_IN'), tx(71, hours=5, amount=26000, ttype='TRANSFER_OUT')]
    assert run('PSP02', flow, flow[-1], threshold_value=20000)
    out_only = [tx(72, amount=500, ttype='TRANSFER_OUT')]
    assert run('PSP02', out_only, out_only[0], threshold_value=0) is None       # no division by zero


# ---------------------------------------------------------------- should-fix 9: high-risk countries
def test_high_risk_read_failure_uses_savepoint_and_full_builtin_list():
    def answer(sql, args):
        if 'high_risk_countries' in sql:
            raise RuntimeError('relation does not exist')
        return []
    db = FakeDB(answer)
    out = E.load_high_risk(db, fresh=True)
    assert out == set(E.FALLBACK_HIGH_RISK) and {'IRAN', 'SYRIA', 'RUSSIA'} <= out
    q = [x for x, _ in db.sql]
    assert 'SAVEPOINT tm_high_risk' in q and 'ROLLBACK TO SAVEPOINT tm_high_risk' in q and db.rollbacks == 0


def test_high_risk_is_cached_per_process():
    calls = []

    def answer(sql, args):
        if 'high_risk_countries' in sql:
            calls.append(1)
            return [{'country_code': 'KP', 'country_name': 'North Korea', 'name_ar': None, 'aliases': 'DPRK'}]
        return []
    db = FakeDB(answer)
    assert 'DPRK' in E.load_high_risk(db, fresh=True)
    E.load_high_risk(db)
    E.load_high_risk(db)
    assert len(calls) == 1


# ---------------------------------------------------------------- should-fix 11 + nits
def test_negative_refunds_count_by_size_and_are_kept():
    refunds = [tx(80, minutes=i, amount=-200, ttype='REFUND') for i in range(3)]
    assert run('TM014', refunds, refunds[-1], threshold_value=3)
    dq = B.data_quality(refunds, known_customers={80})
    assert not dq['exclude'] and dq['issues']['refund_stored_negative'] == 3
    neg_pay = tx(80, amount=-5)
    assert neg_pay['id'] in B.data_quality([neg_pay], known_customers={80})['exclude']


def test_message_number_format_never_scientific():
    assert E._fmt(2000000) == '2,000,000' and E._fmt(1.5) == '1.50' and E._fmt(24.0) == '24'
    t = tx(81, amount=3000000, ttype='CASH_DEPOSIT')
    assert 'e+' not in run('TM001', [t], t, threshold_value=2000000).description


def test_rule_code_validation():
    from aml import tm_versions as V
    for bad in ('A', 'tm-01', 'X' * 21, 'TM 1'):
        assert not V.CODE_RE.match(bad.strip().upper())
    assert V.CODE_RE.match('TM017') and V.CODE_RE.match('PSP_06')


def test_version_errors_carry_arabic():
    from aml import tm_versions as V
    with pytest.raises(V.VersionError) as e:
        V.clean_parameters('TM002', {'min_count': 'abc'})
    assert V.message(e.value, ar=True) != str(e.value) and V.message(e.value) == str(e.value)


def test_packs_load_and_failures_are_reported(monkeypatch):
    E._PACKS.update(ok=False, tried=None)
    assert E.ensure_packs_loaded() == [] and 'PSP01' in E.RULE_SPECS


# ---------------------------------------------------------------- second review
def test_list_parameters_are_hashable_tuples():
    assert E._types(['a', 'b'], ()) == ('A', 'B')
    assert E._types(None, ['X']) == ('X',) and isinstance(E._types('', ['X']), tuple)
    from packs.psp_tm import rules as P  # noqa: F401
    many = [tx(90, hours=i, ttype='TRANSFER_IN', counterparty_account=f'ACC{i:06d}') for i in range(10)]
    assert run('PSP03', many, many[-1], threshold_value=10, time_period_days=7,
               parameters={'types': ['TRANSFER_IN']})


def test_count_rules_count_zero_amount_transactions():
    assert E.needs('TM003') == {'date'} and E.needs('TM016') == {'date'} and E.needs('TM001') == {'amount'}
    from packs.psp_tm import rules as P  # noqa: F401
    assert E.needs('PSP05') == {'date'}
    zeros = [tx(91, minutes=i, amount=0) for i in range(7)]
    assert run('TM003', zeros, zeros[-1], threshold_value=5)
    dq = B.data_quality(zeros, known_customers={91})
    assert not dq['exclude'] and dq['issues']['amount_zero'] == 7


def test_savepoint_is_skipped_on_autocommit_connections():
    class Raw:
        autocommit = True
    db = FakeDB()
    db._conn = Raw()
    with E.savepoint(db, 'x'):
        db.execute('SELECT 1')
    assert [q for q, _ in db.sql] == ['SELECT 1']
    db2 = FakeDB()
    with pytest.raises(RuntimeError):
        with E.savepoint(db2, 'y'):
            raise RuntimeError('boom')
    assert [q for q, _ in db2.sql] == ['SAVEPOINT y', 'ROLLBACK TO SAVEPOINT y', 'RELEASE SAVEPOINT y']


def test_unsupported_rules_in_force_are_reported():
    assert E.warn_unsupported([rule('NOPE01'), rule('TM001')]) == ['NOPE01']


def test_currency_issues_aggregate_per_day():
    seen = []

    def answer(sql, args):
        if sql.lstrip().startswith('UPDATE tm_monitoring_issues'):
            return [{'id': 1}] if seen else []
        if 'INSERT INTO tm_monitoring_issues' in sql:
            seen.append(args)
        return []
    db = FakeDB(answer)
    for i in range(5):
        assert S.record_issue(db, 100 + i, 'currency_unconverted', 'USD compared unconverted by TM001')
    assert len(seen) == 1


def test_evaluate_does_not_commit_inside(monkeypatch):
    db = FakeDB(lambda sql, args: [])
    monkeypatch.setattr(S, '_evaluate', lambda db, i: [])
    S.evaluate_transaction(1, db, commit=False)
    assert db.commits == 0
    S.evaluate_transaction(1, db)
    assert db.commits == 1


def test_compare_hides_the_diff_of_an_unfinished_run(monkeypatch):
    txs = [tx(92, days=d, amount=60000) for d in range(3)]
    for t in txs:
        t['_ts'] = E.parse_ts(t['transaction_date'])
    r = rule('TM012', threshold_value=50000)
    monkeypatch.setattr(B, '_prepare', lambda db, rules, f, t: (
        txs, {}, B.data_quality(txs, known_customers={92}),
        type('C', (E.Context,), {})()))
    ctx_deadline = __import__('time').monotonic() - 1           # already out of time
    orig = B._prepare

    def prep(db, rules, f, t):
        a, b, c, d = orig(db, rules, f, t)
        d.deadline = ctx_deadline
        return a, b, c, d
    monkeypatch.setattr(B, '_prepare', prep)
    out = B.compare(None, r, E.rule_params(r))
    assert out['current']['truncated'] and 'only_current' not in out
