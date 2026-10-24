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
Transaction Monitoring Service - Rule Engine
Evaluates transactions against configured rules and raises alerts
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from database.db import get_db

# High-risk countries (FATF blacklist + greylist)
HIGH_RISK_COUNTRIES = {
    'Iran', 'North Korea', 'Myanmar', 'Afghanistan', 'Syria',
    'Yemen', 'Libya', 'Somalia', 'Sudan', 'Iraq', 'Mali',
    'Burkina Faso', 'Haiti', 'Laos', 'South Sudan', 'Tanzania',
    'Vietnam', 'Nigeria', 'Pakistan', 'Philippines'
}

def get_active_rules(db):
    rules = db.execute("SELECT * FROM tm_rules WHERE is_active = 1").fetchall()
    return [dict(r) for r in rules]

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
        (alert_reference, rule_id, customer_id, alert_date, alert_description,
         triggered_transactions, alert_severity, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'NEW')
        RETURNING id
    """, (
        ref, rule['id'], customer_id, datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
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
        import logging
        logging.getLogger(__name__).exception('Could not score tm_alert %s', alert_id)
    db.execute("""
        UPDATE transactions SET alert_raised=1, alert_status='OPEN', rule_triggered=%s
        WHERE id = %s
    """, (rule['rule_code'], transaction_id))
    db.commit()

    try:
        from models.case import Case
        Case.sync_from_source('TM_ALERT', alert_id)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Failed to sync case registry for tm_alert %s', alert_id)

    return ref

def evaluate_transaction(transaction_id, db=None):
    """
    Main entry point: evaluate a transaction against all active rules.
    Returns list of alert references created.
    """
    close_db_after = False
    if db is None:
        db = get_db()
        close_db_after = True

    tx_row = db.execute("SELECT * FROM transactions WHERE id = %s", (transaction_id,)).fetchone()
    if not tx_row:
        return []
    tx = dict(tx_row)

    rules = get_active_rules(db)
    customer = get_customer(db, tx['customer_id'])
    if not customer:
        return []

    alerts_raised = []

    for rule in rules:
        code = rule['rule_code']
        triggered = False
        description = ''

        # TM001 - Large Cash Transaction
        if code == 'TM001':
            if tx['transaction_type'] in ('CASH_DEPOSIT', 'CASH_WITHDRAWAL') and \
               float(tx['amount']) >= float(rule['threshold_value']):
                triggered = True
                description = f"Cash transaction of {tx['amount']} {tx['currency']} exceeds threshold of {rule['threshold_value']}"

        # TM002 - Structuring
        elif code == 'TM002':
            since = (datetime.now(timezone.utc) - timedelta(days=rule['time_period_days'])).strftime('%Y-%m-%d')
            related = db.execute("""
                SELECT id, amount FROM transactions
                WHERE customer_id=%s AND transaction_type IN ('CASH_DEPOSIT','CASH_WITHDRAWAL')
                AND amount < %s AND amount >= %s AND transaction_date >= %s
            """, (tx['customer_id'], float(rule['threshold_value']) * 1.2, float(rule['threshold_value']) * 0.7, since)).fetchall()
            if len(related) >= 3:
                triggered = True
                total = sum(float(r['amount']) for r in related)
                description = f"Possible structuring: {len(related)} cash transactions totalling {total:.2f} below threshold within {rule['time_period_days']} days"

        # TM003 - High Velocity
        elif code == 'TM003':
            since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
            count = db.execute("""
                SELECT COUNT(*) as cnt FROM transactions
                WHERE customer_id=%s AND transaction_date >= %s
            """, (tx['customer_id'], since)).fetchone()['cnt']
            if count > int(rule['threshold_value']):
                triggered = True
                description = f"High velocity: {count} transactions in last 24 hours (threshold: {int(rule['threshold_value'])})"

        # TM004 - High Risk Country
        elif code == 'TM004':
            country = (tx.get('counterparty_country') or '').strip()
            if country in HIGH_RISK_COUNTRIES:
                triggered = True
                description = f"Transaction with high-risk country: {country}"

        # TM005 - PEP Counterparty
        elif code == 'TM005':
            if tx.get('pep_involvement') or tx.get('sanctions_hit'):
                triggered = True
                description = f"Counterparty flagged: PEP={tx.get('pep_name','')}, Sanctions={tx.get('sanctions_list','')}"

        # TM006 - Dormant Account
        elif code == 'TM006':
            since = (datetime.now(timezone.utc) - timedelta(days=rule['time_period_days'])).strftime('%Y-%m-%d')
            prev = db.execute("""
                SELECT COUNT(*) as cnt FROM transactions
                WHERE customer_id=%s AND transaction_date < %s AND id != %s
            """, (tx['customer_id'], since, tx['id'])).fetchone()['cnt']
            if prev == 0 and float(tx['amount']) >= float(rule['threshold_value']):
                triggered = True
                description = f"Dormant account activity: no transactions in {rule['time_period_days']} days, now {tx['amount']} {tx['currency']}"

        # TM007 - Rapid Round Trip
        elif code == 'TM007':
            if tx['transaction_type'] in ('TRANSFER_IN', 'CREDIT'):
                since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
                outgoing = db.execute("""
                    SELECT id FROM transactions
                    WHERE customer_id=%s AND transaction_type IN ('TRANSFER_OUT','DEBIT')
                    AND ABS(amount - %s) < (%s * 0.05)
                    AND transaction_date >= %s
                """, (tx['customer_id'], float(tx['amount']), float(tx['amount']), since)).fetchall()
                if outgoing:
                    triggered = True
                    description = f"Rapid round trip: funds of {tx['amount']} received and sent within 24 hours"

        # TM008 - Unusual Volume
        elif code == 'TM008':
            since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')
            monthly = db.execute("""
                SELECT COALESCE(SUM(amount),0) as total FROM transactions
                WHERE customer_id=%s AND transaction_date >= %s
            """, (tx['customer_id'], since)).fetchone()['total']
            expected_map = {'<50K': 50000, '50K-100K': 100000, '100K-500K': 500000, '>500K': 2000000, 'UNDECLARED': 50000}
            expected = expected_map.get(customer.get('annual_income_range', 'UNDECLARED'), 50000) / 12
            if float(monthly) > float(expected) * float(rule['threshold_value']):
                triggered = True
                description = f"Monthly volume {monthly:.2f} exceeds {rule['threshold_value']}x expected ({expected:.2f})"

        # TM009 - Multiple Currencies
        elif code == 'TM009':
            since = (datetime.now(timezone.utc) - timedelta(days=rule['time_period_days'])).strftime('%Y-%m-%d')
            currencies = db.execute("""
                SELECT COUNT(DISTINCT currency) as cnt FROM transactions
                WHERE customer_id=%s AND transaction_date >= %s
            """, (tx['customer_id'], since)).fetchone()['cnt']
            if currencies > int(rule['threshold_value']):
                triggered = True
                description = f"Multiple currencies: {currencies} different currencies used in {rule['time_period_days']} days"

        # TM010 - Frequent International Transfers
        elif code == 'TM010':
            since = (datetime.now(timezone.utc) - timedelta(days=rule['time_period_days'])).strftime('%Y-%m-%d')
            intl = db.execute("""
                SELECT COUNT(*) as cnt FROM transactions
                WHERE customer_id=%s AND transaction_type IN ('TRANSFER_OUT','TRANSFER_IN')
                AND counterparty_country IS NOT NULL AND counterparty_country != ''
                AND transaction_date >= %s
            """, (tx['customer_id'], since)).fetchone()['cnt']
            if intl > int(rule['threshold_value']):
                triggered = True
                description = f"Frequent international transfers: {intl} in {rule['time_period_days']} days"

        # TM011 - Card Used at Multiple POS Locations
        elif code == 'TM011':
            pan = tx.get('counterparty_account', '')
            if pan and len(pan) >= 6:
                since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
                # Count distinct merchants where this card was used in last 24h
                distinct_merchants = db.execute("""
                    SELECT COUNT(DISTINCT counterparty_name) as cnt
                    FROM transactions
                    WHERE counterparty_account = %s
                    AND transaction_date >= %s
                    AND counterparty_name IS NOT NULL
                    AND counterparty_name != ''
                """, (pan, since)).fetchone()['cnt']
                threshold = int(rule['threshold_value'] or 3)
                if distinct_merchants >= threshold:
                    triggered = True
                    masked = pan[:6] + '***' + pan[-4:] if len(pan) > 10 else pan
                    description = (
                        f"Card {masked} used at {distinct_merchants} different POS locations "
                        f"within 24 hours (threshold: {threshold}). "
                        f"Possible card skimming, cloning, or unauthorized sharing."
                    )

        # TM012 - Large POS Payment
        elif code == 'TM012':
            if tx.get('transaction_type') == 'PAYMENT':
                threshold = float(rule['threshold_value'] or 50000)
                if float(tx.get('amount') or 0) >= threshold:
                    triggered = True
                    description = (f"Large POS payment of {tx['amount']:,.2f} EGP exceeds "
                                   f"threshold of {threshold:,.0f} EGP at {tx.get('counterparty_name','unknown merchant')}.")

        # TM013 - Large Merchant Settlement
        elif code == 'TM013':
            if tx.get('transaction_type') == 'TRANSFER_IN':
                threshold = float(rule['threshold_value'] or 100000)
                if float(tx.get('amount') or 0) >= threshold:
                    triggered = True
                    description = (f"Large merchant settlement of {tx['amount']:,.2f} EGP "
                                   f"exceeds threshold of {threshold:,.0f} EGP.")

        # TM014 - High Refund Velocity
        elif code == 'TM014':
            if tx.get('transaction_type') == 'REFUND':
                try:
                    tx_dt = datetime.fromisoformat(str(tx['transaction_date']).replace('Z',''))
                except Exception:
                    tx_dt = datetime.now(timezone.utc)
                since = (tx_dt - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
                refund_count = db.execute("""
                    SELECT COUNT(*) as cnt FROM transactions
                    WHERE customer_id=%s AND transaction_type='REFUND'
                    AND transaction_date >= %s
                """, (tx['customer_id'], since)).fetchone()['cnt']
                threshold = int(rule['threshold_value'] or 3)
                if refund_count >= threshold:
                    triggered = True
                    description = (f"High refund velocity: {refund_count} refunds within 24 hours "
                                   f"(threshold: {threshold}). Possible refund fraud.")

        # TM015 - Round Number POS Structuring
        elif code == 'TM015':
            if tx.get('transaction_type') == 'PAYMENT':
                amount = float(tx.get('amount') or 0)
                if amount >= 1000 and amount % 1000 == 0:
                    try:
                        tx_dt = datetime.fromisoformat(str(tx['transaction_date']).replace('Z',''))
                    except Exception:
                        tx_dt = datetime.now(timezone.utc)
                    since = tx_dt.strftime('%Y-%m-%d 00:00:00')
                    round_count = db.execute("""
                        SELECT COUNT(*) as cnt FROM transactions
                        WHERE customer_id=%s AND transaction_type='PAYMENT'
                        AND amount >= 1000 AND MOD(amount::numeric, 1000) = 0
                        AND transaction_date >= %s
                    """, (tx['customer_id'], since)).fetchone()['cnt']
                    threshold = int(rule['threshold_value'] or 3)
                    if round_count >= threshold:
                        triggered = True
                        description = (f"Round number structuring: {round_count} round-number payments "
                                       f"today totaling potential structuring activity. Amount: {amount:,.0f} EGP.")

        # TM016 - Rapid Successive Card Payments
        elif code == 'TM016':
            pan = tx.get('counterparty_account', '')
            if pan and len(pan) >= 6 and tx.get('transaction_type') == 'PAYMENT':
                try:
                    tx_dt = datetime.fromisoformat(str(tx['transaction_date']).replace('Z',''))
                except Exception:
                    tx_dt = datetime.now(timezone.utc)
                since = (tx_dt - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
                rapid_count = db.execute("""
                    SELECT COUNT(*) as cnt FROM transactions
                    WHERE counterparty_account=%s AND transaction_type='PAYMENT'
                    AND transaction_date >= %s
                """, (pan, since)).fetchone()['cnt']
                threshold = int(rule['threshold_value'] or 5)
                if rapid_count >= threshold:
                    triggered = True
                    masked = pan[:6] + '***' + pan[-4:] if len(pan) > 10 else pan
                    description = (f"Rapid card payments: card {masked} used {rapid_count} times "
                                   f"within 1 hour (threshold: {threshold}). Possible card testing or fraud.")

        if triggered:
            # Check if alert already exists for same rule + customer in last 24h
            existing = db.execute("""
                SELECT id FROM tm_alerts
                WHERE rule_id=%s AND customer_id=%s 
                AND alert_date >= %s AND status NOT IN ('CLOSED','FALSE_POSITIVE')
            """, (rule['id'], tx['customer_id'],
                  (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'))).fetchone()
            if not existing:
                ref = create_alert(db, rule, tx['customer_id'], tx['id'],
                                  description, [tx['id']])
                alerts_raised.append({'rule': code, 'alert_ref': ref, 'severity': rule['severity']})

    if close_db_after:
        db.close()

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
