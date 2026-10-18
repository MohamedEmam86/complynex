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
Control engine: a registry of automated checks plus the code that runs them,
stores every run in rc_control_runs and hands the result to the alert and
findings services.

Any module registers a check for a control code:

    from regcontrols.api import register_check

    @register_check('FRA-017', name='Admin fee within cap')
    def admin_fee_cap(ctx):
        cap = ctx.param('lending.admin_fee_cap_pct')
        bad = [...]
        return ctx.fail(f'{len(bad)} loan(s) over the cap', affected=bad) if bad else ctx.ok('All loans within cap')

and adds its module path to CHECK_MODULES so the scheduler (a separate
process) imports it. Controls without a registered check fall back to the
generic evidence check when they are evidence-based; otherwise their run is
recorded as 'no_check' only when someone runs them by hand.

Scheduling: scripts/regcontrols_run.py (cron) calls run_due() and the
sweeps; the UI "Run now" button enqueues job_run_control() on the existing
RQ 'events' queue and falls back to running inline when Redis is down.
"""

import importlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime

from database.db import get_db

from . import logic, params
from .logic import CheckResult, ParameterError

logger = logging.getLogger(__name__)

# Modules imported by load_checks(). Later workstreams append their own
# (e.g. 'lending.checks', 'prudential.checks') — keep this the only list.
CHECK_MODULES = [
    'regcontrols.builtin_checks',
]

_MISSING = object()


@dataclass
class CheckSpec:
    control_code: str
    fn: object
    name: str
    module: str
    description: str = ''


CHECKS = {}
_loaded = False


def register_check(control_id, fn=None, *, name=None, description=None, replace=False):
    """Register `fn(ctx)` as the automated check for a control code.

    Usable as a plain call or as a decorator. Registering a second, different
    function for the same control raises unless replace=True — two modules
    silently fighting over one control would make results meaningless.
    """
    code = str(control_id).strip().upper()

    def _register(f):
        existing = CHECKS.get(code)
        if existing and existing.fn is not f and not replace:
            raise ValueError(f'a check is already registered for {code} ({existing.module}.{existing.name})')
        CHECKS[code] = CheckSpec(code, f, name or getattr(f, '__name__', 'check'),
                                 getattr(f, '__module__', ''), description or (f.__doc__ or '').strip())
        return f

    return _register(fn) if fn is not None else _register


def unregister_check(control_id):
    CHECKS.pop(str(control_id).strip().upper(), None)


def load_checks(force=False):
    global _loaded
    if _loaded and not force:
        return
    for mod in CHECK_MODULES:
        try:
            importlib.import_module(mod)
        except Exception:
            logger.exception('regcontrols: could not import check module %s', mod)
    _loaded = True


# ------------------------------------------------------------------ context
def company_licence_type():
    """The licence this installation runs under (Settings 'fra_licence_type')."""
    try:
        from models.settings import Settings
        return Settings.get('fra_licence_type', 'all') or 'all'
    except Exception:
        return 'all'


@dataclass
class CheckContext:
    control: dict
    as_of: date
    licence_type: str = 'all'
    org_unit_id: int = None
    db: object = None

    def param(self, key, default=_MISSING):
        """Typed regulatory parameter for this run's licence and date."""
        if default is _MISSING:
            return params.get_param(key, self.licence_type, self.as_of, db=self.db)
        return params.get_param(key, self.licence_type, self.as_of, default=default, db=self.db)

    # Small helpers so checks read naturally.
    def ok(self, summary='', **details):
        return CheckResult('pass', summary, details)

    def warn(self, summary, affected=None, **details):
        return CheckResult('warning', summary, details, list(affected or []))

    def fail(self, summary, affected=None, **details):
        return CheckResult('fail', summary, details, list(affected or []))

    def not_applicable(self, summary=''):
        return CheckResult('not_applicable', summary)


def applies_to_licence(control, licence_type):
    lics = control.get('licence_types') or ['all']
    return 'all' in lics or licence_type == 'all' or licence_type in lics


def execute_check(control, ctx, evidence_items=None):
    """Run the check for one control and return a normalised CheckResult.

    Never raises: a crashing check, a missing parameter or a bad return value
    all become an 'error' result that is stored and shown, so a broken check
    is visible instead of silently "passing".
    """
    code = control['control_code']
    if not applies_to_licence(control, ctx.licence_type):
        return CheckResult('not_applicable', f'Not applicable to licence type {ctx.licence_type}'), None
    spec = CHECKS.get(code)
    if spec:
        try:
            return logic.normalise_result(spec.fn(ctx)), spec.name
        except ParameterError as e:
            return CheckResult('error', str(e), {'parameter_error': True}), spec.name
        except Exception as e:
            logger.exception('regcontrols: check for %s crashed', code)
            return CheckResult('error', f'{type(e).__name__}: {e}'[:1000]), spec.name
    if evidence_items is not None and (control.get('control_type') == 'evidence' or evidence_items):
        try:
            warn_days = ctx.param('rc.evidence_expiry_warning_days', 30)
        except ParameterError:
            warn_days = 30
        return logic.evidence_check_result(evidence_items, ctx.as_of, warn_days), 'evidence'
    return CheckResult('no_check', 'No automated check is registered for this control yet.'), None


def has_runnable_check(control, evidence_count=0):
    return (control['control_code'] in CHECKS or control.get('control_type') == 'evidence'
            or evidence_count > 0)


# ------------------------------------------------------------------ runs
def get_control(control, db=None):
    """Accept an id, a code or a row dict."""
    db = db or get_db()
    if isinstance(control, dict):
        return control
    if isinstance(control, int) or str(control).isdigit():
        r = db.execute("SELECT * FROM rc_controls WHERE id = %s", (int(control),)).fetchone()
    else:
        r = db.execute("SELECT * FROM rc_controls WHERE control_code = %s", (str(control).upper(),)).fetchone()
    return dict(r) if r else None


def run_control(control, triggered_by='manual', user_id=None, finding_id=None, as_of=None,
                org_unit_id=None, db=None):
    """Run one control now. Returns the stored rc_control_runs row (dict)."""
    load_checks()
    db = db or get_db()
    control = get_control(control, db)
    if not control:
        raise ValueError('control not found')
    from . import evidence as evidence_svc
    items = evidence_svc.list_for_control(control['id'], db=db)
    ctx = CheckContext(control, logic._as_date(as_of) or date.today(), company_licence_type(), org_unit_id, db)

    started = datetime.now()
    t0 = time.monotonic()
    result, check_name = execute_check(control, ctx, items)
    duration = int((time.monotonic() - t0) * 1000)
    finished = datetime.now()

    if result.status == 'error':
        try:
            db.rollback()  # a check whose query failed leaves the transaction aborted
        except Exception:
            pass
    run_id = db.execute("""
        INSERT INTO rc_control_runs
            (control_id, org_unit_id, status, summary, details, affected_count, affected_records,
             check_name, triggered_by, run_by, finding_id, started_at, finished_at, duration_ms)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (control['id'], org_unit_id, result.status, result.summary[:4000] if result.summary else None,
          json.dumps(result.details or {}, default=str), result.affected_count,
          json.dumps(result.affected or [], default=str), check_name, triggered_by, user_id, finding_id,
          started, finished, duration)).fetchone()['id']
    db.execute("""UPDATE rc_controls SET last_run_id = %s, last_run_at = %s, last_status = %s,
                  next_run_due = %s, updated_at = %s WHERE id = %s""",
               (run_id, finished, result.status, logic.next_due(control['frequency'], finished), finished,
                control['id']))
    db.commit()

    run = dict(db.execute("SELECT * FROM rc_control_runs WHERE id = %s", (run_id,)).fetchone())
    from . import alerts, findings
    for hook in (alerts.handle_run, findings.handle_run):
        try:
            hook(control, run, db=db)
        except Exception:
            logger.exception('regcontrols: post-run hook %s failed for run %s', hook.__name__, run_id)
            db.rollback()
    return run


def due_controls(now=None, db=None):
    db = db or get_db()
    now = now or datetime.now()
    rows = [dict(r) for r in db.execute("""
        SELECT c.*, (SELECT count(*) FROM rc_evidence e WHERE e.control_id = c.id) AS evidence_count
        FROM rc_controls c
        WHERE c.is_active AND c.frequency NOT IN ('event', 'on_demand')
          AND (c.next_run_due IS NULL OR c.next_run_due <= %s)
        ORDER BY c.control_code
    """, (now,)).fetchall()]
    return [r for r in rows if has_runnable_check(r, r['evidence_count'])]


def run_due(now=None, db=None):
    """Run every control whose schedule is due. Returns counts by status."""
    load_checks()
    db = db or get_db()
    counts = {}
    for control in due_controls(now, db):
        try:
            run = run_control(control, triggered_by='schedule', db=db)
            counts[run['status']] = counts.get(run['status'], 0) + 1
        except Exception:
            logger.exception('regcontrols: scheduled run of %s failed', control['control_code'])
            db.rollback()
            counts['crashed'] = counts.get('crashed', 0) + 1
    return counts


def latest_runs(control_id, limit=20, db=None):
    db = db or get_db()
    return [dict(r) for r in db.execute("""
        SELECT r.*, u.first_name || ' ' || u.last_name AS run_by_name
        FROM rc_control_runs r LEFT JOIN users u ON u.id = r.run_by
        WHERE r.control_id = %s ORDER BY r.started_at DESC, r.id DESC LIMIT %s
    """, (control_id, limit)).fetchall()]


# ------------------------------------------------------------------ RQ jobs
def enqueue_run(control_code, user_id=None):
    """Hand a manual run to the RQ worker. Returns the job id, or None when the
    queue is unavailable (the caller then runs inline)."""
    try:
        from events.queue import get_queue
        job = get_queue().enqueue('regcontrols.engine.job_run_control', control_code, user_id, job_timeout=600)
        return job.id
    except Exception:
        logger.warning('regcontrols: RQ unavailable, running %s inline', control_code, exc_info=True)
        return None


def enqueue_due():
    try:
        from events.queue import get_queue
        return get_queue().enqueue('regcontrols.engine.job_run_due', job_timeout=3600).id
    except Exception:
        logger.warning('regcontrols: RQ unavailable for scheduled run', exc_info=True)
        return None


def _app():
    from events.dispatcher import _get_app
    return _get_app()


def job_run_control(control_code, user_id=None):
    with _app().app_context():
        run_control(control_code, triggered_by='manual', user_id=user_id)


def job_run_due():
    with _app().app_context():
        from . import alerts, evidence, findings
        run_due()
        evidence.sweep_expiry()
        findings.sweep_overdue()
        alerts.sweep_escalations()
