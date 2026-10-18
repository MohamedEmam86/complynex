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
Data intake for Lending Conduct & Portfolio. ComplyNex is not the core lending
system: data arrives as CSV / Excel files (one file per record kind), through
the pack's JSON API (POST /api/v1/fra-nbfi/lending/import) or by manual entry.

Every kind is upserted on its natural key, so re-sending a file updates rows
instead of duplicating them. Rows that fail validation are reported with their
line number; valid rows in the same file are still imported. National ID
numbers are never stored — only their hash (EncryptionService.hash_value), as
elsewhere in ComplyNex.

Column reference: KINDS below; downloadable templates on the Import page and
in docs/packs/fra_nbfi/LENDING_IMPORT.md.
"""

import csv
import io
import json
from datetime import date, datetime

from database.db import get_db

from . import logic

# kind -> (required columns, optional columns)
KINDS = {
    'clients': (['client_ref', 'full_name'],
                ['client_type', 'national_id', 'gender', 'phone', 'address', 'governorate', 'business_activity',
                 'monthly_revenue', 'project_size']),
    'loans': (['loan_ref', 'client_ref', 'amount'],
              ['product_code', 'tenor_months', 'interest_rate_pct', 'apr_pct', 'admin_fee_amount', 'other_fees_amount',
               'branch_code', 'officer_code', 'status', 'application_date', 'approval_date', 'disbursement_date',
               'maturity_date', 'outstanding_principal', 'days_past_due', 'gps_lat', 'gps_lng', 'purpose']),
    'contracts': (['loan_ref'],
                  ['contract_no', 'contract_date', 'signed_by_lender', 'lender_signed_at', 'signed_by_client',
                   'client_signed_at', 'penalty_clause_rate_pct', 'penalty_clause_cap_pct']),
    'documents': (['loan_ref', 'doc_type'], ['received_date', 'reference_no', 'notes']),
    'credit_studies': (['loan_ref'],
                       ['study_date', 'officer_code', 'monthly_revenue', 'monthly_costs_total', 'cost_lines',
                        'household_expenses', 'other_debt_service', 'net_income', 'dsr_pct']),
    'instalments': (['loan_ref', 'seq', 'due_date'],
                    ['principal_due', 'interest_due', 'fees_due', 'paid_amount', 'paid_date', 'penalty_charged', 'status']),
    'visits': (['loan_ref'], ['planned_date', 'visit_date', 'officer_code', 'outcome', 'notes']),
    'early_repayments': (['loan_ref', 'settlement_amount'],
                         ['request_date', 'prepayment_fee', 'executed_date', 'consent_signed', 'cost_acknowledged',
                          'disclosure_given']),
    'reschedulings': (['loan_ref', 'resched_date'], ['fee_amount', 'old_tenor', 'new_tenor', 'reason']),
    'transfers': (['loan_ref', 'transfer_date'], ['instalments_moved', 'fee_amount']),
}

DATE_COLS = {'application_date', 'approval_date', 'disbursement_date', 'maturity_date', 'contract_date',
             'lender_signed_at', 'client_signed_at', 'received_date', 'study_date', 'due_date', 'paid_date',
             'planned_date', 'visit_date', 'request_date', 'executed_date', 'resched_date', 'transfer_date'}
NUM_COLS = {'amount', 'interest_rate_pct', 'apr_pct', 'admin_fee_amount', 'other_fees_amount', 'outstanding_principal',
            'gps_lat', 'gps_lng', 'monthly_revenue', 'project_size', 'monthly_costs_total', 'household_expenses',
            'other_debt_service', 'net_income', 'dsr_pct', 'principal_due', 'interest_due', 'fees_due', 'paid_amount',
            'penalty_charged', 'settlement_amount', 'prepayment_fee', 'fee_amount', 'penalty_clause_rate_pct',
            'penalty_clause_cap_pct'}
INT_COLS = {'tenor_months', 'days_past_due', 'seq', 'old_tenor', 'new_tenor', 'instalments_moved'}
BOOL_COLS = {'signed_by_lender', 'signed_by_client', 'consent_signed', 'cost_acknowledged', 'disclosure_given'}
LOAN_STATUSES = ('application', 'approved', 'disbursed', 'closed', 'written_off', 'rejected')


class RowError(ValueError):
    pass


# ------------------------------------------------------------------ parsing
def read_table(filename, data):
    """bytes of a .csv / .xlsx file -> list of dicts (header row lower-cased)."""
    name = (filename or '').lower()
    if name.endswith(('.xlsx', '.xlsm')):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        head = [str(h or '').strip().lower() for h in rows[0]]
        return [{head[i]: v for i, v in enumerate(r) if i < len(head) and head[i]} for r in rows[1:]
                if any(c not in (None, '') for c in r)]
    text = data.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(text))
    return [{(k or '').strip().lower(): v for k, v in r.items()} for r in reader if any((v or '').strip() for v in r.values())]


def _clean(kind, raw):
    req, opt = KINDS[kind]
    out = {}
    for col in req + opt:
        v = raw.get(col)
        if isinstance(v, str):
            v = v.strip()
        if v in (None, ''):
            if col in req:
                raise RowError(f'{col} is required')
            continue
        try:
            if col in DATE_COLS:
                v = v.date() if isinstance(v, datetime) else v if isinstance(v, date) else \
                    datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
            elif col in NUM_COLS:
                v = logic.D(v)
            elif col in INT_COLS:
                v = int(logic.D(v))
            elif col in BOOL_COLS:
                v = str(v).strip().lower() in ('1', 'true', 'yes', 'y', 'نعم')
            elif col == 'cost_lines':
                v = json.loads(v) if isinstance(v, str) else v
                if not isinstance(v, list):
                    raise ValueError
            else:
                v = str(v)
        except (ValueError, TypeError, ArithmeticError):
            kind_hint = 'YYYY-MM-DD' if col in DATE_COLS else 'a JSON list' if col == 'cost_lines' else 'a number'
            raise RowError(f'{col} must be {kind_hint}')
        out[col] = v
    if kind == 'loans' and out.get('status') and out['status'] not in LOAN_STATUSES:
        raise RowError('status must be one of ' + ', '.join(LOAN_STATUSES))
    return out


def template_csv(kind):
    req, opt = KINDS[kind]
    return ','.join(req + opt) + '\n'


# ------------------------------------------------------------------ upserts
def _loan_id(db, ref):
    r = db.execute("SELECT id FROM ln_loans WHERE loan_ref = %s", (ref,)).fetchone()
    if not r:
        raise RowError(f'unknown loan_ref {ref}')
    return r['id']


def _upsert(db, table, key_cols, row):
    cols = list(row)
    updates = [c for c in cols if c not in key_cols]
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
           f"ON CONFLICT ({', '.join(key_cols)}) DO " +
           (f"UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in updates)}" if updates else 'NOTHING') +
           " RETURNING id")
    r = db.execute(sql, tuple(row[c] for c in cols)).fetchone()
    return r['id'] if r else None


def _apply(db, kind, r, batch_id, source):
    if kind == 'clients':
        from data_protection.encryption_service import EncryptionService
        nid = r.pop('national_id', None)
        if nid:
            r['national_id_hash'] = EncryptionService.hash_value(nid)
        r.setdefault('client_type', 'individual')
        if r['client_type'] not in ('individual', 'entity'):
            raise RowError('client_type must be individual or entity')
        r['updated_at'] = datetime.now()
        return _upsert(db, 'ln_clients', ['client_ref'], r)
    if kind == 'loans':
        c = db.execute("SELECT id FROM ln_clients WHERE client_ref = %s", (r.pop('client_ref'),)).fetchone()
        if not c:
            raise RowError('unknown client_ref (import clients first)')
        r['client_id'] = c['id']
        r['source'], r['import_batch_id'], r['updated_at'] = source, batch_id, datetime.now()
        if r.get('status') == 'disbursed' and 'outstanding_principal' not in r:
            r['outstanding_principal'] = r['amount']
        return _upsert(db, 'ln_loans', ['loan_ref'], r)
    lid = _loan_id(db, r.pop('loan_ref'))
    r['loan_id'] = lid
    if kind == 'contracts':
        return _upsert(db, 'ln_contracts', ['loan_id'], r)
    if kind == 'documents':
        return _doc(db, r)
    if kind == 'credit_studies':
        r['cost_lines'] = json.dumps(r.get('cost_lines') or [])
        return _upsert(db, 'ln_credit_studies', ['loan_id'], r)
    if kind == 'instalments':
        return _upsert(db, 'ln_instalments', ['loan_id', 'seq'], r)
    if kind == 'visits':
        return db.execute("""INSERT INTO ln_visits (loan_id, planned_date, visit_date, officer_code, outcome, notes)
                             VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                          (lid, r.get('planned_date'), r.get('visit_date'), r.get('officer_code'), r.get('outcome'),
                           r.get('notes'))).fetchone()['id']
    if kind == 'early_repayments':
        executed = r.pop('executed_date', None)
        disclosed = r.pop('disclosure_given', False)
        status = 'executed' if executed else ('consented' if r.get('consent_signed') and r.get('cost_acknowledged')
                                              else 'disclosed' if disclosed else 'requested')
        return db.execute("""INSERT INTO ln_early_repayments (loan_id, request_date, settlement_amount, prepayment_fee,
                                 consent_signed, cost_acknowledged, disclosed_at, status, executed_at, source)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                          (lid, r.get('request_date') or executed or date.today(), r['settlement_amount'],
                           r.get('prepayment_fee') or 0, bool(r.get('consent_signed')),
                           bool(r.get('cost_acknowledged')),
                           datetime.combine(r.get('request_date') or executed or date.today(), datetime.min.time())
                           if disclosed else None, status,
                           datetime.combine(executed, datetime.min.time()) if executed else None,
                           source)).fetchone()['id']
    if kind == 'reschedulings':
        return db.execute("""INSERT INTO ln_reschedulings (loan_id, resched_date, fee_amount, old_tenor, new_tenor, reason)
                             VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                          (lid, r['resched_date'], r.get('fee_amount') or 0, r.get('old_tenor'), r.get('new_tenor'),
                           r.get('reason'))).fetchone()['id']
    if kind == 'transfers':
        return db.execute("""INSERT INTO ln_transfers (loan_id, transfer_date, instalments_moved, fee_amount)
                             VALUES (%s,%s,%s,%s) RETURNING id""",
                          (lid, r['transfer_date'], r.get('instalments_moved'), r.get('fee_amount') or 0)
                          ).fetchone()['id']
    raise RowError(f'unknown kind {kind}')


def _doc(db, r):
    existing = db.execute("SELECT id FROM ln_documents WHERE loan_id = %s AND doc_type = %s",
                          (r['loan_id'], r['doc_type'])).fetchone()
    if existing:
        db.execute("UPDATE ln_documents SET received_date = %s, reference_no = %s, notes = %s WHERE id = %s",
                   (r.get('received_date'), r.get('reference_no'), r.get('notes'), existing['id']))
        return existing['id']
    return db.execute("""INSERT INTO ln_documents (loan_id, doc_type, received_date, reference_no, notes)
                         VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                      (r['loan_id'], r['doc_type'], r.get('received_date'), r.get('reference_no'), r.get('notes'))
                      ).fetchone()['id']


def import_rows(kind, rows, *, source='file', filename=None, user_id=None, db=None):
    """Validate and upsert rows of one kind. Returns the ln_import_batches row (dict)."""
    if kind not in KINDS:
        raise ValueError(f'unknown kind {kind!r}; expected one of {", ".join(KINDS)}')
    db = db or get_db()
    batch_id = db.execute("INSERT INTO ln_import_batches (kind, source, filename, created_by) VALUES (%s,%s,%s,%s) "
                          "RETURNING id", (kind, source, filename, user_id)).fetchone()['id']
    db.commit()
    ok, errors, touched_loans = 0, [], set()
    for n, raw in enumerate(rows, start=1 if source == 'api' else 2):
        try:
            r = _clean(kind, {str(k).strip().lower(): v for k, v in (raw or {}).items()})
            ref = r.get('loan_ref')
            rid = _apply(db, kind, r, batch_id, source)
            db.commit()
            ok += 1
            if kind == 'loans':
                touched_loans.add(rid)
            elif ref:
                touched_loans.add(r.get('loan_id'))
        except RowError as e:
            db.rollback()
            errors.append({'line': n, 'error': str(e)})
        except Exception as e:  # constraint violations etc. — report, keep going
            db.rollback()
            errors.append({'line': n, 'error': str(e).splitlines()[0][:300]})
    db.execute("UPDATE ln_import_batches SET rows_total = %s, rows_ok = %s, rows_failed = %s, errors = %s WHERE id = %s",
               (len(rows), ok, len(errors), json.dumps(errors[:500]), batch_id))
    db.commit()
    from . import service
    if kind == 'clients':
        for c in db.execute("SELECT id FROM ln_clients WHERE party_id IS NULL").fetchall():
            try:
                service.ensure_party(c['id'], db)
            except Exception:
                db.rollback()
    for lid in touched_loans:
        if lid:
            service.refresh_file_status(lid, db)
    return dict(db.execute("SELECT * FROM ln_import_batches WHERE id = %s", (batch_id,)).fetchone())
