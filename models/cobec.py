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
COBEC (Code of Business Ethics & Conduct) Model
"""
from database.db import get_db
from datetime import datetime

class COBECDeclaration:
    def __init__(self, id=None, employee_id=None, employee_name=None, department=None,
                 declaration_date=None, declaration_year=None,
                 has_read_code=False, understands_responsibilities=False,
                 commits_to_compliance=False, will_report_violations=False,
                 has_known_violations=False, violation_details=None,
                 has_prior_misconduct=False, misconduct_details=None,
                 digital_signature=None, status='under_review',
                 reviewer_id=None, review_date=None, review_comments=None,
                 created_at=None, updated_at=None):
        self.id = id
        self.employee_id = employee_id
        self.employee_name = employee_name
        self.department = department
        self.declaration_date = declaration_date
        self.declaration_year = declaration_year
        self.has_read_code = has_read_code
        self.understands_responsibilities = understands_responsibilities
        self.commits_to_compliance = commits_to_compliance
        self.will_report_violations = will_report_violations
        self.has_known_violations = has_known_violations
        self.violation_details = violation_details
        self.has_prior_misconduct = has_prior_misconduct
        self.misconduct_details = misconduct_details
        self.digital_signature = digital_signature
        self.status = status
        self.reviewer_id = reviewer_id
        self.review_date = review_date
        self.review_comments = review_comments
        self.created_at = created_at
        self.updated_at = updated_at
    
    @staticmethod
    def create(data, employee_id, year=None):
        """Create a new COBEC declaration"""
        db = get_db()
        if not year:
            year = datetime.now().year
        
        cursor = db.cursor()
        try:
            cursor.execute('''
                INSERT INTO cobec_declarations (
                    employee_id, declaration_year,
                    has_read_code, understands_responsibilities,
                    commits_to_compliance, will_report_violations,
                    has_known_violations, violation_details,
                    has_prior_misconduct, misconduct_details,
                    digital_signature, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'under_review')
                RETURNING id
            ''', (
                employee_id, year,
                1 if data.get('has_read_code') else 0,
                1 if data.get('understands_responsibilities') else 0,
                1 if data.get('commits_to_compliance') else 0,
                1 if data.get('will_report_violations') else 0,
                1 if data.get('has_known_violations') == '1' or data.get('has_known_violations') is True else 0,
                data.get('violation_details'),
                1 if data.get('has_prior_misconduct') == '1' or data.get('has_prior_misconduct') is True else 0,
                data.get('misconduct_details'),
                data.get('digital_signature')
            ))
            db.commit()
            return cursor.fetchone()['id']
        except Exception as e:
            db.rollback()
            raise e
    
    @staticmethod
    def get_by_id(declaration_id):
        """Get declaration by ID"""
        db = get_db()
        row = db.execute('''
            SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.department
            FROM cobec_declarations d
            JOIN users u ON d.employee_id = u.id
            WHERE d.id = %s
        ''', (declaration_id,)).fetchone()
        
        if row:
            return COBECDeclaration(**dict(row))
        return None
    
    @staticmethod
    def get_by_employee_year(employee_id, year):
        """Get declaration for employee and year"""
        db = get_db()
        row = db.execute('''
            SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.department
            FROM cobec_declarations d
            JOIN users u ON d.employee_id = u.id
            WHERE d.employee_id = %s AND d.declaration_year = %s
        ''', (employee_id, year)).fetchone()
        
        if row:
            return COBECDeclaration(**dict(row))
        return None
    
    @staticmethod
    def get_by_employee(employee_id):
        """Get all declarations for an employee"""
        db = get_db()
        rows = db.execute('''
            SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.department
            FROM cobec_declarations d
            JOIN users u ON d.employee_id = u.id
            WHERE d.employee_id = %s
            ORDER BY d.declaration_year DESC
        ''', (employee_id,)).fetchall()
        
        return [COBECDeclaration(**dict(row)) for row in rows]
    
    @staticmethod
    def get_all(year=None):
        """Get all COBEC declarations, optionally filtered by year"""
        db = get_db()
        if year:
            rows = db.execute('''
                SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.department
                FROM cobec_declarations d
                JOIN users u ON d.employee_id = u.id
                WHERE d.declaration_year = %s
                ORDER BY d.created_at DESC
            ''', (year,)).fetchall()
        else:
            rows = db.execute('''
                SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.department
                FROM cobec_declarations d
                JOIN users u ON d.employee_id = u.id
                ORDER BY d.declaration_year DESC, d.created_at DESC
            ''').fetchall()
        
        return [COBECDeclaration(**dict(row)) for row in rows]
    
    @staticmethod
    def get_pending_for_manager(manager_id):
        """Get declarations pending review for a manager's direct reports"""
        db = get_db()
        sql = '''
            SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.department
            FROM cobec_declarations d
            JOIN users u ON d.employee_id = u.id
            WHERE u.manager_id = %s AND d.status IN ('submitted', 'under_review')
            ORDER BY d.created_at DESC
        '''
        rows = db.execute(sql, (manager_id,)).fetchall()
        return [COBECDeclaration(**dict(row)) for row in rows]

    @staticmethod
    def get_pending_for_compliance():
        """Get declarations pending compliance review (system-wide)"""
        db = get_db()
        sql = '''
            SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.department
            FROM cobec_declarations d
            JOIN users u ON d.employee_id = u.id
            WHERE d.status IN ('submitted', 'under_review', 'escalated')
            ORDER BY d.created_at DESC
        '''
        rows = db.execute(sql).fetchall()
        return [COBECDeclaration(**dict(row)) for row in rows]

    @staticmethod
    def get_compliance_status(year=None):
        """
        Get status of all active employees for a specific year.
        Returns list of dicts with user details and declaration status.
        """
        db = get_db()
        current_year = year or datetime.now().year
        
        # Left join users with declarations to find missing ones
        sql = '''
            SELECT 
                u.id as user_id, 
                u.first_name, 
                u.last_name, 
                u.department, 
                u.email,
                d.id as declaration_id,
                d.status,
                d.created_at as declaration_date,
                d.has_known_violations,
                d.has_prior_misconduct
            FROM users u
            LEFT JOIN cobec_declarations d 
                ON u.id = d.employee_id AND d.declaration_year = %s
            WHERE u.is_active = 1 AND u.role != 'admin'
            ORDER BY 
                CASE WHEN d.id IS NULL THEN 0 ELSE 1 END, -- Pending first - No, User wanted "identify list of whom are pending"
                u.department, 
                u.last_name
        '''
        
        rows = db.execute(sql, (current_year,)).fetchall()
        
        results = []
        for row in rows:
            results.append({
                'user_id': row['user_id'],
                'employee_name': f"{row['first_name']} {row['last_name']}",
                'department': row['department'] or 'N/A',
                'email': row['email'],
                'declaration_id': row['declaration_id'],
                'status': row['status'] or 'pending',
                'declaration_date': row['declaration_date'],
                'has_issues': bool(row['has_known_violations'] or row['has_prior_misconduct']) if row['declaration_id'] else False
            })
            
        return results

    @staticmethod
    def get_statistics(year=None):
        """Get COBEC statistics"""
        db = get_db()
        current_year = year or datetime.now().year
        
        # Total active employees (excluding admins%s User model doesn't strictly separate, but usually admins are tech)
        # Let's match the logic above
        total_employees = db.execute('''
            SELECT COUNT(*) as count FROM users 
            WHERE is_active = 1 AND role != 'admin'
        ''').fetchone()['count']
        
        # Submitted this year
        submitted = db.execute('''
            SELECT COUNT(d.id) 
            FROM cobec_declarations d
            JOIN users u ON d.employee_id = u.id
            WHERE d.declaration_year = %s AND u.is_active = 1 AND u.role != 'admin'
        ''', (current_year,)).fetchone()['count']
        
        # Not submitted
        not_submitted = total_employees - submitted
        
        return {
            'total_employees': total_employees,
            'submitted': submitted,
            'not_submitted': not_submitted,
            'completion_rate': round((submitted / total_employees * 100) if total_employees > 0 else 0, 1)
        }
    def approve(self, reviewer_id, comments=None):
        """Approve declaration"""
        db = get_db()
        db.execute('''
            UPDATE cobec_declarations 
            SET status = 'approved', reviewer_id = %s, review_date = CURRENT_TIMESTAMP, review_comments = %s
            WHERE id = %s
        ''', (reviewer_id, comments, self.id))
        db.commit()
    
    def request_clarification(self, reviewer_id, comments):
        """Request clarification from employee"""
        db = get_db()
        db.execute('''
            UPDATE cobec_declarations
            SET status = 'requires_clarification', reviewer_id = %s, review_date = CURRENT_TIMESTAMP, review_comments = %s
            WHERE id = %s
        ''', (reviewer_id, comments, self.id))
        db.commit()

    def escalate(self, reviewer_id, comments):
        """Manager escalates declaration to compliance for further review"""
        db = get_db()
        db.execute('''
            UPDATE cobec_declarations
            SET status = 'escalated', reviewer_id = %s, review_date = CURRENT_TIMESTAMP, review_comments = %s
            WHERE id = %s
        ''', (reviewer_id, comments, self.id))
        db.commit()
        
    def to_dict(self):
        return {
            'id': self.id,
            'status': self.status,
            'declaration_year': self.declaration_year,
            'declaration_date': self.declaration_date
        }
