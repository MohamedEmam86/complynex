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

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from flask_babel import gettext as _
from werkzeug.utils import secure_filename

from utils.decorators import permission_required
from utils.file_serving import serve_uploaded_file
from models.audit import AuditLog
from models.notification import Notification
from models.department import Department
from models.user import User
from models.risk import (
    Risk, RiskCategory, RiskScoringBand, RiskAppetiteStatement, Control, RiskControl,
    ControlTestResult, KRI, KRIMeasurement, RiskTreatment, RiskSourceLink,
    RiskScoreHistory, get_pending_risk_suggestions,
)

risk_bp = Blueprint('risk_management', __name__, url_prefix='/risk-management')


def _save_evidence(file, subfolder, entity_id):
    """Shared upload helper — non-static uploads/<module>/<entity>/<file>, not reachable
    via Flask's unauthenticated /static/ route."""
    if not file or not file.filename:
        return None
    filename = secure_filename(f"{entity_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
    rel_dir = f"risk_management/{subfolder}/{entity_id}"
    upload_path = os.path.join(current_app.root_path, 'uploads', rel_dir, filename)
    os.makedirs(os.path.dirname(upload_path), exist_ok=True)
    file.save(upload_path)
    return f"uploads/{rel_dir}/{filename}"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@risk_bp.route('/')
@risk_bp.route('/dashboard')
@login_required
@permission_required('risk_management')
def dashboard():
    risks = Risk.get_all(status='ACTIVE')
    bands = RiskScoringBand.get_all()
    categories = {c.id: c for c in RiskCategory.get_all()}

    # 5x5 heat-map: count of active risks per (likelihood, impact) cell
    heat_map = {}
    for r in risks:
        key = (r.likelihood, r.impact)
        heat_map[key] = heat_map.get(key, 0) + 1

    top_risks = sorted(
        risks, key=lambda r: (r.residual_risk_score or r.inherent_risk_score or 0), reverse=True
    )[:10]

    suggestion_count = len(get_pending_risk_suggestions()) if current_user.can_edit('risk_management') else 0

    return render_template(
        'risk_management/dashboard.html',
        risks=risks, bands=bands, categories=categories, heat_map=heat_map,
        top_risks=top_risks, suggestion_count=suggestion_count,
    )


# ---------------------------------------------------------------------------
# Risk register
# ---------------------------------------------------------------------------

@risk_bp.route('/register')
@login_required
@permission_required('risk_management')
def register_list():
    category_id = request.args.get('category_id', type=int)
    department_id = request.args.get('department_id', type=int)
    status = request.args.get('status') or None
    risks = Risk.get_all(category_id=category_id, department_id=department_id, status=status)
    categories = {c.id: c for c in RiskCategory.get_all(include_inactive=True)}
    departments = {d.id: d for d in Department.get_all()}
    users_by_id = {u.id: u for u in User.get_all()}
    bands = RiskScoringBand.get_all()

    def _band_for(score):
        if score is None:
            return None
        return next((b for b in bands if b.min_score <= score <= b.max_score), None)

    score_bands = {}
    for r in risks:
        score_bands[r.id] = {
            'inherent': _band_for(r.inherent_risk_score),
            'residual': _band_for(r.residual_risk_score),
        }

    return render_template(
        'risk_management/register_list.html',
        risks=risks, categories=categories, departments=departments,
        all_categories=RiskCategory.get_all(), all_departments=Department.get_all(),
        users_by_id=users_by_id, score_bands=score_bands,
        current_category_id=category_id, current_department_id=department_id, current_status=status,
    )


@risk_bp.route('/register/new', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def register_new():
    if request.method == 'POST':
        risk = Risk.create(
            risk_title=request.form.get('risk_title'),
            category_id=request.form.get('category_id', type=int),
            likelihood=request.form.get('likelihood', type=int),
            impact=request.form.get('impact', type=int),
            risk_owner_id=request.form.get('risk_owner_id', type=int),
            created_by=current_user.id,
            risk_description=request.form.get('risk_description'),
            department_id=request.form.get('department_id', type=int) or None,
            existing_controls=request.form.get('existing_controls'),
            risk_response=request.form.get('risk_response') or None,
            review_frequency=request.form.get('review_frequency', 'QUARTERLY'),
            next_review_date=request.form.get('next_review_date') or None,
        )
        AuditLog.log(current_user.id, 'Create Risk', 'Risk Management', risk.id,
                     f'Registered risk {risk.risk_id}: {risk.risk_title}', request.remote_addr)
        flash('Risk registered successfully.', 'success')
        return redirect(url_for('risk_management.register_detail', risk_pk=risk.id))

    return render_template(
        'risk_management/risk_form.html', risk=None,
        categories=RiskCategory.get_all(), departments=Department.get_all(), users=User.get_all(),
    )


@risk_bp.route('/register/<int:risk_pk>')
@login_required
@permission_required('risk_management')
def register_detail(risk_pk):
    risk = Risk.get_by_id(risk_pk)
    if not risk:
        flash('Risk not found.', 'danger')
        return redirect(url_for('risk_management.register_list'))
    controls = RiskControl.get_controls_for_risk(risk_pk)
    treatments = RiskTreatment.get_for_risk(risk_pk)
    history = RiskScoreHistory.get_for_risk(risk_pk)
    links = RiskSourceLink.get_for_risk(risk_pk)
    kris = KRI.get_for_risk(risk_pk)
    category = RiskCategory.get_by_id(risk.category_id)
    owner = User.get_by_id(risk.risk_owner_id) if risk.risk_owner_id else None
    department = Department.get_by_id(risk.department_id) if risk.department_id else None
    inherent_band = RiskScoringBand.get_band_for_score(risk.inherent_risk_score) if risk.inherent_risk_score else None
    residual_band = RiskScoringBand.get_band_for_score(risk.residual_risk_score) if risk.residual_risk_score else None
    kri_latest_status = {}
    for k in kris:
        latest = KRIMeasurement.get_history(k.id, limit=1)
        kri_latest_status[k.id] = latest[0].status if latest else None
    return render_template(
        'risk_management/risk_detail.html', risk=risk, controls=controls, treatments=treatments,
        history=history, links=links, kris=kris, category=category, owner=owner,
        all_controls=Control.get_all(), department=department, inherent_band=inherent_band,
        residual_band=residual_band, kri_latest_status=kri_latest_status,
    )


@risk_bp.route('/register/<int:risk_pk>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def register_edit(risk_pk):
    risk = Risk.get_by_id(risk_pk)
    if not risk:
        flash('Risk not found.', 'danger')
        return redirect(url_for('risk_management.register_list'))

    if request.method == 'POST':
        likelihood = request.form.get('likelihood', type=int)
        impact = request.form.get('impact', type=int)
        residual_likelihood = request.form.get('residual_likelihood', type=int)
        residual_impact = request.form.get('residual_impact', type=int)
        control_effectiveness = request.form.get('control_effectiveness') or None

        Risk.update_scoring(
            risk_pk, likelihood, impact, residual_likelihood, residual_impact,
            control_effectiveness, changed_by=current_user.id,
            change_reason=request.form.get('change_reason'),
        )
        AuditLog.log(current_user.id, 'Update Risk Scoring', 'Risk Management', risk_pk,
                     f'Re-scored risk {risk.risk_id}', request.remote_addr)
        flash('Risk scoring updated.', 'success')
        return redirect(url_for('risk_management.register_detail', risk_pk=risk_pk))

    return render_template(
        'risk_management/risk_form.html', risk=risk,
        categories=RiskCategory.get_all(), departments=Department.get_all(), users=User.get_all(),
    )


@risk_bp.route('/register/<int:risk_pk>/close', methods=['POST'])
@login_required
@permission_required('risk_management', level='edit')
def register_close(risk_pk):
    status = request.form.get('status', 'CLOSED')
    Risk.close(risk_pk, status=status)
    AuditLog.log(current_user.id, 'Close Risk', 'Risk Management', risk_pk,
                 f'Risk marked {status}', request.remote_addr)
    flash(f'Risk marked as {status}.', 'success')
    return redirect(url_for('risk_management.register_detail', risk_pk=risk_pk))


@risk_bp.route('/register/<int:risk_pk>/link-source', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def register_link_source(risk_pk):
    risk = Risk.get_by_id(risk_pk)
    if not risk:
        flash(_('Risk not found.'), 'danger')
        return redirect(url_for("risk_management.register_list"))
    if request.method == 'POST':
        RiskSourceLink.create(
            risk_pk,
            source_module=request.form.get('source_module'),
            source_table=request.form.get('source_table'),
            source_record_id=request.form.get('source_record_id', type=int),
            link_type=request.form.get('link_type', 'RELATED'),
            linked_by=current_user.id,
            notes=request.form.get('notes'),
        )
        AuditLog.log(current_user.id, 'Link Risk Source', 'Risk Management', risk_pk,
                     'Manually linked a source-module record', request.remote_addr)
        flash('Source linked to risk.', 'success')
        return redirect(url_for('risk_management.register_detail', risk_pk=risk_pk))
    return render_template(
        'risk_management/link_source_form.html', risk=risk,
        allowed_modules=RiskSourceLink.ALLOWED_MODULES,
    )


# ---------------------------------------------------------------------------
# Suggested Risks inbox — human-in-the-loop, never auto-creates a risk
# ---------------------------------------------------------------------------

@risk_bp.route('/suggestions')
@login_required
@permission_required('risk_management', level='edit')
def suggestions():
    return render_template('risk_management/suggestions.html', suggestions=get_pending_risk_suggestions())


@risk_bp.route('/suggestions/<source_module>/<source_table>/<int:source_record_id>/create', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def suggestion_create(source_module, source_table, source_record_id):
    if request.method == 'POST':
        risk = Risk.create_draft_from_suggestion(
            source_module=source_module, source_table=source_table, source_record_id=source_record_id,
            risk_title=request.form.get('risk_title'),
            risk_owner_id=request.form.get('risk_owner_id', type=int),
            created_by=current_user.id,
            risk_description=request.form.get('risk_description'),
            category_code=request.form.get('category_code'),
        )
        AuditLog.log(current_user.id, 'Create Draft Risk From Suggestion', 'Risk Management', risk.id,
                     f'Draft risk {risk.risk_id} created from {source_module}.{source_table}#{source_record_id}',
                     request.remote_addr)
        flash(f'Draft risk {risk.risk_id} created — please review and complete scoring.', 'success')
        return redirect(url_for('risk_management.register_edit', risk_pk=risk.id))

    return render_template(
        'risk_management/suggestion_create_form.html',
        source_module=source_module, source_table=source_table, source_record_id=source_record_id,
        categories=RiskCategory.get_all(), users=User.get_all(),
    )


# ---------------------------------------------------------------------------
# Categories (taxonomy admin)
# ---------------------------------------------------------------------------

@risk_bp.route('/categories', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def categories():
    if request.method == 'POST':
        RiskCategory.create(
            category_code=request.form.get('category_code'),
            category_name=request.form.get('category_name'),
            category_description=request.form.get('category_description'),
            parent_category_id=request.form.get('parent_category_id', type=int) or None,
        )
        AuditLog.log(current_user.id, 'Create Risk Category', 'Risk Management', None,
                     f"Category '{request.form.get('category_code')}' created", request.remote_addr)
        flash('Risk category created.', 'success')
        return redirect(url_for('risk_management.categories'))
    all_categories = RiskCategory.get_all(include_inactive=True)
    usage = {c.id: RiskCategory.usage_count(c.id) for c in all_categories}
    return render_template('risk_management/categories.html', categories=all_categories, usage=usage)


@risk_bp.route('/categories/<int:category_id>/edit', methods=['POST'])
@login_required
@permission_required('risk_management', level='edit')
def category_edit(category_id):
    RiskCategory.update(
        category_id,
        category_name=request.form.get('category_name'),
        category_description=request.form.get('category_description'),
        parent_category_id=request.form.get('parent_category_id', type=int) or None,
    )
    AuditLog.log(current_user.id, 'Edit Risk Category', 'Risk Management', category_id,
                 'Category details updated', request.remote_addr)
    flash('Risk category updated.', 'success')
    return redirect(url_for('risk_management.categories'))


@risk_bp.route('/categories/<int:category_id>/archive', methods=['POST'])
@login_required
@permission_required('risk_management', level='edit')
def category_archive(category_id):
    RiskCategory.set_active(category_id, False)
    AuditLog.log(current_user.id, 'Archive Risk Category', 'Risk Management', category_id,
                 'Category archived (hidden from new risk selection)', request.remote_addr)
    flash('Risk category archived. Existing risks keep their reference; it will no longer appear for new selections.', 'success')
    return redirect(url_for('risk_management.categories'))


@risk_bp.route('/categories/<int:category_id>/reactivate', methods=['POST'])
@login_required
@permission_required('risk_management', level='edit')
def category_reactivate(category_id):
    RiskCategory.set_active(category_id, True)
    AuditLog.log(current_user.id, 'Reactivate Risk Category', 'Risk Management', category_id,
                 'Category reactivated', request.remote_addr)
    flash('Risk category reactivated.', 'success')
    return redirect(url_for('risk_management.categories'))


@risk_bp.route('/categories/<int:category_id>/delete', methods=['POST'])
@login_required
@permission_required('risk_management', level='edit')
def category_delete(category_id):
    try:
        RiskCategory.delete(category_id)
        AuditLog.log(current_user.id, 'Delete Risk Category', 'Risk Management', category_id,
                     'Category permanently deleted', request.remote_addr)
        flash('Risk category deleted.', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    return redirect(url_for('risk_management.categories'))


# ---------------------------------------------------------------------------
# Risk appetite
# ---------------------------------------------------------------------------

@risk_bp.route('/appetite', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def appetite():
    if request.method == 'POST':
        RiskAppetiteStatement.create(
            statement_text=request.form.get('statement_text'),
            appetite_level=request.form.get('appetite_level'),
            max_acceptable_residual_score=request.form.get('max_acceptable_residual_score', type=int),
            effective_from=request.form.get('effective_from'),
            category_id=request.form.get('category_id', type=int) or None,
            max_acceptable_inherent_score=request.form.get('max_acceptable_inherent_score', type=int) or None,
            effective_to=request.form.get('effective_to') or None,
            created_by=current_user.id,
        )
        AuditLog.log(current_user.id, 'Create Risk Appetite Statement', 'Risk Management', None,
                     'New risk appetite statement recorded', request.remote_addr)
        flash('Risk appetite statement recorded.', 'success')
        return redirect(url_for('risk_management.appetite'))
    return render_template(
        'risk_management/appetite.html',
        statements=RiskAppetiteStatement.get_all(), categories=RiskCategory.get_all(),
    )


# ---------------------------------------------------------------------------
# Control library (RCM)
# ---------------------------------------------------------------------------

@risk_bp.route('/controls')
@login_required
@permission_required('risk_management')
def controls_list():
    from datetime import date
    return render_template('risk_management/controls_list.html', controls=Control.get_all(), today=date.today())


@risk_bp.route('/controls/new', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def controls_new():
    if request.method == 'POST':
        control = Control.create(
            control_code=request.form.get('control_code'),
            control_name=request.form.get('control_name'),
            control_type=request.form.get('control_type'),
            control_description=request.form.get('control_description'),
            control_nature=request.form.get('control_nature', 'MANUAL'),
            control_owner_id=request.form.get('control_owner_id', type=int) or None,
            department_id=request.form.get('department_id', type=int) or None,
            testing_frequency=request.form.get('testing_frequency', 'ANNUAL'),
        )
        AuditLog.log(current_user.id, 'Create Control', 'Risk Management', control.id,
                     f'Created control {control.control_code}', request.remote_addr)
        flash('Control created.', 'success')
        return redirect(url_for('risk_management.controls_detail', control_id=control.id))
    return render_template(
        'risk_management/control_form.html', control=None,
        users=User.get_all(), departments=Department.get_all(),
    )


@risk_bp.route('/controls/<int:control_id>')
@login_required
@permission_required('risk_management')
def controls_detail(control_id):
    control = Control.get_by_id(control_id)
    if not control:
        flash('Control not found.', 'danger')
        return redirect(url_for('risk_management.controls_list'))
    linked_risks = RiskControl.get_risks_for_control(control_id)
    test_results = ControlTestResult.get_for_control(control_id)
    return render_template(
        'risk_management/control_detail.html', control=control,
        linked_risks=linked_risks, test_results=test_results, all_risks=Risk.get_all(),
    )


@risk_bp.route('/controls/<int:control_id>/link-risk', methods=['POST'])
@login_required
@permission_required('risk_management', level='edit')
def controls_link_risk(control_id):
    risk_pk = request.form.get('risk_pk', type=int)
    RiskControl.link(risk_pk, control_id, reliance_level=request.form.get('reliance_level', 'PRIMARY'))
    AuditLog.log(current_user.id, 'Link Control to Risk', 'Risk Management', control_id,
                 f'Linked control to risk #{risk_pk}', request.remote_addr)
    flash('Control linked to risk.', 'success')
    return redirect(url_for('risk_management.controls_detail', control_id=control_id))


@risk_bp.route('/controls/<int:control_id>/test', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def controls_test(control_id):
    control = Control.get_by_id(control_id)
    if not control:
        flash(_('Control not found.'), 'danger')
        return redirect(url_for("risk_management.controls_list"))
    if request.method == 'POST':
        evidence_path = _save_evidence(request.files.get('evidence_file'), 'controls', control_id)
        ControlTestResult.create(
            control_id=control_id, tested_by=current_user.id,
            test_date=request.form.get('test_date'), result=request.form.get('result'),
            test_procedure=request.form.get('test_procedure'),
            exceptions_noted=request.form.get('exceptions_noted'),
            evidence_file=evidence_path,
        )
        AuditLog.log(current_user.id, 'Log Control Test Result', 'Risk Management', control_id,
                     f'Test result: {request.form.get("result")}', request.remote_addr)
        flash('Control test result recorded.', 'success')
        return redirect(url_for('risk_management.controls_detail', control_id=control_id))
    return render_template('risk_management/control_test_form.html', control=control)


# ---------------------------------------------------------------------------
# KRIs
# ---------------------------------------------------------------------------

@risk_bp.route('/kris')
@login_required
@permission_required('risk_management')
def kris_dashboard():
    kris = KRI.get_all()
    histories = {k.id: KRIMeasurement.get_history(k.id, limit=12) for k in kris}
    risks_by_id = {r.id: r for r in Risk.get_all(status=None)}
    return render_template(
        'risk_management/kri_dashboard.html', kris=kris, histories=histories, risks_by_id=risks_by_id,
    )


@risk_bp.route('/kris/new', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def kris_new():
    if request.method == 'POST':
        kri = KRI.create(
            kri_name=request.form.get('kri_name'),
            direction=request.form.get('direction', 'UPPER'),
            risk_id=request.form.get('risk_id', type=int) or None,
            kri_description=request.form.get('kri_description'),
            unit_of_measure=request.form.get('unit_of_measure'),
            measurement_frequency=request.form.get('measurement_frequency', 'MONTHLY'),
            target_value=request.form.get('target_value', type=float) or None,
            warning_threshold=request.form.get('warning_threshold', type=float) or None,
            breach_threshold=request.form.get('breach_threshold', type=float) or None,
            owner_id=request.form.get('owner_id', type=int) or None,
        )
        AuditLog.log(current_user.id, 'Create KRI', 'Risk Management', kri.id,
                     f'Created KRI {kri.kri_name}', request.remote_addr)
        flash('KRI created.', 'success')
        return redirect(url_for('risk_management.kris_dashboard'))
    return render_template(
        'risk_management/kri_form.html', risks=Risk.get_all(), users=User.get_all(),
    )


@risk_bp.route('/kris/<int:kri_id>/measurements/new', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def kris_record_measurement(kri_id):
    kri = KRI.get_by_id(kri_id)
    if request.method == 'POST':
        _, status = KRIMeasurement.create(
            kri_id, measurement_date=request.form.get('measurement_date'),
            actual_value=request.form.get('actual_value', type=float),
            notes=request.form.get('notes'), recorded_by=current_user.id,
        )
        if status == 'RED' and kri.owner_id:
            Notification.create(
                user_id=kri.owner_id, title=f'KRI breach: {kri.kri_name}',
                message=f'A new measurement for "{kri.kri_name}" has breached the RED threshold.',
                link=url_for('risk_management.kris_dashboard'), n_type='kri_breach',
            )
        flash(f'Measurement recorded ({status}).', 'success')
        return redirect(url_for('risk_management.kris_dashboard'))
    return render_template('risk_management/kri_measurement_form.html', kri=kri)


# ---------------------------------------------------------------------------
# Risk treatments
# ---------------------------------------------------------------------------

@risk_bp.route('/treatments')
@login_required
@permission_required('risk_management')
def treatments_list():
    from datetime import date
    mine = request.args.get('mine')
    all_risks = Risk.get_all()
    treatments = RiskTreatment.get_for_owner(current_user.id) if mine else \
        [t for r in all_risks for t in RiskTreatment.get_for_risk(r.id)]
    risks_by_id = {r.id: r for r in all_risks}
    owners_by_id = {u.id: u for u in User.get_all()}
    return render_template(
        'risk_management/treatments_list.html', treatments=treatments, mine=bool(mine),
        risks_by_id=risks_by_id, owners_by_id=owners_by_id, today=date.today(),
    )


@risk_bp.route('/register/<int:risk_pk>/treatments/new', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def treatment_new(risk_pk):
    risk = Risk.get_by_id(risk_pk)
    if not risk:
        flash(_('Risk not found.'), 'danger')
        return redirect(url_for("risk_management.register_list"))
    if request.method == 'POST':
        treatment = RiskTreatment.create(
            risk_id=risk_pk, treatment_description=request.form.get('treatment_description'),
            treatment_owner_id=request.form.get('treatment_owner_id', type=int),
            target_date=request.form.get('target_date'),
            treatment_type=request.form.get('treatment_type'),
            estimated_cost=request.form.get('estimated_cost', type=float) or None,
            created_by=current_user.id,
        )
        Notification.create(
            user_id=treatment.treatment_owner_id, title=f'Risk treatment assigned: {risk.risk_title}',
            message=f'You have been assigned a treatment for risk {risk.risk_id}.',
            link=url_for('risk_management.register_detail', risk_pk=risk_pk), n_type='treatment_assigned',
        )
        AuditLog.log(current_user.id, 'Propose Risk Treatment', 'Risk Management', treatment.id,
                     f'Treatment proposed for risk {risk.risk_id}', request.remote_addr)
        flash('Treatment proposed.', 'success')
        return redirect(url_for('risk_management.register_detail', risk_pk=risk_pk))
    return render_template('risk_management/treatment_form.html', risk=risk, users=User.get_all())


@risk_bp.route('/treatments/<int:treatment_id>', methods=['GET', 'POST'])
@login_required
@permission_required('risk_management', level='edit')
def treatment_detail(treatment_id):
    treatment = RiskTreatment.get_by_id(treatment_id)
    if not treatment:
        flash('Treatment not found.', 'danger')
        return redirect(url_for('risk_management.register_list'))
    if request.method == 'POST':
        evidence_path = _save_evidence(request.files.get('evidence_file'), 'treatments', treatment_id)
        RiskTreatment.update_status(
            treatment_id, status=request.form.get('status'),
            completion_date=request.form.get('completion_date') or None,
        )
        if evidence_path:
            from database.db import get_db
            get_db().execute('UPDATE risk_treatments SET evidence_file = %s WHERE id = %s',
                              (evidence_path, treatment_id))
            get_db().commit()
        AuditLog.log(current_user.id, 'Update Risk Treatment', 'Risk Management', treatment_id,
                     f'Status changed to {request.form.get("status")}', request.remote_addr)
        flash('Treatment updated.', 'success')
        return redirect(url_for('risk_management.treatment_detail', treatment_id=treatment_id))
    risk = Risk.get_by_id(treatment.risk_id)
    owner = User.get_by_id(treatment.treatment_owner_id) if treatment.treatment_owner_id else None
    verifier = User.get_by_id(treatment.verified_by) if treatment.verified_by else None
    return render_template(
        'risk_management/treatment_detail.html', treatment=treatment, risk=risk,
        owner=owner, verifier=verifier,
    )


@risk_bp.route('/treatments/<int:treatment_id>/evidence')
@login_required
@permission_required('risk_management', level='view')
def treatment_evidence(treatment_id):
    """Serve a risk treatment's evidence file — same module guard as viewing the treatment."""
    treatment = RiskTreatment.get_by_id(treatment_id)
    if not treatment or not treatment.evidence_file:
        flash('File not found.', 'danger')
        return redirect(url_for('risk_management.treatment_detail', treatment_id=treatment_id))
    return serve_uploaded_file(treatment.evidence_file)


@risk_bp.route('/treatments/<int:treatment_id>/verify', methods=['POST'])
@login_required
@permission_required('risk_management', level='edit')
def treatment_verify(treatment_id):
    try:
        RiskTreatment.verify_and_close(treatment_id, verified_by=current_user.id,
                                       verification_notes=request.form.get('verification_notes'))
        AuditLog.log(current_user.id, 'Verify Risk Treatment', 'Risk Management', treatment_id,
                     'Treatment independently verified and closed', request.remote_addr)
        flash('Treatment verified and closed.', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    return redirect(url_for('risk_management.treatment_detail', treatment_id=treatment_id))
