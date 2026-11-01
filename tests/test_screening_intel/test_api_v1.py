"""Screening API v1 (P6-2 / P6-8 / G12): pure helpers — no app, no database."""
import json
import time

import pytest

from api import v1_common as C


def test_request_id_kept_or_generated():
    assert C.request_id_from('abc-123') == 'abc-123'
    rid = C.request_id_from('bad id with spaces')
    assert rid.startswith('req_') and len(rid) == 28
    assert C.request_id_from('x' * 65).startswith('req_')


def test_error_shape():
    b = C.error_body('validation_failed', 'bad', 'req_1', [{'field': 'name'}])
    assert b == {'success': False, 'error': {'code': 'validation_failed', 'message': 'bad',
                                            'details': [{'field': 'name'}]}, 'request_id': 'req_1'}


def test_request_hash_ignores_key_order_but_not_values():
    a = C.request_hash('POST', '/api/v1/screenings', b'{"name": "A", "dob": "1980"}')
    b = C.request_hash('post', '/api/v1/screenings', b'{"dob":"1980","name":"A"}')
    c = C.request_hash('POST', '/api/v1/screenings', b'{"dob":"1981","name":"A"}')
    d = C.request_hash('POST', '/api/v1/payments/screen', b'{"dob":"1980","name":"A"}')
    assert a == b and a != c and a != d


def test_idem_key_validation():
    assert C.valid_idem_key('order-2026-11-01-0001') == 'order-2026-11-01-0001'
    assert C.valid_idem_key('') is None and C.valid_idem_key('a b') is None and C.valid_idem_key('x' * 201) is None


def test_signature_roundtrip_and_tamper():
    body = b'{"type":"screening.completed"}'
    h = C.sign('whsec_x', body, ts=1700000000)
    assert h.startswith('t=1700000000,v1=')
    assert C.verify('whsec_x', body, h, now=1700000010)
    assert not C.verify('whsec_x', body + b' ', h, now=1700000010)       # body changed
    assert not C.verify('whsec_y', body, h, now=1700000010)              # other secret
    assert not C.verify('whsec_x', body, h, now=1700000000 + 3600)       # replayed late


@pytest.mark.parametrize('url,ok', [
    ('https://hooks.example.com/cnx', True),
    ('http://hooks.example.com/cnx', False),
    ('https://127.0.0.1/x', False), ('https://10.1.2.3/x', False), ('https://169.254.169.254/latest', False),
    ('https://[::1]/x', False), ('https://localhost/x', False), ('https://intranet/x', False),
    ('https://user:pw@hooks.example.com/x', False), ('ftp://x.example.com', False),
])
def test_webhook_url_rules(url, ok):
    assert C.check_webhook_url(url, resolve=False)[0] is ok


def _h(tier, code, lt='SANCTIONS', legal=None):
    return {'tier': tier, 'action': {'code': code}, 'list_type': lt, 'legal_status': legal}


def test_payment_decision():
    P = lambda hits, inc=False: {'role': 'payee', 'incomplete': inc, 'hits': hits}
    assert C.payment_decision([P([]), P([])])[0] == 'PASS'
    assert C.payment_decision([P([_h('LOW', 'FREEZE_ESCALATE')])])[0] == 'PASS'
    assert C.payment_decision([P([_h('CONFIRMED', 'FREEZE_ESCALATE')])])[0] == 'BLOCK'
    assert C.payment_decision([P([_h('CONFIRMED', 'FREEZE_REPORT', 'EMLCU')])])[0] == 'BLOCK'
    assert C.payment_decision([P([_h('POTENTIAL', 'FREEZE_ESCALATE')])])[0] == 'HOLD'
    assert C.payment_decision([P([_h('CONFIRMED', 'EDD', 'PEP')])])[0] == 'HOLD'      # PEP: EDD, not a block
    assert C.payment_decision([P([_h('CONFIRMED', 'INFORMATION', 'CONTEXT')])])[0] == 'PASS'
    assert C.payment_decision([P([_h('CONFIRMED', 'FREEZE_ESCALATE', legal='LIFTED')])])[0] == 'PASS'
    # an incomplete party is never passed, and a block wins over a hold
    assert C.payment_decision([P([], inc=True)])[0] == 'HOLD'
    assert C.payment_decision([P([], inc=True), P([_h('CONFIRMED', 'FREEZE_ESCALATE')])])[0] == 'BLOCK'


def test_screening_view_incomplete_never_clear():
    res = {'screening_result': 'CLEAR', 'matches': [],
           'incomplete_reasons': [{'code': 'search_index', 'en': 'x', 'ar': 'y'}]}
    v = C.screening_view(7, res, {'name': 'A'}, 'req_1', {'un': 3})
    assert v['status'] == 'INCOMPLETE' and v['incomplete'] and v['requires_review']
    assert v['list_versions'] == {'un': 3} and v['id'] == 7


def test_sandbox_cases():
    assert C.sandbox_result('Ahmed Ali')['screening_result'] == 'CLEAR'
    hit = C.sandbox_result('test hit person')
    v = C.screening_view(1, hit, {}, 'r', {}, sandbox=True)
    assert v['hits'][0]['tier'] == 'CONFIRMED' and v['hits'][0]['action']['code'] == 'FREEZE_ESCALATE'
    assert C.screening_view(1, C.sandbox_result('TEST INCOMPLETE'), {}, 'r', {})['incomplete']
    pep = C.screening_view(1, C.sandbox_result('TEST PEP'), {}, 'r', {})
    assert C.payment_decision([{'role': 'payer', 'incomplete': False, 'hits': pep['hits']}])[0] == 'HOLD'


def test_parse_screening_input():
    f, e = C.parse_screening_input({'name': ' محمد علي ', 'entity_type': 'company', 'dob': '1980-02'})
    assert not e and f['name'] == 'محمد علي' and f['entity_type'] == 'ENTITY' and f['dob'] == '1980-02'
    f, e = C.parse_screening_input({'entity_type': 'alien', 'dob': '02/1980'})
    assert {x['field'] for x in e} == {'name', 'entity_type', 'dob'}
    assert C.parse_screening_input(['x'])[1]
    f, e = C.parse_screening_input({'name': {'nested': 1}})
    assert e and e[0]['field'] == 'name'


def test_hit_view_hides_internal_fields():
    m = {'full_name': 'X', 'source': 'un', 'source_id': 'un_ind_1', 'match_score': 91.234, 'id': 99,
         'decision': {'tier': 'POTENTIAL'}, 'national_id_numbers': '["123"]'}
    h = C.hit_view(m)
    assert h['score'] == 91.23 and h['list_reference'] == 'un_ind_1'
    assert 'national_id_numbers' not in h and 'id' not in h


def test_webhook_delivery_flow(monkeypatch):
    """deliver_due: 2xx delivers, an error schedules a retry, the last attempt goes DEAD."""
    from api import webhooks as WH

    class Cur:
        def __init__(s, rows):
            s.rows, s.updates = rows, []
        def execute(s, sql, args=None):
            if sql.lstrip().startswith('UPDATE'):
                s.updates.append((sql, args))
        def fetchall(s):
            return s.rows

    class Conn:
        def __init__(s, cur):
            s.cur = cur
        def cursor(s, cursor_factory=None):
            return s.cur
        def commit(s):
            pass

    monkeypatch.setattr(WH, 'unseal', lambda t: 'whsec_test')
    seen = {}

    class R:
        def __init__(s, code):
            s.status_code = code

    def post(url, body, headers):
        seen['sig'] = headers['X-ComplyNex-Signature']
        seen['body'] = body
        return R(200 if 'ok' in url else 500)
    base = {'event': 'screening.completed', 'payload': {'id': 'evt_1'}, 'secret_enc': 'x', 'is_active': True}
    rows = [dict(base, id=1, webhook_id=1, attempts=0, url='https://ok.example.com'),
            dict(base, id=2, webhook_id=2, attempts=0, url='https://bad.example.com'),
            dict(base, id=3, webhook_id=2, attempts=WH.MAX_ATTEMPTS - 1, url='https://bad.example.com')]
    cur = Cur(rows)
    out = WH.deliver_due(Conn(cur), post=post, check_url=lambda u: (True, ''))
    assert out == {'delivered': 1, 'retry': 1, 'dead': 1}
    assert C.verify('whsec_test', seen['body'], seen['sig'])
    kinds = [u[0].split('SET')[1].split(',')[0].strip() for u in cur.updates]
    assert kinds == ["status = 'DELIVERED'", 'attempts = %s', "status = 'DEAD'"]
