"""
API key authentication and rate limiting for /api/v1/.

Usage:
    @require_api_key('screening:read')
    def my_view():
        ...

The decorator:
  - Reads X-API-Key header
  - Hashes it and looks up api_keys table
  - Checks is_active, expiry, and scope
  - Enforces per-key rate limit via Redis (sliding window)
  - Writes every call to api_audit_log
"""
import hashlib
import time
from functools import wraps
from datetime import datetime, timezone

from flask import request, jsonify, g

from database.db import get_db


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_redis():
    try:
        import redis
        return redis.Redis.from_url('redis://localhost:6379/2', socket_timeout=0.5)
    except Exception:
        return None


def _check_rate_limit(key_id: int, limit: int) -> bool:
    """Sliding-window rate limit using Redis.  Returns True if allowed."""
    r = _get_redis()
    if r is None:
        return True  # Redis unavailable — let the request through

    now = time.time()
    window = 60  # 1 minute
    bucket = f'rl:apiv1:{key_id}'
    try:
        pipe = r.pipeline()
        pipe.zadd(bucket, {str(now): now})
        pipe.zremrangebyscore(bucket, 0, now - window)
        pipe.zcard(bucket)
        pipe.expire(bucket, window * 2)
        results = pipe.execute()
        count = results[2]
        return count <= limit
    except Exception:
        return True


def _write_audit(key_id, key_prefix, status_code, response_ms):
    try:
        db = get_db()
        body_snap = None
        if request.is_json:
            raw = request.get_data(as_text=True)
            body_snap = raw[:400] if raw else None
        db.execute(
            """INSERT INTO api_audit_log
               (key_id, key_prefix, endpoint, method, status_code, request_ip, request_body, response_ms, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
            (
                key_id, key_prefix,
                request.path, request.method,
                status_code,
                request.headers.get('X-Forwarded-For', request.remote_addr or '')[:45],
                body_snap,
                response_ms,
            )
        )
        db.execute(
            "UPDATE api_keys SET last_used_at = NOW() WHERE id = %s",
            (key_id,)
        )
        db.commit()
    except Exception:
        pass


def require_api_key(*required_scopes):
    """Decorator factory. Pass required scope strings (e.g. 'screening:read')."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            raw_key = request.headers.get('X-API-Key', '').strip()
            if not raw_key:
                return jsonify({'error': 'Missing X-API-Key header', 'code': 401}), 401

            key_hash = _hash_key(raw_key)
            t0 = time.monotonic()

            db = get_db()
            row = db.execute(
                "SELECT * FROM api_keys WHERE key_hash = %s",
                (key_hash,)
            ).fetchone()

            if not row:
                _write_audit(None, raw_key[:8], 401, int((time.monotonic() - t0) * 1000))
                return jsonify({'error': 'Invalid API key', 'code': 401}), 401

            row = dict(row)

            if not row['is_active']:
                _write_audit(row['id'], row['key_prefix'], 403, 0)
                return jsonify({'error': 'API key is disabled', 'code': 403}), 403

            if row.get('expires_at'):
                exp = row['expires_at']
                if isinstance(exp, str):
                    exp = datetime.fromisoformat(exp)
                if exp.replace(tzinfo=None) < datetime.utcnow():
                    _write_audit(row['id'], row['key_prefix'], 403, 0)
                    return jsonify({'error': 'API key has expired', 'code': 403}), 403

            # Scope check
            granted = set(s.strip() for s in row['scopes'].split(',') if s.strip())
            for scope in required_scopes:
                if scope not in granted:
                    _write_audit(row['id'], row['key_prefix'], 403, 0)
                    return jsonify({'error': f'Scope required: {scope}', 'code': 403}), 403

            # Rate limit
            if not _check_rate_limit(row['id'], row['rate_limit']):
                _write_audit(row['id'], row['key_prefix'], 429, 0)
                return jsonify({'error': 'Rate limit exceeded', 'code': 429,
                                'limit': row['rate_limit'], 'window': '1 minute'}), 429

            # Attach key info to request context
            g.api_key = row

            response = f(*args, **kwargs)

            # Write audit after response
            status_code = response[1] if isinstance(response, tuple) else 200
            ms = int((time.monotonic() - t0) * 1000)
            _write_audit(row['id'], row['key_prefix'], status_code, ms)

            return response
        return wrapped
    return decorator
