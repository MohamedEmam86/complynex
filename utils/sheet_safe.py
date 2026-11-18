# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Spreadsheet-safe cell values for CSV / Excel exports.

A text cell starting with = + - @ (or a tab / carriage return) is run as a formula by Excel / LibreOffice
(formula injection: customer files and list data are untrusted). Such text gets a leading apostrophe, which
makes the spreadsheet show it as text. Numbers stay numbers. Same rule as screening/user_reports.py had.
"""
_FORMULA_START = ('=', '+', '-', '@', '\t', '\r')


def cell(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return v
    s = str(v)
    return "'" + s if s[:1] in _FORMULA_START else s


def row(values):
    return [cell(v) for v in values]
