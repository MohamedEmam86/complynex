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
"""Breadcrumb trail for the shared layout: readable, translated titles for
URL segments, and a link only where a GET page really answers that path."""
from flask import current_app, request
from flask_babel import gettext, lazy_gettext as _l
from werkzeug.exceptions import HTTPException
from werkzeug.routing import RequestRedirect

from utils.labels import humanise, label as _label

# segment -> title where humanising the URL fragment would read badly
SEGMENT_TITLES = {
    'aml': _l('AML/CFT'), 'aml-assurance': _l('AML Assurance'), 'ekyc': _l('eKYC'), 'esg': _l('ESG'),
    'ai': _l('Compliance Copilot (AI)'), 'kris': _l('KRIs'), 'kyc': _l('KYC'), 'coi': _l('COI Declarations'),
    'ghe': _l('GHE Declarations'), 'cobec': _l('Code of Ethics'), 'pep': _l('PEP'), 'sars': _l('SARs'),
    'sar': _l('SAR'), 'fra': _l('FRA'), 'fra-nbfi': _l('FRA NBFI'), 'mfa': _l('Multi-Factor Auth'),
    'api-keys': _l('API Keys'), 'bcp': _l('Business Continuity'), 'it-risks': _l('IT Risks'),
    'tm-rules': _l('Transaction Monitoring Rules'), 'tm-dashboard': _l('Transaction Monitoring'),
    'tm-analytics': _l('TM Analytics'), 'tm-network': _l('TM Network'), 'tm-scenario': _l('Scenario Simulator'),
    'regcontrols': _l('Compliance Controls'), 'merchant-kyc': _l('Merchant KYC'),
    'ubo-verification': _l('UBO Verification'), 'dsrs': _l('Data Subject Requests'), 'dpias': _l('DPIAs'),
    'pdpl': _l('Data Protection'), 'qa': _l('Quality Assurance'), 'new': _l('New'), 'edit': _l('Edit'),
    'add': _l('Add'), 'create': _l('Create'), 'view': _l('View'), 'dashboard': _l('Dashboard'),
    'internal-audit': _l('Internal Audit'), 'risk-management': _l('Risk Management'),
    'data-protection': _l('Data Protection'), 'consumer-protection': _l('Consumer Protection'),
    'permissions-matrix': _l('Permissions Matrix'), 'admin': _l('Administration'),
    'prudential': _l('Prudential & Governance'), 'carbon': _l('Carbon Footprint'),
    'cyber': _l('Cyber Security'), 'resilience': _l('Cyber Resilience'), 'portal': _l('Employee Portal'),
    'fit-proper': _l('Fit & Proper'), 'reporting': _l('Regulatory Reporting'), 'register': _l('Risk Register'),
}


def _title(seg):
    if seg.isdigit():
        return '#' + seg
    t = SEGMENT_TITLES.get(seg)
    if t is not None:
        return str(t)
    if len(seg) > 40:               # tokens, hashes
        return gettext('Details')
    out = _label(seg.replace('-', '_'))
    return out if isinstance(out, str) else str(out)


def _get_page(adapter, path):
    """The URL to link for `path`, or None when no parameterless-safe GET page answers it."""
    try:
        adapter.match(path, method='GET')
        return path
    except RequestRedirect as r:    # e.g. trailing slash: the page exists one redirect away
        from urllib.parse import urlsplit
        return urlsplit(r.new_url).path
    except HTTPException:
        return None
    except Exception:
        return None


def breadcrumb_trail():
    """[(title, url_or_None), ...] for request.path, excluding Home."""
    parts = [p for p in request.path.strip('/').split('/') if p]
    if not parts:
        return []
    try:
        adapter = current_app.create_url_adapter(request)
    except Exception:
        adapter = None
    trail, cur = [], ''
    for i, seg in enumerate(parts):
        cur += '/' + seg
        last = i == len(parts) - 1
        url = None if (last or adapter is None) else _get_page(adapter, cur)
        trail.append((_title(seg), url))
    return trail


def breadcrumb_page_title():
    """Fallback page title (pages without their own title block): the last
    readable breadcrumb, e.g. "Screening configuration" rather than the
    company name alone."""
    try:
        for title, _url in reversed(breadcrumb_trail()):
            if title and not str(title).startswith('#'):
                return title
    except Exception:
        return ''
    return ''
