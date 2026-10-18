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
Pure decision logic for IT / cyber / business-continuity evidence — no
Flask, no database, no regulator-specific values. Ages, validity windows and
warning periods arrive as arguments (from the regcontrols parameter registry
or the bound control's check settings).
"""

from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta


def _today(today):
    return today or date.today()


def dr_issues(sites, tests, today=None, max_age_months=None):
    """Problems with business-continuity / DR readiness."""
    today = _today(today)
    out = []
    dr = [s for s in sites if s.get('is_active', True) and s['site_type'] in ('dr', 'backup', 'cloud')]
    if not dr:
        return ['no active DR / backup site registered']
    done = sorted((t for t in tests if t.get('test_date')), key=lambda t: t['test_date'])
    if not done:
        return ['DR site never tested']
    last = done[-1]
    if max_age_months is not None and last['test_date'] < today - relativedelta(months=int(max_age_months)):
        out.append(f"last DR test {last['test_date']} older than {max_age_months} months")
    if last['result'] == 'fail':
        out.append(f"last DR test {last['test_date']} failed")
    elif last['result'] == 'partial':
        out.append(f"last DR test {last['test_date']} only partially successful")
    return out


def backup_issues(b, now=None, max_age_days=None):
    now = now or datetime.now()
    out = []
    if not b.get('is_active', True):
        return out
    if b.get('location_type') == 'onsite':
        out.append('no off-site copy')
    if not b.get('encrypted'):
        out.append('backup not encrypted')
    last = b.get('last_success_at')
    if not last:
        out.append('no successful backup recorded')
    elif max_age_days is not None and last < now - timedelta(days=int(max_age_days)):
        out.append(f'last successful backup {last:%Y-%m-%d} older than {max_age_days} day(s)')
    if b.get('last_status') == 'failed':
        out.append('last backup run failed')
    return out


def integration_issue(i, now=None, max_age_hours=24):
    now = now or datetime.now()
    if i['status'] != 'live':
        return f"status: {i['status']}"
    last = i.get('last_success_at')
    if not last:
        return 'no successful exchange recorded'
    if max_age_hours is not None and last < now - timedelta(hours=float(max_age_hours)):
        return f'last successful exchange {last:%Y-%m-%d %H:%M} older than {max_age_hours} h'
    return None


def assessment_issue(rows, today=None, max_open_critical=0):
    """Issue for one assessment type given its rows, or None when an accepted, valid one exists."""
    today = _today(today)
    acc = [r for r in rows if r['status'] == 'accepted']
    if not acc:
        return 'no accepted assessment'
    cur = max(acc, key=lambda r: r['performed_on'])
    if cur.get('valid_until') and cur['valid_until'] < today:
        return f"latest ({cur['performed_on']}) expired on {cur['valid_until']}"
    if max_open_critical is not None and (cur.get('critical_open') or 0) > int(max_open_critical):
        return f"latest ({cur['performed_on']}) has {cur['critical_open']} critical finding(s) open"
    return None


def asset_state(a, today=None, warn_days=30):
    """'inactive' | 'no_licence' | 'expired' | 'expiring' | 'ok'."""
    today = _today(today)
    if not a.get('is_active', True):
        return 'inactive'
    exp = a.get('licence_expiry')
    if not exp:
        return 'no_licence'
    if exp < today:
        return 'expired'
    if warn_days is not None and exp <= today + timedelta(days=int(warn_days)):
        return 'expiring'
    return 'ok'


def residency_issue(a):
    if a.get('sends_data_abroad') is None or not a.get('residency_attested_on'):
        return 'data-residency not attested'
    if a['sends_data_abroad']:
        return f"sends data abroad ({a.get('data_location') or 'location not stated'})"
    return None


def cert_state(d, now=None, warn_days=30, stale_hours=48):
    """'unchecked' | 'error' | 'expired' | 'expiring' | 'stale' | 'ok' for one monitored domain."""
    now = now or datetime.now()
    if not d.get('last_checked_at'):
        return 'unchecked'
    if d.get('last_error'):
        return 'error'
    na = d.get('cert_not_after')
    if not na:
        return 'error'
    if na < now:
        return 'expired'
    if warn_days is not None and na <= now + timedelta(days=int(warn_days)):
        return 'expiring'
    if stale_hours is not None and d['last_checked_at'] < now - timedelta(hours=stale_hours):
        return 'stale'
    return 'ok'


def maturity_summary(scores):
    """scores: [{requirement_id, current_level, target_level}] → averages and gaps."""
    rated = [s for s in scores if s.get('current_level') is not None]
    gaps = [s for s in rated if s.get('target_level') is not None and s['current_level'] < s['target_level']]
    avg = round(sum(s['current_level'] for s in rated) / len(rated), 2) if rated else None
    tgt = [s['target_level'] for s in rated if s.get('target_level') is not None]
    return {'rated': len(rated), 'total': len(scores), 'avg_current': avg,
            'avg_target': round(sum(tgt) / len(tgt), 2) if tgt else None, 'gaps': gaps,
            'unrated': len(scores) - len(rated)}


def risk_stale(r, today=None, max_age_days=None):
    """An active risk whose review is overdue or older than max_age_days."""
    today = _today(today)
    if (r.get('status') or 'ACTIVE') not in ('ACTIVE', 'ACCEPTED'):
        return None
    if r.get('next_review_date') and r['next_review_date'] < today:
        return f"review overdue since {r['next_review_date']}"
    last = r.get('last_review_date')
    if max_age_days is not None:
        if not last:
            return 'never reviewed'
        if last < today - timedelta(days=int(max_age_days)):
            return f'last reviewed {last} (older than {max_age_days} days)'
    return None
