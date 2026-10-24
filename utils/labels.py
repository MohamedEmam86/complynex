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
from markupsafe import Markup

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
    # ── regulatory-controls areas (installed by the regulator packs into rc_areas) ──
    'capital_licensing': _l('Capital, solvency, licensing & key functions'),
    'origination': _l('Origination, client files & portfolio follow-up'),
    'pricing_conduct': _l('Pricing, fees, penalties & consumer protection'),
    'aml_cft': _l('AML/CFT'),
    'financial_reporting': _l('Accounting, financial statements & related parties'),
    'it_cyber': _l('IT, cyber & continuity'),
    'remediation': _l('Remediation of findings'),
    'climate': _l('Climate & carbon footprint'),
    # ── codes whose humanised form would read badly ──
    'unauth_txn': _l('Unauthorised transaction'), 'no_mx': _l('No mail server (MX record)'),
    'no_str': _l('No STR'), 'str_filed': _l('STR filed'), 'under_study': _l('Under study'),
    'national_id': _l('National ID'), 'passport': _l('Passport'), 'tax_card_issuer': _l('Tax card issuing office'),
    'pentest': _l('Penetration test'), 'app_pentest': _l('Application penetration test'),
    'malware_test': _l('Malware test'), 'vulnerability_scan': _l('Vulnerability scan'),
    'cis_benchmark': _l('CIS benchmark review'), 'phishing_simulation': _l('Phishing simulation'),
    'file_sar': _l('File STR'), 'sar_created': _l('SAR created'), 'sme_loan': _l('SME loan'), 'micro_loan': _l('Micro loan'),
    # ── transaction types / channels / sources ──
    'cash_in': _l('Cash in'), 'cash_out': _l('Cash out'), 'transfer_in': _l('Incoming transfer'),
    'transfer_out': _l('Outgoing transfer'), 'tm_alert': _l('Transaction monitoring alert'),
    'screening': _l('Screening'), 'employee_report': _l('Employee report'),
    'commercial_reg': _l('Commercial register'), 'commercial_register': _l('Commercial register'),
    'tax_card': _l('Tax card'), 'id_card': _l('National ID card'), 'email': _l('Email'),
    'manual_ad_hoc': _l('Manual (ad hoc)'), 'opensanctions_pep': _l('OpenSanctions PEP data'),
    'internal_blacklist': _l('Internal blacklist'), 'internal_pep': _l('Internal PEP list'),
    'un_sc_sanctions': _l('UN Security Council sanctions'), 'hr_notice': _l('HR notice'),
    'it_notice': _l('IT notice'), 'dr_readiness': _l('Disaster-recovery readiness'),
    'not_connected': _l('Not connected'), 'self_identified': _l('Self-identified'),
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
    try:  # codes labelled by the case registry (channels, case types, sources)
        from cases.labels import LABELS as CASE_LABELS
        found = CASE_LABELS.get(s.upper())
        if found is not None:
            return str(found)
    except Exception:  # pragma: no cover - module optional
        pass
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


# ── codes inside stored sentences ───────────────────────────────────────────
_TOKEN_RE = re.compile(r'(?<![\w/.@#-])([A-Za-z][A-Za-z0-9]*(?:[_\-][A-Za-z0-9]+)*)(?![\w/@-])')
_TRAILING_ZERO_RE = re.compile(r'(?<![\d.])(\d+)\.0+(?![\d.])')


def _code_text(tok):
    """Label for a code-looking token, or None when it is an ordinary word."""
    has_us = '_' in tok
    if not (has_us or (tok.isupper() and len(tok) > 1)):
        return None
    k = _key(tok)
    if k in LABELS:
        return str(LABELS[k])
    try:
        from cases.labels import LABELS as CASE_LABELS
        found = CASE_LABELS.get(tok.upper())
        if found is not None:
            return str(found)
    except Exception:  # pragma: no cover - module optional
        pass
    if has_us and (tok.isupper() or tok.islower()) and not any(ch.isdigit() for ch in tok):
        return _translated(humanise(tok))
    return None


def label_codes(text):
    """Replace stored codes inside a sentence with their labels:
    'Complaint submitted via PUBLIC_FORM' -> 'Complaint submitted via Online form'
    and drop a trailing '.0' from whole numbers ('0.0%' -> '0%'). Ordinary words,
    references (INC-2026-0001) and acronyms that are not codes stay as they are."""
    if text is None:
        return ''
    if isinstance(text, Markup):
        return text
    s = str(text)
    if not s:
        return s

    def rep(m):
        out = _code_text(m.group(1))
        return m.group(1) if out is None else out
    s = _TOKEN_RE.sub(rep, s)
    return _TRAILING_ZERO_RE.sub(r'\1', s)


# Stored history sentences (written in English by earlier code and the demo
# seed) -> translatable message; captured parts are labelled with label_codes.
# A trailing remainder (free text the user typed) is kept as is.
HISTORY_SENTENCES = [
    (r'Complaint submitted via (?P<channel>\S+)', 'Complaint submitted via %(channel)s'),
    (r'Complaint registered at branch counter', 'Complaint registered at branch counter'),
    (r'Complaint escalated due to exceeding statutory deadline \((?P<days>\d+) days\)\.?',
     'Complaint escalated due to exceeding the statutory deadline (%(days)s days).'),
    (r'Status changed from (?P<old>\S+) to (?P<new>[A-Za-z_]+)', 'Status changed from %(old)s to %(new)s'),
    (r'Root cause: (?P<root>[^;]+); redress: (?P<redress>.+)', 'Root cause: %(root)s; redress: %(redress)s'),
    (r'Root cause identified: (?P<root>.+)', 'Root cause identified: %(root)s'),
    (r'Assigned to (?P<name>[^—]+?)', 'Assigned to %(name)s'),
    (r'Internal note added', 'Internal note added'),
    (r'Request received via (?P<channel>\S+) on (?P<date>\S+)', 'Request received via %(channel)s on %(date)s'),
    (r'Request received via (?P<channel>\S+)', 'Request received via %(channel)s'),
    (r'Identity verified via (?P<method>\S+)', 'Identity verified via %(method)s'),
    (r'Request (?P<status>[a-z_]+)\. Notes: ', 'Request %(status)s. Notes: '),
    (r'SAR (?P<ref>\S+) opened \(source (?P<source>[^)]+)\)', 'SAR %(ref)s opened (source: %(source)s)'),
    (r'Escalated to Compliance for review \(regulatory sensitivity\)',
     'Escalated to Compliance for review (regulatory sensitivity)'),
    (r'Customer confirmed resolution - complaint closed', 'Customer confirmed resolution - complaint closed'),
    (r'SAR (?P<ref>\S+): assigned to (?P<name>.+)', 'SAR %(ref)s: assigned to %(name)s'),
    (r'SAR (?P<ref>\S+): investigation note — sent for decision', 'SAR %(ref)s: investigation note — sent for decision'),
    (r'SAR (?P<ref>\S+): investigation note', 'SAR %(ref)s: investigation note'),
    (r'SAR (?P<ref>\S+): decision (?P<decision>\S+)', 'SAR %(ref)s: decision %(decision)s'),
    (r'SAR (?P<ref>\S+): filed, reference (?P<fref>.+)', 'SAR %(ref)s: filed, reference %(fref)s'),
    (r'SAR (?P<ref>\S+): linked (?P<kind>\S+) ', 'SAR %(ref)s: linked %(kind)s '),
    (r'SAR (?P<ref>\S+): removed link to (?P<kind>\S+) ', 'SAR %(ref)s: removed link to %(kind)s '),
]
_HISTORY_RX = [(re.compile('^' + rx + r'(?P<_rest>.*)$', re.S), msg) for rx, msg in HISTORY_SENTENCES]


def history_text(text):
    """A stored history / activity sentence in the reader's language."""
    if text is None:
        return ''
    if isinstance(text, Markup):
        return text
    s = str(text).strip()
    for rx, msg in _HISTORY_RX:
        m = rx.match(s)
        if m:
            vals = {k: (label(v) if _CODE_RE.match(v or '') else label_codes(v))
                    for k, v in m.groupdict().items() if k != '_rest'}
            rest = m.group('_rest') or ''
            return gettext(msg, **vals) + label_codes(rest)
    return label_codes(s)


# ── template output finalizer ───────────────────────────────────────────────
# Every {{ expression }} passes through finalize(): date-times print in the
# standard display form (Africa/Cairo, no seconds or microseconds), whole
# floats/Decimals without ".0", None as an empty string. Values stay
# machine-readable (no thousands separators, "." decimal point), so
# value="{{ x }}" in a form still posts a number. Markup (|tojson, |safe) is
# never touched.
_TS_FULL_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})([ T])(\d{2}:\d{2})(?::(\d{2})(\.\d{1,6})?)?'
                         r'\s*(Z|[+-]\d{2}(?::?\d{2})?)?$')
_TS_EMBED_RE = re.compile(r'(?<![\d-])\d{4}-\d{2}-\d{2}( |T)\d{2}:\d{2}:\d{2}(\.\d{1,6})?'
                          r'(\s?(?:Z|[+-]\d{2}(?::?\d{2})?))?(?![\d:])')


def _iso_tz(tz):
    if not tz:
        return ''
    if tz == 'Z':
        return '+00:00'
    tz = tz.replace(':', '')
    return tz[:3] + ':' + (tz[3:5] or '00')


def _fmt_datetime(dt):
    if dt.tzinfo is None and dt.hour == dt.minute == dt.second == dt.microsecond == 0:
        return dt.strftime('%Y-%m-%d')
    return fmt_dt(dt)


def _fmt_ts_string(day, sep, hm, sec, frac, tz):
    """A timestamp string -> display form; None to leave it unchanged."""
    if sec is None and not tz:
        return None                       # already 'YYYY-MM-DD HH:MM'
    if sep == 'T' and not frac and not tz:
        return None                       # machine value (datetime-local inputs)
    try:
        dt = datetime.fromisoformat(f'{day}T{hm}:{sec or "00"}{frac or ""}{_iso_tz(tz)}')
    except ValueError:
        return None
    return _fmt_datetime(dt)


def _fmt_ts_text(s):
    m = _TS_FULL_RE.match(s)
    if m:
        out = _fmt_ts_string(*m.groups())
        return s if out is None else out
    if ':' not in s or not _TS_EMBED_RE.search(s):
        return s

    def rep(mm):
        if mm.group(1) == 'T' and not mm.group(2) and not mm.group(3):
            return mm.group(0)
        full = _TS_FULL_RE.match(mm.group(0).replace(' Z', 'Z'))
        out = _fmt_ts_string(*full.groups()) if full else None
        return mm.group(0) if out is None else out
    return _TS_EMBED_RE.sub(rep, s)


def _fmt_float(x):
    if x != x or x in (float('inf'), float('-inf')):
        return str(x)
    if x.is_integer() and abs(x) < 1e15:
        return str(int(x))
    a = abs(x)
    if a >= 1:
        places = max(2, 6 - len(str(int(a))))
    else:
        import math
        places = min(12, 5 - int(math.floor(math.log10(a))))
    out = f'{x:.{places}f}'
    return out.rstrip('0').rstrip('.') if '.' in out else out


def _fmt_decimal(d):
    if not d.is_finite():
        return str(d)
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), 'f')


def finalize(value):
    t = type(value)
    if t is str:
        if len(value) >= 16 and '-' in value and ':' in value:
            return _fmt_ts_text(value)
        return value
    if value is None:
        return ''
    if t is float:
        return _fmt_float(value)
    if t is Decimal:
        return _fmt_decimal(value)
    if t is datetime:
        return _fmt_datetime(value)
    return value


def register_filters(app):
    app.jinja_env.filters.update(label=label, num=num, money=money, pct=pct,
                                 fmt_dt=fmt_dt, fmt_date=fmt_date, module_label=module_label,
                                 label_codes=label_codes, history=history_text)
    app.jinja_env.finalize = finalize
    from utils.breadcrumbs import breadcrumb_trail, breadcrumb_page_title
    app.jinja_env.globals.update(breadcrumb_trail=breadcrumb_trail, breadcrumb_page_title=breadcrumb_page_title)
    from utils.regulator import register as _register_regulator
    _register_regulator(app)   # regulator_name / regulator_short for regulator-neutral wording
