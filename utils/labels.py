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
"""Readable, translated labels for stored codes, and display formatting.

Records keep machine codes (``IN_PROGRESS``, ``high``, ``compliance_officer``);
pages should show words. Templates use the filters registered by
``register_filters(app)``:

    {{ risk.status | label }}          -> "In Progress" / "قيد التنفيذ"
    {{ amount | money }}               -> "1,250,000.00"
    {{ ratio | pct }}                  -> "12.5%"
    {{ count | num }}                  -> "12,480"
    {{ row.created_at | fmt_dt }}      -> "2026-10-24 14:05" (Africa/Cairo)
    {{ row.due_date | fmt_date }}      -> "2026-10-24"

One dictionary serves every module; an unknown code falls back to a
humanised form ("NOT_YET_TESTED" -> "Not yet tested"), translated when the
catalogue knows that phrase. Free text that is not a code is returned as is.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask_babel import gettext, lazy_gettext as _l

# code (lower case, '_' separated) -> English label (msgid)
LABELS = {
    # ── workflow / record status ──
    'open': _l('Open'), 'opened': _l('Open'), 'reopened': _l('Reopened'),
    'new': _l('New'), 'in_progress': _l('In Progress'), 'ongoing': _l('Ongoing'),
    'closed': _l('Closed'), 'resolved': _l('Resolved'), 'pending': _l('Pending'),
    'approved': _l('Approved'), 'rejected': _l('Rejected'), 'draft': _l('Draft'),
    'submitted': _l('Submitted'), 'under_review': _l('Under Review'), 'in_review': _l('Under Review'),
    'review': _l('Review'), 'pending_review': _l('Pending Review'),
    'pending_approval': _l('Pending Approval'), 'awaiting_approval': _l('Pending Approval'),
    'completed': _l('Completed'), 'complete': _l('Completed'), 'done': _l('Done'),
    'cancelled': _l('Cancelled'), 'canceled': _l('Cancelled'), 'on_hold': _l('On Hold'),
    'overdue': _l('Overdue'), 'due': _l('Due'), 'not_started': _l('Not Started'),
    'planned': _l('Planned'), 'scheduled': _l('Scheduled'), 'active': _l('Active'),
    'inactive': _l('Inactive'), 'archived': _l('Archived'), 'expired': _l('Expired'),
    'escalated': _l('Escalated'), 'assigned': _l('Assigned'), 'accepted': _l('Accepted'),
    'declined': _l('Declined'), 'returned': _l('Returned'), 'withdrawn': _l('Withdrawn'),
    'suspended': _l('Suspended'), 'reported': _l('Reported'), 'published': _l('Published'),
    'final': _l('Final'), 'effective': _l('Effective'), 'superseded': _l('Superseded'),
    'retired': _l('Retired'), 'deferred': _l('Deferred'), 'waived': _l('Waived'),
    'executed': _l('Executed'), 'fulfilled': _l('Fulfilled'), 'ready': _l('Ready'),
    'verified': _l('Verified'), 'unverified': _l('Unverified'), 'confirmed': _l('Confirmed'),
    'failed': _l('Failed'), 'fail': _l('Fail'), 'passed': _l('Passed'), 'pass': _l('Pass'),
    'partial': _l('Partial'), 'success': _l('Success'), 'ok': _l('OK'), 'warning': _l('Warning'),
    'error': _l('Error'), 'skipped': _l('Skipped'), 'live': _l('Live'),
    'not_applicable': _l('Not Applicable'), 'n_a': _l('Not Applicable'), 'na': _l('Not Applicable'),
    'not_required': _l('Not Required'), 'not_connected': _l('Not Connected'),
    'connected': _l('Connected'), 'enabled': _l('Enabled'), 'disabled': _l('Disabled'),
    'implemented': _l('Implemented'), 'partially_implemented': _l('Partially Implemented'),
    'not_implemented': _l('Not Implemented'), 'ineffective': _l('Ineffective'),
    'partially_effective': _l('Partially Effective'), 'not_tested': _l('Not Tested'),
    'investigating': _l('Investigating'), 'contained': _l('Contained'),
    'recovered': _l('Recovered'), 'identified': _l('Identified'), 'mitigated': _l('Mitigated'),
    'monitoring': _l('Monitoring'), 'false_positive': _l('False Positive'),
    'true_positive': _l('True Positive'), 'cleared': _l('Cleared'), 'clear': _l('Clear'),
    'match': _l('Match'), 'potential_match': _l('Potential Match'), 'no_match': _l('No Match'),
    'met': _l('Met'), 'not_met': _l('Not Met'), 'partially_met': _l('Partially Met'),
    'compliant': _l('Compliant'), 'non_compliant': _l('Non-compliant'),
    'partially_compliant': _l('Partially Compliant'), 'breach': _l('Breach'),
    'within_appetite': _l('Within Appetite'), 'outside_appetite': _l('Outside Appetite'),
    'green': _l('Green'), 'amber': _l('Amber'), 'red': _l('Red'),
    'disbursed': _l('Disbursed'), 'paid': _l('Paid'), 'performing': _l('Performing'),
    'rescheduled': _l('Rescheduled'), 'written_off': _l('Written Off'),
    # ── risk levels / severities / priorities ──
    'very_low': _l('Very Low'), 'low': _l('Low'), 'medium': _l('Medium'), 'moderate': _l('Moderate'),
    'high': _l('High'), 'very_high': _l('Very High'), 'critical': _l('Critical'),
    'extreme': _l('Extreme'), 'severe': _l('Severe'), 'minor': _l('Minor'), 'major': _l('Major'),
    'significant': _l('Significant'), 'insignificant': _l('Insignificant'),
    'catastrophic': _l('Catastrophic'), 'negligible': _l('Negligible'),
    'informational': _l('Informational'), 'info': _l('Informational'),
    'urgent': _l('Urgent'), 'normal': _l('Normal'),
    'increasing': _l('Increasing'), 'decreasing': _l('Decreasing'), 'stable': _l('Stable'),
    'up': _l('Up'), 'down': _l('Down'),
    # ── risk treatment ──
    'mitigate': _l('Mitigate'), 'reduce': _l('Reduce'), 'accept': _l('Accept'),
    'transfer': _l('Transfer'), 'avoid': _l('Avoid'), 'share': _l('Share'),
    # ── entity / party types ──
    'individual': _l('Individual'), 'person': _l('Individual'), 'natural_person': _l('Individual'),
    'entity': _l('Entity'), 'organization': _l('Organisation'), 'organisation': _l('Organisation'),
    'company': _l('Company'), 'legal_entity': _l('Legal Entity'), 'corporate': _l('Corporate'),
    'vessel': _l('Vessel'), 'aircraft': _l('Aircraft'), 'customer': _l('Customer'),
    'merchant': _l('Merchant'), 'employee': _l('Employee'), 'supplier': _l('Supplier'),
    'vendor': _l('Vendor'), 'third_party': _l('Third Party'), 'pep': _l('PEP'),
    'sanctions': _l('Sanctions'), 'adverse_media': _l('Adverse Media'),
    # ── frequencies ──
    'daily': _l('Daily'), 'weekly': _l('Weekly'), 'monthly': _l('Monthly'),
    'quarterly': _l('Quarterly'), 'quarter': _l('Quarterly'), 'semi_annual': _l('Semi-annual'),
    'semiannual': _l('Semi-annual'), 'annual': _l('Annual'), 'annually': _l('Annual'),
    'yearly': _l('Annual'), 'ad_hoc': _l('Ad hoc'), 'one_off': _l('One-off'),
    'continuous': _l('Continuous'),
    # ── user roles ──
    'admin': _l('Administrator'), 'superadmin': _l('Administrator'), 'it_admin': _l('IT Administrator'),
    'compliance_officer': _l('Compliance Officer'), 'compliance_manager': _l('Compliance Manager'),
    'manager': _l('Manager'), 'analyst': _l('Analyst'), 'viewer': _l('Viewer'),
    'mlro': _l('MLRO'), 'auditor': _l('Auditor'), 'risk_officer': _l('Risk Officer'),
    # ── misc ──
    'yes': _l('Yes'), 'no': _l('No'), 'true': _l('Yes'), 'false': _l('No'),
    'manual': _l('Manual'), 'automatic': _l('Automatic'), 'auto': _l('Automatic'),
    'ghe': _l('GHE'), 'coi': _l('COI'), 'cobec': _l('COBEC'),
    'it_dependent': _l('IT-dependent'), 'automated': _l('Automated'), 'preventive': _l('Preventive'),
    'detective': _l('Detective'), 'corrective': _l('Corrective'), 'directive': _l('Directive'),
    'granted': _l('Granted'), 'refused': _l('Refused'), 'shareholder': _l('Shareholder'),
    'default': _l('Default'), 'action_plan': _l('Action Plan'), 'other': _l('Other'),
    'internal': _l('Internal'), 'external': _l('External'), 'regulatory': _l('Regulatory'),
    'operational': _l('Operational'), 'strategic': _l('Strategic'), 'financial': _l('Financial'),
    'compliance': _l('Compliance'), 'reputational': _l('Reputational'), 'legal': _l('Legal'),
    'technology': _l('Technology'), 'cyber': _l('Cyber'), 'fraud': _l('Fraud'),
    'phishing': _l('Phishing'), 'malware': _l('Malware'), 'ransomware': _l('Ransomware'),
    'data_breach': _l('Data Breach'), 'outage': _l('Outage'),
    'capital_increase': _l('Capital Increase'), 'capital_contribution': _l('Capital Contribution'),
    'exiting_shareholder': _l('Exiting Shareholder'), 'board_minutes': _l('Board Minutes'),
    # ── carbon (GHG Protocol activity categories) ──
    'scope1': _l('Scope 1'), 'scope2': _l('Scope 2'), 'scope3': _l('Scope 3'),
    'stationary_combustion': _l('Stationary Combustion'), 'mobile_combustion': _l('Mobile Combustion'),
    'fugitive_emissions': _l('Fugitive Emissions'), 'purchased_electricity': _l('Purchased Electricity'),
    'purchased_goods_services': _l('Purchased Goods and Services'), 'business_travel': _l('Business Travel'),
    'employee_commuting': _l('Employee Commuting'), 'upstream_transport': _l('Upstream Transport'),
    'waste_operations': _l('Waste Generated in Operations'),
    'fuel_energy_related': _l('Fuel- and Energy-related Activities'),
    'business_loans': _l('Business Loans'), 'equity_share': _l('Equity Share'),
    'operational_control': _l('Operational Control'), 'financial_control': _l('Financial Control'),
}

# Permission modules shown in administration (code, English label).
MODULES = [
    ('governance', _l('Corporate Governance')), ('aml', _l('AML/CFT')), ('tm', _l('Transaction Monitoring')),
    ('screening', _l('Sanction Screening')), ('ongoing_screening', _l('Ongoing Screening')),
    ('merchant_kyc', _l('Merchant KYC')), ('ekyc', _l('eKYC')), ('policies', _l('Policies')),
    ('reports', _l('Regulatory Reports')), ('pdpl', _l('Data Protection')), ('training', _l('Training')),
    ('cyber', _l('Cyber Incidents Hub')), ('phishing', _l('Phishing Awareness')),
    ('whistleblowing', _l('Whistleblowing')), ('consumer_protection', _l('Consumer Protection')),
    ('ghe', _l('GHE Declarations')), ('coi', _l('COI Declarations')), ('cobec', _l('Code of Ethics')),
    ('risk_management', _l('Risk Management')), ('internal_audit', _l('Internal Audit')),
    ('esg', _l('ESG Management')), ('carbon', _l('Carbon Footprint')),
    ('regcontrols', _l('Compliance Controls')), ('prudential', _l('Prudential & Governance')),
    ('academy', _l('Integrys Academy (learners)')), ('ai', _l('Compliance Copilot (AI)')),
    ('config', _l('System Configuration')),
]
MODULE_LABELS = dict(MODULES)

_CODE_RE = re.compile(r'^[A-Za-z][A-Za-z0-9]*(?:[_\-][A-Za-z0-9]+)*$')


def _key(value):
    return re.sub(r'[\s\-]+', '_', str(value).strip()).lower()


def _translated(phrase):
    """gettext(phrase) if the catalogue knows it (also tries Title Case)."""
    t = gettext(phrase)
    if t != phrase:
        return t
    title = ' '.join(w[:1].upper() + w[1:] for w in phrase.split(' '))
    t2 = gettext(title)
    return t2 if t2 != title else phrase


def humanise(code):
    """'NOT_YET_TESTED' -> 'Not yet tested'."""
    words = re.split(r'[_\-\s]+', str(code).strip())
    words = [w for w in words if w]
    if not words:
        return ''
    text = ' '.join(w.lower() for w in words)
    return text[:1].upper() + text[1:]


def label(value, default='—'):
    """Readable, translated label for a stored code. Numbers and free text
    that is not a code pass through unchanged."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        return str(LABELS['yes' if value else 'no'])
    if isinstance(value, (int, float, Decimal)):
        return value
    s = str(value).strip()
    k = _key(s)
    if k in LABELS:
        return str(LABELS[k])
    if k.startswith('perm_') and k[5:] in MODULE_LABELS:
        return str(MODULE_LABELS[k[5:]])
    if k in MODULE_LABELS:
        return str(MODULE_LABELS[k])
    if _CODE_RE.match(s) and (('_' in s) or s.isupper() or s.islower()) and not any(ch.isdigit() for ch in s):
        if len(s) <= 4 and s.isupper():   # acronyms (PEP, ESG, KYC) stay as they are
            return s
        return _translated(humanise(s))
    return _translated(s)


def module_label(code):
    return str(MODULE_LABELS.get(code, humanise(code)))


# ── numbers ──────────────────────────────────────────────────────────────────
def _to_number(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return value
    try:
        return Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, ValueError):
        return None


def num(value, decimals=None, default='—', max_decimals=2):
    """Thousands separators. With `decimals`, exactly that many places;
    otherwise whole numbers without decimals and others with up to
    `max_decimals` places (default 2), trailing zeros trimmed."""
    n = _to_number(value)
    if n is None:
        return value if value not in (None, '') else default
    if decimals is None:
        d = Decimal(str(n))
        if d == d.to_integral_value():
            return f'{int(d):,}'
        out = f'{float(d):,.{int(max_decimals)}f}'
        return out.rstrip('0').rstrip('.') if '.' in out else out
    return f'{float(n):,.{int(decimals)}f}'


def money(value, currency='', decimals=2, default='—'):
    n = _to_number(value)
    if n is None:
        return value if value not in (None, '') else default
    out = f'{float(n):,.{int(decimals)}f}'
    return f'{out} {currency}'.strip() if currency else out


def pct(value, decimals=1, ratio=False, default='—'):
    """12.345 -> '12.3%'; with ratio=True, 0.123 -> '12.3%'."""
    n = _to_number(value)
    if n is None:
        return value if value not in (None, '') else default
    f = float(n) * (100 if ratio else 1)
    out = f'{f:,.{int(decimals)}f}'
    if '.' in out:
        out = out.rstrip('0').rstrip('.')
    return out + '%'


# ── dates ────────────────────────────────────────────────────────────────────
try:
    from zoneinfo import ZoneInfo
    DISPLAY_TZ = ZoneInfo('Africa/Cairo')
except Exception:  # pragma: no cover - tzdata missing
    from datetime import timedelta, timezone
    DISPLAY_TZ = timezone(timedelta(hours=2))


def _parse_dt(value):
    if isinstance(value, (datetime, date)):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None


def fmt_dt(value, fmt='%Y-%m-%d %H:%M', default='—'):
    """Date-time in Africa/Cairo, no seconds/microseconds. Naive values are
    taken as the server's local time (how PostgreSQL CURRENT_TIMESTAMP and
    datetime.now() store them)."""
    if not value:
        return default
    dt = _parse_dt(value)
    if dt is None:
        return value
    if not isinstance(dt, datetime):
        return dt.strftime('%Y-%m-%d')
    try:
        dt = (dt.astimezone() if dt.tzinfo is None else dt).astimezone(DISPLAY_TZ)
    except (OverflowError, OSError, ValueError):
        pass
    return dt.strftime(fmt)


def fmt_date(value, default='—'):
    if not value:
        return default
    dt = _parse_dt(value)
    if dt is None:
        return value
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        dt = dt.astimezone(DISPLAY_TZ)
    return dt.strftime('%Y-%m-%d')


def register_filters(app):
    app.jinja_env.filters.update(label=label, num=num, money=money, pct=pct,
                                 fmt_dt=fmt_dt, fmt_date=fmt_date, module_label=module_label)
    from utils.breadcrumbs import breadcrumb_trail
    app.jinja_env.globals.update(breadcrumb_trail=breadcrumb_trail)
    from utils.regulator import register as _register_regulator
    _register_regulator(app)   # regulator_name / regulator_short for regulator-neutral wording
