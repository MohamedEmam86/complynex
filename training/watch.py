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
Server-side rules for course completion (no database access; unit-tested).

Watch time is credited by the SERVER from the time between two heartbeats of
the player, never from what the browser says it watched: a heartbeat credits
at most the wall-clock time since the previous one (capped, so a tab left in
the background or a paused player does not count), and the video counts as
watched once the credited seconds reach the course's threshold (default 90%)
of the video length. The client cannot post a "completed" flag.
"""

from datetime import datetime

DEFAULT_THRESHOLD_PCT = 90
DEFAULT_MAX_ATTEMPTS = 3
HEARTBEAT_MAX_CREDIT = 15      # seconds credited at most per heartbeat (player sends one every ~5 s)
HEARTBEAT_STALE_AFTER = 60     # a longer gap starts a new viewing session (nothing credited)


def threshold_pct(course_value):
    try:
        v = int(course_value)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD_PCT
    return min(max(v, 10), 100)


def max_attempts(course_value):
    try:
        v = int(course_value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ATTEMPTS
    return max(v, 1)


def credit_seconds(last_heartbeat, now=None, playing=True):
    """Seconds to credit for this heartbeat."""
    if not playing or last_heartbeat is None:
        return 0
    now = now or datetime.now()
    gap = (now - last_heartbeat).total_seconds()
    if gap <= 0 or gap > HEARTBEAT_STALE_AFTER:
        return 0
    return int(min(gap, HEARTBEAT_MAX_CREDIT))


def video_length(course_seconds, duration_minutes=None):
    """Video length used for the threshold. Only lengths known to the SERVER
    count: the course's recorded length (entered by the training administrator
    or read from the uploaded file); else the course's declared duration, so
    the credited watch time must reach the declared minutes. A length reported
    by the browser is never used - it could be forged to complete in seconds."""
    try:
        v = int(float(course_seconds))
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    try:
        m = int(duration_minutes)
        return m * 60 if m > 0 else None
    except (TypeError, ValueError):
        return None


def watched_pct(watched_seconds, length):
    if not length:
        return 0
    return min(100, int(100 * (watched_seconds or 0) / length))


def completion_reached(watched_seconds, length, pct=DEFAULT_THRESHOLD_PCT):
    return bool(length) and (watched_seconds or 0) >= length * (threshold_pct(pct) / 100.0)


def attempts_remaining(max_allowed, used, extra=0):
    return max(0, max_attempts(max_allowed) + int(extra or 0) - int(used or 0))


def quiz_language(course_language, ui_language):
    """Language the quiz is served in: the course's language when it has one,
    otherwise the interface language."""
    lang = (course_language or '').strip().lower()
    if lang in ('ar', 'en'):
        return lang
    return 'ar' if (ui_language or '') == 'ar' else 'en'


def localize_question(q, lang):
    """Question text and options in `lang`, falling back to the other language
    when a translation is missing. Options keep their order (grading uses the
    option index), so translated options are used only when complete."""
    en_text, ar_text = q.get('question_text'), q.get('question_text_ar')
    en_opts, ar_opts = q.get('options') or [], q.get('options_ar') or []
    if lang == 'ar':
        text = ar_text or en_text
        opts = ar_opts if ar_opts and (not en_opts or len(ar_opts) == len(en_opts)) else en_opts
    else:
        text = en_text or ar_text
        opts = en_opts or ar_opts
    out = dict(q)
    out['display_text'] = text
    out['display_options'] = opts
    out['display_dir'] = 'rtl' if lang == 'ar' and (ar_text or ar_opts) else 'auto'
    return out
