"""Pure rules for the customer risk floor, EDD, corporate KYB, merchant approval
and one-time passwords — no database."""
from datetime import date, timedelta

from aml import edd_logic as L
from kyb import logic as K
from merchant_kyc import workflow as W
from utils import temp_password
from models.user import User

HR = [{'country_code': 'SY', 'country_name': 'Syria', 'name_ar': 'سوريا', 'aliases': 'Syrian Arab Republic|Syrian',
       'is_active': 1},
      {'country_code': 'KP', 'country_name': 'North Korea', 'aliases': 'DPRK', 'is_active': 0}]


class TestRiskFloor:
    def test_country_matching_by_name_code_alias_arabic(self):
        for v in ('Syria', 'syria ', 'SY', 'Syrian', 'سوريا', 'Syrian Arab Republic'):
            assert L.match_country(v, HR), v
        assert L.match_country('Egypt', HR) is None
        assert L.match_country('DPRK', HR) is None          # inactive row ignored

    def test_pep_forces_high(self):
        r = L.forced_high_reasons({'is_pep': 1}, HR)
        assert r and r[0][0] == 'pep'
        assert L.final_classification('LOW', r) == 'HIGH'

    def test_country_and_screening_force_high(self):
        assert L.forced_high_reasons({'nationality': 'Syria'}, HR)[0] == ('country', 'Syria')
        assert L.forced_high_reasons({}, HR, 'open')[0][0] == 'screening'
        assert L.forced_high_reasons({}, HR, None) == []

    def test_owner_reasons(self):
        r = L.forced_high_reasons({}, HR, owners=[{'full_name': 'A', 'nationality': 'Syrian'},
                                                  {'full_name': 'B', 'is_pep': True},
                                                  {'full_name': 'C', 'screening_state': 'confirmed'}])
        assert {c for c, _d in r} == {'owner_country', 'owner_pep', 'owner_screening'}

    def test_no_reason_keeps_model_or_override(self):
        assert L.final_classification('MEDIUM', []) == 'MEDIUM'
        assert L.final_classification('LOW', [], override_class='high') == 'HIGH'

    def test_screening_link(self):
        assert L.screening_link([]) is None
        assert L.screening_link([{'status': 'Pending'}]) == 'open'
        assert L.screening_link([{'status': 'Resolved', 'resolution': 'False Positive'}]) is None
        assert L.screening_link([{'status': 'Resolved', 'resolution': 'PEP - Flag'}]) == 'pep'
        assert L.screening_link([{'status': 'Resolved', 'resolution': 'True Match - Block'}]) == 'confirmed'


class TestEdd:
    def full_case(self, **kw):
        c = dict(status='OPEN', source_of_wealth='Inheritance', source_of_funds='Salary', sof_evidence='',
                 purpose_nature='Savings account', enhanced_monitoring_frequency='Monthly',
                 next_review_date=date.today() + timedelta(days=200))
        c.update(kw)
        return c

    def test_source_of_funds_needs_evidence(self):
        assert 'Source of funds with evidence' in L.missing_for_submission(self.full_case(), 0)
        assert L.missing_for_submission(self.full_case(), 1) == []
        assert L.missing_for_submission(self.full_case(sof_evidence='6 months statements'), 0) == []

    def test_next_review_in_future(self):
        assert 'Next review date' in L.missing_for_submission(self.full_case(next_review_date=date.today()), 1)

    def test_legacy_statuses(self):
        assert L.edd_status({'status': 'COMPLETED'}) == L.EDD_APPROVED
        assert L.edd_status({'status': 'IN_PROGRESS'}) == L.EDD_OPEN
        assert L.can_edit({'status': 'RETURNED'}) and not L.can_edit({'status': 'SUBMITTED'})

    def test_four_eyes_and_roles(self):
        assert L.four_eyes_error(3, 3)
        assert L.four_eyes_error(2, 3) is None
        assert L.approver_role_ok('compliance_manager', False)
        assert L.approver_role_ok('manager', True) and not L.approver_role_ok('manager', False)
        assert not L.approver_role_ok('compliance_officer', True)

    def test_display_and_blockers(self):
        assert L.display_status(0, None) == 'not_required'
        assert L.display_status(1, None) == 'not_started'
        assert L.display_status(1, {'status': 'SUBMITTED'}) == 'awaiting_approval'
        assert L.is_pending(1, {'status': 'OPEN'}) and not L.is_pending(1, {'status': 'APPROVED'})
        assert L.activation_blockers({}, 1, {'status': 'SUBMITTED'})
        assert L.activation_blockers({}, 1, {'status': 'APPROVED'}) == []


class TestKyb:
    def msgs(self, lst):
        return [m[0] for m in lst]

    def test_ownership_bounds_and_total(self):
        e, _w = K.validate_ubos([{'full_name': 'A', 'ownership_pct': 60}, {'full_name': 'B', 'ownership_pct': 50}])
        assert any('cannot exceed' in m for m in self.msgs(e))
        e, _w = K.validate_ubos([{'full_name': 'A', 'ownership_pct': 101}])
        assert any('between 0 and 100' in m for m in self.msgs(e))
        e, _w = K.validate_ubos([{'full_name': 'A', 'ownership_pct': 'x'}])
        assert e

    def test_warning_without_25_or_controller(self):
        e, w = K.validate_ubos([{'full_name': 'A', 'ownership_pct': 20}, {'full_name': 'B', 'ownership_pct': 20}])
        assert not e and w
        e, w = K.validate_ubos([{'full_name': 'A', 'ownership_pct': 20},
                                {'full_name': 'B', 'ownership_pct': None, 'control_type': 'senior_manager'}])
        assert not e and not w
        assert K.validate_ubos([{'full_name': 'A', 'ownership_pct': 25}]) == ([], [])

    def test_screening_state(self):
        p = {'full_name': 'A', 'screening_history_id': 1}
        p['screened_key'] = K.screen_key(p)
        assert K.screening_state({'full_name': 'A'}, None, []) == K.NOT_SCREENED
        assert K.screening_state(p, {'screening_result': 'CLEAR'}, []) == K.CLEAR
        assert K.screening_state(p, {'screening_result': 'POTENTIAL_MATCH'}, [{'status': 'Pending'}]) == K.OPEN
        assert K.screening_state(p, {'screening_result': 'POTENTIAL_MATCH'}, [{'status': 'Resolved', 'resolution': 'False Positive'}]) == K.CLEARED
        assert K.screening_state(p, {'screening_result': 'POTENTIAL_MATCH'}, [{'status': 'Resolved', 'resolution': 'True Match - Block'}]) == K.CONFIRMED
        changed = dict(p, full_name='B')
        assert K.screening_state(changed, {'screening_result': 'CLEAR'}, []) == K.NOT_SCREENED
        assert K.screening_state({'full_name': 'A', 'screening_error': 'down'}, None, []) == K.ERROR

    def test_approval_blockers(self):
        ent = {'cr_number': '1', 'tax_card_number': '2', 'legal_form': 'LLC', 'incorporation_date': '2010-01-01',
               'incorporation_country': 'Egypt'}
        u = [{'id': 1, 'full_name': 'A', 'ownership_pct': 100}]
        s = [{'id': 7, 'full_name': 'A'}]
        assert K.approval_blockers(ent, u, s, {('ubo', 1): K.CLEAR, ('signatory', 7): K.CLEAR}) == []
        b = K.approval_blockers(ent, u, s, {('ubo', 1): K.OPEN, ('signatory', 7): K.CLEAR})
        assert any('still open' in m[0] for m in b)
        b = K.approval_blockers(dict(ent, tax_card_number=''), [], [], {})
        assert len(b) == 3

    def test_main_owner(self):
        assert K.main_owner([{'full_name': 'A', 'ownership_pct': 30}, {'full_name': 'B', 'ownership_pct': 70}])['full_name'] == 'B'


class TestMerchantWorkflow:
    def test_four_eyes(self):
        m = {'kyc_status': 'SUBMITTED', 'created_by': 3, 'submitted_by': 4}
        assert W.decision_error(m, 3, 'approve')
        assert W.decision_error(m, 4, 'approve')
        assert W.decision_error(m, 2, 'approve') is None

    def test_reject_reason_and_states(self):
        m = {'kyc_status': 'SUBMITTED', 'created_by': 3}
        assert W.decision_error(m, 2, 'reject', 'short')
        assert W.decision_error(m, 2, 'reject', 'Documents could not be verified') is None
        assert W.decision_error({'kyc_status': 'PENDING'}, 2, 'approve')
        assert W.decision_error({'kyc_status': 'APPROVED'}, 2, 'reject', 'x' * 20)

    def test_edit_cannot_decide(self):
        assert W.edit_status('PENDING', 'APPROVED') == 'PENDING'
        assert W.edit_status('PENDING', 'SUBMITTED') == 'SUBMITTED'
        assert W.edit_status('APPROVED', 'PENDING') == 'APPROVED'


class TestTempPassword:
    def test_policy_and_uniqueness(self):
        pws = {temp_password.generate() for _ in range(50)}
        assert len(pws) == 50
        for p in pws:
            assert User.validate_password_strength(p)[0], p
            assert p[0].isalpha()

    def test_csv(self):
        out = temp_password.credentials_csv([{'email': 'a@x.example', 'first_name': '=cmd', 'password': 'Abc'}])
        assert out.startswith('﻿') and "'=cmd" in out and 'Abc' in out
