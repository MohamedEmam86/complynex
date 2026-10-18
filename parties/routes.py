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
Entity 360: search the party registry and view one party's linked source
records + associated cases in one place. Gated on 'aml' permission — party
data is fundamentally KYC/customer data, same sensitivity class merchant_kyc
already stacks 'aml' permission alongside its own for.
"""

from flask import render_template, request
from flask_login import login_required

from database.db import get_db
from utils.decorators import permission_required
from models.party import Party, PartyLink

from . import parties_bp

# Where each link_role's source record can be viewed, for building a link
# from the Entity 360 page back to the actual working record.
_SOURCE_VIEW_ENDPOINT = {
    'customers': 'aml.view_customer',
    'merchants': 'merchant_kyc.view_merchant',
}


@parties_bp.route('/')
@login_required
@permission_required('aml', level='view')
def party_list():
    q = request.args.get('q', '').strip()
    parties = Party.search(q, limit=100) if q else []
    return render_template('parties/list.html', parties=parties, q=q)


@parties_bp.route('/<int:party_id>')
@login_required
@permission_required('aml', level='view')
def party_detail(party_id):
    party = Party.get_by_id(party_id)
    if not party:
        return render_template('parties/not_found.html'), 404

    links = PartyLink.get_for_party(party_id)
    for link in links:
        link['view_endpoint'] = _SOURCE_VIEW_ENDPOINT.get(link['source_table'])

    cases = get_db().execute("""
        SELECT * FROM cases WHERE party_id = %s ORDER BY opened_at DESC
    """, (party_id,)).fetchall()

    return render_template('parties/view.html', party=party, links=links, cases=cases)
