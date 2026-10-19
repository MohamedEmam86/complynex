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

"""Copilot phase 2 without a database: document extraction (fake PDFs, fake local OCR), freeze-order
name/ID matching on fixture records, citation-only policy answers and the IMAP import (fake server)."""

import builtins
import sys
from datetime import datetime

import pytest

from ai import extract, freeze_screening as FS, library, mailbox, tasks
from ai.providers import Provider, ProviderError
from fakes import FakeIMAP, FakeOCR, make_email, make_pdf

try:
    import pypdf  # noqa: F401
    HAVE_PYPDF = True
except ImportError:
    HAVE_PYPDF = False
needs_pypdf = pytest.mark.skipif(not HAVE_PYPDF, reason='pypdf is not installed in this environment (pip install pypdf)')


class FakeProvider(Provider):
    name, model, can_generate = 'fake', 'fake-1', True

    def __init__(self, *replies):
        self.replies = list(replies)

    def generate(self, system, prompt, timeout=None):
        if not self.replies:
            raise ProviderError('no more replies')
        return self.replies.pop(0)


# ---------------------------------------------------------------- 1. extraction
def test_make_pdf_is_a_pdf():
    assert make_pdf([['hello']]).startswith(b'%PDF-1.4')


@needs_pypdf
def test_text_pdf_uses_pypdf_and_no_ocr(monkeypatch):
    ocr = FakeOCR().install(monkeypatch)
    lines = ['Freeze order No. 15 of 2026', 'Please freeze all accounts of Ahmed Samir Fathy', 'National ID 29001011234567']
    r = extract.extract('order.pdf', make_pdf([lines]))
    assert r['method'] == 'pypdf' and 'Ahmed Samir Fathy' in r['text'] and r['note'] is None
    assert not [c for c in ocr.calls if 'stdout' in c], 'OCR must not run when the PDF has a text layer'


@needs_pypdf
def test_scanned_pdf_goes_to_local_ocr_with_arabic(monkeypatch):
    ocr = FakeOCR(text='أمر تجميد رقم ١٥ لسنة ٢٠٢٦\nأحمد سمير فتحي', pages=2).install(monkeypatch)
    r = extract.extract('scan.pdf', make_pdf([[], []]))
    assert r['method'] == 'ocr' and 'أحمد سمير فتحي' in r['text'] and r['note'] is None
    tess = [c for c in ocr.calls if c[0].endswith('tesseract') and 'stdout' in c]
    assert len(tess) == 2 and all(c[c.index('-l') + 1] == 'ara+eng' for c in tess)
    assert any(c[0].endswith('pdftoppm') for c in ocr.calls)


@needs_pypdf
def test_scanned_pdf_without_renderer_records_that_ocr_was_not_possible(monkeypatch):
    FakeOCR(has_pdftoppm=False).install(monkeypatch)
    r = extract.extract('scan.pdf', make_pdf([[]]))
    assert r['method'] == 'none' and r['text'] == '' and 'poppler-utils' in r['note']


@needs_pypdf
def test_no_tesseract_at_all_degrades(monkeypatch):
    FakeOCR(has_tesseract=False, has_pdftoppm=False).install(monkeypatch)
    r = extract.extract('scan.pdf', make_pdf([[]]))
    assert r['method'] == 'none' and 'tesseract-ocr' in r['note']
    r = extract.extract('photo.jpg', b'\xff\xd8\xff fake jpeg')
    assert r['method'] == 'none' and 'OCR is not available' in r['note']


def test_image_ocr_without_arabic_data_says_so(monkeypatch):
    ocr = FakeOCR(text='FREEZE ORDER', langs=('eng',)).install(monkeypatch)
    r = extract.extract('photo.png', b'\x89PNG\r\n\x1a\nfake')
    assert r['method'] == 'ocr' and r['text'] == 'FREEZE ORDER' and 'tesseract-ocr-ara' in r['note']
    assert [c for c in ocr.calls if 'stdout' in c][0][-1] == 'eng'


def test_pdf_without_any_reader(monkeypatch):
    FakeOCR(has_tesseract=False).install(monkeypatch)
    real_import = builtins.__import__

    def no_pdf(name, *a, **k):
        if name in ('pypdf', 'pdfminer.high_level'):
            raise ImportError(name)
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, '__import__', no_pdf)
    monkeypatch.delitem(sys.modules, 'pypdf', raising=False)
    r = extract.extract('order.pdf', make_pdf([['text']]))
    assert r['method'] == 'none' and 'pip install pypdf' in r['note']


def test_plain_and_legacy_api():
    r = extract.extract('note.txt', 'Freeze order'.encode())
    assert (r['method'], r['text']) == ('text', 'Freeze order')
    assert extract.text_from_bytes('x.xyz', b'1') == ('', 'unsupported file type for text extraction: paste the text')


# ---------------------------------------------------------------- 2. freeze-order matching (fixture records)
CANDS = [
    {'source': 'customer', 'key': 'customers', 'record_id': 1, 'label': 'Ahmed Samir Fathy',
     'names': ['Ahmed Samir Fathy', 'أحمد سمير فتحي'], 'ids': ['29001011234567']},
    {'source': 'customer', 'key': 'customers', 'record_id': 2, 'label': 'Mona Adel Kamel', 'names': ['Mona Adel Kamel'], 'ids': []},
    {'source': 'merchant', 'key': 'merchants', 'record_id': 7, 'label': 'Nile Star Trading', 'names': ['Nile Star Trading'],
     'ids': ['CR-55501']},
    {'source': 'beneficial_owner', 'key': 'merchants.ubo', 'record_id': 7, 'label': 'Karim Hassan Lotfy',
     'names': ['Karim Hassan Lotfy'], 'ids': ['28512250101234']},
    {'source': 'counterparty', 'key': 'transactions', 'record_id': 99, 'label': 'Sherif Nabil Zaki',
     'names': ['Sherif Nabil Zaki'], 'ids': ['EG1234']},
]


def test_match_by_national_id_even_with_arabic_digits():
    res = FS.match([], ['٢٨٥١٢٢٥٠١٠١٢٣٤'], CANDS)
    assert [(m['source'], m['record_id'], m['match_type'], m['score']) for m in res] == [('beneficial_owner', 7, 'id', 1.0)]


def test_match_arabic_order_name_against_english_record_and_counterparty():
    res = FS.match(['احمد سمير فتحى', 'Sherif Nabil Zaky'], [], CANDS, threshold=0.85)
    got = {(m['source'], m['record_id']) for m in res}
    assert ('customer', 1) in got and ('counterparty', 99) in got
    assert ('customer', 2) not in got and ('merchant', 7) not in got


def test_arabic_script_order_name_matches_latin_record():
    res = FS.match(['كريم حسن لطفي'], [], CANDS)          # default threshold 0.80 (as the screening search)
    assert [(m['source'], m['record_id'], m['match_type']) for m in res] == [('beneficial_owner', 7, 'name')]


def test_unrelated_names_do_not_match():
    assert FS.match(['Youssef Tarek Mansour'], ['30101010000000'], CANDS) == []


def test_hash_id_match():
    cands = [{'source': 'customer', 'key': 'customers', 'record_id': 5, 'label': 'X', 'names': [], 'ids': [],
              'id_hashes': ['h:29001011234567']}]
    res = FS.match([], ['29001011234567'], cands, id_hash=lambda v: 'h:' + v)
    assert res and res[0]['match_type'] == 'id'


def test_subjects_of_item_and_receipt_time():
    item = {'id': 1, 'body': 'Order dated 2026-10-18. Freeze Ahmed Samir Fathy, ID 29001011234567.',
            'created_at': datetime(2026, 10, 19, 9, 0), 'received_at': None,
            'final': {'fields': {'subject_names': 'Ahmed Samir Fathy, شركة النجم للتجارة\nKarim Hassan Lotfy',
                                 'national_id': '28512250101234'}}}
    names, ids = FS.subjects_of(item)
    assert names == ['Ahmed Samir Fathy', 'شركة النجم للتجارة', 'Karim Hassan Lotfy']
    assert set(ids) == {'28512250101234', '29001011234567'}
    od = FS.order_date(item['body'], item['created_at'])
    assert od == datetime(2026, 10, 18)
    item['received_at'] = od
    assert FS.receipt_time(item) == od and FS.hours_since(item, now=datetime(2026, 10, 19, 12, 0)) == 36.0
    assert FS.order_date('Law dated 2002-06-01', item['created_at']) is None     # not the order's own date


def test_should_screen_is_data():
    assert FS.should_screen({'handler_params': {'screen_subjects': True}})
    assert not FS.should_screen({'handler_params': {}}) and not FS.should_screen(None)


# ---------------------------------------------------------------- 3. citations
POLICY = ('Gifts and hospitality policy\n\nEmployees must not accept gifts from suppliers above the value set in this '
          'policy. Every gift offered must be recorded in the gifts register within five working days.\n\n'
          'Information security policy\n\nPasswords must be changed every ninety days and never shared.')


def _rows(texts):
    rows = []
    for i, t in enumerate(texts, start=1):
        full = t
        rows.append({'id': i, '_ng': library.T.ngrams(full), '_tok': set(library.T.tokens(full)), 'body': t})
    return rows


def test_paragraphs_split_and_merge():
    ps = library.paragraphs(POLICY)
    assert len(ps) == 2 and ps[0].startswith('Gifts and hospitality policy') and 'Passwords' in ps[1]
    assert all(len(p) <= library.MAX_PARA for p in library.paragraphs('word ' * 2000))


def test_rules_score_ranks_the_relevant_paragraph():
    rows = _rows(library.paragraphs(POLICY))
    idf = {t: 1.0 for r in rows for t in r['_tok']}
    q = 'Can I accept a gift from a supplier? Do I have to record it?'
    s = [library.rules_score(q, r, idf) for r in rows]
    assert s[0] > 0.3 > s[1]
    assert library.rules_score('lunch on thursday', rows[0], idf) < 0.3


CITES = [{'id': 11, 'ref_label': 'POL-007', 'title': 'Gifts', 'body': 'Every gift offered must be recorded.'}]


def test_model_may_only_summarise_cited_paragraphs():
    res, meta = tasks.summarise_citations('gift?', CITES, 'en', FakeProvider('{"answer": "Record every gift.", "cited": [11]}'))
    assert res == {'answer': 'Record every gift.', 'cited': [11]} and meta['status'] == 'ok'
    # a reply that cites nothing (or an unknown paragraph) is refused twice -> no model answer, paragraphs only
    bad = FakeProvider('{"answer": "Gifts are fine.", "cited": []}', '{"answer": "Gifts are fine.", "cited": [99]}')
    res, meta = tasks.summarise_citations('gift?', CITES, 'en', bad)
    assert res['answer'] is None and res['cited'] == [11] and meta['status'] == 'fallback'


def test_no_citation_means_no_answer(monkeypatch):
    monkeypatch.setattr(library, 'search', lambda *a, **k: [])
    res, meta = library.answer('What is the gifts limit?', gen=FakeProvider('{"answer": "500 EGP", "cited": [1]}'))
    assert res['status'] == 'no_source' and res['answer'] is None and res['citations'] == []
    monkeypatch.setattr(library, 'search', lambda *a, **k: [dict(CITES[0])])
    res, _ = library.answer('What is the gifts limit?')
    assert res['status'] == 'cited' and res['citations'][0]['id'] == 11 and res['answer'] is None


# ---------------------------------------------------------------- 4. monitored mailbox (fake IMAP)
CFG = {'ai.imap_enabled': True, 'ai.imap_host': 'imap.example.test', 'ai.imap_port': 993, 'ai.imap_security': 'ssl',
       'ai.imap_user': 'compliance@example.test', 'ai.imap_password': 'env:TEST_PW', 'ai.imap_folder': 'INBOX',
       'ai.imap_max_messages': 10, 'ai.imap_channel': 'email'}


def test_parse_email_with_attachment():
    raw = make_email('Freeze order 15/2026', 'See the attached order.', [('order.pdf', make_pdf([['Freeze']]), 'application', 'pdf')])
    m = mailbox.parse(raw)
    assert m['subject'] == 'Freeze order 15/2026' and m['message_id'] == '<order-1@example.test>'
    assert m['attachments'][0][0] == 'order.pdf' and m['date'] is not None and m['body'].strip() == 'See the attached order.'


def test_run_import_marks_seen_only_after_import(monkeypatch):
    imported = []
    monkeypatch.setattr(mailbox, 'import_message', lambda m, cfg, db=None: imported.append(m['subject']) or len(imported))
    monkeypatch.setattr(mailbox, '_after_import', lambda ids, db: None)
    conn = FakeIMAP([make_email('A', 'one', message_id='<a@x>'), make_email('B', 'two', message_id='<b@x>'),
                     make_email('C', 'three', message_id='<c@x>')], fail_uids=[2])

    class DB:
        def rollback(self):
            pass
    r = mailbox.run_import(CFG, db=DB(), conn=conn)
    assert imported == ['A', 'C'] and r['imported'] == 2 and len(r['errors']) == 1
    assert conn.seen == {b'1', b'3'} and conn.logged_out, 'a message that failed stays unseen for the next run'


def test_imap_requires_tls(monkeypatch):
    seen = {}

    class SSL(FakeIMAP):
        def __init__(self, host, port, ssl_context=None, timeout=None):
            seen.update(host=host, port=port, ctx=ssl_context)
            super().__init__([])
    monkeypatch.setattr(mailbox.imaplib, 'IMAP4_SSL', SSL)
    monkeypatch.setenv('TEST_PW', 's3cret')
    monkeypatch.setattr(mailbox.settings, 'mail_password', lambda cfg=None: 's3cret')
    conn = mailbox.connect(CFG)
    assert seen['ctx'] is not None and seen['ctx'].verify_mode.name == 'CERT_REQUIRED'
    assert ('login', 'compliance@example.test', 's3cret') in conn.log
    with pytest.raises(mailbox.MailboxError):
        mailbox.connect(dict(CFG, **{'ai.imap_security': 'plain'}))


def test_disabled_mailbox_does_nothing():
    assert mailbox.run_import(dict(CFG, **{'ai.imap_enabled': False}))['enabled'] is False
