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
Storage for captured eKYC media (ID frames, selfie frames).

Lives OUTSIDE static/ and templates/ — never web-served — under a
directory with restrictive permissions, since this is biometric/ID data.
Files are encrypted at rest with Fernet (symmetric, authenticated
encryption); the key is versioned via EKYC_ENCRYPTION_KEY_<version> env
vars so a future key rotation can decrypt old files with the old key
while encrypting new ones with the new key, without a flag day. The
active version for new writes is CURRENT_KEY_VERSION below.
"""
import os
import uuid

from cryptography.fernet import Fernet

STORAGE_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ekyc_storage')

CURRENT_KEY_VERSION = 'v1'


def _get_key(version):
    env_var = f'EKYC_ENCRYPTION_KEY_{version.upper()}'
    key = os.environ.get(env_var)
    if not key:
        raise RuntimeError(f"Missing {env_var} — eKYC media encryption key not configured")
    return key.encode()


def _ensure_root():
    os.makedirs(STORAGE_ROOT, mode=0o700, exist_ok=True)
    os.chmod(STORAGE_ROOT, 0o700)


def session_dir(session_token):
    _ensure_root()
    path = os.path.join(STORAGE_ROOT, session_token)
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def save_frame(session_token, doc_role, frame_bytes, ext='jpg'):
    """Encrypts and saves one captured frame. Returns (stored_path, file_size, key_version).

    file_size is the size of the PLAINTEXT frame (what callers care about
    for display/audit), not the slightly larger encrypted blob on disk.
    """
    directory = session_dir(session_token)
    filename = f"{doc_role}_{uuid.uuid4().hex[:12]}.{ext}.enc"
    path = os.path.join(directory, filename)

    fernet = Fernet(_get_key(CURRENT_KEY_VERSION))
    encrypted = fernet.encrypt(frame_bytes)

    with open(path, 'wb') as f:
        f.write(encrypted)
    os.chmod(path, 0o600)
    return path, len(frame_bytes), CURRENT_KEY_VERSION


def read_frame(stored_path, key_version=CURRENT_KEY_VERSION):
    """Reads and decrypts a stored frame. key_version must match what it was encrypted with."""
    with open(stored_path, 'rb') as f:
        encrypted = f.read()
    fernet = Fernet(_get_key(key_version))
    return fernet.decrypt(encrypted)


def delete_frame(stored_path):
    """Permanently removes a stored (encrypted) frame from disk, for retention/purge."""
    if os.path.exists(stored_path):
        os.remove(stored_path)
