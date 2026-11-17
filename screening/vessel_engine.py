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
Vessel screening engine (V2) - four layers, from certain to inferred.

  1. Identifier   IMO (current or past) = the listed ship: CONFIRMED. MMSI / call sign alone = strong
                  but not decisive (both change when a ship is re-flagged): POTENTIAL.
  2. Name         current and former names and aliases, any script: prefixes dropped, every number in
                  the name must be the same (STAR 1 is not STAR 2), fuzzy + cross-script skeleton match.
                  A name alone never confirms; a different valid IMO on both sides = a different ship.
  3. Owner        the declared owner / operator / manager is screened with the person / entity engine;
                  a listed party = "linked to a listed party". Listed ships also show their own owners.
  4. Risk         flag of convenience, invalid IMO check digit, invalid MMSI, flag changes of a listed
                  ship: a separate risk score with one line per rule. Never creates a match by itself.

Tiers use the live screening thresholds (screening/thresholds.py -> match_intel.LOW / POTENTIAL /
CONFIRMED), so the MLRO's threshold settings apply to vessels as well.

screen_vessel(...) is the single entry point (UI, bulk, API and the vessel Gold Set).
"""
import logging
import re

from screening import vessel_utils as VU

logger = logging.getLogger(__name__)

NAME_WEIGHT = 0.9          # an exact name alone scores 90: POTENTIAL, never CONFIRMED
MMSI_SCORE = 90.0
CALLSIGN_SCORE = 85.0


def _thresholds():
    try:
        from screening import match_intel as mi
        return float(mi.LOW), float(mi.POTENTIAL), float(mi.CONFIRMED)
    except Exception:
        return 75.0, 80.0, 95.0


def tier_of(score):
    low, pot, conf = _thresholds()
    if score >= conf:
        return 'CONFIRMED'
    if score >= pot:
        return 'POTENTIAL'
    if score >= low:
        return 'LOW'
    return 'BELOW'


# --------------------------------------------------------------------------- names
def _skeleton(word):
    """Consonant key shared by Arabic and Latin spellings (screening/match_intel._xs_key)."""
    try:
        from screening.match_intel import _xs_key
        return _xs_key(word.lower() if not VU.is_arabic(word) else word)
    except Exception:
        return re.sub('[aeiouyw]', '', word.lower())


def _latin(name):
    """A Latin reading of an Arabic ship name (transliteration of each word)."""
    if not VU.is_arabic(name):
        return name
    try:
        from screening.arabic_transliteration_enhanced import transliterate_to_english
        return transliterate_to_english(name)
    except Exception:
        return name


def name_score(query, listed):
    """0-100 similarity of two ship names, with the reasons. Numbers must agree exactly."""
    from rapidfuzz import fuzz
    qn, ln = VU.norm_name(query), VU.norm_name(listed)
    if not qn or not ln:
        return 0.0, []
    reasons = []
    qnum, lnum = VU.name_numbers(qn), VU.name_numbers(ln)
    if VU.is_arabic(qn) != VU.is_arabic(ln):
        q_lat = VU.norm_name(_latin(query)) if VU.is_arabic(qn) else qn
        l_lat = VU.norm_name(_latin(listed)) if VU.is_arabic(ln) else ln
        qw, lw = VU.name_words(q_lat), VU.name_words(l_lat)
        fz = fuzz.token_sort_ratio(' '.join(qw), ' '.join(lw)) if qw and lw else 0.0
        # cross-script: compare the consonant skeleton of each word as well
        qs = [_skeleton(w) for w in VU.name_words(qn)]
        ls = [_skeleton(w) for w in VU.name_words(ln)]
        sk = 100.0 if qs and qs == ls and all(qs) else (
            fuzz.token_sort_ratio(' '.join(qs), ' '.join(ls)) if qs and ls else 0.0)
        s = max(fz, sk * 0.97)
        reasons.append('compared across scripts (Arabic / Latin)')
        qnum = VU.name_numbers(q_lat) or qnum
        lnum = VU.name_numbers(l_lat) or lnum
    else:
        qw, lw = VU.name_words(qn), VU.name_words(ln)
        if not qw or not lw:
            s = 100.0 if qn == ln else 0.0
        else:
            a, b = ' '.join(qw), ' '.join(lw)
            s = max(fuzz.token_sort_ratio(a, b), fuzz.ratio(a.replace(' ', ''), b.replace(' ', '')))
            if len(qw) == len(lw) and s < 88:
                # spelling variants of the same words (NOOR / NOUR, MOHAMMED / MUHAMAD): same consonants
                qs, ls = [_skeleton(w) for w in qw], [_skeleton(w) for w in lw]
                if all(qs) and qs == ls:
                    s = 88.0
                    reasons.append('same name, another spelling')
            if len(qw) == 1 and len(lw) > 1 and qw[0] in lw:
                # one word of a longer listed name ("OCEAN" vs "OCEAN GLORY") is not that ship
                s = min(s, 60.0)
    if qnum != lnum:
        if qnum or lnum:
            reasons.append('the numbers in the names differ (%s / %s): a different ship'
                           % (' '.join(map(str, qnum)) or '-', ' '.join(map(str, lnum)) or '-'))
            s = min(s, 60.0)
    elif qnum:
        reasons.append('same number in the name')
    return round(float(s), 1), reasons


def best_name(query, names):
    best = (0.0, None, [])
    for n in names or []:
        s, r = name_score(query, n)
        if s > best[0]:
            best = (s, n, r)
    return best


# --------------------------------------------------------------------------- candidates
def _prefilter(query, cands, limit=60):
    """Cheap recall over every listed name (rapidfuzz on normalised names + the cross-script skeleton)."""
    from rapidfuzz import fuzz, process
    qn = VU.norm_name(query)
    if not qn:
        return []
    q_lat = VU.norm_name(_latin(query)) if VU.is_arabic(qn) else qn
    q_sk = ' '.join(_skeleton(w) for w in VU.name_words(qn))
    choices = {}
    for i, c in enumerate(cands):
        for n in c['names']:
            nn = VU.norm_name(n)
            if nn:
                choices[(i, n)] = nn
    keys = list(choices.keys())
    vals = [choices[k] for k in keys]
    picked = set()
    for q in {qn, q_lat}:
        for _, sc, idx in process.extract(q, vals, scorer=fuzz.token_sort_ratio, limit=limit, score_cutoff=55):
            picked.add(keys[idx][0])
    if q_sk:
        sks = [' '.join(_skeleton(w) for w in VU.name_words(v)) for v in vals]
        for _, sc, idx in process.extract(q_sk, sks, scorer=fuzz.ratio, limit=limit, score_cutoff=80):
            picked.add(keys[idx][0])
    return [cands[i] for i in picked]


def _flag_eq(a, b):
    a, b = (VU.clean_flag(a) or '').lower(), (VU.clean_flag(b) or '').lower()
    return bool(a) and a == b


# --------------------------------------------------------------------------- main
def screen_vessel(name=None, imo=None, mmsi=None, call_sign=None, flag=None, owner=None, vessel_type=None,
                  *, conn=None, candidates=None, id_index=None, screen_party=None, flags=None, links=None,
                  max_hits=25):
    """Screen one vessel. Returns
      {'query', 'warnings', 'tier', 'score', 'hits': [...], 'owner_hits': [...], 'risk': {'score','lines'},
       'near': [...] (below-threshold names shown for transparency)}

    Each hit: {watchlist_id, source, name, matched_name, imo, mmsi, call_sign, flag, flags_past, type,
               year_built, measures, owners, score, tier, layer, explanation[], fields{}}

    conn          DB connection (candidates, identifiers, flags and owner links are read through it)
    candidates    list of vessel dicts (vessel_store.load_candidates format) - tests / Gold Set
    id_index      {('IMO','9123456'): [(watchlist_id, is_current)]} - tests / Gold Set
    screen_party  callable(name) -> [{'name','score','tier','list_type'}]: the person / entity engine
    flags         {flag-name-lower: {'foc': bool, 'note': str}}
    links         {watchlist_id: [{name, role, party_listed}]}
    """
    from screening import vessel_store as VS
    q_imo, q_mmsi, q_call = VU.norm_imo(imo), VU.norm_mmsi(mmsi), VU.norm_call_sign(call_sign)
    q_name = (name or '').strip()
    query = {'name': q_name or None, 'imo': q_imo, 'mmsi': q_mmsi, 'call_sign': q_call,
             'flag': VU.clean_flag(flag), 'owner': (owner or '').strip() or None, 'type': vessel_type or None}
    warnings = []
    if imo and not q_imo:
        warnings.append('IMO number is not 7 digits: not used')
    if mmsi and not q_mmsi:
        warnings.append('MMSI is not 9 digits: not used')
    if not (q_name or q_imo or q_mmsi or q_call or query['owner']):
        return {'query': query, 'warnings': warnings + ['nothing to screen'], 'tier': 'INCOMPLETE',
                'score': 0.0, 'hits': [], 'owner_hits': [], 'risk': {'score': 0, 'lines': []}, 'near': []}

    if candidates is None:
        candidates = VS.load_candidates(conn) if conn is not None else []
    by_id = {c['watchlist_id']: c for c in candidates}

    def ids_for(kind, value):
        if not value:
            return []
        if id_index is not None:
            return id_index.get((kind, value), [])
        return VS.identifier_hits(conn, kind, value) if conn is not None else []

    hits = {}

    def add(c, score, layer, expl, matched_name=None, fields=None):
        wid = c['watchlist_id']
        h = hits.get(wid)
        if h is None or score > h['score']:
            base = {k: c.get(k) for k in ('watchlist_id', 'source', 'list_type', 'name', 'imo', 'mmsi',
                                           'call_sign', 'flag', 'flags_past', 'type', 'year_built',
                                           'measures', 'owners', 'previous_names', 'gross_tonnage',
                                           'legal_status')}
            h = dict(base, score=round(score, 1), layer=layer, explanation=list(expl),
                     matched_name=matched_name or c.get('name'), fields=fields or {})
            hits[wid] = h
        else:
            for e in expl:
                if e not in h['explanation']:
                    h['explanation'].append(e)

    # ---- layer 1: identifiers
    for kind, val, score, label in (('IMO', q_imo, 100.0, 'IMO number'), ('MMSI', q_mmsi, MMSI_SCORE, 'MMSI'),
                                    ('CALLSIGN', q_call, CALLSIGN_SCORE, 'call sign')):
        for wid, is_current in ids_for(kind, val):
            c = by_id.get(wid)
            if c is None:
                continue
            when = 'current' if is_current else 'former'
            expl = [f'same {label} ({val}, the listed ship\'s {when} {label})']
            sc = score
            if kind != 'IMO' and q_imo and c.get('imo') and c['imo'] != q_imo:
                # a different IMO on both sides: the MMSI / call sign was re-used by another ship
                sc = min(sc, 60.0)
                expl.append(f'but a different IMO number ({q_imo} / {c["imo"]}): a different ship')
            fields = {label: {'query': val, 'listed': val, 'match': True}}
            if q_name:
                ns, nm, nr = best_name(q_name, c['names'])
                fields['name'] = {'query': q_name, 'listed': nm or c['name'], 'match': ns >= 85}
                if ns < 70 and kind == 'IMO':
                    expl.append('the name differs (the ship may have been renamed)')
            add(c, sc, 'identifier', expl, fields=fields)

    # ---- layer 2: names
    if q_name:
        for c in _prefilter(q_name, candidates):
            ns, nm, nr = best_name(q_name, c['names'])
            if ns < 60:
                continue
            sc = ns * NAME_WEIGHT
            expl = [f'name match {ns:.0f}%' + (f' with "{nm}"' if nm and nm != c['name'] else '')] + nr
            if nm and nm in (c.get('previous_names') or []):
                expl.append('matched a former name of the ship')
            fields = {'name': {'query': q_name, 'listed': nm, 'match': ns >= 85}}
            if q_imo and c.get('imo'):
                fields['IMO number'] = {'query': q_imo, 'listed': c['imo'], 'match': q_imo == c['imo']}
                if q_imo != c['imo'] and VU.imo_valid(q_imo):
                    sc = min(sc, 60.0)
                    expl.append(f'different IMO number ({q_imo} / {c["imo"]}): a different ship')
            if q_mmsi and c.get('mmsi') and q_mmsi != c['mmsi']:
                fields['MMSI'] = {'query': q_mmsi, 'listed': c['mmsi'], 'match': False}
                expl.append('different MMSI (it changes when a ship is re-flagged)')
            if query['flag']:
                same = _flag_eq(query['flag'], c.get('flag')) or any(_flag_eq(query['flag'], f)
                                                                      for f in c.get('flags_past') or [])
                fields['flag'] = {'query': query['flag'], 'listed': c.get('flag'), 'match': same}
                if same and sc < 90:
                    sc = min(sc + 3.0, 90.0)
                    expl.append('same flag (current or former)')
            if vessel_type and c.get('type'):
                same_t = vessel_type.strip().lower() in str(c['type']).lower() or \
                    str(c['type']).strip().lower() in vessel_type.lower()
                fields['type'] = {'query': vessel_type, 'listed': c['type'], 'match': same_t}
            add(c, sc, 'name', expl, matched_name=nm, fields=fields)

    # ---- layer 3: owner / operator / manager
    owner_hits = []
    if query['owner'] and screen_party:
        try:
            for ph in screen_party(query['owner']) or []:
                if float(ph.get('score') or 0) >= _thresholds()[0]:
                    owner_hits.append({'query': query['owner'], 'name': ph.get('name'),
                                       'score': round(float(ph.get('score') or 0), 1),
                                       'tier': ph.get('tier') or tier_of(float(ph.get('score') or 0)),
                                       'list_type': ph.get('list_type'), 'watchlist_id': ph.get('watchlist_id')})
        except Exception as e:
            logger.warning(f'[VESSELS] owner screening failed: {e}')
            warnings.append('owner screening unavailable: screen the owner separately')

    # links of the listed ships found (their own owners, and whether those are listed too)
    if hits and links is None and conn is not None:
        try:
            links = VS.party_links(conn, list(hits.keys()))
        except Exception:
            links = {}
    for wid, h in hits.items():
        h['parties'] = (links or {}).get(wid, [])
        if any(p.get('party_listed') for p in h['parties']):
            h['explanation'].append('owned / operated by a listed party')

    # ---- layer 4: risk
    if flags is None and conn is not None:
        flags = VS.flag_risk(conn)
    flags = flags or {}
    lines, risk = [], 0
    if q_imo and not VU.imo_valid(q_imo):
        lines.append('IMO number fails its check digit (possibly false or mistyped)')
        risk += 20
    if q_mmsi and not VU.mmsi_valid(q_mmsi):
        lines.append('MMSI is not a ship station number (first digit not 2-7)')
        risk += 10
    fr = flags.get((query['flag'] or '').lower())
    if fr and fr.get('foc'):
        lines.append(f'flag of convenience registry: {query["flag"]}')
        risk += 15
    top = sorted(hits.values(), key=lambda h: -h['score'])
    if top and top[0]['score'] >= _thresholds()[0]:
        fp = [f for f in (top[0].get('flags_past') or []) if f]
        if len(fp) >= 2:
            lines.append(f'the matched listed ship changed flag {len(fp)} times')
            risk += 10
        if top[0].get('previous_names'):
            lines.append('the matched listed ship has former names')
            risk += 5
    if owner_hits:
        lines.append('the declared owner / operator matches a listed party')
        risk += 40

    low = _thresholds()[0]
    for h in top:
        h['tier'] = tier_of(h['score'])
    alerts = [h for h in top if h['score'] >= low][:max_hits]
    near = [{'name': h['name'], 'matched_name': h['matched_name'], 'score': h['score'],
             'explanation': h['explanation']} for h in top if h['score'] < low][:5]
    score = alerts[0]['score'] if alerts else 0.0
    if owner_hits:
        score = max(score, max(o['score'] for o in owner_hits) * 0.95)
    tier = tier_of(score) if (alerts or owner_hits) else 'CLEAR'
    if tier == 'BELOW':
        tier = 'CLEAR'
    return {'query': query, 'warnings': warnings, 'tier': tier, 'score': round(score, 1), 'hits': alerts,
            'owner_hits': owner_hits, 'risk': {'score': min(risk, 100), 'lines': lines}, 'near': near}


def party_screener():
    """screen_party callable backed by the person / entity engine (company screening, no media)."""
    def _run(name):
        from screening.routes import get_engine
        eng = get_engine()
        res = eng.screen_person(name=name, entity_type='ENTITY', include_media=False)
        out = []
        for m in (res or {}).get('matches') or []:
            if str(m.get('entity_type') or '').upper() == 'VESSEL':
                continue        # a ship is not an owner; vessel hits come from layers 1-2
            out.append({'name': m.get('full_name') or m.get('name'), 'score': m.get('match_score') or 0,
                        'tier': (m.get('decision') or {}).get('tier'), 'list_type': m.get('list_type'),
                        'watchlist_id': m.get('entity_id')})
        return out
    return _run
