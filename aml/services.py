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

from datetime import datetime
from database.db import get_db

def calculate_customer_risk(customer_id, user_id=None):
    """Re-rate one customer: the scoring model on the stored profile, then the
    HIGH floor (PEP, screening link, high-risk country) and EDD — see aml/edd.py.
    Returns (risk_score, risk_classification)."""
    from utils.aml_risk import calculate_risk_score
    from .edd import reassess
    db = get_db()
    row = db.execute("SELECT * FROM customers WHERE id = %s", (customer_id,)).fetchone()
    if not row:
        return 0, 'LOW'
    c = dict(row)
    model = calculate_risk_score({'country': c.get('country') or '', 'customer_type': c.get('customer_type'),
                                  'business_activity': c.get('business_activity'), 'occupation': c.get('occupation'),
                                  'annual_income_range': c.get('annual_income_range')})
    db.execute("UPDATE customers SET risk_score = %s WHERE id = %s", (model['score'], customer_id))
    db.commit()
    res = reassess(customer_id, user_id, model_class=model['classification'])
    return model['score'], (res or {}).get('classification', model['classification'])

def analyze_transaction_pattern(customer_id):
    """
    Run TM rules against customer transactions.
    (Stub for Phase 9.1 delivery)
    """
    return []
