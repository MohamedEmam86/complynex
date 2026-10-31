"""
Analyst workflow on top of the match decision (Phase 4).

P4-1  completeness(): a screening during which a source was unavailable (search index down,
      semantic recall down, a list out of date) is never reported as "no match": the engine
      marks it INCOMPLETE with the reasons, and the analyst re-screens.
P4-2  explain(): a short, plain explanation of each hit (English + Arabic), built only from
      the decision data the engine already computed (no language model).
P4-3  list_type_of() / action_for(): similarity (the score), identity (identifiers) and the
      ACTION are kept apart; the action depends on the kind of list the record is on, from a
      table the MLRO maintains (screening_config 'list_action_table', audited).
G9    identity_status(): when identifiers are missing on either side the hit is shown as
      "identity not verifiable" with the next step the analyst must take.

Every function here is pure or fails open: an error never removes or lowers a hit.
"""
import json
import logging
import os
import threading
import time

from screening import match_intel as mi

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- P4-1 completeness
SEMANTIC_REQUIRED = os.getenv('SEMANTIC_REQUIRED', '1') != '0'

_REASONS = {
    'search_index': ('The main search index was unavailable: recall fell back to the database search only.',
                     'فهرس البحث الرئيسي ماكانش متاح: البحث اتعمل على قاعدة البيانات بس.'),
    'semantic': ('The semantic (similar-name) search was unavailable during this screening.',
                 'البحث الدلالي (الأسماء المتشابهة) ماكانش متاح وقت الفحص.'),
    'list_overdue': ('List "{name}" is out of date (last good update {age} h ago, allowed {max} h).',
                     'قايمة "{name}" مش محدّثة (آخر تحديث سليم من {age} ساعة، والمسموح {max} ساعة).'),
    'list_failed': ('The last update of list "{name}" failed; the previous version (still within its allowed age) was searched.',
                    'آخر تحديث لقايمة "{name}" فشل؛ اتبحث في الإصدار السابق (لسه في حدود العمر المسموح).'),
    'list_blocked': ('The last update of list "{name}" was blocked by the update guard; the version in force was searched.',
                     'آخر تحديث لقايمة "{name}" اتوقف بواسطة حماية التحديث؛ اتبحث في الإصدار الساري.'),
    'adverse_media': ('The adverse media search did not complete.',
                      'البحث في الأخبار السلبية ماكملش.'),
}


def _reason(code, **kw):
    en, ar = _REASONS[code]
    try:
        return {'code': code, 'source': kw.get('source'), 'en': en.format(**kw), 'ar': ar.format(**kw)}
    except Exception:
        return {'code': code, 'source': kw.get('source'), 'en': en, 'ar': ar}


def _is_demo():
    try:
        from utils.demo import is_demo
        return bool(is_demo())
    except Exception:
        return False


def _freshness():
    """List freshness (cached a minute per worker). None when it cannot be read (never blocks)."""
    if _is_demo():
        return []          # the demo's lists are maintained by the main instance
    try:
        from screening import list_versions as LV
        return LV.cached_freshness(ttl=60)
    except Exception as e:
        logger.warning('list freshness not readable (%s); completeness check skips lists', e)
        return None


def completeness(es_degraded=False, semantic_degraded=False, adverse_error=None, freshness='auto'):
    """(blocking, warnings): blocking reasons make a no-match result INCOMPLETE; warnings are shown only."""
    blocking, warnings = [], []
    if es_degraded:
        blocking.append(_reason('search_index'))
    if semantic_degraded and SEMANTIC_REQUIRED:
        blocking.append(_reason('semantic'))
    if adverse_error:
        warnings.append(_reason('adverse_media'))
    rows = _freshness() if freshness == 'auto' else freshness
    for f in rows or []:
        try:
            name = f.get('name') or f.get('source')
            age, mx = f.get('age_hours'), f.get('max_age_hours')
            overdue = f.get('problem') == 'overdue' or (age is not None and mx and float(age) > float(mx))
            if overdue:
                blocking.append(_reason('list_overdue', source=f.get('source'), name=name,
                                        age='—' if age is None else int(round(float(age))),
                                        max=int(round(float(mx or 0)))))
            elif f.get('problem') in ('failed', 'blocked'):
                warnings.append(_reason('list_' + f['problem'], source=f.get('source'), name=name))
        except Exception as e:
            logger.debug('freshness row skipped: %s', e)
    return blocking, warnings


INCOMPLETE_FROM = ('CLEAR', 'LOW_MATCH')


def finalize_status(result_status, blocking):
    """A result with no alert is never 'clear' when a source was unavailable."""
    if blocking and result_status in INCOMPLETE_FROM:
        return 'INCOMPLETE'
    return result_status


# --------------------------------------------------------------------------- P4-3 list type and action
LIST_TYPES = ['SANCTIONS', 'TERROR', 'UNCLASSIFIED', 'SANCTION_LINKED', 'CRIME', 'PEP', 'EXPORT_CONTROL',
              'COUNTER_SANCTIONS', 'DEBARMENT', 'REG_ACTION', 'TRADE_RISK', 'POI', 'CONTEXT',
              'INTERNAL', 'EMLCU', 'PMA', 'REGULATORY']

LIST_TYPE_LABEL = {
    'SANCTIONS': ('Sanctions / asset freeze', 'عقوبات / تجميد أموال'),
    'TERROR': ('Terrorism listing', 'إدراج إرهاب'),
    'UNCLASSIFIED': ('Unclassified (treated as sanctions)', 'غير مصنف (يعامل كعقوبات)'),
    'SANCTION_LINKED': ('Linked to a sanctioned party', 'مرتبط بجهة معاقبة'),
    'CRIME': ('Criminal / wanted list', 'قايمة جنائية / مطلوبين'),
    'PEP': ('Politically exposed person', 'شخص سياسي ممثل للمخاطر'),
    'EXPORT_CONTROL': ('Export control', 'قيود تصدير'),
    'COUNTER_SANCTIONS': ('Counter-sanctions', 'عقوبات مضادة'),
    'DEBARMENT': ('Debarment / disqualification', 'حرمان / استبعاد'),
    'REG_ACTION': ('Regulatory action or warning', 'إجراء أو تحذير رقابي'),
    'TRADE_RISK': ('Trade risk research', 'مخاطر تجارية'),
    'POI': ('Person of interest', 'شخص محل اهتمام'),
    'CONTEXT': ('Background data, not a list', 'بيانات خلفية - مش قايمة'),
    'INTERNAL': ('Internal list (local orders / lists)', 'قايمة داخلية (أوامر وقوايم محلية)'),
    'EMLCU': ('EMLCU terrorist lists (Egypt)', 'قوايم الإرهاب - وحدة مكافحة غسل الأموال'),
    'PMA': ('Palestine national list (UNSCR 1373)', 'القايمة الوطنية الفلسطينية (1373)'),
    'REGULATORY': ('Regulatory measures (KYB)', 'إجراءات رقابية (KYB)'),
}

ACTIONS = {
    'FREEZE_ESCALATE': {
        'label': ('Freeze and escalate', 'تجميد وتصعيد'),
        'CONFIRMED': ('Do not onboard or process. Freeze funds without delay, escalate to the MLRO and report as the law requires.',
                      'ماتكملش التعامل. جمّد الأموال فوراً، صعّد لمسؤول الإبلاغ، وبلّغ حسب القانون.'),
        'POTENTIAL': ('Hold the relationship / transaction and escalate to the MLRO. Verify identity; freeze without delay once it is confirmed.',
                      'أوقف العلاقة / العملية وصعّد لمسؤول الإبلاغ. اتحقق من الهوية، ولو اتأكدت جمّد فوراً.'),
    },
    'FREEZE_REPORT': {
        'label': ('Freeze and report (local law)', 'تجميد وإبلاغ (القانون المحلي)'),
        'CONFIRMED': ('Freeze without delay and report to the competent authority (EMLCU / supervisor) as the local order requires.',
                      'جمّد فوراً وبلّغ الجهة المختصة (الوحدة / الجهة الرقابية) حسب الأمر المحلي.'),
        'POTENTIAL': ('Hold and escalate to the MLRO. Verify identity against the order (national ID, date of birth); freeze and report once confirmed.',
                      'أوقف وصعّد لمسؤول الإبلاغ. اتحقق من الهوية مقابل الأمر (رقم قومي، تاريخ ميلاد)؛ ولو اتأكدت جمّد وبلّغ.'),
    },
    'EDD': {
        'label': ('Enhanced due diligence (not a rejection)', 'عناية واجبة مشددة (مش رفض)'),
        'CONFIRMED': ('Enhanced due diligence: source of funds and wealth, senior-management approval, enhanced ongoing monitoring. Not a reason to reject on its own.',
                      'عناية واجبة مشددة: مصدر الأموال والثروة، موافقة الإدارة العليا، ومتابعة مشددة. ده لوحده مش سبب للرفض.'),
        'POTENTIAL': ('Confirm whether the customer is this PEP (or a family member / close associate) before onboarding.',
                      'اتأكد إن العميل هو الشخص ده (أو قريب / مقرّب منه) قبل فتح العلاقة.'),
    },
    'MLRO_DECISION': {
        'label': ('MLRO decision', 'قرار مسؤول الإبلاغ'),
        'CONFIRMED': ('Not a freeze order on its own. Hold, confirm the identity, apply enhanced due diligence and let the MLRO decide; consider a suspicious transaction report.',
                      'مش أمر تجميد لوحده. أوقف، أكّد الهوية، طبّق عناية مشددة، والقرار لمسؤول الإبلاغ؛ وفكّر في إخطار اشتباه.'),
        'POTENTIAL': ('Hold and confirm the identity; the MLRO decides.', 'أوقف وأكّد الهوية؛ والقرار لمسؤول الإبلاغ.'),
    },
    'REVIEW': {
        'label': ('Review and record', 'مراجعة وتسجيل'),
        'CONFIRMED': ('Not a sanction: record it, apply enhanced due diligence where relevant, and reflect it in the customer risk rating.',
                      'مش عقوبات: سجّله، وطبّق عناية مشددة لو مناسب، وخده في تقييم مخاطر العميل.'),
        'POTENTIAL': ('Confirm whether it is the same person / entity and record the conclusion.',
                      'اتأكد هل هو نفس الشخص / الكيان وسجّل النتيجة.'),
    },
    'INFORMATION': {
        'label': ('Information only', 'للعلم فقط'),
        'CONFIRMED': ('Background information, not a list hit: use it only as context for due diligence.',
                      'معلومة خلفية، مش إدراج على قايمة: استخدمها كسياق للعناية الواجبة بس.'),
        'POTENTIAL': ('Background information, not a list hit: use it only as context.', 'معلومة خلفية، مش إدراج: للسياق بس.'),
    },
    'KYB_REVIEW': {
        'label': ('KYB review', 'مراجعة KYB'),
        'CONFIRMED': ('Regulatory measure on record: enhanced due diligence on the institution / person, record the measure and its date, decide with compliance approval.',
                      'إجراء رقابي مسجل: عناية مشددة على المؤسسة / الشخص، سجّل الإجراء وتاريخه، والقرار بموافقة الامتثال.'),
        'POTENTIAL': ('Confirm whether the customer is the institution / person the measure was taken against.',
                      'اتأكد إن العميل هو المؤسسة / الشخص اللي الإجراء اتاخد ضده.'),
    },
}
LOW_STEP = ('Low-confidence lead: review and record why it is or is not this person.',
            'احتمال ضعيف: راجع وسجّل ليه هو أو مش هو نفس الشخص.')

DEFAULT_TABLE = {
    'SANCTIONS': 'FREEZE_ESCALATE', 'TERROR': 'FREEZE_ESCALATE', 'UNCLASSIFIED': 'FREEZE_ESCALATE',
    'PEP': 'EDD',
    'CRIME': 'MLRO_DECISION', 'SANCTION_LINKED': 'MLRO_DECISION',
    'DEBARMENT': 'REVIEW', 'REG_ACTION': 'REVIEW', 'TRADE_RISK': 'REVIEW', 'EXPORT_CONTROL': 'REVIEW',
    'COUNTER_SANCTIONS': 'REVIEW',
    'CONTEXT': 'INFORMATION', 'POI': 'INFORMATION',
    'INTERNAL': 'FREEZE_REPORT', 'EMLCU': 'FREEZE_REPORT', 'PMA': 'FREEZE_REPORT',
    'REGULATORY': 'KYB_REVIEW',
}
TABLE_KEY = 'list_action_table'
_TABLE = {'at': 0.0, 'value': dict(DEFAULT_TABLE)}
_TLOCK = threading.Lock()
CACHE_SECONDS = 60


def validate_table(table):
    problems = []
    if not isinstance(table, dict):
        return ['the table must be an object']
    for k, v in table.items():
        if k not in LIST_TYPES:
            problems.append(f'unknown list type {k}')
        elif v not in ACTIONS:
            problems.append(f'unknown action {v} for {k}')
    return problems


def _read_table():
    import psycopg2
    from config import Config
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG, connect_timeout=5)
    try:
        cur = conn.cursor()
        cur.execute("SELECT config_value FROM screening_config WHERE config_key = %s", (TABLE_KEY,))
        row = cur.fetchone()
    finally:
        conn.close()
    stored = json.loads(row[0]) if row and row[0] else {}
    if validate_table(stored):
        logger.warning('list_action_table is invalid; defaults used for the invalid entries')
        stored = {k: v for k, v in stored.items() if k in LIST_TYPES and v in ACTIONS}
    return dict(DEFAULT_TABLE, **stored)


def action_table(force=False):
    """{list type: action code} in force (MLRO overrides on top of the defaults, cached a minute)."""
    now = time.time()
    if not force and now - _TABLE['at'] < CACHE_SECONDS:
        return dict(_TABLE['value'])
    with _TLOCK:
        try:
            val = _read_table()
        except Exception as e:
            logger.debug('action table not readable (%s); keeping the last values', e)
            val = dict(_TABLE['value'])
        _TABLE.update(at=now, value=val)
        return dict(val)


def list_type_of(m):
    """The kind of list a hit comes from (decides the action)."""
    m = m or {}
    src = str(m.get('source') or '').strip().lower()
    lt = str(m.get('list_type') or '').strip().upper()
    if src.endswith('_reg') or lt == 'REGULATORY':
        return 'REGULATORY'
    if src.startswith('internal_pep') or (src.startswith('internal') and lt == 'PEP'):
        return 'PEP'
    if src.startswith('internal'):
        return 'INTERNAL'
    if src.startswith('emlcu'):
        return 'EMLCU'
    if src.startswith('pma_ps'):
        return 'PMA'
    try:
        from screening import list_category as lc
        code = lc.for_match(m)
        if code:
            return code
    except Exception:
        pass
    if lt == 'PEP' or 'pep' in src:
        return 'PEP'
    if lt in ('TERROR', 'TERRORIST'):
        return 'TERROR'
    return 'SANCTIONS'          # official sanctions lists (UN, OFAC, EU, UK ...)


def _tier(m):
    d = (m or {}).get('decision') or {}
    t = d.get('tier')
    if t:
        return t
    s = float((m or {}).get('match_score') or 0)
    return 'CONFIRMED' if s >= mi.CONFIRMED else 'POTENTIAL' if s >= mi.POTENTIAL else 'LOW' if s >= mi.LOW else 'BELOW'


def action_for(m, table=None):
    """{'list_type', 'list_label', 'code', 'label', 'step'} (each text as {'en', 'ar'})."""
    ltype = list_type_of(m)
    tbl = table if table is not None else action_table()
    code = tbl.get(ltype) or DEFAULT_TABLE.get(ltype) or 'REVIEW'
    a = ACTIONS.get(code) or ACTIONS['REVIEW']
    tier = _tier(m)
    if (m or {}).get('legal_status') == 'LIFTED' or str((m or {}).get('legal_status') or '').upper() == 'LIFTED':
        step = ('The listing was lifted (إنهاء أثر): no freeze on this record; record the review and check for other active listings.',
                'الإدراج ده اتنهى أثره: مفيش تجميد على السجل ده؛ سجّل المراجعة واتأكد مفيش إدراج تاني ساري.')
    elif tier == 'CONFIRMED':
        step = a['CONFIRMED']
    elif tier == 'POTENTIAL':
        step = a['POTENTIAL']
    else:
        step = LOW_STEP
    lab = LIST_TYPE_LABEL.get(ltype, (ltype, ltype))
    return {'list_type': ltype, 'list_label': {'en': lab[0], 'ar': lab[1]}, 'code': code,
            'label': {'en': a['label'][0], 'ar': a['label'][1]}, 'step': {'en': step[0], 'ar': step[1]},
            'tier': tier}


# --------------------------------------------------------------------------- G9 identity
def identity_status(m, provided=None):
    """Whether identity can be verified for this hit and, if not, the next step.
    provided: {'dob': bool, 'nid': bool, 'nationality': bool} given by the customer."""
    m = m or {}
    d = m.get('decision') or {}
    provided = provided or {}
    ident = d.get('identity')
    if ident == 'id_match':
        return {'state': 'verified', 'en': 'Identity verified: an identifier agrees.', 'ar': 'الهوية متأكدة: معرّف مطابق.'}
    if ident in ('id_conflict', 'dob_conflict'):
        return {'state': 'conflict', 'en': 'An identifier contradicts the listed record: record why it is a different person.',
                'ar': 'معرّف بيتعارض مع السجل المدرج: سجّل ليه ده شخص مختلف.'}
    if d.get('identifier_match') or ident == 'corroborated':
        return {'state': 'supported', 'en': 'Supported by an identifier (birth date / country); not proof on its own.',
                'ar': 'مدعوم بمعرّف (تاريخ ميلاد / دولة)؛ مش دليل كافي لوحده.'}
    listed_has = any(m.get(k) for k in ('national_id', 'national_id_numbers', 'date_of_birth', 'year_of_birth',
                                         'passport_number', 'passport_numbers'))
    cust_has = bool(provided.get('dob') or provided.get('nid'))
    if not cust_has and listed_has:
        return {'state': 'not_verifiable', 'en': 'Identity not verifiable: the customer\'s national ID / date of birth was not given. '
                'Next step: obtain them and compare with the listed record before deciding.',
                'ar': 'الهوية مش قابلة للتحقق: الرقم القومي / تاريخ الميلاد للعميل مش موجودين. الخطوة الجاية: هاتهم وقارنهم بالسجل المدرج قبل القرار.'}
    if cust_has and not listed_has:
        return {'state': 'not_verifiable', 'en': 'Identity not verifiable: the listed record carries no identifiers. '
                'Next step: compare other details (address, occupation, relatives, photo / documents from the source) and record the basis of the decision.',
                'ar': 'الهوية مش قابلة للتحقق: السجل المدرج مفيهوش معرّفات. الخطوة الجاية: قارن بيانات تانية (عنوان، مهنة، أقارب، صور / مستندات من المصدر) وسجّل أساس القرار.'}
    if not cust_has and not listed_has:
        return {'state': 'not_verifiable', 'en': 'Identity not verifiable: no identifiers on either side; the decision rests on name and country. '
                'Next step: obtain the customer\'s ID documents and check the list source for more details.',
                'ar': 'الهوية مش قابلة للتحقق: مفيش معرّفات عند الطرفين؛ القرار على الاسم والدولة بس. الخطوة الجاية: هات مستندات هوية العميل وراجع مصدر القايمة لتفاصيل أكتر.'}
    return {'state': 'unknown', 'en': 'Identifiers on both sides could not be compared: verify manually.',
            'ar': 'المعرّفات عند الطرفين ماتقارنتش: اتحقق يدوياً.'}


# --------------------------------------------------------------------------- P4-2 explanation
def _pair_kind(listed, screened):
    if listed == screened:
        return 'same'
    if mi.is_arabic(listed) != mi.is_arabic(screened):
        return 'translit'
    return 'variant'


def explain(m, provided=None):
    """{'en': [...], 'ar': [...]} short lines explaining why this record was returned."""
    m = m or {}
    d = m.get('decision') or {}
    en, ar = [], []
    nm = d.get('name') or {}
    pairs = nm.get('matched') or []
    if pairs:
        kinds = [_pair_kind(str(a), str(b)) for a, b in pairs]
        n_same, n_tr, n_var = kinds.count('same'), kinds.count('translit'), kinds.count('variant')
        parts_en, parts_ar = [], []
        if n_same:
            parts_en.append(f'{n_same} identical'); parts_ar.append(f'{n_same} متطابق')
        if n_tr:
            parts_en.append(f'{n_tr} by transliteration (Arabic / Latin)'); parts_ar.append(f'{n_tr} بالنقل بين العربي واللاتيني')
        if n_var:
            parts_en.append(f'{n_var} as a spelling variant or typo'); parts_ar.append(f'{n_var} كاختلاف هجاء أو خطأ كتابة')
        en.append(f"Name elements matched: {len(pairs)} ({', '.join(parts_en)}).")
        ar.append(f"مقاطع الاسم المتطابقة: {len(pairs)} ({'، '.join(parts_ar)}).")
        if nm.get('complete'):
            en.append('The full name matches, in the same order.'); ar.append('الاسم كامل متطابق وبنفس الترتيب.')
        elif nm.get('order_ok') is False:
            en.append('The name elements appear in a different order.'); ar.append('مقاطع الاسم بترتيب مختلف.')
        miss = nm.get('missing_from_query') or []
        extra = nm.get('extra_in_query') or []
        if miss:
            en.append('Listed name has element(s) the customer name lacks: ' + ' '.join(map(str, miss[:4])) + '.')
            ar.append('الاسم المدرج فيه مقاطع مش في اسم العميل: ' + ' '.join(map(str, miss[:4])) + '.')
        if extra:
            en.append('Customer name has element(s) not in the listed name: ' + ' '.join(map(str, extra[:4])) + '.')
            ar.append('اسم العميل فيه مقاطع مش في الاسم المدرج: ' + ' '.join(map(str, extra[:4])) + '.')
    elif d:
        en.append('Matched on the name (no element detail stored).'); ar.append('التطابق على الاسم (من غير تفاصيل المقاطع).')
    else:
        en.append(f"Name similarity {float(m.get('match_score') or 0):.0f}%."); ar.append(f"تشابه الاسم {float(m.get('match_score') or 0):.0f}%.")
    c = d.get('country')
    if c == 'agree':
        en.append('Nationality / country agrees.'); ar.append('الجنسية / الدولة متطابقة.')
    elif c == 'differ':
        en.append('Nationality differs (does not lower the name score).'); ar.append('الجنسية مختلفة (مش بتقلل درجة الاسم).')
    dob = d.get('dob')
    if dob == 'agree':
        en.append('Date / year of birth agrees.'); ar.append('تاريخ / سنة الميلاد متطابقة.')
    elif dob == 'differ':
        en.append('Date of birth differs.'); ar.append('تاريخ الميلاد مختلف.')
    ident = d.get('identity')
    if ident == 'id_match':
        en.append('An identifier (national ID / passport) matches the listed record.'); ar.append('معرّف (رقم قومي / جواز) مطابق للسجل المدرج.')
    elif ident == 'id_conflict':
        en.append('The listed record carries a different national ID.'); ar.append('السجل المدرج عليه رقم قومي مختلف.')
    if d.get('gender') == 'differ':
        en.append('Gender differs (information only).'); ar.append('النوع مختلف (للعلم فقط).')
    wa = d.get('weak_alias')
    if isinstance(wa, dict):
        if wa.get('state') == 'capped':
            en.append('Matched only through a weak / short alias: kept below the alert threshold.')
            ar.append('التطابق عن طريق اسم بديل ضعيف / قصير بس: فضل تحت حد التنبيه.')
        else:
            en.append('Matched through a weak alias, kept because an identifier agrees.')
            ar.append('التطابق عن طريق اسم بديل ضعيف، واتساب لأن معرّف مطابق.')
    if str(m.get('legal_status') or '').upper() == 'LIFTED':
        en.append('This listing was lifted (إنهاء أثر); the record is kept for history.')
        ar.append('الإدراج ده اتنهى أثره؛ السجل محفوظ للتاريخ.')
    lt = list_type_of(m)
    lab = LIST_TYPE_LABEL.get(lt, (lt, lt))
    en.append(f'List type: {lab[0]}.'); ar.append(f'نوع القايمة: {lab[1]}.')
    return {'en': en[:9], 'ar': ar[:9]}


def annotate(matches, provided=None):
    """Attach 'workflow' (explanation, action, identity status) to every hit. Never removes a hit."""
    try:
        table = action_table()
    except Exception:
        table = dict(DEFAULT_TABLE)
    for m in matches or []:
        if not isinstance(m, dict):
            continue
        try:
            m['workflow'] = {'explanation': explain(m, provided), 'action': action_for(m, table),
                             'identity_status': identity_status(m, provided)}
        except Exception as e:
            logger.warning('[WORKFLOW] annotate failed: %s', e)
    return matches


def view(m, inputs=None):
    """The workflow block for a stored hit (computed for results saved before Phase 4)."""
    w = (m or {}).get('workflow')
    if isinstance(w, dict) and w.get('action'):
        return w
    inputs = inputs or {}
    provided = {'dob': bool(inputs.get('dob')), 'nid': bool(inputs.get('national_id')),
                'nationality': bool(inputs.get('nationality'))}
    try:
        return {'explanation': explain(m, provided), 'action': action_for(m),
                'identity_status': identity_status(m, provided)}
    except Exception as e:
        logger.warning('[WORKFLOW] view failed: %s', e)
        return None
