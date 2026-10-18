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

import gevent.monkey
gevent.monkey.patch_all()

"""
ComplyNex CMS - Entry Point

Run this file to start the Flask development server:
    python run.py

The server will start on http://localhost:5000
"""
import os
import sys

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, create_app
from database.db import init_db


def main():
    """Initialize database if needed and run the Flask application."""
    
    # Check if database exists
    if app.config.get('DB_TYPE', 'sqlite') == 'sqlite' and not os.path.exists(app.config.get('DATABASE', '')):
        print("Database not found. Initializing...")
        with app.app_context():
            init_db()
        print(f"Database created at: {app.config['DATABASE']}")
        print("Default admin user created:")
        print("  Email: admin@complynex.online")
        print("  Password: Admin@123")
        print("  (Please change this password after first login!)")
        print()
    
    # Print startup message
    print("=" * 60)
    print("  ComplyNex Full Compliance Platform")
    print("  Phase 1 - Foundation")
    print("=" * 60)
    print()
    print("Starting development server...")
    print("Access the application at: http://localhost:5000")
    print("Press Ctrl+C to stop the server")
    print()
    
    # Run the development server
    port = int(os.environ.get('PORT', 5000))
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    
    app.run(debug=False, host='0.0.0.0', port=port)


if __name__ == '__main__':
    main()
