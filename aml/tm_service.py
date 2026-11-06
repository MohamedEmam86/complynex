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
Transaction Monitoring Service - live monitoring.

evaluate_transaction() runs every rule version in force (aml/tm_versions.py)
through the shared rule engine (aml/tm_engine.py) on one transaction, with the
customer's look-back history (and the card's, for card rules) loaded once, and
raises or extends alerts. The same engine drives the backtest and simulation
pages, so a rule fires live exactly as it did in its backtest.
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from database.db import get_db

from aml import tm_engine as E

log = logging.getLogger(__name__)

# Kept for callers that import it; the engine reads the high_risk_countries table
# (this built-in list of the risk model is used only when that table cannot be read).
HIGH_RISK_COUNTRIES = E.FALLBACK_HIGH_RISK

_TX_COLS = ("id, transaction_reference, customer_id, transaction_date, transaction_type, amount, currency, "
            "counterparty_name, counterparty_account, counterparty_country, pep_involvement, pep_name, "
            "sanctions_hit, sanctions_list, alert_raised, created_at")


def get_active_rules(db):
    from aml.tm_versions import active_rules
    return active_rules(db)


def get_customer_transactions(db, customer_id, days=30):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    rows = db.execute("""
        SELECT * FROM transactions
        WHERE customer_id = %s AND transaction_date >= %s
        ORDER BY transaction_date DESC
    """, (customer_id, since)).fetchall()
    return [dict(r) for r in rows]


def get_customer(db, customer_id):
    row = db.execute("SELECT * FROM customers WHERE id = %s", (customer_id,)).fetchone()
    return dict(row) if row else None


def create_alert(db, rule, customer_id, transaction_id, description, triggered_txs):
    ref = f"ALT-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{str(uuid.uuid4()).replace('-','')[:12].upper()}"
    cursor = db.execute("""
        INSERT INTO tm_alerts
        (alert_reference, rule_id, rule_code, rule_version, customer_id, alert_date, alert_description,
         triggered_transactions, alert_severity, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'NEW')
        RETURNING id
    """, (
        ref, rule['id'], rule.get('rule_code'), rule.get('version'), customer_id,
        datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        description, json.dumps(triggered_txs), rule['severity']
    ))
    alert_id = cursor.fetchone()['id']
    try:
        from aml.tm_alerts import alert_score
        ids = [t for t in (triggered_txs or []) if str(t).isdigit()]
        scores = [r['risk_score'] for r in db.execute(
            "SELECT risk_score FROM transactions WHERE id = ANY(%s)", ([int(i) for i in ids],)).fetchall()] if ids else []
        db.execute("UPDATE tm_alerts SET risk_score = %s WHERE id = %s", (alert_score(rule['severity'], scores), alert_id))
    except Exception:
        log.exception('Could not score tm_alert %s', alert_id)
    db.execute("""
        UPDATE transactions SET alert_raised=1, alert_status='OPEN', rule_triggered=%s
        WHERE id = %s
    """, (rule['rule_code'], transaction_id))
    db.commit()

    try:
        from models.case import Case
        Case.sync_from_source('TM_ALERT', alert_id)
    except Exception:
        log.exception('Failed to sync case registry for tm_alert %s', alert_id)

    return ref


def _iso_day(d):
    return d.strftime('%Y-%m-%d')


def load_history(db, tx, rules):
    """The customer's transactions in the look-back the rules need (up to this one),
    plus the same card's transactions for the card rules (over the card rules' own
    look-back). Plain ISO range comparisons on transaction_date, served by the
    (customer_id, transaction_date) and (counterparty_account, transaction_date)
    indexes. Rows whose date is not stored as YYYY-MM-DD... are not found by the
    range: the data-quality report counts them (date_not_iso).
    Returns (transactions, prior) - prior = {(customer_id, day): bool} answers the
    dormant rule's "any activity before the quiet period" with one EXISTS query."""
    ts = tx['_ts']
    # one extra day each side: a row stored with a UTC offset can sit on the neighbouring
    # calendar day as text; the windows themselves use the parsed local time.
    start = _iso_day(ts - timedelta(days=E.max_lookback_days(rules) + 1))
    end = _iso_day(ts + timedelta(days=2))           # exclusive; later rows are never read by the windows
    rows = db.execute(f"SELECT {_TX_COLS} FROM transactions WHERE customer_id = %s "
                      "AND transaction_date >= %s AND transaction_date < %s",
                      (tx['customer_id'], start, end)).fetchall()
    txs = {r['id']: dict(r) for r in rows}
    card = (tx.get('counterparty_account') or '').strip()
    card_days = E.card_lookback_days(rules)
    if len(card) >= 6 and card_days > 0:
        cstart = _iso_day(ts - timedelta(days=card_days + 1))
        for r in db.execute(f"SELECT {_TX_COLS} FROM transactions WHERE counterparty_account = %s "
                            "AND transaction_date >= %s AND transaction_date < %s",
                            (card, cstart, end)).fetchall():
            txs.setdefault(r['id'], dict(r))
    txs[tx['id']] = tx
    prior = {}
    for r in E.prior_history_rules(rules):
        day = E.quiet_start(ts, E.rule_params(r)).date()
        if (tx['customer_id'], day) in prior:
            continue
        # strictly before the day the quiet period starts (minus the spare day, which is in the
        # loaded look-back together with that day itself)
        row = db.execute("SELECT EXISTS (SELECT 1 FROM transactions WHERE customer_id = %s "
                         "AND transaction_date < %s AND transaction_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}') AS e",
                         (tx['customer_id'], _iso_day(day - timedelta(days=1)))).fetchone()
        prior[(tx['customer_id'], day)] = bool(row and row['e'])
    # the EXISTS bound above is the spare day; rows from it to `day` are in memory
    return list(txs.values()), prior


def record_issue(db, transaction_id, issue, detail=''):
    """Keep what live monitoring could not fully judge (shown on the data-quality page).
    One row per issue, detail and day, counting its occurrences (an upload of thousands of
    USD rows is one line, not thousands). Written inside a savepoint: never breaks
    monitoring. Returns True when written."""
    detail = (detail or '')[:500]
    try:
        with E.savepoint(db, 'tm_issue'):
            row = db.execute("""UPDATE tm_monitoring_issues SET occurrences = occurrences + 1,
                                       last_transaction_id = %s, last_at = NOW()
                                 WHERE issue = %s AND detail = %s AND created_at >= CURRENT_DATE
                                 RETURNING id""", (transaction_id, issue, detail)).fetchone()
            if not row:
                db.execute("""INSERT INTO tm_monitoring_issues (transaction_id, issue, detail, last_transaction_id)
                              VALUES (%s, %s, %s, %s)""", (transaction_id, issue, detail, transaction_id))
        return True
    except Exception:
        log.exception('Could not record TM monitoring issue %s for transaction %s', issue, transaction_id)
        return False


MERGE_HOURS = 24
# Alerts in these statuses never take new transactions: closed ones are finished, and
# once an STR / SAR has been raised from an alert (SAR_CREATED) its transaction set is
# the evidence of that report and must not change; a later hit opens a new alert.
# Same list as the alert workflow's final statuses (aml/tm_alerts.py).
try:
    from aml.tm_alerts import CLOSED_STATUSES as NO_MERGE_STATUSES
except Exception:                     # pragma: no cover
    NO_MERGE_STATUSES = ('CLOSED', 'FALSE_POSITIVE', 'SAR_CREATED')
NO_MERGE_STATUSES = tuple(NO_MERGE_STATUSES)


def _open_alert_for(db, rule, customer_id, tx_ts):
    """The open alert of this rule (any version: matched by rule_code) and customer whose
    pattern started within MERGE_HOURS of this transaction's own date - the same grouping
    as the backtest, which also measures it on transaction dates, not on "now"."""
    rows = db.execute("""
        SELECT a.id, a.triggered_transactions, a.alert_date FROM tm_alerts a
         WHERE a.customer_id = %s AND a.status NOT IN %s
           AND (a.rule_code = %s OR (a.rule_code IS NULL AND a.rule_id IN (SELECT id FROM tm_rules WHERE rule_code = %s)))
         ORDER BY a.id DESC LIMIT 20""",
        (customer_id, NO_MERGE_STATUSES, rule['rule_code'], rule['rule_code'])).fetchall()
    if not rows:
        return None
    firsts = {}
    for r in rows:
        try:
            linked = json.loads(r['triggered_transactions'] or '[]')
        except (ValueError, TypeError):
            linked = []
        first = next((int(x) for x in linked if str(x).isdigit()), None)
        firsts[r['id']] = first
    ids = [i for i in firsts.values() if i is not None]
    dates = {}
    if ids:
        dates = {d['id']: E.parse_ts(d['transaction_date']) for d in db.execute(
            "SELECT id, transaction_date FROM transactions WHERE id = ANY(%s)", (ids,)).fetchall()}
    for r in rows:
        anchor = dates.get(firsts[r['id']]) or E.parse_ts(r['alert_date'])
        if anchor is not None and abs((tx_ts - anchor).total_seconds()) < MERGE_HOURS * 3600:
            return r
    return None


def evaluate_transaction(transaction_id, db=None, commit=True):
    """
    Main entry point: evaluate a transaction against all rule versions in force.
    Returns list of alert references created. _evaluate() itself never commits the
    caller's transaction (create_alert keeps its own historical commit); this entry point
    commits once at the end (alert links, data-quality records) unless commit=False -
    the existing callers (manual entry, upload, API) commit their insert before and
    nothing after.
    """
    close_db_after = False
    if db is None:
        db = get_db()
        close_db_after = True
    try:
        out = _evaluate(db, transaction_id)
        if commit:
            db.commit()
        return out
    finally:
        if close_db_after:
            db.close()


def _evaluate(db, transaction_id):
    tx_row = db.execute(f"SELECT {_TX_COLS} FROM transactions WHERE id = %s", (transaction_id,)).fetchone()
    if not tx_row:
        return []
    tx = dict(tx_row)
    customer = get_customer(db, tx['customer_id'])
    if not customer:
        return []
    E.ensure_packs_loaded()
    in_force = get_active_rules(db)
    E.warn_unsupported(in_force)
    rules = [r for r in in_force if E.supported(r.get('rule_code'))]
    if not rules:
        return []
    # data quality before rules run (TM-G1). A transaction whose date or amount cannot be
    # used still goes through the rules that do not need it (PEP / sanctions flag,
    # high-risk country, single-amount thresholds): never skip everything.
    ts = E.parse_ts(tx.get('transaction_date'))
    tx['_ts'] = ts
    amount = E._num(tx.get('amount'))
    issues = 0
    # zero is a usable amount (count rules count it; amount rules compare it); negative only
    # for a refund / reversal stored signed
    amount_ok = amount is not None and (amount >= 0 or (tx.get('transaction_type') or '').upper() in E.REVERSAL_TYPES)
    if ts is None:
        log.error('TM: transaction %s has an unreadable date (%r): only rules that need no date run',
                  transaction_id, tx.get('transaction_date'))
        issues += record_issue(db, transaction_id, 'date_unreadable', str(tx.get('transaction_date'))[:100])
    if not amount_ok:
        log.error('TM: transaction %s has no usable amount (%r): only the rules that need no amount run',
                  transaction_id, tx.get('amount'))
        issues += record_issue(db, transaction_id, 'amount_unusable', str(tx.get('amount'))[:100])
    runnable = [r for r in rules
                if (ts is not None or 'date' not in E.needs(r['rule_code']))
                and (amount_ok or 'amount' not in E.needs(r['rule_code']))]
    other_cur = sorted({r['rule_code'] for r in runnable if E.other_currency(r, tx)})
    if other_cur:
        # compared UNCONVERTED (fail safe: never skipped) - no exchange-rate table exists
        log.warning('TM: transaction %s in %s compared unconverted by %s', transaction_id,
                    (tx.get('currency') or '').upper(), ', '.join(other_cur))
        issues += record_issue(db, transaction_id, 'currency_unconverted',
                               f"{(tx.get('currency') or '').upper()} compared unconverted by {', '.join(other_cur)}")
    if ts is not None:
        txs, prior = load_history(db, tx, runnable)
        hist = E.History(txs, prior=prior)
    else:
        hist = E.History([])
    ctx = E.Context(E.load_high_risk(db))

    alerts_raised = []
    for rule in runnable:
        try:
            hit = E.evaluate(rule, tx, hist, customer, ctx)
        except Exception:
            log.exception('TM rule %s failed on transaction %s', rule.get('rule_code'), transaction_id)
            continue
        if not hit:
            continue
        # One open alert per rule + customer for a pattern of 24 hours (on transaction dates):
        # a new hit joins it.
        existing = _open_alert_for(db, rule, tx['customer_id'], ts) if ts is not None else None
        if existing:
            # The open alert covers the whole pattern: link this transaction to it
            # too, so the alert (and an STR raised from it) carries every
            # transaction and their total, not only the first one.
            try:
                linked = json.loads(existing['triggered_transactions'] or '[]')
            except (ValueError, TypeError):
                linked = []
            if str(tx['id']) not in [str(x) for x in linked]:
                linked.append(tx['id'])
                db.execute("UPDATE tm_alerts SET triggered_transactions = %s WHERE id = %s",
                           (json.dumps(linked), existing['id']))
        else:
            ref = create_alert(db, rule, tx['customer_id'], tx['id'], hit.description, [tx['id']])
            alerts_raised.append({'rule': rule['rule_code'], 'alert_ref': ref, 'severity': rule['severity']})
    return alerts_raised


def get_alert_stats(db):
    stats = {}
    stats['total_open'] = db.execute("SELECT COUNT(*) as count FROM tm_alerts WHERE status='NEW'").fetchone()['count']
    stats['total_investigating'] = db.execute("SELECT COUNT(*) as count FROM tm_alerts WHERE status='INVESTIGATING'").fetchone()['count']
    stats['total_escalated'] = db.execute("SELECT COUNT(*) as count FROM tm_alerts WHERE status='ESCALATED'").fetchone()['count']
    stats['high_severity'] = db.execute("SELECT COUNT(*) as count FROM tm_alerts WHERE alert_severity='HIGH' AND status NOT IN ('CLOSED','FALSE_POSITIVE')").fetchone()['count']
    stats['total_transactions'] = db.execute("SELECT COUNT(*) as count FROM transactions").fetchone()['count']
    stats['flagged_transactions'] = db.execute("SELECT COUNT(*) as count FROM transactions WHERE alert_raised=1").fetchone()['count']
    return stats
