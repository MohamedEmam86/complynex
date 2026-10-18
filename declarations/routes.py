"""Annual declaration campaigns — GHE / COI / COBEC (Phase 5)."""
import csv
import io as _io

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, Response)
from flask_login import login_required, current_user

from database.db import query_db
from utils.decorators import permission_required
from services import declaration_service as DS, org_service as O
from services.notification_service import delivery_status

declarations_bp = Blueprint('declarations', __name__, url_prefix='/declarations')


@declarations_bp.route('/')
@login_required
@permission_required('config')
def index():
    campaigns = query_db("""SELECT c.*, o.name_en AS scope_name,
                                   (SELECT count(*) FROM declaration_campaign_targets t
                                     WHERE t.campaign_id=c.id) AS targets
                            FROM declaration_campaigns c
                            LEFT JOIN org_units o ON o.id = c.org_scope_unit_id
                            ORDER BY c.cycle_year DESC, c.id DESC""")
    rows = []
    for c in campaigns:
        d = dict(c); d['stats'] = DS.stats(d['id']); rows.append(d)
    return render_template('declarations/index.html', campaigns=rows,
                           org_units=O.get_tree(), modules=DS.MODULES,
                           delivery=delivery_status())


@declarations_bp.route('/create', methods=['POST'])
@login_required
@permission_required('config')
def create():
    cid, msg = DS.create_campaign(
        request.form.get('module'),
        (request.form.get('name') or '').strip(),
        int(request.form.get('cycle_year') or 2026),
        request.form.get('due_at') or None,
        request.form.get('org_scope_unit_id') or None,
        bool(request.form.get('include_descendants')),
        created_by=current_user.id)
    flash(msg, 'success' if cid else 'danger')
    return redirect(url_for('declarations.detail', campaign_id=cid) if cid
                    else url_for('declarations.index'))


@declarations_bp.route('/<int:campaign_id>')
@login_required
@permission_required('config')
def detail(campaign_id):
    DS.sync_submissions(campaign_id)
    c = query_db("SELECT * FROM declaration_campaigns WHERE id=%s", (campaign_id,), one=True)
    if not c:
        flash('Campaign not found.', 'danger')
        return redirect(url_for('declarations.index'))
    return render_template('declarations/detail.html', c=dict(c),
                           stats=DS.stats(campaign_id),
                           people=DS.participants(campaign_id),
                           history=DS.reminder_history(campaign_id),
                           modules=DS.MODULES, delivery=delivery_status())


@declarations_bp.route('/<int:campaign_id>/remind', methods=['POST'])
@login_required
@permission_required('config')
def remind(campaign_id):
    ids = [int(x) for x in request.form.getlist('user_ids') if x.isdigit()]
    n, msg = DS.send_reminders(campaign_id, current_user.id,
                               user_ids=ids or None,
                               message=request.form.get('message') or None)
    flash(msg, 'success' if n else 'info')
    return redirect(url_for('declarations.detail', campaign_id=campaign_id))


@declarations_bp.route('/<int:campaign_id>/refresh', methods=['POST'])
@login_required
@permission_required('config')
def refresh(campaign_id):
    n = DS.refresh_targets(campaign_id)
    flash(f'Participant list refreshed — {n} new person(s) added.', 'success')
    return redirect(url_for('declarations.detail', campaign_id=campaign_id))


@declarations_bp.route('/<int:campaign_id>/export.<fmt>')
@login_required
@permission_required('config')
def export(campaign_id, fmt):
    which = request.args.get('which', 'all')
    rows = DS.export_rows(campaign_id, which)
    if not rows:
        flash('Nothing to export for that filter.', 'warning')
        return redirect(url_for('declarations.detail', campaign_id=campaign_id))

    c = dict(query_db("SELECT module, cycle_year FROM declaration_campaigns WHERE id=%s",
                      (campaign_id,), one=True))
    base = f"{c['module']}_{c['cycle_year']}_{which}"

    if fmt == 'xlsx':
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
            wb = Workbook(); ws = wb.active; ws.title = 'Declarations'
            hdr = list(rows[0].keys())
            ws.append(hdr)
            for cell in ws[1]:
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill('solid', fgColor='1F4E79')
            for r in rows:
                ws.append([r[h] for h in hdr])
            for i, h in enumerate(hdr, 1):
                width = max(len(str(h)), *(len(str(r[h])) for r in rows)) + 2
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width, 40)
            ws.freeze_panes = 'A2'
            buf = _io.BytesIO(); wb.save(buf); buf.seek(0)
            return Response(buf.read(),
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                headers={'Content-Disposition': f'attachment; filename={base}.xlsx'})
        except ImportError:
            flash('openpyxl is not installed — exported as CSV instead.', 'warning')
            fmt = 'csv'

    out = _io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={base}.csv'})


@declarations_bp.route('/reminders', methods=['GET', 'POST'])
@login_required
@permission_required('config')
def bulk_reminders():
    """Send reminders across GHE, COI and COBEC in one action.

    Chasing three declarations separately is three logins, three screens and
    three chances to miss someone. This targets whoever is outstanding across
    whichever modules are selected, de-duplicated so a person owing all three
    gets one message naming all three rather than three separate nags.
    """
    from database.db import query_db
    from services.notification_service import notify, delivery_status

    campaigns = query_db("""SELECT c.*, o.name_en AS scope_name
                            FROM declaration_campaigns c
                            LEFT JOIN org_units o ON o.id = c.org_scope_unit_id
                            WHERE c.status <> 'closed'
                            ORDER BY c.module, c.cycle_year DESC""")

    if request.method == 'POST':
        modules = request.form.getlist('modules')
        if not modules:
            flash('Select at least one declaration type.', 'warning')
            return redirect(url_for('declarations.bulk_reminders'))

        which = request.form.get('which', 'outstanding')
        custom = (request.form.get('message') or '').strip()

        # user_id -> the declarations they still owe
        owed, campaign_ids = {}, []
        for c in campaigns:
            c = dict(c)
            if c['module'] not in modules:
                continue
            campaign_ids.append(c['id'])
            DS.sync_submissions(c['id'])
            for p in DS.participants(c['id']):
                if which == 'outstanding' and p['status'] not in ('pending', 'overdue'):
                    continue
                if which == 'overdue' and p['status'] != 'overdue':
                    continue
                owed.setdefault(p['user_id'], []).append(
                    f"{DS.MODULES[c['module']]['label']} ({c['cycle_year']})")

        if not owed:
            flash('Nobody is outstanding for the selected declarations.', 'info')
            return redirect(url_for('declarations.bulk_reminders'))

        sent = 0
        for uid, items in owed.items():
            body = custom or (
                'The following declaration(s) are still outstanding:\n\n  - '
                + '\n  - '.join(items)
                + '\n\nPlease complete them at your earliest convenience.')
            notify(uid, 'Outstanding declarations — action required', body,
                   link='/declarations/', category='warning',
                   channels=('inapp', 'email'))
            sent += 1

        from database.db import execute_db
        d = delivery_status()
        for cid in campaign_ids:
            execute_db("""INSERT INTO reminder_log
                            (campaign_id, sent_by, recipients, channel, subject,
                             message, target_filter)
                          VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                       (cid, current_user.id, sent,
                        'inapp+email' if d['email'] else 'inapp',
                        'Bulk declaration reminder', custom or '(standard text)',
                        f"{which} · {', '.join(modules)}"))

        note = '' if d['email'] else ' (in-app only — email is not configured yet)'
        flash(f'Reminded {sent} people across {len(modules)} declaration type(s){note}. '
              f'Anyone owing more than one received a single message listing all of them.',
              'success')
        return redirect(url_for('declarations.bulk_reminders'))

    # counts per module, for the form
    counts = {}
    for c in campaigns:
        c = dict(c)
        st = DS.stats(c['id'])
        m = counts.setdefault(c['module'], {'pending': 0, 'overdue': 0, 'campaigns': 0})
        m['pending'] += st['pending']; m['overdue'] += st['overdue']; m['campaigns'] += 1

    return render_template('declarations/reminders.html',
                           campaigns=campaigns, modules=DS.MODULES,
                           counts=counts, delivery=delivery_status(),
                           history=query_db("""SELECT r.*, u.first_name, u.last_name
                                               FROM reminder_log r
                                               LEFT JOIN users u ON u.id = r.sent_by
                                               ORDER BY r.sent_at DESC LIMIT 15"""))
