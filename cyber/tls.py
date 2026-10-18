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
Real TLS certificate check for monitored domains (FRA-072-style controls, but
generic): opens a verified TLS connection, reads the peer certificate and
returns its subject, issuer and expiry. A certificate that fails verification
(expired, wrong host, untrusted chain) is reported as an error with the
reason — never as valid.
"""

import socket
import ssl
from datetime import datetime, timezone


def _name(parts):
    return ', '.join('='.join(x) for rdn in parts or () for x in rdn)


def check(domain, port=443, timeout=8):
    """→ {'subject', 'issuer', 'not_after' (naive UTC datetime), 'error'}."""
    out = {'subject': None, 'issuer': None, 'not_after': None, 'error': None}
    host = (domain or '').strip().lower()
    for prefix in ('https://', 'http://'):
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.split('/')[0]
    if not host:
        out['error'] = 'no domain'
        return out
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, int(port or 443)), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
        out['subject'] = _name(cert.get('subject'))
        out['issuer'] = _name(cert.get('issuer'))
        out['not_after'] = parse_not_after(cert.get('notAfter'))
    except ssl.SSLCertVerificationError as e:
        out['error'] = f'certificate not valid: {e.verify_message or e}'
    except (ssl.SSLError, OSError) as e:
        out['error'] = f'connection failed: {e}'
    return out


def parse_not_after(value):
    if not value:
        return None
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(value), tz=timezone.utc).replace(tzinfo=None)
