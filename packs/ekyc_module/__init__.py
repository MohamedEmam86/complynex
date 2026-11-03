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

"""eKYC as an optional package (Phase 7, H4).

Registers eKYC as a content pack so an installation can switch it off (and back
on) on Compliance Controls > Content packs, like any other optional package.
The eKYC code itself stays in ekyc/; while the pack is disabled every eKYC page
answers 404 and its menu entries are hidden. Identity data and retention are not
touched: disabling only closes the pages, enabling opens them again with all
data intact. An installation without a recorded state keeps eKYC on (current use).
"""
from regcontrols.packs import Pack, register_pack


def _install(db):
    return {'module': 'ekyc', 'note': 'eKYC pages enabled'}


register_pack(Pack(
    code='ekyc', version='1',
    name_en='eKYC - remote identity verification',
    name_ar='التحقق الإلكتروني من الهوية (eKYC)',
    description_en='Remote onboarding with ID document capture, OCR, liveness and face match. '
                   'Disable to hide the eKYC pages; data is kept.',
    description_ar='التعريف عن بعد بالتقاط بطاقة الهوية والقراءة الآلية والتحقق من الحيوية ومطابقة الوجه. '
                   'عند التعطيل تختفي صفحات eKYC وتبقى البيانات.',
    install=_install,
))
