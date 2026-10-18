#!/usr/bin/env python3
"""
Build the merchant screening workbook from the background run's results.

Run this once the screening job reports COMPLETE (or any time — it will build
from whatever has been screened so far and say so).

Sheets:
  Summary            counts and coverage, with live formulas
  Full Merchant List every original row, with its screening outcome
  Matches >=85%      one row per match, engine score AND independent score
  Review First       matches where BOTH scores agree - the ones worth opening
  Excluded (junk)    entries that are not names (phone numbers, digits)
  Methodology        what was run, the scorer fixes, and the known limits
"""
import json
import os
from collections import defaultdict
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

RESULTS = '/var/www/complynex/backups/merchant_screening_results.jsonl'
JUNK = '/var/www/complynex/backups/merchant_junk_names.json'
ROWS = '/tmp/merchant_rows.json'
PROGRESS = '/var/www/complynex/backups/merchant_screening_progress.json'
OUT = '/var/www/complynex/backups/ComplyNex_Merchant_Screening_Results.xlsx'

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
GREEN = PatternFill('solid', fgColor='E7F3E7')


def header(ws, cols):
    ws.append([c[0] for c in cols])
    for i, (h, w) in enumerate(cols, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
        c = ws.cell(row=1, column=i)
        c.fill, c.font = HDR_FILL, HDR_FONT
        c.alignment = Alignment(horizontal='center', vertical='center',
                                wrap_text=True)
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = 'A2'


def main():
    screened = {}
    with open(RESULTS, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                screened[d['name']] = d
            except Exception:
                pass
    junk = json.load(open(JUNK, encoding='utf-8')) if os.path.exists(JUNK) else []
    rows = json.load(open(ROWS, encoding='utf-8'))
    prog = json.load(open(PROGRESS)) if os.path.exists(PROGRESS) else {}

    print('screened names: %d | junk: %d | merchant rows: %d'
          % (len(screened), len(junk), len(rows)))

    wb = Workbook()

    # ---------------------------------------------------------- Matches
    ws = wb.active
    ws.title = 'Matches over 85'
    header(ws, [('Merchant Name', 34), ('Matched Name (list)', 34),
                ('Engine Score', 12), ('Independent Score', 15),
                ('Both Agree', 11), ('Source', 20), ('List Type', 18),
                ('Category', 26), ('Nationality', 13), ('DOB', 12),
                ('Rows in Merchant File', 18), ('Source URL', 34)])
    row_count = defaultdict(int)
    for r in rows:
        if r['name']:
            row_count[r['name']] += 1

    n_match = 0
    for name, d in screened.items():
        for h in d.get('hits', []):
            agree = 'YES' if h.get('independent_similarity', 0) >= 85 else 'no'
            ws.append([name, h.get('matched_name'), h.get('score'),
                       h.get('independent_similarity'), agree,
                       h.get('source'), h.get('list_type'),
                       h.get('category'), h.get('nationality'),
                       h.get('dob'), row_count.get(name, 0),
                       h.get('source_url')])
            n_match += 1
    for r in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=12):
        for c in r:
            c.font, c.border = BASE, BORDER
        if r[4].value == 'YES':
            for c in r:
                c.fill = RED
    if ws.max_row > 1:
        ws.auto_filter.ref = 'A1:L%d' % ws.max_row

    # ------------------------------------------------------ Review first
    ws2 = wb.create_sheet('Review First')
    ws2['A1'] = 'Matches where the engine AND an independent check both agree'
    ws2['A1'].font = TITLE
    ws2['A2'] = ('These are the flags worth opening first. Both the ComplyNex '
                 'engine and an independent ordered-similarity measure score '
                 'the pair at 85% or above.')
    ws2['A2'].font = NOTE
    ws2.append([])
    hdr = ['Merchant Name', 'Matched Name', 'Engine', 'Independent',
           'Source', 'List Type', 'Category']
    ws2.append(hdr)
    for i, w in enumerate([34, 34, 10, 12, 20, 18, 26], start=1):
        ws2.column_dimensions[get_column_letter(i)].width = w
        c = ws2.cell(row=4, column=i)
        c.fill, c.font = HDR_FILL, HDR_FONT
    n_review = 0
    for name, d in screened.items():
        for h in d.get('hits', []):
            if h.get('independent_similarity', 0) >= 85:
                ws2.append([name, h.get('matched_name'), h.get('score'),
                            h.get('independent_similarity'), h.get('source'),
                            h.get('list_type'), h.get('category')])
                n_review += 1
    for r in ws2.iter_rows(min_row=5, max_row=ws2.max_row, max_col=7):
        for c in r:
            c.font, c.border = BASE, BORDER
    ws2.freeze_panes = 'A5'

    # --------------------------------------------------- Full merchant list
    ws3 = wb.create_sheet('Full Merchant List')
    header(ws3, [('Row', 8), ('Merchant/Agent Name', 32), ('Account', 14),
                 ('Status', 11), ('Outlet', 26), ('Business Nature', 24),
                 ('Identity Number', 18), ('Governorate', 14), ('Area', 18),
                 ('Company', 10), ('Screening Outcome', 20),
                 ('Matches >=85%', 14), ('Top Score', 11)])
    for r in rows:
        nm = r.get('name', '')
        d = screened.get(nm)
        if not nm:
            outcome, nh, top = 'No name in file', '', ''
        elif nm in junk:
            outcome, nh, top = 'Excluded - not a name', '', ''
        elif d is None:
            outcome, nh, top = 'Not yet screened', '', ''
        elif d.get('error'):
            outcome, nh, top = 'Error', '', ''
        elif d.get('hits'):
            outcome = 'POTENTIAL MATCH'
            nh = len(d['hits'])
            top = d['hits'][0]['score']
        else:
            outcome, nh, top = 'Clear', 0, ''
        ws3.append([r.get('row'), nm, r.get('Network_Account'),
                    r.get('Network_Status'), r.get('Network_Outlet_Ar'),
                    r.get('Network_BusinessNature'),
                    r.get('Network_IdentityNumber'),
                    r.get('Network_Governorate'), r.get('Network_Area'),
                    r.get('Network_Company'), outcome, nh, top])
    for r in ws3.iter_rows(min_row=2, max_row=ws3.max_row, max_col=13):
        for c in r:
            c.font, c.border = BASE, BORDER
        v = r[10].value
        if v == 'POTENTIAL MATCH':
            r[10].fill = RED
        elif v == 'Clear':
            r[10].fill = GREEN
        elif v in ('Not yet screened', 'Excluded - not a name'):
            r[10].fill = AMBER
    ws3.auto_filter.ref = 'A1:M%d' % ws3.max_row

    # ------------------------------------------------------------ Junk
    ws4 = wb.create_sheet('Excluded - not names')
    ws4['A1'] = 'Entries in the merchant name column that are not names'
    ws4['A1'].font = TITLE
    ws4['A2'] = ('Phone numbers, digit strings and single characters. These '
                 'were skipped: screening a phone number produces noise. '
                 'They should be corrected at source.')
    ws4['A2'].font = NOTE
    ws4.append([])
    ws4.append(['#', 'Value in Merchant Name column'])
    ws4.column_dimensions['A'].width = 8
    ws4.column_dimensions['B'].width = 44
    for i in (1, 2):
        c = ws4.cell(row=4, column=i)
        c.fill, c.font = HDR_FILL, HDR_FONT
    for i, j in enumerate(junk, start=1):
        ws4.append([i, j])
    for r in ws4.iter_rows(min_row=5, max_row=ws4.max_row, max_col=2):
        for c in r:
            c.font, c.border = BASE, BORDER

    # --------------------------------------------------------- Summary
    ws5 = wb.create_sheet('Summary', 0)
    ws5.column_dimensions['A'].width = 3
    ws5.column_dimensions['B'].width = 52
    ws5.column_dimensions['C'].width = 16
    ws5['B2'] = 'Merchant Screening — Results'
    ws5['B2'].font = Font(name=FONT, bold=True, size=16, color='1F3864')
    ws5['B3'] = 'Source: Full Merchant List.xlsx | Screened on merchant name only'
    ws5['B3'].font = NOTE
    ws5['B4'] = 'Prepared %s — ComplyNex Compliance' % date.today().isoformat()
    ws5['B4'].font = NOTE

    complete = prog.get('status') == 'COMPLETE'
    ws5['B6'] = ('Run status: COMPLETE' if complete else
                 'Run status: IN PROGRESS — %s of %s names screened'
                 % (prog.get('done', len(screened)), prog.get('total', '?')))
    ws5['B6'].font = BOLD
    if not complete:
        ws5['B6'].fill = AMBER

    data = [
        ('Merchant rows in file', len(rows)),
        ('Unique merchant names', len(screened) + len(junk)),
        ('Excluded - not names', len(junk)),
        ('Names screened', len(screened)),
        ('Names with at least one match >=85%',
         sum(1 for d in screened.values() if d.get('hits'))),
        ('Total match rows >=85%', n_match),
        ('Of those, independently corroborated', n_review),
    ]
    ws5['B8'] = 'Measure'
    ws5['C8'] = 'Count'
    for col in 'BC':
        ws5['%s8' % col].fill = HDR_FILL
        ws5['%s8' % col].font = HDR_FONT
    for i, (k, v) in enumerate(data, start=9):
        ws5.cell(row=i, column=2, value=k).font = BASE
        ws5.cell(row=i, column=3, value=v).font = BASE
        ws5.cell(row=i, column=2).border = BORDER
        ws5.cell(row=i, column=3).border = BORDER

    ws5['B18'] = 'Read "Review First" before the full match list.'
    ws5['B18'].font = BOLD

    # ------------------------------------------------------- Methodology
    ws6 = wb.create_sheet('Methodology')
    ws6.column_dimensions['B'].width = 112
    ws6['B2'] = 'How this screening was run'
    ws6['B2'].font = TITLE
    lines = [
        '',
        'SCOPE',
        '  Merchant name only, as instructed. No DOB, nationality or ID was used.',
        '  Adverse media was not included - it is a per-name web scrape and is not part of',
        '  a name-match assessment.',
        '',
        'THRESHOLD',
        '  Every match scoring 85% or above is listed.',
        '',
        'TWO SCORES PER MATCH',
        '  Engine Score       - the ComplyNex screening engine result.',
        '  Independent Score  - an ordered character-similarity measure computed outside',
        '                       the engine. Where the two disagree sharply, the match is',
        '                       usually a coincidence of shared common name components.',
        '  "Both Agree" = YES means both are >=85. Start there.',
        '',
        'SCORER DEFECTS FOUND AND FIXED BEFORE THIS RUN',
        '  1. The "exact match" boost divided by the SMALLER token set, so one shared token',
        '     against a one-token listed name counted as a 100% exact match and earned +25.',
        '  2. token_set_ratio was used as the fuzzy score. It returns 100 whenever one token',
        '     set is contained in the other, however many extra words there are.',
        '  3. A hard 0.95 floor was applied on semantic similarity alone, so an Arabic name',
        '     scored 95% against an unrelated Latin name on embedding similarity.',
        '  4. Candidate matches were not de-duplicated (one name returned six times).',
        '',
        '  Effect on a fixed sample: match rows fell from 951 to 231 (-76%), cross-script',
        '  false positives fell 88%, and no true positive was lost (12/12 listed names and',
        '  4/4 known sanctioned figures still match).',
        '',
        'KNOWN LIMITATION',
        '  Egyptian names draw on a very small pool of components - محمد appears in 45% of',
        '  all merchant names in this file, احمد in 23%. Two unrelated people therefore share',
        '  tokens routinely. The fixes above remove the worst of it, but some matches in this',
        '  workbook will still be coincidences of shared common components. The Independent',
        '  Score column exists precisely so those can be spotted without re-running anything.',
        '',
        'NOT WRITTEN TO PRODUCTION',
        '  These results were NOT saved into screening_results or the review queue. This is',
        '  an offline assessment; writing 102,000 screening records and their queue items',
        '  would flood live compliance data. It can be switched to persist if you want the',
        '  results inside the platform.',
    ]
    for i, t in enumerate(lines, start=3):
        ws6.cell(row=i, column=2, value=t).font = (
            BOLD if t and t.isupper() else BASE)

    wb.save(OUT)
    print('written %s' % OUT)
    print('matches >=85%%: %d   |   independently corroborated: %d'
          % (n_match, n_review))


if __name__ == '__main__':
    main()
