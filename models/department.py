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

from database.db import get_db

UNIT_TYPES = ('department', 'business_unit', 'branch')


class Department:
    def __init__(self, id=None, name=None, code=None, description=None, created_at=None,
                 unit_type='department', parent_id=None, is_active=True, **kwargs):
        self.id = id
        self.name = name
        self.code = code
        self.description = description
        self.created_at = created_at
        self.unit_type = unit_type or 'department'
        self.parent_id = parent_id
        self.is_active = is_active if is_active is not None else True

    @staticmethod
    def get_all(unit_type=None, active_only=False):
        db = get_db()
        clauses, params = [], []
        if unit_type:
            clauses.append('unit_type = %s')
            params.append(unit_type)
        if active_only:
            clauses.append('is_active = TRUE')
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        rows = db.execute(f'SELECT * FROM departments {where} ORDER BY name', tuple(params)).fetchall()
        return [Department(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(dept_id):
        if not dept_id: return None
        db = get_db()
        row = db.execute('SELECT * FROM departments WHERE id = %s', (dept_id,)).fetchone()
        return Department(**dict(row)) if row else None

    @staticmethod
    def get_by_code(code):
        if not code: return None
        db = get_db()
        row = db.execute('SELECT * FROM departments WHERE code = %s', (code,)).fetchone()
        return Department(**dict(row)) if row else None

    @staticmethod
    def create(name, code, description=None, unit_type='department', parent_id=None):
        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute('''
                INSERT INTO departments (name, code, description, unit_type, parent_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            ''', (name, code, description, unit_type or 'department', parent_id or None))
            db.commit()
            return Department.get_by_id(cursor.fetchone()['id'])
        except Exception as e:
            db.rollback()
            raise e

    @staticmethod
    def update(dept_id, name, code, description=None, unit_type='department', parent_id=None):
        db = get_db()
        try:
            db.execute('''
                UPDATE departments
                SET name = %s, code = %s, description = %s, unit_type = %s, parent_id = %s
                WHERE id = %s
            ''', (name, code, description, unit_type or 'department', parent_id or None, dept_id))
            db.commit()
            return Department.get_by_id(dept_id)
        except Exception as e:
            db.rollback()
            raise e

    @staticmethod
    def set_active(dept_id, is_active):
        db = get_db()
        db.execute('UPDATE departments SET is_active = %s WHERE id = %s', (is_active, dept_id))
        db.commit()
        return Department.get_by_id(dept_id)

    @staticmethod
    def delete(dept_id):
        db = get_db()
        # Check for dependencies would go here (users, policies)
        # For now, simple delete or we can restrict if used
        db.execute('DELETE FROM departments WHERE id = %s', (dept_id,))
        db.commit()
        return True
