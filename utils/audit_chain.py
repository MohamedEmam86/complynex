# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Audit-trail integrity (P6-5).

audit_logs is hash-chained and append-only in the database (triggers since
20261029/20261030). This module checks it:
  * chain   : audit_logs_verify() recomputes every row's hash in id order;
  * anchors : audit_anchors are hash-chained checkpoints (last id, its hash, row
              count). Each anchor must still match the trail: the row it names
              has the same hash and there are exactly as many rows up to it.
              A trail rebuilt or cut by a database superuser (who can bypass
              triggers) no longer matches the anchors written before the change.
Works on a plain psycopg2 connection (scripts) or the app's get_db() wrapper.
"""


def _rows(db, sql, args=()):
    cur = db.cursor()
    cur.execute(sql, args)
    raw = getattr(cur, '_cursor', cur)          # the app's DictCursor wraps a psycopg2 cursor
    cols = [d[0] for d in raw.description] if raw.description else []
    out = []
    for r in cur.fetchall():
        out.append(dict(r) if hasattr(r, 'keys') else dict(zip(cols, r)))
    return out


def check(db, anchor_limit=200):
    """{'ok', 'chain': {...}, 'anchors': {...}, 'mismatches': [...]} — read only."""
    res = {'ok': True, 'chain': {}, 'anchors': {}, 'mismatches': [], 'error': None}
    try:
        ch = _rows(db, "SELECT broken_id, checked FROM audit_logs_verify()")[0]
        last = _rows(db, "SELECT id, row_hash FROM audit_logs ORDER BY id DESC LIMIT 1")
        res['chain'] = {'checked': int(ch['checked'] or 0), 'broken_id': ch['broken_id'],
                        'last_id': last[0]['id'] if last else None,
                        'last_hash': last[0]['row_hash'] if last else None}
        if ch['broken_id'] is not None:
            res['ok'] = False
    except Exception as e:
        res['ok'] = False
        res['error'] = f'chain check failed: {e}'
        _rollback(db)
        return res
    try:
        av = _rows(db, "SELECT checked, first_bad_id FROM audit_anchors_verify()")[0]
        res['anchors'] = {'checked': int(av['checked'] or 0), 'broken_id': av['first_bad_id']}
        if av['first_bad_id'] is not None:
            res['ok'] = False
        rows = _rows(db, """SELECT a.id, a.taken_at, a.last_id, a.last_hash, a.row_count,
                                   l.row_hash AS now_hash,
                                   (SELECT count(*) FROM audit_logs x WHERE x.id <= a.last_id) AS now_count
                              FROM (SELECT * FROM audit_anchors ORDER BY id DESC LIMIT %s) a
                              LEFT JOIN audit_logs l ON l.id = a.last_id
                             ORDER BY a.id DESC""", (anchor_limit,))
        for r in rows:
            if r['last_id'] is None:
                continue
            if r['now_hash'] != r['last_hash'] or int(r['now_count'] or 0) != int(r['row_count'] or 0):
                res['mismatches'].append({'anchor_id': r['id'], 'taken_at': r['taken_at'], 'last_id': r['last_id'],
                                          'expected_count': r['row_count'], 'now_count': r['now_count'],
                                          'hash_matches': r['now_hash'] == r['last_hash']})
        if res['mismatches']:
            res['ok'] = False
    except Exception as e:
        # anchors table not migrated yet: chain result still stands
        res['anchors'] = {'checked': 0, 'broken_id': None, 'unavailable': str(e)[:200]}
        _rollback(db)
    return res


def take_anchor(db, user_id=None, note=None):
    """Verify, then write an anchor for the current end of the chain. Returns (anchor_id, result)."""
    res = check(db)
    if res.get('error'):
        return None, res                          # the check itself failed: no checkpoint
    ch = res.get('chain') or {}
    cur = db.cursor()
    cur.execute("""INSERT INTO audit_anchors (last_id, last_hash, row_count, chain_ok, first_bad_id, taken_by, note)
                   VALUES (%s, %s, (SELECT count(*) FROM audit_logs WHERE id <= %s), %s, %s, %s, %s)
                   RETURNING id, anchor_hash""",
                (ch.get('last_id'), ch.get('last_hash'), ch.get('last_id') or 0, bool(res['ok']),
                 ch.get('broken_id'), user_id, (note or '')[:500] or None))
    row = cur.fetchone()
    db.commit()
    aid = row['id'] if hasattr(row, 'keys') else row[0]
    return aid, res


def recent_anchors(db, limit=30):
    return _rows(db, """SELECT a.id, a.taken_at, a.last_id, a.row_count, a.chain_ok, a.first_bad_id, a.note,
                               left(a.anchor_hash, 16) AS anchor_short,
                               TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS taken_by_name
                          FROM audit_anchors a LEFT JOIN users u ON u.id = a.taken_by
                         ORDER BY a.id DESC LIMIT %s""", (limit,))


def _rollback(db):
    try:
        db.rollback()
    except Exception:
        pass
