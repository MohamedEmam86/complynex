# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Vessel screening pages (V3): screen one ship, bulk file (CSV / Excel, per-row results), history and open
alerts, validation of each hit (true / false match with a mandatory reason and comment), the vessel
whitelist (cleared ships, re-opened when the name / flag / owner changes), the PDF report, the flag-risk
reference and the ComplyNex Vessels Database (browse / search every listed ship).

Access: users.perm_vessels (user form): view = screen and browse, edit = validate hits, bulk files and the
whitelist. Site administrators have both. Clients see "Official sanctions lists" (or ban / exclusion lists); the real list is
shown to the platform superadmin only (vessel_store.can_see_sources) - never in PDFs, exports or the API.
The system alerts and records; it never freezes or blocks anything (actions happen outside the system).
"""
import csv
import io
import json
import logging
from functools import wraps

from flask import (Blueprint, Response, abort, flash, redirect, render_template, request, send_file, url_for)
from flask_babel import gettext
from flask_login import current_user, login_required

from access.registry import mark
from database.db import get_db
from screening import vessel_engine as VE
from screening import vessel_store as VS
from screening import vessel_utils as VU
from screening import vessel_guidance as VG
from screening import vessel_provenance as VP
from screening import vessel_regimes as VR
from utils.decorators import permission_required

logger = logging.getLogger(__name__)

vessels_bp = Blueprint('vessels', __name__, url_prefix='/screening/vessels')

BULK_MAX_ROWS = 200      # screened in the request: kept well inside the worker timeout
BULK_OWNER_MAX = 25      # the owner layer runs the full person / entity engine per row
PAGE = 50

# reason codes for the validation of a hit: (code, English, Arabic, decision it fits)
REASONS = [
    ('identifier_differs', 'IMO / MMSI differs', 'رقم IMO أو MMSI مختلف', 'false_match'),
    ('name_only', 'Name similarity only', 'تشابه في الاسم فقط', 'false_match'),
    ('number_differs', 'Different number in the name', 'رقم مختلف في الاسم', 'false_match'),
    ('different_ship_type', 'Different ship type / tonnage / build year', 'نوع أو حمولة أو سنة بناء مختلفة', 'false_match'),
    ('different_owner', 'Different owner / operator', 'مالك أو مشغّل مختلف', 'false_match'),
    ('identifier_matches', 'Same IMO / MMSI', 'نفس رقم IMO أو MMSI', 'true_match'),
    ('name_and_details_match', 'Name and ship details match', 'الاسم وبيانات السفينة متطابقة', 'true_match'),
    ('owner_matches', 'Owner / operator is listed', 'المالك أو المشغّل مدرج', 'true_match'),
    ('other', 'Other (see comment)', 'أخرى (انظر التعليق)', 'any'),
]
REASON_CODES = {c for c, *_ in REASONS}
MEASURES = {'asset_freeze': ('Asset freeze', 'تجميد أصول'), 'port_ban': ('Port entry ban', 'حظر دخول الموانئ'),
            'deflag': ('De-flagging', 'سحب العلم'), 'chartering_ban': ('Chartering ban', 'حظر التأجير'),
            'shipping_sanctions': ('Shipping sanctions', 'عقوبات شحن'),
            'trade_sanctions': ('Trade sanctions', 'عقوبات تجارية'), 'services_ban': ('Services ban', 'حظر الخدمات')}
TIERS = ('CONFIRMED', 'POTENTIAL', 'LOW', 'CLEAR', 'INCOMPLETE')
RISK_LINE_LABELS = {
    'psc_detained': ('Port-state-control record', 'سجل رقابة دولة الميناء'),
    'psc_repeated': ('Several port-state-control records', 'عدة سجلات رقابة دولة الميناء'),
    'foc': ('Flag of convenience', 'علم مواءمة'), 'high_risk_flag': ('High-risk flag', 'علم عالي المخاطر'),
    'false_flag': ('False flag', 'علم مزيف'), 'flag_changes': ('Several flag changes', 'تغيير العلم عدة مرات'),
    'renamed': ('Renamed', 'تغيير الاسم'), 'invalid_imo': ('IMO fails its check digit', 'رقم IMO غير صحيح'),
    'owner_listed': ('Owner / operator listed', 'المالك أو المشغّل مدرج'),
    'multi_list': ('On several lists', 'مدرجة في عدة قوائم'),
}
RISK_BAND_LABELS = {'high': ('High', 'مرتفع'), 'medium': ('Medium', 'متوسط'), 'low': ('Low', 'منخفض'),
                    'none': ('None', 'لا يوجد')}
ROLE_LABELS = {'owner': ('owner', 'مالك'), 'operator': ('operator', 'مشغّل'), 'manager': ('manager', 'مدير'),
               'owner_operator': ('owner / operator', 'مالك / مشغّل'),
               'former_owner_operator': ('former owner / operator', 'مالك / مشغّل سابق'),
               'beneficial_interest': ('beneficial interest', 'مصلحة منتفعة'), 'linked': ('linked', 'مرتبط')}


def _lang():
    try:
        from flask_babel import get_locale
        return 'ar' if str(get_locale()) == 'ar' else 'en'
    except Exception:
        return 'en'


def _pick(pair):
    return pair[1] if _lang() == 'ar' else pair[0]


def is_site_admin():
    return getattr(current_user, 'role', '') in ('admin', 'superadmin', 'it_admin') or \
        (hasattr(current_user, 'is_admin') and current_user.is_admin())


def is_superadmin():
    """The flag-risk reference is shared by every tenant: only the platform superadmin changes it."""
    return getattr(current_user, 'role', '') == 'superadmin'


def can_decide():
    return is_site_admin() or current_user.can_edit('vessels')


def sees_team():
    """Colleagues' screenings, bulk jobs and whitelist entries ('vessels.team' in the access matrix). Old rule:
    site administrators and editors. A restricted (external) user only ever sees their own."""
    from access import service as AS
    return AS.team_view(current_user, 'vessels.team', is_site_admin() or current_user.can_edit('vessels'))


def vessels_required(level='view'):
    """users.perm_vessels (site administrators always); otherwise refused like every other module."""
    def deco(f):
        guarded = permission_required('vessels', level=level)(f)

        @wraps(f)
        def wrapped(*a, **kw):
            # site administrators (admin, superadmin, it_admin) always - the same rule as is_site_admin();
            # only the superadmin sees the real lists (vessel_store.can_see_sources)
            if getattr(current_user, 'is_authenticated', False) and is_site_admin():
                return f(*a, **kw)
            return guarded(*a, **kw)
        # the rule, for the access registry (access/registry.py)
        return mark(('any', [('role', ('admin', 'superadmin', 'it_admin')), ('perm', 'vessels', level)]))(wrapped)
    return deco


def can_db(user=None):
    """The ComplyNex Vessels Database (browse every listed ship) is its own permission, users.perm_vessels_db,
    off by default for every role but the superadmin (owner decision: the list is not for every user)."""
    u = user or current_user
    if not getattr(u, 'is_authenticated', False):
        return False
    if getattr(u, 'role', '') == 'superadmin':
        return True
    return (getattr(u, 'perm_vessels_db', None) or 'none') in ('view', 'use', 'edit', 'admin')


def vessels_db_required(f):
    @wraps(f)
    def wrapped(*a, **kw):
        if not can_db():
            _audit('Vessels Database access refused', request.path)
            abort(403)
        return f(*a, **kw)
    return mark(('any', [('role', ('superadmin',)), ('col', 'perm_vessels_db', ('view', 'use', 'edit', 'admin'))]))(wrapped)


def list_label(source):
    """What the page shows for a list: generic for every client user, the real source for the superadmin."""
    return VS.list_label(source, _lang())


def sources_label(h):
    srcs = (h or {}).get('sources') or ([h.get('source')] if (h or {}).get('source') else [])
    if VS.can_see_sources():
        return ', '.join(srcs) or '-'
    if (h or {}).get('alert_type') == 'ban':
        return _pick((VS.GENERIC_BAN_LABEL, VS.GENERIC_BAN_LABEL_AR))
    return VS.list_label(None, _lang())


@vessels_bp.app_context_processor
def _vessel_helpers():
    from screening import vessel_flags as VF
    return {'vessel_list_label': list_label, 'vessel_sources_label': sources_label, 'vessel_can_db': can_db,
            'vessel_can_see_sources': VS.can_see_sources,
            'vessel_measure_label': lambda m: _pick(MEASURES.get(m, (m, m))),
            'vessel_reasons': [(c, _pick((en, ar)), d) for c, en, ar, d in REASONS],
            'vessel_reason_label': lambda c: _pick(next(((en, ar) for cc, en, ar, _ in REASONS if cc == c), (c, c))),
            'vessel_text': lambda items: VE.text(items, _lang()),
            'vessel_category': lambda lt: VS.category_label(lt, _lang()),
            'vessel_flag': lambda f: VF.name(f, _lang()) if f else '',
            'vessel_risk_line': lambda c: _pick(RISK_LINE_LABELS.get(c, (c, c))),
            'vessel_risk_band': lambda s: VS.risk_band(s),
            'vessel_risk_band_label': lambda b: _pick(RISK_BAND_LABELS.get(b, (b, b))),
            'vessel_role': lambda r: _pick(ROLE_LABELS.get(r, (r or '', r or ''))),
            'vessel_regime': lambda c: VR.label(c, _lang()),
            'vessel_status': lambda cls: _pick(VP.LABELS.get(cls or VP.SANCTION, (cls, cls))),
            'vessel_verdict': lambda res: VG.verdict(res, _lang()),
            'vessel_next_steps': lambda res: VG.next_steps(res, _lang()),
            'vessel_field': lambda k: _pick(FIELD_LABELS.get(k, (k, k))),
            'vessel_pick': _pick}


FIELD_LABELS = {'current_flag': ('Flag state', 'دولة العلم'), 'flag_history': ('Former flags', 'الأعلام السابقة'),
                'previous_names': ('Former names', 'الأسماء السابقة'), 'provenance': ('Status', 'الحالة'),
                'regimes': ('Regime', 'نظام العقوبات'), 'measures': ('Measures', 'الإجراءات'), 'imo': ('IMO number', 'رقم IMO'),
                'mmsi': ('MMSI', 'MMSI'), 'vessel_type': ('Vessel type', 'نوع السفينة'),
                'name': ('Name', 'الاسم'), 'IMO number': ('IMO number', 'رقم IMO'), 'MMSI': ('MMSI', 'MMSI'),
                'call sign': ('Call sign', 'نداء الاتصال'), 'flag': ('Flag state', 'دولة العلم'),
                'owner': ('Owner / operator', 'المالك / المشغّل'), 'type': ('Vessel type', 'نوع السفينة')}


def _conn():
    return get_db()


def _form_query(form):
    return {k: (form.get(k) or '').strip()[:300] for k in
            ('name', 'imo', 'mmsi', 'call_sign', 'flag', 'flags_past', 'owner', 'vessel_type')}


def _screen(form, conn, with_owner=True):
    q = _form_query(form)
    return VE.screen_vessel(
        name=q['name'], imo=q['imo'], mmsi=q['mmsi'], call_sign=q['call_sign'], flag=q['flag'],
        flags_past=q['flags_past'], owner=q['owner'], vessel_type=q['vessel_type'], conn=conn,
        screen_party=VE.party_screener() if (with_owner and q['owner']) else None)


def _release_engine():
    try:
        from screening.routes import get_engine
        from api.screening_v1 import _release_engine_conn
        _release_engine_conn(get_engine())
    except Exception:
        pass


def save_screening(conn, res, user_id, kind='single', bulk_id=None, customer_ref=None):
    row = conn.execute("""INSERT INTO vessel_screenings (user_id, kind, bulk_id, customer_ref, query, result, tier,
                                                         hit_count)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                       (user_id, kind, bulk_id, customer_ref,
                        json.dumps(res['query'], ensure_ascii=False), json.dumps(res, ensure_ascii=False, default=str),
                        res['tier'], len(res['hits']) + len(res['owner_hits']) + len(res.get('ban_hits') or []))).fetchone()
    conn.commit()
    return row['id']


def _audit(action, details, item_id=None):
    try:
        from models.audit import AuditLog
        AuditLog.log(current_user.id, action, 'Vessel screening', item_id, details, request.remote_addr)
    except Exception:
        pass


def _query_label(q):
    return q.get('name') or ('IMO ' + q['imo'] if q.get('imo') else None) or q.get('mmsi') or \
        q.get('call_sign') or q.get('owner') or '-'


# --------------------------------------------------------------------------- screen one ship
@vessels_bp.route('/', methods=['GET'])
@login_required
@vessels_required('view')
def index():
    return redirect(url_for('vessels.screen'))


@vessels_bp.route('/screen', methods=['GET', 'POST'])
@login_required
@vessels_required('view')
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
        sid = save_screening(conn, res, current_user.id,
                             customer_ref=(f.get('customer_ref') or '').strip()[:200] or None)
        _audit('Vessel screened', f"{_query_label(res['query'])} - {res['tier']} "
                                  f"({len(res['hits'])} ship hits, {len(res['owner_hits'])} owner hits)", sid)
        return redirect(url_for('vessels.result', sid=sid))
    return render_template('vessels/screen.html', form={})


def _load_screening(sid):
    conn = _conn()
    row = conn.execute('SELECT * FROM vessel_screenings WHERE id = %s', (sid,)).fetchone()
    if not row:
        abort(404)
    if row['user_id'] != current_user.id and not sees_team():
        abort(403)
    res = row['result'] if isinstance(row['result'], dict) else json.loads(row['result'])
    return conn, row, res


def _decisions(conn, sid):
    """Latest decision per hit ('ship:<listed_key>' / 'owner:<watchlist_id or name>') + full history."""
    rows = conn.execute("""SELECT d.*, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS decided_by_name
                           FROM vessel_hit_decisions d LEFT JOIN users u ON u.id = d.decided_by
                           WHERE d.screening_id = %s ORDER BY d.decided_at, d.id""", (sid,)).fetchall()
    latest = {}
    for d in rows:
        latest[_hit_key(d['hit_kind'], d['listed_key'] or ('WL:%s' % d['watchlist_id']))] = d
    return latest, rows


def _hit_key(kind, key):
    return f'{kind}:{key}'


def owner_key(o):
    """Key of an owner hit (fits vessel_hit_decisions.listed_key, 40 characters): the listed record's id, else
    the name, hashed when it is long."""
    if o.get('watchlist_id'):
        return 'WL:%s' % o['watchlist_id']
    k = 'NAME:' + VS.party_key(o.get('name'))
    if len(k) > 40:
        import hashlib
        k = 'NAMEH:' + hashlib.sha1(k.encode('utf-8')).hexdigest()[:32]
    return k


@vessels_bp.route('/result/<int:sid>')
@login_required
@vessels_required('view')
def result(sid):
    conn, row, res = _load_screening(sid)
    latest, history = _decisions(conn, sid)
    for h in (res.get('hits') or []) + (res.get('ban_hits') or []):
        h.setdefault('listed_key', VS.listed_key(h))
    open_n = sum(1 for h in (res.get('hits') or []) + (res.get('ban_hits') or []) if _hit_key('ship', h['listed_key']) not in latest) + \
        sum(1 for o in res.get('owner_hits') or [] if _hit_key('owner', owner_key(o)) not in latest)
    return render_template('vessels/result.html', sid=sid, row=row, res=res, decisions=latest, history=history,
                           open_n=open_n, can_decide=can_decide(), owner_key=owner_key)


@vessels_bp.route('/result/<int:sid>/news')
@login_required
@vessels_required('view')
def result_news(sid):
    """News about the ship of a screening (the listed ship found, else the ship screened), as JSON for the
    result page. Read-only for the screening; the news cache is refreshed after its TTL."""
    from flask import jsonify
    from screening import vessel_news as VN
    conn, row, res = _load_screening(sid)
    ships = (res.get('hits') or []) + (res.get('ban_hits') or [])
    q = res.get('query') or {}
    name, imo = (ships[0].get('name'), ships[0].get('imo')) if ships else (q.get('name'), q.get('imo'))
    if not (name or imo):
        return jsonify({'items': [], 'error': None, 'ship': None})
    try:
        out = VN.news_for(conn, name=name, imo=imo)
    except Exception as e:
        logger.warning(f'[VESSELS] news failed: {e}')
        out = {'items': [], 'error': 'unavailable'}
    out['ship'] = {'name': name, 'imo': imo}
    why = {'imo': _pick(('IMO number in the article', 'رقم IMO مذكور في الخبر')),
           'name': _pick(('Ship name with maritime context', 'اسم السفينة في سياق بحري'))}
    for it in out.get('items') or []:
        it['why_label'] = why.get(it.get('why'), '')
    return jsonify(out)


@vessels_bp.route('/result/<int:sid>/decide', methods=['POST'])
@login_required
@vessels_required('edit')
def decide(sid):
    conn, row, res = _load_screening(sid)
    kind = 'owner' if request.form.get('hit_kind') == 'owner' else 'ship'
    key = (request.form.get('hit_key') or '').strip()
    if kind == 'ship':
        hit = next((h for h in (res.get('hits') or []) + (res.get('ban_hits') or []) if (h.get('listed_key') or VS.listed_key(h)) == key), None)
    else:
        hit = next((o for o in res.get('owner_hits') or [] if owner_key(o) == key), None)
    decision = request.form.get('decision')
    reason = request.form.get('reason')
    comment = (request.form.get('comment') or '').strip()
    fits = next((d for c, _, _, d in REASONS if c == reason), None)
    if not hit or decision not in ('true_match', 'false_match') or reason not in REASON_CODES or \
            fits not in ('any', decision):
        flash(gettext('Choose the decision and a reason that fits it.'), 'danger')
        return redirect(url_for('vessels.result', sid=sid))
    if len(comment) < 5:
        flash(gettext('A comment explaining the decision is required (at least 5 characters).'), 'danger')
        return redirect(url_for('vessels.result', sid=sid))
    q = res['query']
    qkey = res.get('query_key') or VU.query_key(q.get('name'), q.get('imo'), q.get('mmsi'), q.get('flag'))
    qfp = res.get('query_fp') or VS.query_fingerprint(q)
    lfp = hit.get('listed_fp') if kind == 'ship' else VU.fingerprint(hit.get('name'))
    d = conn.execute("""INSERT INTO vessel_hit_decisions (screening_id, watchlist_id, decision, reason, comment, query_key,
                                                          candidate_fp, decided_by, listed_key, query_fp, hit_kind)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                     (sid, hit.get('watchlist_id'), decision, reason, comment[:4000], qkey, lfp, current_user.id,
                      key[:40], qfp, kind)).fetchone()
    wl_note = ''
    if kind == 'ship' and decision == 'false_match' and request.form.get('whitelist') == '1' and lfp:
        conn.execute("""UPDATE vessel_whitelist SET status = 'revoked', revoked_by = %s, revoked_at = now(),
                               revoke_reason = 'replaced by a new clearance'
                        WHERE query_key = %s AND listed_key = %s AND status IN ('active', 'reopened')""",
                     (current_user.id, qkey, key))
        conn.execute("""INSERT INTO vessel_whitelist (query_key, listed_key, watchlist_id, listed_name, listed_fp,
                                                      query_fp, query_label, decision_id, reason, comment, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (query_key, listed_key) WHERE status = 'active' DO NOTHING""",
                     (qkey, key, hit.get('watchlist_id'), hit.get('name'), lfp, qfp, _query_label(q), d['id'],
                      reason, comment[:4000], current_user.id))
        wl_note = ' + whitelist'
    elif kind == 'ship' and decision == 'true_match':
        # a true match ends any clearance of the same pair
        conn.execute("""UPDATE vessel_whitelist SET status = 'revoked', revoked_by = %s, revoked_at = now(),
                               revoke_reason = 'validated as a true match'
                        WHERE query_key = %s AND listed_key = %s AND status IN ('active', 'reopened')""",
                     (current_user.id, qkey, key))
    conn.commit()
    _audit('Vessel hit validated', f'screening {sid}: {kind} hit "{hit.get("name")}" ({key}) - {decision}, '
                                   f'reason {reason}{wl_note}: {comment[:300]}', sid)
    flash(gettext('Decision recorded.'), 'success')
    return redirect(url_for('vessels.result', sid=sid))


@vessels_bp.route('/result/<int:sid>/pdf')
@login_required
@vessels_required('view')
def result_pdf(sid):
    conn, row, res = _load_screening(sid)
    latest, history = _decisions(conn, sid)
    for h in (res.get('hits') or []) + (res.get('ban_hits') or []):
        h.setdefault('listed_key', VS.listed_key(h))
    from datetime import datetime
    html = render_template('vessels/report_pdf.html', sid=sid, row=row, res=res, decisions=latest,
                           history=history, owner_key=owner_key, generated_at=datetime.now(),
                           generated_by=f'{current_user.first_name or ""} {current_user.last_name or ""}'.strip(),
                           generic_label=VS.list_label(None, _lang(), user=False))
    try:
        from weasyprint import HTML
        pdf = HTML(string=html, base_url=request.host_url).write_pdf()
    except Exception as e:
        logger.error(f'[VESSELS] PDF failed: {e}')
        flash(gettext('The PDF could not be produced.'), 'danger')
        return redirect(url_for('vessels.result', sid=sid))
    _audit('Vessel screening PDF', f'screening {sid}', sid)
    return send_file(io.BytesIO(pdf), mimetype='application/pdf', as_attachment=True,
                     download_name=f'vessel_screening_{sid}.pdf')


HISTORY_PAGE = 100


@vessels_bp.route('/history')
@login_required
@vessels_required('view')
def history():
    conn = _conn()
    status = request.args.get('status') or ''
    tier = request.args.get('tier') or ''
    where, params = [], []
    if not sees_team():
        where.append('s.user_id = %s')
        params.append(current_user.id)
    if tier in TIERS:
        where.append('s.tier = %s')
        params.append(tier)
    try:
        page = max(1, min(int(request.args.get('page') or 1), 10000))
    except ValueError:
        page = 1
    w = ('WHERE ' + ' AND '.join(where)) if where else ''
    outer = 'WHERE x.hit_count > x.decided' if status == 'open' else ''
    rows = conn.execute(f"""SELECT * FROM (
                              SELECT s.id, s.kind, s.query, s.tier, COALESCE(s.hit_count, 0) AS hit_count, s.created_at,
                                     s.customer_ref, s.bulk_id,
                                     TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS user_name,
                                     (SELECT count(DISTINCT d.hit_kind || ':' || coalesce(d.listed_key, d.watchlist_id::text))
                                        FROM vessel_hit_decisions d WHERE d.screening_id = s.id) AS decided
                              FROM vessel_screenings s LEFT JOIN users u ON u.id = s.user_id {w}) x {outer}
                            ORDER BY x.id DESC LIMIT %s OFFSET %s""",
                        params + [HISTORY_PAGE + 1, (page - 1) * HISTORY_PAGE]).fetchall()
    more = len(rows) > HISTORY_PAGE
    items = []
    for r in rows[:HISTORY_PAGE]:
        q = r['query'] if isinstance(r['query'], dict) else json.loads(r['query'] or '{}')
        items.append(dict(r, q=q, open=max(0, int(r['hit_count'] or 0) - int(r['decided'] or 0))))
    return render_template('vessels/history.html', items=items, status=status, tier=tier, tiers=TIERS,
                           page=page, more=more)


# --------------------------------------------------------------------------- whitelist
@vessels_bp.route('/whitelist')
@login_required
@vessels_required('edit')
def whitelist():
    status = request.args.get('status') or ''
    params, cond = [], []
    if status in ('active', 'reopened', 'revoked'):
        cond.append('w.status = %s')
        params.append(status)
    if not sees_team():                         # own clearances only
        cond.append('w.created_by = %s')
        params.append(current_user.id)
    w = ('WHERE ' + ' AND '.join(cond)) if cond else ''
    rows = _conn().execute(f"""SELECT w.*, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS by_name
                               FROM vessel_whitelist w LEFT JOIN users u ON u.id = w.created_by {w}
                               ORDER BY (w.status = 'reopened') DESC, w.created_at DESC LIMIT 500""", params).fetchall()
    return render_template('vessels/whitelist.html', items=rows, status=status)


@vessels_bp.route('/whitelist/<int:wid>/revoke', methods=['POST'])
@login_required
@vessels_required('edit')
def whitelist_revoke(wid):
    reason = (request.form.get('reason') or '').strip()
    if len(reason) < 5:
        flash(gettext('A reason is required (at least 5 characters).'), 'danger')
        return redirect(url_for('vessels.whitelist'))
    conn = _conn()
    r = conn.execute("""UPDATE vessel_whitelist SET status = 'revoked', revoked_by = %s, revoked_at = now(),
                               revoke_reason = %s WHERE id = %s AND status <> 'revoked'
                               AND (%s OR created_by = %s) RETURNING query_label, listed_name""",
                     (current_user.id, reason[:1000], wid, sees_team(), current_user.id)).fetchone()
    conn.commit()
    if r:
        _audit('Vessel whitelist revoked', f'entry {wid}: {r["query_label"]} / {r["listed_name"]}: {reason[:300]}', wid)
        flash(gettext('The clearance was revoked: the hit will alert again.'), 'success')
    return redirect(url_for('vessels.whitelist'))


# --------------------------------------------------------------------------- bulk
BULK_COLUMNS = ('reference', 'name', 'imo', 'mmsi', 'call_sign', 'flag', 'flags_past', 'owner', 'vessel_type')
_HEAD_ALIASES = {'vessel name': 'name', 'ship name': 'name', 'vessel': 'name', 'ship': 'name', 'imo number': 'imo',
                 'imo no': 'imo', 'call sign': 'call_sign', 'callsign': 'call_sign', 'flag state': 'flag',
                 'previous flags': 'flags_past', 'former flags': 'flags_past', 'operator': 'owner',
                 'owner / operator': 'owner', 'type': 'vessel_type', 'vessel type': 'vessel_type', 'ref': 'reference',
                 'customer_ref': 'reference', 'اسم السفينة': 'name', 'السفينة': 'name', 'رقم imo': 'imo',
                 'العلم': 'flag', 'المالك': 'owner', 'المرجع': 'reference', 'نداء الاتصال': 'call_sign',
                 'نوع السفينة': 'vessel_type'}


def _head(h):
    k = str(h or '').strip().lower().replace('﻿', '')
    return _HEAD_ALIASES.get(k, k.replace(' ', '_'))


def _template_rows():
    return [list(BULK_COLUMNS), ['REF-001', 'OCEAN GLORY', '9074729', '', '', 'Panama', 'Togo; Comoros', '',
                                 'Crude Oil Tanker'],
            ['REF-002', 'م/ن النور 2', '', '', '', 'مصر', '', '', '']]


@vessels_bp.route('/bulk/template')
@login_required
@vessels_required('view')
def bulk_template():
    if request.args.get('format') == 'xlsx':
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'vessels'
        for r in _template_rows():
            ws.append(r)
        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        return send_file(out, as_attachment=True, download_name='vessel_screening_template.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    buf = io.StringIO()
    csv.writer(buf).writerows(_template_rows())
    return Response('﻿' + buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=vessel_screening_template.csv'})


BULK_MAX_BYTES = 5 * 1024 * 1024           # the upload itself
BULK_MAX_XLSX_UNZIPPED = 40 * 1024 * 1024  # an .xlsx is a zip: its sheets may not unpack beyond this
BULK_MAX_COLS = 30
BULK_MAX_CELL = 300


class BulkTooLarge(ValueError):
    pass


def _bulk_bytes(fs):
    """The upload, refused beyond BULK_MAX_BYTES without reading more than that."""
    raw = fs.stream.read(BULK_MAX_BYTES + 1)
    if len(raw) > BULK_MAX_BYTES:
        raise BulkTooLarge('file')
    return raw


def read_bulk_rows(fs, max_rows=None):
    """[(row_no, {column: value})] of a CSV (UTF-8) or .xlsx file; header names in English or Arabic.
    Bounded before anything is parsed in full: file size, the unzipped size of an .xlsx, columns per row,
    cell length, and rows (stops at max_rows + 1 and raises BulkTooLarge)."""
    max_rows = max_rows or BULK_MAX_ROWS
    name = (fs.filename or '').lower()
    rows = []

    def take(n, head, values):
        values = list(values)[:BULK_MAX_COLS]
        r = {head[i]: ('' if v is None else str(v).strip()[:BULK_MAX_CELL]) for i, v in enumerate(values)
             if i < len(head)}
        if any((r.get(c) or '').strip() for c in BULK_COLUMNS):
            rows.append((n, r))
            if len(rows) > max_rows:
                raise BulkTooLarge('rows')

    if name.endswith('.xlsx'):
        import zipfile
        raw = _bulk_bytes(fs)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if sum(i.file_size for i in z.infolist()) > BULK_MAX_XLSX_UNZIPPED:
                raise BulkTooLarge('unzipped')
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            it = wb.active.iter_rows(values_only=True, max_col=BULK_MAX_COLS)
            head = [_head(h) for h in (next(it, None) or [])][:BULK_MAX_COLS]
            for n, r in enumerate(it, 2):
                take(n, head, r)
        finally:
            wb.close()
    elif name.endswith('.csv') or name.endswith('.txt'):
        raw = _bulk_bytes(fs)
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp1256', errors='replace')
        rdr = csv.reader(io.StringIO(text))
        head = [_head(h) for h in (next(rdr, None) or [])][:BULK_MAX_COLS]
        for n, r in enumerate(rdr, 2):
            take(n, head, r)
    else:
        raise ValueError('unsupported file type')
    return rows


@vessels_bp.route('/bulk', methods=['GET', 'POST'])
@login_required
@vessels_required('edit')
def bulk():
    if request.method == 'POST':
        fs = request.files.get('file')
        if not fs or not fs.filename:
            flash(gettext('Choose a CSV or Excel file.'), 'warning')
            return redirect(url_for('vessels.bulk'))
        try:
            rows = read_bulk_rows(fs)
        except BulkTooLarge as e:
            flash(gettext('The file is too large: up to %(n)s rows and %(mb)s MB per file.', n=BULK_MAX_ROWS,
                          mb=BULK_MAX_BYTES // (1024 * 1024)), 'warning')
            logger.info(f'[VESSELS] bulk file refused ({e})')
            return redirect(url_for('vessels.bulk'))
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
        # the owner layer runs the full person / entity engine: kept for files of up to BULK_OWNER_MAX rows
        with_owner = len(rows) <= BULK_OWNER_MAX
        if not with_owner and any((r.get('owner') or '').strip() for _, r in rows):
            flash(gettext('Owners were not screened (file over %(n)s rows): screen them with bulk name screening.',
                          n=BULK_OWNER_MAX), 'warning')
        try:
            for n, r in rows:
                if not any((r.get(c) or '').strip() for c in ('name', 'imo', 'mmsi', 'call_sign', 'owner')):
                    res = VE.screen_vessel(conn=conn)        # INCOMPLETE: nothing to screen on this row
                else:
                    res = _screen(r, conn, with_owner=with_owner)
                res['row_no'] = n
                if res['hits'] or res['owner_hits'] or res.get('ban_hits'):
                    hit_rows += 1
                save_screening(conn, res, current_user.id, kind='bulk', bulk_id=job['id'],
                               customer_ref=(r.get('reference') or '')[:200] or None)
        finally:
            _release_engine()
        conn.execute('UPDATE vessel_bulk_jobs SET hit_rows = %s WHERE id = %s', (hit_rows, job['id']))
        conn.commit()
        _audit('Vessel bulk screening', f'{fs.filename}: {len(rows)} rows, {hit_rows} with hits', job['id'])
        return redirect(url_for('vessels.bulk_result', job_id=job['id']))
    return render_template('vessels/bulk.html', max_rows=BULK_MAX_ROWS, owner_max=BULK_OWNER_MAX)


def _bulk_rows(job_id):
    conn = _conn()
    job = conn.execute('SELECT * FROM vessel_bulk_jobs WHERE id = %s', (job_id,)).fetchone()
    if not job:
        abort(404)
    if job['user_id'] != current_user.id and not sees_team():
        abort(403)
    rows = conn.execute("""SELECT s.id, s.query, s.result, s.tier, s.customer_ref,
                                  (SELECT count(DISTINCT d.hit_kind || ':' || coalesce(d.listed_key, d.watchlist_id::text))
                                     FROM vessel_hit_decisions d WHERE d.screening_id = s.id) AS decided
                           FROM vessel_screenings s WHERE s.bulk_id = %s ORDER BY s.id""", (job_id,)).fetchall()
    out = []
    for r in rows:
        res = r['result'] if isinstance(r['result'], dict) else json.loads(r['result'])
        out.append({'id': r['id'], 'ref': r['customer_ref'], 'q': res['query'], 'tier': r['tier'], 'res': res,
                    'row_no': res.get('row_no'), 'decided': r['decided']})
    return job, out


@vessels_bp.route('/bulk/<int:job_id>')
@login_required
@vessels_required('view')
def bulk_result(job_id):
    job, rows = _bulk_rows(job_id)
    counts = {t: sum(1 for r in rows if r['tier'] == t) for t in TIERS}
    return render_template('vessels/bulk_result.html', job=job, rows=rows, counts=counts)


def _export_rows(rows, lang='en'):
    """Bulk results as rows; the list behind a hit is never named (generic label)."""
    label = VS.list_label(None, lang, user=False)
    head = ['row', 'reference', 'name', 'imo', 'mmsi', 'flag', 'owner', 'result', 'score', 'top_hit', 'top_hit_imo',
            'top_hit_flag', 'measures', 'lists', 'explanation', 'owner_hit', 'ban_hit', 'risk_score', 'risk', 'warnings',
            'screening_id']
    out = [head]
    for r in rows:
        res = r['res']
        top = (res.get('hits') or [{}])[0]
        oh = (res.get('owner_hits') or [{}])[0]
        out.append([r.get('row_no') or '', r['ref'] or '', r['q'].get('name') or '', r['q'].get('imo') or '',
                    r['q'].get('mmsi') or '', r['q'].get('flag') or '', r['q'].get('owner') or '', r['tier'],
                    res.get('score'), top.get('name') or '', top.get('imo') or '', top.get('flag') or '',
                    ', '.join(top.get('measures') or []), label if (res.get('hits') or res.get('owner_hits') or res.get('ban_hits')) else '',
                    '; '.join(VE.text(top.get('explanation'), lang)), oh.get('name') or '',
                    ((res.get('ban_hits') or [{}])[0].get('name') or ''),
                    res['risk']['score'], '; '.join(VE.text(res['risk']['lines'], lang)),
                    '; '.join(VE.text(res.get('warnings'), lang)), r['id']])
    from utils.sheet_safe import row as safe_row      # formula injection: file and list text is untrusted
    return [safe_row(r) for r in out]


@vessels_bp.route('/bulk/<int:job_id>.csv')
@login_required
@vessels_required('view')
def bulk_csv(job_id):
    job, rows = _bulk_rows(job_id)
    buf = io.StringIO()
    csv.writer(buf).writerows(_export_rows(rows, _lang()))
    return Response('﻿' + buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=vessel_bulk_{job_id}.csv'})


@vessels_bp.route('/bulk/<int:job_id>.xlsx')
@login_required
@vessels_required('view')
def bulk_xlsx(job_id):
    job, rows = _bulk_rows(job_id)
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'results'
    for r in _export_rows(rows, _lang()):
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return send_file(out, as_attachment=True, download_name=f'vessel_bulk_{job_id}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# --------------------------------------------------------------------------- Vessels Database


def _db_filters(conn):
    a = request.args
    f = {'q': (a.get('q') or '').strip()[:200], 'flag': (a.get('flag') or '').strip()[:80],
         'type': (a.get('type') or '').strip()[:80], 'measure': (a.get('measure') or '').strip()[:40],
         'regime': (a.get('regime') or '').strip().upper()[:20], 'risk': (a.get('risk') or '').strip()[:10],
         'status': (a.get('status') or 'sanction').strip()[:10],
         'source': (a.get('source') or '').strip()[:40] if VS.can_see_sources() else ''}
    try:
        f['page'] = max(1, int(a.get('page') or 1))
    except ValueError:
        f['page'] = 1
    return f


@vessels_bp.route('/database')
@login_required
@vessels_db_required
def database():
    """One row per ship (the same IMO on several lists is one ship), searchable and filterable."""
    conn = _conn()
    f = _db_filters(conn)
    inc_os = VS.include_opensanctions(conn)
    where = ["w.is_active = 1", "w.entity_type = 'VESSEL'"]
    params = []
    if not inc_os:
        where.append("w.source <> ALL(%s)")
        params.append(list(VS.OPENSANCTIONS_SOURCES))
    st_sql, st_params = _status_sql(f['status'])
    where.append(st_sql)
    params += st_params
    ranked = None
    if f['q']:
        d = VU.digits_only(f['q'])
        if d and len(d) in (7, 9) and len(d) >= len(f['q'].replace(' ', '')) - 4:
            kind = 'IMO' if len(d) == 7 else 'MMSI'
            where.append("p.group_key IN (SELECT p2.group_key FROM vessel_identifier i JOIN vessel_profile p2 "
                         "ON p2.watchlist_id = i.watchlist_id WHERE i.kind = %s AND i.value_norm = %s)")
            params += [kind, d]
        else:
            cands = VS.load_candidates(conn)
            scored = {}
            for c in VE._prefilter(f['q'], cands, limit=200):
                s, nm, _ = VE.best_name(f['q'], c['names'])
                if s >= 70:
                    scored[c['group_key']] = max(scored.get(c['group_key'], 0), s)
            ranked = sorted(scored, key=lambda g: -scored[g])[:300]
            where.append('p.group_key = ANY(%s)')
            params.append(ranked or ['-'])
    if f['flag']:
        where.append('p.group_key IN (SELECT group_key FROM vessel_profile WHERE current_flag = %s)')
        params.append(VU.clean_flag(f['flag']) or f['flag'])
    if f['type']:
        where.append('p.vessel_type ILIKE %s')
        params.append('%' + f['type'].replace('%', '').replace('_', ' ') + '%')
    if f['measure']:
        where.append('p.measures LIKE %s')
        params.append('%"' + f['measure'].replace('%', '').replace('"', '') + '"%')
    if f['regime'] in VR.REGIMES:
        where.append('p.group_key IN (SELECT group_key FROM vessel_profile WHERE regimes LIKE %s)')
        params.append('%"' + f['regime'] + '"%')
    if f['source']:
        where.append('w.source = %s')
        params.append(f['source'])
    w_sql = ' AND '.join(where)
    having = ''
    hi, med = _band_limits()
    if f['risk'] == 'high':
        having = f'HAVING max(p.risk_score) >= {hi}'
    elif f['risk'] == 'medium':
        having = f'HAVING max(p.risk_score) >= {med} AND max(p.risk_score) < {hi}'
    elif f['risk'] == 'low':
        having = f'HAVING max(p.risk_score) < {med}'
    grouped = f"""SELECT p.group_key, min(w.id) AS id, count(*) AS records, count(DISTINCT w.source) AS lists,
                         max(p.risk_score) AS risk_score
                  FROM screening_watchlist w JOIN vessel_profile p ON p.watchlist_id = w.id
                  WHERE {w_sql} GROUP BY p.group_key {having}"""
    total = conn.execute(f'SELECT count(*) AS n FROM ({grouped}) g', params).fetchone()['n']
    if ranked is not None:
        rows = conn.execute(grouped, params).fetchall()
        order = {g: i for i, g in enumerate(ranked)}
        rows = sorted(rows, key=lambda r: order.get(r['group_key'], 1e9))
        rows = rows[(f['page'] - 1) * PAGE: f['page'] * PAGE]
    else:
        rows = conn.execute(f"""SELECT g.* FROM ({grouped}) g JOIN screening_watchlist w0 ON w0.id = g.id
                                ORDER BY upper(w0.full_name) LIMIT %s OFFSET %s""",
                            params + [PAGE, (f['page'] - 1) * PAGE]).fetchall()
    items = _ship_views(conn, [r['group_key'] for r in rows], {r['group_key']: r for r in rows})
    stats = _db_stats(conn, inc_os, f['status'])
    _audit('Vessels Database viewed', json.dumps({k: v for k, v in f.items() if v}, ensure_ascii=False)[:500])
    return render_template('vessels/database.html', items=items, total=total, page=f['page'], page_size=PAGE,
                           f=f, stats=stats, ranked=ranked is not None, regimes=VR.REGIMES, statuses=STATUSES)


def _ship_views(conn, group_keys, meta):
    """One merged view per ship group (all its list records)."""
    if not group_keys:
        return []
    cur = conn.execute("""SELECT w.id, w.full_name, w.source, w.list_type, w.aliases, p.*
                          FROM screening_watchlist w JOIN vessel_profile p ON p.watchlist_id = w.id
                          WHERE w.is_active = 1 AND p.group_key = ANY(%s)""", (list(group_keys),)).fetchall()
    by = {}
    for r in cur:
        by.setdefault(r['group_key'], []).append(r)
    out = []
    for gk in group_keys:
        recs = sorted(by.get(gk) or [], key=lambda r: (r['source'] in VS.OPENSANCTIONS_SOURCES, r['id']))
        if not recs:
            continue
        base = recs[0]
        v = {'id': base['id'], 'group_key': gk, 'name': base['full_name'],
             'imo': next((r['imo'] for r in recs if r['imo']), None),
             'imo_valid': next((r['imo_valid'] for r in recs if r['imo']), None),
             'mmsi': next((r['mmsi'] for r in recs if r['mmsi']), None),
             'vessel_type': next((r['vessel_type'] for r in recs if r['vessel_type']), None),
             'flag': next((r['current_flag'] for r in recs if r['current_flag']), None),
             'year_built': next((r['year_built'] for r in recs if r['year_built']), None),
             'flag_history': list(dict.fromkeys(x for r in recs for x in VS._j(r['flag_history'], []) or [])),
             'previous_names': list(dict.fromkeys(x for r in recs for x in VS._j(r['previous_names'], []) or [])),
             'measures': list(dict.fromkeys(x for r in recs for x in VS._j(r['measures'], []) or [])),
             'sources': sorted({r['source'] for r in recs}),
             'risk_score': max(int(r['risk_score'] or 0) for r in recs),
             'risk_lines': list(dict.fromkeys(x for r in recs for x in VS._j(r['risk_lines'], []) or [])),
             'regimes': sorted({x for r in recs for x in VS._j(r.get('regimes'), []) or []}),
             'provenance': max((r.get('provenance') or 'SANCTION' for r in recs), key=lambda x: VP.ORDER.get(x, 0)),
             'records': len(recs)}
        out.append(v)
    return out


STATUSES = (('sanction', ('Sanctioned ships', 'السفن الخاضعة لعقوبات')),
            ('ban', ('Banned / excluded ships', 'السفن المحظورة أو المستبعدة')),
            ('alerting', ('Sanctioned or banned', 'خاضعة لعقوبات أو محظورة')),
            ('all', ('All ship records, incl. risk-only', 'كل سجلات السفن بما فيها سجلات المخاطر فقط')))


def _status_sql(status):
    if status == 'ban':
        return "p.provenance = 'BAN'", []
    if status == 'alerting':
        return "p.provenance IN ('SANCTION', 'BAN')", []
    if status == 'all':
        return 'TRUE', []
    return "p.provenance = 'SANCTION'", []


def _band_limits():
    d = dict(VS.RISK_BANDS)
    return int(d['high']), int(d['medium'])


def _db_stats(conn, inc_os, status='sanction'):
    excl = '' if inc_os else "AND w.source <> ALL(%s)"
    p = [] if inc_os else [list(VS.OPENSANCTIONS_SOURCES)]
    st_sql, _ = _status_sql(status)
    base = (f"FROM screening_watchlist w JOIN vessel_profile p ON p.watchlist_id = w.id WHERE w.is_active = 1 {excl} "
            f"AND {st_sql}")
    hi, _m = _band_limits()
    tot = conn.execute(f"""SELECT count(*) AS ships, sum(records) AS records,
                                  count(*) FILTER (WHERE group_key LIKE 'IMO:%%') AS with_imo,
                                  count(*) FILTER (WHERE risk >= {hi}) AS high_risk
                           FROM (SELECT p.group_key, count(*) AS records, max(p.risk_score) AS risk {base}
                                 GROUP BY p.group_key) g""", p).fetchone()
    regimes = {}
    for r in conn.execute(f"SELECT p.group_key, p.regimes {base}", p).fetchall():
        for g in VS._j(r['regimes'], []) or []:
            regimes.setdefault(g, set()).add(r['group_key'])
    flags = conn.execute(f"""SELECT p.current_flag AS flag, count(DISTINCT p.group_key) AS n {base}
                             AND p.current_flag IS NOT NULL GROUP BY 1 ORDER BY 2 DESC""", p).fetchall()
    types = conn.execute(f"""SELECT p.vessel_type AS type, count(DISTINCT p.group_key) AS n {base}
                             AND p.vessel_type IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 12""", p).fetchall()
    meas = {}
    for r in conn.execute(f"SELECT p.group_key, p.measures {base}", p).fetchall():
        for m in VS._j(r['measures'], []) or []:
            meas.setdefault(m, set()).add(r['group_key'])
    sources = []
    if VS.can_see_sources():
        sources = conn.execute(f"SELECT w.source, count(*) AS n {base} GROUP BY 1 ORDER BY 2 DESC", p).fetchall()
    return {'ships': tot['ships'], 'records': tot['records'] or 0, 'with_imo': tot['with_imo'],
            'high_risk': tot['high_risk'], 'flags': flags, 'types': types,
            'regimes': sorted(((k, len(v)) for k, v in regimes.items()), key=lambda x: -x[1]),
            'measures': sorted(((k, len(v)) for k, v in meas.items()), key=lambda x: -x[1]), 'sources': sources}


@vessels_bp.route('/database/<int:wid>')
@login_required
@vessels_required('view')
def profile(wid):
    """A ship's profile: every list record of the same IMO merged; the records themselves (and their real
    sources) for the superadmin only."""
    conn = _conn()
    row = conn.execute("""SELECT p.group_key, w.source FROM screening_watchlist w JOIN vessel_profile p
                          ON p.watchlist_id = w.id WHERE w.id = %s""", (wid,)).fetchone()
    if not row:
        abort(404)
    # without the Vessels Database permission, a ship's profile opens only from a screening of the user's
    # that found it (?sid=): the officer sees the ship behind his own hit, never the whole list
    if not can_db():
        try:
            sid = int(request.args.get('sid') or 0)
        except ValueError:
            sid = 0
        if not sid:
            abort(403)
        _c, _row, res = _load_screening(sid)
        found = {m for h in (res.get('hits') or []) + (res.get('ban_hits') or [])
                 for m in ([h.get('watchlist_id')] + list(h.get('member_ids') or []))}
        if wid not in found and row['group_key'] not in {h.get('group_key') for h in
                                                          (res.get('hits') or []) + (res.get('ban_hits') or [])}:
            abort(403)
    _audit('Vessel profile viewed', f'listed ship {wid}', wid)
    inc_os = VS.include_opensanctions(conn)
    recs = conn.execute("""SELECT w.id, w.full_name, w.aliases, w.full_name_arabic, w.source, w.source_id, w.is_active,
                                  w.list_type, w.first_seen, w.properties, w.details, p.*
                           FROM screening_watchlist w JOIN vessel_profile p ON p.watchlist_id = w.id
                           WHERE p.group_key = %s ORDER BY (w.source = ANY(%s)), w.id""",
                        (row['group_key'], list(VS.OPENSANCTIONS_SOURCES))).fetchall()
    recs = [r for r in recs if inc_os or r['source'] not in VS.OPENSANCTIONS_SOURCES]
    if not recs:
        abort(404)
    active = [r for r in recs if r['is_active']] or recs
    base = active[0]
    ids = [r['id'] for r in active]
    idents = conn.execute("""SELECT kind, value_norm, bool_or(is_current) AS is_current, bool_and(check_ok) AS check_ok
                             FROM vessel_identifier WHERE watchlist_id = ANY(%s)
                             GROUP BY kind, value_norm ORDER BY kind, value_norm""", (ids,)).fetchall()
    parties, seen = [], set()
    for lst in VS.party_links(conn, ids).values():
        for p in lst:
            k = (VS.party_key(p['name']), p['role'])
            if k not in seen:
                seen.add(k)
                parties.append(p)
    names = []
    for r in active:
        names += [r['full_name']] + (VS._j(r['aliases'], []) or [])
    prev = list(dict.fromkeys(x for r in active for x in VS._j(r['previous_names'], []) or []))
    v = {'name': base['full_name'], 'is_active': any(r['is_active'] for r in recs),
         'other_names': [n for n in dict.fromkeys(names) if n and n != base['full_name'] and n not in prev][:40],
         'previous_names': prev, 'full_name_arabic': next((r['full_name_arabic'] for r in active if r['full_name_arabic']), None),
         'imo': next((r['imo'] for r in active if r['imo']), None),
         'imo_valid': next((r['imo_valid'] for r in active if r['imo']), None),
         'mmsi': next((r['mmsi'] for r in active if r['mmsi']), None),
         'call_sign': next((r['call_sign'] for r in active if r['call_sign']), None),
         'flag': next((r['current_flag'] for r in active if r['current_flag']), None),
         'flag_history': list(dict.fromkeys(x for r in active for x in VS._j(r['flag_history'], []) or [])),
         'vessel_type': next((r['vessel_type'] for r in active if r['vessel_type']), None),
         'gross_tonnage': next((r['gross_tonnage'] for r in active if r['gross_tonnage']), None),
         'year_built': next((r['year_built'] for r in active if r['year_built']), None),
         'measures': list(dict.fromkeys(x for r in active for x in VS._j(r['measures'], []) or [])),
         'first_seen': min((str(r['first_seen']) for r in active if r['first_seen']), default=None),
         'lists': len({r['source'] for r in active}),
         'risk_score': max(int(r['risk_score'] or 0) for r in active),
         'risk_lines': list(dict.fromkeys(x for r in active for x in VS._j(r['risk_lines'], []) or [])),
         'regimes': sorted({x for r in active for x in VS._j(r.get('regimes'), []) or []}),
         'provenance': max((r.get('provenance') or 'SANCTION' for r in active), key=lambda x: VP.ORDER.get(x, 0)),
         'psc_records': len({x for r in active for x in VS._j(r.get('risk_datasets'), []) or []})}
    internal = None
    if VS.can_see_sources():
        internal = []
        for r in recs:
            props = VS._j(r['properties'], {}) or {}
            det = VS._j(r['details'], {}) or {}
            if not isinstance(det, dict):          # OpenSanctions keeps its notes as a list
                det = {'comments': det}
            if not isinstance(props, dict):
                props = {}
            internal.append({'id': r['id'], 'source': r['source'], 'source_id': r['source_id'], 'active': r['is_active'],
                             'programs': props.get('programs') or det.get('program') or props.get('regime'),
                             'remarks': props.get('remarks') or det.get('comments') or det.get('reason')})
    return render_template('vessels/profile.html', v=v, idents=idents, parties=parties, internal=internal, wid=wid)


# --------------------------------------------------------------------------- flag risk reference
@vessels_bp.route('/flags', methods=['GET', 'POST'])
@login_required
@vessels_required('view')
def flags():
    """The flag-risk reference (open registries, high-risk flags): a risk indicator, never a match.
    The platform superadmin edits it (shared by all tenants)."""
    conn = _conn()
    if request.method == 'POST':
        if not is_superadmin():
            abort(403)
        from screening import vessel_flags as VF
        country = VU.clean_flag(request.form.get('country'))
        iso = VF.iso2(country or '')
        note = (request.form.get('note') or '').strip()[:300]
        if not country or len(note) < 3:
            flash(gettext('Choose a flag state and give a note (the reason).'), 'danger')
            return redirect(url_for('vessels.flags'))
        foc = request.form.get('foc') == '1'
        high = request.form.get('high_risk') == '1'
        if request.form.get('action') == 'delete':
            conn.execute('DELETE FROM flag_risk WHERE country = %s', (country,))
        else:
            conn.execute("""INSERT INTO flag_risk (country, iso2, flag_of_convenience, high_risk, note, updated_by, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, now())
                            ON CONFLICT (country) DO UPDATE SET flag_of_convenience = EXCLUDED.flag_of_convenience,
                              high_risk = EXCLUDED.high_risk, note = EXCLUDED.note, iso2 = EXCLUDED.iso2,
                              updated_by = EXCLUDED.updated_by, updated_at = now()""",
                         (country, (iso or '').upper() or None, foc, high, note, current_user.id))
        conn.commit()
        VS._CACHE.pop('flags', None)
        try:
            VS.refresh_risk(conn)
        except Exception as e:
            logger.warning(f'[VESSELS] risk refresh failed: {e}')
            conn.rollback()
        _audit('Vessel flag risk changed', f'{country}: {request.form.get("action") or "save"} foc={foc} high={high}: {note}')
        flash(gettext('Saved.'), 'success')
        return redirect(url_for('vessels.flags'))
    rows = conn.execute('SELECT * FROM flag_risk ORDER BY country').fetchall()
    from screening import vessel_flags as VF
    countries = sorted(v[0] for v in VF.COUNTRIES.values())
    return render_template('vessels/flags.html', rows=rows, countries=countries, can_edit=is_superadmin())


# --------------------------------------------------------------------------- update status and change log
def _superadmin_only():
    if getattr(current_user, 'role', '') != 'superadmin':
        abort(403)


def _vessel_sources(conn):
    rows = conn.execute("""SELECT p.source, count(*) FILTER (WHERE w.is_active = 1) AS active,
                                  count(*) FILTER (WHERE w.is_active = 1 AND p.provenance = 'SANCTION') AS sanction,
                                  count(*) FILTER (WHERE w.is_active = 1 AND p.provenance = 'BAN') AS ban,
                                  count(*) FILTER (WHERE w.is_active = 1 AND p.provenance IN ('RISK', 'INTEL')) AS risk_only
                           FROM vessel_profile p JOIN screening_watchlist w ON w.id = p.watchlist_id
                           GROUP BY p.source ORDER BY 2 DESC""").fetchall()
    meta = {r['source_name']: r for r in conn.execute(
        """SELECT id, source_name, last_successful_update, update_frequency_hours, last_update_error
           FROM screening_data_sources""").fetchall()}
    out = []
    for r in rows:
        m = meta.get(r['source']) or {}
        out.append(dict(r, source_id=m.get('id'), last_update=m.get('last_successful_update'),
                        every_hours=m.get('update_frequency_hours'), error=m.get('last_update_error')))
    return out


@vessels_bp.route('/updates')
@login_required
@vessels_db_required
def updates():
    """When each vessel list was last updated, its ships by class, every refresh of the vessel tables and the
    ships added / removed / changed (vessel_change_log)."""
    conn = _conn()
    runs = conn.execute("""SELECT r.*, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS by_name
                           FROM vessel_update_runs r LEFT JOIN users u ON u.id = r.user_id
                           ORDER BY r.id DESC LIMIT 40""").fetchall()
    try:
        run_id = int(request.args.get('run') or 0)
    except ValueError:
        run_id = 0
    if not run_id:
        r = next((x for x in runs if (x['added'] or x['removed'] or x['changed']) and x['message'] != 'initial load'), None)
        run_id = r['id'] if r else 0
    change = request.args.get('change') or ''
    params = [run_id]
    extra = ''
    if change in ('added', 'removed', 'changed'):
        extra = ' AND change = %s'
        params.append(change)
    changes = conn.execute(f"""SELECT * FROM vessel_change_log WHERE run_id = %s{extra} ORDER BY change, name LIMIT 500""",
                           params).fetchall() if run_id else []
    items = []
    for c in changes:
        d = VS._j(c['detail'], {}) or {}
        items.append(dict(c, detail=d))
    sources = _vessel_sources(conn)
    _audit('Vessel list updates viewed', f'run {run_id}')
    return render_template('vessels/updates.html', runs=runs, run_id=run_id, changes=items, change=change,
                           sources=sources, is_superadmin=getattr(current_user, 'role', '') == 'superadmin')


@vessels_bp.route('/updates/check', methods=['POST'])
@login_required
def updates_check():
    """Superadmin: download and apply the lists that carry ships now (the normal list update, in the background;
    the vessel tables and the change log are refreshed by it)."""
    _superadmin_only()
    import threading
    from config import get_config
    conn = _conn()
    ids = [s['source_id'] for s in _vessel_sources(conn) if s.get('source_id')]
    db_config = dict(get_config().POSTGRES_CONFIG)
    uid = current_user.id

    def run(ids=ids):
        from screening.data_updater_enhanced import EnhancedDataUpdater
        for sid in ids:
            try:
                u = EnhancedDataUpdater(db_config)
                u.version_trigger = 'manual'
                u.update_watchlist(source_id=sid, user_id=uid)
            except Exception as e:
                logger.error(f'[VESSELS] manual update of source {sid} failed: {e}')
    threading.Thread(target=run, daemon=True).start()
    _audit('Vessel lists update started', f'{len(ids)} lists')
    flash(gettext('The update of the vessel lists has started in the background. Refresh this page in a few minutes.'),
          'success')
    return redirect(url_for('vessels.updates'))


@vessels_bp.route('/updates/rebuild', methods=['POST'])
@login_required
def updates_rebuild():
    """Superadmin: rebuild the vessel tables from the lists already loaded (no download)."""
    _superadmin_only()
    from screening import list_versions as LV
    c = LV.connect()
    try:
        out = VS.sync(c, None, trigger='manual', user_id=current_user.id)
    finally:
        c.close()
    _audit('Vessel tables rebuilt', json.dumps({k: out.get(k) for k in ('vessels', 'added', 'removed', 'changed')}))
    flash(gettext('Vessel tables rebuilt: %(n)s ships, %(a)s added, %(r)s removed, %(c)s changed.', n=out['vessels'],
                  a=out['added'], r=out['removed'], c=out['changed']), 'success')
    return redirect(url_for('vessels.updates', run=out.get('run_id')))


@vessels_bp.route('/updates/upload', methods=['POST'])
@login_required
def updates_upload():
    """Superadmin: load a vessel list published without a machine-readable feed (CSV / .xlsx with name, imo, flag,
    type, measure, listed_on, reference, aliases, owner; or the list's page saved as HTML). Dry run first."""
    _superadmin_only()
    import os
    import tempfile
    fs = request.files.get('file')
    source = (request.form.get('source') or '').strip().lower()
    label = (request.form.get('label') or '').strip()[:200] or None
    apply = request.form.get('apply') == '1'
    if not fs or not fs.filename:
        flash(gettext('Choose a file.'), 'warning')
        return redirect(url_for('vessels.updates'))
    name = fs.filename.lower()
    suffix = '.xlsx' if name.endswith('.xlsx') else '.html' if name.endswith(('.html', '.htm')) else '.csv'
    raw = fs.stream.read(BULK_MAX_BYTES + 1)
    if len(raw) > BULK_MAX_BYTES:
        flash(gettext('The file is too large.'), 'warning')
        return redirect(url_for('vessels.updates'))
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw)
    import importlib.util
    spec = importlib.util.spec_from_file_location('import_vessel_list', os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'import_vessel_list.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from screening import list_versions as LV
    c = LV.connect()
    lines = []
    try:
        out = mod.run(path, source, label=label, html=suffix == '.html', apply=apply, out=lines.append,
                      user_id=current_user.id, conn=c)
        flash(gettext('%(mode)s: %(n)s ships read (%(i)s with IMO), %(d)s would be / were deactivated.',
                      mode=gettext('Applied') if apply else gettext('Dry run, nothing saved'), n=out['ships'],
                      i=out['with_imo'], d=out['deactivated']), 'success' if apply else 'info')
        _audit('Vessel list uploaded', json.dumps(dict(out, file=fs.filename[:100]), default=str)[:800])
    except mod.ImportStop as e:
        flash(gettext('The file was refused: %(why)s', why=str(e)[:300]), 'danger')
    except Exception as e:
        logger.warning(f'[VESSELS] list upload failed: {e}')
        flash(gettext('The file could not be read.'), 'danger')
    finally:
        c.close()
        try:
            os.remove(path)
        except OSError:
            pass
    return redirect(url_for('vessels.updates'))
