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
Four-eyes on sanctions clearance and whitelist governance.

Clearing a hit ("not the person") is the decision that lets a customer or a
payment through. When the hit is strong (score at or above a configurable
threshold) or comes from a sanctions list, the officer's decision alone does
not take effect: it waits for a second person with approval authority (the
MLRO), who approves or rejects it with a comment. Maker and checker must be
different people — enforced here, server-side.

Whitelist entries suppress future alerts, so each one carries a reason, a
review date (default 12 months, at most 24) and an approval by someone other
than the person who requested it; past its review date an entry stops
suppressing hits until it is renewed.

The pure functions at the top are tested without a database.
"""
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

DEFAULT_APPROVAL_THRESHOLD = 85.0
REVIEW_MONTHS_DEFAULT = 12
REVIEW_MONTHS_MAX = 24

# hit statuses while a clearance waits for the second person
QUEUE_PENDING_APPROVAL = 'Pending MLRO Approval'
RESULT_PENDING_APPROVAL = 'PENDING_APPROVAL'

# whitelist statuses
WL_PENDING = 'Pending Approval'
WL_ACTIVE = 'Active'
WL_REJECTED = 'Rejected'
WL_EXPIRED = 'Expired'          # shown, never stored: Active + review date passed

APPROVER_ROLES = ('compliance_manager', 'admin')

NOT_SANCTIONS_SOURCES = ('adverse media',)


# --------------------------------------------------------------------------- pure rules
def is_sanctions_hit(list_source=None, match=None):
    """Is the hit from a sanctions list (as opposed to PEP / adverse media)?
    Unknown hits count as sanctions — the stricter obligation wins."""
    if str(list_source or '').strip().lower() in NOT_SANCTIONS_SOURCES:
        return False
    try:
        from screening.match_classifier import classify_match
        m = dict(match) if isinstance(match, dict) else {}
        if list_source and not m.get('source'):
            m['source'] = list_source
        return classify_match(m) == 'SANCTIONS'
    except Exception:
        return True


def needs_approval(score, sanctions, threshold=DEFAULT_APPROVAL_THRESHOLD):
    """A clearance needs MLRO approval when the score reaches the threshold
    or the hit comes from a sanctions list."""
    try:
        s = float(score or 0)
    except (TypeError, ValueError):
        s = 0.0
    return bool(sanctions) or s >= float(threshold)


def maker_checker_error(checker_id, maker_id):
    """None when the checker is independent of the maker, else the
    (untranslated) reason the approval is refused."""
    if checker_id is None:
        return 'no approver'
    if maker_id is not None and int(checker_id) == int(maker_id):
        return 'you made this decision; another person must approve it'
    return None


def add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def default_review_date(today=None):
    return add_months(today or date.today(), REVIEW_MONTHS_DEFAULT)


def parse_review_date(value, today=None):
    """(date, error). Empty -> default +12 months. Must be in the future and
    at most 24 months away."""
    today = today or date.today()
    v = (value or '').strip() if isinstance(value, str) else value
    if not v:
        return default_review_date(today), None
    if isinstance(v, date):
        d = v
    else:
        try:
            d = datetime.strptime(v[:10], '%Y-%m-%d').date()
        except ValueError:
            return None, 'invalid review date'
    if d <= today:
        return None, 'the review date must be in the future'
    if d > add_months(today, REVIEW_MONTHS_MAX):
        return None, 'the review date can be at most 24 months away'
    return d, None


def effective_wl_status(status, review_date, today=None):
    """What the list shows: an Active entry past its review date is Expired
    (and no longer suppresses hits)."""
    st = status or WL_ACTIVE
    if st == WL_ACTIVE and review_date:
        try:
            d = datetime.strptime(str(review_date)[:10], '%Y-%m-%d').date()
            if d < (today or date.today()):
                return WL_EXPIRED
        except ValueError:
            pass
    return st


def can_approve(user):
    """MLRO authority: compliance manager, admin, or 'admin' on screening."""
    if user is None:
        return False
    if getattr(user, 'role', None) in APPROVER_ROLES:
        return True
    try:
        return bool(user.can_admin_module('screening'))
    except Exception:
        return False


# --------------------------------------------------------------------------- DB helpers
def approval_threshold():
    try:
        from database.db import query_db
        r = query_db("SELECT config_value FROM screening_config WHERE config_key = %s",
                     ('clearance_approval_threshold',), one=True)
        if r and r['config_value'] not in (None, ''):
            return float(r['config_value'])
    except Exception as e:
        logger.warning('clearance threshold unreadable, using default: %s', e)
    return DEFAULT_APPROVAL_THRESHOLD


def approver_ids(exclude=None):
    from database.db import query_db
    rows = query_db("SELECT id FROM users WHERE is_active = 1 AND role = 'compliance_manager' ORDER BY id") or []
    ids = [r['id'] for r in rows]
    if not ids:
        rows = query_db("SELECT id FROM users WHERE is_active = 1 AND role = 'admin' ORDER BY id") or []
        ids = [r['id'] for r in rows]
    return [i for i in ids if i != exclude]


def notify_approvers(title, message, link=None, exclude=None, category='warning'):
    """In-app notification to every MLRO, plus email through the non-blocking
    helper (never sent on the demo instance). Never raises."""
    try:
        ids = approver_ids(exclude)
        if not ids:
            return 0
        from services.notification_service import notify
        notify(ids, title, message, link=link, category=category)
        try:
            from flask import current_app
            from flask_mail import Message
            from database.db import query_db
            from utils.email import send_mail_async
            rows = query_db("SELECT email FROM users WHERE id = ANY(%s)", (ids,)) or []
            emails = [r['email'] for r in rows if r['email']]
            if emails:
                body = message + (f"\n\n{link}" if link else '')
                msg = Message(subject=title, recipients=emails, body=body,
                              sender=current_app.config.get('MAIL_USERNAME', 'noreply@complynex.online'))
                send_mail_async(msg)
        except Exception as e:
            logger.info('approver email not queued: %s', e)
        return len(ids)
    except Exception as e:
        logger.error('notify_approvers failed: %s', e)
        return 0


def log_decision(target_type, target_id, action, decision, reason, actor_id, request_id=None):
    try:
        from database.db import execute_db
        execute_db("""INSERT INTO screening_hit_decisions
                        (target_type, target_id, action, decision, reason, actor_id, request_id)
                      VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                   (target_type, target_id, action, decision, reason, actor_id, request_id))
    except Exception as e:
        logger.error('hit decision log failed: %s', e)


def decision_history(target_type, target_id):
    from database.db import query_db
    try:
        return query_db("""
            SELECT d.*, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS actor_name,
                   u.email AS actor_email
              FROM screening_hit_decisions d LEFT JOIN users u ON u.id = d.actor_id
             WHERE d.target_type = %s AND d.target_id = %s
             ORDER BY d.created_at, d.id""", (target_type, target_id)) or []
    except Exception:
        return []


def pending_request(target_type, target_id):
    from database.db import query_db
    try:
        return query_db("""
            SELECT r.*, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS requested_by_name
              FROM screening_clearance_requests r LEFT JOIN users u ON u.id = r.requested_by
             WHERE r.target_type = %s AND r.target_id = %s AND r.status = 'pending'""",
                        (target_type, target_id), one=True)
    except Exception:
        return None


def create_request(target_type, target_id, entity_name, match_name, score, list_source,
                   sanctions, decision, reason, previous_status, user_id):
    from database.db import query_db
    row = query_db("""
        INSERT INTO screening_clearance_requests
            (target_type, target_id, entity_name, match_name, match_score, list_source,
             is_sanctions, proposed_decision, reason, previous_status, requested_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                   (target_type, target_id, entity_name, match_name, score, list_source,
                    bool(sanctions), decision, reason, previous_status, user_id), one=True)
    return row['id'] if row else None


def pending_counts():
    from database.db import query_db
    out = {'hits': 0, 'whitelist': 0}
    try:
        r = query_db("SELECT count(*) AS c FROM screening_clearance_requests WHERE status = 'pending'", one=True)
        out['hits'] = r['c'] if r else 0
        r = query_db("SELECT count(*) AS c FROM screening_whitelist WHERE status = %s", (WL_PENDING,), one=True)
        out['whitelist'] = r['c'] if r else 0
    except Exception:
        pass
    return out
