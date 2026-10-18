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
Generic Attachments — shared optional evidence/document upload capability.

Added 2026-07-24. Any module can let a page attach optional supporting
files to one of its records without building its own upload/download/
delete routes and its own DB table: the parent page just needs to
(1) query existing attachments for its (module, record_type, record_id)
via attachments.service.list_attachments() and pass them to its template,
and (2) render templates/partials/attachment_widget.html, which posts to
the two routes in this blueprint.

Attaching evidence is always OPTIONAL — nothing in this blueprint or the
widget makes a file required to save the parent record. That's a
deliberate compliance-process decision (the underlying business record
must always be saveable without evidence attached; evidence can be added
later), not just a technical default.
"""
from flask import Blueprint

attachments_bp = Blueprint('attachments', __name__, url_prefix='/attachments')

from . import routes  # noqa: E402,F401
