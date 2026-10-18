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

import sqlite3
from datetime import datetime, timedelta
from database.db import get_db

class PolicyCategory:
    def __init__(self, id=None, name_en=None, name_ar=None, description_en=None, description_ar=None, icon='bi-folder', created_at=None, **kwargs):
        self.id = id
        self.name_en = name_en
        self.name_ar = name_ar
        self.description_en = description_en
        self.description_ar = description_ar
        self.icon = icon
        self.icon = icon
        self.department_id = kwargs.get('department_id')
        self.created_at = created_at

    @staticmethod
    def get_all(department_id=None, include_global=True):
        db = get_db()
        query = 'SELECT * FROM policy_categories'
        params = []
        
        conditions = []
        if department_id:
            if include_global:
                conditions.append('(department_id = %s OR department_id IS NULL)')
                params.append(department_id)
            else:
                conditions.append('department_id = %s')
                params.append(department_id)
        elif not include_global: 
            # If no dept specified but we don't want global%s (Unusual case, assumes caller handles it)
            pass 
            
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
            
        query += ' ORDER BY name_en'
        
        rows = db.execute(query, params).fetchall()
        return [PolicyCategory(**dict(row)) for row in rows]
    
    @staticmethod
    def get_by_id(category_id):
        if not category_id: return None
        db = get_db()
        row = db.execute('SELECT * FROM policy_categories WHERE id = %s', (category_id,)).fetchone()
        return PolicyCategory(**dict(row)) if row else None

    @staticmethod
    def get_by_name(name_en):
        db = get_db()
        row = db.execute('SELECT * FROM policy_categories WHERE name_en = %s', (name_en,)).fetchone()
        return PolicyCategory(**dict(row)) if row else None

    @staticmethod
    def create(name_en, name_ar=None, description_en=None, description_ar=None, icon='bi-folder', department_id=None):
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO policy_categories (name_en, name_ar, description_en, description_ar, icon, department_id) 
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        ''', (name_en, name_ar or name_en, description_en, description_ar, icon, department_id))
        db.commit()
        return PolicyCategory.get_by_id(cursor.fetchone()[0])

    @staticmethod
    def update(category_id, name_en, name_ar=None, description_en=None, description_ar=None, icon='bi-folder', department_id=None):
        db = get_db()
        db.execute('''
            UPDATE policy_categories 
            SET name_en = %s, name_ar = %s, description_en = %s, description_ar = %s, icon = %s, department_id = COALESCE(%s, department_id)
            WHERE id = %s
        ''', (name_en, name_ar, description_en, description_ar, icon, department_id, category_id))
        db.commit()

        return PolicyCategory.get_by_id(category_id)

    @staticmethod
    def delete(category_id):
        db = get_db()
        # First check if there are any policies in this category
        policies = db.execute('SELECT COUNT(*) as count FROM policies WHERE category_id = %s', (category_id,)).fetchone()
        if policies['count'] > 0:
            return False, "Cannot delete category with associated policies."
        
        db.execute('DELETE FROM policy_categories WHERE id = %s', (category_id,))
        db.commit()
        return True, "Category deleted successfully."



class Policy:
    def __init__(self, id=None, policy_number=None, policy_name=None,
                 category_id=None, version='1.0', effective_date=None,
                 review_date=None, next_review_date=None, owner_id=None,
                 owner_function=None, description=None, content=None, 
                 attachment_path=None, status='draft', 
                 regulatory_reference=None, cbe_requirement=None,
                 is_public=False, issuing_date=None, approval_cycle='Annual',
                 approved_by=None, approval_date=None,
                 previous_version_id=None, change_summary=None,
                 is_mandatory=False, department_id=None, is_internal=True,
                 created_by=None, created_at=None, updated_by=None, updated_at=None, **kwargs):
        self.id = id
        self.policy_number = policy_number
        self.policy_name = policy_name
        self.category_id = category_id
        self.version = version
        self.effective_date = effective_date
        self.review_date = review_date
        self.next_review_date = next_review_date
        self.owner_id = owner_id
        self.owner_function = owner_function
        self.description = description
        self.content = content
        self.attachment_path = attachment_path
        self.status = status
        self.regulatory_reference = regulatory_reference
        self.cbe_requirement = cbe_requirement
        self.department_id = department_id
        self.is_internal = is_internal
        self.created_by = created_by
        self.created_at = created_at
        self.updated_by = updated_by
        self.updated_at = updated_at
        self.is_public = int(bool(is_public))
        self.issuing_date = issuing_date
        self.approval_cycle = approval_cycle
        self.approved_by = approved_by
        self.approval_date = approval_date
        self.previous_version_id = previous_version_id
        self.change_summary = change_summary
        self.is_mandatory = int(bool(is_mandatory))
        
        # Helper for templates
        self._category_name_en = None
        self._category_name_ar = None
        self.owner_name = None
        self.approved_by_name = None
        self.department_name = kwargs.get('department_name')
        self.department_code = kwargs.get('department_code')

    @property
    def version_number(self):
        return self.version
    
    @version_number.setter
    def version_number(self, value):
        self.version = value

    @property
    def responsible_function(self):
        # Prefer explicit owner_function over department name
        if self.owner_function:
            return self.owner_function
        if self.department_name:
            if self.department_code:
                return f"{self.department_name} ({self.department_code})"
            return self.department_name
        return "—"

    @property
    def category_name(self):
        """Return the category name based on current locale."""
        from flask_babel import get_locale
        locale = str(get_locale())
        if locale == 'ar' and self._category_name_ar:
            return self._category_name_ar
        return self._category_name_en or "General"
    
    @category_name.setter
    def category_name(self, value):
        self._category_name_en = value

    @property
    def category_name_en(self): return self._category_name_en
    @category_name_en.setter
    def category_name_en(self, value): self._category_name_en = value
    
    @property
    def category_name_ar(self): return self._category_name_ar
    @category_name_ar.setter
    def category_name_ar(self, value): self._category_name_ar = value

    def is_acknowledged_by(self, user_id):
        """Check if a specific user has acknowledged this policy."""
        from models.policy import PolicyAcknowledgment
        return PolicyAcknowledgment.has_acknowledged(self.id, user_id)

    @staticmethod
    def generate_policy_number(category_id):
        """[DEP]-[CAT]-[YEAR]-[SEQ]"""
        db = get_db()
        cat = PolicyCategory.get_by_id(category_id)
        
        dept_code = "COMP"
        if cat:
            name = cat.name_en.upper() if cat.name_en else "GEN"
            if "GOV" in name: dept_code = "GOV"
            elif "HR" in name: dept_code = "HR"
            elif "OPS" in name or "OPER" in name: dept_code = "OPS"
            elif "TECH" in name or "CYBER" in name: dept_code = "TECH"
        
        cat_code = cat.name_en[:3].upper() if (cat and cat.name_en) else "GEN"
        year = datetime.now().year
        
        row = db.execute('''
            SELECT COUNT(*) as count FROM policies 
            WHERE policy_number LIKE %s
        ''', (f"%-{year}-%",)).fetchone()
        seq = (row['count'] or 0) + 1
        
        return f"{dept_code}-{cat_code}-{year}-{seq:03d}"
    
    @staticmethod
    def create(data, created_by):
        db = get_db()
        policy_number = data.get('policy_number')
        if not policy_number:
            policy_number = Policy.generate_policy_number(data.get('category_id'))
        
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO policies (
                policy_number, policy_name, category_id, version,
                effective_date, review_date, next_review_date, owner_id,
                owner_function, description, content, attachment_path, 
                status, regulatory_reference, cbe_requirement, is_public, 
                is_mandatory, issuing_date, approval_cycle, created_by, updated_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        ''', (
            policy_number, data.get('policy_name', ''), data.get('category_id'),
            data.get('version', '1.0'), data.get('effective_date'),
            data.get('review_date'), data.get('next_review_date'),
            data.get('owner_id'), data.get('owner_function'),
            data.get('description'), data.get('content'), data.get('attachment_path'),
            data.get('status', 'draft'), data.get('regulatory_reference'),
            data.get('cbe_requirement'), data.get('is_public', 0),
            data.get('is_mandatory', 0),
            data.get('issuing_date', datetime.now().date().isoformat()),
            data.get('approval_cycle', 'Annual'), created_by, created_by
        ))
        db.commit()
        return Policy.get_by_id(cursor.fetchone()[0])
    
    @staticmethod
    def get_by_id(policy_id):
        db = get_db()
        row = db.execute('''
            SELECT p.*, c.name_en as category_name_en, c.name_ar as category_name_ar,
                   u.first_name || ' ' || u.last_name as owner_name,
                   ap.first_name || ' ' || ap.last_name as approved_by_name,
                   d.name as department_name, d.code as department_code
            FROM policies p
            LEFT JOIN policy_categories c ON p.category_id = c.id
            LEFT JOIN users u ON p.owner_id = u.id
            LEFT JOIN users ap ON p.approved_by = ap.id
            LEFT JOIN departments d ON p.department_id = d.id
            WHERE p.id = %s
        ''', (policy_id,)).fetchone()
        
        if row:
            init_params = Policy.__init__.__code__.co_varnames
            pol_data = {k: row[k] for k in row.keys() if k in init_params}
            policy = Policy(**pol_data)
            policy._category_name_en = row['category_name_en']
            policy._category_name_ar = row['category_name_ar']
            policy.owner_name = row['owner_name']
            policy.approved_by_name = row['approved_by_name'] 
            policy.department_name = row['department_name']
            policy.department_code = row['department_code']
            return policy
        return None
    
    @staticmethod
    def get_all(filters=None, status=None, category_id=None):
        db = get_db()
        query = '''
            SELECT p.*, c.name_en as category_name_en, c.name_ar as category_name_ar,
                   u.first_name || ' ' || u.last_name as owner_name,
                   d.name as department_name, d.code as department_code
            FROM policies p
            LEFT JOIN policy_categories c ON p.category_id = c.id
            LEFT JOIN users u ON p.owner_id = u.id
            LEFT JOIN departments d ON p.department_id = d.id
            WHERE 1=1
        '''
        params = []
        
        if status:
            query += " AND p.status = %s"
            params.append(status)
            
        if category_id:
            query += " AND p.category_id = %s"
            params.append(category_id)

        if filters and filters.get('is_public') is not None:
            query += " AND p.is_public = %s"
            params.append(filters.get('is_public'))
            
        query += " ORDER BY p.created_at DESC"
        
        rows = db.execute(query, params).fetchall()
        init_params = Policy.__init__.__code__.co_varnames
        policies = []
        for row in rows:
            pol_data = {k: row[k] for k in row.keys() if k in init_params}
            p = Policy(**pol_data)
            p._category_name_en = row['category_name_en']
            p._category_name_ar = row['category_name_ar']
            p.owner_name = row['owner_name']
            p.department_name = row['department_name']
            p.department_code = row['department_code']
            policies.append(p)
        return policies
    
    @staticmethod
    def get_published(only_public=True):
        filters = {'is_public': 1} if only_public else None
        return Policy.get_all(status='published', filters=filters)
    
    @staticmethod
    def get_pending_acknowledgment(employee_id):
        db = get_db()
        rows = db.execute('''
            SELECT p.*, c.name_en as category_name_en, c.name_ar as category_name_ar,
                   d.name as department_name, d.code as department_code
            FROM policies p
            JOIN policy_categories c ON p.category_id = c.id
            LEFT JOIN departments d ON p.department_id = d.id
            WHERE p.status = 'published'
            AND p.id NOT IN (
                SELECT policy_id FROM policy_acknowledgments WHERE employee_id = %s
            )
            ORDER BY p.is_mandatory DESC, p.created_at DESC
        ''', (employee_id,)).fetchall()
        
        policies = []
        init_params = Policy.__init__.__code__.co_varnames
        for row in rows:
            pol_data = {k: row[k] for k in row.keys() if k in init_params}
            p = Policy(**pol_data)
            p._category_name_en = row['category_name_en']
            p._category_name_ar = row['category_name_ar']
            p.department_name = row['department_name']
            p.department_code = row['department_code']
            policies.append(p)
        return policies
    
    @staticmethod
    def get_upcoming_reviews(days=30):
        db = get_db()
        next_date = (datetime.now() + timedelta(days=days)).date().isoformat()
        rows = db.execute('''
            SELECT p.*, c.name_en as category_name_en,
                   d.name as department_name, d.code as department_code
            FROM policies p
            JOIN policy_categories c ON p.category_id = c.id
            LEFT JOIN departments d ON p.department_id = d.id
            WHERE p.next_review_date IS NOT NULL 
            AND NULLIF(p.next_review_date, '')::date <= %s
            AND p.status != 'archived'
        ''', (next_date,)).fetchall()
        
        policies = []
        init_params = Policy.__init__.__code__.co_varnames
        for row in rows:
            pol_data = {k: row[k] for k in row.keys() if k in init_params}
            policy = Policy(**pol_data)
            policy.category_name_en = row['category_name_en']
            policy.department_name = row['department_name']
            policy.department_code = row['department_code']
            policies.append(policy)
        return policies
    
    def update(self, data, updated_by):
        db = get_db()
        db.execute('''
            UPDATE policies SET
                policy_number = %s, policy_name = %s, category_id = %s, version = %s, 
                effective_date = %s, review_date = %s, next_review_date = %s, 
                owner_id = %s, owner_function = %s, department_id = %s, 
                is_internal = %s, description = %s, content = %s, 
                attachment_path = %s, status = %s, regulatory_reference = %s, 
                cbe_requirement = %s, is_public = %s, is_mandatory = %s, 
                issuing_date = %s, approval_cycle = %s, 
                updated_by = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (
            # _v: use submitted value only if non-empty, else keep existing
            (lambda v, f: f if (v is None or str(v).strip() == '') else v)(data.get('policy_number'), self.policy_number),
            (lambda v, f: f if (v is None or str(v).strip() == '') else v)(data.get('policy_name'), self.policy_name),
            (lambda v, f: f if (v is None or str(v).strip() == '') else v)(data.get('category_id'), self.category_id),
            (lambda v, f: f if (v is None or str(v).strip() == '') else v)(data.get('version'), self.version),
            (lambda v, f: f if (v is None or str(v).strip() == '') else v)(data.get('effective_date'), self.effective_date),
            data.get('review_date', self.review_date),
            data.get('next_review_date', self.next_review_date),
            data.get('owner_id', self.owner_id),
            (lambda v, f: f if (v is None or str(v).strip() == '') else v)(data.get('owner_function'), self.owner_function),
            data.get('department_id', self.department_id),
            int(bool(data.get('is_internal', self.is_internal))),
            data.get('description', self.description),
            data.get('content', self.content),
            (lambda v, f: f if (v is None or str(v).strip() == '') else v)(data.get('attachment_path'), self.attachment_path),
            (lambda v, f: f if (v is None or str(v).strip() == '') else v)(data.get('status'), self.status),
            data.get('regulatory_reference', self.regulatory_reference),
            data.get('cbe_requirement', self.cbe_requirement),
            int(bool(data.get('is_public', self.is_public))),
            int(bool(data.get('is_mandatory', self.is_mandatory))),
            data.get('issuing_date', self.issuing_date),
            data.get('approval_cycle', self.approval_cycle),
            updated_by,
            self.id
        ))
        db.commit()

    def approve(self, approver_id):
        db = get_db()
        db.execute('''
            UPDATE policies SET 
                status = 'approved', approved_by = %s, approval_date = CURRENT_TIMESTAMP,
                updated_by = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (approver_id, approver_id, self.id))
        db.commit()
    
    def publish(self):
        db = get_db()
        db.execute("UPDATE policies SET status = 'published' WHERE id = %s", (self.id,))
        db.commit()
    
    def archive(self):
        db = get_db()
        db.execute("UPDATE policies SET status = 'archived' WHERE id = %s", (self.id,))
        db.commit()
    
    def acknowledge(self, employee_id, ip_address=None, signature=None):
        db = get_db()
        db.execute('''
            INSERT INTO policy_acknowledgments 
            (policy_id, employee_id, acknowledgment_date, ip_address, digital_signature)
            VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)
        ON CONFLICT (policy_id, employee_id) DO UPDATE SET acknowledgment_date = CURRENT_TIMESTAMP, ip_address = EXCLUDED.ip_address
        ''', (self.id, employee_id, ip_address, signature))
        db.commit()

    def get_acknowledgment_count(self):
        db = get_db()
        row = db.execute('SELECT COUNT(*) as count FROM policy_acknowledgments WHERE policy_id = %s', (self.id,)).fetchone()
        return row['count']
    
    def get_acknowledgment_rate(self):
        db = get_db()
        total_employees = db.execute("SELECT COUNT(*) as count FROM users WHERE role != 'admin' AND is_active = 1").fetchone()['count']
        if total_employees == 0: return 0
        return int((self.get_acknowledgment_count() / total_employees) * 100)

    def get_pending_employees(self):
        """Active non-admin users who have NOT yet acknowledged this policy."""
        db = get_db()
        rows = db.execute('''
            SELECT u.id, u.first_name || ' ' || u.last_name as employee_name, u.department, u.email
            FROM users u
            WHERE u.role != 'admin' AND u.is_active = 1
              AND u.id NOT IN (
                  SELECT employee_id FROM policy_acknowledgments WHERE policy_id = %s
              )
            ORDER BY u.department, employee_name
        ''', (self.id,)).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def get_overall_stats():
        db = get_db()
        total_employees = db.execute("SELECT COUNT(*) as count FROM users WHERE role != 'admin' AND is_active = 1").fetchone()['count']
        total_mandatory_policies = db.execute("SELECT COUNT(*) as count FROM policies WHERE status = 'published' AND is_mandatory = 1").fetchone()['count']
        total_published_policies = db.execute("SELECT COUNT(*) as count FROM policies WHERE status = 'published'").fetchone()['count']

        if total_employees == 0 or total_published_policies == 0:
            return {
                'rate': 0,
                'actual_acks': 0,
                'total_required_acks': 0,
                'total_employees': total_employees,
                'total_mandatory_policies': total_mandatory_policies,
                'total_published_policies': total_published_policies
            }

        total_required_acks = total_employees * total_published_policies

        # Count actual acknowledgments across all published policies (not just mandatory ones,
        # so the dashboard reflects real acknowledgment activity instead of hiding it)
        actual_acks = db.execute('''
            SELECT COUNT(*) as count FROM policy_acknowledgments a
            JOIN policies p ON a.policy_id = p.id
            WHERE p.status = 'published'
        ''').fetchone()['count']

        rate = int((actual_acks / total_required_acks) * 100) if total_required_acks > 0 else 0

        return {
            'rate': rate,
            'actual_acks': actual_acks,
            'total_required_acks': total_required_acks,
            'total_employees': total_employees,
            'total_mandatory_policies': total_mandatory_policies,
            'total_published_policies': total_published_policies
        }
    
    def create_version(self, change_summary, created_by):
        db = get_db()
        db.execute('''
            INSERT INTO policy_versions (
                policy_id, version, change_summary, content, 
                created_by
            ) VALUES (%s, %s, %s, %s, %s)
        ''', (self.id, self.version, change_summary, self.content, created_by))
        db.commit()
    
    def get_versions(self):
        db = get_db()
        rows = db.execute('''
            SELECT v.*, u.first_name || ' ' || u.last_name as creator_name 
            FROM policy_versions v
            LEFT JOIN users u ON v.created_by = u.id
            WHERE v.policy_id = %s ORDER BY v.created_at DESC
        ''', (self.id,)).fetchall()
        return rows

    @staticmethod
    def get_gap_analysis():
        """Compare required policies vs existing policies"""
        required = RequiredPolicy.get_all()
        existing = Policy.get_all()
        
        analysis = []
        for req in required:
            match = None
            # Normalize for comparison
            req_name = req.policy_name_en.lower() if req.policy_name_en else ""
            
            for policy in existing:
                pol_name = policy.policy_name.lower() if policy.policy_name else ""
                # Check if names are similar enough (simple check)
                if req_name and (req_name in pol_name or pol_name in req_name):
                    match = policy
                    break
            
            status = 'Missing'
            if match:
                if match.status == 'published':
                    status = 'Implemented'
                else:
                    status = 'Draft'
            
            analysis.append({
                'required': req,
                'status': status,
                'policy': match
            })
        return analysis

    def get_reviews(self):
        """Get all review stages for this policy."""
        db = get_db()
        rows = db.execute('''
            SELECT w.*, u.first_name || ' ' || u.last_name as reviewer_name
            FROM policy_review_workflow w
            JOIN users u ON w.reviewer_id = u.id
            WHERE w.policy_id = %s
            ORDER BY w.created_at ASC
        ''', (self.id,)).fetchall()
        return rows

    def add_review_stage(self, reviewer_id, stage_name):
        """Assign a reviewer to a new stage."""
        db = get_db()
        db.execute('''
            INSERT INTO policy_review_workflow (policy_id, reviewer_id, stage_name, status)
            VALUES (%s, %s, %s, 'pending')
        ''', (self.id, reviewer_id, stage_name))
        db.commit()
        # Update policy status to 'pending_approval' if it's currently 'draft'
        if self.status == 'draft':
            db.execute("UPDATE policies SET status = 'pending_approval' WHERE id = %s", (self.id,))
            db.commit()

    def submit_review(self, reviewer_id, status, comments=None):
        """Submit a review decision."""
        db = get_db()
        db.execute('''
            UPDATE policy_review_workflow 
            SET status = %s, comments = %s, review_date = CURRENT_TIMESTAMP
            WHERE policy_id = %s AND reviewer_id = %s AND status = 'pending'
        ''', (status, comments, self.id, reviewer_id))
        db.commit()
        
        # Check if all reviews are approved
        pending = db.execute('''
            SELECT COUNT(*) as count FROM policy_review_workflow 
            WHERE policy_id = %s AND status = 'pending'
        ''', (self.id,)).fetchone()['count']
        
        if pending == 0:
            # If all are approved, set policy to 'approved'
            # (In a more complex system, we'd check if any were rejected)
            rejected = db.execute('''
                SELECT COUNT(*) as count FROM policy_review_workflow 
                WHERE policy_id = %s AND status = 'rejected'
            ''', (self.id,)).fetchone()['count']
            
            new_status = 'approved' if rejected == 0 else 'rejected'
            db.execute("UPDATE policies SET status = %s WHERE id = %s", (new_status, self.id))
            db.commit()

class PolicyReviewWorkflow:
    def __init__(self, id=None, policy_id=None, reviewer_id=None, stage_name=None, status='pending', comments=None, review_date=None, created_at=None, **kwargs):
        self.id = id
        self.policy_id = policy_id
        self.reviewer_id = reviewer_id
        self.stage_name = stage_name
        self.status = status
        self.comments = comments
        self.review_date = review_date
        self.created_at = created_at

    @staticmethod
    def get_pending_for_user(user_id):
        db = get_db()
        rows = db.execute('''
            SELECT w.*, p.policy_name, p.policy_number
            FROM policy_review_workflow w
            JOIN policies p ON w.policy_id = p.id
            WHERE w.reviewer_id = %s AND w.status = 'pending'
        ''', (user_id,)).fetchall()
        return rows


class PolicyAcknowledgment:
    @staticmethod
    def acknowledge(policy_id, employee_id, ip_address=None, signature=None):
        db = get_db()
        db.execute('''
            INSERT INTO policy_acknowledgments 
            (policy_id, employee_id, acknowledgment_date, ip_address, digital_signature)
            VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)
        ON CONFLICT (policy_id, employee_id) DO UPDATE SET acknowledgment_date = CURRENT_TIMESTAMP, ip_address = EXCLUDED.ip_address
        ''', (policy_id, employee_id, ip_address, signature))
        db.commit()

    @staticmethod
    def acknowledge_all(policy_ids, employee_id, ip_address=None):
        db = get_db()
        for pid in policy_ids:
            db.execute('''
                INSERT INTO policy_acknowledgments 
                (policy_id, employee_id, acknowledgment_date, ip_address, digital_signature)
                VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)
            ON CONFLICT (policy_id, employee_id) DO UPDATE SET acknowledgment_date = CURRENT_TIMESTAMP, ip_address = EXCLUDED.ip_address
            ''', (pid, employee_id, ip_address, 'Batch Acknowledgment'))
        db.commit()
    
    @staticmethod
    def has_acknowledged(policy_id, employee_id):
        db = get_db()
        row = db.execute('SELECT 1 FROM policy_acknowledgments WHERE policy_id = %s AND employee_id = %s', 
                        (policy_id, employee_id)).fetchone()
        return row is not None
    
    @staticmethod
    def get_acknowledgments(policy_id):
        db = get_db()
        return db.execute('''
            SELECT a.*, u.first_name || ' ' || u.last_name as employee_name, u.department
            FROM policy_acknowledgments a
            JOIN users u ON a.employee_id = u.id
            WHERE a.policy_id = %s
            ORDER BY a.acknowledgment_date DESC
        ''', (policy_id,)).fetchall()

class RequiredPolicy:
    def __init__(self, id=None, policy_name_en=None, policy_name_ar=None, 
                 regulatory_reference=None, is_mandatory=True, 
                 description_en=None, description_ar=None, created_at=None, **kwargs):
        self.id = id
        self.policy_name_en = policy_name_en
        self.policy_name_ar = policy_name_ar
        self.regulatory_reference = regulatory_reference
        self.is_mandatory = is_mandatory
        self.description_en = description_en
        self.description_ar = description_ar
        self.created_at = created_at

    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute('SELECT * FROM required_policies ORDER BY is_mandatory DESC, policy_name_en').fetchall()
        return [RequiredPolicy(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(policy_id):
        db = get_db()
        row = db.execute('SELECT * FROM required_policies WHERE id = %s', (policy_id,)).fetchone()
        return RequiredPolicy(**dict(row)) if row else None

    @staticmethod
    def create(data):
        db = get_db()
        cursor = db.execute('''
            INSERT INTO required_policies (policy_name_en, policy_name_ar, regulatory_reference, 
                                         is_mandatory, description_en, description_ar)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (
            data.get('policy_name_en'),
            data.get('policy_name_ar'),
            data.get('regulatory_reference'),
            1 if data.get('is_mandatory') else 0,
            data.get('description_en'),
            data.get('description_ar')
        ))
        db.commit()
        return cursor.fetchone()[0]

    @staticmethod
    def update(policy_id, data):
        db = get_db()
        db.execute('''
            UPDATE required_policies 
            SET policy_name_en = %s, policy_name_ar = %s, regulatory_reference = %s, 
                is_mandatory = %s, description_en = %s, description_ar = %s
            WHERE id = %s
        ''', (
            data.get('policy_name_en'),
            data.get('policy_name_ar'),
            data.get('regulatory_reference'),
            1 if data.get('is_mandatory') else 0,
            data.get('description_en'),
            data.get('description_ar'),
            policy_id
        ))
        db.commit()

    @staticmethod
    def delete(policy_id):
        db = get_db()
        db.execute('DELETE FROM required_policies WHERE id = %s', (policy_id,))
        db.commit()


class PolicyAttachment:
    """Handles multiple document attachments per policy."""

    def __init__(self, id=None, policy_id=None, filename=None, file_path=None,
                 file_size=0, uploaded_by=None, uploaded_at=None, **kwargs):
        self.id = id
        self.policy_id = policy_id
        self.filename = filename
        self.file_path = file_path
        self.file_size = file_size
        self.uploaded_by = uploaded_by
        self.uploaded_at = uploaded_at
        self.uploader_name = kwargs.get('uploader_name')

    @staticmethod
    def get_all_for_policy(policy_id):
        db = get_db()
        rows = db.execute('''
            SELECT a.*, u.first_name || ' ' || u.last_name as uploader_name
            FROM policy_attachments a
            LEFT JOIN users u ON a.uploaded_by = u.id
            WHERE a.policy_id = %s
            ORDER BY a.uploaded_at DESC
        ''', (policy_id,)).fetchall()
        return [PolicyAttachment(**dict(row)) for row in rows]

    @staticmethod
    def create(policy_id, filename, file_path, file_size=0, uploaded_by=None):
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO policy_attachments (policy_id, filename, file_path, file_size, uploaded_by)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        ''', (policy_id, filename, file_path, file_size, uploaded_by))
        db.commit()
        return cursor.fetchone()[0]

    @staticmethod
    def get_by_id(attachment_id):
        db = get_db()
        row = db.execute('SELECT * FROM policy_attachments WHERE id = %s', (attachment_id,)).fetchone()
        return PolicyAttachment(**dict(row)) if row else None

    @staticmethod
    def delete(attachment_id):
        db = get_db()
        attachment = db.execute('SELECT file_path FROM policy_attachments WHERE id = %s', (attachment_id,)).fetchone()
        db.execute('DELETE FROM policy_attachments WHERE id = %s', (attachment_id,))
        db.commit()
        return dict(attachment) if attachment else None
