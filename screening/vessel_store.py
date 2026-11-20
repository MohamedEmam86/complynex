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
# (round 3: "International approved lists" told the officer nothing; the result now says what the ship is and
#  under which kind of regime, and the lists are named generically by what they are)
GENERIC_LIST_LABEL = 'Official sanctions lists'
GENERIC_LIST_LABEL_AR = 'قوائم العقوبات الرسمية'
GENERIC_BAN_LABEL = 'Official ban / exclusion lists'
GENERIC_BAN_LABEL_AR = 'قوائم الحظر والاستبعاد الرسمية'

OPENSANCTIONS_SOURCES = ('opensanctions',)
CFG_INCLUDE_OS = 'vessels_include_opensanctions'

# risk indicators of a listed ship (the Vessels Database "risk" filter); weights add up, capped at 100
# Risk indicators of a listed ship: signs of evasion or poor standing, each counted once. Being on a list, on
# several lists, or owned by a listed party is a FACT shown with the ship, not part of this score (almost every
# listed ship has it, so it would make every ship "high").
RISK_WEIGHTS = {'false_flag': 30, 'high_risk_flag': 20, 'invalid_imo': 20, 'flag_changes': 15, 'foc': 10,
                'renamed': 10, 'psc_detained': 10, 'psc_repeated': 10,
                'owner_listed': 0, 'multi_list': 0}
# high = several independent indicators (or one severe one with another), medium = one or two, low = minor only
RISK_BANDS = (('high', 45), ('medium', 20), ('low', 0))


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


# list categories a client may see (the category of a list, never its name); anything else -> the generic label
CATEGORIES = {
    'SANCTIONS': ('Sanctions', 'عقوبات'), 'TERROR': ('Terrorism', 'إرهاب'),
    'SANCTION_LINKED': ('Linked to a sanctioned party', 'مرتبط بجهة معاقبة'),
    'COUNTER_SANCTIONS': ('Counter-sanctions', 'عقوبات مضادة'), 'CRIME': ('Criminal / wanted', 'جرائم / مطلوب'),
    'PEP': ('Politically exposed person', 'شخص سياسي ممثل للمخاطر'), 'EXPORT_CONTROL': ('Export control', 'قيود تصدير'),
    'DEBARMENT': ('Debarment', 'حرمان'), 'REG_ACTION': ('Regulatory action', 'إجراء رقابي'),
    'TRADE_RISK': ('Trade risk', 'مخاطر تجارية'),
}


def list_category(list_type):
    """Generic category code of a record's list_type ('UN_Sanctions' -> 'SANCTIONS'), None when unknown.
    The raw list_type can carry a list's name, so clients only ever get this code."""
    lt = str(list_type or '').strip().upper()
    if lt in CATEGORIES:
        return lt
    if 'SANCTION' in lt:
        return 'SANCTIONS'
    if 'TERROR' in lt:
        return 'TERROR'
    return None


def category_label(list_type, lang='en', user=None):
    """What a page shows for a hit's list type: the raw value for the superadmin, else the generic category."""
    if can_see_sources(user):
        return str(list_type or '')
    code = list_category(list_type)
    if code:
        return CATEGORIES[code][1 if lang == 'ar' else 0]
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


def config_value(conn, key):
    """screening_config value through either connection type (the app's get_db() wrapper or a raw psycopg2
    connection). Runs inside a savepoint, so a failure never discards the caller's uncommitted work."""
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute('SAVEPOINT vessel_cfg')
    except Exception:
        return None
    try:
        cur.execute('SELECT config_value FROM screening_config WHERE config_key = %s', (key,))
        r = cur.fetchone()
        cur.execute('RELEASE SAVEPOINT vessel_cfg')
        if not r:
            return None
        return r['config_value'] if isinstance(r, dict) or hasattr(r, 'keys') else r[0]
    except Exception as e:
        logger.warning(f'[VESSELS] screening_config {key} unreadable: {e}')
        try:
            cur.execute('ROLLBACK TO SAVEPOINT vessel_cfg')
        except Exception:
            pass
        return None


def read_rows(conn, sql, params=()):
    """Rows of a read-only query inside a savepoint: on failure (e.g. a table not migrated yet) returns None and
    leaves the caller's transaction usable, without rolling back work that is not ours."""
    cur = conn.cursor()
    try:
        cur.execute('SAVEPOINT vessel_read')
    except Exception:
        return None
    try:
        cur.execute(sql, params)
        rows = _rows(cur)
        cur.execute('RELEASE SAVEPOINT vessel_read')
        return rows
    except Exception as e:
        logger.warning(f'[VESSELS] read failed: {e}')
        try:
            cur.execute('ROLLBACK TO SAVEPOINT vessel_read')
        except Exception:
            pass
        return None


def config_json(conn, key):
    v = config_value(conn, key)
    try:
        d = json.loads(v) if v else {}
    except Exception:
        logger.warning(f'[VESSELS] screening_config {key} is not JSON: ignored')
        return {}
    return d if isinstance(d, dict) else {}


def include_opensanctions(conn):
    """screening_config 'vessels_include_opensanctions': 'on' (default) / 'off' - switch the
    aggregator's vessels out of screening and the database page without touching the data."""
    v = str(config_value(conn, CFG_INCLUDE_OS) or 'on').strip().lower()
    return v != 'off'


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
        # cx_party_key() mirrors party_key for Latin names and is indexed (20261120b_vessel_owner_index.sql)
        cur.execute("""SELECT id, source, cx_party_key(full_name) AS k FROM screening_watchlist
                       WHERE cx_party_key(full_name) = ANY(%s) AND is_active = 1
                         AND coalesce(entity_type, '') <> 'VESSEL'""", (names,))
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


def _listed_risk(prof, n_lists, owner_listed, flags, psc=0):
    """(score, indicator codes) of a listed ship; facts (owner listed, several lists) carry no weight."""
    lines = []
    fl = (prof.get('current_flag') or '')
    fr = flags.get(fl.lower()) or flags.get((VU.flag_code(fl) or '-').lower()) or {}
    if '(false flag)' in fl:
        lines.append('false_flag')
    if fr.get('high_risk'):
        lines.append('high_risk_flag')
    elif fr.get('foc'):
        lines.append('foc')
    if len(_j(prof.get('flag_history'), []) or []) >= 2:
        lines.append('flag_changes')
    if _j(prof.get('previous_names'), []):
        lines.append('renamed')
    if prof.get('imo') and prof.get('imo_valid') is False:
        lines.append('invalid_imo')
    if psc >= 1:
        lines.append('psc_detained')
    if psc >= 3:
        lines.append('psc_repeated')
    if owner_listed:
        lines.append('owner_listed')
    if n_lists >= 2:
        lines.append('multi_list')
    return min(100, sum(RISK_WEIGHTS.get(x, 0) for x in lines)), lines


_CHANGE_FIELDS = ('name', 'imo', 'mmsi', 'current_flag', 'flag_history', 'previous_names', 'provenance', 'regimes',
                  'measures', 'vessel_type', 'is_active')


def _snapshot(cur, source):
    """{watchlist_id: {fields}} of the materialised ships of a source (or all), for the change log."""
    w = 'WHERE p.source = %s' if source else ''
    cur.execute(f"""SELECT p.watchlist_id, p.group_key, p.imo, p.mmsi, p.current_flag, p.flag_history, p.previous_names,
                           p.provenance, p.regimes, p.measures, p.vessel_type, w.full_name AS name, w.is_active, p.source
                    FROM vessel_profile p LEFT JOIN screening_watchlist w ON w.id = p.watchlist_id {w}""",
                (source,) if source else ())
    return {r['watchlist_id']: r for r in _rows(cur)}


def _change_log(cur, run_id, before, after, log=None):
    """Write the added / removed / changed ships between two snapshots. Returns (added, removed, changed)."""
    if not before:          # first load of these lists: counts only, no row per ship
        return sum(1 for r in after.values() if r.get('is_active')), 0, 0
    added = removed = changed = 0
    rows = []
    for wid, new in after.items():
        old = before.get(wid)
        if new.get('is_active') and (old is None or not old.get('is_active')):
            added += 1
            rows.append(('added', new, None))
        elif old is not None and old.get('is_active') and not new.get('is_active'):
            removed += 1
            rows.append(('removed', new, None))
        elif old is not None and new.get('is_active'):
            # a column filled for the first time (old value NULL after a migration) is not a change of the ship
            diff = {f: [old.get(f), new.get(f)] for f in _CHANGE_FIELDS
                    if f != 'is_active' and str(old.get(f) or '') != str(new.get(f) or '')
                    and not (f == 'regimes' and old.get(f) is None)}
            if diff:
                changed += 1
                rows.append(('changed', new, diff))
    for wid, old in before.items():
        if wid not in after and old.get('is_active'):
            removed += 1
            rows.append(('removed', old, None))
    if rows:
        from psycopg2.extras import execute_values
        execute_values(cur, """INSERT INTO vessel_change_log (run_id, source, change, watchlist_id, group_key, imo, name,
                                                           provenance, detail) VALUES %s""",
                       [(run_id, r.get('source'), ch, r.get('watchlist_id'), r.get('group_key'), r.get('imo'),
                         (r.get('name') or '')[:300], r.get('provenance'),
                         json.dumps(d, ensure_ascii=False, default=str) if d else None) for ch, r, d in rows],
                       page_size=1000)
    return added, removed, changed


def _start_run(conn, source, trigger, user_id):
    rows = read_rows(conn, """INSERT INTO vessel_update_runs (source, trigger, user_id) VALUES (%s, %s, %s)
                              RETURNING id""", (source, trigger, user_id))
    conn.commit()
    return (rows or [{}])[0].get('id')


def sync(conn, source=None, log=None, trigger='list_update', user_id=None):
    """Rebuild vessel_profile / vessel_identifier / vessel_party_link for one source (or all) from the
    VESSEL rows of screening_watchlist (no download), classify each record's provenance
    (screening/vessel_provenance.py), refresh the risk of every ship, re-check the whitelist and bump the
    data version (every worker drops its cache). Idempotent; commits. Returns counts."""
    from screening import vessel_provenance as VP
    from screening import vessel_regimes as VR
    log = log or logger.info
    t0 = time.time()
    table = VP.classes(conn)
    run_id = _start_run(conn, source, trigger, user_id)
    cur = conn.cursor()
    try:
        before = _snapshot(cur, source)
    except Exception:
        conn.rollback()
        cur = conn.cursor()
        before = {}
    params = []
    where = "entity_type = 'VESSEL'"
    if source:
        where += ' AND source = %s'
        params.append(source)
    cur.execute(f"SELECT id, source, source_id, properties, details, topics FROM screening_watchlist WHERE {where}",
                params)
    rows = _rows(cur)
    profiles, idents, links = [], [], []
    classes_n, unclassified = {}, set()
    for row in rows:
        block = vessel_block(row)
        if not block:
            continue
        prof, ids = _profile_values(row['id'], row['source'], block)
        props = _j(row.get('properties'), {}) or {}
        pv = VP.classify(row['source'], props.get('datasets') if isinstance(props, dict) else None,
                         _j(row.get('topics'), []) or [], table)
        prof['provenance'] = pv['class']
        det = _j(row.get('details'), {}) or {}
        det = det if isinstance(det, dict) else {}
        props_d = props if isinstance(props, dict) else {}
        comments = det.get('comments') or ''
        prof['regimes'] = json.dumps(VR.regimes_of(
            props_d.get('programs') or [], props_d.get('regime'), det.get('program'), det.get('regime'),
            re.findall(r'resolution\s+\d{4}', str(comments), re.I), topics=_j(row.get('topics'), []) or [])) or None
        prof['datasets'] = json.dumps(pv['datasets']) if pv['datasets'] else None
        prof['risk_datasets'] = json.dumps(pv['risk_datasets']) if pv['risk_datasets'] else None
        classes_n[pv['class']] = classes_n.get(pv['class'], 0) + 1
        unclassified.update(pv['unclassified'])
        profiles.append(prof)
        idents += ids
        if not VP.alerts(pv['class']):
            continue            # owners of a ship that never alerts are not needed
        for o in (block.get('owners') or []):
            name = str(o.get('name') or '').strip()
            if not name and not o.get('ref'):
                continue
            links.append((row['id'], o.get('ref'), name[:500] or None, (o.get('role') or 'owner')[:30],
                          row['source']))
    resolved = _resolve_parties(cur, links)
    # replace the source's materialised rows in one transaction (by source, and by the rows' ids, so rows of a
    # record that moved to another source go too); rows of records deleted from the list (orphans) go as well
    if source:
        for t in ('vessel_identifier', 'vessel_party_link', 'vessel_profile'):
            cur.execute(f'DELETE FROM {t} WHERE source = %s OR watchlist_id IN '
                        f'(SELECT id FROM screening_watchlist WHERE source = %s)', (source, source))
    else:
        for t in ('vessel_identifier', 'vessel_party_link', 'vessel_profile'):
            cur.execute(f'DELETE FROM {t}')
    for t in ('vessel_identifier', 'vessel_party_link', 'vessel_profile'):
        cur.execute(f'DELETE FROM {t} x WHERE NOT EXISTS (SELECT 1 FROM screening_watchlist w WHERE w.id = x.watchlist_id)')
    from psycopg2.extras import execute_values
    cols = ('watchlist_id', 'source', 'imo', 'imo_valid', 'mmsi', 'call_sign', 'vessel_type', 'current_flag',
            'flag_history', 'previous_names', 'gross_tonnage', 'year_built', 'measures', 'owners', 'group_key',
            'provenance', 'datasets', 'risk_datasets', 'regimes')
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
    after = _snapshot(cur, source)
    added, removed, changed = _change_log(cur, run_id, before, after)
    conn.commit()
    risk = refresh_risk(conn)
    reopened = check_whitelist(conn)
    bump_version(conn, f'sync {source or "all"}')
    read_rows(conn, """UPDATE vessel_update_runs SET finished_at = now(), status = 'done', vessels = %s, added = %s,
                              removed = %s, changed = %s, by_class = %s, message = %s WHERE id = %s RETURNING id""",
              (len(profiles), added, removed, changed, json.dumps(classes_n),
               'initial load' if not before else None, run_id))
    conn.commit()
    out = {'source': source or 'all', 'run_id': run_id, 'added': added, 'removed': removed, 'changed': changed,
           'vessels': len(profiles), 'by_class': classes_n,
           'unclassified_datasets': sorted(unclassified),
           'with_imo': sum(1 for p in profiles if p['imo']),
           'imo_check_fails': sum(1 for p in profiles if p['imo'] and p['imo_valid'] is False),
           'identifiers': len(idents), 'parties': len(resolved),
           'parties_listed': sum(1 for r in resolved if r[1]), 'risk_rows': risk,
           'whitelist_reopened': reopened, 'seconds': round(time.time() - t0, 1)}
    log(f'[VESSELS] materialised {out}')
    return out


def refresh_risk(conn):
    """Risk indicators of every listed ship, per ship (all list records of the same IMO): flags, renames,
    IMO check digit, port-state-control records. Every record of a ship gets the ship's score."""
    cur = conn.cursor()
    flags = flag_risk(conn, force=True)
    cur.execute("""SELECT p.watchlist_id, p.imo, p.imo_valid, p.current_flag, p.flag_history, p.previous_names,
                          p.group_key, p.provenance, p.risk_datasets, w.source, w.is_active,
                          EXISTS (SELECT 1 FROM vessel_party_link l JOIN screening_watchlist o
                                    ON o.id = l.party_watchlist_id AND o.is_active = 1
                                   WHERE l.watchlist_id = p.watchlist_id) AS owner_listed
                   FROM vessel_profile p JOIN screening_watchlist w ON w.id = p.watchlist_id""")
    groups = {}
    for r in _rows(cur):
        groups.setdefault(r['group_key'], []).append(r)
    upd = []
    for gk, recs in groups.items():
        active = [r for r in recs if r['is_active']] or recs
        lists = {r['source'] for r in active if r['provenance'] == 'SANCTION'}
        psc = len({d for r in active for d in (_j(r['risk_datasets'], []) or [])})
        merged = {'current_flag': next((r['current_flag'] for r in active if r['current_flag']), None),
                  'flag_history': json.dumps(sorted({x for r in active for x in _j(r['flag_history'], []) or []})),
                  'previous_names': json.dumps(sorted({x for r in active for x in _j(r['previous_names'], []) or []})),
                  'imo': next((r['imo'] for r in active if r['imo']), None),
                  'imo_valid': next((r['imo_valid'] for r in active if r['imo']), None)}
        score, lines = _listed_risk(merged, len(lists), any(r['owner_listed'] for r in active), flags, psc)
        for r in recs:
            upd.append((score, json.dumps(lines), r['watchlist_id']))
    if upd:
        from psycopg2.extras import execute_batch
        execute_batch(cur, 'UPDATE vessel_profile SET risk_score = %s, risk_lines = %s WHERE watchlist_id = %s',
                      upd, page_size=1000)
    conn.commit()
    return len(upd)


# --------------------------------------------------------------------------- engine data
_CACHE = {}
_TTL = 600                     # upper bound; the data-version stamp normally invalidates much sooner
STAMP_EVERY = 3.0              # seconds between two reads of the stamp in one process
_STAMP = {'at': 0.0, 'value': None}


def bump_version(conn, reason=''):
    """Tell every worker that the vessel data or settings changed (their caches are dropped on their next
    screening). Runs in the caller's transaction; the caller commits."""
    rows = read_rows(conn, """UPDATE vessel_data_version SET version = version + 1, updated_at = now(), reason = %s
                              WHERE id = 1 RETURNING version""", (str(reason or '')[:200],))
    _CACHE.clear()
    _STAMP['at'] = 0.0
    return (rows or [{}])[0].get('version')


def data_stamp(conn):
    """The data version + a digest of the vessel settings in screening_config (one indexed single-row read)."""
    rows = read_rows(conn, """SELECT (SELECT version FROM vessel_data_version WHERE id = 1) AS v,
                                     (SELECT md5(coalesce(string_agg(config_key || '=' || coalesce(config_value, ''), ';'
                                                                     ORDER BY config_key), ''))
                                        FROM screening_config WHERE left(config_key, 6) = 'vessel') AS c""")
    if not rows:
        return None
    return f"{rows[0].get('v')}|{rows[0].get('c')}"


def check_stamp(conn, force=False):
    """Drop this process's caches when another process changed the vessel data or settings."""
    now = time.time()
    if not force and now - _STAMP['at'] < STAMP_EVERY:
        return
    _STAMP['at'] = now
    try:
        st = data_stamp(conn)
    except Exception:
        return
    if st is not None and st != _STAMP['value']:
        if _STAMP['value'] is not None:
            _CACHE.clear()
        _STAMP['value'] = st


def load_candidates(conn, force=False):
    """All active listed vessels with their names, cached for 10 minutes per process.
    [{watchlist_id, group_key, source, list_type, name, names[], imo, mmsi, call_sign, flag, flags_past[],
      type, year_built, measures[], owners[], parties[], risk_score}]"""
    key = 'cands'
    check_stamp(conn)
    now = time.time()
    if not force and key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    inc_os = include_opensanctions(conn)
    cur = conn.cursor()
    cur.execute("""SELECT w.id, w.source, w.list_type, w.full_name, w.aliases, w.full_name_arabic,
                          w.aliases_arabic, w.original_name,
                          p.imo, p.imo_valid, p.mmsi, p.call_sign, p.vessel_type, p.current_flag, p.flag_history,
                          p.previous_names, p.year_built, p.measures, p.owners, p.gross_tonnage, p.group_key,
                          p.risk_score, p.provenance, p.risk_datasets, p.regimes
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
            'provenance': row.get('provenance') or 'SANCTION',
            'risk_datasets': _j(row.get('risk_datasets'), []) or [],
            'regimes': _j(row.get('regimes'), []) or [],
        })
    add_known_names(out, known_names(conn))
    _CACHE[key] = (now, out)
    return out


# --------------------------------------------------------------------------- names known before the lists
def known_names(conn, group_key=None):
    """Active names ComplyNex knows for listed ships that the lists have not published yet (a ship renamed
    after its listing), entered or confirmed by the platform superadmin. [{id, group_key, name, kind, ...}]"""
    sql = 'SELECT * FROM vessel_known_names WHERE status = %s'
    params = ['active']
    if group_key:
        sql += ' AND group_key = %s'
        params.append(group_key)
    return read_rows(conn, sql + ' ORDER BY id', tuple(params)) or []


def add_known_names(cands, rows):
    """Add the known names to every record of their ship (same group), marked as ComplyNex intelligence."""
    by_group = {}
    for r in rows or []:
        by_group.setdefault(r['group_key'], []).append(r)
    if not by_group:
        return cands
    for c in cands:
        for r in by_group.get(c.get('group_key')) or []:
            if r['name'] not in c['names']:
                c['names'] = c['names'] + [r['name']]
            if r.get('kind') == 'former_name' and r['name'] not in c['previous_names']:
                c['previous_names'] = c['previous_names'] + [r['name']]
            c.setdefault('known_names', [])
            if r['name'] not in c['known_names']:
                c['known_names'] = c['known_names'] + [r['name']]
    return cands


def add_known_name(conn, group_key, name, source_note, user_id, imo=None, kind='new_name', effective_date=None,
                   observation_id=None):
    """Record a name for a listed ship (superadmin). Returns the new row id, or None when it is already known.
    The caller commits; every worker reloads its ship names on its next screening."""
    from screening import vessel_utils as VU
    nm = ' '.join(str(name or '').split())[:200]
    norm = VU.norm_name(nm)
    if not nm or not norm or not group_key:
        return None
    rows = read_rows(conn, """INSERT INTO vessel_known_names (group_key, imo, name, name_norm, kind, source_note,
                                                               effective_date, observation_id, created_by)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                              ON CONFLICT (group_key, name_norm) WHERE status = 'active' DO NOTHING
                              RETURNING id""",
                     (group_key, imo, nm, norm, kind if kind in ('new_name', 'alias', 'former_name') else 'new_name',
                      str(source_note or '')[:1000], effective_date or None, observation_id, user_id))
    if not rows:
        return None
    bump_version(conn, 'known name added')
    return rows[0]['id']


def revoke_known_name(conn, kid, user_id, reason):
    rows = read_rows(conn, """UPDATE vessel_known_names SET status = 'revoked', revoked_by = %s, revoked_at = now(),
                                     revoke_reason = %s WHERE id = %s AND status = 'active' RETURNING group_key, name""",
                     (user_id, str(reason or '')[:500], kid))
    if rows:
        bump_version(conn, 'known name revoked')
    return (rows or [None])[0]


def record_name_observations(conn, res, screening_id=None):
    """Queue for the superadmin the names entered in a screening that differ from the listed name of a ship the
    IMO / MMSI / call sign confirmed (possibly a new name the lists have not published). One row per ship and
    entered name, counted on repeats. Never fails the screening."""
    from screening import vessel_utils as VU
    n = 0
    for h in res.get('hits') or []:
        d = h.get('entered_name_differs')
        if not d or not h.get('group_key'):
            continue
        norm = VU.norm_name(d.get('entered'))
        if not norm:
            continue
        rows = read_rows(conn, """INSERT INTO vessel_name_observations (group_key, imo, listed_name, entered_name,
                                                                      entered_norm, identifier, last_screening_id)
                                  VALUES (%s, %s, %s, %s, %s, %s, %s)
                                  ON CONFLICT (group_key, entered_norm) DO UPDATE SET seen_count =
                                    vessel_name_observations.seen_count + 1, last_seen = now(),
                                    last_screening_id = EXCLUDED.last_screening_id
                                  RETURNING id""",
                         (h['group_key'], h.get('imo'), h.get('name'), str(d.get('entered'))[:200], norm,
                          d.get('identifier') or 'IMO', screening_id))
        n += bool(rows)
    return n


# --------------------------------------------------------------------------- update status and schedule
DEFAULT_UPDATE_TIME = '03:30'      # the daily list update (deploy/systemd/complynex-sanctions-update.timer.d)


def update_schedule(conn=None):
    """(hour, minute) of the daily list update: screening_config 'lists_update_time' ('HH:MM'), else 03:30,
    the time the server's timer runs it."""
    raw = config_value(conn, 'lists_update_time') if conn is not None else None
    m = re.match(r'^\s*(\d{1,2}):(\d{2})\s*$', str(raw or DEFAULT_UPDATE_TIME))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        m = re.match(r'(\d+):(\d+)', DEFAULT_UPDATE_TIME)
    return int(m.group(1)), int(m.group(2))


def next_update(conn=None, now=None):
    from datetime import datetime, timedelta
    now = now or datetime.now()
    h, mi = update_schedule(conn)
    nxt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    return nxt if nxt > now else nxt + timedelta(days=1)


def update_status(conn):
    """{'last_update', 'last_run', 'next_update', 'stale', 'ships': {class: n}} for the status lines."""
    from datetime import datetime, timedelta
    run = (read_rows(conn, """SELECT id, trigger, status, started_at, finished_at, added, removed, changed, message
                               FROM vessel_update_runs WHERE status = 'done' ORDER BY id DESC LIMIT 1""") or [None])[0]
    src = (read_rows(conn, """SELECT max(d.last_successful_update) AS at FROM screening_data_sources d
                               WHERE d.source_name IN (SELECT DISTINCT source FROM vessel_profile)""") or [{}])[0]
    cands = [x for x in (run and (run.get('finished_at') or run.get('started_at')), src.get('at')) if x]
    last = None
    for x in cands:
        if isinstance(x, str):
            try:
                x = datetime.fromisoformat(x[:19])
            except ValueError:
                continue
        x = x.astimezone().replace(tzinfo=None) if getattr(x, 'tzinfo', None) else x
        last = x if last is None or x > last else last
    ships = {r['provenance']: r['n'] for r in read_rows(
        conn, """SELECT p.provenance, count(DISTINCT p.group_key) AS n FROM vessel_profile p
                  JOIN screening_watchlist w ON w.id = p.watchlist_id WHERE w.is_active = 1
                  GROUP BY p.provenance""") or []}
    return {'last_update': last, 'last_run': run, 'next_update': next_update(conn),
            'stale': last is None or datetime.now() - last > timedelta(hours=48), 'ships': ships}


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
    check_stamp(conn)
    if not force and 'flags' in _CACHE and time.time() - _CACHE['flags'][0] < _TTL:
        return _CACHE['flags'][1]
    out = {}
    for r in read_rows(conn, 'SELECT * FROM flag_risk') or []:
        v = {'foc': bool(r.get('flag_of_convenience')), 'high_risk': bool(r.get('high_risk')),
             'note': r.get('note')}
        out[str(r['country']).lower()] = v
        if r.get('iso2'):
            out[str(r['iso2']).lower()] = v
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
    rows = read_rows(conn, """SELECT w.*, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS by_name
                              FROM vessel_whitelist w LEFT JOIN users u ON u.id = w.created_by
                              WHERE w.query_key = %s AND w.status IN ('active', 'reopened')
                              ORDER BY w.created_at""", (qkey,)) or []
    return {r['listed_key']: r for r in rows}


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
    base['regimes'] = sorted({r for m in members for r in m.get('regimes') or []})
    return base
