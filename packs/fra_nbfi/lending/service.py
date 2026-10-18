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
FRA NBFI pack — database layer for Lending Conduct & Portfolio. Decisions are
delegated to logic.py; every regulatory number is read through regcontrols.
"""

import json
from datetime import date, datetime

from database.db import get_db

from . import logic

MODULE = 'lending'


class LendingError(ValueError):
    pass


def _rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


# ------------------------------------------------------------------ parameters
def licence_type():
    from regcontrols.engine import company_licence_type
    return company_licence_type()


def param(key, default=None, as_of=None):
    """Regulatory parameter for the company licence, or `default` when it is
    not defined / not set yet (the matching control check reports that)."""
    from regcontrols.api import get_param
    return get_param(key, licence_type(), as_of, default=default)


# ------------------------------------------------------------------ loading
def get_loan(loan_id, db=None):
    db = db or get_db()
    r = db.execute("""SELECT l.*, c.client_ref, c.full_name AS client_name, c.monthly_revenue, c.project_size,
                             c.party_id, c.client_type
                      FROM ln_loans l JOIN ln_clients c ON c.id = l.client_id WHERE l.id = %s""",
                   (loan_id,)).fetchone()
    return dict(r) if r else None


def bundle(loan_id, db=None):
    """Everything about one loan file."""
    db = db or get_db()
    loan = get_loan(loan_id, db)
    if not loan:
        return None
    one = lambda sql: (dict(r) if (r := db.execute(sql, (loan_id,)).fetchone()) else None)  # noqa: E731
    b = {
        'loan': loan,
        'client': dict(db.execute("SELECT * FROM ln_clients WHERE id = %s", (loan['client_id'],)).fetchone()),
        'product': (dict(r) if (r := db.execute("SELECT * FROM ln_products WHERE code = %s",
                                                 (loan['product_code'],)).fetchone()) else None),
        'contract': one("SELECT * FROM ln_contracts WHERE loan_id = %s"),
        'study': one("SELECT * FROM ln_credit_studies WHERE loan_id = %s"),
        'documents': _rows(db, "SELECT * FROM ln_documents WHERE loan_id = %s ORDER BY doc_type", (loan_id,)),
        'instalments': _rows(db, "SELECT * FROM ln_instalments WHERE loan_id = %s ORDER BY seq", (loan_id,)),
        'visits': _rows(db, "SELECT * FROM ln_visits WHERE loan_id = %s ORDER BY COALESCE(visit_date, planned_date)",
                        (loan_id,)),
        'early_repayments': _rows(db, "SELECT * FROM ln_early_repayments WHERE loan_id = %s ORDER BY id DESC",
                                  (loan_id,)),
        'reschedulings': _rows(db, "SELECT * FROM ln_reschedulings WHERE loan_id = %s ORDER BY resched_date",
                               (loan_id,)),
        'transfers': _rows(db, "SELECT * FROM ln_transfers WHERE loan_id = %s ORDER BY transfer_date", (loan_id,)),
        'exceptions': _rows(db, """SELECT e.*, u.first_name || ' ' || u.last_name AS requested_by_name
                                   FROM ln_exceptions e LEFT JOIN users u ON u.id = e.requested_by
                                   WHERE e.loan_id = %s ORDER BY e.id DESC""", (loan_id,)),
        'qa_flags': _rows(db, "SELECT * FROM ln_qa_flags WHERE loan_id = %s ORDER BY id", (loan_id,)),
    }
    return b


# ------------------------------------------------------------------ file & eligibility
def file_gaps(b):
    return logic.file_gaps(
        b['loan'], contract=b['contract'], documents=b['documents'], study=b['study'],
        product_docs=(b['product'] or {}).get('required_docs') or (),
        gps_min_amount=param('lending.gps_mandatory_min_amount'),
        min_cost_lines=param('lending.min_cost_lines'))


def eligibility(client):
    return logic.eligibility_breaches(client, max_monthly_revenue=param('lending.max_client_monthly_revenue'),
                                      max_project_size=param('lending.max_project_size'))


def refresh_file_status(loan_id, db=None):
    db = db or get_db()
    b = bundle(loan_id, db)
    gaps = file_gaps(b)
    db.execute("UPDATE ln_loans SET file_complete = %s, file_gaps = %s, updated_at = %s WHERE id = %s",
               (not gaps, json.dumps([{'control': g[0], 'code': g[1], 'message': g[2]} for g in gaps]),
                datetime.now(), loan_id))
    db.commit()
    return gaps


def refresh_all_files(db=None):
    db = db or get_db()
    for r in db.execute("SELECT id FROM ln_loans WHERE status IN ('approved', 'disbursed')").fetchall():
        refresh_file_status(r['id'], db)


def approved_exception(b, exception_type):
    return any(e['exception_type'] == exception_type and e['status'] == 'approved' for e in b['exceptions'])


def disbursement_blockers(b):
    """What stops this loan from being marked disbursed (empty = may disburse)."""
    blockers = []
    gaps = file_gaps(b)
    if gaps and not approved_exception(b, 'file_incomplete'):
        blockers += [g[2] for g in gaps]
    elig = eligibility(b['client'])
    if elig and not approved_exception(b, 'eligibility'):
        blockers += [f'Client {f} {v} above licence ceiling {c}' for f, v, c in elig]
    return blockers


def mark_disbursed(loan_id, user_id, disbursement_date=None, db=None):
    db = db or get_db()
    b = bundle(loan_id, db)
    if not b:
        raise LendingError('loan not found')
    if b['loan']['status'] not in ('application', 'approved'):
        raise LendingError('only an application or approved loan can be disbursed')
    blockers = disbursement_blockers(b)
    if blockers:
        raise LendingError('cannot disburse: ' + '; '.join(blockers))
    d = disbursement_date or date.today()
    db.execute("""UPDATE ln_loans SET status = 'disbursed', disbursement_date = %s,
                  outstanding_principal = CASE WHEN outstanding_principal = 0 THEN amount ELSE outstanding_principal END,
                  updated_at = %s WHERE id = %s""", (d, datetime.now(), loan_id))
    db.commit()
    refresh_file_status(loan_id, db)


def request_exception(loan_id, exception_type, reason, user_id, db=None):
    db = db or get_db()
    if exception_type not in ('eligibility', 'file_incomplete'):
        raise LendingError('unknown exception type')
    if not (reason or '').strip():
        raise LendingError('a reason is required')
    db.execute("INSERT INTO ln_exceptions (loan_id, exception_type, reason, requested_by) VALUES (%s,%s,%s,%s)",
               (loan_id, exception_type, reason.strip(), user_id))
    db.commit()


def decide_exception(exception_id, user_id, approve, comment=None, db=None):
    db = db or get_db()
    e = db.execute("SELECT * FROM ln_exceptions WHERE id = %s", (exception_id,)).fetchone()
    if not e or e['status'] != 'pending':
        raise LendingError('exception not found or already decided')
    if e['requested_by'] == user_id:
        raise LendingError('an exception must be approved by someone other than the requester')
    db.execute("UPDATE ln_exceptions SET status = %s, decided_by = %s, decided_at = %s, decision_comment = %s "
               "WHERE id = %s", ('approved' if approve else 'rejected', user_id, datetime.now(), comment,
                                 exception_id))
    db.commit()
    return e['loan_id']


# ------------------------------------------------------------------ portfolio
def refresh_dpd(today=None, db=None):
    """Recompute days past due from the instalment schedule (imported DPD is
    kept for loans without a schedule)."""
    db = db or get_db()
    today = today or date.today()
    loans = _rows(db, "SELECT id, days_past_due FROM ln_loans WHERE status = 'disbursed'")
    inst = {}
    for i in _rows(db, """SELECT i.* FROM ln_instalments i JOIN ln_loans l ON l.id = i.loan_id
                          WHERE l.status = 'disbursed'"""):
        inst.setdefault(i['loan_id'], []).append(i)
    for l in loans:
        dpd = logic.days_past_due(inst.get(l['id'], []), today, fallback=l['days_past_due'])
        if dpd != l['days_past_due']:
            db.execute("UPDATE ln_loans SET days_past_due = %s WHERE id = %s", (dpd, l['id']))
    db.commit()


def active_portfolio(scope_sql='', scope_args=(), db=None):
    db = db or get_db()
    return _rows(db, f"""SELECT l.id, l.loan_ref, l.branch_code, l.officer_code, l.product_code,
                               l.outstanding_principal, l.days_past_due AS dpd, l.client_id
                        FROM ln_loans l WHERE l.status = 'disbursed' {scope_sql}""", tuple(scope_args))


def snapshot_par(period=None, db=None):
    """Store PAR by company/branch/officer/product for a period (month end)."""
    db = db or get_db()
    period = period or date.today()
    loans = active_portfolio(db=db)
    groups = {'company': {'ALL': logic.portfolio_metrics(loans)},
              'branch': logic.par_by(loans, 'branch_code'),
              'officer': logic.par_by(loans, 'officer_code'),
              'product': logic.par_by(loans, 'product_code')}
    for dim, items in groups.items():
        for val, m in items.items():
            db.execute("""
                INSERT INTO ln_par_snapshots (period, dimension, dim_value, loans, outstanding, par30, par60, par90, par120)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (period, dimension, dim_value) DO UPDATE SET loans = EXCLUDED.loans,
                    outstanding = EXCLUDED.outstanding, par30 = EXCLUDED.par30, par60 = EXCLUDED.par60,
                    par90 = EXCLUDED.par90, par120 = EXCLUDED.par120, computed_at = CURRENT_TIMESTAMP
            """, (period, dim, str(val)[:60], m['loans'], m['outstanding'], *[m['par'][x] for x in logic.PAR_LEVELS]))
    db.commit()
    return groups


def previous_snapshot(dimension, dim_value, before, db=None):
    db = db or get_db()
    r = db.execute("""SELECT * FROM ln_par_snapshots WHERE dimension = %s AND dim_value = %s AND period < %s
                      ORDER BY period DESC LIMIT 1""", (dimension, dim_value, before)).fetchone()
    return dict(r) if r else None


# ------------------------------------------------------------------ fees
def fee_breaches(db=None, today=None):
    """All pricing breaches with the over-charge per loan / client.
    Returns dict control_code -> list of breach dicts, plus 'missing_params'."""
    db = db or get_db()
    cap, tiers = param('lending.admin_fee_cap_pct'), param('lending.admin_fee_tiers')
    rate, pcap = param('lending.late_penalty_rate_pct'), param('lending.late_penalty_cap_pct')
    tcap, rcap = param('lending.transfer_fee_cap'), param('lending.rescheduling_fee_cap')
    out = {'FRA-017': [], 'FRA-018': [], 'FRA-020': [], 'FRA-025': [], 'FRA-026': [], 'missing_params': []}
    for k, v in (('lending.admin_fee_cap_pct', cap), ('lending.admin_fee_tiers', tiers),
                 ('lending.late_penalty_rate_pct', rate), ('lending.transfer_fee_cap', tcap),
                 ('lending.rescheduling_fee_cap', rcap)):
        if v is None:
            out['missing_params'].append(k)
    loans = _rows(db, """SELECT l.*, c.client_ref, c.full_name AS client_name FROM ln_loans l
                         JOIN ln_clients c ON c.id = l.client_id WHERE l.status <> 'rejected'""")
    for l in loans:
        base = {'loan_id': l['id'], 'loan_ref': l['loan_ref'], 'client_ref': l['client_ref'],
                'client_name': l['client_name'], 'branch': l['branch_code']}
        if cap is not None:
            b = logic.admin_fee_breach(l, cap_pct=cap)
            if b:
                out['FRA-017'].append(dict(base, charged=str(logic.money(l['admin_fee_amount'])), allowed=str(b[1]),
                                           overcharge=str(b[0])))
        if tiers:
            b = logic.admin_fee_breach(l, tiers=tiers)
            if b:
                out['FRA-018'].append(dict(base, charged=str(logic.money(l['admin_fee_amount'])), allowed=str(b[1]),
                                           overcharge=str(b[0])))
    if rate is not None:
        for i in _rows(db, """SELECT i.*, l.loan_ref, c.client_ref, c.full_name AS client_name, l.branch_code
                              FROM ln_instalments i JOIN ln_loans l ON l.id = i.loan_id
                              JOIN ln_clients c ON c.id = l.client_id WHERE i.penalty_charged > 0"""):
            b = logic.penalty_overcharge(i, rate, pcap, today)
            if b:
                out['FRA-020'].append({'loan_id': i['loan_id'], 'loan_ref': i['loan_ref'], 'client_ref': i['client_ref'],
                                       'client_name': i['client_name'], 'branch': i['branch_code'],
                                       'instalment': i['seq'], 'charged': str(logic.money(i['penalty_charged'])),
                                       'allowed': str(b[1]), 'overcharge': str(b[0])})
    for code, cap_v, table, col in (('FRA-025', tcap, 'ln_transfers', 'transfer_date'),
                                    ('FRA-026', rcap, 'ln_reschedulings', 'resched_date')):
        if cap_v is None:
            continue
        for t in _rows(db, f"""SELECT t.*, l.loan_ref, c.client_ref, c.full_name AS client_name, l.branch_code
                               FROM {table} t JOIN ln_loans l ON l.id = t.loan_id
                               JOIN ln_clients c ON c.id = l.client_id"""):
            b = logic.flat_fee_overcharge(t['fee_amount'], cap_v)
            if b:
                out[code].append({'loan_id': t['loan_id'], 'loan_ref': t['loan_ref'], 'client_ref': t['client_ref'],
                                  'client_name': t['client_name'], 'branch': t['branch_code'], 'date': str(t[col]),
                                  'charged': str(logic.money(t['fee_amount'])), 'allowed': str(b[1]),
                                  'overcharge': str(b[0])})
    return out


def overcharge_by_client(breaches):
    """Total over-charge per client across all fee controls (refund list)."""
    totals = {}
    for code in ('FRA-017', 'FRA-018', 'FRA-020', 'FRA-025', 'FRA-026'):
        seen = set()
        for b in breaches.get(code, []):
            # FRA-017 and FRA-018 can both flag the same admin fee: count the larger once.
            key = (b['client_ref'], b['loan_id'], 'admin' if code in ('FRA-017', 'FRA-018') else code,
                   b.get('instalment'), b.get('date'))
            t = totals.setdefault(b['client_ref'], {'client_ref': b['client_ref'], 'client_name': b['client_name'],
                                                   'items': {}, 'total': logic.ZERO})
            t['items'][key] = max(t['items'].get(key, logic.ZERO), logic.D(b['overcharge']))
            seen.add(key)
    for t in totals.values():
        t['total'] = sum(t['items'].values(), logic.ZERO)
        t['count'] = len(t['items'])
        del t['items']
    return sorted(totals.values(), key=lambda x: -x['total'])


# ------------------------------------------------------------------ credit-study QA
def qa_scan(db=None):
    """Run the anomaly rules over all credit studies and refresh the QA queue.
    Returns the number of open flags."""
    db = db or get_db()
    studies = _rows(db, """SELECT s.*, COALESCE(s.officer_code, l.officer_code) AS officer_code
                           FROM ln_credit_studies s JOIN ln_loans l ON l.id = s.loan_id""")
    flags = logic.study_anomalies(studies, min_cost_lines=param('lending.min_cost_lines'))
    for loan_id, items in flags.items():
        for flag_type, detail in items:
            db.execute("""INSERT INTO ln_qa_flags (loan_id, flag_type, detail) VALUES (%s,%s,%s)
                          ON CONFLICT (loan_id, flag_type) DO UPDATE SET detail = EXCLUDED.detail""",
                       (loan_id, flag_type, detail))
    db.commit()
    return db.execute("SELECT count(*) AS n FROM ln_qa_flags WHERE status = 'open'").fetchone()['n']


def review_qa(flag_id, user_id, status, note):
    db = get_db()
    if status not in ('cleared', 'confirmed'):
        raise LendingError('unknown QA decision')
    db.execute("UPDATE ln_qa_flags SET status = %s, reviewed_by = %s, reviewed_at = %s, review_note = %s WHERE id = %s",
               (status, user_id, datetime.now(), note, flag_id))
    db.commit()


# ------------------------------------------------------------------ early repayment
def er_request(loan_id, settlement_amount, prepayment_fee, user_id, db=None):
    db = db or get_db()
    loan = get_loan(loan_id, db)
    if not loan or loan['status'] != 'disbursed':
        raise LendingError('early repayment is only possible on a disbursed loan')
    if logic.D(settlement_amount) is None:
        raise LendingError('settlement amount is required')
    er_id = db.execute("""INSERT INTO ln_early_repayments (loan_id, settlement_amount, prepayment_fee)
                          VALUES (%s,%s,%s) RETURNING id""",
                       (loan_id, logic.money(settlement_amount), logic.money(prepayment_fee or 0))).fetchone()['id']
    db.commit()
    er_disclose(er_id, db)
    return er_id


def er_disclose(er_id, db=None):
    """FRA-021: generate the written cost disclosure (original vs new cost)."""
    db = db or get_db()
    er = dict(db.execute("SELECT * FROM ln_early_repayments WHERE id = %s", (er_id,)).fetchone())
    remaining = _rows(db, "SELECT * FROM ln_instalments WHERE loan_id = %s AND status <> 'paid'", (er['loan_id'],))
    d = logic.early_repayment_disclosure(remaining, er['settlement_amount'], er['prepayment_fee'])
    db.execute("""UPDATE ln_early_repayments SET original_remaining_cost = %s, new_total_cost = %s,
                  disclosure_text_en = %s, disclosure_text_ar = %s, disclosed_at = %s,
                  status = CASE WHEN status = 'requested' THEN 'disclosed' ELSE status END WHERE id = %s""",
               (d['original_remaining_cost'], d['new_total_cost'], logic.disclosure_text(d, 'en'),
                logic.disclosure_text(d, 'ar'), datetime.now(), er_id))
    db.commit()
    return d


def er_consent(er_id, consent_signed, cost_acknowledged, consent_date, db=None):
    """FRA-022 / FRA-024: record the signed consent (file must be attached) and
    the client's acknowledgement of the cost impact."""
    from attachments.service import list_attachments
    db = db or get_db()
    er = db.execute("SELECT * FROM ln_early_repayments WHERE id = %s", (er_id,)).fetchone()
    if not er or er['status'] not in ('disclosed', 'consented'):
        raise LendingError('generate the disclosure first')
    if consent_signed and not list_attachments(MODULE, 'ln_early_repayment', er_id):
        raise LendingError('attach the signed consent before recording it')
    db.execute("""UPDATE ln_early_repayments SET consent_signed = %s, cost_acknowledged = %s, consent_date = %s,
                  status = CASE WHEN %s AND %s THEN 'consented' ELSE 'disclosed' END WHERE id = %s""",
               (bool(consent_signed), bool(cost_acknowledged), consent_date or date.today(),
                bool(consent_signed), bool(cost_acknowledged), er_id))
    db.commit()


def er_execute(er_id, user_id, db=None):
    db = db or get_db()
    er = db.execute("SELECT * FROM ln_early_repayments WHERE id = %s", (er_id,)).fetchone()
    if not er:
        raise LendingError('early repayment not found')
    if not er['disclosed_at']:
        raise LendingError('the written cost disclosure has not been generated')
    if not er['consent_signed'] or not er['cost_acknowledged']:
        raise LendingError('signed client consent and cost acknowledgement are required before execution')
    if er['status'] == 'executed':
        raise LendingError('already executed')
    now = datetime.now()
    db.execute("UPDATE ln_early_repayments SET status = 'executed', executed_at = %s, executed_by = %s WHERE id = %s",
               (now, user_id, er_id))
    db.execute("UPDATE ln_loans SET status = 'closed', outstanding_principal = 0, updated_at = %s WHERE id = %s",
               (now, er['loan_id']))
    db.execute("UPDATE ln_instalments SET status = 'paid', paid_date = %s WHERE loan_id = %s AND status <> 'paid'",
               (now.date(), er['loan_id']))
    db.commit()


def refinance_hits(db=None):
    """FRA-023 pattern hits; also registers each one as an AML unusual-transaction candidate."""
    db = db or get_db()
    window = param('lending.prepay_new_loan_window_days')
    if window is None:
        return None
    ers = _rows(db, "SELECT * FROM ln_early_repayments WHERE status = 'executed'")
    loans = _rows(db, "SELECT * FROM ln_loans")
    hits = logic.costlier_refinance(ers, loans, window)
    if hits:
        from aml.unusual import register_candidate
        clients = {c['id']: c for c in _rows(db, "SELECT * FROM ln_clients WHERE id = ANY(%s)",
                                               (list({h['client_id'] for h in hits}),))}
        by_id = {l['id']: l for l in loans}
        for h in hits:
            c = clients.get(h['client_id'], {})
            uid, _ = register_candidate(
                source_module='lending', detection_rule='prepay_costlier_new_loan', source_table='ln_early_repayments',
                source_record_id=h['early_repayment_id'], party_id=c.get('party_id'), subject_name=c.get('full_name'),
                subject_ref=c.get('client_ref'), amount=by_id[h['new_loan_id']]['amount'],
                description=(f"Early repayment of {by_id[h['old_loan_id']]['loan_ref']} followed after {h['days']} day(s) "
                             f"by {by_id[h['new_loan_id']]['loan_ref']} ({h['reason']})"),
                study_sla_days=param('aml.unusual_txn_study_sla_days'), db=db)
            h['aml_ref'] = uid
            h['old_ref'], h['new_ref'] = by_id[h['old_loan_id']]['loan_ref'], by_id[h['new_loan_id']]['loan_ref']
            h['client_ref'] = c.get('client_ref')
    return hits


# ------------------------------------------------------------------ disclosure (FRA-019)
def pricing_disclosure(start, end, db=None):
    db = db or get_db()
    return _rows(db, """
        SELECT COALESCE(l.product_code, '-') AS product_code, p.name_en, p.name_ar, count(*) AS loans,
               sum(l.amount) AS total_amount, round(avg(l.interest_rate_pct), 2) AS avg_rate,
               min(l.interest_rate_pct) AS min_rate, max(l.interest_rate_pct) AS max_rate,
               round(avg(l.apr_pct), 2) AS avg_apr, max(l.apr_pct) AS max_apr,
               round(avg(CASE WHEN l.amount > 0 THEN l.admin_fee_amount / l.amount * 100 END), 2) AS avg_admin_fee_pct,
               round(max(CASE WHEN l.amount > 0 THEN l.admin_fee_amount / l.amount * 100 END), 2) AS max_admin_fee_pct,
               max(ct.penalty_clause_rate_pct) AS penalty_rate, max(ct.penalty_clause_cap_pct) AS penalty_cap
        FROM ln_loans l LEFT JOIN ln_products p ON p.code = l.product_code
        LEFT JOIN ln_contracts ct ON ct.loan_id = l.id
        WHERE l.disbursement_date BETWEEN %s AND %s
        GROUP BY COALESCE(l.product_code, '-'), p.name_en, p.name_ar ORDER BY 1
    """, (start, end))


def disclosure_submissions(db=None):
    db = db or get_db()
    try:
        return _rows(db, """SELECT s.* FROM regulatory_report_submissions s JOIN regulatory_reports r ON r.id = s.report_id
                            WHERE r.report_code = 'FRA-RPD' ORDER BY s.due_date DESC""")
    except Exception:
        db.rollback()
        return []


# ------------------------------------------------------------------ party registry
def ensure_party(client_id, db=None):
    """Link a lending client to the Entity-360 party registry (role LENDING_CLIENT)."""
    db = db or get_db()
    c = dict(db.execute("SELECT * FROM ln_clients WHERE id = %s", (client_id,)).fetchone())
    if c['party_id']:
        return c['party_id']
    from models.party import Party, PartyLink
    party = Party.find_by_id_number_hash(c['national_id_hash']) if c['national_id_hash'] else None
    party_id = party['id'] if party else Party.create(
        'ENTITY' if c['client_type'] == 'entity' else 'INDIVIDUAL', c['full_name'],
        id_type='NATIONAL_ID' if c['national_id_hash'] else None,
        id_number_hash=c['national_id_hash'] if c['client_type'] == 'individual' else None,
        cr_number_hash=c['national_id_hash'] if c['client_type'] == 'entity' else None, phone=c['phone'])
    PartyLink.create(party_id, MODULE, 'ln_clients', client_id, 'LENDING_CLIENT')
    db.execute("UPDATE ln_clients SET party_id = %s WHERE id = %s", (party_id, client_id))
    db.commit()
    return party_id
