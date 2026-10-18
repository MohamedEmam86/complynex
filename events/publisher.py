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
publish_event(): the single call any module makes to announce something
happened. It only writes a row to compliance_events and enqueues async
processing — it never runs routing-rule actions inline, so a slow action
(e.g. a 1-2s screening call) never blocks the publishing request.

If Redis is unreachable the event row is still committed (status stays
'pending'); it just won't be dispatched until something processes it. There
is no retry sweep in this first cut — a caller-visible warning is logged so
this degradation is noticeable rather than silent.
"""

import json
import logging

from flask_login import current_user

from database.db import get_db

logger = logging.getLogger(__name__)


def publish_event(event_type, source_module, payload=None, source_table=None,
                   source_record_id=None, entity_type=None, entity_id=None,
                   user_id=None):
    """
    Record a compliance event and hand it off for async routing.

    Returns the new compliance_events.id, or None if the insert itself
    failed (this is intentionally non-fatal to the caller — a publish
    failure should never break the request that triggered it).
    """
    if user_id is None:
        try:
            user_id = current_user.id if current_user.is_authenticated else None
        except Exception:
            user_id = None

    db = get_db()
    try:
        cursor = db.execute("""
            INSERT INTO compliance_events
                (event_type, source_module, source_table, source_record_id,
                 entity_type, entity_id, payload, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            event_type, source_module, source_table, source_record_id,
            entity_type, entity_id, json.dumps(payload or {}), user_id,
        ))
        event_id = cursor.fetchone()['id']
        db.commit()
    except Exception:
        logger.exception("Failed to record compliance event %s", event_type)
        return None

    try:
        from events.queue import enqueue_event
        enqueue_event(event_id)
    except Exception:
        logger.warning(
            "compliance_events row %s (%s) committed but could not be enqueued "
            "for dispatch — it will stay 'pending' until reprocessed.",
            event_id, event_type, exc_info=True,
        )

    return event_id
