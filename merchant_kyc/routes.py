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

from flask_babel import gettext
from flask import render_template, redirect, url_for, flash, request, Response, current_app, send_from_directory
from flask_login import login_required, current_user
from utils.decorators import permission_required
from database.db import get_db
from datetime import datetime
from extensions import csrf, limiter
from werkzeug.utils import secure_filename
from . import merchant_kyc_bp
from . import workflow as wf
from models.audit import AuditLog
from utils.kyc_labels import tr
import uuid
import csv
import io
import os


UPLOAD_FOLDER = 'uploads/merchant_kyc'
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx'}


def _val(v):
    """Convert empty strings to None to avoid CHECK constraint violations."""
    return v if v else None


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _sync_party_registry(merchant_id):
    try:
        from parties.linker import upsert_party_for_merchant
        upsert_party_for_merchant(merchant_id)
    except Exception:
        current_app.logger.exception('Failed to sync party registry for merchant %s', merchant_id)


def _save_documents(merchant_id, files, doc_types, uploaded_by='public'):
    """Save uploaded documents for a merchant."""
    db = get_db()
    upload_path = os.path.join(current_app.root_path, UPLOAD_FOLDER)
    os.makedirs(upload_path, exist_ok=True)
    
    for i, f in enumerate(files):
        if f and f.filename and _allowed_file(f.filename):
            original_name = secure_filename(f.filename)
            stored_name = f"{merchant_id}_{uuid.uuid4().hex[:8]}_{original_name}"
            f.save(os.path.join(upload_path, stored_name))
            
            doc_type = doc_types[i] if i < len(doc_types) else 'Other'
            file_size = os.path.getsize(os.path.join(upload_path, stored_name))
            
            db.execute('''
                INSERT INTO merchant_kyc_documents 
                (merchant_id, doc_type, original_filename, stored_filename, file_size, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (merchant_id, doc_type, original_name, stored_name, file_size, uploaded_by))
    db.commit()


def _get_documents(merchant_id):
    """Get all documents for a merchant."""
    db = get_db()
    return db.execute(
        'SELECT * FROM merchant_kyc_documents WHERE merchant_id = %s ORDER BY uploaded_at DESC',
        (merchant_id,)
    ).fetchall()


@merchant_kyc_bp.route('/')
@login_required
@permission_required('aml')
@permission_required('merchant_kyc', level='view')
def merchant_list():
    """List all merchants with KYC status."""
    db = get_db()
    merchants = db.execute('''
        SELECT * FROM merchants ORDER BY created_at DESC
    ''').fetchall()
    return render_template('merchant_kyc/list.html', merchants=merchants)


@merchant_kyc_bp.route('/new', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
@permission_required('merchant_kyc', level='view')
def create_merchant():
    """Create a new merchant KYC record."""
    if request.method == 'POST':
        db = get_db()
        kyc_token = str(uuid.uuid4())
        
        db.execute('''
            INSERT INTO merchants (
                merchant_name, trade_name, cr_number, tax_id, business_type, industry, website,
                contact_person, contact_email, contact_phone, address, city, country,
                ubo_name, ubo_nationality, ubo_id_type, ubo_id_number, ubo_dob, ownership_percentage,
                bank_name, bank_account_number, iban,
                kyc_status, kyc_token, risk_level,
                created_by, updated_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            _val(request.form.get('merchant_name')),
            _val(request.form.get('trade_name')),
            _val(request.form.get('cr_number')),
            _val(request.form.get('tax_id')),
            _val(request.form.get('business_type')),
            _val(request.form.get('industry')),
            _val(request.form.get('website')),
            _val(request.form.get('contact_person')),
            _val(request.form.get('contact_email')),
            _val(request.form.get('contact_phone')),
            _val(request.form.get('address')),
            _val(request.form.get('city')),
            _val(request.form.get('country')) or 'Egypt',
            _val(request.form.get('ubo_name')),
            _val(request.form.get('ubo_nationality')),
            _val(request.form.get('ubo_id_type')),
            _val(request.form.get('ubo_id_number')),
            _val(request.form.get('ubo_dob')),
            _val(request.form.get('ownership_percentage')),
            _val(request.form.get('bank_name')),
            _val(request.form.get('bank_account_number')),
            _val(request.form.get('iban')),
            'PENDING', kyc_token, 'MEDIUM',
            current_user.id, current_user.id
        ))
        db.commit()

        # Handle file uploads
        merchant_id = db.execute('SELECT LASTVAL() as lastid').fetchone()['lastid']
        files = request.files.getlist('documents')
        doc_types = request.form.getlist('doc_types')
        if files:
            _save_documents(merchant_id, files, doc_types, uploaded_by=current_user.email)

        wf.record(db, merchant_id, None, 'PENDING', 'created', current_user.id)
        db.commit()
        if (request.form.get('ubo_name') or '').strip():
            # the principal owner entered on the form becomes the first of the
            # merchant's beneficial owners, screened on save
            from kyb import service as kyb
            try:
                kyb.save_person('ubo', 'merchant', merchant_id, {
                    'full_name': request.form.get('ubo_name'), 'nationality': request.form.get('ubo_nationality'),
                    'id_type': request.form.get('ubo_id_type'), 'id_number': request.form.get('ubo_id_number'),
                    'date_of_birth': request.form.get('ubo_dob'),
                    'ownership_pct': request.form.get('ownership_percentage'), 'control_type': 'ownership'},
                    current_user.id)
            except kyb.KybError as e:
                for m in e.messages:
                    flash(tr(m), 'warning')
        _sync_party_registry(merchant_id)

        flash(gettext('Merchant KYC record created successfully.'), 'success')
        flash(tr('Complete the KYB file (entity details, all beneficial owners and authorised signatories) before submitting for approval.'), 'info')
        return redirect(url_for('merchant_kyc.merchant_kyb', id=merchant_id))
    
    return render_template('merchant_kyc/form.html')


@merchant_kyc_bp.route('/<int:id>')
@login_required
@permission_required('aml')
@permission_required('merchant_kyc', level='view')
def view_merchant(id):
    """View merchant KYC details (printable)."""
    db = get_db()
    merchant = db.execute('SELECT * FROM merchants WHERE id = %s', (id,)).fetchone()
    if not merchant:
        flash(gettext('Merchant not found.'), 'danger')
        return redirect(url_for('merchant_kyc.merchant_list'))
    documents = _get_documents(id)
    from kyb import service as kyb
    ubos, sigs, _states = kyb.with_states('merchant', id)
    m = dict(merchant)
    decision_block = wf.four_eyes_error(current_user.id, m.get('created_by'), m.get('submitted_by'))
    names = {k: _user_name(db, m.get(k)) for k in ('created_by', 'submitted_by', 'kyc_reviewed_by')}
    return render_template('merchant_kyc/view.html', merchant=merchant, documents=documents,
                           ubos=ubos, signatories=sigs, kyb_blockers=kyb.blockers('merchant', id),
                           history=wf.history(db, id), names=names, decision_block=decision_block,
                           can_submit=(m.get('kyc_status') or 'PENDING') in wf.SUBMITTABLE,
                           can_decide=(m.get('kyc_status') or '') in wf.DECIDABLE)


def _user_name(db, uid):
    if not uid:
        return None
    r = db.execute('SELECT first_name, last_name, email FROM users WHERE id = %s', (uid,)).fetchone()
    return ((f"{r['first_name'] or ''} {r['last_name'] or ''}".strip()) or r['email']) if r else None


@merchant_kyc_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
@permission_required('merchant_kyc', level='edit')
def edit_merchant(id):
    """Edit merchant KYC record."""
    db = get_db()
    merchant = db.execute('SELECT * FROM merchants WHERE id = %s', (id,)).fetchone()
    if not merchant:
        flash(gettext('Merchant not found.'), 'danger')
        return redirect(url_for('merchant_kyc.merchant_list'))
    
    if request.method == 'POST':
        old_status = merchant['kyc_status'] or 'PENDING'
        new_status = wf.edit_status(old_status, request.form.get('kyc_status'))
        if (request.form.get('kyc_status') or '').upper() in wf.FINAL and new_status != request.form.get('kyc_status'):
            flash(tr('Approval and rejection are recorded with the Approve / Reject actions on the merchant page.'), 'warning')
        submitting = new_status in wf.DECIDABLE and old_status not in wf.DECIDABLE
        db.execute('''
            UPDATE merchants SET
                merchant_name = %s, trade_name = %s, cr_number = %s, tax_id = %s,
                business_type = %s, industry = %s, website = %s,
                contact_person = %s, contact_email = %s, contact_phone = %s,
                address = %s, city = %s, country = %s,
                bank_name = %s, bank_account_number = %s, iban = %s,
                kyc_status = %s, risk_level = %s, risk_notes = %s,
                submitted_by = CASE WHEN %s THEN %s ELSE submitted_by END,
                submitted_at = CASE WHEN %s THEN to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS') ELSE submitted_at END,
                updated_at = CURRENT_TIMESTAMP, updated_by = %s
            WHERE id = %s
        ''', (
            _val(request.form.get('merchant_name')),
            _val(request.form.get('trade_name')),
            _val(request.form.get('cr_number')),
            _val(request.form.get('tax_id')),
            _val(request.form.get('business_type')),
            _val(request.form.get('industry')),
            _val(request.form.get('website')),
            _val(request.form.get('contact_person')),
            _val(request.form.get('contact_email')),
            _val(request.form.get('contact_phone')),
            _val(request.form.get('address')),
            _val(request.form.get('city')),
            _val(request.form.get('country')),
            _val(request.form.get('bank_name')),
            _val(request.form.get('bank_account_number')),
            _val(request.form.get('iban')),
            new_status,
            _val(request.form.get('risk_level')),
            _val(request.form.get('risk_notes')),
            submitting, current_user.id, submitting,
            current_user.id,
            id
        ))
        if new_status != old_status:
            wf.record(db, id, old_status, new_status, 'submitted' if submitting else 'status_changed',
                      current_user.id)
        db.commit()

        # Handle file uploads
        files = request.files.getlist('documents')
        doc_types = request.form.getlist('doc_types')
        if files:
            _save_documents(id, files, doc_types, uploaded_by=current_user.email)

        _sync_party_registry(id)

        flash(gettext('Merchant KYC updated successfully.'), 'success')
        return redirect(url_for('merchant_kyc.view_merchant', id=id))
    
    documents = _get_documents(id)
    return render_template('merchant_kyc/form.html', merchant=merchant, documents=documents)


@merchant_kyc_bp.route('/<int:id>/send-kyc', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
@permission_required('merchant_kyc', level='edit')
def send_kyc_link(id):
    """Generate and mark KYC link as sent to merchant."""
    db = get_db()
    merchant = db.execute('SELECT * FROM merchants WHERE id = %s', (id,)).fetchone()
    if not merchant:
        flash(gettext('Merchant not found.'), 'danger')
        return redirect(url_for('merchant_kyc.merchant_list'))
    
    token = merchant['kyc_token']
    if not token:
        token = str(uuid.uuid4())
    
    # Only change status to SENT if currently PENDING; otherwise keep current status
    new_status = 'SENT' if merchant['kyc_status'] == 'PENDING' else merchant['kyc_status']
    
    db.execute('''
        UPDATE merchants SET kyc_status = %s, kyc_token = %s, kyc_sent_at = CURRENT_TIMESTAMP,
        updated_at = CURRENT_TIMESTAMP, updated_by = %s
        WHERE id = %s
    ''', (new_status, token, current_user.id, id))
    if new_status != merchant['kyc_status']:
        wf.record(db, id, merchant['kyc_status'], new_status, 'link_sent', current_user.id)
    db.commit()
    
    # Build the public link
    public_url = url_for('merchant_kyc.public_kyc_form', token=token, _external=True)

    # Build WhatsApp message
    merchant_name = merchant['merchant_name'] or 'Merchant'
    phone = str(merchant['contact_phone'] or '').strip()
    # Normalize Egyptian number to international format
    if phone.startswith('0'):
        phone = '20' + phone[1:]
    elif phone.startswith('+'):
        phone = phone[1:]

    wa_message = (
        "عزيزنا " + merchant_name + "،\n\n"
        "تحية طيبة،\n\n"
        "تطلب منك شركة ComplyNex استكمال / تحديث بيانات KYB (معرفة عملك) للحفاظ على خدمة POS الخاصة بك.\n\n"
        "يرجى الضغط على الرابط أدناه وتعبئة بياناتك." "لن يستغرق ذلك أكثر من 5 دقائق:\n\n"
        + public_url + "\n\n"
        "هذا الرابط خاص بحسابك فقط، لا تشاركه مع أحد.\n\n"
        "للدعم: تواصل مع مندوب ComplyNex الخاص بك."
    )


    import urllib.parse
    wa_url = f"https://wa.me/{phone}?text={urllib.parse.quote(wa_message)}" if phone else None

    # Update sent_via
    db.execute("UPDATE merchants SET kyb_link_sent_via='whatsapp', updated_at=CURRENT_TIMESTAMP WHERE id=%s", (id,))
    db.commit()

    flash(gettext('KYB link generated successfully.'), 'success')
    return render_template('merchant_kyc/send_kyc.html',
        merchant=merchant,
        public_url=public_url,
        wa_url=wa_url,
        phone=phone,
        wa_message=wa_message)


@merchant_kyc_bp.route('/<int:id>/submit', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
@permission_required('merchant_kyc', level='edit')
def submit_merchant(id):
    """Send a merchant whose KYB file is ready for a four-eyes decision."""
    db = get_db()
    merchant = db.execute('SELECT * FROM merchants WHERE id = %s', (id,)).fetchone()
    if not merchant:
        flash(gettext('Merchant not found.'), 'danger')
        return redirect(url_for('merchant_kyc.merchant_list'))
    old = merchant['kyc_status'] or 'PENDING'
    if old not in wf.SUBMITTABLE:
        flash(tr('Only a pending merchant can be submitted for approval.'), 'warning')
        return redirect(url_for('merchant_kyc.view_merchant', id=id))
    db.execute("""UPDATE merchants SET kyc_status = 'SUBMITTED', submitted_by = %s,
                  submitted_at = to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
                  kyc_submitted_at = COALESCE(kyc_submitted_at, to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')),
                  updated_at = CURRENT_TIMESTAMP, updated_by = %s WHERE id = %s""", (current_user.id, current_user.id, id))
    wf.record(db, id, old, 'SUBMITTED', 'submitted', current_user.id, (request.form.get('note') or '').strip() or None)
    db.commit()
    AuditLog.log(current_user.id, 'Merchant Submitted', 'Merchant KYC', id,
                 f'Merchant {merchant["merchant_name"]} submitted for approval', request.remote_addr)
    flash(tr('Submitted for approval. Another person must approve or reject it.'), 'success')
    return redirect(url_for('merchant_kyc.view_merchant', id=id))


@merchant_kyc_bp.route('/<int:id>/approve', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
@permission_required('merchant_kyc', level='edit')
def approve_merchant(id):
    """Approve merchant KYC: four-eyes, complete KYB file, no open screening hit."""
    db = get_db()
    row = db.execute('SELECT * FROM merchants WHERE id = %s', (id,)).fetchone()
    if not row:
        flash(gettext('Merchant not found.'), 'danger')
        return redirect(url_for('merchant_kyc.merchant_list'))
    merchant = dict(row)
    err = wf.decision_error(merchant, current_user.id, 'approve')
    from kyb import service as kyb
    blockers = [] if err else kyb.blockers('merchant', id)
    if err or blockers:
        for m in ([err] if err else blockers):
            flash(tr(m), 'danger')
        return redirect(url_for('merchant_kyc.view_merchant', id=id))
    note = (request.form.get('note') or '').strip() or None
    db.execute('''
        UPDATE merchants SET kyc_status = 'APPROVED', kyc_reviewed_by = %s, kyc_reviewed_at = CURRENT_TIMESTAMP,
        onboarding_status = 'Active', updated_at = CURRENT_TIMESTAMP, updated_by = %s
        WHERE id = %s
    ''', (current_user.id, current_user.id, id))
    wf.record(db, id, merchant['kyc_status'], 'APPROVED', 'approved', current_user.id, note)
    db.commit()
    AuditLog.log(current_user.id, 'Merchant Approved', 'Merchant KYC', id,
                 f'Merchant {merchant["merchant_name"]} approved', request.remote_addr)
    flash(gettext('Merchant KYC approved.'), 'success')
    return redirect(url_for('merchant_kyc.view_merchant', id=id))


@merchant_kyc_bp.route('/<int:id>/reject', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
@permission_required('merchant_kyc', level='edit')
def reject_merchant(id):
    """Reject merchant KYC: a written reason is required; four-eyes applies."""
    db = get_db()
    row = db.execute('SELECT * FROM merchants WHERE id = %s', (id,)).fetchone()
    if not row:
        flash(gettext('Merchant not found.'), 'danger')
        return redirect(url_for('merchant_kyc.merchant_list'))
    merchant = dict(row)
    reason = (request.form.get('rejection_reason') or '').strip()
    err = wf.decision_error(merchant, current_user.id, 'reject', reason)
    if err:
        flash(tr(err), 'danger')
        return redirect(url_for('merchant_kyc.view_merchant', id=id))
    db.execute('''
        UPDATE merchants SET kyc_status = 'REJECTED', kyc_reviewed_by = %s, kyc_reviewed_at = CURRENT_TIMESTAMP,
        kyc_rejection_reason = %s, onboarding_status = 'Rejected', updated_at = CURRENT_TIMESTAMP, updated_by = %s
        WHERE id = %s
    ''', (current_user.id, reason, current_user.id, id))
    wf.record(db, id, merchant['kyc_status'], 'REJECTED', 'rejected', current_user.id, reason)
    db.commit()
    AuditLog.log(current_user.id, 'Merchant Rejected', 'Merchant KYC', id,
                 f'Merchant {merchant["merchant_name"]} rejected: {reason}', request.remote_addr)
    flash(gettext('Merchant KYC rejected.'), 'warning')
    return redirect(url_for('merchant_kyc.view_merchant', id=id))


@merchant_kyc_bp.route('/<int:id>/kyb', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
@permission_required('merchant_kyc', level='view')
def merchant_kyb(id):
    """Corporate KYB file: entity details, beneficial owners, signatories."""
    from kyb import views
    m = get_db().execute('SELECT merchant_name, kyc_status FROM merchants WHERE id = %s', (id,)).fetchone()
    if not m:
        flash(gettext('Merchant not found.'), 'danger')
        return redirect(url_for('merchant_kyc.merchant_list'))
    can_edit = (current_user.can_edit('aml') and current_user.can_edit('merchant_kyc')
                and (m['kyc_status'] or '') not in wf.FINAL)
    return views.handle('merchant', id, self_endpoint='merchant_kyc.merchant_kyb',
                        back_url=url_for('merchant_kyc.view_merchant', id=id), can_edit=can_edit,
                        title_prefix=m['merchant_name'] or tr('Merchant'),
                        after_change=lambda mid: _sync_party_registry(mid))


def _public_ubo_to_register(merchant_id, form):
    """The merchant's self-declared owner joins the beneficial-owner list
    (unscreened: an officer screens it before approval)."""
    name = (form.get('ubo_name') or '').strip()
    if not name or name.lower() in ('none', 'null'):
        return
    db = get_db()
    if db.execute("SELECT 1 FROM kyc_beneficial_owners WHERE subject = 'merchant' AND subject_id = %s "
                  "AND lower(trim(full_name)) = lower(%s)", (merchant_id, name)).fetchone():
        return
    from kyb import service as kyb
    try:
        kyb.save_person('ubo', 'merchant', merchant_id, {
            'full_name': name, 'nationality': form.get('ubo_nationality'), 'id_type': form.get('ubo_id_type'),
            'id_number': form.get('ubo_id_number'), 'date_of_birth': form.get('ubo_dob'),
            'ownership_pct': form.get('ownership_percentage'), 'control_type': 'ownership'},
            None, screen=False)
    except kyb.KybError:
        current_app.logger.info('Public KYB owner for merchant %s not added to the register (invalid data)', merchant_id)


# ======== PUBLIC ROUTE (No Login Required) ========
@merchant_kyc_bp.route('/public/<token>', methods=['GET', 'POST'])
@csrf.exempt
@limiter.limit('20 per minute')
def public_kyc_form(token):
    """Public KYC self-service form for merchants (no login required)."""
    db = get_db()
    merchant = db.execute('SELECT * FROM merchants WHERE kyc_token = %s', (token,)).fetchone()
    
    if not merchant:
        return render_template('merchant_kyc/public_form.html', error='Invalid or expired KYC link.'), 404
    
    if merchant['kyc_status'] in ('APPROVED', 'REJECTED'):
        return render_template('merchant_kyc/public_form.html', 
                             error='This KYC form has already been processed.', merchant=merchant), 403
    
    if request.method == 'POST':
        # Capture GPS location from form
        gps_lat = _val(request.form.get('gps_latitude'))
        gps_lng = _val(request.form.get('gps_longitude'))
        gps_acc = _val(request.form.get('gps_accuracy'))
        gps_addr = _val(request.form.get('gps_address'))

        db.execute('''
            UPDATE merchants SET
                merchant_name = %s, trade_name = %s, cr_number = %s, tax_id = %s,
                business_type = %s, industry = %s, website = %s,
                contact_person = %s, contact_email = %s, contact_phone = %s,
                address = %s, city = %s, country = %s,
                ubo_name = %s, ubo_nationality = %s, ubo_id_type = %s, ubo_id_number = %s,
                ubo_dob = %s, ownership_percentage = %s,
                bank_name = %s, bank_account_number = %s, iban = %s,
                gps_latitude = %s, gps_longitude = %s, gps_accuracy = %s,
                gps_address = %s, gps_captured_at = CURRENT_TIMESTAMP,
                kyc_status = 'SUBMITTED', kyc_submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE kyc_token = %s
        ''', (
            _val(request.form.get('merchant_name')),
            _val(request.form.get('trade_name')),
            _val(request.form.get('cr_number')),
            _val(request.form.get('tax_id')),
            _val(request.form.get('business_type')),
            _val(request.form.get('industry')),
            _val(request.form.get('website')),
            _val(request.form.get('contact_person')),
            _val(request.form.get('contact_email')),
            _val(request.form.get('contact_phone')),
            _val(request.form.get('address')),
            _val(request.form.get('city')),
            _val(request.form.get('country')) or 'Egypt',
            _val(request.form.get('ubo_name')),
            _val(request.form.get('ubo_nationality')),
            _val(request.form.get('ubo_id_type')),
            _val(request.form.get('ubo_id_number')),
            _val(request.form.get('ubo_dob')),
            _val(request.form.get('ownership_percentage')),
            _val(request.form.get('bank_name')),
            _val(request.form.get('bank_account_number')),
            _val(request.form.get('iban')),
            gps_lat, gps_lng, gps_acc, gps_addr,
            token
        ))
        db.commit()
        
        wf.record(db, merchant['id'], merchant['kyc_status'], 'SUBMITTED', 'public_submitted',
                  actor_label='merchant (public link)')
        db.commit()
        _public_ubo_to_register(merchant['id'], request.form)

        # Handle file uploads from public form
        files = request.files.getlist('documents')
        doc_types = request.form.getlist('doc_types')
        if files:
            _save_documents(merchant['id'], files, doc_types, uploaded_by='merchant-public')
        
        return render_template('merchant_kyc/public_form.html', submitted=True, merchant=merchant)
    
    return render_template('merchant_kyc/public_form.html', merchant=merchant, token=token)


@merchant_kyc_bp.route('/export')
@login_required
@permission_required('aml')
@permission_required('merchant_kyc', level='view')
def export_merchants():
    """Export merchants to CSV."""
    db = get_db()
    merchants = db.execute('SELECT * FROM merchants ORDER BY created_at DESC').fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID', 'Merchant Name', 'Trade Name', 'CR Number', 'Tax ID',
        'Business Type', 'Industry', 'Contact Person', 'Contact Email', 'Contact Phone',
        'City', 'Country', 'KYC Status', 'Risk Level', 'Created At'
    ])
    
    for m in merchants:
        d = dict(m)
        writer.writerow([
            d.get('id'), d.get('merchant_name'), d.get('trade_name'), d.get('cr_number'), d.get('tax_id'),
            d.get('business_type'), d.get('industry'), d.get('contact_person'), d.get('contact_email'), d.get('contact_phone'),
            d.get('city'), d.get('country'), d.get('kyc_status'), d.get('risk_level'), d.get('created_at')
        ])
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=merchant_kyc_export.csv"}
    )


@merchant_kyc_bp.route('/document/<int:doc_id>/download')
@login_required
@permission_required('aml')
@permission_required('merchant_kyc', level='view')
def download_document(doc_id):
    """Download a merchant KYC document."""
    db = get_db()
    doc = db.execute('SELECT * FROM merchant_kyc_documents WHERE id = %s', (doc_id,)).fetchone()
    if not doc:
        flash(gettext('Document not found.'), 'danger')
        return redirect(url_for('merchant_kyc.merchant_list'))
    
    upload_path = os.path.join(current_app.root_path, UPLOAD_FOLDER)
    return send_from_directory(upload_path, doc['stored_filename'], 
                               download_name=doc['original_filename'], as_attachment=True)


@merchant_kyc_bp.route('/document/<int:doc_id>/delete', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
@permission_required('merchant_kyc', level='edit')
def delete_document(doc_id):
    """Delete a merchant KYC document."""
    db = get_db()
    doc = db.execute('SELECT * FROM merchant_kyc_documents WHERE id = %s', (doc_id,)).fetchone()
    if not doc:
        flash(gettext('Document not found.'), 'danger')
        return redirect(url_for('merchant_kyc.merchant_list'))
    
    # Remove file from disk
    file_path = os.path.join(current_app.root_path, UPLOAD_FOLDER, doc['stored_filename'])
    if os.path.exists(file_path):
        os.remove(file_path)
    
    db.execute('DELETE FROM merchant_kyc_documents WHERE id = %s', (doc_id,))
    db.commit()
    flash(gettext('Document deleted.'), 'success')
    return redirect(url_for('merchant_kyc.view_merchant', id=doc['merchant_id']))


@merchant_kyc_bp.route('/<int:id>/run-screening', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
@permission_required('merchant_kyc', level='edit')
def run_screening(id):
    """Run sanctions screening for a merchant via the unified screening API."""
    db = get_db()
    row = db.execute('SELECT * FROM merchants WHERE id = %s', (id,)).fetchone()
    if not row:
        flash(gettext('Merchant not found.'), 'danger')
        return redirect(url_for('merchant_kyc.merchant_list'))
    merchant = dict(row)

    import json
    import requests as req_lib

    # Generate internal reference number if not already assigned
    if not merchant.get('internal_reference_number') or merchant['internal_reference_number'] is None:
        year = datetime.now().year
        count_row = db.execute(
            "SELECT COUNT(*) as cnt FROM merchants WHERE internal_reference_number IS NOT NULL"
        ).fetchone()
        seq = (count_row['cnt'] if count_row else 0) + 1
        ref_num = f"MER-{year}-{seq:04d}"
        db.execute("UPDATE merchants SET internal_reference_number = %s WHERE id = %s", (ref_num, id))
        db.commit()

    # Screen the merchant name
    names_to_screen = [merchant['merchant_name']]

    # Also screen UBO name if available. Guard against the literal string
    # "None"/"none"/"null" (not just a real NULL) — a template bug once let
    # empty fields get saved with that literal text, which is truthy and
    # would otherwise get screened as if it were a real name.
    ubo_name = merchant.get('ubo_name') or merchant.get('authorized_signatory_name')
    if ubo_name and str(ubo_name).strip().lower() not in ('none', 'null', ''):
        names_to_screen.append(ubo_name)

    overall_result = 'CLEAR'
    overall_score = 0.0
    total_high_risk = 0
    results_summary = []

    for name in names_to_screen:
        try:
            # Reuse the app's shared, already-loaded screening engine (same
            # one screening/routes.py uses) instead of constructing a fresh
            # ComplyNexScreeningEngine per call — that used to reload the
            # full 4-tier ML ensemble from disk on every screening request,
            # and passed current_app.config['DATABASE'] (a raw Postgres DSN)
            # into a constructor that infers sqlite-vs-postgres from the
            # shape of its db_config argument, mistagging itself as sqlite.
            from screening.routes import get_engine
            engine = get_engine()
            result = engine.screen_person(
                name=name,
                nationality=merchant.get('merchant_country'),
                entity_type='INDIVIDUAL' if name == ubo_name else 'ENTITY'
            )

            matches = result.get('matches', [])
            highest_score = result.get('highest_score', 0.0)
            high_risk = [m for m in matches if m.get('match_score', 0) >= 70.0]

            # Determine status
            if result.get('screening_result') == 'WHITE_LISTED':
                sr = 'WHITE_LISTED'
            elif high_risk:
                sr = 'POTENTIAL_MATCH'
            else:
                sr = 'CLEAR'

            # Save to screening_history
            db.execute("""
                INSERT INTO screening_history
                    (entity_name, entity_type, screening_type, initiated_by,
                     source_module, source_record_id, total_matches_found,
                     high_risk_matches, auto_cleared_matches, highest_score,
                     screening_result, matches_json, status, processing_time_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                name, 'ENTITY' if name != ubo_name else 'INDIVIDUAL',
                'Merchant KYC', current_user.id, 'Merchant KYC', id,
                len(matches), len(high_risk), len(matches) - len(high_risk),
                highest_score, sr,
                json.dumps(matches),
                'Pending Review' if high_risk else 'Completed',
                result.get('processing_time_ms', 0)
            ))

            history_row = db.execute(
                "SELECT id FROM screening_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
            history_id = history_row['id'] if history_row else None

            # Also save to screening_results for backward compat
            db.execute("""
                INSERT INTO screening_results (
                    screening_type, screened_name, screening_method,
                    total_matches_found, highest_match_score,
                    screening_result, matches, adverse_media, processing_time_ms, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                'MERCHANT_KYC', name, 'API',
                len(matches), highest_score, sr,
                json.dumps(matches),
                json.dumps(result.get('adverse_media', [])),
                result.get('processing_time_ms', 0), current_user.id
            ))

            # Create queue items for high-risk matches
            for match in high_risk:
                priority = 'High' if match.get('match_score', 0) >= 90 else 'Medium'
                db.execute("""
                    INSERT INTO screening_queue
                        (screening_history_id, entity_name, entity_type, match_name,
                         match_score, list_source, match_details, priority, status,
                         source_module, source_record_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Pending', %s, %s, CURRENT_TIMESTAMP)
                """, (
                    history_id, name,
                    'ENTITY' if name != ubo_name else 'INDIVIDUAL',
                    match.get('full_name', match.get('watchlist_name_ar', '')),
                    match.get('match_score', 0),
                    match.get('source', match.get('dataset', 'Unknown')),
                    json.dumps(match),
                    priority, 'Merchant KYC', id
                ))

            total_high_risk += len(high_risk)
            if highest_score > overall_score:
                overall_score = highest_score

            if sr == 'POTENTIAL_MATCH' or sr == 'CONFIRMED_HIT':
                overall_result = sr

            results_summary.append({
                'name': name,
                'result': sr,
                'score': highest_score,
                'matches': len(matches),
                'high_risk': len(high_risk)
            })

        except Exception as e:
            flash(f'Screening error for "{name}": {str(e)}', 'danger')
            results_summary.append({'name': name, 'result': 'ERROR', 'error': str(e)})

    # Update merchant screening status
    if overall_result == 'CLEAR' or overall_result == 'WHITE_LISTED':
        screening_status = 'Clear'
        risk_rating = 'Low'
    elif total_high_risk > 0:
        screening_status = 'Pending Review'
        risk_rating = 'High'
    else:
        screening_status = 'Clear'
        risk_rating = 'Medium'

    db.execute("""
        UPDATE merchants
        SET screening_status = %s, last_screening_date = CURRENT_TIMESTAMP,
            last_screened_by = %s, risk_rating = %s, sanctions_checked = 1
        WHERE id = %s
    """, (screening_status, current_user.id, risk_rating, id))
    db.commit()

    if total_high_risk > 0:
        flash(gettext('Screening completed: %(total_high_risk)s high-risk match(es) found! Review required in Screening Queue.', total_high_risk=total_high_risk), 'danger')
        try:
            from events.publisher import publish_event
            publish_event(
                event_type='merchant.screening.hit',
                source_module='Merchant KYC',
                source_table='merchants',
                source_record_id=id,
                entity_type='MERCHANT',
                entity_id=id,
                payload={
                    'entity_name': merchant['merchant_name'],
                    'high_risk_matches': total_high_risk,
                    'highest_score': overall_score,
                },
            )
        except Exception:
            current_app.logger.exception('Failed to publish merchant.screening.hit event for merchant %s', id)
    else:
        flash(gettext('Screening completed: All clear. No sanctions matches found.'), 'success')

    return redirect(url_for('merchant_kyc.view_merchant', id=id))



@merchant_kyc_bp.route('/dashboard')
@login_required
def dashboard():
    return redirect(url_for('merchant_kyc.merchant_list'))
