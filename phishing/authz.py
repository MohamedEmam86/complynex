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

`problems()` is pure so the rule can be tested without a database. It returns
(code, message_key, params) triples — never a ready-made string with runtime
text folded in — so the message can be translated (English/Arabic) and
formatted safely by `message()` (a bare ``%`` or an email address in the text
can neither crash gettext nor be mistaken for a format placeholder).
"""
from datetime import date, datetime
from email.utils import parseaddr

RECORD_TYPE = 'phishing_authorisation'

# Free webmail / consumer domains that must never be registered as a target
# domain for a simulation: they belong to the public, not to the authorising
# organisation. (Not exhaustive — a representative set of the common ones.)
FREEMAIL = {
    'gmail.com', 'googlemail.com', 'outlook.com', 'outlook.sa', 'hotmail.com', 'hotmail.co.uk',
    'live.com', 'msn.com', 'yahoo.com', 'yahoo.co.uk', 'ymail.com', 'rocketmail.com',
    'icloud.com', 'me.com', 'mac.com', 'aol.com', 'aim.com', 'protonmail.com', 'proton.me',
    'gmx.com', 'gmx.net', 'mail.com', 'zoho.com', 'yandex.com', 'yandex.ru', 'tutanota.com',
    'qq.com', '163.com', '126.com', 'sina.com', 'fastmail.com', 'hushmail.com',
}

# Message catalogue: key -> (English, Arabic). Placeholders are named (%(d)s,
# %(emails)s) so a value folded in at render time is data, never a format
# directive. Translating these lives here (not scattered through gettext calls
# on runtime text) so the wording stays accurate and bilingual.
MESSAGES = {
    'missing': ('No written authorisation is recorded for this campaign.',
                'لا يوجد تفويض كتابي مسجَّل لهذه الحملة.'),
    'revoked': ('The authorisation was revoked.',
                'تم إلغاء التفويض.'),
    'incomplete_name': ('The authorisation does not state the name of the person who authorised it.',
                        'لا يذكر التفويض اسم الشخص الذي أصدره.'),
    'incomplete_title': ('The authorisation does not state the title of the person who authorised it.',
                         'لا يذكر التفويض المسمى الوظيفي للشخص الذي أصدره.'),
    'incomplete_org': ('The authorisation does not state the organisation.',
                       'لا يذكر التفويض الجهة المُصدِرة.'),
    'incomplete_scope': ('The authorisation does not state the scope.',
                         'لا يحدد التفويض النطاق.'),
    'dates_missing': ('The authorisation has no validity period.',
                      'لا توجد فترة صلاحية محددة للتفويض.'),
    'dates_order': ('The authorisation ends before it starts.',
                    'تاريخ انتهاء التفويض يسبق تاريخ بدايته.'),
    'not_yet': ('The authorisation is valid only from %(d)s.',
                'التفويض ساري المفعول اعتباراً من %(d)s فقط.'),
    'expired': ('The authorisation expired on %(d)s.',
                'انتهت صلاحية التفويض بتاريخ %(d)s.'),
    'document': ('The signed authorisation document is not uploaded.',
                 'لم يتم رفع وثيقة التفويض المُوقَّعة.'),
    'domains': ('The authorisation does not list the email domains that may be targeted.',
                'لا يحدد التفويض نطاقات البريد الإلكتروني المسموح استهدافها.'),
    'out_of_scope': ('Recipients outside the authorised domains: %(emails)s',
                     'مستلمون خارج النطاقات المصرَّح بها: %(emails)s'),
}


def message(item, lang='en'):
    """Render one (code, key, params) problem as a translated, formatted string."""
    try:
        _code, key, params = item
    except (ValueError, TypeError):
        return str(item)
    en, ar = MESSAGES.get(key, (key, key))
    text = ar if lang == 'ar' else en
    if params:
        try:
            return text % params
        except (KeyError, ValueError, TypeError):
            return text
    return text


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


def invalid_domains(allowed):
    """Return the entries of `allowed` that may NOT be used as a target domain:
    free webmail, a wildcard '*', a single-label / public-suffix-like domain, or
    anything without a dot. An allowed target domain must identify the
    organisation, so it needs at least one dot and must not be public webmail."""
    bad = []
    for d in sorted(allowed):
        dl = str(d).strip().lower().lstrip('@')
        if (not dl or dl == '*' or '*' in dl or ' ' in dl
                or '.' not in dl or dl in FREEMAIL):
            bad.append(dl or str(d))
    return bad


def valid_email(email):
    """A single, plain recipient address: exactly one '@', no display name, no
    separators or control-ish characters, a dotted domain. parseaddr must return
    the address unchanged (rejects 'Name <a@b>', '<a@b>', comment forms …)."""
    e = str(email or '').strip()
    if not e or e.count('@') != 1:
        return False
    if any(c.isspace() for c in e) or any(c in e for c in '%;,<>!"()[]\\'):
        return False
    _name, addr = parseaddr(e)
    if addr != e:
        return False
    local, _, dom = e.partition('@')
    if not local or not dom or '.' not in dom or dom.startswith('.') or dom.endswith('.'):
        return False
    return True


def email_domain(email):
    e = str(email or '').strip().lower()
    return e.rsplit('@', 1)[1] if '@' in e else ''


def in_scope(email, allowed):
    d = email_domain(email)
    return bool(d) and any(d == a or d.endswith('.' + a) for a in allowed)


def problems(auth, recipient_emails, documents_count, today=None):
    """Why this campaign may NOT be sent - [(code, message_key, params)]; empty = authorised.

    `today` should be the local (Africa/Cairo) date, passed by the caller, so a
    validity window is judged by the organisation's calendar day, not the
    server's UTC day.
    """
    today = today or date.today()
    if not auth:
        return [('missing', 'missing', {})]
    out = []
    if auth.get('revoked_at'):
        out.append(('revoked', 'revoked', {}))
    for f, key in (('authorised_by_name', 'incomplete_name'), ('authorised_by_title', 'incomplete_title'),
                   ('organisation', 'incomplete_org'), ('scope', 'incomplete_scope')):
        if not str(auth.get(f) or '').strip():
            out.append(('incomplete', key, {}))
    vf, vt = _d(auth.get('valid_from')), _d(auth.get('valid_to'))
    if not vf or not vt:
        out.append(('dates', 'dates_missing', {}))
    elif vt < vf:
        out.append(('dates', 'dates_order', {}))
    elif today < vf:
        out.append(('not_yet', 'not_yet', {'d': vf.isoformat()}))
    elif today > vt:
        out.append(('expired', 'expired', {'d': vt.isoformat()}))
    if not documents_count:
        out.append(('document', 'document', {}))
    allowed = domains(auth.get('allowed_domains'))
    if not allowed:
        out.append(('domains', 'domains', {}))
    else:
        outside = sorted({e for e in recipient_emails if not in_scope(e, allowed)})
        if outside:
            extra = outside[3:]
            shown = ', '.join(outside[:3]) + (f' (+{len(extra)} more)' if extra else '')
            out.append(('out_of_scope', 'out_of_scope', {'emails': shown}))
    return out
