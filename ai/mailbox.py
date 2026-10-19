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

"""
Monitored mailbox (optional, off by default): unseen messages of one IMAP
folder become intake items (channel 'email' by default) in the "Submit to
Compliance" queue, with their attachments stored like intake uploads.

IMAP is not an AI service, so the mail host may be external — but only over
TLS (implicit SSL or STARTTLS, certificate verified). The message content is
only READ from the configured mailbox; it is never sent anywhere else. A
message is marked seen only after its intake item was created; a
Message-ID already imported is skipped (no duplicates if marking fails).
"""

import email
import imaplib
import io
import logging
import os
import ssl
from datetime import datetime
from email import policy
from email.utils import parsedate_to_datetime

from database.db import get_db

from . import extract, intake, settings

logger = logging.getLogger(__name__)
MAX_ATTACHMENT = 10 * 1024 * 1024
ATTACH_EXT = ('.pdf', '.docx', '.txt', '.png', '.jpg', '.jpeg', '.eml', '.html', '.htm', '.csv')


class MailboxError(RuntimeError):
    pass


def connect(cfg, password=None):
    host, port = cfg['ai.imap_host'], int(cfg['ai.imap_port'])
    if not host:
        raise MailboxError('no mail server configured')
    ctx = ssl.create_default_context()
    try:
        if cfg['ai.imap_security'] == 'ssl':
            conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=30)
        elif cfg['ai.imap_security'] == 'starttls':
            conn = imaplib.IMAP4(host, port, timeout=30)
            conn.starttls(ssl_context=ctx)
        else:
            raise MailboxError('the mailbox can only be read over SSL/TLS or STARTTLS')
        conn.login(cfg['ai.imap_user'], password if password is not None else settings.mail_password(cfg))
    except MailboxError:
        raise
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as e:
        raise MailboxError(f'mailbox connection failed: {e.__class__.__name__}: {str(e)[:150]}') from e
    return conn


def _text(msg):
    body = msg.get_body(preferencelist=('plain', 'html'))
    if not body:
        return ''
    try:
        content = body.get_content()
    except (LookupError, ValueError):
        content = (body.get_payload(decode=True) or b'').decode('utf-8', 'replace')
    return extract._html(content) if body.get_content_type() == 'text/html' else content


def parse(raw):
    """→ dict(subject, sender, date, message_id, body, attachments=[(filename, bytes)])."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    try:
        when = parsedate_to_datetime(msg['date']) if msg['date'] else None
        if when is not None and when.tzinfo is not None:
            when = when.astimezone().replace(tzinfo=None)
    except (TypeError, ValueError):
        when = None
    atts = []
    for part in msg.iter_attachments():
        name = part.get_filename()
        if not name:
            continue
        data = part.get_payload(decode=True) or b''
        if data and len(data) <= MAX_ATTACHMENT:
            atts.append((name, data))
    return {'subject': str(msg.get('subject') or '')[:290], 'sender': str(msg.get('from') or ''), 'date': when,
            'message_id': str(msg.get('message-id') or '').strip()[:300] or None, 'body': _text(msg), 'attachments': atts}


def _store_attachment(item_id, name, data, db):
    """Same place and table as an intake upload (generic_attachments module 'ai', record_type 'ai_intake')."""
    from flask import current_app
    from werkzeug.datastructures import FileStorage
    from utils.file_validator import secure_filename_strict, validate_file
    ext = os.path.splitext(name.lower())[1]
    if ext not in ATTACH_EXT:
        return None, f'{name}: file type not imported'
    if ext in ('.pdf', '.png', '.jpg', '.jpeg', '.txt', '.docx'):
        ok, err = validate_file(FileStorage(io.BytesIO(data), filename=name),
                                upload_type='image' if ext in ('.png', '.jpg', '.jpeg') else 'document')
        if not ok:
            return None, f'{name}: {err}'
    safe = secure_filename_strict(name)
    rel_dir = os.path.join('uploads', 'attachments', 'ai', 'ai_intake', str(item_id))
    full_dir = os.path.join(current_app.root_path, rel_dir)
    os.makedirs(full_dir, exist_ok=True)
    with open(os.path.join(full_dir, safe), 'wb') as fh:
        fh.write(data)
    db.execute("""INSERT INTO generic_attachments (module, record_type, record_id, filename, file_path, file_size, uploaded_by,
                  uploaded_at) VALUES ('ai', 'ai_intake', %s, %s, %s, %s, NULL, %s)""",
               (item_id, name[:255], os.path.join(rel_dir, safe).replace('\\', '/'), len(data),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()
    return extract.extract(name, data), None


def import_message(m, cfg, db=None):
    """Create one intake item from a parsed message. → item id, or None when it was already imported."""
    db = db or get_db()
    if m['message_id'] and db.execute("SELECT 1 FROM ai_intake_items WHERE source_message_id = %s", (m['message_id'],)).fetchone():
        return None
    head = f"From: {m['sender']}\nSubject: {m['subject']}\n" + (f"Date: {m['date']:%Y-%m-%d %H:%M}\n" if m['date'] else '')
    body = (m['body'] or '').strip()
    iid = intake.create_item(cfg.get('ai.imap_channel') or 'email', m['subject'] or '(e-mail)', f'{head}\n{body}'.strip(), None,
                             db=db, received_at=m['date'], message_id=m['message_id'])
    notes, best = [], None
    for name, data in m['attachments']:
        res, err = _store_attachment(iid, name, data, db)
        if err:
            notes.append(err)
        elif res and res['text'] and (best is None or len(res['text']) > len(best['text'])):
            best = res
        elif res and res.get('note'):
            notes.append(f"{name}: {res['note']}")
    if best:   # the order is often in the attachment: analyse the e-mail text and the attachment text together
        text = f'{head}\n{body}\n\n---\n{best["text"]}'
        intake.set_extraction(iid, dict(best, text=text[:extract.MAX_CHARS],
                                        note='; '.join(filter(None, [best.get('note')] + notes)) or None), db=db)
    elif notes:
        intake.set_extraction(iid, {'method': 'text' if body else 'none', 'note': '; '.join(notes)}, use_text=False, db=db)
    return iid


def run_import(cfg=None, db=None, conn=None):
    """Fetch the unseen messages, create intake items, mark them seen. → stats. Never raises for one bad message."""
    cfg = cfg or settings.get_mail_config()
    if not cfg['ai.imap_enabled'] and conn is None:
        return {'enabled': False, 'imported': 0, 'skipped': 0, 'errors': []}
    db = db or get_db()
    conn = conn or connect(cfg)
    stats = {'enabled': True, 'imported': 0, 'skipped': 0, 'errors': [], 'items': []}
    try:
        typ, _ = conn.select(cfg['ai.imap_folder'] or 'INBOX')
        if typ != 'OK':
            raise MailboxError(f"folder {cfg['ai.imap_folder']} not found")
        typ, data = conn.uid('SEARCH', None, 'UNSEEN')
        uids = (data[0] or b'').split()[:int(cfg['ai.imap_max_messages'])] if typ == 'OK' and data else []
        for uid in uids:
            try:
                typ, parts = conn.uid('FETCH', uid, '(BODY.PEEK[])')
                raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1), None)
                if typ != 'OK' or not raw:
                    raise MailboxError('empty message')
                iid = import_message(parse(raw), cfg, db)
                conn.uid('STORE', uid, '+FLAGS', '(\\Seen)')
                if iid:
                    stats['imported'] += 1
                    stats['items'].append(iid)
                else:
                    stats['skipped'] += 1
            except Exception as e:
                db.rollback()
                logger.exception('AI mailbox: message %s not imported', uid)
                stats['errors'].append(f'{uid.decode() if isinstance(uid, bytes) else uid}: {e.__class__.__name__}')
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    _after_import(stats['items'], db)
    return stats


def _after_import(item_ids, db):
    """Analyse the new items (rules inline / local model as a job) and tell the compliance team."""
    if not item_ids:
        return
    from . import service
    for iid in item_ids:
        try:
            service.start_job('intake', {'item_id': iid}, None)
        except Exception:
            db.rollback()
            logger.exception('AI mailbox: analysis of intake %s not started', iid)
    try:
        from regcontrols.alerts import compliance_heads
        from services.notification_service import notify
        notify(compliance_heads(db), 'Submitted to Compliance (mailbox)', f'{len(item_ids)} new e-mail(s) in the intake queue',
               link='/ai/', category='info')
    except Exception:
        db.rollback()


def test_connection(cfg=None, password=None):
    cfg = cfg or settings.get_mail_config()
    conn = connect(cfg, password)
    try:
        typ, data = conn.select(cfg['ai.imap_folder'] or 'INBOX', readonly=True)
        if typ != 'OK':
            raise MailboxError(f"folder {cfg['ai.imap_folder']} not found")
        return {'ok': True, 'detail': f"{cfg['ai.imap_folder']}: {(data[0] or b'0').decode()} message(s)"}
    finally:
        try:
            conn.logout()
        except Exception:
            pass
