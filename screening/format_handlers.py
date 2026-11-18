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
import zlib
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
                    'comments': comments,
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

            # Ships (V1): the UN lists ships as ENTITY records (e.g. 2146 Libya designations) with the IMO
            # number and the flag state in the comments; a shipping company's own IMO company number is
            # told apart by the ship check digit and the company-like name (format_handlers.ship_from_text)
            entity_type, vessel = 'ENTITY', None
            imos = ship_from_text(full_name, comments)
            if imos is not None:
                entity_type = 'VESSEL'
                fm = re.search(r'Flag(?: State)?\s*:\s*([A-Za-z ,.\'()-]+?)(?:\.|;|$)', comments or '', re.M)
                tm = re.search(r'Type of (?:ship|vessel)\s*:\s*([^.;\n]+)', comments or '', re.I)
                vessel = vessel_block(imos=imos, flag=fm.group(1).strip() if fm else None,
                                      vtype=tm.group(1).strip() if tm else None,
                                      measures=vessel_measures(comments) or ['asset_freeze'])

            entity = {
                'source_id': source_id,
                'full_name': full_name,
                'original_name': self._get_text(entity_elem, 'NAME_ORIGINAL_SCRIPT'),
                'list_type': 'UN_Sanctions',
                'entity_type': entity_type,
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
                    'comments': comments,
                    **({'vessel': vessel} if vessel else {}),
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


# ---- vessels (V1): every handler that lists ships puts them in properties.vessel / details.vessel
# with this shape; screening/vessel_store.py materialises it for the vessel engine.
#   {'imo': str|None, 'imos': [..], 'mmsi': [..], 'call_sign': [..], 'type': str, 'flag': str,
#    'flags_past': [..], 'names_past': [..], 'gross_tonnage': str, 'year_built': str,
#    'owners': [{'name': str, 'role': str, 'ref': source_id|None}], 'measures': [..],
#    'bad_identifiers': [..]  (IMO / MMSI values that are not 7 / 9 digits, kept for the record)}
_VESSEL_MEASURES = (('asset freeze', 'asset_freeze'), ('port entry', 'port_ban'), ('port ban', 'port_ban'),
                    ('enter ports', 'port_ban'), ('de-flag', 'deflag'), ('deflag', 'deflag'),
                    ('charter', 'chartering_ban'), ('shipping sanction', 'shipping_sanctions'),
                    ('specified ship', 'shipping_sanctions'), ('trade sanction', 'trade_sanctions'),
                    ('services', 'services_ban'), ('bunkering', 'services_ban'), ('blocked', 'asset_freeze'),
                    ('prohibition to load', 'port_ban'))

# names that are companies, not ships (lists record a company's own "IMO number" - the IMO company
# number, 7 digits without the ship check digit - so an IMO alone does not make a record a ship)
_COMPANY_WORDS = re.compile(
    r"\b(SHIPPING|SHIPMANAGEMENT|SHIP ?MANAGEMENT|MANAGEMENT|CO|CORP|CORPORATION|COMPANY|LTD|LIMITED|LLC|"
    r"L\.L\.C|INC|PTE|JSC|PJSC|OJSC|SPC|FZCO|FZE|FZ|GMBH|HOLDING|HOLDINGS|SERVICES|TRADING|GROUP|JV|"
    r"MARITIME|NAVIGATION|LOGISTICS|FREIGHT|ENTERPRISE|INVESTMENT|BANK|AGENCY|OOO|S\.A\.|S\.A\.R\.L|B\.V)\b",
    re.I)
_IMO_IN_TEXT = re.compile(r'\bIMO(?:\s*(?:\(IMO\)\s*)?(?:number|no\.?|nr\.?|#)?)?\s*[:.]?\s*(\d{7})\b', re.I)
_SHIP_WORDS = re.compile(r'\b(flag state|the vessel|this vessel|vessel was|type of ship|ship type|oil tanker|'
                         r'tanker|bulk carrier|cargo ship|general cargo|container ship)\b', re.I)


def _imo_check(d):
    return len(d) == 7 and d.isdigit() and sum(int(d[i]) * (7 - i) for i in range(6)) % 10 == int(d[6])


def looks_like_company(name):
    return bool(_COMPANY_WORDS.search(str(name or '')))


def ship_from_text(name, text, imos=()):
    """Decide whether a list ENTITY record (UN / EU, which have no 'ship' subject type) is a ship.
    A ship needs a ship IMO number (check digit valid) or a 'Type of ship' remark, and a name that is not a
    company's. Returns the IMO numbers found, or None when the record is not a ship."""
    text = str(text or '')
    found = [m.group(1) for m in _IMO_IN_TEXT.finditer(text)] + [re.sub(r'\D', '', str(i)) for i in imos or ()]
    found = [d for d in dict.fromkeys(found) if len(d) == 7]
    if looks_like_company(name):
        return None
    if any(_imo_check(d) for d in found) or re.search(r'type of ship', text, re.I):
        if found or _SHIP_WORDS.search(text):
            return found
    return None


def vessel_measures(*texts):
    """Measures named in free text ('Asset freeze|Prohibition of port entry' -> ['asset_freeze', 'port_ban'])."""
    out = []
    blob = ' '.join(str(t or '') for t in texts).lower()
    for needle, code in _VESSEL_MEASURES:
        if needle in blob and code not in out:
            out.append(code)
    return out


def _vessel_digits(v):
    return re.sub(r'\D', '', str(v or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')))


def _vessel_flag(v):
    if not v or not str(v).strip():
        return None
    try:
        from screening.vessel_flags import canonical
        return canonical(v)
    except Exception:
        return str(v).strip()


def vessel_block(imos=(), mmsi=(), call_sign=(), vtype=None, flag=None, flags_past=(), names_past=(),
                 gross_tonnage=None, year_built=None, owners=(), measures=()):
    raw_imos = [x for x in imos if x and str(x).strip()]
    d_imos = [_vessel_digits(x) for x in raw_imos]
    good = [d for d in dict.fromkeys(d_imos) if len(d) == 7]
    # the check digit decides which IMO is the ship's own: a valid one first (an invalid one is kept and
    # flagged by the vessel tables, never dropped)
    good.sort(key=lambda d: 0 if _imo_check(d) else 1)
    raw_mmsi = [x for x in mmsi if x and str(x).strip()]
    good_mmsi = [d for d in dict.fromkeys(_vessel_digits(x) for x in raw_mmsi) if len(d) == 9]
    bad = [str(x).strip() for x, d in zip(raw_imos, d_imos) if len(d) != 7]
    bad += [str(x).strip() for x in raw_mmsi if len(_vessel_digits(x)) != 9]
    flag_c = _vessel_flag(flag)
    past = [f for f in dict.fromkeys(_vessel_flag(x) for x in flags_past if x and str(x).strip()) if f and f != flag_c]
    yb = str(year_built).strip() if year_built else ''
    m = re.search(r'\b(1[89]\d\d|20\d\d)\b', yb)
    seen_o, own = set(), []
    for o in owners:
        if not (o.get('name') or o.get('ref')):
            continue
        k = (str(o.get('name') or '').strip().upper(), o.get('ref'), o.get('role'))
        if k not in seen_o:
            seen_o.add(k)
            own.append(o)
    return {
        'imo': good[0] if good else None, 'imos': good,
        'mmsi': good_mmsi,
        'call_sign': [c for c in dict.fromkeys(str(x).strip().upper() for x in call_sign if x and str(x).strip())],
        'type': (str(vtype).strip() if vtype and str(vtype).strip() else None), 'flag': flag_c,
        'flags_past': past,
        'names_past': [n for n in dict.fromkeys(str(x).strip() for x in names_past if x and str(x).strip())],
        'gross_tonnage': (str(gross_tonnage).strip() or None) if gross_tonnage else None,
        'year_built': (m.group(1) if m else (yb[:10] or None)),
        'owners': own,
        'measures': list(dict.fromkeys(measures)),
        **({'bad_identifiers': bad} if bad else {}),
    }


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
                    entity_type = 'INDIVIDUAL' if sdn_type == 'Individual' else (
                        'VESSEL' if sdn_type == 'Vessel' else 'ENTITY')

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

                    vessel = self._vessel(sdn_entry, ns, ids, remarks, programs) if sdn_type == 'Vessel' else None
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
                                        'weak_aliases': weak_aliases,
                                        **({'vessel': vessel} if vessel else {})},
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

    def _vessel(self, sdn_entry, ns, ids, remarks, programs):
        """The ship data of an OFAC 'Vessel' entry: vesselInfo + the vessel identifiers of idList, the
        f.k.a. names (former names of the ship), the '(Linked To: ...)' parties of the remarks."""
        vi = sdn_entry.find(f'{ns}vesselInfo')
        g = (lambda tag: self._t(vi, f'{ns}{tag}')) if vi is not None else (lambda tag: None)

        def idv(*types):
            return [i['number'] for i in ids if i['type'].strip().lower() in types]
        former = []
        al = sdn_entry.find(f'{ns}akaList')
        if al is not None:
            for aka in al.findall(f'{ns}aka'):
                if (self._t(aka, f'{ns}type') or '').lower().startswith('f.k.a'):
                    fn, ln = self._t(aka, f'{ns}firstName'), self._t(aka, f'{ns}lastName')
                    n = f"{fn} {ln}".strip() if fn and ln else (fn or ln)
                    if n:
                        former.append(n)
        owners = []
        if g('vesselOwner'):
            owners.append({'name': g('vesselOwner'), 'role': 'owner', 'ref': None})
        for m in re.finditer(r'Linked To:\s*([^)]+)\)', remarks or ''):
            for part in m.group(1).split(';'):
                if part.strip():
                    owners.append({'name': part.strip().rstrip('.'), 'role': 'linked', 'ref': None})
        return vessel_block(
            imos=idv('vessel registration identification'), mmsi=idv('mmsi'),
            call_sign=[g('callSign')] + idv('other vessel call sign'),
            vtype=g('vesselType') or (idv('other vessel type') or [None])[0],
            flag=g('vesselFlag'), flags_past=idv('former vessel flag') + idv('other vessel flag'),
            names_past=former,
            gross_tonnage=g('grossRegisteredTonnage') or g('tonnage'),
            year_built=(idv('vessel year of build') or [None])[0], owners=owners,
            measures=['asset_freeze'])

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
        entity_type = 'INDIVIDUAL' if ind_entity.lower() == 'individual' else (
            'VESSEL' if ind_entity.lower() == 'ship' else 'ENTITY')

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
        vessel = None
        if entity_type == 'VESSEL':
            ship = desig.find('ShipDetails/Ship')
            if ship is None:
                ship = desig.find('ShipDetails')
            tx = (lambda path: texts(f'ShipDetails/Ship/{path}')) if ship is not None else (lambda path: [])
            vessel = vessel_block(
                imos=tx('IMONumbers/IMONumber'), mmsi=tx('MMSINumbers/MMSINumber'),
                call_sign=tx('CallSigns/CallSign'), vtype=(tx('TypeOfShipDetails/TypeOfShip') or [None])[0],
                flag=(tx('CurrentBelievedFlagOfShips/CurrentBelievedFlagOfShip') or [None])[0],
                flags_past=tx('PreviousFlags/PreviousFlag'), names_past=[],
                gross_tonnage=(tx('TonnageOfShipDetails/TonnageOfShip') or [None])[0],
                year_built=(tx('YearsBuilt/YearBuilt') or [None])[0],
                owners=[{'name': n, 'role': 'owner_operator', 'ref': None}
                        for n in tx('CurrentOwnerOperators/CurrentOwnerOperator')] +
                       [{'name': n, 'role': 'former_owner_operator', 'ref': None}
                        for n in tx('PreviousOwnerOperators/PreviousOwnerOperator')],
                measures=self._uk_measures(desig))
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
                              'nationalities': nats, 'weak_aliases': weak, 'non_latin_names': non_latin,
                              **({'vessel': vessel} if vessel else {})},
            '_rich':         True,
            'is_active':     True,
            'last_updated':  self._t(desig, 'LastUpdated'),
        }

    _UK_INDICATORS = (('AssetFreeze', 'asset_freeze'), ('ProhibitionOfPortEntry', 'port_ban'),
                      ('Deflag', 'deflag'), ('CharteringOfShips', 'chartering_ban'),
                      ('PreventionOfCharteringOfShips', 'chartering_ban'),
                      ('PreventionOfCharteringOfShipsAndAircraft', 'chartering_ban'),
                      ('CrewServicingOfShipsAndAircraft', 'services_ban'))

    def _uk_measures(self, desig):
        """Measures of a UK-listed ship: the SanctionsImposedIndicators flags, else the free text."""
        out = []
        ind = desig.find('SanctionsImposedIndicators')
        if ind is not None:
            for tag, code in self._UK_INDICATORS:
                if (self._t(ind, tag) or '').strip().lower() == 'true' and code not in out:
                    out.append(code)
        for c in vessel_measures(self._t(desig, 'SanctionsImposed')):
            if c not in out:
                out.append(c)
        return out or ['shipping_sanctions']

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

            # Ships (V1): the EU file has no ship subject type, and its "IMO (vessel identification)"
            # is mostly a shipping company's IMO company number; ship_from_text tells the two apart.
            vessel = None
            remarks_all = ' '.join(r.text or '' for r in entity_elem.iter('{http://eu.europa.ec/fpi/fsd/export}remark'))
            imo_ids = [idn.get('number') for idn in entity_elem.findall('fsd:identification', ns)
                       if idn.get('number') and (idn.get('identificationTypeCode') or '').lower() == 'imo']
            if entity_type == 'ENTITY':
                imos = ship_from_text(full_name, remarks_all, imo_ids)
                if imos is not None:
                    entity_type = 'VESSEL'
                    tm = re.search(r'Type of ship\s*:\s*([^\n]+)', remarks_all, re.I)
                    om = re.search(r'Owner\s*:\s*([^\n]+)', remarks_all)
                    fm = re.search(r'Flag(?: State)?\s*:\s*([^\n.;]+)', remarks_all, re.I)
                    vessel = vessel_block(imos=imos, vtype=tm.group(1).strip() if tm else None,
                                          flag=fm.group(1).strip() if fm else None,
                                          owners=[{'name': om.group(1).strip(), 'role': 'owner', 'ref': None}] if om else [],
                                          measures=['asset_freeze'])

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
                    **({'vessel': vessel} if vessel else {}),
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


def expand_rich(entity):
    """OpenSanctions keeps its profile fields in one compact JSON string (entity['_os_rich']):
    ~2.2M records are held in memory during an update, and separate keys / lists would roughly
    double their size. Returns the entity with those fields as normal keys (a new dict), or the
    entity itself when it has none. Used wherever the fields are read (hash, store, backfill)."""
    blob = entity.get('_os_rich') if isinstance(entity, dict) else None
    if not blob:
        return entity
    out = dict(entity)
    out.pop('_os_rich', None)
    out.update(json.loads(zlib.decompress(blob).decode('utf-8')))
    return out


def _pack_rich(d):
    """Profile fields -> compressed JSON bytes (key order fixed by the caller)."""
    return zlib.compress(json.dumps(d, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), 6)


# OpenSanctions identifier properties kept in properties.identifiers (type label, FtM property).
# passportNumber / idNumber also fill passport_numbers / national_id_numbers.
_OS_ID_PROPS = (
    ('idNumber', 'ID number'), ('passportNumber', 'Passport'), ('taxNumber', 'Tax number'),
    ('innCode', 'INN'), ('registrationNumber', 'Registration number'), ('leiCode', 'LEI'),
    ('ogrnCode', 'OGRN'), ('swiftBic', 'SWIFT/BIC'), ('imoNumber', 'IMO'),
    ('uniqueEntityId', 'UEI'), ('permId', 'PermID'), ('vatCode', 'VAT'),
)


def _os_clean(v):
    """One spelling of a value for comparison: str, inner whitespace collapsed."""
    return ' '.join(str(v).split()) if v is not None else ''


# Datasets preferred for the `dataset` column (the list a hit is shown under) when an entity is on
# several; otherwise the alphabetically first. OpenSanctions does not keep the order of an entity's
# datasets from one export to the next, so "the first one" changed daily and rewrote the row.
_OS_DATASET_PRIORITY = ('un_sc_sanctions', 'us_ofac_sdn', 'eu_fsf', 'gb_hmt_sanctions', 'gb_fcdo_sanctions',
                        'ch_seco_sanctions', 'us_ofac_cons')


def _os_pick_dataset(datasets):
    if not datasets:
        return 'OpenSanctions'
    for d in _OS_DATASET_PRIORITY:
        if d in datasets:
            return d
    return sorted(datasets)[0]


def _os_pick_referent(referents):
    """The referent kept as source_url: an OFAC SDN uid first (build_entity_links.py links on it),
    then the alphabetically first, so it does not change with OpenSanctions' order."""
    refs = sorted(str(r) for r in (referents or []) if r)
    for r in refs:
        if re.match(r'^ofac-[0-9]+$', r):
            return r
    return refs[0] if refs else None


class OpenSanctionsHandler(BaseFormatHandler):
    """
    Enhanced parser for OpenSanctions FTJSON format
    URL: https://data.opensanctions.org/datasets/latest/default/entities.ftm.json

    rich=False (default): the record exactly as before the profile fields (first date of birth,
    `nationality` only, no gender / identifiers). rich=True: profile fields too, used once
    screening_config 'opensanctions_rich' is on (see scripts/backfill_opensanctions_rich.py).
    """

    def __init__(self, rich=False):
        super().__init__()
        self.rich = bool(rich)
        # ship ownership (V1): FtM keeps owners in separate Ownership / UnknownLink records;
        # {entity id: [(other entity id, role)]}, attached to the ships by attach_vessel_links()
        self.vessel_links = {}

    _OS_LINK_ROLES = {'owned or controlled by': 'owner', 'owns, controls, or operates': 'owner',
                      'property in the interest of': 'beneficial_interest', '': 'owner'}

    def _collect_link(self, data):
        p = data.get('properties') or {}
        role_txt = ((p.get('role') or [''])[0] or '').strip().lower()
        if data.get('schema') == 'Ownership':
            role = self._OS_LINK_ROLES.get(role_txt, 'linked')
            for a in p.get('asset') or []:
                for o in p.get('owner') or []:
                    self.vessel_links.setdefault(a, []).append((o, role))
        else:       # UnknownLink: direction unknown - kept both ways, only ships are read
            for a in p.get('subject') or []:
                for o in p.get('object') or []:
                    self.vessel_links.setdefault(a, []).append((o, 'linked'))
                    self.vessel_links.setdefault(o, []).append((a, 'linked'))

    def attach_vessel_links(self, entities):
        """Add the owners / linked parties collected from Ownership / UnknownLink records to the ships'
        properties.vessel.owners (ref = the party's source_id, resolved to its row by vessel_store)."""
        n = 0
        for e in entities:
            if e.get('entity_type') != 'VESSEL':
                continue
            links = self.vessel_links.get(str(e.get('source_id') or '')[3:])
            if not links:
                continue
            full = expand_rich(e)
            props = dict(full.get('properties') or {})
            v = dict(props.get('vessel') or {})
            have = {(o.get('ref'), o.get('role')) for o in v.get('owners') or []}
            add = [{'name': None, 'role': r, 'ref': f'OS-{o}'} for o, r in sorted(set(links))
                   if (f'OS-{o}', r) not in have]
            if not add:
                continue
            v['owners'] = list(v.get('owners') or []) + add
            props['vessel'] = v
            if '_os_rich' in e:
                rich = json.loads(zlib.decompress(e['_os_rich']).decode('utf-8'))
                rich['properties'] = props
                e['_os_rich'] = _pack_rich(rich)
            else:
                e['properties'] = props
            n += 1
        return n
    
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
                    
            self.attach_vessel_links(entities)
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
        if schema in ('Ownership', 'UnknownLink'):
            self._collect_link(data)
            return None
        if schema not in ['Person', 'Organization', 'Company', 'LegalEntity', 'Vessel']:
            return None
            
        props = data.get('properties', {})
        
        # Names
        names = props.get('name', []) + props.get('alias', [])
        if not names:
            return None
            
        full_name = names[0]
        aliases = names[1:] if len(names) > 1 else []
        
        # Entity Type
        entity_type = 'INDIVIDUAL' if schema == 'Person' else ('VESSEL' if schema == 'Vessel' else 'ENTITY')
        
        # Countries
        countries = props.get('country', [])
        
        # Topics
        topics = props.get('topics', [])
        
        # ships always get the profile record: IMO / MMSI / flags live there (a few thousand rows)
        if not self.rich and schema != 'Vessel':
            return self._legacy_entity(data, props, full_name, aliases, entity_type, countries, topics)

        # ---- deterministic record (P2 churn fix): OpenSanctions re-orders an entity's names, aliases,
        # datasets, topics and referents between exports. The legacy record took "the first name" as
        # full_name, so ~1/3 of the rows were rewritten every day with nothing changed. The rich record
        # uses the entity's caption (its display name) and sorted values, so the same entity in two
        # exports gives the same record and only real changes are written.
        uniq = sorted({_os_clean(n) for n in names if _os_clean(n)})
        full_name = _os_clean(data.get('caption')) or (uniq[0] if uniq else '')
        if not full_name:
            return None
        aliases = [n for n in uniq if n != full_name]
        countries = sorted({_os_clean(c) for c in countries if _os_clean(c)})
        topics = sorted({_os_clean(t) for t in topics if _os_clean(t)})

        # ---- profile fields (P2-2 for OpenSanctions): every date of birth, place of birth,
        # nationality / citizenship, gender, identifiers, addresses and all datasets, stored the
        # way the OFAC / UK loaders store them so DOB / ID scoring and the match profile use them.
        def _vals(key, cap=20, size=300):
            # sorted and de-duplicated before the cap: the same values in any order give the same list
            out = sorted({_os_clean(v)[:size] for v in (props.get(key) or []) if _os_clean(v)})
            return out[:cap]

        dobs = _vals('birthDate')
        dob = ';'.join(dobs) or None
        pobs = _vals('birthPlace', 5)
        nats = _vals('nationality', 10)
        cits = _vals('citizenship', 10)
        nationality = (nats or cits or [None])[0]
        genders = _vals('gender', 2)
        gender = genders[0].lower() if genders else None
        passports = _vals('passportNumber', 10, 60)
        # idNumber is a generic "ID number" from any country (national ID, register, tax ...):
        # it is kept in properties.identifiers, NOT in national_id_numbers, which the engine
        # treats as national IDs (an equal number there can confirm a hit)
        identifiers = []
        for key, label in _OS_ID_PROPS:
            for v in _vals(key, 10, 60):
                identifiers.append({'type': label, 'number': v})
        addresses = _vals('address', 10)
        positions = _vals('position', 10, 200)

        # Datasets (source within OpenSanctions): the first one stays in `dataset` (the category
        # and the display read it); the full list goes into properties.datasets.
        datasets = sorted({str(d) for d in (data.get('datasets') or []) if d})
        dataset = _os_pick_dataset(datasets)
        from screening.list_category import categorize as _list_category

        # Source URL
        source_url = _os_pick_referent(data.get('referents'))
        if not source_url:
            source_url = f"https://www.opensanctions.org/entities/{data.get('id')}/"

        first_seen = str(data.get('first_seen') or '').strip()[:19].replace(' ', 'T') or None

        properties = {k: v for k, v in (
            ('datasets', datasets),
            ('dates_of_birth', dobs),
            ('places_of_birth', pobs),
            ('nationalities', nats),
            ('citizenships', cits),
            ('identifiers', identifiers),
            ('weak_aliases', _vals('weakAlias', 20)),
            ('positions', positions),
            ('programs', _vals('programId', 10, 100)),
            ('father_name', _vals('fatherName', 2, 100)),
        ) if v}
        if schema == 'Vessel':
            pn = _vals('previousName', 20, 200) + _vals('pastNames', 20, 200)
            # 'YI MENG SHAN (formerly ATTICA)': the bracket names a former name, the rest is the name
            clean_aliases = []
            for a in aliases:
                m = re.search(r'\(\s*(?:formerly|ex|f\.?k\.?a\.?|previously)\s*:?\s*([^)]+)\)', a, re.I)
                if m:
                    pn += [x.strip() for x in re.split(r'[,;/]', m.group(1)) if x.strip()]
                    a = (a[:m.start()] + a[m.end():]).strip()
                if a:
                    clean_aliases.append(a)
            m = re.search(r'\(\s*(?:formerly|ex|f\.?k\.?a\.?|previously)\s*:?\s*([^)]+)\)', full_name, re.I)
            if m:
                pn += [x.strip() for x in re.split(r'[,;/]', m.group(1)) if x.strip()]
                full_name = (full_name[:m.start()] + full_name[m.end():]).strip() or full_name
            pn = [x for x in dict.fromkeys(pn) if x and x.upper() != full_name.upper()]
            aliases = [a for a in dict.fromkeys(clean_aliases + pn) if a != full_name]
            properties['vessel'] = vessel_block(
                imos=_vals('imoNumber', 5, 20), mmsi=_vals('mmsi', 5, 20), call_sign=_vals('callSign', 5, 20),
                vtype=next((t for t in sorted(props.get('type') or []) if t and t.isascii()), None) or
                (_vals('type', 1, 100) or [None])[0], flag=(_vals('flag', 1, 60) or [None])[0],
                flags_past=_vals('pastFlags', 20, 60), names_past=pn,
                gross_tonnage=(_vals('grossRegisteredTonnage', 1, 40) or _vals('tonnage', 1, 40) or [None])[0],
                year_built=(_vals('buildDate', 1, 20) or [None])[0],
                owners=[{'name': None, 'role': r, 'ref': f'OS-{v}'}
                        for key, r in (('owner', 'owner'), ('operator', 'operator'))
                        for v in _vals(key, 10, 200)],
                measures=vessel_measures(' '.join(props.get('notes') or [])) or
                (['asset_freeze'] if 'sanction' in topics else []))

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
            'gender': gender,
            # profile fields in one compact string (see expand_rich); key order is fixed, so the
            # content hash computed from the expanded record is stable from run to run
            '_os_rich': _pack_rich({
                'place_of_birth': pobs[0] if pobs else None,
                'passport_numbers': passports,
                'national_id_numbers': [],
                'addresses': addresses,
                'properties': properties,
                'first_seen': first_seen,
            }),
            'aliases': aliases,
            'details': sorted({_os_clean(x) for x in (props.get('notes') or []) if _os_clean(x)}),
            # rich fields are written (and compared by content hash) only once the backfill has
            # run: see EnhancedDataUpdater._import_entities_batch and
            # scripts/backfill_opensanctions_rich.py (screening_config 'opensanctions_rich').
            '_rich': True,
        }
        
        return entity

    def _legacy_entity(self, data, props, full_name, aliases, entity_type, countries, topics):
        """The OpenSanctions record as the loader built it before the profile fields."""
        dob = (props.get('birthDate') or [None])[0]
        nationality = (props.get('nationality') or [None])[0]
        datasets = data.get('datasets', [])
        dataset = datasets[0] if datasets else 'OpenSanctions'
        from screening.list_category import categorize as _list_category
        source_url = (data.get('referents') or [None])[0]
        if not source_url:
            source_url = f"https://www.opensanctions.org/entities/{data.get('id')}/"
        return {
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
