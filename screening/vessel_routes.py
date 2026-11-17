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
Vessel screening pages (V3): screen one ship, bulk file, history, validation of each hit, and the
ComplyNex Vessels Database (browse / search every listed ship).

Access: module permission 'vessels' (user form -> Additional modules): view = screen and browse,
edit = record validation decisions and run bulk files. Site admins have both.
Clients see "International approved lists"; the real list is shown to site administrators only.
"""
import csv
import io
import json
import logging

from flask import (Blueprint, Response, abort, flash, redirect, render_template, request, url_for)
from flask_babel import gettext
from flask_login import current_user, login_required

from database.db import get_db
from screening import vessel_engine as VE
from screening import vessel_store as VS
from screening import vessel_utils as VU
from utils.decorators import permission_required

logger = logging.getLogger(__name__)

vessels_bp = Blueprint('vessels', __name__, url_prefix='/screening/vessels')

BULK_MAX_ROWS = 500
REASONS = [
    ('identifier_differs', 'IMO / MMSI differs'), ('name_only', 'Name similarity only'),
    ('different_ship_type', 'Different ship type / tonnage / build year'),
    ('different_owner', 'Different owner / operator'), ('number_differs', 'Different number in the name'),
    ('identifier_matches', 'Same IMO / MMSI'), ('owner_matches', 'Owner / operator is listed'),
    ('other', 'Other (see comment)'),
]
REASON_CODES = {c for c, _ in REASONS}
MEASURES = {'asset_freeze': 'Asset freeze', 'port_ban': 'Port entry ban', 'deflag': 'De-flagging',
            'chartering_ban': 'Chartering ban', 'shipping_sanctions': 'Shipping sanctions',
            'trade_sanctions': 'Trade sanctions', 'services_ban': 'Services ban'}


def is_site_admin():
    return getattr(current_user, 'role', '') in ('admin', 'superadmin', 'it_admin') or \
        (hasattr(current_user, 'is_admin') and current_user.is_admin())


def list_label(source):
    """What the page shows for a list: generic for clients, the real source for site administrators."""
    if is_site_admin():
        return source or '-'
    return gettext('International approved lists')


@vessels_bp.app_context_processor
def _vessel_helpers():
    return {'vessel_list_label': list_label, 'vessel_measure_label': lambda m: gettext(MEASURES.get(m, m)),
            'vessel_reasons': REASONS,
            'vessel_reason_label': lambda c: gettext(dict(REASONS).get(c, c))}


def _conn():
    return get_db()


def _screen(form, conn, with_owner=True):
    return VE.screen_vessel(
        name=form.get('name'), imo=form.get('imo'), mmsi=form.get('mmsi'), call_sign=form.get('call_sign'),
        flag=form.get('flag'), owner=form.get('owner'), vessel_type=form.get('vessel_type'), conn=conn,
        screen_party=VE.party_screener() if (with_owner and (form.get('owner') or '').strip()) else None)


def _release_engine():
    try:
        from screening.routes import get_engine
        from api.screening_v1 import _release_engine_conn
        _release_engine_conn(get_engine())
    except Exception:
        pass


def _save(conn, res, kind='single', bulk_id=None, customer_ref=None):
    row = conn.execute("""INSERT INTO vessel_screenings (user_id, kind, bulk_id, customer_ref, query, result, tier,
                                                         hit_count)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                       (getattr(current_user, 'id', None), kind, bulk_id, customer_ref,
                        json.dumps(res['query'], ensure_ascii=False), json.dumps(res, ensure_ascii=False, default=str),
                        res['tier'], len(res['hits']) + len(res['owner_hits']))).fetchone()
    conn.commit()
    return row['id']


def _audit(action, details):
    try:
        from models.audit import AuditLog
        AuditLog.log(current_user.id, action, 'Vessel screening', None, details, request.remote_addr)
    except Exception:
        pass


def candidate_fp(h):
    return VU.fingerprint(h.get('name'), h.get('imo'), h.get('flag'),
                          ','.join(sorted(str(o.get('name') or '') for o in h.get('owners') or [])))


# --------------------------------------------------------------------------- screen one ship
@vessels_bp.route('/', methods=['GET'])
@login_required
@permission_required('vessels', level='view')
def index():
    return redirect(url_for('vessels.screen'))


@vessels_bp.route('/screen', methods=['GET', 'POST'])
@login_required
@permission_required('vessels', level='view')
def screen():
    if request.method == 'POST':
        f = request.form
        if not any((f.get(k) or '').strip() for k in ('name', 'imo', 'mmsi', 'call_sign', 'owner')):
            flash(gettext('Enter at least a ship name, IMO number, MMSI, call sign or owner.'), 'warning')
            return render_template('vessels/screen.html', form=f)
        conn = _conn()
        try:
            res = _screen(f, conn)
        finally:
            _release_engine()
        sid = _save(conn, res, customer_ref=(f.get('customer_ref') or '').strip()[:200] or None)
        _audit('Vessel screened', f"{res['query'].get('name') or res['query'].get('imo')} - {res['tier']}")
        return redirect(url_for('vessels.result', sid=sid))
    return render_template('vessels/screen.html', form={})


def _load_screening(sid):
    conn = _conn()
    row = conn.execute('SELECT * FROM vessel_screenings WHERE id = %s', (sid,)).fetchone()
    if not row:
        abort(404)
    if not is_site_admin() and row['user_id'] not in (None, current_user.id) and \
            not current_user.can_edit('vessels'):
        abort(403)
    res = row['result'] if isinstance(row['result'], dict) else json.loads(row['result'])
    return conn, row, res


@vessels_bp.route('/result/<int:sid>')
@login_required
@permission_required('vessels', level='view')
def result(sid):
    conn, row, res = _load_screening(sid)
    decisions = {d['watchlist_id']: d for d in conn.execute(
        """SELECT d.*, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS decided_by_name FROM vessel_hit_decisions d LEFT JOIN users u ON u.id = d.decided_by
           WHERE d.screening_id = %s ORDER BY d.decided_at""", (sid,)).fetchall()}
    qkey = VU.query_key(res['query'].get('name'), res['query'].get('imo'), res['query'].get('mmsi'),
                        res['query'].get('flag'))
    cleared = {}
    for h in res['hits']:
        prev = conn.execute("""SELECT d.decided_at, d.reason, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS by_name FROM vessel_hit_decisions d
                               LEFT JOIN users u ON u.id = d.decided_by
                               WHERE d.query_key = %s AND d.watchlist_id = %s AND d.decision = 'false_match'
                                 AND d.candidate_fp = %s AND d.screening_id <> %s
                               ORDER BY d.decided_at DESC LIMIT 1""",
                            (qkey, h['watchlist_id'], candidate_fp(h), sid)).fetchone()
        if prev:
            cleared[h['watchlist_id']] = prev
    return render_template('vessels/result.html', sid=sid, row=row, res=res, decisions=decisions,
                           cleared=cleared, can_decide=current_user.can_edit('vessels') or is_site_admin())


@vessels_bp.route('/result/<int:sid>/decide', methods=['POST'])
@login_required
@permission_required('vessels', level='edit')
def decide(sid):
    conn, row, res = _load_screening(sid)
    try:
        wid = int(request.form.get('watchlist_id') or 0)
    except ValueError:
        wid = 0
    hit = next((h for h in res['hits'] if h['watchlist_id'] == wid), None)
    decision = request.form.get('decision')
    reason = request.form.get('reason')
    comment = (request.form.get('comment') or '').strip()
    if not hit or decision not in ('true_match', 'false_match') or reason not in REASON_CODES:
        flash(gettext('Choose the hit, the decision and a reason.'), 'danger')
        return redirect(url_for('vessels.result', sid=sid))
    if len(comment) < 5:
        flash(gettext('A comment explaining the decision is required.'), 'danger')
        return redirect(url_for('vessels.result', sid=sid))
    q = res['query']
    conn.execute("""INSERT INTO vessel_hit_decisions (screening_id, watchlist_id, decision, reason, comment, query_key,
                                                      candidate_fp, decided_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                 (sid, wid, decision, reason, comment[:4000], VU.query_key(q.get('name'), q.get('imo'),
                                                                            q.get('mmsi'), q.get('flag')),
                  candidate_fp(hit), current_user.id))
    conn.commit()
    _audit('Vessel hit validated', f'screening {sid}, listed ship {hit.get("name")}: {decision} ({reason})')
    flash(gettext('Decision recorded.'), 'success')
    return redirect(url_for('vessels.result', sid=sid))


@vessels_bp.route('/history')
@login_required
@permission_required('vessels', level='view')
def history():
    conn = _conn()
    if is_site_admin() or current_user.can_edit('vessels'):
        rows = conn.execute("""SELECT s.id, s.kind, s.query, s.tier, s.hit_count, s.created_at, s.customer_ref,
                                      TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS user_name,
                                      (SELECT count(*) FROM vessel_hit_decisions d WHERE d.screening_id = s.id) AS decided
                               FROM vessel_screenings s LEFT JOIN users u ON u.id = s.user_id
                               ORDER BY s.id DESC LIMIT 300""").fetchall()
    else:
        rows = conn.execute("""SELECT s.id, s.kind, s.query, s.tier, s.hit_count, s.created_at, s.customer_ref,
                                      TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS user_name,
                                      (SELECT count(*) FROM vessel_hit_decisions d WHERE d.screening_id = s.id) AS decided
                               FROM vessel_screenings s LEFT JOIN users u ON u.id = s.user_id
                               WHERE s.user_id = %s ORDER BY s.id DESC LIMIT 300""", (current_user.id,)).fetchall()
    items = []
    for r in rows:
        q = r['query'] if isinstance(r['query'], dict) else json.loads(r['query'] or '{}')
        items.append(dict(r, q=q))
    return render_template('vessels/history.html', items=items)


# --------------------------------------------------------------------------- bulk
BULK_COLUMNS = ('name', 'imo', 'mmsi', 'call_sign', 'flag', 'owner', 'vessel_type', 'reference')


@vessels_bp.route('/bulk/template')
@login_required
@permission_required('vessels', level='view')
def bulk_template():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(BULK_COLUMNS)
    w.writerow(['OCEAN GLORY', '9074729', '', '', 'Panama', '', 'Crude Oil Tanker', 'REF-001'])
    return Response('﻿' + buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=vessel_screening_template.csv'})


def _read_rows(fs):
    name = (fs.filename or '').lower()
    rows = []
    if name.endswith('.xlsx'):
        import openpyxl
        ws = openpyxl.load_workbook(fs, read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        head = [str(h or '').strip().lower() for h in next(it, [])]
        for r in it:
            rows.append({head[i]: ('' if v is None else str(v).strip()) for i, v in enumerate(r) if i < len(head)})
    else:
        text = fs.read().decode('utf-8-sig', errors='replace')
        for r in csv.DictReader(io.StringIO(text)):
            rows.append({str(k or '').strip().lower(): str(v or '').strip() for k, v in r.items()})
    return [r for r in rows if any(r.get(c) for c in ('name', 'imo', 'mmsi', 'call_sign', 'owner'))]


@vessels_bp.route('/bulk', methods=['GET', 'POST'])
@login_required
@permission_required('vessels', level='edit')
def bulk():
    if request.method == 'POST':
        fs = request.files.get('file')
        if not fs or not fs.filename:
            flash(gettext('Choose a CSV or Excel file.'), 'warning')
            return redirect(url_for('vessels.bulk'))
        try:
            rows = _read_rows(fs)
        except Exception as e:
            logger.warning(f'[VESSELS] bulk file unreadable: {e}')
            flash(gettext('The file could not be read. Use the template (CSV UTF-8 or .xlsx).'), 'danger')
            return redirect(url_for('vessels.bulk'))
        if not rows:
            flash(gettext('The file has no rows to screen.'), 'warning')
            return redirect(url_for('vessels.bulk'))
        if len(rows) > BULK_MAX_ROWS:
            flash(gettext('Up to %(n)s rows per file.', n=BULK_MAX_ROWS), 'warning')
            return redirect(url_for('vessels.bulk'))
        conn = _conn()
        job = conn.execute("""INSERT INTO vessel_bulk_jobs (user_id, filename, row_count) VALUES (%s, %s, %s)
                              RETURNING id""", (current_user.id, fs.filename[:200], len(rows))).fetchone()
        conn.commit()
        hit_rows = 0
        # the owner layer runs the full person / entity engine: kept for files of up to 100 rows
        with_owner = len(rows) <= 100
        if not with_owner and any((r.get('owner') or '').strip() for r in rows):
            flash(gettext('Owners were not screened (file over 100 rows): screen them with bulk name screening.'),
                  'warning')
        try:
            for r in rows:
                res = _screen(r, conn, with_owner=with_owner)
                if res['hits'] or res['owner_hits']:
                    hit_rows += 1
                _save(conn, res, kind='bulk', bulk_id=job['id'], customer_ref=(r.get('reference') or '')[:200] or None)
        finally:
            _release_engine()
        conn.execute('UPDATE vessel_bulk_jobs SET hit_rows = %s WHERE id = %s', (hit_rows, job['id']))
        conn.commit()
        _audit('Vessel bulk screening', f'{fs.filename}: {len(rows)} rows, {hit_rows} with hits')
        return redirect(url_for('vessels.bulk_result', job_id=job['id']))
    return render_template('vessels/bulk.html', max_rows=BULK_MAX_ROWS)


def _bulk_rows(job_id):
    conn = _conn()
    job = conn.execute('SELECT * FROM vessel_bulk_jobs WHERE id = %s', (job_id,)).fetchone()
    if not job:
        abort(404)
    if not is_site_admin() and job['user_id'] != current_user.id and not current_user.can_edit('vessels'):
        abort(403)
    rows = conn.execute('SELECT id, query, result, tier, customer_ref FROM vessel_screenings WHERE bulk_id = %s '
                        'ORDER BY id', (job_id,)).fetchall()
    out = []
    for r in rows:
        res = r['result'] if isinstance(r['result'], dict) else json.loads(r['result'])
        out.append({'id': r['id'], 'ref': r['customer_ref'], 'q': res['query'], 'tier': r['tier'], 'res': res})
    return job, out


@vessels_bp.route('/bulk/<int:job_id>')
@login_required
@permission_required('vessels', level='view')
def bulk_result(job_id):
    job, rows = _bulk_rows(job_id)
    return render_template('vessels/bulk_result.html', job=job, rows=rows)


@vessels_bp.route('/bulk/<int:job_id>.csv')
@login_required
@permission_required('vessels', level='view')
def bulk_csv(job_id):
    job, rows = _bulk_rows(job_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['reference', 'name', 'imo', 'mmsi', 'flag', 'owner', 'result', 'score', 'top_hit', 'top_hit_imo',
                'explanation', 'risk_score', 'risk', 'screening_id'])
    for r in rows:
        top = (r['res']['hits'] or [{}])[0]
        w.writerow([r['ref'] or '', r['q'].get('name') or '', r['q'].get('imo') or '', r['q'].get('mmsi') or '',
                    r['q'].get('flag') or '', r['q'].get('owner') or '', r['tier'], r['res']['score'],
                    top.get('name') or '', top.get('imo') or '', '; '.join(top.get('explanation') or []),
                    r['res']['risk']['score'], '; '.join(r['res']['risk']['lines']), r['id']])
    return Response('﻿' + buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=vessel_bulk_{job_id}.csv'})


# --------------------------------------------------------------------------- Vessels Database
PAGE = 50


@vessels_bp.route('/database')
@login_required
@permission_required('vessels', level='view')
def database():
    conn = _conn()
    q = (request.args.get('q') or '').strip()
    flag = (request.args.get('flag') or '').strip()
    vtype = (request.args.get('type') or '').strip()
    measure = (request.args.get('measure') or '').strip()
    try:
        page = max(1, int(request.args.get('page') or 1))
    except ValueError:
        page = 1
    inc_os = VS.include_opensanctions(conn)
    where = ["w.is_active = 1", "w.entity_type = 'VESSEL'"]
    params = []
    if not inc_os:
        where.append("w.source <> ALL(%s)")
        params.append(list(VS.OPENSANCTIONS_SOURCES))
    ranked_ids = None
    if q:
        d = VU.digits_only(q)
        if d and len(d) in (7, 9) and len(d) >= len(q.replace(' ', '')) - 4:
            kind = 'IMO' if len(d) == 7 else 'MMSI'
            where.append("w.id IN (SELECT watchlist_id FROM vessel_identifier WHERE kind = %s AND value_norm = %s)")
            params += [kind, d]
        else:
            cands = VS.load_candidates(conn)
            scored = []
            for c in VE._prefilter(q, cands, limit=200):
                s, nm, _ = VE.best_name(q, c['names'])
                if s >= 65:
                    scored.append((s, c['watchlist_id']))
            scored.sort(reverse=True)
            ranked_ids = [w for _, w in scored[:500]]
            where.append('w.id = ANY(%s)')
            params.append(ranked_ids or [0])
    if flag:
        where.append('lower(p.current_flag) = lower(%s)')
        params.append(flag)
    if vtype:
        where.append('p.vessel_type ILIKE %s')
        params.append('%' + vtype.replace('%', '') + '%')
    if measure:
        where.append('p.measures LIKE %s')
        params.append('%"' + measure.replace('%', '').replace('"', '') + '"%')
    w_sql = ' AND '.join(where)
    total = conn.execute(f"""SELECT count(*) AS n FROM screening_watchlist w JOIN vessel_profile p
                             ON p.watchlist_id = w.id WHERE {w_sql}""", params).fetchone()['n']
    rows = conn.execute(f"""SELECT w.id, w.full_name, w.source, p.imo, p.imo_valid, p.mmsi, p.vessel_type,
                                   p.current_flag, p.year_built, p.measures, p.flag_history, p.previous_names
                            FROM screening_watchlist w JOIN vessel_profile p ON p.watchlist_id = w.id
                            WHERE {w_sql} ORDER BY w.full_name LIMIT %s OFFSET %s""",
                        params + [PAGE if ranked_ids is None else 500, 0 if ranked_ids is not None else (page - 1) * PAGE]
                        ).fetchall()
    items = [dict(r, measures=VS._j(r['measures'], []), flag_history=VS._j(r['flag_history'], []),
                  previous_names=VS._j(r['previous_names'], [])) for r in rows]
    if ranked_ids is not None:
        order = {w: i for i, w in enumerate(ranked_ids)}
        items.sort(key=lambda r: order.get(r['id'], 1e9))
        total = len(items)
    stats = _db_stats(conn, inc_os)
    return render_template('vessels/database.html', items=items, total=total, page=page, page_size=PAGE,
                           q=q, flag=flag, vtype=vtype, measure=measure, stats=stats, ranked=ranked_ids is not None)


def _db_stats(conn, inc_os):
    excl = '' if inc_os else "AND w.source <> ALL(%s)"
    p = [] if inc_os else [list(VS.OPENSANCTIONS_SOURCES)]
    base = f"FROM screening_watchlist w JOIN vessel_profile p ON p.watchlist_id = w.id WHERE w.is_active = 1 {excl}"
    tot = conn.execute(f"SELECT count(*) AS n, count(p.imo) AS with_imo {base}", p).fetchone()
    flags = conn.execute(f"""SELECT p.current_flag AS flag, count(*) AS n {base} AND p.current_flag IS NOT NULL
                             GROUP BY 1 ORDER BY 2 DESC LIMIT 12""", p).fetchall()
    types = conn.execute(f"""SELECT p.vessel_type AS type, count(*) AS n {base} AND p.vessel_type IS NOT NULL
                             GROUP BY 1 ORDER BY 2 DESC LIMIT 12""", p).fetchall()
    meas = {}
    for r in conn.execute(f"SELECT p.measures {base}", p).fetchall():
        for m in VS._j(r['measures'], []) or []:
            meas[m] = meas.get(m, 0) + 1
    return {'total': tot['n'], 'with_imo': tot['with_imo'], 'flags': flags, 'types': types,
            'measures': sorted(meas.items(), key=lambda x: -x[1])}


@vessels_bp.route('/database/<int:wid>')
@login_required
@permission_required('vessels', level='view')
def profile(wid):
    conn = _conn()
    row = conn.execute("""SELECT w.id, w.full_name, w.aliases, w.full_name_arabic, w.source, w.source_id,
                                 w.is_active, w.list_type, w.first_seen, w.last_seen, w.legal_status, w.properties,
                                 w.details, p.*
                          FROM screening_watchlist w JOIN vessel_profile p ON p.watchlist_id = w.id
                          WHERE w.id = %s""", (wid,)).fetchone()
    if not row:
        abort(404)
    if not VS.include_opensanctions(conn) and row['source'] in VS.OPENSANCTIONS_SOURCES:
        abort(404)
    idents = conn.execute("""SELECT kind, value_norm, is_current, check_ok FROM vessel_identifier
                             WHERE watchlist_id = %s ORDER BY kind, is_current DESC""", (wid,)).fetchall()
    parties = VS.party_links(conn, [wid]).get(wid, [])
    # the same ship on other lists (same IMO)
    same = []
    if row['imo']:
        same = conn.execute("""SELECT w.id, w.full_name, w.source FROM vessel_identifier i
                               JOIN screening_watchlist w ON w.id = i.watchlist_id
                               WHERE i.kind = 'IMO' AND i.value_norm = %s AND w.id <> %s AND w.is_active = 1""",
                            (row['imo'], wid)).fetchall()
    props = VS._j(row['properties'], {}) or {}
    v = dict(row, aliases=VS._j(row['aliases'], []) or [], measures=VS._j(row['measures'], []) or [],
             flag_history=VS._j(row['flag_history'], []) or [], previous_names=VS._j(row['previous_names'], []) or [])
    internal = {'source': row['source'], 'source_id': row['source_id'],
                'programs': props.get('programs') or props.get('regime'),
                'remarks': props.get('remarks') or props.get('other_information')} if is_site_admin() else None
    return render_template('vessels/profile.html', v=v, idents=idents, parties=parties, same=same,
                           internal=internal)
