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

"""Inspection-readiness pages: executive dashboard, area drill-down, board
report (printable / PDF), per-area evidence pack (ZIP) and the unified
regulatory calendar."""

from datetime import date, datetime, timedelta

from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user

from database.db import get_db

from . import readiness as R
from . import readiness_logic as RL
from . import regcontrols_bp as bp
from .routes import _log, rc_required


def _fw():
    return request.args.get('framework', type=int)


@bp.route('/readiness')
@rc_required('view')
def readiness():
    return render_template('regcontrols/readiness/dashboard.html', d=R.overview(_fw()), fw=_fw(), today=date.today())


@bp.route('/readiness/area/<area>')
@rc_required('view')
def readiness_area(area):
    db = get_db()
    cs = R.controls(db, _fw(), area)
    if not cs:
        abort(404)
    ids = [c['id'] for c in cs]
    ev = [e for e in __import__('regcontrols.evidence', fromlist=['x']).list_all(db=db) if e['control_id'] in ids]
    fids = {r['finding_id'] for r in db.execute("SELECT finding_id FROM rc_finding_controls WHERE control_id = ANY(%s)",
                                                 (ids,)).fetchall()}
    fnd = [f for f in __import__('regcontrols.findings', fromlist=['x']).list_findings(db=db) if f['id'] in fids]
    return render_template('regcontrols/readiness/area.html', area=area, label=R.area_labels(db).get(area, area),
                           s=RL.score(cs), controls=cs, evidence=ev, findings=fnd, trend=R.trend(_fw(), area, db=db),
                           fw=_fw())


@bp.route('/readiness/board')
@rc_required('view')
def readiness_board():
    d = R.overview(_fw())
    pdf = request.args.get('format') == 'pdf'
    html = render_template('regcontrols/readiness/board.html', d=d, generated_at=datetime.now(), pdf=pdf)
    if not pdf:
        return html
    from weasyprint import HTML
    _log('regcontrols_readiness_board_pdf')
    return Response(HTML(string=html, base_url=request.url_root).write_pdf(), mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename=readiness_board_{date.today()}.pdf'})


@bp.route('/readiness/pack')
@rc_required('view')
def readiness_pack():
    area = request.args.get('area') or None
    db = get_db()
    cs = R.controls(db, _fw(), area)
    from weasyprint import HTML
    index = render_template('regcontrols/readiness/pack_index.html', area=area,
                            label=R.area_labels(db).get(area, area) if area else _('All areas'), s=RL.score(cs), controls=cs,
                            generated_at=datetime.now())
    data, cs, nfiles, missing = R.evidence_pack(area, _fw(), HTML(string=index, base_url=request.url_root).write_pdf(), db)
    _log('regcontrols_evidence_pack', None, f'{area or "all"}: {len(cs)} controls, {nfiles} files')
    return Response(data, mimetype='application/zip',
                    headers={'Content-Disposition': f'attachment; filename=inspection_pack_{area or "all"}_{date.today()}.zip'})


@bp.route('/readiness/snapshot', methods=['POST'])
@rc_required('edit')
def readiness_snapshot():
    n = R.snapshot()
    flash(_('Readiness snapshot saved (%(n)s scores).', n=n), 'success')
    return redirect(url_for('regcontrols.readiness'))


@bp.route('/calendar')
@rc_required('view')
def reg_calendar():
    days = request.args.get('days', 120, type=int)
    items = R.calendar_items(date.today() - timedelta(days=30), date.today() + timedelta(days=max(7, min(days, 730))))
    if request.args.get('format') == 'ics':
        lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ComplyNex//Regulatory calendar//EN']
        for i in items:
            lines += ['BEGIN:VEVENT', f"UID:{i['key']}@complynex", f"DTSTART;VALUE=DATE:{i['date']:%Y%m%d}",
                      f"SUMMARY:{i['title'][:200]}", f"DESCRIPTION:{i['kind']} · {i['status']}", 'END:VEVENT']
        lines.append('END:VCALENDAR')
        return Response('\r\n'.join(lines), mimetype='text/calendar',
                        headers={'Content-Disposition': 'attachment; filename=regulatory_calendar.ics'})
    return render_template('regcontrols/readiness/calendar.html', items=items, days=days, today=date.today())
