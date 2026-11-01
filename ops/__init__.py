# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Server status page for admins (P6-7). Shows what scripts/ops_monitor.py wrote last
(logs/ops_status.json, every 5 minutes) and the last two days of changes. Read-only."""
import json
import os
from datetime import datetime, timezone

from flask import Blueprint, render_template
from flask_login import login_required

from utils.decorators import admin_required

ops_status_bp = Blueprint('ops_status', __name__)
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    status, history = None, []
    try:
        with open(os.path.join(_BASE, 'logs', 'ops_status.json')) as f:
            status = json.load(f)
    except Exception:
        status = None
    try:
        with open(os.path.join(_BASE, 'logs', 'ops_history.jsonl')) as f:
            history = [json.loads(l) for l in f if l.strip()]
    except Exception:
        history = []
    age_min = None
    if status and status.get('at'):
        try:
            age_min = int((datetime.now(timezone.utc) - datetime.fromisoformat(status['at'])).total_seconds() // 60)
        except Exception:
            age_min = None
    changes = [h for h in history if h.get('overall') != 'ok'][-50:][::-1]
    return status, changes, age_min


@ops_status_bp.route('/admin/server-status')
@login_required
@admin_required
def server_status():
    status, changes, age_min = _load()
    return render_template('ops/server_status.html', status=status, changes=changes, age_min=age_min)
