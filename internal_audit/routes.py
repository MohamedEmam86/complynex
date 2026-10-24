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

import os
from datetime import datetime

from flask_babel import gettext
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from flask_babel import gettext as _, lazy_gettext as _l
from werkzeug.utils import secure_filename

from utils.decorators import permission_required
from utils.file_serving import serve_uploaded_file
from models.audit import AuditLog
from models.notification import Notification
from models.department import Department
from models.user import User
from models.risk import Risk, RiskCategory, Control
from models.internal_audit import (
    AuditUniverse, AnnualAuditPlan, AuditProject, AuditTeamMember, AuditProgram,
    AuditWorkingPaper, AuditFinding, generate_committee_report, attach_report_to_meeting,
)
from models.settings import Settings
from attachments.service import list_attachments

ia_bp = Blueprint('internal_audit', __name__, url_prefix='/internal-audit')


def _save_working_paper(file, subfolder, entity_id):
    """Non-static uploads/<module>/<entity>/<file> — not reachable via Flask's
    unauthenticated /static/ route."""
    if not file or not file.filename:
        return None
    filename = secure_filename(f"{entity_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
    rel_dir = f"internal_audit/{subfolder}/{entity_id}"
    upload_path = os.path.join(current_app.root_path, 'uploads', rel_dir, filename)
    os.makedirs(os.path.dirname(upload_path), exist_ok=True)
    file.save(upload_path)
    return f"uploads/{rel_dir}/{filename}"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@ia_bp.route('/')
@ia_bp.route('/dashboard')
@login_required
@permission_required('internal_audit')
def dashboard():
    from datetime import date

    all_findings = AuditFinding.get_all()
    open_findings = [f for f in all_findings if f.status in AuditFinding.OPEN_STATUSES]
    overdue = AuditFinding.get_overdue()
    all_projects = AuditProject.get_all()
    active_projects = [p for p in all_projects if p.status == 'FIELDWORK']

    severity_breakdown = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    for f in open_findings:
        if f.severity in severity_breakdown:
            severity_breakdown[f.severity] += 1

    pipeline_statuses = ['PLANNED', 'FIELDWORK', 'REPORTING', 'MANAGEMENT_RESPONSE', 'FOLLOW_UP', 'CLOSED']
    pipeline = {s: 0 for s in pipeline_statuses}
    for p in all_projects:
        if p.status in pipeline:
            pipeline[p.status] += 1

    current_year = date.today().year
    current_plan = next((p for p in AnnualAuditPlan.get_all() if p.plan_year == current_year), None)
    universe_areas = AuditUniverse.get_all()
    covered_area_ids = {p.auditable_area_id for p in all_projects
                         if p.auditable_area_id and p.plan_id and current_plan and p.plan_id == current_plan.id}
    plan_coverage = {
        'total_areas': len(universe_areas),
        'covered_areas': len(covered_area_ids),
        'pct': round(100 * len(covered_area_ids) / len(universe_areas)) if universe_areas else 0,
    }

    upcoming_projects = sorted(
        [p for p in all_projects if p.status == 'PLANNED' and p.planned_start_date],
        key=lambda p: p.planned_start_date
    )[:5]

    return render_template(
        'internal_audit/dashboard.html', open_findings=open_findings, overdue=overdue,
        active_projects=active_projects, all_projects=all_projects,
        severity_breakdown=severity_breakdown, pipeline=pipeline, current_plan=current_plan,
        plan_coverage=plan_coverage, upcoming_projects=upcoming_projects,
    )


# ---------------------------------------------------------------------------
# Audit universe
# ---------------------------------------------------------------------------

@ia_bp.route('/universe')
@login_required
@permission_required('internal_audit')
def universe():
    areas = AuditUniverse.get_all()
    derived_scores = {a.id: AuditUniverse.get_derived_risk_score(a.id) for a in areas}
    linked_risks = {a.id: AuditUniverse.get_linked_risks(a.id) for a in areas}
    departments_by_id = {d.id: d for d in Department.get_all()}
    return render_template(
        'internal_audit/universe.html', areas=areas, derived_scores=derived_scores,
        linked_risks=linked_risks, departments_by_id=departments_by_id, all_risks=Risk.get_all(),
    )


@ia_bp.route('/universe/new', methods=['GET', 'POST'])
@login_required
@permission_required('internal_audit', level='edit')
def universe_new():
    if request.method == 'POST':
        area = AuditUniverse.create(
            auditable_area=request.form.get('auditable_area'),
            risk_level=request.form.get('risk_level', 'MEDIUM'),
            area_description=request.form.get('area_description'),
            department_id=request.form.get('department_id', type=int) or None,
            audit_frequency=request.form.get('audit_frequency', 'ANNUAL'),
            responsible_department=request.form.get('responsible_department'),
        )
        AuditLog.log(current_user.id, 'Create Audit Universe Entry', 'Internal Audit', area.id,
                     f'Added auditable area {area.auditable_area}', request.remote_addr)
        flash(gettext('Auditable area added.'), 'success')
        return redirect(url_for('internal_audit.universe'))
    return render_template('internal_audit/universe_form.html', departments=Department.get_all())


@ia_bp.route('/universe/<int:universe_id>/link-risk', methods=['POST'])
@login_required
@permission_required('internal_audit', level='edit')
def universe_link_risk(universe_id):
    risk_pk = request.form.get('risk_pk', type=int)
    AuditUniverse.link_risk(universe_id, risk_pk)
    AuditLog.log(current_user.id, 'Link Risk to Audit Universe', 'Internal Audit', universe_id,
                 f'Linked risk #{risk_pk}', request.remote_addr)
    flash(gettext('Risk linked to auditable area.'), 'success')
    return redirect(url_for('internal_audit.universe'))


# ---------------------------------------------------------------------------
# Annual plans
# ---------------------------------------------------------------------------

@ia_bp.route('/plans')
@login_required
@permission_required('internal_audit')
def plans():
    plan_list = AnnualAuditPlan.get_all()
    engagement_counts = {p.id: len(AuditProject.get_all(plan_id=p.id)) for p in plan_list}
    return render_template('internal_audit/plans.html', plans=plan_list, engagement_counts=engagement_counts)


@ia_bp.route('/plans/new', methods=['GET', 'POST'])
@login_required
@permission_required('internal_audit', level='edit')
def plans_new():
    if request.method == 'POST':
        plan_year = request.form.get('plan_year', type=int)
        error = None
        if not plan_year or not 2000 <= plan_year <= 2100:
            error = gettext('Enter a valid plan year.')
        elif any(p.plan_year == plan_year for p in AnnualAuditPlan.get_all()):
            error = gettext('An annual audit plan for %(year)s already exists.', year=plan_year)
        if error:
            flash(error, 'danger')
            return redirect(url_for('internal_audit.plans_new'))
        plan = AnnualAuditPlan.create(
            plan_year=plan_year,
            plan_name=request.form.get('plan_name'),
        )
        AuditLog.log(current_user.id, 'Create Annual Audit Plan', 'Internal Audit', plan.id,
                     f'Created plan for {plan.plan_year}', request.remote_addr)
        flash(gettext('Annual audit plan created.'), 'success')
        return redirect(url_for('internal_audit.plans'))
    areas = AuditUniverse.get_all()
    derived_scores = {a.id: AuditUniverse.get_derived_risk_score(a.id) for a in areas}
    return render_template('internal_audit/plan_form.html', areas=areas, derived_scores=derived_scores)


@ia_bp.route('/plans/<int:plan_id>/approve', methods=['POST'])
@login_required
@permission_required('internal_audit', level='edit')
def plans_approve(plan_id):
    AnnualAuditPlan.approve(plan_id, approved_by=current_user.id,
                             approved_by_meeting_id=request.form.get('meeting_id', type=int) or None)
    AuditLog.log(current_user.id, 'Approve Annual Audit Plan', 'Internal Audit', plan_id,
                 'Plan approved', request.remote_addr)
    flash(gettext('Plan approved.'), 'success')
    return redirect(url_for('internal_audit.plans'))


# ---------------------------------------------------------------------------
# Engagements (audit projects)
# ---------------------------------------------------------------------------

@ia_bp.route('/projects')
@login_required
@permission_required('internal_audit')
def projects():
    status = request.args.get('status') or None
    project_list = AuditProject.get_all(status=status)
    users_by_id = {u.id: u for u in User.get_all()}
    findings_count = {p.id: len(AuditFinding.get_for_project(p.id)) for p in project_list}
    return render_template(
        'internal_audit/projects.html', projects=project_list, users_by_id=users_by_id,
        findings_count=findings_count, current_status=status,
    )


@ia_bp.route('/projects/new', methods=['GET', 'POST'])
@login_required
@permission_required('internal_audit', level='edit')
def projects_new():
    if request.method == 'POST':
        start = request.form.get('planned_start_date') or None
        end = request.form.get('planned_end_date') or None
        if start and end and end < start:  # ISO dates compare correctly as text
            flash(gettext('The planned end date cannot be before the start date.'), 'danger')
            return render_template(
                'internal_audit/project_form.html', plans=AnnualAuditPlan.get_all(),
                areas=AuditUniverse.get_all(), users=User.get_all(),
                preselected_area_id=request.form.get('auditable_area_id', type=int),
            ), 400
        project = AuditProject.create(
            audit_name=request.form.get('audit_name'),
            lead_auditor_id=request.form.get('lead_auditor_id', type=int),
            plan_id=request.form.get('plan_id', type=int) or None,
            auditable_area_id=request.form.get('auditable_area_id', type=int) or None,
            audit_type=request.form.get('audit_type', 'INTERNAL'),
            audit_scope=request.form.get('audit_scope'),
            planned_start_date=request.form.get('planned_start_date') or None,
            planned_end_date=request.form.get('planned_end_date') or None,
        )
        AuditLog.log(current_user.id, 'Create Audit Engagement', 'Internal Audit', project.id,
                     f'Created engagement {project.audit_number}: {project.audit_name}', request.remote_addr)
        flash(gettext('Engagement %(audit_number)s created.', audit_number=project.audit_number), 'success')
        return redirect(url_for('internal_audit.project_detail', project_id=project.id))
    preselected_area_id = request.args.get('auditable_area_id', type=int)
    return render_template(
        'internal_audit/project_form.html', plans=AnnualAuditPlan.get_all(),
        areas=AuditUniverse.get_all(), users=User.get_all(), preselected_area_id=preselected_area_id,
    )


@ia_bp.route('/projects/<int:project_id>')
@login_required
@permission_required('internal_audit')
def project_detail(project_id):
    project = AuditProject.get_by_id(project_id)
    if not project:
        flash(gettext('Engagement not found.'), 'danger')
        return redirect(url_for('internal_audit.projects'))
    team = AuditTeamMember.get_for_project(project_id)
    program = AuditProgram.get_for_project(project_id)
    findings = AuditFinding.get_for_project(project_id)
    papers = AuditWorkingPaper.get_for_project(project_id)
    plan = AnnualAuditPlan.get_by_id(project.plan_id) if project.plan_id else None
    area = AuditUniverse.get_by_id(project.auditable_area_id) if project.auditable_area_id else None
    all_users = User.get_all()
    all_controls = Control.get_all()
    return render_template(
        'internal_audit/project_detail.html', project=project, team=team, program=program,
        findings=findings, papers=papers, users=all_users, controls=all_controls,
        users_by_id={u.id: u for u in all_users}, controls_by_id={c.id: c for c in all_controls},
        plan=plan, area=area,
    )


@ia_bp.route('/working-papers/<int:paper_id>')
@login_required
@permission_required('internal_audit')
def working_paper_download(paper_id):
    """Serve a working paper file — same module guard as viewing the engagement."""
    paper = AuditWorkingPaper.get_by_id(paper_id)
    if not paper or not paper.file_path:
        flash(gettext('File not found.'), 'danger')
        return redirect(url_for('internal_audit.projects'))
    return serve_uploaded_file(paper.file_path)


@ia_bp.route('/projects/<int:project_id>/status', methods=['POST'])
@login_required
@permission_required('internal_audit', level='edit')
def project_status(project_id):
    status = request.form.get('status')
    AuditProject.update_status(project_id, status)
    AuditLog.log(current_user.id, 'Update Audit Engagement Status', 'Internal Audit', project_id,
                 f'Status changed to {status}', request.remote_addr)
    flash(gettext('Engagement status updated.'), 'success')
    return redirect(url_for('internal_audit.project_detail', project_id=project_id))


@ia_bp.route('/projects/<int:project_id>/team', methods=['POST'])
@login_required
@permission_required('internal_audit', level='edit')
def project_team_add(project_id):
    AuditTeamMember.add(
        project_id, user_id=request.form.get('user_id', type=int),
        role_on_engagement=request.form.get('role_on_engagement', 'AUDITOR'),
        allocated_hours=request.form.get('allocated_hours', type=float) or None,
    )
    flash(gettext('Team member added.'), 'success')
    return redirect(url_for('internal_audit.project_detail', project_id=project_id))


@ia_bp.route('/projects/<int:project_id>/program', methods=['POST'])
@login_required
@permission_required('internal_audit', level='edit')
def project_program_add(project_id):
    AuditProgram.create(
        project_id, procedure_description=request.form.get('procedure_description'),
        control_id=request.form.get('control_id', type=int) or None,
    )
    flash(gettext('Procedure step added.'), 'success')
    return redirect(url_for('internal_audit.project_detail', project_id=project_id))


@ia_bp.route('/projects/<int:project_id>/program/<int:program_id>/result', methods=['POST'])
@login_required
@permission_required('internal_audit', level='edit')
def project_program_result(project_id, program_id):
    AuditProgram.record_result(
        program_id, test_result=request.form.get('test_result'), performed_by=current_user.id,
        workpaper_reference=request.form.get('workpaper_reference'), audit_project_id=project_id,
    )
    AuditLog.log(current_user.id, 'Record Audit Program Result', 'Internal Audit', project_id,
                 f'Program step #{program_id} result: {request.form.get("test_result")}', request.remote_addr)
    flash(gettext('Procedure result recorded.'), 'success')
    return redirect(url_for('internal_audit.project_detail', project_id=project_id))


@ia_bp.route('/projects/<int:project_id>/working-papers', methods=['POST'])
@login_required
@permission_required('internal_audit', level='edit')
def project_working_papers(project_id):
    file_path = _save_working_paper(request.files.get('evidence_file'), 'projects', project_id)
    if file_path:
        AuditWorkingPaper.create(
            project_id, file_path=file_path, description=request.form.get('description'),
            program_step_id=request.form.get('program_step_id', type=int) or None,
            uploaded_by=current_user.id,
        )
        flash(gettext('Working paper uploaded.'), 'success')
    else:
        flash(gettext('No file selected.'), 'warning')
    return redirect(url_for('internal_audit.project_detail', project_id=project_id))


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

@ia_bp.route('/findings')
@login_required
@permission_required('internal_audit')
def findings():
    from datetime import date

    status = request.args.get('status') or None
    severity = request.args.get('severity') or None
    finding_list = AuditFinding.get_all(status=status, severity=severity)
    projects_by_id = {p.id: p for p in AuditProject.get_all()}
    return render_template(
        'internal_audit/findings.html', findings=finding_list, projects_by_id=projects_by_id,
        current_status=status, current_severity=severity,
        today=date.today(), open_statuses=AuditFinding.OPEN_STATUSES,
    )


@ia_bp.route('/findings-report')
@login_required
@permission_required('internal_audit')
def findings_report():
    """
    Printable, formal Findings Report — every finding (not just open ones,
    unlike the working /findings dashboard) with severity, status, root
    cause, agreed action, responsible person and target date, plus the same
    committee-level summary shown on the Annual Governance Report so the two
    numbers can never silently disagree. Added 2026-07-24.
    """
    from datetime import date

    status = request.args.get('status') or None
    severity = request.args.get('severity') or None
    finding_list = AuditFinding.get_all(status=status, severity=severity)
    projects_by_id = {p.id: p for p in AuditProject.get_all()}
    users_by_id = {u.id: u for u in User.get_all()} if hasattr(User, 'get_all') else {}
    summary = generate_committee_report()

    return render_template(
        'internal_audit/findings_report.html',
        findings=finding_list, projects_by_id=projects_by_id, users_by_id=users_by_id,
        current_status=status, current_severity=severity, summary=summary,
        open_statuses=AuditFinding.OPEN_STATUSES, today=date.today(),
        company_name=Settings.get('company_name', 'ComplyNex'), generated_at=datetime.now(),
        attach_module='internal_audit', attach_record_type='findings_report', attach_record_id=1,
        attach_items=list_attachments('internal_audit', 'findings_report', 1),
        attach_can_edit=current_user.can_edit('internal_audit'),
        narrative=_load_narrative("findings_report"),
        can_edit_report=current_user.can_edit("internal_audit"),
    )


@ia_bp.route('/projects/<int:project_id>/findings/new', methods=['GET', 'POST'])
@login_required
@permission_required('internal_audit', level='edit')
def finding_new(project_id):
    project = AuditProject.get_by_id(project_id)
    if not project:
        flash(_('Audit project not found.'), 'danger')
        return redirect(url_for('internal_audit.projects'))
    if request.method == 'POST':
        finding = AuditFinding.create(
            project_id, finding_title=request.form.get('finding_title'),
            severity=request.form.get('severity'),
            finding_description=request.form.get('finding_description'),
            root_cause=request.form.get('root_cause'),
            recommendation=request.form.get('recommendation'),
            responsible_person_id=request.form.get('responsible_person_id', type=int) or None,
            target_date=request.form.get('target_date') or None,
        )
        if finding.responsible_person_id:
            Notification.create(
                user_id=finding.responsible_person_id, title=f'Audit finding assigned: {finding.finding_title}',
                message=f'You have been assigned finding {finding.finding_number} from engagement {project.audit_number}.',
                link=url_for('internal_audit.finding_detail', finding_id=finding.id), n_type='finding_assigned',
            )
        AuditLog.log(current_user.id, 'Raise Audit Finding', 'Internal Audit', finding.id,
                     f'Finding {finding.finding_number} raised: {finding.finding_title}', request.remote_addr)
        flash(gettext('Finding %(finding_number)s recorded.', finding_number=finding.finding_number), 'success')
        return redirect(url_for('internal_audit.finding_detail', finding_id=finding.id))
    return render_template('internal_audit/finding_form.html', project=project, users=User.get_all())


@ia_bp.route('/findings/<int:finding_id>')
@login_required
@permission_required('internal_audit')
def finding_detail(finding_id):
    finding = AuditFinding.get_by_id(finding_id)
    if not finding:
        flash(gettext('Finding not found.'), 'danger')
        return redirect(url_for('internal_audit.findings'))
    project = AuditProject.get_by_id(finding.project_id)
    responsible = User.get_by_id(finding.responsible_person_id) if finding.responsible_person_id else None
    verifier = User.get_by_id(finding.verified_by) if finding.verified_by else None
    linked_risk = Risk.get_by_id(finding.linked_risk_id) if finding.linked_risk_id else None
    return render_template(
        'internal_audit/finding_detail.html', finding=finding, project=project,
        risks=Risk.get_all(), categories=RiskCategory.get_all(), users=User.get_all(),
        responsible=responsible, verifier=verifier, linked_risk=linked_risk,
        # Optional supporting evidence for this specific finding (sampled
        # documents, screenshots, signed management response, etc).
        attach_module='internal_audit', attach_record_type='audit_finding',
        attach_record_id=finding_id,
        attach_items=list_attachments('internal_audit', 'audit_finding', finding_id),
        attach_can_edit=current_user.can_edit('internal_audit'),
    )


@ia_bp.route('/findings/<int:finding_id>/management-response', methods=['POST'])
@login_required
@permission_required('internal_audit', level='edit')
def finding_management_response(finding_id):
    response = (request.form.get('management_response') or '').strip()
    if not response:
        flash(gettext('The management response text is required.'), 'danger')
        return redirect(url_for('internal_audit.finding_detail', finding_id=finding_id))
    AuditFinding.record_management_response(
        finding_id, management_response=response,
        agreed_action=(request.form.get('agreed_action') or '').strip() or None,
    )
    AuditLog.log(current_user.id, 'Record Management Response', 'Internal Audit', finding_id,
                 'Management response recorded', request.remote_addr)
    flash(gettext('Management response recorded.'), 'success')
    return redirect(url_for('internal_audit.finding_detail', finding_id=finding_id))


@ia_bp.route('/findings/<int:finding_id>/remediate', methods=['POST'])
@login_required
@permission_required('internal_audit', level='edit')
def finding_remediate(finding_id):
    note = (request.form.get('remediation_note') or '').strip()
    if not note:
        flash(gettext('Describe the remediation and the evidence for it before marking it complete.'), 'danger')
        return redirect(url_for('internal_audit.finding_detail', finding_id=finding_id))
    AuditFinding.mark_remediated(finding_id, remediation_note=note)
    AuditLog.log(current_user.id, 'Mark Finding Remediated', 'Internal Audit', finding_id,
                 'Marked remediated, pending independent verification', request.remote_addr)
    flash(gettext('Finding marked as remediated — pending independent verification.'), 'success')
    return redirect(url_for('internal_audit.finding_detail', finding_id=finding_id))


@ia_bp.route('/findings/<int:finding_id>/verify', methods=['POST'])
@login_required
@permission_required('internal_audit', level='edit')
def finding_verify(finding_id):
    try:
        AuditFinding.verify_and_close(finding_id, verified_by=current_user.id,
                                      verification_notes=request.form.get('verification_notes'))
        AuditLog.log(current_user.id, 'Verify Audit Finding', 'Internal Audit', finding_id,
                     'Finding independently verified and closed', request.remote_addr)
        flash(gettext('Finding verified and closed.'), 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    return redirect(url_for('internal_audit.finding_detail', finding_id=finding_id))


@ia_bp.route('/findings/<int:finding_id>/link-risk', methods=['GET', 'POST'])
@login_required
@permission_required('internal_audit', level='edit')
def finding_link_risk(finding_id):
    finding = AuditFinding.get_by_id(finding_id)
    if not finding:
        flash(_('Finding not found.'), 'danger')
        return redirect(url_for('internal_audit.findings'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'link_existing':
            AuditFinding.link_to_risk(finding_id, request.form.get('risk_pk', type=int), linked_by=current_user.id)
            flash(gettext('Finding linked to existing risk.'), 'success')
        else:
            risk = AuditFinding.create_risk_from_finding(
                finding_id, risk_owner_id=request.form.get('risk_owner_id', type=int),
                created_by=current_user.id, category_code=request.form.get('category_code'),
            )
            flash(gettext('Draft risk %(risk_id)s created from this finding — please review and score it.', risk_id=risk.risk_id), 'success')
        AuditLog.log(current_user.id, 'Link Audit Finding to Risk', 'Internal Audit', finding_id,
                     'Finding linked to risk register', request.remote_addr)
        return redirect(url_for('internal_audit.finding_detail', finding_id=finding_id))
    return render_template(
        'internal_audit/finding_link_risk.html', finding=finding, risks=Risk.get_all(),
        categories=RiskCategory.get_all(), users=User.get_all(),
    )


# ---------------------------------------------------------------------------
# Committee reporting
# ---------------------------------------------------------------------------

@ia_bp.route('/committee-report')
@login_required
@permission_required('internal_audit')
def committee_report():
    report = generate_committee_report()
    from models.governance import BoardMeeting
    return render_template('internal_audit/committee_report.html', report=report,
                           meetings=BoardMeeting.get_upcoming(),
                           narrative=_load_narrative('committee_report'),
                           can_edit_report=current_user.can_edit('internal_audit'))


@ia_bp.route('/committee-report/attach/<int:meeting_id>', methods=['POST'])
@login_required
@permission_required('internal_audit', level='edit')
def committee_report_attach(meeting_id):
    report = generate_committee_report()
    attach_report_to_meeting(meeting_id, report['report_text'], create_decisions=True)
    AuditLog.log(current_user.id, 'Attach Committee Report', 'Internal Audit', meeting_id,
                 'Attached audit committee report to board meeting', request.remote_addr)
    flash(gettext('Committee report attached to the board meeting.'), 'success')
    return redirect(url_for('internal_audit.committee_report'))


# ---------------------------------------------------------------------------
# Editable report narrative  (added 2026-07-24)
#
# The Audit Committee Report and the Findings Report are generated from live
# data, which is correct - the numbers must never be hand-typed. But a report
# that goes to the Audit Committee / Board also needs the CAE's own narrative:
# scope and limitations, an opinion, and recommended committee actions.
#
# Those narrative blocks are stored in system_settings (the same key/value
# store the rest of the app uses) so they persist between report runs and are
# editable, while every figure stays computed. Editing requires 'edit'
# permission on internal_audit and is written to the audit log.
# ---------------------------------------------------------------------------

REPORT_NARRATIVE_FIELDS = {
    'committee_report': [
        ('ia_committee_report_scope', _l('Scope & Basis of Preparation')),
        ('ia_committee_report_opinion', _l('Chief Audit Executive Opinion')),
        ('ia_committee_report_actions', _l('Recommended Committee Actions')),
    ],
    'findings_report': [
        ('ia_findings_report_scope', _l('Scope & Basis of Preparation')),
        ('ia_findings_report_commentary', _l('Commentary on Findings')),
        ('ia_findings_report_actions', _l('Recommended Management Actions')),
    ],
}


def _load_narrative(report_key):
    """Return {field_key: (label, saved_value)} for a report."""
    fields = REPORT_NARRATIVE_FIELDS[report_key]
    return [(k, label, Settings.get(k, '') or '') for k, label in fields]


@ia_bp.route('/committee-report/edit', methods=['GET', 'POST'])
@login_required
@permission_required('internal_audit', level='edit')
def committee_report_edit():
    """Edit the narrative sections of the Audit Committee Report."""
    if request.method == 'POST':
        for key, _label in REPORT_NARRATIVE_FIELDS['committee_report']:
            Settings.set(key, (request.form.get(key) or '').strip())
        AuditLog.log(current_user.id, 'Edit Committee Report Narrative',
                     'Internal Audit', 0,
                     'Updated audit committee report narrative sections',
                     request.remote_addr)
        flash(_('Committee report narrative saved.'), 'success')
        return redirect(url_for('internal_audit.committee_report'))

    return render_template(
        'internal_audit/report_narrative_form.html',
        title=_('Edit Audit Committee Report'),
        back_url=url_for('internal_audit.committee_report'),
        fields=_load_narrative('committee_report'),
    )


@ia_bp.route('/findings-report/edit', methods=['GET', 'POST'])
@login_required
@permission_required('internal_audit', level='edit')
def findings_report_edit():
    """Edit the narrative sections of the Findings Report."""
    if request.method == 'POST':
        for key, _label in REPORT_NARRATIVE_FIELDS['findings_report']:
            Settings.set(key, (request.form.get(key) or '').strip())
        AuditLog.log(current_user.id, 'Edit Findings Report Narrative',
                     'Internal Audit', 0,
                     'Updated findings report narrative sections',
                     request.remote_addr)
        flash(_('Findings report narrative saved.'), 'success')
        return redirect(url_for('internal_audit.findings_report'))

    return render_template(
        'internal_audit/report_narrative_form.html',
        title=_('Edit Findings Report'),
        back_url=url_for('internal_audit.findings_report'),
        fields=_load_narrative('findings_report'),
    )
