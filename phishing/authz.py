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
import ipaddress
from datetime import date, datetime
from email.utils import parseaddr

RECORD_TYPE = 'phishing_authorisation'

# Free webmail / consumer domains that must never be registered as a target
# domain for a simulation: they belong to the public, not to the authorising
# organisation. (Not exhaustive — a representative set of the common ones.)
FREEMAIL = {
    'gmail.com', 'googlemail.com', 'outlook.com', 'outlook.sa', 'outlook.fr', 'outlook.com.eg',
    'hotmail.com', 'hotmail.co.uk', 'hotmail.fr', 'live.com', 'live.co.uk', 'live.fr',
    'msn.com', 'windowslive.com', 'yahoo.com', 'yahoo.co.uk', 'yahoo.fr', 'yahoo.com.eg',
    'ymail.com', 'rocketmail.com', 'icloud.com', 'me.com', 'mac.com', 'aol.com', 'aim.com',
    'protonmail.com', 'proton.me', 'gmx.com', 'gmx.net', 'mail.com', 'zoho.com',
    'yandex.com', 'yandex.ru', 'tutanota.com', 'qq.com', '163.com', '126.com', 'sina.com',
    'fastmail.com', 'hushmail.com', 'link.net', 'tedata.net.eg', 'vodafone.com.eg',
}

# Snapshot of common PUBLIC SUFFIXES (registry-level names under which anyone
# may register). A target domain must not BE one of these: 'com.eg' would put
# every Egyptian company in scope. Single-label suffixes (com, eg, uk …) are
# already rejected by the "needs a dot" rule. This is not the full Public
# Suffix List — the common second-level registries for the region and the main
# markets. (publicsuffix2 / tldextract are not installed; this is the bundled
# fallback the review asked for.)
PUBLIC_SUFFIXES = frozenset('''
com.eg gov.eg edu.eg org.eg net.eg sci.eg info.eg name.eg tv.eg mil.eg eun.eg
com.sa gov.sa edu.sa org.sa net.sa med.sa sch.sa pub.sa
co.ae gov.ae ac.ae net.ae org.ae sch.ae mil.ae
com.kw gov.kw edu.kw net.kw org.kw com.qa gov.qa edu.qa net.qa org.qa
com.bh gov.bh edu.bh net.bh org.bh com.om gov.om edu.om net.om org.om co.om
com.jo gov.jo edu.jo net.jo org.jo com.lb gov.lb edu.lb net.lb org.lb
co.ma gov.ma ac.ma net.ma org.ma com.tn gov.tn ens.tn com.dz gov.dz edu.dz
com.ly gov.ly edu.ly com.iq gov.iq edu.iq com.sy com.ye com.sd com.ps
co.uk org.uk gov.uk ac.uk me.uk ltd.uk plc.uk net.uk sch.uk nhs.uk
com.au net.au org.au gov.au edu.au co.nz org.nz govt.nz ac.nz
co.jp ne.jp or.jp go.jp ac.jp co.kr go.kr or.kr ac.kr
com.cn net.cn org.cn gov.cn edu.cn com.hk gov.hk edu.hk com.sg gov.sg edu.sg
co.in net.in org.in gov.in ac.in edu.in com.pk gov.pk edu.pk
com.tr gov.tr edu.tr org.tr com.br gov.br org.br net.br com.mx gob.mx
com.ar gob.ar co.za gov.za ac.za org.za co.ke go.ke ac.ke
com.ng gov.ng edu.ng com.gh gov.gh com.ru gov.ru com.ua gov.ua co.il gov.il ac.il
github.io herokuapp.com azurewebsites.net cloudfront.net blogspot.com appspot.com
'''.split())

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
    'bad_domains': ('The authorisation lists domains that may not be targeted '
                    '(free webmail, public suffixes, IP addresses or wildcards): %(domains)s',
                    'يتضمن التفويض نطاقات لا يجوز استهدافها '
                    '(بريد مجاني أو لاحقات عامة أو عناوين IP أو رموز عامة): %(domains)s'),
    'bad_recipients': ('These recipient addresses are not valid single email addresses: %(emails)s',
                       'عناوين المستلمين التالية ليست عناوين بريد إلكتروني صحيحة: %(emails)s'),
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


def _is_ip_like(dl):
    # a literal IPv4/IPv6, or an all-numeric-and-dots string (1.2.3.4, 1.2.3)
    try:
        ipaddress.ip_address(dl)
        return True
    except ValueError:
        pass
    bare = dl.strip('[]')
    return bool(bare) and all(c.isdigit() or c == '.' for c in bare) and '.' in bare


def invalid_domains(allowed):
    """Return the entries of `allowed` that may NOT be used as a target domain:
    free webmail, a wildcard, a leading dot, a single-label domain, an IP
    address, or a public suffix (com.eg, co.uk …). An allowed target domain
    must identify the organisation — at least one dot, not public, not an IP."""
    bad = []
    for d in sorted(allowed):
        dl = str(d).strip().lower().lstrip('@')
        if (not dl or '*' in dl or ' ' in dl
                or dl.startswith('.') or dl.endswith('.') or '..' in dl
                or '.' not in dl
                or dl in FREEMAIL
                or dl in PUBLIC_SUFFIXES
                or _is_ip_like(dl)):
            bad.append(dl or str(d))
    return bad


def valid_email(email):
    """A single, plain recipient address: exactly one '@', no display name, no
    separators or control-ish characters, no '..', a dotted domain. parseaddr
    must return the address unchanged (rejects 'Name <a@b>', '<a@b>', comments)."""
    e = str(email or '').strip()
    if not e or e.count('@') != 1:
        return False
    if any(c.isspace() for c in e) or any(c in e for c in '%;,<>!"()[]\\'):
        return False
    if '..' in e:
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
    if not d:
        return False
    # exact domain, or a sub-domain under an allowed domain (a dot boundary, so
    # 'notdemo.example' is NOT under 'demo.example')
    return any(d == a or d.endswith('.' + a) for a in allowed)


def problems(auth, recipient_emails, documents_count, today=None):
    """Why this campaign may NOT be sent - [(code, message_key, params)]; empty = authorised.

    `today` should be the local (Africa/Cairo) date, passed by the caller, so a
    validity window is judged by the organisation's calendar day, not the
    server's UTC day. Stored domains and every recipient address are re-checked
    here (not only when first entered) so a record that was edited around the
    UI validation, or recipients added later, are still caught at send time.
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
        # re-validate the STORED domains, not just the ones typed in the form
        bad = invalid_domains(allowed)
        if bad:
            extra = bad[3:]
            shown = ', '.join(bad[:3]) + (f' (+{len(extra)} more)' if extra else '')
            out.append(('bad_domains', 'bad_domains', {'domains': shown}))
        allowed = {a for a in allowed if a not in bad}
        outside = sorted({e for e in recipient_emails if not in_scope(e, allowed)})
        if outside:
            extra = outside[3:]
            shown = ', '.join(outside[:3]) + (f' (+{len(extra)} more)' if extra else '')
            out.append(('out_of_scope', 'out_of_scope', {'emails': shown}))
    # every recipient address must be a valid single address (import validates
    # too, but re-check here so nothing malformed is ever sent)
    bad_rcpt = sorted({str(e) for e in recipient_emails if not valid_email(e)})
    if bad_rcpt:
        extra = bad_rcpt[3:]
        shown = ', '.join(bad_rcpt[:3]) + (f' (+{len(extra)} more)' if extra else '')
        out.append(('bad_recipients', 'bad_recipients', {'emails': shown}))
    return out
