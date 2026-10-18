"""Unit tests for regcontrols.logic — pure functions, no database."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from regcontrols import logic
from regcontrols.logic import CheckResult, ParameterNotSet


def v(id, lic, start, end=None, value='1', status='active', vt='number'):
    return {'id': id, 'licence_type': lic, 'effective_from': start, 'effective_to': end,
            'value_text': value, 'value_type': vt, 'status': status}


# ---------------------------------------------------------------- parameter lookup
class TestSelectParam:
    rows = [
        v(1, 'all', date(2020, 1, 1), date(2025, 12, 31), '5'),
        v(2, 'all', date(2026, 1, 1), None, '6'),
        v(3, 'microfinance', date(2026, 3, 1), None, '7'),
        v(4, 'microfinance', date(2027, 1, 1), None, '8', status='retired'),
    ]

    def test_specific_licence_beats_all(self):
        assert logic.select_param(self.rows, 'microfinance', date(2026, 6, 1))['id'] == 3

    def test_falls_back_to_all_before_specific_starts(self):
        assert logic.select_param(self.rows, 'microfinance', date(2026, 2, 1))['id'] == 2

    def test_other_licence_uses_all(self):
        assert logic.select_param(self.rows, 'leasing', date(2026, 6, 1))['id'] == 2

    def test_as_of_past_date_uses_old_version(self):
        assert logic.select_param(self.rows, 'all', date(2024, 5, 5))['id'] == 1

    def test_retired_versions_are_ignored(self):
        assert logic.select_param(self.rows, 'microfinance', date(2027, 6, 1))['id'] == 3

    def test_nothing_covers_date(self):
        assert logic.select_param(self.rows, 'all', date(2019, 1, 1)) is None

    def test_accepts_string_dates(self):
        rows = [v(9, 'all', '2026-01-01', '2026-12-31')]
        assert logic.select_param(rows, 'all', '2026-07-01')['id'] == 9
        assert logic.select_param(rows, 'all', '2027-01-01') is None


class TestCoerce:
    def test_numbers_are_decimal(self):
        assert logic.coerce_value('2.5', 'percent') == Decimal('2.5')
        assert logic.coerce_value('1,000,000', 'amount') == Decimal('1000000')

    def test_integer(self):
        assert logic.coerce_value('30', 'integer') == 30

    def test_boolean(self):
        assert logic.coerce_value('true', 'boolean') is True
        assert logic.coerce_value('0', 'boolean') is False

    def test_json(self):
        assert logic.coerce_value('[60, 30, 7]', 'json') == [60, 30, 7]

    def test_empty_raises_not_set(self):
        with pytest.raises(ParameterNotSet):
            logic.coerce_value(None, 'number')
        with pytest.raises(ParameterNotSet):
            logic.coerce_value('  ', 'number')

    def test_malformed_number_is_an_error_not_zero(self):
        with pytest.raises(ValueError):
            logic.coerce_value('ten', 'number')

    def test_validate_value_allows_empty(self):
        assert logic.validate_value('', 'number') is None
        assert logic.validate_value('abc', 'integer')


class TestPlanVersionChange:
    rows = [v(1, 'all', date(2020, 1, 1)), v(2, 'microfinance', date(2026, 1, 1))]

    def test_same_date_updates_in_place(self):
        assert logic.plan_version_change(self.rows, 'all', date(2020, 1, 1)) == ('update', 1, [], None)

    def test_new_date_closes_open_version(self):
        mode, row_id, close, nxt = logic.plan_version_change(self.rows, 'all', date(2026, 7, 1))
        assert (mode, row_id, close, nxt) == ('insert', None, [1], None)

    def test_other_licence_untouched(self):
        _, _, close, _ = logic.plan_version_change(self.rows, 'microfinance', date(2026, 7, 1))
        assert close == [2]

    def test_back_dated_version_ends_before_next(self):
        rows = [v(1, 'all', date(2020, 1, 1), date(2025, 12, 31)), v(2, 'all', date(2026, 1, 1))]
        mode, _, close, nxt = logic.plan_version_change(rows, 'all', date(2024, 1, 1))
        assert mode == 'insert' and close == [1] and nxt == date(2026, 1, 1)


# ---------------------------------------------------------------- results
class TestNormalise:
    def test_shapes(self):
        assert logic.normalise_result(True).status == 'pass'
        assert logic.normalise_result(False).status == 'fail'
        assert logic.normalise_result('warning').status == 'warning'
        r = logic.normalise_result(('fail', '2 loans', [{'id': 1}, {'id': 2}]))
        assert (r.status, r.summary, r.affected_count) == ('fail', '2 loans', 2)
        r = logic.normalise_result({'status': 'PASS', 'summary': 'ok', 'details': 'text'})
        assert r.status == 'pass' and r.details == {'text': 'text'}

    def test_unknown_status_is_error(self):
        assert logic.normalise_result('green').status == 'error'
        assert logic.normalise_result(42).status == 'error'

    def test_affected_is_capped_but_counted(self):
        r = logic.normalise_result(CheckResult('fail', 'many', affected=list(range(1200))))
        assert r.affected_count == 1200
        assert len(r.affected) == logic.MAX_AFFECTED_STORED
        assert r.details['affected_truncated'] is True
        assert r.affected[0] == {'label': '0'}

    def test_non_json_values_become_strings(self):
        r = logic.normalise_result(CheckResult('fail', 'x', affected=[{'d': date(2026, 1, 1)}]))
        assert r.affected[0]['d'] == '2026-01-01'

    def test_worst_status(self):
        assert logic.worst_status(['pass', 'warning', 'fail']) == 'fail'
        assert logic.worst_status(['pass', 'no_check']) == 'no_check'
        assert logic.worst_status([]) == 'no_check'


def test_next_due():
    t = datetime(2026, 1, 31, 10, 0)
    assert logic.next_due('daily', t) == datetime(2026, 2, 1, 10, 0)
    assert logic.next_due('monthly', t) == datetime(2026, 2, 28, 10, 0)
    assert logic.next_due('quarterly', t) == datetime(2026, 4, 30, 10, 0)
    assert logic.next_due('event', t) is None
    assert logic.next_due('on_demand', t) is None


# ---------------------------------------------------------------- evidence
class TestEvidence:
    today = date(2026, 6, 1)

    def item(self, status='approved', valid_to=None, valid_from=None):
        return {'status': status, 'valid_to': valid_to, 'valid_from': valid_from}

    def test_states(self):
        e = self.item
        assert logic.evidence_state(e(valid_to=date(2027, 1, 1)), self.today, 30) == 'valid'
        assert logic.evidence_state(e(valid_to=date(2026, 6, 20)), self.today, 30) == 'expiring'
        assert logic.evidence_state(e(valid_to=date(2026, 5, 31)), self.today, 30) == 'expired'
        assert logic.evidence_state(e(valid_to=None), self.today, 30) == 'valid'
        assert logic.evidence_state(e(status='pending'), self.today, 30) == 'pending'
        assert logic.evidence_state(e(valid_from=date(2026, 7, 1)), self.today, 30) == 'pending'

    def test_check_result(self):
        e = self.item
        assert logic.evidence_check_result([], self.today).status == 'fail'
        assert logic.evidence_check_result([e(valid_to=date(2026, 5, 1))], self.today).status == 'fail'
        assert logic.evidence_check_result([e(status='pending')], self.today).status == 'warning'
        assert logic.evidence_check_result([e(valid_to=date(2026, 6, 10))], self.today, 30).status == 'warning'
        res = logic.evidence_check_result([e(valid_to=date(2026, 6, 10)), e(valid_to=date(2028, 1, 1))], self.today)
        assert res.status == 'pass' and res.details['valid'] == 1


# ---------------------------------------------------------------- findings & recurrence
class TestRecurrence:
    findings = [
        {'id': 1, 'status': 'closed', 'closure_type': 'remediated'},
        {'id': 2, 'status': 'in_progress'},
        {'id': 3, 'status': 'closed', 'closure_type': 'not_applicable'},
        {'id': 4, 'status': 'closed', 'closure_type': None},
    ]

    def test_closed_finding_reopens_when_control_fails_again(self):
        actions = dict(logic.recurrence_actions(self.findings, 'fail'))
        assert actions[1] == 'reopen_repeat'
        assert actions[4] == 'reopen_repeat'  # legacy rows without closure_type count as remediated

    def test_open_finding_only_records_still_failing(self):
        assert dict(logic.recurrence_actions(self.findings, 'fail'))[2] == 'still_failing'

    def test_not_applicable_closure_never_reopens(self):
        assert 3 not in dict(logic.recurrence_actions(self.findings, 'fail'))

    @pytest.mark.parametrize('status', ['pass', 'warning', 'error', 'no_check', 'not_applicable'])
    def test_only_a_real_failure_triggers(self, status):
        assert logic.recurrence_actions(self.findings, status) == []


def test_verification_outcome():
    assert logic.verification_outcome(['pass', 'pass']) == 'verified'
    assert logic.verification_outcome(['pass', 'fail']) == 'failed'
    assert logic.verification_outcome(['pass', 'error']) == 'failed'
    assert logic.verification_outcome(['pass', 'warning']) == 'inconclusive'
    assert logic.verification_outcome(['no_check']) == 'manual'
    assert logic.verification_outcome([]) == 'manual'
    assert logic.verification_outcome(['pass', 'no_check']) == 'verified'


def test_ageing_and_overdue():
    today = date(2026, 6, 1)
    assert logic.age_bucket(date(2026, 5, 20), today) == '0-30'
    assert logic.age_bucket(date(2026, 4, 1), today) == '61-90'
    assert logic.age_bucket(date(2025, 1, 1), today) == '90+'
    assert logic.is_overdue(date(2026, 5, 31), 'open', today)
    assert not logic.is_overdue(date(2026, 5, 31), 'open', today, grace_days=5)
    assert not logic.is_overdue(date(2026, 5, 1), 'closed', today)
    assert not logic.is_overdue(None, 'open', today)


# ---------------------------------------------------------------- alerts
def test_escalation_due():
    now = datetime(2026, 6, 10, 9, 0)
    base = {'status': 'open', 'raised_at': now - timedelta(days=5), 'escalated_at': None}
    assert logic.escalation_due(base, now, 5)
    assert not logic.escalation_due(base, now, 6)
    assert logic.escalation_due(dict(base, status='acknowledged'), now, 5)
    assert not logic.escalation_due(dict(base, escalated_at=now), now, 5)
    assert not logic.escalation_due(dict(base, status='resolved'), now, 5)


def test_renotify_due():
    now = datetime(2026, 6, 10)
    a = {'status': 'open', 'raised_at': now - timedelta(days=10), 'last_notified_at': now - timedelta(days=1)}
    assert not logic.renotify_due(a, now, 3)
    assert logic.renotify_due(dict(a, last_notified_at=now - timedelta(days=3)), now, 3)
    assert not logic.renotify_due(dict(a, status='acknowledged', last_notified_at=None), now, 3)


# ---------------------------------------------------------------- CSV import
def test_parse_findings_csv_happy_path():
    text = ('﻿title,severity,source,control_codes,due_date,owner_email\n'
            'Register incomplete,high,regulator,fra-035; FRA-036,2026-03-31,Owner@Example.com\n'
            ',,,,,\n')
    rows, errors = logic.parse_findings_csv(text, ['FRA-035', 'FRA-036'])
    assert errors == []
    assert rows[0]['control_codes'] == ['FRA-035', 'FRA-036']
    assert rows[0]['due_date'] == date(2026, 3, 31)
    assert rows[0]['owner_email'] == 'owner@example.com'


def test_parse_findings_csv_errors():
    text = 'title,severity,source,control_codes,due_date\n,urgent,press,FRA-999,31/03/2026\n'
    rows, errors = logic.parse_findings_csv(text, ['FRA-035'])
    assert rows == []
    msgs = ' '.join(m for _, m in errors)
    for part in ('title is required', 'severity', 'source', 'FRA-999', 'YYYY-MM-DD'):
        assert part in msgs
    assert all(line == 2 for line, _ in errors)


def test_parse_findings_csv_missing_title_column():
    assert logic.parse_findings_csv('name\nx\n')[1] == [(1, 'missing required column "title"')]


def test_csv_template_parses():
    rows, errors = logic.parse_findings_csv(logic.findings_csv_template(), ['FRA-035', 'FRA-036'])
    assert not errors and len(rows) == 1
