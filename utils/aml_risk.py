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

def calculate_risk_score(data):
    """
    Calculate AML risk score based on customer data.
    Returns a dictionary with score, classification, and breakdown.
    """
    score = 0
    reasons = []
    
    # 1. Geographic Risk (Country)
    high_risk_countries = ['IRAN', 'NORTH KOREA', 'SYRIA', 'RUSSIA', 'MYANMAR']
    country = data.get('country', '').upper()
    if country in high_risk_countries:
        score += 50
        reasons.append(f"High Risk Country: {country}")
    elif country != 'EGYPT':
        score += 10
        reasons.append(f"Foreign Country: {country}")
        
    # 2. Customer Type Risk
    customer_type = data.get('customer_type')
    if customer_type == 'CORPORATE':
        score += 10
        reasons.append("Corporate Entity")
        
    # 3. Occupation / Activity Risk
    high_risk_activities = ['REAL ESTATE', 'JEWELRY', 'LEGAL', 'ACCOUNTING', 'GAMBLING', 'CHARITY']
    activity = (data.get('business_activity') or data.get('occupation') or '').upper()
    if any(risk in activity for risk in high_risk_activities):
        score += 30
        reasons.append(f"High Risk Activity: {activity}")
        
    # 5. Financial Profile
    # Check both keys because form uses 'income' but model might expect 'annual_income_range'
    income = data.get('annual_income_range') or data.get('income')
    
    if income == '>500K':
        score += 10
        reasons.append("High Income/Turnover")
    elif income == 'UNDECLARED': # Placeholder if we add this option
        score += 20
        reasons.append("Undeclared Income")
        
    # Determine Classification
    if score >= 70:
        classification = 'HIGH'
    elif score >= 30:
        classification = 'MEDIUM'
    else:
        classification = 'LOW'
        
    return {
        'score': score,
        'classification': classification,
        'reasons': reasons
    }
