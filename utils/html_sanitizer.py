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
Sanitize rich-text HTML submitted through forms (policy content, training
course content, and similar 'the user pastes/writes formatted text' fields)
before it is stored, so it can safely be rendered later with Jinja's `|safe`
filter without becoming a stored-XSS vector.

Added 2026-07-24 after a sanitize audit found policies/routes.py and
training/routes.py saving `request.form.get('content')` verbatim and
rendering it with `{{ ... | safe }}` — any user permitted to edit a policy
or training course could otherwise plant a <script> tag that fires in the
browser of every other user who later views that policy/course.

Uses nh3 (Rust-based, actively maintained ammonia binding) rather than
bleach, which is effectively unmaintained. The allowlist below covers
normal rich-text formatting (bold/italic/underline, headings, lists,
tables, links, images) and strips everything else (script, style, iframe,
on*, javascript: URLs, etc.) by default — nh3's default behavior is a
strict allowlist, so anything not explicitly listed here is removed.
"""
import nh3

_ALLOWED_TAGS = {
    'p', 'br', 'hr', 'b', 'strong', 'i', 'em', 'u', 's', 'strike', 'sub', 'sup',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a', 'img', 'span', 'div',
}

_ALLOWED_ATTRIBUTES = {
    # 'rel' deliberately excluded — nh3 manages it automatically via the
    # link_rel= option below, and having it in both places raises ValueError.
    'a': {'href', 'title', 'target'},
    'img': {'src', 'alt', 'title', 'width', 'height'},
    'span': {'style'},
    'div': {'style'},
    'table': {'border'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan'},
}

# Only allow safe URL schemes for links/images — blocks javascript:, data:
# (except harmless image data URIs are still blocked too, deliberately;
# evidence/media should be uploaded as files, not inlined as data: URIs).
_ALLOWED_URL_SCHEMES = {'http', 'https', 'mailto'}


def sanitize_html(html_text):
    """Return a sanitized copy of html_text safe to store and later render
    with `|safe`. None/empty input passes through unchanged."""
    if not html_text:
        return html_text
    return nh3.clean(
        html_text,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_ALLOWED_URL_SCHEMES,
        link_rel='noopener noreferrer',
    )
