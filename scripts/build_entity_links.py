#!/usr/bin/env python3
"""
P2-6 / G5 — link records of the same person or entity across lists.

Rows are never merged or changed: this script groups watchlist ids into
clusters (screening_entity_clusters / screening_entity_links). Never on a name
alone. A link needs one of:

  os_id                 the same OpenSanctions entity id (opensanctions, opensanctions_pep, un)
  os_referent           an OpenSanctions record whose referent is an OFAC SDN uid
  linked_internal       EMLCU record already tied to the Public Prosecution order by full national ID
  official_id           the same national / official ID number (8+ characters), same kind of entity,
                        and no contradiction (birth years more than 1 apart, or different nationalities)
  passport              the same passport number + the same nationality or birth year
  name_dob_nationality  the same full name (all elements, 3 or more), the same full date of birth (not 1 Jan)
                        and a shared nationality / country; persons only; small groups only

The official record leads the cluster (EMLCU, PMA, internal orders, UN, OFAC,
UK, EU before OpenSanctions). An MLRO "unlink" (screening_entity_unlinks) is
respected by every rebuild.

  build_entity_links.py              dry run: counts only, writes nothing
  build_entity_links.py --apply      full rebuild of the link tables (one transaction)
"""
import argparse
import collections
import io
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

SOURCE_RANK = {'emlcu': 0, 'pma_ps': 1, 'internal_blacklist': 2, 'internal_pep': 3, 'un': 4,
               'ofac': 5, 'hmt': 6, 'eu': 7, 'opensanctions': 8, 'opensanctions_pep': 9}
STRONG = ('os_id', 'os_referent', 'linked_internal', 'official_id')
MAX_CLUSTER = 50          # a group bigger than this is not one person
MAX_NAME_CLUSTER = 12     # name + DOB + nationality may only join small groups
MAX_ID_GROUP = 8          # one ID number on more records than this is a placeholder, not an ID
LOCK_KEY = 'cx_entity_links_build'
# the watchlist copy of an internal-list row (scripts/sync_internal_to_watchlist.py): its own
# source_id when it has the list prefix, else prefix + md5 of the name
IBL_SID = ("CASE WHEN b.source_id LIKE 'IBL-%%' THEN b.source_id "
           "ELSE 'IBL-' || upper(left(md5(lower(btrim(b.full_name))), 12)) END")


def rank(src):
    return SOURCE_RANK.get(str(src or '').lower(), 10)


def as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x not in (None, '')]
    s = str(v).strip()
    if not s:
        return []
    if s.startswith('['):
        try:
            return [str(x) for x in json.loads(s) if x not in (None, '')]
        except Exception:
            pass
    return [p.strip() for p in re.split(r'[;|]', s) if p.strip()]


def norm_id(x):
    s = re.sub(r'[^0-9A-Za-z]', '', str(x or '')).upper()
    if len(s) < 8 or len(set(s)) < 3:          # too short, or 00000000-style placeholders
        return None
    return s


def norm_passport(x):
    s = re.sub(r'[^0-9A-Za-z]', '', str(x or '')).upper()
    return s if len(s) >= 6 and len(set(s)) >= 3 else None


_DATE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})')


def full_dates(v):
    out = set()
    for p in as_list(v):
        m = _DATE.match(p.strip())
        if m and not (m.group(2) == '01' and m.group(3) == '01') and m.group(2) != '00':
            out.add(m.group(0))
    return out


def years(v):
    return {int(y) for p in as_list(v) for y in re.findall(r'\b(1[89]\d{2}|20\d{2})\b', p)}


def kind(entity_type):
    t = str(entity_type or '').upper()
    if t.startswith(('IND', 'PER')) or t in ('', 'NATURAL', 'PERSON'):
        return 'P'
    return 'E'


def connect():
    import psycopg2
    from config import Config
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    with conn.cursor() as c:
        c.execute("SET statement_timeout = '20min'")
    return conn


def tables_exist(cur):
    cur.execute("SELECT to_regclass('screening_entity_links') IS NOT NULL")
    return cur.fetchone()[0]


def build(conn, log=print):
    """Return (clusters, stats). clusters: list of {lead, members: {wid: (basis, linked_to, conf)}, ...}.
    Memory: records get a dense index; union-find lives in arrays; name keys are hashed."""
    from array import array
    from screening.match_intel import tokens
    from screening.country_codes import to_iso2
    t0 = time.time()
    cur = conn.cursor()
    stats = collections.Counter()
    idx, wids, src_rank = {}, array('i'), array('b')
    parent, size, via_b, via_o = array('i'), array('i'), array('b'), array('i')
    BASES = ['lead'] + list(STRONG) + ['passport', 'name_dob_nationality']
    BCODE = {b: i for i, b in enumerate(BASES)}

    def node(wid, source):
        i = idx.get(wid)
        if i is None:
            i = idx[wid] = len(wids)
            wids.append(wid)
            src_rank.append(rank(source))
            parent.append(i)
            size.append(1)
            via_b.append(-1)
            via_o.append(-1)
        return i

    def find(i):
        r = i
        while parent[r] != r:
            r = parent[r]
        while parent[i] != r:
            parent[i], i = r, parent[i]
        return r

    # unlinks first: pairs that must never be joined again
    forbid = collections.defaultdict(set)
    cur.execute("SELECT to_regclass('screening_entity_unlinks') IS NOT NULL")
    if cur.fetchone()[0]:
        cur.execute("SELECT watchlist_id, other_ids FROM screening_entity_unlinks WHERE revoked_at IS NULL")
        for wid, others in cur.fetchall():
            try:
                for o in json.loads(others or '[]'):
                    forbid[int(wid)].add(int(o))
                    forbid[int(o)].add(int(wid))
            except Exception:
                pass

    def link(a, sa, b, sb, basis):
        stats['edges_' + basis] += 1
        if a == b:
            return
        if b in forbid.get(a, ()):
            stats['edges_unlinked_by_mlro'] += 1
            return
        ia, ib = node(a, sa), node(b, sb)
        ra, rb = find(ia), find(ib)
        if ra == rb:
            return
        limit = MAX_NAME_CLUSTER if basis == 'name_dob_nationality' else MAX_CLUSTER
        if size[ra] + size[rb] > limit:
            stats['edges_refused_size_' + basis] += 1
            return
        if size[ra] < size[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        size[ra] += size[rb]
        code = BCODE[basis]
        if via_b[ib] < 0:
            via_b[ib], via_o[ib] = code, ia
        if via_b[ia] < 0:
            via_b[ia], via_o[ia] = code, ib
        stats['edges_used_' + basis] += 1

    # 1. same OpenSanctions entity id on several sources
    cur.execute("""SELECT array_agg(id ORDER BY id), array_agg(source ORDER BY id)
                   FROM screening_watchlist WHERE is_active = 1 AND source_id LIKE 'OS-%%'
                   GROUP BY source_id HAVING count(*) > 1""")
    for ids, srcs in cur:
        for w, s in zip(ids[1:], srcs[1:]):
            link(ids[0], srcs[0], w, s, 'os_id')
    log(f'os_id done ({time.time()-t0:.0f}s)')

    # 2. OpenSanctions referent = OFAC SDN uid
    cur.execute("""SELECT o.id, o.source, w.id
                   FROM screening_watchlist o
                   JOIN screening_watchlist w ON w.source = 'ofac' AND w.is_active = 1
                        AND w.source_id = 'OFAC-' || substring(o.source_url from '(?:^|/)ofac-([0-9]+)/?$')
                   WHERE o.is_active = 1 AND o.source IN ('opensanctions', 'opensanctions_pep', 'un')
                     AND o.source_url ~ '(^|/)ofac-[0-9]+/?$'""")
    for oid, osrc, wid in cur.fetchall():
        link(wid, 'ofac', oid, osrc, 'os_referent')
    log(f'os_referent done ({time.time()-t0:.0f}s)')

    # 3. EMLCU <-> Public Prosecution order (already tied by full national ID, link_emlcu_internal.py)
    cur.execute("""SELECT id, properties FROM screening_watchlist
                   WHERE is_active = 1 AND source = 'emlcu' AND properties LIKE '%%linked_internal%%'""")
    want = collections.defaultdict(list)
    for wid, props in cur.fetchall():
        try:
            li = (json.loads(props) or {}).get('linked_internal') or []
        except Exception:
            li = []
        for ib in li:
            want[int(ib)].append(wid)
    if want:
        cur.execute("""SELECT b.id, w.id FROM internal_blacklist b
                       JOIN screening_watchlist w ON w.source = 'internal_blacklist' AND w.source_id = """ + IBL_SID + """
                            AND w.is_active = 1
                       WHERE b.id = ANY(%s)""", (list(want),))
        for bid, iw in cur.fetchall():
            for wid in want[bid]:
                link(wid, 'emlcu', iw, 'internal_blacklist', 'linked_internal')
    log(f'linked_internal done ({time.time()-t0:.0f}s)')

    # 4 + 5. official ID numbers and passports
    by_id, by_pp, pp_ctx, srcof = collections.defaultdict(set), collections.defaultdict(set), {}, {}
    id_ctx = {}                 # wid -> (nationality codes, birth years): an ID match must not contradict them
    cur.execute("""SELECT id, source, entity_type, national_id_numbers, passport_numbers, nationality, countries, date_of_birth
                   FROM screening_watchlist WHERE is_active = 1
                     AND (coalesce(national_id_numbers, '') NOT IN ('', '[]') OR coalesce(passport_numbers, '') NOT IN ('', '[]'))""")
    for wid, src, et, nids, pps, nat, ctr, dob in cur:
        k = kind(et)
        srcof[wid] = src
        for n in as_list(nids):
            v = norm_id(n)
            if v:
                by_id[(k, v)].add(wid)
                id_ctx[wid] = (to_iso2(nat), years(dob))
        has_pp = False
        for p in as_list(pps):
            v = norm_passport(p)
            if v:
                by_pp[(k, v)].add(wid)
                has_pp = True
        if has_pp:
            pp_ctx[wid] = (to_iso2(nat) or to_iso2(ctr), years(dob))
    cur.execute("""SELECT w.id, w.entity_type, b.national_id, b.nationality, b.date_of_birth FROM internal_blacklist b
                   JOIN screening_watchlist w ON w.source = 'internal_blacklist' AND w.source_id = """ + IBL_SID.replace('%%', '%') + """
                        AND w.is_active = 1
                   WHERE coalesce(b.national_id, '') <> '' AND coalesce(b.is_active, 1) <> 0""")
    for wid, et, nid, nat, dob in cur:
        srcof[wid] = 'internal_blacklist'
        v = norm_id(nid)
        if v:
            by_id[(kind(et), v)].add(wid)
            id_ctx[wid] = (to_iso2(nat), years(dob))

    def agree(a, b):
        (ia, ya), (ib, yb) = id_ctx.get(a, (set(), set())), id_ctx.get(b, (set(), set()))
        if ya and yb and not any(abs(x - y) <= 1 for x in ya for y in yb):
            return False
        if ia and ib and not (ia & ib):
            return False
        return True
    # records already grouped (earlier steps) that carry a birth year / nationality, per group root:
    # a new member must agree with EVERY one of them (A 1970 - B no year - C 1990 never become one group)
    known = collections.defaultdict(list)
    for w in id_ctx:
        if w in idx:
            known[find(idx[w])].append(w)

    def group_of(w):
        i = idx.get(w)
        return (find(i), known.get(find(i)) or [w]) if i is not None else (None, [w])

    for ws in by_id.values():
        if 1 < len(ws) <= MAX_ID_GROUP:
            ws = sorted(ws)
            for i, w in enumerate(ws[1:], 1):
                rw, mw = group_of(w)
                to = None
                for x in ws[:i]:
                    rx, mx = group_of(x)
                    if rx is not None and rx == rw:
                        to = False                      # already in one group
                        break
                    if all(agree(a, b) for a in mx for b in mw):
                        to = x
                        break
                if to is False:
                    continue
                if to is None:
                    stats['official_id_refused_contradiction'] += 1
                    continue
                rx, mx = group_of(to)
                link(to, srcof[to], w, srcof[w], 'official_id')
                if w not in idx or to not in idx or find(idx[w]) != find(idx[to]):
                    continue                            # refused (unlinked by the MLRO, or group too big)
                rn = find(idx[w])
                for r in (rx, rw):
                    if r is not None and r != rn:
                        known.pop(r, None)
                known[rn] = list(dict.fromkeys(mx + mw))
        elif len(ws) > MAX_ID_GROUP:
            stats['skipped_id_groups_too_big'] += 1
    for ws in by_pp.values():
        if not (1 < len(ws) <= MAX_ID_GROUP):
            continue
        ws = sorted(ws)
        for i, a in enumerate(ws):
            for b in ws[i + 1:]:
                ia, ya = pp_ctx.get(a, (set(), set()))
                ib, yb = pp_ctx.get(b, (set(), set()))
                if (ia & ib) or any(abs(x - y) <= 1 for x in ya for y in yb):
                    link(a, srcof[a], b, srcof[b], 'passport')
    del by_id, by_pp, pp_ctx, srcof, id_ctx
    log(f'official_id / passport done ({time.time()-t0:.0f}s)')

    # 6. full name + full date of birth + shared nationality (persons, small groups only)
    groups = {}
    ctx = {}
    cur2 = conn.cursor(name='cx_entity_links_names')
    cur2.itersize = 5000
    cur2.execute("""SELECT id, source, entity_type, full_name, full_name_arabic, date_of_birth, nationality, countries
                    FROM screening_watchlist WHERE is_active = 1 AND date_of_birth ~ '[0-9]{4}-[0-9]{2}-[0-9]{2}'""")
    n = 0
    for wid, src, et, fn, fa, dob, nat, ctr in cur2:
        n += 1
        if kind(et) != 'P':
            continue
        iso = to_iso2(nat) or to_iso2(ctr)
        if not iso:
            continue
        dates = full_dates(dob)
        if not dates:
            continue
        keyed = False
        for name in {fn, fa}:
            toks = tokens(name or '')
            if len(toks) < 3:          # two elements are too common to identify a person
                continue
            key = ' '.join(sorted(toks))
            for d in dates:
                h = hash((key, d))
                g = groups.get(h)
                if g is None:
                    groups[h] = wid
                elif isinstance(g, list):
                    if wid not in g:
                        g.append(wid)
                elif g != wid:
                    groups[h] = [g, wid]
                keyed = True
        if keyed:
            ctx[wid] = (frozenset(iso), rank(src), src)
    cur2.close()
    for g in groups.values():
        if not isinstance(g, list):
            continue
        if len(g) > 6:
            stats['skipped_name_groups_too_big'] += 1
            continue
        g = sorted(g)
        for i, a in enumerate(g):
            for b in g[i + 1:]:
                if ctx[a][0] & ctx[b][0]:
                    link(a, ctx[a][2], b, ctx[b][2], 'name_dob_nationality')
    del groups, ctx
    log(f'name + DOB + nationality done: {n:,} records with a full date ({time.time()-t0:.0f}s)')

    comps = collections.defaultdict(list)
    for i in range(len(wids)):
        if size[find(i)] > 1:
            comps[find(i)].append(i)
    clusters = []
    for root, members_i in comps.items():
        ws = {wids[i]: i for i in members_i}
        for w in list(ws):
            if forbid.get(w) and forbid[w] & set(ws):
                del ws[w]
                stats['members_removed_by_unlink'] += 1
        if len(ws) < 2:
            continue
        lead = min(ws, key=lambda w: (src_rank[ws[w]], w))
        members = {}
        for w, i in ws.items():
            if w == lead:
                members[w] = ('lead', None, 1.0)
                continue
            b = BASES[via_b[i]] if via_b[i] >= 0 else 'os_id'
            other = wids[via_o[i]] if via_o[i] >= 0 else lead
            conf = {'os_id': 1.0, 'os_referent': 1.0, 'linked_internal': 1.0, 'official_id': 0.95,
                    'passport': 0.9, 'name_dob_nationality': 0.85}.get(b, 0.8)
            members[w] = (b, other if other in ws else lead, conf)
        bases = sorted({b for b, _, _ in members.values() if b != 'lead'})
        clusters.append({'lead': lead, 'members': members, 'bases': bases, 'conflict': [],
                         'ranks': sorted({src_rank[i] for i in ws.values()})})
    del comps
    _conflicts(conn, clusters, stats)
    inv = {v: k for k, v in SOURCE_RANK.items()}
    for c in clusters:
        stats['clusters'] += 1
        stats['links'] += len(c['members'])
        n_ = len(c['members'])
        stats['size_%s' % ('2' if n_ == 2 else '3-5' if n_ <= 5 else '6+')] += 1
        for x in c['conflict']:
            stats['conflict_' + x] += 1
        for b, _, _ in c['members'].values():
            stats['member_basis_' + b] += 1
        srcs = [inv.get(r, 'other') for r in c['ranks']]
        stats['pair ' + ' + '.join(srcs[:2]) + (' + …' if len(srcs) > 2 else '')] += 1
    stats['seconds'] = int(time.time() - t0)
    return clusters, stats


def _conflicts(conn, clusters, stats):
    """Members that disagree on date of birth / nationality / ID (shown to the analyst, never used to split).
    Only groups that are not just the same OpenSanctions entity in two of its datasets."""
    from screening.country_codes import to_iso2
    os_only = {SOURCE_RANK['opensanctions'], SOURCE_RANK['opensanctions_pep']}
    todo = [c for c in clusters if not set(c['ranks']) <= os_only]
    cur = conn.cursor()
    for k in range(0, len(todo), 2000):
        part = todo[k:k + 2000]
        ids = [w for c in part for w in c['members']]
        cur.execute("""SELECT id, date_of_birth, nationality, national_id_numbers FROM screening_watchlist
                       WHERE id = ANY(%s)""", (ids,))
        info = {r[0]: (years(r[1]), to_iso2(r[2]), {norm_id(x) for x in as_list(r[3])} - {None}) for r in cur.fetchall()}
        for c in part:
            rows = [info[w] for w in c['members'] if w in info]
            yrs = [r[0] for r in rows if r[0]]
            if len(yrs) > 1 and not all(any(abs(x - y) <= 1 for x in a for y in b)
                                        for i, a in enumerate(yrs) for b in yrs[i + 1:]):
                c['conflict'].append('dob')
            isos = [r[1] for r in rows if r[1]]
            if len(isos) > 1 and not set.intersection(*isos):
                c['conflict'].append('nationality')
            idsets = [r[2] for r in rows if r[2]]
            if len(idsets) > 1 and not set.intersection(*idsets):
                c['conflict'].append('id')
    stats['groups_checked_for_conflicts'] = len(todo)


def fingerprint(cur):
    """Cheap summary of everything the links depend on: when it has not changed since the last
    applied build, the daily rebuild is skipped (--if-changed)."""
    cur.execute("""SELECT count(*) FILTER (WHERE is_active = 1), count(*), max(updated_at::timestamptz)
                   FROM screening_watchlist""")
    w = cur.fetchone()
    b = ()
    for table in ('internal_blacklist', 'internal_pep'):
        # every column the links read: an edit of any of them triggers a rebuild
        cur.execute(f"""SELECT count(*), max(modified_date::text),
                              md5(string_agg(concat_ws('|', id, source_id, full_name, national_id, date_of_birth, nationality),
                                             ',' ORDER BY id))
                       FROM {table} WHERE coalesce(is_active, 1) <> 0""")
        b = tuple(b) + tuple(cur.fetchone())
    cur.execute("SELECT to_regclass('screening_entity_unlinks') IS NOT NULL")
    u = None
    if cur.fetchone()[0]:
        cur.execute("SELECT count(*), max(unlinked_at), max(revoked_at) FROM screening_entity_unlinks")
        u = cur.fetchone()
    return json.dumps([str(x) for x in (w or ())] + [str(x) for x in (b or ())] + [str(x) for x in (u or ())])


def last_fingerprint(cur):
    cur.execute("""SELECT stats FROM screening_entity_link_runs WHERE status = 'APPLIED'
                   ORDER BY id DESC LIMIT 1""")
    r = cur.fetchone()
    try:
        return (json.loads(r[0]) or {}).get('fingerprint') if r else None
    except Exception:
        return None


def apply(conn, clusters, stats, log=print, fp=None):
    cur = conn.cursor()
    cur.execute("INSERT INTO screening_entity_link_runs (status) VALUES ('RUNNING') RETURNING id")
    run_id = cur.fetchone()[0]
    conn.commit()
    try:
        cur.execute("""CREATE TEMP TABLE tmp_entity_links (watchlist_id INTEGER, cluster_id INTEGER, basis TEXT,
                       confidence REAL, linked_to INTEGER) ON COMMIT DROP""")
        cbuf, lbuf = io.StringIO(), io.StringIO()
        for i, c in enumerate(clusters, 1):
            cbuf.write('%d\t%d\t%d\t%s\t%s\n' % (i, c['lead'], len(c['members']), ','.join(c['bases']) or '\\N',
                                                't' if c['conflict'] else 'f'))
            for w, (basis, other, conf) in c['members'].items():
                lbuf.write('%d\t%d\t%s\t%s\t%s\n' % (w, i, basis, conf, '\\N' if other is None else other))
        cbuf.seek(0)
        lbuf.seek(0)
        cur.copy_expert("COPY tmp_entity_links (watchlist_id, cluster_id, basis, confidence, linked_to) FROM STDIN", lbuf)
        del lbuf
        cur.execute("DELETE FROM screening_entity_links")
        cur.execute("DELETE FROM screening_entity_clusters")
        cur.copy_expert("COPY screening_entity_clusters (id, lead_watchlist_id, member_count, bases, has_conflict) FROM STDIN", cbuf)
        cur.execute("""INSERT INTO screening_entity_links (watchlist_id, cluster_id, source, source_id, basis, confidence, linked_to)
                       SELECT t.watchlist_id, t.cluster_id, w.source, w.source_id, t.basis, t.confidence, t.linked_to
                       FROM tmp_entity_links t JOIN screening_watchlist w ON w.id = t.watchlist_id""")
        cur.execute("SELECT setval('screening_entity_clusters_id_seq', GREATEST(%s, 1))", (len(clusters),))
        cur.execute("""UPDATE screening_entity_link_runs SET finished_at = now(), status = 'APPLIED', clusters = %s,
                       links = %s, stats = %s WHERE id = %s""",
                    (stats.get('clusters', 0), stats.get('links', 0), json.dumps(dict(stats, fingerprint=fp)), run_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.execute("UPDATE screening_entity_link_runs SET finished_at = now(), status = 'FAILED', stats = %s WHERE id = %s",
                    (json.dumps({'error': str(e)[:500]}), run_id))
        conn.commit()
        raise
    log(f'applied: {stats.get("clusters", 0):,} clusters, {stats.get("links", 0):,} linked records (run {run_id})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='rebuild the link tables (default: dry run)')
    ap.add_argument('--json', action='store_true', help='print the counts as JSON')
    ap.add_argument('--if-changed', action='store_true',
                    help='with --apply: skip when no list, internal record or unlink changed since the last build')
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE, '.env'))
    except ImportError:
        pass
    conn = connect()
    cur = conn.cursor()
    if not tables_exist(cur):
        if a.apply:
            print('entity link tables are missing (migration 20261114_p2_entity_links.sql not applied) - nothing to do')
            return 0
        print('entity link tables are missing - dry run only')
    cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_KEY,))
    if not cur.fetchone()[0]:
        print('another entity-link build (or an unlink) is running - stop')
        return 2
    conn.commit()
    fp = None
    if a.apply:
        fp = fingerprint(cur)
        if a.if_changed and fp == last_fingerprint(cur):
            conn.close()
            print('no list, internal record or unlink changed since the last build - skipped')
            return 0
        conn.commit()
    clusters, stats = build(conn, log=lambda m: print(m, flush=True))
    out = dict(sorted(stats.items()))
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        for k, v in out.items():
            print(f'  {k:<55} {v:>10,}')
    sample = [{'lead': c['lead'], 'members': sorted(c['members']), 'bases': c['bases'], 'conflict': c['conflict']}
              for c in clusters if c['conflict'] or 'name_dob_nationality' in c['bases']][:5]
    print('sample (ids only):', json.dumps(sample))
    if a.apply:
        apply(conn, clusters, stats, fp=fp)
    else:
        print('dry run: nothing written')
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
