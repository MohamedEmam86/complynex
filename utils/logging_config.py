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

import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line for ELK/Loki ingestion."""

    def format(self, record):
        payload = {
            'ts': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'module': record.module,
            'msg': record.getMessage(),
            'app': 'complynex-cms',
        }
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(app):
    """Configure rotating plain-text + JSON log handlers for ComplyNex."""

    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Plain rotating log (human-readable, for ops)
    plain_handler = RotatingFileHandler(
        os.path.join(log_dir, 'complynex.log'),
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding='utf-8',
    )
    plain_handler.setLevel(logging.INFO)
    plain_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    ))
    root.addHandler(plain_handler)

    # Structured JSON log (machine-readable, for SIEM/ELK/Loki shipping)
    json_handler = RotatingFileHandler(
        os.path.join(log_dir, 'complynex.json.log'),
        maxBytes=20 * 1024 * 1024,
        backupCount=10,
        encoding='utf-8',
    )
    json_handler.setLevel(logging.INFO)
    json_handler.setFormatter(_JsonFormatter())
    root.addHandler(json_handler)

    # stderr console handler (captured by journald / gunicorn)
    try:
        import sys
        if sys.stderr:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
            root.addHandler(console_handler)
    except Exception:
        pass

    app.logger.setLevel(logging.INFO)
    app.logger.info('Logging configured successfully')
