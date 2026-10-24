"""Financial crime: AML customers + KYC files, 12 months of transactions with
transaction-monitoring alerts, cases and STRs, sanctions/PEP screening through
the real engine (queue, adjudication, whitelist, confirmed matches, ongoing and
delta re-screening), internal blacklist / PEP lists, merchants (KYB) and the
AML-assurance module (key roles, monitoring programme, annual report, unusual
transactions register, screening QA, employee screening).

Engine calls are the slow part (~0.6 s each). FINCRIME_SCREEN_N sets how many
customers go through the engine at onboarding (default 24; the others are
marked as screened clear without a history row). FINCRIME_LIGHT=1 also skips
employee screening and the screening QA cases (quick tests).
"""
import json
import os
import time
import uuid
from datetime import date, datetime, timedelta

import psycopg2.extras

N_SCREEN = int(os.environ.get("FINCRIME_SCREEN_N", "24"))
LIGHT = os.environ.get("FINCRIME_LIGHT") == "1"

HR_COUNTRIES = {'Iran', 'North Korea', 'Myanmar', 'Afghanistan', 'Syria', 'Yemen', 'Libya', 'Somalia', 'Sudan',
                'Iraq', 'Mali', 'Burkina Faso', 'Haiti', 'Laos', 'South Sudan', 'Tanzania', 'Vietnam', 'Nigeria',
                'Pakistan', 'Philippines'}

MALE = [('Ahmed', 'أحمد'), ('Mohamed', 'محمد'), ('Mahmoud', 'محمود'), ('Mostafa', 'مصطفى'), ('Hassan', 'حسن'),
        ('Hussein', 'حسين'), ('Ibrahim', 'إبراهيم'), ('Khaled', 'خالد'), ('Omar', 'عمر'), ('Ali', 'علي'),
        ('Youssef', 'يوسف'), ('Tarek', 'طارق'), ('Sameh', 'سامح'), ('Walid', 'وليد'), ('Hany', 'هاني'),
        ('Ayman', 'أيمن'), ('Ashraf', 'أشرف'), ('Gamal', 'جمال'), ('Reda', 'رضا'), ('Saber', 'صابر'),
        ('Ramadan', 'رمضان'), ('Shaaban', 'شعبان'), ('Fathy', 'فتحي'), ('Magdy', 'مجدي'), ('Nasser', 'ناصر'),
        ('Sayed', 'سيد'), ('Emad', 'عماد'), ('Adel', 'عادل'), ('Karim', 'كريم'), ('Islam', 'إسلام'),
        ('Abdallah', 'عبدالله'), ('Medhat', 'مدحت'), ('Atef', 'عاطف'), ('Hamdy', 'حمدي'), ('Ragab', 'رجب'),
        ('Samir', 'سمير'), ('Wael', 'وائل'), ('Essam', 'عصام'), ('Fouad', 'فؤاد'), ('Saad', 'سعد')]
FEMALE = [('Fatma', 'فاطمة'), ('Aya', 'آية'), ('Mona', 'منى'), ('Hanan', 'حنان'), ('Samia', 'سامية'),
          ('Nadia', 'نادية'), ('Heba', 'هبة'), ('Doaa', 'دعاء'), ('Asmaa', 'أسماء'), ('Rasha', 'رشا'),
          ('Eman', 'إيمان'), ('Nagwa', 'نجوى'), ('Sabah', 'صباح'), ('Zeinab', 'زينب'), ('Amal', 'أمل'),
          ('Azza', 'عزة'), ('Shaimaa', 'شيماء'), ('Marwa', 'مروة'), ('Hoda', 'هدى'), ('Salwa', 'سلوى'),
          ('Nesma', 'نسمة'), ('Wafaa', 'وفاء'), ('Soad', 'سعاد'), ('Ghada', 'غادة')]
FAMILY = [('El-Sayed', 'السيد'), ('Abdel Aziz', 'عبدالعزيز'), ('Shehata', 'شحاتة'), ('El-Masry', 'المصري'),
          ('Farag', 'فرج'), ('Salem', 'سالم'), ('Hegazy', 'حجازي'), ('Morsy', 'مرسي'), ('Abdel Ghani', 'عبدالغني'),
          ('Soliman', 'سليمان'), ('Zaki', 'زكي'), ('Mansour', 'منصور'), ('El-Naggar', 'النجار'), ('Badawy', 'بدوي'),
          ('Ghoneim', 'غنيم'), ('Rizk', 'رزق'), ('Kandil', 'قنديل'), ('Atia', 'عطية'), ('Khalil', 'خليل'),
          ('Darwish', 'درويش'), ('Ismail', 'إسماعيل'), ('Lotfy', 'لطفي'), ('Sharaf', 'شرف'), ('Abu Zeid', 'أبو زيد'),
          ('El-Gendy', 'الجندي'), ('Metwally', 'متولي'), ('Hamouda', 'حمودة'), ('Tantawy', 'طنطاوي'),
          ('Galal', 'جلال'), ('Abdel Maksoud', 'عبدالمقصود'), ('Gad', 'جاد'), ('Hafez', 'حافظ')]

BRANCHES = [('Cairo', 'القاهرة', 'NM-CAI-01', ['Shubra', 'El-Sayeda Zeinab', 'Ain Shams', 'El-Matareya', 'Boulaq']),
            ('Giza', 'الجيزة', 'NM-GIZ-02', ['Imbaba', 'Boulaq El-Dakrour', 'Faisal', 'El-Haram', 'Kerdasa']),
            ('Assiut', 'أسيوط', 'NM-ASY-03', ['Assiut City', 'Abnoub', 'Manfalut', 'Dairut', 'El-Qusiya'])]
OCCUP = [  # occupation, product, income range
    ('Grocery shop owner', 'micro_loan', '50K-100K'), ('Tailor', 'micro_loan', '<50K'),
    ('Poultry farmer', 'micro_loan', '50K-100K'), ('Street food vendor', 'micro_loan', '<50K'),
    ('Mobile phone repair shop owner', 'micro_loan', '50K-100K'), ('Carpenter', 'micro_loan', '<50K'),
    ('Hairdresser', 'micro_loan', '<50K'), ('Vegetable trader', 'group_loan', '<50K'),
    ('Home-based baker', 'group_loan', '<50K'), ('Handicrafts producer', 'group_loan', '<50K'),
    ('Government employee', 'consumer_finance', '50K-100K'), ('Teacher', 'consumer_finance', '50K-100K'),
    ('Nurse', 'consumer_finance', '50K-100K'), ('Private-sector accountant', 'consumer_finance', '100K-500K'),
    ('Microbus driver', 'consumer_finance', '50K-100K'), ('Livestock trader', 'micro_loan', '100K-500K')]
PURPOSE = {'micro_loan': 'Microfinance loan - working capital', 'group_loan': 'Group lending - working capital',
           'consumer_finance': 'Consumer finance - household goods instalment purchase',
           'sme_loan': 'Small business loan - working capital and equipment'}

# name_en, name_ar, activity, city index
CORPS = [
    ('Nile Star Trading', 'النجم للتجارة', 'Wholesale foodstuffs', 0),
    ('Al Amal Trading Company', 'شركة الأمل للتجارة', 'General trading', 1),
    ('Delta Horizon Import & Export', 'دلتا هورايزن للاستيراد والتصدير', 'Import and export of spare parts', 0),
    ('Sky Pyramids Travel', 'سكاي بيراميدز للسياحة', 'Travel agency', 1),
    ('El-Noor Plastics Workshop', 'ورشة النور للبلاستيك', 'Plastic products manufacturing', 0),
    ('Upper Egypt Dairy Farms', 'مزارع الصعيد للألبان', 'Dairy farming', 2),
    ('Golden Wheat Bakery', 'مخبز القمح الذهبي', 'Bakery', 1),
    ('Assiut Modern Furniture', 'أسيوط الحديثة للأثاث', 'Furniture workshop', 2),
    ('Giza Auto Spare Parts', 'الجيزة لقطع غيار السيارات', 'Auto spare parts retail', 1),
    ('Masr Green Agriculture', 'مصر الخضراء للزراعة', 'Agricultural inputs trading', 2),
    ('Cairo Print House', 'دار القاهرة للطباعة', 'Printing services', 0),
    ('El-Salam Pharmacy Supplies', 'السلام للمستلزمات الصيدلية', 'Medical supplies distribution', 0),
    ('Red Sea Marble Works', 'البحر الأحمر للرخام', 'Marble cutting', 1),
    ('Nour El Sabah Textiles', 'نور الصباح للمنسوجات', 'Textile workshop', 0),
    ('Future Tech Computer Store', 'فيوتشر تك للحاسبات', 'Computer retail', 1),
    ('Om El Donia Catering', 'أم الدنيا للتغذية', 'Catering services', 0),
    ('Pharaoh Leather Goods', 'فرعون للمنتجات الجلدية', 'Leather goods workshop', 0),
    ('Nour El Sabah Poultry', 'نور الصباح للدواجن', 'Poultry farm', 2),
    ('Banha Building Materials', 'بنها لمواد البناء', 'Building materials trading', 1),
    ('El-Wadi Transport Services', 'الوادي لخدمات النقل', 'Goods transport', 2)]

# key, en, ar, gender, nationality, occupation index, city index, extra
SPECIAL = [
    ('saber', 'Saber Ramadan Abu Zeid', 'صابر رمضان أبو زيد', 'M', 'Egypt', 0, 1),
    ('walid', 'Walid Atef Morsy', 'وليد عاطف مرسي', 'M', 'Egypt', 15, 2),
    ('sudan', 'Abdelmoneim Osman Babiker', 'عبدالمنعم عثمان بابكر', 'M', 'Sudan', 0, 0),
    ('syria', 'Ahmad Khaled Al-Hamwi', 'أحمد خالد الحموي', 'M', 'Syria', 4, 1),
    ('pep1', 'Fawzy Abdel Hamid Kandil', 'فوزي عبدالحميد قنديل', 'M', 'Egypt', 15, 2),
    ('pep2', 'Nagwa Ibrahim Tantawy', 'نجوى إبراهيم طنطاوي', 'F', 'Egypt', 11, 0),
    ('fp1', 'Hassan Mohamed Hassan', 'حسن محمد حسن', 'M', 'Egypt', 2, 2),
    ('fp2', 'Abdel Rahman Hassan', 'عبدالرحمن حسن', 'M', 'Egypt', 5, 1),
    ('fp3', 'Mohamed Ibrahim Moussa', 'محمد إبراهيم موسى', 'M', 'Egypt', 7, 2),
    ('third', 'Shaimaa Fathy El-Gendy', 'شيماء فتحي الجندي', 'F', 'Egypt', 1, 0),
    ('recent', 'Ramadan Shaaban Hegazy', 'رمضان شعبان حجازي', 'M', 'Egypt', 0, 0),
    ('velo', 'Magdy Saber Ghoneim', 'مجدي صابر غنيم', 'M', 'Egypt', 4, 1),
]

MERCHANTS = [  # name, ar trade name, industry, city, status
    ('El-Fayrouz Home Appliances', 'الفيروز للأجهزة المنزلية', 'Home appliances retail', 'Cairo', 'APPROVED'),
    ('Bayt El-Mobile Phones', 'بيت الموبايل', 'Mobile phones retail', 'Giza', 'APPROVED'),
    ('Nour Furniture Gallery', 'معرض نور للأثاث', 'Furniture retail', 'Cairo', 'APPROVED'),
    ('Rawda Electronics', 'الروضة للإلكترونيات', 'Electronics retail', 'Cairo', 'APPROVED'),
    ('Al-Hana Bridal & Furniture', 'الهناء للأثاث وتجهيز العرائس', 'Furniture retail', 'Assiut', 'APPROVED'),
    ('Masr Cooling & AC', 'مصر للتبريد والتكييف', 'Air conditioning retail', 'Giza', 'APPROVED'),
    ('Sahara Motorcycles', 'صحارى للدراجات النارية', 'Motorcycles retail', 'Giza', 'REJECTED'),
    ('Tahrir Computers', 'التحرير للحاسبات', 'Computer retail', 'Cairo', 'APPROVED'),
    ('Bab El-Louk Kitchenware', 'باب اللوق للأدوات المنزلية', 'Kitchenware retail', 'Cairo', 'APPROVED'),
    ('Assiut Electro Center', 'مركز أسيوط للأجهزة الكهربائية', 'Home appliances retail', 'Assiut', 'SUBMITTED'),
    ('Giza Solar Energy Systems', 'الجيزة لأنظمة الطاقة الشمسية', 'Solar equipment', 'Giza', 'SUBMITTED'),
    ('Imbaba Sewing Machines', 'إمبابة لماكينات الخياطة', 'Sewing machines retail', 'Giza', 'SENT'),
    ('Faisal Ceramic & Sanitary', 'فيصل للسيراميك والأدوات الصحية', 'Building finishes retail', 'Giza', 'SENT'),
    ('Helwan Bicycles', 'حلوان للدراجات', 'Bicycles retail', 'Cairo', 'PENDING'),
    ('Shubra Optical Center', 'مركز شبرا للبصريات', 'Optical retail', 'Cairo', 'PENDING')]

SANCTIONED = [  # name, entity type, context, outcome
    ('Mahan Air', 'ENTITY', 'Beneficiary named on an outgoing payment request of Sky Pyramids Travel (ticket settlement)',
     'reported'),
    ('Korea Kwangson Banking Corporation', 'ENTITY',
     'Ordering institution on an incoming transfer to Delta Horizon Import & Export', 'reported'),
    ('Viktor Bout', 'INDIVIDUAL', 'Remitter name on a cross-border transfer instruction received at Cairo Downtown branch',
     'closed'),
    ('Rami Makhlouf', 'INDIVIDUAL', 'Named as shareholder in documents of a prospective corporate applicant', 'open'),
]

INTERNAL_PEPS = [  # en, ar, position, category, reason
    ('Fawzy Abdel Hamid Kandil', 'فوزي عبدالحميد قنديل', 'Former member, Assiut Governorate Local Council (demo)',
     'Domestic PEP', 'Held a prominent public function until 2024 (fictional demo record)'),
    ('Mahmoud Sherif Abdel Ghani', 'محمود شريف عبدالغني', 'Member of the House of Representatives (demo)',
     'Domestic PEP', 'Sitting member of parliament (fictional demo record)'),
    ('Nagwa Ibrahim Tantawy', 'نجوى إبراهيم طنطاوي', 'Spouse of a member of parliament (demo)', 'Family member',
     'Spouse of Mahmoud Sherif Abdel Ghani (fictional demo record)'),
    ('Adel Mostafa Shalaby', 'عادل مصطفى شلبي', 'Deputy Governor (demo)', 'Domestic PEP',
     'Senior regional government official (fictional demo record)'),
    ('Samir Lotfy Habib', 'سمير لطفي حبيب', 'Chairman of a state-owned company (demo)', 'Domestic PEP',
     'Head of a state-owned enterprise (fictional demo record)'),
    ('Laila Kamal Fahmy', 'ليلى كمال فهمي', 'Senior judge (demo)', 'Domestic PEP',
     'Senior member of the judiciary (fictional demo record)')]

BLACKLIST = [  # en, ar, entity type, category, risk, reason, days ago
    ('Tamer Fouad Abdel Maksoud', 'تامر فؤاد عبدالمقصود', 'INDIVIDUAL', 'Fraud', 'HIGH',
     'Loan application with a forged national ID card detected at Giza branch (internal investigation INV-2025-014)', 330),
    ('Reda Salah Kassem', 'رضا صلاح قاسم', 'INDIVIDUAL', 'Fraud', 'HIGH',
     'Identity-theft ring: obtained three group loans with borrowed IDs (Assiut branch)', 260),
    ('Sameh Nabil Ezzat', 'سامح نبيل عزت', 'INDIVIDUAL', 'Fraud', 'HIGH',
     'Submitted forged salary certificates for consumer-finance applications', 190),
    ('El-Masria Quick Loans Brokerage', 'المصرية للوساطة في القروض السريعة', 'ORGANIZATION', 'Fraud', 'CRITICAL',
     'Unlicensed loan broker charging clients fees and submitting fabricated documents', 150),
    ('Hanan Sobhy Mekawy', 'حنان صبحي مكاوي', 'INDIVIDUAL', 'Fraud', 'HIGH',
     'Collusion with a former loan officer to create fictitious group-loan members', 95),
    ('Ezzat Hamed Barakat', 'عزت حامد بركات', 'INDIVIDUAL', 'Legal Order - Asset Freeze', 'CRITICAL',
     'Court order freezing the assets of the named person (fictional demo order no. DEMO-AF-2026-07)', 40)]


def seed(ctx):
    t0 = time.time()
    st = {'t': t0}

    def lap(label):
        print(f'    {label:<28} {time.time() - st["t"]:5.1f}s', flush=True)
        st['t'] = time.time()

    s = Seeder(ctx)
    s.customers()
    lap('customers')
    s.merchants()
    lap('merchants')
    s.transactions()
    lap('transactions')
    s.tm_alerts()
    lap('tm alerts + cases')
    s.sars()
    lap('sars + unusual register')
    s.lists()
    lap('internal lists')
    s.screening()
    lap('screening')
    s.kyc()
    lap('kyc files + ratings')
    s.ongoing_and_delta()
    lap('ongoing + delta')
    s.assurance()
    lap('aml assurance')
    s.finish()
    lap('finish')


class Seeder:
    def __init__(self, ctx):
        self.c = ctx
        self.r = ctx.rnd
        self.now = ctx.now
        self.cust = []          # dicts
        self.by_key = {}
        self.merch = []
        self.tx = []
        self.alerts = []
        self.hist = {}          # customer id -> screening history id

    # ------------------------------------------------------------ helpers
    def ts(self, dt):
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    def dt(self, days, hour=None):
        d = self.now - timedelta(days=days)
        h = hour if hour is not None else self.r.choice([9, 10, 11, 12, 13, 14, 15, 16])
        return d.replace(hour=h, minute=self.r.randrange(60), second=self.r.randrange(60), microsecond=0)

    def phone(self):
        return f'+20 10 0000 {self.r.randrange(10000):04d}'

    def nid(self):
        return 'DEMO' + ''.join(str(self.r.randrange(10)) for _ in range(10))

    def commit(self):
        self.c.commit()

    def has_table(self, name):
        try:
            self.c.cols(name)
            return True
        except KeyError:
            return False

    # ------------------------------------------------------------ customers
    def customers(self):
        c, r = self.c, self.r
        used = set()
        rows = []
        for sp in SPECIAL:
            key, en, ar, g, nat, occ, city = sp
            rows.append(dict(key=key, en=en, ar=ar, gender=g, nat=nat, occ=OCCUP[occ], city=city, kind='INDIVIDUAL'))
            used.add(en)
        while len(rows) < 150:
            g = 'F' if r.random() < 0.45 else 'M'
            f = r.choice(FEMALE if g == 'F' else MALE)
            fa = r.choice(MALE)
            fam = r.choice(FAMILY)
            en = f'{f[0]} {fa[0]} {fam[0]}'
            if en in used or f[0] == fa[0]:
                continue
            used.add(en)
            rows.append(dict(key=None, en=en, ar=f'{f[1]} {fa[1]} {fam[1]}', gender=g, nat='Egypt',
                             occ=r.choice(OCCUP), city=r.choice([0, 0, 1, 1, 2]), kind='INDIVIDUAL'))
        for i, (en, ar, act, city) in enumerate(CORPS):
            key = {0: 'nilestar', 1: 'fpcorp', 2: 'delta', 3: 'sky'}.get(i)
            rows.append(dict(key=key, en=en, ar=ar, gender=None, nat='Egypt', occ=(act, 'sme_loan', '>500K'),
                             city=city, kind='CORPORATE'))
        # onboarding: spread over the last 18 months, more recent activity
        days = sorted((int(30 + (r.random() ** 1.3) * 510) for _ in rows), reverse=True)
        r.shuffle(days)
        fixed_days = {'saber': 420, 'walid': 500, 'sudan': 380, 'syria': 300, 'pep1': 250, 'pep2': 160,
                      'fp1': 230, 'fp2': 120, 'fp3': 75, 'third': 210, 'recent': 330, 'velo': 280,
                      'nilestar': 450, 'fpcorp': 140, 'delta': 400, 'sky': 350}
        n = 0
        for i, row in enumerate(rows):
            n += 1
            od = fixed_days.get(row['key'], days[i])
            row['onb_days'] = od
            onb = self.dt(od)
            city_en, city_ar, branch, districts = BRANCHES[row['city']]
            corp = row['kind'] == 'CORPORATE'
            occ, product, income = row['occ']
            status = 'ACTIVE'
            if not corp and row['key'] is None and r.random() < 0.06 and od > 200:
                status = 'CLOSED'
            if row['key'] is None and od < 40 and r.random() < 0.5:
                status = 'PENDING'
            row['status'] = status
            row['product'] = product
            row['branch'] = branch
            row['ref'] = f'NMF-C{n:05d}'
            row['channel'] = 'branch' if r.random() < 0.7 else r.choice(['agent', 'digital'])
            if corp:
                row['channel'] = r.choice(['branch', 'branch', 'digital'])
            first = row['en'].split()[0].lower().replace("'", '')
            email = (f"info.{row['ref'][-3:]}@{first}-co.example" if corp
                     else f"{first}.{row['ref'][-4:]}@mail.example")
            dob = None if corp else str(date(1965, 1, 1) + timedelta(days=r.randrange(365 * 38)))
            idn = None if corp else self.nid()
            pep = 1 if row['key'] in ('pep1', 'pep2') else 0
            vals = dict(
                customer_reference=row['ref'], customer_number=row['ref'], customer_type=row['kind'],
                full_name=row['en'], full_name_arabic=row['ar'],
                company_name=row['en'] if corp else None, date_of_birth=dob,
                nationality=row['nat'], id_type=None if corp else 'NATIONAL_ID', id_number=idn,
                id_expiry_date=None if corp else str(onb.date() + timedelta(days=365 * r.choice([3, 4, 5, 6]))),
                registration_number=f'DEMO-CR-{r.randrange(10000, 99999)}' if corp else None,
                registration_country='Egypt' if corp else None,
                incorporation_date=str(date(2008, 1, 1) + timedelta(days=r.randrange(4500))) if corp else None,
                business_activity=occ if corp else None,
                address_line1=f'{r.randrange(1, 140)} Example St., {r.choice(districts)} (demo address)',
                city=city_en, country='Egypt', postal_code=None, phone=self.phone(), email=email,
                occupation=None if corp else occ, employer=None if corp or product != 'consumer_finance' else
                r.choice(['Ministry of Education (demo)', 'Cairo University Hospital (demo)', 'Private clinic (demo)',
                          'Demo Logistics Co.', 'Governorate office (demo)']),
                source_of_income=('Business revenue' if corp else
                                  'Salary' if product == 'consumer_finance' else 'Own business income'),
                annual_income_range=income, purpose_of_relationship=PURPOSE[product],
                expected_transaction_volume=('EGP 100,000-500,000 per month' if corp else
                                             'Up to EGP 15,000 per month'),
                risk_classification='LOW', risk_classification_date=str(onb.date()), risk_score=10,
                is_pep=pep, onboarding_date=str(onb.date()), cdd_completed=0 if status == 'PENDING' else 1,
                cdd_completed_by=c.uid(r.choice(['co', 'aml'])) if status != 'PENDING' else None,
                cdd_completed_date=str((onb + timedelta(days=r.randrange(0, 3))).date()) if status != 'PENDING' else None,
                status=status, approved_by=c.uid('co') if status != 'PENDING' else None,
                approval_date=str(onb.date()) if status != 'PENDING' else None,
                closed_date=str(self.dt(r.randrange(10, 120)).date()) if status == 'CLOSED' else None,
                closed_reason='Loan fully repaid; relationship ended at client request' if status == 'CLOSED' else None,
                created_at=self.ts(onb), created_by=c.uid('lo1' if branch == 'NM-GIZ-02' else 'lo2'
                                                           if branch == 'NM-ASY-03' else 'br1'),
                updated_at=self.ts(onb), updated_by=c.uid('co'), is_encrypted=0, is_sanctioned=0,
                is_high_risk_country=1 if row['nat'] in HR_COUNTRIES else 0, requires_edd=0, edd_completed=0,
                screening_status='Not Screened')
            if pep:
                vals.update(pep_category='Domestic PEP' if row['key'] == 'pep1' else 'Family member of PEP',
                            pep_position=('Former member, Assiut Governorate Local Council (demo)' if row['key'] == 'pep1'
                                          else 'Spouse of a member of parliament (demo)'),
                            pep_screening_date=str(onb.date()), pep_approved_by=c.uid('ceo'),
                            pep_approval_date=str((onb + timedelta(days=4)).date()),
                            pep_approval_notes='Business relationship approved by the CEO after EDD (source of '
                                               'funds and wealth verified).')
            try:
                from data_protection.encryption_service import EncryptionService
                vals['national_id_hash'] = EncryptionService.hash_value(idn) if idn else None
            except Exception:
                pass
            row['id'] = c.ins('customers', **vals)
            row['onb'] = onb
            row['email'] = email
            self.cust.append(row)
            if row['key']:
                self.by_key[row['key']] = row
        self.commit()
        from parties.linker import upsert_party_for_customer
        for row in self.cust:
            row['party_id'] = upsert_party_for_customer(row['id'])
        from database.db import get_db
        get_db().commit()
        # party rows: creation date = onboarding
        for row in self.cust:
            if row['party_id']:
                c.q("UPDATE parties SET created_at = %s, updated_at = %s WHERE id = %s",
                    (row['onb'], row['onb'], row['party_id']))
                c.q("UPDATE party_links SET linked_at = %s WHERE party_id = %s AND source_table = 'customers'",
                    (row['onb'], row['party_id']))
        self.commit()

    # ------------------------------------------------------------ merchants
    def merchants(self):
        c, r = self.c, self.r
        saber = self.by_key['saber']
        for i, (en, ar, ind, city, kst) in enumerate(MERCHANTS):
            od = int(40 + (r.random() ** 1.2) * 420) if kst in ('APPROVED', 'REJECTED') else r.randrange(3, 35)
            cr = self.dt(od)
            g = r.choice(MALE)
            ubo = f'{g[0]} {r.choice(MALE)[0]} {r.choice(FAMILY)[0]}'
            vals = dict(
                merchant_name=en, trade_name=ar, cr_number=f'DEMO-CR-{r.randrange(10000, 99999)}',
                tax_id=f'DEMO-{r.randrange(100, 999)}-{r.randrange(100, 999)}-{r.randrange(100, 999)}',
                business_type=r.choice(['SOLE_PROPRIETORSHIP', 'SOLE_PROPRIETORSHIP', 'LLC', 'PARTNERSHIP']),
                industry=ind, website=None, contact_person=ubo,
                contact_email=f'sales{i + 1}@merchant{i + 1}.example', contact_phone=self.phone(),
                address=f'{r.randrange(1, 90)} Market St., {city} (demo address)', city=city, country='Egypt',
                ubo_name=saber['en'] if en == 'Sahara Motorcycles' else ubo, ubo_nationality='Egypt',
                ubo_id_type='NATIONAL_ID', ubo_id_number=self.nid(),
                ubo_dob=str(date(1968, 1, 1) + timedelta(days=r.randrange(365 * 30))),
                ownership_percentage=100.0 if r.random() < 0.6 else float(r.choice([51, 60, 75])),
                bank_name='Demo Bank S.A.E.', bank_account_number=f'DEMO{r.randrange(10 ** 9, 10 ** 10)}',
                iban=f'EG00DEMO{r.randrange(10 ** 11, 10 ** 12)}', kyc_status=kst, kyc_token=str(uuid.uuid4()),
                kyc_sent_at=self.ts(cr + timedelta(hours=2)) if kst != 'PENDING' else None,
                kyc_submitted_at=self.ts(cr + timedelta(days=2)) if kst in ('APPROVED', 'SUBMITTED', 'REJECTED') else None,
                kyc_reviewed_by=c.uid('aml') if kst in ('APPROVED', 'REJECTED') else None,
                kyc_reviewed_at=self.ts(cr + timedelta(days=5)) if kst in ('APPROVED', 'REJECTED') else None,
                kyc_rejection_reason=('Beneficial owner is the subject of an STR and is on the internal blacklist '
                                      '(loan fraud). Relationship declined.') if kst == 'REJECTED' else None,
                risk_level='MEDIUM' if kst == 'REJECTED' else r.choice(['LOW', 'LOW', 'MEDIUM']),
                sanctions_checked=0, pep_checked=1 if kst in ('APPROVED', 'REJECTED') else 0,
                created_at=self.ts(cr), created_by=c.uid('ops'), updated_at=self.ts(cr + timedelta(days=5)),
                updated_by=c.uid('aml'), internal_reference_number=f'MER-{cr.year}-{i + 1:04d}',
                internal_account_number=f'NMF-MA-{1000 + i}', screening_status='Not Screened',
                onboarding_status={'APPROVED': 'Active', 'REJECTED': 'Rejected', 'SUBMITTED': 'Under Review',
                                   'SENT': 'Awaiting Documents', 'PENDING': 'Pending Screening'}[kst],
                kyb_link_sent_via=r.choice(['email', 'whatsapp']) if kst != 'PENDING' else None,
                pos_wallet_limit=r.choice([250000, 500000, 750000]))
            if 'incorporation_date' in c.cols('merchants'):
                vals.update(incorporation_date=str(date(2005, 1, 1) + timedelta(days=r.randrange(6000))),
                            incorporation_country='Egypt')
            mid = c.ins('merchants', **vals)
            self.merch.append(dict(id=mid, name=en, ar=ar, status=kst, created=cr, ubo=vals['ubo_name'],
                                   ubo_id=vals['ubo_id_number'], ubo_dob=vals['ubo_dob']))
        self.commit()
        from parties.linker import upsert_party_for_merchant
        for m in self.merch:
            try:
                upsert_party_for_merchant(m['id'])
            except Exception as e:
                print('    party sync failed for merchant', m['id'], e)
        from database.db import get_db
        get_db().commit()

    # ------------------------------------------------------------ transactions
    def transactions(self):
        c, r = self.c, self.r
        approved_merchants = [m['name'] for m in self.merch if m['status'] == 'APPROVED']
        T = []

        def add(cust, when, typ, amt, cp=None, cpc='Egypt', purpose=None, acct=None, cur='EGP', tag=None):
            if when > self.now - timedelta(minutes=5):
                return
            if when < self.now - timedelta(days=365):
                return
            T.append(dict(cust=cust, when=when, type=typ, amount=round(float(amt), 2), cp=cp, cpc=cpc,
                          purpose=purpose, acct=acct, cur=cur, tag=tag))

        for cu in self.cust:
            if cu['status'] == 'PENDING':
                continue
            corp = cu['kind'] == 'CORPORATE'
            product = cu['product']
            start = cu['onb'] + timedelta(days=r.randrange(1, 6))
            end = self.now if cu['status'] != 'CLOSED' else self.now - timedelta(days=r.randrange(15, 90))
            when = start
            cycle = 0
            while when < end and cycle < 4:
                cycle += 1
                if corp:
                    amount = r.randrange(15, 120) * 10000
                    term, step = r.choice([12, 18, 24]), 30
                elif product == 'group_loan':
                    amount, term, step = r.randrange(5, 21) * 1000, r.choice([12, 16, 20]), 14
                elif product == 'consumer_finance':
                    amount, term, step = r.randrange(8, 61) * 1000, r.choice([6, 9, 12, 18]), 30
                else:
                    amount, term = r.randrange(10, 61) * 1000 * (1 + cycle * 0.2), r.choice([6, 9, 12])
                    step = r.choice([14, 30])
                    term = term * 2 if step == 14 else term
                if cu['key'] == 'saber':
                    amount, term = 60000, 12
                cp = r.choice(approved_merchants) if product == 'consumer_finance' else 'Client account (own)'
                add(cu, when.replace(hour=11), 'DISBURSEMENT', amount, cp=cp,
                    purpose=('Consumer finance purchase financed' if product == 'consumer_finance' else
                             f'Loan disbursement - cycle {cycle}'), acct=f"NMF-LN-{cu['id']:05d}-{cycle}")
                period_rate = 0.30 * (step / 365)
                inst = amount * period_rate / (1 - (1 + period_rate) ** -term)
                early = (not corp) and r.random() < 0.10 and cu['key'] is None
                early_at = r.randrange(3, max(4, term - 1)) if early else None
                paid = 0
                for k in range(1, term + 1):
                    d = when + timedelta(days=step * k + r.randrange(-2, 4))
                    if d >= end:
                        break
                    if early_at and k == early_at:
                        bal = inst * (term - k + 1) * 0.93
                        add(cu, d, 'CASH_DEPOSIT', round(bal, -1), cp='Branch cash counter',
                            purpose='Early settlement of loan (cash)', tag='early')
                        paid = term
                        break
                    if corp:
                        typ = 'TRANSFER_IN' if r.random() < 0.85 else 'CASH_DEPOSIT'
                        cpn = f"{cu['en']} - company bank account" if typ == 'TRANSFER_IN' else 'Branch cash counter'
                    else:
                        x = r.random()
                        typ = 'CASH_DEPOSIT' if x < 0.5 else ('REPAYMENT' if x < 0.88 else 'TRANSFER_IN')
                        if typ == 'CASH_DEPOSIT' and inst >= 9000:
                            typ = 'TRANSFER_IN'
                        cpn = {'CASH_DEPOSIT': 'Branch cash counter', 'REPAYMENT': 'Mobile wallet collection',
                               'TRANSFER_IN': 'Client bank account'}[typ]
                    add(cu, d, typ, round(inst, 2), cp=cpn, purpose=f'Instalment {k}/{term}')
                    paid = k
                if paid < term:
                    break
                when = d + timedelta(days=r.randrange(10, 40))
            # corporates: occasional large cash deposits (seasonal sales) - TM001
            if corp and cu['key'] not in ('delta', 'sky'):
                for _ in range(r.choice([0, 0, 1, 1, 2])):
                    d = self.dt(r.randrange(5, 360))
                    if d > cu['onb']:
                        add(cu, d, 'CASH_DEPOSIT', r.randrange(12, 45) * 1000, cp='Branch cash counter',
                            purpose='Advance instalment payment from seasonal sales')

        k = self.by_key
        # 1. structuring before early settlement (Saber) - 5 cash deposits in 3 days, then settlement
        for i, d in enumerate([128, 128, 127, 126, 126]):
            add(k['saber'], self.dt(d, 10 + i), 'CASH_DEPOSIT', r.choice([9400, 9650, 9800, 9500, 9700]),
                cp='Branch cash counter', purpose='Partial prepayment (cash)', tag='struct1')
        for i, d in enumerate([97, 96, 96, 95]):
            add(k['saber'], self.dt(d, 11 + i), 'CASH_DEPOSIT', r.choice([9300, 9600, 9900]),
                cp='Branch cash counter', purpose='Partial prepayment (cash)', tag='struct2')
        # 2. dormant account reactivated with a large settlement (Walid)
        T[:] = [t for t in T if not (t['cust'] is k['walid'] and (self.now - t['when']).days < 170)]
        add(k['walid'], self.dt(38, 12), 'CASH_DEPOSIT', 74500, cp='Branch cash counter',
            purpose='Full settlement of outstanding loan after 4 months of inactivity', tag='dormant')
        # 3. Sudan / Syria remittances funding instalments
        for d in [300, 241, 182, 121, 64, 22]:
            add(k['sudan'], self.dt(d), 'TRANSFER_IN', r.randrange(8, 15) * 1000, cp='Family member (remitter)',
                cpc='Sudan', purpose='Family support - instalment payment', tag='hrc')
        for d in [200, 199, 198, 197, 196, 195, 150, 90, 33]:
            add(k['syria'], self.dt(d), 'TRANSFER_IN', r.randrange(3, 9) * 1000, cp='Relative abroad (remitter)',
                cpc='Syria', purpose='Remittance - instalment payment', tag='hrc')
        # 4. third-party repayments (Shaimaa) - several unrelated payers
        for i, d in enumerate([25, 21, 18, 14, 9, 6]):
            add(k['third'], self.dt(d), 'TRANSFER_IN', r.randrange(6, 14) * 1000,
                cp=f'{r.choice(MALE)[0]} {r.choice(MALE)[0]} {r.choice(FAMILY)[0]} (third party)',
                purpose='Instalment paid by a third party', tag='third')
        # 5. velocity - many small wallet repayments in a day (Magdy)
        for i in range(7):
            add(k['velo'], self.dt(160, 9 + i), 'REPAYMENT', r.randrange(4, 9) * 100, cp='Mobile wallet collection',
                purpose='Instalment (split wallet payments)', tag='velo')
        # 6. Delta Horizon - overpayment then refund to a third-party account (rapid round trip)
        add(k['delta'], self.dt(58, 10), 'TRANSFER_IN', 420000, cp='Unrelated company (overseas)', cpc='United Arab Emirates',
            purpose='Loan overpayment', tag='roundtrip')
        add(k['delta'], self.dt(58, 15), 'TRANSFER_OUT', 405000, cp='Third-party account (refund request)',
            cpc='Turkey', purpose='Refund of excess payment to a third-party account', tag='roundtrip')
        add(k['delta'], self.dt(212, 10), 'TRANSFER_IN', 185000, cp='Trading partner (overseas)', cpc='China',
            purpose='Customer payment for spare parts', tag='intl')
        # 7. Sky Pyramids - payment request to a sanctioned airline (blocked)
        add(k['sky'], self.dt(84, 13), 'TRANSFER_OUT', 96500, cp='Mahan Air', cpc='Iran',
            purpose='Group ticket settlement (payment blocked - sanctions)', tag='sanctions')
        # 8. recent structuring - evaluated by the live TM engine (last 2 days)
        rec = []
        for h in (30, 26, 20, 3):
            when = self.now - timedelta(hours=h)
            rec.append(dict(cust=k['recent'], when=when.replace(microsecond=0), type='CASH_DEPOSIT',
                            amount=float(r.choice([9200, 9450, 9700, 9850])), cp='Branch cash counter', cpc='Egypt',
                            purpose='Partial prepayment (cash)', acct=None, cur='EGP', tag='live'))
        rec.append(dict(cust=self.by_key['nilestar'], when=(self.now - timedelta(hours=5)).replace(microsecond=0),
                        type='CASH_DEPOSIT', amount=38000.0, cp='Branch cash counter', cpc='Egypt',
                        purpose='Advance instalment payment from seasonal sales', acct=None, cur='EGP', tag='live'))
        T.sort(key=lambda t: t['when'])
        T.extend(rec)
        # insert
        users = {'NM-CAI-01': c.uid('br1'), 'NM-GIZ-02': c.uid('lo1'), 'NM-ASY-03': c.uid('lo2')}
        vals = []
        for i, t in enumerate(T):
            t['ref'] = f"TXN-{t['when'].strftime('%Y%m%d')}-{i + 1:06d}"
            vals.append((t['ref'], t['cust']['id'], self.ts(t['when']), t['type'], t['amount'], t['cur'], t['cp'],
                         t['acct'], t['cpc'], t['purpose'], None, 0, 0, 0, 0, 0, self.ts(t['when']),
                         users[t['cust']['branch']]))
        ids = psycopg2.extras.execute_values(
            c.cur, """INSERT INTO transactions (transaction_reference, customer_id, transaction_date, transaction_type,
                      amount, currency, counterparty_name, counterparty_account, counterparty_country,
                      purpose_of_transaction, remittance_information, sanctions_hit, pep_involvement, risk_score,
                      alert_raised, sar_filed, created_at, created_by) VALUES %s RETURNING id""", vals,
            page_size=1000, fetch=True)
        for t, row in zip(T, ids):
            t['id'] = row['id']
        c.q("UPDATE transactions SET sanctions_hit = 1, sanctions_list = 'OFAC SDN', risk_score = 95 "
            "WHERE counterparty_name = 'Mahan Air'")
        self.tx = T
        self.live = rec
        self.commit()
        print(f'      {len(T)} transactions')

    # ------------------------------------------------------------ TM alerts
    def tm_alerts(self):
        c, r = self.c, self.r
        rules = {x['rule_code']: x for x in c.q("SELECT * FROM tm_rules")}
        c.q("UPDATE tm_rules SET created_by = %s, approved_by = %s, approved_at = %s, created_at = %s",
            (c.uid('mlro'), c.uid('mlro'), self.dt(400, 10), self.ts(self.dt(405, 10))))
        by_c = {}
        for t in self.tx:
            if t['tag'] != 'live':
                by_c.setdefault(t['cust']['id'], []).append(t)
        raw = []   # (rule, cust, when, [tx], description)

        def hit(code, cu, txs, desc):
            raw.append((code, cu, txs[-1]['when'] + timedelta(minutes=r.randrange(1, 4)), txs, desc))

        for cid, txs in by_c.items():
            cu = txs[0]['cust']
            last = {}
            for i, t in enumerate(txs):
                cash = t['type'] in ('CASH_DEPOSIT', 'CASH_WITHDRAWAL')
                if cash and t['amount'] >= 10000:
                    hit('TM001', cu, [t], f"Cash transaction of {t['amount']:.2f} EGP exceeds threshold of 10000")
                if cash and 6300 <= t['amount'] < 10800:
                    win = [x for x in txs[:i + 1] if x['type'] in ('CASH_DEPOSIT', 'CASH_WITHDRAWAL')
                           and 6300 <= x['amount'] < 10800 and (t['when'] - x['when']).days < 3]
                    if len(win) >= 3 and (t['when'] - last.get('TM002', datetime.min)).days >= 3:
                        last['TM002'] = t['when']
                        tot = sum(x['amount'] for x in win)
                        hit('TM002', cu, win, f"Possible structuring: {len(win)} cash transactions totalling "
                                              f"{tot:.2f} below threshold within 3 days")
                if t['cpc'] in HR_COUNTRIES and (t['when'] - last.get('TM004', datetime.min)).days >= 20:
                    last['TM004'] = t['when']
                    hit('TM004', cu, [t], f"Transaction with high-risk country: {t['cpc']}")
                day = [x for x in txs if x['when'].date() == t['when'].date() and x['when'] <= t['when']]
                if len(day) > 5 and last.get('TM003') != t['when'].date():
                    last['TM003'] = t['when'].date()
                    hit('TM003', cu, day, f"High velocity: {len(day)} transactions in last 24 hours (threshold: 5)")
                intl = [x for x in txs[:i + 1] if x['type'] in ('TRANSFER_IN', 'TRANSFER_OUT') and x['cpc'] != 'Egypt'
                        and (t['when'] - x['when']).days < 7]
                if len(intl) > 5 and (t['when'] - last.get('TM010', datetime.min)).days >= 7:
                    last['TM010'] = t['when']
                    hit('TM010', cu, intl, f"Frequent international transfers: {len(intl)} in 7 days")
                if t['type'] in ('TRANSFER_OUT',) and i:
                    back = [x for x in txs[:i] if x['type'] == 'TRANSFER_IN' and abs(x['amount'] - t['amount'])
                            < x['amount'] * 0.05 and (t['when'] - x['when']) <= timedelta(days=1)]
                    if back:
                        hit('TM007', cu, back + [t], f"Rapid round trip: funds of {back[0]['amount']} received and "
                                                     f"sent within 24 hours")
                if t['tag'] == 'dormant':
                    hit('TM006', cu, [t], f"Dormant account activity: no transactions in 90 days, now "
                                          f"{t['amount']} EGP")
                if t['tag'] == 'third' and len([x for x in txs[:i + 1] if x['tag'] == 'third']) == 5:
                    tot = sum(x['amount'] for x in txs if x['tag'] == 'third' and x['when'] <= t['when'])
                    hit('TM008', cu, [x for x in txs[:i + 1] if x['tag'] == 'third'],
                        f"Monthly volume {tot:.2f} exceeds 3x expected ({50000 / 12:.2f})")
                if t['tag'] == 'sanctions':
                    t2 = dict(t)
                    hit('TM005', cu, [t2], 'Counterparty flagged: PEP=, Sanctions=OFAC SDN (Mahan Air)')
        # keep the TM001 volume realistic: corporates' frequent cash only once a month
        raw.sort(key=lambda x: x[2])
        sar_keys = {'saber', 'walid', 'delta', 'sky', 'third'}
        aml, co, mlro = c.uid('aml'), c.uid('co'), c.uid('mlro')
        NOTES = {
            'TM001': ['Source of cash verified: proceeds of business sales; supporting invoices on file.',
                      'Customer settled early from savings (gam\'eya payout); explanation consistent with profile.',
                      'Cash deposit consistent with seasonal sales; no further action.'],
            'TM002': ['Pattern of sub-threshold cash deposits; customer could not explain source.'],
            'TM003': ['Customer split the instalment across several wallet payments due to wallet daily limits.'],
            'TM004': ['Remittances from close family abroad; amounts consistent with declared support.',
                      'Counterparty in high-risk jurisdiction; enhanced review of remitter identity performed.'],
            'TM010': ['Several small remittances from relatives in one week; documentary evidence obtained.'],
        }
        n = 0
        for code, cu, when, txs, desc in raw:
            n += 1
            age = (self.now - when).days
            rule = rules[code]
            special = cu['key'] in sar_keys and code in ('TM002', 'TM006', 'TM007', 'TM005', 'TM008')
            assignee = r.choice([aml, aml, co])
            if special:
                status = 'SAR_CREATED' if cu['key'] in ('saber', 'sky') else 'ESCALATED'
                if cu['key'] == 'third':
                    status = 'INVESTIGATING'
                assignee = mlro if status != 'INVESTIGATING' else aml
            elif age > 45:
                status = 'FALSE_POSITIVE' if (code in ('TM001', 'TM003') and r.random() < 0.55) else 'CLOSED'
            elif age > 14:
                status = r.choice(['CLOSED', 'FALSE_POSITIVE', 'INVESTIGATING', 'CLOSED'])
            elif age > 4:
                status = r.choice(['ASSIGNED', 'INVESTIGATING', 'NEW'])
            else:
                status = r.choice(['NEW', 'NEW', 'ASSIGNED'])
            disp = {'NEW': None, 'ASSIGNED': 'ASSIGN', 'INVESTIGATING': 'INVESTIGATE', 'ESCALATED': 'ESCALATE',
                    'FALSE_POSITIVE': 'FALSE_POSITIVE', 'CLOSED': 'CLOSE', 'SAR_CREATED': 'ESCALATE'}[status]
            if status in ('CLOSED', 'FALSE_POSITIVE'):
                note = r.choice(NOTES.get(code, ['Reviewed against customer profile; activity explained.']))
            elif status in ('ESCALATED', 'SAR_CREATED'):
                note = 'Escalated to the MLRO: activity inconsistent with the customer profile; STR assessment opened.'
            elif status == 'INVESTIGATING':
                note = 'Customer contacted by the branch for an explanation; documents requested.'
            elif status == 'ASSIGNED':
                note = 'Assigned for first-level review.'
            else:
                note = None
            ddate = when + timedelta(days=min(max(age - 1, 0), r.randrange(1, 6))) if disp else None
            aid = c.ins('tm_alerts', alert_reference=f"ALT-{when.strftime('%Y%m%d')}-{uuid.UUID(int=r.getrandbits(128)).hex[:12].upper()}",
                        rule_id=rule['id'], customer_id=cu['id'], alert_date=self.ts(when), alert_description=desc,
                        triggered_transactions=json.dumps([t['id'] for t in txs]), alert_severity=rule['severity'],
                        assigned_to=assignee if status != 'NEW' else None, status=status, investigation_notes=note,
                        disposition=disp, disposition_by=(assignee if disp else None),
                        disposition_date=str(ddate.date()) if ddate else None)
            for t in txs:
                c.q("""UPDATE transactions SET alert_raised = 1, rule_triggered = %s, alert_id = %s,
                       alert_status = %s, investigated_by = %s, investigation_date = %s WHERE id = %s""",
                    (code, str(aid), 'CLOSED' if status in ('CLOSED', 'FALSE_POSITIVE') else 'OPEN',
                     assignee if status != 'NEW' else None, str(ddate.date()) if ddate else None, t['id']))
            self.alerts.append(dict(id=aid, code=code, cust=cu, when=when, status=status, txs=txs))
        self.commit()
        # the live engine on the last two days (alerts dated now, status NEW)
        from aml.tm_service import evaluate_transaction
        from database.db import get_db
        db = get_db()
        live = []
        for t in self.live:
            live += evaluate_transaction(t['id'], db)
        db.commit()
        print(f'      {len(raw)} historical alerts, live engine raised {len(live)}: '
              f'{sorted({a["rule"] for a in live})}')
        # cases for every alert (the engine syncs its own)
        from models.case import Case
        for a in self.alerts:
            Case.sync_from_source('TM_ALERT', a['id'])
        db.commit()
        # SLA clock: cases closed when the alert was dispositioned
        c.q("""UPDATE cases k SET resolved_at = (a.disposition_date || ' 16:00')::timestamp
               FROM tm_alerts a WHERE k.source_table = 'tm_alerts' AND k.source_record_id = a.id
               AND k.status IN ('CLOSED', 'RESOLVED') AND a.disposition_date IS NOT NULL""")
        self.commit()

    # ------------------------------------------------------------ SARs / STRs
    def sars(self):
        c, r = self.c, self.r
        k = self.by_key
        aml, co, mlro = c.uid('aml'), c.uid('co'), c.uid('mlro')

        def alerts_of(key, codes=None):
            return [a for a in self.alerts if a['cust'] is k[key] and (not codes or a['code'] in codes)]

        def txs_of(key, tags):
            return [t for t in self.tx if t['cust'] is k[key] and t['tag'] in tags]

        cases = [
            # key, tags, alert codes, status, decision, days(discovery), description, red flags
            ('saber', ('struct1', 'struct2'), ('TM002',), 'CLOSED', 'FILE_SAR', 125,
             'Repeated cash deposits just below the EGP 10,000 reporting threshold over two short periods, used to '
             'prepay a micro-loan; customer could not document the source of cash.',
             'Structuring below threshold; cash inconsistent with declared business turnover; early settlement'),
            ('sky', ('sanctions',), ('TM005',), 'CLOSED', 'FILE_SAR', 83,
             'Outgoing payment request in favour of Mahan Air (OFAC SDN). Payment blocked; true sanctions match '
             'confirmed by the MLRO.',
             'Sanctioned counterparty; high-risk jurisdiction (Iran)'),
            ('delta', ('roundtrip',), ('TM007',), 'FILE_SAR', 'FILE_SAR', 56,
             'EGP 420,000 overpayment received from an unrelated overseas company followed the same day by a request '
             'to refund EGP 405,000 to a third-party account in another jurisdiction.',
             'Rapid in/out; third-party funds; refund to unrelated account; layering through loan account'),
            ('walid', ('dormant',), ('TM006',), 'UNDER_INVESTIGATION', None, 36,
             'Account inactive for four months then settled in full with EGP 74,500 in cash; customer claims '
             'proceeds of a land sale, documents requested.',
             'Dormant account reactivation; large cash settlement'),
            ('third', ('third',), ('TM008',), 'NEW', None, 5,
             'Instalments paid by six different unrelated third parties within three weeks.',
             'Third-party payments; volume above profile'),
            ('sudan', ('hrc',), ('TM004',), 'CLOSED', 'NO_SAR', 170,
             'Regular remittances from Sudan funding instalments. Remitters identified as close family; amounts '
             'consistent with declared family support.',
             'High-risk jurisdiction'),
        ]
        sa_ids = {}
        for key, tags, codes, status, decision, disc_days, desc, flags in cases:
            txs = txs_of(key, tags)
            disc = self.dt(disc_days, 10)
            amount = sum(t['amount'] for t in txs)
            act = min(t['when'] for t in txs) if txs else disc
            filed = decision == 'FILE_SAR' and status == 'CLOSED'
            sid = c.ins('suspicious_activities',
                        sar_reference=f"SAR-{disc.strftime('%Y%m')}-{r.randrange(16 ** 4):04X}",
                        activity_date=str(act.date()), discovery_date=str(disc.date()), customer_id=k[key]['id'],
                        customer_name=k[key]['en'], activity_description=desc, amount_involved=round(amount, 2),
                        currency='EGP', transaction_ids=json.dumps([t['id'] for t in txs]),
                        red_flags_identified=flags, reported_by=aml if key != 'sky' else co,
                        report_date=str(disc.date()), assigned_to=mlro,
                        assignment_date=str((disc + timedelta(days=1)).date()), investigation_status=status,
                        investigation_notes=('Customer file, KYC documents and full transaction history reviewed. '
                                             'Branch interview conducted.' if status != 'NEW' else None),
                        investigation_findings=(desc if status in ('CLOSED', 'FILE_SAR') else None),
                        decision=decision, decision_by=mlro if decision else None,
                        decision_date=str((disc + timedelta(days=6)).date()) if decision else None,
                        decision_rationale=('Grounds for suspicion established; STR to the EMLCU.' if decision == 'FILE_SAR'
                                            else 'Activity explained and documented; no grounds for suspicion.'
                                            if decision == 'NO_SAR' else None),
                        sar_filed=1 if filed else 0,
                        sar_filing_date=str((disc + timedelta(days=8)).date()) if filed else None,
                        sar_deadline=str((disc + timedelta(days=15)).date()),
                        sar_days_remaining=max(0, (disc + timedelta(days=15) - self.now).days)
                        if status not in ('CLOSED',) else 0,
                        emlcu_reference=f'DEMO-EMLCU-{disc.year}-{r.randrange(1000, 9999)}' if filed else None,
                        emlcu_acknowledgment_date=str((disc + timedelta(days=10)).date()) if filed else None,
                        created_at=self.ts(disc), updated_at=self.ts(disc + timedelta(days=8)))
            sa_ids[key] = sid
            for a in alerts_of(key, codes):
                c.q("UPDATE tm_alerts SET sar_id = %s WHERE id = %s", (sid, a['id']))
                for t in a['txs']:
                    c.q("UPDATE transactions SET sar_id = %s, sar_filed = %s WHERE id = %s",
                        (sid, 1 if filed else 0, t['id']))
            if decision == 'FILE_SAR':
                c.ins('sar_reports', sar_reference=f'STR-{disc.year}-{len(sa_ids):03d}', customer_id=k[key]['id'],
                      detection_date=str(disc.date()), detected_by=aml, detection_method='Transaction monitoring',
                      activity_description=desc, red_flags=flags, transaction_ids=json.dumps([t['id'] for t in txs]),
                      total_amount=round(amount, 2), currency='EGP', activity_period_start=str(act.date()),
                      activity_period_end=str(max(t['when'] for t in txs).date()) if txs else None,
                      assigned_to=mlro, investigation_notes='See case file.', investigation_completed=1,
                      investigation_completed_date=str((disc + timedelta(days=5)).date()), decision='FILE',
                      decision_by=mlro, decision_date=str((disc + timedelta(days=6)).date()),
                      decision_rationale='Reasonable grounds to suspect; reported to the EMLCU.',
                      filed_to_emlcu=1 if filed else 0,
                      emlcu_filing_date=str((disc + timedelta(days=8)).date()) if filed else None,
                      emlcu_reference_number=f'DEMO-EMLCU-{disc.year}-{r.randrange(1000, 9999)}' if filed else None,
                      case_closed=1 if filed else 0, case_closed_date=str((disc + timedelta(days=12)).date())
                      if filed else None, access_restricted=1, created_at=self.ts(disc), created_by=aml)
        self.sa_ids = sa_ids
        self.commit()
        # unusual-transactions register (AML assurance) - one candidate per study
        from aml.unusual import register_candidate
        from models.case import Case
        from database.db import get_db
        db = get_db()
        plan = [  # key, alert code, status, decision, days, analysis
            ('saber', 'TM002', 'str_filed', 'str', 125,
             'Two bursts of sub-threshold cash deposits used to prepay the loan; no documented source. STR filed.'),
            ('sky', 'TM005', 'str_filed', 'str', 83, 'Payment to a sanctioned airline blocked; STR filed.'),
            ('sudan', 'TM004', 'no_str', 'no_str', 170,
             'Remitters are the customer\'s brothers (documents on file); amounts match declared support.'),
            ('velo', 'TM003', 'no_str', 'no_str', 158,
             'Split wallet payments due to the wallet\'s per-transaction limit; no suspicion.'),
            ('delta', 'TM007', 'under_study', None, 56,
             'Overpayment from an unrelated overseas company refunded to a third party. Draft conclusion: STR.'),
            ('walid', 'TM006', 'under_study', None, 36, 'Awaiting land-sale contract and bank statement.'),
            ('third', 'TM008', 'candidate', None, 5, None),
            ('syria', 'TM004', 'candidate', None, 30, None)]
        sla = 15
        for key, code, status, decision, days, analysis in plan:
            al = alerts_of(key, (code,))
            if not al:
                continue
            a = al[-1]
            amount = sum(t['amount'] for t in a['txs'])
            uid, _ = register_candidate(
                source_module='aml', detection_rule=code, description=f"{k[key]['en']}: "
                + c.one("SELECT alert_description FROM tm_alerts WHERE id = %s", (a['id'],))['alert_description'],
                source_table='tm_alerts', source_record_id=a['id'], party_id=k[key].get('party_id'),
                subject_name=k[key]['en'], subject_ref=k[key]['ref'], amount=round(amount, 2),
                org_unit_id=c.units[k[key]['branch']], created_by=aml, study_sla_days=sla, db=db)
            det = self.dt(days, 9)
            db.execute("""UPDATE aml_unusual_transactions SET detected_at = %s, study_due_date = %s, status = %s,
                          analysis = %s, decision = %s, decision_by = %s, decision_at = %s, str_reference = %s
                          WHERE id = %s""",
                       (det, (det + timedelta(days=sla)).date(), status, analysis, decision,
                        mlro if decision else None, det + timedelta(days=7) if decision else None,
                        f'STR-{det.year}-{list(self.sa_ids).index(key) + 1:03d}' if decision == 'str' else None, uid))
            db.execute("DELETE FROM cases WHERE source_table = 'aml_unusual_transactions' AND source_record_id = %s",
                       (uid,))
            db.commit()
            Case.sync_from_source('UNUSUAL_TXN', uid)
        db.commit()

    # ------------------------------------------------------------ internal lists
    def lists(self):
        c = self.c
        from screening.internal_pep_service import InternalPEPService
        svc = InternalPEPService()
        for i, (en, ar, pos, cat, reason) in enumerate(INTERNAL_PEPS):
            eid = svc.add_entry({'full_name': en, 'original_name': ar, 'entity_type': 'INDIVIDUAL',
                                 'nationality': 'Egypt', 'country': 'Egypt', 'position': pos, 'category': cat,
                                 'reason': reason, 'risk_level': 'HIGH',
                                 'notes': 'Added from public sources / customer declaration (fictional demo data).'},
                                c.uid('co'))
            d = self.dt(420 - i * 40)
            c.q("UPDATE internal_pep SET added_date = %s, created_at = %s, updated_at = %s WHERE id = %s",
                (self.ts(d), self.ts(d), self.ts(d), eid))
        self.commit()

    def blacklist(self, rows, before_delta):
        c = self.c
        from screening.internal_blacklist_service import InternalBlacklistService
        svc = InternalBlacklistService()
        for en, ar, et, cat, risk, reason, days in rows:
            data = {'full_name': en, 'original_name': ar, 'entity_type': et, 'nationality': 'Egypt', 'country': 'Egypt',
                    'city': 'Cairo', 'reason': reason, 'risk_level': risk, 'category': cat,
                    'notes': 'Internal list - fictional demo record.'}
            if en == self.by_key['saber']['en']:
                data['national_id'] = c.one("SELECT id_number FROM customers WHERE id = %s",
                                            (self.by_key['saber']['id'],))['id_number']
            eid = svc.add_entry(data, c.uid('mlro' if risk == 'CRITICAL' else 'co'))
            d = self.dt(days)
            c.q("""UPDATE internal_blacklist SET added_date = %s, created_at = %s, updated_at = %s,
                   confirmation_type = 'CONFIRMED' WHERE id = %s""", (self.ts(d), self.ts(d), self.ts(d), eid))
            c.q("UPDATE internal_blacklist_audit SET changed_at = %s WHERE blacklist_id = %s", (d, eid))
        self.commit()

    # ------------------------------------------------------------ screening
    def _backdate_hist(self, hid, rid, when, qstatus=None):
        c = self.c
        c.q("UPDATE screening_history SET created_at = %s, screening_date = %s WHERE id = %s",
            (when, self.ts(when), hid))
        if rid:
            c.q("UPDATE screening_results SET created_at = %s WHERE id = %s", (self.ts(when), rid))
            c.q("UPDATE aml_alerts SET created_at = %s, updated_at = %s WHERE screening_result_id = %s",
                (self.ts(when), self.ts(when), rid))
        c.q("UPDATE screening_queue SET created_at = %s WHERE screening_history_id = %s", (when, hid))

    def _resolve(self, hid, rid, resolution, who, when, notes, customer_id=None):
        """Mirror the queue-review decision (screening/routes.py queue_review)."""
        c = self.c
        c.q("""UPDATE screening_queue SET status = 'Resolved', resolution = %s, resolution_notes = %s,
               resolved_by = %s, resolved_date = %s, assigned_to = %s WHERE screening_history_id = %s""",
            (resolution, notes, who, self.ts(when), who, hid))
        c.q("""UPDATE screening_history SET status = 'Completed', resolution_date = %s, resolved_by = %s, notes = %s
               WHERE id = %s""", (self.ts(when), who, notes, hid))
        if rid:
            st = {'False Positive': 'FALSE_POSITIVE', 'True Match - Block': 'TRUE_HIT', 'PEP - Flag': 'TRUE_HIT'}
            c.q("""UPDATE screening_results SET status = %s, resolution_notes = %s, resolved_by = %s, resolved_at = %s,
                   reviewed_by = %s, reviewed_at = %s, false_positive = %s WHERE id = %s""",
                (st[resolution], notes, who, self.ts(when), who, self.ts(when),
                 1 if resolution == 'False Positive' else 0, rid))
            c.q("""UPDATE aml_alerts SET alert_status = 'CLOSED', false_positive = %s, resolved_by = %s,
                   resolved_at = %s, resolution_notes = %s, assigned_to = %s, customer_id = COALESCE(%s, customer_id),
                   updated_at = %s WHERE screening_result_id = %s""",
                (1 if resolution == 'False Positive' else 0, who, self.ts(when),
                 f'Auto-closed via queue resolution ({resolution}): {notes}', who, customer_id, self.ts(when), rid))

    def screening(self):
        c, r = self.c, self.r
        from screening.customer_screening_service import screen_and_save
        from screening.routes import get_engine, _save_screening_result
        from services import ongoing_screening as OS
        from database.db import get_db
        db = get_db()
        aml, co, mlro = c.uid('aml'), c.uid('co'), c.uid('mlro')
        self.commit()
        k = self.by_key
        # who goes through the engine at onboarding: all special + corporates + a sample
        must = [cu for cu in self.cust if cu['key'] or cu in [x for x in self.cust if x['kind'] == 'CORPORATE'][:6]]
        rest = [cu for cu in self.cust if cu not in must]
        r.shuffle(rest)
        chosen = must + rest[:max(0, N_SCREEN - len(must))]
        self.whitelist_todo = []
        for cu in chosen:
            res = screen_and_save(name=cu['en'], entity_type='ENTITY' if cu['kind'] == 'CORPORATE' else 'INDIVIDUAL',
                                  dob=None, nationality=cu['nat'], source_module='Customer KYC',
                                  source_record_id=cu['id'], screening_type='Customer Onboarding',
                                  user_id=aml, results_screening_type='CUSTOMER')
            when = cu['onb'] + timedelta(minutes=20)
            hid, rid = res['history_id'], res['results_id']
            self._backdate_hist(hid, rid, when)
            c.q("UPDATE aml_alerts SET customer_id = %s WHERE screening_result_id = %s", (cu['id'], rid))
            self.hist[cu['id']] = hid
            hi = res['high_risk_matches']
            status = 'Clear'
            if hi:
                rw = when + timedelta(days=r.randrange(1, 3), hours=2)
                if cu['key'] in ('pep1', 'pep2'):
                    self._resolve(hid, rid, 'PEP - Flag', co, rw, 'Customer confirmed as PEP (internal PEP list). '
                                  'EDD and senior management approval required.', cu['id'])
                    db.execute("""INSERT INTO pep_database (full_name, risk_level, source_list, is_active, created_at,
                                  position, country, pep_category, nationality)
                                  VALUES (%s,'HIGH','INTERNAL_PEP',1,%s,%s,'Egypt',%s,'Egypt')""",
                               (cu['en'], self.ts(rw), c.one("SELECT pep_position FROM customers WHERE id=%s",
                                                             (cu['id'],))['pep_position'],
                                c.one("SELECT pep_category FROM customers WHERE id=%s", (cu['id'],))['pep_category']))
                    status = 'PEP'
                elif cu['key'] == 'saber':
                    status = 'Clear'   # nothing at onboarding
                else:
                    notes = ('Different person: date of birth, nationality and national ID do not match the listed '
                             'individual; no adverse information.')
                    self._resolve(hid, rid, 'False Positive', aml, rw, notes, cu['id'])
                    self.whitelist_todo.append((cu, res['matches'], notes, rw))
                    status = 'Clear'
            c.q("UPDATE customers SET screening_status = %s, last_screening_date = %s, last_screened_by = %s, "
                "screening_notes = %s WHERE id = %s",
                (status, self.ts(when), aml, None if status == 'Clear' else 'Confirmed PEP - EDD applied', cu['id']))
        db.commit()
        self.commit()
        # everyone else: screened clear at onboarding (no history kept for these demo rows)
        for cu in self.cust:
            if cu['id'] not in self.hist:
                c.q("UPDATE customers SET screening_status = 'Clear', last_screening_date = %s, last_screened_by = %s "
                    "WHERE id = %s", (self.ts(cu['onb'] + timedelta(minutes=15)), aml, cu['id']))
        # merchants
        for m in self.merch:
            if m['status'] == 'PENDING':
                continue
            res = screen_and_save(name=m['name'], entity_type='ENTITY', source_module='Merchant KYC',
                                  source_record_id=m['id'], screening_type='Merchant KYC', user_id=aml,
                                  results_screening_type='MERCHANT_KYC')
            when = m['created'] + timedelta(hours=3)
            self._backdate_hist(res['history_id'], res['results_id'], when)
            if res['high_risk_matches']:
                self._resolve(res['history_id'], res['results_id'], 'False Positive', aml, when + timedelta(days=1),
                              'Trade name coincides with a listed entity; different country and registration.')
                c.q("UPDATE merchants SET screening_status = 'Clear', risk_rating = 'Medium' WHERE id = %s", (m['id'],))
            c.q("UPDATE merchants SET last_screening_date = %s, sanctions_checked = 1 WHERE id = %s",
                (self.ts(when), m['id']))
            if m['status'] == 'REJECTED':
                c.q("UPDATE merchants SET screening_status = 'Blocked', risk_rating = 'High', screening_notes = %s "
                    "WHERE id = %s", ('UBO matches the internal blacklist (loan fraud) - onboarding declined.', m['id']))
        db.commit()
        # ad-hoc screening of counterparties: real international sanctions targets
        engine = get_engine()
        self.confirmed = []
        days = {'Mahan Air': 84, 'Korea Kwangson Banking Corporation': 213, 'Viktor Bout': 290, 'Rami Makhlouf': 17}
        for name, et, context, outcome in SANCTIONED:
            res = engine.screen_person(name=name, entity_type=et)
            hid = _save_screening_result(name=name, entity_type=et, dob=None, nationality=None,
                                         source_module='Manual Ad-Hoc', source_record_id=None, result=res,
                                         user_id=aml, screening_type='MANUAL',
                                         inputs={'context': context, 'threshold': 70})
            row = c.one("SELECT screening_result_id FROM screening_history WHERE id = %s", (hid,))
            rid = row['screening_result_id'] if row else None
            when = self.dt(days[name], 11)
            self._backdate_hist(hid, rid, when)
            ms = res.get('matches') or []
            top = max(ms, key=lambda m: m.get('match_score') or 0) if ms else None
            if not top:
                continue
            rw = when + timedelta(hours=3)
            if outcome == 'open':
                # pending second-level review: leave the queue open, assigned to the MLRO
                c.q("UPDATE screening_queue SET status = 'In Review', assigned_to = %s WHERE screening_history_id = %s "
                    "AND match_score >= 90", (mlro, hid))
                c.q("UPDATE screening_queue SET status = 'Resolved', resolution = 'False Positive', resolved_by = %s, "
                    "resolved_date = %s, resolution_notes = 'Weak partial-name match, different person.' "
                    "WHERE screening_history_id = %s AND match_score < 90", (aml, self.ts(rw), hid))
                c.q("UPDATE aml_alerts SET assigned_to = %s, notes = %s WHERE screening_result_id = %s",
                    (mlro, context, rid))
            else:
                notes = f'True match confirmed: {context}. Transaction blocked.'
                self._resolve(hid, rid, 'True Match - Block', mlro, rw, notes)
                db.execute("""INSERT INTO internal_blacklist (full_name, entity_type, reason, risk_level, category,
                              source, added_by, added_date, is_active, confirmation_type, created_at)
                              VALUES (%s,%s,%s,'HIGH','Sanctions Match',%s,%s,%s,1,'TEAM_CONFIRMED',%s)""",
                           (name, et, f"True sanctions match ({top.get('source')}, score: {top.get('match_score')}%): "
                                      f"{notes}", top.get('source'), mlro, self.ts(rw), self.ts(rw)))
            strref = f'STR-{rw.year}-0{len(self.confirmed) + 7:02d}' if outcome == 'reported' else None
            c.ins('confirmed_matches', entity_name=name, normalized_name=name.upper(), entity_type=et,
                  matched_entity_id=int(top['id']) if str(top.get('id') or '').isdigit() else None,
                  matched_name=top.get('full_name'), list_source=top.get('source'),
                  list_type='pep' if 'pep' in str(top.get('source')) else 'sanctions',
                  match_score=top.get('match_score'), screening_history_id=hid,
                  queue_id=(c.one("SELECT id FROM screening_queue WHERE screening_history_id = %s ORDER BY match_score "
                                  "DESC LIMIT 1", (hid,)) or {}).get('id'),
                  source_module='Manual Ad-Hoc', confirmed_by=mlro, confirmed_at=rw,
                  confirmation_reason=context,
                  action_taken={'reported': 'Transaction blocked; STR filed', 'closed': 'Instruction rejected',
                                'open': None}[outcome],
                  str_reference=strref, str_filed_at=rw + timedelta(days=2) if strref else None,
                  str_filed_by=mlro if strref else None, reported_to_emlcu=bool(strref),
                  status={'reported': 'reported', 'closed': 'closed', 'open': 'open'}[outcome],
                  closed_at=rw + timedelta(days=3) if outcome == 'closed' else None,
                  closed_by=mlro if outcome == 'closed' else None,
                  closure_reason='Instruction rejected and the remitting bank informed.' if outcome == 'closed' else None,
                  notes=context, created_at=rw)
            self.confirmed.append(name)
        # a few routine ad-hoc checks (prospects, guarantors) - clear
        for i in range(6):
            g = r.choice(MALE)
            nm = f'{g[0]} {r.choice(MALE)[0]} {r.choice(FAMILY)[0]}'
            res = engine.screen_person(name=nm, entity_type='INDIVIDUAL')
            hid = _save_screening_result(name=nm, entity_type='INDIVIDUAL', dob=None, nationality='Egypt',
                                         source_module='Manual Ad-Hoc', source_record_id=None, result=res,
                                         user_id=r.choice([aml, co]), screening_type='MANUAL',
                                         inputs={'context': 'Loan guarantor check'})
            row = c.one("SELECT screening_result_id FROM screening_history WHERE id = %s", (hid,))
            when = self.dt(r.randrange(2, 300), 12)
            self._backdate_hist(hid, row['screening_result_id'] if row else None, when)
            if res.get('matches') and r.random() < 0.7:
                self._resolve(hid, row['screening_result_id'], 'False Positive', aml, when + timedelta(hours=5),
                              'Guarantor is a different person (DOB and ID mismatch).')
        db.commit()
        self.commit()

    # ------------------------------------------------------------ KYC (aml assurance)
    def kyc(self):
        c, r = self.c, self.r
        from amlkyc import service
        from database.db import get_db
        db = get_db()
        self.commit()
        # the company's calibrated risk model (risk-model page)
        model = {
            'customer_type': (1, {'*': 30, 'CORPORATE': 50, 'INDIVIDUAL': 20}),
            'residence': (1, {'*': 60, 'Egypt': 10}),
            'product': (1, {'*': 30, 'micro_loan': 20, 'group_loan': 15, 'consumer_finance': 20, 'sme_loan': 45}),
            'channel': (1, {'*': 40, 'agent': 60, 'branch': 20, 'digital': 50}),
            'pep': (4, {'*': 0, '1': 100, 'True': 100, 'true': 100}),
            'behaviour': (2, {'*': 80, '0': 0, '1': 40}),
        }
        for key, (w, sc) in model.items():
            c.q("UPDATE kyc_risk_factors SET weight = %s, scoring = %s WHERE factor_key = %s", (w, json.dumps(sc), key))
        c.ins('kyc_risk_factors', factor_key='nationality', category='geography', label_en='Nationality',
              label_ar='الجنسية', field_key='nationality', weight=2,
              scoring=json.dumps({'*': 50, 'Egypt': 10, 'Sudan': 90, 'Syria': 90, 'Yemen': 90, 'Iran': 100}),
              is_active=True)
        c.q("UPDATE kyc_risk_bands SET min_score = 18 WHERE band = 'medium'")
        c.q("UPDATE kyc_risk_bands SET min_score = 40 WHERE band = 'high'")
        self.commit()
        issuers = ['Cairo Investors Tax Office', 'Giza Tax Office', 'Assiut Tax Office', 'Large Taxpayers Center']
        co, aml, mlro, ceo = c.uid('co'), c.uid('aml'), c.uid('mlro'), c.uid('ceo')
        overrides = {'saber': 'Subject of an STR (structuring); relationship under exit review.',
                     'delta': 'Subject of an STR (rapid in/out through the loan account).',
                     'sky': 'Attempted payment to a sanctioned counterparty; STR filed.',
                     'walid': 'Large unexplained cash settlement under investigation.'}
        incomplete = set(cu['id'] for cu in r.sample([x for x in self.cust if x['key'] is None], 12))
        counts = {}
        for cu in self.cust:
            corp = cu['kind'] == 'CORPORATE'
            prof = {'product': cu['product'], 'channel': cu['channel']}
            if corp:
                prof.update(tax_card_number=f'DEMO-{r.randrange(100, 999)}-{r.randrange(100, 999)}-{r.randrange(100, 999)}',
                            tax_card_issuer=r.choice(issuers),
                            senior_management=f'{r.choice(MALE)[0]} {r.choice(FAMILY)[0]} (Managing Director)')
            else:
                prof['gender'] = 'Male' if cu['gender'] == 'M' else 'Female'
            if cu['id'] in incomplete or cu['status'] == 'PENDING':
                prof.pop('gender', None)
                prof.pop('tax_card_issuer', None)
            for fk, v in prof.items():
                c.ins('kyc_profile_values', subject='aml_customer', subject_id=cu['id'], field_key=fk, value=v,
                      updated_by=co, updated_at=cu['onb'])
            if corp:
                n_bo = r.choice([1, 2, 2, 3])
                left = 100
                for j in range(n_bo):
                    pct = left if j == n_bo - 1 else r.choice([50, 40, 30, 25])
                    left -= pct
                    bo = f'{r.choice(MALE)[0]} {r.choice(MALE)[0]} {r.choice(FAMILY)[0]}'
                    is_pep = cu['key'] == 'nilestar' and j == 0
                    if is_pep:
                        bo = 'Samir Lotfy Habib'
                    bo_nid = self.nid()
                    kbo = dict(subject='aml_customer', subject_id=cu['id'], full_name=bo,
                               nationality='Egypt', ownership_pct=pct, control_type='ownership', is_pep=is_pep,
                               created_by=co, created_at=cu['onb'])
                    if 'id_number' in c.cols('kyc_beneficial_owners'):
                        kbo.update(id_type='NATIONAL_ID', id_number=bo_nid)
                    c.ins('kyc_beneficial_owners', **kbo)
                    c.ins('beneficial_owners', customer_id=cu['id'], owner_type='INDIVIDUAL', full_name=bo,
                          nationality='Egypt', id_type='NATIONAL_ID', id_number=bo_nid, ownership_percentage=pct,
                          ownership_type='Direct shareholding', is_pep=1 if is_pep else 0,
                          pep_category='Domestic PEP' if is_pep else None,
                          pep_position='Chairman of a state-owned company (demo)' if is_pep else None,
                          verified=1, verified_by=co, verification_date=str(cu['onb'].date()),
                          verification_notes='Verified against the commercial register extract and IDs.',
                          created_at=self.ts(cu['onb']), created_by=co)
                if self.has_table('kyb_signatories'):
                    c.ins('kyb_signatories', subject='aml_customer', subject_id=cu['id'], full_name=bo,
                          position='Managing Director', signing_authority='sole', nationality='Egypt',
                          id_type='NATIONAL_ID', id_number=self.nid(), created_by=co, created_at=cu['onb'])
                if 'tax_card_number' in c.cols('customers'):
                    c.q("UPDATE customers SET tax_card_number = %s, legal_form = %s WHERE id = %s",
                        (f'DEMO-{r.randrange(100, 999)}-{r.randrange(100, 999)}-{r.randrange(100, 999)}',
                         r.choice(['LLC', 'JOINT_STOCK']), cu['id']))
                if cu['id'] not in incomplete:
                    c.ins('kyc_bo_declarations', subject='aml_customer', subject_id=cu['id'], declaration_type='other',
                          bo_name=bo, signed_on=cu['onb'].date(), recorded_by=co, recorded_at=cu['onb'])
        self.commit()
        # ratings through the model
        for cu in self.cust:
            if cu['status'] == 'PENDING':
                continue
            score, band, nr = service.rate_subject('aml_customer', cu['id'], co,
                                                   trigger='onboarding', db=db)
            al = [a for a in self.alerts if a['cust'] is cu]
            when = max([cu['onb'] + timedelta(hours=1)] + [a['when'] + timedelta(days=3) for a in al])
            when = min(when, self.now - timedelta(hours=1))
            if cu['key'] in overrides:
                band = 'high'
            months = {'low': 36, 'medium': 24, 'high': 12}[band]
            nrd = (when + timedelta(days=int(months * 30.4))).date()
            if band == 'high' and cu['key'] in ('pep1', 'walid'):
                nrd = (self.now - timedelta(days=r.randrange(5, 25))).date()   # overdue review
            db.execute("""UPDATE kyc_risk_ratings SET rated_at = %s, trigger = %s, band = %s, next_review_date = %s,
                          rated_by = %s WHERE subject = 'aml_customer' AND subject_id = %s AND is_current""",
                       (when, 'manual' if cu['key'] in overrides else 'alert' if al else 'onboarding', band, nrd,
                        mlro if cu['key'] in overrides else aml if al else co, cu['id']))
            if al:
                db.execute("""INSERT INTO kyc_risk_ratings (subject, subject_id, score, band, factors, trigger,
                              rated_at, rated_by, next_review_date, is_current)
                              VALUES ('aml_customer', %s, %s, 'low', '[]', 'onboarding', %s, %s, %s, FALSE)""",
                           (cu['id'], round(max(5.0, float(score) - 12), 2), cu['onb'] + timedelta(hours=1), co,
                            (cu['onb'] + timedelta(days=1095)).date()))
            cls = band.upper()
            counts[cls] = counts.get(cls, 0) + 1
            cu['band'] = band
            last_rev = when.date()
            c.q("""UPDATE customers SET risk_classification = %s, risk_score = %s, risk_classification_date = %s,
                   risk_classification_reason = %s, risk_classified_by = %s, risk_override_reason = %s,
                   requires_edd = %s, edd_completed = %s, edd_approved_by = %s, edd_approval_date = %s,
                   last_review_date = %s, next_review_date = %s WHERE id = %s""",
                (cls, int(float(score)), str(when.date()),
                 'Risk model v2 (customer type, geography, product, channel, PEP, behaviour)',
                 aml if al else co, overrides.get(cu['key']), 1 if cls == 'HIGH' else 0,
                 1 if cls == 'HIGH' and cu['key'] not in ('walid',) else 0,
                 ceo if cls == 'HIGH' else None, str((when + timedelta(days=5)).date()) if cls == 'HIGH' else None,
                 str(last_rev), str(nrd), cu['id']))
            # onboarding gate
            hi = band == 'high'
            edd_done = hi and cu['key'] != 'walid'
            checklist = [{'item': it, 'done': edd_done or (not hi)} for it in service.EDD_ITEMS] if hi else []
            c.ins('kyc_onboarding', subject='aml_customer', subject_id=cu['id'],
                  status='approved' if cu['id'] not in incomplete else 'pending',
                  edd_checklist=json.dumps(checklist), edd_completed=edd_done,
                  senior_approved_by=ceo if edd_done else None,
                  senior_approved_at=cu['onb'] + timedelta(days=4) if edd_done else None,
                  approved_by=co if cu['id'] not in incomplete else None,
                  approved_at=cu['onb'] + timedelta(days=1) if cu['id'] not in incomplete else None,
                  note=('EDD completed: source of funds and wealth verified; CEO approval obtained.' if edd_done
                        else 'Awaiting missing KYC data from the branch.' if cu['id'] in incomplete else None))
            # legacy CDD/EDD registers
            if (self.now - cu['onb']).days > 200 and r.random() < 0.45 or hi:
                rd = cu['onb'] + timedelta(days=min(365, (self.now - cu['onb']).days - 3))
                c.ins('cdd_reviews', customer_id=cu['id'], review_date=str(rd.date()),
                      review_type='Trigger review' if al else 'Periodic review', reviewed_by=aml,
                      review_notes=('Profile refreshed; transactions consistent with stated activity.' if not al else
                                    'Reviewed following TM alerts; risk rating updated.'),
                      documents_reviewed='National ID, proof of address, business licence / salary certificate',
                      risk_classification_changed=1 if al and band != 'low' else 0,
                      previous_risk_classification='LOW', new_risk_classification=cls,
                      reclassification_reason='Alert history' if al and band != 'low' else None,
                      actions_required='Obtain updated proof of address' if r.random() < 0.3 else None,
                      actions_completed=1, actions_completed_date=str((rd + timedelta(days=10)).date()),
                      next_review_date=str(nrd), created_at=self.ts(rd))
            if hi:
                trig = {'pep1': 'PEP', 'pep2': 'PEP'}.get(cu['key'], 'High-risk activity')
                c.ins('edd_cases', case_reference=f"EDD-{cu['onb'].year}-{cu['id']:04d}", customer_id=cu['id'],
                      edd_trigger=trig, trigger_description=overrides.get(cu['key']) or 'Politically exposed person',
                      trigger_date=str(when.date()), assigned_to=aml, priority='HIGH',
                      status='COMPLETED' if edd_done else 'IN_PROGRESS',
                      investigation_notes='Source of funds / wealth documents collected and verified.',
                      additional_documents_required='Bank statements (6 months), proof of source of wealth',
                      additional_documents_received=1 if edd_done else 0,
                      compliance_reviewed=1 if edd_done else 0, compliance_reviewed_by=mlro if edd_done else None,
                      compliance_review_date=str((when + timedelta(days=3)).date()) if edd_done else None,
                      senior_management_approval=1 if edd_done else 0, approved_by=ceo if edd_done else None,
                      approval_date=str((when + timedelta(days=5)).date()) if edd_done else None,
                      completion_date=str((when + timedelta(days=5)).date()) if edd_done else None,
                      outcome='Continue with enhanced monitoring' if edd_done else None,
                      relationship_continued=1, monitoring_enhanced=1, enhanced_monitoring_frequency='Monthly',
                      created_at=self.ts(when), created_by=aml, updated_at=self.ts(when + timedelta(days=5)))
        db.commit()
        self.commit()
        # merchants: KYB files
        for m in self.merch:
            for fk, v in {'tax_card_issuer': r.choice(issuers),
                          'senior_management': f"{m['ubo']} (Owner / Manager)"}.items():
                if m['status'] in ('SENT', 'PENDING') and fk == 'tax_card_issuer':
                    continue
                c.ins('kyc_profile_values', subject='merchant', subject_id=m['id'], field_key=fk, value=v,
                      updated_by=c.uid('aml'), updated_at=m['created'])
            bo = dict(subject='merchant', subject_id=m['id'], full_name=m['ubo'],
                      nationality='Egypt', ownership_pct=100, control_type='ownership', is_pep=False,
                      created_by=c.uid('aml'), created_at=m['created'])
            if 'id_number' in c.cols('kyc_beneficial_owners'):
                bo.update(id_type='NATIONAL_ID', id_number=m['ubo_id'], date_of_birth=m['ubo_dob'])
            c.ins('kyc_beneficial_owners', **bo)
            if self.has_table('kyb_signatories'):
                c.ins('kyb_signatories', subject='merchant', subject_id=m['id'], full_name=m['ubo'],
                      position='Owner / Manager', signing_authority='sole', nationality='Egypt',
                      id_type='NATIONAL_ID', id_number=m['ubo_id'], date_of_birth=m['ubo_dob'],
                      created_by=c.uid('aml'), created_at=m['created'])
            if m['status'] in ('APPROVED', 'SUBMITTED', 'REJECTED'):
                c.ins('kyc_bo_declarations', subject='merchant', subject_id=m['id'], declaration_type='self',
                      bo_name=None, signed_on=m['created'].date() + timedelta(days=2), recorded_by=c.uid('aml'),
                      recorded_at=m['created'] + timedelta(days=2))
        self.commit()
        for m in self.merch:
            if m['status'] == 'APPROVED':
                service.rate_subject('merchant', m['id'], c.uid('aml'), trigger='onboarding', db=db)
                db.execute("UPDATE kyc_risk_ratings SET rated_at = %s WHERE subject = 'merchant' AND subject_id = %s",
                           (m['created'] + timedelta(days=5), m['id']))
                db.execute("""INSERT INTO kyc_onboarding (subject, subject_id, status, approved_by, approved_at)
                              VALUES ('merchant', %s, 'approved', %s, %s)""",
                           (m['id'], c.uid('co'), m['created'] + timedelta(days=5)))
        db.commit()
        # regulatory floor and EDD records exactly as the application applies them
        try:
            from aml.edd import reassess
            for cu in self.cust:
                reassess(cu['id'], co, db=db)
        except Exception as e:
            db.rollback()
            print('    risk floor / EDD reassessment skipped:', e)
        print('      customer risk bands:', counts)

    # ------------------------------------------------------------ ongoing + delta
    def ongoing_and_delta(self):
        c, r = self.c, self.r
        from services import ongoing_screening as OS
        from screening.routes import get_engine
        from database.db import get_db
        db = get_db()
        self.commit()
        mlro, aml = c.uid('mlro'), c.uid('aml')
        cfg = {'default': 'quarterly', 'CRITICAL': 'weekly', 'HIGH': 'monthly', 'MODERATE': 'quarterly',
               'LOW': 'yearly'}
        for scope, freq in cfg.items():
            c.q("""UPDATE ongoing_screening_config SET frequency = %s, is_configured = TRUE, configured_by = %s,
                   configured_at = %s, rationale = %s, updated_by = %s, updated_at = %s WHERE scope_name = %s""",
                (freq, mlro, self.dt(300, 10),
                 'Cadence aligned with the customer risk model and the FRA risk-based approach; approved by the '
                 'Compliance Committee (minutes CC-2025-11).', mlro, self.dt(300, 10), scope))
        crit = [('CRITICAL', 'list_type', 'equals', 'sanctions', 5, 'Any match on a sanctions list'),
                ('CRITICAL', 'match_score', 'gte', '95', 4, 'Near-exact name match'),
                ('HIGH', 'is_pep', 'equals', '1', 3, 'Politically exposed persons'),
                ('HIGH', 'country', 'in', 'Iran,Syria,Sudan,Yemen,North Korea', 3, 'High-risk jurisdictions'),
                ('MODERATE', 'match_score', 'gte', '80', 2, 'Strong partial match'),
                ('LOW', 'match_score', 'lte', '79', 1, 'Weak match, cleared once')]
        for band, f, op, v, w, d in crit:
            c.ins('screening_risk_criteria', band=band, factor=f, operator=op, value=v, weight=w, description=d,
                  is_active=True, created_by=mlro, created_at=self.dt(298, 11))
        self.commit()
        # whitelist the false positives (match-set scope)
        engine = get_engine()
        wl_ids = []
        for cu, matches, notes, when in self.whitelist_todo:
            ms = [m for m in matches if (m.get('match_score') or 0) >= 70]
            band = 'MODERATE' if cu['kind'] == 'CORPORATE' else 'LOW'
            wid = OS.whitelist_from_false_positive(cu['en'], ms, f'Cleared at onboarding screening: {notes}', aml,
                                                   customer_id=cu['id'], risk_band=band)
            nxt = when + OS.FREQUENCIES[OS.frequency_for(band)]
            db.execute("""UPDATE screening_whitelist SET added_at = %s, last_screened_at = %s, next_screening_at = %s,
                          risk_band = %s, risk_band_by = %s, risk_band_at = %s, approved_by = %s, approval_date = %s,
                          entity_type = %s, date_of_birth = %s, nationality = %s WHERE id = %s""",
                       (self.ts(when), when, nxt, band, c.uid('co'), when, c.uid('co'), self.ts(when),
                        'Entity' if cu['kind'] == 'CORPORATE' else 'Individual',
                        c.one("SELECT date_of_birth FROM customers WHERE id=%s", (cu['id'],))['date_of_birth'],
                        cu['nat'], wid))
            db.execute("UPDATE screening_whitelist_matches SET cleared_at = %s WHERE whitelist_id = %s", (when, wid))
            wl_ids.append(wid)
        db.commit()
        # scheduled re-screening runs: one a month ago, one this week (finds the new listing for fp1)
        for days in (33, 3):
            if days == 3:
                # a cleared listing for fp1 has since been amended on its source list
                fp1 = self.by_key['fp1']
                db.execute("""UPDATE screening_whitelist_matches SET fingerprint = 'amended-since-clearance'
                              WHERE id = (SELECT m.id FROM screening_whitelist_matches m JOIN screening_whitelist w
                              ON w.id = m.whitelist_id WHERE w.customer_id = %s ORDER BY m.match_score DESC LIMIT 1)""",
                           (fp1['id'],))
                db.commit()
            run_id, stats = OS.run(engine=engine, run_type='scheduled', triggered_by=None, include_all=True)
            when = self.dt(days, 2)
            db.execute("UPDATE ongoing_screening_runs SET started_at = %s, finished_at = %s, notes = %s WHERE id = %s",
                       (when, when + timedelta(seconds=40), 'Nightly scheduled re-screen', run_id))
            db.execute("UPDATE ongoing_screening_findings SET created_at = %s WHERE run_id = %s", (when, run_id))
            if days == 33:
                # first run: nothing outside the cleared sets yet - accept anything found
                db.execute("""UPDATE ongoing_screening_findings SET status = 'accepted', reviewed_by = %s,
                              reviewed_at = %s WHERE run_id = %s""", (aml, when + timedelta(hours=8), run_id))
            print(f'      ongoing run {run_id}: {stats}')
        db.execute("UPDATE screening_whitelist SET last_screened_at = %s", (self.dt(3, 2),))
        db.commit()
        # ---- delta re-screening: starting point, then new internal-list names vs existing relationships
        self.blacklist([b for b in BLACKLIST], True)
        mx = c.one("""SELECT (SELECT COALESCE(max(id),0) FROM internal_blacklist) bl,
                             (SELECT COALESCE(max(id),0) FROM internal_pep) pep,
                             (SELECT COALESCE(max(id),0) FROM screening_watchlist) wl""")
        c.ins('screening_delta_runs', run_at=self.dt(60, 3), from_bl_id=mx['bl'], to_bl_id=mx['bl'],
              from_pep_id=mx['pep'], to_pep_id=mx['pep'], from_wl_id=mx['wl'], to_wl_id=mx['wl'],
              note='starting point')
        self.commit()
        saber = self.by_key['saber']
        self.blacklist([(saber['en'], saber['ar'], 'INDIVIDUAL', 'Fraud', 'HIGH',
                         'Structuring and forged salary certificates across several lenders; STR filed '
                         f"({self.sar_ref('saber')}). Relationship exited.", 6)], False)
        self.run_delta()
        c.q("UPDATE customers SET status = 'SUSPENDED', status_reason = %s, is_sanctioned = 0, "
            "screening_status = 'Blocked', screening_notes = %s WHERE id = %s",
            ('Exit in progress after STR; added to the internal blacklist.',
             'Matches internal blacklist entry (loan fraud) - delta re-screening', saber['id']))
        self.commit()

    def sar_ref(self, key):
        row = self.c.one("SELECT sar_reference FROM suspicious_activities WHERE id = %s", (self.sa_ids[key],))
        return row['sar_reference'] if row else 'STR on file'

    def run_delta(self):
        c = self.c
        import importlib.util
        import sys
        import utils.demo
        import screening.update_lock
        path = os.path.join(os.getcwd(), 'scripts', 'screening_delta_rescreen.py')
        spec = importlib.util.spec_from_file_location('_delta_rescreen', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        orig_skip, orig_wait = utils.demo.skip_in_demo, screening.update_lock.wait_until_free
        utils.demo.skip_in_demo = lambda *a, **k: False
        screening.update_lock.wait_until_free = lambda *a, **k: None
        argv = sys.argv
        sys.argv = ['screening_delta_rescreen.py']
        try:
            mod.main()
        finally:
            utils.demo.skip_in_demo, screening.update_lock.wait_until_free = orig_skip, orig_wait
            sys.argv = argv
        when = self.dt(6, 4)
        c.q("UPDATE screening_delta_runs SET run_at = %s WHERE id = (SELECT max(id) FROM screening_delta_runs)", (when,))
        c.q("UPDATE screening_delta_hits SET found_at = %s", (when,))
        # the customer hit was reviewed (true match -> exit); the merchant UBO / party hits stay open
        c.q("""UPDATE screening_delta_hits SET status = 'true_match', reviewed_by = %s, reviewed_at = %s,
               review_note = 'Same person (national ID matches). Relationship exit started.'
               WHERE subject_table = 'customers'""", (c.uid('mlro'), when + timedelta(hours=6)))
        self.commit()

    # ------------------------------------------------------------ AML assurance
    def assurance(self):
        c, r = self.c, self.r
        from amlkyc import service
        from database.db import get_db
        db = get_db()
        self.commit()
        mlro, co, aml, ceo = c.uid('mlro'), c.uid('co'), c.uid('aml'), c.uid('ceo')
        service.save_key_role({'role_code': 'mlro', 'title': 'Money Laundering Reporting Officer (MLRO)',
                               'holder_user_id': mlro, 'holder_name': c.name('mlro'),
                               'reports_to_title': 'Board of Directors (functional) / CEO (administrative)',
                               'reports_to_user_id': ceo, 'reports_to_board': True,
                               'other_positions': 'Head of Compliance', 'appointed_on': date(2023, 3, 1),
                               'regulator_notified_on': date(2023, 3, 9), 'regulator_ref': 'FRA-AML-DEMO-2023-117',
                               'notes': 'Appointment approved by the Board (meeting 2/2023); FRA and EMLCU notified.',
                               'is_active': True}, c.uid('admin'))
        service.save_key_role({'role_code': 'deputy_mlro', 'title': 'Deputy MLRO',
                               'holder_user_id': co, 'holder_name': c.name('co'),
                               'reports_to_title': 'Head of Compliance & MLRO', 'reports_to_user_id': mlro,
                               'other_positions': 'Senior Compliance Officer', 'appointed_on': date(2024, 1, 15),
                               'regulator_notified_on': date(2024, 1, 22), 'regulator_ref': 'FRA-AML-DEMO-2024-031',
                               'notes': 'Acts for the MLRO during absence.', 'is_active': True}, c.uid('admin'))
        service.save_key_role({'role_code': 'aml_analyst', 'title': 'AML / TM Analyst', 'holder_user_id': aml,
                               'holder_name': c.name('aml'), 'reports_to_title': 'Head of Compliance & MLRO',
                               'reports_to_user_id': mlro, 'appointed_on': date(2025, 2, 1),
                               'other_positions': None, 'is_active': True}, c.uid('admin'))
        c.q("UPDATE aml_key_roles SET updated_at = %s", (self.dt(200, 10),))
        # monitoring programme
        units = [('Cairo Downtown Branch', 'NM-CAI-01', c.uid('aml')), ('Giza Branch', 'NM-GIZ-02', c.uid('co')),
                 ('Assiut Branch', 'NM-ASY-03', c.uid('aml')), ('Operations & Lending (HQ)', 'NMF-OPS', c.uid('co'))]
        p25 = service.save_plan(2025, 'AML compliance monitoring programme 2025', date(2025, 1, 20), mlro, db=db)
        p26 = service.save_plan(2026, 'AML compliance monitoring programme 2026', date(2026, 1, 18), mlro, db=db)
        today = self.now.date()
        planned = []
        for label, code, rev in units[:3]:
            planned.append((p25, label, code, 'onsite', date(2025, 11, 10) + timedelta(days=7 * len(planned)), rev))
        for q, (mo, typ) in enumerate([(2, 'offsite'), (5, 'onsite'), (8, 'offsite'), (11, 'onsite')]):
            for label, code, rev in units:
                planned.append((p26, label, code, typ, date(2026, mo, 8 + 5 * units.index((label, code, rev))), rev))
        for pid, label, code, typ, pd, rev in planned:
            service.add_review(pid, label, typ, pd, rev, c.units[code], db=db)
        db.commit()
        revs = c.q("SELECT id, unit_label, planned_date, checklist FROM aml_monitoring_reviews ORDER BY planned_date, id")
        issue_done = False
        for rv in revs:
            if rv['planned_date'] > today - timedelta(days=3):
                continue
            n = len(rv['checklist'])
            res = [('ok', '')] * n
            concl = 'No exceptions noted.'
            if not issue_done and 'Assiut' in rv['unit_label'] and rv['planned_date'].year == 2026:
                res = list(res)
                res[0] = ('issue', '3 of 15 sampled files missing proof of address')
                res[3] = ('issue', '2 loan officers overdue on annual AML refresher')
                concl = 'Two exceptions; branch manager to remediate within 30 days.'
                issue_done = True
            elif r.random() < 0.15:
                res = list(res)
                res[5] = ('na', 'Records review covered by internal audit this quarter')
            reviewer = c.one("SELECT reviewer_id FROM aml_monitoring_reviews WHERE id=%s", (rv['id'],))['reviewer_id']
            service.complete_review(rv['id'], res, concl, reviewer,
                performed_date=rv['planned_date'] + timedelta(days=r.randrange(0, 4)), db=db)
        db.commit()
        # annual MLRO report for 2025 (board-approved)
        rid = service.generate_annual_report(2025, mlro, db=db)
        service.annual_report_action(rid, 'narrative', mlro, narrative=(
            'In 2025 the AML function completed the migration of transaction monitoring to ComplyNex, calibrated '
            'the customer risk model, screened all new customers and merchants before onboarding and filed STRs '
            'with the EMLCU where grounds for suspicion existed. Priorities for 2026: third-party repayments, '
            'cash early settlements and refresher training for branch staff.'), db=db)
        service.annual_report_action(rid, 'submit', mlro, db=db)
        service.annual_report_action(rid, 'approve', mlro, meeting_ref='BOD-2026-02',
                                     approved_on=date(2026, 2, 24), db=db)
        c.q("UPDATE aml_annual_reports SET generated_at = %s, submitted_at = %s WHERE id = %s",
            (datetime(2026, 1, 21, 10, 30), datetime(2026, 2, 3, 12, 0), rid))
        # employee screening and screening QA (engine calls)
        if not LIGHT:
            users = c.q("SELECT id, email, created_at FROM users WHERE email LIKE %s ORDER BY id", ('%@nilemicro.example',))
            skip = {c.uid('itsup'), c.uid('agent')}
            for u in users:
                if u['id'] in skip:
                    continue
                res = service.screen_employee(u['id'], c.uid('hr') if False else co, 'periodic', db=db)
                when = self.dt(r.randrange(20, 250), 10)
                db.execute("UPDATE employee_screenings SET screened_at = %s WHERE history_id = %s",
                           (when, res.get('history_id')))
                self._backdate_hist(res['history_id'], res.get('results_id'), when)
                if res.get('high_risk_matches'):
                    self._resolve(res['history_id'], res.get('results_id'), 'False Positive', co,
                                  when + timedelta(hours=4), 'Employee is a different person (DOB / ID mismatch).')
            db.commit()
            service.add_cases_from_entry('Viktor Bout', 'OFAC SDN', mlro, db=db)
            service.add_cases_from_entry('Korea Kwangson Banking Corp', 'UN / OFAC', mlro, db=db)
            db.execute("UPDATE screening_qa_cases SET entity_type = 'ENTITY' WHERE expected_name LIKE 'Korea%%'")
            service.add_synthetic_negatives(mlro, n=6, db=db)
            # QA cases only: service.run_qa reads m['name'] / m['matched_name'] but the engine returns
            # 'full_name', so every expected hit counts as a miss (recall 0%) - not run here (app bug).
            db.execute("UPDATE screening_qa_cases SET created_at = %s", (self.dt(10, 15),))
            db.commit()
        db.commit()

    # ------------------------------------------------------------ finishing touches
    def finish(self):
        c = self.c
        # queue items still pending from recent screenings: assign the older ones
        c.q("""UPDATE screening_queue SET status = 'In Review', assigned_to = %s
               WHERE status = 'Pending' AND created_at < NOW() - interval '1 day'
               AND source_module <> 'Manual Ad-Hoc'""", (c.uid('aml'),))
        # aml_alerts for screenings still open: assigned to the analyst
        c.q("UPDATE aml_alerts SET assigned_to = %s WHERE alert_status = 'OPEN' AND assigned_to IS NULL",
            (c.uid('aml'),))
        self.commit()
