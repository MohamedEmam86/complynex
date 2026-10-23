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
Whistleblowing Module - Models
===============================
ComplyNex CMS - 100% Free Implementation

Features:
- Anonymous submission with secure tracking
- End-to-end encryption for sensitive data
- Case management workflow
- File attachment support
- Audit trail
- CBE compliance
"""

from database.db import get_db
from datetime import datetime, timedelta
import secrets
import hashlib
import base64
from cryptography.fernet import Fernet
import os
import logging

logger = logging.getLogger(__name__)

class WhistleblowingCase:
    """
    Whistleblowing case model with anonymity protection.
    """
    
    # Status options
    STATUS_SUBMITTED = 'SUBMITTED'
    STATUS_UNDER_REVIEW = 'UNDER_REVIEW'
    STATUS_INVESTIGATING = 'INVESTIGATING'
    STATUS_RESOLVED = 'RESOLVED'
    STATUS_DISMISSED = 'DISMISSED'
    
    # Severity levels
    SEVERITY_LOW = 'LOW'
    SEVERITY_MEDIUM = 'MEDIUM'
    SEVERITY_HIGH = 'HIGH'
    SEVERITY_CRITICAL = 'CRITICAL'
    
    @staticmethod
    def generate_case_number():
        """Generate unique case number: WB-YYYY-###"""
        db = get_db()
        year = datetime.now().year
        
        # Get count of cases this year
        result = db.execute(
            "SELECT COUNT(*) as count FROM whistleblowing_cases WHERE TO_CHAR(submitted_at::timestamp, 'YYYY') = %s",
            (str(year),)
        ).fetchone()
        
        count = result['count'] + 1
        return f"WB-{year}-{count:04d}"
    
    @staticmethod
    def generate_anonymous_code():
        """
        Generate memorable anonymous access code.
        Format: WB-ABC-123-XYZ

        Uses `secrets` (CSPRNG) rather than `random` — this code is the sole
        credential guarding access to an anonymous whistleblower's report.
        """
        import string

        letters1 = ''.join(secrets.choice(string.ascii_uppercase) for _ in range(3))
        numbers = ''.join(secrets.choice(string.digits) for _ in range(3))
        letters2 = ''.join(secrets.choice(string.ascii_uppercase) for _ in range(3))

        return f"WB-{letters1}-{numbers}-{letters2}"
    
    @staticmethod
    def generate_encryption_key():
        """Generate encryption key for sensitive data"""
        return Fernet.generate_key().decode()
    
    @staticmethod
    def encrypt_data(data, key):
        """Encrypt sensitive data"""
        if not data:
            return None
        f = Fernet(key.encode())
        return f.encrypt(data.encode()).decode()
    
    @staticmethod
    def decrypt_data(encrypted_data, key):
        """Decrypt sensitive data"""
        if not encrypted_data or not key:
            return None
        try:
            f = Fernet(key.encode())
            return f.decrypt(encrypted_data.encode()).decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return None
    
    @classmethod
    def create(cls, data, is_anonymous=False, submitter_id=None):
        """
        Create a new whistleblowing case.
        
        Args:
            data: Dict with case details
            is_anonymous: Boolean
            submitter_id: User ID (if not anonymous)
            
        Returns:
            Dict with case_id and anonymous_code (if anonymous)
        """
        db = get_db()
        
        # Generate unique identifiers
        case_number = cls.generate_case_number()
        anonymous_code = cls.generate_anonymous_code() if is_anonymous else None
        encryption_key = cls.generate_encryption_key() if is_anonymous else None
        
        # Encrypt email if anonymous and provided
        email = data.get('submitter_email')
        if is_anonymous and email:
            email = cls.encrypt_data(email, encryption_key)
        
        # Insert case
        # submitted_at has no DB-level default (it's a plain TEXT column, like the
        # other date fields on this table) — it must be set explicitly here, or every
        # case is stored with a NULL submitted_at, which silently breaks
        # generate_case_number()'s year-based COUNT() above (TO_CHAR(NULL, ...) never
        # matches, so the count never advances past whatever pre-existing rows already
        # had a real submitted_at, and every new case collides on the same number).
        cursor = db.execute("""
            INSERT INTO whistleblowing_cases (
                case_number, submitted_at, is_anonymous, submitter_id, submitter_name,
                submitter_email, submitter_phone, submitter_department,
                incident_type, incident_category, severity,
                incident_date, incident_location, title, description,
                evidence_description, witnesses, suspected_individuals,
                status, priority, anonymous_code, encryption_key,
                is_confidential, requires_investigation, is_urgent
            ) VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            case_number,
            1 if is_anonymous else 0,
            submitter_id,
            data.get('submitter_name') if not is_anonymous else None,
            email,
            data.get('submitter_phone'),
            data.get('submitter_department'),
            data.get('incident_type'),
            data.get('incident_category'),
            data.get('severity', cls.SEVERITY_MEDIUM),
            data.get('incident_date'),
            data.get('incident_location'),
            data.get('title'),
            data.get('description'),
            data.get('evidence_description'),
            data.get('witnesses'),
            data.get('suspected_individuals'),
            cls.STATUS_SUBMITTED,
            data.get('priority', 'NORMAL'),
            anonymous_code,
            encryption_key,
            1 if data.get('is_confidential', True) else 0,
            1 if data.get('requires_investigation', False) else 0,
            1 if data.get('is_urgent', False) else 0
        ))

        # RETURNING id is the reliable way to get the new row's id on psycopg2/Postgres
        # — cursor.lastrowid (used elsewhere in this file historically) is a SQLite-only
        # concept and silently evaluates to 0 here, which was corrupting every caller
        # that relied on the returned case_id (e.g. attachment uploads saving with the
        # wrong case association).
        case_id = cursor.fetchone()['id']
        db.commit()

        try:
            from models.case import Case
            Case.sync_from_source('WHISTLEBLOWING', case_id)
        except Exception:
            logger.exception('Failed to sync case registry for whistleblowing_cases %s', case_id)

        # Create initial update
        cls.add_update(
            case_id=case_id,
            update_type='STATUS_CHANGE',
            update_text='Case submitted',
            new_value=cls.STATUS_SUBMITTED,
            created_by=submitter_id
        )
        
        # Create anonymous access token if needed
        if is_anonymous:
            access_token = secrets.token_urlsafe(32)
            db.execute("""
                INSERT INTO whistleblowing_anonymous_tokens 
                (case_id, access_token, access_code, expires_at)
                VALUES (%s, %s, %s, %s)
            """, (
                case_id,
                access_token,
                anonymous_code,
                datetime.now() + timedelta(days=365)  # Valid for 1 year
            ))
            db.commit()
        
        return {
            'case_id': case_id,
            'case_number': case_number,
            'anonymous_code': anonymous_code,
            'access_token': access_token if is_anonymous else None
        }
    
    @staticmethod
    def add_update(case_id, update_type, update_text, old_value=None, new_value=None, created_by=None, visible_to_submitter=True):
        """Add an update/comment to a case"""
        db = get_db()
        db.execute("""
            INSERT INTO whistleblowing_updates 
            (case_id, update_type, update_text, old_value, new_value, created_by, is_visible_to_submitter, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (case_id, update_type, update_text, old_value, new_value, created_by, 1 if visible_to_submitter else 0))
        db.commit()
    
    @staticmethod
    def get_by_id(case_id, include_updates=False):
        """Get case by ID"""
        db = get_db()
        case = db.execute(
            "SELECT * FROM whistleblowing_cases WHERE id = %s",
            (case_id,)
        ).fetchone()
        
        if not case:
            return None
            
        case_dict = dict(case)
        
        if include_updates:
            updates = db.execute(
                """SELECT u.*, (users.first_name || ' ' || users.last_name) as created_by_name 
                   FROM whistleblowing_updates u
                   LEFT JOIN users ON u.created_by = users.id
                   WHERE u.case_id = %s 
                   ORDER BY u.created_at DESC""",
                (case_id,)
            ).fetchall()
            case_dict['updates'] = [dict(u) for u in updates]
            
        return case_dict
    
    @staticmethod
    def get_by_anonymous_code(anonymous_code):
        """Get case by anonymous tracking code.

        Deliberately matches ONLY the high-entropy anonymous_code, never the
        sequential, predictable case_number — the public /track endpoint uses
        this lookup, and accepting case_number there would let anyone enumerate
        every case (including non-anonymous ones) just by walking WB-YYYY-#### values.
        """
        db = get_db()

        case = db.execute(
            """SELECT * FROM whistleblowing_cases
               WHERE anonymous_code = %s""",
            (anonymous_code,)
        ).fetchone()

        if not case:
            return None

        return case

    @staticmethod
    def _get_by_anonymous_code_legacy(anonymous_code):
        """Legacy stub - kept for compatibility"""
        return None
            
        # Update access stats
        db.execute("""
            UPDATE whistleblowing_anonymous_tokens 
            SET last_accessed = NOW(), access_count = access_count + 1
            WHERE access_code = %s
        """, (anonymous_code,))
        db.commit()
        
        return WhistleblowingCase.get_by_id(token_info['case_id'], include_updates=True)
    
    @staticmethod
    def update_status(case_id, new_status, updated_by, note=None):
        """Update case status"""
        db = get_db()
        
        # Get old status
        case = db.execute("SELECT status FROM whistleblowing_cases WHERE id = %s", (case_id,)).fetchone()
        if not case:
            return False
            
        old_status = case['status']
        
        # Update status
        db.execute(
            "UPDATE whistleblowing_cases SET status = %s, updated_at = NOW() WHERE id = %s",
            (new_status, case_id)
        )
        db.commit()
        
        # Log update
        WhistleblowingCase.add_update(
            case_id=case_id,
            update_type='STATUS_CHANGE',
            update_text=note or f'Status changed from {old_status} to {new_status}',
            old_value=old_status,
            new_value=new_status,
            created_by=updated_by,
            visible_to_submitter=True
        )
        
        return True
    
    @staticmethod
    def assign_case(case_id, assigned_to, assigned_by, note=None):
        """Assign case to an investigator"""
        db = get_db()
        
        db.execute("""
            UPDATE whistleblowing_cases 
            SET assigned_to = %s, assigned_at = NOW(), updated_at = NOW()
            WHERE id = %s
        """, (assigned_to, case_id))
        
        # Log assignment
        db.execute("""
            INSERT INTO whistleblowing_assignments 
            (case_id, assigned_to, assigned_by, assignment_note)
            VALUES (%s, %s, %s, %s)
        """, (case_id, assigned_to, assigned_by, note))
        
        db.commit()
        
        # Add update
        WhistleblowingCase.add_update(
            case_id=case_id,
            update_type='ASSIGNMENT',
            update_text=note or 'Case assigned for investigation',
            created_by=assigned_by,
            visible_to_submitter=False  # Don't reveal investigator to anonymous submitter
        )
        
        return True
    
    @staticmethod
    def resolve_case(case_id, resolution_summary, resolution_action, resolved_by):
        """Resolve a case"""
        db = get_db()
        
        db.execute("""
            UPDATE whistleblowing_cases 
            SET status = %s, resolution_summary = %s, resolution_action = %s,
                resolved_at = NOW(), resolved_by = %s, updated_at = NOW()
            WHERE id = %s
        """, (WhistleblowingCase.STATUS_RESOLVED, resolution_summary, resolution_action, resolved_by, case_id))
        db.commit()
        
        # Add update
        WhistleblowingCase.add_update(
            case_id=case_id,
            update_type='RESOLUTION',
            update_text='Case resolved',
            new_value='RESOLVED',
            created_by=resolved_by,
            visible_to_submitter=True
        )
        
        return True
    
    @staticmethod
    def get_all_cases(filters=None, limit=100, offset=0):
        """Get all cases with optional filters"""
        db = get_db()
        
        query = """
            SELECT c.*, 
                   (submitter.first_name || ' ' || submitter.last_name) as submitter_name_real,
                   (assigned.first_name || ' ' || assigned.last_name) as assigned_to_name,
                   (resolver.first_name || ' ' || resolver.last_name) as resolved_by_name
            FROM whistleblowing_cases c
            LEFT JOIN users submitter ON c.submitter_id = submitter.id
            LEFT JOIN users assigned ON c.assigned_to = assigned.id
            LEFT JOIN users resolver ON c.resolved_by = resolver.id
            WHERE 1=1
        """
        
        params = []
        
        if filters:
            if filters.get('status'):
                query += " AND c.status = %s"
                params.append(filters['status'])
            if filters.get('incident_type'):
                query += " AND c.incident_type = %s"
                params.append(filters['incident_type'])
            if filters.get('severity'):
                query += " AND c.severity = %s"
                params.append(filters['severity'])
            if filters.get('assigned_to'):
                query += " AND c.assigned_to = %s"
                params.append(filters['assigned_to'])
                
        query += " ORDER BY c.submitted_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cases = db.execute(query, params).fetchall()
        return [dict(c) for c in cases]
    
    @staticmethod
    def get_statistics():
        """Get whistleblowing statistics"""
        db = get_db()
        
        stats = {
            'total_cases': 0,
            'anonymous_cases': 0,
            'open_cases': 0,
            'resolved_cases': 0,
            'pending_cases': 0,
            'investigating_cases': 0,
            'avg_resolution_days': 0,
            'by_type': {},
            'by_severity': {},
            'by_status': {}
        }
        
        # Total cases
        result = db.execute("SELECT COUNT(*) as count FROM whistleblowing_cases").fetchone()
        stats['total_cases'] = result['count']
        
        # Anonymous
        result = db.execute("SELECT COUNT(*) as count FROM whistleblowing_cases WHERE is_anonymous = 1").fetchone()
        stats['anonymous_cases'] = result['count']
        
        # Open cases
        result = db.execute(
            "SELECT COUNT(*) as count FROM whistleblowing_cases WHERE status NOT IN ('RESOLVED', 'DISMISSED')"
        ).fetchone()
        stats['open_cases'] = result['count']
        
        # Resolved
        result = db.execute("SELECT COUNT(*) as count FROM whistleblowing_cases WHERE status = 'RESOLVED'").fetchone()
        stats['resolved_cases'] = result['count']

        # Dashboard cards: waiting for triage vs. under investigation
        result = db.execute(
            "SELECT COUNT(*) as count FROM whistleblowing_cases WHERE status IN ('SUBMITTED', 'UNDER_REVIEW')"
        ).fetchone()
        stats['pending_cases'] = result['count']
        result = db.execute("SELECT COUNT(*) as count FROM whistleblowing_cases WHERE status = 'INVESTIGATING'").fetchone()
        stats['investigating_cases'] = result['count']

        # Average resolution time
        result = db.execute("""
            SELECT AVG(EXTRACT(EPOCH FROM (resolved_at::timestamp - submitted_at::timestamp))/86400) as avg_days
            FROM whistleblowing_cases
            WHERE resolved_at IS NOT NULL
        """).fetchone()
        stats['avg_resolution_days'] = round(result['avg_days'], 1) if result['avg_days'] else 0
        
        # By type
        results = db.execute("""
            SELECT incident_type, COUNT(*) as count 
            FROM whistleblowing_cases 
            GROUP BY incident_type
        """).fetchall()
        stats['by_type'] = {r['incident_type']: r['count'] for r in results}
        
        # By severity
        results = db.execute("""
            SELECT severity, COUNT(*) as count 
            FROM whistleblowing_cases 
            GROUP BY severity
        """).fetchall()
        stats['by_severity'] = {r['severity']: r['count'] for r in results}
        
        # By status
        results = db.execute("""
            SELECT status, COUNT(*) as count 
            FROM whistleblowing_cases 
            GROUP BY status
        """).fetchall()
        stats['by_status'] = {r['status']: r['count'] for r in results}
        
        return stats


class WhistleblowingAttachment:
    """File attachment model with encryption"""
    
    @staticmethod
    def save_attachment(case_id, file, uploaded_by=None, description=None):
        """
        Save an encrypted file attachment.
        
        Args:
            case_id: Case ID
            file: FileStorage object from Flask
            uploaded_by: User ID (optional for anonymous)
            description: File description
            
        Returns:
            attachment_id
        """
        from werkzeug.utils import secure_filename
        
        # Generate secure filename
        original_filename = secure_filename(file.filename)
        file_ext = os.path.splitext(original_filename)[1]
        encrypted_filename = f"{secrets.token_urlsafe(16)}{file_ext}"
        
        # Create upload directory if not exists
        upload_dir = os.path.join('uploads', 'whistleblowing', str(case_id))
        os.makedirs(upload_dir, exist_ok=True)
        
        file_path = os.path.join(upload_dir, encrypted_filename)
        
        # Generate encryption key
        encryption_key = Fernet.generate_key()
        
        # Read and encrypt file content
        file_content = file.read()
        f = Fernet(encryption_key)
        encrypted_content = f.encrypt(file_content)
        
        # Save encrypted file
        with open(file_path, 'wb') as f:
            f.write(encrypted_content)
        
        # Save to database
        db = get_db()
        cursor = db.execute("""
            INSERT INTO whistleblowing_attachments 
            (case_id, filename, original_filename, file_path, file_size, file_type,
             uploaded_by, is_encrypted, encryption_key, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
            RETURNING id
        """, (
            case_id,
            encrypted_filename,
            original_filename,
            file_path,
            len(file_content),
            file.content_type,
            uploaded_by,
            encryption_key.decode(),
            description
        ))
        db.commit()

        return cursor.fetchone()['id']
    
    @staticmethod
    def get_attachment(attachment_id):
        """Get attachment metadata"""
        db = get_db()
        return db.execute(
            "SELECT * FROM whistleblowing_attachments WHERE id = %s",
            (attachment_id,)
        ).fetchone()
    
    @staticmethod
    def decrypt_attachment(attachment_id):
        """
        Decrypt and return file content.
        
        Returns:
            (file_content, original_filename, mime_type)
        """
        attachment = WhistleblowingAttachment.get_attachment(attachment_id)
        if not attachment:
            return None, None, None
            
        # Read encrypted file
        with open(attachment['file_path'], 'rb') as f:
            encrypted_content = f.read()
        
        # Decrypt
        encryption_key = attachment['encryption_key'].encode()
        fernet = Fernet(encryption_key)
        decrypted_content = fernet.decrypt(encrypted_content)
        
        return decrypted_content, attachment['original_filename'], attachment['file_type']


class WhistleblowingCategory:
    """Category management"""
    
    @staticmethod
    def get_all_categories():
        """Get all active categories"""
        db = get_db()
        categories = db.execute("""
            SELECT * FROM whistleblowing_categories 
            WHERE is_active = 1 
            ORDER BY display_order, category_name_en
        """).fetchall()
        return [dict(c) for c in categories]
    
    @staticmethod
    def get_category(category_code):
        """Get single category"""
        db = get_db()
        return db.execute(
            "SELECT * FROM whistleblowing_categories WHERE category_code = %s",
            (category_code,)
        ).fetchone()
