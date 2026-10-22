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
