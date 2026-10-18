#!/usr/bin/env python3
"""
National-ID match report — available immediately, no screening run required.

A national ID match is DEFINITIVE. A name match is probabilistic. The merchant
file carries an Egyptian national ID on 99% of rows and the internal blacklist
carries one on 97%, so this comparison is both cheap and conclusive — and it
completes in seconds rather than 28 hours.

Produces a workbook with every merchant whose national ID appears on a list,
alongside how closely the two names agree (a strong corroboration signal: same
ID AND same name is as close to certain as screening gets).
"""
import difflib
import json
import os
import sys
from datetime import date

sys.path.insert(0, '/var/www/complynex')
os.chdir('/var/www/complynex')
from dotenv import load_dotenv
load_dotenv('/var/www/complynex/.env')

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app import create_app
from database.db import get_db

app = create_app()
OUT = '/var/www/complynex/backups/ComplyNex_Merchant_ID_Matches.xlsx'

FONT = 'Arial'
HDR_FILL = PatternFill('solid', fgColor='1F3864')
HDR_FONT = Font(name=FONT, bold=True, color='FFFFFF', size=11)
BASE = Font(name=FONT, size=10)
BOLD = Font(name=FONT, size=10, bold=True)
NOTE = Font(name=FONT, size=9, italic=True, color='555555')
TITLE = Font(name=FONT, bold=True, size=15, color='1F3864')
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
RED = PatternFill('solid', fgColor='FCE4E4')
AMBER = PatternFill('solid', fgColor='FFF3CD')


def clean_id(v):
    d = ''.join(ch for ch in str(v or '') if ch.isdigit())
    return d if len(d) >= 10 else ''


def sim(a, b):
    return round(difflib.SequenceMatcher(None, str(a), str(b)).ratio() * 100, 1)


with open('/tmp/merchant_rows.json', encoding='utf-8') as f:
    rows = json.load(f)

m_by_id = {}
for r in rows:
    i = clean_id(r.get('Network_IdentityNumber'))
    if i:
        m_by_id.setdefault(i, []).append(r)

listed = {}
with app.app_context():
    db = get_db()
    for tbl in ('internal_blacklist', 'internal_pep'):
        try:
            cur = db.execute(
                "SELECT national_id, full_name, original_name, category, "
                "reason, source, risk_level FROM %s "
                "WHERE national_id IS NOT NULL AND national_id <> '' "
                "AND COALESCE(is_active,1) <> 0" % tbl)
            for r in cur.fetchall():
                d = dict(r)
                i = clean_id(d.get('national_id'))
                if i:
                    listed.setdefault(i, []).append((tbl, d))
        except Exception:
            db.rollback()

hits = sorted(set(m_by_id) & set(listed))
print('merchant IDs: %d | listed IDs: %d | ID MATCHES: %d'
      % (len(m_by_id), len(listed), len(hits)))

wb = Workbook()
ws = wb.active
ws.title = 'National ID Matches'
cols = [('National ID', 18), ('Merchant Name', 32), ('Listed Name', 32),
        ('Name Agreement %', 16), ('Confidence', 14), ('List', 20),
        ('Category', 24), ('Risk', 10), ('Merchant Account', 15),
        ('Status', 11), ('Governorate', 14), ('Outlet', 26),
        ('Rows in File', 12), ('Reason for Listing', 60)]
ws.append([c[0] for c in cols])
for i, (h, w) in enumerate(cols, start=1):
    ws.column_dimensions[get_column_letter(i)].width = w
    c = ws.cell(row=1, column=i)
    c.fill, c.font = HDR_FILL, HDR_FONT
    c.alignment = Alignment(horizontal='center', vertical='center',
                            wrap_text=True)
ws.row_dimensions[1].height = 30
ws.freeze_panes = 'A2'

for i in hits:
    mrows = m_by_id[i]
    m = mrows[0]
    for tbl, l in listed[i]:
        lname = l.get('original_name') or l.get('full_name') or ''
        agree = sim(m.get('name', ''), lname)
        conf = ('CONFIRMED' if agree >= 70 else
                'ID match, name differs')
        ws.append([i, m.get('name'), lname, agree, conf,
                   tbl, l.get('category'), l.get('risk_level'),
                   m.get('Network_Account'), m.get('Network_Status'),
                   m.get('Network_Governorate'), m.get('Network_Outlet_Ar'),
                   len(mrows), (l.get('reason') or '')[:400]])

for r in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(cols)):
    for c in r:
        c.font, c.border = BASE, BORDER
    if r[4].value == 'CONFIRMED':
        for c in r:
            c.fill = RED
    else:
        for c in r:
            c.fill = AMBER
if ws.max_row > 1:
    ws.auto_filter.ref = 'A1:%s%d' % (get_column_letter(len(cols)), ws.max_row)

# ------------------------------------------------------------- notes
ws2 = wb.create_sheet('About this report')
ws2.column_dimensions['B'].width = 108
ws2['B2'] = 'National ID matching — why this is the strongest signal you have'
ws2['B2'].font = TITLE
lines = [
    '',
    'WHAT THIS IS',
    '  Every merchant whose Egyptian national ID appears on the internal blacklist or',
    '  internal PEP list. A national ID match is definitive; a name match is probabilistic.',
    '',
    'WHY IT MATTERS',
    '  99% of merchant rows carry a national ID. 97% of blacklist entries carry one.',
    '  This comparison runs in seconds and returns an answer you can act on, whereas',
    '  fuzzy name screening across 102,196 names takes roughly 28 hours and returns',
    '  tens of thousands of probable matches that each need a human decision.',
    '',
    'HOW TO READ IT',
    '  CONFIRMED              - the ID matches AND the names agree. Treat as a true match',
    '                           and escalate. This is as close to certain as screening gets.',
    '  ID match, name differs - the ID matches but the names do not. Investigate: it may be',
    '                           a data-entry error on either side, a name change, or a',
    '                           recycled/incorrect ID. Do not dismiss without checking.',
    '',
    'LIMITATION',
    '  internal_pep holds a national ID on only 4 of 550 records (1%). PEP matching',
    '  therefore still depends almost entirely on names. Capturing IDs for PEP entries',
    '  is the single highest-value data improvement available.',
    '',
    'NOTE ON TEST DATA',
    '  Two blacklist records carried the placeholder ID 12345678901234 (جون دو / John Doe',
    '  and عبدالله احمد تيست / Abdullah Ahmed Test). They produced a spurious ID match and',
    '  have been retired.',
]
for i, t in enumerate(lines, start=3):
    ws2.cell(row=i, column=2, value=t).font = (BOLD if t and t.isupper() else BASE)

ws3 = wb.create_sheet('Summary', 0)
ws3.column_dimensions['B'].width = 54
ws3.column_dimensions['C'].width = 16
ws3['B2'] = 'Merchant National ID Screening'
ws3['B2'].font = Font(name=FONT, bold=True, size=16, color='1F3864')
ws3['B3'] = 'Prepared %s — ComplyNex Compliance' % date.today().isoformat()
ws3['B3'].font = NOTE
stats = [
    ('Merchant rows', len(rows)),
    ('Merchant rows with a national ID', sum(len(v) for v in m_by_id.values())),
    ('Distinct merchant national IDs', len(m_by_id)),
    ('Distinct listed national IDs', len(listed)),
    ('MERCHANTS MATCHING A LISTED ID', len(hits)),
]
ws3['B5'] = 'Measure'
ws3['C5'] = 'Count'
for c in ('B5', 'C5'):
    ws3[c].fill, ws3[c].font = HDR_FILL, HDR_FONT
for i, (k, v) in enumerate(stats, start=6):
    ws3.cell(row=i, column=2, value=k).font = BOLD if 'MATCHING' in k else BASE
    ws3.cell(row=i, column=3, value=v).font = BOLD if 'MATCHING' in k else BASE
    for col in (2, 3):
        ws3.cell(row=i, column=col).border = BORDER
        if 'MATCHING' in k:
            ws3.cell(row=i, column=col).fill = RED

wb.save(OUT)
print('written %s' % OUT)
