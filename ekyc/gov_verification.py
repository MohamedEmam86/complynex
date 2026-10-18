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
Pluggable seam for government-database identity verification (e.g. the
CBE Haweya rail, or a licensed KYC provider's API).

Per the brief, building the actual integration is explicitly OUT of
scope — only this orchestration seam is. Implementing it for real would
mean: (a) a contractual/licensed relationship with a provider, and
(b) sending citizen PII to a third party, which itself needs its own
consent/data-protection review — decisions for Emam, not something to
wire up silently. This stub keeps the call site in the pipeline live and
audited so dropping in a real provider later is a one-function change,
not a pipeline rewrite.
"""
import logging

logger = logging.getLogger(__name__)


def verify_with_government_database(national_id, full_name):
    """
    Returns {'verified': None, 'provider': None, 'note': str} until a
    real provider is configured. 'verified' stays None (not False) —
    "not checked" must never be conflated with "checked and failed" in
    anything consuming this result.
    """
    logger.info(f"Government verification not configured — skipped for national_id={national_id}")
    return {
        'verified': None,
        'provider': None,
        'note': 'Government-database verification is not configured. This is a pluggable seam '
                '(see ekyc/gov_verification.py) — wire in a licensed provider or the CBE Haweya '
                'rail here when available.',
    }
