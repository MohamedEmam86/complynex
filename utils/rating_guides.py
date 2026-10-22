"""Rating guides: what every score in the system means and when to give it.

One place for the descriptors behind each rating scale (risk likelihood and
impact, fit & proper criteria, ESG maturity, materiality, carbon data quality,
cyber maturity, board skills, audit finding ratings...). Pages show the guide
next to the input (templates/partials/rating_guide.html) and all guides are
listed at /guides/ratings, so two people scoring the same facts reach the same
number and the reason for a score can be explained to an inspector.

Data only - a company may adapt a guide; keep each level's text short and
observable (what evidence would you see?).
"""

def _lv(n, en, ar, d_en, d_ar, ev_en='', ev_ar=''):
    return {'level': n, 'label_en': en, 'label_ar': ar, 'desc_en': d_en, 'desc_ar': d_ar,
            'evidence_en': ev_en, 'evidence_ar': ev_ar}


GUIDES = {
    # ------------------------------------------------------------------ risk
    'risk.likelihood': {
        'module': 'risk_management', 'title_en': 'Risk likelihood (1–5)', 'title_ar': 'احتمالية الخطر (1–5)',
        'where_en': 'Risk register — inherent and residual likelihood', 'where_ar': 'سجل المخاطر — الاحتمالية الكامنة والمتبقية',
        'how_en': 'Ask how often the event would happen in the next 12 months with today\'s controls (residual) or with no controls (inherent). Use your own loss/incident history first, then peer and regulator data. When two levels fit, choose the higher and record why.',
        'how_ar': 'السؤال: كم مرة قد يقع الحدث خلال الـ 12 شهراً القادمة في ظل الضوابط الحالية (المتبقي) أو بدون ضوابط (الكامن)؟ اعتمد أولاً على سجل الخسائر والحوادث لديك، ثم بيانات النظراء والجهات الرقابية. إذا انطبق مستويان اختر الأعلى ووثّق السبب.',
        'levels': [
            _lv(1, 'Rare', 'نادر', 'May occur only in exceptional circumstances; not seen in the last 5 years here or at peers. Below 5% a year.',
                'قد يحدث في ظروف استثنائية فقط؛ لم يقع خلال آخر 5 سنوات لدينا أو لدى النظراء. أقل من 5% سنوياً.',
                'No incidents in the loss database; strong preventive controls tested effective.', 'لا حوادث في قاعدة الخسائر؛ ضوابط وقائية قوية مختبرة وفعّالة.'),
            _lv(2, 'Unlikely', 'غير محتمل', 'Could occur at some time; once in 3–5 years. 5–20% a year.', 'قد يحدث في وقت ما؛ مرة كل 3–5 سنوات. 5–20% سنوياً.',
                'Isolated near-misses; one event at a peer.', 'حالات وشيكة متفرقة؛ حدث واحد لدى أحد النظراء.'),
            _lv(3, 'Possible', 'ممكن', 'Might occur; about once in 1–3 years. 20–50% a year.', 'قد يحدث؛ مرة كل 1–3 سنوات تقريباً. 20–50% سنوياً.',
                'Has happened here before; control weaknesses noted by audit.', 'سبق حدوثه لدينا؛ ملاحظات مراجعة على الضوابط.'),
            _lv(4, 'Likely', 'مرجح', 'Will probably occur in most circumstances; at least once a year. 50–80% a year.', 'سيحدث غالباً؛ مرة على الأقل سنوياً. 50–80% سنوياً.',
                'Repeated incidents; KRI in amber/red; open findings.', 'حوادث متكررة؛ مؤشر مخاطر في المنطقة الصفراء/الحمراء؛ ملاحظات مفتوحة.'),
            _lv(5, 'Almost certain', 'شبه مؤكد', 'Expected to occur; several times a year or already occurring. Above 80% a year.', 'متوقع الحدوث؛ عدة مرات سنوياً أو يحدث بالفعل. أكثر من 80% سنوياً.',
                'Ongoing losses or breaches; regulator or auditor has already raised it.', 'خسائر أو مخالفات مستمرة؛ أثارتها الجهة الرقابية أو المراجع بالفعل.'),
        ]},
    'risk.impact': {
        'module': 'risk_management', 'title_en': 'Risk impact (1–5)', 'title_ar': 'أثر الخطر (1–5)',
        'where_en': 'Risk register — inherent and residual impact', 'where_ar': 'سجل المخاطر — الأثر الكامن والمتبقي',
        'how_en': 'Score the worst reasonable outcome on each dimension (financial, regulatory, customers, reputation, operations) and take the HIGHEST. Set the financial bands as a share of equity in the risk appetite statement so they scale with the company.',
        'how_ar': 'قيّم أسوأ نتيجة معقولة في كل بُعد (مالي، رقابي، العملاء، السمعة، التشغيل) وخذ الأعلى. حدّد الشرائح المالية كنسبة من حقوق الملكية في بيان الرغبة في المخاطر حتى تتناسب مع حجم الشركة.',
        'levels': [
            _lv(1, 'Insignificant', 'ضئيل', 'Loss < 0.5% of equity; no regulatory interest; no customer harm; internal only; disruption < 1 hour.',
                'خسارة < 0.5% من حقوق الملكية؛ لا اهتمام رقابي؛ لا ضرر للعملاء؛ داخلي فقط؛ توقف < ساعة.'),
            _lv(2, 'Minor', 'بسيط', 'Loss 0.5–1% of equity; routine regulator query; few customers inconvenienced; local complaints; disruption < 1 day.',
                'خسارة 0.5–1% من حقوق الملكية؛ استفسار رقابي روتيني؛ إزعاج عدد محدود من العملاء؛ شكاوى محلية؛ توقف < يوم.'),
            _lv(3, 'Moderate', 'متوسط', 'Loss 1–3% of equity; regulator finding or warning; a group of customers harmed and compensated; local media; disruption 1–3 days.',
                'خسارة 1–3% من حقوق الملكية؛ ملاحظة أو إنذار رقابي؛ ضرر لمجموعة من العملاء مع تعويض؛ إعلام محلي؛ توقف 1–3 أيام.'),
            _lv(4, 'Major', 'كبير', 'Loss 3–10% of equity; fine or restriction on activity; widespread customer harm; national media; critical service down > 3 days.',
                'خسارة 3–10% من حقوق الملكية؛ غرامة أو تقييد للنشاط؛ ضرر واسع للعملاء؛ إعلام قومي؛ توقف خدمة حرجة > 3 أيام.'),
            _lv(5, 'Severe', 'جسيم', 'Loss > 10% of equity or capital below the licence minimum; licence suspension; systemic customer harm; lasting reputational damage; business continuity threatened.',
                'خسارة > 10% من حقوق الملكية أو انخفاض رأس المال عن الحد الأدنى للترخيص؛ إيقاف الترخيص؛ ضرر منهجي للعملاء؛ ضرر دائم بالسمعة؛ تهديد استمرارية الأعمال.'),
        ]},
    'risk.control_effectiveness': {
        'module': 'risk_management', 'title_en': 'Control effectiveness', 'title_ar': 'فعالية الضوابط',
        'where_en': 'Risk register — residual assessment; control tests', 'where_ar': 'سجل المخاطر — التقييم المتبقي؛ اختبارات الضوابط',
        'how_en': 'Base it on the latest test (design and operating effectiveness), not on the policy text. A control never tested is "Not assessed", whatever its design.',
        'how_ar': 'يُبنى على آخر اختبار (التصميم وفعالية التشغيل) وليس على نص السياسة. الضابط الذي لم يُختبر يُصنَّف "غير مُقيَّم" مهما كان تصميمه.',
        'levels': [
            _lv('EFFECTIVE', 'Effective', 'فعّال', 'Designed to address the risk AND tested in the last 12 months with no exceptions (or only trivial ones).',
                'مصمم لمعالجة الخطر واختُبر خلال آخر 12 شهراً دون استثناءات (أو استثناءات طفيفة فقط).'),
            _lv('PARTIALLY_EFFECTIVE', 'Partially effective', 'فعّال جزئياً', 'Design gaps, or exceptions found in testing, or manual and dependent on one person.',
                'فجوات في التصميم، أو استثناءات في الاختبار، أو يدوي ويعتمد على شخص واحد.'),
            _lv('INEFFECTIVE', 'Ineffective', 'غير فعّال', 'Not operating, repeatedly failing tests, or the risk event happened despite it.',
                'لا يعمل، أو يفشل في الاختبارات بشكل متكرر، أو وقع حدث الخطر رغم وجوده.'),
            _lv('NOT_ASSESSED', 'Not assessed', 'غير مُقيَّم', 'No test in the last 12 months. Treat residual risk as equal to inherent until tested.',
                'لا يوجد اختبار خلال آخر 12 شهراً. يُعامل الخطر المتبقي كمساوٍ للكامن حتى يُختبر.'),
        ]},
    # ------------------------------------------------------------------ fit & proper
    'fp.honesty': {
        'module': 'governance', 'title_en': 'Fit & proper — Honesty, integrity and reputation', 'title_ar': 'الجدارة والصلاحية — المصداقية والنزاهة وحسن السمعة',
        'where_en': 'Fit & proper institution assessment (form section 6, references, screening)', 'where_ar': 'تقييم المؤسسة للجدارة والصلاحية (القسم 6 من النموذج، المراجع، الفحص)',
        'how_en': 'Start from the candidate\'s answers to section 6, then verify: criminal record certificate, sanctions/PEP/adverse-media screening, references, regulator history. Any undisclosed adverse fact found later caps the score at 1.',
        'how_ar': 'ابدأ من إجابات المرشح في القسم 6 ثم تحقق من: الفيش الجنائي، فحص العقوبات والأشخاص المعرضين سياسياً والأخبار السلبية، المراجع، السجل لدى الجهات الرقابية. أي واقعة سلبية لم يُفصح عنها تُكتشف لاحقاً تجعل الدرجة 1 كحد أقصى.',
        'levels': [
            _lv(1, 'Not acceptable', 'غير مقبول', 'Conviction for dishonesty/fraud, final disciplinary removal, or material facts concealed in the form.',
                'حكم في جريمة ماسة بالشرف أو احتيال، أو فصل تأديبي نهائي، أو إخفاء وقائع جوهرية في النموذج.'),
            _lv(2, 'Serious concerns', 'مخاوف جدية', 'A "Yes" in section 6 that is recent or not fully explained; adverse media under investigation.',
                'إجابة "نعم" في القسم 6 حديثة أو غير موضحة بالكامل؛ أخبار سلبية قيد التحقق.'),
            _lv(3, 'Acceptable with explanation', 'مقبول مع إيضاح', 'An old, minor and fully disclosed matter, explained and closed; references satisfactory.',
                'واقعة قديمة وبسيطة ومُفصح عنها بالكامل، موضحة ومغلقة؛ مراجع مُرضية.'),
            _lv(4, 'Good', 'جيد', 'All answers "No", criminal record clear, screening clear, references positive.',
                'كل الإجابات "لا"، فيش جنائي نظيف، الفحص نظيف، مراجع إيجابية.'),
            _lv(5, 'Exemplary', 'نموذجي', 'As 4, plus a long record in regulated roles with no regulator findings and independent confirmation from a previous regulator/employer.',
                'كالدرجة 4، بالإضافة إلى سجل طويل في وظائف خاضعة للرقابة دون ملاحظات رقابية وتأكيد مستقل من جهة رقابية/صاحب عمل سابق.'),
        ]},
    'fp.competence': {
        'module': 'governance', 'title_en': 'Fit & proper — Competence and capability', 'title_ar': 'الجدارة والصلاحية — الكفاءة والقدرة',
        'where_en': 'Fit & proper institution assessment (form sections 4 and 7)', 'where_ar': 'تقييم المؤسسة للجدارة والصلاحية (القسمان 4 و7 من النموذج)',
        'how_en': 'Compare qualifications and experience with the role profile (job description, committee charter, regulator minimums). Verify degrees and certificates, not just the CV.',
        'how_ar': 'قارن المؤهلات والخبرة بمتطلبات الوظيفة (الوصف الوظيفي، ميثاق اللجنة، الحد الأدنى الرقابي). تحقق من الشهادات والمؤهلات وليس السيرة الذاتية فقط.',
        'levels': [
            _lv(1, 'Does not meet', 'لا يستوفي', 'Below the regulatory minimum qualifications or experience for the role.', 'أقل من الحد الأدنى الرقابي للمؤهلات أو الخبرة للوظيفة.'),
            _lv(2, 'Partly meets', 'يستوفي جزئياً', 'Meets minimums on paper but lacks experience in the institution\'s activity or at this level.', 'يستوفي الحد الأدنى شكلياً لكن تنقصه خبرة في نشاط المؤسسة أو في هذا المستوى.'),
            _lv(3, 'Meets', 'يستوفي', 'Relevant degree, required years of experience, at least some at a comparable level.', 'مؤهل مناسب، وسنوات الخبرة المطلوبة، بعضها على الأقل في مستوى مماثل.'),
            _lv(4, 'Strong', 'قوي', 'Exceeds requirements; relevant professional certification; proven results in a similar role.', 'يتجاوز المتطلبات؛ شهادة مهنية ذات صلة؛ نتائج مثبتة في وظيفة مماثلة.'),
            _lv(5, 'Outstanding', 'متميز', 'Recognised expert in the field; senior regulated experience; adds a skill missing on the board/committee skills matrix.', 'خبير معترف به في المجال؛ خبرة قيادية في جهات خاضعة للرقابة؛ يضيف مهارة ناقصة في مصفوفة مهارات المجلس/اللجنة.'),
        ]},
    'fp.financial': {
        'module': 'governance', 'title_en': 'Fit & proper — Financial soundness', 'title_ar': 'الجدارة والصلاحية — الملاءة المالية',
        'where_en': 'Fit & proper institution assessment (form section 8, credit report)', 'where_ar': 'تقييم المؤسسة للجدارة والصلاحية (القسم 8 من النموذج، تقرير الائتمان)',
        'how_en': 'Use the answers in section 8 and the credit bureau (I-Score) report and no-bankruptcy certificate.',
        'how_ar': 'استخدم إجابات القسم 8 وتقرير الاستعلام الائتماني (I-Score) وشهادة عدم الإفلاس.',
        'levels': [
            _lv(1, 'Not acceptable', 'غير مقبول', 'Bankruptcy, unpaid judgment debt, or classified non-performing now.', 'إفلاس، أو دين بحكم لم يُسدد، أو مصنف غير منتظم حالياً.'),
            _lv(2, 'Serious concerns', 'مخاوف جدية', 'Settlement of obligations in progress or recent defaults.', 'تسوية التزامات جارية أو تعثر حديث.'),
            _lv(3, 'Acceptable with explanation', 'مقبول مع إيضاح', 'A past default fully settled and explained; obligations now current.', 'تعثر سابق تمت تسويته بالكامل وتوضيحه؛ الالتزامات منتظمة حالياً.'),
            _lv(4, 'Good', 'جيد', 'Clean credit report; obligations proportionate to income.', 'تقرير ائتماني نظيف؛ التزامات متناسبة مع الدخل.'),
            _lv(5, 'Strong', 'قوي', 'Clean report, low leverage, no contingent liabilities that could create pressure.', 'تقرير نظيف، مديونية منخفضة، لا التزامات محتملة قد تشكل ضغطاً.'),
        ]},
    'fp.independence': {
        'module': 'governance', 'title_en': 'Fit & proper — Independence and conflicts of interest', 'title_ar': 'الجدارة والصلاحية — الاستقلالية وتعارض المصالح',
        'where_en': 'Fit & proper institution assessment (form sections 5, 9 and 10)', 'where_ar': 'تقييم المؤسسة للجدارة والصلاحية (الأقسام 5 و9 و10 من النموذج)',
        'how_en': 'Check related parties, shareholdings, competing activities and relatives. For independent board members every item of section 10 must be met; one failure makes the member non-independent (score 1 for that role).',
        'how_ar': 'افحص الأطراف ذات الصلة والملكيات والأنشطة المنافسة والأقارب. لعضو المجلس المستقل يجب استيفاء كل بنود القسم 10؛ عدم استيفاء بند واحد يجعله غير مستقل (درجة 1 لهذه الصفة).',
        'levels': [
            _lv(1, 'Not acceptable', 'غير مقبول', 'Conflict that cannot be managed for this role, or independence criteria not met for an independent seat.', 'تعارض لا يمكن إدارته لهذه الوظيفة، أو عدم استيفاء شروط الاستقلالية لمقعد مستقل.'),
            _lv(2, 'Serious concerns', 'مخاوف جدية', 'Material conflict needing recusal on frequent decisions or divestment.', 'تعارض جوهري يتطلب التنحي عن قرارات متكررة أو التخارج.'),
            _lv(3, 'Manageable', 'قابل للإدارة', 'Disclosed conflict with an agreed mitigation (recusal, information barrier) recorded.', 'تعارض مُفصح عنه مع إجراء معالجة متفق عليه (التنحي، فصل المعلومات) وموثق.'),
            _lv(4, 'Good', 'جيد', 'Minor, disclosed interests only; no related-party dealings.', 'مصالح بسيطة مُفصح عنها فقط؛ لا تعاملات مع أطراف ذات صلة.'),
            _lv(5, 'Fully independent', 'مستقل تماماً', 'No interests, relatives or relationships that could affect judgement.', 'لا مصالح أو أقارب أو علاقات قد تؤثر على الحكم.'),
        ]},
    'fp.time': {
        'module': 'governance', 'title_en': 'Fit & proper — Time commitment', 'title_ar': 'الجدارة والصلاحية — التفرغ وتخصيص الوقت',
        'where_en': 'Fit & proper institution assessment (form section 4.5–4.7)', 'where_ar': 'تقييم المؤسسة للجدارة والصلاحية (القسم 4.5–4.7 من النموذج)',
        'how_en': 'Add up the time declared for other boards and commitments and compare with the expected time for this role (meetings, preparation, committee work; executives are full time).',
        'how_ar': 'اجمع الوقت المعلن للمجالس والالتزامات الأخرى وقارنه بالوقت المتوقع لهذه الوظيفة (الاجتماعات، التحضير، أعمال اللجان؛ التنفيذيون متفرغون).',
        'levels': [
            _lv(1, 'Insufficient', 'غير كافٍ', 'Full-time job elsewhere for an executive role, or commitments that clearly leave no time.', 'وظيفة بدوام كامل في جهة أخرى لوظيفة تنفيذية، أو التزامات لا تترك وقتاً بوضوح.'),
            _lv(2, 'Doubtful', 'محل شك', 'Many concurrent boards/roles; attendance record below 75%.', 'عضويات/وظائف متزامنة كثيرة؛ نسبة حضور أقل من 75%.'),
            _lv(3, 'Adequate', 'كافٍ', 'Declared time meets the expected minimum; attendance 75–90%.', 'الوقت المعلن يفي بالحد الأدنى المتوقع؛ حضور 75–90%.'),
            _lv(4, 'Good', 'جيد', 'Comfortable margin; attendance above 90%.', 'هامش مريح؛ حضور أعلى من 90%.'),
            _lv(5, 'Fully available', 'متفرغ تماماً', 'Few or no other commitments; available for ad-hoc meetings and committee work.', 'التزامات قليلة أو منعدمة؛ متاح للاجتماعات الطارئة وأعمال اللجان.'),
        ]},
    # ------------------------------------------------------------------ governance
    'governance.skills': {
        'module': 'governance', 'title_en': 'Board skills matrix (0–5)', 'title_ar': 'مصفوفة مهارات المجلس (0–5)',
        'where_en': 'Governance — skills assessment per board member', 'where_ar': 'الحوكمة — تقييم المهارات لكل عضو مجلس',
        'how_en': 'Score what the member can evidence (roles held, qualifications, board training), not self-perception. The matrix shows gaps when no member reaches 4 in a skill the board needs.',
        'how_ar': 'قيّم ما يستطيع العضو إثباته (الوظائف السابقة، المؤهلات، تدريب المجلس) وليس تقديره لنفسه. تُظهر المصفوفة فجوة إذا لم يصل أي عضو إلى 4 في مهارة يحتاجها المجلس.',
        'levels': [
            _lv(0, 'None', 'لا يوجد', 'No knowledge or exposure.', 'لا معرفة أو احتكاك.'),
            _lv(1, 'Basic awareness', 'وعي أساسي', 'Understands the terms; relies on others.', 'يفهم المصطلحات؛ يعتمد على الآخرين.'),
            _lv(2, 'Developing', 'قيد التطوير', 'Some training; can ask the right questions.', 'بعض التدريب؛ يستطيع طرح الأسئلة الصحيحة.'),
            _lv(3, 'Competent', 'كفء', 'Has worked in the area; can challenge management on it.', 'عمل في هذا المجال؛ يستطيع مناقشة الإدارة فيه.'),
            _lv(4, 'Advanced', 'متقدم', 'Senior role or certification in the area; leads board discussion on it.', 'وظيفة قيادية أو شهادة في المجال؛ يقود نقاش المجلس فيه.'),
            _lv(5, 'Expert', 'خبير', 'Recognised expert (e.g. former CRO for risk, chartered accountant for audit).', 'خبير معترف به (مثل رئيس مخاطر سابق للمخاطر، محاسب قانوني للمراجعة).'),
        ]},
    # ------------------------------------------------------------------ ESG / carbon
    'esg.maturity': {
        'module': 'esg', 'title_en': 'ESG indicator maturity (1–5)', 'title_ar': 'نضج مؤشر الاستدامة (1–5)',
        'where_en': 'ESG — scoring of each indicator', 'where_ar': 'الاستدامة — تقييم كل مؤشر',
        'how_en': 'Score the management of the topic, not the size of the number. Each level needs the evidence of all levels below it. Leave blank (not 1) when the indicator does not apply.',
        'how_ar': 'قيّم إدارة الموضوع وليس حجم الرقم. كل مستوى يتطلب أدلة المستويات الأدنى منه. اتركه فارغاً (وليس 1) إذا لم ينطبق المؤشر.',
        'levels': [
            _lv(1, 'Not started', 'لم يبدأ', 'No data, owner or policy for the topic.', 'لا بيانات ولا مسؤول ولا سياسة للموضوع.'),
            _lv(2, 'Basic / ad-hoc', 'أساسي / غير منتظم', 'Some data collected once or on request; no owner or method.', 'بيانات جُمعت مرة أو عند الطلب؛ لا مسؤول ولا منهجية.'),
            _lv(3, 'Developing', 'قيد التطوير', 'Owner named, method documented, data collected yearly for the FRA template.', 'مسؤول محدد، منهجية موثقة، بيانات تُجمع سنوياً لنموذج الهيئة.'),
            _lv(4, 'Managed', 'مُدار', 'Target set and approved, data reviewed (second line or verifier), progress reported to the board.', 'هدف محدد ومعتمد، بيانات مُراجعة (خط ثانٍ أو جهة تحقق)، التقدم يُرفع للمجلس.'),
            _lv(5, 'Optimized', 'مُحسَّن', 'Integrated into strategy, pricing or credit decisions; externally assured; improving year on year.', 'مدمج في الاستراتيجية أو التسعير أو قرارات الائتمان؛ مؤكد خارجياً؛ يتحسن سنوياً.'),
        ]},
    'esg.materiality': {
        'module': 'esg', 'title_en': 'Materiality — stakeholder importance and business impact (1–5)', 'title_ar': 'الأهمية النسبية — أهمية أصحاب المصلحة والأثر على الأعمال (1–5)',
        'where_en': 'ESG — materiality assessment (double materiality)', 'where_ar': 'الاستدامة — تقييم الأهمية النسبية (الأهمية المزدوجة)',
        'how_en': 'Score each topic twice: how much stakeholders (customers, staff, regulator, investors, community) care and are affected (impact materiality), and how much the topic can change the company\'s cash flows, cost of capital or licence (financial materiality). Topics above 3 on both axes (top-right of the matrix) are the priority material topics; a topic at 4–5 on either axis is reviewed for disclosure.',
        'how_ar': 'قيّم كل موضوع مرتين: مدى اهتمام أصحاب المصلحة (العملاء، العاملون، الجهة الرقابية، المستثمرون، المجتمع) وتأثرهم (الأهمية من حيث الأثر)، ومدى قدرة الموضوع على تغيير التدفقات النقدية أو تكلفة التمويل أو الترخيص (الأهمية المالية). الموضوعات فوق 3 على المحورين (الربع الأعلى الأيمن في المصفوفة) هي الموضوعات الجوهرية ذات الأولوية، وأي موضوع يحصل على 4–5 في محور واحد يُراجع للإفصاح.',
        'levels': [
            _lv(1, 'Very low', 'منخفض جداً', 'Rarely raised; no measurable effect.', 'نادراً ما يُثار؛ لا أثر قابل للقياس.'),
            _lv(2, 'Low', 'منخفض', 'Raised occasionally; effect limited to one area.', 'يُثار أحياناً؛ أثر محدود بمجال واحد.'),
            _lv(3, 'Medium', 'متوسط', 'Regularly raised by one stakeholder group; moderate financial effect possible.', 'تثيره مجموعة من أصحاب المصلحة بانتظام؛ أثر مالي متوسط محتمل.'),
            _lv(4, 'High', 'مرتفع', 'Raised by several groups or required by the regulator; clear financial effect within 3 years.', 'تثيره عدة مجموعات أو تتطلبه الجهة الرقابية؛ أثر مالي واضح خلال 3 سنوات.'),
            _lv(5, 'Very high', 'مرتفع جداً', 'Core to the business model or licence; significant effect already visible.', 'جوهري لنموذج الأعمال أو الترخيص؛ أثر كبير ظاهر بالفعل.'),
        ]},
    'carbon.pcaf': {
        'module': 'carbon', 'title_en': 'Financed emissions data quality — PCAF score (1–5, 1 = best)', 'title_ar': 'جودة بيانات الانبعاثات الممولة — درجة PCAF (1–5، 1 = الأفضل)',
        'where_en': 'Carbon — financed emissions (Scope 3, category 15)', 'where_ar': 'الكربون — الانبعاثات الممولة (النطاق 3، الفئة 15)',
        'how_en': 'Follows the PCAF Global GHG Accounting & Reporting Standard. Use the best score your data supports for each exposure; report the weighted average and improve it year on year.',
        'how_ar': 'وفق معيار PCAF العالمي لحساب انبعاثات غازات الاحتباس الحراري والإفصاح عنها. استخدم أفضل درجة تدعمها بياناتك لكل تمويل؛ أفصح عن المتوسط المرجح وحسّنه سنوياً.',
        'levels': [
            _lv(1, 'Verified emissions', 'انبعاثات موثقة', 'Client\'s reported emissions, verified by a third party.', 'انبعاثات معلنة من العميل ومُتحقق منها من طرف ثالث.'),
            _lv(2, 'Reported, unverified', 'معلنة غير موثقة', 'Client\'s reported emissions, not verified; or physical activity data with specific factors.', 'انبعاثات معلنة من العميل غير موثقة؛ أو بيانات نشاط فعلية بمعاملات محددة.'),
            _lv(3, 'Physical activity based', 'مبنية على النشاط الفعلي', 'Estimated from the client\'s physical activity (energy use, production) with average factors.', 'مقدرة من النشاط الفعلي للعميل (استهلاك الطاقة، الإنتاج) بمعاملات متوسطة.'),
            _lv(4, 'Revenue based', 'مبنية على الإيرادات', 'Estimated from the client\'s revenue and sector emission factors.', 'مقدرة من إيرادات العميل ومعاملات انبعاث القطاع.'),
            _lv(5, 'Asset / sector average', 'متوسط القطاع/الأصل', 'Estimated from the outstanding amount and sector averages only.', 'مقدرة من الرصيد القائم ومتوسطات القطاع فقط.'),
        ]},
    'carbon.activity_quality': {
        'module': 'carbon', 'title_en': 'Activity data quality (Scope 1 & 2)', 'title_ar': 'جودة بيانات النشاط (النطاقان 1 و2)',
        'where_en': 'Carbon — activity entries and data-quality page', 'where_ar': 'الكربون — قيود النشاط وصفحة جودة البيانات',
        'how_en': 'For every entry record its source in the notes and attach the bill or invoice as evidence. The verifier samples from entries with evidence; estimated entries must state the method. Aim for at least 90% of Scope 1+2 tCO2e from measured data before FRA verification.',
        'how_ar': 'لكل قيد سجّل مصدره في الملاحظات وأرفق الفاتورة كدليل. جهة التحقق تأخذ عينات من القيود المدعومة بالأدلة؛ القيود المقدرة يجب أن تذكر طريقة التقدير. الهدف: 90% على الأقل من انبعاثات النطاقين 1 و2 من بيانات مقاسة قبل التحقق المطلوب من الهيئة.',
        'levels': [
            _lv('measured', 'Measured', 'مقاس', 'Meter reading, utility bill or fuel invoice for the exact period and site.', 'قراءة عداد أو فاتورة مرافق أو فاتورة وقود للفترة والموقع بالضبط.'),
            _lv('calculated', 'Calculated', 'محسوب', 'Derived from measured data of another period/site (e.g. split of a shared bill by floor area).', 'مشتق من بيانات مقاسة لفترة/موقع آخر (مثل تقسيم فاتورة مشتركة حسب المساحة).'),
            _lv('estimated', 'Estimated', 'مقدَّر', 'Benchmark or average (e.g. kWh per m² for a missing month). Must be replaced when the bill arrives.', 'قيمة مرجعية أو متوسط (مثل كيلووات ساعة لكل م² لشهر مفقود). يجب استبدالها عند وصول الفاتورة.'),
        ]},
    # ------------------------------------------------------------------ cyber / audit / privacy / kyc
    'cyber.maturity': {
        'module': 'cyber', 'title_en': 'Cyber maturity (0–5)', 'title_ar': 'نضج الأمن السيبراني (0–5)',
        'where_en': 'Cyber resilience — maturity assessment per requirement (current and target level)', 'where_ar': 'المرونة السيبرانية — تقييم النضج لكل متطلب (المستوى الحالي والمستهدف)',
        'how_en': 'CMMI-style scale used by most cyber frameworks. Score the weakest site/system, not the best. Target level comes from the risk appetite and the regulator\'s minimum.',
        'how_ar': 'مقياس على نمط CMMI تستخدمه معظم أطر الأمن السيبراني. قيّم أضعف موقع/نظام وليس أفضلها. المستوى المستهدف يُحدد من الرغبة في المخاطر والحد الأدنى الرقابي.',
        'levels': [
            _lv(0, 'Non-existent', 'غير موجود', 'Control absent.', 'الضابط غير موجود.'),
            _lv(1, 'Initial', 'مبدئي', 'Done ad hoc, depends on individuals; no documentation.', 'يُنفذ بشكل عشوائي ويعتمد على أفراد؛ لا توثيق.'),
            _lv(2, 'Repeatable', 'قابل للتكرار', 'Done regularly by the team but not formally documented or approved.', 'يُنفذ بانتظام من الفريق لكن غير موثق أو معتمد رسمياً.'),
            _lv(3, 'Defined', 'مُعرَّف', 'Documented, approved procedure applied across the organisation.', 'إجراء موثق ومعتمد ومطبق في كل المؤسسة.'),
            _lv(4, 'Managed', 'مُدار', 'Measured with metrics/KRIs and tested (internal audit, pentest).', 'مُقاس بمؤشرات ومختبر (مراجعة داخلية، اختبار اختراق).'),
            _lv(5, 'Optimized', 'مُحسَّن', 'Automated where possible and continuously improved from incidents and tests.', 'مؤتمت حيثما أمكن ويتحسن باستمرار من الحوادث والاختبارات.'),
        ]},
    'audit.finding_rating': {
        'module': 'internal_audit', 'title_en': 'Audit finding rating', 'title_ar': 'تصنيف ملاحظة المراجعة',
        'where_en': 'Internal audit — findings', 'where_ar': 'المراجعة الداخلية — الملاحظات',
        'how_en': 'Rate on the risk the gap leaves open (likelihood × impact using the risk guides), not on how easy it is to fix. The rating drives the due date and committee reporting.',
        'how_ar': 'يُصنف حسب الخطر الذي تتركه الفجوة مفتوحاً (الاحتمالية × الأثر وفق أدلة المخاطر) وليس حسب سهولة الإصلاح. التصنيف يحدد موعد المعالجة والرفع للجنة.',
        'levels': [
            _lv('CRITICAL', 'Critical', 'حرج', 'Breach of law/licence condition or loss/fraud occurring; fix within 30 days; immediate report to the audit committee.', 'مخالفة للقانون أو شروط الترخيص أو خسارة/احتيال قائم؛ المعالجة خلال 30 يوماً؛ رفع فوري للجنة المراجعة.'),
            _lv('HIGH', 'High', 'مرتفع', 'Key control missing or failing; regulatory finding likely; fix within 60–90 days.', 'ضابط رئيسي غائب أو فاشل؛ ملاحظة رقابية مرجحة؛ المعالجة خلال 60–90 يوماً.'),
            _lv('MEDIUM', 'Medium', 'متوسط', 'Control weakness with a compensating control; fix within 6 months.', 'ضعف في ضابط مع وجود ضابط تعويضي؛ المعالجة خلال 6 أشهر.'),
            _lv('LOW', 'Low', 'منخفض', 'Improvement opportunity, documentation or efficiency; fix at management\'s discretion within 12 months.', 'فرصة تحسين أو توثيق أو كفاءة؛ المعالجة وفق تقدير الإدارة خلال 12 شهراً.'),
        ]},
    'privacy.dpia_risk': {
        'module': 'pdpl', 'title_en': 'DPIA risk level', 'title_ar': 'مستوى خطر تقييم أثر حماية البيانات',
        'where_en': 'Data protection — DPIAs', 'where_ar': 'حماية البيانات — تقييمات الأثر',
        'how_en': 'Consider the data (sensitive, biometric, financial, children), the scale, new technology and transfers outside Egypt under PDPL 151/2020.',
        'how_ar': 'ضع في الاعتبار نوع البيانات (حساسة، بيومترية، مالية، أطفال) والحجم والتقنيات الجديدة والنقل خارج مصر وفق قانون حماية البيانات الشخصية 151 لسنة 2020.',
        'levels': [
            _lv('low', 'Low', 'منخفض', 'Limited personal data, no sensitive data, internal processing only.', 'بيانات شخصية محدودة، لا بيانات حساسة، معالجة داخلية فقط.'),
            _lv('medium', 'Medium', 'متوسط', 'Financial or large-volume data, or a processor involved; standard safeguards suffice.', 'بيانات مالية أو بحجم كبير، أو وجود معالج بيانات؛ الضمانات المعتادة كافية.'),
            _lv('high', 'High', 'مرتفع', 'Sensitive/biometric data, profiling, cross-border transfer or new technology; DPO sign-off and possibly a licence/permit from the Data Protection Center needed.', 'بيانات حساسة/بيومترية، تنميط، نقل عبر الحدود أو تقنية جديدة؛ يتطلب موافقة مسؤول حماية البيانات وربما ترخيص/تصريح من مركز حماية البيانات.'),
        ]},
    'kyc.risk_band': {
        'module': 'aml', 'title_en': 'Customer risk rating (KYC)', 'title_ar': 'تصنيف مخاطر العميل (اعرف عميلك)',
        'where_en': 'AML/KYC — customer and merchant risk rating', 'where_ar': 'مكافحة غسل الأموال/اعرف عميلك — تصنيف مخاطر العملاء والتجار',
        'how_en': 'The score is calculated by the risk model (AML/KYC > Risk model: factors and weights set by the company) and mapped to a band. Overrides need a reason and approval; PEPs and high-risk countries are high by rule.',
        'how_ar': 'الدرجة تُحسب بنموذج المخاطر (مكافحة غسل الأموال/اعرف عميلك > نموذج المخاطر: العوامل والأوزان تحددها الشركة) وتُحوَّل إلى فئة. أي تعديل يدوي يحتاج سبباً وموافقة؛ الأشخاص المعرضون سياسياً والدول عالية المخاطر تُصنف مرتفعة بالقاعدة.',
        'levels': [
            _lv('low', 'Low', 'منخفض', 'Simplified/standard due diligence; review every 3 years (or per policy).', 'عناية واجبة مبسطة/عادية؛ مراجعة كل 3 سنوات (أو وفق السياسة).'),
            _lv('medium', 'Medium', 'متوسط', 'Standard due diligence plus source of funds; review every 2 years.', 'عناية واجبة عادية مع مصدر الأموال؛ مراجعة كل سنتين.'),
            _lv('high', 'High', 'مرتفع', 'Enhanced due diligence, senior management approval, enhanced monitoring; review yearly.', 'عناية واجبة معززة، موافقة الإدارة العليا، مراقبة معززة؛ مراجعة سنوية.'),
        ]},
}


def guide(key):
    return GUIDES.get(key)


def all_guides():
    order = ['risk_management', 'governance', 'aml', 'esg', 'carbon', 'cyber', 'internal_audit', 'pdpl']
    return sorted(GUIDES.items(), key=lambda kv: (order.index(kv[1]['module']) if kv[1]['module'] in order else 99, kv[0]))


def localized(g, field, lang):
    if not g:
        return ''
    return g.get(f'{field}_ar') if lang == 'ar' and g.get(f'{field}_ar') else g.get(f'{field}_en', '')
