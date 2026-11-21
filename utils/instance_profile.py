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
Instance profile: what one running instance of the code offers.

The same code can run as a SECONDARY instance (own folder, database, Redis db and systemd unit — see
scripts/instance/) that serves only part of the platform. The profile is chosen with the environment variable
CX_INSTANCE_PROFILE (in the instance's .env):

  full        (default) everything, exactly as before.
  governance  a lightweight instance for governance-only clients: board, committees, meetings, resolutions,
              fit & proper, policies, declarations / conflict of interest, documents, users & administration,
              audit logs and the dashboard. The screening engine, ML / semantic models, Elasticsearch,
              list updaters, eKYC, adverse media, vessel / dual-use and content packs are never imported.

Everything a profile enables is DATA in PROFILES below, expressed in the access catalogue's module and
feature keys (access/catalog.py): the blueprints registered, the sidebar links, the access matrix and the
request gate (404 for anything outside the profile) are all derived from it.

Optional per-instance upload quota: CX_UPLOAD_QUOTA_MB (any profile; unset = no quota) caps the size of the
instance's upload folder (CX_UPLOAD_DIR, default <app>/uploads).
"""

import fnmatch
import os
import sys
import time

ENV = 'CX_INSTANCE_PROFILE'
DEFAULT = 'full'
OFF_PREFIX = '/_off/'           # links built for pages this instance does not offer (404, pruned from menus)

PROFILES = {
    'full': {
        'label': ('Full platform', 'المنصة الكاملة'),
    },
    'governance': {
        'label': ('Governance', 'الحوكمة'),
        # access-catalogue modules offered (their blueprints are registered, nothing else is)
        'modules': ('governance', 'policies', 'coi', 'declarations', 'tracker', 'portal', 'admin', 'general'),
        # features of those modules that belong to screening / AML / platform operations
        'features_off': ('general.operations', 'admin.limits', 'admin.client_sites', 'admin.api',
                         'portal.cobec', 'portal.ghe', 'portal.learning', 'portal.suspicion',
                         'portal.whistleblowing'),
        # blueprints that belong to no catalogue module but serve the enabled ones
        'blueprints': ('auth', 'users', 'attachments', 'guides', 'legal', 'access', 'public_coi'),
        # never imported in this profile (an import raises ImportError, which optional callers already handle)
        'blocked_imports': ('screening', 'ekyc', 'packs', 'aml', 'amlkyc', 'merchant_kyc', 'blacklist',
                            'faiss', 'torch', 'torchvision', 'sentence_transformers', 'transformers',
                            'elasticsearch', 'sklearn', 'insightface', 'onnxruntime', 'cv2', 'deepface',
                            'mediapipe', 'paddleocr', 'easyocr'),
        'packs': False,
    },
}


def name():
    p = (os.environ.get(ENV) or DEFAULT).strip().lower()
    return p if p in PROFILES else DEFAULT


def spec():
    return PROFILES[name()]


def is_full():
    return 'modules' not in spec()


def label(lang='en'):
    en, ar = spec()['label']
    return ar if str(lang).startswith('ar') else en


def packs_enabled():
    return spec().get('packs', True)


def heavy_enabled():
    """Screening engine, ML models, search index clients and their dashboards."""
    return is_full()


# ------------------------------------------------------------------ modules, features, blueprints
def module_enabled(key):
    s = spec()
    return 'modules' not in s or key in s['modules']


def feature_enabled(feature):
    """feature: a registry Feature (or its key)."""
    s = spec()
    if 'modules' not in s:
        return True
    key = getattr(feature, 'key', feature)
    module = getattr(feature, 'module', None)
    if module is None:
        from access import registry as R
        module = R.module_of(key) or R.MODULES.get(str(key).split('.', 1)[0])
    if module is None or not module_enabled(getattr(module, 'key', module)):
        return False
    return not any(fnmatch.fnmatchcase(key, p) for p in s.get('features_off', ()))


def enabled_blueprints():
    """Names of the blueprints this instance registers (None: all)."""
    s = spec()
    if 'modules' not in s:
        return None
    from access import catalog  # noqa: F401  (registers the core modules; pure data)
    from access import registry as R
    names = set(s.get('blueprints', ()))
    for key in s['modules']:
        m = R.MODULES.get(key)
        if m is not None:
            names.update(m.blueprints or ())
    return frozenset(names)


def blueprint_enabled(bp_name):
    names = enabled_blueprints()
    return names is None or bp_name in names


def endpoint_enabled(endpoint):
    """False for a page outside this instance's profile (the request gate answers 404)."""
    if is_full() or not endpoint or endpoint == 'static':
        return True
    if '.' in endpoint and not blueprint_enabled(endpoint.split('.', 1)[0]):
        return False
    from access import registry as R
    key = R.feature_for(endpoint)
    return key is None or feature_enabled(R.FEATURES.get(key) or key)


def is_off_link(href):
    return bool(href) and str(href).startswith(OFF_PREFIX)


def install_url_fallback(app):
    """url_for() of a page this instance does not offer gives an /_off/ link (404, removed from menus)
    instead of a BuildError that would break every template naming it. Not installed for 'full'."""
    if is_full():
        return

    def _off(error, endpoint, values):
        if endpoint and (endpoint.split('.', 1)[0] not in app.blueprints or not endpoint_enabled(endpoint)):
            return OFF_PREFIX + endpoint
        raise error
    app.url_build_error_handlers.append(_off)


def _rc_loc(en, ar):
    try:
        from flask_babel import get_locale
        return (ar or en) if str(get_locale()).startswith('ar') else (en or ar)
    except Exception:
        return en or ar


def _corp_profile():
    try:
        from prudential import service
        return service.profile()
    except Exception:
        try:
            from database.db import get_db
            get_db().rollback()
        except Exception:
            pass
        return {}


# Template helpers that blueprints outside a profile normally provide (app_template_global /
# app_context_processor) and that shared templates (base, sidebar, dashboard, letterhead) call: neutral values.
TEMPLATE_FALLBACKS = {
    'ai_level': lambda *a, **k: 0,
    'ai_enabled': lambda *a, **k: False,
    'ekyc_enabled': lambda *a, **k: False,
    'vessel_can_db': lambda *a, **k: False,
    'screenings_left': lambda *a, **k: None,
    'rc_pack_menus': lambda *a, **k: [],
    'rc_pack_permission_modules': lambda *a, **k: [],
    'rc_user_module_perm': lambda *a, **k: 'none',
    'rc_loc': _rc_loc,
    'corp_profile': _corp_profile,
}


def install_template_fallbacks(app):
    """Neutral template helpers for the blueprints this profile does not register (not for 'full')."""
    if is_full():
        return
    for key, fn in TEMPLATE_FALLBACKS.items():
        app.jinja_env.globals.setdefault(key, fn)


# ------------------------------------------------------------------ import guard
class _Blocker:
    def __init__(self, roots):
        self.roots = frozenset(roots)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.', 1)[0] in self.roots:
            raise ImportError(f"'{fullname}' is not available in the '{name()}' instance profile")
        return None


def install_import_guard():
    """Refuse the heavy packages of the profile (no-op for 'full'). Idempotent."""
    roots = spec().get('blocked_imports')
    if not roots or any(isinstance(f, _Blocker) for f in sys.meta_path):
        return False
    sys.meta_path.insert(0, _Blocker(roots))
    return True


# ------------------------------------------------------------------ upload quota
QUOTA_ENV = 'CX_UPLOAD_QUOTA_MB'
_usage = {'at': 0.0, 'bytes': 0, 'dir': None}
_USAGE_TTL = 60


def quota_bytes():
    try:
        mb = float(os.environ.get(QUOTA_ENV) or 0)
    except ValueError:
        return 0
    return int(mb * 1024 * 1024) if mb > 0 else 0


def upload_dir(app=None):
    d = os.environ.get('CX_UPLOAD_DIR')
    if d:
        return d
    root = app.root_path if app is not None else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, 'uploads')


def dir_bytes(path):
    total = 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(base, f)).st_size
            except OSError:
                pass
    return total


def used_bytes(path, fresh=False):
    now = time.monotonic()
    if fresh or _usage['dir'] != path or now - _usage['at'] > _USAGE_TTL:
        _usage.update(at=now, bytes=dir_bytes(path), dir=path)
    return _usage['bytes']


def quota_message(lang, quota):
    mb = int(quota / (1024 * 1024))
    if str(lang).startswith('ar'):
        return (f'تم رفض رفع الملف: امتلأت مساحة التخزين المخصصة لهذه النسخة ({mb} ميجابايت). '
                'احذف ملفات غير لازمة أو تواصل مع مسؤول المنصة لزيادة المساحة.')
    return (f'Upload refused: this instance has used its storage quota ({mb} MB). '
            'Remove files you no longer need or ask the platform administrator for more space.')


def install_upload_quota(app):
    """Refuse multipart uploads once the instance's upload folder (plus the incoming body) exceeds
    CX_UPLOAD_QUOTA_MB. Read at request time, so a changed quota needs only a restart."""
    from flask import flash, jsonify, redirect, request

    @app.before_request
    def _cx_upload_quota():
        if request.method not in ('POST', 'PUT', 'PATCH'):
            return None
        if not (request.content_type or '').startswith('multipart/form-data'):
            return None
        quota = quota_bytes()
        if not quota:
            return None
        incoming = request.content_length or 0
        if used_bytes(upload_dir(app)) + incoming <= quota:
            return None
        try:
            from flask_babel import get_locale
            lang = str(get_locale() or 'ar')
        except Exception:
            lang = 'ar'
        msg = quota_message(lang, quota)
        app.logger.warning('upload refused: quota %s bytes reached (%s)', quota, request.path)
        if request.path.startswith('/api/') or request.is_json or \
                request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
                request.accept_mimetypes.best == 'application/json':
            resp = jsonify({'error': 'quota_exceeded', 'message': msg,
                            'message_en': quota_message('en', quota), 'message_ar': quota_message('ar', quota)})
            resp.status_code = 413
            return resp
        flash(msg, 'danger')
        ref = request.referrer or ''
        resp = redirect(ref if ref.startswith(request.host_url) else '/')   # back to the form, same site only
        resp.headers['X-CX-Quota'] = 'exceeded'
        return resp
