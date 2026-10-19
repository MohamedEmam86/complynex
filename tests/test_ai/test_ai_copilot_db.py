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

"""End-to-end on a TEST database (skipped when none is reachable): freeze-order intake → synchronous
screening on fixture customers / merchants / beneficial owners / counterparties → freeze and
false-positive decisions; policy question answered only with a citation; monitored-mailbox import
(fake IMAP); pages in English and Arabic. Fictional data only; fixture rows are removed afterwards."""

import os
import shutil
from datetime import date, timedelta

import pytest

from fakes import FakeIMAP, FakeOCR, make_email, make_pdf

pytestmark = pytest.mark.filterwarnings('ignore::DeprecationWarning')


@pytest.fixture(scope='module')
def app():
    if not os.environ.get('POSTGRES_DB'):
        pytest.skip('no test database configured (POSTGRES_DB)')
    try:
        from app import create_app
        a = create_app('development')
        a.config.update(WTF_CSRF_ENABLED=False, TESTING=True, SESSION_COOKIE_SECURE=False, PROPAGATE_EXCEPTIONS=True)
        with a.app_context():
            from database.db import get_db
            if not get_db().execute("SELECT to_regclass('ai_screening_matches') AS t").fetchone()['t']:
                pytest.skip('migration 20261030_ai_copilot_ocr_screening.sql is not applied on the test database')
    except pytest.skip.Exception:
        raise
    except Exception as e:  # noqa: BLE001
        pytest.skip(f'test database not reachable: {e.__class__.__name__}')
    return a


@pytest.fixture(autouse=True)
def inline_jobs(monkeypatch):
    """No RQ worker in tests: every job runs inline."""
    import events.queue

    def no_queue():
        raise RuntimeError('no queue in tests')
    monkeypatch.setattr(events.queue, 'get_queue', no_queue)


def client(app, lang='en'):
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = '1'
        s['_fresh'] = True
        s['mfa_verified'] = True
        s['lang'] = lang
    return c


@pytest.fixture(scope='module')
def fixtures(app):
    """Fictional records in every source table; removed afterwards."""
    from database.db import get_db
    with app.app_context():
        db = get_db()
        made_tx = not db.execute("SELECT to_regclass('transactions') AS t").fetchone()['t']
        if made_tx:
            db.execute("""CREATE TABLE transactions (id SERIAL PRIMARY KEY, transaction_reference TEXT, customer_id INTEGER,
                          transaction_date DATE, transaction_type TEXT, amount NUMERIC, currency TEXT, counterparty_name TEXT,
                          counterparty_account TEXT, counterparty_country TEXT)""")
        ids = {}
        ids['cust'] = db.execute("""INSERT INTO customers (customer_number, customer_type, full_name, full_name_arabic, id_number)
                                    VALUES ('TST-FZ-1', 'INDIVIDUAL', 'Ahmed Samir Fathy', 'أحمد سمير فتحي', '29001011234567')
                                    RETURNING id""").fetchone()['id']
        ids['cust2'] = db.execute("""INSERT INTO customers (customer_number, customer_type, full_name) VALUES
                                     ('TST-FZ-2', 'INDIVIDUAL', 'Mona Adel Kamel') RETURNING id""").fetchone()['id']
        ids['merch'] = db.execute("""INSERT INTO merchants (merchant_name, cr_number, ubo_name, ubo_id_number) VALUES
                                     ('Nile Star Trading', 'CR-55501', 'Karim Hassan Lotfy', '28512250101234') RETURNING id""").fetchone()['id']
        ids['bo'] = db.execute("""INSERT INTO kyc_beneficial_owners (subject, subject_id, full_name) VALUES
                                  ('aml_customer', %s, 'Laila Fouad Hamdy') RETURNING id""", (ids['cust2'],)).fetchone()['id']
        ids['tx'] = db.execute("""INSERT INTO transactions (customer_id, transaction_date, transaction_type, amount, currency,
                                  counterparty_name, counterparty_account) VALUES (%s, %s, 'TRANSFER', 1000, 'EGP',
                                  'Sherif Nabil Zaki', 'EG00TEST') RETURNING id""",
                               (ids['cust2'], date.today() - timedelta(days=10))).fetchone()['id']
        ids['tx_old'] = db.execute("""INSERT INTO transactions (customer_id, transaction_date, transaction_type, amount, currency,
                                      counterparty_name) VALUES (%s, %s, 'TRANSFER', 1000, 'EGP', 'Omar Galal Saber') RETURNING id""",
                                   (ids['cust2'], date.today() - timedelta(days=200))).fetchone()['id']
        ids['policy'] = db.execute("""INSERT INTO policies (policy_number, policy_name, effective_date, status, description, content)
            VALUES ('TST-POL-GIFTS', 'Gifts and hospitality policy', CURRENT_DATE, 'approved',
                    'Rules for gifts, hospitality and entertainment offered to or by employees.',
                    '<p>Employees must not accept gifts from suppliers or customers above the value set by the compliance function.</p>
                     <p>Every gift offered must be recorded in the gifts register within five working days, whether accepted or declined.</p>')
            RETURNING id""").fetchone()['id']
        db.commit()
    yield ids
    with app.app_context():
        db = get_db()
        db.rollback()
        items = [r['id'] for r in db.execute("SELECT id FROM ai_intake_items WHERE subject LIKE 'TST-FZ%%'").fetchall()]
        if items:
            db.execute("DELETE FROM aml_unusual_transactions WHERE (source_table = 'ai_intake_items' AND source_record_id = ANY(%s)) "
                       "OR (source_table = 'ai_screening_matches' AND source_record_id IN "
                       "(SELECT id FROM ai_screening_matches WHERE item_id = ANY(%s)))", (items, items))
            db.execute("DELETE FROM generic_attachments WHERE module = 'ai' AND record_id = ANY(%s)", (items,))
            db.execute("DELETE FROM ai_intake_items WHERE id = ANY(%s)", (items,))
            for i in items:
                shutil.rmtree(os.path.join(app.root_path, 'uploads', 'attachments', 'ai', 'ai_intake', str(i)), ignore_errors=True)
        db.execute("DELETE FROM rc_findings WHERE source_ref LIKE 'ai_intake:%%' AND title LIKE '%%TST-FZ%%'")
        db.execute("DELETE FROM customers WHERE customer_number LIKE 'TST-FZ-%%'")
        db.execute("DELETE FROM merchants WHERE id = %s", (ids['merch'],))
        db.execute("DELETE FROM kyc_beneficial_owners WHERE id = %s", (ids['bo'],))
        db.execute("DELETE FROM policies WHERE id = %s", (ids['policy'],))
        if made_tx:
            db.execute("DROP TABLE transactions")
        else:
            db.execute("DELETE FROM transactions WHERE id = ANY(%s)", ([ids['tx'], ids['tx_old']],))
        db.execute("DELETE FROM ai_library_paragraphs WHERE source_type = 'policy' AND source_id = %s", (ids['policy'],))
        db.commit()


def _item(app, iid):
    from ai import intake
    with app.app_context():
        return intake.item(iid)


def _submit(app, c, subject, body):
    r = c.post('/ai/', data={'channel': 'text', 'subject': subject, 'body': body})
    assert r.status_code == 302, r.data[:300]
    return int(r.headers['Location'].split('/ai/intake/')[1].split('?')[0])


ORDER = ('Freeze order No. 15 of 2026, dated {d}.\nPlease freeze immediately all accounts and funds of the persons listed below:\n'
         '1. أحمد سمير فتحى\n2. Karim Hassan Lotfi, ID 28512250101234\n3. Sherif Nabil Zaky\n4. Omar Galal Saber\n'
         'and confirm the action taken.')


def test_freeze_order_flow(app, fixtures):
    c = client(app)
    iid = _submit(app, c, 'TST-FZ freeze order', ORDER.format(d=date.today().isoformat()))
    it = _item(app, iid)
    assert it['status'] == 'proposed' and it['proposal']['intent'] == 'freeze_order'
    r = c.post(f'/ai/intake/{iid}', data={'action': 'confirm', 'intent': 'freeze_order', 'f_order_reference': '15/2026',
                                          'f_subject_names': 'أحمد سمير فتحى, Karim Hassan Lotfi, Sherif Nabil Zaky, Omar Galal Saber',
                                          'f_national_id': '28512250101234', 'priority': 'critical', 'summary': 'freeze TST-FZ'})
    assert r.status_code == 302 and r.headers['Location'].endswith('#screening')
    from ai import freeze_screening as FS
    with app.app_context():
        ms = FS.matches(iid)
    got = {(m['source'], m['source_table'], m['record_id'], m['match_type']) for m in ms}
    assert ('customer', 'customers', fixtures['cust'], 'name') in got                     # Arabic order name, Latin record
    assert ('beneficial_owner', 'merchants.ubo', fixtures['merch'], 'id') in got           # exact national ID
    assert ('counterparty', 'transactions', fixtures['tx'], 'name') in got                 # counterparty of the last 90 days
    assert not any(m['record_id'] == fixtures['tx_old'] for m in ms if m['source'] == 'counterparty')   # older than 90 days
    assert not any(m['record_id'] == fixtures['cust2'] for m in ms if m['source'] == 'customer')
    it = _item(app, iid)
    assert it['screened_at'] and it['received_at'] and it['proposal']['screening']['matches'] == len(ms)

    for lang in ('en', 'ar'):
        page = client(app, lang).get(f'/ai/intake/{iid}')
        assert page.status_code == 200 and b'data-elapsed-s' in page.data and b'screening' in page.data

    cust = next(m for m in ms if m['source'] == 'customer')
    cp = next(m for m in ms if m['source'] == 'counterparty')
    r = c.post(f'/ai/intake/{iid}/matches/{cp["id"]}', data={'decision': 'false_positive', 'reason': ''})
    with app.app_context():
        from database.db import get_db
        assert get_db().execute("SELECT status FROM ai_screening_matches WHERE id = %s", (cp['id'],)).fetchone()['status'] == 'open'
    c.post(f'/ai/intake/{iid}/matches/{cp["id"]}', data={'decision': 'false_positive', 'reason': 'different date of birth'})
    c.post(f'/ai/intake/{iid}/matches/{cust["id"]}', data={'decision': 'freeze'})
    with app.app_context():
        db = get_db()
        st = {r['id']: dict(r) for r in db.execute("SELECT * FROM ai_screening_matches WHERE item_id = %s", (iid,)).fetchall()}
        assert st[cp['id']]['status'] == 'false_positive' and st[cp['id']]['reason'] == 'different date of birth'
        assert st[cust['id']]['status'] == 'frozen' and st[cust['id']]['aml_unusual_id']
        utr = db.execute("SELECT * FROM aml_unusual_transactions WHERE id = %s", (st[cust['id']]['aml_unusual_id'],)).fetchone()
        assert utr['detection_rule'] == 'freeze_order_match' and utr['source_table'] == 'ai_screening_matches'
        order_utr = db.execute("SELECT description FROM aml_unusual_transactions WHERE source_table = 'ai_intake_items' "
                               "AND source_record_id = %s", (iid,)).fetchone()
        assert order_utr and 'FREEZE' in order_utr['description']
        assert db.execute("SELECT count(*) AS n FROM audit_logs WHERE action = 'ai_freeze_match_freeze' AND item_id::text = %s",
                          (str(iid),)).fetchone()['n'] == 1
        assert db.execute("SELECT status FROM customers WHERE id = %s", (fixtures['cust'],)).fetchone()['status'] in (None, 'ACTIVE')
    again = c.post(f'/ai/intake/{iid}/matches/{cust["id"]}', data={'decision': 'false_positive', 'reason': 'x'})
    assert again.status_code == 302          # already decided: refused with a message, nothing changes


def test_policy_question_needs_a_citation(app, fixtures):
    from ai import library, settings
    with app.app_context():
        stats = library.rebuild(embedder=settings.embedder())
        assert stats['documents'].get('policy', 0) >= 1 and stats['paragraphs'] >= 1
    c = client(app)
    iid = _submit(app, c, 'TST-FZ question', 'Can I accept a gift from a supplier? Which policy applies and must I record it?')
    prop = _item(app, iid)['proposal']
    assert prop['intent'] == 'policy_question' and prop['library']['status'] == 'cited'
    top = prop['library']['citations'][0]
    assert top['source_type'] == 'policy' and top['source_id'] == fixtures['policy'] and 'gift' in top['body']
    assert any('gifts register' in c['body'] for c in prop['library']['citations'])
    page = c.get(f'/ai/intake/{iid}')
    assert page.status_code == 200 and f'/policies/{fixtures["policy"]}'.encode() in page.data
    c.post(f'/ai/intake/{iid}', data={'action': 'confirm', 'intent': 'policy_question', 'f_topic': 'gifts from suppliers'})
    it = _item(app, iid)
    assert it['final']['library']['status'] == 'cited' and it['created_refs'][0]['type'] == 'policy'

    iid2 = _submit(app, c, 'TST-FZ question 2', 'What is the procedure for booking the parking garage on Thursdays? Which policy?')
    prop2 = _item(app, iid2)['proposal']
    if prop2.get('intent') == 'policy_question':
        assert prop2['library']['status'] == 'no_source' and prop2['library']['answer'] is None
    c.post(f'/ai/intake/{iid2}', data={'action': 'confirm', 'intent': 'policy_question', 'f_topic': 'parking garage bookings'})
    it2 = _item(app, iid2)
    assert it2['final']['library']['status'] == 'no_source' and it2['created_refs'] == []
    assert b'No source found' in c.get(f'/ai/intake/{iid2}').data
    for i in (iid, iid2):
        assert client(app, 'ar').get(f'/ai/intake/{i}').status_code == 200


def test_mailbox_import_creates_queue_items(app, fixtures, monkeypatch):
    from ai import mailbox
    FakeOCR(has_tesseract=False).install(monkeypatch)
    pdf = make_pdf([['Freeze order No. 16 of 2026', 'Freeze all funds of Mona Adel Kamel']])
    raw = make_email('TST-FZ mail order', 'Please see the attached order.', [('order16.pdf', pdf, 'application', 'pdf')],
                     message_id='<tst-fz-16@example.test>')
    cfg = {'ai.imap_enabled': True, 'ai.imap_folder': 'INBOX', 'ai.imap_max_messages': 5, 'ai.imap_channel': 'email'}
    with app.test_request_context():
        conn = FakeIMAP([raw])
        r = mailbox.run_import(cfg, conn=conn)
        assert r['imported'] == 1 and conn.seen == {b'1'}
        iid = r['items'][0]
        r2 = mailbox.run_import(cfg, conn=FakeIMAP([raw]))         # same Message-ID again: skipped
        assert r2['imported'] == 0 and r2['skipped'] == 1
    it = _item(app, iid)
    assert it['channel'] == 'email' and it['created_by'] is None and it['received_at'] is not None
    assert it['source_message_id'] == '<tst-fz-16@example.test>'
    try:
        import pypdf  # noqa: F401
        assert it['extraction_method'] == 'pypdf' and 'Mona Adel Kamel' in it['body']
    except ImportError:
        assert it['extraction_method'] in ('text', 'none')
    assert it['status'] == 'proposed'
    from attachments.service import list_attachments
    with app.app_context():
        files = list_attachments('ai', 'ai_intake', iid)
    assert files and files[0]['filename'] == 'order16.pdf'
    assert client(app).get(f'/ai/intake/{iid}').status_code == 200


def test_mail_settings_password_never_plain(app):
    from ai import settings
    from database.db import get_db
    with app.app_context():
        saved = settings.get_mail_config()
        try:
            settings.save_mail_config({'ai.imap_host': 'imap.example.test', 'ai.imap_user': 'u', 'ai.imap_password': 'pw-123',
                                       'ai.imap_security': 'ssl', 'ai.imap_port': '993'})
            raw = get_db().execute("SELECT setting_value FROM system_settings WHERE setting_key = 'ai.imap_password'").fetchone()
            assert raw['setting_value'].startswith('enc:') and 'pw-123' not in raw['setting_value']
            assert settings.mail_password() == 'pw-123'
            settings.save_mail_config({'ai.imap_host': 'imap.example.test', 'ai.imap_user': 'u', 'ai.imap_security': 'ssl'})
            assert settings.mail_password() == 'pw-123'                      # empty field keeps the stored one
            with pytest.raises(ValueError):
                settings.save_mail_config({'ai.imap_host': 'imap.example.test', 'ai.imap_security': 'none'})
        finally:
            get_db().rollback()
            from models.settings import Settings
            Settings.set_many({k: str(saved[k]).lower() if isinstance(saved[k], bool) else str(saved[k])
                               for k in settings.MAIL_DEFAULTS})


@pytest.mark.parametrize('lang', ['en', 'ar'])
def test_pages_render(app, fixtures, lang):
    c = client(app, lang)
    for url in ('/ai/', '/ai/settings', '/dashboard'):
        r = c.get(url)
        assert r.status_code == 200, (url, r.status_code)
    assert b'/ai/' in c.get('/dashboard').data
    r = c.post('/ai/settings', data={'action': 'library_index'})
    assert r.status_code == 302
