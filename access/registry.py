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
Access-control registry: every module and feature a user can be granted, as DATA.

    Module (screening, vessels, aml, governance, portal …)
      └─ Feature (screening.name.screen, vessels.database, portal.coi …)
            └─ endpoints (blueprint.function patterns)

The core catalogue lives in access/catalog.py; optional content packs declare their own modules in their
manifest (``Pack(access_modules=[...])``) — the core never names a pack. ``build(app)`` runs once all
blueprints are registered and resolves every endpoint of ``app.url_map`` to at most one feature.

Old rule of a feature ("legacy"): what the code checked before per-user features existed. It is derived
from the guard each view declares (``permission_required`` and the module guards record it with ``mark``),
OR-ed over the feature's endpoints, unless the feature states it. It is used (a) to backfill today's access
as explicit grants and (b) for users nobody has edited yet — so nobody's effective access changes until an
administrator changes it.
"""

import fnmatch
from dataclasses import dataclass, field

# Rank of the stored perm_* levels (ai uses 'use', pdpl 'approve' is checked as view).
RANK = {'none': 0, 'view': 1, 'use': 2, 'edit': 2, 'admin': 3}
ADMIN_ROLES = ('admin', 'superadmin', 'it_admin')
MODES = ('cms', 'portal', 'restricted')

# The one vocabulary for permission levels, wherever a level is shown (matrix, permissions matrix, exports, access
# review). Data, not gettext: 'Admin' in the message catalogue is the ROLE ("system administrator").
LEVEL_LABELS = {
    'none': ('No access', 'لا وصول'),
    'view': ('View', 'عرض'),
    'edit': ('View & Edit', 'عرض وتعديل'),
    'admin': ('Admin', 'إدارة الوحدة'),
}
LEVEL_ALIASES = {'use': 'edit', 'approve': 'admin', 'action': 'edit', '': 'none', None: 'none'}


def level_label(code, lang='en'):
    code = LEVEL_ALIASES.get(code, code)
    en, ar = LEVEL_LABELS.get(code, LEVEL_LABELS['none'])
    return ar if str(lang).startswith('ar') else en


# ------------------------------------------------------------------ old-rule specs
# 'auth' | ('perm', module, level) | ('role', (roles,)) | ('cms',) | ('col', column, (values,))
# | ('any', [spec, ...]) | ('all', [spec, ...]) | ('never',)

def mark(*specs):
    """Decorator helper for route guards: record the old rule a view checks (outermost guard first).
    Usage inside a guard: ``wrapped = mark(('perm', 'aml', 'edit'))(wrapped)``. Pure metadata."""
    def deco(f):
        f._cx_access = list(specs) + list(getattr(f, '_cx_access', []) or [])
        return f
    return deco


def legacy_can_access_cms(user):
    """The CMS rule before access modes existed (models/user.py can_access_cms)."""
    return getattr(user, 'role', '') in ('admin', 'compliance_officer', 'compliance_manager') or \
        (getattr(user, 'cms_access_level', None) or 'none') in ('view', 'edit')


def legacy_mode(user):
    # the platform superadmin is unrestricted and works in the CMS
    if (getattr(user, 'role', '') or '') == 'superadmin':
        return 'cms'
    return 'cms' if legacy_can_access_cms(user) else 'portal'


def allows(user, spec):
    """Evaluate an old-rule spec for a user (never consults the new grants)."""
    if spec is None or spec == 'auth':
        return True
    if (getattr(user, 'role', '') or '') == 'superadmin':
        return True     # the platform superadmin is unrestricted (and an admin wherever a page asks for one)
    kind = spec[0]
    if kind == 'perm':
        _k, module, level = spec
        if level in ('edit', 'use'):
            return bool(user.can_edit(module))
        if level == 'admin':
            return bool(user.can_admin_module(module))
        return bool(user.can_view(module))
    if kind == 'role':
        return (getattr(user, 'role', '') or '') in spec[1]
    if kind == 'cms':
        return legacy_can_access_cms(user)
    if kind == 'col':
        return (getattr(user, spec[1], None) or 'none') in spec[2]
    if kind == 'any':
        return any(allows(user, s) for s in spec[1])
    if kind == 'all':
        return all(allows(user, s) for s in spec[1])
    if kind == 'never':
        return False
    raise ValueError(f'unknown access spec {spec!r}')


def perm_leaves(spec):
    """[(module, level)] the perm_* columns a spec relies on (for write-through)."""
    if spec is None or spec == 'auth':
        return []
    if spec[0] == 'perm':
        return [(spec[1], spec[2])]
    if spec[0] == 'col' and spec[1].startswith('perm_'):
        return [(spec[1][5:], 'view')]
    if spec[0] in ('any', 'all'):
        out = []
        for s in spec[1]:
            out += perm_leaves(s)
        return out
    return []


def _or(specs):
    specs = [s for s in specs]
    if not specs or any(s is None or s == 'auth' for s in specs):
        return 'auth'
    uniq = []
    for s in specs:
        if s not in uniq:
            uniq.append(s)
    return uniq[0] if len(uniq) == 1 else ('any', uniq)


# ------------------------------------------------------------------ catalogue
@dataclass
class Feature:
    key: str
    label_en: str
    label_ar: str
    patterns: list = field(default_factory=list)   # endpoint fnmatch patterns
    when: object = None         # None | 'view' | 'manage' | 'admin' | tuple — only endpoints of that kind match
    legacy: object = None       # old rule override (else derived from the endpoints' guards)
    perms: list = None          # write-through override [(perm module, level)]
    requires: tuple = ()        # features ticked automatically with this one (UI)
    kind: str = 'view'          # view | action | admin (badge in the matrix)
    platform: bool = False      # platform-superadmin pages (shared reference data): never granted, not in the matrix
    workspace: bool = True      # False: never part of a restricted workspace (e.g. seeing colleagues' records)
    grant_by: tuple = ()        # roles that may grant / remove it (empty: any access editor), e.g. ('superadmin',)
    sensitive: bool = False     # refusals by the gate are written to the audit log
    hint_en: str = ''
    hint_ar: str = ''
    # filled by build()
    module: object = None
    endpoints: list = field(default_factory=list)
    derived: object = None
    write_perms: dict = field(default_factory=dict)

    def label(self, lang):
        return self.label_ar if lang == 'ar' and self.label_ar else self.label_en

    def hint(self, lang):
        return self.hint_ar if lang == 'ar' and self.hint_ar else self.hint_en

    @property
    def old_rule(self):
        return self.legacy if self.legacy is not None else (self.derived or 'auth')


@dataclass
class Module:
    key: str
    label_en: str
    label_ar: str
    area: str
    icon: str = 'bi-grid'
    surface: str = 'cms'        # cms | portal | shell (CMS chrome: notifications, search, support…) — portal and
                                # shell features are never available in a restricted workspace

    @property
    def workspace_ok(self):
        return self.surface == 'cms'
    blueprints: tuple = ()      # endpoints of these blueprints not matched by a feature use `default`
    default: str = None         # 'feature.key' or a pair prefix: '<prefix>.view' / '<prefix>.manage'
    landing: str = None         # endpoint opened from the restricted workspace tile
    desc_en: str = ''
    desc_ar: str = ''
    features: list = field(default_factory=list)
    order: int = 100
    pack: str = None

    def label(self, lang):
        return self.label_ar if lang == 'ar' and self.label_ar else self.label_en

    def desc(self, lang):
        return self.desc_ar if lang == 'ar' and self.desc_ar else self.desc_en


AREAS = {}          # key -> (label_en, label_ar, order)
MODULES = {}        # key -> Module (registration order kept)
FEATURES = {}       # key -> Feature
ENDPOINT_FEATURE = {}   # endpoint -> feature key
ENDPOINT_SPEC = {}      # endpoint -> old rule of that endpoint (from its guards)
ENDPOINT_RULES = {}     # endpoint -> old rule stated in a catalogue (views whose check is inside the body)
PUBLIC = []             # endpoint patterns that are public pages (no sign-in): never part of a module
_built = {'done': False}


def area(key, label_en, label_ar, order=100):
    AREAS[key] = (label_en, label_ar, order)


def pair(prefix, label_en, label_ar, patterns, view=LEVEL_LABELS['view'], manage=LEVEL_LABELS['edit'],
         hint_en='', hint_ar=''):
    """Two features over the same pages: '<prefix>.view' for read pages, '<prefix>.manage' for
    the pages and actions that change data (picked from each view's own guard)."""
    return [Feature(f'{prefix}.view', f'{label_en} — {view[0]}', f'{label_ar} — {view[1]}', patterns, when='view',
                    hint_en=hint_en, hint_ar=hint_ar),
            Feature(f'{prefix}.manage', f'{label_en} — {manage[0]}', f'{label_ar} — {manage[1]}', patterns,
                    when=('manage', 'admin'), requires=(f'{prefix}.view',), kind='action')]


def register_module(module):
    """Add (or replace) a module. Packs call this through their manifest; the core catalogue at import."""
    if isinstance(module, dict):
        feats = [f if isinstance(f, Feature) else Feature(**f) for f in module.pop('features', [])]
        module = Module(features=feats, **module)
    for f in module.features:
        f.module = module
    MODULES[module.key] = module
    _built['done'] = False
    return module


def all_features():
    """Features this instance offers (its instance profile, utils/instance_profile.py; all for 'full')."""
    from utils import instance_profile as P
    return [f for m in modules() for f in m.features if P.feature_enabled(f)]


def modules():
    """Modules this instance offers (its instance profile; all for 'full'), in menu order."""
    from utils import instance_profile as P
    return [m for m in _all_modules() if P.module_enabled(m.key)]


def _all_modules():
    return sorted(MODULES.values(), key=lambda m: (AREAS.get(m.area, ('', '', 999))[2], m.order))


def _all_features():
    return [f for m in _all_modules() for f in m.features]


def module_of(feature_key):
    f = FEATURES.get(feature_key)
    return f.module if f else None


# ------------------------------------------------------------------ resolution
def _kind(endpoint, methods, specs):
    """'admin' when the view's guard asks for module administration (level admin or an administrator
    role), 'manage' for edit/use or when it only accepts POST; 'view' otherwise."""
    top = 'view'
    for s in specs:
        if s != 'auth' and s[0] == 'role':
            return 'admin'
        for mod, lvl in perm_leaves(s):
            if RANK.get(lvl, 1) >= 3:
                return 'admin'
            if RANK.get(lvl, 1) >= 2:
                top = 'manage'
    if top == 'manage':
        return top
    if methods and methods <= {'POST', 'PUT', 'PATCH', 'DELETE'}:
        return 'manage'
    return 'view'


def _endpoint_specs(app, endpoint):
    f = app.view_functions.get(endpoint)
    return list(getattr(f, '_cx_access', []) or [])


def build(app):
    """Resolve every endpoint to a feature and derive old rules and write-through perms."""
    FEATURES.clear()
    ENDPOINT_FEATURE.clear()
    ENDPOINT_SPEC.clear()
    # every module, also those outside the instance profile: their endpoints keep their feature, so the
    # request gate can refuse them (utils/instance_profile.endpoint_enabled)
    for m in _all_modules():
        for f in m.features:
            f.module = m
            f.endpoints = []
            if f.key in FEATURES:
                raise ValueError(f'duplicate access feature {f.key}')
            FEATURES[f.key] = f
    methods = {}
    for rule in app.url_map.iter_rules():
        methods.setdefault(rule.endpoint, set()).update(rule.methods - {'HEAD', 'OPTIONS'})
    bp_module = {}
    for m in _all_modules():
        for bp in m.blueprints:
            bp_module.setdefault(bp, m)
    for ep in sorted(methods):
        specs = _endpoint_specs(app, ep)
        if not specs and ep in ENDPOINT_RULES:
            specs = [ENDPOINT_RULES[ep]]
        ENDPOINT_SPEC[ep] = ('all', specs) if len(specs) > 1 else (specs[0] if specs else 'auth')
        kind = _kind(ep, methods[ep], specs)
        hit = None
        if not any(fnmatch.fnmatchcase(ep, p) for p in PUBLIC):
            # exact names first (a page named by one feature wins over another module's wildcard), then patterns
            for exact in (True, False):
                for f in _all_features():
                    if f.when and kind not in ((f.when,) if isinstance(f.when, str) else f.when):
                        continue
                    if any((p == ep) if exact else ('*' in p and fnmatch.fnmatchcase(ep, p)) for p in f.patterns):
                        hit = f
                        break
                if hit:
                    break
        if hit is None and not any(fnmatch.fnmatchcase(ep, p) for p in PUBLIC):
            m = bp_module.get(ep.split('.', 1)[0]) if '.' in ep else None
            if m and m.default:
                key = m.default if m.default in FEATURES else f'{m.default}.{kind}'
                hit = FEATURES.get(key) or (FEATURES.get(f'{m.default}.manage') if kind == 'admin' else None)
        if hit is not None:
            ENDPOINT_FEATURE[ep] = hit.key
            hit.endpoints.append(ep)
    # a feature that covers no page and grants no level does nothing: leave it out of the catalogue
    for m in MODULES.values():
        empty = [f for f in m.features if not f.endpoints and f.perms is None and f.legacy is None]
        for f in empty:
            FEATURES.pop(f.key, None)
        m.features = [f for f in m.features if f not in empty]
    for f in FEATURES.values():
        f.derived = _or([ENDPOINT_SPEC[e] for e in f.endpoints]) if f.endpoints else 'auth'
        wp = {}
        leaves = f.perms if f.perms is not None else \
            [lf for e in f.endpoints for lf in perm_leaves(ENDPOINT_SPEC[e])]
        if f.perms is None and f.legacy is not None:
            leaves = perm_leaves(f.legacy) or leaves
        for mod, lvl in leaves:
            lvl = 'view' if lvl not in RANK else lvl
            if RANK[lvl] > RANK.get(wp.get(mod, 'none'), 0):
                wp[mod] = lvl
        f.write_perms = wp
    _built['done'] = True
    return FEATURES


def feature_for(endpoint):
    return ENDPOINT_FEATURE.get(endpoint)


def is_built():
    return _built['done']
