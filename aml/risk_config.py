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
The customer risk model in force (F1) and its history.

Versions live in aml_risk_models (one row per saved version, one is_current).
Only the MLRO saves a version, with a written reason; every save is audited.
Until the first save the model is utils.aml_risk.DEFAULT_MODEL, i.e. the
scoring used before it became configurable.
"""
import copy
import json
import threading
import time

from database.db import get_db
from utils import aml_risk

CACHE_SECONDS = 60
_lock = threading.Lock()
_cache = {'at': 0.0, 'model': None}


class RiskModelError(ValueError):
    pass


def _table_exists(db):
    r = db.execute("SELECT to_regclass('public.aml_risk_models') AS t").fetchone()
    return bool(r and r['t'])


def current_model(db=None, force=False):
    """The model in force, merged over the defaults (cached for a minute)."""
    now = time.time()
    if not force and _cache['model'] is not None and now - _cache['at'] < CACHE_SECONDS:
        return copy.deepcopy(_cache['model'])
    with _lock:
        model = None
        try:
            db = db or get_db()
            if _table_exists(db):
                r = db.execute("SELECT model FROM aml_risk_models WHERE is_current ORDER BY id DESC LIMIT 1").fetchone()
                if r:
                    model = r['model'] if isinstance(r['model'], dict) else json.loads(r['model'])
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            model = _cache['model']          # keep the last good model
        model = aml_risk.merged(model)
        if aml_risk.validate(model):
            model = copy.deepcopy(aml_risk.DEFAULT_MODEL)
        _cache['model'], _cache['at'] = model, now
        return copy.deepcopy(model)


def high_risk_rows(db=None):
    db = db or get_db()
    return [dict(r) for r in db.execute("SELECT * FROM high_risk_countries WHERE is_active = 1").fetchall()]


def history(db=None, limit=20):
    db = db or get_db()
    if not _table_exists(db):
        return []
    return [dict(r) for r in db.execute(
        """SELECT m.id, m.reason, m.created_at, m.is_current, m.model,
                  trim(coalesce(u.first_name, '') || ' ' || coalesce(u.last_name, '')) AS by_name
             FROM aml_risk_models m LEFT JOIN users u ON u.id = m.created_by
            ORDER BY m.id DESC LIMIT %s""", (limit,)).fetchall()]


def _int(v, label):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        raise RiskModelError(f'{label} must be a whole number')


def _words(v):
    return [w.strip().upper() for w in str(v or '').replace('\n', ',').split(',') if w.strip()]


def from_form(form):
    """Model dict from the edit form (raises RiskModelError on bad numbers)."""
    m = aml_risk.merged(None)
    m['country'] = {
        'source': form.get('country_source') or 'builtin',
        'builtin_list': _words(form.get('builtin_list')),
        'high_risk_points': _int(form.get('high_risk_points'), 'high-risk country points'),
        'home_country': (form.get('home_country') or '').strip().upper(),
        'foreign_points': _int(form.get('foreign_points'), 'foreign country points'),
    }
    m['customer_type_points'] = {'CORPORATE': _int(form.get('corporate_points'), 'corporate points')}
    m['activity'] = {'keywords': _words(form.get('activity_keywords')),
                     'points': _int(form.get('activity_points'), 'activity points')}
    m['income_points'] = {'>500K': _int(form.get('income_high_points'), 'income points'),
                          'UNDECLARED': _int(form.get('income_undeclared_points'), 'undeclared income points')}
    m['bands'] = {'HIGH': _int(form.get('band_high'), 'HIGH band'), 'MEDIUM': _int(form.get('band_medium'), 'MEDIUM band')}
    m['review_months'] = {c: _int(form.get(f'review_{c.lower()}'), f'review interval {c}') for c in aml_risk.CLASSES}
    m['reminders'] = {'enabled': form.get('reminders_enabled') == 'on',
                      'days_before': _int(form.get('reminder_days'), 'reminder lead time')}
    return m


def save_model(model, reason, user_id, db=None):
    """Store a new version and make it current. Returns the version id."""
    db = db or get_db()
    reason = (reason or '').strip()
    if len(reason) < 15:
        raise RiskModelError('give the reason for the change (at least 15 characters)')
    probs = aml_risk.validate(model)
    if probs:
        raise RiskModelError('; '.join(probs))
    old = current_model(db, force=True)
    db.execute("UPDATE aml_risk_models SET is_current = FALSE WHERE is_current")
    vid = db.execute("""INSERT INTO aml_risk_models (model, reason, created_by, is_current)
                        VALUES (%s, %s, %s, TRUE) RETURNING id""",
                     (json.dumps(aml_risk.merged(model)), reason, user_id)).fetchone()['id']
    db.commit()
    _cache['model'] = None
    try:
        from flask import request
        ip = request.remote_addr
    except Exception:
        ip = None
    from models.audit import AuditLog
    AuditLog.log(user_id, 'Customer risk model changed', 'AML', vid,
                 f'version {vid}: {diff_text(old, aml_risk.merged(model))}; reason: {reason}', ip)
    return vid


def diff_text(old, new, prefix=''):
    """Short description of what changed between two models."""
    out = []
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k), new.get(k)
        if isinstance(a, dict) and isinstance(b, dict):
            t = diff_text(a, b, f'{prefix}{k}.')
            if t != 'no change':
                out.append(t)
        elif a != b:
            out.append(f'{prefix}{k} {a} -> {b}')
    return '; '.join(out) or 'no change'


def _customer_input(c):
    return {'country': c.get('country') or '', 'customer_type': c.get('customer_type'),
            'business_activity': c.get('business_activity'), 'occupation': c.get('occupation'),
            'annual_income_range': c.get('annual_income_range')}


def preview(model, db=None):
    """What the model would do to the register, without writing anything:
    {'customers', 'by_class': {cls: (now, with_model)}, 'changed'}. Only model
    classes are compared; the HIGH floor (PEP, screening, table country) is
    applied on top in production and is not part of this preview."""
    db = db or get_db()
    m = aml_risk.merged(model)
    cur = current_model(db)
    rows = high_risk_rows(db) if (m['country']['source'] != 'builtin' or cur['country']['source'] != 'builtin') else []
    now, new, changed, n = {c: 0 for c in aml_risk.CLASSES}, {c: 0 for c in aml_risk.CLASSES}, 0, 0
    for c in db.execute("""SELECT country, customer_type, business_activity, occupation, annual_income_range
                             FROM customers""").fetchall():
        d = _customer_input(dict(c))
        a = aml_risk.calculate_risk_score(d, model=cur, high_risk_rows=rows)['classification']
        b = aml_risk.calculate_risk_score(d, model=m, high_risk_rows=rows)['classification']
        now[a] += 1
        new[b] += 1
        changed += a != b
        n += 1
    return {'customers': n, 'by_class': {c: (now[c], new[c]) for c in aml_risk.CLASSES}, 'changed': changed}
