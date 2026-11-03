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

phishing_bp = Blueprint('phishing', __name__, url_prefix='/phishing')

from phishing import routes  # noqa: E402, F401

# the signed authorisation of a campaign is stored with the generic attachment widget
try:
    from attachments.routes import register_module as _register_attachments
    _register_attachments('phishing')
except Exception:  # pragma: no cover - attachments module missing
    pass
