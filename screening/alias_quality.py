"""G8 — weak aliases never raise an alert on their own.

Lists mark some a.k.a. names as low quality: OFAC "weak" AKAs and the UK
list's low-quality aliases (both stored in properties.weak_aliases by the
loaders). Very short aliases of a PERSON are treated the same way: an
alias of four letters or fewer, or a one-word alias (a nickname such as
"Hamza"). Companies keep their one-word names and acronyms (IRGC) as
normal names.

Rule (applied after the analyst decision layer, before the alert filter):
when the query matches the record ONLY through such an alias - every strong
form of the record (its names and normal aliases) scores below the alert
threshold while a weak alias scores at or above it - the hit is capped just
below the threshold, unless an identifier agrees (national ID, date of birth,
passport), in which case it stays and the explanation says that it matched
through a weak alias. Internal lists are never touched.

Passport: the screening form, the API and customer screening have no passport
input today, so only a national ID or date of birth can keep such a hit; the
engine passes passport= to apply_decisions as soon as an input carries one.
"""
import json
import logging
import re
import unicodedata

from screening import match_intel as mi

logger = logging.getLogger(__name__)

SHORT_LETTERS = 4
MAX_FORMS = 400          # safety bound; a record with more forms than this is never capped
REASON_CAPPED = ('matched only through a weak alias (low-quality / short AKA on the list): '
                 'not an alert on its own')
REASON_KEPT = 'matched through a weak alias (low-quality / short AKA on the list); an identifier agrees'

_NON_PERSON = {'ENTITY', 'ORGANIZATION', 'ORGANISATION', 'COMPANY', 'LEGALENTITY', 'LEGAL_ENTITY',
               'VESSEL', 'AIRCRAFT', 'ASSET', 'SECURITY'}


def _j(v):
    if isinstance(v, str) and v.strip()[:1] in ('[', '{'):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


def _list(v):
    v = _j(v)
    if v is None or isinstance(v, dict):
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x).strip() for x in v if x is not None and str(x).strip()]
    return [x.strip() for x in re.split(r'\s*[|;]\s*', str(v)) if x.strip()]


def _key(s):
    return ' '.join(str(s or '').casefold().split())


def _letters(s):
    return sum(1 for c in str(s or '') if unicodedata.category(c).startswith('L'))


def is_person(m):
    return str(m.get('entity_type') or 'INDIVIDUAL').strip().upper().replace(' ', '') not in _NON_PERSON


def is_short_alias(alias, person=True):
    """A person's alias of <= 4 letters or of one word. Companies and other
    entities keep short names and acronyms (IRGC, ISIL) as normal names."""
    if not person:
        return False
    if _letters(alias) <= SHORT_LETTERS:
        return True
    # elements as the matcher reads them: ابومحمد / عبدالرحمن are two elements, not one word
    try:
        n = len(mi.tokens(alias))
    except Exception:
        n = len([w for w in str(alias or '').split() if _letters(w)])
    return n <= 1


def split_forms(m):
    """(strong forms, weak aliases, truncated) of one listed record. Every strong form is read: a strong
    alias left unread could make a real hit look as if it rested on a weak alias only."""
    props = _j(m.get('properties'))
    props = props if isinstance(props, dict) else {}
    marked = {_key(a) for a in _list(props.get('weak_aliases'))}
    person = is_person(m)
    main = [m.get('watchlist_name_ar'), m.get('original_name'), m.get('full_name_arabic'),
            m.get('full_name'), m.get('candidate_name')]
    strong = [n for n in dict.fromkeys(str(x).strip() for x in main if x) if n]
    main_keys = {_key(n) for n in strong}
    weak = []
    truncated = False
    for a in dict.fromkeys(_list(m.get('aliases')) + _list(m.get('aliases_arabic'))):
        if len(strong) + len(weak) >= MAX_FORMS:
            truncated = True
            break
        k = _key(a)
        if k in main_keys:
            continue
        if k in marked or is_short_alias(a, person):
            weak.append(a)
        else:
            strong.append(a)
    # a marked-weak name never counts as strong, even when it is also the caption
    weak += [n for n in strong if _key(n) in marked and n not in weak]
    strong = [n for n in strong if _key(n) not in marked]
    return strong, weak, truncated


def _best(query, forms):
    best, best_form = 0.0, None
    q_ar = mi.is_arabic(query)
    for f in forms:
        try:
            s = float(mi.name_match(query, f)['score'])
        except Exception:
            continue
        if mi.is_arabic(f) != q_ar:
            s *= 0.97                                  # transliteration is never certain
        if s > best:
            best, best_form = s, f
    return best, best_form


def _internal(m):
    return bool(m.get('is_internal')) or str(m.get('source') or '').upper().startswith('INTERNAL')


def check(m, query, low=None):
    """None, or {'state': 'capped'|'kept', 'alias', 'weak_score', 'strong_score'}."""
    low = float(low if low is not None else mi.LOW)
    if _internal(m):
        return None
    strong, weak, truncated = split_forms(m)
    if not weak or truncated:
        return None                                    # unread forms: never cap on partial evidence
    ws, wform = _best(query, weak)
    if ws < low:
        return None
    ss, _ = _best(query, strong)
    if ss >= low or ss >= ws:
        return None                                    # a strong name explains the hit
    d = m.get('decision') or {}
    state = 'kept' if d.get('identifier_match') or d.get('identity') == 'id_match' else 'capped'
    return {'state': state, 'alias': wform, 'weak_score': round(ws, 2), 'strong_score': round(ss, 2)}


def apply(matches, query, low=None):
    """Cap hits that rest only on a weak alias (mutates and returns the list)."""
    low = float(low if low is not None else mi.LOW)
    for m in matches:
        try:
            r = check(m, query, low)
        except Exception as e:                          # never drop a hit because of this layer
            logger.warning('[ALIAS-QUALITY] check failed: %s', e)
            continue
        if not r:
            continue
        d = m.setdefault('decision', {})
        d['weak_alias'] = r
        reasons = d.setdefault('reasons', [])
        if r['state'] == 'kept':
            reasons.append(REASON_KEPT)
            continue
        score = min(float(m.get('match_score') or 0.0), low - 1)
        m['match_score'] = round(score, 2)
        d['final_score'] = m['match_score']
        d['tier'] = 'BELOW'
        reasons.append(REASON_CAPPED)
    return matches
