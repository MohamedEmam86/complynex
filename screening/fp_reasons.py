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
P4-6 — standard reasons for clearing a hit as a false positive.

A clearance records WHY the customer is not the listed person, as codes an
examiner can count and compare, plus the free-text rationale. Some reasons are
never enough on their own:

  * gender differs — gender is information only (P3-10), never a basis to
    clear a hit by itself;
  * common name, no other identifiers — a frequent name is the reason the hit
    exists, not evidence that it is wrong.

At least one substantive reason (an identifier, the date of birth, the
nationality backed by an ID, documents, the record being lifted ...) is
required. Labels are translated in the templates (_fp_reasons.html).
"""
import json

REASONS = (
    ('dob_differs', 'Date of birth differs from the listed person'),
    ('id_differs', 'National ID / passport differs from the listed one'),
    ('nationality_differs_with_id', 'Different nationality, proven by an identity document'),
    ('age_incompatible', 'Age is incompatible with the listing (e.g. a minor at listing date)'),
    ('entity_type_differs', 'Different entity type (person vs. company)'),
    ('different_name_elements', 'Name elements differ on review (different father / family name)'),
    ('documents_verified', 'Identity documents verified and inconsistent with the listing'),
    ('record_lifted', 'The listing was lifted / delisted for this record'),
    ('registry_differs', 'Company registry number / place of registration differs'),
    ('gender_differs', 'Gender differs (information only — not sufficient alone)'),
    ('common_name', 'Common name, no other identifiers (not sufficient alone)'),
    ('other', 'Other (explained in the rationale)'),
)
CODES = tuple(c for c, _ in REASONS)
LABELS = dict(REASONS)
NOT_SUFFICIENT_ALONE = ('gender_differs', 'common_name')


def parse(values):
    """Form values (list or comma string) -> ordered, de-duplicated list of known codes."""
    if values is None:
        return []
    if isinstance(values, str):
        values = values.split(',')
    out = []
    for v in values:
        v = str(v or '').strip()
        if v in CODES and v not in out:
            out.append(v)
    return out


def validate(codes, notes=''):
    """None when the reasons can support a clearance, else the (untranslated) problem."""
    codes = parse(codes)
    if not codes:
        return 'Select at least one false-positive reason.'
    if all(c in NOT_SUFFICIENT_ALONE for c in codes):
        return ('Gender or a common name alone is not a reason to clear a hit: '
                'add a substantive reason (identifier, date of birth, documents ...).')
    if 'other' in codes and len((notes or '').strip()) < 20:
        return "'Other' needs the explanation in the rationale (at least 20 characters)."
    return None


def as_json(codes):
    return json.dumps(parse(codes))


def as_text(codes):
    """English summary prefixed to the stored notes, so every existing screen shows it."""
    c = parse(codes)
    return ('[FP reasons: ' + '; '.join(LABELS[x] for x in c) + ']') if c else ''
