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
Seeds a practical, illustrative sample dataset for the Enterprise Risk
Management module: risk register entries, controls (RCM), control test
results, KRIs with historical measurements, risk treatments (mitigation
action plans), and risk appetite statements.

Intent: give a new user a populated, realistic register to learn the
workflow from (heat map, KRI dashboard, treatment lifecycle) rather than an
empty module. Content is illustrative, not a real risk assessment.

Run AFTER scripts/mig_risk_management_schema.py and scripts/seed_risk_categories.py.
Idempotent — every insert is skipped if a record with the same natural key
(risk_title / control_code / kri_name) already exists, so it's safe to re-run.

Real users/departments already present in the deployment are looked up
dynamically (by role / department code) rather than hardcoded, so this
script is portable across environments — only test/verification accounts
and departments are excluded.

Run with: python scripts/seed_risk_management_sample_data.py
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from database.db import get_db
from models.risk import (
    Risk, RiskCategory, Control, RiskControl, ControlTestResult, KRI,
    KRIMeasurement, RiskTreatment, RiskAppetiteStatement,
)

app = create_app()

DEPT_CODES = ['COMP', 'IT', 'FIN', 'OPS', 'LEGAL', 'HR']


def _get_real_users(db):
    """Real (non-test/verification) admin + manager accounts, oldest first."""
    rows = db.execute(
        """SELECT id, first_name, last_name, role FROM users
           WHERE role IN ('admin', 'manager')
           AND email NOT ILIKE '%%test%%' AND email NOT ILIKE '%%verify%%'
           ORDER BY id"""
    ).fetchall()
    return [dict(r) for r in rows]


def _get_real_departments(db):
    rows = db.execute(
        "SELECT id, code FROM departments WHERE code = ANY(%s) ORDER BY id", (DEPT_CODES,)
    ).fetchall()
    return {r['code']: r['id'] for r in [dict(r) for r in rows]}


def seed():
    with app.app_context():
        db = get_db()

        users = _get_real_users(db)
        if len(users) < 3:
            print("Not enough real (non-test) admin/manager users found — skipping sample data seed.")
            return
        depts = _get_real_departments(db)
        admin_id = next((u['id'] for u in users if u['role'] == 'admin'), users[0]['id'])
        managers = [u['id'] for u in users if u['role'] == 'manager'] or [admin_id]

        def mgr(i):
            return managers[i % len(managers)]

        cat = {c.category_code: c.id for c in RiskCategory.get_all(include_inactive=True)}

        today = date.today()

        # -------------------------------------------------------------
        # Sample Risk Register — spans every category with a realistic
        # spread of scores across the 5x5 heat map.
        # -------------------------------------------------------------
        SAMPLE_RISKS = [
            dict(risk_title='Transaction Monitoring Threshold Miscalibration',
                 risk_description='TM rule thresholds have not been recalibrated since go-live, risking '
                                   'both missed true positives and an unmanageable false-positive backlog.',
                 category_code='FCR', dept_code='COMP', likelihood=4, impact=4,
                 existing_controls='Dual review of high-severity alerts before closure.',
                 risk_response='MITIGATE', residual_likelihood=3, residual_impact=3, control_effectiveness='PARTIALLY_EFFECTIVE'),
            dict(risk_title='Unpatched Vulnerabilities in Payment Gateway API',
                 risk_description='Critical/high vulnerabilities identified in the last penetration test '
                                   'remain open beyond the internal remediation SLA.',
                 category_code='TEC', dept_code='IT', likelihood=3, impact=5,
                 existing_controls='Quarterly penetration testing of payment APIs.',
                 risk_response='MITIGATE', residual_likelihood=2, residual_impact=5, control_effectiveness='PARTIALLY_EFFECTIVE'),
            dict(risk_title='Manual Reconciliation Errors in Merchant Settlement',
                 risk_description='Residual manual steps in the daily settlement reconciliation process '
                                   'create exposure to posting errors and delayed merchant payouts.',
                 category_code='OPR', dept_code='FIN', likelihood=3, impact=3,
                 existing_controls='Automated reconciliation with exception reporting.',
                 risk_response='MITIGATE', residual_likelihood=2, residual_impact=3, control_effectiveness='EFFECTIVE'),
            dict(risk_title='Concentration Risk with Single International Remittance Partner',
                 risk_description='A single partner processes the large majority of outbound remittance '
                                   'volume; an outage or contract termination would disrupt the channel.',
                 category_code='TPR', dept_code='OPS', likelihood=2, impact=4,
                 existing_controls='Annual third-party risk assessment for critical vendors.',
                 risk_response='TRANSFER', residual_likelihood=2, residual_impact=3, control_effectiveness='PARTIALLY_EFFECTIVE'),
            dict(risk_title='Delayed Regulatory Reporting to CBE',
                 risk_description='Large cash transaction and suspicious activity reports have occasionally '
                                   'missed the CBE-mandated submission window during peak volume periods.',
                 category_code='CMP', dept_code='COMP', likelihood=2, impact=5,
                 existing_controls='Automated report generation with dual sign-off.',
                 risk_response='MITIGATE', residual_likelihood=1, residual_impact=5, control_effectiveness='EFFECTIVE'),
            dict(risk_title='Insufficient Real-Time Liquidity Buffer on Peak Settlement Days',
                 risk_description='Intraday liquidity buffer policy has not been re-assessed against '
                                   'observed peak-day settlement volumes.',
                 category_code='LIQ', dept_code='FIN', likelihood=2, impact=5,
                 existing_controls='Daily liquidity position monitoring and escalation.',
                 risk_response='MITIGATE', residual_likelihood=2, residual_impact=4, control_effectiveness='PARTIALLY_EFFECTIVE'),
            dict(risk_title='Inconsistent Complaint Handling Turnaround Across Channels',
                 risk_description='Complaint resolution times vary significantly between the call centre '
                                   'and in-app channels, risking CBE consumer-protection turnaround breaches.',
                 category_code='CON', dept_code='COMP', likelihood=3, impact=2,
                 existing_controls='Weekly complaint ageing review by compliance.',
                 risk_response='MITIGATE', residual_likelihood=2, residual_impact=2, control_effectiveness='EFFECTIVE'),
            dict(risk_title='Legacy On-Premises Server Approaching End-of-Life',
                 risk_description='A small number of internal reporting servers are on an end-of-life OS '
                                   'version with vendor support ending next year.',
                 category_code='TEC', dept_code='IT', likelihood=1, impact=3,
                 existing_controls='Isolated network segment with restricted access.',
                 risk_response='ACCEPT', residual_likelihood=None, residual_impact=None, control_effectiveness=None),
            dict(risk_title='Social Media Backlash Risk from Service Outages',
                 risk_description='Recent app outages generated visible negative sentiment on social media, '
                                   'with potential to affect customer trust and acquisition.',
                 category_code='REP', dept_code='OPS', likelihood=3, impact=3,
                 existing_controls='Incident communications playbook and status page.',
                 risk_response='MITIGATE', residual_likelihood=2, residual_impact=3, control_effectiveness='PARTIALLY_EFFECTIVE'),
            dict(risk_title='Merchant Cash-Advance Default Risk in High-Risk Verticals',
                 risk_description='Underwriting criteria for cash-advance products have not been tightened '
                                   'despite rising default rates in certain high-risk merchant verticals.',
                 category_code='CRD', dept_code='FIN', likelihood=3, impact=4,
                 existing_controls='Manual underwriting review above a fixed exposure threshold.',
                 risk_response='MITIGATE', residual_likelihood=2, residual_impact=4, control_effectiveness='PARTIALLY_EFFECTIVE'),
        ]

        risk_by_category = {}
        for idx, r in enumerate(SAMPLE_RISKS):
            existing = db.execute('SELECT id FROM risks WHERE risk_title = %s', (r['risk_title'],)).fetchone()
            if existing:
                print(f"  Risk '{r['risk_title']}' already exists, skipping.")
                risk_pk = existing[0]
            else:
                risk = Risk.create(
                    risk_title=r['risk_title'],
                    risk_description=r['risk_description'],
                    category_id=cat.get(r['category_code']),
                    department_id=depts.get(r['dept_code']),
                    likelihood=r['likelihood'], impact=r['impact'],
                    risk_owner_id=mgr(idx), created_by=admin_id,
                    existing_controls=r['existing_controls'],
                    risk_response=r['risk_response'],
                    next_review_date=today + timedelta(days=90),
                )
                risk_pk = risk.id
                if r['residual_likelihood'] and r['residual_impact']:
                    Risk.update_scoring(
                        risk_pk, r['likelihood'], r['impact'],
                        residual_likelihood=r['residual_likelihood'], residual_impact=r['residual_impact'],
                        control_effectiveness=r['control_effectiveness'], changed_by=mgr(idx),
                        change_reason='Residual scoring after control effectiveness review',
                    )
                print(f"  Created risk: {r['risk_title']} ({risk.risk_id})")
            risk_by_category.setdefault(r['category_code'], []).append(risk_pk)

        # -------------------------------------------------------------
        # Control library (RCM) + links to the risks they mitigate
        # -------------------------------------------------------------
        SAMPLE_CONTROLS = [
            dict(control_code='CTL-FCR-001', control_name='Dual Review of High-Severity TM Alerts',
                 control_type='DETECTIVE', control_nature='MANUAL', dept_code='COMP',
                 testing_frequency='MONTHLY', category_code='FCR'),
            dict(control_code='CTL-TEC-001', control_name='Quarterly Penetration Testing of Payment APIs',
                 control_type='PREVENTIVE', control_nature='MANUAL', dept_code='IT',
                 testing_frequency='QUARTERLY', category_code='TEC'),
            dict(control_code='CTL-OPR-001', control_name='Automated Settlement Reconciliation with Exception Alerts',
                 control_type='DETECTIVE', control_nature='AUTOMATED', dept_code='FIN',
                 testing_frequency='QUARTERLY', category_code='OPR'),
            dict(control_code='CTL-TPR-001', control_name='Annual Third-Party Risk Assessment for Critical Vendors',
                 control_type='PREVENTIVE', control_nature='MANUAL', dept_code='OPS',
                 testing_frequency='ANNUAL', category_code='TPR'),
            dict(control_code='CTL-CMP-001', control_name='Automated CBE Regulatory Report Generation & Dual Sign-off',
                 control_type='PREVENTIVE', control_nature='AUTOMATED', dept_code='COMP',
                 testing_frequency='QUARTERLY', category_code='CMP'),
            dict(control_code='CTL-LIQ-001', control_name='Daily Liquidity Position Monitoring & Escalation',
                 control_type='DETECTIVE', control_nature='MANUAL', dept_code='FIN',
                 testing_frequency='QUARTERLY', category_code='LIQ'),
        ]

        control_ids = {}
        for idx, c in enumerate(SAMPLE_CONTROLS):
            existing = db.execute('SELECT id FROM controls WHERE control_code = %s', (c['control_code'],)).fetchone()
            if existing:
                print(f"  Control {c['control_code']} already exists, skipping.")
                control_pk = existing[0]
            else:
                control = Control.create(
                    control_code=c['control_code'], control_name=c['control_name'],
                    control_type=c['control_type'], control_nature=c['control_nature'],
                    control_owner_id=mgr(idx), department_id=depts.get(c['dept_code']),
                    testing_frequency=c['testing_frequency'],
                    control_description=f"{c['control_name']} — mitigates {c['category_code']} category risk.",
                )
                control_pk = control.id
                print(f"  Created control: {c['control_code']} — {c['control_name']}")
            control_ids[c['control_code']] = (control_pk, c['category_code'])

            # Link to every sample risk in the matching category
            for risk_pk in risk_by_category.get(c['category_code'], []):
                RiskControl.link(risk_pk, control_pk, reliance_level='PRIMARY')

            # One illustrative test result per control, mostly effective
            existing_test = db.execute(
                'SELECT id FROM control_test_results WHERE control_id = %s', (control_pk,)
            ).fetchone()
            if not existing_test:
                result = 'PARTIALLY_EFFECTIVE' if idx % 3 == 0 else 'EFFECTIVE'
                ControlTestResult.create(
                    control_id=control_pk, tested_by=mgr(idx + 1),
                    test_date=today - timedelta(days=20 + idx * 5),
                    test_procedure=f"Walkthrough and sample testing of '{c['control_name']}' operating effectiveness.",
                    result=result,
                    exceptions_noted=None if result == 'EFFECTIVE' else 'Minor timing exceptions noted in a small sample of cases.',
                )
                Control.record_test_result(
                    control_pk, result, today - timedelta(days=20 + idx * 5),
                    next_test_due_date=today + timedelta(days=70),
                )

        # -------------------------------------------------------------
        # KRIs + historical measurements
        # -------------------------------------------------------------
        SAMPLE_KRIS = [
            dict(kri_name='TM Alert Backlog Aged Over 48 Hours', category_code='FCR', unit='alerts',
                 freq='WEEKLY', target=10, warning=20, breach=40, direction='UPPER',
                 history=[12, 18, 22, 35, 28, 19]),
            dict(kri_name='Critical/High Vulnerabilities Open Beyond SLA', category_code='TEC', unit='count',
                 freq='MONTHLY', target=0, warning=3, breach=6, direction='UPPER',
                 history=[2, 4, 7, 5]),
            dict(kri_name='CBE Regulatory Report Submission Lateness', category_code='CMP', unit='days late',
                 freq='MONTHLY', target=0, warning=1, breach=3, direction='UPPER',
                 history=[0, 0, 1, 0]),
            dict(kri_name='Settlement Liquidity Buffer Ratio', category_code='LIQ', unit='%',
                 freq='MONTHLY', target=150, warning=120, breach=100, direction='LOWER',
                 history=[165, 148, 130, 118]),
        ]

        for kdef in SAMPLE_KRIS:
            existing = db.execute('SELECT id FROM kris WHERE kri_name = %s', (kdef['kri_name'],)).fetchone()
            if existing:
                print(f"  KRI '{kdef['kri_name']}' already exists, skipping.")
                continue
            risk_pk = (risk_by_category.get(kdef['category_code']) or [None])[0]
            kri = KRI.create(
                kri_name=kdef['kri_name'], risk_id=risk_pk,
                kri_description=f"Tracks {kdef['kri_name'].lower()} for the {kdef['category_code']} risk category.",
                unit_of_measure=kdef['unit'], measurement_frequency=kdef['freq'],
                target_value=kdef['target'], warning_threshold=kdef['warning'],
                breach_threshold=kdef['breach'], direction=kdef['direction'],
                owner_id=mgr(0),
            )
            # Oldest-first history, most recent last, roughly one period apart
            n = len(kdef['history'])
            for i, value in enumerate(kdef['history']):
                measurement_date = today - timedelta(days=(n - i) * 30 if kdef['freq'] == 'MONTHLY' else (n - i) * 7)
                _, status = KRIMeasurement.create(
                    kri.id, measurement_date, value,
                    notes='Routine measurement.', recorded_by=mgr(0),
                )
            print(f"  Created KRI: {kdef['kri_name']} ({n} historical measurements, latest status {status})")

        # -------------------------------------------------------------
        # Risk treatments (mitigation action plans) for the higher-scored risks
        # -------------------------------------------------------------
        SAMPLE_TREATMENTS = [
            dict(category_code='FCR', description='Recalibrate TM rule thresholds based on Q1 false-positive '
                                                     'analysis and re-test against a sample of historical alerts.',
                 treatment_type='MITIGATE', days_out=45, status='IN_PROGRESS'),
            dict(category_code='TEC', description='Remediate outstanding critical/high vulnerabilities from the '
                                                     'latest penetration test and re-scan before sign-off.',
                 treatment_type='MITIGATE', days_out=-10, status='IN_PROGRESS'),  # overdue, illustrates escalation
            dict(category_code='CMP', description='Implement an automated pre-submission validation checklist for '
                                                     'CBE regulatory reports to prevent late filings.',
                 treatment_type='MITIGATE', days_out=60, status='PROPOSED'),
            dict(category_code='LIQ', description='Raise the intraday liquidity buffer policy minimum and add a '
                                                     'real-time dashboard alert for peak settlement days.',
                 treatment_type='MITIGATE', days_out=-5, status='IN_PROGRESS'),  # overdue
            dict(category_code='CRD', description='Tighten underwriting criteria and exposure limits for '
                                                     'cash-advance products in high-risk merchant verticals.',
                 treatment_type='MITIGATE', days_out=-15, status='COMPLETED'),  # ready for independent verification
        ]

        for idx, t in enumerate(SAMPLE_TREATMENTS):
            risk_pk = (risk_by_category.get(t['category_code']) or [None])[0]
            if not risk_pk:
                continue
            existing = db.execute(
                'SELECT id FROM risk_treatments WHERE risk_id = %s AND treatment_description = %s',
                (risk_pk, t['description'])
            ).fetchone()
            if existing:
                print(f"  Treatment for {t['category_code']} risk already exists, skipping.")
                continue
            owner = mgr(idx + 2)
            treatment = RiskTreatment.create(
                risk_id=risk_pk, treatment_description=t['description'], treatment_owner_id=owner,
                target_date=today + timedelta(days=t['days_out']), treatment_type=t['treatment_type'],
                created_by=admin_id,
            )
            if t['status'] != 'PROPOSED':
                RiskTreatment.update_status(
                    treatment.id, t['status'],
                    completion_date=(today + timedelta(days=t['days_out'])) if t['status'] == 'COMPLETED' else None,
                )
            print(f"  Created treatment for {t['category_code']} risk (status {t['status']})")

        # -------------------------------------------------------------
        # Risk appetite statements — one per category, reflecting a
        # payments-regulated entity's typically low tolerance for
        # financial-crime and compliance risk vs. moderate tolerance
        # elsewhere.
        # -------------------------------------------------------------
        # appetite_level uses the standard COSO/ISO-31000-style scale enforced
        # by the risk_appetite_statements CHECK constraint: AVERSE, MINIMAL,
        # CAUTIOUS, OPEN, HUNGRY (least to most risk-tolerant).
        APPETITE = [
            ('FCR', 'AVERSE', 6, 9, 'Zero tolerance for unmanaged financial crime exposure; residual risk must stay in the LOW band.'),
            ('CMP', 'AVERSE', 4, 6, 'Regulatory breaches carry direct CBE sanction risk; appetite is minimal.'),
            ('TEC', 'CAUTIOUS', 9, 12, 'Some residual technology risk is accepted given the pace of change, subject to active monitoring.'),
            ('OPR', 'CAUTIOUS', 9, 12, 'Operational risk is managed to a moderate residual level via automation and dual controls.'),
            ('LIQ', 'AVERSE', 6, 9, 'Liquidity shortfalls directly threaten settlement obligations; appetite is low.'),
            ('TPR', 'CAUTIOUS', 9, 12, 'Some third-party concentration is accepted where contractual and contingency controls exist.'),
            ('CON', 'CAUTIOUS', 9, 12, 'Consumer-protection risk is managed to a moderate level with active complaint monitoring.'),
            ('STR', 'OPEN', 12, 15, 'Strategic risk-taking is expected as part of normal business growth.'),
            ('REP', 'CAUTIOUS', 9, 12, 'Reputational risk is managed reactively via communications protocols.'),
            ('CRD', 'CAUTIOUS', 9, 12, 'Credit risk is accepted within defined underwriting and exposure limits.'),
        ]
        for category_code, level, inherent_max, residual_max, text in APPETITE:
            category_id = cat.get(category_code)
            if not category_id:
                continue
            existing = db.execute(
                'SELECT id FROM risk_appetite_statements WHERE category_id = %s', (category_id,)
            ).fetchone()
            if existing:
                print(f"  Appetite statement for {category_code} already exists, skipping.")
                continue
            RiskAppetiteStatement.create(
                statement_text=text, appetite_level=level,
                max_acceptable_residual_score=residual_max, category_id=category_id,
                max_acceptable_inherent_score=inherent_max,
                effective_from=date(today.year, 1, 1), created_by=admin_id,
            )
            print(f"  Created risk appetite statement for {category_code}")

        db.commit()
        print("Risk Management sample data seed complete.")


if __name__ == "__main__":
    seed()
