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
Small helper for parent modules to fetch a record's optional attachments
before rendering a page. Kept separate from attachments/routes.py so a
route module can `from attachments.service import list_attachments`
without importing Flask routing machinery.
"""
from database.db import query_db


def list_attachments(module, record_type, record_id):
    """Return active (non-deleted) attachments for one record, newest first."""
    return query_db("""
        SELECT ga.*, u.first_name, u.last_name
        FROM generic_attachments ga
        LEFT JOIN users u ON ga.uploaded_by = u.id
        WHERE ga.module = %s AND ga.record_type = %s AND ga.record_id = %s
          AND ga.is_deleted = 0
        ORDER BY ga.uploaded_at DESC
    """, (module, record_type, record_id)) or []
