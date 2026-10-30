"""
Match classification: PEP vs SANCTIONS vs OTHER.

WHY THIS EXISTS
---------------
This used to be done with substring tests inside the Jinja template:

    {% if 'pep' in mtype or 'politici' in mtype or 'peps' in dataset or 'pep' in src %}
    {% elif 'sanction' in mtype or ... %}

That mis-filed genuine PEPs as sanctions hits, which is a serious compliance
error: a PEP requires enhanced due diligence, a sanctions hit requires
blocking. Showing one as the other misrepresents the obligation.

Two concrete failure modes were confirmed in production data:

  1. `list_type` sometimes carries a SOURCE LABEL, not a classification --
     e.g. "OpenSanctions". The sanctions branch tested `'sanction' in mtype`,
     and "opensanctions" contains "sanction", so the record was filed as a
     sanctions match.

  2. The two most authoritative fields were ignored entirely:
       * `category` -- e.g. "Politically Exposed Person" (11 of 33 matches
         on the sample record carried this and were still mis-filed)
       * `topics`   -- OpenSanctions' own taxonomy, e.g. ["role.pep"],
         ["role.pol", "role.pep"], vs ["sanction"], ["sanction.counter"]
     Meanwhile `dataset` values like "wikidata" (rendered in the UI as
     "Egypt PEP - Wikidata") were tested with `'peps' in dataset`, which
     never matches.

DESIGN
------
Decide from the most authoritative signal first and stop:

    topics -> category -> list_type -> dataset -> source -> fallback

`topics` is OpenSanctions' structured taxonomy and is trusted above free-text.
Source labels are stripped before substring tests so "opensanctions" can never
be read as "sanction". A record that is genuinely both (a sanctioned PEP) is
classified as SANCTIONS, because the blocking obligation is the stricter one.
"""

# OpenSanctions taxonomy prefixes
PEP_TOPICS = ('role.pep', 'role.pol', 'role.rca')
SANCTION_TOPICS = ('sanction', 'crime', 'debarment', 'wanted', 'terror')

# Values of list_type/dataset/source that name a SOURCE, not a classification.
# These must never be substring-tested for the word "sanction".
SOURCE_LABELS = (
    'opensanctions', 'open_sanctions', 'open sanctions',
    'wikidata', 'emlcu', 'internal_blacklist', 'internal blacklist',
    'ofac', 'un', 'eu', 'hmt', 'dfat', 'seco',
)

PEP_WORDS = ('pep', 'politically exposed', 'politici', 'royal family',
             'ann_pep', 'pep_positions')
SANCTION_WORDS = ('sanction', 'terror', 'watchlist', 'watch list',
                  'asset freeze', 'legal order', 'debarment', 'embargo')


def _s(v):
    return str(v).strip().lower() if v not in (None, '') else ''


def _topics(m):
    """topics may arrive as a list, a JSON string, or a comma string."""
    raw = m.get('topics')
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [_s(t) for t in raw if t]
    s = _s(raw)
    for ch in '[]"\'':
        s = s.replace(ch, '')
    return [p.strip() for p in s.split(',') if p.strip()]


def _is_source_label(value):
    v = _s(value)
    return any(v == lbl or v.replace(' ', '_') == lbl for lbl in SOURCE_LABELS)


def _has(hay, words):
    return any(w in hay for w in words)


def classify_match(m):
    """Return 'PEP', 'SANCTIONS' or 'OTHER' for one match dict."""
    if not isinstance(m, dict):
        return 'OTHER'

    # 0. regulatory-measures lists (supervisory sanctions on financial institutions / staff):
    #    risk information for due diligence, never a freeze order
    if str(m.get('list_type') or '').strip().upper() == 'REGULATORY' or \
            str(m.get('source') or '').strip().lower().endswith('_reg') or 'reg.action' in _topics(m):
        return 'OTHER'

    topics = _topics(m)
    # 1. structured taxonomy wins. Sanctions outranks PEP: if an entity is
    #    both, the blocking obligation is the stricter one.
    if topics:
        if any(t.startswith(SANCTION_TOPICS) for t in topics):
            return 'SANCTIONS'
        if any(t.startswith(PEP_TOPICS) for t in topics):
            return 'PEP'

    # 2. explicit category text
    cat = _s(m.get('category'))
    if cat:
        if _has(cat, PEP_WORDS):
            return 'PEP'
        if _has(cat, SANCTION_WORDS):
            return 'SANCTIONS'

    # 3. list_type -- but ONLY if it is a real classification, not a source
    #    label. "OpenSanctions" here means "this came from OpenSanctions",
    #    it does not mean the entity is sanctioned.
    lt = _s(m.get('list_type'))
    if lt and not _is_source_label(lt):
        if _has(lt, PEP_WORDS):
            return 'PEP'
        if _has(lt, SANCTION_WORDS):
            return 'SANCTIONS'

    # 4/5. dataset and source names
    for field in ('dataset', 'source', 'source_name'):
        v = _s(m.get(field))
        if not v:
            continue
        if _has(v, PEP_WORDS):
            return 'PEP'
        if not _is_source_label(v) and _has(v, SANCTION_WORDS):
            return 'SANCTIONS'

    # 6. dataset names that are known PEP feeds but carry no keyword
    if _s(m.get('dataset')) in ('wikidata', 'ann_pep_positions'):
        return 'PEP'

    # 7. anything still unknown is surfaced as a sanctions-side hit so it is
    #    never silently hidden from the reviewer.
    return 'SANCTIONS'


def split_matches(matches):
    """Split a match list into (sanctions, pep, other)."""
    sanctions, pep, other = [], [], []
    for m in (matches or []):
        k = classify_match(m)
        if k == 'PEP':
            pep.append(m)
        elif k == 'SANCTIONS':
            sanctions.append(m)
        else:
            other.append(m)
    return sanctions, pep, other
