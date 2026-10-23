"""Fit & proper form definitions (JSON data, one file per form).

A definition lists sections and items (text, textarea, date, choice, yesno,
grid, docstatus, signature, confirm) with English and Arabic wording. Regulator
forms reproduce the regulator's questions word for word ("locked": they are not
edited in the system) and may map every item to the content controls of the
regulator's original Word file ("docx" indices), so the system can hand back
the original form filled in. Add a regulator's new or updated form by adding a
file here - no code change.
"""
import json
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE = {}


def _load():
    if not _CACHE:
        for name in sorted(os.listdir(_DIR)):
            if name.endswith('.json'):
                with open(os.path.join(_DIR, name), encoding='utf-8') as f:
                    d = json.load(f)
                _CACHE[d['code']] = d
    return _CACHE


def all_forms():
    """Default form first (the general board questionnaire), then by code.
    Sector-specific regulator forms carry a "sector" and say so in their title."""
    return sorted(_load().values(), key=lambda d: (not d.get('default'), d['code']))


def default_form():
    return next((d for d in _load().values() if d.get('default')), None)


def get_form(code):
    return _load().get(code)


def docx_path(defn):
    name = (defn or {}).get('docx_template')
    if not name:
        return None
    p = os.path.join(_DIR, name)
    return p if os.path.isfile(p) else None
