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
ESG Management — scoring engine.

Pure functions only, same discipline as carbon/engine.py. The scoring
model is entirely data-driven (framework -> pillars -> indicators, each
carrying its own weight) — nothing here hardcodes a pillar name, a weight
value, or an indicator count. That is a deliberate fix for the pattern
found in the Integrys workbooks, where the scoring formula was typed once
into a spreadsheet cell and silently diverged from a second, differently
weighted version six months later with no way to tell which was current.

Score scale: every indicator is scored 1-5 (a maturity scale — 1 = not
started / non-existent, 5 = fully embedded & continuously improved), matching
the maturity-model language already familiar to the compliance team from
internal audit and risk assessments elsewhere in ComplyNex.
"""

MATURITY_LABELS = {
    1: "Not Started",
    2: "Basic / Ad-hoc",
    3: "Developing",
    4: "Managed",
    5: "Optimized",
}


def compute_pillar_score(indicator_scores):
    """indicator_scores: list of {'weight': float, 'score': float|None}.
    Un-scored indicators (score is None — not yet answered this period)
    are excluded from both numerator and denominator so a partially
    completed pillar still shows an honest score for what HAS been
    answered, rather than silently treating blanks as zero (the exact
    bug pattern that deflated scores in the reviewed workbooks whenever a
    row was left blank).
    Returns (score_out_of_5, pct_of_indicators_answered).
    """
    answered = [i for i in indicator_scores if i.get('score') is not None]
    if not answered:
        return None, 0.0

    weight_sum = sum(i['weight'] for i in answered)
    if weight_sum <= 0:
        return None, 0.0

    weighted = sum(i['weight'] * i['score'] for i in answered) / weight_sum
    completeness = round(100.0 * len(answered) / len(indicator_scores), 1) if indicator_scores else 0.0
    return round(weighted, 3), completeness


def compute_overall_score(pillar_results):
    """pillar_results: list of {'weight': float, 'score': float|None}.
    Same "exclude unanswered" discipline as compute_pillar_score, applied
    one level up. Returns (overall_score_out_of_5, overall_pct, as_100).
    """
    answered = [p for p in pillar_results if p.get('score') is not None]
    if not answered:
        return None, None

    weight_sum = sum(p['weight'] for p in answered)
    if weight_sum <= 0:
        return None, None

    weighted = sum(p['weight'] * p['score'] for p in answered) / weight_sum
    as_100 = round((weighted / 5.0) * 100, 1)
    return round(weighted, 3), as_100


def rating_band(score_out_of_5):
    """Maps a 1-5 score to a plain-language rating band shown in the UI
    next to the raw number, so a non-specialist reading the dashboard
    doesn't need to interpret '3.4' unaided."""
    if score_out_of_5 is None:
        return None
    if score_out_of_5 >= 4.5:
        return ('Leading', '#198754')
    if score_out_of_5 >= 3.5:
        return ('Advanced', '#20c997')
    if score_out_of_5 >= 2.5:
        return ('Developing', '#fd7e14')
    if score_out_of_5 >= 1.5:
        return ('Basic', '#dc3545')
    return ('Not Started', '#adb5bd')


def build_pillar_summary(pillars_with_indicators):
    """pillars_with_indicators: list of dicts:
        {'code','name','weight','indicators':[{'weight','score',...}, ...]}
    Returns a list of pillar summaries (score, completeness, rating band)
    plus the overall framework score, in one pass — this is the single
    function routes.py calls to render both the ESG dashboard and the
    scoring-entry page's live summary panel, so the two views can never
    show different numbers for the same period.
    """
    pillar_summaries = []
    for pillar in pillars_with_indicators:
        score, completeness = compute_pillar_score(pillar['indicators'])
        pillar_summaries.append({
            'code': pillar['code'],
            'name': pillar['name'],
            'weight': pillar['weight'],
            'score': score,
            'completeness_pct': completeness,
            'rating': rating_band(score),
            'indicator_count': len(pillar['indicators']),
            'answered_count': len([i for i in pillar['indicators'] if i.get('score') is not None]),
        })

    overall_score, overall_pct_100 = compute_overall_score(
        [{'weight': p['weight'], 'score': p['score']} for p in pillar_summaries]
    )
    return {
        'pillars': pillar_summaries,
        'overall_score': overall_score,
        'overall_pct_100': overall_pct_100,
        'overall_rating': rating_band(overall_score),
    }
