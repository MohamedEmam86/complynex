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
Migration Script: Populate search_vector (tsvector) Column + Auto-Update Trigger

The search_vector column and GIN index already exist in the schema,
but were never populated. This script:

1. Populates search_vector for ALL existing rows using full_name + name_normalized + original_name
2. Creates a trigger to auto-update search_vector on INSERT/UPDATE

Actual column names (verified from production schema):
  - full_name (text) — English name
  - original_name (text) — Arabic/non-Latin script name
  - name_normalized (text) — Cleaned name
  - aliases (text[]) — Array of alternative names  
  - nationality (text)

Usage:
    python scripts/migrate_tsvector.py
"""

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'dbname': os.getenv('DB_NAME', 'complynex_dev'),
    'user': os.getenv('DB_USER', 'complynex_dev'),
    'password': os.getenv('DB_PASSWORD', 'dev_password_123'),
    'port': int(os.getenv('DB_PORT', 5432))
}


def run_migration():
    """Populate search_vector and create auto-update trigger."""
    
    try:
        import psycopg
        conn = psycopg.connect(**DB_CONFIG)
        conn.autocommit = True
        cursor = conn.cursor()
    except ImportError:
        try:
            import psycopg2
            conn = psycopg2.connect(**DB_CONFIG)
            conn.autocommit = True
            cursor = conn.cursor()
        except ImportError:
            logger.error("Neither psycopg nor psycopg2 installed.")
            sys.exit(1)
    
    print("=" * 60)
    print("  tsvector Population & Trigger Migration")
    print("=" * 60)
    print()
    
    # Step 1: Check current state
    print("[1/4] Checking current state...")
    cursor.execute("SELECT COUNT(*) FROM screening_watchlist;")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM screening_watchlist WHERE search_vector IS NOT NULL;")
    populated = cursor.fetchone()[0]
    
    print(f"  Total records: {total}")
    print(f"  Already populated: {populated}")
    print(f"  Need updating: {total - populated}")
    
    # Step 2: Populate search_vector for all rows
    # Uses 'simple' config (language-agnostic, works with Arabic + English)
    # aliases is TEXT[] array — use array_to_string to convert
    print("[2/4] Populating search_vector column...")
    try:
        cursor.execute("""
            UPDATE screening_watchlist SET
            search_vector = 
                setweight(to_tsvector('simple', COALESCE(full_name, '')), 'A') ||
                setweight(to_tsvector('simple', COALESCE(name_normalized, '')), 'A') ||
                setweight(to_tsvector('simple', COALESCE(original_name, '')), 'B') ||
                setweight(to_tsvector('simple', COALESCE(array_to_string(aliases, ' '), '')), 'C') ||
                setweight(to_tsvector('simple', COALESCE(nationality, '')), 'D');
        """)
        print(f"  ✅ Updated search_vector for all records")
    except Exception as e:
        logger.error(f"Population failed: {e}")
        print(f"  ❌ Failed: {e}")
    
    # Step 3: Create trigger function for auto-updates on INSERT/UPDATE
    print("[3/4] Creating auto-update trigger...")
    try:
        cursor.execute("""
            CREATE OR REPLACE FUNCTION screening_watchlist_search_vector_update()
            RETURNS trigger AS $$
            BEGIN
                NEW.search_vector :=
                    setweight(to_tsvector('simple', COALESCE(NEW.full_name, '')), 'A') ||
                    setweight(to_tsvector('simple', COALESCE(NEW.name_normalized, '')), 'A') ||
                    setweight(to_tsvector('simple', COALESCE(NEW.original_name, '')), 'B') ||
                    setweight(to_tsvector('simple', COALESCE(array_to_string(NEW.aliases, ' '), '')), 'C') ||
                    setweight(to_tsvector('simple', COALESCE(NEW.nationality, '')), 'D');
                RETURN NEW;
            END
            $$ LANGUAGE plpgsql;
        """)
        print("  ✅ Trigger function created")
    except Exception as e:
        logger.error(f"Trigger function failed: {e}")
        print(f"  ❌ Failed: {e}")
    
    try:
        cursor.execute("""
            DROP TRIGGER IF EXISTS trig_screening_search_vector 
            ON screening_watchlist;
        """)
        cursor.execute("""
            CREATE TRIGGER trig_screening_search_vector
            BEFORE INSERT OR UPDATE OF full_name, name_normalized, original_name, aliases, nationality
            ON screening_watchlist
            FOR EACH ROW
            EXECUTE FUNCTION screening_watchlist_search_vector_update();
        """)
        print("  ✅ Trigger attached to screening_watchlist")
    except Exception as e:
        logger.error(f"Trigger creation failed: {e}")
        print(f"  ❌ Failed: {e}")
    
    # Step 4: Verify
    print("[4/4] Verifying...")
    cursor.execute("SELECT COUNT(*) FROM screening_watchlist WHERE search_vector IS NOT NULL;")
    now_populated = cursor.fetchone()[0]
    print(f"  Records with search_vector: {now_populated}/{total}")
    
    # Quick FTS test
    if now_populated > 0:
        try:
            cursor.execute("""
                SELECT full_name, ts_rank(search_vector, plainto_tsquery('simple', 'ahmed')) AS rank
                FROM screening_watchlist
                WHERE search_vector @@ plainto_tsquery('simple', 'ahmed')
                ORDER BY rank DESC
                LIMIT 5;
            """)
            results = cursor.fetchall()
            print(f"  FTS test 'ahmed': {len(results)} matches")
            for r in results:
                print(f"    - {r[0]} (rank: {r[1]:.4f})")
        except Exception as e:
            logger.warning(f"FTS test skipped: {e}")
    
    print()
    print("=" * 60)
    print("  ✅ tsvector Migration Complete!")  
    print("=" * 60)
    
    cursor.close()
    conn.close()


if __name__ == "__main__":
    run_migration()
