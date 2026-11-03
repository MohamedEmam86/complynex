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
Transaction-monitoring rule versions (Phase 7, TM-G4).

Every change to a rule is a new row in tm_rules (same rule_code, version + 1,
previous_id = the version it replaces) carrying who proposed it and why. It
does nothing until a DIFFERENT person approves it (four eyes); approval
retires every other active version of that code, so exactly one version is in
force. Alerts record the version that raised them (tm_alerts.rule_id points at
that row, rule_version / rule_code copy it). Rollback re-activates the previous
version, with a written reason.
"""
import json

from aml import tm_engine as E


def N_(s):
    return s


class VersionError(ValueError):
    pass


MIN_REASON = 10
FIELDS = ('rule_name', 'rule_name_ar', 'rule_description', 'rule_category', 'rule_type', 'threshold_value',
          'threshold_currency', 'time_period_days', 'severity', 'reference', 'threshold_unit')


def active_rules(db):
    """The version in force of each rule code (newest active one when data is inconsistent)."""
    rows = db.execute("""SELECT DISTINCT ON (rule_code) * FROM tm_rules
                         WHERE is_active = 1 AND COALESCE(status, 'ACTIVE') = 'ACTIVE'
                         ORDER BY rule_code, version DESC NULLS LAST, id DESC""").fetchall()
    return [dict(r) for r in rows]


def _get(db, rule_id):
    row = db.execute("SELECT * FROM tm_rules WHERE id = %s", (rule_id,)).fetchone()
    if not row:
        raise VersionError(N_('Rule not found.'))
    return dict(row)


def _reason(reason):
    reason = (reason or '').strip()
    if len(reason) < MIN_REASON:
        raise VersionError(N_('Write the reason for the change (at least 10 characters).'))
    return reason


def clean_parameters(code, raw):
    """Keep only the extra parameters the rule defines, typed as the spec says."""
    spec = E.RULE_SPECS.get(code, {}).get('params', {})
    out = {}
    for k, v in (raw or {}).items():
        d = spec.get(k)
        if not d or k in ('threshold', 'days') or v in (None, ''):
            continue
        unit = d['unit']
        try:
            if unit == 'types':
                out[k] = [x.strip().upper() if k.endswith('_types') else x.strip()
                          for x in (v if isinstance(v, list) else str(v).split(',')) if str(x).strip()]
            elif unit == 'bool':
                out[k] = str(v).lower() in ('1', 'true', 'yes', 'on')
            elif unit in ('count', 'days'):
                out[k] = int(float(v))
            else:
                out[k] = float(v)
        except (TypeError, ValueError):
            raise VersionError(N_('A rule parameter has an invalid value.'))
        if unit in ('count', 'amount', 'ratio', 'hours', 'minutes', 'percent') and out[k] < 0:
            raise VersionError(N_('A rule parameter has an invalid value.'))
    return out


def propose(db, base_id, values, parameters, reason, user_id, code=None):
    """New pending version of an existing rule (base_id) or a brand-new rule (base_id None, code given)."""
    reason = _reason(reason)
    if base_id:
        base = _get(db, base_id)
        code = base['rule_code']
        latest = db.execute("SELECT MAX(version) AS v FROM tm_rules WHERE rule_code = %s", (code,)).fetchone()['v'] or 0
        version, previous = latest + 1, base_id
        if db.execute("SELECT 1 FROM tm_rules WHERE rule_code = %s AND status = 'PENDING'", (code,)).fetchone():
            raise VersionError(N_('This rule already has a version waiting for approval; approve or reject it first.'))
    else:
        code = (code or '').strip().upper()
        if not code:
            raise VersionError(N_('Rule code is required.'))
        if db.execute("SELECT 1 FROM tm_rules WHERE rule_code = %s", (code,)).fetchone():
            raise VersionError(N_('This rule code already exists; edit it to make a new version.'))
        version, previous, base = 1, None, {}
    row = {f: values.get(f, base.get(f)) for f in FIELDS}
    params = clean_parameters(code, parameters if parameters is not None else _json(base.get('parameters')))
    new_id = db.execute("""
        INSERT INTO tm_rules (rule_code, rule_name, rule_name_ar, rule_description, rule_category, rule_type,
                              threshold_value, threshold_currency, time_period_days, severity, reference,
                              threshold_unit, parameters, pack_code, change_reason, is_active, status,
                              created_by, created_at, version, previous_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,'PENDING',%s,NOW(),%s,%s) RETURNING id""",
        (code, row['rule_name'], row['rule_name_ar'], row['rule_description'], row['rule_category'],
         row['rule_type'], row['threshold_value'], row['threshold_currency'], row['time_period_days'],
         row['severity'], row['reference'], row['threshold_unit'], json.dumps(params),
         base.get('pack_code'), reason, user_id, version, previous)).fetchone()['id']
    db.commit()
    return new_id


def _json(v):
    if isinstance(v, dict):
        return v
    try:
        return json.loads(v or '{}')
    except (TypeError, ValueError):
        return {}


def approve(db, rule_id, user_id, can_self_approve=False):
    """Put a pending version in force. Four eyes: not by the person who proposed it."""
    rule = _get(db, rule_id)
    if rule.get('status') != 'PENDING':
        raise VersionError(N_('Only a version waiting for approval can be approved.'))
    if rule.get('created_by') and int(rule['created_by']) == int(user_id) and not can_self_approve:
        raise VersionError(N_('Another person must approve a rule change (four eyes).'))
    db.execute("""UPDATE tm_rules SET is_active = 0, status = 'DISABLED', updated_at = NOW(), updated_by = %s
                  WHERE rule_code = %s AND id <> %s AND status = 'ACTIVE'""", (user_id, rule['rule_code'], rule_id))
    db.execute("""UPDATE tm_rules SET status = 'ACTIVE', is_active = 1, approved_by = %s, approved_at = NOW(),
                  updated_at = NOW() WHERE id = %s""", (user_id, rule_id))
    db.commit()
    return rule


def reject(db, rule_id, user_id, reason):
    reason = _reason(reason)
    rule = _get(db, rule_id)
    if rule.get('status') != 'PENDING':
        raise VersionError(N_('Only a version waiting for approval can be rejected.'))
    db.execute("""UPDATE tm_rules SET status = 'REJECTED', is_active = 0, updated_at = NOW(), updated_by = %s,
                  change_reason = COALESCE(change_reason, '') || ' | rejected: ' || %s WHERE id = %s""",
               (user_id, reason, rule_id))
    db.commit()
    return rule


def rollback(db, rule_id, user_id, reason):
    """Re-activate the version this one replaced; this one is disabled."""
    reason = _reason(reason)
    rule = _get(db, rule_id)
    if not rule.get('previous_id'):
        raise VersionError(N_('No previous version to roll back to.'))
    if rule.get('status') != 'ACTIVE':
        raise VersionError(N_('Only the version in force can be rolled back.'))
    prev = _get(db, rule['previous_id'])
    db.execute("""UPDATE tm_rules SET status = 'DISABLED', is_active = 0, updated_at = NOW(), updated_by = %s
                  WHERE rule_code = %s AND status = 'ACTIVE'""", (user_id, rule['rule_code']))
    db.execute("""UPDATE tm_rules SET status = 'ACTIVE', is_active = 1, updated_at = NOW(), updated_by = %s,
                  change_reason = COALESCE(change_reason, '') || ' | restored by rollback: ' || %s WHERE id = %s""",
               (user_id, reason, prev['id']))
    db.commit()
    return prev


def history(db, rule_code):
    """All versions of a rule, newest first, with who / when / why and the alerts each raised."""
    rows = db.execute("""
        SELECT r.*, cu.email AS created_by_email, au.email AS approved_by_email,
               (SELECT COUNT(*) FROM tm_alerts a WHERE a.rule_id = r.id) AS alerts
          FROM tm_rules r LEFT JOIN users cu ON cu.id = r.created_by LEFT JOIN users au ON au.id = r.approved_by
         WHERE r.rule_code = %s ORDER BY r.version DESC NULLS LAST, r.id DESC""", (rule_code,)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        r['params'] = E.rule_params(r)
        out.append(r)
    return out


def diff(old, new):
    """Parameter changes between two versions: [(name, old, new)]."""
    a, b = E.rule_params(old or {}), E.rule_params(new or {})
    keys = sorted(set(a) | set(b))
    ch = [(k, a.get(k), b.get(k)) for k in keys if a.get(k) != b.get(k)]
    for f in ('severity', 'threshold_currency', 'rule_name'):
        if (old or {}).get(f) != (new or {}).get(f):
            ch.append((f, (old or {}).get(f), (new or {}).get(f)))
    return ch
