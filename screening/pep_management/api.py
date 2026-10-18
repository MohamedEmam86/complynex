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

from flask import Blueprint, jsonify, request
from flask_login import login_required
import psycopg2
from psycopg2.extras import DictCursor
import logging

from .scheduler import PEPScheduler
from utils.decorators import permission_required

logger = logging.getLogger(__name__)

pep_api = Blueprint('pep_api', __name__, url_prefix='/api/pep')

# Only the standalone scheduler process (scripts/run_pep_scheduler.py, run by
# complynex-pep-scheduler.service) calls init_pep_module() — the web app
# itself never does, since a scheduler thread per gunicorn worker would mean
# 4 duplicate schedulers firing the same external syncs simultaneously. So
# these routes must not depend on init_pep_module() having been called in
# this process — they read DB config directly, same as the rest of the app.
DB_CONFIG = None
SCHEDULER = None

def init_pep_module(db_config: dict, oc_api_key: str = None):
    """
    Called only from scripts/run_pep_scheduler.py to start the background
    sync loop as its own process — not called from the web app.
    """
    global DB_CONFIG, SCHEDULER
    DB_CONFIG = db_config
    SCHEDULER = PEPScheduler(db_config, oc_api_key=oc_api_key)

    # Start the background sync loop
    SCHEDULER.start_background_service()

def get_db():
    from config import Config
    return psycopg2.connect(**Config.POSTGRES_CONFIG)


@pep_api.route('/search', methods=['GET'])
@login_required
@permission_required('screening', level='view')
def search_pep():
    """
    Search PEPs (with transliteration). 
    Matches against canonical names, aliases natively via db indexes.
    %sq=Mostafa
    """
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify({'error': 'Search query must be at least 2 characters'}), 400
        
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                # Basic trigram search against master names
                cur.execute("""
                    SELECT id, canonical_name_en, canonical_name_ar, date_of_birth, nationality, is_active, pep_level, risk_level, confidence_score,
                           GREATEST(similarity(canonical_name_en, %s), similarity(canonical_name_ar, %s)) as score
                    FROM pep_master 
                    WHERE similarity(canonical_name_en, %s) > 0.3 OR similarity(canonical_name_ar, %s) > 0.3
                    ORDER BY score DESC LIMIT 20
                """, (query, query, query, query))
                
                results = [dict(row) for row in cur.fetchall()]
                
        return jsonify({'status': 'success', 'count': len(results), 'data': results})
        
    except Exception as e:
        logger.error(f"PEP search error: {e}")
        return jsonify({'error': 'Server error'}), 500


@pep_api.route('/<int:pep_id>', methods=['GET'])
@login_required
@permission_required('screening', level='view')
def get_pep_details(pep_id):
    """
    Get PEP details with full provenance
    """
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                # Get master record
                cur.execute("SELECT * FROM pep_master WHERE id = %s", (pep_id,))
                pep = cur.fetchone()
                
                if not pep:
                    return jsonify({'error': 'PEP not found'}), 404
                    
                pep_data = dict(pep)
                
                # Fetch positions
                cur.execute("SELECT * FROM pep_positions WHERE pep_id = %s ORDER BY start_date DESC NULLS LAST", (pep_id,))
                pep_data['positions'] = [dict(row) for row in cur.fetchall()]
                
                # Fetch sources (provenance)
                cur.execute("SELECT source_name, source_record_id, source_url, first_retrieved, last_updated FROM pep_sources WHERE pep_id = %s", (pep_id,))
                pep_data['provenance'] = [dict(row) for row in cur.fetchall()]
                
                # Fetch aliases
                cur.execute("SELECT alias_name, alias_language, source FROM pep_aliases WHERE pep_id = %s", (pep_id,))
                pep_data['aliases'] = [dict(row) for row in cur.fetchall()]
                
        return jsonify({'status': 'success', 'data': pep_data})
        
    except Exception as e:
        logger.error(f"PEP fetch error: {e}")
        return jsonify({'error': 'Server error'}), 500


@pep_api.route('/sync', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def trigger_manual_sync():
    """
    Trigger manual updates for specific or all sources.
    Payload: {"source": "opensanctions"} or {"source": "all"}
    """
    from config import Config
    data = request.json or {}
    source = data.get('source', 'all')

    # Built on demand rather than reusing the module-level SCHEDULER — that
    # one only exists in the separate complynex-pep-scheduler.service process
    # (see init_pep_module()'s docstring above). A fresh instance here is
    # fine: trigger_manual_refresh() below doesn't touch the `schedule`
    # library's job registry, just calls the sync methods directly.
    on_demand_scheduler = PEPScheduler(dict(Config.POSTGRES_CONFIG))

    # We trigger it via a thread to answer API immediately
    from threading import Thread
    thread = Thread(target=on_demand_scheduler.trigger_manual_refresh, args=(source,))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'status': 'success', 
        'message': f'Manual sync triggered for source: {source}'
    })


@pep_api.route('/logs', methods=['GET'])
@login_required
@permission_required('screening', level='view')
def get_update_logs():
    """
    View update history
    """
    limit = request.args.get('limit', 20)
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT * FROM pep_update_logs ORDER BY started_at DESC LIMIT %s", (limit,))
                logs = [dict(row) for row in cur.fetchall()]
                
        return jsonify({'status': 'success', 'data': logs})
        
    except Exception as e:
        logger.error(f"PEP log fetch error: {e}")
        return jsonify({'error': 'Server error'}), 500
