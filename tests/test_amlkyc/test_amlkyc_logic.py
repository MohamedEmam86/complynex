"""Unit tests for amlkyc.logic — pure functions, no database."""
from datetime import date

from amlkyc import logic

RULES = [
    {'role_code': 'mlro', 'rule_type': 'holds', 'keyword': 'internal audit', 'reason_en': 'audits AML'},
    {'role_code': 'mlro', 'rule_type': 'reports_to', 'keyword': 'operations', 'reason_en': 'business line'},
]


class TestRoles:
    def test_holds_conflict(self):
        r = {'role_code': 'mlro', 'other_positions': 'Head of Internal Audit'}
        assert [c[0] for c in logic.role_conflicts(r, RULES)] == ['holds']

    def test_reporting_line_conflict_unless_board(self):
        r = {'role_code': 'mlro', 'reports_to_title': 'COO / Operations'}
        assert logic.role_conflicts(r, RULES)[0][0] == 'reports_to'
        assert logic.role_conflicts(dict(r, reports_to_board=True), RULES) == []

    def test_other_role_code_ignored(self):
        assert logic.role_conflicts({'role_code': 'cfo', 'other_positions': 'internal audit'}, RULES) == []

    def test_combined_role_needs_approval(self):
        assert logic.combined_role_unapproved({'other_positions': 'Compliance'})
        assert not logic.combined_role_unapproved({'other_positions': 'Compliance', 'combined_role_approval_ref': 'L-1'})
        assert not logic.combined_role_unapproved({'other_positions': ''})


FIELDS = [
    {'field_key': 'gender', 'source': 'column', 'column_names': ['gender'], 'applies_to': 'individual', 'is_required': True},
    {'field_key': 'address', 'source': 'column', 'column_names': ['address_line1', 'address'], 'applies_to': 'all',
     'is_required': True},
    {'field_key': 'tax_card_issuer', 'source': 'profile', 'column_names': [], 'applies_to': 'entity', 'is_required': True},
]


class TestCompleteness:
    def test_individual(self):
        c = logic.completeness({'gender': 'F', 'address': ''}, 'individual', FIELDS)
        assert c['missing'] == ['address'] and c['score'] == 50

    def test_first_non_empty_column_wins(self):
        assert logic.field_value({'address_line1': '', 'address': '5 St'}, {}, FIELDS[1]) == ('5 St', True)

    def test_profile_value_for_entity(self):
        assert logic.completeness({'address': 'x'}, 'entity', FIELDS, {'tax_card_issuer': 'Office A'})['score'] == 100

    def test_not_captured_column(self):
        c = logic.completeness({}, 'individual', FIELDS)
        assert 'gender' in c['not_captured']

    def test_only_restricts(self):
        assert logic.completeness({'gender': None}, 'individual', FIELDS, only=['address'])['missing'] == ['address']


FACTORS = [
    {'factor_key': 'type', 'category': 'customer', 'field_key': 'customer_type', 'weight': 1,
     'scoring': {'CORPORATE': 60, '*': 20}},
    {'factor_key': 'pep', 'category': 'pep', 'field_key': 'is_pep', 'weight': 3, 'scoring': {'true': 100, '*': 0}},
]
BANDS = [{'band': 'low', 'min_score': 0}, {'band': 'medium', 'min_score': 40}, {'band': 'high', 'min_score': 70}]


class TestRiskModel:
    def test_weighted_rating(self):
        score, band, br = logic.rate({'customer_type': 'corporate', 'is_pep': True}, FACTORS, BANDS)
        assert score == 90.0 and band == 'high' and len(br) == 2

    def test_default_score(self):
        assert logic.rate({'customer_type': 'INDIVIDUAL'}, FACTORS, BANDS)[:2] == (5.0, 'low')

    def test_model_gaps(self):
        assert set(logic.model_gaps(FACTORS)) == {'geography', 'product', 'channel', 'behaviour'}

    def test_next_review(self):
        assert logic.next_review(date(2026, 1, 31), 12) == date(2027, 1, 31)
        assert logic.next_review(date(2026, 1, 1), None) is None
        assert logic.review_overdue({'next_review_date': date(2026, 1, 1)}, date(2026, 2, 1))


class TestScreeningQA:
    def test_arabic_normalisation(self):
        assert logic.same_name('أحمد', 'احمد') and logic.same_name('فاطمة', 'فاطمه')

    def test_variants(self):
        types = {t for t, _ in logic.name_variants('Omar Khaled Hassan')}
        assert {'reordered', 'middle_dropped', 'initial', 'typo'} <= types
        assert any(t == 'arabic_letter_form' for t, _ in logic.name_variants('أحمد علي'))

    def test_negatives_deterministic(self):
        assert logic.synthetic_negatives(3) == logic.synthetic_negatives(3)

    def test_metrics(self):
        m = logic.qa_metrics([{'expect_match': True, 'found': True}, {'expect_match': True, 'found': False},
                              {'expect_match': False, 'found': True}])
        assert m['recall_pct'] == 50.0 and m['misses'] == 1 and m['false_positives'] == 1 and m['precision_pct'] == 50.0


class TestCoverage:
    def test_by_group(self):
        cov = logic.coverage_by_group([{'id': 1, 'group': 'A'}, {'id': 2, 'group': 'A'}, {'id': 3, 'group': 'B'}], {1, 3})
        assert cov == {'A': (1, 2, 50.0), 'B': (1, 1, 100.0)}

    def test_monitoring_gaps(self):
        rv = [{'status': 'planned', 'planned_date': date(2026, 1, 1)}, {'status': 'done', 'planned_date': date(2026, 1, 1)}]
        assert len(logic.monitoring_gaps(rv, date(2026, 3, 1))) == 1

    def test_audit_coverage(self):
        ctl = [{'id': 1, 'criticality': 'high'}, {'id': 2, 'criticality': 'low'}, {'id': 3, 'criticality': 'critical'}]
        assert [c['id'] for c in logic.audit_coverage(ctl, {3})] == [1]

    def test_study_overdue(self):
        assert logic.study_overdue({'status': 'candidate', 'study_due_date': date(2026, 1, 1)}, date(2026, 1, 2))
        assert not logic.study_overdue({'status': 'no_str', 'study_due_date': date(2026, 1, 1)}, date(2026, 1, 2))
