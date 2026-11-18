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
    UN/EU  ENTITY rows with a ship IMO (check digit) or a 'Type of ship' remark and a non-company name
           (the EU "IMO (vessel identification)" is mostly a shipping company's IMO company number)
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


def ofac_block(props, remarks, aliases=()):
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


def entity_block(name, details, source):
    """UN / EU ENTITY rows that are ships (format_handlers.ship_from_text: ship IMO check digit or a
    'Type of ship' remark, and a name that is not a company's)."""
    from screening.format_handlers import vessel_block, ship_from_text, vessel_measures
    if source == 'un':
        text = details.get('comments') or ''
        imos = ship_from_text(name, text)
    else:
        text = ' '.join(str(x) for x in [details.get('reason')] if x)
        ids = [str(s).split(':')[-1] for s in details.get('identifiers') or [] if 'imo' in str(s).lower()]
        imos = ship_from_text(name, text, ids)
    if imos is None:
        return None
    fm = re.search(r'Flag(?: State)?\s*:\s*([A-Za-z ,.\'()-]+?)(?:\.|;|$)', text, re.M)
    return vessel_block(imos=imos, flag=fm.group(1).strip() if fm else None,
                        measures=vessel_measures(text) or ['asset_freeze'])


def backfill(conn, apply):
    """Re-type ship rows stored before the handlers marked them (the next list update does the same)."""
    cur = conn.cursor()
    cur.execute("""SELECT id, source, full_name, details, properties FROM screening_watchlist
                   WHERE coalesce(entity_type, '') <> 'VESSEL' AND (
                     (source = 'ofac' AND details LIKE '%%"sdn_type": "Vessel"%%')
                     OR (source IN ('un', 'eu') AND (details ILIKE '%%imo%%' OR details ILIKE '%%type of ship%%')))""")
    rows = cur.fetchall()
    changed = {'ofac': 0, 'eu': 0, 'un': 0}
    for wid, source, name, details, props in rows:
        d, p = _j(details, {}), _j(props, {})
        if not isinstance(d, dict):
            continue
        if source == 'ofac':
            if d.get('sdn_type') != 'Vessel':
                continue
            p = dict(p or {}, vessel=ofac_block(p or {}, (p or {}).get('remarks')))
            if apply:
                cur.execute("""UPDATE screening_watchlist SET entity_type = 'VESSEL', properties = %s,
                               updated_at = CURRENT_TIMESTAMP WHERE id = %s""",
                            (json.dumps(p, ensure_ascii=False), wid))
        else:
            block = entity_block(name, d, source)
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
            print(VS.sync(conn, None, log=print))
    if a.sync:
        print(VS.sync(conn, a.source, log=print))
    if not (a.backfill or a.sync):
        ap.print_help()


if __name__ == '__main__':
    main()
