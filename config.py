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

import os
from datetime import timedelta

class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(32).hex()
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URI') or 'sqlite:///complynex.db'

    # PostgreSQL configuration
    DB_TYPE = os.environ.get('DB_TYPE', 'sqlite')
    POSTGRES_CONFIG = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'database': os.environ.get('POSTGRES_DB', 'complynex_db'),
        'user': os.environ.get('POSTGRES_USER', 'complynex'),
        'password': os.environ.get('POSTGRES_PASSWORD', ''),
        'port': int(os.environ.get('POSTGRES_PORT', 5432))
    }
    
    # Backward compatibility for database/db.py
    if SQLALCHEMY_DATABASE_URI.startswith('sqlite:///'):
        DATABASE = os.path.join(os.getcwd(), 'complynex.db')
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{DATABASE}'
    else:
        DATABASE = SQLALCHEMY_DATABASE_URI

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Security settings
    DEBUG = False
    TESTING = False
    
    # Session configuration
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hour of inactivity logs the user out (must be >= WTF_CSRF_TIME_LIMIT, otherwise the session -- and its stored csrf_token -- expires before a long form's CSRF token does, causing "CSRF session token is missing" on submit)

    # "Remember me" cookie (separate from the session cookie above) - bounded
    # so a checked box on a shared computer doesn't grant a year of persistent login
    REMEMBER_COOKIE_DURATION = timedelta(days=14)
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'

    # CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # tokens expire after 1 hour
    WTF_CSRF_HEADERS = ["X-CSRFToken", "X-CSRF-Token"]

    # Redis Configuration
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'

    # File Uploads
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max file size

    # Email Configuration
    # Three separate faults meant no email could ever leave the system:
    #   1. this read EMAIL_USER / EMAIL_PASS while .env holds GMAIL_USER /
    #      GMAIL_PASS, so both came back None
    #   2. MAIL_SERVER was hard-coded to Hostinger while the credentials are
    #      Gmail, so even correct credentials would have gone to the wrong host
    #   3. EMAIL_MOCK_MODE defaulted to True, so delivery was off regardless
    #
    # Now: accept either variable name, infer the host from the address, and
    # only mock when there is genuinely nothing to send with.
    MAIL_USERNAME = (os.environ.get('EMAIL_USER')
                     or os.environ.get('GMAIL_USER')
                     or os.environ.get('SMTP_USER'))
    MAIL_PASSWORD = (os.environ.get('EMAIL_PASS')
                     or os.environ.get('GMAIL_PASS')
                     or os.environ.get('SMTP_PASS'))

    _addr = (MAIL_USERNAME or '').lower()
    if os.environ.get('MAIL_SERVER'):
        MAIL_SERVER = os.environ.get('MAIL_SERVER')
    elif 'gmail.com' in _addr or 'googlemail.com' in _addr:
        MAIL_SERVER = 'smtp.gmail.com'
    elif 'outlook.com' in _addr or 'hotmail.com' in _addr or 'office365' in _addr:
        MAIL_SERVER = 'smtp.office365.com'
    else:
        MAIL_SERVER = 'smtp.hostinger.com'

    # Port 465 is implicit SSL (SMTPS) — the connection is encrypted from the
    # first byte. Port 587 is STARTTLS, which begins in the clear and upgrades.
    # They are not interchangeable: using TLS settings on 465 hangs, and SSL on
    # 587 is refused. Hostinger publishes 465, so the mode follows the port.
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 465))
    MAIL_USE_SSL = MAIL_PORT == 465
    MAIL_USE_TLS = not MAIL_USE_SSL
    MAIL_DEFAULT_SENDER = (os.environ.get('MAIL_DEFAULT_SENDER')
                           or MAIL_USERNAME
                           or 'noreply@complynex.online')

    # Explicit setting wins; otherwise mock only when there is no credential to
    # send with. A system that silently swallows mail because of a default flag
    # is how "reminders sent" ends up meaning nothing.
    _mock = os.environ.get('EMAIL_MOCK_MODE')
    if _mock is not None:
        EMAIL_MOCK_MODE = _mock.lower() == 'true'
    else:
        EMAIL_MOCK_MODE = not (MAIL_USERNAME and MAIL_PASSWORD)


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False
    
    # Enforce Security
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Ensure SECRET_KEY is set via Env in Prod
    if not os.environ.get('SECRET_KEY'):
        raise RuntimeError('SECRET_KEY environment variable must be set in production')

# Select config based on environment
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

def get_config():
    env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, config['default'])
