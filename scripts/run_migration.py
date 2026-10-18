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
Run database migration for screening system enhancement.
Creates new tables: data_update_audit_log, data_source_urls, adverse_media_results
Adds columns to screening_data_sources.
"""
import sqlite3
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'complynex_cms.db')

def run_migration():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("=" * 60)
    print("ComplyNex Screening System - Database Migration v2.0")
    print("=" * 60)
    
    # 1. Create audit log table
    print("\n[1/7] Creating data_update_audit_log table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS data_update_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            update_type VARCHAR(50) NOT NULL,
            initiated_by INTEGER NOT NULL,
            total_sources INTEGER DEFAULT 0,
            records_added INTEGER DEFAULT 0,
            records_updated INTEGER DEFAULT 0,
            records_unchanged INTEGER DEFAULT 0,
            errors_count INTEGER DEFAULT 0,
            status VARCHAR(20) DEFAULT 'IN_PROGRESS',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            duration_seconds INTEGER,
            error_message TEXT,
            notes TEXT,
            FOREIGN KEY (initiated_by) REFERENCES users(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_initiated_by ON data_update_audit_log(initiated_by)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_started_at ON data_update_audit_log(started_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_status ON data_update_audit_log(status)")
    print("  OK")
    
    # 2. Create URL configuration table
    print("[2/7] Creating data_source_urls table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS data_source_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            is_current BOOLEAN DEFAULT TRUE,
            valid_from DATE DEFAULT CURRENT_DATE,
            valid_until DATE,
            verified_at TIMESTAMP,
            verification_status VARCHAR(20),
            verification_error TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (source_id) REFERENCES screening_data_sources(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_urls_source_id ON data_source_urls(source_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_urls_is_current ON data_source_urls(is_current)")
    print("  OK")
    
    # 3. Add new columns to screening_data_sources (SQLite: ignore errors if already exists)
    print("[3/7] Adding columns to screening_data_sources...")
    new_columns = [
        ("last_update_records_added", "INTEGER DEFAULT 0"),
        ("last_update_records_updated", "INTEGER DEFAULT 0"),
        ("last_update_duration_seconds", "INTEGER"),
        ("last_update_error", "TEXT"),
        ("priority", "INTEGER DEFAULT 100"),
        ("update_frequency_hours", "INTEGER DEFAULT 24"),
        ("next_scheduled_update", "TIMESTAMP"),
    ]
    for col_name, col_type in new_columns:
        try:
            cursor.execute(f"ALTER TABLE screening_data_sources ADD COLUMN {col_name} {col_type}")
            print(f"  Added: {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"  Exists: {col_name}")
            else:
                print(f"  Warning ({col_name}): {e}")
    
    # 4. Create adverse media results table
    print("[4/7] Creating adverse_media_results table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS adverse_media_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screening_result_id INTEGER,
            person_name VARCHAR(255) NOT NULL,
            risk_level VARCHAR(20),
            risk_score DECIMAL(5,2),
            total_hits INTEGER DEFAULT 0,
            high_risk_hits INTEGER DEFAULT 0,
            medium_risk_hits INTEGER DEFAULT 0,
            low_risk_hits INTEGER DEFAULT 0,
            sources_checked TEXT,
            top_hits TEXT,
            all_hits TEXT,
            recommendation TEXT,
            screened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            screened_by INTEGER,
            FOREIGN KEY (screening_result_id) REFERENCES screening_results(id),
            FOREIGN KEY (screened_by) REFERENCES users(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_adverse_media_person ON adverse_media_results(person_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_adverse_media_risk ON adverse_media_results(risk_level)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_adverse_media_screened_at ON adverse_media_results(screened_at DESC)")
    print("  OK")
    
    # 5. Insert/update default data sources with correct URLs
    print("[5/7] Configuring default data sources...")
    
    # Check which column names are used (source_name vs name)
    cols_info = cursor.execute("PRAGMA table_info(screening_data_sources)").fetchall()
    col_names = [c[1] for c in cols_info]
    
    # Determine the correct column names
    has_source_name = 'source_name' in col_names
    has_name = 'name' in col_names
    has_source_type = 'source_type' in col_names
    has_type = 'type' in col_names
    
    name_col = 'source_name' if has_source_name else 'name'
    type_col = 'source_type' if has_source_type else 'type'
    
    # Also check for source_url vs url
    has_source_url = 'source_url' in col_names
    url_col = 'source_url' if has_source_url else 'url'
    
    # Check for description column
    has_description = 'description' in col_names
    has_source_display_name = 'source_display_name' in col_names
    
    print(f"  Using columns: {name_col}, {type_col}, {url_col}")
    
    # Update EMLCU source URL
    cursor.execute(f"""
        UPDATE screening_data_sources 
        SET {url_col} = ?,
            {type_col} = 'EMLCU',
            priority = 10
        WHERE {name_col} LIKE '%EMLCU%' OR {name_col} LIKE '%emlcu%' OR {name_col} LIKE '%Egypt%'
    """, ('https://www.mlcu.org.eg/upload/uploadeditor/files/%D8%A7%D9%84%D9%82%D9%88%D8%A7%D8%A6%D9%85%20%D8%A7%D9%84%D9%85%D8%AD%D9%84%D9%8A%D8%A9/%D9%82%D8%A7%D8%A6%D9%85%D8%A9%20%D8%A5%D8%AF%D8%B1%D8%A7%D8%AC%20%D8%A7%D9%84%D9%83%D9%8A%D8%A7%D9%86%D8%A7%D8%AA%20%D8%A7%D9%84%D8%A5%D8%B1%D9%87%D8%A7%D8%A8%D9%8A%D8%A9%20%D9%88%D8%A7%D9%84%D8%A5%D8%B1%D9%87%D8%A7%D8%A8%D9%8A%D9%8A%D9%86%206%20%D9%8A%D9%86%D8%A7%D9%8A%D8%B1%202026.xlsx',))
    print(f"  EMLCU updated: {cursor.rowcount} rows")
    
    # Define sources to insert
    sources = [
        ('UN Security Council', 'UN', 'https://scsanctions.un.org/resources/xml/en/consolidated.xml', 
         'United Nations Security Council Consolidated List', 20, 24),
        ('OFAC SDN List', 'OFAC', 'https://www.treasury.gov/ofac/downloads/sdn.xml',
         'US Treasury OFAC Specially Designated Nationals List', 30, 24),
        ('HM Treasury UK', 'HMT', 'https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml',
         'UK Financial Sanctions Consolidated List', 40, 48),
        ('EU Consolidated Sanctions List', 'EU', 'https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content',
         'European Union Consolidated Financial Sanctions List', 50, 24),
        ('OpenSanctions', 'OPENSANCTIONS', 'https://data.opensanctions.org/datasets/latest/default/entities.ftm.json',
         'OpenSanctions comprehensive watchlists (FTJSON)', 60, 24),
    ]
    
    for src_name, src_type, src_url, src_desc, priority, freq in sources:
        # Check if source already exists
        existing = cursor.execute(f"SELECT id FROM screening_data_sources WHERE {name_col} = ?", (src_name,)).fetchone()
        if not existing:
            # Build INSERT based on available columns
            if has_source_display_name:
                cursor.execute(f"""
                    INSERT INTO screening_data_sources ({name_col}, {has_source_display_name and 'source_display_name,' or ''} {type_col}, {url_col}, is_active, priority, update_frequency_hours)
                    VALUES (?, ?, ?, ?, TRUE, ?, ?)
                """, (src_name, src_name, src_type, src_url, priority, freq))
            elif has_description:
                cursor.execute(f"""
                    INSERT INTO screening_data_sources ({name_col}, {type_col}, {url_col}, description, is_active, priority, update_frequency_hours)
                    VALUES (?, ?, ?, ?, TRUE, ?, ?)
                """, (src_name, src_type, src_url, src_desc, priority, freq))
            else:
                cursor.execute(f"""
                    INSERT INTO screening_data_sources ({name_col}, {type_col}, {url_col}, is_active, priority, update_frequency_hours)
                    VALUES (?, ?, ?, TRUE, ?, ?)
                """, (src_name, src_type, src_url, priority, freq))
            print(f"  Inserted: {src_name}")
        else:
            # Update URL and priority
            cursor.execute(f"""
                UPDATE screening_data_sources SET {url_col} = ?, priority = ?, update_frequency_hours = ?
                WHERE {name_col} = ?
            """, (src_url, priority, freq, src_name))
            print(f"  Updated: {src_name}")
    
    # 6. Create audit dashboard view
    print("[6/7] Creating v_data_update_summary view...")
    cursor.execute("DROP VIEW IF EXISTS v_data_update_summary")
    cursor.execute("""
        CREATE VIEW IF NOT EXISTS v_data_update_summary AS
        SELECT 
            dal.id,
            dal.update_type,
            u.email as initiated_by_user,
            dal.total_sources,
            dal.records_added,
            dal.records_updated,
            dal.records_unchanged,
            dal.errors_count,
            dal.status,
            dal.started_at,
            dal.completed_at,
            dal.duration_seconds,
            dal.error_message
        FROM data_update_audit_log dal
        LEFT JOIN users u ON dal.initiated_by = u.id
        ORDER BY dal.started_at DESC
    """)
    print("  OK")
    
    # 7. Add NewsAPI config to screening_config (not screening_settings since config uses different columns)
    print("[7/7] Adding NewsAPI configuration...")
    
    # Check screening_config columns
    config_cols = [c[1] for c in cursor.execute("PRAGMA table_info(screening_config)").fetchall()]
    
    if 'config_key' in config_cols and 'config_value' in config_cols:
        news_configs = [
            ('newsapi_key', 'YOUR_NEWSAPI_KEY_HERE', 'adverse_media', 'NewsAPI.org API key for adverse media screening'),
            ('adverse_media_enabled', 'false', 'adverse_media', 'Enable adverse media screening feature'),
            ('audit_log_retention_days', '365', 'audit', 'Number of days to retain audit logs'),
        ]
        for key, value, category, desc in news_configs:
            existing = cursor.execute("SELECT id FROM screening_config WHERE config_key = ?", (key,)).fetchone()
            if not existing:
                if 'category' in config_cols:
                    cursor.execute(
                        "INSERT INTO screening_config (config_key, config_value, category, description) VALUES (?, ?, ?, ?)",
                        (key, value, category, desc)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO screening_config (config_key, config_value, description) VALUES (?, ?, ?)",
                        (key, value, desc)
                    )
                print(f"  Added config: {key}")
            else:
                print(f"  Exists: {key}")
    
    # Also add to screening_settings if it exists
    settings_cols = [c[1] for c in cursor.execute("PRAGMA table_info(screening_settings)").fetchall()]
    if 'key' in settings_cols:
        existing = cursor.execute("SELECT id FROM screening_settings WHERE key = ?", ('NEWSAPI_KEY',)).fetchone()
        if not existing:
            cursor.execute(
                "INSERT INTO screening_settings (key, value, description) VALUES (?, ?, ?)",
                ('NEWSAPI_KEY', 'YOUR_NEWSAPI_KEY_HERE', 'NewsAPI.org API key for adverse media screening')
            )
            print("  Added to screening_settings: NEWSAPI_KEY")
        else:
            print("  Exists in screening_settings: NEWSAPI_KEY")
    
    conn.commit()
    
    # Verify
    print("\n" + "=" * 60)
    print("Migration Verification")
    print("=" * 60)
    
    for table in ['data_update_audit_log', 'data_source_urls', 'adverse_media_results']:
        count = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")
    
    src_count = cursor.execute("SELECT COUNT(*) FROM screening_data_sources").fetchone()[0]
    print(f"  screening_data_sources: {src_count} rows")
    
    # Show current data sources
    print("\nConfigured Data Sources:")
    rows = cursor.execute(f"SELECT id, {name_col}, {type_col}, is_active, priority FROM screening_data_sources ORDER BY priority").fetchall()
    for row in rows:
        print(f"  [{row[0]}] {row[1]} ({row[2]}) active={row[3]} priority={row[4]}")
    
    conn.close()
    print("\n✓ Migration completed successfully!")

if __name__ == "__main__":
    run_migration()
