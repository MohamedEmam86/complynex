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
Per-user access control: one registry of modules x features (access/registry.py, access/catalog.py and each
pack's manifest), per-user grants (access/service.py), one gate for every request plus the menus
(access/gate.py), the administrator's matrix and the restricted workspace (access/routes.py).

``init_app(app)`` must run after every blueprint is registered (end of create_app).
"""


def _pack_modules(app):
    """Modules contributed by content packs: their manifest's access_modules, or one module per
    permission over the pack's guarded blueprints. Generic: no pack is named here."""
    import importlib
    from . import registry as R
    try:
        from regcontrols import packs as P
        P.discover()
        packs = list(P.PACKS.values())
    except Exception:
        return
    for pack in packs:
        if pack.access_modules:
            for spec in pack.access_modules:
                spec = dict(spec)
                spec.setdefault('area', 'packs')
                spec['pack'] = pack.code
                R.register_module(spec)
            continue
        if not pack.permissions:
            continue
        bps = []
        for bspec in pack.blueprints:
            mod_name, attr = bspec.split(':')
            try:
                bp = getattr(importlib.import_module(mod_name), attr)
            except Exception:
                continue
            guarded = any(getattr(app.view_functions.get(ep), '_cx_access', None)
                          for ep in app.view_functions if ep.startswith(bp.name + '.'))
            if guarded:
                bps.append(bp.name)
        for module, label_en, label_ar, levels in pack.permissions:
            feats = R.pair(f'{module}', label_en, label_ar, [f'{b}.*' for b in bps])
            if 'admin' in levels:
                feats.insert(0, R.Feature(f'{module}.admin', f'{label_en} — Administration',
                                          f'{label_ar} — الإدارة', [f'{b}.*' for b in bps], when=('admin',),
                                          requires=(f'{module}.view',), kind='admin'))
            landing = next((ep for ep, *_ in pack.menu), None)
            R.register_module(R.Module(module, label_en, label_ar, 'packs', pack.menu_icon or 'bi-box-seam',
                                       blueprints=tuple(bps), default=module, landing=landing, features=feats,
                                       pack=pack.code))


def init_app(app):
    from . import catalog  # noqa: F401  (registers the core modules)
    from . import registry, gate
    from .routes import bp
    if 'access' not in app.blueprints:
        app.register_blueprint(bp)
    _pack_modules(app)
    registry.build(app)
    gate.install(app)
