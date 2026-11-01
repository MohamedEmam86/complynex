"""
Monthly drift report (Phase 5, P5-5).

Once a month the screening system is compared with the month before, so a slow change in
the lists, the engine or how analysts decide is noticed instead of discovered at audit:

  lists      per list: update runs, failures, added / updated / delisted / relisted, blocked
             versions, active records at report time
  hits       per list and per list category: hits raised, true matches, false positives,
             pending, false-positive rate, average match score
  screening  screenings run, hit rate, INCOMPLETE rate, average highest score, result mix
  quality    Gold Set runs of the month (v1 and v2: last run's headline rates) and the
             end-to-end quality runs (average / lowest recall, false-alert rate)

Each report is stored in screening_drift_reports (one row per month). An alert is raised
to the MLROs when a metric moves beyond its threshold (screening_config 'drift_thresholds',
JSON, overrides DEFAULT_THRESHOLDS).
"""
import glob
import io
import json
import logging
import os
from datetime import date, datetime

logger = logging.getLogger(__name__)

GOLD_RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'screening', 'data', 'gold', 'results')
LINK = '/screening/reports/drift'

DEFAULT_THRESHOLDS = {
    'fp_rate_points': 10.0,        # false-positive rate of a list moved by more than N points (min_decided decisions)
    'min_decided': 20,
    'hits_change_pct': 50.0,       # hits of a list moved by more than N % (min_hits)
    'min_hits': 30,
    'incomplete_rate': 2.0,        # INCOMPLETE screenings above N % of the month's screenings
    'incomplete_points': 1.0,      # ... or up by more than N points
    'gold_miss_points': 0.5,       # Gold Set headline miss / false-alert rate up by more than N points
    'e2e_recall_points': 2.0,      # end-to-end recall down by more than N points
    'delisted_pct': 5.0,           # a list delisted more than N % of its active records in the month
    'update_failures': 3,          # a list failed / was blocked at least N times in the month
}


# ---------------------------------------------------------------------------- helpers
def month_bounds(month):
    """'YYYY-MM' (or a date) -> (first day, first day of next month) as ISO dates."""
    if isinstance(month, (date, datetime)):
        y, m = month.year, month.month
    else:
        y, m = (int(x) for x in str(month)[:7].split('-'))
    start = date(y, m, 1)
    end = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return start.isoformat(), end.isoformat()


def previous_month(today=None):
    today = today or date.today()
    y, m = today.year, today.month - 1
    if m == 0:
        y, m = y - 1, 12
    return f'{y:04d}-{m:02d}'


def month_before(month):
    y, m = (int(x) for x in month.split('-'))
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    return f'{y:04d}-{m:02d}'


def _rate(a, b):
    return round(100.0 * a / b, 2) if b else None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm(s):
    from screening.user_reports import norm_source
    return norm_source(s)


# ---------------------------------------------------------------------------- collect
def collect(q, month, gold_dir=GOLD_RESULTS):
    """All metrics of one month. q(sql, params) -> list of dict rows."""
    start, end = month_bounds(month)
    out = {'month': month[:7], 'period': [start, end], 'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M')}

    # lists
    lists = {}
    for r in q("""SELECT source, status, COALESCE(added,0) added, COALESCE(updated,0) updated,
                         COALESCE(delisted,0) delisted, COALESCE(relisted,0) relisted
                  FROM screening_list_update_log WHERE run_at >= %s AND run_at < %s""", (start, end)):
        d = lists.setdefault(_norm(r['source']), {'runs': 0, 'failures': 0, 'added': 0, 'updated': 0,
                                                  'delisted': 0, 'relisted': 0, 'blocked': 0, 'active': None})
        d['runs'] += 1
        if str(r['status'] or '').lower() in ('failed', 'error', 'blocked'):
            d['failures'] += 1
        for k in ('added', 'updated', 'delisted', 'relisted'):
            d[k] += int(r[k] or 0)
    for r in q("""SELECT source, count(*) n FROM screening_list_versions
                  WHERE status = 'BLOCKED' AND started_at >= %s AND started_at < %s GROUP BY source""", (start, end)):
        lists.setdefault(_norm(r['source']), {'runs': 0, 'failures': 0, 'added': 0, 'updated': 0, 'delisted': 0,
                                              'relisted': 0, 'blocked': 0, 'active': None})['blocked'] = int(r['n'])
    for r in q("SELECT source, count(*) n FROM screening_watchlist WHERE is_active = 1 GROUP BY source", ()):
        k = _norm(r['source'])
        if k in lists:
            lists[k]['active'] = int(r['n'])
    for d in lists.values():
        d['delisted_pct'] = _rate(d['delisted'], d['active'] or 0)
    out['lists'] = lists

    # hits (screening queue rows raised in the month)
    from screening.user_reports import category, _is_tm, _is_fp, _json
    by_list, by_cat = {}, {}
    for r in q("""SELECT list_source, status, resolution, match_score, match_details FROM screening_queue
                  WHERE created_at >= %s AND created_at < %s""", (start, end)):
        md = _json(r.get('match_details'))
        pending = str(r['status'] or '').lower() != 'resolved'
        for key, bucket in ((_norm(r['list_source']), by_list), (category(md, r['list_source']), by_cat)):
            d = bucket.setdefault(key, {'hits': 0, 'true_matches': 0, 'false_positives': 0, 'pending': 0, '_s': []})
            d['hits'] += 1
            if pending:
                d['pending'] += 1
            elif _is_tm(r['resolution']):
                d['true_matches'] += 1
            elif _is_fp(r['resolution']):
                d['false_positives'] += 1
            s = _f(r['match_score'])
            if s is not None:
                d['_s'].append(s)
    for bucket in (by_list, by_cat):
        for d in bucket.values():
            decided = d['true_matches'] + d['false_positives']
            d['decided'] = decided
            d['fp_rate'] = _rate(d['false_positives'], decided)
            s = d.pop('_s')
            d['avg_score'] = round(sum(s) / len(s), 1) if s else None
    out['hits_by_list'], out['hits_by_category'] = by_list, by_cat

    # screenings (created_at is text; ISO strings compare correctly)
    rows = q("""SELECT screening_result, total_matches_found, highest_match_score FROM screening_results
                WHERE created_at >= %s AND created_at < %s""", (start, end))
    n = len(rows)
    mix = {}
    inc = hits = 0
    sc = []
    for r in rows:
        res = str(r['screening_result'] or 'UNKNOWN').upper()
        mix[res] = mix.get(res, 0) + 1
        inc += res == 'INCOMPLETE'
        hits += int(r['total_matches_found'] or 0) > 0
        s = _f(r['highest_match_score'])
        if s is not None:
            sc.append(s)
    out['screening'] = {'screenings': n, 'with_hits': hits, 'hit_rate': _rate(hits, n), 'incomplete': inc,
                        'incomplete_rate': _rate(inc, n), 'avg_highest_score': round(sum(sc) / len(sc), 1) if sc else None,
                        'result_mix': mix}

    # Gold Set runs of the month (result files written by every gold_set_eval.py run)
    gold = {}
    for path in sorted(glob.glob(os.path.join(gold_dir, '*.json'))):
        stamp = os.path.basename(path)[:8]
        if not (start.replace('-', '') <= stamp < end.replace('-', '')):
            continue
        try:
            res = json.load(open(path))
        except Exception:
            continue
        v = f"v{res.get('gold_version', 1)}"
        g = gold.setdefault(v, {'runs': 0})
        g['runs'] += 1
        g['last_run'] = os.path.basename(path)[:15]
        g['commit'] = res.get('commit')
        for k, val in res.items():
            if k.endswith('_miss_rate') or k.endswith('_fp_rate'):
                g[k] = val
        g['holdout'] = res.get('holdout')
        g['categories'] = {c: x.get('rate') for c, x in (res.get('categories') or {}).items()}
    out['gold'] = gold

    # end-to-end quality runs
    rec, fa = [], []
    for r in q("""SELECT summary FROM screening_quality_runs WHERE run_at >= %s AND run_at < %s""", (start, end)):
        s = _json(r['summary'])
        if _f(s.get('recall')) is not None:
            rec.append(_f(s.get('recall')))
        if _f(s.get('false_alert_rate')) is not None:
            fa.append(_f(s.get('false_alert_rate')))
    out['e2e'] = {'runs': len(rec), 'avg_recall': round(sum(rec) / len(rec), 2) if rec else None,
                  'min_recall': min(rec) if rec else None,
                  'avg_false_alert_rate': round(sum(fa) / len(fa), 2) if fa else None}
    return out


# ---------------------------------------------------------------------------- compare
def thresholds(cfg=None):
    t = dict(DEFAULT_THRESHOLDS)
    for k, v in (cfg or {}).items():
        if k in t and _f(v) is not None:
            t[k] = _f(v)
    return t


def compare(cur, prev, th=None):
    """Alerts for metrics that moved beyond their threshold. prev may be None (first report)."""
    th = th or thresholds()
    al = []

    def add(code, subject, en, ar):
        al.append({'code': code, 'subject': subject, 'en': en, 'ar': ar})

    prev = prev or {}
    for src, d in (cur.get('lists') or {}).items():
        if (d.get('failures', 0) + d.get('blocked', 0)) >= th['update_failures']:
            add('list_updates', src, f"{src}: {d['failures']} failed and {d['blocked']} blocked updates this month",
                f"{src}: {d['failures']} تحديث فشل و {d['blocked']} اتوقف الشهر ده")
        if d.get('delisted_pct') is not None and d['delisted_pct'] > th['delisted_pct']:
            add('list_delisted', src, f"{src}: {d['delisted']} records delisted ({d['delisted_pct']}% of the list)",
                f"{src}: اتشال {d['delisted']} سجل ({d['delisted_pct']}% من القايمة)")
    ph = prev.get('hits_by_list') or {}
    for src, d in (cur.get('hits_by_list') or {}).items():
        p = ph.get(src)
        if not p:
            continue
        if (d.get('decided', 0) >= th['min_decided'] and p.get('decided', 0) >= th['min_decided']
                and d.get('fp_rate') is not None and p.get('fp_rate') is not None
                and abs(d['fp_rate'] - p['fp_rate']) > th['fp_rate_points']):
            add('fp_rate', src, f"{src}: false-positive rate {p['fp_rate']}% -> {d['fp_rate']}%",
                f"{src}: نسبة التنبيهات الغلط {p['fp_rate']}% ← {d['fp_rate']}%")
        if max(d['hits'], p['hits']) >= th['min_hits'] and p['hits']:
            ch = 100.0 * (d['hits'] - p['hits']) / p['hits']
            if abs(ch) > th['hits_change_pct']:
                add('hit_volume', src, f"{src}: hits {p['hits']} -> {d['hits']} ({ch:+.0f}%)",
                    f"{src}: عدد النتايج {p['hits']} ← {d['hits']} ({ch:+.0f}%)")
    s, ps = cur.get('screening') or {}, prev.get('screening') or {}
    if s.get('incomplete_rate') is not None:
        up = s['incomplete_rate'] - (ps.get('incomplete_rate') or 0)
        if s['incomplete_rate'] > th['incomplete_rate'] or (ps and up > th['incomplete_points']):
            add('incomplete', 'screening', f"INCOMPLETE screenings: {s['incomplete_rate']}% ({s['incomplete']})",
                f"فحوصات غير مكتملة: {s['incomplete_rate']}% ({s['incomplete']})")
    for v, g in (cur.get('gold') or {}).items():
        pg = (prev.get('gold') or {}).get(v) or {}
        for k in ('core_miss_rate', 'core_fp_rate'):
            if g.get(k) is not None and pg.get(k) is not None and g[k] - pg[k] > th['gold_miss_points']:
                add('gold', f'gold {v}', f"Gold Set {v} {k}: {pg[k]}% -> {g[k]}%",
                    f"الـ Gold Set {v} {k}: {pg[k]}% ← {g[k]}%")
    e, pe = cur.get('e2e') or {}, prev.get('e2e') or {}
    if e.get('avg_recall') is not None and pe.get('avg_recall') is not None \
            and pe['avg_recall'] - e['avg_recall'] > th['e2e_recall_points']:
        add('e2e_recall', 'quality', f"end-to-end recall {pe['avg_recall']}% -> {e['avg_recall']}%",
            f"نسبة اكتشاف الأسماء في الاختبار الشامل {pe['avg_recall']}% ← {e['avg_recall']}%")
    return al


# ---------------------------------------------------------------------------- store / alert
def load(conn, month):
    c = conn.cursor()
    c.execute("SELECT metrics, alerts FROM screening_drift_reports WHERE month = %s", (month_bounds(month)[0],))
    r = c.fetchone()
    conn.rollback()
    if not r:
        return None, None
    m, a = (r['metrics'], r['alerts']) if isinstance(r, dict) else (r[0], r[1])
    return (m if isinstance(m, dict) else json.loads(m or '{}')), (a if isinstance(a, list) else json.loads(a or '[]'))


def store(conn, month, metrics, alerts, created_by='scheduled'):
    c = conn.cursor()
    c.execute("""INSERT INTO screening_drift_reports (month, metrics, alerts, created_by)
                 VALUES (%s, %s, %s, %s)
                 ON CONFLICT (month) DO UPDATE SET metrics = EXCLUDED.metrics, alerts = EXCLUDED.alerts,
                     created_by = EXCLUDED.created_by, created_at = now()""",
              (month_bounds(month)[0], json.dumps(metrics, default=str, ensure_ascii=False),
               json.dumps(alerts, ensure_ascii=False), created_by))
    conn.commit()


def notify(conn, month, alerts):
    """One in-app notification per MLRO (admins if none) listing the month's alerts. Never raises."""
    if not alerts:
        return 0
    try:
        from screening.list_versions import _recipients, _cur
        c = _cur(conn)
        ids = _recipients(c)
        title = f'Screening drift report {month}: {len(alerts)} alert(s)'
        msg = '; '.join(a['en'] for a in alerts[:8]) + (' ...' if len(alerts) > 8 else '')
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for uid in ids:
            c.execute("""INSERT INTO notifications (user_id, title, message, type, is_read, link, created_at)
                         VALUES (%s, %s, %s, 'warning', 0, %s, %s)""", (uid, title[:200], msg, f'{LINK}?month={month}', now))
        conn.commit()
        return len(ids)
    except Exception as e:
        logger.error('drift alert failed: %s', e)
        try:
            conn.rollback()
        except Exception:
            pass
        return 0


def run(conn, q, month, created_by='scheduled', cfg=None, alert=True):
    """Collect, compare with the month before, store, alert. Returns (metrics, alerts)."""
    m = collect(q, month)
    prev, _ = load(conn, month_before(month[:7]))
    al = compare(m, prev, thresholds(cfg))
    store(conn, month[:7], m, al, created_by)
    if alert:
        notify(conn, month[:7], al)
    return m, al


# ---------------------------------------------------------------------------- export
def workbook(month, m, alerts, tr=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from screening.user_reports import _cell
    tr = tr or (lambda s: s)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Summary'
    bold = Font(bold=True)
    ws.append([tr('Month'), month])
    ws.append([tr('Generated at'), m.get('generated_at', '')])
    s = m.get('screening') or {}
    for k in ('screenings', 'with_hits', 'hit_rate', 'incomplete', 'incomplete_rate', 'avg_highest_score'):
        ws.append([tr(k), _cell(s.get(k))])
    e = m.get('e2e') or {}
    for k in ('runs', 'avg_recall', 'min_recall', 'avg_false_alert_rate'):
        ws.append([tr('end-to-end') + ' ' + k, _cell(e.get(k))])

    def sheet(title, head, rows):
        sh = wb.create_sheet(title[:31])
        sh.append([tr(h) for h in head])
        for c in sh[1]:
            c.font = bold
        for r in rows:
            sh.append([_cell(x) for x in r])

    sheet('Alerts', ['Subject', 'Alert'], [[a['subject'], a['en']] for a in alerts])
    sheet('Lists', ['List', 'Runs', 'Failures', 'Blocked', 'Added', 'Updated', 'Delisted', 'Relisted', 'Active',
                    'Delisted %'],
          [[k, d['runs'], d['failures'], d['blocked'], d['added'], d['updated'], d['delisted'], d['relisted'],
            d['active'], d['delisted_pct']] for k, d in sorted((m.get('lists') or {}).items())])
    hh = ['Hits', 'True matches', 'False positives', 'Pending', 'False-positive rate', 'Average score']
    for title, key in (('Hits by list', 'hits_by_list'), ('Hits by category', 'hits_by_category')):
        sheet(title, ['Key'] + hh, [[k, d['hits'], d['true_matches'], d['false_positives'], d['pending'], d['fp_rate'],
                                     d['avg_score']] for k, d in sorted((m.get(key) or {}).items())])
    sheet('Gold Set', ['Version', 'Runs', 'Core miss %', 'Core false alerts %', 'Extended miss %',
                       'Extended false alerts %', 'Last run'],
          [[v, g.get('runs'), g.get('core_miss_rate'), g.get('core_fp_rate'), g.get('extended_miss_rate'),
            g.get('extended_fp_rate'), g.get('last_run')] for v, g in sorted((m.get('gold') or {}).items())])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
