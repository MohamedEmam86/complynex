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
Purge for the (now-retired) per-side ID check debug capture folder.

ekyc.worker.check_id_side — the synchronous per-side OCR/document-PAD gate
this folder's artifacts were saved for — was removed (see ekyc/worker.py's
docstring for why: routinely 40-60+ seconds on a CPU-only box, customer-
facing capture is now async instead). Nothing writes into DEBUG_ROOT
anymore; purge_expired_debug_captures() stays only to clean up whatever a
pre-existing deployment already wrote there, via the existing daily
complynex-ekyc-purge timer (scripts/ekyc_purge_expired.py) — safe to remove
entirely once a deployment's DEBUG_ROOT has aged out.
"""
import os

DEBUG_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs', 'ekyc_debug')
DEBUG_RETENTION_DAYS = 3


def purge_expired_debug_captures():
    """Deletes debug session folders older than DEBUG_RETENTION_DAYS. Safe to call repeatedly."""
    import time
    if not os.path.isdir(DEBUG_ROOT):
        return 0
    cutoff = time.time() - DEBUG_RETENTION_DAYS * 86400
    purged = 0
    for name in os.listdir(DEBUG_ROOT):
        path = os.path.join(DEBUG_ROOT, name)
        try:
            if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                import shutil
                shutil.rmtree(path, ignore_errors=True)
                purged += 1
        except OSError:
            continue
    return purged
