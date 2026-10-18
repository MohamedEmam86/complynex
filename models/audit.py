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

try:
    from system_fingerprint import get_short_fingerprint as _fp
except Exception:
    _fp = lambda: "UNKNOWN"

try:
    from utils.metrics import audit_events as _audit_events_counter
except Exception:
    _audit_events_counter = None

class AuditLog:
    def __init__(self, id=None, user_id=None, action=None, 
                 module=None, item_id=None, details=None, 
                 created_at=None, ip_address=None, user_name=None):
        self.id = id
        self.user_id = user_id
        self.user_name = user_name
        self.action = action
        self.module = module
        self.item_id = item_id
        self.details = details
        self.details = details
        
        # Ensure created_at is a datetime object
        if isinstance(created_at, str):
            try:
                # Try common SQLite formats
                self.created_at = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                try:
                    self.created_at = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    self.created_at = datetime.now() # Fallback
        else:
            self.created_at = created_at
            
        self.ip_address = ip_address

    @staticmethod
    def log(user_id, action, module=None, item_id=None, details=None, ip_address=None):
        db = get_db()
        watermark = f"[deploy:{_fp()}]"
        stamped_details = f"{details} {watermark}" if details else watermark
        db.execute('''
            INSERT INTO audit_logs (user_id, action, module, item_id, details, ip_address, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, action, module, item_id, stamped_details, ip_address, datetime.now()))
        db.commit()
        if _audit_events_counter is not None:
            try:
                _audit_events_counter.labels(module=module or 'unknown').inc()
            except Exception:
                pass

    @staticmethod
    def get_all(filters=None):
        db = get_db()
        query = '''
            SELECT a.*, u.first_name || ' ' || u.last_name as user_name, u.role as user_role, u.email as user_email
            FROM audit_logs a
            LEFT JOIN users u ON a.user_id = u.id
            WHERE 1=1
        '''
        params = []
        if filters:
            if filters.get('user_id'):
                query += " AND a.user_id = %s"
                params.append(filters['user_id'])
            if filters.get('module'):
                query += " AND a.module = %s"
                params.append(filters['module'])
            if filters.get('action'):
                query += " AND a.action = %s"
                params.append(filters['action'])
            if filters.get('search'):
                query += " AND (a.details LIKE %s OR u.first_name LIKE %s OR u.last_name LIKE %s OR u.email LIKE %s)"
                search_term = f"%{filters['search']}%"
                params.extend([search_term, search_term, search_term, search_term])
            if filters.get('date_from'):
                query += " AND date(a.created_at) >= %s"
                params.append(filters['date_from'])
            if filters.get('date_to'):
                query += " AND date(a.created_at) <= %s"
                params.append(filters['date_to'])
        
        query += " ORDER BY a.created_at DESC"
        rows = db.execute(query, params).fetchall()
        
        logs = []
        for row in rows:
            log_dict = dict(row)
            log = AuditLog(**{k: v for k, v in log_dict.items() if k != 'user_role' and k != 'user_email'})
            log.user_role = log_dict.get('user_role')
            log.user_email = log_dict.get('user_email')
            logs.append(log)
        return logs

    @staticmethod
    def get_recent(limit=100):
        db = get_db()
        query = '''
            SELECT a.*, u.first_name || ' ' || u.last_name as user_name, u.role as user_role, u.email as user_email
            FROM audit_logs a
            LEFT JOIN users u ON a.user_id = u.id
            ORDER BY a.created_at DESC
            LIMIT %s
        '''
        rows = db.execute(query, (limit,)).fetchall()
        logs = []
        for row in rows:
            log_dict = dict(row)
            log = AuditLog(**{k: v for k, v in log_dict.items() if k != 'user_role' and k != 'user_email'})
            log.user_role = log_dict.get('user_role')
            log.user_email = log_dict.get('user_email')
            logs.append(log)
        return logs
