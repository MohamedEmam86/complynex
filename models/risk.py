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

"""
Enterprise Risk Management models: risk register, categories, appetite,
scoring bands, the control library (RCM), KRIs, treatment lifecycle, score
history, and the generic cross-module risk_source_links table.
"""
from datetime import date

from database.db import get_db

# Fixed module -> default risk-category-code lookup, used only to pre-fill a
# suggestion's category when a risk is drafted from a source-module record.
# The risk owner reviews and can change it before saving.
MODULE_CATEGORY_MAP = {
    'aml': 'FCR',
    'screening': 'FCR',
    'whistleblowing': 'CON',
    'consumer_protection': 'CON',
    'cyber': 'TEC',
    'data_protection': 'CON',
    'phishing': 'OPR',
    'merchant_kyc': 'FCR',
    'coi': 'CON',
    'ghe': 'CON',
    'cobec': 'CON',
    'policies': 'OPR',
    'training': 'OPR',
    'internal_audit': 'OPR',
}


class RiskCategory:
    def __init__(self, id=None, category_code=None, parent_category_id=None,
                 category_name=None, category_description=None, is_active=True,
                 created_at=None, **kwargs):
        self.id = id
        self.category_code = category_code
        self.parent_category_id = parent_category_id
        self.category_name = category_name
        self.category_description = category_description
        self.is_active = bool(is_active) if is_active is not None else True
        self.created_at = created_at

    @staticmethod
    def get_all(include_inactive=False):
        db = get_db()
        if include_inactive:
            rows = db.execute('SELECT * FROM risk_categories ORDER BY is_active DESC, category_name').fetchall()
        else:
            rows = db.execute(
                'SELECT * FROM risk_categories WHERE is_active = TRUE ORDER BY category_name'
            ).fetchall()
        return [RiskCategory(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(category_id):
        if not category_id:
            return None
        db = get_db()
        row = db.execute('SELECT * FROM risk_categories WHERE id = %s', (category_id,)).fetchone()
        return RiskCategory(**dict(row)) if row else None

    @staticmethod
    def get_by_code(code):
        db = get_db()
        row = db.execute('SELECT * FROM risk_categories WHERE category_code = %s', (code,)).fetchone()
        return RiskCategory(**dict(row)) if row else None

    @staticmethod
    def create(category_code, category_name, category_description=None, parent_category_id=None):
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO risk_categories (category_code, parent_category_id, category_name, category_description)
               VALUES (%s, %s, %s, %s) RETURNING id''',
            (category_code, parent_category_id, category_name, category_description)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return RiskCategory.get_by_id(new_id)

    @staticmethod
    def update(category_id, category_name, category_description=None, parent_category_id=None):
        db = get_db()
        db.execute(
            '''UPDATE risk_categories SET category_name = %s, category_description = %s,
               parent_category_id = %s WHERE id = %s''',
            (category_name, category_description, parent_category_id, category_id)
        )
        db.commit()
        return RiskCategory.get_by_id(category_id)

    @staticmethod
    def usage_count(category_id):
        """Number of risk register entries currently referencing this category."""
        db = get_db()
        row = db.execute('SELECT COUNT(*) AS c FROM risks WHERE category_id = %s', (category_id,)).fetchone()
        return dict(row)['c'] if row else 0

    @staticmethod
    def set_active(category_id, active):
        db = get_db()
        db.execute('UPDATE risk_categories SET is_active = %s WHERE id = %s', (active, category_id))
        db.commit()

    @staticmethod
    def delete(category_id):
        """Hard-delete only permitted when no risk currently references this
        category and no other category is nested under it — otherwise callers
        should archive instead, so existing risk register entries and
        sub-categories never lose a valid reference."""
        if RiskCategory.usage_count(category_id) > 0:
            raise ValueError('Cannot delete a category that is still referenced by risk register entries. Archive it instead.')
        db = get_db()
        row = db.execute('SELECT COUNT(*) AS c FROM risk_categories WHERE parent_category_id = %s', (category_id,)).fetchone()
        if row and dict(row)['c'] > 0:
            raise ValueError('Cannot delete a category that has sub-categories under it. Archive it instead.')
        db.execute('DELETE FROM risk_categories WHERE id = %s', (category_id,))
        db.commit()


class RiskScoringBand:
    def __init__(self, id=None, band_name=None, min_score=None, max_score=None,
                 color_hex=None, display_order=None, requires_board_notification=False, **kwargs):
        self.id = id
        self.band_name = band_name
        self.min_score = min_score
        self.max_score = max_score
        self.color_hex = color_hex
        self.display_order = display_order
        self.requires_board_notification = bool(requires_board_notification)

    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute('SELECT * FROM risk_scoring_bands ORDER BY display_order').fetchall()
        return [RiskScoringBand(**dict(row)) for row in rows]

    @staticmethod
    def get_band_for_score(score):
        db = get_db()
        row = db.execute(
            'SELECT * FROM risk_scoring_bands WHERE %s BETWEEN min_score AND max_score', (score,)
        ).fetchone()
        return RiskScoringBand(**dict(row)) if row else None


class RiskAppetiteStatement:
    def __init__(self, id=None, category_id=None, statement_text=None, appetite_level=None,
                 max_acceptable_inherent_score=None, max_acceptable_residual_score=None,
                 effective_from=None, effective_to=None, approved_by_meeting_id=None,
                 created_by=None, created_at=None, **kwargs):
        self.id = id
        self.category_id = category_id
        self.statement_text = statement_text
        self.appetite_level = appetite_level
        self.max_acceptable_inherent_score = max_acceptable_inherent_score
        self.max_acceptable_residual_score = max_acceptable_residual_score
        self.effective_from = effective_from
        self.effective_to = effective_to
        self.approved_by_meeting_id = approved_by_meeting_id
        self.created_by = created_by
        self.created_at = created_at

    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute('SELECT * FROM risk_appetite_statements ORDER BY effective_from DESC').fetchall()
        return [RiskAppetiteStatement(**dict(row)) for row in rows]

    @staticmethod
    def get_active_for_category(category_id):
        """Category-specific active statement first; falls back to the entity-wide one."""
        db = get_db()
        row = db.execute(
            '''SELECT * FROM risk_appetite_statements
               WHERE category_id = %s AND effective_from <= CURRENT_DATE
               AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
               ORDER BY effective_from DESC LIMIT 1''',
            (category_id,)
        ).fetchone()
        if row:
            return RiskAppetiteStatement(**dict(row))
        row = db.execute(
            '''SELECT * FROM risk_appetite_statements
               WHERE category_id IS NULL AND effective_from <= CURRENT_DATE
               AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
               ORDER BY effective_from DESC LIMIT 1'''
        ).fetchone()
        return RiskAppetiteStatement(**dict(row)) if row else None

    @staticmethod
    def create(statement_text, appetite_level, max_acceptable_residual_score, effective_from,
               category_id=None, max_acceptable_inherent_score=None, effective_to=None,
               approved_by_meeting_id=None, created_by=None):
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO risk_appetite_statements
               (category_id, statement_text, appetite_level, max_acceptable_inherent_score,
                max_acceptable_residual_score, effective_from, effective_to,
                approved_by_meeting_id, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (category_id, statement_text, appetite_level, max_acceptable_inherent_score,
             max_acceptable_residual_score, effective_from, effective_to,
             approved_by_meeting_id, created_by)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return new_id


class Control:
    def __init__(self, id=None, control_code=None, control_name=None, control_description=None,
                 control_type=None, control_nature='MANUAL', control_owner_id=None, department_id=None,
                 testing_frequency='ANNUAL', last_tested_date=None, last_test_result=None,
                 next_test_due_date=None, status='ACTIVE', created_at=None, **kwargs):
        self.id = id
        self.control_code = control_code
        self.control_name = control_name
        self.control_description = control_description
        self.control_type = control_type
        self.control_nature = control_nature
        self.control_owner_id = control_owner_id
        self.department_id = department_id
        self.testing_frequency = testing_frequency
        self.last_tested_date = last_tested_date
        self.last_test_result = last_test_result
        self.next_test_due_date = next_test_due_date
        self.status = status
        self.created_at = created_at

    @staticmethod
    def get_all(status='ACTIVE'):
        db = get_db()
        if status:
            rows = db.execute('SELECT * FROM controls WHERE status = %s ORDER BY control_code', (status,)).fetchall()
        else:
            rows = db.execute('SELECT * FROM controls ORDER BY control_code').fetchall()
        return [Control(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(control_id):
        db = get_db()
        row = db.execute('SELECT * FROM controls WHERE id = %s', (control_id,)).fetchone()
        return Control(**dict(row)) if row else None

    @staticmethod
    def create(control_code, control_name, control_type, control_description=None,
               control_nature='MANUAL', control_owner_id=None, department_id=None,
               testing_frequency='ANNUAL'):
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO controls
               (control_code, control_name, control_description, control_type, control_nature,
                control_owner_id, department_id, testing_frequency)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (control_code, control_name, control_description, control_type, control_nature,
             control_owner_id, department_id, testing_frequency)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return Control.get_by_id(new_id)

    @staticmethod
    def record_test_result(control_id, result, last_tested_date, next_test_due_date=None):
        db = get_db()
        db.execute(
            'UPDATE controls SET last_test_result = %s, last_tested_date = %s, next_test_due_date = %s WHERE id = %s',
            (result, last_tested_date, next_test_due_date, control_id)
        )
        db.commit()


class RiskControl:
    @staticmethod
    def link(risk_id, control_id, reliance_level='PRIMARY'):
        db = get_db()
        existing = db.execute(
            'SELECT id FROM risk_controls WHERE risk_id = %s AND control_id = %s', (risk_id, control_id)
        ).fetchone()
        if existing:
            return existing[0]
        cursor = db.execute(
            'INSERT INTO risk_controls (risk_id, control_id, reliance_level) VALUES (%s, %s, %s) RETURNING id',
            (risk_id, control_id, reliance_level)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return new_id

    @staticmethod
    def unlink(risk_id, control_id):
        db = get_db()
        db.execute('DELETE FROM risk_controls WHERE risk_id = %s AND control_id = %s', (risk_id, control_id))
        db.commit()

    @staticmethod
    def get_controls_for_risk(risk_id):
        db = get_db()
        rows = db.execute(
            '''SELECT c.*, rc.reliance_level FROM controls c
               JOIN risk_controls rc ON rc.control_id = c.id
               WHERE rc.risk_id = %s ORDER BY rc.reliance_level, c.control_code''',
            (risk_id,)
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            reliance_level = d.pop('reliance_level', None)
            control = Control(**d)
            control.reliance_level = reliance_level
            results.append(control)
        return results

    @staticmethod
    def get_risks_for_control(control_id):
        db = get_db()
        rows = db.execute(
            '''SELECT r.* FROM risks r
               JOIN risk_controls rc ON rc.risk_id = r.id
               WHERE rc.control_id = %s ORDER BY r.risk_id''',
            (control_id,)
        ).fetchall()
        return [Risk(**dict(row)) for row in rows]


class ControlTestResult:
    def __init__(self, id=None, control_id=None, tested_by=None, test_date=None, test_procedure=None,
                 result=None, exceptions_noted=None, evidence_file=None, audit_project_id=None,
                 created_at=None, **kwargs):
        self.id = id
        self.control_id = control_id
        self.tested_by = tested_by
        self.test_date = test_date
        self.test_procedure = test_procedure
        self.result = result
        self.exceptions_noted = exceptions_noted
        self.evidence_file = evidence_file
        self.audit_project_id = audit_project_id
        self.created_at = created_at

    @staticmethod
    def create(control_id, tested_by, test_date, result, test_procedure=None,
               exceptions_noted=None, evidence_file=None, audit_project_id=None):
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO control_test_results
               (control_id, tested_by, test_date, test_procedure, result, exceptions_noted,
                evidence_file, audit_project_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (control_id, tested_by, test_date, test_procedure, result, exceptions_noted,
             evidence_file, audit_project_id)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        Control.record_test_result(control_id, result, test_date)
        return new_id

    @staticmethod
    def get_for_control(control_id):
        db = get_db()
        rows = db.execute(
            'SELECT * FROM control_test_results WHERE control_id = %s ORDER BY test_date DESC',
            (control_id,)
        ).fetchall()
        return [ControlTestResult(**dict(row)) for row in rows]


class KRI:
    def __init__(self, id=None, risk_id=None, kri_name=None, kri_description=None, unit_of_measure=None,
                 measurement_frequency='MONTHLY', target_value=None, warning_threshold=None,
                 breach_threshold=None, direction='UPPER', owner_id=None, is_active=True,
                 created_at=None, **kwargs):
        self.id = id
        self.risk_id = risk_id
        self.kri_name = kri_name
        self.kri_description = kri_description
        self.unit_of_measure = unit_of_measure
        self.measurement_frequency = measurement_frequency
        self.target_value = target_value
        self.warning_threshold = warning_threshold
        self.breach_threshold = breach_threshold
        self.direction = direction
        self.owner_id = owner_id
        self.is_active = bool(is_active)
        self.created_at = created_at

    @staticmethod
    def get_all(active_only=True):
        db = get_db()
        if active_only:
            rows = db.execute('SELECT * FROM kris WHERE is_active = TRUE ORDER BY kri_name').fetchall()
        else:
            rows = db.execute('SELECT * FROM kris ORDER BY kri_name').fetchall()
        return [KRI(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(kri_id):
        db = get_db()
        row = db.execute('SELECT * FROM kris WHERE id = %s', (kri_id,)).fetchone()
        return KRI(**dict(row)) if row else None

    @staticmethod
    def get_for_risk(risk_id):
        db = get_db()
        rows = db.execute('SELECT * FROM kris WHERE risk_id = %s ORDER BY kri_name', (risk_id,)).fetchall()
        return [KRI(**dict(row)) for row in rows]

    @staticmethod
    def create(kri_name, direction='UPPER', risk_id=None, kri_description=None, unit_of_measure=None,
               measurement_frequency='MONTHLY', target_value=None, warning_threshold=None,
               breach_threshold=None, owner_id=None):
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO kris
               (risk_id, kri_name, kri_description, unit_of_measure, measurement_frequency,
                target_value, warning_threshold, breach_threshold, direction, owner_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (risk_id, kri_name, kri_description, unit_of_measure, measurement_frequency,
             target_value, warning_threshold, breach_threshold, direction, owner_id)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return KRI.get_by_id(new_id)


class KRIMeasurement:
    def __init__(self, id=None, kri_id=None, measurement_date=None, actual_value=None,
                 status=None, notes=None, recorded_by=None, created_at=None, **kwargs):
        self.id = id
        self.kri_id = kri_id
        self.measurement_date = measurement_date
        self.actual_value = actual_value
        self.status = status
        self.notes = notes
        self.recorded_by = recorded_by
        self.created_at = created_at

    @staticmethod
    def _compute_status(kri, actual_value):
        actual_value = float(actual_value)
        upper = (kri.direction or 'UPPER') == 'UPPER'
        breach = kri.breach_threshold is not None and float(kri.breach_threshold)
        warning = kri.warning_threshold is not None and float(kri.warning_threshold)
        if breach is not False and breach is not None:
            if (upper and actual_value >= breach) or (not upper and actual_value <= breach):
                return 'RED'
        if warning is not False and warning is not None:
            if (upper and actual_value >= warning) or (not upper and actual_value <= warning):
                return 'AMBER'
        return 'GREEN'

    @staticmethod
    def create(kri_id, measurement_date, actual_value, notes=None, recorded_by=None):
        kri = KRI.get_by_id(kri_id)
        status = KRIMeasurement._compute_status(kri, actual_value) if kri else 'GREEN'
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO kri_measurements (kri_id, measurement_date, actual_value, status, notes, recorded_by)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id''',
            (kri_id, measurement_date, actual_value, status, notes, recorded_by)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return new_id, status

    @staticmethod
    def get_history(kri_id, limit=24):
        db = get_db()
        rows = db.execute(
            'SELECT * FROM kri_measurements WHERE kri_id = %s ORDER BY measurement_date DESC LIMIT %s',
            (kri_id, limit)
        ).fetchall()
        return [KRIMeasurement(**dict(row)) for row in rows]


class RiskScoreHistory:
    def __init__(self, id=None, risk_id=None, likelihood=None, impact=None, inherent_risk_score=None,
                 residual_likelihood=None, residual_impact=None, residual_risk_score=None,
                 control_effectiveness=None, changed_by=None, change_reason=None, recorded_at=None, **kwargs):
        self.id = id
        self.risk_id = risk_id
        self.likelihood = likelihood
        self.impact = impact
        self.inherent_risk_score = inherent_risk_score
        self.residual_likelihood = residual_likelihood
        self.residual_impact = residual_impact
        self.residual_risk_score = residual_risk_score
        self.control_effectiveness = control_effectiveness
        self.changed_by = changed_by
        self.change_reason = change_reason
        self.recorded_at = recorded_at

    @staticmethod
    def create(risk_id, likelihood, impact, inherent_risk_score, residual_likelihood=None,
               residual_impact=None, residual_risk_score=None, control_effectiveness=None,
               changed_by=None, change_reason=None):
        db = get_db()
        db.execute(
            '''INSERT INTO risk_score_history
               (risk_id, likelihood, impact, inherent_risk_score, residual_likelihood,
                residual_impact, residual_risk_score, control_effectiveness, changed_by, change_reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (risk_id, likelihood, impact, inherent_risk_score, residual_likelihood,
             residual_impact, residual_risk_score, control_effectiveness, changed_by, change_reason)
        )
        db.commit()

    @staticmethod
    def get_for_risk(risk_id):
        db = get_db()
        rows = db.execute(
            'SELECT * FROM risk_score_history WHERE risk_id = %s ORDER BY recorded_at', (risk_id,)
        ).fetchall()
        return [RiskScoreHistory(**dict(row)) for row in rows]


class RiskTreatment:
    OPEN_STATUSES = ('PROPOSED', 'APPROVED', 'IN_PROGRESS', 'COMPLETED')

    def __init__(self, id=None, risk_id=None, treatment_description=None, treatment_type=None,
                 treatment_owner_id=None, estimated_cost=None, budget_approved=False,
                 target_date=None, completion_date=None, status='PROPOSED', verified_by=None,
                 verified_at=None, verification_notes=None, evidence_file=None, created_by=None,
                 created_at=None, updated_at=None, **kwargs):
        self.id = id
        self.risk_id = risk_id
        self.treatment_description = treatment_description
        self.treatment_type = treatment_type
        self.treatment_owner_id = treatment_owner_id
        self.estimated_cost = estimated_cost
        self.budget_approved = bool(budget_approved)
        self.target_date = target_date
        self.completion_date = completion_date
        self.status = status
        self.verified_by = verified_by
        self.verified_at = verified_at
        self.verification_notes = verification_notes
        self.evidence_file = evidence_file
        self.created_by = created_by
        self.created_at = created_at
        self.updated_at = updated_at

    @staticmethod
    def get_by_id(treatment_id):
        db = get_db()
        row = db.execute('SELECT * FROM risk_treatments WHERE id = %s', (treatment_id,)).fetchone()
        return RiskTreatment(**dict(row)) if row else None

    @staticmethod
    def get_for_risk(risk_id):
        db = get_db()
        rows = db.execute(
            'SELECT * FROM risk_treatments WHERE risk_id = %s ORDER BY target_date', (risk_id,)
        ).fetchall()
        return [RiskTreatment(**dict(row)) for row in rows]

    @staticmethod
    def get_for_owner(owner_id):
        db = get_db()
        rows = db.execute(
            "SELECT * FROM risk_treatments WHERE treatment_owner_id = %s AND status != 'CLOSED' ORDER BY target_date",
            (owner_id,)
        ).fetchall()
        return [RiskTreatment(**dict(row)) for row in rows]

    @staticmethod
    def get_overdue():
        db = get_db()
        rows = db.execute(
            '''SELECT * FROM risk_treatments
               WHERE target_date < CURRENT_DATE AND status IN ('PROPOSED', 'APPROVED', 'IN_PROGRESS')
               ORDER BY target_date'''
        ).fetchall()
        return [RiskTreatment(**dict(row)) for row in rows]

    @staticmethod
    def create(risk_id, treatment_description, treatment_owner_id, target_date, treatment_type=None,
               estimated_cost=None, created_by=None):
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO risk_treatments
               (risk_id, treatment_description, treatment_type, treatment_owner_id, estimated_cost,
                target_date, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (risk_id, treatment_description, treatment_type, treatment_owner_id, estimated_cost,
             target_date, created_by)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return RiskTreatment.get_by_id(new_id)

    @staticmethod
    def update_status(treatment_id, status, completion_date=None):
        db = get_db()
        db.execute(
            '''UPDATE risk_treatments SET status = %s, completion_date = COALESCE(%s, completion_date),
               updated_at = CURRENT_TIMESTAMP WHERE id = %s''',
            (status, completion_date, treatment_id)
        )
        db.commit()

    @staticmethod
    def verify_and_close(treatment_id, verified_by, verification_notes=None):
        """Independent verification — the verifier must not be the treatment owner
        (management should not be able to mark its own remediation as done)."""
        treatment = RiskTreatment.get_by_id(treatment_id)
        if not treatment:
            raise ValueError('Treatment not found')
        if treatment.treatment_owner_id == verified_by:
            raise ValueError('The treatment owner cannot verify their own treatment')
        db = get_db()
        db.execute(
            '''UPDATE risk_treatments
               SET status = 'VERIFIED', verified_by = %s, verified_at = CURRENT_TIMESTAMP,
                   verification_notes = %s, updated_at = CURRENT_TIMESTAMP
               WHERE id = %s''',
            (verified_by, verification_notes, treatment_id)
        )
        db.commit()


class RiskSourceLink:
    ALLOWED_MODULES = (
        'aml', 'screening', 'whistleblowing', 'consumer_protection', 'cyber', 'data_protection',
        'phishing', 'merchant_kyc', 'coi', 'ghe', 'cobec', 'policies', 'training', 'internal_audit',
    )

    def __init__(self, id=None, risk_id=None, source_module=None, source_table=None,
                 source_record_id=None, link_type='EVIDENCE', linked_by=None, linked_at=None,
                 notes=None, **kwargs):
        self.id = id
        self.risk_id = risk_id
        self.source_module = source_module
        self.source_table = source_table
        self.source_record_id = source_record_id
        self.link_type = link_type
        self.linked_by = linked_by
        self.linked_at = linked_at
        self.notes = notes

    @staticmethod
    def create(risk_id, source_module, source_table, source_record_id, link_type='EVIDENCE',
               linked_by=None, notes=None):
        if source_module not in RiskSourceLink.ALLOWED_MODULES:
            raise ValueError(f'Unknown source_module: {source_module}')
        db = get_db()
        existing = db.execute(
            '''SELECT id FROM risk_source_links
               WHERE risk_id = %s AND source_module = %s AND source_table = %s
               AND source_record_id = %s AND link_type = %s''',
            (risk_id, source_module, source_table, source_record_id, link_type)
        ).fetchone()
        if existing:
            return existing[0]
        cursor = db.execute(
            '''INSERT INTO risk_source_links
               (risk_id, source_module, source_table, source_record_id, link_type, linked_by, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (risk_id, source_module, source_table, source_record_id, link_type, linked_by, notes)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return new_id

    @staticmethod
    def get_for_risk(risk_id):
        db = get_db()
        rows = db.execute(
            'SELECT * FROM risk_source_links WHERE risk_id = %s ORDER BY linked_at', (risk_id,)
        ).fetchall()
        return [RiskSourceLink(**dict(row)) for row in rows]

    @staticmethod
    def is_linked(source_module, source_table, source_record_id):
        db = get_db()
        row = db.execute(
            '''SELECT 1 FROM risk_source_links
               WHERE source_module = %s AND source_table = %s AND source_record_id = %s LIMIT 1''',
            (source_module, source_table, source_record_id)
        ).fetchone()
        return row is not None


class Risk:
    def __init__(self, id=None, risk_id=None, risk_title=None, risk_description=None, category_id=None,
                 secondary_tags=None, department_id=None, parent_risk_id=None, likelihood=None,
                 impact=None, inherent_risk_score=None, existing_controls=None, control_effectiveness=None,
                 residual_likelihood=None, residual_impact=None, residual_risk_score=None,
                 risk_response=None, risk_owner_id=None, review_frequency='QUARTERLY',
                 last_review_date=None, next_review_date=None, risk_appetite_aligned=None,
                 status='ACTIVE', created_by=None, created_at=None, updated_at=None, **kwargs):
        self.id = id
        self.risk_id = risk_id
        self.risk_title = risk_title
        self.risk_description = risk_description
        self.category_id = category_id
        self.secondary_tags = secondary_tags
        self.department_id = department_id
        self.parent_risk_id = parent_risk_id
        self.likelihood = likelihood
        self.impact = impact
        self.inherent_risk_score = inherent_risk_score
        self.existing_controls = existing_controls
        self.control_effectiveness = control_effectiveness
        self.residual_likelihood = residual_likelihood
        self.residual_impact = residual_impact
        self.residual_risk_score = residual_risk_score
        self.risk_response = risk_response
        self.risk_owner_id = risk_owner_id
        self.review_frequency = review_frequency
        self.last_review_date = last_review_date
        self.next_review_date = next_review_date
        self.risk_appetite_aligned = risk_appetite_aligned
        self.status = status
        self.created_by = created_by
        self.created_at = created_at
        self.updated_at = updated_at

    @staticmethod
    def compute_score(likelihood, impact):
        return int(likelihood) * int(impact)

    @staticmethod
    def _generate_risk_id():
        year = date.today().year
        db = get_db()
        seq_row = db.execute(
            "SELECT prefix, padding FROM numbering_sequences WHERE sequence_key = 'risk_id'"
        ).fetchone()
        prefix = seq_row['prefix'] if seq_row else 'RSK'
        padding = seq_row['padding'] if seq_row else 4

        row = db.execute(
            "SELECT risk_id FROM risks WHERE risk_id LIKE %s ORDER BY risk_id DESC LIMIT 1",
            (f'{prefix}-{year}-%',)
        ).fetchone()
        seq = 1
        if row:
            try:
                seq = int(row['risk_id'].split('-')[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        return f'{prefix}-{year}-{seq:0{padding}d}'

    @staticmethod
    def get_by_id(risk_pk):
        db = get_db()
        row = db.execute('SELECT * FROM risks WHERE id = %s', (risk_pk,)).fetchone()
        return Risk(**dict(row)) if row else None

    @staticmethod
    def get_by_risk_id(risk_id_str):
        db = get_db()
        row = db.execute('SELECT * FROM risks WHERE risk_id = %s', (risk_id_str,)).fetchone()
        return Risk(**dict(row)) if row else None

    @staticmethod
    def get_all(category_id=None, department_id=None, owner_id=None, status=None):
        db = get_db()
        clauses = []
        params = []
        if category_id:
            clauses.append('category_id = %s')
            params.append(category_id)
        if department_id:
            clauses.append('department_id = %s')
            params.append(department_id)
        if owner_id:
            clauses.append('risk_owner_id = %s')
            params.append(owner_id)
        if status:
            clauses.append('status = %s')
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        rows = db.execute(
            f'SELECT * FROM risks {where} ORDER BY residual_risk_score DESC NULLS LAST, inherent_risk_score DESC',
            tuple(params)
        ).fetchall()
        return [Risk(**dict(row)) for row in rows]

    @staticmethod
    def compute_appetite_alignment(category_id, residual_score):
        if residual_score is None:
            return None
        appetite = RiskAppetiteStatement.get_active_for_category(category_id)
        if not appetite:
            return None
        return residual_score <= appetite.max_acceptable_residual_score

    @staticmethod
    def refresh_appetite_alignment(risk_pk):
        risk = Risk.get_by_id(risk_pk)
        if not risk:
            return
        aligned = Risk.compute_appetite_alignment(risk.category_id, risk.residual_risk_score)
        db = get_db()
        db.execute('UPDATE risks SET risk_appetite_aligned = %s WHERE id = %s', (aligned, risk_pk))
        db.commit()

    @staticmethod
    def create(risk_title, category_id, likelihood, impact, risk_owner_id, created_by,
               risk_description=None, secondary_tags=None, department_id=None, parent_risk_id=None,
               existing_controls=None, risk_response=None, review_frequency='QUARTERLY',
               next_review_date=None, status='ACTIVE'):
        inherent_score = Risk.compute_score(likelihood, impact)
        risk_id_str = Risk._generate_risk_id()
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO risks
               (risk_id, risk_title, risk_description, category_id, secondary_tags, department_id,
                parent_risk_id, likelihood, impact, inherent_risk_score, existing_controls,
                risk_response, risk_owner_id, review_frequency, next_review_date, status, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (risk_id_str, risk_title, risk_description, category_id, secondary_tags, department_id,
             parent_risk_id, likelihood, impact, inherent_score, existing_controls,
             risk_response, risk_owner_id, review_frequency, next_review_date, status, created_by)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        RiskScoreHistory.create(new_id, likelihood, impact, inherent_score, changed_by=created_by,
                                 change_reason='Initial risk registration')
        return Risk.get_by_id(new_id)

    @staticmethod
    def update_scoring(risk_pk, likelihood, impact, residual_likelihood=None, residual_impact=None,
                        control_effectiveness=None, changed_by=None, change_reason=None):
        inherent_score = Risk.compute_score(likelihood, impact)
        residual_score = Risk.compute_score(residual_likelihood, residual_impact) \
            if residual_likelihood and residual_impact else None
        db = get_db()
        db.execute(
            '''UPDATE risks SET likelihood = %s, impact = %s, inherent_risk_score = %s,
               residual_likelihood = %s, residual_impact = %s, residual_risk_score = %s,
               control_effectiveness = %s, last_review_date = CURRENT_DATE, updated_at = CURRENT_TIMESTAMP
               WHERE id = %s''',
            (likelihood, impact, inherent_score, residual_likelihood, residual_impact,
             residual_score, control_effectiveness, risk_pk)
        )
        db.commit()
        RiskScoreHistory.create(risk_pk, likelihood, impact, inherent_score, residual_likelihood,
                                 residual_impact, residual_score, control_effectiveness,
                                 changed_by, change_reason)
        Risk.refresh_appetite_alignment(risk_pk)

    @staticmethod
    def close(risk_pk, status='CLOSED'):
        db = get_db()
        db.execute('UPDATE risks SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                   (status, risk_pk))
        db.commit()

    @staticmethod
    def create_draft_from_suggestion(source_module, source_table, source_record_id, risk_title,
                                      risk_owner_id, created_by, risk_description=None,
                                      category_code=None, link_type='TRIGGER'):
        """Human-in-the-loop draft creation from a Suggested-Risks inbox item. Likelihood/impact
        default to a neutral 3/3 (MODERATE) — the risk owner must review and re-score before the
        risk leaves DRAFT status."""
        category = RiskCategory.get_by_code(category_code or MODULE_CATEGORY_MAP.get(source_module, 'OPR'))
        risk = Risk.create(
            risk_title=risk_title,
            category_id=category.id if category else None,
            likelihood=3, impact=3,
            risk_owner_id=risk_owner_id, created_by=created_by,
            risk_description=risk_description, status='DRAFT',
        )
        RiskSourceLink.create(risk.id, source_module, source_table, source_record_id,
                               link_type=link_type, linked_by=created_by)
        return risk


def get_pending_risk_suggestions():
    """
    Surfaces high-severity / open records from the 13 existing modules that have
    no risk_source_links row yet, for the human-reviewed "Suggested Risks" inbox.
    Never creates a risk automatically — each entry must be explicitly promoted
    by a risk owner via Risk.create_draft_from_suggestion(). Best-effort: a
    failing per-module query is skipped rather than breaking the whole inbox
    (e.g. a table not present in a given deployment).
    """
    db = get_db()
    suggestions = []

    def _add(source_module, source_table, rows, title_fn, desc_fn):
        for row in rows:
            row = dict(row)
            record_id = row['id']
            if RiskSourceLink.is_linked(source_module, source_table, record_id):
                continue
            suggestions.append({
                'source_module': source_module,
                'source_table': source_table,
                'source_record_id': record_id,
                'title': title_fn(row),
                'description': desc_fn(row),
                'suggested_category_code': MODULE_CATEGORY_MAP.get(source_module, 'OPR'),
            })

    queries = [
        ('aml', 'tm_alerts',
         "SELECT * FROM tm_alerts WHERE UPPER(alert_severity) IN ('HIGH','CRITICAL') "
         "AND UPPER(status) NOT IN ('CLOSED','RESOLVED','DISMISSED') ORDER BY id DESC LIMIT 50",
         lambda r: f"AML Alert {r.get('alert_reference') or r['id']}",
         lambda r: (r.get('alert_description') or '')[:500]),

        ('aml', 'suspicious_activities',
         "SELECT * FROM suspicious_activities WHERE decision IS NULL "
         "AND UPPER(COALESCE(investigation_status,'')) NOT IN ('CLOSED','COMPLETED') ORDER BY id DESC LIMIT 50",
         lambda r: f"Pending SAR {r.get('sar_reference') or r['id']}",
         lambda r: (r.get('activity_description') or '')[:500]),

        ('screening', 'screening_queue',
         "SELECT * FROM screening_queue WHERE UPPER(priority) = 'HIGH' "
         "AND UPPER(status) NOT IN ('CLOSED','RESOLVED') ORDER BY id DESC LIMIT 50",
         lambda r: f"Unresolved screening match: {r.get('match_name') or r.get('entity_name') or r['id']}",
         lambda r: (r.get('match_details') or '')[:500]),

        ('whistleblowing', 'whistleblowing_cases',
         "SELECT * FROM whistleblowing_cases WHERE UPPER(COALESCE(severity,'')) IN ('HIGH','CRITICAL') "
         "AND UPPER(status) NOT IN ('CLOSED','RESOLVED','DISMISSED') ORDER BY id DESC LIMIT 50",
         lambda r: f"Whistleblowing case {r.get('case_number') or r['id']}",
         lambda r: (r.get('title') or r.get('description') or '')[:500]),

        ('consumer_protection', 'consumer_complaints',
         "SELECT * FROM consumer_complaints WHERE days_remaining_to_deadline < 0 "
         "AND UPPER(status) NOT IN ('CLOSED','RESOLVED') ORDER BY id DESC LIMIT 50",
         lambda r: f"Complaint past CBE deadline: CP-{r['id']}",
         lambda r: (r.get('complaint_description') or '')[:500]),

        ('cyber', 'cyber_incidents',
         "SELECT * FROM cyber_incidents WHERE UPPER(severity) IN ('HIGH','CRITICAL') "
         "AND UPPER(status) != 'CLOSED' ORDER BY id DESC LIMIT 50",
         lambda r: f"Cyber incident {r.get('incident_number') or r['id']}",
         lambda r: (r.get('incident_description') or '')[:500]),

        ('data_protection', 'data_breaches',
         "SELECT * FROM data_breaches WHERE UPPER(severity) IN ('HIGH','CRITICAL') "
         "AND UPPER(status) != 'CLOSED' ORDER BY id DESC LIMIT 50",
         lambda r: f"Data breach {r.get('breach_number') or r['id']}",
         lambda r: (r.get('breach_description') or '')[:500]),

        ('data_protection', 'data_subject_requests',
         "SELECT * FROM data_subject_requests WHERE overdue = 1 "
         "AND UPPER(COALESCE(status,'')) NOT IN ('CLOSED') ORDER BY id DESC LIMIT 50",
         lambda r: f"Overdue data subject request {r.get('request_reference') or r['id']}",
         lambda r: (r.get('request_description') or '')[:500]),

        ('merchant_kyc', 'merchants',
         "SELECT * FROM merchants WHERE UPPER(COALESCE(risk_level,'')) = 'CRITICAL' ORDER BY id DESC LIMIT 50",
         lambda r: f"Critical-risk merchant: {r.get('merchant_name') or r['id']}",
         lambda r: (r.get('risk_notes') or '')[:500]),

        ('coi', 'coi_campaign_employees',
         "SELECT * FROM coi_campaign_employees WHERE status = 'overdue' ORDER BY id DESC LIMIT 50",
         lambda r: f"Overdue COI declaration (employee #{r.get('employee_id')})",
         lambda r: 'COI declaration not submitted by campaign deadline.'),

        ('ghe', 'ghe_declarations',
         "SELECT * FROM ghe_declarations WHERE (is_government_official = 1 OR estimated_value_egp > 2000) "
         "AND status NOT IN ('approved','rejected') ORDER BY id DESC LIMIT 50",
         lambda r: f"GHE declaration {r.get('declaration_number') or r['id']}",
         lambda r: (r.get('business_purpose') or r.get('description') or '')[:500]),

        ('cobec', 'cobec_declarations',
         "SELECT * FROM cobec_declarations WHERE has_known_violations = 1 OR has_prior_misconduct = 1 "
         "ORDER BY id DESC LIMIT 50",
         lambda r: f"COBEC disclosed violation (employee #{r.get('employee_id')})",
         lambda r: (r.get('violation_details') or r.get('misconduct_details') or '')[:500]),

        ('policies', 'policies',
         "SELECT * FROM policies WHERE status = 'published' AND next_review_date < CURRENT_DATE "
         "ORDER BY next_review_date LIMIT 50",
         lambda r: f"Overdue policy review: {r.get('policy_name') or r['id']}",
         lambda r: f"Policy review was due {r.get('next_review_date')}."),

        ('training', 'training_enrollments',
         "SELECT te.* FROM training_enrollments te JOIN training_courses tc ON tc.id = te.course_id "
         "WHERE te.status = 'overdue' AND tc.is_mandatory = 1 ORDER BY te.id DESC LIMIT 50",
         lambda r: f"Overdue mandatory training (employee #{r.get('employee_id')})",
         lambda r: f"Course: {r.get('course_name') or r.get('course_id')}"),
    ]

    for source_module, source_table, sql, title_fn, desc_fn in queries:
        try:
            rows = db.execute(sql).fetchall()
            _add(source_module, source_table, rows, title_fn, desc_fn)
        except Exception:
            db.rollback()
            continue

    return suggestions
