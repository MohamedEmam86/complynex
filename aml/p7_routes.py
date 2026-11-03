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
screening hits that need action with the path to an STR case, the freeze log
(F6) and the STR draft (F5). Business rules live in risk_config,
periodic_review, freeze_log and str_draft; this module only wires the pages.
Every page text is given in English and Arabic (L(en, ar) in the templates).
"""
from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database.db import get_db
from utils import aml_risk
from utils.decorators import permission_required

from . import aml_bp
from . import freeze_log as FL
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
    'Record the freeze before the report.': 'سجّل التجميد قبل الإخطار.',
    'The report cannot be before the freeze.': 'لا يمكن أن يسبق الإخطار التجميد.',
    'A release must come after the freeze.': 'رفع التجميد يجب أن يكون بعد التجميد.',
    'Freeze log entry not found.': 'قيد التجميد غير موجود.',
    'Enter the name of the listed person or entity.': 'أدخل اسم الشخص أو الكيان المدرج.',
    'Enter when the match was discovered (not in the future).': 'أدخل وقت اكتشاف التطابق (ليس في المستقبل).',
    'The freeze is already recorded.': 'التجميد مسجل بالفعل.',
    'Describe what was frozen (accounts, wallets, funds).': 'صف ما تم تجميده (حسابات، محافظ، أموال).',
    'The amount must be a positive number.': 'المبلغ يجب أن يكون رقماً موجباً.',
    'The report is already recorded.': 'الإخطار مسجل بالفعل.',
    'Name the authority the freeze was reported to.': 'اذكر الجهة التي تم إخطارها بالتجميد.',
    'Only the MLRO records the release of a freeze.': 'مسؤول الإبلاغ فقط يسجل رفع التجميد.',
    'The release is already recorded.': 'رفع التجميد مسجل بالفعل.',
    'Give the legal basis of the release (at least 20 characters).': 'اذكر السند القانوني لرفع التجميد (20 حرفاً على الأقل).',
    'STR case not found.': 'حالة الإخطار غير موجودة.',
    'This case is closed without a report; there is no draft to keep.': 'الحالة مغلقة بدون إخطار؛ لا توجد مسودة.',
    'The report is filed; the draft can no longer change.': 'تم إرسال الإخطار؛ لا يمكن تعديل المسودة.',
    'Write the grounds of suspicion (at least 30 characters).': 'اكتب أسباب الاشتباه (30 حرفاً على الأقل).',
}


def _ar():
    from flask_babel import get_locale
    return str(get_locale()) == 'ar'


def _msg(e):
    s = str(e)
    return MSG_AR.get(s, s) if _ar() else s


def _is_mlro():
    return getattr(current_user, 'role', None) in ('compliance_manager', 'admin')


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
            probs = aml_risk.validate(draft)
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
    state = request.args.get('state') if request.args.get('state') in ('overdue', 'due_soon', 'unknown', 'ok') else None
    risk = request.args.get('risk') if request.args.get('risk') in aml_risk.CLASSES else None
    every = PR.portfolio(db, model)
    rows = [r for r in every if (not state or r['state'] == state) and
            (not risk or (r.get('risk_classification') or 'LOW').upper() == risk)]
    return render_template('aml/p7_reviews.html', ar=_ar(), rows=rows[:500], total=len(rows), summary=PR.summary(every),
                           model=model, state=state, risk=risk, outcomes=PR.OUTCOMES, classes=aml_risk.CLASSES)


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
    back = request.form.get('next') or url_for('aml.periodic_reviews')
    if not back.startswith('/'):
        back = url_for('aml.periodic_reviews')
    return redirect(back)


# ----------------------------------------------------------------------------- hits needing action

def _open_hits(db):
    """Screening queue items still open or confirmed (true match), with their case and freeze entries."""
    rows = [dict(r) for r in db.execute("""
        SELECT q.id, q.entity_name, q.match_name, q.list_source, q.match_score, q.status, q.resolution,
               q.source_module, q.source_record_id, q.created_at
          FROM screening_queue q
         WHERE COALESCE(q.status, '') <> 'Resolved' OR q.resolution ILIKE 'true match%%'
         ORDER BY q.created_at DESC LIMIT 300""").fetchall()]
    if not rows:
        return rows
    ids = [r['id'] for r in rows]
    cases = {}
    for l in db.execute("""SELECT l.target_id, s.id, s.sar_reference, s.investigation_status FROM aml_sar_links l
                             JOIN suspicious_activities s ON s.id = l.sar_id
                            WHERE l.link_type = 'screening_hit' AND l.unlinked_at IS NULL AND l.target_id = ANY(%s)""",
                        (ids,)).fetchall():
        cases.setdefault(l['target_id'], dict(l))
    frz = {}
    for f in db.execute("SELECT id, reference, status, screening_queue_id FROM aml_freeze_log WHERE screening_queue_id = ANY(%s)",
                        (ids,)).fetchall():
        frz.setdefault(f['screening_queue_id'], dict(f))
    for r in rows:
        r['case'] = cases.get(r['id'])
        r['freeze'] = frz.get(r['id'])
        r['confirmed'] = (r.get('resolution') or '').lower().startswith('true match')
    return rows


@aml_bp.route('/hits')
@login_required
@permission_required('aml')
def hits_to_act():
    return render_template('aml/p7_hits.html', ar=_ar(), rows=_open_hits(get_db()))


@aml_bp.route('/hits/<int:queue_id>/open-case', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def open_case_from_hit(queue_id):
    db = get_db()
    q = db.execute("SELECT * FROM screening_queue WHERE id = %s", (queue_id,)).fetchone()
    if not q:
        abort(404)
    q = dict(q)
    existing = db.execute("""SELECT sar_id FROM aml_sar_links WHERE link_type = 'screening_hit' AND target_id = %s
                             AND unlinked_at IS NULL LIMIT 1""", (queue_id,)).fetchone()
    if existing:
        return redirect(url_for('aml.sar_detail', sar_id=existing['sar_id']))
    cid = q['source_record_id'] if q.get('source_module') == 'Customer KYC' else None
    if cid and not db.execute("SELECT 1 FROM customers WHERE id = %s", (cid,)).fetchone():
        cid = None
    found = str(q.get('created_at') or '')[:10] or None
    desc = (f"Screening hit: {q.get('entity_name') or ''} matched {q.get('match_name') or ''} on "
            f"{q.get('list_source') or 'a list'} (score {q.get('match_score') or '-'}; queue #{queue_id}, "
            f"status {q.get('status') or '-'} {q.get('resolution') or ''}).")
    sid, ref = SR.create_case(source='screening', reported_by=current_user.id, description=desc, customer_id=cid,
                              customer_name=q.get('entity_name'), discovery_date=found, activity_date=found,
                              links=[('screening_hit', queue_id)], db=db)
    db.execute("UPDATE aml_freeze_log SET sar_id = %s WHERE screening_queue_id = %s AND sar_id IS NULL", (sid, queue_id))
    db.commit()
    flash(_L(f'STR case {ref} opened from the screening hit.', f'تم فتح حالة الإخطار {ref} من نتيجة الفحص.'), 'success')
    return redirect(url_for('aml.sar_detail', sar_id=sid))


# ----------------------------------------------------------------------------- F6 freeze log

@aml_bp.route('/freeze-log')
@login_required
@permission_required('aml')
def freeze_log():
    db = get_db()
    st = request.args.get('status') if request.args.get('status') in FL.STATUS_CODES else None
    tg = FL.targets(db)
    rows = FL.entries(db, status=st)
    for r in rows:
        r['tl'] = FL.timeline(r, tg)
    return render_template('aml/p7_freeze_list.html', ar=_ar(), rows=rows, status=st, statuses=FL.STATUSES,
                           targets=tg, dur=FL.duration_text)


@aml_bp.route('/freeze-log/new', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def freeze_new():
    db = get_db()
    if request.method == 'POST':
        try:
            eid, ref = FL.create(request.form, current_user.id, db)
            flash(_L(f'Freeze log entry {ref} opened. Record the freeze as soon as it is done.',
                     f'تم فتح قيد التجميد {ref}. سجّل التجميد فور تنفيذه.'), 'success')
            return redirect(url_for('aml.freeze_view', entry_id=eid))
        except FL.FreezeError as e:
            flash(_msg(e), 'danger')
            pre = request.form
    else:
        pre = {}
        if (request.args.get('queue_id') or '').isdigit():
            pre = FL.from_hit(int(request.args['queue_id']), db) or {}
        if (request.args.get('sar_id') or '').isdigit():
            pre = dict(pre, sar_id=request.args['sar_id'])
            if not pre.get('customer_id'):
                s = db.execute("SELECT customer_id, customer_name FROM suspicious_activities WHERE id = %s",
                               (request.args['sar_id'],)).fetchone()
                if s:
                    pre.update(customer_id=s['customer_id'], subject_name=pre.get('subject_name') or s['customer_name'])
    disc = pre.get('discovered_at')
    disc = disc.strftime('%Y-%m-%dT%H:%M') if isinstance(disc, datetime) else (disc or '')
    return render_template('aml/p7_freeze_new.html', ar=_ar(), pre=pre, disc=disc,
                           now=datetime.now().strftime('%Y-%m-%dT%H:%M'))


@aml_bp.route('/freeze-log/<int:entry_id>', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def freeze_view(entry_id):
    db = get_db()
    try:
        e = FL.get(entry_id, db)
    except FL.FreezeError:
        abort(404)
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        a, f = request.form.get('action'), request.form
        try:
            if a == 'freeze':
                FL.record_freeze(entry_id, f.get('when'), f.get('scope'), f.get('amount'), current_user.id, db)
            elif a == 'report':
                FL.record_report(entry_id, f.get('when'), f.get('reported_to'), f.get('reference'), current_user.id, db)
            elif a == 'release':
                FL.record_release(entry_id, f.get('when'), f.get('reason'), current_user.id, _is_mlro(), db)
            elif a == 'link' and (f.get('sar_id') or '').isdigit():
                FL.link_case(entry_id, int(f['sar_id']), current_user.id, db)
            else:
                raise FL.FreezeError('Enter the date and time.')
            flash(_L('Freeze log updated.', 'تم تحديث سجل التجميد.'), 'success')
        except FL.FreezeError as ex:
            flash(_msg(ex), 'danger')
        return redirect(url_for('aml.freeze_view', entry_id=entry_id))
    names = {k: SR.user_name(db, e.get(k)) for k in ('created_by', 'frozen_by', 'reported_by') if e.get(k)}
    cust = db.execute("SELECT id, customer_reference, full_name, company_name FROM customers WHERE id = %s",
                      (e['customer_id'],)).fetchone() if e.get('customer_id') else None
    sar = db.execute("SELECT id, sar_reference, investigation_status FROM suspicious_activities WHERE id = %s",
                     (e['sar_id'],)).fetchone() if e.get('sar_id') else None
    return render_template('aml/p7_freeze_view.html', ar=_ar(), e=e, tl=FL.timeline(e, FL.targets(db)),
                           targets=FL.targets(db), dur=FL.duration_text, names=names, cust=cust, sar=sar,
                           statuses=dict((c, (en, a)) for c, en, a in FL.STATUSES), is_mlro=_is_mlro(),
                           now=datetime.now().strftime('%Y-%m-%dT%H:%M'))


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
                           dur=FL.duration_text)
