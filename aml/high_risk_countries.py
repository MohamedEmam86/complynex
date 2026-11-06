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
High-risk countries list (FATF black / grey lists, internal and other lists).

The list is DATA (table high_risk_countries), maintained on /aml/high-risk-countries
by the MLRO (the designation of screening.clearance: compliance managers, or the
administrators where there is none). Every change needs a reason and is audited.

What reads the list (kept in IMPACT below, shown on the page):
  * aml/edd.py + edd_logic.forced_high_reasons: the customer HIGH risk floor and EDD
  * aml/tm_engine.load_high_risk: transaction-monitoring rule TM004
  * utils/aml_risk (customer risk model score) ONLY when the model's country source is
    'table' or 'both' (default: its own built-in list)
  * the risk radar chart on the customer page (display only)
Every ACTIVE row counts the same, whatever its category.
"""
import json
import re
from datetime import date

from database.db import get_db

CATEGORIES = [  # code, EN, AR
    ('CALL_FOR_ACTION', 'FATF black list — high-risk jurisdictions subject to a call for action',
     'القائمة السوداء لمجموعة العمل المالي (فاتف) — دول عالية المخاطر مطلوب اتخاذ إجراء بشأنها'),
    ('INCREASED_MONITORING', 'FATF grey list — jurisdictions under increased monitoring',
     'القائمة الرمادية لمجموعة العمل المالي (فاتف) — دول تحت المراقبة المعززة'),
    ('INTERNAL', 'Internal decision', 'قرار داخلي'),
    ('OTHER', 'Other list (e.g. a regulator or another authority)', 'قائمة أخرى (مثل جهة رقابية أو جهة أخرى)'),
]
CATEGORY_CODES = tuple(c for c, _e, _a in CATEGORIES)

# What uses the list, for the "Impact" panel: (key, EN title, AR title, EN text, AR text, where in code)
IMPACT = [
    ('floor',
     'Customer risk floor and enhanced due diligence (always on)',
     'الحد الأدنى لتصنيف مخاطر العميل والعناية الواجبة المشددة (يعمل دائماً)',
     'A customer whose nationality, country or registration country — or, for a company, the nationality of a '
     'beneficial owner or authorised signatory (KYB) — is an active country here is rated HIGH risk whatever the '
     'score, is marked "high-risk country connection" (customer page and CDD form), needs enhanced due diligence '
     '(an EDD record is opened) and, when new, stays PENDING until the EDD is approved. It is applied when a '
     'customer is created, edited, screened or its KYB changes, and to everyone with "Re-assess all customers".',
     'العميل الذي تكون جنسيته أو دولته أو دولة تسجيله — أو جنسية أحد المستفيدين الحقيقيين أو المفوضين بالتوقيع '
     'للشركات (KYB) — دولة نشطة في هذه القائمة يُصنف عالي المخاطر أياً كانت درجته، ويُعلَّم "ارتباط بدولة عالية '
     'المخاطر" (صفحة العميل ونموذج العناية الواجبة)، ويلزمه عناية واجبة مشددة (يُفتح سجل EDD)، والعميل الجديد يظل '
     '"قيد الانتظار" حتى اعتماد العناية المشددة. يُطبق عند إنشاء العميل أو تعديله أو فحصه أو تغيير بيانات KYB، '
     'وعلى الجميع بزر "إعادة تقييم كل العملاء".',
     'aml/edd.py reassess · aml/edd_logic.py forced_high_reasons'),
    ('tm004',
     'Transaction monitoring rule TM004 — transaction with a high-risk country',
     'قاعدة مراقبة المعاملات TM004 — معاملة مع دولة عالية المخاطر',
     'A transaction whose counterparty country is an active country here (by code, English or Arabic name, or another '
     'spelling) raises a TM004 alert, in live monitoring, back-tests and the rule test. If the list cannot be read, '
     'the rule falls back to Iran, North Korea and Myanmar.',
     'المعاملة التي تكون دولة الطرف المقابل فيها دولة نشطة هنا (بالرمز أو الاسم الإنجليزي أو العربي أو تهجئة أخرى) '
     'تولّد تنبيه TM004، في المراقبة الفعلية والاختبار الرجعي واختبار القاعدة. إذا تعذرت قراءة القائمة تستخدم القاعدة '
     'إيران وكوريا الشمالية وميانمار فقط.',
     'aml/tm_engine.py load_high_risk · rule TM004'),
    ('model',
     'Customer risk model score (only when switched on)',
     'درجة نموذج تقييم مخاطر العملاء (فقط عند تفعيلها)',
     'The country points of the customer risk model come from this list only when the model\'s "High-risk countries '
     'come from" is set to the table or to either. Otherwise the model uses its own built-in list.',
     'نقاط الدولة في نموذج تقييم مخاطر العملاء تُحسب من هذه القائمة فقط عند ضبط "مصدر الدول عالية المخاطر" في '
     'النموذج على الجدول أو على أي منهما. وإلا يستخدم النموذج قائمته المدمجة.',
     'utils/aml_risk.py _high_risk_country'),
    ('radar',
     'Customer page risk radar (display only)',
     'مخطط المخاطر في صفحة العميل (للعرض فقط)',
     'The geography axis of the radar chart on the customer page is high when the customer\'s nationality or country '
     'is an active country here. It changes no rating.',
     'محور الجغرافيا في مخطط المخاطر بصفحة العميل يكون مرتفعاً إذا كانت جنسية العميل أو دولته دولة نشطة هنا. لا يغيّر '
     'أي تصنيف.',
     'aml/routes.py view_customer'),
]
NOT_USED = (
    'Not used by: name screening against sanctions / PEP lists, the TM010 rule (international transfers, which uses '
    'its own "domestic country" parameter) and the KYB sanctioned-ownership check.',
    'لا تستخدمها: مطابقة الأسماء مع قوائم العقوبات والأشخاص السياسيين، وقاعدة TM010 (التحويلات الدولية، ولها معامل '
    '"الدولة المحلية" الخاص بها)، وفحص الملكية المعاقبة في KYB.')

CODE_RE = re.compile(r'^[A-Z]{2,3}$')


class CountryError(ValueError):
    pass


def category_label(code, ar=False):
    for c, en, a in CATEGORIES:
        if c == code:
            return a if ar else en
    return code or '—'


def _aliases(v):
    parts = [p.strip() for p in str(v or '').replace('\n', '|').split('|')]
    seen, out = set(), []
    for p in parts:
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p[:100])
    return '|'.join(out) or None


def clean(form):
    """Validated row values from the add / edit form (raises CountryError)."""
    code = (form.get('country_code') or '').strip().upper()
    if not CODE_RE.match(code):
        raise CountryError('Enter the ISO country code: 2 or 3 letters (e.g. YE or YEM).')
    name = (form.get('country_name') or '').strip()
    if len(name) < 2:
        raise CountryError('Enter the country name in English.')
    cat = form.get('risk_category') or ''
    if cat not in CATEGORY_CODES:
        raise CountryError('Choose the category.')
    source = (form.get('source') or '').strip()
    if len(source) < 3:
        raise CountryError('Enter the source (e.g. FATF public statement, October 2026, or the internal decision).')
    eff = (form.get('effective_date') or '').strip()
    if eff:
        try:
            eff = date.fromisoformat(eff[:10]).isoformat()
        except ValueError:
            raise CountryError('The date must be a valid date (YYYY-MM-DD).')
    return {'country_code': code, 'country_name': name[:100], 'name_ar': (form.get('name_ar') or '').strip()[:100] or None,
            'aliases': _aliases(form.get('aliases')), 'risk_category': cat, 'source': source[:300],
            'effective_date': eff or None, 'notes': (form.get('notes') or '').strip()[:1000] or None,
            'is_active': 1 if form.get('is_active') in ('1', 'on', 'true') else 0}


def reason_of(form):
    r = (form.get('reason') or '').strip()
    if len(r) < 5:
        raise CountryError('Give the reason for the change (at least 5 characters).')
    return r[:500]


def rows(db=None):
    db = db or get_db()
    return [dict(r) for r in db.execute(
        """SELECT h.*, TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS updated_by_name
             FROM high_risk_countries h LEFT JOIN users u ON u.id = h.updated_by
            ORDER BY COALESCE(h.is_active, 0) DESC,
                     CASE h.risk_category WHEN 'CALL_FOR_ACTION' THEN 0 WHEN 'INCREASED_MONITORING' THEN 1
                                          WHEN 'INTERNAL' THEN 2 ELSE 3 END, h.country_name""").fetchall()]


def get(row_id, db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM high_risk_countries WHERE id = %s", (row_id,)).fetchone()
    if not r:
        raise CountryError('Country not found.')
    return dict(r)


def _duplicate(db, vals, exclude_id=None):
    return db.execute("""SELECT id FROM high_risk_countries
                          WHERE (upper(country_code) = %s OR upper(country_name) = upper(%s)) AND id <> %s LIMIT 1""",
                      (vals['country_code'], vals['country_name'], exclude_id or 0)).fetchone()


def _audit(user_id, row_id, detail):
    try:
        from flask import request
        ip = request.remote_addr
    except Exception:
        ip = None
    from models.audit import AuditLog
    AuditLog.log(user_id, 'High-risk Countries', 'AML', row_id, detail, ip)


def _changed():
    try:
        from . import risk_config
        risk_config.invalidate()
    except Exception:
        pass


def _row_text(r):
    keep = ('country_code', 'country_name', 'name_ar', 'aliases', 'risk_category', 'source', 'effective_date',
            'notes', 'is_active')
    return json.dumps({k: r.get(k) for k in keep}, ensure_ascii=False, default=str)


def add(form, user_id, db=None):
    db = db or get_db()
    vals, reason = clean(form), reason_of(form)
    vals['is_active'] = 1
    if _duplicate(db, vals):
        raise CountryError('This country is already on the list: edit or reactivate it instead.')
    try:
        rid = _insert(db, vals, user_id)
    except Exception as ex:
        import psycopg2
        if not isinstance(ex, psycopg2.IntegrityError):
            raise
        db.rollback()
        raise CountryError('This country is already on the list: edit or reactivate it instead.')
    db.commit()
    _changed()
    _audit(user_id, rid, f'added {vals["country_code"]} {vals["country_name"]} ({vals["risk_category"]}): {reason}')
    return rid


def _insert(db, vals, user_id):
    return db.execute("""INSERT INTO high_risk_countries (country_code, country_name, name_ar, aliases, risk_category,
                        source, effective_date, is_active, notes, updated_by, updated_at)
                        VALUES (%(country_code)s, %(country_name)s, %(name_ar)s, %(aliases)s, %(risk_category)s,
                                %(source)s, %(effective_date)s, %(is_active)s, %(notes)s, %(uid)s, now()) RETURNING id""",
                      dict(vals, uid=user_id)).fetchone()['id']


def update(row_id, form, user_id, db=None):
    db = db or get_db()
    old = get(row_id, db)
    vals, reason = clean(form), reason_of(form)
    if _duplicate(db, vals, exclude_id=row_id):
        raise CountryError('Another row already has this code or name.')
    db.execute("""UPDATE high_risk_countries SET country_code = %(country_code)s, country_name = %(country_name)s,
                  name_ar = %(name_ar)s, aliases = %(aliases)s, risk_category = %(risk_category)s, source = %(source)s,
                  effective_date = %(effective_date)s, is_active = %(is_active)s, notes = %(notes)s,
                  updated_by = %(uid)s, updated_at = now() WHERE id = %(id)s""", dict(vals, uid=user_id, id=row_id))
    db.commit()
    _changed()
    _audit(user_id, row_id, f'edited {old["country_code"]} {old["country_name"]}: {reason}; before {_row_text(old)}; '
                            f'after {_row_text(vals)}')


def active_count(db=None):
    db = db or get_db()
    return int(db.execute("SELECT count(*) AS n FROM high_risk_countries WHERE is_active = 1").fetchone()['n'])


def set_active(row_id, active, form, user_id, db=None):
    """Returns the number of active countries left."""
    db = db or get_db()
    old = get(row_id, db)
    reason = reason_of(form)
    db.execute("UPDATE high_risk_countries SET is_active = %s, updated_by = %s, updated_at = now() WHERE id = %s",
               (1 if active else 0, user_id, row_id))
    db.commit()
    _changed()
    _audit(user_id, row_id, f'{"reactivated" if active else "deactivated"} {old["country_code"]} {old["country_name"]}: '
                            f'{reason}')
    return active_count(db)


def delete(row_id, form, user_id, db=None):
    """Delete an INACTIVE row (deactivate it first). Returns the number of active countries left."""
    db = db or get_db()
    old = get(row_id, db)
    reason = reason_of(form)
    if old.get('is_active') not in (0, None, False):
        raise CountryError('Deactivate the country before deleting it.')
    try:
        db.execute("DELETE FROM high_risk_countries WHERE id = %s", (row_id,))
        db.commit()
    except Exception as ex:
        import psycopg2
        if not isinstance(ex, psycopg2.IntegrityError):
            raise
        db.rollback()
        raise CountryError('The country is still referenced and cannot be deleted; keep it deactivated.')
    _changed()
    _audit(user_id, row_id, f'deleted {old["country_code"]} {old["country_name"]}: {reason}; row was {_row_text(old)}')
    return active_count(db)


def impact_status(db=None):
    """Live facts for the Impact panel: model source, built-in list, flagged customers, TM004 on/off."""
    from . import risk_config as RC
    db = db or get_db()
    model = RC.current_model(db)
    out = {'model_source': model['country'].get('source', 'builtin'),
           'builtin_list': model['country'].get('builtin_list') or [],
           'model_saved': bool(RC.history(db, limit=1)), 'flagged_customers': None, 'tm004_active': None}
    try:
        r = RC.safe_rows(db, "SELECT count(*) AS n FROM customers WHERE is_high_risk_country = 1")
        out['flagged_customers'] = int(r[0]['n']) if r else 0
    except Exception:
        pass
    try:
        r = RC.safe_rows(db, "SELECT max(COALESCE(is_active, 0)) AS a FROM tm_rules WHERE rule_code = 'TM004'")
        out['tm004_active'] = bool(r and r[0]['a'])
    except Exception:
        pass
    return out
