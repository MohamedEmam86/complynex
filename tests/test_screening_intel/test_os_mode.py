"""Daily OpenSanctions comparison by mode (off / partial / on) and the PEP-feed source fix."""
import json

from screening.format_handlers import OpenSanctionsHandler
from screening.data_updater_enhanced import EnhancedDataUpdater as U


class _Cur:
    def __init__(self, rows):
        self.rows = rows
        self._out = []

    def execute(self, sql, params=None):
        if sql.strip().startswith('SELECT source_id'):
            src, ids = params[0], params[1:]
            self._out = [dict(r) for r in self.rows if r['source'] == src and r['source_id'] in ids]

    def fetchall(self):
        return self._out


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self, *a, **k):
        return _Cur(self.rows)


def _updater(rows, mode):
    u = U.__new__(U)
    u.db_conn = _Conn(rows)
    u.placeholder = '%s'
    u.calls = []
    u._os_rich_mode = lambda: mode
    u._update_entity = lambda e, c: u.calls.append(('update', e['source'], e['source_id']))
    u._store_rich = lambda e, c, s: u.calls.append(('rich', s, e['source_id'])) if e.get('_rich') else None
    u._batch_insert_entities = lambda es, c, s=None: u.calls.extend(('insert', s, e['source_id']) for e in es)
    return u


def _ent(caption='Ana Test', names=('Ana Test', 'Test Ana'), rich=True, eid='e1'):
    d = {'id': eid, 'caption': caption, 'schema': 'Person', 'datasets': ['x'],
         'properties': {'name': list(names), 'topics': ['sanction']}}
    return OpenSanctionsHandler(rich=rich)._parse_line(json.dumps(d))


def test_pep_feed_updates_its_own_rows():
    rows = [{'source': 'opensanctions_pep', 'source_id': 'OS-e1', 'id': 1, 'full_name': 'old', 'content_hash': None}]
    u = _updater(rows, 'off')
    u._import_entities_batch([_ent(rich=False)], 'opensanctions_pep')
    assert ('update', 'opensanctions_pep', 'OS-e1') in u.calls       # not the main feed's row


def test_partial_mode_rows_without_hash_only_on_name_change():
    e = _ent()
    rows = [{'source': 'opensanctions', 'source_id': 'OS-e1', 'id': 1, 'full_name': 'Ana Test', 'content_hash': None}]
    u = _updater(rows, 'partial')
    assert u._import_entities_batch([e], 'opensanctions') == (0, 0, 1)
    rows[0]['full_name'] = 'Test Ana'
    u = _updater(rows, 'partial')
    assert u._import_entities_batch([_ent()], 'opensanctions') == (0, 1, 0)


def test_rows_with_hash_compared_on_it_and_on_mode_rewrites_unhashed():
    e = _ent()
    h = U._content_hash(e)
    rows = [{'source': 'opensanctions', 'source_id': 'OS-e1', 'id': 1, 'full_name': 'Ana Test', 'content_hash': h}]
    for mode in ('partial', 'on'):
        assert _updater(rows, mode)._import_entities_batch([_ent()], 'opensanctions') == (0, 0, 1)
    rows[0]['content_hash'] = 'stale'
    assert _updater(rows, 'partial')._import_entities_batch([_ent()], 'opensanctions') == (0, 1, 0)
    rows[0]['content_hash'] = None
    assert _updater(rows, 'on')._import_entities_batch([_ent()], 'opensanctions') == (0, 1, 0)


def test_off_mode_drops_rich_and_compares_names_only():
    rows = [{'source': 'opensanctions', 'source_id': 'OS-e1', 'id': 1, 'full_name': 'Ana Test', 'content_hash': None}]
    u = _updater(rows, 'off')
    assert u._import_entities_batch([_ent()], 'opensanctions') == (0, 0, 1)
    assert not any(c[0] == 'rich' for c in u.calls)
