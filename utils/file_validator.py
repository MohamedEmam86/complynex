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
Secure file upload validation using magic bytes.
Never trust file extensions alone — always check actual file content.
"""
import os
import logging
from flask_babel import gettext as _

logger = logging.getLogger(__name__)

# Magic bytes for allowed file types
# Format: {mime_type: (bytes_to_read, list_of_valid_signatures)}
MAGIC_SIGNATURES = {
    'application/pdf': (5, [b'%PDF-']),
    'image/jpeg':      (3, [b'\xff\xd8\xff']),
    'image/png':       (8, [b'\x89PNG\r\n\x1a\n']),
    'image/gif':       (6, [b'GIF87a', b'GIF89a']),
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':  # xlsx
                       (4, [b'PK\x03\x04']),
    'application/vnd.ms-excel':  # xls
                       (8, [b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1']),
    'text/csv':        (0, []),   # CSV has no magic bytes, validated by extension + encoding
    'text/plain':      (0, []),
}

# Dangerous file signatures to ALWAYS reject regardless of extension
DANGEROUS_SIGNATURES = [
    b'MZ',           # Windows PE executable (.exe, .dll, .com)
    b'\x7fELF',      # Linux ELF executable
    b'#!/',          # Shell script
    b'#!',           # Any script shebang
    b'<script',      # HTML/JS injection
    b'<?php',        # PHP script
    b'#!/usr/bin',   # Unix executable
]

# Allowed extensions per upload type
ALLOWED_EXTENSIONS = {
    'document':    {'.pdf', '.docx', '.doc', '.txt'},
    'image':       {'.jpg', '.jpeg', '.png', '.gif'},
    'spreadsheet': {'.csv', '.xlsx', '.xls'},
    'sanctions':   {'.csv', '.xml', '.json', '.xlsx'},
    'any':         {'.pdf', '.docx', '.doc', '.txt', '.jpg', '.jpeg', 
                    '.png', '.csv', '.xlsx', '.xls'},
}

# Max file sizes per type (bytes)
MAX_FILE_SIZES = {
    'document':    10 * 1024 * 1024,   # 10MB
    'image':        5 * 1024 * 1024,   #  5MB
    'spreadsheet': 50 * 1024 * 1024,   # 50MB
    'sanctions':  100 * 1024 * 1024,   # 100MB
    'any':         10 * 1024 * 1024,   # 10MB default
}


def validate_file(file_obj, upload_type='any'):
    """
    Validate uploaded file for security.
    
    Args:
        file_obj: Flask FileStorage object
        upload_type: 'document', 'image', 'spreadsheet', 'sanctions', 'any'
    
    Returns:
        (is_valid: bool, error_message: str)
    """
    if not file_obj or not file_obj.filename:
        return False, _("No file provided")

    filename = file_obj.filename.lower()

    # Step 1: Check for double extensions (e.g. malware.pdf.exe)
    parts = filename.split('.')
    if len(parts) > 2:
        # Allow legitimate double extensions like .tar.gz
        safe_doubles = {('.tar', '.gz'), ('.tar', '.bz2')}
        last_two = (f'.{parts[-2]}', f'.{parts[-1]}')
        if last_two not in safe_doubles:
            logger.warning(f"Rejected double-extension file: {filename}")
            return False, _("Files with multiple extensions are not allowed")

    # Step 2: Check extension is in allowed list
    ext = os.path.splitext(filename)[1]
    allowed = ALLOWED_EXTENSIONS.get(upload_type, ALLOWED_EXTENSIONS['any'])
    if ext not in allowed:
        return False, _("File type '%(ext)s' is not allowed. Allowed: %(allowed)s",
                         ext=ext, allowed=', '.join(sorted(allowed)))

    # Step 3: Read magic bytes
    file_obj.seek(0)
    header = file_obj.read(16)
    file_obj.seek(0)

    # Step 4: Reject known dangerous signatures
    for sig in DANGEROUS_SIGNATURES:
        if header.startswith(sig):
            logger.critical(f"SECURITY: Dangerous file rejected: {filename} sig={sig!r}")
            return False, _("This file type is not allowed for security reasons")

    # Step 5: Validate magic bytes match claimed extension
    if ext == '.pdf':
        if not header.startswith(b'%PDF-'):
            return False, _("File does not appear to be a valid PDF")
    elif ext in ('.jpg', '.jpeg'):
        if not header.startswith(b'\xff\xd8\xff'):
            return False, _("File does not appear to be a valid JPEG image")
    elif ext == '.png':
        if not header.startswith(b'\x89PNG'):
            return False, _("File does not appear to be a valid PNG image")
    elif ext == '.xlsx':
        if not header.startswith(b'PK\x03\x04'):
            return False, _("File does not appear to be a valid Excel file")
    elif ext == '.xls':
        if not header.startswith(b'\xd0\xcf\x11\xe0'):
            return False, _("File does not appear to be a valid Excel file")
    elif ext == '.csv':
        # CSV: verify it's valid UTF-8 or ASCII text
        try:
            header.decode('utf-8')
        except UnicodeDecodeError:
            try:
                header.decode('latin-1')
            except Exception:
                return False, _("CSV file contains invalid characters")

    # Step 6: Check file size
    file_obj.seek(0, 2)  # Seek to end
    file_size = file_obj.tell()
    file_obj.seek(0)
    max_size = MAX_FILE_SIZES.get(upload_type, MAX_FILE_SIZES['any'])
    if file_size > max_size:
        max_mb = max_size // (1024 * 1024)
        return False, _("File too large. Maximum size is %(mb)sMB", mb=max_mb)

    return True, None


def secure_filename_strict(filename):
    """
    Generate a secure filename that strips all dangerous characters.
    More strict than werkzeug's secure_filename.
    """
    import re
    import time
    # Get extension
    ext = os.path.splitext(filename.lower())[1]
    # Generate timestamp-based name to prevent path traversal
    safe_name = re.sub(r'[^a-z0-9_-]', '_', 
                       os.path.splitext(filename.lower())[0])[:50]
    timestamp = int(time.time())
    return f"{safe_name}_{timestamp}{ext}"
