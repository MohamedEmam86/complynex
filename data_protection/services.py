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

from database.db import get_db

def calculate_breach_severity(breach_id):
    """
    Calculate breach severity based on affected individuals and sensitivity.
    Returns (severity_level, severity_score)
    """
    db = get_db()
    cursor = db.execute("SELECT * FROM data_breaches WHERE id = %s", (breach_id,))
    breach = cursor.fetchone()
    
    if not breach:
        return None, 0
        
    score = 0
    # Factors (Simplified for Phase 9.1)
    # affected_individuals_count
    count = breach['affected_individuals_count'] or 0
    if count > 1000: score += 40
    elif count > 100: score += 20
    else: score += 5
    
    # includes_sensitive_data
    if breach['includes_sensitive_data']:
        score += 50
        
    # Potential Harm
    harm = breach['potential_harm'] or ''
    if 'financia' in harm.lower(): score += 20
    
    severity = 'LOW'
    if score >= 80: severity = 'CRITICAL'
    elif score >= 50: severity = 'HIGH'
    elif score >= 20: severity = 'MEDIUM'
    
    db.execute("UPDATE data_breaches SET severity = %s, severity_score = %s WHERE id = %s", (severity, score, breach_id))
    db.commit()
    
    return severity, score

def check_pdpc_notification_requirement(breach_id):
    """
    Check if Egyptian Data Protection Center (PDPC) notification is required.
    PDPL Art. 32: Notification within 72 hours of discovery if breach involves sensitive data or large scale.
    """
    severity, score = calculate_breach_severity(breach_id)
    required = (severity in ['HIGH', 'CRITICAL'])
    
    if required:
        db = get_db()
        db.execute("UPDATE data_breaches SET pdpc_notification_required = 1 WHERE id = %s", (breach_id,))
        db.commit()
        
    return required
