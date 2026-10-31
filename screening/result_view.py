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
What the analyst sees on a screening result: the verdict and the required
action, why each hit scored as it did (name elements, identifiers), what the
list says about the listed person, which lists were searched and how fresh
they are, and what the news search actually covered.

Pure functions over the stored result so the page can be tested without a
browser.
"""
import json
import re
import time

from screening import match_intel as mi

TIER_LABEL = {
    'CONFIRMED': 'Confirmed match', 'POTENTIAL': 'Potential match',
    'LOW': 'Low-confidence lead', 'BELOW': 'Below threshold',
}

IDENTITY_LABEL = {
    'id_match': ('Same national ID', 'match'),
    'id_conflict': ('Different national ID', 'conflict'),
    'dob_conflict': ('Date of birth differs', 'conflict'),
    'gender_conflict': ('Gender differs (from the national ID)', 'conflict'),
    'country_conflict': ('Nationality differs (does not lower the name score)', 'unknown'),
    'corroborated': ('An identifier agrees', 'match'),
    'unknown': ('No identifier to compare — decided on the name', 'unknown'),
}

SOURCE_LABEL = {
    'ofac': 'OFAC SDN (US Treasury)', 'ofac_sdn': 'OFAC SDN (US Treasury)',
    'un': 'UN Security Council Consolidated List', 'un_consolidated': 'UN Security Council Consolidated List',
    'eu': 'EU Financial Sanctions', 'eu_sanctions': 'EU Financial Sanctions',
    'uk_hmt': 'UK HM Treasury (OFSI)', 'hmt': 'UK HM Treasury (OFSI)', 'uk': 'UK HM Treasury (OFSI)',
    'emlcu': 'EMLCU — Egyptian terrorist lists', 'emlcu_egypt': 'EMLCU — Egyptian terrorist lists',
    'pma_ps': 'Palestine national list (UNSCR 1373)', 'pma_ps_national_1373': 'Palestine national list (UNSCR 1373)',
    'pma_ps_reg': 'Palestine Monetary Authority - AML/CFT regulatory measures',
    'pma_ps_regulatory_art58': 'Palestine Monetary Authority - AML/CFT regulatory measures',
    'INTERNAL_BLACKLIST': 'Internal list (asset-freeze orders / local & UN terrorist lists)',
    'internal_blacklist': 'Internal list (asset-freeze orders / local & UN terrorist lists)',
    'INTERNAL_PEP': 'Internal PEP list', 'internal_pep': 'Internal PEP list',
    'opensanctions_pep': 'Global PEP database (OpenSanctions)',
    'open_sanctions_pep_eg': 'Egypt PEP (OpenSanctions)', 'wikidata_pep_eg': 'Egypt PEP (Wikidata)',
}


def source_label(m):
    ds = str(m.get('dataset') or '').lower()
    src = str(m.get('source') or '')
    if ds == 'wikidata':
        return 'Egypt PEP — Wikidata (via OpenSanctions)'
    if ds == 'opensanctions_peps':
        return 'Global PEP database (OpenSanctions)'
    return SOURCE_LABEL.get(src) or SOURCE_LABEL.get(src.lower()) or m.get('source_name') or \
        (src.replace('_', ' ').title() if src else (m.get('dataset') or 'Unknown list'))


def tier_of(m):
    d = m.get('decision') or {}
    if d.get('tier'):
        return d['tier']
    s = float(m.get('match_score') or 0)          # results saved before the decision layer
    try:
        from screening import thresholds
        thresholds.apply()
    except Exception:
        pass
    return 'CONFIRMED' if s >= mi.CONFIRMED else 'POTENTIAL' if s >= mi.POTENTIAL else \
        'LOW' if s >= mi.LOW else 'BELOW'


def _mask_id(v):
    v = _jsonish(v)
    if isinstance(v, str) and ',' in v:
        # several identifiers on the record: keep the ones that carry digits
        parts = [x.strip() for x in v.split(',') if re.search(r'\d{4,}', x)]
        return ', '.join(_mask_id(x) for x in parts) or None
    d = re.sub(r'\D', '', str(v or ''))
    if len(d) >= 10:
        return d[:7] + '•' * (len(d) - 9) + d[-2:]
    return str(v or '').strip() or None


def _jsonish(v):
    """Lists stored as JSON text ('["Venezuela"]') -> a readable string."""
    if isinstance(v, str) and v.strip()[:1] in ('[', '{'):
        try:
            v = json.loads(v)
        except Exception:
            return v
    if isinstance(v, dict):
        v = [f"{k}: {x}" for k, x in v.items() if x]
    if isinstance(v, (list, tuple)):
        v = ', '.join(str(x) for x in v if x not in (None, '', [], {}))
    return v


def _first(*vals):
    for v in vals:
        v = _jsonish(v)
        if v not in (None, '', '[]', '{}') and str(v).strip():
            return str(v).strip()
    return None


def _props(m):
    p = m.get('properties')
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except Exception:
            p = {}
    return p if isinstance(p, dict) else {}


def _details(m):
    d = m.get('details')
    return d if isinstance(d, dict) else {}


def _bio(m):
    d = m.get('details')
    return d.strip() if isinstance(d, str) and d.strip() and not d.strip().startswith('{') else None


def _aliases(m):
    out = []
    for f in ('aliases', 'aliases_arabic'):
        v = m.get(f)
        if isinstance(v, str) and v.strip()[:1] == '[':
            try:
                v = json.loads(v)
            except Exception:
                pass
        if isinstance(v, str):
            v = re.split(r'\s*[|;]\s*', v)
        for a in v or []:
            a = str(a).strip()
            if a and a not in out:
                out.append(a)
    return out[:12]


def match_view(m, kind, inputs):
    """Everything the card shows for one hit."""
    # aggregated databases: what the record is (sanctions, PEP, debarment, background data ...);
    # its kind decides the card colour, the section and the default action
    _nat = None
    try:
        from screening import list_category as _lc
        _nat = _lc.nature(m)
    except Exception:
        _nat = None
    if _nat:
        kind = _nat['kind']
    d = m.get('decision') or {}
    p, det = _props(m), _details(m)
    tier = tier_of(m)
    ar_name = _first(m.get('watchlist_name_ar'), m.get('full_name_arabic'),
                     m.get('original_name') if mi.is_arabic(m.get('original_name') or '') else None)
    lat_name = _first(m.get('full_name') if not mi.is_arabic(m.get('full_name') or '') else None,
                      m.get('original_name') if not mi.is_arabic(m.get('original_name') or '') else None)
    listed_nid = _first(m.get('national_id'), m.get('national_id_numbers'))
    listed_dob = _first(m.get('date_of_birth'), m.get('year_of_birth'), p.get('birthDate'))
    listed_nat = _first(m.get('nationality'), m.get('countries'), p.get('nationality'), p.get('country'))
    ident = d.get('identity') or 'unknown'
    id_label, id_state = IDENTITY_LABEL.get(ident, (ident, 'unknown'))

    def row(label, screened, listed, compare):
        if not screened and not listed:
            return None
        if screened and listed:
            state = compare
        else:
            state = 'missing'
        return {'label': label, 'screened': screened or '—', 'listed': listed or '—', 'state': state}

    nid_state = {'id_match': 'match', 'id_conflict': 'conflict', 'gender_conflict': 'conflict'}.get(ident, 'unknown')
    _st = {'agree': 'match', 'differ': 'conflict'}
    if 'dob' in d or 'country' in d:
        dob_state = _st.get(d.get('dob'), 'unknown')
        nat_state = _st.get(d.get('country'), 'unknown')
    else:                       # results saved before these fields existed
        dob_state = 'conflict' if ident == 'dob_conflict' else ('match' if ident in ('corroborated', 'id_match') else 'unknown')
        nat_state = 'conflict' if ident == 'country_conflict' else ('match' if ident in ('corroborated', 'id_match') else 'unknown')
    identity_rows = [r for r in (
        row('National ID', _mask_id(inputs.get('national_id')), _mask_id(listed_nid), nid_state),
        row('Date of birth', _first(inputs.get('dob')), listed_dob, dob_state),
        row('Nationality', _first(inputs.get('nationality')), listed_nat, nat_state),
    ) if r]

    nm = d.get('name') or {}
    matched = [{'listed': a, 'screened': b} for a, b in (nm.get('matched') or [])]
    if kind == 'SANCTIONS':
        action = {'CONFIRMED': 'Do not onboard or process. Freeze funds without delay and report to EMLCU and the supervisory regulator.',
                  'POTENTIAL': 'Hold the relationship/transaction. Verify identity with the national ID and date of birth, then decide.',
                  'LOW': 'Review and record why it is or is not the same person. Not an alert on its own.'}
    elif kind == 'PEP':
        action = {'CONFIRMED': 'Enhanced due diligence: source of funds and wealth, senior-management approval, enhanced ongoing monitoring.',
                  'POTENTIAL': 'Confirm whether the customer is this PEP (or a family member / close associate) before onboarding.',
                  'LOW': 'Review and record the conclusion.'}
    elif str(m.get('list_type') or '').upper() == 'REGULATORY' or str(m.get('source') or '').lower().endswith('_reg'):
        action = {'CONFIRMED': 'Regulatory measure on record: enhanced due diligence on the institution / person, '
                               'record the measure and its date, and decide the relationship with compliance approval.',
                  'POTENTIAL': 'Confirm whether the customer is the institution / person the measure was taken against.',
                  'LOW': 'Review and record the conclusion.'}
    else:
        action = {'CONFIRMED': 'Escalate to compliance for a decision.', 'POTENTIAL': 'Review before proceeding.',
                  'LOW': 'Review and record the conclusion.'}
    if _nat and _nat['action']:
        action = {'CONFIRMED': _nat['action'], 'POTENTIAL': _nat['action'], 'LOW': 'Review and record the conclusion.'}
    return {
        'kind': kind, 'nature': _nat, 'tier': tier, 'tier_label': TIER_LABEL.get(tier, tier),
        'score': float(m.get('match_score') or 0),
        'original_score': d.get('original_score'),
        'ar_name': ar_name, 'lat_name': lat_name,
        'display_name': ar_name or lat_name or m.get('candidate_name') or '—',
        'source': source_label(m),
        'also_listed_in': m.get('also_listed_in') or [],
        'cluster': m.get('cluster') if isinstance(m.get('cluster'), dict) else None,
        'ref': '%s:%s' % (str(m.get('source') or '').upper(),
                          m.get('entity_id') if str(m.get('source') or '').upper().startswith('INTERNAL') else m.get('id')),
        'grouped_under': m.get('grouped_under'),
        'grouped_hits': [dict(g, source_label=SOURCE_LABEL.get(str(g.get('source') or '').lower(), g.get('source')),
                              tier_label=TIER_LABEL.get(g.get('tier')))
                         for g in (m.get('grouped_hits') or []) if isinstance(g, dict)][:12],
        'entity_type': _first(m.get('entity_type')),
        'category': _first(m.get('category'), det.get('category'), p.get('topics')),
        'program': _first(p.get('program'), p.get('programs'), p.get('sanctionsProgram'), det.get('program'), det.get('programs'), m.get('program')),
        'position': _first(m.get('position'), det.get('position'), p.get('position')),
        'reason': _first(m.get('reason'), det.get('reason'), p.get('reason'), p.get('remarks')),
        'identifiers': _first(det.get('identifiers'), p.get('identifiers')),
        'notes': _first(det.get('notes'), p.get('notes')),
        'bio': _bio(m),
        'aliases': _aliases(m),
        'risk_level': _first(m.get('risk_level')),
        'listed_since': _first(p.get('listingDate'), p.get('createdAt'), m.get('first_seen'), m.get('created_at')),
        'identity': ident, 'identity_label': id_label, 'identity_state': id_state,
        'gender_differs': d.get('gender') == 'differ',
        'identity_rows': identity_rows,
        'reasons': [_reason(r) for r in (d.get('reasons') or [])],
        'judged_against': d.get('judged_against'),
        'name_matched': matched,
        'name_missing': nm.get('missing_from_query') or [],
        'name_extra': nm.get('extra_in_query') or [],
        'name_order_ok': nm.get('order_ok'),
        'name_complete': nm.get('complete'),
        'action': action.get(tier),
        'url': _profile_url(m),
        'profile_src': m.get('source'),
        'profile_rec': m.get('entity_id') if str(m.get('source') or '').upper().startswith('INTERNAL') else m.get('id'),
        'has_decision': bool(d),
    }


_REASON_PREFIX = ('name structure: ', 'not in the customer name: ', 'extra in the customer name: ')


def _reason(r):
    """(text to translate, untranslated detail) so prefixes can be translated."""
    r = str(r)
    for p in _REASON_PREFIX:
        if r.startswith(p):
            return {'t': p.strip(': ').strip(), 'a': r[len(p):]}
    if r.endswith(')') and ' (' in r:
        i = r.index(' (')
        return {'t': r[:i], 'a': r[i + 1:]}
    return {'t': r, 'a': ''}


def _profile_url(m):
    u = str(m.get('source_url') or '')
    if u.startswith('http'):
        return u
    if u and m.get('source') in ('opensanctions', 'opensanctions_pep'):
        return f'https://www.opensanctions.org/entities/{u}/'
    return None


def overall(sanctions, peps, others, am_summary, adverse_hits):
    """The single verdict at the top of the page and what the analyst must do."""
    def best(views):
        order = {'CONFIRMED': 3, 'POTENTIAL': 2, 'LOW': 1, 'BELOW': 0}
        return max([order.get(v['tier'], 0) for v in views] or [0])
    # freeze wording only for real sanctions / terror listings; criminal / wanted lists and links to a
    # sanctioned party stay on the strict side but are not freeze orders
    _freeze = ('SANCTIONS', 'TERROR', 'UNCLASSIFIED')
    strict = [v for v in sanctions if (v.get('nature') or {}).get('code') not in (None,) + _freeze]
    sanctions = [v for v in sanctions if v not in strict]
    s, p, o = best(sanctions), best(peps), best(others)
    s2 = best(strict)
    am = (am_summary or {}).get('risk_level')
    if s == 3:
        return ('danger', 'Confirmed sanctions match',
                'Do not proceed. Freeze funds without delay, file the report to EMLCU and notify the supervisory regulator. Document the decision below.')
    if s == 2:
        return ('danger', 'Potential sanctions match — review required',
                'Hold onboarding/transactions until the analyst confirms or clears the match with the national ID and date of birth.')
    if s2 >= 2:
        return ('danger', 'Serious list match — MLRO decision required',
                'The match is on a criminal / wanted list or linked to a sanctioned party, which is not a freeze order on its own. '
                'Hold, confirm the identity, apply enhanced due diligence and let the MLRO decide; consider a suspicious transaction report.')
    if p == 3:
        return ('warning', 'Politically exposed person',
                'Enhanced due diligence and senior-management approval are required before the relationship continues.')
    if p == 2 or o >= 2:
        return ('warning', 'Potential match — review required',
                'Confirm or clear the match before proceeding, and record the rationale.')
    if am in ('HIGH', 'MEDIUM'):
        return ('warning', 'Adverse media found',
                'No list match, but the person is named in negative news. Review the articles and decide on enhanced due diligence.')
    if s == 1 or s2 == 1 or p == 1 or o == 1 or am == 'LOW':
        return ('info', 'Low-confidence leads only',
                'No alert. Review the leads below and record why they are not this person.')
    if am in ('PENDING',):
        return ('secondary', 'Lists clear — news search running', 'The adverse media search is still running.')
    if am in ('TIMEOUT', 'ERROR'):
        return ('secondary', 'Lists clear — news search incomplete',
                'No list match. The adverse media search did not complete: re-run it before closing.')
    return ('success', 'Clear — no match', 'No list match and no adverse media. Proceed with standard due diligence.')


AM_LEVEL = {
    'HIGH': ('High risk', 'The person is named in news about terrorism, sanctions or financial crime. Escalate.'),
    'MEDIUM': ('Medium risk', 'The person is named in news about criminal proceedings or serious allegations. Enhanced due diligence.'),
    'LOW': ('Low risk', 'Weak or partial-name adverse news. Review and record the conclusion.'),
    'CLEAR': ('No adverse media', 'No adverse news naming this person was found.'),
    'PENDING': ('Running', 'The news search is running.'),
    'TIMEOUT': ('Incomplete', 'News sources did not answer in time. Re-run the search.'),
    'ERROR': ('Incomplete', 'News sources did not answer. Re-run the search.'),
}

_COVERAGE = {'t': 0, 'data': None}


def coverage(ttl=600, at=None):
    """Lists searched, their size, last update and version (cached for ten minutes).
    With `at` (when the screening ran) each list also carries the version in force then."""
    rows = _coverage_rows(ttl)
    if not at or not rows:
        return rows
    try:
        from screening import list_versions as LV
        v_at = LV.versions_at_cached(at)
    except Exception:
        v_at = {}
    return [dict(r, version_at=v_at.get(r.get('source'))) for r in rows]


def _coverage_rows(ttl):
    if _COVERAGE['data'] is not None and time.time() - _COVERAGE['t'] < ttl:
        return _COVERAGE['data']
    rows = []
    try:
        from screening import quality_service as qs
        for f in qs.list_freshness():
            rows.append({'name': SOURCE_LABEL.get(f['source'], f['source']), 'records': f['active'],
                         'updated': f.get('last_run') or f.get('last_change'), 'state': f['state'],
                         'source': f['source'], 'version': f.get('version_no')})
        for i in qs.internal_lists():
            rows.append({'name': SOURCE_LABEL.get(i['table'], i['label']), 'records': i['active'],
                         'updated': i.get('last_added'), 'state': 'green'})
    except Exception:
        rows = []
    rows.sort(key=lambda r: -int(r['records'] or 0))
    _COVERAGE.update(t=time.time(), data=rows)
    return rows


def adverse_view(summary, hits):
    s = summary if isinstance(summary, dict) else {}
    legacy = bool(hits) and not any('name_match' in h for h in hits)
    by_cat = {}
    for h in hits or []:
        for c in h.get('categories') or []:
            by_cat[c] = by_cat.get(c, 0) + 1
    level = s.get('risk_level') or ('CLEAR' if not hits else 'LOW')
    return {
        'level': level,
        'level_label': AM_LEVEL.get(level, (level, ''))[0],
        'level_text': AM_LEVEL.get(level, ('', ''))[1],
        'recommendation': s.get('recommendation'),
        'sources_used': s.get('sources_used') or [],
        'sources_failed': s.get('sources_failed') or [],
        'queries': s.get('queries') or [],
        'reviewed': s.get('articles_reviewed'),
        'unrelated': s.get('unrelated_filtered'),
        'mentions': s.get('mentions') or [],
        'mentions_count': s.get('mentions_count') or 0,
        'searched_at': s.get('searched_at'),
        'by_category': sorted(by_cat.items(), key=lambda x: -x[1]),
        'legacy': legacy,
    }
