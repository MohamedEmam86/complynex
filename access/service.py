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
Per-user grants: effective access, saving the administrator's matrix (with write-through to the old
perm_* columns so every existing module guard agrees with the matrix), copy from another user, backfill
and the audit trail.

Effective access of a user for a feature:
  superadmin                       -> always (unrestricted)
  explicit row in user_access_grants -> that decision
  no row, mode 'restricted'        -> refused
  no row, mode 'cms' / 'portal'    -> the old rule (registry Feature.old_rule) — nothing changes for users
                                      nobody has edited
Portal features are never available in a restricted workspace.
"""

import json
import logging
from datetime import datetime

from flask_babel import lazy_gettext as _l

from database.db import get_db

from . import registry as R

logger = logging.getLogger(__name__)

UNRESTRICTED_ROLES = ('superadmin',)
EDITOR_ROLES = ('admin', 'superadmin')


def is_unrestricted(user):
    return (getattr(user, 'role', '') or '') in UNRESTRICTED_ROLES


def can_manage_access(user):
    return bool(getattr(user, 'is_authenticated', False)) and (getattr(user, 'role', '') or '') in EDITOR_ROLES


# ------------------------------------------------------------------ reading
def _explicit(user_id, db=None):
    db = db or get_db()
    try:
        return {r['feature']: bool(r['granted']) for r in db.execute(
            "SELECT feature, granted FROM user_access_grants WHERE user_id = %s", (user_id,)).fetchall()}
    except Exception:
        db.rollback()       # table not migrated yet: behave as before
        return {}


class Access:
    """What one user may do. ``granted`` is the set of feature keys."""

    def __init__(self, user, mode, granted, explicit, unrestricted=False):
        self.user_id = getattr(user, 'id', None)
        self.mode = mode
        self.granted = set(granted)
        self.explicit = explicit
        self.unrestricted = unrestricted
        self.managed = bool(explicit)

    def has(self, key):
        return self.unrestricted or key in self.granted

    def modules(self):
        """Modules with at least one granted feature (registry order)."""
        return [m for m in R.modules() if any(self.has(f.key) for f in m.features)]


def mode_of(user):
    mode = getattr(user, 'access_mode', None)
    return mode if mode in R.MODES else R.legacy_mode(user)


def compute(user, mode=None, explicit=None, db=None):
    """Effective access (not cached). ``mode``/``explicit`` override the stored ones (preview)."""
    if is_unrestricted(user):
        return Access(user, mode or mode_of(user), [f.key for f in R.all_features()], {}, unrestricted=True)
    mode = mode or mode_of(user)
    if explicit is None:
        explicit = _explicit(user.id, db) if getattr(user, 'id', None) else {}
    granted = []
    for f in R.all_features():
        if mode == 'restricted' and (not f.module.workspace_ok or not f.workspace):
            continue
        if f.platform:
            continue            # only the superadmin, who is unrestricted
        if f.key in explicit:
            ok = explicit[f.key]
        elif mode == 'restricted':
            ok = False
        else:
            try:
                ok = R.allows(user, f.old_rule)
            except Exception:
                logger.warning('access: old rule of %s failed', f.key, exc_info=True)
                ok = False
        if ok:
            granted.append(f.key)
    return Access(user, mode, granted, explicit)


def effective(user):
    """Effective access of a user, cached for the request."""
    try:
        from flask import g, has_app_context
        if has_app_context():
            cache = g.setdefault('_cx_access', {})
            key = (getattr(user, 'id', None), getattr(user, 'access_mode', None))
            if key not in cache:
                cache[key] = compute(user)
            return cache[key]
    except RuntimeError:
        pass
    return compute(user)


def reset_cache():
    try:
        from flask import g
        g.pop('_cx_access', None)
    except Exception:
        pass


def team_view(user, key, old_rule):
    """May this user see colleagues' records in a module (feature `key`, e.g. 'vessels.team')? A restricted
    user never does (own records only); the superadmin always; otherwise the user's grant, which for users
    nobody edited is the module's own old rule `old_rule` (passed by the caller, also used when the registry
    is not built)."""
    if is_unrestricted(user):
        return True
    if not R.is_built() or key not in R.FEATURES:
        return bool(old_rule)
    try:
        from flask import current_app
        if not current_app.config.get('ACCESS_CONTROL', True):
            return bool(old_rule)
    except RuntimeError:
        pass
    acc = effective(user)
    if acc.mode == 'restricted':
        return False
    return acc.has(key)


# ------------------------------------------------------------------ endpoints
ALWAYS = ('static', 'set_language', 'favicon', 'health', 'auth.*', 'access.workspace', 'access.workspace_login', 'legal.*',
          'users.profile', 'users.update_profile', 'users.upload_avatar', 'users.download_avatar', 'users.change_password',
          'users.password_change_required')
HOMES = ('index', 'dashboard', 'portal.dashboard')


def _always(endpoint):
    import fnmatch
    return any(fnmatch.fnmatchcase(endpoint, p) for p in ALWAYS)


def endpoint_allowed(access, endpoint):
    """The one check used by the request gate, the menus, the landing pages and the APIs."""
    if not endpoint or access.unrestricted or _always(endpoint):
        return True
    key = R.feature_for(endpoint)
    if access.mode == 'restricted':
        return bool(key) and access.has(key)
    if key is None:
        return True             # not part of any module (public pages, sign-in, API keys) — unchanged
    return access.has(key)


def home_endpoint(access):
    """Where this user lands."""
    if access.mode == 'restricted':
        return 'access.workspace'
    if access.mode == 'cms':
        return 'dashboard'
    return 'portal.dashboard' if access.has('portal.home') else 'access.workspace'


# ------------------------------------------------------------------ writing
def _user_columns(db):
    try:
        return {r['column_name'] for r in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'").fetchall()}
    except Exception:
        db.rollback()
        return set()


def _stored_level(db, user_id, module, cols, row):
    col = f'perm_{module}'
    if col in cols:
        return (row.get(col) or 'none') if row else 'none'
    r = db.execute("SELECT level FROM user_module_permissions WHERE user_id = %s AND module = %s",
                   (user_id, module)).fetchone()
    return r['level'] if r else 'none'


def write_through(db, user_id, granted, added=(), removed=()):
    """Keep the old perm_* levels in line with the matrix, so the module guards that still check them agree:
    * a feature granted by this change raises the level its pages need;
    * a feature taken away by this change lowers the level to what the remaining features need;
    * otherwise the stored level is left alone (re-saving an unchanged matrix changes nothing, and a stored
      level that no feature describes — e.g. 'admin' — survives)."""
    cols = _user_columns(db)
    row = db.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    row = dict(row) if row else {}

    def _max(keys, mod):
        top = 'none'
        for k in keys:
            f = R.FEATURES.get(k)
            lvl = f.write_perms.get(mod) if f else None
            if lvl and R.RANK[lvl] > R.RANK[top]:
                top = lvl
        return top

    mods = {mod for f in R.all_features() for mod in f.write_perms}
    changes = {}
    for mod in sorted(mods):
        old = _stored_level(db, user_id, mod, cols, row)
        new = old
        up = _max(added, mod)
        if R.RANK[up] > R.RANK.get(new, 0):
            new = up
        if _max(removed, mod) != 'none':
            keep = _max(granted, mod)
            if R.RANK.get(new, 0) > R.RANK[keep]:
                new = keep
        if new == old:
            continue
        col = f'perm_{mod}'
        if col in cols:
            db.execute(f'UPDATE users SET {col} = %s WHERE id = %s', (new, user_id))
        else:
            lvl = new if new in ('none', 'view', 'edit', 'admin') else 'edit'
            db.execute("""INSERT INTO user_module_permissions (user_id, module, level, updated_at) VALUES (%s,%s,%s,%s)
                          ON CONFLICT (user_id, module) DO UPDATE SET level = EXCLUDED.level,
                              updated_at = EXCLUDED.updated_at""", (user_id, mod, lvl, datetime.now()))
        changes[mod] = (old, new)
    return changes


def expand_requires(keys):
    """Add the features a granted feature needs (e.g. 'screen' needs 'view')."""
    out = set(k for k in keys if k in R.FEATURES)
    todo = list(out)
    while todo:
        f = R.FEATURES.get(todo.pop())
        for r in (f.requires if f else ()):
            if r in R.FEATURES and r not in out:
                out.add(r)
                todo.append(r)
    return out


class AccessError(ValueError):
    pass


def locked_for(actor):
    """Feature keys this editor may not change (their grant_by roles exclude the editor). None = the system."""
    if actor is None or is_unrestricted(actor):
        return set()
    role = getattr(actor, 'role', '') or ''
    return {k for k, f in R.FEATURES.items() if f.grant_by and role not in f.grant_by}


def save(user, mode, granted, actor_id=None, cms_level=None, source='admin', note=None, ip=None, db=None):
    """Store a user's complete access: mode + one row per feature. Returns (added, removed)."""
    from models.user import User
    db = db or get_db()
    if mode not in R.MODES:
        raise AccessError(_l('Choose where this user works: CMS, employee portal or restricted workspace.'))
    if is_unrestricted(user):
        raise AccessError(_l('The superadmin is unrestricted; there is nothing to save.'))
    granted = expand_requires(granted)
    if mode == 'restricted':
        granted = {k for k in granted if R.FEATURES[k].module.workspace_ok and R.FEATURES[k].workspace}
    actor = User.get_by_id(actor_id) if actor_id else None
    if actor is not None and actor.id == user.id and not is_unrestricted(actor):
        # nobody changes their own access (no self-escalation, no self-lockout); another administrator must
        raise AccessError(_l('You cannot change your own access. Ask another administrator.'))
    before = compute(user, db=db)
    # features only some roles may grant (e.g. the Vessels Database: superadmin): an editor without that role
    # leaves them exactly as they are
    locked = locked_for(actor)
    granted = {k for k in granted if k not in locked} | {k for k in locked if before.has(k)}
    if mode == 'restricted':
        granted = {k for k in granted if R.FEATURES[k].module.workspace_ok and R.FEATURES[k].workspace}
    now = datetime.now()
    for f in R.all_features():
        db.execute("""INSERT INTO user_access_grants (user_id, feature, granted, source, updated_by, updated_at)
                      VALUES (%s, %s, %s, %s, %s, %s)
                      ON CONFLICT (user_id, feature) DO UPDATE SET granted = EXCLUDED.granted,
                          source = CASE WHEN user_access_grants.granted = EXCLUDED.granted
                                        THEN user_access_grants.source ELSE EXCLUDED.source END,
                          updated_by = CASE WHEN user_access_grants.granted = EXCLUDED.granted
                                        THEN user_access_grants.updated_by ELSE EXCLUDED.updated_by END,
                          updated_at = CASE WHEN user_access_grants.granted = EXCLUDED.granted
                                        THEN user_access_grants.updated_at ELSE EXCLUDED.updated_at END""",
                   (user.id, f.key, f.key in granted, source, actor_id, now))
    old_cms = getattr(user, 'cms_access_level', None) or 'none'
    if mode == 'cms':
        cms = cms_level if cms_level in ('view', 'edit') else (old_cms if old_cms in ('view', 'edit') else 'view')
    else:
        cms = 'none'
    db.execute("UPDATE users SET access_mode = %s, cms_access_level = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
               (mode, cms, user.id))
    added = sorted(granted - before.granted)
    removed = sorted(before.granted - granted)
    perms = write_through(db, user.id, granted, added, removed)
    if added or removed or before.mode != mode or source != 'admin' or not before.managed:
        db.execute("""INSERT INTO user_access_audit (user_id, actor_id, action, mode_before, mode_after, added, removed,
                                                     note, ip_address)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (user.id, actor_id, source if source != 'admin' else 'save', before.mode, mode,
                    json.dumps(added), json.dumps(removed),
                    (note or '') + (f" perm levels: {json.dumps(perms)}" if perms else ''), ip))
    db.commit()
    reset_cache()
    try:
        from models.audit import AuditLog
        for k in [k for k in added + removed if R.FEATURES.get(k) and R.FEATURES[k].grant_by]:
            AuditLog.log(actor_id, 'Restricted Feature ' + ('Granted' if k in added else 'Removed'), 'Admin', user.id,
                         f'{user.email}: {k}', ip)
        AuditLog.log(actor_id, 'Update Access Rights', 'Admin', user.id,
                     f'{user.email}: mode {before.mode}->{mode}; +{len(added)} -{len(removed)} features'
                     + (f' ({note})' if note else ''), ip)
    except Exception:
        logger.warning('access: audit log failed', exc_info=True)
    return added, removed


def copy_from(source_user, target_user, actor_id=None, ip=None, db=None):
    src = compute(source_user, db=db)
    return save(target_user, src.mode, src.granted, actor_id=actor_id,
                cms_level=getattr(source_user, 'cms_access_level', None), source='copy',
                note=f'copied from user {source_user.id}', ip=ip, db=db)


def form_to_access(form):
    """(mode, granted, cms_level) from the matrix fields: cx_mode, cx_feature (multi), cx_cms_level."""
    mode = form.get('cx_mode')
    granted = set(form.getlist('cx_feature')) if hasattr(form, 'getlist') else set(form.get('cx_feature') or [])
    return mode, {k for k in granted if k in R.FEATURES}, form.get('cx_cms_level')


def history(user_id=None, limit=200, db=None):
    db = db or get_db()
    sql = """SELECT a.*, u.email AS user_email, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS user_name,
                    ac.email AS actor_email, TRIM(COALESCE(ac.first_name,'') || ' ' || COALESCE(ac.last_name,'')) AS actor_name
               FROM user_access_audit a JOIN users u ON u.id = a.user_id LEFT JOIN users ac ON ac.id = a.actor_id"""
    args = []
    if user_id:
        sql += " WHERE a.user_id = %s"
        args.append(user_id)
    sql += " ORDER BY a.created_at DESC, a.id DESC LIMIT %s"
    args.append(limit)
    try:
        rows = [dict(r) for r in db.execute(sql, tuple(args)).fetchall()]
    except Exception:
        db.rollback()
        return []
    for r in rows:
        r['added'] = json.loads(r['added'] or '[]')
        r['removed'] = json.loads(r['removed'] or '[]')
    return rows


# ------------------------------------------------------------------ backfill
def signin_url(user):
    """The sign-in address to give a user: the workspace sign-in for a restricted user, the portal sign-in for a
    portal user, the CMS sign-in otherwise (absolute URL, for e-mails and the one-time-password page)."""
    from flask import url_for
    mode = mode_of(user)
    ep = {'restricted': 'access.workspace_login', 'portal': 'auth.portal_login'}.get(mode, 'auth.login')
    return url_for(ep, _external=True)


def send_welcome(user, url=None):
    """Welcome e-mail with the sign-in link (bilingual). The temporary password is never e-mailed."""
    try:
        from utils.email import send_confirmation_email
        from models.settings import Settings
        company = Settings.get('company_name', 'ComplyNex')
    except Exception:
        logger.warning('access: welcome e-mail unavailable', exc_info=True)
        return False
    access = compute(user)
    mods = []
    for lang in ('en', 'ar'):
        mods.append([m.label(lang) for m in access.modules() if m.surface == 'cms'])
    return bool(send_confirmation_email(
        user.email, f'{company}: your access / وصولك', 'emails/access_welcome.html',
        user=user, url=url or signin_url(user), company=company, mode=access.mode,
        modules_en=mods[0], modules_ar=mods[1]))


def backfill(db=None, dry_run=False, only_user_ids=None, note=None):
    """Write today's effective access as explicit grants for every user that has none yet (idempotent:
    users with rows are skipped). Nothing changes in what anybody can do: the rows equal the old rules.
    Superadmins stay unrestricted (no rows)."""
    from models.user import User
    db = db or get_db()
    done = []
    if only_user_ids:
        rows = db.execute("SELECT * FROM users WHERE id = ANY(%s) ORDER BY id", (list(only_user_ids),)).fetchall()
    else:
        rows = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    for row in rows:
        u = User._from_row(row)
        if is_unrestricted(u):
            continue
        if db.execute("SELECT 1 FROM user_access_grants WHERE user_id = %s LIMIT 1", (u.id,)).fetchone():
            continue
        acc = compute(u, explicit={}, db=db)
        done.append((u.id, acc.mode, len(acc.granted)))
        if dry_run:
            continue
        now = datetime.now()
        for f in R.all_features():
            db.execute("""INSERT INTO user_access_grants (user_id, feature, granted, source, updated_at)
                          VALUES (%s, %s, %s, 'backfill', %s) ON CONFLICT (user_id, feature) DO NOTHING""",
                       (u.id, f.key, f.key in acc.granted, now))
        db.execute("UPDATE users SET access_mode = %s WHERE id = %s AND access_mode IS NULL", (acc.mode, u.id))
        db.execute("""INSERT INTO user_access_audit (user_id, action, mode_before, mode_after, added, removed, note)
                      VALUES (%s, 'backfill', %s, %s, %s, '[]', %s)""",
                   (u.id, acc.mode, acc.mode, json.dumps(sorted(acc.granted)),
                    note or "today's access written as explicit grants"))
    if not dry_run:
        db.commit()
    return done
