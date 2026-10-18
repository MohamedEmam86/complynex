"""Lending conduct logic — worked examples, no database."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from packs.fra_nbfi.lending import logic
from packs.fra_nbfi.lending.importer import RowError, _clean
import pytest

D = Decimal


# ---------------------------------------------------------------- file completeness
def full_file():
    loan = {'amount': 50000, 'gps_lat': 30.0, 'gps_lng': 31.2}
    contract = {'signed_by_lender': True, 'lender_signed_at': date(2026, 1, 1), 'signed_by_client': True,
                'client_signed_at': date(2026, 1, 1)}
    docs = [{'doc_type': t} for t in ('national_id', 'contract', 'receipt_acknowledgement', 'credit_study')]
    study = {'monthly_revenue': 1, 'monthly_costs_total': 1, 'household_expenses': 1, 'other_debt_service': 0,
             'net_income': 1, 'cost_lines': [{}, {}, {}]}
    return loan, contract, docs, study


def codes(gaps):
    return {g[1] for g in gaps}


def test_complete_file_has_no_gaps():
    loan, c, d, s = full_file()
    assert logic.file_gaps(loan, contract=c, documents=d, study=s, product_docs=['national_id'],
                           gps_min_amount=30000, min_cost_lines=3) == []


def test_each_gap_is_reported():
    loan, c, d, s = full_file()
    loan.update(gps_lat=None)
    c.update(signed_by_client=False)
    d = [x for x in d if x['doc_type'] != 'receipt_acknowledgement']
    s.update(net_income=None, cost_lines=[{}])
    gaps = logic.file_gaps(loan, contract=c, documents=d, study=s, product_docs=['guarantor_id'],
                           gps_min_amount=30000, min_cost_lines=3)
    assert codes(gaps) == {'gps_missing', 'client_signature', 'receipt_ack', 'study_fields', 'study_cost_lines',
                           'doc_guarantor_id'}
    assert {g[0] for g in gaps} == {'FRA-009', 'FRA-013', 'FRA-014', 'FRA-015'}


def test_gps_only_above_threshold_and_only_when_configured():
    loan, c, d, s = full_file()
    loan.update(amount=20000, gps_lat=None)
    assert logic.file_gaps(loan, contract=c, documents=d, study=s, gps_min_amount=30000) == []
    loan.update(amount=90000)
    assert 'gps_missing' not in codes(logic.file_gaps(loan, contract=c, documents=d, study=s, gps_min_amount=None))


def test_missing_contract_and_study():
    loan, _, d, _ = full_file()
    assert {'contract_missing', 'study_missing'} <= codes(logic.file_gaps(loan, documents=d))


# ---------------------------------------------------------------- eligibility
def test_eligibility():
    c = {'monthly_revenue': '60000', 'project_size': '100000'}
    assert logic.eligibility_breaches(c, max_monthly_revenue=50000, max_project_size=500000) == \
        [('monthly_revenue', D('60000'), D('50000'))]
    assert logic.eligibility_breaches(c) == []


# ---------------------------------------------------------------- QA anomalies
def study(loan_id, officer, rev, cost, hh, lines=3):
    return {'loan_id': loan_id, 'officer_code': officer, 'monthly_revenue': rev, 'monthly_costs_total': cost,
            'household_expenses': hh, 'cost_lines': [{'label': str(i), 'amount': 123 + i} for i in range(lines)]}


def test_identical_figures_same_officer_only():
    s = [study(1, 'A', 20150, 11030, 3020), study(2, 'A', 20150, 11030, 3020), study(3, 'B', 20150, 11030, 3020)]
    f = logic.study_anomalies(s)
    assert [x[0] for x in f[1]] == ['identical_figures'] and 3 not in f


def test_round_numbers_and_few_lines():
    s = [{'loan_id': 9, 'officer_code': 'A', 'monthly_revenue': 20000, 'monthly_costs_total': 10000,
          'household_expenses': 3000, 'cost_lines': [{'label': 'stock', 'amount': 10000}]}]
    flags = {x[0] for x in logic.study_anomalies(s, min_cost_lines=3)[9]}
    assert flags == {'round_numbers', 'few_cost_lines'}


def test_ratio_outlier():
    s = [study(i, 'A', 10000 + i * 37, 5000 + i * 11, 2000 + i) for i in range(1, 8)]
    s.append(study(99, 'A', 10000, 9900, 2100))
    f = logic.study_anomalies(s)
    assert any(x[0] == 'ratio_outlier' for x in f[99])


# ---------------------------------------------------------------- fees
def test_admin_fee_cap_and_tiers():
    tiers = [{'max_amount': 20000, 'cap_pct': 3}, {'max_amount': None, 'cap_pct': 2}]
    assert logic.tier_cap_pct(15000, tiers) == D('3')
    assert logic.tier_cap_pct(40000, tiers) == D('2')
    # 40,000 at 2.5% = 1,000; tier allows 800 -> over by 200; flat 3% cap allows 1,200
    loan = {'amount': 40000, 'admin_fee_amount': 1000}
    assert logic.admin_fee_breach(loan, cap_pct=3) is None
    assert logic.admin_fee_breach(loan, tiers=tiers) == (D('200.00'), D('800.00'), 'tier')
    assert logic.admin_fee_breach(loan, cap_pct=3, tiers=tiers)[2] == 'tier'
    assert logic.admin_fee_breach(loan) is None


def test_late_penalty_formula():
    # 1,000 overdue, 2% per started month, cap 10%: 45 days -> 2 months -> 40
    assert logic.max_late_penalty(1000, 45, 2, 10) == D('40.00')
    # 400 days -> 14 months -> 280, capped at 100
    assert logic.max_late_penalty(1000, 400, 2, 10) == D('100.00')
    assert logic.max_late_penalty(1000, 0, 2, 10) == D('0')
    inst = {'penalty_charged': 900, 'due_date': date(2026, 1, 1), 'paid_date': date(2026, 1, 21),
            'principal_due': 833.33, 'interest_due': 200}
    over, allowed = logic.penalty_overcharge(inst, 2, 10)
    assert allowed == D('20.67') and over == D('879.33')


def test_flat_fee_caps():
    assert logic.flat_fee_overcharge(600, 250) == (D('350.00'), D('250.00'))
    assert logic.flat_fee_overcharge(100, 250) is None


# ---------------------------------------------------------------- early repayment
def test_disclosure_numbers():
    rem = [{'principal_due': 1000, 'interest_due': 200, 'fees_due': 0}] * 3
    d = logic.early_repayment_disclosure(rem, 3000, 100)
    assert d['original_remaining_cost'] == D('3600.00')
    assert d['new_total_cost'] == D('3100.00')
    assert d['client_saving'] == D('500.00')
    assert '3600.00' in logic.disclosure_text(d) and '3600.00' in logic.disclosure_text(d, 'ar')


def test_costlier_refinance_detection():
    er = {'id': 1, 'loan_id': 10, 'status': 'executed', 'executed_at': datetime(2026, 3, 1, 10)}
    old = {'id': 10, 'client_id': 5, 'apr_pct': 32, 'amount': 10000, 'admin_fee_amount': 200}
    new = {'id': 11, 'client_id': 5, 'apr_pct': 41, 'disbursement_date': date(2026, 3, 13), 'amount': 20000}
    late = {'id': 12, 'client_id': 5, 'apr_pct': 45, 'disbursement_date': date(2026, 5, 1)}
    cheaper = {'id': 13, 'client_id': 5, 'apr_pct': 30, 'disbursement_date': date(2026, 3, 5)}
    other = {'id': 14, 'client_id': 6, 'apr_pct': 50, 'disbursement_date': date(2026, 3, 5)}
    hits = logic.costlier_refinance([er], [old, new, late, cheaper, other], 30)
    assert [(h['new_loan_id'], h['days']) for h in hits] == [(11, 12)]
    assert logic.costlier_refinance([dict(er, status='consented')], [old, new], 30) == []


def test_costlier_by_fee_when_no_apr():
    er = {'id': 1, 'loan_id': 10, 'status': 'executed', 'executed_at': date(2026, 3, 1)}
    old = {'id': 10, 'client_id': 5, 'amount': 10000, 'admin_fee_amount': 200}
    new = {'id': 11, 'client_id': 5, 'amount': 10000, 'admin_fee_amount': 400, 'application_date': date(2026, 3, 2)}
    assert 'admin fee' in logic.costlier_refinance([er], [old, new], 30)[0]['reason']


# ---------------------------------------------------------------- portfolio
def test_days_past_due():
    today = date(2026, 6, 30)
    inst = [{'due_date': date(2026, 5, 1), 'status': 'paid', 'paid_amount': 100, 'principal_due': 100, 'interest_due': 0},
            {'due_date': date(2026, 6, 1), 'status': 'due', 'paid_amount': 0, 'principal_due': 100, 'interest_due': 0}]
    assert logic.days_past_due(inst, today) == 29
    assert logic.days_past_due([], today, fallback=45) == 45


def test_portfolio_metrics_and_par():
    loans = [{'outstanding_principal': 1000, 'dpd': 0, 'branch_code': 'A'},
             {'outstanding_principal': 500, 'dpd': 45, 'branch_code': 'A'},
             {'outstanding_principal': 500, 'dpd': 100, 'branch_code': 'B'}]
    m = logic.portfolio_metrics(loans)
    assert m['par'][30] == D('50.00') and m['par'][90] == D('25.00') and m['par'][120] == D('0')
    assert m['buckets']['31-60']['count'] == 1 and m['buckets']['91-120']['amount'] == D('500')
    by = logic.par_by(loans, 'branch_code')
    assert by['B']['par'][90] == D('100.00')
    assert logic.trend(D('7.5'), D('5')) == D('2.50') and logic.trend(1, None) is None


def test_visit_gaps():
    today = date(2026, 6, 30)
    loans = [{'id': 1, 'status': 'disbursed', 'disbursement_date': date(2026, 5, 1)},
             {'id': 2, 'status': 'disbursed', 'disbursement_date': date(2026, 5, 1)},
             {'id': 3, 'status': 'disbursed', 'disbursement_date': date(2026, 6, 20)}]
    visits = [{'id': 7, 'loan_id': 1, 'visit_date': date(2026, 5, 20)},
              {'id': 8, 'loan_id': 2, 'visit_date': date(2026, 6, 25)},
              {'id': 9, 'loan_id': 3, 'planned_date': date(2026, 6, 25)}]
    missing, overdue = logic.visit_gaps(loans, visits, 30, today)
    assert [l['id'] for l, _ in missing] == [2]  # visited only after the 30-day window
    assert [v['id'] for v in overdue] == [9]


# ---------------------------------------------------------------- import validation
def test_import_clean_types_and_errors():
    r = _clean('loans', {'loan_ref': 'L1', 'client_ref': 'C1', 'amount': '1,000', 'disbursement_date': '2026-01-05',
                         'tenor_months': '12', 'status': 'disbursed'})
    assert r['amount'] == D('1000') and r['disbursement_date'] == date(2026, 1, 5) and r['tenor_months'] == 12
    with pytest.raises(RowError, match='amount is required'):
        _clean('loans', {'loan_ref': 'L1', 'client_ref': 'C1'})
    with pytest.raises(RowError, match='YYYY-MM-DD'):
        _clean('loans', {'loan_ref': 'L1', 'client_ref': 'C1', 'amount': 1, 'disbursement_date': '05/01/2026'})
    with pytest.raises(RowError, match='status'):
        _clean('loans', {'loan_ref': 'L1', 'client_ref': 'C1', 'amount': 1, 'status': 'paid'})
    assert _clean('contracts', {'loan_ref': 'L1', 'signed_by_client': 'نعم'})['signed_by_client'] is True
