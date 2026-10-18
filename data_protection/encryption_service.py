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

import os
from cryptography.fernet import Fernet
from flask import current_app
import base64
import hashlib

class EncryptionService:
    """
    Service for encrypting and decrypting sensitive data (PII).
    Uses Fernet (symmetric encryption) from cryptography library.
    """
    
    @staticmethod
    def _get_key():
        """
        Get encryption key from config or secret key.
        Ensures key is 32 url-safe base64-encoded bytes.
        """
        key = os.environ.get('ENCRYPTION_KEY')
        if not key:
            # Fallback to deriving from SECRET_KEY if strict ENCRYPTION_KEY not set
            # This allows it to work with just SECRET_KEY, though dedicated key is better
            secret = current_app.config['SECRET_KEY']
            # Create 32 byte key
            digest = hashlib.sha256(secret.encode()).digest()
            key = base64.urlsafe_b64encode(digest)
        return key

    @staticmethod
    def encrypt_value(value):
        """
        Encrypt a string value.
        """
        if not value:
            return None
        try:
            f = Fernet(EncryptionService._get_key())
            return f.encrypt(value.encode()).decode()
        except Exception as e:
            current_app.logger.error(f"Encryption error: {str(e)}")
            return None

    @staticmethod
    def decrypt_value(encrypted_value):
        """
        Decrypt an encrypted string value.
        """
        if not encrypted_value:
            return None
        try:
            f = Fernet(EncryptionService._get_key())
            return f.decrypt(encrypted_value.encode()).decode()
        except Exception as e:
            # If decryption fails (e.g. wrong key, or data not encrypted), return original or None
            # In migration phase, data might not be encrypted yet, but here we expect encrypted
            current_app.logger.error(f"Decryption error: {str(e)}")
            return None

    @staticmethod
    def hash_value(value):
        """
        Create a deterministic hash of a value for searching/indexing.
        (Encryption is randomized, so can't search by it)
        """
        if not value:
            return None
        salt = current_app.config['SECRET_KEY'][:16] # Use simple salt
        return hashlib.sha256((value + salt).encode()).hexdigest()
