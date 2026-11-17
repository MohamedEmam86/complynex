# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
POST /api/v1/vessels/screen  (scope screening:write) - screen one ship (V3).

Body: {"name", "imo", "mmsi", "call_sign", "flag", "owner", "vessel_type", "customer_ref"} - at least one of
name / imo / mmsi / call_sign / owner. The answer never names a list: hits are on "International approved
lists" (owner decision, 17 Nov 2026).
"""
import json
import logging

from flask import g

from api import api_v1_bp
from api import screening_v1 as V1
from database.db import get_db

logger = logging.getLogger(__name__)
FIELDS = ('name', 'imo', 'mmsi', 'call_sign', 'flag', 'owner', 'vessel_type')
LABEL = 'International approved lists'


def _view(sid, res, customer_ref, sandbox=False):
    return {
        'id': sid, 'object': 'vessel_screening', 'sandbox': sandbox, 'customer_ref': customer_ref,
        'status': res['tier'], 'score': res['score'], 'requires_review': res['tier'] in ('CONFIRMED', 'POTENTIAL', 'LOW'),
        'query': res['query'], 'warnings': res['warnings'],
        'hits': [{'vessel_id': h['watchlist_id'], 'name': h['name'], 'matched_name': h.get('matched_name'),
                  'imo': h.get('imo'), 'mmsi': h.get('mmsi'), 'call_sign': h.get('call_sign'), 'flag': h.get('flag'),
                  'type': h.get('type'), 'score': h['score'], 'tier': h['tier'], 'layer': h['layer'],
                  'explanation': h['explanation'], 'measures': h.get('measures') or [], 'lists': LABEL}
                 for h in res['hits']],
        'owner_hits': [{'name': o['name'], 'score': o['score'], 'tier': o['tier'], 'lists': LABEL}
                       for o in res['owner_hits']],
        'risk': res['risk'],
    }


@api_v1_bp.route('/vessels/screen', methods=['POST'])
@V1.v1_key('screening:write')
@V1.idempotent
def v1_screen_vessel():
    data = V1._json_body()
    if data is None:
        return V1.err('invalid_request', 'Request body must be a JSON object', 400)
    f = {k: str(data.get(k) or '').strip()[:300] for k in FIELDS}
    ref = str(data.get('customer_ref') or '').strip()[:200] or None
    if not any(f[k] for k in ('name', 'imo', 'mmsi', 'call_sign', 'owner')):
        return V1.err('validation_failed', 'Give at least one of name, imo, mmsi, call_sign, owner', 422)
    from screening import vessel_engine as VE
    if g.api_sandbox:
        res = {'query': f, 'warnings': [], 'tier': 'CLEAR', 'score': 0.0, 'hits': [], 'owner_hits': [],
               'risk': {'score': 0, 'lines': []}, 'near': []}
        return V1.ok(_view(None, res, ref, sandbox=True), 201)
    db = get_db()
    try:
        res = VE.screen_vessel(conn=db, screen_party=VE.party_screener() if f['owner'] else None, **f)
    except Exception:
        logger.exception('[API] vessel screening failed')
        return V1.err('engine_unavailable', 'The screening engine failed; retry later', 503,
                      headers={'Retry-After': '30'})
    finally:
        try:
            from screening.routes import get_engine
            V1._release_engine_conn(get_engine())
        except Exception:
            pass
    row = db.execute("""INSERT INTO vessel_screenings (user_id, kind, customer_ref, query, result, tier, hit_count)
                        VALUES (%s, 'api', %s, %s, %s, %s, %s) RETURNING id""",
                     (V1._acting_user(), ref, json.dumps(res['query'], ensure_ascii=False),
                      json.dumps(res, ensure_ascii=False, default=str), res['tier'],
                      len(res['hits']) + len(res['owner_hits']))).fetchone()
    db.commit()
    body = _view(int(row['id']), res, ref)
    try:
        V1._record('vessel', customer_ref=ref, status=res['tier'], response=body)
    except Exception:
        db.rollback()
    return V1.ok(body, 201)
