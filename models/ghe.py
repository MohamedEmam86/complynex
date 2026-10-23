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
GHE (Gift, Hospitality & Entertainment) Model
Handles GHE declarations with approval workflow logic.
"""
import sqlite3
from datetime import datetime, date
from database.db import get_db


class GHEDeclaration:
    """Model for GHE (Gift, Hospitality & Entertainment) declarations."""
    
    # Approval thresholds (in EGP)
    AUTO_APPROVE_THRESHOLD = 500
    MANAGER_APPROVAL_THRESHOLD = 2000
    
    def __init__(self, id=None, declaration_number=None, employee_id=None, 
                 declaration_date=None, ghe_type=None, direction=None,
                 event_date=None, estimated_value_egp=None, currency='EGP',
                 description=None, provider_recipient_name=None, 
                 provider_recipient_company=None, business_purpose=None,
                 is_government_official=False, government_official_details=None,
                 status='pending', auto_approved=False, manager_id=None,
                 manager_approval_date=None, manager_comments=None,
                 compliance_officer_id=None, compliance_approval_date=None,
                 compliance_comments=None, attachment_path=None,
                 created_at=None, updated_at=None, created_by=None, updated_by=None,
                 # Public submission fields
                 submitter_email=None, submitter_name=None, submitter_department=None,
                 tracking_id=None, is_public_submission=False,
                 # Info request fields
                 needs_more_info=False, info_request_message=None, info_request_date=None,
                 info_response=None, info_response_date=None,
                 # Joined fields
                 employee_name=None, department=None, 
                 manager_name=None, compliance_officer_name=None, **kwargs):
        self.id = id
        self.declaration_number = declaration_number
        self.employee_id = employee_id
        self.declaration_date = declaration_date
        self.ghe_type = ghe_type
        self.direction = direction
        self.event_date = event_date
        self.estimated_value_egp = float(estimated_value_egp) if estimated_value_egp else 0.0
        self.currency = currency
        self.description = description
        self.provider_recipient_name = provider_recipient_name
        self.provider_recipient_company = provider_recipient_company
        self.business_purpose = business_purpose
        self.is_government_official = bool(is_government_official)
        self.government_official_details = government_official_details
        self.government_official_position = kwargs.get('government_official_position')
        self.status = status
        self.auto_approved = bool(auto_approved)
        self.manager_id = manager_id
        self.manager_approval_date = manager_approval_date
        self.manager_comments = manager_comments
        self.compliance_officer_id = compliance_officer_id
        self.compliance_approval_date = compliance_approval_date
        self.compliance_comments = compliance_comments
        self.attachment_path = attachment_path
        self.created_at = created_at
        self.updated_at = updated_at
        self.created_by = created_by
        self.updated_by = updated_by
        # Public submission fields
        self.submitter_email = submitter_email
        self.submitter_name = submitter_name
        self.submitter_department = submitter_department
        self.tracking_id = tracking_id
        self.is_public_submission = bool(is_public_submission)
        # Info request fields
        self.needs_more_info = bool(needs_more_info)
        self.info_request_message = info_request_message
        self.info_request_date = info_request_date
        self.info_response = info_response
        self.info_response_date = info_response_date
        # Joined fields
        self.employee_name = employee_name
        self.department = department
        self.manager_name = manager_name
        self.compliance_officer_name = compliance_officer_name
    
    @staticmethod
    def generate_declaration_number():
        """Generate unique declaration number: GHE-YYYYMMDD-XXXX"""
        db = get_db()
        today = datetime.now().strftime('%Y%m%d')
        prefix = f'GHE-{today}-'
        
        # Get the last declaration number for today
        result = db.execute(
            '''SELECT declaration_number FROM ghe_declarations 
               WHERE declaration_number LIKE %s 
               ORDER BY declaration_number DESC LIMIT 1''',
            (f'{prefix}%',)
        ).fetchone()
        
        if result:
            # Extract the sequence number and increment
            last_num = int(result['declaration_number'].split('-')[-1])
            seq = last_num + 1
        else:
            seq = 1
        
        return f'{prefix}{seq:04d}'
    
    @staticmethod
    def get_setting(key, default=None):
        """Fetch a system setting value."""
        db = get_db()
        row = db.execute('SELECT setting_value FROM system_settings WHERE setting_key = %s', (key,)).fetchone()
        return row['setting_value'] if row else default

    @staticmethod
    def get_cumulative_value(user_id, partner_name=None, year=None):
        """
        Calculate the cumulative GHE value for a user within a calendar year.
        If partner_name is provided, calculates specifically for that partner.
        """
        db = get_db()
        if not year:
            year = datetime.now().year
            
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        
        query = '''
            SELECT SUM(estimated_value_egp) as total 
            FROM ghe_declarations 
            WHERE employee_id = %s 
            AND status NOT IN ('rejected', 'cancelled')
            AND event_date BETWEEN %s AND %s
        '''
        params = [user_id, start_date, end_date]
        
        if partner_name:
            query += ' AND provider_recipient_name = %s'
            params.append(partner_name)
            
        result = db.execute(query, params).fetchone()
        return float(result['total']) if result and result['total'] else 0.0

    @staticmethod
    def determine_approval_workflow(value, is_government_official, employee_manager_id, cumulative_total=0.0):
        """
        Determine the approval workflow based on value, government official flag, and cumulative annual totals.
        
        Returns tuple: (status, auto_approved, manager_id, escalation_reason)
        """
        # Rule 1: Government official always goes to compliance review
        if is_government_official:
            return ('compliance_review', False, None, 'Government Official involvement')
        
        # Fetch dynamic thresholds
        auto_approve_threshold = float(GHEDeclaration.get_setting('ghe_auto_approve_threshold', 500))
        manager_approval_threshold = float(GHEDeclaration.get_setting('ghe_manager_approval_threshold', 2000))
        annual_limit_threshold = float(GHEDeclaration.get_setting('ghe_annual_limit_threshold', 5000))
        
        # Rule 2: Cumulative limit check (Auto-escalate to compliance if annual limit exceeded)
        if cumulative_total + value > annual_limit_threshold:
            return ('compliance_review', False, None, f'Annual cumulative limit ({annual_limit_threshold} EGP) exceeded')
            
        # Rule 3: Auto-approve if below threshold
        if value < auto_approve_threshold:
            return ('approved', True, None, None)
        
        # Rule 4: Manager approval for medium value
        if value <= manager_approval_threshold:
            return ('manager_review', False, employee_manager_id, None)
        
        # Rule 5: Compliance approval for high value
        return ('compliance_review', False, None, 'Value exceeds manager approval threshold')
    
    @staticmethod
    def create(data, employee_id, created_by=None):
        """
        Create new GHE declaration with automatic approval logic and cumulative tracking.
        """
        from models.user import User
        
        db = get_db()
        
        # Get employee's manager
        employee = User.get_by_id(employee_id)
        manager_id = employee.manager_id if employee else None
        
        # Parse values
        value = float(data.get('estimated_value_egp', 0))
        is_gov = data.get('is_government_official') in [True, 'on', '1', 1]
        
        # Calculate cumulative total for the year
        cumulative_total = GHEDeclaration.get_cumulative_value(employee_id)
        
        # Determine approval workflow
        status, auto_approved, assigned_manager, escalation_reason = GHEDeclaration.determine_approval_workflow(
            value, is_gov, manager_id, cumulative_total
        )
        
        import uuid
        
        # Generate declaration number
        declaration_number = GHEDeclaration.generate_declaration_number()
        
        # Generate tracking ID
        tracking_id = str(uuid.uuid4())
        
        # Insert declaration
        cursor = db.execute(
            '''INSERT INTO ghe_declarations 
               (declaration_number, employee_id, declaration_date, ghe_type, direction,
                event_date, estimated_value_egp, currency, description,
                provider_recipient_name, provider_recipient_company, business_purpose,
                is_government_official, government_official_details, government_official_position,
                status, auto_approved, manager_id, attachment_path,
                created_at, created_by, tracking_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (
                declaration_number,
                employee_id,
                datetime.now().strftime('%Y-%m-%d'),
                data.get('ghe_type'),
                data.get('direction'),
                data.get('event_date'),
                value,
                data.get('currency', 'EGP'),
                data.get('description'),
                data.get('provider_recipient_name'),
                data.get('provider_recipient_company'),
                data.get('business_purpose'),
                1 if is_gov else 0,
                data.get('government_official_details') if is_gov else None,
                data.get('government_official_position') if is_gov else None,
                status,
                1 if auto_approved else 0,
                assigned_manager,
                data.get('attachment_path'),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                created_by or employee_id,
                tracking_id
            )
        )
        db.commit()
        
        declaration_id = cursor.fetchone()[0]
        
        # Log the creation action with escalation reason
        comments = f'Declaration submitted with value {value} EGP.'
        if escalation_reason:
            comments += f' Escalation reason: {escalation_reason}.'
        if cumulative_total > 0:
            comments += f' YTD Cumulative: {cumulative_total} EGP.'

        GHEApprovalHistory.log_action(
            declaration_id=declaration_id,
            action='Created' if not auto_approved else 'Auto-approved',
            action_by=created_by or employee_id,
            comments=comments,
            old_status=None,
            new_status=status
        )
        
        return GHEDeclaration.get_by_id(declaration_id)
    
    @staticmethod
    def get_by_id(declaration_id):
        """Get single declaration by ID with joined user names."""
        db = get_db()
        
        row = db.execute(
            '''SELECT g.*,
                      u.first_name || ' ' || u.last_name as employee_name,
                      u.department,
                      m.first_name || ' ' || m.last_name as manager_name,
                      c.first_name || ' ' || c.last_name as compliance_officer_name
               FROM ghe_declarations g
               LEFT JOIN users u ON g.employee_id = u.id
               LEFT JOIN users m ON g.manager_id = m.id
               LEFT JOIN users c ON g.compliance_officer_id = c.id
               WHERE g.id = %s''',
            (declaration_id,)
        ).fetchone()
        
        if row:
            return GHEDeclaration(**dict(row))
        return None
    
    @staticmethod
    def get_by_employee(employee_id, status=None):
        """Get all declarations for an employee, optionally filtered by status."""
        db = get_db()
        
        if status:
            rows = db.execute(
                '''SELECT g.*,
                          u.first_name || ' ' || u.last_name as employee_name,
                          u.department
                   FROM ghe_declarations g
                   LEFT JOIN users u ON g.employee_id = u.id
                   WHERE g.employee_id = %s AND g.status = %s
                   ORDER BY g.created_at DESC''',
                (employee_id, status)
            ).fetchall()
        else:
            rows = db.execute(
                '''SELECT g.*,
                          u.first_name || ' ' || u.last_name as employee_name,
                          u.department
                   FROM ghe_declarations g
                   LEFT JOIN users u ON g.employee_id = u.id
                   WHERE g.employee_id = %s
                   ORDER BY g.created_at DESC''',
                (employee_id,)
            ).fetchall()
        
        return [GHEDeclaration(**dict(row)) for row in rows]
    
    @staticmethod
    def get_pending_for_manager(manager_id):
        """Get declarations pending manager approval for a specific manager's team."""
        db = get_db()
        
        # Get team member IDs (employees who have this manager)
        team_members = db.execute(
            '''SELECT id FROM users WHERE manager_id = %s''',
            (manager_id,)
        ).fetchall()
        team_ids = [m['id'] for m in team_members]
        
        if not team_ids:
            return []
        
        placeholders = ','.join(['%s'] * len(team_ids))
        rows = db.execute(
            f'''SELECT g.*,
                       u.first_name || ' ' || u.last_name as employee_name,
                       u.department
                FROM ghe_declarations g
                LEFT JOIN users u ON g.employee_id = u.id
                WHERE g.status = 'manager_review'
                AND g.employee_id IN ({placeholders})
                ORDER BY g.created_at DESC''',
            team_ids
        ).fetchall()
        
        return [GHEDeclaration(**dict(row)) for row in rows]
    
    @staticmethod
    def get_pending_for_compliance():
        """Get declarations pending compliance approval."""
        db = get_db()
        
        rows = db.execute(
            '''SELECT g.*,
                      u.first_name || ' ' || u.last_name as employee_name,
                      u.department
               FROM ghe_declarations g
               LEFT JOIN users u ON g.employee_id = u.id
               WHERE g.status = 'compliance_review'
               ORDER BY g.created_at DESC'''
        ).fetchall()
        
        return [GHEDeclaration(**dict(row)) for row in rows]
    
    @staticmethod
    def get_all(filters=None, limit=50, offset=0):
        """Get all declarations with optional filters."""
        db = get_db()
        
        query = '''SELECT g.*,
                          u.first_name || ' ' || u.last_name as employee_name,
                          u.department
                   FROM ghe_declarations g
                   LEFT JOIN users u ON g.employee_id = u.id
                   WHERE 1=1'''
        params = []
        
        if filters:
            if filters.get('status'):
                query += ' AND g.status = %s'
                params.append(filters['status'])
            
            if filters.get('ghe_type'):
                query += ' AND g.ghe_type = %s'
                params.append(filters['ghe_type'])
            
            if filters.get('date_from'):
                query += ' AND g.declaration_date >= %s'
                params.append(filters['date_from'])
            
            if filters.get('date_to'):
                query += ' AND g.declaration_date <= %s'
                params.append(filters['date_to'])
            
            if filters.get('employee_id'):
                query += ' AND g.employee_id = %s'
                params.append(filters['employee_id'])
        
        query += ' ORDER BY g.created_at DESC LIMIT %s OFFSET %s'
        params.extend([limit, offset])
        
        rows = db.execute(query, params).fetchall()
        return [GHEDeclaration(**dict(row)) for row in rows]
    
    @staticmethod
    def get_statistics(employee_id=None):
        """
        Get dashboard statistics including YTD totals.
        """
        db = get_db()
        year = datetime.now().year
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        
        where_clause = ""
        params = []
        if employee_id:
            where_clause = " WHERE employee_id = %s"
            params = [employee_id]
            
        # 1. Get counts by status
        rows = db.execute(
            f'''SELECT status, COUNT(*) as count 
                FROM ghe_declarations{where_clause}
                GROUP BY status''',
            params
        ).fetchall()
        
        stats = {
            'total': 0, 'pending': 0, 'manager_review': 0, 
            'compliance_review': 0, 'approved': 0, 'rejected': 0,
            'requires_clarification': 0, 'total_value_ytd': 0.0,
            'monthly_trend': {}
        }
        
        for row in rows:
            st = row['status']
            if st in stats:
                stats[st] = row['count']
                stats['total'] += row['count']
        
        # 2. Get YTD Total Value
        ytd_query = f'''
            SELECT SUM(estimated_value_egp) as total 
            FROM ghe_declarations 
            WHERE status NOT IN ('rejected', 'cancelled') 
            AND event_date BETWEEN %s AND %s
        '''
        ytd_params = [start_date, end_date]
        if employee_id:
            ytd_query += " AND employee_id = %s"
            ytd_params.append(employee_id)
            
        result = db.execute(ytd_query, ytd_params).fetchone()
        stats['total_value_ytd'] = float(result['total']) if result and result['total'] else 0.0

        # 3. Get monthly trend
        trend_query = f'''
            SELECT TO_CHAR(event_date::DATE, 'MM') as month, SUM(estimated_value_egp) as value
            FROM ghe_declarations
            WHERE status != 'rejected' AND event_date BETWEEN %s AND %s
        '''
        trend_params = [start_date, end_date]
        if employee_id:
            trend_query += " AND employee_id = %s"
            trend_params.append(employee_id)
        
        trend_query += " GROUP BY month ORDER BY month"
        trend_rows = db.execute(trend_query, trend_params).fetchall()
        stats['monthly_trend'] = {row['month']: row['value'] for row in trend_rows}
        
        return stats
    
    @staticmethod
    def get_employee_stats(employee_id):
        """Get statistics specific to an employee."""
        stats = GHEDeclaration.get_statistics(employee_id)
        
        # Calculate "under review" as manager_review + compliance_review
        stats['under_review'] = stats['manager_review'] + stats['compliance_review']
        
        return stats
    
    def approve(self, approver_id, approver_role, comments=None):
        """
        Approve declaration.
        
        Args:
            approver_id: ID of the approver
            approver_role: Role of approver ('manager' or 'compliance_officer')
            comments: Optional approval comments
        
        Returns:
            True if successful
        """
        db = get_db()
        old_status = self.status
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if approver_role == 'manager':
            # Fetch dynamic threshold for escalation
            manager_approval_threshold = float(GHEDeclaration.get_setting('ghe_manager_approval_threshold', 2000))
            
            # Manager approval
            if self.estimated_value_egp > manager_approval_threshold or self.is_government_official:
                # High value or gov official: escalate to compliance
                # (Gov official should have been escalated initially, but check here too as safety)
                new_status = 'compliance_review'
            else:
                # Final approval
                new_status = 'approved'
            
            db.execute(
                '''UPDATE ghe_declarations 
                   SET status = %s, manager_id = %s, manager_approval_date = %s, 
                       manager_comments = %s, updated_at = %s, updated_by = %s
                   WHERE id = %s''',
                (new_status, approver_id, now, comments, now, approver_id, self.id)
            )
        else:
            # Compliance officer approval (final)
            new_status = 'approved'
            db.execute(
                '''UPDATE ghe_declarations 
                   SET status = %s, compliance_officer_id = %s, compliance_approval_date = %s, 
                       compliance_comments = %s, updated_at = %s, updated_by = %s
                   WHERE id = %s''',
                (new_status, approver_id, now, comments, now, approver_id, self.id)
            )
        
        db.commit()
        
        # Log the action
        GHEApprovalHistory.log_action(
            declaration_id=self.id,
            action='Approved' if new_status == 'approved' else 'Escalated to Compliance',
            action_by=approver_id,
            comments=comments,
            old_status=old_status,
            new_status=new_status
        )
        
        self.status = new_status
        return True
    
    def request_clarification(self, requestor_id, requestor_role, comments):
        """
        Request clarification/feedback from employee.
        """
        db = get_db()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Update status to requires_clarification and set flag
        db.execute(
            '''UPDATE ghe_declarations 
               SET status = 'requires_clarification',
                   needs_more_info = 1,
                   info_request_message = %s,
                   info_request_date = %s,
                   updated_at = %s, updated_by = %s
               WHERE id = %s''',
            (comments, now, now, requestor_id, self.id)
        )
        db.commit()
        
        # Log action
        GHEApprovalHistory.log_action(
            declaration_id=self.id,
            action='Request Feedback',
            action_by=requestor_id,
            comments=comments,
            old_status=self.status,
            new_status='requires_clarification'
        )
        
        self.status = 'requires_clarification'
        return True

    def reject(self, approver_id, approver_role, comments):
        """
        Reject declaration.
        
        Args:
            approver_id: ID of the approver
            approver_role: Role of approver
            comments: Required rejection reason
        
        Returns:
            True if successful
        """
        db = get_db()
        old_status = self.status
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if approver_role == 'manager':
            db.execute(
                '''UPDATE ghe_declarations 
                   SET status = 'rejected', manager_id = %s, manager_approval_date = %s, 
                       manager_comments = %s, updated_at = %s, updated_by = %s
                   WHERE id = %s''',
                (approver_id, now, comments, now, approver_id, self.id)
            )
        else:
            db.execute(
                '''UPDATE ghe_declarations 
                   SET status = 'rejected', compliance_officer_id = %s, compliance_approval_date = %s, 
                       compliance_comments = %s, updated_at = %s, updated_by = %s
                   WHERE id = %s''',
                (approver_id, now, comments, now, approver_id, self.id)
            )
        
        db.commit()
        
        # Log the action
        GHEApprovalHistory.log_action(
            declaration_id=self.id,
            action='Rejected',
            action_by=approver_id,
            comments=comments,
            old_status=old_status,
            new_status='rejected'
        )
        
        self.status = 'rejected'
        return True
    
    def update(self, data, updated_by):
        """Update declaration (only if pending)."""
        if self.status not in ['pending', 'manager_review']:
            return False
        
        db = get_db()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Update allowed fields
        db.execute(
            '''UPDATE ghe_declarations 
               SET ghe_type = %s, direction = %s, event_date = %s, 
                   estimated_value_egp = %s, description = %s,
                   provider_recipient_name = %s, provider_recipient_company = %s,
                   business_purpose = %s, is_government_official = %s,
                   government_official_details = %s, updated_at = %s, updated_by = %s
               WHERE id = %s''',
            (
                data.get('ghe_type', self.ghe_type),
                data.get('direction', self.direction),
                data.get('event_date', self.event_date),
                float(data.get('estimated_value_egp', self.estimated_value_egp)),
                data.get('description', self.description),
                data.get('provider_recipient_name', self.provider_recipient_name),
                data.get('provider_recipient_company', self.provider_recipient_company),
                data.get('business_purpose', self.business_purpose),
                1 if data.get('is_government_official') in [True, 'on', '1', 1] else 0,
                data.get('government_official_details', self.government_official_details),
                now,
                updated_by,
                self.id
            )
        )
        db.commit()
        
        # Log the action
        GHEApprovalHistory.log_action(
            declaration_id=self.id,
            action='Updated',
            action_by=updated_by,
            comments='Declaration details updated',
            old_status=self.status,
            new_status=self.status
        )
        
        return True
    
    def delete(self):
        """Delete declaration (only if pending)."""
        if self.status != 'pending':
            return False
        
        db = get_db()
        
        # Delete approval history first
        db.execute(
            'DELETE FROM ghe_approval_history WHERE ghe_declaration_id = %s',
            (self.id,)
        )
        
        # Delete declaration
        db.execute('DELETE FROM ghe_declarations WHERE id = %s', (self.id,))
        db.commit()
        
        return True
    
    def to_dict(self):
        """Convert to dictionary for JSON/templates."""
        return {
            'id': self.id,
            'declaration_number': self.declaration_number,
            'employee_id': self.employee_id,
            'employee_name': self.employee_name,
            'department': self.department,
            'declaration_date': self.declaration_date,
            'ghe_type': self.ghe_type,
            'direction': self.direction,
            'event_date': self.event_date,
            'estimated_value_egp': self.estimated_value_egp,
            'currency': self.currency,
            'description': self.description,
            'provider_recipient_name': self.provider_recipient_name,
            'provider_recipient_company': self.provider_recipient_company,
            'business_purpose': self.business_purpose,
            'is_government_official': self.is_government_official,
            'government_official_details': self.government_official_details,
            'status': self.status,
            'auto_approved': self.auto_approved,
            'manager_id': self.manager_id,
            'manager_name': self.manager_name,
            'manager_approval_date': self.manager_approval_date,
            'manager_comments': self.manager_comments,
            'compliance_officer_id': self.compliance_officer_id,
            'compliance_officer_name': self.compliance_officer_name,
            'compliance_approval_date': self.compliance_approval_date,
            'compliance_comments': self.compliance_comments,
            'attachment_path': self.attachment_path,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            # Public submission fields
            'submitter_email': self.submitter_email,
            'submitter_name': self.submitter_name,
            'submitter_department': self.submitter_department,
            'tracking_id': self.tracking_id,
            'is_public_submission': self.is_public_submission,
            # Info request fields
            'needs_more_info': self.needs_more_info,
            'info_request_message': self.info_request_message,
            'info_request_date': self.info_request_date,
            'info_response': self.info_response,
            'info_response_date': self.info_response_date
        }


class GHEDeclarationHistory:
    """Model for GHE declaration history"""
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
        """Log an action in the GHE declaration history"""
        db = get_db()
        db.execute('''
            INSERT INTO ghe_declaration_history (
                declaration_id, action, performer_id, status_before, status_after, comments
            ) VALUES (%s, %s, %s, %s, %s, %s)
        ''', (declaration_id, action, performer_id, status_before, status_after, comments))
        db.commit()

    @staticmethod
    def get_by_declaration(declaration_id):
        """Get history for a specific GHE declaration"""
        db = get_db()
        sql = '''
            SELECT h.*, u.first_name || ' ' || u.last_name as performer_name
            FROM ghe_declaration_history h
            LEFT JOIN users u ON h.performer_id = u.id
            WHERE h.declaration_id = %s
            ORDER BY h.created_at DESC
        '''
        rows = db.execute(sql, (declaration_id,)).fetchall()
        return [GHEDeclarationHistory(**dict(row)) for row in rows]


class GHEApprovalHistory:
    """Legacy helper for tracking GHE approval history, now using unified history table."""
    
    @staticmethod
    def log_action(declaration_id, action, action_by, comments=None, old_status=None, new_status=None):
        """Log approval action to history (wraps the new system)."""
        GHEDeclarationHistory.log(
            declaration_id=declaration_id,
            action=action,
            performer_id=action_by,
            status_before=old_status,
            status_after=new_status,
            comments=comments
        )
    
    @staticmethod
    def get_history(declaration_id):
        """Get history for a declaration (wraps the new system)."""
        history = GHEDeclarationHistory.get_by_declaration(declaration_id)
        return [vars(h) for h in history]
