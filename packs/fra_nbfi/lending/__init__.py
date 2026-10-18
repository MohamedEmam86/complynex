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
FRA NBFI pack — Lending Conduct & Portfolio module (FRA-004, 009–026) for
microfinance and consumer-finance companies. ComplyNex is not the core
lending system: data arrives by CSV / Excel import, the pack's JSON API
(POST /api/v1/fra-nbfi/lending/import) or manual entry, and every rule is a
regcontrols check that reads its limits from the parameter registry.
Registered and shown only while the fra_nbfi pack is enabled.
"""

from flask import Blueprint

lending_bp = Blueprint('lending', __name__, url_prefix='/lending')
