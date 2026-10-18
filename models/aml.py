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

from database.db import get_db
import sqlite3
from data_protection.encryption_service import EncryptionService

class Customer:
    def __init__(self, id, customer_reference, customer_type, full_name, risk_classification, status):
        self.id = id
        self.customer_reference = customer_reference
        self.customer_type = customer_type
        self.full_name = full_name
        self.risk_classification = risk_classification
        self.status = status

    @staticmethod
    def _process_row(row):
        """Convert row to dict and decrypt PII."""
        data = dict(row)
        
        # specific decryption logic
        if data.get('is_encrypted'):
            if data.get('email_encrypted'):
                data['email'] = EncryptionService.decrypt_value(data['email_encrypted'])
            if data.get('phone_encrypted'):
                data['phone'] = EncryptionService.decrypt_value(data['phone_encrypted'])
                
        return data

    @staticmethod
    def get_all():
        db = get_db()
        cursor = db.execute("SELECT * FROM customers ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [Customer._process_row(row) for row in rows]

    @staticmethod
    def create(data):
        from utils.aml_risk import calculate_risk_score
        
        db = get_db()
        try:
            # Simple reference generation for now
            import uuid
            ref = str(uuid.uuid4())[:8].upper()
            
            # Calculate Risk
            risk_result = calculate_risk_score(data)
            
            # Default risk values if calculation fails (safety net, though shouldn't happen)
            risk_score = risk_result.get('score', 0)
            risk_class = risk_result.get('classification', 'LOW')
            risk_reasons = ', '.join(risk_result.get('reasons', []))
            
            # Encrypt PII
            email = data.get('email')
            phone = data.get('phone')
            id_number = data.get('id_number')
            
            email_enc = EncryptionService.encrypt_value(email)
            phone_enc = EncryptionService.encrypt_value(phone)
            # Hash ID for searching
            id_hash = EncryptionService.hash_value(id_number)
            
            query = """
                INSERT INTO customers (
                    customer_reference, customer_type, full_name, company_name, 
                    email, phone, email_encrypted, phone_encrypted,
                    id_number, national_id_hash, is_encrypted,
                    address_line1, city, country, 
                    purpose_of_relationship, source_of_income,
                    risk_classification, risk_score, risk_classification_reason,
                    created_by, updated_by,
                    date_of_birth, nationality, id_type, id_expiry_date,
                    registration_number, business_activity, is_pep,
                    customer_number
                ) VALUES (
                    %(ref)s, %(type)s, %(name)s, %(company)s, 
                    %(email_plain)s, %(phone_plain)s, %(email_enc)s, %(phone_enc)s,
                    %(id_plain)s, %(id_hash)s, %(enc_flag)s,
                    %(addr)s, %(city)s, %(country)s, 
                    %(purpose)s, %(income)s,
                    %(risk_class)s, %(risk_score)s, %(risk_reasons)s,
                    %(created_by)s, %(updated_by)s,
                    %(dob)s, %(nat)s, %(id_type)s, %(id_exp)s,
                    %(reg_num)s, %(activity)s, %(pep)s,
                    %(ref)s
                )
                RETURNING id
            """
            params = {
                'ref': ref,
                'type': data.get('customer_type'),
                'name': data.get('full_name') if data.get('customer_type') == 'INDIVIDUAL' else None,
                'company': data.get('company_name') if data.get('customer_type') == 'CORPORATE' else None,
                'email_plain': '',
                'phone_plain': '',
                'email_enc': email_enc,
                'phone_enc': phone_enc,
                'id_plain': data.get('id_number'),
                'id_hash': id_hash,
                'enc_flag': 1,
                'addr': data.get('address', 'N/A'),
                'city': 'Cairo',
                'country': data.get('country', 'EGYPT'),
                'purpose': data.get('purpose'),
                'income': data.get('income'),
                'risk_class': risk_class,
                'risk_score': risk_score,
                'risk_reasons': risk_reasons,
                'created_by': 1,
                'updated_by': 1,
                'dob': data.get('date_of_birth'),
                'nat': data.get('nationality'),
                'id_type': data.get('id_type'),
                'id_exp': data.get('id_expiry_date'),
                'reg_num': data.get('registration_number'),
                'activity': data.get('industry') or data.get('business_activity'),
                'source': data.get('source_of_funds') or data.get('source_of_income'),
                'pep': 1 if data.get('is_pep') else 0
            }
            cursor = db.execute(query, params)
            row = cursor.fetchone()
            db.commit()
            return row[0] if row else None
        except Exception as e:
            print(f"Database error in create: {e}")
            return None

    @staticmethod
    def update(customer_id, data):
        db = get_db()
        try:
            # Prepare fields and values
            fields = []
            params = {'id': customer_id}
            
            # Encrypt PII if provided
            email = data.get('email')
            phone = data.get('phone')
            id_number = data.get('id_number')
            
            if email is not None:
                fields.append("email = %(email_plain)s")
                fields.append("email_encrypted = %(email_enc)s")
                params['email_plain'] = ''
                params['email_enc'] = EncryptionService.encrypt_value(email)
                params['is_encrypted'] = 1
                if "is_encrypted = %(is_encrypted)s" not in fields: fields.append("is_encrypted = %(is_encrypted)s")
            
            if phone is not None:
                fields.append("phone = %(phone_plain)s")
                fields.append("phone_encrypted = %(phone_enc)s")
                params['phone_plain'] = ''
                params['phone_enc'] = EncryptionService.encrypt_value(phone)
                params['is_encrypted'] = 1
                if "is_encrypted = %(is_encrypted)s" not in fields: fields.append("is_encrypted = %(is_encrypted)s")
                
            if id_number is not None:
                fields.append("national_id_hash = %(id_hash)s")
                params['id_hash'] = EncryptionService.hash_value(id_number)
                # Keep plain id_number for now as per previous logic
                fields.append("id_number = %(id_plain)s")
                params['id_plain'] = id_number
            
            # Other fields
            mapping = {
                'full_name': 'full_name',
                'full_name_arabic': 'full_name_arabic',
                'company_name': 'company_name',
                'address': 'address_line1',
                'address_line1': 'address_line1',
                'city': 'city',
                'country': 'country',
                'industry': 'business_activity',
                'business_activity': 'business_activity',
                'source_of_funds': 'source_of_income',
                'source_of_income': 'source_of_income',
                'purpose': 'purpose_of_relationship',
                'purpose_of_relationship': 'purpose_of_relationship',
                'income': 'annual_income_range',
                'annual_income_range': 'annual_income_range',
                'date_of_birth': 'date_of_birth',
                'nationality': 'nationality',
                'id_type': 'id_type',
                'id_expiry_date': 'id_expiry_date',
                'registration_number': 'registration_number',
                'status': 'status',
                'updated_by': 'updated_by'
            }
            
            for key, col in mapping.items():
                if key in data and data[key] is not None:
                    fields.append(f"{col} = %({key})s")
                    params[key] = data[key]
            
            if not fields:
                return True # Nothing to update
                
            fields.append("updated_at = CURRENT_TIMESTAMP")
            
            query = f"UPDATE customers SET {', '.join(fields)} WHERE id = %(id)s"
            db.execute(query, params)
            db.commit()
            return True
        except Exception as e:
            print(f"Database error in update: {e}")
            return False
