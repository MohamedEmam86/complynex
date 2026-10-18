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
Governance log of AI suggestions: every call (model, repaired, fallback or
rules) is recorded with input hash, provider, model, prompt version, output,
latency, and later the user's decision (accept / edit / reject). Prompt
text stays on this server and is purged after the retention period.
"""

import hashlib
import json
from datetime import datetime, timedelta

from database.db import get_db


def input_hash(payload):
    s = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def log(feature, payload, provider, model, prompt_version, output, status='ok', error=None, latency_ms=None,
        prompt_text=None, object_type=None, object_id=None, user_id=None, db=None):
    db = db or get_db()
    rid = db.execute("""INSERT INTO ai_suggestions (feature, object_type, object_id, input_hash, provider, model, prompt_version,
                        prompt_text, output, status, error, latency_ms, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id""",
                     (feature, object_type, object_id, input_hash(payload), provider, model, prompt_version, prompt_text,
                      json.dumps(output, ensure_ascii=False, default=str) if output is not None else None, status,
                      (error or '')[:2000] or None, latency_ms, user_id)).fetchone()['id']
    db.commit()
    return rid


def decide(suggestion_id, decision, user_id, db=None):
    if not suggestion_id or decision not in ('accept', 'edit', 'reject'):
        return
    db = db or get_db()
    db.execute("""UPDATE ai_suggestions SET decision = %s, decided_by = %s, decided_at = %s
                  WHERE id = %s AND decision IS NULL""", (decision, user_id, datetime.now(), suggestion_id))
    db.commit()


def purge(retention_days, db=None, now=None):
    """Drop prompt text (inputs may contain personal data) of suggestions older than the retention
    period; the metadata (hash, provider, model, decision, latency) is kept for accountability."""
    db = db or get_db()
    cutoff = (now or datetime.now()) - timedelta(days=int(retention_days))
    n = db.execute("""UPDATE ai_suggestions SET prompt_text = NULL, output = NULL, purged_at = %s
                      WHERE created_at < %s AND purged_at IS NULL""", (now or datetime.now(), cutoff)).rowcount
    m = db.execute("UPDATE ai_intake_items SET body = NULL WHERE created_at < %s AND status IN ('confirmed', 'rejected') "
                   "AND body IS NOT NULL", (cutoff,)).rowcount
    db.execute("DELETE FROM ai_jobs WHERE created_at < %s", (cutoff,))
    db.commit()
    return {'suggestions': n, 'intake_bodies': m}


def stats(days=30, db=None):
    db = db or get_db()
    since = datetime.now() - timedelta(days=days)
    rows = [dict(r) for r in db.execute("""
        SELECT feature, provider, status, decision, count(*) AS n, round(avg(latency_ms)) AS avg_ms
        FROM ai_suggestions WHERE created_at >= %s GROUP BY feature, provider, status, decision
        ORDER BY feature, provider""", (since,)).fetchall()]
    return rows
