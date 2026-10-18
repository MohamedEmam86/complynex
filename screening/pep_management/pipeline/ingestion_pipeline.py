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
Master Data Ingestion Pipeline
Orchestrates all data sources and manages the complete ETL process
"""

import asyncio
from typing import List, Dict, Optional
import json
from datetime import datetime
import logging
from concurrent.futures import ProcessPoolExecutor

logger = logging.getLogger(__name__)


class DataIngestionPipeline:
    """
    Master orchestrator for PEP data ingestion
    Manages all sources, deduplication, and database updates
    """
    
    def __init__(self, db_connection, config: Dict):
        self.db = db_connection
        self.config = config
        
        # Initialize source adapters
        from ..sources.opensanctions import OpenSanctionsAdapter
        from ..sources.wikidata import WikidataAdapter
        from ..sources.egypt_gov import EgyptGovAdapter
        from ..sources.opencorporates import OpenCorporatesAdapter
        
        self.sources = {
            'opensanctions': OpenSanctionsAdapter(),
            'wikidata': WikidataAdapter(),
            'egypt_gov': EgyptGovAdapter(),
            'opencorporates': OpenCorporatesAdapter(
                api_token=config.get('opencorporates_api_token')
            )
        }
        
        # Initialize deduplication engine
        from ..matching.deduplication_engine import DeduplicationEngine
        self.dedup_engine = DeduplicationEngine(db_connection)
        
        # Statistics
        self.stats = {
            'total_fetched': 0,
            'total_added': 0,
            'total_updated': 0,
            'total_merged': 0,
            'total_failed': 0,
            'by_source': {}
        }
    
    async def run_full_update(self) -> Dict:
        """
        Run complete data update from all sources
        
        Returns:
            Statistics dictionary
        """
        logger.info("="*70)
        logger.info("STARTING FULL PEP DATA UPDATE")
        logger.info("="*70)
        
        start_time = datetime.now()
        
        # Create update log entry
        log_id = self._create_update_log('full')
        
        try:
            # Phase 1: Fetch from all sources (parallel)
            logger.info("\n📥 PHASE 1: FETCHING DATA FROM ALL SOURCES")
            all_records = await self._fetch_from_all_sources()
            
            self.stats['total_fetched'] = len(all_records)
            logger.info(f"✅ Fetched {len(all_records)} total records")
            
            # Phase 2: Process and deduplicate
            logger.info("\n🔍 PHASE 2: PROCESSING AND DEDUPLICATING")
            processed_records = await self._process_records(all_records)
            
            # Phase 3: Update database
            logger.info("\n💾 PHASE 3: UPDATING DATABASE")
            await self._update_database(processed_records)
            
            # Phase 4: Enrich with corporate data
            logger.info("\n🏢 PHASE 4: ENRICHING WITH CORPORATE DATA")
            await self._enrich_corporate_links()
            
            # Phase 5: Run deduplication check
            logger.info("\n🔗 PHASE 5: DETECTING DUPLICATES")
            await self._detect_duplicates()
            
            # Complete update log
            duration = (datetime.now() - start_time).total_seconds()
            self._complete_update_log(log_id, 'completed', duration)
            
            logger.info("\n" + "="*70)
            logger.info("UPDATE COMPLETE!")
            logger.info("="*70)
            logger.info(f"Duration: {duration:.1f} seconds")
            logger.info(f"Fetched: {self.stats['total_fetched']}")
            logger.info(f"Added: {self.stats['total_added']}")
            logger.info(f"Updated: {self.stats['total_updated']}")
            logger.info(f"Merged: {self.stats['total_merged']}")
            logger.info(f"Failed: {self.stats['total_failed']}")
            logger.info("="*70)
            
            return self.stats
            
        except Exception as e:
            logger.error(f"❌ Update failed: {str(e)}")
            self._complete_update_log(log_id, 'failed', error=str(e))
            raise
    
    async def _fetch_from_all_sources(self) -> List[Dict]:
        """Fetch data from all sources in parallel"""
        all_records = []
        
        # Use ProcessPoolExecutor for parallel fetching
        with ProcessPoolExecutor(max_workers=4) as executor:
            futures = {}
            
            # OpenSanctions
            if self.config.get('opensanctions_enabled', True):
                futures['opensanctions'] = executor.submit(
                    self.sources['opensanctions'].fetch_all_peps
                )
            
            # Wikidata
            if self.config.get('wikidata_enabled', True):
                futures['wikidata'] = executor.submit(
                    self.sources['wikidata'].fetch_egyptian_politicians
                )
            
            # Egyptian Government sites
            if self.config.get('egypt_gov_enabled', True):
                futures['cabinet'] = executor.submit(
                    self.sources['egypt_gov'].fetch_cabinet_members
                )
                futures['parliament'] = executor.submit(
                    self.sources['egypt_gov'].fetch_parliament_members
                )
            
            # Collect results
            for source_name, future in futures.items():
                try:
                    records = future.result(timeout=300)  # 5 min timeout
                    all_records.extend(records)
                    
                    self.stats['by_source'][source_name] = {
                        'fetched': len(records),
                        'status': 'success'
                    }
                    
                    logger.info(f"✅ {source_name}: {len(records)} records")
                    
                except Exception as e:
                    logger.error(f"❌ {source_name} failed: {str(e)}")
                    self.stats['by_source'][source_name] = {
                        'fetched': 0,
                        'status': 'failed',
                        'error': str(e)
                    }
        
        return all_records
    
    async def _process_records(self, records: List[Dict]) -> List[Dict]:
        """
        Process and normalize records
        - Extract all name variants
        - Normalize dates
        - Validate data
        """
        logger.info(f"Processing {len(records)} records...")
        
        processed = []
        
        for i, record in enumerate(records):
            if (i + 1) % 100 == 0:
                logger.info(f"   Processed: {i+1}/{len(records)}")
            
            try:
                # Validate required fields
                if not record.get('canonical_name_en') and not record.get('canonical_name_ar'):
                    logger.warning(f"Skipping record without name: {record}")
                    continue
                
                # Normalize dates
                if record.get('date_of_birth'):
                    if isinstance(record['date_of_birth'], str):
                        try:
                            record['date_of_birth'] = datetime.strptime(
                                record['date_of_birth'], '%Y-%m-%d'
                            ).date()
                        except Exception as e:
                            logger.debug(f"[SWALLOWED] PEP date_of_birth parsing failed: {e}")
                            record['date_of_birth'] = None
                
                # Extract all name variants
                record['all_aliases'] = self._extract_aliases(record)
                
                processed.append(record)
                
            except Exception as e:
                logger.error(f"Error processing record: {str(e)}")
                self.stats['total_failed'] += 1
        
        logger.info(f"✅ Successfully processed {len(processed)} records")
        return processed
    
    def _extract_aliases(self, record: Dict) -> List[Dict]:
        """Extract all name variations for a record"""
        aliases = []
        
        # Get names
        name_en = record.get('canonical_name_en', '')
        name_ar = record.get('canonical_name_ar', '')
        
        # Add canonical names as aliases
        if name_en:
            aliases.append({
                'alias_name': name_en,
                'alias_language': 'en',
                'alias_type': 'canonical',
                'source': record.get('source')
            })
        
        if name_ar:
            aliases.append({
                'alias_name': name_ar,
                'alias_language': 'ar',
                'alias_type': 'canonical',
                'source': record.get('source')
            })
        
        # Add existing aliases from record
        if 'aliases' in record:
            for alias in record['aliases']:
                # Detect language
                from ..matching.deduplication_engine import ArabicEnglishTransliterator
                is_arabic = ArabicEnglishTransliterator.is_arabic(alias)
                
                aliases.append({
                    'alias_name': alias,
                    'alias_language': 'ar' if is_arabic else 'en',
                    'alias_type': 'alias',
                    'source': record.get('source')
                })
        
        # Generate transliterations
        if name_ar and not name_en:
            # Generate English variants
            from ..matching.deduplication_engine import ArabicEnglishTransliterator
            variants = ArabicEnglishTransliterator.get_english_variants(name_ar)
            
            for variant in variants[:10]:  # Limit to 10
                aliases.append({
                    'alias_name': variant,
                    'alias_language': 'en',
                    'alias_type': 'transliteration',
                    'source': 'generated'
                })
        
        elif name_en and not name_ar:
            # Generate Arabic variants
            from ..matching.deduplication_engine import ArabicEnglishTransliterator
            variants = ArabicEnglishTransliterator.get_arabic_variants(name_en)
            
            for variant in variants[:10]:
                aliases.append({
                    'alias_name': variant,
                    'alias_language': 'ar',
                    'alias_type': 'transliteration',
                    'source': 'generated'
                })
        
        return aliases
    
    async def _update_database(self, records: List[Dict]):
        """
        Update database with processed records
        - Check for existing PEPs
        - Add new or update existing
        - Handle deduplication
        """
        logger.info(f"Updating database with {len(records)} records...")
        
        for i, record in enumerate(records):
            if (i + 1) % 50 == 0:
                logger.info(f"   Updated: {i+1}/{len(records)}")
            
            try:
                # Check if PEP already exists
                existing_pep = self._find_existing_pep(record)
                
                if existing_pep:
                    # Update existing record
                    self._update_pep(existing_pep['id'], record)
                    self.stats['total_updated'] += 1
                else:
                    # Add new PEP
                    pep_id = self._insert_pep(record)
                    self.stats['total_added'] += 1
                
            except Exception as e:
                logger.error(f"Error updating database: {str(e)}")
                self.stats['total_failed'] += 1
        
        self.db.commit()
        logger.info("✅ Database update complete")
    
    def _find_existing_pep(self, record: Dict) -> Optional[Dict]:
        """Find existing PEP record in database"""
        cursor = self.db.cursor()
        
        # Try to find by source ID first
        if record.get('source_id'):
            cursor.execute("""
                SELECT p.id, p.canonical_name_en
                FROM pep_master p
                JOIN pep_sources s ON p.id = s.pep_id
                WHERE s.source_name = %s
                  AND s.source_record_id = %s
                LIMIT 1
            """, (record['source'], str(record['source_id'])))
            
            result = cursor.fetchone()
            if result:
                # Convert the result dict/tuple to a dict
                fields = [desc[0] for desc in cursor.description]
                return dict(zip(fields, result))
        
        # Try fuzzy match
        name_en = record.get('canonical_name_en', '')
        if name_en:
            cursor.execute("""
                SELECT id, canonical_name_en
                FROM pep_master
                WHERE similarity(canonical_name_en, %s) > 0.8
                ORDER BY similarity(canonical_name_en, %s) DESC
                LIMIT 1
            """, (name_en, name_en))
            
            result = cursor.fetchone()
            if result:
                fields = [desc[0] for desc in cursor.description]
                return dict(zip(fields, result))
        
        return None
    
    def _insert_pep(self, record: Dict) -> int:
        """Insert new PEP record"""
        cursor = self.db.cursor()
        
        cursor.execute("""
            INSERT INTO pep_master (
                canonical_name_en, canonical_name_ar, date_of_birth,
                nationality, is_active, source_count, confidence_score
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            record.get('canonical_name_en'),
            record.get('canonical_name_ar'),
            record.get('date_of_birth'),
            record.get('nationality', 'EG'),
            True,
            1,
            0.7
        ))
        
        pep_id = cursor.fetchone()[0]
        
        # Insert source
        self._insert_source(pep_id, record)
        
        # Insert aliases
        for alias in record.get('all_aliases', []):
            self._insert_alias(pep_id, alias)
        
        # Insert positions
        for position in record.get('positions', []):
            self._insert_position(pep_id, position)
        
        return pep_id
    
    def _update_pep(self, pep_id: int, record: Dict):
        """Update existing PEP record"""
        cursor = self.db.cursor()
        
        # Update master record
        cursor.execute("""
            UPDATE pep_master
            SET last_updated = NOW(),
                source_count = source_count + 1
            WHERE id = %s
        """, (pep_id,))
        
        # Add new source
        self._insert_source(pep_id, record)
        
        # Add new aliases (if they don't exist)
        for alias in record.get('all_aliases', []):
            cursor.execute("""
                INSERT INTO pep_aliases (pep_id, alias_name, alias_language, alias_type, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (
                pep_id,
                alias['alias_name'],
                alias['alias_language'],
                alias['alias_type'],
                alias['source']
            ))
        
        # Add new positions
        for position in record.get('positions', []):
            self._insert_position(pep_id, position)
    
    def _insert_source(self, pep_id: int, record: Dict):
        """Insert source provenance record"""
        cursor = self.db.cursor()
        
        cursor.execute("""
            INSERT INTO pep_sources (
                pep_id, source_name, source_type, source_url,
                source_record_id, raw_data
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            pep_id,
            record.get('source'),
            'api',
            record.get('source_url'),
            str(record.get('source_id')),
            json.dumps(record.get('raw_data', {}))
        ))
    
    def _insert_alias(self, pep_id: int, alias: Dict):
        """Insert alias record"""
        cursor = self.db.cursor()
        
        cursor.execute("""
            INSERT INTO pep_aliases (
                pep_id, alias_name, alias_language, alias_type, source
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (
            pep_id,
            alias['alias_name'],
            alias['alias_language'],
            alias['alias_type'],
            alias['source']
        ))
    
    def _insert_position(self, pep_id: int, position: Dict):
        """Insert position record"""
        cursor = self.db.cursor()
        
        cursor.execute("""
            INSERT INTO pep_positions (
                pep_id, position_title_en, position_title_ar,
                organization_en, organization_ar,
                start_date, end_date, source
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            pep_id,
            position.get('title_en'),
            position.get('title_ar'),
            position.get('organization_en'),
            position.get('organization_ar'),
            position.get('start_date'),
            position.get('end_date'),
            position.get('source')
        ))
    
    async def _enrich_corporate_links(self):
        """Enrich PEPs with corporate officer data from OpenCorporates"""
        logger.info("Enriching with corporate data...")
        
        cursor = self.db.cursor()
        
        # Get all PEPs without corporate data
        cursor.execute("""
            SELECT id, canonical_name_en, canonical_name_ar
            FROM pep_master
            WHERE id NOT IN (
                SELECT DISTINCT pep_id FROM pep_corporate_links
            )
            LIMIT 100  -- Process in batches
        """)
        
        # Using dict instead of row factory to prevent issues
        fields = [desc[0] for desc in cursor.description]
        peps = [dict(zip(fields, row)) for row in cursor.fetchall()]
        
        for pep in peps:
            pep_id = pep['id']
            name_en = pep['canonical_name_en']
            
            if name_en:
                try:
                    corporate_links = self.sources['opencorporates'].search_person_as_officer(name_en)
                    
                    for link in corporate_links:
                        cursor.execute("""
                            INSERT INTO pep_corporate_links (
                                pep_id, company_name, company_jurisdiction,
                                company_number, role, start_date, end_date,
                                opencorporates_url
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            pep_id,
                            link['company_name'],
                            link['company_jurisdiction'],
                            link['company_number'],
                            link['role'],
                            link['start_date'],
                            link['end_date'],
                            link['opencorporates_url']
                        ))
                    
                except Exception as e:
                    logger.warning(f"Error enriching {name_en}: {str(e)}")
        
        self.db.commit()
        logger.info("✅ Corporate enrichment complete")
    
    async def _detect_duplicates(self):
        """Run deduplication check and log potential duplicates"""
        logger.info("Detecting potential duplicates...")
        
        cursor = self.db.cursor()
        
        # Get recently added/updated PEPs
        cursor.execute("""
            SELECT id, canonical_name_en, canonical_name_ar, date_of_birth
            FROM pep_master
            WHERE last_updated >= NOW() - INTERVAL '1 day'
        """)
        
        fields = [desc[0] for desc in cursor.description]
        recent_peps = [dict(zip(fields, row)) for row in cursor.fetchall()]
        
        for pep in recent_peps:
            duplicates = self.dedup_engine.find_duplicates(pep, threshold=0.75)
            
            for dup_id, score, reason in duplicates:
                # Log to duplicate candidates table
                cursor.execute("""
                    INSERT INTO pep_duplicate_candidates (
                        pep_id_1, pep_id_2, match_score, match_reason
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (pep['id'], dup_id, score, reason))
        
        self.db.commit()
        logger.info("✅ Duplicate detection complete")
    
    def _create_update_log(self, update_type: str) -> int:
        """Create update log entry"""
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO pep_update_logs (update_type, status, source_name)
            VALUES (%s, 'running', 'FULL_SYSTEM')
            RETURNING id
        """, (update_type,))
        return cursor.fetchone()[0]
    
    def _complete_update_log(self, log_id: int, status: str, 
                            duration: Optional[float] = None, 
                            error: Optional[str] = None):
        """Complete update log entry"""
        cursor = self.db.cursor()
        cursor.execute("""
            UPDATE pep_update_logs
            SET status = %s,
                completed_at = NOW(),
                records_fetched = %s,
                records_added = %s,
                records_updated = %s,
                records_merged = %s,
                records_failed = %s,
                error_message = %s
            WHERE id = %s
        """, (
            status,
            self.stats['total_fetched'],
            self.stats['total_added'],
            self.stats['total_updated'],
            self.stats['total_merged'],
            self.stats['total_failed'],
            error,
            log_id
        ))
        self.db.commit()
