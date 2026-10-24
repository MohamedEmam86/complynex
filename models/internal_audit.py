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
Internal Audit models: risk-based audit universe, annual planning, engagements
(team, program/procedures, working papers), and the finding lifecycle with
independent verification. Findings integrate with the Risk Management module
via the shared risk_source_links table (internal_audit is just another
source_module) and via Control.record_test_result for control effectiveness.
"""
from datetime import date

from database.db import get_db
from models.risk import Risk, Control, RiskSourceLink, ControlTestResult


class AuditUniverse:
    def __init__(self, id=None, auditable_area=None, area_description=None, risk_level='MEDIUM',
                 department_id=None, last_audit_date=None, audit_frequency='ANNUAL',
                 next_audit_due=None, responsible_department=None, is_active=True,
                 created_at=None, **kwargs):
        self.id = id
        self.auditable_area = auditable_area
        self.area_description = area_description
        self.risk_level = risk_level
        self.department_id = department_id
        self.last_audit_date = last_audit_date
        self.audit_frequency = audit_frequency
        self.next_audit_due = next_audit_due
        self.responsible_department = responsible_department
        self.is_active = bool(is_active)
        self.created_at = created_at

    @staticmethod
    def get_all(active_only=True):
        db = get_db()
        if active_only:
            rows = db.execute('SELECT * FROM audit_universe WHERE is_active = TRUE ORDER BY auditable_area').fetchall()
        else:
            rows = db.execute('SELECT * FROM audit_universe ORDER BY auditable_area').fetchall()
        return [AuditUniverse(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(universe_id):
        db = get_db()
        row = db.execute('SELECT * FROM audit_universe WHERE id = %s', (universe_id,)).fetchone()
        return AuditUniverse(**dict(row)) if row else None

    @staticmethod
    def create(auditable_area, risk_level='MEDIUM', area_description=None, department_id=None,
               audit_frequency='ANNUAL', responsible_department=None):
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO audit_universe
               (auditable_area, area_description, risk_level, department_id, audit_frequency, responsible_department)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id''',
            (auditable_area, area_description, risk_level, department_id, audit_frequency, responsible_department)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return AuditUniverse.get_by_id(new_id)

    @staticmethod
    def link_risk(universe_id, risk_id):
        db = get_db()
        existing = db.execute(
            'SELECT id FROM audit_universe_risks WHERE universe_id = %s AND risk_id = %s',
            (universe_id, risk_id)
        ).fetchone()
        if existing:
            return existing[0]
        cursor = db.execute(
            'INSERT INTO audit_universe_risks (universe_id, risk_id) VALUES (%s, %s) RETURNING id',
            (universe_id, risk_id)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return new_id

    @staticmethod
    def get_linked_risks(universe_id):
        db = get_db()
        rows = db.execute(
            '''SELECT r.* FROM risks r JOIN audit_universe_risks aur ON aur.risk_id = r.id
               WHERE aur.universe_id = %s''',
            (universe_id,)
        ).fetchall()
        return [Risk(**dict(row)) for row in rows]

    @staticmethod
    def get_derived_risk_score(universe_id):
        """Highest residual (or inherent, if not yet residually scored) score across
        every risk linked to this auditable area — the risk-based input to audit
        planning, shown alongside the manually-set risk_level for the planner to
        weigh and override with justification."""
        db = get_db()
        row = db.execute(
            '''SELECT MAX(COALESCE(r.residual_risk_score, r.inherent_risk_score)) AS max_score
               FROM risks r JOIN audit_universe_risks aur ON aur.risk_id = r.id
               WHERE aur.universe_id = %s''',
            (universe_id,)
        ).fetchone()
        return row['max_score'] if row else None


class AnnualAuditPlan:
    def __init__(self, id=None, plan_year=None, plan_name=None, status='DRAFT', approved_date=None,
                 approved_by=None, approved_by_meeting_id=None, created_at=None, **kwargs):
        self.id = id
        self.plan_year = plan_year
        self.plan_name = plan_name
        self.status = status
        self.approved_date = approved_date
        self.approved_by = approved_by
        self.approved_by_meeting_id = approved_by_meeting_id
        self.created_at = created_at

    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute('SELECT * FROM annual_audit_plans ORDER BY plan_year DESC').fetchall()
        return [AnnualAuditPlan(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(plan_id):
        db = get_db()
        row = db.execute('SELECT * FROM annual_audit_plans WHERE id = %s', (plan_id,)).fetchone()
        return AnnualAuditPlan(**dict(row)) if row else None

    @staticmethod
    def create(plan_year, plan_name=None):
        db = get_db()
        cursor = db.execute(
            'INSERT INTO annual_audit_plans (plan_year, plan_name) VALUES (%s, %s) RETURNING id',
            (plan_year, plan_name)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return AnnualAuditPlan.get_by_id(new_id)

    @staticmethod
    def approve(plan_id, approved_by, approved_by_meeting_id=None):
        db = get_db()
        db.execute(
            '''UPDATE annual_audit_plans SET status = 'APPROVED', approved_date = CURRENT_DATE,
               approved_by = %s, approved_by_meeting_id = %s WHERE id = %s''',
            (approved_by, approved_by_meeting_id, plan_id)
        )
        db.commit()


class AuditProject:
    def __init__(self, id=None, plan_id=None, audit_number=None, audit_name=None, auditable_area_id=None,
                 audit_type='INTERNAL', audit_scope=None, planned_start_date=None, planned_end_date=None,
                 actual_start_date=None, actual_end_date=None, lead_auditor_id=None, status='PLANNED',
                 created_at=None, **kwargs):
        self.id = id
        self.plan_id = plan_id
        self.audit_number = audit_number
        self.audit_name = audit_name
        self.auditable_area_id = auditable_area_id
        self.audit_type = audit_type
        self.audit_scope = audit_scope
        self.planned_start_date = planned_start_date
        self.planned_end_date = planned_end_date
        self.actual_start_date = actual_start_date
        self.actual_end_date = actual_end_date
        self.lead_auditor_id = lead_auditor_id
        self.status = status
        self.created_at = created_at

    @staticmethod
    def _generate_audit_number():
        year = date.today().year
        db = get_db()
        seq_row = db.execute(
            "SELECT prefix, padding FROM numbering_sequences WHERE sequence_key = 'audit_engagement'"
        ).fetchone()
        prefix = seq_row['prefix'] if seq_row else 'AUD'
        padding = seq_row['padding'] if seq_row else 4

        row = db.execute(
            "SELECT audit_number FROM audit_projects WHERE audit_number LIKE %s ORDER BY audit_number DESC LIMIT 1",
            (f'{prefix}-{year}-%',)
        ).fetchone()
        seq = 1
        if row:
            try:
                seq = int(row['audit_number'].split('-')[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        return f'{prefix}-{year}-{seq:0{padding}d}'

    @staticmethod
    def get_all(status=None, plan_id=None):
        db = get_db()
        clauses, params = [], []
        if status:
            clauses.append('status = %s')
            params.append(status)
        if plan_id:
            clauses.append('plan_id = %s')
            params.append(plan_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        rows = db.execute(f'SELECT * FROM audit_projects {where} ORDER BY planned_start_date DESC', tuple(params)).fetchall()
        return [AuditProject(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(project_id):
        db = get_db()
        row = db.execute('SELECT * FROM audit_projects WHERE id = %s', (project_id,)).fetchone()
        return AuditProject(**dict(row)) if row else None

    @staticmethod
    def create(audit_name, lead_auditor_id, plan_id=None, auditable_area_id=None, audit_type='INTERNAL',
               audit_scope=None, planned_start_date=None, planned_end_date=None):
        audit_number = AuditProject._generate_audit_number()
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO audit_projects
               (plan_id, audit_number, audit_name, auditable_area_id, audit_type, audit_scope,
                planned_start_date, planned_end_date, lead_auditor_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (plan_id, audit_number, audit_name, auditable_area_id, audit_type, audit_scope,
             planned_start_date, planned_end_date, lead_auditor_id)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        # Keep audit_team_members in sync: the lead auditor is always a LEAD row.
        AuditTeamMember.add(new_id, lead_auditor_id, role_on_engagement='LEAD')
        return AuditProject.get_by_id(new_id)

    @staticmethod
    def update_status(project_id, status):
        db = get_db()
        if status == 'FIELDWORK':
            db.execute("UPDATE audit_projects SET status = %s, actual_start_date = COALESCE(actual_start_date, CURRENT_DATE) WHERE id = %s",
                       (status, project_id))
        elif status == 'CLOSED':
            db.execute("UPDATE audit_projects SET status = %s, actual_end_date = COALESCE(actual_end_date, CURRENT_DATE) WHERE id = %s",
                       (status, project_id))
        else:
            db.execute('UPDATE audit_projects SET status = %s WHERE id = %s', (status, project_id))
        db.commit()


class AuditTeamMember:
    def __init__(self, id=None, project_id=None, user_id=None, role_on_engagement='AUDITOR',
                 allocated_hours=None, **kwargs):
        self.id = id
        self.project_id = project_id
        self.user_id = user_id
        self.role_on_engagement = role_on_engagement
        self.allocated_hours = allocated_hours

    @staticmethod
    def add(project_id, user_id, role_on_engagement='AUDITOR', allocated_hours=None):
        db = get_db()
        existing = db.execute(
            'SELECT id FROM audit_team_members WHERE project_id = %s AND user_id = %s', (project_id, user_id)
        ).fetchone()
        if existing:
            db.execute('UPDATE audit_team_members SET role_on_engagement = %s, allocated_hours = %s WHERE id = %s',
                       (role_on_engagement, allocated_hours, existing[0]))
            db.commit()
            return existing[0]
        cursor = db.execute(
            'INSERT INTO audit_team_members (project_id, user_id, role_on_engagement, allocated_hours) '
            'VALUES (%s, %s, %s, %s) RETURNING id',
            (project_id, user_id, role_on_engagement, allocated_hours)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return new_id

    @staticmethod
    def get_for_project(project_id):
        db = get_db()
        rows = db.execute('SELECT * FROM audit_team_members WHERE project_id = %s', (project_id,)).fetchall()
        return [AuditTeamMember(**dict(row)) for row in rows]

    @staticmethod
    def is_team_member(project_id, user_id):
        db = get_db()
        row = db.execute('SELECT 1 FROM audit_team_members WHERE project_id = %s AND user_id = %s',
                          (project_id, user_id)).fetchone()
        return row is not None


class AuditProgram:
    def __init__(self, id=None, project_id=None, step_number=None, procedure_description=None,
                 control_id=None, test_result=None, workpaper_reference=None, performed_by=None,
                 performed_at=None, reviewed_by=None, reviewed_at=None, **kwargs):
        self.id = id
        self.project_id = project_id
        self.step_number = step_number
        self.procedure_description = procedure_description
        self.control_id = control_id
        self.test_result = test_result
        self.workpaper_reference = workpaper_reference
        self.performed_by = performed_by
        self.performed_at = performed_at
        self.reviewed_by = reviewed_by
        self.reviewed_at = reviewed_at

    @staticmethod
    def get_for_project(project_id):
        db = get_db()
        rows = db.execute('SELECT * FROM audit_programs WHERE project_id = %s ORDER BY step_number', (project_id,)).fetchall()
        return [AuditProgram(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(program_id):
        db = get_db()
        row = db.execute('SELECT * FROM audit_programs WHERE id = %s', (program_id,)).fetchone()
        return AuditProgram(**dict(row)) if row else None

    @staticmethod
    def create(project_id, procedure_description, control_id=None):
        db = get_db()
        row = db.execute('SELECT COALESCE(MAX(step_number), 0) + 1 AS next_step FROM audit_programs WHERE project_id = %s',
                          (project_id,)).fetchone()
        step_number = row['next_step']
        cursor = db.execute(
            'INSERT INTO audit_programs (project_id, step_number, procedure_description, control_id) '
            'VALUES (%s, %s, %s, %s) RETURNING id',
            (project_id, step_number, procedure_description, control_id)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return AuditProgram.get_by_id(new_id)

    @staticmethod
    def record_result(program_id, test_result, performed_by, workpaper_reference=None, audit_project_id=None):
        """Records the procedure result and, if the step tests a specific control,
        logs it in control_test_results (audit_project_id set) so the control's
        test history shows it was verified by an independent audit engagement."""
        db = get_db()
        db.execute(
            '''UPDATE audit_programs SET test_result = %s, performed_by = %s,
               performed_at = CURRENT_TIMESTAMP, workpaper_reference = %s WHERE id = %s''',
            (test_result, performed_by, workpaper_reference, program_id)
        )
        db.commit()
        program = AuditProgram.get_by_id(program_id)
        if program.control_id and test_result in ('EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'INEFFECTIVE'):
            ControlTestResult.create(
                control_id=program.control_id, tested_by=performed_by, test_date=date.today(),
                test_procedure=program.procedure_description, result=test_result,
                audit_project_id=audit_project_id or program.project_id,
            )

    @staticmethod
    def review(program_id, reviewed_by):
        db = get_db()
        db.execute('UPDATE audit_programs SET reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP WHERE id = %s',
                   (reviewed_by, program_id))
        db.commit()


class AuditWorkingPaper:
    def __init__(self, id=None, project_id=None, program_step_id=None, finding_id=None, file_path=None,
                 description=None, uploaded_by=None, uploaded_at=None, **kwargs):
        self.id = id
        self.project_id = project_id
        self.program_step_id = program_step_id
        self.finding_id = finding_id
        self.file_path = file_path
        self.description = description
        self.uploaded_by = uploaded_by
        self.uploaded_at = uploaded_at

    @staticmethod
    def create(project_id, file_path, description=None, program_step_id=None, finding_id=None, uploaded_by=None):
        db = get_db()
        cursor = db.execute(
            '''INSERT INTO audit_working_papers
               (project_id, program_step_id, finding_id, file_path, description, uploaded_by)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id''',
            (project_id, program_step_id, finding_id, file_path, description, uploaded_by)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return new_id

    @staticmethod
    def get_for_project(project_id):
        db = get_db()
        rows = db.execute('SELECT * FROM audit_working_papers WHERE project_id = %s ORDER BY uploaded_at', (project_id,)).fetchall()
        return [AuditWorkingPaper(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(paper_id):
        db = get_db()
        row = db.execute('SELECT * FROM audit_working_papers WHERE id = %s', (paper_id,)).fetchone()
        return AuditWorkingPaper(**dict(row)) if row else None


class AuditFinding:
    OPEN_STATUSES = ('OPEN', 'MANAGEMENT_RESPONSE_RECEIVED', 'REMEDIATION_IN_PROGRESS',
                      'REMEDIATED_PENDING_VERIFICATION')

    def __init__(self, id=None, project_id=None, finding_number=None, finding_title=None,
                 finding_description=None, severity=None, root_cause=None, recommendation=None,
                 management_response=None, agreed_action=None, responsible_person_id=None,
                 target_date=None, status='OPEN', verified_by=None, verified_at=None,
                 verification_notes=None, linked_risk_id=None, linked_control_id=None,
                 created_at=None, **kwargs):
        self.id = id
        self.project_id = project_id
        self.finding_number = finding_number
        self.finding_title = finding_title
        self.finding_description = finding_description
        self.severity = severity
        self.root_cause = root_cause
        self.recommendation = recommendation
        self.management_response = management_response
        self.agreed_action = agreed_action
        self.responsible_person_id = responsible_person_id
        self.target_date = target_date
        self.status = status
        self.verified_by = verified_by
        self.verified_at = verified_at
        self.verification_notes = verification_notes
        self.linked_risk_id = linked_risk_id
        self.linked_control_id = linked_control_id
        self.created_at = created_at
        self.remediation_note = kwargs.get('remediation_note')
        self.remediated_at = kwargs.get('remediated_at')

    @staticmethod
    def get_by_id(finding_id):
        db = get_db()
        row = db.execute('SELECT * FROM audit_findings WHERE id = %s', (finding_id,)).fetchone()
        return AuditFinding(**dict(row)) if row else None

    @staticmethod
    def get_for_project(project_id):
        db = get_db()
        rows = db.execute('SELECT * FROM audit_findings WHERE project_id = %s ORDER BY severity, finding_number', (project_id,)).fetchall()
        return [AuditFinding(**dict(row)) for row in rows]

    @staticmethod
    def get_all(status=None, severity=None):
        db = get_db()
        clauses, params = [], []
        if status:
            clauses.append('status = %s')
            params.append(status)
        if severity:
            clauses.append('severity = %s')
            params.append(severity)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        rows = db.execute(f'SELECT * FROM audit_findings {where} ORDER BY severity, target_date', tuple(params)).fetchall()
        return [AuditFinding(**dict(row)) for row in rows]

    @staticmethod
    def get_overdue():
        db = get_db()
        rows = db.execute(
            f"SELECT * FROM audit_findings WHERE target_date < CURRENT_DATE AND status IN %s ORDER BY target_date",
            (AuditFinding.OPEN_STATUSES,)
        ).fetchall()
        return [AuditFinding(**dict(row)) for row in rows]

    @staticmethod
    def create(project_id, finding_title, severity, finding_description=None, root_cause=None,
               recommendation=None, responsible_person_id=None, target_date=None):
        db = get_db()
        row = db.execute(
            "SELECT finding_number FROM audit_findings WHERE project_id = %s ORDER BY finding_number DESC LIMIT 1",
            (project_id,)
        ).fetchone()
        seq = 1
        if row:
            try:
                seq = int(row['finding_number'].split('-')[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        finding_number = f'F-{seq:03d}'
        cursor = db.execute(
            '''INSERT INTO audit_findings
               (project_id, finding_number, finding_title, finding_description, severity, root_cause,
                recommendation, responsible_person_id, target_date)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (project_id, finding_number, finding_title, finding_description, severity, root_cause,
             recommendation, responsible_person_id, target_date)
        )
        new_id = cursor.fetchone()[0]
        db.commit()
        return AuditFinding.get_by_id(new_id)

    @staticmethod
    def record_management_response(finding_id, management_response, agreed_action):
        db = get_db()
        db.execute(
            '''UPDATE audit_findings SET management_response = %s, agreed_action = %s,
               status = 'MANAGEMENT_RESPONSE_RECEIVED' WHERE id = %s''',
            (management_response, agreed_action, finding_id)
        )
        db.commit()

    @staticmethod
    def mark_remediation_in_progress(finding_id):
        db = get_db()
        db.execute("UPDATE audit_findings SET status = 'REMEDIATION_IN_PROGRESS' WHERE id = %s", (finding_id,))
        db.commit()

    @staticmethod
    def mark_remediated(finding_id, remediation_note=None):
        db = get_db()
        db.execute("UPDATE audit_findings SET status = 'REMEDIATED_PENDING_VERIFICATION', "
                   "remediation_note = %s, remediated_at = CURRENT_TIMESTAMP WHERE id = %s",
                   (remediation_note, finding_id))
        db.commit()

    @staticmethod
    def verify_and_close(finding_id, verified_by, verification_notes=None):
        """Independent verification — the verifier must be an auditor on the
        engagement team and must not be the person responsible for remediation
        (management cannot mark its own remediation as done)."""
        finding = AuditFinding.get_by_id(finding_id)
        if not finding:
            raise ValueError('Finding not found')
        if finding.responsible_person_id == verified_by:
            raise ValueError('The responsible person cannot verify their own finding')
        if not AuditTeamMember.is_team_member(finding.project_id, verified_by):
            raise ValueError('Only an auditor on the engagement team can verify this finding')
        db = get_db()
        db.execute(
            '''UPDATE audit_findings SET status = 'VERIFIED_CLOSED', verified_by = %s,
               verified_at = CURRENT_TIMESTAMP, verification_notes = %s WHERE id = %s''',
            (verified_by, verification_notes, finding_id)
        )
        db.commit()

    @staticmethod
    def link_to_risk(finding_id, risk_id, linked_by, link_type='EVIDENCE'):
        RiskSourceLink.create(risk_id, source_module='internal_audit', source_table='audit_findings',
                               source_record_id=finding_id, link_type=link_type, linked_by=linked_by)
        db = get_db()
        db.execute('UPDATE audit_findings SET linked_risk_id = %s WHERE id = %s', (risk_id, finding_id))
        db.commit()

    @staticmethod
    def create_risk_from_finding(finding_id, risk_owner_id, created_by, category_code=None):
        finding = AuditFinding.get_by_id(finding_id)
        if not finding:
            raise ValueError(f'Audit finding {finding_id} not found — cannot raise a risk from it.')
        risk = Risk.create_draft_from_suggestion(
            source_module='internal_audit', source_table='audit_findings', source_record_id=finding_id,
            risk_title=finding.finding_title, risk_owner_id=risk_owner_id, created_by=created_by,
            risk_description=finding.finding_description, category_code=category_code, link_type='TRIGGER',
        )
        db = get_db()
        db.execute('UPDATE audit_findings SET linked_risk_id = %s WHERE id = %s', (risk.id, finding_id))
        db.commit()
        return risk


def generate_committee_report():
    """Summary for the audit committee: open findings by severity, overdue count,
    closures in the last quarter, and top risks. Returned as a dict plus a plain-text
    rendering ready to append to a board meeting agenda."""
    open_findings = [f for f in AuditFinding.get_all() if f.status in AuditFinding.OPEN_STATUSES]
    overdue = AuditFinding.get_overdue()
    by_severity = {}
    for f in open_findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1

    closed = [f for f in AuditFinding.get_all(status='VERIFIED_CLOSED')]
    top_risks = sorted(Risk.get_all(status='ACTIVE'),
                        key=lambda r: (r.residual_risk_score or r.inherent_risk_score or 0), reverse=True)[:5]

    lines = [
        'Internal Audit Committee Report',
        f'Open findings: {len(open_findings)} ({", ".join(f"{k}: {v}" for k, v in by_severity.items()) or "none"})',
        f'Overdue findings: {len(overdue)}',
        f'Findings closed to date: {len(closed)}',
        'Top risks: ' + '; '.join(f'{r.risk_id} ({r.risk_title})' for r in top_risks) if top_risks else 'Top risks: none',
    ]
    report_text = '\n'.join(lines)

    return {
        'open_findings_count': len(open_findings),
        'open_by_severity': by_severity,
        'overdue_count': len(overdue),
        'closed_count': len(closed),
        'top_risks': top_risks,
        'report_text': report_text,
    }


def attach_report_to_meeting(meeting_id, report_text, create_decisions=True):
    """Appends the report text to the board meeting's agenda and, optionally,
    creates a board_decisions row per open CRITICAL/HIGH finding so it's tracked
    through the existing governance follow-up mechanism rather than a silo."""
    from models.governance import BoardMeeting, BoardDecision

    meeting = BoardMeeting.get_by_id(meeting_id)
    if not meeting:
        raise ValueError('Board meeting not found')
    updated_agenda = f"{meeting.agenda or ''}\n\n{report_text}".strip()
    meeting.update({'agenda': updated_agenda})

    if create_decisions:
        material_findings = [f for f in AuditFinding.get_all()
                              if f.status in AuditFinding.OPEN_STATUSES and f.severity in ('CRITICAL', 'HIGH')]
        for f in material_findings:
            from models.user import User
            responsible = User.get_by_id(f.responsible_person_id) if f.responsible_person_id else None
            BoardDecision.create({
                'meeting_id': meeting_id,
                'decision_number': f.finding_number,
                'decision_text': f'Audit finding {f.finding_number}: {f.finding_title}',
                'responsible_person': f'{responsible.first_name} {responsible.last_name}' if responsible else None,
                'deadline': f.target_date,
                'status': 'PENDING',
            })
