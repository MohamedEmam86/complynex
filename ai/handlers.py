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
Routing targets for confirmed intake items. Each handler turns the
confirmed proposal into records through the EXISTING module APIs — the
handler set is code (generic adapters), but which intent uses which handler
and with which parameters is data (ai_intents.handler / handler_params).
Packs may register more handlers with `register_handler`.

A handler returns {'refs': [{type, id, label, url}], 'message': str}.
"""

import os
from datetime import date

from flask import current_app, url_for

from database.db import get_db

HANDLERS = {}


class HandlerError(ValueError):
    pass


def register_handler(code, label_en, label_ar, required=()):
    def deco(fn):
        HANDLERS[code] = {'fn': fn, 'label_en': label_en, 'label_ar': label_ar, 'required': tuple(required)}
        return fn
    return deco


def _url(endpoint, **kw):
    try:
        return url_for(endpoint, **kw)
    except Exception:
        return None


def _desc(item, final):
    lines = [final.get('summary') or '']
    for k, v in (final.get('fields') or {}).items():
        if v:
            lines.append(f'{k}: {v}')
    lines.append(f"(Submitted to Compliance, intake #{item['id']})")
    return '\n'.join(x for x in lines if x is not None)


def _files(item_id):
    from attachments.service import list_attachments
    out = []
    for a in list_attachments('ai', 'ai_intake', item_id) or []:
        p = os.path.realpath(os.path.join(current_app.root_path, a['file_path'] or ''))
        if p.startswith(os.path.realpath(current_app.root_path) + os.sep) and os.path.isfile(p):
            out.append((p, a['filename']))
    return out


@register_handler('manual', 'Manual triage by the owner role', 'فرز يدوي بواسطة المسؤول')
def h_manual(item, final, user, intent):
    from regcontrols.alerts import compliance_heads
    from services.notification_service import notify
    notify(compliance_heads(), 'Submitted to Compliance', f"Intake #{item['id']}: {final.get('summary') or ''}"[:300],
           link=f"/ai/intake/{item['id']}", category='info')
    return {'refs': [], 'message': 'Routed to the compliance team for manual handling.'}


@register_handler('link', 'Open the target module (no record created)', 'فتح الوحدة المختصة (دون إنشاء سجل)')
def h_link(item, final, user, intent):
    ep = (intent.get('handler_params') or {}).get('endpoint')
    u = _url(ep) if ep else None
    return {'refs': [{'type': 'link', 'id': None, 'label': intent['name_en'], 'url': u}] if u else [],
            'message': 'Continue in the target module.'}


@register_handler('guidance', 'Answer from policies (no record created)', 'إجابة من السياسات (دون إنشاء سجل)')
def h_guidance(item, final, user, intent):
    return {'refs': [{'type': 'policy', 'id': p['id'], 'label': p['policy_name'], 'url': p['url']}
                     for p in related_policies(final.get('fields', {}).get('topic') or final.get('summary') or '')],
            'message': 'Related policies listed; no record created.'}


def related_policies(text, limit=5):
    from . import text as T
    db = get_db()
    try:
        rows = [dict(r) for r in db.execute("SELECT id, policy_number, policy_name FROM policies").fetchall()]
    except Exception:
        db.rollback()
        return []
    toks = set(T.tokens(text))
    scored = sorted(((len(toks & set(T.tokens(r['policy_name'] or ''))), r) for r in rows), key=lambda x: -x[0])
    return [dict(r, url=_url('policies.view_policy', id=r['id']) or _url('policies.list_policies')) for s, r in scored[:limit] if s]


@register_handler('finding', 'Finding with action plan (Compliance Controls)', 'ملاحظة بخطة تصحيح (الضوابط الرقابية)', ('title',))
def h_finding(item, final, user, intent):
    from regcontrols.api import raise_finding
    f = final.get('fields') or {}
    title = f.get('title') or final.get('summary') or intent['name_en']
    src = (intent.get('handler_params') or {}).get('source') or 'self_identified'
    due = final.get('deadline')
    fid = raise_finding(title[:390], source=src, severity=final.get('priority') or 'medium', description=_desc(item, final),
                        source_ref=f"ai_intake:{item['id']}", control_codes=final.get('control_codes') or None,
                        owner_user_id=final.get('owner_user_id') or user.id, due_date=date.fromisoformat(due) if due else None,
                        created_by=user.id, dedupe=True)
    return {'refs': [{'type': 'finding', 'id': fid, 'label': title[:80], 'url': _url('regcontrols.finding_detail', finding_id=fid)}],
            'message': 'Finding created.'}


@register_handler('evidence', 'Evidence on a control (pending review)', 'دليل على ضابط (بانتظار المراجعة)', ('title', 'control_code'))
def h_evidence(item, final, user, intent):
    from regcontrols.api import record_evidence
    f = final.get('fields') or {}
    files = _files(item['id'])
    eid = record_evidence(f['control_code'].strip().upper(), f['title'][:250],
                          valid_from=date.fromisoformat(f['valid_from']) if f.get('valid_from') else None,
                          valid_to=date.fromisoformat(f['valid_to']) if f.get('valid_to') else None,
                          reference_no=f.get('reference_no'), description=_desc(item, final), submitted_by=user.id,
                          file_path=files[0][0] if files else None, file_name=files[0][1] if files else None)
    return {'refs': [{'type': 'evidence', 'id': eid, 'label': f['title'][:80], 'url': _url('regcontrols.evidence_detail', evidence_id=eid)}],
            'message': 'Evidence recorded; it waits for review by someone other than you.'}


@register_handler('aml_candidate', 'AML unusual-transactions register (+ finding for orders)', 'سجل العمليات غير العادية (+ ملاحظة للأوامر)')
def h_aml(item, final, user, intent):
    from aml.unusual import register_candidate
    p = intent.get('handler_params') or {}
    f = final.get('fields') or {}
    names = [n.strip() for n in (f.get('subject_names') or f.get('subject_name') or '').replace('\n', ',').split(',') if n.strip()]
    label = (names[0] + (f' (+{len(names) - 1})' if len(names) > 1 else '')) if names else None
    uid, _ = register_candidate(source_module='ai_intake', detection_rule=p.get('detection_rule') or intent['code'],
                                description=_desc(item, final), source_table='ai_intake_items', source_record_id=item['id'],
                                subject_name=(label or '')[:250] or None, subject_ref=(f.get('national_id') or '')[:100] or None,
                                created_by=user.id)
    refs = [{'type': 'aml_unusual', 'id': uid, 'label': label or intent['name_en'], 'url': _url('amlkyc.unusual_item', item_id=uid)}]
    if p.get('finding'):
        refs += h_finding(item, dict(final, fields=dict(f, title=f"{intent['name_en']} {f.get('order_reference') or ''}: "
                                                                f"screen and freeze — {', '.join(names)[:200]}")), user, intent)['refs']
    return {'refs': refs, 'message': 'Registered for AML study.'}


@register_handler('complaint', 'Consumer complaint (complaints module)', 'شكوى عميل (وحدة الشكاوى)',
                  ('customer_name', 'customer_phone', 'complaint_subject'))
def h_complaint(item, final, user, intent):
    from models.consumer_protection import ConsumerComplaint
    f = final.get('fields') or {}
    data = {'customer_name': f['customer_name'], 'customer_phone': f['customer_phone'], 'customer_email': f.get('customer_email'),
            'complaint_channel': 'EMAIL' if item['channel'] == 'email' else 'INTERNAL',
            'complaint_category': f.get('complaint_category') or 'OTHER', 'complaint_subject': f['complaint_subject'][:250],
            'complaint_description': item.get('body') or final.get('summary') or ''}
    cid = ConsumerComplaint.create(data)
    cid = cid.get('id') if isinstance(cid, dict) else cid
    return {'refs': [{'type': 'complaint', 'id': cid, 'label': f['complaint_subject'][:80],
                      'url': _url('consumer_protection.view_complaint', id=cid) or _url('consumer_protection.dashboard')}],
            'message': 'Complaint registered (statutory deadline set by the complaints module).'}


@register_handler('whistleblowing', 'Whistleblowing case (confidential)', 'بلاغ (سري)', ('title',))
def h_whistle(item, final, user, intent):
    from whistleblowing.models import WhistleblowingCase
    f = final.get('fields') or {}
    res = WhistleblowingCase.create({'title': f['title'][:250], 'description': item.get('body') or final.get('summary') or '',
                                     'incident_type': f.get('incident_type') or 'OTHER', 'incident_location': f.get('incident_location'),
                                     'incident_date': f.get('incident_date'), 'severity': {'critical': 'CRITICAL', 'high': 'HIGH'}.get(
                                         final.get('priority'), 'MEDIUM')}, is_anonymous=False, submitter_id=user.id)
    cid = res.get('case_id') if isinstance(res, dict) else res
    return {'refs': [{'type': 'whistleblowing', 'id': cid, 'label': f['title'][:80],
                      'url': _url('whistleblowing.view_case', case_id=cid)}], 'message': 'Confidential case opened.'}


@register_handler('playbook', 'Start a playbook (tasks, evidence, approvals)', 'بدء دليل إجراءات (مهام وأدلة واعتمادات)', ('playbook_code',))
def h_playbook(item, final, user, intent):
    from . import playbooks
    code = final.get('playbook_code') or (intent.get('handler_params') or {}).get('playbook_code')
    if not code:
        raise HandlerError('choose a playbook')
    params = dict(final.get('fields') or {}, **(final.get('playbook_params') or {}))
    try:
        r = playbooks.instantiate(code, params, user.id, suggestion_id=item.get('suggestion_id'),
                                  source_ref=f"ai_intake:{item['id']}:{code}")
    except ValueError as e:
        raise HandlerError(str(e))
    return {'refs': [{'type': 'finding', 'id': r['finding_id'], 'label': f'Playbook {code}',
                      'url': _url('regcontrols.finding_detail', finding_id=r['finding_id'])}],
            'message': 'Playbook started; the tasks were created.'}


def missing(handler, final, intent):
    h = HANDLERS.get(handler)
    if not h:
        return ['handler']
    f = final.get('fields') or {}
    out = []
    for k in h['required']:
        if k == 'playbook_code':
            if not (final.get('playbook_code') or (intent.get('handler_params') or {}).get('playbook_code')):
                out.append(k)
        elif not (str(f.get(k) or '')).strip():
            out.append(k)
    return out


def execute(handler, item, final, user, intent):
    h = HANDLERS.get(handler)
    if not h:
        raise HandlerError('unknown routing target')
    miss = missing(handler, final, intent)
    if miss:
        raise HandlerError('required: ' + ', '.join(miss))
    return h['fn'](item, final, user, intent)
