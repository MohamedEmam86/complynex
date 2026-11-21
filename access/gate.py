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
The request gate and the menus.

* ``before_request``: every signed-in request is checked against the user's effective access with
  service.endpoint_allowed() — the same function the sidebar, the portal, the workspace and the landing
  pages use, so a module that is hidden is also refused by URL (403 page / JSON 403).
* ``cx_nav`` Jinja filter: prunes the rendered sidebar (CMS and portal share it) to the links the user may
  open, then drops groups left empty. When nothing is pruned the markup is returned unchanged.
* Template globals: cx_can(feature), cx_ok(endpoint), cx_mode(), cx_restricted(), cx_modules().
Requests authenticated by an API key carry no session (api/ authenticates them itself), so the gate never sees a
signed-in user for them; a header alone never skips the gate.
"""

import logging
import re

from flask import current_app, g, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from markupsafe import Markup

from utils import instance_profile as _profile

from . import service as S

logger = logging.getLogger(__name__)


def enabled():
    return current_app.config.get('ACCESS_CONTROL', True)


def _signed_in():
    try:
        return bool(current_user and current_user.is_authenticated)
    except Exception:
        return False


def current_access():
    if not _signed_in():
        return None
    return S.effective(current_user)


_REFUSALS = {}           # (user id, feature) -> last time written; per worker, keeps the audit log small
_REFUSAL_EVERY = 600


def _audit_refusal(endpoint):
    """Refusals of sensitive features (list data, exports) go to the audit log: endpoint and path only,
    at most once per user and feature every 10 minutes."""
    from . import registry as R
    import time
    key = R.feature_for(endpoint)
    f = R.FEATURES.get(key or '')
    if not f or not f.sensitive:
        return
    uid = getattr(current_user, 'id', None)
    now = time.monotonic()
    if now - _REFUSALS.get((uid, key), -1e9) < _REFUSAL_EVERY:
        return
    _REFUSALS[(uid, key)] = now
    if len(_REFUSALS) > 5000:
        _REFUSALS.clear()
    try:
        from models.audit import AuditLog
        AuditLog.log(uid, 'Access Refused', 'Access', None, f'{key}: {request.method} {request.path[:200]}',
                     request.remote_addr)
    except Exception:
        logger.warning('access: refusal audit failed', exc_info=True)


def _deny(access):
    wants_json = (request.path.startswith('/api/') or request.is_json
                  or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                  or request.accept_mimetypes.best == 'application/json')
    logger.info('access refused: user=%s endpoint=%s', getattr(current_user, 'id', None), request.endpoint)
    _audit_refusal(request.endpoint)
    if wants_json:
        resp = jsonify({'error': 'forbidden', 'message': 'This feature is not enabled for your account.'})
    else:
        resp = current_app.make_response(render_template('access/denied.html', home=S.home_endpoint(access)))
    resp.status_code = 403
    resp.headers['X-CX-Gate'] = 'denied'
    return resp


def check_request():
    ep = request.endpoint
    if ep and not _profile.endpoint_enabled(ep):
        # outside this instance's profile: the page does not exist here (for everybody, superadmin too)
        from flask import abort
        abort(404)
    if not enabled():
        return None
    if not ep or ep == 'static':
        return None
    if not _signed_in():
        return None
    access = S.effective(current_user)
    if access.unrestricted:
        return None
    if ep in S.HOMES:
        home = S.home_endpoint(access)
        if home == 'access.workspace' or (ep == 'portal.dashboard' and not access.has('portal.home')):
            resp = redirect(url_for('access.workspace'))
            resp.headers['X-CX-Gate'] = 'workspace'
            return resp
    if S.endpoint_allowed(access, ep):
        return None
    return _deny(access)


# ------------------------------------------------------------------ menus
_adapter_cache = {}


def endpoint_of(href):
    """'blueprint.function' a link points to (None for external / unknown links)."""
    if not href or href.startswith(('#', 'http://', 'https://', 'mailto:', 'javascript:')):
        return None
    path = href.split('#', 1)[0].split('?', 1)[0]
    try:
        adapter = current_app.url_map.bind('localhost')
        return adapter.match(path, method='GET')[0]
    except Exception:
        try:
            return current_app.url_map.bind('localhost').match(path, method='POST')[0]
        except Exception:
            return None


def link_ok(href, access=None):
    access = access or current_access()
    if access is None or access.unrestricted:
        return True
    ep = endpoint_of(href)
    return ep is None or S.endpoint_allowed(access, ep)


def prune_nav(html):
    """Remove the sidebar links this user may not open (and those outside the instance profile, for
    everybody) and the groups left empty."""
    text = str(html)
    hrefs = set(re.findall(r'href="([^"]+)"', text))
    off = set() if _profile.is_full() else {h for h in hrefs if _off_link(h.replace('&amp;', '&'))}
    access = current_access() if enabled() else None
    if (not enabled() or access is None or access.unrestricted) and not off:
        return html
    denied = set(off)
    if enabled() and access is not None and not access.unrestricted:
        denied |= {h for h in hrefs if not link_ok(h.replace('&amp;', '&'), access)}
    if not denied:
        return html
    from lxml import html as LH
    root = LH.fragment_fromstring(text, create_parent='div')
    for a in root.iter('a'):
        if a.get('href') not in {d.replace('&amp;', '&') for d in denied} and a.get('href') not in denied:
            continue
        li = a.getparent()
        while li is not None and li.tag != 'li':
            li = li.getparent()
        if li is not None and li.getparent() is not None:
            li.getparent().remove(li)
        else:
            a.set('href', url_for(S.home_endpoint(access)) if access is not None else url_for('dashboard'))
    changed = True
    while changed:
        changed = False
        for ul in list(root.iter('ul')):
            if 'cnx-nav__sub' in (ul.get('class') or '') and not any(c.tag == 'li' for c in ul):
                li = ul.getparent()
                while li is not None and li.tag != 'li':
                    li = li.getparent()
                if li is not None and li.getparent() is not None:
                    li.getparent().remove(li)
                    changed = True
    for li in root.iter('li'):
        if 'cnx-nav__item--module' in (li.get('class') or ''):
            cnt = li.find('.//span[@class="cnx-nav__count"]')
            sub = li.find('.//ul')
            if cnt is not None and sub is not None:
                cnt.text = str(sum(1 for c in sub if c.tag == 'li'))
    out = ''.join(LH.tostring(c, encoding='unicode') for c in root)
    return Markup((root.text or '') + out)


def _off_link(href):
    """A link to a page outside this instance's profile (an /_off/ link or a page the profile refuses)."""
    if _profile.is_off_link(href):
        return True
    ep = endpoint_of(href)
    return bool(ep) and not _profile.endpoint_enabled(ep)


# ------------------------------------------------------------------ template globals
def cx_can(key):
    access = current_access()
    return bool(access and access.has(key))


def cx_ok(endpoint):
    access = current_access()
    return bool(access) and S.endpoint_allowed(access, endpoint)


def cx_mode():
    access = current_access()
    return access.mode if access else None


def cx_restricted():
    if not enabled():
        return False
    access = current_access()
    return bool(access and not access.unrestricted and access.mode == 'restricted')


def cx_modules(surface=None):
    """Granted modules with an openable landing page: [{'module', 'url', 'features'}]."""
    access = current_access()
    if not access:
        return []
    from flask_babel import get_locale
    lang = str(get_locale() or 'en')[:2]
    out = []
    for m in access.modules():
        if surface and m.surface != surface:
            continue
        if not m.landing or not S.endpoint_allowed(access, m.landing):
            # first granted page without URL arguments
            landing = None
            for f in m.features:
                if not access.has(f.key):
                    continue
                for ep in f.endpoints:
                    if _no_args(ep) and _gettable(ep):
                        landing = ep
                        break
                if landing:
                    break
        else:
            landing = m.landing
        if not landing:
            continue
        try:
            url = url_for(landing)
        except Exception:
            continue
        out.append({'module': m, 'key': m.key, 'label': m.label(lang), 'desc': m.desc(lang), 'icon': m.icon,
                    'url': url, 'features': [f.label(lang) for f in m.features if access.has(f.key)]})
    return out


def _no_args(ep):
    return any(not r.arguments for r in current_app.url_map.iter_rules(ep))


def _gettable(ep):
    return any('GET' in r.methods for r in current_app.url_map.iter_rules(ep))


def _level_label(code):
    """{{ level_label('edit') }} -> 'View & Edit' / 'عرض وتعديل' (registry.LEVEL_LABELS)."""
    from flask_babel import get_locale
    from .registry import level_label
    return level_label(code, str(get_locale() or 'en'))


def install(app):
    if getattr(app, '_cx_access_installed', False):
        return
    app._cx_access_installed = True
    app.before_request(check_request)
    app.jinja_env.filters['cx_nav'] = prune_nav
    app.jinja_env.globals.update(cx_can=cx_can, cx_ok=cx_ok, cx_mode=cx_mode, cx_restricted=cx_restricted,
                                 cx_modules=cx_modules, level_label=_level_label)
