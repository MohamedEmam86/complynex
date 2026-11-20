# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Generic sanctions regimes of a listed ship (Russia-related, Iran-related, DPRK-related, counter-terrorism ...).

The officer must see WHAT a ship is and UNDER WHICH KIND OF REGIME it is listed, without the publishing
authority (owner decision: only the superadmin sees list names). The lists' own programme codes and regulation
titles ("RUSSIA-EO14024", "GB-RUS", "The Russia (Sanctions) (EU Exit) Regulations 2019", "UN-SC1718") carry the
authority, so they are mapped here to generic regime codes and only those are ever shown. A code that maps to
nothing (e.g. a law covering several regimes) gives no regime rather than a guess.
"""
import re

REGIMES = {
    'RUSSIA': ('Russia-related', 'مرتبطة بروسيا'),
    'IRAN': ('Iran-related', 'مرتبطة بإيران'),
    'DPRK': ('North Korea (DPRK)-related', 'مرتبطة بكوريا الشمالية'),
    'SYRIA': ('Syria-related', 'مرتبطة بسوريا'),
    'VENEZUELA': ('Venezuela-related', 'مرتبطة بفنزويلا'),
    'CUBA': ('Cuba-related', 'مرتبطة بكوبا'),
    'LIBYA': ('Libya-related (illicit petroleum exports)', 'مرتبطة بليبيا (تصدير غير مشروع للنفط)'),
    'BELARUS': ('Belarus-related', 'مرتبطة ببيلاروسيا'),
    'MYANMAR': ('Myanmar-related', 'مرتبطة بميانمار'),
    'YEMEN': ('Yemen-related', 'مرتبطة باليمن'),
    'TERRORISM': ('Counter-terrorism', 'مكافحة الإرهاب'),
    'PROLIFERATION': ('Weapons of mass destruction proliferation', 'انتشار أسلحة الدمار الشامل'),
    'NARCOTICS': ('Narcotics trafficking', 'الاتجار بالمخدرات'),
    'HUMAN_RIGHTS': ('Human rights abuse / corruption', 'انتهاكات حقوق الإنسان / الفساد'),
    'CYBER': ('Malicious cyber activity', 'أنشطة سيبرانية ضارة'),
}

# (pattern over the upper-cased programme code / regulation title, regime)
_RULES = [
    (r'RUS(SIA)?\b|RUSHAR|\bRUS-|UKRAINE|UKRRUS|PEESA|EU-MARE|\bRUSSIA\b', 'RUSSIA'),
    (r'IRAN|\bIFSR\b|IRGC', 'IRAN'),
    (r'DPRK|-NK\b|^PRK$|-PRK\b|NORTH ?KOREA|NORTHKOREA|KOREA, DEMOCRATIC|SC ?1718|RESOLUTION 1718|DEMOCRATIC PEOPLE', 'DPRK'),
    (r'SYRIA|-SYR?\b', 'SYRIA'),
    (r'VENEZUELA|-VEN\b', 'VENEZUELA'),
    (r'CUBA', 'CUBA'),
    (r'LIBYA|-LBY\b|SC ?1970|RESOLUTION 2146|RESOLUTION 1970', 'LIBYA'),
    (r'BELARUS|-BLR\b', 'BELARUS'),
    (r'MYANMAR|BURMA', 'MYANMAR'),
    (r'YEMEN|HOUTHI', 'YEMEN'),
    (r'\bSDGT\b|\bSDT\b|-TERR\b|TERRORIS|1373\b|\bISIL\b|AL-?QAIDA|1267\b', 'TERRORISM'),
    (r'NPWMD|NON-?PROLIF|PROLIFERATION', 'PROLIFERATION'),
    (r'NARCO|ILLICIT-DRUGS|SDNTK', 'NARCOTICS'),
    (r'GLOMAG|HUMAN RIGHTS|MAGNITSKY|CORRUPTION', 'HUMAN_RIGHTS'),
    (r'CYB', 'CYBER'),
]
_COMPILED = [(re.compile(p), r) for p, r in _RULES]


def regimes_of(*texts, topics=()):
    """Generic regime codes found in programme codes / regulation titles / remarks (sorted)."""
    out = set()
    for t in texts:
        items = t if isinstance(t, (list, tuple, set)) else [t]
        for x in items:
            s = str(x or '').upper()
            if not s:
                continue
            for rx, code in _COMPILED:
                if rx.search(s):
                    out.add(code)
    if 'crime.terror' in set(topics or ()):
        out.add('TERRORISM')
    return sorted(out)


def label(code, lang='en'):
    pair = REGIMES.get(code)
    if not pair:
        return code
    return pair[1] if lang == 'ar' else pair[0]
