"""Whole-list exports are ComplyNex data: only administrators may download them (Phase 1, P1-1)."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUARDED = [('blacklist/routes.py', "route('/export')"),
           ('screening/routes.py', "route('/internal-pep/export')"),
           ('screening/pep_management/api.py', "route('/<int:pep_id>'")]


def test_full_list_routes_need_admin():
    for path, marker in GUARDED:
        src = open(os.path.join(ROOT, path), encoding='utf-8').read()
        i = src.index(marker)
        head = src[i:src.index('def ', i)]
        assert re.search(r"permission_required\('screening', level='admin'\)", head), path


def test_list_pages_cap_per_page():
    src = open(os.path.join(ROOT, 'blacklist/routes.py'), encoding='utf-8').read()
    assert "int(request.args.get('per_page', 50))" not in src.replace('min(max(int(request.args.get(\'per_page\', 50))', '')
    assert src.count('MAX_PER_PAGE)') >= 2 and 'MAX_PER_PAGE = 200' in src
