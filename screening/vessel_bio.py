# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
The Vessel BIO: everything ComplyNex holds about one listed ship, in one bilingual view.

Built only from data already held: the list records of the same ship (same IMO) as materialised by
vessel_store.sync (vessel_profile, vessel_identifier, vessel_party_link), the flag-risk reference, the names
ComplyNex knows (vessel_known_names) and the list records' own dates. Nothing is fetched. A field no list
carries is simply absent (the page hides it). The publishing lists, their programme codes, source links and
descriptions are kept apart (``internal``) for the platform superadmin only.
"""
import json
import re
from datetime import date

# --------------------------------------------------------------------------- vocabularies (EN / AR)
# vessel types: (pattern over the list's wording, English or French, code)
_TYPE_RULES = [
    (r'crude', 'crude_tanker'), (r'lng|m[ée]thanier|liquefied natural', 'lng_carrier'),
    (r'lpg|liquefied petroleum|gas carrier|gaz', 'gas_carrier'),
    (r'chemical|chimique|oilchem', 'chemical_oil_tanker'),
    (r'products? tanker|produits p[ée]troliers|product', 'product_tanker'),
    (r'bitumen|asphalt', 'bitumen_tanker'), (r'bunker', 'bunkering_tanker'),
    (r'tanker|p[ée]trolier|citerne', 'oil_tanker'),
    (r'bulk|vraquier|woodchip|ore carrier', 'bulk_carrier'), (r'container|porte-conteneurs', 'container_ship'),
    (r'refrigerated|reefer|frigorifique', 'reefer'), (r'vehicle|car carrier|ro-?ro|roll-on', 'roro'),
    (r'livestock', 'livestock_carrier'), (r'passenger|ferry|cruise|passagers', 'passenger'),
    (r'general cargo|multipurpose|multi purpose|cargo classique|cargo', 'general_cargo'),
    (r'fishing|fish|p[êe]che', 'fishing'), (r'tug|remorqueur', 'tug'),
    (r'offshore|supply|platform', 'offshore'), (r'research|survey', 'research'), (r'yacht', 'yacht'),
    (r'heavy load|heavy lift', 'heavy_load'), (r'broken up|scrapped|demolished', 'broken_up'),
    (r'total loss|sunk', 'total_loss'),
]
TYPES = {
    'crude_tanker': ('Crude oil tanker', 'ناقلة نفط خام'), 'lng_carrier': ('LNG carrier', 'ناقلة غاز طبيعي مسال'),
    'gas_carrier': ('Gas carrier (LPG)', 'ناقلة غاز (غاز بترول مسال)'),
    'chemical_oil_tanker': ('Chemical / oil products tanker', 'ناقلة كيماويات / منتجات نفطية'),
    'product_tanker': ('Oil products tanker', 'ناقلة منتجات نفطية'), 'bitumen_tanker': ('Bitumen tanker', 'ناقلة أسفلت'),
    'bunkering_tanker': ('Bunkering tanker', 'ناقلة تزويد بالوقود'), 'oil_tanker': ('Oil tanker', 'ناقلة نفط'),
    'bulk_carrier': ('Bulk carrier', 'ناقلة بضائع سائبة'), 'container_ship': ('Container ship', 'سفينة حاويات'),
    'reefer': ('Refrigerated cargo ship', 'سفينة بضائع مبردة'), 'roro': ('Ro-Ro / vehicle carrier', 'سفينة دحرجة / ناقلة مركبات'),
    'livestock_carrier': ('Livestock carrier', 'ناقلة مواشٍ'), 'passenger': ('Passenger ship / ferry', 'سفينة ركاب / عبّارة'),
    'general_cargo': ('General cargo ship', 'سفينة بضائع عامة'), 'fishing': ('Fishing vessel', 'سفينة صيد'),
    'tug': ('Tug', 'قاطرة بحرية'), 'offshore': ('Offshore supply vessel', 'سفينة إمداد بحري'),
    'research': ('Research vessel', 'سفينة أبحاث'), 'yacht': ('Yacht', 'يخت'),
    'heavy_load': ('Heavy-load carrier', 'ناقلة حمولات ثقيلة'), 'broken_up': ('Broken up (scrapped)', 'تم تفكيكها'),
    'total_loss': ('Total loss', 'خسارة كلية'),
}

# who the party is for the ship (vessel_party_link.role)
ROLES = {
    'registered_owner': ('Registered owner', 'المالك المسجل'), 'owner': ('Owner', 'المالك'),
    'beneficial_owner': ('Beneficial owner', 'المالك المستفيد'),
    'beneficial_interest': ('Held in the interest of', 'مملوكة لصالح'),
    'owner_operator': ('Owner / operator', 'المالك / المشغّل'), 'operator': ('Operator', 'المشغّل'),
    'ship_manager': ('Ship manager', 'مدير السفينة'), 'ism_manager': ('ISM manager', 'مدير السلامة (ISM)'),
    'commercial_manager': ('Commercial manager', 'المدير التجاري'), 'security_manager': ('Security manager', 'مدير الأمن'),
    'class_society': ('Classification society', 'هيئة التصنيف'),
    'recognised_org': ('Recognised organisation (flag state)', 'منظمة معترف بها (لدولة العلم)'),
    'pi_club': ('P&I insurer', 'نادي الحماية والتعويض (P&I)'), 'master': ('Master', 'الربان'),
    'crew': ('Crew member', 'أحد أفراد الطاقم'), 'former_owner': ('Former owner', 'مالك سابق'),
    'former_owner_operator': ('Former owner / operator', 'مالك / مشغّل سابق'),
    'associated': ('Associated company', 'شركة مرتبطة'), 'company': ('Linked company', 'شركة مرتبطة'),
    'linked': ('Linked party', 'طرف مرتبط'), 'manager': ('Manager', 'مدير'),
}
# people named as crew: shown to the platform superadmin only (personal data, not needed for the decision)
PERSONAL_ROLES = ('master', 'crew')
# the order of the ownership & management section
ROLE_ORDER = ['registered_owner', 'owner', 'beneficial_owner', 'beneficial_interest', 'owner_operator', 'operator',
              'ship_manager', 'ism_manager', 'commercial_manager', 'security_manager', 'class_society',
              'recognised_org', 'pi_club', 'master', 'crew', 'associated', 'company', 'linked', 'former_owner',
              'former_owner_operator']

# what the list records' topics say about the ship (indicators, never a match)
TOPICS = {
    'mare.shadow': ('Reported as part of the shadow / dark fleet', 'مذكورة ضمن "أسطول الظل"'),
    'mare.detained': ('Detained by port-state control', 'احتُجزت في رقابة دولة الميناء'),
    'mare.sts': ('Ship-to-ship transfers reported', 'عمليات نقل من سفينة إلى سفينة'),
    'export.control.linked': ('Linked to export-control listings', 'مرتبطة بقوائم ضوابط التصدير'),
    'sanction.linked': ('Linked to a sanctioned party', 'مرتبطة بطرف خاضع لعقوبات'),
    'sanction.control': ('Controlled by a sanctioned party', 'تحت سيطرة طرف خاضع لعقوبات'),
    'reg.warn': ('Regulatory warning', 'تحذير رقابي'), 'debarment': ('Debarment / exclusion', 'حظر / استبعاد'),
    'crime.terror': ('Terrorism-related', 'مرتبطة بالإرهاب'),
}
# port-state-control regions (never the publishing authority)
PSC_REGIONS = {'tokyo': ('Asia-Pacific', 'آسيا والمحيط الهادئ'), 'black_sea': ('Black Sea', 'البحر الأسود'),
               'abuja': ('West and Central Africa', 'غرب ووسط أفريقيا'), 'paris': ('Europe and North Atlantic', 'أوروبا وشمال الأطلسي'),
               'med': ('Mediterranean', 'البحر المتوسط'), 'indian': ('Indian Ocean', 'المحيط الهندي'),
               'riyadh': ('Arabian Gulf', 'الخليج العربي'), 'caribbean': ('Caribbean', 'الكاريبي'),
               'vina': ('Latin America', 'أمريكا اللاتينية'), 'uscg': ('United States', 'الولايات المتحدة')}


def pick(pair, lang):
    return pair[1] if lang == 'ar' else pair[0]


def type_code(text):
    t = str(text or '').lower()
    for rx, code in _TYPE_RULES:
        if re.search(rx, t):
            return code
    return None


def type_label(text, lang='en'):
    """The ship type in the reader's language; the list's own wording when it fits no type."""
    code = type_code(text)
    return pick(TYPES[code], lang) if code else (str(text).strip() if text else None)


def psc_region(dataset, lang='en'):
    d = str(dataset or '').lower()
    for k, pair in PSC_REGIONS.items():
        if k in d:
            return pick(pair, lang)
    return pick(('Other region', 'منطقة أخرى'), lang)


def _j(v, default=None):
    if v is None or v == '':
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return default


def _num(v):
    """'99,087' / '2693.0' -> 99087 / 2693 (None when there is no number)."""
    m = re.search(r'\d[\d,. ]*', str(v or ''))
    if not m:
        return None
    s = re.sub(r'[ ,]', '', m.group(0))
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f >= 1 else None


def _first(recs, key):
    return next((r[key] for r in recs if r.get(key)), None)


def build(recs, idents, parties, *, flags=None, known=None, psc_recs=None, lang='en', today=None):
    """The BIO of one ship.
    recs      the ship's list records (vessel_profile joined with screening_watchlist), active first
    idents    vessel_identifier rows of the active records (kind, value_norm, is_current, check_ok)
    parties   [{name, role, party_listed, role_label, start, end, country, party_type}] of the ship
    flags     vessel_store.flag_risk(); known: vessel_known_names rows; psc_recs: the ship's records that never
              alert (port-state control, analysis) with first_seen / last_seen and risk datasets
    Returns {'identity', 'history', 'ownership', 'sanctions', 'risk', 'known_names', 'internal'}."""
    from screening import vessel_provenance as VP
    from screening import vessel_flags as VF
    from screening import vessel_utils as VU
    today = today or date.today()
    active = [r for r in recs if r.get('is_active')] or recs
    alerting = [r for r in active if VP.alerts(r.get('provenance') or VP.SANCTION)] or active
    # ---------------------------------------------------------------- identity
    flag = _first(alerting, 'current_flag') or _first(active, 'current_flag')
    fr = {}
    if flag and flags:
        fr = flags.get(flag.lower()) or flags.get((VU.flag_code(flag) or '-').lower()) or {}
    vtype = _first(alerting, 'vessel_type') or _first(active, 'vessel_type')
    build_date = _first(active, 'build_date')
    yb = _first(active, 'year_built') or (build_date[:4] if build_date else None)
    year = int(yb[:4]) if yb and str(yb)[:4].isdigit() else None
    dwt = max((_num(r.get('deadweight')) or 0 for r in active), default=0) or None
    # some lists put the deadweight in their 'tonnage' field: a gross tonnage equal to the deadweight is not one
    gts = [g for g in (_num(r.get('gross_tonnage')) for r in active) if g and g != dwt]
    gt = max(gts) if gts else None
    imo = _first(alerting, 'imo') or _first(active, 'imo')
    cls = [p for p in parties if p.get('role') == 'class_society']
    identity = {
        'name': alerting[0]['full_name'], 'imo': imo,
        'imo_valid': (VU.imo_valid(imo) if imo else None),
        'mmsi': _first(alerting, 'mmsi') or _first(active, 'mmsi'),
        'call_sign': _first(alerting, 'call_sign') or _first(active, 'call_sign'),
        'flag': flag, 'flag_label': VF.name(flag, lang) if flag else None,
        'flag_foc': bool(fr.get('foc')), 'flag_high_risk': bool(fr.get('high_risk')),
        'flag_note': fr.get('note'), 'false_flag': bool(flag and '(false flag)' in flag),
        'type': vtype, 'type_label': type_label(vtype, lang), 'type_code': type_code(vtype),
        'gross_tonnage': gt, 'deadweight': dwt, 'year_built': year, 'build_date': build_date,
        'age': (today.year - year) if year and 1850 < year <= today.year else None,
        'registration_number': _first(active, 'registration_number'),
        'class_society': cls[0]['name'] if cls else None,
    }
    # ---------------------------------------------------------------- names, flags and identifiers over time
    prev = list(dict.fromkeys(x for r in active for x in _j(r.get('previous_names'), []) or []))
    current = identity['name']
    names_now = []
    for r in active:
        names_now += [r['full_name']] + (_j(r.get('aliases'), []) or [])
    prev_u = {VU.norm_name(p) for p in prev}
    others = [n for n in dict.fromkeys(names_now) if n and VU.norm_name(n) != VU.norm_name(current)
              and VU.norm_name(n) not in prev_u]
    past_flags = list(dict.fromkeys(f for r in active for f in _j(r.get('flag_history'), []) or [] if f and f != flag))
    timeline = []
    for k in known or []:
        timeline.append({'kind': 'known_name', 'name': k['name'], 'date': str(k.get('effective_date') or '')[:10] or None,
                         'note_kind': k.get('kind')})
    timeline.append({'kind': 'current_name', 'name': current, 'date': None})
    for p in prev:
        timeline.append({'kind': 'former_name', 'name': p, 'date': None})
    other_ids = [{'kind': i['kind'], 'value': i['value_norm'], 'current': bool(i['is_current'])}
                 for i in idents if i['kind'] in ('MMSI', 'CALLSIGN') and not i['is_current']]
    history = {'timeline': timeline, 'former_names': prev, 'other_names': others[:30],
               'renamed': bool(prev) or any(k.get('kind') == 'new_name' for k in known or []),
               'flag': identity['flag_label'],
               'past_flags': [{'code': f, 'label': VF.name(f, lang)} for f in past_flags],
               'flag_changes': len(past_flags), 'other_identifiers': other_ids}
    # ---------------------------------------------------------------- ownership and management
    by_role = {}
    seen = set()
    from screening.vessel_store import party_key
    for p in parties:
        k = (party_key(p.get('name')), p.get('role'))
        if not p.get('name') or k in seen:
            continue
        seen.add(k)
        by_role.setdefault(p.get('role') or 'linked', []).append({
            'name': p['name'], 'listed': bool(p.get('party_listed')), 'country': p.get('country'),
            'country_label': VF.name(p['country'], lang) if p.get('country') and len(str(p['country'])) <= 3 else p.get('country'),
            'since': p.get('start'), 'until': p.get('end'), 'as_of': p.get('as_of'), 'wording': p.get('role_label'),
            'party_type': p.get('party_type')})
    ownership = []
    for role in ROLE_ORDER + sorted(set(by_role) - set(ROLE_ORDER)):
        if role in by_role:
            ownership.append({'role': role, 'label': pick(ROLES.get(role, (role, role)), lang),
                              'parties': sorted(by_role[role], key=lambda x: (not x['listed'], x['name']))})
    # ---------------------------------------------------------------- sanctions status
    status = max((r.get('provenance') or VP.SANCTION for r in active), key=lambda x: VP.ORDER.get(x, 0))
    dates = sorted({str(r['listed_on'])[:10] for r in alerting if r.get('listed_on')})
    first_seen = min((str(r['first_seen'])[:10] for r in alerting if r.get('first_seen')), default=None)
    sanctions = {
        'status': status, 'status_label': pick(VP.LABELS.get(status, (status, status)), lang),
        'alerts': VP.alerts(status), 'is_active': any(r.get('is_active') for r in recs),
        'regimes': sorted({x for r in alerting for x in _j(r.get('regimes'), []) or []}),
        'measures': list(dict.fromkeys(x for r in alerting for x in _j(r.get('measures'), []) or [])),
        'lists': len({r['source'] for r in alerting if VP.alerts(r.get('provenance') or VP.SANCTION)}),
        'listed_on': dates[0] if dates else None, 'listing_dates': dates,
        'on_record_since': first_seen,
    }
    # ---------------------------------------------------------------- risk
    topics = sorted({t for r in active + list(psc_recs or []) for t in _j(r.get('topics'), []) or []})
    psc_ds = sorted({d for r in list(active) + list(psc_recs or []) for d in _j(r.get('risk_datasets'), []) or []})
    psc_dates = sorted(str(r.get(k))[:10] for r in psc_recs or [] for k in ('first_seen', 'last_seen') if r.get(k))
    risk = {
        'score': max(int(r.get('risk_score') or 0) for r in active),
        'lines': list(dict.fromkeys(x for r in active for x in _j(r.get('risk_lines'), []) or [])),
        'indicators': [{'code': t, 'label': pick(TOPICS[t], lang)} for t in topics if t in TOPICS],
        'psc_records': len(psc_ds),
        'psc_regions': sorted({psc_region(d, lang) for d in psc_ds}),
        'psc_first': psc_dates[0] if psc_dates else None, 'psc_last': psc_dates[-1] if psc_dates else None,
        'listed_parties': sum(1 for g in ownership for p in g['parties'] if p['listed']),
        'renamed': history['renamed'], 'flag_changes': len(past_flags),
    }
    internal = [{'source': r['source'], 'source_id': r.get('source_id'), 'active': r.get('is_active'),
                 'listed_on': r.get('listed_on'), 'provenance': r.get('provenance'),
                 'datasets': _j(r.get('datasets'), []) or [],
                 'urls': _j(r.get('source_urls'), []) or [], 'description': r.get('description')} for r in recs]
    return {'identity': identity, 'history': history, 'ownership': ownership, 'sanctions': sanctions,
            'risk': risk, 'known_names': list(known or []), 'internal': internal}
