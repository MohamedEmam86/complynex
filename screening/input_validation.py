"""Server-side checks for the manual screening form (screening.manual_screen).

Kept free of Flask/DB imports so it can be unit-tested; the route passes
flask_babel.gettext as ``_`` so the messages are translated."""
from datetime import date, datetime

ENTITY_TYPES = ('INDIVIDUAL', 'ENTITY')
THRESHOLD_MIN, THRESHOLD_MAX, THRESHOLD_DEFAULT = 40, 90, 55
EGYPT_NAMES = {'', 'EG', 'EGY', 'EGYPT', 'EGYPTIAN', 'مصر', 'مصري', 'مصرى'}
_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def _identity(msg, **kw):
    return msg % kw if kw else msg


def validate_screen_inputs(entity_type, threshold, dob, national_id, country, _=_identity, today=None):
    """Returns (errors, cleaned) where cleaned holds entity_type, threshold (int),
    dob (date or None) and national_id (digits or None)."""
    errors = []
    today = today or date.today()

    entity_type = (entity_type or 'INDIVIDUAL').strip().upper()
    if entity_type not in ENTITY_TYPES:
        errors.append(_('Entity type must be Individual or Company / Entity.'))

    threshold_val = THRESHOLD_DEFAULT
    if threshold not in (None, ''):
        try:
            threshold_val = int(str(threshold).strip())
        except ValueError:
            threshold_val = None
        if threshold_val is None or not THRESHOLD_MIN <= threshold_val <= THRESHOLD_MAX:
            errors.append(_('Match threshold must be a whole number between %(min)d and %(max)d.',
                            min=THRESHOLD_MIN, max=THRESHOLD_MAX))

    dob_val = None
    if dob:
        try:
            dob_val = datetime.strptime(dob.strip().translate(_ARABIC_DIGITS), '%Y-%m-%d').date()
        except ValueError:
            errors.append(_('Date of birth must be a valid date (YYYY-MM-DD).'))
        else:
            if dob_val > today:
                errors.append(_('Date of birth cannot be in the future.'))

    nid = (national_id or '').translate(_ARABIC_DIGITS).replace(' ', '') or None
    if nid:
        if not nid.isdigit():
            errors.append(_('National ID must contain digits only.'))
        elif (country or '').strip().upper() in EGYPT_NAMES and len(nid) != 14:
            errors.append(_('An Egyptian national ID must be exactly 14 digits.'))

    return errors, {'entity_type': entity_type, 'threshold': threshold_val,
                    'dob': dob_val, 'national_id': nid}
