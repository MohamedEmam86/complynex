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

from datetime import datetime, date, timedelta
from database.db import get_db

class Regulator:
    def __init__(self, id=None, regulator_name=None, regulator_code=None, 
                 contact_email=None, contact_phone=None, website=None, 
                 description=None, is_active=True, **kwargs):
        self.id = id
        self.regulator_name = regulator_name
        self.regulator_code = regulator_code
        self.contact_email = contact_email
        self.contact_phone = contact_phone
        self.website = website
        self.description = description
        self.is_active = is_active

    @staticmethod
    def get_all(include_inactive=False):
        db = get_db()
        if include_inactive:
            rows = db.execute('SELECT * FROM regulators ORDER BY regulator_name').fetchall()
        else:
            rows = db.execute('SELECT * FROM regulators WHERE is_active = 1 ORDER BY regulator_name').fetchall()
        return [Regulator(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(regulator_id):
        db = get_db()
        row = db.execute('SELECT * FROM regulators WHERE id = %s', (regulator_id,)).fetchone()
        return Regulator(**dict(row)) if row else None

    @staticmethod
    def create(data):
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO regulators (regulator_name, regulator_code, contact_email,
                                  contact_phone, website, description, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('regulator_name'),
            data.get('regulator_code'),
            data.get('contact_email'),
            data.get('contact_phone'),
            data.get('website'),
            data.get('description'),
            1 if data.get('is_active', True) else 0
        ))
        db.commit()
        return cursor.fetchone()['id']

    def update(self, data):
        db = get_db()
        db.execute('''
            UPDATE regulators SET 
            regulator_name = %s, regulator_code = %s, contact_email = %s,
            contact_phone = %s, website = %s, description = %s, is_active = %s
            WHERE id = %s
        ''', (
            data.get('regulator_name', self.regulator_name),
            data.get('regulator_code', self.regulator_code),
            data.get('contact_email', self.contact_email),
            data.get('contact_phone', self.contact_phone),
            data.get('website', self.website),
            data.get('description', self.description),
            int(data.get('is_active', self.is_active)),
            self.id
        ))
        db.commit()


class RegulatoryReport:
    def __init__(self, id=None, report_code=None, report_name=None,
                 regulator_id=None, frequency=None, due_day=None, due_month=None,
                 description=None, submission_method=None, responsible_department=None,
                 cbe_circular_reference=None, regulatory_reference=None, is_active=True, created_at=None, **kwargs):
        self.id = id
        self.report_code = report_code
        self.report_name = report_name
        self.regulator_id = regulator_id
        self.frequency = frequency
        self.due_day = due_day
        self.due_month = due_month
        self.description = description
        self.submission_method = submission_method
        self.responsible_department = responsible_department
        self.cbe_circular_reference = cbe_circular_reference
        # regulatory_reference is the regulator-agnostic replacement for the
        # legacy cbe_circular_reference column; fall back to the old value
        # for any report created before this field existed.
        self.regulatory_reference = regulatory_reference or cbe_circular_reference
        self.is_active = is_active
        self.created_at = created_at
        
        # Helper for templates
        self.regulator_name = kwargs.get('regulator_name')

    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute('''
            SELECT r.*, reg.regulator_name
            FROM regulatory_reports r
            LEFT JOIN regulators reg ON r.regulator_id = reg.id
            WHERE r.is_active = 1
        ''').fetchall()
        reports = []
        for row in rows:
            rep = RegulatoryReport(**dict(row))
            reports.append(rep)
        return reports
    
    @staticmethod
    def get_by_id(report_id):
        db = get_db()
        row = db.execute('''
            SELECT r.*, reg.regulator_name
            FROM regulatory_reports r
            LEFT JOIN regulators reg ON r.regulator_id = reg.id
            WHERE r.id = %s
        ''', (report_id,)).fetchone()
        if row:
            rep = RegulatoryReport(**dict(row))
            return rep
        return None

    @staticmethod
    def create(data):
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO regulatory_reports (
                report_code, report_name, regulator_id, frequency,
                due_day, due_month, description, submission_method,
                responsible_department, cbe_circular_reference, regulatory_reference, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('report_code'),
            data.get('report_name'),
            data.get('regulator_id'),
            data.get('frequency'),
            data.get('due_day'),
            data.get('due_month'),
            data.get('description'),
            data.get('submission_method'),
            data.get('responsible_department'),
            data.get('regulatory_reference'),
            data.get('regulatory_reference'),
            1
        ))
        db.commit()
        return cursor.fetchone()['id']

    def update(self, data):
        db = get_db()
        db.execute('''
            UPDATE regulatory_reports SET
                report_code = %s, report_name = %s, regulator_id = %s, frequency = %s,
                due_day = %s, due_month = %s, description = %s, submission_method = %s,
                responsible_department = %s, regulatory_reference = %s
            WHERE id = %s
        ''', (
            data.get('report_code', self.report_code),
            data.get('report_name', self.report_name),
            data.get('regulator_id', self.regulator_id),
            data.get('frequency', self.frequency),
            data.get('due_day', self.due_day),
            data.get('due_month', self.due_month),
            data.get('description', self.description),
            data.get('submission_method', self.submission_method),
            data.get('responsible_department', self.responsible_department),
            data.get('regulatory_reference', self.regulatory_reference),
            self.id
        ))
        db.commit()

    def generate_upcoming_submissions(self, months_ahead=12):
        """
        Generates pending submission records for future dates based on frequency.
        """
        db = get_db()
        today = date.today()
        due_dates = []
        
        if self.frequency == 'monthly':
            current_month = today.replace(day=1)
            for i in range(months_ahead):
                try:
                    d_day = int(self.due_day) if self.due_day else 15
                    target_date = current_month.replace(day=min(d_day, 28))
                    if target_date >= today:
                        due_dates.append(target_date)
                except ValueError: pass
                
                # Increment month
                if current_month.month == 12:
                    current_month = current_month.replace(year=current_month.year + 1, month=1)
                else:
                    current_month = current_month.replace(month=current_month.month + 1)

        elif self.frequency == 'quarterly':
            # Quarters usually end Mar, Jun, Sep, Dec. Submission usually month after.
            quarter_months = [3, 6, 9, 12] # Months where quarters END
            # Let's say due date is next month's 15th
            current_month = today.replace(day=1)
            for i in range(months_ahead):
                if current_month.month in quarter_months:
                    # Due on 15th of FOLLOWING month
                    next_m = 1 if current_month.month == 12 else current_month.month + 1
                    next_y = current_month.year + 1 if current_month.month == 12 else current_month.year
                    target_date = date(next_y, next_m, min(int(self.due_day or 15), 28))
                    if target_date >= today:
                        due_dates.append(target_date)
                
                # Increment month
                if current_month.month == 12:
                    current_month = current_month.replace(year=current_month.year + 1, month=1)
                else:
                    current_month = current_month.replace(month=current_month.month + 1)
        
        elif self.frequency == 'annual':
            d_month = int(self.due_month) if self.due_month else 12
            d_day = int(self.due_day) if self.due_day else 31
            target_year = today.year
            try:
                target_date = date(target_year, d_month, min(d_day, 28))
                if target_date < today:
                    target_date = target_date.replace(year=target_year + 1)
                due_dates.append(target_date)
            except ValueError: pass

        elif self.frequency == 'weekly':
            # Every Sunday for example
            cur = today
            for i in range(months_ahead * 4):
                if cur.weekday() == 6: # Sunday
                    due_dates.append(cur)
                cur += timedelta(days=1)

        count = 0
        for due_date in due_dates:
            exists = db.execute('''
                SELECT 1 FROM regulatory_report_submissions 
                WHERE report_id = %s AND due_date = %s
            ''', (self.id, due_date)).fetchone()
            
            if not exists:
                # Calculate period
                if self.frequency == 'monthly':
                    start = (due_date.replace(day=1) - timedelta(days=1)).replace(day=1)
                    end = due_date.replace(day=1) - timedelta(days=1)
                else:
                    start = due_date - timedelta(days=30)
                    end = due_date - timedelta(days=1)

                RegulatoryReportSubmission.create({
                    'report_id': self.id,
                    'reporting_period_start': start,
                    'reporting_period_end': end,
                    'due_date': due_date,
                    'status': 'pending',
                    'notes': 'Auto-generated'
                })
                count += 1
        return count




class RegulatoryReportSubmission:
    def __init__(self, id=None, report_id=None, reporting_period_start=None,
                 reporting_period_end=None, due_date=None, submission_date=None,
                 status='pending', submission_reference=None, notes=None,
                 attachment_path=None, prepared_by=None, reviewed_by=None,
                 approved_by=None, reminder_sent=False, reminder_date=None,
                 created_at=None, updated_at=None, **kwargs):
        self.id = id
        self.report_id = report_id
        self.reporting_period_start = reporting_period_start
        self.reporting_period_end = reporting_period_end
        self.due_date = due_date
        self.submission_date = submission_date
        self.status = status
        self.submission_reference = submission_reference
        self.notes = notes
        self.attachment_path = attachment_path
        self.prepared_by = prepared_by
        self.reviewed_by = reviewed_by
        self.approved_by = approved_by
        self.reminder_sent = reminder_sent
        self.reminder_date = reminder_date
        self.created_at = created_at
        self.updated_at = updated_at
        
        # Helpers
        self.report_name = kwargs.get('report_name')
        self.report_code = kwargs.get('report_code')
        self.regulator_name = kwargs.get('regulator_name')
        self.regulatory_reference = kwargs.get('regulatory_reference')

    @staticmethod
    def get_all(status=None):
        db = get_db()
        query = '''
            SELECT s.*, r.report_name, r.report_code, r.regulatory_reference, reg.regulator_name
            FROM regulatory_report_submissions s
            JOIN regulatory_reports r ON s.report_id = r.id
            LEFT JOIN regulators reg ON r.regulator_id = reg.id
        '''
        params = []
        if status:
            query += " WHERE s.status = %s"
            params.append(status)
        
        query += " ORDER BY s.due_date ASC"
        
        rows = db.execute(query, params).fetchall()
        submissions = []
        for row in rows:
            s = RegulatoryReportSubmission(**dict(row))
            submissions.append(s)
        return submissions

    @staticmethod
    def get_upcoming(days=30):
        db = get_db()
        today = date.today()
        future = today + timedelta(days=days)
        
        rows = db.execute('''
            SELECT s.*, r.report_name, r.report_code, r.regulatory_reference, reg.regulator_name
            FROM regulatory_report_submissions s
            JOIN regulatory_reports r ON s.report_id = r.id
            LEFT JOIN regulators reg ON r.regulator_id = reg.id
            WHERE s.status IN ('pending', 'in_progress')
            AND s.due_date::date <= %s
            ORDER BY s.due_date ASC
        ''', (future,)).fetchall()
        
        submissions = []
        for row in rows:
            s = RegulatoryReportSubmission(**dict(row))
            submissions.append(s)
        return submissions
    
    @staticmethod
    def get_by_id(submission_id):
        db = get_db()
        row = db.execute('''
            SELECT s.*, r.report_name, r.report_code, r.regulatory_reference, reg.regulator_name
            FROM regulatory_report_submissions s
            JOIN regulatory_reports r ON s.report_id = r.id
            LEFT JOIN regulators reg ON r.regulator_id = reg.id
            WHERE s.id = %s
        ''', (submission_id,)).fetchone()
        if row:
            s = RegulatoryReportSubmission(**dict(row))
            return s
        return None
    
    @staticmethod
    def create(data):
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO regulatory_report_submissions (
                report_id, reporting_period_start, reporting_period_end,
                due_date, status, notes, prepared_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data['report_id'],
            data.get('reporting_period_start'),
            data.get('reporting_period_end'),
            data['due_date'],
            data.get('status', 'pending'),
            data.get('notes'),
            data.get('prepared_by')
        ))
        db.commit()
        return cursor.fetchone()['id']

    def update_status(self, status, user_id, submission_date=None, reference=None, notes=None):
        db = get_db()
        sql = "UPDATE regulatory_report_submissions SET status = %s, updated_at = CURRENT_TIMESTAMP"
        params = [status]
        
        if status == 'submitted':
            sql += ", submission_date = %s, submission_reference = %s, approved_by = %s"
            params.extend([submission_date or date.today(), reference, user_id])
        elif status == 'in_progress':
            sql += ", prepared_by = %s"
            params.append(user_id)
            
        if notes:
            sql += ", notes = %s"
            params.append(notes)
            
        sql += " WHERE id = %s"
        params.append(self.id)
        
        db.execute(sql, params)
        db.commit()
