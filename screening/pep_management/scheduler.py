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
import time
import schedule
from datetime import datetime
from threading import Thread
from typing import Dict

from .sources.opensanctions import OpenSanctionsAdapter
from .sources.wikidata import WikidataAdapter
from .sources.egypt_gov import EgyptGovAdapter
from .sources.opencorporates import OpenCorporatesAdapter
from .engine.ingestion import PEPIngestionEngine

logger = logging.getLogger(__name__)


class PEPScheduler:
    """
    Coordinates automatic updates for the PEP master database based on the 
    defined frequency for each source.
    """
    
    def __init__(self, db_config: Dict, oc_api_key: str = None):
        self.db_config = db_config
        self.ingestion = PEPIngestionEngine(db_config)
        self.oc_api_key = oc_api_key
        
        self.os_adapter = OpenSanctionsAdapter()
        self.wiki_adapter = WikidataAdapter()
        self.gov_adapter = EgyptGovAdapter()
        self.oc_adapter = OpenCorporatesAdapter(api_token=oc_api_key)
        
        self._scheduler_thread = None
        self._running = False
        
    def _sync_opensanctions(self):
        logger.info("[Scheduler] Starting Daily OpenSanctions Sync...")
        try:
            records = self.os_adapter.fetch_all_peps()
            self.ingestion.ingest_records('opensanctions', records)
        except Exception as e:
            logger.error(f"[Scheduler] OpenSanctions sync failed: {e}")

    def _sync_wikidata(self):
        logger.info("[Scheduler] Starting Daily Wikidata Sync...")
        try:
            records = self.wiki_adapter.fetch_egyptian_politicians()
            self.ingestion.ingest_records('wikidata', records)
        except Exception as e:
            logger.error(f"[Scheduler] Wikidata sync failed: {e}")

    def _sync_gov_websites(self):
        logger.info("[Scheduler] Starting Weekly Government Websites Sync...")
        try:
            cabinet = self.gov_adapter.fetch_cabinet_members()
            self.ingestion.ingest_records('cabinet.gov.eg', cabinet)
            
            parliament = self.gov_adapter.fetch_parliament_members()
            self.ingestion.ingest_records('parliament.gov.eg', parliament)
        except Exception as e:
            logger.error(f"[Scheduler] Gov website sync failed: {e}")

    def _sync_opencorporates(self):
        """
        OpenCorporates sync might loop over all active PEPs to search their names.
        """
        logger.info("[Scheduler] Starting Monthly OpenCorporates Sync...")
        try:
            # Note: For production, this should fetch current active PEPs from DB
            # and iterate through them. Mocking the loop here:
            pass
        except Exception as e:
            logger.error(f"[Scheduler] OpenCorporates sync failed: {e}")

    def configure_jobs(self):
        """Configure scheduling rules according to architecture spec."""
        # Daily: OpenSanctions, Wikidata
        schedule.every().day.at("02:00").do(self._sync_opensanctions)
        schedule.every().day.at("03:00").do(self._sync_wikidata)
        
        # Weekly: Government websites
        schedule.every().sunday.at("04:00").do(self._sync_gov_websites)
        
        # Monthly: OpenCorporates (approx 30 days)
        schedule.every(30).days.at("05:00").do(self._sync_opencorporates)
        
        logger.info("[Scheduler] Jobs configured successfully.")

    def run_pending(self):
        while self._running:
            schedule.run_pending()
            time.sleep(60)
            
    def start_background_service(self):
        """Launch the blocking scheduler loop in a background daemon thread."""
        if self._running:
            return
            
        self.configure_jobs()
        self._running = True
        self._scheduler_thread = Thread(target=self.run_pending, daemon=True)
        self._scheduler_thread.start()
        logger.info("[Scheduler] Background service started.")
        
    def stop(self):
        self._running = False
        if self._scheduler_thread:
            self._scheduler_thread.join()
        logger.info("[Scheduler] Background service stopped.")
        
    def trigger_manual_refresh(self, source: str = 'all'):
        """Utility for API endpoint to force a refresh outside of schedule."""
        if source in ['all', 'opensanctions']:
            self._sync_opensanctions()
        if source in ['all', 'wikidata']:
            self._sync_wikidata()
        if source in ['all', 'gov']:
            self._sync_gov_websites()
