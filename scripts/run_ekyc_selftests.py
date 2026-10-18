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
eKYC self-test pipeline (B9): runs every per-layer self-test
(scripts/test_national_id.py .. test_pipeline_e2e.py) in one command and
prints a single consolidated report.

Each layer already has its own independent self-test — this just saves
having to remember and run eight separate commands after a deploy,
dependency bump, or model/threshold change. It adds no new test logic of
its own.

Every script below follows the same convention (see any of them): a
`check()` helper tallies passed/failed assertions and the script exits
with code 0 if everything passed, 1 otherwise. This runner relies on
that exit code alone — it does not parse stdout.

Runs each script as a subprocess (not an in-process import) so that one
layer crashing hard (e.g. a missing model file) can't take down the
rest of the run, and so each gets a clean Python process matching how
it's actually invoked standalone.

Run with: python scripts/run_ekyc_selftests.py
Exit code: 0 if every layer passed, 1 if any layer failed or errored.
"""
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent

# Ordered fast/pure-logic -> synthetic-ML -> full integration, so an early
# failure in a cheap layer is visible before sinking time into loading
# EasyOCR/insightface/torch for the heavier ones.
SELFTESTS = [
    ('national_id', 'test_national_id.py', None),
    ('risk_engine', 'test_risk_engine.py', None),
    ('capture_quality', 'test_capture_quality.py', None),
    ('ocr_pipeline', 'test_ocr_pipeline.py', None),
    ('face_match', 'test_face_match.py', None),
    ('face_liveness', 'test_face_liveness.py', None),
    ('document_pad', 'test_document_pad.py', None),
    ('pipeline_e2e', 'test_pipeline_e2e.py', 'requires a reachable Postgres (POSTGRES_* env vars)'),
]


def run_one(script_name):
    result = subprocess.run([sys.executable, str(SCRIPTS_DIR / script_name)], cwd=PROJECT_ROOT)
    return result.returncode


def main():
    results = []
    for label, script_name, note in SELFTESTS:
        header = f"=== {label} ({script_name}) ==="
        if note:
            header += f"  [{note}]"
        print(f"\n{header}")
        start = time.time()
        returncode = run_one(script_name)
        elapsed = time.time() - start
        results.append((label, returncode == 0, elapsed))

    print("\n" + "=" * 60)
    print("eKYC self-test pipeline summary")
    print("=" * 60)
    failed_labels = []
    for label, ok, elapsed in results:
        status = 'PASS' if ok else 'FAIL'
        if not ok:
            failed_labels.append(label)
        print(f"  {status:4}  {label:<16} ({elapsed:5.1f}s)")

    total_elapsed = sum(elapsed for _, _, elapsed in results)
    print(f"\n{len(results) - len(failed_labels)}/{len(results)} layers passed ({total_elapsed:.1f}s total)")
    if failed_labels:
        print(f"Failed: {', '.join(failed_labels)}")

    sys.exit(1 if failed_labels else 0)


if __name__ == '__main__':
    main()
