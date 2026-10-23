import time

import demo_access as D


def test_token_roundtrip_and_expiry(monkeypatch):
    monkeypatch.setenv('DEMO_LINK_SECRET', 'test-secret-123')
    token, days = D.make_token(3, 'Academy batch')
    data, expires = D.read_token(token)
    assert days == 3 and data['l'] == 'Academy batch'
    assert 2.9 * 86400 < expires - time.time() <= 3 * 86400 + 5
    # tampered or signed with another secret -> rejected
    assert D.read_token(token[:-2] + 'xx') == (None, None)
    monkeypatch.setenv('DEMO_LINK_SECRET', 'other')
    assert D.read_token(token) == (None, None)


def test_days_are_capped_and_no_secret_means_no_links(monkeypatch):
    monkeypatch.setenv('DEMO_LINK_SECRET', 's')
    _t, days = D.make_token(400, '')
    assert days == D.MAX_DAYS
    monkeypatch.delenv('DEMO_LINK_SECRET')
    assert D.read_token('anything') == (None, None)


def test_expired_link(monkeypatch):
    monkeypatch.setenv('DEMO_LINK_SECRET', 's')
    token, _d = D.make_token(1, '')
    real = time.time
    monkeypatch.setattr(D.time, 'time', lambda: real() + 2 * 86400)
    assert D.read_token(token) == (None, None)
