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

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app
from werkzeug.security import generate_password_hash
from database.db import query_db, execute_db

app = create_app()
with app.app_context():
    admin = query_db("SELECT * FROM users WHERE email = ? OR role = ?", ('admin@complynex.com', 'admin'), one=True)
    if admin:
        print(f"Found admin with email: {admin['email']} and ID: {admin['id']}")
        new_hash = generate_password_hash("admin123")
        execute_db("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, admin['id']))
        print("Password reset successfully to: admin123")
    else:
        print("Admin not found. Creating a new admin user...")
        new_hash = generate_password_hash("admin123")
        execute_db("INSERT INTO users (username, email, password_hash, role, is_active) VALUES (?, ?, ?, ?, ?)", 
                   ("admin", "admin@complynex.com", new_hash, "admin", 1))
        print("Admin user created with email 'admin@complynex.com' and password 'admin123'")
