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

Four eyes holds on every path that puts a version in force:
- approve(): only a PENDING version with a recorded proposer, by someone else;
- rollback() / enable(): only a DISABLED version that was approved once (approved_at)
  or was in force before versioning existed (legacy_baseline);
- propose(): previous_id is always the version in force when the change was
  proposed (never a rejected or never-approved row), whatever row seeded the form.
"""
import json
import re

from aml import tm_engine as E


def N_(s):
    return s


class VersionError(ValueError):
    """A refused change; carries the message in English and Arabic."""

    def __init__(self, en, ar=None):
        super().__init__(en)
        self.ar = ar


def message(e, ar=False):
    """The message of a VersionError in the user's language."""
    return (getattr(e, 'ar', None) if ar else None) or str(e)


MIN_REASON = 10
CODE_RE = re.compile(r'^[A-Z0-9_]{2,20}$')
# The version in force (legacy rows may still have status NULL with is_active = 1).
IN_FORCE = "is_active = 1 AND COALESCE(status, 'ACTIVE') = 'ACTIVE'"
# Rows to retire when another version goes in force (also inconsistent ones).
RETIRE = "(is_active = 1 OR status = 'ACTIVE')"
FIELDS = ('rule_name', 'rule_name_ar', 'rule_description', 'rule_category', 'rule_type', 'threshold_value',
          'threshold_currency', 'time_period_days', 'severity', 'reference', 'threshold_unit')


def active_rules(db):
    """The version in force of each rule code (newest active one when data is inconsistent)."""
    rows = db.execute(f"""SELECT DISTINCT ON (rule_code) * FROM tm_rules
                         WHERE {IN_FORCE}
                         ORDER BY rule_code, version DESC NULLS LAST, id DESC""").fetchall()
    return [dict(r) for r in rows]


def in_force(db, rule_code):
    row = db.execute(f"""SELECT * FROM tm_rules WHERE rule_code = %s AND {IN_FORCE}
                         ORDER BY version DESC NULLS LAST, id DESC LIMIT 1""", (rule_code,)).fetchone()
    return dict(row) if row else None


def was_approved(rule):
    """Approved once by four eyes, or in force before versioning existed."""
    return bool(rule.get('approved_at')) or bool(rule.get('legacy_baseline'))


def _retire_others(db, rule_code, keep_id, user_id):
    db.execute(f"""UPDATE tm_rules SET is_active = 0, status = 'DISABLED', updated_at = NOW(), updated_by = %s
                   WHERE rule_code = %s AND id <> %s AND {RETIRE}""", (user_id, rule_code, keep_id))


def _get(db, rule_id):
    row = db.execute("SELECT * FROM tm_rules WHERE id = %s", (rule_id,)).fetchone()
    if not row:
        raise VersionError(N_('Rule not found.'), 'القاعدة مش موجودة.')
    return dict(row)


def _reason(reason):
    reason = (reason or '').strip()
    if len(reason) < MIN_REASON:
        raise VersionError(N_('Write the reason for the change (at least 10 characters).'), 'اكتب سبب التعديل (10 حروف على الأقل).')
    return reason


def clean_parameters(code, raw):
    """Keep only the extra parameters the rule defines, typed as the spec says."""
    E.ensure_packs_loaded()            # a pack rule's parameters are known only once the pack is loaded
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
            raise VersionError(N_('A rule parameter has an invalid value.'), 'في معيار من معايير القاعدة قيمته غير صحيحة.')
        if unit in ('count', 'amount', 'ratio', 'hours', 'minutes', 'percent') and out[k] < 0:
            raise VersionError(N_('A rule parameter has an invalid value.'), 'في معيار من معايير القاعدة قيمته غير صحيحة.')
    return out


def propose(db, base_id, values, parameters, reason, user_id, code=None):
    """New pending version of an existing rule (base_id) or a brand-new rule (base_id None, code given)."""
    reason = _reason(reason)
    E.ensure_packs_loaded()
    if base_id:
        base = _get(db, base_id)
        code = base['rule_code']
        latest = db.execute("SELECT MAX(version) AS v FROM tm_rules WHERE rule_code = %s", (code,)).fetchone()['v'] or 0
        if db.execute("SELECT 1 FROM tm_rules WHERE rule_code = %s AND status = 'PENDING'", (code,)).fetchone():
            raise VersionError(N_('This rule already has a version waiting for approval; approve or reject it first.'), 'القاعدة دي عندها نسخة مستنية اعتماد؛ اعتمدها أو ارفضها الأول.')
        # The new version replaces the version IN FORCE (what a rollback returns to), not the
        # row the form was opened from: that row only seeds the values.
        current = in_force(db, code)
        version, previous = latest + 1, (current['id'] if current else None)
    else:
        code = (code or '').strip().upper()
        if not CODE_RE.match(code):
            raise VersionError(N_('Rule code: 2 to 20 capital letters, digits or underscores.'), 'كود القاعدة: من 2 لـ 20 حرف إنجليزي كبير أو رقم أو _.')
        if db.execute("SELECT 1 FROM tm_rules WHERE rule_code = %s", (code,)).fetchone():
            raise VersionError(N_('This rule code already exists; edit it to make a new version.'), 'كود القاعدة ده موجود؛ عدّل القاعدة عشان تعمل نسخة جديدة.')
        version, previous, base = 1, None, {}
    row = {f: values.get(f, base.get(f)) for f in FIELDS}
    if row.get('time_period_days') is None:
        row['time_period_days'] = 1
    # Parameters not on the form (or left empty) keep the base version's values.
    merged = dict(_json(base.get('parameters')))
    merged.update({k: v for k, v in (parameters or {}).items() if v not in (None, '')})
    params = clean_parameters(code, merged)
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
        raise VersionError(N_('Only a version waiting for approval can be approved.'), 'ممكن تعتمد بس نسخة مستنية اعتماد.')
    if rule.get('created_by') is None:
        # Four eyes cannot be checked without a proposer: reject it and propose it again
        # (the new version records who proposed it).
        raise VersionError(N_('This version has no recorded proposer, so four eyes cannot be checked. '
                              'Reject it and propose it again, then have another person approve it.'), 'النسخة دي مش متسجل مين اقترحها، فمش ممكن نتأكد من مبدأ الأربع عيون. ارفضها واقترحها تاني، وبعدين شخص تاني يعتمدها.')
    if int(rule['created_by']) == int(user_id) and not can_self_approve:
        raise VersionError(N_('Another person must approve a rule change (four eyes).'), 'لازم شخص تاني يعتمد تعديل القاعدة (مبدأ الأربع عيون).')
    _retire_others(db, rule['rule_code'], rule_id, user_id)
    db.execute("""UPDATE tm_rules SET status = 'ACTIVE', is_active = 1, approved_by = %s, approved_at = NOW(),
                  updated_at = NOW() WHERE id = %s""", (user_id, rule_id))
    db.commit()
    return rule


def reject(db, rule_id, user_id, reason):
    reason = _reason(reason)
    rule = _get(db, rule_id)
    if rule.get('status') != 'PENDING':
        raise VersionError(N_('Only a version waiting for approval can be rejected.'), 'ممكن ترفض بس نسخة مستنية اعتماد.')
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
        raise VersionError(N_('No previous version to roll back to.'), 'مافيش نسخة سابقة ترجع لها.')
    if not (rule.get('is_active') == 1 and (rule.get('status') or 'ACTIVE') == 'ACTIVE'):
        raise VersionError(N_('Only the version in force can be rolled back.'), 'ممكن ترجع بس من النسخة المفعلة حاليًا.')
    prev = _get(db, rule['previous_id'])
    if prev.get('rule_code') != rule.get('rule_code') or prev.get('status') != 'DISABLED' or not was_approved(prev):
        raise VersionError(N_('The previous version was never approved (or is not a retired version of this rule), '
                              'so it cannot be put back in force. Propose a new version instead.'), 'النسخة السابقة عمرها ما اتعتمدت (أو مش نسخة موقوفة من نفس القاعدة)، فمش ممكن ترجع للتفعيل. اقترح نسخة جديدة.')
    _retire_others(db, rule['rule_code'], prev['id'], user_id)
    db.execute("""UPDATE tm_rules SET status = 'ACTIVE', is_active = 1, updated_at = NOW(), updated_by = %s,
                  change_reason = COALESCE(change_reason, '') || ' | restored by rollback: ' || %s WHERE id = %s""",
               (user_id, reason, prev['id']))
    db.commit()
    return prev


def disable(db, rule_id, user_id, reason):
    """Take the version in force out of force (reason required, kept in the audit log)."""
    if not (reason or '').strip():
        raise VersionError(N_('A reason is required to disable a rule.'), 'لازم تكتب سبب إيقاف القاعدة.')
    rule = _get(db, rule_id)
    if (rule.get('status') or ('ACTIVE' if rule.get('is_active') == 1 else 'DISABLED')) != 'ACTIVE':
        raise VersionError(N_('Only an active rule can be disabled.'), 'ممكن توقف بس قاعدة مفعلة.')
    db.execute("UPDATE tm_rules SET status='DISABLED', is_active=0, updated_at=NOW(), updated_by=%s WHERE id=%s",
               (user_id, rule_id))
    db.commit()
    return rule


def enable(db, rule_id, user_id, reason):
    """Put a disabled version back in force. Only one that was approved once (or was in
    force before versioning); every other version of the code is retired, so exactly
    one version is in force."""
    if not (reason or '').strip():
        raise VersionError(N_('A reason is required to enable a rule.'), 'لازم تكتب سبب تفعيل القاعدة.')
    rule = _get(db, rule_id)
    if rule.get('status') != 'DISABLED':
        raise VersionError(N_('Only a disabled rule can be enabled.'), 'ممكن تفعّل بس قاعدة موقوفة.')
    if not was_approved(rule):
        raise VersionError(N_('This version was never approved, so it cannot be enabled. '
                              'Propose a new version and have another person approve it.'), 'النسخة دي عمرها ما اتعتمدت، فمش ممكن تتفعل. اقترح نسخة جديدة وخلي شخص تاني يعتمدها.')
    _retire_others(db, rule['rule_code'], rule_id, user_id)
    db.execute("UPDATE tm_rules SET status='ACTIVE', is_active=1, updated_at=NOW(), updated_by=%s WHERE id=%s",
               (user_id, rule_id))
    db.commit()
    return rule


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
