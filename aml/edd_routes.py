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

"""Routes: customer EDD record, customer activation gate, corporate KYB page,
and the configurable high-risk country list."""

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from attachments.service import list_attachments
from database.db import get_db
from models.audit import AuditLog
from utils.decorators import permission_required
from utils.kyc_labels import tr
from . import aml_bp, edd, edd_logic as L


def _customer(cid):
    r = get_db().execute("SELECT * FROM customers WHERE id = %s", (cid,)).fetchone()
    return dict(r) if r else None


def _flash_error(e):
    msgs = e.args[0] if e.args else ''
    for m in (msgs if isinstance(msgs, list) else [msgs]):
        flash(tr(m), 'danger')


@aml_bp.route('/customers/<int:id>/edd', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def customer_edd(id):
    c = _customer(id)
    if not c:
        flash(tr('Customer not found.'), 'danger')
        return redirect(url_for('aml.customer_list'))
    here = url_for('aml.customer_edd', id=id)
    case = edd.latest_case(id)

    if request.method == 'POST':
        action = request.form.get('action', '')
        cname = c.get('company_name') or c.get('full_name')
        try:
            if action == 'start':
                if not current_user.can_edit('aml'):
                    raise edd.EddError('You do not have permission to prepare EDD.')
                if case and L.edd_status(case) != L.EDD_APPROVED:
                    raise edd.EddError('An EDD record is already in progress for this customer.')
                case = edd.new_review(id, current_user.id) if case else \
                    edd.open_case(id, edd.forced_reasons(c), current_user.id)
                msg = 'EDD record opened.'
            else:
                if not case or str(case['id']) != request.form.get('case_id'):
                    raise edd.EddError('The EDD record changed; reload the page.')
                if action in ('save', 'submit'):
                    if not current_user.can_edit('aml'):
                        raise edd.EddError('You do not have permission to prepare EDD.')
                    edd.save_case(case, request.form, current_user.id)
                    msg = 'EDD saved.'
                    if action == 'submit':
                        edd.submit(edd.get_case(case['id']), current_user.id)
                        msg = 'EDD submitted for approval.'
                elif action == 'approve':
                    edd.approve(case, current_user, request.form.get('notes'))
                    msg = 'EDD approved.'
                elif action == 'return':
                    edd.return_case(case, current_user, request.form.get('notes'))
                    msg = 'EDD returned to the preparer.'
                else:
                    raise edd.EddError('Unknown action.')
        except edd.EddError as e:
            _flash_error(e)
            return redirect(here)
        AuditLog.log(current_user.id, 'EDD', 'AML', id, f'{msg} for customer {c.get("customer_reference")} ({cname})',
                     request.remote_addr)
        flash(tr(msg), 'success')
        return redirect(here)

    ev = edd.evidence_count(case['id']) if case else 0
    reasons = edd.forced_reasons(c)
    return render_template(
        'aml/customer_edd.html', customer=c, case=case, status=L.edd_status(case),
        display=L.display_status(c.get('requires_edd'), case),
        checklist=L.checklist(case, ev) if case else [], evidence_count=ev, reasons=reasons,
        history=edd.history(case['id']) if case else [],
        preparer=edd.user_name(case.get('prepared_by')) if case else None,
        approver=edd.user_name(case.get('approved_by')) if case else None,
        can_prepare=current_user.can_edit('aml') and (not case or L.can_edit(case)),
        can_decide=bool(case) and L.edd_status(case) == L.EDD_SUBMITTED
        and L.approver_role_ok(current_user.role, current_user.can_view('aml'))
        and not L.four_eyes_error(current_user.id, case.get('prepared_by')),
        is_preparer=bool(case) and case.get('prepared_by') == current_user.id,
        frequencies=L.MONITORING_FREQUENCIES,
        attach_module='aml', attach_record_type=edd.ATTACH_TYPE, attach_record_id=case['id'] if case else 0,
        attach_items=list_attachments('aml', edd.ATTACH_TYPE, case['id']) if case else [],
        attach_can_edit=current_user.can_edit('aml') and bool(case) and L.can_edit(case))


@aml_bp.route('/customers/<int:id>/activate', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def activate_customer(id):
    c = _customer(id)
    if not c:
        flash(tr('Customer not found.'), 'danger')
        return redirect(url_for('aml.customer_list'))
    try:
        old = edd.activate(id, current_user, request.form.get('note'))
    except edd.EddError as e:
        _flash_error(e)
        return redirect(url_for('aml.view_customer', id=id))
    AuditLog.log(current_user.id, 'Customer Activated', 'AML', id,
                 f'Customer {c.get("customer_reference")} status {old} -> ACTIVE', request.remote_addr)
    flash(tr('Customer approved and activated.'), 'success')
    return redirect(url_for('aml.view_customer', id=id))


@aml_bp.route('/customers/<int:id>/kyb', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def customer_kyb(id):
    from kyb import views
    c = _customer(id)
    if not c or (c.get('customer_type') or '').upper() not in ('CORPORATE', 'ENTITY'):
        flash(tr('Corporate KYB applies to corporate customers only.'), 'warning')
        return redirect(url_for('aml.view_customer', id=id) if c else url_for('aml.customer_list'))
    return views.handle('aml_customer', id, self_endpoint='aml.customer_kyb',
                        back_url=url_for('aml.view_customer', id=id), can_edit=current_user.can_edit('aml'),
                        title_prefix=c.get('company_name') or c.get('full_name') or tr('Customer'),
                        after_change=lambda cid: edd.reassess(cid, current_user.id))


HR_MSG_AR = {
    'Enter the ISO country code: 2 or 3 letters (e.g. YE or YEM).': 'أدخل رمز الدولة (ISO): حرفان أو ثلاثة (مثل YE أو YEM).',
    'Enter the country name in English.': 'أدخل اسم الدولة بالإنجليزية.',
    'Choose the category.': 'اختر التصنيف.',
    'Enter the source (e.g. FATF public statement, October 2026, or the internal decision).':
        'أدخل المصدر (مثل بيان مجموعة العمل المالي، أكتوبر 2026، أو القرار الداخلي).',
    'The date must be a valid date (YYYY-MM-DD).': 'التاريخ يجب أن يكون تاريخاً صحيحاً (YYYY-MM-DD).',
    'Give the reason for the change (at least 5 characters).': 'اذكر سبب التعديل (5 أحرف على الأقل).',
    'Country not found.': 'الدولة غير موجودة.',
    'This country is already on the list: edit or reactivate it instead.': 'الدولة موجودة بالفعل في القائمة: عدّلها أو أعد تفعيلها.',
    'Another row already has this code or name.': 'يوجد صف آخر بنفس الرمز أو الاسم.',
}


def _hr_ar():
    from flask_babel import get_locale
    return str(get_locale()) == 'ar'


@aml_bp.route('/high-risk-countries', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def high_risk_countries():
    """The high-risk countries list (FATF black / grey lists, internal and other lists):
    view for AML users; add / edit / deactivate / delete for the MLRO only, with a reason, audited."""
    from . import high_risk_countries as HR
    from . import str_register as SR
    db = get_db()
    ar = _hr_ar()
    can_edit = SR.is_mlro(current_user)
    here = url_for('aml.high_risk_countries')

    def L(en, a):
        return a if ar else en

    if request.method == 'POST':
        if not can_edit:
            flash(L('Only the MLRO (compliance manager) changes the high-risk country list.',
                    'مسؤول الإبلاغ (مدير الامتثال) فقط يعدّل قائمة الدول عالية المخاطر.'), 'danger')
            return redirect(here)
        action = request.form.get('action')
        rid = request.form.get('id', type=int)
        try:
            if action == 'add':
                HR.add(request.form, current_user.id, db)
            elif action == 'update' and rid:
                HR.update(rid, request.form, current_user.id, db)
            elif action in ('activate', 'deactivate') and rid:
                HR.set_active(rid, action == 'activate', request.form, current_user.id, db)
            elif action == 'delete' and rid:
                HR.delete(rid, request.form, current_user.id, db)
            elif action == 'reassess':
                n = 0
                for r in db.execute("SELECT id FROM customers WHERE COALESCE(status, '') NOT IN ('CLOSED')").fetchall():
                    edd.reassess(r['id'], current_user.id, db=db)
                    n += 1
                db.commit()
                AuditLog.log(current_user.id, 'High-risk Countries', 'AML', None,
                             f're-assessed {n} customers against the list', request.remote_addr)
                flash(L(f'{n} customers re-assessed against the list.', f'تمت إعادة تقييم {n} عميل مقابل القائمة.'), 'info')
                return redirect(here)
            else:
                raise HR.CountryError('Country not found.')
        except HR.CountryError as e:
            msg = str(e)
            flash(HR_MSG_AR.get(msg, msg) if ar else msg, 'danger')
            if action == 'update' and rid:
                return redirect(url_for('aml.high_risk_countries', edit=rid))
            return redirect(here)
        flash(L('High-risk country list updated. Customer ratings change when customers are re-assessed (button '
                'above) or next edited; monitoring uses the new list on its next run.',
                'تم تحديث قائمة الدول عالية المخاطر. تتغير تصنيفات العملاء عند إعادة تقييمهم (الزر أعلاه) أو عند تعديلهم؛ '
                'والمراقبة تستخدم القائمة الجديدة في تشغيلها التالي.'), 'success')
        return redirect(here)

    edit_row = None
    if request.args.get('edit', type=int):
        try:
            edit_row = HR.get(request.args.get('edit', type=int), db)
        except HR.CountryError:
            edit_row = None
    return render_template('aml/high_risk_countries.html', ar=ar, rows=HR.rows(db), can_edit=can_edit,
                           edit_row=edit_row, categories=HR.CATEGORIES, cat_label=HR.category_label,
                           impact=HR.IMPACT, not_used=HR.NOT_USED, status=HR.impact_status(db),
                           today=datetime.now().strftime('%Y-%m-%d'))
