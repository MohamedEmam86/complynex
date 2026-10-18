# =============================================================================
# ComplyNex — organisational hierarchy and scope resolution
#
# Two questions are kept strictly separate:
#
#   perm_<module>  may this user see the Policies module at all?   (existing)
#   org scope      which policies, out of the ones the module holds? (this file)
#
# Both must pass. Nothing here can widen what the perm_* columns already allow,
# which is why the whole layer could be added without touching 98 is_admin()
# call sites or any existing permission check.
# =============================================================================
from flask import g
from flask_login import current_user

from database.db import get_db


# --------------------------------------------------------------------- tree
def get_unit(unit_id):
    return get_db().execute(
        "SELECT o.*, t.code AS type_code, t.name_en AS type_name "
        "FROM org_units o JOIN org_unit_types t ON t.id = o.unit_type_id "
        "WHERE o.id = %s", (unit_id,)).fetchone()


def get_tree(active_only=True):
    """Whole tree in path order, so a caller can render it by walking the list
    and indenting on `depth` — no recursion needed in the template."""
    q = ("SELECT o.*, t.code AS type_code, t.name_en AS type_name, t.icon AS type_icon, "
         "       (SELECT count(*) FROM users u WHERE u.org_unit_id = o.id) AS user_count "
         "FROM org_units o JOIN org_unit_types t ON t.id = o.unit_type_id ")
    if active_only:
        q += "WHERE o.is_active "
    q += "ORDER BY o.path"
    return [dict(r) for r in get_db().execute(q).fetchall()]


def get_unit_types(active_only=True):
    q = "SELECT * FROM org_unit_types "
    if active_only:
        q += "WHERE is_active "
    q += "ORDER BY rank_hint, name_en"
    return [dict(r) for r in get_db().execute(q).fetchall()]


def descendants(unit_id, include_self=True):
    row = get_db().execute("SELECT path FROM org_units WHERE id = %s", (unit_id,)).fetchone()
    if not row:
        return []
    path = dict(row)['path']
    op = '' if include_self else '_%'
    rows = get_db().execute(
        "SELECT id FROM org_units WHERE path LIKE %s", (path + '%' if include_self else path + '_%',)
    ).fetchall()
    return [dict(r)['id'] for r in rows]


# ------------------------------------------------------------------- scope
def resolve_scope(user_id=None, use_cache=True):
    """The set of org_unit ids a user may see.

    Returns None to mean "everything" — an admin, or a user whose rules cover
    the whole tree. None rather than a set of every id so callers can skip
    filtering entirely in the common case instead of building a huge IN list.
    """
    if user_id is None:
        user_id = getattr(current_user, 'id', None)
    if user_id is None:
        return set()

    if use_cache:
        cache = getattr(g, '_org_scope_cache', None)
        if cache is None:
            cache = g._org_scope_cache = {}
        if user_id in cache:
            return cache[user_id]

    db = get_db()

    # Admins bypass scoping, exactly as they bypass perm_* today. Keeping the
    # two consistent avoids an admin seeing a module but not its contents.
    row = db.execute("SELECT role FROM users WHERE id = %s", (user_id,)).fetchone()
    if row and (dict(row).get('role') or '') in ('admin', 'superadmin', 'it_admin'):
        result = None
        if use_cache:
            g._org_scope_cache[user_id] = result
        return result

    rules = [dict(r) for r in db.execute(
        "SELECT * FROM user_org_scope_rules WHERE user_id = %s", (user_id,)).fetchall()]

    allow, deny = set(), set()
    for r in rules:
        target = deny if r['is_exclusion'] else allow
        rt = r['rule_type']

        if rt == 'unit_only' and r['org_unit_id']:
            target.add(r['org_unit_id'])

        elif rt == 'subtree' and r['org_unit_id']:
            target.update(descendants(r['org_unit_id']))

        elif rt == 'by_code' and r['match_code']:
            # "every Compliance department across the group" — the case a
            # node-by-node grant cannot express without re-granting whenever a
            # new company is added.
            params = [r['match_code']]
            q = "SELECT id FROM org_units WHERE upper(code) = upper(%s)"
            if r['root_unit_id']:
                root = db.execute("SELECT path FROM org_units WHERE id = %s",
                                  (r['root_unit_id'],)).fetchone()
                if root:
                    q += " AND path LIKE %s"
                    params.append(dict(root)['path'] + '%')
            target.update(dict(x)['id'] for x in db.execute(q, tuple(params)).fetchall())

        elif rt == 'by_type' and r['match_type_id']:
            params = [r['match_type_id']]
            q = "SELECT id FROM org_units WHERE unit_type_id = %s"
            if r['root_unit_id']:
                root = db.execute("SELECT path FROM org_units WHERE id = %s",
                                  (r['root_unit_id'],)).fetchone()
                if root:
                    q += " AND path LIKE %s"
                    params.append(dict(root)['path'] + '%')
            target.update(dict(x)['id'] for x in db.execute(q, tuple(params)).fetchall())

    # Exclusions win. "The whole Group except Company C" must not be defeatable
    # by also holding a narrower grant that happens to include C.
    result = allow - deny

    # A user granted the entire tree is treated as unscoped, which keeps the
    # common case cheap.
    total = dict(db.execute("SELECT count(*) AS c FROM org_units WHERE is_active").fetchone())['c']
    if len(result) >= total and not deny:
        result = None

    if use_cache:
        g._org_scope_cache[user_id] = result
    return result


def scope_filter(column='org_unit_id', user_id=None, allow_null=True):
    """SQL fragment + params to constrain a query to the user's scope.

    allow_null keeps records that have not been assigned to a unit yet visible
    during the migration period. Set it False once a module has been fully
    migrated, otherwise unassigned rows leak across the whole organisation.
    """
    ids = resolve_scope(user_id)
    if ids is None:
        return '', ()
    if not ids:
        return f' AND 1=0 ', ()
    placeholders = ','.join(['%s'] * len(ids))
    if allow_null:
        return f' AND ({column} IN ({placeholders}) OR {column} IS NULL) ', tuple(ids)
    return f' AND {column} IN ({placeholders}) ', tuple(ids)


def can_see_unit(unit_id, user_id=None):
    ids = resolve_scope(user_id)
    return True if ids is None else unit_id in ids


def visible_units(user_id=None):
    """Tree filtered to what the user may see — for pickers and dropdowns."""
    ids = resolve_scope(user_id)
    tree = get_tree()
    if ids is None:
        return tree
    return [u for u in tree if u['id'] in ids]


def describe_scope(user_id):
    """Plain-language summary for the admin UI, so granting is auditable by
    reading rather than by reverse-engineering rows."""
    db = get_db()
    rules = [dict(r) for r in db.execute(
        "SELECT r.*, o.name_en AS unit_name, ro.name_en AS root_name, t.name_en AS type_name "
        "FROM user_org_scope_rules r "
        "LEFT JOIN org_units o  ON o.id  = r.org_unit_id "
        "LEFT JOIN org_units ro ON ro.id = r.root_unit_id "
        "LEFT JOIN org_unit_types t ON t.id = r.match_type_id "
        "WHERE r.user_id = %s ORDER BY r.is_exclusion, r.id", (user_id,)).fetchall()]
    out = []
    for r in rules:
        if r['rule_type'] == 'subtree':
            s = f"{r['unit_name']} and everything below it"
        elif r['rule_type'] == 'unit_only':
            s = f"{r['unit_name']} only"
        elif r['rule_type'] == 'by_code':
            s = f"every unit coded {r['match_code']}"
            if r['root_name']:
                s += f" within {r['root_name']}"
        else:
            s = f"every {r['type_name']}"
            if r['root_name']:
                s += f" within {r['root_name']}"
        out.append(('Except: ' if r['is_exclusion'] else '') + s)
    return out


# ============================================================================
# Authority level — set directly on the user record
#
# The rule engine below is expressive enough for anything, but expressing
# "this person is a Company-level user" as a hand-built rule set every time is
# how mistakes get made. So the common shapes are named, stored on the user,
# and translated into rules on save. `custom` is the escape hatch: it leaves
# whatever rules were built on the advanced screen alone.
# ============================================================================

AUTHORITY_LEVELS = {
    'group': {
        'label': 'Group level',
        'help': 'Sees every company and every department in the group.',
        'needs_unit': False,
    },
    'company': {
        'label': 'Company level',
        'help': 'Sees one company and everything inside it. Other companies are invisible.',
        'needs_unit': True,
    },
    'department': {
        'label': 'Department level',
        'help': 'Sees one department only.',
        'needs_unit': True,
    },
    'function': {
        'label': 'Function across the group',
        'help': 'Sees their own function in every company — e.g. all Compliance departments.',
        'needs_unit': True,
    },
    'explicit': {
        'label': 'Chosen unit by unit',
        'help': 'Exactly the units listed under “Can see”. Nothing else.',
        'needs_unit': False,
    },
    'custom': {
        'label': 'Custom',
        'help': 'Built by hand on the visibility screen. Saving the user will not overwrite it.',
        'needs_unit': False,
    },
    'none': {
        'label': 'No access',
        'help': 'Sees no scoped records at all.',
        'needs_unit': False,
    },
}


def root_unit_id():
    r = get_db().execute("SELECT id FROM org_units WHERE parent_id IS NULL "
                         "ORDER BY id LIMIT 1").fetchone()
    return dict(r)['id'] if r else None


def apply_authority(user_id, level, unit_id=None, exclusions=None, granted_by=None):
    """Write the user's level and rebuild their scope rules to match.

    'custom' deliberately does not touch the rules — otherwise editing an
    unrelated field on the user form would silently destroy a carefully built
    combination.
    """
    db = get_db()
    level = level if level in AUTHORITY_LEVELS else 'group'
    unit_id = int(unit_id) if unit_id else None

    db.execute("UPDATE users SET authority_level=%s, authority_unit_id=%s WHERE id=%s",
               (level, unit_id, user_id))

    if level == 'custom':
        db.commit()
        return 'custom', 'Custom visibility left unchanged.'

    db.execute("DELETE FROM user_org_scope_rules WHERE user_id=%s", (user_id,))

    if level == 'none':
        db.commit()
        return 'none', 'This user will see no scoped records.'

    if level == 'group':
        rid = root_unit_id()
        if rid:
            db.execute("""INSERT INTO user_org_scope_rules
                            (user_id, rule_type, org_unit_id, granted_by)
                          VALUES (%s,'subtree',%s,%s)""", (user_id, rid, granted_by))

    elif level in ('company', 'department'):
        if not unit_id:
            db.commit()
            return level, 'No unit was selected, so this user currently sees nothing.'
        rtype = 'subtree' if level == 'company' else 'unit_only'
        db.execute("""INSERT INTO user_org_scope_rules
                        (user_id, rule_type, org_unit_id, granted_by)
                      VALUES (%s,%s,%s,%s)""", (user_id, rtype, unit_id, granted_by))

    elif level == 'function':
        if not unit_id:
            db.commit()
            return level, 'No unit was selected, so this user currently sees nothing.'
        u = db.execute("SELECT code FROM org_units WHERE id=%s", (unit_id,)).fetchone()
        if u:
            db.execute("""INSERT INTO user_org_scope_rules
                            (user_id, rule_type, match_code, root_unit_id, granted_by)
                          VALUES (%s,'by_code',%s,%s,%s)""",
                       (user_id, dict(u)['code'], root_unit_id(), granted_by))

    # Exclusions apply on top of any level and always win.
    for ex in (exclusions or []):
        if ex:
            db.execute("""INSERT INTO user_org_scope_rules
                            (user_id, rule_type, org_unit_id, is_exclusion, granted_by)
                          VALUES (%s,'subtree',%s,TRUE,%s)""", (user_id, int(ex), granted_by))

    db.commit()
    return level, f'Authority set to {AUTHORITY_LEVELS[level]["label"]}.'


def visibility_summary(user_id):
    """What this user can and cannot see, in plain language and by name.

    Both halves are shown deliberately: an administrator granting access should
    be able to read back the exclusions, not infer them.
    """
    db = get_db()
    u = db.execute("SELECT authority_level, authority_unit_id, role FROM users WHERE id=%s",
                   (user_id,)).fetchone()
    if not u:
        return None
    u = dict(u)
    level = u.get('authority_level') or 'group'

    all_units = get_tree(active_only=True)
    if (u.get('role') or '') in ('admin', 'superadmin', 'it_admin'):
        return {'level': level, 'level_label': 'Administrator',
                'can_see': all_units, 'cannot_see': [],
                'note': 'Administrators bypass scoping entirely.'}

    visible = resolve_scope(user_id, use_cache=False)
    if visible is None:
        can = all_units
        cannot = []
    else:
        can = [x for x in all_units if x['id'] in visible]
        cannot = [x for x in all_units if x['id'] not in visible]

    return {
        'level': level,
        'level_label': AUTHORITY_LEVELS.get(level, {}).get('label', level),
        'can_see': can,
        'cannot_see': cannot,
        'note': AUTHORITY_LEVELS.get(level, {}).get('help', ''),
    }


def apply_explicit_scope(user_id, visible_unit_ids, granted_by=None):
    """Set visibility from an explicit list of units.

    This is what the two-box picker saves. It writes one unit_only rule per
    chosen unit rather than a subtree rule, because the whole point of picking
    unit by unit is that adding a new child unit later must NOT silently widen
    what this person can see. A subtree rule would do exactly that.
    """
    db = get_db()
    ids = sorted({int(x) for x in (visible_unit_ids or []) if str(x).strip()})

    db.execute("DELETE FROM user_org_scope_rules WHERE user_id=%s", (user_id,))
    for uid in ids:
        db.execute("""INSERT INTO user_org_scope_rules
                        (user_id, rule_type, org_unit_id, granted_by)
                      VALUES (%s,'unit_only',%s,%s)""", (user_id, uid, granted_by))

    total = dict(db.execute("SELECT count(*) AS c FROM org_units WHERE is_active").fetchone())['c']
    level = 'group' if len(ids) >= total else ('none' if not ids else 'explicit')
    db.execute("UPDATE users SET authority_level=%s, authority_unit_id=NULL WHERE id=%s",
               (level, user_id))
    db.commit()

    hidden = total - len(ids)
    return level, (f'Saved. This user can see {len(ids)} unit(s) and cannot see {hidden}.')


def can_cannot_lists(user_id):
    """The two sides of the picker, both fully populated.

    Returns every active unit split into what the user can and cannot see, so
    the form shows the complete picture rather than only the granted half.
    """
    all_units = get_tree(active_only=True)
    visible = resolve_scope(user_id, use_cache=False)
    if visible is None:
        return all_units, []
    return ([u for u in all_units if u['id'] in visible],
            [u for u in all_units if u['id'] not in visible])
