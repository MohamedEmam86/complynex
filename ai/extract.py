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

"""Text from an uploaded document, with the standard library only (no new
dependency): plain text / e-mail / HTML / CSV, .docx (zip + XML); PDF only
if a PDF parser is already installed on the server (pypdf or pdfminer)."""

import email
import io
import re
import zipfile
from email import policy

MAX_CHARS = 20000


def _html(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s))


def text_from_bytes(name, data):
    """→ (text, note). note explains when no text could be read."""
    n = (name or '').lower()
    try:
        if n.endswith(('.txt', '.csv', '.md')):
            return data.decode('utf-8', 'replace')[:MAX_CHARS], None
        if n.endswith(('.html', '.htm')):
            return _html(data.decode('utf-8', 'replace'))[:MAX_CHARS], None
        if n.endswith('.eml'):
            msg = email.message_from_bytes(data, policy=policy.default)
            body = msg.get_body(preferencelist=('plain', 'html'))
            content = body.get_content() if body else ''
            if body and body.get_content_type() == 'text/html':
                content = _html(content)
            return f"Subject: {msg.get('subject', '')}\nFrom: {msg.get('from', '')}\n\n{content}"[:MAX_CHARS], None
        if n.endswith('.docx'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read('word/document.xml').decode('utf-8', 'replace')
            xml = re.sub(r'</w:p>', '\n', xml)
            return re.sub(r'[ \t]+', ' ', re.sub(r'<[^>]+>', '', xml)).strip()[:MAX_CHARS], None
        if n.endswith('.pdf'):
            try:
                from pypdf import PdfReader
                return '\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(data)).pages)[:MAX_CHARS], None
            except ImportError:
                try:
                    from pdfminer.high_level import extract_text
                    return extract_text(io.BytesIO(data))[:MAX_CHARS], None
                except ImportError:
                    return '', 'no PDF text reader is installed on this server: paste the text'
    except Exception as e:
        return '', f'could not read the document ({e.__class__.__name__}): paste the text'
    return '', 'unsupported file type for text extraction: paste the text'
