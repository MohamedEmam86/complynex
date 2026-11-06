#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================

"""Sample board (fictional) for the governance register: one company, a board of
7 members with different capacities, a secretary, vote tellers, 3 committees and
6 board meetings (2025-2026) plus one audit committee meeting, with resolutions,
votes, conflicts, quorum, signatures, filing and follow-ups.

Every row it inserts is marked as sample (is_sample = TRUE on the parent rows;
child rows hang off sample parents), so `--remove` deletes exactly those rows.
Names and figures are invented.

Usage (from the application folder, as the application user, after the
20261106_p8gov_*.sql migration):
    venv/bin/python scripts/seed_board_sample.py            # insert (does nothing if present)
    venv/bin/python scripts/seed_board_sample.py --reset    # remove, then insert again
    venv/bin/python scripts/seed_board_sample.py --remove   # delete the sample rows only
    add --db <name> to use another database than POSTGRES_DB
"""
import argparse
import os
import sys
from datetime import date, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, '.env'))
except Exception:
    pass
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from config import Config  # noqa: E402
from governance import register_logic as RL  # noqa: E402
from governance import resolution_search as RS  # noqa: E402

ENTITY_EN = 'Nile Finance Company (sample)'
ENTITY_AR = 'شركة النيل للتمويل (مثال)'
CODE = 'NFC'


class DB:
    def __init__(self, dbname=None):
        cfg = dict(Config.POSTGRES_CONFIG)
        if dbname:
            cfg['database'] = dbname
        self.conn = psycopg2.connect(**cfg)
        self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql, args=()):
        self.cur.execute(sql, args)
        return self.cur

    def one(self, sql, args=()):
        return self.execute(sql, args).fetchone()

    def ins(self, table, **cols):
        keys = list(cols)
        return self.one(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))}) RETURNING id",
                        tuple(cols[k] for k in keys))['id']

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def has_table(self, t):
        return bool(self.one("SELECT to_regclass(%s) AS t", ('public.' + t,))['t'])


# ------------------------------------------------------------------ people
MEMBERS = [
    # key, English, Arabic, gender, nationality, legacy role, position, appointed, capacities [(dim, code, from, represents)]
    ('chair', 'Dr. Hisham Abdel-Rahman Fawzy', 'د. هشام عبد الرحمن فوزي', 'M', 'Egyptian', 'Non-Executive Chairman', 'CHAIRMAN', '2023-04-01',
     [('BOARD_ROLE', 'CHAIR', '2023-04-01', None), ('EXEC_STATUS', 'NON_EXECUTIVE', '2023-04-01', None),
      ('INDEPENDENCE', 'INDEPENDENT', '2023-04-01', None), ('REPRESENTS', 'SELF', '2023-04-01', None),
      ('SEAT_BASIS', 'ELECTED', '2023-04-01', None)]),
    ('vice', 'Mona Saeed El-Gamal', 'منى سعيد الجمال', 'F', 'Egyptian', 'Vice Chairman', 'VICE_CHAIR', '2023-04-01',
     [('BOARD_ROLE', 'VICE_CHAIR', '2023-04-01', None), ('EXEC_STATUS', 'NON_EXECUTIVE', '2023-04-01', None),
      ('INDEPENDENCE', 'NON_INDEPENDENT', '2023-04-01', None),
      ('REPRESENTS', 'LEGAL_PERSON', '2023-04-01', 'Delta Capital Holding (sample) / دلتا كابيتال القابضة (مثال)'),
      ('SEAT_BASIS', 'ELECTED', '2023-04-01', None)]),
    ('md', 'Karim Adel Mansour', 'كريم عادل منصور', 'M', 'Egyptian', 'Managing Director', 'MEMBER', '2024-01-15',
     [('BOARD_ROLE', 'MD', '2024-01-15', None), ('EXEC_STATUS', 'EXECUTIVE', '2024-01-15', None),
      ('INDEPENDENCE', 'NON_INDEPENDENT', '2024-01-15', None), ('REPRESENTS', 'SELF', '2024-01-15', None),
      ('SEAT_BASIS', 'APPOINTED', '2024-01-15', None)]),
    ('rep', 'Tarek Nabil Soliman', 'طارق نبيل سليمان', 'M', 'Egyptian', 'Board Member', 'MEMBER', '2023-04-01',
     [('BOARD_ROLE', 'MEMBER', '2023-04-01', None), ('EXEC_STATUS', 'NON_EXECUTIVE', '2023-04-01', None),
      ('INDEPENDENCE', 'NON_INDEPENDENT', '2023-04-01', None),
      ('REPRESENTS', 'LEGAL_PERSON', '2023-04-01', 'Misr Agri Investments (sample) / مصر للاستثمارات الزراعية (مثال)'),
      ('SEAT_BASIS', 'ELECTED', '2023-04-01', None)]),
    ('ind1', 'Dr. Rania Mostafa Helmy', 'د. رانيا مصطفى حلمي', 'F', 'Egyptian', 'Independent Director', 'MEMBER', '2019-05-01',
     [('BOARD_ROLE', 'MEMBER', '2019-05-01', None), ('EXEC_STATUS', 'NON_EXECUTIVE', '2019-05-01', None),
      ('INDEPENDENCE', 'INDEPENDENT', '2019-05-01', None), ('REPRESENTS', 'SELF', '2019-05-01', None),
      ('SEAT_BASIS', 'ELECTED', '2019-05-01', None)]),
    ('ind2', 'Omar Farouk Zaki', 'عمر فاروق زكي', 'M', 'Jordanian', 'Independent Director', 'MEMBER', '2023-04-01',
     [('BOARD_ROLE', 'MEMBER', '2023-04-01', None), ('EXEC_STATUS', 'NON_EXECUTIVE', '2023-04-01', None),
      ('INDEPENDENCE', 'INDEPENDENT', '2023-04-01', None), ('REPRESENTS', 'SELF', '2023-04-01', None),
      ('SEAT_BASIS', 'ELECTED', '2023-04-01', None)]),
    ('emp', 'Nadia Ibrahim Shawky', 'نادية إبراهيم شوقي', 'F', 'Egyptian', 'Board Member', 'MEMBER', '2023-04-01',
     [('BOARD_ROLE', 'MEMBER', '2023-04-01', None), ('EXEC_STATUS', 'NON_EXECUTIVE', '2023-04-01', None),
      ('INDEPENDENCE', 'NON_INDEPENDENT', '2023-04-01', None), ('REPRESENTS', 'EMPLOYEES', '2023-04-01', None),
      ('SEAT_BASIS', 'EXPERT', '2023-04-01', None)]),
]
OFFICERS = [
    ('sec', 'Ahmed Samir Lotfy', 'أحمد سمير لطفي', 'SECRETARY', 'Board secretary (not a board member).'),
    ('sec2', 'Heba Youssef Kamel', 'هبة يوسف كامل', 'SECRETARY', 'Secretary of the board committees.'),
    ('t1', 'Mahmoud Reda Hassan', 'محمود رضا حسن', 'TELLER', None),
    ('t2', 'Salma Adel Fathy', 'سلمى عادل فتحي', 'TELLER', None),
    ('aud', 'Sherif Wagdy (Hamdy & Partners, sample audit firm)', 'شريف وجدي (حمدي وشركاه للمراجعة - مثال)', 'AUDITOR', None),
]
COMMITTEES = [
    ('audit', 'Audit Committee', 'لجنة المراجعة', 'AUDIT', 'ind1', ['ind1', 'ind2', 'rep'], 'AUD'),
    ('risk', 'Risk Committee', 'لجنة المخاطر', 'RISK', 'ind2', ['ind2', 'ind1', 'vice'], 'RSK'),
    ('dcx', 'Digital Transformation & Customer Experience Committee', 'لجنة التحول الرقمي وتجربة العملاء',
     'SAMPLE_DIGITAL_CX', 'vice', ['vice', 'md', 'emp'], 'DCX'),
]
ALL = [m[0] for m in MEMBERS]


def R(title, text, summary, cat, tags, **kw):
    return dict(title=title, text=text, summary=summary, cat=cat, tags=tags, **kw)


MEETINGS = [
    dict(key='m1', date='2025-03-18', time='10:00', end='12:30', kind='ORDINARY', seq=1, mode='IN_PERSON',
         location='Head office boardroom, New Cairo', notice='2025-03-04', chair='chair', sec='sec',
         att={'ind2': 'ABSENT_EXCUSED'}, approved_on='2025-06-24', signed=('2025-06-24', '2025-06-24'), filed='2025-03-26',
         items=[
             R('اعتماد القوائم المالية عن السنة المالية 2024 وعرضها على الجمعية العامة العادية',
               'وافق المجلس على القوائم المالية المستقلة للشركة عن السنة المالية المنتهية في 31/12/2024 وتقرير مراقب الحسابات عنها، وقرر عرضها على الجمعية العامة العادية للتصديق عليها.',
               'Approval of the 2024 financial statements, referred to the ordinary general assembly for ratification.',
               'BUDGET', 'قوائم مالية, financial statements, 2024, جمعية عامة', outcome='GA_RATIFICATION',
               owner='Chief Financial Officer', due='2025-03-31', fu='DONE', evidence='Ratified by the OGM on 2025-03-30.'),
             R('ترشيح مراقب حسابات الشركة عن السنة المالية 2025',
               'قرر المجلس ترشيح مكتب حمدي وشركاه للمراجعة (مثال) لتعيينه مراقباً لحسابات الشركة عن السنة المالية 2025 بأتعاب سنوية قدرها 850 ألف جنيه، وعرض الترشيح على الجمعية العامة العادية لاعتماد التعيين.',
               'Appointment of the external auditor for FY2025 proposed to the general assembly.',
               'AUDIT', 'مراقب حسابات, external auditor, appointment, أتعاب', outcome='GA_RATIFICATION',
               owner='Board Secretary', due='2025-03-31', fu='DONE', evidence='Appointment approved by the OGM on 2025-03-30.'),
             R('اعتماد السياسة المحدثة لمكافحة غسل الأموال وتمويل الإرهاب (الإصدار الثالث)',
               'اعتمد المجلس الإصدار الثالث من سياسة مكافحة غسل الأموال وتمويل الإرهاب متضمناً منهج تقييم المخاطر المبني على المخاطر وإجراءات العناية الواجبة المعززة للعملاء مرتفعي المخاطر.',
               'Board approved version 3 of the AML/CFT policy (risk-based approach, enhanced due diligence).',
               'AML_COMPLIANCE', 'AML, CFT, KYC, سياسة, العناية الواجبة', owner='Compliance Manager',
               due='2025-04-30', fu='DONE', evidence='Policy published on the intranet on 2025-04-10; training completed.'),
             R('الموافقة على حد تمويل من البنك بمبلغ 150 مليون جنيه',
               'وافق المجلس على الحصول على تسهيل ائتماني متوسط الأجل من أحد البنوك بحد أقصى 150 مليون جنيه مصري لتمويل محفظة العملاء، وتفويض العضو المنتدب في التوقيع على عقود التمويل والضمانات.',
               'Approval of a bank credit facility (loan) up to EGP 150 million and authority to the MD to sign.',
               'FINANCING', 'قرض, تسهيل ائتماني, borrowing limit, bank', owner='Chief Financial Officer',
               due='2025-05-31', fu='DONE', evidence='Facility agreement signed on 2025-05-12.'),
             R('تشكيل لجنة التحول الرقمي وتجربة العملاء',
               'قرر المجلس تشكيل لجنة التحول الرقمي وتجربة العملاء برئاسة نائب رئيس المجلس وعضوية العضو المنتدب وممثلة العاملين، واعتماد ميثاقها.',
               'Formation of the Digital Transformation & Customer Experience Committee and approval of its charter.',
               'GOVERNANCE', 'لجنة, committee, charter, ميثاق, digital', owner='Board Secretary', due='2025-04-15',
               fu='DONE', evidence='Committee constituted; first meeting held 2025-05-05.'),
         ]),
    dict(key='m2', date='2025-06-24', time='11:00', end='13:45', kind='ORDINARY', seq=2, mode='HYBRID',
         location='Head office boardroom + video conference', notice='2025-06-10', chair='chair', sec='sec', prev='m1',
         att={'vice': 'REMOTE', 'ind2': 'REMOTE', 'emp': 'ABSENT_UNEXCUSED'}, approved_on='2025-09-14',
         signed=('2025-09-14', '2025-09-15'), filed='2025-07-08',
         conflicts=[('rep', 1, 'The premises belong to a subsidiary of the shareholder he represents (Misr Agri Investments, sample).', True, True)],
         items=[
             R('اعتماد نتائج الربع الأول وتحديث الموازنة التقديرية لعام 2025',
               'استعرض المجلس نتائج أعمال الربع الأول من عام 2025 ووافق على تحديث الموازنة التقديرية للعام في ضوء نمو المحفظة.',
               'Q1 2025 results reviewed; revised 2025 budget approved.', 'BUDGET', 'موازنة, budget, forecast, Q1',
               owner='Chief Financial Officer', due='2025-07-15', fu='DONE', evidence='Revised budget circulated 2025-07-01.'),
             R('الموافقة على تعامل مع طرف ذي علاقة: استئجار مقر فرع المنصورة',
               'وافق المجلس على استئجار مقر فرع المنصورة من شركة تابعة لأحد المساهمين بقيمة إيجارية سنوية 1.2 مليون جنيه وفقاً لتقييم مستقل لسعر السوق، مع إخطار الجمعية العامة القادمة. وقد أفصح العضو طارق نبيل سليمان عن مصلحته وامتنع عن التصويت وغادر الاجتماع أثناء المناقشة.',
               'Related-party transaction: lease of the Mansoura branch premises at market rent; the interested member disclosed and recused.',
               'RELATED_PARTY', 'طرف ذو علاقة, تعارض مصالح, related party, lease, إيجار', owner='Managing Director',
               due='2025-08-31', fu='DONE', evidence='Lease signed 2025-08-05; disclosed to the OGM of 2026.'),
             R('افتتاح فرعين جديدين في الإسكندرية وأسيوط',
               'وافق المجلس على خطة افتتاح فرعين جديدين في محافظتي الإسكندرية وأسيوط خلال عام 2025 بتكلفة استثمارية إجمالية 9 ملايين جنيه، على أن تُستكمل موافقة الجهة الرقابية قبل التشغيل.',
               'Opening of two new branches (Alexandria and Assiut) subject to regulatory approval.', 'STRATEGY',
               'فرع, فروع, branch, expansion, توسع', conditions='Regulatory approval before operation.',
               owner='Managing Director', due='2025-12-31', fu='IN_PROGRESS',
               evidence='Alexandria branch fitted out; Assiut site not yet contracted.'),
             R('سياسة أمن المعلومات والأمن السيبراني',
               'قرر المجلس تأجيل النظر في اعتماد سياسة أمن المعلومات والأمن السيبراني لحين استكمال تقييم مخاطر تكنولوجيا المعلومات من جهة استشارية مستقلة.',
               'Information security / cyber policy deferred until an independent IT risk assessment is completed.',
               'POLICIES', 'أمن المعلومات, cyber, security policy, تأجيل', outcome='DEFERRED'),
         ]),
    dict(key='m3', date='2025-09-14', time='12:00', end='13:30', kind='EXTRAORDINARY', seq=3, mode='IN_PERSON',
         location='Head office boardroom, New Cairo', notice='2025-09-07', chair='chair', sec='sec', prev='m2', call_no=2,
         first_call_at='2025-09-10 10:00', first_call_present=3,
         first_call_note='Only 3 of 7 members attended the first call (4 needed); the chair adjourned and called the meeting again for 2025-09-14.',
         tellers=['t1', 't2'], att={'ind2': 'ABSENT_EXCUSED'}, approved_on='2025-12-16', signed=('2025-12-16', '2025-12-16'),
         filed='2025-09-22',
         items=[
             R('زيادة حد التمويل من البنك من 150 إلى 250 مليون جنيه',
               'وافق المجلس على تعديل القرار الصادر بجلسة مارس 2025 بشأن حد التمويل، بزيادة الحد الأقصى للتسهيل الائتماني من 150 مليون جنيه إلى 250 مليون جنيه، مع تفويض العضو المنتدب في التوقيع.',
               'Credit facility limit increased from EGP 150m to EGP 250m (amends the March 2025 resolution).',
               'FINANCING', 'قرض, تمويل, facility, limit increase, حد ائتماني', owner='Chief Financial Officer',
               due='2025-10-15', fu='DONE', evidence='Amendment to the facility agreement signed 2025-10-02.',
               link=('AMENDS', 'm1', 4)),
             R('إعدام ديون محفظة التمويل متناهي الصغر بقيمة 4.2 مليون جنيه',
               'عرض العضو المنتدب مقترح إعدام ديون متعثرة بمحفظة التمويل متناهي الصغر بقيمة 4.2 مليون جنيه. لم يحصل المقترح على الأغلبية المطلوبة ورفضه المجلس.',
               'Proposed write-off of EGP 4.2m of non-performing microfinance loans: rejected.', 'RISK',
               'إعدام ديون, write-off, NPL, ديون متعثرة',
               votes={'md': ('FOR', None), 'rep': ('FOR', None), 'vice': ('ABSTAIN', None),
                      'chair': ('AGAINST', 'Collection efforts are not exhausted; the audit committee has not reviewed the provisioning.'),
                      'ind1': ('AGAINST', 'The write-off must first be reviewed by the audit committee against the provisioning policy.'),
                      'emp': ('AGAINST', 'Insufficient evidence of legal collection steps.')}),
             R('اعتماد خطة الطوارئ للسيولة',
               'اعتمد المجلس خطة الطوارئ لإدارة السيولة ومؤشرات الإنذار المبكر وحدود فجوات الاستحقاق.',
               'Approval of the contingency liquidity plan and early-warning indicators.', 'RISK',
               'سيولة, liquidity, contingency plan, مخاطر', owner='Head of Risk', due='2025-10-31', fu='DONE',
               evidence='Plan adopted; first stress test reported to the risk committee.'),
             R('دعوة الجمعية العامة غير العادية للنظر في زيادة رأس المال المرخص به',
               'قرر المجلس دعوة الجمعية العامة غير العادية للنظر في زيادة رأس المال المرخص به من 100 مليون جنيه إلى 300 مليون جنيه وتعديل المادتين 6 و7 من النظام الأساسي.',
               'Calling an extraordinary general assembly to increase the authorised capital.', 'CAPITAL',
               'رأس المال, capital increase, EGM, جمعية غير عادية', outcome='GA_RATIFICATION',
               owner='Board Secretary', due='2025-11-30', fu='DONE', evidence='EGM held on 2025-11-20.'),
         ]),
    dict(key='m4', date='2025-12-16', time='10:00', end='13:00', kind='ORDINARY', seq=4, mode='IN_PERSON',
         location='Head office boardroom, New Cairo', notice='2025-12-01', chair='chair', sec='sec', prev='m3',
         att={'ind2': ('PROXY', 'ind1', 'Written proxy dated 2025-12-14, certified by the chair'), 'emp': 'ABSENT_EXCUSED'},
         approved_on='2026-04-21', signed=('2026-04-21', '2026-04-21'), filed='2025-12-24',
         items=[
             R('اعتماد الموازنة التقديرية لعام 2026',
               'وافق المجلس على الموازنة التقديرية للشركة لعام 2026 بإجمالي إيرادات متوقعة 410 مليون جنيه وصافي ربح مستهدف 62 مليون جنيه، وخطة التوظيف المرفقة.',
               'Approval of the 2026 budget (revenues EGP 410m, target net profit EGP 62m).', 'BUDGET',
               'ميزانية, موازنة, budget 2026, خطة', owner='Chief Financial Officer', due='2026-01-15', fu='DONE',
               evidence='Budget loaded in the ERP on 2026-01-05.'),
             R('اعتماد تقرير الالتزام السنوي وخطة الالتزام ومكافحة غسل الأموال لعام 2026',
               'اعتمد المجلس تقرير مسؤول الالتزام السنوي عن مكافحة غسل الأموال وتمويل الإرهاب وخطة الالتزام لعام 2026 بما فيها خطة التدريب وتحديث تقييم المخاطر.',
               'Annual AML/CFT compliance report and 2026 compliance plan approved.', 'AML_COMPLIANCE',
               'غسل الأموال, compliance plan, AML report, تدريب', owner='Compliance Manager', due='2026-02-28', fu='DONE',
               evidence='Plan shared with the FRA with the annual report.'),
             R('تعيين السيدة ليلى حسني رئيساً لإدارة المخاطر',
               'وافق المجلس على تعيين السيدة ليلى حسني (مثال) رئيساً لإدارة المخاطر اعتباراً من 1/1/2026 بعد استيفاء متطلبات الصلاحية والملاءمة والحصول على موافقة الجهة الرقابية.',
               'Appointment of the Chief Risk Officer, subject to fit & proper and regulatory approval.', 'APPOINTMENTS',
               'تعيين, appointment, CRO, مخاطر, صلاحية وملاءمة', conditions='Regulator no-objection letter.',
               effective='2026-01-01', owner='Managing Director', due='2026-01-31', fu='DONE',
               evidence='No-objection received 2026-01-20.'),
             R('مقترح مكافآت وبدلات أعضاء مجلس الإدارة واللجان لعام 2026',
               'قرر المجلس رفع مقترح مكافآت وبدلات حضور أعضاء مجلس الإدارة واللجان لعام 2026 إلى الجمعية العامة العادية لاعتماده، دون مشاركة الأعضاء في التصويت على مكافآتهم في الجمعية.',
               'Board and committee remuneration proposal 2026 referred to the general assembly.', 'REMUNERATION',
               'مكافآت, بدلات, remuneration, sitting fees', outcome='GA_RATIFICATION'),
             R('تحديث مصفوفة تفويض الصلاحيات والتوقيعات البنكية',
               'اعتمد المجلس مصفوفة تفويض الصلاحيات المحدثة وحدود التوقيع على الحسابات البنكية (توقيع مزدوج فوق 5 ملايين جنيه).',
               'Updated delegation of authority matrix and bank signatories (dual signature above EGP 5m).',
               'DELEGATION', 'تفويض, توقيعات, delegation of authority, signatories', owner='Chief Financial Officer',
               due='2026-01-10', fu='DONE', evidence='Banks notified 2026-01-07.'),
         ]),
    dict(key='m5', date='2026-02-05', time='09:00', end=None, kind='CIRCULATION', seq=1, mode='REMOTE',
         location='Resolutions by circulation (written votes)', notice='2026-02-02', chair='chair', sec='sec',
         att={k: 'REMOTE' for k in ALL}, approved_on='2026-02-12', signed=('2026-02-12', '2026-02-12'), filed='2026-02-12',
         items=[
             R('تعديل حدود العناية الواجبة المعززة في سياسة مكافحة غسل الأموال',
               'بالتمرير: اعتمد المجلس تعديل سياسة مكافحة غسل الأموال لخفض حد العناية الواجبة المعززة للعملاء الأفراد إلى 200 ألف جنيه سنوياً تنفيذاً لتعليمات رقابية جديدة، وتحديث إجراءات الفحص.',
               'By circulation: AML policy amended (lower enhanced due diligence threshold) following a new regulatory circular.',
               'AML_COMPLIANCE', 'غسيل الأموال, EDD, threshold, تعديل السياسة', owner='Compliance Manager',
               due='2026-03-31', fu='IN_PROGRESS', evidence='Procedures drafted; system parameters not yet changed.',
               link=('AMENDS', 'm1', 3)),
             R('التصديق على توقيع العضو المنتدب على ملحق عقد التسهيل الائتماني',
               'بالتمرير: صادق المجلس على توقيع العضو المنتدب على ملحق عقد التسهيل الائتماني تنفيذاً لقرار زيادة الحد.',
               'By circulation: ratification of the MD signing the facility amendment.', 'FINANCING',
               'تصديق, ratify, loan agreement, عقد تمويل', link=('RATIFIES', 'm3', 1)),
             R('اعتماد إجراءات معالجة شكاوى العملاء المحدثة',
               'بالتمرير: اعتمد المجلس إجراءات معالجة شكاوى العملاء المحدثة ومدد الرد القصوى.',
               'By circulation: updated customer complaints handling procedure approved.', 'POLICIES',
               'شكاوى, complaints, consumer protection, إجراءات'),
             R('تبرع لمبادرة مجتمعية للشمول المالي بمبلغ 500 ألف جنيه',
               'بالتمرير: وافق المجلس على تبرع الشركة بمبلغ 500 ألف جنيه لمبادرة توعية بالشمول المالي في صعيد مصر.',
               'By circulation: donation of EGP 500k to a financial-inclusion awareness initiative.', 'STRATEGY',
               'تبرع, CSR, donation, شمول مالي', votes={'ind2': ('ABSTAIN', None)}),
         ]),
    dict(key='m6', date='2026-04-21', time='10:00', end='13:15', kind='ORDINARY', seq=2, mode='IN_PERSON',
         location='Head office boardroom, New Cairo', notice='2026-04-06', chair='chair', sec='sec', prev='m4',
         tellers=['t1', 't2'], att={'rep': 'ABSENT_EXCUSED'}, approved_on='2026-04-21', signed=('2026-04-28', None), filed=None,
         items=[
             R('اعتماد القوائم المالية لعام 2025 ومقترح توزيع الأرباح',
               'وافق المجلس على القوائم المالية عن السنة المالية 2025 ومقترح توزيع أرباح نقدية بواقع 0.75 جنيه للسهم، وعرضهما على الجمعية العامة العادية.',
               'FY2025 financial statements and dividend proposal referred to the general assembly.', 'BUDGET',
               'قوائم مالية, توزيع أرباح, dividend, financial statements 2025', outcome='GA_RATIFICATION'),
             R('اعتماد الخطة الاستراتيجية وخطة العمل 2026-2028',
               'اعتمد المجلس الخطة الاستراتيجية للشركة للأعوام 2026-2028 وتتضمن التحول الرقمي للخدمات والتوسع في التمويل الأخضر.',
               'Approval of the 2026-2028 strategy and business plan.', 'STRATEGY',
               'استراتيجية, business plan, خطة عمل, digital', owner='Managing Director', due='2026-06-30', fu='DONE',
               evidence='Strategy cascaded to departments in May 2026.'),
             R('ترشيح مراقب الحسابات عن السنة المالية 2026 وتحديد أتعابه',
               'بناءً على توصية لجنة المراجعة قرر المجلس ترشيح مكتب حمدي وشركاه للمراجعة (مثال) مراقباً لحسابات الشركة عن السنة المالية 2026 بأتعاب 920 ألف جنيه، وعرض ذلك على الجمعية العامة العادية.',
               'Re-appointment of the external auditor for FY2026 (on the audit committee recommendation) for GA approval.',
               'AUDIT', 'مراقب حسابات, external auditor, re-appointment, audit fee', outcome='GA_RATIFICATION',
               owner='Board Secretary', due='2026-05-15', fu='DONE', evidence='Approved by the OGM on 2026-05-10.'),
             R('اعتماد سياسة أمن المعلومات والأمن السيبراني',
               'بعد استكمال تقييم مخاطر تكنولوجيا المعلومات اعتمد المجلس سياسة أمن المعلومات والأمن السيبراني التي سبق تأجيلها بجلسة يونيو 2025.',
               'Information security and cyber policy approved (deferred in June 2025).', 'POLICIES',
               'أمن المعلومات, cyber security policy, سيبراني', owner='Head of IT', due='2026-07-31', fu='DONE',
               evidence='Policy published; awareness sessions held.', link=('SUPERSEDES', 'm2', 4)),
             R('إلغاء افتتاح فرع أسيوط والاكتفاء بفرع الإسكندرية',
               'قرر المجلس إلغاء قراره السابق بشأن افتتاح فرع أسيوط في ضوء دراسة الجدوى المحدثة، والإبقاء على فرع الإسكندرية. اعترض العضو المنتدب.',
               'Revocation of the Assiut branch opening (Alexandria kept); the MD dissented.', 'STRATEGY',
               'فرع أسيوط, branch, revoke, إلغاء',
               votes={'md': ('AGAINST', 'The updated feasibility study still shows the Assiut branch breaking even in year two.')},
               link=('REVOKES', 'm2', 3)),
             R('الموافقة على ميزانية تطوير نظام الفحص على قوائم العقوبات',
               'وافق المجلس على تخصيص 2.4 مليون جنيه لتطوير نظام الفحص على قوائم العقوبات والأشخاص المعرضين سياسياً وربطه بنظام العملاء.',
               'Budget of EGP 2.4m approved for upgrading the sanctions and PEP screening system.', 'AML_COMPLIANCE',
               'قوائم العقوبات, sanctions screening, PEP, AML, budget', owner='Compliance Manager', due='2026-06-30',
               fu='NOT_STARTED'),
         ]),
]
COMMITTEE_MEETINGS = [
    dict(key='a1', committee='audit', date='2026-03-30', time='13:00', end='14:30', kind='ORDINARY', seq=1, mode='IN_PERSON',
         location='Head office, meeting room 2', notice='2026-03-23', chair='ind1', sec='sec2', att={},
         approved_on='2026-04-15', signed=('2026-04-15', '2026-04-15'), filed=None,
         items=[
             R('التوصية بإعادة ترشيح مراقب الحسابات للسنة المالية 2026',
               'توصي لجنة المراجعة مجلس الإدارة بإعادة ترشيح مكتب حمدي وشركاه للمراجعة (مثال) مراقباً للحسابات للسنة المالية 2026 بعد تقييم استقلاليته وجودة أعماله.',
               'Audit committee recommends re-appointing the external auditor for FY2026.', 'AUDIT',
               'توصية, مراقب حسابات, auditor, recommendation', outcome='RECOMMENDATION'),
             R('اعتماد خطة المراجعة الداخلية لعام 2026',
               'اعتمدت اللجنة خطة المراجعة الداخلية المبنية على المخاطر لعام 2026.',
               'Risk-based internal audit plan 2026 approved.', 'AUDIT', 'مراجعة داخلية, internal audit plan',
               owner='Head of Internal Audit', due='2026-04-30', fu='DONE', evidence='Plan in execution.'),
         ]),
]


# ------------------------------------------------------------------ remove
def remove(db):
    if not db.has_table('gov_entities'):
        print('The governance register migration is not applied; nothing to remove.')
        return
    ents = [r['id'] for r in db.execute("SELECT id FROM gov_entities WHERE is_sample").fetchall()]
    # rows marked as sample, and rows recorded later on the sample board (its meetings, members, committees)
    members = [r['id'] for r in db.execute("SELECT id FROM board_members WHERE is_sample OR entity_id = ANY(%s)",
                                           (ents,)).fetchall()]
    meetings = [r['id'] for r in db.execute("SELECT id FROM board_meetings WHERE is_sample OR entity_id = ANY(%s)",
                                            (ents,)).fetchall()]
    committees = [r['id'] for r in db.execute("SELECT id FROM board_committees WHERE is_sample OR entity_id = ANY(%s)",
                                              (ents,)).fetchall()]
    res = [r['id'] for r in db.execute("SELECT id FROM board_decisions WHERE is_sample OR meeting_id = ANY(%s)",
                                       (meetings,)).fetchall()]
    counts = {}

    def run(label, sql, args):
        cur = db.execute(sql, args)
        counts[label] = counts.get(label, 0) + (cur.rowcount or 0)
    run('resolution links', "DELETE FROM gov_resolution_links WHERE from_resolution_id = ANY(%s) OR to_resolution_id = ANY(%s)", (res, res))
    run('votes', "DELETE FROM gov_resolution_votes WHERE resolution_id = ANY(%s) OR member_id = ANY(%s)", (res, members))
    run('conflicts', "DELETE FROM gov_conflict_declarations WHERE meeting_id = ANY(%s) OR member_id = ANY(%s)", (meetings, members))
    run('meeting officers', "DELETE FROM gov_meeting_officers WHERE meeting_id = ANY(%s)", (meetings,))
    run('action items', "DELETE FROM meeting_action_items WHERE meeting_id = ANY(%s)", (meetings,))
    run('resolutions', "DELETE FROM board_decisions WHERE id = ANY(%s)", (res,))
    run('resolution numbers', "DELETE FROM gov_resolution_numbers WHERE is_sample OR resolution_id = ANY(%s)", (res,))
    for t in ('meeting_attendance', 'meeting_agenda_items', 'meeting_minutes', 'meeting_events', 'meeting_external_attendees'):
        run(t, f"DELETE FROM {t} WHERE meeting_id = ANY(%s)", (meetings,))
    run('meetings', "DELETE FROM board_meetings WHERE id = ANY(%s)", (meetings,))
    run('committee memberships', "DELETE FROM committee_memberships WHERE committee_id = ANY(%s) OR member_id = ANY(%s)",
        (committees, members))
    if db.has_table('fp_officials'):
        offs = [r['id'] for r in db.execute("SELECT id FROM fp_officials WHERE board_member_id = ANY(%s)", (members,)).fetchall()]
        if offs:
            forms = [r['id'] for r in db.execute("SELECT id FROM fp_forms WHERE official_id = ANY(%s)", (offs,)).fetchall()]
            run('f&p form events', "DELETE FROM fp_form_events WHERE form_id = ANY(%s)", (forms,))
            run('f&p forms', "DELETE FROM fp_forms WHERE id = ANY(%s)", (forms,))
            run('f&p committee seats', "DELETE FROM fp_official_committees WHERE official_id = ANY(%s) OR committee_id = ANY(%s)",
                (offs, committees))
            run('f&p officials', "DELETE FROM fp_officials WHERE id = ANY(%s)", (offs,))
    for t in ('board_evaluations', 'board_meeting_attendance', 'board_skills_matrix', 'board_training_attendance',
              'fit_proper_assessments', 'independence_declarations'):
        if db.has_table(t):
            run(t, f"DELETE FROM {t} WHERE member_id = ANY(%s)", (members,))
    if db.has_table('pr_key_functions'):
        run('key functions unlinked', "UPDATE pr_key_functions SET board_member_id = NULL WHERE board_member_id = ANY(%s)", (members,))
    run('capacities', "DELETE FROM gov_member_capacities WHERE is_sample OR member_id = ANY(%s)", (members,))
    run('committees', "DELETE FROM board_committees WHERE id = ANY(%s)", (committees,))
    run('members', "DELETE FROM board_members WHERE id = ANY(%s)", (members,))
    run('meetings', "DELETE FROM board_meetings WHERE committee_id = ANY(%s)", (committees,))
    run('officers', "UPDATE board_meetings SET secretary_officer_id = NULL WHERE secretary_officer_id IN (SELECT id FROM gov_officers WHERE is_sample)", ())
    run('officers', "DELETE FROM gov_officers WHERE is_sample OR entity_id = ANY(%s)", (ents,))
    run('committee types', "DELETE FROM gov_committee_types WHERE is_sample", ())
    run('boards', "DELETE FROM gov_entities WHERE id = ANY(%s)", (ents,))
    db.commit()
    print('Removed sample rows: ' + ', '.join(f'{k} {v}' for k, v in counts.items() if v))


# ------------------------------------------------------------------ insert
def seed(db):
    if not db.has_table('gov_entities') or not db.has_table('gov_resolution_votes'):
        sys.exit('Apply database/migrations/20261106_p8gov_register.sql first.')
    if db.one("SELECT id FROM gov_entities WHERE is_sample AND name_en = %s", (ENTITY_EN,)):
        print('The sample board is already present (use --reset to recreate it).')
        return
    opt = {(r['dim'], r['code']): r['id'] for r in db.execute(
        """SELECT d.code AS dim, o.code, o.id FROM gov_capacity_options o
           JOIN gov_capacity_dimensions d ON d.id = o.dimension_id""").fetchall()}
    rules = {r['code']: dict(r) for r in db.execute("SELECT * FROM gov_meeting_rules").fetchall()}
    board_rule = rules.get('BOARD_FILING_10D') or rules.get('BOARD_DEFAULT')
    com_rule = rules.get('COMMITTEE_HALF') or board_rule
    ent = db.ins('gov_entities', name_en=ENTITY_EN, name_ar=ENTITY_AR, short_code=CODE, legal_form='S.A.E. (sample)',
                 rule_codes='COMPANIES_LAW,FRA_NBFI,CBE_PSP,EG_CODE_2016', is_sample=True, sort_order=50,
                 notes='Fictional company created by scripts/seed_board_sample.py')
    officers = {}
    for key, en, ar, role, note in OFFICERS:
        officers[key] = db.ins('gov_officers', full_name=en, full_name_ar=ar, role_option_id=opt.get(('NON_MEMBER_ROLE', role)),
                               entity_id=ent, email=f'{key}.sample@nilefinance.example', notes=note, is_sample=True)
    mem = {}
    for key, en, ar, gender, nat, role, pos, appointed, caps in MEMBERS:
        indep = any(d == 'INDEPENDENCE' and c == 'INDEPENDENT' for d, c, _f, _r in caps)
        exe = any(d == 'EXEC_STATUS' and c == 'EXECUTIVE' for d, c, _f, _r in caps)
        mem[key] = db.ins('board_members', member_name=en, member_name_arabic=ar, gender=gender, nationality=nat, role=role,
                          position=pos, member_type='INDEPENDENT' if indep else ('EXECUTIVE' if exe else 'NON_EXECUTIVE'),
                          is_independent=1 if indep else 0, is_executive=1 if exe else 0, appointment_date=appointed,
                          term_start_date='2026-03-30', term_end_date='2029-03-29', status='ACTIVE', is_deleted=0,
                          email=f'{key}.sample@nilefinance.example', entity_id=ent, is_sample=True, other_board_seats=1 if indep else 0,
                          independence_declaration_date='2026-01-10' if indep else None,
                          fit_proper_status='APPROVED', fit_proper_next_review='2027-01-10',
                          bio='Fictional member of the sample board.', created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        for dim, code, frm, represents in caps:
            db.ins('gov_member_capacities', member_id=mem[key], option_id=opt[(dim, code)], effective_from=frm,
                   represented_entity=represents, is_sample=True, source='sample')
    # an earlier capacity, so the history shows a change: Mona was an ordinary member before becoming vice-chair
    db.execute("UPDATE gov_member_capacities SET effective_from = '2025-01-01' WHERE member_id = %s AND option_id = %s",
               (mem['vice'], opt[('BOARD_ROLE', 'VICE_CHAIR')]))
    db.ins('gov_member_capacities', member_id=mem['vice'], option_id=opt[('BOARD_ROLE', 'MEMBER')], effective_from='2023-04-01',
           effective_to='2024-12-31', is_sample=True, source='sample', note='Elected vice-chair by the board on 2025-01-01.')
    db.ins('gov_committee_types', code='SAMPLE_DIGITAL_CX', name_en='Digital transformation & customer experience',
           name_ar='التحول الرقمي وتجربة العملاء', min_members=3, min_meetings_per_year=2, meeting_rule_code='COMMITTEE_HALF',
           res_prefix='DCX', is_sample=True, sort_order=500)
    com = {}
    for key, en, ar, typ, chair, members, prefix in COMMITTEES:
        t = db.one("SELECT * FROM gov_committee_types WHERE code = %s", (typ,)) or {}
        com[key] = db.ins('board_committees', committee_name=en + ' (sample)', committee_name_arabic=ar + ' (مثال)',
                          committee_type=typ, chairman_id=mem[chair], is_active=1, meeting_frequency='Quarterly',
                          min_members=t.get('min_members'), min_meetings_per_year=t.get('min_meetings_per_year'),
                          independent_chair=1 if t.get('independent_chair') else 0,
                          non_executive_chair=1 if t.get('non_executive_chair') else 0,
                          requires_financial_expert=1 if t.get('requires_financial_expert') else 0,
                          meeting_rule_id=com_rule['id'], res_prefix=prefix, entity_id=ent, is_sample=True,
                          charter_next_review='2027-03-31', charter_version='1.0',
                          created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        for k in members:
            db.ins('committee_memberships', committee_id=com[key], member_id=mem[k],
                   role='CHAIRMAN' if k == chair else 'MEMBER', joined_date='2025-05-01', is_active=1,
                   has_required_expertise=1 if k == 'ind1' else 0)
    meeting_ids, res_ids, pending_links = {}, {}, []
    for spec in MEETINGS + COMMITTEE_MEETINGS:
        is_com = 'committee' in spec
        rule = com_rule if is_com else board_rule
        body = 'COMMITTEE' if is_com else 'BOARD'
        people = COMMITTEES[[c[0] for c in COMMITTEES].index(spec['committee'])][5] if is_com else ALL
        d = RL.as_date(spec['date'])
        prefix = RL.body_prefix(body, COMMITTEES[[c[0] for c in COMMITTEES].index(spec['committee'])][6] if is_com else None, CODE)
        ref = f"{prefix}-{d.year}-{spec['seq']:02d}"
        mtype = 'AUDIT_COMMITTEE' if is_com else ('EXTRAORDINARY' if spec['kind'] == 'EXTRAORDINARY' else 'BOARD')
        signed = spec.get('signed') or (None, None)
        filing_due = None if is_com else RL.filing_due(d, rule.get('filing_days'))
        state = 'SIGNED' if signed[0] and signed[1] else ('APPROVED' if spec.get('approved_on') else 'DRAFT')
        mid = db.ins('board_meetings', meeting_type=mtype, committee_id=com.get(spec.get('committee')), meeting_date=spec['date'],
                     meeting_time=spec['time'], end_time=spec.get('end'), location=spec['location'], status='COMPLETED',
                     meeting_reference=ref, entity_id=ent, body=body, meeting_kind=spec['kind'], sequence_no=spec['seq'],
                     mode=spec['mode'], notice_date=spec['notice'], notice_channel='Email with the meeting papers',
                     chair_member_id=mem[spec['chair']], secretary_officer_id=officers[spec['sec']], meeting_rule_id=rule['id'],
                     call_no=spec.get('call_no', 1), first_call_at=spec.get('first_call_at'),
                     first_call_present=spec.get('first_call_present'), first_call_note=spec.get('first_call_note'),
                     prev_minutes_meeting_id=meeting_ids.get(spec.get('prev')), prev_minutes_approved=1 if spec.get('prev') else None,
                     minutes_state=state, minutes_approved_on=spec.get('approved_on'),
                     chair_signed_at=signed[0], chair_signed_name=MEMBERS[ALL.index(spec['chair'])][1] if signed[0] else None,
                     secretary_signed_at=signed[1],
                     secretary_signed_name=[o[1] for o in OFFICERS if o[0] == spec['sec']][0] if signed[1] else None,
                     filing_authority=None if is_com else rule.get('filing_authority'), filing_due_date=filing_due,
                     filed_on=spec.get('filed'), filing_reference=('FRA-SAMPLE-' + spec['date'].replace('-', '')) if spec.get('filed') else None,
                     is_sample=True)
        meeting_ids[spec['key']] = mid
        # attendance
        att = {}
        for k in people:
            a = spec['att'].get(k, 'IN_PERSON')
            code, holder, doc = (a if isinstance(a, tuple) else (a, None, None))
            cols = RL.legacy_columns(code)
            db.ins('meeting_attendance', meeting_id=mid, member_id=mem[k], attended=cols['attended'],
                   attended_remotely=cols['attended_remotely'], apology_received=cols['apology_received'],
                   attendance_status=cols['attendance_status'], proxy_holder_member_id=mem[holder] if holder else None,
                   proxy_name=MEMBERS[ALL.index(holder)][1] if holder else None, proxy_document=doc,
                   proxy_valid=1 if holder else None, absence_authorized=1 if code == 'ABSENT_EXCUSED' else 0,
                   remote_platform='Video conference' if code == 'REMOTE' else None,
                   recorded_at=spec['date'] + ' 18:00:00')
            att[k] = code
        counts = {c: sum(1 for v in att.values() if v == c) for c in RL.ATTENDANCE}
        q = RL.quorum(rule, len(people), counts, spec.get('call_no', 1))
        db.execute("UPDATE board_meetings SET quorum_required = %s, quorum_counted = %s, members_total = %s, quorum_met = %s WHERE id = %s",
                   (q['required'], q['counted'], len(people), 1 if q['valid'] else 0, mid))
        for t in spec.get('tellers', []):
            db.ins('gov_meeting_officers', meeting_id=mid, role='TELLER', officer_id=officers[t])
        # agenda
        agenda_titles = []
        n = 0
        if spec.get('prev'):
            n += 1
            db.ins('meeting_agenda_items', meeting_id=mid, item_number=n, item_title='التصديق على محضر الاجتماع السابق',
                   item_type='MINUTES', display_order=n)
            agenda_titles.append('التصديق على محضر الاجتماع السابق')
        item_ids = []
        for it in spec['items']:
            n += 1
            item_ids.append(db.ins('meeting_agenda_items', meeting_id=mid, item_number=n, item_title=it['title'],
                                   item_description=it['summary'], item_type='DECISION', display_order=n,
                                   presenter_name='Managing Director' if not is_com else None))
            agenda_titles.append(it['title'])
        db.execute("UPDATE board_meetings SET agenda = %s WHERE id = %s",
                   ('\n'.join(f'{i}. {t}' for i, t in enumerate(agenda_titles, 1)), mid))
        conflicted = {}
        for who, idx, nature, left, ga in spec.get('conflicts', []):
            cid = db.ins('gov_conflict_declarations', meeting_id=mid, member_id=mem[who], agenda_item_id=item_ids[idx],
                         nature=nature, left_room=left, did_not_vote=True, ga_informed=ga)
            conflicted.setdefault(idx, []).append((who, cid))
        # resolutions
        for i, it in enumerate(spec['items']):
            votes = {}
            for k in people:
                code = att[k]
                v = 'FOR' if code in ('IN_PERSON', 'REMOTE', 'PROXY') else 'ABSENT'
                votes[k] = [v, None]
            for k, (v, dis) in (it.get('votes') or {}).items():
                votes[k] = [v, dis]
            for who, _cid in conflicted.get(i, []):
                votes[who] = ['RECUSED', None]
            codes = [v[0] for v in votes.values()]
            eligible = sum(1 for c in codes if c in ('FOR', 'AGAINST', 'ABSTAIN'))
            achieved, need, note = RL.majority(rule['majority_rule'], codes, votes.get(spec['chair'], [None])[0],
                                               casting=bool(rule.get('chair_casting_vote')), eligible=eligible)
            outcome = RL.suggested_outcome(achieved, it.get('outcome'))
            t = RL.tally(codes)
            res_no = RL.resolution_number(prefix, d.year, spec['seq'], i + 1)
            dissent = '; '.join(f"{MEMBERS[ALL.index(k)][1]}: {v[1]}" for k, v in votes.items() if v[1]) or None
            due = RL.as_date(it.get('due'))
            rid = db.ins('board_decisions', meeting_id=mid, res_no=res_no, item_no=i + 1, decision_number=res_no,
                         decision_reference=res_no, decision_date=spec['date'], decision_title=it['title'],
                         decision_text=it['text'], decision_description=it['text'], summary=it['summary'],
                         category_code=it['cat'], tags=it['tags'], agenda_item_id=item_ids[i], outcome=outcome,
                         majority_rule=rule['majority_rule'], majority_achieved=1 if achieved else 0,
                         majority_note=f"{t['FOR']}/{eligible} for; {need} needed ({note})", conditions=it.get('conditions'),
                         effective_date=it.get('effective') or (spec['date'] if outcome == 'APPROVED' else None),
                         action_owner=it.get('owner'), due_date=due, responsible_person=it.get('owner'),
                         deadline=due.isoformat() if due else None, implementation_deadline=due.isoformat() if due else None,
                         followup_status=it.get('fu'), followup_evidence=it.get('evidence'),
                         implemented=1 if it.get('fu') == 'DONE' else 0,
                         votes_for=t['FOR'], votes_against=t['AGAINST'], votes_abstain=t['ABSTAIN'],
                         vote_result=RL.legacy_vote_result(outcome),
                         vote_type='UNANIMOUS' if t['AGAINST'] == 0 and t['ABSTAIN'] == 0 else 'MAJORITY',
                         dissent_notes=dissent, dissenting_reasons=dissent,
                         dissenting_members=', '.join(MEMBERS[ALL.index(k)][1] for k, v in votes.items() if v[0] == 'AGAINST') or None,
                         status='COMPLETED' if it.get('fu') == 'DONE' else 'PENDING', is_sample=True,
                         recorded_at=datetime.strptime(spec['date'], '%Y-%m-%d'), created_at=spec['date'] + ' 18:00:00')
            db.execute("INSERT INTO gov_resolution_numbers (res_no, resolution_id, meeting_id, is_sample) VALUES (%s,%s,%s,TRUE)",
                       (res_no, rid, mid))
            for k, (v, dis) in votes.items():
                db.ins('gov_resolution_votes', resolution_id=rid, member_id=mem[k], vote=v,
                       via_proxy=(att[k] == 'PROXY' and v in ('FOR', 'AGAINST', 'ABSTAIN')), dissent_text=dis)
            for who, cid in conflicted.get(i, []):
                db.execute("UPDATE gov_conflict_declarations SET resolution_id = %s WHERE id = %s", (rid, cid))
            res_ids[(spec['key'], i + 1)] = rid
            if it.get('link'):
                pending_links.append((rid, it['link']))
            db.execute("""INSERT INTO meeting_events (meeting_id, subject, subject_id, event, to_status, note)
                          VALUES (%s,'resolution',%s,'resolution_recorded',%s,%s)""", (mid, rid, outcome, res_no + ' (sample)'))
    for rid, (lt, mkey, item) in pending_links:
        db.ins('gov_resolution_links', from_resolution_id=rid, to_resolution_id=res_ids[(mkey, item)], link_type=lt,
               note='sample')
    db.commit()
    n = 0
    for rid in res_ids.values():
        n += RS.reindex(db, rid)
    print(f'Sample board created: "{ENTITY_EN}" — {len(mem)} members, {len(officers)} officers, {len(com)} committees, '
          f'{len(meeting_ids)} meetings, {len(res_ids)} resolutions (indexed {n}).')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--remove', action='store_true', help='delete the sample rows only')
    ap.add_argument('--reset', action='store_true', help='remove, then insert again')
    ap.add_argument('--db', help='database name (default POSTGRES_DB)')
    a = ap.parse_args()
    db = DB(a.db)
    try:
        if a.remove or a.reset:
            remove(db)
        if not a.remove:
            seed(db)
    except Exception:
        db.rollback()
        raise


if __name__ == '__main__':
    main()
