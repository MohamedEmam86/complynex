"""Demo instance switch.

A demo instance (e.g. demo.complynex.online) runs the same code from its own
folder, with its own database of fictional data. It shares the read-only
public sanctions search index and the semantic service with the main
instance, so it must never write to them or download lists itself.

The instance is a demo when its folder holds a `.demo_instance` file (or the
COMPLYNEX_DEMO=1 environment variable is set).
"""
import os

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MARKER = os.path.join(_BASE, '.demo_instance')


def is_demo():
    return os.environ.get('COMPLYNEX_DEMO') == '1' or os.path.exists(_MARKER)


def skip_in_demo(what, logger=None):
    """True (and logs why) when a job that writes shared data must not run here."""
    if not is_demo():
        return False
    msg = f"demo instance: {what} is disabled (shared lists and search index are maintained by the main instance)"
    if logger is not None:
        logger.info(msg)
    else:
        print(msg)
    return True


# ── idle sleep ──────────────────────────────────────────────────────────────
# The demo web app is started on demand (systemd socket activation) and stopped
# after a quiet period by scripts/demo_idle_sleep.sh, which reads the time of
# the last real request from this file. Written at most once a minute.
ACTIVITY_FILE = os.path.join(_BASE, 'logs', '.last_request')
_last_mark = [0.0]


def register_activity_marker(app):
    """Record the time of the last request (health checks excluded) on a demo instance."""
    import time
    from flask import request

    @app.after_request
    def _mark_demo_activity(response):
        if request.path.startswith(('/health', '/static/')):
            return response
        now = time.time()
        if now - _last_mark[0] >= 60:
            _last_mark[0] = now
            try:
                with open(ACTIVITY_FILE, 'w') as f:
                    f.write(str(int(now)))
            except OSError:
                pass
        return response
