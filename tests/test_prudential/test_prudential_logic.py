"""Unit tests for prudential.logic — pure functions, no database."""
from datetime import date
from decimal import Decimal

from prudential import logic


def ev(t, amount, d, i=0):
    return {'capital_type': t, 'amount': amount, 'effective_date': d, 'id': i}


class TestCapital:
    events = [ev('authorised', 50, date(2024, 1, 1)), ev('issued', 20, date(2024, 1, 1)),
              ev('paid_up', 10, date(2024, 1, 1)), ev('registered', 10, date(2024, 2, 1)),
              ev('paid_up', 15, date(2026, 9, 1))]

    def test_latest_level_as_of(self):
        assert logic.capital_levels(self.events, date(2026, 1, 1))['paid_up']['amount'] == 10
        assert logic.capital_levels(self.events, date(2026, 10, 1))['paid_up']['amount'] == 15

    def test_issues(self):
        codes = [c for c, _ in logic.capital_issues(logic.capital_levels(self.events, date(2026, 10, 1)), 20)]
        assert codes == ['below_minimum', 'not_registered']

    def test_ok(self):
        assert logic.capital_issues(logic.capital_levels(self.events, date(2026, 1, 1)), 10) == []

    def test_no_paid_up(self):
        assert logic.capital_issues({}, 1)[0][0] == 'no_paid_up'


class TestDeadlines:
    def test_state(self):
        t = date(2026, 10, 1)
        assert logic.deadline_state({'status': 'open', 'due_date': date(2026, 9, 30)}, t) == 'overdue'
        assert logic.deadline_state({'status': 'open', 'due_date': date(2026, 10, 20)}, t) == 'due_soon'
        assert logic.deadline_state({'status': 'open', 'due_date': date(2027, 1, 1)}, t) == 'ok'
        assert logic.deadline_state({'status': 'met', 'due_date': date(2026, 1, 1)}, t) == 'met'

    def test_thresholds(self):
        assert logic.thresholds_to_send(25, [60, 30, 7], [60]) == [30]
        assert logic.thresholds_to_send(5, [60, 30, 7], []) == [60, 30, 7]
        assert logic.thresholds_to_send(90, [60, 30, 7], []) == []

    def test_board_escalation(self):
        t = date(2026, 10, 1)
        assert logic.needs_board_escalation({'status': 'open', 'due_date': date(2026, 10, 5)}, t)
        assert not logic.needs_board_escalation({'status': 'open', 'due_date': date(2026, 10, 30)}, t)
        assert not logic.needs_board_escalation({'status': 'open', 'due_date': date(2026, 9, 1),
                                                 'board_escalated_at': date(2026, 9, 2)}, t)


class TestSolvency:
    def test_ratios(self):
        r = logic.ratios({'total_assets': 100, 'total_liabilities': 80})
        assert r['equity'] == 20 and r['leverage'] == Decimal('4.00') and r['equity_to_assets_pct'] == Decimal('20.00')

    def test_negative_equity_is_critical(self):
        b = logic.solvency_breaches({'total_assets': 100, 'total_liabilities': 120}, max_leverage=7, min_equity=0)
        assert ('equity', Decimal(-20), Decimal(0), 'critical') in b

    def test_leverage_breach(self):
        b = logic.solvency_breaches({'equity': 10, 'total_liabilities': 90}, max_leverage=7, min_equity=0)
        assert b == [('leverage', Decimal('9.00'), Decimal(7), 'high')]


class TestAddress:
    reg = '12 Example Street, Nasr City, Cairo'

    def test_variants_match(self):
        assert logic.address_matches('12 example st. nasr city - cairo', self.reg)
        assert logic.address_matches('١٢ شارع المثال، مدينة نصر', '12 شارع المثال، مدينه نصر، القاهرة')

    def test_mismatch(self):
        assert not logic.address_matches('5 Old Demo Road, Dokki, Giza', self.reg)

    def test_alias(self):
        assert logic.address_matches('Tower B, Demo Plaza', self.reg, ['Tower B, Demo Plaza'])

    def test_same_party(self):
        assert logic.same_party('Delta Demo Holdings S.A.E.', 'delta demo holdings')
        assert not logic.same_party('Omar Demo', 'Delta Demo Holdings')


class TestKeyFunctionsBranches:
    def test_key_function_issues(self):
        t = {'is_required': True, 'notify_regulator': True, 'needs_no_objection': True}
        assert logic.key_function_issues(t, None)[0][0] == 'vacant'
        codes = {c for c, _ in logic.key_function_issues(t, {'fit_proper_status': 'passed', 'no_objection_status': 'pending'})}
        assert codes == {'not_notified', 'no_objection_pending'}
        assert logic.key_function_issues(dict(t, is_required=False), None) == []

    def test_branch_vacancy(self):
        b = {'status': 'active', 'manager_vacant_since': date(2026, 8, 1)}
        assert logic.branch_issues(b, date(2026, 8, 31), 60)[0][0] == 'vacancy_within_limit'
        assert logic.branch_issues(b, date(2026, 10, 31), 60)[0][0] == 'no_manager'
        assert logic.branch_issues({'status': 'active', 'manager_name': 'X', 'manager_no_objection': 'pending'})[0][0] == \
            'no_objection_missing'

    def test_staffing(self):
        gaps = logic.staffing_gaps([{'id': 1, 'status': 'active'}], [{'code': 'lo'}], {(1, 'lo'): 2}, {'lo': 3})
        assert [(g[2], g[3]) for g in gaps] == [(2, 3)]


class TestFacilities:
    def test_expected_accrual(self):
        assert logic.expected_accrual(36500, 10, date(2026, 1, 1), date(2026, 1, 11)) == Decimal('100.00')

    def test_gap(self):
        f = {'status': 'performing', 'balance': 36500, 'interest_rate_pct': 10, 'accrual_from': date(2026, 1, 1),
             'booked_as_of': date(2026, 1, 11), 'accrued_booked': 50}
        assert logic.accrual_gap(f, 5)['breach'] and not logic.accrual_gap(dict(f, accrued_booked=98), 5)['breach']

    def test_confirmation(self):
        f = {'status': 'performing', 'last_confirmation_date': date(2026, 1, 1)}
        assert 'old' in logic.confirmation_issue(f, date(2026, 6, 1), 90)
        assert logic.confirmation_issue(dict(f, last_confirmation_date=None), date(2026, 6, 1), 90)

    def test_status(self):
        assert logic.facility_status_issues({'status': 'default'})
        assert not logic.facility_status_issues({'status': 'default', 'board_escalated_on': date(2026, 1, 1)})
        assert logic.facility_status_issues({'status': 'rescheduled'})


class TestRelatedPartiesStudies:
    def test_rp_items(self):
        party = {'name': 'Delta Demo Holdings', 'relation': 'shareholder'}
        it = {'item_type': 'capital_contribution', 'payer_name': 'Omar Demo'}
        assert len(logic.rp_item_issues(it, party, False)) == 2
        assert logic.rp_item_issues(dict(it, explanation='paid on behalf, letter attached'), party, True) == []
        ex = {'name': 'K', 'relation': 'exiting_shareholder'}
        assert logic.rp_item_issues({'item_type': 'dues', 'classification': 'equity'}, ex, True)

    def test_study(self):
        t = date(2026, 10, 1)
        assert logic.study_issue([], t) == 'no approved study'
        s = {'status': 'approved', 'approved_on': date(2025, 1, 1), 'next_refresh_date': date(2026, 1, 1)}
        assert 'refresh' in logic.study_issue([s], t)
        assert logic.study_issue([dict(s, next_refresh_date=date(2027, 1, 1))], t) is None
