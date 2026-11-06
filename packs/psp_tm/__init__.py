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
PSP transaction-monitoring pack — typologies for payment service providers
(e-wallets, agents / cash-in points, merchants). Optional: the core rule engine
(aml/tm_engine.py) knows nothing about it.

Importing the pack registers its rule logic with the engine. Enabling it
(Compliance Controls > Packs) runs install(), which adds its rules to
tm_rules as PENDING versions: none of them monitors anything until a
compliance officer reviews the parameters, backtests them and approves them.
Default values are starting points, not regulatory limits.
TODO(compliance-review): confirm every default against the institution's own
limits and the regulator's typology guidance before approval.
"""
import json

from regcontrols.api import Pack, register_pack

from . import rules as R

PACK_CODE = 'psp_tm'


def _installer_id():
    """The signed-in user who enables the pack (recorded as the proposer of its rules,
    so a different person must approve them). None outside a request."""
    try:
        from flask_login import current_user
        if current_user and current_user.is_authenticated:
            return int(current_user.id)
    except Exception:
        pass
    return None


def install(db, user_id=None):
    """Idempotent: adds each pack rule once, as a pending version proposed by the person
    who enables the pack; never touches existing rules."""
    user_id = user_id if user_id is not None else _installer_id()
    added = 0
    for r in R.RULES:
        if db.execute("SELECT 1 FROM tm_rules WHERE rule_code = %s", (r['rule_code'],)).fetchone():
            continue
        db.execute("""
            INSERT INTO tm_rules (rule_code, rule_name, rule_name_ar, rule_description, rule_category, rule_type,
                                  threshold_value, threshold_currency, time_period_days, severity, parameters,
                                  reference, pack_code, change_reason, is_active, status, created_by, created_at,
                                  version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,'PENDING',%s,NOW(),1)""",
            (r['rule_code'], r['rule_name'], r['rule_name_ar'], r['rule_description'], r['rule_category'],
             r['rule_type'], r['threshold_value'], r.get('threshold_currency'), r.get('time_period_days') or 1,
             r['severity'], json.dumps(r.get('parameters') or {}), r.get('reference'), PACK_CODE,
             'Added by the PSP transaction-monitoring pack: review, backtest and approve before use', user_id))
        added += 1
    db.commit()
    return {'rules_added': added, 'rules_in_pack': len(R.RULES)}


PACK = register_pack(Pack(
    code=PACK_CODE,
    name_en='PSP transaction-monitoring rules',
    name_ar='قواعد مراقبة المعاملات لمقدمي خدمات الدفع',
    description_en=('Monitoring typologies for payment service providers: cash-in structuring, pass-through '
                    'wallets, many-to-one and one-to-many transfers, cash velocity of one account (agent / cash point). Rules are added as '
                    'pending versions to be backtested and approved; defaults are starting points.'),
    description_ar=('أنماط مراقبة لمقدمي خدمات الدفع: تجزئة الإيداع النقدي، المحافظ اللي بتمرر الفلوس، '
                    'تحويلات من كتير لواحد ومن واحد لكتير، وسرعة عمليات الكاش لحساب واحد (وكيل / نقطة كاش). القواعد بتتضاف كنسخ '
                    'معلقة لازم تتختبر وتتعتمد، والقيم الافتراضية نقطة بداية بس.'),
    version='1',
    install=install,
))
