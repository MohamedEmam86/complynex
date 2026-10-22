"""ESG (I-ESG scoring, FRA ESG / TCFD disclosures, materiality) and Carbon (inventory FY-1 approved and
verified, FY in preparation) for Nile Microfinance. Complements the carbon demo already in the base
(packs/fra_nbfi/scripts/seed_demo_carbon.py): its sites, entries, planted data-quality issues and the
FY-1 offset obligation are kept; this adds the other sites, fuels, refrigerants, travel, workflow,
verification, offsets, targets, initiatives and all ESG content."""
from datetime import date, datetime, timedelta

from common import COMPANY_EN, COMPANY_AR

SEAS = {1: .86, 2: .84, 3: .9, 4: .98, 5: 1.1, 6: 1.28, 7: 1.38, 8: 1.4, 9: 1.25, 10: 1.05, 11: .92, 12: .88}
VERIFIER = 'Delta Assurance & Verification (fictional demo verifier)'


def _dt(d, hour=10, minute=15):
    return datetime(d.year, d.month, d.day, hour, minute)


def seed(ctx):
    from database.db import get_db
    from carbon import service as S
    db = get_db()
    r = ctx.rnd
    y = ctx.today.year
    per = {p['start_date'].year: p for p in ctx.q("SELECT * FROM esg_reporting_periods")}
    P0, P1 = per[y - 1]['id'], per[y]['id']          # FY-1 closed, FY open
    last_m = (ctx.today.replace(day=1) - timedelta(days=1)).month if ctx.today.month > 1 else 0
    U = ctx.uid
    co, risk, cfo, mlro = U('co'), U('risk'), U('cfo'), U('mlro')

    # ------------------------------------------------------------------ boundary: entities, sites, config
    e_hq = ctx.one("SELECT id FROM carbon_entities WHERE operational_control ORDER BY id LIMIT 1")['id']
    e_jv = ctx.one("SELECT id FROM carbon_entities WHERE NOT operational_control ORDER BY id LIMIT 1")['id']
    ctx.q("""UPDATE carbon_entities SET name = %s, name_ar = %s, note = %s WHERE id = %s""",
          (COMPANY_EN, COMPANY_AR, 'FRA-licensed company: head office, branches and the data centre (100 %, full control).', e_hq))
    ctx.q("""UPDATE carbon_entities SET name_ar = %s, note = %s WHERE id = %s""",
          ('مشروع الدلتا المشترك للتحصيل (تجريبي)', 'Collections joint venture, 40 % equity, no operational control — '
           'included at 40 % under the equity-share approach.', e_jv))
    old = {x['name']: x['id'] for x in ctx.q("SELECT id, name FROM carbon_sites")}
    site = {}
    for name, sid in old.items():
        if name.startswith('Head office'):
            site['HQ'] = sid
            ctx.q("UPDATE carbon_sites SET name = 'Head office — New Cairo', city = 'New Cairo', opened_on = '2018-09-01' "
                  "WHERE id = %s", (sid,))
        elif name.startswith('Giza'):
            site['GIZ'] = sid
            ctx.q("UPDATE carbon_sites SET name = 'Giza branch', opened_on = '2019-02-10' WHERE id = %s", (sid,))
        elif 'JV' in name:
            site['JV'] = sid
            ctx.q("UPDATE carbon_sites SET opened_on = '2021-05-01' WHERE id = %s", (sid,))
    for code, name, typ, city, area, hc, opened in [
            ('CAI', 'Cairo Downtown branch', 'branch', 'Cairo', 280, 24, date(2019, 3, 1)),
            ('ASY', 'Assiut branch', 'branch', 'Assiut', 320, 18, date(2020, 10, 15)),
            ('DC', 'Data centre — 6th of October City', 'data_centre', '6th of October City', 140, 4, date(2021, 1, 10))]:
        site[code] = ctx.ins('carbon_sites', entity_id=e_hq, name=name, site_type=typ, city=city, floor_area_m2=area,
                             headcount=hc, is_active=True, opened_on=opened)
    ctx.q("""UPDATE carbon_scope_config SET issued_capital_egp = 20000000, net_equity_egp = 145000000,
             fiscal_year_end = %s, updated_by = %s, updated_at = %s WHERE company_label = 'default'""",
          (date(y, 12, 31), risk, ctx.ago(40, 11)))
    # the real FRA-accredited verifiers stay untouched; the demo company uses a fictional one
    if not ctx.one("SELECT id FROM fra_verifiers WHERE name = %s", (VERIFIER,)):
        ctx.ins('fra_verifiers', name=VERIFIER, contact_info='verification@delta-assurance.example · +20 2 0000 0099',
                is_active=True, notes='Fictional verifier for the demo company only.', registration_no='DEMO-VVB-01',
                registered_on=date(y - 2, 2, 8))
    ctx.commit()

    # ------------------------------------------------------------------ factors (versioned)
    src24 = 'DESNZ/DEFRA GHG conversion factors 2024 (demo copy)'
    F = lambda code, d: S.publish_factor_version(code, d, co, db)  # noqa: E731
    F('NMF_PETROL', {'scope': 'scope1', 'category': 'Mobile combustion', 'activity': 'Petrol — company cars & motorcycles',
                     'unit': 'litre', 'factor_kgco2e': '2.084', 'effective_from': f'{y - 1}-01-01', 'vintage_year': '2024',
                     'source': src24, 'version_label': f'{y - 1}'})
    F('NMF_PETROL', {'factor_kgco2e': '2.070', 'effective_from': f'{y}-01-01', 'vintage_year': '2025',
                     'source': 'DESNZ/DEFRA GHG conversion factors 2025 (demo copy)', 'version_label': f'{y}'})
    F('NMF_R410A', {'scope': 'scope1', 'category': 'Fugitive emissions', 'activity': 'Refrigerant R-410A — AC top-ups',
                    'unit': 'kg', 'factor_kgco2e': '2088', 'effective_from': f'{y - 1}-01-01', 'vintage_year': '2014',
                    'source': 'IPCC AR5 GWP-100 (demo copy)'})
    F('NMF_AIR_DOM', {'scope': 'scope3', 'category': 'Business travel', 'ghg_category_no': '6',
                      'activity': 'Air travel — domestic (Cairo–Assiut)', 'unit': 'passenger-km', 'factor_kgco2e': '0.246',
                      'effective_from': f'{y - 1}-01-01', 'vintage_year': '2024', 'source': src24})
    F('NMF_HOTEL', {'scope': 'scope3', 'category': 'Business travel', 'ghg_category_no': '6',
                    'activity': 'Hotel stay — Egypt (per room-night)', 'unit': 'night', 'factor_kgco2e': '28.5',
                    'effective_from': f'{y - 1}-01-01', 'vintage_year': '2024', 'source': src24})
    F('DEMO_PCAF_CONS', {'scope': 'scope3', 'category': 'Financed emissions', 'ghg_category_no': '15',
                         'activity': 'Consumer finance (durable goods) — per EGP m outstanding (demo)', 'unit': 'EGP m',
                         'factor_kgco2e': '2600', 'effective_from': f'{y - 1}-01-01',
                         'source': 'DEMO factor — illustrative only, not an official value'})
    for code, ar in [('NMF_PETROL', 'بنزين — سيارات الشركة والدراجات النارية'), ('NMF_R410A', 'غاز التبريد R-410A — إعادة تعبئة التكييف'),
                     ('NMF_AIR_DOM', 'سفر جوي داخلي (القاهرة–أسيوط)'), ('NMF_HOTEL', 'إقامة فندقية — مصر (لكل ليلة)'),
                     ('DEMO_PCAF_CONS', 'التمويل الاستهلاكي (سلع معمرة) — لكل مليون جنيه قائم (تجريبي)'),
                     ('DEMO_GRID_ELEC', 'كهرباء الشبكة القومية (تجريبي)'), ('DEMO_DIESEL', 'سولار — مولدات (تجريبي)'),
                     ('DEMO_COMMUTE', 'الانتقال اليومي للعاملين — وسائل مختلطة (تجريبي)'),
                     ('DEMO_PCAF_MICRO', 'قروض المشروعات متناهية الصغر — لكل مليون جنيه قائم (تجريبي)'),
                     ('DEMO_PCAF_TRADE', 'تجارة التجزئة — لكل مليون جنيه إيرادات (تجريبي)')]:
        db.execute("UPDATE carbon_emission_factors SET activity_ar = %s WHERE factor_code = %s AND activity_ar IS NULL",
                   (ar, code))
    db.commit()

    # ------------------------------------------------------------------ activity data
    def add(pid, code, month, sid, qty, yr, note=None):
        d = {'factor_code': code, 'activity_month': f'{yr}-{month:02d}' if month else '', 'quantity': str(round(qty, 1)),
             'notes': note}
        if sid:
            d['site_id'] = sid
        rid, _ = S.add_entry(pid, d, co, db)
        return rid

    noise = lambda: 1 + r.uniform(-.045, .045)  # noqa: E731
    no_evidence = []
    for pid, yr, months in [(P0, y - 1, range(1, 13)), (P1, y, range(1, last_m + 1))]:
        cur = pid == P1
        for m in months:
            s = SEAS[m]
            add(pid, 'DEMO_GRID_ELEC', m, site['CAI'], 5600 * s * noise() * (.91 if cur and m >= 4 else 1), yr,
                'LED retrofit completed in April' if cur and m == 4 else None)
            add(pid, 'DEMO_GRID_ELEC', m, site['ASY'], 4800 * s * noise() * (.62 if cur and m >= 7 else 1), yr,
                'Rooftop solar (25 kWp) in operation — grid purchase reduced' if cur and m == 7 else None)
            add(pid, 'DEMO_GRID_ELEC', m, site['DC'], 14500 * (1 + .12 * (s - 1)) * noise() * (1.06 if cur else 1), yr)
            add(pid, 'DEMO_GRID_ELEC', m, site['JV'], 6000 * s * noise(), yr)
            add(pid, 'NMF_PETROL', m, site['HQ'], 1650 * noise() * (.8 if cur and m >= 5 else 1), yr,
                'Two pool cars replaced by EVs (pilot)' if cur and m == 5 else None)
            for k, base in (('CAI', 320), ('GIZ', 300), ('ASY', 410)):
                rid = add(pid, 'NMF_PETROL', m, site[k], base * noise() * (1.08 if cur else 1), yr)
                if cur and m == last_m and k != 'CAI':
                    no_evidence.append(rid)          # fuel-card statement not uploaded yet
            gen = 260 if m in (6, 7, 8) else 150
            add(pid, 'DEMO_DIESEL', m, site['ASY'], gen * noise() * (.88 if cur else 1), yr,
                'Load-shedding hours in Upper Egypt' if m == 7 else None)
            dc = 380 if (not cur and m == 8) else 60
            add(pid, 'DEMO_DIESEL', m, site['DC'], dc * noise(), yr,
                '14-hour grid outage on 12 August — generator ran the data centre' if dc == 380 else 'Monthly generator test run')
        for m, trips, nights in ((3, 5, 20), (6, 4, 16), (9, 6, 26), (12, 5, 22)):
            if m <= months[-1]:
                add(pid, 'NMF_AIR_DOM', m, None, trips * 2 * 2 * 320, yr, f'{trips} Cairo–Assiut trips, 2 travellers, return')
                add(pid, 'NMF_HOTEL', m, None, nights, yr, 'Branch supervision & audit visits to Assiut')
        add(pid, 'NMF_R410A', None, None, 12.2 if cur else 21.0, yr,
            ('F-gas log Jan–Sep from the HVAC contractor: HQ 5.0 kg, data centre 2.4 kg, Assiut 3.0 kg, Cairo Downtown 1.8 kg'
             if cur else 'Annual F-gas log from the HVAC contractor: HQ 10.5 kg, data centre 5.7 kg, Assiut 2.8 kg, '
                         'Giza 2.0 kg'))

    # dates, preparer and evidence of every entry
    code_of = {v: k for k, v in site.items()}
    for e in ctx.q("SELECT id, reporting_period_id, site_id, factor_code, activity_month, evidence_path FROM carbon_activity_entries"):
        p = per[y - 1] if e['reporting_period_id'] == P0 else per[y]
        m = e['activity_month']
        base = (date(m.year + (m.month == 12), m.month % 12 + 1, 1) if m else min(p['end_date'], ctx.today - timedelta(days=12)))
        created = min(_dt(base + timedelta(days=r.randrange(3, 14)), r.randrange(9, 17), r.randrange(60)),
                      ctx.now - timedelta(hours=r.randrange(4, 60)))
        ev = e['evidence_path']
        unsupported = e['id'] in no_evidence or (e['reporting_period_id'] == P1 and not ev and e['factor_code'] in
                                                  ('DEMO_DIESEL', 'DEMO_COMMUTE') and (e['site_id'] in (site['HQ'], site['GIZ'], None)))
        if not unsupported and not ev:
            kind = {'DEMO_GRID_ELEC': 'electricity-bill', 'NMF_PETROL': 'fuel-card-statement', 'DEMO_DIESEL': 'generator-log',
                    'NMF_R410A': 'f-gas-log', 'NMF_AIR_DOM': 'travel-agency-invoice', 'NMF_HOTEL': 'hotel-invoices',
                    'DEMO_COMMUTE': 'commuting-survey'}.get(e['factor_code'], 'evidence')
            ev = f"evidence/carbon/{p['start_date'].year}/{code_of.get(e['site_id'], 'ALL')}/{kind}" \
                 f"{'-' + m.strftime('%Y-%m') if m else ''}.pdf"
        ctx.q("UPDATE carbon_activity_entries SET created_at = %s, updated_at = %s, created_by = %s, evidence_path = %s "
              "WHERE id = %s", (created, created, co, ev, e['id']))
    ctx.commit()

    # ------------------------------------------------------------------ PCAF exposures, metrics
    for pid, k in ((P0, .9), (P1, 1.0)):
        S.save_exposure(pid, {'reference': 'PCAF-CONS-01', 'borrower': 'Consumer finance book — durable goods', 'asset_class': 'consumer',
                              'sector': 'households', 'method': 'asset', 'outstanding': str(14000000 * k),
                              'factor_code': 'DEMO_PCAF_CONS'}, risk, db)
        S.save_exposure(pid, {'reference': 'PCAF-SME-03', 'borrower': 'Example Dairy Cooperative (demo)', 'sector': 'agriculture',
                              'method': 'reported_verified', 'outstanding': str(4500000 * k), 'attribution_base': '30000000',
                              'borrower_emissions_tco2e': '1240'}, risk, db)
        S.save_exposure(pid, {'reference': 'PCAF-SME-04', 'borrower': 'Example Brick Workshop (demo)', 'sector': 'manufacturing',
                              'method': 'physical', 'outstanding': str(2200000 * k), 'attribution_base': '9000000',
                              'borrower_emissions_tco2e': '610'}, risk, db)
    S.save_exposure(P1, {'reference': 'PCAF-SME-05', 'borrower': 'Example Poultry Farm (demo)', 'sector': 'agriculture',
                         'method': 'reported', 'outstanding': '1800000'}, risk, db)   # attribution base missing -> PCAF warning
    ctx.q("UPDATE carbon_financed_exposures SET created_at = %s WHERE reporting_period_id = %s", (ctx.ago(230, 11), P0))
    ctx.q("UPDATE carbon_financed_exposures SET created_at = %s WHERE reporting_period_id = %s", (ctx.ago(25, 12), P1))
    ctx.commit()
    for pid, rev, hc in ((P0, '82000000', 176), (P1, '95000000', 183)):
        port = ctx.one("SELECT SUM(outstanding) AS s FROM carbon_financed_exposures WHERE reporting_period_id = %s", (pid,))['s']
        S.save_metrics(pid, {'revenue_egp': rev, 'headcount': str(hc), 'floor_area_m2': '2640',
                             'financed_portfolio_egp': str(port)}, cfo, db)
    ctx.q("UPDATE carbon_period_metrics SET updated_at = %s WHERE reporting_period_id = %s", (ctx.ago(225, 10), P0))
    ctx.q("UPDATE carbon_period_metrics SET updated_at = %s WHERE reporting_period_id = %s", (ctx.ago(20, 10), P1))

    # ------------------------------------------------------------------ inventory FY-1 -> targets, obligation, offsets
    ctx.commit()
    inv0 = S.inventory(P0, db)
    t0 = inv0['totals']
    s12 = round(t0['scope1'] + t0['scope2_location'], 1)
    ctx.q("UPDATE carbon_scope_config SET base_year_tco2e = %s WHERE company_label = 'default'", (s12,))
    ctx.q("""UPDATE carbon_targets SET baseline_tco2e = %s, target_2030_pct = 30, target_2035_pct = 50, sbti_aligned = FALSE,
             notes = %s, updated_by = %s, updated_at = %s""",
          (s12, f'Base year FY{y - 1}, first verified inventory: Scope 1 + Scope 2 (location-based), the FRA reporting '
                'boundary. Board-approved targets: -30 % by 2030 and -50 % by 2035. Scope 3 (travel, commuting) and financed '
                'emissions (PCAF) are tracked separately.', cfo, _dt(date(y, 4, 22))))
    req = round(s12 * 0.20, 1)
    ob = ctx.one("SELECT * FROM carbon_offset_obligations WHERE reporting_period_id = %s", (P0,))
    if ob:
        ctx.q("UPDATE carbon_offset_obligations SET total_emissions_tco2e = %s, required_tco2e = %s, created_by = %s, "
              "created_at = %s WHERE id = %s", (s12, req, co, _dt(ob['report_submitted_date'], 15), ob['id']))
        late = ctx.one("SELECT COALESCE(SUM(quantity_tco2e), 0) AS q FROM carbon_offset_purchases WHERE obligation_id = %s",
                       (ob['id'],))['q']
        ctx.q("""UPDATE carbon_offset_purchases SET standard = COALESCE(standard, 'VCS'), vintage_year = COALESCE(vintage_year, 2024),
                 cost_egp = COALESCE(cost_egp, quantity_tco2e * 610), fra_project_id = COALESCE(fra_project_id, 'DEMO-FRA-VCM-0058'),
                 serial_numbers = COALESCE(serial_numbers, 'DEMO-VCU-0058-000141 to 000168'), created_by = COALESCE(created_by, %s),
                 notes = COALESCE(notes, 'Balance bought after the 90-day deadline — see regulatory finding FRA-CF-05.')
                 WHERE obligation_id = %s""", (co, ob['id']))
        first = round(float(req) - float(late), 1)
        if first > 0:
            ctx.ins('carbon_offset_purchases', obligation_id=ob['id'], project_name='Upper Egypt Biogas Digesters (demo)',
                    registry_reference='DEMO-FRA-VCM-REG-2026-0147', quantity_tco2e=first, purchase_date=date(y, 8, 30),
                    cost_egp=round(first * 540), notes='First tranche bought from the FRA voluntary carbon market platform; '
                    'certificates retired in the company name.', created_by=co, created_at=_dt(date(y, 8, 30), 13),
                    retired_on=date(y, 9, 2), serial_numbers='DEMO-VCU-0031-004501 to 004558', standard='Gold Standard',
                    vintage_year=2024, fra_project_id='DEMO-FRA-VCM-0031')
        ctx.q("UPDATE carbon_offset_obligations SET status = 'FULFILLED' WHERE id = %s", (ob['id'],))

    # ------------------------------------------------------------------ initiatives
    ctx.q("""UPDATE carbon_initiatives SET title = 'LED retrofit in all branches', owner_user_id = %s, start_date = %s,
             cost_egp = 420000, achieved_reduction_tco2e = 4.6, created_by = %s,
             note = 'Cairo Downtown done (Apr), Giza and Assiut in Q4; savings measured on the electricity bills.'
             WHERE title LIKE 'LED retrofit%%'""", (U('ops'), date(y, 3, 1), co))
    ctx.q("""UPDATE carbon_initiatives SET title = 'Rooftop solar PV — head office (60 kWp)', owner_user_id = %s,
             start_date = %s, cost_egp = 2100000, created_by = %s,
             note = 'In the 2027 capex plan; landlord approval for the roof received Sep 2026.'
             WHERE title LIKE 'Solar PV on head-office%%'""", (U('ops'), date(y + 1, 1, 15), co))
    for t, sc, own, st, td, exp, ach, cost, status, note in [
            ('Rooftop solar PV — Assiut branch (25 kWp)', 'scope2', 'ops', date(y, 2, 1), date(y, 6, 30), 16, 6.1, 780000, 'done',
             'Commissioned 28 Jun; net-metering contract with the distribution company. About 38 % of the branch consumption.'),
            ('EV pilot — two head-office pool cars', 'scope1', 'ops', date(y, 4, 15), date(y, 12, 31), 9, 3.2, 960000, 'in_progress',
             'Two petrol pool cars replaced by leased EVs from May; charger at the head office. Decision on fleet roll-out in Jan.'),
            ('Refrigerant leak checks & R-32 replacement plan', 'scope1', 'ops', date(y, 5, 1), date(y + 1, 9, 30), 12, None, 350000,
             'in_progress', 'Quarterly leak checks by the HVAC contractor; R-410A units to be replaced at end of life.'),
            ('Paperless loan files (e-signature)', 'scope3', 'it', date(y - 1, 9, 1), date(y, 3, 31), 3, 2.4, 260000, 'done',
             'E-signature for loan contracts in all branches; paper purchases down 35 %.'),
            ('Diesel generator replacement at Giza branch', 'scope1', 'ops', None, date(y, 9, 30), 2, None, 450000, 'cancelled',
             'Cancelled: the branch moved to a dedicated feeder and the generator is now standby only.')]:
        ctx.ins('carbon_initiatives', title=t, scope=sc, owner_user_id=U(own), start_date=st, target_date=td,
                expected_reduction_tco2e=exp, achieved_reduction_tco2e=ach, cost_egp=cost, status=status, note=note,
                created_by=co, created_at=_dt(st or date(y, 2, 10), 11))

    # ------------------------------------------------------------------ workflow & verification
    def wf_event(pid, action, frm, to, user, when, note=None):
        ctx.ins('carbon_workflow_events', reporting_period_id=pid, action=action, from_status=frm, to_status=to,
                user_id=user, note=note, at=when)

    d = lambda mo, dd, h=11: _dt(date(y, mo, dd), h, r.randrange(60))  # noqa: E731
    wf_event(P0, 'submit', 'preparing', 'in_review', co, d(2, 16))
    wf_event(P0, 'return', 'in_review', 'preparing', risk, d(2, 23),
             'Data-centre generator log for August (outage) missing; attach the outage report and the fuel receipt.')
    wf_event(P0, 'submit', 'preparing', 'in_review', co, d(3, 2))
    wf_event(P0, 'review', 'in_review', 'reviewed', risk, d(3, 9))
    wf_event(P0, 'approve', 'reviewed', 'approved', cfo, d(3, 16, 14),
             'Approved for external verification and the FRA carbon-footprint report.')
    ctx.ins('carbon_period_workflow', reporting_period_id=P0, status='approved', prepared_by=co, prepared_at=d(3, 2),
            reviewed_by=risk, reviewed_at=d(3, 9), approved_by=cfo, approved_at=d(3, 16, 14),
            note='Approved for external verification and the FRA carbon-footprint report.')
    ctx.q("UPDATE carbon_activity_entries SET reviewed_by = %s, reviewed_at = %s WHERE reporting_period_id = %s",
          (risk, d(3, 9), P0))
    if last_m >= 8:
        wf_event(P1, 'submit', 'preparing', 'in_review', co, d(8, 10), 'H1 interim review (Jan–Jul data).')
        wf_event(P1, 'review', 'in_review', 'reviewed', risk, d(8, 13))
        wf_event(P1, 'return', 'reviewed', 'preparing', cfo, d(8, 17),
                 'Returned: February head-office electricity bill missing, January Giza generator entry recorded in kWh '
                 'instead of litres, and the March head-office spike must be explained before year-end submission.')
        ctx.ins('carbon_period_workflow', reporting_period_id=P1, status='preparing', prepared_by=co, prepared_at=d(8, 10),
                note='Returned: February head-office electricity bill missing, January Giza generator entry recorded in kWh '
                     'instead of litres, March head-office spike to be explained.')
        ctx.q("""UPDATE carbon_activity_entries SET reviewed_by = %s, reviewed_at = %s
                 WHERE reporting_period_id = %s AND activity_month <= %s""", (risk, d(8, 13), P1, date(y, 7, 1)))
    vrow = ctx.one("SELECT contact_info FROM fra_verifiers WHERE name = %s", (VERIFIER,))
    vname = VERIFIER if vrow else (ctx.one("SELECT name FROM fra_verifiers ORDER BY id LIMIT 1") or {}).get('name')
    vcontact = (vrow or {}).get('contact_info')
    sub = ob['report_submitted_date'] if ob else date(y, 6, 24)
    ctx.q("""UPDATE esg_reporting_periods SET fra_status = 'Submitted', verifier_name = %s, verifier_contact = %s,
             sent_to_verifier_at = %s, certified_at = %s, submitted_to_fra_at = %s, created_by = %s, verification_notes = %s
             WHERE id = %s""",
          (vname, vcontact, date(y, 4, 5), sub - timedelta(days=16), sub, mlro,
           f'Limited assurance (ISO 14064-3) on Scope 1 and Scope 2 — {s12:,.1f} tCO2e. Two minor findings (refrigerant log '
           'without site split; one generator receipt missing) closed before certification. Offset obligation 20 % within '
           '90 days of submission.', P0))
    ctx.q("""UPDATE esg_reporting_periods SET fra_status = 'Draft', verifier_name = %s, verifier_contact = %s, created_by = %s,
             verification_notes = %s WHERE id = %s""",
          (vname, vcontact, mlro, f'Verifier re-appointed for FY{y} (engagement letter signed 15 Sep {y}). Planning visit '
                                  f'in late November, fieldwork after year-end once the inventory is approved.', P1))
    for act, when, det in (('carbon_disclosure_pdf', d(3, 18, 15), 'Disclosure PDF for the board pack'),
                           ('carbon_disclosure_xlsx', d(4, 5, 10), 'Disclosure workbook sent to the verifier')):
        ctx.ins('audit_logs', user_id=co, action=act, module='carbon', item_id=P0, details=det,
                created_at=when.strftime('%Y-%m-%d %H:%M:%S'))
    ctx.commit()

    # ------------------------------------------------------------------ ESG
    _esg(ctx, db, P0, P1, y, s12, inv0)


def _esg(ctx, db, P0, P1, y, s12_prev, inv0):
    from carbon import service as S
    from packs.fra_sustainability import _install_disclosure_templates
    U = ctx.uid
    r = ctx.rnd
    _install_disclosure_templates(db)
    ctx.q("UPDATE esg_indicators SET carbon_metric = 'total' WHERE code = 'E1' AND carbon_metric IS NULL")
    db.commit()
    inv1 = S.inventory(P1, db)
    sc1_prev, sc1_cur = inv0['totals']['scope1'], inv1['totals']['scope1']
    kwh = {pid: ctx.one("SELECT SUM(quantity) AS q FROM carbon_activity_entries WHERE reporting_period_id = %s "
                        "AND factor_code = 'DEMO_GRID_ELEC' AND unit = 'kWh' AND scope = 'scope2'", (pid,))['q'] or 0
           for pid in (P0, P1)}
    fuel = {pid: ctx.one("SELECT SUM(quantity) AS q FROM carbon_activity_entries WHERE reporting_period_id = %s "
                         "AND factor_code IN ('NMF_PETROL', 'DEMO_DIESEL') AND unit = 'litre'", (pid,))['q'] or 0
            for pid in (P0, P1)}

    # owner, FY-1 status, FY-1 note, FY status, FY note
    D = {
        ('FRA-ESG', 'E1'): ('risk', 'complete', 'Yes — Environmental & Climate Policy approved by the Board (Jun ' + str(y - 1) + '); '
                            'environmental screening in the credit policy for loans above EGP 500k. No ISO 14001 certificate.',
                            'partial', 'Policy reviewed in June; water and waste sections being added. ISO 14001 gap assessment planned for Q1.'),
        ('FRA-ESG', 'E2'): ('co', 'complete', f'Yes — first carbon inventory (Scope 1 + 2, business travel and commuting) approved on '
                            f'16 Mar {y}; Scope 1 + 2 = {s12_prev:,.1f} tCO2e. External verification in progress.',
                            'partial', 'FY inventory in preparation in the Carbon module (data to September); approval and VVB '
                            'verification after year-end.'),
        ('FRA-ESG', 'E3'): ('risk', 'complete', f'Yes — {kwh[P0] / 1000:,.0f} MWh grid electricity and {fuel[P0] / 1000:,.1f} kL fuel '
                            '(petrol and diesel); no renewable energy yet.',
                            'partial', f'Jan–Sep: {kwh[P1] / 1000:,.0f} MWh grid electricity, {fuel[P1] / 1000:,.1f} kL fuel; '
                            'Assiut rooftop solar running since July, LED retrofit at Cairo Downtown.'),
        ('FRA-ESG', 'E4'): ('risk', 'partial', 'Partly — water bills for the head office only (1,940 m3); branches share building meters.',
                            'not_started', 'Sub-meters requested from the branch landlords; collection starts in Q4.'),
        ('FRA-ESG', 'E5'): ('risk', 'partial', 'Partly — paper recycling at the head office (2.1 t collected); no weighing at branches.',
                            'not_started', 'Waste weighing procedure to be issued with the facilities contract renewal in December.'),
        ('FRA-ESG', 'S1'): ('hr', 'complete', 'Yes — gender split of staff and managers and the median pay ratio reported from payroll.',
                            'partial', 'HR payroll extract for the full year due in January.'),
        ('FRA-ESG', 'S2'): ('hr', 'complete', 'Yes — turnover of permanent staff 14.2 % (loan officers 21 %); contract staff reported separately.',
                            'partial', 'Turnover tracked monthly; full-year figure after December payroll.'),
        ('FRA-ESG', 'S3'): ('hr', 'complete', 'Yes — Anti-harassment & Non-discrimination Policy in force; cases handled through the '
                            'grievance and whistleblowing channel.', 'complete', 'Policy unchanged; cases recorded in the Whistleblowing module.'),
        ('FRA-ESG', 'S4'): ('hr', 'complete', 'Yes — occupational health & safety policy; no lost-time injury; fire-safety and first-aid '
                            'training in all branches.', 'partial', 'OHS training plan 70 % delivered; injury log kept by Operations.'),
        ('FRA-ESG', 'S5'): ('ops', 'complete', 'Yes — Code of Conduct and supplier contracts prohibit child and forced labour.',
                            'complete', 'Clause included in every supplier contract renewed this year.'),
        ('FRA-ESG', 'S6'): ('hr', 'complete', 'Yes — social and health insurance for all staff, beyond the Labour Law minimum.',
                            'complete', 'No change; commitments in the HR manual.'),
        ('FRA-ESG', 'G1'): ('sec', 'complete', 'Yes — board seats and committee chairs by gender disclosed in the board report.',
                            'partial', 'To be confirmed after the AGM in March.'),
        ('FRA-ESG', 'G2'): ('mlro', 'complete', 'Yes — Anti-Bribery & Corruption Policy, gifts register, no confirmed case.',
                            'complete', 'Policy re-approved by the Board in May; gifts register reviewed quarterly.'),
        ('FRA-ESG', 'G3'): ('mlro', 'complete', 'Yes — Code of Business Ethics attested by all staff.',
                            'complete', 'This year\'s attestation campaign closed in the Code of conduct module.'),
        ('FRA-ESG', 'G4'): ('dpo', 'complete', 'Yes — data-protection framework under Law 151/2020; DPO appointed; breach register kept.',
                            'complete', 'Framework and breach register maintained in the Data protection module.'),
        ('FRA-ESG', 'G5'): ('co', 'complete', 'Yes — first sustainability section in the annual report (GRI-referenced); SDGs 1, 5 and 8.',
                            'not_started', 'Sustainability section to be drafted in January with the annual report.'),
        ('FRA-ESG', 'G6'): ('cfo', 'complete', 'No — the ESG template is not externally assured; the carbon inventory is verified by an '
                            'FRA-accredited verifier.', 'partial', 'Verifier re-appointed for the carbon inventory; ESG template assurance '
                            'under discussion with the external auditor.'),
        ('FRA-TCFD', '1a'): ('sec', 'complete', 'Yes (voluntary) — the Board Risk Committee oversees climate risk; added to its charter in September.',
                             'complete', 'Board Risk Committee reviewed climate risk in April and September.'),
        ('FRA-TCFD', '1b'): ('risk', 'complete', 'Yes — the CRO owns climate risk; sustainability working group (Risk, Compliance, Finance, '
                             'Operations) meets monthly.', 'complete', 'Working group monthly; climate KRIs owned by the CRO.'),
        ('FRA-TCFD', '2a'): ('risk', 'partial', 'Partly — physical (heat, water stress in Upper Egypt) and transition risks identified '
                             'qualitatively; horizons not yet quantified.', 'partial',
                             'Heat and water-stress scenario for agricultural borrowers in Upper Egypt under development.'),
        ('FRA-TCFD', '2b'): ('cfo', 'partial', 'Partly — solar and LED capex in the budget; no climate scenario in the business plan.',
                             'partial', 'Next year\'s budget includes head-office solar (EGP 2.1m) and the EV fleet decision.'),
        ('FRA-TCFD', '2c'): ('cfo', 'not_started', 'No dedicated climate-resilience investment line.',
                             'not_started', 'To be considered with the business plan update.'),
        ('FRA-TCFD', '3a'): ('risk', 'complete', 'Yes — climate added to the risk taxonomy; sector heat-map of the loan book.',
                             'complete', 'Climate questionnaire extended to all agricultural loans above EGP 100k.'),
        ('FRA-TCFD', '3b'): ('risk', 'partial', 'Partly — climate questionnaire for agricultural loans above EGP 200k.',
                             'partial', 'Concentration limits for climate-sensitive sectors drafted, pending Board approval.'),
        ('FRA-TCFD', '3c'): ('risk', 'partial', 'Partly — climate is a sub-category of the enterprise risk register.',
                             'partial', 'Climate KRIs added to the ERM register; thresholds pending.'),
        ('FRA-TCFD', '4a'): ('risk', 'partial', 'Partly — tCO2e, intensity per employee and financed emissions (PCAF) tracked.',
                             'partial', 'Financed emissions and intensity tracked in Carbon; climate KRIs pending Board approval.'),
        ('FRA-TCFD', '4b'): ('co', 'complete', f'Yes — Scope 1 = {sc1_prev:,.1f} tCO2e (verified).',
                             'partial', f'Scope 1 January–September: {sc1_cur:,.1f} tCO2e; final after approval and verification.'),
    }
    for it in ctx.q("SELECT id, reporting_period_id, framework, ref_code FROM esg_disclosure_items WHERE reporting_period_id IN (%s, %s)",
                    (P0, P1)):
        row = D.get((it['framework'], it['ref_code']))
        if not row:
            continue
        own, st0, n0, st1, n1 = row
        prev = it['reporting_period_id'] == P0
        when = _dt(date(y, 3, r.randrange(2, 24)), r.randrange(9, 17)) if prev else ctx.ago(r.randrange(3, 75), r.randrange(9, 17))
        ctx.q("""UPDATE esg_disclosure_items SET owner_id = %s, status = %s, evidence_notes = %s, updated_by = %s, updated_at = %s,
                 evidence_path = %s WHERE id = %s""",
              (U(own), st0 if prev else st1, n0 if prev else n1, U(own), when,
               f"evidence/esg/FY{y - 1 if prev else y}/{it['framework']}-{it['ref_code']}.pdf"
               if (st0 if prev else st1) == 'complete' else None, it['id']))

    # I-ESG maturity scores (1-5): FY-1, FY (None = not yet scored)
    SC = {'E1': (2, 3, 'co', 'Inventory approved and verified; monthly data collection by site.'),
          'E2': (2, 3, 'risk', 'Assiut rooftop solar live; LED retrofit under way.'),
          'E3': (2, None, 'risk', 'Recycling at head office only.'),
          'E4': (2, 3, 'risk', 'Environmental & Climate Policy approved; reviewed annually.'),
          'S1': (3, 4, 'hr', 'Annual training plan with completion tracking in the Training module.'),
          'S2': (3, None, 'hr', 'Gender data available; DEI targets not set yet.'),
          'S3': (3, 4, 'mlro', 'Anonymous channel live; cases tracked to closure.'),
          'S4': (4, 4, 'ops', 'Micro-loans to women and first-time borrowers in Upper Egypt.'),
          'S5': (3, 4, 'cs', 'Complaints SLA and root-cause reviews in Consumer protection.'),
          'G1': (3, 3, 'sec', 'Board committees in place; evaluation every two years.'),
          'G2': (3, 4, 'mlro', 'Code attested yearly by all staff.'),
          'G3': (3, 3, 'mlro', 'Annual declarations; register reviewed by Compliance.'),
          'G4': (2, 3, 'dpo', 'DPO appointed; records of processing completed.'),
          'G5': (3, 4, 'co', 'Policy register with review dates and owners.'),
          'R1': (3, 4, 'mlro', 'Risk-based AML/CFT programme; screening and monitoring in place.'),
          'R2': (4, 4, 'co', 'FRA periodic returns filed on time in the year.'),
          'R3': (4, 4, 'co', 'Licence in good standing; inspection findings tracked in Regulatory controls.'),
          'R4': (3, 3, 'it', 'ISMS controls and DR test; vulnerability management maturing.')}
    raw = {'E1': (s12_prev, None), 'S4': (64.0, 66.0), 'S1': (16.5, 18.0)}
    for ind in ctx.q("SELECT id, code FROM esg_indicators"):
        if ind['code'] not in SC:
            continue
        a, b, own, note = SC[ind['code']]
        for pid, sc, when in ((P0, a, _dt(date(y, 2, r.randrange(3, 27)), 11)), (P1, b, ctx.ago(r.randrange(5, 60), 12))):
            if sc is None:
                continue
            rv = raw.get(ind['code'], (None, None))[0 if pid == P0 else 1]
            ctx.ins('esg_indicator_responses', reporting_period_id=pid, indicator_id=ind['id'], score=float(sc), raw_value=rv,
                    is_auto_computed=False, evidence_notes=note, updated_by=U(own), updated_at=when)

    # materiality: extra topics + double-materiality scores
    order = (ctx.one("SELECT MAX(display_order) AS m FROM esg_materiality_topics")['m'] or 0)
    for cat, en, gri, ar in [
            ('S', 'Responsible lending & client over-indebtedness', 'GRI 2-25 / FS15', 'الإقراض المسؤول وتجنب الإفراط في مديونية العملاء'),
            ('E', 'Climate risk in the loan portfolio', 'TCFD / IFRS S2', 'المخاطر المناخية في محفظة القروض'),
            ('S', "Women's economic empowerment", 'GRI 405', 'التمكين الاقتصادي للمرأة'),
            ('G', 'Cybersecurity & IT resilience', 'GRI 418', 'الأمن السيبراني وصمود تقنية المعلومات'),
            ('S', 'Community investment & financial literacy', 'GRI 203 / 413', 'الاستثمار المجتمعي والتثقيف المالي'),
            ('E', 'Resource use, paper & waste', 'GRI 306', 'استخدام الموارد والورق والمخلفات')]:
        order += 1
        ctx.ins('esg_materiality_topics', category=cat, name=en, gri_reference=gri, is_active=True, display_order=order, name_ar=ar)
    M = {'Climate Change & GHG Emissions': ((3.4, 2.8), (3.9, 3.4), 'FRA Decision 36/2026 makes the carbon report and offsets mandatory.'),
         'Energy Management': ((2.6, 2.4), (2.9, 2.7), 'Electricity is about 70 % of operational emissions.'),
         'Financial Inclusion & Access': ((4.8, 4.6), (4.9, 4.7), 'Core mission; drives growth and FRA standing.'),
         'Data Privacy & Customer Protection': ((4.3, 4.0), (4.5, 4.2), 'Law 151/2020 and FRA consumer-protection rules.'),
         'Employee Development': ((3.5, 3.2), (3.6, 3.4), 'Loan-officer turnover is the main people risk.'),
         'Business Ethics & Anti-Corruption': ((4.0, 3.9), (4.1, 4.0), 'Cash handling in branches; gifts from borrowers.'),
         'Board Governance & Oversight': ((3.6, 3.8), (3.7, 3.9), 'FRA governance rules for NBFIs.'),
         'Regulatory Compliance & AML/CFT': ((4.4, 4.8), (4.5, 4.9), 'Licence condition; FRA inspections.'),
         'Responsible lending & client over-indebtedness': ((4.6, 4.3), (4.7, 4.5), 'Multiple borrowing in Upper Egypt villages.'),
         'Climate risk in the loan portfolio': (None, (3.3, 3.6), 'About a third of the book is agriculture in Upper Egypt.'),
         "Women's economic empowerment": (None, (4.2, 3.5), 'Women are about two thirds of active borrowers.'),
         'Cybersecurity & IT resilience': (None, (3.9, 4.4), 'Mobile collections and e-signature increase exposure.'),
         'Community investment & financial literacy': (None, (3.4, 2.6), 'Financial-literacy sessions with NGOs in Assiut.'),
         'Resource use, paper & waste': (None, (2.4, None), 'Business impact to be scored after the waste baseline.')}
    for t in ctx.q("SELECT id, name FROM esg_materiality_topics"):
        if t['name'] not in M:
            continue
        a, b, note = M[t['name']]
        for pid, v, when, who in ((P0, a, _dt(date(y - 1, 11, 18), 12), 'risk'), (P1, b, _dt(date(y, 9, 24), 12), 'risk')):
            if v:
                ctx.ins('esg_materiality_scores', reporting_period_id=pid, topic_id=t['id'], stakeholder_importance=v[0],
                        business_impact=v[1], notes=note, updated_by=U(who), updated_at=when)

    for name, unit in [('Head office — New Cairo', None), ('Cairo Downtown branch', 'NM-CAI-01'), ('Giza branch', 'NM-GIZ-02'),
                       ('Assiut branch', 'NM-ASY-03'), ('Data centre — 6th of October City', 'NMF-IT')]:
        ctx.ins('esg_sites', name=name, department_id=ctx.depts.get(unit) if unit else None, is_active=True,
                created_at=ctx.ago(300, 10))
    print(f'    carbon FY{y - 1}: S1+S2 {s12_prev:,.1f} t, offset {s12_prev * .2:,.1f} t; FY{y} S1 {sc1_cur:,.1f} t')
