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

import requests
import json
from typing import List, Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class OpenSanctionsAdapter:
    """
    Fetch PEP data from OpenSanctions.org
    Docs: https://www.opensanctions.org/docs/api/
    """
    
    BASE_URL = "https://data.opensanctions.org/datasets/latest"
    DATASET = "default"  # or 'peps' for PEPs only
    
    def __init__(self):
        self.session = requests.Session()
    
    def fetch_all_peps(self, country: str = 'eg') -> List[Dict]:
        """
        Download complete PEP dataset for Egypt
        
        Returns:
            List of PEP records in OpenSanctions format
        """
        logger.info("[OpenSanctions] Fetching PEP data for Egypt...")
        
        try:
            # Option 1: Download bulk JSON file
            url = f"{self.BASE_URL}/{self.DATASET}/entities.ftm.json"
            response = self.session.get(url, stream=True)
            
            peps = []
            for line in response.iter_lines():
                if line:
                    entity = json.loads(line)
                    
                    # Filter for Egyptian PEPs
                    if self._is_egyptian_pep(entity):
                        peps.append(self._normalize_entity(entity))
            
            logger.info(f"[OpenSanctions] Fetched {len(peps)} Egyptian PEPs")
            return peps
            
        except Exception as e:
            logger.error(f"[OpenSanctions] Error: {str(e)}")
            raise
    
    def _is_egyptian_pep(self, entity: Dict) -> bool:
        """Check if entity is an Egyptian PEP"""
        # Check schema type
        if entity.get('schema') != 'Person':
            return False
        
        # Check topics include 'role.pep'
        topics = entity.get('properties', {}).get('topics', [])
        if 'role.pep' not in topics:
            return False
        
        # Check country is Egypt
        countries = entity.get('properties', {}).get('country', [])
        if 'eg' not in [c.lower() for c in countries]:
            return False
        
        return True
    
    def _normalize_entity(self, entity: Dict) -> Dict:
        """
        Convert OpenSanctions format to our standard format
        
        OpenSanctions uses FollowTheMoney (FTM) schema
        """
        props = entity.get('properties', {})
        
        # Extract names
        names = props.get('name', [])
        name_en = names[0] if names else ''
        
        # Try to find Arabic name in aliases
        aliases = props.get('alias', [])
        name_ar = None
        for alias in aliases:
            if self._contains_arabic(alias):
                name_ar = alias
                break
        
        # Extract dates
        birth_date = None
        birth_dates = props.get('birthDate', [])
        if birth_dates:
            try:
                birth_date = datetime.strptime(birth_dates[0], '%Y-%m-%d').date()
            except Exception:
                pass
        
        return {
            'source': 'opensanctions',
            'source_id': entity.get('id'),
            'source_url': f"https://www.opensanctions.org/entities/{entity.get('id')}/",
            'canonical_name_en': name_en,
            'canonical_name_ar': name_ar,
            'date_of_birth': birth_date,
            'nationality': 'EG',
            'aliases': aliases,
            'positions': self._extract_positions(props),
            'raw_data': entity
        }
    
    def _extract_positions(self, props: Dict) -> List[Dict]:
        """Extract political positions from entity properties"""
        positions = []
        
        # OpenSanctions stores positions in 'position' property
        position_titles = props.get('position', [])
        
        for title in position_titles:
            positions.append({
                'title_en': title,
                'source': 'opensanctions'
            })
        
        return positions
    
    def _contains_arabic(self, text: str) -> bool:
        """Check if text contains Arabic characters"""
        return any('\u0600' <= c <= '\u06FF' for c in text)
