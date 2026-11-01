#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Daily audit-trail check (P6-5): recompute the audit_logs hash chain, compare it
with the saved checkpoints, save a new checkpoint, and append one JSON line to
logs/audit_anchors.log (a copy of the checkpoint outside the database).
Exit code 0 = intact, 1 = problem found, 2 = could not run.

    python scripts/audit_anchor.py            # check + checkpoint
    python scripts/audit_anchor.py --check    # check only, writes nothing
"""
import argparse
import json
import os
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='check only, no checkpoint')
    ap.add_argument('--note', default='scheduled daily check')
    a = ap.parse_args()
    try:
        import psycopg2
        from config import Config
        from utils import audit_chain as AC
        conn = psycopg2.connect(**dict(Config.POSTGRES_CONFIG))
    except Exception as e:
        print(f'cannot connect: {e}')
        return 2
    try:
        if a.check:
            aid, res = None, AC.check(conn)
        else:
            aid, res = AC.take_anchor(conn, None, a.note)
    except Exception as e:
        print(f'check failed: {e}')
        return 2
    finally:
        try:
            conn.close()
        except Exception:
            pass
    line = {'at': datetime.now().isoformat(timespec='seconds'), 'anchor_id': aid, 'ok': res['ok'],
            'chain': res.get('chain'), 'anchors': res.get('anchors'), 'mismatches': res.get('mismatches'),
            'error': res.get('error')}
    out = json.dumps(line, default=str)
    print(out)
    if not a.check:
        try:
            with open(os.path.join(BASE, 'logs', 'audit_anchors.log'), 'a') as f:
                f.write(out + '\n')
        except Exception as e:
            print(f'could not write logs/audit_anchors.log: {e}')
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
