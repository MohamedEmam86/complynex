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

"""ESG Management module — routes.

A configurable, weighted ESG scoring engine (pillars, indicators and weights
are data, e.g. E/S/G plus a regulatory pillar) with every score traceable to
the indicator weights and raw answers behind it — no hardcoded formulas, so
the weighting scheme can evolve without a rebuild. Carbon results are shown
next to the indicators and disclosure items they feed (carbon/links.py).
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_babel import _
from flask_login import login_required, current_user

from utils.decorators import permission_required
from models.audit import AuditLog
from database.db import get_db, query_db, execute_db
from esg.engine import build_pillar_summary, MATURITY_LABELS, rating_band
from attachments.service import list_attachments
from carbon import links as carbon_links

esg_bp = Blueprint('esg', __name__, url_prefix='/esg')


def _default_framework():
    return query_db("SELECT * FROM esg_frameworks WHERE is_default = TRUE AND is_active = TRUE LIMIT 1", one=True)


def _current_period():
    row = query_db(
        "SELECT * FROM esg_reporting_periods WHERE status = 'open' ORDER BY start_date DESC LIMIT 1", one=True
    )
    if not row:
        row = query_db("SELECT * FROM esg_reporting_periods ORDER BY start_date DESC LIMIT 1", one=True)
    return row


def _pillars_with_indicators(framework_id, period_id):
    pillars = query_db(
        "SELECT * FROM esg_pillars WHERE framework_id = %s ORDER BY display_order", (framework_id,)
    ) or []
    result = []
    for p in pillars:
        indicators = query_db(
            "SELECT * FROM esg_indicators WHERE pillar_id = %s ORDER BY display_order", (p['id'],)
        ) or []
        responses = {}
        if period_id:
            resp_rows = query_db(
                """SELECT r.* FROM esg_indicator_responses r
                   JOIN esg_indicators i ON r.indicator_id = i.id
                   WHERE i.pillar_id = %s AND r.reporting_period_id = %s""",
                (p['id'], period_id),
            ) or []
            responses = {r['indicator_id']: r for r in resp_rows}

        ind_list = []
        for ind in indicators:
            resp = responses.get(ind['id'])
            ind_list.append({
                'id': ind['id'], 'code': ind['code'], 'name': ind['name'],
                'description': ind['description'], 'weight': ind['weight'], 'carbon_metric': ind.get('carbon_metric'),
                'score': resp['score'] if resp else None,
                'evidence_notes': resp['evidence_notes'] if resp else None,
            })
        result.append({
            'id': p['id'], 'code': p['code'], 'name': p['name'],
            'weight': p['weight'], 'indicators': ind_list,
        })
    return result


def _disclosure_completion(period_id):
    """Per-framework completion %, used by both the dashboard tile and the
    disclosure tracker's own summary header."""
    rows = query_db(
        "SELECT framework, status, COUNT(*) AS n FROM esg_disclosure_items "
        "WHERE reporting_period_id = %s GROUP BY framework, status",
        (period_id,),
    ) or []
    by_framework = {}
    for r in rows:
        fw = by_framework.setdefault(r['framework'], {'total': 0, 'applicable': 0, 'complete': 0, 'partial': 0})
        fw['total'] += r['n']  # includes not_applicable, shown for context (e.g. "3 items, 1 N/A")
        if r['status'] == 'not_applicable':
            continue
        fw['applicable'] += r['n']
        if r['status'] == 'complete':
            fw['complete'] += r['n']
        elif r['status'] == 'partial':
            fw['partial'] += r['n']
    for fw, d in by_framework.items():
        # Not Applicable items are excluded from the denominator once marked,
        # so they don't artificially suppress a framework's completion score.
        d['pct'] = round(100.0 * (d['complete'] + 0.5 * d['partial']) / d['applicable'], 1) if d['applicable'] else 0.0
    total_applicable = sum(d['applicable'] for d in by_framework.values())
    total_complete = sum(d['complete'] for d in by_framework.values())
    total_partial = sum(d['partial'] for d in by_framework.values())
    total_items = sum(d['total'] for d in by_framework.values())
    overall_pct = round(100.0 * (total_complete + 0.5 * total_partial) / total_applicable, 1) if total_applicable else None
    return {'by_framework': by_framework, 'overall_pct': overall_pct, 'total_items': total_items}


def _materiality_completion(period_id):
    total = query_db("SELECT COUNT(*) AS c FROM esg_materiality_topics WHERE is_active = TRUE", one=True)['c']
    scored = query_db(
        "SELECT COUNT(*) AS c FROM esg_materiality_scores WHERE reporting_period_id = %s "
        "AND stakeholder_importance IS NOT NULL AND business_impact IS NOT NULL",
        (period_id,), one=True,
    )['c']
    pct = round(100.0 * scored / total, 1) if total else 0.0
    return {'total': total, 'scored': scored, 'pct': pct}


def _carbon_values(period):
    """Carbon figures of the same reporting period, for users who may see Carbon."""
    if not period or not current_user.can_view('carbon'):
        return None
    return carbon_links.carbon_values(period['id'])


def _carbon_summary(period):
    vals = _carbon_values(period)
    if vals is None:
        return None
    try:
        from carbon.journey import journey
        return {'values': vals, 'journey': journey(period['id'])}
    except Exception:
        get_db().rollback()
        return {'values': vals, 'journey': None}


def _metric_from_form(value):
    return value if value in carbon_links.METRICS or value == 'none' else None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@esg_bp.route('/')
@esg_bp.route('/dashboard')
@login_required
@permission_required('esg')
def dashboard():
    framework = _default_framework()
    period = _current_period()
    summary = None
    if framework and period:
        pillars = _pillars_with_indicators(framework['id'], period['id'])
        summary = build_pillar_summary(pillars)

    disclosure_progress = None
    materiality_progress = None
    if period:
        disclosure_progress = _disclosure_completion(period['id'])
        materiality_progress = _materiality_completion(period['id'])

    return render_template(
        'esg/dashboard.html', framework=framework, period=period, summary=summary,
        maturity_labels=MATURITY_LABELS,
        disclosure_progress=disclosure_progress, materiality_progress=materiality_progress,
        carbon=_carbon_summary(period),
    )


# ---------------------------------------------------------------------------
# Scoring entry — one page per pillar, live-summary panel driven by the same
# build_pillar_summary() the dashboard uses, so the two views never diverge.
# ---------------------------------------------------------------------------

@esg_bp.route('/scoring/<pillar_code>', methods=['GET', 'POST'])
@login_required
@permission_required('esg', level='view')
def scoring(pillar_code):
    framework = _default_framework()
    period = _current_period()
    if not framework or not period:
        flash(_('No active ESG framework or reporting period found.'), 'warning')
        return redirect(url_for('esg.dashboard'))

    pillar = query_db(
        "SELECT * FROM esg_pillars WHERE framework_id = %s AND code = %s",
        (framework['id'], pillar_code), one=True,
    )
    if not pillar:
        flash(_('Unknown pillar.'), 'danger')
        return redirect(url_for('esg.dashboard'))

    if request.method == 'POST':
        if not current_user.can_edit('esg'):
            flash(_('You do not have permission to submit ESG scores.'), 'danger')
            return redirect(url_for('esg.scoring', pillar_code=pillar_code))

        indicators = query_db("SELECT * FROM esg_indicators WHERE pillar_id = %s", (pillar['id'],)) or []
        for ind in indicators:
            if f"metric_{ind['id']}" in request.form:   # which carbon figure feeds this indicator (display only)
                try:
                    execute_db("UPDATE esg_indicators SET carbon_metric = %s WHERE id = %s",
                               (_metric_from_form(request.form.get(f"metric_{ind['id']}")), ind['id']))
                except Exception:
                    get_db().rollback()
            score_raw = request.form.get(f"score_{ind['id']}")
            notes = request.form.get(f"notes_{ind['id']}") or None
            if score_raw in (None, ''):
                continue
            score = float(score_raw)
            existing = query_db(
                "SELECT id FROM esg_indicator_responses WHERE reporting_period_id=%s AND indicator_id=%s",
                (period['id'], ind['id']), one=True,
            )
            if existing:
                execute_db(
                    """UPDATE esg_indicator_responses SET score=%s, evidence_notes=%s,
                       updated_by=%s, updated_at=NOW() WHERE id=%s""",
                    (score, notes, current_user.id, existing['id']),
                )
            else:
                execute_db(
                    """INSERT INTO esg_indicator_responses
                       (reporting_period_id, indicator_id, score, evidence_notes, updated_by)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (period['id'], ind['id'], score, notes, current_user.id),
                )
        AuditLog.log(current_user.id, 'UPDATE', module='esg', item_id=pillar['id'],
                     details=f"Submitted ESG scores for pillar {pillar['code']} ({pillar['name']})")
        flash(_('Scores saved.'), 'success')
        return redirect(url_for('esg.scoring', pillar_code=pillar_code))

    pillars = _pillars_with_indicators(framework['id'], period['id'])
    this_pillar = next((p for p in pillars if p['code'] == pillar_code), None)
    cvals = _carbon_values(period)
    for ind in (this_pillar or {}).get('indicators', []):
        ind['carbon_feed'] = carbon_links.feed(ind, cvals, 'code', 'name', 'description')
    summary = build_pillar_summary(pillars)
    this_pillar_summary = next((p for p in summary['pillars'] if p['code'] == pillar_code), None)

    return render_template(
        'esg/scoring.html', framework=framework, period=period, pillar=this_pillar,
        pillar_summary=this_pillar_summary, maturity_labels=MATURITY_LABELS, rating_band=rating_band,
        attach_module='esg', attach_record_type='esg_pillar', attach_record_id=pillar['id'],
        attach_items=list_attachments('esg', 'esg_pillar', pillar['id']),
        attach_can_edit=current_user.can_edit('esg'),
        carbon_values=cvals, carbon_metrics=carbon_links.METRICS,
    )


# ---------------------------------------------------------------------------
# Framework view — shows the weighting scheme transparently (data, not code)
# ---------------------------------------------------------------------------

@esg_bp.route('/framework')
@login_required
@permission_required('esg')
def framework_view():
    framework = _default_framework()
    period = _current_period()
    pillars = _pillars_with_indicators(framework['id'], period['id']) if framework and period else []
    summary = build_pillar_summary(pillars) if pillars else None
    return render_template('esg/framework.html', framework=framework, pillars=pillars, summary=summary)


# ---------------------------------------------------------------------------
# Methodology — the transparency page every score links back to
# ---------------------------------------------------------------------------

@esg_bp.route('/methodology')
@login_required
@permission_required('esg')
def methodology():
    framework = _default_framework()
    return render_template('esg/methodology.html', framework=framework, maturity_labels=MATURITY_LABELS)


# ---------------------------------------------------------------------------
# Materiality assessment workshop — stakeholder importance x business impact
# per topic; renders as a 2x2 matrix so the highest-priority (top-right)
# topics are visually obvious, matching how materiality workshops are
# actually run and presented to a board/audit committee.
# ---------------------------------------------------------------------------

@esg_bp.route('/materiality', methods=['GET', 'POST'])
@login_required
@permission_required('esg', level='view')
def materiality():
    period = _current_period()
    if not period:
        flash(_('No active reporting period found.'), 'warning')
        return redirect(url_for('esg.dashboard'))

    if request.method == 'POST':
        if not current_user.can_edit('esg'):
            flash(_('You do not have permission to submit materiality scores.'), 'danger')
            return redirect(url_for('esg.materiality'))

        topics = query_db("SELECT id FROM esg_materiality_topics WHERE is_active = TRUE") or []
        for t in topics:
            imp_raw = request.form.get(f"importance_{t['id']}")
            impact_raw = request.form.get(f"impact_{t['id']}")
            notes = request.form.get(f"notes_{t['id']}") or None
            if imp_raw in (None, '') and impact_raw in (None, ''):
                continue
            importance = float(imp_raw) if imp_raw not in (None, '') else None
            impact = float(impact_raw) if impact_raw not in (None, '') else None
            existing = query_db(
                "SELECT id FROM esg_materiality_scores WHERE reporting_period_id=%s AND topic_id=%s",
                (period['id'], t['id']), one=True,
            )
            if existing:
                execute_db(
                    """UPDATE esg_materiality_scores SET stakeholder_importance=%s, business_impact=%s,
                       notes=%s, updated_by=%s, updated_at=NOW() WHERE id=%s""",
                    (importance, impact, notes, current_user.id, existing['id']),
                )
            else:
                execute_db(
                    """INSERT INTO esg_materiality_scores
                       (reporting_period_id, topic_id, stakeholder_importance, business_impact, notes, updated_by)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (period['id'], t['id'], importance, impact, notes, current_user.id),
                )
        AuditLog.log(current_user.id, 'UPDATE', module='esg',
                     details='Submitted materiality assessment scores')
        flash(_('Materiality scores saved.'), 'success')
        return redirect(url_for('esg.materiality'))

    topics = query_db(
        "SELECT * FROM esg_materiality_topics WHERE is_active = TRUE ORDER BY display_order"
    ) or []
    scores = query_db(
        "SELECT * FROM esg_materiality_scores WHERE reporting_period_id = %s", (period['id'],)
    ) or []
    scores_by_topic = {s['topic_id']: s for s in scores}

    plotted = []
    for t in topics:
        s = scores_by_topic.get(t['id'])
        if s and s['stakeholder_importance'] is not None and s['business_impact'] is not None:
            plotted.append({
                'topic': t, 'importance': s['stakeholder_importance'], 'impact': s['business_impact'],
            })

    return render_template(
        'esg/materiality.html', period=period, topics=topics, scores_by_topic=scores_by_topic,
        plotted=plotted, completion=_materiality_completion(period['id']),
    )


# ---------------------------------------------------------------------------
# GRI / IFRS S1&S2 / TCFD / EGX disclosure tracker
# ---------------------------------------------------------------------------

@esg_bp.route('/disclosures')
@login_required
@permission_required('esg')
def disclosures():
    period = _current_period()
    if not period:
        flash(_('No active reporting period found.'), 'warning')
        return redirect(url_for('esg.dashboard'))

    framework = request.args.get('framework') or None
    status = request.args.get('status') or None
    q = "SELECT d.*, (u.first_name || ' ' || u.last_name) AS owner_name FROM esg_disclosure_items d " \
        "LEFT JOIN users u ON d.owner_id = u.id WHERE d.reporting_period_id = %s"
    params = [period['id']]
    if framework:
        q += " AND d.framework = %s"
        params.append(framework)
    if status:
        q += " AND d.status = %s"
        params.append(status)
    q += " ORDER BY d.framework, d.ref_code"
    items = [dict(i) for i in (query_db(q, tuple(params)) or [])]
    cvals = _carbon_values(period)
    for it in items:
        it['carbon_feed'] = carbon_links.feed(it, cvals, 'ref_code', 'title', 'requirement')

    frameworks = query_db(
        "SELECT DISTINCT framework FROM esg_disclosure_items WHERE reporting_period_id = %s ORDER BY framework",
        (period['id'],),
    ) or []
    users = query_db(
        "SELECT id, (first_name || ' ' || last_name) AS full_name FROM users "
        "WHERE is_active = 1 ORDER BY first_name, last_name"
    ) or []

    return render_template(
        'esg/disclosures.html', period=period, items=items, current_framework=framework,
        current_status=status, frameworks=[f['framework'] for f in frameworks], users=users,
        completion=_disclosure_completion(period['id']),
        carbon_values=cvals, carbon_metrics=carbon_links.METRICS,
    )


@esg_bp.route('/disclosures/<int:item_id>/update', methods=['POST'])
@login_required
@permission_required('esg', level='edit')
def disclosure_update(item_id):
    item = query_db("SELECT * FROM esg_disclosure_items WHERE id = %s", (item_id,), one=True)
    if not item:
        flash(_('Disclosure item not found.'), 'danger')
        return redirect(url_for('esg.disclosures'))

    status = request.form.get('status', 'not_started')
    owner_id = request.form.get('owner_id', type=int) or None
    evidence_notes = request.form.get('evidence_notes') or None

    execute_db(
        """UPDATE esg_disclosure_items SET status=%s, owner_id=%s, evidence_notes=%s,
           updated_by=%s, updated_at=NOW() WHERE id=%s""",
        (status, owner_id, evidence_notes, current_user.id, item_id),
    )
    if 'carbon_metric' in request.form:   # which carbon figure is shown next to this item (display only)
        try:
            execute_db("UPDATE esg_disclosure_items SET carbon_metric = %s WHERE id = %s",
                       (_metric_from_form(request.form.get('carbon_metric')), item_id))
        except Exception:
            get_db().rollback()
    AuditLog.log(current_user.id, 'UPDATE', module='esg', item_id=item_id,
                 details=f"Updated disclosure {item['framework']} {item['ref_code']} -> status={status}")
    flash(_('Disclosure item updated.'), 'success')
    return redirect(url_for('esg.disclosures', framework=request.form.get('return_framework') or None))
