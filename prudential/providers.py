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
Finance data interface — ERP-ready.

The prudential checks never read finance tables directly: they ask the active
provider. Today the provider is the built-in database registers (manual entry
and CSV import). A future finance / ERP module registers its own provider
with the same three methods and every check, page and report keeps working:

    from prudential.providers import register_provider

    class ErpProvider:
        name = 'erp'
        def financial_periods(self, db): ...      # rows shaped like pr_financial_periods
        def facilities(self, db): ...             # rows shaped like pr_facilities
        def related_party_items(self, db): ...    # rows shaped like pr_rp_items (+ party name/relation)

    register_provider(ErpProvider())
"""


class DatabaseProvider:
    name = 'registers'

    def financial_periods(self, db):
        return [dict(r) for r in db.execute("SELECT * FROM pr_financial_periods ORDER BY period_end").fetchall()]

    def facilities(self, db):
        return [dict(r) for r in db.execute("SELECT * FROM pr_facilities ORDER BY reference").fetchall()]

    def related_party_items(self, db):
        return [dict(r) for r in db.execute("""
            SELECT i.*, p.name AS party_name, p.relation, p.exited_on
            FROM pr_rp_items i JOIN pr_related_parties p ON p.id = i.related_party_id
            ORDER BY i.item_date DESC, i.id DESC""").fetchall()]


_PROVIDER = DatabaseProvider()


def register_provider(provider):
    global _PROVIDER
    _PROVIDER = provider
    return provider


def get():
    return _PROVIDER
