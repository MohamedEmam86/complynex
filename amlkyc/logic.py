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
Pure decision logic for AML & KYC assurance — no Flask, no database, no
regulator-specific values. Thresholds and cycles arrive as arguments (read
by the caller from the regcontrols parameter registry or check_config).
"""

import random
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta


def _txt(v):
    return (v or '').strip().lower() if isinstance(v, str) else ('' if v is None else str(v).lower())


# --------------------------------------------------------------------------
# Key roles: independence and conflicts
# --------------------------------------------------------------------------

def role_conflicts(role, rules):
    """Conflicts of one key-role record against the rule set.

    role: dict with role_code, reports_to_title, reports_to_board, other_positions, title.
    rules: dicts with role_code, rule_type ('holds' | 'reports_to'), keyword, reason_en.
    Returns list of (rule_type, keyword, reason). Reporting to the board
    satisfies independence: reports_to rules are then not evaluated.
    """
    out = []
    for r in rules:
        if not r.get('is_active', True) or r['role_code'] != role.get('role_code'):
            continue
        kw = _txt(r['keyword'])
        if r['rule_type'] == 'reports_to':
            if role.get('reports_to_board'):
                continue
            if kw and kw in _txt(role.get('reports_to_title')):
                out.append(('reports_to', r['keyword'], r.get('reason_en') or ''))
        elif r['rule_type'] == 'holds':
            if kw and kw in _txt(role.get('other_positions')):
                out.append(('holds', r['keyword'], r.get('reason_en') or ''))
    return out


def combined_role_unapproved(role):
    """A role holder with other positions needs an approval reference."""
    return bool(_txt(role.get('other_positions'))) and not (role.get('combined_role_approval_ref') or '').strip()


# --------------------------------------------------------------------------
# KYC completeness
# --------------------------------------------------------------------------

def field_value(record, profile, field):
    """Value of a catalogue field for one subject: first non-empty listed
    column, else the supplementary profile value. Returns (value, captured)
    where captured=False means the source table has none of the columns."""
    cols = field.get('column_names') or []
    captured = False
    if field.get('source', 'column') == 'column':
        for c in cols:
            if c in record:
                captured = True
                v = record.get(c)
                if v not in (None, '') and not (isinstance(v, str) and not v.strip()):
                    return v, True
    v = profile.get(field['field_key'])
    if v not in (None, '') and str(v).strip():
        return v, True
    return None, captured or field.get('source') == 'profile'


def applies(field, kind):
    return field.get('applies_to', 'all') in ('all', kind)


def completeness(record, kind, fields, profile=None, only=None):
    """Completeness of one KYC file.

    kind: 'individual' | 'entity'. fields: catalogue rows. only: optional list
    of field_keys to restrict to (a control checks just its fields).
    Returns dict(score 0-100, missing=[field_key], not_captured=[field_key]).
    """
    profile = profile or {}
    req = [f for f in fields if f.get('is_required', True) and applies(f, kind)
           and (only is None or f['field_key'] in only)]
    missing, not_captured = [], []
    for f in req:
        v, captured = field_value(record, profile, f)
        if v is None:
            missing.append(f['field_key'])
            if not captured:
                not_captured.append(f['field_key'])
    score = 100 if not req else round(100 * (len(req) - len(missing)) / len(req))
    return {'score': score, 'missing': missing, 'not_captured': not_captured, 'required': len(req)}


# --------------------------------------------------------------------------
# Risk model
# --------------------------------------------------------------------------

CATEGORIES = ('customer', 'geography', 'product', 'channel', 'pep', 'behaviour')


def factor_score(factor, value):
    scoring = factor.get('scoring') or {}
    key = '' if value is None else str(value)
    for k in (key, key.upper(), key.lower()):
        if k in scoring:
            return float(scoring[k])
    return float(scoring.get('*', 0))


def rate(values, factors, bands):
    """Weighted average of factor scores → (score, band, breakdown).

    values: {field_key: value}. bands: rows with band, min_score.
    """
    active = [f for f in factors if f.get('is_active', True)]
    total_w = sum(float(f.get('weight') or 0) for f in active)
    breakdown = []
    acc = 0.0
    for f in active:
        s = factor_score(f, values.get(f['field_key']))
        w = float(f.get('weight') or 0)
        acc += s * w
        breakdown.append({'factor': f['factor_key'], 'category': f['category'], 'value': values.get(f['field_key']),
                          'score': s, 'weight': w})
    score = round(acc / total_w, 2) if total_w else 0.0
    return score, band_for(score, bands), breakdown


def band_for(score, bands):
    chosen = None
    for b in sorted(bands, key=lambda b: float(b['min_score'])):
        if score >= float(b['min_score']):
            chosen = b['band']
    return chosen or 'low'


def model_gaps(factors):
    """Risk categories with no active factor (the model must be multi-factor)."""
    present = {f['category'] for f in factors if f.get('is_active', True) and float(f.get('weight') or 0) > 0}
    return [c for c in CATEGORIES if c not in present]


def next_review(rated_on, months):
    if not months:
        return None
    return rated_on + relativedelta(months=int(months))


def review_overdue(rating, today=None):
    today = today or date.today()
    nr = rating.get('next_review_date')
    return bool(nr and nr < today)


# --------------------------------------------------------------------------
# Screening QA
# --------------------------------------------------------------------------

_AR_VARIANTS = [('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ة', 'ه'), ('ى', 'ي'), ('ؤ', 'و'), ('ئ', 'ي')]


def _norm(s):
    s = unicodedata.normalize('NFKC', s or '').strip().lower()
    for a, b in _AR_VARIANTS:
        s = s.replace(a, b)
    s = re.sub(r'[ً-ْ]', '', s)       # harakat
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', s)).strip()


def same_name(a, b):
    return _norm(a) == _norm(b)


def name_variants(name):
    """Spelling variants a good matcher must still find: word order, dropped
    middle name, initials, Arabic letter forms (hamza / taa marbuta / alif
    maqsura), and a single-letter typo. Returns [(variant_type, text)]."""
    name = ' '.join((name or '').split())
    parts = name.split(' ')
    out = []
    if len(parts) >= 2:
        out.append(('reordered', ' '.join([parts[-1]] + parts[:-1])))
    if len(parts) >= 3:
        out.append(('middle_dropped', ' '.join([parts[0], parts[-1]])))
        out.append(('initial', ' '.join([parts[0], parts[1][0] + '.', *parts[2:]])))
    swapped = name
    for a, b in _AR_VARIANTS:
        if a in swapped:
            swapped = swapped.replace(a, b)
        elif b in swapped and a in ('أ', 'ة', 'ى'):
            swapped = swapped.replace(b, a, 1)
    if swapped != name:
        out.append(('arabic_letter_form', swapped))
    longest = max(parts, key=len) if parts else ''
    if len(longest) >= 5:
        i = len(longest) // 2
        typo = longest[:i] + longest[i + 1:]
        out.append(('typo', name.replace(longest, typo, 1)))
    seen, uniq = {name}, []
    for t, v in out:
        if v not in seen:
            seen.add(v)
            uniq.append((t, v))
    return uniq


_SYN_FIRST = ['Zarnov', 'Quellan', 'Mirotte', 'Vashkel', 'Odrima', 'Tessaly', 'Brunelk', 'Yavrin', 'Kolvane', 'Ilsender']
_SYN_LAST = ['Pellatrix', 'Ondravo', 'Kestrune', 'Varmolin', 'Thessick', 'Quorvane', 'Lindqvar', 'Morvessa']


def synthetic_negatives(n=10, seed=7):
    """Invented names that must NOT match any list (for precision)."""
    rnd = random.Random(seed)
    return [f'{rnd.choice(_SYN_FIRST)} {rnd.choice(_SYN_LAST)} {rnd.choice(_SYN_LAST)}' for _ in range(n)]


def qa_metrics(results):
    """results: [{expect_match, found, false_positive}] → counts and percentages.
    A positive case is a hit when the expected entry is among the matches; a
    negative case is a false positive when anything matches above threshold."""
    positives = [r for r in results if r['expect_match']]
    negatives = [r for r in results if not r['expect_match']]
    hits = sum(1 for r in positives if r['found'])
    fps = sum(1 for r in negatives if r['found'])
    recall = round(100 * hits / len(positives), 2) if positives else None
    precision = round(100 * hits / (hits + fps), 2) if (hits + fps) else None
    return {'cases': len(results), 'positives': len(positives), 'hits': hits, 'misses': len(positives) - hits,
            'false_positives': fps, 'recall_pct': recall, 'precision_pct': precision}


# --------------------------------------------------------------------------
# Training coverage, monitoring programme, audit coverage
# --------------------------------------------------------------------------

def coverage_by_group(people, completed_ids):
    """people: [{id, group}] ; completed_ids: set of person ids who completed.
    Returns {group: (completed, total, pct)}."""
    out = {}
    for p in people:
        g = p.get('group') or '-'
        c, t = out.get(g, (0, 0))
        out[g] = (c + (1 if p['id'] in completed_ids else 0), t + 1)
    return {g: (c, t, round(100 * c / t, 1) if t else 0.0) for g, (c, t) in out.items()}


def monitoring_gaps(reviews, today=None):
    """Planned reviews past their date and not performed."""
    today = today or date.today()
    return [r for r in reviews if r.get('status') == 'planned' and r.get('planned_date') and r['planned_date'] < today]


def audit_coverage(controls, covered_control_ids, min_criticality=('critical', 'high')):
    """Controls (of the given criticalities) not covered by the audit plan."""
    return [c for c in controls if c.get('criticality') in min_criticality and c['id'] not in covered_control_ids]


def study_overdue(item, today=None):
    today = today or date.today()
    return item.get('status') in ('candidate', 'under_study') and item.get('study_due_date') and \
        item['study_due_date'] < today
