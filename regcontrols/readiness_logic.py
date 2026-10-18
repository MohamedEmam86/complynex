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
Inspection readiness — pure scoring and calendar logic (no Flask, no DB).

Score of a set of controls = criticality-weighted average of the latest
result of each control:
    pass 100 · warning 50 · fail / error 0 · not assessed 0 (counted as a gap)
    not applicable → excluded.
Weights: critical 4 · high 3 · medium 2 · low 1.
"""

import calendar as _cal
from datetime import date, timedelta

WEIGHTS = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}
STATUS_SCORE = {'pass': 100, 'warning': 50, 'fail': 0, 'error': 0}
EXCLUDED = ('not_applicable',)


def control_points(c):
    """(weight, points 0-100 or None when excluded)."""
    st = c.get('last_status')
    if st in EXCLUDED:
        return 0, None
    return WEIGHTS.get(c.get('criticality') or 'medium', 2), STATUS_SCORE.get(st, 0)


def score(controls):
    """→ dict(score, controls, assessed, failing, not_assessed, by_status)."""
    tw = tp = 0
    out = {'controls': 0, 'assessed': 0, 'failing': 0, 'not_assessed': 0, 'by_status': {}}
    for c in controls:
        st = c.get('last_status') or 'not_run'
        out['by_status'][st] = out['by_status'].get(st, 0) + 1
        w, p = control_points(c)
        if p is None:
            continue
        out['controls'] += 1
        tw += w
        tp += w * p
        if st in STATUS_SCORE:
            out['assessed'] += 1
        else:
            out['not_assessed'] += 1
        if st in ('fail', 'error'):
            out['failing'] += 1
    out['score'] = round(tp / tw, 1) if tw else None
    return out


def band(s):
    if s is None:
        return 'none'
    return 'ready' if s >= 85 else 'partial' if s >= 60 else 'not_ready'


def by_area(controls):
    groups = {}
    for c in controls:
        groups.setdefault(c.get('area') or '-', []).append(c)
    return {a: score(cs) for a, cs in groups.items()}


def top_gaps(controls, n=10):
    """Failing / unassessed controls ordered by weight (critical first)."""
    gaps = [c for c in controls if c.get('last_status') not in ('pass', 'not_applicable')]
    return sorted(gaps, key=lambda c: (-WEIGHTS.get(c.get('criticality') or 'medium', 2),
                                       0 if c.get('last_status') in ('fail', 'error') else 1, c.get('control_code') or ''))[:n]


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------

def _day(year, month, day):
    return date(year, month, min(int(day or 1), _cal.monthrange(year, month)[1]))


def occurrences(frequency, due_day=None, due_month=None, start=None, end=None):
    """Due dates of a periodic submission between start and end (inclusive)."""
    start, end = start or date.today(), end or (date.today() + timedelta(days=365))
    f = (frequency or '').lower()
    out = []
    if f in ('monthly', 'quarterly', 'semi_annual', 'annual'):
        step = {'monthly': 1, 'quarterly': 3, 'semi_annual': 6, 'annual': 12}[f]
        anchor = int(due_month or (1 if f != 'monthly' else start.month))
        y, m = start.year - 1, anchor
        while True:
            d = _day(y, m, due_day or 1)
            if d > end:
                break
            if d >= start:
                out.append(d)
            m += step
            while m > 12:
                m -= 12
                y += 1
    elif f == 'weekly':
        d = start + timedelta(days=(int(due_day or 0) - start.weekday()) % 7)
        while d <= end:
            out.append(d)
            d += timedelta(days=7)
    return out


def reminders_due(item_date, today, days_list, already=()):
    """Reminder thresholds reached for one dated item (days before; 0 = due today)."""
    left = (item_date - today).days
    return sorted((d for d in days_list if left <= d and left >= -1 and d not in already), reverse=True)
