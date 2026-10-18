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
FRA NBFI pack — JSON API for pushing lending data from the core lending system.

    POST /api/v1/fra-nbfi/lending/import      X-API-Key with scope lending:write
    {"kind": "loans", "rows": [{...}, ...]}    (max 5,000 rows per call)

Same columns as the CSV templates (Lending > Import data). Reuses the core
API-key authentication (api/auth.py); answers 404 while the pack is disabled.
"""

from flask import Blueprint, jsonify, request

from api.auth import require_api_key

from . import importer

api_bp = Blueprint('fra_nbfi_lending_api', __name__, url_prefix='/api/v1/fra-nbfi/lending')
api_bp.csrf_exempt = True   # API-key authenticated, no browser session


@api_bp.route('/import', methods=['POST'])
@require_api_key('lending:write')
def lending_import():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data.get('kind') or 'rows' not in data:
        return jsonify({'success': False, 'error': 'Body must be JSON with "kind" and "rows"'}), 422
    if data['kind'] not in importer.KINDS:
        return jsonify({'success': False, 'error': 'Unknown kind; expected one of ' + ', '.join(importer.KINDS)}), 422
    rows = data['rows']
    if not isinstance(rows, list) or len(rows) > 5000:
        return jsonify({'success': False, 'error': 'rows must be a list of at most 5000 objects'}), 422
    batch = importer.import_rows(data['kind'], rows, source='api')
    return jsonify({'success': True, 'data': {
        'batch_id': batch['id'], 'rows_total': batch['rows_total'], 'rows_ok': batch['rows_ok'],
        'rows_failed': batch['rows_failed'], 'errors': batch['errors']}}), 200 if not batch['rows_failed'] else 207
