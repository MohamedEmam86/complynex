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
Service layer for IT / cyber / business-continuity evidence (extends the
cyber module). Pages, checks, the API feed and the scheduled TLS sweep all
go through here.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from database.db import get_db

from . import resilience_logic as logic
from . import tls


def N_(s):
    """Mark a message for translation (shown translated by the page)."""
    return s


class ResilienceError(ValueError):
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
    if not key:
        return default
    from regcontrols.api import get_param
    from regcontrols.engine import company_licence_type
    return get_param(key, company_licence_type(), default=default)


def _date(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        raise ResilienceError(N_('dates must be YYYY-MM-DD'))


def _num(v):
    if v in (None, ''):
        return None
    try:
        return Decimal(str(v).strip())
    except InvalidOperation:
        raise ResilienceError(N_('not a number'))


def _bool(v):
    return str(v).lower() in ('1', 'true', 'yes', 'on')


def _active(data):
    """Checkbox from a form (hidden _form marker) or an optional API field (default active)."""
    if data.get('_form'):
        return _bool(data.get('is_active'))
    return data.get('is_active') is None or _bool(data.get('is_active'))


def has_files(record_type, record_id, db=None):
    db = db or get_db()
    return bool(_safe_rows(db, """SELECT 1 FROM generic_attachments WHERE module = 'cyber' AND record_type = %s
                                  AND record_id = %s AND COALESCE(is_deleted, 0) = 0 LIMIT 1""", (record_type, record_id)))


# ------------------------------------------------------------------ BCP / DR
def sites(db=None):
    db = db or get_db()
    return _rows(db, """SELECT s.*, (SELECT max(t.test_date) FROM cy_dr_tests t WHERE t.site_id = s.id) AS last_test
                        FROM cy_bcp_sites s ORDER BY s.is_active DESC, s.site_type, s.name""")


def save_site(data, user_id, db=None):
    db = db or get_db()
    if not (data.get('name') or '').strip():
        raise ResilienceError(N_('name is required'))
    st = data.get('site_type') if data.get('site_type') in ('primary', 'dr', 'backup', 'cloud') else 'dr'
    rid = db.execute("""INSERT INTO cy_bcp_sites (name, site_type, location, provider, rto_hours, rpo_hours, note, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (data['name'].strip(), st, data.get('location') or None, data.get('provider') or None,
                      _num(data.get('rto_hours')), _num(data.get('rpo_hours')), data.get('note') or None,
                      user_id)).fetchone()['id']
    db.commit()
    return rid


def dr_tests(db=None):
    db = db or get_db()
    return _rows(db, """SELECT t.*, s.name AS site_name FROM cy_dr_tests t LEFT JOIN cy_bcp_sites s ON s.id = t.site_id
                        ORDER BY t.test_date DESC, t.id DESC""")


def add_dr_test(data, user_id, db=None):
    db = db or get_db()
    d = _date(data.get('test_date'))
    if not d or data.get('result') not in ('pass', 'partial', 'fail'):
        raise ResilienceError(N_('test date and result are required'))
    if d > date.today():
        raise ResilienceError(N_('the test date cannot be in the future'))
    for k in ('rto_achieved_hours', 'rpo_achieved_hours'):
        v = _num(data.get(k))
        if v is not None and v < 0:
            raise ResilienceError(N_('RTO and RPO cannot be negative'))
    tid = db.execute("""INSERT INTO cy_dr_tests (site_id, test_date, scope, result, rto_achieved_hours, rpo_achieved_hours,
                        issues, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (data.get('site_id') or None, d, data.get('scope') or None, data['result'],
                      _num(data.get('rto_achieved_hours')), _num(data.get('rpo_achieved_hours')),
                      data.get('issues') or None, user_id)).fetchone()['id']
    if data['result'] != 'pass':
        from regcontrols.api import raise_finding
        fid = raise_finding(f"DR test {d} {data['result']}", source='self_identified', source_ref=f'cy_dr_test:{tid}',
                            severity='high', description=data.get('issues') or 'DR test not fully successful',
                            created_by=user_id, db=db)
        db.execute("UPDATE cy_dr_tests SET finding_id = %s WHERE id = %s", (fid, tid))
    db.commit()
    return tid


# ------------------------------------------------------------------ backups
def backups(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM cy_backups ORDER BY is_active DESC, system_name")


def save_backup(data, db=None, source='manual'):
    db = db or get_db()
    name = (data.get('system_name') or '').strip()
    if not name:
        raise ResilienceError(N_('system name is required'))
    bt = data.get('backup_type') if data.get('backup_type') in ('full', 'incremental', 'snapshot', 'replication') else 'full'
    lt = data.get('location_type') if data.get('location_type') in ('onsite', 'offsite', 'cloud') else 'offsite'
    last = data.get('last_success_at')
    if isinstance(last, str) and last:
        try:
            last = datetime.fromisoformat(last.replace('Z', '').strip())
        except ValueError:
            raise ResilienceError(N_('last success must be an ISO date-time'))
    status = data.get('last_status') if data.get('last_status') in ('success', 'failed', 'partial') else None
    bid = db.execute("""INSERT INTO cy_backups (system_name, backup_type, location_type, location_detail, encrypted,
                        last_success_at, last_status, last_message, last_restore_test, is_active, source, updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (system_name) DO UPDATE SET backup_type = EXCLUDED.backup_type,
                        location_type = EXCLUDED.location_type, location_detail = EXCLUDED.location_detail,
                        encrypted = EXCLUDED.encrypted,
                        last_success_at = COALESCE(EXCLUDED.last_success_at, cy_backups.last_success_at),
                        last_status = COALESCE(EXCLUDED.last_status, cy_backups.last_status),
                        last_message = EXCLUDED.last_message,
                        last_restore_test = COALESCE(EXCLUDED.last_restore_test, cy_backups.last_restore_test),
                        is_active = EXCLUDED.is_active, source = EXCLUDED.source, updated_at = EXCLUDED.updated_at
                        RETURNING id""",
                     (name, bt, lt, data.get('location_detail') or None, _bool(data.get('encrypted')), last or None,
                      status, data.get('last_message') or None, _date(data.get('last_restore_test')),
                      _active(data), source, datetime.now())).fetchone()['id']
    db.commit()
    return bid


def record_backup_run(system_name, status, finished_at=None, message=None, db=None, **attrs):
    """Feed from a backup job (API). A successful run moves last_success_at."""
    db = db or get_db()
    if status not in ('success', 'failed', 'partial'):
        raise ResilienceError(N_('status must be success, failed or partial'))
    finished_at = finished_at or datetime.now()
    data = {'system_name': system_name, 'last_status': status, 'last_message': message, **attrs}
    ex = db.execute("SELECT * FROM cy_backups WHERE system_name = %s", (system_name,)).fetchone()
    if ex:
        ex = dict(ex)
        for k in ('backup_type', 'location_type', 'location_detail', 'encrypted'):
            data.setdefault(k, ex[k])
    if status == 'success':
        data['last_success_at'] = finished_at
    return save_backup(data, db, source='api')


# ------------------------------------------------------------------ integrations
def integrations(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM cy_integrations ORDER BY code")


def save_integration(data, user_id, db=None):
    db = db or get_db()
    code = (data.get('code') or '').strip().lower()
    if not code or not (data.get('name') or '').strip():
        raise ResilienceError(N_('code and name are required'))
    st = data.get('status') if data.get('status') in ('live', 'testing', 'down', 'not_connected') else 'not_connected'
    it = data.get('integration_type') if data.get('integration_type') in ('api', 'sftp', 'portal', 'email', 'manual') else 'api'
    rid = db.execute("""INSERT INTO cy_integrations (code, name, counterparty, purpose, integration_type, status, note,
                        updated_by, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, counterparty = EXCLUDED.counterparty,
                        purpose = EXCLUDED.purpose, integration_type = EXCLUDED.integration_type, status = EXCLUDED.status,
                        note = EXCLUDED.note, updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at
                        RETURNING id""",
                     (code, data['name'].strip(), data.get('counterparty') or None, data.get('purpose') or None, it, st,
                      data.get('note') or None, user_id, datetime.now())).fetchone()['id']
    db.commit()
    return rid


def record_integration_exchange(code, ok, db=None, at=None):
    """Called by an integration (or the API) after each exchange."""
    db = db or get_db()
    at = at or datetime.now()
    n = db.execute("""UPDATE cy_integrations SET last_checked_at = %s,
                      last_success_at = CASE WHEN %s THEN %s ELSE last_success_at END,
                      status = CASE WHEN %s THEN (CASE WHEN status = 'not_connected' THEN 'live' ELSE status END)
                                    ELSE 'down' END WHERE code = %s""", (at, ok, at, ok, code)).rowcount
    db.commit()
    if not n:
        raise ResilienceError(N_('unknown integration code'))


def install_integration(code, name, *, counterparty=None, purpose=None, integration_type='api', pack_code=None, db=None):
    """Declare an expected integration (status not_connected) if missing — for content packs."""
    db = db or get_db()
    db.execute("""INSERT INTO cy_integrations (code, name, counterparty, purpose, integration_type, pack_code)
                  VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (code) DO NOTHING""",
               (code, name, counterparty, purpose, integration_type, pack_code))


# ------------------------------------------------------------------ security assessments
def assessments(db=None, assessment_type=None):
    db = db or get_db()
    if assessment_type:
        return _rows(db, "SELECT * FROM cy_assessments WHERE assessment_type = %s ORDER BY performed_on DESC",
                     (assessment_type,))
    return _rows(db, "SELECT * FROM cy_assessments ORDER BY performed_on DESC, id DESC")


def add_assessment(data, user_id, db=None):
    db = db or get_db()
    t = (data.get('assessment_type') or '').strip().lower()
    d = _date(data.get('performed_on'))
    if not t or not (data.get('title') or '').strip() or not d:
        raise ResilienceError(N_('type, title and date are required'))
    rid = db.execute("""INSERT INTO cy_assessments (assessment_type, title, provider, provider_qualification, performed_on,
                        valid_until, scope, critical_open, high_open, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (t, data['title'].strip(), data.get('provider') or None, data.get('provider_qualification') or None, d,
                      _date(data.get('valid_until')), data.get('scope') or None, int(data.get('critical_open') or 0),
                      int(data.get('high_open') or 0), user_id)).fetchone()['id']
    db.commit()
    return rid


def update_open_findings(assessment_id, critical, high, db=None):
    db = db or get_db()
    db.execute("UPDATE cy_assessments SET critical_open = %s, high_open = %s WHERE id = %s",
               (max(0, int(critical or 0)), max(0, int(high or 0)), assessment_id))
    db.commit()


def accept_assessment(assessment_id, user_id, db=None):
    db = db or get_db()
    a = db.execute("SELECT * FROM cy_assessments WHERE id = %s", (assessment_id,)).fetchone()
    if not a:
        raise ResilienceError(N_('assessment not found'))
    if not has_files('cy_assessment', assessment_id, db):
        raise ResilienceError(N_('attach the report before accepting it'))
    db.execute("UPDATE cy_assessments SET status = 'accepted', accepted_by = %s, accepted_at = %s WHERE id = %s",
               (user_id, datetime.now(), assessment_id))
    db.commit()


# ------------------------------------------------------------------ security assets & licences
def assets(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM cy_security_assets ORDER BY is_active DESC, asset_type, product")


def save_asset(data, user_id, asset_id=None, db=None):
    db = db or get_db()
    t = (data.get('asset_type') or '').strip().lower()
    if not t or not (data.get('product') or '').strip():
        raise ResilienceError(N_('type and product are required'))
    abroad = data.get('sends_data_abroad')
    abroad = None if abroad in (None, '') else _bool(abroad)
    vals = (t, data['product'].strip(), data.get('vendor') or None, data.get('licence_ref') or None,
            _date(data.get('licence_expiry')), data.get('coverage_note') or None,
            _active(data), abroad, data.get('data_location') or None,
            _date(data.get('residency_attested_on')), data.get('residency_attested_by') or None, user_id, datetime.now())
    cols = ('asset_type, product, vendor, licence_ref, licence_expiry, coverage_note, is_active, sends_data_abroad, '
            'data_location, residency_attested_on, residency_attested_by, updated_by, updated_at')
    if asset_id:
        db.execute(f"UPDATE cy_security_assets SET ({cols}) = ({', '.join(['%s'] * 13)}) WHERE id = %s", (*vals, asset_id))
    else:
        asset_id = db.execute(f"INSERT INTO cy_security_assets ({cols}) VALUES ({', '.join(['%s'] * 13)}) RETURNING id",
                              vals).fetchone()['id']
    db.commit()
    return asset_id


# ------------------------------------------------------------------ domains & TLS
def domains(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM cy_domains ORDER BY is_active DESC, domain")


def add_domain(domain, user_id, port=443, db=None):
    db = db or get_db()
    d = (domain or '').strip().lower().replace('https://', '').replace('http://', '').split('/')[0]
    if not d or '.' not in d or ' ' in d:
        raise ResilienceError(N_('enter a domain name, e.g. portal.example.com'))
    rid = db.execute("""INSERT INTO cy_domains (domain, port, created_by) VALUES (%s,%s,%s)
                        ON CONFLICT (domain) DO UPDATE SET is_active = TRUE RETURNING id""",
                     (d, int(port or 443), user_id)).fetchone()['id']
    db.commit()
    return rid


def check_domain(domain_id, db=None, checker=None):
    """Run the TLS check now and store the result (checker injectable for tests)."""
    db = db or get_db()
    d = db.execute("SELECT * FROM cy_domains WHERE id = %s", (domain_id,)).fetchone()
    if not d:
        raise ResilienceError(N_('domain not found'))
    res = (checker or tls.check)(d['domain'], d['port'])
    db.execute("""UPDATE cy_domains SET last_checked_at = %s, cert_subject = %s, cert_issuer = %s, cert_not_after = %s,
                  last_error = %s WHERE id = %s""",
               (datetime.now(), res.get('subject'), res.get('issuer'), res.get('not_after'), res.get('error'), domain_id))
    db.commit()
    return res


def tls_sweep(db=None, max_age_hours=12, checker=None):
    """Check every active domain not checked in the last max_age_hours."""
    db = db or get_db()
    due = _safe_rows(db, """SELECT id FROM cy_domains WHERE is_active AND (last_checked_at IS NULL OR last_checked_at < %s)""",
                     (datetime.now() - timedelta(hours=max_age_hours),))
    errors = 0
    for d in due:
        if check_domain(d['id'], db, checker).get('error'):
            errors += 1
    return {'checked': len(due), 'errors': errors}


# ------------------------------------------------------------------ maturity self-assessment
def maturity_assessments(db=None):
    db = db or get_db()
    return _rows(db, """SELECT a.*, f.code AS framework_code, f.name_en AS framework_name,
                        (SELECT count(*) FROM cy_maturity_scores s WHERE s.assessment_id = a.id) AS items,
                        (SELECT round(avg(s.current_level), 2) FROM cy_maturity_scores s WHERE s.assessment_id = a.id) AS avg_current
                        FROM cy_maturity_assessments a JOIN rc_frameworks f ON f.id = a.framework_id
                        ORDER BY a.assessed_on DESC, a.id DESC""")


def start_maturity(framework_id, title, user_id, db=None, default_target=3):
    db = db or get_db()
    reqs = _rows(db, "SELECT id FROM rc_requirements WHERE framework_id = %s ORDER BY sort_order, id", (framework_id,))
    if not reqs:
        raise ResilienceError(N_('this framework has no requirements yet'))
    prev = db.execute("""SELECT id FROM cy_maturity_assessments WHERE framework_id = %s ORDER BY assessed_on DESC, id DESC
                         LIMIT 1""", (framework_id,)).fetchone()
    aid = db.execute("""INSERT INTO cy_maturity_assessments (framework_id, title, created_by) VALUES (%s,%s,%s)
                        RETURNING id""", (framework_id, (title or '').strip() or 'Maturity self-assessment', user_id)).fetchone()['id']
    carry = {r['requirement_id']: r for r in _rows(db, "SELECT * FROM cy_maturity_scores WHERE assessment_id = %s",
                                                   (prev['id'],))} if prev else {}
    for r in reqs:
        p = carry.get(r['id'], {})
        db.execute("""INSERT INTO cy_maturity_scores (assessment_id, requirement_id, current_level, target_level, note)
                      VALUES (%s,%s,%s,%s,%s)""", (aid, r['id'], p.get('current_level'), p.get('target_level', default_target),
                                                  p.get('note')))
    db.commit()
    return aid


def maturity_scores(assessment_id, db=None):
    db = db or get_db()
    return _rows(db, """SELECT s.*, q.ref_code, q.title_en, q.title_ar, q.area_code FROM cy_maturity_scores s
                        JOIN rc_requirements q ON q.id = s.requirement_id WHERE s.assessment_id = %s
                        ORDER BY q.sort_order, q.id""", (assessment_id,))


def _level(v):
    """A maturity level: empty, or a whole number 0-5 (the DB check constraint)."""
    if v in (None, ''):
        return None
    try:
        n = int(str(v).strip())
    except ValueError:
        raise ResilienceError(N_('maturity levels must be whole numbers from 0 to 5'))
    if not 0 <= n <= 5:
        raise ResilienceError(N_('maturity levels must be whole numbers from 0 to 5'))
    return n


def save_maturity(assessment_id, levels, finalise=False, db=None):
    """levels: {requirement_id: (current, target, note)}."""
    db = db or get_db()
    a = db.execute("SELECT status FROM cy_maturity_assessments WHERE id = %s", (assessment_id,)).fetchone()
    if not a:
        raise ResilienceError(N_('assessment not found'))
    if a['status'] == 'final':
        raise ResilienceError(N_('a final assessment cannot be changed'))
    parsed = {rid: (_level(cur), _level(tgt), note) for rid, (cur, tgt, note) in levels.items()}
    for rid, (cur, tgt, note) in parsed.items():
        db.execute("""UPDATE cy_maturity_scores SET current_level = %s, target_level = %s, note = %s
                      WHERE assessment_id = %s AND requirement_id = %s""",
                   (cur, tgt, note or None, assessment_id, rid))
    if finalise:
        if db.execute("SELECT count(*) AS n FROM cy_maturity_scores WHERE assessment_id = %s AND current_level IS NULL",
                      (assessment_id,)).fetchone()['n']:
            db.rollback()
            raise ResilienceError(N_('rate every requirement before finalising'))
        db.execute("UPDATE cy_maturity_assessments SET status = 'final', assessed_on = %s WHERE id = %s",
                   (date.today(), assessment_id))
    db.commit()


# ------------------------------------------------------------------ IT risks (ERM register, not duplicated)
def it_risks(categories=None, db=None):
    """Risks of the ERM register in the given category codes (default: the technology category)."""
    db = db or get_db()
    cats = categories or ['TEC']
    return _safe_rows(db, """SELECT r.id, r.risk_id, r.risk_title, r.status, r.inherent_risk_score, r.residual_risk_score,
                             r.last_review_date, r.next_review_date, c.category_code, c.category_name,
                             COALESCE(u.first_name || ' ' || u.last_name, '-') AS owner
                             FROM risks r JOIN risk_categories c ON c.id = r.category_id
                             LEFT JOIN users u ON u.id = r.risk_owner_id
                             WHERE c.category_code = ANY(%s) OR c.parent_category_id IN
                                   (SELECT id FROM risk_categories WHERE category_code = ANY(%s))
                             ORDER BY r.residual_risk_score DESC NULLS LAST, r.inherent_risk_score DESC""", (cats, cats))
