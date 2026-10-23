-- Talent pool: ready-made e-mails staff send to an applicant from the system
-- (placeholders {first_name} {full_name} {ref} {org} {area} {sender}).
BEGIN;
CREATE TABLE IF NOT EXISTS talent_email_templates (
    id          SERIAL PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    name_en     TEXT NOT NULL,
    name_ar     TEXT,
    subject_en  TEXT NOT NULL,
    subject_ar  TEXT,
    body_en     TEXT NOT NULL,
    body_ar     TEXT,
    set_status  TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order  INTEGER NOT NULL DEFAULT 100,
    updated_by  INTEGER,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

INSERT INTO talent_email_templates (code, name_en, name_ar, subject_en, subject_ar, body_en, body_ar, set_status, sort_order) VALUES
('call_request', 'Invite to a short call', 'دعوة لمكالمة قصيرة',
 'Your application to {org} — a short call', 'طلبك لدى {org} — مكالمة قصيرة',
 E'Dear {first_name},\n\nThank you for applying to join our consultants network (reference {ref}). Your experience in {area} is relevant to work we have coming up, and we would like to arrange a short call of about 20 minutes.\n\nPlease reply with two or three times that suit you over the next few days, and the best number to reach you on.\n\nKind regards,\n{sender}\n{org}',
 E'الأستاذ/ة {first_name}،\n\nشكرًا لتقديمك للانضمام إلى شبكة الاستشاريين لدينا (الرقم المرجعي {ref}). خبرتك في مجال {area} مناسبة لأعمال قادمة لدينا، ونود ترتيب مكالمة قصيرة مدتها نحو 20 دقيقة.\n\nيُرجى الرد بموعدين أو ثلاثة تناسبك خلال الأيام القادمة، مع رقم الهاتف الأنسب للتواصل.\n\nمع خالص التحية،\n{sender}\n{org}',
 'contacted', 10),
('shortlisted', 'Shortlisted — next steps', 'ضمن القائمة المختصرة — الخطوات القادمة',
 'Your application to {org} — shortlisted', 'طلبك لدى {org} — ضمن القائمة المختصرة',
 E'Dear {first_name},\n\nWe are pleased to tell you that your profile (reference {ref}) has been shortlisted for upcoming {area} work. We will be in touch with the scope and timing as soon as the engagement is confirmed.\n\nAs a reminder, any engagement is under a non-disclosure agreement and a consulting contract agreed with you in advance.\n\nKind regards,\n{sender}\n{org}',
 E'الأستاذ/ة {first_name}،\n\nيسعدنا إبلاغك بأن ملفك (الرقم المرجعي {ref}) أصبح ضمن القائمة المختصرة لأعمال قادمة في مجال {area}. سنتواصل معك بالنطاق والتوقيت فور تأكيد التكليف.\n\nللتذكير، يتم أي تعاون بموجب اتفاقية سرية وعقد استشارات يُتفق عليهما معك مسبقًا.\n\nمع خالص التحية،\n{sender}\n{org}',
 'shortlisted', 20),
('more_info', 'Ask for an updated CV / more details', 'طلب سيرة ذاتية محدثة / تفاصيل إضافية',
 'Your application to {org} — a few more details', 'طلبك لدى {org} — بعض التفاصيل الإضافية',
 E'Dear {first_name},\n\nThank you for your application (reference {ref}). To assess it properly, could you please reply with your updated CV and a short note on the projects you have led in {area} (sector, size and your role)?\n\nKind regards,\n{sender}\n{org}',
 E'الأستاذ/ة {first_name}،\n\nشكرًا لتقديمك (الرقم المرجعي {ref}). لتقييم طلبك بشكل دقيق، يُرجى الرد بسيرتك الذاتية المحدثة ونبذة قصيرة عن المشروعات التي قُدتها في مجال {area} (القطاع وحجم المشروع ودورك).\n\nمع خالص التحية،\n{sender}\n{org}',
 'contacted', 30),
('engagement', 'Engagement — NDA and contract', 'التكليف — اتفاقية السرية والعقد',
 'Engagement with {org} — NDA and consulting contract', 'التعاون مع {org} — اتفاقية السرية وعقد الاستشارات',
 E'Dear {first_name},\n\nFollowing our discussion, we would like to engage you on a {area} assignment. The next step is to sign a non-disclosure agreement, followed by a consulting contract that sets out the scope, timeline and fee.\n\nWe will send both documents shortly. Please confirm the full name and address that should appear on them.\n\nKind regards,\n{sender}\n{org}',
 E'الأستاذ/ة {first_name}،\n\nبناءً على حديثنا، نود التعاون معك في تكليف بمجال {area}. الخطوة التالية هي توقيع اتفاقية سرية، يليها عقد استشارات يحدد النطاق والمدة والأتعاب.\n\nسنرسل لك المستندين قريبًا. يُرجى تأكيد الاسم الكامل والعنوان اللذين يُكتبان فيهما.\n\nمع خالص التحية،\n{sender}\n{org}',
 'engaged', 40),
('not_now', 'Thank you — not suitable now', 'شكرًا — غير مناسب حاليًا',
 'Your application to {org}', 'طلبك لدى {org}',
 E'Dear {first_name},\n\nThank you for your interest in joining our consultants network and for the time you took to apply (reference {ref}).\n\nAfter reviewing your profile, we do not have an assignment that matches it at the moment. We will keep your details on file and contact you if a suitable opportunity comes up. You can ask us at any time to update or delete your details by replying to this e-mail.\n\nWe wish you every success.\n\nKind regards,\n{sender}\n{org}',
 E'الأستاذ/ة {first_name}،\n\nشكرًا لاهتمامك بالانضمام إلى شبكة الاستشاريين لدينا وللوقت الذي خصصته للتقديم (الرقم المرجعي {ref}).\n\nبعد مراجعة ملفك، لا يتوفر لدينا حاليًا تكليف يناسبه. سنحتفظ ببياناتك ونتواصل معك عند توفر فرصة مناسبة، ويمكنك في أي وقت طلب تحديث بياناتك أو حذفها بالرد على هذه الرسالة.\n\nنتمنى لك كل التوفيق.\n\nمع خالص التحية،\n{sender}\n{org}',
 'rejected', 50)
ON CONFLICT (code) DO NOTHING;

GRANT SELECT, INSERT, UPDATE, DELETE ON talent_email_templates TO complynex;
GRANT USAGE, SELECT ON SEQUENCE talent_email_templates_id_seq TO complynex;
COMMIT;
