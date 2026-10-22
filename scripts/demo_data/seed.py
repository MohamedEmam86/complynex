#!/usr/bin/env python3
"""Load the fictional demo company into a DEMO instance (after wipe_sql.py).

Company: "Nile Microfinance S.A.E." (النيل للتمويل متناهي الصغر) - every
company, person, ID, account and figure is invented. Twelve months of activity
across the modules, so a trial user or a trainee sees a working system.

Run only through reset.sh. Each m_<area>.py file seeds one area.
"""
import os
import sys
import time
import importlib

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
sys.path.insert(0, HERE)
os.chdir(BASE)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE, '.env'))
from utils.demo import is_demo  # noqa: E402

AREAS = ['base', 'regcontrols', 'fincrime', 'risk', 'audit', 'governance', 'policies', 'conduct', 'training',
         'consumer', 'whistleblowing', 'privacy', 'cyber', 'esg', 'fp', 'finish']


def main(only=None):
    if not is_demo():
        sys.exit('refused: not a demo instance (no .demo_instance file)')
    from app import create_app
    from common import Ctx
    app = create_app()
    with app.app_context():
        ctx = Ctx()
        for area in (only or AREAS):
            t0 = time.time()
            mod = importlib.import_module(f'm_{area}')
            mod.seed(ctx)
            ctx.commit()
            print(f'  {area:<15} ok  {time.time() - t0:5.1f}s', flush=True)
        ctx.close()


if __name__ == '__main__':
    main(sys.argv[1:] or None)
