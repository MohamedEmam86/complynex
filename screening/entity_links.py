"""
P2-6 / G5 — the same person or entity on several lists, at screening time.

The link tables are built by scripts/build_entity_links.py (never on a name
alone; rows are never merged). This module reads them:

  annotate(matches)          engine: hits of one cluster and the same kind
                             (sanctions / PEP / other) become ONE hit with
                             several sources; hits of one cluster in different
                             kinds point at each other. Nothing is dropped: the
                             secondary hits stay inside the primary
                             ('grouped_hits') and every hit keeps its own score.
  members(cur, table, row)   match profile: the other records of the cluster,
                             which list each one comes from, and a differences
                             report (date of birth, nationality, IDs).
  unlink(...)                MLRO: take one record out of its group (audited,
                             respected by every rebuild).

Every function fails open: no tables, no cluster or any error = the result is
exactly what it was without this module.
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

SOURCE_RANK = {'emlcu': 0, 'pma_ps': 1, 'internal_blacklist': 2, 'internal_pep': 3, 'un': 4,
               'ofac': 5, 'hmt': 6, 'eu': 7, 'opensanctions': 8, 'opensanctions_pep': 9}
BASIS_LABEL = {
    'lead': 'Leading (official) record',
    'os_id': 'Same OpenSanctions entity',
    'os_referent': 'OpenSanctions copy of this OFAC record',
    'linked_internal': 'Same full national ID (EMLCU and Public Prosecution order)',
    'official_id': 'Same official ID number',
    'passport': 'Same passport number and nationality / birth year',
    'name_dob_nationality': 'Same full name, date of birth and nationality',
}
_MAX_MEMBERS = 50
_TABLES = {'ok': None}


def _rank(src):
    return SOURCE_RANK.get(str(src or '').lower(), 10)


def _tables_ok(cur):
    if _TABLES['ok'] is None:
        try:
            cur.execute("SELECT to_regclass('screening_entity_links') IS NOT NULL")
            r = cur.fetchone()
            _TABLES['ok'] = bool(r[0] if not isinstance(r, dict) else list(r.values())[0])
        except Exception:
            return False
    return _TABLES['ok']


def _val(r, k, i):
    return r[k] if isinstance(r, dict) else r[i]


def watchlist_sid(table, source_id, full_name):
    """source_id of the watchlist copy of an internal-list row (sync_internal_to_watchlist.py)."""
    import hashlib
    prefix = 'IPEP' if table == 'internal_pep' else 'IBL'
    if source_id and str(source_id).startswith(prefix + '-'):
        return str(source_id)
    if not full_name:
        return None
    return prefix + '-' + hashlib.md5(str(full_name).strip().lower().encode()).hexdigest()[:12].upper()


def _hit_key(m):
    """('id', watchlist id) for list hits, ('sid', source, source_id) for internal-list hits."""
    src = str(m.get('source') or '').lower()
    if src.startswith('internal'):
        table = 'internal_pep' if 'pep' in src else 'internal_blacklist'
        sid = m.get('source_id') if isinstance(m.get('source_id'), str) else None
        if sid and sid.startswith(('IBL-', 'IPEP-')):
            return ('sid', table, sid)
        if m.get('entity_id') is not None:
            return ('int', table, m.get('entity_id'))
        return None
    try:
        return ('id', int(str(m.get('id'))))
    except (TypeError, ValueError):
        return None


def lookup(cur, matches):
    """{index of hit: (cluster_id, watchlist_id)} and {cluster_id: [member rows]}."""
    keys = {i: _hit_key(m) for i, m in enumerate(matches) if isinstance(m, dict)}
    keys = {i: k for i, k in keys.items() if k}
    if not keys or not _tables_ok(cur):
        return {}, {}
    # internal-list hits carry the internal row id: find their watchlist copy
    for table in ('internal_blacklist', 'internal_pep'):
        rows = sorted({int(k[2]) for k in keys.values() if k[0] == 'int' and k[1] == table and str(k[2]).isdigit()})
        if not rows:
            continue
        cur.execute(f"SELECT id, source_id, full_name FROM {table} WHERE id = ANY(%s)", (rows,))
        sid_of = {}
        for r in cur.fetchall():
            sid_of[_val(r, 'id', 0)] = watchlist_sid(table, _val(r, 'source_id', 1), _val(r, 'full_name', 2))
        for i, k in list(keys.items()):
            if k[0] == 'int' and k[1] == table:
                s = sid_of.get(int(k[2])) if str(k[2]).isdigit() else None
                keys[i] = ('sid', table, s) if s else None
    keys = {i: k for i, k in keys.items() if k}
    ids = sorted({k[1] for k in keys.values() if k[0] == 'id'})
    sids = sorted({k[2] for k in keys.values() if k[0] == 'sid'})
    cur.execute("""SELECT watchlist_id, cluster_id, source, source_id FROM screening_entity_links
                   WHERE watchlist_id = ANY(%s) OR (source IN ('internal_blacklist', 'internal_pep') AND source_id = ANY(%s))""",
                (ids or [0], sids or ['']))
    by_id, by_sid = {}, {}
    for r in cur.fetchall():
        wid, cid, src, sid = (_val(r, 'watchlist_id', 0), _val(r, 'cluster_id', 1), _val(r, 'source', 2), _val(r, 'source_id', 3))
        by_id[wid] = cid
        if sid:
            by_sid[(src, sid)] = (cid, wid)
    hit_cluster = {}
    for i, k in keys.items():
        if k[0] == 'id' and k[1] in by_id:
            hit_cluster[i] = (by_id[k[1]], k[1])
        elif k[0] == 'sid' and (k[1], k[2]) in by_sid:
            hit_cluster[i] = by_sid[(k[1], k[2])]
    if not hit_cluster:
        return {}, {}
    cids = sorted({c for c, _ in hit_cluster.values()})
    cur.execute("""SELECT l.cluster_id, l.watchlist_id, l.source, l.basis, w.list_type, w.dataset, w.full_name,
                          w.full_name_arabic
                   FROM screening_entity_links l JOIN screening_watchlist w ON w.id = l.watchlist_id
                   WHERE l.cluster_id = ANY(%s) ORDER BY l.cluster_id, l.watchlist_id""", (cids,))
    members = {}
    for r in cur.fetchall():
        cid = _val(r, 'cluster_id', 0)
        lst = members.setdefault(cid, [])
        if len(lst) < _MAX_MEMBERS:
            lst.append({'watchlist_id': _val(r, 'watchlist_id', 1), 'source': _val(r, 'source', 2),
                        'basis': _val(r, 'basis', 3), 'list_type': _val(r, 'list_type', 4),
                        'dataset': _val(r, 'dataset', 5)})
    return hit_cluster, members


def _label(src, dataset=None):
    try:
        from screening.result_view import SOURCE_LABEL
        base = SOURCE_LABEL.get(str(src or '').lower()) or SOURCE_LABEL.get(str(src or '')) or str(src or '')
    except Exception:
        base = str(src or '')
    return f'{base} · {dataset}' if dataset and str(dataset).lower() != str(src or '').lower() else base


def annotate(matches, cur=None):
    """Group the hits of one cluster (see module doc). Returns the new hit list."""
    if not matches:
        return matches
    try:
        if cur is None:
            from screening.db_pool import db_pool
            with db_pool.get_connection() as conn:
                c = conn.cursor()
                try:
                    hit_cluster, members = lookup(c, matches)
                finally:
                    try:
                        conn.rollback()     # read only: hand the connection back clean
                    except Exception:
                        pass
        else:
            hit_cluster, members = lookup(cur, matches)
        if not hit_cluster:
            return matches
        from screening.match_classifier import classify_match
        kinds = {}
        for i in hit_cluster:
            try:
                kinds[i] = classify_match(matches[i])
            except Exception:
                kinds[i] = 'OTHER'
        groups = {}
        for i, (cid, _) in hit_cluster.items():
            groups.setdefault(cid, []).append(i)
        drop = set()
        for cid, idx in groups.items():
            mem = members.get(cid) or []
            by_kind = {}
            for i in idx:
                by_kind.setdefault(kinds[i], []).append(i)
            primaries = {}
            for k, ii in by_kind.items():
                ii.sort(key=lambda i: (-float(matches[i].get('match_score') or 0), _rank(matches[i].get('source'))))
                p = ii[0]
                primaries[k] = p
                prim = matches[p]
                for j in ii[1:]:
                    s = matches[j]
                    prim.setdefault('grouped_hits', []).append({
                        'source': s.get('source'), 'dataset': s.get('dataset') or s.get('category'),
                        'score': s.get('match_score'), 'tier': (s.get('decision') or {}).get('tier'),
                        'name': s.get('watchlist_name_ar') or s.get('original_name') or s.get('full_name'),
                        'list_type': s.get('list_type'), 'id': s.get('id'), 'entity_id': s.get('entity_id')})
                    lab = _label(s.get('source'), s.get('dataset') or s.get('category'))
                    also = prim.setdefault('also_listed_in', [])
                    if lab and lab not in also:
                        also.append(lab)
                    drop.add(j)
            hit_ids = {hit_cluster[i][1] for i in idx}
            for k, p in primaries.items():
                prim = matches[p]
                others = [m for m in mem if m['watchlist_id'] != hit_cluster[p][1]]
                prim['cluster'] = {
                    'id': cid, 'size': len(mem),
                    'members': [{'source': m['source'], 'label': _label(m['source'], m.get('dataset')),
                                 'list_type': m.get('list_type'), 'basis': m['basis'],
                                 'basis_label': BASIS_LABEL.get(m['basis'], m['basis']),
                                 'in_result': m['watchlist_id'] in hit_ids} for m in others][:20],
                    'other_kinds': sorted(x for x in primaries if x != k),
                }
                for m in others:
                    lab = _label(m['source'], m.get('dataset'))
                    also = prim.setdefault('also_listed_in', [])
                    if lab and lab not in also and len(also) < 12:
                        also.append(lab)
        return [m for i, m in enumerate(matches) if i not in drop]
    except Exception as e:                     # never lose or change a hit because of this layer
        logger.warning('[ENTITY-LINKS] grouping skipped: %s', e)
        return matches


# --------------------------------------------------------------------------- profile page
def _as_list(v):
    if v is None:
        return []
    s = str(v).strip()
    if s.startswith('['):
        try:
            return [str(x) for x in json.loads(s) if x]
        except Exception:
            pass
    return [p.strip() for p in re.split(r'[;|]', s) if p.strip()]


def members(cur, table, row):
    """Cluster of a profile record: (members with basis + label, differences report) or ([], [])."""
    try:
        if not _tables_ok(cur):
            return [], []
        if table == 'screening_watchlist':
            cur.execute("SELECT cluster_id FROM screening_entity_links WHERE watchlist_id = %s", (row.get('id'),))
        else:
            src = 'internal_pep' if table == 'internal_pep' else 'internal_blacklist'
            cur.execute("SELECT cluster_id FROM screening_entity_links WHERE source = %s AND source_id = %s",
                        (src, watchlist_sid(table, row.get('source_id'), row.get('full_name'))))
        r = cur.fetchone()
        if not r:
            return [], []
        cid = _val(r, 'cluster_id', 0)
        cur.execute("""SELECT l.watchlist_id, l.basis, l.confidence, w.source, w.source_id, w.dataset, w.list_type,
                              w.full_name, w.full_name_arabic, w.date_of_birth, w.nationality, w.countries,
                              w.national_id_numbers, w.passport_numbers
                       FROM screening_entity_links l JOIN screening_watchlist w ON w.id = l.watchlist_id
                       WHERE l.cluster_id = %s ORDER BY l.watchlist_id LIMIT %s""", (cid, _MAX_MEMBERS))
        rows = [dict(x) if isinstance(x, dict) else dict(zip(
            ('watchlist_id', 'basis', 'confidence', 'source', 'source_id', 'dataset', 'list_type', 'full_name',
             'full_name_arabic', 'date_of_birth', 'nationality', 'countries', 'national_id_numbers',
             'passport_numbers'), x)) for x in cur.fetchall()]
        rows.sort(key=lambda m: (m['basis'] != 'lead', _rank(m['source']), m['watchlist_id']))
        self_sid = (watchlist_sid(table, row.get('source_id'), row.get('full_name'))
                    if table != 'screening_watchlist' else None)
        out = []
        for m in rows:
            m['label'] = _label(m['source'], m.get('dataset'))
            m['basis_label'] = BASIS_LABEL.get(m['basis'], m['basis'])
            m['is_self'] = (m['source_id'] == self_sid) if self_sid else (m['watchlist_id'] == row.get('id'))
            m['cluster_id'] = cid
            out.append(m)
        return out, differences(out)
    except Exception as e:
        logger.warning('[ENTITY-LINKS] profile members skipped: %s', e)
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return [], []


def differences(rows):
    """Fields on which the records of one group disagree: [{'field', 'values': [(label, value)]}]."""
    from screening.country_codes import to_iso2
    out = []

    def years(v):
        return {int(y) for p in _as_list(v) for y in re.findall(r'\b(1[89]\d{2}|20\d{2})\b', p)}

    def ids(v):
        return {re.sub(r'[^0-9A-Za-z]', '', x).upper() for x in _as_list(v)
                if len(re.sub(r'[^0-9A-Za-z]', '', x)) >= 6}

    def mask(s):
        s = str(s)
        return ('•' * (len(s) - 4) + s[-4:]) if len(s) > 4 else s

    with_dob = [(r['label'], r.get('date_of_birth'), years(r.get('date_of_birth'))) for r in rows if years(r.get('date_of_birth'))]
    if len(with_dob) > 1:
        ys = [y for _, _, y in with_dob]
        if not all(any(abs(a - b) <= 1 for a in x for b in y) for i, x in enumerate(ys) for y in ys[i + 1:]):
            out.append({'field': 'Date of birth', 'values': [(l, ', '.join(_as_list(v))) for l, v, _ in with_dob]})
    with_nat = [(r['label'], r.get('nationality'), to_iso2(r.get('nationality'))) for r in rows if to_iso2(r.get('nationality'))]
    if len(with_nat) > 1 and not set.intersection(*[c for _, _, c in with_nat]):
        out.append({'field': 'Nationality', 'values': [(l, ', '.join(_as_list(v))) for l, v, _ in with_nat]})
    with_id = [(r['label'], ids(r.get('national_id_numbers'))) for r in rows if ids(r.get('national_id_numbers'))]
    if len(with_id) > 1 and not set.intersection(*[s for _, s in with_id]):
        out.append({'field': 'National / official ID', 'values': [(l, ', '.join(mask(x) for x in sorted(s))) for l, s in with_id]})
    with_pp = [(r['label'], ids(r.get('passport_numbers'))) for r in rows if ids(r.get('passport_numbers'))]
    if len(with_pp) > 1 and not set.intersection(*[s for _, s in with_pp]):
        out.append({'field': 'Passport', 'values': [(l, ', '.join(mask(x) for x in sorted(s))) for l, s in with_pp]})
    return out


# --------------------------------------------------------------------------- MLRO unlink
def unlink(conn, watchlist_id, user_id, reason):
    """Take one record out of its group. Kept in screening_entity_unlinks so the next
    rebuild does not join it again; the link row is removed now. Returns the cluster id."""
    reason = (reason or '').strip()
    if len(reason) < 15:
        raise ValueError('Please give the reason (at least 15 characters).')
    cur = conn.cursor()
    cur.execute("SELECT cluster_id FROM screening_entity_links WHERE watchlist_id = %s FOR UPDATE", (int(watchlist_id),))
    r = cur.fetchone()
    if not r:
        conn.rollback()
        raise ValueError('This record is not linked to any other record.')
    cid = _val(r, 'cluster_id', 0)
    cur.execute("SELECT watchlist_id FROM screening_entity_links WHERE cluster_id = %s AND watchlist_id <> %s",
                (cid, int(watchlist_id)))
    others = sorted(_val(x, 'watchlist_id', 0) for x in cur.fetchall())
    cur.execute("""INSERT INTO screening_entity_unlinks (watchlist_id, other_ids, reason, unlinked_by)
                   VALUES (%s, %s, %s, %s)""", (int(watchlist_id), json.dumps(others), reason[:1000], user_id))
    cur.execute("DELETE FROM screening_entity_links WHERE watchlist_id = %s", (int(watchlist_id),))
    if len(others) < 2:
        # a group of one is no group
        cur.execute("DELETE FROM screening_entity_links WHERE cluster_id = %s", (cid,))
        cur.execute("DELETE FROM screening_entity_clusters WHERE id = %s", (cid,))
    else:
        cur.execute("UPDATE screening_entity_clusters SET member_count = %s WHERE id = %s", (len(others), cid))
        cur.execute("SELECT lead_watchlist_id FROM screening_entity_clusters WHERE id = %s", (cid,))
        lead = cur.fetchone()
        if lead and _val(lead, 'lead_watchlist_id', 0) == int(watchlist_id):
            cur.execute("""SELECT watchlist_id, source FROM screening_entity_links WHERE cluster_id = %s""", (cid,))
            rest = [(_val(x, 'watchlist_id', 0), _val(x, 'source', 1)) for x in cur.fetchall()]
            new = min(rest, key=lambda t: (_rank(t[1]), t[0]))[0]
            cur.execute("UPDATE screening_entity_clusters SET lead_watchlist_id = %s WHERE id = %s", (new, cid))
            cur.execute("UPDATE screening_entity_links SET basis = 'lead' WHERE watchlist_id = %s", (new,))
    conn.commit()
    return cid
