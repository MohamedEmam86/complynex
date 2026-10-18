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
Fixed, regulator-neutral vocabularies of the control engine. Everything that
depends on a regulator or sector (areas, licence types, owner roles,
frameworks, requirements) is data — see catalog.py.
"""

CONTROL_TYPES = {
    'automated': ('Automated rule', 'قاعدة آلية'),
    'evidence': ('Evidence / attestation', 'دليل / إقرار'),
    'workflow': ('Workflow / approval gate', 'سير عمل / بوابة اعتماد'),
    'metric': ('Metric / KPI', 'مؤشر قياس'),
}

# Letters used in control maps (A = automated, E = evidence, W = workflow,
# M = metric); the first letter is the primary type.
TYPE_LETTERS = {'A': 'automated', 'E': 'evidence', 'W': 'workflow', 'M': 'metric'}

FREQUENCIES = {
    'daily': ('Daily', 'يومي'),
    'weekly': ('Weekly', 'أسبوعي'),
    'monthly': ('Monthly', 'شهري'),
    'quarterly': ('Quarterly', 'ربع سنوي'),
    'semi_annual': ('Semi-annual', 'نصف سنوي'),
    'annual': ('Annual', 'سنوي'),
    'event': ('On event', 'عند حدوث واقعة'),
    'on_demand': ('On demand', 'عند الطلب'),
}

CRITICALITY = {
    'critical': ('Critical', 'حرج'),
    'high': ('High', 'مرتفع'),
    'medium': ('Medium', 'متوسط'),
    'low': ('Low', 'منخفض'),
}
