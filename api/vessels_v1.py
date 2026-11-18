# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Vessel screening API (V3), same conventions as api/screening_v1.py (X-API-Key with scopes, per-key rate
limit, Idempotency-Key, X-Request-Id, one error shape, sandbox keys):

    POST /api/v1/vessels/screen          scope vessels:screen   screen one ship
    GET  /api/v1/vessels/screenings/<id> scope vessels:screen   the result with the analysts' decisions

Body: {"name", "imo", "mmsi", "call_sign", "flag", "flags_past" (list or ";"-separated), "owner",
"vessel_type", "customer_ref"} - at least one of name / imo / mmsi / call_sign / owner.
The answer never names a list: hits are on "International approved lists" (owner decision, 17 Nov 2026).
The system alerts and records; it never blocks or freezes anything.
"""
import json
import logging

from flask import g

from api import api_v1_bp
from api import screening_v1 as V1
from database.db import get_db

logger = logging.getLogger(__name__)
FIELDS = ('name', 'imo', 'mmsi', 'call_sign', 'flag', 'owner', 'vessel_type')
SCOPE = 'vessels:screen'
LABEL = 'International approved lists'


def _en(items):
    from screening.vessel_engine import text
    return text(items, 'en')


def _category(o):
    """The generic category of an owner hit (SANCTIONS, TERROR ...), never the list's own list_type."""
    from screening.vessel_store import list_category
    return list_category(o.get('list_type_raw') or o.get('list_type'))


def _view(sid, res, customer_ref, sandbox=False):
    """API body of a vessel screening; no list names, no internal ids beyond the ship's own record id."""
    return {
        'id': sid, 'object': 'vessel_screening', 'sandbox': sandbox, 'customer_ref': customer_ref,
        'status': res['tier'], 'score': res['score'],
        'requires_review': bool(res['hits'] or res['owner_hits']),
        'query': res['query'], 'warnings': _en(res.get('warnings')),
        'hits': [{'vessel_id': h['watchlist_id'], 'name': h['name'], 'matched_name': h.get('matched_name'),
                  'imo': h.get('imo'), 'mmsi': h.get('mmsi'), 'call_sign': h.get('call_sign'), 'flag': h.get('flag'),
                  'former_flags': h.get('flags_past') or [], 'type': h.get('type'), 'year_built': h.get('year_built'),
                  'score': h['score'], 'tier': h['tier'], 'layer': h['layer'],
                  'explanation': _en(h.get('explanation')),
                  'explanation_codes': [e.get('code') for e in h.get('explanation') or [] if isinstance(e, dict)],
                  'fields': h.get('fields') or {}, 'measures': h.get('measures') or [],
                  'list_count': len(h.get('sources') or []) or 1, 'lists': LABEL,
                  'parties': [{'name': p.get('name'), 'role': p.get('role'), 'listed': bool(p.get('party_listed'))}
                              for p in (h.get('parties') or [])[:20]],
                  'reopened': bool(h.get('reopened'))}
                 for h in res['hits']],
        'owner_hits': [{'name': o['name'], 'entered': o.get('query'), 'score': o['score'], 'tier': o['tier'],
                        'category': _category(o), 'lists': LABEL} for o in res['owner_hits']],
        'cleared_before': [{'name': s['name'], 'imo': s.get('imo'), 'score': s['score']}
                           for s in res.get('suppressed') or []],
        'risk': {'score': res['risk']['score'], 'indicators': _en(res['risk']['lines']),
                 'codes': [e.get('code') for e in res['risk']['lines'] if isinstance(e, dict)]},
    }


def _sandbox(f):
    """Deterministic sandbox answer: IMO 9999990 (valid check digit) is a confirmed hit, anything else is clear."""
    from screening import vessel_engine as VE
    hit = []
    if (f.get('imo') or '').replace('IMO', '').strip() == '9999990':
        hit = [{'watchlist_id': 0, 'name': 'SANDBOX TEST VESSEL', 'imo': '9999990', 'score': 100.0,
                'tier': 'CONFIRMED', 'layer': 'identifier', 'explanation': [VE.say('same_imo', v='9999990', when='current')],
                'measures': ['asset_freeze'], 'sources': ['sandbox']}]
    return {'query': f, 'warnings': [], 'tier': 'CONFIRMED' if hit else 'CLEAR', 'score': 100.0 if hit else 0.0,
            'hits': hit, 'owner_hits': [], 'risk': {'score': 0, 'lines': []}, 'near': [], 'suppressed': []}


@api_v1_bp.route('/vessels/screen', methods=['POST'])
@V1.v1_key(SCOPE)
@V1.idempotent
def v1_screen_vessel():
    data = V1._json_body()
    if data is None:
        return V1.err('invalid_request', 'Request body must be a JSON object', 400)
    f = {k: str(data.get(k) or '').strip()[:300] for k in FIELDS}
    fp = data.get('flags_past')
    f['flags_past'] = [str(x).strip()[:60] for x in fp][:20] if isinstance(fp, list) else str(fp or '').strip()[:300]
    ref = str(data.get('customer_ref') or '').strip()[:200] or None
    if not any(f[k] for k in ('name', 'imo', 'mmsi', 'call_sign', 'owner')):
        return V1.err('validation_failed', 'Give at least one of name, imo, mmsi, call_sign, owner', 422)
    from screening import vessel_engine as VE
    if g.api_sandbox:
        return V1.ok(_view(None, _sandbox(f), ref, sandbox=True), 201)
    db = get_db()
    try:
        res = VE.screen_vessel(conn=db, screen_party=VE.party_screener() if f['owner'] else None, **f)
    except Exception:
        logger.exception('[API] vessel screening failed')
        try:
            db.rollback()
        except Exception:
            pass
        return V1.err('engine_unavailable', 'The screening engine failed; retry later', 503,
                      headers={'Retry-After': '30'})
    finally:
        try:
            from screening.routes import get_engine
            V1._release_engine_conn(get_engine())
        except Exception:
            pass
    from screening.vessel_routes import save_screening
    sid = save_screening(db, res, V1._acting_user(), kind='api', customer_ref=ref)
    body = _view(int(sid), res, ref)
    try:
        api_id = V1._record('vessel', customer_ref=ref, result_id=int(sid), status=res['tier'], response=body)
        V1._emit('vessel_screening.completed', {'id': sid, 'status': res['tier'], 'customer_ref': ref,
                                                'requires_review': body['requires_review']},
                 f'vessel_screening.completed:{sid}')
        logger.info('[API] vessel screening %s recorded as api_screenings %s', sid, api_id)
    except Exception:
        db.rollback()
    return V1.ok(body, 201)


@api_v1_bp.route('/vessels/screenings/<int:sid>', methods=['GET'])
@V1.v1_key(SCOPE)
def v1_get_vessel_screening(sid):
    db = get_db()
    own = db.execute("""SELECT id FROM api_screenings WHERE client_id = %s AND kind = 'vessel' AND result_id = %s
                        LIMIT 1""", (g.api_client, sid)).fetchone()
    row = db.execute("SELECT * FROM vessel_screenings WHERE id = %s AND kind = 'api'", (sid,)).fetchone() if own else None
    if not row:
        return V1.err('not_found', 'No such vessel screening for this client', 404)
    res = row['result'] if isinstance(row['result'], dict) else json.loads(row['result'])
    body = _view(sid, res, row['customer_ref'])
    decisions = db.execute("""SELECT hit_kind, listed_key, watchlist_id, decision, reason, decided_at
                              FROM vessel_hit_decisions WHERE screening_id = %s ORDER BY decided_at""", (sid,)).fetchall()
    body['review'] = [{'hit': d['hit_kind'], 'vessel_id': d['watchlist_id'], 'decision': d['decision'],
                       'reason': d['reason'], 'decided_at': d['decided_at'].isoformat() if d['decided_at'] else None}
                      for d in decisions]
    return V1.ok(body)


def _register_spec():
    try:
        from api.routes import OPENAPI_SPEC
        ref = V1._schema_ref
        OPENAPI_SPEC['components'].setdefault('schemas', {}).update({
            'VesselScreeningRequest': {'type': 'object', 'properties': {
                'name': {'type': 'string', 'maxLength': 300, 'description': 'ship name, Arabic or Latin'},
                'imo': {'type': 'string', 'description': '7-digit IMO ship number'},
                'mmsi': {'type': 'string'}, 'call_sign': {'type': 'string'},
                'flag': {'type': 'string', 'description': 'flag state (name or ISO code)'},
                'flags_past': {'type': 'array', 'items': {'type': 'string'}},
                'owner': {'type': 'string', 'description': 'owner / operator / manager, screened as a company'},
                'vessel_type': {'type': 'string'}, 'customer_ref': {'type': 'string'}}},
            'VesselScreening': {'type': 'object', 'properties': {
                'id': {'type': 'integer'}, 'object': {'type': 'string', 'example': 'vessel_screening'},
                'status': {'type': 'string', 'enum': ['CONFIRMED', 'POTENTIAL', 'LOW', 'CLEAR', 'INCOMPLETE']},
                'score': {'type': 'number'}, 'requires_review': {'type': 'boolean'},
                'hits': {'type': 'array', 'items': {'type': 'object'}},
                'owner_hits': {'type': 'array', 'items': {'type': 'object'}},
                'risk': {'type': 'object'}, 'review': {'type': 'array', 'items': {'type': 'object'}}}},
        })
        err = {'description': 'Error', 'content': {'application/json': {'schema': ref('Error')}}}
        OPENAPI_SPEC['paths'].update({
            '/vessels/screen': {'post': {
                'summary': 'Screen a vessel (IMO / MMSI / call sign, names in any script, owner, flag risk)',
                'tags': ['Vessels'], 'security': [{'ApiKeyAuth': [SCOPE]}], 'parameters': [V1._IDEM],
                'requestBody': {'required': True, 'content': {'application/json': {'schema': ref('VesselScreeningRequest')}}},
                'responses': {'201': {'description': 'Result', 'content': {'application/json': {'schema': ref('VesselScreening')}}},
                              '401': err, '403': err, '422': err, '429': err, '503': err}}},
            '/vessels/screenings/{id}': {'get': {
                'summary': 'A vessel screening with the analysts\' decisions', 'tags': ['Vessels'],
                'security': [{'ApiKeyAuth': [SCOPE]}],
                'parameters': [{'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'integer'}}],
                'responses': {'200': {'description': 'Result'}, '404': err, '401': err, '403': err}}},
        })
    except Exception as e:
        logger.warning('[API] vessel spec update failed: %s', e)


_register_spec()
