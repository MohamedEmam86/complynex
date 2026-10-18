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
Unified case dashboard: a cross-cutting rollup over the 4 investigation
tables with a centralized write path (tm_alerts, whistleblowing_cases,
consumer_complaints, cyber_incidents — see models/case.py). Source tables
stay authoritative for workflow; this is oversight/SLA visibility only.
"""

from flask import Blueprint

cases_bp = Blueprint('cases', __name__, url_prefix='/cases')
