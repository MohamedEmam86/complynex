"""Staff training: role/department training requirements, enrollments on the kept courses,
completions with scores and certificates over 12 months, some overdue."""
from datetime import timedelta

ALL = ['mlro', 'co', 'aml', 'ceo', 'risk', 'audit', 'it', 'dpo', 'cfo', 'ops', 'cs', 'hr', 'sec', 'br1',
       'lo1', 'lo2', 'acc', 'agent', 'itsup']
FRONT = ['mlro', 'co', 'aml', 'ops', 'br1', 'lo1', 'lo2', 'cs', 'agent']        # customer-facing + compliance
COMP = ['mlro', 'co', 'aml', 'risk', 'br1', 'audit']

# course code -> list of waves: (enrolled days ago, due days, people, completion share, overdue keys)
PLAN = {
    'AML-001': [(352, 30, ALL + ['admin'], 1.0, ['itsup'])],
    'Data Privacy & Law 151- 002': [(323, 30, ['mlro', 'co', 'aml', 'ceo', 'risk', 'audit', 'it', 'dpo', 'cfo', 'hr',
                                                'sec', 'acc', 'itsup', 'admin'], 1.0, []),
                                    (232, 30, ['ops', 'cs', 'br1', 'lo1', 'lo2', 'agent'], 1.0, ['lo2', 'agent'])],
    'Sanctions & Narrative Testing-003': [(270, 21, ['mlro', 'co', 'aml'], 1.0, []),
                                          (176, 30, ['ops', 'br1', 'lo1', 'lo2'], 1.0, ['lo1']),
                                          (128, 30, ['cs', 'agent', 'risk', 'audit'], 1.0, [])],
    'AML-CFT-VID-005': [(12, 30, ALL + ['admin'], 0.4, [])],
    'KYC-CDD-006': [(12, 30, FRONT, 0.3, [])],
    'PEP-VID-007': [(10, 14, COMP, 0.35, [])],
}
# course created dates moved back so the history above is consistent (days ago)
CREATED = {'AML-001': 360, 'Data Privacy & Law 151- 002': 330, 'Sanctions & Narrative Testing-003': 275}

# requirements: (role, department, course code, policy name prefix, deadline days)
REQS = [
    ('employee', '', 'AML-001', 'Anti-Money Laundering', 30),
    ('manager', '', 'AML-001', 'Anti-Money Laundering', 30),
    ('compliance_officer', '', 'AML-001', 'Anti-Money Laundering', 14),
    ('', '', 'Data Privacy & Law 151- 002', 'Data Privacy', 30),
    ('', '', 'AML-CFT-VID-005', 'Anti-Money Laundering', 30),
    ('compliance_officer', '', 'Sanctions & Narrative Testing-003', 'Sanctions', 21),
    ('compliance_manager', '', 'PEP-VID-007', 'Customer Due Diligence', 14),
    ('compliance_officer', '', 'PEP-VID-007', 'Customer Due Diligence', 14),
    ('', 'Operations & Lending', 'KYC-CDD-006', 'Customer Due Diligence', 30),
    ('', 'Cairo Downtown Branch', 'KYC-CDD-006', 'Customer Due Diligence', 30),
    ('', 'Giza Branch', 'KYC-CDD-006', 'Customer Due Diligence', 30),
    ('', 'Assiut Branch', 'KYC-CDD-006', 'Customer Due Diligence', 30),
    ('', 'Giza Branch', 'Sanctions & Narrative Testing-003', 'Sanctions', 30),
    ('', 'Assiut Branch', 'Sanctions & Narrative Testing-003', 'Sanctions', 30),
    ('', 'Customer Service', 'Sanctions & Narrative Testing-003', 'Customer Protection', 30),
]


def seed(ctx):
    rnd = ctx.rnd
    courses = {r['course_code']: r for r in ctx.q(
        "SELECT id, course_code, course_name, passing_score, duration_minutes, content_type FROM training_courses")}
    pol = {r['policy_name']: r['id'] for r in ctx.q("SELECT id, policy_name FROM policies")}

    # Video lengths known to the server (read from each uploaded MP4), replacing any
    # length a player heartbeat stored in older versions; the watch check needs them.
    import os
    from training.media import mp4_duration_seconds
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    for r in ctx.q("SELECT id, video_file_path FROM training_courses"):
        secs = None
        if r['video_file_path']:
            for base in (os.getcwd(), root):
                secs = mp4_duration_seconds(os.path.join(base, r['video_file_path']))
                if secs:
                    break
        ctx.q("UPDATE training_courses SET video_duration_seconds=%s WHERE id=%s", (secs, r['id']))

    def policy(prefix):
        return next((v for k, v in pol.items() if k.startswith(prefix)), None)

    for code, days in CREATED.items():
        if code in courses:
            ctx.q("UPDATE training_courses SET created_at=%s WHERE id=%s",
                  (ctx.ago(days, 11).strftime('%Y-%m-%d %H:%M:%S'), courses[code]['id']))

    # requirements (replace the single sample rule)
    ctx.q("DELETE FROM training_requirements")
    n_req = 0
    for role, dept, code, pprefix, dl in REQS:
        if code not in courses:
            continue
        ctx.ins('training_requirements', role=role or None, department=dept or None, course_id=courses[code]['id'],
                policy_id=policy(pprefix), is_mandatory=1, deadline_days=dl,
                created_at=ctx.ago(360 if 'VID' not in code and 'CDD' not in code else 12, 10).strftime('%Y-%m-%d %H:%M:%S'))
        n_req += 1

    n_enr = n_done = n_over = n_cert = 0
    hr, mlro = ctx.uid('hr'), ctx.uid('mlro')
    for code, waves in PLAN.items():
        c = courses.get(code)
        if not c:
            print(f'    course {code} missing - skipped')
            continue
        video = c['content_type'] in ('Video', 'Hybrid')
        secs = (c['duration_minutes'] or 10) * 60
        for enr_days, due_days, people, share, overdue in waves:
            enr_d = ctx.dago(enr_days)
            due_d = enr_d + timedelta(days=due_days)
            for key in people:
                if key not in ctx.users:
                    continue
                emp = ctx.uid(key)
                done = (key not in overdue) and not (key == 'admin' and share < 1) and rnd.random() < share
                if share < 1 and key in ('mlro', 'co', 'aml'):
                    done = True          # compliance team completes new courses first
                status, comp, score, prog, vdone = 'enrolled', None, None, 0, 0
                if done:
                    span = max((min(due_d, ctx.today) - enr_d).days, 1)
                    lag = min(int(rnd.expovariate(1 / (span / 3))) + 1, max((ctx.today - enr_d).days - 1, 1))
                    if rnd.random() < 0.12 and enr_days > due_days + 20:
                        lag = due_days + rnd.randrange(3, 20)        # a few completed late
                    comp = ctx.ago(enr_days - lag, rnd.randrange(9, 18)).replace(microsecond=0)
                    score = rnd.choice(range(max(c['passing_score'] or 70, 70), 101, 5))
                    status, prog, vdone = 'completed', secs if video else 0, 1 if video else 0
                elif due_d < ctx.today:
                    status = 'overdue'
                    prog = int(secs * rnd.choice([0, 0.2, 0.45])) if video else 0
                    n_over += 1
                else:
                    if video and rnd.random() < 0.5:
                        status, prog = 'in_progress', int(secs * rnd.uniform(0.15, 0.8))
                eid = ctx.ins('training_enrollments', employee_id=emp, course_id=c['id'], course_name=c['course_name'],
                              enrolled_date=str(enr_d), enrolled_by=mlro if code in ('PEP-VID-007',) else hr,
                              due_date=str(due_d), completion_date=comp.strftime('%Y-%m-%d %H:%M:%S') if comp else None,
                              status=status, score=score, video_progress=prog if video else None,
                              video_completed=vdone if video else None,
                              created_at=ctx.ago(enr_days, 9).strftime('%Y-%m-%d %H:%M:%S'))
                n_enr += 1
                if done:
                    n_done += 1
                    ctx.ins('training_certificates', certificate_number=f"CERT-{eid}-{emp}-{comp.strftime('%Y%m%d')}",
                            enrollment_id=eid, employee_id=emp, course_id=c['id'],
                            issue_date=comp.strftime('%Y-%m-%d %H:%M:%S'), score=score)
                    n_cert += 1
    print(f'    requirements {n_req}, enrollments {n_enr}, completed {n_done}, overdue {n_over}, certificates {n_cert}')
