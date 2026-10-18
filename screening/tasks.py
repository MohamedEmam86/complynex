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

from screening.db_pool import db_pool
"""
Celery Task module for asynchronous background screening.
Replaces the synchronous, interface-blocking ThreadPool wait sequence.
"""
from celery import shared_task
import pandas as pd
import numpy as np
import os
import sqlite3
import json
from datetime import datetime
import logging
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

logger = logging.getLogger(__name__)

def update_task_progress(task_obj, current, total, metadata=None):
    """Safely update celery task progress state format."""
    state_meta = {'current': current, 'total': total, 'percent': int((current / total) * 100) if total > 0 else 0}
    if metadata:
        state_meta.update(metadata)
    task_obj.update_state(state='PROGRESS', meta=state_meta)


@shared_task(bind=True)
def run_batch_screening_task(self, dataframe_json, user_id=1):
    """
    Main background Celery task for processing a batch of names.
    Uses ProcessPoolExecutor internally for CPU parallelism, but runs
    the orchestration asynchronously so the web UI isn't blocked.
    """
    from screening.complynex_engine import ComplyNexScreeningEngine
    
    logger.info(f"Celery Batch Task Started -- user_id: {user_id}")
    
    try:
        # Reconstruct DataFrame
        df = pd.read_json(dataframe_json, orient='records')
        total_rows = len(df)
        
        # Determine CPU distribution (Reserve 1 core for OS/Redis/ES)
        max_workers = max(1, multiprocessing.cpu_count() - 1)
        
        update_task_progress(self, 0, total_rows, {'status': 'Initializing Process Pool'})
        
        results = []
        completed = 0
        
        # To avoid passing DB connections across processes, we only pass the raw dictionary data.
        # ProcessPool worker re-instantiates what it needs.
        records = df.to_dict('records')
        
        # Optimal chunk size to avoid memory bloat
        chunk_size = 500
        
        for i in range(0, total_rows, chunk_size):
            chunk = records[i:i + chunk_size]
            
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_screen_single_row_worker, row, user_id): row for row in chunk}
                
                for future in as_completed(futures): # type: ignore
                    try:
                        res = future.result()
                        results.append(res)
                        completed += 1
                        
                        if completed % 50 == 0 or completed == total_rows:
                            update_task_progress(self, completed, total_rows, 
                                                 {'status': f'Processing Batch ({completed}/{total_rows})'})
                    except Exception as e:
                        logger.error(f"Worker process failed: {e}")
                        
        logger.info("Celery Batch Task Completed successfully")
        
        return {
            'status': 'Completed',
            'total_processed': completed,
            'success_rate': round(len([r for r in results if r]) / max(total_rows, 1), 2),
            # Return JSON dumped results to avoid Celery serialization limits on large dicts
            'results_json': json.dumps(results) 
        }

    except Exception as e:
        logger.error(f"Batch Screening Task Error: {e}")
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise e


def _screen_single_row_worker(row, user_id):
    """
    CPU-bound worker function executed in isolated ProcessPool.
    Re-instantiates the screening engine per-process to ensure thread/DB safety.
    """
    # Import inside worker to ensure clean state
    from screening.complynex_engine import ComplyNexScreeningEngine
    from config import Config

    # Read active threshold
    active_thresh = 55
    conn = None
    try:
        conn = db_pool.checkout_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT config_value FROM screening_config WHERE config_key = 'screening_threshold'")
        res = cur.fetchone()
        if res:
            active_thresh = int(res['config_value'])
    except: pass
    finally:
        if conn:
            db_pool.return_connection(conn)

    # Init isolated engine. db_config must be a multi-key dict (matching
    # db_pool's own Postgres config), not a bare sqlite path string — a
    # single-key {'database': path} dict makes the engine misdetect
    # self.db_type as 'sqlite' even though db_pool always connects to
    # Postgres underneath, which silently disabled trigram fuzzy matching
    # (use_trigram = self.db_type == 'postgresql') for every row screened
    # through this worker.
    engine = ComplyNexScreeningEngine(db_config=dict(Config.POSTGRES_CONFIG))
    # Inject dynamically retrieved threshold
    engine.active_threshold = active_thresh
    
    name = row.get('Search Name', row.get('Merchant Name', row.get('Name', '')))
    
    if pd.isna(name) or not str(name).strip():
         return {
            'merchant_name': '',
            'screening_result': 'NO_NAME_PROVIDED',
            'matches': []
         }
         
    try:
         result = engine.screen_person(str(name), user_id=user_id, include_media=False)
         return {
             'merchant_name': str(name),
             'screening_result': result.get('screening_result', 'ERROR'),
             'matches': result.get('matches', []),
             'highest_score': result.get('highest_score', 0),
             'processing_time_ms': result.get('processing_time_ms', 0),
             'cache_hit': result.get('cache_hit', False)
         }
    except Exception as e:
        logger.error(f"Engine screen error on {name}: {e}")
        return {
            'merchant_name': str(name),
            'screening_result': 'ERROR',
            'error': str(e),
            'matches': []
        }
    finally:
        engine.close()
