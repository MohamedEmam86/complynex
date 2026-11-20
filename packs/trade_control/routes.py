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
"""Dual-use goods screening pages: bilingual search, entry pages, single and batch screening, decisions."""
import io
import json
import os
import re
import secrets
import tempfile
import time
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file,
                   url_for)
from flask_login import current_user, login_required

from models.audit import AuditLog

from . import guidance as G
from . import screening as SC
from . import service as S
from . import text as T
from access.registry import mark as _mark

bp = Blueprint('dualuse', __name__, url_prefix='/dual-use')
MODULE = S.MODULE
PAGE = 20


def can(level='view', user=None):
    """Module access with the vessel module's rule: superadmin and it_admin always; everyone else (the
    client's 'admin' included, whom User._get_perm gives 'edit') by the per-user permission."""
    user = user or current_user
    if not getattr(user, 'is_authenticated', False):
        return False
    if (getattr(user, 'role', '') or '') in S.BYPASS_ROLES:
        return True
    return bool({'view': user.can_view, 'edit': user.can_edit, 'admin': user.can_admin_module}[level](MODULE))


def perm(level='view'):
    def deco(f):
        @wraps(f)
        @login_required
        def wrapped(*a, **kw):
            if not can(level):
                abort(403)
            return f(*a, **kw)
        return _mark(('any', [('role', S.BYPASS_ROLES), ('perm', MODULE, level)]))(wrapped)
    return deco


def sees_all():
    """Colleagues' screenings ('dualuse.team' in the access matrix). Old rule: editors and module
    administrators see every screening, a view-only user only their own (the vessel module's rule); a
    restricted (external) user only ever sees their own."""
    from access import service as AS
    return AS.team_view(current_user, 'dualuse.team', can('edit'))


def _load(sid):
    s, lines = S.get_screening(sid)
    if not s:
        abort(404)
    if not sees_all() and s.get('created_by') != current_user.id:
        abort(403)
    return s, lines


def _audit(action, item_id=None, details=None):
    try:
        AuditLog.log(current_user.id, action, 'Dual-use goods', item_id, details, request.remote_addr)
    except Exception:
        current_app.logger.warning('dual-use audit failed', exc_info=True)


def show_lists():
    """Real list names, versions and links are for the platform superadmin only (owner decision); every
    client user, their 'admin' included, sees the generic label."""
    if not getattr(current_user, 'is_authenticated', False):
        return False
    return (getattr(current_user, 'role', '') or '') in S.SOURCE_ROLES


@bp.context_processor
def _ctx():
    if not getattr(current_user, 'is_authenticated', False):
        return {}
    return {'du_can_edit': can('edit'), 'du_can_admin': can('admin'),
            'du_show_lists': show_lists(), 'DU': S, 'DUSC': SC, 'du_lang': 'ar' if _rc('en', 'ar') == 'ar' else 'en'}


def _filters(args):
    f = {}
    for k in ('category', 'group', 'risk', 'kind', 'chapter'):
        v = (args.get(k) or '').strip()
        if v and re.fullmatch(r'[A-Za-z0-9]{1,10}', v):
            f[k] = v
    if show_lists() and re.fullmatch(r'[a-z0-9_]{2,30}', args.get('list') or ''):
        f['list'] = args['list']
    return f


def _public(r):
    """A search result as JSON, without the list name for clients."""
    d = r['doc']
    out = {'id': d.id, 'code': d.code, 'kind': d.kind, 'title_en': d.title_en, 'title_ar': d.title_ar,
           'snippet_en': r.get('snippet_en'), 'snippet_ar': r.get('snippet_ar'), 'risk': d.risk,
           'category': d.category, 'group': d.group, 'hs': d.hs[:6], 'why': r['why'],
           'meets': [m[0] for m in r.get('meets') or []], 'url': _entry_url(d)}
    if show_lists():
        out['lists'] = [d.list_code] + r.get('also', [])
    return out


def _entry_url(d):
    if d.kind == 'priority':
        return url_for('dualuse.guide', did=d.id)
    if d.list_code == 'chemicals':
        return url_for('dualuse.chemical', cas=d.code)
    return url_for('dualuse.entry', item_id=d.id)


@bp.route('/')
@perm('view')
def index():
    q = (request.args.get('q') or '').strip()[:300]
    page = max(1, min(50, request.args.get('page', 1, type=int) or 1))
    res = None
    if q or _filters(request.args):
        idx = S.get_index()
        res = idx.search(q, _filters(request.args), limit=PAGE, offset=(page - 1) * PAGE, show_lists=show_lists())
        cats = G.categories()
        for r in res['results']:
            r['url'] = _entry_url(r['doc'])
            r['guide'] = _guide(r['doc'], cats)
            r['guide_url'] = url_for('dualuse.guide', did=r['doc'].id) + '#guide-%s' % r['doc'].id
        if q:
            _audit('dualuse_search', None, q[:200])
    idx = S.get_index()
    own = None if sees_all() else current_user.id
    return render_template('trade_control/search.html', q=q, res=res, page=page, pages=((res or {}).get('total', 0)
                           + PAGE - 1) // PAGE, args=_safe_args(), entries=len(idx.docs),
                           stats=S.stats(user_id=own), recent=[] if res else S.recent(own),
                           status=None if res else _status_summary(), ready=getattr(idx, 'ready', False))


def _safe_args():
    """The query string echoed into links and hidden fields; the source-list filter only for site admins."""
    from werkzeug.datastructures import MultiDict
    return MultiDict([(k, v) for k, v in request.args.items(multi=True) if k != 'list' or show_lists()])


@bp.route('/api/suggest')
@perm('view')
def api_suggest():
    q = (request.args.get('q') or '').strip()[:100]
    return jsonify(S.get_index().suggest(q))


@bp.route('/api/search')
@perm('view')
def api_search():
    q = (request.args.get('q') or '').strip()[:300]
    res = S.get_index().search(q, _filters(request.args), limit=min(50, request.args.get('limit', 10, type=int) or 10),
                               show_lists=show_lists())
    return jsonify({'total': res['total'], 'exact': res['exact'], 'results': [_public(r) for r in res['results']]})


@bp.route('/entry/<int:item_id>')
@perm('view')
def entry(item_id):
    idx = S.get_index()
    d = idx.by_id(item_id)
    if d is None:
        abort(404)
    family = idx.family(d)
    parent = idx.get(d.list_code, d.parent_code) if d.parent_code else None
    entry_doc = idx.get(d.list_code, d.entry_code) if d.entry_code and d.entry_code != d.code else None
    others = [x for x in idx.docs if x.kind == d.kind and (x.code or '').lower() == (d.code or '').lower()
              and x.id != d.id]
    chems = [c for c in idx.docs if c.list_code == 'chemicals' and d.code in (c.extra.get('item_codes') or [])]
    _audit('dualuse_view_entry', item_id, d.code)
    return render_template('trade_control/entry.html', d=d, family=family, parent=parent, entry_doc=entry_doc,
                           others=others, chems=chems, gd=_guide(d))


@bp.route('/chemical/<cas>')
@perm('view')
def chemical(cas):
    if not T.CAS_RE.fullmatch(cas or ''):
        abort(404)
    idx = S.get_index()
    d = next((x for x in idx.docs if x.list_code == 'chemicals' and x.code == cas), None)
    if d is None:
        abort(404)
    items = [x for x in idx.docs if x.kind == 'item' and x.code in (d.extra.get('item_codes') or [])]
    _audit('dualuse_view_chemical', None, cas)
    return render_template('trade_control/chemical.html', d=d, items=items,
                           listings=d.extra.get('listings') or [], gd=_guide(d))


# ------------------------------------------------------------------ single screening
def _line_from_form(f):
    return {'description': (f.get('description') or '').strip()[:2000] or None,
            'hs_code': (f.get('hs_code') or '').strip()[:20] or None, 'cas': (f.get('cas') or '').strip()[:40] or None,
            'model': (f.get('model') or '').strip()[:120] or None, 'origin': (f.get('origin') or '').strip()[:80] or None,
            'quantity': (f.get('quantity') or '').strip()[:60] or None}


HEADER_FIELDS = ('title', 'supplier', 'consignee', 'end_user', 'origin', 'transport_doc', 'vessel_name', 'vessel_imo')


def _header_from_form(f):
    return {k: (f.get(k) or '').strip()[:300] or None for k in HEADER_FIELDS}


@bp.route('/screen', methods=['GET', 'POST'])
@perm('edit')
def screen():
    if request.method == 'POST':
        line = _line_from_form(request.form)
        if not any(line.get(k) for k in ('description', 'hs_code', 'cas', 'model')):
            flash(_rc('Enter at least a description, an HS code, a CAS number or a model.',
                      'أدخل الوصف أو كود HS أو رقم CAS أو الموديل على الأقل.'), 'warning')
            return render_template('trade_control/screen.html', form=request.form)
        from screening.limits import consume as _consume_limit
        _consume_limit(1, 'dualuse')         # daily screening limit (all screening modules together)
        try:
            sid = S.create_screening(_header_from_form(request.form), [line], current_user.id)
        except S.ListsUnavailable as e:
            flash(_rc(e.en, e.ar), 'danger')
            return render_template('trade_control/screen.html', form=request.form)
        _audit('dualuse_screen', sid, (line.get('description') or line.get('model') or '')[:200])
        return redirect(url_for('dualuse.screening', sid=sid))
    return render_template('trade_control/screen.html', form=request.args)


def _rc(en, ar):
    from flask_babel import get_locale
    try:
        return ar if str(get_locale()).startswith('ar') else en
    except Exception:
        return en


HISTORY_PAGE = 50


@bp.route('/screenings')
@perm('view')
def screenings():
    page = max(1, request.args.get('page', 1, type=int) or 1)
    rows = S.history(request.args, limit=HISTORY_PAGE, offset=(page - 1) * HISTORY_PAGE,
                     user_id=None if sees_all() else current_user.id)
    return render_template('trade_control/history.html', args=request.args, own_only=not sees_all(),
                           rows=rows[:HISTORY_PAGE], page=page, has_next=len(rows) > HISTORY_PAGE)


LINES_PER_PAGE = 25        # a 200-line invoice is shown in pages, not as one 7 MB page


@bp.route('/screenings/<int:sid>')
@perm('view')
def screening(sid):
    s, lines = _load(sid)
    idx = S.get_index()
    open_line = request.args.get('line', type=int)
    only = request.args.get('only') if request.args.get('only') in ('open',) else None
    if only == 'open':
        lines = [ln for ln in lines if not ln['decision']]
    pages = max(1, (len(lines) + LINES_PER_PAGE - 1) // LINES_PER_PAGE)
    page = min(pages, max(1, request.args.get('page', 1, type=int) or 1))
    if open_line:
        pos = next((n for n, ln in enumerate(lines) if ln['id'] == open_line), None)
        page = pos // LINES_PER_PAGE + 1 if pos is not None else page
    lines = lines[(page - 1) * LINES_PER_PAGE: page * LINES_PER_PAGE]
    return render_template('trade_control/screening.html', s=s, lines=lines, open_line=open_line, page=page,
                           pages=pages, only=only,
                           reasons=S.DECISION_REASONS, idx=idx, trail=S.decisions(sid),
                           guides={ln['id']: _line_guides(idx, ln) for ln in lines},
                           explain={ln['id']: SC.explain(ln['candidates'] or [], ln['hard_flags'] or [],
                                                         ln['suggested'], ln) for ln in lines})


@bp.route('/lines/<int:line_id>/answers', methods=['POST'])
@perm('edit')
def line_answers(line_id):
    ln = S.get_line(line_id)
    if not ln:
        abort(404)
    answers = {}
    for q in ln['questions'] or []:
        v = request.form.get('a_' + q['id'])
        num = (request.form.get('v_' + q['id']) or '').strip()
        if num and q.get('type') == 'threshold':
            answers[q['id']] = {'value': num[:20], 'unit': (request.form.get('u_' + q['id']) or q.get('unit') or '')[:20]}
        elif v in ('yes', 'no', 'unknown'):
            answers[q['id']] = v
    sug = S.answer_line(line_id, answers)
    _audit('dualuse_answers', line_id, json.dumps(answers)[:500])
    flash(_rc('Answers saved. Suggested outcome: ', 'تم حفظ الإجابات. النتيجة المقترحة: ')
          + _rc(*S.OUTCOME_LABELS[sug]), 'info')
    return redirect(url_for('dualuse.screening', sid=ln['screening_id'], line=line_id) + '#line-%d' % line_id)


@bp.route('/lines/<int:line_id>/decide', methods=['POST'])
@perm('edit')
def line_decide(line_id):
    ln = S.get_line(line_id)
    if not ln:
        abort(404)
    decision, reason = request.form.get('decision'), request.form.get('reason')
    comment = (request.form.get('comment') or '').strip()
    errs = S.validate_decision(decision, reason, comment)
    if errs:
        for e in errs:
            flash(_rc(*e), 'danger')
        return redirect(url_for('dualuse.screening', sid=ln['screening_id'], line=line_id) + '#line-%d' % line_id)
    S.decide_line(line_id, decision, reason, comment, current_user.id, remember=request.form.get('remember') == '1')
    _audit('dualuse_decision', line_id, '%s / %s / suggested %s: %s' % (decision, reason, ln['suggested'], comment[:300]))
    flash(_rc('Decision recorded.', 'تم تسجيل القرار.'), 'success')
    return redirect(url_for('dualuse.screening', sid=ln['screening_id']) + '#line-%d' % line_id)


@bp.route('/lines/<int:line_id>/confirm', methods=['POST'])
@perm('edit')
def line_confirm(line_id):
    """Confirm the decision proposed from an identical product decided earlier: it is recorded as a new
    decision of the CURRENT user (never under the earlier decider's name), with their own comment."""
    ln = S.get_line(line_id)
    if not ln:
        abort(404)
    p = ln.get('proposal') or {}
    comment = (request.form.get('comment') or '').strip()
    errs = S.validate_decision(p.get('decision'), p.get('reason'), comment)
    if not p or errs:
        for e in errs or [('Nothing to confirm.', 'لا يوجد ما يمكن تأكيده.')]:
            flash(_rc(*e), 'danger')
        return redirect(url_for('dualuse.screening', sid=ln['screening_id'], line=line_id) + '#line-%d' % line_id)
    full = 'Confirmed the earlier decision of an identical product (%s): %s' % ((p.get('decided_at') or '')[:10], comment)
    S.decide_line(line_id, p['decision'], p['reason'], full, current_user.id, remember=False)
    _audit('dualuse_decision_confirmed', line_id, '%s / %s (proposal from %s): %s' % (
        p['decision'], p['reason'], (p.get('decided_at') or '')[:10], comment[:300]))
    flash(_rc('Decision recorded.', 'تم تسجيل القرار.'), 'success')
    return redirect(url_for('dualuse.screening', sid=ln['screening_id']) + '#line-%d' % line_id)


# ------------------------------------------------------------------ batch
TMP_TTL = 3600          # an uploaded invoice waits at most one hour for its column mapping


def _sweep_tmp(d):
    """Uploads never run (the user left the mapping page) hold customer invoice data: delete them after TMP_TTL."""
    now = time.time()
    try:
        names = os.listdir(d)
    except OSError:
        return
    for n in names:
        p = os.path.join(d, n)
        try:
            if n.endswith('.json') and now - os.path.getmtime(p) > TMP_TTL:
                os.remove(p)
        except OSError:
            continue


def _tmp_dir():
    d = os.path.join(tempfile.gettempdir(), 'complynex_dualuse')
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


@bp.route('/batch', methods=['GET', 'POST'])
@perm('edit')
def batch():
    if request.method == 'POST' and request.files.get('file'):
        f = request.files['file']
        data = f.stream.read(S.MAX_UPLOAD_BYTES + 1)
        if len(data) > S.MAX_UPLOAD_BYTES:
            flash(_rc('The file is larger than 10 MB.', 'حجم الملف أكبر من 10 ميجابايت.'), 'danger')
            return redirect(url_for('dualuse.batch'))
        try:
            header, rows = S.read_table(f.filename, data)
        except S.TableError as e:
            flash(_rc(e.en, e.ar), 'danger')
            return redirect(url_for('dualuse.batch'))
        token = secrets.token_hex(16)
        _sweep_tmp(_tmp_dir())
        with open(os.path.join(_tmp_dir(), token + '.json'), 'w', encoding='utf-8') as fh:
            json.dump({'name': os.path.basename(f.filename or '')[:200], 'header': header, 'rows': rows,
                       'user': current_user.id}, fh, ensure_ascii=False)
        mapping = S.guess_mapping(header)
        return render_template('trade_control/batch_map.html', token=token, header=header, rows=rows[:5],
                               n=len(rows), mapping=mapping, columns=S.COLUMNS, file_name=f.filename,
                               preview=S.lines_from(rows[:40], mapping)[:6])
    return render_template('trade_control/batch.html', columns=S.COLUMNS, max_lines=S.MAX_BATCH_LINES)


@bp.route('/batch/run', methods=['POST'])
@perm('edit')
def batch_run():
    token = request.form.get('token') or ''
    if not re.fullmatch(r'[0-9a-f]{32}', token):
        abort(400)
    path = os.path.join(_tmp_dir(), token + '.json')
    if not os.path.exists(path):
        flash(_rc('The upload expired: upload the file again.', 'انتهت صلاحية الملف المرفوع: ارفعه مرة أخرى.'), 'warning')
        return redirect(url_for('dualuse.batch'))
    with open(path, encoding='utf-8') as fh:
        up = json.load(fh)
    if up.get('user') != current_user.id:
        abort(403)
    mapping = {}
    for field, _, _ in S.COLUMNS:
        v = request.form.get('col_' + field, '')
        if v.isdigit() and int(v) < len(up['header']):
            mapping[field] = int(v)
    if not any(k in mapping for k in ('description', 'hs_code', 'cas', 'model')):
        flash(_rc('Map at least the description, HS code, CAS or model column.',
                  'حدّد عمود الوصف أو كود HS أو CAS أو الموديل على الأقل.'), 'warning')
        return render_template('trade_control/batch_map.html', token=token, header=up['header'], rows=up['rows'][:5],
                               n=len(up['rows']), mapping=mapping, columns=S.COLUMNS, file_name=up['name'],
                               preview=[])
    lines = S.lines_from(up['rows'], mapping)
    from screening.limits import consume as _consume_limit
    _consume_limit(len(lines), 'dualuse')    # daily screening limit: the whole batch or nothing
    try:
        sid = S.create_screening(_header_from_form(request.form), lines, current_user.id, batch=True,
                                 file_name=up['name'])
    except S.ListsUnavailable as e:
        flash(_rc(e.en, e.ar), 'danger')
        return redirect(url_for('dualuse.batch'))
    try:
        os.remove(path)
    except OSError:
        pass
    _audit('dualuse_batch', sid, '%s: %d lines' % (up['name'], len(lines)))
    return redirect(url_for('dualuse.screening', sid=sid))


# ------------------------------------------------------------------ export
def _L(pair, lang):
    return pair[1] if lang == 'ar' else pair[0]


def _export_rows(s, lines, lang='en'):
    out = []
    reasons = {r[0]: (r[1], r[2]) for r in S.DECISION_REASONS}
    for ln in lines:
        cands = ', '.join(c['code'] for c in (ln['candidates'] or [])[:6])
        flags = ', '.join('%s (%s)' % (_L(SC.HARD_LABELS.get(h['flag'], (h['flag'], h['flag'])), lang),
                                       h.get('name') or h.get('code')) for h in (ln['hard_flags'] or []))
        why = ' | '.join(_L(e, lang) for e in SC.explain(ln['candidates'] or [], ln['hard_flags'] or [],
                                                          ln['suggested'], ln))
        out.append([ln['line_no'], (ln['description'] or '')[:1000], ln['hs_code'] or '', ln['cas'] or '',
                    ln['model'] or '', ln['origin'] or '', cands, flags, _L(S.OUTCOME_LABELS[ln['suggested']], lang),
                    why[:2000], _L(S.OUTCOME_LABELS[ln['decision']], lang) if ln['decision'] else '',
                    _L(reasons.get(ln['reason'], (ln['reason'] or '', ln['reason'] or '')), lang),
                    (ln['comment'] or '')[:2000], ln.get('decided_by_name') or '',
                    ln['decided_at'].strftime('%Y-%m-%d %H:%M') if ln['decided_at'] else ''])
    return out


EXPORT_HEAD = [('Line', 'البند'), ('Description', 'الوصف'), ('HS code', 'كود HS'), ('CAS', 'CAS'),
               ('Model', 'الموديل'), ('Origin', 'المنشأ'), ('Candidate entries', 'البنود المحتملة'),
               ('Flags', 'المؤشرات'), ('Screening result', 'نتيجة الفحص'), ('Why', 'السبب'),
               ('Decision', 'القرار'), ('Reason', 'سبب القرار'), ('Comment', 'التعليق'), ('Decided by', 'بواسطة'),
               ('Decided at', 'التاريخ')]
_ROLES = {'supplier': ('Supplier', 'المورد'), 'consignee': ('Consignee', 'المرسل إليه'),
          'end_user': ('End user', 'المستخدم النهائي')}


@bp.route('/screenings/<int:sid>/export.xlsx')
@perm('view')
def export_xlsx(sid):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from utils.sheet_safe import row as safe_row
    s, lines = _load(sid)
    lang = 'ar' if _rc('en', 'ar') == 'ar' else 'en'
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'فحص' if lang == 'ar' else 'Screening'
    ws.sheet_view.rightToLeft = lang == 'ar'

    def row(*vals):
        ws.append(safe_row(list(vals)))            # customer data never becomes a formula (= + - @ ...)

    row(_L(('Dual-use goods screening', 'فحص السلع مزدوجة الاستخدام'), lang), s['ref'])
    row(_L(('Screened against', 'تم الفحص مقابل'), lang), _L(S.CLIENT_LIST_LABEL, lang))
    for c in S.coverage_lines(s['list_versions'], lang):
        row(_L(('Lists used', 'القوائم المستخدمة'), lang), c)
    row(_L(('Note', 'ملاحظة'), lang), _L(S.DISCLAIMER, lang))
    if s.get('vessel_name') or s.get('vessel_imo'):
        v = s.get('vessel_result') or {}
        row(_L(('Vessel', 'السفينة'), lang),
            '%s %s' % (s.get('vessel_name') or '', ('IMO ' + s['vessel_imo']) if s.get('vessel_imo') else ''),
            _L(('not available', 'غير متاح'), lang) if v.get('error') else
            _L(S.VESSEL_TIERS.get(v.get('tier'), (v.get('tier') or '', v.get('tier') or '')), lang),
            _L(S.VESSEL_LIST_LABEL, lang))
    row(_L(('Created', 'تاريخ الإنشاء'), lang), s['created_at'].strftime('%Y-%m-%d %H:%M') if s['created_at'] else '',
        s.get('created_by_name') or '')
    for p in s['party_results'] or []:
        row(_L(_ROLES.get(p['role'], (p['role'], p['role'])), lang), p['name'],
            p.get('result') or (_L(('not completed', 'لم يكتمل'), lang) if p.get('error') else ''))
    ws.append([])
    ws.append([_L(h, lang) for h in EXPORT_HEAD])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='1F3A5F')
    for r in _export_rows(s, lines, lang):
        row(*r)
    for col, w in zip('ABCDEFGHIJKLMNO', (6, 50, 14, 14, 18, 12, 30, 18, 12, 50, 11, 20, 40, 18, 17)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    _audit('dualuse_export', sid, 'xlsx')
    return send_file(buf, as_attachment=True, download_name='%s.xlsx' % s['ref'],
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@bp.route('/screenings/<int:sid>/export.pdf')
@perm('view')
def export_pdf(sid):
    s, lines = _load(sid)
    html = render_template('trade_control/report_pdf.html', s=s, lines=lines, reasons=dict(
        (r[0], (r[1], r[2])) for r in S.DECISION_REASONS), trail=S.decisions(sid),
        coverage=S.coverage_lines(s['list_versions'], 'ar' if _rc('en', 'ar') == 'ar' else 'en'),
        explain={ln['id']: SC.explain(ln['candidates'] or [], ln['hard_flags'] or [], ln['suggested'], ln) for ln in lines})
    try:
        from weasyprint import HTML
        pdf = HTML(string=html, base_url=request.url_root).write_pdf()
    except Exception:
        current_app.logger.warning('dual-use PDF export failed', exc_info=True)
        return html          # printable page as a fallback
    _audit('dualuse_export', sid, 'pdf')
    return send_file(io.BytesIO(pdf), as_attachment=True, download_name='%s.pdf' % s['ref'],
                     mimetype='application/pdf')


# ------------------------------------------------------------------ administration
@bp.route('/admin', methods=['GET', 'POST'])
@perm('admin')
def admin():
    if request.method == 'POST':
        # the dictionary is shared reference data (all tenants): only the platform superadmin edits it
        if not show_lists():
            abort(403)
        en, ar = (request.form.get('term_en') or '').strip(), (request.form.get('term_ar') or '').strip()
        if en and ar and T.is_arabic(ar):
            S.add_term(en, ar, current_user.id)
            _audit('dualuse_add_term', None, '%s = %s' % (en[:100], ar[:100]))
            flash(_rc('Term added.', 'تمت إضافة المصطلح.'), 'success')
        else:
            flash(_rc('Enter the English term and its Arabic equivalent.', 'أدخل المصطلح بالإنجليزية ومقابله بالعربية.'),
                  'warning')
        return redirect(url_for('dualuse.admin'))
    return render_template('trade_control/admin.html', lists=S.list_status(), terms=S.terms(),
                           entries=len(S.get_index().docs))


# ------------------------------------------------------------------ guidance
def _lang():
    return 'ar' if _rc('en', 'ar') == 'ar' else 'en'


def _guide(d, cats=None):
    """Everything the guidance panel shows for one result (no external call)."""
    if d is None:
        return None
    cat = G.for_doc(d, cats if cats is not None else G.categories())
    return {'doc': d, 'plain': G.plain(d), 'g': G.view(cat, _lang(), sources=show_lists()),
            'thresholds': G.thresholds(d)}


def _line_guides(idx, ln):
    """Guidance for a screening line: its candidates and flagged chemicals / tariff codes, one panel per
    guidance category (at most three)."""
    cats, out, seen = G.categories(), [], set()
    docs = [idx.get(c['list_code'], c['code']) for c in (ln['candidates'] or [])]
    for h in ln['hard_flags'] or []:
        if h.get('flag') in ('cwc', 'precursor'):
            docs.append(idx.get('chemicals', h.get('code')))
        elif h.get('flag') == 'priority':
            docs.append(idx.get('chpl', h.get('code')))
    for d in docs:
        if d is None:
            continue
        gd = _guide(d, cats)
        key = gd['g']['category'] if gd and gd['g'] else None
        if key and key not in seen:
            seen.add(key)
            out.append(gd)
        if len(out) >= 3:
            break
    return out


def _status_summary():
    """List status for the landing page: clients get one generic line, the superadmin each list."""
    try:
        rows = S.list_overview()
    except Exception:
        current_app.logger.warning('dual-use list status failed', exc_info=True)
        return None
    live = [r for r in rows if r.get('version_id')]
    dates = [r['last_ok'] for r in live if r.get('last_ok')]
    return {'rows': rows if show_lists() else [], 'checked': min(dates) if dates else None,
            'stale': any(r['stale'] for r in rows if r['code'] in S.REQUIRED_LISTS),
            'loaded': len(live), 'total': len(rows)}


def _doc_by_did(did):
    idx = S.get_index()
    if not re.fullmatch(r'[cp]?\d{1,9}', did or ''):
        abort(404)
    d = idx.by_id(int(did) if did.isdigit() else did)
    if d is None:
        abort(404)
    return d


@bp.route('/guide/<did>')
@perm('view')
def guide(did):
    d = _doc_by_did(did)
    _audit('dualuse_view_guidance', None, d.code)
    return render_template('trade_control/guide.html', d=d, gd=_guide(d), url=_entry_url(d))


@bp.route('/api/check')
@perm('view')
def api_check():
    """The user's value against one threshold of an entry -> above / below / unknown (computed here)."""
    d = _doc_by_did(request.args.get('d') or '')
    n = request.args.get('n', type=int)
    out = G.check(d, n if n is not None else -1, (request.args.get('v') or '').strip()[:30],
                  (request.args.get('u') or '').strip()[:20])
    return jsonify(out)


@bp.route('/lines/<int:line_id>/guidance', methods=['POST'])
@perm('edit')
def line_guidance(line_id):
    ln = S.get_line(line_id)
    if not ln:
        abort(404)
    s, _ = _load(ln['screening_id'])
    cat = (request.form.get('category') or '')[:60]
    if not re.fullmatch(r'[a-z0-9_]{2,60}', cat):
        abort(400)

    def ints(name):
        return sorted({int(v) for v in request.form.getlist(name) if v.isdigit() and int(v) < 60})
    name = ('%s %s' % (getattr(current_user, 'first_name', '') or '', getattr(current_user, 'last_name', '') or '')).strip()
    from datetime import datetime
    data = {'asked': ints('asked'), 'docs': ints('docs'), 'flags': ints('flags'),
            'notes': (request.form.get('notes') or '').strip()[:2000], 'by': current_user.id,
            'by_name': name or getattr(current_user, 'username', ''), 'at': datetime.now().isoformat(timespec='minutes')}
    S.save_line_guidance(line_id, cat, data)
    _audit('dualuse_guidance_checklist', line_id, '%s: asked %s, documents %s, red flags %s' % (
        cat, data['asked'], data['docs'], data['flags']))
    flash(_rc('Checklist saved.', 'تم حفظ قائمة التحقق.'), 'success')
    return redirect(url_for('dualuse.screening', sid=s['id'], line=line_id) + '#line-%d' % line_id)


@bp.route('/screenings/<int:sid>/export_memo.pdf')
@perm('view')
def export_memo(sid):
    """Decision memo: per line the result, the guidance followed, the user's answers, checklist and decision."""
    s, lines = _load(sid)
    idx = S.get_index()
    html = render_template('trade_control/memo_pdf.html', s=s, lines=lines, reasons=dict(
        (r[0], (r[1], r[2])) for r in S.DECISION_REASONS), trail=S.decisions(sid),
        coverage=S.coverage_lines(s['list_versions'], _lang()), now=__import__('datetime').datetime.now(),
        guides={ln['id']: _line_guides(idx, ln) for ln in lines[:100]},
        explain={ln['id']: SC.explain(ln['candidates'] or [], ln['hard_flags'] or [], ln['suggested'], ln)
                 for ln in lines})
    try:
        from weasyprint import HTML
        pdf = HTML(string=html, base_url=request.url_root).write_pdf()
    except Exception:
        current_app.logger.warning('dual-use memo PDF failed', exc_info=True)
        return html
    _audit('dualuse_export', sid, 'decision memo pdf')
    return send_file(io.BytesIO(pdf), as_attachment=True, download_name='%s-decision-memo.pdf' % s['ref'],
                     mimetype='application/pdf')


# ------------------------------------------------------------------ catalogue
SPECIAL = {'chemicals': ('Controlled chemicals (by CAS number)', 'المواد الكيميائية الخاضعة للرقابة (برقم CAS)'),
           'precursors': ('Explosives precursors', 'سلائف المتفجرات'),
           'priority': ('High-priority diversion items (by HS code)', 'الأصناف عالية الأولوية لخطر التحويل (بكود HS)')}


def _entries(idx, cat=None):
    """Level-0 entries of the control lists, one per code (an entry published by two lists is shown once)."""
    seen, out = set(), []
    for d in idx.docs:
        if d.kind != 'item' or d.level or d.list_code not in ('eu_annex1', 'us_ccl'):
            continue
        if cat and d.category != cat:
            continue
        k = (d.code or '').upper()
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
    return out


@bp.route('/browse')
@perm('view')
def browse():
    idx = S.get_index()
    counts = {}
    for d in _entries(idx):
        counts.setdefault(d.category, {}).setdefault(d.group, 0)
        counts[d.category][d.group] += 1
    special = {'chemicals': sum(1 for d in idx.docs if d.list_code == 'chemicals'),
               'precursors': sum(1 for d in idx.docs if d.list_code == 'eu_expl_precursors'),
               'priority': sum(1 for d in idx.docs if d.kind == 'priority')}
    return render_template('trade_control/browse.html', counts=counts, special=special)


@bp.route('/browse/<cat>')
@perm('view')
def browse_category(cat):
    idx = S.get_index()
    grp = request.args.get('group') if (request.args.get('group') or '') in S.GROUP_LABELS else None
    if cat in SPECIAL:
        if cat == 'chemicals':
            docs = sorted((d for d in idx.docs if d.list_code == 'chemicals'), key=lambda d: (d.title_en or '').lower())
        elif cat == 'precursors':
            docs = sorted((d for d in idx.docs if d.list_code == 'eu_expl_precursors'), key=lambda d: d.code)
        else:
            docs = sorted((d for d in idx.docs if d.kind == 'priority'), key=lambda d: (d.extra.get('tier') or '', d.code))
        return render_template('trade_control/browse_list.html', cat=cat, title=SPECIAL[cat], docs=docs, groups=None,
                               grp=None, url=_entry_url)
    if cat not in S.CATEGORY_LABELS:
        abort(404)
    docs = sorted(_entries(idx, cat), key=lambda d: (d.group or '', d.code))
    groups = {}
    for d in docs:
        groups[d.group] = groups.get(d.group, 0) + 1
    if grp:
        docs = [d for d in docs if d.group == grp]
    return render_template('trade_control/browse_list.html', cat=cat, title=S.CATEGORY_LABELS[cat], docs=docs,
                           groups=groups, grp=grp, url=_entry_url)


# ------------------------------------------------------------------ list updates (superadmin)
def superadmin(f):
    """Shared reference data (every tenant): the real lists, their sources and the guidance are managed by the
    platform superadmin only."""
    @wraps(f)
    @login_required
    def wrapped(*a, **kw):
        if not show_lists():
            abort(403)
        return f(*a, **kw)
    return _mark(('role', S.SOURCE_ROLES))(wrapped)


@bp.route('/admin/lists')
@superadmin
def admin_lists():
    from . import loader as LD
    rows = S.list_overview()
    hist = {r['code']: S.versions(r['code']) for r in rows}
    return render_template('trade_control/admin_lists.html', rows=rows, runs=S.update_runs(), hist=hist,
                           uploadable=LD.UPLOADABLE, max_mb=LD.MAX_UPLOAD // (1024 * 1024), stale_days=S.STALE_DAYS)


@bp.route('/admin/lists/check', methods=['POST'])
@superadmin
def admin_check():
    rid = S.start_check(getattr(current_user, 'username', None) or str(current_user.id))
    if rid is None:
        flash(_rc('A check is already running: its result appears below in a few minutes.',
                  'يوجد فحص قيد التنفيذ: ستظهر نتيجته أدناه خلال دقائق.'), 'info')
    else:
        _audit('dualuse_lists_check', rid, 'manual check started')
        flash(_rc('Checking the official publishers for updates. Refresh this page in a few minutes.',
                  'جارٍ فحص التحديثات لدى الجهات الناشرة الرسمية. حدّث هذه الصفحة بعد بضع دقائق.'), 'success')
    return redirect(url_for('dualuse.admin_lists'))


@bp.route('/admin/lists/upload', methods=['POST'])
@superadmin
def admin_upload():
    from . import loader as LD
    code = request.form.get('list') or ''
    f = request.files.get('file')
    if code not in LD.UPLOADABLE or not f:
        flash(_rc('Choose the list and the file.', 'اختر القائمة والملف.'), 'warning')
        return redirect(url_for('dualuse.admin_lists'))
    data = f.stream.read(LD.MAX_UPLOAD + 1)
    name = os.path.basename(f.filename or '')[:200]
    res = LD.load_uploaded(code, data, name, 'upload:%s' % (getattr(current_user, 'username', None) or current_user.id))
    _audit('dualuse_lists_upload', res.get('version_id'), '%s: %s (%s, %d bytes) %s' % (
        code, res['status'], name, len(data), (res.get('message') or '')[:200]))
    d = res.get('diff') or {}
    if res['status'] == 'loaded':
        flash(_rc('New version loaded: %d added, %d removed, %d changed, %d with changed thresholds.',
                  'تم تحميل إصدار جديد: %d مضاف، %d محذوف، %d معدل، %d بحدود معدلة.') % (
            d.get('added', 0), d.get('removed', 0), d.get('changed', 0), d.get('thresholds_changed', 0)), 'success')
        S.get_index(force=True)
    elif res['status'] == 'unchanged':
        flash(_rc('The file has the same content as the current version: nothing to load.',
                  'محتوى الملف مطابق للإصدار الحالي: لا يوجد ما يُحمَّل.'), 'info')
    else:
        flash(_rc('Not loaded: ', 'لم يتم التحميل: ') + (res.get('message') or ''), 'danger')
    return redirect(url_for('dualuse.admin_lists'))


@bp.route('/admin/versions/<int:vid>')
@superadmin
def admin_version(vid):
    v, prev = S.version_changes(vid)
    if not v:
        abort(404)
    idx = S.get_index()

    def link(code):
        code = str(code).split(' ')[0]
        d = idx.get(v['list_code'], code) if v['list_code'] not in ('chpl', 'eu_cn_correlation') else None
        if v['list_code'] == 'chemicals':
            d = idx.get('chemicals', code)
        return _entry_url(d) if d is not None else None
    return render_template('trade_control/admin_version.html', v=v, prev=prev, diff=v['diff'] or {}, link=link)


@bp.route('/admin/guidance')
@superadmin
def admin_guidance():
    return render_template('trade_control/admin_guidance.html', cats=G.categories(force=True))


@bp.route('/admin/guidance/<category>', methods=['GET', 'POST'])
@superadmin
def admin_guidance_edit(category):
    from database.db import get_db
    cur = next((c for c in G.categories(force=True) if c['category'] == category), None)
    if cur is None:
        abort(404)
    if request.method == 'POST':
        data, errs = G.from_form(request.form, cur)
        if errs:
            for e in errs:
                flash(_rc(*e), 'danger')
            return render_template('trade_control/admin_guidance_edit.html', c=dict(cur, **data), fields=G.FIELDS,
                                   history=G.history(category, get_db()))
        ver = G.save(get_db(), category, data, current_user.id, (request.form.get('note') or '').strip()[:300])
        _audit('dualuse_guidance_edit', None, '%s -> version %s' % (category, ver))
        flash(_rc('Saved as version %d. The previous versions are kept.', 'تم الحفظ كإصدار %d. الإصدارات السابقة محفوظة.')
              % ver, 'success')
        return redirect(url_for('dualuse.admin_guidance_edit', category=category))
    return render_template('trade_control/admin_guidance_edit.html', c=cur, fields=G.FIELDS,
                           history=G.history(category, get_db()))
