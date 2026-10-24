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
End-to-end FRA demo on the FICTIONAL company "Nile Microfinance S.A.E."
(sales / training only — every name and figure is invented; parameter values
are marked "DEMO VALUE").

    python packs/fra_nbfi/scripts/demo_fra.py setup       # load all demo data, run every control,
                                                          # open findings + action plans for 15 violations
    python packs/fra_nbfi/scripts/demo_fra.py remediate   # fix 6 of them, verify by re-test, close, re-score
    python packs/fra_nbfi/scripts/demo_fra.py repeat      # break one fixed control again -> repeated violation

Walkthrough: docs/DEMO_FRA.md.
"""
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

# (control, finding title, severity) — the 15 violations the demo walks through, across all areas.
SCENARIOS = [
    ('FRA-001', 'Paid-up capital below the licence minimum', 'critical'),
    ('FRA-006', 'Key functions vacant or not notified to the regulator', 'high'),
    ('FRA-007', 'Branch managers without regulator no-objection / long vacancy', 'high'),
    ('FRA-011', 'Portfolio at risk above threshold in a branch', 'high'),
    ('FRA-017', 'Administrative fees above the cap', 'high'),
    ('FRA-023', 'Early repayment followed by a costlier new loan', 'high'),
    ('FRA-027', 'MLRO independence not evidenced', 'high'),
    ('FRA-053', 'Annual AML report not board-approved', 'medium'),
    ('FRA-056', 'Stale balance confirmations for borrowings', 'medium'),
    ('FRA-061', "Exiting shareholders' dues not classified as liabilities", 'medium'),
    ('FRA-051', 'Off-site encrypted backups not in place for every system', 'high'),
    ('FRA-069', 'Penetration test expired; no malware test', 'high'),
    ('FRA-072', 'TLS certificate check failing on the public portal', 'medium'),
    ('FRA-CF-02', 'Carbon activity data incomplete / unsupported', 'medium'),
    ('FRA-CF-05', 'Carbon offset obligation past its deadline', 'high'),
]
FIXES = ['FRA-056', 'FRA-061', 'FRA-051', 'FRA-069', 'FRA-007', 'FRA-CF-05']


def _app():
    from app import create_app
    return create_app()


def _run_all(db):
    from regcontrols import engine
    st = {}
    for r in db.execute("SELECT control_code FROM rc_controls WHERE is_active ORDER BY control_code").fetchall():
        res = engine.run_control(r['control_code'], triggered_by='schedule')
        st[res['status']] = st.get(res['status'], 0) + 1
    return st


def setup():
    for s in ('lending', 'prudential', 'it', 'carbon'):
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'packs', 'fra_nbfi', 'scripts', f'seed_demo_{s}.py')],
                           capture_output=True, text=True)
        print(f'seed {s}: {"ok" if p.returncode == 0 else "FAILED"}')
        if p.returncode:
            print(p.stdout[-800:], p.stderr[-800:])
            return 1
    app = _app()
    with app.app_context():
        from database.db import get_db
        from regcontrols import readiness
        from regcontrols.api import raise_finding
        from regcontrols.findings import add_action
        db = get_db()
        print('controls run:', _run_all(db))
        owner = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()['id']
        for code, title, sev in SCENARIOS:
            c = db.execute("SELECT id, last_status FROM rc_controls WHERE control_code = %s", (code,)).fetchone()
            if not c:
                continue
            fid = raise_finding(f'{title} (demo)', source='regulator', source_ref=f'DEMO-INSPECTION:{code}', severity=sev,
                                control_codes=[code], owner_user_id=owner, due_date=date.today() + timedelta(days=30),
                                description=f'Demo inspection finding. Control {code} result: {c["last_status"]}.',
                                created_by=owner, db=db)
            if not db.execute("SELECT 1 FROM rc_corrective_actions WHERE finding_id = %s", (fid,)).fetchone():
                add_action(fid, f'Remediate {code}: {title.lower()}', owner_user_id=owner,
                           due_date=date.today() + timedelta(days=21), created_by=owner, db=db)
        n = readiness.snapshot(db, on=date.today() - timedelta(days=30))
        readiness.snapshot(db)
        s = readiness.overview(db=db)['overall']
        print(f'findings opened: {len(SCENARIOS)} · readiness now {s["score"]} / 100 ({s["failing"]} failing) · {n} scores stored')
    return 0


def _fix(code, db):
    today, now = date.today(), datetime.now()
    if code == 'FRA-056':
        db.execute("UPDATE pr_facilities SET last_confirmation_date = %s, confirmation_balance = balance", (today,))
    elif code == 'FRA-061':
        db.execute("UPDATE pr_rp_items SET classification = 'liability' WHERE item_type IN ('dues', 'current_account')")
    elif code == 'FRA-051':
        db.execute("""UPDATE cy_backups SET location_type = 'offsite', encrypted = TRUE, last_success_at = %s,
                      last_status = 'success' WHERE is_active""", (now,))
    elif code == 'FRA-069':
        for t in ('pentest', 'malware_test'):
            db.execute("""INSERT INTO cy_assessments (assessment_type, title, provider, performed_on, valid_until, critical_open,
                          status, accepted_at) VALUES (%s, %s, 'Example Security Labs (demo)', %s, %s, 0, 'accepted', %s)""",
                       (t, f'{t} — remediation re-test (demo)', today, today + timedelta(days=365), now))
    elif code == 'FRA-007':
        db.execute("""UPDATE pr_branches SET manager_name = COALESCE(manager_name, 'Appointed manager (demo)'),
                      manager_no_objection = 'granted', manager_no_objection_on = %s, manager_vacant_since = NULL
                      WHERE status = 'active'""", (today,))
    elif code == 'FRA-CF-05':
        db.execute("""INSERT INTO carbon_offset_purchases (obligation_id, project_name, registry_reference, quantity_tco2e,
                      purchase_date, retired_on) SELECT id, 'Example Wind Farm (demo)', 'DEMO-REG-001', required_tco2e, %s, %s
                      FROM carbon_offset_obligations""", (today, today))
        db.execute("UPDATE carbon_offset_obligations SET status = 'FULFILLED'")
    db.commit()


def remediate():
    app = _app()
    with app.app_context():
        from database.db import get_db
        from regcontrols import findings, readiness
        db = get_db()
        before = readiness.overview(db=db)['overall']['score']
        # four-eyes: one person completes the action and asks for verification, another verifies
        doer = db.execute("SELECT id FROM users ORDER BY id OFFSET 1 LIMIT 1").fetchone() or \
            db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        verifier = db.execute("SELECT id FROM users WHERE id <> %s ORDER BY id LIMIT 1", (doer['id'],)).fetchone() or doer
        for code in FIXES:
            f = db.execute("SELECT id, status FROM rc_findings WHERE source_ref = %s", (f'DEMO-INSPECTION:{code}',)).fetchone()
            if not f or f['status'] == 'closed':
                continue
            _fix(code, db)
            for a in db.execute("SELECT id FROM rc_corrective_actions WHERE finding_id = %s", (f['id'],)).fetchall():
                findings.set_action_status(a['id'], 'done', doer['id'], note='Done (demo)', db=db)
            findings.request_verification(f['id'], doer['id'], db=db)
            outcome, runs = findings.verify(f['id'], verifier['id'], db=db)
            print(f'{code}: corrective action done -> re-test {[r["status"] for r in runs]} -> {outcome}')
        _run_all(db)
        readiness.snapshot(db)
        after = readiness.overview(db=db)['overall']['score']
        print(f'readiness score {before} -> {after}')
    return 0


def repeat():
    app = _app()
    with app.app_context():
        from database.db import get_db
        from regcontrols import engine
        db = get_db()
        db.execute("UPDATE cy_backups SET last_success_at = %s, last_status = 'failed' WHERE system_name LIKE 'Accounting%%'",
                   (datetime.now() - timedelta(days=20),))
        db.commit()
        res = engine.run_control('FRA-051', triggered_by='schedule')
        f = db.execute("SELECT reference, status, is_repeated, repeat_count FROM rc_findings WHERE source_ref = %s",
                       ('DEMO-INSPECTION:FRA-051',)).fetchone()
        print(f'FRA-051 -> {res["status"]}; finding {dict(f) if f else None}')
    return 0


if __name__ == '__main__':
    step = sys.argv[1] if len(sys.argv) > 1 else 'setup'
    sys.exit({'setup': setup, 'remediate': remediate, 'repeat': repeat}[step]())
