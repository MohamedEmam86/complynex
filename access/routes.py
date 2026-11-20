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
Pages of the access-control module:
  /workspace                          restricted workspace: only the modules granted to the user
  /admin/access/users/<id>            the access matrix of one user (also embedded in the user edit page)
  /admin/access/users/<id>  POST      save it
  /admin/access/users/<id>/copy POST  copy another user's access ("copy from user")
  /admin/access/users/<id>/preview    effective-access preview of the ticked matrix (JSON)
  /admin/access/audit                 every access change
Editing access: administrators and the superadmin; the superadmin's own access is unrestricted.
"""

from functools import wraps

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import get_locale, gettext as _
from flask_login import current_user, login_required

from . import registry as R
from . import service as S

bp = Blueprint('access', __name__)


def _lang():
    return str(get_locale() or 'en')[:2]


def _editor(f):
    @wraps(f)
    @login_required
    def wrapped(*a, **kw):
        if not S.can_manage_access(current_user):
            abort(403)
        return f(*a, **kw)
    return R.mark(('role', S.EDITOR_ROLES))(wrapped)


def _safe_next(nxt):
    """A local path only (no scheme, no host, no protocol-relative or backslash tricks), else None."""
    nxt = (nxt or '').strip()
    if not nxt.startswith('/') or nxt.startswith('//') or '\\' in nxt or any(ord(c) < 32 for c in nxt):
        return None
    return nxt


def _target(user_id):
    from models.user import User
    u = User.get_by_id(user_id)
    if not u:
        abort(404)
    return u


# ------------------------------------------------------------------ restricted workspace
@bp.route('/workspace')
@login_required
def workspace():
    access = S.effective(current_user)
    from .gate import cx_modules
    tiles = cx_modules()
    if access.mode != 'restricted':
        tiles = [t for t in tiles if t['module'].surface == 'cms']
    return render_template('access/workspace.html', tiles=tiles, access=access)


# ------------------------------------------------------------------ matrix
def _blank_user(role='employee'):
    """A user that does not exist yet (add-user page / preview): no id, no grants, no module levels."""
    from models.user import User
    u = User(id=None, email='', password_hash='', first_name='', last_name='', role=role or 'employee')
    u._module_perms = {}
    return u


def matrix_context(user=None):
    """Everything the matrix partial needs for one user (None: the add-user page, which starts from what a
    new employee gets — the employee portal with its items — and is then ticked by the administrator)."""
    from models.user import User
    lang = _lang()
    if user is not None:
        access = S.compute(user)
    else:
        access = S.compute(_blank_user(), mode='portal', explicit={k: f.module.surface in ('portal', 'shell')
                                                                  for k, f in R.FEATURES.items()})
    editor = current_user if getattr(current_user, 'is_authenticated', False) else None
    locked = S.locked_for(editor)
    self_locked = bool(user is not None and editor is not None and editor.id == user.id
                       and not S.is_unrestricted(editor))
    areas = []
    for m in R.modules():
        feats = [{'key': f.key, 'label': f.label(lang), 'hint': f.hint(lang), 'kind': f.kind,
                  'requires': list(f.requires), 'checked': access.has(f.key),
                  'locked': f.key in locked, 'workspace': f.workspace,
                  'pages': len(f.endpoints)} for f in m.features if (f.endpoints or f.perms is not None) and not f.platform]
        if not feats:
            continue
        a_en, a_ar, _o = R.AREAS.get(m.area, (m.area, m.area, 999))
        if not areas or areas[-1]['key'] != m.area:
            areas.append({'key': m.area, 'label': a_ar if lang == 'ar' else a_en, 'modules': []})
        areas[-1]['modules'].append({'key': m.key, 'label': m.label(lang), 'icon': m.icon, 'surface': m.surface,
                                     'desc': m.desc(lang), 'features': feats,
                                     'granted': sum(1 for f in feats if f['checked'])})
    others = [u for u in User.get_all() if (user is None or u.id != user.id) and not S.is_unrestricted(u)]
    try:
        from screening.limits import default_limit
        limit_default = default_limit()
    except Exception:
        limit_default = 0
    return {'cx_user': user, 'cx_access': access, 'cx_areas': areas, 'cx_others': others, 'cx_self_locked': self_locked,
            'cx_limit_default': limit_default,
            'cx_unrestricted': bool(user is not None and S.is_unrestricted(user)),
            'cx_history': S.history(user.id, limit=15) if user is not None else [],
            'cx_feature_labels': {k: f.label(lang) for k, f in R.FEATURES.items()},
            'cx_total': sum(len(m['features']) for a in areas for m in a['modules'])}


@bp.route('/admin/access/users/<int:user_id>', methods=['GET'])
@_editor
def admin_user(user_id):
    user = _target(user_id)
    return render_template('access/user.html', **matrix_context(user))


@bp.route('/admin/access/users/<int:user_id>', methods=['POST'])
@_editor
def admin_save(user_id):
    user = _target(user_id)
    mode, granted, cms = S.form_to_access(request.form)
    try:
        added, removed = S.save(user, mode, granted, actor_id=current_user.id, cms_level=cms,
                                note=(request.form.get('cx_note') or '').strip()[:300] or None,
                                ip=request.remote_addr)
    except S.AccessError as e:
        flash(str(e), 'danger')
        return redirect(url_for('access.admin_user', user_id=user_id))
    from screening.limits import apply_form as _limit_form
    _limit_form(user.id, request.form, current_user.id, ip=request.remote_addr)
    flash(_('Access saved: %(a)s granted, %(r)s removed.', a=len(added), r=len(removed)), 'success')
    return redirect(_safe_next(request.form.get('next')) or url_for('access.admin_user', user_id=user_id))


@bp.route('/admin/access/users/<int:user_id>/copy', methods=['POST'])
@_editor
def admin_copy(user_id):
    user = _target(user_id)
    try:
        src = _target(int(request.form.get('source_user_id') or 0))
    except (TypeError, ValueError):
        abort(400)
    if src.id == user.id or S.is_unrestricted(src):
        flash(_('Choose another user to copy from.'), 'warning')
    else:
        try:
            added, removed = S.copy_from(src, user, actor_id=current_user.id, ip=request.remote_addr)
            flash(_('Access copied from %(name)s: %(a)s granted, %(r)s removed.', name=src.get_full_name(),
                    a=len(added), r=len(removed)), 'success')
        except S.AccessError as e:
            flash(str(e), 'danger')
    return redirect(_safe_next(request.form.get('next')) or url_for('access.admin_user', user_id=user_id))


@bp.route('/admin/access/users/<int:user_id>/grants')
@_editor
def admin_grants(user_id):
    """A user's effective access as data — "copy from user" on the add-user page ticks these boxes."""
    src = _target(user_id)
    acc = S.compute(src)
    return jsonify({'mode': acc.mode, 'features': sorted(acc.granted),
                    'cms_level': getattr(src, 'cms_access_level', None) or 'view'})


@bp.route('/admin/access/preview')
@_editor
def admin_preview_new():
    """Preview for a user being created (role taken from the form)."""
    return admin_preview(None)


@bp.route('/admin/access/users/<int:user_id>/preview')
@_editor
def admin_preview(user_id):
    """What the user would see with the ticked matrix (not saved)."""
    user = _target(user_id) if user_id else _blank_user(request.args.get('role'))
    mode = request.args.get('mode') or S.mode_of(user)
    if mode not in R.MODES:
        abort(400)
    ticked = S.expand_requires(request.args.getlist('f'))
    explicit = {k: (k in ticked) for k in R.FEATURES}
    access = S.compute(user, mode=mode, explicit=explicit)
    lang = _lang()
    pages = [ep for ep in R.ENDPOINT_FEATURE if S.endpoint_allowed(access, ep)]
    mods = []
    for m in access.modules():
        mods.append({'label': m.label(lang), 'icon': m.icon, 'portal': m.surface == 'portal',
                     'features': [f.label(lang) for f in m.features if access.has(f.key)]})
    homes = {'access.workspace': _('Restricted workspace (only the modules below)'),
             'dashboard': _('CMS dashboard'), 'portal.dashboard': _('Employee portal')}
    return jsonify({'mode': mode, 'home': homes.get(S.home_endpoint(access)), 'modules': mods,
                    'pages': len(pages), 'pages_total': len(R.ENDPOINT_FEATURE),
                    'unrestricted': access.unrestricted})


@bp.route('/admin/access/audit')
@_editor
def admin_audit():
    uid = request.args.get('user', type=int)
    lang = _lang()
    return render_template('access/audit.html', rows=S.history(uid, limit=500), user_filter=uid,
                           labels={k: f.label(lang) + ' · ' + f.module.label(lang) for k, f in R.FEATURES.items()})


# ------------------------------------------------------------------ workspace sign-in
@bp.route('/workspace/login')
def workspace_login():
    """The address given to external / restricted users: a clean sign-in page (it posts to the portal sign-in,
    which lands every restricted user on /workspace)."""
    from flask_login import current_user as cu
    if getattr(cu, 'is_authenticated', False):
        return redirect(url_for(S.home_endpoint(S.effective(cu))))
    return render_template('access/login.html')
