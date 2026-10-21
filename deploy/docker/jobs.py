"""Scheduled jobs for the container stack (the systemd timers of a VM install).
Times are server-local; each job runs in its own process and logs to stdout."""
import subprocess, sys, time
from datetime import datetime

JOBS = [  # (name, minutes past midnight or None, every-N-minutes or None, command)
    ('sanctions-update', 3 * 60 + 30, None, ['scripts/run_sanctions_update.py']),
    ('screening-delta', 4 * 60 + 10, None, ['scripts/screening_delta_rescreen.py']),
    ('semantic-incremental', 4 * 60 + 30, None, ['scripts/incremental_reindex.py']),
    ('ekyc-purge', 0, None, ['scripts/ekyc_purge_expired.py']),
    ('risk-audit-escalation', 0, None, ['scripts/risk_audit_escalation.py']),
    ('ai-retention', 2 * 60 + 40, None, ['scripts/ai_retention.py']),
    ('es-sync', None, 15, ['scripts/es_incremental_sync.py']),
    ('case-sync', None, 15, ['scripts/sync_cases.py']),
    ('regcontrols', None, 60, ['scripts/regcontrols_run.py']),
]
last = {}
while True:
    now = datetime.now(); m = now.hour * 60 + now.minute
    for name, at, every, cmd in JOBS:
        due = (at is not None and m == at) or (every and m % every == 0)
        if due and last.get(name) != (now.date(), m):
            last[name] = (now.date(), m)
            print(f'{now:%F %T} start {name}', flush=True)
            subprocess.Popen([sys.executable] + cmd)
    time.sleep(20)
