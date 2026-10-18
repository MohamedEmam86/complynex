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
import sqlite3
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

# Add parent directory to path to allow importing from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from config import config
from database.db import init_app, get_db
from data_protection.encryption_service import EncryptionService

def encrypt_existing_data():
    app = Flask(__name__)
    # Use development or production config based on needs, here default is fine
    
    app.config.from_object(config['default'])
    
    with app.app_context():
        db = get_db()
        print("Starting encryption of existing PII...")
        
        # Check if encryption columns exist (assuming schema update ran)
        try:
            db.execute("SELECT email_encrypted FROM customers LIMIT 1")
        except sqlite3.OperationalError:
            print("Error: 'email_encrypted' column not found. Please run schema update first.")
            return

        # Get all unencrypted customers
        # (Those where is_encrypted is 0 or NULL)
        cursor = db.execute("SELECT * FROM customers WHERE is_encrypted = 0 OR is_encrypted IS NULL")
        customers = cursor.fetchall()
        
        print(f"Found {len(customers)} records to encrypt.")
        
        count = 0
        for row in customers:
            c_id = row['id']
            email = row['email']
            phone = row['phone']
            id_number = row['id_number']
            
            updates = []
            params = []
            
            if email:
                email_enc = EncryptionService.encrypt_value(email)
                updates.append("email_encrypted = ?")
                params.append(email_enc)
                # We can optionally clear email here, but for safety in this script we might keep it
                # and verify later. But guide implies we move to encrypted.
                # Let's keep plain text for now until verified, or clear it if we are confident.
                # "Encrypt existing PII" -> The functional change in model clears it on create.
                # So we should probably clear it here to be consistent with model.
                updates.append("email = NULL") 

            if phone:
                phone_enc = EncryptionService.encrypt_value(phone)
                updates.append("phone_encrypted = ?")
                params.append(phone_enc)
                updates.append("phone = NULL")

            if id_number:
                id_hash = EncryptionService.hash_value(id_number)
                updates.append("national_id_hash = ?")
                params.append(id_hash)
                # Keep original id_number for now as discussed
            
            if updates:
                updates.append("is_encrypted = 1")
                query = f"UPDATE customers SET {', '.join(updates)} WHERE id = ?"
                params.append(c_id)
                db.execute(query, tuple(params))
                count += 1
                
        db.commit()
        print(f"Successfully encrypted {count} records.")

if __name__ == '__main__':
    encrypt_existing_data()
