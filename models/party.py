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


class Party:
    @staticmethod
    def find_by_id_number_hash(id_hash):
        if not id_hash:
            return None
        row = get_db().execute(
            "SELECT * FROM parties WHERE id_number_hash = %s LIMIT 1", (id_hash,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def find_by_cr_number_hash(cr_hash):
        if not cr_hash:
            return None
        row = get_db().execute(
            "SELECT * FROM parties WHERE cr_number_hash = %s LIMIT 1", (cr_hash,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_by_id(party_id):
        row = get_db().execute("SELECT * FROM parties WHERE id = %s", (party_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def search(q, limit=50):
        rows = get_db().execute("""
            SELECT * FROM parties WHERE full_name ILIKE %s OR full_name_arabic ILIKE %s
            ORDER BY full_name LIMIT %s
        """, (f'%{q}%', f'%{q}%', limit)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def create(party_type, full_name, full_name_arabic=None, date_of_birth=None,
               nationality=None, id_type=None, id_number_hash=None, cr_number_hash=None,
               email=None, phone=None):
        db = get_db()
        cursor = db.execute("""
            INSERT INTO parties
                (party_type, full_name, full_name_arabic, date_of_birth, nationality,
                 id_type, id_number_hash, cr_number_hash, email, phone)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (party_type, full_name, full_name_arabic, date_of_birth, nationality,
              id_type, id_number_hash, cr_number_hash, email, phone))
        party_id = cursor.fetchone()['id']
        db.commit()
        return party_id

    @staticmethod
    def update_bio(party_id, full_name=None, email=None, phone=None, nationality=None):
        """Refresh mutable bio fields from the latest-seen source record.
        Only non-None fields are updated — callers pass what they have."""
        db = get_db()
        fields, params = [], []
        for col, val in (('full_name', full_name), ('email', email),
                          ('phone', phone), ('nationality', nationality)):
            if val:
                fields.append(f"{col} = %s")
                params.append(val)
        if not fields:
            return
        fields.append("updated_at = NOW()")
        params.append(party_id)
        db.execute(f"UPDATE parties SET {', '.join(fields)} WHERE id = %s", tuple(params))
        db.commit()


class PartyLink:
    @staticmethod
    def create(party_id, source_module, source_table, source_record_id, link_role):
        """Dedupes on (source_table, source_record_id, link_role) — safe to call
        repeatedly (e.g. on every edit_merchant save) without creating duplicate links."""
        db = get_db()
        existing = db.execute("""
            SELECT id FROM party_links
            WHERE source_table = %s AND source_record_id = %s AND link_role = %s
        """, (source_table, source_record_id, link_role)).fetchone()
        if existing:
            return existing['id']
        cursor = db.execute("""
            INSERT INTO party_links (party_id, source_module, source_table, source_record_id, link_role)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (party_id, source_module, source_table, source_record_id, link_role))
        link_id = cursor.fetchone()['id']
        db.commit()
        return link_id

    @staticmethod
    def find_party_id_for_source(source_table, source_record_id, link_role=None):
        db = get_db()
        if link_role:
            row = db.execute("""
                SELECT party_id FROM party_links
                WHERE source_table = %s AND source_record_id = %s AND link_role = %s
                LIMIT 1
            """, (source_table, source_record_id, link_role)).fetchone()
        else:
            row = db.execute("""
                SELECT party_id FROM party_links
                WHERE source_table = %s AND source_record_id = %s
                LIMIT 1
            """, (source_table, source_record_id)).fetchone()
        return row['party_id'] if row else None

    @staticmethod
    def get_for_party(party_id):
        rows = get_db().execute("""
            SELECT * FROM party_links WHERE party_id = %s ORDER BY linked_at
        """, (party_id,)).fetchall()
        return [dict(r) for r in rows]
