"""
Match profile ("BIO") for one screening hit (Phase 2 / P4-4).

Reads the listed record live from the database (not only what was copied into the screening
result) and lays out everything an analyst needs to decide whether the customer is this person:
names in every script, identity data (dates and places of birth, nationality, gender, identity
documents, the Egyptian national ID decoded), listing data (list, programme / regime, reason,
dates, measures, lifted orders), addresses and positions, the same person on other lists, and the
side-by-side comparison with the screened customer.
"""
import json
import re

from screening import match_intel as mi

HEBREW = re.compile('[֐-׿]')
ARABIC = re.compile('[؀-ۿ]')


def _j(v):
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return v
    s = str(v).strip()
    if not s:
        return None
    if s[:1] in '[{':
        try:
            return json.loads(s)
        except ValueError:
            return s
    return s


def _list(v):
    v = _j(v)
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, dict):
        return []
    return [x.strip() for x in re.split(r'\s*[|;]\s*', str(v)) if x.strip()]


def _uniq(xs):
    out = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out


def mask(v):
    s = re.sub(r'\s', '', str(v or ''))
    if len(s) <= 4:
        return s
    return '•' * (len(s) - 4) + s[-4:]


def load_record(cur, source, rid):
    """(table, row dict) for a hit, or (None, None)."""
    src = (source or '').upper()
    if src.startswith('INTERNAL_BLACKLIST') or src == 'INTERNAL BLACKLIST':
        table = 'internal_blacklist'
    elif src.startswith('INTERNAL_PEP') or src == 'INTERNAL PEP':
        table = 'internal_pep'
    else:
        table = 'screening_watchlist'
    try:
        rid = int(str(rid))
    except (TypeError, ValueError):
        return None, None
    cur.execute(f'SELECT * FROM {table} WHERE id = %s', (rid,))
    row = cur.fetchone()
    return (table, dict(row)) if row else (None, None)


def related(cur, table, row):
    """The same name on other lists (exact name in any script), for 'also listed in'."""
    names = _uniq([row.get('full_name'), row.get('original_name'), row.get('full_name_arabic')])
    names = [n for n in names if n and len(mi.tokens(n)) >= 2][:3]
    if not names:
        return []
    out = []
    cur.execute("""SELECT id, source, dataset, full_name, full_name_arabic, date_of_birth, nationality
                   FROM screening_watchlist WHERE is_active=1
                     AND source NOT IN ('internal_blacklist', 'internal_pep')
                     AND (full_name = ANY(%s) OR original_name = ANY(%s) OR full_name_arabic = ANY(%s))
                   LIMIT 25""", (names, names, names))
    for r in cur.fetchall():
        r = dict(r)
        if table == 'screening_watchlist' and r['id'] == row.get('id'):
            continue
        out.append({'table': 'screening_watchlist', **r})
    cur.execute("""SELECT id, source, category AS dataset, full_name, original_name AS full_name_arabic,
                          date_of_birth, nationality, legal_status
                   FROM internal_blacklist WHERE COALESCE(is_active,1)!=0
                     AND (original_name = ANY(%s) OR full_name = ANY(%s)) LIMIT 25""", (names, names))
    for r in cur.fetchall():
        r = dict(r)
        if table == 'internal_blacklist' and r['id'] == row.get('id'):
            continue
        out.append({'table': 'internal_blacklist', **r})
    return out[:30]


def _nature(row):
    try:
        from screening import list_category as _lc
        return _lc.nature(row)
    except Exception:
        return None


def build(table, row, rel=None, labels=None):
    """Everything the profile page shows."""
    props = _j(row.get('properties')) or {}
    props = props if isinstance(props, dict) else {}
    det = _j(row.get('details'))
    det_d = det if isinstance(det, dict) else {}
    det_text = det if isinstance(det, str) else (' '.join(det) if isinstance(det, list) else None)

    aliases = _uniq(_list(row.get('aliases')) + _list(row.get('aliases_arabic')))
    weak = set(_list(props.get('weak_aliases')))
    names = {
        'primary': row.get('full_name'),
        'original': row.get('original_name') if row.get('original_name') != row.get('full_name') else None,
        'arabic': row.get('full_name_arabic') or (row.get('original_name') if ARABIC.search(row.get('original_name') or '') else None),
        'latin_aliases': [a for a in aliases if not ARABIC.search(a) and not HEBREW.search(a)],
        'arabic_aliases': [a for a in aliases if ARABIC.search(a)],
        'other_script_aliases': [a for a in aliases if HEBREW.search(a)],
        'weak': sorted(weak),
    }

    nid_raw = row.get('national_id') if table != 'screening_watchlist' else None
    nids = _uniq(([nid_raw] if nid_raw else []) + _list(row.get('national_id_numbers')))
    decoded = None
    for n in nids:
        d = re.sub(r'\D', '', n)
        if len(d) == 14:
            dd = mi.decode_egyptian_nid(d) or {}
            if dd.get('valid'):
                decoded = dd
                break
    passports = _uniq(_list(row.get('passport_numbers')) + ([row['passport_number']] if row.get('passport_number') else []))
    other_ids = [i for i in (props.get('identifiers') or []) if isinstance(i, dict)]

    identity = {
        'date_of_birth': row.get('date_of_birth'),
        'all_dates_of_birth': _uniq([d for d in (props.get('dates_of_birth') or []) if d]),
        'dob_source': props.get('dob_source') or det_d.get('dob_note'),
        'place_of_birth': row.get('place_of_birth'),
        'all_places_of_birth': _uniq(props.get('places_of_birth') or []),
        'nationality': row.get('nationality'),
        'all_nationalities': _uniq((props.get('nationalities') or []) + (props.get('citizenships') or [])),
        'gender': row.get('gender'),
        'national_ids': [mask(n) for n in nids],
        'passports': [mask(p) for p in passports],
        'other_ids': [{'type': i.get('type'), 'number': mask(i.get('number'))} for i in other_ids][:12],
        'decoded_nid': decoded,
    }

    listing = {
        'table': table,
        'source': row.get('source'),
        'source_label': ((row.get('source') if row.get('source') not in (None, '', 'INTERNAL') else 'Internal list') + (' — ' + row['category'] if row.get('category') else '')) if table == 'internal_blacklist' else (labels or {}).get(str(row.get('source') or '').lower(), row.get('source')),
        'dataset': row.get('dataset') or row.get('category'),
        'list_type': row.get('list_type'),
        'topics': _list(row.get('topics')),
        'programs': _uniq(_list(props.get('programs')) + _list(det_d.get('programs'))),
        'regime': props.get('regime') or det_d.get('regime'),
        'reason': row.get('reason') or props.get('statement_of_reasons') or props.get('remarks'),
        'other_information': props.get('other_information') or det_text,
        'sanctions_imposed': props.get('sanctions_imposed'),
        'un_reference': props.get('un_reference'),
        'designation_source': props.get('designation_source'),
        'listed_since': props.get('date_designated') or det_d.get('listed') or row.get('first_seen') or row.get('added_date'),
        'last_updated': row.get('last_updated') or row.get('updated_at'),
        'legal_status': row.get('legal_status'),
        'legal_status_note': row.get('legal_status_note'),
        'legal_status_date': row.get('legal_status_date'),
        'case': props.get('case_number') or det_d.get('case'),
        'source_url': row.get('source_url') if str(row.get('source_url') or '').startswith('http') else None,
        'record_id': row.get('source_id') or row.get('id'),
        'risk_level': row.get('risk_level'),
        'category': row.get('category') or row.get('risk_category'),
        'notes': row.get('notes'),
        'nature': _nature(row),
    }
    other = {
        'addresses': _uniq(_list(row.get('addresses')) + ([row['address']] if row.get('address') else [])),
        'positions': _uniq(_list(props.get('positions')) + ([row['position']] if row.get('position') else [])),
        'titles': _list(props.get('titles')),
        'father': det_d.get('father'), 'mother': det_d.get('mother'),
        'linked_entity': det_d.get('linked_entity'),
        'entity_type': row.get('entity_type'),
        'linked_internal': props.get('linked_internal') or [],
    }
    rel = rel or []
    for r in rel:
        r['label'] = (labels or {}).get(str(r.get('source') or '').lower(), r.get('source'))
    return {'names': names, 'identity': identity, 'listing': listing, 'other': other, 'related': rel,
            'display_name': names['arabic'] or names['primary']}
