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

"""Configurable governance lists, edited in the UI by users who can edit
governance (POST + CSRF, every change written to the audit log):
committee types, capacity dimensions and options (صفة العضو), meeting rules
(quorum / majority / filing), resolution categories, search synonyms,
composition rule sets, boards (entities) and officers who are not board members
(secretary, vote tellers ...).

One spec per list drives the generic page `governance/config_list.html`.
A row that is referenced elsewhere is deactivated instead of deleted; rows
shipped with the system (is_system) can be renamed and deactivated, not deleted.
"""
import re
from decimal import Decimal, InvalidOperation

from flask import render_template, request, redirect, url_for, flash, abort
from flask_babel import gettext as _, lazy_gettext as _l
from flask_login import login_required, current_user

from database.db import get_db
from models.audit import AuditLog
from utils.decorators import permission_required
from governance.routes import governance_bp

CODE_RE = re.compile(r'^[A-Z0-9_]{2,40}$')

CAPACITY_FLAGS = ['', 'chair', 'vice_chair', 'md', 'chair_md', 'ceo', 'member', 'executive', 'non_executive',
                  'independent', 'non_independent', 'self', 'legal_person', 'shareholder_block', 'employees',
                  'public_funds', 'elected', 'appointed', 'co_opted', 'alternate', 'expert', 'secretary', 'teller',
                  'gm', 'external_member', 'observer', 'auditor']


def _rules_choices():
    return [('', '—')] + [(r['code'], r['name_en']) for r in get_db().execute(
        "SELECT code, name_en FROM gov_meeting_rules WHERE is_active ORDER BY sort_order, id").fetchall()]


def _dimension_choices():
    return [(str(r['id']), r['name_en'] + (' / ' + r['name_ar'] if r['name_ar'] else '')) for r in get_db().execute(
        "SELECT id, name_en, name_ar FROM gov_capacity_dimensions ORDER BY sort_order, id").fetchall()]


def _non_member_role_choices():
    return [('', '—')] + [(str(r['id']), r['name_en'] + (' / ' + r['name_ar'] if r['name_ar'] else ''))
                          for r in get_db().execute(
        """SELECT o.id, o.name_en, o.name_ar FROM gov_capacity_options o JOIN gov_capacity_dimensions d
           ON d.id = o.dimension_id WHERE d.applies_to = 'NON_MEMBER' AND o.is_active ORDER BY o.sort_order, o.id""").fetchall()]


def _entity_choices():
    return [('', '—')] + [(str(r['id']), r['name_en'] + (' / ' + r['name_ar'] if r['name_ar'] else ''))
                          for r in get_db().execute(
        "SELECT id, name_en, name_ar FROM gov_entities WHERE is_active ORDER BY sort_order, id").fetchall()]


def _composition_choices():
    return [(r['code'], r['name_en']) for r in get_db().execute(
        "SELECT code, name_en FROM gov_composition_rules WHERE is_active ORDER BY sort_order, id").fetchall()]


_DEFAULT_ON = ('is_active', 'count_proxies', 'count_remote', 'chair_casting_vote', 'circulation_requires_all', 'is_voting')


def F(name, label, kind='text', required=False, choices=None, help=None, readonly_on_edit=False, width=3, default=None):
    if default is None and kind == 'bool':
        default = name in _DEFAULT_ON
    return dict(name=name, label=label, kind=kind, required=required, choices=choices, help=help,
                readonly_on_edit=readonly_on_edit, width=width, default=default)


SCOPE_CHOICES = [('ANY', _l('Any body')), ('BOARD', _l('Board')), ('COMMITTEE', _l('Committee')),
                 ('OGM', _l('Ordinary general assembly')), ('EGM', _l('Extraordinary general assembly'))]
QTYPE_CHOICES = [('MAJORITY', _l('More than the fraction')), ('AT_LEAST', _l('The fraction or more'))]
QTYPE_CHOICES_BLANK = [('', _l('Same as the first call'))] + QTYPE_CHOICES
MAJORITY_CHOICES = [('SIMPLE_PRESENT', _l('More than half of the members present')),
                    ('SIMPLE_CAST', _l('More votes for than against')),
                    ('TWO_THIRDS', _l('Two thirds of the members present')),
                    ('THREE_QUARTERS', _l('Three quarters of the members present')),
                    ('UNANIMOUS', _l('Unanimous'))]

LISTS = {
    'committee-types': dict(
        table='gov_committee_types', title=_l('Committee types'), order='sort_order, id', label='name_en',
        intro=_l('Any committee name can be used. Each type carries default composition rules that a new committee '
                 'of that type starts with; each committee can then change them.'),
        fields=[F('code', _l('Code'), 'code', True, readonly_on_edit=True, width=2), F('name_en', _l('Name (English)'), required=True),
                F('name_ar', _l('Name (Arabic)'), 'text_ar'), F('res_prefix', _l('Resolution prefix'), width=2),
                F('min_members', _l('Min members'), 'int', width=2), F('max_members', _l('Max members'), 'int', width=2),
                F('min_independent_members', _l('Min independent members'), 'int', width=2),
                F('independent_majority', _l('Independent majority'), 'bool', width=2),
                F('independent_chair', _l('Independent chair'), 'bool', width=2),
                F('non_executive_chair', _l('Non-executive chair'), 'bool', width=2),
                F('requires_financial_expert', _l('Financial expert'), 'bool', width=2),
                F('min_meetings_per_year', _l('Meetings per year'), 'int', width=2),
                F('meeting_rule_code', _l('Quorum / majority rule'), 'select', choices=_rules_choices),
                F('sort_order', _l('Order'), 'int', width=1), F('is_active', _l('Active'), 'bool', width=1)],
        usage="SELECT COUNT(*) AS n FROM board_committees WHERE UPPER(committee_type) = (SELECT code FROM gov_committee_types WHERE id = %s)"),
    'capacity-dimensions': dict(
        table='gov_capacity_dimensions', title=_l('Capacity dimensions'), order='sort_order, id', label='name_en',
        intro=_l('A member\'s capacity (صفة العضو) is recorded along separate dimensions: board role, executive status, '
                 'independence, whom the member represents, how the seat was filled, plus any additional capacities. '
                 'Add dimensions or options freely.'),
        fields=[F('code', _l('Code'), 'code', True, readonly_on_edit=True), F('name_en', _l('Name (English)'), required=True),
                F('name_ar', _l('Name (Arabic)'), 'text_ar'),
                F('multi_select', _l('Several at once'), 'bool', width=2),
                F('applies_to', _l('Applies to'), 'select', choices=[('MEMBER', _l('Board members')),
                                                                    ('NON_MEMBER', _l('Non-members'))], width=2),
                F('sort_order', _l('Order'), 'int', width=1), F('is_active', _l('Active'), 'bool', width=1)],
        usage="SELECT COUNT(*) AS n FROM gov_capacity_options WHERE dimension_id = %s"),
    'capacity-options': dict(
        table='gov_capacity_options', title=_l('Capacities'), order='dimension_id, sort_order, id', label='name_en',
        intro=_l('Each capacity belongs to a dimension. The meaning flag tells the checks what the capacity counts as '
                 '(e.g. a capacity flagged "independent" counts towards the independent ratio).'),
        fields=[F('dimension_id', _l('Dimension'), 'select_int', True, choices=_dimension_choices),
                F('code', _l('Code'), 'code', True, readonly_on_edit=True, width=2), F('name_en', _l('Name (English)'), required=True),
                F('name_ar', _l('Name (Arabic)'), 'text_ar'),
                F('flag', _l('Counts as'), 'select', choices=lambda: [(f, f.replace('_', ' ') or '—') for f in CAPACITY_FLAGS], width=2),
                F('is_voting', _l('Votes'), 'bool', width=1),
                F('sort_order', _l('Order'), 'int', width=1), F('is_active', _l('Active'), 'bool', width=1)],
        usage="""SELECT (SELECT COUNT(*) FROM gov_member_capacities WHERE option_id = %s)
                      + (SELECT COUNT(*) FROM gov_officers WHERE role_option_id = %s) AS n""", usage_args=2),
    'meeting-rules': dict(
        table='gov_meeting_rules', title=_l('Quorum, majority and filing rules'), order='sort_order, id', label='name_en',
        intro=_l('Each meeting uses one rule: the quorum (share of members, or of capital for a general assembly, with '
                 'a minimum head count and an optional second-call threshold), how a resolution passes, whether the '
                 'chair has a casting vote, and the filing deadline after the meeting. Set them to match the articles of '
                 'association and the regulator.'),
        fields=[F('code', _l('Code'), 'code', True, readonly_on_edit=True, width=2), F('name_en', _l('Name (English)'), required=True, width=4),
                F('name_ar', _l('Name (Arabic)'), 'text_ar', width=4),
                F('applies_to', _l('Body'), 'select', choices=SCOPE_CHOICES, width=2),
                F('quorum_basis', _l('Quorum basis'), 'select', choices=[('MEMBERS', _l('Members')), ('CAPITAL', _l('Capital represented'))], width=2),
                F('quorum_type', _l('Quorum'), 'select', choices=QTYPE_CHOICES, width=2),
                F('quorum_fraction', _l('Fraction (0-1)'), 'fraction', True, width=2),
                F('quorum_min', _l('Minimum present'), 'int', width=2),
                F('second_call_type', _l('Second call'), 'select', choices=QTYPE_CHOICES_BLANK, width=2),
                F('second_call_fraction', _l('Second-call fraction'), 'fraction', width=2),
                F('second_call_min', _l('Second-call minimum'), 'int', width=2),
                F('count_proxies', _l('Proxies count'), 'bool', width=1), F('count_remote', _l('Remote counts'), 'bool', width=1),
                F('min_personal', _l('Minimum present in person or remotely'), 'int', width=2),
                F('majority_rule', _l('Majority'), 'select', choices=MAJORITY_CHOICES),
                F('chair_casting_vote', _l('Chair casting vote'), 'bool', width=2),
                F('circulation_requires_all', _l('Circulation: all must vote'), 'bool', width=2),
                F('notice_days', _l('Notice days'), 'int', width=2), F('filing_days', _l('Filing days'), 'int', width=2),
                F('filing_authority', _l('Filed with'), width=2), F('legal_ref', _l('Legal reference'), width=6),
                F('sort_order', _l('Order'), 'int', width=1), F('is_active', _l('Active'), 'bool', width=1)],
        usage="""SELECT (SELECT COUNT(*) FROM board_meetings WHERE meeting_rule_id = %s OR rule_snapshot->>'id' = %s::text)
                      + (SELECT COUNT(*) FROM board_committees WHERE meeting_rule_id = %s) AS n""", usage_args=3,
        # once meetings use a rule, the values that decide quorum and majority are kept: make a new rule instead
        frozen_when_used=('applies_to', 'quorum_basis', 'quorum_type', 'quorum_fraction', 'quorum_min', 'min_personal',
                          'second_call_type', 'second_call_fraction', 'second_call_min', 'count_proxies', 'count_remote',
                          'majority_rule', 'chair_casting_vote', 'circulation_requires_all')),
    'resolution-categories': dict(
        table='gov_resolution_categories', title=_l('Resolution categories'), order='sort_order, id', label='name_en',
        intro=_l('Categories group resolutions in the register and the search filters.'),
        fields=[F('code', _l('Code'), 'code', True, readonly_on_edit=True), F('name_en', _l('Name (English)'), required=True),
                F('name_ar', _l('Name (Arabic)'), 'text_ar'),
                F('sort_order', _l('Order'), 'int', width=1), F('is_active', _l('Active'), 'bool', width=1)],
        usage="SELECT COUNT(*) AS n FROM board_decisions WHERE category_code = (SELECT code FROM gov_resolution_categories WHERE id = %s)"),
    'synonyms': dict(
        table='gov_search_synonyms', title=_l('Search synonyms'), order='group_code, id', label='term',
        intro=_l('Words or phrases in the same group are treated as the same thing by the resolutions search, in either '
                 'language (e.g. اعتماد / موافقة / approve). Add a term to an existing group code or start a new group.'),
        fields=[F('group_code', _l('Group'), 'code', True), F('term', _l('Word or phrase'), required=True, width=5),
                F('is_active', _l('Active'), 'bool', width=1)],
        usage=None),
    'composition-rules': dict(
        table='gov_composition_rules', title=_l('Board composition rule sets'), order='sort_order, id', label='name_en',
        intro=_l('Each board applies one or more rule sets (chosen on the board). An empty value is not checked. '
                 'Shares are percentages.'),
        fields=[F('code', _l('Code'), 'code', True, readonly_on_edit=True, width=2), F('name_en', _l('Name (English)'), required=True, width=4),
                F('name_ar', _l('Name (Arabic)'), 'text_ar', width=4),
                F('min_board_size', _l('Min board size'), 'int', width=2), F('max_board_size', _l('Max board size'), 'int', width=2),
                F('non_exec_majority', _l('Non-executive majority'), 'bool', width=2),
                F('min_indep_share_of_non_exec', _l('Independent share of non-executives'), 'pct', width=2),
                F('min_indep_share_of_board', _l('Independent share of the board'), 'pct', width=2),
                F('min_independent_count', _l('Min independent members'), 'int', width=2),
                F('min_executives', _l('Min executives'), 'int', width=2), F('max_executives', _l('Max executives'), 'int', width=2),
                F('min_women_share', _l('Women share'), 'pct', width=2), F('min_women_count', _l('Min women'), 'int', width=2),
                F('chair_ceo_separate', _l('Chair and CEO separate'), 'bool', width=2),
                F('independence_max_years', _l('Independence lapses after (years)'), 'int', width=2),
                F('max_absence_pct', _l('Max absence share of meetings'), 'pct', width=2),
                F('max_missed_meetings', _l('Max missed meetings a year'), 'int', width=2),
                F('min_board_meetings_per_year', _l('Board meetings per year'), 'int', width=2),
                F('legal_ref', _l('Legal reference'), width=6),
                F('sort_order', _l('Order'), 'int', width=1), F('is_active', _l('Active'), 'bool', width=1)],
        usage="SELECT COUNT(*) AS n FROM gov_entities WHERE ',' || COALESCE(rule_codes, '') || ',' LIKE '%%,' || (SELECT code FROM gov_composition_rules WHERE id = %s) || ',%%'"),
    'entities': dict(
        table='gov_entities', title=_l('Boards (companies)'), order='sort_order, id', label='name_en',
        intro=_l('Each company whose board is managed here. Records created before boards existed belong to the default '
                 'one. The short code is put in front of its resolution numbers.'),
        fields=[F('name_en', _l('Name (English)'), required=True, width=4), F('name_ar', _l('Name (Arabic)'), 'text_ar', width=4),
                F('short_code', _l('Short code'), width=2), F('legal_form', _l('Legal form'), width=2),
                F('rule_codes', _l('Composition rule sets'), 'multi', choices=_composition_choices, width=6),
                F('notes', _l('Notes'), width=4),
                F('sort_order', _l('Order'), 'int', width=1), F('is_active', _l('Active'), 'bool', width=1)],
        usage="""SELECT (SELECT COUNT(*) FROM board_members WHERE entity_id = %s)
                      + (SELECT COUNT(*) FROM board_meetings WHERE entity_id = %s)
                      + (SELECT COUNT(*) FROM board_committees WHERE entity_id = %s)
                      + (SELECT COUNT(*) FROM gov_entities WHERE id = %s AND is_default) AS n""", usage_args=4),
    'officers': dict(
        table='gov_officers', title=_l('Secretaries, tellers and other officers'), order='is_active DESC, full_name', label='full_name',
        intro=_l('People who take part in meetings without being board members: the board secretary (أمين السر), vote '
                 'tellers (فارزو الأصوات), the general manager, the external auditor, observers.'),
        fields=[F('full_name', _l('Full name'), required=True, width=3), F('full_name_ar', _l('Name (Arabic)'), 'text_ar', width=3),
                F('role_option_id', _l('Role'), 'select_int', choices=_non_member_role_choices, width=2),
                F('entity_id', _l('Board'), 'select_int', choices=_entity_choices, width=2),
                F('email', _l('Email'), width=2), F('notes', _l('Notes'), width=4),
                F('is_active', _l('Active'), 'bool', width=1)],
        usage="""SELECT (SELECT COUNT(*) FROM board_meetings WHERE secretary_officer_id = %s)
                      + (SELECT COUNT(*) FROM gov_meeting_officers WHERE officer_id = %s) AS n""", usage_args=2),
}


def _choices(field):
    c = field.get('choices')
    return [(str(k), str(v)) for k, v in (c() if callable(c) else (c or []))]


def parse_value(field, raw, multi_raw=None):
    """(value, error) for one submitted field."""
    kind = field['kind']
    if kind == 'bool':
        return (raw in ('1', 'on', 'true', 'yes')), None
    if kind == 'multi':
        vals = [v for v in (multi_raw or []) if v]
        return (','.join(vals) or None), None
    raw = (raw or '').strip()
    if raw == '':
        return None, (_('%(f)s is required.', f=field['label']) if field['required'] else None)
    if kind == 'code':
        v = re.sub(r'[\s\-]+', '_', raw.upper())
        if not CODE_RE.match(v):
            return None, _('%(f)s: use 2-40 letters, digits or underscores.', f=field['label'])
        return v, None
    if kind in ('int', 'select_int'):
        try:
            v = int(raw)
        except ValueError:
            return None, _('%(f)s must be a whole number.', f=field['label'])
        if kind == 'int' and v < 0:
            return None, _('%(f)s cannot be negative.', f=field['label'])
        if kind == 'select_int' and str(v) not in {k for k, _v in _choices(field)}:
            return None, _('%(f)s: choose a value from the list.', f=field['label'])
        return v, None
    if kind in ('fraction', 'pct'):
        try:
            v = Decimal(raw.replace(',', '.').rstrip('%'))
        except InvalidOperation:
            return None, _('%(f)s must be a number.', f=field['label'])
        hi = Decimal(1) if kind == 'fraction' else Decimal(100)
        if v < 0 or v > hi:
            return None, _('%(f)s must be between 0 and %(hi)s.', f=field['label'], hi=hi)
        return v, None
    if kind == 'select':
        allowed = {k for k, _v in _choices(field)}
        if raw not in allowed:
            return None, _('%(f)s: choose a value from the list.', f=field['label'])
        return raw, None
    return raw[:2000], None


def _spec(name):
    spec = LISTS.get(name)
    if not spec:
        abort(404)
    return spec


def _audit(action, rid, details):
    try:
        AuditLog.log(current_user.id, action, 'Governance', rid, details, request.remote_addr)
    except Exception:
        pass


def _entity_errors(db, spec, data, rid, row):
    """A board other than the default one needs a short code (it starts its resolution numbers); codes are unique."""
    if spec['table'] != 'gov_entities':
        return []
    code = (data.get('short_code') or '').strip().upper()
    if not code:
        return [] if row.get('is_default') else [_('A board other than the default one needs a short code.')]
    data['short_code'] = code
    if db.execute("SELECT 1 FROM gov_entities WHERE UPPER(short_code) = %s AND id <> %s", (code, rid or 0)).fetchone():
        return [_('The code %(c)s is already used.', c=code)]
    return []


def usage_count(db, spec, rid):
    if not spec.get('usage'):
        return 0
    row = db.execute(spec['usage'], (rid,) * spec.get('usage_args', 1)).fetchone()
    return int(row['n'] or 0) if row else 0


@governance_bp.route('/settings')
@login_required
@permission_required('governance')
def gov_settings():
    db = get_db()
    counts = {}
    for key, spec in LISTS.items():
        counts[key] = db.execute(f"SELECT COUNT(*) AS n FROM {spec['table']}").fetchone()['n']
    return render_template('governance/gov_settings.html', lists=LISTS, counts=counts)


@governance_bp.route('/settings/<name>')
@login_required
@permission_required('governance')
def gov_config_list(name):
    spec = _spec(name)
    db = get_db()
    rows = [dict(r) for r in db.execute(f"SELECT * FROM {spec['table']} ORDER BY {spec['order']}").fetchall()]
    choices = {f['name']: _choices(f) for f in spec['fields'] if f.get('choices')}
    return render_template('governance/config_list.html', name=name, spec=spec, rows=rows, choices=choices,
                           can_edit=current_user.can_edit('governance') or current_user.is_admin())


def _collect(spec, editing=False, row=None):
    data, errors = {}, []
    for f in spec['fields']:
        if editing and f.get('readonly_on_edit'):
            continue
        v, err = parse_value(f, request.form.get(f['name']), request.form.getlist(f['name']))
        if err:
            errors.append(err)
        data[f['name']] = v
    return data, errors


@governance_bp.route('/settings/<name>/add', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def gov_config_add(name):
    spec = _spec(name)
    db = get_db()
    data, errors = _collect(spec)
    if 'code' in data and data.get('code') and spec['table'] != 'gov_search_synonyms':
        extra = ''
        args = [data['code']]
        if spec['table'] == 'gov_capacity_options':
            extra, args = ' AND dimension_id = %s', [data['code'], data.get('dimension_id')]
        if db.execute(f"SELECT 1 FROM {spec['table']} WHERE code = %s{extra}", tuple(args)).fetchone():
            errors.append(_('The code %(c)s is already used.', c=data['code']))
    if spec['table'] == 'gov_search_synonyms' and data.get('term') and data.get('group_code'):
        if db.execute("SELECT 1 FROM gov_search_synonyms WHERE group_code = %s AND term = %s",
                      (data['group_code'], data['term'])).fetchone():
            errors.append(_('This term is already in the group.'))
    errors += _entity_errors(db, spec, data, None, {})
    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(url_for('governance.gov_config_list', name=name))
    cols = list(data.keys())
    rid = db.execute(f"INSERT INTO {spec['table']} ({', '.join(cols)}, created_by) VALUES "
                     f"({', '.join(['%s'] * len(cols))}, %s) RETURNING id",
                     tuple(data[c] for c in cols) + (current_user.id,)).fetchone()['id']
    db.commit()
    _audit('Governance Setting Added', rid, f"{spec['table']}: {data.get(spec['label'])}")
    flash(_('Added.'), 'success')
    return redirect(url_for('governance.gov_config_list', name=name))


@governance_bp.route('/settings/<name>/<int:rid>/update', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def gov_config_update(name, rid):
    spec = _spec(name)
    db = get_db()
    row = db.execute(f"SELECT * FROM {spec['table']} WHERE id = %s", (rid,)).fetchone()
    if not row:
        abort(404)
    data, errors = _collect(spec, editing=True, row=row)
    if spec['table'] == 'gov_entities' and row.get('is_default') and data.get('is_active') is False:
        errors.append(_('The default board cannot be deactivated.'))
    errors += _entity_errors(db, spec, data, rid, row)
    frozen = spec.get('frozen_when_used')
    if frozen and usage_count(db, spec, rid):
        changed = [c for c in frozen if c in data and str(row.get(c)) != str(data[c])
                   and not (row.get(c) in (None, '') and data[c] in (None, ''))]
        for c in frozen:
            data.pop(c, None)
        if changed:
            flash(_('Meetings already use this rule, so its quorum and majority values were kept; '
                    'add a new rule for different values.'), 'warning')
    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(url_for('governance.gov_config_list', name=name))
    has_updated = spec['table'] != 'gov_search_synonyms'
    sets = ', '.join(f'{c} = %s' for c in data) + (', updated_at = NOW(), updated_by = %s' if has_updated else '')
    args = tuple(data.values()) + ((current_user.id,) if has_updated else ()) + (rid,)
    db.execute(f"UPDATE {spec['table']} SET {sets} WHERE id = %s", args)
    db.commit()
    changed = [c for c in data if str(row.get(c)) != str(data[c])]
    _audit('Governance Setting Changed', rid, f"{spec['table']} #{rid}: {', '.join(changed) or 'no change'}")
    flash(_('Saved.'), 'success')
    return redirect(url_for('governance.gov_config_list', name=name))


@governance_bp.route('/settings/<name>/<int:rid>/delete', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def gov_config_delete(name, rid):
    spec = _spec(name)
    db = get_db()
    row = db.execute(f"SELECT * FROM {spec['table']} WHERE id = %s", (rid,)).fetchone()
    if not row:
        abort(404)
    if spec['table'] == 'gov_entities' and row.get('is_default'):
        flash(_('The default board cannot be removed or deactivated.'), 'danger')
        return redirect(url_for('governance.gov_config_list', name=name))
    used = usage_count(db, spec, rid)
    label = row.get(spec['label'])
    if used or row.get('is_system'):
        if 'is_active' in row:
            db.execute(f"UPDATE {spec['table']} SET is_active = FALSE WHERE id = %s", (rid,))
            db.commit()
            _audit('Governance Setting Deactivated', rid, f"{spec['table']}: {label} (in use: {used})")
            flash(_('It is in use (or part of the system), so it was deactivated instead of deleted.'), 'warning')
        else:
            flash(_('It is in use and cannot be removed.'), 'danger')
        return redirect(url_for('governance.gov_config_list', name=name))
    db.execute(f"DELETE FROM {spec['table']} WHERE id = %s", (rid,))
    db.commit()
    _audit('Governance Setting Removed', rid, f"{spec['table']}: {label}")
    flash(_('Removed.'), 'info')
    return redirect(url_for('governance.gov_config_list', name=name))
