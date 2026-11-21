# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================

"""
First superadmin of an instance, with a password nobody sees.

    sudo -u complynex /var/www/complynex/venv/bin/python /var/www/complynex-<name>/scripts/instance/create_superadmin.py \
        --email owner@example.org [--first-name First --last-name Last] [--base-url https://host] [--hours 24]

Run from the instance's folder (the script uses the folder it lives in, or --root): that instance's .env is
loaded, so the user is created in that instance's database. The account gets a random password that is never
printed or stored; the script prints a ONE-TIME set-password link (auth/set_password.py) valid for --hours
(default 24, at most 7 days). Re-running for an existing superadmin creates nothing and prints a new link.
"""

import argparse
import os
import secrets
import string
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def random_password(length=40):
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
    while True:
        pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pwd) and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd) and any(c in '!@#$%^&*' for c in pwd)):
            return pwd


def issue(email, first_name='Platform', last_name='Administrator', base_url=None, hours=24):
    """Create (or find) the superadmin and return (created, link). Needs an app (request) context."""
    from models.user import User
    from auth import set_password as SP
    email = email.strip().lower()
    user = User.get_by_email(email)
    created = False
    if user is None:
        User.create_user(email=email, password=random_password(), first_name=first_name, last_name=last_name,
                         role='superadmin', department='Administration', job_title='Platform administrator',
                         cms_access_level='edit')
        user = User.get_by_email(email)
        created = True
        try:
            from models.audit import AuditLog
            AuditLog.log(None, 'Create User', 'Users', user.id, 'First superadmin created (one-time link issued)', None)
        except Exception:
            pass
    elif (getattr(user, 'role', '') or '') != 'superadmin':
        raise SystemExit(f'{email} exists and is not a superadmin: nothing changed')
    return created, SP.set_password_url(user, base_url=base_url, hours=hours)


def main(argv=None):
    ap = argparse.ArgumentParser(description='First superadmin of an instance (one-time set-password link).')
    ap.add_argument('--email', required=True)
    ap.add_argument('--first-name', default='Platform')
    ap.add_argument('--last-name', default='Administrator')
    ap.add_argument('--base-url', default=None, help='public address of the instance (default: APP_URL in .env)')
    ap.add_argument('--hours', type=float, default=24)
    ap.add_argument('--root', default=ROOT, help='instance folder (default: the one this script is in)')
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    os.chdir(root)
    sys.path.insert(0, root)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(root, '.env'), override=True)
    import logging
    logging.disable(logging.WARNING)
    from app import app           # the instance's application (app.py builds it on import)
    base = a.base_url or os.environ.get('APP_URL') or None
    from auth import set_password as SP
    hours = max(0.01, min(a.hours, SP.MAX_HOURS))
    with app.test_request_context('/', base_url=base or 'http://localhost'):
        created, link = issue(a.email, a.first_name, a.last_name, base_url=base, hours=hours)
    print(('Superadmin created: ' if created else 'Superadmin exists: ') + a.email.strip().lower())
    print(f'One-time set-password link (valid {hours:g} h, works once):')
    print(link)
    return 0


if __name__ == '__main__':
    sys.exit(main())
