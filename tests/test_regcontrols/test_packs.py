"""Pack registry behaviour that needs no database."""
from regcontrols import packs
from regcontrols.packs import Pack


class FakeUser:
    def __init__(self, allowed):
        self.allowed = allowed

    def can_view(self, module):
        return module in self.allowed


def test_register_and_permission_modules(monkeypatch):
    p = Pack(code='demo_pack', name_en='Demo', permissions=[('demo_mod', 'Demo module', 'وحدة', ('none', 'view'))])
    packs.register_pack(p)
    try:
        assert ('demo_mod', 'Demo module', 'وحدة', ('none', 'view')) in packs.permission_modules()
    finally:
        packs.PACKS.pop('demo_pack')


def test_menus_only_for_enabled_packs_and_permitted_items(monkeypatch):
    p = Pack(code='demo_pack', name_en='Demo', menu=[('demo.a', 'A', 'أ', 'demo_mod'), ('demo.b', 'B', 'ب', None)])
    packs.register_pack(p)
    try:
        monkeypatch.setattr(packs, 'enabled_packs', lambda db=None: [p])
        m = packs.menus(FakeUser(set()))
        assert [i[0] for i in m[0]['items']] == ['demo.b']
        assert [i[0] for i in packs.menus(FakeUser({'demo_mod'}))[0]['items']] == ['demo.a', 'demo.b']
        monkeypatch.setattr(packs, 'enabled_packs', lambda db=None: [])
        assert packs.menus(FakeUser({'demo_mod'})) == []
    finally:
        packs.PACKS.pop('demo_pack')


def test_core_never_imports_a_pack():
    """Core modules must not reference a specific pack."""
    import glob
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    offenders = []
    for path in glob.glob(os.path.join(root, 'regcontrols', '*.py')) + glob.glob(os.path.join(root, 'templates', 'regcontrols', '*.html')):
        text = open(path, encoding='utf-8').read()
        if 'packs.fra_nbfi' in text or 'fra_nbfi' in text or 'FRA-' in text:
            offenders.append(os.path.basename(path))
    assert offenders == []
