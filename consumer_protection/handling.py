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
Complaint handling: reference lists (root cause, redress), validation and the
periodic complaints report (counts by category / status / channel, average
resolution days, overdue). Pure functions are DB-free so they can be tested.
"""
from datetime import date, datetime, timedelta

ROOT_CAUSES = ('PROCESS_FAILURE', 'STAFF_ERROR', 'SYSTEM_ERROR', 'PRODUCT_DESIGN', 'THIRD_PARTY',
               'MISCOMMUNICATION', 'FRAUD', 'CUSTOMER_MISUNDERSTANDING', 'NO_FAULT', 'OTHER')
REDRESS_TYPES = ('NONE', 'REFUND', 'FEE_WAIVER', 'COMPENSATION', 'CORRECTION', 'APOLOGY',
                 'SERVICE_RESTORED', 'OTHER')
MONETARY_REDRESS = ('REFUND', 'FEE_WAIVER', 'COMPENSATION')
DONE = ('RESOLVED', 'CLOSED')


def _dt(v):
    if v in (None, ''):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    s = str(v).strip()
    for fmt, n in (('%Y-%m-%d %H:%M:%S', 19), ('%Y-%m-%dT%H:%M:%S', 19), ('%Y-%m-%d', 10)):
        try:
            return datetime.strptime(s[:n], fmt)
        except ValueError:
            continue
    return None


def validate_resolution_details(root_cause, redress_type, amount, redress_date, today=None):
    """Returns (error_key or None, cleaned dict). Error keys are mapped to messages by the caller."""
    today = today or date.today()
    if root_cause not in ROOT_CAUSES:
        return 'root_cause', None
    if redress_type not in REDRESS_TYPES:
        return 'redress_type', None
    amt = None
    if amount not in (None, ''):
        try:
            amt = round(float(str(amount).replace(',', '')), 2)
        except ValueError:
            return 'amount', None
        if amt < 0:
            return 'amount', None
    if redress_type in MONETARY_REDRESS and not amt:
        return 'amount_required', None
    d = None
    if redress_date:
        d = _dt(redress_date)
        if not d:
            return 'date', None
        d = d.date()
        if d > today:
            return 'date_future', None
    if redress_type != 'NONE' and not d:
        return 'date_required', None
    return None, {'root_cause_category': root_cause, 'redress_type': redress_type,
                  'redress_amount': amt if redress_type != 'NONE' else None,
                  'redress_date': d if redress_type != 'NONE' else None}


def resolution_days(c):
    if (c.get('status') or '') not in DONE:
        return None
    start = _dt(c.get('created_at'))
    end = _dt(c.get('resolved_at')) or _dt(c.get('updated_at'))
    if not start or not end or end < start:
        return None
    return round((end - start).total_seconds() / 86400, 1)


def is_overdue(c, today=None):
    """Open past its statutory deadline, or resolved after it."""
    today = today or date.today()
    dl = _dt(c.get('statutory_deadline_date'))
    if not dl:
        return False
    if (c.get('status') or '') in DONE:
        end = _dt(c.get('resolved_at')) or _dt(c.get('updated_at'))
        return bool(end and end.date() > dl.date())
    return dl.date() < today


def summarize(rows, today=None):
    rows = [dict(r) for r in rows]
    out = {'total': len(rows), 'by_category': {}, 'by_status': {}, 'by_channel': {}, 'by_root_cause': {},
           'resolved': 0, 'open': 0, 'overdue_open': 0, 'resolved_late': 0, 'avg_resolution_days': None,
           'redress_total': 0.0}
    days = []
    for c in rows:
        for key, col in (('by_category', 'complaint_category'), ('by_status', 'status'),
                         ('by_channel', 'complaint_channel'), ('by_root_cause', 'root_cause_category')):
            k = c.get(col) or 'UNSPECIFIED'
            out[key][k] = out[key].get(k, 0) + 1
        done = (c.get('status') or '') in DONE
        out['resolved' if done else 'open'] += 1
        c['resolution_days'] = resolution_days(c)
        c['overdue'] = is_overdue(c, today)
        if c['resolution_days'] is not None:
            days.append(c['resolution_days'])
        if c['overdue']:
            out['resolved_late' if done else 'overdue_open'] += 1
        if c.get('redress_amount'):
            out['redress_total'] += float(c['redress_amount'])
    if days:
        out['avg_resolution_days'] = round(sum(days) / len(days), 1)
    out['overdue'] = out['overdue_open'] + out['resolved_late']
    for key in ('by_category', 'by_status', 'by_channel', 'by_root_cause'):
        out[key] = dict(sorted(out[key].items(), key=lambda kv: -kv[1]))
    out['rows'] = rows
    return out


def period_bounds(period, start=None, end=None, today=None):
    """'month' / 'quarter' / 'year' (the current one), 'last_month', 'last_quarter' or 'custom'."""
    today = today or date.today()
    if period == 'custom':
        s, e = _dt(start), _dt(end)
        if s and e and s <= e:
            return s.date(), e.date()
        period = 'month'
    if period == 'last_month':
        first = today.replace(day=1)
        e = first - timedelta(days=1)
        return e.replace(day=1), e
    if period in ('quarter', 'last_quarter'):
        q0 = (today.month - 1) // 3 * 3 + 1
        s = today.replace(month=q0, day=1)
        if period == 'last_quarter':
            e = s - timedelta(days=1)
            return e.replace(month=(e.month - 1) // 3 * 3 + 1, day=1), e
        nxt = s.replace(year=s.year + 1, month=1) if q0 == 10 else s.replace(month=q0 + 3)
        return s, nxt - timedelta(days=1)
    if period == 'year':
        return today.replace(month=1, day=1), today.replace(month=12, day=31)
    first = today.replace(day=1)
    nxt = first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1)
    return first, nxt - timedelta(days=1)


def fetch(db, start, end):
    rows = db.execute("""
        SELECT c.*, NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), '') AS owner_name
        FROM consumer_complaints c LEFT JOIN users u ON u.id = c.assigned_to_user_id
        WHERE LEFT(c.created_at, 10) >= %s AND LEFT(c.created_at, 10) <= %s
        ORDER BY c.created_at""", (start.isoformat(), end.isoformat())).fetchall()
    return rows
