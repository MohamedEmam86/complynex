#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Vessel tables (V1): one-off backfill of the ships already loaded + rebuild of the vessel tables.

The list handlers mark ships (entity_type 'VESSEL', properties.vessel) from their next update on. Rows
loaded before that change are ENTITY rows; --backfill reclassifies the ones that can be recognised
from what is stored:
    OFAC   details.sdn_type = 'Vessel'; IMO / MMSI / year of build / former flags from
           properties.identifiers, linked parties from the remarks (call sign, type and flag arrive with
           the next OFAC update)
    EU     details.identifiers with an 'IMO (vessel ...)' identification
UK and OpenSanctions ships carry no ship marker in stored rows: they arrive with the next update of
those lists (the UK ShipDetails block and the OpenSanctions 'Vessel' schema are now read).

    python scripts/vessels_sync.py --backfill            # dry run: counts only
    python scripts/vessels_sync.py --backfill --apply    # reclassify + materialise
    python scripts/vessels_sync.py --sync [--source ofac] # rebuild vessel_profile / identifiers / links
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _j(v, d):
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v) if v else d
    except Exception:
        return d


def ofac_block(props, remarks):
    from screening.format_handlers import vessel_block
    ids = props.get('identifiers') or []

    def idv(*types):
        return [i.get('number') for i in ids if str(i.get('type') or '').strip().lower() in types]
    owners = []
    for m in re.finditer(r'Linked To:\s*([^)]+)\)', remarks or ''):
        owners += [{'name': p.strip().rstrip('.'), 'role': 'linked', 'ref': None}
                   for p in m.group(1).split(';') if p.strip()]
    return vessel_block(imos=idv('vessel registration identification'), mmsi=idv('mmsi'),
                        call_sign=idv('other vessel call sign'), vtype=(idv('other vessel type') or [None])[0],
                        flags_past=idv('former vessel flag') + idv('other vessel flag'),
                        year_built=(idv('vessel year of build') or [None])[0], owners=owners,
                        measures=['asset_freeze'])


def eu_block(details):
    from screening.format_handlers import vessel_block
    imos = []
    for s in details.get('identifiers') or []:
        s = str(s)
        if 'vessel' in s.lower() and 'imo' in s.lower():
            imos.append(s.split(':')[-1])
    return vessel_block(imos=imos, measures=['asset_freeze']) if imos else None


def backfill(conn, apply):
    cur = conn.cursor()
    cur.execute("""SELECT id, source, details, properties FROM screening_watchlist
                   WHERE entity_type <> 'VESSEL' AND (
                     (source = 'ofac' AND details LIKE '%%"sdn_type": "Vessel"%%')
                     OR (source = 'eu' AND details ILIKE '%%vessel%%' AND details ILIKE '%%imo%%'))""")
    rows = cur.fetchall()
    changed = {'ofac': 0, 'eu': 0}
    for wid, source, details, props in rows:
        d, p = _j(details, {}), _j(props, {})
        if source == 'ofac':
            if (d or {}).get('sdn_type') != 'Vessel':
                continue
            block = ofac_block(p or {}, (p or {}).get('remarks'))
            p = dict(p or {}, vessel=block)
            if apply:
                cur.execute("""UPDATE screening_watchlist SET entity_type = 'VESSEL', properties = %s,
                               updated_at = CURRENT_TIMESTAMP WHERE id = %s""",
                            (json.dumps(p, ensure_ascii=False), wid))
        else:
            if not isinstance(d, dict):
                continue
            block = eu_block(d)
            if not block:
                continue
            d = dict(d, vessel=block)
            if apply:
                cur.execute("""UPDATE screening_watchlist SET entity_type = 'VESSEL', details = %s,
                               updated_at = CURRENT_TIMESTAMP WHERE id = %s""",
                            (json.dumps(d, ensure_ascii=False), wid))
        changed[source] += 1
    print(f'ships recognised in stored rows: {changed}')
    if apply:
        conn.commit()
    else:
        conn.rollback()
        print('DRY RUN (nothing saved)')
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill', action='store_true')
    ap.add_argument('--sync', action='store_true')
    ap.add_argument('--source')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    import psycopg2
    from config import Config
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    from screening import vessel_store as VS
    if a.backfill:
        backfill(conn, a.apply)
        if a.apply:
            for s in ('ofac', 'eu'):
                print(VS.sync(conn, s, log=print))
    if a.sync:
        print(VS.sync(conn, a.source, log=print))
    if not (a.backfill or a.sync):
        ap.print_help()


if __name__ == '__main__':
    main()
