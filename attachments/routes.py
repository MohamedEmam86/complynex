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

import os
import logging
from datetime import datetime

from flask import request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from flask_babel import gettext as _

from . import attachments_bp
from database.db import query_db, execute_db
from utils.file_validator import validate_file, secure_filename_strict
from utils.file_serving import serve_uploaded_file

logger = logging.getLogger(__name__)

# Modules allowed to use the generic attachment widget, and the module name
# each maps to for permission checks (current_user.has_permission(module,...)).
# Whitelisting explicitly here (rather than trusting an arbitrary form value)
# stops a crafted request from writing files under a made-up module folder
# or from probing permissions for a module name that doesn't exist.
ALLOWED_MODULES = {
    'esg': 'esg',
    'governance': 'governance',
    'internal_audit': 'internal_audit',
    'aml': 'aml',
    'regcontrols': 'regcontrols',
}


def _check_module(module):
    if module not in ALLOWED_MODULES:
        abort(400, description="Unknown module for attachments")
    return ALLOWED_MODULES[module]


@attachments_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    """
    Generic optional-evidence upload. Expects form fields: module,
    record_type, record_id, file, and an optional description. Always
    redirects back to request.referrer so the parent page doesn't need a
    dedicated success view.
    """
    module = request.form.get('module', '')
    perm_module = _check_module(module)
    if not current_user.has_permission(perm_module, level='edit'):
        flash(_('You do not have permission to attach files here.'), 'danger')
        return redirect(request.referrer or url_for('dashboard'))

    record_type = request.form.get('record_type', '')
    record_id_raw = request.form.get('record_id', '')
    description = (request.form.get('description') or '').strip() or None
    fallback_url = request.referrer or url_for('dashboard')

    if not record_type or not record_id_raw.isdigit():
        flash(_('Invalid attachment target.'), 'danger')
        return redirect(fallback_url)
    record_id = int(record_id_raw)

    file = request.files.get('file')
    if not file or not file.filename:
        # Attaching evidence is optional — a page that posts this form
        # with no file selected should never be treated as an error; it
        # just means nothing to save.
        return redirect(fallback_url)

    is_valid, error = validate_file(file, upload_type='document')
    if not is_valid:
        flash(_('File not accepted: %(error)s', error=error), 'danger')
        return redirect(fallback_url)

    safe_name = secure_filename_strict(file.filename)
    rel_dir = os.path.join('uploads', 'attachments', module, record_type, str(record_id))
    full_dir = os.path.join(current_app.root_path, rel_dir)
    os.makedirs(full_dir, exist_ok=True)
    full_path = os.path.join(full_dir, safe_name)
    file.save(full_path)
    file_size = os.path.getsize(full_path)
    rel_path = os.path.join(rel_dir, safe_name).replace('\\', '/')

    execute_db("""
        INSERT INTO generic_attachments
            (module, record_type, record_id, filename, file_path, file_size,
             description, uploaded_by, uploaded_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (module, record_type, record_id, file.filename[:255], rel_path, file_size,
          description, current_user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    logger.info(f"Attachment uploaded: module={module} record_type={record_type} "
                f"record_id={record_id} by user={current_user.id}")
    flash(_('"%(name)s" attached.', name=file.filename), 'success')
    return redirect(fallback_url)


@attachments_bp.route('/<int:attachment_id>/download')
@login_required
def download(attachment_id):
    row = query_db("SELECT * FROM generic_attachments WHERE id = %s AND is_deleted = 0",
                    (attachment_id,), one=True)
    if not row:
        abort(404)
    perm_module = _check_module(row['module'])
    if not current_user.has_permission(perm_module, level='view'):
        flash(_('You do not have permission to view this attachment.'), 'danger')
        return redirect(url_for('dashboard'))
    return serve_uploaded_file(row['file_path'], download_name=row['filename'], as_attachment=True)


@attachments_bp.route('/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete(attachment_id):
    row = query_db("SELECT * FROM generic_attachments WHERE id = %s AND is_deleted = 0",
                    (attachment_id,), one=True)
    fallback_url = request.referrer or url_for('dashboard')
    if not row:
        flash(_('Attachment not found (it may already be removed).'), 'info')
        return redirect(fallback_url)
    perm_module = _check_module(row['module'])
    # Anyone who uploaded it, or anyone with edit rights on the parent
    # module, may remove it — matches the module's own edit permission
    # rather than a separate attachments-specific permission.
    if row['uploaded_by'] != current_user.id and not current_user.has_permission(perm_module, level='edit'):
        flash(_('You do not have permission to remove this attachment.'), 'danger')
        return redirect(fallback_url)

    # Soft delete only — evidence removal must stay traceable for audit.
    execute_db("""
        UPDATE generic_attachments
        SET is_deleted = 1, deleted_by = %s, deleted_at = %s
        WHERE id = %s
    """, (current_user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), attachment_id))
    flash(_('Attachment removed.'), 'info')
    return redirect(fallback_url)
