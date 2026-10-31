"""P4-9 bulk screening and P4-8 adverse-media consolidation (invented names only)."""
import io
import threading

from screening import bulk_jobs as BJ
from screening import media_rank as MR


# ------------------------------------------------------------------ bulk: file + mapping
def test_guess_mapping_en_and_ar():
    m = BJ.guess_mapping(['Full Name', 'Type', 'Date of Birth', 'Country', 'National ID', 'Customer ID'])
    assert m == {'name': 'Full Name', 'entity_type': 'Type', 'dob': 'Date of Birth', 'nationality': 'Country',
                 'national_id': 'National ID', 'customer_ref': 'Customer ID'}
    m = BJ.guess_mapping(['الاسم', 'تاريخ الميلاد', 'الجنسية', 'الرقم القومي', 'رقم العميل'])
    assert m['name'] == 'الاسم' and m['dob'] == 'تاريخ الميلاد' and m['nationality'] == 'الجنسية'
    assert m['national_id'] == 'الرقم القومي' and m['customer_ref'] == 'رقم العميل'


def test_read_csv_keeps_ids_and_blanks():
    data = 'Name,ID,DOB\nTarek Fawzy Nour,29001011234567,1990-01-01\n,,\n'.encode('utf-8-sig')
    headers, rows = BJ.read_file(io.BytesIO(data), 'x.csv')
    assert headers == ['Name', 'ID', 'DOB']
    assert rows[0]['ID'] == '29001011234567' and rows[1]['Name'] == ''


def test_read_rejects_other_types_and_too_many_rows(monkeypatch):
    try:
        BJ.read_file(io.BytesIO(b'x'), 'x.pdf')
        assert False
    except ValueError:
        pass
    monkeypatch.setattr(BJ, 'MAX_ROWS', 2)
    try:
        BJ.read_file(io.BytesIO(b'Name\na\nb\nc\n'), 'x.csv')
        assert False
    except ValueError as e:
        assert 'limit' in str(e)


def test_cell_cleanup():
    assert BJ._cell(29001011234567.0) == '29001011234567'
    assert BJ._cell(float('nan')) == ''
    assert BJ._cell('1980-05-01 00:00:00') == '1980-05-01'


def test_entity_type_words():
    assert BJ.entity_type_of('Company') == 'ENTITY'
    assert BJ.entity_type_of('شركة') == 'ENTITY'
    assert BJ.entity_type_of('') == 'INDIVIDUAL'
    assert BJ.entity_type_of('', 'ENTITY') == 'ENTITY'


# ------------------------------------------------------------------ bulk: run
def _job(store, n, empty_every=0):
    rows = []
    for i in range(n):
        name = '' if empty_every and i % empty_every == 0 else f'Invented Person {i} Example'
        rows.append({'Name': name, 'Ref': f'R{i}'})
    jid = store.create_job(1, 'test.csv', ['Name', 'Ref'], rows)
    BJ.prepare(store, jid, {'name': 'Name', 'customer_ref': 'Ref'})
    return jid


def test_every_row_accounted_for_with_failures():
    store = MemStore = BJ.MemoryStore()
    jid = _job(store, 103, empty_every=10)

    def screen(row):
        n = int(row['name'].split()[2])
        if n % 7 == 0:
            raise RuntimeError('engine error')
        st = 'POTENTIAL_MATCH' if n % 5 == 0 else ('INCOMPLETE' if n % 11 == 0 else 'CLEAR')
        return {'screening_result': st, 'highest_score': 80 if st == 'POTENTIAL_MATCH' else 0,
                'matches': [1] if st == 'POTENTIAL_MATCH' else [], 'incomplete': st == 'INCOMPLETE'}

    saved = []
    lock = threading.Lock()

    def save(row, res):
        with lock:
            saved.append(row['row_no'])
            return 1000 + row['row_no']

    s = BJ.run(store, jid, screen, save, threads=4, batch=7)
    st = s['counts']
    assert s['rows_in'] == 103 and s['rows_out'] == 103 and s['left'] == 0 and s['complete']
    assert st['SKIPPED'] == 11                       # rows 1, 11, 21 ... (empty names)
    assert st['FAILED'] > 0 and st['DONE'] + st['FAILED'] == 92
    assert len(saved) == st['DONE']
    assert store.job(jid)['status'] == 'DONE'
    rep = store.rows_for_report(jid)
    assert all(r['status'] == 'FAILED' or r.get('result_status') in BJ.FLAGGED for r in rep)
    assert any(r.get('result_status') == 'INCOMPLETE' for r in rep)
    assert all(r.get('error') for r in rep if r['status'] == 'FAILED')


def test_incomplete_never_reads_clear():
    store = BJ.MemoryStore()
    jid = _job(store, 3)
    BJ.run(store, jid, lambda r: {'screening_result': 'CLEAR', 'incomplete': True, 'matches': []},
           lambda r, res: 1)
    assert all(r['result_status'] == 'INCOMPLETE' for r in store.rows[jid])


def test_resume_after_interrupted_worker():
    store = BJ.MemoryStore()
    jid = _job(store, 10)
    # a worker died after claiming 4 rows
    store.claim(jid, 4)
    calls = []
    s = BJ.run(store, jid, lambda r: calls.append(r['row_no']) or {'screening_result': 'CLEAR', 'matches': []},
               lambda r, res: 1)
    assert sorted(calls) == list(range(1, 11)) and s['complete']


def test_cancel_stops_and_keeps_status():
    store = BJ.MemoryStore()
    jid = _job(store, 50)
    state = {'n': 0}

    def stop():
        state['n'] += 1
        return state['n'] > 2

    s = BJ.run(store, jid, lambda r: {'screening_result': 'CLEAR', 'matches': []}, lambda r, res: 1,
               threads=1, batch=5, stop=stop)
    assert store.job(jid)['status'] == 'CANCELLED'
    assert s['counts'].get('DONE') == 10 and s['counts'].get('PENDING') == 40


def test_prepare_requires_name_and_records_warnings():
    store = BJ.MemoryStore()
    jid = store.create_job(1, 'x.csv', ['N'], [{'N': 'Ab'}, {'N': 'Invented Person Example'}])
    try:
        BJ.prepare(store, jid, {})
        assert False
    except ValueError:
        pass
    s = BJ.prepare(store, jid, {'name': 'N'})
    assert s['total'] == 2 and s['to_screen'] == 2
    assert s['with_warnings'] >= 1          # one word / too short
    assert store.rows[jid][0]['input_warnings']


def test_export_has_three_sheets():
    import pandas as pd
    store = BJ.MemoryStore()
    jid = _job(store, 5)
    BJ.run(store, jid, lambda r: {'screening_result': 'POTENTIAL_MATCH', 'highest_score': 82, 'matches': [1]},
           lambda r, res: 7)
    out = BJ.export_xlsx(store, jid)
    x = pd.ExcelFile(out)
    assert x.sheet_names == ['Summary', 'Hits, incomplete, failed', 'All rows']
    assert len(pd.read_excel(x, 'All rows')) == 5


# ------------------------------------------------------------------ media
def _a(title, url, src, date='2026-10-01T10:00:00', nm='exact', sev=3):
    return {'title': title, 'url': url, 'source': src, 'published_at': date, 'name_match': nm, 'severity': sev}


def test_same_url_and_tracking_params_merge():
    s, info = MR.consolidate([_a('X arrested', 'https://www.a.com/n/1?utm_source=g', 'A'),
                              _a('X arrested', 'https://a.com/n/1', 'A')])
    assert len(s) == 1 and info['duplicates_merged'] == 1


def test_same_story_across_outlets_kept_once_with_outlets():
    arts = [_a('Invented Trader charged with fraud in Cairo court - Outlet One', 'https://one.com/1', 'Outlet One'),
            _a('Invented Trader charged with fraud in Cairo court - Outlet Two', 'https://two.com/9', 'Outlet Two'),
            _a('Invented Trader charged with fraud in Cairo court today', 'https://three.com/x', 'Three News')]
    s, info = MR.consolidate(arts)
    assert len(s) == 1 and s[0]['outlets'] == 3
    assert {o['source'] for o in s[0]['also_reported_by']} == {'Outlet Two', 'Three News'} or \
        len(s[0]['also_reported_by']) == 2


def test_different_stories_not_merged_and_ranked():
    arts = [_a('Company results announced', 'https://a.com/2', 'A', nm='partial', sev=1),
            _a('Invented Trader sanctioned for terror financing', 'https://b.com/3', 'B', nm='exact', sev=3)]
    s, _ = MR.consolidate(arts)
    assert len(s) == 2 and s[0]['url'] == 'https://b.com/3'


def test_cap():
    words = ['alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot', 'golf', 'hotel', 'india', 'juliet',
             'kilo', 'lima', 'mike', 'november', 'oscar', 'papa', 'quebec', 'romeo', 'sierra', 'tango',
             'uniform', 'victor', 'whiskey', 'xray', 'yankee', 'zulu', 'amber', 'cobalt', 'violet', 'sienna']
    arts = [_a(f'{w} {words[(i + 7) % 30]} {words[(i + 13) % 30]} story', f'https://x.com/{i}', 'X')
            for i, w in enumerate(words)]
    s, info = MR.consolidate(arts, cap=20)
    assert len(s) == 20 and info['over_cap'] == 10


def test_bad_input_never_raises():
    s, info = MR.consolidate([None, {}, {'title': None, 'url': None}, 'x'])
    assert isinstance(s, list)
    assert MR.canonical_url(None) == ''
