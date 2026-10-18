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

def calculate_customer_risk(customer_id):
    """
    Calculate customer risk score based on seeded risk factors.
    Returns (risk_score, risk_classification)
    """
    db = get_db()
    
    # 1. Get base risk factors
    cursor = db.execute("SELECT id, risk_weight, is_edd_trigger FROM cdd_risk_factors WHERE is_active = 1")
    factors = cursor.fetchall()
    
    total_score = 0
    requires_edd = False
    
    # 2. Check customer attributes
    cursor = db.execute("SELECT is_pep, nationality FROM customers WHERE id = %s", (customer_id,))
    customer = cursor.fetchone()
    
    if not customer:
        return 0, 'LOW'
        
    is_pep, nationality = customer
    
    # Check if nationality is high risk
    is_hrc = False
    if nationality:
        hrc_check = db.execute("SELECT id FROM high_risk_countries WHERE country_name = %s AND is_active = 1", (nationality,)).fetchone()
        if hrc_check:
            is_hrc = True

    if is_pep:
        total_score += 50
        requires_edd = True
    if is_hrc:
        total_score += 30
        requires_edd = True
        
    # Classification logic
    classification = 'LOW'
    if total_score >= 80 or requires_edd:
        classification = 'HIGH'
    elif total_score >= 40:
        classification = 'MEDIUM'
        
    # Update customer record
    db.execute("""
        UPDATE customers 
        SET risk_score = %s, 
            risk_classification = %s, 
            requires_edd = %s,
            risk_classification_date = CURRENT_DATE
        WHERE id = %s
    """, (total_score, classification, 1 if requires_edd else 0, customer_id))
    db.commit()
    
    return total_score, classification

def analyze_transaction_pattern(customer_id):
    """
    Run TM rules against customer transactions.
    (Stub for Phase 9.1 delivery)
    """
    return []
