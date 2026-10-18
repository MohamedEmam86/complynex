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

from flask_babel import get_locale, format_date, format_datetime, format_number
from datetime import datetime

def localized_date(date_obj):
    """Format date according to current locale"""
    if not date_obj:
        return ''
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.fromisoformat(date_obj)
        except ValueError:
            return date_obj
    return format_date(date_obj, format='medium', locale=get_locale())

def localized_datetime(datetime_obj):
    """Format datetime according to current locale"""
    if not datetime_obj:
        return ''
    if isinstance(datetime_obj, str):
        try:
            datetime_obj = datetime.fromisoformat(datetime_obj)
        except ValueError:
            return datetime_obj
    return format_datetime(datetime_obj, format='medium', locale=get_locale())

def localized_number(number):
    """Format number according to current locale"""
    if number is None:
        return ''
    return format_number(number, locale=get_locale())
