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
Sanctions List Format Handlers
===============================

Parsers for different sanctions list formats:
- UN Security Council (XML)
- OFAC - US Treasury (XML)
- HM Treasury UK (CSV)  
- EU Sanctions (XML)
- OpenSanctions (FTJSON) - Enhanced

Each handler converts source format to standardized entity dictionary.
"""

import xml.etree.ElementTree as ET
import csv
import json
import logging
import re
import hashlib
from datetime import datetime
from io import StringIO

logger = logging.getLogger(__name__)


class BaseFormatHandler:
    """Base class for format handlers"""
    
    def __init__(self):
        self.processed_count = 0
        self.error_count = 0
        
    def parse(self, content):
        """
        Parse content and return list of standardized entities.
        Must be implemented by subclasses.
        """
        raise NotImplementedError
        
    def _standardize_entity(self, raw_entity):
        """
        Convert raw entity to standardized format.
        Must be implemented by subclasses.
        """
        raise NotImplementedError
        

class UNSecurityCouncilHandler(BaseFormatHandler):
    """
    Parser for UN Security Council Consolidated List (XML format)
    URL: https://scsanctions.un.org/resources/xml/en/consolidated.xml
    """
    
    def parse(self, content):
        """
        Parse UN XML format.
        
        Structure:
        <CONSOLIDATED_LIST>
          <INDIVIDUALS>
            <INDIVIDUAL> ... </INDIVIDUAL>
          </INDIVIDUALS>
          <ENTITIES>
            <ENTITY> ... </ENTITY>
          </ENTITIES>
        </CONSOLIDATED_LIST>
        """
        entities = []
        try:
            import io
            context = ET.iterparse(io.BytesIO(content.encode('utf-8') if isinstance(content, str) else content), events=('end',))
            
            for event, elem in context:
                if elem.tag == 'INDIVIDUAL':
                    entity = self._parse_individual(elem)
                    if entity:
                        entities.append(entity)
                        self.processed_count += 1
                    elem.clear()
                elif elem.tag == 'ENTITY':
                    entity = self._parse_entity(elem)
                    if entity:
                        entities.append(entity)
                        self.processed_count += 1
                    elem.clear()
                
                if self.processed_count % 500 == 0 and self.processed_count > 0:
                    logger.info(f"UN Parser: Processed {self.processed_count} entities...")
                        
            logger.info(f"UN Parser: Successfully processed {self.processed_count} entities total")
            
        except Exception as e:
            logger.error(f"Failed to parse UN XML: {e}")
            self.error_count += 1
            
        return entities
        
    def _parse_individual(self, individual):
        """Parse UN INDIVIDUAL entry"""
        try:
            # Extract DATAID (unique identifier)
            dataid = individual.find('DATAID')
            source_id = f"UN-{dataid.text}" if dataid is not None else None
            
            if not source_id:
                return None
                
            # Names
            first_name = self._get_text(individual, 'FIRST_NAME')
            second_name = self._get_text(individual, 'SECOND_NAME')
            third_name = self._get_text(individual, 'THIRD_NAME')
            fourth_name = self._get_text(individual, 'FOURTH_NAME')
            
            # Build full name
            name_parts = [first_name, second_name, third_name, fourth_name]
            full_name = ' '.join(p for p in name_parts if p)
            
            if not full_name:
                full_name = self._get_text(individual, 'NAME_ORIGINAL_SCRIPT')
                
            if not full_name:
                return None
                
            # Aliases
            aliases = []
            for alias in individual.findall('.//INDIVIDUAL_ALIAS'):
                alias_name = self._get_text(alias, 'ALIAS_NAME')
                if alias_name and alias_name != full_name:
                    aliases.append(alias_name)
                    
            # Date of Birth
            dob = None
            dob_elem = individual.find('.//INDIVIDUAL_DATE_OF_BIRTH')
            if dob_elem is not None:
                date_str = self._get_text(dob_elem, 'DATE')
                if date_str:
                    dob = self._parse_date(date_str)
                    
            # Nationality
            nationality = self._get_text(individual, 'NATIONALITY/VALUE')
            
            # Designation
            designation = self._get_text(individual, 'DESIGNATION/VALUE')
            
            # Listed On date
            listed_on = self._get_text(individual, 'LISTED_ON')
            
            # Comments/Notes
            comments = self._get_text(individual, 'COMMENTS1')
            
            # Build standardized entity
            entity = {
                'source_id': source_id,
                'full_name': full_name,
                'original_name': self._get_text(individual, 'NAME_ORIGINAL_SCRIPT'),
                'list_type': 'UN_Sanctions',
                'entity_type': 'INDIVIDUAL',
                'dataset': 'UN_Security_Council',
                'source': 'un',
                'source_url': f"https://www.un.org/securitycouncil/sanctions/1267/aq_sanctions_list",
                'risk_level': 'HIGH',
                'topics': ['sanctions', 'un'],
                'countries': [nationality] if nationality else [],
                'date_of_birth': dob,
                'nationality': nationality,
                'aliases': aliases,
                'details': {
                    'designation': designation,
                    'listed_on': listed_on,
                    'comments': comments
                }
            }
            
            return entity
            
        except Exception as e:
            logger.warning(f"Failed to parse UN individual: {e}")
            self.error_count += 1
            return None
            
    def _parse_entity(self, entity_elem):
        """Parse UN ENTITY (organization) entry"""
        try:
            # Extract DATAID
            dataid = entity_elem.find('DATAID')
            source_id = f"UN-{dataid.text}" if dataid is not None else None
            
            if not source_id:
                return None
                
            # Name
            first_name = self._get_text(entity_elem, 'FIRST_NAME')
            full_name = first_name or self._get_text(entity_elem, 'NAME_ORIGINAL_SCRIPT')
            
            if not full_name:
                return None
                
            # Aliases
            aliases = []
            for alias in entity_elem.findall('.//ENTITY_ALIAS'):
                alias_name = self._get_text(alias, 'ALIAS_NAME')
                if alias_name and alias_name != full_name:
                    aliases.append(alias_name)
                    
            # Address
            address = None
            address_elem = entity_elem.find('.//ENTITY_ADDRESS')
            if address_elem is not None:
                address_parts = [
                    self._get_text(address_elem, 'STREET'),
                    self._get_text(address_elem, 'CITY'),
                    self._get_text(address_elem, 'COUNTRY')
                ]
                address = ', '.join(p for p in address_parts if p)
                
            # Listed On
            listed_on = self._get_text(entity_elem, 'LISTED_ON')
            
            # Comments
            comments = self._get_text(entity_elem, 'COMMENTS1')
            
            entity = {
                'source_id': source_id,
                'full_name': full_name,
                'original_name': self._get_text(entity_elem, 'NAME_ORIGINAL_SCRIPT'),
                'list_type': 'UN_Sanctions',
                'entity_type': 'ENTITY',
                'dataset': 'UN_Security_Council',
                'source': 'un',
                'source_url': f"https://www.un.org/securitycouncil/sanctions/1267/aq_sanctions_list",
                'risk_level': 'HIGH',
                'topics': ['sanctions', 'un'],
                'countries': [],
                'aliases': aliases,
                'details': {
                    'address': address,
                    'listed_on': listed_on,
                    'comments': comments
                }
            }
            
            return entity
            
        except Exception as e:
            logger.warning(f"Failed to parse UN entity: {e}")
            self.error_count += 1
            return None
            
    def _get_text(self, element, path):
        """Safely get text from XML element"""
        try:
            elem = element.find(path)
            return elem.text.strip() if elem is not None and elem.text else None
        except:
            return None
            
    def _parse_date(self, date_str):
        """Parse UN date format (YYYY-MM-DD or DD MMM YYYY)"""
        if not date_str:
            return None
            
        for fmt in ['%Y-%m-%d', '%d %b %Y', '%Y']:
            try:
                parsed = datetime.strptime(date_str, fmt)
                return parsed.strftime('%Y-%m-%d')
            except ValueError:
                continue
                
        return date_str  # Return as-is if can't parse


_MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct',
                                          'nov', 'dec'], 1)}


def iso_date(s):
    """'19 Apr 1947' / '12/11/1967' / 'dd/mm/1968' / '1947' / 'Apr 1947' -> '1947-04-19' / '1967-11-12' /
    '1968' / '1947' / '1947-04'. Anything else is returned as written (never invented)."""
    import re as _re
    s = (s or '').strip()
    if not s:
        return None
    m = _re.fullmatch(r'(\d{1,2}) ([A-Za-z]{3})[a-z]* (\d{4})', s)
    if m and m.group(2).lower() in _MONTHS:
        return f'{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}'
    m = _re.fullmatch(r'([A-Za-z]{3})[a-z]* (\d{4})', s)
    if m and m.group(1).lower() in _MONTHS:
        return f'{m.group(2)}-{_MONTHS[m.group(1).lower()]:02d}'
    m = _re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if mo == 0:
            return y
        if d == 0:
            return f'{y}-{mo:02d}'
        try:
            import datetime as _dt
            _dt.date(int(y), mo, d)
            return f'{y}-{mo:02d}-{d:02d}'
        except ValueError:
            return y
    m = _re.fullmatch(r'(?:dd|\d{1,2})/(?:mm|\d{1,2})/(\d{4})', s, _re.I)
    if m:
        return m.group(1)
    m = _re.fullmatch(r'\d{4}(-\d{2}(-\d{2})?)?', s)
    if m:
        return s
    return s


_PASSPORT = ('passport',)
_NATIONAL_ID = ('national id', 'national identification', 'identification number', 'cedula', 'personal id',
                'id card', 'nic', 'tax id', 'curp', 'c.u.r.p', 'personal number', 'citizen')
# OFAC idList types that are not personal identity documents
_NOT_ID = ('country', 'vessel', 'aircraft', 'imo', 'mmsi', 'swift', 'bic', 'website', 'email', 'phone',
           'sanctions risk', 'executive order', 'gender', 'organization established', 'organization type',
           'registration country', 'nationality of registration')


class OFACHandler(BaseFormatHandler):
    """Parser for OFAC SDN List XML format"""

    def parse(self, content):
        entities = []
        try:
            root = ET.fromstring(content)
            # Detect default namespace
            ns = ''
            if root.tag.startswith('{'):
                ns = root.tag.split('}')[0] + '}'

            for sdn_entry in root.findall(f'.//{ns}sdnEntry'):
                try:
                    uid = self._t(sdn_entry, f'{ns}uid')
                    if not uid:
                        continue
                    source_id = f"OFAC-{uid}"

                    first_name = self._t(sdn_entry, f'{ns}firstName')
                    last_name  = self._t(sdn_entry, f'{ns}lastName')
                    full_name  = f"{first_name} {last_name}".strip() if first_name and last_name else (first_name or last_name)
                    if not full_name:
                        continue

                    sdn_type    = self._t(sdn_entry, f'{ns}sdnType')
                    entity_type = 'INDIVIDUAL' if sdn_type == 'Individual' else 'ENTITY'

                    # Programs
                    programs = []
                    pl = sdn_entry.find(f'{ns}programList')
                    if pl is not None:
                        for p in pl.findall(f'{ns}program'):
                            if p.text: programs.append(p.text)

                    # Aliases (OFAC marks each a.k.a. strong or weak)
                    aliases, weak_aliases = [], []
                    al = sdn_entry.find(f'{ns}akaList')
                    if al is not None:
                        for aka in al.findall(f'{ns}aka'):
                            fn = self._t(aka, f'{ns}firstName')
                            ln = self._t(aka, f'{ns}lastName')
                            aka_name = f"{fn} {ln}".strip() if fn and ln else (fn or ln)
                            if aka_name and aka_name != full_name:
                                aliases.append(aka_name)
                                if (self._t(aka, f'{ns}category') or '').lower() == 'weak':
                                    weak_aliases.append(aka_name)

                    def _items(lst, item, field):
                        out, main = [], None
                        le = sdn_entry.find(f'{ns}{lst}')
                        if le is not None:
                            for it in le.findall(f'{ns}{item}'):
                                v = self._t(it, f'{ns}{field}')
                                if v:
                                    out.append(v)
                                    if (self._t(it, f'{ns}mainEntry') or '').lower() == 'true' and main is None:
                                        main = v
                        return out, (main or (out[0] if out else None))
                    dobs, dob_main = _items('dateOfBirthList', 'dateOfBirthItem', 'dateOfBirth')
                    pobs, pob_main = _items('placeOfBirthList', 'placeOfBirthItem', 'placeOfBirth')
                    nats, nat_main = _items('nationalityList', 'nationality', 'country')
                    cits, cit_main = _items('citizenshipList', 'citizenship', 'country')
                    remarks = self._t(sdn_entry, f'{ns}remarks')

                    # Addresses
                    addresses = []
                    adl = sdn_entry.find(f'{ns}addressList')
                    if adl is not None:
                        for addr in adl.findall(f'{ns}address'):
                            parts = [self._t(addr, f'{ns}address1'),
                                     self._t(addr, f'{ns}city'),
                                     self._t(addr, f'{ns}country')]
                            s = ', '.join(p for p in parts if p)
                            if s: addresses.append(s)

                    # IDs
                    ids = []
                    idl = sdn_entry.find(f'{ns}idList')
                    if idl is not None:
                        for id_entry in idl.findall(f'{ns}id'):
                            id_type = self._t(id_entry, f'{ns}idType')
                            id_num  = self._t(id_entry, f'{ns}idNumber')
                            if id_type and id_num:
                                ids.append({'type': id_type, 'number': id_num})

                    gender = next((i['number'] for i in ids if i['type'].lower() == 'gender'), None)
                    passports = [i['number'] for i in ids if any(k in i['type'].lower() for k in _PASSPORT)]
                    national_ids = [i['number'] for i in ids
                                    if any(k in i['type'].lower() for k in _NATIONAL_ID)
                                    and not any(k in i['type'].lower() for k in _PASSPORT + _NOT_ID)]
                    entity = {
                        'source_id':   source_id,
                        'source':      'ofac',
                        'full_name':   full_name,
                        'entity_type': entity_type,
                        'aliases':     aliases,
                        'addresses':   addresses,
                        'ids':         ids,
                        'programs':    programs,
                        'date_of_birth': ';'.join(dict.fromkeys(
                            [d for d in [iso_date(dob_main)] + [iso_date(x) for x in dobs] if d])) or None,
                        'place_of_birth': pob_main,
                        'nationality': nat_main or cit_main,
                        'gender':      gender.lower() if gender else None,
                        'passport_numbers': passports,
                        'national_id_numbers': national_ids,
                        'risk_level':  'HIGH',
                        'source_url':  'https://sanctionslistservice.ofac.treas.gov/api/publicationpreview/exports/sdn.xml',
                        'details':     {'programs': programs, 'sdn_type': sdn_type},
                        'properties':  {'programs': programs, 'remarks': remarks,
                                        'dates_of_birth': [iso_date(d) for d in dobs],
                                        'places_of_birth': pobs, 'nationalities': nats, 'citizenships': cits,
                                        'identifiers': [i for i in ids if i['type'].lower() != 'gender'],
                                        'weak_aliases': weak_aliases},
                        '_rich':       True,
                        'is_active':   True,
                        'last_updated': None,
                    }
                    entities.append(entity)
                    self.processed_count += 1
                except Exception as e:
                    logger.warning(f"Skipped OFAC entry: {e}")
                    continue

            logger.info(f"OFAC Parser: Processed {self.processed_count} entities")
        except Exception as e:
            logger.error(f"Failed to parse OFAC XML: {e}")
            self.error_count += 1
        return entities

    def _t(self, element, tag):
        """Safely get text from an element by tag"""
        try:
            el = element.find(tag)
            return el.text.strip() if el is not None and el.text else None
        except:
            return None

    def _get_text(self, element, path, ns=""):
        return self._t(element, f"{ns}{path}")

    def _standardize_entity(self, raw_entity):
        return raw_entity


class HMTreasuryHandler(BaseFormatHandler):
    """Parser for HM Treasury UK Sanctions List (XML format)"""

    def parse(self, content):
        entities = []
        try:
            if isinstance(content, bytes):
                root = ET.fromstring(content)
            else:
                root = ET.fromstring(content.encode('utf-8'))

            for desig in root.findall('Designation'):
                try:
                    entity = self._parse_designation(desig)
                    if entity:
                        entities.append(entity)
                        self.processed_count += 1
                except Exception as e:
                    logger.warning(f"Skipped HMT entry: {e}")
                    continue

            logger.info(f"HMT Parser: Processed {self.processed_count} entities")
        except Exception as e:
            logger.error(f"Failed to parse HMT XML: {e}")
            self.error_count += 1
        return entities

    def _t(self, element, tag):
        try:
            el = element.find(tag)
            return el.text.strip() if el is not None and el.text else None
        except:
            return None

    def _parse_designation(self, desig):
        unique_id = self._t(desig, 'UniqueID')
        if not unique_id:
            return None

        # Names are nested: Names > Name > Name6
        full_name = None
        aliases = []
        names_el = desig.find('Names')
        if names_el is not None:
            for name_el in names_el.findall('Name'):
                # Name1..Name5 are the given / middle names, Name6 the family name: the full name is all of them
                name_val = ' '.join(p for p in (self._t(name_el, f'Name{k}') for k in range(1, 7)) if p) or None
                name_type = self._t(name_el, 'NameType') or ''
                if not name_val:
                    continue
                if 'primary' in name_type.lower():
                    full_name = name_val
                else:
                    aliases.append(name_val)

        if not full_name:
            # fallback: use first name found
            if aliases:
                full_name = aliases.pop(0)
            else:
                return None

        # Entity type
        ind_entity = self._t(desig, 'IndividualEntityShip') or ''
        entity_type = 'INDIVIDUAL' if ind_entity.lower() == 'individual' else 'ENTITY'

        # Addresses
        addresses = []
        addr_el = desig.find('Addresses')
        if addr_el is not None:
            for addr in addr_el.findall('Address'):
                parts = [
                    self._t(addr, 'AddressLine1'),
                    self._t(addr, 'AddressLine2'),
                    self._t(addr, 'AddressLine3'),
                    self._t(addr, 'AddressLine4'),
                    self._t(addr, 'AddressLine5'),
                    self._t(addr, 'AddressLine6'),
                    self._t(addr, 'PostCode'),
                    self._t(addr, 'Country'),
                ]
                s = ', '.join(p for p in parts if p)
                if s:
                    addresses.append(s)

        regime = self._t(desig, 'RegimeName') or ''

        def texts(path):
            return [e.text.strip() for e in desig.findall(path) if e is not None and e.text and e.text.strip()]

        weak = []
        if names_el is not None:
            for name_el in names_el.findall('Name'):
                nm = ' '.join(p for p in (self._t(name_el, f'Name{k}') for k in range(1, 7)) if p)
                if 'low' in (self._t(name_el, 'AliasStrength') or '').lower() and nm:
                    weak.append(nm)
        non_latin = texts('NonLatinNames/NonLatinName/NameNonLatinScript')
        arabic = [n for n in non_latin if any('\u0600' <= ch <= '\u06ff' for ch in n)]
        dobs = texts('IndividualDetails/Individual/DOBs/DOB')
        pobs = []
        for loc in desig.findall('IndividualDetails/Individual/BirthDetails/Location'):
            p = ', '.join(x for x in (self._t(loc, 'TownOfBirth'), self._t(loc, 'CountryOfBirth')) if x)
            if p and p not in pobs:
                pobs.append(p)
        nats = texts('IndividualDetails/Individual/Nationalities/Nationality')
        passports = texts('IndividualDetails/Individual/PassportDetails/Passport/PassportNumber')
        nids = [e.text.strip() for e in desig.iter() if e.tag.endswith('NationalIdentifierNumber') and e.text and e.text.strip()]
        genders = [e.text.strip() for e in desig.iter() if e.tag == 'Gender' and e.text and e.text.strip()]
        positions = texts('IndividualDetails/Individual/Positions/Position')
        dob_main = next((iso_date(d) for d in dobs if iso_date(d) and len(iso_date(d)) == 10), None) or \
            (iso_date(dobs[0]) if dobs else None)
        return {
            'source_id':     f"HMT-{unique_id}",
            'source':        'hmt',
            'full_name':     full_name,
            'full_name_arabic': arabic[0] if arabic else None,
            'aliases_arabic': arabic[1:],
            'entity_type':   entity_type,
            'aliases':       aliases,
            'addresses':     addresses,
            'date_of_birth': ';'.join(dict.fromkeys([d for d in [dob_main] + [iso_date(x) for x in dobs] if d])) or None,
            'place_of_birth': pobs[0] if pobs else None,
            'nationality':   nats[0] if nats else None,
            'gender':        genders[0].lower() if genders else None,
            'passport_numbers': passports,
            'national_id_numbers': nids,
            'first_seen':    iso_date(self._t(desig, 'DateDesignated')),
            'risk_level':    'HIGH',
            'source_url':    'https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml',
            'details':       {'regime': regime, 'date_designated': self._t(desig, 'DateDesignated')},
            'properties':    {'regime': regime, 'date_designated': iso_date(self._t(desig, 'DateDesignated')),
                              'un_reference': self._t(desig, 'UNReferenceNumber'),
                              'designation_source': self._t(desig, 'DesignationSource'),
                              'sanctions_imposed': self._t(desig, 'SanctionsImposed'),
                              'other_information': self._t(desig, 'OtherInformation'),
                              'statement_of_reasons': self._t(desig, 'UKStatementofReasons'),
                              'titles': texts('Titles/Title'), 'positions': positions,
                              'dates_of_birth': [iso_date(d) for d in dobs], 'places_of_birth': pobs,
                              'nationalities': nats, 'weak_aliases': weak, 'non_latin_names': non_latin},
            '_rich':         True,
            'is_active':     True,
            'last_updated':  self._t(desig, 'LastUpdated'),
        }

    def _standardize_entity(self, raw_entity):
        return raw_entity


class EUSanctionsHandler(BaseFormatHandler):
    """
    Parser for EU Consolidated Sanctions List (XML format)
    URL: https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content
    """
    
    def parse(self, content):
        """
        Parse EU XML format.
        
        Structure is complex with nested entities and multilingual names.
        """
        entities = []
        
        try:
            root = ET.fromstring(content)
            
            # Parse sanctionEntity elements
            for sanction_entity in root.findall('.//{http://eu.europa.ec/fpi/fsd/export}sanctionEntity'):
                entity = self._parse_sanction_entity(sanction_entity)
                if entity:
                    entities.append(entity)
                    self.processed_count += 1
                    
            logger.info(f"EU Parser: Processed {self.processed_count} entities")
            
        except Exception as e:
            logger.error(f"Failed to parse EU XML: {e}")
            self.error_count += 1
            
        return entities
        
    def _parse_sanction_entity(self, entity_elem):
        """Parse one EU sanctionEntity.

        The EU file carries names, subject type, birth dates and documents as
        ATTRIBUTES (<nameAlias wholeName="..." nameLanguage="AR"/>,
        <subjectType code="person"/>). The earlier version read them as child
        elements, found no name on any record and returned 0 entities, so the
        EU list silently stopped updating.
        """
        try:
            ns = {'fsd': 'http://eu.europa.ec/fpi/fsd/export'}
            ref = entity_elem.get('euReferenceNumber') or entity_elem.get('logicalId')
            if not ref:
                return None
            source_id = f"EU-{ref}"

            st = entity_elem.find('fsd:subjectType', ns)
            code = (st.get('code') if st is not None else '') or ''
            entity_type = 'INDIVIDUAL' if code == 'person' else 'ENTITY'

            arabic, names, primary = None, [], []
            for na in entity_elem.findall('fsd:nameAlias', ns):
                name = (na.get('wholeName') or ' '.join(
                    x for x in (na.get('firstName'), na.get('middleName'), na.get('lastName')) if x)).strip()
                if not name:
                    continue
                lang = (na.get('nameLanguage') or '').upper()
                if lang == 'AR' and not arabic:
                    arabic = name
                names.append(name)
                if lang in ('', 'EN') and na.get('strong', 'true') == 'true':
                    primary.append(name)
            # the fullest strong Latin name is the listed name; the rest are aliases
            full_name = max(primary or names, key=len) if (primary or names) else None
            if not full_name:
                return None
            aliases = [n for n in names if n != full_name]

            dob = None
            for bd in entity_elem.findall('fsd:birthdate', ns):
                d = bd.get('birthdate') or (bd.get('year') and f"{bd.get('year')}")
                if d:
                    dob = self._parse_date(d) if len(d) > 4 else d
                    break

            nationality, countries = None, []
            for c in entity_elem.findall('fsd:citizenship', ns):
                desc = c.get('countryDescription') or c.get('countryIso2Code')
                if desc and desc not in countries:
                    countries.append(desc)
            if countries:
                nationality = countries[0]

            ids = []
            for idn in entity_elem.findall('fsd:identification', ns):
                num = idn.get('number')
                if num:
                    ids.append(f"{idn.get('identificationTypeDescription') or idn.get('identificationTypeCode') or 'ID'}: {num}")

            programmes, regulation_summary = [], None
            for reg in entity_elem.findall('fsd:regulation', ns):
                if reg.get('programme') and reg.get('programme') not in programmes:
                    programmes.append(reg.get('programme'))
                regulation_summary = regulation_summary or reg.get('numberTitle')
            remark = self._get_text(entity_elem, 'fsd:remark', ns)

            address = None
            address_elem = entity_elem.find('fsd:address', ns)
            if address_elem is not None:
                address = ', '.join(x for x in (address_elem.get('street'), address_elem.get('city'),
                                                address_elem.get('countryDescription')) if x) or None

            return {
                'source_id': source_id,
                'full_name': full_name,
                'original_name': arabic,
                'list_type': 'SANCTIONS',
                'entity_type': entity_type,
                'dataset': 'eu_fsf',
                'source': 'eu',
                'source_url': 'https://webgate.ec.europa.eu/fsd/fsf#!/search',
                'risk_level': 'HIGH',
                'topics': ['sanctions', 'eu'] + [p.lower() for p in programmes],
                'countries': countries,
                'date_of_birth': dob,
                'nationality': nationality,
                'aliases': list(dict.fromkeys(a for a in aliases if a != full_name)),
                'details': {
                    'program': ', '.join(programmes) or None,
                    'regulation': regulation_summary,
                    'reason': remark,
                    'identifiers': ids or None,
                    'address': address,
                    'designation_date': entity_elem.get('designationDate'),
                    'un_reference': entity_elem.get('unitedNationId') or None,
                }
            }
        except Exception as e:
            logger.warning(f"Failed to parse EU entity: {e}")
            self.error_count += 1
            return None

    def _get_text(self, element, path, ns):
        """Safely get text from XML element with namespace"""
        try:
            elem = element.find(path, ns)
            return elem.text.strip() if elem is not None and elem.text else None
        except:
            return None
            
    def _parse_date(self, date_str):
        """Parse EU date format"""
        if not date_str:
            return None
            
        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%Y']:
            try:
                parsed = datetime.strptime(date_str, fmt)
                return parsed.strftime('%Y-%m-%d')
            except ValueError:
                continue
                
        return date_str


class OpenSanctionsHandler(BaseFormatHandler):
    """
    Enhanced parser for OpenSanctions FTJSON format
    URL: https://data.opensanctions.org/datasets/latest/default/entities.ftm.json
    """
    
    def parse(self, content):
        """
        Parse FTJSON format (JSON Lines - one entity per line)
        """
        entities = []
        
        try:
            lines = content.strip().split('\n')
            
            for line in lines:
                if not line.strip():
                    continue
                    
                try:
                    entity = self._parse_line(line)
                    if entity:
                        entities.append(entity)
                        self.processed_count += 1
                except Exception as e:
                    logger.warning(f"Failed to parse FTJSON line: {e}")
                    self.error_count += 1
                    continue
                    
            logger.info(f"OpenSanctions Parser: Processed {self.processed_count} entities")
            
        except Exception as e:
            logger.error(f"Failed to parse OpenSanctions FTJSON: {e}")
            self.error_count += 1
            
        return entities
        
    def _parse_line(self, line):
        """Parse single FTJSON line"""
        data = json.loads(line)
        
        # Filter by schema (only relevant entity types)
        schema = data.get('schema')
        if schema not in ['Person', 'Organization', 'Company', 'LegalEntity']:
            return None
            
        props = data.get('properties', {})
        
        # Names
        names = props.get('name', []) + props.get('alias', [])
        if not names:
            return None
            
        full_name = names[0]
        aliases = names[1:] if len(names) > 1 else []
        
        # Entity Type
        entity_type = 'INDIVIDUAL' if schema == 'Person' else 'ENTITY'
        
        # Countries
        countries = props.get('country', [])
        
        # Topics
        topics = props.get('topics', [])
        
        # Date of Birth
        dob = (props.get('birthDate') or [None])[0]
        
        # Nationality
        nationality = (props.get('nationality') or [None])[0]
        
        # Datasets (source within OpenSanctions)
        datasets = data.get('datasets', [])
        dataset = datasets[0] if datasets else 'OpenSanctions'
        from screening.list_category import categorize as _list_category
        
        # Source URL
        source_url = (data.get('referents') or [None])[0]
        if not source_url:
            source_url = f"https://www.opensanctions.org/entities/{data.get('id')}/"
            
        entity = {
            'source_id': f"OS-{data.get('id')}",
            'full_name': full_name,
            'original_name': None,
            'list_type': _list_category(topics, datasets or dataset),
            'entity_type': entity_type,
            'dataset': dataset,
            'source': 'opensanctions',
            'source_url': source_url,
            'risk_level': 'HIGH' if any(t in topics for t in ['sanction', 'crime']) else 'MEDIUM',
            'topics': topics,
            'countries': countries,
            'date_of_birth': dob,
            'nationality': nationality,
            'aliases': aliases,
            'details': props.get('notes', {})
        }
        
        return entity


# Factory function to get appropriate handler
def get_format_handler(source_type):
    """
    Get appropriate format handler for source type.
    
    Args:
        source_type: One of: UN, OFAC, HMT, EU, OPENSANCTIONS, EMLCU
        
    Returns:
        Handler instance
    """
    handlers = {
        'UN': UNSecurityCouncilHandler,
        'OFAC': OFACHandler,
        'HMT': HMTreasuryHandler,
        'EU': EUSanctionsHandler,
        'OPENSANCTIONS': OpenSanctionsHandler,
    }
    
    handler_class = handlers.get(source_type)
    if not handler_class:
        raise ValueError(f"Unknown source type: {source_type}")
        
    return handler_class()
