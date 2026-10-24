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
Case.sync_from_source() upserts one row into `cases` from one of the 4 live
source tables (tm_alerts, whistleblowing_cases, consumer_complaints,
cyber_incidents — see database/schema_cases.sql for why aml_alerts,
edd_cases and screening_queue aren't synced). Each source has its own status
vocabulary and shape, so this is 4 explicit branches rather than a generic
engine — not worth abstracting for 4 known cases; add a 5th branch if a
future source needs it, don't build for it now.

`due_date` uses plain calendar days from case_sla_config, not business days —
a deliberate simplification; consumer_complaints is the exception, since it
already carries its own statutory_deadline_date, which is used directly.

All 4 source tables store their date columns as `text`, not `timestamp`
(alert_date, submitted_at, created_at, statutory_deadline_date), and not
even consistently — some are hand-formatted ('%Y-%m-%d %H:%M:%S'), some are
Postgres's default text cast of NOW(), one is a bare date. dateutil.parser
is used rather than a fixed strptime format to survive that inconsistency.
"""

from datetime import datetime, timedelta

from dateutil import parser as dateutil_parser

from database.db import get_db
from data_protection.encryption_service import EncryptionService
from models.party import PartyLink, Party


def _parse_dt(value):
    if not value:
        return None
    try:
        return dateutil_parser.parse(str(value))
    except (ValueError, TypeError):
        return None


def _get_sla_days(db, case_type):
    row = db.execute("SELECT sla_days FROM case_sla_config WHERE case_type = %s", (case_type,)).fetchone()
    return row['sla_days'] if row else 5


def _upsert(db, case_type, source_table, source_record_id, reference, title,
            status, priority, party_id, assigned_to, opened_at, due_date, resolved_at):
    cursor = db.execute("""
        INSERT INTO cases
            (case_type, source_table, source_record_id, reference, title, status,
             priority, party_id, assigned_to, opened_at, due_date, resolved_at, last_synced_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (source_table, source_record_id) DO UPDATE SET
            reference = EXCLUDED.reference,
            title = EXCLUDED.title,
            status = EXCLUDED.status,
            priority = EXCLUDED.priority,
            party_id = COALESCE(EXCLUDED.party_id, cases.party_id),
            assigned_to = EXCLUDED.assigned_to,
            resolved_at = EXCLUDED.resolved_at,
            last_synced_at = NOW()
        RETURNING id
    """, (case_type, source_table, source_record_id, reference, title, status,
          priority, party_id, assigned_to, opened_at, due_date, resolved_at))
    case_id = cursor.fetchone()['id']
    db.commit()
    return case_id


class Case:
    STATUS_MAP = {
        'TM_ALERT': {'NEW': 'OPEN', 'ASSIGNED': 'IN_PROGRESS', 'INVESTIGATING': 'IN_PROGRESS',
                     'ESCALATED': 'IN_PROGRESS', 'SAR_CREATED': 'CLOSED', 'CLOSED': 'CLOSED', 'FALSE_POSITIVE': 'CLOSED'},
        'WHISTLEBLOWING': {'SUBMITTED': 'OPEN', 'UNDER_REVIEW': 'IN_PROGRESS', 'INVESTIGATING': 'IN_PROGRESS', 'ESCALATED': 'IN_PROGRESS', 'RESOLVED': 'RESOLVED'},
        'CONSUMER_COMPLAINT': {'NEW': 'OPEN', 'IN_PROGRESS': 'IN_PROGRESS', 'RESOLVED': 'RESOLVED', 'CLOSED': 'CLOSED'},
        'CYBER_INCIDENT': {'NEW': 'OPEN', 'OPEN': 'OPEN', 'IN_PROGRESS': 'IN_PROGRESS', 'CONTAINED': 'IN_PROGRESS',
                           'RESOLVED': 'RESOLVED', 'CLOSED': 'CLOSED'},
        'REG_CONTROL': {'open': 'OPEN', 'acknowledged': 'IN_PROGRESS', 'resolved': 'RESOLVED'},
        'UNUSUAL_TXN': {'candidate': 'OPEN', 'under_study': 'IN_PROGRESS', 'str_filed': 'CLOSED', 'no_str': 'CLOSED',
                        'dismissed': 'CLOSED'},
    }

    @staticmethod
    def get_by_id(case_id):
        row = get_db().execute("SELECT * FROM cases WHERE id = %s", (case_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_open(case_type=None, assigned_to=None, limit=200):
        db = get_db()
        clauses, params = ["status NOT IN ('RESOLVED', 'CLOSED')"], []
        if case_type:
            clauses.append("case_type = %s")
            params.append(case_type)
        if assigned_to:
            clauses.append("assigned_to = %s")
            params.append(assigned_to)
        params.append(limit)
        rows = db.execute(f"""
            SELECT * FROM cases WHERE {' AND '.join(clauses)}
            ORDER BY due_date NULLS LAST, opened_at DESC LIMIT %s
        """, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def sync_from_source(case_type, source_record_id):
        db = get_db()
        method = getattr(Case, f'_sync_{case_type.lower()}', None)
        if not method:
            raise ValueError(f"No sync handler for case_type {case_type!r}")
        return method(db, source_record_id)

    @staticmethod
    def _sync_tm_alert(db, alert_id):
        row = db.execute("SELECT * FROM tm_alerts WHERE id = %s", (alert_id,)).fetchone()
        if not row:
            return None
        alert = dict(row)
        status = Case.STATUS_MAP['TM_ALERT'].get(alert.get('status'), 'OPEN')
        opened_at = _parse_dt(alert.get('alert_date')) or datetime.now()
        due_date = opened_at + timedelta(days=_get_sla_days(db, 'TM_ALERT'))
        party_id = PartyLink.find_party_id_for_source('customers', alert['customer_id'], 'CUSTOMER') \
            if alert.get('customer_id') else None
        return _upsert(
            db, 'TM_ALERT', 'tm_alerts', alert_id,
            reference=alert.get('alert_reference'),
            title=alert.get('alert_description'),
            status=status,
            priority=alert.get('alert_severity'),
            party_id=party_id,
            assigned_to=alert.get('assigned_to'),
            opened_at=opened_at,
            due_date=due_date,
            resolved_at=None if status not in ('RESOLVED', 'CLOSED') else opened_at,
        )

    @staticmethod
    def _sync_whistleblowing(db, case_id):
        row = db.execute("SELECT * FROM whistleblowing_cases WHERE id = %s", (case_id,)).fetchone()
        if not row:
            return None
        wcase = dict(row)
        status = Case.STATUS_MAP['WHISTLEBLOWING'].get(wcase.get('status'), 'OPEN')
        opened_at = _parse_dt(wcase.get('submitted_at')) or datetime.now()
        due_date = opened_at + timedelta(days=_get_sla_days(db, 'WHISTLEBLOWING'))
        return _upsert(
            db, 'WHISTLEBLOWING', 'whistleblowing_cases', case_id,
            reference=wcase.get('case_number'),
            title=wcase.get('title'),
            status=status,
            priority=wcase.get('priority'),
            party_id=None,  # whistleblowing reports have no customer/merchant link in this schema
            assigned_to=wcase.get('assigned_to'),
            opened_at=opened_at,
            due_date=due_date,
            resolved_at=None if status != 'RESOLVED' else _parse_dt(wcase.get('resolved_at')),
        )

    @staticmethod
    def _sync_consumer_complaint(db, complaint_id):
        row = db.execute("SELECT * FROM consumer_complaints WHERE id = %s", (complaint_id,)).fetchone()
        if not row:
            return None
        complaint = dict(row)
        status = Case.STATUS_MAP['CONSUMER_COMPLAINT'].get(complaint.get('status'), 'OPEN')
        opened_at = _parse_dt(complaint.get('created_at')) or datetime.now()
        due_date = _parse_dt(complaint.get('statutory_deadline_date'))  # own real SLA field, used directly

        party_id = None
        id_hash = EncryptionService.hash_value(complaint.get('customer_id_number'))
        if id_hash:
            party = Party.find_by_id_number_hash(id_hash)
            party_id = party['id'] if party else None

        return _upsert(
            db, 'CONSUMER_COMPLAINT', 'consumer_complaints', complaint_id,
            # Staff-facing reference; the PIN is the customer's secret and never shown to staff.
            reference=f"CP-{complaint_id}",
            title=complaint.get('complaint_subject'),
            status=status,
            priority=complaint.get('priority'),
            party_id=party_id,
            assigned_to=complaint.get('assigned_to_user_id'),
            opened_at=opened_at,
            due_date=due_date,
            resolved_at=None if status not in ('RESOLVED', 'CLOSED') else _parse_dt(complaint.get('updated_at')),
        )

    @staticmethod
    def _sync_cyber_incident(db, incident_id):
        row = db.execute("SELECT * FROM cyber_incidents WHERE id = %s", (incident_id,)).fetchone()
        if not row:
            return None
        incident = dict(row)
        status = Case.STATUS_MAP['CYBER_INCIDENT'].get(incident.get('status'), 'OPEN')
        opened_at = _parse_dt(incident.get('created_at')) or datetime.now()
        due_date = opened_at + timedelta(days=_get_sla_days(db, 'CYBER_INCIDENT'))
        title = f"{incident.get('incident_type') or 'Incident'} — {incident.get('incident_number') or ''}".strip(' —')
        return _upsert(
            db, 'CYBER_INCIDENT', 'cyber_incidents', incident_id,
            reference=incident.get('incident_number'),
            title=title,
            status=status,
            priority=incident.get('severity'),
            party_id=None,  # cyber_incidents has no customer/merchant link
            assigned_to=None,  # cyber_incidents has no assigned_to column at all
            opened_at=opened_at,
            due_date=due_date,
            resolved_at=None if status not in ('RESOLVED', 'CLOSED') else None,
        )

    @staticmethod
    def _sync_reg_control(db, alert_id):
        """A failed FRA control (regcontrols rc_alerts row) worked as a case."""
        row = db.execute("""
            SELECT a.*, c.control_code, c.title_en
            FROM rc_alerts a LEFT JOIN rc_controls c ON c.id = a.control_id WHERE a.id = %s
        """, (alert_id,)).fetchone()
        if not row:
            return None
        alert = dict(row)
        status = Case.STATUS_MAP['REG_CONTROL'].get(alert.get('status'), 'OPEN')
        opened_at = alert.get('raised_at') or datetime.now()
        return _upsert(
            db, 'REG_CONTROL', 'rc_alerts', alert_id,
            reference=alert.get('control_code'),
            title=alert.get('title'),
            status=status,
            priority=(alert.get('severity') or 'high').upper(),
            party_id=None,  # control failures are about the institution, not one customer
            assigned_to=alert.get('owner_user_id'),
            opened_at=opened_at,
            due_date=opened_at + timedelta(days=_get_sla_days(db, 'REG_CONTROL')),
            resolved_at=alert.get('resolved_at'),
        )

    @staticmethod
    def _sync_unusual_txn(db, item_id):
        """An unusual transaction / AML red flag waiting for study (aml_unusual_transactions)."""
        row = db.execute("SELECT * FROM aml_unusual_transactions WHERE id = %s", (item_id,)).fetchone()
        if not row:
            return None
        u = dict(row)
        status = Case.STATUS_MAP['UNUSUAL_TXN'].get(u.get('status'), 'OPEN')
        opened_at = u.get('detected_at') or datetime.now()
        due = (datetime.combine(u['study_due_date'], datetime.min.time()) if u.get('study_due_date')
               else opened_at + timedelta(days=_get_sla_days(db, 'UNUSUAL_TXN')))
        return _upsert(
            db, 'UNUSUAL_TXN', 'aml_unusual_transactions', item_id,
            reference=u.get('reference'),
            title=(u.get('description') or u.get('detection_rule') or '')[:250],
            status=status,
            priority='HIGH',
            party_id=u.get('party_id'),
            assigned_to=u.get('decision_by'),
            opened_at=opened_at,
            due_date=due,
            resolved_at=u.get('decision_at') if status == 'CLOSED' else None,
        )
