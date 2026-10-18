# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# =============================================================================
"""Lesson media: uploaded files (video / presentation / material) and video embeds."""
import os
import re
import secrets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, 'uploads', 'academy')

KINDS = {
    'video':        {'ext': {'mp4', 'webm'}, 'max_mb': 300},
    'presentation': {'ext': {'pdf', 'pptx', 'ppt'}, 'max_mb': 60},
    'material':     {'ext': {'pdf', 'docx', 'doc', 'xlsx', 'pptx', 'zip'}, 'max_mb': 60},
}
MIME = {'mp4': 'video/mp4', 'webm': 'video/webm', 'pdf': 'application/pdf',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'ppt': 'application/vnd.ms-powerpoint',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'doc': 'application/msword',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'zip': 'application/zip'}
# magic bytes — the extension alone is not trusted
MAGIC = {'pdf': [b'%PDF'], 'mp4': [b'ftyp'], 'webm': [b'\x1a\x45\xdf\xa3'],
         'pptx': [b'PK\x03\x04'], 'docx': [b'PK\x03\x04'], 'xlsx': [b'PK\x03\x04'], 'zip': [b'PK\x03\x04'],
         'ppt': [b'\xd0\xcf\x11\xe0'], 'doc': [b'\xd0\xcf\x11\xe0']}


def ext_of(name):
    return (name or '').rsplit('.', 1)[-1].lower() if '.' in (name or '') else ''


def save_upload(fs, kind, course_id):
    """Validate + store an uploaded FileStorage. Returns (stored_relpath, original_name) or raises ValueError."""
    rule = KINDS[kind]
    original = os.path.basename(fs.filename or '')[:150]
    ext = ext_of(original)
    if ext not in rule['ext']:
        raise ValueError(f'{kind}: allowed types are ' + ', '.join(sorted(rule['ext'])))
    head = fs.stream.read(16)
    fs.stream.seek(0)
    sig = MAGIC.get(ext, [])
    if sig and not any(head.startswith(s) or (ext == 'mp4' and s in head[:12]) for s in sig):
        raise ValueError(f'{original}: file content does not match its extension')
    folder = os.path.join(STORE, str(int(course_id)))
    os.makedirs(folder, exist_ok=True)
    stored = f'{kind}-{secrets.token_hex(8)}.{ext}'
    path = os.path.join(folder, stored)
    fs.save(path)
    size_mb = os.path.getsize(path) / 1048576
    if size_mb > rule['max_mb']:
        os.remove(path)
        raise ValueError(f'{original}: {size_mb:.0f} MB exceeds the {rule["max_mb"]} MB limit')
    return f'{int(course_id)}/{stored}', original


def abs_path(rel):
    if not rel or '..' in rel or rel.startswith('/'):
        return None
    p = os.path.realpath(os.path.join(STORE, rel))
    return p if p.startswith(os.path.realpath(STORE) + os.sep) and os.path.exists(p) else None


def remove(rel):
    p = abs_path(rel)
    if p:
        try:
            os.remove(p)
        except OSError:
            pass


def embed_url(url):
    """YouTube / Vimeo page URL -> privacy-friendly embed URL, else None."""
    u = (url or '').strip()
    m = re.search(r'(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})', u)
    if m:
        return f'https://www.youtube-nocookie.com/embed/{m.group(1)}?rel=0'
    m = re.search(r'vimeo\.com/(?:video/)?(\d+)(?:/([0-9a-f]+))?', u)
    if m:
        return f'https://player.vimeo.com/video/{m.group(1)}' + (f'?h={m.group(2)}' if m.group(2) else '')
    return None


def is_inline_pdf(rel):
    return ext_of(rel) == 'pdf'
