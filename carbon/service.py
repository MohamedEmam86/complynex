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
Service layer for carbon accounting (boundary, sites, versioned factors,
detailed activity entries, PCAF financed emissions, data quality, workflow
and period lock, intensity metrics, initiatives). Existing carbon pages keep
working on the same tables; this adds the controls an auditor and the
regulator expect.
"""

import json
from datetime import date, datetime

from database.db import get_db

from . import accounting as A
from .engine import compute_scope3_breakdown, compute_scope_totals


def N_(s):
    """Mark a message for translation (shown translated by the page)."""
    return s


class CarbonError(ValueError):
    pass


def _rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def _safe_rows(db, sql, args=()):
    try:
        return _rows(db, sql, args)
    except Exception:
        db.rollback()
        return []


def param(key, default=None):
    try:
        from regcontrols.api import get_param
        from regcontrols.engine import company_licence_type
        return get_param(key, company_licence_type(), default=default)
    except Exception:
        return default


def _date(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        raise CarbonError(N_('dates must be YYYY-MM-DD'))


def _f(v):
    if v in (None, ''):
        return None
    try:
        return float(str(v).replace(',', ''))
    except ValueError:
        raise CarbonError(N_('not a number'))


# ------------------------------------------------------------------ periods & boundary
def period(period_id=None, db=None):
    db = db or get_db()
    if period_id:
        r = db.execute("SELECT * FROM esg_reporting_periods WHERE id = %s", (period_id,)).fetchone()
    else:
        r = db.execute("""SELECT * FROM esg_reporting_periods WHERE status = 'open' ORDER BY start_date DESC LIMIT 1""").fetchone() \
            or db.execute("SELECT * FROM esg_reporting_periods ORDER BY start_date DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def periods(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM esg_reporting_periods ORDER BY start_date DESC")


def prior_period(p, db=None):
    db = db or get_db()
    if not p:
        return None
    r = db.execute("SELECT * FROM esg_reporting_periods WHERE start_date < %s ORDER BY start_date DESC LIMIT 1",
                   (p['start_date'],)).fetchone()
    return dict(r) if r else None


def config(db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM carbon_scope_config WHERE company_label = 'default'").fetchone()
    if not r:
        db.execute("INSERT INTO carbon_scope_config (company_label) VALUES ('default') ON CONFLICT DO NOTHING")
        db.commit()
        r = db.execute("SELECT * FROM carbon_scope_config WHERE company_label = 'default'").fetchone()
    return dict(r)


def save_boundary(data, user_id, db=None):
    db = db or get_db()
    ap = data.get('consolidation_approach')
    if ap not in A.APPROACHES:
        raise CarbonError(N_('choose a consolidation approach'))
    config(db)
    db.execute("""UPDATE carbon_scope_config SET consolidation_approach = %s, base_year = %s, base_year_tco2e = %s,
                  recalculation_threshold_pct = %s, recalculation_policy = %s, updated_by = %s, updated_at = %s
                  WHERE company_label = 'default'""",
               (ap, int(data['base_year']) if data.get('base_year') else None, _f(data.get('base_year_tco2e')),
                _f(data.get('recalculation_threshold_pct')), data.get('recalculation_policy') or None, user_id,
                datetime.now()))
    db.commit()


def entities(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM carbon_entities ORDER BY name")


def save_entity(data, entity_id=None, db=None):
    db = db or get_db()
    if not (data.get('name') or '').strip():
        raise CarbonError(N_('name is required'))
    vals = (data['name'].strip(), data.get('name_ar') or None, _f(data.get('ownership_pct')) if data.get('ownership_pct') not in (None, '') else 100,
            bool(data.get('operational_control')), bool(data.get('financial_control')), bool(data.get('included')),
            data.get('note') or None)
    if entity_id:
        db.execute("""UPDATE carbon_entities SET name = %s, name_ar = %s, ownership_pct = %s, operational_control = %s,
                      financial_control = %s, included = %s, note = %s WHERE id = %s""", (*vals, entity_id))
    else:
        entity_id = db.execute("""INSERT INTO carbon_entities (name, name_ar, ownership_pct, operational_control,
                                  financial_control, included, note) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                               vals).fetchone()['id']
    db.commit()
    return entity_id


def sites(db=None):
    db = db or get_db()
    return _rows(db, """SELECT s.*, e.name AS entity_name FROM carbon_sites s LEFT JOIN carbon_entities e ON e.id = s.entity_id
                        ORDER BY s.is_active DESC, s.name""")


def save_site(data, site_id=None, db=None):
    db = db or get_db()
    if not (data.get('name') or '').strip():
        raise CarbonError(N_('name is required'))
    vals = (data.get('entity_id') or None, data['name'].strip(), data.get('site_type') or 'office', data.get('city') or None,
            _f(data.get('floor_area_m2')), int(data['headcount']) if data.get('headcount') else None,
            bool(data.get('is_active', True)) if data.get('_form') is None else bool(data.get('is_active')),
            _date(data.get('opened_on')), _date(data.get('closed_on')))
    if site_id:
        db.execute("""UPDATE carbon_sites SET entity_id = %s, name = %s, site_type = %s, city = %s, floor_area_m2 = %s,
                      headcount = %s, is_active = %s, opened_on = %s, closed_on = %s WHERE id = %s""", (*vals, site_id))
    else:
        site_id = db.execute("""INSERT INTO carbon_sites (entity_id, name, site_type, city, floor_area_m2, headcount, is_active,
                                opened_on, closed_on) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", vals).fetchone()['id']
    db.commit()
    return site_id


def _share_for_site(site_id, db, approach):
    if not site_id:
        return 1.0
    r = db.execute("""SELECT e.* FROM carbon_sites s LEFT JOIN carbon_entities e ON e.id = s.entity_id WHERE s.id = %s""",
                   (site_id,)).fetchone()
    return A.inclusion_share(dict(r) if r and r['id'] else None, approach)


# ------------------------------------------------------------------ factor versions
def factor_codes(db=None):
    db = db or get_db()
    rows = _rows(db, "SELECT * FROM carbon_emission_factors ORDER BY factor_code, effective_from NULLS FIRST, id")
    by = {}
    for r in rows:
        by.setdefault(r['factor_code'] or f"F{r['id']}", []).append(r)
    return by


def factor_versions(code, db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM carbon_emission_factors WHERE factor_code = %s ORDER BY effective_from NULLS FIRST, id",
                 (code,))


def publish_factor_version(code, data, user_id, db=None):
    """New version of a factor: the current one is closed the day before; history is kept."""
    db = db or get_db()
    vers = factor_versions(code, db)
    value, eff = _f(data.get('factor_kgco2e')), _date(data.get('effective_from'))
    if value is None or not eff or not (data.get('source') or '').strip():
        raise CarbonError(N_('value, effective date and source are required'))
    base = vers[-1] if vers else None
    if not base and not (data.get('activity') and data.get('unit') and data.get('scope')):
        raise CarbonError(N_('a new factor needs scope, activity and unit'))
    if base and any((v.get('effective_from') or date.min) >= eff for v in vers):
        raise CarbonError(N_('the new version must start after the existing versions'))
    from datetime import timedelta
    if base:
        db.execute("UPDATE carbon_emission_factors SET effective_to = %s WHERE factor_code = %s AND effective_to IS NULL",
                   (eff - timedelta(days=1), code))
    src = base or {}
    rid = db.execute("""INSERT INTO carbon_emission_factors (factor_code, scope, category, ghg_category_no, activity, unit,
                        factor_kgco2e, source, vintage_year, notes, effective_from, version_label, region, source_url, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (code, data.get('scope') or src.get('scope'), data.get('category') or src.get('category'),
                      int(data['ghg_category_no']) if data.get('ghg_category_no') else src.get('ghg_category_no'),
                      data.get('activity') or src.get('activity'), data.get('unit') or src.get('unit'), value,
                      data['source'].strip(), int(data['vintage_year']) if data.get('vintage_year') else eff.year,
                      data.get('notes') or None, eff, data.get('version_label') or str(eff.year),
                      (data.get('region') or src.get('region') or 'EG')[:10], data.get('source_url') or None,
                      user_id)).fetchone()['id']
    db.commit()
    return rid


def factor_for(code, on_date, db=None):
    return A.select_factor_version(factor_versions(code, db), on_date)


# ------------------------------------------------------------------ workflow & lock
def workflow(period_id, db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM carbon_period_workflow WHERE reporting_period_id = %s", (period_id,)).fetchone()
    return dict(r) if r else {'reporting_period_id': period_id, 'status': 'preparing'}


def ensure_unlocked(period_id, db=None):
    if period_id and A.is_locked(workflow(period_id, db)):
        raise CarbonError(N_('this reporting period is approved and locked'))


def workflow_events(period_id, db=None):
    db = db or get_db()
    return _rows(db, """SELECT e.*, COALESCE(u.first_name || ' ' || u.last_name, '-') AS user_name FROM carbon_workflow_events e
                        LEFT JOIN users u ON u.id = e.user_id WHERE e.reporting_period_id = %s ORDER BY e.at""", (period_id,))


def workflow_action(period_id, action, user, note=None, db=None):
    db = db or get_db()
    wf = workflow(period_id, db)
    if action == 'unlock' and not user.is_admin():
        raise CarbonError(N_('only an administrator can unlock an approved inventory'))
    if action in ('unlock', 'return') and not (note or '').strip():
        raise CarbonError(N_('give the reason'))
    crit = sum(1 for i in data_quality(period_id, db)['issues'] if i['severity'] == 'critical') if action == 'submit' else 0
    try:
        new = A.next_state(wf, action, user.id, crit)
    except ValueError as e:
        raise CarbonError(str(e))
    now = datetime.now()
    sets = {'status': new}
    if action == 'submit':
        sets.update(prepared_by=user.id, prepared_at=now, reviewed_by=None, reviewed_at=None, approved_by=None, approved_at=None)
    elif action == 'review':
        sets.update(reviewed_by=user.id, reviewed_at=now)
        db.execute("""UPDATE carbon_activity_entries SET reviewed_by = %s, reviewed_at = %s
                      WHERE reporting_period_id = %s AND reviewed_by IS NULL""", (user.id, now, period_id))
    elif action == 'approve':
        sets.update(approved_by=user.id, approved_at=now)
    elif action in ('return', 'unlock'):
        sets.update(approved_by=None, approved_at=None, reviewed_by=None, reviewed_at=None)
    db.execute("INSERT INTO carbon_period_workflow (reporting_period_id) VALUES (%s) ON CONFLICT DO NOTHING", (period_id,))
    db.execute(f"UPDATE carbon_period_workflow SET {', '.join(f'{k} = %s' for k in sets)}, note = %s WHERE reporting_period_id = %s",
               (*sets.values(), note or None, period_id))
    db.execute("""INSERT INTO carbon_workflow_events (reporting_period_id, action, from_status, to_status, user_id, note)
                  VALUES (%s,%s,%s,%s,%s,%s)""", (period_id, action, wf.get('status'), new, user.id, note or None))
    db.commit()
    return new


# ------------------------------------------------------------------ entries
def entries(period_id, db=None):
    db = db or get_db()
    return _rows(db, """SELECT e.*, f.unit AS factor_unit, f.factor_code AS f_code, s.name AS site_name
                        FROM carbon_activity_entries e LEFT JOIN carbon_emission_factors f ON f.id = e.factor_id
                        LEFT JOIN carbon_sites s ON s.id = e.site_id WHERE e.reporting_period_id = %s
                        ORDER BY e.activity_month NULLS LAST, e.id""", (period_id,))


def has_evidence(e, db=None):
    if e.get('evidence_path'):
        return True
    db = db or get_db()
    return bool(_safe_rows(db, """SELECT 1 FROM generic_attachments WHERE module = 'carbon' AND record_type = 'carbon_entry'
                                  AND record_id = %s AND COALESCE(is_deleted, 0) = 0 LIMIT 1""", (e['id'],)))


def add_entry(period_id, data, user_id, db=None):
    """Detailed activity entry: the factor version in force in the activity month is used and stored."""
    db = db or get_db()
    ensure_unlocked(period_id, db)
    code = data.get('factor_code')
    month = _date((data.get('activity_month') or '') + ('-01' if len(data.get('activity_month') or '') == 7 else ''))
    p = period(period_id, db)
    on = month or (p['end_date'] if p else date.today())
    f = factor_for(code, on, db) if code else None
    if not f:
        raise CarbonError(N_('no factor version applies to that date'))
    helper = data.get('helper')
    qty = _f(data.get('quantity'))
    hin = None
    if helper == 'commuting':
        hin = {k: _f(data.get(k)) for k in ('employees', 'days_per_year', 'one_way_km')}
        qty = A.commuting_quantity(hin['employees'], hin['days_per_year'], hin['one_way_km'])
    elif helper == 'travel':
        hin = {k: _f(data.get(k)) for k in ('trips', 'distance_km', 'travellers')}
        qty = A.travel_quantity(hin['trips'], hin['distance_km'], hin['travellers'] or 1, bool(data.get('round_trip')))
    if qty is None:
        raise CarbonError(N_('quantity is required'))
    unit = (data.get('unit') or f['unit'])
    site_id = data.get('site_id') or None
    share = _share_for_site(site_id, db, config(db).get('consolidation_approach') or 'operational_control')
    res = A.compute_activity(qty, f, share, unit)
    basis = 'market' if (f['scope'] == 'scope2' and data.get('basis') == 'market') else 'location'
    rid = db.execute("""INSERT INTO carbon_activity_entries (reporting_period_id, site_id, scope, category, ghg_category_no, activity,
                        calc_method, quantity, unit, factor_id, tco2e, basis, notes, created_by, activity_month, factor_code,
                        factor_kgco2e_used, factor_source_used, factor_vintage_used, gross_tco2e, boundary_share,
                        instrument_type, instrument_ref, helper_inputs, updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (period_id, site_id, f['scope'], f['category'], f['ghg_category_no'], f['activity'],
                      helper or 'activity_based', qty, unit, f['id'], res['tco2e'], basis, data.get('notes') or None, user_id,
                      month, f['factor_code'], f['factor_kgco2e'], f['source'], f['vintage_year'], res['gross_tco2e'], share,
                      data.get('instrument_type') or None if basis == 'market' else None,
                      data.get('instrument_ref') or None if basis == 'market' else None,
                      json.dumps(hin) if hin else None, datetime.now())).fetchone()['id']
    db.commit()
    return rid, res


def set_entry_month(entry_id, month, db=None):
    """Add the missing activity month to an entry. Allowed only when the factor version in
    force in that month is the one the entry already used, so the recorded figure is unchanged."""
    db = db or get_db()
    e = db.execute("SELECT * FROM carbon_activity_entries WHERE id = %s", (entry_id,)).fetchone()
    if not e:
        raise CarbonError(N_('entry not found'))
    ensure_unlocked(e['reporting_period_id'], db)
    m = _date((month or '') + ('-01' if len(month or '') == 7 else ''))
    p = period(e['reporting_period_id'], db)
    if not m or (p and not (date(p['start_date'].year, p['start_date'].month, 1) <= m <= p['end_date'])):
        raise CarbonError(N_('choose a month inside the reporting period'))
    f = factor_for(e['factor_code'], m, db) if e['factor_code'] else None
    if f and f['id'] != e['factor_id']:
        raise CarbonError(N_('a different factor version applies to that month — delete the entry and record it again'))
    db.execute("UPDATE carbon_activity_entries SET activity_month = %s, updated_at = %s WHERE id = %s",
               (m, datetime.now(), entry_id))
    db.commit()


def delete_entry(entry_id, db=None):
    db = db or get_db()
    e = db.execute("SELECT reporting_period_id FROM carbon_activity_entries WHERE id = %s", (entry_id,)).fetchone()
    if not e:
        raise CarbonError(N_('entry not found'))
    ensure_unlocked(e['reporting_period_id'], db)
    db.execute("DELETE FROM carbon_activity_entries WHERE id = %s", (entry_id,))
    db.commit()


# ------------------------------------------------------------------ financed emissions (PCAF)
def exposures(period_id, db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM carbon_financed_exposures WHERE reporting_period_id = %s ORDER BY asset_class, id",
                 (period_id,))


def save_exposure(period_id, data, user_id, db=None, source='manual'):
    db = db or get_db()
    ensure_unlocked(period_id, db)
    method = data.get('method')
    if method not in A.PCAF_METHODS:
        raise CarbonError(N_('choose a PCAF method'))
    p = period(period_id, db)
    f = factor_for(data['factor_code'], p['end_date'] if p else date.today(), db) if data.get('factor_code') else None
    sector = float(f['factor_kgco2e']) / 1000.0 if f else None   # factor stored as kgCO2e per EGP m -> tCO2e
    x = {'outstanding': _f(data.get('outstanding')), 'attribution_base': _f(data.get('attribution_base')), 'method': method,
         'borrower_emissions_tco2e': _f(data.get('borrower_emissions_tco2e')),
         'borrower_revenue_egp': _f(data.get('borrower_revenue_egp')), 'asset_class': data.get('asset_class')}
    r = A.pcaf_exposure(x, sector)
    rid = db.execute("""INSERT INTO carbon_financed_exposures (reporting_period_id, reference, borrower, asset_class, sector,
                        outstanding, attribution_base, method, borrower_emissions_tco2e, borrower_revenue_egp, factor_id,
                        factor_kgco2e_used, attribution, financed_tco2e, data_quality_score, error, source, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (period_id, data.get('reference') or None, data.get('borrower') or None,
                      data.get('asset_class') or 'business_loans', data.get('sector') or None, x['outstanding'] or 0,
                      x['attribution_base'], method, x['borrower_emissions_tco2e'], x['borrower_revenue_egp'],
                      f['id'] if f else None, f['factor_kgco2e'] if f else None, r['attribution'], r['financed_tco2e'],
                      r['score'], r['error'], source, user_id)).fetchone()['id']
    db.commit()
    return rid, r


def financed_summary(period_id, db=None):
    rows = exposures(period_id, db)
    res = [(x, {'financed_tco2e': float(x['financed_tco2e'] or 0), 'score': x['data_quality_score'], 'error': x['error']})
           for x in rows]
    return A.pcaf_portfolio([(dict(x, outstanding=float(x['outstanding'] or 0)), r) for x, r in res])


# ------------------------------------------------------------------ metrics, initiatives
def metrics(period_id, db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM carbon_period_metrics WHERE reporting_period_id = %s", (period_id,)).fetchone()
    m = dict(r) if r else {'reporting_period_id': period_id}
    act = [s for s in sites(db) if s['is_active']]
    m.setdefault('headcount', None)
    m['headcount_sites'] = sum(s['headcount'] or 0 for s in act) or None
    m['floor_area_sites'] = sum(float(s['floor_area_m2'] or 0) for s in act) or None
    m['financed_exposures'] = financed_summary(period_id, db)['outstanding'] or None
    return m


def save_metrics(period_id, data, user_id, db=None):
    db = db or get_db()
    db.execute("""INSERT INTO carbon_period_metrics (reporting_period_id, revenue_egp, headcount, floor_area_m2,
                  financed_portfolio_egp, updated_by, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT (reporting_period_id) DO UPDATE SET revenue_egp = EXCLUDED.revenue_egp,
                  headcount = EXCLUDED.headcount, floor_area_m2 = EXCLUDED.floor_area_m2,
                  financed_portfolio_egp = EXCLUDED.financed_portfolio_egp, updated_by = EXCLUDED.updated_by,
                  updated_at = EXCLUDED.updated_at""",
               (period_id, _f(data.get('revenue_egp')), int(data['headcount']) if data.get('headcount') else None,
                _f(data.get('floor_area_m2')), _f(data.get('financed_portfolio_egp')), user_id, datetime.now()))
    db.commit()


def initiatives(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM carbon_initiatives ORDER BY status, target_date NULLS LAST, id")


def save_initiative(data, user_id, db=None):
    db = db or get_db()
    if not (data.get('title') or '').strip():
        raise CarbonError(N_('title is required'))
    st = data.get('status') if data.get('status') in ('planned', 'in_progress', 'done', 'cancelled') else 'planned'
    if data.get('initiative_id'):
        db.execute("""UPDATE carbon_initiatives SET status = %s, achieved_reduction_tco2e = %s WHERE id = %s""",
                   (st, _f(data.get('achieved_reduction_tco2e')), int(data['initiative_id'])))
    else:
        db.execute("""INSERT INTO carbon_initiatives (title, scope, owner_user_id, start_date, target_date, expected_reduction_tco2e,
                      cost_egp, status, note, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (data['title'].strip(), data.get('scope') or None, data.get('owner_user_id') or None,
                    _date(data.get('start_date')), _date(data.get('target_date')), _f(data.get('expected_reduction_tco2e')),
                    _f(data.get('cost_egp')), st, data.get('note') or None, user_id))
    db.commit()


# ------------------------------------------------------------------ data quality & inventory
def enabled_scopes(cfg):
    return [s for s, k in (('scope1', 'scope1_enabled'), ('scope2', 'scope2_enabled'), ('scope3', 'scope3_enabled'))
            if cfg.get(k) in (True, 1, '1', 't', 'true') or (k != 'scope3_enabled' and cfg.get(k) is None)]


def data_quality(period_id, db=None):
    db = db or get_db()
    p = period(period_id, db)
    if not p:
        return {'issues': [], 'entries': 0}
    cur = entries(period_id, db)
    pr = prior_period(p, db)
    prev = entries(pr['id'], db) if pr else []
    for e in cur + prev:
        e['factor_code'] = e.get('factor_code') or e.get('f_code')
    monthly = {e['factor_code'] for e in cur if e.get('scope') in ('scope1', 'scope2') and e.get('activity_month')}
    issues = A.dq_issues(cur, p['start_date'], p['end_date'], prev, param('carbon.outlier_pct', 50), monthly,
                         lambda e: has_evidence(e, db))
    for e in cur:   # Scope 1/2 are recorded month by month; a whole-period entry hides gaps
        if not e.get('activity_month') and e.get('scope') in ('scope1', 'scope2'):
            issues.append({'severity': 'warning', 'code': 'no_month', 'entry_id': e['id'],
                           'message': f"{e.get('activity')}: recorded for the whole period, no month"})
    # A figure the verifier cannot trace to an official source: factors marked indicative / estimate.
    flagged = {}
    for e in cur:
        src = ' '.join(str(e.get(k) or '') for k in ('factor_source_used', 'source', 'f_source'))
        if any(w in src.lower() for w in ('estimate', 'indicative', 'generic')) and e.get('factor_code') not in flagged:
            flagged[e.get('factor_code')] = e
    for code, e in flagged.items():
        issues.append({'severity': 'warning', 'code': 'indicative_factor', 'entry_id': e['id'],
                       'message': f"{e.get('activity')}: {e.get('factor_source_used') or 'factor'} — replace with the official national factor before verification"})
    for x in exposures(period_id, db):
        if x['error']:
            issues.append({'severity': 'warning', 'code': 'pcaf', 'message': f"PCAF {x['reference'] or x['id']}: {x['error']}"})
    return {'issues': issues, 'entries': len(cur)}


def inventory(period_id, db=None):
    """Everything the disclosure needs for one period."""
    db = db or get_db()
    p = period(period_id, db)
    cfg = config(db)
    en = enabled_scopes(cfg)
    rows = [e for e in entries(period_id, db) if e['scope'] in en]
    for e in rows:
        e['tco2e'] = float(e['tco2e'] or 0)
    totals = compute_scope_totals(rows)
    loc, mkt = A.scope2_dual(rows)
    totals['scope2_location'], totals['scope2_market'] = loc, mkt
    totals['total_location_based'] = round(totals['scope1'] + loc + totals['scope3'], 3)
    totals['total_market_based'] = round(totals['scope1'] + mkt + totals['scope3'], 3)
    fin = financed_summary(period_id, db)
    s3 = compute_scope3_breakdown(rows) if 'scope3' in en else {}
    if 'scope3' in en and fin['financed_tco2e']:
        s3.setdefault(15, {'label': 'Investments', 'tco2e': 0.0})
        s3[15]['tco2e'] = round(s3[15]['tco2e'] + fin['financed_tco2e'], 3)
        s3[15]['pcaf_score'] = fin['weighted_score']
        totals['scope3'] = round(totals['scope3'] + fin['financed_tco2e'], 3)
        totals['total_location_based'] = round(totals['total_location_based'] + fin['financed_tco2e'], 3)
        totals['total_market_based'] = round(totals['total_market_based'] + fin['financed_tco2e'], 3)
    m = metrics(period_id, db)
    ops = round(totals['scope1'] + totals['scope2_location'], 3)
    inten = A.intensities(totals['total_location_based'], m.get('headcount') or m.get('headcount_sites'),
                          m.get('floor_area_m2') or m.get('floor_area_sites'), m.get('revenue_egp'),
                          m.get('financed_portfolio_egp') or m.get('financed_exposures'), fin['financed_tco2e'])
    used = {}
    for e in rows:
        k = (e.get('factor_source_used') or '-', e.get('factor_vintage_used'))
        used[k] = used.get(k, 0) + 1
    off = _safe_rows(db, """SELECT p.* FROM carbon_offset_purchases p JOIN carbon_offset_obligations o ON o.id = p.obligation_id
                            WHERE o.reporting_period_id = %s""", (period_id,))
    return {'period': p, 'cfg': cfg, 'enabled': en, 'entries': rows, 'totals': totals, 'scope3': s3, 'financed': fin,
            'metrics': m, 'intensity': inten, 'operational_tco2e': ops,
            'factors_used': [{'source': k[0], 'vintage': k[1], 'entries': n} for k, n in sorted(used.items(), key=str)],
            'offsets': A.offsets_view(totals['total_location_based'], sum(float(x['quantity_tco2e'] or 0) for x in off)),
            'offset_purchases': off, 'workflow': workflow(period_id, db), 'events': workflow_events(period_id, db),
            'dq': data_quality(period_id, db), 'entities': entities(db), 'sites': sites(db)}
