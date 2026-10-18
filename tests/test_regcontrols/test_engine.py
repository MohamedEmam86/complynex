"""Control engine: registry, check execution and parameter lookup (no database)."""
from datetime import date

import pytest

from regcontrols import engine, params
from regcontrols.logic import CheckResult, ParameterNotFound, ParameterNotSet


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeParamDB:
    """Answers params.get_versions() from an in-memory list."""

    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, args=()):
        assert 'FROM rc_parameters' in sql
        return FakeCursor([r for r in self.rows if r['param_key'] == args[0]])


PARAM_ROWS = [
    {'id': 1, 'param_key': 'lending.admin_fee_cap_pct', 'licence_type': 'all', 'value_text': '3',
     'value_type': 'percent', 'effective_from': date(2020, 1, 1), 'effective_to': None, 'status': 'active'},
    {'id': 2, 'param_key': 'lending.admin_fee_cap_pct', 'licence_type': 'microfinance', 'value_text': '2.5',
     'value_type': 'percent', 'effective_from': date(2026, 1, 1), 'effective_to': None, 'status': 'active'},
    {'id': 3, 'param_key': 'capital.min_paid_up', 'licence_type': 'microfinance', 'value_text': None,
     'value_type': 'amount', 'effective_from': date(2020, 1, 1), 'effective_to': None, 'status': 'active'},
]


@pytest.fixture
def registry():
    saved = dict(engine.CHECKS)
    engine.CHECKS.clear()
    yield engine.CHECKS
    engine.CHECKS.clear()
    engine.CHECKS.update(saved)


def control(code='FRA-017', ctype='automated', licences=None):
    return {'id': 1, 'control_code': code, 'control_type': ctype, 'frequency': 'daily',
            'licence_types': licences or ['all']}


def ctx(c=None, licence='microfinance', db=None):
    return engine.CheckContext(c or control(), date(2026, 6, 1), licence, None, db or FakeParamDB(PARAM_ROWS))


# ---------------------------------------------------------------- get_param
class TestGetParam:
    db = FakeParamDB(PARAM_ROWS)

    def test_licence_specific_value(self):
        assert str(params.get_param('lending.admin_fee_cap_pct', 'microfinance', date(2026, 6, 1), db=self.db)) == '2.5'

    def test_generic_value_for_other_licence_and_dates(self):
        assert str(params.get_param('lending.admin_fee_cap_pct', 'consumer_finance', db=self.db)) == '3'
        assert str(params.get_param('lending.admin_fee_cap_pct', 'microfinance', date(2025, 6, 1), db=self.db)) == '3'

    def test_missing_parameter(self):
        with pytest.raises(ParameterNotFound):
            params.get_param('no.such.key', db=self.db)
        assert params.get_param('no.such.key', default=7, db=self.db) == 7

    def test_seeded_but_unset_parameter(self):
        with pytest.raises(ParameterNotSet):
            params.get_param('capital.min_paid_up', 'microfinance', db=self.db)
        assert params.get_param('capital.min_paid_up', 'microfinance', default=None, db=self.db) is None


# ---------------------------------------------------------------- registry
def test_register_as_decorator_and_call(registry):
    @engine.register_check('fra-017', name='cap')
    def chk(ctx):
        return True

    assert 'FRA-017' in registry and registry['FRA-017'].name == 'cap'
    engine.register_check('FRA-018', lambda ctx: 'pass')
    assert 'FRA-018' in registry


def test_duplicate_registration_is_refused(registry):
    engine.register_check('FRA-017', lambda ctx: True)
    with pytest.raises(ValueError):
        engine.register_check('FRA-017', lambda ctx: False)
    engine.register_check('FRA-017', lambda ctx: False, replace=True)


def test_re_registering_same_function_is_harmless(registry):
    def chk(ctx):
        return True
    engine.register_check('FRA-017', chk)
    engine.register_check('FRA-017', chk)


# ---------------------------------------------------------------- execute_check
def test_check_reads_parameter_and_fails(registry):
    loans = [{'id': 10, 'fee_pct': 2.0}, {'id': 11, 'fee_pct': 4.0}]

    @engine.register_check('FRA-017')
    def cap(ctx):
        limit = ctx.param('lending.admin_fee_cap_pct')
        bad = [{'table': 'loans', 'id': l['id']} for l in loans if l['fee_pct'] > limit]
        return ctx.fail(f'{len(bad)} over', bad, cap=limit) if bad else ctx.ok()

    res, name = engine.execute_check(control(), ctx())
    assert (res.status, res.affected_count, name) == ('fail', 1, 'cap')
    assert res.affected == [{'table': 'loans', 'id': 11}]


def test_crashing_check_becomes_error(registry):
    engine.register_check('FRA-017', lambda ctx: 1 / 0)
    res, _ = engine.execute_check(control(), ctx())
    assert res.status == 'error' and 'ZeroDivisionError' in res.summary


def test_unset_parameter_becomes_error_with_message(registry):
    engine.register_check('FRA-001', lambda ctx: ctx.param('capital.min_paid_up'))
    res, _ = engine.execute_check(control('FRA-001'), ctx())
    assert res.status == 'error' and 'capital.min_paid_up' in res.summary
    assert res.details.get('parameter_error') is True


def test_not_applicable_to_licence(registry):
    engine.register_check('FRA-017', lambda ctx: False)
    res, _ = engine.execute_check(control(licences=['microfinance']), ctx(licence='leasing'))
    assert res.status == 'not_applicable'


def test_evidence_fallback_and_no_check(registry):
    ev_ctrl = control('FRA-069', ctype='evidence')
    res, name = engine.execute_check(ev_ctrl, ctx(ev_ctrl), evidence_items=[])
    assert (res.status, name) == ('fail', 'evidence')
    approved = [{'status': 'approved', 'valid_to': date(2027, 1, 1), 'valid_from': None}]
    assert engine.execute_check(ev_ctrl, ctx(ev_ctrl), approved)[0].status == 'pass'
    wf = control('FRA-030', ctype='workflow')
    assert engine.execute_check(wf, ctx(wf), [])[0].status == 'no_check'
    # A workflow control that does have evidence uploaded is judged on it.
    assert engine.execute_check(wf, ctx(wf), approved)[0].status == 'pass'


def test_check_returning_check_result(registry):
    engine.register_check('FRA-017', lambda ctx: CheckResult('warning', 'close to cap'))
    assert engine.execute_check(control(), ctx())[0].status == 'warning'


def test_has_runnable_check(registry):
    engine.register_check('FRA-017', lambda ctx: True)
    assert engine.has_runnable_check(control())
    assert engine.has_runnable_check(control('FRA-069', 'evidence'))
    assert not engine.has_runnable_check(control('FRA-030', 'workflow'))
    assert engine.has_runnable_check(control('FRA-030', 'workflow'), evidence_count=1)


def test_builtin_checks_register():
    engine.load_checks(force=True)
    assert 'FRA-079' in engine.CHECKS
