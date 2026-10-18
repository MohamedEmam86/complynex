# =============================================================================
# ComplyNex — ongoing sanctions screening (match-pair model)
#
# WHY THE WHITELIST HAD TO CHANGE FIRST
# A whitelist entry used to mean "never screen this name again": the engine
# returned WHITE_LISTED and stopped before matching. Re-screening such an entry
# could only ever reproduce the same suppression, so ongoing screening was
# impossible to build on top of it.
#
# An entry now records WHICH listed entity was cleared. A re-screen then has
# three meaningful outcomes instead of one:
#
#   every current match is in the cleared set -> silent. Already adjudicated.
#   a match appears OUTSIDE the cleared set    -> ALERT on that one only.
#   a cleared listing CHANGED                  -> ALERT for re-review.
#   a cleared listing was DE-LISTED            -> informational.
#
# The clearance covers a SET. Screening "Mohamed Emam" returns 18 matches; the
# analyst reviews them and accepts that none is this customer. That is one
# decision over 18 listings, not 18 decisions. If a 19th appears later, that is
# new evidence nobody has seen — which is the entire purpose of re-screening.
#
# The middle case is the entire point. A name cleared in January can become a
# genuine match in June because the person was listed, not because the name
# changed — and a name-level whitelist would silence exactly that.
# =============================================================================
import hashlib
from datetime import datetime, timedelta

from database.db import get_db

FREQUENCIES = {
    'daily':     timedelta(days=1),
    'weekly':    timedelta(days=7),
    'monthly':   timedelta(days=30),
    'quarterly': timedelta(days=91),
    'yearly':    timedelta(days=365),
}


def fingerprint(entity):
    """Stable hash of the fields that, if they change, invalidate a clearance.

    Deliberately narrow: a listing's description or last_updated timestamp
    churning should not force a re-review, but a new alias or a new sanctions
    programme should.
    """
    if not entity:
        return None
    parts = [str(entity.get(k) or '') for k in
             ('full_name', 'full_name_arabic', 'aliases', 'date_of_birth',
              'nationality', 'source', 'list_type', 'risk_level')]
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:32]


def get_entity(entity_id):
    r = get_db().execute("SELECT * FROM screening_watchlist WHERE id = %s",
                         (entity_id,)).fetchone()
    return dict(r) if r else None


def frequency_for(risk_band=None):
    db = get_db()
    if risk_band:
        r = db.execute("SELECT frequency FROM ongoing_screening_config "
                       "WHERE risk_band = %s AND is_active", (risk_band,)).fetchone()
        if r:
            return dict(r)['frequency']
    r = db.execute("SELECT frequency FROM ongoing_screening_config "
                   "WHERE scope_name = 'default'").fetchone()
    return dict(r)['frequency'] if r else 'monthly'


def schedule_next(whitelist_id, frequency=None, from_time=None):
    db = get_db()
    if not frequency:
        r = db.execute("SELECT screening_frequency FROM screening_whitelist WHERE id=%s",
                       (whitelist_id,)).fetchone()
        frequency = (dict(r)['screening_frequency'] if r else None) or 'monthly'
    if frequency == 'manual':
        db.execute("UPDATE screening_whitelist SET next_screening_at=NULL WHERE id=%s",
                   (whitelist_id,))
        db.commit()
        return None
    nxt = (from_time or datetime.now()) + FREQUENCIES.get(frequency, FREQUENCIES['monthly'])
    db.execute("UPDATE screening_whitelist SET next_screening_at=%s WHERE id=%s",
               (nxt, whitelist_id))
    db.commit()
    return nxt


def set_fingerprint(entity_ids):
    """Hash of the cleared set, so a changed set is one comparison."""
    ids = sorted(int(x) for x in entity_ids if x)
    return hashlib.sha256(','.join(str(i) for i in ids).encode()).hexdigest()[:32]


def whitelist_from_false_positive(name, matches, reason, cleared_by,
                                  customer_id=None, alert_id=None,
                                  risk_band=None, normalized_name=None):
    """Clear a name against its whole current match set.

    `matches` is the list the screening run actually returned — each item
    needing at least an id, ideally name/source/score. All of them are recorded
    as cleared. Anything appearing later that is not in this set will alert.
    """
    db = get_db()
    freq = frequency_for(risk_band)
    norm = normalized_name or (name or '').upper().strip()

    rows = []
    for m in (matches or []):
        eid = m.get('id') or m.get('entity_id') or m.get('watchlist_id')
        if not eid:
            continue
        ent = get_entity(eid)
        rows.append((int(eid),
                     (ent or {}).get('full_name') or m.get('matched_name') or m.get('name'),
                     (ent or {}).get('source') or m.get('list_source') or m.get('source'),
                     m.get('match_score') or m.get('score'),
                     fingerprint(ent)))

    wl = db.execute("""INSERT INTO screening_whitelist
            (name, normalized_name, reason, added_by, added_at, status,
             scope, screening_frequency, last_screened_at, next_screening_at,
             source_alert_id, customer_id, cleared_match_count, match_set_fingerprint)
          VALUES (%s,%s,%s,%s,to_char(NOW(),'YYYY-MM-DD HH24:MI:SS'),'Active',
                  'match_set',%s,NOW(),NOW() + %s,%s,%s,%s,%s)
          RETURNING id""",
        (name, norm, reason, cleared_by, freq,
         FREQUENCIES.get(freq, FREQUENCIES['monthly']),
         alert_id, customer_id, len(rows),
         set_fingerprint([r[0] for r in rows]))).fetchone()
    wid = dict(wl)['id']

    for eid, ename, esrc, score, fp in rows:
        db.execute("""INSERT INTO screening_whitelist_matches
                        (whitelist_id, entity_id, entity_name, entity_source,
                         match_score, fingerprint)
                      VALUES (%s,%s,%s,%s,%s,%s)
                      ON CONFLICT (whitelist_id, entity_id) DO NOTHING""",
                   (wid, eid, ename, esrc, score, fp))
    db.commit()
    return wid


def cleared_matches(whitelist_id):
    return [dict(r) for r in get_db().execute(
        "SELECT * FROM screening_whitelist_matches WHERE whitelist_id=%s AND is_active "
        "ORDER BY match_score DESC NULLS LAST", (whitelist_id,)).fetchall()]


def due_for_screening(limit=500, include_all=False, include_legacy=False):
    """Entries due for a re-screen.

    Legacy name-scoped entries (cleared before the entity was recorded) are
    EXCLUDED by default. They have no cleared-entity baseline, so every match
    they produce looks 'new' and a single run would flood the queue with
    findings that are really just un-adjudicated history. They need a one-off
    re-adjudication pass, not to be swept into routine monitoring.
    """
    q = """SELECT * FROM screening_whitelist
           WHERE status = 'Active'
             AND screening_frequency <> 'manual' """
    if not include_legacy:
        q += " AND scope = 'match_set' "
    if not include_all:
        q += " AND (next_screening_at IS NULL OR next_screening_at <= NOW()) "
    q += " ORDER BY next_screening_at NULLS FIRST LIMIT %s"
    return [dict(r) for r in get_db().execute(q, (limit,)).fetchall()]


def run(engine=None, run_type='scheduled', triggered_by=None, limit=500,
        include_all=False, include_legacy=False):
    """Re-screen every whitelisted name that is due.

    `engine` is injected so this can be exercised in tests without loading the
    full ML stack. In production the caller passes screening.routes.get_engine().
    """
    db = get_db()
    run_row = db.execute("""INSERT INTO ongoing_screening_runs (run_type, triggered_by)
                            VALUES (%s,%s) RETURNING id""",
                         (run_type, triggered_by)).fetchone()
    run_id = dict(run_row)['id']
    db.commit()

    stats = dict(names=0, unchanged=0, new_matches=0, changed=0, delisted=0, errors=0)

    for wl in due_for_screening(limit=limit, include_all=include_all,
                                include_legacy=include_legacy):
        stats['names'] += 1
        try:
            cleared = cleared_matches(wl['id'])
            cleared_ids = {c['entity_id'] for c in cleared}

            # 1. has anything in the cleared SET changed or gone away?
            for c in cleared:
                ent = get_entity(c['entity_id'])
                if ent is None:
                    _finding(run_id, wl, 'delisted', None, None, c['fingerprint'], None)
                    stats['delisted'] += 1
                    continue
                fp = fingerprint(ent)
                if c['fingerprint'] and fp != c['fingerprint']:
                    _finding(run_id, wl, 'entity_changed', ent, None, c['fingerprint'], fp)
                    stats['changed'] += 1

            # 2. has anything appeared OUTSIDE the cleared set?
            if engine is not None:
                res = engine.screen_person(name=wl['name'])
                found_new = False
                for m in (res.get('matches') or []):
                    mid = m.get('id') or m.get('entity_id') or m.get('watchlist_id')
                    score = m.get('match_score') or m.get('score') or 0
                    if mid and int(mid) not in cleared_ids and score >= 85:
                        _finding(run_id, wl, 'new_entity',
                                 {'id': mid,
                                  'full_name': m.get('matched_name') or m.get('name'),
                                  'source': m.get('list_source') or m.get('source')},
                                 score, None, None)
                        stats['new_matches'] += 1
                        found_new = True
                if not found_new:
                    stats['unchanged'] += 1
            else:
                stats['unchanged'] += 1

            db.execute("UPDATE screening_whitelist SET last_screened_at=NOW() WHERE id=%s",
                       (wl['id'],))
            schedule_next(wl['id'], wl.get('screening_frequency'))
        except Exception:
            stats['errors'] += 1

    db.execute("""UPDATE ongoing_screening_runs
                     SET finished_at=NOW(), names_screened=%s, unchanged=%s,
                         new_matches=%s, changed_listings=%s, delisted=%s, errors=%s
                   WHERE id=%s""",
               (stats['names'], stats['unchanged'], stats['new_matches'],
                stats['changed'], stats['delisted'], stats['errors'], run_id))
    db.commit()
    return run_id, stats


def _finding(run_id, wl, kind, entity, score, old_fp, new_fp):
    get_db().execute("""INSERT INTO ongoing_screening_findings
            (run_id, whitelist_id, screened_name, finding_type, entity_id,
             entity_name, entity_source, match_score, old_fingerprint, new_fingerprint)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (run_id, wl['id'], wl['name'], kind,
         (entity or {}).get('id'), (entity or {}).get('full_name'),
         (entity or {}).get('source'), score, old_fp, new_fp))
    get_db().commit()


def open_findings(limit=200):
    return [dict(r) for r in get_db().execute(
        """SELECT f.*, r.started_at AS run_started
           FROM ongoing_screening_findings f
           JOIN ongoing_screening_runs r ON r.id = f.run_id
           WHERE f.status = 'open'
           ORDER BY f.created_at DESC LIMIT %s""", (limit,)).fetchall()]


def recent_runs(limit=20):
    return [dict(r) for r in get_db().execute(
        "SELECT * FROM ongoing_screening_runs ORDER BY started_at DESC LIMIT %s",
        (limit,)).fetchall()]
