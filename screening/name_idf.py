#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rarity weighting for name elements.

The engine has been treating a shared name element as evidence without asking
how common it is. In the Egyptian population that is the wrong instinct:

    محمد     37.1% of names   weight 0.99
    احمد     20.9%            weight 1.56
    علي       9.8%            weight 2.32
    الرحمن    2.5%            weight 3.68
    مبارك     0.13%           weight 6.63
    الجندي    0.09%           weight 7.06

Two strangers sharing محمد have told you nothing. Two sharing الجندي have told
you a great deal. The old defence was a list of 110 tokens, in or out, hand
maintained, and built only from Arabic — which is why 'Amr Mohamed' still scored
100 against a merchant sharing nothing else.

WHAT THIS MEASURES
`shared_evidence(a, b)` returns the total weight of the elements two names have
in common — how much identifying information the match actually rests on,
measured in the same units for every pair.

Elements absent from the table are treated as rare, not as unknown: a name that
appears once in 161,000 is exactly the kind that identifies someone.

WHAT IT DELIBERATELY DOES NOT DO
It does not fire on names that are effectively identical. احمد على احمد على is
built entirely from common elements and carries only 3.9 of evidence, but
against its own record it is a certain match. Rarity answers "is this shared
element meaningful", not "are these the same name" — the containment and
equality tests answer that, and they take precedence.
"""
import io
import json
import os
import threading

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'data', 'name_idf.json')

_lock = threading.Lock()
_table = None
_default = 8.0          # unseen element: treat as rare
_total = 0


def _load():
    global _table, _default, _total
    if _table is not None:
        return _table
    with _lock:
        if _table is not None:
            return _table
        try:
            with io.open(_PATH, encoding='utf-8') as f:
                blob = json.load(f)
            _table = blob.get('idf') or {}
            _default = float(blob.get('default_idf') or 8.0)
            _total = int(blob.get('total_names') or 0)
        except Exception:
            # Never let a missing table break screening: with an empty table
            # every element reads as rare, which is the permissive direction.
            _table = {}
    return _table


def weight(token):
    """Rarity weight of one name element. Higher means more identifying."""
    if not token:
        return 0.0
    return float(_load().get(str(token).lower(), _default))


def is_common(token, threshold=2.5):
    """Does this element appear in more than roughly 8% of Egyptian names?

    Replaces the hand-maintained token list. Being continuous underneath, the
    threshold can be moved without rewriting anything.
    """
    return weight(token) < threshold


def name_evidence(tokens):
    """Total identifying weight carried by a set of elements."""
    return sum(weight(t) for t in set(tokens))


def shared_evidence(tokens_a, tokens_b):
    """Weight of what two names actually share.

    This is the number that matters: two four-element names can overlap on three
    elements and still share almost nothing, if those three are محمد, احمد and
    السيد.
    """
    return name_evidence(set(tokens_a) & set(tokens_b))


def evidence_ratio(tokens_a, tokens_b):
    """Shared weight as a fraction of the better-covered side.

    Measured against the SMALLER side so that a short form inside a full
    patronymic chain still reads as well covered — that is a real pattern in
    sanctions data, not a weakness.
    """
    sa, sb = name_evidence(tokens_a), name_evidence(tokens_b)
    lo = min(sa, sb)
    if lo <= 0:
        return 0.0
    return shared_evidence(tokens_a, tokens_b) / lo
