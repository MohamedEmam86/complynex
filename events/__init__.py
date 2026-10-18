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
Compliance Event Bus: a shared publish/route mechanism so modules can react
to each other's activity (e.g. "notify compliance when a screening returns a
high-risk hit") without being directly wired together. See publisher.py for
publish_event(), dispatcher.py for the routing/execution logic, and
routes.py for the admin UI over event_routing_rules.
"""

from flask import Blueprint

events_bp = Blueprint('events', __name__, url_prefix='/events')
