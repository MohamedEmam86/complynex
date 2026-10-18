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
Compliance Copilot (phase 1) — local-only AI layer.

The AI selects, fills and explains; the correct flow is always defined by
data (intents, playbooks, controls, workflow rules) and every record is
created only after a user confirms. No external AI service is ever called:
see docs/ai/AI_ARCHITECTURE.md.
"""

from flask import Blueprint

ai_bp = Blueprint('ai', __name__, url_prefix='/ai')
