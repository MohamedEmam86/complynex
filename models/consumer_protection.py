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
Consumer Protection Module - Models
===================================
ComplyNex CMS - 100% Free Implementation
Compliant with Banking Law No. 194 of 2020

Features:
- Bilingual support (EN/AR)
- Statutory deadline tracking (15 days)
- CBE reporting compliance
- Audit trail
"""

from database.db import get_db
from datetime import datetime, date, timedelta
import json

class ConsumerComplaint:
    """Main complaints model"""
    
    @staticmethod
    def create(data):
        """Create a new complaint"""
        db = get_db()
        
        # Generate PIN if not provided
        if 'complaint_pin' not in data:
            import secrets
            data['complaint_pin'] = secrets.token_hex(4).upper()
            
        # Calculate deadline if not provided (15 days)
        if 'statutory_deadline_date' not in data:
            deadline = date.today() + timedelta(days=15)
            data['statutory_deadline_date'] = deadline.isoformat()
            
        cursor = db.execute("""
            INSERT INTO consumer_complaints (
                complaint_pin, customer_name, customer_email, customer_phone,
                customer_id_number, customer_type, complaint_channel,
                complaint_category, complaint_subject, complaint_description,
                statutory_deadline_date, days_remaining_to_deadline, status,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            RETURNING id
        """, (
            data['complaint_pin'], data['customer_name'], data.get('customer_email'),
            data['customer_phone'], data.get('customer_id_number'),
            data.get('customer_type', 'INDIVIDUAL'), data.get('complaint_channel', 'PUBLIC_FORM'),
            data['complaint_category'], data['complaint_subject'], data['complaint_description'],
            data['statutory_deadline_date'], data.get('days_remaining_to_deadline', 15),
            data.get('status', 'NEW')
        ))
        db.commit()

        row = cursor.fetchone()
        case_id = row['id'] if row and isinstance(row, dict) else (row[0] if row else cursor.lastrowid)

        try:
            from models.case import Case
            Case.sync_from_source('CONSUMER_COMPLAINT', case_id)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Failed to sync case registry for consumer_complaints %s', case_id)

        # Log initial submission
        ComplaintActivityLog.create({
            'complaint_id': case_id,
            'activity_type': 'SUBMISSION',
            'activity_description': f"Complaint submitted via {data.get('complaint_channel', 'PUBLIC_FORM')}",
            'new_status': data.get('status', 'NEW'),
            'performed_by': None # Performed by system/customer
        })
        
        return ConsumerComplaint.get_by_id(case_id)

    @staticmethod
    def get_by_pin(pin):
        """Get complaint by PIN"""
        db = get_db()
        row = db.execute("SELECT * FROM consumer_complaints WHERE complaint_pin = %s", (pin,)).fetchone()
        return dict(row) if row else None
        
    @staticmethod
    def get_by_ref_and_pin(ref, pin):
        """Get complaint by ID (ref) and PIN. Supports 'CP-123' or '123'"""
        db = get_db()
        
        # Clean reference number if it has CP- prefix
        clean_id = ref
        if isinstance(ref, str) and ref.upper().startswith('CP-'):
            clean_id = ref[3:]
            
        try:
            clean_id = int(clean_id)
        except (ValueError, TypeError):
            return None

        row = db.execute(
            "SELECT * FROM consumer_complaints WHERE id = %s AND complaint_pin = %s", 
            (clean_id, pin)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_by_email_and_pin(email, pin):
        """Get complaint by Email and PIN (case-insensitive)"""
        db = get_db()
        row = db.execute(
            "SELECT * FROM consumer_complaints WHERE LOWER(customer_email) = LOWER(%s) AND complaint_pin = %s", 
            (email, pin)
        ).fetchone()
        return dict(row) if row else None
        
    @staticmethod
    def get_by_id(id):
        """Get complaint by ID"""
        db = get_db()
        row = db.execute("SELECT * FROM consumer_complaints WHERE id = %s", (id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_all(status=None, limit=100, q=None):
        """Get all complaints; q searches the reference (CP-12 / 12) or customer name."""
        db = get_db()
        query = "SELECT * FROM consumer_complaints WHERE 1=1"
        params = []
        if status:
            query += " AND status = %s"
            params.append(status)
        if q:
            ref = q.upper()
            ref = ref[3:] if ref.startswith('CP-') else ref
            if ref.strip().isdigit():
                query += " AND (id = %s OR customer_name ILIKE %s)"
                params.extend([int(ref.strip()), f'%{q}%'])
            else:
                query += " AND customer_name ILIKE %s"
                params.append(f'%{q}%')
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        
        rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    
    @staticmethod
    def update_status(id, status, user_id=None, resolution_summary=None):
        """Update complaint status (and the resolution shown to the customer, if given)."""
        db = get_db()
        db.execute(
            "UPDATE consumer_complaints SET status = %s, "
            "resolution_summary = COALESCE(%s, resolution_summary), updated_at = NOW() WHERE id = %s",
            (status, resolution_summary, id)
        )
        db.commit()
        # Resolution timestamp (for resolution-time reporting); cleared again if the complaint is reopened.
        try:
            db.execute("""UPDATE consumer_complaints SET resolved_at = CASE
                              WHEN %s IN ('RESOLVED', 'CLOSED') THEN COALESCE(resolved_at, NOW()) ELSE NULL END
                          WHERE id = %s""", (status, id))
            db.commit()
        except Exception:
            db.rollback()  # column arrives with migration 20261110_complaints_handling
        from models.case import sync_case
        sync_case('CONSUMER_COMPLAINT', id)

    @staticmethod
    def assign(id, user_id, by_user_id, reason=None):
        """Set the complaint owner; logged in the activity log and pushed to the case registry."""
        db = get_db()
        row = db.execute("SELECT assigned_to_user_id FROM consumer_complaints WHERE id = %s", (id,)).fetchone()
        if not row:
            return False
        db.execute("""UPDATE consumer_complaints SET assigned_to_user_id = %s, assigned_at = NOW(),
                          assigned_by = %s, updated_at = NOW() WHERE id = %s""", (user_id, by_user_id, id))
        db.commit()
        from models.case import sync_case
        sync_case('CONSUMER_COMPLAINT', id)
        return True

    @staticmethod
    def set_resolution_details(id, root_cause_category, redress_type, redress_amount, redress_date):
        db = get_db()
        db.execute("""UPDATE consumer_complaints SET root_cause_category = %s, redress_type = %s,
                          redress_amount = %s, redress_date = %s, updated_at = NOW() WHERE id = %s""",
                   (root_cause_category, redress_type, redress_amount, redress_date, id))
        db.commit()

    @staticmethod
    def get_stats():
        """Get dashboard stats"""
        db = get_db()
        total_open = db.execute(
            "SELECT COUNT(*) as count FROM consumer_complaints WHERE status NOT IN ('RESOLVED', 'CLOSED')"
        ).fetchone()['count']
        
        overdue = db.execute(
            "SELECT COUNT(*) as count FROM consumer_complaints WHERE statutory_deadline_date::date < CURRENT_DATE AND status NOT IN ('RESOLVED', 'CLOSED')"
        ).fetchone()['count']
        
        return {'total_open': total_open, 'overdue': overdue}

class ComplaintInternalNote:
    """Staff-only notes. Append-only (no edit/delete; enforced by a DB trigger too)."""

    @staticmethod
    def add(complaint_id, note, user_id):
        db = get_db()
        db.execute("INSERT INTO complaint_internal_notes (complaint_id, note, created_by) VALUES (%s, %s, %s)",
                   (complaint_id, note, user_id))
        db.commit()

    @staticmethod
    def list(complaint_id):
        db = get_db()
        try:
            rows = db.execute("""
                SELECT n.*, NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), '') AS author,
                       u.email AS author_email
                FROM complaint_internal_notes n LEFT JOIN users u ON u.id = n.created_by
                WHERE n.complaint_id = %s ORDER BY n.created_at DESC, n.id DESC""", (complaint_id,)).fetchall()
        except Exception:
            db.rollback()
            return []
        return [dict(r) for r in rows]


class ComplaintDocument:
    """Document model"""
    @staticmethod
    def create(data):
        db = get_db()
        db.execute("""
            INSERT INTO complaint_documents (
                complaint_id, file_name, file_path, uploaded_by, uploaded_at
            ) VALUES (%s, %s, %s, %s, NOW())
        """, (
            data['complaint_id'], data['file_name'], data['file_path'], data.get('uploaded_by', 'CUSTOMER')
        ))
        db.commit()

    @staticmethod
    def get_by_complaint_id(complaint_id):
        """Get all documents for a specific complaint"""
        db = get_db()
        rows = db.execute(
            "SELECT * FROM complaint_documents WHERE complaint_id = %s ORDER BY uploaded_at DESC",
            (complaint_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def get_by_id(doc_id):
        db = get_db()
        row = db.execute("SELECT * FROM complaint_documents WHERE id = %s", (doc_id,)).fetchone()
        return dict(row) if row else None

class ComplaintActivityLog:
    """Audit log model"""
    @staticmethod
    def create(data):
        db = get_db()
        db.execute("""
            INSERT INTO complaint_activity_log (
                complaint_id, activity_type, activity_description,
                new_status, performed_by, activity_timestamp
            ) VALUES (%s, %s, %s, %s, %s, NOW())
        """, (
            data['complaint_id'], data['activity_type'], data['activity_description'],
            data.get('new_status'), data.get('performed_by')
        ))
        db.commit()

    @staticmethod
    def get_logs(complaint_id):
        """Get activity logs for a complaint"""
        db = get_db()
        rows = db.execute("""
            SELECT l.*, (u.first_name || ' ' || u.last_name) as performed_by_name
            FROM complaint_activity_log l
            LEFT JOIN users u ON l.performed_by = u.id
            WHERE l.complaint_id = %s
            ORDER BY l.activity_timestamp DESC
        """, (complaint_id,)).fetchall()
        return [dict(row) for row in rows]

class ComplaintCategory:
    """Category model"""
    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute("SELECT * FROM complaint_categories ORDER BY display_order").fetchall()
        return [dict(row) for row in rows]
    
    @staticmethod
    def create(data):
        db = get_db()
        db.execute("""
            INSERT INTO complaint_categories (
                category_code, category_name_en, category_name_ar, display_order
            ) VALUES (%s, %s, %s, %s)
        """, (
            data['category_code'], data['category_name_en'], data['category_name_ar'], data['display_order']
        ))
        db.commit()
    
    @staticmethod
    def count():
        db = get_db()
        return db.execute("SELECT COUNT(*) as count FROM complaint_categories").fetchone()['count']

# Placeholder classes for other models to avoid import errors in __init__.py
class ComplaintCommunication: pass
class ComplaintEscalation: pass
class CBEConsumerReport: pass
