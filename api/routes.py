"""
Versioned REST API — /api/v1/

Endpoints
---------
Screening
  POST /api/v1/screening/check           screen an entity against all lists

AML / KYC
  POST /api/v1/aml/customer              create/onboard a customer
  GET  /api/v1/aml/customer/<ref>        fetch customer record + risk
  POST /api/v1/aml/transaction           submit a transaction for TM evaluation
  GET  /api/v1/aml/alerts                list open TM alerts (paginated)

KYC (eKYC sessions)
  POST /api/v1/kyc/session               create eKYC session (returns link)
  GET  /api/v1/kyc/session/<token>       check eKYC session status

API key management (superadmin only, uses session auth not key auth)
  POST   /api/v1/keys                    issue a new API key
  GET    /api/v1/keys                    list all keys
  DELETE /api/v1/keys/<id>              revoke a key

OpenAPI spec
  GET  /api/v1/openapi.json              machine-readable spec (no auth needed)
"""
import hashlib
import os
import secrets
import json
from datetime import datetime, timezone

from flask import request, jsonify, g
from flask_login import login_required, current_user
from flask_wtf.csrf import validate_csrf, ValidationError as CSRFValidationError

from api import api_v1_bp
from api.auth import require_api_key
from database.db import get_db


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _ok(data, status=200):
    return jsonify({'success': True, 'data': data}), status


def _err(msg, status=400, code=None):
    payload = {'success': False, 'error': msg}
    if code:
        payload['code'] = code
    return jsonify(payload), status


def _require_json(*fields):
    """Validate JSON body; return (data, None) or (None, error_response)."""
    data = request.get_json(silent=True)
    if data is None:
        return None, _err('Request body must be JSON', 400)
    missing = [f for f in fields if not data.get(f)]
    if missing:
        return None, _err(f'Missing required fields: {", ".join(missing)}', 422)
    return data, None


# ──────────────────────────────────────────────────────────────────────────────
# Screening endpoints
# ──────────────────────────────────────────────────────────────────────────────

@api_v1_bp.route('/screening/check', methods=['POST'])
@require_api_key('screening:read')
def screening_check():
    """
    Screen an entity against sanctions, PEP, and internal blacklists.

    Body (JSON):
      name        string  required  Full name of entity
      entity_type string  optional  INDIVIDUAL|CORPORATE  (default INDIVIDUAL)
      nationality string  optional  ISO-3166 alpha-2
      dob         string  optional  YYYY-MM-DD
    """
    data, err = _require_json('name')
    if err:
        return err

    name        = data['name'].strip()
    entity_type = data.get('entity_type', 'INDIVIDUAL').upper()
    nationality = data.get('nationality', '')
    dob         = data.get('dob', '')

    try:
        from screening.customer_screening_service import screen_and_save
        # This endpoint's public contract uses INDIVIDUAL|CORPORATE; the engine's
        # own vocabulary is INDIVIDUAL|ENTITY (matching aml/routes.py's convention).
        engine_entity_type = 'ENTITY' if entity_type == 'CORPORATE' else 'INDIVIDUAL'
        res = screen_and_save(
            name=name,
            entity_type=engine_entity_type,
            dob=dob or None,
            nationality=nationality or None,
            source_module='Public API',
            screening_type='API',
            user_id=g.api_key['created_by'],
            results_screening_type='API',
        )

        return _ok({
            'query': {'name': name, 'entity_type': entity_type},
            'risk_level': res['screening_result'],
            'hit_count': res['total_matches'],
            'hits': res['matches'][:50],  # cap response size
        })
    except Exception as e:
        return _err(f'Screening engine error: {e}', 500)


# ──────────────────────────────────────────────────────────────────────────────
# AML endpoints
# ──────────────────────────────────────────────────────────────────────────────

@api_v1_bp.route('/aml/customer', methods=['POST'])
@require_api_key('aml:write')
def aml_create_customer():
    """Onboard a new customer with risk scoring."""
    data, err = _require_json('full_name', 'customer_type')
    if err:
        return err

    try:
        from models.aml import Customer
        customer_id = Customer.create(data)
        if not customer_id:
            return _err('Failed to create customer', 500)

        db = get_db()
        row = db.execute(
            "SELECT id, customer_reference, risk_classification, risk_score, status "
            "FROM customers WHERE id = %s", (customer_id,)
        ).fetchone()

        return _ok(dict(row) if row else {'id': customer_id}, 201)
    except Exception as e:
        return _err(str(e), 500)


@api_v1_bp.route('/aml/customer/<ref>', methods=['GET'])
@require_api_key('aml:read')
def aml_get_customer(ref):
    """Fetch customer record and current risk classification."""
    db = get_db()
    row = db.execute(
        """SELECT id, customer_reference, customer_type, full_name, company_name,
                  risk_classification, risk_score, risk_classification_reason,
                  nationality, status, created_at
           FROM customers WHERE customer_reference = %s""",
        (ref,)
    ).fetchone()

    if not row:
        return _err('Customer not found', 404)

    return _ok(dict(row))


@api_v1_bp.route('/aml/transaction', methods=['POST'])
@require_api_key('aml:write')
def aml_submit_transaction():
    """
    Submit a transaction for transaction-monitoring evaluation.

    Body:
      customer_reference  string   required
      amount              number   required
      currency            string   required  (e.g. EGP)
      transaction_type    string   required  (CASH_IN, CASH_OUT, TRANSFER…)
      transaction_date    string   optional  ISO-8601 (default: now)
      description         string   optional
    """
    data, err = _require_json('customer_reference', 'amount', 'currency', 'transaction_type')
    if err:
        return err

    db = get_db()
    customer = db.execute(
        "SELECT id FROM customers WHERE customer_reference = %s",
        (data['customer_reference'],)
    ).fetchone()
    if not customer:
        return _err('Customer not found', 404)

    customer_id = customer['id']
    tx_date = data.get('transaction_date') or datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    try:
        db.execute(
            """INSERT INTO transactions
               (customer_id, amount, currency, transaction_type, transaction_date, remittance_information, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, NOW())""",
            (
                customer_id,
                float(data['amount']),
                data['currency'][:10],
                data['transaction_type'][:50],
                tx_date,
                data.get('description', '')[:500],
            )
        )
        db.commit()

        tx_row = db.execute(
            "SELECT id FROM transactions WHERE customer_id = %s ORDER BY created_at DESC LIMIT 1",
            (customer_id,)
        ).fetchone()

        alerts = []
        if tx_row:
            try:
                from aml.tm_service import evaluate_transaction
                alerts = evaluate_transaction(tx_row['id'], db=db) or []
            except Exception:
                pass

        return _ok({
            'transaction_id': tx_row['id'] if tx_row else None,
            'alerts_raised': len(alerts),
            'alert_references': alerts,
        }, 201)
    except Exception as e:
        return _err(str(e), 500)


@api_v1_bp.route('/aml/alerts', methods=['GET'])
@require_api_key('aml:read')
def aml_list_alerts():
    """List open TM alerts. Query params: page (1-based), per_page (max 100)."""
    try:
        page     = max(1, int(request.args.get('page', 1)))
        per_page = min(100, max(1, int(request.args.get('per_page', 20))))
    except (ValueError, TypeError):
        return _err('Invalid pagination params', 400)
    offset   = (page - 1) * per_page

    db = get_db()
    rows = db.execute(
        """SELECT a.alert_reference, a.alert_date, a.alert_description,
                  a.alert_severity, a.status, r.rule_name, c.customer_reference
           FROM tm_alerts a
           LEFT JOIN tm_rules r ON a.rule_id = r.id
           LEFT JOIN customers c ON a.customer_id = c.id
           WHERE a.status NOT IN ('CLOSED', 'FALSE_POSITIVE')
           ORDER BY a.alert_date DESC
           LIMIT %s OFFSET %s""",
        (per_page, offset)
    ).fetchall()

    total = (db.execute("SELECT COUNT(*) as n FROM tm_alerts WHERE status NOT IN ('CLOSED', 'FALSE_POSITIVE')").fetchone() or {}).get('n', 0)

    return _ok({
        'alerts': [dict(r) for r in rows],
        'page': page, 'per_page': per_page, 'total': total,
    })


# ──────────────────────────────────────────────────────────────────────────────
# KYC / eKYC endpoints
# ──────────────────────────────────────────────────────────────────────────────

@api_v1_bp.route('/kyc/session', methods=['POST'])
@require_api_key('kyc:write')
def kyc_create_session():
    """
    Create an eKYC session and return a one-time verification link.

    Body:
      customer_reference  string  required
      document_type       string  optional  (NATIONAL_ID, PASSPORT…)
      language            string  optional  ar|en (default: ar)
    """
    data, err = _require_json('customer_reference')
    if err:
        return err

    try:
        from models.ekyc import EkycSession
        customer_ref = data['customer_reference']
        doc_type     = data.get('document_type', 'NATIONAL_ID')
        language     = data.get('language', 'ar')

        session_obj = EkycSession.create(
            customer_reference=customer_ref,
            document_type=doc_type,
            locale=language,
        )
        if not session_obj:
            return _err('Failed to create KYC session', 500)

        base_url = os.environ.get('APP_BASE_URL', 'https://complynex.online')
        link = f"{base_url}/ekyc/verify/{session_obj['session_token']}"

        return _ok({'session_id': session_obj['id'], 'token': session_obj['session_token'],
                    'link': link, 'status': 'CREATED'}, 201)
    except Exception as e:
        return _err(str(e), 500)


@api_v1_bp.route('/kyc/session/<token>', methods=['GET'])
@require_api_key('kyc:read')
def kyc_session_status(token):
    """Get the current status of a KYC verification session."""
    try:
        from models.ekyc import EkycSession
        session_obj = EkycSession.get_by_token(token)
        if not session_obj:
            return _err('Session not found', 404)

        safe = {k: v for k, v in dict(session_obj).items()
                if k not in ('id_image_path', 'selfie_image_path')}
        return _ok(safe)
    except Exception as e:
        return _err(str(e), 500)


# ──────────────────────────────────────────────────────────────────────────────
# API key management  (session-authenticated, superadmin only)
# ──────────────────────────────────────────────────────────────────────────────

def _superadmin_session():
    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required', 'code': 401}), 401
    role = getattr(current_user, 'role', '')
    if role not in ('superadmin', 'admin', 'it_admin'):
        return jsonify({'error': 'Superadmin required', 'code': 403}), 403
    # These 3 routes are session-cookie-authenticated (not API-key-authenticated),
    # but api_v1_bp is CSRF-exempt as a whole (it's a programmatic API elsewhere
    # in this blueprint). Enforce CSRF manually here for the state-changing verbs
    # so a session-authenticated admin can't be CSRF'd into issuing/revoking keys.
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        try:
            validate_csrf(request.headers.get('X-CSRFToken', ''))
        except CSRFValidationError:
            return jsonify({'error': 'CSRF token missing or invalid', 'code': 400}), 400
    return None


@api_v1_bp.route('/keys', methods=['POST'])
def create_api_key():
    guard = _superadmin_session()
    if guard:
        return guard

    data, err = _require_json('name')
    if err:
        return err

    raw_key    = 'bpk_' + secrets.token_hex(28)   # 64-char total with prefix
    key_hash   = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]
    scopes     = data.get('scopes', 'screening:read,aml:read,kyc:read')
    rate_limit = int(data.get('rate_limit', 100))
    expires_at = data.get('expires_at')  # ISO-8601 or None

    db = get_db()
    row = db.execute(
        """INSERT INTO api_keys (name, key_hash, key_prefix, scopes, rate_limit, expires_at, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id, created_at""",
        (data['name'], key_hash, key_prefix, scopes, rate_limit, expires_at, current_user.id)
    ).fetchone()
    db.commit()

    # Return the raw key ONCE — it is never stored and cannot be recovered
    return _ok({
        'id': row['id'],
        'name': data['name'],
        'key': raw_key,   # shown once only
        'key_prefix': key_prefix,
        'scopes': scopes,
        'rate_limit': rate_limit,
        'expires_at': expires_at,
        'created_at': str(row['created_at']),
        'warning': 'Store this key securely — it will NOT be shown again.',
    }, 201)


@api_v1_bp.route('/keys', methods=['GET'])
def list_api_keys():
    guard = _superadmin_session()
    if guard:
        return guard

    db = get_db()
    rows = db.execute(
        """SELECT k.id, k.name, k.key_prefix, k.scopes, k.rate_limit,
                  k.is_active, k.last_used_at, k.created_at, k.expires_at,
                  u.email as owner_email
           FROM api_keys k
           LEFT JOIN users u ON k.created_by = u.id
           ORDER BY k.created_at DESC"""
    ).fetchall()

    return _ok({'keys': [dict(r) for r in rows]})


@api_v1_bp.route('/keys/<int:key_id>', methods=['DELETE'])
def revoke_api_key(key_id):
    guard = _superadmin_session()
    if guard:
        return guard

    db = get_db()
    row = db.execute("SELECT id FROM api_keys WHERE id = %s", (key_id,)).fetchone()
    if not row:
        return _err('Key not found', 404)

    db.execute("UPDATE api_keys SET is_active = FALSE WHERE id = %s", (key_id,))
    db.commit()
    return _ok({'revoked': True, 'key_id': key_id})


# ──────────────────────────────────────────────────────────────────────────────
# OpenAPI 3.0 spec (no auth required)
# ──────────────────────────────────────────────────────────────────────────────

OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "ComplyNex Compliance API",
        "version": "1.0.0",
        "description": (
            "Versioned REST API for AML screening, KYC verification, and "
            "transaction monitoring. Regulated by the Central Bank of Egypt."
        ),
        "contact": {"email": "compliance@complynex.online"},
    },
    "servers": [{"url": "/api/v1", "description": "Production"}],
    "security": [{"ApiKeyAuth": []}],
    "components": {
        "securitySchemes": {
            "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
        }
    },
    "paths": {
        "/screening/check": {
            "post": {
                "summary": "Screen an entity",
                "tags": ["Screening"],
                "security": [{"ApiKeyAuth": ["screening:read"]}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {
                            "name":        {"type": "string"},
                            "entity_type": {"type": "string", "enum": ["INDIVIDUAL","CORPORATE"]},
                            "nationality": {"type": "string"},
                            "dob":         {"type": "string", "format": "date"},
                        }
                    }}}
                },
                "responses": {
                    "200": {"description": "Screening result"},
                    "401": {"description": "Invalid or missing API key"},
                    "429": {"description": "Rate limit exceeded"},
                },
            }
        },
        "/aml/customer": {
            "post": {
                "summary": "Onboard a customer",
                "tags": ["AML"],
                "security": [{"ApiKeyAuth": ["aml:write"]}],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["full_name", "customer_type"],
                    "properties": {
                        "full_name":     {"type": "string"},
                        "customer_type": {"type": "string", "enum": ["INDIVIDUAL","CORPORATE"]},
                    }
                }}}},
                "responses": {"201": {"description": "Customer created"}, "401": {"description": "Unauthorized"}},
            }
        },
        "/aml/customer/{ref}": {
            "get": {
                "summary": "Get customer record",
                "tags": ["AML"],
                "parameters": [{"name": "ref", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Customer data"}, "404": {"description": "Not found"}},
            }
        },
        "/aml/transaction": {
            "post": {
                "summary": "Submit transaction for TM evaluation",
                "tags": ["AML"],
                "security": [{"ApiKeyAuth": ["aml:write"]}],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["customer_reference","amount","currency","transaction_type"],
                    "properties": {
                        "customer_reference": {"type": "string"},
                        "amount":             {"type": "number"},
                        "currency":           {"type": "string"},
                        "transaction_type":   {"type": "string"},
                        "transaction_date":   {"type": "string", "format": "date-time"},
                        "description":        {"type": "string"},
                    }
                }}}},
                "responses": {"201": {"description": "Transaction submitted and evaluated"}},
            }
        },
        "/aml/alerts": {
            "get": {
                "summary": "List open TM alerts",
                "tags": ["AML"],
                "parameters": [
                    {"name": "page",     "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20, "maximum": 100}},
                ],
                "responses": {"200": {"description": "Alert list"}},
            }
        },
        "/kyc/session": {
            "post": {
                "summary": "Create eKYC session",
                "tags": ["KYC"],
                "security": [{"ApiKeyAuth": ["kyc:write"]}],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["customer_reference"],
                    "properties": {
                        "customer_reference": {"type": "string"},
                        "document_type":      {"type": "string"},
                        "language":           {"type": "string", "enum": ["ar","en"]},
                    }
                }}}},
                "responses": {"201": {"description": "Session created with verification link"}},
            }
        },
        "/kyc/session/{token}": {
            "get": {
                "summary": "Get eKYC session status",
                "tags": ["KYC"],
                "parameters": [{"name": "token", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Session status"}},
            }
        },
        "/keys": {
            "get": {"summary": "List API keys (superadmin)", "tags": ["Keys"], "security": [{"cookieAuth": []}],
                    "responses": {"200": {"description": "Key list"}}},
            "post": {"summary": "Create API key (superadmin)", "tags": ["Keys"], "security": [{"cookieAuth": []}],
                     "requestBody": {"required": True, "content": {"application/json": {"schema": {
                         "type": "object", "required": ["name"],
                         "properties": {
                             "name":       {"type": "string"},
                             "scopes":     {"type": "string"},
                             "rate_limit": {"type": "integer"},
                             "expires_at": {"type": "string", "format": "date-time"},
                         }
                     }}}},
                     "responses": {"201": {"description": "Key created — raw key returned once only"}}},
        },
        "/keys/{id}": {
            "delete": {"summary": "Revoke API key (superadmin)", "tags": ["Keys"], "security": [{"cookieAuth": []}],
                       "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                       "responses": {"200": {"description": "Key revoked"}}},
        },
    },
}


@api_v1_bp.route('/openapi.json', methods=['GET'])
def openapi_spec():
    """Serve the OpenAPI 3.0 spec (no auth required)."""
    return jsonify(OPENAPI_SPEC)
