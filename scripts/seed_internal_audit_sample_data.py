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
Seeds a practical, illustrative sample dataset for the Internal Audit
module: a risk-based audit universe, an approved annual audit plan,
engagements at different lifecycle stages (planned/fieldwork/reporting/
closed), audit programs with recorded test results, and findings spanning
every severity and status in the remediation lifecycle — including one
fully verified-and-closed finding to demonstrate independent verification.

Intent: give a new user a populated, realistic pipeline to learn the audit
lifecycle from, and to demonstrate the module's integration with Risk
Management (audit universe linked to risks, control test results recorded
from audit procedures, a finding linked to the risk register).

Run AFTER scripts/mig_internal_audit_schema.py and, ideally, AFTER
scripts/seed_risk_management_sample_data.py (this script links to the
sample risks/controls created there when present, but degrades gracefully
if they are not — e.g. run this against a deployment that seeded ERM sample
data separately).

Idempotent — every insert is skipped if a record with the same natural key
(auditable_area / audit_name / finding_title) already exists, so it's safe
to re-run.

Run with: python scripts/seed_internal_audit_sample_data.py
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from database.db import get_db
from models.internal_audit import (
    AuditUniverse, AnnualAuditPlan, AuditProject, AuditTeamMember, AuditProgram,
    AuditFinding,
)

app = create_app()

DEPT_CODES = ['COMP', 'IT', 'FIN', 'OPS', 'LEGAL', 'HR']


def _get_real_users(db):
    rows = db.execute(
        """SELECT id, role FROM users
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


def _find_risk_pk(db, risk_title_like):
    row = db.execute(
        "SELECT id FROM risks WHERE risk_title ILIKE %s LIMIT 1", (f'%{risk_title_like}%',)
    ).fetchone()
    return row[0] if row else None


def _find_control_pk(db, control_code):
    row = db.execute("SELECT id FROM controls WHERE control_code = %s", (control_code,)).fetchone()
    return row[0] if row else None


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

        today = date.today()

        # -------------------------------------------------------------
        # Audit Universe — the risk-based inventory of auditable areas
        # -------------------------------------------------------------
        SAMPLE_UNIVERSE = [
            dict(area='AML/CFT Transaction Monitoring Program', risk_level='CRITICAL', dept_code='COMP',
                 freq='ANNUAL', linked_risk_hint='Transaction Monitoring Threshold'),
            dict(area='Merchant Onboarding & KYC', risk_level='HIGH', dept_code='COMP',
                 freq='ANNUAL', linked_risk_hint=None),
            dict(area='IT General Controls & Cybersecurity', risk_level='HIGH', dept_code='IT',
                 freq='ANNUAL', linked_risk_hint='Unpatched Vulnerabilities'),
            dict(area='Payment Settlement & Reconciliation', risk_level='HIGH', dept_code='FIN',
                 freq='SEMI_ANNUAL', linked_risk_hint='Manual Reconciliation Errors'),
            dict(area='Regulatory Reporting to CBE', risk_level='HIGH', dept_code='COMP',
                 freq='ANNUAL', linked_risk_hint='Delayed Regulatory Reporting'),
            dict(area='Treasury & Liquidity Management', risk_level='MEDIUM', dept_code='FIN',
                 freq='ANNUAL', linked_risk_hint='Real-Time Liquidity Buffer'),
            dict(area='Vendor & Third-Party Management', risk_level='MEDIUM', dept_code='OPS',
                 freq='BIENNIAL', linked_risk_hint='Single International Remittance Partner'),
            dict(area='Human Resources & Payroll', risk_level='MEDIUM', dept_code='HR',
                 freq='BIENNIAL', linked_risk_hint=None),
            dict(area='Data Protection & Privacy Compliance', risk_level='MEDIUM', dept_code='LEGAL',
                 freq='ANNUAL', linked_risk_hint=None),
            dict(area='Consumer Protection & Complaints Handling', risk_level='MEDIUM', dept_code='COMP',
                 freq='ANNUAL', linked_risk_hint='Complaint Handling Turnaround'),
        ]

        universe_ids = {}
        for u in SAMPLE_UNIVERSE:
            existing = db.execute('SELECT id FROM audit_universe WHERE auditable_area = %s', (u['area'],)).fetchone()
            if existing:
                print(f"  Auditable area '{u['area']}' already exists, skipping.")
                universe_pk = existing[0]
            else:
                area = AuditUniverse.create(
                    auditable_area=u['area'],
                    area_description=f"Risk-based audit coverage of {u['area'].lower()}.",
                    risk_level=u['risk_level'], department_id=depts.get(u['dept_code']),
                    audit_frequency=u['freq'],
                )
                universe_pk = area.id
                print(f"  Created auditable area: {u['area']}")
            universe_ids[u['area']] = universe_pk

            if u['linked_risk_hint']:
                risk_pk = _find_risk_pk(db, u['linked_risk_hint'])
                if risk_pk:
                    AuditUniverse.link_risk(universe_pk, risk_pk)

        # -------------------------------------------------------------
        # Annual Audit Plan — approved for the current year
        # -------------------------------------------------------------
        plan_name = f'{today.year} Annual Internal Audit Plan'
        existing_plan = db.execute(
            'SELECT id, status FROM annual_audit_plans WHERE plan_year = %s', (today.year,)
        ).fetchone()
        if existing_plan:
            print(f"  Annual audit plan for {today.year} already exists, skipping.")
            plan_id = existing_plan[0]
        else:
            plan = AnnualAuditPlan.create(plan_year=today.year, plan_name=plan_name)
            plan_id = plan.id
            AnnualAuditPlan.approve(plan_id, approved_by=admin_id)
            print(f"  Created and approved {plan_name}")

        # -------------------------------------------------------------
        # Audit Projects (engagements) at different lifecycle stages
        # -------------------------------------------------------------
        SAMPLE_PROJECTS = [
            dict(name=f'{today.year} AML/CFT Transaction Monitoring Audit', area='AML/CFT Transaction Monitoring Program',
                 scope='Design and operating effectiveness of TM alert generation, investigation, and closure.',
                 status='CLOSED', start_offset=-120, end_offset=-60),
            dict(name='Merchant KYC Onboarding Review', area='Merchant Onboarding & KYC',
                 scope='Completeness of onboarding due diligence and enhanced due diligence triggers.',
                 status='REPORTING', start_offset=-45, end_offset=-10),
            dict(name='IT General Controls Audit', area='IT General Controls & Cybersecurity',
                 scope='Access management, change management, and vulnerability remediation controls.',
                 status='FIELDWORK', start_offset=-20, end_offset=30),
            dict(name='Settlement Reconciliation Process Audit', area='Payment Settlement & Reconciliation',
                 scope='Daily reconciliation completeness, exception handling, and sign-off evidence.',
                 status='PLANNED', start_offset=30, end_offset=60),
            dict(name='CBE Regulatory Reporting Compliance Review', area='Regulatory Reporting to CBE',
                 scope='Timeliness and accuracy of large-transaction and periodic regulatory submissions.',
                 status='FIELDWORK', start_offset=-15, end_offset=25),
        ]

        project_ids = {}
        for idx, p in enumerate(SAMPLE_PROJECTS):
            existing = db.execute('SELECT id FROM audit_projects WHERE audit_name = %s', (p['name'],)).fetchone()
            if existing:
                print(f"  Audit engagement '{p['name']}' already exists, skipping.")
                project_pk = existing[0]
            else:
                project = AuditProject.create(
                    audit_name=p['name'], lead_auditor_id=mgr(idx), plan_id=plan_id,
                    auditable_area_id=universe_ids.get(p['area']), audit_type='INTERNAL',
                    audit_scope=p['scope'],
                    planned_start_date=today + timedelta(days=p['start_offset']),
                    planned_end_date=today + timedelta(days=p['end_offset']),
                )
                project_pk = project.id
                AuditTeamMember.add(project_pk, mgr(idx + 1), role_on_engagement='AUDITOR')
                if p['status'] in ('FIELDWORK', 'REPORTING', 'CLOSED'):
                    AuditProject.update_status(project_pk, 'FIELDWORK')
                if p['status'] in ('REPORTING', 'CLOSED'):
                    AuditProject.update_status(project_pk, 'REPORTING')
                if p['status'] == 'CLOSED':
                    AuditProject.update_status(project_pk, 'CLOSED')
                print(f"  Created audit engagement: {p['name']} ({p['status']})")
            project_ids[p['name']] = project_pk

        # -------------------------------------------------------------
        # Audit Programs (procedures) — for the closed AML audit and the
        # in-progress IT audit, with recorded results (syncs into
        # control_test_results for the linked controls).
        # -------------------------------------------------------------
        aml_project_id = project_ids.get(SAMPLE_PROJECTS[0]['name'])
        it_project_id = project_ids.get(SAMPLE_PROJECTS[2]['name'])

        def _seed_program(project_id, steps):
            if not project_id:
                return
            existing_steps = db.execute(
                'SELECT COUNT(*) AS c FROM audit_programs WHERE project_id = %s', (project_id,)
            ).fetchone()
            if existing_steps and dict(existing_steps)['c'] > 0:
                print(f"  Audit program for project {project_id} already exists, skipping.")
                return
            for step_idx, (description, control_code, result) in enumerate(steps):
                control_pk = _find_control_pk(db, control_code) if control_code else None
                program = AuditProgram.create(project_id, description, control_id=control_pk)
                if result:
                    AuditProgram.record_result(
                        program.id, result, performed_by=mgr(step_idx),
                        workpaper_reference=f'WP-{program.step_number:02d}', audit_project_id=project_id,
                    )

        _seed_program(aml_project_id, [
            ('Sample 25 closed TM alerts and verify documented investigation rationale.', 'CTL-FCR-001', 'PARTIALLY_EFFECTIVE'),
            ('Confirm segregation of duties between alert investigation and closure roles.', None, None),
            ('Re-perform threshold back-testing against six months of transaction data.', 'CTL-FCR-001', 'EFFECTIVE'),
        ])
        _seed_program(it_project_id, [
            ('Verify remediation status of critical/high vulnerabilities from the latest penetration test.', 'CTL-TEC-001', 'PARTIALLY_EFFECTIVE'),
            ('Review quarterly privileged access recertification evidence.', None, None),
            ('Test change management approval trail for a sample of production deployments.', None, None),
        ])

        # -------------------------------------------------------------
        # Findings — span every severity and lifecycle status, including
        # one independently verified-and-closed finding.
        # -------------------------------------------------------------
        SAMPLE_FINDINGS = [
            dict(project=SAMPLE_PROJECTS[0]['name'], title='TM Alerts Closed Without Documented Rationale',
                 severity='CRITICAL',
                 description='15% of sampled high-severity TM alerts were closed without a documented '
                              'investigation rationale, contrary to policy.',
                 root_cause='Investigation template does not enforce a mandatory rationale field.',
                 recommendation='Make the rationale field mandatory in the alert closure workflow and '
                                 'retrain the investigation team.',
                 lifecycle='VERIFIED_CLOSED', days_out=-30),
            dict(project=SAMPLE_PROJECTS[0]['name'], title='Segregation of Duties Gap in Alert Lifecycle',
                 severity='HIGH',
                 description='The same analyst can both investigate and close a TM alert with no independent '
                              'second check for medium-severity alerts.',
                 root_cause='Workflow configuration only enforces dual review for high/critical severity.',
                 recommendation='Extend the dual-review requirement to medium-severity alerts.',
                 lifecycle='REMEDIATION_IN_PROGRESS', days_out=20),
            dict(project=SAMPLE_PROJECTS[2]['name'], title='Critical Vulnerabilities Unpatched Beyond SLA',
                 severity='HIGH',
                 description='Three critical vulnerabilities identified in the Q4 penetration test remain '
                              'open more than 30 days past the internal remediation SLA.',
                 root_cause='Patch deployment is dependent on a change window shared with unrelated releases.',
                 recommendation='Establish an expedited emergency patch process for critical vulnerabilities.',
                 lifecycle='OPEN', days_out=15, link_to_risk_hint='Unpatched Vulnerabilities'),
            dict(project=SAMPLE_PROJECTS[2]['name'], title='Quarterly Privileged Access Review Not Evidenced',
                 severity='MEDIUM',
                 description='No evidence of the quarterly privileged access recertification was available '
                              'for the two most recent quarters.',
                 root_cause='Recertification is performed informally over email rather than through a '
                             'tracked workflow.',
                 recommendation='Implement a tracked privileged-access recertification workflow with an '
                                 'audit trail.',
                 lifecycle='MANAGEMENT_RESPONSE_RECEIVED', days_out=25),
            dict(project=SAMPLE_PROJECTS[1]['name'], title='Enhanced Due Diligence Inconsistently Applied',
                 severity='HIGH',
                 description='Enhanced due diligence steps were not consistently performed for merchants '
                              'onboarded in higher-risk categories.',
                 root_cause='EDD triggers rely on manual category tagging rather than a system-enforced rule.',
                 recommendation='Automate EDD triggering based on merchant risk category at onboarding.',
                 lifecycle='OPEN', days_out=-10),  # deliberately overdue — illustrates the follow-up/escalation view
            dict(project=SAMPLE_PROJECTS[1]['name'], title='Minor Merchant File Documentation Gaps',
                 severity='LOW',
                 description='A small number of merchant files were missing a secondary contact document, '
                              'though all mandatory KYC documents were present.',
                 root_cause='Checklist does not distinguish mandatory from supplementary documents.',
                 recommendation='Clarify the onboarding checklist to separate mandatory and supplementary items.',
                 lifecycle='OPEN', days_out=60),
        ]

        for f in SAMPLE_FINDINGS:
            project_pk = project_ids.get(f['project'])
            if not project_pk:
                continue
            existing = db.execute('SELECT id FROM audit_findings WHERE finding_title = %s', (f['title'],)).fetchone()
            if existing:
                print(f"  Finding '{f['title']}' already exists, skipping.")
                continue
            responsible = mgr(1)
            finding = AuditFinding.create(
                project_id=project_pk, finding_title=f['title'], severity=f['severity'],
                finding_description=f['description'], root_cause=f['root_cause'],
                recommendation=f['recommendation'], responsible_person_id=responsible,
                target_date=today + timedelta(days=f['days_out']),
            )
            # Advance the finding through however much of the remediation
            # lifecycle its sample status calls for.
            if f['lifecycle'] in ('MANAGEMENT_RESPONSE_RECEIVED', 'REMEDIATION_IN_PROGRESS', 'VERIFIED_CLOSED'):
                AuditFinding.record_management_response(
                    finding.id,
                    management_response='Management agrees with the finding and has committed to the recommended action.',
                    agreed_action=f['recommendation'],
                )
            if f['lifecycle'] in ('REMEDIATION_IN_PROGRESS', 'VERIFIED_CLOSED'):
                AuditFinding.mark_remediation_in_progress(finding.id)
            if f['lifecycle'] == 'VERIFIED_CLOSED':
                AuditFinding.mark_remediated(finding.id)
                # Independent verifier must differ from the responsible person
                # and must be a team member on the engagement.
                verifier = mgr(0) if mgr(0) != responsible else mgr(2)
                AuditTeamMember.add(project_pk, verifier, role_on_engagement='REVIEWER')
                AuditFinding.verify_and_close(
                    finding.id, verified_by=verifier,
                    verification_notes='Re-tested a sample of alerts closed after the process change; '
                                        'rationale field is now consistently populated.',
                )
            if f.get('link_to_risk_hint'):
                risk_pk = _find_risk_pk(db, f['link_to_risk_hint'])
                if risk_pk:
                    AuditFinding.link_to_risk(finding.id, risk_pk, linked_by=admin_id)
            print(f"  Created finding: {f['title']} ({f['severity']}, {f['lifecycle']})")

        db.commit()
        print("Internal Audit sample data seed complete.")


if __name__ == "__main__":
    seed()
