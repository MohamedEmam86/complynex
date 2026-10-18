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

import sqlite3
import os

# Project Root
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(project_root, 'complynex_cms.db')

def fix_db():
    print(f"Connecting to {DB_PATH}...")
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Check if table exists
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='screening_data_sources'")
    if c.fetchone():
        print("⚠️ Table 'screening_data_sources' ALREADY EXISTS.")
    else:
        print("Creating screening_data_sources table...")
        c.execute("""
        CREATE TABLE screening_data_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) UNIQUE NOT NULL, -- Internal slug: un, ofac, eu, hmt, emlcu, opensanctions
            display_name VARCHAR(200) NOT NULL,
            source_url TEXT,
            type VARCHAR(50) DEFAULT 'sanctions', -- sanctions, pep, crime
            is_official BOOLEAN DEFAULT 1, -- 1 for UN/OFAC/EU/HMT/EMLCU which appear at top
            is_active BOOLEAN DEFAULT 1,
            update_frequency_hours INTEGER DEFAULT 24,
            last_successful_update TIMESTAMP,
            total_records INTEGER DEFAULT 0,
            last_updated_by INTEGER
        )
        """)
        
        # Seed Data
        sources = [
            ('un', 'UN Consolidated List', 'https://scsanctions.un.org/', 'sanctions', 1),
            ('ofac', 'US OFAC SDN List', 'https://ofac.treasury.gov/', 'sanctions', 1),
            ('eu', 'EU Financial Sanctions', 'https://data.europa.eu/euodp/en/data/dataset/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions', 'sanctions', 1),
            ('hmt', 'UK HMT Sanctions', 'https://www.gov.uk/government/publications/financial-sanctions-consolidated-list-of-targets', 'sanctions', 1),
            ('emlcu', 'Egypt EMLCU Terrorist List', 'https://www.emlcu.gov.eg/', 'sanctions', 1),
            ('opensanctions', 'Global PEPs (OpenSanctions)', 'https://www.opensanctions.org/', 'pep', 0),
            ('custom', 'Internal Blacklist', None, 'custom', 0)
        ]

        print("Inserting default sources...")
        for s in sources:
            try:
                c.execute("""
                INSERT INTO screening_data_sources (name, display_name, source_url, type, is_official)
                VALUES (?, ?, ?, ?, ?)
                """, s)
            except sqlite3.IntegrityError:
                pass 

        conn.commit()
        print("✅ Table created and seeded.") # cbe_circular_reference is not in this table

    conn.close()

if __name__ == '__main__':
    fix_db()
