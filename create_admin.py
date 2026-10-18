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

import secrets
import string

from app import create_app
from models.user import User
from database.db import get_db

app = create_app()


def _generate_strong_password(length=20):
    """Random password meeting User.validate_password_strength (12+ chars,
    upper/lower/digit/symbol) — never hardcode a bootstrap admin credential."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pwd) and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd) and any(c in "!@#$%^&*" for c in pwd)):
            return pwd


with app.app_context():
    email = "admin@complynex.online"
    password = _generate_strong_password()

    user = User.get_by_email(email)
    if user:
        print(f"User {email} already exists.")
    else:
        print(f"Creating user {email}...")
        try:
            User.create_user(
                email=email,
                password=password,
                first_name="Admin",
                last_name="User",
                role="admin",
                department="Management",
                job_title="System Administrator",
                cms_access_level='edit'
            )
            print("User created successfully.")
            print(f"Generated password (shown once, save it now): {password}")
            print("Log in immediately and change this password — it is not stored anywhere else.")
        except Exception as e:
            print(f"Error creating user: {e}")
