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

"""One KYB page handler, mounted by each module that holds legal entities."""

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from models.audit import AuditLog
from utils.kyc_labels import tr
from . import logic, service
from .service import KybError

AUDIT_MODULE = {'merchant': 'Merchant KYC', 'aml_customer': 'AML'}


def _flash_all(messages, category):
    for m in messages:
        flash(tr(m), category)


def handle(subject, subject_id, *, self_endpoint, back_url, can_edit, title_prefix, after_change=None):
    """GET: render the KYB page. POST: one action, then redirect back (PRG).

    after_change(subject_id) runs after any change (e.g. the customer risk floor).
    """
    ent = service.entity(subject, subject_id)
    if not ent:
        flash(tr('Record not found.'), 'danger')
        return redirect(back_url)
    here = url_for(self_endpoint, id=subject_id)

    if request.method == 'POST':
        if not can_edit:
            flash(tr('You do not have permission to change this KYB file.'), 'danger')
            return redirect(here)
        action = request.form.get('action', '')
        module = AUDIT_MODULE.get(subject, 'KYB')
        try:
            if action == 'save_entity':
                service.save_entity(subject, subject_id, request.form, current_user.id)
                AuditLog.log(current_user.id, 'KYB Entity Updated', module, subject_id,
                             f'KYB entity details updated for {ent["name"]}', request.remote_addr)
                flash(tr('Entity details saved.'), 'success')
            elif action in ('save_ubo', 'save_signatory'):
                kind = 'ubo' if action == 'save_ubo' else 'signatory'
                pid = request.form.get('person_id', type=int)
                pid, warnings = service.save_person(kind, subject, subject_id, request.form, current_user.id,
                                                    person_id=pid)
                AuditLog.log(current_user.id, 'KYB ' + ('Owner' if kind == 'ubo' else 'Signatory') + ' Saved',
                             module, subject_id, f'{kind} #{pid} "{request.form.get("full_name", "")}" saved '
                             f'for {ent["name"]} and screened', request.remote_addr)
                flash(tr('Saved. The person was screened; the result is shown in the list.'), 'success')
                _flash_all(warnings, 'warning')
            elif action in ('delete_ubo', 'delete_signatory'):
                kind = 'ubo' if action == 'delete_ubo' else 'signatory'
                row = service.delete_person(kind, subject, subject_id, request.form.get('person_id', type=int))
                if row:
                    AuditLog.log(current_user.id, 'KYB ' + ('Owner' if kind == 'ubo' else 'Signatory') + ' Removed',
                                 module, subject_id,
                                 f'{kind} "{row.get("full_name")}" removed from {ent["name"]} '
                                 f'(ownership {row.get("ownership_pct")}, ID {row.get("id_type")})', request.remote_addr)
                    flash(tr('Removed.'), 'success')
            elif action == 'screen_all':
                n = service.screen_all(subject, subject_id, current_user.id,
                                       only_needed=request.form.get('force') != '1')
                AuditLog.log(current_user.id, 'KYB Screening', module, subject_id,
                             f'{n} owner(s)/signatory(ies) screened for {ent["name"]}', request.remote_addr)
                flash(tr(('%(n)s person(s) screened.', {'n': n})), 'info')
            else:
                flash(tr('Unknown action.'), 'danger')
                return redirect(here)
        except KybError as e:
            _flash_all(e.messages, 'danger')
            return redirect(here)
        if after_change:
            after_change(subject_id)
        return redirect(here)

    ubos, sigs, states = service.with_states(subject, subject_id)
    errors, warnings = logic.validate_ubos(ubos) if ubos else ([], [])
    edit_ubo = next((u for u in ubos if u['id'] == request.args.get('edit_ubo', type=int)), None)
    edit_sig = next((s for s in sigs if s['id'] == request.args.get('edit_signatory', type=int)), None)
    return render_template('kyb/kyb_page.html', subject=subject, ent=ent, ubos=ubos, signatories=sigs,
                           blockers=logic.approval_blockers(ent, ubos, sigs, states),
                           ubo_errors=errors, ubo_warnings=warnings, total_pct=logic.total_ownership(ubos),
                           edit_ubo=edit_ubo, edit_sig=edit_sig, can_edit=can_edit, here=here, back_url=back_url,
                           title_prefix=title_prefix, legal_forms=logic.LEGAL_FORMS,
                           control_types=logic.CONTROL_TYPES, id_types=logic.ID_TYPES,
                           signing_authorities=logic.SIGNING_AUTHORITIES, blocking_states=logic.BLOCKING_STATES)
