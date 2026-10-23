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
Data access for the eKYC module: ekyc_session, ekyc_document, ekyc_result, ekyc_audit_log.
Mirrors the raw-SQL/psycopg2 conventions used elsewhere in the app (see models/audit.py).
"""
import json
import secrets
from datetime import datetime, timedelta

from database.db import get_db


class EkycConfig:
    """Editable risk-fusion thresholds/weights, mirroring screening_config's key-value pattern."""

    _DEFAULTS = {
        'risk_threshold_pass': 80.0,
        'risk_threshold_review': 55.0,
        'weight_ocr': 0.20,
        'weight_face_match': 0.30,
        'weight_passive_liveness': 0.15,
        'weight_active_liveness': 0.15,
        'weight_document_pad': 0.20,
    }

    @classmethod
    def get_float(cls, key):
        db = get_db()
        row = db.execute('SELECT config_value FROM ekyc_config WHERE config_key = %s', (key,)).fetchone()
        if row:
            return float(row['config_value'])
        return cls._DEFAULTS[key]

    @classmethod
    def get_all_weights(cls):
        return {
            'ocr': cls.get_float('weight_ocr'),
            'face_match': cls.get_float('weight_face_match'),
            'passive_liveness': cls.get_float('weight_passive_liveness'),
            'active_liveness': cls.get_float('weight_active_liveness'),
            'document_pad': cls.get_float('weight_document_pad'),
        }


class EkycAuditLog:
    """Fine-grained, session-scoped audit trail for eKYC actions (consent, capture, decision, access)."""

    @staticmethod
    def log(session_id, action, user_id=None, details=None, ip_address=None):
        db = get_db()
        db.execute('''
            INSERT INTO ekyc_audit_log (session_id, user_id, action, details, ip_address)
            VALUES (%s, %s, %s, %s, %s)
        ''', (session_id, user_id, action, details, ip_address))
        db.commit()

    @staticmethod
    def get_for_session(session_id):
        db = get_db()
        rows = db.execute('''
            SELECT a.*, u.first_name || ' ' || u.last_name AS user_name
            FROM ekyc_audit_log a
            LEFT JOIN users u ON a.user_id = u.id
            WHERE a.session_id = %s
            ORDER BY a.created_at ASC
        ''', (session_id,)).fetchall()
        return [dict(r) for r in rows]


class EkycSession:
    """A single eKYC verification attempt, from consent through decision."""

    DEFAULT_SESSION_LIFETIME_HOURS = 2
    # How long raw captured media is retained before being purged (PDPL data-minimization).
    DEFAULT_MEDIA_RETENTION_DAYS = 30

    @staticmethod
    def create(document_type='NATIONAL_ID', customer_reference=None, created_by=None, locale='ar'):
        db = get_db()
        token = secrets.token_urlsafe(32)
        now = datetime.now()
        expires_at = now + timedelta(hours=EkycSession.DEFAULT_SESSION_LIFETIME_HOURS)
        retention_expires_at = now + timedelta(days=EkycSession.DEFAULT_MEDIA_RETENTION_DAYS)
        db.execute('''
            INSERT INTO ekyc_session
                (session_token, customer_reference, document_type, status, locale,
                 created_by, expires_at, retention_expires_at)
            VALUES (%s, %s, %s, 'CREATED', %s, %s, %s, %s)
        ''', (token, customer_reference, document_type, locale, created_by, expires_at, retention_expires_at))
        db.commit()
        session = EkycSession.get_by_token(token)
        EkycAuditLog.log(session['id'], 'SESSION_CREATED', user_id=created_by,
                          details=f'document_type={document_type}')
        return session

    @staticmethod
    def get_by_token(token):
        db = get_db()
        row = db.execute('SELECT * FROM ekyc_session WHERE session_token = %s', (token,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_by_id(session_id):
        db = get_db()
        row = db.execute('SELECT * FROM ekyc_session WHERE id = %s', (session_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_all(limit=200):
        db = get_db()
        rows = db.execute('''
            SELECT s.*, r.decision, r.risk_score, u.first_name || ' ' || u.last_name AS created_by_name
            FROM ekyc_session s
            LEFT JOIN ekyc_result r ON r.session_id = s.id
            LEFT JOIN users u ON s.created_by = u.id
            ORDER BY s.created_at DESC
            LIMIT %s
        ''', (limit,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def is_expired(session):
        if not session.get('expires_at'):
            return False
        return datetime.now() > session['expires_at']

    @staticmethod
    def record_consent(session_id, consent_text, ip_address, declared_national_id=None, declared_name_ar=None):
        """declared_*: what the customer typed on the consent page — used by
        ekyc/pipeline.py when the card cannot be read, and cross-checked
        against the card read when it can."""
        db = get_db()
        db.execute('''
            UPDATE ekyc_session
            SET consent_given = TRUE, consent_text = %s, consent_given_at = CURRENT_TIMESTAMP,
                consent_ip = %s, status = 'CONSENT_GIVEN', updated_at = CURRENT_TIMESTAMP,
                declared_national_id = %s, declared_name_ar = %s,
                declared_at = CASE WHEN %s IS NULL AND %s IS NULL THEN NULL ELSE CURRENT_TIMESTAMP END
            WHERE id = %s
        ''', (consent_text, ip_address, declared_national_id, declared_name_ar,
              declared_national_id, declared_name_ar, session_id))
        db.commit()
        EkycAuditLog.log(session_id, 'CONSENT_GIVEN', details=consent_text[:200], ip_address=ip_address)

    @staticmethod
    def update_status(session_id, status, error_message=None, user_id=None, ip_address=None):
        db = get_db()
        db.execute('''
            UPDATE ekyc_session
            SET status = %s, error_message = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (status, error_message, session_id))
        db.commit()
        EkycAuditLog.log(session_id, f'STATUS_{status}', user_id=user_id,
                          details=error_message, ip_address=ip_address)

    @staticmethod
    def update_details(session_id, document_type, customer_reference, locale, user_id=None):
        """Edits the session's form fields (document type, customer reference, locale)."""
        db = get_db()
        db.execute('''
            UPDATE ekyc_session
            SET document_type = %s, customer_reference = %s, locale = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (document_type, customer_reference, locale, session_id))
        db.commit()
        EkycAuditLog.log(session_id, 'SESSION_EDITED', user_id=user_id,
                          details=f'document_type={document_type}, locale={locale}')

    @staticmethod
    def update_customer_reference(session_id, customer_reference, user_id=None):
        """
        Sets/corrects the free-text customer reference independently of
        update_details() above — unlike document_type/locale (which the
        capture flow already depends on and must stay locked once
        submitted, see POST_SUBMISSION_STATUSES), this label has no bearing
        on capture/OCR and is exactly the thing staff want to fill in once
        they're reviewing/deciding the case, i.e. after it's already
        post-submission and the regular edit form is locked.
        """
        db = get_db()
        db.execute('''
            UPDATE ekyc_session SET customer_reference = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (customer_reference, session_id))
        db.commit()
        EkycAuditLog.log(session_id, 'CUSTOMER_REFERENCE_UPDATED', user_id=user_id,
                          details=f'customer_reference={customer_reference}')

    @staticmethod
    def list_needs_review(limit=200):
        """
        The 'needs an officer to correct/confirm extracted data' queue —
        deliberately reviewed_at IS NULL, not just status='NEEDS_REVIEW':
        a session also lands in NEEDS_REVIEW when a screening hit is still
        pending disposition (see ekyc/pipeline.py), which is a different
        queue entirely (the existing /screening/queue UI) — without this
        filter, an already-corrected session would reappear here every time
        it's re-evaluated while still waiting on a screening disposition.
        """
        db = get_db()
        rows = db.execute('''
            SELECT s.*, r.decision AS ai_decision, r.risk_score, r.screening_result,
                   u.first_name || ' ' || u.last_name AS assigned_to_name
            FROM ekyc_session s
            LEFT JOIN ekyc_result r ON r.session_id = s.id
            LEFT JOIN users u ON s.assigned_to = u.id
            WHERE s.status = 'NEEDS_REVIEW' AND s.reviewed_at IS NULL
            ORDER BY s.updated_at ASC
            LIMIT %s
        ''', (limit,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def list_decision_pending(limit=200):
        db = get_db()
        rows = db.execute('''
            SELECT s.*, r.decision AS ai_decision, r.risk_score, r.screening_result
            FROM ekyc_session s
            LEFT JOIN ekyc_result r ON r.session_id = s.id
            WHERE s.status = 'DECISION_PENDING'
            ORDER BY s.updated_at ASC
            LIMIT %s
        ''', (limit,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def assign_reviewer(session_id, assigned_to, user_id=None):
        db = get_db()
        db.execute('UPDATE ekyc_session SET assigned_to = %s WHERE id = %s', (assigned_to, session_id))
        db.commit()
        EkycAuditLog.log(session_id, 'REVIEW_ASSIGNED', user_id=user_id, details=f'assigned_to={assigned_to}')

    @staticmethod
    def record_review(session_id, user_id, notes=None, new_status=None):
        """
        Marks a NEEDS_REVIEW session as reviewed by a compliance officer.
        new_status is the caller's decision on where the session goes next
        (e.g. DECISION_PENDING once screening is clear, or NEEDS_REVIEW still
        if a screening hit is now pending) — left to the caller rather than
        decided here since that depends on what the review submit actually
        changed (corrected fields, re-run screening).
        """
        db = get_db()
        db.execute('''
            UPDATE ekyc_session SET reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (user_id, session_id))
        db.commit()
        EkycAuditLog.log(session_id, 'MANUAL_REVIEW_SUBMITTED', user_id=user_id, details=notes)
        if new_status:
            EkycSession.update_status(session_id, new_status, user_id=user_id)

    @staticmethod
    def record_decision(session_id, decision, user_id, notes=None):
        """decision is 'APPROVED' or 'REJECTED' — the officer's final call, distinct
        from ekyc_result.decision (the pipeline's own PASS/REVIEW/FAIL)."""
        db = get_db()
        db.execute('''
            UPDATE ekyc_session
            SET final_decision = %s, decision_by = %s, decided_at = CURRENT_TIMESTAMP,
                decision_notes = %s, status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (decision, user_id, notes, decision, session_id))
        db.commit()
        EkycAuditLog.log(session_id, 'DECISION_RECORDED', user_id=user_id,
                          details=f'final_decision={decision} notes={notes}')

    @staticmethod
    def clear_decision(session_id, user_id=None):
        """Withdraws a final decision after the officer corrected the data,
        so the session must be approved again on the corrected values."""
        db = get_db()
        db.execute('''
            UPDATE ekyc_session SET final_decision = NULL, decision_by = NULL, decided_at = NULL,
                   decision_notes = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (session_id,))
        db.commit()
        EkycAuditLog.log(session_id, 'DECISION_WITHDRAWN', user_id=user_id,
                          details='data corrected after approval')

    @staticmethod
    def record_onboarding(session_id, customer_id, user_id=None):
        db = get_db()
        db.execute('''
            UPDATE ekyc_session SET onboarded_customer_id = %s, status = 'ONBOARDED', updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (customer_id, session_id))
        db.commit()
        EkycAuditLog.log(session_id, 'ONBOARDED', user_id=user_id, details=f'customer_id={customer_id}')

    @staticmethod
    def regenerate_link(session_id, user_id=None, ip_address=None):
        """
        Issues a fresh one-time token and resets the session back to its
        pre-consent state, invalidating the old link — used when a customer
        couldn't complete the original link (e.g. camera/permission issue)
        and staff need to resend a working one without losing the audit
        trail or any documents already captured under this session.
        """
        db = get_db()
        new_token = secrets.token_urlsafe(32)
        now = datetime.now()
        expires_at = now + timedelta(hours=EkycSession.DEFAULT_SESSION_LIFETIME_HOURS)
        db.execute('''
            UPDATE ekyc_session
            SET session_token = %s, status = 'CREATED', consent_given = FALSE,
                consent_text = NULL, consent_given_at = NULL, consent_ip = NULL,
                error_message = NULL, expires_at = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (new_token, expires_at, session_id))
        db.commit()
        EkycAuditLog.log(session_id, 'LINK_REGENERATED', user_id=user_id, ip_address=ip_address)
        return EkycSession.get_by_id(session_id)


class EkycDocument:
    """A captured media artifact (ID video, selfie video) linked to a session."""

    @staticmethod
    def create(session_id, doc_role, stored_path, encryption_key_id, checksum_sha256=None,
               file_size=None, mime_type=None, client_ocr_hint=None):
        """
        client_ocr_hint: optional dict ({national_id, raw_text, confidence}, see
        static/ekyc/js/capture.js's readIdHint()) — the browser's draft-only
        OCR read of this exact frame, kept alongside it purely for officer
        cross-reference (ekyc/pipeline.py, templates/ekyc/review_detail.html).
        Never used as an input to OCR/decision logic — see EKYC_MODULE.md.
        """
        db = get_db()
        hint_json = json.dumps(client_ocr_hint) if client_ocr_hint is not None else None
        cur = db.execute('''
            INSERT INTO ekyc_document
                (session_id, doc_role, stored_path, encryption_key_id, checksum_sha256, file_size, mime_type,
                 client_ocr_hint)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (session_id, doc_role, stored_path, encryption_key_id, checksum_sha256, file_size, mime_type,
              hint_json))
        new_id = cur.fetchone()['id']
        db.commit()
        EkycAuditLog.log(session_id, 'DOCUMENT_CAPTURED', details=f'doc_role={doc_role}')
        return new_id

    @staticmethod
    def list_for_session(session_id):
        db = get_db()
        rows = db.execute('''
            SELECT * FROM ekyc_document WHERE session_id = %s ORDER BY captured_at ASC
        ''', (session_id,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_by_id(document_id):
        db = get_db()
        row = db.execute('SELECT * FROM ekyc_document WHERE id = %s', (document_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def mark_purged(document_id):
        db = get_db()
        db.execute('UPDATE ekyc_document SET purged_at = CURRENT_TIMESTAMP WHERE id = %s', (document_id,))
        db.commit()


class EkycResult:
    """The fused outcome of a session's verification pipeline."""

    @staticmethod
    def upsert(session_id, **fields):
        db = get_db()
        existing = db.execute('SELECT id FROM ekyc_result WHERE session_id = %s', (session_id,)).fetchone()
        fields['session_id'] = session_id
        columns = list(fields.keys())
        if existing:
            set_clause = ', '.join(f'{c} = %s' for c in columns)
            db.execute(f'UPDATE ekyc_result SET {set_clause} WHERE session_id = %s',
                       tuple(fields.values()) + (session_id,))
        else:
            col_clause = ', '.join(columns)
            placeholders = ', '.join(['%s'] * len(columns))
            db.execute(f'INSERT INTO ekyc_result ({col_clause}) VALUES ({placeholders})',
                       tuple(fields.values()))
        db.commit()
        EkycAuditLog.log(session_id, 'RESULT_RECORDED', details=f"decision={fields.get('decision')}")

    @staticmethod
    def get_for_session(session_id):
        db = get_db()
        row = db.execute('SELECT * FROM ekyc_result WHERE session_id = %s', (session_id,)).fetchone()
        return dict(row) if row else None
