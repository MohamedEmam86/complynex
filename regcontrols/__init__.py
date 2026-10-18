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
regcontrols — FRA regulatory control framework (foundation).

Turns each requirement of docs/regulatory/FRA_NBFI_CONTROL_MAP.md into a
control that is monitored (control engine), evidenced (evidence items with
expiry), remediated (findings & corrective actions with recurrence detection)
and alerted on. Every regulatory number comes from the parameter registry.

Other modules talk to it only through regcontrols/api.py — see
docs/regulatory/REGCONTROLS_API.md.

Layout:
  library.py  seed data (control library + parameters) from the control map
  logic.py    pure decision logic (no Flask/DB) — unit-tested
  params.py   parameter registry + maker-checker change workflow
  engine.py   check registry, control runs, scheduling
  evidence.py evidence items, review, expiry sweep
  findings.py findings, corrective actions, verification, recurrence
  alerts.py   in-app + email alerts, escalation, optional case creation
  routes.py   UI (imported by app.py after the blueprint is created)
"""

from flask import Blueprint

regcontrols_bp = Blueprint('regcontrols', __name__, url_prefix='/regcontrols')
