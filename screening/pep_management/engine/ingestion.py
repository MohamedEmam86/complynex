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

import logging
from typing import Dict, List
import psycopg2
from psycopg2.extras import Json
from .deduplicator import PEPDeduplicator

logger = logging.getLogger(__name__)

class PEPIngestionEngine:
    """
    Handles Extract, Transform, and Load (ETL) operations from PEP data sources
    into the master PostgreSQL database.
    """
    
    def __init__(self, db_config: Dict):
        self.db_config = db_config
        self.deduplicator = PEPDeduplicator(db_config)
        
    def _get_connection(self):
        return psycopg2.connect(**self.db_config)
        
    def ingest_records(self, source_name: str, records: List[Dict]):
        """
        Main entry point for batch processing pulled PEP data formats.
        """
        logger.info(f"Starting ingestion of {len(records)} records from {source_name}")
        added = 0
        updated = 0
        failed = 0
        
        # We will create an update log run
        run_id = self._start_update_log(source_name)
        
        for record in records:
            try:
                # 1. Check if source already provided this entity (using source_id)
                existing_pep_id = self._find_existing_by_source_id(source_name, record.get('source_id'))
                
                if existing_pep_id:
                    self._update_existing_record(existing_pep_id, record)
                    updated += 1
                else:
                    new_id = self._insert_new_record(record)
                    added += 1
                    
                    # 2. Trigger asynchronous deduplication flagging
                    self.deduplicator.process_new_record_deduplication(new_id)
                    
            except Exception as e:
                logger.error(f"Failed to ingest record {record.get('canonical_name_en')}: {e}")
                failed += 1
                
        self._complete_update_log(run_id, len(records), added, updated, failed)
        logger.info(f"Ingestion complete: {added} added, {updated} updated, {failed} failed.")

    def _find_existing_by_source_id(self, source_name: str, source_id: str) -> int:
        if not source_id:
            return None
            
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pep_id FROM pep_sources 
                    WHERE source_name = %s AND source_record_id = %s
                """, (source_name, str(source_id)))
                row = cur.fetchone()
                return row[0] if row else None

    def _insert_new_record(self, record: Dict) -> int:
        """Insert a fresh PEP record and its related sub-tables."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Master Record
                cur.execute("""
                    INSERT INTO pep_master 
                    (canonical_name_en, canonical_name_ar, date_of_birth, nationality, source_count)
                    VALUES (%s, %s, %s, %s, 1)
                    RETURNING id
                """, (
                    record.get('canonical_name_en', ''),
                    record.get('canonical_name_ar'),
                    record.get('date_of_birth'),
                    record.get('nationality', 'EG')
                ))
                pep_id = cur.fetchone()[0]
                
                # 2. Source Provenance
                cur.execute("""
                    INSERT INTO pep_sources 
                    (pep_id, source_name, source_record_id, source_url, raw_data)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    pep_id,
                    record.get('source'),
                    str(record.get('source_id')),
                    record.get('source_url'),
                    Json(record.get('raw_data', {}))
                ))
                
                # 3. Aliases
                for alias in record.get('aliases', []):
                    # Basic language detection for 'en' vs 'ar'
                    lang = 'ar' if any('\u0600' <= c <= '\u06FF' for c in alias) else 'en'
                    cur.execute("""
                        INSERT INTO pep_aliases (pep_id, alias_name, alias_language, source)
                        VALUES (%s, %s, %s, %s)
                    """, (pep_id, alias, lang, record.get('source')))
                    
                # 4. Positions
                for pos in record.get('positions', []):
                    cur.execute("""
                        INSERT INTO pep_positions 
                        (pep_id, position_title_en, position_title_ar, organization_en, organization_ar, start_date, end_date, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        pep_id,
                        pos.get('title_en'),
                        pos.get('title_ar'),
                        pos.get('organization_en'),
                        pos.get('organization_ar'),
                        pos.get('start_date'),
                        pos.get('end_date'),
                        record.get('source')
                    ))
                    
                conn.commit()
                return pep_id

    def _update_existing_record(self, pep_id: int, record: Dict):
        """Update an existing PEP record. Currently updates timestamps and raw_data."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Update Master timestamp
                cur.execute("UPDATE pep_master SET last_updated = NOW() WHERE id = %s", (pep_id,))
                
                # Update Source data
                cur.execute("""
                    UPDATE pep_sources 
                    SET raw_data = %s, last_updated = NOW()
                    WHERE pep_id = %s AND source_name = %s
                """, (
                    Json(record.get('raw_data', {})),
                    pep_id,
                    record.get('source')
                ))
                conn.commit()

    def _start_update_log(self, source_name: str) -> int:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO pep_update_logs (source_name, update_type, status)
                    VALUES (%s, 'incremental', 'running')
                    RETURNING id
                """, (source_name,))
                conn.commit()
                return cur.fetchone()[0]

    def _complete_update_log(self, run_id: int, fetched: int, added: int, updated: int, failed: int):
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE pep_update_logs 
                    SET status = 'completed', completed_at = NOW(),
                        records_fetched = %s, records_added = %s, records_updated = %s, records_failed = %s
                    WHERE id = %s
                """, (fetched, added, updated, failed, run_id))
                conn.commit()
