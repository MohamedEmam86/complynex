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
"""The organisation's primary regulator, for wording in pages and messages.

Texts must not hard-code one regulator ("CBE"): an FRA-supervised company
would read the wrong authority. The name comes from Administration >
Settings > General ("Regulator", setting `regulator_name`), with its Arabic
name taken from the regulators catalogue (installed by the regulator packs)
when the codes match. Without a setting the wording is neutral
("the regulator")."""
import re

from flask import g
from flask_babel import get_locale, gettext


def _split(name):
    """'Financial Regulatory Authority (FRA)' -> ('Financial Regulatory Authority', 'FRA')."""
    m = re.match(r'^\s*(.*?)\s*\(([^()]{2,12})\)\s*$', name or '')
    return (m.group(1), m.group(2)) if m else ((name or '').strip(), '')


def regulator_info():
    """{'name': full name, 'short': abbreviation or name, 'configured': bool} in the current language."""
    lang = str(get_locale() or 'en')
    cache = getattr(g, '_regulator_info', None)
    if cache and cache.get('_lang') == lang:
        return cache
    info = {'name': gettext('the regulator'), 'short': gettext('the regulator'), 'configured': False, '_lang': lang}
    try:
        from models.settings import Settings
        raw = (Settings.get('regulator_name', '') or '').strip()
        code = (Settings.get('regulator_code', '') or '').strip()
        if raw:
            name, abbr = _split(raw)
            code = code or abbr
            name_ar = None
            try:
                from database.db import query_db
                row = query_db("SELECT name_ar, regulator_code FROM regulators WHERE "
                               "(%s <> '' AND UPPER(regulator_code) = UPPER(%s)) OR LOWER(regulator_name) = LOWER(%s) "
                               "ORDER BY is_active DESC NULLS LAST LIMIT 1", (code, code, name), one=True)
                if row:
                    name_ar = row.get('name_ar')
                    code = code or (row.get('regulator_code') or '')
            except Exception:
                from database.db import get_db
                get_db().rollback()
            if lang == 'ar' and name_ar:
                info.update(name=name_ar, short=name_ar, configured=True)
            else:
                info.update(name=name, short=code or name, configured=True)
    except Exception:
        pass
    g._regulator_info = info
    return info


def regulator_name():
    return regulator_info()['name']


def regulator_short():
    return regulator_info()['short']


def register(app):
    @app.context_processor
    def _inject_regulator():
        # lazy: computed only when a template actually prints it
        class _Lazy:
            def __init__(self, key):
                self.key = key

            def __str__(self):
                return regulator_info()[self.key]

            def __html__(self):
                from markupsafe import escape
                return str(escape(str(self)))

            def __bool__(self):
                return regulator_info()['configured']
        return {'regulator_name': _Lazy('name'), 'regulator_short': _Lazy('short')}
