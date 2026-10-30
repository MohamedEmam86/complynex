"""Company names (Phase 3, P3-6): generic business words that mean the same thing.

Two elements of the same class compare as the same element (Trade = Trading = تجارة,
Intl = International = دولية, Bank = Banque = مصرف = بنك ...).  Only generic words are listed;
the distinctive part of a company name is compared by the normal rules, and legal forms
(LLC, Ltd, ش.م.م ...) are already dropped by match_intel.
"""
_CLASSES = {
    'trade': ('trade', 'trading', 'trader', 'traders', 'تجاره', 'تجاريه',
              'للتجاره', 'تجارى', 'تجاري'),
    'international': ('international', 'intl', 'internacional', 'internationale', 'دوليه', 'دولي', 'دولى'),
    'organization': ('organization', 'organisation', 'org', 'organizacion', 'منظمه'),
    'industry': ('industry', 'industries', 'industrie', 'صناعه', 'صناعات', 'للصناعات', 'للصناعه'),
    'group': ('group', 'grp', 'groupe', 'grupo', 'مجموعه'),
    'holding': ('holding', 'holdings', 'hldg', 'hldgs', 'قابضه'),
    'bank': ('bank', 'banque', 'banco', 'banca', 'bankasi', 'بنك', 'مصرف', 'لمصرف'),
    'investment': ('investment', 'investments', 'استثمار', 'استثمارات', 'للاستثمار'),
    'services': ('service', 'services', 'svc', 'svcs', 'خدمات'),
    'technology': ('technology', 'technologies', 'tech', 'تكنولوجيا', 'تقنيه'),
    'manufacturing': ('manufacturing', 'manufacture', 'mfg', 'تصنيع'),
    'brothers': ('brothers', 'bros', 'اخوان'),
    'association': ('association', 'assoc', 'assn', 'جمعيه'),
    'center': ('center', 'centre', 'ctr', 'مركز'),
    'chemical': ('chemical', 'chemicals', 'كيماويات'),
    'general': ('general', 'genl', 'عامه'),
}
_INDEX = None


def _index():
    global _INDEX
    if _INDEX is None:
        from screening import match_intel as mi
        idx = {}
        for cls, words in _CLASSES.items():
            for w in words:
                for t in mi.tokens(w) or []:
                    idx.setdefault(t, cls)
                idx.setdefault(mi.normalize(w), cls)
        _INDEX = idx
    return _INDEX


def same_class(a, b):
    """True when two (normalised) elements are the same generic business word."""
    idx = _index()
    ca = idx.get(a)
    return ca is not None and ca == idx.get(b)
