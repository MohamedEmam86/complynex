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
Database layer for AML & KYC assurance. Decisions live in logic.py; every
regulatory cycle or threshold is read through regcontrols parameters.
"""

import json
from datetime import date, datetime, timedelta

from database.db import get_db

from . import logic, subjects


def N_(s):
    """Mark a message for translation (shown translated by the page)."""
    return s


class AssuranceError(ValueError):
    pass


def _rows(db, sql, args=()):
    try:
        return [dict(r) for r in db.execute(sql, args).fetchall()]
    except Exception:
        db.rollback()
        raise


def param(key, default=None):
    from regcontrols.api import get_param
    from regcontrols.engine import company_licence_type
    return get_param(key, company_licence_type(), default=default)


# ------------------------------------------------------------------ key roles
def key_roles(db=None, active_only=True):
    db = db or get_db()
    return _rows(db, f"""SELECT r.*, h.first_name || ' ' || h.last_name AS holder_user_name,
                               h.job_title AS holder_job_title,
                               m.first_name || ' ' || m.last_name AS reports_to_user_name, m.job_title AS reports_to_job_title
                        FROM aml_key_roles r LEFT JOIN users h ON h.id = r.holder_user_id
                        LEFT JOIN users m ON m.id = r.reports_to_user_id
                        {'WHERE r.is_active' if active_only else ''} ORDER BY r.role_code, r.id""")


def effective_role(r):
    """Fill reporting line / positions from the user records when the register
    leaves them empty (the org structure is the source)."""
    r = dict(r)
    if not r.get('reports_to_title'):
        r['reports_to_title'] = r.get('reports_to_job_title') or ''
    return r


def conflict_rules(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM aml_role_conflict_rules ORDER BY role_code, rule_type, keyword")


def save_key_role(data, user_id, role_id=None, db=None):
    db = db or get_db()
    if not (data.get('role_code') or '').strip():
        raise AssuranceError(N_('role code is required'))
    cols = ['role_code', 'title', 'holder_user_id', 'holder_name', 'reports_to_title', 'reports_to_user_id',
            'reports_to_board', 'other_positions', 'combined_role_approval_ref', 'combined_role_approved_on',
            'appointed_on', 'regulator_notified_on', 'regulator_ref', 'notes', 'is_active']
    vals = [data.get(c) if data.get(c) not in ('',) else None for c in cols]
    vals[cols.index('role_code')] = data['role_code'].strip().lower()
    vals[cols.index('reports_to_board')] = bool(data.get('reports_to_board'))
    vals[cols.index('is_active')] = bool(data.get('is_active', True))
    if role_id:
        db.execute(f"UPDATE aml_key_roles SET {', '.join(f'{c} = %s' for c in cols)}, updated_by = %s, updated_at = %s "
                   f"WHERE id = %s", (*vals, user_id, datetime.now(), role_id))
    else:
        role_id = db.execute(f"INSERT INTO aml_key_roles ({', '.join(cols)}, updated_by) VALUES "
                             f"({', '.join(['%s'] * len(cols))}, %s) RETURNING id", (*vals, user_id)).fetchone()['id']
    db.commit()
    return role_id


def save_conflict_rule(role_code, rule_type, keyword, reason_en=None, reason_ar=None, db=None):
    db = db or get_db()
    if rule_type not in ('holds', 'reports_to') or not (keyword or '').strip() or not (role_code or '').strip():
        raise AssuranceError(N_('role, rule type and keyword are required'))
    db.execute("""INSERT INTO aml_role_conflict_rules (role_code, rule_type, keyword, reason_en, reason_ar)
                  VALUES (%s,%s,%s,%s,%s) ON CONFLICT (role_code, rule_type, keyword)
                  DO UPDATE SET reason_en = EXCLUDED.reason_en, reason_ar = EXCLUDED.reason_ar, is_active = TRUE""",
               (role_code.strip().lower(), rule_type, keyword.strip().lower(), reason_en, reason_ar))
    db.commit()


# ------------------------------------------------------------------ annual report
def build_annual_report(year, db=None):
    """Collect the year's AML figures from the system (best effort per source)."""
    db = db or get_db()
    start, end = date(year, 1, 1), date(year, 12, 31)

    def q(sql, args=()):
        try:
            r = db.execute(sql, args).fetchone()
            return dict(r) if r else {}
        except Exception:
            db.rollback()
            return {}
    data = {
        'period': [str(start), str(end)],
        'screening': q("SELECT count(*) AS screenings FROM screening_history WHERE created_at BETWEEN %s AND %s",
                       (start, end + timedelta(days=1))),
        'tm_alerts': q("SELECT count(*) AS alerts, count(*) FILTER (WHERE status IN ('CLOSED', 'FALSE_POSITIVE')) AS closed "
                       "FROM tm_alerts WHERE CAST(alert_date AS TEXT) BETWEEN %s AND %s", (str(start), str(end) + ' 23:59')),
        'unusual_transactions': q("""SELECT count(*) AS registered, count(*) FILTER (WHERE decision = 'str') AS strs,
                                     count(*) FILTER (WHERE decision = 'no_str') AS no_strs,
                                     count(*) FILTER (WHERE status IN ('candidate', 'under_study')) AS open
                                     FROM aml_unusual_transactions WHERE detected_at BETWEEN %s AND %s""",
                                  (start, end + timedelta(days=1))),
        'risk_distribution': {r['band']: r['n'] for r in _safe_rows(db, """SELECT band, count(*) AS n FROM kyc_risk_ratings
                              WHERE is_current GROUP BY band""")},
        'monitoring_reviews': q("""SELECT count(*) AS planned, count(*) FILTER (WHERE status = 'done') AS done
                                   FROM aml_monitoring_reviews r JOIN aml_monitoring_plans p ON p.id = r.plan_id
                                   WHERE p.plan_year = %s""", (year,)),
        'employee_screenings': q("SELECT count(DISTINCT user_id) AS employees FROM employee_screenings "
                                 "WHERE screened_at BETWEEN %s AND %s", (start, end + timedelta(days=1))),
        'findings': q("""SELECT count(*) FILTER (WHERE status <> 'closed') AS open, count(*) FILTER (WHERE is_repeated) AS repeated
                         FROM rc_findings f WHERE f.area = 'aml_cft' OR EXISTS (SELECT 1 FROM rc_finding_controls fc
                         JOIN rc_controls c ON c.id = fc.control_id WHERE fc.finding_id = f.id AND c.area = 'aml_cft')"""),
    }
    return data


def _safe_rows(db, sql, args=()):
    try:
        return [dict(r) for r in db.execute(sql, args).fetchall()]
    except Exception:
        db.rollback()
        return []


def generate_annual_report(year, user_id, role_code='mlro', db=None):
    db = db or get_db()
    data = build_annual_report(year, db)
    existing = db.execute("SELECT id, status FROM aml_annual_reports WHERE report_year = %s AND role_code = %s",
                          (year, role_code)).fetchone()
    if existing and existing['status'] == 'approved':
        raise AssuranceError(N_('this report is already board-approved; it cannot be regenerated'))
    if existing:
        db.execute("UPDATE aml_annual_reports SET data = %s, generated_at = %s, generated_by = %s WHERE id = %s",
                   (json.dumps(data, default=str), datetime.now(), user_id, existing['id']))
        rid = existing['id']
    else:
        rid = db.execute("""INSERT INTO aml_annual_reports (report_year, role_code, data, generated_at, generated_by)
                            VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                         (year, role_code, json.dumps(data, default=str), datetime.now(), user_id)).fetchone()['id']
    db.commit()
    return rid


def annual_report_action(report_id, action, user_id, narrative=None, meeting_ref=None, approved_on=None, db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM aml_annual_reports WHERE id = %s", (report_id,)).fetchone()
    if not r:
        raise AssuranceError(N_('report not found'))
    if action == 'narrative':
        if r['status'] == 'approved':
            raise AssuranceError(N_('an approved report cannot be changed'))
        db.execute("UPDATE aml_annual_reports SET narrative = %s WHERE id = %s", (narrative, report_id))
    elif action == 'submit':
        if r['status'] != 'draft':
            raise AssuranceError(N_('only a draft can be submitted to the board'))
        db.execute("UPDATE aml_annual_reports SET status = 'submitted', submitted_at = %s WHERE id = %s",
                   (datetime.now(), report_id))
    elif action == 'approve':
        if r['status'] != 'submitted':
            raise AssuranceError(N_('submit the report to the board first'))
        if not approved_on or not (meeting_ref or '').strip():
            raise AssuranceError(N_('board meeting reference and approval date are required'))
        db.execute("""UPDATE aml_annual_reports SET status = 'approved', board_approved_on = %s, board_meeting_ref = %s,
                      approval_recorded_by = %s WHERE id = %s""", (approved_on, meeting_ref.strip(), user_id, report_id))
    else:
        raise AssuranceError(N_('unknown action'))
    db.commit()


# ------------------------------------------------------------------ policies needing board approval
def board_policies(db=None):
    db = db or get_db()
    return _safe_rows(db, """
        SELECT p.id, p.policy_number, p.policy_name, p.version, p.status, p.created_at, p.updated_at,
               p.requires_board_approval,
               (SELECT max(a.approved_on) FROM policy_board_approvals a WHERE a.policy_id = p.id
                  AND (a.policy_version IS NULL OR a.policy_version = p.version)) AS board_approved_on
        FROM policies p ORDER BY p.requires_board_approval DESC, p.policy_name""")


def set_board_required(policy_id, required, db=None):
    db = db or get_db()
    db.execute("UPDATE policies SET requires_board_approval = %s WHERE id = %s", (bool(required), policy_id))
    db.commit()


def record_board_approval(policy_id, approved_on, board_ref, user_id, notes=None, db=None):
    db = db or get_db()
    p = db.execute("SELECT version FROM policies WHERE id = %s", (policy_id,)).fetchone()
    if not p:
        raise AssuranceError(N_('policy not found'))
    if not approved_on or not (board_ref or '').strip():
        raise AssuranceError(N_('board meeting reference and approval date are required'))
    db.execute("""INSERT INTO policy_board_approvals (policy_id, policy_version, approved_on, board_ref, notes, recorded_by)
                  VALUES (%s,%s,%s,%s,%s,%s)""", (policy_id, p['version'], approved_on, board_ref.strip(), notes, user_id))
    db.commit()


# ------------------------------------------------------------------ monitoring programme
DEFAULT_CHECKLIST = [
    'KYC files complete for a sample of new clients',
    'Risk ratings present and current for the sample',
    'Unusual transactions escalated to the AML function',
    'Staff AML training up to date',
    'Screening performed before onboarding',
    'Records kept and retrievable',
]


def plans(db=None):
    db = db or get_db()
    return _rows(db, """SELECT p.*, (SELECT count(*) FROM aml_monitoring_reviews r WHERE r.plan_id = p.id) AS reviews,
                               (SELECT count(*) FROM aml_monitoring_reviews r WHERE r.plan_id = p.id AND r.status = 'done') AS done
                        FROM aml_monitoring_plans p ORDER BY p.plan_year DESC""")


def reviews(plan_id, db=None):
    db = db or get_db()
    return _rows(db, """SELECT r.*, u.first_name || ' ' || u.last_name AS reviewer_name, f.reference AS finding_ref
                        FROM aml_monitoring_reviews r LEFT JOIN users u ON u.id = r.reviewer_id
                        LEFT JOIN rc_findings f ON f.id = r.finding_id WHERE r.plan_id = %s
                        ORDER BY r.planned_date, r.id""", (plan_id,))


def save_plan(year, title, approved_on, user_id, db=None):
    db = db or get_db()
    db.execute("""INSERT INTO aml_monitoring_plans (plan_year, title, approved_on, created_by) VALUES (%s,%s,%s,%s)
                  ON CONFLICT (plan_year) DO UPDATE SET title = EXCLUDED.title, approved_on = EXCLUDED.approved_on""",
               (year, title, approved_on, user_id))
    db.commit()
    return db.execute("SELECT id FROM aml_monitoring_plans WHERE plan_year = %s", (year,)).fetchone()['id']


def add_review(plan_id, unit_label, review_type, planned_date, reviewer_id=None, org_unit_id=None, db=None):
    db = db or get_db()
    if not (unit_label or '').strip() or not planned_date:
        raise AssuranceError(N_('unit and planned date are required'))
    db.execute("""INSERT INTO aml_monitoring_reviews (plan_id, unit_label, review_type, planned_date, reviewer_id,
                  org_unit_id, checklist) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
               (plan_id, unit_label.strip(), review_type if review_type in ('offsite', 'onsite') else 'offsite',
                planned_date, reviewer_id, org_unit_id,
                json.dumps([{'item': i, 'result': None, 'note': ''} for i in DEFAULT_CHECKLIST])))
    db.commit()


def complete_review(review_id, results, conclusion, user_id, performed_date=None, db=None):
    """results: list of (result, note) in checklist order. Issues open a finding."""
    db = db or get_db()
    r = db.execute("SELECT * FROM aml_monitoring_reviews WHERE id = %s", (review_id,)).fetchone()
    if not r:
        raise AssuranceError(N_('review not found'))
    checklist = r['checklist'] or []
    for i, item in enumerate(checklist):
        if i < len(results):
            item['result'], item['note'] = results[i]
    if any(item.get('result') not in ('ok', 'issue', 'na') for item in checklist):
        raise AssuranceError(N_('answer every checklist item (ok / issue / n.a.)'))
    issues = [item for item in checklist if item['result'] == 'issue']
    finding_id = r['finding_id']
    if issues and not finding_id:
        from regcontrols.api import raise_finding
        finding_id = raise_finding(
            f"AML monitoring review: {r['unit_label']} — {len(issues)} issue(s)", source='self_identified',
            source_ref=f'AMLMON-{review_id}', severity='medium', area='aml_cft',
            description='\n'.join(f"- {i['item']}: {i.get('note') or ''}" for i in issues) + (
                f"\n\n{conclusion}" if conclusion else ''), created_by=user_id, db=db)
    db.execute("""UPDATE aml_monitoring_reviews SET checklist = %s, conclusion = %s, status = 'done',
                  performed_date = %s, reviewer_id = COALESCE(reviewer_id, %s), finding_id = %s WHERE id = %s""",
               (json.dumps(checklist), conclusion, performed_date or date.today(), user_id, finding_id, review_id))
    db.commit()
    return finding_id


# ------------------------------------------------------------------ screening assurance
def screening_sources(db=None):
    db = db or get_db()
    for sql in ("SELECT id, name, type, is_active, last_successful_update FROM screening_data_sources ORDER BY name",
                "SELECT id, source_name AS name, NULL AS type, is_active, last_successful_update "
                "FROM screening_data_sources ORDER BY source_name"):
        try:
            return [dict(r) for r in db.execute(sql).fetchall()]
        except Exception:
            db.rollback()
    return []


def source_status(sources, required, max_age_hours=None, now=None):
    """required: [{'label': 'UN Security Council', 'match': ['un ', 'security council']}].
    Returns rows: label, matched source names, ok flags (configured, loaded, fresh)."""
    now = now or datetime.now()
    out = []
    for req in required:
        pats = [p.lower() for p in (req.get('match') or [req.get('label', '')]) if p]
        hits = [s for s in sources if any(p in (s.get('name') or '').lower() for p in pats)]
        active = [s for s in hits if s.get('is_active') not in (False, 0)]
        loaded = [s for s in active if s.get('last_successful_update')]
        fresh = loaded
        if max_age_hours is not None:
            fresh = [s for s in loaded if now - _dt(s['last_successful_update']) <= timedelta(hours=float(max_age_hours))]
        out.append({'label': req.get('label'), 'sources': [s['name'] for s in hits], 'configured': bool(active),
                    'loaded': bool(loaded), 'fresh': bool(fresh),
                    'last_update': max((str(s['last_successful_update']) for s in loaded), default=None)})
    return out


def _dt(v):
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    return datetime.fromisoformat(str(v)[:19])


def qa_cases(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM screening_qa_cases ORDER BY expect_match DESC, expected_name, query_name")


def add_qa_case(query_name, expected_name, variant_type, expect_match, list_label, user_id, db=None):
    db = db or get_db()
    if not (query_name or '').strip():
        raise AssuranceError(N_('query name is required'))
    db.execute("""INSERT INTO screening_qa_cases (query_name, expected_name, variant_type, expect_match, list_label, created_by)
                  VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (query_name, expected_name) DO NOTHING""",
               (query_name.strip(), (expected_name or '').strip() or None, variant_type or 'exact', bool(expect_match),
                list_label or None, user_id))
    db.commit()


def add_cases_from_entry(name, list_label, user_id, db=None):
    """A real watchlist name picked by the user: exact + generated variants."""
    add_qa_case(name, name, 'exact', True, list_label, user_id, db)
    n = 1
    for vt, v in logic.name_variants(name):
        add_qa_case(v, name, vt, True, list_label, user_id, db)
        n += 1
    return n


def add_synthetic_negatives(user_id, n=10, db=None):
    for name in logic.synthetic_negatives(n):
        add_qa_case(name, None, 'synthetic_negative', False, None, user_id, db)


def _default_screen(name, entity_type):
    from screening.routes import get_engine
    res = get_engine().screen_person(name=name, entity_type=entity_type)
    return res.get('matches') or []


def run_qa(user_id=None, screen_fn=None, threshold=None, db=None):
    """Screen every active QA case without saving to screening history.
    Returns the screening_qa_runs row."""
    db = db or get_db()
    screen_fn = screen_fn or _default_screen
    if threshold is None:
        try:
            from screening.customer_screening_service import HIGH_RISK_THRESHOLD as threshold
        except Exception:
            threshold = 0.85
    results, error = [], None
    cases = [c for c in qa_cases(db) if c['is_active']]
    for c in cases:
        try:
            matches = [m for m in screen_fn(c['query_name'], c['entity_type']) if float(m.get('match_score') or 0) >= threshold]
        except Exception as e:
            error = f'{type(e).__name__}: {e}'[:500]
            break
        names = [m.get('name') or m.get('matched_name') or m.get('entity_name') or '' for m in matches]
        if c['expect_match']:
            found = any(logic.same_name(n, c['expected_name'] or c['query_name']) for n in names) or \
                any(logic.same_name(a, c['expected_name'] or '') for m in matches for a in (m.get('aliases') or [])
                    if isinstance(a, str))
        else:
            found = bool(matches)
        results.append({'case_id': c['id'], 'query': c['query_name'], 'expected': c['expected_name'],
                        'variant': c['variant_type'], 'expect_match': c['expect_match'], 'found': found,
                        'top': names[:3]})
    m = logic.qa_metrics(results)
    rid = db.execute("""INSERT INTO screening_qa_runs (run_by, cases, positives, hits, misses, false_positives,
                        recall_pct, precision_pct, details, error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (user_id, m['cases'], m['positives'], m['hits'], m['misses'], m['false_positives'],
                      m['recall_pct'], m['precision_pct'], json.dumps(results, default=str), error)).fetchone()['id']
    db.commit()
    return dict(db.execute("SELECT * FROM screening_qa_runs WHERE id = %s", (rid,)).fetchone())


def last_qa_run(db=None):
    db = db or get_db()
    r = _safe_rows(db, "SELECT * FROM screening_qa_runs ORDER BY run_at DESC, id DESC LIMIT 1")
    return r[0] if r else None


# ------------------------------------------------------------------ employee screening
def employees_due(months, db=None, today=None):
    """Active users never screened, or not screened within `months`."""
    db = db or get_db()
    today = today or date.today()
    cutoff = today - timedelta(days=int(round(float(months) * 30.4))) if months else None
    rows_ = _rows(db, """SELECT u.id, u.first_name, u.last_name, u.job_title, u.created_at,
                                (SELECT max(screened_at) FROM employee_screenings s WHERE s.user_id = u.id) AS last_screened,
                                (SELECT s.high_risk_matches FROM employee_screenings s WHERE s.user_id = u.id
                                   ORDER BY s.screened_at DESC LIMIT 1) AS last_hits
                         FROM users u WHERE u.is_active = 1 ORDER BY u.first_name, u.last_name""")
    for r in rows_:
        r['due'] = r['last_screened'] is None or (cutoff is not None and r['last_screened'].date() < cutoff)
    return rows_


def screen_employee(user_id_to_screen, actor_id, trigger='manual', db=None, screen_fn=None):
    db = db or get_db()
    u = db.execute("SELECT id, first_name, last_name FROM users WHERE id = %s", (user_id_to_screen,)).fetchone()
    if not u:
        raise AssuranceError(N_('user not found'))
    name = f"{u['first_name']} {u['last_name']}".strip()
    if screen_fn:
        res = screen_fn(name)
    else:
        from screening.customer_screening_service import screen_and_save
        res = screen_and_save(name=name, entity_type='INDIVIDUAL', source_module='Employee Screening',
                              source_record_id=u['id'], screening_type='Employee', user_id=actor_id)
    db.execute("""INSERT INTO employee_screenings (user_id, trigger, history_id, status, high_risk_matches, screened_by)
                  VALUES (%s,%s,%s,%s,%s,%s)""",
               (u['id'], trigger if trigger in ('hiring', 'periodic', 'manual') else 'manual', res.get('history_id'),
                res.get('status'), int(res.get('high_risk_matches') or 0), actor_id))
    db.commit()
    return res


# ------------------------------------------------------------------ unusual transactions
def unusual_list(status=None, db=None):
    db = db or get_db()
    clause, args = ('WHERE u.status = %s', (status,)) if status else ('', ())
    return _rows(db, f"""SELECT u.*, d.first_name || ' ' || d.last_name AS decision_by_name
                        FROM aml_unusual_transactions u LEFT JOIN users d ON d.id = u.decision_by {clause}
                        ORDER BY (u.status IN ('candidate', 'under_study')) DESC, u.study_due_date NULLS LAST,
                                 u.detected_at DESC LIMIT 1000""", args)


def unusual_study(item_id, user_id, analysis, decision=None, str_reference=None, db=None):
    """Record the study; a decision (str / no_str) closes it. STR needs a reference;
    both need a written analysis and at least one document."""
    db = db or get_db()
    from attachments.service import list_attachments
    u = db.execute("SELECT * FROM aml_unusual_transactions WHERE id = %s", (item_id,)).fetchone()
    if not u:
        raise AssuranceError(N_('item not found'))
    if u['status'] in ('str_filed', 'no_str', 'dismissed'):
        raise AssuranceError(N_('this item is already decided'))
    if not (analysis or '').strip():
        raise AssuranceError(N_('write the analysis first'))
    if decision:
        if decision not in ('str', 'no_str'):
            raise AssuranceError(N_('decision must be STR or no STR'))
        if decision == 'str' and not (str_reference or '').strip():
            raise AssuranceError(N_('enter the STR reference'))
        if not list_attachments('aml', 'aml_unusual', item_id):
            raise AssuranceError(N_('attach the supporting documents before deciding'))
        status = 'str_filed' if decision == 'str' else 'no_str'
        db.execute("""UPDATE aml_unusual_transactions SET analysis = %s, decision = %s, decision_by = %s, decision_at = %s,
                      str_reference = %s, status = %s WHERE id = %s""",
                   (analysis.strip(), decision, user_id, datetime.now(), (str_reference or '').strip() or None, status,
                    item_id))
    else:
        db.execute("UPDATE aml_unusual_transactions SET analysis = %s, status = 'under_study' WHERE id = %s",
                   (analysis.strip(), item_id))
    db.commit()
    _sync_case(item_id)


def _sync_case(item_id):
    try:
        from models.case import Case
        Case.sync_from_source('UNUSUAL_TXN', item_id)
    except Exception:
        get_db().rollback()


# Modules / packs register functions that list what SHOULD be in the register
# (reconciliation): fn(db) -> [(source_table, source_record_id, label)].
EXPECTED_SOURCES = {}


def register_expected_source(name, fn):
    EXPECTED_SOURCES[name] = fn
    return fn


def reconcile_register(db=None):
    db = db or get_db()
    have = {(r['source_table'], r['source_record_id']) for r in _safe_rows(
        db, "SELECT source_table, source_record_id FROM aml_unusual_transactions")}
    missing = []
    for name, fn in EXPECTED_SOURCES.items():
        try:
            for table, rid, label in fn(db) or []:
                if (table, rid) not in have:
                    missing.append({'source': name, 'table': table, 'id': rid, 'label': label})
        except Exception:
            db.rollback()
    return missing


def route_audit_red_flags(db=None):
    """Internal-audit findings tagged as AML red flags → unusual-transactions register (+ case)."""
    db = db or get_db()
    from aml.unusual import register_candidate
    n = 0
    sla = param('aml.unusual_txn_study_sla_days')
    for f in _safe_rows(db, """SELECT af.* FROM audit_findings af WHERE af.aml_red_flag
                               AND NOT EXISTS (SELECT 1 FROM aml_unusual_transactions u
                                               WHERE u.source_table = 'audit_findings' AND u.source_record_id = af.id)"""):
        uid, created = register_candidate(
            source_module='internal_audit', detection_rule='audit_red_flag', source_table='audit_findings',
            source_record_id=f['id'], subject_name=f.get('finding_title'), subject_ref=f.get('finding_number'),
            description=(f.get('finding_description') or '')[:2000], study_sla_days=sla, db=db)
        if created:
            _sync_case(uid)
            n += 1
    return n


# ------------------------------------------------------------------ KYC
def fields(subject, db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM kyc_fields WHERE subject = %s ORDER BY sort_order, field_key", (subject,))


def profile(subject, subject_id, db=None):
    db = db or get_db()
    return {r['field_key']: r['value'] for r in _rows(
        db, "SELECT field_key, value FROM kyc_profile_values WHERE subject = %s AND subject_id = %s",
        (subject, subject_id))}


def profiles(subject, db=None):
    db = db or get_db()
    out = {}
    for r in _rows(db, "SELECT subject_id, field_key, value FROM kyc_profile_values WHERE subject = %s", (subject,)):
        out.setdefault(r['subject_id'], {})[r['field_key']] = r['value']
    return out


def save_profile(subject, subject_id, values, user_id, db=None):
    db = db or get_db()
    for k, v in values.items():
        db.execute("""INSERT INTO kyc_profile_values (subject, subject_id, field_key, value, updated_by, updated_at)
                      VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (subject, subject_id, field_key)
                      DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at""",
                   (subject, subject_id, k, (v or '').strip() or None, user_id, datetime.now()))
    db.commit()


def file_status(subject, record, prof, flds, db=None, only=None):
    s = subjects.SUBJECTS[subject]
    kind = s.kind(record)
    c = logic.completeness(record, kind, flds, prof, only)
    return dict(c, kind=kind)


def portfolio(subject, db=None):
    """Every subject with completeness, current rating and onboarding state."""
    db = db or get_db()
    s = subjects.SUBJECTS[subject]
    flds = fields(subject, db)
    profs = profiles(subject, db)
    ratings = {r['subject_id']: r for r in _safe_rows(
        db, "SELECT * FROM kyc_risk_ratings WHERE subject = %s AND is_current", (subject,))}
    onb = {r['subject_id']: r for r in _safe_rows(db, "SELECT * FROM kyc_onboarding WHERE subject = %s", (subject,))}
    decl = {r['subject_id'] for r in _safe_rows(db, "SELECT DISTINCT subject_id FROM kyc_bo_declarations WHERE subject = %s",
                                                (subject,))}
    bos = {r['subject_id']: r['n'] for r in _safe_rows(
        db, "SELECT subject_id, count(*) AS n FROM kyc_beneficial_owners WHERE subject = %s GROUP BY subject_id", (subject,))}
    out = []
    for r in subjects.rows(subject, db):
        st = file_status(subject, r, profs.get(r['id'], {}), flds)
        out.append({'id': r['id'], 'name': s.name(r), 'kind': st['kind'], 'active': s.active(r), 'score': st['score'],
                    'missing': st['missing'], 'rating': ratings.get(r['id']), 'onboarding': onb.get(r['id']),
                    'declaration': r['id'] in decl, 'bo_count': bos.get(r['id'], 0)})
    return out


def add_bo(subject, subject_id, data, user_id, db=None):
    db = db or get_db()
    if not (data.get('full_name') or '').strip():
        raise AssuranceError(N_('beneficial owner name is required'))
    db.execute("""INSERT INTO kyc_beneficial_owners (subject, subject_id, full_name, nationality, ownership_pct, control_type,
                  is_pep, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
               (subject, subject_id, data['full_name'].strip(), data.get('nationality') or None,
                data.get('ownership_pct') or None,
                data.get('control_type') if data.get('control_type') in ('ownership', 'control', 'senior_manager')
                else 'ownership', bool(data.get('is_pep')), user_id))
    db.commit()


def bos(subject, subject_id, db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM kyc_beneficial_owners WHERE subject = %s AND subject_id = %s ORDER BY id",
                 (subject, subject_id))


def declarations(subject, subject_id, db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM kyc_bo_declarations WHERE subject = %s AND subject_id = %s ORDER BY signed_on DESC",
                 (subject, subject_id))


def add_declaration(subject, subject_id, declaration_type, bo_name, signed_on, user_id, db=None):
    db = db or get_db()
    if declaration_type not in ('self', 'other'):
        raise AssuranceError(N_('choose self or another beneficial owner'))
    if declaration_type == 'other' and not (bo_name or '').strip():
        raise AssuranceError(N_('name the beneficial owner'))
    if not signed_on:
        raise AssuranceError(N_('signature date is required'))
    did = db.execute("""INSERT INTO kyc_bo_declarations (subject, subject_id, declaration_type, bo_name, signed_on, recorded_by)
                        VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (subject, subject_id, declaration_type, (bo_name or '').strip() or None, signed_on, user_id)
                     ).fetchone()['id']
    db.commit()
    return did


def risk_factors(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM kyc_risk_factors ORDER BY category, factor_key")


def risk_bands(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM kyc_risk_bands ORDER BY min_score")


def rate_subject(subject, subject_id, user_id, trigger='manual', db=None):
    db = db or get_db()
    s = subjects.SUBJECTS[subject]
    r = subjects.row(subject, subject_id, db)
    if not r:
        raise AssuranceError(N_('record not found'))
    values = dict(r)
    values.update(profile(subject, subject_id, db))
    if s.risk_values:
        values.update({k: v for k, v in s.risk_values(r, db).items() if v is not None})
    score, band, breakdown = logic.rate(values, risk_factors(db), risk_bands(db))
    bands = {b['band']: b for b in risk_bands(db)}
    key = bands.get(band, {}).get('refresh_param_key')
    months = param(key) if key else None
    nr = logic.next_review(date.today(), months)
    db.execute("UPDATE kyc_risk_ratings SET is_current = FALSE WHERE subject = %s AND subject_id = %s AND is_current",
               (subject, subject_id))
    db.execute("""INSERT INTO kyc_risk_ratings (subject, subject_id, score, band, factors, trigger, rated_by, next_review_date)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
               (subject, subject_id, score, band, json.dumps(breakdown, default=str), trigger, user_id, nr))
    db.commit()
    return score, band, nr


EDD_ITEMS = ['Source of funds verified', 'Source of wealth verified', 'Purpose and intended nature of the relationship',
             'Adverse media reviewed', 'Beneficial owners verified', 'Senior management approval obtained']


def onboarding(subject, subject_id, db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM kyc_onboarding WHERE subject = %s AND subject_id = %s", (subject, subject_id)).fetchone()
    return dict(r) if r else None


def save_edd(subject, subject_id, done_items, note, user_id, db=None):
    db = db or get_db()
    checklist = [{'item': i, 'done': i in done_items} for i in EDD_ITEMS]
    complete = all(c['done'] for c in checklist)
    db.execute("""INSERT INTO kyc_onboarding (subject, subject_id, edd_checklist, edd_completed, note)
                  VALUES (%s,%s,%s,%s,%s) ON CONFLICT (subject, subject_id)
                  DO UPDATE SET edd_checklist = EXCLUDED.edd_checklist, edd_completed = EXCLUDED.edd_completed,
                  note = EXCLUDED.note""", (subject, subject_id, json.dumps(checklist), complete, note))
    db.commit()


def onboarding_blockers(subject, subject_id, db=None):
    db = db or get_db()
    r = subjects.row(subject, subject_id, db)
    if not r:
        return ['record not found']
    st = file_status(subject, r, profile(subject, subject_id, db), fields(subject, db))
    out = []
    if st['missing']:
        out.append('incomplete KYC file: ' + ', '.join(st['missing']))
    rating = _safe_rows(db, "SELECT * FROM kyc_risk_ratings WHERE subject = %s AND subject_id = %s AND is_current",
                        (subject, subject_id))
    if not rating:
        out.append('no risk rating')
    elif rating[0]['band'] == 'high':
        o = onboarding(subject, subject_id, db) or {}
        if not o.get('edd_completed'):
            out.append('high risk: enhanced due diligence not completed')
        if not o.get('senior_approved_by'):
            out.append('high risk: senior management approval missing')
    if st['kind'] == 'entity' and not declarations(subject, subject_id, db):
        out.append('no signed beneficial-owner declaration')
    return out


def senior_approve(subject, subject_id, user_id, db=None):
    db = db or get_db()
    from models.user import User
    u = User.get_by_id(user_id)
    if not (u and (u.is_compliance_officer() or u.role in ('manager',))):
        raise AssuranceError(N_('senior approval must be given by a manager or compliance officer'))
    db.execute("""INSERT INTO kyc_onboarding (subject, subject_id, senior_approved_by, senior_approved_at)
                  VALUES (%s,%s,%s,%s) ON CONFLICT (subject, subject_id)
                  DO UPDATE SET senior_approved_by = EXCLUDED.senior_approved_by, senior_approved_at = EXCLUDED.senior_approved_at""",
               (subject, subject_id, user_id, datetime.now()))
    db.commit()


def approve_onboarding(subject, subject_id, user_id, db=None):
    db = db or get_db()
    blockers = onboarding_blockers(subject, subject_id, db)
    if blockers:
        raise AssuranceError('cannot approve: ' + '; '.join(blockers))
    db.execute("""INSERT INTO kyc_onboarding (subject, subject_id, status, approved_by, approved_at)
                  VALUES (%s,%s,'approved',%s,%s) ON CONFLICT (subject, subject_id)
                  DO UPDATE SET status = 'approved', approved_by = EXCLUDED.approved_by, approved_at = EXCLUDED.approved_at""",
               (subject, subject_id, user_id, datetime.now()))
    db.commit()


# ------------------------------------------------------------------ training coverage
def training_coverage(course_ids=None, category=None, window_months=None, db=None):
    """Active users by department and whether they completed one of the courses."""
    db = db or get_db()
    people = _rows(db, """SELECT u.id, COALESCE(d.name, u.department, '-') AS "group" FROM users u
                          LEFT JOIN departments d ON d.id = u.department_id WHERE u.is_active = 1""")
    clauses, args = ["e.status = 'completed'"], []
    if course_ids:
        clauses.append('e.course_id = ANY(%s)')
        args.append([int(c) for c in course_ids])
    elif category:
        clauses.append('e.course_id IN (SELECT id FROM training_courses WHERE category ILIKE %s)')
        args.append(f'%{category}%')
    if window_months:
        clauses.append("COALESCE(e.completion_date, e.enrolled_date) >= %s")
        args.append(date.today() - timedelta(days=int(float(window_months) * 30.4)))
    done = {r['employee_id'] for r in _safe_rows(
        db, f"SELECT DISTINCT e.employee_id FROM training_enrollments e WHERE {' AND '.join(clauses)}", tuple(args))}
    return logic.coverage_by_group(people, done), people, done


# ------------------------------------------------------------------ internal-audit coverage
def audit_coverage(year=None, db=None):
    """Controls covered by the year's audit plan via auditable areas (ia_area_controls)."""
    db = db or get_db()
    year = year or date.today().year
    covered = {r['control_id'] for r in _safe_rows(db, """
        SELECT DISTINCT ac.control_id FROM ia_area_controls ac
        JOIN audit_projects p ON p.auditable_area_id = ac.universe_id
        JOIN annual_audit_plans ap ON ap.id = p.plan_id WHERE ap.plan_year = %s""", (year,))}
    controls = _rows(db, "SELECT id, control_code, title_en, title_ar, criticality, area FROM rc_controls WHERE is_active "
                         "ORDER BY control_code")
    areas = _safe_rows(db, "SELECT id, auditable_area FROM audit_universe WHERE CAST(is_active AS INTEGER) = 1 ORDER BY auditable_area")
    mapping = {}
    for r in _safe_rows(db, "SELECT universe_id, control_id FROM ia_area_controls"):
        mapping.setdefault(r['control_id'], []).append(r['universe_id'])
    return {'year': year, 'controls': controls, 'covered': covered, 'areas': areas, 'mapping': mapping,
            'gaps': logic.audit_coverage(controls, covered)}


def map_area_control(universe_id, control_id, linked=True, db=None):
    db = db or get_db()
    if linked:
        db.execute("INSERT INTO ia_area_controls (universe_id, control_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                   (universe_id, control_id))
    else:
        db.execute("DELETE FROM ia_area_controls WHERE universe_id = %s AND control_id = %s", (universe_id, control_id))
    db.commit()
