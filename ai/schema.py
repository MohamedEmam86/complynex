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
Minimal JSON-schema validator (the subset the AI tasks use: type, required,
properties, additionalProperties, enum, items, minItems, maxItems,
minLength, maxLength, minimum, maximum). Avoids a new dependency.
"""

import json
import re

_TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool, 'null': type(None)}


def _is(v, t):
    if t == 'integer':
        return isinstance(v, int) and not isinstance(v, bool)
    if t == 'number':
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def errors(value, schema, path='$'):
    out = []
    t = schema.get('type')
    if t:
        types = t if isinstance(t, list) else [t]
        if not any(_is(value, x) for x in types):
            return [f'{path}: expected {"/".join(types)}']
    if 'enum' in schema and value not in schema['enum']:
        out.append(f'{path}: {value!r} not one of {schema["enum"]}')
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0):
            out.append(f'{path}: too short')
        if 'maxLength' in schema and len(value) > schema['maxLength']:
            out.append(f'{path}: too long')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 'minimum' in schema and value < schema['minimum']:
            out.append(f'{path}: below minimum')
        if 'maximum' in schema and value > schema['maximum']:
            out.append(f'{path}: above maximum')
    if isinstance(value, dict):
        for k in schema.get('required', []):
            if k not in value:
                out.append(f'{path}.{k}: required')
        props = schema.get('properties', {})
        for k, v in value.items():
            if k in props:
                out += errors(v, props[k], f'{path}.{k}')
            elif schema.get('additionalProperties') is False:
                out.append(f'{path}.{k}: not allowed')
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            out.append(f'{path}: too few items')
        if 'maxItems' in schema and len(value) > schema['maxItems']:
            out.append(f'{path}: too many items')
        if 'items' in schema:
            for i, v in enumerate(value):
                out += errors(v, schema['items'], f'{path}[{i}]')
    return out


def extract_json(text):
    """First JSON object in a model reply (handles ```json fences and chatter around it)."""
    if text is None:
        raise ValueError('empty reply')
    if isinstance(text, (dict, list)):
        return text
    s = text.strip()
    m = re.search(r'```(?:json)?\s*(.*?)```', s, re.S)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    start = s.find('{')
    while start != -1:
        depth = 0
        for i in range(start, len(s)):
            if s[i] == '{':
                depth += 1
            elif s[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start:i + 1])
                    except ValueError:
                        break
        start = s.find('{', start + 1)
    raise ValueError('no JSON object in the reply')
