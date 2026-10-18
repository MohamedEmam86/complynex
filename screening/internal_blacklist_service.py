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
Internal Blacklist Service
Handles CRUD operations for internal blacklist entries
"""

import os
import sys
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)
from config import Config

def normalize_arabic_text(text):
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    # Normalize Alef variants
    text = text.replace('أ', 'ا')  # أ → ا
    text = text.replace('إ', 'ا')  # إ → ا
    text = text.replace('آ', 'ا')  # آ → ا
    text = text.replace('ٱ', 'ا')  # ٱ → ا
    # Normalize Yeh/Maksura
    text = text.replace('ى', 'ي')  # ى → ي
    # Normalize Teh Marbuta
    text = text.replace('ة', 'ه')  # ة → ه
    # Normalize Hamza variants
    text = text.replace('ؤ', 'ء')  # ؤ → ء
    text = text.replace('ئ', 'ء')  # ئ → ء
    # Expand unspaced عبد compounds → spaced form  (DB stores spaced)
    # e.g. عبدالحليم → عبد الحليم
    import re as _rn
    text = _rn.sub(
        r'عبدال([؀-ۿ])',
        lambda m: 'عبد ال' + m.group(1),
        text
    )
    # Collapse any double-space that crept in
    text = _rn.sub(r' {2,}', ' ', text).strip()
    return text.strip().lower()

class InternalBlacklistService:

    def __init__(self):
        pass

    def get_connection(self):
        import psycopg2
        from psycopg2.extras import RealDictCursor
        return psycopg2.connect(cursor_factory=RealDictCursor, **Config.POSTGRES_CONFIG)

    def _generate_source_id(self, name):
        import hashlib
        # Deterministic on name alone — it used to mix in time.time() and a
        # random int, so re-adding the exact same name (e.g. re-running a
        # bulk import through this method) generated a fresh source_id every
        # time and could never be recognized as the same entry.
        hash_str = hashlib.md5(name.strip().lower().encode()).hexdigest()
        return f"IBL-{hash_str[:12].upper()}"

    def add_entry(self, entry_data, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            raw_target = entry_data.get('original_name') or entry_data.get('full_name') or ''
            submitted_full_name = entry_data.get('full_name')
            try:
                from screening.arabic_transliteration_enhanced import prepare_name_for_screening
                english_variant, arabic_variant = prepare_name_for_screening(raw_target)
                entry_data['full_name'] = english_variant
                if arabic_variant:
                    entry_data['original_name'] = arabic_variant
            except Exception:
                pass

            source_id = self._generate_source_id(entry_data['full_name'])

            aliases = entry_data.get('aliases', [])
            if isinstance(aliases, str):
                aliases = [a.strip() for a in aliases.split(',') if a.strip()]
            # Whatever was actually submitted as full_name moves into
            # aliases if the auto-generated spelling replaced it — nothing
            # the user typed gets silently discarded.
            if submitted_full_name and submitted_full_name != entry_data['full_name']:
                aliases.append(submitted_full_name)
            # Store every known spelling variant of the name (e.g. حسن ->
            # hassan/hasan/hasaan/hassaan) as searchable aliases, not just
            # whichever single spelling prepare_name_for_screening picked
            # as the primary full_name — a search using any other real
            # spelling should still hit this record directly rather than
            # relying on fuzzy-match tolerance alone.
            try:
                from screening.arabic_transliteration_enhanced import generate_all_spelling_variants
                variants = generate_all_spelling_variants(raw_target)
                existing_lower = {a.lower() for a in aliases}
                aliases.extend(v for v in variants if v.lower() not in existing_lower)
            except Exception:
                pass
            aliases_json = json.dumps(aliases)

            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # ON CONFLICT (source_id) DO UPDATE — both tables have a UNIQUE
            # constraint on source_id, which is deterministic on the name, so
            # re-uploading the same sheet now updates the existing row instead
            # of either duplicating it or failing on the unique-constraint
            # violation. added_date/created_at are intentionally left out of
            # the UPDATE SET so the original "date added" survives re-uploads.
            cursor.execute("""
                INSERT INTO internal_blacklist (
                    full_name, original_name, entity_type,
                    national_id, passport_number, date_of_birth, place_of_birth,
                    nationality, registration_number,
                    address, city, country,
                    reason, risk_level, category,
                    aliases, notes, phone_number, email,
                    source, source_id, added_by, added_date, created_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    original_name = EXCLUDED.original_name,
                    entity_type = EXCLUDED.entity_type,
                    national_id = EXCLUDED.national_id,
                    passport_number = EXCLUDED.passport_number,
                    date_of_birth = EXCLUDED.date_of_birth,
                    place_of_birth = EXCLUDED.place_of_birth,
                    nationality = EXCLUDED.nationality,
                    registration_number = EXCLUDED.registration_number,
                    address = EXCLUDED.address,
                    city = EXCLUDED.city,
                    country = EXCLUDED.country,
                    reason = EXCLUDED.reason,
                    risk_level = EXCLUDED.risk_level,
                    category = EXCLUDED.category,
                    aliases = EXCLUDED.aliases,
                    notes = EXCLUDED.notes,
                    phone_number = EXCLUDED.phone_number,
                    email = EXCLUDED.email,
                    is_active = 1,
                    modified_by = %s,
                    modified_date = %s,
                    updated_at = %s
                RETURNING id, (xmax = 0) AS inserted
            """, (
                entry_data['full_name'],
                entry_data.get('original_name'),
                entry_data.get('entity_type', 'INDIVIDUAL'),
                entry_data.get('national_id'),
                entry_data.get('passport_number'),
                entry_data.get('date_of_birth'),
                entry_data.get('place_of_birth'),
                entry_data.get('nationality'),
                entry_data.get('registration_number'),
                entry_data.get('address'),
                entry_data.get('city'),
                entry_data.get('country'),
                entry_data['reason'],
                entry_data.get('risk_level', 'HIGH'),
                entry_data.get('category'),
                aliases_json,
                entry_data.get('notes'),
                entry_data.get('phone_number'),
                entry_data.get('email'),
                'INTERNAL',
                source_id,
                user_id,
                now,
                now,
                now,
                user_id,
                now,
                now
            ))

            row = cursor.fetchone()
            entry_id = row['id']
            is_new = row['inserted']
            self._log_audit(cursor, entry_id, 'ADDED' if is_new else 'UPDATED', None, None, None, user_id,
                            entry_data.get('reason'))
            conn.commit()
            logger.info(f"{'Added' if is_new else 'Updated'} blacklist entry: {entry_data['full_name']} (ID: {entry_id})")
            return entry_id

        except Exception as e:
            conn.rollback()
            logger.error(f"Error adding blacklist entry: {e}")
            raise
        finally:
            conn.close()

    def get_entry(self, entry_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ib.*,
                u1.first_name || ' ' || u1.last_name as added_by_username,
                u2.first_name || ' ' || u2.last_name as modified_by_username
            FROM internal_blacklist ib
            LEFT JOIN users u1 ON ib.added_by = u1.id
            LEFT JOIN users u2 ON ib.modified_by = u2.id
            WHERE ib.id = %s
        """, (entry_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            entry = dict(result)
            if entry['aliases']:
                try:
                    entry['aliases'] = json.loads(entry['aliases'])
                except Exception:
                    entry['aliases'] = []
            return entry
        return None

    _SORTABLE_COLUMNS = {'added_date', 'full_name', 'risk_level', 'entity_type', 'category', 'id'}

    def get_all_entries(self, filters=None, page=1, per_page=50, sort_by='added_date', sort_dir='desc'):
        conn = self.get_connection()
        cursor = conn.cursor()

        sort_by = sort_by if sort_by in self._SORTABLE_COLUMNS else 'added_date'
        sort_dir = 'ASC' if str(sort_dir).lower() == 'asc' else 'DESC'

        conditions = ["1=1"]
        params = []
        count_params = []

        if filters:
            if filters.get('search'):
                conditions.append("(ib.full_name ILIKE %s OR ib.original_name ILIKE %s)")
                search_term = f"%{filters['search']}%"
                params.extend([search_term, search_term])
                count_params.extend([search_term, search_term])
            if filters.get('entity_type'):
                conditions.append("ib.entity_type = %s")
                params.append(filters['entity_type'])
                count_params.append(filters['entity_type'])
            if filters.get('risk_level'):
                conditions.append("ib.risk_level = %s")
                params.append(filters['risk_level'])
                count_params.append(filters['risk_level'])
            if filters.get('category'):
                conditions.append("ib.category = %s")
                params.append(filters['category'])
                count_params.append(filters['category'])
            # Separate entries YOUR team confirmed from bulk-imported list data.
            if filters.get('confirmation_type') == 'TEAM_CONFIRMED':
                conditions.append("ib.confirmation_type = %s")
                params.append('TEAM_CONFIRMED')
                count_params.append('TEAM_CONFIRMED')
            elif filters.get('confirmation_type') == 'IMPORTED':
                conditions.append("ib.confirmation_type IS DISTINCT FROM %s")
                params.append('TEAM_CONFIRMED')
                count_params.append('TEAM_CONFIRMED')
            if filters.get('is_active') is not None:
                # COALESCE: 4,610 legacy rows have is_active NULL, which fails
                # both "= 1" and "= 0". Screening already treats NULL as active
                # (sync_internal_to_watchlist uses COALESCE(is_active,1) != 0),
                # so the list view must agree or it hides records that are
                # actively being screened against.
                conditions.append("COALESCE(ib.is_active, 1) = %s")
                val = 1 if filters['is_active'] else 0
                params.append(val)
                count_params.append(val)

        where = " AND ".join(conditions)

        cursor.execute(f"SELECT COUNT(*) as total FROM internal_blacklist ib WHERE {where}", count_params)
        total = cursor.fetchone()['total']

        cursor.execute(f"""
            SELECT ib.*, u.first_name || ' ' || u.last_name as added_by_username
            FROM internal_blacklist ib
            LEFT JOIN users u ON ib.added_by = u.id
            WHERE {where}
            ORDER BY ib.{sort_by} {sort_dir}, ib.id {sort_dir}
            LIMIT %s OFFSET %s
        """, params + [per_page, (page - 1) * per_page])

        results = cursor.fetchall()
        conn.close()

        entries = []
        for row in results:
            entry = dict(row)
            if entry['aliases']:
                try:
                    entry['aliases'] = json.loads(entry['aliases'])
                except Exception:
                    entry['aliases'] = []
            entries.append(entry)

        return entries, total

    def get_statistics(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) as c FROM internal_blacklist WHERE COALESCE(is_active,1) != 0")
            total = cursor.fetchone()['c']
            cursor.execute("SELECT risk_level, COUNT(*) as c FROM internal_blacklist WHERE COALESCE(is_active,1) != 0 GROUP BY risk_level")
            by_risk = {r['risk_level']: r['c'] for r in cursor.fetchall()}
            cursor.execute("SELECT entity_type, COUNT(*) as c FROM internal_blacklist WHERE COALESCE(is_active,1) != 0 GROUP BY entity_type")
            by_type = {r['entity_type']: r['c'] for r in cursor.fetchall()}
            cursor.execute("SELECT category, COUNT(*) as c FROM internal_blacklist WHERE COALESCE(is_active,1) != 0 AND category IS NOT NULL GROUP BY category ORDER BY c DESC LIMIT 5")
            by_category = {r['category']: r['c'] for r in cursor.fetchall()}
            cursor.execute("""SELECT COUNT(*) as c FROM internal_blacklist 
                WHERE COALESCE(is_active,1) != 0 
                AND added_date >= (NOW() - INTERVAL '30 days')::text""")
            last30 = cursor.fetchone()['c']
            return {'total': total, 'total_active': total, 'by_risk_level': by_risk, 'by_type': by_type, 'by_entity_type': by_type, 'by_category': by_category, 'added_last_30_days': last30}
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {'total': 0, 'total_active': 0, 'by_risk_level': {}, 'by_type': {}, 'by_entity_type': {}, 'by_category': {}, 'added_last_30_days': 0}
        finally:
            conn.close()

    def update_entry(self, entry_id, update_data, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM internal_blacklist WHERE id = %s", (entry_id,))
            row = cursor.fetchone()
            if not row:
                return False

            if 'aliases' in update_data:
                aliases = update_data['aliases']
                if isinstance(aliases, str):
                    aliases = [a.strip() for a in aliases.split(',') if a.strip()]
                update_data['aliases'] = json.dumps(aliases)

            # Unlike add_entry(), edits don't otherwise regenerate spelling
            # variants — if the name changed, the aliases should catch up
            # too, or an edited record silently reverts to relying on
            # fuzzy-match tolerance alone (see add_entry()'s comment).
            if 'original_name' in update_data or 'full_name' in update_data:
                try:
                    from screening.arabic_transliteration_enhanced import generate_all_spelling_variants
                    raw_target = update_data.get('original_name') or update_data.get('full_name') or row.get('original_name') or row.get('full_name') or ''
                    variants = generate_all_spelling_variants(raw_target)
                    current_aliases = json.loads(update_data.get('aliases') or row.get('aliases') or '[]')
                    # The name being replaced moves into aliases rather
                    # than being discarded.
                    old_full_name = row.get('full_name')
                    new_full_name = update_data.get('full_name', old_full_name)
                    if old_full_name and old_full_name != new_full_name:
                        current_aliases.append(old_full_name)
                    if variants:
                        existing_lower = {a.lower() for a in current_aliases}
                        current_aliases.extend(v for v in variants if v.lower() not in existing_lower)
                    update_data['aliases'] = json.dumps(current_aliases)
                except Exception:
                    pass

            update_fields = []
            params = []
            for field, value in update_data.items():
                if field not in ['id', 'source_id', 'added_by', 'added_date', 'created_at']:
                    update_fields.append(f"{field} = %s")
                    params.append(value)

            if not update_fields:
                return False

            update_fields.append("modified_by = %s")
            update_fields.append("modified_date = CURRENT_TIMESTAMP")
            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            params.extend([user_id, entry_id])

            cursor.execute(f"""
                UPDATE internal_blacklist
                SET {', '.join(update_fields)}
                WHERE id = %s
            """, params)

            self._log_audit(cursor, entry_id, 'MODIFIED', 'ALL', 'Multiple fields', 'Updated', user_id)
            conn.commit()
            logger.info(f"Updated blacklist entry ID: {entry_id}")
            return True

        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating blacklist entry: {e}")
            raise
        finally:
            conn.close()

    def delete_entry(self, entry_id, user_id, reason=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE internal_blacklist
                SET is_active = 0, modified_by = %s, modified_date = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (user_id, entry_id))
            self._log_audit(cursor, entry_id, 'DEACTIVATED', None, None, None,
                            user_id, reason or 'Entry deleted')
            conn.commit()
            logger.info(f"Deleted blacklist entry ID: {entry_id}")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting blacklist entry: {e}")
            raise
        finally:
            conn.close()

    def bulk_import(self, entries_list, user_id, filename=None):
        stats = {'total': len(entries_list), 'successful': 0, 'failed': 0, 'errors': []}
        for entry in entries_list:
            try:
                if not entry.get('full_name'):
                    stats['failed'] += 1
                    stats['errors'].append('Missing full_name')
                    continue
                if not entry.get('reason'):
                    entry['reason'] = 'Bulk import'
                self.add_entry(entry, user_id)
                stats['successful'] += 1
            except Exception as e:
                stats['failed'] += 1
                stats['errors'].append(f"{entry.get('full_name', '?')}: {e}")
        return stats

    def search_by_name(self, name):
        if not name or not str(name).strip() or len(str(name).strip()) < 2:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Generate both spaced and unspaced forms for Arabic compound names
        import re
        name_spaced = re.sub(r'عبدال([\u0600-\u06FF\w])', r'عبد ال\1', name)  # عبدالحليم -> عبد الحليم
        name_unspaced = re.sub(r'عبد\s+ال', 'عبدال', name)     # عبد الحليم -> عبدالحليم
        
        search_forms = list({name, name_spaced, name_unspaced})
        
        conditions = []
        params = []
        for form in search_forms:
            conditions.append("(full_name ILIKE %s OR original_name ILIKE %s OR aliases ILIKE %s)")
            params.extend([f'%{form}%', f'%{form}%', f'%{form}%'])
        
        where_clause = " OR ".join(conditions)
        cursor.execute(f"""
            SELECT * FROM internal_blacklist
            WHERE COALESCE(is_active,1) != 0
            AND ({where_clause})
            LIMIT 100
        """, params)
        results = cursor.fetchall()
        conn.close()

        entries = []
        for row in results:
            entry = dict(row)
            if entry['aliases']:
                try:
                    entry['aliases'] = json.loads(entry['aliases'])
                except Exception:
                    entry['aliases'] = []
            full_name = (entry.get('full_name') or '').lower().strip()
            original_name = (entry.get('original_name') or '').lower().strip()
            search_lower = name.lower().strip()
            # Normalize both sides before comparison (expand عبد compounds)
            import re as _re
            def _norm_ar(t):
                t = _re.sub(r'عبدال([\u0600-\u06FF])', r'عبد ال\1', t)
                t = _re.sub(r'\s{2,}', ' ', t).strip()
                return t.lower()
            search_norm     = _norm_ar(name)
            full_norm       = _norm_ar(entry.get('full_name') or '')
            original_norm   = _norm_ar(entry.get('original_name') or '')
            if search_norm == full_norm or search_norm == original_norm:
                score = 1.0
            elif search_norm in full_norm or search_norm in original_norm:
                score = 0.92
            elif search_lower in full_name or search_lower in original_name:
                score = 0.90
            else:
                try:
                    import jellyfish
                    score = round(max(
                        jellyfish.jaro_winkler_similarity(search_norm, full_norm),
                        jellyfish.jaro_winkler_similarity(search_norm, original_norm),
                        jellyfish.jaro_winkler_similarity(search_lower, full_name),
                        jellyfish.jaro_winkler_similarity(search_lower, original_name)
                    ), 4)
                except Exception:
                    score = 0.75
            entry['_match_score'] = score
            entry['match_score'] = round(score * 100, 2)
            entries.append(entry)

        entries.sort(key=lambda x: x.get('_match_score', 0), reverse=True)
        return entries

    def _log_audit(self, cursor, entry_id, action, field_name, old_value, new_value, changed_by, reason=None):
        try:
            # changed_at was never in this INSERT's column list, so every
            # audit row had a NULL timestamp — templates/blacklist/view.html's
            # audit.changed_at[:16] then 500s on it.
            cursor.execute("""
                INSERT INTO internal_blacklist_audit
                    (blacklist_id, action, field_changed, old_value, new_value, changed_by, reason, changed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (entry_id, action, field_name, str(old_value) if old_value else None,
                  str(new_value) if new_value else None, changed_by, reason,
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        except Exception as e:
            logger.warning(f"Audit log failed (non-fatal): {e}")
