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

from screening.db_pool import db_pool
"""
Enhanced Data Updater for ComplyNex Screening System
=====================================================

Features:
- All format handlers (UN, OFAC, HMT, EU, OpenSanctions, EMLCU)
- Incremental updates (only add/update changed records)
- Comprehensive audit logging
- Error handling and resilience
- Progress tracking

Version: 2.0
"""

import os
import sys
import requests
import sqlite3
import logging
import json
import jellyfish
from datetime import datetime
import hashlib
import time

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None

# Import format handlers
from .emlcu_scraper_production import EMLCUScraperFixed
from .format_handlers import (
    UNSecurityCouncilHandler,
    OFACHandler,
    HMTreasuryHandler,
    EUSanctionsHandler,
    OpenSanctionsHandler
)


def stored_json_value(v):
    """How a profile field is written to its TEXT column: JSON (ensure_ascii=False), nothing
    for empty values."""
    if v in (None, [], {}, ''):
        return None
    return json.dumps(v, ensure_ascii=False)


def normalize_arabic_text(text):
    """Normalize Arabic text for comparison"""
    if not text:
        return ""
    # Import from complynex_engine or re-implement
    import re
    text = text.strip().lower()
    # Remove diacritics
    text = re.sub(r'[\u064B-\u0652]', '', text)
    # Normalize alef variations
    text = text.replace('إ', 'ا').replace('أ', 'ا').replace('آ', 'ا')
    # Normalize teh marbuta
    text = text.replace('ة', 'ه')
    return text


import fcntl as _fcntl
import tempfile as _tempfile

class _ScrapeGuard:
    """File-based lock preventing concurrent scrape tasks"""
    def __init__(self, source):
        self._path = f"/tmp/complynex_scrape_{source}.lock"
        self._fh = None
    def acquire(self):
        self._fh = open(self._path, 'w')
        try:
            _fcntl.flock(self._fh, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            return True
        except OSError:
            self._fh.close(); self._fh = None
            return False
    def release(self):
        if self._fh:
            _fcntl.flock(self._fh, _fcntl.LOCK_UN)
            self._fh.close(); self._fh = None

class EnhancedDataUpdater:
    """
    Production-ready Data Updater with full format support and incremental updates.
    """
    
    def __init__(self, db_config, task_id=None):
        self.db_config = db_config
        self.db_conn = None
        self.audit_log_id = None
        self.task_id = task_id
        
        # Detect DB Type
        if isinstance(db_config, dict) and 'database' in db_config and len(db_config) == 1:
            self.db_type = 'sqlite'
            self.placeholder = '%s'
        elif isinstance(db_config, str):
            self.db_type = 'sqlite'
            self.db_config = {'database': db_config}
            self.placeholder = '%s'
        else:
            self.db_type = 'postgresql'
            self.placeholder = '%s'
            
        # Stats tracking
        self.stats = {
            'added': 0,
            'updated': 0,
            'unchanged': 0,
            'errors': 0,
            'start_time': None,
            'end_time': None
        }
        
    def connect_db(self):
        """Establish database connection"""
        if self.db_type == 'sqlite':
            if not self.db_conn:
                self.db_conn = db_pool.checkout_connection()
                self.db_conn.row_factory = sqlite3.Row
        else:
            if not self.db_conn or (hasattr(self.db_conn, 'closed') and self.db_conn.closed):
                if psycopg2 is None:
                    raise ImportError("psycopg2 is required for PostgreSQL")
                self.db_conn = psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)
                
    def close_db(self):
        """Close database connection"""
        if self.db_conn:
            try:
                self.db_conn.close()
            except Exception as e:
                logger.debug(f"[SWALLOWED] db connection close (cleanup) failed: {e}")
            self.db_conn = None
            
    def update_watchlist(self, source_id=None, user_id=1):
        """Run a list update while marking it as running (see screening.update_lock),
        so incremental readers of the watchlist wait instead of missing rows."""
        from utils.demo import is_demo
        if is_demo():
            logger.info("demo instance: list update skipped (lists are maintained by the main instance)")
            return {'added': 0, 'updated': 0, 'unchanged': 0, 'errors': 0, 'demo': True}
        from screening.update_lock import hold
        with hold(f"source_id={source_id}"):
            return self._update_watchlist(source_id=source_id, user_id=user_id)

    def _update_watchlist(self, source_id=None, user_id=1):
        """
        Update database from configured sources.
        
        Args:
            source_id: Specific source ID to update (None = all active sources)
            user_id: User performing the update (for audit trail)
            
        Returns:
            Statistics dictionary
        """
        self.stats['start_time'] = datetime.now()
        self.connect_db()
        
        try:
            cursor = self.db_conn.cursor()
            
            # Get sources to update
            if source_id:
                cursor.execute(f"SELECT * FROM screening_data_sources WHERE id = {self.placeholder}", (source_id,))
                sources = cursor.fetchall()
            else:
                cursor.execute("SELECT * FROM screening_data_sources WHERE is_active = TRUE ORDER BY priority")
                sources = cursor.fetchall()
                
            if not sources:
                logger.warning("No active screening sources found.")

                return self.stats
                
            total_sources = len(sources)
            
            # Create audit log entry
            self.audit_log_id = self._create_audit_log(user_id, total_sources)
            
            # Process each source
            for idx, source in enumerate(sources, 1):
                # Convert sqlite3.Row to dict
                source = dict(source)
                logger.info(f"[{idx}/{total_sources}] Processing source: {source['source_name']} ({source['source_type']})")
                
                source_stats = self._update_source(source, user_id)
                
                # Aggregate stats
                self.stats['added'] += source_stats['added']
                self.stats['updated'] += source_stats['updated']
                self.stats['unchanged'] += source_stats['unchanged']
                self.stats['errors'] += source_stats['errors']
                for _k in ('delisted', 'relisted'):
                    self.stats[_k] = self.stats.get(_k, 0) + int(source_stats.get(_k) or 0)
                if source_stats.get('error'):
                    self.stats['error'] = source_stats['error']
                
                # Update source metadata
                self._update_source_metadata(source['id'], source_stats, user_id)
                
                # Commit after each source
                self.db_conn.commit()
                
            self.stats['end_time'] = datetime.now()
            
            # Finalize audit log
            self._finalize_audit_log(self.audit_log_id, self.stats)
            
            logger.info(f"Update complete: {self.stats['added']} added, {self.stats['updated']} updated, {self.stats['unchanged']} unchanged, {self.stats['errors']} errors")
            
            

            return self.stats
            
        except Exception as e:
            logger.error(f"Update failed: {e}")
            if hasattr(self, 'audit_log_id') and self.audit_log_id:
                try:
                    self._mark_audit_log_failed(self.audit_log_id, str(e))
                except Exception as log_err:
                    logger.error(f"Failed to log audit failure: {log_err}")
            self.db_conn.rollback()
            raise
        finally:
            self.close_db()
            
    def _update_source(self, source, user_id):
        """One writer per list: the update holds the list's lock for its whole run, so a
        rollback (or a second update of the same list) cannot interleave with it (P2-1)."""
        from screening import list_versions as LV
        try:
            lock = LV.source_lock(self.db_conn, source['source_name'])
            lock.__enter__()
        except LV.SourceBusy as e:
            logger.error(f"[VERSION] {source['source_name']}: {e} - this update was not run")
            return {'added': 0, 'updated': 0, 'unchanged': 0, 'errors': 1,
                    'error': 'another update or rollback of this list is running'}
        except Exception as e:
            logger.warning(f"[VERSION] {source['source_name']}: list lock unavailable ({e}); continuing")
            try:
                self.db_conn.rollback()
            except Exception:
                pass
            lock = None
        try:
            return self._update_source_locked(source, user_id)
        except BaseException:
            try:
                self.db_conn.rollback()   # the unlock must not commit a half-written update
            except Exception:
                pass
            raise
        finally:
            if lock is not None:
                lock.__exit__(None, None, None)

    def _update_source_locked(self, source, user_id):
        """
        Update a single data source.
        
        Returns:
            Statistics for this source
        """
        source_stats = {'added': 0, 'updated': 0, 'unchanged': 0, 'errors': 0}
        
        try:
            # Fetch entities based on source type
            entities = self._fetch_entities(source)
            
            sname = source['source_name']
            trigger = getattr(self, 'version_trigger', None) or 'manual'
            if not entities:
                # An empty download is a failure, not "nothing changed": the
                # EU feed returned nothing for weeks while every run said [OK].
                logger.error(f"No entities fetched from {sname}")
                source_stats['errors'] += 1
                source_stats['error'] = 'no entities fetched (download or parse failed)'
                self._version_failed(sname, source_stats['error'], user_id, trigger)
                return source_stats
                
            logger.info(f"Fetched {len(entities)} entities from {sname}")

            # List version + update guard (P2-1): nothing is written when the download
            # would drop or deactivate too much of the list; the version in force stays.
            from screening import list_versions as LV
            vid, ev = None, None
            try:
                raw_sha = getattr(self, '_last_raw_sha', None)
                # approvals are matched on the parsed content: a re-download of the same list
                # often has another file hash (generation date inside the file)
                csha = LV.content_sha256(entities)
                sha = raw_sha or csha
                n_ids = len({e.get('source_id') for e in entities if e.get('source_id')})
                vid = LV.begin(self.db_conn, sname, sha, 'file' if raw_sha else 'content', n_ids,
                               user_id=None if trigger == 'scheduled' else user_id, trigger=trigger, content_sha=csha)
                ev = LV.evaluate(self.db_conn, sname, [e.get('source_id') for e in entities], sha=sha,
                                 content_sha=csha)
            except Exception as e:
                # Versioning infrastructure must not stop the daily update (the older
                # partial-download check in _sync_delistings still applies).
                logger.error(f"[VERSION] {sname}: version / guard unavailable: {e}")
                try:
                    self.db_conn.rollback()
                except Exception:
                    pass
                if vid:
                    LV.fail(self.db_conn, vid, f'guard check failed: {e}')
                LV.alert(self.db_conn, sname, 'guard_error', f'List update guard unavailable: {sname}',
                         f'The update of {sname} ran without the version check (no guard, no rollback point): '
                         f'{str(e)[:300]}. Check the list after the run.')
                vid, ev = None, None
            if ev and ev['blocked']:
                LV.block(self.db_conn, vid, ev)
                logger.error(f"[BLOCKED] {sname}: {'; '.join(ev['reasons'])} - previous version stays in force")
                source_stats['errors'] += 1
                source_stats['blocked'] = True
                source_stats['error'] = 'BLOCKED by the update guard: ' + '; '.join(ev['reasons'])
                return source_stats
            
            # an MLRO-approved download is applied in full (also its deactivations)
            self._delist_approved = bool(ev and ev.get('approved_version'))
            # Process entities in batch (MUCH faster - single SELECT for all)
            try:
                added, updated, unchanged = self._import_entities_batch(entities, sname)
                source_stats['added'] += added
                source_stats['updated'] += updated
                source_stats['unchanged'] += unchanged
                self.db_conn.commit()
                try:
                    source_stats.update(self._sync_delistings(entities, sname))
                except Exception as e:
                    logger.error(f"Delisting sync failed for {sname}: {e}")
                    self.db_conn.rollback()
                logger.info(f"Batch complete: {added} added, {updated} updated, {unchanged} unchanged")
                if vid:
                    try:
                        LV.applied(self.db_conn, vid, source_stats, ev)
                    except Exception as e:
                        logger.error(f"[VERSION] {sname}: could not close version {vid}: {e}")
                        try:
                            self.db_conn.rollback()
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"Failed to process {sname}: {e}")
                self.db_conn.rollback()
                source_stats['errors'] += 1
                if vid:
                    LV.fail(self.db_conn, vid, e)
            finally:
                self._delist_approved = False
                    
            return source_stats
            
        except Exception as e:
            logger.error(f"Failed to fetch/process source {source['source_name']}: {e}")
            source_stats['errors'] += 1
            try:
                self.db_conn.rollback()
            except Exception:
                pass
            return source_stats

    def _version_failed(self, sname, error, user_id, trigger):
        """Record a failed download as a FAILED version (and alert). Never raises."""
        try:
            from screening import list_versions as LV
            vid = LV.begin(self.db_conn, sname, None, None, 0,
                           user_id=None if trigger == 'scheduled' else user_id, trigger=trigger)
            LV.fail(self.db_conn, vid, error)
        except Exception as e:
            logger.error(f"[VERSION] {sname}: could not record the failed update: {e}")
            try:
                self.db_conn.rollback()
            except Exception:
                pass
            
    def _fetch_entities(self, source):
        """
        Fetch entities from source based on type.
        """
        source_type = source['source_type'].upper()
        source_url = source.get('source_url') or source.get('url')
        
        if not source_url:
            logger.error(f"No URL for source {source['source_name']}")
            return []
            
        self._last_raw_sha = None   # hash of the downloaded file, recorded in the list version (P2-1)
        try:
            # EMLCU - Special case (XLSX)
            if source_type in ['EMLCU_SCRAPER', 'EMLCU']:
                logger.info(f"Using Production EMLCU scraper with URL: {source_url}")
                # Auto-discover and download the current file (its filename
                # changes with every EMLCU update), then parse via the same
                # tested parser the manual-upload UI uses
                # (scripts/import_sanctions_file.py's parse_emlcu_xlsx) — not
                # this class's own scrape_list()/_download_direct(), which
                # depends on a parse_emlcu_excel() function that doesn't
                # exist anywhere in this codebase and would always crash.
                scraper = EMLCUScraperFixed(url=source_url, db_conn=self.db_conn)
                file_path = scraper.download_only()
                if not file_path:
                    raise Exception("Failed to download EMLCU file")
                try:
                    from screening.list_versions import file_sha256 as _fsha
                    with open(file_path, 'rb') as _fh:
                        self._last_raw_sha = _fsha(_fh.read())
                except Exception:
                    self._last_raw_sha = None
                scripts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts')
                if scripts_dir not in sys.path:
                    sys.path.append(scripts_dir)
                from import_sanctions_file import parse_emlcu_xlsx
                return parse_emlcu_xlsx(file_path)
                
            # Download content for other sources with retry logic
            max_retries = 3
            last_error = None
            response = None
            
            for attempt in range(max_retries):
                try:
                    logger.info(f"Downloading from {source_url} (Attempt {attempt+1}/{max_retries})")
                    # Increased timeout for large files like UN
                    response = requests.get(source_url, timeout=(15, 120), stream=True)
                    response.raise_for_status()
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(f"Download attempt {attempt+1} failed: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(5)
                    else:
                        raise last_error

            # For JSON/OpenSanctions: stream line by line to avoid loading 2GB into RAM
            if source_type in ['OPENSANCTIONS', 'FTJSON', 'JSON']:
                import json as _json
                entities = []
                handler = OpenSanctionsHandler(rich=self._os_rich_enabled())
                raw_line_count = 0  # Count ALL lines, not just valid entities
                for raw_line in response.iter_lines():
                    try:
                        if not raw_line:
                            continue
                        raw_line_count += 1
                        line = raw_line.decode('utf-8') if isinstance(raw_line, bytes) else raw_line
                        entity = handler._parse_line(line)
                        if entity:
                            entities.append(entity)
                            handler.processed_count += 1
                        # Update progress every 500 lines regardless of valid count
                        if raw_line_count % 500 == 0:
                            self._update_download_progress(
                                raw_line_count,
                                f"Downloading... {raw_line_count:,} lines / {handler.processed_count:,} valid records"
                            )
                    except Exception as e:
                        handler.error_count += 1
                        continue
                logger.info(f"OpenSanctions streamed {handler.processed_count} entities")
                # Final download progress update
                self._update_download_progress(
                    handler.processed_count,
                    f"Download complete: {handler.processed_count:,} records. Importing..."
                )
                return entities

            # For large files, get raw content or text based on handler preference
            # XML lists are passed as bytes so the parser reads the encoding the file declares
            # (response.text guessed ISO-8859-1 for the UK list and garbled every Arabic name)
            if source_type in ['UN', 'UN_SECURITY_COUNCIL', 'HMT', 'UK', 'HM_TREASURY', 'OFAC', 'OFAC_SDN', 'EU', 'EU_SANCTIONS']:
                content = response.content
            else:
                content = response.text

            try:
                from screening.list_versions import file_sha256 as _fsha
                self._last_raw_sha = _fsha(content)
            except Exception:
                self._last_raw_sha = None

            # Get appropriate handler
            if source_type in ['UN', 'UN_SECURITY_COUNCIL']:
                handler = UNSecurityCouncilHandler()
            elif source_type in ['OFAC', 'OFAC_SDN']:
                handler = OFACHandler()
            elif source_type in ['HMT', 'UK', 'HM_TREASURY']:
                handler = HMTreasuryHandler()
            elif source_type in ['EU', 'EU_SANCTIONS']:
                handler = EUSanctionsHandler()
            else:
                logger.error(f"Unknown source type: {source_type}")
                return []

            # Parse content
            entities = handler.parse(content)

            return entities
            
        except Exception as e:
            logger.error(f"Failed to fetch entities from {source['source_name']}: {e}")
            return []
            
    def _sync_delistings(self, entities, source_name):
        """Deactivate records the source no longer lists (and reactivate ones it
        lists again). Without this a delisted person stayed an active hit for
        ever. Guarded: skipped when the download looks partial (fewer than 80%
        of the currently active records), so a truncated file cannot wipe a list.
        """
        ids = list({e['source_id'] for e in entities if e.get('source_id')})
        cur = self.db_conn.cursor()
        # Compare with the active records written in the CURRENT id format only.
        # Older importers wrote the same people under other ids (eu_123 vs
        # EU-EU.1.2, hmt_RUS1 vs HMT-RUS1); counting those doubled the active
        # total, so the guard always skipped and the duplicates never left.
        import re as _re
        prefixes = sorted({_re.match(r'^\D*', i).group(0) for i in ids})
        cur.execute("""SELECT count(*) AS n FROM screening_watchlist
                       WHERE source = %s AND is_active = 1
                         AND substring(source_id from '^\\D*') = ANY(%s)""", (source_name, prefixes))
        row = cur.fetchone()
        active = row['n'] if isinstance(row, dict) else row[0]
        approved = getattr(self, '_delist_approved', False)   # MLRO approved this exact download (P2-1)
        if not ids or (active and len(ids) < 0.8 * active and not approved):
            logger.warning(f"[DELIST] {source_name}: {len(ids)} fetched vs {active} active — skipped (partial download?)")
            return {'delisted': 0, 'relisted': 0, 'delist_skipped': True}
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS _fetched_ids (source_id text PRIMARY KEY) ON COMMIT DROP")
        cur.execute("TRUNCATE _fetched_ids")
        from psycopg2.extras import execute_values
        execute_values(cur, "INSERT INTO _fetched_ids (source_id) VALUES %s ON CONFLICT DO NOTHING",
                       [(i,) for i in ids], page_size=5000)
        cur.execute("""UPDATE screening_watchlist w SET is_active = 0, updated_at = now()
                       WHERE w.source = %s AND w.is_active = 1
                         AND NOT EXISTS (SELECT 1 FROM _fetched_ids f WHERE f.source_id = w.source_id)""",
                    (source_name,))
        delisted = cur.rowcount
        cur.execute("""UPDATE screening_watchlist w SET is_active = 1, updated_at = now()
                       WHERE w.source = %s AND w.is_active = 0
                         AND EXISTS (SELECT 1 FROM _fetched_ids f WHERE f.source_id = w.source_id)""",
                    (source_name,))
        relisted = cur.rowcount
        self.db_conn.commit()
        logger.info(f"[DELIST] {source_name}: {delisted} delisted, {relisted} relisted")
        return {'delisted': delisted, 'relisted': relisted}

    def _import_entities_batch(self, entities, source_name):
        """
        Batch import with chunked SELECT to avoid 65k param limit.
        Returns: (added_count, updated_count, unchanged_count)
        """
        if not entities:
            return 0, 0, 0

        if str(source_name or '').startswith('opensanctions') and not self._os_rich_enabled():
            # Until scripts/backfill_opensanctions_rich.py has filled the profile fields of the
            # ~2.2M existing rows (and switched this on), a daily run must not rewrite every row
            # because its content hash is still empty: rich fields are only stored for rows that
            # change for another reason (name) or are new.
            for e in entities:
                e.pop('_rich', None)

        cursor = self.db_conn.cursor()
        added, updated, unchanged = 0, 0, 0
        
        # Process in chunks of 10,000 to avoid PostgreSQL param limit (65,535)
        chunk_size = 200  # Small chunks so progress bar updates for both small (UN~1000) and large (OpenSanctions~800k) datasets
        insert_batch = []
        insert_batch_size = 500
        
        for chunk_start in range(0, len(entities), chunk_size):
            chunk = entities[chunk_start:chunk_start + chunk_size]
            source_ids = [e['source_id'] for e in chunk]
            
            # Get existing records for this chunk
            placeholders = ','.join(['%s'] * len(source_ids))
            cursor.execute(
                f"SELECT source_id, id, full_name, content_hash FROM screening_watchlist "
                f"WHERE source = %s AND source_id IN ({placeholders})",
                [source_name] + source_ids
            )
            existing_map = {row['source_id']: dict(row) for row in cursor.fetchall()}
            
            # Process this chunk
            for entity in chunk:
                source_id = entity['source_id']
                
                if source_id not in existing_map:
                    insert_batch.append(entity)
                    added += 1
                else:
                    existing = existing_map[source_id]
                    rich_changed = entity.get('_rich') and existing.get('content_hash') != self._content_hash(entity)
                    if existing.get('full_name') != entity.get('full_name') or rich_changed:
                        self._update_entity(entity, cursor)
                        self._store_rich(entity, cursor, source_name)
                        updated += 1
                    else:
                        unchanged += 1
                
                # Batch insert
                if len(insert_batch) >= insert_batch_size:
                    self._batch_insert_entities(insert_batch, cursor, source_name)
                    insert_batch = []
            
            # Update progress every chunk
            if hasattr(self, 'task_id') and self.task_id:
                processed = chunk_start + len(chunk)
                self._update_task_progress(processed, len(entities))
            
            # Free memory after each chunk
            del existing_map
        
        # Final batch
        if insert_batch:
            self._batch_insert_entities(insert_batch, cursor, source_name)
        
        logger.info(f"Batch import complete: {added} added, {updated} updated, {unchanged} unchanged")
        return added, updated, unchanged


    def _update_task_progress(self, processed, total):
        """Update task progress in screening_tasks table"""
        if not hasattr(self, 'task_id') or not self.task_id:
            return
        try:
            import psycopg2
            from config import get_config
            cfg = get_config()
            conn = psycopg2.connect(**cfg.POSTGRES_CONFIG)
            cur = conn.cursor()
            pct = int((processed / total) * 100) if total > 0 else 0
            cur.execute("""
                UPDATE screening_tasks SET progress = %s, 
                message = %s, updated_at = NOW()
                WHERE task_id = %s
            """, (pct, f"Importing: {processed:,} / {total:,} records ({pct}%)", self.task_id))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            pass  # Don't let progress update failures kill the sync
    
    def _update_download_progress(self, count, message):
        """Update task status during download phase (before batch processing)"""
        if not hasattr(self, 'task_id') or not self.task_id:
            return
        try:
            import psycopg2
            from config import get_config
            cfg = get_config()
            conn = psycopg2.connect(**cfg.POSTGRES_CONFIG)
            cur = conn.cursor()
            # Calculate rough progress % based on count (UN ~1000, OpenSanctions ~800k)
            est_total = 1000 if count < 5000 else 800000
            pct = min(int((count / est_total) * 40), 40)  # Download = 0-40%
            cur.execute("""
                UPDATE screening_tasks SET message = %s, progress = %s, updated_at = NOW()
                WHERE task_id = %s
            """, (message, pct, self.task_id))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as _e:
            logger.warning(f"_update_download_progress failed: {_e}")

    def _os_rich_enabled(self):
        """screening_config 'opensanctions_rich' = 'on' (set by the backfill when it completes)."""
        try:
            from screening.list_versions import _cfg_raw
            return str(_cfg_raw(self.db_conn, 'opensanctions_rich') or '').strip().lower() == 'on'
        except Exception as e:
            logger.warning(f"opensanctions_rich flag unreadable ({e}); rich fields off")
            return False

    def _has_entity_changed_fast(self, existing, new_entity):
        """Quick comparison without JSON parsing"""
        if existing.get('full_name') != new_entity.get('full_name'):
            return True
        return False
    
    @staticmethod
    def _content_hash(entity):
        """Fingerprint of everything stored for a record, so a changed date of birth, alias or
        identifier is updated even when the name is unchanged."""
        import hashlib
        from screening.format_handlers import expand_rich
        entity = expand_rich(entity)
        keys = ('full_name', 'original_name', 'full_name_arabic', 'aliases', 'aliases_arabic', 'entity_type',
                'date_of_birth', 'place_of_birth', 'nationality', 'gender', 'passport_numbers',
                'national_id_numbers', 'addresses', 'details', 'properties', 'dataset', 'topics', 'first_seen')
        blob = json.dumps({k: entity.get(k) for k in keys}, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha1(blob.encode('utf-8')).hexdigest()

    def _store_rich(self, entity, cursor, source_name):
        """Profile fields (place of birth, identifiers, addresses, properties, Arabic names) and the
        content hash, only for handlers that provide them (entity['_rich']). The list is the source of
        truth: values are overwritten, so a document or address the list removes disappears too."""
        if not entity.get('_rich'):
            return
        from screening.format_handlers import expand_rich
        entity = expand_rich(entity)
        j = stored_json_value
        cursor.execute("""
            UPDATE screening_watchlist SET
                place_of_birth = %s,
                passport_numbers = %s,
                national_id_numbers = %s,
                addresses = %s,
                properties = %s,
                full_name_arabic = %s,
                aliases_arabic = %s,
                first_seen = COALESCE(%s, first_seen),
                content_hash = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE source = %s AND source_id = %s
        """, (entity.get('place_of_birth'), j(entity.get('passport_numbers')), j(entity.get('national_id_numbers')),
              j(entity.get('addresses')), j(entity.get('properties')), entity.get('full_name_arabic'),
              j(entity.get('aliases_arabic')), entity.get('first_seen'), self._content_hash(entity),
              source_name or entity.get('source'), entity['source_id']))

    def _batch_insert_entities(self, entities, cursor, source_name=None):
        """True bulk insert using executemany"""
        if not entities:
            return
        
        insert_data = []
        for entity in entities:
            try:
                # Prepare data for bulk insert
                name_norm = normalize_arabic_text(entity['full_name'])
                import jellyfish
                soundex = jellyfish.soundex(name_norm) if name_norm else None
                metaphone = jellyfish.metaphone(name_norm) if name_norm else None
                
                # Extract year of birth
                yob = None
                if entity.get('date_of_birth'):
                    try:
                        yob = int(str(entity['date_of_birth'])[:4])
                    except Exception as e:
                        logger.debug(f"[SWALLOWED] year-of-birth parsing failed: {e}")
                
                # Serialize complex fields
                import json
                topics_json = json.dumps(entity.get('topics', []))
                countries_json = json.dumps(entity.get('countries', []))
                aliases_json = json.dumps(entity.get('aliases', []))
                details_json = json.dumps(entity.get('details', {}))
                
                insert_data.append((
                    entity['source_id'], entity['full_name'], entity.get('original_name'),
                    name_norm, soundex, metaphone,
                    entity.get('dataset', entity.get('source', 'opensanctions')),
                    entity.get('list_type', 'SANCTIONS'),
                    entity.get('entity_type', 'INDIVIDUAL'),
                    topics_json, countries_json,
                    entity.get('date_of_birth'), yob,
                    entity.get('nationality'), entity.get('gender'),
                    entity.get('source_url'), source_name or entity.get('source', 'opensanctions'),
                    entity.get('risk_level', 'MEDIUM'),
                    aliases_json, details_json
                ))
            except Exception as e:
                logger.warning(f"Failed to prepare entity {entity.get('source_id')}: {e}")
        
        # Bulk insert with executemany
        if insert_data:
            # updated_at must be set explicitly here: the trg_watchlist_updated_at
            # trigger only fires BEFORE UPDATE, not BEFORE INSERT, and the column
            # has no default — without this, fresh inserts get a NULL updated_at
            # and es_incremental_sync.py's change-detection (updated_at >= last_sync)
            # never picks them up, so brand-new records would silently never reach
            # Elasticsearch.
            cursor.executemany("""
                INSERT INTO screening_watchlist (
                    source_id, full_name, original_name, name_normalized, name_soundex, name_metaphone,
                    dataset, list_type, entity_type, topics, countries,
                    date_of_birth, year_of_birth, nationality, gender,
                    source_url, source, risk_level, aliases, details, is_active, last_updated, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (source, source_id) DO NOTHING
            """, insert_data)
            for entity in entities:
                if entity.get('_rich'):
                    self._store_rich(entity, cursor, source_name)

    def _has_entity_changed(self, existing, new_entity):
        """
        Check if entity data has changed (excluding timestamps).
        """
        # Compare key fields
        fields_to_compare = [
            'full_name', 'original_name', 'entity_type', 'risk_level',
            'date_of_birth', 'nationality', 'aliases', 'details', 'topics', 'list_type'
        ]
        
        for field in fields_to_compare:
            existing_val = existing.get(field)
            new_val = new_entity.get(field)
            
            # Normalize for comparison
            if field == 'aliases':
                # Compare as sets
                existing_aliases = set(json.loads(existing_val) if existing_val else [])
                new_aliases = set(new_val if isinstance(new_val, list) else [])
                if existing_aliases != new_aliases:
                    return True
            elif field in ('topics', 'list_type'):
                # only when the stored row was read with the field (older callers do not select it)
                if field not in existing:
                    continue
                if field == 'topics':
                    from screening.list_category import topics_list as _tl
                    if set(_tl(existing_val)) != set(_tl(new_val)):
                        return True
                elif (existing_val or None) != (new_val or None):
                    return True
            elif field == 'details':
                # Compare as JSON
                existing_details = json.loads(existing_val) if existing_val else {}
                new_details = new_val if isinstance(new_val, dict) else {}
                if existing_details != new_details:
                    return True
            else:
                # Direct comparison
                if existing_val != new_val:
                    return True
                    
        return False
        
    def _insert_entity(self, entity, cursor):
        """Insert new entity into database"""
        # Prepare data
        name_norm = normalize_arabic_text(entity['full_name'])
        soundex = jellyfish.soundex(name_norm) if name_norm else None
        metaphone = jellyfish.metaphone(name_norm) if name_norm else None
        
        # Extract year of birth
        yob = None
        if entity.get('date_of_birth'):
            try:
                yob = int(str(entity['date_of_birth'])[:4])
            except Exception as e:
                logger.debug(f"[SWALLOWED] year-of-birth parsing failed: {e}")
                
        # Serialize complex fields
        topics_json = json.dumps(entity.get('topics', []))
        countries_json = json.dumps(entity.get('countries', []))
        aliases_json = json.dumps(entity.get('aliases', []))
        details_json = json.dumps(entity.get('details', {}))
        
        if self.db_type == 'sqlite':
            cursor.execute("""
                INSERT INTO screening_watchlist (
                    source_id, full_name, original_name, name_normalized, name_soundex, name_metaphone,
                    dataset, list_type, entity_type, topics, countries,
                    date_of_birth, year_of_birth, nationality, gender,
                    source_url, source, risk_level, aliases, details, is_active, last_updated
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, CURRENT_TIMESTAMP)
            """, (
                entity['source_id'], entity['full_name'], entity.get('original_name'),
                name_norm, soundex, metaphone,
                entity.get('dataset', entity.get('source', 'ofac')), entity.get('list_type', 'SANCTIONS'), entity.get('entity_type', 'INDIVIDUAL'),
                topics_json, countries_json,
                entity.get('date_of_birth'), yob,
                entity.get('nationality'), entity.get('gender'),
                entity.get('source_url'), entity.get('source'), entity.get('risk_level', 'HIGH'),
                aliases_json, details_json
            ))
        else:
            cursor.execute("""
                INSERT INTO screening_watchlist (
                    source_id, full_name, original_name, name_normalized, name_soundex, name_metaphone,
                    dataset, list_type, entity_type, topics, countries,
                    date_of_birth, year_of_birth, nationality, gender,
                    source_url, source, risk_level, aliases, details, is_active, last_updated
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, CURRENT_TIMESTAMP)
            """, (
                entity['source_id'], entity['full_name'], entity.get('original_name'),
                name_norm, soundex, metaphone,
                entity.get('dataset', entity.get('source', 'ofac')), entity.get('list_type', 'SANCTIONS'), entity.get('entity_type', 'INDIVIDUAL'),
                topics_json, countries_json,
                entity.get('date_of_birth'), yob,
                entity.get('nationality'), entity.get('gender'),
                entity.get('source_url'), entity.get('source'), entity.get('risk_level', 'HIGH'),
                aliases_json, details_json
            ))
            
    def _update_entity(self, entity, cursor):
        """Update existing entity"""
        # Prepare data (same as insert)
        name_norm = normalize_arabic_text(entity['full_name'])
        soundex = jellyfish.soundex(name_norm) if name_norm else None
        metaphone = jellyfish.metaphone(name_norm) if name_norm else None
        
        yob = None
        if entity.get('date_of_birth'):
            try:
                yob = int(str(entity['date_of_birth'])[:4])
            except Exception as e:
                logger.debug(f"[SWALLOWED] year-of-birth parsing failed: {e}")
                
        topics_json = json.dumps(entity.get('topics', []))
        countries_json = json.dumps(entity.get('countries', []))
        aliases_json = json.dumps(entity.get('aliases', []))
        details_json = json.dumps(entity.get('details', {}))
        
        cursor.execute(f"""
            UPDATE screening_watchlist SET
                full_name = {self.placeholder},
                original_name = {self.placeholder},
                name_normalized = {self.placeholder},
                name_soundex = {self.placeholder},
                name_metaphone = {self.placeholder},
                dataset = {self.placeholder},
                list_type = {self.placeholder},
                entity_type = {self.placeholder},
                topics = {self.placeholder},
                countries = {self.placeholder},
                date_of_birth = {self.placeholder},
                year_of_birth = {self.placeholder},
                nationality = {self.placeholder},
                gender = {self.placeholder},
                source_url = {self.placeholder},
                risk_level = {self.placeholder},
                aliases = {self.placeholder},
                details = {self.placeholder},
                last_updated = CURRENT_TIMESTAMP
            WHERE source_id = {self.placeholder} AND source = {self.placeholder}
        """, (
            entity['full_name'], entity.get('original_name'),
            name_norm, soundex, metaphone,
            # .get() with the same defaults as the insert path: the OFAC / HMT
            # handlers do not set 'dataset', and entity['dataset'] raised
            # KeyError on every changed record — OFAC and HMT silently stopped
            # updating on 2026-07-22/24 while the run still reported [OK].
            entity.get('dataset', entity.get('source', 'unknown')),
            entity.get('list_type', 'SANCTIONS'), entity.get('entity_type', 'INDIVIDUAL'),
            topics_json, countries_json,
            entity.get('date_of_birth'), yob,
            entity.get('nationality'), entity.get('gender'),
            entity.get('source_url'), entity.get('risk_level', 'MEDIUM'),
            aliases_json, details_json,
            entity['source_id'], entity.get('source')
        ))
        
    def _create_audit_log(self, user_id, total_sources):
        """Create audit log entry at start of update"""
        cursor = self.db_conn.cursor()
        
        if self.db_type == 'sqlite':
            cursor.execute("""
                INSERT INTO data_update_audit_log (
                    update_type, initiated_by, total_sources, status, started_at
                ) VALUES ('FULL_UPDATE', %s, %s, 'IN_PROGRESS', CURRENT_TIMESTAMP)
            """, (user_id, total_sources))
            audit_id = cursor.lastrowid
        else:
            cursor.execute("""
                INSERT INTO data_update_audit_log (
                    update_type, initiated_by, total_sources, status, started_at
                ) VALUES ('FULL_UPDATE', %s, %s, 'IN_PROGRESS', CURRENT_TIMESTAMP)
                RETURNING id
            """, (user_id, total_sources))
            audit_id = cursor.fetchone()['id']
            
        self.db_conn.commit()
        return audit_id
        
    def _finalize_audit_log(self, audit_id, stats):
        """Update audit log with final statistics"""
        cursor = self.db_conn.cursor()
        
        duration_seconds = (stats['end_time'] - stats['start_time']).total_seconds()
        
        cursor.execute(f"""
            UPDATE data_update_audit_log SET
                records_added = {self.placeholder},
                records_updated = {self.placeholder},
                records_unchanged = {self.placeholder},
                errors_count = {self.placeholder},
                status = 'COMPLETED',
                completed_at = CURRENT_TIMESTAMP,
                duration_seconds = {self.placeholder}
            WHERE id = {self.placeholder}
        """, (
            stats['added'], stats['updated'], stats['unchanged'],
            stats['errors'], int(duration_seconds), audit_id
        ))
        
        self.db_conn.commit()
        
    def _mark_audit_log_failed(self, audit_id, error_message):
        """Update audit log to mark it as FAILED when an exception occurs."""
        cursor = self.db_conn.cursor()
        
        cursor.execute(f"""
            UPDATE data_update_audit_log SET
                status = 'FAILED',
                completed_at = CURRENT_TIMESTAMP,
                error_message = {self.placeholder}
            WHERE id = {self.placeholder}
        """, (error_message, audit_id))
        
        self.db_conn.commit()

    def _update_source_metadata(self, source_id, source_stats, user_id):
        """Update source metadata after processing"""
        cursor = self.db_conn.cursor()
        if source_stats.get('errors'):
            # A failed or blocked update must not make the list look fresh (P2-7):
            # it used to stamp last_successful_update even when nothing was applied.
            cursor.execute(f"UPDATE screening_data_sources SET consecutive_failures = COALESCE(consecutive_failures, 0) + 1, "
                           f"last_update_attempt = CURRENT_TIMESTAMP, last_update_error = {self.placeholder} "
                           f"WHERE id = {self.placeholder}",
                           (str(source_stats.get('error') or 'update failed')[:1000], source_id))
            return
        
        cursor.execute(f"""
            UPDATE screening_data_sources SET
                last_successful_update = CURRENT_TIMESTAMP,
                last_update_attempt = CURRENT_TIMESTAMP,
                last_update_error = NULL,
                consecutive_failures = 0,
                last_updated_by = {self.placeholder},
                last_update_records_added = {self.placeholder},
                last_update_records_updated = {self.placeholder}
            WHERE id = {self.placeholder}
        """, (user_id, source_stats['added'], source_stats['updated'], source_id))


# Convenience function for backward compatibility
def update_watchlist_all(db_config):
    """Update all active sources"""
    updater = EnhancedDataUpdater(db_config)
    return updater.update_watchlist()


if __name__ == "__main__":
    # Test the updater
    import os
    logging.basicConfig(level=logging.INFO)
    
    db = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'complynex.db')
    
    updater = EnhancedDataUpdater(db)
    stats = updater.update_watchlist()
    
    print("\n=== Update Statistics ===")
    print(json.dumps(stats, indent=2, default=str))
