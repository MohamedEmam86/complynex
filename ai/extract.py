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

"""Text from an uploaded document — on this server only.

* plain text / e-mail / HTML / CSV and .docx with the standard library;
* the PDF text layer with pypdf (or pdfminer when that is what is installed);
* scanned PDFs and images with the LOCAL Tesseract binary (`tesseract`,
  Arabic + English when the `ara` language data is installed). A scanned
  PDF is rendered to images only when a local renderer (`pdftoppm`, from
  poppler-utils) exists.

Nothing is sent anywhere and no language data is downloaded: when a tool is
missing the result says so and the user pastes the text. Every result
records the method that produced the text: text | pypdf | ocr | none.
"""

import email
import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from email import policy

MAX_CHARS = 20000
MAX_OCR_PAGES = 15
OCR_TIMEOUT_S = 120
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.gif', '.webp')
METHODS = ('text', 'pypdf', 'ocr', 'none')
_MIN_TEXT_PER_PAGE = 25         # fewer non-space characters per page: the PDF is treated as scanned


def _html(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s))


def _result(text, method, note=None):
    text = (text or '').strip()
    return {'text': text[:MAX_CHARS], 'method': method if text else 'none', 'note': note}


# ------------------------------------------------------------------ local OCR (Tesseract)
def ocr_available():
    """{'tesseract': path|None, 'pdftoppm': path|None, 'langs': 'ara+eng'|'ara'|'eng'|None}. No network."""
    tess = shutil.which('tesseract')
    out = {'tesseract': tess, 'pdftoppm': shutil.which('pdftoppm'), 'langs': None}
    if tess:
        try:
            r = subprocess.run([tess, '--list-langs'], capture_output=True, text=True, timeout=15)
            langs = set((r.stdout or '').split()) | set((r.stderr or '').split())
            out['langs'] = 'ara+eng' if {'ara', 'eng'} <= langs else ('ara' if 'ara' in langs else 'eng')
        except (OSError, subprocess.SubprocessError):
            out['langs'] = 'eng'
    return out


_STATUS = {'at': 0, 'value': None}


def ocr_status(ttl=600):
    """ocr_available() cached for the pages (the binary is checked again every `ttl` seconds)."""
    import time
    if _STATUS['value'] is None or time.monotonic() - _STATUS['at'] > ttl:
        _STATUS.update(at=time.monotonic(), value=ocr_available())
    return _STATUS['value']


def _lang_note(tools):
    return None if 'ara' in (tools.get('langs') or '') else 'OCR ran without Arabic language data (install tesseract-ocr-ara)'


def _tesseract(path, tools):
    r = subprocess.run([tools['tesseract'], path, 'stdout', '-l', tools.get('langs') or 'eng'],
                       capture_output=True, timeout=OCR_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or b'').decode('utf-8', 'replace')[:200] or 'tesseract failed')
    out = r.stdout or b''
    return out.decode('utf-8', 'replace') if isinstance(out, bytes) else out


def ocr_image(data, suffix='.png', tools=None):
    """OCR one image with the local tesseract. → (text, note)."""
    tools = tools or ocr_available()
    if not tools['tesseract']:
        return '', 'OCR is not available on this server (install tesseract-ocr and tesseract-ocr-ara): paste the text'
    with tempfile.TemporaryDirectory(prefix='cnx_ocr_') as d:
        p = os.path.join(d, 'page' + (suffix if (suffix or '').startswith('.') else '.png'))
        with open(p, 'wb') as fh:
            fh.write(data)
        try:
            text = _tesseract(p, tools)
        except (OSError, subprocess.SubprocessError, RuntimeError) as e:
            return '', f'OCR failed ({e.__class__.__name__}): paste the text'
    return text.strip(), _lang_note(tools)


def ocr_pdf(data, tools=None):
    """Render the pages with the local pdftoppm and OCR them. → (text, note)."""
    tools = tools or ocr_available()
    if not tools['tesseract'] or not tools['pdftoppm']:
        missing = ', '.join(n for n, k in (('tesseract-ocr', 'tesseract'), ('poppler-utils', 'pdftoppm')) if not tools[k])
        return '', f'scanned PDF: OCR is not possible on this server ({missing} not installed): paste the text'
    with tempfile.TemporaryDirectory(prefix='cnx_ocr_') as d:
        src = os.path.join(d, 'in.pdf')
        with open(src, 'wb') as fh:
            fh.write(data)
        try:
            subprocess.run([tools['pdftoppm'], '-r', '200', '-png', '-l', str(MAX_OCR_PAGES), src, os.path.join(d, 'p')],
                           capture_output=True, timeout=OCR_TIMEOUT_S, check=True)
            pages = sorted(f for f in os.listdir(d) if f.startswith('p') and f.endswith('.png'))
            text = '\n'.join(_tesseract(os.path.join(d, f), tools) for f in pages)
        except (OSError, subprocess.SubprocessError, RuntimeError) as e:
            return '', f'OCR failed ({e.__class__.__name__}): paste the text'
    return text.strip(), _lang_note(tools)


# ------------------------------------------------------------------ PDF text layer
def _pdf_text(data):
    """→ (text, pages, reader) — reader is None when no PDF library is installed."""
    try:
        from pypdf import PdfReader
        pages = PdfReader(io.BytesIO(data)).pages
        return '\n'.join((p.extract_text() or '') for p in pages), len(pages), 'pypdf'
    except ImportError:
        pass
    try:
        from pdfminer.high_level import extract_text
        t = extract_text(io.BytesIO(data))
        return t, max(1, t.count('\f')), 'pdfminer'
    except ImportError:
        return '', 0, None


def is_scanned(text, pages):
    return len(re.sub(r'\s+', '', text or '')) < _MIN_TEXT_PER_PAGE * max(1, pages)


# ------------------------------------------------------------------ entry points
def extract(name, data):
    """→ {'text', 'method' (text|pypdf|ocr|none), 'note'}. Never raises for a bad file."""
    n = (name or '').lower()
    try:
        if n.endswith(('.txt', '.csv', '.md')):
            return _result(data.decode('utf-8', 'replace'), 'text')
        if n.endswith(('.html', '.htm')):
            return _result(_html(data.decode('utf-8', 'replace')), 'text')
        if n.endswith('.eml'):
            msg = email.message_from_bytes(data, policy=policy.default)
            body = msg.get_body(preferencelist=('plain', 'html'))
            content = body.get_content() if body else ''
            if body and body.get_content_type() == 'text/html':
                content = _html(content)
            return _result(f"Subject: {msg.get('subject', '')}\nFrom: {msg.get('from', '')}\n\n{content}", 'text')
        if n.endswith('.docx'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read('word/document.xml').decode('utf-8', 'replace')
            xml = re.sub(r'</w:p>', '\n', xml)
            return _result(re.sub(r'[ \t]+', ' ', re.sub(r'<[^>]+>', '', xml)), 'text')
        if n.endswith('.pdf'):
            text, pages, reader = _pdf_text(data)
            if reader and not is_scanned(text, pages):
                return _result(text, 'pypdf', 'read with pdfminer' if reader == 'pdfminer' else None)
            ocr_text, note = ocr_pdf(data)
            if ocr_text:
                return _result(ocr_text, 'ocr', note)
            if (text or '').strip():        # a thin text layer is better than nothing
                return _result(text, 'pypdf', note)
            if not reader:
                note = 'no PDF text reader is installed on this server (pip install pypdf); ' + (note or 'paste the text')
            return _result('', 'none', note)
        if n.endswith(IMAGE_EXT):
            text, note = ocr_image(data, os.path.splitext(n)[1])
            return _result(text, 'ocr', note)
    except Exception as e:
        return _result('', 'none', f'could not read the document ({e.__class__.__name__}): paste the text')
    return _result('', 'none', 'unsupported file type for text extraction: paste the text')


def text_from_bytes(name, data):
    """Backwards-compatible: → (text, note)."""
    r = extract(name, data)
    return r['text'], r['note']
