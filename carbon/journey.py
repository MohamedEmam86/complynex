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

"""Carbon reporting journey: the nine steps a user follows, with a status
computed from data (never typed in).

    1 Boundary & base year      → 2 Entities & sites     → 3 Emission factors
    4 Activity data (evidence)  → 5 Data-quality checks  → 6 Review & approval
    7 Disclosure                → 8 Regulator submission & verification
    9 Offset obligation (only where the configured regulation requires it)

`compute(snapshot)` is pure (unit-tested); `snapshot(period_id)` reads the
data. Status values: not_started / in_progress / done / blocked /
not_applicable. Each step lists what is missing as (code, value) pairs that
the page translates, and the endpoint of the page that fixes it.
"""

from database.db import get_db

NOT_STARTED, IN_PROGRESS, DONE, BLOCKED, NA = 'not_started', 'in_progress', 'done', 'blocked', 'not_applicable'

STEPS = (
    ('boundary', 'carbon.boundary'),
    ('sites', 'carbon.boundary'),
    ('factors', 'carbon.factor_versions'),
    ('activity', 'carbon.activity'),
    ('quality', 'carbon.quality'),
    ('review', 'carbon.workflow'),
    ('disclosure', 'carbon.disclosure'),
    ('regulator', 'carbon.fra_compliance'),
    ('offsets', 'carbon.fra_compliance'),
)
# pages that belong to a step (for "you are here" in the stepper)
PAGE_STEP = {'carbon.boundary': 'boundary', 'carbon.settings': 'boundary', 'carbon.factor_versions': 'factors',
             'carbon.factors_library': 'factors', 'carbon.activity': 'activity', 'carbon.activity_files': 'activity',
             'carbon.financed': 'activity', 'carbon.quality': 'quality', 'carbon.workflow': 'review',
             'carbon.disclosure': 'disclosure', 'carbon.fra_compliance': 'regulator', 'carbon.fra_report': 'regulator'}
REGULATOR_DONE = 'Submitted'
# scopes normally recorded month by month (an entry without a month is a data-quality warning)
MONTHLY_SCOPES = ('scope1', 'scope2')


def _step(key, status, missing=()):
    return {'key': key, 'status': status, 'missing': list(missing)}


def compute(s):
    """s: snapshot dict (see snapshot()). Returns {'steps': [...], 'next': step|None, 'done': n, 'applicable': n}."""
    enabled = s.get('enabled') or []
    out = []

    # 1 boundary & base year
    miss = [(c, None) for c, ok in (('no_approach', s.get('approach')), ('no_base_year', s.get('base_year'))) if not ok]
    out.append(_step('boundary', DONE if not miss else (IN_PROGRESS if len(miss) == 1 else NOT_STARTED), miss))

    # 2 entities & sites (entities are optional: without them every site is consolidated in full)
    if s.get('sites_active'):
        out.append(_step('sites', DONE))
    else:
        out.append(_step('sites', IN_PROGRESS if s.get('entities') else NOT_STARTED, [('no_sites', None)]))

    # 3 emission factors — at least one current factor for every scope inside the boundary
    fbs = s.get('factors_by_scope') or {}
    miss = [('no_factors_scope', sc) for sc in enabled if not fbs.get(sc)]
    have = [sc for sc in enabled if fbs.get(sc)]
    out.append(_step('factors', DONE if enabled and not miss else (IN_PROGRESS if have else NOT_STARTED),
                     miss or ([] if enabled else [('no_scope', None)])))

    # 4 activity data with evidence
    n_in, n_ev = s.get('entries_in') or 0, s.get('entries_in_evidence') or 0
    if not s.get('period'):
        act = _step('activity', BLOCKED, [('no_period', None)])
    elif not have and not n_in:
        act = _step('activity', BLOCKED, [('needs_factors', None)])
    elif not n_in:
        act = _step('activity', NOT_STARTED, [('no_entries', None)])
    elif n_ev < n_in:
        act = _step('activity', IN_PROGRESS, [('no_evidence', n_in - n_ev)])
    else:
        act = _step('activity', DONE)
    if s.get('entries_no_month'):
        act['missing'].append(('no_month', s['entries_no_month']))
    if s.get('entries_out'):
        act['missing'].append(('outside_boundary', s['entries_out']))
    out.append(act)

    # 5 data-quality checks
    crit, warn = s.get('dq_critical') or 0, s.get('dq_warning') or 0
    if not n_in:
        dq = _step('quality', BLOCKED, [('needs_entries', None)])
    elif crit:
        dq = _step('quality', IN_PROGRESS, [('critical', crit)])
    else:
        dq = _step('quality', DONE)
    if n_in and warn:
        dq['missing'].append(('warnings', warn))
    out.append(dq)

    # 6 review & approval (period lock)
    wf = s.get('wf_status') or 'preparing'
    if wf == 'approved':
        out.append(_step('review', DONE))
    elif wf in ('in_review', 'reviewed'):
        out.append(_step('review', IN_PROGRESS, [('awaiting_review' if wf == 'in_review' else 'awaiting_approval', None)]))
    elif not n_in:
        out.append(_step('review', BLOCKED, [('needs_entries', None)]))
    elif crit:
        out.append(_step('review', BLOCKED, [('fix_critical', crit)]))
    else:
        out.append(_step('review', NOT_STARTED, [('submit', None)]))
    approved = wf == 'approved'

    # 7 disclosure
    if not approved:
        out.append(_step('disclosure', BLOCKED, [('needs_approval', None)]))
    else:
        out.append(_step('disclosure', DONE if s.get('disclosure_exported') else NOT_STARTED,
                         [] if s.get('disclosure_exported') else [('export', None)]))

    # 8 regulator submission & verification (only where a regulation is configured)
    applies, rs = s.get('regulator_applies'), s.get('regulator_status') or 'Draft'
    if applies is False:
        out.append(_step('regulator', NA, [('not_required', None)]))
    else:
        note = [('profile_unknown', None)] if applies is None else []
        if rs == REGULATOR_DONE:
            out.append(_step('regulator', DONE))
        elif rs != 'Draft':
            out.append(_step('regulator', IN_PROGRESS, [('regulator_status', rs)] + note))
        elif not approved:
            out.append(_step('regulator', BLOCKED, [('needs_approval', None)] + note))
        else:
            out.append(_step('regulator', NOT_STARTED, [('start_submission', None)] + note))

    # 9 offset obligation (only where the regulation requires offsets)
    ob = s.get('obligation')
    if applies is False or s.get('offsets_apply') is False:
        out.append(_step('offsets', NA, [('not_required', None)]))
    elif ob and ob.get('status') == 'FULFILLED':
        out.append(_step('offsets', DONE))
    elif ob:
        left = round(max(0.0, float(ob.get('required') or 0) - float(ob.get('purchased') or 0)), 3)
        out.append(_step('offsets', IN_PROGRESS, [('offset_overdue' if ob.get('status') == 'OVERDUE' else 'offset_remaining', left)]))
    else:
        out.append(_step('offsets', BLOCKED, [('needs_submission', None)]))

    for n, (st, (key, ep)) in enumerate(zip(out, STEPS), start=1):
        st['n'], st['endpoint'] = n, ep
    applicable = [x for x in out if x['status'] != NA]
    nxt = next((x for x in applicable if x['status'] in (IN_PROGRESS, NOT_STARTED)), None)
    return {'steps': out, 'next': nxt, 'done': sum(1 for x in applicable if x['status'] == DONE),
            'applicable': len(applicable)}


# ------------------------------------------------------------------ data
def _count(db, sql, args=()):
    try:
        r = db.execute(sql, args).fetchone()
        return int(list(dict(r).values())[0] or 0) if r else 0
    except Exception:
        db.rollback()
        return 0


def regulator_applicability(cfg):
    """(regulator_applies, offsets_apply) from the company profile and the configured
    parameters. False when no regulation is configured (no pack defines the threshold);
    None when the profile is incomplete."""
    from . import service as S
    threshold = S.param('carbon.report_threshold_egp')
    if threshold in (None, ''):
        return False, False
    basis = max(float(cfg.get('issued_capital_egp') or 0), float(cfg.get('net_equity_egp') or 0))
    applies = None if basis <= 0 else basis >= float(threshold)
    pct = S.param('carbon.offset_pct')
    offsets = False if applies is False or pct in (None, '') or float(pct) <= 0 else applies
    return applies, offsets


def boundary_split(rows, enabled):
    """Entries inside / outside the reporting boundary (scopes switched off are kept, not counted)."""
    inside = [e for e in rows if e.get('scope') in enabled]
    return inside, [e for e in rows if e.get('scope') not in enabled]


def snapshot(period_id=None, db=None):
    from . import service as S
    db = db or get_db()
    cfg = S.config(db)
    en = S.enabled_scopes(cfg)
    p = S.period(period_id, db)
    s = {'period': bool(p), 'approach': cfg.get('consolidation_approach'), 'base_year': cfg.get('base_year'),
         'enabled': en, 'entities': _count(db, "SELECT count(*) FROM carbon_entities"),
         'sites_active': _count(db, "SELECT count(*) FROM carbon_sites WHERE is_active"),
         'factors_by_scope': {sc: _count(db, "SELECT count(*) FROM carbon_emission_factors WHERE effective_to IS NULL AND scope = %s",
                                         (sc,)) for sc in ('scope1', 'scope2', 'scope3')}}
    s['regulator_applies'], s['offsets_apply'] = regulator_applicability(cfg)
    if p:
        rows = S.entries(p['id'], db)
        inside, outside = boundary_split(rows, en)
        dq = S.data_quality(p['id'], db)
        ids_in = {e['id'] for e in inside}
        unsupported = {i.get('entry_id') for i in dq['issues'] if i.get('code') == 'unsupported'}
        s.update(entries_in=len(inside), entries_out=len(outside),
                 entries_in_evidence=len(ids_in - unsupported),
                 entries_no_month=sum(1 for e in inside if not e.get('activity_month') and e.get('scope') in MONTHLY_SCOPES),
                 dq_critical=sum(1 for i in dq['issues'] if i['severity'] == 'critical'),
                 dq_warning=sum(1 for i in dq['issues'] if i['severity'] != 'critical'),
                 wf_status=S.workflow(p['id'], db).get('status'),
                 disclosure_exported=bool(_count(db, """SELECT count(*) FROM audit_logs WHERE module = 'carbon'
                                                    AND action IN ('carbon_disclosure_pdf', 'carbon_disclosure_xlsx') AND item_id = %s""",
                                                 (p['id'],))),
                 regulator_status=p.get('fra_status') or 'Draft')
        try:
            ob = db.execute("SELECT * FROM carbon_offset_obligations WHERE reporting_period_id = %s", (p['id'],)).fetchone()
            if ob:
                bought = _count(db, "SELECT COALESCE(sum(quantity_tco2e), 0) FROM carbon_offset_purchases WHERE obligation_id = %s",
                                (ob['id'],))
                s['obligation'] = {'status': ob['status'], 'required': ob['required_tco2e'], 'purchased': bought}
        except Exception:
            db.rollback()
    return s


def journey(period_id=None, db=None):
    return compute(snapshot(period_id, db))


def legal_basis(keys=('carbon.report_threshold_egp', 'carbon.offset_pct', 'carbon.offset_deadline_days',
                      'carbon.esg_report_threshold_egp', 'carbon.tcfd_threshold_egp')):
    """Configured regulatory parameters with their legal reference and the pack that installed them."""
    out = []
    try:
        from regcontrols.api import get_param_record
        from regcontrols.engine import company_licence_type
        lt = company_licence_type()
    except Exception:
        return out
    db = get_db()
    for k in keys:
        try:
            r = get_param_record(k, lt)
        except Exception:
            db.rollback()
            r = None
        if not r:
            continue
        r = dict(r)
        out.append({'key': k, 'value': r.get('value_text'), 'unit': r.get('unit'), 'description_en': r.get('description_en'),
                    'description_ar': r.get('description_ar'), 'legal_reference': r.get('legal_reference'),
                    'needs_review': r.get('needs_review'), 'pack': r.get('pack_code')})
    return out
