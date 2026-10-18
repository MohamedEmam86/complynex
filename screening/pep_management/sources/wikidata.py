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


class WikidataAdapter:
    """
    Query Wikidata for Egyptian politicians using SPARQL
    Docs: https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service
    """
    
    SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ComplyNex-CMS/1.0 (PEP-Data-Collection)'
        })
    
    def fetch_egyptian_politicians(self) -> List[Dict]:
        """
        Fetch all Egyptian politicians and position holders
        """
        logger.info("[Wikidata] Querying Egyptian politicians...")
        
        query = """
        SELECT DISTINCT %sperson %spersonLabel %spersonLabelAr %sdob %sposition %spositionLabel 
                        %sstartDate %sendDate %spartyLabel
        WHERE {
          # Person is a human
          %sperson wdt:P31 wd:Q5 .
          
          # Person holds or held a position
          %sperson p:P39 %spositionStatement .
          %spositionStatement ps:P39 %sposition .
          
          # Position is in Egypt (country: Egypt)
          {
            %sposition wdt:P17 wd:Q79 .  # Egypt
          } UNION {
            %sperson wdt:P27 wd:Q79 .    # Egyptian citizenship
          }
          
          # Get dates if available
          OPTIONAL { %sperson wdt:P569 %sdob }
          OPTIONAL { %spositionStatement pq:P580 %sstartDate }
          OPTIONAL { %spositionStatement pq:P582 %sendDate }
          OPTIONAL { %sperson wdt:P102 %sparty }
          
          # Get labels in English and Arabic
          SERVICE wikibase:label { 
            bd:serviceParam wikibase:language "en,ar" .
            %sperson rdfs:label %spersonLabel .
            %sperson rdfs:label %spersonLabelAr .
            FILTER(LANG(%spersonLabelAr) = "ar")
          }
          
          # Only get notable positions (ministers, MPs, governors, etc.)
          FILTER(%sposition IN (
            wd:Q15647814,  # Minister position
            wd:Q17275736,  # Member of parliament
            wd:Q30185,     # Mayor/Governor
            wd:Q31964827   # Deputy minister
          ))
        }
        LIMIT 10000
        """
        
        try:
            response = self.session.get(
                self.SPARQL_ENDPOINT,
                params={'query': query, 'format': 'json'},
                timeout=60
            )
            
            data = response.json()
            results = data.get('results', {}).get('bindings', [])
            
            logger.info(f"[Wikidata] Found {len(results)} position records")
            
            # Group by person
            persons_dict = {}
            for result in results:
                person_id = result['person']['value']
                
                if person_id not in persons_dict:
                    persons_dict[person_id] = {
                        'source': 'wikidata',
                        'source_id': person_id,
                        'source_url': person_id,
                        'canonical_name_en': result.get('personLabel', {}).get('value'),
                        'canonical_name_ar': result.get('personLabelAr', {}).get('value'),
                        'date_of_birth': self._parse_date(result.get('dob', {}).get('value')),
                        'nationality': 'EG',
                        'positions': [],
                        'raw_data': result
                    }
                
                # Add position
                if 'position' in result:
                    persons_dict[person_id]['positions'].append({
                        'title_en': result.get('positionLabel', {}).get('value'),
                        'start_date': self._parse_date(result.get('startDate', {}).get('value')),
                        'end_date': self._parse_date(result.get('endDate', {}).get('value')),
                        'party': result.get('partyLabel', {}).get('value'),
                        'source': 'wikidata'
                    })
            
            peps = list(persons_dict.values())
            logger.info(f"[Wikidata] Processed {len(peps)} unique persons")
            
            return peps
            
        except Exception as e:
            logger.error(f"[Wikidata] Error: {str(e)}")
            raise
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[str]:
        """Parse Wikidata date format"""
        if not date_str:
            return None
        
        try:
            # Wikidata dates are in format: +1990-01-01T00:00:00Z
            date_str = date_str.replace('+', '').split('T')[0]
            return date_str
        except Exception:
            return None
