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
import json
from datetime import datetime, date, timedelta
from database.db import get_db

class TrainingCourse:
    def __init__(self, id=None, course_code=None, course_name=None,
                 description=None, category=None, duration_minutes=None,
                 content=None, video_url=None, document_path=None,
                 passing_score=70, is_mandatory=False, is_active=True,
                 created_by=None, created_at=None, content_type='Hybrid',
                 presentation_path=None, video_file_path=None, external_link=None,
                 language=None, video_duration_seconds=None, completion_threshold_pct=None,
                 max_quiz_attempts=None, **kwargs):
        self.id = id
        self.language = language
        self.video_duration_seconds = video_duration_seconds
        self.completion_threshold_pct = completion_threshold_pct
        self.max_quiz_attempts = max_quiz_attempts
        self.course_code = course_code
        self.course_name = course_name
        self.description = description
        self.category = category
        self.duration_minutes = duration_minutes
        self.content = content
        self.video_url = video_url
        self.document_path = document_path
        self.passing_score = passing_score
        self.is_mandatory = is_mandatory
        self.is_active = is_active
        self.created_by = created_by
        self.created_at = created_at
        self.content_type = content_type
        self.presentation_path = presentation_path
        self.video_file_path = video_file_path
        self.external_link = external_link

    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute('SELECT * FROM training_courses WHERE is_active = 1').fetchall()
        return [TrainingCourse(**dict(row)) for row in rows]
    
    @staticmethod
    def get_by_id(course_id):
        db = get_db()
        row = db.execute('SELECT * FROM training_courses WHERE id = %s', (course_id,)).fetchone()
        return TrainingCourse(**dict(row)) if row else None
    
    def get_questions(self):
        db = get_db()
        rows = db.execute('SELECT * FROM training_questions WHERE course_id = %s', (self.id,)).fetchall()
        questions = []
        for row in rows:
            q = dict(row)
            if q['options']:
                q['options'] = json.loads(q['options'])
            if q.get('options_ar'):
                q['options_ar'] = json.loads(q['options_ar'])
            questions.append(q)
        return questions

    def save(self):
        db = get_db()
        if self.id:
            db.execute('''
                UPDATE training_courses 
                SET course_code=%s, course_name=%s, description=%s, category=%s, 
                    duration_minutes=%s, content=%s, video_url=%s, document_path=%s, 
                    passing_score=%s, is_mandatory=%s, is_active=%s, content_type=%s,
                    presentation_path=%s, video_file_path=%s, external_link=%s,
                    language=%s, video_duration_seconds=%s, completion_threshold_pct=%s, max_quiz_attempts=%s
                WHERE id=%s
            ''', (self.course_code, self.course_name, self.description, self.category,
                  self.duration_minutes, self.content, self.video_url, self.document_path,
                  self.passing_score, self.is_mandatory, self.is_active, self.content_type,
                  self.presentation_path, self.video_file_path, self.external_link,
                  self.language, self.video_duration_seconds, self.completion_threshold_pct,
                  self.max_quiz_attempts, self.id))
        else:
            cursor = db.execute('''
                INSERT INTO training_courses (
                    course_code, course_name, description, category, 
                    duration_minutes, content, video_url, document_path, 
                    passing_score, is_mandatory, is_active, created_by, content_type,
                    presentation_path, video_file_path, external_link,
                    language, video_duration_seconds, completion_threshold_pct, max_quiz_attempts
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (self.course_code, self.course_name, self.description, self.category,
                  self.duration_minutes, self.content, self.video_url, self.document_path,
                  self.passing_score, self.is_mandatory, self.is_active, self.created_by, self.content_type,
                  self.presentation_path, self.video_file_path, self.external_link,
                  self.language, self.video_duration_seconds, self.completion_threshold_pct,
                  self.max_quiz_attempts))
            self.id = cursor.fetchone()['id']
        db.commit()

    def delete(self):
        db = get_db()
        db.execute('DELETE FROM training_courses WHERE id = %s', (self.id,))
        db.commit()


class TrainingQuestion:
    @staticmethod
    def get_by_id(id):
        db = get_db()
        row = db.execute('SELECT * FROM training_questions WHERE id = %s', (id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def create(course_id, question_text, options, correct_answer, points=1, question_text_ar=None, options_ar=None):
        db = get_db()
        db.execute('''
            INSERT INTO training_questions (course_id, question_text, options, correct_answer, points, question_text_ar, options_ar)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (course_id, question_text, json.dumps(options), correct_answer, points, question_text_ar, json.dumps(options_ar) if options_ar else None))
        db.commit()

    @staticmethod
    def update(id, question_text, options, correct_answer, points=1, question_text_ar=None, options_ar=None):
        db = get_db()
        db.execute('''
            UPDATE training_questions 
            SET question_text=%s, options=%s, correct_answer=%s, points=%s, question_text_ar=%s, options_ar=%s
            WHERE id=%s
        ''', (question_text, json.dumps(options), correct_answer, points, question_text_ar, json.dumps(options_ar) if options_ar else None, id))
        db.commit()

    @staticmethod
    def delete(id):
        db = get_db()
        db.execute('DELETE FROM training_questions WHERE id=%s', (id,))
        db.commit()


class TrainingEnrollment:
    def __init__(self, id=None, course_id=None, employee_id=None,
                 enrolled_date=None, enrolled_by=None, due_date=None,
                 status='enrolled', completion_date=None, score=None, **kwargs):
        self.id = id
        self.course_id = course_id
        self.employee_id = employee_id
        self.enrolled_date = enrolled_date or kwargs.get('enrolled_date')
        self.enrolled_by = enrolled_by
        self.due_date = due_date
        self.status = status
        self.completion_date = completion_date or kwargs.get('completed_at')
        self.score = score
        self.cert_id = kwargs.get('cert_id')
        self.video_progress = kwargs.get('video_progress') or 0
        self.video_completed = kwargs.get('video_completed', 0)
        self.watched_seconds = kwargs.get('watched_seconds') or 0
        self.last_heartbeat_at = kwargs.get('last_heartbeat_at')
        self.extra_quiz_attempts = kwargs.get('extra_quiz_attempts') or 0
        
        # Helpers
        self.course_name = None
        self.course_code = None
        self.employee_name = None
        self.department = None

    @staticmethod
    def get_user_enrollments(employee_id, status=None):
        db = get_db()
        query = '''
            SELECT e.*, c.course_name, c.course_code, c.is_mandatory, cert.id as cert_id
            FROM training_enrollments e
            JOIN training_courses c ON e.course_id = c.id
            LEFT JOIN training_certificates cert ON e.id = cert.enrollment_id
            WHERE e.employee_id = %s
        '''
        params = [employee_id]
        if status:
            query += " AND e.status = %s"
            params.append(status)
            
        rows = db.execute(query, params).fetchall()
        enrollments = []
        for row in rows:
            e = TrainingEnrollment(**dict(row))
            e.course_name = row['course_name']
            e.course_code = row['course_code']
            e.is_mandatory = row['is_mandatory']
            enrollments.append(e)
        return enrollments
    
    @staticmethod
    def get_all_enrollments(filters=None):
        db = get_db()
        query = '''
            SELECT e.*, c.course_name, c.course_code, 
                   u.first_name || ' ' || u.last_name as employee_name, u.department
            FROM training_enrollments e
            JOIN training_courses c ON e.course_id = c.id
            JOIN users u ON e.employee_id = u.id
            WHERE 1=1
        '''
        params = []
        
        if filters:
            if filters.get('course_id'):
                query += " AND e.course_id = %s"
                params.append(filters['course_id'])
            if filters.get('status'):
                query += " AND e.status = %s"
                params.append(filters['status'])
            if filters.get('department_ids'):
                query += " AND u.department_id = ANY(%s)"
                params.append(list(filters['department_ids']))

        query += " ORDER BY e.enrolled_date DESC"
        
        rows = db.execute(query, params).fetchall()
        enrollments = []
        for row in rows:
            e = TrainingEnrollment(**dict(row))
            e.course_name = row['course_name']
            e.course_code = row['course_code']
            e.employee_name = row['employee_name']
            e.department = row['department']
            enrollments.append(e)
        return enrollments

    @staticmethod
    def enroll(course_id, employee_id, enrolled_by, due_days=30):
        db = get_db()
        due_date = (date.today() + timedelta(days=due_days)).isoformat()
        enrolled_date = date.today().isoformat()

        course = db.execute('SELECT course_name FROM training_courses WHERE id = %s', (course_id,)).fetchone()
        course_name = course['course_name'] if course else 'Unknown Course'

        # Check if already enrolled
        existing = db.execute(
            "SELECT id FROM training_enrollments WHERE course_id = %s AND employee_id = %s",
            (course_id, employee_id)
        ).fetchone()
        if existing:
            return True  # Already enrolled, treat as success

        try:
            db.execute('''
                INSERT INTO training_enrollments
                    (course_id, employee_id, enrolled_by, due_date, course_name, enrolled_date, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'enrolled')
            ''', (course_id, employee_id, enrolled_by, due_date, course_name, enrolled_date))
            db.commit()
            return True
        except Exception as e:
            print(f"[Enrollment ERROR] course={course_id} user={employee_id} error={e}")
            db.rollback()
            return False

    def complete(self, score):
        db = get_db()
        course = TrainingCourse.get_by_id(self.course_id)
        passed = score >= (course.passing_score if course else 70)
        
        if passed:
            db.execute('''
                UPDATE training_enrollments 
                SET status = 'completed', completion_date = CURRENT_TIMESTAMP, score = %s
                WHERE id = %s
            ''', (score, self.id))
            
            # Generate certificate
            cert_num = f"CERT-{self.id}-{self.employee_id}-{datetime.now().strftime('%Y%m%d')}"
            db.execute('''
                INSERT INTO training_certificates (certificate_number, enrollment_id, employee_id, course_id, score, issue_date)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (cert_num, self.id, self.employee_id, self.course_id, score, datetime.now().strftime('%Y-%m-%d')))
            db.commit()
            return True, cert_num
        else:
            db.execute('UPDATE training_enrollments SET score = %s WHERE id = %s', (score, self.id))
            db.commit()
            return False, None

    def heartbeat(self, course, playing=True, now=None):
        """Credit watch time from a player heartbeat (server clock only) and mark
        the video watched once the course's threshold is reached. Returns a dict
        for the player. The client cannot declare completion."""
        from training import watch as W
        db = get_db()
        now = now or datetime.now()
        row = db.execute("""SELECT watched_seconds, last_heartbeat_at, video_completed FROM training_enrollments
                            WHERE id = %s FOR UPDATE""", (self.id,)).fetchone()
        watched = (row['watched_seconds'] or 0) if row else 0
        completed = bool(row['video_completed']) if row else False
        if not course.video_duration_seconds and course.video_file_path:
            # Older course without a recorded length: read it from the uploaded file
            # on the server (never from the browser) and keep it on the course.
            from training.media import mp4_duration_seconds
            secs = mp4_duration_seconds(course.video_file_path)
            if secs:
                db.execute("UPDATE training_courses SET video_duration_seconds = %s WHERE id = %s AND video_duration_seconds IS NULL",
                           (secs, course.id))
                course.video_duration_seconds = secs
        length = W.video_length(course.video_duration_seconds, course.duration_minutes)
        if not completed:
            watched += W.credit_seconds(row['last_heartbeat_at'] if row else None, now, playing)
            if length:
                watched = min(watched, length)
            completed = W.completion_reached(watched, length, course.completion_threshold_pct)
        db.execute("""UPDATE training_enrollments SET watched_seconds = %s, last_heartbeat_at = %s,
                      video_progress = GREATEST(COALESCE(video_progress, 0), %s), video_completed = %s
                      WHERE id = %s""",
                   (watched, now if playing else None, watched, 1 if completed else 0, self.id))
        db.commit()
        self.watched_seconds, self.video_completed = watched, 1 if completed else 0
        return {'watched_seconds': watched, 'length': length, 'pct': W.watched_pct(watched, length),
                'threshold_pct': W.threshold_pct(course.completion_threshold_pct), 'completed': completed}

    def quiz_attempts(self):
        db = get_db()
        return [dict(r) for r in db.execute(
            "SELECT * FROM training_quiz_attempts WHERE enrollment_id = %s ORDER BY attempt_no", (self.id,)).fetchall()]

    def record_attempt(self, score, passed, language=None, ip_address=None):
        db = get_db()
        n = db.execute("SELECT COALESCE(MAX(attempt_no), 0) + 1 AS n FROM training_quiz_attempts WHERE enrollment_id = %s",
                       (self.id,)).fetchone()['n']
        db.execute("""INSERT INTO training_quiz_attempts (enrollment_id, employee_id, course_id, attempt_no, score, passed,
                      language, ip_address) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (self.id, self.employee_id, self.course_id, n, score, passed, language, ip_address))
        db.commit()
        return n


class TrainingCertificate:
    def __init__(self, id=None, certificate_number=None, enrollment_id=None,
                 employee_id=None, course_id=None, issue_date=None,
                 expiry_date=None, score=None, **kwargs):
        self.id = id
        self.certificate_number = certificate_number
        self.enrollment_id = enrollment_id
        self.employee_id = employee_id
        self.course_id = course_id
        self.issue_date = issue_date or kwargs.get('issue_date')
        self.expiry_date = expiry_date
        self.score = score

    @staticmethod
    def get_by_id(cert_id):
        db = get_db()
        row = db.execute('''
            SELECT cert.*, c.course_name, c.course_code,
                   u.first_name || ' ' || u.last_name as employee_name
            FROM training_certificates cert
            JOIN training_courses c ON cert.course_id = c.id
            JOIN users u ON cert.employee_id = u.id
            WHERE cert.id = %s
        ''', (cert_id,)).fetchone()
        if row:
            res = TrainingCertificate(**dict(row))
            res.course_name = row['course_name']
            res.course_code = row['course_code']
            res.employee_name = row['employee_name']
            return res
        return None

    @staticmethod
    def get_by_enrollment(enrollment_id):
        db = get_db()
        row = db.execute('SELECT * FROM training_certificates WHERE enrollment_id = %s', (enrollment_id,)).fetchone()
        return TrainingCertificate(**dict(row)) if row else None

    @staticmethod
    def get_user_certificates(employee_id):
        db = get_db()
        rows = db.execute('''
            SELECT cert.*, c.course_name
            FROM training_certificates cert
            JOIN training_courses c ON cert.course_id = c.id
            WHERE cert.employee_id = %s
            ORDER BY cert.issue_date DESC
        ''', (employee_id,)).fetchall()
        return rows


class TrainingRequirement:
    def __init__(self, id=None, role=None, department=None, 
                 course_id=None, policy_id=None, is_mandatory=True, 
                 deadline_days=30, created_at=None, **kwargs):
        self.id = id
        self.role = role
        self.department = department
        self.course_id = course_id
        self.policy_id = policy_id
        self.is_mandatory = is_mandatory
        self.deadline_days = deadline_days
        self.created_at = created_at
        
        # Helpers
        self.course_name = kwargs.get('course_name')
        self.policy_name = kwargs.get('policy_name')

    @staticmethod
    def get_by_id(req_id):
        db = get_db()
        row = db.execute('''
            SELECT tr.*, c.course_name, p.policy_name
            FROM training_requirements tr
            LEFT JOIN training_courses c ON tr.course_id = c.id
            LEFT JOIN policies p ON tr.policy_id = p.id
            WHERE tr.id = %s
        ''', (req_id,)).fetchone()
        return TrainingRequirement(**dict(row)) if row else None

    @staticmethod
    def update(req_id, data):
        db = get_db()
        db.execute('''
            UPDATE training_requirements 
            SET role = %s, department = %s, course_id = %s, policy_id = %s, 
                is_mandatory = %s, deadline_days = %s
            WHERE id = %s
        ''', (
            data.get('role'), data.get('department'),
            data.get('course_id'), data.get('policy_id'),
            1 if data.get('is_mandatory') else 0,
            data.get('deadline_days', 30),
            req_id
        ))
        db.commit()

    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute('''
            SELECT tr.*, c.course_name, p.policy_name
            FROM training_requirements tr
            LEFT JOIN training_courses c ON tr.course_id = c.id
            LEFT JOIN policies p ON tr.policy_id = p.id
            ORDER BY tr.role, tr.department
        ''').fetchall()
        return [TrainingRequirement(**dict(row)) for row in rows]

    @staticmethod
    def create(data):
        db = get_db()
        cursor = db.execute('''
            INSERT INTO training_requirements (role, department, course_id, policy_id, is_mandatory, deadline_days)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('role'), data.get('department'),
            data.get('course_id'), data.get('policy_id'),
            1 if data.get('is_mandatory') else 0,
            data.get('deadline_days', 30)
        ))
        db.commit()
        return cursor.fetchone()['id']

    @staticmethod
    def delete(req_id):
        db = get_db()
        db.execute('DELETE FROM training_requirements WHERE id = %s', (req_id,))
        db.commit()

    @staticmethod
    def assign_requirements(user_id, role, department, assigned_by_id=None):
        """
        Auto-assign courses and policies based on role and department.
        """
        db = get_db()
        
        # 1. Find matching requirements
        # Match Role OR Department OR both (if both fields are set in a requirement, strict match not implemented here for simplicity, 
        # usually requirements are Role-based OR Department-based. Using OR logic for specific rules)
        
        # Let's use a query that matches if:
        # (req.role IS NULL OR req.role = user.role) AND (req.dept IS NULL OR req.dept = user.dept)
        # But for SQLite 'IS NULL' matching in python logic is easier or specific SQL
        
        query = '''
            SELECT * FROM training_requirements 
            WHERE (role IS NULL OR role = '' OR role = %s)
            AND (department IS NULL OR department = '' OR department = %s)
        '''
        
        requirements = db.execute(query, (role, department)).fetchall()
        
        assigned_count = 0
        
        for req in requirements:
            # Assign Course
            if req['course_id']:
                # Check if already enrolled
                existing = db.execute('''
                    SELECT 1 FROM training_enrollments 
                    WHERE employee_id = %s AND course_id = %s
                ''', (user_id, req['course_id'])).fetchone()
                
                if not existing:
                    TrainingEnrollment.enroll(
                        course_id=req['course_id'],
                        employee_id=user_id,
                        enrolled_by=assigned_by_id or user_id, # Self-enrolled by system if no admin
                        due_days=req['deadline_days']
                    )
                    assigned_count += 1
            
            # Policy Acknowledgment (Notification/System Logic - Models/Policy.py logic needed)
            # For now, we only track training enrollment here. 
            # Policy assignment usually just means it appears in their "Pending" list which is dynamic.
            
        print(f"Auto-assigned {assigned_count} training items to User {user_id}")
        return assigned_count

