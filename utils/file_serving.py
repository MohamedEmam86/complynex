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
Shared helper for serving uploaded files that must NOT be reachable through
Flask's unauthenticated /static/<path> route. Each caller is still responsible
for its own authorization check (module permission, ownership, etc.) — this
only handles the actual file lookup/response, safely, via send_from_directory
(which rejects any path attempting to escape the given base directory).
"""
import os
from flask import send_from_directory, current_app, abort


def serve_uploaded_file(relative_path, download_name=None, as_attachment=False):
    """
    Serve a file previously saved under the app's non-static `uploads/`
    directory. `relative_path` is a DB-stored value such as
    'uploads/policies/20260403_file.pdf' — never a value taken directly from
    the request (the caller must have already looked it up from a trusted DB
    row by integer id).
    """
    if not relative_path:
        abort(404, description="No file associated with this record")
    return send_from_directory(
        current_app.root_path,
        relative_path,
        download_name=download_name,
        as_attachment=as_attachment,
    )
