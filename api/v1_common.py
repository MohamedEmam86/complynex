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
Shared pieces of the screening API v1 (P6-2 / P6-8 / G12): request ids, the error model,
idempotency, the client a key belongs to, webhook signing and URL checks, the payment
decision and the sandbox. Kept free of Flask-request state where possible so it can be
unit-tested and used by the webhook dispatcher outside the app.
"""
import hashlib
import hmac
import ipaddress
import json
import re
import socket
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

API_VERSION = 'v1'
EVENTS = ('screening.completed', 'hit.decided', 'list.updated')
IDEM_TTL_HOURS = 24
MAX_BATCH_ROWS = 5000
_RID = re.compile(r'^[A-Za-z0-9._:-]{1,64}$')


# --------------------------------------------------------------------------- request ids / errors
def request_id_from(header_value):
    """The caller's X-Request-Id when it is a safe token, else a new one."""
    v = (header_value or '').strip()
    return v if _RID.match(v) else 'req_' + uuid.uuid4().hex[:24]


def error_body(code, message, request_id=None, details=None):
    """One error shape for every v1 screening endpoint."""
    body = {'success': False, 'error': {'code': code, 'message': message}, 'request_id': request_id}
    if details:
        body['error']['details'] = details
    return body


# --------------------------------------------------------------------------- clients and keys
def client_of(key_row):
    """A client keeps its identity across key rotations (client_id), else the key itself."""
    if not key_row:
        return None
    return int(key_row.get('client_id') or key_row.get('id'))


def scopes_of(key_row):
    return {s.strip() for s in str((key_row or {}).get('scopes') or '').split(',') if s.strip()}


SCOPES = (
    ('screening:read', 'Read screenings and list status'),
    ('screening:write', 'Run screenings (single and batch)'),
    ('payments:screen', 'Real-time payment screening'),
    ('aml:read', 'AML read'), ('aml:write', 'AML write'),
    ('kyc:read', 'eKYC read'), ('kyc:write', 'eKYC write'),
)


# --------------------------------------------------------------------------- idempotency
def request_hash(method, path, body_bytes):
    """sha256 of method + path + canonical JSON body (key order does not matter)."""
    try:
        canon = json.dumps(json.loads(body_bytes or b'{}'), sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False).encode()
    except Exception:
        canon = body_bytes or b''
    h = hashlib.sha256()
    h.update(f'{method.upper()} {path}\n'.encode())
    h.update(canon)
    return h.hexdigest()


def valid_idem_key(v):
    v = (v or '').strip()
    return v if 1 <= len(v) <= 200 and re.match(r'^[\x21-\x7e]+$', v) else None


# --------------------------------------------------------------------------- webhook signing / urls
def sign(secret, body_bytes, ts=None):
    """Stripe-style signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of '<t>.<body>'>."""
    ts = int(ts if ts is not None else time.time())
    mac = hmac.new(secret.encode(), f'{ts}.'.encode() + body_bytes, hashlib.sha256).hexdigest()
    return f't={ts},v1={mac}'


def verify(secret, body_bytes, header, tolerance=300, now=None):
    """For clients (and tests): True when the header matches and is fresh."""
    try:
        parts = dict(p.split('=', 1) for p in header.split(','))
        ts = int(parts['t'])
    except Exception:
        return False
    now = int(now if now is not None else time.time())
    if abs(now - ts) > tolerance:
        return False
    expect = sign(secret, body_bytes, ts).split('v1=', 1)[1]
    return hmac.compare_digest(expect, parts.get('v1', ''))


def _ip_blocked(ip):
    """Anything that is not a public internet address (private, loopback, link-local, CGNAT
    100.64/10, documentation, multicast, reserved ...), also behind IPv4-mapped IPv6."""
    a = ipaddress.ip_address(ip)
    if a.version == 6 and a.ipv4_mapped:
        return _ip_blocked(str(a.ipv4_mapped))
    return (not a.is_global) or a.is_multicast


def resolve_public_ip(host, port=443):
    """Resolve once and return a public address to connect to; ValueError when the name
    does not resolve or ANY of its addresses is internal."""
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        try:
            ips = [i[4][0] for i in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]
        except Exception:
            raise ValueError('the host name does not resolve')
    if not ips:
        raise ValueError('the host name does not resolve')
    for ip in ips:
        if _ip_blocked(ip):
            raise ValueError('the host name points to an internal address')
    return ips[0]


def check_webhook_url(url, resolve=True):
    """(ok, why). https only, a real host name, no credentials, no internal addresses
    (checked again at every delivery: the name could later point inside)."""
    try:
        u = urlparse((url or '').strip())
    except Exception:
        return False, 'not a URL'
    if u.scheme != 'https':
        return False, 'only https URLs are accepted'
    if not u.hostname or u.username or u.password:
        return False, 'the URL needs a host and no user name / password'
    if len(url) > 1000:
        return False, 'the URL is too long'
    host = u.hostname
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal:
        return (False, 'internal addresses are not allowed') if _ip_blocked(host) else (True, '')
    if host in ('localhost',) or host.endswith('.local') or host.endswith('.internal') or '.' not in host:
        return False, 'internal host names are not allowed'
    if resolve:
        try:
            infos = socket.getaddrinfo(host, u.port or 443, proto=socket.IPPROTO_TCP)
        except Exception:
            return False, 'the host name does not resolve'
        for info in infos:
            if _ip_blocked(info[4][0]):
                return False, 'the host name points to an internal address'
    return True, ''


# --------------------------------------------------------------------------- results -> API shape
def _txt(v):
    if isinstance(v, dict):
        return {'en': v.get('en'), 'ar': v.get('ar')}
    return v


def hit_view(m):
    """One hit as the API returns it (no internal row ids beyond the list's own reference)."""
    m = m or {}
    w = m.get('workflow') or {}
    if not w:
        try:
            from screening import workflow as WF
            w = WF.view(m) or {}
        except Exception:
            w = {}
    d = m.get('decision') or {}
    act = w.get('action') or {}
    expl = w.get('explanation')
    if isinstance(expl, list):
        expl = [_txt(x) for x in expl]
    else:
        expl = _txt(expl)
    return {
        'listed_name': m.get('full_name') or m.get('original_name') or m.get('matched_name') or m.get('name'),
        'listed_name_ar': m.get('full_name_arabic') or m.get('watchlist_name_ar'),
        'source': m.get('source') or m.get('list_source'),
        'list_reference': m.get('source_id') or m.get('entity_id'),
        'list_type': act.get('list_type') or m.get('list_type'),
        'score': round(float(m.get('match_score') or 0), 2),
        'tier': act.get('tier') or d.get('tier'),
        'identity': d.get('identity'),
        'identity_status': _txt((w.get('identity_status') or {})) if w.get('identity_status') else None,
        'legal_status': m.get('legal_status'),
        'explanation': expl,
        'action': {'code': act.get('code'), 'label': _txt(act.get('label')), 'step': _txt(act.get('step'))}
        if act else None,
        'grouped_under': m.get('grouped_under'),
        'pep_related': bool(m.get('pep_related')),
    }


def screening_view(public_id, res, query, request_id, versions, sandbox=False, customer_ref=None):
    """The response body of a person / company screening."""
    status = (res or {}).get('screening_result') or (res or {}).get('status') or 'UNKNOWN'
    reasons = (res or {}).get('incomplete_reasons') or []
    incomplete = str(status).upper() == 'INCOMPLETE' or bool(reasons and str(status).upper() in ('CLEAR', 'LOW_MATCH'))
    matches = (res or {}).get('matches') or []
    hits = [hit_view(m) for m in matches[:100]]
    review = any((h['tier'] in ('CONFIRMED', 'POTENTIAL')) for h in hits) or incomplete
    return {
        'id': public_id, 'object': 'screening', 'sandbox': bool(sandbox), 'customer_ref': customer_ref,
        'status': 'INCOMPLETE' if incomplete else status,
        'incomplete': incomplete,
        'incomplete_reasons': [_txt(r) if not isinstance(r, dict) else
                               {k: r.get(k) for k in ('code', 'en', 'ar') if k in r} for r in reasons],
        'requires_review': bool(review),
        'hit_count': len(matches),
        'hits': hits,
        'hits_truncated': len(matches) > 100,
        'query': query,
        'list_versions': versions or {},
        'processing_time_ms': (res or {}).get('processing_time_ms'),
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'request_id': request_id,
    }


# --------------------------------------------------------------------------- payments (G12)
FREEZE_CODES = ('FREEZE_ESCALATE', 'FREEZE_REPORT')
PASSIVE_CODES = ('INFORMATION',)


def payment_decision(parties):
    """PASS / HOLD / BLOCK for a payment from the screened parties.
    parties: [{'role', 'incomplete': bool, 'hits': [hit_view, ...]}]
      BLOCK: a CONFIRMED hit whose list action is a freeze (sanctions, terror, local orders);
      HOLD:  any other CONFIRMED / POTENTIAL hit that is not information-only (PEP -> EDD,
             crime, review lists), or a party whose screening was incomplete (never PASS);
      PASS:  otherwise (no hits, low-tier hits, information-only lists, lifted orders)."""
    decision, reasons = 'PASS', []
    for p in parties:
        if p.get('incomplete'):
            decision = 'HOLD' if decision != 'BLOCK' else decision
            reasons.append({'party': p.get('role'), 'code': 'incomplete',
                            'en': 'The screening of this party was incomplete.',
                            'ar': 'فحص الطرف ده ماكملش.'})
        for h in p.get('hits') or []:
            tier = h.get('tier')
            code = ((h.get('action') or {}).get('code')) or ''
            if str(h.get('legal_status') or '').upper() == 'LIFTED':
                continue
            if tier == 'CONFIRMED' and code in FREEZE_CODES:
                decision = 'BLOCK'
                reasons.append({'party': p.get('role'), 'code': 'confirmed_freeze', 'list_type': h.get('list_type'),
                                'en': 'Confirmed hit on a list that requires a freeze.',
                                'ar': 'تطابق مؤكد على قايمة بتستوجب التجميد.'})
            elif tier in ('CONFIRMED', 'POTENTIAL') and code not in PASSIVE_CODES:
                if decision == 'PASS':
                    decision = 'HOLD'
                reasons.append({'party': p.get('role'), 'code': 'review_hit', 'list_type': h.get('list_type'),
                                'en': 'Possible match: hold for review.', 'ar': 'تطابق محتمل: أوقف للمراجعة.'})
    return decision, reasons


# --------------------------------------------------------------------------- sandbox
SANDBOX_HELP = {
    'TEST HIT': 'a confirmed sanctions hit', 'TEST POTENTIAL': 'a potential sanctions hit',
    'TEST PEP': 'a potential PEP hit', 'TEST INCOMPLETE': 'an incomplete screening',
}


def sandbox_result(name):
    """Fixed synthetic results for sandbox keys: no lists are searched and nothing is stored
    in the screening tables. Put a trigger word in the name to get each case."""
    n = (name or '').upper()

    def hit(list_type, tier, score, code, label):
        return {'full_name': 'SANDBOX LISTED PERSON', 'source': 'sandbox', 'source_id': 'sandbox-1',
                'list_type': list_type, 'match_score': score, 'decision': {'tier': tier, 'identity': None},
                'workflow': {'action': {'list_type': list_type, 'code': code, 'tier': tier,
                                        'label': {'en': label, 'ar': label}, 'step': {'en': 'Sandbox', 'ar': 'Sandbox'}},
                             'explanation': [{'en': 'Sandbox: synthetic hit.', 'ar': 'Sandbox: نتيجة تجريبية.'}],
                             'identity_status': {'state': 'not_verifiable', 'en': 'Sandbox', 'ar': 'Sandbox'}}}
    if 'TEST INCOMPLETE' in n:
        return {'screening_result': 'INCOMPLETE', 'matches': [], 'processing_time_ms': 1,
                'incomplete_reasons': [{'code': 'search_index', 'en': 'Sandbox: a source was unavailable.',
                                        'ar': 'Sandbox: مصدر ماكانش متاح.'}]}
    if 'TEST HIT' in n:
        return {'screening_result': 'CONFIRMED_HIT', 'matches': [hit('SANCTIONS', 'CONFIRMED', 100, 'FREEZE_ESCALATE', 'Freeze and escalate')],
                'processing_time_ms': 1}
    if 'TEST POTENTIAL' in n:
        return {'screening_result': 'POTENTIAL_MATCH', 'matches': [hit('SANCTIONS', 'POTENTIAL', 86, 'FREEZE_ESCALATE', 'Freeze and escalate')],
                'processing_time_ms': 1}
    if 'TEST PEP' in n:
        return {'screening_result': 'POTENTIAL_MATCH', 'matches': [hit('PEP', 'POTENTIAL', 88, 'EDD', 'Enhanced due diligence')],
                'processing_time_ms': 1}
    return {'screening_result': 'CLEAR', 'matches': [], 'processing_time_ms': 1}


# --------------------------------------------------------------------------- input
ENTITY_TYPES = {'person': 'INDIVIDUAL', 'individual': 'INDIVIDUAL', 'company': 'ENTITY', 'entity': 'ENTITY',
                'corporate': 'ENTITY', 'organisation': 'ENTITY', 'organization': 'ENTITY'}


def clean_str(v, n=300):
    if v is None:
        return ''
    if not isinstance(v, (str, int, float)):
        return ''
    return str(v).strip()[:n]


def parse_screening_input(data):
    """(fields, errors) for one screening request body."""
    errs = []
    if not isinstance(data, dict):
        return None, [{'field': 'body', 'message': 'a JSON object is required'}]
    name = clean_str(data.get('name'), 300)
    if not name:
        errs.append({'field': 'name', 'message': 'required'})
    et_raw = clean_str(data.get('entity_type') or 'person', 30).lower()
    et = ENTITY_TYPES.get(et_raw)
    if not et:
        errs.append({'field': 'entity_type', 'message': 'person or company'})
    dob = clean_str(data.get('dob') or data.get('date_of_birth'), 20)
    if dob and not re.match(r'^\d{4}(-\d{2}(-\d{2})?)?$', dob):
        errs.append({'field': 'dob', 'message': 'YYYY, YYYY-MM or YYYY-MM-DD'})
    f = {'name': name, 'entity_type': et or 'INDIVIDUAL', 'dob': dob or None,
         'nationality': clean_str(data.get('nationality') or data.get('country'), 80) or None,
         'national_id': clean_str(data.get('national_id'), 60) or None,
         'customer_ref': clean_str(data.get('customer_ref'), 200) or None}
    return f, errs
