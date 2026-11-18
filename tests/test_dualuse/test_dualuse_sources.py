"""Dual-use goods module: parsers on excerpts of the REAL published sources, the importer's helpers, search
quality rules and screening explanations (no database, no network).

Fixtures (small excerpts, reusable):
  eu_consolidated_excerpt.html  EUR-Lex consolidated text of Regulation (EU) 2021/821 as of 2026-09-21
                                (Annex I entries 1C216, 1C225 and 5A002; reuse allowed under Decision 2011/833/EU)
  us_ccl_excerpt.xml            eCFR Title 15 Part 774 Supplement No. 1 as of 2026-08-28 (1C010, 1C350, 5A002;
                                US Government work, public domain)
  chpl_tiers.txt                List of Common High Priority Items, version of February 2024 (pdftotext -layout)
"""
import importlib.util
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

import pytest

from packs.trade_control import parsers as P
from packs.trade_control import screening as SC
from packs.trade_control import search as SE
from packs.trade_control import service as S
from packs.trade_control import text as T


def _read(name, mode='r'):
    with open(os.path.join(FIX, name), mode, **({} if 'b' in mode else {'encoding': 'utf-8'})) as f:
        return f.read()


@pytest.fixture(scope='module')
def importer():
    spec = importlib.util.spec_from_file_location('du_import_lists', os.path.join(ROOT, 'scripts', 'dualuse',
                                                                                  'import_lists.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ EU consolidated layout
def test_eu_consolidated_entries_items_and_notes():
    recs = {r['code']: r for r in P.parse_eu_annex1(_read('eu_consolidated_excerpt.html'))}
    # the entry written as a paragraph and the one written as a lettered block (1C225) are both found
    assert {'1C216', '1C225', '5A002', '5A002.a', '5A002.a.4.b', '5A002.e'} <= set(recs)
    # notes and technical notes (printed in italics) never become control items
    assert not any(c.startswith('5A002.a.1.') for c in recs)
    assert recs['5A002']['text_en'].startswith('"Information security" systems')
    assert any('cryptography for data confidentiality' in n for n in recs['5A002.a']['notes_en'])
    assert recs['5A002.a']['parent'] == '5A002' and recs['5A002.a.4.b']['level'] == 3
    # Annex II repeats codes: it is not read
    assert 'ignored' not in recs['5A002']['text_en']
    # superscript isotope and thresholds with a thousands space
    assert '(10B)' in recs['1C225']['text_en']
    p = recs['1C216']['parameters'][0]
    assert p['operator'] == '>=' and p['value'] == 1950 and p['unit'] == 'MPa'


def test_eu_label_from_consolidated_text(importer):
    items, _, _, label = importer.build_items('eu_annex1', _read('eu_consolidated_excerpt.html').encode())
    assert label == 'Annex I, consolidated text of 2026-09-21'
    assert {i['code'] for i in items} >= {'5A002', '1C225'}
    assert next(i for i in items if i['code'] == '1C225')['risk_level'] == 'high'      # nuclear dual-use (2)


# ------------------------------------------------------------------ US CCL (eCFR XML)
def test_ccl_real_excerpt():
    recs = {r['code']: r for r in P.parse_ccl(_read('us_ccl_excerpt.xml'))}
    assert set(recs) == {'1C010', '1C350', '5A002'}           # Supplement No. 2 is not read
    r = recs['5A002']
    assert r['reasons'] == ['AT', 'EI', 'NS', 'RS'] and r['category_title']
    subs = {s['code']: s for s in r['sub_items']}
    assert '5A002.a' in subs and '5A002.a.4.b' in subs
    c = recs['1C350']
    assert 'CB' in c['reasons'] and 'CW' in c['reasons']
    assert '7719-09-7' in c['cas_numbers'] and len(c['cas_numbers']) >= 60
    # superscripts are kept as powers of ten and still parsed as thresholds
    params = [p for s in recs['1C010']['sub_items'] for p in s['parameters']]
    assert any(p['value'] > 1e4 and p['unit'] == 'm' for p in params)


def test_chemicals_register_reads_us_cas_format():
    us = P.parse_ccl(_read('us_ccl_excerpt.xml'))
    chem = {c['cas']: c for c in P.build_chemicals([], [], [{'code': r['code'], 'items_text_en': r['items_text_en']}
                                                            for r in us])}
    assert chem['7719-09-7']['names_en'][0] == 'Thionyl chloride'
    assert any(l['ref'].startswith('1C350.') for l in chem['7719-09-7']['listings'])
    assert all(T.cas_valid(c) for c in chem)


# ------------------------------------------------------------------ CHPL
def test_chpl_real_text():
    recs = P.parse_chpl_text(_read('chpl_tiers.txt'))
    assert len(recs) == 50
    tiers = {}
    for r in recs:
        tiers[r['tier']] = tiers.get(r['tier'], 0) + 1
    assert tiers == {'1': 4, '2': 5, '3.A': 16, '3.B': 9, '4.A': 11, '4.B': 5}
    last = recs[-1]
    assert last['hs6'] == '846693' and last['description_en'].endswith('8461, n.e.s.')


# ------------------------------------------------------------------ importer helpers
def test_content_digest_is_stable_and_order_independent(importer):
    a = [{'code': '5A002', 'text_en': 'x', 'params': []}]
    assert importer.content_digest(a) == importer.content_digest([dict(reversed(list(a[0].items())))])
    assert importer.content_digest(a) != importer.content_digest([{'code': '5A002', 'text_en': 'y', 'params': []}])


def test_risk_rules(importer):
    assert importer.risk_eu('0B001') == 'high' and importer.risk_eu('9A120') == 'high'
    assert importer.risk_eu('1C350.9') == 'high' and importer.risk_eu('5A002.a') == 'medium'
    assert importer.risk_us('5A992', ['AT', 'RS'], False, False) == 'low'
    assert importer.risk_us('9A515', ['NS'], False, True) == 'high'


def test_latest_consolidated_date_is_discovered(importer, monkeypatch):
    page = b'<a href="?uri=CELEX:02021R0821-20251115">x</a> 02021R0821-20260921 02021R0821-20241108'
    monkeypatch.setattr(importer, 'fetch', lambda url, timeout=120: page)
    assert importer.latest_eu_consolidated() == '20260921'


def test_user_agent_is_generic(importer):
    ua = importer.UA['User-Agent']
    assert '@' not in ua and 'complynex' not in ua.lower()


# ------------------------------------------------------------------ search quality
def _ix():
    docs = [
        dict(id=1, list_code='eu_annex1', code='9A012', level=0, category='9', group='A',
             title_en='"Unmanned aerial vehicles" ("UAVs"), unmanned airships, related equipment', text_en='x',
             risk='high', kind='item'),
        dict(id=2, list_code='eu_annex1', code='9A107', level=0, category='9', group='A',
             title_en='Solid propellant rocket motors, usable in complete rocket systems or unmanned aerial vehicles',
             text_en='y', risk='high', kind='item'),
        dict(id=3, list_code='eu_annex1', code='0A981.b', level=1, category='0', group='A',
             title_en=None, text_en='Electric chairs for the purpose of executing human beings.', kind='item'),
        dict(id=4, list_code='us_ccl', code='3A001', level=0, category='3', group='A',
             title_en='Electronic items as follows', text_en='a. ' + 'oscilloscope chair router ' * 40,
             index_text='Electronic items as follows', kind='item'),
        dict(id='c1', list_code='chemicals', code='7719-09-7', level=0, title_en='Thionyl chloride',
             text_en='Thionyl chloride', cas=['7719-09-7'], kind='chemical', extra={'names': ['Thionyl chloride']}),
    ]
    return SE.Index(docs, [('drone', 'طائرة مسيرة')], synonyms=[['drone', 'UAV', 'unmanned aerial vehicle']])


def test_synonyms_and_head_noun_ranking():
    ix = _ix()
    r = ix.search('drone')
    assert r['results'][0]['doc'].code == '9A012' and 'synonym' in r['results'][0]['why']
    assert ix.search('طائرة مسيرة')['results'][0]['doc'].code == '9A012'
    assert 'unmanned aerial vehicle' in ' '.join(ix.search('drone')['expanded'])


def test_entry_heading_only_indexed_for_long_us_entries():
    assert ix_codes(_ix().search('oscilloscope')) == []


def ix_codes(res):
    return [r['doc'].code for r in res['results']]


def test_cas_without_dashes_and_coverage():
    ix = _ix()
    r = ix.search('7719097')
    assert r['exact'] == 'cas' and r['results'][0]['doc'].code == '7719-09-7'
    r = ix.search('office chairs')
    assert r['results'] and r['results'][0]['coverage'] < SC.MIN_TEXT_COVERAGE
    assert ix.suggest('77190')[0]['value'] == '7719-09-7'


def test_office_chairs_is_not_a_candidate():
    res = SC.screen_line(_ix(), {'description': 'office chairs', 'hs_code': '9401.30'})
    assert res['candidates'] == [] and res['suggested'] == 'clear'


def test_chemical_named_in_description_without_cas():
    ix = SE.Index([dict(id='c1', list_code='chemicals', code='7719-09-7', level=0, title_en='Thionyl chloride',
                        text_en='Thionyl chloride', cas=['7719-09-7'], kind='chemical', risk='high',
                        extra={'names': ['Thionyl chloride'], 'cwc_schedule': 3, 'ag_precursor': True})] +
                  [dict(id=i, list_code='eu_annex1', code='9X%03d' % i, level=0, title_en='filler %d' % i,
                        text_en='other text', kind='item') for i in range(10)])
    res = SC.screen_line(ix, {'description': 'Thionyl chloride 99 percent, drums'})
    assert {h['flag'] for h in res['hard']} == {'cwc', 'precursor'} and res['suggested'] == 'hold'


def test_explanation_and_priority_outcome():
    cands = [{'code': '3A002.d', 'title_en': 'Signal generators', 'state': 'open', 'why': ['Description matches: x'],
              'reasons': ['text']}]
    ex = SC.explain(cands, [{'flag': 'priority', 'code': '8543.20'}], 'review')
    assert len(ex) == 2 and 'High-priority' in ex[0][0] and 'open' in ex[1][0] and ex[1][1]
    assert SC.evaluate([], [{'flag': 'priority', 'code': '8543.20'}], [], {})[0] == 'review'
    assert SC.evaluate([], [], [], {})[0] == 'clear'
    assert SC.explain([], [], 'clear')[0][0].startswith('No control entry')


def test_snippet_marks_whole_words():
    s = T.snippet('Incorporating focal plane arrays &lt;', ['array', 'lt'])
    assert '<mark>arrays</mark>' in s and '&<mark>' not in s


def test_client_label_and_disclaimer_never_name_a_list():
    for text in S.CLIENT_LIST_LABEL + S.DISCLAIMER:
        for name in ('EU', 'US', 'CCL', 'Wassenaar', 'CWC', 'Australia', 'OPCW', 'EAR'):
            assert name not in text.split()
    assert S.CLIENT_LIST_LABEL == ('International control lists', 'قوائم الرقابة الدولية')
    assert 'not a legal classification' in S.DISCLAIMER[0]


def test_vessel_screening_degrades_without_engine_tables():
    class FakeDB:
        def execute(self, *a, **k):
            class R:
                def fetchone(self):
                    return {'t': None}
            return R()

        def rollback(self):
            pass
    assert S.screen_vessel('', '', FakeDB()) == {}
    assert S.screen_vessel('OCEAN STAR', '9074729', FakeDB())['error'] == 'unavailable'


# ------------------------------------------------------------------ batch file limits (review M6, minors 6 and 9)
def test_batch_file_limits_stop_early_and_speak_arabic():
    big = ('desc,hs\n' + ''.join('item %d,8471.30\n' % i for i in range(S.MAX_BATCH_LINES + S.HEADER_SCAN + 5))).encode()
    with pytest.raises(S.TableError) as e:
        S.read_table('a.csv', big)
    assert e.value.ar and str(S.MAX_BATCH_LINES) in e.value.en
    wide = (','.join('c%d' % i for i in range(80)) + '\n' + ','.join('v' for _ in range(80)) + '\n').encode()
    header, rows = S.read_table('w.csv', wide)
    assert len(header) == S.MAX_COLUMNS and len(rows[0]) == S.MAX_COLUMNS
    with pytest.raises(S.TableError):
        S.read_table('f.csv', b'a,b\n"' + b'x' * 200000 + b'",1\n')        # csv.Error is not a 500
    with pytest.raises(S.TableError) as e:
        S.read_table('x.pdf', b'%PDF')
    assert e.value.ar


def test_xlsx_zip_bomb_refused_before_parsing():
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('xl/worksheets/sheet1.xml', b'0' * (S.MAX_XLSX_UNZIPPED + 1))
    with pytest.raises(S.TableError) as e:
        S.read_table('bomb.xlsx', buf.getvalue())
    assert 'unpacked' in e.value.en


def test_tmp_uploads_are_swept(tmp_path):
    import time as _t
    from packs.trade_control import routes as R
    old, new = tmp_path / ('a' * 32 + '.json'), tmp_path / ('b' * 32 + '.json')
    old.write_text('{}')
    new.write_text('{}')
    past = _t.time() - R.TMP_TTL - 10
    os.utime(old, (past, past))
    R._sweep_tmp(str(tmp_path))
    assert not old.exists() and new.exists()


def test_roles_sources_superadmin_only():
    assert S.SOURCE_ROLES == ('superadmin',)
    assert set(S.BYPASS_ROLES) == {'superadmin', 'it_admin'}
    assert S.VESSEL_LIST_LABEL[1] == 'قوائم دولية معتمدة'


def test_every_dualuse_table_is_classified_on_purpose():
    """Reference lists are shared (loaded centrally, no tenant_id); screenings and decisions are tenant-owned."""
    import re as _re
    from database.tenancy import classify
    sql = open(os.path.join(ROOT, 'database', 'migrations', '20261117_dualuse.sql'), encoding='utf-8').read()
    tables = set(_re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', sql))
    shared = {'dualuse_lists', 'dualuse_list_versions', 'dualuse_items', 'dualuse_parameters', 'dualuse_hs_map',
              'dualuse_chemicals', 'dualuse_terms'}
    tenant = {'dualuse_screenings', 'dualuse_screening_lines', 'dualuse_decisions', 'dualuse_item_master'}
    assert tables == shared | tenant
    assert all(classify(t) == 'shared' for t in shared) and all(classify(t) == 'tenant' for t in tenant)


def test_invoice_header_detection_totals_and_excel_hs_numbers():
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in (['COMMERCIAL INVOICE'], ['Invoice No 123'], ['Seller: Example Trading'], [],
              ['Description of goods', 'HS Code', 'CAS No.', 'Qty'],
              ['Pressure transducer 0-10 kPa', 9026.2, None, 4], ['Laptop', 8471.3, None, 2],
              ['Live animals', 106.11, None, 1], ['TOTAL', None, None, 7]):
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    header, rows = S.read_table('invoice.xlsx', buf.getvalue())
    assert header[0] == 'Description of goods'
    m = S.guess_mapping(header)
    lines = S.lines_from(rows, m)
    assert [l['hs_code'] for l in lines] == ['9026.20', '8471.30', '0106.11']
    assert all(l.get('hs_warning') for l in lines)
    assert not any((l['description'] or '').upper() == 'TOTAL' for l in lines)


def test_compact_code_and_hs_prefix_queries():
    assert T.control_code('5a002a1') == '5A002.a.1' and T.control_code('5A002A') == '5A002.a'
    assert T.hs_digits('HS 8526') == '8526' and T.normalize_hs(9026.2) == ('902620', 'trailing zero restored')


def test_range_and_unitless_thresholds():
    ps = P.extract_parameters("A maximum 'endurance' greater than or equal to 30 minutes but less than 1 hour", '.')
    assert [(p['parameter'], p['operator'], p['value'], p['unit'], p['upper_op'], p['upper_value'], p['upper_unit'])
            for p in ps] == [('endurance', '>=', 30.0, 'min', '<', 1.0, 'h')]
    ps = P.extract_parameters("wind gusts equal to or exceeding 46,3 km/h (25 knots)", ',')
    assert ps[0]['operator'] == '>=' and ps[0]['unit'] == 'km/h'
    ps = P.extract_parameters("A 'total processing performance' of 1600 or more and a 'performance density' of "
                              "5.92 or more.", '.')
    assert [(p['parameter'], p['value'], p['unit']) for p in ps] == [
        ('total processing performance', 1600.0, None), ('performance density', 5.92, None)]
    q = {'type': 'threshold', 'operator': '>=', 'base_value': 1800.0, 'upper_op': '<', 'upper_base': 3600.0,
         'base_unit': 's', 'unit': 'min'}
    assert SC._threshold_result(q, {'value': '45', 'unit': 'min'}) == 'yes'
    assert SC._threshold_result(q, {'value': '25', 'unit': 'min'}) == 'no'
    assert SC._threshold_result(q, {'value': '2', 'unit': 'h'}) == 'no'
    assert T.quantities('12,000 rpm')[0][0] == 12000.0
