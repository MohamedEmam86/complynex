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
Phase 7 AML pages: the customer risk model (F1), periodic reviews (F2),
screening hits that need action with the path to an STR case, the hit
escalation log (F6) and the STR draft (F5). Business rules live in risk_config,
periodic_review, escalation_log and str_draft; this module only wires the pages.
ComplyNex only alerts and escalates: it never freezes or blocks anything.
Every page text is given in English and Arabic (L(en, ar) in the templates).
"""
import logging
from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database.db import get_db
from utils import aml_risk
from utils.decorators import permission_required

from . import aml_bp
from . import escalation_log as EL
from . import periodic_review as PR
from . import risk_config as RC
from . import str_draft as SD
from . import str_register as SR

# Arabic of the messages the Phase 7 modules raise
MSG_AR = {
    'give the reason for the change (at least 15 characters)': 'اكتب سبب التعديل (15 حرفاً على الأقل)',
    'Choose the outcome of the review.': 'اختر نتيجة المراجعة.',
    'Write what was reviewed (at least 10 characters).': 'اكتب ما تمت مراجعته (10 أحرف على الأقل).',
    'Customer not found.': 'العميل غير موجود.',
    'Enter the date and time.': 'أدخل التاريخ والوقت.',
    'The time cannot be in the future.': 'لا يمكن أن يكون الوقت في المستقبل.',
    'This step cannot be before the discovery time.': 'لا يمكن أن تسبق هذه الخطوة وقت الاكتشاف.',
    'Record the escalation to the MLRO before the report.': 'سجّل التصعيد لمسؤول الإبلاغ قبل الإخطار.',
    'The report cannot be before the escalation.': 'لا يمكن أن يسبق الإخطار التصعيد.',
    'Escalation log entry not found.': 'قيد التصعيد غير موجود.',
    'Enter the name of the listed person or entity.': 'أدخل اسم الشخص أو الكيان المدرج.',
    'Enter when the match was discovered (not in the future).': 'أدخل وقت اكتشاف التطابق (ليس في المستقبل).',
    'The escalation is already recorded.': 'التصعيد مسجل بالفعل.',
    'The report is already recorded.': 'الإخطار مسجل بالفعل.',
    'Name the authority the hit was reported to.': 'اذكر الجهة التي تم إخطارها.',
    'STR case not found.': 'حالة الإخطار غير موجودة.',
    'This case is closed without a report; there is no draft to keep.': 'الحالة مغلقة بدون إخطار؛ لا توجد مسودة.',
    'The report is filed; the draft can no longer change.': 'تم إرسال الإخطار؛ لا يمكن تعديل المسودة.',
    'Write the grounds of suspicion (at least 30 characters).': 'اكتب أسباب الاشتباه (30 حرفاً على الأقل).',
    'Someone saved the draft at the same time; reload the page and try again.':
        'قام شخص آخر بحفظ المسودة في نفس الوقت؛ أعد تحميل الصفحة وحاول مرة أخرى.',
    'someone else saved the model at the same time; reload the page and try again':
        'قام شخص آخر بحفظ النموذج في نفس الوقت؛ أعد تحميل الصفحة وحاول مرة أخرى',
    'the home country is required': 'دولة النشاط مطلوبة',
}
logger = logging.getLogger(__name__)


def _ar():
    from flask_babel import get_locale
    return str(get_locale()) == 'ar'


def _msg(e):
    s = str(e)
    return MSG_AR.get(s, s) if _ar() else s


def _is_mlro():
    """The MLRO designation of the screening clearance rule (str_register.is_mlro)."""
    return SR.is_mlro(current_user)


def _safe_back(value, default):
    """A local path to go back to; anything else (other hosts, '//host', '\\host') -> default."""
    v = (value or '').strip()
    if not v.startswith('/') or v.startswith('//') or '\\' in v or any(ord(ch) < 32 or ord(ch) == 127 for ch in v):
        return default
    return v


def _L(en, ar):
    return ar if _ar() else en


# ----------------------------------------------------------------------------- F1 risk model

@aml_bp.route('/risk-scoring', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def risk_scoring():
    db = get_db()
    model = RC.current_model(db, force=True)
    preview, draft = None, None
    if request.method == 'POST':
        if not _is_mlro():
            flash(_L('Only the MLRO can change the customer risk model.', 'مسؤول الإبلاغ فقط يعدل نموذج تقييم المخاطر.'),
                  'danger')
            return redirect(url_for('aml.risk_scoring'))
        try:
            draft = RC.from_form(request.form)
            probs = aml_risk.validate(draft, for_save=True)
            if probs:
                raise RC.RiskModelError('; '.join(probs))
            if request.form.get('action') == 'preview':
                preview = RC.preview(draft, db)
            else:
                vid = RC.save_model(draft, request.form.get('reason'), current_user.id, db)
                flash(_L(f'Risk model version {vid} saved. New ratings use it from now on; existing customers keep their '
                         f'rating until they are re-rated or reviewed.',
                         f'تم حفظ الإصدار {vid} من نموذج المخاطر. يُطبق على التقييمات الجديدة؛ العملاء الحاليون يحتفظون '
                         f'بتقييمهم حتى إعادة التقييم أو المراجعة.'), 'success')
                return redirect(url_for('aml.risk_scoring'))
        except RC.RiskModelError as e:
            flash(_msg(e), 'danger')
    return render_template('aml/p7_risk_scoring.html', ar=_ar(), model=draft or model, current=model,
                           preview=preview, history=RC.history(db), is_mlro=_is_mlro(),
                           sources=aml_risk.COUNTRY_SOURCES, classes=aml_risk.CLASSES,
                           hr_count=len(RC.high_risk_rows(db)))


# ----------------------------------------------------------------------------- F2 periodic reviews

@aml_bp.route('/periodic-reviews')
@login_required
@permission_required('aml')
def periodic_reviews():
    db = get_db()
    model = RC.current_model(db)
    state = request.args.get('state') if request.args.get('state') in PR.STATE_ORDER else None
    risk = request.args.get('risk') if request.args.get('risk') in aml_risk.CLASSES else None
    page = PR.portfolio_page(db, model, state=state, risk=risk, limit=500)
    return render_template('aml/p7_reviews.html', ar=_ar(), rows=page['rows'], total=page['total'],
                           summary=page['summary'], model=model, state=state, risk=risk, outcomes=PR.OUTCOMES,
                           classes=aml_risk.CLASSES)


@aml_bp.route('/periodic-reviews/<int:customer_id>', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def record_periodic_review(customer_id):
    try:
        r = PR.record_review(customer_id, request.form.get('outcome'), request.form.get('notes'), current_user.id)
        flash(_L(f"Review recorded: rating {r['old']} -> {r['new']}, next review {r['next']}.",
                 f"تم تسجيل المراجعة: التقييم {r['old']} ← {r['new']}، المراجعة القادمة {r['next']}."), 'success')
    except PR.ReviewError as e:
        flash(_msg(e), 'danger')
    return redirect(_safe_back(request.form.get('next'), url_for('aml.periodic_reviews')))


# ----------------------------------------------------------------------------- hits needing action

HITS_LIMIT = 300
# Hits still to act on: open (not resolved), or confirmed true matches whose STR case has no MLRO
# decision yet. A hit resolved as a false positive / PEP, or a TRUE MATCH whose linked case the
# MLRO has decided (or closed), is no longer on the list. An open hit always stays.
_TRUE_MATCH = "COALESCE(q.resolution ILIKE 'true match%%', false)"
_HITS_WHERE = """
    WHERE (COALESCE(q.status, '') <> 'Resolved' OR """ + _TRUE_MATCH + """)
      AND NOT (""" + _TRUE_MATCH + """ AND COALESCE(q.status, '') = 'Resolved' AND EXISTS (
               SELECT 1 FROM aml_sar_links l JOIN suspicious_activities s ON s.id = l.sar_id
                WHERE l.link_type = 'screening_hit' AND l.target_id = q.id AND l.unlinked_at IS NULL
                  AND ((s.decision IS NOT NULL AND s.decision <> '')
                       OR s.investigation_status IN ('NO_STR', 'FILED', 'CLOSED'))))"""


def _open_hits(db, limit=HITS_LIMIT):
    """(rows, total): hits still to act on, most urgent first (confirmed true matches, then the
    oldest), with their STR case and escalation log entry."""
    total = db.execute("SELECT count(*) AS n FROM screening_queue q" + _HITS_WHERE).fetchone()['n']
    rows = [dict(r) for r in db.execute("""
        SELECT q.id, q.entity_name, q.match_name, q.list_source, q.match_score, q.status, q.resolution,
               q.source_module, q.source_record_id, q.created_at
          FROM screening_queue q""" + _HITS_WHERE + """
         ORDER BY """ + _TRUE_MATCH + """ DESC, q.created_at ASC, q.id ASC
         LIMIT %s""", (limit,)).fetchall()]
    if not rows:
        return rows, int(total or 0)
    ids = [r['id'] for r in rows]
    cases = {}
    for l in db.execute("""SELECT l.target_id, s.id, s.sar_reference, s.investigation_status FROM aml_sar_links l
                             JOIN suspicious_activities s ON s.id = l.sar_id
                            WHERE l.link_type = 'screening_hit' AND l.unlinked_at IS NULL AND l.target_id = ANY(%s)""",
                        (ids,)).fetchall():
        cases.setdefault(l['target_id'], dict(l))
    esc = {}
    for f in db.execute("""SELECT id, reference, screening_queue_id, escalated_at, reported_at FROM aml_freeze_log
                            WHERE screening_queue_id = ANY(%s) ORDER BY id""", (ids,)).fetchall():
        f = dict(f)
        f['status'] = EL.status_of(f)
        esc.setdefault(f['screening_queue_id'], f)
    for r in rows:
        r['case'] = cases.get(r['id'])
        r['escalation'] = esc.get(r['id'])
        r['confirmed'] = (r.get('resolution') or '').lower().startswith('true match')
    return rows, int(total or 0)


@aml_bp.route('/hits')
@login_required
@permission_required('aml')
def hits_to_act():
    rows, total = _open_hits(get_db())
    return render_template('aml/p7_hits.html', ar=_ar(), rows=rows, total=total,
                           esc_labels={c: (a if _ar() else en) for c, en, a in EL.STATUSES})


HIT_CASE_LOCK = 71070    # first key of the advisory lock "one STR case per screening hit"


@aml_bp.route('/hits/<int:queue_id>/open-case', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def open_case_from_hit(queue_id):
    """One STR case per screening hit, also when two people click at the same time.

    SR.create_case commits half-way (the case, then its links), so a row lock taken
    with SELECT ... FOR UPDATE would be released before the link exists. A
    session-level advisory lock on the hit is held across those commits instead;
    the partial unique index on aml_sar_links (one active case link per hit,
    migration 20261105_p8aml) is the last guard."""
    db = get_db()
    q = db.execute("SELECT * FROM screening_queue WHERE id = %s", (queue_id,)).fetchone()
    if not q:
        abort(404)
    q = dict(q)

    def existing_case():
        r = db.execute("""SELECT sar_id FROM aml_sar_links WHERE link_type = 'screening_hit' AND target_id = %s
                          AND unlinked_at IS NULL ORDER BY id LIMIT 1""", (queue_id,)).fetchone()
        return r['sar_id'] if r else None

    got = db.execute("SELECT pg_try_advisory_lock(%s, %s) AS ok", (HIT_CASE_LOCK, queue_id)).fetchone()['ok']
    if not got:
        found_sid = existing_case()
        if found_sid:
            return redirect(url_for('aml.sar_detail', sar_id=found_sid))
        flash(_L('Someone is opening a case for this hit right now; try again in a moment.',
                 'يتم فتح حالة لهذه النتيجة الآن بواسطة مستخدم آخر؛ حاول مرة أخرى بعد لحظات.'), 'warning')
        return redirect(url_for('aml.hits_to_act'))
    try:
        found_sid = existing_case()
        if found_sid:
            return redirect(url_for('aml.sar_detail', sar_id=found_sid))
        cid = q['source_record_id'] if q.get('source_module') == 'Customer KYC' else None
        if cid and not db.execute("SELECT 1 FROM customers WHERE id = %s", (cid,)).fetchone():
            cid = None
        found = str(q.get('created_at') or '')[:10] or None
        desc = (f"Screening hit: {q.get('entity_name') or ''} matched {q.get('match_name') or ''} on "
                f"{q.get('list_source') or 'a list'} (score {q.get('match_score') or '-'}; queue #{queue_id}, "
                f"status {q.get('status') or '-'} {q.get('resolution') or ''}).")
        try:
            sid, ref = SR.create_case(source='screening', reported_by=current_user.id, description=desc,
                                      customer_id=cid, customer_name=q.get('entity_name'), discovery_date=found,
                                      activity_date=found, links=[('screening_hit', queue_id)], db=db)
        except Exception as ex:
            import psycopg2
            if not isinstance(ex, psycopg2.IntegrityError):
                raise
            db.rollback()
            found_sid = existing_case()
            if not found_sid:
                raise
            return redirect(url_for('aml.sar_detail', sar_id=found_sid))
        linked = existing_case()
        if linked != sid:
            # the hit could not be linked to the new case (another path linked it first): the new
            # case is marked as opened in error so it is not worked twice, and the linked one is shown
            logger.warning('screening hit %s not linked to new case %s (linked case: %s)', queue_id, sid, linked)
            SR.mark_opened_in_error(sid, f'the screening hit #{queue_id} is on case #{linked}' if linked
                                    else f'the screening hit #{queue_id} could not be linked', current_user.id, db=db)
            if not linked:
                flash(_L('The case could not be linked to the hit; it was marked as opened in error.',
                         'تعذر ربط الحالة بالنتيجة؛ تم تمييزها كحالة فُتحت بالخطأ.'), 'danger')
                return redirect(url_for('aml.hits_to_act'))
            flash(_L('This screening hit is already linked to another case; that case is shown.',
                     'نتيجة الفحص مرتبطة بحالة أخرى بالفعل؛ تم عرض تلك الحالة.'), 'warning')
            return redirect(url_for('aml.sar_detail', sar_id=linked))
        db.execute("UPDATE aml_freeze_log SET sar_id = %s WHERE screening_queue_id = %s AND sar_id IS NULL",
                   (sid, queue_id))
        db.commit()
    finally:
        try:
            db.execute("SELECT pg_advisory_unlock(%s, %s)", (HIT_CASE_LOCK, queue_id))
            db.commit()
        except Exception:
            logger.warning('advisory lock on screening hit %s not released explicitly', queue_id)
    flash(_L(f'STR case {ref} opened from the screening hit.', f'تم فتح حالة الإخطار {ref} من نتيجة الفحص.'), 'success')
    return redirect(url_for('aml.sar_detail', sar_id=sid))


# ----------------------------------------------------------------------------- F6 hit escalation log

@aml_bp.route('/escalation-log')
@login_required
@permission_required('aml')
def escalation_log():
    db = get_db()
    st = request.args.get('status') if request.args.get('status') in EL.STATUS_CODES else None
    tg = EL.targets(db)
    rows = EL.entries(db, status=st)
    for r in rows:
        r['tl'] = EL.timeline(r, tg)
    return render_template('aml/p7_escalation_list.html', ar=_ar(), rows=rows, status=st, statuses=EL.STATUSES,
                           status_labels={c: (a if _ar() else en) for c, en, a in EL.STATUSES},
                           targets=tg, dur=EL.duration_text)


@aml_bp.route('/escalation-log/new', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def escalation_new():
    db = get_db()
    if request.method == 'POST':
        try:
            eid, ref = EL.create(request.form, current_user.id, db)
            flash(_L(f'Escalation log entry {ref} opened. Record the escalation to the MLRO as soon as it is made.',
                     f'تم فتح قيد التصعيد {ref}. سجّل التصعيد لمسؤول الإبلاغ فور حدوثه.'), 'success')
            return redirect(url_for('aml.escalation_view', entry_id=eid))
        except EL.EscalationError as e:
            flash(_msg(e), 'danger')
            pre = request.form
    else:
        pre = {}
        if (request.args.get('queue_id') or '').isdigit():
            pre = EL.from_hit(int(request.args['queue_id']), db) or {}
        if (request.args.get('sar_id') or '').isdigit():
            pre = dict(pre, sar_id=request.args['sar_id'])
            if not pre.get('customer_id'):
                s = db.execute("SELECT customer_id, customer_name FROM suspicious_activities WHERE id = %s",
                               (request.args['sar_id'],)).fetchone()
                if s:
                    pre.update(customer_id=s['customer_id'], subject_name=pre.get('subject_name') or s['customer_name'])
    disc = pre.get('discovered_at')
    disc = disc.strftime('%Y-%m-%dT%H:%M') if isinstance(disc, datetime) else (disc or '')
    return render_template('aml/p7_escalation_new.html', ar=_ar(), pre=pre, disc=disc,
                           now=datetime.now().strftime('%Y-%m-%dT%H:%M'))


@aml_bp.route('/escalation-log/<int:entry_id>', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def escalation_view(entry_id):
    db = get_db()
    try:
        e = EL.get(entry_id, db)
    except EL.EscalationError:
        abort(404)
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        a, f = request.form.get('action'), request.form
        try:
            if a == 'escalate':
                EL.record_escalation(entry_id, f.get('when'), current_user.id, db)
            elif a == 'report':
                EL.record_report(entry_id, f.get('when'), f.get('reported_to'), f.get('reference'), current_user.id, db)
            elif a == 'link' and (f.get('sar_id') or '').isdigit():
                EL.link_case(entry_id, int(f['sar_id']), current_user.id, db)
            else:
                raise EL.EscalationError('Enter the date and time.')
            flash(_L('Escalation log updated.', 'تم تحديث سجل التصعيد.'), 'success')
        except EL.EscalationError as ex:
            flash(_msg(ex), 'danger')
        return redirect(url_for('aml.escalation_view', entry_id=entry_id))
    names = {k: SR.user_name(db, e.get(k)) for k in ('created_by', 'escalated_by', 'reported_by') if e.get(k)}
    cust = db.execute("SELECT id, customer_reference, full_name, company_name FROM customers WHERE id = %s",
                      (e['customer_id'],)).fetchone() if e.get('customer_id') else None
    sar = db.execute("SELECT id, sar_reference, investigation_status FROM suspicious_activities WHERE id = %s",
                     (e['sar_id'],)).fetchone() if e.get('sar_id') else None
    tg = EL.targets(db)
    return render_template('aml/p7_escalation_view.html', ar=_ar(), e=e, tl=EL.timeline(e, tg),
                           targets=tg, dur=EL.duration_text, names=names, cust=cust, sar=sar,
                           statuses=dict((c, (en, a)) for c, en, a in EL.STATUSES),
                           now=datetime.now().strftime('%Y-%m-%dT%H:%M'))


# old addresses of the freeze log (Phase 7) -> the escalation log
@aml_bp.route('/freeze-log')
@login_required
def freeze_log_moved():
    return redirect(url_for('aml.escalation_log'), code=301)


@aml_bp.route('/freeze-log/new')
@login_required
def freeze_new_moved():
    return redirect(url_for('aml.escalation_new', **request.args), code=301)


@aml_bp.route('/freeze-log/<int:entry_id>')
@login_required
def freeze_view_moved(entry_id):
    return redirect(url_for('aml.escalation_view', entry_id=entry_id), code=301)


# ----------------------------------------------------------------------------- F5 STR draft

@aml_bp.route('/sars/<int:sar_id>/draft', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def sar_draft(sar_id):
    db = get_db()
    try:
        facts = SD.facts(sar_id, db)
    except SR.StrError:
        abort(404)
    if not SD.can_see(facts['case'], current_user, _is_mlro()):
        flash(_L('The STR draft is confidential: only the MLRO, the analyst assigned to the case and the person who '
                 'reported it can open it.',
                 'مسودة الإخطار سرية: يطلع عليها مسؤول الإبلاغ والمحلل المكلف بالحالة ومن أبلغ عنها فقط.'), 'warning')
        return redirect(url_for('aml.sar_detail', sar_id=sar_id))
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        try:
            v = SD.save(sar_id, request.form, current_user.id, db)
            flash(_L(f'Draft version {v} saved. The MLRO decides on the case page whether the unit is notified.',
                     f'تم حفظ الإصدار {v} من المسودة. مسؤول الإبلاغ يقرر في صفحة الحالة إخطار الوحدة من عدمه.'),
                  'success')
        except SD.DraftError as e:
            flash(_msg(e), 'danger')
        return redirect(url_for('aml.sar_draft', sar_id=sar_id))
    last = SD.latest(sar_id, db)
    text = last['content'] if last else SD.default_text(facts)
    st = facts['case'].get('investigation_status') or 'NEW'
    return render_template('aml/p7_str_draft.html', ar=_ar(), f=facts, text=text, last=last,
                           versions=SD.versions(sar_id, db), status_labels=SR.status_labels(_ar()), st=st,
                           printing=request.args.get('print') == '1', is_mlro=_is_mlro(),
                           editable=current_user.can_edit('aml') and st not in SR.CLOSED_STATUSES,
                           decided_by=SR.user_name(db, facts['case'].get('decision_by')),
                           dur=EL.duration_text)
