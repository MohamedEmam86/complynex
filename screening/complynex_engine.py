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

from rapidfuzz import fuzz
from rapidfuzz import distance as rapid_distance
import jellyfish
from pyarabic import araby
import sqlite3
try:
    import psycopg
    from psycopg.rows import dict_row
    PSYCOPG_VERSION = 3
except ImportError:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        PSYCOPG_VERSION = 2
    except ImportError:
        psycopg2 = None
        PSYCOPG_VERSION = 0
from datetime import datetime
import logging
import re
import os
try:
    import redis
except ImportError:
    redis = None
import hashlib
import json
from itertools import product
from .metrics import ScreeningMetrics
from .arabic_utils import EGYPTIAN_ARABIC_VARIANTS, normalize_arabizi, normalize_prefixes, get_english_variants, generate_compound_variants, generate_arabic_variants
try:
    from .ml_module import MLScoreCalibrator
except ImportError:
    MLScoreCalibrator = None
try:
    from .ml_module import ModelVersionManager, OnlineLearner
except ImportError:
    ModelVersionManager = None
    OnlineLearner = None

try:
    from .adverse_media_config import ADVERSE_MEDIA_CONFIG
    from .waterfall_scraper import WaterfallAdverseMediaScraper
except ImportError:
    WaterfallAdverseMediaScraper = None

try:
    from .semantic_matcher import (
        SemanticMatcherClient,
        WATCHLIST_ID_OFFSET, INTERNAL_PEP_ID_OFFSET, INTERNAL_BLACKLIST_ID_OFFSET,
    )
except ImportError:
    SemanticMatcherClient = None
    WATCHLIST_ID_OFFSET, INTERNAL_PEP_ID_OFFSET, INTERNAL_BLACKLIST_ID_OFFSET = 0, 1_000_000_000, 2_000_000_000

try:
    from .network_analyzer import NetworkAnalyzer
except ImportError:
    NetworkAnalyzer = None

try:
    from .transaction_analyzer import TransactionAnalyzer
except ImportError:
    TransactionAnalyzer = None

from .db_pool import db_pool
from .internal_blacklist_service import InternalBlacklistService
from .internal_pep_service import InternalPEPService

# --- CONSTANTS ---

COMMON_ARABIC_NAMES = {
    'first_names': [
        # Arabic
        'محمد', 'أحمد', 'علي', 'حسن', 'حسين', 'عبد الله', 'خالد', 'عمر', 
        'محمود', 'يوسف', 'إبراهيم', 'مصطفى', 'عبد الرحمن', 'سيد',
        # English variations
        'mohamed', 'muhammad', 'mohammed', 'mohamad', 'muhammed',
        'ahmad', 'ahmed', 'ali', 'hassan', 'hasan', 'hasaan',
        'hussein', 'hussain', 'hosein', 'abdullah', 'abd allah', 'abdallah',
        'khaled', 'khalid', 'omar', 'umar', 'mahmoud', 'mahmud',
        'youssef', 'yusuf', 'yousef', 'ibrahim', 'mustafa', 'mostafa',
        'abdel rahman', 'abdelrahman', 'sayed', 'sayed', 'sayyed',
        'tarek', 'tariq', 'yasser', 'yasir', 'walid', 'waleed',
        'hany', 'hani', 'sherif', 'shareef', 'ramy', 'rami'
    ],
    'last_names': [
        # Arabic
        'حسن', 'علي', 'أحمد', 'محمد', 'عبد الله', 'إبراهيم', 'السيد',
        'عثمان', 'حسين', 'صالح', 'منصور', 'فهمي', 'سليمان', 'عبد العزيز',
        # English
        'hassan', 'hasan', 'ali', 'ahmed', 'ahmad', 'mohamed', 'muhammad',
        'abdullah', 'ibrahim', 'el-sayed', 'al-sayed', 'alsayed', 'elsayed',
        'osman', 'othman', 'uthman', 'hussein', 'saleh', 'salah',
        'mansour', 'mansur', 'fahmy', 'fahmi', 'soliman', 'suleiman',
        'abdel aziz', 'abdelaziz', 'el-shafei', 'elshafei', 'shafei'
    ]
}

# Same purpose as COMMON_ARABIC_NAMES (gates the -15 common-name penalty so
# "John Smith" doesn't ride a real-but-unrelated watchlist "John Smith" up
# to LOW_MATCH), but for Western/English names — that penalty previously
# only ever fired for Arabic-region names, leaving names this common from
# elsewhere with no false-positive mitigation at all. Sourced from US
# Census Bureau's published most-frequent surname/given-name lists (public,
# stable, not a per-name curation — same kind of source the existing Arabic
# list draws its English transliteration spellings from).
COMMON_WESTERN_NAMES = {
    'first_names': [
        'james', 'john', 'robert', 'michael', 'william', 'david', 'richard',
        'joseph', 'thomas', 'charles', 'christopher', 'daniel', 'matthew',
        'anthony', 'mark', 'donald', 'steven', 'paul', 'andrew', 'joshua',
        'kenneth', 'kevin', 'brian', 'george', 'edward', 'ronald', 'timothy',
        'jason', 'jeffrey', 'ryan', 'jacob', 'gary', 'nicholas', 'eric',
        'jonathan', 'stephen', 'larry', 'justin', 'scott', 'brandon',
        'benjamin', 'samuel', 'frank', 'gregory', 'raymond', 'alexander',
        'patrick', 'jack', 'dennis', 'jerry', 'tyler', 'aaron',
        'mary', 'patricia', 'jennifer', 'linda', 'elizabeth', 'barbara',
        'susan', 'jessica', 'sarah', 'karen', 'nancy', 'lisa', 'margaret',
        'betty', 'sandra', 'ashley', 'dorothy', 'kimberly', 'emily', 'donna',
        'michelle', 'carol', 'amanda', 'melissa', 'deborah', 'stephanie',
        'rebecca', 'sharon', 'laura', 'cynthia', 'kathleen', 'amy', 'angela',
        'shirley', 'anna', 'brenda', 'pamela', 'emma', 'nicole', 'helen',
        'samantha', 'katherine', 'christine', 'debra', 'rachel', 'carolyn',
        'janet', 'catherine', 'maria', 'heather', 'diane', 'olivia', 'julie',
        'joyce',
    ],
    'last_names': [
        'smith', 'johnson', 'williams', 'brown', 'jones', 'garcia', 'miller',
        'davis', 'rodriguez', 'martinez', 'hernandez', 'lopez', 'gonzalez',
        'wilson', 'anderson', 'thomas', 'taylor', 'moore', 'jackson',
        'martin', 'lee', 'perez', 'thompson', 'white', 'harris', 'sanchez',
        'clark', 'ramirez', 'lewis', 'robinson', 'walker', 'young', 'allen',
        'king', 'wright', 'scott', 'torres', 'nguyen', 'hill', 'flores',
        'green', 'adams', 'nelson', 'baker', 'hall', 'rivera', 'campbell',
        'mitchell', 'carter', 'roberts', 'gomez', 'phillips', 'evans',
        'turner', 'diaz', 'parker', 'cruz', 'edwards', 'collins', 'reyes',
        'stewart', 'morris', 'morales', 'murphy', 'cook', 'rogers',
        'gutierrez', 'ortiz', 'morgan', 'cooper', 'peterson', 'bailey',
        'reed', 'kelly', 'howard', 'ramos', 'kim', 'cox', 'ward',
        'richardson', 'watson', 'brooks', 'chavez', 'wood', 'james',
        'bennett', 'gray', 'mendoza', 'ruiz', 'hughes', 'price', 'alvarez',
        'castillo', 'sanders', 'patel', 'myers', 'long', 'ross', 'foster',
        'jimenez',
    ],
}

ARABIC_NAME_VARIANTS = {
    # محمد variants
    'محمد': ['mohamed', 'muhammad', 'mohammed', 'mohamad', 'muhammed', 'mohammad'],
    
    # حسن variants
    'حسن': ['hassan', 'hasan', 'hasaan', 'hassaan'],
    
    # حسين variants
    'حسين': ['hussein', 'hussain', 'husain', 'hosein', 'hossein'],
    
    # أحمد variants
    'أحمد': ['ahmed', 'ahmad', 'ahmadi'],
    'احمد': ['ahmed', 'ahmad', 'ahmadi'],
    
    # علي variants
    'علي': ['ali', 'aly', 'alee'],
    
    # عبد الله variants
    'عبد الله': ['abdullah', 'abd allah', 'abdallah', 'abdulla', 'abdollah'],
    'عبدالله': ['abdullah', 'abd allah', 'abdallah', 'abdulla', 'abdollah'],
    
    # عبد الرحمن variants
    'عبد الرحمن': ['abdelrahman', 'abdel rahman', 'abd al rahman', 'abdurahman', 'abdurrahman', 'abdel-rahman', 'abd el-rahman', 'abdulrahman', 'abdul rahman', 'abdul-rahman'],
    'عبدالرحمن': ['abdelrahman', 'abdel rahman', 'abd al rahman', 'abdurahman', 'abdurrahman', 'abdel-rahman', 'abd el-rahman', 'abdulrahman', 'abdul rahman', 'abdul-rahman'],
    
    # عز الدين variants
    'عز الدين': ['ezz eldin', 'ezz el din', 'ezzeldin', 'ezz al din', 'ezz-eldin', 'izz al-din', 'ezz aldeen', 'ezz el-din'],
    'عزالدين': ['ezz eldin', 'ezz el din', 'ezzeldin', 'ezz al din', 'ezz-eldin', 'izz al-din', 'ezz aldeen', 'ezz el-din'],

    # امام / إمام variants (surname/title, e.g. "Emam", "Imam")
    'امام': ['emam', 'imam', 'eemam'],
    'إمام': ['emam', 'imam', 'eemam'],

    # خالد variants
    'خالد': ['khaled', 'khalid', 'kaled', 'kalid'],
    
    # عمر variants
    'عمر': ['omar', 'umar', 'omer'],
    
    # يوسف variants
    'يوسف': ['youssef', 'yusuf', 'yousef', 'yusif', 'yosef'],
    
    # محمود variants
    'محمود': ['mahmoud', 'mahmud', 'mahmood', 'mehmood'],
    
    # إبراهيم variants
    'إبراهيم': ['ibrahim', 'ibraheem', 'ibrahem', 'ebrahim'],
    'ابراهيم': ['ibrahim', 'ibraheem', 'ibrahem', 'ebrahim'],
    
    # Phase 4 Egyptian Additions
    'فرج': ['farag', 'farrag', 'faraj'],
    'شحاتة': ['shehata', 'shihata', 'shahatah'],
    'النجار': ['el-naggar', 'nagar', 'naggar'],
    'السيد': ['el-sayed', 'sayed', 'sayyed'],
    'جابر': ['gaber', 'jaber', 'gabr'],
    'فؤاد': ['fouad', 'fuad'],
    'فوزي': ['fawzy', 'fawzi'],
    'رمضان': ['ramadan', 'ramadhan'],
    'شعبان': ['shaaban', "sha'ban"],
    'بدوي': ['badawi', 'badawy'],
    'عبد الحميد': ['abdel-hamid', 'abd el-hamid', 'abdelhamid', 'abdulhamid', 'abdul hamid', 'abdul-hamid'],
    'عبد العزيز': ['abdel-aziz', 'abd el-aziz', 'abdelaziz', 'abdulaziz', 'abdul aziz', 'abdul-aziz'],
    'مرسي': ['morsi', 'mursi', 'morsy'],
    'طنطاوي': ['tantawi', 'tantawy'],
    'مبارك': ['mubarak', 'moubarek'],
    'السادات': ['sadat', 'el-sadat'],
    'حلمي': ['helmy', 'hilmi'],
    'لطفي': ['lotfy', 'lutfi', 'lotfi'],
    'سرور': ['sorour', 'surur', 'sorur'],
    'جودة': ['gouda', 'joda', 'jawda'],
    'زكي': ['zaki', 'zaky'],
    'شفيق': ['shafik', 'shafiq', 'shafeek'],

    # مصطفى variants (Also handling common Qaf vs Fa typing errors: مصطقي)
    'مصطفى': ['mustafa', 'mostafa', 'mustapha', 'mustpha'],
    'مصطفي': ['mustafa', 'mostafa', 'mustapha', 'mustpha'],
    'مصطقي': ['mustafa', 'mostafa', 'mustapha', 'mustpha'],
    'مصطقى': ['mustafa', 'mostafa', 'mustapha', 'mustpha'],
    
    # عيسى variants 
    'عيسى': ['eisa', 'essa', 'issa'],
    'عيسي': ['eisa', 'essa', 'issa'],
    
    # موسى variants
    'موسى': ['mousa', 'moussa', 'musa'],
    'موسي': ['mousa', 'moussa', 'musa'],
    
    # يحيى variants
    'يحيى': ['yahya', 'yehia', 'yehya'],
    'يحيي': ['yahya', 'yehia', 'yehya'],
    
    # سيد variants
    'سيد': ['sayed', 'sayyed', 'saeed', 'said', 'syed'],
    
    # طارق variants
    'طارق': ['tarek', 'tariq', 'tarik', 'tareq'],
    
    # ياسر variants
    'ياسر': ['yasser', 'yasir', 'yaser', 'yaseer'],
    
    # كامل variants
    'كامل': ['kamel', 'kamal', 'kaamel', 'kamil'],
    
    # الوزير variants (Handling Al/El prefix and Wazir) — 'minister' (the
    # dictionary meaning of the word, not a name spelling) was previously
    # included here and generated search variants like "kamel minister",
    # which token-matched against any watchlist record with "Minister" in
    # a job title/position field — a name meaning "El Wazir" (surname)
    # spuriously matching 18 unrelated PEPs by literal job title, reported
    # against a real screening of "كامل الوزير" / "Kamel El Wazir".
    'الوزير': ['wazir', 'elwazir', 'alwazir', 'el-wazir', 'al-wazir', 'ouazir'],
    'وزير': ['wazir', 'elwazir', 'alwazir', 'el-wazir', 'al-wazir', 'ouazir'],

    # اشرف variants
    'اشرف': ['ashraf', 'ashraff', 'achraf', 'achraff'],
    'أشرف': ['ashraf', 'ashraff', 'achraf', 'achraff'],

    # صبحي variants
    'صبحي': ['sobhy', 'sobhi', 'subhi', 'subhy', 'sobhey', 'sabhi'],
    'صبحى': ['sobhy', 'sobhi', 'subhi', 'subhy', 'sobhey', 'sabhi'],

    # عبد الفتاح variants
    'عبد الفتاح': ['abdelfattah', 'abdel fattah', 'abd al fattah', 'abd el fattah', 'abdel-fattah', 'abd el-fattah', 'abdulfattah', 'abdul fattah', 'abdul-fattah'],
    'عبدالفتاح': ['abdelfattah', 'abdel fattah', 'abd al fattah', 'abd el fattah', 'abdel-fattah', 'abd el-fattah', 'abdulfattah', 'abdul fattah', 'abdul-fattah'],
    
    # السيسي variants
    'سيسي': ['sisi', 'elseysee', 'alsisi', 'el-sisi', 'al-sisi'],
    'السيسي': ['sisi', 'elseysee', 'alsisi', 'el-sisi', 'al-sisi'],
    
    # منصور variants
    'منصور': ['mansour', 'mansur', 'mansoor'],
    
    # سليمان variants
    'سليمان': ['soliman', 'suleiman', 'sulaiman', 'sleiman'],

    # لبيب variants
    'لبيب': ['labib', 'labeeb'],

    # بشار variants (e.g. Bashar al-Assad)
    'بشار': ['bashar', 'bachar', 'basshar'],

    # الأسد / الاسد variants (e.g. al-Assad) — the crude character
    # transliteration fallback drops short vowels ("alasd" instead of
    # "al-assad"), which was too far from the real OFAC/EU spelling for
    # ES's fuzzy matching to retrieve those records at all when screening
    # Arabic input.
    'الأسد': ['al-assad', 'alassad', 'al assad', 'assad'],
    'الاسد': ['al-assad', 'alassad', 'al assad', 'assad'],

    # Other high-profile sanctioned/PEP individuals whose OFAC/EU/UN entries
    # are Latin-only — same vowel-loss problem as الأسد above (e.g. "بوتين"
    # crude-transliterates to "bwtin", nowhere near "putin").
    'بوتين': ['putin'],
    # Arabic has no native "v" — فلاديمير is the standard spelling of
    # "Vladimir" but the plain character map only yields "fladimir",
    # missing the actual official-list spelling entirely.
    'فلاديمير': ['vladimir', 'fladimir'],
    'القذافي': ['al-qadhafi', 'qadhafi', 'gaddafi', 'kadhafi', 'al-gaddafi', 'el-gaddafi'],
    'قذافي': ['qadhafi', 'gaddafi', 'kadhafi'],
    'البشير': ['al-bashir', 'bashir', 'el-bashir'],
    'بشير': ['bashir'],
    'لادن': ['laden', 'ladin'],
    'بن': ['bin', 'ben', 'ibn'],
    'أسامة': ['osama', 'usama', 'ossama', 'oussama'],
    'اسامة': ['osama', 'usama', 'ossama', 'oussama'],
}

logger = logging.getLogger(__name__)

# Elasticsearch client
try:
    from elasticsearch import Elasticsearch
    from screening.es_client import get_es_client
    _es_client = get_es_client()
    if _es_client.ping():
        logger.info("[ES] Elasticsearch connected successfully")
        ES_AVAILABLE = True
    else:
        logger.warning("[ES] Elasticsearch ping failed — will use PostgreSQL fallback")
        ES_AVAILABLE = False
        _es_client = None
except Exception as e:
    logger.warning(f"[ES] Elasticsearch unavailable: {e}")
    ES_AVAILABLE = False
    _es_client = None

# Redis client
try:
    import redis as redis_lib
    _redis_client = redis_lib.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    _redis_client.ping()
    REDIS_AVAILABLE = True
    logger.info("[REDIS] Redis connected successfully")
except Exception as e:
    REDIS_AVAILABLE = False
    _redis_client = None
    logger.warning(f"[REDIS] Redis unavailable: {e}")

ARABIC_TO_ENGLISH_MAP = {
    'ا': 'a', 'أ': 'a', 'إ': 'e', 'آ': 'a', 'ٱ': 'a',
    'ب': 'b', 'ت': 't', 'ث': 'th', 'ج': 'j', 'ح': 'h', 'خ': 'kh',
    'د': 'd', 'ذ': 'th', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'sh',
    'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a', 'غ': 'gh',
    'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
    'ه': 'h', 'و': 'w', 'ي': 'i', 'ى': 'a', 'ة': 'h',
    'ء': '', 'ؤ': '', 'ئ': '',
    # Persian/Urdu additions if needed
    'گ': 'g', 'چ': 'ch', 'پ': 'p', 'ژ': 'zh', 'ک': 'k'
}

def extract_bio_snippet(details_raw, max_len=220):
    """
    Parse a screening_watchlist.details value into a clean, truncated 1-2
    line snippet for display. The column stores a JSON-encoded string —
    typically a single-element list holding a full biography/notability
    paragraph (e.g. OpenSanctions' topics/position blurb, UN's listing
    narrative) — which is far too long to show as-is next to a match.
    Returns '' if there's nothing usable.
    """
    if not details_raw:
        return ''
    try:
        parsed = json.loads(details_raw)
    except (TypeError, ValueError):
        parsed = details_raw

    if isinstance(parsed, list) and parsed:
        text = str(parsed[0])
    elif isinstance(parsed, str):
        text = parsed
    else:
        return ''

    text = text.strip()
    if not text or text in ('{}', '[]'):
        return ''
    if len(text) <= max_len:
        return text

    # Prefer cutting at a sentence boundary near max_len over a hard chop.
    cut = text[:max_len]
    last_period = cut.rfind('. ')
    if last_period > max_len * 0.4:
        return cut[:last_period + 1]
    return cut.rstrip() + '…'


def compute_fallback_bio(candidate):
    """
    When a match has no real narrative text (extract_bio_snippet returned
    nothing), build a short line from whatever structured fields ARE
    available — nationality, DOB, topics — so a screener still has
    something to help judge false positive vs true match, instead of a
    blank bio section. Returns '' if nothing usable is available either.
    """
    parts = []
    nationality = candidate.get('nationality')
    if nationality:
        parts.append(f"Nationality: {nationality}")
    dob = candidate.get('date_of_birth')
    if dob:
        parts.append(f"DOB: {dob}")

    topics = candidate.get('topics')
    if isinstance(topics, str):
        try:
            topics = json.loads(topics)
        except (TypeError, ValueError):
            topics = [topics] if topics else []
    if isinstance(topics, list) and topics:
        readable = [str(t).replace('_', ' ').replace('-', ' ') for t in topics if t and str(t).lower() not in ('sanctions', 'egypt', 'local')]
        if readable:
            parts.append("Topics: " + ", ".join(readable[:3]))

    return " | ".join(parts) if parts else ''


def transliterate_arabic(text: str) -> str:
    """Phonetic transliteration using manual mapping to avoid missing language packs entirely"""
    if not text: 
        return ""
    
    result = []
    for char in text:
        if char in ARABIC_TO_ENGLISH_MAP:
            result.append(ARABIC_TO_ENGLISH_MAP[char])
        elif char.isspace():
            result.append(' ')
        elif char.isalnum(): # Keep English/Numbers
            result.append(char)
    return "".join(result)

def normalize_arabic_text(text):
    """
    Canonical normalization as per specifications
    
    Steps:
    1. Strip diacritics (Tashkeel: Fatha, Damma, Kasra, etc.)
    2. Normalize Alef variants (أ, إ, آ → ا)
    3. Normalize Yeh/Maksura (ى → ي)
    4. Normalize Teh Marbuta (ة → ه)
    5. Remove Tatweel (ـ)
    """
    if not text:
        return ""
    
    # Step 1: Strip all diacritics (Tashkeel)
    text = araby.strip_tashkeel(text)
    
    # Step 2: Normalize Alef variants to plain Alef
    text = text.replace('أ', 'ا')
    text = text.replace('إ', 'ا')
    text = text.replace('آ', 'ا')
    text = text.replace('ٱ', 'ا') # Alef Wasla
    
    # Step 3: Normalize Yeh/Maksura (ى → ي)
    text = text.replace('ى', 'ي')
    
    # Step 4: Normalize Teh Marbuta (ة → ه)
    text = text.replace('ة', 'ه')
    
    # Step 5: Normalize Hamza variants to plain Hamza/Alef where appropriate for matching
    # Note: Generally we want to match 'ؤ' or 'ئ' with 'ء' or just keep them%s
    # Spec says: "Normalize Alef variants".
    text = text.replace('ؤ', 'ء')
    text = text.replace('ئ', 'ء')
    
    # Step 6: Remove Tatweel (elongation character)
    text = araby.strip_tatweel(text)
    
    # Step 7: Normalize Arabic compound prefixes
    # DB stores SPACED form (عبد الحليم), so always EXPAND unspaced input.
    # Uses lambda in re.sub — avoids \1 corruption in any context.
    import re as _re7
    text = _re7.sub(
        r'\u0639\u0628\u062f\u0627\u0644([\u0600-\u06FF])',
        lambda _m: '\u0639\u0628\u062f \u0627\u0644' + _m.group(1),
        text
    )  # عبدالX → عبد الX
    text = _re7.sub(r'\u0639\u0628\u062f\s{2,}\u0627\u0644', '\u0639\u0628\u062f \u0627\u0644', text)
    text = _re7.sub(r'\s{2,}', ' ', text).strip()
    
    # Additional: Remove extra whitespace
    text = ' '.join(text.split())
    
    return text.strip()

def generate_english_variants(name: str) -> list[str]:
    """
    Generate multiple English transliteration variants (Combinatorial)
    """
    if not name:
        return []
        
    tokens = name.lower().strip().split()
    
    # Get variants for each token
    token_variants = []
    for token in tokens:
        # Strip diacritics for lookup
        clean_token = araby.strip_tashkeel(token)
        # Also try normalized versions
        norm_token = normalize_arabic_text(clean_token)
        
        # Hardcoded common transliterations if dictionary lookup fails
        # This acts as a 'smart' fallback for unknown names
        found = False
        for key, vars_list in ARABIC_NAME_VARIANTS.items():
            if clean_token == key or norm_token == key:
                token_variants.append(vars_list)
                found = True
                break
        
        if not found:
            # Fallback transliteration logic for unknown tokens
            # Add the original token so we don't lose the Arabic script
            variants = [token]
            
            # Try character-based transliteration
            transliterated = transliterate_arabic(clean_token)
            if transliterated and transliterated != clean_token:
                variants.append(transliterated)
                
            token_variants.append(variants)
    
    # Generate all combinations
    # Cap each token's spellings BEFORE the product. This is where the growth
    # comes from: five tokens with three spellings each is 243 combinations.
    # The dictionary lists the commonest spelling first.
    MAX_PER_TOKEN = 3
    token_variants = [v[:MAX_PER_TOKEN] for v in token_variants]

    # product() yields in odometer order, so the first combination is every
    # token's most canonical spelling and later ones grow steadily more obscure.
    all_combinations = list(product(*token_variants))
    
    # Convert tuples back to strings
    variants: list[str] = [' '.join(combo) for combo in all_combinations]
    
    base = transliterate_arabic(name)
    if base and base not in variants:
        variants.append(base)
        
    # Return max 50 combinations to prevent astronomical query expansions
    # DEDUPE IN ORDER — not with set().
    #
    # This line was `list(set(variants))[:50]`. Python set iteration follows
    # hash order, not insertion order, so it discarded the ranking product()
    # had just produced and kept fifty arbitrary combinations. The canonical
    # spelling could be dropped while obscure ones survived. The cap was not
    # selecting the most likely variants; it was selecting fifty at random.
    seen = set()
    ordered = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            ordered.append(v)

    # 12, not 50. Variant 40 is the fortieth-most-likely Latin spelling of one
    # name; a record spelled that obscurely is found by the Arabic-to-Arabic
    # and phonetic paths, not by a lucky transliteration. Fifty of these in one
    # Elasticsearch query against 2.7M documents was the largest single cost in
    # a screen — 2,815ms of 4,780ms.
    MAX_VARIANTS = 12
    capped = ordered[:MAX_VARIANTS]

    # The base transliteration always survives the cap.
    if base and base not in capped:
        capped.append(base)

    return capped

def has_variant_exact_match(search_name, match_name):
    """
    Check if any transliteration variant of search_name exactly matches match_name
    """
    search_variants = generate_english_variants(search_name)
    # match_name might be English already, so we might need variants of it if it was Arabic%s
    # Usually match_name from DB is English Normalized for global lists.
    # If match_name from DB is Arabic, we generate variants for it too.
    
    # Assuming match_name might be Latin or Arabic.
    # If match_name is Latin, generate_english_variants returns [match_name] (if no arabic chars)
    # properly if filtered. 
    # Actually generate_english_variants assumes input is Arabic tokens mostly.
    # If input is English, it returns it as is (token not in ARABIC_NAME_VARIANTS).
    
    match_variants = generate_english_variants(match_name)
    
    search_set = set([v.lower() for v in search_variants])
    match_set = set([v.lower() for v in match_variants])
    
    intersection = search_set.intersection(match_set)
    
    if intersection:
        return (True, list(intersection)[0])
    else:
        return (False, None)

def is_common_name_only(name_tokens):
    """Check if ALL tokens in a name are common names (Arabic or Western) —
    used to apply COMMON_NAME_PENALTY so an extremely generic name like
    "Mohamed Ahmed" or "John Smith" doesn't ride a real-but-unrelated
    watchlist entry up to a match purely on first+last name frequency."""
    if not name_tokens:
        return False

    normalized_tokens = [token.lower().strip() for token in name_tokens]

    all_common = (COMMON_ARABIC_NAMES['first_names'] +
                  COMMON_ARABIC_NAMES['last_names'] +
                  COMMON_WESTERN_NAMES['first_names'] +
                  COMMON_WESTERN_NAMES['last_names'])
    all_common_lower = set([name.lower() for name in all_common])
    
    return all(token in all_common_lower for token in normalized_tokens if token)

def apply_common_name_penalty(search_tokens, match_tokens, base_score, penalty_value):
    """Apply penalty if both names are purely common names"""
    search_is_common = is_common_name_only(search_tokens)
    match_is_common = is_common_name_only(match_tokens)
    
    if search_is_common and match_is_common:
        return max(0.0, base_score - penalty_value)
    
    return base_score

def calculate_dob_bonus(search_dob, match_dob):
    """
    Calculate DOB bonus with graduated matching
    """
    if not search_dob or not match_dob:
        return 0.0
    
    # Handle simple string equality first
    if str(search_dob) == str(match_dob):
        return 10.0
        
    s_str = str(search_dob).strip()
    m_str = str(match_dob).strip()
    
    # Helper to clean date
    def clean_date_str(d):
        return d.replace('-XX', '').replace('-00', '')
        
    s_clean = clean_date_str(s_str)
    m_clean = clean_date_str(m_str)
    
    # Split
    s_parts = s_clean.split('-')
    m_parts = m_clean.split('-')
    
    # Level 1: Exact (Already checked, but check parsed)
    if s_clean == m_clean and len(s_parts) == 3:
        return 10.0
        
    # Level 2: Year + Month
    if len(s_parts) >= 2 and len(m_parts) >= 2:
        if s_parts[0] == m_parts[0] and s_parts[1] == m_parts[1]:
            return 7.0
            
    # Level 3: Year Only
    if s_parts[0] == m_parts[0]:
        return 5.0
        
    # Level 4: Decade
    if len(s_parts[0]) == 4 and len(m_parts[0]) == 4:
        if s_parts[0][:3] == m_parts[0][:3]:
            return 3.0
            
    return 0.0

def _token_sorted(s):
    """Alphabetizes whitespace-separated tokens — used to make
    Jaro-Winkler (which is heavily prefix-weighted, unlike token_set_ratio)
    order-insensitive too. Without this, "Saddam Hussein" and "Hussein
    Saddam" can compute near-identical fuzzy/token_set scores but wildly
    different JW scores (high common-prefix vs none), occasionally enough
    to drag a genuinely-matching reordered name below LOW_MATCH_THRESHOLD."""
    return ' '.join(sorted(s.split())) if s else s

# ---------------------------------------------------------------------------
# Non-distinctive name components.
#
# Derived from token frequency across the 102,196 real merchant names in the
# Observed corpus: محمد appears in 45% of all names, احمد in 23%, عبد in 22%.
# Two people sharing these tokens tells you nothing about whether they are the
# same person, so they must not earn an "exact match" boost on their own.
# Latin forms are included because matching also runs on transliterated names.
# ---------------------------------------------------------------------------
NON_DISTINCTIVE_NAME_TOKENS = {
    # Arabic - >=1% frequency in the merchant population
    'محمد', 'احمد', 'أحمد', 'عبد', 'محمود', 'ابراهيم', 'إبراهيم', 'السيد',
    'حسن', 'علي', 'على', 'سيد', 'حسين', 'مصطفى', 'مصطفي', 'ابو', 'أبو',
    'الله', 'عبدالله', 'يوسف', 'رمضان', 'سعيد', 'سعد', 'اسماعيل', 'إسماعيل',
    'جمال', 'الدين', 'الحميد', 'سليمان', 'خالد', 'الرحمن', 'صلاح', 'العزيز',
    'عمر', 'شعبان', 'عادل', 'رجب', 'عوض', 'حامد', 'عبده', 'عبدالرحمن',
    'سالم', 'عيد', 'اسلام', 'ال', 'بن', 'بنت', 'أبو',
    # Latin transliterations of the same components
    'mohamed', 'mohammed', 'muhammad', 'mohammad', 'mohamad', 'muhammed',
    'ahmed', 'ahmad', 'abd', 'abdel', 'abdul', 'abdulla', 'abdullah',
    'mahmoud', 'mahmood', 'ibrahim', 'elsayed', 'el-sayed', 'sayed', 'sayyed',
    'hassan', 'hasan', 'ali', 'aly', 'hussein', 'hussain', 'hossein',
    'mostafa', 'mustafa', 'moustafa', 'abou', 'abu', 'allah', 'youssef',
    'yousef', 'yusuf', 'ramadan', 'said', 'saeed', 'saad', 'ismail',
    'gamal', 'jamal', 'din', 'eldin', 'al', 'el', 'bin', 'ben', 'ibn',
    'omar', 'umar', 'khaled', 'khalid', 'salah', 'aziz', 'adel', 'awad',
    'hamed', 'salem', 'salim', 'islam', 'mohsen',
}


from screening.name_intelligence import (
    _core_tokens,
    given_name_conflict as _given_conflict,
    evidence_too_thin as _thin_evidence,
    thin_name_conflict as _thin_conflict,
    names_are_effectively_same as _same_name,
    arabic_phonetic_key as _ar_key,
    canonicalise_latin as _canon_latin,
    family_name_verdict as _family_verdict,
    is_arabic as _is_ar,
    is_short_form as _is_short_form,
    phonetic_similarity_arabic as _ar_phonetic_sim,
)


def _distinctive_fuzzy(a, b):
    """Fuzzy similarity that trusts containment only when it is meaningful.

    fuzz.token_set_ratio returns 100 whenever one name's token set is contained
    in the other's, however many extra words there are. That is correct for
    'Osama Bin Laden' inside 'Usama Bin Muhammed Bin Awad Bin Laden', and badly
    wrong for 'احمد احمد احمد' inside 'احمد صبره احمد عواجه' — the first shares
    the distinctive token 'laden', the second shares only 'احمد', which appears
    in 23% of Egyptian names.

    So the containment measure is admitted only when the two names share at
    least one token that is not in NON_DISTINCTIVE_NAME_TOKENS. Order-sensitive
    measures always apply.
    """
    if not a or not b:
        return 0.0
    a = str(a)
    b = str(b)
    base = max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))

    # Two Latin spellings of one Arabic name are two different strings:
    # 'Mohamed Hassan' vs 'Muhammad Hasan' is 78.6 raw. Compare the canonical
    # forms too and keep the better result — max() only ever raises the base,
    # and the family-name and given-name caps are applied after this, so this
    # cannot create a match the rules would reject.
    if not (_is_ar(a) or _is_ar(b)):
        try:
            ca, cb = _canon_latin(a), _canon_latin(b)
            if ca and cb and (ca != a or cb != b):
                base = max(base, fuzz.ratio(ca, cb),
                           fuzz.token_sort_ratio(ca, cb))
        except Exception:
            pass

    ta = {t.lower().strip() for t in a.split() if t.strip()}
    tb = {t.lower().strip() for t in b.split() if t.strip()}
    shared = ta & tb
    distinctive = {t for t in shared if t not in NON_DISTINCTIVE_NAME_TOKENS}
    if distinctive:
        base = max(base, fuzz.token_set_ratio(a, b))
    return float(base)


def calculate_exact_match_boost(search_tokens, match_tokens):
    """
    Calculate graduated exact match boost
    """
    if not search_tokens or not match_tokens:
        return 0.0
    
    search_set = set([t.lower().strip() for t in search_tokens if t.strip()])
    match_set = set([t.lower().strip() for t in match_tokens if t.strip()])
    
    if not search_set or not match_set:
        return 0.0
    
    matching_tokens = search_set.intersection(match_set)

    # Shared tokens that actually identify a person. Two names that overlap
    # only on محمد / احمد / عبد are a coincidence: those appear in 45%, 23% and
    # 22% of Egyptian names respectively. Without this test, any merchant
    # called محمد scored a full "exact match" against any listed محمد.
    distinctive_shared = {t for t in matching_tokens
                          if t not in NON_DISTINCTIVE_NAME_TOKENS}
    if not distinctive_shared:
        return 0.0
    # A distinctive token IS shared, so containment is meaningful again: a
    # short query against a longer listed name (Osama Bin Laden vs Usama Bin
    # Muhammed Bin Awad Bin Laden) is a normal sanctions-data pattern and must
    # still match. The smaller-set denominator is safe here because overlaps
    # on common tokens alone already returned 0 above.
    # Floored at 2. With a denominator of 1 — a watchlist record holding a
    # single given name — the ratio is 1.0 by construction and every merchant
    # sharing that one name collects the full boost. 'Amjad' scored 100 against
    # 'AMJAD GHONIMMI HANAFY', whose independent similarity is 8.
    #
    # Containment is evidence when the contained name has two elements (Osama
    # Bin Laden inside the full chain). It is not evidence for one.
    smaller_set_size = max(min(len(search_set), len(match_set)), 2)
    
    if smaller_set_size == 0:
        return 0.0
        
    match_percentage = len(matching_tokens) / smaller_set_size
    
    if match_percentage >= 1.0:
        return 25.0
    elif match_percentage >= 0.67:
        return 15.0
    elif match_percentage >= 0.50:
        return 8.0
        
    return 0.0

class ComplyNexScreeningEngine:
    """
    Advanced AML Screening Engine with Arabic Intelligence
    """
    
    # Algorithm weights (Optimized 2024-02-11)
    FUZZY_RATIO_WEIGHT = 0.40      # 40% (Core)
    JARO_WINKLER_WEIGHT = 0.33     # 33% (Better for names)
    PHONETIC_WEIGHT = 0.15         # 15% — now Arabic-aware (see _ar_phonetic_sim)
    # A contradicting family name caps the score here. Egyptian naming makes
    # the last element decisive; sharing three common given names is not
    # identity. Set just below the 75 LOW_MATCH_THRESHOLD so a contradiction
    # drops out of the queue unless an identifier corroborates it.
    FAMILY_MISMATCH_CAP = 74.0
    PARTIAL_RATIO_WEIGHT = 0.12    # 12% (Compensate)
    
    # Adjustment bonuses
    EXACT_MATCH_MAX_BOOST = 25.0   # Max +25%
    DOB_EXACT_MATCH_BONUS = 10.0   # Max +10%
    DOB_MISMATCH_PENALTY = -10.0   # -10%
    NATIONALITY_BONUS = 5.0        # +5%
    COMMON_NAME_PENALTY = 15.0     # -15%
    
    # Risk thresholds (EXACT per specification)
    CONFIRMED_HIT_THRESHOLD = 95.0    # ≥95%
    POTENTIAL_MATCH_THRESHOLD = 80.0  # ≥80%
    LOW_MATCH_THRESHOLD = 75.0        # >=75%
    
    def __init__(self, db_config, cache_config=None, ml_threshold=0.60):
        self.db_config = db_config
        self.ml_threshold = ml_threshold
        self.db_conn = None
        
        # Redis cache
        if cache_config and redis:
            try:
                self.cache = redis.Redis(
                    host=cache_config.get('host', 'localhost'),
                    port=cache_config.get('port', 6379),
                    db=cache_config.get('db', 0),
                    password=cache_config.get('password'),
                    decode_responses=True
                )
                self.cache.ping() # Quick check
                self.cache_ttl = cache_config.get('ttl', 86400)  # 24 hours
                self.cache_enabled = True
                logger.info("Redis cache enabled and ready.")
            except Exception as e:
                logger.debug(f"Could not connect to Redis: {e}. Caching disabled. (Normal if Redis not running)")
                self.cache = None
                self.cache_enabled = False
        else:
            if cache_config and not redis:
                logger.warning("Redis configuration provided but 'redis' python module not found. Caching disabled.")
            self.cache = None
            self.cache_enabled = False

        # DB Config — normalize string path to dict format
        if isinstance(db_config, str):
            db_config = {'database': db_config}
        self.db_config = db_config
        # Always 'postgresql': db_pool.initialize() below (see db_pool.py's
        # own docstring) always connects to Postgres from env config
        # regardless of what db_config actually contains — every real call
        # site in this codebase passes either a bare sqlite path string or a
        # single-key {'database': path} dict (screening/routes.py's
        # production singleton, aml/routes.py, ekyc/pipeline.py), which the
        # old `'sqlite' if len(db_config) == 1 else 'postgresql'` heuristic
        # always misclassified as sqlite. That silently disabled Postgres-
        # only behavior gated on self.db_type (trigram similarity search in
        # _search_sqlite's fallback path, correct '%s' placeholders, and
        # this class's own semantic-candidate PostgreSQL enrichment) even
        # though every query actually ran against Postgres regardless.
        self.db_type = 'postgresql'
        self.db_conn = None
        
        # Initialize Pool
        db_pool.initialize(db_config)
        self.placeholder = '?' if self.db_type == 'sqlite' else '%s'
            
        # Metrics logger
        self.metrics = ScreeningMetrics(db_config)
        
        # Enhanced Arabic Variants Integration
        self.name_variants: dict[str, list[str]] = dict(ARABIC_NAME_VARIANTS)
        for k, v in EGYPTIAN_ARABIC_VARIANTS.items():
            if k in self.name_variants:
                self.name_variants[k].extend(v)
                self.name_variants[k] = list(set(self.name_variants[k]))
            else:
                self.name_variants[k] = v

        # ML Calibrator
        if MLScoreCalibrator:
            # Use absolute path for model directory to ensure reliability
            model_dir = os.path.dirname(os.path.abspath(__file__))
            self.ml_calibrator = MLScoreCalibrator(
                model_path=os.path.join(model_dir, 'ml_model.pkl'),
                metadata_path=os.path.join(model_dir, 'model_metadata.json'),
                threshold=self.ml_threshold
            )
        else:
            self.ml_calibrator = None

        # ML Manager & Online Learning
        if ModelVersionManager and OnlineLearner:
            # Also use absolute path for version manager
            self.model_manager = ModelVersionManager(model_dir=model_dir)
            # specific model loading
            loaded_model = self.model_manager.load_model()
            if loaded_model and self.ml_calibrator:
                self.ml_calibrator.model = loaded_model
                logger.info(f"Loaded ML Model Version: {self.model_manager.current_version}")
            
            self.online_learner = OnlineLearner(self.model_manager)
        else:
            self.model_manager = None
            self.online_learner = None

        # Calls the dedicated semantic_service.py process (see
        # complynex-semantic.service) over local HTTP rather than loading
        # the ~3.5GB embedding model + FAISS index in this process — every
        # gunicorn web worker lazily builds its own ComplyNexScreeningEngine
        # singleton, so loading it in-process here would mean N workers x
        # ~3.5GB. Cheap to construct; degrades to "no semantic candidates"
        # if the service isn't reachable, same as being disabled.
        if hasattr(self, 'semantic_matcher'):
            pass # already handled
        elif SemanticMatcherClient:
            self.semantic_matcher = SemanticMatcherClient()
        else:
            self.semantic_matcher = None

        if WaterfallAdverseMediaScraper:
            self.media_screener = WaterfallAdverseMediaScraper(config=ADVERSE_MEDIA_CONFIG, cache=self.cache)
        else:
            self.media_screener = None

        # Network & Transaction Analyzers
        self.network_analyzer = NetworkAnalyzer() if NetworkAnalyzer else None
        self.tx_analyzer = TransactionAnalyzer() if TransactionAnalyzer else None


    def _get_cache_key(self, name, dob, nationality):
        """Deprecated: Use screening.cache.make_cache_key instead"""
        key_data = f"{name}|{dob}|{nationality}".lower()
        return f"screening:{hashlib.md5(key_data.encode()).hexdigest()}"
    
    def connect_db(self):
        """Establish database connection using pool"""
        if not self.db_conn:
            try:
                self.db_conn = db_pool.checkout_connection()
                # For SQLite, we might need to attach row_factory if not handled by pool (pool handles it)
                if self.db_type == 'sqlite' and self.db_conn and not self.db_conn.row_factory:
                     self.db_conn.row_factory = sqlite3.Row
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                raise

    def close(self):
        """Return connection to pool"""
        if self.db_conn:
            try:
                db_pool.return_connection(self.db_conn)
            except Exception as e:
                logger.error(f"Error returning connection to pool: {e}")
            finally:
                self.db_conn = None

    def _structural_rescue(self, query_name, candidates, matches):
        """Candidates the string scorer under-rated but whose name matches
        element by element — typically across scripts (a Latin query against
        an Arabic-only record, or an Arabic query against the Arabic form of
        an international record). They are added with the structural score;
        the decision layer then applies identifiers, caps and the rule that
        a cross-script name alone never auto-confirms."""
        try:
            from screening import match_intel as _mi
            have = {str(m.get('id')) for m in matches if m.get('id') is not None}
            q_ar = _mi.is_arabic(query_name)
            for c in candidates or []:
                cid = c.get('id')
                if cid is None or str(cid) in have:
                    continue
                forms = [c.get('full_name'), c.get('original_name'), c.get('full_name_arabic')]
                forms += re.split(r'[|;]', c.get('aliases_arabic') or '')[:5]
                best, best_form = 0.0, None
                for f in dict.fromkeys((x or '').strip() for x in forms):
                    if not f:
                        continue
                    sc = _mi.name_match(query_name, f)['score']
                    if _mi.is_arabic(f) != q_ar:
                        sc *= 0.97
                    if sc > best:
                        best, best_form = sc, f
                if best >= self.LOW_MATCH_THRESHOLD:
                    md = dict(c)
                    md.update({'match_score': round(best, 2), 'matched_on': 'name_structure',
                               'candidate_name': c.get('name_normalized') or best_form,
                               'score_breakdown': {'name_structure': round(best, 2)}})
                    matches.append(md)
                    have.add(str(cid))
        except Exception as e:
            logger.warning(f"[MATCH-INTEL] structural rescue failed: {e}")
        return matches

    def _apply_name_logic_to_internal(self, query_name, internal_matches):
        """Apply the same name-structure rules the watchlist path uses.

        Internal matches are scored by the service layer with a bidirectional
        Jaro-Winkler over the whole string, which rewards a shared prefix and
        ignores which token is the family name. On Egyptian names that is the
        wrong instinct: محمد جابر السيد محمد and محمد السيد محمد العجريد scored
        93 despite belonging to different families.

        The listed name is judged on the form matching the script of the query.
        Judging on the most favourable of both forms looks safer but is not:
        internal records often hold a weak or empty transliteration, whose
        verdict is 'unknown', and 'unknown' does not cap — so a garbage English
        field would quietly rescue a false positive the Arabic form had already
        rejected.
        """
        q_is_ar = _is_ar(query_name)
        for m in internal_matches:
            try:
                ar = m.get('watchlist_name_ar')
                en = m.get('full_name')
                cand = (ar or en) if q_is_ar else (en or ar)
                if not cand:
                    continue
                # A Latin query against a record scored by match_intel was already
                # judged element by element across scripts; the record's own
                # Latin field is often a weak machine rendering and judging on
                # it would wrongly bury a name the Arabic original matches.
                if m.get('_mi_scored') and not q_is_ar:
                    continue

                score = float(m.get('match_score') or 0.0)
                s = score

                if _is_short_form(query_name, cand,
                                  NON_DISTINCTIVE_NAME_TOKENS):
                    s = max(s, 90.0)

                # A shared family name is not identity: عبد اللطيف is a
                # common Egyptian family name, and two unrelated people who
                # share it scored 92.5 on the family bonus alone.
                conflict = (_given_conflict(query_name, cand)
                            or _thin_conflict(query_name, cand)
                            or _thin_evidence(query_name, cand,
                                              NON_DISTINCTIVE_NAME_TOKENS))

                fam = _family_verdict(query_name, cand)
                if fam == 'mismatch' or conflict:
                    s = min(s, self.FAMILY_MISMATCH_CAP)
                elif fam == 'match':
                    s = min(100.0, s + 5.0)

                # A shared common token is not evidence. محمد appears in 45% of
                # Egyptian names and احمد in 23%: two names sharing only those
                # are not a lead.
                #
                # But it must not fire on a name being compared to itself.
                # خالد محمد احمد عبد الرحمن is built entirely from common
                # elements, and this rule capped that PEP against his own
                # record at 74 and dropped him from the results. Many Egyptian
                # names are like that.
                if not _same_name(query_name, cand,
                                  NON_DISTINCTIVE_NAME_TOKENS):
                    shared = (set(_core_tokens(query_name))
                              & set(_core_tokens(cand)))
                    if not (shared - set(NON_DISTINCTIVE_NAME_TOKENS)):
                        s = min(s, self.FAMILY_MISMATCH_CAP)

                if s != score:
                    m['match_score'] = round(float(s), 2)
                    m['name_logic'] = {
                        'original_score': round(score, 2),
                        'adjusted_score': round(float(s), 2),
                        'family_verdict': fam,
                        'judged_against': str(cand)[:120],
                    }
                    if s < score:
                        logger.info(
                            "[NAME-LOGIC] demoted internal match %.1f -> %.1f: "
                            "%r vs %r", score, s, str(query_name)[:40],
                            str(cand)[:40])
            except Exception as e:
                # never let this drop a listed-name match
                logger.warning("[NAME-LOGIC] internal gate failed: %s", e)
        return internal_matches

    def screen_person(self: "ComplyNexScreeningEngine", name: str, date_of_birth=None, nationality=None, entity_type='INDIVIDUAL', address=None, user_id=1, include_media=True, is_internal_blacklist=False, national_id=None, employer=None, threshold=None) -> dict:
        """
        Screen a person/entity using ensemble algorithm
        """
        # SAFETY: Limit name to max 15 words to prevent PostgreSQL 'Expression tree is too large' errors
        if threshold is not None:
            self.active_threshold = int(threshold)  # FIX: allow caller to pass threshold
        if name and isinstance(name, str):
            words: list[str] = name.split()
            if len(words) > 15:
                name = " ".join(words[:15])
                logger.warning(f"Name truncated to 15 words for screening to prevent query overflow")
                
        # --- REDIS RESULT CACHE: INTENTIONALLY DISABLED (2026-07-20) ---
        # AML/CFT screening decisions must always reflect the current sanctions
        # data + current matching logic. This cache was keyed only on
        # name+nationality+dob+threshold with a 1hr TTL and NO invalidation
        # tied to sanctions-list updates or engine code changes, so a stale
        # CLEAR verdict could silently persist for up to an hour after either
        # changed - a genuine false-negative risk for a licensed PSP.
        # Confirmed root cause of a missed sanctions match during live
        # diagnosis (Task #70/#73). Every screening request now always runs
        # the full live recall + scoring pipeline. cache_key is kept as None
        # so the write path below is also a no-op without further edits.
        import hashlib, json
        cache_key = None

        start_time = datetime.now()
        self.connect_db()
        
        import time
        t_start = time.time()
        processed_name = normalize_arabic_text(name) if self._is_arabic(name) else self._normalize_english(name)
        logger.debug(f"[TIMER] Arabic normalisation: {round((time.time()-t_start)*1000)}ms")
        
        if self._is_whitelisted(processed_name):
            return {
                'screening_result': 'WHITE_LISTED',
                'matches': [],
                'total_matches': 0,
                'highest_score': 0.0,
                'recommendation': '✅ WHITE-LISTED: No further action required',
                'processing_time_ms': int((datetime.now() - start_time).total_seconds() * 1000)
            }

        # 0b. INTERNAL BLACKLIST CHECK (High Priority)
        # Note: Results are merged with watchlist matches later, not early-returned,
        # so that PEP/sanctions lists are always checked as well.
        import time
        t_int = time.time()
        internal_matches = []
        internal_service = InternalBlacklistService()
        # Token-based recall + analyst scoring (screening/match_intel.py). The
        # old search_by_name required the whole query to be contained in the
        # listed name, so a customer whose ID name is longer than the listed
        # name, or spelled with a different hamza / taa marbuta, was missed.
        internal_hits: list[dict] = []
        internal_pep_hits: list[dict] = []
        try:
            from screening import match_intel as _mi
            _c = internal_service.get_connection()
            try:
                internal_hits = _mi.search_internal(_c, 'internal_blacklist', name)
                internal_pep_hits = _mi.search_internal(_c, 'internal_pep', name)
            finally:
                _c.close()
        except Exception as _e:
            logger.warning(f"[MATCH-INTEL] internal search failed, falling back: {_e}")
            internal_hits = internal_service.search_by_name(name)
            internal_pep_hits = InternalPEPService().search_by_name(name)
        logger.debug(f"[TIMER] Internal Blacklist hit: {round((time.time()-t_int)*1000)}ms")
        # 0c. INTERNAL PEP CHECK
        if internal_pep_hits:
            for hit in internal_pep_hits:
                hit_name_en = (hit.get('full_name') or '').lower()
                hit_name_ar = (hit.get('original_name') or '').lower()
                target_name = name.lower()
                # Use _match_score from NLP normalizer (bidirectional Jaro-Winkler)
                # _match_score is 0.0-1.0, convert to percentage for consistency
                pep_score = round(hit.get('_match_score', 0) * 100, 2)
                pep_jw = hit.get('_match_score', 0)
                if pep_score < self.LOW_MATCH_THRESHOLD:
                    continue
                hit_name = hit_name_ar if self._is_arabic(target_name) and hit_name_ar else (hit.get('full_name') or '')
                pep_match = {
                    'entity_id': hit['id'],
                    'full_name': hit_name,
                    'watchlist_name_ar': hit['original_name'],
                    'entity_type': hit['entity_type'],
                    'match_score': round(float(pep_score), 2),
                    'reason': hit['reason'],
                    'risk_level': hit['risk_level'],
                    'source': 'INTERNAL_PEP',
                    'source_name': 'Internal PEP List',
                    'list_type': 'PEP',
                    'dataset': 'Internal PEP',
                    'watchlist_id': hit['source_id'],
                    'source_id': hit['source_id'],
                    'nationality': hit['nationality'],
                    'date_of_birth': hit['date_of_birth'],
                    'category': hit.get('category'),
                    'position': hit.get('position'),
                    'national_id': hit.get('national_id'),
                    'is_internal': True,
                    '_mi_scored': bool(hit.get('_name_match')),
                    'details': {
                        'reason': hit['reason'],
                        'category': hit.get('category'),
                        'position': hit.get('position'),
                        'notes': hit.get('notes')
                    },
                    'score_breakdown': {
                        'fuzzy_ratio': round(float(pep_score), 2),
                        'phonetic': 0.0,
                        'jaro_winkler': round(float(pep_jw) * 100, 2)
                    }
                }
                internal_matches.append(pep_match)

        if internal_hits:
            # Format internal hits as matches with actual fuzzy scoring
            for hit in internal_hits:
                hit_name_en = (hit.get('full_name') or '').lower()
                hit_name_ar = (hit.get('original_name') or '').lower()
                target_name = name.lower()
                
                # Use _match_score from NLP normalizer (bidirectional Jaro-Winkler)
                bl_score = round(hit.get('_match_score', 0) * 100, 2)
                bl_jw = hit.get('_match_score', 0)
                hit_name = hit_name_ar if self._is_arabic(target_name) and hit_name_ar else (hit.get('full_name') or hit.get('original_name') or '')

                if bl_score < self.LOW_MATCH_THRESHOLD:
                    continue

                match = {
                    'entity_id': hit['id'],
                    'full_name': hit_name,
                    'watchlist_name_ar': hit['original_name'],
                    'entity_type': hit['entity_type'],
                    'match_score': round(float(bl_score), 2),
                    'reason': hit['reason'],
                    'risk_level': hit['risk_level'],
                    'source': 'INTERNAL_BLACKLIST',
                    'source_name': 'Internal Blacklist',
                    'list_type': 'SANCTIONS',
                    'dataset': 'Internal Blacklist',
                    'watchlist_id': hit['source_id'],
                    'source_id': hit['source_id'],
                    'nationality': hit['nationality'],
                    'date_of_birth': hit['date_of_birth'],
                    'category': hit['category'],
                    'national_id': hit.get('national_id'),
                    'is_internal': True,
                    '_mi_scored': bool(hit.get('_name_match')),
                    'details': {
                        'reason': hit['reason'],
                        'category': hit['category'],
                        'notes': hit['notes']
                    },
                    'score_breakdown': {
                        'fuzzy_ratio': round(float(bl_score), 2),
                        'phonetic': 0.0,
                        'jaro_winkler': round(float(bl_jw) * 100, 2)
                    }
                }
                internal_matches.append(match)

        # Detect if Arabic
        is_arabic = self._is_arabic(name)
        
        # Process name based on script
        english_variants: list[str] = []
        if is_arabic:
            english_variants = generate_english_variants(name)
            if not processed_name and english_variants:
                processed_name = self._normalize_english(english_variants[0])
        
        # --- ADVANCED FEATURE EXTRACTION (for ML) ---
        t_ml = time.time()
        network_score = 0.0
        tx_velocity_score = 0.0
        tenure_days = 0
        media_risk_score = 0.0
        adverse_media_info = {}
        adverse_media_hits = []

        if self.media_screener and include_media:
            # ADVERSE MEDIA IS NOW DETACHED FROM SYNCHRONOUS RUNTIME.
            # It is fetched progressively via /api/screening/adverse_media/
            adverse_media_info = {
                'risk_level': 'PENDING',
                'risk_score': 0,
                'total_hits': 0,
                'recommendation': 'Media screening running in background...'
            }
            adverse_media_hits = []
            media_risk_score = 0.0

        # Optimization: Try to find if this person is an existing customer for features
        customer_info = None
        try:
            # Re-check db connection just in case
            if not self.db_conn: self.connect_db()
            assert self.db_conn is not None
            cur = self.db_conn.cursor()
            cur.execute("SELECT id, onboarding_date FROM customers WHERE full_name = %s OR full_name_arabic = %s LIMIT 1", (name, name))
            customer_info = cur.fetchone()
        except Exception as e:
            logger.warning(f"Feature extraction lookup failed: {e}")

        if customer_info:
            cust_id = customer_info['id']
            if customer_info['onboarding_date']:
                try:
                    onboard_dt = datetime.fromisoformat(customer_info['onboarding_date'].split('T')[0])
                    tenure_days = (datetime.now() - onboard_dt).days
                except: pass
            
            if self.network_analyzer:
                hidden_risks = self.network_analyzer.detect_hidden_risk(cust_id)
                if hidden_risks:
                    network_score = max(r['target_risk'] / (r['hops'] or 1) for r in hidden_risks)

            # FORMAL DEFERRAL (2026-07-21, screening Rec #7, approved by
            # Compliance): the transaction-velocity feature reads
            # customer_transactions, which currently contains only orphaned
            # demo rows with no linkage to real customers - there is no real
            # transaction feed yet. Rather than let a scoring feature
            # silently read an empty/demo table (implying a control that
            # does not exist), it is explicitly disabled until a real feed
            # is connected. Re-enable by setting TX_MONITORING_ENABLED=true
            # in the environment once customer_transactions is fed from
            # production payment data with a defined customer-ID mapping.
            if self.tx_analyzer and os.getenv('TX_MONITORING_ENABLED', 'false').lower() == 'true':
                try:
                    # customer_transactions.customer_id is TEXT while
                    # customers.id is INTEGER - cast explicitly so this
                    # comparison is well-typed regardless of the Python
                    # value's native type (was previously always failing
                    # with "operator does not exist: text = integer" on
                    # every screening that matched an existing customer,
                    # silently zeroing this AML feature - see Task #71).
                    cur.execute("SELECT amount, timestamp FROM customer_transactions WHERE customer_id = %s", (str(cust_id),))
                    transactions = [dict(tx) for tx in cur.fetchall()]
                    alerts = self.tx_analyzer.analyze_transactions(cust_id, transactions)
                    if alerts:
                        severity_map = {'HIGH': 100, 'MEDIUM': 50, 'LOW': 25}
                        tx_velocity_score = max(severity_map.get(a['severity'], 0) for a in alerts)
                except Exception as e:
                    logger.error(f"Tx feature extraction failed for customer_id={cust_id!r}: {e}", exc_info=True)

        adv_features = {
            'network_score': network_score,
            'tx_velocity_score': tx_velocity_score,
            'media_risk_score': media_risk_score,
            'tenure_days': tenure_days
        }

        logger.debug(f"[TIMER] ML inference: {round((time.time()-t_ml)*1000)}ms")

        # Normalize name (reuse processed_name from earlier)
        normalized_name = processed_name
        
        # Enhanced Processing: Arabizi & Prefixes & Variants
        t_variants = time.time()
        search_variations = set()
        if processed_name:
            search_variations.add(processed_name)
        
        # 1. Arabizi Handling
        if processed_name and re.search(r'[235789]', processed_name):
            arabizi_normalized = normalize_arabizi(processed_name)
            if arabizi_normalized != processed_name:
                search_variations.add(arabizi_normalized)
                
        # 2. Prefix Handling (Applied to all variations)
        # Snapshot list to iterate safely
        for n in list(search_variations):
            prefixed = normalize_prefixes(n)
            if prefixed != n:
                search_variations.add(prefixed)
                
        # 2b. Compound Translation (e.g. "Abdel" vs "Abd el")
        for n in list(search_variations):
            compounds = generate_compound_variants(n)
            search_variations.update(compounds)

        # 3. Reverse English Variants (e.g. Gamal -> Jamal)
        for n in list(search_variations):
            others = get_english_variants(n)
            search_variations.update(others)

        # Add to english_variants
        if is_arabic:
            # Add novel variations to existing list
            existing_set = set(english_variants)
            for v in search_variations:
                if v not in existing_set:
                    english_variants.append(v)
        else:
            # For non-Arabic, these are our variants
            english_variants = list(search_variations)

        # 4. Reverse Transliteration: English -> Arabic variants
        # This enables matching English input against Arabic-stored DB entries
        arabic_variants: list[str] = []
        if not is_arabic:
            arabic_variants = generate_arabic_variants(name)
            if arabic_variants:
                logger.info(f"Generated {len(arabic_variants)} Arabic variants for English input")

        logger.debug(f"[TIMER] Variant generation: {round((time.time()-t_variants)*1000)}ms")
        
        logger.info(f"Screening: {name} (Type: {entity_type}, Variants: {len(english_variants)})")

        # Generate phonetic codes used in recall
        # Use primary English translation for Arabic soundex
        # Add known Arabic→English transliteration variants for common names
        KNOWN_ARABIC_EN_VARIANTS = {
            'osama': ['usamah', 'usama', 'oussama', 'ossama'],
            'usamah': ['osama', 'usama', 'oussama'],
            'usama': ['osama', 'usamah', 'oussama'],
            'mohamad': ['muhammad', 'mohammed', 'mohammad', 'mohamed'],
            'muhammad': ['mohamad', 'mohammed', 'mohammad', 'mohamed'],
            'abdel': ['abdelmalek', 'abdelouadoud', 'abdel', 'abd al', 'abd el'],
            'abdelmalek': ['abdel malek', 'abd al-malik', 'abd el malik'],
            'droukdel': ['droukdal', 'drokdal', 'drukdal', 'droukadal'],
            'baghdadi': ['al-baghdadi', 'albaghdadi', 'bagdadi'],
            'zarqawi': ['al-zarqawi', 'alzarqawi', 'zarkawi'],
        }
        pn_lower = processed_name.lower() if processed_name else ''
        for base_word, variants in KNOWN_ARABIC_EN_VARIANTS.items():
            if base_word in pn_lower:
                for v in variants:
                    expanded = pn_lower.replace(base_word, v)
                    if expanded not in [e.lower() for e in english_variants]:
                        english_variants.append(expanded.upper())

        phonetic_base = english_variants[0] if is_arabic and english_variants else processed_name
        
        soundex_code = jellyfish.soundex(phonetic_base) if phonetic_base else None
        metaphone_code = jellyfish.metaphone(phonetic_base) if phonetic_base else None
        
        # PHASE 1: Candidate Recall (Optimization)
        # Note: whitelist check already done
            
        candidates = self._recall_candidates(
            processed_name, 
            english_variants,
            soundex_code,
            metaphone_code,
            entity_type,
            country=nationality,
            is_arabic=is_arabic,
            arabic_variants=arabic_variants
        )
        
        # 2. Precision Phase (Scoring)
        import time
        logger.debug("[Precision scoring started: {len(candidates)} candidates")
        t3 = time.time()
        
        # _precision_scoring takes list of candidates and returns list of matches
        matches = self._precision_scoring(
            candidates,
            name,
            processed_name, 
            date_of_birth, 
            nationality,
            entity_type,
            english_variants,
            address,
            adv_features,
            is_arabic=is_arabic,
            arabic_variants=arabic_variants,
            national_id=national_id,
            employer=employer
        )
        
        logger.debug(f"[TIMER] Scoring loop: {round((time.time()-t3)*1000)}ms")
        
        matches = self._structural_rescue(name, candidates, matches)
        matches = [m for m in matches if m['match_score'] >= self.LOW_MATCH_THRESHOLD]
        
        # Merge internal blacklist matches (if any) with watchlist matches.
        # These arrive pre-scored from the service layer (bidirectional
        # Jaro-Winkler) and never pass through _calculate_precision_scores, so
        # the name-structure rules have to be applied here or they do not apply
        # to internal lists at all.
        if internal_matches:
            internal_matches = self._apply_name_logic_to_internal(
                name, internal_matches)
            internal_matches = [
                m for m in internal_matches
                if m['match_score'] >= self.LOW_MATCH_THRESHOLD
            ]
            matches.extend(internal_matches)
        
        # Analyst decision layer (screening/match_intel.py): identifiers
        # (national ID incl. the birth date it encodes, DOB, nationality) and
        # the structure of the name decide the tier; a partial or short-form
        # name never auto-confirms; the same listed person is shown once.
        try:
            from screening import match_intel as _mi
            matches = _mi.apply_decisions(matches, name, national_id=national_id,
                                          dob=date_of_birth, nationality=nationality)
            matches = [m for m in matches if m['match_score'] >= self.LOW_MATCH_THRESHOLD]
        except Exception as _e:
            logger.warning(f"[MATCH-INTEL] decision layer failed: {_e}")
            _mi = None

        # Sort matches by score desc
        matches.sort(key=lambda x: x['match_score'], reverse=True)
        
        highest_score = matches[0]['match_score'] if matches else 0.0
        
        # Determine result
        result_status = 'CLEAR'
        if _mi is not None:
            result_status = _mi.overall_status(matches)
        elif highest_score >= self.CONFIRMED_HIT_THRESHOLD:
            result_status = 'CONFIRMED_HIT'
        elif highest_score >= self.POTENTIAL_MATCH_THRESHOLD:
            result_status = 'POTENTIAL_MATCH'
        elif highest_score >= self.LOW_MATCH_THRESHOLD:
            result_status = 'LOW_MATCH'
        
        # Escalate status if Adverse Media found
        if adverse_media_hits and result_status == 'CLEAR':
            result_status = 'REVIEW_REQUIRED'

        result = {
            'screening_result': result_status,
            'matches': matches,
            'adverse_media': adverse_media_hits,
            'adverse_media_summary': {
                'risk_level': adverse_media_info.get('risk_level', 'CLEAR'),
                'risk_score': adverse_media_info.get('risk_score', 0),
                'total_hits': adverse_media_info.get('total_hits', 0),
                'recommendation': adverse_media_info.get('recommendation', '')
            },
            'match_count': len(matches),
            'low_candidate_count': getattr(self, 'low_candidate_count', False),
            'adverse_media_count': len(adverse_media_hits),
            'total_matches': len(matches),
            'highest_score': highest_score,
            'processing_time_ms': int((datetime.now() - start_time).total_seconds() * 1000),
            'from_cache': False,
            'search_degraded': bool(getattr(self, 'es_degraded', False)),
            'total_candidates': len(candidates) if 'candidates' in locals() else 0
        }
        
        # --- REDIS CACHE COMMIT: INTENTIONALLY DISABLED (2026-07-20) ---
        # See matching note at the cache-read checkpoint above. cache_key is
        # always None now, so this block is dead by construction; left in
        # place (rather than deleted) so the historical intent is auditable
        # and a future, properly-versioned cache can be re-added deliberately.
        if REDIS_AVAILABLE and _redis_client and not is_internal_blacklist and cache_key:
            try:
                ttl = int(os.getenv('REDIS_CACHE_TTL_SECONDS', 3600))
                _redis_client.setex(cache_key, ttl, json.dumps(result, default=str))
                logger.info(f"[CACHE] Result cached in Redis for: {name}")
            except Exception as e:
                logger.error(f"Redis cache write error: {e}")
        
        # Log Metrics (Async)
        t_met = time.time()
        self.metrics.log(result, name, entity_type)
        logger.debug(f"[TIMER] Metrics log trigger: {round((time.time()-t_met)*1000)}ms")
                
        return result
    
    def _is_arabic(self, text):
        """Detect if text contains Arabic characters"""
        if not text:
            return False
        arabic_pattern = re.compile(r'[\u0600-\u06FF]')
        return bool(arabic_pattern.search(text))
    
    def _normalize_english(self, name):
        """Normalize English name"""
        if not name:
            return ""
        
        STOP_WORDS = {
            'MR', 'MRS', 'MS', 'MISS', 'DR', 'PROF', 'SIR', 'LADY', 'LORD',
            'COLONEL', 'COL', 'GENERAL', 'GEN', 'CAPTAIN', 'CAPT',
            'THE', 'AND', 'OF', 'LLC', 'INC', 'LTD', 'CORP', 'CO',
            'EL', 'AL', 'BIN', 'IBN', 'BEN', 'ABU'
        }
        
        PHONETIC_MAP = {
            'HUSSAIN': 'HUSSEIN', 'HUSSIEN': 'HUSSEIN',
            'AHMAD': 'AHMED', 'AHMET': 'AHMED',
            'MOHAMED': 'MOHAMED', 'MOHAMMAD': 'MOHAMED', 'MOHAMMED': 'MOHAMED', 'MOHAMAD': 'MOHAMED', 'MUHAMMAD': 'MOHAMED',
            'MUSTAFA': 'MUSTAFA', 'MOSTAFA': 'MUSTAFA', 'MOUSTAFA': 'MUSTAFA',
            'ABD': 'ABD', 'ABDEL': 'ABD', 'ABDUL': 'ABD', 'ABDE': 'ABD',
            'KHALED': 'KHALID', 'HALED': 'KHALID',
            'OMAR': 'OMAR', 'OMER': 'OMAR', 'UMAR': 'OMAR',
            'YOUSSEF': 'YOUSSEF', 'YUSUF': 'YOUSSEF', 'YOUSEF': 'YOUSSEF', 'JOSEF': 'YOUSSEF'
        }
        
        name_upper = name.upper()
        tokens: list[str] = name_upper.split()
        
        # Apply phonetic map first, then filter stop words
        normalized_tokens = [PHONETIC_MAP.get(t, t) for t in tokens if t not in STOP_WORDS]
        
        processed = ' '.join(normalized_tokens)
        processed = ''.join(c for c in processed if c.isalnum() or c.isspace())
        processed = ' '.join(processed.split())
        
        return processed.strip()
    
    def _search_elasticsearch(self, name: str, country: str = None, english_variants: list = None,
                               arabic_variants: list = None) -> list:
        """
        Search complynex_watchlist via Elasticsearch.
        Returns list of candidate dicts matching the schema expected by _precision_scoring.
        Supports bilingual search: Arabic input is searched against Arabic alias fields AND
        English transliteration variants are searched against Latin name fields simultaneously.
        For English/Latin input, arabic_variants (reverse-transliterated by
        generate_arabic_variants) are likewise searched against the Arabic
        fields — previously this direction was retrieval-blind: a record that
        exists only in Arabic (e.g. most of the Iraq AML list) could never be
        retrieved by an English-script query at all, since the plain
        multi_match below only ever touched Latin fields.
        """
        if not ES_AVAILABLE or not _es_client:
            # ES layer completely unavailable - recall quality is degraded
            # (trigram-only). Flag it so the result carries the warning.
            self.es_degraded = True
            return []

        try:
            # Detect Arabic input
            is_arabic_input = any('\u0600' <= c <= '\u06FF' for c in (name or ''))

            # FIX 1: Build bilingual "should" query so Arabic input searches both
            # the original Arabic aliases AND the English transliteration variants
            # simultaneously, preventing zero-results for cross-script searches.
            should_clauses = []

            if is_arabic_input:
                # Clause A: search Arabic name against Arabic alias fields
                should_clauses.append({
                    "multi_match": {
                        "query": name,
                        "fields": ["aliases_arabic^5", "full_name_arabic^4", "name_ar^3", "aliases^2"],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                        "minimum_should_match": "50%"
                    }
                })
                # Clause B: search English transliterations against Latin name fields
                for variant in (english_variants or [])[:5]:
                    if variant and variant.strip():
                        should_clauses.append({
                            "multi_match": {
                                "query": variant,
                                "fields": ["original_name^4", "name_normalized^3", "full_name^2", "aliases^1"],
                                "type": "best_fields",
                                "fuzziness": "AUTO",
                                "minimum_should_match": "60%"
                            }
                        })
                # Fallback: also search the Arabic-normalised form against general fields
                should_clauses.append({
                    "multi_match": {
                        "query": name,
                        "fields": ["original_name^2", "name_normalized^1"],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                        "minimum_should_match": "50%"
                    }
                })
            else:
                # Non-Arabic input: standard multi-match across Latin fields
                should_clauses.append({
                    "multi_match": {
                        "query": name,
                        "fields": ["original_name^4", "name_normalized^3", "full_name^2", "aliases^1"],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                        "minimum_should_match": "60%"
                    }
                })
                # Clause B (symmetric with the Arabic-input branch above):
                # search reverse-transliterated Arabic variants against the
                # Arabic fields, so an Arabic-only record can be retrieved
                # by an English-script query.
                for ar_variant in (arabic_variants or [])[:5]:
                    if ar_variant and ar_variant.strip():
                        should_clauses.append({
                            "multi_match": {
                                "query": ar_variant,
                                "fields": ["aliases_arabic^5", "full_name_arabic^4", "name_ar^3"],
                                "type": "best_fields",
                                "fuzziness": "AUTO",
                                "minimum_should_match": "50%"
                            }
                        })

            query = {
                "size": 150 if country or is_arabic_input else 100,
                "query": {
                    "bool": {
                        "should": should_clauses,
                        "minimum_should_match": 1,
                        "filter": [],
                        # Internal lists are searched directly in PostgreSQL
                        # (match_intel.search_internal) — always current. Their
                        # ES mirror was a stale snapshot that produced ghost
                        # and duplicate hits. Inactive / delisted records never match.
                        "must_not": [
                            {"terms": {"source": ["internal_blacklist", "internal_pep"]}},
                            {"term": {"is_active": 0}}
                        ]
                    }
                }
            }

            import os
            index_wl = os.getenv('ES_INDEX_WATCHLIST', 'aml_watchlist')
            index_bl = os.getenv('ES_INDEX_BLACKLIST', 'aml_watchlist')

            response = _es_client.search(index=f"{index_wl},{index_bl}", body=query, ignore_unavailable=True)
            hits = response.get("hits", {}).get("hits", [])

            candidates = []
            pg_ids = []
            for hit in hits:
                src = hit["_source"]
                # FIX 2 (part a): use 'id' or 'watchlist_id' — the ES index stores the
                # PostgreSQL primary key under 'id', not 'db_id'.
                db_id = src.get('id') or src.get('watchlist_id')
                candidate = {
                    'id': str(db_id) if db_id else hit.get('_id'),
                    '_pg_id': int(db_id) if db_id else None,
                    'full_name': src.get('full_name', ''),
                    'original_name': src.get('original_name') or src.get('full_name', ''),
                    'name_normalized': src.get('name_normalized', '') or (src.get('original_name') or src.get('full_name', '')).lower(),
                    'dataset': src.get('dataset') or src.get('source', 'UNKNOWN'),
                    'list_type': src.get('list_type') or ('PEP' if src.get('source') in ('internal_pep', 'opensanctions_pep') else 'SANCTIONS'),
                    'topics': src.get('topics', ''),
                    'countries': src.get('countries', ''),
                    'date_of_birth': src.get('date_of_birth', ''),
                    'year_of_birth': src.get('year_of_birth', ''),
                    'nationality': src.get('nationality', ''),
                    'source_url': src.get('source_url', ''),
                    'risk_level': src.get('risk_level', 'HIGH'),
                    'aliases': src.get('aliases', '') or src.get('search_names', ''),
                    'aliases_arabic': src.get('aliases_arabic', ''),
                    'full_name_arabic': src.get('full_name_arabic', '') or '',
                    'entity_type': src.get('entity_type', 'INDIVIDUAL'),
                    'national_id_numbers': src.get('national_id_numbers', '') or src.get('national_id', ''),
                    'properties': src.get('properties', '{}') or '{}',
                    'source': src.get('source', 'UNKNOWN'),
                    'trgm_score': hit.get('_score', 0.0) / 10.0,
                    'semantic_score': 0.0,
                    'es_score': hit.get("_score", 0.0)
                }
                candidates.append(candidate)
                if db_id:
                    pg_ids.append(int(db_id))

            # FIX 2 (part b): Enrich candidates with full PostgreSQL data.
            # ES may have stale or partial fields (especially 'properties', 'topics',
            # 'countries', 'date_of_birth').  A single batch lookup keeps it fast.
            if pg_ids:
                try:
                    with db_pool.get_connection() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            """SELECT id, properties, details, topics, countries, date_of_birth,
                                      year_of_birth, nationality, source_url,
                                      national_id_numbers, risk_level, entity_type,
                                      list_type, aliases, aliases_arabic, original_name, full_name
                               FROM screening_watchlist
                               WHERE id = ANY(%s)""",
                            (pg_ids,)
                        )
                        pg_rows = {row['id']: dict(row) for row in cur.fetchall()}

                    for cand in candidates:
                        pg_id = cand.get('_pg_id')
                        if pg_id and pg_id in pg_rows:
                            row = pg_rows[pg_id]
                            # Prefer PostgreSQL values for fields that may be stale in ES
                            cand['properties'] = row.get('properties') or cand['properties'] or '{}'
                            cand['topics'] = row.get('topics') or cand['topics'] or ''
                            cand['countries'] = row.get('countries') or cand['countries'] or ''
                            cand['date_of_birth'] = row.get('date_of_birth') or cand['date_of_birth'] or ''
                            cand['year_of_birth'] = row.get('year_of_birth') or cand['year_of_birth'] or ''
                            cand['nationality'] = row.get('nationality') or cand['nationality'] or ''
                            cand['source_url'] = row.get('source_url') or cand['source_url'] or ''
                            cand['national_id_numbers'] = row.get('national_id_numbers') or cand['national_id_numbers'] or ''
                            cand['risk_level'] = row.get('risk_level') or cand['risk_level'] or 'HIGH'
                            cand['entity_type'] = row.get('entity_type') or cand['entity_type'] or 'INDIVIDUAL'
                            cand['aliases_arabic'] = row.get('aliases_arabic') or cand.get('aliases_arabic') or ''
                            # Set after the fields above so a computed fallback (nationality/
                            # DOB/topics) can use their final, enriched values.
                            cand['details'] = (extract_bio_snippet(row.get('details'))
                                                or extract_bio_snippet(cand.get('details'))
                                                or compute_fallback_bio(cand) or '')
                except Exception as enrich_err:
                    logger.warning(f"[ES] PostgreSQL enrichment failed (non-fatal): {enrich_err}")

            # Remove internal helper key
            for cand in candidates:
                cand.pop('_pg_id', None)

            logger.info(f"[ES] Returned {len(candidates)} candidates for: {name}")
            return candidates

        except Exception as e:
            logger.error(f"[ES] Search failed: {e}")
            # Recall will fall back to trigram-only - mark this screening
            # as degraded so the saved result and UI carry the warning
            # instead of silently looking identical to a full search.
            self.es_degraded = True
            return []

    def _recall_candidates(self, processed_name, english_variants, 
                          soundex, metaphone, entity_type, country=None, is_arabic=False, arabic_variants=None) -> list:
        import time
        t0 = time.time()
        all_candidates = []
        seen_ids = set()
        # Reset the degraded-search marker for this screening; set again only
        # if the ES layer actually fails during this recall (Rec #2).
        self.es_degraded = False

        # ES and semantic recall are independent I/O (two local HTTP
        # services) — kick the semantic search off first so it runs
        # concurrently with the ES query instead of strictly after it
        # (sequential cost was the sum, 0.2-3s worse per screen). Only the
        # HTTP search overlaps; the PostgreSQL enrichment of its hits stays
        # on this thread, so no db_pool connection crosses threads.
        sem_thread = None
        sem_out = {}
        if getattr(self, 'semantic_matcher', None) and self.semantic_matcher.enabled:
            import threading

            def _sem_search():
                try:
                    sem_out['results'] = self.semantic_matcher.search_index(
                        processed_name, top_k=25, country=country)
                except Exception as e:  # surfaced after join, same as the old inline call
                    sem_out['error'] = e
            sem_thread = threading.Thread(target=_sem_search, daemon=True)
            sem_thread.start()

        # PRIMARY: Elasticsearch
        # Normalize Arabic before querying — expand عبدالحليم → عبد الحليم
        import re as _rec_re
        _es_name = processed_name
        if is_arabic:
            _es_name = _rec_re.sub(
                r'عبدال([\u0600-\u06FF])',
                lambda m: 'عبد ال' + m.group(1),
                processed_name or ''
            )
            _es_name = _rec_re.sub(r'[أإآٱ]', 'ا', _es_name)
            _es_name = _rec_re.sub(r' {2,}', ' ', _es_name).strip()
        # Pass english_variants/arabic_variants so the ES query builds bilingual "should" clauses
        es_candidates = self._search_elasticsearch(
            _es_name, country,
            english_variants=english_variants if is_arabic else None,
            arabic_variants=arabic_variants if not is_arabic else None,
        )
        # If normalized form returned nothing, retry with original
        if not es_candidates and _es_name != processed_name:
            es_candidates = self._search_elasticsearch(
                processed_name, country,
                english_variants=english_variants if is_arabic else None,
                arabic_variants=arabic_variants if not is_arabic else None,
            )
        for c in es_candidates:
            cid = c.get("id")
            if cid not in seen_ids:
                seen_ids.add(cid)
                all_candidates.append(c)
        logger.info(f"[TIMER] ES recall: {round((time.time()-t0)*1000)}ms — {len(es_candidates)} candidates")

        # SECONDARY: FAISS semantic (started before the ES query — collect it)
        t1 = time.time()
        try:
            faiss_candidates = []
            s_results = []
            if sem_thread is not None:
                # The client caps its own HTTP call at SEARCH_TIMEOUT_S; this
                # join timeout is just a backstop so a wedged thread can't
                # hang the screen — we proceed without semantic candidates.
                sem_thread.join(timeout=8.0)
                if sem_thread.is_alive():
                    logger.warning("[FAISS] semantic search thread still running after 8s — skipping")
                elif 'error' in sem_out:
                    raise sem_out['error']
                else:
                    s_results = sem_out.get('results') or []
            if s_results:
                # search_index() returns bare {'id', 'semantic_score'} — the
                # index only stores ids now (see semantic_matcher.py), so
                # enrich the actual hits (at most 25, not all 2.5M+ records)
                # from PostgreSQL in one batched lookup per source table,
                # same pattern as the ES enrichment above. This also fixes
                # semantic-sourced candidates previously always carrying
                # blank date_of_birth/nationality/properties — those fields
                # never had anywhere to come from when this branch built
                # candidates straight out of the old in-memory metadata file.
                #
                # The index covers all three lists the engine screens
                # against (screening_watchlist, internal_pep,
                # internal_blacklist) in one shared FAISS index — internal
                # lists are not a separate, semantic-search-blind pathway.
                # Each hit's id carries a namespace offset (see
                # semantic_matcher.py's WATCHLIST_ID_OFFSET /
                # INTERNAL_PEP_ID_OFFSET / INTERNAL_BLACKLIST_ID_OFFSET —
                # the three tables have independently-sequenced integer ids
                # that would otherwise collide) — decode it back to route
                # each hit at the table it actually came from.
                score_by_id = {r['id']: r['semantic_score'] for r in s_results}

                watchlist_ids, pep_ids, blacklist_ids = [], [], []
                for sem_id in score_by_id:
                    if sem_id >= INTERNAL_BLACKLIST_ID_OFFSET:
                        blacklist_ids.append(sem_id - INTERNAL_BLACKLIST_ID_OFFSET)
                    elif sem_id >= INTERNAL_PEP_ID_OFFSET:
                        pep_ids.append(sem_id - INTERNAL_PEP_ID_OFFSET)
                    else:
                        watchlist_ids.append(sem_id - WATCHLIST_ID_OFFSET)
                from utils.demo import is_demo
                if is_demo():
                    # the shared semantic index holds the MAIN instance's internal
                    # lists; a demo has its own (searched directly in its database)
                    pep_ids, blacklist_ids = [], []

                if (watchlist_ids or pep_ids or blacklist_ids) and self.db_type == 'postgresql':
                    try:
                        with db_pool.get_connection() as conn:
                            cur = conn.cursor()

                            if watchlist_ids:
                                cur.execute(
                                    """SELECT id, full_name, name_normalized, dataset, list_type,
                                              topics, countries, date_of_birth, year_of_birth,
                                              nationality, source_url, national_id_numbers,
                                              risk_level, entity_type, properties, details, source,
                                              original_name, aliases, aliases_arabic
                                       FROM screening_watchlist
                                       WHERE id = ANY(%s) AND is_active = 1""",
                                    (watchlist_ids,)
                                )
                                for row in cur.fetchall():
                                    candidate = dict(row)
                                    orig_id = candidate['id'] + WATCHLIST_ID_OFFSET
                                    candidate['id'] = str(candidate['id'])
                                    candidate['trgm_score'] = score_by_id[orig_id] / 100.0
                                    candidate['semantic_score'] = score_by_id[orig_id]
                                    candidate['is_semantic'] = True
                                    candidate['details'] = (extract_bio_snippet(candidate.get('details'))
                                                             or compute_fallback_bio(candidate))
                                    faiss_candidates.append(candidate)

                            if pep_ids:
                                cur.execute(
                                    """SELECT id, full_name, original_name, entity_type, reason,
                                              risk_level, nationality, date_of_birth, category,
                                              position, source_id
                                       FROM internal_pep
                                       WHERE id = ANY(%s) AND COALESCE(is_active, 1) != 0""",
                                    (pep_ids,)
                                )
                                for row in cur.fetchall():
                                    orig_id = row['id'] + INTERNAL_PEP_ID_OFFSET
                                    faiss_candidates.append({
                                        'id': str(orig_id), 'full_name': row['full_name'],
                                        'name_normalized': row['full_name'], 'original_name': row['original_name'],
                                        'aliases_arabic': '', 'aliases': '',
                                        'dataset': 'Internal PEP', 'list_type': 'PEP',
                                        'topics': '', 'countries': '',
                                        'date_of_birth': row['date_of_birth'], 'year_of_birth': '',
                                        'nationality': row['nationality'], 'source_url': '',
                                        'national_id_numbers': '', 'risk_level': row['risk_level'],
                                        'entity_type': row['entity_type'], 'properties': '{}',
                                        'source': 'INTERNAL_PEP', 'source_name': 'Internal PEP List',
                                        'watchlist_id': row['source_id'], 'source_id': row['source_id'],
                                        'category': row['category'], 'position': row['position'],
                                        'reason': row['reason'], 'is_internal': True,
                                        'trgm_score': score_by_id[orig_id] / 100.0,
                                        'semantic_score': score_by_id[orig_id], 'is_semantic': True,
                                    })

                            if blacklist_ids:
                                cur.execute(
                                    """SELECT id, full_name, original_name, entity_type, reason,
                                              risk_level, nationality, date_of_birth, category,
                                              source_id
                                       FROM internal_blacklist
                                       WHERE id = ANY(%s) AND COALESCE(is_active, 1) != 0""",
                                    (blacklist_ids,)
                                )
                                for row in cur.fetchall():
                                    orig_id = row['id'] + INTERNAL_BLACKLIST_ID_OFFSET
                                    faiss_candidates.append({
                                        'id': str(orig_id), 'full_name': row['full_name'],
                                        'name_normalized': row['full_name'], 'original_name': row['original_name'],
                                        'aliases_arabic': '', 'aliases': '',
                                        'dataset': 'Internal Blacklist', 'list_type': 'SANCTIONS',
                                        'topics': '', 'countries': '',
                                        'date_of_birth': row['date_of_birth'], 'year_of_birth': '',
                                        'nationality': row['nationality'], 'source_url': '',
                                        'national_id_numbers': '', 'risk_level': row['risk_level'],
                                        'entity_type': row['entity_type'], 'properties': '{}',
                                        'source': 'INTERNAL_BLACKLIST', 'source_name': 'Internal Blacklist',
                                        'watchlist_id': row['source_id'], 'source_id': row['source_id'],
                                        'category': row['category'], 'reason': row['reason'],
                                        'is_internal': True,
                                        'trgm_score': score_by_id[orig_id] / 100.0,
                                        'semantic_score': score_by_id[orig_id], 'is_semantic': True,
                                    })
                    except Exception as enrich_err:
                        logger.warning(f"[FAISS] PostgreSQL enrichment failed: {enrich_err}")

            for c in faiss_candidates:
                cid = c.get("id")
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    all_candidates.append(c)
            logger.info(f"[TIMER] FAISS recall: {round((time.time()-t1)*1000)}ms — {len(faiss_candidates)} candidates")
        except Exception as e:
            logger.warning(f"[FAISS] Search failed: {e}")

        # FALLBACK: PostgreSQL — only if ES returned zero results
        if len(es_candidates) == 0:
            logger.warning(f"[FALLBACK] ES returned {len(es_candidates)} results — running PostgreSQL fallback")
            t2 = time.time()
            sqlite_candidates = self._search_sqlite(
                processed_name, english_variants, soundex, metaphone,
                entity_type, country, is_arabic, arabic_variants
            )
            for c in sqlite_candidates:
                key = str(c.get("id")) if isinstance(c, dict) else str(c['id'])
                if key not in seen_ids:
                    seen_ids.add(key)
                    c_dict = dict(c) if hasattr(c, 'keys') else c
                    all_candidates.append(c_dict)
            logger.info(f"[TIMER] PostgreSQL fallback: {round((time.time()-t2)*1000)}ms — {len(sqlite_candidates)} candidates")

        logger.info(f"[RECALL] Total unique candidates: {len(all_candidates)}")
        return all_candidates

    def _search_sqlite(self, processed_name, english_variants, 
                          soundex, metaphone, entity_type, country=None, is_arabic=False, arabic_variants=None):
        # --- SQLITE SLOW PATH (Fallback) ---
        import time
        t2 = time.time()
        if self.db_type == 'postgresql':
            from psycopg2.extras import RealDictCursor
            cursor = getattr(self, 'db_conn', None).cursor(cursor_factory=RealDictCursor) if getattr(self, 'db_conn', None) else None
            if not cursor:
                self.connect_db()
                cursor = self.db_conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = getattr(self, 'db_conn', None).cursor() if getattr(self, 'db_conn', None) else None
            if not cursor:
                self.connect_db()
                cursor = self.db_conn.cursor()
        
        conditions = []
        params = []
        
        is_arabic = any('\u0600' <= c <= '\u06FF' for c in processed_name) if processed_name else False
        use_trigram = (self.db_type == 'postgresql')
        
        trgm_threshold = 0.3
        
        name_len = len(processed_name) if processed_name else 0
        len_min = max(1, name_len // 2)
        len_max = name_len * 3 
        MAX_CONDITIONS = 15
        
        if use_trigram:
            # ─── PostgreSQL: pg_trgm + tsvector hybrid recall ───
            # Uses the % operator (GIN trigram indexes) + full-text search
            # and similarity() for scoring/ordering
            
            # Set session-level similarity threshold
            try:
                cursor.execute(f"SET pg_trgm.similarity_threshold = {trgm_threshold};")
            except Exception:
                pass # Non-critical, % operator will use default
            
            if processed_name:
                # Core trigram searches (highest value, always include)
                conditions.append(f"name_normalized %% {self.placeholder}")
                params.append(processed_name)
                
                conditions.append(f"full_name %% {self.placeholder}")
                params.append(processed_name)

                # aliases column is empty - skip trigram on it

                # For aliases_arabic, use original Arabic name if available
                _arabic_query = arabic_variants[0] if arabic_variants and not is_arabic else processed_name
                conditions.append(f"aliases_arabic %% {self.placeholder}")
                params.append(_arabic_query if _arabic_query else processed_name)
                
                # Full-text search skipped - search_vector not in screening_watchlist
                
                if is_arabic:
                    conditions.append(f"original_name %% {self.placeholder}")
                    params.append(processed_name)

                    # Arabic compound variant: add opposite spacing form
                    # so عبدالحليم (unspaced) also hits عبد الحليم (spaced DB entries)
                    import re as _re
                    _pn = processed_name or ''
                    _alt = _re.sub(r'عبدال([\u0600-\u06FF])', r'عبد ال\1', _pn)  # unspaced→spaced
                    if _alt == _pn:                                                    # already spaced
                        _alt = _re.sub(r'عبد\s+ال', 'عبدال', _pn)                  # spaced→unspaced
                    if _alt and _alt != _pn and len(conditions) < MAX_CONDITIONS:
                        conditions.append(f"original_name %% {self.placeholder}")
                        params.append(_alt)

                    # Enhanced Arabic normalization - search all variants
                    if globals().get('ARABIC_ENHANCED', False):
                        _ar_variants = generate_arabic_name_variants(processed_name)
                        for _av in _ar_variants[:4]:
                            if _av != processed_name and len(conditions) < MAX_CONDITIONS:
                                conditions.append(f"aliases_arabic %% {self.placeholder}")
                                params.append(_av)
                                conditions.append(f"original_name %% {self.placeholder}")
                                params.append(_av)
                    
                    # Token-based trigram for Arabic (top 2 tokens only)
                    tokens = [t for t in processed_name.split() if len(t) > 2]
                    if len(tokens) >= 2:
                        tokens.sort(key=len, reverse=True)
                        token_query = (f"(name_normalized %% {self.placeholder} "
                                      f"AND name_normalized %% {self.placeholder})")
                        conditions.append(token_query)
                        params.append(tokens[0])
                        params.append(tokens[1])
            
            # Phonetic fallback (exact match, very cheap)
            if soundex and not is_arabic:
                conditions.append(f"name_soundex = {self.placeholder}")
                params.append(soundex)
            
            if metaphone and not is_arabic:
                conditions.append(f"name_metaphone = {self.placeholder}")
                params.append(metaphone)
            
            # English variants — limit to top 3 to control query size
            for variant in english_variants[:3]:
                if len(conditions) < MAX_CONDITIONS:
                    conditions.append(f"full_name %% {self.placeholder}")
                    params.append(variant)
            
            # FTS skipped - search_vector not in screening_watchlist
            
            # Safety cap — truncate if somehow over limit
            if len(conditions) > MAX_CONDITIONS:
                conditions = conditions[:MAX_CONDITIONS]
                # Recalculate params to match (count placeholders)
                param_count = sum(c.count(self.placeholder) for c in conditions)
                params = params[:param_count]
            
            where_clause = " OR ".join(conditions) if conditions else "1=1"
            
            # Build query with similarity ordering + length pre-filter
            query = f"""
                SELECT
                    id, full_name, name_normalized, dataset, list_type, topics,
                    countries, date_of_birth, year_of_birth, nationality,
                    source_url, risk_level, aliases, entity_type, properties, details, source,
                    original_name,
                    GREATEST(
                        similarity(COALESCE(name_normalized, ''), {self.placeholder}),
                        similarity(COALESCE(full_name, ''), {self.placeholder}),
                        similarity(COALESCE(original_name, ''), {self.placeholder}),
                        similarity(COALESCE(aliases_arabic, ''), {self.placeholder}),
                        similarity(COALESCE(original_name, ''), {self.placeholder}),
                        similarity(COALESCE(original_name, ''), {self.placeholder})
                    ) AS trgm_score
                FROM screening_watchlist
                WHERE is_active = 1 AND source NOT IN ('internal_blacklist', 'internal_pep')
                AND COALESCE(LENGTH(name_normalized), 0) BETWEEN {self.placeholder} AND {self.placeholder}
                AND ({where_clause})
                ORDER BY trgm_score DESC
                LIMIT 50
            """
            # Params order: similarity(5) + length_filter(2) + where_clause params
            _pn_alt = (lambda p: __import__('re').sub(r'عبدال([\u0600-\u06FF])', r'عبد ال\\1', p) if __import__('re').search(r'عبدال', p) else __import__('re').sub(r'عبد\\s+ال', 'عبدال', p))(processed_name or '')
            params_with_score = [processed_name or '', processed_name or '', processed_name or '', processed_name or '', processed_name or '', _pn_alt, len_min, len_max] + params
            
            cursor.execute(query, params_with_score)
            
        else:
            # ─── SQLite Fallback: LIKE-based recall (no trigram support) ───
            
            # Soundex/Metaphone are now transliterated for Arabic, so apply them globally
            if soundex:
                conditions.append(f"name_soundex = {self.placeholder}")
                params.append(soundex)
            
            if metaphone:
                conditions.append(f"name_metaphone = {self.placeholder}")
                params.append(metaphone)
            
            if processed_name:
                conditions.append(f"full_name LIKE {self.placeholder}")
                params.append(f"%{processed_name}%")
                conditions.append(f"name_normalized LIKE {self.placeholder}")
                params.append(f"%{processed_name}%")
                
                # Search aliases for all languages (JSON stored as text)
                conditions.append(f"CAST(aliases AS TEXT) LIKE {self.placeholder}")
                params.append(f"%{processed_name}%")
                conditions.append(f"CAST(aliases_arabic AS TEXT) LIKE {self.placeholder}")
                params.append(f"%{processed_name}%")
                if is_arabic:
                    pass  # Already handled above
                    
                if arabic_variants:
                    import re
                    for ar_var in arabic_variants[:5]:  # Limit to 5 to prevent massive queries
                        conditions.append(f"original_name LIKE {self.placeholder}")
                        params.append(f"%{ar_var}%")
                        conditions.append(f"CAST(aliases AS TEXT) LIKE {self.placeholder}")
                        params.append(f"%{ar_var}%")
                        
                        ar_var_strip = re.sub(r'[أإآ]', 'ا', ar_var)
                        # Also normalize ة→ه and ى→ي for better Arabic matching
                        ar_var_strip = re.sub(r'[ة]', 'ه', ar_var_strip)
                        ar_var_strip = re.sub(r'[ى]', 'ي', ar_var_strip)
                        if ar_var_strip != ar_var:
                            conditions.append(f"original_name LIKE {self.placeholder}")
                            params.append(f"%{ar_var_strip}%")
                            conditions.append(f"CAST(aliases AS TEXT) LIKE {self.placeholder}")
                            params.append(f"%{ar_var_strip}%")
                
                # Token-based recall (Global for both English and Arabic)
                tokens = [t for t in processed_name.split() if len(t) > 2]
                if len(tokens) >= 2:
                    tokens.sort(key=len, reverse=True)
                    # Search against full_name which contains the English version
                    token_query_fn = f"full_name LIKE {self.placeholder} AND full_name LIKE {self.placeholder}"
                    conditions.append(f"({token_query_fn})")
                    params.append(f"%{tokens[0]}%")
                    params.append(f"%{tokens[1]}%")
                    
                    # Also search against name_normalized
                    token_query_nn = f"name_normalized LIKE {self.placeholder} AND name_normalized LIKE {self.placeholder}"
                    conditions.append(f"({token_query_nn})")
                    params.append(f"%{tokens[0]}%")
                    params.append(f"%{tokens[1]}%")
                    
                    if is_arabic:
                        ar_token_query = f"original_name LIKE {self.placeholder} AND original_name LIKE {self.placeholder}"
                        conditions.append(f"({ar_token_query})")
                        params.append(f"%{tokens[0]}%")
                        params.append(f"%{tokens[1]}%")
                
                # Also check individual tokens for broader recall
                for token in tokens[:3]:
                    conditions.append(f"full_name LIKE {self.placeholder}")
                    params.append(f"%{token}%")
            
            # Arabic reverse-transliteration recall (English input -> Arabic DB entries)
            if arabic_variants:
                # 1. Full variant matching (for exact multi-word matches)
                for ar_var in arabic_variants[:3]:
                    conditions.append(f"full_name LIKE {self.placeholder}")
                    params.append(f"%{ar_var}%")
                
                # 2. Individual Arabic token matching (most effective for recall)
                # Collect unique Arabic tokens from all variants  
                ar_token_set = set()
                for ar_var in arabic_variants:
                    for tok in ar_var.split():
                        # Only include Arabic tokens (skip English leftovers)
                        if any('\u0600' <= c <= '\u06FF' for c in tok) and len(tok) > 1:
                            ar_token_set.add(tok)
                
                # Search each Arabic token individually  
                for ar_tok in list(ar_token_set)[:6]:
                    conditions.append(f"full_name LIKE {self.placeholder}")
                    params.append(f"%{ar_tok}%")
                    conditions.append(f"name_normalized LIKE {self.placeholder}")
                    params.append(f"%{ar_tok}%")
                
                # 3. Token-pair matching (high precision for Arabic)
                ar_token_list = list(ar_token_set)
                if len(ar_token_list) >= 2:
                    ar_token_list.sort(key=len, reverse=True)
                    ar_token_query = f"full_name LIKE {self.placeholder} AND full_name LIKE {self.placeholder}"
                    conditions.append(f"({ar_token_query})")
                    params.append(f"%{ar_token_list[0]}%")
                    params.append(f"%{ar_token_list[1]}%")

            # Slice to max 5 to prevent SQLite 'Expression tree too large' errors and improve performance
            for variant in english_variants[:5]:
                conditions.append(f"full_name LIKE {self.placeholder}")
                params.append(f"%{variant}%")
            
            where_clause = " OR ".join(conditions) if conditions else "1=1"
            
            # Prioritize closer matches in SQLite so they don't get pushed out by LIMIT 1000
            order_by_clause = "1"
            order_params = []
            if processed_name:
                order_by_clause = f"""
                    CASE 
                        WHEN original_name = {self.placeholder} THEN 1
                        WHEN name_normalized = {self.placeholder} THEN 1
                        WHEN original_name LIKE {self.placeholder} THEN 2
                        WHEN name_normalized LIKE {self.placeholder} THEN 2
                        WHEN original_name LIKE {self.placeholder} THEN 3
                        WHEN name_normalized LIKE {self.placeholder} THEN 3
                        {{}}
                        ELSE 4
                    END,
                    ABS(LENGTH(COALESCE(name_normalized, '')) - LENGTH({self.placeholder})) ASC
                """
                
                ar_injections = ""
                ar_params = []
                if arabic_variants:
                    import re
                    ar_top = re.sub(r'[أإآ]', 'ا', arabic_variants[0])
                    ar_injections = f"WHEN original_name LIKE {self.placeholder} THEN 1.5 WHEN CAST(aliases AS TEXT) LIKE {self.placeholder} THEN 1.5"
                    ar_params = [f"%{ar_top}%", f"%{ar_top}%"]
                
                order_by_clause = order_by_clause.format(ar_injections)
                
                order_params = [
                    processed_name, processed_name, 
                    f"{processed_name}%", f"{processed_name}%",
                    f"%{processed_name}%", f"%{processed_name}%"
                ] + ar_params + [processed_name]
            
            query = f"""
                SELECT
                    id, full_name, name_normalized, dataset, list_type, topics,
                    countries, date_of_birth, year_of_birth, nationality,
                    source_url, risk_level, aliases, entity_type, properties, details, source,
                    original_name
                FROM screening_watchlist
                WHERE is_active = 1 AND source NOT IN ('internal_blacklist', 'internal_pep')
                AND ({where_clause})
                ORDER BY {order_by_clause}
                LIMIT 5000
            """
            
            
            # Combine params
            cursor.execute(query, params + order_params)
        
        candidates = cursor.fetchall()
        cursor.close()

        candidates = [dict(c) for c in candidates]
        for c in candidates:
            if 'details' in c:
                c['details'] = extract_bio_snippet(c.get('details')) or compute_fallback_bio(c)

        logger.debug("[SQLite candidates: {len(candidates)}")
        logger.debug(f"[TIMER] SQLite recall: {round((time.time()-t2)*1000)}ms")
        logger.debug("[Total after dedup: {len(candidates)}")
        
        logger.info(f"Candidate recall: {len(candidates)} candidates found "
                    f"(trigram={'ON' if use_trigram else 'OFF'})")
        
        return candidates
    
    def _apply_country_scoring(self, score, submitted_country, candidate_country):
        # A country / nationality match only ADDS to the score; a different or
        # missing nationality never lowers it (see match_intel.country_score_adjust).
        from screening.match_intel import country_score_adjust
        return country_score_adjust(score, submitted_country, candidate_country)

    def _apply_dob_scoring(self, score, submitted_dob, candidate_dob):
        if not submitted_dob:
            return score  # Officer did not provide DOB — no change either way

        if not candidate_dob:
            return score  # Record has no DOB — cannot confirm or deny, no change

        # Both exist — now compare
        try:
            from dateutil.parser import parse as parse_date
        except ImportError:
            def parse_date(d_str):
                from datetime import datetime
                s_val = str(d_str)
                s_val = s_val[:10] if len(s_val) > 10 else s_val
                for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y', '%Y'):
                    try:
                        return datetime.strptime(s_val, fmt)
                    except ValueError:
                        pass
                raise ValueError("Unparseable date")
        try:
            sub = parse_date(submitted_dob)  # use dateutil.parser.parse
            can = parse_date(candidate_dob)

            if sub.year == can.year and sub.month == can.month and sub.day == can.day:
                return score + 15  # Exact match — strong confirmation boost
            elif sub.year == can.year and sub.month == can.month:
                return score + 8   # Year and month match
            elif sub.year == can.year:
                return score + 4   # Year only match
            else:
                return score - 20  # DOB provided AND exists in record but does not match
                # This is a strong signal this is the wrong person
        except Exception:
            return score  # Unparseable date — no change

    def _precision_scoring(self, candidates, original_name, processed_name,
                          dob, nationality, entity_type, english_variants=None, 
                          address=None, adv_features=None, is_arabic=False, arabic_variants=None,
                          national_id=None, employer=None):
        """
        Phase 2: Precision Scoring (Optimized with Invariant Hoisting & ML Batching)
        """
        if address:
            logger.info(f"DEBUG: _precision_scoring called with address='{address}'")
        else:
            logger.info("DEBUG: _precision_scoring called with address=None")

        scored_matches = []
        
        # --- 1. PRE-COMPUTE LOOP INVARIANTS ---
        # Normalize english variants exactly once, outside the loop
        norm_variants = [self._normalize_english(v) for v in (english_variants or [])]
        
        # Pre-compute soundex and metaphone for the processed name
        # Add known Arabic→English transliteration variants for common names
        KNOWN_ARABIC_EN_VARIANTS = {
            'osama': ['usamah', 'usama', 'oussama', 'ossama'],
            'usamah': ['osama', 'usama', 'oussama'],
            'usama': ['osama', 'usamah', 'oussama'],
            'mohamad': ['muhammad', 'mohammed', 'mohammad', 'mohamed'],
            'muhammad': ['mohamad', 'mohammed', 'mohammad', 'mohamed'],
            'abdel': ['abdelmalek', 'abdelouadoud', 'abdel', 'abd al', 'abd el'],
            'abdelmalek': ['abdel malek', 'abd al-malik', 'abd el malik'],
            'droukdel': ['droukdal', 'drokdal', 'drukdal', 'droukadal'],
            'baghdadi': ['al-baghdadi', 'albaghdadi', 'bagdadi'],
            'zarqawi': ['al-zarqawi', 'alzarqawi', 'zarkawi'],
        }
        pn_lower = processed_name.lower() if processed_name else ''
        for base_word, variants in KNOWN_ARABIC_EN_VARIANTS.items():
            if base_word in pn_lower:
                for v in variants:
                    expanded = pn_lower.replace(base_word, v)
                    if expanded not in [e.lower() for e in english_variants]:
                        english_variants.append(expanded.upper())

        phonetic_base = english_variants[0] if is_arabic and english_variants else processed_name
        s1 = jellyfish.soundex(phonetic_base) if phonetic_base else ""
        m1 = jellyfish.metaphone(phonetic_base) if phonetic_base else ""
        
        # Pre-compute soundex and metaphone for all english variants
        variant_soundexes = [jellyfish.soundex(v) for v in (english_variants or [])]
        variant_metaphones = [jellyfish.metaphone(v) for v in (english_variants or [])]
        
        tokens_input = processed_name.split() if processed_name else []
        is_input_common = is_common_name_only(tokens_input)

        # Prepare for address matching if needed
        compare_addresses = None
        if address:
            try:
                from .address_utils import compare_addresses
            except ImportError:
                logger.warning("address_utils.compare_addresses not found, address matching disabled")

        batch_ml_inputs = []
        intermediate_results = []
        
        # --- 2. BASE SCORING LOOP ---
        for candidate in candidates:
            # Lowercased once here: rapidfuzz/jellyfish do no case-folding of their
            # own, and processed_name (from _normalize_english) is uppercase while
            # ES/PG candidate names are stored lowercase — comparing them as-is
            # made every Latin-script fuzzy/Jaro-Winkler score near-zero
            # regardless of how close the actual names were (e.g. "BASHAR
            # ALASSAD" vs "bashar al-assad" scored ~7% instead of ~97%).
            candidate_name = (candidate['name_normalized'] or '').lower()
            full_candidate_name = candidate['full_name'] or ''

            # Variant Exact Match Check
            is_variant_match = False
            if english_variants:
                for v, v_norm in zip(english_variants, norm_variants):
                    if v_norm.lower() == candidate_name or v.lower() == full_candidate_name.lower():
                        is_variant_match = True
                        break
                        
            # Use 0 if names are empty for some reason
            if not processed_name or not candidate_name:
                fuzzy_score = 0
                jaro_winkler_score = 0
                soundex_match = 0
                metaphone_match = 0
                partial_score = 0
                address_score = 0.0
            else:
                import re as _sc_re

                def _ar_norm_score(s):
                    if not s: return s
                    s = _sc_re.sub(r'[أإآٱ]', 'ا', s)
                    s = s.replace('ة','ه').replace('ى','ي').replace('ؤ','ء').replace('ئ','ء')
                    s = _sc_re.sub(r'عبدال([\u0600-\u06FF])', lambda m: 'عبد ال'+m.group(1), s)
                    return _sc_re.sub(r' {2,}', ' ', s).strip().lower()

                cand_orig_ar = candidate.get('original_name', '') or ''
                # Include aliases_arabic so English records with Arabic alias storage
                # are scored Arabic-to-Arabic instead of via weak transliterations.
                cand_aliases_ar = candidate.get('aliases_arabic', '') or ''
                if candidate.get('full_name_arabic'):
                    cand_aliases_ar = (candidate['full_name_arabic'] + '|' + cand_aliases_ar).strip('|')
                has_arabic_cand = any('\u0600' <= c <= '\u06FF' for c in cand_orig_ar + candidate_name + cand_aliases_ar[:200])

                if is_arabic and has_arabic_cand:
                    pn_norm = _ar_norm_score(processed_name)
                    pn_coll = _sc_re.sub(r'عبد\s+ال', 'عبدال', pn_norm)

                    # Build a list of all Arabic candidate representations to compare
                    # against — original_name, aliases_arabic (pipe-separated), and
                    # the normalised form.  Pick the best score across all of them.
                    _ar_cand_targets = []
                    if cand_orig_ar and any('\u0600' <= c <= '\u06FF' for c in cand_orig_ar):
                        _ar_cand_targets.append(cand_orig_ar)
                    if cand_aliases_ar:
                        for _alias in cand_aliases_ar.split('|')[:5]:
                            _alias = _alias.strip()
                            if _alias and any('\u0600' <= c <= '\u06FF' for c in _alias):
                                _ar_cand_targets.append(_alias)
                    if not _ar_cand_targets:
                        # No Arabic found — fall back to name_normalized
                        _ar_cand_targets.append(candidate_name)

                    best_fuzzy = best_jw = best_partial = 0.0
                    for _ct in _ar_cand_targets:
                        cn_norm = _ar_norm_score(_ct)
                        cn_coll = _sc_re.sub(r'عبد\s+ال', 'عبدال', cn_norm)
                        for a, b in [(pn_norm, cn_norm), (pn_norm, cn_coll),
                                     (pn_coll, cn_norm), (pn_coll, cn_coll)]:
                            if not a or not b:
                                continue
                            f  = _distinctive_fuzzy(a, b) / 100.0
                            jw = jellyfish.jaro_winkler_similarity(a, b)
                            p  = fuzz.partial_ratio(a, b) / 100.0
                            if f  > best_fuzzy:   best_fuzzy   = f
                            if jw > best_jw:      best_jw      = jw
                            if p  > best_partial: best_partial = p
                    fuzzy_score        = best_fuzzy
                    jaro_winkler_score = best_jw
                    partial_score      = best_partial

                # Cross-Script Logic: If we have English variants of an Arabic name,
                elif norm_variants:
                    best_fuzzy = 0
                    best_jw = 0
                    best_partial = 0
                    for v_norm in norm_variants:
                        v_norm_lower = v_norm.lower()
                        # token_set_ratio (missing here previously, present in the
                        # same-script `else` branch below) is what actually rescues
                        # short variants like "putin" against a full official-list
                        # name with extra middle names/patronymics ("Vladimir
                        # Vladimirovich PUTIN") — plain fuzz.ratio penalizes the
                        # length mismatch hard (~30%) while token_set_ratio
                        # correctly recognizes "putin" as a full subset (100%).
                        f = _distinctive_fuzzy(v_norm_lower, candidate_name) / 100.0
                        jw = max(
                            jellyfish.jaro_winkler_similarity(v_norm_lower, candidate_name),
                            jellyfish.jaro_winkler_similarity(_token_sorted(v_norm_lower), _token_sorted(candidate_name)),
                        )
                        p = fuzz.partial_ratio(v_norm_lower, candidate_name) / 100.0
                        if f > best_fuzzy: best_fuzzy = f
                        if jw > best_jw: best_jw = jw
                        if p > best_partial: best_partial = p
                    
                    fuzzy_score = best_fuzzy
                    jaro_winkler_score = best_jw
                    partial_score = best_partial
                else:
                    processed_name_lower = processed_name.lower()
                    fuzzy_score = _distinctive_fuzzy(processed_name_lower, candidate_name) / 100.0
                    jaro_winkler_score = max(
                        jellyfish.jaro_winkler_similarity(processed_name_lower, candidate_name),
                        jellyfish.jaro_winkler_similarity(_token_sorted(processed_name_lower), _token_sorted(candidate_name)),
                    )
                    partial_score = fuzz.partial_ratio(processed_name_lower, candidate_name) / 100.0
                
                # Cross-script: English input vs Arabic candidate
                # When we have arabic_variants and candidate contains Arabic,
                # compare Arabic variants against the candidate for better scoring
                if arabic_variants and not is_arabic:
                    # Semantic hits keep original_name populated with Arabic, not full_name
                    cand_orig_name = candidate.get('original_name', '') or ''
                    candidate_has_arabic = any('\u0600' <= c <= '\u06FF' for c in cand_orig_name + (candidate_name or ''))
                    
                    if candidate_has_arabic:
                        import re
                        def _norm_ar(s):
                            s = re.sub(r'[أإآ]', 'ا', s)
                            s = s.replace('ة', 'ه').replace('ى', 'ي')
                            return s
                            
                        target_name = cand_orig_name if any('\u0600' <= c <= '\u06FF' for c in cand_orig_name) else full_candidate_name
                        target_name_norm = _norm_ar(target_name)
                        for ar_var in arabic_variants:
                            ar_var_norm = _norm_ar(ar_var)
                            ar_f = _distinctive_fuzzy(ar_var_norm, target_name_norm) / 100.0
                            ar_jw = jellyfish.jaro_winkler_similarity(ar_var_norm, target_name_norm)
                            ar_p = fuzz.partial_ratio(ar_var_norm, target_name_norm) / 100.0
                            if ar_f > fuzzy_score: fuzzy_score = ar_f
                            if ar_jw > jaro_winkler_score: jaro_winkler_score = ar_jw
                            if ar_p > partial_score: partial_score = ar_p
                
                # Cross-script reversed: Arabic input vs English candidate
                if not norm_variants and is_arabic:
                   eng_variants = [self._normalize_english(transliterate_arabic(processed_name))]
                   for e_var in eng_variants:
                        e_var_lower = e_var.lower()
                        e_f = _distinctive_fuzzy(e_var_lower, candidate_name) / 100.0
                        e_jw = jellyfish.jaro_winkler_similarity(e_var_lower, candidate_name)
                        e_p = fuzz.partial_ratio(e_var_lower, candidate_name) / 100.0
                        if e_f > fuzzy_score: fuzzy_score = e_f
                        if e_jw > jaro_winkler_score: jaro_winkler_score = e_jw
                        if e_p > partial_score: partial_score = e_p
                
                # Phonetic match (Soundex/Metaphone)
                # Note: jellyfish crashes on non-Latin text (Arabic), so wrap in try/except
                try:
                    s2 = jellyfish.soundex(candidate_name)
                    soundex_match = 1.0 if s1 == s2 else 0.0
                except (UnicodeEncodeError, ValueError, Exception):
                    s2 = ''
                    soundex_match = 0.0
                
                # Address Matching
                address_score = 0.0
                if 'address' in locals() and locals()['address']: # Check if address arg passed
                    candidate_addresses = []
                    try:
                        props = json.loads(candidate.get('properties', '{}') or '{}')
                        if 'addresses' in props:
                            candidate_addresses.extend([a.strip() for a in props['addresses'].split(';') if a.strip()])
                        if 'address' in props:
                            candidate_addresses.append(props['address'])
                    except Exception as e:
                        logger.debug(f"[SWALLOWED] candidate address parsing failed: {e}")
                        
                    if candidate_addresses and compare_addresses:
                        best_addr_score = 0
                        for c_addr in candidate_addresses:
                            s = compare_addresses(address, c_addr)
                            if s > best_addr_score:
                                best_addr_score = s
                        address_score = best_addr_score
                
                try:
                    m2 = jellyfish.metaphone(candidate_name)
                    metaphone_match = 1.0 if m1 == m2 else 0.0
                except (UnicodeEncodeError, ValueError, Exception):
                    m2 = ''
                    metaphone_match = 0.0
                
                # Check variants for phonetic match if main fails
                if soundex_match == 0 and s2 and s2 in variant_soundexes:
                    soundex_match = 1.0
                if metaphone_match == 0 and m2 and m2 in variant_metaphones:
                    metaphone_match = 1.0
            
            phonetic_score = (soundex_match + metaphone_match) / 2.0

            # Soundex/Metaphone are English algorithms. On Arabic, soundex
            # returns the first letter followed by 000 — محمد, محمود and محسن
            # all yield 'م000' — and metaphone returns nothing at all. With
            # PHONETIC_WEIGHT at 15%, that made "starts with the same letter"
            # worth 15% of a match. For Arabic-script pairs use Arabic
            # confusion classes (ث/س/ص, ذ/ز/ظ, ت/ط, د/ض, ق/ك, ح/ه) over the
            # whole token instead.
            try:
                if _is_ar(processed_name) and _is_ar(candidate_name):
                    phonetic_score = _ar_phonetic_sim(processed_name,
                                                      candidate_name)
            except Exception:
                pass
            
            
            # Semantic search integration into ensemble score
            semantic_score = candidate.get('semantic_score', 0.0)
            
            # Baseline classical string distance to fallback/verify against
            classical_score = (
                (fuzzy_score * self.FUZZY_RATIO_WEIGHT) +
                (jaro_winkler_score * self.JARO_WINKLER_WEIGHT) +
                (phonetic_score * self.PHONETIC_WEIGHT) +
                (partial_score * self.PARTIAL_RATIO_WEIGHT)
            )
            
            if semantic_score > 0:
                # Semantic similarity alone cannot identify a person: every
                # personal name embeds close to every other personal name. It is
                # corroborating evidence, never primary evidence.
                #
                # Previously the top tier fired on semantic>=95 AND *any one* of
                # three weak lexical thresholds (OR), then applied max(0.95, ...)
                # — a hard floor. An Arabic merchant name scored 95% against an
                # unrelated Latin sanctions name on embedding similarity alone.
                #
                # Now the lexical evidence must genuinely agree, and the result
                # is a blend rather than a floor. A real cross-script match still
                # passes: the engine transliterates the name first, so a true
                # match scores high on the variant comparison, not on semantics.
                if semantic_score >= 95.0 and fuzzy_score >= 0.70:
                    ensemble_score = min(
                        0.97,
                        (semantic_score / 100.0 * 0.55) + (fuzzy_score * 0.45)
                    )
                elif semantic_score >= 88.0 and (fuzzy_score >= 0.60 and
                                                 (jaro_winkler_score >= 0.60 or
                                                  partial_score >= 0.65)):
                    ensemble_score = (
                        (semantic_score / 100.0 * 0.45) +
                        (fuzzy_score * 0.35) +
                        (jaro_winkler_score * 0.20)
                    )
                else:
                    # Semantic AI is diverging from token validation: treat the
                    # classical score as the ceiling (false-positive guard).
                    ensemble_score = min(classical_score, 0.74)
            else:
                ensemble_score = classical_score
            
            ensemble_score_pct = ensemble_score * 100.0
            
            # --- ADJUSTMENTS ---
            if is_variant_match:
                ensemble_score_pct = max(ensemble_score_pct, 90.0)
            
            tokens_candidate = candidate_name.split() if candidate_name else []
            exact_match_boost = calculate_exact_match_boost(tokens_input, tokens_candidate)
            
            type_match = True
            type_mismatch_penalty = 0.0
            if entity_type and candidate.get('entity_type'):
                # Normalize entity types: PERSON and INDIVIDUAL are equivalent
                input_type = entity_type.upper()
                cand_type = candidate['entity_type'].upper()
                type_equivalents = {'INDIVIDUAL': 'PERSON', 'PERSON': 'INDIVIDUAL'}
                if input_type != cand_type and type_equivalents.get(input_type) != cand_type:
                    type_match = False
                    type_mismatch_penalty = -20.0
                    
            candidate_dob = candidate.get('date_of_birth') or candidate.get('birth_date')
            # FIX 3: DOB penalty — fall back to properties JSON when top-level field is empty.
            # Some records (e.g. OFAC) store birth date inside the JSON blob rather than the
            # dedicated column.  Without this, _apply_dob_scoring is never called and a
            # mismatched DOB cannot lower the match score.
            if not candidate_dob:
                try:
                    _props = json.loads(candidate.get('properties', '{}') or '{}')
                    candidate_dob = (
                        _props.get('birthDate') or _props.get('birth_date')
                        or _props.get('date_of_birth') or _props.get('dob')
                        or _props.get('Birth Date') or ''
                    )
                except Exception:
                    pass
            candidate_country = candidate.get('nationality') or candidate.get('country')
            candidate_national_id = candidate.get('national_id_numbers') or candidate.get('national_id')
                    
            common_name_penalty_val = 0.0
            if is_input_common and is_common_name_only(tokens_candidate):
                common_name_penalty_val = self.COMMON_NAME_PENALTY

            # Save state for post-ML aggregation
            interim_state = {
                'candidate_name_raw': full_candidate_name,
                # The Arabic form is kept alongside because the name-structure
                # rules must compare like with like: an Arabic query against a
                # Latin candidate has no shared tokens, so every rule returns
                # 'unknown' and stands down.
                'candidate_name_ar': (candidate.get('original_name')
                                      or candidate.get('watchlist_name_ar')
                                      or ''),
                'fuzzy_score': fuzzy_score,
                'jaro_winkler_score': jaro_winkler_score,
                'partial_score': partial_score,
                'phonetic_score': phonetic_score,
                'ensemble_score_pct': ensemble_score_pct,
                'exact_match_boost': exact_match_boost,
                'type_match': type_match,
                'type_mismatch_penalty': type_mismatch_penalty,
                'candidate_dob': candidate_dob,
                'candidate_country': candidate_country,
                'candidate_national_id': candidate_national_id,
                'address_score': address_score,
                'common_name_penalty_val': common_name_penalty_val,
                'is_variant_match': is_variant_match,
                'semantic_score': semantic_score
            }
            intermediate_results.append(interim_state)

            # --- ML BATCH PREPARATION ---
            if self.ml_calibrator and self.ml_calibrator.is_fitted:
                batch_ml_inputs.append({
                    'input_name': original_name if is_arabic else original_name,
                    'watchlist_name': full_candidate_name,
                    'input_dob': dob,
                    'watchlist_dob': candidate_dob,
                    'input_nationality': nationality,
                    'watchlist_nationality': candidate.get('nationality'),
                    'network_score': adv_features.get('network_score', 0.0) if adv_features else 0.0,
                    'tx_velocity_score': adv_features.get('tx_velocity_score', 0.0) if adv_features else 0.0,
                    'media_risk_score': adv_features.get('media_risk_score', 0.0) if adv_features else 0.0,
                    'tenure_days': adv_features.get('tenure_days', 0) if adv_features else 0,
                    'semantic_score': semantic_score
                })
        
        # --- 3. BATCH ML EVALUATION ---
        ml_results = []
        if batch_ml_inputs:
            try:
                ml_results = self.ml_calibrator.calculate_ml_score_batch(batch_ml_inputs)
            except Exception as e:
                logger.error(f"Batch ML prediction failed in precision scoring: {e}")
                
        # --- 4. FINAL AGGREGATION ---
        for i, candidate in enumerate(candidates):
            interim = intermediate_results[i]
            
            final_score = float(interim['ensemble_score_pct'])
            final_score += float(interim['exact_match_boost'])

            # ---- name structure -------------------------------------------
            # The engine treated every token as an interchangeable bag item, so
            # 'اشرف محمد احمد منصور' matched 'اشرف محمد احمد الصعيدي' at 82.4
            # despite the differing family name, while 'Osama Bin Laden' missed
            # its own longer listed form at 75.0.
            try:
                # compare against the form written in the query's script
                _cand_en = interim.get('candidate_name_raw') or ''
                _cand_ar = interim.get('candidate_name_ar') or ''
                if _is_ar(original_name):
                    _cand_name = _cand_ar or _cand_en
                else:
                    _cand_name = _cand_en or _cand_ar
                if _cand_name:
                    # a short form inside a full patronymic chain is a match
                    if _is_short_form(original_name, _cand_name,
                                      NON_DISTINCTIVE_NAME_TOKENS):
                        final_score = max(final_score, 90.0)

                    _fam = _family_verdict(original_name, _cand_name)
                    # a shared family name is not identity on its own
                    _conf = (_given_conflict(original_name, _cand_name)
                             or _thin_conflict(original_name, _cand_name)
                             or _thin_evidence(original_name, _cand_name,
                                               NON_DISTINCTIVE_NAME_TOKENS))
                    if _fam == 'mismatch' or _conf:
                        # the family name contradicts, or the given names do:
                        # cap below threshold unless an identifier corroborates
                        final_score = min(final_score,
                                          self.FAMILY_MISMATCH_CAP)
                    elif _fam == 'match':
                        final_score = min(100.0, final_score + 5.0)
            except Exception:
                pass
            final_score += float(interim['type_mismatch_penalty'])
            # Apply Country Scoring
            if nationality and interim['candidate_country']:
                final_score = self._apply_country_scoring(final_score, nationality, interim['candidate_country'])
                
            # Apply DOB Scoring
            if dob and interim['candidate_dob']:
                final_score = self._apply_dob_scoring(final_score, dob, interim['candidate_dob'])
                
            # Apply Disambiguation / Tie-breakers
            exact_nid_match = False
            if national_id and interim['candidate_national_id']:
                if str(national_id).strip() == str(interim['candidate_national_id']).strip():
                    final_score += 25
                    exact_nid_match = True
                else:
                    final_score -= 25
            
            address_bonus = (float(interim['address_score']) / 100.0) * 15.0
            final_score += float(address_bonus)
            final_score -= float(interim['common_name_penalty_val'])
            
            # Blend ML if available
            ml_score_pct = None
            ml_confidence = 'n/a'
            # Cross-script: English input → Arabic candidate OR Arabic input → English candidate.
            # In both cases the ML model (trained on same-script pairs) should not penalise;
            # it may only boost when it confidently agrees.
            _cand_full = (candidate.get('full_name', '') or '') + (candidate.get('name_normalized', '') or '')
            _cand_is_arabic = any('\u0600' <= c <= '\u06FF' for c in _cand_full)
            is_cross_script_match = (
                # English input vs Arabic-named candidate
                (arabic_variants and not is_arabic and _cand_is_arabic)
                # Arabic input vs Latin-named candidate (scored via aliases_arabic)
                or (is_arabic and not _cand_is_arabic)
            )
            # Reordered names ("Hussein Saddam" vs "Saddam Hussein") hit the
            # same problem as cross-script: the ML model's first_name_match/
            # last_name_match features are positional, so a pure word-order
            # swap can make it score the pair as a poor match (seen: 46%)
            # even though token_set_ratio already says the tokens are the
            # same person. Using exact_match_boost>=15 (67% token-set
            # overlap) alone under-fires when a token also differs by a
            # hyphen the query side stripped ("al-assad" candidate vs our
            # normalized "alassad") — fuzzy_score is char-level (rapidfuzz
            # token_set_ratio) and isn't thrown off by that, so OR it in.
            is_reordered_match = interim['exact_match_boost'] >= 15 or interim['fuzzy_score'] >= 0.90
            if ml_results and i < len(ml_results):
                ml_res = ml_results[i]
                ml_score_pct = ml_res.get('ml_score')
                ml_confidence = ml_res.get('confidence', 'medium')

                if ml_score_pct is not None and not is_cross_script_match and not is_reordered_match:
                    # Standard ML blending for same-script matches
                    final_score = (final_score * 0.7) + (ml_score_pct * 0.3)
                elif ml_score_pct is not None and (is_cross_script_match or is_reordered_match):
                    # For cross-script/reordered matches, only boost with ML, never penalize
                    if ml_score_pct > final_score:
                        final_score = (final_score * 0.7) + (ml_score_pct * 0.3)
            
            # Token-level exact match boost for high-value identifier tokens
            # If rare/unique surname tokens match exactly, boost significantly
            HIGH_VALUE_TOKENS = {
                'laden', 'droukdel', 'droukdal', 'zarqawi', 'baghdadi',
                'bin laden', 'benladen', 'awlaki', 'zawahiri', 'masri',
            }
            input_lower = (original_name or '').lower()
            cand_lower = (candidate.get('full_name', '') or '').lower()
            cand_norm_lower = (candidate.get('name_normalized', '') or '').lower()
            for token in HIGH_VALUE_TOKENS:
                if token in input_lower and (token in cand_lower or token in cand_norm_lower):
                    if final_score < 75.0:
                        final_score = max(final_score, 75.0)
                        logger.debug(f"[TOKEN_BOOST] '{token}' exact match → boosted to {final_score}")
                    break

            # Cap at 100
            final_score = min(100.0, max(0.0, final_score))

            # A3 policy (approved 2026-07-11): the officer supplied a DOB
            # but this record has none to check it against — the strongest
            # disambiguator is unverifiable, so a purely name-driven score
            # must not auto-confirm. Cap just below CONFIRMED_HIT (the
            # match presents as at most POTENTIAL_MATCH and goes to human
            # review) unless identity was verified another way (exact
            # national-ID match). Root case: "Jon Smith"+DOB+UK scored
            # CONFIRMED_HIT 100.0 against no-DOB common-name records —
            # records without a DOB skip _apply_dob_scoring entirely (the
            # -20 mismatch penalty can never fire) while exact-token and
            # country boosts saturate the score to 100.
            dob_uncheckable = bool(dob) and not interim['candidate_dob'] and not exact_nid_match
            dob_cap_applied = dob_uncheckable and final_score >= self.CONFIRMED_HIT_THRESHOLD
            if dob_cap_applied:
                final_score = self.CONFIRMED_HIT_THRESHOLD - 0.1

            if final_score >= self.LOW_MATCH_THRESHOLD:
                match_details = {
                    'match_score': round(final_score, 2),
                    'rule_based_score': round(interim['ensemble_score_pct'], 2),
                    'ml_score': round(ml_score_pct, 2) if ml_score_pct is not None else None,
                    'ml_confidence': ml_confidence,
                    'threshold_used': self.ml_threshold,
                    'candidate_name': candidate['name_normalized'],
                    'source': candidate.get('source', 'Unknown'),
                    'entity_type': candidate.get('entity_type', 'Unknown'),
                    'matched_on': 'name_similarity',
                    'score_breakdown': {
                        'fuzzy_ratio': round(float(interim['fuzzy_score']) * 100, 2),
                        'jaro_winkler': round(float(interim['jaro_winkler_score']) * 100, 2),
                        'phonetic': round(float(interim['phonetic_score']) * 100, 2),
                        'partial_ratio': round(float(interim['partial_score']) * 100, 2),
                        'ensemble_base': round(float(interim['ensemble_score_pct']) - float(interim['exact_match_boost']) if not interim['is_variant_match'] else float(interim['ensemble_score_pct']), 2),
                        'exact_match_boost': interim['exact_match_boost'],
                        'variant_match_boost': 90.0 if interim['is_variant_match'] else 0.0,
                        'dob_adjustment': round(self._apply_dob_scoring(0, dob, interim['candidate_dob']) if dob and interim['candidate_dob'] else 0.0, 2),
                        'nationality_adjustment': round(self._apply_country_scoring(0, nationality, interim['candidate_country']) if nationality and interim['candidate_country'] else 0.0, 2),
                        'address_adjustment': round(float(address_bonus), 2),
                        'type_mismatch_penalty': interim['type_mismatch_penalty'],
                        'common_name_penalty': -self.COMMON_NAME_PENALTY if interim['common_name_penalty_val'] > 0 else 0.0,
                        'semantic_score': round(float(interim['semantic_score']), 2),
                        'type_match': interim['type_match'],
                        'dob_unverified_cap': dob_cap_applied
                    }
                }
                match_details.update(dict(candidate))
                
                if 'source_url' in candidate and candidate['source_url']:
                    match_details['source_url'] = candidate['source_url']

                scored_matches.append(match_details)
            
                # Add Explanation
                scored_matches[-1]['explanation'] = self.generate_match_explanation(scored_matches[-1])
        
        scored_matches.sort(key=lambda x: x['match_score'], reverse=True)
        return scored_matches

    def generate_match_explanation(self, match_details):
        """
        Generate human-readable explanation for the match score.
        """
        reasons = []
        breakdown = match_details.get('score_breakdown', {})
        
        # 1. Name Similarity
        fuzzy = breakdown.get('fuzzy_ratio', 0)
        phonetic = breakdown.get('phonetic', 0)
        
        if fuzzy > 90:
            reasons.append(f"Very high name similarity ({fuzzy}%)")
        elif fuzzy > 80:
            reasons.append(f"High name similarity ({fuzzy}%)")
        
        if phonetic > 85:
            reasons.append("Strong phonetic match (sounds optimization)")
            
        # 2. Adjustments
        if breakdown.get('exact_match_boost', 0) > 0:
            reasons.append("Exact name match bonus applied")
            
        if breakdown.get('variant_match_boost', 0) > 0:
            reasons.append("Matched on known name variant (e.g. Gamal/Jamal)")
            
        if breakdown.get('dob_adjustment', 0) > 0:
            reasons.append("Date of Birth match confirmed")
            
        if breakdown.get('nationality_adjustment', 0) > 0:
            reasons.append("Nationality match confirmed")

        if breakdown.get('address_adjustment', 0) > 0:
            reasons.append("Address match confirmed (Location Boost)")
            
        if breakdown.get('nationality_adjustment', 0) > 0:
            reasons.append("Nationality match confirmed")
            
        if breakdown.get('type_mismatch_penalty', 0) < 0:
            reasons.append("Entity type mismatch penalty applied")
            
        if breakdown.get('common_name_penalty', 0) < 0:
            reasons.append("Common name penalty applied")

        if breakdown.get('dob_unverified_cap'):
            reasons.append("Capped below CONFIRMED_HIT: a date of birth was "
                           "provided but this record has none to verify it against")


        # 3. ML Influence
        ml_score = match_details.get('ml_score')
        rule_score = match_details.get('rule_based_score')
        
        if ml_score is not None and rule_score is not None:
            diff = ml_score - rule_score
            if diff > 10:
                reasons.append(f"CMS Matching significantly boosted confidence (+{diff:.1f}%)")
            elif diff < -10:
                reasons.append(f"CMS Matching reduced false positive probability (-{abs(diff):.1f}%)")
                
        return reasons

    def _is_whitelisted(self, normalized_name):
        """Check if name is in the whitelist"""
        try:
            if not self.db_conn: self.connect_db()
            assert self.db_conn is not None
            cursor = self.db_conn.cursor()
            # normalized_name, not whitelisted_name: every INSERT path writes
            # normalized_name and whitelisted_name is NULL in every row, so the
            # original predicate never matched and the whitelist never suppressed
            # anything. status must be Active, otherwise a revoked entry would
            # keep suppressing alerts.
            cursor.execute(
                f"SELECT id FROM screening_whitelist "
                f"WHERE normalized_name = {self.placeholder} AND status = 'Active' "
                # past its review date an entry no longer suppresses hits
                f"AND COALESCE(review_date, '') >= to_char(CURRENT_DATE, 'YYYY-MM-DD')",
                (normalized_name,))
            result = cursor.fetchone()
            cursor.close()
            return result is not None
        except Exception as e:
            logger.error(f"Whitelist usage warning (skipping): {e}")
            return False

    def learn_from_feedback(self, match_id, feedback_type, feedback_details=None):
        """
        Process user feedback for Online Learning.
        feedback_type: 'CONFIRMED_MATCH' (1) or 'FALSE_POSITIVE' (0)
        feedback_details: Dict containing 'features' used if available, or raw data to re-extract.
        """
        if not self.online_learner:
            logger.warning("Online Learning not enabled (missing dependencies).")
            return False
            
        label = 1 if feedback_type == 'CONFIRMED_MATCH' else 0
        
        try:
            # unique logic to retrieve feature context if not provided
            # For now assume feedback_details matches what OnlineLearner expects
            self.online_learner.log_feedback(feedback_details or {}, label)
            return True
        except Exception as e:
            logger.error(f"Failed to log feedback: {e}")
            return False
