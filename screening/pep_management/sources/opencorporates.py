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
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class OpenCorporatesAdapter:
    """
    Query OpenCorporates for corporate officer relationships
    Docs: https://api.opencorporates.com/documentation/API-Reference
    """
    
    BASE_URL = "https://api.opencorporates.com/v0.4"
    
    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token
        self.session = requests.Session()
    
    def search_person_as_officer(self, name: str, jurisdiction: str = 'eg') -> List[Dict]:
        """
        Search for a person's corporate officer roles in Egypt
        """
        logger.info(f"[OpenCorporates] Searching for: {name}")
        
        try:
            params = {
                'q': name,
                'jurisdiction_code': jurisdiction,
                'per_page': 100
            }
            
            if self.api_token:
                params['api_token'] = self.api_token
            
            response = self.session.get(
                f"{self.BASE_URL}/officers/search",
                params=params,
                timeout=30
            )
            
            data = response.json()
            officers = data.get('results', {}).get('officers', [])
            
            corporate_links = []
            for officer in officers:
                officer_data = officer.get('officer', {})
                company_data = officer_data.get('company', {})
                
                corporate_links.append({
                    'company_name': company_data.get('name'),
                    'company_jurisdiction': company_data.get('jurisdiction_code'),
                    'company_number': company_data.get('company_number'),
                    'role': officer_data.get('position'),
                    'start_date': officer_data.get('start_date'),
                    'end_date': officer_data.get('end_date'),
                    'opencorporates_url': officer_data.get('opencorporates_url'),
                    'source': 'opencorporates'
                })
            
            logger.info(f"[OpenCorporates] Found {len(corporate_links)} corporate links")
            return corporate_links
            
        except Exception as e:
            logger.error(f"[OpenCorporates] Error: {str(e)}")
            return []
