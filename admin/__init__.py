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
from flask import Blueprint, request, jsonify, abort

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def _get_real_ip():
    """Read real client IP, respecting X-Forwarded-For from nginx."""
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or ''


@admin_bp.before_request
def ip_whitelist_guard():
    """Block /admin/* requests from IPs not in ADMIN_IP_WHITELIST.

    Set ADMIN_IP_WHITELIST=1.2.3.4,10.0.0.0/24 in env to enable.
    When the env var is absent or empty, all IPs are allowed (break-glass).
    """
    raw = os.environ.get('ADMIN_IP_WHITELIST', '').strip()
    if not raw:
        return  # whitelist not configured — open access

    allowed = [ip.strip() for ip in raw.split(',') if ip.strip()]
    if not allowed:
        return

    client_ip = _get_real_ip()

    import ipaddress
    client_addr = None
    try:
        client_addr = ipaddress.ip_address(client_ip)
    except ValueError:
        pass

    for entry in allowed:
        try:
            if '/' in entry:
                if client_addr and client_addr in ipaddress.ip_network(entry, strict=False):
                    return
            else:
                if client_ip == entry:
                    return
        except ValueError:
            continue

    # Log the blocked attempt
    import logging
    logging.getLogger('admin.ip_whitelist').warning(
        'Admin access blocked: ip=%s path=%s', client_ip, request.path
    )

    if request.is_json or request.path.startswith('/admin/terminal'):
        return jsonify({'error': 'Access denied', 'code': 403}), 403
    abort(403)


from admin import routes
