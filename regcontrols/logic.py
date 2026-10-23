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
Pure decision logic for regcontrols — no Flask, no database.

Everything that decides something (which parameter version applies, what a
check result means, whether a closed finding must reopen, when an alert is due
for escalation) lives here so it can be unit-tested without PostgreSQL. The
service modules (params.py, engine.py, findings.py, alerts.py, evidence.py)
only load rows, call these functions and persist the outcome.
"""

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from dateutil.relativedelta import relativedelta


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class ParameterError(LookupError):
    """Base class for parameter lookup problems."""


class ParameterNotFound(ParameterError):
    """No active version of the parameter covers the requested date/licence."""


class ParameterNotSet(ParameterError):
    """The parameter exists but has no value yet (seeded, waiting for Compliance)."""


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------

def _as_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def select_param(rows, licence_type='all', as_of=None):
    """Pick the parameter version that applies.

    rows: every version of ONE key (dicts with licence_type, effective_from,
    effective_to, status). A version for the exact licence type beats the
    generic 'all' version; among the same licence, the latest effective_from
    wins. Only status 'active' rows are considered. Returns None if nothing
    covers `as_of`.
    """
    as_of = _as_date(as_of) or date.today()
    licence_type = licence_type or 'all'
    best, best_rank = None, None
    for r in rows:
        if (r.get('status') or 'active') != 'active':
            continue
        lic = r.get('licence_type') or 'all'
        if lic not in (licence_type, 'all'):
            continue
        start = _as_date(r.get('effective_from'))
        end = _as_date(r.get('effective_to'))
        if start and start > as_of:
            continue
        if end and end < as_of:
            continue
        rank = (1 if lic == licence_type and lic != 'all' else 0, start or date.min)
        if best_rank is None or rank > best_rank:
            best, best_rank = r, rank
    return best


def coerce_value(raw, value_type):
    """Turn the stored text into a Python value of the declared type.

    Raises ParameterNotSet for NULL/empty and ValueError for text that does
    not parse — a malformed regulatory number must fail loudly, not become 0.
    """
    if raw is None or (isinstance(raw, str) and raw.strip() == ''):
        raise ParameterNotSet('parameter has no value')
    vt = (value_type or 'text').lower()
    s = str(raw).strip()
    if vt in ('number', 'amount', 'percent'):
        try:
            return Decimal(s.replace(',', ''))
        except InvalidOperation:
            raise ValueError(f'not a number: {s!r}')
    if vt in ('integer', 'days'):
        try:
            return int(Decimal(s.replace(',', '')))
        except InvalidOperation:
            raise ValueError(f'not an integer: {s!r}')
    if vt == 'boolean':
        if s.lower() in ('1', 'true', 'yes', 'y', 'on'):
            return True
        if s.lower() in ('0', 'false', 'no', 'n', 'off'):
            return False
        raise ValueError(f'not a boolean: {s!r}')
    if vt == 'json':
        return json.loads(s)
    if vt == 'date':
        return _as_date(s)
    return s


def validate_value(raw, value_type):
    """Return an error message for an admin form, or None if the value is usable.
    Empty is allowed (it means "not configured yet")."""
    if raw is None or str(raw).strip() == '':
        return None
    try:
        coerce_value(raw, value_type)
    except (ValueError, TypeError) as e:
        return str(e)
    return None


def plan_version_change(existing_rows, licence_type, new_from):
    """Decide how an approved change lands in the version table.

    Returns (mode, row_id, close_ids, next_start):
      mode 'update' — a version with the same licence and effective_from
                      already exists; correct it in place (row_id).
      mode 'insert' — add a new version; close_ids are the open versions
                      for the same licence that start earlier and must end
                      the day before new_from.
    Versions that start AFTER new_from are left alone; the caller ends the
    new version the day before next_start so versions never overlap.
    """
    new_from = _as_date(new_from)
    same_lic = [r for r in existing_rows
                if (r.get('licence_type') or 'all') == (licence_type or 'all')
                and (r.get('status') or 'active') == 'active']
    for r in same_lic:
        if _as_date(r.get('effective_from')) == new_from:
            return 'update', r['id'], [], None
    close_ids = []
    later_starts = []
    for r in same_lic:
        start = _as_date(r.get('effective_from'))
        end = _as_date(r.get('effective_to'))
        if start and start < new_from and (end is None or end >= new_from):
            close_ids.append(r['id'])
        if start and start > new_from:
            later_starts.append(start)
    next_start = min(later_starts) if later_starts else None
    return 'insert', None, close_ids, next_start


# --------------------------------------------------------------------------
# Check results
# --------------------------------------------------------------------------

STATUSES = ('pass', 'warning', 'fail', 'error', 'no_check', 'not_applicable')
# Order used when several results are combined: the worst one wins.
_SEVERITY_ORDER = {'pass': 0, 'not_applicable': 0, 'no_check': 1, 'warning': 2, 'error': 3, 'fail': 4}

MAX_AFFECTED_STORED = 500


@dataclass
class CheckResult:
    status: str
    summary: str = ''
    details: dict = field(default_factory=dict)
    affected: list = field(default_factory=list)
    affected_count: int = 0

    def to_dict(self):
        return {'status': self.status, 'summary': self.summary, 'details': self.details,
                'affected': self.affected, 'affected_count': self.affected_count}


def normalise_result(raw):
    """Accept what a check returns and make it a CheckResult.

    Accepted shapes: a CheckResult; a dict with 'status' (+ optional
    summary/details/affected); a tuple (status, summary[, affected]); a bare
    status string; or a bool (True=pass, False=fail). Anything else is an
    'error' — the check author made a mistake and must see it.
    """
    if isinstance(raw, CheckResult):
        res = raw
    elif isinstance(raw, bool):
        res = CheckResult('pass' if raw else 'fail')
    elif isinstance(raw, str):
        res = CheckResult(raw)
    elif isinstance(raw, tuple) and raw:
        res = CheckResult(raw[0], raw[1] if len(raw) > 1 else '',
                          affected=list(raw[2]) if len(raw) > 2 and raw[2] else [])
    elif isinstance(raw, dict) and 'status' in raw:
        details = raw.get('details') or {}
        if not isinstance(details, dict):
            details = {'text': str(details)}
        res = CheckResult(raw['status'], raw.get('summary') or '', details,
                          list(raw.get('affected') or []), raw.get('affected_count') or 0)
    else:
        return CheckResult('error', f'check returned an unsupported value: {type(raw).__name__}')

    status = str(res.status or '').strip().lower()
    if status not in STATUSES:
        return CheckResult('error', f'check returned unknown status {res.status!r}')
    res.status = status
    affected = [_normalise_affected(a) for a in (res.affected or [])]
    res.affected_count = max(int(res.affected_count or 0), len(affected))
    res.affected = affected[:MAX_AFFECTED_STORED]
    if res.affected_count > len(res.affected):
        res.details = dict(res.details or {}, affected_truncated=True)
    return res


def _normalise_affected(a):
    if isinstance(a, dict):
        return {k: (v if isinstance(v, (int, float, str, bool)) or v is None else str(v))
                for k, v in a.items()}
    return {'label': str(a)}


def worst_status(statuses):
    statuses = [s for s in statuses if s]
    if not statuses:
        return 'no_check'
    return max(statuses, key=lambda s: _SEVERITY_ORDER.get(s, 3))


def is_failure(status):
    return status in ('fail',)


# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------

_FREQ_DELTA = {
    'daily': relativedelta(days=1),
    'weekly': relativedelta(weeks=1),
    'monthly': relativedelta(months=1),
    'quarterly': relativedelta(months=3),
    'semi_annual': relativedelta(months=6),
    'annual': relativedelta(years=1),
}


def next_due(frequency, after):
    """Next scheduled run after `after`, or None for event / on-demand controls."""
    delta = _FREQ_DELTA.get(frequency or '')
    if not delta or after is None:
        return None
    return after + delta


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------

def evidence_state(item, today=None, warn_days=30):
    """Lifecycle state of one evidence item, for display and for checks.

    'valid'    approved and in date (not within the warning window)
    'expiring' approved, but valid_to within warn_days
    'expired'  approved but valid_to passed, or already marked expired
    'pending'  submitted, waiting for a reviewer
    'rejected' / 'draft' as stored
    """
    today = _as_date(today) or date.today()
    status = item.get('status') or 'draft'
    if status in ('pending', 'rejected', 'draft'):
        return status
    if status == 'expired':
        return 'expired'
    valid_from = _as_date(item.get('valid_from'))
    valid_to = _as_date(item.get('valid_to'))
    if valid_from and valid_from > today:
        return 'pending'
    if valid_to and valid_to < today:
        return 'expired'
    if valid_to and (valid_to - today).days <= int(warn_days):
        return 'expiring'
    return 'valid'


def evidence_check_result(items, today=None, warn_days=30):
    """Generic result for controls that are proven by evidence.

    pass    at least one approved, in-date item that is not about to expire
    warning only expiring items, or only items still waiting for review
    fail    nothing approved and in date
    """
    states = [evidence_state(i, today, warn_days) for i in items]
    n_valid = states.count('valid')
    n_expiring = states.count('expiring')
    n_pending = states.count('pending')
    details = {'valid': n_valid, 'expiring': n_expiring, 'pending': n_pending,
               'expired': states.count('expired'), 'rejected': states.count('rejected')}
    if n_valid:
        return CheckResult('pass', f'{n_valid} valid evidence item(s)', details)
    if n_expiring:
        return CheckResult('warning', f'{n_expiring} evidence item(s) about to expire', details)
    if n_pending:
        return CheckResult('warning', f'{n_pending} evidence item(s) waiting for review', details)
    return CheckResult('fail', 'No approved, in-date evidence', details)


# --------------------------------------------------------------------------
# Findings: recurrence, ageing, verification
# --------------------------------------------------------------------------

OPEN_FINDING_STATUSES = ('open', 'action_plan', 'in_progress', 'pending_verification', 'reopened')
CLOSED_FINDING_STATUSES = ('closed',)


def recurrence_actions(linked_findings, run_status):
    """What a control run means for the findings linked to that control.

    Returns a list of (finding_id, action):
      'reopen_repeat' — the finding was closed and the control fails again:
                        reopen it and flag it as a repeated violation.
      'still_failing' — the finding is open and the control still fails
                        (recorded on the finding's history, nothing reopens).
    A finding closed as 'not_applicable' (closure_type) never reopens.
    """
    if not is_failure(run_status):
        return []
    actions = []
    for f in linked_findings:
        status = f.get('status')
        if status in CLOSED_FINDING_STATUSES:
            if (f.get('closure_type') or 'remediated') == 'remediated':
                actions.append((f['id'], 'reopen_repeat'))
        elif status in OPEN_FINDING_STATUSES:
            actions.append((f['id'], 'still_failing'))
    return actions


def verification_outcome(run_statuses):
    """Outcome of re-running every control linked to a finding.

    'verified'      every linked control passed
    'failed'        at least one linked control failed or errored
    'manual'        no linked control has an automated / evidence check —
                    a person must verify and record why
    'inconclusive'  warnings only (e.g. evidence waiting for review)
    """
    statuses = [s for s in run_statuses if s]
    if not statuses or all(s in ('no_check', 'not_applicable') for s in statuses):
        return 'manual'
    if any(s in ('fail', 'error') for s in statuses):
        return 'failed'
    if any(s == 'warning' for s in statuses):
        return 'inconclusive'
    return 'verified'


AGE_BUCKETS = (('0-30', 0, 30), ('31-60', 31, 60), ('61-90', 61, 90), ('90+', 91, None))


def four_eyes_error(verifier_id, requested_by=None, completed_by=()):
    """Segregation of duties for closing a finding on verification.

    The verifier must be someone other than the person who asked for
    verification and anyone who marked a corrective action done. Returns the
    (untranslated) reason it is refused, or None when the verifier is
    independent.
    """
    if verifier_id is None:
        return None
    if requested_by is not None and requested_by == verifier_id:
        return 'you requested verification of this finding; another person must verify it'
    if verifier_id in {u for u in (completed_by or ()) if u is not None}:
        return 'you marked a corrective action done; another person must verify the finding'
    return None


def age_bucket(opened, today=None):
    today = _as_date(today) or date.today()
    opened = _as_date(opened)
    if not opened:
        return '0-30'
    days = (today - opened).days
    for label, lo, hi in AGE_BUCKETS:
        if days >= lo and (hi is None or days <= hi):
            return label
    return '0-30'


def is_overdue(due, status, today=None, grace_days=0):
    if status not in OPEN_FINDING_STATUSES:
        return False
    due = _as_date(due)
    if not due:
        return False
    today = _as_date(today) or date.today()
    return today > due + timedelta(days=int(grace_days or 0))


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------

def escalation_due(alert, now=None, escalation_days=5):
    """True when an open alert has waited long enough to go to the Head of Compliance."""
    if alert.get('status') not in ('open', 'acknowledged') or alert.get('escalated_at'):
        return False
    raised = alert.get('raised_at')
    if not raised:
        return False
    now = now or datetime.now()
    if isinstance(raised, date) and not isinstance(raised, datetime):
        raised = datetime.combine(raised, datetime.min.time())
    return now - raised >= timedelta(days=int(escalation_days))


def renotify_due(alert, now=None, renotify_days=3):
    if alert.get('status') != 'open':
        return False
    last = alert.get('last_notified_at') or alert.get('raised_at')
    if not last:
        return True
    now = now or datetime.now()
    return now - last >= timedelta(days=int(renotify_days))


# --------------------------------------------------------------------------
# Findings CSV import
# --------------------------------------------------------------------------

FINDING_CSV_COLUMNS = ['title', 'description', 'severity', 'source', 'source_ref', 'area',
                       'identified_date', 'due_date', 'control_codes', 'owner_email']
FINDING_SOURCES = ('regulator', 'internal_audit', 'self_identified', 'external_audit', 'control_failure')
SEVERITIES = ('critical', 'high', 'medium', 'low')


def parse_findings_csv(text, known_controls=None):
    """Parse an uploaded findings CSV. Returns (rows, errors).

    Each row is a dict ready for raise_finding(); errors is a list of
    (line_number, message). Known control codes are checked when given so a
    typo does not silently drop the link that recurrence detection needs.
    """
    if text and text.startswith('﻿'):
        text = text[1:]
    reader = csv.DictReader(io.StringIO(text or ''))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    if 'title' not in headers:
        return [], [(1, 'missing required column "title"')]
    known = {c.upper() for c in known_controls} if known_controls is not None else None
    rows, errors = [], []
    for i, raw in enumerate(reader, start=2):
        r = {(k or '').strip().lower(): (v or '').strip() for k, v in raw.items()}
        if not any(r.values()):
            continue
        line_errors = []
        title = r.get('title')
        if not title:
            line_errors.append('title is required')
        severity = (r.get('severity') or 'medium').lower()
        if severity not in SEVERITIES:
            line_errors.append(f'severity must be one of {", ".join(SEVERITIES)}')
        source = (r.get('source') or 'regulator').lower()
        if source not in FINDING_SOURCES:
            line_errors.append(f'source must be one of {", ".join(FINDING_SOURCES)}')
        dates = {}
        for col in ('identified_date', 'due_date'):
            if r.get(col):
                try:
                    dates[col] = _as_date(r[col])
                except ValueError:
                    line_errors.append(f'{col} must be YYYY-MM-DD')
        codes = [c.strip().upper() for c in (r.get('control_codes') or '').replace(',', ';').split(';')
                 if c.strip()]
        if known is not None:
            unknown = [c for c in codes if c not in known]
            if unknown:
                line_errors.append('unknown control code(s): ' + ', '.join(unknown))
        if line_errors:
            errors.extend((i, e) for e in line_errors)
            continue
        rows.append({
            'title': title, 'description': r.get('description') or None, 'severity': severity,
            'source': source, 'source_ref': r.get('source_ref') or None, 'area': r.get('area') or None,
            'identified_date': dates.get('identified_date'), 'due_date': dates.get('due_date'),
            'control_codes': codes, 'owner_email': (r.get('owner_email') or '').lower() or None,
        })
    return rows, errors


def findings_csv_template():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(FINDING_CSV_COLUMNS)
    w.writerow(['Example: register of unusual transactions incomplete', 'Describe the observation',
                'high', 'regulator', 'Inspection letter ref', '', '2026-01-15', '2026-03-31',
                'CTRL-001;CTRL-002', 'owner@example.com'])
    return out.getvalue()
