"""Fit & proper: key officials of Nile Microfinance S.A.E. (an FRA-supervised
microfinance company) on the general board fit & proper questionnaire, the annual
re-confirmation and a non-board audit committee expert - every status of the workflow."""
import io
import json
from datetime import date, timedelta

INST = 'Nile Microfinance S.A.E. (demo)'
CEO = 'Mostafa El-Sayed'


def _cbe_answers(ctx, o, n, adverse=False, independent=False, represents=None, partial=False):
    r = ctx.rnd
    born = date(1962 + (n * 3) % 22, 1 + n % 12, 3 + n % 25)
    a = {
        's1_q1': INST, 's1_q2': 'Nile Micro', 's1_q3': 'microfinance', 's1_q4': 'CR DEMO-220871; FRA licence DEMO-MF-0412 — Egypt',
        's2_name': o['full_name'], 's2_dob': str(born), 's2_pob': r.choice(['Cairo, Egypt', 'Alexandria, Egypt', 'Mansoura, Egypt', 'Assiut, Egypt']),
        's2_nat': 'Egyptian', 's2_gender': 'female' if o['full_name'].split()[-2 if o['full_name'].startswith('Dr.') else 0] in ('Nadia', 'Ghada', 'Laila', 'Nour', 'Mona') else 'male',
        's2_id_no': f'DEMO{2 if born.year < 2000 else 3}{born:%y%m%d}{n:07d}', 's2_id_issue': str(date(2021, 3, 1) + timedelta(days=n * 40)),
        's2_id_place': 'Civil Registry — Cairo', 's2_id_expiry': str(date(2028, 3, 1) + timedelta(days=n * 40)),
        's2_addr': f'{10 + n} Example Street, New Cairo, Egypt (demo address)', 's2_addr_perm': 'N/A',
        's2_mobile': f'+20 10 0000 {1000 + n:04d}', 's2_phone2': 'N/A', 's2_email': o.get('email') or f'official{n}@nilemicro.example',
        's2_resident': 'yes',
        's3_function': [o['key_function']], 's3_nature': 'permanent', 's3_start': str(ctx.dago(400 + n * 25)),
        's3_term': '3 years (board term)' if o['official_type'] == 'board' else 'N/A',
        's3_duties': o['duties'], 's3_other_pos': 'no',
        's3_represents': 'yes' if represents else 'no',
        's3_represents_grid': [{'name': represents, 'shares': '1,250,000', 'pct': '12.5%'}] if represents else [],
        's3_exec_board': 'yes' if o['key_function'] == 'ceo' else ('no' if o['official_type'] == 'board' else 'na'),
        's3_exec_board_details': 'Chief Executive Officer and executive board member, as approved by the general assembly (demo).' if o['key_function'] == 'ceo' else '',
        's3_chair_mgmt': 'no' if o['key_function'] in ('board_chair', 'board_deputy') else 'na',
        's4_history': o['history'], 's4_gaps': [], 's4_gov': 'no', 's4_parliament': 'no',
        's4_boards': o.get('boards', []), 's4_commitments': o.get('commitments', []), 's4_time_issue': 'no',
        's5_interests': o.get('interests', []), 's5_shares': [], 's5_beneficial': [], 's5_pledged': 'no', 's5_licensed': 'no',
        's7_academic': o['academic'], 's7_professional': o.get('certs', []), 's7_training': o['training'],
        's7_languages': [{'language': 'Arabic', 'spoken': 'Native', 'written': 'Native'},
                         {'language': 'English', 'spoken': 'Fluent', 'written': 'Fluent'}],
        's8_obligations': [{'type': 'Housing loan', 'creditor': 'Example Bank (demo)', 'amount': 'EGP 1,850,000',
                            'security': 'Mortgage on residence', 'status': 'Regular — no arrears'}] if n % 3 == 0 else [],
        's9_q6': 'no', 's9_relatives': [],
        's11_cv': 'attached', 's11_id': 'attached', 's11_board_approval': 'attached',
        's11_nomination_letter': 'attached' if represents else 'na', 's11_org_chart': 'attached',
        's11_no_bankruptcy': 'attached', 's11_criminal_record': 'attached',
        's13_name': o['full_name'], 's13_position': o['position_title'], 's13_date': str(ctx.dago(120 + n)), 's13_confirm': 'yes',
        's14_inst': INST, 's14_signatory': CEO, 's14_capacity': 'Chief Executive Officer', 's14_date': str(ctx.dago(118 + n)),
    }
    if o['official_type'] == 'board':
        a['s3_board_type'] = 'independent' if independent else ('executive' if o['key_function'] == 'ceo' else 'non_executive')
    for i in range(1, 7):
        a[f's6_q{i}'] = 'no'
    for i in range(1, 5):
        a[f's8_q{i}'] = 'no'
    for i in range(1, 6):
        a[f's9_q{i}'] = 'no'
    if independent:
        a['s10_q1'] = 'yes'
        for i in range(2, 10):
            a[f's10_q{i}'] = 'no'
    if adverse:
        a['s6_q2'] = 'yes'
        a['s6_details'] = [{'qno': '6.2', 'details': 'Written warning in 2016 from the regulator to the board of a leasing company where I was a '
                                                    'non-executive director, for late filing of quarterly statements. No fine; the matter was '
                                                    'closed in 2017 (letter attached). (demo)'}]
        a['s9_q5'] = 'yes'
        a['s9_details'] = [{'qno': '9.5', 'details': 'Board member of a digital lender that offers small-business loans similar to the Company’s. '
                                                    'Will recuse from related decisions; resignation planned within 6 months. (demo)'}]
    if partial:
        for k in [k for k in a if k.startswith(('s7_', 's8_', 's9_', 's10_', 's11_', 's13_', 's14_'))]:
            a.pop(k)
    return a


def _history(ctx, roles):
    out, y = [], 2024
    for employer, title, years, reason in roles:
        out.append({'employer': employer, 'title': title, 'from': f'{y - years}-01-01', 'to': f'{y}-12-31' if reason else '',
                    'reason': reason or 'Current position'})
        y -= years
    return out


PEOPLE = {  # key function, duties, history (employer, title, years, reason), academic
    'board_chair': ('Chair the board; set the agenda; lead board evaluation and the relationship with the FRA and shareholders.',
                    [('Example National Bank (demo)', 'Deputy Chairman', 8, 'retirement'), ('Example Investment Bank (demo)', 'Managing Director', 10, 'resignation')],
                    [{'qualification': 'PhD', 'major': 'Economics', 'institution': 'Cairo University', 'country': 'Egypt', 'year': '1992'}]),
    'board_deputy': ('Deputy chair; chairs the board in the chair\'s absence; member of the risk and nomination committees.',
                     [('Example Telecom Co. (demo)', 'Chief Technology Officer', 9, 'resignation'), ('Example Systems (demo)', 'IT Director', 7, 'end of contract')],
                     [{'qualification': 'BSc', 'major': 'Electrical Engineering', 'institution': 'Ain Shams University', 'country': 'Egypt', 'year': '1990'}]),
    'board_member': ('Non-executive / independent director; committee work as assigned by the board.',
                     [('Example Audit Firm (demo)', 'Partner', 12, 'retirement'), ('Example Insurance Co. (demo)', 'CFO', 6, 'resignation')],
                     [{'qualification': 'BCom', 'major': 'Accounting', 'institution': 'Alexandria University', 'country': 'Egypt', 'year': '1994'}]),
    'ceo': ('Runs the company within the board-approved strategy, budget and risk appetite; reports to the board.',
            [('Nile Microfinance S.A.E. (demo)', 'Chief Executive Officer', 4, ''), ('Example Consumer Finance (demo)', 'Chief Operating Officer', 6, 'resignation')],
            [{'qualification': 'MBA', 'major': 'Finance', 'institution': 'American University in Cairo', 'country': 'Egypt', 'year': '2005'}]),
    'head_compliance': ('Head of compliance and MLRO; reports functionally to the AML & compliance committee and administratively to the CEO.',
                        [('Nile Microfinance S.A.E. (demo)', 'Head of Compliance & MLRO', 3, ''), ('Example Bank (demo)', 'AML Manager', 7, 'resignation')],
                        [{'qualification': 'LLB', 'major': 'Law', 'institution': 'Cairo University', 'country': 'Egypt', 'year': '2006'}]),
    'head_risk': ('Head of risk management; independent from business lines; reports to the risk committee.',
                  [('Nile Microfinance S.A.E. (demo)', 'Chief Risk Officer', 3, ''), ('Example Leasing Co. (demo)', 'Risk Manager', 6, 'resignation')],
                  [{'qualification': 'MSc', 'major': 'Financial Risk', 'institution': 'Example University (demo)', 'country': 'United Kingdom', 'year': '2010'}]),
    'head_audit': ('Head of internal audit; reports to the audit committee.',
                   [('Nile Microfinance S.A.E. (demo)', 'Head of Internal Audit', 4, ''), ('Example Audit Firm (demo)', 'Senior Manager', 8, 'resignation')],
                   [{'qualification': 'BCom', 'major': 'Accounting', 'institution': 'Ain Shams University', 'country': 'Egypt', 'year': '2004'}]),
    'head_it': ('Head of IT and information security for the lending and collections platforms.',
                [('Nile Microfinance S.A.E. (demo)', 'Head of IT & Information Security', 2, ''), ('Example Payments Co. (demo)', 'Security Architect', 6, 'resignation')],
                [{'qualification': 'BSc', 'major': 'Computer Science', 'institution': 'Helwan University', 'country': 'Egypt', 'year': '2008'}]),
    'head_finance': ('Head of finance; financial reporting, capital and liquidity.',
                     [('Nile Microfinance S.A.E. (demo)', 'Chief Financial Officer', 5, ''), ('Example Holding (demo)', 'Finance Manager', 6, 'resignation')],
                     [{'qualification': 'BCom', 'major': 'Accounting', 'institution': 'Cairo University', 'country': 'Egypt', 'year': '2003'}]),
}
TRAINING = [{'program': 'Fit and proper criteria for key officials', 'provider': 'Example Banking Institute (demo)', 'place': 'Egypt', 'date': '2025-09-15', 'duration': '2 days'},
            {'program': 'AML/CFT for board members and senior management', 'provider': 'Integrys Academy (demo course)', 'place': 'Egypt', 'date': '2025-03-10', 'duration': '1 day'}]


def seed(ctx):
    from governance.fp import service as S
    from database.db import get_db
    ctx.commit()
    db = get_db()
    admin, mlro = ctx.uid('admin'), ctx.uid('mlro')
    S.import_board_members(mlro, db)
    # executives (users) as key officials
    for key, kf, title in [('mlro', 'head_compliance', 'Head of Compliance & MLRO'), ('risk', 'head_risk', 'Chief Risk Officer'),
                           ('audit', 'head_audit', 'Head of Internal Audit'), ('it', 'head_it', 'Head of IT & Information Security'),
                           ('cfo', 'head_finance', 'Chief Financial Officer')]:
        u = ctx.user(key)
        db.execute("""INSERT INTO fp_officials (full_name, official_type, user_id, key_function, position_title, email, nationality, created_by)
                      VALUES (%s,'executive',%s,%s,%s,%s,'Egyptian',%s)""",
                   (f"{u['first_name']} {u['last_name']}", u['id'], kf, title, u['email'], mlro))
    # the CEO is a board member already; mark the key function
    db.execute("UPDATE fp_officials SET key_function = 'ceo', position_title = 'Chief Executive Officer / Managing Director' WHERE full_name = %s", (CEO,))
    ext = db.execute("""INSERT INTO fp_officials (full_name, full_name_ar, official_type, key_function, position_title, email, nationality, created_by)
                        VALUES ('Dr. Mona Galal (demo)', 'د. منى جلال', 'committee_external', 'committee_member',
                                'Independent audit committee expert', 'mona.galal@example.org', 'Egyptian', %s) RETURNING id""", (mlro,)).fetchone()['id']
    audit_c = db.execute("SELECT id FROM board_committees WHERE committee_name ILIKE 'Audit%%' LIMIT 1").fetchone()
    if audit_c:
        db.execute("INSERT INTO fp_official_committees (official_id, committee_id, role, joined_on) VALUES (%s,%s,'EXPERT',%s)",
                   (ext, audit_c['id'], ctx.dago(200)))
    db.commit()

    offs = {r['full_name']: dict(r) for r in db.execute("""SELECT o.*, bm.is_independent, bm.status AS bm_status
                                                           FROM fp_officials o LEFT JOIN board_members bm ON bm.id = o.board_member_id""").fetchall()}
    # status plan per official
    plan = {
        'Dr. Hesham Abdel-Aziz': 'regulator_approved', 'Eng. Tarek Mansour': 'regulator_approved', CEO: 'submitted',
        'Dr. Nadia Rashwan': 'regulator_approved', 'Waleed Shawky': 'regulator_approved', 'Ghada El-Masry': 'under_review',
        'Dr. Samir Halim': 'regulator_approved', 'Ahmed Fathy': 'regulator_approved', 'Nour Samir': 'signed',
        'Laila Hassan': 'approved_internal', 'Omar Khaled': 'candidate_completed', 'Sherif Adel': 'draft',
    }
    flow = ['complete', 'start_review', 'approve', '__signed', 'submit', 'regulator_approved']
    stop_at = {'draft': 0, 'candidate_completed': 1, 'under_review': 2, 'approved_internal': 3, 'signed': 4, 'submitted': 5, 'regulator_approved': 6}
    n = 0
    for name, target in plan.items():
        o = offs.get(name)
        if not o or (o.get('bm_status') and o['bm_status'] != 'ACTIVE'):
            continue
        n += 1
        kf = o['key_function'] if o['key_function'] in PEOPLE else 'board_member'
        duties, hist, acad = PEOPLE[kf]
        o2 = dict(o, duties=duties, history=_history(ctx, hist), academic=acad, training=TRAINING,
                  certs=[{'certification': 'CAMS', 'specialization': 'AML', 'institution': 'ACAMS', 'country': 'USA', 'year': '2015', 'expiry': '2027'}]
                  if kf == 'head_compliance' else [],
                  boards=[{'entity': 'Example Charity Foundation (demo)', 'activity': 'Non-profit', 'capacity': 'Board member', 'represented': 'N/A',
                           'from': '2019-01-01', 'to': '', 'pct': '0%'}] if o['official_type'] == 'board' else [],
                  commitments=[{'business': 'University lecturing (demo)', 'role': 'Visiting lecturer', 'time': '4 hours / week'}] if n % 4 == 0 else [])
        a = _cbe_answers(ctx, o2, n, adverse=(name == 'Ghada El-Masry'), independent=bool(o.get('is_independent')),
                         represents='Nile Holding S.A.E. (demo shareholder)' if name == 'Ghada El-Masry' else None,
                         partial=(target == 'draft'))
        purpose = 'new_nomination'
        fid = S.create_form(o['id'], 'general_board_fp', purpose, mlro, db=db)
        S.save_answers(fid, a, mlro, db)
        steps = stop_at[target]
        for i, act in enumerate(flow[:steps]):
            if act == 'approve':
                good = {'honesty': (4, 'Criminal record certificate and screening clear; references from two former employers positive.'),
                        'competence': (4, 'Degree and experience verified against the role profile; relevant certification.'),
                        'financial': (4, 'I-Score report clean; no-bankruptcy certificate on file.'),
                        'independence': (4, 'No related-party dealings; interests disclosed are minor.'),
                        'time': (4, 'Declared commitments leave sufficient time; attendance above 90% last year.')}
                S.save_assessment(fid, {k: {'score': str(v[0]), 'justification': v[1]} for k, v in good.items()}, None, mlro, db)
            if act == '__signed':
                aid = db.execute("""INSERT INTO generic_attachments (module, record_type, record_id, filename, file_path, file_size,
                                    description, uploaded_by, uploaded_at) VALUES ('governance','fp_form',%s,%s,%s,0,%s,%s,%s) RETURNING id""",
                                 (fid, f'signed_form_{fid}_demo.pdf', f'uploads/attachments/governance/fp_form/{fid}/signed_form_{fid}_demo.pdf',
                                  'Signed fit & proper form (candidate and institution) — demo placeholder', mlro,
                                  str(ctx.ago(95 - n)))).fetchone()['id']
                db.commit()
                S.attach_signed(fid, aid, mlro, db)
                continue
            S.transition(fid, act, mlro, note=None,
                         extra={'regulator_reference': f'FRA/MF/FP/{2026}/{100 + n:04d} (demo)'}, db=db)
        if name == 'Ghada El-Masry':
            S.save_assessment(fid, {'honesty': {'score': '3', 'justification': 'Old regulator warning (2016) fully disclosed and closed; no fine; references positive.'},
                                    'competence': {'score': '4', 'justification': 'Former leasing company director; finance background verified.'},
                                    'financial': {'score': '4', 'justification': 'Clean credit report.'},
                                    'independence': {'score': '2', 'justification': 'Board seat at a potentially competing digital lender; recusal agreed; resignation within 6 months as a condition.'},
                                    'time': {'score': '3', 'justification': 'Two other board seats; time declared is adequate.'}},
                              'Resign from the competing lender’s board within 6 months; recuse from decisions on competing products until then.', mlro, db)
        # spread the timeline over the past months
        age = 160 - n * 6
        db.execute("UPDATE fp_forms SET created_at = %s, updated_at = %s WHERE id = %s", (ctx.ago(age, 10), ctx.ago(max(age - 60, 3), 15), fid))
        evs = db.execute("SELECT id FROM fp_form_events WHERE form_id = %s ORDER BY id", (fid,)).fetchall()
        for k, e in enumerate(evs):
            db.execute("UPDATE fp_form_events SET created_at = %s WHERE id = %s", (ctx.ago(max(age - k * 12, 2), 11 + k % 5), e['id']))
        if target == 'regulator_approved':
            dec = ctx.dago(max(age - 70, 5))
            db.execute("UPDATE fp_forms SET regulator_decision_on = %s, next_review_date = %s, approved_at = %s, submitted_at = %s WHERE id = %s",
                       (dec, dec + timedelta(days=365), ctx.ago(age - 30, 12), ctx.ago(age - 45, 12), fid))
        db.commit()

    # annual re-confirmation for a board member approved last year
    samir = offs.get('Dr. Samir Halim')
    if samir:
        fid = S.create_form(samir['id'], 'internal_fp_annual', 'annual_review', mlro, db=db)
        ans = {'a1_name': samir['full_name'], 'a1_position': 'Independent Director', 'a1_year': str(ctx.today.year), 'a1_last_form': str(ctx.dago(330)),
               'a2_personal': 'no', 'a2_positions': 'yes', 'a2_interests': 'no',
               'a2_details': 'Joined the board of a non-profit foundation (no conflict).',
               'a6_time': 'no', 'a6_training': [{'program': 'Board effectiveness', 'provider': 'Example Directors Institute (demo)', 'date': str(ctx.dago(90)), 'hours': '12'}],
               'a7_name': samir['full_name'], 'a7_date': str(ctx.dago(20)), 'a7_confirm': 'yes'}
        for i in range(1, 7):
            ans[f's6_q{i}'] = 'no'
        for i in range(1, 5):
            ans[f's8_q{i}'] = 'no'
        for i in range(1, 7):
            ans[f's9_q{i}'] = 'no'
        S.save_answers(fid, ans, mlro, db)
        S.transition(fid, 'complete', mlro, db=db)
        S.transition(fid, 'start_review', mlro, db=db)
    # external audit committee expert - internal committee form
    if audit_c:
        fid = S.create_form(ext, 'internal_fp_committee', 'committee', mlro, committee_id=audit_c['id'], db=db)
        ans = {'c1_committee': 'Audit Committee', 'c1_role': 'expert', 'c1_expertise': 'Chartered accountant; 20 years in external audit of financial institutions (demo).',
               'c1_start': str(ctx.dago(200)), 'c1_term': '3 years', 's2_name': 'Dr. Mona Galal (demo)', 's2_dob': '1975-04-12', 's2_nat': 'Egyptian',
               's2_id_no': 'DEMO27504120000001', 's2_mobile': '+20 10 0000 4545', 's2_email': 'mona.galal@example.org',
               's4_history': [{'employer': 'Example Audit Firm (demo)', 'title': 'Audit Partner', 'from': '2008-01-01', 'to': '2023-12-31', 'reason': 'retirement'}],
               's7_academic': [{'qualification': 'PhD', 'major': 'Accounting', 'institution': 'Cairo University', 'country': 'Egypt', 'year': '2006'}],
               's7_professional': [{'certification': 'CPA', 'specialization': 'Audit', 'institution': 'Example Board (demo)', 'country': 'USA', 'year': '2002', 'expiry': 'N/A'}],
               's4_boards': [], 's4_commitments': [{'business': 'Independent consultant', 'role': 'Owner', 'time': '20 hours / week'}], 's4_time_issue': 'no',
               'c8_name': 'Dr. Mona Galal (demo)', 'c8_date': str(ctx.dago(190)), 'c8_confirm': 'yes'}
        for i in range(1, 7):
            ans[f's6_q{i}'] = 'no'
        for i in range(1, 5):
            ans[f's8_q{i}'] = 'no'
        for i in range(1, 7):
            ans[f's9_q{i}'] = 'no'
        S.save_answers(fid, ans, mlro, db)
        for act in ('complete', 'start_review'):
            S.transition(fid, act, mlro, db=db)
        S.save_assessment(fid, {k: {'score': '5' if k in ('competence', 'independence') else '4', 'justification': j} for k, j in [
            ('honesty', 'Screening and references clear.'), ('competence', 'Audit partner experience; exactly the skill the committee charter requires.'),
            ('financial', 'Clean credit report.'), ('independence', 'No relationship with the company, its auditor or shareholders in the last 3 years.'),
            ('time', 'Consulting work leaves enough time; attended all meetings since appointment.')]}, None, mlro, db)
        S.transition(fid, 'approve', mlro, db=db)
    db.commit()
    print(f'    fit & proper: {db.execute("SELECT COUNT(*) n FROM fp_officials").fetchone()["n"]} officials, '
          f'{db.execute("SELECT COUNT(*) n FROM fp_forms").fetchone()["n"]} forms')
