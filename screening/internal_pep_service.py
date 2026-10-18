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
Internal PEP Service - PostgreSQL version
"""
import json
import os
import sys
import logging
from datetime import datetime, timezone
logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)
from config import Config

def normalize_arabic_text(text):
    if not text: return ""
    if not isinstance(text, str): text = str(text)
    text = text.replace('أ','ا').replace('إ','ا').replace('آ','ا').replace('ٱ','ا')
    text = text.replace('ى','ي').replace('ة','ه').replace('ؤ','ء').replace('ئ','ء')
    import re
    # Normalize Arabic compound prefixes
    text = re.sub(r'عبد\s+ال', 'عبدال', text)
    text = re.sub(r'ابن\s+', 'ابن', text)
    text = re.sub(r'ابو\s+', 'ابو', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text.strip().lower()

def _get_pg_conn():
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(cursor_factory=RealDictCursor, **Config.POSTGRES_CONFIG)

class InternalPEPService:
    """Service for managing internal PEP entries - PostgreSQL backend"""

    def get_connection(self):
        return _get_pg_conn()

    def add_entry(self, entry_data, user_id):
        submitted_full_name = entry_data.get('full_name')
        try:
            from screening.arabic_transliteration_enhanced import prepare_name_for_screening
            raw_target = entry_data.get('original_name') or entry_data.get('full_name') or ''
            english_variant, arabic_variant = prepare_name_for_screening(raw_target)
            entry_data['full_name'] = english_variant
            if arabic_variant:
                entry_data['original_name'] = arabic_variant
        except Exception:
            pass

        source_id = self._generate_source_id(entry_data.get('full_name', ''))
        aliases = entry_data.get('aliases', [])
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(',') if a.strip()]
        # Whatever was actually submitted as full_name moves into aliases
        # if the auto-generated spelling replaced it — nothing the user
        # typed gets silently discarded.
        if submitted_full_name and submitted_full_name != entry_data['full_name']:
            aliases.append(submitted_full_name)

        # Auto-generate every known spelling variant and add to aliases —
        # e.g. حسن -> hassan/hasan/hasaan/hassaan — so a search using any
        # of them hits this record directly, not just whichever single
        # spelling prepare_name_for_screening picked as the primary
        # full_name. Previously capped at 8 generated + 10 total, which
        # silently dropped most variants for a multi-word name (a 5-token
        # name with 2-4 spellings per token has dozens of combinations,
        # not 8) — uncapped now; generate_english_variants/
        # generate_arabic_variants already cap combinatorial explosion
        # internally (50 max) so this can't run away.
        try:
            from screening.arabic_transliteration_enhanced import generate_all_spelling_variants
            raw = entry_data.get('original_name') or entry_data.get('full_name') or ''
            variants = generate_all_spelling_variants(raw)
            existing_lower = {a.lower() for a in aliases}
            aliases.extend(v for v in variants if v.lower() not in existing_lower)
        except Exception:
            pass

        aliases_json = json.dumps(aliases)

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # ON CONFLICT (source_id) DO UPDATE — was DO NOTHING, which made
            # re-uploading the same sheet silently no-op instead of refreshing
            # the existing entry (and even masked the row count, since RETURNING
            # never fires on a no-op). added_date/created_at stay out of the
            # UPDATE SET so the original "date added" survives re-uploads.
            cursor.execute("""
                INSERT INTO internal_pep (
                    full_name, original_name, entity_type,
                    national_id, passport_number, date_of_birth, place_of_birth,
                    nationality, registration_number, address, city, country,
                    reason, risk_level, category, position,
                    aliases, notes, phone_number, email,
                    source, source_id, added_by, added_date, created_at, updated_at, is_active
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                    position = EXCLUDED.position,
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
                entry_data.get('full_name'), entry_data.get('original_name'),
                entry_data.get('entity_type', 'INDIVIDUAL'),
                entry_data.get('national_id'), entry_data.get('passport_number'),
                entry_data.get('date_of_birth'), entry_data.get('place_of_birth'),
                entry_data.get('nationality'), entry_data.get('registration_number'),
                entry_data.get('address'), entry_data.get('city'), entry_data.get('country'),
                entry_data.get('reason', 'PEP'),
                entry_data.get('risk_level', 'HIGH'),
                entry_data.get('category'), entry_data.get('position'),
                aliases_json, entry_data.get('notes'),
                entry_data.get('phone_number'), entry_data.get('email'),
                'INTERNAL_PEP', source_id, user_id,
                now, now, now,
                1,
                user_id, now, now
            ))
            row = cursor.fetchone()
            entry_id = row['id'] if row else None
            is_new = row['inserted'] if row else True
            if entry_id:
                self._log_audit(cursor, entry_id, 'ADDED' if is_new else 'UPDATED', None, None, None, user_id,
                               entry_data.get('reason'))
            conn.commit()
            return entry_id
        except Exception as e:
            conn.rollback()
            logger.error(f"add_entry error: {e}")
            raise
        finally:
            cursor.close()
            conn.close()

    def get_entry(self, entry_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM internal_pep WHERE id = %s", (entry_id,))
            row = cursor.fetchone()
            if not row: return None
            result = dict(row)
            try: result['aliases'] = json.loads(result.get('aliases') or '[]')
            except: result['aliases'] = []
            return result
        finally:
            cursor.close()
            conn.close()

    _SORTABLE_COLUMNS = {'added_date', 'full_name', 'risk_level', 'entity_type', 'category', 'id'}

    def get_all_entries(self, filters=None, page=1, per_page=50, sort_by='added_date', sort_dir='desc'):
        filters = filters or {}
        sort_by = sort_by if sort_by in self._SORTABLE_COLUMNS else 'added_date'
        sort_dir = 'ASC' if str(sort_dir).lower() == 'asc' else 'DESC'
        conditions = ["is_active = 1"]
        params = []
        if filters.get('search'):
            conditions.append("(full_name ILIKE %s OR original_name ILIKE %s)")
            params += [f"%{filters['search']}%", f"%{filters['search']}%"]
        if filters.get('entity_type'):
            conditions.append("entity_type = %s")
            params.append(filters['entity_type'])
        if filters.get('risk_level'):
            conditions.append("risk_level = %s")
            params.append(filters['risk_level'])
        if filters.get('category'):
            conditions.append("category ILIKE %s")
            params.append(f"%{filters['category']}%")

        where = " AND ".join(conditions)
        offset = (page - 1) * per_page

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT COUNT(*) as total FROM internal_pep WHERE {where}", params)
            total = cursor.fetchone()['total']
            cursor.execute(f"""
                SELECT ip.*, u.first_name || ' ' || u.last_name as added_by_username
                FROM internal_pep ip
                LEFT JOIN users u ON ip.added_by = u.id
                WHERE ip.is_active = 1
                {('AND ' + ' AND '.join(c for c in conditions if 'is_active' not in c)) if len(conditions) > 1 else ''}
                ORDER BY ip.{sort_by} {sort_dir}, ip.id {sort_dir}
                LIMIT %s OFFSET %s
            """, [p for p in params] + [per_page, offset])
            rows = cursor.fetchall()
            entries = []
            for row in rows:
                e = dict(row)
                try: e['aliases'] = json.loads(e.get('aliases') or '[]')
                except: e['aliases'] = []
                entries.append(e)
            return entries, total
        finally:
            cursor.close()
            conn.close()

    def search_by_name(self, name):
        if not name or len(name.strip()) < 2:
            return []
        name_lower = name.strip().lower()
        # Normalize common Arabic article variants before searching
        import re as _re
        name_lower = _re.sub(r'el[\s-]', 'al', name_lower)
        name_lower = _re.sub(r'el$', 'al', name_lower)
        name_lower = name_lower.replace('abdel ', 'abd al').replace('abdal ', 'abd al')
        name_normalized = normalize_arabic_text(name)

        # Detect if input is Arabic
        import re
        is_arabic = bool(re.search(r'[؀-ۿ]', name))

        # Build conditions and params
        conditions = []
        params = []

        # 1. Full name exact LIKE
        conditions.append("LOWER(full_name) LIKE %s")
        params.append(f"%{name_lower}%")

        # 2. Original name normalized
        conditions.append("LOWER(original_name) LIKE %s")
        params.append(f"%{name_normalized}%")

        # 3. Token-based matching on full_name (handles transliteration variants)
        tokens = [t for t in name_lower.split() if len(t) > 2]
        if tokens:
            # Match any single significant token — raw AND normalised form
            from screening.name_normalizer import normalise as _norm
            for token in tokens[:4]:
                conditions.append("LOWER(full_name) LIKE %s")
                params.append(f"%{token}%")
                conditions.append("LOWER(original_name) LIKE %s")
                params.append(f"%{token}%")
                # Also search using the normalised/EQUIV-mapped form of the token
                # e.g. 'akl'→'aql', 'noshwa'→'ncwy', 'sulaiman'→'slyman' equivalent
                norm_token = _norm(token)
                if norm_token and norm_token != token:
                    conditions.append("LOWER(full_name) LIKE %s")
                    params.append(f"%{norm_token}%")
                    conditions.append("LOWER(original_name) LIKE %s")
                    params.append(f"%{norm_token}%")

        # 4. If English input — use trigram similarity + soundex on full_name
        if not is_arabic:
            try:
                # Per-token trigram similarity (handles transliteration spelling variants)
                for token in tokens[:4]:
                    conditions.append("EXISTS (SELECT 1 FROM unnest(string_to_array(LOWER(full_name), ' ')) AS t WHERE similarity(t, %s) > 0.35)")
                    params.append(token)

                # Also generate Arabic variants and search original_name
                from screening.arabic_utils import generate_arabic_variants
                ar_variants = generate_arabic_variants(name)
                for ar_var in ar_variants[:5]:
                    conditions.append("original_name LIKE %s")
                    params.append(f"%{ar_var}%")
                    ar_stripped = re.sub(r"[أإآ]", "ا", ar_var)
                    if ar_stripped != ar_var:
                        conditions.append("original_name LIKE %s")
                        params.append(f"%{ar_stripped}%")
            except Exception as e:
                pass

        # 5. If Arabic input — generate English transliteration and search full_name
        if is_arabic:
            try:
                from screening.complynex_engine import transliterate_arabic
                transliterated = transliterate_arabic(name).lower()
                if transliterated and transliterated != name_lower:
                    conditions.append("LOWER(full_name) LIKE %s")
                    params.append(f"%{transliterated}%")
                    # Token-based on transliterated
                    for tok in transliterated.split():
                        if len(tok) > 2:
                            conditions.append("LOWER(full_name) LIKE %s")
                            params.append(f"%{tok}%")
            except Exception:
                pass

        # 6. Search aliases JSON array
        conditions.append("aliases::text ILIKE %s")
        params.append(f"%{name_lower}%")
        if not is_arabic:
            # Also search aliases for each token
            for token in tokens[:3]:
                conditions.append("aliases::text ILIKE %s")
                params.append(f"%{token}%")

        where_clause = " OR ".join(conditions)

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"""
                SELECT * FROM internal_pep
                WHERE is_active = 1
                AND ({where_clause})
                LIMIT 100
            """, params)
            raw = [dict(r) for r in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()

        # ── Post-retrieval scoring (Tier-1 approach) ──────────────────────
        # SQL casts a wide net; Python scores and filters precisely.
        try:
            from screening.name_normalizer import score_match
            scored = []
            for rec in raw:
                score = score_match(
                    name,
                    rec.get('full_name', ''),
                    rec.get('aliases')
                )
                # Arabic original_name covered via alias variants
                rec['_match_score'] = round(score, 3)
                scored.append((score, rec))

            # Sort by score descending, filter to ≥ 0.60 threshold
            scored.sort(key=lambda x: x[0], reverse=True)
            results = [r for s, r in scored if s >= 0.80]

            # No fallback — if nothing scores above threshold, return empty
            # (Returning low-confidence results causes false positives)

            return results
        except Exception as e:
            logger.warning(f"Post-retrieval scoring failed: {e}")
            return raw

    def update_entry(self, entry_id, update_data, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            aliases = update_data.get('aliases', [])
            if isinstance(aliases, str):
                aliases = [a.strip() for a in aliases.split(',') if a.strip()]

            # Regenerate spelling variants on edit too — otherwise a
            # corrected/changed name silently loses alias coverage (see
            # add_entry()'s comment on why this matters).
            try:
                from screening.arabic_transliteration_enhanced import generate_all_spelling_variants
                cursor.execute("SELECT full_name FROM internal_pep WHERE id = %s", (entry_id,))
                old_row = cursor.fetchone()
                old_full_name = old_row['full_name'] if old_row else None
                new_full_name = update_data.get('full_name', old_full_name)
                # The name being replaced moves into aliases rather than
                # being discarded.
                if old_full_name and old_full_name != new_full_name:
                    aliases.append(old_full_name)

                raw_target = update_data.get('original_name') or update_data.get('full_name') or ''
                variants = generate_all_spelling_variants(raw_target)
                existing_lower = {a.lower() for a in aliases}
                aliases.extend(v for v in variants if v.lower() not in existing_lower)
            except Exception:
                pass

            cursor.execute("""
                UPDATE internal_pep SET
                    full_name=%s, original_name=%s, entity_type=%s,
                    national_id=%s, passport_number=%s, date_of_birth=%s,
                    place_of_birth=%s, nationality=%s, country=%s,
                    reason=%s, risk_level=%s, category=%s, position=%s,
                    aliases=%s, notes=%s, phone_number=%s, email=%s,
                    modified_by=%s, modified_date=NOW()
                WHERE id=%s
            """, (
                update_data.get('full_name'), update_data.get('original_name'),
                update_data.get('entity_type', 'INDIVIDUAL'),
                update_data.get('national_id'), update_data.get('passport_number'),
                update_data.get('date_of_birth'), update_data.get('place_of_birth'),
                update_data.get('nationality'), update_data.get('country'),
                update_data.get('reason'), update_data.get('risk_level', 'HIGH'),
                update_data.get('category'), update_data.get('position'),
                json.dumps(aliases), update_data.get('notes'),
                update_data.get('phone_number'), update_data.get('email'),
                user_id, entry_id
            ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    def delete_entry(self, entry_id, user_id, reason=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE internal_pep SET is_active=0, modified_by=%s, modified_date=NOW() WHERE id=%s",
                (user_id, entry_id)
            )
            self._log_audit(cursor, entry_id, 'DELETED', None, None, None, user_id, reason)
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    def bulk_import(self, entries_list, user_id, filename=None):
        stats = {'total': len(entries_list), 'successful': 0, 'failed': 0, 'errors': []}
        for i, entry in enumerate(entries_list):
            try:
                if not entry.get('full_name'):
                    stats['errors'].append({'row': i+1, 'name': '', 'error': 'Missing full_name'})
                    stats['failed'] += 1
                    continue
                if not entry.get('reason'):
                    entry['reason'] = 'PEP - Bulk Import'
                self.add_entry(entry, user_id)
                stats['successful'] += 1
            except Exception as e:
                stats['errors'].append({'row': i+1, 'name': entry.get('full_name',''), 'error': str(e)})
                stats['failed'] += 1
        return stats

    def get_statistics(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            stats = {}
            cursor.execute("SELECT COUNT(*) as c FROM internal_pep WHERE is_active=1")
            stats['total_active'] = cursor.fetchone()['c']
            cursor.execute("SELECT risk_level, COUNT(*) as c FROM internal_pep WHERE is_active=1 GROUP BY risk_level")
            stats['by_risk_level'] = {r['risk_level']: r['c'] for r in cursor.fetchall()}
            cursor.execute("SELECT entity_type, COUNT(*) as c FROM internal_pep WHERE is_active=1 GROUP BY entity_type")
            stats['by_entity_type'] = {r['entity_type']: r['c'] for r in cursor.fetchall()}
            cursor.execute("SELECT category, COUNT(*) as c FROM internal_pep WHERE is_active=1 AND category IS NOT NULL GROUP BY category ORDER BY c DESC LIMIT 5")
            stats['by_category'] = {r['category']: r['c'] for r in cursor.fetchall()}
            return stats
        finally:
            cursor.close()
            conn.close()

    def _log_audit(self, cursor, entry_id, action, field, old_val, new_val, user_id, reason=None):
        try:
            # changed_at was never in this INSERT's column list, so every
            # audit row had a NULL timestamp (same bug as
            # InternalBlacklistService._log_audit).
            cursor.execute("""
                INSERT INTO internal_pep_audit
                (blacklist_id, action, field_changed, old_value, new_value, changed_by, reason, changed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (entry_id, action, field,
                  str(old_val) if old_val else None,
                  str(new_val) if new_val else None,
                  user_id, reason,
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        except Exception as e:
            logger.warning(f"Audit log failed: {e}")

    def _generate_source_id(self, name):
        import hashlib
        # Deterministic on name alone — it used to include the current
        # timestamp, so re-adding/re-uploading the exact same name generated
        # a fresh source_id every time and the ON CONFLICT (source_id) DO
        # NOTHING below never matched, silently duplicating the entry.
        hash_str = hashlib.md5(name.strip().lower().encode()).hexdigest()
        return f"IPEP-{hash_str[:12].upper()}"
