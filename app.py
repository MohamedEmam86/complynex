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
ComplyNex Full Compliance Platform (CMS)
Main Flask Application

A compliance management platform for ComplyNex,
regulated by the Central Bank of Egypt (CBE).
"""
import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from system_fingerprint import verify_on_startup, get_short_fingerprint, fingerprint_context

from flask import Flask, render_template, redirect, url_for, jsonify, flash, send_from_directory
from flask_login import LoginManager, login_required, current_user
from flask_wtf.csrf import CSRFError

from datetime import datetime, timedelta
from flask_babel import Babel, _
from flask import session, request

from config import config
from database.db import get_db, close_db, init_db, init_app as db_init_app
from extensions import csrf, limiter
from models.user import User
try:
    from screening.dashboard_service import DashboardService
    # Parse Redis URL or use default
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    if redis_url.startswith('redis://'):
        # Simple parse for this specific service which expects dict or we can update service to take URL
        # For now, let's keep it robust by passing what it expects or None
        # The service expects a dict {host, port, db, password}
        try:
            from urllib.parse import urlparse
            r_url = urlparse(redis_url)
            redis_config = {
                'host': r_url.hostname or 'localhost',
                'port': r_url.port or 6379,
                'db': int(r_url.path.strip('/')) if r_url.path.strip('/') else 0,
                'password': r_url.password
            }
            dashboard_service = DashboardService(redis_config)
        except Exception as e:
            logging.getLogger(__name__).warning(f"Redis URL parse failed, using localhost: {e}")
            dashboard_service = DashboardService({'host': 'localhost'})
    else:
        dashboard_service = DashboardService({'host': 'localhost'})
except ImportError:
    dashboard_service = None


def create_app(config_name=None):
    """
    Application factory pattern.

    Args:
        config_name: Configuration to use ('development', 'production', 'testing').
            Defaults to the FLASK_ENV env var so gunicorn (which calls
            create_app() with no argument) picks up ProductionConfig in prod
            instead of silently falling back to DevelopmentConfig.

    Returns:
        Flask application instance
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__)
    app.jinja_options = {'extensions': ['jinja2.ext.do']}

    # Trust exactly one reverse-proxy hop (nginx on 127.0.0.1, see
    # /etc/nginx/sites-enabled/complynex). Without this, Flask sees every
    # request's remote_addr as nginx's own 127.0.0.1 socket peer instead of
    # the real client IP, which breaks Flask-Limiter's get_remote_address
    # key_func (extensions.py) — all visitors share one shared rate-limit
    # bucket instead of being limited per-IP. x_for/x_proto/x_host=1 means
    # "trust exactly one layer of X-Forwarded-* headers", matching the
    # single nginx hop in front of gunicorn.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Load configuration
    app.config.from_object(config[config_name])
    
    # Initialize Logging
    from utils.logging_config import setup_logging
    setup_logging(app)

    # Verify deployment fingerprint — logs CRITICAL if the installation has
    # been copied to an unauthorised server, but does not kill the process
    # so a prod outage is avoided while the alert is investigated.
    verify_on_startup()

    # Initialize database
    db_init_app(app)
    
    # Babel Configuration
    app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'
    
    # Register Jinja2 globals and filters
    import json
    app.jinja_env.globals.update(getattr=getattr)
    # Timezone helper for templates
    from utils.timezone_utils import to_cairo_display, now_cairo
    app.jinja_env.globals.update(to_cairo=to_cairo_display, now_cairo=now_cairo)
    app.jinja_env.filters['from_json'] = json.loads
    app.jinja_env.add_extension('jinja2.ext.do')
    
    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    
    # Initialize CSRF Protection
    csrf.init_app(app)
    limiter.init_app(app)

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/') or request.is_json:
            return jsonify({'error': 'Not found', 'message': str(e)}), 404
        return render_template('errors/404.html', error=str(e)), 404

    @app.errorhandler(500)
    def server_error(e):
        import logging; logging.getLogger(__name__).error(f"500: {e}")
        if request.path.startswith('/api/') or request.is_json:
            return jsonify({'error': 'Internal server error'}), 500
        return render_template('errors/500.html'), 500

    @app.errorhandler(403)
    def forbidden(e):
        if request.path.startswith('/api/') or request.is_json:
            return jsonify({'error': 'Forbidden'}), 403
        return render_template('errors/403.html'), 403

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        if request.path.startswith('/api/') or request.is_json:
            return jsonify({'error': 'CSRF validation failed', 'message': 'Your session expired. Please log in again and resubmit.'}), 400
        if request.path.startswith('/academy') and not request.path.startswith('/academy/admin'):
            # Public Academy learners never see the staff login page.
            flash('Your session expired. Please submit the form again.', 'warning')
            return redirect(request.path if request.method == 'POST' and not request.path.endswith('/done') else '/academy/')
        flash('Your session expired. Please log in again and resubmit the form.', 'warning')
        return redirect(url_for('auth.login', next=request.full_path))

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import jsonify, url_for
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.path.startswith('/screening/bulk-upload-status/'):
            return jsonify({"status": "error", "message": "Session expired. Please log in again."}), 401
        return redirect(url_for('auth.login', next=request.full_path))
    
    # Initialize Mail
    from extensions import mail
    mail.init_app(app)
    
    @login_manager.user_loader
    def load_user(user_id):
        """Load user by session identity '<id>:<auth_version>'. Rejects old-format
        ids, a changed auth_version (revoked sessions), and inactive or expired
        accounts on EVERY request, not only at login."""
        try:
            uid, ver = str(user_id).split(':', 1)
            uid, ver = int(uid), int(ver)
        except (ValueError, TypeError):
            return None
        user = User.get_by_id(uid)
        if not user or not user.is_active or (getattr(user, 'auth_version', 0) or 0) != ver:
            return None
        return user
    
    # Babel Configuration
    app.config['BABEL_DEFAULT_LOCALE'] = 'ar'
    app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'
    app.config['LANGUAGES'] = {
        'ar': 'العربية',
        'en': 'English'
    }

    # Initialize Babel
    def get_locale():
        # Check URL parameter first
        lang = request.args.get('lang')
        if lang in ['ar', 'en']:
            session['lang'] = lang
            session['dir'] = 'rtl' if lang == 'ar' else 'ltr'
            return lang

        # Check if language is forced via session
        if 'lang' in session:
            return session['lang']
        
        # Fallback to browser language (prioritize Arabic)
        return request.accept_languages.best_match(['ar', 'en']) or 'ar'
    
    babel = Babel(app, locale_selector=get_locale)
    app.jinja_env.globals.update(get_locale=get_locale)

    # Cache-busting helper for static assets: appends the file mtime as a
    # query string so browsers (which cache /static/ for 30d, immutable)
    # always fetch the latest version right after a deploy, without needing
    # a manual version bump or a hard refresh from the user.
    def static_v(filename):
        try:
            fpath = os.path.join(app.static_folder, filename)
            v = int(os.path.getmtime(fpath))
        except OSError:
            v = 0
        return url_for('static', filename=filename) + '?v=' + str(v)
    app.jinja_env.globals.update(static_v=static_v)
    
    # Language switcher route
    @app.route('/set-language/<lang>')
    def set_language(lang):
        if lang in ['en', 'ar']:
            session['lang'] = lang
            # Update user direction in session helper for templates
            session['dir'] = 'rtl' if lang == 'ar' else 'ltr'
        return redirect(request.referrer or url_for('dashboard'))

    # Notification routes - without these, notifications never get marked
    # read so the bell badge only ever grows and never reflects what's new
    @app.route('/notifications/open/<int:notif_id>')
    @login_required
    def open_notification(notif_id):
        from models.notification import Notification
        Notification.mark_as_read(notif_id)
        link = request.args.get('next')
        return redirect(link or url_for('dashboard'))

    @app.route('/notifications/mark-all-read', methods=['POST'])
    @login_required
    def mark_all_notifications_read():
        from models.notification import Notification
        Notification.mark_all_as_read(current_user.id)
        return redirect(request.referrer or url_for('dashboard'))

    @app.route('/notifications')
    @login_required
    def notifications_list():
        from models.notification import Notification
        notifications = Notification.get_all_for_user(current_user.id)
        return render_template('notifications/list.html', notifications=notifications)

    # Register blueprints
    from auth.routes import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    
    from admin.routes import admin_bp
    app.register_blueprint(admin_bp)
    
    from ghe.routes import ghe_bp
    app.register_blueprint(ghe_bp)
    
    # Public GHE routes (no authentication required)
    from ghe.public_routes import public_ghe_bp
    app.register_blueprint(public_ghe_bp)

    # COI Module
    from coi.routes import coi_bp
    app.register_blueprint(coi_bp)
    
    from coi.public_routes import public_coi_bp
    app.register_blueprint(public_coi_bp)
    
    # COBEC Module
    from cobec.routes import cobec_bp
    app.register_blueprint(cobec_bp)
    
    # Declaration Tracker Module
    from tracker.routes import tracker_bp
    app.register_blueprint(tracker_bp)
    
    # Policy Management Module
    from policies.routes import policies_bp
    app.register_blueprint(policies_bp)
    
    # Regulatory Reporting Module
    from reporting.routes import reporting_bp
    app.register_blueprint(reporting_bp)
    
    # Training Management Module
    from training.routes import training_bp
    from aml.routes import aml_bp
    from data_protection.routes import dp_bp
    from cyber.routes import cyber_bp
    from governance import governance_bp
    from risk_management import risk_bp
    from internal_audit import ia_bp
    from carbon import carbon_bp
    from esg import esg_bp
    from attachments import attachments_bp
    app.register_blueprint(training_bp)
    app.register_blueprint(aml_bp)
    app.register_blueprint(dp_bp)
    app.register_blueprint(cyber_bp)
    app.register_blueprint(governance_bp)
    app.register_blueprint(risk_bp)
    app.register_blueprint(ia_bp)
    app.register_blueprint(carbon_bp)
    app.register_blueprint(esg_bp)
    app.register_blueprint(attachments_bp)

    # Screening Module
    from screening.routes import screening_bp
    app.register_blueprint(screening_bp, url_prefix='/screening')

    # PEP Management API (search/detail/manual-sync routes only — the actual
    # background sync scheduler runs as its own systemd service,
    # complynex-pep-scheduler.service, not inside gunicorn workers)
    from screening.pep_management.api import pep_api
    app.register_blueprint(pep_api)

    # Whistleblowing Module
    from whistleblowing.routes import whistleblowing_bp
    app.register_blueprint(whistleblowing_bp, url_prefix='/whistleblowing')

    from declarations import declarations_bp
    app.register_blueprint(declarations_bp)

    # Consumer Protection Module
    from consumer_protection.routes import consumer_bp
    app.register_blueprint(consumer_bp)

    # Employee Portal Module (Public Access)
    from portal.routes import portal_bp
    app.register_blueprint(portal_bp)
    
    # User Management Module (Admin)
    from users import users_bp
    app.register_blueprint(users_bp)
    
    # Internal Blacklist Module
    from blacklist import blacklist_bp
    app.register_blueprint(blacklist_bp)
    
    # Merchant KYC Module
    from merchant_kyc.routes import merchant_kyc_bp
    app.register_blueprint(merchant_kyc_bp)

    # Compliance Event Bus (admin UI over compliance_events / event_routing_rules —
    # the actual dispatch runs in complynex-event-dispatcher.service, not gunicorn)
    from events import events_bp
    import events.routes  # noqa: F401 — registers routes on events_bp
    app.register_blueprint(events_bp)

    # Party Registry (Entity 360) + unified Case oversight — see parties/ and cases/
    from parties import parties_bp
    import parties.routes  # noqa: F401 — registers routes on parties_bp
    app.register_blueprint(parties_bp)

    from cases import cases_bp
    import cases.routes  # noqa: F401 — registers routes on cases_bp
    app.register_blueprint(cases_bp)

    # FRA regulatory control framework (parameters, control library, engine,
    # evidence, findings & corrective actions) — see regcontrols/
    from regcontrols import regcontrols_bp
    import regcontrols.routes  # noqa: F401 — registers routes on regcontrols_bp
    app.register_blueprint(regcontrols_bp)

    # AML/CFT & KYC assurance (key roles, annual report, monitoring programme,
    # screening QA, unusual-transactions register, KYC files, risk model) — see amlkyc/
    from amlkyc import amlkyc_bp
    import amlkyc.routes  # noqa: F401 — registers routes on amlkyc_bp
    app.register_blueprint(amlkyc_bp)

    # Prudential, licensing, governance & financial-reporting registers — see prudential/
    from prudential import prudential_bp
    import prudential.routes  # noqa: F401 — registers routes on prudential_bp
    app.register_blueprint(prudential_bp)

    # Compliance Copilot (AI intake, playbooks, next-best-action) — local
    # inference only, rules fallback by default — see ai/ and docs/ai/
    from ai import ai_bp
    import ai.routes  # noqa: F401 — registers routes on ai_bp
    app.register_blueprint(ai_bp)

    # Optional content packs (packs/<code>/): their pages exist only while the
    # pack is enabled (Compliance Controls > Content packs). Core never
    # imports a specific pack.
    from regcontrols.packs import register_blueprints as _register_pack_blueprints
    _register_pack_blueprints(app)


    # Phishing Awareness Module
    from phishing import phishing_bp
    app.register_blueprint(phishing_bp)

        # eKYC Module
    from ekyc.routes import ekyc_bp
    app.register_blueprint(ekyc_bp)

    # Integrys Academy — public learner portal (academy.integrysconsult.com) + staff console
    from academy import academy_bp, academy_admin_bp
    app.register_blueprint(academy_bp)
    app.register_blueprint(academy_admin_bp)

    # Versioned REST API
    try:
        from api import api_v1_bp
        app.register_blueprint(api_v1_bp)
        csrf.exempt(api_v1_bp)
    except Exception as _api_err:
        import logging as _log
        _log.getLogger(__name__).warning('API v1 blueprint not loaded: %s', _api_err)

    # Context processor for templates
    @app.context_processor
    def inject_globals():
        """Inject global variables into all templates."""
        from models.notification import Notification
        from flask_login import current_user
        
        notifications = []
        if current_user.is_authenticated:
            try:
                notifications = Notification.get_unread_for_user(current_user.id)
            except Exception as e:
                import logging as _log
                _log.getLogger(__name__).warning(f"Notification fetch failed for user {current_user.id}: {e}")
                # A failed query leaves this request's pooled connection's
                # transaction aborted — every later query on it (most of the
                # dashboard's KPI widgets share this same g.db connection)
                # would otherwise fail too with "current transaction is
                # aborted" regardless of whether it's a perfectly valid query.
                from database.db import get_db as _get_db
                _get_db().rollback()

        try:
            from models.settings import Settings as _Cfg
            company_name = _Cfg.get('company_name', 'ComplyNex')
        except Exception:
            company_name = 'ComplyNex'

        return {
            'company_name': company_name,
            'current_year': datetime.now().year,
            'now': datetime.now(),
            'unread_notifications': notifications
        }
    
    # ── Prometheus metrics ────────────────────────────────────────────────────
    from utils.metrics import metrics_response, request_latency
    import time as _time

    @app.before_request
    def _start_timer():
        from flask import g as _g2
        _g2._req_start = _time.monotonic()

    @app.after_request
    def _record_latency(response):
        from flask import g as _g2
        start = getattr(_g2, '_req_start', None)
        if start is not None and request.endpoint:
            request_latency.labels(
                method=request.method,
                endpoint=request.endpoint,
            ).observe(_time.monotonic() - start)
        return response

    @app.route('/metrics')
    def prometheus_metrics():
        """Prometheus scrape endpoint — restrict to localhost in Nginx."""
        return metrics_response()

    # Health check — probed by load balancers and uptime monitors (no auth)
    @app.route('/health')
    def health():
        status = {
            'status': 'ok',
            'timestamp': datetime.utcnow().isoformat(),
            'deployment': get_short_fingerprint(),
        }
        try:
            db = get_db()
            db.execute('SELECT 1')
            status['database'] = 'ok'
        except Exception:
            status['database'] = 'error'
            status['status'] = 'degraded'
        try:
            import redis as _redis
            _r = _redis.from_url(app.config.get('REDIS_URL', 'redis://localhost:6379/0'))
            _r.ping()
            status['redis'] = 'ok'
        except Exception:
            status['redis'] = 'error'
            status['status'] = 'degraded'
        http_status = 200 if status['status'] == 'ok' else 503
        # Outsiders get the status word only; component details and the deployment
        # fingerprint stay on the server (deploy.sh / monitoring call it on 127.0.0.1).
        if request.remote_addr not in ('127.0.0.1', '::1'):
            return jsonify({'status': status['status']}), http_status
        return jsonify(status), http_status

    # Root route redirects to dashboard
    @app.route('/')
    @login_required
    def index():
        """Redirect root to dashboard."""
        return redirect(url_for('dashboard'))
    
    # Favicon route
    @app.route('/support', methods=['GET', 'POST'])
    def support():
        from flask import request, flash, render_template
        if request.method == 'POST':
            name     = request.form.get('name', '').strip()
            email    = request.form.get('email', '').strip()
            category = request.form.get('category', '').strip()
            priority = request.form.get('priority', 'Medium').strip()
            message  = request.form.get('message', '').strip()
            try:
                import smtplib
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
                mail_user = app.config.get('MAIL_USERNAME')
                mail_pass = app.config.get('MAIL_PASSWORD')
                body = f"""
New Support Request — ComplyNex CMS

From:     {name}
Email:    {email}
Category: {category}
Priority: {priority}

Message:
{message}
"""
                msg = MIMEMultipart()
                msg['From']    = mail_user or 'noreply@complynex.online'
                msg['To']      = 'info@complynex.online'
                msg['Subject'] = f'[{priority}] Support: {category} — {name}'
                msg['Reply-To'] = email
                msg.attach(MIMEText(body, 'plain'))
                if mail_user and mail_pass:
                    with smtplib.SMTP(app.config.get('MAIL_SERVER', 'smtp.googlemail.com'),
                                      app.config.get('MAIL_PORT', 587)) as server:
                        server.starttls()
                        server.login(mail_user, mail_pass)
                        server.send_message(msg)
                    flash('Your support request has been sent. We will get back to you shortly.', 'success')
                else:
                    flash('Support request received. Email delivery is pending configuration.', 'warning')
            except Exception as e:
                flash(f'Could not send email: {str(e)}', 'danger')
        return render_template('support.html')

    @app.route('/favicon.ico')
    def favicon():
        """Serve favicon to avoid 404 errors."""
        return send_from_directory(
            os.path.join(app.static_folder, 'images'),
            'favicon-32.png',
            mimetype='image/png'
        )
    
    # Dashboard route
    @app.route('/dashboard')
    @login_required
    def dashboard():
        """
        Main dashboard with compliance metrics.

        Widget/KPI assembly lives in utils/dashboard_data.py (get_dashboard_context)
        so this route stays a thin wrapper — see that module for the full list of
        widgets and the shared-connection rollback pattern they rely on.
        """
        if not current_user.can_access_cms():
            return redirect(url_for('portal.dashboard'))

        from utils.dashboard_data import get_dashboard_context, get_my_pending_items
        ctx = get_dashboard_context(current_user, dashboard_service=dashboard_service)
        ctx['my_pending_items'] = get_my_pending_items(current_user)
        return render_template('index.html', **ctx)

    @app.route('/search')
    @login_required
    def search():
        """Lightweight cross-module search for the dashboard command bar.
        Scoped to risks, audit findings, and policies for v1 — expanding to
        more modules (or wiring into the existing screening Elasticsearch
        index) is a natural fast-follow, not needed for a first useful pass."""
        from utils.dashboard_data import _safe
        q = (request.args.get('q') or '').strip()
        results = {'risks': [], 'findings': [], 'policies': []}
        if q and current_user.can_access_cms():
            db = get_db()
            like = f'%{q}%'
            if current_user.can_view('risk_management'):
                results['risks'] = _safe(db, lambda db: db.execute(
                    "SELECT id, risk_id, risk_title FROM risks "
                    "WHERE risk_id ILIKE %s OR risk_title ILIKE %s LIMIT 20",
                    (like, like)
                ).fetchall(), default=[], label="search risks")
            if current_user.can_view('internal_audit'):
                results['findings'] = _safe(db, lambda db: db.execute(
                    "SELECT id, finding_number, finding_title FROM audit_findings "
                    "WHERE finding_number ILIKE %s OR finding_title ILIKE %s LIMIT 20",
                    (like, like)
                ).fetchall(), default=[], label="search findings")
            if current_user.can_view('policies'):
                results['policies'] = _safe(db, lambda db: db.execute(
                    "SELECT id, policy_name FROM policies WHERE policy_name ILIKE %s LIMIT 20",
                    (like,)
                ).fetchall(), default=[], label="search policies")
        return render_template('search_results.html', q=q, results=results)

    @app.route('/dashboard/compliance-operations')
    @login_required
    def compliance_operations():
        """Drill-down page for the AML alert heatmap, sanctions-source
        freshness, and top-flagged-customers widgets — moved off the main
        bento dashboard to keep it calm/focused, still one click away."""
        if not (current_user.is_compliance_officer() or current_user.is_admin()):
            return redirect(url_for('dashboard'))

        import json as _json
        from utils.dashboard_data import _safe
        db = get_db()
        today_str = datetime.now().strftime('%Y-%m-%d')

        alert_heatmap_json = _safe(db, lambda db: _json.dumps([
            {'day': r['day'], 'count': r['count']} for r in db.execute("""
                SELECT SUBSTRING(CAST(alert_date AS TEXT),1,10) as day, COUNT(*) as count
                FROM tm_alerts
                WHERE CAST(alert_date AS TEXT) >= %s
                GROUP BY day ORDER BY day
            """, (((datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')),)).fetchall()
        ]), default='[]', label="alert heatmap")

        reg_deadlines = _safe(db, lambda db: db.execute("""
            SELECT rr.report_name, CAST(rs.due_date AS TEXT) as due_date_str, rs.status
            FROM regulatory_report_submissions rs
            JOIN regulatory_reports rr ON rs.report_id = rr.id
            WHERE CAST(rs.due_date AS TEXT) BETWEEN %s AND %s
            AND rs.status IN ('pending','in_progress')
            ORDER BY rs.due_date LIMIT 10
        """, (today_str, (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d'))).fetchall(),
            default=[], label="regulatory deadlines")

        sanctions_freshness = _safe(db, lambda db: db.execute("""
            SELECT source_name, CAST(last_successful_update AS TEXT) as last_updated, is_active
            FROM screening_data_sources ORDER BY last_successful_update DESC
        """).fetchall(), default=[], label="sanctions freshness")

        top_flagged = _safe(db, lambda db: db.execute("""
            SELECT c.full_name, c.company_name, c.customer_reference,
                   c.risk_classification, COUNT(t.id) as alert_count
            FROM customers c
            JOIN transactions t ON c.id = t.customer_id
            WHERE t.alert_raised = 1
            GROUP BY c.id, c.full_name, c.company_name, c.customer_reference, c.risk_classification
            ORDER BY alert_count DESC LIMIT 5
        """).fetchall(), default=[], label="top flagged customers")

        return render_template(
            'compliance_operations.html',
            alert_heatmap_json=alert_heatmap_json,
            reg_deadlines=reg_deadlines,
            sanctions_freshness=sanctions_freshness,
            top_flagged=top_flagged,
            today_str=today_str,
        )
    

    # Generate a fresh cryptographic nonce for each request so templates can
    # reference {{ csp_nonce }} in <script nonce="..."> tags — this lets us
    # remove 'unsafe-inline' from script-src while keeping inline scripts that
    # are already nonce-tagged.
    import secrets as _secrets
    from flask import g as _g

    @app.before_request
    def _generate_csp_nonce():
        _g.csp_nonce = _secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_csp_nonce():
        return {'csp_nonce': getattr(_g, 'csp_nonce', '')}

    @app.after_request
    def set_security_headers(response):
        nonce = getattr(_g, 'csp_nonce', '')
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(self), camera=(self)'
        if app.config.get('SESSION_COOKIE_SECURE'):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' 'wasm-unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
                "https://fonts.googleapis.com; "
            "img-src 'self' data: blob:; "
            "font-src 'self' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net "
                "https://fonts.gstatic.com; "
            "connect-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "worker-src blob: 'self'; "
            # Academy lessons embed YouTube (privacy mode) / Vimeo players and serve MP4 from self
            "frame-src 'self' https://www.youtube-nocookie.com https://player.vimeo.com; "
            "media-src 'self' blob:;"
        )
        return response

    return app


# Create application instance for direct running
app = create_app()




if __name__ == '__main__':
    # Check if database exists, if not initialize it
    if app.config.get('DB_TYPE', 'sqlite') == 'sqlite' and not os.path.exists(app.config.get('DATABASE', '')):
        with app.app_context():
            init_db()
    
    # Run development server
    app.run(debug=True, host='0.0.0.0', port=5000)

