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

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from utils.decorators import permission_required
from utils.file_serving import serve_uploaded_file
from flask_babel import gettext as _
from models.governance import BoardMember, BoardMeeting, BoardCommittee, CommitteeMembership, MeetingAttendance, BoardDecision, BoardRole
from models.governance_enhanced import FitProperAssessment, IndependenceDeclaration, BoardSkillsMatrix, GovernanceCompliance, BoardEvaluation, BoardTraining
from models.audit import AuditLog
from models.reporting import Regulator
from models.settings import Settings
from database.db import get_db
from attachments.service import list_attachments
from werkzeug.utils import secure_filename
import os
import logging
from datetime import datetime, timedelta
from flask import current_app

logger = logging.getLogger(__name__)

governance_bp = Blueprint('governance', __name__, url_prefix='/governance')

@governance_bp.route('/')
@governance_bp.route('/dashboard')
@login_required
@permission_required('governance')
def dashboard():
    members = BoardMember.get_all()
    upcoming_meetings = BoardMeeting.get_upcoming()
    past_meetings = BoardMeeting.get_past()

    independent_count = len([m for m in members if m.is_independent])
    independent_pct = round(independent_count / len(members) * 100) if members else 0

    compliance = GovernanceCompliance.get_all()
    compliant_count = len([c for c in compliance if c.compliance_status == 'COMPLIANT'])
    compliance_pct = round(compliant_count / len(compliance) * 100) if compliance else 0

    fit_proper_due = len(FitProperAssessment.get_due_for_review())

    return render_template('governance/dashboard.html',
                         members=members,
                         upcoming_meetings=upcoming_meetings,
                         past_meetings=past_meetings,
                         independent_pct=independent_pct,
                         compliance_pct=compliance_pct,
                         fit_proper_due=fit_proper_due)

@governance_bp.route('/members/add', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def add_member():

    if request.method == 'POST':
        data = {
            'member_name': request.form.get('member_name'),
            'member_name_arabic': request.form.get('member_name_arabic'),
            'role': request.form.get('role'),
            'is_independent': request.form.get('is_independent') == 'on',
            'is_executive': request.form.get('is_executive') == 'on',
            'expertise_areas': request.form.get('expertise_areas'),
            'appointment_date': request.form.get('appointment_date'),
            'term_end_date': request.form.get('term_end_date'),
            'email': request.form.get('email'),
            'phone': request.form.get('phone'),
            'bio': request.form.get('bio'),
            'status': request.form.get('status')
        }
        
        # Handle Board Member Document Upload
        file = request.files.get('document_file')
        if file and file.filename:
            filename = secure_filename(f"member_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
            upload_path = os.path.join(current_app.root_path, 'uploads/governance/members', filename)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            file.save(upload_path)
            data['document_path'] = f"uploads/governance/members/{filename}"

        member_id = BoardMember.create(data)
        AuditLog.log(current_user.id, 'Create Board Member', 'Governance', member_id, f'Created board member {data["member_name"]}', request.remote_addr)
        flash('Board member added successfully.', 'success')
        return redirect(url_for('governance.dashboard'))

    roles = BoardRole.get_all()
    return render_template('governance/member_form.html', roles=roles)

@governance_bp.route('/members/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def edit_member(id):
        
    member = BoardMember.get_by_id(id)
    if not member:
        flash(_('Board member not found.'), 'error')
        return redirect(url_for('governance.dashboard'))

    if request.method == 'POST':
        data = {
            'member_name': request.form.get('member_name'),
            'member_name_arabic': request.form.get('member_name_arabic'),
            'role': request.form.get('role'),
            'is_independent': 'is_independent' in request.form,
            'is_executive': 'is_executive' in request.form,
            'expertise_areas': request.form.get('expertise_areas'),
            'appointment_date': request.form.get('appointment_date'),
            'term_end_date': request.form.get('term_end_date'),
            'email': request.form.get('email'),
            'phone': request.form.get('phone'),
            'bio': request.form.get('bio'),
            'status': request.form.get('status')
        }
        
        # Handle Board Member Document Upload
        file = request.files.get('document_file')
        if file and file.filename:
            filename = secure_filename(f"member_{id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
            upload_path = os.path.join(current_app.root_path, 'uploads/governance/members', filename)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            file.save(upload_path)
            data['document_path'] = f"uploads/governance/members/{filename}"
            
        member.update(data)
        AuditLog.log(current_user.id, 'Update Board Member', 'Governance', id, f'Updated board member {data["member_name"]}', request.remote_addr)
        flash(_('Board member updated successfully.'), 'success')
        return redirect(url_for('governance.dashboard'))

    roles = BoardRole.get_all()
    return render_template('governance/member_form.html', member=member, roles=roles, title=_('Edit Board Member'))

@governance_bp.route('/members/view/<int:id>')
@login_required
@permission_required('governance')
def view_member(id):
    member = BoardMember.get_by_id(id)
    if not member:
        flash(_('Board member not found.'), 'error')
        return redirect(url_for('governance.dashboard'))
    
    # Get committees where member is a participant
    db = get_db()
    committees = db.execute('''
        SELECT c.*, cm.role as member_role
        FROM board_committees c
        JOIN committee_memberships cm ON c.id = cm.committee_id
        WHERE cm.member_id = %s
    ''', (id,)).fetchall()
    
    assessments = FitProperAssessment.get_by_member(id)
    declarations = IndependenceDeclaration.get_by_member(id)
    
    return render_template('governance/member_view.html',
                         member=member,
                         committees=committees,
                         assessments=assessments,
                         declarations=declarations)

@governance_bp.route('/members/<int:id>/document')
@login_required
@permission_required('governance')
def member_document(id):
    """Serve a board member's uploaded document — same guard as view_member."""
    member = BoardMember.get_by_id(id)
    if not member or not member.document_path:
        flash(_('Document not found.'), 'error')
        return redirect(url_for('governance.dashboard'))
    return serve_uploaded_file(member.document_path)

# Committee Routes
@governance_bp.route('/committees')
@governance_bp.route('/committee')          # singular alias - all other
@governance_bp.route('/committee/list')     # committee URLs are singular
@login_required
@permission_required('governance')
def list_committees():
    committees = BoardCommittee.get_all()
    return render_template('governance/committee_list.html', committees=committees)

@governance_bp.route('/committee/add', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def add_committee():
    if request.method == 'POST':
        data = {
            'committee_name': request.form.get('committee_name'),
            'committee_type': request.form.get('committee_type', '').upper().strip(),
            'chairman_id': request.form.get('chairman_id'),
            'meeting_frequency': request.form.get('meeting_frequency')
        }
        
        # Handle Committee Charter Upload
        file = request.files.get('charter_file')
        if file and file.filename:
            filename = secure_filename(f"charter_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
            upload_path = os.path.join(current_app.root_path, 'uploads/governance/committees', filename)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            file.save(upload_path)
            data['charter_file'] = f"uploads/governance/committees/{filename}"
            
        BoardCommittee.create(data)
        flash(_('Committee created successfully.'), 'success')
        return redirect(url_for('governance.list_committees'))
    
    members = BoardMember.get_all()
    return render_template('governance/committee_form.html', members=members)

@governance_bp.route('/committee/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def edit_committee(id):
    committee = BoardCommittee.get_by_id(id)
    if not committee:
        flash(_('Committee not found.'), 'danger')
        return redirect(url_for('governance.list_committees'))

    if request.method == 'POST':
        data = {
            'committee_name': request.form.get('committee_name'),
            'committee_type': request.form.get('committee_type', '').upper().strip(),
            'chairman_id': request.form.get('chairman_id'),
            'meeting_frequency': request.form.get('meeting_frequency'),
            'is_active': 'is_active' in request.form
        }
        
        # Handle Committee Charter Upload
        file = request.files.get('charter_file')
        if file and file.filename:
            filename = secure_filename(f"committee_{id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
            upload_path = os.path.join(current_app.root_path, 'uploads/governance/committees', filename)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            file.save(upload_path)
            data['charter_file'] = f"uploads/governance/committees/{filename}"
            
        committee.update(data)
        flash(_('Committee updated successfully.'), 'success')
        return redirect(url_for('governance.list_committees'))
    
    members = BoardMember.get_all()
    return render_template('governance/committee_form.html', committee=committee, members=members)

@governance_bp.route('/committee/delete/<int:id>')
@login_required
@permission_required('governance', level='edit')
def delete_committee(id):
    BoardCommittee.delete(id)
    flash(_('Committee deactivated.'), 'success')
    return redirect(url_for('governance.list_committees'))

@governance_bp.route('/committee/<int:id>/charter')
@login_required
@permission_required('governance')
def committee_charter(id):
    """Serve a committee's uploaded charter — same guard as the committee pages."""
    committee = BoardCommittee.get_by_id(id)
    if not committee:
        flash(_('Committee not found.'), 'danger')
        return redirect(url_for('governance.list_committees'))
    if not committee.charter_file:
        flash(_('No charter has been uploaded for this committee yet. '
                'Use Edit Committee to upload one.'), 'warning')
        return redirect(url_for('governance.edit_committee', id=id))
    # The DB can point at a file that is no longer on disk (restored backup,
    # manual cleanup). send_from_directory would abort(404) with a generic
    # "Record Not Found" page, which tells the user nothing.
    abs_path = os.path.join(current_app.root_path, committee.charter_file)
    if not os.path.isfile(abs_path):
        flash(_('The charter file for this committee is missing from the '
                'server. Please upload it again.'), 'danger')
        return redirect(url_for('governance.edit_committee', id=id))
    return serve_uploaded_file(committee.charter_file)

# Role Management
@governance_bp.route('/roles', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def manage_roles():
    if request.method == 'POST':
        role_name = request.form.get('role_name')
        description = request.form.get('description')
        if role_name:
            BoardRole.create(role_name, description)
            flash(_('Role added successfully.'), 'success')
    
    roles = BoardRole.get_all()
    return render_template('governance/roles_list.html', roles=roles)

@governance_bp.route('/role/delete/<int:id>')
@login_required
@permission_required('governance', level='edit')
def delete_role(id):
    BoardRole.delete(id)
    flash(_('Role removed.'), 'success')
    return redirect(url_for('governance.manage_roles'))

@governance_bp.route('/committee/<int:id>/members', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def manage_committee_members(id):
    committee = BoardCommittee.get_by_id(id)
    if not committee:
        flash(_('Committee not found.'), 'danger')
        return redirect(url_for('governance.list_committees'))
    if request.method == 'POST':
        member_id = request.form.get('member_id')
        role = request.form.get('role', 'MEMBER')
        CommitteeMembership.add_member(id, member_id, role)
        flash(_('Member added to committee.'), 'success')
        return redirect(url_for('governance.manage_committee_members', id=id))
    
    current_members = CommitteeMembership.get_by_committee(id)
    all_members = BoardMember.get_all()
    return render_template('governance/committee_members.html', 
                       committee=committee, 
                       current_members=current_members, 
                       all_members=all_members)

# Meeting Routes
@governance_bp.route('/meetings')
@login_required
@permission_required('governance')
def list_meetings():
    upcoming = BoardMeeting.get_upcoming()
    past = BoardMeeting.get_past()
    return render_template('governance/meeting_list.html', upcoming=upcoming, past=past)

@governance_bp.route('/meeting/schedule', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def schedule_meeting():
    if request.method == 'POST':
        data = {
            'meeting_type': request.form.get('meeting_type'),
            'meeting_date': request.form.get('meeting_date'),
            'meeting_time': request.form.get('meeting_time') or None,
            'location': request.form.get('location') or None,
            'committee_id': request.form.get('committee_id') or None,
            'meeting_reference': request.form.get('meeting_reference') or None,
            'agenda': request.form.get('agenda')
        }
        attendee_ids = request.form.getlist('attendees')
        BoardMeeting.create(data, attendee_ids=attendee_ids)
        flash(_('Meeting scheduled successfully.'), 'success')
        return redirect(url_for('governance.list_meetings'))
    
    committees = BoardCommittee.get_all()
    members = BoardMember.get_all()
    return render_template('governance/meeting_form.html', committees=committees, members=members)

@governance_bp.route('/meeting/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def edit_meeting(id):
    meeting = BoardMeeting.get_by_id(id)
    if not meeting:
        flash(_('Meeting not found.'), 'danger')
        return redirect(url_for('governance.list_meetings'))

    if request.method == 'POST':
        data = {
            'meeting_type': request.form.get('meeting_type'),
            'meeting_date': request.form.get('meeting_date'),
            'meeting_time': request.form.get('meeting_time'),
            'location': request.form.get('location'),
            'committee_id': request.form.get('committee_id') or None,
            'meeting_reference': request.form.get('meeting_reference'),
            'status': request.form.get('status')
        }
        meeting.update(data)
        flash(_('Meeting updated successfully.'), 'success')
        return redirect(url_for('governance.list_meetings'))
    
    committees = BoardCommittee.get_all()
    return render_template('governance/meeting_form.html', meeting=meeting, committees=committees)

@governance_bp.route('/meeting/delete/<int:id>')
@login_required
@permission_required('governance', level='edit')
def delete_meeting(id):
    # For now, just a simple delete or status change
    db = get_db()
    db.execute('DELETE FROM board_meetings WHERE id = %s', (id,))
    db.commit()
    flash(_('Meeting canceled and removed.'), 'success')
    return redirect(url_for('governance.list_meetings'))

@governance_bp.route('/meeting/<int:id>/attendance', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def record_attendance(id):
    meeting = BoardMeeting.get_by_id(id)
    if not meeting:
        flash(_('Meeting not found.'), 'danger')
        return redirect(url_for('governance.list_meetings'))
    if request.method == 'POST':
        # Processing attendance dictionary from form
        attendance_data = {}
        for key, value in request.form.items():
            if key.startswith('attended_'):
                member_id = key.split('_')[1]
                attendance_data[member_id] = {
                    'attended': value == 'on',
                    'apology_received': request.form.get(f'apology_{member_id}') == 'on',
                    'proxy_name': request.form.get(f'proxy_{member_id}')
                }
        MeetingAttendance.record_attendance(id, attendance_data)
        flash(_('Attendance recorded.'), 'success')
        return redirect(url_for('governance.list_meetings'))
    
    # Logic to get relevant members (Board or Committee)
    if meeting.committee_id:
        members = CommitteeMembership.get_by_committee(meeting.committee_id)
    else:
        members = BoardMember.get_all()
        
    return render_template('governance/meeting_attendance.html', meeting=meeting, members=members)

@governance_bp.route('/meeting/invite/<int:id>')
@login_required
@permission_required('governance', level='edit')
def send_meeting_invite(id):
    meeting = BoardMeeting.get_by_id(id)
    if not meeting:
        flash(_('Meeting not found.'), 'danger')
        return redirect(url_for('governance.list_meetings'))
    # NOTE: nothing is actually sent — this writes an audit entry only.
    AuditLog.log(current_user.id, 'Send Meeting Invites', 'Governance', id, 
                f'Simulation: Sent invites for meeting on {meeting.meeting_date}', request.remote_addr)
    flash(_('Meeting logged for invitation. Note: email delivery is not yet '
            'configured, so no invitations have actually been sent.'), 'warning')
    return redirect(url_for('governance.list_meetings'))

@governance_bp.route('/meeting/summary/<int:id>')
@login_required
@permission_required('governance')
def meeting_summary(id):
    meeting = BoardMeeting.get_by_id(id)
    if not meeting:
        flash(_('Meeting not found.'), 'danger')
        return redirect(url_for('governance.list_meetings'))
    attendance = BoardMeeting.get_attendance_summary(id)
    return render_template('governance/meeting_summary.html', meeting=meeting, attendance=attendance,
                            attach_module='governance', attach_record_type='board_meeting', attach_record_id=id,
                            attach_items=list_attachments('governance', 'board_meeting', id),
                            attach_can_edit=current_user.can_edit('governance'))

@governance_bp.route('/governance/report')
@login_required
@permission_required('governance')
def governance_report():
        
    members = BoardMember.get_all()
    committees = BoardCommittee.get_all()
    meetings = BoardMeeting.get_all()
    
    summary_data = []
    for m in meetings:
        attendance = BoardMeeting.get_attendance_summary(m.id)
        summary_data.append({
            'meeting': m,
            'attendance': attendance
        })
    return render_template('governance/governance_report.html', 
                         members=members, 
                         committees=committees,
                         summary_data=summary_data)

# ============================================================================
# ENHANCED GOVERNANCE FEATURES (CBE COMPLIANT)
# ============================================================================

# 1. Fit & Proper Assessments
@governance_bp.route('/fit-proper')
@login_required
@permission_required('governance')
def fit_proper_dashboard():
    assessments = FitProperAssessment.get_due_for_review()
    return render_template('governance/fit_proper_dashboard.html', 
                         assessments=assessments,
                         title=_('Fit & Proper Assessments'))

@governance_bp.route('/fit-proper/add/<int:member_id>', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def add_fit_proper(member_id):
    member = BoardMember.get_by_id(member_id)
    if not member:
        flash(_('Board member not found.'), 'danger')
        return redirect(url_for('governance.fit_proper_dashboard'))
    if request.method == 'POST':
        data = {
            'member_id': member_id,
            'assessment_date': request.form.get('assessment_date'),
            'assessment_type': request.form.get('assessment_type'),
            'assessment_period': request.form.get('assessment_period'),
            'honesty_integrity_score': int(request.form.get('honesty_integrity_score', 0)),
            'competence_capability_score': int(request.form.get('competence_capability_score', 0)),
            'financial_soundness_score': int(request.form.get('financial_soundness_score', 0)),
            'reputation_score': int(request.form.get('reputation_score', 0)),
            'time_commitment_score': int(request.form.get('time_commitment_score', 0)),
            'assessment_result': request.form.get('assessment_result'),
            'regulator_id': request.form.get('regulator_id') or None,
            'submitted_to_regulator': request.form.get('submitted_to_regulator') == 'on',
            'regulator_submission_date': request.form.get('regulator_submission_date') or None,
            'regulator_reference_number': request.form.get('regulator_reference_number') or None,
            'regulator_approval_date': request.form.get('regulator_approval_date') or None,
            'regulator_approval_status': request.form.get('regulator_approval_status') or None,
            'regulator_feedback': request.form.get('regulator_feedback') or None,
            'created_by': current_user.id
        }
        FitProperAssessment.create(data)
        AuditLog.log(current_user.id, 'Create Fit & Proper', 'Governance', member_id, f'Assessment for {member.member_name}', request.remote_addr)
        flash(_('Assessment added successfully.'), 'success')
        return redirect(url_for('governance.fit_proper_dashboard'))

    previous = FitProperAssessment.get_by_member(member_id)
    return render_template('governance/fit_proper_form.html', member=member, previous=previous,
                            regulators=Regulator.get_all(), today=datetime.now().date().isoformat())

# 2. Independence Declarations
@governance_bp.route('/independence')
@login_required
@permission_required('governance')
def independence_dashboard():
    members = BoardMember.get_all()
    # Enhance members with current status
    for m in members:
        m.independence_status = IndependenceDeclaration.get_current_status(m.id)
    return render_template('governance/independence_dashboard.html', members=members)

@governance_bp.route('/independence/declare/<int:member_id>', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def declare_independence(member_id):
    member = BoardMember.get_by_id(member_id)
    if not member:
        flash(_('Member not found.'), 'error')
        return redirect(url_for('governance.independence_dashboard'))

    if request.method == 'POST':
        data = request.form.to_dict()
        data['member_id'] = member_id
        checkboxes = ['no_material_interest', 'no_employment_5years', 'no_relative_employment',
                     'no_professional_relationship', 'no_significant_business',
                     'no_remuneration_except_fees', 'served_less_than_9years', 'no_other_directorships']
        for cb in checkboxes:
            data[cb] = 1 if cb in request.form else 0

        IndependenceDeclaration.create(data)
        flash(_('Independence declaration submitted successfully.'), 'success')
        return redirect(url_for('governance.independence_dashboard'))

    return render_template('governance/independence_form.html', member=member,
                            tenure_years=Settings.get_int('governance_independence_tenure_years', 9),
                            shareholding_pct=Settings.get_int('governance_independence_shareholding_pct', 5))

@governance_bp.route('/fit-proper/view/<int:id>')
@login_required
@permission_required('governance')
def view_fit_proper(id):
    db = get_db()
    assessment = db.execute('''
        SELECT a.*, m.member_name, reg.regulator_name
        FROM fit_proper_assessments a
        JOIN board_members m ON a.member_id = m.id
        LEFT JOIN regulators reg ON a.regulator_id = reg.id
        WHERE a.id = %s
    ''', (id,)).fetchone()
    if not assessment:
        flash(_('Assessment not found.'), 'error')
        return redirect(url_for('governance.fit_proper_dashboard'))
    return render_template('governance/fit_proper_print.html', assessment=assessment, now=datetime.now(),
                            attach_module='governance', attach_record_type='fit_proper_assessment', attach_record_id=id,
                            attach_items=list_attachments('governance', 'fit_proper_assessment', id),
                            attach_can_edit=current_user.can_edit('governance'))

@governance_bp.route('/independence/view/<int:id>')
@login_required
@permission_required('governance')
def view_independence(id):
    db = get_db()
    declaration = db.execute('SELECT d.*, m.member_name FROM independence_declarations d JOIN board_members m ON d.member_id = m.id WHERE d.id = %s', (id,)).fetchone()
    if not declaration:
        flash(_('Declaration not found.'), 'error')
        return redirect(url_for('governance.independence_dashboard'))
    return render_template('governance/independence_print.html', declaration=declaration,
                            attach_module='governance', attach_record_type='independence_declaration', attach_record_id=id,
                            attach_items=list_attachments('governance', 'independence_declaration', id),
                            attach_can_edit=current_user.can_edit('governance'))

@governance_bp.route('/independence/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def edit_independence(id):
    db = get_db()
    declaration = db.execute('SELECT * FROM independence_declarations WHERE id = %s', (id,)).fetchone()
    if not declaration:
        flash(_('Declaration not found.'), 'error')
        return redirect(url_for('governance.independence_dashboard'))
    
    member = BoardMember.get_by_id(declaration['member_id'])
    
    if request.method == 'POST':
        data = request.form.to_dict()
        checkboxes = ['no_material_interest', 'no_employment_5years', 'no_relative_employment',
                     'no_professional_relationship', 'no_significant_business',
                     'no_remuneration_except_fees', 'served_less_than_9years', 'no_other_directorships']
        for cb in checkboxes:
            data[cb] = 1 if cb in request.form else 0

        criteria_met = all(data[cb] for cb in checkboxes)
        independence_status = 'INDEPENDENT' if criteria_met else 'NON_INDEPENDENT'

        db.execute('''
            UPDATE independence_declarations SET
                no_material_interest = %s, no_employment_5years = %s,
                no_relative_employment = %s, no_professional_relationship = %s,
                no_significant_business = %s, no_remuneration_except_fees = %s,
                served_less_than_9years = %s, no_other_directorships = %s,
                independence_status = %s, explanation = %s
            WHERE id = %s
        ''', (
            data['no_material_interest'], data['no_employment_5years'],
            data['no_relative_employment'], data['no_professional_relationship'],
            data['no_significant_business'], data['no_remuneration_except_fees'],
            data['served_less_than_9years'], data['no_other_directorships'],
            independence_status, data.get('explanation'),
            id
        ))
        db.commit()
        flash(_('Declaration updated.'), 'success')
        return redirect(url_for('governance.independence_dashboard'))

    return render_template('governance/independence_form.html', member=member, declaration=declaration,
                            tenure_years=Settings.get_int('governance_independence_tenure_years', 9),
                            shareholding_pct=Settings.get_int('governance_independence_shareholding_pct', 5))

# 3. Board Skills Matrix
@governance_bp.route('/skills')
@login_required
@permission_required('governance')
def skills_matrix_dashboard():
    summary = BoardSkillsMatrix.get_board_skills_summary()
    members = BoardMember.get_all()
    return render_template('governance/skills_matrix.html', summary=summary, members=members, BoardSkillsMatrix=BoardSkillsMatrix)

@governance_bp.route('/skills/assess/<int:member_id>', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def assess_skills(member_id):
    member = BoardMember.get_by_id(member_id)
    if not member:
        flash(_('Board member not found.'), 'danger')
        return redirect(url_for("governance.skills_matrix_dashboard"))
    if request.method == 'POST':
        data = request.form.to_dict()
        data['member_id'] = member_id
        # Convert checkbox
        data['has_professional_certifications'] = 'has_professional_certifications' in request.form
        # Convert scores to int
        score_fields = ['financial_expertise', 'risk_management', 'compliance_regulatory', 
                       'technology_digital', 'strategy_business', 'human_resources',
                       'legal', 'audit', 'marketing_sales', 'operations']
        for f in score_fields:
            data[f] = int(data.get(f, 0))
            
        BoardSkillsMatrix.create(data)
        flash(_('Skills assessment saved.'), 'success')
        return redirect(url_for('governance.skills_matrix_dashboard'))
        
    return render_template('governance/skills_assessment_form.html', member=member)

# 4. Compliance Tracker
@governance_bp.route('/compliance')
@login_required
@permission_required('governance')
def compliance_dashboard():
    show_inactive = request.args.get('include_inactive') == '1'
    requirements = GovernanceCompliance.get_all(include_inactive=show_inactive)
    return render_template('governance/compliance_tracker.html', requirements=requirements, show_inactive=show_inactive)

@governance_bp.route('/compliance/update/<int:id>', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def update_compliance(id):
    status = request.form.get('compliance_status')
    evidence = request.form.get('evidence_description')
    notes = request.form.get('notes')
    GovernanceCompliance.update_status(id, status, evidence, notes)
    flash(_('Compliance status updated.'), 'success')
    return redirect(url_for('governance.compliance_dashboard'))

@governance_bp.route('/compliance/add', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def add_compliance():
    """Add a new compliance requirement — the way to extend the tracker for a
    new or foreign regulator without needing a database script."""
    if request.method == 'POST':
        data = {
            'requirement_code': request.form.get('requirement_code'),
            'requirement_description': request.form.get('requirement_description'),
            'compliance_area': request.form.get('compliance_area'),
            'regulator_id': request.form.get('regulator_id') or None,
            'regulatory_source': request.form.get('regulatory_source'),
            'compliance_status': request.form.get('compliance_status', 'NON_COMPLIANT'),
            'due_date': request.form.get('due_date') or None,
        }
        new_id = GovernanceCompliance.create(data)
        AuditLog.log(current_user.id, 'Add Compliance Requirement', 'Governance', new_id,
                     f'Added requirement {data["requirement_code"]}', request.remote_addr)
        flash(_('New compliance requirement added.'), 'success')
        return redirect(url_for('governance.compliance_dashboard'))

    regulators = Regulator.get_all()
    return render_template('governance/compliance_form.html', regulators=regulators)

@governance_bp.route('/compliance/deactivate/<int:id>')
@login_required
@permission_required('governance', level='edit')
def deactivate_compliance(id):
    GovernanceCompliance.set_active(id, False)
    flash(_('Requirement retired.'), 'success')
    return redirect(url_for('governance.compliance_dashboard'))

@governance_bp.route('/compliance/reactivate/<int:id>')
@login_required
@permission_required('governance', level='edit')
def reactivate_compliance(id):
    GovernanceCompliance.set_active(id, True)
    flash(_('Requirement reactivated.'), 'success')
    return redirect(url_for('governance.compliance_dashboard', include_inactive=1))

# 5. CBE Reports
@governance_bp.route('/compliance/edit/<int:id>')
@login_required
@permission_required('governance', level='edit')
def edit_compliance(id):
    req = GovernanceCompliance.get_by_id(id)
    if not req:
        flash(_('Requirement not found.'), 'danger')
        return redirect(url_for('governance.compliance_dashboard'))
    return render_template('governance/compliance_edit.html', req=req)

# Corporate Governance Disclosure Report — regulator-agnostic, filterable by
# ?regulator_id= for companies reporting to more than one regulator.
@governance_bp.route('/cbe-report')
@login_required
@permission_required('governance')
def cbe_governance_report():
    # Legacy URL kept working for anyone with it bookmarked.
    return redirect(url_for('governance.disclosure_report', **request.args))

@governance_bp.route('/disclosure-report')
@login_required
@permission_required('governance')
def disclosure_report():
    regulator_id = request.args.get('regulator_id', type=int)

    board_members = BoardMember.get_all()
    committees = BoardCommittee.get_all()
    meetings = BoardMeeting.get_upcoming() + BoardMeeting.get_past()
    training = BoardTraining.get_upcoming()
    compliance = GovernanceCompliance.get_all()
    regulators = Regulator.get_all()
    selected_regulator = None

    if regulator_id:
        compliance = [c for c in compliance if c.regulator_id == regulator_id]
        selected_regulator = next((r for r in regulators if r.id == regulator_id), None)

    return render_template('governance/cbe_governance_report.html',
                         board_members=board_members,
                         committees=committees,
                         meetings=meetings,
                         training=training,
                         compliance=compliance,
                         regulators=regulators,
                         selected_regulator=selected_regulator,
                         company_name=Settings.get('company_name', 'ComplyNex'),
                         today=datetime.now())


# ============================================================================
# ANNUAL GOVERNANCE REPORTING SUITE (added 2026-07-24)
# ============================================================================
# Three year-scoped, printable reports building on the same underlying
# governance data as disclosure_report() above, but each addressed to a
# specific audience/purpose instead of one generic filterable page:
#   - annual_board_report        -> "تقرير مجلس إدارة سنوي" / Annual Board of
#                                    Directors Report: board composition,
#                                    meetings/attendance, decisions, committee
#                                    activity for one reporting year.
#   - annual_governance_report   -> "تقرير حوكمة سنوي" / Annual Governance
#                                    Report: the wider governance framework —
#                                    compliance tracker status, ESG 'G' pillar
#                                    score, fit & proper / independence
#                                    coverage, training, internal audit
#                                    committee summary.
#   - fra_governance_report      -> the same governance disclosure, addressed
#                                    to the Financial Regulatory Authority
#                                    specifically (regulator_id pre-selected),
#                                    since FRA-regulated entities need this as
#                                    a distinct submission from the CBE one.
# All three take an optional ?year=YYYY (defaults to the current year) and
# degrade gracefully to "no data recorded for this year" rather than erroring
# when a section has nothing yet — these are meant to be usable from day one
# of adoption, not only once years of history exist.

def _report_years_available():
    """Years with any board activity recorded, newest first, always including
    the current year so the report is usable even with zero history yet."""
    db = get_db()
    rows = db.execute("""
        SELECT DISTINCT EXTRACT(YEAR FROM meeting_date::date)::int AS y
        FROM board_meetings WHERE meeting_date IS NOT NULL
        UNION
        SELECT DISTINCT EXTRACT(YEAR FROM training_date::date)::int AS y
        FROM board_training WHERE training_date IS NOT NULL
    """).fetchall()
    years = sorted({r['y'] for r in rows if r['y']} | {datetime.now().year}, reverse=True)
    return years


@governance_bp.route('/annual-board-report')
@login_required
@permission_required('governance')
def annual_board_report():
    year = request.args.get('year', type=int) or datetime.now().year
    db = get_db()

    board_members = BoardMember.get_all()

    meetings = db.execute("""
        SELECT * FROM board_meetings
        WHERE EXTRACT(YEAR FROM meeting_date::date) = %s
        ORDER BY meeting_date
    """, (year,)).fetchall()

    decisions = db.execute("""
        SELECT d.*, m.meeting_date, m.meeting_type
        FROM board_decisions d
        JOIN board_meetings m ON d.meeting_id = m.id
        WHERE EXTRACT(YEAR FROM m.meeting_date::date) = %s
        ORDER BY m.meeting_date
    """, (year,)).fetchall()

    # Attendance rate per member across this year's meetings
    attendance_rows = db.execute("""
        SELECT a.member_id, m2.member_name,
               COUNT(*) FILTER (WHERE a.attended = 1) AS attended_count,
               COUNT(*) AS total_count
        FROM meeting_attendance a
        JOIN board_meetings mt ON a.meeting_id = mt.id
        JOIN board_members m2 ON a.member_id = m2.id
        WHERE EXTRACT(YEAR FROM mt.meeting_date::date) = %s
        GROUP BY a.member_id, m2.member_name
        ORDER BY m2.member_name
    """, (year,)).fetchall()

    committees = BoardCommittee.get_all()
    committee_meeting_counts = {}
    for c in committees:
        cnt = db.execute("""
            SELECT COUNT(*) AS n FROM board_meetings
            WHERE committee_id = %s AND EXTRACT(YEAR FROM meeting_date::date) = %s
        """, (c.id, year)).fetchone()
        committee_meeting_counts[c.id] = cnt['n'] if cnt else 0

    training = db.execute("""
        SELECT * FROM board_training
        WHERE EXTRACT(YEAR FROM training_date::date) = %s
        ORDER BY training_date
    """, (year,)).fetchall()

    # evaluation_period is free-text (e.g. "2026" or "FY2026 H1"), so match
    # loosely on the year rather than requiring an exact string match.
    evaluations = db.execute("""
        SELECT * FROM board_evaluations WHERE evaluation_period ILIKE %s
    """, (f'%{year}%',)).fetchall()

    return render_template(
        'governance/annual_board_report.html',
        year=year, years_available=_report_years_available(),
        board_members=board_members, meetings=meetings, decisions=decisions,
        attendance_rows=attendance_rows, committees=committees,
        committee_meeting_counts=committee_meeting_counts, training=training,
        evaluations=evaluations, company_name=Settings.get('company_name', 'ComplyNex'),
        generated_at=datetime.now(),
        attach_module='governance', attach_record_type='annual_board_report', attach_record_id=year,
        attach_items=list_attachments('governance', 'annual_board_report', year),
        attach_can_edit=current_user.can_edit('governance'),
    )


@governance_bp.route('/annual-governance-report')
@login_required
@permission_required('governance')
def annual_governance_report():
    year = request.args.get('year', type=int) or datetime.now().year
    db = get_db()

    compliance = GovernanceCompliance.get_all()
    committees = BoardCommittee.get_all()
    board_members = BoardMember.get_all()

    fit_proper_rows = db.execute("""
        SELECT a.*, m.member_name FROM fit_proper_assessments a
        JOIN board_members m ON a.member_id = m.id
        WHERE EXTRACT(YEAR FROM a.assessment_date::date) = %s
        ORDER BY m.member_name
    """, (year,)).fetchall()

    independence_rows = db.execute("""
        SELECT d.*, m.member_name FROM independence_declarations d
        JOIN board_members m ON d.member_id = m.id
        WHERE EXTRACT(YEAR FROM d.declaration_date::date) = %s
        ORDER BY m.member_name
    """, (year,)).fetchall() if _column_exists(db, 'independence_declarations', 'declaration_date') else []

    training_count = db.execute("""
        SELECT COUNT(*) AS n FROM board_training
        WHERE EXTRACT(YEAR FROM training_date::date) = %s
    """, (year,)).fetchone()

    meetings_count = db.execute("""
        SELECT COUNT(*) AS n FROM board_meetings
        WHERE EXTRACT(YEAR FROM meeting_date::date) = %s
    """, (year,)).fetchone()

    # ESG Governance ('G') pillar score, if the ESG framework/period is set up —
    # ties this governance report back to the same score shown on the ESG
    # scoring page, so the two never silently disagree.
    esg_g_summary = None
    try:
        from esg.routes import _default_framework, _current_period, _pillars_with_indicators
        from esg.engine import build_pillar_summary
        framework = _default_framework()
        period = _current_period()
        if framework and period:
            pillars_full = _pillars_with_indicators(framework['id'], period['id'])
            summary = build_pillar_summary(pillars_full)
            esg_g_summary = next((s for s in summary['pillars'] if s['code'] == 'G'), None)
    except Exception as e:
        logger.warning(f"annual_governance_report: could not compute ESG G-pillar summary: {e}")

    # Internal Audit committee-level summary, if that module has any data yet.
    committee_findings_summary = None
    try:
        from models.internal_audit import generate_committee_report
        committee_findings_summary = generate_committee_report()
    except Exception:
        committee_findings_summary = None

    return render_template(
        'governance/annual_governance_report.html',
        year=year, years_available=_report_years_available(),
        compliance=compliance, committees=committees, board_members=board_members,
        fit_proper_rows=fit_proper_rows, independence_rows=independence_rows,
        training_count=(training_count['n'] if training_count else 0),
        meetings_count=(meetings_count['n'] if meetings_count else 0),
        esg_g_summary=esg_g_summary, committee_findings_summary=committee_findings_summary,
        company_name=Settings.get('company_name', 'ComplyNex'), generated_at=datetime.now(),
        attach_module='governance', attach_record_type='annual_governance_report', attach_record_id=year,
        attach_items=list_attachments('governance', 'annual_governance_report', year),
        attach_can_edit=current_user.can_edit('governance'),
    )


@governance_bp.route('/fra-report')
@login_required
@permission_required('governance')
def fra_governance_report():
    year = request.args.get('year', type=int) or datetime.now().year
    db = get_db()

    fra_regulator = db.execute(
        "SELECT * FROM regulators WHERE regulator_name ILIKE %s LIMIT 1",
        ('%Financial Regulatory Authority%',)
    ).fetchone()

    compliance = GovernanceCompliance.get_all()
    if fra_regulator:
        compliance = [c for c in compliance if c.regulator_id == fra_regulator['id']]

    board_members = BoardMember.get_all()
    committees = BoardCommittee.get_all()
    meetings_count = db.execute("""
        SELECT COUNT(*) AS n FROM board_meetings
        WHERE EXTRACT(YEAR FROM meeting_date::date) = %s
    """, (year,)).fetchone()

    return render_template(
        'governance/fra_governance_report.html',
        year=year, years_available=_report_years_available(),
        fra_regulator=fra_regulator, compliance=compliance,
        board_members=board_members, committees=committees,
        meetings_count=(meetings_count['n'] if meetings_count else 0),
        company_name=Settings.get('company_name', 'ComplyNex'), generated_at=datetime.now(),
        attach_module='governance', attach_record_type='fra_governance_report', attach_record_id=year,
        attach_items=list_attachments('governance', 'fra_governance_report', year),
        attach_can_edit=current_user.can_edit('governance'),
    )


def _column_exists(db, table, column):
    row = db.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column)).fetchone()
    return bool(row)
