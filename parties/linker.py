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
Sync helpers that keep the party registry (models/party.py) up to date from
each source module's own record. Called directly (synchronously — this is
cheap DB bookkeeping, not a cross-module reaction, so it doesn't go through
the P1 event bus) right after a customer/merchant is created or edited.

Matching is a hash lookup on the ID/CR number using the same
EncryptionService.hash_value() customers.national_id_hash already uses — see
database/schema_parties.sql for why no new hashing scheme was introduced.

Scope note: eKYC (ekyc_result) is intentionally NOT hooked here. Most of its
identity value is already captured once a session onboards into a customer
(ekyc_session.onboarded_customer_id bridges to customers, which IS hooked),
and ekyc/pipeline.py is a complex, ML-heavy file where adding a hook was
judged a worse risk/value trade-off than covering it in the one-off backfill
script instead (scripts/backfill_parties.py links historical eKYC rows by
national_id hash even though there's no live inline hook going forward).
"""

from database.db import get_db
from data_protection.encryption_service import EncryptionService
from models.party import Party, PartyLink


def upsert_party_for_customer(customer_id):
    row = get_db().execute("SELECT * FROM customers WHERE id = %s", (customer_id,)).fetchone()
    if not row:
        return None
    customer = dict(row)

    is_individual = customer.get('customer_type') == 'INDIVIDUAL'
    name = customer.get('full_name') if is_individual else (customer.get('company_name') or customer.get('full_name'))
    if not name:
        return None

    if is_individual:
        id_hash = EncryptionService.hash_value(customer.get('id_number'))
        party = Party.find_by_id_number_hash(id_hash) if id_hash else None
    else:
        cr_hash = EncryptionService.hash_value(customer.get('registration_number'))
        party = Party.find_by_cr_number_hash(cr_hash) if cr_hash else None

    if party:
        party_id = party['id']
        Party.update_bio(party_id, full_name=name, email=customer.get('email'),
                          phone=customer.get('phone'), nationality=customer.get('nationality'))
    else:
        party_id = Party.create(
            party_type='INDIVIDUAL' if is_individual else 'ENTITY',
            full_name=name,
            full_name_arabic=customer.get('full_name_arabic'),
            date_of_birth=customer.get('date_of_birth') if is_individual else None,
            nationality=customer.get('nationality'),
            id_type=customer.get('id_type') if is_individual else 'CR_NUMBER',
            id_number_hash=EncryptionService.hash_value(customer.get('id_number')) if is_individual else None,
            cr_number_hash=EncryptionService.hash_value(customer.get('registration_number')) if not is_individual else None,
            email=customer.get('email'),
            phone=customer.get('phone'),
        )

    PartyLink.create(party_id, source_module='Customer KYC', source_table='customers',
                      source_record_id=customer_id, link_role='CUSTOMER')
    return party_id


def upsert_party_for_merchant(merchant_id):
    row = get_db().execute("SELECT * FROM merchants WHERE id = %s", (merchant_id,)).fetchone()
    if not row:
        return None
    merchant = dict(row)

    merchant_party_id = None
    if merchant.get('merchant_name'):
        cr_hash = EncryptionService.hash_value(merchant.get('cr_number'))
        party = Party.find_by_cr_number_hash(cr_hash) if cr_hash else None
        if party:
            merchant_party_id = party['id']
            Party.update_bio(merchant_party_id, full_name=merchant.get('merchant_name'),
                              email=merchant.get('contact_email'), phone=merchant.get('contact_phone'),
                              nationality=merchant.get('country'))
        else:
            merchant_party_id = Party.create(
                party_type='ENTITY',
                full_name=merchant.get('merchant_name'),
                nationality=merchant.get('country'),
                id_type='CR_NUMBER',
                cr_number_hash=cr_hash,
                email=merchant.get('contact_email'),
                phone=merchant.get('contact_phone'),
            )
        PartyLink.create(merchant_party_id, source_module='Merchant KYC', source_table='merchants',
                          source_record_id=merchant_id, link_role='MERCHANT')

    ubo_name = merchant.get('ubo_name')
    if ubo_name and str(ubo_name).strip().lower() not in ('none', 'null', ''):
        ubo_hash = EncryptionService.hash_value(merchant.get('ubo_id_number'))
        ubo_party = Party.find_by_id_number_hash(ubo_hash) if ubo_hash else None
        if ubo_party:
            ubo_party_id = ubo_party['id']
            Party.update_bio(ubo_party_id, full_name=ubo_name, nationality=merchant.get('ubo_nationality'))
        else:
            ubo_party_id = Party.create(
                party_type='INDIVIDUAL',
                full_name=ubo_name,
                date_of_birth=merchant.get('ubo_dob'),
                nationality=merchant.get('ubo_nationality'),
                id_type=merchant.get('ubo_id_type'),
                id_number_hash=ubo_hash,
            )
        PartyLink.create(ubo_party_id, source_module='Merchant KYC', source_table='merchants',
                          source_record_id=merchant_id, link_role='MERCHANT_UBO')

    return merchant_party_id
