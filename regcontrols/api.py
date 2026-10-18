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
Public Python API of regcontrols — the only module other packages should
import from. Documented in docs/regulatory/REGCONTROLS_API.md.

    from regcontrols.api import get_param, register_check, record_evidence, raise_finding

All functions need a Flask app context (they use database.db.get_db()).
"""

from .engine import CheckContext, record_manual_test, register_check, register_sweep, run_control  # noqa: F401
from .packs import Pack, register_pack  # noqa: F401
from . import catalog  # noqa: F401 — install_* helpers for packs
from .logic import CheckResult, ParameterError, ParameterNotFound, ParameterNotSet  # noqa: F401
from . import alerts as _alerts
from . import evidence as _evidence
from . import findings as _findings
from . import params as _params


def get_param(key, licence_type='all', as_of=None, **kwargs):
    """Typed value of a regulatory parameter (licence-specific beats 'all';
    the version in force on `as_of`, default today). Pass default=... to
    avoid ParameterNotFound / ParameterNotSet."""
    return _params.get_param(key, licence_type, as_of, **kwargs)


def get_param_record(key, licence_type='all', as_of=None):
    """The full version row (value_text, unit, legal_reference, needs_review …) or None."""
    return _params.get_param_record(key, licence_type, as_of)


def record_evidence(control, title, **kwargs):
    """Add an evidence item to a control (code, id or row). Returns its id.
    See evidence.record_evidence for keyword arguments."""
    return _evidence.record_evidence(control, title, **kwargs)


def raise_finding(title, **kwargs):
    """Create (or, with dedupe, reuse) a finding linked to controls. Returns its id.
    See findings.raise_finding for keyword arguments."""
    return _findings.raise_finding(title, **kwargs)


def raise_alert(alert_type, title, message=None, **kwargs):
    """Open or refresh a live alert and notify its owner. Returns its id."""
    return _alerts.raise_alert(alert_type, title, message, **kwargs)


# ---- AML hooks for packs (the AML core modules stay unaware of any pack) ----

def register_unusual_candidate(**kwargs):
    """Put a detected event on the AML unusual-transactions register (and its
    case). Returns (id, created). See aml.unusual.register_candidate."""
    from aml.unusual import register_candidate
    return register_candidate(**kwargs)


def register_expected_source(name, fn):
    """Declare a detector whose events must all be on the unusual-transactions
    register: fn(db) -> [(source_table, source_record_id, label)]. The core
    check core.aml.unusual_register reconciles them."""
    from amlkyc.service import register_expected_source as _reg
    return _reg(name, fn)
