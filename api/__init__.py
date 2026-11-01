from flask import Blueprint

api_v1_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')

from api import routes  # noqa: E402,F401
from api import screening_v1  # noqa: E402,F401  (P6-2 / P6-8 / G12)
