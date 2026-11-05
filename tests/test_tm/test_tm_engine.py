"""TM rule engine and backtest (Phase 7, TM-G1..G4): pure tests, no database."""
from datetime import datetime, timedelta

import pytest

from aml import tm_engine as E
from aml import tm_backtest as B

T0 = datetime(2025, 6, 1, 10, 0, 0)
_id = [0]


def tx(cust, days=0, hours=0, minutes=0, amount=1000, ttype='PAYMENT', **kw):
    _id[0] += 1
    d = dict(id=_id[0], customer_id=cust, amount=amount, transaction_type=ttype, currency='EGP',
             transaction_date=(T0 + timedelta(days=days, hours=hours, minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S'))
    d.update(kw)
    return d


def rule(code, **kw):
    r = {'id': hash(code) % 1000, 'rule_code': code, 'version': 1}
    r.update(kw)
    return r


def run(code, txs, target, ctx=None, cust=None, **rule_kw):
    h = E.History(txs)
    return E.evaluate(rule(code, **rule_kw), target, h, cust or {}, ctx or E.Context())


# ---------------------------------------------------------------- boundaries (the comparison is explicit)
@pytest.mark.parametrize('amount,fires', [(9999, False), (10000, True), (10001, True)])
def test_cash_threshold_is_inclusive(amount, fires):
    t = tx(1, amount=amount, ttype='CASH_DEPOSIT')
    assert bool(run('TM001', [t], t, threshold_value=10000)) is fires


@pytest.mark.parametrize('n,fires', [(5, False), (6, True)])
def test_velocity_is_strictly_more_than(n, fires):
    txs = [tx(2, minutes=i) for i in range(n)]
    assert bool(run('TM003', txs, txs[-1], threshold_value=5)) is fires


def test_windows_anchor_on_the_transaction_date_not_now():
    # a history from last year still fires (old code compared with "now")
    txs = [tx(3, minutes=i) for i in range(7)]
    assert run('TM003', txs, txs[-1], threshold_value=5)


def test_no_look_ahead():
    txs = [tx(4, minutes=i) for i in range(7)]
    assert not run('TM003', txs, txs[0], threshold_value=5)   # the later ones are not seen yet


def test_structuring_band_is_below_the_threshold():
    a = [tx(5, hours=i, amount=8000, ttype='CASH_DEPOSIT') for i in range(3)]
    assert run('TM002', a, a[-1], threshold_value=9000, time_period_days=3)
    b = [tx(6, hours=i, amount=9500, ttype='CASH_DEPOSIT') for i in range(3)]   # above the threshold: not structuring
    assert not run('TM002', b, b[-1], threshold_value=9000, time_period_days=3)


def test_dormant_needs_prior_history_and_a_quiet_period():
    new = tx(7, amount=9000)
    assert not run('TM006', [new], new, threshold_value=5000, time_period_days=90)   # new customer, not dormant
    old, back = tx(8, days=-200, amount=10), tx(8, amount=9000)
    assert run('TM006', [old, back], back, threshold_value=5000, time_period_days=90)
    recent = tx(8, days=-10, amount=10)
    assert not run('TM006', [old, recent, back], back, threshold_value=5000, time_period_days=90)


def test_round_trip_both_directions():
    i, o = tx(9, amount=50000, ttype='TRANSFER_IN'), tx(9, hours=3, amount=49000, ttype='TRANSFER_OUT')
    assert run('TM007', [i, o], o)
    o2 = tx(10, amount=50000, ttype='TRANSFER_OUT'); i2 = tx(10, hours=2, amount=50100, ttype='TRANSFER_IN')
    assert run('TM007', [o2, i2], i2)
    far = tx(11, amount=50000, ttype='TRANSFER_IN'); late = tx(11, hours=30, amount=50000, ttype='TRANSFER_OUT')
    assert not run('TM007', [far, late], late)


def test_high_risk_country_from_context():
    t = tx(12, counterparty_country='Iran')
    assert run('TM004', [t], t, ctx=E.Context({'IR', 'Iran'}))
    assert not run('TM004', [t], t, ctx=E.Context({'KP'}))


def test_international_transfers_exclude_home_country():
    txs = [tx(13, hours=i, ttype='TRANSFER_OUT', counterparty_country='Egypt') for i in range(8)]
    assert not run('TM010', txs, txs[-1], threshold_value=5, time_period_days=7)
    txs = [tx(14, hours=i, ttype='TRANSFER_OUT', counterparty_country='Turkey') for i in range(6)]
    assert run('TM010', txs, txs[-1], threshold_value=5, time_period_days=7)


def test_card_rules_follow_the_card_across_customers():
    card = '5123456789012345'
    txs = [tx(100 + i, minutes=i, counterparty_account=card, counterparty_name=f'Shop {i}') for i in range(3)]
    assert run('TM011', txs, txs[-1], threshold_value=3)


def test_volume_against_expected_income():
    txs = [tx(15, days=-i, amount=10000) for i in range(5)]
    assert run('TM008', txs, txs[0], cust={'annual_income_range': '<50K'}, threshold_value=3, time_period_days=30)


def test_parameters_json_overrides_defaults():
    a = [tx(16, hours=i, amount=8000, ttype='CASH_DEPOSIT') for i in range(2)]
    assert not run('TM002', a, a[-1], threshold_value=9000)
    assert run('TM002', a, a[-1], threshold_value=9000, parameters='{"min_count": 2}')


def test_pack_rule_registration():
    E.register_rule('ZZ01', {'op': '>=', 'params': {'threshold': E._p(1, 'count', 'x', 'x')}},
                    lambda t, h, c, p, ctx: E.Hit('ZZ01', 'x'))
    t = tx(17)
    assert run('ZZ01', [t], t)


# ---------------------------------------------------------------- data quality + backtest replay
def test_data_quality_flags_and_excludes():
    good = tx(20, amount=500, transaction_reference='R1')
    dup_ref = tx(20, amount=700, transaction_reference='R1')
    dup = tx(20, minutes=0, amount=600)
    dup2 = dict(dup, id=dup['id'] + 1000)
    rep = tx(20, minutes=1, amount=600)
    bad = tx(None, amount=0)
    noday = dict(tx(21), transaction_date='not a date')
    dq = B.data_quality([good, dup_ref, dup, dup2, rep, bad, noday], known_customers={20, 21})
    assert dq['issues']['duplicate_reference'] == 1 and dq['issues']['duplicate_likely'] == 1
    assert {dup_ref['id'], dup2['id'], bad['id'], noday['id']} <= dq['exclude'] and good['id'] not in dq['exclude']
    assert dq['issues']['repeat_within_2_minutes'] == 1 and rep['id'] not in dq['exclude']


def test_replay_groups_like_live_monitoring():
    txs = [tx(30, hours=i, amount=60000) for i in range(3)]          # 3 large payments within 24 h
    txs += [tx(30, days=3, amount=60000)]                             # a new day, a new alert
    r = rule('TM012', threshold_value=50000)
    res = B.replay([r], txs, {}, E.Context())[r['id']]
    assert res['hits'] == 4 and res['alerts'] == 2 and res['customers'] == 1


def test_replay_period_filter_and_unknown_rule():
    txs = [tx(31, days=d, amount=60000) for d in (0, 10)]
    r = rule('TM012', threshold_value=50000)
    day = (T0 + timedelta(days=10)).strftime('%Y-%m-%d')
    assert B.replay([r], txs, {}, E.Context(), date_from=day)[r['id']]['alerts'] == 1
    assert B.replay([rule('NOPE')], txs, {}, E.Context())[rule('NOPE')['id']] == {'supported': False}


def test_sweep_values():
    vals = B.default_sweep_values(rule('TM003', threshold_value=5))
    assert 5 in vals and 4 in vals and 6 in vals and min(vals) >= 1
    assert 10000 in B.default_sweep_values(rule('TM001', threshold_value=10000))


def test_lookback_no_longer_loads_a_year_for_the_dormant_rule():
    # B3: the "activity before the quiet period" is one database question, not 455 days of rows
    assert E.max_lookback_days([rule('TM006', time_period_days=90)]) == 90
    assert E.max_lookback_days([rule('TM003', parameters='{"hours": 48}')]) == 2


# ---------------------------------------------------------------- versions (pure helpers)
def test_clean_parameters_types_and_unknown_keys():
    from aml import tm_versions as V
    out = V.clean_parameters('TM002', {'min_count': '4', 'band_low': '0.6', 'cash_types': 'cash_deposit, deposit',
                                       'nonsense': 1, 'threshold': 5})
    assert out == {'min_count': 4, 'band_low': 0.6, 'cash_types': ['CASH_DEPOSIT', 'DEPOSIT']}
    with pytest.raises(V.VersionError):
        V.clean_parameters('TM002', {'min_count': 'abc'})
    with pytest.raises(V.VersionError):
        V.clean_parameters('TM002', {'band_low': '-1'})


def test_diff_between_versions():
    from aml import tm_versions as V
    a = rule('TM001', threshold_value=10000, severity='HIGH')
    b = rule('TM001', threshold_value=12000, severity='HIGH')
    assert ('threshold', 10000.0, 12000.0) in V.diff(a, b)


# ---------------------------------------------------------------- PSP pack
def test_psp_pack_rules():
    from packs.psp_tm import rules as P
    ins = [tx(40, hours=i, amount=8500, ttype='CASH_IN') for i in range(3)]
    assert run('PSP01', ins, ins[-1], threshold_value=10000, time_period_days=3)
    flow = [tx(41, amount=30000, ttype='TRANSFER_IN'), tx(41, hours=5, amount=26000, ttype='TRANSFER_OUT')]
    assert run('PSP02', flow, flow[-1], threshold_value=20000)
    many = [tx(42, hours=i, ttype='TRANSFER_IN', counterparty_account=f'ACC{i:06d}') for i in range(10)]
    assert run('PSP03', many, many[-1], threshold_value=10, time_period_days=7)
    assert not run('PSP03', many[:9], many[8], threshold_value=10, time_period_days=7)
    assert {r['rule_code'] for r in P.RULES} == set(P.SPECS)
