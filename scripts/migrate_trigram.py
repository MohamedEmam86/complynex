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
Migration Script: Enable PostgreSQL pg_trgm Extension & Create GIN Trigram Indexes

This script enables the pg_trgm extension for fuzzy text search and creates
GIN indexes on the screening_watchlist table for dramatically faster
candidate recall during sanctions screening.

Usage:
    python scripts/migrate_trigram.py

Requirements:
    - PostgreSQL 9.6+ with pg_trgm available (included in contrib modules)
    - Database user must have CREATE EXTENSION privileges (or be superuser)
"""

import os
import sys
import logging

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database config from environment
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'dbname': os.getenv('DB_NAME', 'complynex_dev'),
    'user': os.getenv('DB_USER', 'complynex_dev'),
    'password': os.getenv('DB_PASSWORD', 'dev_password_123'),
    'port': int(os.getenv('DB_PORT', 5432))
}


def run_migration():
    """Enable pg_trgm extension and create GIN trigram indexes."""
    
    try:
        import psycopg
        conn = psycopg.connect(**DB_CONFIG)
        conn.autocommit = True  # Required for CREATE EXTENSION and CONCURRENTLY
        cursor = conn.cursor()
    except ImportError:
        try:
            import psycopg2
            conn = psycopg2.connect(**DB_CONFIG)
            conn.autocommit = True
            cursor = conn.cursor()
        except ImportError:
            logger.error("Neither psycopg (v3) nor psycopg2 is installed.")
            sys.exit(1)
    
    print("=" * 60)
    print("  pg_trgm Trigram Migration for Screening Engine")
    print("=" * 60)
    print()
    
    # Step 1: Enable pg_trgm extension
    print("[1/6] Enabling pg_trgm extension...")
    try:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        print("  ✅ pg_trgm extension enabled")
    except Exception as e:
        logger.error(f"Failed to create pg_trgm extension: {e}")
        print(f"  ❌ Failed: {e}")
        print("  NOTE: You may need superuser privileges. Run: CREATE EXTENSION pg_trgm;")
        conn.close()
        sys.exit(1)
    
    # Step 2: Verify extension is active
    print("[2/6] Verifying extension...")
    try:
        cursor.execute("SELECT similarity('test', 'tset');")
        result = cursor.fetchone()
        print(f"  ✅ pg_trgm working (test similarity: {result[0]:.4f})")
    except Exception as e:
        logger.error(f"pg_trgm verification failed: {e}")
        print(f"  ❌ pg_trgm not working: {e}")
        conn.close()
        sys.exit(1)
    
    # Step 3: Set default similarity threshold
    print("[3/6] Setting similarity threshold to 0.3...")
    try:
        cursor.execute("SET pg_trgm.similarity_threshold = 0.3;")
        print("  ✅ Threshold set to 0.3 (session)")
    except Exception as e:
        logger.warning(f"Could not set threshold: {e}")
    
    # Step 4: Create GIN trigram indexes
    # Using CREATE INDEX IF NOT EXISTS (no CONCURRENTLY to keep it simple and reliable)
    indexes = [
        {
            'name': 'idx_trgm_full_name',
            'column': 'full_name',
            'desc': 'Full Name (English)'
        },
        {
            'name': 'idx_trgm_name_normalized',
            'column': 'name_normalized', 
            'desc': 'Normalized Name'
        },
        {
            'name': 'idx_trgm_original_name',
            'column': 'original_name',
            'desc': 'Original Name (Arabic/non-Latin)'
        },
    ]
    
    print(f"[4/6] Creating {len(indexes)} GIN trigram indexes...")
    for idx in indexes:
        try:
            # Check if column exists first 
            cursor.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'screening_watchlist' AND column_name = %s
            """, (idx['column'],))
            
            if not cursor.fetchone():
                print(f"  ⚠️  Column '{idx['column']}' does not exist, skipping {idx['name']}")
                continue
            
            sql = f"CREATE INDEX IF NOT EXISTS {idx['name']} ON screening_watchlist USING GIN ({idx['column']} gin_trgm_ops);"
            cursor.execute(sql)
            print(f"  ✅ Created {idx['name']} on {idx['desc']}")
        except Exception as e:
            logger.error(f"Failed to create index {idx['name']}: {e}")
            print(f"  ❌ Failed {idx['name']}: {e}")
    
    # Step 5: Verify indexes were created
    print("[5/6] Verifying indexes...")
    try:
        cursor.execute("""
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE tablename = 'screening_watchlist' 
            AND indexname LIKE 'idx_trgm_%'
            ORDER BY indexname;
        """)
        trgm_indexes = cursor.fetchall()
        print(f"  ✅ Found {len(trgm_indexes)} trigram indexes:")
        for idx in trgm_indexes:
            print(f"     - {idx[0]}")
    except Exception as e:
        logger.error(f"Verification failed: {e}")
    
    # Step 6: Run a quick benchmark
    print("[6/6] Running benchmark...")
    try:
        cursor.execute("SELECT COUNT(*) FROM screening_watchlist WHERE is_active = 1;")
        total_records = cursor.fetchone()[0]
        print(f"  Total active watchlist records: {total_records}")
        
        if total_records > 0:
            # Benchmark: LIKE vs Trigram
            import time
            
            test_name = 'ahmed hassan'
            
            # LIKE benchmark
            start = time.time()
            cursor.execute(
                "SELECT COUNT(*) FROM screening_watchlist WHERE name_normalized LIKE %s",
                (f"%{test_name}%",)
            )
            like_count = cursor.fetchone()[0]
            like_time = (time.time() - start) * 1000
            
            # Trigram benchmark
            start = time.time()
            cursor.execute(
                "SELECT COUNT(*) FROM screening_watchlist WHERE name_normalized %% %s",
                (test_name,)
            )
            trgm_count = cursor.fetchone()[0]
            trgm_time = (time.time() - start) * 1000
            
            print(f"  LIKE  '%{test_name}%': {like_count} results in {like_time:.1f}ms")
            print(f"  TRGM  '{test_name}':   {trgm_count} results in {trgm_time:.1f}ms")
            
            if like_time > 0:
                speedup = like_time / max(trgm_time, 0.1)
                print(f"  Speedup: {speedup:.1f}x faster with trigrams")
    except Exception as e:
        logger.warning(f"Benchmark skipped: {e}")
    
    print()
    print("=" * 60)
    print("  ✅ Migration Complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Restart the application to pick up the new indexes")
    print("  2. Test screening with: python -c \"from screening.complynex_engine import *\"")
    print("  3. Bulk upload should be significantly faster now")
    print()
    
    cursor.close()
    conn.close()


if __name__ == "__main__":
    run_migration()
