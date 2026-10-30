"""
What kind of record an aggregated-database hit is (Phase 2, G1).

OpenSanctions mixes real sanctions with PEPs, criminal / wanted lists, debarments, regulatory
warnings, trade-risk research and plain background data (company registers, ship detentions,
Wikidata). Before this, every OpenSanctions record without a PEP topic was shown as a sanctions
hit with the instruction to freeze funds. Each record now gets a category from its topics (and,
when it has none, from its dataset), with a note in Arabic on what the record is and an action
that fits it.

  kind  - which section of the result the hit goes to and whether the sanctions four-eyes rule
          applies: 'SANCTIONS' (also criminal / wanted and links to sanctioned parties: the strict
          path), 'PEP', or 'OTHER' (debarment, regulatory, trade risk, person of interest,
          background data).
"""
import json

# category -> kind, Arabic label, Arabic note on what the record is, action (English, translated in the UI)
CATEGORY = {
    'SANCTIONS': ('SANCTIONS', 'عقوبات / تجميد أموال',
                  'مدرج على قايمة عقوبات أو تجميد رسمية.', None),
    'TERROR': ('SANCTIONS', 'إرهاب',
               'مدرج كإرهابي أو منظمة إرهابية في قايمة رسمية.', None),
    'SANCTION_LINKED': ('SANCTIONS', 'مرتبط بجهة معاقبة',
                        'مش مدرج بنفسه، لكنه مرتبط بجهة معاقبة (ملكية أو سيطرة أو علاقة). التجميد بيتطبق لو مملوك أو مسيطر عليه من الجهة المعاقبة.',
                        'Linked to a sanctioned party: establish ownership and control (50% rule). Freeze only if owned or controlled by the sanctioned party; otherwise enhanced due diligence. MLRO decides.'),
    'CRIME': ('SANCTIONS', 'جرائم / مطلوب',
              'مذكور في قايمة جنائية أو قايمة مطلوبين (شرطة / نيابة / إنتربول). ده مش أمر تجميد.',
              'Criminal or wanted record, not a freeze order: confirm identity, enhanced due diligence, consider a suspicious transaction report. MLRO decides.'),
    'PEP': ('PEP', 'شخص سياسي ممثل للمخاطر (PEP)',
            'شخص في منصب عام بارز أو من أقاربه / المقربين منه.', None),
    'EXPORT_CONTROL': ('OTHER', 'قيود تصدير',
                       'على قايمة قيود تصدير (زي Entity List الأمريكية). مش تجميد أموال.',
                       'Export-control listing, not an asset freeze: enhanced due diligence on the business and the goods or services involved.'),
    'DEBARMENT': ('OTHER', 'حرمان / استبعاد',
                  'محروم من التعاقد مع جهة حكومية أو دولية، أو ممنوع من إدارة شركات. مش عقوبات مالية.',
                  'Debarment or disqualification, not a sanction: record it and consider it in the customer risk rating.'),
    'REG_ACTION': ('OTHER', 'إجراء أو تحذير رقابي',
                   'إجراء أو تحذير صادر من جهة رقابية مالية. مش تجميد أموال.',
                   'Regulatory action or warning, not a freeze order: enhanced due diligence and record the measure.'),
    'TRADE_RISK': ('OTHER', 'مخاطر تجارية / عمل قسري',
                   'وارد في أبحاث أو قوايم مخاطر تجارة (عمل قسري، سلاسل توريد). مش قايمة عقوبات.',
                   'Trade-risk research, not a sanctions list: consider it in the risk assessment.'),
    'POI': ('OTHER', 'شخص محل اهتمام',
            'شخص محل اهتمام في مصادر عامة، من غير إدراج على قايمة عقوبات.',
            'Person of interest, not a listing: review and record the conclusion.'),
    'COUNTER_SANCTIONS': ('OTHER', 'عقوبات مضادة',
                          'مدرج على قايمة عقوبات مضادة (زي قوايم روسيا أو الصين ضد أشخاص وشركات غربية). مش ملزمة في مصر، ومش أمر تجميد.',
                          'Counter-sanctions listing (e.g. Russia or China against Western persons): not binding in Egypt; record it and consider it in the risk assessment.'),
    'UNCLASSIFIED': ('SANCTIONS', 'غير مصنف - يعامل كعقوبات',
                     'السجل من غير تصنيف واضح في المصدر، فبيتعامل كعقوبات لحد ما يتراجع.', None),
    'CONTEXT': ('OTHER', 'بيانات خلفية - مش قايمة',
                'بيانات مرجعية (سجل شركات، ملكية، سفن، ويكي بيانات) جت ضمن قاعدة OpenSanctions. مش إدراج على أي قايمة، وده مش أمر تجميد.',
                'Background data, not a list hit: use it only as context for due diligence.'),
}

DATASET_NOTE = {
    'ext_ru_egrul': 'سجل الشركات الروسي (EGRUL)',
    'shu_uyghur_companies': 'بحث جامعة شيفيلد هالام عن شركات مرتبطة بإقليم شينجيانغ',
    'gem_energy_ownership': 'بيانات ملكية شركات الطاقة (Global Energy Monitor)',
    'wikidata': 'ويكي بيانات (Wikidata)',
    'ru_nsd_isin': 'سجل الأوراق المالية الروسي (NSD)',
    'c4ads_xinjiang_mining': 'بحث C4ADS عن التعدين في شينجيانغ',
    'kp_rusi_reports': 'تقارير RUSI عن كوريا الشمالية',
    'tokyo_mou_detention': 'احتجاز سفن - مذكرة طوكيو',
    'ext_black_sea_mou_psc': 'تفتيش سفن - مذكرة البحر الأسود',
    'black_sea_mou_detention': 'احتجاز سفن - مذكرة البحر الأسود',
    'abuja_mou_detention': 'احتجاز سفن - مذكرة أبوجا',
    'no_brreg': 'سجل الشركات النرويجي',
    'permid': 'معرّفات شركات (Refinitiv PermID)',
    'gb_coh_disqualified': 'مديرين ممنوعين من إدارة الشركات - بريطانيا',
    'me_acp_peps': 'إقرارات ذمة مالية لمسؤولين - الجبل الأسود',
    'ge_declarations': 'إقرارات ذمة مالية لمسؤولين - جورجيا',
}

ORDER = ['SANCTIONS', 'TERROR', 'UNCLASSIFIED', 'SANCTION_LINKED', 'CRIME', 'PEP', 'EXPORT_CONTROL',
         'COUNTER_SANCTIONS', 'DEBARMENT', 'REG_ACTION', 'TRADE_RISK', 'POI', 'CONTEXT']
AGGREGATED_SOURCES = ('opensanctions', 'opensanctions_pep')


def _topic_cat(t):
    if t in ('sanction', 'asset.frozen'):
        return 'SANCTIONS'
    if t == 'sanction.counter':
        return 'COUNTER_SANCTIONS'
    if t == 'crime.terror':
        return 'TERROR'
    if t in ('sanction.linked', 'sanction.control'):
        return 'SANCTION_LINKED'
    if t.startswith('crime') or t == 'wanted':
        return 'CRIME'
    if t.startswith('role.'):
        return 'PEP'
    if t in ('export.control', 'export.control.linked'):
        return 'EXPORT_CONTROL'
    if t in ('debarment', 'corp.disqual'):
        return 'DEBARMENT'
    if t.startswith('reg.'):
        return 'REG_ACTION'
    if t in ('export.risk', 'forced.labor', 'mil'):
        return 'TRADE_RISK'
    if t == 'poi':
        return 'POI'
    return 'CONTEXT'


# datasets whose name does not say what they are, or says it misleadingly
DATASET_CAT = {
    'il_mod_crypto': 'TERROR', 'in_mha_banned': 'TERROR',
    'li_entsg': 'SANCTIONS', 'us_trade_csl': 'SANCTIONS', 'us_special_leg': 'SANCTIONS',
    'us_state_cuba_restricted': 'SANCTIONS', 'us_fincen_special_measures': 'SANCTIONS',
    'iadb_sanctions': 'DEBARMENT', 'wb_debarred': 'DEBARMENT', 'adb_sanctions': 'DEBARMENT',
    'afdb_sanctions': 'DEBARMENT', 'ebrd_ineligible': 'DEBARMENT',
    'au_abf_sanctioned_sponsors': 'REG_ACTION', 'us_ofac_enforcement_actions': 'REG_ACTION', 'us_fda_restricted': 'REG_ACTION', 'ae_dfsa_prohibited': 'REG_ACTION',
    'ch_parlament': 'PEP', 'ann_pep_positions': 'PEP',
    'ru_cbr_banks': 'CONTEXT', 'eiti_soe': 'CONTEXT', 'us_occ_enfact': 'REG_ACTION',
    'opensanctions': 'UNCLASSIFIED',
}
# background data: registers, ownership, ships, reference data (never a listing on its own)
CONTEXT_PREFIXES = ('ext_', 'gem_', 'wikidata', 'wd_', 'permid', 'research', 'brightquery', 'iso9362',
                    'ru_nsd_isin', 'kp_rusi_reports', 'thesentry_atlas', 'md_rise_profiles', 'se_soe',
                    'ir_uani_business_registry', 'ann_graph_topics', 'opencorporates', 'gleif')


def _dataset_cat(ds):
    d = str(ds or '').strip().lower()
    if d in DATASET_CAT:
        return DATASET_CAT[d]
    if 'terror' in d:
        return 'TERROR'
    if 'sanction' in d or 'freezes' in d or 'gels' in d or 'interdictie' in d or 'blacklist' in d \
            or 'proscribed' in d or 'travel_ban' in d or 'fsf' in d or 'ofac' in d or 'fiu' in d:
        return 'SANCTIONS'
    if 'exclusions' in d or 'debarred' in d or 'disqualified' in d:
        return 'DEBARMENT'
    if 'enforcement' in d or 'saris' in d:
        return 'REG_ACTION'
    if 'wanted' in d or 'press_releases' in d:
        return 'CRIME'
    if 'pep' in d or 'declarations' in d or 'parlament' in d or 'officials' in d:
        return 'PEP'
    if 'forced_labor' in d or 'xinjiang' in d or 'uyghur' in d:
        return 'TRADE_RISK'
    if d.startswith(CONTEXT_PREFIXES) or '_mou_' in d or 'mou_detention' in d or d.endswith('_brreg') \
            or d.endswith('brreg') or 'company_registry' in d or 'business_register' in d or d.endswith('_companies'):
        return 'CONTEXT'
    return 'UNCLASSIFIED'      # unknown: the strict side until someone classifies the dataset


def topics_list(v):
    if isinstance(v, (list, tuple)):
        return [str(x).strip().lower() for x in v if str(x).strip()]
    s = str(v or '').strip()
    if s.startswith('['):
        try:
            return [str(x).strip().lower() for x in json.loads(s) if str(x).strip()]
        except ValueError:
            pass
    return [x.strip().strip('"\'').lower() for x in s.strip('[]{}').split(',')
            if x.strip().strip('"\'') and x.strip().strip('"\'').lower() not in ('none', 'null')]


def _worst(cats):
    return min(cats, key=ORDER.index)


def categorize(topics, dataset=None):
    """Category code for an aggregated-database record (the most serious wins).
    `dataset` may be one dataset name or a list (an entity can be in several)."""
    cats = {_topic_cat(t) for t in topics_list(topics)}
    dss = dataset if isinstance(dataset, (list, tuple)) else ([dataset] if dataset else [])
    dcats = {_dataset_cat(d) for d in dss}
    if not cats or cats == {'CONTEXT'}:
        if dcats:
            return _worst(dcats | cats)
        return 'CONTEXT' if cats else 'UNCLASSIFIED'
    # topics are the source's own classification; a dataset that is itself a sanctions list still counts
    return _worst(cats | ({c for c in dcats if c in ('SANCTIONS', 'TERROR')}))


def for_match(m):
    """Category code for a hit, or None when the source is not an aggregated database."""
    m = m or {}
    src = str(m.get('source') or '').strip().lower()
    if src not in AGGREGATED_SOURCES:
        return None
    lt = str(m.get('list_type') or '').strip().upper()
    has_data = bool(topics_list(m.get('topics'))) or bool(str(m.get('dataset') or '').strip())
    if has_data:
        code = categorize(m.get('topics'), m.get('dataset'))
        # a category stored by the loader / migration (not the old generic labels) never gets milder
        if lt in CATEGORY and lt not in ('SANCTIONS', 'PEP'):
            code = _worst({code, lt})
    elif lt in CATEGORY:
        code = lt
    else:
        code = 'UNCLASSIFIED'
    if src == 'opensanctions_pep' and code in ('CONTEXT', 'UNCLASSIFIED', 'POI'):
        code = 'PEP'       # the PEP feed: a record without topics is still a PEP entry
    return code


def nature(m):
    """{'code', 'kind', 'label', 'note', 'action'} for a hit from an aggregated database, else None."""
    code = for_match(m)
    if not code:
        return None
    kind, label, note, action = CATEGORY[code]
    ds = str((m or {}).get('dataset') or '').strip().lower()
    if ds in DATASET_NOTE:
        note = f'{note} المصدر: {DATASET_NOTE[ds]}.'
    elif ds:
        note = f'{note} المصدر داخل OpenSanctions: {ds}.'
    return {'code': code, 'kind': kind, 'label': label, 'note': note, 'action': action}
