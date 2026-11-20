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
"""Local negative-lists workbook import: sheet detection by header content, identity, lift logic, diff and
(against a scratch database only) apply / idempotence / shrink guard. Synthetic fixtures only: every name,
ID and reference below is invented."""
import datetime as dt
import os

import pytest

openpyxl = pytest.importorskip('openpyxl')

from screening.local_lists import workbook as W            # noqa: E402
from screening.local_lists import categories as C          # noqa: E402

NID_A = '29001010112345'      # synthetic, well-formed
NID_B = '28512120212346'
NID_C = '30105050312347'
PH = 'ــــــــ'                # placeholder as written in the workbook


def _pp_sheet(wb, rows, title='sheet one 01-01-2030'):
    ws = wb.create_sheet(title)
    ws.append(['أوامر اختبار'])
    ws.append(['الاسم', 'ترتيب الملفات', 'رقم البطاقة', 'نوع اثبات الشخصية', 'الكود الموحد', 'نوع الشخص',
               'امر المنع', None, 'القضية المنسوب لها المتهم', None, 'منع / إنهاء اثر', 'كتاب السيد المستشار', None,
               'تاريخ ورود الإيميل', 'ملحوظات اخرى'])
    ws.append([None, None, None, None, None, None, 'رقم امر المنع', 'سنة المنع', 'رقم القضية', 'سنة القضية', None,
               'رقم الكتاب', 'التاريخ', None, 'ملحوظات اخرى'])
    for r in rows:
        ws.append(r)
    ws.append(['sig', 'sig', 'sig', 'sig', 'sig', 'sig'])         # filler row: skipped
    return ws


def _pp(name, nid, order, year, lift=False, date=None, code=PH, case='11', note=PH, idtype='رقم قومى'):
    return [name, 1, nid, idtype, code, 'بالغ', order, year, case, 2030, 'انهاء اثر' if lift else PH, 5,
            dt.datetime(2030, 1, 1), date or dt.datetime(2030, 1, 2), note]


def _workbook(path, pp_rows, fiu_rows=None, un_rows=None, extra_entity=False):
    wb = openpyxl.Workbook()
    wb.active.title = 'read me'
    wb.active.append(['شرح الملف'])
    _pp_sheet(wb, pp_rows)
    ws = wb.create_sheet('anything 2')
    ws.append(['الاسم', 'اسم آخر', 'الرقم القومي', 'جواز السفر', 'الجنسية', 'رقم القضية', 'رقم قرار ادراج الارهابيين',
               'تاريخ النشر', 'عدد النشر'])
    for r in (fiu_rows if fiu_rows is not None else [
            ['اختبار جيم دال', PH, '**********4321', PH, PH, '1 لسنة 2030 حصر', '1-2030', '1/2/2030\nمد القرار\n3/4/2031',
             '9 تابع']]):
        ws.append(r)
    ws = wb.create_sheet('xyz')
    ws.append(['أسماء الكيانات'])
    ws.append(['مسلسل', 'اسم الكيان', 'الدولة', 'الاسم بالإنجليزية', 'الاسم بلغة البلد', 'رقم القضية',
               'العدد بالجريدة الرسمية', 'التحديثات'])
    ws.append([1, 'جماعة اختبار هاء', PH, 'TEST GROUP HE', PH, 'قضية رقم 2 لسنة 2030', 'العدد 3', PH])
    if extra_entity:
        ws.append([2, 'جماعة اختبار واو', PH, PH, PH, 'قضية رقم 4 لسنة 2030', 'العدد 5', PH])
    ws = wb.create_sheet('un 01-02-2030')
    ws.append(['قائمة الجزاءات بشأن القرار 1718'])
    ws.append(['اشخاص /كيانات', 'مسلسل الإدراج', 'الاسم', None, None, None, 'الاسم الرسمي', 'تاريخ الميلاد', 'محل الميلاد',
               'أسماء أخرى (تم تأكيدها)', 'أسماء أخرى (غير اكيدة)', 'الجنسية', 'رقم جواز السفر', 'رقم قومي', 'العنوان',
               'تاريخ الإدراج', 'معلومات إضافية'])
    ws.append([None, None, 'الأول', 'الثاني', 'الثالث', 'الرابع'])
    for r in (un_rows if un_rows is not None else [
            ['شخص', 'KPi.901', 'TESTONE', 'ALPHA', None, None, 'اختبار زاي', '1 Jan. 1970', 'na', 'a) T ONE b) T UNO',
             'na', 'na', 'na', 'na', 'na', '2 Feb. 2030', 'na'],
            ['كيان', 'KPe.902', 'TEST TRADING CO', None, None, None, 'na', 'na', 'na', 'na', 'na', 'na', 'na', 'na',
             'na', '2 Feb. 2030', 'na']]):
        ws.append(r)
    wb.save(path)
    return path


BASE_PP = [
    _pp('اختبار الف باء', NID_A, '10', 2030),
    _pp('اختبار الف باء', NID_A, '10', 2030, lift=True, date=dt.datetime(2030, 3, 1)),     # lifted
    _pp('اختبار تاء ثاء', NID_B, '20', 2030),
    _pp('اختبار تاء ثاء', NID_B, '21', 2030),
    _pp('اختبار تاء ثاء', NID_B, '21', 2030, lift=True, date=dt.datetime(2030, 3, 2)),     # one of two lifted
    _pp('اختبار جيم حاء', NID_C, '30', 2030),
    _pp('اختبار جيم حاء', NID_C, '31', 2030),
    _pp('اختبار جيم حاء', NID_C, '99', 2030, lift=True, case='77', date=dt.datetime(2030, 3, 3)),  # unmatched
    _pp('اختبار خاء دال', PH, '40', 2030, idtype=PH, note='سوري الجنسية'),
    _pp('اختبار خاء دال', PH, '40', 2030, lift=True, idtype=PH, date=dt.datetime(2030, 3, 4)),
]


def _by(parsed, kind):
    return [r for r in parsed['records'] if r['kind'] == kind]


def test_sheets_recognised_by_content_not_name(tmp_path):
    p = W.parse(_workbook(str(tmp_path / 'wb.xlsx'), BASE_PP))
    kinds = [s['kind'] for s in p['sheets']]
    assert kinds == [None, 'PP_ORDER', 'FIU_PERSONS', 'FIU_ENTITIES', 'UN']
    pp = next(s for s in p['sheets'] if s['kind'] == 'PP_ORDER')
    assert pp['skipped_rows'] == 1 and pp['data_rows'] == len(BASE_PP)
    assert p['date'] == '2030-02-01' or p['date'] is None or p['date'] <= dt.date.today().isoformat()


def test_categories_are_generic(tmp_path):
    p = W.parse(_workbook(str(tmp_path / 'wb.xlsx'), BASE_PP))
    cats = {r['kind']: r['category'] for r in p['records']}
    assert cats == {'PP_ORDER': 'EG_FREEZE_ORDER', 'FIU_PERSONS': 'EG_TERROR_PERSONS',
                    'FIU_ENTITIES': 'EG_TERROR_ENTITIES', 'UN': 'UN_DPRK'}
    for code in C.CATEGORIES:
        lab = C.label(code)
        assert ' / ' in lab and C.code_of_label(lab) == code
        assert 'sheet' not in lab.lower()


def test_order_level_lift_logic(tmp_path):
    p = W.parse(_workbook(str(tmp_path / 'wb.xlsx'), BASE_PP))
    pp = {r['name']: r for r in _by(p, 'PP_ORDER')}
    assert len(pp) == 4
    assert pp['اختبار الف باء']['status'] == 'LIFTED' and pp['اختبار الف باء']['lifted_on'] == '2030-03-01'
    assert pp['اختبار تاء ثاء']['status'] == 'LISTED'                      # order 20 still in force
    assert {o['state'] for o in pp['اختبار تاء ثاء']['listings']} == {'IN_FORCE', 'LIFTED'}
    assert pp['اختبار جيم حاء']['status'] == 'LISTED'                      # lift names no known order: kept
    assert pp['اختبار جيم حاء']['_flags'].get('lift_unmatched') == 1
    no_id = pp['اختبار خاء دال']                                             # no ID: lift tied by name + order
    assert no_id['status'] == 'LIFTED' and no_id['nationality'] == 'سوري'
    assert pp['اختبار الف باء']['dob'] == '1990-01-01'


def test_relisting_after_lift(tmp_path):
    rows = BASE_PP + [_pp('اختبار الف باء', NID_A, '10', 2030, date=dt.datetime(2030, 5, 1))]
    p = W.parse(_workbook(str(tmp_path / 'wb.xlsx'), rows))
    rec = next(r for r in _by(p, 'PP_ORDER') if r['name'] == 'اختبار الف باء')
    assert rec['status'] == 'LISTED'


def test_masked_id_position_and_multiple_dates(tmp_path):
    a = W.parse(_workbook(str(tmp_path / 'a.xlsx'), BASE_PP))
    fiu = [['اختبار جيم دال', PH, '4321**********', PH, PH, '1 لسنة 2030 حصر', '1-2030',
            '1/2/2030\nمد القرار\n3/4/2031', '9 تابع']]
    b = W.parse(_workbook(str(tmp_path / 'b.xlsx'), BASE_PP, fiu_rows=fiu))
    ka = W.record_key(_by(a, 'FIU_PERSONS')[0])
    kb = W.record_key(_by(b, 'FIU_PERSONS')[0])
    assert ka == kb
    assert _by(a, 'FIU_PERSONS')[0]['listings'][0]['published'] == ['2030-02-01', '2031-04-03']


def test_keys_are_stable_and_hide_ids(tmp_path):
    path = _workbook(str(tmp_path / 'wb.xlsx'), BASE_PP)
    a, b = W.parse(path), W.parse(path)
    ka = sorted((W.record_key(r), W.content_sha(r)) for r in a['records'])
    kb = sorted((W.record_key(r), W.content_sha(r)) for r in b['records'])
    assert ka == kb
    assert not any(NID_A in k for k, _s in ka)


def test_un_sheet(tmp_path):
    p = W.parse(_workbook(str(tmp_path / 'wb.xlsx'), BASE_PP))
    un = {r['listings'][0]['ref']: r for r in _by(p, 'UN')}
    assert un['KPI.901']['entity_type'] == 'INDIVIDUAL' and un['KPE.902']['entity_type'] == 'ENTITY'
    assert un['KPI.901']['name'] == 'اختبار زاي' and un['KPI.901']['name_latin'] == 'TESTONE ALPHA'
    assert un['KPI.901']['aliases'] == ['T ONE', 'T UNO'] and un['KPI.901']['dob'] == '1970-01-01'
    assert un['KPE.902']['national_id'] == ''          # 'na' is a placeholder


def test_helpers():
    assert W.clean('ــــــ') == '' and W.clean(' — ') == '' and W.clean('N/A') == ''
    assert W.find_dates('قرار 1718 -16-11-2030') == ['2030-11-16']
    assert W.find_dates('31 ديسمبر 1979') == ['1979-12-31']
    main, al = W.split_name('اختبار كاف "لام" ميم (الشهير بنون)')
    assert main == 'اختبار كاف ميم' and 'لام' in al and 'نون' in al
    assert W.valid_nid(NID_A) == NID_A and W.valid_nid('29013450112345') == ''
    assert W.detect_kind([W.norm('اسم الكيان'), W.norm('رقم القضية')]) == 'FIU_ENTITIES'
    assert W.is_lift('رفع الحظر- قرار رفع رقم 1-2030') and not W.is_lift('مد الادراج')


# ----------------------------------------------------------------------------- database (scratch only)
DBNAME = os.environ.get('LOCAL_LISTS_TEST_DB', '')
needs_db = pytest.mark.skipif(not DBNAME or os.environ.get('POSTGRES_DB') != DBNAME,
                              reason='needs LOCAL_LISTS_TEST_DB=<scratch db> and POSTGRES_DB set to it')


@needs_db
def test_apply_diff_idempotent_and_shrink(tmp_path):
    import psycopg2
    from config import Config
    from screening.local_lists import importer as I
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    try:
        c = conn.cursor()
        c.execute("SELECT count(*) FROM local_list_records")
        if c.fetchone()[0]:
            pytest.skip('the scratch database already holds imported records')
        # previous state: one hand-loaded row of the same person (taken over), one entity more
        c.execute("""INSERT INTO internal_blacklist (full_name, original_name, entity_type, national_id, reason,
                         category, source, source_id, is_active) VALUES ('X', 'اختبار تاء ثاء', 'INDIVIDUAL', %s,
                         'old', 'old sheet', 'INTERNAL_BULK_UPLOAD', 'IBL-TESTLEGACY01', 1)""", (NID_B,))
        prev = W.parse(_workbook(str(tmp_path / 'prev.xlsx'), BASE_PP[:2] + BASE_PP[2:4], extra_entity=True))
        pl = I.plan(conn, prev)
        assert pl['totals']['adopted'] == 1 and not pl['blocked']
        v1 = I.apply(conn, prev, pl, 'prev.xlsx', 'x' * 64, commit=False)
        new = W.parse(_workbook(str(tmp_path / 'new.xlsx'), BASE_PP))
        pl2 = I.plan(conn, new, shrink_min=1, shrink_pct=60)
        t = pl2['totals']
        assert (t['added'], t['removed'], t['changed']) == (2, 1, 1), t      # +2 persons, -1 entity, 1 lift of 2
        assert pl2['counts']['EG_TERROR_ENTITIES']['removed'] == 1
        v2 = I.apply(conn, new, pl2, 'new.xlsx', 'y' * 64, commit=False)
        assert v2 > v1
        c.execute("SELECT is_active, legal_status FROM internal_blacklist WHERE source = 'LOCAL_LISTS' AND original_name = %s",
                  ('اختبار الف باء',))
        assert c.fetchone() == (1, 'LIFTED')
        c.execute("SELECT count(*) FROM internal_blacklist WHERE source = 'LOCAL_LISTS' AND is_active = 0")
        assert c.fetchone()[0] == 1                                             # the removed entity: never deleted
        pl3 = I.plan(conn, new)
        assert pl3['totals']['changes'] == 0                                    # idempotent
        small = W.parse(_workbook(str(tmp_path / 'small.xlsx'), BASE_PP, un_rows=[]))
        pl4 = I.plan(conn, small, shrink_min=1)
        assert pl4['blocked'] and pl4['shrink']                                  # UN sheet emptied: refused
        assert not I.plan(conn, small, shrink_min=1, allow_shrink=True)['blocked']
    finally:
        conn.rollback()
        conn.close()


@needs_db
def test_superadmin_page_preview_and_refusal(tmp_path):
    import time
    from config import config
    if os.environ.get('FLASK_ENV') not in config:
        os.environ['FLASK_ENV'] = 'development'
    from app import create_app
    from models.user import User
    from screening.local_lists import routes as R
    app = create_app()
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        from database.db import get_db
        db = get_db()
        ids = {}
        for key, role in (('admin', 'admin'), ('super', 'superadmin')):
            email = f'll-{key}@example.test'
            u = User.get_by_email(email) or User.create_user(email, 'Str0ng!Passw0rd#x', 'Test', key, role=role,
                                                             perm_screening='edit')
            db.execute("UPDATE users SET must_change_password = FALSE, perm_screening = 'edit', access_mode = 'cms' "
                       "WHERE id = %s", (u.id,))
            ids[key] = u.id
        db.commit()

    def client(uid):
        cl = app.test_client()
        with cl.session_transaction() as s:
            s['_user_id'] = User.session_id_for_app(app, uid)
            s['_fresh'] = True
        return cl
    adm = client(ids['admin'])
    r = adm.get('/screening/lists/local-import')
    assert r.status_code in (302, 403)
    sup = client(ids['super'])
    r = sup.get('/screening/lists/local-import')
    assert r.status_code == 200 and 'Local lists workbook' in r.get_data(as_text=True)
    path = _workbook(str(tmp_path / 'up.xlsx'), BASE_PP)
    with open(path, 'rb') as fh:
        r = sup.post('/screening/lists/local-import/upload', data={'file': (fh, 'up.xlsx'), 'add_new_only': '1'},
                     content_type='multipart/form-data')
    assert r.status_code == 302
    token = r.headers['Location'].split('job=')[-1]
    for _ in range(60):
        job = R.load_job(token)
        if job and job['state'] != 'running':
            break
        time.sleep(0.5)
    assert job['state'] == 'done' and job['result']['result'] == 'DRY_RUN'
    page = sup.get(f'/screening/lists/local-import?job={token}').get_data(as_text=True)
    assert 'اختبار' not in page                       # counts only: no listed name on the page
    assert 'Apply' in page and 'New persons' in page          # add-new-only preview table
    for f in os.listdir(R.LL_DIR):
        if f.startswith(token):
            os.remove(os.path.join(R.LL_DIR, f))


# ----------------------------------------------------------------------------- add-new-only mode
def test_screenable_duplicate_rules():
    from screening.local_lists.importer import Screenable
    idx = Screenable()
    idx.add(['اختبار الف باء'], [NID_A], dob='1990-01-01')
    idx.add(['اختبار ميم نون'], ['**********9999'])
    idx.add(['TEST PERSON'], [], ['A1234567'])
    rec = {'name': 'اختبار الف باء', 'national_id': '', 'listings': []}
    assert idx.duplicate(dict(rec, national_id=NID_A)) == 'national_id'
    assert idx.duplicate(rec) == 'name'                                          # same name, nothing conflicts
    assert idx.duplicate(dict(rec, national_id=NID_B)) is None                   # same name, other person
    assert idx.duplicate(dict(rec, dob='1991-02-02')) is None                    # same name, other date of birth
    assert idx.duplicate({'name': 'اختبار ميم نون', 'national_id': NID_C}) is None      # masked digits differ
    assert idx.duplicate({'name': 'اختبار ميم نون', 'national_id': '9999**********'}) == 'name'
    assert idx.duplicate({'name': 'x', 'national_id': '', 'passport': 'A1234567'}) == 'passport'


@needs_db
def test_add_new_only_leaves_existing_rows_untouched(tmp_path):
    import psycopg2
    from config import Config
    from screening.local_lists import importer as I
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    try:
        c = conn.cursor()
        c.execute("SELECT count(*) FROM local_list_records")
        if c.fetchone()[0]:
            pytest.skip('the scratch database already holds imported records')
        c.execute("""INSERT INTO internal_blacklist (full_name, original_name, entity_type, national_id, reason,
                         category, aliases, source, source_id, is_active) VALUES ('X', 'اختبار تاء ثاء', 'INDIVIDUAL', %s,
                         'old reason', 'old sheet', '[]', 'INTERNAL_BULK_UPLOAD', 'IBL-TESTLEGACY02', 1) RETURNING id""",
                  (NID_B,))
        bid = c.fetchone()[0]
        c.execute("""INSERT INTO screening_watchlist (full_name, original_name, entity_type, source, source_id,
                         national_id_numbers, is_active) VALUES
                         ('اختبار جيم دال', 'اختبار جيم دال', 'PERSON', 'emlcu', 'emlcu_test_1', '["**********4321"]', 1),
                         ('اختبار جيم حاء', 'اختبار جيم حاء', 'PERSON', 'emlcu', 'emlcu_test_2', '["**********0000"]', 1),
                         ('TESTONE ALPHA', 'TESTONE ALPHA', 'PERSON', 'un', 'UN-TEST-1', NULL, 1)""")
        p = W.parse(_workbook(str(tmp_path / 'wb.xlsx'), BASE_PP))
        base = I.plan(conn, p)
        pl = I.plan_add_new(conn, p, base)
        cnt = pl['counts']
        assert cnt['EG_FREEZE_ORDER']['adopted_linked'] == 1                       # the existing row: linked only
        assert cnt['EG_FREEZE_ORDER']['skipped_lifted'] == 2                       # lifted records never added
        assert cnt['EG_FREEZE_ORDER']['new_persons'] == 1                          # C: the EMLCU namesake has other digits
        assert cnt['EG_TERROR_PERSONS']['dup_name'] == 1                           # already on the EMLCU site list
        assert cnt['EG_TERROR_ENTITIES']['new_entities'] == 1
        assert cnt['UN_DPRK']['un_skipped'] == 2 and not pl['blocked']
        I.apply(conn, p, pl, 'wb.xlsx', 'z' * 64, commit=False)
        c.execute("SELECT full_name, reason, category, aliases, source FROM internal_blacklist WHERE id = %s", (bid,))
        assert c.fetchone() == ('X', 'old reason', 'old sheet', '[]', 'INTERNAL_BULK_UPLOAD')
        c.execute("SELECT count(*) FROM internal_blacklist WHERE source = 'LOCAL_LISTS'")
        assert c.fetchone()[0] == 2
        again = I.plan_add_new(conn, p, I.plan(conn, p))
        assert again['totals']['changes'] == 0                                    # idempotent
        un = I.plan_add_new(conn, p, I.plan(conn, p), include_un=True)
        assert un['counts']['UN_DPRK']['dup_name'] == 1 and un['counts']['UN_DPRK']['new_entities'] == 1
    finally:
        conn.rollback()
        conn.close()
