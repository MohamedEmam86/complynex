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
"""Null out any data a phishing SIMULATION ever captured from a target.

A phishing simulation must never retain what a tricked employee typed on the
fake form. Current code already stores nothing (it records only *that* the
person submitted and which field names were filled). This script cleans up
HISTORICAL rows written by older code that did keep values:

  - phishing_recipients.submitted_email / .submitted_card
  - phishing_events.extra_data keys other than 'fields_entered'
    (older rows stored the raw 'email' / 'card' values here)

IMPORTANT — this script DOES NOT DELETE ANYTHING BY DEFAULT.
  * It is --dry-run by default: it only COUNTS the rows that hold values and
    prints the counts (never the values themselves).
  * Nulling the data is a data change that needs the owner's explicit approval.
    Only then run it with --apply.

It never touches submitted_at / clicked_at / sent_at or the 'fields_entered'
summary, so the awareness metrics (who clicked / who submitted) are preserved.
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, '.env'))
except ImportError:
    pass

# the only extra_data key a simulation is allowed to keep
SAFE_EVENT_KEYS = {'fields_entered'}


def _connect():
    import psycopg2
    from config import Config
    return psycopg2.connect(**dict(Config.POSTGRES_CONFIG))


def counts(cur):
    cur.execute("""SELECT
          COUNT(*) FILTER (WHERE submitted_email IS NOT NULL AND submitted_email <> '') AS email_rows,
          COUNT(*) FILTER (WHERE submitted_card  IS NOT NULL AND submitted_card  <> '') AS card_rows
        FROM phishing_recipients""")
    email_rows, card_rows = cur.fetchone()
    cur.execute("""SELECT COUNT(*) FROM phishing_events
                   WHERE event_type = 'submit' AND extra_data IS NOT NULL
                     AND extra_data::text NOT IN ('', 'null', '{}')
                     AND EXISTS (SELECT 1 FROM jsonb_object_keys(extra_data::jsonb) k
                                 WHERE k <> 'fields_entered')""")
    event_rows = cur.fetchone()[0]
    return {'recipient_email_values': email_rows,
            'recipient_card_values': card_rows,
            'event_extra_data_with_values': event_rows}


def apply_wipe(conn, cur):
    cur.execute("""UPDATE phishing_recipients SET submitted_email = NULL, submitted_card = NULL
                   WHERE submitted_email IS NOT NULL OR submitted_card IS NOT NULL""")
    recips = cur.rowcount
    # rewrite each old event's extra_data to keep only the safe summary key
    cur.execute("""SELECT id, extra_data FROM phishing_events
                   WHERE event_type = 'submit' AND extra_data IS NOT NULL
                     AND extra_data::text NOT IN ('', 'null', '{}')""")
    evchanged = 0
    for ev_id, extra in cur.fetchall():
        try:
            data = extra if isinstance(extra, dict) else json.loads(extra)
        except (ValueError, TypeError):
            data = {}
        cleaned = {k: v for k, v in (data or {}).items() if k in SAFE_EVENT_KEYS}
        if cleaned != data:
            cur.execute("UPDATE phishing_events SET extra_data = %s WHERE id = %s",
                        (json.dumps(cleaned), ev_id))
            evchanged += 1
    conn.commit()
    return recips, evchanged


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true',
                    help='actually null the values (needs owner approval). Default is a dry run.')
    a = ap.parse_args()
    conn = _connect()
    cur = conn.cursor()
    c = counts(cur)
    print('Stored phishing-simulation submission values currently on record:')
    for k, v in c.items():
        print(f'  {k}: {v}')
    if not a.apply:
        print('\nDRY RUN — nothing changed. Re-run with --apply (owner-approved) to null these values.')
        return 0
    recips, evs = apply_wipe(conn, cur)
    print(f'\nAPPLIED: cleared values on {recips} recipient row(s) and {evs} event row(s).')
    print('Post-wipe counts:')
    for k, v in counts(cur).items():
        print(f'  {k}: {v}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
