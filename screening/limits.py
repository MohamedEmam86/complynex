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
Daily screening limits per user (owner decision, round 5).

* Setting ``screening.daily_limit_default`` (system_settings): the default maximum number of screenings a user
  may run per day; 0 = unlimited (the default, so nothing changes for existing users).
* ``users.screening_daily_limit``: a per-user override (NULL = the default, 0 = unlimited).
* The platform superadmin has no limit. API keys keep their own rate limits (not counted here).
* What counts: every subject screened by a user, in every screening module — a name / company screening (single,
  bulk rows, customer / merchant / party screenings started by the user), a vessel screening (single and bulk
  rows), a dual-use product screening (each line). Browsing a catalogue or a list does not count.
* The day is the calendar day in Africa/Cairo. Usage: ``screening_daily_usage(user_id, day, kind, n)``.
* Over the limit: the screening is refused with a clear bilingual message; a bulk job is refused whole (never
  partly run) and the message says how many screenings are left today.
* Administrators see today's usage per user and reset / raise a user's limit (audited: screening_limit_events
  and the audit log).
"""
from datetime import datetime

SETTING_DEFAULT = 'screening.daily_limit_default'
TZ = 'Africa/Cairo'
KINDS = ('name', 'vessel', 'dualuse')
UNLIMITED_ROLES = ('superadmin',)


class DailyLimitReached(Exception):
    """Raised before a screening runs when it would exceed the user's daily limit."""

    def __init__(self, limit, used, wanted=1):
        self.limit, self.used, self.wanted = int(limit), int(used), int(wanted)
        self.remaining = max(0, self.limit - self.used)
        super().__init__(self.message('en'))

    def message(self, lang='en'):
        if self.wanted > 1 and self.remaining > 0:
            if str(lang).startswith('ar'):
                return (f'هذه العملية تتضمن {self.wanted} عملية فحص، والمتبقي لك اليوم {self.remaining} فقط '
                        f'من الحد اليومي ({self.limit}). قلّل عدد الصفوف أو تواصل مع مسؤول النظام لرفع الحد.')
            return (f'This job has {self.wanted} screenings but only {self.remaining} of your daily limit '
                    f'({self.limit}) are left today. Reduce the rows or contact your administrator to raise it.')
        if str(lang).startswith('ar'):
            return f'لقد وصلت إلى الحد اليومي لعمليات الفحص ({self.limit}). تواصل مع مسؤول النظام لإعادة ضبطه.'
        return f'You reached your daily screening limit ({self.limit}). Contact your administrator to reset it.'


def today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TZ)).date()
    except Exception:            # pragma: no cover - tzdata missing
        from datetime import timedelta, timezone
        return datetime.now(timezone(timedelta(hours=2))).date()


def _db(db=None):
    if db is not None:
        return db
    from database.db import get_db
    return get_db()


def default_limit(db=None):
    try:
        from models.settings import Settings
        return max(0, int(Settings.get(SETTING_DEFAULT, '0') or 0))
    except Exception:
        return 0


def limit_for(user, db=None):
    """The user's daily limit, or None when unlimited."""
    if user is None or (getattr(user, 'role', '') or '') in UNLIMITED_ROLES:
        return None
    own = getattr(user, 'screening_daily_limit', None)
    if own is None and not getattr(user, '_sdl_loaded', False):
        try:
            r = _db(db).execute('SELECT screening_daily_limit FROM users WHERE id = %s', (user.id,)).fetchone()
            own = r['screening_daily_limit'] if r else None
        except Exception:
            _db(db).rollback()
            own = None
    n = default_limit(db) if own is None else int(own)
    return n if n and n > 0 else None


def used(user_id, day=None, db=None):
    try:
        r = _db(db).execute('SELECT COALESCE(sum(n), 0) AS n FROM screening_daily_usage WHERE user_id = %s AND day = %s',
                            (user_id, day or today())).fetchone()
        return int(r['n'] or 0)
    except Exception:
        _db(db).rollback()
        return 0


def remaining(user, db=None):
    lim = limit_for(user, db)
    if lim is None:
        return None
    return max(0, lim - used(user.id, db=db))


def _current_user():
    try:
        from flask_login import current_user
        return current_user if getattr(current_user, 'is_authenticated', False) else None
    except Exception:
        return None


def consume(n=1, kind='name', user=None, db=None):
    """Count `n` screenings for the user before they run; raise DailyLimitReached (nothing counted) when they
    would exceed the limit. A bulk job is all or nothing. Unlimited users are still counted (usage page)."""
    user = user or _current_user()
    if user is None or not n:
        return None
    n = int(n)
    kind = kind if kind in KINDS else 'name'
    db = _db(db)
    lim = limit_for(user, db)
    day = today()
    try:
        # serialise this user's counting so two parallel requests cannot both pass the limit
        db.execute('SELECT pg_advisory_xact_lock(%s, %s)', (73120, int(user.id)))
        if lim is not None:
            u = used(user.id, day, db)
            if u + n > lim:
                db.rollback()
                raise DailyLimitReached(lim, u, n)
        db.execute("""INSERT INTO screening_daily_usage (user_id, day, kind, n, updated_at) VALUES (%s, %s, %s, %s, now())
                      ON CONFLICT (user_id, day, kind) DO UPDATE SET n = screening_daily_usage.n + EXCLUDED.n,
                                                                     updated_at = now()""",
                   (user.id, day, kind, n))
        db.commit()
    except DailyLimitReached:
        raise
    except Exception:
        # the table is missing (migration not applied yet): never block a screening because of the counter
        try:
            db.rollback()
        except Exception:
            pass
        return None
    return None if lim is None else max(0, lim - used(user.id, day, db))


def consume_job(job_key, total_rows, kind='name', user=None, db=None):
    """A bulk job: count, all or nothing, the rows not counted yet (total planned minus already counted), so a
    paused / resumed job is never counted twice. Raises DailyLimitReached before anything runs."""
    user = user or _current_user()
    if user is None:
        return None
    db = _db(db)
    try:
        r = db.execute('SELECT counted FROM screening_job_counts WHERE job_key = %s', (job_key,)).fetchone()
        counted = int(r['counted']) if r else 0
    except Exception:
        db.rollback()
        return None
    n = max(0, int(total_rows) - counted)
    left = consume(n, kind, user, db) if n else remaining(user, db)
    if n:
        try:
            db.execute("""INSERT INTO screening_job_counts (job_key, user_id, counted, updated_at) VALUES (%s, %s, %s, now())
                          ON CONFLICT (job_key) DO UPDATE SET counted = screening_job_counts.counted + EXCLUDED.counted,
                                                              updated_at = now()""", (job_key, user.id, n))
            db.commit()
        except Exception:
            db.rollback()
    return left


def usage_today(db=None):
    """[{user_id, name, email, role, used, by_kind, limit, own_limit}] for the administrators' page."""
    db = _db(db)
    day = today()
    dflt = default_limit(db)
    rows = db.execute("""SELECT u.id, u.email, u.role, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS name,
                                u.screening_daily_limit AS own_limit, COALESCE(x.n, 0) AS used, x.by_kind
                           FROM users u
                           LEFT JOIN (SELECT user_id, sum(n) AS n, json_object_agg(kind, n) AS by_kind
                                        FROM screening_daily_usage WHERE day = %s GROUP BY user_id) x ON x.user_id = u.id
                          WHERE COALESCE(u.is_active, 1) = 1
                          ORDER BY COALESCE(x.n, 0) DESC, u.first_name, u.last_name""", (day,)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        if r['role'] in UNLIMITED_ROLES:
            r['limit'] = None
        else:
            n = dflt if r['own_limit'] is None else int(r['own_limit'])
            r['limit'] = n if n > 0 else None
        r['left'] = None if r['limit'] is None else max(0, r['limit'] - int(r['used']))
        out.append(r)
    return out, day, dflt


def _event(db, user_id, actor_id, action, old, new, note, ip=None):
    db.execute("""INSERT INTO screening_limit_events (user_id, actor_id, day, action, old_value, new_value, note)
                  VALUES (%s, %s, %s, %s, %s, %s, %s)""", (user_id, actor_id, today(), action, old, new, note))
    try:
        from models.audit import AuditLog
        AuditLog.log(actor_id, 'Screening Limit ' + action.replace('_', ' ').title(), 'Screening', user_id,
                     f'{old} -> {new}' + (f' ({note})' if note else ''), ip)
    except Exception:
        pass


def reset_today(user_id, actor_id, note=None, ip=None, db=None):
    """Give a user today's full limit again (usage of today set to zero, history kept in the event log)."""
    db = _db(db)
    before = used(user_id, db=db)
    db.execute('DELETE FROM screening_daily_usage WHERE user_id = %s AND day = %s', (user_id, today()))
    _event(db, user_id, actor_id, 'reset', str(before), '0', note, ip)
    db.commit()
    return before


def set_user_limit(user_id, value, actor_id, note=None, ip=None, db=None):
    """Per-user daily limit: None = follow the default, 0 = unlimited, n > 0 = n screenings a day."""
    db = _db(db)
    r = db.execute('SELECT screening_daily_limit FROM users WHERE id = %s', (user_id,)).fetchone()
    old = r['screening_daily_limit'] if r else None
    v = None if value in (None, '') else max(0, int(value))
    db.execute('UPDATE users SET screening_daily_limit = %s WHERE id = %s', (v, user_id))
    _event(db, user_id, actor_id, 'limit_set', 'default' if old is None else str(old),
           'default' if v is None else str(v), note, ip)
    db.commit()
    return v


def apply_form(user_id, form, actor_id, ip=None, db=None):
    """The 'daily screening limit' field of the user / access forms (cx_daily_limit: '' = the default,
    0 = unlimited, n). Only written when it changed."""
    if 'cx_daily_limit' not in form:
        return None
    raw = (form.get('cx_daily_limit') or '').strip()
    if raw and not raw.isdigit():
        return None
    db = _db(db)
    try:
        r = db.execute('SELECT screening_daily_limit FROM users WHERE id = %s', (user_id,)).fetchone()
    except Exception:
        db.rollback()
        return None
    old = r['screening_daily_limit'] if r else None
    new = int(raw) if raw else None
    if old == new:
        return old
    return set_user_limit(user_id, new, actor_id, note='user form', ip=ip, db=db)


def set_default(value, actor_id, ip=None, db=None):
    from models.settings import Settings
    db = _db(db)
    old = default_limit(db)
    v = max(0, int(value or 0))
    Settings.set(SETTING_DEFAULT, str(v), 'Default daily screenings per user (0 = unlimited)')
    _event(db, None, actor_id, 'default_set', str(old), str(v), None, ip)
    db.commit()
    return v


def events(limit=100, db=None):
    db = _db(db)
    try:
        return [dict(r) for r in db.execute(
            """SELECT e.*, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS user_name,
                      TRIM(COALESCE(a.first_name,'') || ' ' || COALESCE(a.last_name,'')) AS actor_name
                 FROM screening_limit_events e LEFT JOIN users u ON u.id = e.user_id LEFT JOIN users a ON a.id = e.actor_id
                ORDER BY e.created_at DESC, e.id DESC LIMIT %s""", (limit,)).fetchall()]
    except Exception:
        db.rollback()
        return []
