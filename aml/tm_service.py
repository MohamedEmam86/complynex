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

# Kept for callers that import it; the engine reads the high_risk_countries table.
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


def load_history(db, tx, rules):
    """The customer's transactions in the look-back the rules need (up to this one),
    plus the same card's transactions for the card rules."""
    ts = E.parse_ts(tx.get('transaction_date'))
    start = (ts - timedelta(days=E.max_lookback_days(rules))).strftime('%Y-%m-%d')
    end = ts.strftime('%Y-%m-%d')
    rows = db.execute(f"SELECT {_TX_COLS} FROM transactions WHERE customer_id = %s "
                      "AND substr(transaction_date, 1, 10) BETWEEN %s AND %s",
                      (tx['customer_id'], start, end)).fetchall()
    txs = {r['id']: dict(r) for r in rows}
    card = (tx.get('counterparty_account') or '').strip()
    if len(card) >= 6:
        day = (ts - timedelta(days=2)).strftime('%Y-%m-%d')
        for r in db.execute(f"SELECT {_TX_COLS} FROM transactions WHERE counterparty_account = %s "
                            "AND substr(transaction_date, 1, 10) BETWEEN %s AND %s",
                            (card, day, end)).fetchall():
            txs.setdefault(r['id'], dict(r))
    txs[tx['id']] = tx
    return list(txs.values())


def evaluate_transaction(transaction_id, db=None):
    """
    Main entry point: evaluate a transaction against all rule versions in force.
    Returns list of alert references created.
    """
    close_db_after = False
    if db is None:
        db = get_db()
        close_db_after = True
    try:
        return _evaluate(db, transaction_id)
    finally:
        if close_db_after:
            db.close()


def _evaluate(db, transaction_id):
    tx_row = db.execute(f"SELECT {_TX_COLS} FROM transactions WHERE id = %s", (transaction_id,)).fetchone()
    if not tx_row:
        return []
    tx = dict(tx_row)
    # data quality before rules run (TM-G1): no usable date or amount -> not monitored
    if E.parse_ts(tx.get('transaction_date')) is None or (E._num(tx.get('amount')) or 0) <= 0:
        log.warning('Transaction %s not monitored: no usable date or amount', transaction_id)
        return []
    customer = get_customer(db, tx['customer_id'])
    if not customer:
        return []
    E.ensure_packs_loaded()
    rules = [r for r in get_active_rules(db) if E.supported(r.get('rule_code'))]
    if not rules:
        return []
    hist = E.History(load_history(db, tx, rules))
    ctx = E.Context(E.load_high_risk(db))

    alerts_raised = []
    for rule in rules:
        try:
            hit = E.evaluate(rule, tx, hist, customer, ctx)
        except Exception:
            log.exception('TM rule %s failed on transaction %s', rule.get('rule_code'), transaction_id)
            continue
        if not hit:
            continue
        # One open alert per rule + customer for 24 hours: a new hit joins it.
        existing = db.execute("""
            SELECT id, triggered_transactions FROM tm_alerts
            WHERE rule_id=%s AND customer_id=%s
            AND alert_date >= %s AND status NOT IN ('CLOSED','FALSE_POSITIVE','SAR_CREATED')
        """, (rule['id'], tx['customer_id'],
              (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'))).fetchone()
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
                db.commit()
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
