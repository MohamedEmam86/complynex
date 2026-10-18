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
Routes one compliance_events row through the enabled event_routing_rules
whose pattern matches, and executes each rule's action. Runs inside the
dedicated event-dispatcher worker process (events/worker.py), never inline
in a web request.

Two action types in this first cut:
  - 'notify': fan out a Notification row to every active user in
    action_config['target_roles'], with {placeholders} in title/message/link
    filled in from the event's payload + top-level columns.
  - 'screen': run screen_and_save() using name/entity_type/dob/nationality
    from the event payload, against source_module/source_record_id from the
    event row. If it comes back with a high-risk match, publishes a
    '<source_module-ish>.screening.hit'-style follow-up event so a 'notify'
    rule can react — kept generic via action_config['hit_event_type'],
    defaulting to 'screening.hit'.

Adding a third action type later (e.g. 'webhook') means adding one more
`elif` here — no changes needed to publishers or to the rules table shape.
"""

import json
import logging

logger = logging.getLogger(__name__)

_app = None


def _get_app():
    global _app
    if _app is None:
        from app import create_app
        _app = create_app()
    return _app


def process_event(event_id):
    """RQ job entrypoint: route and execute actions for one event."""
    app = _get_app()
    with app.app_context():
        _process_event_impl(event_id)


def _matches(pattern, event_type):
    if pattern == event_type:
        return True
    if pattern.endswith('*'):
        return event_type.startswith(pattern[:-1])
    return False


def _process_event_impl(event_id):
    from database.db import get_db
    db = get_db()

    event = db.execute("SELECT * FROM compliance_events WHERE id = %s", (event_id,)).fetchone()
    if not event:
        logger.warning("compliance_events row %s not found, skipping", event_id)
        return

    rules = db.execute("""
        SELECT * FROM event_routing_rules WHERE enabled = true ORDER BY priority ASC, id ASC
    """).fetchall()
    matching = [r for r in rules if _matches(r['event_type_pattern'], event['event_type'])]

    try:
        for rule in matching:
            action_config = rule['action_config'] if isinstance(rule['action_config'], dict) \
                else json.loads(rule['action_config'] or '{}')
            if rule['action_type'] == 'notify':
                _run_notify(event, action_config)
            elif rule['action_type'] == 'screen':
                _run_screen(event)
            else:
                logger.warning("Unknown routing rule action_type %r on rule %s", rule['action_type'], rule['id'])

        db.execute(
            "UPDATE compliance_events SET status = 'processed', processed_at = NOW() WHERE id = %s",
            (event_id,),
        )
        db.commit()
    except Exception as exc:
        logger.exception("Failed dispatching compliance event %s", event_id)
        db.execute(
            "UPDATE compliance_events SET status = 'error', error_message = %s, processed_at = NOW() WHERE id = %s",
            (str(exc)[:2000], event_id),
        )
        db.commit()


def _format(template, event, payload):
    context = {**payload, 'event_type': event['event_type'],
               'source_module': event['source_module'], 'source_record_id': event['source_record_id']}
    try:
        return template.format(**context)
    except (KeyError, IndexError):
        return template


_system_user_id_cache = None


def _system_user_id():
    """Fallback actor for screen_and_save() when an event has no created_by
    (see _run_screen). Cached per worker process — the admin account this
    resolves to doesn't change at runtime."""
    global _system_user_id_cache
    if _system_user_id_cache is None:
        from database.db import get_db
        row = get_db().execute(
            "SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
        ).fetchone()
        _system_user_id_cache = row['id'] if row else None
    return _system_user_id_cache


def _run_notify(event, action_config):
    from models.notification import Notification
    from database.db import get_db

    payload = event['payload'] if isinstance(event['payload'], dict) else json.loads(event['payload'] or '{}')
    target_roles = action_config.get('target_roles') or ['admin']
    title = _format(action_config.get('title', event['event_type']), event, payload)
    message = _format(action_config.get('message', ''), event, payload)
    link = _format(action_config.get('link', ''), event, payload) or None

    db = get_db()
    users = db.execute(
        "SELECT id FROM users WHERE role = ANY(%s) AND is_active = 1",
        (target_roles,),
    ).fetchall()
    for u in users:
        Notification.create(u['id'], title, message, link=link, n_type='compliance_event')


def _run_screen(event):
    from screening.customer_screening_service import screen_and_save
    from events.publisher import publish_event

    payload = event['payload'] if isinstance(event['payload'], dict) else json.loads(event['payload'] or '{}')
    name = payload.get('name')
    if not name or str(name).strip().lower() in ('none', 'null', ''):
        logger.info("Skipping screen action for event %s — no usable name in payload", event['id'])
        return

    # screen_and_save() falls back to flask_login.current_user when user_id is
    # None — there is no request context here, so that fallback would crash.
    # Only reachable if a future producer publishes without a logged-in user
    # (today's producers always run inside a request and set created_by).
    user_id = event['created_by'] or _system_user_id()

    res = screen_and_save(
        name=name,
        entity_type=payload.get('entity_type', 'INDIVIDUAL'),
        dob=payload.get('dob'),
        nationality=payload.get('nationality'),
        source_module=event['source_module'] or 'Event Bus',
        source_record_id=event['source_record_id'],
        screening_type='Automated (Event Bus)',
        user_id=user_id,
        results_screening_type=payload.get('results_screening_type'),
    )

    if res['high_risk_matches'] > 0:
        publish_event(
            event_type=payload.get('hit_event_type', 'screening.hit'),
            source_module=event['source_module'],
            source_table=event['source_table'],
            source_record_id=event['source_record_id'],
            entity_type=event['entity_type'],
            entity_id=event['entity_id'],
            payload={
                'entity_name': name,
                'high_risk_matches': res['high_risk_matches'],
                'highest_score': res['highest_score'],
            },
            user_id=event['created_by'],
        )
