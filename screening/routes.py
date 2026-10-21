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

from extensions import csrf, limiter
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app, send_file, Response
import requests
from flask_login import login_required, current_user
from utils.decorators import permission_required
import os
import sys
import json
import csv
import io
from datetime import datetime
import threading
import uuid
import time
import socket
import ipaddress
from urllib.parse import urlparse
import concurrent.futures
from screening.multi_source_screener import MultiSourceScreener
from screening.transaction_analyzer import TransactionAnalyzer
from screening.reporting_service import ReportingService
from database.db import get_db, query_db, execute_db
import logging

logger = logging.getLogger(__name__)

# App root, resolved dynamically instead of hardcoded, so subprocess calls
# and sys.path tricks below work regardless of where this deployment lives
# (was hardcoded to /opt/complynex, which was the Hostinger deployment path
# and silently broke several admin actions — sync-to-watchlist, scrape-all,
# adverse media subprocess — after the Contabo migration moved the app to
# /var/www/complynex without anyone touching this file).
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

screening_bp = Blueprint('screening', __name__, template_folder='templates')


def _is_safe_external_url(url):
    """Reject URLs that could be used for SSRF against internal infrastructure —
    only plain http(s) URLs that resolve to a public IP address are allowed.
    Used before the server itself makes an outbound request to an
    admin-configured screening data-source URL (validate/auto-scrape), so a
    source pointed at localhost/RFC1918/link-local/cloud-metadata addresses
    can't be used to probe or reach internal services."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Malformed URL"
    if parsed.scheme not in ('http', 'https'):
        return False, "Only http/https URLs are allowed"
    hostname = parsed.hostname
    if not hostname:
        return False, "URL has no hostname"
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, "Could not resolve hostname"
    for family, _type, _proto, _canon, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False, f"URL resolves to a non-public address ({ip}) — not allowed"
    return True, None

from config import get_config

# Lazy-load engine on first use to avoid OOM at startup
_env_config = get_config()
_db_config = {'database': getattr(_env_config, 'DATABASE', 'complynex.db')}
_engine_instance = None

def get_engine():
    """Lazy-load the screening engine on first use to save memory at startup."""
    global _engine_instance
    if _engine_instance is None:
        print("[STARTUP] Loading screening engine and ML model...")
        _engine_instance = MultiSourceScreener(db_config=_db_config, cache_config=None, ml_threshold=0.75)
        print("[STARTUP] Engine ready.")
    return _engine_instance


# DB-backed task status (works across multiple gunicorn workers)
TASK_STATUS = {}  # kept for legacy compatibility only

def _get_task_db_conn():
    import psycopg2
    from config import get_config
    cfg = get_config()
    return psycopg2.connect(**cfg.POSTGRES_CONFIG)

def update_task_status(task_id, status, message=None, progress=None, total=None, result=None):
    try:
        import json
        conn = _get_task_db_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO screening_tasks (task_id, status, message, progress, total, result, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (task_id) DO UPDATE SET
                status = EXCLUDED.status,
                message = COALESCE(EXCLUDED.message, screening_tasks.message),
                progress = COALESCE(EXCLUDED.progress, screening_tasks.progress),
                total = COALESCE(EXCLUDED.total, screening_tasks.total),
                result = COALESCE(EXCLUDED.result, screening_tasks.result),
                updated_at = NOW()
        """, (task_id, status, message, progress, total,
                json.dumps(result, default=str) if result else None))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        if task_id not in TASK_STATUS:
            TASK_STATUS[task_id] = {}
        TASK_STATUS[task_id].update({'status': status, 'message': message,
            'progress': progress, 'total': total, 'result': result})


def cleanup_old_tasks():
    # Remove tasks older than 1 hour
    now = time.time()
    to_remove = []
    for tid, info in TASK_STATUS.items():
        if now - info.get('created_at', 0) > 3600:
            to_remove.append(tid)
    for tid in to_remove:
        del TASK_STATUS[tid]

def run_async_import(task_id, file_path, source_key):
    try:
        cleanup_old_tasks()
        update_task_status(task_id, 'processing', 'Initializing import...', 0, 0)
        
        # Add scripts dir to path
        scripts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts')
        if scripts_dir not in sys.path:
            sys.path.append(scripts_dir)
            
        stats = {}
        result_msg = ""
        
        if source_key == 'internal_pep':
            from screening.internal_pep_service import InternalPEPService
            import csv, openpyxl

            update_task_status(task_id, 'processing', 'Reading PEP file...', 10, 100)
            service = InternalPEPService()
            rows = []
            if file_path.endswith('.csv'):
                with open(file_path, newline='', encoding='utf-8-sig') as f:
                    rows = list(csv.DictReader(f))
            else:
                wb = openpyxl.load_workbook(file_path, data_only=True)
                ws = wb.active
                headers = [str(c.value).strip().lower().replace(' ', '_') for c in next(ws.iter_rows(min_row=1, max_row=1))]
                for row in ws.iter_rows(min_row=2, values_only=True):
                    rows.append(dict(zip(headers, row)))

            added = skipped = 0
            update_task_status(task_id, 'processing', 'Importing PEP records...', 30, 100)
            for row in rows:
                name = str(row.get('full_name') or row.get('name') or '').strip()
                if not name or len(name) < 2:
                    skipped += 1
                    continue
                try:
                    service.add_entry({
                        'full_name': name,
                        'original_name': row.get('original_name') or row.get('arabic_name') or name,
                        'entity_type': row.get('entity_type', 'INDIVIDUAL'),
                        'national_id': row.get('national_id') or row.get('id_number'),
                        'nationality': row.get('nationality') or row.get('country'),
                        'reason': row.get('reason') or 'PEP - Bulk Import',
                        'risk_level': row.get('risk_level', 'HIGH'),
                        'category': row.get('category'),
                        'position': row.get('position'),
                        'notes': row.get('notes'),
                    }, user_id=1)
                    added += 1
                except Exception as e:
                    skipped += 1
            stats = {'added': added, 'skipped': skipped, 'source': 'internal_pep'}
            result_msg = f"Internal PEP Import complete: {added} added, {skipped} skipped"

            # Without this, InternalPEPService.add_entry() rows land in
            # internal_pep but never reach screening_watchlist — nothing
            # else copies them over, so they'd never be screenable.
            update_task_status(task_id, 'processing', 'Syncing to watchlist...', 80, 100)
            import subprocess
            sync_result = subprocess.run([
                sys.executable,
                os.path.join(BASE_DIR, 'scripts', 'sync_internal_to_watchlist.py')
            ], capture_output=True, text=True, timeout=120)
            if sync_result.returncode != 0:
                logger.error(f"sync_internal_to_watchlist failed: {sync_result.stderr[-500:]}")

        elif source_key == 'internal_blacklist':
            from screening.internal_upload_handler import handle_internal_upload
            
            update_task_status(task_id, 'processing', 'Reading blacklist file...', 10, 100)
            stats = handle_internal_upload(file_path, source_key)
            update_task_status(task_id, 'processing', 'Syncing to watchlist...', 80, 100)
            
            # Auto-sync to screening_watchlist
            import subprocess
            subprocess.run([
                sys.executable,
                os.path.join(BASE_DIR, 'scripts', 'sync_internal_to_watchlist.py')
            ], capture_output=True, timeout=120)

            result_msg = f"Custom Import complete: {stats.get('added', 0)} added, {stats.get('updated', 0)} updated"
            
        else:
            # Use Standard Sanctions Importer
            from import_sanctions_file import import_sanctions_file
            
            def progress_callback(stage, data):
                if stage == 'parsing':
                    update_task_status(task_id, 'processing', data.get('message', 'Parsing file...'))
                elif stage == 'starting_import':
                    update_task_status(task_id, 'processing', 'Starting validation...', 0, data.get('total', 0))
                elif stage == 'importing':
                    update_task_status(task_id, 'processing', f"Imported {data.get('processed')} of {data.get('total')}", 
                                      data.get('processed'), data.get('total'))

            # Run the import with callback
            stats = import_sanctions_file(file_path, source_key, progress_callback=progress_callback)
            result_msg = f"Import successful: {stats.get('added', 0)} added, {stats.get('updated', 0)} updated"
        

        # --- AUDIT LOGGING (INJECTED) ---
        try:
            # Removed web-only get_db
            from datetime import datetime
            db_conn = _get_task_db_conn()
            now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            
            # Identify if it was a file upload or an automated web scrape
            u_type = 'AUTO_SCRAPE' if 'source_url' in locals() else 'FILE_IMPORT'
            
            db_conn.cursor().execute('''
                INSERT INTO data_update_audit_log 
                (update_type, initiated_by, total_sources, records_added, records_updated, 
                 records_unchanged, errors_count, status, started_at, completed_at, duration_seconds, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                u_type, 1, 1, 
                stats.get('added', 0), stats.get('updated', 0), 0, 0, 
                'COMPLETED', now_str, now_str, 0, source_key
            ))
            if hasattr(db_conn, 'commit'):
                db_conn.commit()
        except Exception as e:
            current_app.logger.error(f"Audit log receipt error: {e}")
        # --- END AUDIT LOGGING ---

        trigger_es_incremental_sync()

        update_task_status(task_id, 'completed', result_msg, result={
            'success': True,
            'source': stats.get('source', source_key),
            'added': stats.get('added', 0),
            'updated': stats.get('updated', 0),
            'total': stats.get('total_processed', 0),
            'message': result_msg
        })
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"\n🚨 FATAL SCRAPER ERROR ({source_key}):\n{error_details}\n")
        logger.error(f"Scraper failed for {source_key}: {e}")
        traceback.print_exc()
        update_task_status(task_id, 'failed', str(e))
    finally:
        # Clean up temp file
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except: pass

def run_async_auto_scrape(task_id, source_name, source_url, source_key):
    import fcntl as _fcntl_guard
    _lock_fh_guard = open(f"/tmp/bpay_scrape_{source_key}.lock", "w")
    try:
        _fcntl_guard.flock(_lock_fh_guard, _fcntl_guard.LOCK_EX | _fcntl_guard.LOCK_NB)
    except OSError:
        _lock_fh_guard.close()
        logger.warning(f"Scrape already running for {source_key}, task {task_id} skipped")
        update_task_status(task_id, 'SKIPPED', f'Another scrape is already running for {source_key}')
        return
    """Background task to download and import a source file."""
    try:
        cleanup_old_tasks()

        safe, err = _is_safe_external_url(source_url)
        if not safe:
            logger.warning(f"Blocked SSRF-unsafe source_url for {source_key}: {err}")
            update_task_status(task_id, 'FAILED', f'Refusing to fetch source URL: {err}')
            return

        update_task_status(task_id, 'processing', f'Connecting to {source_name}...', 10, 100)

        # Download the file with increased timeout and realistic headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        
        max_retries = 3
        response = None
        last_error = None
        
        for attempt in range(max_retries):
            try:
                update_task_status(task_id, 'processing', f'Attempt {attempt+1} to connect to {source_name}...', 10 + attempt*5, 100)
                response = requests.get(source_url, stream=True, timeout=120, headers=headers)
                response.raise_for_status()
                break
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                raise e
        
        update_task_status(task_id, 'processing', f'Downloading data from {source_name}...', 30, 100)
        
        # Determine extension from content-type or URL
        content_type = response.headers.get('content-type', '').lower()
        ext = '.xml'
        if 'json' in content_type or source_url.lower().endswith('.json'): 
            ext = '.json'
        elif 'excel' in content_type or 'spreadsheet' in content_type or source_url.lower().endswith('.xlsx'): 
            ext = '.xlsx'
        
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        timestamp = __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = os.path.join(upload_dir, f"{source_key}_auto_{timestamp}{ext}")
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        update_task_status(task_id, 'processing', f'Saving file...', 50, 100)
        
        # Validate isn't HTML
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as check:
                first_line = check.readline(200).strip()
            if first_line.lower().startswith('<!doctype') or first_line.lower().startswith('<html'):
                os.remove(file_path)
                raise ValueError("Source URL returned an HTML page instead of data. Please verify the URL.")
        except UnicodeDecodeError:
            # If it's binary (like Excel), it's not HTML, so we proceed
            pass
            
        update_task_status(task_id, 'processing', f'Parsing and importing...', 70, 100)
        
        # Import using the file importer
        scripts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts')
        if scripts_dir not in sys.path: 
            sys.path.append(scripts_dir)
        
        from import_sanctions_file import import_sanctions_file
        
        def progress_callback(stage, data):
            if stage == 'importing':
                # Map 0-100% of import to 70-95% of task progress
                processed = data.get('processed', 0)
                total = data.get('total', 1)
                pct = 70 + (processed / total * 25)
                update_task_status(task_id, 'processing', f"Importing: {processed} records", int(pct), 100)
            elif stage == 'parsing':
                update_task_status(task_id, 'processing', data.get('message', 'Parsing...'), 60, 100)
        
        stats = import_sanctions_file(file_path, source_key, progress_callback=progress_callback)
        result_msg = f"Import complete: {stats.get('added', 0)} added, {stats.get('updated', 0)} updated"
        

        # --- AUDIT LOGGING (INJECTED) ---
        try:
            # Removed web-only get_db
            from datetime import datetime
            db_conn = _get_task_db_conn()
            now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            
            # Identify if it was a file upload or an automated web scrape
            u_type = 'AUTO_SCRAPE' if 'source_url' in locals() else 'FILE_IMPORT'
            
            db_conn.cursor().execute('''
                INSERT INTO data_update_audit_log 
                (update_type, initiated_by, total_sources, records_added, records_updated, 
                 records_unchanged, errors_count, status, started_at, completed_at, duration_seconds, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                u_type, 1, 1, 
                stats.get('added', 0), stats.get('updated', 0), 0, 0, 
                'COMPLETED', now_str, now_str, 0, source_key
            ))
            if hasattr(db_conn, 'commit'):
                db_conn.commit()
        except Exception as e:
            current_app.logger.error(f"Audit log receipt error: {e}")
        # --- END AUDIT LOGGING ---

        trigger_es_incremental_sync()

        update_task_status(task_id, 'completed', result_msg, result={
            'success': True,
            'added': stats.get('added', 0),
            'updated': stats.get('updated', 0),
            'total': stats.get('total_processed', 0),
            'message': result_msg
        })
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"\n🚨 FATAL SCRAPER ERROR ({source_key}):\n{error_details}\n")
        logger.error(f"Scraper failed for {source_key}: {e}")
        traceback.print_exc()
        update_task_status(task_id, 'failed', str(e))
    finally:
        # File cleanup is optional here as it's in uploads, but we could remove it 
        # if we want to save space. For now keep it for auditing.
        pass

def get_param_style():
    """Return SQL parameter style based on DB type."""
    return "%s" if current_app.config.get('DB_TYPE', 'sqlite') == 'postgresql' else "%s"

def trigger_es_incremental_sync():
    """
    Run after a successful Postgres sync so new/updated watchlist rows are
    actually searchable — previously nothing ever called this (no cron, no
    systemd timer, no in-app trigger existed), so synced rows could sit in
    Postgres indefinitely without reaching Elasticsearch. Runs as a
    subprocess (not an in-process import) so an ES/network hiccup here can
    never break the sync that already committed to Postgres; failures are
    logged, not swallowed.
    """
    try:
        import subprocess
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            [sys.executable, os.path.join(base_dir, 'scripts', 'es_incremental_sync.py')],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            logger.error(f"ES incremental sync failed (rc={result.returncode}): {result.stderr[-500:]}")
        else:
            logger.info("ES incremental sync completed after source update.")
    except Exception as e:
        logger.error(f"Could not trigger ES incremental sync: {e}")

def run_async_scrape(task_id, script_path, arg_source, no_limit=False):
    try:
        cleanup_old_tasks()
        update_task_status(task_id, 'processing', 'Starting scraper...', 0, 100)
        
        # Build arguments
        cmd = [sys.executable, '-u', script_path, '--source', arg_source]
        if no_limit:
            cmd.append('--no-limit')
        
        # Run script with unbuffered output
        import subprocess
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Monitor output
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                line = output.strip()
                if line.startswith('PROGRESS:'):
                    try:
                        p = int(line.split(':')[1].strip())
                        update_task_status(task_id, 'processing', progress=p)
                    except: pass
                elif line.startswith('STATUS:'):
                    msg = line.split(':', 1)[1].strip()
                    update_task_status(task_id, 'processing', message=msg)
                    
        rc = process.poll()
        if rc != 0:
            err = process.stderr.read()
            raise Exception(f"Script failed (exit {rc}): {err}")
            
        update_task_status(task_id, 'completed', 'Scraping completed successfully.', 100, 100, result={'success': True})
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"\n🚨 FATAL SCRAPER ERROR ({arg_source}):\n{error_details}\n")
        logger.error(f"Scraper failed for {arg_source}: {e}")
        traceback.print_exc()
        update_task_status(task_id, 'failed', str(e))

@screening_bp.route('/')
@login_required
def screening_index():
    return redirect(url_for('screening.dashboard'))
    return redirect(url_for('screening.dashboard'))

@screening_bp.route('/dashboard')
@login_required
@permission_required('screening')
def dashboard():
    # Statistics
    stats = query_db("""
        SELECT 
            COUNT(*) as total_screenings,
            SUM(CASE WHEN screening_result = 'CONFIRMED_HIT' THEN 1 ELSE 0 END) as confirmed_hits,
            SUM(CASE WHEN screening_result = 'POTENTIAL_MATCH' THEN 1 ELSE 0 END) as potential_matches,
            SUM(CASE WHEN screening_result = 'CLEAR' THEN 1 ELSE 0 END) as clear_results
        FROM screening_results
    """, one=True)
    
    # Recent screenings
    recent_screenings = query_db("SELECT * FROM screening_results ORDER BY created_at DESC LIMIT 10")
    
    # Watchlist stats
    # Was a COUNT over 2.77M rows on every page load (2.2s). Indexed and now
    # cached for an hour — the watchlist syncs monthly.
    from screening.cache import watchlist_stats as _wl_stats
    _wls = _wl_stats()
    watchlist_count_res = {'count': _wls['count']}
    watchlist_count = watchlist_count_res['count'] if watchlist_count_res else 0
    
    # MAX(last_updated) was a 5.5s scan; indexed and served from the same
    
    # cached payload as the count above.
    
    last_update_res = {'last': _wls['last_updated']}
    last_update = last_update_res['last'] if last_update_res else None

    # Per-source list freshness (2026-07-21, screening Rec #1/#4): surfaces
    # how old each sanctions source is, with staleness badges, so nobody has
    # to query the database to know whether screening data is current.
    source_freshness = []
    try:
        from datetime import datetime as _dt
        _now = _dt.now()
        _rows = query_db("""
            SELECT source_name, source_display_name, last_successful_update,
                   consecutive_failures, update_frequency_hours, total_records
            FROM screening_data_sources WHERE is_active = 1 ORDER BY source_name
        """) or []
        for _r in _rows:
            _raw = (_r['last_successful_update'] or '').strip() if _r['last_successful_update'] else ''
            _age_h = None
            if _raw:
                # PostgreSQL renders the offset as +02 — hours only. strptime's
                # %z accepts +0200 and +02:00 but NOT +02, so every one of these
                # parses failed, _age_h stayed None, and all nine sources showed
                # "never" with a red badge despite being updated two days ago.
                # fromisoformat handles it; strptime stays as a fallback.
                try:
                    _parsed = _dt.fromisoformat(_raw)
                    if _parsed.tzinfo is not None:
                        _parsed = _parsed.replace(tzinfo=None)
                    _age_h = (_now - _parsed).total_seconds() / 3600.0
                except (ValueError, TypeError):
                    _norm = _raw
                    # pad a bare 2-digit offset so %z can read it
                    if len(_norm) > 3 and _norm[-3] in '+-' and _norm[-2:].isdigit():
                        _norm = _norm + '00'
                    for _fmt in ('%Y-%m-%d %H:%M:%S.%f%z', '%Y-%m-%d %H:%M:%S%z',
                                 '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
                        try:
                            _parsed = _dt.strptime(_norm, _fmt)
                            if _parsed.tzinfo is not None:
                                _parsed = _parsed.replace(tzinfo=None)
                            _age_h = (_now - _parsed).total_seconds() / 3600.0
                            break
                        except ValueError:
                            continue
            if _age_h is None:
                _status, _badge = 'never', 'danger'
            elif _age_h <= 48:
                _status, _badge = 'fresh', 'success'
            elif _age_h <= 168:
                _status, _badge = 'stale', 'warning'
            else:
                _status, _badge = 'critical', 'danger'
            if _r['consecutive_failures'] and _r['consecutive_failures'] > 0:
                _badge = 'danger'
            source_freshness.append({
                'name': _r['source_display_name'] or _r['source_name'],
                'last': _raw[:16] if _raw else 'Never',
                'age_h': round(_age_h) if _age_h is not None else None,
                'status': _status, 'badge': _badge,
                'failures': _r['consecutive_failures'] or 0,
                'records': _r['total_records'] or 0,
            })
    except Exception as _e:
        logger.warning(f"source freshness panel failed: {_e}")

    return render_template('screening/dashboard.html',
                          stats=stats,
                          recent_screenings=recent_screenings,
                          watchlist_count=watchlist_count,
                          last_update=last_update,
                          source_freshness=source_freshness,
                          open_alerts=(query_db("SELECT COUNT(*) AS c FROM aml_alerts WHERE alert_status='OPEN'", one=True) or {'c': 0})['c'])

@screening_bp.route('/screen', methods=['GET', 'POST'])
@limiter.limit('60 per minute')
@login_required
@permission_required('screening', level='view')
def manual_screen():
    if request.method == 'POST':
        name = request.form.get('name')
        dob = request.form.get('dob')
        country = request.form.get('country')
        gender = request.form.get('gender')
        entity_type = request.form.get('entity_type', 'INDIVIDUAL')
        national_id = request.form.get('national_id')
        employer = request.form.get('employer')
        
        if not name:
            flash('Name is required', 'error')
            return redirect(url_for('screening.manual_screen'))
            
        # Parse Threshold
        try:
            slider_val = int(request.form.get('threshold', 55))
        except ValueError:
            slider_val = 55
            
        # Parse DOB
        formatted_dob = None
        if dob:
            try:
                formatted_dob = datetime.strptime(dob, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        engine = get_engine()
        engine.active_threshold = slider_val
        
        # Also persist the slider val to DB as the last used generic threshold
        try:
            param = get_param_style()
            execute_db(f"UPDATE screening_config SET config_value = {param}, updated_at = CURRENT_TIMESTAMP WHERE config_key = 'screening_threshold'", (str(slider_val),))
        except Exception:
            pass
            
        result = engine.screen_person(
            name=name,
            date_of_birth=formatted_dob,
            nationality=country,
            entity_type=entity_type,
            national_id=national_id,
            employer=employer
        )
        # engine.close()  # REMOVED: singleton must not be closed per-request
        pass
        
        # Save result
        # HARDENED + UNIFIED (2026-07-20, Task #69): route through
        # _save_screening_result() instead of a standalone screening_results
        # -only INSERT. See module-level note above for why: this is what
        # makes a manual screening actually show up in the real History page
        # (/screening/history-full reads screening_history, not
        # screening_results) and what generates a compliance queue entry for
        # high-risk manual matches. Retried once and logged loudly on
        # failure - never silently drop a completed screening decision.
        import time
        t_db = time.time()

        write_ok = False
        history_id = None
        for attempt in (1, 2):
            try:
                history_id = _save_screening_result(
                    name=name,
                    entity_type=entity_type,
                    dob=dob,
                    nationality=country,
                    source_module='Manual Ad-Hoc',
                    source_record_id=None,
                    result=result,
                    user_id=current_user.id,
                    screening_type='MANUAL'
                )
                write_ok = True
                break
            except Exception as e:
                logger.error(
                    f"[SCREENING WRITE FAILURE] attempt {attempt}/2 for name={name!r} "
                    f"user_id={current_user.id}: {e}", exc_info=True
                )
                if attempt == 1:
                    time.sleep(0.3)

        if not write_ok:
            logger.error(
                f"[SCREENING WRITE FAILURE] GIVING UP after 2 attempts for name={name!r} "
                f"user_id={current_user.id}. Screening result was computed "
                f"(screening_result={result.get('screening_result')}, "
                f"total_matches={result.get('total_matches')}) but NOT persisted."
            )
            flash(
                'Your screening completed but could not be saved due to a temporary '
                'database issue. Please try again - if this keeps happening, contact support.',
                'error'
            )
            return redirect(url_for('screening.manual_screen'))

        # Fetches latest screening_results id (view_result() keys off this
        # table's id, not screening_history's - they are independent
        # sequences) for the redirect below.
        if current_app.config.get('DB_TYPE') == 'postgresql':
            latest = query_db("SELECT id FROM screening_results WHERE created_by = %s ORDER BY created_at DESC LIMIT 1", (current_user.id,), one=True)
        else:
            latest = query_db("SELECT id FROM screening_results ORDER BY id DESC LIMIT 1", one=True)

        if not latest:
            logger.error(
                f"[SCREENING WRITE FAILURE] _save_screening_result() reported success "
                f"(history_id={history_id}) but no screening_results row found on "
                f"readback for name={name!r} user_id={current_user.id}"
            )
            flash('Your screening was saved but could not be located. Please check History.', 'error')
            return redirect(url_for('screening.screening_history_full'))

        logger.info(f"[TIMER] DB write: {round((time.time()-t_db)*1000)}ms (history_id={history_id})")

        return redirect(url_for('screening.view_result', id=latest['id']))

    # Fetch current threshold for UI slider
    try:
        threshold_res = query_db("SELECT config_value FROM screening_config WHERE config_key = 'screening_threshold'", one=True)
        current_threshold = int(threshold_res['config_value']) if threshold_res else 55
    except Exception:
        current_threshold = 55
        
    return render_template('screening/manual_screen.html', current_threshold=current_threshold)

@screening_bp.route('/result/<int:id>')
@login_required
@permission_required('screening')
def view_result(id):
    param = get_param_style()
    # Resolve the two accountability roles to real people: who ran the
    # screening (created_by) and who adjudicated it (resolved_by). Both were
    # already stored but never surfaced anywhere in the UI.
    result = query_db(f"""
        SELECT r.*,
               TRIM(COALESCE(cu.first_name,'') || ' ' || COALESCE(cu.last_name,'')) AS screened_by_name,
               cu.email AS screened_by_email,
               TRIM(COALESCE(rv.first_name,'') || ' ' || COALESCE(rv.last_name,'')) AS resolved_by_name,
               rv.email AS resolved_by_email
          FROM screening_results r
          LEFT JOIN users cu ON r.created_by = cu.id
          LEFT JOIN users rv ON r.resolved_by = rv.id
         WHERE r.id = {param}
    """, (id,), one=True)
    
    if not result:
        flash('Screening result not found', 'error')
        return redirect(url_for('screening.dashboard'))
        
    matches = json.loads(result['matches']) if isinstance(result['matches'], str) else result['matches']
    
    # Ensure matches are always strictly sorted by match_score descending
    if matches:
        matches = sorted(matches, key=lambda x: x.get('match_score', 0) if isinstance(x, dict) else 0, reverse=True)
        # Safely parse nested json strings for properties and details
        for m in matches:
            if isinstance(m, dict):
                for field in ['properties', 'details']:
                    val = m.get(field)
                    if isinstance(val, str):
                        try:
                            m[field] = json.loads(val)
                        except json.JSONDecodeError:
                            m[field] = {}
    
    # Classify matches here, not in the template. A PEP requires enhanced due
    # diligence; a sanctions hit requires blocking. Presenting one as the other
    # misstates the obligation, so this must be testable code, not substring
    # tests inside Jinja.
    from screening.match_classifier import split_matches
    sanction_matches, pep_matches, other_matches = split_matches(matches)

    # Parse adverse_media in Python instead of template
    adverse_hits = []
    if result['adverse_media']:
        if isinstance(result['adverse_media'], str):
            try:
                adverse_hits = json.loads(result['adverse_media'])
            except json.JSONDecodeError:
                adverse_hits = []
        else:
            adverse_hits = result['adverse_media']
            
    # Explicitly sort adverse hits by risk score (if available) or date
    if adverse_hits:
        adverse_hits = sorted(
            adverse_hits, 
            key=lambda x: (x.get('risk_score', 0), x.get('published', '') or ''), 
            reverse=True
        )
            
    adverse_media_count = len(adverse_hits)
    
    # Degraded-search warning (2026-07-21, Rec #2): if this screening ran
    # while Elasticsearch was failing, recall used the weaker trigram-only
    # fallback. Say so explicitly so the analyst knows to re-screen.
    try:
        if ('search_degraded' in result.keys()) and result['search_degraded']:
            flash('Warning: this screening ran in DEGRADED search mode (primary search engine was unavailable). Recall quality was reduced - re-screen this name to be safe.', 'warning')
    except Exception:
        pass

    if result:
        from models.audit import AuditLog
        from flask import request
        from flask_login import current_user
        AuditLog.log(current_user.id, 'Screening', 'Screening', None,
            f"Screened: {result.get('entity_name', 'Unknown')} — Result: {result.get('screening_result','UNKNOWN')}", request.remote_addr)
    return render_template('screening/screening_result.html', result=result, matches=matches,
                           adverse_hits=adverse_hits, adverse_media_count=adverse_media_count,
                           sanction_matches=sanction_matches, pep_matches=pep_matches,
                           other_matches=other_matches)

@screening_bp.route('/history')
@login_required
@permission_required('screening', level='view')
def history():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    param = get_param_style()
    if current_app.config.get('DB_TYPE') == 'postgresql':
        screenings = query_db("SELECT * FROM screening_results ORDER BY created_at DESC LIMIT %s OFFSET %s", (per_page, offset))
    else:
        screenings = query_db("SELECT * FROM screening_results ORDER BY created_at DESC LIMIT %s OFFSET %s", (per_page, offset))
    
    return render_template('screening/history.html', screenings=screenings, page=page)

@screening_bp.route('/config', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='view')
def config():
    if not current_user.is_admin() and not current_user.can_edit('screening'):
         flash('Access denied. Edit permission required for screening config.', 'error')
         return redirect(url_for('screening.dashboard'))
         
    param = get_param_style()
    if request.method == 'POST':
        try:
            # Tier-threshold sanity validation (2026-07-21, Rec #6): the
            # decision chain tests confirmed >= potential >= low in that
            # order, so inverted values silently make a tier unreachable
            # (which is exactly what had happened in production: low=70 >
            # potential=60 meant LOW_MATCH could never occur). Reject any
            # save that would produce an inverted ladder.
            def _effective(k):
                v = request.form.get(k)
                if v is None:
                    row = query_db(f"SELECT config_value FROM screening_config WHERE config_key = {param}", (k,), one=True)
                    v = row['config_value'] if row else None
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            _conf = _effective('confirmed_hit_threshold')
            _pot = _effective('potential_match_threshold')
            _low = _effective('low_match_threshold')
            if _conf is not None and _pot is not None and _low is not None:
                if not (_low < _pot < _conf):
                    flash(f'Invalid thresholds: they must satisfy low ({_low:g}) < potential ({_pot:g}) < confirmed ({_conf:g}). Nothing was saved.', 'error')
                    return redirect(url_for('screening.config'))
            for key in request.form:
                val = request.form.get(key)
                execute_db(f"UPDATE screening_config SET config_value = {param}, updated_at = CURRENT_TIMESTAMP WHERE config_key = {param}", (val, key))
            flash('Configuration updated and saved to database', 'success')
            return redirect(url_for('screening.config'))
        except Exception as e:
            flash(f'Update failed: {str(e)}', 'error')
            
    settings = query_db("SELECT * FROM screening_config ORDER BY category, config_key")
    return render_template('screening/config_edit.html', settings=settings)

@screening_bp.route('/sources', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='view')
def data_sources():
    if not current_user.is_admin() and not current_user.is_compliance_officer():
         flash('Access denied', 'error')
         return redirect(url_for('screening.dashboard'))
         
    param = get_param_style()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name')
            url = request.form.get('url')
            stype = request.form.get('type', 'FTJSON')
            slug = request.form.get('id')
            display_name = request.form.get('name') 
            
            execute_db(f"INSERT INTO screening_data_sources (source_name, source_display_name, source_type, source_url, is_active) VALUES ({param}, {param}, {param}, {param}, TRUE)", 
                      (slug, display_name, stype, url))
        elif action == 'toggle':
            sid = request.form.get('sid')
            execute_db(f"UPDATE screening_data_sources SET is_active = NOT is_active WHERE id = {param}", (sid,))
        elif action == 'delete':
            sid = request.form.get('sid')
            execute_db(f"DELETE FROM screening_data_sources WHERE id = {param}", (sid,))
        
        return redirect(url_for('screening.data_sources'))
        
    sources = query_db("SELECT * FROM screening_data_sources ORDER BY priority, is_official DESC, source_name")
    
    # Get recent audit log entries
    try:
        recent_audits = query_db("""
            SELECT dal.*, u.email as initiated_by_user
            FROM data_update_audit_log dal
            LEFT JOIN users u ON dal.initiated_by = u.id
            ORDER BY dal.started_at DESC
            LIMIT 10
        """)
    except Exception:
        recent_audits = []
    
    # Get watchlist count
    try:
        wl_count = query_db("SELECT COUNT(*) as cnt FROM screening_watchlist", one=True)
        watchlist_count = wl_count['cnt'] if wl_count else 0
    except Exception:
        watchlist_count = 0
    
    return render_template('screening/sources.html', 
                         data_sources=sources,
                         recent_audits=recent_audits,
                         watchlist_count=watchlist_count)

@screening_bp.route('/whitelist', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='view')
def manage_whitelist():
    if not current_user.is_admin() and not current_user.is_compliance_officer():
         flash('Access denied', 'error')
         return redirect(url_for('screening.dashboard'))
         
    param = get_param_style()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name')
            reason = request.form.get('reason')
            # Use engine's normalization for consistency
            from .complynex_engine import normalize_arabic_text, ComplyNexScreeningEngine
            is_ar = ComplyNexScreeningEngine._is_arabic(None, name)
            # Rough normalization for the whitelist key
            norm_name = normalize_arabic_text(name) if is_ar else name.upper().strip()

            # ON CONFLICT added 2026-07-24: idx_screening_whitelist_norm is a
            # UNIQUE index on normalized_name. This was a plain INSERT with no
            # conflict handling, so adding a second customer whose name
            # normalizes to one already on the list (a repeat submission, a
            # name variant, or simply approving the same customer twice while
            # bulk-clearing a backlog) crashed with an unhandled
            # UniqueViolation -> 500 page, silently blocking every add after
            # the first duplicate. This is the root cause reported as
            # "can't add all approved customers to the whitelist."
            execute_db(f"""
                INSERT INTO screening_whitelist
                    (name, normalized_name, reason, added_by, added_at, status, approved_by, approval_date)
                VALUES ({param}, {param}, {param}, {param}, {param}, 'Active', {param}, {param})
                ON CONFLICT (normalized_name) WHERE normalized_name IS NOT NULL
                DO UPDATE SET reason = EXCLUDED.reason, added_at = EXCLUDED.added_at
            """,
                       (name, norm_name, reason, current_user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            flash(f'Name "{name}" added to whitelist.', 'success')
        elif action == 'delete':
            wid = request.form.get('wid')
            execute_db(f"DELETE FROM screening_whitelist WHERE id = {param}", (wid,))
            flash('Whitelist entry removed.', 'info')
            
        return redirect(url_for('screening.manage_whitelist'))
        
    # Quarantined entries first — they are the ones needing a decision — then
    # revoked, then active, newest first within each group.
    #
    # ?filter= lets the ongoing-screening dashboard link straight to a subset,
    # so a count on a card is reachable rather than something to go hunting for.
    filt = request.args.get('filter', '')
    where, params = '', ()
    if filt == 'review':
        where = "WHERE status = 'Requires Review'"
    elif filt == 'legacy':
        where = "WHERE scope = 'name' AND status = 'Active'"
    elif filt == 'monitored':
        where = "WHERE scope = 'match_set'"
    elif filt == 'due':
        where = ("WHERE scope = 'match_set' AND status = 'Active' "
                 "AND next_screening_at <= NOW()")
    elif filt == 'revoked':
        where = "WHERE status = 'Revoked'"

    # added_by / approved_by are user ids. Rendering the raw number tells nobody
    # anything — the whole point of an audit trail is that a person is named.
    whitelist = query_db(f"""
        SELECT w.*,
               TRIM(COALESCE(a.first_name,'') || ' ' || COALESCE(a.last_name,'')) AS added_by_name,
               a.email  AS added_by_email,
               TRIM(COALESCE(s.first_name,'') || ' ' || COALESCE(s.last_name,'')) AS screened_by_name,
               s.email  AS screened_by_email,
               (SELECT count(*) FROM screening_whitelist_audit x WHERE x.whitelist_id = w.id) AS history_count,
               (SELECT count(*) FROM ongoing_screening_findings f
                 WHERE f.whitelist_id = w.id AND f.status = 'open')                AS open_findings
        FROM screening_whitelist w
        LEFT JOIN users a ON a.id = w.added_by
        LEFT JOIN users s ON s.id = w.approved_by
        {where.replace('WHERE ', 'WHERE ').replace('status', 'w.status').replace('scope', 'w.scope').replace('next_screening_at', 'w.next_screening_at')}
        ORDER BY CASE w.status WHEN 'Requires Review' THEN 0 WHEN 'Revoked' THEN 1 ELSE 2 END,
                 w.added_at DESC""", params)
    needs_review = sum(1 for w in whitelist if (w['status'] or '') == 'Requires Review')
    # The page is reachable by compliance officers who may only hold 'view' on
    # screening. Showing them buttons that the route will reject is how "the
    # revoke doesn't work" reports get created.
    return render_template('screening/whitelist.html',
                           whitelist=whitelist,
                           needs_review=needs_review,
                           active_filter=filt,
                           filter_labels={
                               'review':    'Needs review — quarantined, not suppressing',
                               'legacy':    'Legacy entries — cleared before match sets were recorded',
                               'monitored': 'Monitored — cleared against a match set',
                               'due':       'Due for re-screening now',
                               'revoked':   'Revoked',
                           },
                           can_edit_wl=current_user.can_edit('screening'))


@screening_bp.route('/whitelist/bulk_upload', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='edit')
def bulk_upload_whitelist():
    """
    Bulk-add approved customers to the screening whitelist from a CSV/Excel
    file. Added 2026-07-24: the whitelist page only had a one-name-at-a-time
    'Add Entry' modal, so onboarding a batch of already-approved customers
    meant opening the modal dozens of times — and any name that normalized to
    one already on the list would 500 the single-add path (see the ON
    CONFLICT fix in manage_whitelist above). This mirrors the existing
    blacklist bulk-upload pattern (blacklist/routes.py's bulk_upload) for
    consistency, but never fails the whole batch on one bad/duplicate row —
    each row is inserted independently and failures are reported per-row.
    """
    if not current_user.is_admin() and not current_user.is_compliance_officer():
        flash('Access denied', 'error')
        return redirect(url_for('screening.dashboard'))

    if request.method == 'POST':
        if 'file' not in request.files or request.files['file'].filename == '':
            flash('No file selected.', 'danger')
            return redirect(request.url)

        file = request.files['file']
        filename = file.filename.lower()
        if not (filename.endswith('.csv') or filename.endswith('.xlsx')):
            flash('Invalid file format. Please upload a CSV or Excel (.xlsx) file.', 'danger')
            return redirect(request.url)

        try:
            rows = _parse_whitelist_csv(file) if filename.endswith('.csv') else _parse_whitelist_excel(file)
        except Exception as e:
            flash(f'Could not read file: {e}', 'danger')
            return redirect(request.url)

        from .complynex_engine import normalize_arabic_text, ComplyNexScreeningEngine
        param = get_param_style()
        total = len(rows)
        successful = 0
        errors = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for idx, row in enumerate(rows, start=2):  # data starts at row 2 (row 1 is the header)
            name = (row.get('name') or '').strip()
            reason = (row.get('reason') or '').strip()
            if not name or not reason:
                errors.append({'row': idx, 'name': name or '(blank)', 'error': 'name and reason are both required'})
                continue
            try:
                is_ar = ComplyNexScreeningEngine._is_arabic(None, name)
                norm_name = normalize_arabic_text(name) if is_ar else name.upper().strip()
                execute_db(f"""
                    INSERT INTO screening_whitelist
                        (name, normalized_name, reason, added_by, added_at, status,
                         approved_by, approval_date, entity_type, national_id,
                         commercial_registry, date_of_birth, nationality)
                    VALUES ({param}, {param}, {param}, {param}, {param}, 'Active',
                            {param}, {param}, {param}, {param}, {param}, {param}, {param})
                    ON CONFLICT (normalized_name) WHERE normalized_name IS NOT NULL
                    DO UPDATE SET reason = EXCLUDED.reason, added_at = EXCLUDED.added_at
                """, (
                    name, norm_name, reason, current_user.id, now_str,
                    current_user.id, now_str,
                    (row.get('entity_type') or 'Individual').strip(),
                    (row.get('national_id') or '').strip() or None,
                    (row.get('commercial_registry') or '').strip() or None,
                    (row.get('date_of_birth') or '').strip() or None,
                    (row.get('nationality') or '').strip() or None,
                ))
                successful += 1
            except Exception as e:
                errors.append({'row': idx, 'name': name, 'error': str(e)})

        if errors:
            flash(f'Import completed: {successful}/{total} added. {len(errors)} row(s) failed — see details below.', 'warning')
        else:
            flash(f'Import completed: {successful}/{total} customers added to the whitelist.', 'success')

        return render_template('screening/whitelist_bulk_upload.html',
                                import_errors=errors, import_total=total, import_successful=successful)

    return render_template('screening/whitelist_bulk_upload.html')


@screening_bp.route('/whitelist/bulk_upload/template')
@login_required
@permission_required('screening', level='view')
def download_whitelist_template():
    """Download a blank CSV template for the whitelist bulk-upload form."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['name', 'reason', 'entity_type', 'national_id', 'commercial_registry', 'date_of_birth', 'nationality'])
    writer.writerow(['Ahmed Mohamed Ali', 'Approved customer - KYC completed, false positive on a common name', 'Individual', '29001011234567', '', '1990-01-01', 'Egyptian'])
    writer.writerow(['ABC Trading LLC', 'Approved merchant - onboarding completed 2026', 'Legal Entity', '', '12345', '', ''])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-disposition": "attachment; filename=whitelist_bulk_upload_template.csv"}
    )


def _normalize_wl_header(h):
    return str(h).strip().lower().replace(' ', '_').replace('-', '_')


def _parse_whitelist_csv(file):
    """Parse an uploaded whitelist CSV into a list of row dicts keyed by normalized header."""
    content = file.stream.read().decode('utf-8-sig')  # utf-8-sig handles a BOM from Excel-saved CSVs
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for row in reader:
        clean = {}
        for k, v in row.items():
            if not k:
                continue
            clean[_normalize_wl_header(k)] = v.strip() if isinstance(v, str) else v
        if clean.get('name'):
            rows.append(clean)
    return rows


def _parse_whitelist_excel(file):
    """Parse an uploaded whitelist .xlsx into a list of row dicts keyed by normalized header."""
    import openpyxl
    workbook = openpyxl.load_workbook(file, data_only=True)
    sheet = workbook.active
    header = []
    for cell in sheet[1]:
        header.append(_normalize_wl_header(cell.value) if cell.value else None)
    rows = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not any(v is not None and str(v).strip() != '' for v in row):
            continue
        clean = {}
        for idx, value in enumerate(row):
            if idx < len(header) and header[idx]:
                clean[header[idx]] = str(value).strip() if value is not None else None
        if clean.get('name'):
            rows.append(clean)
    return rows


@screening_bp.route('/resolve_hit', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def resolve_hit():
    if not current_user.is_admin() and not current_user.is_compliance_officer():
         return jsonify({'success': False, 'error': 'Access denied'}), 403
         
    result_id = request.form.get('result_id')
    status = request.form.get('status') # TRUE_HIT, FALSE_POSITIVE
    notes = request.form.get('notes')
    whitelist_too = request.form.get('whitelist') == 'true'
    
    param = get_param_style()
    execute_db(f"""
        UPDATE screening_results 
        SET status = {param}, resolution_notes = {param}, resolved_by = {param}, resolved_at = CURRENT_TIMESTAMP
        WHERE id = {param}
    """, (status, notes, current_user.id, result_id))
    
    if status == 'TRUE_HIT':
        # Confirming a true match here must have the same effect as confirming
        # it from the review queue: the entity is added to the internal
        # blacklist so it is blocked on any future screening. Previously this
        # path only changed a status, so the two routes disagreed.
        res = query_db(
            f"SELECT screened_name, screening_type, highest_match_score "
            f"FROM screening_results WHERE id = {param}", (result_id,), one=True)
        if res:
            try:
                execute_db(f"""
                    INSERT INTO internal_blacklist
                        (full_name, entity_type, reason, risk_level, category,
                         source, added_by, added_date, is_active, confirmation_type)
                    VALUES ({param}, 'Individual', {param}, 'HIGH', 'Sanctions Match',
                            'Screening Adjudication', {param}, CURRENT_TIMESTAMP, 1,
                            'TEAM_CONFIRMED')
                """, (
                    res['screened_name'],
                    f"True match confirmed on screening result #{result_id} "
                    f"(score: {res['highest_match_score']}): {notes}",
                    current_user.id,
                ))
            except Exception as e:
                logger.error(f"Blacklist insert on adjudication failed: {e}")

    if status == 'FALSE_POSITIVE':
        # Always add to whitelist on false positive resolution
        res = query_db(f"SELECT screened_name FROM screening_results WHERE id = {param}", (result_id,), one=True)
        if res:
            name = res['screened_name']
            from .complynex_engine import normalize_arabic_text, ComplyNexScreeningEngine
            import datetime
            is_ar = ComplyNexScreeningEngine._is_arabic(None, name)
            norm_name = normalize_arabic_text(name) if is_ar else name.upper().strip()
            try:
                execute_db(
                    f"INSERT INTO screening_whitelist (name, normalized_name, reason, added_by, added_at, status) VALUES ({param}, {param}, {param}, {param}, {param}, 'Active') ON CONFLICT (normalized_name) WHERE normalized_name IS NOT NULL DO UPDATE SET reason = EXCLUDED.reason, added_at = EXCLUDED.added_at",
                    (name, norm_name, f"Whitelisted via screening resolution: {notes}", current_user.id, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                )
            except Exception as e:
                logger.error(f"Whitelist insert failed: {e}")
    
    # Mirror the decision onto the history row so Screening History and any
    # report built from it show the verdict and the reviewer, not just the
    # result page.
    try:
        execute_db(f"""
            UPDATE screening_history
               SET status = {param},
                   resolved_by = {param},
                   resolution_date = CURRENT_TIMESTAMP,
                   notes = {param}
             WHERE screening_result_id = {param}
        """, (status, current_user.id, notes, result_id))
    except Exception as e:
        logger.error(f"Could not mirror adjudication onto history: {e}")

    flash('Result resolved successfully.', 'success')
    return redirect(url_for('screening.view_result', id=result_id))

@screening_bp.route('/api/screen/person', methods=['POST'])
@limiter.limit('30 per minute')
@login_required
@permission_required('screening', level='edit')
def api_screen_person():
    data = request.json
    name = data.get('name')
    dob = data.get('date_of_birth')
    country = data.get('country')
    gender = data.get('gender')
    
    if not name:
        return jsonify({'error': 'Name is required'}), 400
        
    # Parse DOB
    formatted_dob = None
    if dob:
        try:
            formatted_dob = datetime.strptime(dob, '%Y-%m-%d').date()
        except ValueError:
             pass

    engine = get_engine()
    result = engine.screen_person(
        name=name,
        date_of_birth=formatted_dob,
        nationality=country,
        entity_type=data.get('entity_type', 'INDIVIDUAL'),
        user_id=current_user.id
    )
    # engine.close()  # REMOVED: singleton must not be closed per-request
    pass
    
    # Save log
    # HARDENED + UNIFIED (2026-07-20, Task #69) - see matching comment in
    # manual_screen() for why: route through _save_screening_result() so
    # this also lands in screening_history (what the real History page
    # reads) and generates a queue entry for high-risk matches. Retried
    # once; never claim success to the caller if not actually persisted.
    write_ok = False
    history_id = None
    for attempt in (1, 2):
        try:
            history_id = _save_screening_result(
                name=name,
                entity_type=data.get('entity_type', 'INDIVIDUAL'),
                dob=dob,
                nationality=country,
                source_module='API',
                source_record_id=None,
                result=result,
                user_id=current_user.id,
                screening_type='API'
            )
            write_ok = True
            break
        except Exception as e:
            logger.error(
                f"[SCREENING WRITE FAILURE] (API) attempt {attempt}/2 for name={name!r} "
                f"user_id={current_user.id}: {e}", exc_info=True
            )
            if attempt == 1:
                import time as _t
                _t.sleep(0.3)

    if not write_ok:
        logger.error(
            f"[SCREENING WRITE FAILURE] (API) GIVING UP after 2 attempts for "
            f"name={name!r} user_id={current_user.id}. Screening result was computed "
            f"(screening_result={result.get('screening_result')}, "
            f"total_matches={result.get('total_matches')}) but NOT persisted."
        )
        result['success'] = False
        result['warning'] = 'Screening completed but could not be saved to History due to a database issue.'
        return jsonify(result), 207  # Multi-Status: computed OK, persistence failed

    result['success'] = True
    result['history_id'] = history_id
    return jsonify(result)

@screening_bp.route('/api/adverse_media/<int:result_id>', methods=['GET'])
@login_required
@permission_required('screening', level='view')
def api_adverse_media(result_id):
    param = get_param_style()
    result = query_db(f"SELECT screened_name, adverse_media, adverse_media_summary FROM screening_results WHERE id = {param}", (result_id,), one=True)
    if not result:
        return jsonify({'error': 'Result not found'}), 404
        
    name = result['screened_name']
    
    # Check if already completed
    existing_summary = None
    if result['adverse_media_summary']:
        try:
            existing_summary = json.loads(result['adverse_media_summary']) if isinstance(result['adverse_media_summary'], str) else result['adverse_media_summary']
        except: pass
        
    # ERROR must be retryable: a transient scraper failure would otherwise
    # be cached forever and replayed as a final verdict on every view.
    if existing_summary and existing_summary.get('risk_level') not in ['PENDING', 'TIMEOUT', 'ERROR']:
        # Already processed - but don't trust a cache entry whose hits blob
        # fails to parse; treat it as not-yet-processed instead of silently
        # reporting a false "completed, 0 hits" (see Task #71).
        try:
            hits = json.loads(result['adverse_media']) if isinstance(result['adverse_media'], str) else result['adverse_media']
            return jsonify({'status': 'completed', 'summary': existing_summary, 'hits': hits})
        except Exception as e:
            logger.error(
                f"[ADVERSE MEDIA] Corrupted cached hits JSON for result_id={result_id} "
                f"(name={name!r}): {e}. Falling through to re-scrape instead of "
                f"reporting a false 'completed, 0 hits'.", exc_info=True
            )
            # fall through to the re-scrape path below

    # Execute Scraper in isolated SUBPROCESS to avoid gevent monkey-patch conflicts
    import subprocess, sys, json as _json
    
    try:
        script = f"""
import sys
sys.path.insert(0, {BASE_DIR!r})
import os
os.environ['DB_TYPE'] = 'postgresql'
from screening.adverse_media_config import ADVERSE_MEDIA_CONFIG
from screening.waterfall_scraper import WaterfallAdverseMediaScraper
import json
scraper = WaterfallAdverseMediaScraper(config=ADVERSE_MEDIA_CONFIG)
result = scraper.screen_person({repr(name)}, save_to_db=False)
print(json.dumps(result))
"""
        proc = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True, text=True, timeout=75
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            raise Exception(f"Scraper subprocess failed: {proc.stderr[-300:]}")
        
        # Get last non-empty line (ignore RSS warning lines)
        output_lines = [l for l in proc.stdout.strip().splitlines() if l.startswith('{')]
        if not output_lines:
            raise Exception("No JSON output from scraper subprocess")
        media_info = _json.loads(output_lines[-1])
        
        adverse_hits = media_info.get('all_hits', [])
        summary = {
            'risk_level': media_info.get('risk_level', 'CLEAR'),
            'risk_score': media_info.get('risk_score', 0),
            'total_hits': media_info.get('total_hits', 0),
            'recommendation': media_info.get('recommendation', '')
        }
        
        # User Requirement: update DB with result
        execute_db(f"UPDATE screening_results SET adverse_media = {param}, adverse_media_summary = {param} WHERE id = {param}", 
                  (json.dumps(adverse_hits), json.dumps(summary), result_id))
    except Exception as e:
        logger.error(f"Adverse media scraper crashed: {e}")
        adverse_hits = []
        summary = {
            'risk_level': 'TIMEOUT',
            'risk_score': 0,
            'total_hits': 0,
            'recommendation': 'Media search temporarily unavailable. Please try again later.'
        }
        # update DB with TIMEOUT status — never leave it PENDING
        try:
            execute_db(f"UPDATE screening_results SET adverse_media = {param}, adverse_media_summary = {param} WHERE id = {param}", 
                      (json.dumps(adverse_hits), json.dumps(summary), result_id))
        except Exception as db_err:
            logger.error(f"Failed to update db with TIMEOUT status: {db_err}")
    finally:
        # Always return a valid response — never return 500
        return jsonify({
            'status': 'completed',
            'summary': summary,
            'hits': adverse_hits
        })

@screening_bp.route('/api/stats')
@login_required
@permission_required('screening', level='edit')
def api_screening_stats():
    res = query_db("SELECT COUNT(*) as count FROM screening_watchlist WHERE is_active = 1", one=True)
    return jsonify({'watchlist_count': res['count'] if res else 0})

@screening_bp.route('/download_report/<int:id>')
@login_required
@permission_required('screening', level='view')
def download_report(id):
    param = get_param_style()
    result = query_db(f"SELECT * FROM screening_results WHERE id = {param}", (id,), one=True)
    
    if not result:
        flash('Screening result not found', 'error')
        return redirect(url_for('screening.dashboard'))
        
    matches = json.loads(result['matches']) if isinstance(result['matches'], str) else result['matches']
    if matches:
        matches = sorted(matches, key=lambda x: x.get('match_score', 0) if isinstance(x, dict) else 0, reverse=True)

    adverse_hits = []
    if result['adverse_media']:
        try:
            adverse_hits = json.loads(result['adverse_media']) if isinstance(result['adverse_media'], str) else result['adverse_media']
            if adverse_hits:
                adverse_hits = sorted(adverse_hits, key=lambda x: x.get('risk_score', 0), reverse=True)
        except Exception:
            adverse_hits = []

    return render_template('screening/report.html', result=result, matches=matches, adverse_hits=adverse_hits)

@screening_bp.route('/update_watchlist', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def update_watchlist():
    if not current_user.is_admin() and not current_user.is_compliance_officer():
         return jsonify({'error': 'Access denied'}), 403

    source_id = request.form.get('source_id')
    user_id = current_user.id

    from config import get_config
    cfg = get_config()
    db_config = dict(cfg.POSTGRES_CONFIG)

    def _run_sync(source_id, user_id, db_config):
        try:
            from screening.data_updater_enhanced import EnhancedDataUpdater
            updater = EnhancedDataUpdater(db_config)
            count = updater.update_watchlist(
                source_id=int(source_id) if source_id else None,
                user_id=user_id
            )
            updater.close_db()  # was .close() - method does not exist; broke ES-sync trigger after every manual sync
            trigger_es_incremental_sync()
            import logging
            logging.getLogger(__name__).info(
                f'[SYNC COMPLETE] source_id={source_id} records={count}'
            )
        except Exception as e:
            import traceback, logging
            logging.getLogger(__name__).error(
                f'[SYNC FAILED] source_id={source_id} error={traceback.format_exc()}'
            )

    t = threading.Thread(target=_run_sync, args=(source_id, user_id, db_config), daemon=True)
    t.start()

    source_label = f'source #{source_id}' if source_id else 'all sources'
    flash(f'Sync started for {source_label}. This runs in the background — check logs or refresh in a minute.', 'success')
    return redirect(url_for('screening.data_sources'))


# ============================================================================
# DATA SOURCES MANAGEMENT (PostgreSQL Dev Environment)
# ============================================================================

@screening_bp.route('/data-sources')
@login_required
@permission_required('screening', level='view')
def data_sources_dev():
    """Orphaned duplicate of /screening/sources — its template
    (screening/data_sources.html) was never added and nothing in the UI
    links here, so it 500'd with TemplateNotFound for anyone who hit the
    URL directly. /screening/sources (sources.html) already covers the
    same data."""
    return redirect(url_for('screening.data_sources'))


@screening_bp.route('/source-logs/<source>')
@login_required
@permission_required('screening', level='view')
def view_source_logs(source):
    """View update logs for a specific data source"""
    param = get_param_style()
    
    try:
        logs = query_db(
            f"SELECT * FROM screening_update_logs WHERE source_name = {param} ORDER BY update_started_at DESC LIMIT 50",
            (source,)
        )
    except Exception:
        logs = []
    
    return render_template('screening/history.html', screenings=logs, page=1)


import threading
import uuid
import pandas as pd
from flask import jsonify

# Global in-memory dictionary to store bulk upload job states
BULK_JOBS = {}

from flask import current_app
from database.db import get_db, query_db

def background_bulk_processor(app, job_id, df, user_id):
    """Processes a bulk screening job in the background with parallel processing."""
    with app.app_context():
        results_map = {}
        total = len(df)
        
        def process_single_row(index, row):
            try:
                with app.app_context():
                    engine = get_engine()
                    try:
                        name = str(row.get('name', '')).strip()
                        if not name or str(name).lower() == 'nan':
                            return index, None
                            
                        entity_type = row.get('type', 'Individual')
                        dob = row.get('dob', None)
                        nationality = row.get('nationality', None)
                        
                        screen_res = engine.screen_person(
                            name=name,
                            date_of_birth=str(dob) if dob else None,
                            nationality=str(nationality) if nationality else None,
                            entity_type=str(entity_type).upper(),
                            user_id=user_id,
                            include_media=False
                        )
                        
                        _save_screening_result(
                            name=name,
                            entity_type=entity_type,
                            dob=dob,
                            nationality=nationality,
                            source_module='Bulk Upload',
                            source_record_id=None,
                            result=screen_res,
                            user_id=user_id,
                            screening_type='BULK'
                        )
                        
                        res_item = {
                            'name': name,
                            'type': entity_type,
                            'result': screen_res['screening_result'],
                            'score': screen_res['highest_score'],
                            'matches': len(screen_res['matches']),
                            'details': screen_res
                        }
                        return index, res_item
                    finally:
                        # engine.close()  # REMOVED: singleton must not be closed per-request
                        pass
            except Exception as e:
                logger.error(f"Error screening row {index}: {str(e)}")
                return index, None

        # Execute in parallel
        futures = []
        # Use a reasonable number of workers for DB operations - 4 is balanced for SQLite
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
            for idx, row in df.iterrows():
                futures.append(executor.submit(process_single_row, idx, row))
            
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                idx, res = future.result()
                if res:
                    results_map[idx] = res
                completed += 1
                if job_id in BULK_JOBS:
                    BULK_JOBS[job_id]['current_count'] = completed

        # Sort results back to original order
        final_results = [results_map[i] for i in sorted(results_map.keys())]
        
        if job_id in BULK_JOBS:
            BULK_JOBS[job_id]['status'] = 'completed'
            BULK_JOBS[job_id]['results'] = final_results

@screening_bp.route('/bulk-upload', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
@login_required
@permission_required('screening')
@permission_required('screening', level='edit')
def bulk_screening_upload():
    """Handle bulk screening via file upload mapping."""
    if request.method == 'POST':
        # Now handles AJAX API requests
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        if 'file' not in request.files:
            if is_ajax: return jsonify({"status": "error", "message": "No file part"}), 400
            flash('No file part', 'error')
            return redirect(request.url)
            
        file = request.files['file']
        if file.filename == '':
            if is_ajax: return jsonify({"status": "error", "message": "No selected file"}), 400
            flash('No selected file', 'error')
            return redirect(request.url)
            
        if file and (file.filename.endswith('.csv') or file.filename.endswith('.xlsx')):
            try:
                if file.filename.endswith('.csv'):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)
                
                # normalize columns
                df.columns = [c.lower().strip().replace(' ', '_') for c in df.columns]
                
                if 'name' not in df.columns:
                    if is_ajax: return jsonify({"status": "error", "message": 'File must contain a "Name" column.'}), 400
                    flash('File must contain a "Name" column.', 'error')
                    return redirect(request.url)
                
                # Generate unique ID and start job
                job_id = str(uuid.uuid4())
                BULK_JOBS[job_id] = {
                    'status': 'processing',
                    'total_count': len(df),
                    'current_count': 0,
                    'results': None,
                    'message': ''
                }
                
                # Spawning Thread
                app = current_app._get_current_object()
                user_id = current_user.id
                thread = threading.Thread(target=background_bulk_processor, args=(app, job_id, df, user_id))
                thread.daemon = True
                thread.start()
                
                if is_ajax: 
                    return jsonify({"status": "started", "job_id": job_id})
                
                flash('Upload started. Warning: synchronous render deprecated.', 'info')
                return redirect(request.url)
                
            except Exception as e:
                logger.error(f"Bulk setup failed: {e}")
                if is_ajax: return jsonify({"status": "error", "message": f'Error processing file: {str(e)}'}), 500
                flash(f'Error processing file: {str(e)}', 'error')
                return redirect(request.url)
        else:
            if is_ajax: return jsonify({"status": "error", "message": 'Allowed file types are CSV and Excel (.xlsx)'}), 400
            flash('Allowed file types are CSV and Excel (.xlsx)', 'error')
            return redirect(request.url)

    return render_template('screening/bulk_upload.html')

@screening_bp.route('/bulk-upload-status/<job_id>', methods=['GET'])
@login_required
@permission_required('screening')
@permission_required('screening', level='edit')
def bulk_upload_status(job_id):
    """AJAX Polling route to return current upload processing metrics"""
    job = BULK_JOBS.get(job_id)
    if not job:
        return jsonify({"status": "error", "message": "Job ID not found"}), 404
        
    return jsonify({
        "status": job['status'],
        "total_count": job['total_count'],
        "current_count": job['current_count'],
        "message": job.get('message', '')
    })

@screening_bp.route('/bulk-results/<job_id>', methods=['GET'])
@login_required
@permission_required('screening')
def bulk_results_view(job_id):
    """Serves the completion view payload"""
    job = BULK_JOBS.get(job_id)
    if not job or job['status'] != 'completed':
        flash('Invalid or incomplete job result payload request.', 'error')
        return redirect(url_for('screening.screening_queue'))
        
    results = job['results']
    # Cleanup memory
    del BULK_JOBS[job_id] 
    
    return render_template('screening/bulk_results.html', results=results)

@screening_bp.route('/bulk-template')
@login_required
@permission_required('screening', level='view')
def bulk_template():
    """Generate and download a sample bulk screening template."""
    import pandas as pd
    from io import BytesIO
    
    data = {
        'Name': ['Ahmed Mohamed', 'Global Trade Corp'],
        'Type': ['Individual', 'Entity'],
        'DOB': ['1980-01-01', ''],
        'Nationality': ['Egypt', ''],
        'ID': ['123456789', '']
    }
    df = pd.DataFrame(data)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
        
    output.seek(0)
    
    return send_file(
        output,
        download_name='bulk_screening_template.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@screening_bp.route('/api/scrape-all', methods=['POST'])
@limiter.limit('5 per hour')
@login_required
@permission_required('screening', level='edit')
def api_scrape_all():
    """
    API endpoint to manually trigger scraping of all sources
    """
    if not current_user.is_admin() and not current_user.is_compliance_officer():
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, 'scripts', 'scrape_all_sources.py')],
            capture_output=True,
            text=True,
            timeout=1800  # 30 minute timeout
        )
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'All sources scraped successfully',
                'total_added': 0,
                'total_updated': 0
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr
            }), 500
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@screening_bp.route('/api/scrape-source', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def api_scrape_source():
    """
    API endpoint to auto-scrape data from a source URL.
    For OpenSanctions: uses GlobalPEPImporter (CSV) to import PEP data.
    For others: downloads the file from source_url and imports it.
    """
    if not current_user.is_admin() and not current_user.is_compliance_officer():
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        data = request.get_json()
        source_name = data.get('source')
        
        if not source_name:
            return jsonify({'success': False, 'error': 'Source name required'}), 400
        
        # Get the source info from DB using abstraction
        param = get_param_style()
        source_row = query_db(f'SELECT * FROM screening_data_sources WHERE source_name = {param}', (source_name,), one=True)
        
        if not source_row:
             # Fallback for legacy source names or if DB is empty
             if source_name in ['opensanctions', 'opensanctions_pep', 'sanctions', 'pep', 'un']:
                 pass # Allow these known sources even if DB record is missing (auto-heal)
             else:
                return jsonify({'success': False, 'error': f'Source not found: {source_name}'}), 404

        if source_name in ('internal_blacklist', 'internal_pep') or (source_row and source_row.get('source_type') == 'CUSTOM'):
            return jsonify({
                'success': False,
                'error': f'{source_name} has no external URL to scrape — it is populated via the Bulk Upload feature instead.'
            }), 400

        if source_name in ['opensanctions', 'opensanctions_pep', 'sanctions', 'pep', 'un']:
            # Use EnhancedDataUpdater like all other sources.
            # NOTE: Config has no flat POSTGRES_HOST/POSTGRES_PORT/... attributes
            # (only the nested POSTGRES_CONFIG dict) — getattr(cfg, 'POSTGRES_PORT', 6432)
            # used to silently return the hardcoded fallback every time, including the
            # wrong port 6432. Use the same dict the app itself connects with instead.
            from config import get_config
            cfg = get_config()
            db_config = dict(cfg.POSTGRES_CONFIG)
            # Get source_id from DB row
            sid = source_row['id'] if source_row else None

            task_id = str(uuid.uuid4())

            def run_opensanctions_sync(tid, source_id, dbc):
                try:
                    update_task_status(tid, 'processing', f'Connecting to {source_name}...', 2, 100)
                    from screening.data_updater_enhanced import EnhancedDataUpdater
                    updater = EnhancedDataUpdater(dbc, task_id=tid)
                    update_task_status(tid, 'processing', f'Downloading {source_name} data... (0 records)', 5, 100)
                    result = updater.update_watchlist(source_id=source_id, user_id=1)
                    msg = f"Done: {result.get('added',0)} added, {result.get('updated',0)} updated"
                    trigger_es_incremental_sync()
                    update_task_status(tid, 'completed', msg, 100, 100, result=result)
                except Exception as e:
                    update_task_status(tid, 'failed', str(e))

            thread = threading.Thread(target=run_opensanctions_sync, args=(task_id, sid, db_config))
            thread.daemon = True
            thread.start()

            return jsonify({'success': True, 'task_id': task_id, 'message': f"Syncing {source_name} started..."})

        elif source_name == 'emlcu':
            # Use the specialized EMLCU scraper which handles website parsing
            # We must import it locally to avoid circular imports if any
            
            task_id = str(uuid.uuid4())
            
            def run_emlcu_scrape_task(tid):
                try:
                    cleanup_old_tasks()
                    update_task_status(tid, 'processing', 'Initializing EMLCU scraper...', 0, 100)
                    
                    # Import here
                    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'screening'))
                    from emlcu_scraper_production import EMLCUScraperFixed
                    
                    scraper = EMLCUScraperFixed()
                    update_task_status(tid, 'processing', 'Searching for latest EMLCU list...', 20, 100)
                    
                    # Download file without parsing first
                    file_path = scraper.download_only()
                    
                    if not file_path:
                        raise Exception("Failed to download EMLCU file")
                        
                    update_task_status(tid, 'processing', 'File downloaded. Starting import...', 50, 100)
                    
                    # Import
                    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts')
                    if scripts_dir not in sys.path: sys.path.append(scripts_dir)
                    from import_sanctions_file import import_sanctions_file
                    
                    def progress_callback(stage, data):
                        if stage == 'importing':
                            processed = data.get('processed', 0)
                            total = data.get('total', 1)
                            pct = 50 + (processed / total * 40)
                            update_task_status(tid, 'processing', f"Importing: {processed} records", int(pct), 100)
                    
                    stats = import_sanctions_file(file_path, 'emlcu', progress_callback=progress_callback)
                    
                    result_msg = f"Import complete: {stats.get('added', 0)} added, {stats.get('updated', 0)} updated"
                    update_task_status(tid, 'completed', result_msg, result=stats)
                    
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    update_task_status(tid, 'failed', str(e))
            
            thread = threading.Thread(target=run_emlcu_scrape_task, args=(task_id,))
            thread.daemon = True
            thread.start()
            
            return jsonify({'success': True, 'task_id': task_id, 'message': "Syncing EMLCU (Advanced Scraper)..."})

        else:
            # For UN, OFAC, EU, HMT: background auto-scrape
            source_url = source_row['source_url'] if source_row else None
            
            if not source_url:
                urls = {
                    'un': 'https://scsanctions.un.org/resources/xml/en/consolidated.xml',
                    'ofac': 'https://www.treasury.gov/ofac/downloads/sdn.xml',
                    'eu': 'https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content%stoken=dG9rZW4tMjAxNw',
                    'hmt': 'https://ofsistorage.blob.core.windows.net/publish/oslist.json'
                    # EMLCU handled above
                }
                for k, v in urls.items():
                    if k in source_name.lower():
                        source_url = v
                        break
            
            if not source_url:
                return jsonify({'success': False, 'error': f'Source URL not found for {source_name}'}), 400

            # Mapping is now standardized to slugs (un, ofac, eu, hmt, emlcu)
            source_key = source_name
            
            task_id = str(uuid.uuid4())
            thread = threading.Thread(target=run_async_auto_scrape, args=(task_id, source_name, source_url, source_key))
            thread.daemon = True
            thread.start()
            
            return jsonify({'success': True, 'task_id': task_id, 'message': f"Syncing {source_name}..."})
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"\n🚨 FATAL SCRAPER ERROR ({source_key}):\n{error_details}\n")
        logger.error(f"Scraper failed for {source_key}: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# EMLCU FILE UPLOAD
# ============================================================================

@screening_bp.route('/api/upload-sanctions', methods=['POST'])
@login_required
@permission_required('screening', level='admin')
def upload_sanctions():
    """
    Generic API endpoint to upload sanctions files (XML/XLSX).
    Requires 'source' form field (un, ofac, eu, hmt, emlcu).
    """
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        source = request.form.get('source')
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
            
        if not source:
            return jsonify({'success': False, 'error': 'No source specified'}), 400

        # Validate file extension based on source
        valid_exts = {
            'un': '.xml',
            'ofac': '.xml',
            'eu': '.xml',
            'hmt': '.xml',
            'emlcu': '.xlsx',
            'internal_blacklist': '.csv',
            'internal_pep': '.csv'
        }
        
        if source not in valid_exts:
             return jsonify({'success': False, 'error': f'Invalid source: {source}'}), 400
             
        ext = valid_exts[source]
        if not file.filename.lower().endswith(ext):
            return jsonify({'success': False, 'error': f'Invalid file type. Expected {ext} for {source}'}), 400
        
        # Save to temp location
        import tempfile
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        
        timestamp = __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')
        # Determine extension for saving. source_key doesn't exist in this
        # function (that was the bug — only upload_source_file() defines
        # that name; this function's variable is source) and crashed every
        # upload with NameError before it ever reached the import step.
        if source in ('internal_blacklist', 'internal_pep'):
            if file.filename.lower().endswith('.xlsx') or file.filename.lower().endswith('.xls'):
                _ext = '.xlsx'
            else:
                _ext = '.csv'
        else:
            _ext = valid_exts.get(source, '.xml')
        safe_filename = f"{source}_upload_{timestamp}{_ext}"
        file_path = os.path.join(upload_dir, safe_filename)
        file.save(file_path)

        # Run import
        from scripts.import_sanctions_file import import_sanctions_file, DB_CONFIG
        
        # Use existing DB config matching the app app context if possible, 
        # or fall back to script's default. 
        # For now we rely on the script's own DB connection logic which is robust.
        
        # Handle internal lists differently
        if source in ['internal_blacklist', 'internal_pep']:
            # Import to internal table first
            from screening.internal_upload_handler import handle_internal_upload
            stats = handle_internal_upload(file_path, source)
            
            # Auto-sync to screening_watchlist
            import subprocess
            sync_result = subprocess.run([
                sys.executable,
                os.path.join(BASE_DIR, 'scripts', 'sync_internal_to_watchlist.py')
            ], capture_output=True, text=True)
            if sync_result.returncode != 0:
                logger.error(f"sync_internal_to_watchlist failed: {sync_result.stderr[-500:]}")
            trigger_es_incremental_sync()
        else:
            # External sources use existing import
            stats = import_sanctions_file(file_path, source)
        
        return jsonify({
            'success': True,
            'source': stats.get('source', source),
            'added': stats.get('added', 0),
            'updated': stats.get('updated', 0),
            'total': stats.get('total_processed', 0),
            'message': f"Import successful: {stats.get('added', 0)} added, {stats.get('updated', 0)} updated"
        })

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        failed_source = locals().get('source', 'unknown')
        print(f"\n🚨 FATAL SCRAPER ERROR ({failed_source}):\n{error_details}\n")
        logger.error(f"Scraper failed for {failed_source}: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Keep the old generic route for compatibility if needed, or remove it%s
# For now, we'll keep the EMLCU specific one as legacy or redirect logic%s
# Actually, let's keep EMLCU specific route if the UI uses it, but we are rewriting the UI to use the new one.
# So I will replacing upload_emlcu with the generic one or just add it before/after%s
# The user wants "button infront of each source list".
# I'll keep upload_emlcu for backward compat if I didn't delete the old UI code yet. 
# But I will replace the block I see in the view_file output.

@screening_bp.route('/api/upload-source', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def upload_source_file():
    """
    Handle manual file upload for a specific source asynchronously.
    Returns a task_id to poll for status.
    """
    if not current_user.is_admin() and not current_user.is_compliance_officer():
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file part'}), 400
            
        file = request.files['file']
        source = request.form.get('source')
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No selected file'}), 400
            
        if not source:
            return jsonify({'success': False, 'error': 'No source specified'}), 400

        # Validate file extension based on source
        valid_exts = {
            'un': '.xml',
            'ofac': '.xml',
            'eu': '.xml',
            'hmt': '.xml',
            'emlcu': '.xlsx',
            'internal_blacklist': '.csv',
            'internal_pep': '.csv'
        }
        
        # Check source prefix or exact match
        source_key = None
        if 'un_' in source or source == 'un': source_key = 'un'
        elif 'ofac' in source: source_key = 'ofac'
        elif 'eu_' in source or source == 'eu': source_key = 'eu'
        elif 'hmt' in source or 'uk' in source: source_key = 'hmt'
        elif 'emlcu' in source: source_key = 'emlcu'
        elif source == 'internal_pep': source_key = 'internal_pep'
        elif 'internal' in source or 'custom' in source: source_key = 'internal_blacklist'
        
        if not source_key:
             return jsonify({'success': False, 'error': f'Unsupported source type: {source}'}), 400
             
        # Validate extension
        if source_key in ('internal_blacklist', 'internal_pep'):
            if not (file.filename.lower().endswith('.csv') or file.filename.lower().endswith('.xlsx') or file.filename.lower().endswith('.xls')):
                return jsonify({'success': False, 'error': 'Invalid file. Requires CSV or Excel file.'}), 400
        else:
            ext = valid_exts.get(source_key, '.xml')
            if not file.filename.lower().endswith(ext):
                 # For EMLCU allow any Excel variant (.xls, .xlsm, .xlsa, etc.)
                 if source_key == 'emlcu' and any(file.filename.lower().endswith(e) for e in ['.xls', '.xlsm', '.xlsa', '.xlsx']):
                     pass
                 else:
                    return jsonify({'success': False, 'error': f'Invalid file type. Expected {ext} for {source}'}), 400
        
        # Save to temp location
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        
        timestamp = __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')
        # Determine extension for saving
        if source_key in ('internal_blacklist', 'internal_pep'):
            if file.filename.lower().endswith('.xlsx') or file.filename.lower().endswith('.xls'):
                _ext = '.xlsx'
            else:
                _ext = '.csv'
        else:
            _ext = valid_exts.get(source_key, '.xml')
        safe_filename = f"{source}_upload_{timestamp}{_ext}"
        file_path = os.path.join(upload_dir, safe_filename)
        file.save(file_path)
        
        # Generate Task ID
        task_id = str(uuid.uuid4())
        
        # Start async thread
        thread = threading.Thread(target=run_async_import, args=(task_id, file_path, source_key))
        thread.daemon = True # Allow app to exit even if thread is running
        thread.start()
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': 'Upload started. Processing in background...'
        })

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        # source_key is only assigned at line ~1650, after the file/source
        # form fields are read — an exception before that point would still
        # crash this handler with NameError without this fallback.
        failed_source = locals().get('source_key') or locals().get('source', 'unknown')
        print(f"\n🚨 FATAL SCRAPER ERROR ({failed_source}):\n{error_details}\n")
        logger.error(f"Scraper failed for {failed_source}: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@screening_bp.route('/api/task_status/<task_id>', methods=['GET'])
@login_required
@permission_required('screening', level='view')
def get_task_status(task_id):
    try:
        conn = _get_task_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT status, message, progress, total, result FROM screening_tasks WHERE task_id = %s", (task_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return jsonify({
                'success': True,
                'status': row[0],
                'message': row[1] or '',
                'progress': row[2] or 0,
                'total': row[3] or 100,
                'result': row[4] or {}
            })
    except Exception:
        pass
    # Fallback to in-memory
    if task_id in TASK_STATUS:
        info = TASK_STATUS[task_id]
        return jsonify({
            'success': True,
            'status': info['status'],
            'message': info.get('message', ''),
            'progress': info.get('progress', 0),
            'total': info.get('total', 0),
            'result': info.get('result', {})
        })
    return jsonify({'success': False, 'error': 'Task not found'}), 404
def upload_emlcu():
    # ... logic ...
    # Wait, I should just redirect this to the new logic if I want cleanlyness, 
    # but the new logic expects 'source' param.
    # I will leave the old one alone and add the new one above it.
    pass

    #     file.save(file_path)
    #     
    #     # Import using the EMLCU importer
    #     import sys
    #     scripts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts')
    #     if scripts_dir not in sys.path:
    #         sys.path.insert(0, scripts_dir)
    #     
    #     from import_emlcu_excel import import_emlcu_file
        
    #     stats = import_emlcu_file(file_path)
    #     
    #     return jsonify({
    #         'success': True,
    #         'message': 'EMLCU file imported successfully',
    #         'file_name': file.filename,
    #         'stats': {
    #             'added': stats.get('added', 0),
    #             'updated': stats.get('updated', 0),
    #             'total_processed': stats.get('total_processed', 0),
    #             'sheet_stats': stats.get('sheet_stats', {})
    #         }
    #     })
    #     
    # except Exception as e:
    #     import traceback
    #     traceback.print_exc()
    #     return jsonify({
    #         'success': False,
    #         'error': str(e)
    #     })
    #             'error': str(e)
    #         }), 500
@screening_bp.route('/transactions/<customer_id>')
@login_required
@permission_required('screening', level='view')
def view_customer_transactions(customer_id):
    # Fetch customer details
    customer = query_db("SELECT * FROM customers WHERE customer_reference = %s", (customer_id,), one=True)

    if not customer:
        flash(f'Customer {customer_id} not found', 'error')
        return redirect(url_for('screening.dashboard'))
        
    # Fetch transactions
    transactions = query_db("SELECT * FROM customer_transactions WHERE customer_id = %s ORDER BY timestamp DESC", (customer_id,))
    
    # Analyze
    analyzer = TransactionAnalyzer()
    alerts = analyzer.analyze_transactions(customer_id, [dict(tx) for tx in transactions])
    stats = analyzer.get_summary_stats([dict(tx) for tx in transactions])
    
    return render_template('screening/customer_transactions.html', 
                           customer=customer, 
                           transactions=transactions,
                           alerts=alerts,
                           stats=stats)

@screening_bp.route('/reports')
@login_required
@permission_required('screening', level='view')
def reports_dashboard():
    # Fetch recent reports or stats for dashboard
    return render_template('screening/reports_dashboard.html')


@screening_bp.route('/reports/kyc-periodic-review')
@login_required
@permission_required('screening', level='view')
def kyc_periodic_review():
    """KYC Periodic Review Summary Report"""
    # Removed web-only get_db, query_db
    import csv, io
    from datetime import date
    
    today = date.today().isoformat()
    
    customers = query_db("""
        SELECT 
            customer_reference, full_name, company_name,
            risk_classification, status, nationality,
            onboarding_date, last_review_date, next_review_date,
            risk_score,
            CASE 
                WHEN next_review_date IS NULL THEN 'NO_REVIEW_DATE'
                WHEN next_review_date < %s THEN 'OVERDUE'
                WHEN next_review_date <= %s THEN 'DUE_SOON'
                ELSE 'UP_TO_DATE'
            END as review_status
        FROM customers
        WHERE status NOT IN ('CLOSED','REJECTED')
        ORDER BY 
            CASE WHEN next_review_date < %s THEN 0
                 WHEN next_review_date IS NULL THEN 1
                 ELSE 2 END,
            next_review_date ASC NULLS LAST
    """, (today, today, today))
    
    # Export as CSV if requested
    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Customer Ref', 'Full Name', 'Risk Classification', 'Status',
            'Nationality', 'Onboarding Date', 'Last Review Date',
            'Next Review Date', 'Risk Score', 'Review Status'
        ])
        for c in customers:
            writer.writerow([
                c['customer_reference'],
                c['full_name'] or c['company_name'] or '',
                c['risk_classification'] or '',
                c['status'] or '',
                c['nationality'] or '',
                c['onboarding_date'] or '',
                c['last_review_date'] or '',
                c['next_review_date'] or '',
                c['risk_score'] or '',
                c['review_status']
            ])
        output.seek(0)
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=KYC_Periodic_Review_{today}.csv'}
        )
    
    # Summary stats
    total = len(customers)
    overdue = sum(1 for c in customers if c['review_status'] == 'OVERDUE')
    due_soon = sum(1 for c in customers if c['review_status'] == 'DUE_SOON')
    no_date = sum(1 for c in customers if c['review_status'] == 'NO_REVIEW_DATE')
    high_risk = sum(1 for c in customers if c['risk_classification'] == 'HIGH')
    
    stats = {
        'total': total, 'overdue': overdue,
        'due_soon': due_soon, 'no_date': no_date, 'high_risk': high_risk
    }
    
    return render_template('screening/kyc_periodic_review.html',
                           customers=customers, stats=stats, today=today)

@screening_bp.route('/reports/generate/sar', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='view')
def generate_sar():
    if request.method == 'POST':
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        
        service = ReportingService()
        report_data = service.generate_suspicious_activity_report(start_date, end_date)
        
        # Add high-score screenings to suspicious_entities for demo
        recent_hits = query_db("""
            SELECT screened_name as name, screening_result as risk_type, 
                   highest_match_score as score, created_at as detected_at
            FROM screening_results 
            WHERE screening_result IN ('CONFIRMED_HIT', 'POTENTIAL_MATCH')
            AND created_at BETWEEN %s AND %s
        """, (start_date, end_date))
        
        report_data['suspicious_entities'] = [dict(hit) for hit in recent_hits]
        report_data['summary_stats']['high_risk_matches'] = len(recent_hits)
        
        if request.form.get('export') == 'csv':
            csv_content = service.export_as_csv(report_data)
            return Response(
                csv_content,
                mimetype="text/csv",
                headers={"Content-disposition": f"attachment; filename=SAR_{start_date}_{end_date}.csv"}
            )
            
        return render_template('screening/sar_preview.html', report=report_data)
        
    return render_template('screening/generate_sar_form.html')


# =========================================================
# URL Management Routes
# =========================================================

@screening_bp.route('/urls')
@login_required
@permission_required('screening', 'view')
def manage_urls():
    """URL management admin page"""
    db = get_db()
    param = "%s" if current_app.config.get('DB_TYPE', 'sqlite') == 'sqlite' else "%s"
    
    sources = query_db("""
        SELECT id, source_name, source_display_name, source_type, source_url, 
               is_active, priority, last_successful_update, update_frequency_hours
        FROM screening_data_sources
        ORDER BY priority
    """)
    
    return render_template('screening/manage_urls.html', sources=sources)


@screening_bp.route('/urls/update', methods=['POST'])
@login_required
@permission_required('screening', level='admin')
def update_source_url():
    """API endpoint to update a source URL"""
    from .url_config_manager import URLConfigManager
    
    data = request.get_json()
    source_id = data.get('source_id')
    new_url = data.get('url')
    notes = data.get('notes')
    validate = data.get('validate', True)
    
    if not source_id or not new_url:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
    
    db_path = current_app.config.get('DATABASE')
    manager = URLConfigManager(db_path)
    success = manager.update_url(source_id, new_url, current_user.id, notes, validate)
    
    if success:
        return jsonify({'success': True, 'message': 'URL updated successfully'})
    else:
        return jsonify({'success': False, 'error': 'URL validation failed or update error'}), 400


@screening_bp.route('/urls/validate', methods=['POST'])
@login_required
@permission_required('screening', 'view')
def validate_source_url():
    """API endpoint to validate a URL"""
    from .url_config_manager import URLConfigManager
    
    data = request.get_json()
    url = data.get('url')
    
    if not url:
        return jsonify({'valid': False, 'error': 'URL is required'}), 200

    # Reject non-HTTP URLs and anything resolving to an internal/private address
    # before the server makes an outbound request on the caller's behalf (SSRF guard).
    safe, err = _is_safe_external_url(url)
    if not safe:
        return jsonify({'valid': False, 'error': err, 'skipped': True}), 200

    try:
        import requests as req
        headers = {'User-Agent': 'ComplyNex-CMS/1.0'}
        # Try GET first with stream=True to avoid full load, or HEAD if preferred
        # Many servers block HEAD, so we try GET directly if needed
        try:
            response = req.get(url, timeout=15, stream=True, headers=headers)
        except Exception:
            # Fallback to HEAD if GET fails for some reason
            response = req.head(url, timeout=15, allow_redirects=True, headers=headers)
        
        result = {
            'valid': response.status_code < 400,
            'status_code': response.status_code,
            'content_type': response.headers.get('Content-Type', ''),
            'error': None if response.status_code < 400 else f'HTTP {response.status_code}'
        }
        return jsonify(result)
        
    except req.exceptions.Timeout:
        return jsonify({'valid': False, 'error': 'Request timeout (>15s)', 'status_code': None})
    except req.exceptions.SSLError:
        return jsonify({'valid': False, 'error': 'SSL certificate error', 'status_code': None})
    except req.exceptions.ConnectionError:
        return jsonify({'valid': False, 'error': 'Connection refused or DNS failure', 'status_code': None})
    except Exception as e:
        return jsonify({'valid': False, 'error': str(e)[:100], 'status_code': None})


@screening_bp.route('/urls/history')
@login_required
@permission_required('screening', 'view')
def get_url_history():
    """API endpoint to get URL history"""
    from .url_config_manager import URLConfigManager
    
    source_id = request.args.get('source_id', type=int)
    
    if not source_id:
        return jsonify({'success': False, 'error': 'source_id is required'}), 400
    
    db_path = current_app.config.get('DATABASE')
    manager = URLConfigManager(db_path)
    history = manager.get_url_history(source_id)
    
    return jsonify({'success': True, 'history': history})


# =========================================================
# Audit Log Routes
# =========================================================

@screening_bp.route('/audit-log')
@login_required
@permission_required('screening', 'view')
def audit_log():
    """Audit log viewer page"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status_filter = request.args.get('status', '')
    source_filter = request.args.get('source', '')
    
    # Build query
    conditions = []
    params = []
    
    if status_filter:
        conditions.append("dal.status = %s")
        params.append(status_filter)
    
    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)
    
    # Get total count
    count_sql = f"SELECT COUNT(*) as cnt FROM data_update_audit_log dal {where_clause}"
    total = query_db(count_sql, params, one=True)
    total_count = total['cnt'] if total else 0
    
    # Get paginated records
    offset = (page - 1) * per_page
    params_page = params + [per_page, offset]
    
    records = query_db(f"""
        SELECT dal.*, u.email as initiated_by_user
        FROM data_update_audit_log dal
        LEFT JOIN users u ON dal.initiated_by = u.id
        {where_clause}
        ORDER BY dal.started_at DESC
        LIMIT %s OFFSET %s
    """, params_page)
    
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    
    return render_template('screening/audit_log.html',
        records=records,
        page=page,
        per_page=per_page,
        total_count=total_count,
        total_pages=total_pages,
        status_filter=status_filter,
        source_filter=source_filter
    )


# =============================================================================
# SCREENING WORKFLOW SYSTEM — Queue, History, Whitelist, Unified API
# =============================================================================

HIGH_RISK_THRESHOLD = 70.0  # Matches ≥ this go to queue for review


@screening_bp.route('/queue')
@login_required
@permission_required('screening')
@permission_required('screening', level='edit')
def screening_queue():
    """Queue dashboard — shows pending reviews for matches ≥70%."""
    status_filter = request.args.get('status', '')
    priority_filter = request.args.get('priority', '')
    source_filter = request.args.get('list_source', '')
    assigned_filter = request.args.get('assigned', '')
    
    # Pagination settings
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    if per_page not in [25, 50, 100]:
        per_page = 25
    offset = (page - 1) * per_page

    conditions = []
    params = []
    if status_filter:
        conditions.append("q.status = %s")
        params.append(status_filter)
    if priority_filter:
        conditions.append("q.priority = %s")
        params.append(priority_filter)
    if source_filter:
        conditions.append("q.list_source = %s")
        params.append(source_filter)
    if assigned_filter:
        conditions.append("q.assigned_to = %s")
        params.append(int(assigned_filter))

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Count unique entities for pagination
    total_res = query_db(f"""
        SELECT COUNT(DISTINCT entity_name || '|' || COALESCE(entity_type, 'Individual')) as cnt 
        FROM screening_queue q 
        {where}
    """, params, one=True)
    total_count = total_res['cnt'] if total_res else 0

    sort_by = request.args.get('sort', 'priority')
    order = request.args.get('order', 'asc').lower()
    if order not in ['asc', 'desc']:
        order = 'asc'

    sql_order = order.upper()
    
    # Sorting logic for unique entities
    if sort_by == 'date':
        entity_sort = f"group_created_at {sql_order}"
    elif sort_by == 'score':
        entity_sort = f"max_score {sql_order}"
    elif sort_by == 'entity':
        entity_sort = f"entity_name {sql_order}"
    elif sort_by == 'priority':
        entity_sort = f"min_priority_order {'ASC' if sql_order == 'ASC' else 'DESC'}"
    else:
        # Default sort: Priority DESC (High first), then Date DESC
        entity_sort = "min_priority_order ASC, group_created_at DESC"

    # 1. Fetch the subset of entities for the current page
    # 2. Join with the full queue to fetch all hits for those entities
    items = query_db(f"""
        WITH entity_page AS (
            SELECT 
                entity_name, 
                COALESCE(entity_type, 'Individual') as entity_type_norm,
                MAX(match_score) as max_score,
                MIN(CASE priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END) as min_priority_order,
                MAX(created_at) as group_created_at
            FROM screening_queue q
            {where}
            GROUP BY entity_name, entity_type_norm
            ORDER BY {entity_sort}
            LIMIT %s OFFSET %s
        )
        SELECT q.*, u.email as assigned_email,
               TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS assigned_name,
               TRIM(COALESCE(ru.first_name,'') || ' ' || COALESCE(ru.last_name,'')) AS resolved_name,
               ru.email AS resolved_email,
               TRIM(COALESCE(iu.first_name,'') || ' ' || COALESCE(iu.last_name,'')) AS screened_by_name,
               CASE
                   WHEN EXTRACT(EPOCH FROM (NOW() - q.created_at::timestamp))/86400 > 3 THEN 'critical'
                   WHEN EXTRACT(EPOCH FROM (NOW() - q.created_at::timestamp))/86400 > 2 THEN 'overdue'
                   WHEN EXTRACT(EPOCH FROM (NOW() - q.created_at::timestamp))/86400 > 1 THEN 'aging'
                   ELSE 'ok'
               END as age_status
        FROM screening_queue q
        JOIN entity_page ep ON q.entity_name = ep.entity_name 
             AND COALESCE(q.entity_type, 'Individual') = ep.entity_type_norm
        LEFT JOIN users u ON q.assigned_to = u.id
        LEFT JOIN users ru ON q.resolved_by = ru.id
        LEFT JOIN screening_history sh ON q.screening_history_id = sh.id
        LEFT JOIN users iu ON sh.initiated_by = iu.id
        ORDER BY {entity_sort.replace('min_priority_order', 'ep.min_priority_order').replace('max_score', 'ep.max_score').replace('group_created_at', 'ep.group_created_at').replace('entity_name', 'ep.entity_name')}, 
                 q.match_score DESC
    """, params + [per_page, offset])

    # Stats
    stats = query_db("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN status = 'In Review' THEN 1 ELSE 0 END) as in_review,
            SUM(CASE WHEN status = 'Resolved' THEN 1 ELSE 0 END) as resolved,
            SUM(CASE WHEN EXTRACT(EPOCH FROM (NOW() - created_at::timestamp))/86400 > 1 AND status != 'Resolved' THEN 1 ELSE 0 END) as aging
        FROM screening_queue
    """, one=True)

    # Compliance officers for assignment dropdown
    officers = query_db("SELECT id, email, (first_name || ' ' || last_name) as full_name FROM users WHERE is_active = 1 ORDER BY first_name")

    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return render_template('screening/queue.html',
        items=items, stats=stats, officers=officers,
        page=page, total_pages=total_pages, total_count=total_count,
        status_filter=status_filter, priority_filter=priority_filter,
        source_filter=source_filter, assigned_filter=assigned_filter,
        sort=sort_by, order=order, per_page=per_page
    )


@screening_bp.route('/queue/<int:id>/review', methods=['GET', 'POST'])
@login_required
@permission_required('screening', level='edit')
@permission_required('screening', level='view')
def queue_review(id):
    """Review a specific queue item with action buttons."""
    # Resolve the three accountability roles to real people rather than
    # rendering a raw id as "User #5":
    #   iu = who ran the screening, u = who it is assigned to,
    #   ru = who dispositioned it (false positive / real match).
    item = query_db("""
        SELECT q.*,
               TRIM(COALESCE(u.first_name,'')  || ' ' || COALESCE(u.last_name,''))  AS assigned_name,
               u.email  AS assigned_email,
               TRIM(COALESCE(ru.first_name,'') || ' ' || COALESCE(ru.last_name,'')) AS resolved_name,
               ru.email AS resolved_email,
               TRIM(COALESCE(iu.first_name,'') || ' ' || COALESCE(iu.last_name,'')) AS screened_by_name,
               iu.email AS screened_by_email,
               sh.created_at AS screened_at
          FROM screening_queue q
          LEFT JOIN users u  ON q.assigned_to = u.id
          LEFT JOIN users ru ON q.resolved_by = ru.id
          LEFT JOIN screening_history sh ON q.screening_history_id = sh.id
          LEFT JOIN users iu ON sh.initiated_by = iu.id
         WHERE q.id = %s
    """, (id,), one=True)
    if not item:
        flash('Queue item not found.', 'error')
        return redirect(url_for('screening.screening_queue'))
    
    # Parse match_details JSON
    match_details = {}
    if item['match_details']:
        try:
            match_details = json.loads(item['match_details'])
        except (json.JSONDecodeError, TypeError):
            pass

    if request.method == 'POST':
        action = request.form.get('resolution')  # false_positive, true_match, pep, escalate
        notes = request.form.get('resolution_notes', '')

        if action == 'false_positive':
            # Mark resolved + optionally whitelist
            execute_db("""
                UPDATE screening_queue
                SET status = 'Resolved', resolution = 'False Positive', resolution_notes = %s,
                    resolved_by = %s, resolved_date = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (notes, current_user.id, id))

            # Auto-add to whitelist. ON CONFLICT matches
            # idx_screening_whitelist_norm (unique on normalized_name) — a
            # name screened more than once (any entity with 2+ pending hits
            # against the same name, or simply screened again later) would
            # otherwise crash here with a duplicate-key error on the second
            # false-positive, since this was an unconditional INSERT.
            execute_db("""
                INSERT INTO screening_whitelist
                    (name, normalized_name, reason, added_by, entity_type,
                     original_match_name, original_match_score, original_list_source, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Active')
                ON CONFLICT (normalized_name) WHERE normalized_name IS NOT NULL
                DO UPDATE SET reason = EXCLUDED.reason
            """, (
                item['entity_name'],
                item['entity_name'].upper().strip(),
                f"Whitelisted from queue review: {notes}",
                current_user.id,
                item['entity_type'] or 'Individual',
                item['match_name'],
                item['match_score'],
                item['list_source']
            ))
            flash('Marked as False Positive and added to whitelist.', 'success')

        elif action == 'true_match':
            execute_db("""
                UPDATE screening_queue
                SET status = 'Resolved', resolution = 'True Match - Block', resolution_notes = %s,
                    resolved_by = %s, resolved_date = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (notes, current_user.id, id))

            # Add to internal blacklist
            execute_db("""
                INSERT INTO internal_blacklist
                    (full_name, entity_type, reason, risk_level, category, source,
                     added_by, added_date, is_active, confirmation_type)
                VALUES (%s, %s, %s, 'HIGH', 'Sanctions Match', %s, %s, CURRENT_TIMESTAMP, 1,
                        'TEAM_CONFIRMED')
            """, (
                item['entity_name'],
                item['entity_type'] or 'Individual',
                f"True sanctions match ({item['list_source']}, score: {item['match_score']}%): {notes}",
                item['list_source'],
                current_user.id
            ))

            # Update source record screening status if linked
            _update_source_screening_status(item, 'Blocked')

            flash('Confirmed as True Match. Entity blocked and added to internal blacklist.', 'danger')

        elif action == 'pep':
            execute_db("""
                UPDATE screening_queue
                SET status = 'Resolved', resolution = 'PEP - Flag', resolution_notes = %s,
                    resolved_by = %s, resolved_date = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (notes, current_user.id, id))

            # Add to PEP database
            execute_db("""
                INSERT INTO pep_database
                    (full_name, risk_level, source_list, is_active, created_at)
                VALUES (%s, 'HIGH', %s, 1, CURRENT_TIMESTAMP)
            """, (item['entity_name'], item['list_source']))

            # Update source record
            _update_source_screening_status(item, 'PEP')

            flash('Entity flagged as PEP. Enhanced Due Diligence required.', 'warning')

        elif action == 'escalate':
            escalate_to = request.form.get('escalate_to')
            execute_db("""
                UPDATE screening_queue
                SET status = 'Pending', escalated = 1, escalation_reason = %s,
                    assigned_to = %s, resolution_notes = %s
                WHERE id = %s
            """, (notes, escalate_to, notes, id))
            flash('Case escalated to senior compliance officer.', 'info')
            return redirect(url_for('screening.screening_queue'))

        # Close the alerts generated for this entity's screening (Rec #5)
        _close_linked_alerts(item['entity_name'], action, notes, current_user.id)

        # Update screening_history
        if item['screening_history_id']:
            execute_db("""
                UPDATE screening_history
                SET status = 'Completed', resolution_date = CURRENT_TIMESTAMP, resolved_by = %s
                WHERE id = %s
            """, (current_user.id, item['screening_history_id']))

        return redirect(url_for('screening.screening_queue'))

    # GET: show review form
    history = None
    if item['screening_history_id']:
        history = query_db("SELECT * FROM screening_history WHERE id = %s",
                           (item['screening_history_id'],), one=True)

    officers = query_db("SELECT id, email, (first_name || ' ' || last_name) as full_name FROM users WHERE is_active = 1 ORDER BY first_name")

    return render_template('screening/queue_review.html',
        item=item, history=history, officers=officers, match_details=match_details)


def _close_linked_alerts(entity_name, resolution, notes, user_id):
    """Auto-disposition AML alerts when their screening is resolved (2026-07-21,
    screening Rec #5). Alerts are created automatically by a DB trigger on
    every screening result, but until now nothing ever closed them - 100% of
    alerts stayed OPEN forever, which reads to an examiner as alerts being
    generated but not managed. Closing them at the moment the analyst
    dispositions the underlying screening keeps the alert lifecycle honest
    without adding a second manual step."""
    try:
        status = 'ESCALATED' if resolution == 'escalate' else 'CLOSED'
        fp = 1 if resolution == 'false_positive' else 0
        execute_db("""
            UPDATE aml_alerts
            SET alert_status = %s, false_positive = %s, resolved_by = %s,
                resolved_at = to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
                resolution_notes = %s,
                updated_at = to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')
            WHERE alert_status = 'OPEN'
              AND screening_result_id IN (
                  SELECT id FROM screening_results WHERE screened_name = %s
              )
        """, (status, fp, user_id,
              f"Auto-{status.lower()} via queue resolution ({resolution}): {notes or ''}",
              entity_name))
    except Exception as e:
        logger.error(f"_close_linked_alerts failed for {entity_name!r}: {e}")


def _update_source_screening_status(queue_item, new_status):
    """Update the screening_status of the original merchant/customer record."""
    if queue_item['source_module'] == 'Merchant KYC' and queue_item['source_record_id']:
        execute_db("""
            UPDATE merchants SET screening_status = %s, last_screening_date = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (new_status, queue_item['source_record_id']))
    elif queue_item['source_module'] == 'Customer KYC' and queue_item['source_record_id']:
        execute_db("""
            UPDATE customers SET screening_status = %s, last_screening_date = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (new_status, queue_item['source_record_id']))
    elif queue_item['source_module'] == 'eKYC' and queue_item['source_record_id']:
        _update_ekyc_session_screening_status(queue_item['source_record_id'], new_status)


def _update_ekyc_session_screening_status(session_id, new_status):
    """
    Routes a resolved eKYC screening_queue item back onto its ekyc_session.
    A confirmed sanctions match blocks onboarding outright (REJECTED)
    regardless of any other pending hit on the same session; everything
    else (false-positive cleared, PEP accepted with EDD) only advances the
    session to DECISION_PENDING once no other eKYC hit is still pending —
    an officer still makes the final Approve/Reject call either way (see
    ekyc/routes.py's session_decision), this only clears screening as a
    blocker to reaching that decision.
    """
    if new_status == 'Blocked':
        execute_db("""
            UPDATE ekyc_session
            SET status = 'REJECTED', final_decision = 'REJECTED', decided_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status NOT IN ('REJECTED', 'ONBOARDED')
        """, (session_id,))
        return

    remaining_pending = query_db("""
        SELECT COUNT(*) AS c FROM screening_queue
        WHERE source_module = 'eKYC' AND source_record_id = %s AND status != 'Resolved'
    """, (session_id,), one=True)
    if remaining_pending and remaining_pending['c'] == 0:
        execute_db("""
            UPDATE ekyc_session SET status = 'DECISION_PENDING'
            WHERE id = %s AND status NOT IN ('REJECTED', 'APPROVED', 'ONBOARDED')
        """, (session_id,))


@screening_bp.route('/queue/<int:id>/assign', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
@permission_required('screening', level='view')
def queue_assign(id):
    """Assign a queue item to a compliance officer."""
    assigned_to = request.form.get('assigned_to', type=int)
    execute_db("UPDATE screening_queue SET assigned_to = %s, status = 'In Review' WHERE id = %s",
               (assigned_to, id))
    flash('Case assigned successfully.', 'success')
    return redirect(url_for('screening.screening_queue'))


@screening_bp.route('/queue/bulk-resolve', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
@permission_required('screening', level='view')
def queue_bulk_resolve():
    """Resolve multiple queue items at once."""
    action = request.form.get('action') # false_positive, true_match
    notes = request.form.get('resolution_notes', '')
    selected_ids_str = request.form.get('selected_ids', '')
    
    if not selected_ids_str:
        flash('No items selected.', 'warning')
        return redirect(url_for('screening.screening_queue'))
        
    try:
        selected_ids = [int(id) for id in selected_ids_str.split(',') if id]
    except ValueError:
        flash('Invalid selection.', 'error')
        return redirect(url_for('screening.screening_queue'))

    processed_count = 0
    
    for id in selected_ids:
        # Get item details
        item = query_db("SELECT * FROM screening_queue WHERE id = %s", (id,), one=True)
        if not item or item['status'] == 'Resolved':
            continue

        if action == 'false_positive':
            # 1. Update queue item
            execute_db("""
                UPDATE screening_queue
                SET status = 'Resolved', resolution = 'False Positive (Bulk)', resolution_notes = %s,
                    resolved_by = %s, resolved_date = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (notes, current_user.id, id))
            
            # 2. Add to whitelist (auto). ON CONFLICT matches
            # idx_screening_whitelist_norm (unique on normalized_name) —
            # bulk-resolving 2+ selected items that share the same entity
            # name (the normal case: one entity often has several fuzzy
            # matches) previously crashed the whole request on the second
            # item's insert with a duplicate-key error, silently leaving
            # every item after it unresolved.
            execute_db("""
                INSERT INTO screening_whitelist
                    (name, normalized_name, reason, added_by, entity_type,
                     original_match_name, original_match_score, original_list_source, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Active')
                ON CONFLICT (normalized_name) WHERE normalized_name IS NOT NULL
                DO UPDATE SET reason = EXCLUDED.reason
            """, (
                item['entity_name'],
                item['entity_name'].upper().strip(),
                f"Whitelisted via Bulk Action: {notes}",
                current_user.id,
                item['entity_type'] or 'Individual',
                item['match_name'],
                item['match_score'],
                item['list_source']
            ))

            # 3. Update source status
            if item['source_module']:
                _update_source_screening_status(item, 'Whitelisted')

        elif action == 'true_match':
            # 1. Update queue item
            execute_db("""
                UPDATE screening_queue
                SET status = 'Resolved', resolution = 'True Match - Block (Bulk)', resolution_notes = %s,
                    resolved_by = %s, resolved_date = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (notes, current_user.id, id))
            
            # 2. Add to Blacklist
            execute_db("""
                INSERT INTO internal_blacklist
                    (full_name, entity_type, reason, risk_level, category, source,
                     added_by, added_date, is_active, confirmation_type)
                VALUES (%s, %s, %s, 'HIGH', 'Sanctions Match', %s, %s, CURRENT_TIMESTAMP, 1,
                        'TEAM_CONFIRMED')
            """, (
                item['entity_name'],
                item['entity_type'] or 'Individual',
                f"True match confirmed via Bulk Action: {notes}",
                item['list_source'],
                current_user.id
            ))
            
            # 3. Update source status
            if item['source_module']:
                _update_source_screening_status(item, 'Blocked')

        # 4. Update History
        if item['screening_history_id']:
             execute_db("""
                UPDATE screening_history
                SET status = 'Completed', resolution_date = CURRENT_TIMESTAMP, resolved_by = %s
                WHERE id = %s
            """, (current_user.id, item['screening_history_id']))
            
        _close_linked_alerts(item['entity_name'], action, notes, current_user.id)
        processed_count += 1

    flash(f'Successfully resolved {processed_count} items.', 'success')
    return redirect(url_for('screening.screening_queue'))
def _save_screening_result(name, entity_type, dob, nationality, source_module, source_record_id, result, user_id, screening_type='API'):
    """
    Helper to save screening result to history, results, and queue.
    Returns: history_id
    """
    matches = result.get('matches', [])
    total_matches = result.get('total_matches', len(matches))
    highest_score = result.get('highest_score', 0.0)
    
    # Categorize matches
    # Use the threshold defined at line ~1527
    high_risk = [m for m in matches if m.get('match_score', 0) >= HIGH_RISK_THRESHOLD]
    auto_cleared = [m for m in matches if m.get('match_score', 0) < HIGH_RISK_THRESHOLD]

    # Determine status
    if result.get('screening_result') == 'WHITE_LISTED':
        status = 'Completed'
        screening_result = 'WHITE_LISTED'
    elif high_risk:
        status = 'Pending Review'
        screening_result = 'POTENTIAL_MATCH'
    else:
        status = 'Completed'
        screening_result = 'CLEAR'

    # Save to screening_history
    param = get_param_style()
    execute_db(f"""
        INSERT INTO screening_history
            (entity_name, entity_type, screening_type, initiated_by,
             source_module, source_record_id, total_matches_found,
             high_risk_matches, auto_cleared_matches, highest_score,
             screening_result, matches_json, status, processing_time_ms)
        VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})
    """, (
        name, entity_type, screening_type,
        user_id, source_module, source_record_id,
        total_matches, len(high_risk), len(auto_cleared),
        highest_score, screening_result,
        json.dumps({
            'matches': matches,
            'adverse_media': result.get('adverse_media', []),
            'adverse_media_summary': result.get('adverse_media_summary', {}),
            'search_degraded': bool(result.get('search_degraded', False))
        }), status,
        result.get('processing_time_ms', 0)
    ))

    # Get the history ID
    history_row = query_db(f"SELECT id FROM screening_history WHERE entity_name = {param} AND initiated_by = {param} ORDER BY id DESC LIMIT 1", (name, user_id), one=True)
    history_id = history_row['id'] if history_row else None

    # Also save to screening_results for backward compat
    execute_db(f"""
        INSERT INTO screening_results (
            screening_type, screened_name, screened_dob,
            screening_method, total_matches_found, highest_match_score,
            screening_result, matches, adverse_media, adverse_media_summary,
            processing_time_ms, created_by, search_degraded, status
        ) VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, 'PENDING')
    """, (
        source_module.upper().replace(' ', '_'), name, dob, screening_type,
        total_matches, highest_score, screening_result,
        json.dumps(matches),
        json.dumps(result.get('adverse_media', [])),
        json.dumps(result.get('adverse_media_summary', {})),
        result.get('processing_time_ms', 0), user_id,
        1 if result.get('search_degraded') else 0
    ))

    # Tie the history row to the results row so an adjudication made on either
    # screen is visible on both. Without this, resolving from the result page
    # left Screening History showing nothing.
    if history_id:
        try:
            res_row = query_db(
                f"SELECT id FROM screening_results WHERE screened_name = {param} "
                f"AND created_by = {param} ORDER BY id DESC LIMIT 1",
                (name, user_id), one=True)
            if res_row:
                execute_db(
                    f"UPDATE screening_history SET screening_result_id = {param} "
                    f"WHERE id = {param}", (res_row['id'], history_id))
        except Exception as _e:
            logger.warning(f"Could not link history to result row: {_e}")

    # Create queue items for EVERY match, not just those above the high-risk
    # threshold. A sub-70 match was previously auto-cleared without a human
    # ever seeing it; priority (not visibility) is what should depend on score.
    if history_id:
        for match in matches:
            _score = match.get('match_score', 0) or 0
            if _score >= 90:
                priority = 'High'
            elif _score >= HIGH_RISK_THRESHOLD:
                priority = 'Medium'
            else:
                priority = 'Low'
            execute_db(f"""
                INSERT INTO screening_queue
                    (screening_history_id, entity_name, entity_type, match_name,
                     match_score, list_source, match_details, priority, status,
                     source_module, source_record_id, created_at)
                VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, 'Pending', {param}, {param}, CURRENT_TIMESTAMP)
            """, (
                history_id, name, entity_type,
                match.get('full_name', match.get('watchlist_name_ar', '')),
                match.get('match_score', 0),
                match.get('source', match.get('dataset', 'Unknown')),
                json.dumps(match),
                priority, source_module, source_record_id
            ))

        # Create queue item for Adverse Media if hits found
        adverse_media_hits = result.get('adverse_media', [])
        if adverse_media_hits:
            am_summary = result.get('adverse_media_summary', {})
            am_score = am_summary.get('risk_score', 0)
            priority = 'High' if am_score >= 20 else 'Medium'
            
            execute_db(f"""
                INSERT INTO screening_queue
                    (screening_history_id, entity_name, entity_type, match_name,
                     match_score, list_source, match_details, priority, status,
                     source_module, source_record_id, created_at)
                VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, 'Pending', {param}, {param}, CURRENT_TIMESTAMP)
            """, (
                history_id, name, entity_type,
                "Adverse Media Findings",
                am_score,
                "Adverse Media",
                json.dumps({'hits': adverse_media_hits}),
                priority, source_module, source_record_id
            ))

    # Update source record screening status
    if source_record_id:
        if source_module == 'Merchant KYC':
            ss = 'Pending Review' if high_risk else ('Whitelisted' if screening_result == 'WHITE_LISTED' else 'Clear')
            risk_rating = 'High' if high_risk else ('Low' if not matches else 'Medium')
            execute_db(f"""
                UPDATE merchants
                SET screening_status = {param}, last_screening_date = CURRENT_TIMESTAMP,
                    last_screened_by = {param}, risk_rating = {param}, sanctions_checked = 1
                WHERE id = {param}
            """, (ss, user_id, risk_rating, source_record_id))
        elif source_module == 'Customer KYC':
            ss = 'Pending Review' if high_risk else ('Whitelisted' if screening_result == 'WHITE_LISTED' else 'Clear')
            execute_db(f"""
                UPDATE customers
                SET screening_status = {param}, last_screening_date = CURRENT_TIMESTAMP,
                    last_screened_by = {param}
                WHERE id = {param}
            """, (ss, user_id, source_record_id))

    return history_id

@login_required
@permission_required('screening', level='edit')
def api_run_screening():
    """
    Unified screening API used by Merchant KYC and Customer KYC.
    Auto-scores results: <70% are auto-cleared, >=70% go to queue.
    Returns JSON with screening summary.
    """
    data = request.get_json() or request.form
    name = data.get('name')
    entity_type = data.get('entity_type', 'Individual')
    dob = data.get('date_of_birth')
    nationality = data.get('nationality')
    source_module = data.get('source_module', 'Manual Screening')
    source_record_id = data.get('source_record_id', type=int) if hasattr(data, 'get') else data.get('source_record_id')

    if not name:
        return jsonify({'success': False, 'error': 'Name is required'}), 400

    # Parse DOB
    formatted_dob = None
    if dob:
        try:
            formatted_dob = datetime.strptime(dob, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            pass

    # Run screening engine
    engine = get_engine()
    result = engine.screen_person(
        name=name,
        date_of_birth=formatted_dob,
        nationality=nationality,
        entity_type=entity_type.upper()
    )
    # engine.close()  # REMOVED: singleton must not be closed per-request
    pass

    matches = result.get('matches', [])
    total_matches = result.get('total_matches', len(matches))
    highest_score = result.get('highest_score', 0.0)

    history_id = _save_screening_result(
        name=name,
        entity_type=entity_type,
        dob=dob,
        nationality=nationality,
        source_module=source_module,
        source_record_id=source_record_id,
        result=result,
        user_id=current_user.id,
        screening_type=data.get('screening_type', 'API')
    )

    return jsonify({
        'success': True,
        'screening_id': history_id,
        'screening_result': screening_result,
        'status': status,
        'total_matches': total_matches,
        'high_risk_matches': len(high_risk),
        'auto_cleared_matches': len(auto_cleared),
        'highest_score': highest_score,
        'requires_review': len(high_risk) > 0,
        'queue_ids': queue_ids,
        'processing_time_ms': result.get('processing_time_ms', 0)
    })


@screening_bp.route('/history-full')
@login_required
@permission_required('screening')
@permission_required('screening', level='edit')
def screening_history_full():
    """Enhanced screening history with search, filters, and export."""
    search = request.args.get('search', '')
    source_filter = request.args.get('source_module', '')
    status_filter = request.args.get('status', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    export = request.args.get('export', '')
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    conditions = []
    params = []
    _order_sql, _sort_key, _sort_dir = _sort_clause(HIST_SORT, 'date')
    if search:
        conditions.append("h.entity_name LIKE %s")
        params.append(f"%{search}%")
    if source_filter:
        conditions.append("h.source_module = %s")
        params.append(source_filter)
    if status_filter:
        conditions.append("h.status = %s")
        params.append(status_filter)
    if date_from:
        conditions.append("h.screening_date >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("h.screening_date <= %s")
        params.append(date_to + ' 23:59:59')

    # Which list matched, and score floors — including a different floor per
    # list type, because a sanctions hit and a PEP hit do not warrant the same
    # threshold. matches_json holds the per-match detail.
    if request.args.get('list_source'):
        conditions.append("h.matches_json::text ILIKE %s")
        params.append(f"%{request.args['list_source']}%")
    if request.args.get('min_score'):
        conditions.append("h.highest_score >= %s")
        params.append(float(request.args['min_score']))
    if request.args.get('result'):
        conditions.append("h.screening_result = %s")
        params.append(request.args['result'])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Export to Excel
    if export == 'excel':
        rows = query_db(f"""
            SELECT h.*, u.email as initiated_by_email,
                   TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS initiated_by_name,
                   COALESCE(hres.decision, adj.decision) AS decision,
                   COALESCE(hres.decided_by_name, adj.decided_by_name) AS decided_by_name,
                   COALESCE(hres.decided_at, adj.decided_at) AS decided_at
            FROM screening_history h
            LEFT JOIN users u ON h.initiated_by = u.id
            -- Roll the linked review-queue rows up into one decision per
            -- screening: a confirmed true match outranks a false positive,
            -- and anything still unresolved stays Pending.
            LEFT JOIN LATERAL (
                SELECT
                    CASE
                        WHEN bool_or(q.resolution LIKE 'True Match%') THEN 'True Match'
                        WHEN bool_or(q.resolution LIKE 'PEP%') THEN 'PEP'
                        WHEN bool_or(q.resolution LIKE 'False Positive%') THEN 'False Positive'
                        WHEN count(*) > 0 THEN 'Pending'
                        ELSE NULL
                    END AS decision,
                    MAX(TRIM(COALESCE(ru.first_name,'') || ' ' || COALESCE(ru.last_name,''))) AS decided_by_name,
                    MAX(q.resolved_date::text) AS decided_at
                FROM screening_queue q
                LEFT JOIN users ru ON q.resolved_by = ru.id
                WHERE q.screening_history_id = h.id
            ) adj ON TRUE
            -- A decision taken on the screening RESULT page lands on the
            -- history row itself; it takes precedence over the queue rollup.
            LEFT JOIN LATERAL (
                SELECT CASE h.status
                           WHEN 'TRUE_HIT' THEN 'True Match'
                           WHEN 'FALSE_POSITIVE' THEN 'False Positive'
                           ELSE NULL
                       END AS decision,
                       TRIM(COALESCE(hu.first_name,'') || ' ' || COALESCE(hu.last_name,'')) AS decided_by_name,
                       h.resolution_date::text AS decided_at
                  FROM users hu
                 WHERE hu.id = h.resolved_by
            ) hres ON TRUE
            {where}
            ORDER BY {_order_sql}
        """, params)
        return _export_history_excel(rows)

    total_res = query_db(f"SELECT COUNT(*) as cnt FROM screening_history h {where}", params, one=True)
    total_count = total_res['cnt'] if total_res else 0

    records = query_db(f"""
        SELECT h.*, u.email as initiated_by_email,
               TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS initiated_by_name,
               COALESCE(hres.decision, adj.decision) AS decision,
               COALESCE(hres.decided_by_name, adj.decided_by_name) AS decided_by_name,
               COALESCE(hres.decided_at, adj.decided_at) AS decided_at
        FROM screening_history h
        LEFT JOIN users u ON h.initiated_by = u.id
        -- Decision taken on the screening RESULT page (lands on history itself).
        LEFT JOIN LATERAL (
            SELECT CASE h.status
                       WHEN 'TRUE_HIT' THEN 'True Match'
                       WHEN 'FALSE_POSITIVE' THEN 'False Positive'
                       ELSE NULL
                   END AS decision,
                   TRIM(COALESCE(hu.first_name,'') || ' ' || COALESCE(hu.last_name,'')) AS decided_by_name,
                   h.resolution_date::text AS decided_at
              FROM users hu
             WHERE hu.id = h.resolved_by
        ) hres ON TRUE
        -- Otherwise roll up the linked review-queue rows: a confirmed true
        -- match outranks a false positive; unresolved items stay Pending.
        LEFT JOIN LATERAL (
            SELECT CASE
                       WHEN bool_or(q.resolution LIKE 'True Match%%') THEN 'True Match'
                       WHEN bool_or(q.resolution LIKE 'PEP%%') THEN 'PEP'
                       WHEN bool_or(q.resolution LIKE 'False Positive%%') THEN 'False Positive'
                       WHEN count(*) > 0 THEN 'Pending'
                       ELSE NULL
                   END AS decision,
                   MAX(TRIM(COALESCE(ru.first_name,'')||' '||COALESCE(ru.last_name,''))) AS decided_by_name,
                   MAX(q.resolved_date::text) AS decided_at
              FROM screening_queue q
              LEFT JOIN users ru ON q.resolved_by = ru.id
             WHERE q.screening_history_id = h.id
        ) adj ON TRUE
        {where}
        ORDER BY {_order_sql}
        LIMIT %s OFFSET %s
    """, params + [per_page, offset])

    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return render_template('screening/screening_history_full.html',
        records=records, page=page, total_pages=total_pages,
        total_count=total_count, search=search,
        source_filter=source_filter, status_filter=status_filter,
        date_from=date_from, date_to=date_to
    )


@screening_bp.route('/history/<int:id>')
@login_required
@permission_required('screening')
def screening_history_detail(id):
    """View detailed results for a specific screening history record."""
    record = query_db("SELECT h.*, u.email as initiated_by_email FROM screening_history h LEFT JOIN users u ON h.initiated_by = u.id WHERE h.id = %s", (id,), one=True)
    if not record:
        flash('Screening record not found.', 'danger')
        return redirect(url_for('screening.screening_history_full'))
    
    record = dict(record)
    
    # Parse matches_json
    matches = []
    adverse_media = []
    if record.get('matches_json'):
        try:
            data = json.loads(record['matches_json'])
            if isinstance(data, dict):
                matches = data.get('matches', [])
                adverse_media = data.get('adverse_media', [])
            elif isinstance(data, list):
                matches = data
        except (json.JSONDecodeError, TypeError):
            pass
    
    return render_template('screening/screening_history_detail.html',
        record=record, matches=matches, adverse_media=adverse_media)


def _export_history_excel(rows):
    """Export screening history as Excel file."""
    import io
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Screening History"
        headers = ['ID', 'Entity Name', 'Entity Type', 'Date', 'Type',
                   'Source Module', 'Total Matches', 'High Risk', 'Auto-Cleared',
                   'Highest Score', 'Result', 'Status', 'Initiated By']
        ws.append(headers)
        for r in rows:
            ws.append([
                r['id'], r['entity_name'], r['entity_type'],
                r['screening_date'], r['screening_type'],
                r['source_module'], r['total_matches_found'],
                r['high_risk_matches'], r['auto_cleared_matches'],
                r['highest_score'], r['screening_result'],
                r['status'], r.get('initiated_by_email', '')
            ])
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True,
                         download_name='screening_history.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except ImportError:
        # Fallback to CSV
        output = io.StringIO()
        import csv
        writer = csv.writer(output)
        writer.writerow(['ID', 'Entity Name', 'Entity Type', 'Date', 'Type',
                         'Source Module', 'Total Matches', 'High Risk', 'Status'])
        for r in rows:
            writer.writerow([r['id'], r['entity_name'], r['entity_type'],
                             r['screening_date'], r['screening_type'],
                             r['source_module'], r['total_matches_found'],
                             r['high_risk_matches'], r['status']])
        return Response(output.getvalue(), mimetype='text/csv',
                        headers={"Content-disposition": "attachment; filename=screening_history.csv"})


# --- Enhanced Whitelist ---

@screening_bp.route('/whitelist/<int:id>/revoke', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def revoke_whitelist(id):
    """Revoke a whitelist entry.

    Was registered at '/screening/whitelist/...' on a blueprint already mounted
    at /screening, producing /screening/screening/whitelist/... — reachable via
    url_for but broken for any hard-coded link.

    A whitelist entry suppresses sanctions alerts, so revoking one is a
    compliance decision: the operator's reason is captured and an audit row is
    written. The engine reads status='Active', so this takes effect on the very
    next screening run.
    """
    row = query_db("SELECT id, name, status FROM screening_whitelist WHERE id = %s",
                   (id,), one=True)
    if not row:
        flash('Whitelist entry not found.', 'danger')
        return redirect(url_for('screening.manage_whitelist'))

    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash('A reason is required to revoke a whitelist entry.', 'danger')
        return redirect(url_for('screening.manage_whitelist'))

    execute_db("UPDATE screening_whitelist SET status = 'Revoked', notes = %s WHERE id = %s",
               (reason, id))
    execute_db("""INSERT INTO screening_whitelist_audit
                     (whitelist_id, entry_name, action, previous_status, new_status,
                      reason, performed_by)
                  VALUES (%s, %s, 'revoked', %s, 'Revoked', %s, %s)""",
               (id, row['name'], row['status'], reason, current_user.id))
    flash(f'Whitelist entry "{row["name"]}" revoked. It will be screened normally from now on.',
          'warning')
    return redirect(url_for('screening.manage_whitelist'))


@screening_bp.route('/whitelist/<int:id>/reinstate', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def reinstate_whitelist(id):
    """Reinstate a revoked or quarantined entry.

    Quarantined entries are the ones whose name matches an active watchlist
    record. Reinstating one means deliberately suppressing a sanctions alert,
    so the justification is mandatory and permanently recorded.
    """
    row = query_db("SELECT id, name, status FROM screening_whitelist WHERE id = %s",
                   (id,), one=True)
    if not row:
        flash('Whitelist entry not found.', 'danger')
        return redirect(url_for('screening.manage_whitelist'))

    reason = (request.form.get('reason') or '').strip()
    if len(reason) < 15:
        flash('Reinstating a whitelist entry suppresses screening alerts. '
              'Please record a specific justification (at least 15 characters).', 'danger')
        return redirect(url_for('screening.manage_whitelist'))

    execute_db("UPDATE screening_whitelist SET status = 'Active', notes = %s WHERE id = %s",
               (reason, id))
    execute_db("""INSERT INTO screening_whitelist_audit
                     (whitelist_id, entry_name, action, previous_status, new_status,
                      reason, performed_by)
                  VALUES (%s, %s, 'reinstated', %s, 'Active', %s, %s)""",
               (id, row['name'], row['status'], reason, current_user.id))
    flash(f'"{row["name"]}" reinstated on the whitelist. Screening alerts for this '
          f'name will now be suppressed.', 'warning')
    return redirect(url_for('screening.manage_whitelist'))




@screening_bp.route('/internal-pep/export')
@login_required
@permission_required('screening', level='view')
def export_internal_pep():
    """Download internal PEP list as Excel"""
    import io
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        flash('openpyxl not installed', 'danger')
        return redirect(url_for('blacklist.pep_index'))

    rows = query_db("""
        SELECT id, full_name, original_name, entity_type, national_id,
               date_of_birth, nationality, country, position, category,
               risk_level, reason, source, added_date
        FROM internal_pep WHERE is_active = 1
        ORDER BY full_name
    """)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Internal PEP List'

    headers = ['ID', 'Full Name (EN)', 'Full Name (AR)', 'Type', 'National ID',
               'Date of Birth', 'Nationality', 'Country', 'Position',
               'Category', 'Risk Level', 'Reason', 'Source', 'Added Date']

    header_fill = PatternFill(start_color='1B3A6B', end_color='1B3A6B', fill_type='solid')
    header_font = Font(color='FFFFFF', bold=True)

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')

    for row_idx, row in enumerate(rows, 2):
        ws.cell(row=row_idx, column=1, value=row['id'])
        ws.cell(row=row_idx, column=2, value=row['full_name'])
        ws.cell(row=row_idx, column=3, value=row['original_name'])
        ws.cell(row=row_idx, column=4, value=row['entity_type'])
        ws.cell(row=row_idx, column=5, value=row['national_id'])
        ws.cell(row=row_idx, column=6, value=row['date_of_birth'])
        ws.cell(row=row_idx, column=7, value=row['nationality'])
        ws.cell(row=row_idx, column=8, value=row['country'])
        ws.cell(row=row_idx, column=9, value=row['position'])
        ws.cell(row=row_idx, column=10, value=row['category'])
        ws.cell(row=row_idx, column=11, value=row['risk_level'])
        ws.cell(row=row_idx, column=12, value=row['reason'])
        ws.cell(row=row_idx, column=13, value=row['source'])
        ws.cell(row=row_idx, column=14, value=row['added_date'])

    for col in ws.columns:
        max_length = max((len(str(cell.value or '')) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_length + 4, 40)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    from flask import send_file
    from datetime import datetime
    filename = f"internal_pep_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(output, download_name=filename,
                     as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@screening_bp.route('/whitelist/export')
@login_required
@permission_required('screening')
def export_whitelist():
    """Export whitelist to Excel/CSV."""
    rows = query_db("SELECT * FROM screening_whitelist ORDER BY added_at DESC")

    import io
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Whitelist"
        headers = ['ID', 'Name', 'Entity Type', 'Reason', 'Status',
                   'Original Match', 'Score', 'List Source',
                   'Added By', 'Added At', 'Approved By', 'Review Date']
        ws.append(headers)
        for r in rows:
            ws.append([
                r['id'], r['name'], r.get('entity_type', ''),
                r['reason'], r.get('status', 'Active'),
                r.get('original_match_name', ''), r.get('original_match_score', ''),
                r.get('original_list_source', ''),
                r['added_by'], r['added_at'],
                r.get('approved_by', ''), r.get('review_date', '')
            ])
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True,
                         download_name='whitelist_export.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except ImportError:
        output = io.StringIO()
        import csv
        writer = csv.writer(output)
        writer.writerow(['ID', 'Name', 'Entity Type', 'Reason', 'Status', 'Added By', 'Added At'])
        for r in rows:
            writer.writerow([r['id'], r['name'], r.get('entity_type', ''),
                             r['reason'], r.get('status', 'Active'),
                             r['added_by'], r['added_at']])
        return Response(output.getvalue(), mimetype='text/csv',
                        headers={"Content-disposition": "attachment; filename=whitelist_export.csv"})


# ============================================================================
# AML ALERT MANAGEMENT (2026-07-21, screening Rec #5)
# The aml_alerts table is populated automatically by a DB trigger on every
# screening result, but had no UI at all - alerts were write-only and 100%
# of them stayed OPEN forever. These routes give the compliance team a
# proper alert lifecycle: triage list with SLA aging, individual
# disposition, bulk disposition, and a one-click backlog cleanup for alerts
# whose underlying screening was already resolved through the queue.
# ============================================================================

@screening_bp.route('/alerts')
@login_required
@permission_required('screening', level='view')
def alerts_list():
    status_filter = request.args.get('status', 'OPEN')
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    where = ""
    params = []
    if status_filter and status_filter != 'ALL':
        where = "WHERE alert_status = %s"
        params.append(status_filter)

    total_res = query_db(f"SELECT COUNT(*) AS cnt FROM aml_alerts {where}", params, one=True)
    total_count = total_res['cnt'] if total_res else 0

    alerts = query_db(f"""
        SELECT a.*, u.email AS resolved_by_email,
               GREATEST(0, EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - a.created_at::timestamp)) / 86400)::int AS age_days
        FROM aml_alerts a
        LEFT JOIN users u ON a.resolved_by = u.id
        {where}
        ORDER BY a.created_at DESC
        LIMIT %s OFFSET %s
    """, params + [per_page, offset])

    counts = query_db("""
        SELECT alert_status, COUNT(*) AS cnt FROM aml_alerts GROUP BY alert_status
    """)
    status_counts = {r['alert_status']: r['cnt'] for r in (counts or [])}

    total_pages = max(1, (total_count + per_page - 1) // per_page)
    return render_template('screening/alerts.html',
        alerts=alerts, page=page, total_pages=total_pages,
        status_filter=status_filter, status_counts=status_counts,
        total_count=total_count)


@screening_bp.route('/alerts/<int:alert_id>/disposition', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def alert_disposition(alert_id):
    action = request.form.get('action')  # close_false_positive, close_resolved, escalate
    notes = request.form.get('notes', '')
    mapping = {
        'close_false_positive': ('CLOSED', 1),
        'close_resolved': ('CLOSED', 0),
        'escalate': ('ESCALATED', 0),
    }
    if action not in mapping:
        flash('Invalid action.', 'error')
        return redirect(url_for('screening.alerts_list'))
    status, fp = mapping[action]
    execute_db("""
        UPDATE aml_alerts
        SET alert_status = %s, false_positive = %s, resolved_by = %s,
            resolved_at = to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
            resolution_notes = %s,
            updated_at = to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')
        WHERE id = %s
    """, (status, fp, current_user.id, notes, alert_id))
    try:
        from models.audit import AuditLog
        AuditLog.log(current_user.id, 'Screening', 'AML Alert', alert_id,
                     f"Alert #{alert_id} dispositioned: {action}. Notes: {notes}", request.remote_addr)
    except Exception:
        pass
    flash(f'Alert #{alert_id} updated.', 'success')
    return redirect(url_for('screening.alerts_list'))


@screening_bp.route('/alerts/bulk-disposition', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def alerts_bulk_disposition():
    if not current_user.is_admin() and not current_user.is_compliance_officer():
        flash('Access denied.', 'error')
        return redirect(url_for('screening.alerts_list'))
    action = request.form.get('action')
    notes = request.form.get('notes', '')
    ids_str = request.form.get('selected_ids', '')

    if action == 'cleanup_resolved':
        # Backlog cleanup: close OPEN alerts whose entity was already
        # dispositioned through the review queue (a Resolved queue item
        # exists for the same entity name) - these are historical alerts
        # from before the alert lifecycle existed.
        execute_db("""
            UPDATE aml_alerts a
            SET alert_status = 'CLOSED', resolved_by = %s,
                resolved_at = to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
                resolution_notes = %s,
                updated_at = to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')
            WHERE a.alert_status = 'OPEN'
              AND EXISTS (
                  SELECT 1 FROM screening_queue q
                  WHERE q.status = 'Resolved'
                    AND q.entity_name = (
                        SELECT r.screened_name FROM screening_results r
                        WHERE r.id = a.screening_result_id
                    )
              )
        """, (current_user.id,
              f"Backlog cleanup: underlying screening already resolved via queue. {notes}"))
        flash('Backlog cleanup completed: alerts with already-resolved screenings closed.', 'success')
        return redirect(url_for('screening.alerts_list'))

    try:
        ids = [int(x) for x in ids_str.split(',') if x.strip()]
    except ValueError:
        ids = []
    if not ids:
        flash('No alerts selected.', 'warning')
        return redirect(url_for('screening.alerts_list'))

    status = 'CLOSED' if action in ('close_false_positive', 'close_resolved') else 'ESCALATED'
    fp = 1 if action == 'close_false_positive' else 0
    execute_db("""
        UPDATE aml_alerts
        SET alert_status = %s, false_positive = %s, resolved_by = %s,
            resolved_at = to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
            resolution_notes = %s,
            updated_at = to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')
        WHERE id = ANY(%s) AND alert_status != 'CLOSED'
    """, (status, fp, current_user.id, f"Bulk disposition ({action}): {notes}", ids))
    flash(f'{len(ids)} alert(s) updated.', 'success')
    return redirect(url_for('screening.alerts_list'))


# =============================================================================
# Ongoing sanctions screening
# =============================================================================

@screening_bp.route('/ongoing')
@login_required
@permission_required('ongoing_screening')
def ongoing_screening_dashboard():
    from services import ongoing_screening as OS
    from database.db import query_db
    return render_template(
        'screening/ongoing.html',
        config=query_db("""SELECT c.*,
                     TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS configured_by_name
                   FROM ongoing_screening_config c
                   LEFT JOIN users u ON u.id = c.configured_by
                   ORDER BY c.id"""),
        criteria_count=dict(query_db("SELECT count(*) AS c FROM screening_risk_criteria "
                                     "WHERE is_active", one=True))['c'],
        runs=OS.recent_runs(10),
        findings=OS.open_findings(100),
        frequencies=['daily', 'weekly', 'monthly', 'quarterly', 'yearly', 'manual'],
        summary=query_db("""
            SELECT count(*) FILTER (WHERE scope='match_set')                    AS monitored,
                   count(*) FILTER (WHERE scope='name' AND status='Active')     AS legacy,
                   count(*) FILTER (WHERE status='Requires Review')             AS quarantined,
                   COALESCE(sum(cleared_match_count),0)                         AS cleared_matches,
                   count(*) FILTER (WHERE scope='match_set'
                                    AND next_screening_at <= NOW())             AS due_now
            FROM screening_whitelist""", one=True),
        can_edit=current_user.can_edit('screening'))


@screening_bp.route('/ongoing/config', methods=['POST'])
@login_required
@permission_required('ongoing_screening', level='edit')
def ongoing_screening_config():
    from database.db import execute_db
    rationale = (request.form.get('rationale') or '').strip()
    if len(rationale) < 10:
        flash('Please record why these cadences were chosen. A screening frequency '
              'is a control decision and needs an owner and a rationale.', 'danger')
        return redirect(url_for('screening.ongoing_screening_dashboard'))

    saved = 0
    for key, val in request.form.items():
        if not key.startswith('freq_') or not val:
            continue
        execute_db("""UPDATE ongoing_screening_config
                         SET frequency=%s, is_configured=TRUE,
                             configured_by=%s, configured_at=NOW(),
                             rationale=%s, updated_by=%s, updated_at=NOW()
                       WHERE id=%s""",
                   (val, current_user.id, rationale, current_user.id, key[5:]))
        saved += 1
    if not saved:
        flash('No cadence was selected.', 'warning')
        return redirect(url_for('screening.ongoing_screening_dashboard'))
    # Changing a band's cadence should take effect now, not at the next run —
    # otherwise a shortened cycle silently waits out the old one.
    execute_db("""UPDATE screening_whitelist SET next_screening_at = NOW()
                   WHERE scope='match_set' AND screening_frequency <> 'manual'
                     AND next_screening_at > NOW() + interval '400 days'""")
    flash(f'{saved} cadence(s) set by {current_user.first_name} {current_user.last_name}. '
          f'Recorded with your rationale.', 'success')
    return redirect(url_for('screening.ongoing_screening_dashboard'))


@screening_bp.route('/ongoing/run', methods=['POST'])
@login_required
@permission_required('ongoing_screening', level='edit')
def ongoing_screening_run():
    from services import ongoing_screening as OS
    from database.db import query_db
    n = dict(query_db("SELECT count(*) AS c FROM ongoing_screening_config "
                      "WHERE is_configured", one=True))['c']
    if not n:
        flash('No screening cadence has been set yet. A compliance manager must decide '
              'the frequencies before ongoing screening can run.', 'danger')
        return redirect(url_for('screening.ongoing_screening_dashboard'))
    try:
        engine = get_engine()
    except Exception:
        engine = None
    run_id, stats = OS.run(engine=engine, run_type='manual',
                           triggered_by=current_user.id,
                           include_all=bool(request.form.get('force_all')))
    if stats['new_matches'] or stats['changed'] or stats['delisted']:
        flash(f"Run complete — {stats['names']} name(s) re-screened. "
              f"{stats['new_matches']} new match(es), {stats['changed']} changed listing(s), "
              f"{stats['delisted']} de-listed. These need review.", 'warning')
    else:
        flash(f"Run complete — {stats['names']} name(s) re-screened, nothing new.", 'success')
    return redirect(url_for('screening.ongoing_screening_dashboard'))


@screening_bp.route('/ongoing/finding/<int:finding_id>', methods=['POST'])
@login_required
@permission_required('ongoing_screening', level='edit')
def ongoing_finding_action(finding_id):
    """Close out a finding.

    'accept' folds a newly-appeared listing into the cleared set — the analyst
    has reviewed it and it is still not this person. 'escalate' leaves it open
    and marks it for investigation, which is where an STR would be raised from.
    """
    from database.db import execute_db, query_db
    action = request.form.get('action')
    f = query_db("SELECT * FROM ongoing_screening_findings WHERE id=%s",
                 (finding_id,), one=True)
    if not f:
        flash('Finding not found.', 'danger')
        return redirect(url_for('screening.ongoing_screening_dashboard'))
    f = dict(f)
    reason = (request.form.get('reason') or '').strip()

    if action == 'accept':
        if not reason:
            flash('A reason is required to accept a new match as a false positive.', 'danger')
            return redirect(url_for('screening.ongoing_screening_dashboard'))
        if f['finding_type'] == 'new_entity' and f['entity_id']:
            execute_db("""INSERT INTO screening_whitelist_matches
                            (whitelist_id, entity_id, entity_name, entity_source,
                             match_score, fingerprint)
                          VALUES (%s,%s,%s,%s,%s,NULL)
                          ON CONFLICT (whitelist_id, entity_id) DO NOTHING""",
                       (f['whitelist_id'], f['entity_id'], f['entity_name'],
                        f['entity_source'], f['match_score']))
        elif f['finding_type'] == 'entity_changed' and f['entity_id']:
            execute_db("""UPDATE screening_whitelist_matches SET fingerprint=%s
                           WHERE whitelist_id=%s AND entity_id=%s""",
                       (f['new_fingerprint'], f['whitelist_id'], f['entity_id']))
        execute_db("""UPDATE screening_whitelist
                         SET cleared_match_count = (
                               SELECT count(*) FROM screening_whitelist_matches
                                WHERE whitelist_id=%s AND is_active)
                       WHERE id=%s""", (f['whitelist_id'], f['whitelist_id']))
        execute_db("""INSERT INTO screening_whitelist_audit
                        (whitelist_id, entry_name, action, previous_status, new_status,
                         reason, performed_by)
                      VALUES (%s,%s,'reinstated','Active','Active',%s,%s)""",
                   (f['whitelist_id'], f['screened_name'],
                    f"Ongoing screening finding accepted: {reason}", current_user.id))
        msg, level = 'Match accepted into the cleared set.', 'success'

    elif action == 'escalate':
        msg, level = ('Escalated for investigation. Raise an STR from the case if confirmed.',
                      'warning')
    else:
        msg, level = 'Finding closed.', 'info'

    execute_db("""UPDATE ongoing_screening_findings
                     SET status=%s, reviewed_by=%s, reviewed_at=NOW()
                   WHERE id=%s""",
               ('escalated' if action == 'escalate' else 'reviewed',
                current_user.id, finding_id))
    flash(msg, level)
    return redirect(url_for('screening.ongoing_screening_dashboard'))


# =============================================================================
# Whitelist case view — the adjudication record for one screened name
#
# "Reinstate" was the wrong word and the wrong model. Putting a name back on a
# list is not a decision anyone makes; the decisions that actually exist are:
#   - it is still not this person        -> confirm, keep suppressing
#   - it IS this person                  -> confirmed match, stop suppressing,
#                                           escalate for an STR
#   - I am not sure                      -> hold for investigation
# The buttons now say those things, and each one records who, when and why.
# =============================================================================

WL_DECISIONS = {
    'confirm_false_positive': ('Active',          'Confirmed false positive'),
    'confirm_true_match':     ('Confirmed Match', 'Confirmed TRUE match'),
    'hold':                   ('Under Investigation', 'Held for investigation'),
    'reopen':                 ('Requires Review', 'Reopened for review'),
}


@screening_bp.route('/whitelist/<int:id>/case')
@login_required
@permission_required('screening')
def whitelist_case(id):
    from database.db import query_db
    from services import ongoing_screening as OS

    entry = query_db("""SELECT w.*, u.first_name, u.last_name, u.email
                        FROM screening_whitelist w
                        LEFT JOIN users u ON u.id = w.added_by
                        WHERE w.id = %s""", (id,), one=True)
    if not entry:
        flash('Whitelist entry not found.', 'danger')
        return redirect(url_for('screening.manage_whitelist'))

    return render_template(
        'screening/whitelist_case.html',
        e=dict(entry),
        cleared=OS.cleared_matches(id),
        # every action ever taken on this entry, newest first
        history=query_db("""SELECT a.*, u.first_name, u.last_name, u.email
                            FROM screening_whitelist_audit a
                            LEFT JOIN users u ON u.id = a.performed_by
                            WHERE a.whitelist_id = %s
                            ORDER BY a.performed_at DESC""", (id,)),
        # what ongoing screening has seen since
        findings=query_db("""SELECT f.*, r.started_at, r.run_type,
                                    u.first_name, u.last_name
                             FROM ongoing_screening_findings f
                             JOIN ongoing_screening_runs r ON r.id = f.run_id
                             LEFT JOIN users u ON u.id = f.reviewed_by
                             WHERE f.whitelist_id = %s
                             ORDER BY f.created_at DESC""", (id,)),
        decisions=WL_DECISIONS,
        can_edit=current_user.can_edit('screening'))


@screening_bp.route('/whitelist/<int:id>/decide', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def whitelist_decide(id):
    """Record a decision on a whitelist case.

    Every path writes an audit row. A decision with no reason is refused —
    suppressing a sanctions alert is a compliance judgement and has to be
    attributable and explained, not a click.
    """
    from database.db import execute_db, query_db

    entry = query_db("SELECT id, name, status FROM screening_whitelist WHERE id=%s",
                     (id,), one=True)
    if not entry:
        flash('Whitelist entry not found.', 'danger')
        return redirect(url_for('screening.manage_whitelist'))
    entry = dict(entry)

    decision = request.form.get('decision')
    if decision not in WL_DECISIONS:
        flash('Unknown decision.', 'danger')
        return redirect(url_for('screening.whitelist_case', id=id))

    reason = (request.form.get('reason') or '').strip()
    if len(reason) < 15:
        flash('Please record a specific justification (at least 15 characters). '
              'It is kept permanently against your name.', 'danger')
        return redirect(url_for('screening.whitelist_case', id=id))

    new_status, label = WL_DECISIONS[decision]
    freq = request.form.get('screening_frequency')

    execute_db("UPDATE screening_whitelist SET status=%s, notes=%s WHERE id=%s",
               (new_status, reason, id))
    if freq:
        execute_db("UPDATE screening_whitelist SET screening_frequency=%s WHERE id=%s",
                   (freq, id))
        from services import ongoing_screening as OS
        OS.schedule_next(id, freq)

    execute_db("""INSERT INTO screening_whitelist_audit
                    (whitelist_id, entry_name, action, previous_status, new_status,
                     reason, performed_by)
                  VALUES (%s,%s,%s,%s,%s,%s,%s)""",
               (id, entry['name'], decision, entry['status'], new_status,
                reason, current_user.id))

    if decision == 'confirm_true_match':
        # Stop suppressing immediately and close the cleared set, so the next
        # screening run raises this name rather than silently passing it.
        execute_db("UPDATE screening_whitelist_matches SET is_active=FALSE "
                   "WHERE whitelist_id=%s", (id,))
        flash(f'"{entry["name"]}" recorded as a CONFIRMED MATCH. It no longer suppresses '
              f'anything and will alert on the next screening. Raise an STR from the case.',
              'danger')
    elif decision == 'confirm_false_positive':
        flash(f'"{entry["name"]}" confirmed as a false positive. It continues to be '
              f'monitored by ongoing screening.', 'success')
    elif decision == 'hold':
        flash(f'"{entry["name"]}" held for investigation. It is not suppressing alerts '
              f'while under investigation.', 'warning')
    else:
        flash('Reopened for review.', 'info')

    return redirect(url_for('screening.whitelist_case', id=id))


# =============================================================================
# Risk band criteria — WHO decides a case is critical, and ON WHAT BASIS
#
# The bands existed with no rule behind them, so "CRITICAL" was a label nobody
# owned. Seeded deliberately empty: a risk methodology shipped with someone
# else's assumptions is worse than none, because it looks decided.
# =============================================================================

RISK_FACTORS = [
    ('match_score',    'Match score',            'Score returned by the screening engine'),
    ('list_source',    'List source',            'Which list the match came from, e.g. EMLCU, OFAC'),
    ('list_type',      'Listing type',           'Sanctions, PEP, adverse media, internal'),
    ('entity_type',    'Entity type',            'Individual or organisation'),
    ('is_pep',         'PEP status',             'Whether the subject is a politically exposed person'),
    ('country',        'Country',                'Nationality or country of the listing'),
    ('adverse_media',  'Adverse media',          'Negative media found against the subject'),
    ('customer_type',  'Customer type',          'Merchant, agent, individual'),
    ('manual',         'Manual override',        'Set by a compliance officer on the case'),
]
RISK_OPERATORS = [('gte', 'is at least'), ('lte', 'is at most'),
                  ('equals', 'equals'), ('in', 'is one of'), ('contains', 'contains')]
RISK_BANDS = ['CRITICAL', 'HIGH', 'MODERATE', 'LOW']


@screening_bp.route('/ongoing/criteria', methods=['GET', 'POST'])
@login_required
@permission_required('ongoing_screening', level='edit')
def risk_criteria():
    from database.db import execute_db, query_db

    if request.method == 'POST':
        act = request.form.get('action')
        if act == 'add':
            if not request.form.get('band') or not request.form.get('factor'):
                flash('Band and factor are both required.', 'danger')
            else:
                execute_db("""INSERT INTO screening_risk_criteria
                                (band, factor, operator, value, weight, description, created_by)
                              VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                           (request.form.get('band'), request.form.get('factor'),
                            request.form.get('operator') or 'equals',
                            (request.form.get('value') or '').strip() or None,
                            int(request.form.get('weight') or 1),
                            (request.form.get('description') or '').strip() or None,
                            current_user.id))
                flash('Criterion added.', 'success')
        elif act == 'toggle':
            execute_db("UPDATE screening_risk_criteria SET is_active = NOT is_active, "
                       "updated_by=%s, updated_at=NOW() WHERE id=%s",
                       (current_user.id, request.form.get('criterion_id')))
            flash('Criterion enabled/disabled.', 'info')
        elif act == 'delete':
            execute_db("DELETE FROM screening_risk_criteria WHERE id=%s",
                       (request.form.get('criterion_id'),))
            flash('Criterion removed.', 'info')
        return redirect(url_for('screening.risk_criteria'))

    return render_template(
        'screening/risk_criteria.html',
        criteria=query_db("""SELECT c.*,
                   TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS created_by_name,
                   u.email AS created_by_email
                 FROM screening_risk_criteria c
                 LEFT JOIN users u ON u.id = c.created_by
                 ORDER BY CASE c.band WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1
                                      WHEN 'MODERATE' THEN 2 ELSE 3 END, c.id"""),
        factors=RISK_FACTORS, operators=RISK_OPERATORS, bands=RISK_BANDS)


# =============================================================================
# Confirmed Matches register  (Phase B)  + sortable list helper  (Phase C)
# =============================================================================

# Whitelisted sort columns. Never interpolate a user-supplied column name into
# SQL — this maps a request parameter to a known-safe expression instead.
CM_SORT = {
    'name':    'entity_name', 'matched': 'matched_name', 'source': 'list_source',
    'type':    'list_type',   'score':   'match_score',  'confirmed': 'confirmed_at',
    'status':  'status',      'action':  'action_taken',
}
HIST_SORT = {
    'name':   'h.entity_name',  'date':   'h.screening_date',
    'score':  'h.highest_score','module': 'h.source_module',
    'result': 'h.screening_result', 'matches': 'h.total_matches_found',
    'status': 'h.status',
}


def _sort_clause(mapping, default_key, default_dir='desc'):
    """(order_by_sql, key, direction) from the request, safely."""
    key = request.args.get('sort', default_key)
    direction = 'asc' if request.args.get('dir', default_dir).lower() == 'asc' else 'desc'
    col = mapping.get(key, mapping[default_key])
    if key not in mapping:
        key = default_key
    return f'{col} {direction.upper()} NULLS LAST', key, direction


@screening_bp.route('/confirmed-matches')
@login_required
@permission_required('screening')
def confirmed_matches():
    """Subjects confirmed as genuine matches.

    This is the register a regulator asks to see: who matched what, on which
    list, who decided, and what was done about it.
    """
    from database.db import query_db
    from screening.cache import list_sources

    where, params = [], []
    if request.args.get('q'):
        where.append('entity_name ILIKE %s'); params.append(f"%{request.args['q']}%")
    if request.args.get('source'):
        where.append('list_source = %s'); params.append(request.args['source'])
    if request.args.get('list_type'):
        where.append('list_type = %s'); params.append(request.args['list_type'])
    if request.args.get('status'):
        where.append('status = %s'); params.append(request.args['status'])
    # score floor, and a separate floor per list type — a sanctions hit and a
    # PEP hit do not warrant the same threshold
    if request.args.get('min_score'):
        where.append('match_score >= %s'); params.append(float(request.args['min_score']))
    if request.args.get('min_sanctions'):
        where.append("(list_type <> 'sanctions' OR match_score >= %s)")
        params.append(float(request.args['min_sanctions']))
    if request.args.get('min_pep'):
        where.append("(list_type <> 'pep' OR match_score >= %s)")
        params.append(float(request.args['min_pep']))

    clause = ('WHERE ' + ' AND '.join(where)) if where else ''
    order, sort_key, sort_dir = _sort_clause(CM_SORT, 'confirmed')

    rows = query_db(f"""SELECT c.*,
                          TRIM(COALESCE(u.first_name,'')||' '||COALESCE(u.last_name,'')) AS confirmed_by_name
                        FROM confirmed_matches c
                        LEFT JOIN users u ON u.id = c.confirmed_by
                        {clause} ORDER BY {order} LIMIT 500""", tuple(params))

    return render_template('screening/confirmed_matches.html',
                           rows=rows, sort=sort_key, dir=sort_dir,
                           sources=list_sources(),
                           args=request.args,
                           summary=query_db("""SELECT count(*) AS total,
                                   count(*) FILTER (WHERE status='open')     AS open,
                                   count(*) FILTER (WHERE status='reported') AS reported,
                                   count(*) FILTER (WHERE str_reference IS NOT NULL) AS with_str,
                                   count(DISTINCT normalized_name) AS subjects
                                 FROM confirmed_matches""", one=True),
                           can_edit=current_user.can_edit('screening'))


@screening_bp.route('/confirmed-matches/<int:match_id>/update', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def confirmed_match_update(match_id):
    from database.db import execute_db, query_db

    row = query_db("SELECT id, entity_name FROM confirmed_matches WHERE id=%s",
                   (match_id,), one=True)
    if not row:
        flash('Record not found.', 'danger')
        return redirect(url_for('screening.confirmed_matches'))

    action = request.form.get('action_taken') or None
    str_ref = (request.form.get('str_reference') or '').strip() or None
    notes = (request.form.get('notes') or '').strip() or None
    status = request.form.get('status') or 'open'

    execute_db("""UPDATE confirmed_matches
                     SET action_taken=%s, str_reference=%s, notes=%s, status=%s,
                         reported_to_emlcu = (%s IS NOT NULL),
                         str_filed_at = CASE WHEN %s IS NOT NULL AND str_filed_at IS NULL
                                             THEN NOW() ELSE str_filed_at END,
                         str_filed_by = CASE WHEN %s IS NOT NULL AND str_filed_by IS NULL
                                             THEN %s ELSE str_filed_by END,
                         closed_at = CASE WHEN %s = 'closed' THEN NOW() ELSE NULL END,
                         closed_by = CASE WHEN %s = 'closed' THEN %s ELSE NULL END
                   WHERE id=%s""",
               (action, str_ref, notes, status, str_ref, str_ref, str_ref,
                current_user.id, status, status, current_user.id, match_id))
    flash(f'Record updated for {dict(row)["entity_name"]}.', 'success')
    return redirect(request.referrer or url_for('screening.confirmed_matches'))


# ---------------------------------------------------------------------------
# Screening Quality: list freshness, index coverage, measured accuracy
# ---------------------------------------------------------------------------
@screening_bp.route('/quality')
@login_required
@permission_required('screening')
def quality():
    from screening import quality_service as qs
    fresh = qs.list_freshness()
    runs = qs.quality_runs()
    latest = runs[0] if runs else None
    cases = qs.run_cases(latest['id']) if latest else []
    misses = [c for c in cases if c.get('variant') not in ('negative', 'id_different', 'short_form')
              and not c.get('found')][:25]
    false_alerts = [c for c in cases if c.get('variant') == 'negative'
                    and c.get('status') in ('CONFIRMED_HIT', 'POTENTIAL_MATCH')][:25]
    return render_template('screening/quality.html', fresh=fresh, internal=qs.internal_lists(),
                           coverage=qs.index_coverage(fresh), runs=runs, latest=latest,
                           misses=misses, false_alerts=false_alerts, targets=qs.TARGETS)


@screening_bp.route('/quality/run', methods=['POST'])
@login_required
@permission_required('screening', level='edit')
def quality_run():
    from flask_babel import gettext as _
    if not current_user.is_admin() and not current_user.is_compliance_officer():
        flash(_('Only administrators and compliance officers can start an evaluation.'), 'danger')
        return redirect(url_for('screening.quality'))
    import subprocess
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_path = os.path.join(base, 'logs', 'screening_quality_eval.log')
    with open(log_path, 'a') as lf:
        subprocess.Popen([sys.executable, os.path.join(base, 'scripts', 'screening_quality_eval.py'),
                          '--kind', 'manual', '--names', '30'],
                         cwd=base, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
    flash(_('Evaluation started. It takes about 10 minutes; refresh this page to see the result.'), 'info')
    return redirect(url_for('screening.quality'))
