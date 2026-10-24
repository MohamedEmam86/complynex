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

from database.db import get_db
from datetime import datetime
import json

class BoardRole:
    def __init__(self, id=None, role_name=None, description=None, **kwargs):
        self.id = id
        self.role_name = role_name
        self.description = description

    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute('SELECT * FROM board_roles ORDER BY role_name').fetchall()
        return [BoardRole(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(id):
        db = get_db()
        row = db.execute('SELECT * FROM board_roles WHERE id = %s', (id,)).fetchone()
        return BoardRole(**dict(row)) if row else None

    @staticmethod
    def create(role_name, description=None):
        db = get_db()
        try:
            cursor = db.execute('INSERT INTO board_roles (role_name, description) VALUES (%s, %s) RETURNING id',
                              (role_name, description))
            db.commit()
            return cursor.fetchone()['id']
        except:
            return None

    @staticmethod
    def update(id, role_name, description=None):
        db = get_db()
        db.execute('UPDATE board_roles SET role_name = %s, description = %s WHERE id = %s', 
                  (role_name, description, id))
        db.commit()

    @staticmethod
    def delete(id):
        db = get_db()
        db.execute('DELETE FROM board_roles WHERE id = %s', (id,))
        db.commit()

class BoardMember:
    def __init__(self, id=None, member_name=None, member_name_arabic=None,
                 role=None, is_independent=False, is_executive=False,
                 expertise_areas=None, appointment_date=None, term_end_date=None,
                 email=None, phone=None, bio=None, status='ACTIVE', 
                 member_type=None, position=None, document_path=None, **kwargs):
        self.id = id
        self.member_name = member_name
        self.member_name_arabic = member_name_arabic
        self.role = role
        self.is_independent = is_independent
        self.is_executive = is_executive
        self.expertise_areas = expertise_areas
        self.appointment_date = appointment_date
        self.term_end_date = term_end_date
        self.email = email
        self.phone = phone
        self.bio = bio
        self.status = status
        
        # Mapping for schema variations
        self.member_type = member_type or self._derive_member_type()
        self.position = position or role
        self.document_path = document_path

    def _derive_member_type(self):
        if self.is_independent:
            return 'INDEPENDENT'
        if self.is_executive:
            return 'EXECUTIVE'
        return 'NON_EXECUTIVE'

    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute('''
            SELECT * FROM board_members 
            WHERE status = 'ACTIVE' 
            ORDER BY member_name
        ''').fetchall()
        return [BoardMember(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(id):
        db = get_db()
        row = db.execute('SELECT * FROM board_members WHERE id = %s', (id,)).fetchone()
        return BoardMember(**dict(row)) if row else None

    @staticmethod
    def create(data):
        db = get_db()
        
        # Handle member_type logic
        member_type = data.get('member_type')
        if not member_type:
            if data.get('is_independent'):
                member_type = 'INDEPENDENT'
            elif data.get('is_executive'):
                member_type = 'EXECUTIVE'
            else:
                member_type = 'NON_EXECUTIVE'

        # Map role to valid position for CHECK constraint
        role = data.get('role', '')
        position = 'MEMBER'
        if role and 'Chairman' in role and 'Vice' not in role:
            position = 'CHAIRMAN'
        elif role and ('Vice Chairman' in role or 'Vice Chair' in role):
            position = 'VICE_CHAIR'

        cursor = db.execute('''
            INSERT INTO board_members (
                member_name, member_name_arabic, role, is_independent,
                is_executive, expertise_areas, appointment_date,
                term_end_date, email, phone, bio, status,
                member_type, position, term_start_date, document_path
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('member_name'),
            data.get('member_name_arabic'),
            data.get('role'),
            1 if data.get('is_independent') else 0,
            1 if data.get('is_executive') else 0,
            data.get('expertise_areas'),
            data.get('appointment_date'),
            data.get('term_end_date'),
            data.get('email'),
            data.get('phone'),
            data.get('bio'),
            data.get('status', 'ACTIVE'),
            member_type,
            position,
            data.get('appointment_date'),
            data.get('document_path')
        ))
        db.commit()
        return cursor.fetchone()['id']

    def update(self, data):
        db = get_db()
        
        member_type = data.get('member_type', self.member_type)
        if 'is_independent' in data or 'is_executive' in data:
            if data.get('is_independent'):
                member_type = 'INDEPENDENT'
            elif data.get('is_executive'):
                member_type = 'EXECUTIVE'
            else:
                member_type = 'NON_EXECUTIVE'

        role = data.get('role', self.role)
        position = data.get('position', self.position)
        if 'role' in data:
            position = 'MEMBER'
            if role and 'Chairman' in role and 'Vice' not in role:
                position = 'CHAIRMAN'
            elif role and ('Vice Chairman' in role or 'Vice Chair' in role):
                position = 'VICE_CHAIR'

        db.execute('''
            UPDATE board_members SET 
                member_name = %s, member_name_arabic = %s, role = %s, 
                is_independent = %s, is_executive = %s, expertise_areas = %s, 
                appointment_date = %s, term_end_date = %s, email = %s, 
                phone = %s, bio = %s, status = %s,
                member_type = %s, position = %s, document_path = %s
            WHERE id = %s
        ''', (
            data.get('member_name', self.member_name),
            data.get('member_name_arabic', self.member_name_arabic),
            data.get('role', self.role),
            1 if data.get('is_independent', self.is_independent) else 0,
            1 if data.get('is_executive', self.is_executive) else 0,
            data.get('expertise_areas', self.expertise_areas),
            data.get('appointment_date', self.appointment_date),
            data.get('term_end_date', self.term_end_date),
            data.get('email', self.email),
            data.get('phone', self.phone),
            data.get('bio', self.bio),
            data.get('status', self.status),
            member_type,
            position,
            data.get('document_path', self.document_path),
            self.id
        ))
        db.commit()

class BoardCommittee:
    def __init__(self, id=None, committee_name=None, committee_type=None,
                 chairman_id=None, charter_file=None, meeting_frequency=None,
                 is_active=True, **kwargs):
        self.id = id
        self.committee_name = committee_name
        self.committee_type = committee_type
        self.chairman_id = chairman_id
        self.charter_file = charter_file
        self.meeting_frequency = meeting_frequency
        self.is_active = is_active
        self.committee_name_arabic = kwargs.get('committee_name_arabic')
        self.requires_fit_proper = kwargs.get('requires_fit_proper', True)

    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute('SELECT * FROM board_committees WHERE is_active = 1').fetchall()
        return [BoardCommittee(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(id):
        db = get_db()
        row = db.execute('SELECT * FROM board_committees WHERE id = %s', (id,)).fetchone()
        return BoardCommittee(**dict(row)) if row else None

    @staticmethod
    def create(data):
        db = get_db()
        cursor = db.execute('''
            INSERT INTO board_committees (
                committee_name, committee_type, chairman_id,
                charter_file, meeting_frequency, is_active, committee_name_arabic, requires_fit_proper
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('committee_name'),
            data.get('committee_type', '').upper().strip() if data.get('committee_type') else None,
            data.get('chairman_id'),
            data.get('charter_file'),
            data.get('meeting_frequency'),
            1 if data.get('is_active', True) else 0,
            data.get('committee_name_arabic'),
            bool(data.get('requires_fit_proper', True))
        ))
        db.commit()
        return cursor.fetchone()['id']

    def update(self, data):
        db = get_db()
        db.execute('''
            UPDATE board_committees SET 
                committee_name = %s, committee_type = %s, chairman_id = %s, 
                charter_file = %s, meeting_frequency = %s, is_active = %s,
                committee_name_arabic = %s, requires_fit_proper = %s
            WHERE id = %s
        ''', (
            data.get('committee_name', self.committee_name),
            data.get('committee_type', self.committee_type).upper().strip() if data.get('committee_type') else self.committee_type,
            data.get('chairman_id', self.chairman_id),
            data.get('charter_file', self.charter_file),
            data.get('meeting_frequency', self.meeting_frequency),
            1 if data.get('is_active', self.is_active) else 0,
            data.get('committee_name_arabic', getattr(self, 'committee_name_arabic', None)),
            bool(data.get('requires_fit_proper', getattr(self, 'requires_fit_proper', True))),
            self.id
        ))
        db.commit()

    @staticmethod
    def delete(id):
        db = get_db()
        db.execute('UPDATE board_committees SET is_active = 0 WHERE id = %s', (id,))
        db.commit()

class CommitteeMembership:
    def __init__(self, id=None, committee_id=None, member_id=None,
                 role='MEMBER', joined_date=None, **kwargs):
        self.id = id
        self.committee_id = committee_id
        self.member_id = member_id
        self.role = role
        self.joined_date = joined_date

    @staticmethod
    def get_by_committee(committee_id):
        db = get_db()
        rows = db.execute('''
            SELECT cm.*, bm.member_name, bm.role as member_role
            FROM committee_memberships cm
            JOIN board_members bm ON cm.member_id = bm.id
            WHERE cm.committee_id = %s AND COALESCE(cm.is_active, 1) = 1
        ''', (committee_id,)).fetchall()
        return rows

    @staticmethod
    def add_member(committee_id, member_id, role='MEMBER'):
        db = get_db()
        cursor = db.execute('''
            INSERT INTO committee_memberships (committee_id, member_id, role, joined_date)
            VALUES (%s, %s, %s, CURRENT_DATE)
            RETURNING id
        ''', (committee_id, member_id, role))
        db.commit()
        return cursor.fetchone()['id']

# meeting_date is a TEXT column; a legacy blank/garbage value must not break
# every list that casts it, so only cast values that look like a date.
SAFE_MEETING_DATE = "(CASE WHEN meeting_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN left(meeting_date, 10)::date END)"


class BoardMeeting:
    def __init__(self, id=None, meeting_type=None, committee_id=None,
                 meeting_date=None, meeting_time=None, location=None,
                 agenda=None, minutes_file=None, quorum_met=False,
                 status='SCHEDULED', meeting_reference=None, **kwargs):
        self.id = id
        self.meeting_type = meeting_type
        self.committee_id = committee_id
        self.meeting_date = meeting_date
        self.meeting_time = meeting_time
        self.location = location
        self.agenda = agenda
        self.minutes_file = minutes_file
        self.quorum_met = quorum_met
        self.status = status
        self.meeting_reference = meeting_reference

    @staticmethod
    def get_all():
        db = get_db()
        rows = db.execute('SELECT * FROM board_meetings ORDER BY meeting_date DESC').fetchall()
        return [BoardMeeting(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(id):
        db = get_db()
        row = db.execute('SELECT * FROM board_meetings WHERE id = %s', (id,)).fetchone()
        return BoardMeeting(**dict(row)) if row else None

    @staticmethod
    def get_upcoming():
        db = get_db()
        rows = db.execute('''
            SELECT * FROM board_meetings
            WHERE ''' + SAFE_MEETING_DATE + ''' >= CURRENT_DATE
            ORDER BY meeting_date ASC
        ''').fetchall()
        return [BoardMeeting(**dict(row)) for row in rows]

    @staticmethod
    def get_past():
        db = get_db()
        # Meetings without a usable date are listed here so they can be fixed.
        rows = db.execute('''
            SELECT * FROM board_meetings
            WHERE ''' + SAFE_MEETING_DATE + ''' < CURRENT_DATE OR ''' + SAFE_MEETING_DATE + ''' IS NULL
            ORDER BY meeting_date DESC NULLS FIRST
        ''').fetchall()
        return [BoardMeeting(**dict(row)) for row in rows]

    @staticmethod
    def create(data, attendee_ids=None):
        db = get_db()
        try:
            cursor = db.execute('''
                INSERT INTO board_meetings (
                    meeting_type, committee_id, meeting_date, meeting_time,
                    location, agenda, minutes_file, status, meeting_reference
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (
                data.get('meeting_type'),
                data.get('committee_id'),
                data.get('meeting_date'),
                data.get('meeting_time'),
                data.get('location'),
                data.get('agenda'),
                data.get('minutes_file'),
                data.get('status', 'SCHEDULED'),
                data.get('meeting_reference')
            ))
            meeting_id = cursor.fetchone()['id']
            
            # Record initial attendance if attendees provided
            if attendee_ids:
                for member_id in attendee_ids:
                    db.execute('''
                        INSERT INTO meeting_attendance (meeting_id, member_id, attended)
                        VALUES (%s, %s, 0)
                    ''', (meeting_id, member_id))
            
            db.commit()
            return meeting_id
        except Exception as e:
            db.rollback()
            print(f"Error creating board meeting: {e}")
            raise e

    def update(self, data):
        db = get_db()
        db.execute('''
            UPDATE board_meetings SET 
                meeting_type = %s, committee_id = %s, meeting_date = %s, 
                meeting_time = %s, location = %s, agenda = %s, 
                minutes_file = %s, status = %s, meeting_reference = %s
            WHERE id = %s
        ''', (
            data.get('meeting_type', self.meeting_type),
            data.get('committee_id', self.committee_id),
            data.get('meeting_date', self.meeting_date),
            data.get('meeting_time', self.meeting_time),
            data.get('location', self.location),
            data.get('agenda', self.agenda),
            data.get('minutes_file', self.minutes_file),
            data.get('status', self.status),
            data.get('meeting_reference', self.meeting_reference),
            self.id
        ))
        db.commit()

    @staticmethod
    def get_attendance_summary(meeting_id):
        db = get_db()
        rows = db.execute('''
            SELECT bm.member_name, ma.attended, ma.apology_received, ma.proxy_name, ma.attendance_status
            FROM meeting_attendance ma
            JOIN board_members bm ON ma.member_id = bm.id
            WHERE ma.meeting_id = %s
            ORDER BY bm.member_name
        ''', (meeting_id,)).fetchall()
        return rows

class MeetingAttendance:
    def __init__(self, id=None, meeting_id=None, member_id=None,
                 attended=False, apology_received=False, proxy_name=None, **kwargs):
        self.id = id
        self.meeting_id = meeting_id
        self.member_id = member_id
        self.attended = attended
        self.apology_received = apology_received
        self.proxy_name = proxy_name

    @staticmethod
    def status_for(attended, apology_received, proxy_name):
        if attended:
            return 'PRESENT'
        if proxy_name:
            return 'REPRESENTED_BY_PROXY'
        return 'ABSENT_WITH_APOLOGY' if apology_received else 'ABSENT'

    @staticmethod
    def get_for_meeting(meeting_id):
        """{member_id: row} of what has been saved for this meeting."""
        db = get_db()
        rows = db.execute('SELECT * FROM meeting_attendance WHERE meeting_id = %s', (meeting_id,)).fetchall()
        return {r['member_id']: r for r in rows}

    @staticmethod
    def record_attendance(meeting_id, attendance_data, recorded_by=None):
        """One row per (meeting, member): insert or overwrite (re-saving the
        sheet, or rows pre-created when the meeting was scheduled)."""
        db = get_db()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for member_id, data in attendance_data.items():
            attended = 1 if data.get('attended') else 0
            apology = 0 if attended else (1 if data.get('apology_received') else 0)
            proxy = None if attended else data.get('proxy_name')
            db.execute('''
                INSERT INTO meeting_attendance
                (meeting_id, member_id, attended, apology_received, proxy_name,
                 attendance_status, recorded_at, recorded_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (meeting_id, member_id) DO UPDATE SET
                    attended = EXCLUDED.attended, apology_received = EXCLUDED.apology_received,
                    proxy_name = EXCLUDED.proxy_name, attendance_status = EXCLUDED.attendance_status,
                    recorded_at = EXCLUDED.recorded_at, recorded_by = EXCLUDED.recorded_by
            ''', (
                meeting_id, member_id, attended, apology, proxy,
                MeetingAttendance.status_for(attended, apology, proxy), now, recorded_by
            ))
        db.commit()

class BoardDecision:
    def __init__(self, id=None, meeting_id=None, decision_number=None,
                 decision_text=None, responsible_person=None, deadline=None,
                 status='PENDING', completion_date=None, **kwargs):
        self.id = id
        self.meeting_id = meeting_id
        self.decision_number = decision_number
        self.decision_text = decision_text
        self.responsible_person = responsible_person
        self.deadline = deadline
        self.status = status
        self.completion_date = completion_date

    @staticmethod
    def create(data):
        db = get_db()
        cursor = db.execute('''
            INSERT INTO board_decisions (
                meeting_id, decision_number, decision_text,
                responsible_person, deadline, status
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('meeting_id'),
            data.get('decision_number'),
            data.get('decision_text'),
            data.get('responsible_person'),
            data.get('deadline'),
            data.get('status', 'PENDING')
        ))
        db.commit()
        return cursor.fetchone()['id']
