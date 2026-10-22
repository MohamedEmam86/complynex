import os
import importlib


def test_demo_flag_env(monkeypatch):
    from utils import demo
    monkeypatch.delenv('COMPLYNEX_DEMO', raising=False)
    monkeypatch.setattr(demo, '_MARKER', '/nonexistent/.demo_instance')
    assert not demo.is_demo()
    assert demo.skip_in_demo('x') is False
    monkeypatch.setenv('COMPLYNEX_DEMO', '1')
    assert demo.is_demo()
    assert demo.skip_in_demo('x') is True


def test_demo_flag_marker(monkeypatch, tmp_path):
    from utils import demo
    monkeypatch.delenv('COMPLYNEX_DEMO', raising=False)
    m = tmp_path / '.demo_instance'
    m.write_text('')
    monkeypatch.setattr(demo, '_MARKER', str(m))
    assert demo.is_demo()


def test_update_lock(monkeypatch, tmp_path):
    from screening import update_lock as ul
    monkeypatch.setattr(ul, 'LOCK_DIR', str(tmp_path / 'lk'))
    assert not ul.held()
    with ul.hold('a'):
        assert ul.held()
        with ul.hold('b'):
            assert len(os.listdir(ul.LOCK_DIR)) == 2
    assert not ul.held()
    (tmp_path / 'lk' / '999999-dead').write_text('x')   # stale marker of a dead process
    assert not ul.held()
    assert ul.wait_until_free(max_wait_s=1, poll_s=1)
