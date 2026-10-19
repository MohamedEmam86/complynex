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

"""Test doubles for the Copilot: a tiny PDF writer (text or "scanned" pages), a fake local
Tesseract / pdftoppm (subprocess + shutil.which) and a fake IMAP server. Fictional data only."""

import os
import subprocess
from email.message import EmailMessage


def make_pdf(pages):
    """A minimal valid PDF. pages: list of lists of text lines; an empty list = a page without any
    text layer (what a scanner produces, minus the image)."""
    objs = ['<< /Type /Catalog /Pages 2 0 R >>', None, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for lines in pages:
        ops = ['BT', '/F1 12 Tf', '14 TL', '72 720 Td']
        for ln in lines:
            ops.append('(' + ln.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') + ') Tj T*')
        ops.append('ET')
        stream = '\n'.join(ops) if lines else ''
        objs.append(f'<< /Length {len(stream.encode("latin-1"))} >>\nstream\n{stream}\nendstream')
        content_no = len(objs)
        objs.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> '
                    f'/Contents {content_no} 0 R >>')
        kids.append(f'{len(objs)} 0 R')
    objs[1] = f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(kids)} >>'
    out, offsets = b'%PDF-1.4\n', []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n{o}\nendobj\n'.encode('latin-1')
    xref = len(out)
    out += f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode()
    for off in offsets:
        out += f'{off:010d} 00000 n \n'.encode()
    out += f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return out


class FakeOCR:
    """Stands in for the local `tesseract` and `pdftoppm` binaries."""

    def __init__(self, text='OCR TEXT', langs=('eng', 'ara', 'osd'), has_tesseract=True, has_pdftoppm=True, pages=1):
        self.text, self.langs, self.pages = text, langs, pages
        self.has = {'tesseract': has_tesseract, 'pdftoppm': has_pdftoppm}
        self.calls = []

    def which(self, name):
        return f'/usr/bin/{name}' if self.has.get(name) else None

    def run(self, cmd, capture_output=False, text=False, timeout=None, check=False):
        self.calls.append(list(cmd))
        exe = os.path.basename(cmd[0])
        if exe == 'tesseract' and '--list-langs' in cmd:
            out = 'List of available languages (3):\n' + '\n'.join(self.langs)
            return subprocess.CompletedProcess(cmd, 0, out if text else out.encode(), '' if text else b'')
        if exe == 'pdftoppm':
            prefix = cmd[-1]
            for i in range(1, self.pages + 1):
                with open(f'{prefix}-{i}.png', 'wb') as fh:
                    fh.write(b'\x89PNG\r\n\x1a\nfake')
            return subprocess.CompletedProcess(cmd, 0, b'', b'')
        if exe == 'tesseract':
            assert os.path.isfile(cmd[1]), 'tesseract must get a local file'
            return subprocess.CompletedProcess(cmd, 0, self.text.encode('utf-8'), b'')
        raise AssertionError(f'unexpected command {cmd}')

    def install(self, monkeypatch):
        import ai.extract as X
        monkeypatch.setattr(X.shutil, 'which', self.which)
        monkeypatch.setattr(X.subprocess, 'run', self.run)
        return self


def make_email(subject, body, attachments=(), message_id='<order-1@example.test>', date='Mon, 19 Oct 2026 08:15:00 +0300'):
    m = EmailMessage()
    m['From'] = 'Notifications <notices@example.test>'
    m['To'] = 'compliance@example.test'
    m['Subject'] = subject
    m['Date'] = date
    m['Message-ID'] = message_id
    m.set_content(body)
    for name, data, maintype, subtype in attachments:
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return m.as_bytes()


class FakeIMAP:
    """Enough of imaplib.IMAP4 for ai.mailbox: login/select/uid SEARCH|FETCH|STORE/logout."""

    def __init__(self, messages, fail_uids=()):
        self.messages = {str(i).encode(): raw for i, raw in enumerate(messages, start=1)}
        self.seen, self.fail_uids, self.log = set(), {str(u).encode() for u in fail_uids}, []
        self.logged_out = False

    def login(self, user, password):
        self.log.append(('login', user, password))
        return 'OK', [b'logged in']

    def select(self, folder='INBOX', readonly=False):
        self.log.append(('select', folder))
        return 'OK', [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        self.log.append((command,) + args)
        if command == 'SEARCH':
            return 'OK', [b' '.join(u for u in self.messages if u not in self.seen)]
        if command == 'FETCH':
            uid, what = args
            assert 'PEEK' in what, 'messages must not be marked seen while fetching'
            if uid in self.fail_uids:
                return 'NO', [None]
            return 'OK', [(uid + b' (BODY[] {%d}' % len(self.messages[uid]), self.messages[uid]), b')']
        if command == 'STORE':
            self.seen.add(args[0])
            return 'OK', [b'']
        raise AssertionError(command)

    def logout(self):
        self.logged_out = True
        return 'BYE', [b'']
