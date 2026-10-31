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
P4-7 — one evidence pack (PDF) per screening.

What an examiner asks for, in one document: what was screened (inputs and the
input-quality warnings), against which lists and which version of each list
was in force at that moment, with which settings, what the engine found (every
hit with its score, explanation, identity verdict and the action it calls for),
what was cleared earlier and why, and every human decision with who / when /
why.

The pack's content is serialised canonically and hashed (SHA-256). The hash is
printed on every page and stored in screening_evidence_packs, so a pack handed
to an examiner can later be checked against the system. The same screening can
produce a new pack after a later decision; each issue is recorded.
"""
import hashlib
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _j(v, default=None):
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return json.loads(v)
        except ValueError:
            return default
    return default


def canonical(content):
    """Stable serialisation: sorted keys, no whitespace, str() for dates."""
    return json.dumps(content, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)


def content_hash(content):
    return hashlib.sha256(canonical(content).encode('utf-8')).hexdigest()


def _wf_view(w):
    """The workflow block (screening/workflow.py) reduced to plain bilingual text for the pack."""
    if not isinstance(w, dict):
        return None
    a = w.get('action') if isinstance(w.get('action'), dict) else {}
    e = w.get('explanation') if isinstance(w.get('explanation'), dict) else {}
    i = w.get('identity_status') if isinstance(w.get('identity_status'), dict) else {}
    def _p(d, k):
        d = d.get(k) if isinstance(d, dict) else None
        return d if isinstance(d, dict) else {}
    return {
        'list_type': {'en': _p(a, 'list_label').get('en'), 'ar': _p(a, 'list_label').get('ar')},
        'action': {'en': _p(a, 'label').get('en'), 'ar': _p(a, 'label').get('ar')},
        'step': {'en': _p(a, 'step').get('en'), 'ar': _p(a, 'step').get('ar')},
        'explanation': {'en': list(e.get('en') or []), 'ar': list(e.get('ar') or [])},
        'identity': {'state': i.get('state'), 'en': i.get('en'), 'ar': i.get('ar')},
    }


def _hits(matches, inputs):
    from screening.match_classifier import split_matches
    from screening import result_view as rv
    s, p, o = split_matches([m for m in (matches or []) if isinstance(m, dict)])
    out = []
    for kind, group in (('SANCTIONS', s), ('PEP', p), ('OTHER', o)):
        for m in group:
            try:
                v = rv.match_view(m, kind, inputs)
            except Exception as e:                       # never drop a hit from the pack
                logger.warning('evidence pack: match_view failed: %s', e)
                v = {'display_name': m.get('full_name') or m.get('watchlist_name_ar'), 'score': m.get('match_score'),
                     'source': m.get('source'), 'tier': None, 'reasons': [], 'identity_label': None}
            out.append({
                'kind': kind,
                'name': v.get('display_name'),
                'latin': v.get('lat_name'), 'arabic': v.get('ar_name'),
                'source': v.get('source'), 'ref': v.get('ref'),
                'score': v.get('score'), 'original_score': v.get('original_score'),
                'tier': v.get('tier_label') or v.get('tier'),
                'identity': v.get('identity_label') or v.get('identity'),
                'identity_rows': [{k: r.get(k) for k in ('label', 'screened', 'listed', 'state')}
                                  for r in (v.get('identity_rows') or []) if isinstance(r, dict)],
                'reasons': [((r.get('t') or '') + ((' ' + r.get('a')) if r.get('a') else '')).strip()
                            for r in (v.get('reasons') or []) if isinstance(r, dict)],
                'action': v.get('action'),
                'program': v.get('program'), 'listed_since': v.get('listed_since'),
                'nature': (v.get('nature') or {}).get('label') if isinstance(v.get('nature'), dict) else None,
                'grouped_under': v.get('grouped_under'),
                'clearance': m.get('clearance') if isinstance(m.get('clearance'), dict) else None,
                # P4-2 / P4-3 / G9 (p4-core): list-type action, explanation, identity status
                'workflow': _wf_view(v.get('workflow')),
            })
    return out


def build(result_id):
    """(content dict, sha256) for one screening result, read from the database."""
    from database.db import query_db
    from screening import clearance as CL
    r = query_db("""
        SELECT r.*, TRIM(COALESCE(cu.first_name,'') || ' ' || COALESCE(cu.last_name,'')) AS screened_by_name,
               TRIM(COALESCE(rv.first_name,'') || ' ' || COALESCE(rv.last_name,'')) AS resolved_by_name
          FROM screening_results r
          LEFT JOIN users cu ON cu.id = r.created_by
          LEFT JOIN users rv ON rv.id = r.resolved_by
         WHERE r.id = %s""", (result_id,), one=True)
    if not r:
        return None, None
    md = _j(r.get('match_details'), {}) or {}
    inputs = md.get('inputs') or {}
    matches = _j(r.get('matches'), []) or []
    matches = sorted([m for m in matches if isinstance(m, dict)],
                     key=lambda m: m.get('match_score') or 0, reverse=True)

    # lists and the version of each in force when the screening ran
    lists = []
    try:
        from screening import result_view as rv
        for c in rv.coverage(at=r.get('created_at')) or []:
            lists.append({'name': c.get('name'), 'source': c.get('source'), 'records': c.get('records'),
                          'version_at_screening': c.get('version_at'), 'state_now': c.get('state')})
    except Exception as e:
        logger.warning('evidence pack: coverage failed: %s', e)

    settings = {}
    try:
        from screening import thresholds as TH
        settings['tier_thresholds'] = TH.current()
    except Exception:
        pass
    settings['clearance_approval_threshold'] = CL.approval_threshold()
    for key in ('whitelist_legacy_mode', 'clearance_sla_hours', 'regulatory_lists_scope'):
        try:
            row = query_db("SELECT config_value FROM screening_config WHERE config_key = %s", (key,), one=True)
            if row:
                settings[key] = row['config_value']
        except Exception:
            pass

    # every human decision on the result and on its queue items
    decisions = []
    for d in CL.decision_history('result', result_id) or []:
        decisions.append({'on': 'result', 'action': d.get('action'), 'decision': d.get('decision'),
                          'reason': d.get('reason'), 'by': d.get('actor_name') or d.get('actor_email'),
                          'at': d.get('created_at')})
    try:
        q = query_db("""
            SELECT q.id, q.match_name, q.match_score, q.status, q.resolution, q.resolution_notes, q.resolved_date,
                   TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS resolved_by_name
              FROM screening_queue q
              JOIN screening_history h ON h.id = q.screening_history_id
              LEFT JOIN users u ON u.id = q.resolved_by
             WHERE h.screening_result_id = %s
             ORDER BY q.id""", (result_id,)) or []
    except Exception:
        q = []
    queue = []
    for it in q:
        queue.append({'id': it['id'], 'hit': it['match_name'], 'score': it['match_score'], 'status': it['status'],
                      'resolution': it['resolution'], 'notes': it['resolution_notes'],
                      'by': it['resolved_by_name'], 'at': it['resolved_date']})
        for d in CL.decision_history('queue', it['id']) or []:
            decisions.append({'on': f"queue #{it['id']}", 'action': d.get('action'), 'decision': d.get('decision'),
                              'reason': d.get('reason'), 'by': d.get('actor_name') or d.get('actor_email'),
                              'at': d.get('created_at')})
    decisions.sort(key=lambda d: str(d.get('at') or ''))

    content = {
        'pack_version': 1,
        'screening': {
            'result_id': r['id'], 'name': r.get('screened_name'), 'type': r.get('screening_type'),
            'method': r.get('screening_method'), 'run_at': r.get('created_at'),
            'run_by': r.get('screened_by_name'),
            'engine_result': r.get('screening_result'), 'highest_score': r.get('highest_match_score'),
            'hits': r.get('total_matches_found'), 'search_degraded': bool(r.get('search_degraded')),
            'status': r.get('status'), 'resolved_by': r.get('resolved_by_name'), 'resolved_at': r.get('resolved_at'),
            'resolution_notes': r.get('resolution_notes'),
        },
        'inputs': {k: v for k, v in inputs.items() if v not in (None, '', 'None')},
        'input_warnings': [{'code': w.get('code'), 'en': w.get('en') or w.get('message'), 'ar': w.get('ar')}
                           for w in (md.get('input_warnings') or []) if isinstance(w, dict)],
        # P4-1 (p4-core): sources unavailable during the screening
        'incomplete': bool(md.get('incomplete_reasons')) or r.get('screening_result') == 'INCOMPLETE',
        'incomplete_reasons': [{'en': w.get('en'), 'ar': w.get('ar')}
                               for w in (md.get('incomplete_reasons') or []) if isinstance(w, dict)],
        'coverage_warnings': [{'en': w.get('en'), 'ar': w.get('ar')}
                              for w in (md.get('coverage_warnings') or []) if isinstance(w, dict)],
        'lists': lists,
        'settings': settings,
        'hits': _hits(matches, inputs),
        'cleared_earlier': [{'name': c.get('full_name') or c.get('watchlist_name_ar'), 'source': c.get('source'),
                             'score': c.get('match_score'), 'clearance': c.get('clearance')}
                            for c in (md.get('cleared_matches') or []) if isinstance(c, dict)],
        'adverse_media': {'hits': len(_j(r.get('adverse_media'), []) or []),
                          'summary': _j(r.get('adverse_media_summary'), {}) or {}},
        'queue': queue,
        'decisions': decisions,
    }
    return content, content_hash(content)


def render_pdf(content, digest, generated_by, base_url):
    from flask import render_template
    from weasyprint import HTML
    html = render_template('screening/evidence_pack.html', c=content, digest=digest,
                           generated_by=generated_by, generated_at=datetime.now())
    return HTML(string=html, base_url=base_url).write_pdf()


def record(result_id, digest, user_id, size):
    from database.db import execute_db
    try:
        execute_db("""INSERT INTO screening_evidence_packs (result_id, sha256, generated_by, size_bytes)
                      VALUES (%s,%s,%s,%s)""", (result_id, digest, user_id, size))
    except Exception as e:
        logger.error('evidence pack record failed: %s', e)
