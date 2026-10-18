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
Content packs: optional bundles of regulator- or sector-specific content and
logic on top of the generic core — e.g. a regulator's framework and
requirements, its control library and parameters, and sector modules (such as
a lending-conduct module) with their checks.

A pack lives in packs/<code>/ and registers itself in its __init__.py:

    from regcontrols.packs import Pack, register_pack
    register_pack(Pack(code='my_pack', name_en=..., install=install, check_modules=[...],
                       blueprints=['packs.my_pack.routes:bp'], menu=[...], permissions=[...]))

The core never imports a specific pack: discover() imports whatever packages
exist under packs/, and only ENABLED packs (rc_packs.enabled) contribute
checks, sweeps, menus and pages. Disabling a pack deactivates its controls
and hides its pages; its data stays, so enabling it again restores
everything. Packs are enabled per installation on Compliance Controls >
Content packs.
"""

import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from datetime import datetime

from database.db import get_db

logger = logging.getLogger(__name__)


@dataclass
class Pack:
    code: str
    name_en: str
    name_ar: str = ''
    description_en: str = ''
    description_ar: str = ''
    version: str = '1'
    install: object = None              # callable(db) -> summary dict; must be idempotent
    check_modules: list = field(default_factory=list)
    blueprints: list = field(default_factory=list)   # 'module.path:attr'
    menu: list = field(default_factory=list)         # [(endpoint, label_en, label_ar, permission_module)]
    menu_title_en: str = ''
    menu_title_ar: str = ''
    menu_icon: str = 'bi-box-seam'
    permissions: list = field(default_factory=list)  # [(module, label_en, label_ar, levels)]


PACKS = {}
_discovered = False


def register_pack(pack):
    PACKS[pack.code] = pack
    return pack


def discover():
    """Import every package under packs/ so it can register itself."""
    global _discovered
    if _discovered:
        return PACKS
    try:
        import packs as packs_pkg
    except ImportError:
        _discovered = True
        return PACKS
    for mod in pkgutil.iter_modules(packs_pkg.__path__):
        if mod.ispkg:
            try:
                importlib.import_module(f'packs.{mod.name}')
            except Exception:
                logger.exception('regcontrols: could not load pack %s', mod.name)
    _discovered = True
    return PACKS


# ------------------------------------------------------------------ state
def _state(db=None):
    db = db or get_db()
    try:
        return {r['code']: dict(r) for r in db.execute("SELECT * FROM rc_packs").fetchall()}
    except Exception:
        db.rollback()
        return {}


def is_enabled(code, db=None):
    try:
        from flask import g, has_app_context
        if has_app_context():
            cache = getattr(g, '_rc_pack_state', None)
            if cache is None:
                cache = g._rc_pack_state = _state(db)
            return bool(cache.get(code, {}).get('enabled'))
    except Exception:
        pass
    return bool(_state(db).get(code, {}).get('enabled'))


def enabled_packs(db=None):
    discover()
    return [p for code, p in PACKS.items() if is_enabled(code, db)]


def listing(db=None):
    discover()
    state = _state(db)
    return [{'pack': p, 'state': state.get(code, {})} for code, p in sorted(PACKS.items())]


def enable(code, user_id=None, db=None):
    """Install (idempotently) and enable a pack. Returns the install summary."""
    discover()
    pack = PACKS.get(code)
    if not pack:
        raise ValueError('unknown pack')
    db = db or get_db()
    summary = pack.install(db) if pack.install else {}
    # Switch back on exactly the controls the last disable switched off.
    db.execute("""UPDATE rc_controls SET is_active = TRUE WHERE id = ANY(
                      COALESCE((SELECT deactivated_controls FROM rc_packs WHERE code = %s), '{}'))""", (code,))
    db.execute("""INSERT INTO rc_packs (code, enabled, installed_version, installed_at, updated_by, updated_at)
                  VALUES (%s, TRUE, %s, %s, %s, %s)
                  ON CONFLICT (code) DO UPDATE SET enabled = TRUE, installed_version = EXCLUDED.installed_version,
                      deactivated_controls = '{}',
                      installed_at = EXCLUDED.installed_at, updated_by = EXCLUDED.updated_by,
                      updated_at = EXCLUDED.updated_at""",
               (code, pack.version, datetime.now(), user_id, datetime.now()))
    db.commit()
    _reset_cache()
    from . import engine
    engine.load_checks(force=True)
    return summary


def disable(code, user_id=None, db=None):
    db = db or get_db()
    now = datetime.now()
    ids = [r['id'] for r in db.execute(
        "UPDATE rc_controls SET is_active = FALSE, updated_at = %s WHERE pack_code = %s AND is_active RETURNING id",
        (now, code)).fetchall()]
    db.execute("""INSERT INTO rc_packs (code, enabled, deactivated_controls, updated_by, updated_at)
                  VALUES (%s, FALSE, %s, %s, %s)
                  ON CONFLICT (code) DO UPDATE SET enabled = FALSE, deactivated_controls = EXCLUDED.deactivated_controls,
                      updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at""", (code, ids, user_id, now))
    db.commit()
    _reset_cache()


def _reset_cache():
    try:
        from flask import g
        g.pop('_rc_pack_state', None)
    except Exception:
        pass


# ------------------------------------------------------------------ app wiring
def register_blueprints(app):
    """Register every discovered pack's blueprints. Pages of a disabled pack
    answer 404, so url_for() always resolves but nothing is reachable."""
    from flask import abort
    discover()
    for pack in PACKS.values():
        for spec in pack.blueprints:
            mod_name, attr = spec.split(':')
            try:
                bp = getattr(importlib.import_module(mod_name), attr)
            except Exception:
                logger.exception('regcontrols: could not load blueprint %s of pack %s', spec, pack.code)
                continue

            if not getattr(bp, '_rc_pack_guarded', False):   # create_app() may run more than once per process
                def _guard(code=pack.code):
                    if not is_enabled(code):
                        abort(404)
                bp.before_request(_guard)
                bp._rc_pack_guarded = True
            if getattr(bp, 'csrf_exempt', False):     # API-key authenticated blueprints
                from extensions import csrf
                csrf.exempt(bp)
            app.register_blueprint(bp)


def menus(user):
    """Sidebar groups contributed by enabled packs, filtered by permission."""
    out = []
    for p in enabled_packs():
        items = [(ep, en, ar) for ep, en, ar, perm in p.menu if not perm or user.can_view(perm)]
        if items:
            out.append({'title_en': p.menu_title_en or p.name_en, 'title_ar': p.menu_title_ar or p.name_ar,
                        'icon': p.menu_icon, 'links': items, 'code': p.code})
    return out


def permission_modules():
    """[(module, label_en, label_ar, levels)] declared by all discovered packs —
    shown on the user form even before a pack is enabled, so access can be
    prepared in advance."""
    discover()
    out = []
    for p in PACKS.values():
        out += list(p.permissions)
    return out


# ------------------------------------------------------------------ module permissions
def get_module_perms(user_id, db=None):
    db = db or get_db()
    try:
        return {r['module']: r['level'] for r in db.execute(
            "SELECT module, level FROM user_module_permissions WHERE user_id = %s", (user_id,)).fetchall()}
    except Exception:
        db.rollback()
        return {}


def save_module_perms(user_id, form, db=None):
    """Persist modperm_<module> fields of the user form."""
    db = db or get_db()
    for module, *_ in permission_modules():
        level = form.get(f'modperm_{module}')
        if level is None:
            continue
        if level not in ('none', 'view', 'edit', 'admin'):
            level = 'none'
        db.execute("""INSERT INTO user_module_permissions (user_id, module, level, updated_at) VALUES (%s,%s,%s,%s)
                      ON CONFLICT (user_id, module) DO UPDATE SET level = EXCLUDED.level, updated_at = EXCLUDED.updated_at""",
                   (user_id, module, level, datetime.now()))
    db.commit()
