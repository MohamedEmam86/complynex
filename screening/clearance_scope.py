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
P4-5 — a clearance covers the listed RECORDS that were reviewed, not the name.

When an analyst clears a hit ("not the person"), the whitelist entry of the
screened name remembers each cleared record: (kind, record id) plus a
fingerprint of what identifies that record (names, aliases, dates of birth,
nationalities, ID numbers, list type, legal status). On a later screening of
the same name:

  * a cleared record whose fingerprint is unchanged and that is still listed is
    not raised again — it is shown as "cleared earlier by X on <date>, record
    unchanged";
  * a cleared record whose content changed, that was delisted and re-listed,
    or that now agrees on an identifier (national ID / DOB / passport) comes
    back as a normal hit, with a note saying why;
  * any record that was not part of the clearance is a normal hit.

The fingerprint is order-insensitive: OpenSanctions re-orders names between
exports, which must not expire a clearance.

Entries without any recorded record (old name-only entries and manual
whitelist entries) cannot tell a new listing from an old one. Their behaviour
is set by screening_config 'whitelist_legacy_mode': 'review' (default) shows
the hits with a note to re-confirm; 'suppress' keeps the old behaviour.

Every function fails open towards SHOWING hits: an error never hides a hit.
"""
import hashlib
import json
import logging
import re

logger = logging.getLogger(__name__)

KIND_WATCHLIST = 'watchlist'
KIND_BLACKLIST = 'internal_blacklist'
KIND_PEP = 'internal_pep'
KINDS = (KIND_WATCHLIST, KIND_BLACKLIST, KIND_PEP)

LEGACY_REVIEW = 'review'
LEGACY_SUPPRESS = 'suppress'

# clearance state of a hit
ST_CLEARED = 'cleared'            # unchanged since it was cleared: not raised
ST_CHANGED = 'changed'            # record content changed since the clearance
ST_RELISTED = 'relisted'          # record was delisted after the clearance and is listed again
ST_IDENTIFIER = 'identifier'      # an identifier now agrees: never cleared silently
ST_NEW = 'new'                    # not part of the clearance
ST_LEGACY = 'legacy'              # name-only clearance, no record baseline
ST_OTHER = 'other_customer'       # the entry was made for another customer of the same name

_FIELDS = {
    KIND_WATCHLIST: ('full_name', 'original_name', 'aliases', 'full_name_arabic', 'aliases_arabic',
                     'date_of_birth', 'year_of_birth', 'nationality', 'countries',
                     'national_id_numbers', 'passport_numbers', 'list_type', 'source', 'entity_type',
                     'place_of_birth', 'gender', 'topics', 'properties', 'content_hash'),
    KIND_BLACKLIST: ('full_name', 'original_name', 'aliases', 'date_of_birth', 'nationality',
                     'national_id', 'passport_number', 'registration_number', 'category',
                     'legal_status', 'entity_type'),
    KIND_PEP: ('full_name', 'original_name', 'aliases', 'date_of_birth', 'nationality',
               'national_id', 'position', 'country', 'entity_type', 'passport_number',
               'registration_number', 'place_of_birth'),
}
_TABLE = {KIND_WATCHLIST: 'screening_watchlist', KIND_BLACKLIST: 'internal_blacklist',
          KIND_PEP: 'internal_pep'}


# --------------------------------------------------------------------------- pure helpers
def record_key(m):
    """(kind, record id) of a hit, or None. Internal-list hits carry the internal row id in
    entity_id; list hits carry the watchlist id in id."""
    if not isinstance(m, dict):
        return None
    src = str(m.get('source') or '').lower()
    if src.startswith('internal'):
        kind = KIND_PEP if 'pep' in src else KIND_BLACKLIST
        rid = m.get('entity_id')
    else:
        kind = KIND_WATCHLIST
        rid = m.get('id') if m.get('id') is not None else m.get('watchlist_id')
    try:
        return (kind, int(str(rid)))
    except (TypeError, ValueError):
        return None


def _norm(s):
    s = str(s).casefold()
    s = re.sub(r'[ً-ْـ]', '', s)                  # harakat, tatweel
    s = re.sub(r'[^\w\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _items(v):
    """Split a stored multi-value field (JSON list, ';' / '|' / newline separated) into a set."""
    if v is None:
        return set()
    if isinstance(v, (list, tuple, set)):
        vals = v
    else:
        s = str(v).strip()
        if not s:
            return set()
        vals = None
        if s[:1] in '[{':
            try:
                j = json.loads(s)
                vals = j if isinstance(j, list) else list(j.values()) if isinstance(j, dict) else [j]
            except (ValueError, TypeError):
                vals = None
        if vals is None:
            vals = re.split(r'[;|\n]', s)
    out = set()
    for x in vals:
        if isinstance(x, dict):
            x = x.get('name') or x.get('value') or json.dumps(x, sort_keys=True)
        n = _norm(x) if x is not None else ''
        if n:
            out.add(n)
    return out


def fingerprint(kind, row):
    """Order-insensitive hash of what identifies a listed record. Names of every field are
    pooled (a name moved from full_name to aliases is not a change)."""
    if not row:
        return None
    fields = _FIELDS.get(kind, _FIELDS[KIND_WATCHLIST])
    names = set()
    parts = []
    for f in fields:
        v = row.get(f) if hasattr(row, 'get') else None
        if f == 'properties':
            # only what defines the listing, not every enrichment field
            p = v
            if isinstance(p, str):
                try:
                    p = json.loads(p)
                except (ValueError, TypeError):
                    p = None
            p = p if isinstance(p, dict) else {}
            for k in ('datasets', 'jurisdiction'):
                parts.append('p.' + k + '=' + ','.join(sorted(_items(p.get(k)))))
            continue
        if f in ('full_name', 'original_name', 'aliases', 'full_name_arabic', 'aliases_arabic'):
            names |= _items(v)
        else:
            parts.append(f + '=' + ','.join(sorted(_items(v))))
    parts.append('names=' + ','.join(sorted(names)))
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:32]


def _is_active(kind, row):
    if not row:
        return False
    v = row.get('is_active')
    if v is None:
        return True
    try:
        return int(v) == 1
    except (TypeError, ValueError):
        return bool(v)


def _identifier_agrees(m):
    d = m.get('decision') if isinstance(m.get('decision'), dict) else {}
    return bool(d.get('identifier_match')) or d.get('identity') == 'id_match'


def entry_applies(entry, national_id=None, dob=None):
    """A name entry recorded for one person does not cover a different person of the same
    name: when both the entry and the screening carry a national ID (or a full DOB) and they
    differ, the entry is ignored."""
    if not entry:
        return False
    def _digits(x):
        return re.sub(r'\D', '', str(x or ''))
    e_id, q_id = _digits(entry.get('national_id')), _digits(national_id)
    if len(e_id) >= 8 and len(q_id) >= 8 and e_id != q_id:
        return False
    e_dob, q_dob = str(entry.get('date_of_birth') or '')[:10], str(dob or '')[:10]
    if len(e_dob) == 10 and len(q_dob) == 10 and e_dob != q_dob:
        return False
    return True


def same_customer(entry, customer_id=None, national_id=None, dob=None):
    """A name entry silently covers a record only for the customer it was made for: the same
    customer id, or an identifier of this screening (national ID or full DOB) that agrees
    with the one recorded on the entry. Otherwise the hit is shown with a re-confirm note."""
    if not entry:
        return False
    e_cid = entry.get('customer_id')
    if e_cid not in (None, '') and customer_id not in (None, '') and str(e_cid) == str(customer_id):
        return True
    e_id = re.sub(r'\D', '', str(entry.get('national_id') or ''))
    q_id = re.sub(r'\D', '', str(national_id or ''))
    if len(e_id) >= 8 and e_id == q_id:
        return True
    e_dob, q_dob = str(entry.get('date_of_birth') or '')[:10], str(dob or '')[:10]
    if len(e_dob) == 10 and e_dob == q_dob and e_dob not in ('None',):
        return True
    return False


def classify(matches, entry, links, current, mode=LEGACY_REVIEW, who=None):
    """Pure core. (kept, cleared): kept = hits still raised (each annotated with
    'clearance' when the entry has something to say about it), cleared = hits not raised
    because the same record was cleared and is unchanged.

    links:   {(kind, id): link dict with fingerprint, is_active, cleared_at, cleared_by_name}
    current: {(kind, id): (fingerprint, active)} of the records as they are now
    """
    if not entry:
        return list(matches or []), []
    base = {'whitelist_id': entry.get('id'), 'by': entry.get('approved_by_name') or entry.get('requested_by_name'),
            'at': str(entry.get('approval_date') or entry.get('added_at') or '')[:16]}
    kept, cleared = [], []
    legacy = not links
    who = who if isinstance(who, dict) else None
    same = True if who is None else same_customer(entry, **who)
    for m in (matches or []):
        if not isinstance(m, dict):
            kept.append(m)
            continue
        if legacy:
            m['clearance'] = dict(base, state=ST_LEGACY)
            kept.append(m)
            continue
        key = record_key(m)
        link = links.get(key) if key else None
        if not link:
            m['clearance'] = dict(base, state=ST_NEW)
            kept.append(m)
            continue
        info = dict(base, by=link.get('cleared_by_name') or base['by'],
                    at=str(link.get('cleared_at') or base['at'])[:16])
        fp_now, active_now = current.get(key, (None, False))
        if _identifier_agrees(m):
            m['clearance'] = dict(info, state=ST_IDENTIFIER)
            kept.append(m)
        elif not link.get('is_active', True):
            m['clearance'] = dict(info, state=ST_RELISTED)
            kept.append(m)
        elif not fp_now or fp_now != link.get('fingerprint'):
            m['clearance'] = dict(info, state=ST_CHANGED)
            kept.append(m)
        elif not active_now:
            kept.append(m)          # cannot happen for a live hit; never hide on doubt
        elif not same:
            m['clearance'] = dict(info, state=ST_OTHER)
            kept.append(m)
        else:
            m['clearance'] = dict(info, state=ST_CLEARED)
            cleared.append(m)
    return kept, cleared


# --------------------------------------------------------------------------- DB helpers
def _raw(conn):
    return getattr(conn, '_conn', conn)


def _rows(conn, sql, params=()):
    import psycopg2.extras
    cur = _raw(conn).cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()] if cur.description else []
    finally:
        cur.close()


def legacy_mode(conn):
    try:
        r = _rows(conn, "SELECT config_value FROM screening_config WHERE config_key = 'whitelist_legacy_mode'")
        v = (r[0]['config_value'] if r else '') or ''
        return LEGACY_SUPPRESS if v.strip().lower() == LEGACY_SUPPRESS else LEGACY_REVIEW
    except Exception:
        return LEGACY_REVIEW


def name_keys(normalized_name, raw_name=None):
    """Keys a whitelist entry of this name may be stored under. Entries were written with
    upper().strip() of the raw name (queue clearances) or the engine's own normalisation; the
    engine looks up its normalised form, so both are tried."""
    keys = []
    for k in (normalized_name, (raw_name or '').upper().strip() if raw_name else None,
              re.sub(r'\s+', ' ', (raw_name or '').upper()).strip() if raw_name else None):
        if k and k not in keys:
            keys.append(k)
    return keys


def find_entry(conn, normalized_name, raw_name=None):
    """The Active, in-review whitelist entry of a screened name (or None). When several keys
    match, an entry with recorded records wins, then the most recent."""
    rows = _rows(conn, """
        SELECT w.id, w.name, w.scope, w.national_id, w.date_of_birth, w.approval_date, w.added_at,
               w.customer_id,
               TRIM(COALESCE(a.first_name,'') || ' ' || COALESCE(a.last_name,'')) AS approved_by_name,
               TRIM(COALESCE(r.first_name,'') || ' ' || COALESCE(r.last_name,'')) AS requested_by_name
          FROM screening_whitelist w
          LEFT JOIN users a ON a.id = w.approved_by
          LEFT JOIN users r ON r.id = COALESCE(w.requested_by, w.added_by)
         WHERE w.normalized_name = ANY(%s) AND w.status = 'Active'
           AND COALESCE(w.review_date, '') >= to_char(CURRENT_DATE, 'YYYY-MM-DD')
         ORDER BY (w.scope = 'match_set') DESC, w.id DESC
         LIMIT 1""", (name_keys(normalized_name, raw_name),))
    return rows[0] if rows else None


def entry_links(conn, whitelist_id):
    rows = _rows(conn, """
        SELECT m.entity_kind, m.entity_id, m.fingerprint, m.is_active, m.cleared_at,
               TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS cleared_by_name
          FROM screening_whitelist_matches m LEFT JOIN users u ON u.id = m.cleared_by
         WHERE m.whitelist_id = %s""", (whitelist_id,))
    return {(r['entity_kind'] or KIND_WATCHLIST, int(r['entity_id'])): r for r in rows}


def current_state(conn, keys):
    """{(kind, id): (fingerprint, active)} for the given record keys — one query per kind."""
    out = {}
    by_kind = {}
    for k in keys or ():
        if k and k[0] in _TABLE:
            by_kind.setdefault(k[0], set()).add(int(k[1]))
    for kind, ids in by_kind.items():
        cols = sorted(set(_FIELDS[kind]) | {'id', 'is_active'})
        avail = {r['column_name'] for r in _rows(
            conn, "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (_TABLE[kind],))}
        cols = [c for c in cols if c in avail]
        for r in _rows(conn, f"SELECT {', '.join(cols)} FROM {_TABLE[kind]} WHERE id = ANY(%s)", (sorted(ids),)):
            out[(kind, int(r['id']))] = (fingerprint(kind, r), _is_active(kind, r))
    return out


def lookup(conn, normalized_name, national_id=None, dob=None, raw_name=None, customer_id=None):
    """Engine hook, before the search. The clearance context of a screened name, or None:
    {'entry', 'links', 'summary', 'suppress_all'}. suppress_all is True only for a legacy
    (name-only) entry in 'suppress' mode, the old behaviour."""
    try:
        entry = find_entry(conn, normalized_name, raw_name)
        if not entry or not entry_applies(entry, national_id, dob):
            return None
        links = entry_links(conn, entry['id'])
        summary = {'whitelist_id': entry['id'], 'records': len(links),
                   'by': entry.get('approved_by_name') or entry.get('requested_by_name'),
                   'at': str(entry.get('approval_date') or entry.get('added_at') or '')[:16]}
        suppress = False
        if not links:
            summary['legacy'] = legacy_mode(conn)
            suppress = summary['legacy'] == LEGACY_SUPPRESS
        return {'entry': entry, 'links': links, 'summary': summary, 'suppress_all': suppress,
                'who': {'customer_id': customer_id, 'national_id': national_id, 'dob': dob}}
    except Exception as e:
        logger.warning('[CLEARANCE-SCOPE] lookup failed, no clearance applied: %s', e)
        try:
            _raw(conn).rollback()
        except Exception:
            pass
        return None


def filter_hits(conn, matches, ctx):
    """Engine hook, after scoring. (kept, cleared). Any error keeps every hit."""
    if not ctx:
        return list(matches or []), []
    try:
        links = ctx.get('links') or {}
        keys = [record_key(m) for m in (matches or [])]
        current = current_state(conn, [k for k in keys if k and k in links]) if links else {}
        return classify(matches, ctx['entry'], links, current, who=ctx.get('who'))
    except Exception as e:
        logger.warning('[CLEARANCE-SCOPE] failed, all hits kept: %s', e)
        try:
            _raw(conn).rollback()
        except Exception:
            pass
        for m in (matches or []):
            if isinstance(m, dict):
                m.pop('clearance', None)
        return list(matches or []), []


def stamp(conn, matches):
    """Engine hook: record each hit's record fingerprint AS IT WAS AT SCREENING TIME
    (m['record_fp']), so a later clearance covers exactly what the analyst reviewed."""
    try:
        keys = [record_key(m) for m in (matches or []) if isinstance(m, dict)]
        state = current_state(conn, [k for k in keys if k])
        for m in (matches or []):
            k = record_key(m) if isinstance(m, dict) else None
            fp = state.get(k, (None, False))[0] if k else None
            if fp:
                m['record_fp'] = fp
    except Exception as e:
        logger.warning('[CLEARANCE-SCOPE] fingerprints not stamped: %s', e)
        try:
            _raw(conn).rollback()
        except Exception:
            pass
    return matches


def _ts(v):
    s = str(v or '').replace('T', ' ')
    return s[:19] if len(s) >= 19 else ''


def updated_at(conn, keys):
    """{(kind, id): 'YYYY-MM-DD HH:MM:SS'} last change time of the given records ('' if unknown)."""
    out = {}
    by_kind = {}
    for k in keys or ():
        if k and k[0] in _TABLE:
            by_kind.setdefault(k[0], set()).add(int(k[1]))
    for kind, ids in by_kind.items():
        avail = {r['column_name'] for r in _rows(
            conn, "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (_TABLE[kind],))}
        cols = [c for c in ('updated_at', 'modified_date', 'last_updated') if c in avail]
        if not cols:
            continue
        for r in _rows(conn, f"SELECT id, {', '.join(cols)} FROM {_TABLE[kind]} WHERE id = ANY(%s)", (sorted(ids),)):
            out[(kind, int(r['id']))] = max((_ts(r.get(c)) for c in cols), default='')
    return out


def record_links(conn, whitelist_id, matches, cleared_by=None, screened_at=None, skipped=None):
    """Remember the records a clearance covered (called when the clearance is made). Re-clearing
    a record refreshes its fingerprint and re-activates it. Returns the number recorded.

    Only records still as they were when the analyst screened them are covered: a hit carrying
    its screening-time fingerprint (record_fp) is linked only if the record is unchanged; for
    older results without one, a record updated after screened_at is not linked. Records left
    out stay hits on the next screening; they are appended to `skipped` (list) when given."""
    keyed = [(record_key(m), m) for m in (matches or []) if isinstance(m, dict)]
    keyed = [(k, m) for k, m in keyed if k]
    if not whitelist_id or not keyed:
        return 0
    state = current_state(conn, [k for k, _ in keyed])
    need_ts = [k for k, m in keyed if not m.get('record_fp')]
    upd = updated_at(conn, need_ts) if (need_ts and _ts(screened_at)) else {}
    cur = _raw(conn).cursor()
    n = 0
    try:
        for (kind, rid), m in keyed:
            fp = state.get((kind, rid), (None, False))[0]
            if not fp:
                continue
            then = m.get('record_fp')
            changed = (then and then != fp) or (
                not then and _ts(screened_at) and upd.get((kind, rid), '') > _ts(screened_at))
            if changed:
                if isinstance(skipped, list):
                    skipped.append({'kind': kind, 'id': rid, 'reason': 'changed_since_screening',
                                    'name': m.get('full_name') or m.get('matched_name') or m.get('watchlist_name_ar')})
                continue
            cur.execute("""
                INSERT INTO screening_whitelist_matches
                    (whitelist_id, entity_kind, entity_id, entity_name, entity_source, match_score,
                     fingerprint, cleared_by, cleared_at, is_active)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),true)
                ON CONFLICT (whitelist_id, entity_kind, entity_id) DO UPDATE
                   SET fingerprint = EXCLUDED.fingerprint, match_score = EXCLUDED.match_score,
                       cleared_by = EXCLUDED.cleared_by, cleared_at = NOW(), is_active = true,
                       deactivated_at = NULL, deactivated_reason = NULL""",
                        (whitelist_id, kind, rid,
                         m.get('full_name') or m.get('matched_name') or m.get('watchlist_name_ar'),
                         m.get('source') or m.get('list_source'), m.get('match_score'), fp, cleared_by))
            n += 1
        if n:
            cur.execute("""UPDATE screening_whitelist
                              SET scope = 'match_set',
                                  cleared_match_count = (SELECT count(*) FROM screening_whitelist_matches
                                                          WHERE whitelist_id = %s AND is_active)
                            WHERE id = %s""", (whitelist_id, whitelist_id))
    finally:
        cur.close()
    return n


def expire_delisted(conn):
    """Mark cleared records that are no longer listed (is_active = 0). If such a record is
    listed again later, its hit comes back ('relisted'). Run after list updates. Returns count."""
    cur = _raw(conn).cursor()
    total = 0
    try:
        for kind, table in _TABLE.items():
            cur.execute(f"""
                UPDATE screening_whitelist_matches m
                   SET is_active = false, deactivated_at = NOW(), deactivated_reason = 'delisted'
                  FROM {table} t
                 WHERE m.is_active AND m.entity_kind = %s AND t.id = m.entity_id
                   AND COALESCE(t.is_active, 1) = 0""", (kind,))
            total += cur.rowcount or 0
    finally:
        cur.close()
    return total


def remember_identity(conn, whitelist_id, inputs):
    """Store the identifiers the clearance was made with (never overwrites existing ones)."""
    if not whitelist_id or not isinstance(inputs, dict):
        return
    nid = (inputs.get('national_id') or '').strip() if isinstance(inputs.get('national_id'), str) else None
    dob = str(inputs.get('dob') or '')[:10] or None
    nat = inputs.get('nationality') or None
    if not (nid or dob or nat):
        return
    cur = _raw(conn).cursor()
    try:
        cur.execute("""UPDATE screening_whitelist
                          SET national_id = COALESCE(NULLIF(national_id, ''), %s),
                              date_of_birth = COALESCE(NULLIF(date_of_birth, ''), %s),
                              nationality = COALESCE(NULLIF(nationality, ''), %s)
                        WHERE id = %s""", (nid, dob if dob and dob != 'None' else None, nat, whitelist_id))
    finally:
        cur.close()
