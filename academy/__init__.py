"""Integrys Academy — public training portal + staff console."""
from .routes import academy_bp  # noqa: F401
from .admin_routes import academy_admin_bp  # noqa: F401
from . import authoring  # noqa: F401  (registers authoring + results routes on academy_admin_bp)
