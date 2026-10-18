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
Network guard: the AI layer may only talk to the customer's own machines.

A URL is accepted only when its host is localhost or resolves exclusively to
loopback / private / link-local addresses (RFC 1918, RFC 4193, 100.64/10).
Checked when the setting is saved AND before every call (DNS can change).
"""

import ipaddress
import socket
from urllib.parse import urlparse


class NotLocalError(ValueError):
    pass


def _private(ip):
    a = ipaddress.ip_address(ip)
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_loopback or a.is_private or a.is_link_local or (a.version == 4 and a in ipaddress.ip_network('100.64.0.0/10'))


def check_local_url(url, resolver=None):
    """Return the URL if it points at the local / private network, else raise NotLocalError."""
    p = urlparse((url or '').strip())
    if p.scheme not in ('http', 'https') or not p.hostname:
        raise NotLocalError('URL must be http(s)://host[:port]')
    if p.username or p.password:
        raise NotLocalError('credentials in the URL are not allowed')
    host = p.hostname
    try:
        addrs = [host] if _is_ip(host) else [ai[4][0] for ai in (resolver or socket.getaddrinfo)(host, p.port or 80)]
    except (socket.gaierror, UnicodeError):
        raise NotLocalError(f'cannot resolve host {host}')
    if not addrs:
        raise NotLocalError(f'cannot resolve host {host}')
    bad = [a for a in addrs if not _private(a)]
    if bad:
        raise NotLocalError(f'{host} resolves to a public address ({bad[0]}); only local / private hosts are allowed')
    return url.strip().rstrip('/')


def _is_ip(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False
