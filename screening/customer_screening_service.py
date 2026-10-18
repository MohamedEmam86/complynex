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
Single shared entry point for other modules (aml, merchant_kyc, ...) to run a
sanctions/PEP screen and persist the result — routes through the same engine
pipeline (`get_engine()` / `MultiSourceScreener`) `screening`'s own routes use,
instead of each caller instantiating its own engine and writing to
screening_history/screening_results/screening_queue independently.
"""

import json
from database.db import get_db
from flask_login import current_user

HIGH_RISK_THRESHOLD = 70.0


def screen_and_save(name, entity_type='INDIVIDUAL', dob=None, nationality=None,
                     gender=None, national_id=None, employer=None,
                     source_module='Manual Screening', source_record_id=None,
                     screening_type='API', user_id=None,
                     write_results_table=True, results_screening_type=None):
    """
    Screen `name` and persist the result to screening_history, screening_results
    (backward compat), and screening_queue (for high-risk hits).

    `write_results_table` controls whether a row is also written to the legacy
    `screening_results` table (backward compat for older UI/reports); pass
    `results_screening_type` to control the literal value written to its
    `screening_type` column (some callers filter on that exact string).

    Returns a dict with: history_id, results_id, queue_ids, screening_result,
    status, total_matches, high_risk_matches, auto_cleared_matches,
    highest_score, matches, adverse_media, adverse_media_summary,
    processing_time_ms.
    """
    from screening.routes import get_engine  # local import: avoid loading the ML engine at module-import time

    if user_id is None:
        user_id = current_user.id

    engine = get_engine()
    # Note: the canonical engine (ComplyNexScreeningEngine, via MultiSourceScreener)
    # has no `gender` parameter — unlike HybridScreeningEngine, which some callers
    # used before. `gender` is accepted here for interface parity but intentionally
    # not forwarded, since passing it raises TypeError.
    result = engine.screen_person(
        name=name,
        date_of_birth=dob,
        nationality=nationality,
        entity_type=entity_type,
        national_id=national_id,
        employer=employer,
    )

    matches = result.get('matches', [])
    total_matches = result.get('total_matches', len(matches))
    highest_score = result.get('highest_score', 0.0)
    high_risk = [m for m in matches if m.get('match_score', 0) >= HIGH_RISK_THRESHOLD]
    auto_cleared = [m for m in matches if m.get('match_score', 0) < HIGH_RISK_THRESHOLD]

    if result.get('screening_result') == 'WHITE_LISTED':
        status = 'Completed'
        screening_result = 'WHITE_LISTED'
    elif high_risk:
        status = 'Pending Review'
        screening_result = 'POTENTIAL_MATCH'
    else:
        status = 'Completed'
        screening_result = 'CLEAR'

    db = get_db()

    history_cursor = db.execute("""
        INSERT INTO screening_history
            (entity_name, entity_type, screening_type, initiated_by,
             source_module, source_record_id, total_matches_found,
             high_risk_matches, auto_cleared_matches, highest_score,
             screening_result, matches_json, status, processing_time_ms)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        name, entity_type, screening_type, user_id, source_module, source_record_id,
        total_matches, len(high_risk), len(auto_cleared), highest_score,
        screening_result,
        json.dumps({
            'matches': matches,
            'adverse_media': result.get('adverse_media', []),
            'adverse_media_summary': result.get('adverse_media_summary', {}),
        }),
        status, result.get('processing_time_ms', 0),
    ))
    history_id = history_cursor.fetchone()['id']

    results_id = None
    if write_results_table:
        results_cursor = db.execute("""
            INSERT INTO screening_results (
                screening_type, screened_name, screened_dob,
                screening_method, total_matches_found, highest_match_score,
                screening_result, matches, adverse_media, adverse_media_summary,
                processing_time_ms, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            results_screening_type or source_module.upper().replace(' ', '_'),
            name, dob, 'API',
            total_matches, highest_score, screening_result,
            json.dumps(matches),
            json.dumps(result.get('adverse_media', [])),
            json.dumps(result.get('adverse_media_summary', {})),
            result.get('processing_time_ms', 0), user_id,
        ))
        results_id = results_cursor.fetchone()['id']

    queue_ids = []
    for match in high_risk:
        priority = 'High' if match.get('match_score', 0) >= 90 else 'Medium'
        q_cursor = db.execute("""
            INSERT INTO screening_queue
                (screening_history_id, entity_name, entity_type, match_name,
                 match_score, list_source, match_details, priority, status,
                 source_module, source_record_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Pending', %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
        """, (
            history_id, name, entity_type,
            match.get('full_name', match.get('watchlist_name_ar', '')),
            match.get('match_score', 0),
            match.get('source', match.get('dataset', 'Unknown')),
            json.dumps(match),
            priority, source_module, source_record_id,
        ))
        queue_ids.append(q_cursor.fetchone()['id'])

    adverse_media_hits = result.get('adverse_media', [])
    if adverse_media_hits:
        am_summary = result.get('adverse_media_summary', {})
        am_score = am_summary.get('risk_score', 0)
        priority = 'High' if am_score >= 20 else 'Medium'
        am_cursor = db.execute("""
            INSERT INTO screening_queue
                (screening_history_id, entity_name, entity_type, match_name,
                 match_score, list_source, match_details, priority, status,
                 source_module, source_record_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Pending', %s, %s, CURRENT_TIMESTAMP)
            RETURNING id
        """, (
            history_id, name, entity_type, "Adverse Media Findings", am_score,
            "Adverse Media", json.dumps({'hits': adverse_media_hits}),
            priority, source_module, source_record_id,
        ))
        queue_ids.append(am_cursor.fetchone()['id'])

    if source_record_id:
        if source_module == 'Merchant KYC':
            ss = 'Pending Review' if high_risk else ('Whitelisted' if screening_result == 'WHITE_LISTED' else 'Clear')
            risk_rating = 'High' if high_risk else ('Low' if not matches else 'Medium')
            db.execute("""
                UPDATE merchants
                SET screening_status = %s, last_screening_date = CURRENT_TIMESTAMP,
                    last_screened_by = %s, risk_rating = %s, sanctions_checked = 1
                WHERE id = %s
            """, (ss, user_id, risk_rating, source_record_id))
        elif source_module == 'Customer KYC':
            ss = 'Pending Review' if high_risk else ('Whitelisted' if screening_result == 'WHITE_LISTED' else 'Clear')
            db.execute("""
                UPDATE customers
                SET screening_status = %s, last_screening_date = CURRENT_TIMESTAMP,
                    last_screened_by = %s
                WHERE id = %s
            """, (ss, user_id, source_record_id))

    db.commit()

    return {
        'history_id': history_id,
        'results_id': results_id,
        'queue_ids': queue_ids,
        'screening_result': screening_result,
        'status': status,
        'total_matches': total_matches,
        'high_risk_matches': len(high_risk),
        'auto_cleared_matches': len(auto_cleared),
        'highest_score': highest_score,
        'matches': matches,
        'adverse_media': result.get('adverse_media', []),
        'adverse_media_summary': result.get('adverse_media_summary', {}),
        'processing_time_ms': result.get('processing_time_ms', 0),
    }
