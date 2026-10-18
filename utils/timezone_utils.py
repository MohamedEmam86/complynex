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

from datetime import datetime, timezone, timedelta

# Cairo is UTC+2 (Egypt does not currently observe DST changes that alter this base offset in standard libraries reliably, but standardizing to an explicit offset is safest)
CAIRO_TZ = timezone(timedelta(hours=2))

def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def now_utc_str() -> str:
    return now_utc().strftime('%Y-%m-%d %H:%M:%S')

def now_cairo() -> datetime:
    return datetime.now(CAIRO_TZ)

def to_cairo_display(dt) -> str:
    if dt is None:
        return '—'
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except Exception:
            return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CAIRO_TZ).strftime('%Y-%m-%d %H:%M')

def today_utc_str() -> str:
    return now_utc().strftime('%Y-%m-%d')
