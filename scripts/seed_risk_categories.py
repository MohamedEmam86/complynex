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
Seeds the initial risk taxonomy (risk_categories) and scoring bands
(risk_scoring_bands) for the Enterprise Risk Management module.

Run AFTER scripts/mig_risk_management_schema.py.
Idempotent — skips any category/band that already exists (by code / score
range) rather than duplicating it, so it's safe to re-run.

Run with: python scripts/seed_risk_categories.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from database.db import get_db

app = create_app()

# (code, name, description) — top-level taxonomy appropriate for a Central
# Bank of Egypt-regulated payment service provider. Reputational risk is
# deliberately kept as its own category as well as an available secondary
# tag on individual risks (risks.secondary_tags), since it's often a
# *consequence* of another category rather than a root cause.
RISK_CATEGORIES = [
    ("CRD", "Credit Risk", "Settlement exposure, merchant cash-advance and counterparty default risk."),
    ("OPR", "Operational Risk", "Process failure, people, systems and internal-control breakdowns."),
    ("CMP", "Compliance & Regulatory Risk", "CBE directives, licensing conditions and regulatory reporting obligations."),
    ("FCR", "Financial Crime / AML-CFT Risk", "Money laundering, terrorist financing and sanctions-evasion exposure."),
    ("TEC", "Technology & Cyber Risk", "IT infrastructure, cybersecurity, data integrity and system availability."),
    ("TPR", "Third-Party & Vendor Risk", "Payment scheme, processor, agent-network and outsourcing dependency risk."),
    ("STR", "Strategic Risk", "Business model, market positioning and competitive risk."),
    ("REP", "Reputational Risk", "Brand and stakeholder-trust impact, often a consequence of other risk categories."),
    ("LIQ", "Liquidity & Financial Risk", "Settlement liquidity, treasury and funding risk."),
    ("CON", "Conduct & Consumer Protection Risk", "Employee conduct, ethics and fair treatment of customers."),
]

# (band_name, min_score, max_score, color_hex, display_order, requires_board_notification)
# Standard 5x5 matrix (likelihood x impact, 1-5 each => 1-25 range).
RISK_SCORING_BANDS = [
    ("LOW", 1, 4, "#28a745", 1, False),
    ("MODERATE", 5, 9, "#ffc107", 2, False),
    ("HIGH", 10, 15, "#fd7e14", 3, False),
    ("CRITICAL", 16, 25, "#dc3545", 4, True),
]


def seed():
    with app.app_context():
        db = get_db()

        print("Seeding risk_categories...")
        for code, name, description in RISK_CATEGORIES:
            existing = db.execute(
                "SELECT id FROM risk_categories WHERE category_code = %s", (code,)
            ).fetchone()
            if existing:
                print(f"  {code} already exists, skipping.")
                continue
            db.execute(
                "INSERT INTO risk_categories (category_code, category_name, category_description) "
                "VALUES (%s, %s, %s)",
                (code, name, description),
            )
            print(f"  Created {code} — {name}")

        print("Seeding risk_scoring_bands...")
        for band_name, min_score, max_score, color_hex, display_order, requires_board in RISK_SCORING_BANDS:
            existing = db.execute(
                "SELECT id FROM risk_scoring_bands WHERE min_score = %s AND max_score = %s",
                (min_score, max_score),
            ).fetchone()
            if existing:
                print(f"  Band {band_name} ({min_score}-{max_score}) already exists, skipping.")
                continue
            db.execute(
                "INSERT INTO risk_scoring_bands "
                "(band_name, min_score, max_score, color_hex, display_order, requires_board_notification) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (band_name, min_score, max_score, color_hex, display_order, requires_board),
            )
            print(f"  Created band {band_name} ({min_score}-{max_score})")

        db.commit()
        print("Risk category and scoring band seed complete.")


if __name__ == "__main__":
    seed()
