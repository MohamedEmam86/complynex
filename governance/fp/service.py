"""Fit & proper forms: officials, forms, validation, assessment, workflow."""
import json
from datetime import datetime, date, timedelta

from database.db import get_db
from . import forms as F

KEY_FUNCTIONS = [  # code, EN, AR  (the CBE list; usable for any regulator)
    ('board_chair', 'Board Chairperson', 'رئيس مجلس الإدارة'),
    ('board_deputy', 'Board Deputy Chairperson', 'نائب رئيس مجلس الإدارة'),
    ('board_member', 'Board Member', 'عضو مجلس الإدارة'),
    ('ceo', 'Chief Executive Officer / Managing Director', 'الرئيس التنفيذي / العضو المنتدب'),
    ('regional_manager', 'Regional Manager responsible for activities in Egypt', 'المدير الإقليمي المسئول عن النشاط في مصر'),
    ('head_commercial', 'Head of Commercial', 'رئيس الإدارة التجارية'),
    ('head_bizdev', 'Head of Business Development', 'رئيس إدارة تطوير الأعمال'),
    ('head_operations', 'Head of Operations', 'رئيس إدارة العمليات'),
    ('head_it', 'Head of Information Technology', 'رئيس إدارة تكنولوجيا المعلومات'),
    ('head_finance', 'Head of Finance', 'رئيس الإدارة المالية'),
    ('head_legal', 'Head of Legal', 'رئيس الإدارة القانونية'),
    ('head_hr', 'Head of Human Resources', 'رئيس إدارة الموارد البشرية'),
    ('head_marketing', 'Head of Marketing', 'رئيس إدارة التسويق'),
    ('head_risk', 'Head of Risk Management', 'رئيس إدارة المخاطر'),
    ('head_audit', 'Head of Internal Audit', 'رئيس إدارة المراجعة الداخلية'),
    ('head_compliance', 'Head of Compliance', 'رئيس إدارة الالتزام'),
    ('head_infosec', 'Head of Information Security', 'رئيس إدارة أمن المعلومات'),
    ('committee_member', 'Committee member (not a board member)', 'عضو لجنة (من غير أعضاء المجلس)'),
    ('other', 'Other key function', 'وظيفة رئيسية أخرى'),
]
KF = {k: (en, ar) for k, en, ar in KEY_FUNCTIONS}

STATUSES = ['draft', 'candidate_completed', 'under_review', 'approved_internal', 'signed', 'submitted',
            'regulator_approved', 'regulator_rejected', 'withdrawn']
STATUS_LABELS = {
    'draft': ('Draft', 'مسودة'), 'candidate_completed': ('Completed by candidate', 'استوفاه المرشح'),
    'under_review': ('Under compliance review', 'قيد مراجعة الالتزام'),
    'approved_internal': ('Approved internally', 'معتمد داخلياً'), 'signed': ('Signed copy on file', 'النسخة الموقعة مرفقة'),
    'submitted': ('Submitted to regulator', 'مُرسل للجهة الرقابية'),
    'regulator_approved': ('Approved by regulator', 'موافقة الجهة الرقابية'),
    'regulator_rejected': ('Rejected by regulator', 'رفض الجهة الرقابية'), 'withdrawn': ('Withdrawn', 'مسحوب'),
}
PURPOSES = {'licensing': ('Licensing application', 'طلب الترخيص'), 'new_nomination': ('New nomination', 'ترشيح جديد'),
            'change': ('Change notification', 'إخطار بتغيير'), 'annual_review': ('Annual re-confirmation', 'تأكيد سنوي'),
            'committee': ('Committee membership', 'عضوية لجنة')}
# the five assessment criteria (scored 1-5, guide in utils/rating_guides.py)
CRITERIA = [
    ('honesty', 'fp.honesty', ['s6', 'a3', 'c5'], 'Honesty, integrity and reputation', 'المصداقية والنزاهة وحسن السمعة'),
    ('competence', 'fp.competence', ['s4', 's7', 'c3'], 'Competence and capability', 'الكفاءة والقدرة'),
    ('financial', 'fp.financial', ['s8', 'a4', 'c6'], 'Financial soundness', 'الملاءة المالية'),
    ('independence', 'fp.independence', ['s5', 's9', 's10', 'a5', 'c7'], 'Independence and conflicts of interest', 'الاستقلالية وتعارض المصالح'),
    ('time', 'fp.time', ['s4', 'a6', 'c4'], 'Time commitment', 'التفرغ وتخصيص الوقت'),
]
NA = ('n/a', 'na', 'لا ينطبق', 'not applicable', 'not applicable (n/a)')


# ------------------------------------------------------------------ definitions
def iter_items(defn):
    for s in defn.get('sections', []):
        for it in s.get('items', []):
            yield s, it


def visible(cond, answers):
    if not cond:
        return True
    for k, v in cond.items():
        a = answers.get(k)
        if isinstance(a, list):
            if v not in a:
                return False
        elif a != v:
            return False
    return True


def _filled(v):
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ''
    if isinstance(v, list):
        return any(_filled(x) for x in v)
    if isinstance(v, dict):
        return any(_filled(x) for x in v.values())
    return True


def validate(defn, answers):
    """Problems that stop 'completed by candidate': unanswered items, 'Yes' without details."""
    issues = []
    for s, it in iter_items(defn):
        if s.get('optional') or it.get('optional') or it['type'] in ('signature', 'grid'):
            continue
        if not visible(s.get('show_if'), answers) or not visible(it.get('show_if'), answers):
            continue
        v = answers.get(it['id'])
        if it['type'] == 'confirm':
            if v != 'yes':
                issues.append((it['no'], it['en'], it['ar'], 'not confirmed'))
        elif not _filled(v):
            issues.append((it['no'], it['en'], it['ar'], 'missing'))
        elif it['type'] == 'yesno' and v == 'yes' and 'details_docx' in it and not _filled(answers.get(it['id'] + '_details')):
            issues.append((it['no'], it['en'], it['ar'], 'yes without details'))
    # "Yes" in an adverse block needs a line in that section's details grid
    for s in defn.get('sections', []):
        if not visible(s.get('show_if'), answers):
            continue
        det = next((i for i in s['items'] if i['type'] == 'grid' and i['id'].endswith('_details')), None)
        if not det:
            continue
        rows = answers.get(det['id']) or []
        listed = ' '.join(str(r.get('qno', '')) for r in rows if isinstance(r, dict))
        for it in s['items']:
            if it['type'] == 'yesno' and it.get('adverse') and answers.get(it['id']) == 'yes' and it['no'] not in listed \
                    and it['no'].split('.')[-1] not in listed.split():
                issues.append((it['no'], it['en'], it['ar'], 'yes without details'))
    return issues


def adverse_flags(defn, answers):
    """'Yes' answers to integrity / financial / independence questions, for the reviewer."""
    out = []
    for s, it in iter_items(defn):
        if it['type'] == 'yesno' and it.get('adverse', s['id'] in ('s6', 's8', 's9', 'a3', 'a4', 'a5', 'c5', 'c6', 'c7')) \
                and answers.get(it['id']) == 'yes' and visible(s.get('show_if'), answers):
            out.append({'section': s['id'], 'no': it['no'], 'en': it['en'], 'ar': it['ar']})
    if answers.get('s10_q1') == 'no' and visible({'s3_board_type': 'independent'}, answers):
        out.append({'section': 's10', 'no': '10.1', 'en': 'No relevant experience declared', 'ar': 'لم يُقر بخبرة ذات صلة'})
    return out


def suggest_caps(defn, answers):
    """Highest score the evidence in the form supports for each criterion (the reviewer may go lower)."""
    flags = adverse_flags(defn, answers)
    caps = {}
    for key, _g, sections, _e, _a in CRITERIA:
        n = sum(1 for f in flags if f['section'] in sections)
        if n:
            caps[key] = 2 if n > 1 else 3
    if any(answers.get(f's10_q{i}') == 'yes' for i in range(2, 10)) and visible({'s3_board_type': 'independent'}, answers):
        caps['independence'] = 1
    return caps


def score_and_result(assessment):
    vals = [int(v['score']) for v in assessment.values() if isinstance(v, dict) and str(v.get('score', '')).isdigit()]
    if len(vals) < len(CRITERIA):
        return None, None
    avg = round(sum(vals) / len(vals), 2)
    if min(vals) <= 1:
        return avg, 'not_fit'
    if min(vals) == 2 or avg < 3:
        return avg, 'fit_with_conditions'
    return avg, 'fit'


# ------------------------------------------------------------------ prefill
def institution(db=None):
    db = db or get_db()
    cp = db.execute("SELECT * FROM corp_profile WHERE id = 1").fetchone()
    cp = dict(cp) if cp else {}
    ceo = db.execute("""SELECT o.full_name FROM fp_officials o WHERE o.key_function = 'ceo' AND o.is_active
                        ORDER BY o.id LIMIT 1""").fetchone()
    return {'legal_name': cp.get('legal_name_en') or '', 'legal_name_ar': cp.get('legal_name_ar') or '',
            'trade_name': ', '.join(cp.get('address_aliases') or []) if isinstance(cp.get('address_aliases'), list) else '',
            'cr': cp.get('commercial_register_no') or '', 'signatory': ceo['full_name'] if ceo else '',
            'signatory_capacity': 'Chief Executive Officer' if ceo else ''}


def prefill(defn, official, form_row=None, db=None):
    inst = institution(db)
    o = dict(official or {})
    if o.get('key_function') in KF:
        o.setdefault('position_title', KF[o['key_function']][0])
    o['board_type'] = o.get('_board_type')
    ctx = {'institution': inst, 'official': o, 'form': dict(form_row or {})}
    out = {}
    for _s, it in iter_items(defn):
        src = it.get('prefill')
        if not src:
            continue
        a, b = src.split('.', 1)
        v = ctx.get(a, {}).get(b)
        if v in (None, ''):
            continue
        if it['type'] == 'choice' and it.get('multi'):
            v = [v]
        out[it['id']] = v
    return out


# ------------------------------------------------------------------ officials
def officials(db=None, active_only=True):
    db = db or get_db()
    rows = db.execute(f"""
        SELECT o.*, bm.member_type, bm.is_independent, bm.is_executive, bm.position AS board_position,
               f.id AS form_id, f.reference AS form_ref, f.status AS form_status, f.template_code,
               f.assessment_result, f.next_review_date, f.updated_at AS form_updated
        FROM fp_officials o
        LEFT JOIN board_members bm ON bm.id = o.board_member_id
        LEFT JOIN LATERAL (SELECT * FROM fp_forms x WHERE x.official_id = o.id AND x.status <> 'withdrawn'
                           ORDER BY x.created_at DESC LIMIT 1) f ON TRUE
        {'WHERE o.is_active' if active_only else ''}
        ORDER BY CASE o.official_type WHEN 'board' THEN 0 WHEN 'executive' THEN 1 ELSE 2 END, o.full_name""").fetchall()
    out = [dict(r) for r in rows]
    comm = committee_seats(db)
    for r in out:
        r['committees'] = comm.get(r['id'], [])
    return out


def committee_seats(db=None):
    """official_id -> [committee names] (board members via committee_memberships, others via fp_official_committees)."""
    db = db or get_db()
    seats = {}
    for r in db.execute("""SELECT o.id, c.id AS cid, COALESCE(c.committee_name, '') AS name, cm.role
                           FROM fp_officials o JOIN committee_memberships cm ON cm.member_id = o.board_member_id
                           JOIN board_committees c ON c.id = cm.committee_id
                           WHERE COALESCE(cm.is_active, 1) = 1 AND COALESCE(c.is_active, 1) = 1
                           UNION ALL
                           SELECT oc.official_id, c.id, COALESCE(c.committee_name, ''), oc.role
                           FROM fp_official_committees oc JOIN board_committees c ON c.id = oc.committee_id
                           WHERE oc.is_active AND COALESCE(c.is_active, 1) = 1""").fetchall():
        seats.setdefault(r['id'], []).append({'id': r['cid'], 'name': r['name'], 'role': r['role']})
    return seats


def import_board_members(user_id, db=None):
    db = db or get_db()
    n = 0
    for m in db.execute("""SELECT * FROM board_members bm WHERE COALESCE(bm.is_deleted, 0) = 0
                           AND COALESCE(bm.status, 'ACTIVE') NOT IN ('RESIGNED', 'INACTIVE', 'TERMINATED')
                           AND NOT EXISTS (SELECT 1 FROM fp_officials o WHERE o.board_member_id = bm.id)""").fetchall():
        pos = (m['position'] or m['role'] or '').lower()
        kf = 'board_chair' if 'chair' in pos and 'deputy' not in pos and 'vice' not in pos else \
             'board_deputy' if ('deputy' in pos or 'vice' in pos) else 'board_member'
        db.execute("""INSERT INTO fp_officials (full_name, full_name_ar, official_type, board_member_id, key_function,
                      position_title, email, phone, nationality, created_by)
                      VALUES (%s,%s,'board',%s,%s,%s,%s,%s,%s,%s)""",
                   (m['member_name'], m['member_name_arabic'], m['id'], kf, m['position'] or KF[kf][0],
                    m['email'], m['phone'], m['nationality'], user_id))
        n += 1
    db.commit()
    return n


def board_type(official, db=None):
    if not official or not official.get('board_member_id'):
        return None
    db = db or get_db()
    m = db.execute("SELECT is_independent, is_executive FROM board_members WHERE id = %s", (official['board_member_id'],)).fetchone()
    if not m:
        return None
    return 'independent' if m['is_independent'] else ('executive' if m['is_executive'] else 'non_executive')


# ------------------------------------------------------------------ forms
def next_reference(db):
    y = datetime.now().year
    r = db.execute("SELECT COUNT(*) AS n FROM fp_forms WHERE reference LIKE %s", (f'FP-{y}-%',)).fetchone()
    return f"FP-{y}-{(r['n'] or 0) + 1:04d}"


def create_form(official_id, template_code, purpose, user_id, committee_id=None, db=None):
    db = db or get_db()
    defn = F.get_form(template_code)
    if not defn:
        raise ValueError('unknown form')
    o = db.execute("SELECT * FROM fp_officials WHERE id = %s", (official_id,)).fetchone()
    if not o:
        raise ValueError('unknown official')
    o = dict(o)
    o['_board_type'] = board_type(o, db)
    crow = {}
    if committee_id:
        c = db.execute("SELECT committee_name FROM board_committees WHERE id = %s", (committee_id,)).fetchone()
        crow = {'committee_name': c['committee_name'] if c else ''}
    answers = prefill(defn, o, crow, db)
    ref = next_reference(db)
    fid = db.execute("""INSERT INTO fp_forms (reference, template_code, official_id, purpose, committee_id, answers, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (ref, template_code, official_id, purpose, committee_id, json.dumps(answers, ensure_ascii=False),
                      user_id)).fetchone()['id']
    log(fid, 'created', None, 'draft', f'{defn["title_en"]}', user_id, db)
    db.commit()
    return fid


def get(fid, db=None):
    db = db or get_db()
    r = db.execute("""SELECT f.*, o.full_name, o.full_name_ar, o.official_type, o.key_function, o.position_title,
                             o.board_member_id, c.committee_name,
                             ur.first_name || ' ' || ur.last_name AS reviewer_name,
                             ua.first_name || ' ' || ua.last_name AS approver_name
                      FROM fp_forms f JOIN fp_officials o ON o.id = f.official_id
                      LEFT JOIN board_committees c ON c.id = f.committee_id
                      LEFT JOIN users ur ON ur.id = f.reviewed_by LEFT JOIN users ua ON ua.id = f.approved_by
                      WHERE f.id = %s""", (fid,)).fetchone()
    if not r:
        return None
    r = dict(r)
    for k in ('answers', 'assessment'):
        if isinstance(r[k], str):
            r[k] = json.loads(r[k] or '{}')
    return r


def log(fid, action, st_from, st_to, note, user_id, db):
    db.execute("""INSERT INTO fp_form_events (form_id, action, status_from, status_to, note, user_id)
                  VALUES (%s,%s,%s,%s,%s,%s)""", (fid, action, st_from, st_to, note, user_id))


def events(fid, db=None):
    db = db or get_db()
    return [dict(r) for r in db.execute("""SELECT e.*, u.first_name || ' ' || u.last_name AS user_name
                                           FROM fp_form_events e LEFT JOIN users u ON u.id = e.user_id
                                           WHERE e.form_id = %s ORDER BY e.created_at, e.id""", (fid,)).fetchall()]


def parse_answers(defn, form):
    """Read the posted form into an answers dict (items + grids + details)."""
    a = {}
    for _s, it in iter_items(defn):
        i = it['id']
        t = it['type']
        if t == 'grid':
            rows = []
            for r in range(int(it.get('rows', 4))):
                row = {c['key']: (form.get(f'{i}__{r}__{c["key"]}') or '').strip() for c in it['columns']}
                rows.append(row)
            a[i] = rows
        elif t == 'choice' and it.get('multi'):
            a[i] = form.getlist(i)
        else:
            a[i] = (form.get(i) or '').strip()
        if t == 'yesno' and 'details_docx' in it or (t == 'yesno' and it.get('details')):
            a[i + '_details'] = (form.get(i + '_details') or '').strip()
    return a


def save_answers(fid, answers, user_id, db=None):
    db = db or get_db()
    db.execute("UPDATE fp_forms SET answers = %s, updated_at = now() WHERE id = %s",
               (json.dumps(answers, ensure_ascii=False), fid))
    db.commit()


TRANSITIONS = {  # action -> (allowed from, to)
    'complete': (['draft'], 'candidate_completed'),
    'start_review': (['candidate_completed'], 'under_review'),
    'approve': (['under_review'], 'approved_internal'),
    'return': (['candidate_completed', 'under_review', 'approved_internal'], 'draft'),
    'submit': (['signed', 'approved_internal'], 'submitted'),
    'regulator_approved': (['submitted'], 'regulator_approved'),
    'regulator_rejected': (['submitted'], 'regulator_rejected'),
    'withdraw': (['draft', 'candidate_completed', 'under_review', 'approved_internal', 'signed', 'submitted'], 'withdrawn'),
}


def transition(fid, action, user_id, note=None, extra=None, db=None):
    db = db or get_db()
    f = get(fid, db)
    if not f or action not in TRANSITIONS:
        raise ValueError('invalid action')
    allowed, to = TRANSITIONS[action]
    if f['status'] not in allowed:
        raise ValueError(f'cannot {action} from {f["status"]}')
    sets = {'status': to}
    now = datetime.now()
    if action == 'start_review':
        sets.update(reviewed_by=user_id, reviewed_at=now)
    if action == 'approve':
        if not f.get('assessment_result'):
            raise ValueError('assessment missing')
        sets.update(approved_by=user_id, approved_at=now)
    if action == 'submit':
        sets.update(submitted_at=now, regulator_reference=(extra or {}).get('regulator_reference') or f.get('regulator_reference'))
    if action in ('regulator_approved', 'regulator_rejected'):
        sets.update(regulator_decision_on=(extra or {}).get('decision_on') or date.today(),
                    regulator_notes=note, regulator_reference=(extra or {}).get('regulator_reference') or f.get('regulator_reference'))
        if action == 'regulator_approved':
            sets['next_review_date'] = date.today() + timedelta(days=365)
            if f.get('board_member_id'):
                db.execute("""UPDATE board_members SET fit_proper_status = 'APPROVED', fit_proper_approval_date = %s,
                              fit_proper_next_review = %s, fit_proper_score = %s WHERE id = %s""",
                           (str(date.today()), str(sets['next_review_date']), f.get('assessment_score'), f['board_member_id']))
    cols = ', '.join(f'{k} = %s' for k in sets)
    db.execute(f"UPDATE fp_forms SET {cols}, updated_at = now() WHERE id = %s", (*sets.values(), fid))
    log(fid, action, f['status'], to, note, user_id, db)
    db.commit()
    return to


def save_assessment(fid, assessment, conditions, user_id, db=None):
    db = db or get_db()
    score, result = score_and_result(assessment)
    db.execute("""UPDATE fp_forms SET assessment = %s, assessment_score = %s, assessment_result = %s, conditions = %s,
                  updated_at = now() WHERE id = %s""",
               (json.dumps(assessment, ensure_ascii=False), score, result, conditions, fid))
    log(fid, 'assessed', None, None, f'score {score} -> {result}', user_id, db)
    db.commit()
    return score, result


def attach_signed(fid, attachment_id, user_id, db=None):
    db = db or get_db()
    f = get(fid, db)
    to = 'signed' if f['status'] in ('approved_internal', 'under_review', 'candidate_completed') else f['status']
    db.execute("UPDATE fp_forms SET signed_attachment_id = %s, signed_at = now(), status = %s, updated_at = now() WHERE id = %s",
               (attachment_id, to, fid))
    log(fid, 'signed_copy', f['status'], to, None, user_id, db)
    db.commit()


def dashboard(db=None):
    db = db or get_db()
    offs = officials(db)
    by = {}
    for o in offs:
        by[o['form_status'] or 'none'] = by.get(o['form_status'] or 'none', 0) + 1
    today = date.today()
    due = [o for o in offs if (o['next_review_date'] and o['next_review_date'] <= today + timedelta(days=60))
           or not o['form_status'] or o['form_status'] in ('regulator_rejected',)]
    comms = [dict(r) for r in db.execute("""SELECT c.id, c.committee_name, c.committee_name_arabic, c.is_active
                                            FROM board_committees c WHERE COALESCE(c.is_active, 1) = 1
                                            ORDER BY c.committee_name""").fetchall()]
    seats = committee_seats(db)
    for c in comms:
        mem = [o for o in offs if any(s['id'] == c['id'] for s in seats.get(o['id'], []))]
        c['members'] = len(mem)
        c['approved'] = sum(1 for o in mem if o['form_status'] == 'regulator_approved' or
                            (o['form_status'] in ('approved_internal', 'signed') and o['template_code'] == 'internal_fp_committee'))
    return {'officials': offs, 'by_status': by, 'due': due, 'committees': comms}
