"""Dual-use goods module: text handling, parsers, bilingual search and screening logic (no database)."""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from packs.trade_control import parsers as P
from packs.trade_control import screening as SC
from packs.trade_control import search as SE
from packs.trade_control import service as S
from packs.trade_control import text as T


# ------------------------------------------------------------------ text
def test_arabic_normalisation_and_stemming():
    assert T.norm_ar('إِشْعَاعٌ') == 'اشعاع'
    assert T.norm_ar('أجهزة') == 'اجهزه'
    toks = [t for t, _ in T.tokens('والمخرطات الرقمية')]
    assert 'مخرط' in toks[0] or toks[0].startswith('مخرط')
    assert [t for t, _ in T.tokens('١٢٣')] == ['123']


def test_english_tokens_keep_codes_and_pieces():
    toks = [t for t, _ in T.tokens('5A002.a routers and high-speed cameras')]
    assert '5a002.a' in toks and '5a002' in toks
    assert 'router' in toks and 'camera' in toks and 'speed' in toks


def test_identifiers():
    assert T.control_code('5a002 a 1') == '5A002.a.1'
    assert T.control_code('5A002.a.') == '5A002.a'
    assert T.control_code('hello') is None
    assert T.cas_valid('7719-09-7') and not T.cas_valid('7719-09-8')
    assert T.find_cas('thionyl chloride (CAS 7719-09-7)') == ['7719-09-7']
    assert T.hs_digits('8517.62') == '851762'
    assert T.hs_digits('8517 62 00 00') == '8517620000'
    assert T.hs_digits('12') is None
    assert T.looks_like_model('XC7K325T') and not T.looks_like_model('lathe')


def test_units_and_quantities():
    assert T.to_base(10, 'GHz') == (1e10, 'Hz')
    assert T.to_base(500, 'µm')[1] == 'm'
    assert T.to_base(3, 'bar')[0] == pytest.approx(3e5)
    assert T.to_base(1, 'furlong') == (None, None)
    q = T.quantities('frequency synthesizer 40 GHz, output 5 mw')
    assert (4e10, 'Hz') in [(v, b) for v, b, _ in q]
    assert any(b == 'W' for _, b, _ in q)
    q = T.quantities('مولد اشارة ١٠ جيجاهرتز')
    assert q and q[0][0] == pytest.approx(1e10) and q[0][1] == 'Hz'
    assert T.compare(5, '>', 3) and not T.compare(5, '<=', 3) and T.compare(None, '>', 1) is None


def test_snippet_escapes_and_marks():
    s = T.snippet('Routers <script>x</script> with encryption', ['encryption'])
    assert '<script>' not in s and '<mark>encryption</mark>' in s
    s = T.snippet('أجهزة التشفير المتقدمة', ['تشفير'])
    assert '<mark>' in s


# ------------------------------------------------------------------ parsers
def test_extract_parameters():
    ps = P.extract_parameters('having a "peak power" exceeding 1 kW and a frequency of 8 GHz or more', '.')
    ops = {(p['operator'], p['value'], p['unit']) for p in ps}
    assert ('>', 1.0, 'kW') in ops and ('>=', 8.0, 'GHz') in ops
    ps = P.extract_parameters('accuracy less than 6 µm', '.')
    assert ps and ps[0]['operator'] == '<' and ps[0]['unit'] == 'µm'
    ps = P.extract_parameters('exceeding 2,5 GHz', ',')
    assert ps[0]['value'] == 2.5


def test_eu_annex_html_parser():
    html = """<table><tr><td>5A002</td><td>"Information security" systems as follows:
      <table><tr><td>a.</td><td>Designed to use cryptography with a key length exceeding 56 bits
        <table><tr><td>1.</td><td>Not used</td></tr></table></td></tr>
      <tr><td>Note:</td><td>5A002 does not control smart cards.</td></tr></table></td></tr></table>"""
    recs = {r['code']: r for r in P.parse_eu_annex1(html)}
    assert set(recs) == {'5A002', '5A002.a', '5A002.a.1'}
    assert recs['5A002.a']['parent'] == '5A002' and recs['5A002.a']['parameters']
    assert recs['5A002.a.1']['not_used']
    assert recs['5A002']['notes_en'] and recs['5A002']['category'] == '5' and recs['5A002']['group'] == 'A'


def test_correlation_parser():
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['CN', 'Footnote', 'Dual-use'])
    ws.append(['8517 62 00', 'DU001', '5A002a; 5A002.b'])
    ws.append(['2812 17 00', None, '1C350.9'])
    buf = io.BytesIO()
    wb.save(buf)
    rows = P.parse_correlation(buf.getvalue(), {'5A002', '5A002.a', '1C350'})
    codes = {(r['cn10'], r['control_code'], r['resolved_code']) for r in rows}
    assert ('8517620000', '5A002.a', '5A002.a') in codes
    assert ('8517620000', '5A002.b', '5A002') in codes          # unknown sub-item -> nearest parent
    assert ('2812170000', '1C350.9', '1C350') in codes


def test_chpl_text_parser_and_seed():
    txt = "TIER 1\n  HS code   Description\nElectronic integrated circuits:\n   8542.31   Processors and controllers\n" \
          "TIER 2\n   8517.62   Machines for the reception\n  and transmission of data\n"
    recs = P.parse_chpl_text(txt)
    assert [(r['tier'], r['hs6']) for r in recs] == [('1', '854231'), ('2', '851762')]
    assert recs[1]['description_en'].endswith('and transmission of data')
    seed = P.chpl_seed()
    assert len(seed) == 50 and all(len(r['hs6']) == 6 for r in seed)


def test_cwc_parser():
    page = """<div>A. Toxic chemicals:</div><p>(1)</p><p>O-Alkyl phosphonofluoridates</p><p>e.g.</p>
      <p>Sarin: O-Isopropyl methylphosphonofluoridate</p><p>(107-44-8)</p>
      <p>B. Precursors:</p><p>(14)</p><p>Thionyl chloride</p><p>(7719-09-7)</p><p>Download</p>"""
    recs = P.parse_cwc({1: page})
    by_cas = {r['cas']: r for r in recs}
    assert by_cas['107-44-8']['common_name_en'] == 'Sarin' and by_cas['107-44-8']['part'] == 'A'
    assert by_cas['7719-09-7']['part'] == 'B' and by_cas['7719-09-7']['item'] == 14


def test_ccl_parser():
    xml = ('<DIV9 N="Supplement No. 1 to Part 774"><HD1>Category 5 &#x2014;Telecommunications</HD1>'
           '<FP-2><B>5A002 “Information security” systems</B></FP-2><P>Reason for Control: NS, AT, EI</P>'
           '<P>Items:</P><P>a. Designed to use cryptography exceeding 56 bits</P><P>b. Routers</P>'
           '</DIV9><DIV9 N="Supplement No. 2 to Part 774"></DIV9>')
    recs = P.parse_ccl(xml)
    assert recs[0]['code'] == '5A002' and recs[0]['reasons'] == ['AT', 'EI', 'NS']
    assert recs[0]['category_title'] == 'Telecommunications'
    assert [s['code'] for s in recs[0]['sub_items']] == ['5A002.a', '5A002.b']


def test_build_chemicals():
    chem = P.build_chemicals([{'code': '1C350.9', 'text_en': 'Thionyl chloride (CAS 7719-09-7);'}],
                             [{'cas': '7719-09-7', 'schedule': 3, 'part': 'B', 'item': 14, 'name_en': 'Thionyl chloride',
                               'common_name_en': None}], [])
    assert chem[0]['cas'] == '7719-09-7' and chem[0]['cwc_schedule'] == 3 and chem[0]['ag_precursor']


# ------------------------------------------------------------------ search
def _docs():
    return [
        dict(id=1, list_code='eu_annex1', code='5A002', level=0, category='5', group='A',
             title_en='"Information security" systems, equipment and components', text_en='Cryptography systems as follows',
             risk='medium', kind='item', hs=['8517620000']),
        dict(id=2, list_code='eu_annex1', code='5A002.a', level=1, parent_code='5A002', entry_code='5A002', category='5',
             group='A', text_en='Designed to use cryptography with a symmetric key length exceeding 56 bits',
             risk='medium', kind='item', hs=['8517620000'],
             params=[{'parameter': 'key length', 'operator': '>', 'value': 56, 'unit': 'bits',
                      'base_value': 56, 'base_unit': 'bit'}]),
        dict(id=3, list_code='us_ccl', code='5A002', level=0, category='5', group='A',
             title_en='Information security systems', text_en='Encryption items', risk='medium', kind='item'),
        dict(id=4, list_code='eu_annex1', code='2B001', level=0, category='2', group='B',
             title_en='Machine tools for removing or cutting metals (lathes, milling machines)',
             text_en='Numerically controlled lathes having positioning accuracy less than 6 µm', risk='medium',
             kind='item', params=[{'parameter': 'positioning accuracy', 'operator': '<', 'value': 6, 'unit': 'µm',
                                   'base_value': 6e-6, 'base_unit': 'm'}]),
        dict(id=5, list_code='eu_annex1', code='3A002.d', level=1, entry_code='3A002', category='3', group='A',
             text_en='Frequency synthesizer assemblies with an output frequency exceeding 31.8 GHz', risk='medium',
             kind='item', params=[{'parameter': 'output frequency', 'operator': '>', 'value': 31.8, 'unit': 'GHz',
                                   'base_value': 3.18e10, 'base_unit': 'Hz'}]),
        dict(id='c1', list_code='chemicals', code='7719-09-7', level=0, category='1', group='C',
             title_en='Thionyl chloride', text_en='Thionyl chloride', cas=['7719-09-7'], risk='high', kind='chemical',
             extra={'names': ['Thionyl chloride'], 'cwc_schedule': 3, 'ag_precursor': True, 'item_codes': ['1C350.9']}),
        dict(id='p1', list_code='chpl', code='8542.31', level=0, title_en='Processors and controllers',
             text_en='Electronic integrated circuits: processors and controllers', hs=['854231'], risk='high',
             kind='priority', extra={'tier': '1'}),
    ]


TERMS = [('lathe', 'مخرطة'), ('encryption', 'تشفير'), ('cryptography', 'تشفير'), ('machine tool', 'آلة تشغيل'),
         ('drone', 'طائرة بدون طيار'), ('unmanned aerial vehicle', 'طائرة بدون طيار')]


@pytest.fixture(scope='module')
def idx():
    return SE.Index(_docs(), TERMS)


def test_exact_code_first_and_children(idx):
    r = idx.search('5a002')
    assert r['exact'] == 'code'
    assert r['results'][0]['doc'].code == '5A002'
    assert r['results'][0]['also']                       # the same code in a second list is merged
    assert any(x['doc'].code == '5A002.a' for x in r['results'])


def test_cas_and_hs(idx):
    r = idx.search('7719-09-7')
    assert r['exact'] == 'cas' and r['results'][0]['doc'].code == '7719-09-7'
    r = idx.search('8517.62')
    assert r['exact'] == 'hs' and {x['doc'].code for x in r['results']} >= {'5A002'}
    r = idx.search('854231')
    assert r['results'][0]['doc'].kind == 'priority'


def test_arabic_query_finds_english_entries(idx):
    r = idx.search('مخرطة')
    assert r['results'] and r['results'][0]['doc'].code == '2B001'
    assert 'translated' in r['results'][0]['why']
    r = idx.search('تشفير')
    assert r['results'][0]['doc'].code.startswith('5A002')


def test_two_hop_synonyms_and_typos(idx):
    docs = _docs() + [dict(id=9, list_code='eu_annex1', code='9A012', level=0, category='9', group='A',
                           title_en='Unmanned aerial vehicles', text_en='UAV systems', kind='item', risk='medium')]
    ix = SE.Index(docs, TERMS)
    assert ix.search('drone')['results'][0]['doc'].code == '9A012'
    r = idx.search('cryptograhpy')                       # typo
    assert r['results'] and r['results'][0]['doc'].code.startswith('5A002')


def test_threshold_from_query_value(idx):
    r = idx.search('frequency synthesizer 40 GHz')
    top = r['results'][0]
    assert top['doc'].code == '3A002.d' and 'threshold' in top['why']
    r = idx.search('frequency synthesizer 20 GHz')
    assert 'threshold' not in r['results'][0]['why']


def test_lists_hidden_from_clients(idx):
    assert 'list' not in idx.search('lathe')['facets']
    assert 'list' in idx.search('lathe', show_lists=True)['facets']
    # a client cannot filter by list
    assert idx.search('5A002', {'list': 'us_ccl'})['total'] == idx.search('5A002')['total']


def test_browse_by_filter_and_suggest(idx):
    r = idx.search('', {'category': '5'})
    assert r['exact'] == 'browse' and {x['doc'].code for x in r['results']} == {'5A002'}
    s = idx.suggest('5A0')
    assert s and s[0]['type'] == 'code' and s[0]['value'].startswith('5A002')
    s = idx.suggest('encr')
    assert any(x['value'].startswith('encryption') for x in s)
    assert idx.suggest('x') == []


def test_highlight_in_results(idx):
    r = idx.search('numerically controlled lathe')
    assert '<mark>' in r['results'][0]['snippet_en']


# ------------------------------------------------------------------ screening
def test_screening_hs_candidates_and_questions(idx):
    res = SC.screen_line(idx, {'description': 'network router with encryption', 'hs_code': '8517.62.00'})
    codes = [c['code'] for c in res['candidates']]
    assert '5A002' in codes or '5A002.a' in codes
    assert res['suggested'] == 'review'
    assert res['questions'] and len(res['questions']) <= SC.MAX_QUESTIONS
    # every candidate gets the entry-level question; thresholds only when they relate to the description
    assert any(q['type'] == 'describes' and q['code'].startswith('5A002') for q in res['questions'])
    res = SC.screen_line(idx, {'description': 'cryptography with key length of 128 bits', 'hs_code': '8517.62.00'})
    q = next(q for q in res['questions'] if q['type'] == 'threshold')
    assert q['operator'] == '>' and q['value'] == 56


def test_screening_answers_drive_outcome(idx):
    res = SC.screen_line(idx, {'description': 'lathe', 'hs_code': ''})
    qs = res['questions']
    assert qs
    no = {q['id']: 'no' for q in qs}
    assert SC.evaluate(res['candidates'], res['hard'], qs, no)[0] in ('clear', 'review')
    yes = {qs[0]['id']: 'yes'}
    assert SC.evaluate(res['candidates'], res['hard'], qs, yes)[0] == 'hold'
    tq = next(q for q in qs if q['type'] == 'threshold' and q['code'] == '2B001')
    val = {tq['id']: {'value': '4', 'unit': 'µm'}}         # 4 µm accuracy is better than 6 µm: controlled
    assert SC.evaluate(res['candidates'], res['hard'], qs, val)[0] == 'hold'
    val = {tq['id']: {'value': '0.01', 'unit': 'mm'}}      # 10 µm: not controlled by this threshold
    sug, state = SC.evaluate(res['candidates'], res['hard'], qs, val)
    # below the asked threshold is the user's declaration, never a clear: the entry is not ruled out
    assert state[('eu_annex1', '2B001')] == 'below' and sug == 'review'
    dq = next(q for q in qs if q['type'] == 'describes' and q['code'] == '2B001')
    sug, state = SC.evaluate(res['candidates'], res['hard'], qs, {dq['id']: 'no'})
    assert state[('eu_annex1', '2B001')] == 'cleared'


def test_screening_cas_and_priority_are_hard_flags(idx):
    res = SC.screen_line(idx, {'description': 'chemical', 'cas': '7719-09-7'})
    flags = {h['flag'] for h in res['hard']}
    assert {'cwc', 'precursor'} <= flags and res['suggested'] == 'hold'
    res = SC.screen_line(idx, {'description': 'cpu', 'hs_code': '8542.31.10'})
    assert any(h['flag'] == 'priority' for h in res['hard'])
    # a high-priority tariff heading is a risk indicator: review, never an automatic hold or clear
    assert SC.batch_suggestion(res) == 'review' and res['suggested'] == 'review'


def test_no_candidate_is_clear_and_key_is_stable(idx):
    res = SC.screen_line(idx, {'description': 'cotton t-shirts', 'hs_code': '6109.10'})
    assert res['candidates'] == [] and res['suggested'] == 'clear'
    a = SC.line_key({'description': 'Cotton T-Shirts', 'hs_code': '6109.10'})
    b = SC.line_key({'description': 'cotton  t-shirts', 'hs_code': '610910'})
    assert a == b and SC.line_key({}) is None


# ------------------------------------------------------------------ service helpers (no database)
def test_decision_validation():
    assert S.validate_decision('clear', 'not_controlled', 'Checked datasheet: key 40 bits') == []
    errs = S.validate_decision('maybe', 'nope', 'short')
    assert len(errs) == 3


def test_batch_file_helpers():
    data = 'Item description,HS Code,Qty,Model\nFibre laser 2 kW,8456.11,1,FL-2000\n,,,\nCotton shirts,6109.10,500,\n'
    header, rows = S.read_table('invoice.csv', data.encode('utf-8'))
    m = S.guess_mapping(header)
    assert m['description'] == 0 and m['hs_code'] == 1 and m['quantity'] == 2 and m['model'] == 3
    lines = S.lines_from(rows, m)
    assert len(lines) == 2 and lines[0]['model'] == 'FL-2000'
    ar = 'الوصف,البند\nمخرطة,8458.11\n'.encode('utf-8')
    h, r = S.read_table('a.csv', ar)
    assert S.guess_mapping(h) == {'description': 0, 'hs_code': 1}
    with pytest.raises(ValueError):
        S.read_table('x.pdf', b'%PDF')


def test_same_code_in_two_lists_is_one_candidate_and_values_prefill(idx):
    res = SC.screen_line(idx, {'description': 'information security cryptography system', 'hs_code': '8517.62'})
    codes = [c['code'] for c in res['candidates']]
    # 5A002 (both lists) and its sub-item 5A002.a: one candidate, the more precise one, with every list
    assert codes.count('5A002.a') == 1 and '5A002' not in codes
    c = next(c for c in res['candidates'] if c['code'] == '5A002.a')
    assert 'eu_annex1' in c['lists'] and {'hs', 'text'} <= set(c['reasons'])
    merged = SC._drop_ancestors({'5a002': dict(code='5A002', reasons=['text'], strength=0.6, lists=['us_ccl']),
                                 '5a002.a': dict(code='5A002.a', reasons=['hs'], strength=0.4, lists=['eu_annex1'])})
    assert list(merged) == ['5a002.a'] and merged['5a002.a']['lists'] == ['eu_annex1', 'us_ccl']
    assert merged['5a002.a']['reasons'] == ['hs', 'text'] and merged['5a002.a']['strength'] == 0.6
    res = SC.screen_line(idx, {'description': 'frequency synthesizer, output frequency 40 GHz'})
    q = next(q for q in res['questions'] if q['code'] == '3A002.d')
    assert res['answers'][q['id']]['auto'] and res['suggested'] == 'hold'
    assert len({q['text_en'] for q in res['questions']}) == len(res['questions'])
