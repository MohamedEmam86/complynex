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
Next-best-action: DETERMINISTIC gaps for a finding, a control, a case or an
AML register item (missing evidence, overdue actions, required approvals,
verification, SLA left). The AI only phrases these gaps; it never decides
what is required.

Each gap: {code, severity, text_en, text_ar, due}.
"""

from datetime import date

from database.db import get_db

OBJECTS = ('finding', 'control', 'case', 'aml_unusual')


def _g(code, severity, en, ar, due=None):
    return {'code': code, 'severity': severity, 'text_en': en, 'text_ar': ar, 'due': str(due) if due else None}


def finding_gaps(f, today=None):
    today = today or date.today()
    out = []
    if f['status'] == 'closed':
        return out
    acts = f.get('actions') or []
    open_acts = [a for a in acts if a['status'] not in ('done', 'cancelled')]
    if not acts:
        out.append(_g('no_action_plan', 'high', 'Add a corrective-action plan (at least one action with an owner and a due date).',
                      'أضف خطة تصحيح (إجراء واحد على الأقل بمسؤول وتاريخ استحقاق).'))
    for a in open_acts:
        if a.get('due_date') and a['due_date'] < today:
            out.append(_g('action_overdue', 'high', f"Action overdue since {a['due_date']}: {a['description'][:120]}",
                          f"إجراء متأخر منذ {a['due_date']}: {a['description'][:120]}", a['due_date']))
        if not a.get('owner_user_id'):
            out.append(_g('action_no_owner', 'medium', f"Assign an owner to: {a['description'][:120]}",
                          f"حدد مسؤولاً عن: {a['description'][:120]}"))
    if acts and not open_acts and f['status'] not in ('pending_verification',):
        out.append(_g('request_verification', 'medium', 'All actions are done: request verification (the linked controls will be re-tested).',
                      'تم تنفيذ كل الإجراءات: اطلب التحقق (سيُعاد اختبار الضوابط المرتبطة).'))
    if f['status'] == 'pending_verification':
        out.append(_g('verify', 'medium', 'Verify the remediation: re-test the linked controls and close the finding if they pass.',
                      'تحقق من المعالجة: أعد اختبار الضوابط المرتبطة وأغلق الملاحظة إذا نجحت.'))
    failing = [c for c in f.get('controls') or [] if c.get('last_status') in ('fail', 'error')]
    for c in failing[:3]:
        out.append(_g('control_failing', 'high', f"Linked control {c['control_code']} still fails — fix the cause before verification.",
                      f"الضابط المرتبط {c['control_code']} ما زال غير ملتزم — عالج السبب قبل التحقق."))
    if f.get('due_date') and f['due_date'] < today:
        out.append(_g('finding_overdue', 'high', f"The finding is past its due date ({f['due_date']}); escalate or re-plan.",
                      f"الملاحظة تجاوزت تاريخ استحقاقها ({f['due_date']})؛ صعّد أو أعد التخطيط.", f['due_date']))
    if f.get('is_repeated'):
        out.append(_g('repeated', 'critical', 'Repeated violation: identify the root cause, not only the symptom.',
                      'مخالفة متكررة: حدد السبب الجذري وليس العَرَض فقط.'))
    return out


def control_gaps(c, evidence=(), open_findings=0, today=None):
    out = []
    st = c.get('last_status')
    if not st:
        out.append(_g('not_run', 'medium', 'Run the control or record a manual test result.', 'شغّل الضابط أو سجّل نتيجة اختبار يدوي.'))
    if st == 'error':
        out.append(_g('error', 'high', f"The last run could not complete: {(c.get('last_summary') or '')[:160]} — usually a missing parameter or data.",
                      f"تعذر إكمال آخر تشغيل: {(c.get('last_summary') or '')[:160]} — غالباً معامل أو بيانات ناقصة."))
    if st in ('fail', 'warning'):
        out.append(_g('fix', 'high' if st == 'fail' else 'medium',
                      f"Resolve the failing items: {(c.get('last_summary') or '')[:160]}", f"عالج البنود غير الملتزمة: {(c.get('last_summary') or '')[:160]}"))
        if st == 'fail' and not open_findings:
            out.append(_g('raise_finding', 'medium', 'Open a finding with an action plan so the gap is tracked to closure.',
                          'افتح ملاحظة بخطة تصحيح لمتابعة الفجوة حتى الإغلاق.'))
    if c.get('control_type') == 'evidence' or not c.get('check_key'):
        live = [e for e in evidence if e.get('state') in ('valid', 'expiring')]
        if not live:
            out.append(_g('evidence', 'high', 'Upload current evidence for this control (it is reviewed by a second person).',
                          'ارفع دليلاً سارياً لهذا الضابط (يراجعه شخص آخر).'))
        elif any(e.get('state') == 'expiring' for e in live):
            out.append(_g('evidence_expiring', 'medium', 'Evidence expires soon: prepare the renewal.', 'الدليل قارب على الانتهاء: جهّز التجديد.'))
    if not c.get('owner_user_id'):
        out.append(_g('owner', 'low', 'Assign a control owner.', 'حدد مسؤولاً عن الضابط.'))
    return out


def case_gaps(case, today=None):
    today = today or date.today()
    out = []
    if (case.get('status') or '').upper() in ('CLOSED', 'RESOLVED'):
        return out
    due = case.get('due_date')
    due = due.date() if hasattr(due, 'date') else due
    if due:
        left = (due - today).days
        if left < 0:
            out.append(_g('sla_breached', 'high', f"SLA breached {-left} day(s) ago — escalate and record the reason.",
                          f"تم تجاوز مهلة الخدمة منذ {-left} يوم — صعّد وسجّل السبب.", due))
        elif left <= 2:
            out.append(_g('sla_soon', 'medium', f"SLA ends in {left} day(s) ({due}).", f"تنتهي مهلة الخدمة خلال {left} يوم ({due}).", due))
    if not case.get('assigned_to'):
        out.append(_g('assign', 'medium', 'Assign the case to an investigator.', 'أسند الحالة إلى محقق.'))
    return out


def aml_gaps(u, has_docs=False, today=None):
    today = today or date.today()
    out = []
    if u['status'] in ('str_filed', 'no_str', 'dismissed'):
        return out
    if not (u.get('analysis') or '').strip():
        out.append(_g('analysis', 'high', 'Write the analysis (facts checked, customer profile, conclusion).',
                      'اكتب التحليل (الوقائع، ملف العميل، الخلاصة).'))
    if not has_docs:
        out.append(_g('documents', 'high', 'Attach the supporting documents.', 'أرفق المستندات المؤيدة.'))
    if u.get('study_due_date'):
        left = (u['study_due_date'] - today).days
        out.append(_g('study_due', 'high' if left < 0 else 'medium',
                      f"Study {'overdue since' if left < 0 else 'due on'} {u['study_due_date']}.",
                      f"الدراسة {'متأخرة منذ' if left < 0 else 'مستحقة في'} {u['study_due_date']}.", u['study_due_date']))
    out.append(_g('decide', 'medium', 'Decide: file an STR (with reference) or record why no STR is needed.',
                  'قرّر: قدّم إخطار اشتباه (بالمرجع) أو سجّل سبب عدم الحاجة.'))
    return out


def gaps_for(obj_type, obj_id, db=None):
    """→ (gaps, context) for the card. Raises LookupError when the object does not exist."""
    db = db or get_db()
    if obj_type == 'finding':
        from regcontrols.findings import get_finding
        f = get_finding(obj_id, db)
        if not f:
            raise LookupError
        return finding_gaps(f), {'title': f['title'], 'status': f['status'], 'due_date': f['due_date']}
    if obj_type == 'control':
        from regcontrols import evidence as ev
        c = db.execute("SELECT * FROM rc_controls WHERE id = %s", (obj_id,)).fetchone()
        if not c:
            raise LookupError
        c = dict(c)
        evs = [e for e in ev.list_all(db=db) if e['control_id'] == obj_id]
        n = db.execute("""SELECT count(*) AS n FROM rc_findings f JOIN rc_finding_controls fc ON fc.finding_id = f.id
                          WHERE fc.control_id = %s AND f.status <> 'closed'""", (obj_id,)).fetchone()['n']
        last = db.execute("SELECT summary FROM rc_control_runs WHERE control_id = %s ORDER BY id DESC LIMIT 1", (obj_id,)).fetchone()
        c['last_summary'] = last['summary'] if last else None
        return control_gaps(c, evs, n), {'control': c['control_code'], 'title': c['title_en'], 'status': c.get('last_status')}
    if obj_type == 'case':
        r = db.execute("SELECT * FROM cases WHERE id = %s", (obj_id,)).fetchone()
        if not r:
            raise LookupError
        r = dict(r)
        return case_gaps(r), {'reference': r.get('reference'), 'title': r.get('title'), 'status': r.get('status')}
    if obj_type == 'aml_unusual':
        r = db.execute("SELECT * FROM aml_unusual_transactions WHERE id = %s", (obj_id,)).fetchone()
        if not r:
            raise LookupError
        r = dict(r)
        docs = db.execute("""SELECT 1 FROM generic_attachments WHERE module = 'aml' AND record_type = 'aml_unusual' AND record_id = %s
                             AND COALESCE(is_deleted, 0) = 0 LIMIT 1""", (obj_id,)).fetchone()
        return aml_gaps(r, bool(docs)), {k: r.get(k) for k in ('reference', 'subject_name', 'subject_ref', 'source_module',
                                                              'detection_rule', 'detected_at', 'amount', 'description')}
    raise LookupError
