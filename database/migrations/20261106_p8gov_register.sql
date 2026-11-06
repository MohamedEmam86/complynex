-- P8 governance: configurable committee types, member capacities, meeting rules,
-- full board-meeting record (body / kind / sequence / quorum / secretary / tellers /
-- conflicts / signatures / filing), resolutions register (numbering, per-member votes,
-- outcome, follow-up, typed links), search synonyms and composition rule sets.
-- Additive only: new tables, new nullable columns, reference rows inserted when missing.
BEGIN;

-- ------------------------------------------------------------------ boards / entities
CREATE TABLE IF NOT EXISTS gov_entities (
    id SERIAL PRIMARY KEY,
    name_en TEXT NOT NULL,
    name_ar TEXT,
    short_code VARCHAR(20),
    legal_form TEXT,
    rule_codes TEXT,                 -- comma-separated gov_composition_rules codes applied to this board
    notes TEXT,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_sample BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    updated_at TIMESTAMP, updated_by INTEGER
);
-- The organisation that owns the existing records (entity_id NULL = this one).
INSERT INTO gov_entities (name_en, name_ar, is_default, sort_order)
SELECT 'This organisation', 'هذه المؤسسة', TRUE, 0
WHERE NOT EXISTS (SELECT 1 FROM gov_entities WHERE is_default);

-- ------------------------------------------------------------------ meeting rules (quorum / majority / filing)
CREATE TABLE IF NOT EXISTS gov_meeting_rules (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) NOT NULL UNIQUE,
    name_en TEXT NOT NULL,
    name_ar TEXT,
    applies_to VARCHAR(12) NOT NULL DEFAULT 'ANY',      -- BOARD / COMMITTEE / OGM / EGM / ANY
    quorum_basis VARCHAR(10) NOT NULL DEFAULT 'MEMBERS', -- MEMBERS (head count) / CAPITAL (% of capital represented)
    quorum_type VARCHAR(10) NOT NULL DEFAULT 'MAJORITY', -- MAJORITY = more than the fraction; AT_LEAST = the fraction or more
    quorum_fraction NUMERIC(6,4) NOT NULL DEFAULT 0.5,
    quorum_min INTEGER,
    second_call_type VARCHAR(10),                        -- NULL = second call needs the same quorum
    second_call_fraction NUMERIC(6,4),
    second_call_min INTEGER,
    count_proxies BOOLEAN NOT NULL DEFAULT TRUE,
    count_remote BOOLEAN NOT NULL DEFAULT TRUE,
    majority_rule VARCHAR(16) NOT NULL DEFAULT 'SIMPLE_PRESENT', -- SIMPLE_CAST / SIMPLE_PRESENT / TWO_THIRDS / THREE_QUARTERS / UNANIMOUS
    chair_casting_vote BOOLEAN NOT NULL DEFAULT TRUE,
    circulation_requires_all BOOLEAN NOT NULL DEFAULT TRUE,
    notice_days INTEGER,
    filing_days INTEGER,
    filing_authority TEXT,
    legal_ref TEXT,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_sample BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    updated_at TIMESTAMP, updated_by INTEGER
);
INSERT INTO gov_meeting_rules (code, name_en, name_ar, applies_to, quorum_basis, quorum_type, quorum_fraction, quorum_min,
        majority_rule, chair_casting_vote, notice_days, filing_days, filing_authority, legal_ref, sort_order) VALUES
 ('BOARD_DEFAULT', 'Board - majority of members, never fewer than 3', 'مجلس الإدارة - أغلبية الأعضاء وبحد أدنى 3',
  'BOARD', 'MEMBERS', 'MAJORITY', 0.5, 3, 'SIMPLE_PRESENT', TRUE, NULL, NULL, NULL,
  'Companies Law 159/1981 Arts 77, 80; majority and casting vote per the articles of association', 10),
 ('BOARD_FILING_10D', 'Board - majority of members (min 3), minutes filed within 10 days',
  'مجلس الإدارة - أغلبية الأعضاء (3 على الأقل) وإرسال المحضر خلال 10 أيام',
  'BOARD', 'MEMBERS', 'MAJORITY', 0.5, 3, 'SIMPLE_PRESENT', TRUE, NULL, 10, 'FRA',
  'Companies Law 159/1981 Arts 77, 80; FRA Decree 100/2020 (minutes to FRA within 10 days)', 20),
 ('COMMITTEE_HALF', 'Committee - half of members', 'لجنة - نصف الأعضاء',
  'COMMITTEE', 'MEMBERS', 'AT_LEAST', 0.5, 2, 'SIMPLE_PRESENT', TRUE, NULL, NULL, NULL,
  'Egyptian Code of Corporate Governance 2016 (committee quorum half, chair casting vote)', 30),
 ('OGM_DEFAULT', 'Ordinary general assembly - 25% of capital (second meeting: any)',
  'الجمعية العامة العادية - 25% من رأس المال (الاجتماع الثاني: أي عدد)',
  'OGM', 'CAPITAL', 'AT_LEAST', 0.25, NULL, 'SIMPLE_PRESENT', FALSE, 21, 30, 'GAFI',
  'Companies Law 159/1981 Arts 61, 67, 75', 40),
 ('EGM_DEFAULT', 'Extraordinary general assembly - 50% of capital (second meeting 25%), two-thirds majority',
  'الجمعية العامة غير العادية - 50% من رأس المال (الاجتماع الثاني 25%) وأغلبية الثلثين',
  'EGM', 'CAPITAL', 'AT_LEAST', 0.5, NULL, 'TWO_THIRDS', FALSE, 21, 30, 'GAFI',
  'Companies Law 159/1981 Arts 70, 75 (3/4 for capital, dissolution, merger)', 50)
ON CONFLICT (code) DO NOTHING;
UPDATE gov_meeting_rules SET second_call_type = 'AT_LEAST', second_call_fraction = 0
 WHERE code = 'OGM_DEFAULT' AND second_call_type IS NULL;
UPDATE gov_meeting_rules SET second_call_type = 'AT_LEAST', second_call_fraction = 0.25
 WHERE code = 'EGM_DEFAULT' AND second_call_type IS NULL;

-- ------------------------------------------------------------------ committee types
CREATE TABLE IF NOT EXISTS gov_committee_types (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) NOT NULL UNIQUE,
    name_en TEXT NOT NULL,
    name_ar TEXT,
    description TEXT,
    min_members INTEGER,
    max_members INTEGER,
    min_independent_members INTEGER,
    independent_majority BOOLEAN NOT NULL DEFAULT FALSE,
    independent_chair BOOLEAN NOT NULL DEFAULT FALSE,
    non_executive_chair BOOLEAN NOT NULL DEFAULT FALSE,
    requires_financial_expert BOOLEAN NOT NULL DEFAULT FALSE,
    min_meetings_per_year INTEGER,
    meeting_rule_code VARCHAR(40),
    res_prefix VARCHAR(12),
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_sample BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    updated_at TIMESTAMP, updated_by INTEGER
);
INSERT INTO gov_committee_types (code, name_en, name_ar, min_members, independent_chair, non_executive_chair,
        requires_financial_expert, min_meetings_per_year, meeting_rule_code, res_prefix, sort_order) VALUES
 ('AUDIT', 'Audit Committee', 'لجنة المراجعة', 3, TRUE, TRUE, TRUE, 4, 'COMMITTEE_HALF', 'AUD', 10),
 ('RISK', 'Risk Committee', 'لجنة المخاطر', 3, FALSE, TRUE, FALSE, 4, 'COMMITTEE_HALF', 'RSK', 20),
 ('GOVERNANCE', 'Governance Committee', 'لجنة الحوكمة', 3, FALSE, TRUE, FALSE, NULL, 'COMMITTEE_HALF', 'GOV', 30),
 ('NOMREM', 'Nomination & Remuneration Committee', 'لجنة الترشيحات والمكافآت', 3, TRUE, TRUE, FALSE, NULL, 'COMMITTEE_HALF', 'NRC', 40),
 ('COMPLIANCE', 'Compliance & AML Committee', 'لجنة الالتزام ومكافحة غسل الأموال', 3, FALSE, TRUE, FALSE, NULL, 'COMMITTEE_HALF', 'CMP', 50),
 ('IT', 'IT & Cyber Security Committee', 'لجنة تكنولوجيا المعلومات والأمن السيبراني', 3, FALSE, FALSE, FALSE, NULL, 'COMMITTEE_HALF', 'ITC', 60),
 ('CREDIT', 'Credit Committee', 'لجنة الائتمان', 3, FALSE, FALSE, FALSE, NULL, 'COMMITTEE_HALF', 'CRD', 70),
 ('EXECUTIVE', 'Executive Committee', 'اللجنة التنفيذية', 3, FALSE, FALSE, FALSE, NULL, 'COMMITTEE_HALF', 'EXC', 80),
 ('INVESTMENT', 'Investment Committee', 'لجنة الاستثمار', 3, FALSE, FALSE, FALSE, NULL, 'COMMITTEE_HALF', 'INV', 90),
 ('OTHER', 'Other committee', 'لجنة أخرى', NULL, FALSE, FALSE, FALSE, NULL, 'COMMITTEE_HALF', 'COM', 999)
ON CONFLICT (code) DO NOTHING;

ALTER TABLE board_committees ADD COLUMN IF NOT EXISTS independent_majority INTEGER;
ALTER TABLE board_committees ADD COLUMN IF NOT EXISTS independent_chair INTEGER;
ALTER TABLE board_committees ADD COLUMN IF NOT EXISTS non_executive_chair INTEGER;
ALTER TABLE board_committees ADD COLUMN IF NOT EXISTS meeting_rule_id INTEGER;
ALTER TABLE board_committees ADD COLUMN IF NOT EXISTS res_prefix VARCHAR(12);
ALTER TABLE board_committees ADD COLUMN IF NOT EXISTS entity_id INTEGER;
ALTER TABLE board_committees ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE board_committees ADD COLUMN IF NOT EXISTS is_sample BOOLEAN NOT NULL DEFAULT FALSE;

-- ------------------------------------------------------------------ member capacities (صفة العضو)
CREATE TABLE IF NOT EXISTS gov_capacity_dimensions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) NOT NULL UNIQUE,
    name_en TEXT NOT NULL,
    name_ar TEXT,
    multi_select BOOLEAN NOT NULL DEFAULT FALSE,   -- several options of this dimension at the same time
    applies_to VARCHAR(12) NOT NULL DEFAULT 'MEMBER', -- MEMBER / NON_MEMBER
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    updated_at TIMESTAMP, updated_by INTEGER
);
INSERT INTO gov_capacity_dimensions (code, name_en, name_ar, multi_select, applies_to, sort_order, is_system) VALUES
 ('BOARD_ROLE', 'Board role', 'المنصب في المجلس', FALSE, 'MEMBER', 10, TRUE),
 ('EXEC_STATUS', 'Executive status', 'الصفة التنفيذية', FALSE, 'MEMBER', 20, TRUE),
 ('INDEPENDENCE', 'Independence', 'الاستقلالية', FALSE, 'MEMBER', 30, TRUE),
 ('REPRESENTS', 'Represents', 'يمثل', FALSE, 'MEMBER', 40, TRUE),
 ('SEAT_BASIS', 'How the seat was filled', 'طريقة شغل المقعد', FALSE, 'MEMBER', 50, TRUE),
 ('ADDITIONAL', 'Additional capacities', 'صفات إضافية', TRUE, 'MEMBER', 60, TRUE),
 ('NON_MEMBER_ROLE', 'Non-member roles', 'أدوار غير الأعضاء', TRUE, 'NON_MEMBER', 70, TRUE)
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS gov_capacity_options (
    id SERIAL PRIMARY KEY,
    dimension_id INTEGER NOT NULL REFERENCES gov_capacity_dimensions(id) ON DELETE CASCADE,
    code VARCHAR(40) NOT NULL,
    name_en TEXT NOT NULL,
    name_ar TEXT,
    flag VARCHAR(30),          -- meaning used by the checks: chair, vice_chair, md, ceo, chair_md, member,
                               -- executive, non_executive, independent, non_independent, legal_person,
                               -- employees, secretary, teller, gm, auditor, observer, external_member ...
    is_voting BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    is_sample BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    updated_at TIMESTAMP, updated_by INTEGER,
    UNIQUE (dimension_id, code)
);
INSERT INTO gov_capacity_options (dimension_id, code, name_en, name_ar, flag, is_voting, sort_order, is_system)
SELECT d.id, v.code, v.name_en, v.name_ar, v.flag, v.voting, v.so, TRUE
FROM (VALUES
 ('BOARD_ROLE', 'CHAIR', 'Chair of the board', 'رئيس مجلس الإدارة', 'chair', TRUE, 10),
 ('BOARD_ROLE', 'VICE_CHAIR', 'Vice-chair', 'نائب رئيس مجلس الإدارة', 'vice_chair', TRUE, 20),
 ('BOARD_ROLE', 'MD', 'Managing director', 'العضو المنتدب', 'md', TRUE, 30),
 ('BOARD_ROLE', 'CHAIR_MD', 'Chair and managing director', 'رئيس مجلس الإدارة والعضو المنتدب', 'chair_md', TRUE, 40),
 ('BOARD_ROLE', 'CEO', 'Chief executive officer', 'الرئيس التنفيذي', 'ceo', TRUE, 50),
 ('BOARD_ROLE', 'MEMBER', 'Board member', 'عضو مجلس الإدارة', 'member', TRUE, 60),
 ('EXEC_STATUS', 'EXECUTIVE', 'Executive', 'تنفيذي', 'executive', TRUE, 10),
 ('EXEC_STATUS', 'NON_EXECUTIVE', 'Non-executive', 'غير تنفيذي', 'non_executive', TRUE, 20),
 ('INDEPENDENCE', 'INDEPENDENT', 'Independent', 'مستقل', 'independent', TRUE, 10),
 ('INDEPENDENCE', 'NON_INDEPENDENT', 'Non-independent', 'غير مستقل', 'non_independent', TRUE, 20),
 ('REPRESENTS', 'SELF', 'In a personal capacity', 'بصفته الشخصية', 'self', TRUE, 10),
 ('REPRESENTS', 'LEGAL_PERSON', 'Representative of a legal person', 'ممثل لشخص اعتباري', 'legal_person', TRUE, 20),
 ('REPRESENTS', 'SHAREHOLDER_BLOCK', 'Representative of a shareholder group', 'ممثل لمجموعة من المساهمين', 'shareholder_block', TRUE, 30),
 ('REPRESENTS', 'EMPLOYEES', 'Employees'' representative', 'ممثل العاملين', 'employees', TRUE, 40),
 ('REPRESENTS', 'PUBLIC_FUNDS', 'Public funds representative', 'ممثل المال العام', 'public_funds', TRUE, 50),
 ('SEAT_BASIS', 'ELECTED', 'Elected', 'منتخب', 'elected', TRUE, 10),
 ('SEAT_BASIS', 'APPOINTED', 'Appointed', 'معيّن', 'appointed', TRUE, 20),
 ('SEAT_BASIS', 'CO_OPTED', 'Co-opted to fill a vacancy', 'معيّن لشغل مقعد شاغر', 'co_opted', TRUE, 30),
 ('SEAT_BASIS', 'ALTERNATE', 'Alternate member', 'عضو احتياطي', 'alternate', TRUE, 40),
 ('SEAT_BASIS', 'EXPERT', 'Expert member', 'عضو من ذوي الخبرة', 'expert', TRUE, 50),
 ('NON_MEMBER_ROLE', 'SECRETARY', 'Board secretary', 'أمين السر', 'secretary', FALSE, 10),
 ('NON_MEMBER_ROLE', 'TELLER', 'Vote teller', 'فارز الأصوات', 'teller', FALSE, 20),
 ('NON_MEMBER_ROLE', 'GM', 'General manager (attends without a vote)', 'المدير العام (يحضر بدون صوت)', 'gm', FALSE, 30),
 ('NON_MEMBER_ROLE', 'EXTERNAL_COMMITTEE', 'External committee member', 'عضو لجنة من خارج المجلس', 'external_member', TRUE, 40),
 ('NON_MEMBER_ROLE', 'INVITEE', 'Invitee / observer', 'مدعو / مراقب', 'observer', FALSE, 50),
 ('NON_MEMBER_ROLE', 'AUDITOR', 'External auditor', 'مراقب الحسابات', 'auditor', FALSE, 60)
) AS v(dim, code, name_en, name_ar, flag, voting, so)
JOIN gov_capacity_dimensions d ON d.code = v.dim
ON CONFLICT (dimension_id, code) DO NOTHING;

CREATE TABLE IF NOT EXISTS gov_member_capacities (
    id SERIAL PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES board_members(id) ON DELETE CASCADE,
    option_id INTEGER NOT NULL REFERENCES gov_capacity_options(id) ON DELETE CASCADE,
    effective_from DATE,
    effective_to DATE,
    represented_entity TEXT,       -- the legal person / shareholder group represented
    note TEXT,
    source VARCHAR(20),            -- 'legacy' for rows derived from the old independent / executive fields
    is_sample BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    ended_at TIMESTAMP, ended_by INTEGER
);
CREATE INDEX IF NOT EXISTS ix_gov_member_capacities_member ON gov_member_capacities (member_id);

ALTER TABLE board_members ADD COLUMN IF NOT EXISTS entity_id INTEGER;
ALTER TABLE board_members ADD COLUMN IF NOT EXISTS gender VARCHAR(10);
ALTER TABLE board_members ADD COLUMN IF NOT EXISTS other_board_seats INTEGER;
ALTER TABLE board_members ADD COLUMN IF NOT EXISTS is_sample BOOLEAN NOT NULL DEFAULT FALSE;

-- Backward compatibility: every existing member gets the capacities its current
-- independent / executive flags mean (only when it has none in that dimension yet).
INSERT INTO gov_member_capacities (member_id, option_id, effective_from, source, note)
SELECT bm.id, o.id,
       CASE WHEN COALESCE(bm.term_start_date, bm.appointment_date) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
            THEN left(COALESCE(bm.term_start_date, bm.appointment_date), 10)::date END,
       'legacy', 'Derived from the independent flag'
FROM board_members bm
JOIN gov_capacity_dimensions d ON d.code = 'INDEPENDENCE'
JOIN gov_capacity_options o ON o.dimension_id = d.id
     AND o.code = CASE WHEN COALESCE(bm.is_independent, 0) = 1 THEN 'INDEPENDENT' ELSE 'NON_INDEPENDENT' END
WHERE NOT EXISTS (SELECT 1 FROM gov_member_capacities mc JOIN gov_capacity_options o2 ON o2.id = mc.option_id
                  WHERE mc.member_id = bm.id AND o2.dimension_id = d.id);
INSERT INTO gov_member_capacities (member_id, option_id, effective_from, source, note)
SELECT bm.id, o.id,
       CASE WHEN COALESCE(bm.term_start_date, bm.appointment_date) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
            THEN left(COALESCE(bm.term_start_date, bm.appointment_date), 10)::date END,
       'legacy', 'Derived from the executive flag'
FROM board_members bm
JOIN gov_capacity_dimensions d ON d.code = 'EXEC_STATUS'
JOIN gov_capacity_options o ON o.dimension_id = d.id
     AND o.code = CASE WHEN COALESCE(bm.is_executive, 0) = 1 THEN 'EXECUTIVE' ELSE 'NON_EXECUTIVE' END
WHERE NOT EXISTS (SELECT 1 FROM gov_member_capacities mc JOIN gov_capacity_options o2 ON o2.id = mc.option_id
                  WHERE mc.member_id = bm.id AND o2.dimension_id = d.id);

-- ------------------------------------------------------------------ officers who are not board members
CREATE TABLE IF NOT EXISTS gov_officers (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    full_name_ar TEXT,
    role_option_id INTEGER REFERENCES gov_capacity_options(id) ON DELETE SET NULL,
    email TEXT,
    user_id INTEGER,
    entity_id INTEGER,
    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_sample BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    updated_at TIMESTAMP, updated_by INTEGER
);

-- ------------------------------------------------------------------ meeting record
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS entity_id INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS body VARCHAR(12);          -- BOARD / COMMITTEE / OGM / EGM
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS meeting_kind VARCHAR(14);  -- ORDINARY / EXTRAORDINARY / CIRCULATION
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS sequence_no INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS end_time TEXT;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS mode VARCHAR(10);          -- IN_PERSON / REMOTE / HYBRID
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS notice_date DATE;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS notice_channel TEXT;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS chair_member_id INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS chair_name TEXT;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS secretary_officer_id INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS meeting_rule_id INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS call_no INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS first_call_at TEXT;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS first_call_present INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS first_call_note TEXT;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS capital_represented_pct NUMERIC(7,3);
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS quorum_required INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS quorum_counted INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS members_total INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS prev_minutes_meeting_id INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS prev_minutes_approved INTEGER;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS minutes_state VARCHAR(10);  -- DRAFT / APPROVED / SIGNED
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS minutes_approved_on DATE;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS chair_signed_at TIMESTAMP;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS chair_signed_name TEXT;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS secretary_signed_at TIMESTAMP;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS secretary_signed_name TEXT;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS filing_authority TEXT;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS filing_due_date DATE;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS filed_on DATE;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS filing_reference TEXT;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS recording_ref TEXT;
ALTER TABLE board_meetings ADD COLUMN IF NOT EXISTS is_sample BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE meeting_attendance ADD COLUMN IF NOT EXISTS proxy_holder_member_id INTEGER;
ALTER TABLE meeting_attendance ADD COLUMN IF NOT EXISTS proxy_document TEXT;
ALTER TABLE meeting_agenda_items ADD COLUMN IF NOT EXISTS objection_note TEXT;

-- meeting roles held by several people (vote tellers ...)
CREATE TABLE IF NOT EXISTS gov_meeting_officers (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES board_meetings(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'TELLER',
    officer_id INTEGER REFERENCES gov_officers(id) ON DELETE CASCADE,
    member_id INTEGER REFERENCES board_members(id) ON DELETE CASCADE,
    name TEXT,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER
);
CREATE INDEX IF NOT EXISTS ix_gov_meeting_officers_meeting ON gov_meeting_officers (meeting_id);

CREATE TABLE IF NOT EXISTS gov_conflict_declarations (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES board_meetings(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES board_members(id) ON DELETE CASCADE,
    agenda_item_id INTEGER,
    resolution_id INTEGER REFERENCES board_decisions(id) ON DELETE CASCADE,
    nature TEXT NOT NULL,
    left_room BOOLEAN NOT NULL DEFAULT FALSE,
    did_not_vote BOOLEAN NOT NULL DEFAULT TRUE,
    ga_informed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER
);
CREATE INDEX IF NOT EXISTS ix_gov_conflicts_member ON gov_conflict_declarations (member_id);

-- ------------------------------------------------------------------ resolutions register
CREATE TABLE IF NOT EXISTS gov_resolution_categories (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) NOT NULL UNIQUE,
    name_en TEXT NOT NULL,
    name_ar TEXT,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_sample BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    updated_at TIMESTAMP, updated_by INTEGER
);
INSERT INTO gov_resolution_categories (code, name_en, name_ar, sort_order) VALUES
 ('BUDGET', 'Budget & financial statements', 'الموازنة والقوائم المالية', 10),
 ('AUDIT', 'External audit & auditors', 'المراجعة الخارجية ومراقبي الحسابات', 20),
 ('FINANCING', 'Borrowing, financing & credit limits', 'الاقتراض والتمويل وحدود الائتمان', 30),
 ('AML_COMPLIANCE', 'Compliance & AML/CFT', 'الالتزام ومكافحة غسل الأموال وتمويل الإرهاب', 40),
 ('RELATED_PARTY', 'Related-party transactions', 'التعاملات مع الأطراف ذات العلاقة', 50),
 ('APPOINTMENTS', 'Appointments & board composition', 'التعيينات وتشكيل المجلس', 60),
 ('POLICIES', 'Policies & procedures', 'السياسات والإجراءات', 70),
 ('GOVERNANCE', 'Governance & committees', 'الحوكمة واللجان', 80),
 ('STRATEGY', 'Strategy & business plan', 'الاستراتيجية وخطة العمل', 90),
 ('RISK', 'Risk management', 'إدارة المخاطر', 100),
 ('REMUNERATION', 'Remuneration & incentives', 'المكافآت والحوافز', 110),
 ('CAPITAL', 'Capital, dividends & shares', 'رأس المال والأرباح والأسهم', 120),
 ('DELEGATION', 'Delegation of authority & signatories', 'تفويض الصلاحيات والتوقيعات', 130),
 ('OTHER', 'Other', 'أخرى', 999)
ON CONFLICT (code) DO NOTHING;

ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS res_no VARCHAR(60);
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS item_no INTEGER;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS agenda_item_id INTEGER;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS category_code VARCHAR(40);
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS tags TEXT;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS outcome VARCHAR(20);  -- APPROVED / REJECTED / DEFERRED / GA_RATIFICATION / RECOMMENDATION
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS majority_rule VARCHAR(16);
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS majority_achieved INTEGER;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS majority_note TEXT;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS conditions TEXT;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS effective_date DATE;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS expiry_date DATE;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS action_owner TEXT;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS action_owner_user_id INTEGER;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS due_date DATE;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS followup_status VARCHAR(14); -- NOT_STARTED / IN_PROGRESS / DONE / NOT_REQUIRED / CANCELLED
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS followup_evidence TEXT;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS followup_updated_at TIMESTAMP;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS followup_updated_by INTEGER;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS search_index JSONB;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS search_norm TEXT;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS search_version INTEGER;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS search_updated_at TIMESTAMP;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS is_sample BOOLEAN NOT NULL DEFAULT FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS ux_board_decisions_res_no ON board_decisions (res_no) WHERE res_no IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_board_decisions_meeting ON board_decisions (meeting_id);

-- Every number ever issued; a number is never issued twice even if a resolution is withdrawn.
CREATE TABLE IF NOT EXISTS gov_resolution_numbers (
    res_no VARCHAR(60) PRIMARY KEY,
    resolution_id INTEGER,
    meeting_id INTEGER,
    issued_at TIMESTAMP DEFAULT NOW(),
    is_sample BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS gov_resolution_votes (
    id SERIAL PRIMARY KEY,
    resolution_id INTEGER NOT NULL REFERENCES board_decisions(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES board_members(id) ON DELETE CASCADE,
    vote VARCHAR(10) NOT NULL,       -- FOR / AGAINST / ABSTAIN / RECUSED / ABSENT
    via_proxy BOOLEAN NOT NULL DEFAULT FALSE,
    dissent_text TEXT,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    UNIQUE (resolution_id, member_id)
);
CREATE INDEX IF NOT EXISTS ix_gov_votes_member ON gov_resolution_votes (member_id);

CREATE TABLE IF NOT EXISTS gov_resolution_links (
    id SERIAL PRIMARY KEY,
    from_resolution_id INTEGER NOT NULL REFERENCES board_decisions(id) ON DELETE CASCADE,
    to_resolution_id INTEGER NOT NULL REFERENCES board_decisions(id) ON DELETE CASCADE,
    link_type VARCHAR(12) NOT NULL,  -- AMENDS / SUPERSEDES / REVOKES / IMPLEMENTS / RATIFIES
    note TEXT,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    UNIQUE (from_resolution_id, to_resolution_id, link_type)
);

-- ------------------------------------------------------------------ search synonyms (configurable)
CREATE TABLE IF NOT EXISTS gov_search_synonyms (
    id SERIAL PRIMARY KEY,
    group_code VARCHAR(40) NOT NULL,
    term TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    UNIQUE (group_code, term)
);
INSERT INTO gov_search_synonyms (group_code, term) VALUES
 ('APPROVE', 'اعتماد'), ('APPROVE', 'موافقة'), ('APPROVE', 'إقرار'), ('APPROVE', 'تصديق'), ('APPROVE', 'approve'),
 ('APPROVE', 'approval'), ('APPROVE', 'adopt'), ('APPROVE', 'endorse'),
 ('APPOINT', 'تعيين'), ('APPOINT', 'اختيار'), ('APPOINT', 'appoint'), ('APPOINT', 'appointment'), ('APPOINT', 'nominate'),
 ('BUDGET', 'ميزانية'), ('BUDGET', 'موازنة'), ('BUDGET', 'موازنة تقديرية'), ('BUDGET', 'budget'), ('BUDGET', 'forecast'),
 ('LOAN', 'قرض'), ('LOAN', 'تمويل'), ('LOAN', 'اقتراض'), ('LOAN', 'تسهيلات'), ('LOAN', 'تسهيل ائتماني'),
 ('LOAN', 'loan'), ('LOAN', 'financing'), ('LOAN', 'borrowing'), ('LOAN', 'facility'), ('LOAN', 'credit line'),
 ('AUDITOR', 'مراقب حسابات'), ('AUDITOR', 'مراقب الحسابات'), ('AUDITOR', 'مراجع خارجي'), ('AUDITOR', 'مدقق'),
 ('AUDITOR', 'auditor'), ('AUDITOR', 'external auditor'),
 ('AML', 'غسل الأموال'), ('AML', 'غسيل الأموال'), ('AML', 'مكافحة غسل الأموال'), ('AML', 'aml'),
 ('AML', 'anti money laundering'), ('AML', 'money laundering'),
 ('CFT', 'تمويل الإرهاب'), ('CFT', 'مكافحة تمويل الإرهاب'), ('CFT', 'terrorist financing'),
 ('CFT', 'terrorism financing'), ('CFT', 'cft'), ('LOAN', 'قروض'), ('LOAN', 'loans'),
 ('POLICY', 'سياسة'), ('POLICY', 'لائحة'), ('POLICY', 'policy'), ('POLICY', 'procedure'),
 ('RELATED', 'أطراف ذات علاقة'), ('RELATED', 'طرف ذو علاقة'), ('RELATED', 'related party'), ('RELATED', 'related-party'),
 ('RELATED', 'conflict of interest'), ('RELATED', 'تعارض المصالح'),
 ('LIMIT', 'حد'), ('LIMIT', 'سقف'), ('LIMIT', 'limit'), ('LIMIT', 'ceiling'),
 ('STATEMENTS', 'قوائم مالية'), ('STATEMENTS', 'القوائم المالية'), ('STATEMENTS', 'financial statements'),
 ('DIVIDEND', 'توزيع أرباح'), ('DIVIDEND', 'أرباح'), ('DIVIDEND', 'dividend'), ('DIVIDEND', 'profit distribution'),
 ('COMMITTEE', 'لجنة'), ('COMMITTEE', 'committee'),
 ('AMEND', 'تعديل'), ('AMEND', 'amend'), ('AMEND', 'amendment'), ('AMEND', 'modify'),
 ('REMUNERATION', 'مكافآت'), ('REMUNERATION', 'بدلات'), ('REMUNERATION', 'remuneration'), ('REMUNERATION', 'compensation'),
 ('BRANCH', 'فرع'), ('BRANCH', 'branch'), ('BRANCH', 'فروع'),
 ('CAPITAL', 'رأس المال'), ('CAPITAL', 'capital'),
 ('RISK', 'مخاطر'), ('RISK', 'risk'),
 ('STRATEGY', 'استراتيجية'), ('STRATEGY', 'خطة'), ('STRATEGY', 'strategy'), ('STRATEGY', 'business plan'),
 ('DELEGATE', 'تفويض'), ('DELEGATE', 'توقيع'), ('DELEGATE', 'delegation'), ('DELEGATE', 'signatory'),
 ('REJECT', 'رفض'), ('REJECT', 'reject'), ('REJECT', 'rejected'),
 ('DEFER', 'تأجيل'), ('DEFER', 'defer'), ('DEFER', 'postpone')
ON CONFLICT (group_code, term) DO NOTHING;

-- ------------------------------------------------------------------ composition rule sets
CREATE TABLE IF NOT EXISTS gov_composition_rules (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) NOT NULL UNIQUE,
    name_en TEXT NOT NULL,
    name_ar TEXT,
    min_board_size INTEGER,
    max_board_size INTEGER,
    non_exec_majority BOOLEAN NOT NULL DEFAULT FALSE,
    min_indep_share_of_non_exec NUMERIC(5,2),   -- percent
    min_indep_share_of_board NUMERIC(5,2),       -- percent
    min_independent_count INTEGER,
    max_executives INTEGER,
    min_executives INTEGER,
    min_women_share NUMERIC(5,2),                -- percent
    min_women_count INTEGER,
    chair_ceo_separate BOOLEAN NOT NULL DEFAULT FALSE,
    independence_max_years INTEGER,
    max_absence_pct NUMERIC(5,2),                -- percent of the year's meetings
    max_missed_meetings INTEGER,                 -- per year
    min_board_meetings_per_year INTEGER,
    legal_ref TEXT,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(), created_by INTEGER,
    updated_at TIMESTAMP, updated_by INTEGER
);
INSERT INTO gov_composition_rules (code, name_en, name_ar, min_board_size, non_exec_majority, min_indep_share_of_non_exec,
        min_women_share, chair_ceo_separate, independence_max_years, min_board_meetings_per_year, legal_ref, sort_order)
VALUES ('FRA_NBFI', 'FRA non-bank financial institutions', 'الجهات الخاضعة للهيئة العامة للرقابة المالية',
        3, TRUE, 50, 25, TRUE, 6, 4, 'FRA Decree 100/2020 (updated 2024); FRA Decree 48/2022 (women 25%)', 10)
ON CONFLICT (code) DO NOTHING;
INSERT INTO gov_composition_rules (code, name_en, name_ar, min_board_size, min_executives, min_independent_count, legal_ref, sort_order)
VALUES ('FRA_MICROFINANCE', 'FRA microfinance companies', 'شركات التمويل متناهي الصغر',
        7, 2, 2, 'FRA Decree 173/2014', 20)
ON CONFLICT (code) DO NOTHING;
INSERT INTO gov_composition_rules (code, name_en, name_ar, independence_max_years, max_absence_pct, legal_ref, sort_order)
VALUES ('CBE_PSP', 'CBE payment service providers', 'مقدمو خدمات الدفع - البنك المركزي المصري',
        6, 25, 'CBE governance rules for PSPs (Sept 2025)', 30)
ON CONFLICT (code) DO NOTHING;
INSERT INTO gov_composition_rules (code, name_en, name_ar, max_executives, min_independent_count, min_women_count,
        independence_max_years, legal_ref, sort_order)
VALUES ('CBE_BANKS', 'CBE banks', 'البنوك - البنك المركزي المصري', 2, 2, 2, 6,
        'Banking Law 194/2020 and CBE governance instructions', 40)
ON CONFLICT (code) DO NOTHING;
INSERT INTO gov_composition_rules (code, name_en, name_ar, max_missed_meetings, min_board_meetings_per_year, legal_ref, sort_order)
VALUES ('EG_CODE_2016', 'Egyptian Code of Corporate Governance', 'الدليل المصري لحوكمة الشركات',
        3, 4, 'Egyptian Code of Corporate Governance 2016 (best practice)', 50)
ON CONFLICT (code) DO NOTHING;
INSERT INTO gov_composition_rules (code, name_en, name_ar, min_board_size, legal_ref, sort_order)
VALUES ('COMPANIES_LAW', 'Companies Law 159/1981', 'قانون الشركات 159 لسنة 1981', 3,
        'Companies Law 159/1981 Art 77', 60)
ON CONFLICT (code) DO NOTHING;

-- trigram index for the resolutions search (pg_trgm when installed)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS ix_board_decisions_search_trgm ON board_decisions USING gin (search_norm gin_trgm_ops)';
  END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON gov_entities, gov_meeting_rules, gov_committee_types, gov_capacity_dimensions,
    gov_capacity_options, gov_member_capacities, gov_officers, gov_meeting_officers, gov_conflict_declarations,
    gov_resolution_categories, gov_resolution_numbers, gov_resolution_votes, gov_resolution_links,
    gov_search_synonyms, gov_composition_rules TO complynex;
GRANT USAGE, SELECT ON SEQUENCE gov_entities_id_seq, gov_meeting_rules_id_seq, gov_committee_types_id_seq,
    gov_capacity_dimensions_id_seq, gov_capacity_options_id_seq, gov_member_capacities_id_seq, gov_officers_id_seq,
    gov_meeting_officers_id_seq, gov_conflict_declarations_id_seq, gov_resolution_categories_id_seq,
    gov_resolution_votes_id_seq, gov_resolution_links_id_seq, gov_search_synonyms_id_seq,
    gov_composition_rules_id_seq TO complynex;
COMMIT;
