"""Consumer protection: customer complaints (12 months), categories, activity logs, case registry."""
from datetime import timedelta

NEW_CATS = [  # code, en, ar, order
    ('COLLECTION', 'Debt Collection Practices', 'ممارسات التحصيل', 11),
    ('LOAN_TERMS', 'Loan Terms & Pricing', 'شروط التمويل والتسعير', 12),
    ('SERVICE_DELAY', 'Service / Disbursement Delay', 'تأخير الخدمة أو الصرف', 13),
    ('DATA_PRIVACY', 'Personal Data Handling', 'التعامل مع البيانات الشخصية', 14),
    ('STAFF_CONDUCT', 'Staff Conduct', 'سلوك الموظفين', 15),
]

# category, subject_en, desc_en, subject_ar, desc_ar, root cause, resolution
TPL = [
    ('FEES', 'Early settlement fee higher than disclosed',
     'I settled my microloan four months early and was charged an early-settlement fee of 3% although the officer told me it was 1%.',
     'رسوم السداد المبكر أعلى من المعلن', 'سددت القرض قبل موعده بأربعة أشهر وتم خصم رسوم سداد مبكر 3% رغم أن الموظف أخبرني أنها 1%.',
     'Fee schedule in branch differed from the approved tariff after the March tariff update.',
     'Difference of EGP 640 refunded; branch tariff posters replaced and staff briefed.'),
    ('FEES', 'Late penalty charged although instalment paid on time',
     'I paid my instalment through Fawry on the due date but a late payment penalty was added to my account.',
     'غرامة تأخير رغم السداد في الموعد', 'سددت القسط عن طريق فوري في يوم الاستحقاق وتمت إضافة غرامة تأخير على حسابي.',
     'Payment-aggregator file posted one day late (T+1 settlement) and the penalty job ran before posting.',
     'Penalty reversed; penalty job rescheduled to run after the aggregator file is posted.'),
    ('FEES', 'Credit life insurance premium deducted without explanation',
     'An insurance amount was deducted from my loan at disbursement. Nobody explained it to me.',
     'خصم قسط تأمين بدون توضيح', 'تم خصم مبلغ تأمين من القرض عند الصرف ولم يشرح لي أحد سبب الخصم.',
     'Mandatory credit life cover not explained at onboarding; disclosure checklist not used.',
     'Policy terms explained and copy given to customer; disclosure checklist made mandatory in loan file.'),
    ('COLLECTION', 'Collector contacted my employer about my arrears',
     'A collection officer visited my workplace and discussed my overdue instalments with my manager.',
     'مندوب التحصيل تواصل مع جهة عملي', 'قام مندوب التحصيل بزيارة مكان عملي وتحدث مع مديري عن الأقساط المتأخرة.',
     'Collector breached the collection code of conduct (third-party disclosure).',
     'Written apology issued; collector received a final warning and refresher training on the FRA collection rules.'),
    ('COLLECTION', 'Repeated collection calls late at night',
     'I received more than ten calls after 9 pm in one week about a payment that is only 5 days late.',
     'مكالمات تحصيل متكررة في وقت متأخر', 'تلقيت أكثر من عشر مكالمات بعد التاسعة مساءً خلال أسبوع بسبب قسط متأخر خمسة أيام فقط.',
     'Auto-dialler campaign had no calling-hours restriction for the Assiut queue.',
     'Calling window 9:00-20:00 enforced in the dialler; customer added to do-not-call list until due date.'),
    ('COLLECTION', 'Guarantor family contacted and pressured',
     'The collection team called my guarantor\'s wife several times and threatened to go to the police.',
     'الضغط على أسرة الضامن', 'اتصل فريق التحصيل بزوجة الضامن عدة مرات وهددها بالذهاب إلى الشرطة.',
     'Inappropriate script used by an outsourced collection agent.',
     'Agency issued a formal notice; script withdrawn; case reviewed by Compliance.'),
    ('LOAN_TERMS', 'Interest rate in contract differs from what was agreed',
     'The loan officer told me the flat rate was 18% but the contract shows a higher effective rate.',
     'سعر العائد في العقد مختلف عن المتفق عليه', 'أخبرني موظف الائتمان أن سعر العائد الثابت 18% لكن العقد يوضح سعرًا فعليًا أعلى.',
     'Officer quoted the flat rate without the effective annual rate required by the disclosure rules.',
     'Effective rate explained with a repayment schedule; officer coached; no pricing error found.'),
    ('LOAN_TERMS', 'No copy of the loan contract was given',
     'I signed the contract at the branch but I was not given a copy and the branch asks me to come back.',
     'لم أستلم نسخة من عقد التمويل', 'وقعت العقد في الفرع ولم أستلم نسخة منه والفرع يطلب مني الحضور مرة أخرى.',
     'Branch printer failure on the disbursement day; copy not handed over afterwards.',
     'Signed copy sent by courier; branch checklist updated to record hand-over of the contract copy.'),
    ('LOAN_TERMS', 'Group loan liability not explained',
     'Our group of five was told each member is only responsible for her own loan, now I am asked to pay for another member.',
     'عدم توضيح المسؤولية التضامنية في القرض الجماعي', 'قيل لمجموعتنا إن كل عضوة مسؤولة عن قرضها فقط والآن يطلب مني السداد عن عضوة أخرى.',
     'Joint-liability clause not explained in the group orientation session.',
     'Group orientation script revised; collection on the customer suspended while the group restructures.'),
    ('SERVICE_DELAY', 'Loan disbursement delayed for two weeks',
     'My loan was approved but the money has not been disbursed after two weeks and I need it for my shop stock.',
     'تأخر صرف القرض أسبوعين', 'تمت الموافقة على القرض ولم يتم الصرف بعد أسبوعين وأحتاج المبلغ لبضاعة المحل.',
     'Pending I-Score inquiry result was not followed up by the branch.',
     'Loan disbursed; daily pending-disbursement report added for branch managers.'),
    ('SERVICE_DELAY', 'Clearance letter not issued after full repayment',
     'I repaid my loan in full last month and I still did not receive the clearance letter.',
     'عدم إصدار خطاب مخالصة بعد السداد', 'سددت القرض بالكامل الشهر الماضي ولم أستلم خطاب المخالصة حتى الآن.',
     'Clearance letters issued manually; request queue not monitored.',
     'Letter issued within 24 hours; clearance letter now generated automatically on closure.'),
    ('SERVICE_DELAY', 'Credit bureau record not updated after settlement',
     'My I-Score still shows an open loan with Nile Microfinance although I settled it.',
     'عدم تحديث الاستعلام الائتماني بعد السداد', 'ما زال تقرير آي سكور يظهر قرضًا قائمًا رغم أنني سددته.',
     'Monthly bureau file excluded early-settled loans due to a mapping error.',
     'Correction file submitted to the bureau; mapping fixed and reconciled.'),
    ('SERVICE_FAILURE', 'Repayment through e-wallet not reflected',
     'I paid my instalment from my mobile wallet, the money left my wallet but the loan still shows overdue.',
     'سداد عبر المحفظة الإلكترونية لم يظهر', 'دفعت القسط من محفظتي الإلكترونية وتم خصم المبلغ لكن القرض ما زال متأخرًا.',
     'Wallet callback failed; transaction stuck in the suspense account.',
     'Payment posted from suspense with original value date; daily suspense reconciliation added.'),
    ('SYSTEM_ERROR', 'Instalment collected twice',
     'My instalment was debited twice from my account this month.',
     'تم تحصيل القسط مرتين', 'تم خصم القسط مرتين من حسابي هذا الشهر.',
     'Duplicate collection file processed after a batch restart.',
     'Duplicate amount refunded; duplicate-file control added to the batch.'),
    ('DATA_PRIVACY', 'Received SMS about another customer\'s loan',
     'I received an SMS reminder with another person\'s name and loan amount.',
     'رسالة نصية ببيانات عميل آخر', 'وصلتني رسالة تذكير باسم شخص آخر وقيمة قرضه.',
     'Mobile number recycled by the operator and not updated in the customer record.',
     'Record corrected; DPO informed and assessed as low-risk; phone re-verification added at renewal.'),
    ('DATA_PRIVACY', 'Marketing calls after I withdrew consent',
     'I asked the branch to stop marketing calls but I still receive offers for new loans.',
     'مكالمات تسويقية رغم سحب الموافقة', 'طلبت من الفرع إيقاف المكالمات التسويقية ولكن ما زالت تصلني عروض قروض جديدة.',
     'Consent withdrawal recorded in the branch but not synchronised with the marketing list.',
     'Consent flag synchronised; marketing list now pulled from the consent register.'),
    ('STAFF_CONDUCT', 'Rude treatment at the branch',
     'The customer service employee shouted at me when I asked about my balance.',
     'معاملة غير لائقة في الفرع', 'قام موظف خدمة العملاء برفع صوته علي عندما سألت عن رصيدي.',
     'Staff behaviour issue during peak hours; queue management absent.',
     'Apology call made; employee coached; queue ticket system introduced.'),
    ('STAFF_CONDUCT', 'Loan officer asked for a personal payment',
     'The loan officer asked me for EGP 500 in cash to speed up approval of my loan.',
     'موظف ائتمان طلب مبلغًا شخصيًا', 'طلب مني موظف الائتمان 500 جنيه نقدًا لتسريع الموافقة على القرض.',
     'Individual misconduct (solicitation) - referred to Compliance and the whistleblowing investigation.',
     'Referred to Compliance; officer dismissed after investigation; amount refunded to the customer.'),
    ('UNAUTH_TXN', 'Loan opened in my name without my knowledge',
     'I received a collection call for a loan I never applied for.',
     'قرض باسمي دون علمي', 'تلقيت مكالمة تحصيل عن قرض لم أتقدم بطلبه.',
     'Identity documents of the customer used by a third party; branch did not complete biometric check.',
     'Loan cancelled and bureau record corrected; case reported to the AML unit; biometric check enforced.'),
    ('DISCLOSURE', 'Total cost of the loan not explained',
     'Nobody told me the total amount I will pay back including all fees.',
     'عدم توضيح التكلفة الإجمالية للتمويل', 'لم يوضح لي أحد إجمالي المبلغ الذي سأسدده شاملًا كل الرسوم.',
     'Key facts statement not printed for renewals.',
     'Key facts statement re-issued; renewal workflow now prints it automatically.'),
    ('CUSTOMER_SERVICE', 'Hotline not answering',
     'I called the hotline many times over three days and nobody answered.',
     'الخط الساخن لا يرد', 'اتصلت بالخط الساخن عدة مرات على مدار ثلاثة أيام ولم يرد أحد.',
     'Two agents on leave during the Eid peak; no overflow routing.',
     'Overflow routing to branches configured; customer called back the same day.'),
]
FREQ = {'FEES': 9, 'COLLECTION': 10, 'LOAN_TERMS': 8, 'SERVICE_DELAY': 9, 'SERVICE_FAILURE': 4, 'SYSTEM_ERROR': 3,
        'DATA_PRIVACY': 4, 'STAFF_CONDUCT': 4, 'UNAUTH_TXN': 2, 'DISCLOSURE': 3, 'CUSTOMER_SERVICE': 4}

FIRST_F = ['Mona', 'Fatma', 'Samia', 'Hanan', 'Azza', 'Nagwa', 'Sabah', 'Rasha', 'Amal', 'Doaa', 'Eman', 'Wafaa',
           'Asmaa', 'Shaimaa', 'Hoda', 'Nadia', 'Zeinab', 'Safaa']
FIRST_M = ['Mahmoud', 'Sayed', 'Ashraf', 'Ibrahim', 'Gamal', 'Tarek', 'Reda', 'Emad', 'Wael', 'Hassan', 'Adel',
           'Sameh', 'Magdy', 'Ramadan', 'Fathy', 'Osama']
LAST = ['Abdel Aziz', 'El-Sharkawy', 'Mansour', 'Rizk', 'Soliman', 'Farag', 'Habib', 'Zaki', 'Hegazy', 'Abdel Hamid',
        'El-Masry', 'Shehata', 'Gaber', 'Ismail', 'Fouad', 'Ragab', 'Barakat', 'Attia', 'El-Naggar', 'Kamel']
CHANNELS = ['BRANCH'] * 9 + ['HOTLINE'] * 7 + ['EMAIL'] * 4 + ['PUBLIC_FORM'] * 3 + ['FRA_REFERRAL'] * 1
BRANCH_STAFF = ['br1', 'lo1', 'lo2']


def _ts(d):
    return d.strftime('%Y-%m-%d %H:%M:%S')


def _wh(d, rnd):
    """Move a timestamp into Egyptian working hours (Sun-Thu, 09:00-17:00)."""
    if d.hour >= 17:
        d = (d + timedelta(days=1)).replace(hour=rnd.randint(9, 11))
    elif d.hour < 9:
        d = d.replace(hour=rnd.randint(9, 11))
    while d.weekday() in (4, 5):
        d += timedelta(days=1)
    return d


def seed(ctx):
    rnd = ctx.rnd
    for code, en, ar, order in NEW_CATS:
        if not ctx.one("SELECT 1 FROM complaint_categories WHERE category_code = %s", (code,)):
            ctx.ins('complaint_categories', category_code=code, category_name_en=en, category_name_ar=ar,
                    display_order=order)

    pool = []
    for cat, n in FREQ.items():
        tpls = [t for t in TPL if t[0] == cat]
        pool += [tpls[i % len(tpls)] for i in range(n)]
    rnd.shuffle(pool)
    days = ctx.spread(len(pool), 360, recent_bias=True)
    days[-6:] = [11, 8, 5, 2, 1, 0]  # steady recent intake
    ids = []
    fra_n = 0
    for i, (tpl, d) in enumerate(zip(pool, days)):
        cat, s_en, d_en, s_ar, d_ar, root, fix = tpl
        female = rnd.random() < 0.62  # microfinance borrowers are mostly women
        name = f"{rnd.choice(FIRST_F if female else FIRST_M)} {rnd.choice(FIRST_M)} {rnd.choice(LAST)}"
        channel = rnd.choice(CHANNELS)
        if cat in ('COLLECTION', 'STAFF_CONDUCT') and rnd.random() < 0.2:
            channel = 'FRA_REFERRAL'
        arabic = channel in ('BRANCH', 'HOTLINE', 'PUBLIC_FORM') and rnd.random() < 0.6
        created = ctx.ago(d, hour=rnd.randint(9, 17))
        deadline = (created + timedelta(days=15)).date()
        age = d
        # lifecycle by age
        if age <= 3:
            status = rnd.choice(['NEW', 'NEW', 'IN_PROGRESS'])
        elif age <= 15:
            status = rnd.choice(['IN_PROGRESS', 'IN_PROGRESS', 'RESOLVED', 'NEW'])
        elif age <= 40:
            status = rnd.choice(['RESOLVED', 'CLOSED', 'CLOSED', 'IN_PROGRESS'])
        else:
            status = 'CLOSED' if rnd.random() < 0.9 else 'RESOLVED'
        # a few long-running escalated / overdue cases
        if i in (len(pool) - 9, len(pool) - 14, len(pool) - 21) and age > 15:
            status = 'IN_PROGRESS'
        escalated = channel == 'FRA_REFERRAL' or cat in ('STAFF_CONDUCT', 'UNAUTH_TXN')
        priority = 'URGENT' if cat in ('UNAUTH_TXN',) else 'HIGH' if escalated or cat == 'COLLECTION' else \
            rnd.choice(['NORMAL', 'NORMAL', 'NORMAL', 'LOW'])
        owner = 'co' if escalated else rnd.choice(['agent', 'agent', 'cs'])
        if status in ('RESOLVED', 'CLOSED'):
            handle = rnd.randint(3, 13) if rnd.random() < 0.88 else rnd.randint(16, 22)
            resolved = _wh(created + timedelta(days=handle, hours=rnd.randint(1, 6)), rnd)
            if resolved > ctx.now:
                resolved = ctx.now - timedelta(hours=rnd.randint(2, 20))
            closed = _wh(resolved + timedelta(days=rnd.randint(2, 6)), rnd) if status == 'CLOSED' else None
            if closed and closed > ctx.now:
                closed, status = None, 'RESOLVED'
            updated = closed or resolved
            days_rem = (deadline - resolved.date()).days
        else:
            resolved = closed = None
            updated = created + timedelta(days=min(age, rnd.randint(0, 3)), hours=2)
            days_rem = (deadline - ctx.today).days
        pin = ''.join(rnd.choice('0123456789ABCDEF') for _ in range(8))
        email = None
        if channel in ('EMAIL', 'PUBLIC_FORM') or rnd.random() < 0.3:
            email = f"{name.split()[0].lower()}.{name.split()[-1].lower().replace(' ', '').replace('-', '')}{rnd.randint(10, 99)}@mail.example"
        res_summary = None
        if status in ('RESOLVED', 'CLOSED'):
            res_summary = f"Root cause: {root} Resolution: {fix}"
        cid = ctx.ins('consumer_complaints', complaint_pin=pin, customer_name=name, customer_email=email,
                      customer_phone=f"+20 10 0000 {rnd.randint(1000, 9999)}",
                      customer_id_number=f"DEMO{rnd.randint(10**9, 10**10 - 1)}",
                      customer_type='INDIVIDUAL' if rnd.random() < 0.8 else 'MICRO_ENTERPRISE',
                      complaint_channel=channel, complaint_category=cat,
                      complaint_subject=s_ar if arabic else s_en, complaint_description=d_ar if arabic else d_en,
                      statutory_deadline_date=deadline.isoformat(), days_remaining_to_deadline=days_rem,
                      status=status, priority=priority, assigned_to_user_id=ctx.uid(owner),
                      resolution_summary=res_summary, created_at=_ts(created), updated_at=_ts(updated))
        ids.append(cid)

        # ---- activity log
        def log(at, typ, desc, new=None, by=None):
            ctx.ins('complaint_activity_log', complaint_id=cid, activity_type=typ, activity_description=desc,
                    new_status=new, performed_by=ctx.uid(by) if by else None, activity_timestamp=_ts(at))
        if channel == 'FRA_REFERRAL':
            fra_n += 1
            log(created, 'SUBMISSION', f"Complaint referred by FRA Consumer Protection (ref FRA-CP-DEMO-{2600 + fra_n})",
                'NEW', 'co')
        elif channel == 'BRANCH':
            log(created, 'SUBMISSION', 'Complaint registered at branch counter', 'NEW', rnd.choice(BRANCH_STAFF))
        elif channel == 'HOTLINE':
            log(created, 'SUBMISSION', 'Complaint received via hotline 16xxx (demo)', 'NEW', 'agent')
        else:
            log(created, 'SUBMISSION', f'Complaint submitted via {channel}', 'NEW', None)
        if status == 'NEW':
            continue
        t1 = _wh(created + timedelta(hours=rnd.randint(2, 20)), rnd)
        log(t1, 'ASSIGNMENT', f"Assigned to {ctx.name(owner)}", None, 'cs')
        log(t1 + timedelta(minutes=20), 'STATUS_CHANGE', 'Status changed from NEW to IN_PROGRESS', 'IN_PROGRESS', owner)
        t2 = _wh(t1 + timedelta(days=1, hours=rnd.randint(0, 5)), rnd)
        if t2 < ctx.now:
            log(t2, 'NOTE', 'Customer contacted by phone; acknowledgement and reference number shared', None, owner)
        if escalated:
            t3 = _wh(t1 + timedelta(days=2), rnd)
            if t3 < ctx.now:
                log(t3, 'ESCALATION', 'Escalated to Compliance for review (regulatory sensitivity)', None, 'cs')
        if status == 'IN_PROGRESS' and days_rem < 0:
            log(ctx.now - timedelta(days=rnd.randint(1, 4)), 'NOTE',
                'Statutory deadline passed - waiting for branch/collection agency evidence; reminder sent', None, 'cs')
        if resolved:
            log(resolved - timedelta(hours=2), 'NOTE', f"Root cause identified: {root}", None, owner)
            log(resolved, 'STATUS_CHANGE', f"Status changed from IN_PROGRESS to RESOLVED. {fix}", 'RESOLVED', owner)
            if channel == 'FRA_REFERRAL':
                log(resolved + timedelta(hours=2), 'NOTE', 'Response letter submitted to FRA with supporting evidence',
                    None, 'co')
        if closed:
            log(closed, 'STATUS_CHANGE', 'Customer confirmed resolution - complaint closed', 'CLOSED', 'cs')

    ctx.commit()
    from models.case import Case
    for cid in ids:
        Case.sync_from_source('CONSUMER_COMPLAINT', cid)
    ctx.data['complaint_ids'] = ids
    print(f'    complaints: {len(ids)}')
