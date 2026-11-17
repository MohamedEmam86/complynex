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
Vessel data layer (V1).

Vessels stay rows of screening_watchlist (entity_type 'VESSEL'), loaded, versioned and delisted by the
normal list pipeline. Each list handler puts the ship data in properties.vessel (details.vessel for the
EU file). sync() materialises that block into:

    vessel_profile      one row per listed ship record (identity, flag history, past names, measures)
    vessel_identifier   IMO / MMSI / call sign values, current and past, for the exact-match layer
    vessel_party_link   owners / operators / managers, linked to their own watchlist row when listed

The engine and the Vessels Database page read only these tables + screening_watchlist, so a new vessel
source needs nothing more than a handler that fills properties.vessel.
"""
import json
import logging
import time

from screening import vessel_utils as VU

logger = logging.getLogger(__name__)

# what clients see instead of a list's name (owner decision, 17 Nov 2026)
GENERIC_LIST_LABEL = 'International approved lists'
GENERIC_LIST_LABEL_AR = 'قوائم دولية معتمدة'

# sources whose rows are vessels (the materialiser only reads entity_type = 'VESSEL' rows anyway)
OPENSANCTIONS_SOURCES = ('opensanctions',)
CFG_INCLUDE_OS = 'vessels_include_opensanctions'


def _j(v, default=None):
    if v is None or v == '':
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return default


def vessel_block(row):
    """The ship data a handler stored on a watchlist row (properties.vessel, else details.vessel)."""
    for col in ('properties', 'details'):
        d = _j(row.get(col), {})
        if isinstance(d, dict) and isinstance(d.get('vessel'), dict):
            return d['vessel']
    return None


def include_opensanctions(conn):
    """screening_config 'vessels_include_opensanctions': 'on' (default) / 'off' - switch the
    aggregator's vessels out of screening and the database page without touching the data."""
    try:
        from screening.list_versions import _cfg_raw
        v = str(_cfg_raw(conn, CFG_INCLUDE_OS) or 'on').strip().lower()
        return v != 'off'
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return True


# --------------------------------------------------------------------------- materialise
def _profile_values(wid, source, block):
    imos = [VU.norm_imo(x) for x in ([block.get('imo')] + list(block.get('imos') or []))]
    imos = [x for x in dict.fromkeys(imos) if x]
    mmsis = [x for x in dict.fromkeys(VU.norm_mmsi(x) for x in (block.get('mmsi') or [])) if x]
    calls = [x for x in dict.fromkeys(VU.norm_call_sign(x) for x in (block.get('call_sign') or [])) if x]
    flags_past = [VU.clean_flag(f) for f in (block.get('flags_past') or []) if VU.clean_flag(f)]
    names_past = [str(n).strip() for n in (block.get('names_past') or []) if str(n or '').strip()]
    prof = {
        'watchlist_id': wid, 'source': source,
        'imo': imos[0] if imos else None,
        'imo_valid': VU.imo_valid(imos[0]) if imos else None,
        'mmsi': mmsis[0] if mmsis else None,
        'call_sign': calls[0] if calls else None,
        'vessel_type': (block.get('type') or None),
        'current_flag': VU.clean_flag(block.get('flag')),
        'flag_history': json.dumps(list(dict.fromkeys(flags_past)), ensure_ascii=False),
        'previous_names': json.dumps(list(dict.fromkeys(names_past)), ensure_ascii=False),
        'gross_tonnage': block.get('gross_tonnage') or block.get('tonnage') or None,
        'year_built': block.get('year_built') or None,
        'measures': json.dumps(list(dict.fromkeys(block.get('measures') or [])), ensure_ascii=False),
        'owners': json.dumps(block.get('owners') or [], ensure_ascii=False),
    }
    idents = [(wid, 'IMO', v, i == 0, VU.imo_valid(v), source) for i, v in enumerate(imos)]
    idents += [(wid, 'MMSI', v, i == 0, VU.mmsi_valid(v), source) for i, v in enumerate(mmsis)]
    idents += [(wid, 'CALLSIGN', v, i == 0, True, source) for i, v in enumerate(calls)]
    return prof, idents


def sync(conn, source=None, log=None):
    """Rebuild vessel_profile / vessel_identifier / vessel_party_link for one source (or all) from the
    VESSEL rows of screening_watchlist. Idempotent; commits. Returns counts."""
    log = log or logger.info
    t0 = time.time()
    cur = conn.cursor()
    params = []
    where = "entity_type = 'VESSEL'"
    if source:
        where += ' AND source = %s'
        params.append(source)
    cur.execute(f"SELECT id, source, source_id, properties, details FROM screening_watchlist WHERE {where}",
                params)
    rows = cur.fetchall()
    cols = [d[0] for d in (getattr(cur, 'description', None) or [])]
    profiles, idents, links = [], [], []
    for r in rows:
        row = dict(zip(cols, r)) if not isinstance(r, dict) else r
        block = vessel_block(row)
        if not block:
            continue
        prof, ids = _profile_values(row['id'], row['source'], block)
        profiles.append(prof)
        idents += ids
        for o in (block.get('owners') or []):
            name = str(o.get('name') or '').strip()
            if not name and not o.get('ref'):
                continue
            links.append((row['id'], o.get('ref'), name[:500] or None, (o.get('role') or 'owner')[:30],
                          row['source']))
    ids_by_wid = [p['watchlist_id'] for p in profiles]
    # replace the source's materialised rows in one transaction
    if source:
        cur.execute("""DELETE FROM vessel_identifier WHERE watchlist_id IN
                       (SELECT id FROM screening_watchlist WHERE source = %s)""", (source,))
        cur.execute("""DELETE FROM vessel_party_link WHERE watchlist_id IN
                       (SELECT id FROM screening_watchlist WHERE source = %s)""", (source,))
        cur.execute("""DELETE FROM vessel_profile WHERE watchlist_id IN
                       (SELECT id FROM screening_watchlist WHERE source = %s)""", (source,))
    else:
        cur.execute('DELETE FROM vessel_identifier')
        cur.execute('DELETE FROM vessel_party_link')
        cur.execute('DELETE FROM vessel_profile')
    for p in profiles:
        cur.execute("""INSERT INTO vessel_profile (watchlist_id, source, imo, imo_valid, mmsi, call_sign,
                           vessel_type, current_flag, flag_history, previous_names, gross_tonnage, year_built,
                           measures, owners, updated_at)
                       VALUES (%(watchlist_id)s, %(source)s, %(imo)s, %(imo_valid)s, %(mmsi)s, %(call_sign)s,
                           %(vessel_type)s, %(current_flag)s, %(flag_history)s, %(previous_names)s,
                           %(gross_tonnage)s, %(year_built)s, %(measures)s, %(owners)s, now())""",
                    {**p, 'gross_tonnage': str(p['gross_tonnage'])[:40] if p['gross_tonnage'] else None,
                     'year_built': str(p['year_built'])[:10] if p['year_built'] else None})
    for i in idents:
        cur.execute("""INSERT INTO vessel_identifier (watchlist_id, kind, value_norm, is_current, check_ok, source)
                       VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (watchlist_id, kind, value_norm) DO NOTHING""",
                    i)
    for wid, ref, name, role, src in links:
        party = None
        if ref:
            cur.execute('SELECT id FROM screening_watchlist WHERE source = %s AND source_id = %s LIMIT 1',
                        (src, ref))
            hit = cur.fetchone()
            party = (hit['id'] if isinstance(hit, dict) else hit[0]) if hit else None
        cur.execute("""INSERT INTO vessel_party_link (watchlist_id, party_watchlist_id, party_name, role, source)
                       VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (wid, party, name or ref, role, src))
    conn.commit()
    _CACHE.clear()
    out = {'source': source or 'all', 'vessels': len(profiles), 'identifiers': len(idents),
           'parties': len(links), 'seconds': round(time.time() - t0, 1)}
    log(f'[VESSELS] materialised {out}')
    return out


# --------------------------------------------------------------------------- engine data
_CACHE = {}
_TTL = 600


def load_candidates(conn, force=False):
    """All active listed vessels with their names, cached for 10 minutes per process.
    [{watchlist_id, source, list_type, name, names[], imo, mmsi, call_sign, flag, flags_past[],
      type, year_built, measures[], owners[]}]"""
    key = 'cands'
    now = time.time()
    if not force and key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    inc_os = include_opensanctions(conn)
    cur = conn.cursor()
    cur.execute("""SELECT w.id, w.source, w.list_type, w.full_name, w.aliases, w.full_name_arabic,
                          w.aliases_arabic, w.original_name, w.legal_status,
                          p.imo, p.mmsi, p.call_sign, p.vessel_type, p.current_flag, p.flag_history,
                          p.previous_names, p.year_built, p.measures, p.owners, p.gross_tonnage
                   FROM screening_watchlist w JOIN vessel_profile p ON p.watchlist_id = w.id
                   WHERE w.is_active = 1 AND w.entity_type = 'VESSEL'""")
    cols = [d[0] for d in (getattr(cur, 'description', None) or [])]
    out = []
    for r in cur.fetchall():
        row = dict(zip(cols, r)) if not isinstance(r, dict) else dict(r)
        if not inc_os and row['source'] in OPENSANCTIONS_SOURCES:
            continue
        names = [row['full_name']] + list(_j(row['aliases'], []) or []) + list(_j(row['previous_names'], []) or [])
        names += [row.get('full_name_arabic'), row.get('original_name')] + list(_j(row.get('aliases_arabic'), []) or [])
        names = [n for n in dict.fromkeys(str(x).strip() for x in names if x and str(x).strip())]
        out.append({
            'watchlist_id': row['id'], 'source': row['source'], 'list_type': row.get('list_type'),
            'name': row['full_name'], 'names': names,
            'previous_names': _j(row['previous_names'], []) or [],
            'imo': row['imo'], 'mmsi': row['mmsi'], 'call_sign': row['call_sign'],
            'flag': row['current_flag'], 'flags_past': _j(row['flag_history'], []) or [],
            'type': row['vessel_type'], 'year_built': row['year_built'],
            'gross_tonnage': row.get('gross_tonnage'),
            'measures': _j(row['measures'], []) or [], 'owners': _j(row['owners'], []) or [],
            'legal_status': row.get('legal_status'),
        })
    _CACHE[key] = (now, out)
    return out


def identifier_hits(conn, kind, value):
    """Watchlist ids of active vessels that carry this IMO / MMSI / call sign now or in the past.
    [(watchlist_id, is_current)]"""
    if not value:
        return []
    cur = conn.cursor()
    cur.execute("""SELECT i.watchlist_id, i.is_current FROM vessel_identifier i
                   JOIN screening_watchlist w ON w.id = i.watchlist_id
                   WHERE i.kind = %s AND i.value_norm = %s AND w.is_active = 1""", (kind, value))
    rows = cur.fetchall()
    return [((r['watchlist_id'], r['is_current']) if isinstance(r, dict) else (r[0], r[1])) for r in rows]


def party_links(conn, watchlist_ids):
    """{watchlist_id: [{name, role, party_watchlist_id, party_listed}]}"""
    if not watchlist_ids:
        return {}
    cur = conn.cursor()
    cur.execute("""SELECT l.watchlist_id, l.party_name, l.role, l.party_watchlist_id,
                          (p.id IS NOT NULL AND p.is_active = 1) AS party_listed
                   FROM vessel_party_link l LEFT JOIN screening_watchlist p ON p.id = l.party_watchlist_id
                   WHERE l.watchlist_id = ANY(%s)""", (list(watchlist_ids),))
    out = {}
    for r in cur.fetchall():
        r = r if isinstance(r, dict) else dict(zip(('watchlist_id', 'party_name', 'role', 'party_watchlist_id',
                                                     'party_listed'), r))
        out.setdefault(r['watchlist_id'], []).append({'name': r['party_name'], 'role': r['role'],
                                                      'party_watchlist_id': r['party_watchlist_id'],
                                                      'party_listed': bool(r['party_listed'])})
    return out


def flag_risk(conn):
    """{lower-case flag name or ISO2: {foc, note}} (reference table, editable)."""
    if 'flags' in _CACHE and time.time() - _CACHE['flags'][0] < _TTL:
        return _CACHE['flags'][1]
    out = {}
    try:
        cur = conn.cursor()
        cur.execute('SELECT country, iso2, flag_of_convenience, note FROM flag_risk')
        for r in cur.fetchall():
            r = r if isinstance(r, dict) else dict(zip(('country', 'iso2', 'flag_of_convenience', 'note'), r))
            v = {'foc': bool(r['flag_of_convenience']), 'note': r['note']}
            out[str(r['country']).lower()] = v
            if r.get('iso2'):
                out[str(r['iso2']).lower()] = v
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    _CACHE['flags'] = (time.time(), out)
    return out
