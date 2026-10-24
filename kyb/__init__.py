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
Corporate KYB shared by every register of legal entities (corporate AML
customers, merchants, or a pack's own register): entity identification,
multiple beneficial owners, authorised signatories, and their screening.

logic.py  - pure validation / status rules (unit-tested)
service.py - database access and screening through the public screening service
views.py  - one page handler reused by each module's route
"""
