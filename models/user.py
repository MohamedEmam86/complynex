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
User model for ComplyNex CMS
Handles user authentication and role-based permissions
"""
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import bcrypt
import re
from datetime import datetime


class User(UserMixin):
    """
    User model with role-based access control.
    
    Roles:
        - admin: Full system access
        - compliance_officer: Can approve high-value GHE, manage policies, manage users
        - compliance_manager: Full read/approval access, NO user/settings management
        - manager: Can approve team GHE (500-2000 EGP)
        - employee: Basic access to submit declarations
    """
    
    def __init__(self, id, email, password_hash, first_name, last_name, 
                 role='employee', is_active=True, employee_id=None, expires_at=None, is_temporary=False,
                 department=None, department_id=None, job_title=None, manager_id=None,
                 last_login=None, created_at=None, updated_at=None,
                 cms_access_level='none', profile_picture=None,
                 perm_governance='none', perm_aml='none', perm_policies='none',
                 perm_reports='none', perm_pdpl='none', perm_training='none',
                 perm_screening='none', perm_config='none', perm_cyber='none',
                 perm_consumer_protection='none', perm_whistleblowing='none',
                 perm_ghe='none', perm_coi='none', perm_cobec='none',
                 perm_merchant_kyc='none', perm_tm='none', perm_ekyc='none',
                 perm_risk_management='none', perm_internal_audit='none',
                 perm_esg='none', perm_carbon='none',
                 can_assign_training=False,
                 mfa_secret=None, mfa_enabled=False, mfa_backup_codes=None,
                 mfa_required_override=None,
                 **kwargs):
        self.id = id
        self.email = email
        self.password_hash = password_hash
        self.first_name = first_name
        self.last_name = last_name
        self.role = role
        self._is_active = is_active
        self.profile_picture = profile_picture
        self.expires_at = expires_at
        self.is_temporary = is_temporary
        self.employee_id = employee_id
        self.department = department
        self.department_id = department_id
        self.job_title = job_title
        self.manager_id = manager_id
        self.last_login = last_login
        self.created_at = created_at
        self.updated_at = updated_at
        self.cms_access_level = cms_access_level
        self.perm_governance = perm_governance
        self.perm_aml = perm_aml
        self.perm_policies = perm_policies
        self.perm_reports = perm_reports
        self.perm_pdpl = perm_pdpl
        self.perm_training = perm_training
        self.perm_screening = perm_screening
        self.perm_config = perm_config
        self.perm_cyber = perm_cyber
        self.perm_consumer_protection = perm_consumer_protection
        self.perm_whistleblowing = perm_whistleblowing
        self.perm_ghe = perm_ghe
        self.perm_coi = perm_coi
        self.perm_cobec = perm_cobec
        self.perm_merchant_kyc = perm_merchant_kyc
        self.perm_tm = perm_tm
        self.perm_ekyc = perm_ekyc
        self.perm_risk_management = perm_risk_management
        self.perm_internal_audit = perm_internal_audit
        self.perm_esg = perm_esg
        self.perm_carbon = perm_carbon
        self.can_assign_training = bool(can_assign_training)
        self.mfa_secret = mfa_secret
        self.mfa_enabled = bool(mfa_enabled)
        self.mfa_required_override = mfa_required_override
        self.mfa_backup_codes = mfa_backup_codes

    @property
    def is_active(self):
        """Required by Flask-Login. Returns whether the user account is active."""
        return self._is_active
    
    @property
    def username(self):
        """Mocked username property returning email for compatibility."""
        return self.email
    
    def get_full_name(self):
        """Return user's full name."""
        return f"{self.first_name} {self.last_name}"
    
    def get_initials(self):
        """Return user's initials for avatar."""
        return f"{self.first_name[0]}{self.last_name[0]}".upper()
    
    def is_admin(self):
        """Check if user has admin role."""
        return self.role == 'admin'
    
    def is_compliance_officer(self):
        """Check if user can perform compliance officer actions (Approve, View Reports)."""
        return self.role in ['admin', 'compliance_officer', 'compliance_manager']

    def can_manage_users(self):
        """Check if user can add/edit/delete other users."""
        return self.role in ['admin', 'compliance_officer']
    
    def is_manager(self):
        """Check if user can perform manager actions."""
        return self.role in ['admin', 'manager', 'compliance_manager'] # Compliance Manager also acts as a manager

    def can_manage_training(self):
        """Check if user can access training assignment/reporting features.
        Compliance officers always can; other users need explicit assignment authority."""
        return self.is_compliance_officer() or bool(self.can_assign_training)

    def can_assign_training_to(self, target_user):
        """Check if this user may assign/enroll training for target_user.
        Compliance officers can assign to anyone; managers with explicit authority
        are limited to users in departments they have access to."""
        if not target_user:
            return False
        if self.is_compliance_officer():
            return True
        if self.can_assign_training:
            return self.has_department_access(target_user.department_id)
        return False

    def can_access_cms(self):
        """Check if user is allowed to access the CMS backend."""
        # Admins and Officers always have access
        if self.is_compliance_officer():
            return True
        # Others need explicit access level
        return self.cms_access_level in ['view', 'edit']

    def can_edit_cms(self):
        """Check if user has write access to CMS data."""
        if self.is_compliance_officer():
            return True
        return self.cms_access_level == 'edit'
    
    def can_approve_ghe(self, amount):
        """
        Check if user can approve GHE of given amount.
        
        Args:
            amount: GHE amount in EGP
        
        Returns:
            bool: True if user can approve
        """
        if self.is_admin() or self.is_compliance_officer():
            return True
        if self.is_manager() and amount <= 2000:
            return True
        return False
        
    def get_accessible_departments(self):
        """
        Returns a list of department IDs this user has access to.
        Including their primary department and any additional assigned departments.
        """
        from database.db import get_db
        db = get_db()
        
        # Start with primary department
        dept_ids = {self.department_id} if self.department_id else set()
        
        # Get additional departments from user_departments table
        rows = db.execute('SELECT department_id FROM user_departments WHERE user_id = %s', (self.id,)).fetchall()
        for row in rows:
            dept_ids.add(row['department_id'])
            
        return list(dept_ids)

    def has_department_access(self, dept_id):
        """Check if user has access to a specific department."""
        if not dept_id: return False
        if self.is_admin(): return True # Admins access all
        
        return int(dept_id) in self.get_accessible_departments()
    
    def check_password(self, password):
        """Verify password against stored hash (Legacy wrapper)."""
        return self.verify_password(password)

    @staticmethod
    def hash_password(password):
        """
        Hash a password using bcrypt
        """
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def verify_password(self, password):
        """
        Verify a password against stored hash.
        Supports both bcrypt (new) and werkzeug (legacy) hashes.
        """
        if not self.password_hash:
            return False
            
        # Check if it's a bcrypt hash
        if self.password_hash.startswith('$2b$'):
            return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
            
        # Fallback to legacy werkzeug hash
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def validate_password_strength(password):
        """
        Validate password meets security requirements (CBE Compliant)
        """
        if len(password) < 12:
            return False, "Password must be at least 12 characters long"
        
        if not re.search(r'[A-Z]', password):
            return False, "Password must contain at least one uppercase letter"
        
        if not re.search(r'[a-z]', password):
            return False, "Password must contain at least one lowercase letter"
        
        if not re.search(r'\d', password):
            return False, "Password must contain at least one number"
        
        if not re.search(r'[!@#$%^&*(),.%s":{}|<>]', password):
            return False, "Password must contain at least one special character"
            
        return True, "Password is valid"

    def _get_perm(self, module):
        """Helper to get permission for a module, admin gets 'edit'."""
        if self.is_admin():
            return 'edit'
        attr = f'perm_{module}'
        return getattr(self, attr, 'none')

    def can_view(self, module):
        """Check if user can view a specific module."""
        return self._get_perm(module) in ['view', 'edit']

    def can_edit(self, module):
        """Check if user can edit a specific module."""
        return self._get_perm(module) == 'edit'
    
    def has_permission(self, module, level='view'):
        """Convenience wrapper for permission checks."""
        if level == 'edit':
            return self.can_edit(module)
        return self.can_view(module)
    
    @staticmethod
    def get_by_id(user_id):
        """Fetch user by ID from database."""
        from database.db import get_db
        db = get_db()
        row = db.execute(
            'SELECT * FROM users WHERE id = %s', (user_id,)
        ).fetchone()
        
        if row:
            return User._from_row(row)
        return None
    
    @staticmethod
    def get_by_email(email):
        """Fetch user by email from database."""
        from database.db import get_db
        db = get_db()
        row = db.execute(
            'SELECT * FROM users WHERE email = %s', (email,)
        ).fetchone()
        
        if row:
            return User._from_row(row)
        return None
    
    @staticmethod
    def create_user(email, password, first_name, last_name, role='employee',
                    employee_id=None, department=None, job_title=None, manager_id=None,
                    cms_access_level='none', **kwargs):
        """Create a new user in the database."""
        from database.db import get_db
        
        if User.get_by_email(email):
            raise ValueError(f"Email {email} already exists")
        
        password_hash = User.hash_password(password)
        db = get_db()

        # Extract permissions
        perm_governance = kwargs.get('perm_governance', 'none')
        perm_aml = kwargs.get('perm_aml', 'none')
        perm_policies = kwargs.get('perm_policies', 'none')
        perm_reports = kwargs.get('perm_reports', 'none')
        perm_pdpl = kwargs.get('perm_pdpl', 'none')
        perm_training = kwargs.get('perm_training', 'none')
        perm_screening = kwargs.get('perm_screening', 'none')
        perm_config = kwargs.get('perm_config', 'none')
        perm_cyber = kwargs.get('perm_cyber', 'none')
        perm_consumer_protection = kwargs.get('perm_consumer_protection', 'none')
        perm_whistleblowing = kwargs.get('perm_whistleblowing', 'none')
        perm_ghe = kwargs.get('perm_ghe', 'none')
        perm_coi = kwargs.get('perm_coi', 'none')
        perm_cobec = kwargs.get('perm_cobec', 'none')
        perm_merchant_kyc = kwargs.get('perm_merchant_kyc', 'none')
        perm_tm = kwargs.get('perm_tm', 'none')
        perm_ekyc = kwargs.get('perm_ekyc', 'none')
        perm_risk_management = kwargs.get('perm_risk_management', 'none')
        perm_internal_audit = kwargs.get('perm_internal_audit', 'none')
        perm_esg = kwargs.get('perm_esg', 'none')
        perm_carbon = kwargs.get('perm_carbon', 'none')

        cursor = db.execute(
            '''INSERT INTO users
               (email, password_hash, first_name, last_name, role,
                employee_id, department, job_title, manager_id, cms_access_level,
                perm_governance, perm_aml, perm_policies, perm_reports, perm_pdpl,
                perm_training, perm_screening, perm_config, perm_cyber,
                perm_consumer_protection, perm_whistleblowing,
                perm_ghe, perm_coi, perm_cobec, perm_merchant_kyc, perm_tm, perm_ekyc,
                perm_risk_management, perm_internal_audit, perm_esg, perm_carbon)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (email, password_hash, first_name, last_name, role,
             employee_id, department, job_title, manager_id, cms_access_level,
             perm_governance, perm_aml, perm_policies, perm_reports, perm_pdpl,
             perm_training, perm_screening, perm_config, perm_cyber,
             perm_consumer_protection, perm_whistleblowing,
             perm_ghe, perm_coi, perm_cobec, perm_merchant_kyc, perm_tm, perm_ekyc,
             perm_risk_management, perm_internal_audit, perm_esg, perm_carbon)
        )
        db.commit()

        # Permissions added after this INSERT was written (perm_ongoing_screening,
        # perm_academy, ...) are persisted here instead of being silently dropped.
        _late = {k: v for k, v in kwargs.items()
                 if k in ('perm_ongoing_screening', 'perm_academy') and v and v != 'none'}
        if _late:
            db.execute('UPDATE users SET ' + ', '.join(f'{k} = %s' for k in _late) + ' WHERE email = %s',
                       (*_late.values(), email))
            db.commit()

        # Get the newly created user by email (more reliable than lastrowid)
        new_user = User.get_by_email(email)
        if not new_user:
            raise ValueError("User was created but could not be retrieved")
        return new_user
    
    @staticmethod
    def update_last_login(user_id):
        """Update user's last login timestamp."""
        from database.db import get_db
        db = get_db()
        db.execute(
            'UPDATE users SET last_login = %s WHERE id = %s',
            (datetime.now(), user_id)
        )
        db.commit()

    @staticmethod
    def update_user(user_id, **kwargs):
        """Update user details in database."""
        from database.db import get_db
        db = get_db()
        
        # Handle secondary departments update first if present
        if 'accessible_departments' in kwargs:
             accessible_departments = kwargs.pop('accessible_departments') # Remove from kwargs for main update
             # Clear existing assignments
             db.execute('DELETE FROM user_departments WHERE user_id = %s', (user_id,))
             # Insert new ones
             for dept_id in accessible_departments:
                 if dept_id: # ensure not None/Empty
                     db.execute('INSERT INTO user_departments (user_id, department_id) VALUES (%s, %s)', (user_id, dept_id))
        
        if not kwargs:
            db.commit()
            return User.get_by_id(user_id)
            
        fields = []
        values = []
        for key, value in kwargs.items():
            fields.append(f"{key} = %s")
            values.append(value)
        
        sql = f"UPDATE users SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
        values.append(user_id)
        
        db = get_db()
        db.execute(sql, tuple(values))
        db.commit()
    
    @staticmethod
    def _from_row(row):
        """Convert database row to User object."""
        # Handle case where cms_access_level column might not exist yet (during migration)
        # But for new code it should exist
        cms_access_level = row['cms_access_level'] if 'cms_access_level' in row.keys() else 'none'
        expires_at = row['expires_at'] if 'expires_at' in row.keys() else None
        is_temporary = row['is_temporary'] if 'is_temporary' in row.keys() else 0
        
        _u = User(
            id=row['id'],
            email=row['email'],
            password_hash=row['password_hash'],
            first_name=row['first_name'],
            last_name=row['last_name'],
            role=row['role'],
            expires_at=expires_at,
            is_temporary=is_temporary,
            is_active=bool(row['is_active']),
            employee_id=row['employee_id'],
            department=row['department'],
            department_id=row['department_id'] if 'department_id' in row.keys() else None,
            job_title=row['job_title'],
            manager_id=row['manager_id'],
            last_login=row['last_login'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            cms_access_level=cms_access_level,
            profile_picture=row['profile_picture'] if 'profile_picture' in row.keys() else None,
            perm_governance=row['perm_governance'] if 'perm_governance' in row.keys() else 'none',
            perm_aml=row['perm_aml'] if 'perm_aml' in row.keys() else 'none',
            perm_policies=row['perm_policies'] if 'perm_policies' in row.keys() else 'none',
            perm_reports=row['perm_reports'] if 'perm_reports' in row.keys() else 'none',
            perm_pdpl=row['perm_pdpl'] if 'perm_pdpl' in row.keys() else 'none',
            perm_training=row['perm_training'] if 'perm_training' in row.keys() else 'none',
            perm_screening=row['perm_screening'] if 'perm_screening' in row.keys() else 'none',
            perm_config=row['perm_config'] if 'perm_config' in row.keys() else 'none',
            perm_cyber=row['perm_cyber'] if 'perm_cyber' in row.keys() else 'none',
            perm_consumer_protection=row['perm_consumer_protection'] if 'perm_consumer_protection' in row.keys() else 'none',
            perm_whistleblowing=row['perm_whistleblowing'] if 'perm_whistleblowing' in row.keys() else 'none',
            perm_ghe=row['perm_ghe'] if 'perm_ghe' in row.keys() else 'none',
            perm_coi=row['perm_coi'] if 'perm_coi' in row.keys() else 'none',
            perm_cobec=row['perm_cobec'] if 'perm_cobec' in row.keys() else 'none',
            perm_merchant_kyc=row['perm_merchant_kyc'] if 'perm_merchant_kyc' in row.keys() else 'none',
            perm_tm=row['perm_tm'] if 'perm_tm' in row.keys() else 'none',
            perm_ekyc=row['perm_ekyc'] if 'perm_ekyc' in row.keys() else 'none',
            perm_risk_management=row['perm_risk_management'] if 'perm_risk_management' in row.keys() else 'none',
            perm_internal_audit=row['perm_internal_audit'] if 'perm_internal_audit' in row.keys() else 'none',
            perm_esg=row['perm_esg'] if 'perm_esg' in row.keys() else 'none',
            perm_carbon=row['perm_carbon'] if 'perm_carbon' in row.keys() else 'none',
            can_assign_training=row['can_assign_training'] if 'can_assign_training' in row.keys() else False,
            mfa_secret=row['mfa_secret'] if 'mfa_secret' in row.keys() else None,
            mfa_enabled=row['mfa_enabled'] if 'mfa_enabled' in row.keys() else False,
            mfa_required_override=(row['mfa_required_override']
                                   if 'mfa_required_override' in row.keys() else None),
            mfa_backup_codes=row['mfa_backup_codes'] if 'mfa_backup_codes' in row.keys() else None,
        )
        # Late-added module permissions are not constructor args; load them so
        # can_view()/can_edit() see the stored value instead of defaulting to 'none'.
        for _k in ('perm_ongoing_screening', 'perm_academy'):
            if _k in row.keys():
                setattr(_u, _k, row[_k] or 'none')
        return _u
    
    @staticmethod
    def get_all():
        """Fetch all users from the database."""
        from database.db import get_db
        db = get_db()
        rows = db.execute(
            'SELECT * FROM users ORDER BY first_name, last_name'
        ).fetchall()
        
        return [User._from_row(row) for row in rows]

    @staticmethod
    def get_all_compliance_officers():
        """Fetch all users with compliance_officer or admin role."""
        from database.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM users WHERE role IN ('admin', 'compliance_officer')"
        ).fetchall()

        return [User._from_row(row) for row in rows]

    @staticmethod
    def get_by_departments(dept_ids):
        """Fetch all users whose primary department is in the given list of department IDs."""
        from database.db import get_db
        if not dept_ids:
            return []
        db = get_db()
        rows = db.execute(
            'SELECT * FROM users WHERE department_id = ANY(%s) ORDER BY first_name, last_name',
            (list(dept_ids),)
        ).fetchall()

        return [User._from_row(row) for row in rows]

    # ── MFA helpers ──────────────────────────────────────────────────────────

    def mfa_required(self):
        """True when this user must have MFA configured.

        An administrator's explicit decision wins over the role default in both
        directions — they can require it of anyone, or lift it from a role that
        would otherwise be forced. NULL means "follow the role rule", so
        existing behaviour is unchanged for everyone untouched.
        """
        override = getattr(self, 'mfa_required_override', None)
        if override is not None:
            return bool(override)
        return self.role in ('admin', 'compliance_officer', 'compliance_manager')

    def verify_totp(self, code):
        """Verify a 6-digit TOTP code against this user's secret (±30s window)."""
        if not self.mfa_secret or not self.mfa_enabled:
            return False
        import pyotp
        totp = pyotp.TOTP(self.mfa_secret)
        return totp.verify(str(code).strip(), valid_window=1)

    def verify_backup_code(self, code):
        """Consume a backup code (one-time use). Returns True if valid."""
        import json
        from database.db import get_db
        if not self.mfa_backup_codes:
            return False
        try:
            codes = json.loads(self.mfa_backup_codes)
        except Exception:
            return False
        code = code.strip().upper().replace('-', '')
        if code not in codes:
            return False
        codes.remove(code)
        db = get_db()
        db.execute('UPDATE users SET mfa_backup_codes=%s WHERE id=%s',
                   (json.dumps(codes), self.id))
        db.commit()
        self.mfa_backup_codes = json.dumps(codes)
        return True

    @staticmethod
    def generate_mfa_secret():
        import pyotp
        return pyotp.random_base32()

    @staticmethod
    def generate_backup_codes(n=8):
        import secrets, json
        codes = [secrets.token_hex(4).upper() for _ in range(n)]
        return codes, json.dumps(codes)

    @staticmethod
    def enable_mfa(user_id, secret, backup_codes_json):
        from database.db import get_db
        db = get_db()
        db.execute(
            'UPDATE users SET mfa_secret=%s, mfa_enabled=TRUE, mfa_backup_codes=%s WHERE id=%s',
            (secret, backup_codes_json, user_id)
        )
        db.commit()

    @staticmethod
    def disable_mfa(user_id):
        from database.db import get_db
        db = get_db()
        db.execute(
            'UPDATE users SET mfa_secret=NULL, mfa_enabled=FALSE, mfa_backup_codes=NULL WHERE id=%s',
            (user_id,)
        )
        db.commit()
