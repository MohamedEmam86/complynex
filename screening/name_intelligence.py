# =============================================================================
# Arabic name intelligence — the reasoning steps the scorer was missing.
#
# Added after a labelled test set (tools/healthcheck/name_logic_probe.py)
# showed the engine misjudging 5 of 20 pairs. Each function here implements one
# step a compliance officer applies when deciding whether two Arabic names are
# the same person.
# =============================================================================
import re as _re
import re

# --- Arabic phonetic classes -------------------------------------------------
# Soundex and Metaphone are English algorithms. On Arabic, soundex returns the
# first letter followed by 000 (محمد -> 'م000', محمود -> 'م000', محسن -> 'م000')
# and metaphone returns nothing at all — yet the phonetic step carried 15% of
# the score. Any two Arabic names starting with the same letter scored a perfect
# phonetic match.
#
# These classes group the consonants that are ACTUALLY confused in Arabic
# speech and transcription, which is what a phonetic step is supposed to model.
_AR_PHONETIC_CLASSES = {
    'ا': 'A', 'أ': 'A', 'إ': 'A', 'آ': 'A', 'ى': 'A', 'ء': 'A', 'ؤ': 'A', 'ئ': 'A',
    'ب': 'B', 'پ': 'B',
    'ت': 'T', 'ط': 'T', 'ة': 'T',
    'ث': 'S', 'س': 'S', 'ص': 'S',
    'ج': 'G', 'چ': 'G',
    'ح': 'H', 'ه': 'H',
    'خ': 'X',
    'د': 'D', 'ض': 'D',
    'ذ': 'Z', 'ز': 'Z', 'ظ': 'Z',
    'ر': 'R',
    'ش': 'C',
    'ع': 'E', 'غ': 'E',
    'ف': 'F', 'ڤ': 'F',
    'ق': 'K', 'ك': 'K',
    'ل': 'L',
    'م': 'M',
    'ن': 'N',
    'و': 'W',
    'ي': 'Y',
}

_ARABIC_RE = re.compile(r'[؀-ۿ]')

# Words that are structural, not identifying: the definite article, patronymic
# particles, and the 'servant-of' prefix that begins compound theophoric names.
_PARTICLES = {'ال', 'بن', 'ابن', 'بنت', 'ابو', 'أبو', 'عبد', 'آل',
              'al', 'el', 'bin', 'ben', 'ibn', 'abu', 'abou', 'abd', 'abdel'}


def is_arabic(text):
    return bool(_ARABIC_RE.search(str(text or '')))


def arabic_phonetic_key(token):
    """Phonetic key for one Arabic token using Arabic confusion classes.

    Unlike soundex it uses the WHOLE token, so محمد and محمود produce different
    keys, while ثابت/سابت (ث/س) and حسن/هسن (ح/ه) — genuine Arabic confusions —
    produce the same one.
    """
    t = str(token or '').strip()
    if not t:
        return ''
    out = []
    for ch in t:
        c = _AR_PHONETIC_CLASSES.get(ch)
        if c:
            # collapse doubled sounds
            if not out or out[-1] != c:
                out.append(c)
    return ''.join(out)


def phonetic_similarity_arabic(a, b):
    """0..1 similarity between two Arabic names on phonetic keys."""
    ka = [arabic_phonetic_key(t) for t in str(a).split() if t]
    kb = [arabic_phonetic_key(t) for t in str(b).split() if t]
    ka = [k for k in ka if k]
    kb = [k for k in kb if k]
    if not ka or not kb:
        return 0.0
    sa, sb = set(ka), set(kb)
    return len(sa & sb) / max(len(sa), len(sb))


# --- name structure ----------------------------------------------------------
def name_parts(name):
    """Split into (first, middles, family), ignoring particles.

    Egyptian names run ism + father + grandfather + family. The first and last
    elements carry identity; the middles are patronymics.
    """
    toks = [t for t in str(name or '').split() if t]
    core = [t for t in toks if t.lower() not in _PARTICLES]
    if not core:
        return ('', [], '')
    if len(core) == 1:
        return (core[0], [], '')
    return (core[0], core[1:-1], core[-1])


_FUSED_RE = _re.compile(r'\b(عبد|ابو|أبو|بن|ابن)(ال[\u0621-\u064A]{2,})')


def _split_fused_compounds(text):
    """Split fused compounds so both spellings tokenise identically.

    عبدالرحمن -> عبد الرحمن.  Written fused, the particle عبد is not recognised
    and is never dropped, so 'عبد الرحمن' and 'عبدالرحمن' compared as different
    family names — including a real PEP against his own record. Both spellings
    are common in Egyptian records, often in the same file.
    """
    s = str(text or '')
    prev = None
    while prev != s:                      # عبدالله بنالوليد -> both split
        prev = s
        s = _FUSED_RE.sub(r'\1 \2', s)
    return s


def _core_tokens(name):
    """Identity-bearing tokens: Arabic normalised, particles dropped, Latin
    canonicalised.

    Normalising HERE rather than relying on the caller matters: حسني and حسنى are
    the same name, and without normalisation they are two different tokens. That
    made the short-form test fail on 'حسني مبارك' vs 'محمد حسنى السيد مبارك'
    — Hosni Mubarak against his own asset-freeze listing.
    """
    raw = str(name or '')
    try:
        from screening.utils.normalization import normalize_arabic_text as _n
        raw = _n(raw) or raw
    except Exception:
        pass
    raw = _split_fused_compounds(raw)
    toks = [t for t in raw.split() if t]
    if not any(is_arabic(t) for t in toks):
        toks = canonicalise_latin(' '.join(toks)).split()
    return [t.lower() for t in toks if t.lower() not in _PARTICLES]


def family_name_verdict(a, b):
    """Compare the family (last) name — but only when that comparison is
    meaningful.

    Egyptian naming makes the last element decisive: two people sharing three
    common given names but differing on the family name are different people
    ('اشرف محمد احمد منصور' vs 'اشرف محمد احمد الصعيدي').

    But "last tokens differ" does not always mean different people. Three cases
    where the comparison must NOT be applied:

      * REORDERING  — same token set, different order ('Saddam Hussein' /
                      'Hussein Saddam'). Order carries no identity here.
      * TRUNCATION  — the shorter name stops earlier in the patronymic chain,
                      so its last token appears mid-chain in the longer name.
      * SPELLING    — 'Nasser' / 'Nasir'. Compared on canonical forms.

    Returns 'match' | 'mismatch' | 'unknown'. 'unknown' leaves the score alone.
    """
    from rapidfuzz import fuzz

    ca, cb = _core_tokens(a), _core_tokens(b)
    if not ca or not cb:
        return 'unknown'

    # 1. identical token sets -> reordering, not a different family
    if set(ca) == set(cb):
        return 'match'

    fa, fb = ca[-1], cb[-1]

    if fa == fb or fuzz.ratio(fa, fb) >= 85:
        return 'match'
    if is_arabic(fa) and is_arabic(fb) and \
            arabic_phonetic_key(fa) == arabic_phonetic_key(fb):
        return 'match'

    # 2. truncated chain: the shorter name's last token sits inside the longer
    shorter, longer = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    if len(shorter) < len(longer):
        tail = shorter[-1]
        if tail in longer:
            return 'unknown'          # a truncation, not a contradiction
        if any(fuzz.ratio(tail, t) >= 85 for t in longer):
            return 'unknown'

    return 'mismatch'


def token_present(token, tokens):
    """Is this name element present among those tokens, allowing for spelling?

    Exact, then fuzzy, then Arabic phonetic — the same ladder used elsewhere, so
    حسني finds حسنى and Nasser finds Nasir.
    """
    from rapidfuzz import fuzz
    for t in tokens:
        if token == t or fuzz.ratio(token, t) >= 80:
            return True
        if is_arabic(token) and is_arabic(t) and \
                arabic_phonetic_key(token) == arabic_phonetic_key(t):
            return True
    return False


def given_name_conflict(a, b):
    """True when the given names contradict each other.

    A shared family name is not identity. عبد اللطيف is a common Egyptian
    family name, and 'محمود عماد أحمد عبد اللطيف' vs 'شعبان رافت احمد عبد
    اللطيف' scored 92.5 on family agreement alone despite being two unrelated
    people.

    Conflict requires the contradiction to run BOTH ways — A's given name absent
    from B and B's given name absent from A. That two-way test is what keeps the
    legitimate cases safe: in a reordering, a mid-chain form or a truncated
    chain, at least one given name is still present in the other name.
    """
    ca, cb = _core_tokens(a), _core_tokens(b)
    if len(ca) < 2 or len(cb) < 2:
        return False                       # too little structure to judge
    if set(ca) == set(cb):
        return False                       # reordering

    def _unmatched(these, those):
        """This name's own elements that appear nowhere in the other."""
        return [t for t in these if not token_present(t, those)]

    # A given name missing from the other side is only a contradiction when
    # this name also carries its own unmatched content. Without that second
    # test, حسني مبارك inside محمد حسنى السيد مبارك would read as a conflict;
    # with it, the short form is protected (nothing of it is unmatched) while
    # محمود عماد أحمد عبد اللطيف against احمد عبد الرحمن عبد اللطيف is caught
    # — محمود and عماد appear nowhere in the listed name, so the shared احمد
    # and عبد اللطيف are a family coincidence, not identity.
    ua, ub = _unmatched(ca, cb), _unmatched(cb, ca)

    # 1. does a given name go missing in either direction?
    given_absent = (not token_present(ca[0], cb)) or \
                   (not token_present(cb[0], ca))
    # 2. does each name carry content the other lacks? If one is contained in
    #    the other it is a short form or a truncated chain, not a contradiction
    #    — this is what protects حسني مبارك inside محمد حسنى السيد مبارك.
    #
    #    But containment only excuses a differing given name when one name is
    #    genuinely SHORTER. احمد زكريا احمد محمد is contained in ولاء زكريا احمد
    #    محمد too, and they are four elements each: neither abbreviates the
    #    other, so there is no innocent reason for the first element to differ.
    #    That pair scored 100 and is a large part of why 27% of merchants were
    #    flagging.
    _lo, _hi = min(len(ca), len(cb)), max(len(ca), len(cb))
    comparable_length = _hi > 0 and (_lo / float(_hi)) >= 0.8
    both_have_own = comparable_length or (bool(ua) and bool(ub))
    # 3. and the divergence must be more than one element, so a single spelling
    #    difference cannot reject a pair on its own.
    substantial = max(len(ua), len(ub)) >= 1

    return bool(given_absent and both_have_own and substantial)


def thin_name_conflict(a, b):
    """True when one name is a single element and the other is a full name.

    A watchlist record holding only 'Amjad' or 'Abdelrahman' matches every
    merchant sharing that one given name, and the similarity components
    encourage it: partial-ratio returns 100 for any substring, which a
    single-token candidate always is.

    Requires the other side to hold two or more elements, so a mononym compared
    with a mononym is unaffected.
    """
    ca, cb = _core_tokens(a), _core_tokens(b)
    if not ca or not cb:
        return False
    lo, hi = min(len(ca), len(cb)), max(len(ca), len(cb))
    return lo < 2 and hi >= 2


def names_are_effectively_same(a, b, non_distinctive=frozenset()):
    """True when two names are the same name, however common their tokens.

    Guards the distinctive-token rule. Many Egyptian names consist entirely of
    common elements — خالد محمد احمد عبد الرحمن is four of them — and demanding
    a rare shared token would reject such a name against its own record. That
    is how a listed PEP disappeared from his own screening result.
    """
    from rapidfuzz import fuzz
    ca, cb = _core_tokens(a), _core_tokens(b)
    if not ca or not cb:
        return False

    # SEQUENCE equality, not set equality, and at least two elements.
    #
    # Matching on the set alone waved through 'Ahmed El said' against 'Said
    # AHMED' and 'Abu walid' against 'EL WALID' — both scored 100 by bypassing
    # every later check. Reordered names are no longer treated as identical
    # here; they go to the rarity gate instead, which keeps صدام حسين / حسين
    # صدام (evidence 13.4) and drops the pairs built from common elements.
    if len(ca) >= 2 and ca == cb:
        return True

    # No containment branch. 'A is contained in B' is the definition of a short
    # form, not of sameness, and treating it as sameness exempted four false
    # positives from the rarity gate. Real short forms clear the gate on their
    # own evidence (Mubarak 12.09, Bin Laden 18.77) rather than by exemption.
    if len(ca) < 2 or len(cb) < 2:
        return False
    return fuzz.ratio(' '.join(ca), ' '.join(cb)) >= 90


# Calibrated by grid search over 22 labelled pairs: keeps 10/10 true matches
# and removes 9/12 false ones. See calibrate_idf2.
MIN_SHARED_EVIDENCE = 8.5
MIN_EVIDENCE_COVERAGE = 0.30


def evidence_too_thin(a, b, non_distinctive=frozenset()):
    """Does this match rest on too little identifying information?

    Two names can overlap on three of four elements and still share almost
    nothing, if those three are محمد, احمد and السيد — which between them appear
    in 37%, 21% and 7% of Egyptian names.

    Returns False (i.e. does not object) for:
      * names that are effectively the same name — a record must always match
        itself, however common its elements;
      * cross-script pairs, where Arabic and Latin tokens cannot overlap by
        construction and the measure would be meaningless. Cross-script matching
        is handled upstream by variant generation.
    """
    try:
        from screening.name_idf import name_evidence, shared_evidence
    except Exception:
        return False                      # never block screening on this

    ca, cb = _core_tokens(a), _core_tokens(b)
    if not ca or not cb:
        return False
    if is_arabic(ca[0]) != is_arabic(cb[0]):
        return False
    if names_are_effectively_same(a, b, non_distinctive):
        return False

    ev = shared_evidence(ca, cb)
    hi = max(name_evidence(ca), name_evidence(cb))
    cov = (ev / hi) if hi > 0 else 0.0
    return ev < MIN_SHARED_EVIDENCE or cov < MIN_EVIDENCE_COVERAGE


def coverage_both_ways(a, b, non_distinctive=frozenset()):
    """How much of each name's DISTINCTIVE content appears in the other.

    A short form inside a full patronymic chain ('Osama Bin Laden' inside
    'Usama Bin Muhammed Bin Awad Bin Laden') shows high coverage one way and
    low the other. Symmetric measures cannot see that, which is why the engine
    scored that pair 75.0 and missed it.
    """
    # canonicalise Latin spellings first, so 'Osama' and 'Usama' count as the
    # same token rather than two different ones
    da = {t for t in _core_tokens(a) if t not in non_distinctive}
    db = {t for t in _core_tokens(b) if t not in non_distinctive}
    if not da or not db:
        return (0.0, 0.0)
    inter = da & db
    return (len(inter) / len(da), len(inter) / len(db))


def is_short_form(a, b, non_distinctive=frozenset()):
    """True when one name is plausibly the short form of the other.

    Requires the shorter name's distinctive tokens to be almost entirely
    contained in the longer one, AND the first and family names to agree —
    containment alone is what produced the original false positives.
    """
    from rapidfuzz import fuzz
    ca, cb = coverage_both_ways(a, b, non_distinctive)
    if max(ca, cb) < 0.99:
        return False
    ta, tb = _core_tokens(a), _core_tokens(b)
    if not ta or not tb:
        return False

    # A short form has to be short FOR something. Some watchlist records hold
    # only a given name ('Amjad', 'Amr Mohamed'); containment then makes every
    # merchant sharing that name look like the same person, and those scored
    # 100 against an independent similarity of 8.
    #
    # Require the shorter name to carry two identity-bearing tokens and to share
    # at least one that is not merely common. 'Osama Bin Laden' passes — two
    # tokens, 'laden' rare. 'Amjad' does not.
    _short = ta if len(ta) <= len(tb) else tb
    if len(_short) < 2:
        return False
    _shared = set(ta) & set(tb)
    _distinct_shared = _shared - set(non_distinctive)
    if not _distinct_shared:
        return False
    # One distinctive token is not enough on its own: 'Amr Mohamed' shares only
    # 'amr' with 'AMR MOHAMED ABD-RABO ABD-ALLA' and is two given names with no
    # family name. Either a second distinctive token, or genuine family-name
    # agreement, has to corroborate it.
    if len(_distinct_shared) < 2 and family_name_verdict(a, b) != 'match':
        return False

    # The known name's given element may sit ANYWHERE in the full legal chain,
    # not at position 0. Hosni Mubarak is listed as محمد حسنى السيد مبارك, where
    # حسني is third. Requiring ta[0] == tb[0] missed him entirely. Most public
    # figures follow this pattern, so the given name is looked for anywhere in
    # the longer name.
    shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    given = shorter[0]

    def _same(x, y):
        if x == y or fuzz.ratio(x, y) >= 80:
            return True
        return (is_arabic(x) and is_arabic(y)
                and arabic_phonetic_key(x) == arabic_phonetic_key(y))

    first_ok = any(_same(given, t) for t in longer)
    # and the family name must not actively contradict
    fam_ok = family_name_verdict(a, b) in ('match', 'unknown')
    return bool(first_ok and fam_ok)


# --- Latin transliteration canonicalisation ---------------------------------
# 'Mohamed Hassan' vs 'Muhammad Hasan' scored 78.6 and was missed. The variant
# dictionary was only applied on the Arabic->English path, so two Latin
# spellings of the same Arabic name were compared as raw strings.
_LATIN_CANON = {}


def _seed_latin_canon():
    if _LATIN_CANON:
        return
    groups = [
        ('mohamed', ['mohammed', 'muhammad', 'mohammad', 'mohamad',
                     'muhammed', 'mohamet', 'mehmet', 'muhamad']),
        ('ahmed', ['ahmad', 'ahmet', 'ahmd']),
        ('hassan', ['hasan', 'hasaan', 'hassaan', 'hassen']),
        ('hussein', ['hussain', 'hosein', 'husayn', 'husein', 'hussien']),
        ('mahmoud', ['mahmood', 'mahmud', 'mahmut']),
        ('ibrahim', ['ibraheem', 'ebrahim', 'brahim']),
        ('youssef', ['yousef', 'yusuf', 'yousif', 'yousuf', 'joseph']),
        ('mostafa', ['mustafa', 'moustafa', 'mustapha']),
        ('abdel', ['abdul', 'abd', 'abdal', 'abdel', 'abdo']),
        ('gamal', ['jamal', 'gamaal', 'jamaal']),
        ('nasser', ['nasir', 'naser', 'nassir', 'nasr']),
        ('ali', ['aly', 'aley']),
        ('omar', ['umar', 'omer']),
        ('khaled', ['khalid', 'khaleed']),
        ('said', ['saeed', 'sayed', 'sayyid', 'saied']),
        ('sherif', ['shareef', 'sharif']),
        ('tarek', ['tariq', 'tarik']),
        ('yasser', ['yasir', 'yaser']),
        ('salah', ['salaah', 'saleh', 'salih']),
        ('osama', ['usama', 'oussama']),
        ('saddam', ['sadam']),
        ('laden', ['ladin']),
        ('bashar', ['bashaar']),
        ('assad', ['asad', 'assaad']),
    ]
    for canon, variants in groups:
        _LATIN_CANON[canon] = canon
        for v in variants:
            _LATIN_CANON[v] = canon


def canonicalise_latin(name):
    """Map Latin spelling variants to one canonical form before comparing."""
    _seed_latin_canon()
    out = []
    for t in re.split(r'[\s\-_]+', str(name or '').lower()):
        t = t.strip('.,')
        if not t:
            continue
        if t in _PARTICLES:
            continue
        out.append(_LATIN_CANON.get(t, t))
    return ' '.join(out)
