"""Spelling families the core normaliser does not cover (Phase 3: P3-7 Franco-Arabic, P3-8 dialects).

Called from match_intel.normalize() on the lower-cased Latin form, before the core spelling rules:

* Accents and Turkish / French letters are folded (Saïd = Said, Hüseyin = Huseyin, Şerif = Sherif);
  without this they were cut out of the name (Sa d).
* Franco-Arabic: digits written inside a Latin name stand for Arabic letters (Mo7amed, 3ali, 5aled,
  Ra2fat, 7'alil). They are turned into the Latin letters the rest of the engine already understands.
  A token made only of digits is left alone.
* Dialect spellings: Maghrebi French (Houcine, Hacen, Lahcen, Mhamed, Youcef, Brahim, ould), Turkish
  (Mehmet, Ahmet, Mahmut, Hüseyin) and Gulf / South-Asian abbreviations (Mohd) are recognised as the
  usual spelling of the same name (canon(); whole known names only, used as a second chance).

General rules only: no name list from the Gold Set is used here.
"""
import re
import unicodedata

_FOLD = str.maketrans({'ı': 'i', 'ş': 'sh', 'ș': 'sh', 'ç': 'c', 'ğ': 'g', 'ß': 'ss', 'ø': 'o',
                       'æ': 'ae', 'œ': 'oe', 'đ': 'd', 'ł': 'l', 'ð': 'd', 'þ': 'th',
                       'ʿ': "'", 'ʾ': "'", 'ʼ': "'", '‘': "'", '´': "'"})

# Franco-Arabic digits.  2 = ء and 3 = ع are dropped next to a vowel (the engine treats ع / ء as
# free); between two consonants 3 reads as a.  7' / 5 = خ, 3' / 8 = غ / ق, 9 = ق (Gulf) / ص,
# 6 = ط.
_FRANCO_PAIRS = (("7'", 'kh'), ("3'", 'gh'), ('5', 'kh'), ('7', 'h'), ('8', 'q'), ('9', 'q'), ('6', 't'))
_VOWEL = set('aeiouy')
_HAS_DIGIT = re.compile(r'\d')
_HAS_LETTER = re.compile('[a-z]')
_WORD = re.compile(r"[a-z0-9']+")


def fold(t):
    """Accented / special Latin letters -> plain a-z (Saïd -> said, Hüseyin -> huseyin)."""
    t = t.translate(_FOLD)
    if t.isascii():
        return t
    t = unicodedata.normalize('NFKD', t)
    return ''.join(ch for ch in t if not unicodedata.combining(ch))


def _franco_word(w):
    if not _HAS_DIGIT.search(w) or not _HAS_LETTER.search(w):
        return w
    for a, b in _FRANCO_PAIRS:
        w = w.replace(a, b)
    out = []
    for i, ch in enumerate(w):
        if ch in '23':
            prev = w[i - 1] if i else ''
            nxt = w[i + 1] if i + 1 < len(w) else ''
            if ch == '3' and prev not in _VOWEL and nxt not in _VOWEL and (prev or nxt):
                out.append('a')       # s3d = sa'd, 3mr = 'amr
            continue                  # next to a vowel: ع / ء carry no Latin letter
        out.append(ch)
    return ''.join(out)


def franco(t):
    """Digits inside Latin words -> letters (Mo7amed -> mohamed, 3ali -> ali, 5aled -> khaled)."""
    if not _HAS_DIGIT.search(t):
        return t
    return _WORD.sub(lambda m: _franco_word(m.group(0)), t)


# Dialect spellings of well-known names (P3-8).  They are NOT rewritten in normalize(): a foreign
# spelling must still be compared as written with an Arabic rendering of it (Husayn = حوساين,
# Mehmet = ميحميت).  canon() is used as a second chance only, when two elements did not match as
# written (match_intel._same_token).  Input is an element already normalised by match_intel
# (lower case, doubled letters collapsed, ou -> u).
_DIALECT = [
    (r'^(?:mohd|muhd)$', 'mohamed'),                                       # Gulf / South-Asian abbreviation
    (r'^(?:m[eu]hme[dt]|m[ou]+hamm?[ae]t|mh?amm?[ae]d)$', 'mohamed'),      # Mehmet, Muhammet, Mhamed
    (r'^ahmet$', 'ahmed'),
    (r'^mahmut$', 'mahmoud'),
    (r'^brahim$', 'ibrahim'),
    (r'^dris+$', 'idris'),
    (r'^l?h[ou]+(?:c|s+)(?:aine|ine|eyin|ein)$', 'hussein'),              # Houcine, Houssine, Huseyin
    (r'^(?:la)?h[ae]?(?:c|s+)[ae]ne?$', 'hassan'),                         # Hacen, Hacene, Lahcen, Lahsen
    (r'^y[ou]+(?:c|s+)[eo]f$', 'youssef'),                                 # Youcef
    (r'^y[ae](?:c|s+)ine?$', 'yassin'),                                    # Yacine
    (r'^m[ou]+h(?:c|s+)[ei]ne?$', 'mohsen'),                               # Mouhcine
    (r'^f[ae][iy](?:c|s+)[ae]l$', 'faisal'),                               # Faycel
    (r'^amine$', 'amin'),
]
_DIALECT_RX = [(re.compile(p), r) for p, r in _DIALECT]
_REP_NORM = {}


def canon(tok):
    """The usual spelling of a dialect form of a well-known name, normalised like match_intel does
    (Houcine -> hussein, Mehmet -> mohamed, Youcef -> yusef); any other element is returned as is."""
    for rx, rep in _DIALECT_RX:
        if rx.match(tok):
            if rep not in _REP_NORM:
                from screening import match_intel as mi
                _REP_NORM[rep] = mi.normalize(rep)
            return _REP_NORM[rep]
    return tok


def latin(t):
    """Pre-pass for a lower-cased Latin name inside match_intel.normalize(): accents folded,
    Franco-Arabic digits read as letters, Maghrebi "ould" (son of) read as bin."""
    t = franco(fold(t))
    return re.sub(r'\bould\b', 'bin', t)
