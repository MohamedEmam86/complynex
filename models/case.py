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

Data protection requests (data_subject_requests) and personal-data breaches
(data_breaches) are case sources too (DSR / DATA_BREACH).

Source modules call the module-level ``sync_case(case_type, source_id)`` after
every create / status / owner change. It never raises: a failed sync is logged
and the source transaction is unaffected (scripts/backfill_cases.py and the
periodic scripts/sync_cases.py reconcile anything missed).
"""

import logging

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


logger = logging.getLogger(__name__)

CASE_STATUSES = ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')
CASE_PRIORITIES = ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
_PRIORITY_ALIASES = {'NORMAL': 'MEDIUM', 'MODERATE': 'MEDIUM', 'MED': 'MEDIUM', 'URGENT': 'HIGH',
                     'VERY_HIGH': 'CRITICAL', 'SEVERE': 'CRITICAL', 'MINOR': 'LOW'}


def normalize_priority(*values):
    """First value that maps onto LOW / MEDIUM / HIGH / CRITICAL (None if none does)."""
    for v in values:
        key = str(v or '').strip().upper().replace(' ', '_')
        if key in CASE_PRIORITIES:
            return key
        if key in _PRIORITY_ALIASES:
            return _PRIORITY_ALIASES[key]
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
            due_date = COALESCE(EXCLUDED.due_date, cases.due_date),
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
        'WHISTLEBLOWING': {'SUBMITTED': 'OPEN', 'UNDER_REVIEW': 'IN_PROGRESS', 'INVESTIGATING': 'IN_PROGRESS',
                           'ESCALATED': 'IN_PROGRESS', 'RESOLVED': 'RESOLVED', 'DISMISSED': 'CLOSED'},
        'CONSUMER_COMPLAINT': {'NEW': 'OPEN', 'IN_PROGRESS': 'IN_PROGRESS', 'ESCALATED': 'IN_PROGRESS',
                               'RESOLVED': 'RESOLVED', 'CLOSED': 'CLOSED', 'DISMISSED': 'CLOSED'},
        'DSR': {'NEW': 'OPEN', 'IN_PROGRESS': 'IN_PROGRESS', 'OVERDUE': 'IN_PROGRESS', 'ON_HOLD': 'IN_PROGRESS',
                'COMPLETED': 'RESOLVED', 'REJECTED': 'CLOSED'},
        'DATA_BREACH': {'NEW': 'OPEN', 'INVESTIGATING': 'IN_PROGRESS', 'CONTAINED': 'IN_PROGRESS',
                        'REMEDIATING': 'IN_PROGRESS', 'CLOSED': 'CLOSED'},
        'CYBER_INCIDENT': {'NEW': 'OPEN', 'OPEN': 'OPEN', 'IN_PROGRESS': 'IN_PROGRESS', 'CONTAINED': 'IN_PROGRESS',
                           'RESOLVED': 'RESOLVED', 'CLOSED': 'CLOSED'},
        'REG_CONTROL': {'open': 'OPEN', 'acknowledged': 'IN_PROGRESS', 'resolved': 'RESOLVED'},
        'UNUSUAL_TXN': {'candidate': 'OPEN', 'under_study': 'IN_PROGRESS', 'str_filed': 'CLOSED', 'no_str': 'CLOSED',
                        'dismissed': 'CLOSED'},
    }

    # case_type -> (source table, SQL listing the source ids that belong in the registry).
    SOURCES = {
        'TM_ALERT': ('tm_alerts', 'SELECT id FROM tm_alerts'),
        'WHISTLEBLOWING': ('whistleblowing_cases', 'SELECT id FROM whistleblowing_cases'),
        'CONSUMER_COMPLAINT': ('consumer_complaints', 'SELECT id FROM consumer_complaints'),
        'CYBER_INCIDENT': ('cyber_incidents', 'SELECT id FROM cyber_incidents'),
        'DSR': ('data_subject_requests', 'SELECT id FROM data_subject_requests'),
        'DATA_BREACH': ('data_breaches', 'SELECT id FROM data_breaches'),
        # Only failed controls that were opened as a case (rc_alerts.case_id set).
        'REG_CONTROL': ('rc_alerts', 'SELECT id FROM rc_alerts WHERE case_id IS NOT NULL'),
        'UNUSUAL_TXN': ('aml_unusual_transactions', 'SELECT id FROM aml_unusual_transactions'),
    }

    @staticmethod
    def map_status(case_type, source_status):
        """Source-module status -> unified case status (OPEN / IN_PROGRESS / RESOLVED / CLOSED).

        Lookup is exact first, then case-insensitive; an unknown status counts as OPEN so a
        record never silently drops out of the open-case view."""
        mapping = Case.STATUS_MAP.get(case_type, {})
        raw = (source_status or '').strip()
        if raw in mapping:
            return mapping[raw]
        upper = {k.upper(): v for k, v in mapping.items()}
        return upper.get(raw.upper(), 'OPEN')

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
        status = Case.map_status('TM_ALERT', alert.get('status'))
        opened_at = _parse_dt(alert.get('alert_date')) or datetime.now()
        due_date = opened_at + timedelta(days=_get_sla_days(db, 'TM_ALERT'))
        party_id = PartyLink.find_party_id_for_source('customers', alert['customer_id'], 'CUSTOMER') \
            if alert.get('customer_id') else None
        return _upsert(
            db, 'TM_ALERT', 'tm_alerts', alert_id,
            reference=alert.get('alert_reference'),
            title=alert.get('alert_description'),
            status=status,
            priority=normalize_priority(alert.get('alert_severity')) or alert.get('alert_severity'),
            party_id=party_id,
            assigned_to=alert.get('assigned_to'),
            opened_at=opened_at,
            due_date=due_date,
            resolved_at=None if status not in ('RESOLVED', 'CLOSED') else
            (_parse_dt(alert.get('disposition_date')) or opened_at),
        )

    @staticmethod
    def _sync_whistleblowing(db, case_id):
        row = db.execute("SELECT * FROM whistleblowing_cases WHERE id = %s", (case_id,)).fetchone()
        if not row:
            return None
        wcase = dict(row)
        status = Case.map_status('WHISTLEBLOWING', wcase.get('status'))
        opened_at = _parse_dt(wcase.get('submitted_at')) or datetime.now()
        due_date = opened_at + timedelta(days=_get_sla_days(db, 'WHISTLEBLOWING'))
        return _upsert(
            db, 'WHISTLEBLOWING', 'whistleblowing_cases', case_id,
            reference=wcase.get('case_number'),
            title=wcase.get('title'),
            status=status,
            # 'priority' is mostly NORMAL on this table; severity is the meaningful signal.
            priority=normalize_priority(wcase.get('priority') if (wcase.get('priority') or '').upper()
                                        in CASE_PRIORITIES else None, wcase.get('severity')),
            party_id=None,  # whistleblowing reports have no customer/merchant link in this schema
            assigned_to=wcase.get('assigned_to'),
            opened_at=opened_at,
            due_date=due_date,
            resolved_at=None if status not in ('RESOLVED', 'CLOSED') else
            (_parse_dt(wcase.get('resolved_at')) or _parse_dt(wcase.get('updated_at'))),
        )

    @staticmethod
    def _sync_consumer_complaint(db, complaint_id):
        row = db.execute("SELECT * FROM consumer_complaints WHERE id = %s", (complaint_id,)).fetchone()
        if not row:
            return None
        complaint = dict(row)
        status = Case.map_status('CONSUMER_COMPLAINT', complaint.get('status'))
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
            priority=normalize_priority(complaint.get('priority')) or 'MEDIUM',
            party_id=party_id,
            assigned_to=complaint.get('assigned_to_user_id'),
            opened_at=opened_at,
            due_date=due_date,
            resolved_at=None if status not in ('RESOLVED', 'CLOSED') else
            (_parse_dt(complaint.get('resolved_at')) or _parse_dt(complaint.get('updated_at'))),
        )

    @staticmethod
    def _sync_cyber_incident(db, incident_id):
        row = db.execute("SELECT * FROM cyber_incidents WHERE id = %s", (incident_id,)).fetchone()
        if not row:
            return None
        incident = dict(row)
        status = Case.map_status('CYBER_INCIDENT', incident.get('status'))
        opened_at = _parse_dt(incident.get('created_at')) or datetime.now()
        due_date = opened_at + timedelta(days=_get_sla_days(db, 'CYBER_INCIDENT'))
        title = f"{incident.get('incident_type') or 'Incident'} — {incident.get('incident_number') or ''}".strip(' —')
        return _upsert(
            db, 'CYBER_INCIDENT', 'cyber_incidents', incident_id,
            reference=incident.get('incident_number'),
            title=title,
            status=status,
            priority=normalize_priority(incident.get('severity')) or incident.get('severity'),
            party_id=None,  # cyber_incidents has no customer/merchant link
            assigned_to=None,  # cyber_incidents has no assigned_to column at all
            opened_at=opened_at,
            due_date=due_date,
            resolved_at=None if status not in ('RESOLVED', 'CLOSED') else
            (_parse_dt(incident.get('closed_date')) or _parse_dt(incident.get('recovery_date')) or datetime.now()),
        )

    @staticmethod
    def _sync_dsr(db, request_id):
        """A data subject request (data_protection). Own statutory due_date is used directly."""
        row = db.execute("SELECT * FROM data_subject_requests WHERE id = %s", (request_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        status = Case.map_status('DSR', d.get('status'))
        opened_at = _parse_dt(d.get('request_date')) or _parse_dt(d.get('created_at')) or datetime.now()
        due_date = _parse_dt(d.get('due_date')) or opened_at + timedelta(days=_get_sla_days(db, 'DSR'))
        rtype = (d.get('request_type') or '').replace('_', ' ').title()
        return _upsert(
            db, 'DSR', 'data_subject_requests', request_id,
            reference=d.get('request_reference'),
            title=f"{rtype} request — {d.get('data_subject_name') or ''}".strip(' —'),
            status=status,
            priority='HIGH' if (d.get('request_type') or '').upper() in ('ERASURE', 'ACCESS') else 'MEDIUM',
            party_id=None,
            assigned_to=d.get('assigned_to'),
            opened_at=opened_at,
            due_date=due_date,
            resolved_at=None if status not in ('RESOLVED', 'CLOSED') else
            (_parse_dt(d.get('closed_date')) or _parse_dt(d.get('decision_date')) or datetime.now()),
        )

    @staticmethod
    def _sync_data_breach(db, breach_id):
        """A personal-data breach (data_protection). Due = regulator-notification clock from discovery."""
        row = db.execute("SELECT * FROM data_breaches WHERE id = %s", (breach_id,)).fetchone()
        if not row:
            return None
        b = dict(row)
        status = Case.map_status('DATA_BREACH', b.get('status'))
        opened_at = _parse_dt(b.get('discovery_date')) or _parse_dt(b.get('created_at')) or datetime.now()
        due_date = (_parse_dt(b.get('pdpc_notification_deadline'))
                    or opened_at + timedelta(days=_get_sla_days(db, 'DATA_BREACH')))
        btype = (b.get('breach_type') or 'Breach').replace('_', ' ').title()
        return _upsert(
            db, 'DATA_BREACH', 'data_breaches', breach_id,
            reference=b.get('breach_number'),
            title=f"{btype} — {(b.get('breach_description') or '')[:120]}".strip(' —'),
            status=status,
            priority=normalize_priority(b.get('severity')) or 'MEDIUM',
            party_id=None,
            assigned_to=b.get('owner_user_id') if 'owner_user_id' in b else None,
            opened_at=opened_at,
            due_date=due_date,
            resolved_at=None if status not in ('RESOLVED', 'CLOSED') else
            (_parse_dt(b.get('closed_date')) or _parse_dt(b.get('updated_at')) or datetime.now()),
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
        status = Case.map_status('REG_CONTROL', alert.get('status'))
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
        status = Case.map_status('UNUSUAL_TXN', u.get('status'))
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


def sync_case(case_type, source_id):
    """Create/update the unified case for one source record. Never raises.

    Call it after every create, status change or owner change in a source module:
        from models.case import sync_case
        sync_case('WHISTLEBLOWING', case_id)
    Returns the cases.id, or None when the sync failed or the source row is missing.
    """
    try:
        return Case.sync_from_source(case_type, source_id)
    except Exception:
        logger.exception('Case registry sync failed for %s %s', case_type, source_id)
        try:
            get_db().rollback()
        except Exception:
            pass
        return None


def resync_all(case_types=None):
    """Idempotent re-sync of every source record (backfill / periodic reconciliation).
    Returns {case_type: number synced}. A missing source table is skipped."""
    db = get_db()
    counts = {}
    for case_type, (_table, sql) in Case.SOURCES.items():
        if case_types and case_type not in case_types:
            continue
        try:
            ids = [r['id'] for r in db.execute(sql).fetchall()]
        except Exception:
            db.rollback()
            counts[case_type] = 'skipped'
            continue
        n = 0
        for sid in ids:
            if sync_case(case_type, sid):
                n += 1
        counts[case_type] = n
    return counts
