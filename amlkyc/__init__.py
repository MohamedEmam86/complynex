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
AML & KYC assurance (core, regulator-neutral): key AML roles and
independence, annual MLRO report with board approval, policy board approvals,
AML monitoring programme, screening assurance (required sources, freshness,
QA harness), employee screening, unusual-transactions study, KYC/KYB file
completeness, beneficial owners and declarations, configurable risk model,
onboarding gate with EDD, training coverage and internal-audit coverage.

Generic checks for the regcontrols engine are in checks.py (core.aml.*,
core.kyc.*, core.screening.*, core.audit.*, core.policies.*,
core.training.*); content packs bind their controls to them.
Permission: perm_aml (view / edit).
"""

from flask import Blueprint

amlkyc_bp = Blueprint('amlkyc', __name__, url_prefix='/aml-assurance')
