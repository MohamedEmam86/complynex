# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""CV upload checks and storage.

A CV arrives from an anonymous visitor, so it is treated as hostile:
  * PDF or DOCX only, at most MAX_BYTES; the extension must agree with the
    file's own signature (magic bytes);
  * PDF: rejected if it carries active content (JavaScript, launch actions,
    embedded files, forms that submit) — none of which a CV needs;
  * DOCX: must be a real Word package; macros, ActiveX, embedded objects and
    external relationships are rejected; the uncompressed size is capped so
    a zip bomb cannot exhaust the disk;
  * stored outside the web root under a random name, never under the
    visitor's file name, and only ever served as a download to staff with
    the talent permission.
"""
import hashlib
import io
import os
import re
import uuid
import zipfile
from datetime import datetime

MAX_BYTES = 5 * 1024 * 1024
MAX_UNZIPPED = 40 * 1024 * 1024
STORE_DIR = os.path.join('uploads', 'talent')

_PDF_ACTIVE = re.compile(rb'/(JavaScript|JS|Launch|EmbeddedFile|RichMedia|SubmitForm|ImportData|XFA)\b')
_RISKY_EXT = {'exe', 'js', 'vbs', 'bat', 'cmd', 'scr', 'com', 'msi', 'ps1', 'sh', 'php', 'html', 'htm',
              'hta', 'jar', 'docm', 'dotm', 'xlsm', 'lnk', 'svg', 'iso'}
_DOCX_FORBIDDEN = ('vbaproject.bin', 'activex', '/embeddings/', 'vbadata.xml')


class CVError(ValueError):
    """Message keys: the caller turns them into a bilingual message."""


def _ext(name):
    return os.path.splitext((name or '').lower())[1]


def check(file_storage):
    """Validate an uploaded CV. Returns (bytes, ext, original_name) or raises CVError(key)."""
    name = (file_storage.filename or '').strip()
    if not name:
        raise CVError('missing')
    base = os.path.basename(name.replace('\\', '/'))
    # "Ahmed.Mostafa CV.pdf" is fine; "cv.exe.pdf" / "cv.pdf.js" are not
    inner = base.lower().split('.')[1:-1]
    if any(p.strip() in _RISKY_EXT for p in inner):
        raise CVError('double_ext')
    ext = _ext(base)
    if ext not in ('.pdf', '.docx'):
        raise CVError('type')
    data = file_storage.stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise CVError('size')
    if len(data) < 200:
        raise CVError('empty')
    if ext == '.pdf':
        if not data.startswith(b'%PDF-'):
            raise CVError('signature')
        if _PDF_ACTIVE.search(data):
            raise CVError('active')
    else:
        if not data.startswith(b'PK\x03\x04'):
            raise CVError('signature')
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            names = [i.filename.lower() for i in z.infolist()]
            total = sum(i.file_size for i in z.infolist())
        except zipfile.BadZipFile:
            raise CVError('signature')
        if '[content_types].xml' not in names or 'word/document.xml' not in names:
            raise CVError('signature')
        if total > MAX_UNZIPPED or len(names) > 2000:
            raise CVError('size')
        if any(f in n for n in names for f in _DOCX_FORBIDDEN):
            raise CVError('active')
        try:
            ct = z.read('[Content_Types].xml').lower()
        except KeyError:
            ct = b''
        if b'macroenabled' in ct or b'vbaproject' in ct:
            raise CVError('active')
        for n in names:
            if n.endswith('.rels'):
                try:
                    rel = z.read(z.getinfo(next(i.filename for i in z.infolist() if i.filename.lower() == n)))
                except Exception:
                    continue
                # attachedTemplate / external links can pull remote content when opened
                if b'targetmode="external"' in rel.lower() and (b'attachedtemplate' in rel.lower()
                                                               or b'oleobject' in rel.lower()
                                                               or b'frame' in rel.lower()):
                    raise CVError('active')
    safe_original = re.sub(r'[^\w\-. ؀-ۿ]', '_', base)[:120]
    return data, ext, safe_original


def store(app_root, data, ext):
    """Write the file under uploads/talent/<yyyy>/<uuid><ext>. Returns (rel_path, sha256, size)."""
    sub = os.path.join(STORE_DIR, datetime.now().strftime('%Y'))
    abs_dir = os.path.join(app_root, sub)
    os.makedirs(abs_dir, mode=0o750, exist_ok=True)
    fname = f'{uuid.uuid4().hex}{ext}'
    rel = os.path.join(sub, fname)
    abs_path = os.path.join(app_root, rel)
    fd = os.open(abs_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(data)
    return rel, hashlib.sha256(data).hexdigest(), len(data)


def remove(app_root, rel_path):
    """Delete a stored CV (data-subject erasure). Only paths inside STORE_DIR."""
    if not rel_path:
        return False
    norm = os.path.normpath(rel_path)
    if not norm.startswith(STORE_DIR + os.sep) or '..' in norm.split(os.sep):
        return False
    try:
        os.remove(os.path.join(app_root, norm))
        return True
    except FileNotFoundError:
        return False


MESSAGES = {
    'missing': ('Please choose a file.', 'من فضلك اختر ملفًا.'),
    'double_ext': ('File names with more than one extension are not accepted.', 'لا نقبل ملفات بأكثر من امتداد.'),
    'type': ('Your CV must be a PDF or Word (.docx) file.', 'السيرة الذاتية لازم تكون ملف PDF أو Word (.docx).'),
    'size': ('Your CV must be 5 MB or smaller.', 'حجم السيرة الذاتية لازم يكون 5 ميجابايت أو أقل.'),
    'empty': ('The file looks empty.', 'الملف يبدو فارغًا.'),
    'signature': ('The file is not a valid PDF / Word document.', 'الملف ليس مستند PDF أو Word صالحًا.'),
    'active': ('The file contains macros, scripts or embedded content. Please upload a plain PDF or Word file.',
               'الملف يحتوي على ماكرو أو أكواد أو محتوى مضمّن. من فضلك ارفع ملف PDF أو Word عادي.'),
}
