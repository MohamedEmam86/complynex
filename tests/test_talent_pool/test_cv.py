import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    'tp_cv', os.path.join(os.path.dirname(__file__), '..', '..', 'packs', 'talent_pool', 'cv.py'))
cv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cv)

import pytest


class FS:
    def __init__(self, name, data):
        self.filename = name
        self.stream = io.BytesIO(data)


def pdf(extra=b''):
    return b'%PDF-1.7\n' + b'1 0 obj << /Type /Catalog >> endobj\n' * 10 + extra + b'\n%%EOF'


def docx(extra_files=None, ctype=b'<Types><Default Extension="xml" ContentType="application/xml"/></Types>'):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('[Content_Types].xml', ctype)
        z.writestr('word/document.xml', '<w:document>' + 'x' * 300 + '</w:document>')
        for n, d in (extra_files or {}).items():
            z.writestr(n, d)
    return b.getvalue()


def test_good_pdf_and_docx():
    assert cv.check(FS('Ahmed.Mostafa CV.pdf', pdf()))[1] == '.pdf'
    assert cv.check(FS('cv.docx', docx()))[1] == '.docx'


@pytest.mark.parametrize('name,data,key', [
    ('cv.exe', b'MZ' + b'0' * 500, 'type'),
    ('cv.pdf', b'MZ' + b'0' * 500, 'signature'),
    ('cv.exe.pdf', pdf(), 'double_ext'),
    ('cv.pdf', pdf(b'/OpenAction << /S /JavaScript /JS (app.alert(1)) >>'), 'active'),
    ('cv.pdf', pdf(b'/Launch /F (cmd.exe)'), 'active'),
    ('cv.pdf', pdf(b'/EmbeddedFile'), 'active'),
    ('cv.docx', docx({'word/vbaProject.bin': 'x'}), 'active'),
    ('cv.docx', docx({'word/embeddings/oleObject1.bin': 'x'}), 'active'),
    ('cv.docx', b'PK\x03\x04' + b'0' * 500, 'signature'),
    ('cv.pdf', b'%PDF-' + b'0' * (cv.MAX_BYTES + 10), 'size'),
    ('cv.pdf', b'%PDF-1', 'empty'),
    ('cv.docm', docx(), 'type'),
    ('cv.html', b'<script>' + b'x' * 400, 'type'),
])
def test_rejected(name, data, key):
    with pytest.raises(cv.CVError) as e:
        cv.check(FS(name, data))
    assert str(e.value) == key


def test_zip_bomb():
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', '0' * (cv.MAX_UNZIPPED + 1))
    with pytest.raises(cv.CVError) as e:
        cv.check(FS('cv.docx', b.getvalue()))
    assert str(e.value) == 'size'


def test_store_and_remove(tmp_path):
    rel, sha, size = cv.store(str(tmp_path), pdf(), '.pdf')
    assert rel.startswith(cv.STORE_DIR) and rel.endswith('.pdf') and size > 0
    assert os.path.exists(tmp_path / rel)
    assert oct(os.stat(tmp_path / rel).st_mode)[-3:] == '640'
    assert not cv.remove(str(tmp_path), '../../etc/passwd')
    assert cv.remove(str(tmp_path), rel)
