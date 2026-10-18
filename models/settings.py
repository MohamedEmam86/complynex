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

"""Thin wrapper around the generic system_settings key/value table."""

from database.db import get_db


class Settings:
    @staticmethod
    def get(key, default=None):
        db = get_db()
        row = db.execute('SELECT setting_value FROM system_settings WHERE setting_key = %s', (key,)).fetchone()
        return row['setting_value'] if row and row['setting_value'] is not None else default

    @staticmethod
    def get_bool(key, default=False):
        val = Settings.get(key, None)
        if val is None:
            return default
        return str(val).strip().lower() in ('1', 'true', 'yes', 'on')

    @staticmethod
    def get_int(key, default=0):
        val = Settings.get(key, None)
        try:
            return int(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def get_many(keys):
        if not keys:
            return {}
        db = get_db()
        placeholders = ','.join(['%s'] * len(keys))
        rows = db.execute(
            f'SELECT setting_key, setting_value FROM system_settings WHERE setting_key IN ({placeholders})',
            tuple(keys)
        ).fetchall()
        return {row['setting_key']: row['setting_value'] for row in rows}

    @staticmethod
    def set(key, value, description=None):
        db = get_db()
        existing = db.execute('SELECT setting_key FROM system_settings WHERE setting_key = %s', (key,)).fetchone()
        if existing:
            if description is not None:
                db.execute(
                    'UPDATE system_settings SET setting_value = %s, description = %s, updated_at = CURRENT_TIMESTAMP::TEXT WHERE setting_key = %s',
                    (value, description, key)
                )
            else:
                db.execute(
                    'UPDATE system_settings SET setting_value = %s, updated_at = CURRENT_TIMESTAMP::TEXT WHERE setting_key = %s',
                    (value, key)
                )
        else:
            db.execute(
                'INSERT INTO system_settings (setting_key, setting_value, description, updated_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP::TEXT)',
                (key, value, description)
            )
        db.commit()

    @staticmethod
    def set_many(values: dict):
        for key, value in values.items():
            Settings.set(key, value)
