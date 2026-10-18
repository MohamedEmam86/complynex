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
Prometheus metrics for ComplyNex CMS.
Exposes /metrics (text/plain) compatible with Prometheus scraping.
All counters use a multiprocess-safe registry backed by the prometheus_client
default (works with gunicorn multi-worker via PROMETHEUS_MULTIPROC_DIR).
"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# ── Counters ─────────────────────────────────────────────────────────────────

screening_requests = Counter(
    'complynex_screenings_total',
    'Total sanctions/PEP screening requests',
    ['result'],            # clear | queue | hit
)

ekyc_sessions = Counter(
    'complynex_ekyc_sessions_total',
    'Total eKYC sessions created',
)

ekyc_pipeline_results = Counter(
    'complynex_ekyc_pipeline_results_total',
    'eKYC pipeline decisions',
    ['decision'],          # PASS | REVIEW | FAIL
)

aml_alerts = Counter(
    'complynex_aml_alerts_total',
    'AML/TM alerts raised',
    ['severity'],          # HIGH | MEDIUM | LOW
)

login_attempts = Counter(
    'complynex_login_attempts_total',
    'Login attempts',
    ['outcome'],           # success | failure | mfa_required | mfa_failure
)

audit_events = Counter(
    'complynex_audit_events_total',
    'Audit log entries written',
    ['module'],
)

# ── Histograms ────────────────────────────────────────────────────────────────

request_latency = Histogram(
    'complynex_http_request_duration_seconds',
    'HTTP request latency',
    ['method', 'endpoint'],
    buckets=[.05, .1, .25, .5, 1, 2.5, 5, 10],
)

screening_latency = Histogram(
    'complynex_screening_duration_seconds',
    'Sanctions screening engine latency',
    buckets=[.1, .5, 1, 2, 5, 10, 30],
)

# ── Gauges ────────────────────────────────────────────────────────────────────

active_ekyc_sessions = Gauge(
    'complynex_ekyc_sessions_active',
    'eKYC sessions currently pending review',
)

open_aml_alerts = Gauge(
    'complynex_aml_alerts_open',
    'Open AML alerts (NEW + ASSIGNED + INVESTIGATING)',
)

screening_queue_depth = Gauge(
    'complynex_screening_queue_depth',
    'Screening queue entries with status=pending',
)

compliance_health = Gauge(
    'complynex_compliance_health_score',
    'Compliance health score 0-100',
)


def metrics_response():
    """Return a Flask Response with the Prometheus text exposition."""
    from flask import Response as _Response
    return _Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)
