"""Labels are never double-escaped or broken ('View &amp;amp; Edit', 'View & &dit', '&&'), and permission levels
use one vocabulary (No access / View / View & Edit / Admin). Static checks of the catalogue, templates and
Python; the rendered pages are checked by tests/test_access/test_access_db.py and scripts/route_crawl.py."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BAD = re.compile(r'&amp;(amp|lt|gt|quot|#\d+);|(?<![&\w])& &|&&')


def _po_entries():
    path = os.path.join(ROOT, 'translations', 'ar', 'LC_MESSAGES', 'messages.po')
    text = open(path, encoding='utf-8').read()
    for block in text.split('\n\n'):
        if block.lstrip().startswith('#~'):
            continue
        mid = ''.join(re.findall(r'^(?:msgid )?"(.*)"$', block.split('msgstr')[0], re.M))
        mstr = ''.join(re.findall(r'^(?:msgstr )?"(.*)"$', block.split('msgstr', 1)[1], re.M)) if 'msgstr' in block else ''
        yield mid, mstr


def test_catalogue_has_no_broken_ampersands():
    bad = []
    for mid, mstr in _po_entries():
        if not mid:            # header (plural forms use '&&')
            continue
        for s in (mid, mstr):
            if BAD.search(s):
                bad.append((mid[:60], mstr[:60]))
        # an escaped entity in the English text must not turn into a bare '&' in the translation (or back)
        if '&amp;' in mid and re.search(r'&(?!amp;|[a-z]+;|#\d+;)', mstr):
            bad.append((mid[:60], mstr[:60]))
    assert not bad, bad[:10]


def test_templates_never_filter_or_reescape_an_escaped_label():
    bad = []
    for base, _d, files in os.walk(os.path.join(ROOT, 'templates')):
        for f in files:
            if not f.endswith('.html'):
                continue
            p = os.path.join(base, f)
            src = open(p, encoding='utf-8').read()
            # _('… &amp; …')|label / |e / |title … turns the Markup into text and escapes it again
            for m in re.finditer(r"_\('[^']*&amp;[^']*'\)\s*\|\s*(\w+)", src):
                bad.append((os.path.relpath(p, ROOT), m.group(0)[:80]))
            for m in re.finditer(r"&amp;amp;", src):
                bad.append((os.path.relpath(p, ROOT), 'literal &amp;amp;'))
    assert not bad, bad


def test_python_messages_carry_no_html_entities():
    """_l('A &amp; B') in Python is plain text: the template escapes it again ('A &amp;amp; B')."""
    bad = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ('.git', 'venv', 'node_modules', 'tests', '__pycache__', 'static')]
        for f in files:
            if f.endswith('.py'):
                p = os.path.join(base, f)
                src = open(p, encoding='utf-8', errors='ignore').read()
                for m in re.finditer(r"\b(_l|_|gettext|lazy_gettext)\(\s*'[^']*&amp;[^']*'", src):
                    bad.append((os.path.relpath(p, ROOT), m.group(0)[:80]))
    assert not bad, bad


def test_one_vocabulary_for_permission_levels():
    from access.registry import level_label, LEVEL_LABELS
    assert [level_label(k) for k in ('none', 'view', 'edit', 'admin')] == ['No access', 'View', 'View & Edit', 'Admin']
    assert [level_label(k, 'ar') for k in ('none', 'view', 'edit', 'admin')] == ['لا وصول', 'عرض', 'عرض وتعديل',
                                                                               'إدارة الوحدة']
    assert level_label('use') == 'View & Edit' and level_label('approve') == 'Admin' and level_label(None) == 'No access'
    for en, ar in LEVEL_LABELS.values():
        assert not BAD.search(en) and not BAD.search(ar)
