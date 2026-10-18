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
URL Configuration Manager for ComplyNex Screening System
=========================================================

Provides:
- URL management and versioning
- URL validation and testing
- Historical URL tracking
- Notification on URL changes

"""

import requests
import sqlite3
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None


class URLConfigManager:
    """
    Manages data source URLs with versioning and validation.
    """
    
    def __init__(self, db_config):
        self.db_config = db_config
        self.db_conn = None
        
        # Detect DB Type
        if isinstance(db_config, dict) and 'database' in db_config and len(db_config) == 1:
            self.db_type = 'sqlite'
            self.placeholder = '?'
        elif isinstance(db_config, str):
            self.db_type = 'sqlite'
            self.db_config = {'database': db_config}
            self.placeholder = '%s'
        else:
            self.db_type = 'postgresql'
            self.placeholder = '%s'
            
    def connect_db(self):
        """Establish database connection"""
        if self.db_type == 'sqlite':
            if not self.db_conn:
                # Despite the name, this always serves the shared Postgres
                # pool (db_pool always backs onto Config.POSTGRES_CONFIG) —
                # the 'sqlite' branch only reflects how db_config was typed
                # (a bare string/single-key dict), not the actual engine.
                self.db_conn = db_pool.checkout_connection()
                self.db_conn.row_factory = sqlite3.Row
                self._pooled = True
        else:
            if not self.db_conn or (hasattr(self.db_conn, 'closed') and self.db_conn.closed):
                if psycopg2 is None:
                    raise ImportError("psycopg2 is required for PostgreSQL")
                self.db_conn = psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)
                self._pooled = False

    def close_db(self):
        """Release the database connection — back to the pool if it came from there."""
        if self.db_conn:
            try:
                if getattr(self, '_pooled', False):
                    db_pool.return_connection(self.db_conn)
                else:
                    self.db_conn.close()
            except Exception as e:
                logger.debug(f"[SWALLOWED] db connection close (cleanup) failed: {e}")
            self.db_conn = None
            
    def get_current_url(self, source_id):
        """
        Get the current active URL for a data source.
        
        Args:
            source_id: Data source ID
            
        Returns:
            URL string or None
        """
        self.connect_db()
        cursor = self.db_conn.cursor()
        
        # First check data_source_urls table
        cursor.execute(
            f"""SELECT url FROM data_source_urls 
               WHERE source_id = {self.placeholder} AND is_current = TRUE
               ORDER BY valid_from DESC LIMIT 1""",
            (source_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return result['url']
            
        # Fallback to screening_data_sources table
        cursor.execute(
            f"SELECT source_url FROM screening_data_sources WHERE id = {self.placeholder}",
            (source_id,)
        )
        result = cursor.fetchone()
        
        return result['source_url'] if result else None
        
    def update_url(self, source_id, new_url, user_id, notes=None, validate=True):
        """
        Update URL for a data source.
        
        Args:
            source_id: Data source ID
            new_url: New URL
            user_id: User making the change
            notes: Optional notes about the change
            validate: Whether to validate URL before saving
            
        Returns:
            Boolean success
        """
        self.connect_db()
        
        try:
            # Validate URL if requested
            if validate:
                validation_result = self.validate_url(new_url)
                if not validation_result['valid']:
                    logger.error(f"URL validation failed: {validation_result['error']}")
                    return False
                    
            cursor = self.db_conn.cursor()
            
            # Mark current URL as no longer current
            cursor.execute(
                f"""UPDATE data_source_urls 
                   SET is_current = FALSE, valid_until = CURRENT_DATE
                   WHERE source_id = {self.placeholder} AND is_current = TRUE""",
                (source_id,)
            )
            
            # Insert new URL
            if self.db_type == 'sqlite':
                cursor.execute("""
                    INSERT INTO data_source_urls (
                        source_id, url, is_current, valid_from, 
                        verified_at, verification_status, created_by, created_at, notes
                    ) VALUES (%s, %s, TRUE, CURRENT_DATE, CURRENT_TIMESTAMP, 'VERIFIED', %s, CURRENT_TIMESTAMP, %s)
                """, (source_id, new_url, user_id, notes))
            else:
                cursor.execute("""
                    INSERT INTO data_source_urls (
                        source_id, url, is_current, valid_from,
                        verified_at, verification_status, created_by, created_at, notes
                    ) VALUES (%s, %s, TRUE, CURRENT_DATE, CURRENT_TIMESTAMP, 'VERIFIED', %s, CURRENT_TIMESTAMP, %s)
                """, (source_id, new_url, user_id, notes))
                
            # Update main source table
            cursor.execute(
                f"UPDATE screening_data_sources SET source_url = {self.placeholder} WHERE id = {self.placeholder}",
                (new_url, source_id)
            )
            
            self.db_conn.commit()
            
            logger.info(f"Updated URL for source {source_id} by user {user_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update URL: {e}")
            self.db_conn.rollback()
            return False
        finally:
            self.close_db()
            
    def validate_url(self, url, timeout=10):
        """
        Validate a URL by attempting to connect.
        
        Args:
            url: URL to validate
            timeout: Request timeout in seconds
            
        Returns:
            Dict with validation result
        """
        result = {
            'valid': False,
            'status_code': None,
            'error': None,
            'content_type': None,
            'content_length': None
        }
        
        try:
            # Make HEAD request first (faster)
            response = requests.head(url, timeout=timeout, allow_redirects=True)
            
            result['status_code'] = response.status_code
            result['content_type'] = response.headers.get('Content-Type')
            result['content_length'] = response.headers.get('Content-Length')
            
            if response.status_code == 200:
                result['valid'] = True
            elif response.status_code == 405:  # HEAD not allowed, try GET
                response = requests.get(url, timeout=timeout, stream=True)
                result['status_code'] = response.status_code
                result['valid'] = (response.status_code == 200)
            else:
                result['error'] = f"HTTP {response.status_code}"
                
        except requests.exceptions.Timeout:
            result['error'] = "Request timeout"
        except requests.exceptions.ConnectionError:
            result['error'] = "Connection failed"
        except requests.exceptions.RequestException as e:
            result['error'] = str(e)
        except Exception as e:
            result['error'] = f"Unexpected error: {e}"
            
        return result
        
    def get_url_history(self, source_id, limit=10):
        """
        Get URL change history for a source.
        
        Args:
            source_id: Data source ID
            limit: Maximum number of records to return
            
        Returns:
            List of URL history records
        """
        self.connect_db()
        cursor = self.db_conn.cursor()
        
        cursor.execute(f"""
            SELECT 
                dsu.url,
                dsu.is_current,
                dsu.valid_from,
                dsu.valid_until,
                dsu.verified_at,
                dsu.verification_status,
                dsu.created_at,
                u.email as created_by_user,
                dsu.notes
            FROM data_source_urls dsu
            LEFT JOIN users u ON dsu.created_by = u.id
            WHERE dsu.source_id = {self.placeholder}
            ORDER BY dsu.valid_from DESC, dsu.created_at DESC
            LIMIT {self.placeholder}
        """, (source_id, limit))
        
        history = cursor.fetchall()
        self.close_db()
        
        return [dict(row) for row in history]
        
    def check_urls_validity(self):
        """
        Check validity of all current URLs.
        
        Returns:
            Dict with validation results for each source
        """
        self.connect_db()
        cursor = self.db_conn.cursor()
        
        cursor.execute("""
            SELECT id, name, source_url 
            FROM screening_data_sources 
            WHERE is_active = 1 AND source_url IS NOT NULL
        """)
        sources = cursor.fetchall()
        
        results = {}
        
        for source in sources:
            source_id = source['id']
            source_name = source['name']
            url = source['source_url']
            
            logger.info(f"Validating URL for {source_name}...")
            
            validation = self.validate_url(url)
            
            results[source_id] = {
                'name': source_name,
                'url': url,
                'validation': validation
            }
            
            # Update verification status in database
            cursor.execute(f"""
                UPDATE data_source_urls 
                SET verified_at = CURRENT_TIMESTAMP,
                    verification_status = {self.placeholder},
                    verification_error = {self.placeholder}
                WHERE source_id = {self.placeholder} AND is_current = TRUE
            """, (
                'VERIFIED' if validation['valid'] else 'FAILED',
                validation['error'],
                source_id
            ))
            
        self.db_conn.commit()
        self.close_db()
        
        return results
        
    def get_sources_needing_update(self):
        """
        Get list of sources that are due for update based on schedule.
        
        Returns:
            List of source IDs that should be updated
        """
        self.connect_db()
        cursor = self.db_conn.cursor()
        
        cursor.execute("""
            SELECT id, name, update_frequency_hours, last_successful_update
            FROM screening_data_sources
            WHERE is_active = 1
            AND (
                last_successful_update IS NULL
                OR datetime(last_successful_update, '+' || update_frequency_hours || ' hours') <= NOW()
            )
            ORDER BY priority
        """)
        
        sources = cursor.fetchall()
        self.close_db()
        
        return [dict(row) for row in sources]


# Flask route helpers (to be added to routes.py)
def get_url_management_routes():
    """
    Returns Flask route functions for URL management.
    Add these to your routes.py:
    
    Example:
        from url_config_manager import get_url_management_routes
        
        @screening_bp.route('/screening/urls')
        @login_required
        @permission_required('screening', 'admin')
        def manage_urls():
            return get_url_management_routes()['manage_urls']()
    """
    from flask import render_template, request, jsonify, current_app
    from flask_login import current_user
    
    def manage_urls():
        """Display URL management interface"""
        manager = URLConfigManager(current_app.config['DATABASE'])
        
        # Get all sources with current URLs
        manager.connect_db()
        cursor = manager.db_conn.cursor()
        cursor.execute("""
            SELECT id, name, type, source_url, is_active, priority,
                   last_successful_update, update_frequency_hours
            FROM screening_data_sources
            ORDER BY priority
        """)
        sources = cursor.fetchall()
        manager.close_db()
        
        return render_template('screening/manage_urls.html', sources=sources)
        
    def update_source_url():
        """API endpoint to update a source URL"""
        data = request.get_json()
        
        source_id = data.get('source_id')
        new_url = data.get('url')
        notes = data.get('notes')
        validate = data.get('validate', True)
        
        if not source_id or not new_url:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
            
        manager = URLConfigManager(current_app.config['DATABASE'])
        success = manager.update_url(source_id, new_url, current_user.id, notes, validate)
        
        if success:
            return jsonify({'success': True, 'message': 'URL updated successfully'})
        else:
            return jsonify({'success': False, 'error': 'URL validation failed'}), 400
            
    def validate_source_url():
        """API endpoint to validate a URL"""
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400
            
        manager = URLConfigManager(current_app.config['DATABASE'])
        result = manager.validate_url(url)
        
        return jsonify(result)
        
    def get_url_history_api():
        """API endpoint to get URL history"""
        source_id = request.args.get('source_id', type=int)
        
        if not source_id:
            return jsonify({'success': False, 'error': 'source_id is required'}), 400
            
        manager = URLConfigManager(current_app.config['DATABASE'])
        history = manager.get_url_history(source_id)
        
        return jsonify({'success': True, 'history': history})
        
    def check_all_urls():
        """API endpoint to check all URLs"""
        manager = URLConfigManager(current_app.config['DATABASE'])
        results = manager.check_urls_validity()
        
        return jsonify({'success': True, 'results': results})
        
    return {
        'manage_urls': manage_urls,
        'update_source_url': update_source_url,
        'validate_source_url': validate_source_url,
        'get_url_history': get_url_history_api,
        'check_all_urls': check_all_urls
    }


if __name__ == "__main__":
    # Test the manager
    import os
    logging.basicConfig(level=logging.INFO)
    
    db = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'complynex.db')
    
    manager = URLConfigManager(db)
    
    print("\n=== Checking All URLs ===")
    results = manager.check_urls_validity()
    
    for source_id, data in results.items():
        status = "✅ Valid" if data['validation']['valid'] else "❌ Invalid"
        print(f"{status} - {data['name']}")
        if not data['validation']['valid']:
            print(f"  Error: {data['validation']['error']}")
