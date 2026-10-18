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
Home dashboard data assembly.

Replaces the ~340 lines of inline per-widget SQL that used to live directly
in app.py's /dashboard route. `g.db` is a single pooled connection shared for
the whole request — one failing query aborts the entire Postgres transaction,
so every later query on the same connection fails too until a rollback()
happens. This file centralizes that defensive pattern in one place (`_safe`)
instead of the 11+ hand-copied try/except/rollback blocks that caused two
real production bugs previously (a wrong column name in the merchant KYC
widget, another in the sanctions-freshness widget — both only surfaced as
cascading failures in unrelated, later widgets on the same request).
"""
import logging
from datetime import datetime, timedelta

from database.db import get_db
from utils.timezone_utils import now_cairo

logger = logging.getLogger(__name__)


def _safe(db, fn, default=None, label=""):
    """Run fn(db); on any error, roll back the shared connection so later
    widgets on this request aren't cascade-broken, and return `default`."""
    try:
        return fn(db)
    except Exception as e:
        logger.warning(f"Dashboard widget failed ({label}): {e}")
        db.rollback()
        return default


def get_dashboard_context(current_user, dashboard_service=None):
    """Assembles every value templates/index.html needs. Each widget is
    independently `_safe`-wrapped so one broken query degrades gracefully
    instead of 500-ing the whole page."""
    from models.coi import COICampaign, COIDeclaration
    from models.ghe import GHEDeclaration
    from models.cobec import COBECDeclaration
    from models.consumer_protection import ConsumerComplaint
    from whistleblowing.models import WhistleblowingCase
    from models.policy import Policy
    from models.risk import Risk, RiskScoringBand, KRI, KRIMeasurement, get_pending_risk_suggestions
    from models.internal_audit import AuditFinding, AuditProject

    db = get_db()
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    now_local = now_cairo()
    if 5 <= now_local.hour < 12:
        greeting = 'Good Morning'
    elif 12 <= now_local.hour < 17:
        greeting = 'Good Afternoon'
    else:
        greeting = 'Good Evening'
    ctx = {
        'today_str': today_str,
        'greeting': greeting,
        'dashboard_datetime': now_local,
    }

    # --- GHE ---
    row = _safe(db, lambda db: db.execute(
        "SELECT COUNT(*) as count FROM ghe_declarations WHERE employee_id = %s AND status = 'pending'",
        (current_user.id,)
    ).fetchone(), label="ghe own pending")
    pending_ghe_count = row['count'] if row else 0
    if current_user.is_compliance_officer() or current_user.is_admin():
        pending_ghe_count = _safe(db, lambda db: len(GHEDeclaration.get_pending_for_compliance()),
                                   default=0, label="ghe compliance queue")
    elif current_user.is_manager():
        pending_ghe_count = _safe(db, lambda db: len(GHEDeclaration.get_pending_for_manager(current_user.id)),
                                   default=0, label="ghe manager queue")
    ctx['pending_ghe_count'] = pending_ghe_count

    # --- COI ---
    active_annual = _safe(db, lambda db: COICampaign.get_active_annual(), label="coi active campaign")
    coi_pending = 0
    if active_annual:
        def _own_coi(db):
            decl = COIDeclaration.get_by_employee_campaign(current_user.id, active_annual.id)
            if not decl:
                return 1
            if decl.status == 'requires_clarification':
                return 1
            return 0
        coi_pending = _safe(db, _own_coi, default=0, label="coi own declaration")
    ctx['active_campaign'] = active_annual
    ctx['pending_coi_count'] = coi_pending

    coi_pending_reviews = 0
    if current_user.is_compliance_officer() or current_user.is_admin():
        coi_pending_reviews = _safe(db, lambda db: len(COIDeclaration.get_pending_for_compliance()),
                                     default=0, label="coi compliance queue")
    elif current_user.is_manager():
        coi_pending_reviews = _safe(db, lambda db: len(COIDeclaration.get_pending_for_manager(current_user.id)),
                                     default=0, label="coi manager queue")
    ctx['coi_pending_reviews'] = coi_pending_reviews

    # --- COBEC ---
    cobec_pending_count = 0
    if current_user.is_compliance_officer() or current_user.is_admin():
        row = _safe(db, lambda db: db.execute(
            "SELECT COUNT(*) as count FROM cobec_declarations WHERE status IN ('under_review', 'escalated', 'submitted')"
        ).fetchone(), label="cobec compliance queue")
        cobec_pending_count = row['count'] if row else 0
    elif current_user.is_manager():
        cobec_pending_count = _safe(db, lambda db: len(COBECDeclaration.get_pending_for_manager(current_user.id)),
                                     default=0, label="cobec manager queue")
    ctx['cobec_pending_count'] = cobec_pending_count

    # --- Policies ---
    policy_reviews_count = 0
    if current_user.is_compliance_officer() or current_user.is_admin():
        row = _safe(db, lambda db: db.execute(
            "SELECT COUNT(*) as count FROM policies WHERE NULLIF(next_review_date, '')::date "
            "<= (CURRENT_DATE + INTERVAL '30 days') AND status = 'published'"
        ).fetchone(), label="policy reviews due")
        policy_reviews_count = row['count'] if row else 0
    ctx['policy_reviews_count'] = policy_reviews_count

    acknowledged = _safe(db, lambda db: db.execute(
        "SELECT policy_id FROM policy_acknowledgments WHERE employee_id = %s", (current_user.id,)
    ).fetchall(), default=[], label="own policy acks")
    acknowledged_ids = [p['policy_id'] for p in acknowledged]
    if acknowledged_ids:
        placeholders = ','.join(['%s'] * len(acknowledged_ids))
        row = _safe(db, lambda db: db.execute(
            f"SELECT COUNT(*) as count FROM policies WHERE status = 'published' AND id NOT IN ({placeholders})",
            acknowledged_ids
        ).fetchone(), label="pending policies (with acks)")
    else:
        row = _safe(db, lambda db: db.execute(
            "SELECT COUNT(*) as count FROM policies WHERE status = 'published'"
        ).fetchone(), label="pending policies (no acks)")
    ctx['pending_policies_count'] = row['count'] if row else 0

    # --- Regulatory reports (next 30 days) ---
    thirty_days = (today + timedelta(days=30)).strftime('%Y-%m-%d')
    row = _safe(db, lambda db: db.execute(
        "SELECT COUNT(*) as count FROM regulatory_report_submissions "
        "WHERE due_date BETWEEN %s AND %s AND status IN ('pending', 'in_progress')",
        (today_str, thirty_days)
    ).fetchone(), label="upcoming regulatory reports")
    ctx['upcoming_reports_count'] = row['count'] if row else 0

    # --- Training (own) ---
    row = _safe(db, lambda db: db.execute(
        "SELECT COUNT(*) as count FROM training_enrollments "
        "WHERE employee_id = %s AND status IN ('enrolled', 'in_progress')",
        (current_user.id,)
    ).fetchone(), label="own training due")
    ctx['training_due_count'] = row['count'] if row else 0

    # --- Policy gap analysis ---
    gap_score = 0
    if current_user.is_compliance_officer() or current_user.is_admin():
        def _gap(db):
            gaps = Policy.get_gap_analysis()
            total = len(gaps)
            implemented = len([g for g in gaps if g['status'] == 'Implemented'])
            return int((implemented / total) * 100) if total else 0
        gap_score = _safe(db, _gap, default=0, label="policy gap analysis")
    ctx['gap_score'] = gap_score

    # --- Consumer protection / whistleblowing summaries ---
    ctx['cp_open_count'] = 0
    if current_user.can_view('consumer_protection'):
        stats = _safe(db, lambda db: ConsumerComplaint.get_stats(), default={'total_open': 0},
                       label="consumer protection stats")
        ctx['cp_open_count'] = stats.get('total_open', 0)

    ctx['wb_open_count'] = 0
    if current_user.can_view('whistleblowing'):
        stats = _safe(db, lambda db: WhistleblowingCase.get_statistics(), default={'open_cases': 0},
                       label="whistleblowing stats")
        ctx['wb_open_count'] = stats.get('open_cases', 0)

    # --- AML / TM ---
    ctx.update({'tm_open_alerts': 0, 'tm_high_alerts': 0, 'total_transactions': 0, 'high_risk_customers': 0})
    if current_user.can_view('aml'):
        def _aml(db):
            open_alerts = db.execute(
                "SELECT COUNT(*) as c FROM tm_alerts WHERE status IN ('NEW','ASSIGNED','INVESTIGATING')"
            ).fetchone()['c']
            high_alerts = db.execute(
                "SELECT COUNT(*) as c FROM tm_alerts WHERE status IN ('NEW','ASSIGNED','INVESTIGATING') "
                "AND alert_severity='HIGH'"
            ).fetchone()['c']
            total_tx = db.execute("SELECT COUNT(*) as c FROM transactions").fetchone()['c']
            high_risk = db.execute("SELECT COUNT(*) as c FROM customers WHERE risk_classification='HIGH'").fetchone()['c']
            return open_alerts, high_alerts, total_tx, high_risk
        result = _safe(db, _aml, default=(0, 0, 0, 0), label="AML stats")
        (ctx['tm_open_alerts'], ctx['tm_high_alerts'],
         ctx['total_transactions'], ctx['high_risk_customers']) = result

    # --- Screening ---
    ctx['screening_queue_count'] = 0
    if current_user.can_view('screening'):
        row = _safe(db, lambda db: db.execute(
            "SELECT COUNT(*) as c FROM screening_queue WHERE status='Pending'"
        ).fetchone(), label="screening queue")
        ctx['screening_queue_count'] = row['c'] if row else 0

    # --- Merchant KYC ---
    ctx['merchant_pending_count'] = 0
    if current_user.can_view('merchant_kyc'):
        row = _safe(db, lambda db: db.execute(
            "SELECT COUNT(*) as c FROM merchants WHERE kyc_status='SUBMITTED'"
        ).fetchone(), label="merchant KYC pending")
        ctx['merchant_pending_count'] = row['c'] if row else 0

    # --- Cyber (status casing corrected to UPPERCASE — live enum is NEW/CLOSED/etc,
    # the original lowercase comparison never matched anything) ---
    ctx['cyber_open_count'] = 0
    if current_user.can_view('cyber'):
        row = _safe(db, lambda db: db.execute(
            "SELECT COUNT(*) as c FROM cyber_incidents WHERE status NOT IN ('CLOSED','RESOLVED')"
        ).fetchone(), label="cyber open incidents")
        ctx['cyber_open_count'] = row['c'] if row else 0

    # --- Data breaches (same casing correction) ---
    ctx['breach_open_count'] = 0
    if current_user.can_view('pdpl'):
        row = _safe(db, lambda db: db.execute(
            "SELECT COUNT(*) as c FROM data_breaches WHERE status NOT IN ('CLOSED','RESOLVED')"
        ).fetchone(), label="data breaches open")
        ctx['breach_open_count'] = row['c'] if row else 0

    # --- Compliance health score ---
    def _health(db):
        pol = db.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN EXISTS("
            "SELECT 1 FROM policy_acknowledgments pa WHERE pa.policy_id=p.id) THEN 1 ELSE 0 END) as acked "
            "FROM policies p WHERE status='published'"
        ).fetchone()
        pol_score = int(pol['acked'] / max(pol['total'], 1) * 100) if pol and pol['total'] else 100
        tr = db.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as done "
            "FROM training_enrollments"
        ).fetchone()
        tr_score = int(tr['done'] / max(tr['total'], 1) * 100) if tr and tr['total'] else 100
        al = db.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) as closed FROM tm_alerts"
        ).fetchone()
        al_score = int(al['closed'] / max(al['total'], 1) * 100) if al and al['total'] else 100
        return int((pol_score + tr_score + al_score) / 3)
    ctx['compliance_health_score'] = _safe(db, _health, default=75, label="compliance health score")

    # --- Risk Management: heat map + top risks + suggestion count ---
    ctx.update({'risk_heat_map': {}, 'risk_bands': [], 'risk_top': [],
                'risk_suggestion_count': 0, 'risk_total_active': 0})
    if current_user.can_view('risk_management'):
        def _risk(db):
            risks = Risk.get_all(status='ACTIVE')
            bands = RiskScoringBand.get_all()
            heat_map = {}
            for r in risks:
                key = (r.likelihood, r.impact)
                heat_map[key] = heat_map.get(key, 0) + 1
            top = sorted(risks, key=lambda r: (r.residual_risk_score or r.inherent_risk_score or 0),
                          reverse=True)[:5]
            return heat_map, bands, top, len(risks)
        heat_map, bands, top, total = _safe(db, _risk, default=({}, [], [], 0), label="risk heat map")
        ctx['risk_heat_map'], ctx['risk_bands'], ctx['risk_top'], ctx['risk_total_active'] = heat_map, bands, top, total

        if current_user.can_edit('risk_management'):
            ctx['risk_suggestion_count'] = _safe(
                db, lambda db: len(get_pending_risk_suggestions()), default=0, label="risk suggestions")

    # --- KRIs ---
    ctx['kri_snapshot'] = []
    if current_user.can_view('risk_management'):
        def _kris(db):
            snapshot = []
            for k in KRI.get_all():
                history = KRIMeasurement.get_history(k.id, limit=1)
                snapshot.append({'kri': k, 'latest': history[0] if history else None})
            return snapshot
        ctx['kri_snapshot'] = _safe(db, _kris, default=[], label="KRI snapshot")

    # --- Internal Audit ---
    ctx.update({'ia_open_findings': 0, 'ia_overdue_findings': 0, 'ia_fieldwork_count': 0})
    if current_user.can_view('internal_audit'):
        def _ia(db):
            open_findings = [f for f in AuditFinding.get_all() if f.status in AuditFinding.OPEN_STATUSES]
            overdue = AuditFinding.get_overdue()
            fieldwork = AuditProject.get_all(status='FIELDWORK')
            return len(open_findings), len(overdue), len(fieldwork)
        result = _safe(db, _ia, default=(0, 0, 0), label="internal audit stats")
        ctx['ia_open_findings'], ctx['ia_overdue_findings'], ctx['ia_fieldwork_count'] = result

    # --- Screening service stats (external Redis-backed service, not part of the DB transaction) ---
    ctx['screening_stats'] = dashboard_service.get_stats() if dashboard_service else {}

    # --- ESG Management (overall score for the current open period) ---
    ctx['esg_overall_score'] = None
    if current_user.can_view('esg'):
        def _esg(db):
            fw = db.execute(
                "SELECT id FROM esg_frameworks WHERE is_default = TRUE AND is_active = TRUE LIMIT 1"
            ).fetchone()
            period = db.execute(
                "SELECT id FROM esg_reporting_periods WHERE status = 'open' ORDER BY start_date DESC LIMIT 1"
            ).fetchone()
            if not fw or not period:
                return None
            rows = db.execute(
                "SELECT p.weight AS pillar_weight, i.weight AS ind_weight, r.score AS score "
                "FROM esg_pillars p JOIN esg_indicators i ON i.pillar_id = p.id "
                "LEFT JOIN esg_indicator_responses r "
                "  ON r.indicator_id = i.id AND r.reporting_period_id = %s "
                "WHERE p.framework_id = %s",
                (period['id'], fw['id'])
            ).fetchall()
            from collections import defaultdict
            pillar_num, pillar_den, pillar_weight = defaultdict(float), defaultdict(float), {}
            for r in rows:
                pillar_weight[r['pillar_weight']] = r['pillar_weight']
                if r['score'] is not None:
                    pillar_num[r['pillar_weight']] += r['ind_weight'] * r['score']
                    pillar_den[r['pillar_weight']] += r['ind_weight']
            overall_num, overall_den = 0.0, 0.0
            for pw, den in pillar_den.items():
                if den > 0:
                    pillar_score = pillar_num[pw] / den
                    overall_num += pw * pillar_score
                    overall_den += pw
            return round(overall_num / overall_den, 2) if overall_den > 0 else None
        ctx['esg_overall_score'] = _safe(db, _esg, default=None, label="ESG overall score")

    # --- Carbon Footprint (current open period total, location-based) ---
    ctx['carbon_total_tco2e'] = None
    if current_user.can_view('carbon'):
        def _carbon(db):
            period = db.execute(
                "SELECT id FROM esg_reporting_periods WHERE status = 'open' ORDER BY start_date DESC LIMIT 1"
            ).fetchone()
            if not period:
                return None
            row = db.execute(
                "SELECT COALESCE(SUM(tco2e), 0) AS total FROM carbon_activity_entries "
                "WHERE reporting_period_id = %s AND (basis IS NULL OR basis != 'market')",
                (period['id'],)
            ).fetchone()
            return round(row['total'], 2) if row else None
        ctx['carbon_total_tco2e'] = _safe(db, _carbon, default=None, label="carbon total tCO2e")

    return ctx


_SEVERITY_RANK = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}


def get_my_pending_items(user):
    """Cross-module 'My Tasks Today' aggregator: items directly assigned to
    this user by ID, plus role-scoped approval queues (manager/compliance-
    officer) that only someone in that role can act on — both are things
    only this user can act on today. Returns a list of
    {module, title, link, due_date, severity} dicts, sorted overdue-first,
    then by severity, then by date."""
    from models.risk import RiskTreatment
    from models.internal_audit import AuditFinding
    from models.ghe import GHEDeclaration
    from models.coi import COIDeclaration
    from whistleblowing.models import WhistleblowingCase

    db = get_db()
    items = []

    def _add(module, title, link, due_date=None, severity=None):
        items.append({'module': module, 'title': title, 'link': link,
                      'due_date': due_date, 'severity': severity})

    def _treatments(db):
        for t in RiskTreatment.get_for_owner(user.id):
            _add('Risk Management', (t.treatment_description or 'Treatment')[:80],
                 f'/risk-management/treatments/{t.id}', t.target_date)
    _safe(db, _treatments, label="my risk treatments")

    def _findings(db):
        rows = db.execute(
            "SELECT * FROM audit_findings WHERE responsible_person_id = %s AND status IN %s",
            (user.id, AuditFinding.OPEN_STATUSES)
        ).fetchall()
        for f in rows:
            _add('Internal Audit', f['finding_title'], f"/internal-audit/findings/{f['id']}",
                 f['target_date'], f['severity'])
    _safe(db, _findings, label="my audit findings")

    def _screening(db):
        rows = db.execute(
            "SELECT * FROM screening_queue WHERE assigned_to = %s AND status != 'Resolved'", (user.id,)
        ).fetchall()
        for r in rows:
            _add('Screening', r.get('entity_name') or f"Queue item #{r['id']}",
                 '/screening/queue', severity=r.get('priority'))
    _safe(db, _screening, label="my screening queue")

    def _aml_alerts(db):
        rows = db.execute(
            "SELECT * FROM tm_alerts WHERE assigned_to = %s AND status NOT IN ('CLOSED','FALSE_POSITIVE')",
            (user.id,)
        ).fetchall()
        for r in rows:
            _add('AML', r.get('alert_reference') or f"Alert #{r['id']}", '/aml/alerts',
                 severity=r.get('alert_severity'))
    _safe(db, _aml_alerts, label="my AML alerts")

    def _sars(db):
        rows = db.execute(
            "SELECT * FROM suspicious_activities WHERE assigned_to = %s "
            "AND UPPER(COALESCE(investigation_status,'')) NOT IN ('CLOSED','COMPLETED')",
            (user.id,)
        ).fetchall()
        for r in rows:
            _add('AML', r.get('sar_reference') or f"SAR #{r['id']}", '/aml/sars')
    _safe(db, _sars, label="my SARs")

    def _wb(db):
        cases = WhistleblowingCase.get_all_cases(filters={'assigned_to': user.id})
        for c in cases:
            if c.get('status') not in ('RESOLVED', 'DISMISSED'):
                _add('Whistleblowing', c.get('title') or c.get('case_number'),
                     f"/whistleblowing/case/{c['id']}", severity=c.get('severity'))
    _safe(db, _wb, label="my whistleblowing cases")

    def _training(db):
        rows = db.execute(
            "SELECT * FROM training_enrollments WHERE employee_id = %s "
            "AND status != 'completed' AND NULLIF(due_date, '')::date < CURRENT_DATE",
            (user.id,)
        ).fetchall()
        for r in rows:
            _add('Training', r.get('course_name') or 'Training course',
                 '/training/courses', r.get('due_date'))
    _safe(db, _training, label="my overdue training")

    def _ghe(db):
        if user.is_manager():
            for d in GHEDeclaration.get_pending_for_manager(user.id):
                _add('GHE', 'Declaration pending your review', f'/ghe/{d.id}')
        elif user.is_compliance_officer():
            for d in GHEDeclaration.get_pending_for_compliance():
                _add('GHE', 'Declaration pending compliance review', f'/ghe/{d.id}')
    _safe(db, _ghe, label="GHE queue")

    def _coi(db):
        if user.is_manager():
            for d in COIDeclaration.get_pending_for_manager(user.id):
                _add('COI', 'Declaration pending your review', f'/coi/declarations/{d.id}/review')
        elif user.is_compliance_officer():
            for d in COIDeclaration.get_pending_for_compliance():
                _add('COI', 'Declaration pending compliance review', f'/coi/declarations/{d.id}/review')
    _safe(db, _coi, label="COI queue")

    def _merchant(db):
        if user.can_edit('merchant_kyc'):
            rows = db.execute("SELECT * FROM merchants WHERE kyc_status='SUBMITTED'").fetchall()
            for m in rows:
                _add('Merchant KYC', m.get('merchant_name') or f"Merchant #{m['id']}", '/merchant-kyc/')
    _safe(db, _merchant, label="merchant KYC queue")

    def _sort_key(item):
        due = item['due_date']
        is_overdue = 0 if (due and str(due) < datetime.now().strftime('%Y-%m-%d')) else 1
        sev = _SEVERITY_RANK.get((item['severity'] or '').upper(), 4)
        date_key = str(due) if due else '9999-99-99'
        return (is_overdue, sev, date_key)

    items.sort(key=_sort_key)
    return items
