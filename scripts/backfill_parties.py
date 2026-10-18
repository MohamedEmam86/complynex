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
One-off backfill: populates the party registry (parties/party_links, see
database/schema_parties.sql) from every existing customers/merchants row,
plus eKYC sessions that haven't already onboarded into a customer.

Idempotent and safe to re-run: parties/linker.py's upsert helpers dedupe on
the same ID/CR hash lookup used for live traffic, and PartyLink.create()
dedupes on (source_table, source_record_id, link_role). Going forward, new
customers/merchants are kept in sync live via the inline hooks in
aml/routes.py and merchant_kyc/routes.py — this script only needs to run
once for historical data (and again if the party registry is ever rebuilt).

eKYC is backfilled here (unlike the live-hook decision in parties/linker.py)
because there's no ongoing-risk downside to a one-off read of ekyc_result —
the risk that ruled out a live hook was touching ekyc/pipeline.py itself,
not reading eKYC data.

Safe to run manually: python scripts/backfill_parties.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def backfill_customers():
    from database.db import get_db
    from parties.linker import upsert_party_for_customer

    db = get_db()
    rows = db.execute("SELECT id FROM customers").fetchall()
    count = 0
    for row in rows:
        try:
            if upsert_party_for_customer(row['id']):
                count += 1
        except Exception as exc:
            print(f"  customer {row['id']}: skipped ({exc})")
    return count


def backfill_merchants():
    from database.db import get_db
    from parties.linker import upsert_party_for_merchant

    db = get_db()
    rows = db.execute("SELECT id FROM merchants").fetchall()
    count = 0
    for row in rows:
        try:
            if upsert_party_for_merchant(row['id']):
                count += 1
        except Exception as exc:
            print(f"  merchant {row['id']}: skipped ({exc})")
    return count


def backfill_ekyc():
    from database.db import get_db
    from data_protection.encryption_service import EncryptionService
    from models.party import Party, PartyLink

    db = get_db()
    rows = db.execute("""
        SELECT r.*, s.onboarded_customer_id
        FROM ekyc_result r
        JOIN ekyc_session s ON s.id = r.session_id
        WHERE s.onboarded_customer_id IS NULL
    """).fetchall()

    count = 0
    for row in rows:
        result = dict(row)
        national_id = result.get('final_national_id') or result.get('national_id')
        name = result.get('final_name') or result.get('extracted_full_name_en') or result.get('extracted_full_name_ar')
        if not national_id or not name:
            continue

        id_hash = EncryptionService.hash_value(national_id)
        party = Party.find_by_id_number_hash(id_hash)
        party_id = party['id'] if party else Party.create(
            party_type='INDIVIDUAL',
            full_name=name,
            full_name_arabic=result.get('extracted_full_name_ar'),
            date_of_birth=result.get('dob'),
            id_type='NATIONAL_ID',
            id_number_hash=id_hash,
        )
        PartyLink.create(party_id, source_module='eKYC', source_table='ekyc_result',
                          source_record_id=result['id'], link_role='EKYC_APPLICANT')
        count += 1
    return count


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        print("Backfilling parties from customers...")
        print(f"  linked: {backfill_customers()}")
        print("Backfilling parties from merchants...")
        print(f"  linked: {backfill_merchants()}")
        print("Backfilling parties from eKYC (not-yet-onboarded sessions only)...")
        print(f"  linked: {backfill_ekyc()}")
