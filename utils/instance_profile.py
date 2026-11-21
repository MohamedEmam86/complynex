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


class UnknownProfile(RuntimeError):
    pass


def name():
    """The instance's profile. An unknown value is a configuration error: the instance refuses to start
    instead of silently running the full platform."""
    p = (os.environ.get(ENV) or DEFAULT).strip().lower()
    if p not in PROFILES:
        raise UnknownProfile(f"{ENV}={p!r} is not a known instance profile (known: {', '.join(sorted(PROFILES))})")
    return p


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


def install_url_for_guard(app):
    """url_for() of a REGISTERED page the profile refuses (e.g. a feature turned off in an enabled module) gives
    an /_off/ link too, so no rendered link leads to a 404. Not installed for 'full'."""
    if is_full():
        return
    original = app.url_for

    def url_for(endpoint, *args, **kwargs):
        full_ep = endpoint
        if endpoint and endpoint.startswith('.'):
            try:
                from flask import request
                full_ep = (request.blueprint or '') + endpoint if request.blueprint else endpoint[1:]
            except RuntimeError:
                full_ep = None
        if full_ep and not endpoint_enabled(full_ep):
            return OFF_PREFIX + full_ep
        return original(endpoint, *args, **kwargs)
    app.url_for = url_for                           # flask.url_for() in views
    app.jinja_env.globals['url_for'] = url_for      # templates (the environment keeps its own reference)


# ------------------------------------------------------------------ page clean-up (links to pages not offered)
# Templates mark what may disappear:
#   data-cx-widget              a block (card, tile, row, button) removed when it holds a link to an /_off/ page
#   data-cx-endpoint="bp.view"  a block that belongs to that page's module, removed when the profile refuses it
# Any other /_off/ link: a menu entry (li in a nav / dropdown) is removed, a plain link keeps its text only,
# a form posting to it is removed.
_OFF_ATTRS = ('href', 'action', 'formaction', 'data-href', 'data-url')


def scrub_html(text):
    """The page without links to pages this instance does not offer (see the marks above)."""
    if OFF_PREFIX not in text and 'data-cx-endpoint' not in text:
        return text
    from lxml import html as LH
    head = text.lstrip()[:200].lower()
    document = head.startswith('<!doctype') or head.startswith('<html')
    doctype = head.startswith('<!doctype')
    # a whole page is rewritten; a fragment (partial, widget) is edited in place, never wrapped
    root = LH.document_fromstring(text) if document else LH.fragment_fromstring(text, create_parent='div')

    def attached(el):
        return any(a is root for a in el.iterancestors()) or el is root

    for el in root.xpath('//*[@data-cx-endpoint]'):
        if attached(el) and not endpoint_enabled(el.get('data-cx-endpoint')):
            el.drop_tree()
    cond = ' or '.join(f'starts-with(@{a}, "{OFF_PREFIX}")' for a in _OFF_ATTRS)
    for el in root.xpath(f'//*[{cond}]'):
        if not attached(el):
            continue
        widget = next((a for a in [el, *el.iterancestors()] if a.get('data-cx-widget') is not None), None)
        if widget is not None:
            widget.drop_tree()
            continue
        if el.tag == 'a':
            li = next((a for a in el.iterancestors() if a.tag == 'li'), None)
            menu = li is not None and li.getparent() is not None and any(
                c in (li.getparent().get('class') or '') for c in ('nav', 'dropdown-menu', 'list-group', 'breadcrumb'))
            if menu:
                li.drop_tree()
            else:
                el.drop_tag()           # keep the words, drop the dead link
        elif el.tag == 'form' or el.get('formaction', '').startswith(OFF_PREFIX):
            el.drop_tree()
        else:
            for a in _OFF_ATTRS:
                if (el.get(a) or '').startswith(OFF_PREFIX):
                    del el.attrib[a]
    if not document:
        return (root.text or '') + ''.join(LH.tostring(c, encoding='unicode', method='html') for c in root)
    out = LH.tostring(root, encoding='unicode', method='html')
    return ('<!DOCTYPE html>\n' + out) if doctype else out


def install_link_scrub(app):
    """Apply scrub_html to every HTML page (not for 'full')."""
    if is_full():
        return

    @app.after_request
    def _cx_scrub_off_links(response):
        if response.direct_passthrough or response.is_streamed or response.mimetype != 'text/html':
            return response
        data = response.get_data(as_text=True)
        if OFF_PREFIX in data or 'data-cx-endpoint' in data:
            response.set_data(scrub_html(data))
        return response


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


# Request bodies that are not file uploads (forms, JSON, text) are never counted.
NON_UPLOAD_TYPES = ('application/x-www-form-urlencoded', 'application/json', 'text/plain')
FRESH_FROM = 0.9                # within 10% of the quota the folder is counted again for every upload


def is_upload(req):
    """A request that may store a file: POST/PUT/PATCH with a body that is not a form, JSON or text
    (multipart, octet-stream, image/..., application/pdf, an unknown type, or a chunked body)."""
    if req.method not in ('POST', 'PUT', 'PATCH'):
        return False
    mt = (req.mimetype or '').lower()
    chunked = 'chunked' in (req.headers.get('Transfer-Encoding') or '').lower()
    if not mt and not chunked and not req.content_length:
        return False
    return mt not in NON_UPLOAD_TYPES


def length_message(lang):
    if str(lang).startswith('ar'):
        return 'تم رفض رفع الملف: الطلب لا يحدد حجمه (Content-Length)، وهو مطلوب لأن لهذه النسخة حداً للتخزين.'
    return 'Upload refused: the request does not state its size (Content-Length), which this instance requires.'


def install_upload_quota(app):
    """Refuse uploads once the instance's upload folder plus the incoming body would exceed
    CX_UPLOAD_QUOTA_MB (any upload type, see is_upload); uploads without Content-Length are refused while a
    quota is set. The folder size is cached for a minute, and counted afresh near the quota. Read at request
    time, so a changed quota needs only a restart."""
    from flask import flash, jsonify, redirect, request

    def _lang():
        try:
            from flask_babel import get_locale
            return str(get_locale() or 'ar')
        except Exception:
            return 'ar'

    def _refuse(status, msg, msg_en, msg_ar, error):
        app.logger.warning('upload refused (%s): %s', error, request.path)
        if request.path.startswith('/api/') or request.is_json or \
                request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
                request.accept_mimetypes.best == 'application/json':
            resp = jsonify({'error': error, 'message': msg, 'message_en': msg_en, 'message_ar': msg_ar})
            resp.status_code = status
            return resp
        flash(msg, 'danger')
        ref = request.referrer or ''
        resp = redirect(ref if ref.startswith(request.host_url) else '/')   # back to the form, same site only
        resp.headers['X-CX-Quota'] = 'exceeded' if status == 413 else 'length-required'
        return resp

    @app.before_request
    def _cx_upload_quota():
        quota = quota_bytes()
        if not quota or not is_upload(request):
            return None
        if request.content_length is None:
            return _refuse(411, length_message(_lang()), length_message('en'), length_message('ar'),
                           'length_required')
        incoming = request.content_length
        folder = upload_dir(app)
        used = used_bytes(folder)
        if used + incoming > quota * FRESH_FROM:
            used = used_bytes(folder, fresh=True)      # near the limit: never trust the cached size
        if used + incoming <= quota:
            return None
        return _refuse(413, quota_message(_lang(), quota), quota_message('en', quota), quota_message('ar', quota),
                       'quota_exceeded')
