"""Wave 4 review fixes (invented names only)."""
import io

from screening import bulk_jobs as BJ
from screening import media_rank as MR
from kyb import parties_screening as G
from kyb import logic


def _job(store, n):
    jid = store.create_job(1, 'x.csv', ['Name'], [{'Name': f'Test Person {i}'} for i in range(1, n + 1)])
    BJ.prepare(store, jid, {'name': 'Name'})
    return jid


# ---- B2: no formula reaches the export
def test_export_cells_are_not_formulas():
    assert BJ._xl('=HYPERLINK("x")') == "'=HYPERLINK(\"x\")"
    for p in ('+', '-', '@', '\t', '\r'):
        assert BJ._xl(p + '1').startswith("'")
    assert BJ._xl('Ali') == 'Ali' and BJ._xl(5) == 5 and BJ._xl(None) is None
    store = BJ.MemoryStore()
    jid = store.create_job(1, '=cmd.csv', ['Name'], [{'Name': '=1+1'}, {'Name': '@SUM(A1)'}])
    BJ.prepare(store, jid, {'name': 'Name'})
    BJ.run(store, jid, lambda r: {'screening_result': 'CLEAR', 'matches': []}, lambda r, res: 1)
    import openpyxl
    wb = openpyxl.load_workbook(BJ.export_xlsx(store, jid))
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for v in row:
                assert not (isinstance(v, str) and v[:1] in ('=', '+', '-', '@'))


# ---- should-fix 4: end states
def test_row_without_result_fails_with_reason():
    store = BJ.MemoryStore()
    jid = _job(store, 3)
    s = BJ.run(store, jid, lambda r: {'matches': []}, lambda r, res: 1)
    assert s['counts'].get('FAILED') == 3
    assert all('no screening result' in (r.get('error') or '') for r in store.rows[jid])


def test_cancel_during_last_batch_is_kept():
    store = BJ.MemoryStore()
    jid = _job(store, 4)

    def save(r, res):
        store.jobs[jid]['status'] = 'CANCELLED'      # pressed while the last batch runs
        return 1
    BJ.run(store, jid, lambda r: {'screening_result': 'CLEAR', 'matches': []}, save, threads=1, batch=10)
    assert store.job(jid)['status'] == 'CANCELLED'


def test_resume_retries_failed_rows():
    store = BJ.MemoryStore()
    jid = _job(store, 5)
    BJ.run(store, jid, lambda r: (_ for _ in ()).throw(RuntimeError('down')), lambda r, res: 1)
    assert store.retry_failed(jid) == 5
    s = BJ.run(store, jid, lambda r: {'screening_result': 'CLEAR', 'matches': []}, lambda r, res: 1)
    assert s['counts'].get('DONE') == 5 and s['complete']


def test_running_jobs_listed_for_the_concurrency_limit():
    store = BJ.MemoryStore()
    a, b = _job(store, 1), _job(store, 1)
    store.set_status(a, 'RUNNING')
    assert [j['id'] for j in store.running_jobs(exclude=b)] == [a]
    assert store.running_jobs(exclude=a) == []
    assert BJ.MAX_CONCURRENT >= 1


def test_xlsx_row_cap_checked_before_full_parse(monkeypatch):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Name'])
    for i in range(30):
        ws.append([f'Test Person {i}'])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    monkeypatch.setattr(BJ, 'MAX_ROWS', 10)
    try:
        BJ.read_file(buf, 'x.xlsx')
        assert False
    except ValueError as e:
        assert 'limit' in str(e)
    buf.seek(0)
    monkeypatch.setattr(BJ, 'MAX_ROWS', 100)
    h, rows = BJ.read_file(buf, 'x.xlsx')
    assert h == ['Name'] and len(rows) == 30


# ---- should-fix 5: only http(s) links
def test_media_links_http_only():
    out, _info = MR.consolidate([{'title': 'A story about a test case', 'url': 'javascript:alert(1)', 'source': 'X'},
                                 {'title': 'Another unrelated story here', 'link': 'https://example.org/a', 'source': 'Y'}])
    urls = [(s.get('url'), s.get('link')) for s in out]
    assert (None, None) in urls and (None, 'https://example.org/a') in urls
    from screening.routes import _http_only
    assert _http_only('javascript:alert(1)') == '#' and _http_only('data:x') == '#'
    assert _http_only('https://example.org') == 'https://example.org'


# ---- B1 / should-fix 2: a parent status is never lowered by its parties
def test_combined_status_never_lowers():
    cs = G.combined_status
    assert cs('Clear', logic.OPEN) == 'Pending Review'
    assert cs('Clear', logic.PEP) == 'Pending Review'
    assert cs('Clear', logic.NOT_SCREENED) == 'Incomplete'
    assert cs('Pending Review', logic.INCOMPLETE) == 'Pending Review'
    assert cs('Incomplete', logic.CLEAR) == 'Incomplete'
    assert cs('True Match', logic.CLEAR) == 'True Match'          # unknown / more severe kept
    assert cs('Whitelisted', logic.CLEARED) == 'Whitelisted'


def test_customer_route_screens_parties_once_after_its_own_update():
    import inspect
    from aml import routes as R
    src = inspect.getsource(R.run_customer_screening)
    assert 'screen_parties=False' in src
    assert src.index("after_parent_screening('Customer KYC'") > src.index('UPDATE customers')
    from screening import customer_screening_service as S
    assert 'screen_parties' in inspect.signature(S.screen_and_save).parameters


def test_g10_inline_cap(monkeypatch):
    from kyb import service
    people = {'ubo': [{'id': i, 'full_name': f'P{i}'} for i in range(20)], 'signatory': []}
    screened = []
    monkeypatch.setattr(G, 'INLINE_CAP', 5)
    monkeypatch.setattr(service, 'record', lambda s, i, db=None: {'customer_type': 'CORPORATE', 'screening_status': 'Clear'})
    monkeypatch.setattr(service, 'people', lambda kind, s, i, db=None: people[kind])
    monkeypatch.setattr(service, 'screen_person', lambda kind, p, u, db=None, release=True: screened.append(p['id']))
    monkeypatch.setattr(service, '_release_engine_connection', lambda: None)
    monkeypatch.setattr(G, 'overview', lambda s, i, db=None: {'people': [], 'worst': logic.CLEAR, 'counts': {}, 'total': 20})

    class _DB:
        def __init__(self):
            self.sql = []

        def execute(self, q, a=None):
            self.sql.append((q, a))

        def commit(self):
            pass

        def rollback(self):
            pass
    db = _DB()
    out = G.after_parent_screening('Customer KYC', 7, 1, db)
    assert len(screened) == 5 and out['not_screened_now'] == 15
    assert out['status'] == 'Incomplete'
    assert any('Incomplete' in str(a) for _q, a in db.sql)
