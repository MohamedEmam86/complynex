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

"""Migration script for Merchant KYC table."""
import sqlite3
import os

def run_migration():
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'complynex_cms.db')
    if not os.path.exists(db_path):
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'complynex_cms.db')
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS merchants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            -- Business Information
            merchant_name VARCHAR(200) NOT NULL,
            trade_name VARCHAR(200),
            cr_number VARCHAR(100),
            tax_id VARCHAR(100),
            business_type VARCHAR(50) CHECK(business_type IN ('SOLE_PROPRIETORSHIP', 'PARTNERSHIP', 'LLC', 'JOINT_STOCK', 'OTHER')),
            industry VARCHAR(200),
            website VARCHAR(200),
            
            -- Contact Information
            contact_person VARCHAR(200),
            contact_email VARCHAR(200),
            contact_phone VARCHAR(50),
            address TEXT,
            city VARCHAR(100),
            country VARCHAR(50) DEFAULT 'Egypt',
            
            -- Beneficial Ownership
            ubo_name VARCHAR(200),
            ubo_nationality VARCHAR(100),
            ubo_id_type VARCHAR(50),
            ubo_id_number VARCHAR(100),
            ubo_dob DATE,
            ownership_percentage REAL,
            
            -- Banking Details
            bank_name VARCHAR(200),
            bank_account_number VARCHAR(100),
            iban VARCHAR(50),
            
            -- KYC Status & Workflow
            kyc_status VARCHAR(20) DEFAULT 'PENDING' CHECK(kyc_status IN ('PENDING', 'SENT', 'SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'REJECTED')),
            kyc_token VARCHAR(100) UNIQUE,
            kyc_sent_at TIMESTAMP,
            kyc_submitted_at TIMESTAMP,
            kyc_reviewed_by INTEGER REFERENCES users(id),
            kyc_reviewed_at TIMESTAMP,
            kyc_rejection_reason TEXT,
            
            -- Risk Assessment
            risk_level VARCHAR(20) DEFAULT 'MEDIUM' CHECK(risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
            sanctions_checked BOOLEAN DEFAULT 0,
            pep_checked BOOLEAN DEFAULT 0,
            risk_notes TEXT,
            
            -- Audit
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER REFERENCES users(id),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by INTEGER REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Migration complete: merchants table created.")

if __name__ == '__main__':
    run_migration()
