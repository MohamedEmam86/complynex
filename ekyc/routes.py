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

import base64
import csv
import io
import json
import os

from flask_babel import gettext
from flask import render_template, redirect, url_for, flash, request, jsonify, Response, make_response, current_app
from flask_login import login_required, current_user
from extensions import limiter

from utils.decorators import permission_required
from database.db import query_db
from models.ekyc import EkycSession, EkycDocument, EkycResult, EkycAuditLog
from ekyc.secure_storage import save_frame, read_frame
from ekyc.queue import enqueue_session
from . import ekyc_bp

MAX_FRAMES_PER_ROLE = 20
MAX_SIDE_CHECK_FRAMES = 8
# 'turn_head' (not directional left/right): the displayed selfie preview is
# typically mirrored for a natural selfie UX, but MediaPipe processes the
# raw, unmirrored camera frame — "left" on screen isn't reliably "left" in
# the coordinates we measure. A direction-agnostic "turn to either side"
# challenge avoids that ambiguity entirely while still requiring real head
# motion. See static/ekyc/js/capture.js.
ALLOWED_CHALLENGES = {'blink', 'turn_head', 'smile'}

# Every status the pipeline or an officer can leave a session in once the
# customer's part is done — session expiry no longer applies (matches the
# pre-existing 'COMPLETED' exemption) and the customer-facing /verify route
# shows the generic "thank you, under review" page rather than falling
# through to the capture screen again.
POST_SUBMISSION_STATUSES = ('COMPLETED', 'NEEDS_REVIEW', 'DECISION_PENDING',
                             'APPROVED', 'ONBOARDED', 'REJECTED')

DOCUMENT_TYPES = [
    ('NATIONAL_ID', 'National ID'),
    ('PASSPORT', 'Passport'),
    ('DRIVING_LICENSE', 'Driving License'),
    ('COMMERCIAL_REGISTER', 'Commercial Register'),
    ('TAX_ID', 'Tax ID'),
]

# Only NATIONAL_ID has a calibrated back-side field layout (ekyc/id_layout.py's
# BACK_FIELDS) — capturing a back image for the other types would just OCR
# garbage against the wrong card layout, so the capture UI only asks for one
# for those.
BACK_SIDE_REQUIRED_TYPES = {'NATIONAL_ID'}

CONSENT_TEXT_EN = (
    "I consent to ComplyNex collecting and processing my ID document images, a short selfie "
    "video, and the biometric data derived from them (a numeric face template), solely to "
    "verify my identity for compliance purposes. This data is encrypted at rest, access is "
    "restricted to authorized staff, and it is retained only as long as required by law "
    "before deletion."
)
CONSENT_TEXT_AR = (
    "أوافق على قيام ComplyNex بجمع ومعالجة صور وثيقة هويتي، وفيديو سيلفي قصير، والبيانات "
    "الحيوية المستخلصة منها (نموذج رقمي للوجه)، وذلك فقط لأغراض التحقق من هويتي للالتزام "
    "التنظيمي. يتم تشفير هذه البيانات أثناء التخزين، ويقتصر الوصول إليها على الموظفين "
    "المخولين، ويتم الاحتفاظ بها فقط للمدة التي يتطلبها القانون قبل حذفها."
)


@ekyc_bp.route('/')
@login_required
@permission_required('ekyc', level='view')
def dashboard():
    sessions = EkycSession.list_all()
    needs_review_count = len(EkycSession.list_needs_review())
    decision_pending_count = len(EkycSession.list_decision_pending())
    return render_template('ekyc/list.html', sessions=sessions,
                            needs_review_count=needs_review_count,
                            decision_pending_count=decision_pending_count)


@ekyc_bp.route('/sessions/export')
@login_required
@permission_required('ekyc', level='view')
def export_sessions():
    """
    CSV export of the session list, filtered by the officer's final
    decision — 'approved'/'rejected' match final_decision directly (set
    once by session_decision() and left alone by onboarding, so it still
    covers ONBOARDED sessions); 'pending' is everything not yet decided;
    'all' is unfiltered.
    """
    status_filter = (request.args.get('status') or 'all').lower()
    where = {
        'approved': "WHERE s.final_decision = 'APPROVED'",
        'rejected': "WHERE s.final_decision = 'REJECTED'",
        'pending': "WHERE s.final_decision IS NULL",
    }.get(status_filter, '')

    rows = query_db(f'''
        SELECT s.id, s.customer_reference, s.document_type, s.status,
               s.final_decision, r.decision AS ai_decision, r.risk_score,
               s.created_at, s.decided_at,
               u.first_name || ' ' || u.last_name AS created_by_name,
               d.first_name || ' ' || d.last_name AS decided_by_name
        FROM ekyc_session s
        LEFT JOIN ekyc_result r ON r.session_id = s.id
        LEFT JOIN users u ON s.created_by = u.id
        LEFT JOIN users d ON s.decision_by = d.id
        {where}
        ORDER BY s.created_at DESC
    ''')

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Customer Reference', 'Document Type', 'Status', 'Final Decision',
                      'System Decision', 'Risk Score', 'Created At', 'Created By',
                      'Decided At', 'Decided By'])
    for row in rows:
        r = dict(row)
        writer.writerow([
            r.get('id'), r.get('customer_reference') or '', r.get('document_type'), r.get('status'),
            r.get('final_decision') or '', r.get('ai_decision') or '', r.get('risk_score'),
            r.get('created_at'), r.get('created_by_name') or '',
            r.get('decided_at') or '', r.get('decided_by_name') or '',
        ])

    EkycAuditLog.log(None, 'SESSIONS_EXPORTED', user_id=current_user.id,
                      details=f'filter={status_filter} rows={len(rows)}', ip_address=request.remote_addr)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=ekyc_sessions_{status_filter}.csv'}
    )


@ekyc_bp.route('/new', methods=['GET', 'POST'])
@limiter.limit('20 per minute')
@login_required
@permission_required('ekyc', level='edit')
def new_session():
    if request.method == 'POST':
        document_type = request.form.get('document_type', 'NATIONAL_ID')
        customer_reference = request.form.get('customer_reference') or None
        locale = request.form.get('locale', 'ar')
        session = EkycSession.create(
            document_type=document_type,
            customer_reference=customer_reference,
            created_by=current_user.id,
            locale=locale,
        )
        flash(gettext('eKYC session created. Share the verification link with the customer.'), 'success')
        return redirect(url_for('ekyc.view_session', session_id=session['id']))
    return render_template('ekyc/new.html', document_types=DOCUMENT_TYPES)


@ekyc_bp.route('/session/<int:session_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('ekyc', level='edit')
def edit_session(session_id):
    session = EkycSession.get_by_id(session_id)
    if not session:
        flash(gettext('eKYC session not found.'), 'danger')
        return redirect(url_for('ekyc.dashboard'))
    if session['status'] in POST_SUBMISSION_STATUSES:
        flash(gettext('This session is already completed and can\'t be edited. Create a new session instead.'), 'warning')
        return redirect(url_for('ekyc.view_session', session_id=session_id))

    if request.method == 'POST':
        document_type = request.form.get('document_type', session['document_type'])
        if document_type not in dict(DOCUMENT_TYPES):
            document_type = session['document_type']
        customer_reference = request.form.get('customer_reference') or None
        locale = request.form.get('locale', session['locale'])
        EkycSession.update_details(session_id, document_type, customer_reference, locale,
                                    user_id=current_user.id)
        flash(gettext('eKYC session updated.'), 'success')
        return redirect(url_for('ekyc.view_session', session_id=session_id))

    return render_template('ekyc/edit.html', session=session, document_types=DOCUMENT_TYPES)


@ekyc_bp.route('/session/<int:session_id>/customer-reference', methods=['POST'])
@login_required
@permission_required('ekyc', level='edit')
def update_customer_reference(session_id):
    """
    Always available, regardless of session status — unlike edit_session()
    above, which locks document_type/locale once the customer has submitted
    (POST_SUBMISSION_STATUSES). The customer reference is just a free-text
    staff label with no effect on capture/OCR, and review/decision is
    usually exactly when staff first know which customer/CRM record to tag
    it with, so locking it out at that point left it stuck on '-' forever.
    """
    session = EkycSession.get_by_id(session_id)
    if not session:
        flash(gettext('eKYC session not found.'), 'danger')
        return redirect(url_for('ekyc.dashboard'))

    customer_reference = request.form.get('customer_reference') or None
    EkycSession.update_customer_reference(session_id, customer_reference, user_id=current_user.id)
    flash(gettext('Customer reference updated.'), 'success')
    return redirect(url_for('ekyc.view_session', session_id=session_id))


@ekyc_bp.route('/session/<int:session_id>/regenerate-link', methods=['POST'])
@login_required
@permission_required('ekyc', level='edit')
def regenerate_link(session_id):
    session = EkycSession.get_by_id(session_id)
    if not session:
        flash(gettext('eKYC session not found.'), 'danger')
        return redirect(url_for('ekyc.dashboard'))
    if session['status'] in POST_SUBMISSION_STATUSES:
        flash(gettext('This session is already completed and can\'t be regenerated. Create a new session instead.'), 'warning')
        return redirect(url_for('ekyc.view_session', session_id=session_id))

    EkycSession.regenerate_link(session_id, user_id=current_user.id, ip_address=request.remote_addr)
    flash(gettext('A new verification link has been generated. The old link no longer works.'), 'success')
    return redirect(url_for('ekyc.view_session', session_id=session_id))


@ekyc_bp.route('/session/<int:session_id>')
@login_required
@permission_required('ekyc', level='view')
def view_session(session_id):
    session = EkycSession.get_by_id(session_id)
    if not session:
        flash(gettext('eKYC session not found.'), 'danger')
        return redirect(url_for('ekyc.dashboard'))
    documents = EkycDocument.list_for_session(session_id)
    result = EkycResult.get_for_session(session_id)
    audit_trail = EkycAuditLog.get_for_session(session_id)
    verify_url = url_for('ekyc.verify', token=session['session_token'], lang=session['locale'], _external=True)
    # PII/biometric access is audited regardless of read vs edit permission level.
    EkycAuditLog.log(session_id, 'SESSION_VIEWED', user_id=current_user.id, ip_address=request.remote_addr)
    return render_template('ekyc/view.html', session=session, documents=documents,
                            result=result, audit_trail=audit_trail, verify_url=verify_url)


@ekyc_bp.route('/document/<int:doc_id>/view')
@login_required
@permission_required('ekyc', level='edit')
def view_document(doc_id):
    """
    Decrypts and serves a captured frame on the fly — never writes a
    decrypted copy to disk, never served from static/. Gated at 'edit'
    level (stricter than the dashboard's 'view') since this exposes raw
    biometric/ID imagery, and every access is audited with who/when.
    """
    document = EkycDocument.get_by_id(doc_id)
    if document is None:
        flash(gettext('Document not found.'), 'danger')
        return redirect(url_for('ekyc.dashboard'))

    if document.get('purged_at'):
        flash(gettext('This media has been purged per the data retention policy.'), 'warning')
        return redirect(url_for('ekyc.view_session', session_id=document['session_id']))

    data = read_frame(document['stored_path'], key_version=document['encryption_key_id'])
    EkycAuditLog.log(document['session_id'], 'DOCUMENT_VIEWED', user_id=current_user.id,
                      details=f"doc_id={doc_id} doc_role={document['doc_role']}", ip_address=request.remote_addr)
    return Response(data, mimetype=document.get('mime_type') or 'image/jpeg')


@ekyc_bp.route('/verify/<token>')
def verify(token):
    """Customer-facing entry point — no login required (the applicant, not staff)."""
    session = EkycSession.get_by_token(token)
    if not session:
        return render_template('ekyc/expired.html'), 404
    if EkycSession.is_expired(session) and session['status'] not in POST_SUBMISSION_STATUSES:
        return render_template('ekyc/expired.html'), 410

    if not session['consent_given']:
        consent_text = CONSENT_TEXT_AR if session['locale'] == 'ar' else CONSENT_TEXT_EN
        return render_template('ekyc/consent.html', session=session, consent_text=consent_text)

    if session['status'] == 'CONSENT_GIVEN':
        # Resume at the right step on reload (e.g. after a dropped
        # connection or a customer closing the tab mid-flow) instead of
        # always restarting at step 1 — front/back ID sides are persisted
        # one at a time by check_side() as soon as the customer confirms
        # each one, so what's already on file tells us exactly where to
        # resume.
        existing_roles = {d['doc_role'] for d in EkycDocument.list_for_session(session['id'])}
        return render_template('ekyc/capture.html', session=session,
                                front_done='ID_FRONT_VIDEO' in existing_roles,
                                back_done='ID_BACK_VIDEO' in existing_roles)

    if session['status'] in ('CAPTURED', 'QUEUED', 'PROCESSING', 'FAILED') \
            or session['status'] in POST_SUBMISSION_STATUSES:
        # The customer's part ends the moment the selfie is uploaded:
        # processing runs in the background (a minute or more on this CPU-
        # only server) and its outcome goes to staff, not to the customer.
        # Showing a spinner that polls until processing ends made the page
        # look frozen, so the "received" page is shown straight away.
        # Same "thank you, under review" page regardless of where the
        # session landed (NEEDS_REVIEW awaiting an officer, DECISION_PENDING
        # awaiting final approve/reject, or already APPROVED/ONBOARDED) —
        # and deliberately also for REJECTED: the customer is never told a
        # hard "no" here (see the module brief's "never hard-block" principle
        # plus screening_queue's standard practice of not tipping off a
        # confirmed match), staff follow up separately if needed.
        return render_template('ekyc/done.html', session=session)

    return render_template('ekyc/capture.html', session=session)


@ekyc_bp.route('/verify/<token>/consent', methods=['POST'])
def give_consent(token):
    session = EkycSession.get_by_token(token)
    if not session:
        return render_template('ekyc/expired.html'), 404
    if EkycSession.is_expired(session):
        return render_template('ekyc/expired.html'), 410

    if session['consent_given']:
        return redirect(url_for('ekyc.verify', token=token))

    consent_text = CONSENT_TEXT_AR if session['locale'] == 'ar' else CONSENT_TEXT_EN
    declared_nid, declared_name, errors = _read_declared_identity(session)
    if errors:
        return render_template('ekyc/consent.html', session=session, consent_text=consent_text,
                                errors=errors, declared_nid=request.form.get('declared_national_id', ''),
                                declared_name=request.form.get('declared_name_ar', '')), 400
    EkycSession.record_consent(session['id'], consent_text, request.remote_addr,
                                declared_national_id=declared_nid, declared_name_ar=declared_name)
    return redirect(url_for('ekyc.verify', token=token))


_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def _read_declared_identity(session):
    """The national ID and Arabic name the customer types before capture.
    Required for a national ID card; returns (nid, name, errors)."""
    import re
    from ekyc.national_id import decode as decode_national_id

    ar = session['locale'] == 'ar'
    raw_nid = (request.form.get('declared_national_id') or '').translate(_ARABIC_DIGITS)
    nid = re.sub(r'\D', '', raw_nid) or None
    name = ' '.join((request.form.get('declared_name_ar') or '').split()) or None
    errors = []
    if session['document_type'] != 'NATIONAL_ID':
        return None, name, errors
    if not nid:
        errors.append('اكتب الرقم القومي (14 رقمًا).' if ar else 'Enter your national ID number (14 digits).')
    elif not decode_national_id(nid)['is_valid']:
        errors.append('الرقم القومي غير صحيح، راجعه من البطاقة.' if ar
                      else 'The national ID number is not valid; check it against your card.')
    if not name:
        errors.append('اكتب اسمك بالعربي كما هو في البطاقة.' if ar
                      else 'Enter your name in Arabic as printed on the card.')
    elif not re.fullmatch(r'[\u0621-\u064A\s]+', name) or len(name.split()) < 3:
        errors.append('اكتب الاسم بالحروف العربية كما هو في البطاقة (ثلاثة أسماء على الأقل).' if ar
                      else 'Write the name in Arabic letters as on the card (at least three names).')
    return nid, name, errors


@ekyc_bp.route('/verify/<token>/check_side', methods=['POST'])
def check_side(token):
    """
    Accepts a customer-confirmed burst of ID-side frames (front/back) and
    saves all of them immediately. The customer already saw (the last of)
    their own just-captured frames and confirmed it looked clear (static/
    ekyc/js/capture.js's image-preview step) before this request was even
    sent — there is deliberately no OCR/document-PAD gate here. Multiple
    frames (not just the one previewed) so the async pipeline still has
    enough for OCR consensus and ekyc/document_pad.py's reflection-variance
    check, which needs >=3 frames per side — accepting only one would
    silently zero out that signal for every session.

    Previously ran a synchronous OCR/document-PAD validation job
    (ekyc.worker.check_id_side) before letting the customer advance. Removed
    by explicit decision: on this CPU-only box that job routinely took
    40-60+ seconds and regularly exceeded its own 60s timeout, surfacing as
    a generic upload-failed error for what was really just a slow OCR call
    (see ekyc/worker.py's docstring). The real, authoritative OCR/document-
    PAD/decision still happens — async, after final submission, via
    ekyc.pipeline.run_pipeline — exactly as before; only WHEN a bad capture
    is caught changed (officer review instead of capture time).
    """
    session = EkycSession.get_by_token(token)
    if not session:
        return jsonify({'error': 'session not found'}), 404
    if EkycSession.is_expired(session):
        return jsonify({'error': 'session expired'}), 410
    if session['status'] != 'CONSENT_GIVEN':
        return jsonify({'error': f"unexpected session status '{session['status']}'"}), 409

    side = request.form.get('side')
    if side not in ('front', 'back'):
        return jsonify({'error': "'side' must be 'front' or 'back'"}), 400
    if side == 'back' and session['document_type'] not in BACK_SIDE_REQUIRED_TYPES:
        return jsonify({'error': 'back-side capture is not required for this document type'}), 400

    frame_files = [f for key, f in sorted(request.files.items())
                   if key.startswith('frame_')][:MAX_SIDE_CHECK_FRAMES]
    if not frame_files:
        return jsonify({'error': 'no frames received'}), 400
    frames_data = [data for data in (f.read() for f in frame_files) if data]
    if not frames_data:
        return jsonify({'error': 'no frames received'}), 400

    # Optional draft-only hint from static/ekyc/js/capture.js's readIdHint()
    # (front side only) — validated just enough to drop anything malformed
    # or oversized; never used for anything but display (ekyc/pipeline.py's
    # raw_signals, the officer review screen).
    ocr_hint = None
    ocr_hint_raw = request.form.get('ocr_hint')
    if ocr_hint_raw and len(ocr_hint_raw) <= 2048:
        try:
            parsed = json.loads(ocr_hint_raw)
            if isinstance(parsed, dict):
                ocr_hint = parsed
        except (TypeError, ValueError):
            pass

    doc_role = 'ID_FRONT_VIDEO' if side == 'front' else 'ID_BACK_VIDEO'
    for i, data in enumerate(frames_data):
        path, size, key_version = save_frame(token, doc_role, data)
        # Hint attached to the first frame's row only (one read-back per
        # side, not duplicated across every frame in the burst).
        EkycDocument.create(session['id'], doc_role, path, encryption_key_id=key_version,
                             file_size=size, mime_type='image/jpeg',
                             client_ocr_hint=(ocr_hint if i == 0 and side == 'front' else None))
    EkycAuditLog.log(session['id'], 'SIDE_CHECK_ATTEMPT',
                      details=f"side={side} result=ACCEPTED (customer-confirmed, no OCR gate) "
                              f"frames={len(frames_data)}")

    return jsonify({'ok': True})


@ekyc_bp.route('/verify/<token>/upload', methods=['POST'])
@limiter.limit('10 per minute')
def upload_capture(token):
    """
    Receives the selfie frames (multipart, fields selfie_frame_0..) plus the
    client-evaluated active liveness challenge result (JSON in the
    'liveness_result' field). ID frames (front, and back for NATIONAL_ID)
    are NOT sent here — they're already persisted one side at a time by
    check_side() as each side is captured and confirmed, so by the time the
    customer reaches this final submit step those EkycDocument rows already
    exist.

    The active liveness pass/fail is evaluated client-side by MediaPipe
    (per the brief's design) and reported here, not independently
    re-verified server-side — see ekyc/face_liveness.py's docstring and
    the eKYC module docs for that limitation. 'passed' may be None (manual-
    capture fallback, see static/ekyc/js/capture.js) — preserved as NULL,
    not coerced to False, so ekyc/risk_engine.py can tell "not evaluated"
    apart from "evaluated and failed".
    """
    session = EkycSession.get_by_token(token)
    if not session:
        return jsonify({'error': 'session not found'}), 404
    if EkycSession.is_expired(session):
        return jsonify({'error': 'session expired'}), 410
    if session['status'] != 'CONSENT_GIVEN':
        return jsonify({'error': f"unexpected session status '{session['status']}'"}), 409

    selfie_files = [f for key, f in request.files.items() if key.startswith('selfie_frame_')][:MAX_FRAMES_PER_ROLE]
    if not selfie_files:
        return jsonify({'error': 'selfie frames are required'}), 400

    front_passed = any(d['doc_role'] == 'ID_FRONT_VIDEO' for d in EkycDocument.list_for_session(session['id']))
    if not front_passed:
        return jsonify({'error': 'front-side ID has not passed validation yet'}), 409
    if session['document_type'] in BACK_SIDE_REQUIRED_TYPES:
        back_passed = any(d['doc_role'] == 'ID_BACK_VIDEO' for d in EkycDocument.list_for_session(session['id']))
        if not back_passed:
            return jsonify({'error': 'back-side ID has not passed validation yet'}), 409

    for f in selfie_files:
        data = f.read()
        if not data:
            continue
        path, size, key_version = save_frame(token, 'SELFIE_VIDEO', data)
        EkycDocument.create(session['id'], 'SELFIE_VIDEO', path, encryption_key_id=key_version,
                             file_size=size, mime_type=f.mimetype)

    liveness_raw = request.form.get('liveness_result', '{}')
    try:
        liveness = json.loads(liveness_raw)
    except (TypeError, ValueError):
        liveness = {}
    challenge = liveness.get('challenge')
    if challenge not in ALLOWED_CHALLENGES:
        challenge = None
    # 'passed' is explicitly None (not False) when the client fell back to
    # manual selfie capture because the in-browser face detector failed to
    # load (see static/ekyc/js/capture.js's runManualSelfieCapture) — that's
    # "not evaluated", distinct from "evaluated and failed", and must not be
    # scored the same way by ekyc/risk_engine.py's fuse_risk().
    raw_passed = liveness.get('passed')
    active_liveness_pass = None if raw_passed is None else bool(raw_passed)
    EkycResult.upsert(
        session['id'],
        active_liveness_pass=active_liveness_pass,
        active_liveness_challenge=challenge,
    )

    EkycSession.update_status(session['id'], 'CAPTURED', ip_address=request.remote_addr)
    try:
        enqueue_session(session['id'])
        EkycSession.update_status(session['id'], 'QUEUED', ip_address=request.remote_addr)
    except Exception:
        # Capture is safely stored; staff can start processing from the
        # session page Re-run processing. The customer is done either way.
        current_app.logger.exception(f"eKYC enqueue failed for session {session['id']}")
        EkycAuditLog.log(session['id'], 'ENQUEUE_FAILED', ip_address=request.remote_addr)

    return jsonify({'ok': True, 'redirect': url_for('ekyc.verify', token=token)})


@ekyc_bp.route('/verify/<token>/status')
def capture_status(token):
    """JSON polling endpoint for the processing page."""
    session = EkycSession.get_by_token(token)
    if not session:
        return jsonify({'error': 'session not found'}), 404
    return jsonify({'status': session['status'], 'error_message': session.get('error_message')})


def _doc_data_uri(document):
    """Decrypts one captured frame and returns it as a data: URI for inline embedding
    in the report — never written to disk decrypted, same guarantee as view_document."""
    if not document or document.get('purged_at'):
        return None
    data = read_frame(document['stored_path'], key_version=document['encryption_key_id'])
    mime = document.get('mime_type') or 'image/jpeg'
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


@ekyc_bp.route('/session/<int:session_id>/form')
@login_required
@permission_required('ekyc', level='view')
def session_report(session_id):
    """
    Printable/PDF eKYC verification report — one page covering identity,
    documents, biometrics, AI result, screening dispositions, consent, and
    the final compliance decision. ?format=pdf renders the exact same
    template through WeasyPrint instead of returning the HTML page, so
    there's only one layout to keep in sync.

    Generated on demand and streamed straight from memory (no temp file on
    disk) — see secure_storage.read_frame, which is the same on-the-fly
    decryption view_document already uses for single images.
    """
    from datetime import datetime

    session = EkycSession.get_by_id(session_id)
    if not session:
        flash(gettext('eKYC session not found.'), 'danger')
        return redirect(url_for('ekyc.dashboard'))

    result = EkycResult.get_for_session(session_id) or {}
    documents = EkycDocument.list_for_session(session_id)
    audit_trail = EkycAuditLog.get_for_session(session_id)

    docs_by_role = {}
    for doc in documents:
        docs_by_role.setdefault(doc['doc_role'], doc)  # first (earliest) capture per role
    id_front_image = _doc_data_uri(docs_by_role.get('ID_FRONT_VIDEO'))
    id_back_image = _doc_data_uri(docs_by_role.get('ID_BACK_VIDEO'))
    selfie_image = _doc_data_uri(docs_by_role.get('SELFIE_VIDEO'))

    customer = None
    if session.get('onboarded_customer_id'):
        customer = query_db('SELECT * FROM customers WHERE id = %s', (session['onboarded_customer_id'],), one=True)

    screening_history = query_db("""
        SELECT * FROM screening_history
        WHERE source_module = 'eKYC' AND source_record_id = %s
        ORDER BY id DESC
    """, (session_id,))
    screening_matches = query_db("""
        SELECT q.*, u.first_name || ' ' || u.last_name AS resolved_by_name
        FROM screening_queue q
        LEFT JOIN users u ON q.resolved_by = u.id
        WHERE q.source_module = 'eKYC' AND q.source_record_id = %s
        ORDER BY q.match_score DESC
    """, (session_id,))

    reviewed_by_name = decision_by_name = None
    if session.get('reviewed_by'):
        row = query_db("SELECT first_name || ' ' || last_name AS name FROM users WHERE id = %s",
                        (session['reviewed_by'],), one=True)
        reviewed_by_name = row['name'] if row else None
    if session.get('decision_by'):
        row = query_db("SELECT first_name || ' ' || last_name AS name FROM users WHERE id = %s",
                        (session['decision_by'],), one=True)
        decision_by_name = row['name'] if row else None

    field_sources = result.get('field_sources') or {}

    fmt = request.args.get('format')
    context = dict(
        session=session, result=result, customer=customer,
        id_front_image=id_front_image, id_back_image=id_back_image, selfie_image=selfie_image,
        screening_history=screening_history, screening_matches=screening_matches,
        reviewed_by_name=reviewed_by_name, decision_by_name=decision_by_name,
        field_sources=field_sources, audit_trail=audit_trail,
        generated_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
        generated_by=current_user.get_full_name(),
        is_pdf=(fmt == 'pdf'),
        # Browsers block <img src="file://..."> from a page served over
        # http(s) (mixed-content/local-file restriction) — that only ever
        # worked for the WeasyPrint PDF path, which renders server-side with
        # real filesystem access. The plain HTML view needs the normal
        # static URL instead.
        logo_path=('file://' + os.path.join(current_app.static_folder, 'images', 'logo.png'))
                  if fmt == 'pdf' else url_for('static', filename='images/logo.png'),
    )

    EkycAuditLog.log(session_id, 'REPORT_GENERATED', user_id=current_user.id,
                      details=f"format={fmt or 'html'}", ip_address=request.remote_addr)

    html_content = render_template('ekyc/report.html', **context)
    if fmt != 'pdf':
        return html_content

    from weasyprint import HTML
    pdf_bytes = HTML(string=html_content).write_pdf()
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    reference = session.get('customer_reference') or session['session_token'][:12]
    response.headers['Content-Disposition'] = f'attachment; filename=eKYC_Report_{reference}.pdf'
    return response


# ─────────────────────────────────────────────
#  COMPLIANCE REVIEW QUEUE (manual OCR/data correction)
# ─────────────────────────────────────────────

# Statuses in which an officer may open "Correct data": anything the
# pipeline has finished with, up to (not including) onboarding. Correcting
# an APPROVED session sends it back to DECISION_PENDING for a fresh approval.
CORRECTABLE_STATUSES = ('NEEDS_REVIEW', 'FAILED', 'DECISION_PENDING', 'APPROVED')
REPROCESSABLE_STATUSES = ('FAILED', 'CAPTURED', 'QUEUED', 'PROCESSING')

REVIEWABLE_RESULT_FIELDS = (
    'extracted_full_name_ar', 'national_id', 'dob', 'gender', 'governorate_name',
    'extracted_address', 'extracted_occupation', 'extracted_marital_status', 'id_expiry_raw',
)


@ekyc_bp.route('/review')
@login_required
@permission_required('ekyc', level='view')
def review_queue():
    sessions = EkycSession.list_needs_review()
    return render_template('ekyc/review_queue.html', sessions=sessions)


@ekyc_bp.route('/decision-pending')
@login_required
@permission_required('ekyc', level='view')
def decision_pending_queue():
    """Sessions cleared by the system and screening, awaiting an officer's
    final Approve/Reject — see EkycSession.record_decision."""
    sessions = EkycSession.list_decision_pending()
    return render_template('ekyc/decision_pending.html', sessions=sessions)


@ekyc_bp.route('/review/<int:session_id>', methods=['GET', 'POST'])
@login_required
@permission_required('ekyc', level='edit')
def review_detail(session_id):
    """
    Side-by-side correction UI: ID images + selfie on one side, AI-extracted
    fields (editable) on the other, with live national-ID validation. On
    submit, corrected fields are saved (tagged source='manual' in
    field_sources for whichever changed), the officer's visual face-match
    confirmation is logged, and screening is re-run against the
    (possibly corrected) identity — see ekyc.pipeline._run_screening, the
    same helper the AI pipeline itself uses, so a hit found here lands in
    the exact same screening_queue an officer already works from.
    """
    from ekyc.national_id import decode as decode_national_id

    session = EkycSession.get_by_id(session_id)
    if not session:
        flash(gettext('eKYC session not found.'), 'danger')
        return redirect(url_for('ekyc.review_queue'))
    if session['status'] not in CORRECTABLE_STATUSES:
        flash(gettext('This session is not available for manual review.'), 'warning')
        return redirect(url_for('ekyc.view_session', session_id=session_id))

    result = EkycResult.get_for_session(session_id) or {}
    documents = EkycDocument.list_for_session(session_id)
    form_values, field_sources = _review_prefill(session, result)

    if request.method == 'POST':
        submitted = {field: (request.form.get(field) or '').strip() or None
                     for field in REVIEWABLE_RESULT_FIELDS}

        if submitted['national_id']:
            submitted['national_id'] = submitted['national_id'].translate(_ARABIC_DIGITS).replace(' ', '')
        decoded = decode_national_id(submitted['national_id']) if submitted['national_id'] else None
        problems = []
        if submitted['national_id'] and not decoded['is_valid']:
            problems.append(gettext('National ID is not valid: %(errors)s', errors='; '.join(decoded['errors'])))
        if decoded and decoded['is_valid']:
            # Blank fields the national ID itself encodes are filled from it.
            submitted['dob'] = submitted['dob'] or decoded['dob'].isoformat()
            submitted['gender'] = submitted['gender'] or decoded.get('gender')
            submitted['governorate_name'] = submitted['governorate_name'] or decoded.get('governorate_name_ar')
        if submitted['dob']:
            from datetime import date
            try:
                date.fromisoformat(submitted['dob'].translate(_ARABIC_DIGITS))
                submitted['dob'] = submitted['dob'].translate(_ARABIC_DIGITS)
            except ValueError:
                problems.append(gettext('Date of birth must be written as YYYY-MM-DD.'))
        if not submitted['extracted_full_name_ar']:
            problems.append(gettext('Full name is required.'))
        if problems:
            for problem in problems:
                flash(problem, 'danger')
            return render_template('ekyc/review_detail.html', session=session, result=result,
                                    documents=documents, field_sources=field_sources,
                                    form_values=submitted)

        field_sources = dict(result.get('field_sources') or {})
        manually_changed = []
        for field in REVIEWABLE_RESULT_FIELDS:
            old_val, new_val = result.get(field), submitted[field]
            if old_val is not None and not isinstance(old_val, str):
                old_val = old_val.isoformat() if hasattr(old_val, 'isoformat') else str(old_val)
            if new_val != old_val and not (new_val is None and old_val is None):
                field_sources[field] = 'manual'
                manually_changed.append(field)
            else:
                # Officer reviewed this field and left it unchanged — mark confirmed
                field_sources[field] = field_sources.get(field) if field_sources.get(field) == 'manual' else 'confirmed'

        face_match_confirmed = request.form.get('face_match_confirmed') == 'on'
        review_notes = request.form.get('review_notes') or None

        EkycResult.upsert(
            session_id,
            extracted_full_name_ar=submitted['extracted_full_name_ar'],
            national_id=submitted['national_id'],
            national_id_valid=decoded['is_valid'] if decoded else result.get('national_id_valid'),
            dob=submitted['dob'],
            gender=submitted['gender'],
            governorate_name=submitted['governorate_name'],
            extracted_address=submitted['extracted_address'],
            extracted_occupation=submitted['extracted_occupation'],
            extracted_marital_status=submitted['extracted_marital_status'],
            id_expiry_raw=submitted['id_expiry_raw'],
            field_sources=json.dumps(field_sources),
            # Dual storage: preserve original pipeline reads in extracted_* (above);
            # also write officer-confirmed values to final_* so both are queryable.
            final_name=submitted['extracted_full_name_ar'],
            final_national_id=submitted['national_id'],
            final_address=submitted['extracted_address'],
        )
        EkycAuditLog.log(session_id, 'MANUAL_FIELDS_CORRECTED', user_id=current_user.id,
                          details=f"fields_changed={manually_changed} "
                                  f"face_match_confirmed={face_match_confirmed}")

        pending_matches = 0
        name = submitted['extracted_full_name_ar']
        if name:
            from ekyc.pipeline import _run_screening
            _, _, pending_matches = _run_screening(session_id, name, decoded or {})

        EkycSession.record_review(
            session_id, current_user.id, notes=review_notes,
            new_status='DECISION_PENDING' if pending_matches == 0 else 'NEEDS_REVIEW',
        )
        if session['status'] == 'APPROVED':
            EkycSession.clear_decision(session_id, user_id=current_user.id)
            flash(gettext('Data corrected. The earlier approval no longer applies: approve the session again.'), 'warning')
        if pending_matches:
            flash(gettext('Review submitted. Screening hit(s) found — see the screening queue.'), 'warning')
        else:
            flash(gettext('Review submitted. Ready for final decision.'), 'success')
        return redirect(url_for('ekyc.view_session', session_id=session_id))

    return render_template('ekyc/review_detail.html', session=session, result=result, documents=documents,
                            field_sources=field_sources, form_values=form_values)


def _review_prefill(session, result):
    """Form values for the correction screen: the saved result, with the
    customer's own entry filling any field the card read left empty."""
    from ekyc.national_id import decode as decode_national_id

    values = dict(result)
    sources = dict(result.get('field_sources') or {})
    declared_nid = session.get('declared_national_id')
    declared_name = session.get('declared_name_ar')
    if declared_nid and not values.get('national_id'):
        decoded = decode_national_id(declared_nid)
        values['national_id'] = declared_nid
        sources['national_id'] = 'declared'
        if decoded['is_valid']:
            for field, value in (('dob', decoded['dob']), ('gender', decoded.get('gender')),
                                 ('governorate_name', decoded.get('governorate_name_ar'))):
                if not values.get(field):
                    values[field] = value
                    sources[field] = 'declared'
    if declared_name and not values.get('extracted_full_name_ar'):
        values['extracted_full_name_ar'] = declared_name
        sources['extracted_full_name_ar'] = 'declared'
    return values, sources


@ekyc_bp.route('/session/<int:session_id>/reprocess', methods=['POST'])
@login_required
@permission_required('ekyc', level='edit')
def session_reprocess(session_id):
    """Puts a captured session back on the processing queue — for a
    session that failed, or that has sat in the queue because the worker
    was down. Officer corrections made later still go through Correct data."""
    session = EkycSession.get_by_id(session_id)
    if not session:
        flash(gettext('eKYC session not found.'), 'danger')
        return redirect(url_for('ekyc.dashboard'))
    if session['status'] not in REPROCESSABLE_STATUSES:
        flash(gettext('Only a failed or waiting session can be processed again.'), 'warning')
        return redirect(url_for('ekyc.view_session', session_id=session_id))
    try:
        enqueue_session(session_id)
    except Exception:
        current_app.logger.exception(f"eKYC re-enqueue failed for session {session_id}")
        flash(gettext('Could not reach the processing queue. Try again in a minute.'), 'danger')
        return redirect(url_for('ekyc.view_session', session_id=session_id))
    EkycSession.update_status(session_id, 'QUEUED', user_id=current_user.id, ip_address=request.remote_addr)
    flash(gettext('Session sent for processing again.'), 'success')
    return redirect(url_for('ekyc.view_session', session_id=session_id))


@ekyc_bp.route('/review/<int:session_id>/assign', methods=['POST'])
@login_required
@permission_required('ekyc', level='edit')
def review_assign(session_id):
    EkycSession.assign_reviewer(session_id, current_user.id, user_id=current_user.id)
    flash(gettext('Assigned to you.'), 'success')
    return redirect(url_for('ekyc.review_detail', session_id=session_id))


@ekyc_bp.route('/national-id/validate', methods=['POST'])
@login_required
@permission_required('ekyc', level='edit')
def validate_national_id():
    """Live-validation AJAX endpoint for the review form — wraps the same
    ekyc.national_id.decode() the pipeline itself uses, so the officer sees
    the exact same checksum/century/governorate verdict the AI did."""
    from ekyc.national_id import decode as decode_national_id
    raw = (request.form.get('national_id', '') or '').translate(_ARABIC_DIGITS).strip()
    if not raw:
        return jsonify({'is_valid': None})
    decoded = dict(decode_national_id(raw))
    if decoded.get('dob') is not None:
        decoded['dob'] = decoded['dob'].isoformat()  # jsonify would send an HTTP-date string
    return jsonify(decoded)


# ─────────────────────────────────────────────
#  SCREENING SUMMARY, FINAL DECISION, ONBOARDING
# ─────────────────────────────────────────────

@ekyc_bp.route('/session/<int:session_id>/screening')
@login_required
@permission_required('ekyc', level='view')
def session_screening(session_id):
    """
    Read-only summary of this session's screening hits — actual disposition
    (False Positive / True Match / PEP / Escalate) happens in the existing
    /screening/queue UI (see ekyc/pipeline.py's _run_screening docstring for
    why eKYC reuses that workflow instead of a parallel one); this page just
    links each hit there and shows whatever's already been resolved.
    """
    session = EkycSession.get_by_id(session_id)
    if not session:
        flash(gettext('eKYC session not found.'), 'danger')
        return redirect(url_for('ekyc.dashboard'))

    screening_history = query_db("""
        SELECT * FROM screening_history WHERE source_module = 'eKYC' AND source_record_id = %s
        ORDER BY id DESC
    """, (session_id,))
    screening_matches = query_db("""
        SELECT q.*, u.first_name || ' ' || u.last_name AS resolved_by_name
        FROM screening_queue q
        LEFT JOIN users u ON q.resolved_by = u.id
        WHERE q.source_module = 'eKYC' AND q.source_record_id = %s
        ORDER BY q.match_score DESC
    """, (session_id,))
    return render_template('ekyc/screening.html', session=session,
                            screening_history=screening_history, screening_matches=screening_matches)


@ekyc_bp.route('/session/<int:session_id>/decision', methods=['POST'])
@login_required
@permission_required('ekyc', level='edit')
def session_decision(session_id):
    session = EkycSession.get_by_id(session_id)
    if not session:
        flash(gettext('eKYC session not found.'), 'danger')
        return redirect(url_for('ekyc.dashboard'))

    action = request.form.get('action')
    notes = request.form.get('notes') or None
    if action == 'approve':
        if session['status'] != 'DECISION_PENDING':
            flash(gettext('This session is not ready for approval — screening must be clear first.'), 'warning')
            return redirect(url_for('ekyc.view_session', session_id=session_id))
        EkycSession.record_decision(session_id, 'APPROVED', current_user.id, notes)
        flash(gettext('Session approved.'), 'success')
    elif action == 'reject':
        if session['status'] in ('ONBOARDED', 'REJECTED'):
            flash(gettext('This session is already finalized.'), 'warning')
            return redirect(url_for('ekyc.view_session', session_id=session_id))
        EkycSession.record_decision(session_id, 'REJECTED', current_user.id, notes)
        flash(gettext('Session rejected.'), 'success')
    else:
        flash(gettext("Invalid action — must be 'approve' or 'reject'."), 'danger')
    return redirect(url_for('ekyc.view_session', session_id=session_id))


def _expiry_date(raw):
    """The card's expiry as YYYY-MM-DD from the raw back-side read
    ("البطاقة سارية حتى ٢٠٢٩/٠٥/١٢", "12/05/2029", "2029-05-12"), or None —
    the customer record should hold a date, not the OCR line."""
    import re
    from datetime import date
    text = (raw or '').translate(_ARABIC_DIGITS)
    for pattern, order in ((r'(\d{4})\D{1,3}(\d{1,2})\D{1,3}(\d{1,2})', 'ymd'),
                           (r'(\d{1,2})\D{1,3}(\d{1,2})\D{1,3}(\d{4})', 'dmy')):
        m = re.search(pattern, text)
        if m:
            a, b, c = (int(x) for x in m.groups())
            y, mo, d = (a, b, c) if order == 'ymd' else (c, b, a)
            try:
                return date(y, mo, d).isoformat()
            except ValueError:
                continue
    return None


@ekyc_bp.route('/session/<int:session_id>/onboard', methods=['POST'])
@login_required
@permission_required('ekyc', level='edit')
def session_onboard(session_id):
    """Creates the final customer record from an APPROVED session — mirrors
    the same Customer.create() Customer KYC itself uses (models/aml.py), so
    the resulting customer looks identical regardless of which flow onboarded
    them, and is already covered by the existing periodic re-screening job."""
    from models.aml import Customer

    session = EkycSession.get_by_id(session_id)
    if not session:
        flash(gettext('eKYC session not found.'), 'danger')
        return redirect(url_for('ekyc.dashboard'))
    if session['status'] != 'APPROVED':
        flash(gettext('Only an approved session can be onboarded.'), 'warning')
        return redirect(url_for('ekyc.view_session', session_id=session_id))

    result = EkycResult.get_for_session(session_id) or {}
    full_name = result.get('final_name') or result.get('extracted_full_name_ar')
    national_id = result.get('final_national_id') or result.get('national_id')
    if not full_name or not national_id:
        flash(gettext('Name and national ID are needed before onboarding — use Review / correct data first.'), 'warning')
        return redirect(url_for('ekyc.view_session', session_id=session_id))
    customer_id = Customer.create({
        'customer_type': 'INDIVIDUAL',
        'full_name': full_name,
        'date_of_birth': result.get('dob'),
        'nationality': 'Egypt',
        'id_type': session['document_type'],
        'id_number': national_id,
        'id_expiry_date': _expiry_date(result.get('id_expiry_raw')),
        'address': result.get('final_address') or result.get('extracted_address') or 'N/A',
        'country': 'EGYPT',
    })
    if not customer_id:
        flash(gettext('Failed to create the customer record — see server logs.'), 'danger')
        return redirect(url_for('ekyc.view_session', session_id=session_id))

    EkycSession.record_onboarding(session_id, customer_id, user_id=current_user.id)
    flash(gettext('Customer #%(customer_id)s created and session onboarded.', customer_id=customer_id), 'success')
    return redirect(url_for('ekyc.view_session', session_id=session_id))
