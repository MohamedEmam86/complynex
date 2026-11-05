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
Customer risk score of the AML customers register (F1).

The model is DATA: country risk, customer type, activity keywords, income and
the score bands. DEFAULT_MODEL reproduces exactly the scoring used before the
model became configurable; the MLRO changes it on /aml/risk-scoring (versioned,
audited — aml/risk_config.py). Whether the country factor uses the built-in
list or the high-risk countries table (FATF) is a setting of the model, not a
code change: the default stays the built-in list.

The regulatory HIGH floor (PEP, screening link, high-risk country from the
table) is applied afterwards in aml/edd.py and is not part of this score.
"""
import copy

DEFAULT_MODEL = {
    'country': {
        # 'builtin' = the list below; 'table' = active rows of high_risk_countries; 'both' = either
        'source': 'builtin',
        'builtin_list': ['IRAN', 'NORTH KOREA', 'SYRIA', 'RUSSIA', 'MYANMAR'],
        'high_risk_points': 50,
        'home_country': 'EGYPT',
        'foreign_points': 10,
    },
    'customer_type_points': {'CORPORATE': 10},
    'activity': {'keywords': ['REAL ESTATE', 'JEWELRY', 'LEGAL', 'ACCOUNTING', 'GAMBLING', 'CHARITY'], 'points': 30},
    'income_points': {'>500K': 10, 'UNDECLARED': 20},
    'bands': {'HIGH': 70, 'MEDIUM': 30},
    # periodic review (F2): months between reviews per classification
    'review_months': {'HIGH': 12, 'MEDIUM': 24, 'LOW': 36},
    # reminders of reviews coming due (F2): off until the MLRO switches them on
    'reminders': {'enabled': False, 'days_before': 30},
}
COUNTRY_SOURCES = ('builtin', 'table', 'both')
CLASSES = ('HIGH', 'MEDIUM', 'LOW')


def merged(model=None):
    """The model with every missing key taken from DEFAULT_MODEL."""
    out = copy.deepcopy(DEFAULT_MODEL)
    for k, v in (model or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ('customer_type_points', 'income_points'):
            out[k].update(v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def validate(model):
    """Problems with a model (empty list = valid)."""
    m = merged(model)
    probs = []

    def pts(v, label):
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 100):
            probs.append(f'{label} must be a number between 0 and 100')

    c = m['country']
    if c.get('source') not in COUNTRY_SOURCES:
        probs.append('country source must be builtin, table or both')
    pts(c.get('high_risk_points'), 'high-risk country points')
    pts(c.get('foreign_points'), 'foreign country points')
    if not str(c.get('home_country') or '').strip():
        probs.append('the home country is required')
    if not isinstance(c.get('builtin_list'), list):
        probs.append('the built-in country list must be a list')
    for k, v in (m.get('customer_type_points') or {}).items():
        pts(v, f'customer type {k} points')
    pts(m['activity'].get('points'), 'high-risk activity points')
    for k, v in (m.get('income_points') or {}).items():
        pts(v, f'income {k} points')
    b = m['bands']
    try:
        hi, me = float(b['HIGH']), float(b['MEDIUM'])
        if not (0 < me < hi <= 1000):
            probs.append('bands must satisfy 0 < MEDIUM < HIGH')
    except (KeyError, TypeError, ValueError):
        probs.append('bands HIGH and MEDIUM must be numbers')
    for cls in CLASSES:
        v = (m.get('review_months') or {}).get(cls)
        if not isinstance(v, int) or isinstance(v, bool) or not (1 <= v <= 120):
            probs.append(f'review interval for {cls} must be 1 to 120 months')
    r = m.get('reminders') or {}
    if not isinstance(r.get('enabled'), bool):
        probs.append('reminders on/off must be true or false')
    d = r.get('days_before')
    if not isinstance(d, int) or isinstance(d, bool) or not (1 <= d <= 180):
        probs.append('reminder lead time must be 1 to 180 days')
    return probs


def _high_risk_country(country, model, high_risk_rows):
    c = model['country']
    src = c.get('source', 'builtin')
    if src in ('builtin', 'both') and country in [str(x).upper() for x in c.get('builtin_list') or []]:
        return True
    if src in ('table', 'both') and high_risk_rows:
        from aml.edd_logic import match_country
        return match_country(country, high_risk_rows) is not None
    return False


def classify(score, model=None):
    b = merged(model)['bands']
    if score >= float(b['HIGH']):
        return 'HIGH'
    if score >= float(b['MEDIUM']):
        return 'MEDIUM'
    return 'LOW'


def calculate_risk_score(data, model=None, high_risk_rows=None):
    """
    Calculate AML risk score based on customer data.
    Returns a dictionary with score, classification, and breakdown.

    model: a risk model (see DEFAULT_MODEL); None = the MLRO's current model
    (aml/risk_config.py), or DEFAULT_MODEL when it cannot be read.
    high_risk_rows: active high_risk_countries rows (needed when the model's
    country source is 'table' or 'both'; loaded with the model when None).
    """
    if model is None:
        model, high_risk_rows = _current(high_risk_rows)
    m = merged(model)
    score = 0
    reasons = []

    # 1. Geographic Risk (Country)
    country = str(data.get('country') or '').upper()
    c = m['country']
    if _high_risk_country(country, m, high_risk_rows):
        score += c['high_risk_points']
        reasons.append(f"High Risk Country: {country}")
    elif country != str(c.get('home_country') or '').upper():
        # TODO(compliance-review): as before, a blank country counts as foreign
        score += c['foreign_points']
        reasons.append(f"Foreign Country: {country}")

    # 2. Customer Type Risk
    customer_type = data.get('customer_type')
    pts = (m.get('customer_type_points') or {}).get(customer_type)
    if pts:
        score += pts
        reasons.append("Corporate Entity" if customer_type == 'CORPORATE' else f"Customer type: {customer_type}")

    # 3. Occupation / Activity Risk
    activity = (data.get('business_activity') or data.get('occupation') or '').upper()
    if any(str(risk).upper() in activity for risk in m['activity'].get('keywords') or [] if risk):
        score += m['activity']['points']
        reasons.append(f"High Risk Activity: {activity}")

    # 4. Financial Profile
    # Check both keys because form uses 'income' but model might expect 'annual_income_range'
    income = data.get('annual_income_range') or data.get('income')
    ip = (m.get('income_points') or {}).get(income)
    if ip:
        score += ip
        reasons.append("High Income/Turnover" if income == '>500K'
                       else ("Undeclared Income" if income == 'UNDECLARED' else f"Income: {income}"))

    return {
        'score': score,
        'classification': classify(score, m),
        'reasons': reasons
    }


def _current(high_risk_rows=None):
    """(model, high-risk rows) in force; DEFAULT_MODEL when they cannot be read."""
    try:
        from aml.risk_config import current_model, high_risk_rows_cached as _rows
        model = current_model()
        if high_risk_rows is None and model['country'].get('source') in ('table', 'both'):
            high_risk_rows = _rows()         # cached with the model (one minute)
        return model, high_risk_rows
    except Exception:
        return copy.deepcopy(DEFAULT_MODEL), high_risk_rows
