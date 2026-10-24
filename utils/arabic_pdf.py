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

"""Arabic text for fpdf2 without HarfBuzz.

fpdf2's own text shaping needs `uharfbuzz`, which is not installed; the core
fonts (helvetica…) are latin-1 only, so Arabic names/course titles crashed PDF
generation with UnicodeEncodeError. `shape()` turns Arabic into its contextual
presentation forms (incl. lam-alef) and reorders it for display with
python-bidi, and `add_unicode_font()` registers a TTF that has those glyphs.
"""

import os
import re

from bidi import get_display

# letter -> first presentation form; 4 forms (iso, fin, ini, med) when dual-joining, else 2 (iso, fin)
_FORMS = {
    'ء': (0xFE80, 1), 'آ': (0xFE81, 2), 'أ': (0xFE83, 2), 'ؤ': (0xFE85, 2),
    'إ': (0xFE87, 2), 'ئ': (0xFE89, 4), 'ا': (0xFE8D, 2), 'ب': (0xFE8F, 4),
    'ة': (0xFE93, 2), 'ت': (0xFE95, 4), 'ث': (0xFE99, 4), 'ج': (0xFE9D, 4),
    'ح': (0xFEA1, 4), 'خ': (0xFEA5, 4), 'د': (0xFEA9, 2), 'ذ': (0xFEAB, 2),
    'ر': (0xFEAD, 2), 'ز': (0xFEAF, 2), 'س': (0xFEB1, 4), 'ش': (0xFEB5, 4),
    'ص': (0xFEB9, 4), 'ض': (0xFEBD, 4), 'ط': (0xFEC1, 4), 'ظ': (0xFEC5, 4),
    'ع': (0xFEC9, 4), 'غ': (0xFECD, 4), 'ف': (0xFED1, 4), 'ق': (0xFED5, 4),
    'ك': (0xFED9, 4), 'ل': (0xFEDD, 4), 'م': (0xFEE1, 4), 'ن': (0xFEE5, 4),
    'ه': (0xFEE9, 4), 'و': (0xFEED, 2), 'ى': (0xFEEF, 2), 'ي': (0xFEF1, 4),
}
_LAM_ALEF = {'آ': 0xFEF5, 'أ': 0xFEF7, 'إ': 0xFEF9, 'ا': 0xFEFB}
_TATWEEL = 'ـ'
_HARAKAT = re.compile('[ً-ْٰ]')
_ARABIC = re.compile('[؀-ۿ]')

FONT_DIRS = ('/usr/share/fonts/truetype/dejavu', '/usr/share/fonts/dejavu')


def has_arabic(text):
    return bool(text) and bool(_ARABIC.search(text))


def _joins_left(ch):
    """Can the NEXT letter connect to this one?"""
    return ch == _TATWEEL or (ch in _FORMS and _FORMS[ch][1] == 4)


def _shape_logical(text):
    text = _HARAKAT.sub('', text)
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch not in _FORMS:
            out.append(ch)
            i += 1
            continue
        prev = text[i - 1] if i > 0 else ''
        joined_prev = _joins_left(prev)
        if ch == 'ل' and i + 1 < n and text[i + 1] in _LAM_ALEF:
            out.append(chr(_LAM_ALEF[text[i + 1]] + (1 if joined_prev else 0)))
            i += 2
            continue
        base, count = _FORMS[ch]
        nxt = text[i + 1] if i + 1 < n else ''
        joins_next = count == 4 and (nxt in _FORMS or nxt == _TATWEEL)
        if count == 1:
            form = 0
        elif joined_prev and joins_next:
            form = 3
        elif joins_next:
            form = 2
        elif joined_prev:
            form = 1
        else:
            form = 0
        out.append(chr(base + form))
        i += 1
    return ''.join(out)


def shape(text):
    """Text ready to draw left-to-right with fpdf2 (unchanged when not Arabic)."""
    if text is None:
        return ''
    text = str(text)
    if not has_arabic(text):
        return text
    return get_display(_shape_logical(text))


def add_unicode_font(pdf, family='CxUni'):
    """Register DejaVu Sans (regular/bold; italic maps to regular). Returns the
    family name, or None when the font is not installed (caller falls back)."""
    for d in FONT_DIRS:
        reg, bold = os.path.join(d, 'DejaVuSans.ttf'), os.path.join(d, 'DejaVuSans-Bold.ttf')
        if os.path.isfile(reg):
            pdf.add_font(family, '', reg)
            pdf.add_font(family, 'B', bold if os.path.isfile(bold) else reg)
            pdf.add_font(family, 'I', reg)
            pdf.add_font(family, 'BI', bold if os.path.isfile(bold) else reg)
            return family
    return None


def latin1_safe(text):
    """Last-resort fallback for core fonts: never raise on non latin-1 text."""
    return str(text or '').encode('latin-1', 'replace').decode('latin-1')
