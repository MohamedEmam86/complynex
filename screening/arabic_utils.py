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

import re

# Enhanced Egyptian & Arabic Variants
# Expands on the standard dictionary
EGYPTIAN_ARABIC_VARIANTS = {
    # G/J Sound (Jim vs Gim - Egyptian Dialect)
    'جمال': ['gamal', 'jamal'],
    'جمعة': ['gomaa', 'juma', 'gomma'],
    'جلال': ['galal', 'jalal'],
    'جاد': ['gad', 'jad'],
    'مجدي': ['magdy', 'majdy', 'magdi'],
    'نجوى': ['nagwa', 'najwa'],
    'ماجد': ['maged', 'majed'],
    'وجدي': ['wagdy', 'wajdi'],
    'رجاء': ['ragaa', 'rajaa'],
    
    # Q/K/A Sound (Qaf)
    'قاسم': ['kassem', 'qasim', 'kasim'],
    'طارق': ['tarek', 'tariq'],
    
    # Phase 4 Egyptian Additions
    'فرج': ['farag', 'farrag', 'faraj'],
    'النجار': ['el-naggar', 'nagar', 'naggar'],
    'السيد': ['el-sayed', 'sayed', 'sayyed'],
    'جابر': ['gaber', 'jaber', 'gabr'],
    'فؤاد': ['fouad', 'fuad'],
    'رمضان': ['ramadan', 'ramadhan'],
    'شعبان': ['shaaban', "sha'ban"],
    'بدوي': ['badawi', 'badawy'],
    'عبد الفتاح': ['abdel-fattah', 'abd el-fattah'],
    'عبد الحميد': ['abdel-hamid', 'abd el-hamid'],
    'عبد الرحمن': ['abdel-rahman', 'abd el-rahman'],
    'عبد العزيز': ['abdel-aziz', 'abd el-aziz'],
    'مرسي': ['morsi', 'mursi', 'morsy'],
    'طنطاوي': ['tantawi', 'tantawy'],
    'مبارك': ['mubarak', 'moubarek'],
    'السادات': ['sadat', 'el-sadat'],
    'حلمي': ['helmy', 'hilmi'],
    'منصور': ['mansour', 'mansur'],
    'سرور': ['sorour', 'surur', 'sorur'],
    'جودة': ['gouda', 'joda', 'jawda'],
    'زكي': ['zaki', 'zaky'],
    'شفيق': ['shafik', 'shafiq', 'shafeek'],

    # Common Egyptian Names & Transliterations
    'محمد': ['mohamed', 'mohammed', 'mohammad', 'muhammad', 'mohamad'],
    'أحمد': ['ahmed', 'ahmad'],
    'محمود': ['mahmoud', 'mahmoud', 'mahmod', 'mahmood'],
    'مصطفى': ['mostafa', 'moustafa', 'mustafa', 'mostapha'],
    'حسين': ['hussein', 'hussain', 'hossein', 'husein'],
    'حسن': ['hassan', 'hasan'],
    'علي': ['ali', 'aly'],
    'إبراهيم': ['ibrahim', 'ebrahim', 'ibraheem'],
    'إسماعيل': ['ismail', 'ismael', 'ismaeel'],
    'يوسف': ['youssef', 'yousef', 'josef', 'yosef'],
    'سعيد': ['said', 'saeed'],
    'سعد': ['saad'],
    'ناصر': ['nasser', 'nasir'],
    'عمرو': ['amr', 'amrou'],
    'عمر': ['omar', 'omer'],
    'خالد': ['khaled', 'khalid'],
    'وليد': ['walid', 'waleed'],
    'هاني': ['hany', 'hani'],
    'سامح': ['sameh'],
    'سمير': ['samir', 'sameer'],
    'عصام': ['essam', 'issam'],
    'شريف': ['sherif', 'sharif'],
    'أشرف': ['ashraf'],
    'مدحت': ['medhat'],
    'رفعت': ['rifaat', 'refaat'],
    'طلعت': ['talaat'],
    'حامد': ['hamed', 'hamid'],
    'حمدي': ['hamdy', 'hamdi'],
    'وجيه': ['wagih', 'wajeeh', 'waguih'],
    'عادل': ['adel', 'adil'],
    'نبيل': ['nabil', 'nabeel'],
    'منير': ['mounir', 'monir'],
    'صبحي': ['sobhy', 'sobhi'],
    'فكري': ['fekry', 'fikry', 'fekri'],
    'لطفي': ['lotfy', 'lutfi', 'lotfi'],
    'هشام': ['hesham', 'hisham'],
    'حازم': ['hazem'],
    'ياسر': ['yasser', 'yasir'],
    'وائل': ['wael'],
    'إيهاب:': ['ehab', 'ihab'],
    'تامر': ['tamer'],
    'هيثم': ['haitham'],
    'عاصم': ['assem', 'assim'],
    'رامز': ['ramez'],
    'رامي': ['ramy', 'rami'],
    'أمير': ['amir', 'ameer'],
    'كمال': ['kamal'],
    'فريد': ['farid', 'fareed'],
    'ممدوح': ['mamdouh', 'mamdooh'],
    'أدهم': ['adham'],
    'إياد': ['eyad', 'iyad'],
    'زياد': ['ziad', 'zeyad'],
    'معتز': ['moataz', 'motaz'],
    'مؤمن': ['moamen', 'momen'],
    'مصعب': ['mosab', 'mosaab'],
    'حمزة': ['hamza', 'hamzah'],
    'بلال': ['bilal'],
    'أنس': ['anas'],
    'يحيى': ['yehia', 'yahya'],
    'زكريا': ['zakaria', 'zakariya'],
    'توفيق': ['tawfik', 'tawfiq'],
    'صفوت': ['safwat'],
    'ثروت': ['tharwat'],
    'مروان': ['marwan'],
    'ريان': ['ryan', 'rayan'],
    'متولي': ['metwally', 'metwalli'],
    'بيومي': ['bayoumi', 'bayoumy'],
    'شحاتة': ['shehata', 'shihata', 'shahatah', 'shahata'],
    'صبري': ['sabry', 'sabri'],
}

ARABIZI_MAP = {
    '2': 'a',   # Hamza/Qaf
    '3': 'a',   # Ain
    '5': 'kh',  # Kha
    '7': 'h',   # Ha
    '8': 'gh',  # Ghain
    '9': 's',   # Sad
    "9'": 'd',  # Dad (represented as 9')
}

ENGLISH_VARIANT_MAP = {}
ENGLISH_TO_ARABIC_MAP = {}

# Build reverse maps: english -> set of english variants, english -> set of arabic originals
for arabic, variants in EGYPTIAN_ARABIC_VARIANTS.items():
    arabic_clean = arabic.rstrip(':')  # Fix typo in 'إيهاب:'
    for v in variants:
        v_lower = v.lower()
        # English -> other English variants
        if v_lower not in ENGLISH_VARIANT_MAP:
            ENGLISH_VARIANT_MAP[v_lower] = set()
        for other in variants:
            if other.lower() != v_lower:
                ENGLISH_VARIANT_MAP[v_lower].add(other.lower())
        # English -> Arabic (reverse transliteration)
        if v_lower not in ENGLISH_TO_ARABIC_MAP:
            ENGLISH_TO_ARABIC_MAP[v_lower] = set()
        ENGLISH_TO_ARABIC_MAP[v_lower].add(arabic_clean)


def _ensure_main_variants_loaded():
    """Lazily load ARABIC_NAME_VARIANTS from complynex_engine into the reverse map."""
    if getattr(_ensure_main_variants_loaded, '_done', False):
        return
    try:
        from .complynex_engine import ARABIC_NAME_VARIANTS
        for arabic, variants in ARABIC_NAME_VARIANTS.items():
            for v in variants:
                v_lower = v.lower()
                if v_lower not in ENGLISH_TO_ARABIC_MAP:
                    ENGLISH_TO_ARABIC_MAP[v_lower] = set()
                ENGLISH_TO_ARABIC_MAP[v_lower].add(arabic)
    except ImportError:
        pass
    _ensure_main_variants_loaded._done = True


# English-to-Arabic character-level reverse transliteration
# Multi-char patterns must be matched first (longest-match-first)
_ENGLISH_TO_ARABIC_MULTI = [
    ('sh', 'ش'), ('kh', 'خ'), ('th', 'ث'), ('gh', 'غ'),
    ('dh', 'ذ'), ('ch', 'ش'), ('ou', 'و'), ('oo', 'و'),
    ('ee', 'ي'), ('ei', 'ي'), ('aa', 'ا'), ('ph', 'ف'),
]

_ENGLISH_TO_ARABIC_SINGLE = {
    'a': 'ا', 'b': 'ب', 't': 'ت', 'j': 'ج', 'h': 'ح',
    'd': 'د', 'r': 'ر', 'z': 'ز', 's': 'س',
    'c': 'ك', 'f': 'ف', 'q': 'ق',
    'k': 'ك', 'l': 'ل', 'm': 'م', 'n': 'ن',
    'w': 'و', 'y': 'ي', 'i': 'ي', 'o': 'و', 'u': 'و',
    'e': 'ي', 'g': 'ج', 'p': 'ب', 'v': 'ف', 'x': 'كس',
}


def _transliterate_english_to_arabic(token):
    """
    Character-level reverse transliteration from English to Arabic.
    Used as fallback when a token is not in the dictionary.
    e.g. 'mejawer' -> 'ميجاوير', 'mabrouk' -> 'مابروك'
    """
    result = []
    i = 0
    token = token.lower()
    while i < len(token):
        matched = False
        # Try multi-char patterns first (longest match)
        for eng, arb in _ENGLISH_TO_ARABIC_MULTI:
            if token[i:i+len(eng)] == eng:
                result.append(arb)
                i += len(eng)
                matched = True
                break
        if not matched:
            ch = token[i]
            if ch in _ENGLISH_TO_ARABIC_SINGLE:
                result.append(_ENGLISH_TO_ARABIC_SINGLE[ch])
            # Skip characters we can't map (rare)
            i += 1
    return ''.join(result)


def generate_arabic_variants(english_name):
    """
    Reverse-transliterate an English name into Arabic script variants.
    e.g. "Sameh Mejawer Mabrouk" -> ["سامح مجاور مبروك"]

    Uses the ENGLISH_TO_ARABIC_MAP (dictionary lookup) first, then falls back
    to character-level reverse transliteration for unknown tokens.

    Multi-word phrase matching: many dictionary keys are multi-word compounds
    (e.g. "abd al rahman", "abd el-fattah") that a naive single-token lookup
    can never reach, since english_name.split() only ever yields one-word
    tokens. This does a greedy longest-match scan (tries 3-word, then 2-word,
    then 1-word windows) so those compound entries are actually used instead
    of silently falling through to the much weaker character-level fallback.
    """
    _ensure_main_variants_loaded()

    if not english_name:
        return []

    tokens = english_name.lower().strip().split()

    # Get Arabic variants for each token/phrase via greedy longest-match
    token_arabic_variants = []
    i = 0
    n = len(tokens)
    while i < n:
        matched = False
        # Try 3-word, then 2-word phrase windows before falling back to 1 word,
        # so multi-word dictionary keys (e.g. "abd al rahman") are reachable.
        for window in (3, 2, 1):
            if i + window > n:
                continue
            phrase = ' '.join(tokens[i:i + window])
            if phrase in ENGLISH_TO_ARABIC_MAP:
                token_arabic_variants.append(list(ENGLISH_TO_ARABIC_MAP[phrase]))
                i += window
                matched = True
                break
        if matched:
            continue

        # No dictionary phrase matched at this position - fall back to
        # character-level reverse transliteration for the single token.
        token = tokens[i]
        fallback = _transliterate_english_to_arabic(token)
        if fallback:
            token_arabic_variants.append([fallback])
        else:
            token_arabic_variants.append([token])
        i += 1

    # Generate combinations (limit to prevent explosion)
    from itertools import product
    all_combos = list(product(*token_arabic_variants))

    # Convert to strings
    variants = [' '.join(combo) for combo in all_combos]

    # Cap at 30 to prevent query bloat
    return list(set(variants))[:30]


def get_english_variants(name):
    """
    Get other English variants for a given name if it exists in our known map.
    e.g. "Gamal" -> ["Jamal"]
    """
    if not name:
        return []
    
    name_lower = name.lower()
    variants = set()
    
    # Check whole name
    if name_lower in ENGLISH_VARIANT_MAP:
        variants.update(ENGLISH_VARIANT_MAP[name_lower])
        
    # Check parts%s 
    # For now, simple whole-part check or part-by-part replacement might be complex.
    # Let's keep it simple: exact matches of known names.
    
    return list(variants)

def normalize_arabizi(text):
    """
    Convert common Arabizi characters to Latin equivalents for phonetic matching.
    Examples: 
    - "mo7amed" -> "mohamed"
    - "3ali" -> "aali" (approximate for phonetic)
    """
    if not text:
        return text
    
    normalized = text.lower()
    
    # Handle composite replacements first if any
    normalized = normalized.replace("9'", "d")
    
    # Single char replacements
    for char, replacement in ARABIZI_MAP.items():
        if char in normalized:
            normalized = normalized.replace(char, replacement)
        
    return normalized

def normalize_prefixes(text):
    """
    Standardize common Arabic name prefixes in English.
    Goal: "Abdel Rahman" == "Abd al-Rahman" == "Abdulrahman"
    """
    if not text:
        return text
        
    normalized = text.lower()
    
    # 1. Normalize separators
    normalized = normalized.replace('-', ' ')
    
    # 2. Handle 'Abd' compounds (Abdel, Abdul, Abd al, Abd el)
    # Standardize to 'abd el' as Egyptian/general bridge form
    normalized = re.sub(r'\babdel\s*', 'abd el ', normalized)
    normalized = re.sub(r'\babdul\s*', 'abd el ', normalized)
    normalized = re.sub(r'\abdal\s*',  'abd el ', normalized)
    normalized = re.sub(r'\babd\s+(al|el|ul)\s*', 'abd el ', normalized)
    normalized = re.sub(r'\babd\s+al\s*', 'abd el ', normalized)
    
    # 3. Handle 'Abu' / 'Umm' / 'Bin' / 'Ibn' / 'Ben' / 'Bint'
    # "Abu Bakr" -> "abu bakr", "Abubakr" -> "abu bakr"
    normalized = re.sub(r'\babubakr', 'abu bakr', normalized)
    normalized = re.sub(r'\babubaker', 'abu bakr', normalized)
    # ibn/ben/bint all standardize to "bin" — linguistically ibn/bin (son of)
    # vs bint (daughter of) differ by gender, and ben is a Maghrebi spelling
    # variant, but for fuzzy screening matches we want "Omar bin Laden" /
    # "Omar ben Laden" / "Fatima bint Mohammed" to all collapse to the same
    # token rather than have an unrelated single-character diff silently
    # lower the match score.
    normalized = re.sub(r'\bibn\s+', 'bin ', normalized)
    normalized = re.sub(r'\bben\s+', 'bin ', normalized)
    normalized = re.sub(r'\bbint\s+', 'bin ', normalized)
    
    # 4. Handle 'Al' / 'El' (The)
    # "Al-Sisi" -> "al sisi", "El-Sisi" -> "al sisi"
    normalized = re.sub(r'(?<!abd )\b(el|al)\s+', 'al ', normalized)  # FIX: protect 'abd el'
    
    # Fix double spaces and trim
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    return normalized

def generate_compound_variants(name):
    """
    Generate variations for compound Arabic/English names.
    Handles both Arabic script and English transliterations.
    """
    variants = {name}
    norm = name.lower().strip()
    
    # English transliteration variants
    if 'abd' in norm:
        if re.search(r'\babd\s+(el|al|ul)\s+', norm):
            base = re.sub(r'\babd\s+(el|al|ul)\s+', '', norm)
            variants.add(f"abdel{base}")
            variants.add(f"abdul{base}")
            variants.add(f"abd el {base}")
            variants.add(f"abd al {base}")
            variants.add(f"abdal{base}")
        elif re.match(r'\b(abdel|abdul|abdal)', norm):
            base = re.sub(r'\b(abdel|abdul|abdal)', '', norm).strip()
            variants.add(f"abdel{base}")
            variants.add(f"abdul{base}")
            variants.add(f"abd el {base}")
            variants.add(f"abd al {base}")
            variants.add(f"abdal{base}")

    # Arabic script variants — both spaced and unspaced forms
    if '\u0639\u0628\u062f' in name:  # عبد
        import re as _gc
        # unspaced → spaced
        spaced = _gc.sub(
            r'\u0639\u0628\u062f\u0627\u0644([\u0600-\u06FF\w])',
            lambda m: '\u0639\u0628\u062f \u0627\u0644' + m.group(1),
            name
        )
        # spaced → unspaced
        unspaced = _gc.sub(r'\u0639\u0628\u062f\s+\u0627\u0644',
                           '\u0639\u0628\u062f\u0627\u0644', name)
        variants.add(spaced)
        variants.add(unspaced)
        variants.add(_gc.sub(r'\s{2,}', ' ', spaced).strip())
        variants.add(_gc.sub(r'\s{2,}', ' ', unspaced).strip())
    if 'ابن' in name:
        variants.add(name.replace('ابن ', 'ابن'))
        variants.add(name.replace('ابن', 'ابن '))

    if 'ابو' in name or 'أبو' in name:
        variants.add(name.replace('أبو ', 'ابو '))
        variants.add(name.replace('أبو', 'ابو'))
        variants.add(name.replace('ابو', 'أبو'))

    # Always add a fully-normalised space-collapsed version
    variants.add(re.sub(r'\s{2,}', ' ', name).strip())

    return list(variants)

