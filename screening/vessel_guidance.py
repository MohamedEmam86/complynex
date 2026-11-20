# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Verdict and next steps of a vessel screening, from data.

verdict(res) says in one line what was found (a sanctioned ship confirmed by its IMO, a name match to confirm,
a banned ship, a listed owner, nothing) with the generic regimes; next_steps(res) returns the officer's next
steps and the documents to request, from screening/guidance/vessel_next_steps.json (bilingual, editable,
versioned). Nothing is generated at run time.
"""
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'guidance', 'vessel_next_steps.json')
_DATA = {'mtime': None, 'data': None}


def data():
    try:
        m = os.path.getmtime(_PATH)
        if _DATA['mtime'] != m:
            with open(_PATH, encoding='utf-8') as f:
                _DATA['data'], _DATA['mtime'] = json.load(f), m
    except Exception:
        _DATA['data'] = _DATA['data'] or {'situations': {}}
    return _DATA['data']


def _alerting(res):
    return (res.get('hits') or []), (res.get('ban_hits') or []), (res.get('owner_hits') or [])


def situations(res):
    hits, bans, owners = _alerting(res)
    out = []
    if any(h.get('tier') == 'CONFIRMED' for h in hits):
        out.append('confirmed')
    elif hits:
        out.append('name_only')
    if len(hits) > 1:
        out.append('several_ships')
    if any(h.get('entered_name_differs') for h in hits + bans):
        out.append('renamed')
    if res.get('related_hulls') and not hits:
        out.append('hull_number')
    if bans:
        out.append('ban')
    if owners:
        out.append('owner')
    if (res.get('risk') or {}).get('lines'):
        out.append('risk')
    if not (hits or bans or owners):
        out.append('clear')
    return list(dict.fromkeys(out))


def next_steps(res, lang='en'):
    """[{code, title, steps[], documents[]}] in the user's language (English when a text has no Arabic)."""
    sit = data().get('situations') or {}
    pick = lambda t: (t.get(lang) or t.get('en') or '') if isinstance(t, dict) else str(t or '')  # noqa: E731
    out = []
    for code in situations(res):
        s = sit.get(code)
        if not s:
            continue
        out.append({'code': code, 'title': pick(s.get('title')),
                    'steps': [pick(x) for x in s.get('steps') or []],
                    'documents': [pick(x) for x in s.get('documents') or []]})
    return out


VERDICTS = {
    'confirmed': ('Sanctioned vessel - confirmed by its identifier', 'سفينة خاضعة لعقوبات - مؤكدة بالمعرّف'),
    'potential': ('Possible sanctioned vessel - name match, confirm with the IMO number, flag and owner',
                  'سفينة محتمل خضوعها لعقوبات - تطابق في الاسم، تأكد برقم IMO ودولة العلم والمالك'),
    'possible': ('Name match to check - not confirmed', 'تطابق في الاسم يحتاج تحققًا - غير مؤكد'),
    'ban': ('Banned / excluded vessel - not a sanctions listing', 'سفينة محظورة أو مستبعدة - ليست إدراجًا على قائمة عقوبات'),
    'owner': ('Owner / operator is a listed party', 'المالك أو المشغّل طرف مدرج'),
    'clear': ('No listed vessel found', 'لم يتم العثور على سفينة مدرجة'),
    'incomplete': ('Nothing to screen', 'لا توجد بيانات للفحص'),
}


def verdict(res, lang='en'):
    """{'code', 'text', 'level'} of the whole screening: level danger / warning / info / success."""
    hits, bans, owners = _alerting(res)
    i = 1 if lang == 'ar' else 0
    t = res.get('tier')
    if t == 'INCOMPLETE':
        code, level = 'incomplete', 'secondary'
    elif hits and hits[0].get('tier') == 'CONFIRMED':
        code, level = 'confirmed', 'danger'
    elif hits and hits[0].get('tier') == 'POTENTIAL':
        code, level = 'potential', 'danger'
    elif hits:
        code, level = 'possible', 'warning'
    elif owners:
        code, level = 'owner', 'danger' if owners[0].get('tier') in ('CONFIRMED', 'POTENTIAL') else 'warning'
    elif bans:
        code, level = 'ban', 'warning'
    else:
        code, level = 'clear', 'success'
    return {'code': code, 'text': VERDICTS[code][i], 'level': level}
