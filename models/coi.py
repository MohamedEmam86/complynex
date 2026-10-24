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
from datetime import datetime
from database.db import get_db

class COICampaign:
    def __init__(self, id=None, campaign_name=None, campaign_year=None,
                 start_date=None, end_date=None, description=None,
                 status='draft', created_by=None, created_at=None,
                 campaign_type='annual',  # New field
                 completion_rate=0, total=0, completed=0, **kwargs):
        self.id = id
        self.campaign_name = campaign_name
        self.campaign_year = campaign_year
        self.start_date = start_date
        self.end_date = end_date
        self.description = description
        self.status = status
        self.created_by = created_by
        self.created_at = created_at
        self.campaign_type = campaign_type
        
        # Stats (optional)
        self.completion_rate = completion_rate
        self.total = total
        self.completed = completed
        
        # User specific state (optional)
        self.user_declared = False
    
    @staticmethod
    def create(data, created_by):
        """Create new COI campaign"""
        db = get_db()
        cursor = db.cursor()
        
        campaign_type = data.get('campaign_type', 'annual')
        
        try:
            cursor.execute('''
                INSERT INTO coi_campaigns (campaign_name, campaign_year, start_date, end_date, description, status, created_by, campaign_type,
                                           is_active, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s) RETURNING id
            ''', (
                data['campaign_name'],
                data['campaign_year'],
                data['start_date'],
                data['end_date'],
                data.get('description'),
                'active',  # Create as active immediately
                created_by,
                campaign_type,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))
            campaign_id = cursor.fetchone()[0]
            
            # Only add employees for annual campaigns
            if campaign_type == 'annual':
                cursor.execute("SELECT id FROM users WHERE is_active = 1 AND COALESCE(role, '') <> 'admin'")
                employees = cursor.fetchall()
                
                for emp in employees:
                    emp_id = emp[0]
                    cursor.execute('''
                        INSERT INTO coi_campaign_employees (campaign_id, employee_id, status)
                        VALUES (%s, %s, 'pending')
                    ''', (campaign_id, emp_id))
            
            db.commit()
            return campaign_id
        except Exception as e:
            db.rollback()
            raise e

    # ... (get_by_id, get_all, get_active, update, close - unchanged for now, but update SQL in get_by_id/get_all if needed%s)
    # Wait, SQLite ignores extra kwargs in __init__ if row has extra col%s No.
    # I need to update get_by_id and get_all SQL queries to select * which includes new column.
    # And check if existing rows (without the column) cause issues.
    # If I just add the column via ALTER TABLE, 'SELECT *' will return it.
    
    # ...


    
    @staticmethod
    def get_by_id(campaign_id):
        """Get campaign by ID"""
        db = get_db()
        campaign = db.execute('SELECT * FROM coi_campaigns WHERE id = %s', (campaign_id,)).fetchone()
        if not campaign:
            return None
        return COICampaign(**dict(campaign))
    
    @staticmethod
    def get_all(status=None):
        """Get all campaigns"""
        db = get_db()
        if status:
            rows = db.execute('SELECT * FROM coi_campaigns WHERE status = %s ORDER BY created_at DESC', (status,)).fetchall()
        else:
            rows = db.execute('SELECT * FROM coi_campaigns ORDER BY created_at DESC').fetchall()
            
        campaigns = []
        for row in rows:
            camp = COICampaign(**dict(row))
            # Calculate stats for the list view
            stats = camp.get_statistics()
            camp.completion_rate = stats['completion_rate']
            camp.total = stats['total_employees']
            camp.completed = stats['completed']
            campaigns.append(camp)
            
        return campaigns
    
    @staticmethod
    def get_active_annual():
        """Get currently active annual campaign"""
        db = get_db()
        row = db.execute("SELECT * FROM coi_campaigns WHERE status = 'active' AND campaign_type = 'annual' ORDER BY end_date ASC LIMIT 1").fetchone()
        if row:
            return COICampaign(**dict(row))
        return None

    @staticmethod
    def get_active_adhoc():
        """Get currently active ad-hoc campaign"""
        db = get_db()
        row = db.execute("SELECT * FROM coi_campaigns WHERE status = 'active' AND campaign_type = 'adhoc' ORDER BY end_date ASC LIMIT 1").fetchone()
        if row:
            return COICampaign(**dict(row))
        return None
    
    @staticmethod
    def get_active():
        """Get any active campaign (prefer annual)"""
        # Fallback for legacy calls, but prefer annual
        annual = COICampaign.get_active_annual()
        if annual: return annual
        return COICampaign.get_active_adhoc()
    
    def update(self, data):
        """Update campaign"""
        db = get_db()
        db.execute('''
            UPDATE coi_campaigns 
            SET campaign_name=%s, end_date=%s, description=%s
            WHERE id=%s
        ''', (data['campaign_name'], data['end_date'], data['description'], self.id))
        db.commit()
    
    def close(self):
        """Close campaign"""
        db = get_db()
        db.execute("UPDATE coi_campaigns SET status = 'closed' WHERE id = %s", (self.id,))
        db.commit()
    
    def get_statistics(self):
        """Get campaign statistics"""
        db = get_db()
        
        # Total participants
        total = db.execute(
            "SELECT COUNT(*) as count FROM coi_campaign_employees WHERE campaign_id = %s", 
            (self.id,)
        ).fetchone()['count']
        
        # Completed (Approved)
        completed = db.execute(
            "SELECT COUNT(*) as count FROM coi_campaign_employees WHERE campaign_id = %s AND status = 'completed'", 
            (self.id,)
        ).fetchone()['count']
        
        # Submitted (Under Review)
        submitted = db.execute(
            "SELECT COUNT(*) as count FROM coi_campaign_employees WHERE campaign_id = %s AND status = 'submitted'", 
            (self.id,)
        ).fetchone()['count']
        
        # Pending (Not Started)
        pending = total - completed - submitted
        
        # Overdue (if today > end_date and not completed)
        overdue = 0
        end_date_obj = self.end_date
        if isinstance(end_date_obj, str):
            try:
                end_date_obj = datetime.strptime(end_date_obj, '%Y-%m-%d').date()
            except ValueError:
                end_date_obj = datetime.now().date() # Fallback if format is wrong
        
        if datetime.now().date() > end_date_obj:
            overdue = pending
        
        completion_rate = 0
        if total > 0:
            completion_rate = round((completed / total) * 100)
            
        return {
            'total_employees': total,
            'completed': completed,
            'submitted': submitted,
            'pending': pending,
            'overdue': overdue,
            'completion_rate': completion_rate
        }
    
    def get_employee_status(self, employee_id):
        """Get specific employee's status in campaign"""
        db = get_db()
        row = db.execute(
            "SELECT status FROM coi_campaign_employees WHERE campaign_id = %s AND employee_id = %s", 
            (self.id, employee_id)
        ).fetchone()
        return row['status'] if row else None
    
    def add_employee(self, employee_id):
        """Add employee to campaign"""
        db = get_db()
        try:
            db.execute('''
                INSERT INTO coi_campaign_employees (campaign_id, employee_id, status)
                VALUES (%s, %s, 'pending')
            ''', (self.id, employee_id))
            db.commit()
        except Exception:
            pass # Already exists
    
    def get_members(self):
        """Get all employees in campaign with status"""
        db = get_db()
        sql = '''
            SELECT 
                u.id as user_id,
                u.first_name,
                u.last_name,
                u.department,
                u.email,
                ce.status as participation_status,
                ce.completed_date,
                d.id as declaration_id,
                d.status as declaration_status
            FROM coi_campaign_employees ce
            JOIN users u ON ce.employee_id = u.id
            LEFT JOIN coi_declarations d 
                ON ce.campaign_id = d.campaign_id AND ce.employee_id = d.employee_id
            WHERE ce.campaign_id = %s
            ORDER BY 
                CASE WHEN ce.status = 'pending' THEN 0 ELSE 1 END,
                u.department, 
                u.last_name
        '''
        rows = db.execute(sql, (self.id,)).fetchall()
        
        members = []
        for row in rows:
            members.append({
                'user_id': row['user_id'],
                'employee_name': f"{row['first_name']} {row['last_name']}",
                'department': row['department'] or 'N/A',
                'email': row['email'],
                'participation_status': row['participation_status'],
                'completed_date': row['completed_date'],
                'declaration_id': row['declaration_id'],
                'declaration_status': row['declaration_status']
            })
        return members

    def send_reminders(self):
        """Send reminders to pending employees"""
        db = get_db()
        # In a real app, this would send emails.
        # Here we just flag that reminders were sent.
        db.execute('''
            UPDATE coi_campaign_employees 
            SET reminder_sent = 1, reminder_date = CURRENT_TIMESTAMP
            WHERE campaign_id = %s AND status = 'pending'
        ''', (self.id,))
        db.commit()


class COIMitigationPlan:
    def __init__(self, id=None, declaration_id=None, mitigation_strategy=None,
                 plan_details=None, assigned_to=None, target_date=None,
                 status='active', reviewer_comments=None, created_at=None,
                 updated_at=None, created_by=None, assignee_name=None, **kwargs):
        self.id = id
        self.declaration_id = declaration_id
        self.mitigation_strategy = mitigation_strategy
        self.plan_details = plan_details
        self.assigned_to = assigned_to
        self.target_date = target_date
        self.status = status
        self.reviewer_comments = reviewer_comments
        self.created_at = created_at
        self.updated_at = updated_at
        self.created_by = created_by
        self.assignee_name = assignee_name

    @staticmethod
    def create(data, created_by):
        """Create new COI mitigation plan"""
        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute('''
                INSERT INTO coi_mitigation_plans (
                    declaration_id, mitigation_strategy, plan_details,
                    assigned_to, target_date, status, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            ''', (
                data['declaration_id'],
                data['mitigation_strategy'],
                data['plan_details'],
                data.get('assigned_to'),
                data.get('target_date'),
                'active',
                created_by
            ))
            plan_id = cursor.fetchone()[0]
            
            
            # Link to declaration and update its status
            cursor.execute('''
                UPDATE coi_declarations 
                SET mitigation_plan_id = %s, status = 'mitigation_in_progress'
                WHERE id = %s
            ''', (plan_id, data['declaration_id']))
            
            # Log creation in history
            cursor.execute('''
                INSERT INTO coi_mitigation_history (
                    mitigation_plan_id, action, action_by, old_status, new_status, comments
                ) VALUES (%s, 'created', %s, NULL, 'active', 'Mitigation plan created')
            ''', (plan_id, created_by))
            
            # Also log in declaration history for unified view
            COIDeclarationHistory.log(
                declaration_id=data['declaration_id'],
                action='mitigation_plan_created',
                performer_id=created_by,
                status_before='under_review',
                status_after='mitigation_in_progress',
                comments=f"Mitigation plan created: {data['mitigation_strategy']}"
            )
            
            db.commit()
            return plan_id
        except Exception as e:
            db.rollback()
            raise e

    @staticmethod
    def get_by_id(plan_id):
        """Get mitigation plan by ID"""
        db = get_db()
        sql = '''
            SELECT p.*, u.first_name || ' ' || u.last_name as assignee_name
            FROM coi_mitigation_plans p
            LEFT JOIN users u ON p.assigned_to = u.id
            WHERE p.id = %s
        '''
        row = db.execute(sql, (plan_id,)).fetchone()
        if not row:
            return None
        return COIMitigationPlan(**dict(row))

    @staticmethod
    def get_by_declaration(declaration_id):
        """Get mitigation plan for a declaration"""
        db = get_db()
        sql = '''
            SELECT p.*, u.first_name || ' ' || u.last_name as assignee_name
            FROM coi_mitigation_plans p
            LEFT JOIN users u ON p.assigned_to = u.id
            WHERE p.declaration_id = %s
            ORDER BY p.created_at DESC LIMIT 1
        '''
        row = db.execute(sql, (declaration_id,)).fetchone()
        if not row:
            return None
        return COIMitigationPlan(**dict(row))

    def update_status(self, status, comments=None, updated_by=None):
        """Update mitigation plan status"""
        db = get_db()
        old_status = self.status
        
        db.execute('''
            UPDATE coi_mitigation_plans 
            SET status = %s, reviewer_comments = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (status, comments, self.id))
        
        # Log status change in history
        db.execute('''
            INSERT INTO coi_mitigation_history (
                mitigation_plan_id, action, action_by, old_status, new_status, comments
            ) VALUES (%s, 'status_change', %s, %s, %s, %s)
        ''', (self.id, updated_by, old_status, status, comments))
        
        # If closed, we might want to update the declaration status to 'approved' or 'closed'
        if status == 'closed':
            # Log closure action
            db.execute('''
                INSERT INTO coi_mitigation_history (
                    mitigation_plan_id, action, action_by, old_status, new_status, comments
                ) VALUES (%s, 'closed', %s, %s, %s, 'Plan closed and declaration approved')
            ''', (self.id, updated_by, status, 'closed'))
            
            # Also log in declaration history
            COIDeclarationHistory.log(
                declaration_id=self.declaration_id,
                action='mitigation_plan_closed',
                performer_id=updated_by,
                status_before='mitigation_in_progress',
                status_after='approved',
                comments='Mitigation plan closed and declaration approved'
            )
            
            # Update declaration status
            db.execute('''
                UPDATE coi_declarations 
                SET status = 'approved'
                WHERE id = %s
            ''', (self.declaration_id,))
            
            # Update campaign employee status
            # We need to get campaign_id and employee_id from the declaration
            decl = db.execute('SELECT campaign_id, employee_id FROM coi_declarations WHERE id = %s', (self.declaration_id,)).fetchone()
            if decl:
                db.execute('''
                    UPDATE coi_campaign_employees
                    SET status = 'completed', completed_date = CURRENT_TIMESTAMP
                    WHERE campaign_id = %s AND employee_id = %s
                ''', (decl['campaign_id'], decl['employee_id']))
        else:
            # Just log status change in declaration history
            COIDeclarationHistory.log(
                declaration_id=self.declaration_id,
                action='mitigation_update',
                performer_id=updated_by,
                status_before='mitigation_in_progress',
                status_after='mitigation_in_progress',
                comments=f"Mitigation plan status updated to {status}: {comments}"
            )
            
        db.commit()
        self.status = status
        
    def get_history(self):
        """Get history of actions on this plan"""
        db = get_db()
        sql = '''
            SELECT h.*, u.first_name || ' ' || u.last_name as action_by_name
            FROM coi_mitigation_history h
            LEFT JOIN users u ON h.action_by = u.id
            WHERE h.mitigation_plan_id = %s
            ORDER BY h.action_date DESC
        '''
        rows = db.execute(sql, (self.id,)).fetchall()
        return [dict(row) for row in rows]


class COIDeclarationHistory:
    """Model for COI declaration history"""
    def __init__(self, id=None, declaration_id=None, action=None, performer_id=None,
                 performer_name=None, status_before=None, status_after=None,
                 comments=None, created_at=None, **kwargs):
        self.id = id
        self.declaration_id = declaration_id
        self.action = action
        self.performer_id = performer_id
        self.performer_name = performer_name
        self.status_before = status_before
        self.status_after = status_after
        self.comments = comments
        self.created_at = created_at

    @staticmethod
    def log(declaration_id, action, performer_id=None, status_before=None, 
            status_after=None, comments=None):
        """Log an action in the declaration history"""
        db = get_db()
        db.execute('''
            INSERT INTO coi_declaration_history (
                declaration_id, action, performer_id, status_before, status_after, comments
            ) VALUES (%s, %s, %s, %s, %s, %s)
        ''', (declaration_id, action, performer_id, status_before, status_after, comments))
        db.commit()

    @staticmethod
    def get_by_declaration(declaration_id):
        """Get history for a specific declaration"""
        db = get_db()
        sql = '''
            SELECT h.*, u.first_name || ' ' || u.last_name as performer_name
            FROM coi_declaration_history h
            LEFT JOIN users u ON h.performer_id = u.id
            WHERE h.declaration_id = %s
            ORDER BY h.created_at DESC
        '''
        rows = db.execute(sql, (declaration_id,)).fetchall()
        return [COIDeclarationHistory(**dict(row)) for row in rows]


class COIDeclaration:
    def __init__(self, id=None, campaign_id=None, employee_id=None, employee_name=None, department=None,
                 declaration_date=None, has_financial_interests=False,
                 financial_interests_details=None, has_family_in_competitor=False,
                 family_competitor_details=None, has_family_in_supplier=False,
                 family_supplier_details=None, has_outside_employment=False,
                 outside_employment_details=None, has_received_gifts=False,
                 gifts_details=None, has_other_conflicts=False,
                 other_conflicts_details=None, declaration_statement=None,
                 digital_signature=None, status='pending', reviewer_id=None,
                 review_date=None, review_comments=None, pin_code=None,
                 created_at=None, updated_at=None, mitigation_plan_id=None, **kwargs):
        self.id = id
        self.campaign_id = campaign_id
        self.employee_id = employee_id
        self.employee_name = employee_name # Joined field
        self.department = department # Joined field
        self.declaration_date = declaration_date
        self.mitigation_plan_id = mitigation_plan_id
        
        # Boolean conversion for SQLite (0/1)
        self.has_financial_interests = bool(has_financial_interests)
        self.has_family_in_competitor = bool(has_family_in_competitor)
        self.has_family_in_supplier = bool(has_family_in_supplier)
        self.has_outside_employment = bool(has_outside_employment)
        self.has_received_gifts = bool(has_received_gifts)
        self.has_other_conflicts = bool(has_other_conflicts)
        
        self.financial_interests_details = financial_interests_details
        self.family_competitor_details = family_competitor_details
        self.family_supplier_details = family_supplier_details
        self.outside_employment_details = outside_employment_details
        self.gifts_details = gifts_details
        self.other_conflicts_details = other_conflicts_details
        
        self.declaration_statement = declaration_statement
        self.digital_signature = digital_signature
        self.status = status
        self.reviewer_id = reviewer_id
        self.review_date = review_date
        self.review_comments = review_comments
        self.pin_code = pin_code
        self.created_at = created_at
        self.updated_at = updated_at
        # Ad-hoc disclosure fields (portal form)
        self.conflict_type = kwargs.get('conflict_type')
        self.details = kwargs.get('details')
        self.parties_involved = kwargs.get('parties_involved')
        self.mitigation_plan = kwargs.get('mitigation_plan')
        # Who the declaration was escalated to (may lack the COI module permission;
        # gets scoped access to this declaration only — see coi/routes.py).
        self.escalated_to = kwargs.get('escalated_to')
        self.escalated_by = kwargs.get('escalated_by')
        self.escalated_at = kwargs.get('escalated_at')
    
    @staticmethod
    def create(data, employee_id):
        """Create new COI declaration"""
        db = get_db()
        
        # Determine status logic
        has_conflict = (
            data.get('has_financial_interests') or
            data.get('has_family_in_competitor') or
            data.get('has_family_in_supplier') or
            data.get('has_outside_employment') or
            data.get('has_received_gifts') or
            data.get('has_other_conflicts')
        )
        
        initial_status = 'under_review' # Always require review
        
        # Generate random 4-digit PIN
        import random
        pin_code = ''.join([str(random.randint(0, 9)) for _ in range(4)])
        
        cursor = db.cursor()
        try:
            cursor.execute('''
                INSERT INTO coi_declarations (
                    campaign_id, employee_id, declaration_date,
                    has_financial_interests, financial_interests_details,
                    has_family_in_competitor, family_competitor_details,
                    has_family_in_supplier, family_supplier_details,
                    has_outside_employment, outside_employment_details,
                    has_received_gifts, gifts_details,
                    has_other_conflicts, other_conflicts_details,
                    declaration_statement, digital_signature,
                    status, pin_code,
                    has_conflict, conflict_type, details, parties_involved, mitigation_plan, created_at
                ) VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, CURRENT_TIMESTAMP) RETURNING id
            ''', (
                data['campaign_id'],
                employee_id,
                1 if data.get('has_financial_interests') else 0,
                data.get('financial_interests_details'),
                1 if data.get('has_family_in_competitor') else 0,
                data.get('family_competitor_details'),
                1 if data.get('has_family_in_supplier') else 0,
                data.get('family_supplier_details'),
                1 if data.get('has_outside_employment') else 0,
                data.get('outside_employment_details'),
                1 if data.get('has_received_gifts') else 0,
                data.get('gifts_details'),
                1 if data.get('has_other_conflicts') else 0,
                data.get('other_conflicts_details'),
                "I agree to the declaration statement",
                data['digital_signature'],
                initial_status,
                pin_code,
                1 if has_conflict or data.get('conflict_type') else 0,
                data.get('conflict_type'),
                data.get('details'),
                data.get('parties_involved'),
                data.get('mitigation_plan'),
            ))
            
            declaration_id = cursor.fetchone()[0]
            
            # Update OR INSERT employee status in campaign
            # Set to 'submitted' - not 'completed' until approved
            cursor.execute('''
                INSERT INTO coi_campaign_employees (campaign_id, employee_id, status, completed_date)
                VALUES (%s, %s, 'submitted', CURRENT_TIMESTAMP)
                ON CONFLICT(campaign_id, employee_id) DO UPDATE SET
                status = 'submitted',
                completed_date = CURRENT_TIMESTAMP
            ''', (data['campaign_id'], employee_id))
            
            # Log in history
            COIDeclarationHistory.log(
                declaration_id=declaration_id,
                action='submitted',
                performer_id=employee_id,
                status_before=None,
                status_after=initial_status,
                comments='Form submitted by employee'
            )
            
            db.commit()
            return declaration_id, pin_code
        except Exception as e:
            db.rollback()
            raise e
    
    @staticmethod
    def get_by_id(declaration_id):
        """Get declaration by ID"""
        db = get_db()
        sql = '''
            SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.department
            FROM coi_declarations d
            JOIN users u ON d.employee_id = u.id
            WHERE d.id = %s
        '''
        row = db.execute(sql, (declaration_id,)).fetchone()
        if not row:
            return None
        return COIDeclaration(**dict(row))
    
    @staticmethod
    def get_by_employee_campaign(employee_id, campaign_id):
        """Get employee's declaration for specific campaign"""
        db = get_db()
        row = db.execute(
            "SELECT * FROM coi_declarations WHERE employee_id = %s AND campaign_id = %s", 
            (employee_id, campaign_id)
        ).fetchone()
        if not row:
            return None
        return COIDeclaration(**dict(row))
    
    @staticmethod
    def get_pending_for_manager(manager_id):
        """Get declarations pending manager review"""
        db = get_db()
        sql = '''
            SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.department, c.campaign_name
            FROM coi_declarations d
            JOIN users u ON d.employee_id = u.id
            JOIN coi_campaigns c ON d.campaign_id = c.id
            WHERE u.manager_id = %s AND d.status IN ('submitted', 'under_review', 'requires_clarification', 'mitigation_in_progress', 'escalated')
            ORDER BY d.created_at DESC
        '''
        rows = db.execute(sql, (manager_id,)).fetchall()
        
        declarations = []
        for row in rows:
            decl = COIDeclaration(**dict(row))
            # Attach campaign name (hacky but works for template)
            decl.campaign_name = row['campaign_name']
            declarations.append(decl)
        return declarations
    
    @staticmethod
    def get_pending_for_compliance():
        """Get declarations pending compliance review"""
        db = get_db()
        sql = '''
            SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.department, c.campaign_name
            FROM coi_declarations d
            JOIN users u ON d.employee_id = u.id
            JOIN coi_campaigns c ON d.campaign_id = c.id
            WHERE d.status IN ('submitted', 'under_review', 'requires_clarification', 'mitigation_in_progress')
            ORDER BY d.created_at DESC
        '''
        rows = db.execute(sql).fetchall()
        
        declarations = []
        for row in rows:
            row_dict = dict(row)
            campaign_name = row_dict.pop('campaign_name', None)
            decl = COIDeclaration(**row_dict)
            decl.campaign_name = campaign_name
            declarations.append(decl)
        return declarations
    
    def approve(self, reviewer_id, comments=None):
        """Approve declaration"""
        db = get_db()
        old_status = self.status
        db.execute('''
            UPDATE coi_declarations 
            SET status = 'approved', reviewer_id = %s, review_date = CURRENT_TIMESTAMP, review_comments = %s
            WHERE id = %s
        ''', (reviewer_id, comments, self.id))
        
        # Also update the campaign_employee status to completed
        db.execute('''
            UPDATE coi_campaign_employees
            SET status = 'completed', completed_date = CURRENT_TIMESTAMP
            WHERE campaign_id = %s AND employee_id = %s
        ''', (self.campaign_id, self.employee_id))
        
        # Log in history
        COIDeclarationHistory.log(
            declaration_id=self.id,
            action='approved',
            performer_id=reviewer_id,
            status_before=old_status,
            status_after='approved',
            comments=comments
        )
        
        db.commit()
    
    def request_clarification(self, reviewer_id, comments):
        """Request clarification from employee"""
        db = get_db()
        old_status = self.status
        db.execute('''
            UPDATE coi_declarations 
            SET status = 'requires_clarification', reviewer_id = %s, review_date = CURRENT_TIMESTAMP, review_comments = %s
            WHERE id = %s
        ''', (reviewer_id, comments, self.id))
        
        # Log in history
        COIDeclarationHistory.log(
            declaration_id=self.id,
            action='clarification_requested',
            performer_id=reviewer_id,
            status_before=old_status,
            status_after='requires_clarification',
            comments=comments
        )
        
        db.commit()
    
    def escalate(self, reviewer_id, comments, escalated_to=None):
        """Escalate to management (considered a terminal state/closed case for compliance)"""
        db = get_db()
        old_status = self.status
        db.execute('''
            UPDATE coi_declarations 
            SET status = 'escalated', reviewer_id = %s, review_date = CURRENT_TIMESTAMP, review_comments = %s,
                escalated_to = %s, escalated_by = %s, escalated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (reviewer_id, comments, escalated_to, reviewer_id, self.id))
        self.escalated_to = escalated_to
        
        # Also update the campaign_employee status to completed since it's "closed"
        db.execute('''
            UPDATE coi_campaign_employees
            SET status = 'completed'
            WHERE campaign_id = %s AND employee_id = %s
        ''', (self.campaign_id, self.employee_id))
        
        # Log in history
        COIDeclarationHistory.log(
            declaration_id=self.id,
            action='escalated',
            performer_id=reviewer_id,
            status_before=old_status,
            status_after='escalated',
            comments=comments
        )
        
        db.commit()
    
    def has_conflicts(self):
        """Check if declaration has any conflicts"""
        return (self.has_financial_interests or 
                self.has_family_in_competitor or 
                self.has_family_in_supplier or 
                self.has_outside_employment or 
                self.has_received_gifts or 
                self.has_other_conflicts)

    def get_history(self):
        """Get activity log for this declaration"""
        return COIDeclarationHistory.get_by_declaration(self.id)
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'status': self.status,
            'declaration_date': self.declaration_date
        }
