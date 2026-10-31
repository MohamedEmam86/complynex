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
G13 — relatives and close associates (RCA) of politically exposed persons.

Links live in screening_pep_relations (one row per relation, never merged into the
listed records):
  * origin 'opensanctions': Family / Associate entities of the OpenSanctions exports,
    imported by scripts/import_pep_relations.py (both sides are OpenSanctions ids, so
    the side's source is stored as 'opensanctions' and matches both OpenSanctions feeds);
  * origin 'manual': added by the MLRO on the match profile page (reason, audited).

annotate(matches)   engine: adds 'pep_relations' to a hit whose record is linked to
                    another record (max 5), and 'pep_related' = True when the other side
                    is a PEP. It never removes, reorders or re-scores a hit. The workflow
                    layer then labels the hit "related to PEP X (relation)" and gives a
                    background-type record (CONTEXT / POI) the PEP action (EDD).
for_record(cur,row) match profile: every relative / associate of the shown record.

Every function fails open: no table, no link or any error = the hits are exactly what
they were without this module.
"""
import logging
import time

logger = logging.getLogger(__name__)

OS_SOURCES = ('opensanctions', 'opensanctions_pep')
RELATION_TYPES = ('family', 'associate')
TYPE_LABEL = {'family': ('Family member', 'فرد من العائلة'),
              'associate': ('Close associate', 'شريك / مقرّب')}
_MAX_PER_HIT = 5
_RECHECK = 300
_TABLE = {'ok': None, 'at': 0.0}


def _val(r, k, i):
    return r[k] if isinstance(r, dict) else r[i]


def side_source(source):
    """Relations store OpenSanctions sides as 'opensanctions' (one id, two feeds)."""
    s = str(source or '').strip().lower()
    return 'opensanctions' if s in OS_SOURCES else s


def _table_ok(cur):
    now = time.time()
    if _TABLE['ok'] is True or (_TABLE['ok'] is False and now - _TABLE['at'] < _RECHECK):
        return _TABLE['ok']
    try:
        cur.execute("SELECT to_regclass('screening_pep_relations') IS NOT NULL AS ok")
        _TABLE['ok'], _TABLE['at'] = bool(_val(cur.fetchone(), 'ok', 0)), time.time()
    except Exception:
        return False
    return _TABLE['ok']


def is_pep_record(row):
    """A listed record that is itself a PEP (list type or OpenSanctions role topics)."""
    if not row:
        return False
    lt = str(_get(row, 'list_type') or '').upper()
    src = str(_get(row, 'source') or '').lower()
    topics = str(_get(row, 'topics') or '')
    if lt == 'PEP' or src in ('opensanctions_pep', 'internal_pep'):
        return True
    return 'role.pep' in topics or 'role.pol' in topics


def _get(row, k):
    try:
        return row.get(k) if isinstance(row, dict) else None
    except Exception:
        return None


def _hit_key(m):
    sid = m.get('source_id')
    if not isinstance(sid, str) or not sid:
        return None
    return (side_source(m.get('source')), sid)


def _links(cur, keys):
    """Active relations touching any of keys [(source, source_id)] -> rows."""
    if not keys:
        return []
    srcs = [k[0] for k in keys]
    sids = [k[1] for k in keys]
    cur.execute("""
        WITH k AS (SELECT * FROM unnest(%s::text[], %s::text[]) AS k(src, sid))
        SELECT r.id, r.pep_source, r.pep_source_id, r.related_source, r.related_source_id,
               r.relation_type, r.relationship, r.origin
          FROM screening_pep_relations r
          JOIN k ON (r.pep_source = k.src AND r.pep_source_id = k.sid)
                 OR (r.related_source = k.src AND r.related_source_id = k.sid)
         WHERE r.is_active
         LIMIT 2000""", (srcs, sids))
    return [{'id': _val(r, 'id', 0), 'pep': (_val(r, 'pep_source', 1), _val(r, 'pep_source_id', 2)),
             'rel': (_val(r, 'related_source', 3), _val(r, 'related_source_id', 4)),
             'type': _val(r, 'relation_type', 5), 'relationship': _val(r, 'relationship', 6),
             'origin': _val(r, 'origin', 7)} for r in cur.fetchall()]


def _records(cur, keys):
    """(source, source_id) -> the active watchlist record shown for that side
    (an OpenSanctions id prefers its PEP-feed row)."""
    out = {}
    if not keys:
        return out
    os_ids = sorted({sid for src, sid in keys if src == 'opensanctions'})
    other = sorted({(src, sid) for src, sid in keys if src != 'opensanctions'})
    if os_ids:
        cur.execute("""SELECT DISTINCT ON (source_id) id, source, source_id, full_name, full_name_arabic,
                              list_type, topics, date_of_birth, nationality
                         FROM screening_watchlist
                        WHERE source IN ('opensanctions_pep', 'opensanctions') AND source_id = ANY(%s)
                          AND is_active = 1
                        ORDER BY source_id, (source = 'opensanctions_pep') DESC""", (os_ids,))
        for r in cur.fetchall():
            d = dict(r) if isinstance(r, dict) else dict(zip(
                ('id', 'source', 'source_id', 'full_name', 'full_name_arabic', 'list_type', 'topics',
                 'date_of_birth', 'nationality'), r))
            out[('opensanctions', d['source_id'])] = d
    if other:
        cur.execute("""SELECT id, source, source_id, full_name, full_name_arabic, list_type, topics,
                              date_of_birth, nationality
                         FROM screening_watchlist
                        WHERE (source, source_id) IN (SELECT * FROM unnest(%s::text[], %s::text[]))
                          AND is_active = 1""", ([o[0] for o in other], [o[1] for o in other]))
        for r in cur.fetchall():
            d = dict(r) if isinstance(r, dict) else dict(zip(
                ('id', 'source', 'source_id', 'full_name', 'full_name_arabic', 'list_type', 'topics',
                 'date_of_birth', 'nationality'), r))
            out[(side_source(d['source']), d['source_id'])] = d
    return out


def _summaries(cur, key, links, records, limit=None):
    """The relations of one record, seen from that record: the OTHER side + relation."""
    out = []
    for ln in links:
        if ln['pep'] == key:
            other, role = ln['rel'], 'has_relative'       # this record is the PEP side
        elif ln['rel'] == key:
            other, role = ln['pep'], 'relative_of'        # this record is the relative / associate
        else:
            continue
        rec = records.get(other)
        if not rec:
            continue                                        # other side no longer listed
        out.append({'relation_id': ln['id'], 'type': ln['type'], 'relationship': ln['relationship'] or '',
                    'origin': ln['origin'], 'role': role,
                    'other_name': rec.get('full_name_arabic') or rec.get('full_name') or '',
                    'other_name_latin': rec.get('full_name') or '',
                    'other_source': rec.get('source'), 'other_watchlist_id': rec.get('id'),
                    'other_is_pep': is_pep_record(rec)})
    # a PEP on the other side first
    out.sort(key=lambda x: (not x['other_is_pep'], x['type'] != 'family'))
    return out[:limit] if limit else out


def annotate(matches, cur=None):
    """Tag hits linked to a PEP (see module doc). Returns the SAME list; adds only
    'pep_relations' and 'pep_related'."""
    if not matches:
        return matches
    try:
        keys = {}
        for i, m in enumerate(matches):
            if isinstance(m, dict):
                k = _hit_key(m)
                if k:
                    keys.setdefault(k, []).append(i)
        if not keys:
            return matches

        def _run(c):
            if not _table_ok(c):
                return None
            links = _links(c, list(keys))
            if not links:
                return None
            others = {ln['rel'] for ln in links} | {ln['pep'] for ln in links}
            return links, _records(c, list(others))

        if cur is None:
            from screening.db_pool import db_pool
            with db_pool.get_connection() as conn:
                c = conn.cursor()
                try:
                    got = _run(c)
                finally:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
        else:
            got = _run(cur)
        if not got:
            return matches
        links, records = got
        for k, idx in keys.items():
            rel = _summaries(None, k, links, records, limit=_MAX_PER_HIT)
            if not rel:
                continue
            for i in idx:
                matches[i]['pep_relations'] = rel
                if any(r['other_is_pep'] for r in rel):
                    matches[i]['pep_related'] = True
    except Exception as e:
        logger.warning('[PEP-RELATIONS] annotate skipped: %s', e)
    return matches


def for_record(cur, row):
    """Every relative / associate of one listed record (match profile)."""
    try:
        if not row or not _table_ok(cur):
            return []
        sid = row.get('source_id')
        if not sid:
            return []
        key = (side_source(row.get('source')), str(sid))
        links = _links(cur, [key])
        if not links:
            return []
        others = {ln['rel'] for ln in links} | {ln['pep'] for ln in links}
        return _summaries(cur, key, links, _records(cur, list(others)))
    except Exception as e:
        logger.warning('[PEP-RELATIONS] profile lookup skipped: %s', e)
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return []


def explain_lines(m):
    """(en, ar) lines for the workflow explanation."""
    en, ar = [], []
    for r in (m or {}).get('pep_relations') or []:
        lab = TYPE_LABEL.get(r.get('type'), TYPE_LABEL['associate'])
        relship = (' — ' + r['relationship']) if r.get('relationship') else ''
        if r.get('role') == 'relative_of':
            if r.get('other_is_pep'):
                en.append(f"Related to PEP {r.get('other_name_latin') or r.get('other_name')} ({lab[0]}{relship}).")
                ar.append(f"مرتبط بشخص سياسي ممثل للمخاطر: {r.get('other_name')} ({lab[1]}{relship}).")
            else:
                en.append(f"Linked to {r.get('other_name_latin') or r.get('other_name')} ({lab[0]}{relship}).")
                ar.append(f"مرتبط بـ {r.get('other_name')} ({lab[1]}{relship}).")
        else:
            en.append(f"Has a listed {lab[0].lower()}: {r.get('other_name_latin') or r.get('other_name')}{relship}.")
            ar.append(f"له {lab[1]} مدرج: {r.get('other_name')}{relship}.")
        if len(en) >= 2:
            break
    return en, ar


# ----------------------------------------------------------------------------- manual links
def add_manual(conn, pep_row, related_row, relation_type, relationship, user_id, reason):
    """MLRO adds a relation between two listed records (audited by the caller's route)."""
    if relation_type not in RELATION_TYPES:
        raise ValueError('Invalid relation type.')
    if len((reason or '').strip()) < 15:
        raise ValueError('Please give the reason (at least 15 characters).')
    a = (side_source(pep_row.get('source')), str(pep_row.get('source_id') or ''))
    b = (side_source(related_row.get('source')), str(related_row.get('source_id') or ''))
    if not a[1] or not b[1] or a == b:
        raise ValueError('Both records must be different listed records.')
    key = f"manual:{a[0]}:{a[1]}>{b[0]}:{b[1]}:{relation_type}"
    cur = conn.cursor()
    cur.execute("""INSERT INTO screening_pep_relations
                     (relation_key, pep_source, pep_source_id, related_source, related_source_id,
                      relation_type, relationship, origin, created_by, reason)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'manual',%s,%s)
                   ON CONFLICT (relation_key) DO UPDATE SET is_active = TRUE, relationship = EXCLUDED.relationship,
                      reason = EXCLUDED.reason, created_by = EXCLUDED.created_by, updated_at = now()
                   RETURNING id""",
                (key, a[0], a[1], b[0], b[1], relation_type, (relationship or '')[:120], user_id, reason.strip()[:500]))
    rid = _val(cur.fetchone(), 'id', 0)
    return rid


def deactivate(conn, relation_id, user_id, reason):
    """MLRO removes a relation (kept, marked inactive; an OpenSanctions re-import does not
    revive a relation an MLRO removed)."""
    if len((reason or '').strip()) < 15:
        raise ValueError('Please give the reason (at least 15 characters).')
    cur = conn.cursor()
    cur.execute("""UPDATE screening_pep_relations SET is_active = FALSE, removed_by = %s, removed_reason = %s,
                          updated_at = now()
                    WHERE id = %s AND is_active RETURNING id""", (user_id, reason.strip()[:500], relation_id))
    return bool(cur.fetchone())
