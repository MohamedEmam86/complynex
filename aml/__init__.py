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

aml_bp = Blueprint('aml', __name__, template_folder='templates', url_prefix='/aml')

from . import routes
from . import edd_routes  # noqa: E402,F401  EDD, activation gate, KYB page, high-risk countries

from utils.kyc_labels import register as _register_kyc_labels  # noqa: E402
_register_kyc_labels(aml_bp)
