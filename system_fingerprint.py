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
System Fingerprint & Deployment Watermark
==========================================
Generates a hardware-bound, domain-locked fingerprint that:

  1. Is computed once on startup from stable machine identifiers.
  2. Is embedded in every audit log record as `system_fingerprint`.
  3. Is written to a `.fingerprint` file on first run, then verified on
     every subsequent start — if the file is missing or tampered with the
     app logs a critical warning but continues (we don't hard-kill prod).
  4. Exposes `get_fingerprint()` for any module that needs to embed the
     deployment identity in exported documents or API responses.

Fingerprint inputs (all read-only, hardware-stable):
  - Machine-id  (/etc/machine-id or /var/lib/dbus/machine-id)
  - Primary MAC address (lowest non-loopback interface)
  - Registered domain (APP_URL env var, falls back to hostname)
  - A fixed salt tied to Complynex

The fingerprint is a SHA-256 hex digest — deterministic for a given
deployment, unguessable without knowing all four inputs.
"""

import hashlib
import hmac
import logging
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Configuration -----------------------------------------------------------

# Salt is baked in — changing it invalidates all existing fingerprints.
_COMPLYNEX_SALT = b"Complynex-CMS-2026-CBE-Regulated"

# Where the fingerprint is persisted across restarts
_FINGERPRINT_FILE = Path(__file__).parent / ".fingerprint"

# The single computed fingerprint for this process lifetime
_cached: str | None = None


# --- Hardware identifiers ----------------------------------------------------

def _machine_id() -> str:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            text = Path(path).read_text().strip()
            if text:
                return text
        except OSError:
            pass
    # Fallback: hostname (less stable but always available)
    return socket.gethostname()


def _primary_mac() -> str:
    try:
        import uuid as _uuid
        mac = _uuid.getnode()
        # getnode() returns a fake random MAC if it can't find one;
        # the multicast bit (bit 40) is set in that case — detect it.
        if mac >> 40 & 1:
            return "00:00:00:00:00:00"
        return ":".join(f"{(mac >> (i * 8)) & 0xFF:02x}" for i in reversed(range(6)))
    except Exception:
        return "00:00:00:00:00:00"


def _registered_domain() -> str:
    app_url = os.environ.get("APP_URL", "").strip().rstrip("/")
    if app_url:
        # Strip protocol
        for prefix in ("https://", "http://"):
            if app_url.startswith(prefix):
                app_url = app_url[len(prefix):]
        return app_url.split("/")[0].lower()
    return socket.gethostname().lower()


# --- Core fingerprint computation --------------------------------------------

def _compute(machine_id: str, mac: str, domain: str) -> str:
    payload = f"{machine_id}|{mac}|{domain}".encode()
    return hmac.new(_COMPLYNEX_SALT, payload, hashlib.sha256).hexdigest()


def get_fingerprint() -> str:
    """Return the deployment fingerprint (computed once, then cached)."""
    global _cached
    if _cached is None:
        _cached = _compute(_machine_id(), _primary_mac(), _registered_domain())
    return _cached


def get_short_fingerprint() -> str:
    """First 16 hex chars — safe to embed in document headers/exports."""
    return get_fingerprint()[:16].upper()


# --- Startup verification ----------------------------------------------------

def verify_on_startup() -> bool:
    """
    Called once from app.py's create_app().

    First run:  writes the fingerprint + metadata to .fingerprint.
    Later runs: reads and compares; logs CRITICAL if mismatch (tamper/copy).

    Returns True if fingerprint matches (or was just written), False on mismatch.
    """
    fp = get_fingerprint()
    domain = _registered_domain()
    now_iso = datetime.now(timezone.utc).isoformat()

    if not _FINGERPRINT_FILE.exists():
        # First run — register this deployment
        _FINGERPRINT_FILE.write_text(
            f"fingerprint={fp}\n"
            f"domain={domain}\n"
            f"machine_id={_machine_id()}\n"
            f"mac={_primary_mac()}\n"
            f"registered={now_iso}\n"
            f"product=Complynex CMS\n"
            f"licensed_to=ComplyNex Ltd.\n"
        )
        _FINGERPRINT_FILE.chmod(0o400)  # read-only, owner only
        logger.info(
            "System fingerprint registered. Deployment: %s | Domain: %s | "
            "Short ID: %s", now_iso, domain, get_short_fingerprint()
        )
        return True

    # Subsequent runs — verify
    stored_fp = None
    try:
        for line in _FINGERPRINT_FILE.read_text().splitlines():
            if line.startswith("fingerprint="):
                stored_fp = line.split("=", 1)[1].strip()
                break
    except Exception as e:
        logger.critical("Cannot read .fingerprint file: %s", e)
        return False

    if stored_fp != fp:
        logger.critical(
            "DEPLOYMENT FINGERPRINT MISMATCH — This installation may have "
            "been copied to an unauthorised server. "
            "Stored: %s | Computed: %s | Domain: %s",
            stored_fp[:16], fp[:16], domain,
        )
        return False

    logger.info(
        "Deployment fingerprint verified. Short ID: %s | Domain: %s",
        get_short_fingerprint(), domain,
    )
    return True


# --- Audit log integration ---------------------------------------------------

def fingerprint_context() -> dict:
    """
    Returns a dict to merge into every audit log entry so that all records
    carry the deployment identity.  Usage in models/audit.py:

        from system_fingerprint import fingerprint_context
        log_data.update(fingerprint_context())
    """
    return {
        "system_fingerprint": get_short_fingerprint(),
        "deployment_domain": _registered_domain(),
    }


# --- CLI helper --------------------------------------------------------------

if __name__ == "__main__":
    import json

    print(json.dumps({
        "fingerprint": get_fingerprint(),
        "short_id": get_short_fingerprint(),
        "machine_id": _machine_id(),
        "mac": _primary_mac(),
        "domain": _registered_domain(),
        "product": "Complynex CMS",
        "licensed_to": "ComplyNex Ltd.",
    }, indent=2))
