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
Client sites: a client gets its own sub-domain (e.g. <client>.complynex.online) served by the SAME application.
Everything client-specific is DATA (table client_sites), managed by the platform superadmin
(/admin/client-sites). No client is named in code.

* Host resolution: a before_request hook (installed first) resolves request.host (ProxyFix x_host) to an active
  client site and stores it on g.client_site. The main hosts behave exactly as before. Any other host gets 404
  (host-header validation). Main hosts: MAIN_HOSTS (config / .env, comma separated; default
  complynex.online, www.complynex.online, localhost, 127.0.0.1), plus the hosts of APP_URL and DEMO_BASE_URL and
  the Academy host, which this application also serves. HOST_VALIDATION=0 switches the 404 off (break-glass).
* Sign-in: a user bound to a site (users.site_id) signs in on that site's host only, a site host accepts its own
  users only (others get the normal "invalid e-mail or password"), and the user's access mode must be one the
  site allows. The platform superadmin signs in anywhere. The same rule is checked on every request (load_user).
* Sessions: on a client host the session cookie is named cx_session_<site id>, so sessions never cross hosts
  (cookies stay host-only, secure, httponly, samesite as configured).
* Limits: a site user without an own daily limit gets the site's default daily limit; the site's monthly
  organisation cap counts vessel + dual-use screenings of all its users in the calendar month (Africa/Cairo),
  from screening_daily_usage (screening/limits.py).
"""
import logging
import os
import re
import time
from urllib.parse import urlparse

from flask import Response, current_app, g, has_request_context, request
from flask.sessions import SecureCookieSessionInterface

logger = logging.getLogger(__name__)

MODES = ('cms', 'portal', 'restricted')
CAP_KINDS = ('vessel', 'dualuse')
DEFAULT_MAIN_HOSTS = ('complynex.online', 'www.complynex.online', 'localhost', '127.0.0.1')
LOGO_MAX_BYTES = 512 * 1024
LOGO_DIR = 'client_sites'
_ENV_KEY = 'cx.client_site'
_TTL = 30.0
_CACHE = {'at': -1e9, 'sites': None}
_UNSET = object()
HOST_RE = re.compile(r'^(?=.{4,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class Site(dict):
    """One row of client_sites (attribute access for templates)."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def name(self, lang='en'):
        return ((self.get('name_ar') if str(lang).startswith('ar') else None) or self.get('name_en') or '').strip()

    def welcome(self, lang='en'):
        return ((self.get('welcome_ar') if str(lang).startswith('ar') else None) or self.get('welcome_en') or '').strip()

    @property
    def cookie_name(self):
        return f"cx_session_{int(self['id'])}"

    @property
    def modes(self):
        return [m for m in (self.get('allowed_access_modes') or []) if m in MODES]


# ------------------------------------------------------------------ hosts
def normalise_host(host):
    h = (host or '').strip().lower()
    if h.startswith('['):                       # [::1]:8000
        return h.split(']', 1)[0] + ']'
    return h.split(':', 1)[0].rstrip('.')


def main_hosts(app=None):
    app = app or current_app
    cached = app.extensions.get('cx_main_hosts')
    if cached is not None:
        return cached
    raw = str(app.config.get('MAIN_HOSTS') or os.environ.get('MAIN_HOSTS') or '')
    hosts = {normalise_host(x) for x in raw.split(',') if x.strip()} or set(DEFAULT_MAIN_HOSTS)
    for key in ('APP_URL', 'DEMO_BASE_URL'):
        v = app.config.get(key) or os.environ.get(key)
        if v:
            hosts.add(normalise_host(urlparse(v).netloc or v))
    try:
        from academy.service import ACADEMY_HOST
        hosts.add(normalise_host(ACADEMY_HOST))
    except Exception:
        pass
    hosts.add('[::1]')
    hosts.discard('')
    out = frozenset(hosts)
    app.extensions['cx_main_hosts'] = out
    return out


def host_validation_enabled(app=None):
    app = app or current_app
    v = app.config.get('HOST_VALIDATION', os.environ.get('HOST_VALIDATION', '1'))
    return str(v).strip().lower() not in ('0', 'false', 'no', 'off')


def invalidate():
    _CACHE['sites'] = None
    _CACHE['at'] = -1e9


def _db(db=None):
    if db is not None:
        return db
    from database.db import get_db
    return get_db()


def _rollback(db):
    try:
        db.rollback()
    except Exception:
        pass


def active_sites():
    """{host: Site} of the active client sites (cached per worker for a few seconds)."""
    now = time.monotonic()
    if _CACHE['sites'] is not None and now - _CACHE['at'] < _TTL:
        return _CACHE['sites']
    sites = {}
    db = None
    try:
        db = _db()
        rows = db.execute('SELECT * FROM client_sites WHERE active').fetchall()
        sites = {r['host']: Site(r) for r in rows}
    except Exception:
        # table missing (migration not applied yet) or the database is down: no client sites
        if db is not None:
            _rollback(db)
        sites = {}
    _CACHE.update(at=now, sites=sites)
    return sites


def site_for_request():
    """The active client site of this request's host, or None (main hosts, no request)."""
    if not has_request_context():
        return None
    env = request.environ
    if _ENV_KEY in env:
        return env[_ENV_KEY]
    host = normalise_host(request.host)
    site = None
    if host not in main_hosts():
        site = active_sites().get(host)
    env[_ENV_KEY] = site
    return site


def resolve_request():
    """before_request (first of all): g.client_site, and 404 for a host that is neither a main host nor an
    active client site."""
    site = site_for_request()
    g.client_site = site
    if site is None and host_validation_enabled() and normalise_host(request.host) not in main_hosts():
        logger.info('host refused: %s %s', normalise_host(request.host)[:100], request.path[:100])
        return Response('Not found', status=404, mimetype='text/plain')
    return None


class SiteSessionInterface(SecureCookieSessionInterface):
    """A distinct session cookie per client host (cx_session_<site id>); the main hosts keep the usual one."""

    def get_cookie_name(self, app):
        site = site_for_request()
        return site.cookie_name if site else super().get_cookie_name(app)


# ------------------------------------------------------------------ sign-in
def _is_superadmin(user):
    return (getattr(user, 'role', '') or '') == 'superadmin'


def user_site_id(user, db=None):
    if user is None:
        return None
    sid = getattr(user, 'site_id', None)
    if sid is None and not getattr(user, '_site_loaded', False) and getattr(user, 'id', None):
        db = _db(db)
        try:
            r = db.execute('SELECT site_id FROM users WHERE id = %s', (user.id,)).fetchone()
            sid = r['site_id'] if r else None
        except Exception:
            _rollback(db)
            sid = None
        try:
            user.site_id, user._site_loaded = sid, True
        except Exception:
            pass
    return sid


def user_allowed_here(user, site=_UNSET):
    """A site's users on its own host only; the main hosts take users bound to no site. Superadmin: anywhere."""
    if user is None:
        return False
    if not has_request_context() and site is _UNSET:
        return True
    if _is_superadmin(user):
        return True
    site = site_for_request() if site is _UNSET else site
    sid = user_site_id(user)
    if site is None:
        return sid is None
    return sid is not None and int(sid) == int(site['id'])


def _mode_of(user):
    try:
        from access import service as S
        return S.effective(user).mode
    except Exception:
        return getattr(user, 'access_mode', None)


def login_user_for_host(user):
    """The user if they may sign in on this host, else None (the caller answers "invalid e-mail or password",
    so a refusal never tells whether the account exists)."""
    if user is None:
        return None
    if not user_allowed_here(user):
        logger.info('sign-in refused on this host: user=%s', getattr(user, 'id', None))
        return None
    site = site_for_request()
    if site is not None and not _is_superadmin(user) and site.modes and _mode_of(user) not in site.modes:
        logger.info('sign-in refused: access mode not allowed on site %s: user=%s', site['id'], getattr(user, 'id', None))
        return None
    return user


def landing_endpoint(user, default):
    """On a client host: the user's own home (the restricted workspace for restricted users)."""
    if site_for_request() is None:
        return default
    try:
        from access import service as S
        return S.home_endpoint(S.effective(user))
    except Exception:
        return default


def login_template(default):
    return 'client_sites/login.html' if site_for_request() is not None else default


# ------------------------------------------------------------------ limits
def site_by_id(site_id, db=None):
    if not site_id:
        return None
    db = _db(db)
    r = db.execute('SELECT * FROM client_sites WHERE id = %s', (int(site_id),)).fetchone()
    return Site(r) if r else None


def default_limit_for_user(user, db=None):
    """The site's default daily limit for a user bound to a site (None: no site / no site default)."""
    sid = user_site_id(user, db)
    if not sid:
        return None
    db = _db(db)
    try:
        r = db.execute('SELECT default_daily_screening_limit AS d FROM client_sites WHERE id = %s', (int(sid),)).fetchone()
    except Exception:
        _rollback(db)
        return None
    return None if not r or r['d'] is None else int(r['d'])


def cap_for_user(user, db=None):
    """(site id, monthly cap) when the user's site has a monthly organisation cap, else None."""
    if user is None or _is_superadmin(user):
        return None
    sid = user_site_id(user, db)
    if not sid:
        return None
    db = _db(db)
    try:
        r = db.execute('SELECT monthly_org_cap AS c FROM client_sites WHERE id = %s', (int(sid),)).fetchone()
    except Exception:
        _rollback(db)
        return None
    cap = int(r['c'] or 0) if r else 0
    return (int(sid), cap) if cap > 0 else None


def month_bounds(day):
    start = day.replace(day=1)
    nxt = (start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1))
    return start, nxt


def month_used(site_id, day, db=None):
    """Vessel + dual-use screenings of all the site's users in the calendar month of day."""
    db = _db(db)
    start, nxt = month_bounds(day)
    r = db.execute("""SELECT COALESCE(sum(d.n), 0) AS n FROM screening_daily_usage d JOIN users u ON u.id = d.user_id
                       WHERE u.site_id = %s AND d.kind = ANY(%s) AND d.day >= %s AND d.day < %s""",
                   (int(site_id), list(CAP_KINDS), start, nxt)).fetchone()
    return int(r['n'] or 0) if r else 0


def usage_by_user(site_id, day, db=None):
    """[{id, name, email, role, name_n, vessel, dualuse, capped}] for the month of day, plus the capped total."""
    db = _db(db)
    start, nxt = month_bounds(day)
    rows = db.execute("""SELECT u.id, u.email, u.role, TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS name,
                                d.kind, COALESCE(sum(d.n), 0) AS n
                           FROM users u
                           LEFT JOIN screening_daily_usage d ON d.user_id = u.id AND d.day >= %s AND d.day < %s
                          WHERE u.site_id = %s
                          GROUP BY u.id, u.email, u.role, u.first_name, u.last_name, d.kind
                          ORDER BY u.first_name, u.last_name, u.email""", (start, nxt, int(site_id))).fetchall()
    out = {}
    for r in rows:
        x = out.setdefault(r['id'], {'id': r['id'], 'name': r['name'] or r['email'], 'email': r['email'],
                                     'role': r['role'], 'name_n': 0, 'vessel': 0, 'dualuse': 0})
        if r['kind'] in ('vessel', 'dualuse'):
            x[r['kind']] += int(r['n'] or 0)
        elif r['kind']:
            x['name_n'] += int(r['n'] or 0)
    users = list(out.values())
    for x in users:
        x['capped'] = x['vessel'] + x['dualuse']
    users.sort(key=lambda x: -x['capped'])
    return users, sum(x['capped'] for x in users), start


# ------------------------------------------------------------------ superadmin forms
def parse_form(form, existing_id=None, db=None):
    """(data, errors) from the create / edit form. errors: list of (en, ar) messages."""
    errs = []
    host = normalise_host(form.get('host'))
    if not HOST_RE.match(host or ''):
        errs.append(('Enter a valid host name, e.g. client.complynex.online.', 'أدخل اسم نطاق صحيحاً، مثل client.complynex.online.'))
    elif host in main_hosts():
        errs.append(('This host is one of the main hosts of the platform.', 'هذا النطاق من النطاقات الرئيسية للمنصة.'))
    name_en = (form.get('name_en') or '').strip()[:200]
    if not name_en:
        errs.append(('The English name is required.', 'الاسم بالإنجليزية مطلوب.'))
    modes = [m for m in MODES if m in form.getlist('allowed_access_modes')]
    if not modes:
        errs.append(('Choose at least one access mode.', 'اختر نوع وصول واحداً على الأقل.'))
    dmode = (form.get('default_access_mode') or '').strip()
    if dmode not in modes:
        dmode = modes[0] if modes else 'restricted'
    email = (form.get('contact_email') or '').strip()[:254]
    if email and not EMAIL_RE.match(email):
        errs.append(('Enter a valid contact e-mail.', 'أدخل بريداً إلكترونياً صحيحاً للتواصل.'))

    def _int(key, allow_blank):
        raw = (form.get(key) or '').strip()
        if raw == '' and allow_blank:
            return None
        try:
            v = int(raw or 0)
        except ValueError:
            v = -1
        if v < 0 or v > 10_000_000:
            errs.append(('Limits are whole numbers, 0 or more.', 'الحدود أرقام صحيحة تساوي صفراً أو أكثر.'))
            return 0
        return v

    data = {
        'host': host, 'name_en': name_en, 'name_ar': (form.get('name_ar') or '').strip()[:200] or None,
        'welcome_en': (form.get('welcome_en') or '').strip()[:2000] or None,
        'welcome_ar': (form.get('welcome_ar') or '').strip()[:2000] or None,
        'allowed_access_modes': modes, 'default_access_mode': dmode, 'contact_email': email or None,
        'default_daily_screening_limit': _int('default_daily_screening_limit', True),
        'monthly_org_cap': _int('monthly_org_cap', False) or 0,
        'active': form.get('active') in ('1', 'on', 'true'),
    }
    if not errs and host:
        db = _db(db)
        r = db.execute('SELECT id FROM client_sites WHERE host = %s AND id <> %s', (host, int(existing_id or 0))).fetchone()
        if r:
            errs.append(('Another client site already uses this host.', 'هذا النطاق مستخدم لموقع عميل آخر.'))
    return data, errs


_COLS = ('host', 'name_en', 'name_ar', 'welcome_en', 'welcome_ar', 'allowed_access_modes', 'default_access_mode',
         'contact_email', 'default_daily_screening_limit', 'monthly_org_cap', 'active')


def save_site(data, site_id=None, db=None):
    db = _db(db)
    vals = [data[c] for c in _COLS]
    if site_id:
        db.execute('UPDATE client_sites SET ' + ', '.join(f'{c} = %s' for c in _COLS) + ', updated_at = now() WHERE id = %s',
                   (*vals, int(site_id)))
    else:
        r = db.execute('INSERT INTO client_sites (' + ', '.join(_COLS) + ') VALUES (' + ', '.join(['%s'] * len(_COLS))
                       + ') RETURNING id', tuple(vals)).fetchone()
        site_id = r['id']
    db.commit()
    invalidate()
    return int(site_id)


# ------------------------------------------------------------------ logo
_SVG_NS = 'http://www.w3.org/2000/svg'
_XLINK_NS = 'http://www.w3.org/1999/xlink'
_SVG_TAGS = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'text', 'tspan', 'defs',
             'lineargradient', 'radialgradient', 'stop', 'clippath', 'mask', 'title', 'desc', 'use', 'symbol'}


def _local(tag):
    return str(tag).rsplit('}', 1)[-1].lower()


def sanitise_svg(raw):
    """A clean SVG (bytes) or ValueError: no DTD / entities, scripts, event handlers, foreign objects, styles
    or external references. Only drawing elements and their presentation attributes are kept."""
    import xml.etree.ElementTree as ET
    from defusedxml import ElementTree as DET
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise ValueError('svg_encoding')
    if re.search(r'<!(DOCTYPE|ENTITY)', text, re.I):
        raise ValueError('svg_dtd')
    try:
        root = DET.fromstring(text)
    except Exception:
        raise ValueError('svg_parse')
    if _local(root.tag) != 'svg':
        raise ValueError('svg_root')

    def clean(el):
        for child in list(el):
            if not isinstance(child.tag, str) or _local(child.tag) not in _SVG_TAGS:
                el.remove(child)
                continue
            clean(child)
        for k in list(el.attrib):
            name = _local(k)
            v = str(el.attrib[k])
            low = re.sub(r'\s+', '', v).lower()
            if name.startswith('on') or name == 'style' or 'javascript:' in low or 'data:' in low \
                    or ('url(' in low and not low.startswith('url(#')) \
                    or (name == 'href' and not v.startswith('#')):
                del el.attrib[k]

    clean(root)
    ET.register_namespace('', _SVG_NS)
    ET.register_namespace('xlink', _XLINK_NS)
    return ET.tostring(root, encoding='utf-8')


def check_logo(filename, raw):
    """(extension, bytes) of an accepted logo, or ValueError(code)."""
    if not raw:
        raise ValueError('empty')
    if len(raw) > LOGO_MAX_BYTES:
        raise ValueError('too_big')
    ext = (filename or '').rsplit('.', 1)[-1].lower() if '.' in (filename or '') else ''
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        kind = 'png'
    elif raw.startswith(b'\xff\xd8\xff'):
        kind = 'jpg'
    elif ext == 'svg':
        return 'svg', sanitise_svg(raw)
    else:
        raise ValueError('type')
    if ext not in ('png', 'jpg', 'jpeg'):
        raise ValueError('type')
    try:
        import io
        from PIL import Image
        Image.open(io.BytesIO(raw)).verify()
    except ImportError:
        pass
    except Exception:
        raise ValueError('image')
    return kind, raw


LOGO_ERRORS = {
    'empty': ('The logo file is empty.', 'ملف الشعار فارغ.'),
    'too_big': ('The logo is larger than 512 KB.', 'حجم الشعار أكبر من 512 كيلوبايت.'),
    'type': ('The logo must be a PNG, JPG or SVG file.', 'يجب أن يكون الشعار ملف PNG أو JPG أو SVG.'),
    'image': ('The logo image could not be read.', 'تعذّرت قراءة صورة الشعار.'),
}


def logo_error(code):
    return LOGO_ERRORS.get(code, ('The SVG logo is not accepted (it must be a plain drawing, without scripts or '
                                  'external references).', 'شعار SVG غير مقبول (يجب أن يكون رسماً بسيطاً بلا نصوص برمجية '
                                  'أو مراجع خارجية).'))


def uploads_root():
    return current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.root_path, 'uploads')


def store_logo(site_id, filename, raw, db=None):
    ext, data = check_logo(filename, raw)
    folder = os.path.join(uploads_root(), LOGO_DIR)
    os.makedirs(folder, exist_ok=True)
    for old in ('png', 'jpg', 'svg'):
        p = os.path.join(folder, f'site_{int(site_id)}.{old}')
        if old != ext and os.path.exists(p):
            os.remove(p)
    rel = f'{LOGO_DIR}/site_{int(site_id)}.{ext}'
    with open(os.path.join(uploads_root(), rel), 'wb') as fh:
        fh.write(data)
    db = _db(db)
    db.execute('UPDATE client_sites SET logo_path = %s, updated_at = now() WHERE id = %s', (rel, int(site_id)))
    db.commit()
    invalidate()
    return rel


def remove_logo(site_id, db=None):
    db = _db(db)
    site = site_by_id(site_id, db)
    if site and site.get('logo_path'):
        p = _logo_file(site)
        if p and os.path.exists(p):
            os.remove(p)
    db.execute('UPDATE client_sites SET logo_path = NULL, updated_at = now() WHERE id = %s', (int(site_id),))
    db.commit()
    invalidate()


def _logo_file(site):
    rel = (site.get('logo_path') or '').strip()
    if not re.fullmatch(LOGO_DIR + r'/site_\d+\.(png|jpg|svg)', rel):
        return None
    return os.path.join(uploads_root(), rel)


def logo_response(site_id):
    """The site's logo: on its own host, or for the superadmin anywhere (admin pages). Else 404."""
    from flask import abort, send_file
    from flask_login import current_user
    here = site_for_request()
    is_super = bool(getattr(current_user, 'is_authenticated', False)) and _is_superadmin(current_user)
    if not is_super and (here is None or int(here['id']) != int(site_id)):
        abort(404)
    site = here if here is not None and int(here['id']) == int(site_id) else site_by_id(site_id)
    path = _logo_file(site) if site else None
    if not path or not os.path.exists(path):
        abort(404)
    mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'svg': 'image/svg+xml'}[path.rsplit('.', 1)[-1]]
    resp = send_file(path, mimetype=mime, max_age=300)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    return resp


# ------------------------------------------------------------------ users
def site_members(site_id, db=None):
    db = _db(db)
    return db.execute("""SELECT id, email, role, access_mode, screening_daily_limit,
                                TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS name, is_active
                           FROM users WHERE site_id = %s ORDER BY first_name, last_name, email""", (int(site_id),)).fetchall()


def assignable_users(db=None):
    db = _db(db)
    return db.execute("""SELECT id, email, role, TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS name
                           FROM users WHERE site_id IS NULL AND COALESCE(role, '') <> 'superadmin'
                            AND COALESCE(is_active, 1) = 1
                          ORDER BY first_name, last_name, email""").fetchall()


def assign_user(site_id, user_id, db=None):
    """Bind a user to a site: the access mode becomes the site's default mode when the user's mode is not
    allowed there; the user's sessions elsewhere end (auth_version + 1). The superadmin is never bound."""
    db = _db(db)
    site = site_by_id(site_id, db)
    u = db.execute('SELECT id, role, access_mode FROM users WHERE id = %s', (int(user_id),)).fetchone()
    if not site or not u or (u['role'] or '') == 'superadmin':
        return False
    mode = u['access_mode']
    if mode not in site.modes:
        mode = site['default_access_mode']
    db.execute('UPDATE users SET site_id = %s, access_mode = %s, auth_version = COALESCE(auth_version, 0) + 1 WHERE id = %s',
               (int(site_id), mode, int(user_id)))
    db.commit()
    return True


def unassign_user(site_id, user_id, db=None):
    db = _db(db)
    db.execute('UPDATE users SET site_id = NULL, auth_version = COALESCE(auth_version, 0) + 1 WHERE id = %s AND site_id = %s',
               (int(user_id), int(site_id)))
    db.commit()
    return True


def all_sites(db=None):
    db = _db(db)
    return [Site(r) for r in db.execute(
        """SELECT s.*, (SELECT count(*) FROM users u WHERE u.site_id = s.id) AS users_n
             FROM client_sites s ORDER BY s.name_en""").fetchall()]
