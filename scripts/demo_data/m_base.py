"""Company profile, organisation chart, departments and the demo users."""
import os
import secrets
from common import COMPANY_EN, COMPANY_AR, DOMAIN

UNITS = [  # code, type, parent, en, ar
    ('NMF', 'COMPANY', None, COMPANY_EN, COMPANY_AR),
    ('NMF-COMP', 'DEPT', 'NMF', 'Compliance & AML', 'الالتزام ومكافحة غسل الأموال'),
    ('NMF-RISK', 'DEPT', 'NMF', 'Risk Management', 'إدارة المخاطر'),
    ('NMF-IA', 'DEPT', 'NMF', 'Internal Audit', 'المراجعة الداخلية'),
    ('NMF-FIN', 'DEPT', 'NMF', 'Finance', 'الإدارة المالية'),
    ('NMF-OPS', 'DIVISION', 'NMF', 'Operations & Lending', 'العمليات والإقراض'),
    ('NMF-IT', 'DEPT', 'NMF', 'IT & Information Security', 'تكنولوجيا المعلومات وأمن المعلومات'),
    ('NMF-CS', 'DEPT', 'NMF', 'Customer Service', 'خدمة العملاء'),
    ('NMF-HR', 'DEPT', 'NMF', 'Human Resources', 'الموارد البشرية'),
    ('NMF-LEG', 'DEPT', 'NMF', 'Legal & Board Secretariat', 'الشؤون القانونية وأمانة المجلس'),
    ('NM-CAI-01', 'BU', 'NMF-OPS', 'Cairo Downtown Branch', 'فرع وسط القاهرة'),
    ('NM-GIZ-02', 'BU', 'NMF-OPS', 'Giza Branch', 'فرع الجيزة'),
    ('NM-ASY-03', 'BU', 'NMF-OPS', 'Assiut Branch', 'فرع أسيوط'),
]

ALL = ['governance', 'aml', 'policies', 'reports', 'pdpl', 'training', 'screening', 'config', 'cyber',
       'consumer_protection', 'whistleblowing', 'ghe', 'coi', 'cobec', 'merchant_kyc', 'tm', 'ekyc',
       'risk_management', 'internal_audit', 'esg', 'carbon', 'ongoing_screening', 'academy', 'regcontrols',
       'prudential', 'ai']
COMPLIANCE = ['governance', 'aml', 'policies', 'reports', 'pdpl', 'training', 'screening', 'consumer_protection',
              'whistleblowing', 'ghe', 'coi', 'cobec', 'merchant_kyc', 'tm', 'ekyc', 'ongoing_screening',
              'regcontrols', 'esg', 'carbon', 'risk_management', 'ai']

# key, first, last, role, title, unit, edit-modules, view-modules
USERS = [
    ('admin', 'Demo', 'Administrator', 'admin', 'System Administrator', 'NMF-IT', ALL, []),
    ('mlro', 'Ahmed', 'Fathy', 'compliance_manager', 'Head of Compliance & MLRO', 'NMF-COMP', COMPLIANCE, ALL),
    ('co', 'Salma', 'Nabil', 'compliance_officer', 'Senior Compliance Officer', 'NMF-COMP', COMPLIANCE, ALL),
    ('aml', 'Youssef', 'Hamdy', 'compliance_officer', 'AML Analyst', 'NMF-COMP',
     ['aml', 'screening', 'tm', 'ekyc', 'merchant_kyc', 'ongoing_screening'], COMPLIANCE),
    ('ceo', 'Mostafa', 'El-Sayed', 'manager', 'Chief Executive Officer', 'NMF', ['governance'], ALL),
    ('risk', 'Nour', 'Samir', 'manager', 'Chief Risk Officer', 'NMF-RISK', ['risk_management', 'prudential', 'esg', 'carbon'], COMPLIANCE),
    ('audit', 'Laila', 'Hassan', 'manager', 'Head of Internal Audit', 'NMF-IA', ['internal_audit'], ALL),
    ('it', 'Omar', 'Khaled', 'manager', 'Head of IT & Information Security', 'NMF-IT', ['cyber'], ['regcontrols', 'pdpl']),
    ('dpo', 'Rania', 'Mostafa', 'manager', 'Data Protection Officer', 'NMF-LEG', ['pdpl'], ['cyber', 'policies']),
    ('cfo', 'Sherif', 'Adel', 'manager', 'Chief Financial Officer', 'NMF-FIN', ['prudential', 'carbon'], ['risk_management', 'esg']),
    ('ops', 'Hany', 'Ibrahim', 'manager', 'Head of Operations & Lending', 'NMF-OPS', [], ['regcontrols', 'risk_management']),
    ('cs', 'Yasmin', 'Mahmoud', 'manager', 'Customer Service Manager', 'NMF-CS', ['consumer_protection'], ['policies']),
    ('hr', 'Dina', 'Fawzy', 'manager', 'HR Manager', 'NMF-HR', ['training'], ['policies', 'coi', 'ghe']),
    ('sec', 'Ayman', 'Lotfy', 'employee', 'Board Secretary', 'NMF-LEG', ['governance'], ['policies']),
    ('br1', 'Mariam', 'Adel', 'manager', 'Branch Manager - Cairo Downtown', 'NM-CAI-01', [], ['policies', 'training']),
    ('lo1', 'Khaled', 'Mounir', 'employee', 'Loan Officer', 'NM-GIZ-02', [], ['policies', 'training']),
    ('lo2', 'Heba', 'Saad', 'employee', 'Loan Officer', 'NM-ASY-03', [], ['policies', 'training']),
    ('acc', 'Amr', 'Tawfik', 'employee', 'Senior Accountant', 'NMF-FIN', [], ['policies', 'training']),
    ('agent', 'Nada', 'Ezz', 'employee', 'Customer Service Agent', 'NMF-CS', [], ['consumer_protection', 'policies']),
    ('itsup', 'Ali', 'Ragab', 'employee', 'IT Support Engineer', 'NMF-IT', [], ['cyber', 'policies']),
]
MANAGER = {'co': 'mlro', 'aml': 'mlro', 'mlro': 'ceo', 'risk': 'ceo', 'audit': 'ceo', 'it': 'ceo', 'dpo': 'ceo',
           'cfo': 'ceo', 'ops': 'ceo', 'cs': 'ops', 'hr': 'ceo', 'sec': 'ceo', 'br1': 'ops', 'lo1': 'ops',
           'lo2': 'ops', 'acc': 'cfo', 'agent': 'cs', 'itsup': 'it'}
HEADS = {'NMF': 'ceo', 'NMF-COMP': 'mlro', 'NMF-RISK': 'risk', 'NMF-IA': 'audit', 'NMF-FIN': 'cfo', 'NMF-OPS': 'ops',
         'NMF-IT': 'it', 'NMF-CS': 'cs', 'NMF-HR': 'hr', 'NMF-LEG': 'dpo', 'NM-CAI-01': 'br1'}


def demo_password():
    pw = os.environ.get('DEMO_PASSWORD')
    if not pw:
        pw = 'Demo-' + secrets.token_urlsafe(9) + '#7a'
        print('  WARNING: DEMO_PASSWORD not set in .env - users got a random password')
    return pw


def seed(ctx):
    from models.user import User
    types = {r['code']: r['id'] for r in ctx.q("SELECT id, code FROM org_unit_types")}
    reg = ctx.one("SELECT id FROM regulators WHERE regulator_code = 'FRA'")
    ctx.data['fra_id'] = reg['id'] if reg else None

    for code, typ, parent, en, ar in UNITS:
        dtype = 'branch' if typ == 'BU' else 'department'
        if typ != 'COMPANY':
            ctx.depts[code] = ctx.ins('departments', name=en, code=code, description=ar, unit_type=dtype,
                                      is_active=True, created_at=str(ctx.ago(400)))
        ctx.units[code] = ctx.ins('org_units', parent_id=ctx.units.get(parent), unit_type_id=types[typ], code=code,
                                  name_en=en, name_ar=ar, is_legal_entity=(typ == 'COMPANY'),
                                  country='EG' if typ == 'COMPANY' else None,
                                  registration_no='DEMO-CR-104233' if typ == 'COMPANY' else None,
                                  legacy_department_id=ctx.depts.get(code), sort_order=len(ctx.units),
                                  is_active=True)

    pw_hash = User.hash_password(demo_password())
    for i, (key, first, last, role, title, unit, edit, view) in enumerate(USERS, start=1):
        vals = {f'perm_{m}': ('edit' if m in edit else 'view' if m in view else 'none')
                for m in ALL if f'perm_{m}' in ctx.cols('users')}
        ctx.users[key] = ctx.ins(
            'users', email=f'{key if key != "admin" else "demo.admin"}@{DOMAIN}', password_hash=pw_hash,
            first_name=first, last_name=last, role=role, employee_id=f'NMF-{1000 + i}',
            department=dict((u[0], u[3]) for u in UNITS)[unit], job_title=title,
            cms_access_level='edit' if edit else ('view' if view else 'none'), is_active=1,
            created_at=str(ctx.ago(380)), updated_at=str(ctx.ago(30)),
            department_id=ctx.depts.get(unit), org_unit_id=ctx.units[unit], authority_level='group',
            mfa_enabled=False, mfa_required_override=False, failed_login_count=0, auth_version=0,
            last_login=ctx.ago(ctx.rnd.randrange(0, 6), hour=9), can_assign_training=key in ('hr', 'mlro'),
            **vals)
    # 'group' authority = the whole organisation: give each such user the root-unit scope rule
    # (without a rule a non-admin user sees no scoped record at all).
    ctx.q("""INSERT INTO user_org_scope_rules (user_id, rule_type, org_unit_id)
             SELECT u.id, 'subtree', (SELECT id FROM org_units WHERE parent_id IS NULL ORDER BY id LIMIT 1)
               FROM users u
              WHERE u.authority_level = 'group'
                AND NOT EXISTS (SELECT 1 FROM user_org_scope_rules r WHERE r.user_id = u.id)""")
    for key, mgr in MANAGER.items():
        ctx.q("UPDATE users SET manager_id = %s WHERE id = %s", (ctx.users[mgr], ctx.users[key]))
    for code, key in HEADS.items():
        ctx.q("UPDATE org_units SET head_user_id = %s WHERE id = %s", (ctx.users[key], ctx.units[code]))
    ctx.q("UPDATE org_units SET created_by = %s", (ctx.users['admin'],))

    ctx.ins('corp_profile', id=1, legal_name_en=COMPANY_EN, legal_name_ar=COMPANY_AR,
            registered_address_en='12 Example Street, Fifth Settlement, New Cairo, Egypt (demo address)',
            registered_address_ar='12 شارع المثال، التجمع الخامس، القاهرة الجديدة (عنوان وهمي)',
            address_aliases=['Nile Micro', 'NMF'], commercial_register_no='DEMO-CR-104233',
            tax_card_no='DEMO-552-118-907', licence_number='FRA-MF-DEMO-0417', licence_type='microfinance',
            regulator_id=ctx.data['fra_id'],
            phone='+20 2 0000 0000', email=f'info@{DOMAIN}', website=f'https://www.{DOMAIN}',
            updated_by=ctx.users['admin'])
    for k, v in {'company_name': COMPANY_EN, 'regulator_name': 'Financial Regulatory Authority (FRA)',
                 'registration_number': 'FRA-MF-DEMO-0417', 'contact_email': f'compliance@{DOMAIN}',
                 'contact_phone': '+20 2 0000 0000',
                 'address': '12 Example Street, Fifth Settlement, New Cairo (demo)'}.items():
        ctx.q("UPDATE system_settings SET setting_value = %s WHERE setting_key = %s", (v, k))
