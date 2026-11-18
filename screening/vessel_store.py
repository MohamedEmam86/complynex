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
normal list pipeline (data_updater_enhanced + list_versions; rollback only flips is_active, which every
query below filters on). Each list handler puts the ship data in properties.vessel (details.vessel for the
UN / EU files). sync() materialises that block into:

    vessel_profile      one row per listed ship record (identity, flag history, past names, measures,
                        group_key = the same ship on several lists, risk indicators of the listed ship)
    vessel_identifier   IMO / MMSI / call sign values, current and past, for the exact-match layer
                        (an IMO failing its check digit is kept with check_ok = false, never dropped)
    vessel_party_link   owners / operators / managers, linked to their own watchlist row when listed

and re-checks the vessel whitelist (an entry whose listed ship changed name / flag / owner is re-opened).
The engine and the Vessels Database page read only these tables + screening_watchlist, so a new vessel
source needs nothing more than a handler that fills properties.vessel.
"""
import json
import logging
import re
import time

from screening import vessel_utils as VU

logger = logging.getLogger(__name__)

# what clients see instead of a list's name (owner decision, 17 Nov 2026)
GENERIC_LIST_LABEL = 'International approved lists'
GENERIC_LIST_LABEL_AR = 'قوائم دولية معتمدة'

OPENSANCTIONS_SOURCES = ('opensanctions',)
CFG_INCLUDE_OS = 'vessels_include_opensanctions'

# risk indicators of a listed ship (the Vessels Database "risk" filter); weights add up, capped at 100
RISK_WEIGHTS = {'foc': 15, 'high_risk_flag': 25, 'false_flag': 30, 'flag_changes': 15, 'renamed': 10,
                'invalid_imo': 20, 'owner_listed': 25, 'multi_list': 10}
RISK_BANDS = (('high', 50), ('medium', 25), ('low', 0))


def can_see_sources(user=None):
    """The real list behind a hit is shown to the platform superadmin only (owner decision): every other
    user, the API, the PDFs and the exports see the generic label."""
    if user is None:
        try:
            from flask_login import current_user as user
        except Exception:
            return False
    return bool(getattr(user, 'is_authenticated', False)) and getattr(user, 'role', '') == 'superadmin'


def list_label(source, lang='en', user=None):
    if can_see_sources(user):
        return source or '-'
    return GENERIC_LIST_LABEL_AR if lang == 'ar' else GENERIC_LIST_LABEL


def risk_band(score):
    for name, lo in RISK_BANDS:
        if (score or 0) >= lo and (name != 'low' or (score or 0) > 0):
            return name
    return 'none'


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


def _rows(cur):
    cols = [d[0] for d in (getattr(cur, 'description', None) or [])]
    return [dict(zip(cols, r)) if not isinstance(r, dict) else dict(r) for r in cur.fetchall()]


def party_key(name):
    """Comparable form of an owner name ('Ocean Ltd.' / 'OCEAN LTD' -> 'OCEAN LTD')."""
    s = VU._strip_accents(str(name or '')).upper()
    s = re.sub(r'[(][^)]*[)]', ' ', s)
    s = re.sub(r'[^A-Z0-9\u0600-\u06ff]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


# --------------------------------------------------------------------------- materialise
def _profile_values(wid, source, block):
    imos = [VU.norm_imo(x) for x in ([block.get('imo')] + list(block.get('imos') or []))]
    imos = [x for x in dict.fromkeys(imos) if x]
    mmsis = [x for x in dict.fromkeys(VU.norm_mmsi(x) for x in (block.get('mmsi') or [])) if x]
    calls = [x for x in dict.fromkeys(VU.norm_call_sign(x) for x in (block.get('call_sign') or [])) if x]
    flag = VU.clean_flag(block.get('flag'))
    flags_past = [f for f in dict.fromkeys(VU.clean_flag(f) for f in (block.get('flags_past') or [])) if f and f != flag]
    names_past = [str(n).strip() for n in (block.get('names_past') or []) if str(n or '').strip()]
    valid_imo = next((i for i in imos if VU.imo_valid(i)), None)
    prof = {
        'watchlist_id': wid, 'source': source,
        'imo': valid_imo or (imos[0] if imos else None),
        'imo_valid': (VU.imo_valid(valid_imo or imos[0]) if imos else None),
        'mmsi': mmsis[0] if mmsis else None,
        'call_sign': calls[0] if calls else None,
        'vessel_type': (block.get('type') or None),
        'current_flag': flag,
        'flag_history': json.dumps(flags_past, ensure_ascii=False),
        'previous_names': json.dumps(list(dict.fromkeys(names_past)), ensure_ascii=False),
        'gross_tonnage': block.get('gross_tonnage') or block.get('tonnage') or None,
        'year_built': block.get('year_built') or None,
        'measures': json.dumps(list(dict.fromkeys(block.get('measures') or [])), ensure_ascii=False),
        'owners': json.dumps(block.get('owners') or [], ensure_ascii=False),
        # the same ship listed by several lists shares its (valid) IMO number
        'group_key': ('IMO:' + valid_imo) if valid_imo else ('WL:%d' % wid),
    }
    idents = [(wid, 'IMO', v, True, VU.imo_valid(v), source) for v in imos]
    idents += [(wid, 'MMSI', v, i == 0, VU.mmsi_valid(v), source) for i, v in enumerate(mmsis)]
    idents += [(wid, 'CALLSIGN', v, i == 0, True, source) for i, v in enumerate(calls)]
    return prof, idents


def _resolve_parties(cur, links):
    """[(wid, ref, name, role, source)] -> [(wid, party_watchlist_id, party_name, role, source)].
    A ref is the party's source_id on the same list (OpenSanctions); a name is looked up among the active
    non-ship records, the same list first, then any list."""
    refs = sorted({(src, ref) for _, ref, _, _, src in links if ref})
    by_ref = {}
    for i in range(0, len(refs), 1000):
        chunk = refs[i:i + 1000]
        cur.execute("""SELECT id, source, source_id, full_name FROM screening_watchlist
                       WHERE (source, source_id) IN (SELECT * FROM unnest(%s::text[], %s::text[]))""",
                    ([c[0] for c in chunk], [c[1] for c in chunk]))
        for r in _rows(cur):
            by_ref[(r['source'], r['source_id'])] = (r['id'], r['full_name'])
    names = sorted({party_key(n) for _, ref, n, _, _ in links if n and not ref} - {''})
    by_name = {}
    if names:
        # one pass over the list records (the key expression mirrors party_key for Latin names)
        key_sql = ("upper(btrim(regexp_replace(regexp_replace(regexp_replace(full_name, '[(][^)]*[)]', ' ', 'g'), "
                   "'[^A-Za-z0-9\u0600-\u06ff]+', ' ', 'g'), '\\s+', ' ', 'g')))")
        cur.execute(f"""SELECT id, source, {key_sql} AS k FROM screening_watchlist
                        WHERE is_active = 1 AND coalesce(entity_type, '') <> 'VESSEL' AND {key_sql} = ANY(%s)""",
                    (names,))
        for r in _rows(cur):
            by_name.setdefault(r['k'], []).append((r['id'], r['source']))
    out = []
    for wid, ref, name, role, src in links:
        pid, pname = None, name
        if ref and (src, ref) in by_ref:
            pid, full = by_ref[(src, ref)]
            pname = pname or full
        elif name:
            cands = by_name.get(party_key(name)) or []
            same = [c for c in cands if c[1] == src]
            pick = (same or cands or [None])[0]
            pid = pick[0] if pick else None
        if pname or pid:
            out.append((wid, pid, (pname or ref or '')[:500] or None, role, src))
    return out


def _listed_risk(prof, n_lists, owner_listed, flags):
    lines = []
    fl = (prof.get('current_flag') or '')
    fr = flags.get(fl.lower()) or flags.get((VU.flag_code(fl) or '-').lower()) or {}
    if '(false flag)' in fl:
        lines.append('false_flag')
    if fr.get('foc'):
        lines.append('foc')
    if fr.get('high_risk'):
        lines.append('high_risk_flag')
    if len(_j(prof.get('flag_history'), []) or []) >= 2:
        lines.append('flag_changes')
    if _j(prof.get('previous_names'), []):
        lines.append('renamed')
    if prof.get('imo') and prof.get('imo_valid') is False:
        lines.append('invalid_imo')
    if owner_listed:
        lines.append('owner_listed')
    if n_lists >= 2:
        lines.append('multi_list')
    return min(100, sum(RISK_WEIGHTS[x] for x in lines)), lines


def sync(conn, source=None, log=None):
    """Rebuild vessel_profile / vessel_identifier / vessel_party_link for one source (or all) from the
    VESSEL rows of screening_watchlist, then refresh the cross-list risk of every ship and re-check the
    whitelist. Idempotent; commits. Returns counts."""
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
    rows = _rows(cur)
    profiles, idents, links = [], [], []
    for row in rows:
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
    resolved = _resolve_parties(cur, links)
    # replace the source's materialised rows in one transaction
    if source:
        sub = '(SELECT id FROM screening_watchlist WHERE source = %s)'
        for t in ('vessel_identifier', 'vessel_party_link', 'vessel_profile'):
            cur.execute(f'DELETE FROM {t} WHERE watchlist_id IN {sub}', (source,))
    else:
        for t in ('vessel_identifier', 'vessel_party_link', 'vessel_profile'):
            cur.execute(f'DELETE FROM {t}')
    from psycopg2.extras import execute_values
    cols = ('watchlist_id', 'source', 'imo', 'imo_valid', 'mmsi', 'call_sign', 'vessel_type', 'current_flag',
            'flag_history', 'previous_names', 'gross_tonnage', 'year_built', 'measures', 'owners', 'group_key')
    vals = []
    for p in profiles:
        p = dict(p, gross_tonnage=str(p['gross_tonnage'])[:40] if p['gross_tonnage'] else None,
                 year_built=str(p['year_built'])[:10] if p['year_built'] else None)
        vals.append(tuple(p[c] for c in cols))
    if vals:
        execute_values(cur, f"INSERT INTO vessel_profile ({', '.join(cols)}) VALUES %s", vals, page_size=1000)
    if idents:
        execute_values(cur, """INSERT INTO vessel_identifier (watchlist_id, kind, value_norm, is_current, check_ok, source)
                               VALUES %s ON CONFLICT (watchlist_id, kind, value_norm) DO NOTHING""", idents,
                       page_size=2000)
    if resolved:
        execute_values(cur, """INSERT INTO vessel_party_link (watchlist_id, party_watchlist_id, party_name, role, source)
                               VALUES %s ON CONFLICT DO NOTHING""", resolved, page_size=2000)
    conn.commit()
    risk = refresh_risk(conn)
    reopened = check_whitelist(conn)
    _CACHE.clear()
    out = {'source': source or 'all', 'vessels': len(profiles),
           'with_imo': sum(1 for p in profiles if p['imo']),
           'imo_check_fails': sum(1 for p in profiles if p['imo'] and p['imo_valid'] is False),
           'identifiers': len(idents), 'parties': len(resolved),
           'parties_listed': sum(1 for r in resolved if r[1]), 'risk_rows': risk,
           'whitelist_reopened': reopened, 'seconds': round(time.time() - t0, 1)}
    log(f'[VESSELS] materialised {out}')
    return out


def refresh_risk(conn):
    """Risk indicators of every listed ship (needs all lists: 'on several lists', 'owner listed')."""
    cur = conn.cursor()
    flags = flag_risk(conn, force=True)
    cur.execute("""SELECT p.watchlist_id, p.imo, p.imo_valid, p.current_flag, p.flag_history, p.previous_names,
                          p.group_key,
                          (SELECT count(DISTINCT w2.source) FROM vessel_profile p2
                             JOIN screening_watchlist w2 ON w2.id = p2.watchlist_id AND w2.is_active = 1
                            WHERE p2.group_key = p.group_key) AS n_lists,
                          EXISTS (SELECT 1 FROM vessel_party_link l JOIN screening_watchlist o
                                    ON o.id = l.party_watchlist_id AND o.is_active = 1
                                   WHERE l.watchlist_id = p.watchlist_id) AS owner_listed
                   FROM vessel_profile p""")
    upd = []
    for r in _rows(cur):
        score, lines = _listed_risk(r, int(r['n_lists'] or 0), bool(r['owner_listed']), flags)
        upd.append((score, json.dumps(lines), r['watchlist_id']))
    if upd:
        from psycopg2.extras import execute_batch
        execute_batch(cur, 'UPDATE vessel_profile SET risk_score = %s, risk_lines = %s WHERE watchlist_id = %s',
                      upd, page_size=1000)
    conn.commit()
    return len(upd)


# --------------------------------------------------------------------------- engine data
_CACHE = {}
_TTL = 600


def load_candidates(conn, force=False):
    """All active listed vessels with their names, cached for 10 minutes per process.
    [{watchlist_id, group_key, source, list_type, name, names[], imo, mmsi, call_sign, flag, flags_past[],
      type, year_built, measures[], owners[], parties[], risk_score}]"""
    key = 'cands'
    now = time.time()
    if not force and key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    inc_os = include_opensanctions(conn)
    cur = conn.cursor()
    cur.execute("""SELECT w.id, w.source, w.list_type, w.full_name, w.aliases, w.full_name_arabic,
                          w.aliases_arabic, w.original_name,
                          p.imo, p.imo_valid, p.mmsi, p.call_sign, p.vessel_type, p.current_flag, p.flag_history,
                          p.previous_names, p.year_built, p.measures, p.owners, p.gross_tonnage, p.group_key,
                          p.risk_score
                   FROM screening_watchlist w JOIN vessel_profile p ON p.watchlist_id = w.id
                   WHERE w.is_active = 1 AND w.entity_type = 'VESSEL'""")
    rows = _rows(cur)
    cur.execute("""SELECT l.watchlist_id, l.party_name, l.role, l.party_watchlist_id,
                          (o.id IS NOT NULL AND o.is_active = 1) AS party_listed
                   FROM vessel_party_link l LEFT JOIN screening_watchlist o ON o.id = l.party_watchlist_id""")
    parties = {}
    for r in _rows(cur):
        parties.setdefault(r['watchlist_id'], []).append(
            {'name': r['party_name'], 'role': r['role'], 'party_watchlist_id': r['party_watchlist_id'],
             'party_listed': bool(r['party_listed'])})
    out = []
    for row in rows:
        if not inc_os and row['source'] in OPENSANCTIONS_SOURCES:
            continue
        names = [row['full_name']] + list(_j(row['aliases'], []) or []) + list(_j(row['previous_names'], []) or [])
        names += [row.get('full_name_arabic'), row.get('original_name')] + list(_j(row.get('aliases_arabic'), []) or [])
        names = [n for n in dict.fromkeys(str(x).strip() for x in names if x and str(x).strip())]
        out.append({
            'watchlist_id': row['id'], 'group_key': row.get('group_key') or 'WL:%d' % row['id'],
            'source': row['source'], 'list_type': row.get('list_type'),
            'name': row['full_name'], 'names': names,
            'previous_names': _j(row['previous_names'], []) or [],
            'imo': row['imo'], 'imo_valid': row.get('imo_valid'), 'mmsi': row['mmsi'], 'call_sign': row['call_sign'],
            'flag': row['current_flag'], 'flags_past': _j(row['flag_history'], []) or [],
            'type': row['vessel_type'], 'year_built': row['year_built'],
            'gross_tonnage': row.get('gross_tonnage'),
            'measures': _j(row['measures'], []) or [], 'owners': _j(row['owners'], []) or [],
            'parties': parties.get(row['id'], []), 'risk_score': row.get('risk_score') or 0,
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
    return [(r['watchlist_id'], r['is_current']) for r in _rows(cur)]


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
    for r in _rows(cur):
        out.setdefault(r['watchlist_id'], []).append({'name': r['party_name'], 'role': r['role'],
                                                      'party_watchlist_id': r['party_watchlist_id'],
                                                      'party_listed': bool(r['party_listed'])})
    return out


def flag_risk(conn, force=False):
    """{lower-case flag name or ISO2: {foc, high_risk, note}} (reference table, editable)."""
    if not force and 'flags' in _CACHE and time.time() - _CACHE['flags'][0] < _TTL:
        return _CACHE['flags'][1]
    out = {}
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM flag_risk')
        for r in _rows(cur):
            v = {'foc': bool(r.get('flag_of_convenience')), 'high_risk': bool(r.get('high_risk')),
                 'note': r.get('note')}
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


# --------------------------------------------------------------------------- whitelist
def listed_fingerprint(hit):
    """Identity of a listed ship (all lists of the same IMO): names, flags, owners. A change of any of them
    re-opens a whitelisted hit."""
    names = sorted({VU.norm_name(n) for n in ([hit.get('name')] + list(hit.get('names') or [])) if n} - {''})
    flags = sorted({f for f in [hit.get('flag')] + list(hit.get('flags_all') or []) if f})
    owners = sorted({party_key(p.get('name')) for p in (hit.get('parties') or []) if p.get('name')} - {''})
    return VU.fingerprint('|'.join(names), '|'.join(flags), '|'.join(owners))


def listed_key(hit):
    return hit.get('group_key') or ('IMO:' + hit['imo'] if hit.get('imo') else 'WL:%s' % hit.get('watchlist_id'))


def query_fingerprint(q):
    """Identity of the screened ship: name, flag, owner (the IMO is in the key)."""
    return VU.fingerprint(VU.norm_name(q.get('name')), VU.clean_flag(q.get('flag')) or '', party_key(q.get('owner')))


def whitelist_for(conn, qkey):
    """{listed_key: entry} of the whitelist entries of a screened ship (active and re-opened)."""
    cur = conn.cursor()
    cur.execute("""SELECT w.*, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS by_name
                   FROM vessel_whitelist w LEFT JOIN users u ON u.id = w.created_by
                   WHERE w.query_key = %s AND w.status IN ('active', 'reopened')
                   ORDER BY w.created_at""", (qkey,))
    out = {}
    for r in _rows(cur):
        out[r['listed_key']] = r
    return out


def check_whitelist(conn):
    """After a list update: re-open active entries whose listed ship changed (name / flag / owner) or left
    every list. Returns the number re-opened."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, listed_key, listed_fp FROM vessel_whitelist WHERE status = 'active'")
        entries = _rows(cur)
        if not entries:
            return 0
        _CACHE.pop('cands', None)
        groups = {}
        for c in load_candidates(conn, force=True):
            groups.setdefault(c['group_key'], []).append(c)
        n = 0
        for e in entries:
            members = groups.get(e['listed_key'])
            if not members:
                reason = 'the listed ship is no longer on any list'
            else:
                fp = listed_fingerprint(merge_group(members))
                if fp == e['listed_fp']:
                    continue
                reason = 'the listed ship changed (name, flag or owner)'
            cur.execute("""UPDATE vessel_whitelist SET status = 'reopened', reopened_at = now(), reopened_reason = %s
                           WHERE id = %s AND status = 'active'""", (reason, e['id']))
            n += cur.rowcount
        conn.commit()
        return n
    except Exception as ex:
        logger.warning(f'[VESSELS] whitelist check failed: {ex}')
        try:
            conn.rollback()
        except Exception:
            pass
        return 0


def merge_group(members):
    """One view of a ship listed by several lists (same IMO): the fullest record, all names, flags,
    measures, parties and sources."""
    members = sorted(members, key=lambda c: (c['source'] in OPENSANCTIONS_SOURCES, c['watchlist_id']))
    base = dict(members[0])
    for k in ('mmsi', 'call_sign', 'flag', 'type', 'year_built', 'gross_tonnage', 'imo'):
        if not base.get(k):
            base[k] = next((m.get(k) for m in members if m.get(k)), None)
    base['names'] = list(dict.fromkeys(n for m in members for n in m.get('names') or []))
    base['previous_names'] = list(dict.fromkeys(n for m in members for n in m.get('previous_names') or []))
    base['flags_past'] = list(dict.fromkeys(f for m in members for f in m.get('flags_past') or []
                                            if f and f != base.get('flag')))
    base['flags_all'] = list(dict.fromkeys(f for m in members for f in [m.get('flag')] + list(m.get('flags_past') or []) if f))
    base['measures'] = list(dict.fromkeys(x for m in members for x in m.get('measures') or []))
    seen, parties = set(), []
    for m in members:
        for p in m.get('parties') or []:
            k = (party_key(p.get('name')), p.get('role'))
            if k not in seen:
                seen.add(k)
                parties.append(p)
    base['parties'] = parties
    base['sources'] = sorted({m['source'] for m in members})
    base['member_ids'] = [m['watchlist_id'] for m in members]
    base['list_types'] = sorted({m.get('list_type') for m in members if m.get('list_type')})
    base['risk_score'] = max(int(m.get('risk_score') or 0) for m in members)
    return base
