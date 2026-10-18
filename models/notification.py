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

from datetime import datetime
from database.db import get_db

class Notification:
    def __init__(self, id=None, user_id=None, title=None, message=None, 
                 is_read=0, created_at=None, link=None, type='general'):
        self.id = id
        self.user_id = user_id
        self.title = title
        self.message = message
        self.is_read = is_read
        self.created_at = created_at
        self.link = link
        self.type = type

    @staticmethod
    def create(user_id, title, message, link=None, n_type='general'):
        db = get_db()
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.execute('''
            INSERT INTO notifications (user_id, title, message, link, type, is_read, created_at)
            VALUES (%s, %s, %s, %s, %s, 0, %s)
        ''', (user_id, title, message, link, n_type, created_at))
        db.commit()

    @staticmethod
    def get_unread_for_user(user_id):
        db = get_db()
        rows = db.execute('''
            SELECT * FROM notifications
            WHERE user_id = %s AND is_read = 0
            ORDER BY created_at DESC
        ''', (user_id,)).fetchall()
        return [Notification(**dict(row)) for row in rows]

    @staticmethod
    def get_all_for_user(user_id, limit=200):
        db = get_db()
        rows = db.execute('''
            SELECT * FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        ''', (user_id, limit)).fetchall()
        return [Notification(**dict(row)) for row in rows]

    @staticmethod
    def mark_as_read(notif_id):
        db = get_db()
        db.execute('UPDATE notifications SET is_read = 1 WHERE id = %s', (notif_id,))
        db.commit()

    @staticmethod
    def mark_all_as_read(user_id):
        db = get_db()
        db.execute('UPDATE notifications SET is_read = 1 WHERE user_id = %s', (user_id,))
        db.commit()
