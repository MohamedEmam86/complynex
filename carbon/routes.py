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

"""Carbon Footprint & Climate module — routes.

A GHG Protocol-aligned Scope 1/2/3 carbon inventory inside the compliance
platform, with every figure traceable to the exact activity quantity and
emission factor (source + vintage year) that produced it. Regulator-specific
rules (thresholds, offset share and deadline) come from the parameter
registry, installed by the relevant regulatory pack.
"""
import os
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_babel import _
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from utils.decorators import permission_required
from models.audit import AuditLog
from database.db import get_db, query_db, execute_db
from carbon.engine import (
    compute_entry_emissions, compute_scope_totals, compute_scope3_breakdown,
    compute_intensity_metrics, compute_yoy_comparison, compute_target_progress,
    SCOPE3_CATEGORIES, SCOPE_LABELS,
)

carbon_bp = Blueprint('carbon', __name__, url_prefix='/carbon')


def _save_evidence(file, entity_id):
    if not file or not file.filename:
        return None
    filename = secure_filename(f"{entity_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
    rel_dir = f"carbon/activity/{entity_id}"
    upload_path = os.path.join(current_app.root_path, 'uploads', rel_dir, filename)
    os.makedirs(os.path.dirname(upload_path), exist_ok=True)
    file.save(upload_path)
    return f"uploads/{rel_dir}/{filename}"


def _current_period():
    row = query_db(
        "SELECT * FROM esg_reporting_periods WHERE status = 'open' ORDER BY start_date DESC LIMIT 1",
        one=True,
    )
    if not row:
        row = query_db("SELECT * FROM esg_reporting_periods ORDER BY start_date DESC LIMIT 1", one=True)
    return row


def _prior_period(current):
    if not current:
        return None
    return query_db(
        "SELECT * FROM esg_reporting_periods WHERE start_date < %s ORDER BY start_date DESC LIMIT 1",
        (current['start_date'],), one=True,
    )


def _entries_for_period(period_id):
    return query_db(
        "SELECT * FROM carbon_activity_entries WHERE reporting_period_id = %s",
        (period_id,),
    ) or []


def _locked(period_id):
    """An approved carbon inventory is locked (preparer → reviewer → approver workflow)."""
    try:
        from carbon.accounting import is_locked
        from carbon.service import workflow
        return is_locked(workflow(period_id))
    except Exception:
        get_db().rollback()
        return False


def _param(key, default):
    """Regulatory numbers come from the parameter registry; the default keeps the
    previous behaviour where the parameter is not installed."""
    from carbon.service import param
    v = param(key, default)
    return default if v is None else v


def _scope_config():
    """The company's Carbon Scope Profile (2026-07-21, Scope 1/2/3
    segregation feature). Defaults to Scope 1+2 enabled / Scope 3 disabled -
    exactly the FRA Decision 36/2026 reporting boundary - so a fresh
    deployment is FRA-compliant out of the box and Scope 3 is a deliberate
    opt-in. Keyed per company_label so a future multi-company model gets a
    profile per client with no rework."""
    row = query_db("SELECT * FROM carbon_scope_config WHERE company_label = 'default'", one=True)
    if not row:
        execute_db("INSERT INTO carbon_scope_config (company_label) VALUES ('default') ON CONFLICT (company_label) DO NOTHING")
        row = query_db("SELECT * FROM carbon_scope_config WHERE company_label = 'default'", one=True)
    return row


def _enabled_scopes(cfg=None):
    cfg = cfg or _scope_config()
    scopes = []
    if not cfg:
        return ['scope1', 'scope2', 'scope3']
    if cfg['scope1_enabled']:
        scopes.append('scope1')
    if cfg['scope2_enabled']:
        scopes.append('scope2')
    if cfg['scope3_enabled']:
        scopes.append('scope3')
    return scopes


def _filter_by_scopes(entries, enabled):
    """Cascade rule: disabled scopes disappear from dashboards, entry lists
    and reports, but the underlying rows are NEVER deleted - re-enabling a
    scope brings its history straight back."""
    return [e for e in entries if e['scope'] in enabled]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@carbon_bp.route('/')
@carbon_bp.route('/dashboard')
@login_required
@permission_required('carbon')
def dashboard():
    period = _current_period()
    scope_cfg = _scope_config()
    enabled = _enabled_scopes(scope_cfg)
    all_entries = _entries_for_period(period['id']) if period else []
    entries = _filter_by_scopes(all_entries, enabled)
    outside = [e for e in all_entries if e['scope'] not in enabled]
    totals = compute_scope_totals(entries)
    scope3_breakdown = compute_scope3_breakdown(entries) if 'scope3' in enabled else {}

    prior = _prior_period(period) if period else None
    prior_entries = _entries_for_period(prior['id']) if prior else []
    prior_totals = compute_scope_totals(prior_entries) if prior_entries else None
    yoy = compute_yoy_comparison(
        totals['total_location_based'],
        prior_totals['total_location_based'] if prior_totals else None,
    )

    target = query_db("SELECT * FROM carbon_targets ORDER BY id DESC LIMIT 1", one=True)
    target_progress = None
    if target and target['baseline_tco2e']:
        target_progress = compute_target_progress(
            target['baseline_year'], target['baseline_tco2e'],
            totals['total_location_based'], target['target_2030_pct'], 2030,
        )

    recent_entries = sorted(entries, key=lambda e: e['created_at'], reverse=True)[:8]

    from carbon import charts as CH
    site_names = {r['id']: r['name'] for r in (query_db("SELECT id, name FROM carbon_sites") or [])}
    charts = {'monthly': CH.monthly_by_scope(entries, enabled), 'category': CH.by_category(entries),
              'site': CH.by_site(entries, site_names),
              'pathway': CH.pathway(target, target_progress, totals['total_location_based'], period)}

    return render_template(
        'carbon/dashboard.html',
        period=period, totals=totals, scope3_breakdown=scope3_breakdown,
        yoy=yoy, target=target, target_progress=target_progress,
        recent_entries=recent_entries, scope_labels=SCOPE_LABELS,
        entry_count=len(entries), charts=charts,
        scope_cfg=scope_cfg, enabled_scopes=enabled,
        outside_count=len(outside), outside_tco2e=round(sum(float(e['tco2e'] or 0) for e in outside), 3),
        outside_by_scope={sc: round(sum(float(e['tco2e'] or 0) for e in outside if e['scope'] == sc), 3)
                          for sc in ('scope1', 'scope2', 'scope3') if any(e['scope'] == sc for e in outside)},
    )


# ---------------------------------------------------------------------------
# Activity entries (Scope 1 / 2 / 3 data collection)
# ---------------------------------------------------------------------------

@carbon_bp.route('/entries')
@login_required
@permission_required('carbon')
def entries_list():
    """Old activity log: merged into Activity data (one list for the whole journey)."""
    return redirect(url_for('carbon.activity', scope=request.args.get('scope') or None))


@carbon_bp.route('/entries/new', methods=['GET', 'POST'])
@login_required
@permission_required('carbon', level='edit')
def entry_new():
    period = _current_period()
    enabled = _enabled_scopes()
    factors = query_db(
        "SELECT * FROM carbon_emission_factors WHERE effective_to IS NULL ORDER BY scope, category, activity"
    ) or []
    # Scope segregation cascade: only factors for enabled scopes are offered.
    factors = [f for f in factors if f['scope'] in enabled]

    if request.method == 'POST':
        if not period:
            flash(_('No open reporting period exists yet — ask an admin to create one before logging activity.'), 'warning')
            return redirect(url_for('carbon.dashboard'))
        if _locked(period['id']):
            flash(_('This reporting period is approved and locked.'), 'danger')
            return redirect(url_for('carbon.entries_list'))

        factor_id = request.form.get('factor_id', type=int)
        factor = query_db("SELECT * FROM carbon_emission_factors WHERE id = %s", (factor_id,), one=True)
        if not factor:
            flash(_('Please select a valid emission factor.'), 'danger')
            return redirect(url_for('carbon.entry_new'))
        if factor['scope'] not in enabled:
            flash(_('That scope is not part of your current reporting boundary. Enable it in Carbon Settings first.'), 'warning')
            return redirect(url_for('carbon.entry_new'))

        quantity = request.form.get('quantity', type=float) or 0.0
        tco2e = compute_entry_emissions(quantity, factor['factor_kgco2e'])

        # NOTE: execute_db() returns rowcount on Postgres, not the RETURNING
        # value — for INSERT ... RETURNING id we go through get_db() directly
        # and read cursor.fetchone(), matching models/risk.py's convention.
        db = get_db()
        cursor = db.execute(
            """INSERT INTO carbon_activity_entries
               (reporting_period_id, site_id, scope, category, ghg_category_no, activity,
                calc_method, quantity, unit, factor_id, tco2e, basis, notes, created_by,
                factor_code, factor_kgco2e_used, factor_source_used, factor_vintage_used, gross_tco2e, boundary_share)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1) RETURNING id""",
            (period['id'], request.form.get('site_id', type=int) or None, factor['scope'],
             factor['category'], factor['ghg_category_no'], factor['activity'],
             request.form.get('calc_method', 'activity_based'), quantity, factor['unit'],
             factor['id'], tco2e, request.form.get('basis', 'location'),
             request.form.get('notes') or None, current_user.id,
             factor.get('factor_code'), factor['factor_kgco2e'], factor.get('source'), factor.get('vintage_year'), tco2e),
        )
        entry_id = cursor.fetchone()[0]
        db.commit()

        evidence_file = request.files.get('evidence')
        evidence_path = _save_evidence(evidence_file, entry_id)
        if evidence_path:
            execute_db("UPDATE carbon_activity_entries SET evidence_path = %s WHERE id = %s",
                       (evidence_path, entry_id))

        AuditLog.log(current_user.id, 'CREATE', module='carbon', item_id=entry_id,
                     details=f"Logged {factor['scope']} activity: {factor['activity']} "
                             f"({quantity} {factor['unit']} -> {tco2e} tCO2e)")
        flash(_('Activity logged: %(tco2e)s tCO2e recorded.', tco2e=tco2e), 'success')
        return redirect(url_for('carbon.entries_list'))

    # The entry form now lives on Activity data (same calculation, plus month, site and evidence).
    return redirect(url_for('carbon.activity', _anchor='add'))


@carbon_bp.route('/entries/<int:entry_id>/delete', methods=['POST'])
@login_required
@permission_required('carbon', level='edit')
def entry_delete(entry_id):
    entry = query_db("SELECT * FROM carbon_activity_entries WHERE id = %s", (entry_id,), one=True)
    if entry and _locked(entry['reporting_period_id']):
        flash(_('This reporting period is approved and locked.'), 'danger')
        return redirect(url_for('carbon.entries_list'))
    if entry:
        execute_db("DELETE FROM carbon_activity_entries WHERE id = %s", (entry_id,))
        AuditLog.log(current_user.id, 'DELETE', module='carbon', item_id=entry_id,
                     details=f"Deleted activity entry: {entry['activity']} ({entry['tco2e']} tCO2e)")
        flash(_('Entry deleted.'), 'info')
    return redirect(url_for('carbon.entries_list'))


# ---------------------------------------------------------------------------
# Emission factor library (read-heavy reference view)
# ---------------------------------------------------------------------------

@carbon_bp.route('/factors')
@login_required
@permission_required('carbon')
def factors_library():
    """Old factor library: merged into Emission factors (current values + version history)."""
    return redirect(url_for('carbon.factor_versions', scope=request.args.get('scope') or None))


# ---------------------------------------------------------------------------
# Reduction targets
# ---------------------------------------------------------------------------

@carbon_bp.route('/targets', methods=['GET', 'POST'])
@login_required
@permission_required('carbon')
def targets():
    target = query_db("SELECT * FROM carbon_targets ORDER BY id DESC LIMIT 1", one=True)

    if request.method == 'POST':
        if not current_user.can_edit('carbon'):
            flash(_('You do not have permission to edit targets.'), 'danger')
            return redirect(url_for('carbon.targets'))
        baseline_year = request.form.get('baseline_year', type=int)
        baseline_tco2e = request.form.get('baseline_tco2e', type=float)
        target_2030 = request.form.get('target_2030_pct', type=float)
        target_2035 = request.form.get('target_2035_pct', type=float)
        sbti = request.form.get('sbti_aligned') == 'on'
        notes = request.form.get('notes') or None

        if target:
            execute_db(
                """UPDATE carbon_targets SET baseline_year=%s, baseline_tco2e=%s,
                   target_2030_pct=%s, target_2035_pct=%s, sbti_aligned=%s, notes=%s,
                   updated_by=%s, updated_at=NOW() WHERE id=%s""",
                (baseline_year, baseline_tco2e, target_2030, target_2035, sbti, notes,
                 current_user.id, target['id']),
            )
        else:
            execute_db(
                """INSERT INTO carbon_targets
                   (baseline_year, baseline_tco2e, target_2030_pct, target_2035_pct, sbti_aligned, notes, updated_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (baseline_year, baseline_tco2e, target_2030, target_2035, sbti, notes, current_user.id),
            )
        AuditLog.log(current_user.id, 'UPDATE', module='carbon', details='Updated carbon reduction target')
        flash(_('Target updated.'), 'success')
        return redirect(url_for('carbon.targets'))

    period = _current_period()
    entries = _filter_by_scopes(_entries_for_period(period['id']) if period else [], _enabled_scopes())
    totals = compute_scope_totals(entries)
    progress = None
    if target and target['baseline_tco2e']:
        progress = compute_target_progress(target['baseline_year'], target['baseline_tco2e'],
                                            totals['total_location_based'], target['target_2030_pct'], 2030)
    return render_template('carbon/targets.html', target=target, progress=progress, totals=totals)


# ---------------------------------------------------------------------------
# Methodology — the transparency page every calculated figure links back to
# ---------------------------------------------------------------------------

@carbon_bp.route('/methodology')
@login_required
@permission_required('carbon')
def methodology():
    factor_count = query_db(
        "SELECT COUNT(*) as c FROM carbon_emission_factors WHERE effective_to IS NULL", one=True
    )['c']
    sources = query_db(
        "SELECT DISTINCT source, vintage_year FROM carbon_emission_factors "
        "WHERE effective_to IS NULL ORDER BY source"
    ) or []
    return render_template('carbon/methodology.html', factor_count=factor_count, sources=sources)


# ---------------------------------------------------------------------------
# Carbon Settings - Scope 1/2/3 reporting boundary + company profile
# (2026-07-21, scope segregation feature)
# ---------------------------------------------------------------------------

@carbon_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@permission_required('carbon', level='edit')
def settings():
    cfg = _scope_config()

    if request.method == 'POST':
        if not current_user.is_admin() and not current_user.can_edit('carbon'):
            flash(_('Access denied.'), 'danger')
            return redirect(url_for('carbon.dashboard'))

        s1 = request.form.get('scope1_enabled') == 'on'
        s2 = request.form.get('scope2_enabled') == 'on'
        s3 = request.form.get('scope3_enabled') == 'on'
        capital = request.form.get('issued_capital_egp', type=float)
        equity = request.form.get('net_equity_egp', type=float)
        fye = request.form.get('fiscal_year_end') or None

        before = f"S1={cfg['scope1_enabled']} S2={cfg['scope2_enabled']} S3={cfg['scope3_enabled']}"
        after = f"S1={s1} S2={s2} S3={s3}"

        execute_db("""
            UPDATE carbon_scope_config
            SET scope1_enabled=%s, scope2_enabled=%s, scope3_enabled=%s,
                issued_capital_egp=%s, net_equity_egp=%s, fiscal_year_end=%s,
                updated_by=%s, updated_at=NOW()
            WHERE company_label='default'
        """, (s1, s2, s3, capital, equity, fye, current_user.id))

        AuditLog.log(current_user.id, 'UPDATE', module='carbon',
                     details=f"Carbon scope profile changed: [{before}] -> [{after}]; "
                             f"capital={capital} equity={equity} fye={fye}")

        if not (s1 and s2):
            flash(_('Warning: carbon-reporting rules (for example the FRA framework) require Scope 1 and Scope 2 for obligated companies. Switch them off only if no such rule applies to you.'), 'warning')
        flash(_('Carbon settings saved.'), 'success')
        return redirect(url_for('carbon.settings'))

    # Applicability self-check vs FRA thresholds (EGP)
    applicability = None
    basis = max(x for x in [cfg['issued_capital_egp'] or 0, cfg['net_equity_egp'] or 0])
    if basis > 0:
        esg_t = float(_param('carbon.esg_report_threshold_egp', 100_000_000))
        tcfd_t = float(_param('carbon.tcfd_threshold_egp', 500_000_000))
        carb_t = float(_param('carbon.report_threshold_egp', 100_000_000))
        applicability = {
            'basis_egp': float(basis),
            'esg_107': basis >= esg_t,      # ESG report threshold (parameter)
            'tcfd_108': basis >= tcfd_t,    # TCFD layer threshold (parameter)
            'carbon_36': basis >= carb_t,   # carbon report + offsets threshold (parameter)
            'thresholds': {'esg': esg_t, 'tcfd': tcfd_t, 'carbon': carb_t},
        }

    entry_counts = {r['scope']: r['cnt'] for r in (query_db(
        "SELECT scope, COUNT(*) AS cnt FROM carbon_activity_entries GROUP BY scope") or [])}

    from carbon.journey import legal_basis
    return render_template('carbon/settings.html', cfg=cfg,
                           applicability=applicability, entry_counts=entry_counts, legal=legal_basis())


# ---------------------------------------------------------------------------
# FRA Decision 36/2026 compliance suite: annual report + verification
# lifecycle + 20% offset obligation tracking (2026-07-21)
# ---------------------------------------------------------------------------

FRA_STATUSES = ['Draft', 'Internal Review', 'Sent to Verifier', 'Certified', 'Submitted']


def _fra_context():
    from datetime import date, timedelta
    period = _current_period()
    cfg = _scope_config()
    enabled = _enabled_scopes(cfg)
    entries = _filter_by_scopes(_entries_for_period(period['id']) if period else [], enabled)
    totals = compute_scope_totals(entries)

    obligation = None
    purchases = []
    purchased = 0.0
    days_left = None
    if period:
        obligation = query_db(
            "SELECT * FROM carbon_offset_obligations WHERE reporting_period_id = %s AND status <> 'CANCELLED'",
            (period['id'],), one=True)
        if obligation:
            purchases = query_db(
                "SELECT p.*, u.email AS created_by_email FROM carbon_offset_purchases p "
                "LEFT JOIN users u ON p.created_by = u.id "
                "WHERE p.obligation_id = %s ORDER BY p.purchase_date",
                (obligation['id'],)) or []
            purchased = sum(float(x['quantity_tco2e'] or 0) for x in purchases)
            days_left = (obligation['deadline_date'] - date.today()).days
            # auto-status
            new_status = obligation['status']
            if purchased >= float(obligation['required_tco2e']):
                new_status = 'FULFILLED'
            elif days_left is not None and days_left < 0:
                new_status = 'OVERDUE'
            else:
                new_status = 'OPEN'
            if new_status != obligation['status']:
                execute_db("UPDATE carbon_offset_obligations SET status=%s WHERE id=%s",
                           (new_status, obligation['id']))
                obligation = query_db(
                    "SELECT * FROM carbon_offset_obligations WHERE id = %s",
                    (obligation['id'],), one=True)

    # readiness: entries with evidence + reviewer sign-off
    total_e = len(entries)
    with_evidence = sum(1 for e in entries if e['evidence_path'])
    reviewed = sum(1 for e in entries if e['reviewed_by'])
    readiness = {
        'total': total_e,
        'evidence_pct': round(100 * with_evidence / total_e) if total_e else 0,
        'reviewed_pct': round(100 * reviewed / total_e) if total_e else 0,
    }

    # compliance calendar
    calendar = []
    if cfg and cfg['fiscal_year_end']:
        fye = cfg['fiscal_year_end']
        today = date.today()
        # next fiscal year end
        nxt = fye
        while nxt < today:
            try:
                nxt = nxt.replace(year=nxt.year + 1)
            except ValueError:
                nxt = nxt.replace(year=nxt.year + 1, day=28)
        calendar.append({'label': _('Fiscal year end / annual carbon report alignment'),
                         'date': nxt, 'days': (nxt - today).days})
    first_due = _param('carbon.first_report_deadline', None)
    if isinstance(first_due, str):
        try:
            first_due = date.fromisoformat(first_due[:10])
        except ValueError:
            first_due = None
    if first_due and (not period or not period.get('submitted_to_fra_at')):
        calendar.insert(0, {'label': _('Carbon-footprint report due to the regulator'),
                            'date': first_due, 'days': (first_due - date.today()).days, 'key': 'report_due'})
    if obligation and obligation['status'] != 'FULFILLED':
        calendar.append({'label': _('Offset purchase deadline (%(d)s days after submission)', d=_param('carbon.offset_deadline_days', 90)),
                         'date': obligation['deadline_date'], 'days': days_left})

    verifiers = query_db("SELECT * FROM fra_verifiers WHERE is_active = TRUE ORDER BY name") or []
    calendar.sort(key=lambda c: c['date'])
    required = float(obligation['required_tco2e']) if obligation else None
    offset_progress = round(min(100.0, 100.0 * purchased / required), 1) if required else None

    return dict(period=period, cfg=cfg, enabled=enabled, entries=entries, totals=totals,
                obligation=obligation, purchases=purchases, purchased=round(purchased, 3),
                days_left=days_left, readiness=readiness, calendar=calendar,
                verifiers=verifiers, statuses=FRA_STATUSES, offset_progress=offset_progress,
                offset_chart=__import__('carbon.charts', fromlist=['x']).offset_doughnut(purchased, required))


@carbon_bp.route('/fra')
@login_required
@permission_required('carbon')
def fra_compliance():
    from carbon.journey import legal_basis
    ctx = _fra_context()
    return render_template('carbon/fra_compliance.html', **ctx, legal=legal_basis(),
                           offset_pct=_param('carbon.offset_pct', 20), offset_days=_param('carbon.offset_deadline_days', 90))


@carbon_bp.route('/fra/status', methods=['POST'])
@login_required
@permission_required('carbon', level='edit')
def fra_status():
    from datetime import date, timedelta
    period = _current_period()
    if not period:
        flash(_('No reporting period exists.'), 'warning')
        return redirect(url_for('carbon.fra_compliance'))

    new_status = request.form.get('fra_status')
    if new_status not in FRA_STATUSES:
        flash(_('Invalid status.'), 'error')
        return redirect(url_for('carbon.fra_compliance'))

    verifier_name = (request.form.get('verifier_name') or '').strip() or None
    verifier_contact = request.form.get('verifier_contact') or None
    notes = request.form.get('verification_notes') or None

    # A certified or submitted report must rest on an approved inventory and a
    # named independent verifier.
    if new_status in ('Certified', 'Submitted'):
        from carbon.service import workflow
        if (workflow(period['id']) or {}).get('status') != 'approved':
            flash(_('Approve the emissions inventory (workflow) before marking the report %(s)s.', s=_(new_status)), 'error')
            return redirect(url_for('carbon.fra_compliance'))
        if not (verifier_name or period.get('verifier_name')):
            flash(_('Name the independent verifier before marking the report %(s)s.', s=_(new_status)), 'error')
            return redirect(url_for('carbon.fra_compliance'))

    sets = ["fra_status = %s"]
    params = [new_status]
    if verifier_name:
        sets.append("verifier_name = %s"); params.append(verifier_name)
        # remember the verifier in the registry for reuse
        try:
            execute_db("INSERT INTO fra_verifiers (name, contact_info) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                       (verifier_name, verifier_contact))
        except Exception:
            pass
    if verifier_contact:
        sets.append("verifier_contact = %s"); params.append(verifier_contact)
    if notes:
        sets.append("verification_notes = %s"); params.append(notes)
    if new_status == 'Sent to Verifier':
        sets.append("sent_to_verifier_at = CURRENT_DATE")
    if new_status == 'Certified':
        sets.append("certified_at = CURRENT_DATE")
    if new_status == 'Submitted':
        sets.append("submitted_to_fra_at = CURRENT_DATE")
    params.append(period['id'])
    execute_db(f"UPDATE esg_reporting_periods SET {', '.join(sets)} WHERE id = %s", tuple(params))

    # Submitting the report starts the legal 90-day offset window:
    # obligation = 20% of the declared (enabled-scope) emissions.
    if new_status == 'Submitted':
        ctx = _fra_context()
        total = float(ctx['totals']['total_location_based'] or 0)
        pct = float(_param('carbon.offset_pct', 20))
        days = int(_param('carbon.offset_deadline_days', 90))
        required = round(total * pct / 100.0, 3)
        existing = query_db("SELECT id, status FROM carbon_offset_obligations WHERE reporting_period_id = %s",
                            (period['id'],), one=True)
        if existing and existing['status'] == 'CANCELLED':
            # Re-submitted after a revert: the cancelled obligation starts again.
            execute_db("""
                UPDATE carbon_offset_obligations SET total_emissions_tco2e = %s, offset_pct = %s, required_tco2e = %s,
                    report_submitted_date = CURRENT_DATE, deadline_date = CURRENT_DATE + %s, status = 'OPEN'
                WHERE id = %s""", (total, pct, required, days, existing['id']))
            flash(_('Report marked as submitted. Offset obligation created: %(req)s tCO2e (%(pct)s%%) due within %(days)s days.',
                    req=required, pct=pct, days=days), 'info')
        elif not existing:
            execute_db("""
                INSERT INTO carbon_offset_obligations
                    (reporting_period_id, total_emissions_tco2e, offset_pct, required_tco2e,
                     report_submitted_date, deadline_date, created_by)
                VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + %s, %s)
            """, (period['id'], total, pct, required, days, current_user.id))
            flash(_('Report marked as submitted. Offset obligation created: %(req)s tCO2e (%(pct)s%%) due within %(days)s days.',
                    req=required, pct=pct, days=days), 'info')

    # Back to Draft: the report is no longer submitted, so the offset obligation
    # its submission created is cancelled (kept, with any purchases, for the record).
    if new_status == 'Draft':
        cancelled = query_db("SELECT id FROM carbon_offset_obligations WHERE reporting_period_id = %s "
                             "AND status <> 'CANCELLED'", (period['id'],), one=True)
        if cancelled:
            execute_db("UPDATE carbon_offset_obligations SET status = 'CANCELLED' WHERE id = %s", (cancelled['id'],))
        execute_db("UPDATE esg_reporting_periods SET submitted_to_fra_at = NULL, certified_at = NULL WHERE id = %s",
                   (period['id'],))
        if cancelled:
            flash(_('The offset obligation created by the submission was cancelled.'), 'info')

    AuditLog.log(current_user.id, 'UPDATE', module='carbon',
                 details=f"FRA report status -> {new_status} (period {period['label']})")
    flash(_('FRA status updated to %(s)s.', s=new_status), 'success')
    return redirect(url_for('carbon.fra_compliance'))


@carbon_bp.route('/fra/offset/purchase', methods=['POST'])
@login_required
@permission_required('carbon', level='edit')
def fra_offset_purchase():
    period = _current_period()
    obligation = query_db("SELECT * FROM carbon_offset_obligations WHERE reporting_period_id = %s "
                          "AND status <> 'CANCELLED'", (period['id'],), one=True) if period else None
    if not obligation:
        flash(_('No open offset obligation - submit the FRA report first.'), 'warning')
        return redirect(url_for('carbon.fra_compliance'))

    project = request.form.get('project_name')
    qty = request.form.get('quantity_tco2e', type=float)
    pdate = request.form.get('purchase_date')
    if not project or not qty or not pdate:
        flash(_('Project name, quantity and purchase date are required.'), 'error')
        return redirect(url_for('carbon.fra_compliance'))

    execute_db("""
        INSERT INTO carbon_offset_purchases
            (obligation_id, project_name, registry_reference, quantity_tco2e,
             purchase_date, cost_egp, notes, created_by,
             fra_project_id, standard, vintage_year, serial_numbers, retired_on)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (obligation['id'], project, request.form.get('registry_reference') or None,
          qty, pdate, request.form.get('cost_egp', type=float),
          request.form.get('notes') or None, current_user.id,
          request.form.get('fra_project_id') or None, request.form.get('standard') or None,
          request.form.get('vintage_year', type=int), request.form.get('serial_numbers') or None,
          request.form.get('retired_on') or None))

    AuditLog.log(current_user.id, 'CREATE', module='carbon',
                 details=f"Offset purchase logged: {qty} tCO2e from {project}")
    flash(_('Certificate purchase logged: %(q)s tCO2e.', q=qty), 'success')
    return redirect(url_for('carbon.fra_compliance'))


@carbon_bp.route('/fra/report')
@login_required
@permission_required('carbon')
def fra_report():
    """The FRA annual carbon footprint report - printable, bilingual,
    scope-aware, with the GHG Protocol boundary statement. Blocks with a
    warning (rather than silently generating) while entries lack review."""
    ctx = _fra_context()

    # per-category rollup for the annex
    by_cat = {}
    for e in ctx['entries']:
        key = (e['scope'], e['category'])
        by_cat.setdefault(key, {'scope': e['scope'], 'category': e['category'],
                                'tco2e': 0.0, 'count': 0})
        by_cat[key]['tco2e'] += float(e['tco2e'] or 0)
        by_cat[key]['count'] += 1
    category_rows = sorted(by_cat.values(), key=lambda r: (r['scope'], -r['tco2e']))
    for r in category_rows:
        r['tco2e'] = round(r['tco2e'], 3)

    factor_sources = query_db(
        "SELECT DISTINCT source, vintage_year FROM carbon_emission_factors "
        "WHERE effective_to IS NULL ORDER BY source") or []

    from carbon.journey import legal_basis
    refs = {r['key']: r['legal_reference'] for r in legal_basis() if r.get('legal_reference')}
    return render_template('carbon/fra_report.html', **ctx,
                           category_rows=category_rows, factor_sources=factor_sources,
                           generated_at=datetime.now(),
                           carbon_ref=refs.get('carbon.report_threshold_egp') or refs.get('carbon.offset_pct')
                           or _('the FRA carbon-footprint decision (reference to be recorded in the regulatory parameters)'),
                           offset_pct=_param('carbon.offset_pct', 20), offset_days=_param('carbon.offset_deadline_days', 90))
