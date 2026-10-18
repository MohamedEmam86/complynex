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
Internal Blacklist Routes
Web interface for managing internal blacklist
"""

from flask import render_template, request, redirect, url_for, flash, jsonify, send_file, Response
from flask_login import login_required, current_user
import json
import csv
import io
import os
import re
from datetime import datetime

from . import blacklist_bp
from screening.internal_blacklist_service import InternalBlacklistService
from screening.internal_pep_service import InternalPEPService
from utils.decorators import permission_required

# Maps normalized variants of real-world sheet headers (EMLCU export, etc.) to
# the canonical field names InternalBlacklistService/InternalPEPService expect.
# Without this, headers like "Full Name (EN)" normalize to "full_name_en" —
# never matching "full_name" — and every row in the sheet gets silently
# dropped before it reaches the DB (the upload still reports "success"
# because 0 failures occurred; there was just nothing to fail).
_HEADER_ALIASES = {
    'full_name_en': 'full_name',
    'name_en': 'full_name',
    'name': 'full_name',
    'original_name_ar': 'original_name',
    'name_ar': 'original_name',
    'arabic_name': 'original_name',
    'passport_no': 'passport_number',
    'passport_num': 'passport_number',
    'registration_no': 'registration_number',
    'reg_no': 'registration_number',
    'reason_designation_basis': 'reason',
    'designation_basis': 'reason',
    'aliases_en': 'aliases',
    'alias': 'aliases',
    'notes_gazette_reference': 'notes',
    'gazette_reference': 'notes',
    'phone': 'phone_number',
    'phone_no': 'phone_number',
    'id_number': 'national_id',
    'national_id_no': 'national_id',
}


def _normalize_header(raw):
    """Lowercase, collapse any run of non-alphanumeric chars to a single
    underscore, then map known sheet-header variants to canonical field names."""
    h = str(raw or '').strip().lower()
    h = re.sub(r'[^a-z0-9]+', '_', h).strip('_')
    return _HEADER_ALIASES.get(h, h)

def _sync_to_watchlist():
    """Push internal_blacklist/internal_pep changes into screening_watchlist
    so added/edited/deleted entries are actually picked up by screening checks."""
    import subprocess
    import sys
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        subprocess.run(
            [sys.executable, os.path.join(base_dir, 'scripts', 'sync_internal_to_watchlist.py')],
            capture_output=True, timeout=120
        )
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"sync_internal_to_watchlist failed: {e}")

    # sync_internal_to_watchlist.py only writes to Postgres (screening_watchlist) —
    # nothing else picks that up and pushes it to Elasticsearch, so without this
    # call new/updated entries sit in Postgres but never become screenable.
    try:
        from screening.routes import trigger_es_incremental_sync
        trigger_es_incremental_sync()
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"trigger_es_incremental_sync failed: {e}")

@blacklist_bp.route('/')
@login_required
@permission_required('screening', level='view')
def index():
    """Main blacklist management page"""
    service = InternalBlacklistService()
    
    # Get filters from request
    filters = {}
    if request.args.get('search'):
        filters['search'] = request.args.get('search')
    if request.args.get('entity_type'):
        filters['entity_type'] = request.args.get('entity_type')
    if request.args.get('risk_level'):
        filters['risk_level'] = request.args.get('risk_level')
    if request.args.get('category'):
        filters['category'] = request.args.get('category')
    # TEAM_CONFIRMED = confirmed by a reviewer resolving a screening case.
    # IMPORTED = bulk-loaded list data. Lets the two be evidenced separately.
    if request.args.get('confirmation_type'):
        filters['confirmation_type'] = request.args.get('confirmation_type')
    
    # Get page
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    # Get sort
    sort_by = request.args.get('sort', 'added_date')
    sort_dir = request.args.get('dir', 'desc')

    # Get entries
    entries, total = service.get_all_entries(filters, page, per_page, sort_by, sort_dir)

    # Get statistics
    stats = service.get_statistics()

    # Calculate pagination
    total_pages = (total + per_page - 1) // per_page

    return render_template('blacklist/index.html',
                         entries=entries,
                         stats=stats,
                         total=total,
                         page=page,
                         per_page=per_page,
                         total_pages=total_pages,
                         filters=filters,
                         sort_by=sort_by,
                         sort_dir=sort_dir)


@blacklist_bp.route('/add', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='edit')
def add():
    """Add new blacklist entry"""
    if request.method == 'POST':
        service = InternalBlacklistService()
        
        # Collect form data
        entry_data = {
            'full_name': request.form.get('full_name'),
            'original_name': request.form.get('original_name'),
            'entity_type': request.form.get('entity_type', 'INDIVIDUAL'),
            'national_id': request.form.get('national_id'),
            'passport_number': request.form.get('passport_number'),
            'date_of_birth': request.form.get('date_of_birth') or None,
            'place_of_birth': request.form.get('place_of_birth'),
            'nationality': request.form.get('nationality'),
            'registration_number': request.form.get('registration_number'),
            'address': request.form.get('address'),
            'city': request.form.get('city'),
            'country': request.form.get('country'),
            'reason': request.form.get('reason'),
            'risk_level': request.form.get('risk_level', 'HIGH'),
            'category': request.form.get('category'),
            'aliases': request.form.get('aliases'),
            'notes': request.form.get('notes'),
            'phone_number': request.form.get('phone_number'),
            'email': request.form.get('email')
        }
        
        try:
            entry_id = service.add_entry(entry_data, current_user.id)
            _sync_to_watchlist()
            flash(f'Blacklist entry added successfully: {entry_data["full_name"]}', 'success')
            return redirect(url_for('blacklist.index'))
        except Exception as e:
            flash(f'Error adding entry: {str(e)}', 'danger')
    
    return render_template('blacklist/add.html')


@blacklist_bp.route('/edit/<int:entry_id>', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='edit')
def edit(entry_id):
    """Edit blacklist entry"""
    service = InternalBlacklistService()
    
    if request.method == 'POST':
        update_data = {
            'full_name': request.form.get('full_name'),
            'original_name': request.form.get('original_name'),
            'entity_type': request.form.get('entity_type'),
            'national_id': request.form.get('national_id'),
            'passport_number': request.form.get('passport_number'),
            'date_of_birth': request.form.get('date_of_birth') or None,
            'place_of_birth': request.form.get('place_of_birth'),
            'nationality': request.form.get('nationality'),
            'registration_number': request.form.get('registration_number'),
            'address': request.form.get('address'),
            'city': request.form.get('city'),
            'country': request.form.get('country'),
            'reason': request.form.get('reason'),
            'risk_level': request.form.get('risk_level'),
            'category': request.form.get('category'),
            'aliases': request.form.get('aliases'),
            'notes': request.form.get('notes'),
            'phone_number': request.form.get('phone_number'),
            'email': request.form.get('email')
        }
        
        try:
            service.update_entry(entry_id, update_data, current_user.id)
            _sync_to_watchlist()
            flash('Blacklist entry updated successfully', 'success')
            return redirect(url_for('blacklist.index'))
        except Exception as e:
            flash(f'Error updating entry: {str(e)}', 'danger')
    
    # GET request - show form with current data
    entry = service.get_entry(entry_id)
    if not entry:
        flash('Entry not found', 'danger')
        return redirect(url_for('blacklist.index'))
    
    return render_template('blacklist/edit.html', entry=entry)


@blacklist_bp.route('/delete/<int:entry_id>', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def delete(entry_id):
    """Delete (deactivate) blacklist entry"""
    service = InternalBlacklistService()
    
    reason = request.form.get('reason', 'Deleted by user')
    
    try:
        service.delete_entry(entry_id, current_user.id, reason)
        _sync_to_watchlist()
        flash('Blacklist entry deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting entry: {str(e)}', 'danger')
    
    return redirect(url_for('blacklist.index'))


@blacklist_bp.route('/view/<int:entry_id>')
@login_required
@permission_required('screening', level='view')
def view(entry_id):
    """View blacklist entry details"""
    service = InternalBlacklistService()
    
    entry = service.get_entry(entry_id)
    if not entry:
        flash('Entry not found', 'danger')
        return redirect(url_for('blacklist.index'))
    
    # Get audit log
    conn = service.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            iba.*,
            u.first_name || ' ' || u.last_name as changed_by_username
        FROM internal_blacklist_audit iba
        LEFT JOIN users u ON iba.changed_by = u.id
        WHERE iba.blacklist_id = %s
        ORDER BY iba.changed_at DESC
    """, (entry_id,))
    
    audit_log = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return render_template('blacklist/view.html', entry=entry, audit_log=audit_log)


@blacklist_bp.route('/bulk_upload', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='edit')
def bulk_upload():
    """Bulk upload blacklist entries from CSV/Excel"""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        
        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(request.url)
        
        if not (file.filename.endswith('.csv') or file.filename.endswith('.xlsx')):
            flash('Invalid file format. Please upload CSV or Excel file', 'danger')
            return redirect(request.url)
        
        try:
            # Parse file
            if file.filename.endswith('.csv'):
                entries_list = parse_csv(file)
            else:
                entries_list = parse_excel(file)
            
            # Import entries
            service = InternalBlacklistService()
            stats = service.bulk_import(entries_list, current_user.id, file.filename)
            _sync_to_watchlist()

            if stats['failed'] > 0:
                error_preview = '; '.join(stats['errors'][:5])
                flash(f'Import completed: {stats["successful"]}/{stats["total"]} successful. {stats["failed"]} failed: {error_preview}', 'warning')
            else:
                flash(f'Import completed: {stats["successful"]}/{stats["total"]} entries added successfully', 'success')
            
            return redirect(url_for('blacklist.index'))
            
        except Exception as e:
            flash(f'Error importing file: {str(e)}', 'danger')
    
    return render_template('blacklist/bulk_upload.html')


@blacklist_bp.route('/download_template')
@login_required
@permission_required('screening', level='view')
def download_template():
    """Download CSV template for bulk upload"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'full_name', 'original_name', 'entity_type', 'national_id', 
        'passport_number', 'date_of_birth', 'place_of_birth', 'nationality',
        'registration_number', 'address', 'city', 'country', 'reason',
        'risk_level', 'category', 'aliases', 'notes', 'phone_number', 'email'
    ])
    
    # Write example row
    writer.writerow([
        'John Doe', 'جون دو', 'INDIVIDUAL', '12345678901234', 
        'A1234567', '1980-01-15', 'Cairo', 'Egyptian',
        '', '123 Main St', 'Cairo', 'Egypt', 'Fraud investigation',
        'HIGH', 'Fraud', 'Johnny,J.Doe', 'Additional notes here',
        '+20123456789', 'john.doe@example.com'
    ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-disposition": "attachment; filename=blacklist_template.csv"}
    )


@blacklist_bp.route('/export')
@login_required
@permission_required('screening', level='view')
def export():
    """Export blacklist to CSV"""
    service = InternalBlacklistService()
    
    # Get all active entries
    entries, _ = service.get_all_entries({'is_active': True}, page=1, per_page=10000)
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'ID', 'Full Name', 'Original Name', 'Entity Type', 'National ID',
        'Passport', 'Date of Birth', 'Nationality', 'Address', 'City', 'Country',
        'Reason', 'Risk Level', 'Category', 'Aliases', 'Added Date', 'Added By'
    ])
    
    # Write data
    for entry in entries:
        writer.writerow([
            entry['id'],
            entry['full_name'],
            entry['original_name'] or '',
            entry['entity_type'],
            entry['national_id'] or '',
            entry['passport_number'] or '',
            entry['date_of_birth'] or '',
            entry['nationality'] or '',
            entry['address'] or '',
            entry['city'] or '',
            entry['country'] or '',
            entry['reason'],
            entry['risk_level'],
            entry['category'] or '',
            ', '.join(entry['aliases']) if entry['aliases'] else '',
            entry['added_date'],
            entry['added_by_username'] or ''
        ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-disposition": f"attachment; filename=internal_blacklist_export_{datetime.now().strftime('%Y%m%d')}.csv"}
    )


def parse_csv(file):
    """Parse CSV file into list of entry dictionaries"""
    # Read file
    content = file.stream.read().decode("utf-8-sig") # Handle BOM
    stream = io.StringIO(content)
    reader = csv.DictReader(stream)

    entries = []
    for row in reader:
        # Normalize headers (handles real-world variants like "Full Name (EN)")
        # and strip whitespace from values
        entry = {}
        for k, v in row.items():
            if not k:
                continue
            entry[_normalize_header(k)] = v.strip() if isinstance(v, str) else v
        # Use original_name as fallback if full_name is missing
        if not entry.get('full_name') and entry.get('original_name'):
            entry['full_name'] = entry['original_name']
        if not entry.get('full_name'):
            continue
        entries.append(entry)

    return entries


def parse_excel(file):
    """Parse Excel file into list of entry dictionaries"""
    import openpyxl
    
    workbook = openpyxl.load_workbook(file, data_only=True)
    sheet = workbook.active
    
    # Get header row and clean it up
    header = []
    for cell in sheet[1]:
        if cell.value:
            header.append(_normalize_header(cell.value))
        else:
            header.append(None)
    
    entries = []
    # Identify the last row with data to avoid processing thousands of empty rows if any
    for row in sheet.iter_rows(min_row=2, values_only=True):
        # Skip if the entire row is empty
        if not any(val is not None and str(val).strip() != '' for val in row):
            continue
            
        entry = {}
        for idx, value in enumerate(row):
            if idx < len(header) and header[idx]:
                # Special handling for dates
                if isinstance(value, datetime):
                    entry[header[idx]] = value.strftime('%Y-%m-%d')
                else:
                    entry[header[idx]] = str(value).strip() if value is not None else None
        
        # Use original_name as fallback if full_name missing
        if not entry.get('full_name') and entry.get('original_name'):
            entry['full_name'] = entry['original_name']
        # Only add if we have at least a name
        if entry.get('full_name'):
            entries.append(entry)
    
    return entries


@blacklist_bp.route('/pep')
@login_required
@permission_required('screening', level='view')
def pep_index():
    """Internal PEP List management page"""
    service = InternalPEPService()

    filters = {}
    if request.args.get('search'):
        filters['search'] = request.args.get('search')
    if request.args.get('entity_type'):
        filters['entity_type'] = request.args.get('entity_type')
    if request.args.get('risk_level'):
        filters['risk_level'] = request.args.get('risk_level')
    if request.args.get('category'):
        filters['category'] = request.args.get('category')

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    sort_by = request.args.get('sort', 'added_date')
    sort_dir = request.args.get('dir', 'desc')

    entries, total = service.get_all_entries(filters, page, per_page, sort_by, sort_dir)
    stats = service.get_statistics()
    total_pages = (total + per_page - 1) // per_page

    return render_template('blacklist/pep_index.html',
                         entries=entries,
                         stats=stats,
                         total=total,
                         page=page,
                         per_page=per_page,
                         total_pages=total_pages,
                         filters=filters,
                         sort_by=sort_by,
                         sort_dir=sort_dir)


@blacklist_bp.route('/pep/add', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='edit')
def pep_add():
    """Add a new Internal PEP entry"""
    service = InternalPEPService()
    if request.method == 'POST':
        try:
            entry_data = {
                'full_name': request.form.get('full_name', '').strip(),
                'original_name': request.form.get('original_name', '').strip() or None,
                'entity_type': request.form.get('entity_type', 'INDIVIDUAL'),
                'national_id': request.form.get('national_id', '').strip() or None,
                'passport_number': request.form.get('passport_number', '').strip() or None,
                'date_of_birth': request.form.get('date_of_birth') or None,
                'nationality': request.form.get('nationality', '').strip() or None,
                'country': request.form.get('country', '').strip() or None,
                'reason': request.form.get('reason', '').strip(),
                'risk_level': request.form.get('risk_level', 'HIGH'),
                'category': request.form.get('category', '').strip() or None,
                'position': request.form.get('position', '').strip() or None,
                'notes': request.form.get('notes', '').strip() or None,
            }
            if not entry_data['full_name']:
                flash('Full name is required', 'error')
                return render_template('blacklist/pep_add.html')
            if not entry_data['reason']:
                flash('Reason is required', 'error')
                return render_template('blacklist/pep_add.html')
            entry_id = service.add_entry(entry_data, user_id=current_user.id)
            if entry_id:
                _sync_to_watchlist()
                flash(f"PEP entry added successfully.", 'success')
            else:
                flash(f"Entry already exists in the list.", 'warning')
            return redirect(url_for('blacklist.pep_index'))
        except Exception as e:
            flash(f'Error adding entry: {str(e)}', 'error')
    return render_template('blacklist/pep_add.html')


@blacklist_bp.route('/pep/delete/<int:entry_id>', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def pep_delete(entry_id):
    """Delete a PEP entry"""
    service = InternalPEPService()
    try:
        service.delete_entry(entry_id, user_id=current_user.id)
        _sync_to_watchlist()
        flash('PEP entry deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting entry: {str(e)}', 'error')
    return redirect(url_for('blacklist.pep_index'))


@blacklist_bp.route('/pep/bulk_upload', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='edit')
def pep_bulk_upload():
    """Bulk upload PEP list entries from CSV/Excel"""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded', 'danger')
            return redirect(request.url)

        file = request.files['file']

        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(request.url)

        if not (file.filename.endswith('.csv') or file.filename.endswith('.xlsx')):
            flash('Invalid file format. Please upload CSV or Excel file', 'danger')
            return redirect(request.url)

        try:
            if file.filename.endswith('.csv'):
                entries_list = parse_csv(file)
            else:
                entries_list = parse_excel(file)

            service = InternalPEPService()
            stats = service.bulk_import(entries_list, current_user.id, file.filename)
            _sync_to_watchlist()

            flash(f'Import completed: {stats["successful"]}/{stats["total"]} successful', 'success')

            if stats['failed'] > 0:
                from flask import session
                session['import_errors'] = stats['errors']

            return redirect(url_for('blacklist.pep_index'))

        except Exception as e:
            flash(f'Error importing file: {str(e)}', 'danger')

    return render_template('blacklist/pep_bulk_upload.html')


@blacklist_bp.route('/pep/download_template')
@login_required
@permission_required('screening', level='view')
def pep_download_template():
    """Download CSV template for PEP bulk upload"""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        'full_name', 'original_name', 'entity_type', 'national_id',
        'passport_number', 'date_of_birth', 'place_of_birth', 'nationality',
        'registration_number', 'address', 'city', 'country', 'reason',
        'risk_level', 'category', 'position', 'aliases', 'notes', 'phone_number', 'email'
    ])

    writer.writerow([
        'Ahmed Al-Rashid', 'أحمد الراشد', 'INDIVIDUAL', '12345678901234',
        'A1234567', '1975-06-20', 'Riyadh', 'Saudi Arabian',
        '', '456 Palace Rd', 'Riyadh', 'Saudi Arabia', 'Politically Exposed Person',
        'HIGH', 'GOVERNMENT', 'Minister of Finance', 'A.Rashid', 'Cabinet member since 2015',
        '+966512345678', 'ahmed@example.com'
    ])

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-disposition": "attachment; filename=pep_list_template.csv"}
    )


@blacklist_bp.route('/pep/view/<int:entry_id>')
@login_required
@permission_required('screening', level='view')
def pep_view(entry_id):
    """View PEP entry details"""
    service = InternalPEPService()
    entry = service.get_entry(entry_id)
    if not entry:
        flash('Entry not found', 'danger')
        return redirect(url_for('blacklist.pep_index'))
    conn = service.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ipa.*, u.first_name || ' ' || u.last_name as changed_by_username
        FROM internal_pep_audit ipa
        LEFT JOIN users u ON ipa.changed_by = u.id
        WHERE ipa.blacklist_id = %s
        ORDER BY ipa.changed_at DESC
    """, (entry_id,))
    audit_log = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return render_template('blacklist/pep_view.html', entry=entry, audit_log=audit_log)


@blacklist_bp.route('/pep/edit/<int:entry_id>', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='edit')
def pep_edit(entry_id):
    """Edit PEP entry"""
    service = InternalPEPService()
    if request.method == 'POST':
        update_data = {
            'full_name': request.form.get('full_name'),
            'original_name': request.form.get('original_name'),
            'entity_type': request.form.get('entity_type'),
            'national_id': request.form.get('national_id'),
            'passport_number': request.form.get('passport_number'),
            'date_of_birth': request.form.get('date_of_birth') or None,
            'place_of_birth': request.form.get('place_of_birth'),
            'nationality': request.form.get('nationality'),
            'registration_number': request.form.get('registration_number'),
            'address': request.form.get('address'),
            'city': request.form.get('city'),
            'country': request.form.get('country'),
            'reason': request.form.get('reason'),
            'risk_level': request.form.get('risk_level'),
            'category': request.form.get('category'),
            'position': request.form.get('position'),
            'aliases': request.form.get('aliases'),
            'notes': request.form.get('notes'),
            'phone_number': request.form.get('phone_number'),
            'email': request.form.get('email')
        }
        try:
            service.update_entry(entry_id, update_data, current_user.id)
            _sync_to_watchlist()
            flash('PEP entry updated successfully', 'success')
            return redirect(url_for('blacklist.pep_index'))
        except Exception as e:
            flash(f'Error updating entry: {str(e)}', 'danger')
    entry = service.get_entry(entry_id)
    if not entry:
        flash('Entry not found', 'danger')
        return redirect(url_for('blacklist.pep_index'))
    return render_template('blacklist/pep_edit.html', entry=entry)
