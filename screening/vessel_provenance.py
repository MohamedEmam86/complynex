# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Why a ship is in the vessel tables (provenance), per list record.

Official lists (OFAC, UK, EU, UN, imported vessel lists) are sanctions by definition. An aggregated database
(OpenSanctions) also carries ships that are only there because of port-state-control inspections or
detentions, exclusion lists, or analytical / press material. Each of its datasets is classified:

    SANCTION  official sanctions, asset-freeze or terrorism lists               -> a sanctions hit
    BAN       port bans, procurement exclusions, forced-labour import bans      -> a separate, labelled alert
              ("access refused / excluded"), never called "sanctioned"
    RISK      port-state-control detentions and inspections                     -> a risk factor with a count,
              never a hit
    INTEL     analytical, graph or press-release material                       -> a risk note at most

A record takes the most serious class of its datasets. OpenSanctions topics ('sanction', 'crime.terror',
'debarment') decide only for a record whose datasets are all analytical (INTEL) or that has none. A dataset
nobody classified is RISK (safe: it can raise risk, never alert) and is logged so that someone classifies it.

The classification is data: DEFAULT_CLASSES below, overridden per dataset by screening_config
'vessel_dataset_classes' (JSON {dataset: class}). vessel_store.sync() stores the result on vessel_profile
(provenance, datasets, risk_datasets), so a change only needs `scripts/vessels_sync.py --sync`.
"""
import logging
import re

logger = logging.getLogger(__name__)

SANCTION, BAN, RISK, INTEL = 'SANCTION', 'BAN', 'RISK', 'INTEL'
ORDER = {SANCTION: 4, BAN: 3, RISK: 2, INTEL: 1}
CLASSES = (SANCTION, BAN, RISK, INTEL)
LABELS = {SANCTION: ('Sanctioned', 'خاضعة لعقوبات'),
          BAN: ('Banned / excluded (not a sanctions listing)', 'محظورة أو مستبعدة (ليست قائمة عقوبات)'),
          RISK: ('Port-state-control record only', 'سجل رقابة دولة الميناء فقط'),
          INTEL: ('Mentioned in analytical or press material', 'مذكورة في مواد تحليلية أو صحفية')}
CFG_KEY = 'vessel_dataset_classes'

# OpenSanctions datasets seen on ships (default collection, Nov 2026) and their class
DEFAULT_CLASSES = {
    # official sanctions / freezes / terrorism
    'us_ofac_sdn': SANCTION, 'us_ofac_cons': SANCTION, 'us_trade_csl': SANCTION, 'eu_fsf': SANCTION,
    'eu_journal_sanctions': SANCTION, 'eu_sanctions_map': SANCTION, 'gb_fcdo_sanctions': SANCTION,
    'gb_hmt_sanctions': SANCTION, 'un_sc_sanctions': SANCTION, 'un_1718_vessels': SANCTION,
    'ch_seco_sanctions': SANCTION, 'ca_dfatd_sema_sanctions': SANCTION, 'au_dfat_sanctions': SANCTION,
    'ua_war_sanctions': SANCTION, 'mc_fund_freezes': SANCTION, 'fr_tresor_gels_avoir': SANCTION,
    'be_fod_sanctions': SANCTION, 'sa_pcct_terrorism_list': SANCTION, 'ae_local_terrorists': SANCTION,
    'nz_russia_sanctions': SANCTION, 'jp_mof_sanctions': SANCTION,
    # bans and exclusions
    'paris_mou_banned': BAN, 'us_sam_exclusions': BAN, 'us_cbp_forced_labor': BAN,
    # port state control
    'tokyo_mou_detention': RISK, 'ext_tokyo_mou_psc': RISK, 'black_sea_mou_detention': RISK,
    'ext_black_sea_mou_psc': RISK, 'abuja_mou_detention': RISK, 'ext_abuja_mou_psc': RISK,
    'paris_mou_detention': RISK, 'indian_ocean_mou_detention': RISK,
    # analytical / press
    'ann_graph_topics': INTEL, 'kp_rusi_reports': INTEL, 'ext_us_ofac_press_releases': INTEL,
}

# name patterns for datasets not in the table (still logged as unclassified)
_PATTERNS = (
    (re.compile(r'(^|_)(mou|psc)(_|$)|detention|inspection'), RISK),
    (re.compile(r'press_release|_reports?$|^ann_|graph|research|media'), INTEL),
    (re.compile(r'banned|exclusion|debar|forced_labor'), BAN),
)

_UNCLASSIFIED_LOGGED = set()


def classes(conn=None):
    """{dataset: class}: DEFAULT_CLASSES with the screening_config overrides."""
    out = dict(DEFAULT_CLASSES)
    if conn is not None:
        try:
            from screening.vessel_store import config_json
            for k, v in (config_json(conn, CFG_KEY) or {}).items():
                v = str(v or '').upper()
                if v in CLASSES:
                    out[str(k)] = v
        except Exception as e:
            logger.warning(f'[VESSELS] dataset classes not readable: {e}')
    return out


def dataset_class(ds, table):
    """(class, known) of one dataset."""
    if ds in table:
        return table[ds], True
    for rx, cls in _PATTERNS:
        if rx.search(ds):
            return cls, False
    return RISK, False


def classify(source, datasets, topics, table=None, aggregated=('opensanctions', 'opensanctions_pep')):
    """{'class', 'datasets', 'risk_datasets', 'unclassified'} of one list record.
    A record of an official list (not an aggregated database) is SANCTION."""
    table = table if table is not None else DEFAULT_CLASSES
    datasets = sorted({str(d) for d in (datasets or []) if d})
    topics = {str(t) for t in (topics or []) if t}
    if str(source or '').lower() not in aggregated:
        return {'class': SANCTION, 'datasets': datasets, 'risk_datasets': [], 'unclassified': []}
    best, risk_ds, unknown = None, [], []
    for d in datasets:
        cls, known = dataset_class(d, table)
        if not known:
            unknown.append(d)
        if cls == RISK:
            risk_ds.append(d)
        if best is None or ORDER[cls] > ORDER[best]:
            best = cls
    # topics decide only for analytical material (INTEL) and for a record with no dataset at all: an
    # unclassified dataset stays RISK whatever its topics, and a ban never becomes a sanction through them
    if best in (None, INTEL):
        if topics & {'sanction', 'crime.terror'}:
            best = SANCTION
        elif 'debarment' in topics:
            best = BAN
    if best is None:
        best = RISK if (not topics or topics & {'mare.detained', 'reg.warn', 'mare.shadow'}) else INTEL
    for d in unknown:
        if d not in _UNCLASSIFIED_LOGGED:
            _UNCLASSIFIED_LOGGED.add(d)
            logger.warning(f'[VESSELS] dataset {d!r} is not classified: treated as {dataset_class(d, table)[0]} '
                           f'(set screening_config {CFG_KEY} to classify it)')
    return {'class': best, 'datasets': datasets, 'risk_datasets': risk_ds, 'unclassified': unknown}


def alerts(cls):
    """Does a record of this class produce a hit?"""
    return cls in (SANCTION, BAN)
