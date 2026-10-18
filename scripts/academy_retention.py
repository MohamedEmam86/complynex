"""Monthly PDPL retention job for Integrys Academy (cron)."""
import sys
sys.path.insert(0, '/var/www/complynex')
from app import app
from academy.service import purge_inactive

with app.app_context():
    print('academy retention: erased', purge_inactive())
