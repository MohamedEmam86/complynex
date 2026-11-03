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

"""Written authorisation for a phishing simulation (Phase 7, H2).

A simulated phishing campaign targets real people. It may only be sent when the
organisation has authorised it IN WRITING: who authorised it (name and title),
for which organisation and scope, for which dates, which email domains may be
targeted, and the signed document itself (uploaded as an attachment). The rule
is enforced when the campaign is sent, not only shown on the page.

`problems()` is pure so the rule can be tested without a database.
"""
from datetime import date, datetime

RECORD_TYPE = 'phishing_authorisation'


def _d(v):
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def domains(text):
    """'example.com, @demo.example; other.example' -> {'example.com', 'demo.example', 'other.example'}"""
    out = set()
    for part in str(text or '').replace(';', ',').replace('\n', ',').split(','):
        p = part.strip().lower().lstrip('@')
        if p:
            out.add(p)
    return out


def email_domain(email):
    e = str(email or '').strip().lower()
    return e.rsplit('@', 1)[1] if '@' in e else ''


def in_scope(email, allowed):
    d = email_domain(email)
    return bool(d) and any(d == a or d.endswith('.' + a) for a in allowed)


def problems(auth, recipient_emails, documents_count, today=None):
    """Why this campaign may NOT be sent - [(code, message)]; empty list = authorised."""
    today = today or date.today()
    if not auth:
        return [('missing', 'No written authorisation is recorded for this campaign.')]
    out = []
    if auth.get('revoked_at'):
        out.append(('revoked', 'The authorisation was revoked.'))
    for f, label in (('authorised_by_name', 'the name of the person who authorised it'),
                     ('authorised_by_title', 'their title'), ('organisation', 'the organisation'),
                     ('scope', 'the scope')):
        if not str(auth.get(f) or '').strip():
            out.append(('incomplete', f'The authorisation does not state {label}.'))
    vf, vt = _d(auth.get('valid_from')), _d(auth.get('valid_to'))
    if not vf or not vt:
        out.append(('dates', 'The authorisation has no validity period.'))
    elif vt < vf:
        out.append(('dates', 'The authorisation ends before it starts.'))
    elif today < vf:
        out.append(('not_yet', f'The authorisation is valid only from {vf.isoformat()}.'))
    elif today > vt:
        out.append(('expired', f'The authorisation expired on {vt.isoformat()}.'))
    if not documents_count:
        out.append(('document', 'The signed authorisation document is not uploaded.'))
    allowed = domains(auth.get('allowed_domains'))
    if not allowed:
        out.append(('domains', 'The authorisation does not list the email domains that may be targeted.'))
    else:
        outside = sorted({e for e in recipient_emails if not in_scope(e, allowed)})
        if outside:
            more = f' (+{len(outside) - 3} more)' if len(outside) > 3 else ''
            out.append(('out_of_scope', 'Recipients outside the authorised domains: ' + ', '.join(outside[:3]) + more))
    return out
