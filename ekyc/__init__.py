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

from flask import Blueprint

ekyc_bp = Blueprint('ekyc', __name__, url_prefix='/ekyc')


def ekyc_enabled():
    """Is the optional eKYC package switched on? (Content packs; no recorded state = on.)"""
    try:
        from flask import g, has_app_context
        from regcontrols import packs as _packs
        if has_app_context():
            state = getattr(g, '_rc_pack_state', None)
            if state is None:
                state = g._rc_pack_state = _packs._state()
        else:
            state = _packs._state()
        row = state.get('ekyc')
        return True if row is None else bool(row.get('enabled'))
    except Exception:
        return True          # never lock people out of eKYC because the switch could not be read


# Customer-facing and machine-to-machine entry points under /ekyc. When the
# package is switched off these must NOT answer 404: a customer already holding
# a verification link, or a vendor posting a webhook/callback, should get a
# "temporarily unavailable" (503) so the link is understood as paused rather
# than gone, and a vendor keeps retrying instead of treating it as permanent.
# Staff/console routes stay hidden (404) when the package is off.
_EKYC_PUBLIC_PREFIXES = ('/ekyc/verify', '/ekyc/webhook', '/ekyc/webhooks',
                         '/ekyc/callback', '/ekyc/callbacks', '/ekyc/vendor')


@ekyc_bp.before_request
def _ekyc_package_guard():
    if not ekyc_enabled():
        from flask import abort, request, Response
        path = (request.path or '').rstrip('/')
        if any(path == p or path.startswith(p + '/') for p in _EKYC_PUBLIC_PREFIXES):
            # temporarily unavailable, not gone: tell the caller to retry later
            return Response('eKYC is temporarily unavailable.', status=503,
                            headers={'Retry-After': '3600'}, mimetype='text/plain')
        abort(404)


@ekyc_bp.app_context_processor
def _ekyc_package_flag():
    return {'ekyc_enabled': ekyc_enabled}
