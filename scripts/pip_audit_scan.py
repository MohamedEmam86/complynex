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
Weekly dependency vulnerability scan (P6c hardening punch list): runs
pip-audit against the packages actually installed in venv/, not against
requirements.txt's own resolution (`pip-audit -r requirements.txt` fails here
- it does a fresh dependency solve that conflicts with the pinned installer
pip-audit bundles - so this scans the live environment instead, which is
also more honest about what's actually running).

Only publishes a compliance event (security.vuln_scan_completed) when
vulnerabilities are found - a clean scan stays silent, since the
event_routing_rules notify rule fires per-event, not per-schedule.

Runs as a weekly systemd timer (complynex-pip-audit.timer). Safe to run
manually: python scripts/pip_audit_scan.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIP_AUDIT_BIN = os.path.join(APP_ROOT, 'venv', 'bin', 'pip-audit')


def run_scan():
    proc = subprocess.run(
        [PIP_AUDIT_BIN, '--format', 'json'],
        capture_output=True, text=True,
    )
    if not proc.stdout:
        print(f"pip-audit produced no output (exit {proc.returncode}): {proc.stderr}")
        return

    report = json.loads(proc.stdout)
    vulnerable = [
        {'name': dep['name'], 'version': dep['version'],
         'vuln_ids': [v['id'] for v in dep['vulns']]}
        for dep in report.get('dependencies', []) if dep.get('vulns')
    ]

    if not vulnerable:
        print("pip-audit: no known vulnerabilities found.")
        return

    vuln_count = sum(len(d['vuln_ids']) for d in vulnerable)
    print(f"pip-audit: {vuln_count} known vulnerabilit(y/ies) in {len(vulnerable)} package(s).")
    for d in vulnerable:
        print(f"  {d['name']}=={d['version']}: {', '.join(d['vuln_ids'])}")

    from app import create_app
    from events.publisher import publish_event

    app = create_app()
    with app.app_context():
        publish_event(
            event_type='security.vuln_scan_completed',
            source_module='Security',
            payload={
                'vulnerability_count': vuln_count,
                'package_count': len(vulnerable),
                'packages': vulnerable,
            },
        )


if __name__ == '__main__':
    run_scan()
