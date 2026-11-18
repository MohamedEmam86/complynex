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
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file,
                   url_for)
from flask_login import current_user, login_required

from models.audit import AuditLog

from . import screening as SC
from . import service as S
from . import text as T

bp = Blueprint('dualuse', __name__, url_prefix='/dual-use')
MODULE = S.MODULE
PAGE = 20


def perm(level='view'):
    def deco(f):
        @wraps(f)
        @login_required
        def wrapped(*a, **kw):
            ok = {'view': current_user.can_view, 'edit': current_user.can_edit,
                  'admin': current_user.can_admin_module}[level](MODULE)
            if not ok:
                abort(403)
            return f(*a, **kw)
        return wrapped
    return deco


def _audit(action, item_id=None, details=None):
    try:
        AuditLog.log(current_user.id, action, 'Dual-use goods', item_id, details, request.remote_addr)
    except Exception:
        current_app.logger.warning('dual-use audit failed', exc_info=True)


def show_lists():
    """Real list names are for site administrators (superadmin) only; clients see the generic label."""
    if not getattr(current_user, 'is_authenticated', False):
        return False
    return (getattr(current_user, 'role', '') or '') in S.SITE_ADMIN_ROLES


@bp.context_processor
def _ctx():
    if not getattr(current_user, 'is_authenticated', False):
        return {}
    return {'du_can_edit': current_user.can_edit(MODULE), 'du_can_admin': current_user.can_admin_module(MODULE),
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
        return url_for('dualuse.index', q=d.code)
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
        for r in res['results']:
            r['url'] = _entry_url(r['doc'])
        if q:
            _audit('dualuse_search', None, q[:200])
    idx = S.get_index()
    return render_template('trade_control/search.html', q=q, res=res, page=page, pages=((res or {}).get('total', 0)
                           + PAGE - 1) // PAGE, args=_safe_args(), entries=len(idx.docs), stats=S.stats())


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
                           others=others, chems=chems)


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
                           listings=d.extra.get('listings') or [])


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
        sid = S.create_screening(_header_from_form(request.form), [line], current_user.id)
        _audit('dualuse_screen', sid, (line.get('description') or line.get('model') or '')[:200])
        return redirect(url_for('dualuse.screening', sid=sid))
    return render_template('trade_control/screen.html', form=request.args)


def _rc(en, ar):
    from flask_babel import get_locale
    try:
        return ar if str(get_locale()).startswith('ar') else en
    except Exception:
        return en


@bp.route('/screenings')
@perm('view')
def screenings():
    return render_template('trade_control/history.html', rows=S.history(request.args), args=request.args)


@bp.route('/screenings/<int:sid>')
@perm('view')
def screening(sid):
    s, lines = S.get_screening(sid)
    if not s:
        abort(404)
    idx = S.get_index()
    open_line = request.args.get('line', type=int)
    return render_template('trade_control/screening.html', s=s, lines=lines, open_line=open_line,
                           reasons=S.DECISION_REASONS, idx=idx, trail=S.decisions(sid),
                           explain={ln['id']: SC.explain(ln['candidates'] or [], ln['hard_flags'] or [],
                                                         ln['decision'] or ln['suggested']) for ln in lines})


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


# ------------------------------------------------------------------ batch
def _tmp_dir():
    d = os.path.join(tempfile.gettempdir(), 'complynex_dualuse')
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


@bp.route('/batch', methods=['GET', 'POST'])
@perm('edit')
def batch():
    if request.method == 'POST' and request.files.get('file'):
        f = request.files['file']
        data = f.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            flash(_rc('The file is larger than 10 MB.', 'حجم الملف أكبر من 10 ميجابايت.'), 'danger')
            return redirect(url_for('dualuse.batch'))
        try:
            header, rows = S.read_table(f.filename, data)
        except ValueError as e:
            flash(str(e), 'danger')
            return redirect(url_for('dualuse.batch'))
        token = secrets.token_hex(16)
        with open(os.path.join(_tmp_dir(), token + '.json'), 'w', encoding='utf-8') as fh:
            json.dump({'name': os.path.basename(f.filename or '')[:200], 'header': header, 'rows': rows,
                       'user': current_user.id}, fh, ensure_ascii=False)
        return render_template('trade_control/batch_map.html', token=token, header=header, rows=rows[:5],
                               n=len(rows), mapping=S.guess_mapping(header), columns=S.COLUMNS,
                               file_name=f.filename)
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
                               n=len(up['rows']), mapping=mapping, columns=S.COLUMNS, file_name=up['name'])
    lines = S.lines_from(up['rows'], mapping)
    sid = S.create_screening(_header_from_form(request.form), lines, current_user.id, batch=True,
                             file_name=up['name'])
    try:
        os.remove(path)
    except OSError:
        pass
    _audit('dualuse_batch', sid, '%s: %d lines' % (up['name'], len(lines)))
    return redirect(url_for('dualuse.screening', sid=sid))


# ------------------------------------------------------------------ export
def _export_rows(s, lines):
    out = []
    for ln in lines:
        cands = ', '.join(c['code'] for c in (ln['candidates'] or [])[:6])
        flags = ', '.join('%s (%s)' % (SC.HARD_LABELS.get(h['flag'], (h['flag'],))[0], h.get('name') or h.get('code'))
                          for h in (ln['hard_flags'] or []))
        out.append([ln['line_no'], ln['description'] or '', ln['hs_code'] or '', ln['cas'] or '', ln['model'] or '',
                    ln['origin'] or '', cands, flags, ln['suggested'], ln['decision'] or '', ln['reason'] or '',
                    ln['comment'] or '', ln.get('decided_by_name') or '',
                    ln['decided_at'].strftime('%Y-%m-%d %H:%M') if ln['decided_at'] else ''])
    return out


EXPORT_HEAD = ['Line', 'Description', 'HS code', 'CAS', 'Model', 'Origin', 'Candidate entries', 'Flags', 'Suggested',
               'Decision', 'Reason', 'Comment', 'Decided by', 'Decided at']


@bp.route('/screenings/<int:sid>/export.xlsx')
@perm('view')
def export_xlsx(sid):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    s, lines = S.get_screening(sid)
    if not s:
        abort(404)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Screening'
    ws.append(['Dual-use goods screening', s['ref']])
    ws.append(['Screened against', S.CLIENT_LIST_LABEL[0]])
    ws.append(['Note', S.DISCLAIMER[0]])
    if s.get('vessel_name') or s.get('vessel_imo'):
        v = s.get('vessel_result') or {}
        ws.append(['Vessel', '%s %s' % (s.get('vessel_name') or '', ('IMO ' + s['vessel_imo']) if s.get('vessel_imo') else ''),
                   'not available' if v.get('error') else (v.get('tier') or '')])
    ws.append(['Created', s['created_at'].strftime('%Y-%m-%d %H:%M') if s['created_at'] else '',
               s.get('created_by_name') or ''])
    for p in s['party_results'] or []:
        ws.append(['Party: ' + p['role'], p['name'], p.get('result') or p.get('error') or ''])
    ws.append([])
    ws.append(EXPORT_HEAD)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='1F3A5F')
    for r in _export_rows(s, lines):
        ws.append(r)
    for col, w in zip('ABCDEFGHIJKLMN', (6, 50, 14, 14, 18, 12, 30, 18, 11, 11, 20, 40, 18, 17)):
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
    s, lines = S.get_screening(sid)
    if not s:
        abort(404)
    html = render_template('trade_control/report_pdf.html', s=s, lines=lines, reasons=dict(
        (r[0], (r[1], r[2])) for r in S.DECISION_REASONS), trail=S.decisions(sid),
        explain={ln['id']: SC.explain(ln['candidates'] or [], ln['hard_flags'] or [], ln['suggested']) for ln in lines})
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
        en, ar = (request.form.get('term_en') or '').strip(), (request.form.get('term_ar') or '').strip()
        if en and ar and T.is_arabic(ar):
            S.add_term(en, ar, current_user.id)
            S.get_index(force=True)
            _audit('dualuse_add_term', None, '%s = %s' % (en[:100], ar[:100]))
            flash(_rc('Term added.', 'تمت إضافة المصطلح.'), 'success')
        else:
            flash(_rc('Enter the English term and its Arabic equivalent.', 'أدخل المصطلح بالإنجليزية ومقابله بالعربية.'),
                  'warning')
        return redirect(url_for('dualuse.admin'))
    return render_template('trade_control/admin.html', lists=S.list_status(), terms=S.terms(),
                           entries=len(S.get_index().docs))
