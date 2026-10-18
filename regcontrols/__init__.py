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
regcontrols — generic compliance control framework (core of ComplyNex).

Regulators, frameworks, requirements, controls, tests, evidence, findings,
alerts and regulatory parameters are DATA, configurable in the UI, so the
same engine and screens serve any regulator, sector or jurisdiction.
Regulator- or sector-specific content and logic come in optional content
packs (packs/<code>/), enabled per installation — the core never depends on
a pack.

Other modules talk to it through regcontrols/api.py — see
docs/regulatory/REGCONTROLS_API.md.

Layout:
  vocab.py    regulator-neutral vocabularies (control types, frequencies, criticality)
  catalog.py  reference data, frameworks, requirements, control mapping, pack installers
  packs.py    content-pack registry: discover, enable/disable, menus, module permissions
  logic.py    pure decision logic (no Flask/DB) — unit-tested
  params.py   parameter registry + maker-checker change workflow
  engine.py   check registry (by check key), test runs, manual tests, sweeps, scheduling
  evidence.py evidence items, review, expiry sweep
  findings.py findings, corrective actions, verification, recurrence
  alerts.py   in-app + email alerts, escalation, optional case creation
  routes.py   UI (imported by app.py after the blueprint is created)
"""

from flask import Blueprint

regcontrols_bp = Blueprint('regcontrols', __name__, url_prefix='/regcontrols')
