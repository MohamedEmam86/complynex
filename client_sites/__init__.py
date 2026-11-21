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
"""Client sites (host-based client sub-domains on the same instance) — see client_sites/service.py.
The superadmin pages are admin/client_sites.py; the sign-in rules are applied in auth/routes.py and load_user."""


def init_app(app):
    """Install the host resolution (first before_request), the per-host session cookie and the template global."""
    if getattr(app, '_cx_sites_installed', False):
        return
    app._cx_sites_installed = True
    from flask import g
    from . import service as S
    app.session_interface = S.SiteSessionInterface()
    app.before_request_funcs.setdefault(None, []).insert(0, S.resolve_request)

    @app.context_processor
    def _inject_client_site():
        return {'client_site': getattr(g, 'client_site', None)}
