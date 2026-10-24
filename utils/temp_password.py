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

"""One-time passwords issued by an administrator.

Each new account gets its own random password that satisfies the password
policy (User.validate_password_strength). It is shown once to the
administrator, never stored in clear, and the user must replace it at the
first login (users.must_change_password).
"""

import csv
import io
import secrets
import string

_UP, _LO, _DG, _SP = string.ascii_uppercase, string.ascii_lowercase, string.digits, '!@#$%^&*'
_SAFE_UP = ''.join(c for c in _UP if c not in 'IO')
_SAFE_LO = ''.join(c for c in _LO if c not in 'l')
_SAFE_DG = ''.join(c for c in _DG if c not in '01')


def generate(length=16):
    length = max(12, int(length))
    chars = [secrets.choice(_SAFE_UP), secrets.choice(_SAFE_LO), secrets.choice(_SAFE_DG), secrets.choice(_SP)]
    pool = _SAFE_UP + _SAFE_LO + _SAFE_DG + _SP
    chars += [secrets.choice(pool) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    if chars[0] not in _SAFE_UP + _SAFE_LO:      # never start with a symbol (spreadsheet formula prefixes)
        i = next(i for i, c in enumerate(chars) if c in _SAFE_UP + _SAFE_LO)
        chars[0], chars[i] = chars[i], chars[0]
    return ''.join(chars)


def _cell(v):
    v = '' if v is None else str(v)
    return "'" + v if v[:1] in ('=', '+', '-', '@') else v


def credentials_csv(rows):
    """rows: dicts with email, first_name, last_name, password ('' when the
    administrator set it). Returns CSV text (UTF-8 BOM for Excel)."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Email', 'First name', 'Last name', 'Temporary password', 'Must change at first login'])
    for r in rows:
        w.writerow([_cell(r.get('email')), _cell(r.get('first_name')), _cell(r.get('last_name')),
                    r.get('password') or '(set by administrator)', 'yes'])
    return '﻿' + out.getvalue()
