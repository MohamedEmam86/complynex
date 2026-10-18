-- ============================================================================
-- BASATAPAY COMPLIANCE MANAGEMENT SYSTEM - DATABASE SCHEMA
-- ============================================================================
-- Database: SQLite
-- Purpose: Phase 1 Foundation + Phase 2 GHE Module
-- ============================================================================

-- Users Table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    employee_id VARCHAR(50) UNIQUE,
    department VARCHAR(100),
    job_title VARCHAR(100),
    manager_id INTEGER,
    role VARCHAR(50) DEFAULT 'employee' CHECK (role IN ('admin', 'compliance_officer', 'manager', 'employee')),
    cms_access_level VARCHAR(20) DEFAULT 'none' CHECK (cms_access_level IN ('none', 'view', 'edit')),
    is_active BOOLEAN DEFAULT 1,
    last_login DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (manager_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- System Settings
CREATE TABLE IF NOT EXISTS system_settings (
    setting_key VARCHAR(100) PRIMARY KEY,
    setting_value TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit Logs Table
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    module TEXT NOT NULL,
    item_id INTEGER,
    details TEXT,
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- ============================================================================
-- GIFT, HOSPITALITY & ENTERTAINMENT (GHE) MANAGEMENT
-- ============================================================================

-- GHE Declarations (Full Schema)
CREATE TABLE IF NOT EXISTS ghe_declarations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    declaration_number VARCHAR(50) UNIQUE NOT NULL,
    employee_id INTEGER,  -- NULL for public submissions
    declaration_date DATE DEFAULT CURRENT_DATE,
    ghe_type VARCHAR(50) NOT NULL CHECK (ghe_type IN ('Gift', 'Hospitality', 'Entertainment')),
    direction VARCHAR(50) NOT NULL CHECK (direction IN ('Given', 'Received')),
    event_date DATE NOT NULL,
    estimated_value_egp DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'EGP',
    description TEXT NOT NULL,
    provider_recipient_name VARCHAR(200) NOT NULL,
    provider_recipient_company VARCHAR(200),
    business_purpose TEXT,
    is_government_official BOOLEAN DEFAULT 0,
    government_official_details TEXT,
    government_official_position TEXT,
    
    -- Public Submission Fields
    submitter_email VARCHAR(255),  -- For public submissions
    submitter_name VARCHAR(200),   -- For public submissions
    submitter_department VARCHAR(100),  -- For public submissions
    tracking_id VARCHAR(36) UNIQUE,  -- UUID for public status tracking
    is_public_submission BOOLEAN DEFAULT 0,
    
    -- More Info Request
    needs_more_info BOOLEAN DEFAULT 0,
    info_request_message TEXT,
    info_request_date DATETIME,
    info_response TEXT,
    info_response_date DATETIME,
    
    -- Approval Workflow
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'manager_review', 'compliance_review', 'approved', 'rejected', 'info_requested')),
    auto_approved BOOLEAN DEFAULT 0,
    manager_id INTEGER,
    manager_approval_date DATETIME,
    manager_comments TEXT,
    compliance_officer_id INTEGER,
    compliance_approval_date DATETIME,
    compliance_comments TEXT,
    
    -- Attachments
    attachment_path VARCHAR(500),
    
    -- Audit
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER,
    updated_by INTEGER,
    
    FOREIGN KEY (employee_id) REFERENCES users(id),
    FOREIGN KEY (manager_id) REFERENCES users(id),
    FOREIGN KEY (compliance_officer_id) REFERENCES users(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (updated_by) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_ghe_employee ON ghe_declarations(employee_id);
CREATE INDEX IF NOT EXISTS idx_ghe_status ON ghe_declarations(status);
CREATE INDEX IF NOT EXISTS idx_ghe_date ON ghe_declarations(declaration_date);
CREATE INDEX IF NOT EXISTS idx_ghe_value ON ghe_declarations(estimated_value_egp);

-- GHE Approval History Log
CREATE TABLE IF NOT EXISTS ghe_approval_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ghe_declaration_id INTEGER NOT NULL,
    action VARCHAR(50) NOT NULL,
    action_by INTEGER NOT NULL,
    action_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    comments TEXT,
    old_status VARCHAR(50),
    new_status VARCHAR(50),
    FOREIGN KEY (ghe_declaration_id) REFERENCES ghe_declarations(id),
    FOREIGN KEY (action_by) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_ghe_history_declaration ON ghe_approval_history(ghe_declaration_id);

-- ============================================================================
-- CONFLICT OF INTEREST (COI) MANAGEMENT
-- ============================================================================

CREATE TABLE IF NOT EXISTS coi_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_name VARCHAR(200) NOT NULL,
    campaign_year INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('draft', 'active', 'closed')),
    campaign_type VARCHAR(50) DEFAULT 'annual' CHECK (campaign_type IN ('annual', 'adhoc')),
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS coi_declarations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,
    declaration_date DATE DEFAULT CURRENT_DATE,
    
    -- Personal Interests
    has_financial_interests BOOLEAN DEFAULT 0,
    financial_interests_details TEXT,
    
    -- Family Members
    has_family_in_competitor BOOLEAN DEFAULT 0,
    family_competitor_details TEXT,
    has_family_in_supplier BOOLEAN DEFAULT 0,
    family_supplier_details TEXT,
    
    -- Outside Employment
    has_outside_employment BOOLEAN DEFAULT 0,
    outside_employment_details TEXT,
    
    -- Gifts & Benefits
    has_received_gifts BOOLEAN DEFAULT 0,
    gifts_details TEXT,
    
    -- Other Conflicts
    has_other_conflicts BOOLEAN DEFAULT 0,
    other_conflicts_details TEXT,
    
    -- Declaration Statement
    declaration_statement TEXT,
    digital_signature VARCHAR(255),
    
    -- Review Workflow
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'under_review', 'approved', 'requires_clarification', 'escalated')),
    reviewer_id INTEGER,
    review_date DATETIME,
    review_comments TEXT,
    pin_code VARCHAR(4),
    
    -- Audit
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (campaign_id) REFERENCES coi_campaigns(id),
    FOREIGN KEY (employee_id) REFERENCES users(id),
    FOREIGN KEY (reviewer_id) REFERENCES users(id),
    UNIQUE(campaign_id, employee_id)
);

CREATE INDEX IF NOT EXISTS idx_coi_employee ON coi_declarations(employee_id);
CREATE INDEX IF NOT EXISTS idx_coi_campaign ON coi_declarations(campaign_id);
CREATE INDEX IF NOT EXISTS idx_coi_status ON coi_declarations(status);

-- COI Campaign Employee Status (for tracking completion)
CREATE TABLE IF NOT EXISTS coi_campaign_employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'submitted', 'completed', 'overdue')),
    reminder_sent BOOLEAN DEFAULT 0,
    reminder_date DATETIME,
    completed_date DATETIME,
    FOREIGN KEY (campaign_id) REFERENCES coi_campaigns(id),
    FOREIGN KEY (employee_id) REFERENCES users(id),
    UNIQUE(campaign_id, employee_id)
);

-- ============================================================================
-- CODE OF BUSINESS ETHICS & CONDUCT (COBEC) DECLARATIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS cobec_declarations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    declaration_date DATE DEFAULT CURRENT_DATE,
    declaration_year INTEGER NOT NULL,
    
    -- Acknowledgment Questions
    has_read_code BOOLEAN DEFAULT 0,
    understands_responsibilities BOOLEAN DEFAULT 0,
    commits_to_compliance BOOLEAN DEFAULT 0,
    will_report_violations BOOLEAN DEFAULT 0,
    
    -- Potential Violations
    has_known_violations BOOLEAN DEFAULT 0,
    violation_details TEXT,
    
    -- Prior Misconduct
    has_prior_misconduct BOOLEAN DEFAULT 0,
    misconduct_details TEXT,
    
    -- Signature
    digital_signature VARCHAR(255),
    
    -- Status
    status VARCHAR(50) DEFAULT 'submitted' CHECK (status IN ('submitted', 'acknowledged')),
    
    -- Audit
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (employee_id) REFERENCES users(id),
    UNIQUE(employee_id, declaration_year)
);

CREATE INDEX IF NOT EXISTS idx_cobec_employee ON cobec_declarations(employee_id);
CREATE INDEX IF NOT EXISTS idx_cobec_year ON cobec_declarations(declaration_year);

-- ============================================================================
-- POLICY MANAGEMENT (Phase 4)
-- ============================================================================

-- Policy Categories
CREATE TABLE IF NOT EXISTS policy_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name_en VARCHAR(100) NOT NULL,
    name_ar VARCHAR(100),
    description_en TEXT,
    description_ar TEXT,
    icon VARCHAR(50) DEFAULT 'bi-folder',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Policies
CREATE TABLE IF NOT EXISTS policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_number VARCHAR(50) UNIQUE NOT NULL,
    policy_name VARCHAR(200) NOT NULL,
    category_id INTEGER,
    version VARCHAR(20) DEFAULT '1.0',
    effective_date DATE NOT NULL,
    review_date DATE,
    next_review_date DATE,
    owner_id INTEGER,
    owner_function VARCHAR(100),
    description TEXT,
    content TEXT,
    attachment_path VARCHAR(500),
    status VARCHAR(50) DEFAULT 'draft' CHECK (status IN ('draft', 'pending_approval', 'approved', 'published', 'archived')),
    regulatory_reference VARCHAR(200),
    cbe_requirement VARCHAR(200),
    is_public BOOLEAN DEFAULT 0,
    issuing_date DATE,
    approval_cycle VARCHAR(50) DEFAULT 'Annual',
    approved_by INTEGER,
    approval_date DATETIME,

    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES policy_categories(id),
    FOREIGN KEY (owner_id) REFERENCES users(id),
    FOREIGN KEY (approved_by) REFERENCES users(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (updated_by) REFERENCES users(id)
);

-- Policy Acknowledgments
CREATE TABLE IF NOT EXISTS policy_acknowledgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,
    acknowledgment_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    digital_signature VARCHAR(255),
    FOREIGN KEY (policy_id) REFERENCES policies(id),
    FOREIGN KEY (employee_id) REFERENCES users(id),
    UNIQUE(policy_id, employee_id)
);

-- Policy Version History
CREATE TABLE IF NOT EXISTS policy_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id INTEGER NOT NULL,
    version VARCHAR(20) NOT NULL,
    change_summary TEXT,
    content TEXT,
    effective_date DATE,
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (policy_id) REFERENCES policies(id),
    FOREIGN KEY (created_by) REFERENCES users(id)
);

-- ============================================================================
-- REGULATORY REPORTING & TRAINING (Phase 5)
-- ============================================================================

-- Regulators
CREATE TABLE IF NOT EXISTS regulators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    regulator_name VARCHAR(100) NOT NULL,
    regulator_code VARCHAR(20) UNIQUE,
    contact_email VARCHAR(255),
    contact_phone VARCHAR(50),
    website VARCHAR(255),
    description TEXT,
    is_active BOOLEAN DEFAULT 1
);

-- Report Templates
CREATE TABLE IF NOT EXISTS regulatory_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_code VARCHAR(50) UNIQUE NOT NULL,
    report_name VARCHAR(200) NOT NULL,
    regulator_id INTEGER,
    frequency VARCHAR(50) NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly', 'quarterly', 'semi_annual', 'annual', 'adhoc')),
    due_day INTEGER,
    due_month INTEGER,
    description TEXT,
    submission_method VARCHAR(100),
    responsible_department VARCHAR(100),
    cbe_circular_reference VARCHAR(200),
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (regulator_id) REFERENCES regulators(id)
);

-- Report Submissions
CREATE TABLE IF NOT EXISTS regulatory_report_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    reporting_period_start DATE,
    reporting_period_end DATE,
    due_date DATE NOT NULL,
    submission_date DATE,
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'submitted', 'late', 'overdue')),
    submission_reference VARCHAR(100),
    notes TEXT,
    attachment_path VARCHAR(500),
    prepared_by INTEGER,
    reviewed_by INTEGER,
    approved_by INTEGER,
    reminder_sent BOOLEAN DEFAULT 0,
    reminder_date DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES regulatory_reports(id),
    FOREIGN KEY (prepared_by) REFERENCES users(id),
    FOREIGN KEY (reviewed_by) REFERENCES users(id),
    FOREIGN KEY (approved_by) REFERENCES users(id)
);

-- Training Courses
CREATE TABLE IF NOT EXISTS training_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code VARCHAR(50) UNIQUE NOT NULL,
    course_name VARCHAR(200) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    duration_minutes INTEGER,
    content TEXT,
    video_url VARCHAR(500),
    document_path VARCHAR(500),
    presentation_path VARCHAR(500),
    video_file_path VARCHAR(500),
    external_link VARCHAR(500),
    content_type VARCHAR(50) DEFAULT 'Hybrid',
    passing_score INTEGER DEFAULT 70,
    is_mandatory BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id)
);

-- Training Enrollments
CREATE TABLE IF NOT EXISTS training_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,
    enrolled_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    enrolled_by INTEGER,
    due_date DATE,
    status VARCHAR(50) DEFAULT 'enrolled' CHECK (status IN ('enrolled', 'in_progress', 'completed', 'overdue')),
    completion_date DATETIME,
    score INTEGER,
    video_progress INTEGER DEFAULT 0,
    video_completed BOOLEAN DEFAULT 0,
    FOREIGN KEY (course_id) REFERENCES training_courses(id),
    FOREIGN KEY (employee_id) REFERENCES users(id),
    FOREIGN KEY (enrolled_by) REFERENCES users(id),
    UNIQUE(course_id, employee_id)
);

-- Training Questions
CREATE TABLE IF NOT EXISTS training_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    question_type VARCHAR(50) DEFAULT 'multiple_choice',
    options TEXT, -- JSON: ["Option A", "Option B", "Option C", "Option D"]
    correct_answer TEXT, -- Index or text
    explanation TEXT,
    points INTEGER DEFAULT 1,
    FOREIGN KEY (course_id) REFERENCES training_courses(id)
);

-- Training Certificates
CREATE TABLE IF NOT EXISTS training_certificates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    certificate_number VARCHAR(100) UNIQUE NOT NULL,
    enrollment_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    issue_date DATE DEFAULT CURRENT_DATE,
    expiry_date DATE,
    score INTEGER,
    FOREIGN KEY (enrollment_id) REFERENCES training_enrollments(id),
    FOREIGN KEY (employee_id) REFERENCES users(id),
    FOREIGN KEY (course_id) REFERENCES training_courses(id)
);

-- ============================================================================
-- INITIAL DATA
-- ============================================================================

-- Default Admin User (password: Admin@123)
INSERT OR IGNORE INTO users (email, password_hash, first_name, last_name, role, is_active) VALUES
('admin@basatapay.com', 'pbkdf2:sha256:600000$placeholder$hash', 'System', 'Administrator', 'admin', 1);

-- Default Policy Categories
INSERT OR IGNORE INTO policy_categories (name_en, name_ar, description_en, description_ar) VALUES
('AML/CFT', 'مكافحة غسل الأموال', 'Anti-Money Laundering and Counter Terrorist Financing', 'سياسات مكافحة غسل الأموال وتمويل الإرهاب'),
('Data Protection', 'حماية البيانات', 'Personal Data Protection and Privacy', 'حماية البيانات الشخصية والخصوصية'),
('Information Security', 'أمن المعلومات', 'Cybersecurity and Information Security', 'الأمن السيبراني وأمن المعلومات'),
('Business Continuity', 'استمرارية الأعمال', 'Business Continuity and Disaster Recovery', 'استمرارية الأعمال والتعافي من الكوارث'),
('Consumer Protection', 'حماية المستهلك', 'Consumer Rights and Protection', 'حقوق وحماية المستهلك'),
('Code of Conduct', 'مدونة قواعد السلوك', 'Ethics, Code of Conduct, and Employee Behavior', 'الأخلاقيات ومدونة قواعد السلوك'),
('Risk Management', 'إدارة المخاطر', 'Enterprise Risk Management', 'إدارة مخاطر المؤسسة'),
('Compliance', 'الالتزام', 'General Compliance and Regulatory Policies', 'سياسات الالتزام العام والرقابة');

-- GHE Thresholds
INSERT OR IGNORE INTO system_settings (setting_key, setting_value, description) VALUES
('ghe_auto_approve_threshold', '500', 'Auto-approve below this EGP'),
('ghe_manager_approval_threshold', '2000', 'Manager approval below this EGP'),
('company_name', 'Basatapay', 'Company name');

-- =====================================================================
-- PHASE 9: FULL CBE/FRA/PDPL COMPLIANCE UPGRADE
-- =====================================================================

-- =====================================================================
-- AML/CFT DATABASE TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_number VARCHAR(20) UNIQUE NOT NULL,
    customer_type VARCHAR(20) NOT NULL CHECK (customer_type IN ('INDIVIDUAL', 'CORPORATE')),
    full_name VARCHAR(255),
    full_name_arabic VARCHAR(255),
    date_of_birth DATE,
    nationality VARCHAR(100),
    id_type VARCHAR(50),
    id_number VARCHAR(100),
    id_expiry_date DATE,
    gender VARCHAR(10),
    company_name VARCHAR(255),
    company_name_arabic VARCHAR(255),
    registration_number VARCHAR(100),
    registration_date DATE,
    legal_form VARCHAR(100),
    industry VARCHAR(100),
    address TEXT,
    city VARCHAR(100),
    country VARCHAR(100),
    phone VARCHAR(50),
    email VARCHAR(255),
    occupation VARCHAR(255),
    employer VARCHAR(255),
    source_of_income TEXT,
    source_of_funds TEXT,
    purpose_of_relationship TEXT,
    expected_transaction_volume VARCHAR(50),
    expected_transaction_frequency VARCHAR(50),
    risk_classification VARCHAR(20) DEFAULT 'MEDIUM' CHECK (risk_classification IN ('LOW', 'MEDIUM', 'HIGH')),
    risk_score INTEGER DEFAULT 50,
    risk_classification_date DATE,
    risk_classification_reason TEXT,
    risk_classified_by INTEGER,
    risk_override_reason TEXT,
    is_pep BOOLEAN DEFAULT 0,
    is_sanctioned BOOLEAN DEFAULT 0,
    is_high_risk_country BOOLEAN DEFAULT 0,
    requires_edd BOOLEAN DEFAULT 0,
    edd_completed BOOLEAN DEFAULT 0,
    edd_approved_by INTEGER,
    edd_approval_date DATE,
    last_review_date DATE,
    next_review_date DATE,
    review_frequency_months INTEGER DEFAULT 24,
    annual_income_range VARCHAR(100),
    business_activity TEXT,
    status VARCHAR(20) DEFAULT 'ACTIVE' CHECK (status IN ('PENDING', 'ACTIVE', 'SUSPENDED', 'CLOSED', 'BLOCKED')),
    onboarding_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER,
    updated_at TIMESTAMP,
    updated_by INTEGER,
    email_encrypted TEXT,
    phone_encrypted TEXT,
    national_id_hash TEXT,
    is_encrypted INTEGER DEFAULT 0,
    FOREIGN KEY (risk_classified_by) REFERENCES users(id),
    FOREIGN KEY (edd_approved_by) REFERENCES users(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (updated_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS cdd_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    document_type VARCHAR(100) NOT NULL,
    document_name VARCHAR(255),
    file_path VARCHAR(500),
    file_size INTEGER,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    uploaded_by INTEGER,
    expiry_date DATE,
    verified BOOLEAN DEFAULT 0,
    verified_by INTEGER,
    verification_date DATE,
    verification_notes TEXT,
    status VARCHAR(20) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'VERIFIED', 'REJECTED', 'EXPIRED')),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (uploaded_by) REFERENCES users(id),
    FOREIGN KEY (verified_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS beneficial_owners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    owner_name VARCHAR(255) NOT NULL,
    owner_name_arabic VARCHAR(255),
    nationality VARCHAR(100),
    date_of_birth DATE,
    id_type VARCHAR(50),
    id_number VARCHAR(100),
    ownership_percentage DECIMAL(5,2),
    is_direct_owner BOOLEAN DEFAULT 1,
    ownership_chain TEXT,
    is_pep BOOLEAN DEFAULT 0,
    is_sanctioned BOOLEAN DEFAULT 0,
    verification_status VARCHAR(20) DEFAULT 'PENDING',
    verified_by INTEGER,
    verification_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (verified_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS cdd_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    review_type VARCHAR(50) NOT NULL CHECK (review_type IN ('INITIAL', 'PERIODIC', 'TRIGGERED', 'EDD')),
    review_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_by INTEGER NOT NULL,
    previous_risk_classification VARCHAR(20),
    new_risk_classification VARCHAR(20),
    risk_changed BOOLEAN DEFAULT 0,
    findings TEXT,
    recommendations TEXT,
    documents_reviewed TEXT,
    next_review_date DATE,
    status VARCHAR(20) DEFAULT 'COMPLETED',
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (reviewed_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS cdd_risk_factors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    factor_category VARCHAR(100) NOT NULL,
    factor_name VARCHAR(255) NOT NULL,
    factor_description TEXT,
    risk_weight INTEGER DEFAULT 1,
    is_edd_trigger BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS customer_risk_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    factor_id INTEGER NOT NULL,
    factor_value VARCHAR(255),
    score_contribution INTEGER,
    assessment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assessed_by INTEGER,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (factor_id) REFERENCES cdd_risk_factors(id),
    FOREIGN KEY (assessed_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS pep_screenings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screening_reference VARCHAR(50) UNIQUE NOT NULL,
    entity_type VARCHAR(20) NOT NULL CHECK (entity_type IN ('CUSTOMER', 'BENEFICIAL_OWNER', 'RELATED_PARTY', 'COUNTERPARTY')),
    entity_id INTEGER,
    entity_name VARCHAR(255) NOT NULL,
    date_of_birth DATE,
    nationality VARCHAR(100),
    screening_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    screened_by INTEGER,
    screening_source VARCHAR(100),
    matches_found INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'NO_MATCH', 'POTENTIAL_MATCH', 'CONFIRMED_MATCH', 'FALSE_POSITIVE')),
    FOREIGN KEY (screened_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS pep_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screening_id INTEGER NOT NULL,
    pep_name VARCHAR(255),
    pep_position VARCHAR(255),
    pep_country VARCHAR(100),
    pep_category VARCHAR(100),
    match_score DECIMAL(5,2),
    match_details TEXT,
    investigation_status VARCHAR(20) DEFAULT 'PENDING' CHECK (investigation_status IN ('PENDING', 'INVESTIGATING', 'CONFIRMED', 'FALSE_POSITIVE')),
    investigated_by INTEGER,
    investigation_date DATE,
    investigation_notes TEXT,
    is_false_positive BOOLEAN DEFAULT 0,
    false_positive_reason TEXT,
    senior_approval_required BOOLEAN DEFAULT 0,
    approved_by INTEGER,
    approval_date DATE,
    approval_notes TEXT,
    FOREIGN KEY (screening_id) REFERENCES pep_screenings(id),
    FOREIGN KEY (investigated_by) REFERENCES users(id),
    FOREIGN KEY (approved_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sanctions_screenings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screening_reference VARCHAR(50) UNIQUE NOT NULL,
    entity_type VARCHAR(20) NOT NULL,
    entity_id INTEGER,
    entity_name VARCHAR(255) NOT NULL,
    screening_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    screened_by INTEGER,
    lists_checked TEXT,
    matches_found INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'CLEAR', 'POTENTIAL_MATCH', 'CONFIRMED_MATCH', 'FALSE_POSITIVE', 'BLOCKED')),
    FOREIGN KEY (screened_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sanctions_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screening_id INTEGER NOT NULL,
    sanctioned_name VARCHAR(255),
    sanctions_list VARCHAR(100),
    list_id VARCHAR(100),
    match_score DECIMAL(5,2),
    match_details TEXT,
    investigation_status VARCHAR(20) DEFAULT 'PENDING',
    investigated_by INTEGER,
    investigation_date DATE,
    investigation_notes TEXT,
    is_false_positive BOOLEAN DEFAULT 0,
    false_positive_reason TEXT,
    is_blocked BOOLEAN DEFAULT 0,
    blocked_date DATE,
    emlcu_notified BOOLEAN DEFAULT 0,
    emlcu_notification_date DATE,
    emlcu_reference VARCHAR(100),
    FOREIGN KEY (screening_id) REFERENCES sanctions_screenings(id),
    FOREIGN KEY (investigated_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sanctions_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_code VARCHAR(50) NOT NULL,
    list_name VARCHAR(255) NOT NULL,
    source_url VARCHAR(500),
    last_download_date TIMESTAMP,
    record_count INTEGER,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sanctions_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL,
    entry_id VARCHAR(100),
    entry_type VARCHAR(50),
    name VARCHAR(500),
    aliases TEXT,
    date_of_birth VARCHAR(100),
    nationality VARCHAR(255),
    addresses TEXT,
    identifications TEXT,
    programs TEXT,
    remarks TEXT,
    listed_date DATE,
    FOREIGN KEY (list_id) REFERENCES sanctions_lists(id)
);

CREATE TABLE IF NOT EXISTS red_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flag_code VARCHAR(50) UNIQUE NOT NULL,
    flag_name VARCHAR(255) NOT NULL,
    flag_description TEXT,
    flag_category VARCHAR(100),
    severity VARCHAR(20) DEFAULT 'MEDIUM' CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS suspicious_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sar_reference VARCHAR(50) UNIQUE NOT NULL,
    activity_date DATE NOT NULL,
    discovery_date DATE NOT NULL,
    customer_id INTEGER,
    customer_name VARCHAR(255),
    activity_description TEXT NOT NULL,
    amount_involved DECIMAL(18,2),
    currency VARCHAR(10) DEFAULT 'EGP',
    transaction_ids TEXT,
    red_flags_identified TEXT,
    reported_by INTEGER NOT NULL,
    report_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_to INTEGER,
    assignment_date DATE,
    investigation_status VARCHAR(20) DEFAULT 'NEW' CHECK (investigation_status IN ('NEW', 'ASSIGNED', 'INVESTIGATING', 'PENDING_DECISION', 'FILE_SAR', 'NO_SAR', 'CLOSED')),
    investigation_notes TEXT,
    investigation_findings TEXT,
    decision VARCHAR(20),
    decision_by INTEGER,
    decision_date DATE,
    decision_rationale TEXT,
    sar_filed BOOLEAN DEFAULT 0,
    sar_filing_date DATE,
    sar_deadline DATE,
    sar_days_remaining INTEGER,
    sar_file_path VARCHAR(500),
    emlcu_reference VARCHAR(100),
    emlcu_acknowledgment_date DATE,
    emlcu_feedback TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (reported_by) REFERENCES users(id),
    FOREIGN KEY (assigned_to) REFERENCES users(id),
    FOREIGN KEY (decision_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sar_red_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sar_id INTEGER NOT NULL,
    red_flag_id INTEGER NOT NULL,
    notes TEXT,
    FOREIGN KEY (sar_id) REFERENCES suspicious_activities(id),
    FOREIGN KEY (red_flag_id) REFERENCES red_flags(id)
);

CREATE TABLE IF NOT EXISTS tm_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_code VARCHAR(50) UNIQUE NOT NULL,
    rule_name VARCHAR(255) NOT NULL,
    rule_description TEXT,
    rule_category VARCHAR(100),
    rule_type VARCHAR(50) CHECK (rule_type IN ('THRESHOLD', 'VELOCITY', 'PATTERN', 'GEOGRAPHIC', 'BEHAVIORAL')),
    threshold_value DECIMAL(18,2),
    threshold_currency VARCHAR(10),
    time_period_days INTEGER,
    is_active BOOLEAN DEFAULT 1,
    severity VARCHAR(20) DEFAULT 'MEDIUM',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tm_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_reference VARCHAR(50) UNIQUE NOT NULL,
    rule_id INTEGER,
    customer_id INTEGER,
    alert_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    alert_description TEXT,
    triggered_transactions TEXT,
    alert_severity VARCHAR(20),
    assigned_to INTEGER,
    status VARCHAR(20) DEFAULT 'NEW' CHECK (status IN ('NEW', 'ASSIGNED', 'INVESTIGATING', 'ESCALATED', 'FALSE_POSITIVE', 'SAR_CREATED', 'CLOSED')),
    investigation_notes TEXT,
    disposition VARCHAR(50),
    disposition_by INTEGER,
    disposition_date DATE,
    sar_id INTEGER,
    FOREIGN KEY (rule_id) REFERENCES tm_rules(id),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (assigned_to) REFERENCES users(id),
    FOREIGN KEY (disposition_by) REFERENCES users(id),
    FOREIGN KEY (sar_id) REFERENCES suspicious_activities(id)
);

CREATE TABLE IF NOT EXISTS high_risk_countries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country_code VARCHAR(10) NOT NULL,
    country_name VARCHAR(100) NOT NULL,
    risk_category VARCHAR(50) CHECK (risk_category IN ('FATF_BLACKLIST', 'FATF_GRAYLIST', 'SANCTIONS', 'HIGH_CORRUPTION', 'TAX_HAVEN', 'OTHER')),
    source VARCHAR(100),
    effective_date DATE,
    is_active BOOLEAN DEFAULT 1
);

-- =====================================================================
-- DATA PROTECTION (PDPL) DATABASE TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS data_subject_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_number VARCHAR(50) UNIQUE NOT NULL,
    request_date DATE NOT NULL,
    request_channel VARCHAR(50) CHECK (request_channel IN ('EMAIL', 'WEBSITE', 'PHONE', 'MAIL', 'IN_PERSON')),
    data_subject_name VARCHAR(255) NOT NULL,
    data_subject_email VARCHAR(255),
    data_subject_phone VARCHAR(50),
    data_subject_id_type VARCHAR(50),
    data_subject_id_number VARCHAR(100),
    request_type VARCHAR(50) NOT NULL CHECK (request_type IN ('ACCESS', 'RECTIFICATION', 'ERASURE', 'RESTRICTION', 'PORTABILITY', 'OBJECTION')),
    request_description TEXT,
    identity_verified BOOLEAN DEFAULT 0,
    identity_verified_by INTEGER,
    identity_verification_date DATE,
    identity_verification_method VARCHAR(100),
    assigned_to INTEGER,
    assigned_date DATE,
    due_date DATE NOT NULL,
    days_remaining INTEGER,
    status VARCHAR(50) DEFAULT 'NEW' CHECK (status IN ('NEW', 'IDENTITY_PENDING', 'IN_PROGRESS', 'PENDING_APPROVAL', 'COMPLETED', 'REJECTED', 'OVERDUE')),
    response_date DATE,
    response_method VARCHAR(50),
    response_file VARCHAR(500),
    response_notes TEXT,
    rejection_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER,
    updated_at TIMESTAMP,
    FOREIGN KEY (identity_verified_by) REFERENCES users(id),
    FOREIGN KEY (assigned_to) REFERENCES users(id),
    FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS dsr_timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    action_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    action_type VARCHAR(100) NOT NULL,
    action_description TEXT,
    action_by INTEGER,
    FOREIGN KEY (request_id) REFERENCES data_subject_requests(id),
    FOREIGN KEY (action_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS consent_purposes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purpose_code VARCHAR(50) UNIQUE NOT NULL,
    purpose_name VARCHAR(255) NOT NULL,
    purpose_name_arabic VARCHAR(255),
    purpose_description TEXT,
    purpose_description_arabic TEXT,
    is_required BOOLEAN DEFAULT 0,
    legal_basis VARCHAR(100),
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_subject_id VARCHAR(100) NOT NULL,
    data_subject_identifier VARCHAR(255),
    purpose_id INTEGER NOT NULL,
    consent_given BOOLEAN NOT NULL,
    consent_date TIMESTAMP NOT NULL,
    consent_method VARCHAR(50) CHECK (consent_method IN ('WEBSITE', 'APP', 'PAPER', 'VERBAL', 'EMAIL')),
    consent_text TEXT,
    ip_address VARCHAR(50),
    user_agent TEXT,
    withdrawn BOOLEAN DEFAULT 0,
    withdrawal_date TIMESTAMP,
    withdrawal_method VARCHAR(50),
    withdrawal_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (purpose_id) REFERENCES consent_purposes(id)
);

CREATE TABLE IF NOT EXISTS data_breaches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    breach_number VARCHAR(50) UNIQUE NOT NULL,
    breach_date DATE NOT NULL,
    discovery_date DATE NOT NULL,
    discovered_by VARCHAR(255),
    discovery_method VARCHAR(100),
    breach_type VARCHAR(100) NOT NULL CHECK (breach_type IN ('UNAUTHORIZED_ACCESS', 'DATA_THEFT', 'ACCIDENTAL_DISCLOSURE', 'LOSS_OF_DEVICE', 'RANSOMWARE', 'HACKING', 'INSIDER_THREAT', 'PHISHING', 'OTHER')),
    breach_description TEXT NOT NULL,
    affected_systems TEXT,
    affected_individuals_count INTEGER,
    data_types_affected TEXT,
    includes_sensitive_data BOOLEAN DEFAULT 0,
    sensitive_data_types TEXT,
    potential_harm TEXT,
    severity VARCHAR(20) CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    severity_score INTEGER,
    pdpc_notification_required BOOLEAN DEFAULT 0,
    pdpc_notification_deadline TIMESTAMP,
    pdpc_notified BOOLEAN DEFAULT 0,
    pdpc_notification_date TIMESTAMP,
    pdpc_reference VARCHAR(100),
    pdpc_notification_file VARCHAR(500),
    individuals_notification_required BOOLEAN DEFAULT 0,
    individuals_notified BOOLEAN DEFAULT 0,
    individuals_notification_date DATE,
    individuals_notification_method VARCHAR(100),
    individuals_notification_count INTEGER,
    root_cause TEXT,
    investigation_findings TEXT,
    containment_actions TEXT,
    containment_date DATE,
    remediation_actions TEXT,
    remediation_status VARCHAR(50) DEFAULT 'PENDING',
    remediation_completion_date DATE,
    lessons_learned TEXT,
    policy_changes TEXT,
    status VARCHAR(50) DEFAULT 'NEW' CHECK (status IN ('NEW', 'INVESTIGATING', 'CONTAINED', 'REMEDIATING', 'CLOSED')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER,
    updated_at TIMESTAMP,
    closed_date DATE,
    closed_by INTEGER,
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (closed_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS breach_remediation_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    breach_id INTEGER NOT NULL,
    action_description TEXT NOT NULL,
    action_owner INTEGER,
    target_date DATE,
    completion_date DATE,
    status VARCHAR(20) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'OVERDUE')),
    evidence_file VARCHAR(500),
    notes TEXT,
    FOREIGN KEY (breach_id) REFERENCES data_breaches(id),
    FOREIGN KEY (action_owner) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS data_processing_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_code VARCHAR(50) UNIQUE NOT NULL,
    activity_name VARCHAR(255) NOT NULL,
    activity_description TEXT,
    processing_purpose TEXT NOT NULL,
    legal_basis VARCHAR(100) NOT NULL,
    data_categories TEXT NOT NULL,
    data_subject_categories TEXT NOT NULL,
    recipients TEXT,
    international_transfer BOOLEAN DEFAULT 0,
    transfer_countries TEXT,
    transfer_safeguards TEXT,
    retention_period VARCHAR(100),
    retention_justification TEXT,
    security_measures TEXT,
    data_owner INTEGER,
    system_name VARCHAR(255),
    last_review_date DATE,
    next_review_date DATE,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (data_owner) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS dpias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dpia_number VARCHAR(50) UNIQUE NOT NULL,
    project_name VARCHAR(255) NOT NULL,
    project_description TEXT,
    processing_description TEXT,
    necessity_assessment TEXT,
    proportionality_assessment TEXT,
    risks_identified TEXT,
    risk_level VARCHAR(20) CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH')),
    mitigation_measures TEXT,
    residual_risk_level VARCHAR(20),
    pdpc_consultation_required BOOLEAN DEFAULT 0,
    pdpc_consulted BOOLEAN DEFAULT 0,
    pdpc_consultation_date DATE,
    pdpc_response TEXT,
    approved BOOLEAN DEFAULT 0,
    approved_by INTEGER,
    approval_date DATE,
    approval_conditions TEXT,
    status VARCHAR(50) DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'IN_PROGRESS', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'ARCHIVED')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER,
    updated_at TIMESTAMP,
    FOREIGN KEY (approved_by) REFERENCES users(id),
    FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS dpo_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_date DATE NOT NULL,
    activity_type VARCHAR(100) NOT NULL,
    activity_description TEXT,
    outcome TEXT,
    follow_up_required BOOLEAN DEFAULT 0,
    follow_up_date DATE,
    logged_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (logged_by) REFERENCES users(id)
);

-- =====================================================================
-- CYBERSECURITY INCIDENT DATABASE TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS cyber_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_number VARCHAR(50) UNIQUE NOT NULL,
    incident_date TIMESTAMP NOT NULL,
    discovery_date TIMESTAMP NOT NULL,
    reported_by VARCHAR(255),
    incident_type VARCHAR(100) NOT NULL CHECK (incident_type IN ('MALWARE', 'RANSOMWARE', 'PHISHING', 'UNAUTHORIZED_ACCESS', 'DATA_BREACH', 'DDOS', 'SYSTEM_OUTAGE', 'VULNERABILITY_EXPLOIT', 'INSIDER_THREAT', 'OTHER')),
    incident_description TEXT NOT NULL,
    affected_systems TEXT,
    affected_users_count INTEGER,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    cbe_notification_required BOOLEAN DEFAULT 0,
    cbe_notification_deadline TIMESTAMP,
    cbe_notified BOOLEAN DEFAULT 0,
    cbe_notification_date TIMESTAMP,
    cbe_reference VARCHAR(100),
    containment_actions TEXT,
    containment_date TIMESTAMP,
    eradication_actions TEXT,
    eradication_date TIMESTAMP,
    recovery_actions TEXT,
    recovery_date TIMESTAMP,
    root_cause TEXT,
    attack_vector VARCHAR(255),
    indicators_of_compromise TEXT,
    lessons_learned TEXT,
    preventive_measures TEXT,
    status VARCHAR(50) DEFAULT 'NEW' CHECK (status IN ('NEW', 'TRIAGING', 'CONTAINING', 'ERADICATING', 'RECOVERING', 'POST_INCIDENT', 'CLOSED')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER,
    closed_date TIMESTAMP,
    closed_by INTEGER,
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (closed_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS incident_response_team (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role VARCHAR(100),
    assigned_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (incident_id) REFERENCES cyber_incidents(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS incident_timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER NOT NULL,
    event_date TIMESTAMP NOT NULL,
    event_type VARCHAR(100),
    event_description TEXT,
    action_taken TEXT,
    recorded_by INTEGER,
    FOREIGN KEY (incident_id) REFERENCES cyber_incidents(id),
    FOREIGN KEY (recorded_by) REFERENCES users(id)
);

-- =====================================================================
-- RISK MANAGEMENT MODULE
-- =====================================================================

CREATE TABLE IF NOT EXISTS risks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id VARCHAR(50) UNIQUE NOT NULL,
    risk_title VARCHAR(255) NOT NULL,
    risk_description TEXT,
    category_id INTEGER NOT NULL,
    likelihood INTEGER NOT NULL CHECK (likelihood BETWEEN 1 AND 5),
    impact INTEGER NOT NULL CHECK (impact BETWEEN 1 AND 5),
    inherent_risk_score INTEGER,
    existing_controls TEXT,
    control_effectiveness VARCHAR(20) CHECK (control_effectiveness IN ('EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'INEFFECTIVE')),
    residual_likelihood INTEGER CHECK (residual_likelihood BETWEEN 1 AND 5),
    residual_impact INTEGER CHECK (residual_impact BETWEEN 1 AND 5),
    residual_risk_score INTEGER,
    risk_response VARCHAR(20) CHECK (risk_response IN ('ACCEPT', 'MITIGATE', 'TRANSFER', 'AVOID')),
    risk_owner_id INTEGER,
    review_frequency VARCHAR(20) DEFAULT 'QUARTERLY',
    last_review_date DATE,
    next_review_date DATE,
    risk_appetite_aligned BOOLEAN DEFAULT 1,
    status VARCHAR(20) DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'CLOSED', 'ACCEPTED')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES risk_categories(id),
    FOREIGN KEY (risk_owner_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS risk_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name VARCHAR(100) NOT NULL,
    category_description TEXT
);

CREATE TABLE IF NOT EXISTS risk_treatments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id INTEGER NOT NULL,
    treatment_description TEXT NOT NULL,
    treatment_owner_id INTEGER,
    target_date DATE,
    completion_date DATE,
    status VARCHAR(20) DEFAULT 'PENDING',
    evidence_file VARCHAR(500),
    FOREIGN KEY (risk_id) REFERENCES risks(id),
    FOREIGN KEY (treatment_owner_id) REFERENCES users(id)
);

-- =====================================================================
-- INTERNAL AUDIT MODULE
-- =====================================================================

CREATE TABLE IF NOT EXISTS audit_universe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    auditable_area VARCHAR(255) NOT NULL,
    area_description TEXT,
    risk_level VARCHAR(20) DEFAULT 'MEDIUM',
    last_audit_date DATE,
    audit_frequency VARCHAR(20) DEFAULT 'ANNUAL',
    next_audit_due DATE,
    responsible_department VARCHAR(100),
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS annual_audit_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_year INTEGER NOT NULL,
    plan_name VARCHAR(255),
    status VARCHAR(20) DEFAULT 'DRAFT',
    approved_date DATE,
    approved_by INTEGER,
    FOREIGN KEY (approved_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audit_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER,
    audit_number VARCHAR(50) UNIQUE NOT NULL,
    audit_name VARCHAR(255) NOT NULL,
    auditable_area_id INTEGER,
    audit_type VARCHAR(50) CHECK (audit_type IN ('INTERNAL', 'EXTERNAL', 'REGULATORY', 'SPECIAL')),
    audit_scope TEXT,
    planned_start_date DATE,
    planned_end_date DATE,
    actual_start_date DATE,
    actual_end_date DATE,
    lead_auditor_id INTEGER,
    status VARCHAR(20) DEFAULT 'PLANNED',
    FOREIGN KEY (plan_id) REFERENCES annual_audit_plans(id),
    FOREIGN KEY (auditable_area_id) REFERENCES audit_universe(id),
    FOREIGN KEY (lead_auditor_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audit_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    finding_number VARCHAR(50) NOT NULL,
    finding_title VARCHAR(255) NOT NULL,
    finding_description TEXT,
    severity VARCHAR(20) CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')),
    root_cause TEXT,
    recommendation TEXT,
    management_response TEXT,
    agreed_action TEXT,
    responsible_person_id INTEGER,
    target_date DATE,
    status VARCHAR(20) DEFAULT 'OPEN',
    FOREIGN KEY (project_id) REFERENCES audit_projects(id),
    FOREIGN KEY (responsible_person_id) REFERENCES users(id)
);

-- =====================================================================
-- CUSTOMER COMPLAINTS MODULE
-- =====================================================================

CREATE TABLE IF NOT EXISTS customer_complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_number VARCHAR(50) UNIQUE NOT NULL,
    submission_date DATE NOT NULL,
    submission_channel VARCHAR(50) CHECK (submission_channel IN ('PHONE', 'EMAIL', 'WEBSITE', 'MOBILE_APP', 'BRANCH', 'MAIL', 'SOCIAL_MEDIA')),
    customer_id INTEGER,
    customer_name VARCHAR(255),
    customer_email VARCHAR(255),
    customer_phone VARCHAR(50),
    complaint_category VARCHAR(100),
    complaint_subcategory VARCHAR(100),
    complaint_description TEXT NOT NULL,
    acknowledgment_due_date DATE,
    acknowledgment_sent BOOLEAN DEFAULT 0,
    acknowledgment_date DATE,
    resolution_due_date DATE,
    assigned_to INTEGER,
    investigation_notes TEXT,
    resolution TEXT,
    resolution_date DATE,
    closure_date DATE,
    customer_satisfied BOOLEAN,
    satisfaction_score INTEGER,
    root_cause TEXT,
    corrective_action TEXT,
    status VARCHAR(20) DEFAULT 'NEW' CHECK (status IN ('NEW', 'ACKNOWLEDGED', 'INVESTIGATING', 'RESOLVED', 'CLOSED', 'ESCALATED', 'OVERDUE')),
    escalated BOOLEAN DEFAULT 0,
    escalation_reason TEXT,
    escalated_to INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (assigned_to) REFERENCES users(id),
    FOREIGN KEY (escalated_to) REFERENCES users(id)
);

-- =====================================================================
-- GOVERNANCE MODULE
-- =====================================================================

CREATE TABLE IF NOT EXISTS board_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_name VARCHAR(255) NOT NULL,
    member_name_arabic VARCHAR(255),
    role VARCHAR(100) NOT NULL,
    is_independent BOOLEAN DEFAULT 0,
    is_executive BOOLEAN DEFAULT 0,
    expertise_areas TEXT,
    appointment_date DATE NOT NULL,
    term_end_date DATE,
    email VARCHAR(255),
    phone VARCHAR(50),
    bio TEXT,
    status VARCHAR(20) DEFAULT 'ACTIVE',
    document_path VARCHAR(500)
);

CREATE TABLE board_committees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Committee Details
    committee_name TEXT NOT NULL,
    committee_name_arabic TEXT,
    committee_type TEXT CHECK(committee_type IN (
        'AUDIT', 'RISK', 'NOMREM', 'COMPLIANCE', 'GOVERNANCE',
        'EXECUTIVE', 'INVESTMENT', 'IT', 'CREDIT', 'OTHER'
    )) NOT NULL,
    
    -- Mandatory Status (CBE requires certain committees)
    is_mandatory BOOLEAN DEFAULT 0, -- Audit, Risk, NomRem are mandatory
    regulatory_requirement TEXT, -- Reference to regulation requiring it
    
    -- Leadership
    chairman_id INTEGER,
    secretary_id INTEGER,
    
    -- Composition Requirements (CBE Specific)
    min_members INTEGER DEFAULT 3,
    max_members INTEGER,
    independence_requirement TEXT, -- e.g., "Majority must be independent"
    min_independent_members INTEGER, -- Enforced minimum
    requires_financial_expert BOOLEAN DEFAULT 0, -- Audit Committee requirement
    
    -- Charter & Terms of Reference
    charter_file TEXT,
    charter_version TEXT,
    charter_last_review DATE,
    charter_next_review DATE,
    terms_of_reference TEXT, -- Full text or summary
    
    -- Meeting Requirements
    meeting_frequency TEXT, -- e.g., "Quarterly", "Monthly"
    min_meetings_per_year INTEGER DEFAULT 4,
    quorum_requirement TEXT, -- e.g., "50% + 1", "3 members"
    quorum_number INTEGER, -- Calculated quorum
    
    -- Performance & Effectiveness
    last_evaluation_date DATE,
    evaluation_score REAL,
    effectiveness_rating TEXT CHECK(effectiveness_rating IN ('EXCELLENT', 'GOOD', 'SATISFACTORY', 'NEEDS_IMPROVEMENT')),
    
    -- Reporting
    reports_to TEXT, -- e.g., "Full Board", "Shareholders"
    reporting_frequency TEXT,
    last_report_date DATE,
    next_report_due DATE,
    
    -- Status
    is_active BOOLEAN DEFAULT 1,
    activation_date DATE,
    deactivation_date DATE,
    deactivation_reason TEXT,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (chairman_id) REFERENCES board_members(id),
    FOREIGN KEY (secretary_id) REFERENCES board_members(id)
);

CREATE TABLE IF NOT EXISTS committee_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    committee_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    role VARCHAR(50) DEFAULT 'MEMBER',
    joined_date DATE,
    FOREIGN KEY (committee_id) REFERENCES board_committees(id),
    FOREIGN KEY (member_id) REFERENCES board_members(id)
);

CREATE TABLE IF NOT EXISTS board_meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_type VARCHAR(50) CHECK (meeting_type IN ('BOARD', 'AUDIT_COMMITTEE', 'RISK_COMMITTEE', 'COMPLIANCE_COMMITTEE', 'NOMREM_COMMITTEE')),
    committee_id INTEGER,
    meeting_date DATE NOT NULL,
    meeting_time TIME,
    location VARCHAR(255),
    agenda TEXT,
    minutes_file VARCHAR(500),
    quorum_met BOOLEAN DEFAULT 0,
    status VARCHAR(20) DEFAULT 'SCHEDULED',
    FOREIGN KEY (committee_id) REFERENCES board_committees(id)
);

CREATE TABLE IF NOT EXISTS meeting_attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    attended BOOLEAN DEFAULT 0,
    apology_received BOOLEAN DEFAULT 0,
    proxy_name VARCHAR(255),
    FOREIGN KEY (meeting_id) REFERENCES board_meetings(id),
    FOREIGN KEY (member_id) REFERENCES board_members(id)
);

CREATE TABLE IF NOT EXISTS board_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL,
    decision_number VARCHAR(50),
    decision_text TEXT NOT NULL,
    responsible_person VARCHAR(255),
    deadline DATE,
    status VARCHAR(20) DEFAULT 'PENDING',
    completion_date DATE,
    FOREIGN KEY (meeting_id) REFERENCES board_meetings(id)
);

CREATE TABLE IF NOT EXISTS fit_proper_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER,
    assessment_date DATE,
    assessment_type VARCHAR(50) NOT NULL CHECK (assessment_type IN ('PERIODIC', 'AD_HOC')),
    assessment_period VARCHAR(50),
    honesty_integrity_score INTEGER,
    competence_capability_score INTEGER,
    financial_soundness_score INTEGER,
    reputation_score INTEGER,
    time_commitment_score INTEGER,
    criminal_record_check BOOLEAN DEFAULT 0,
    criminal_record_clear BOOLEAN DEFAULT 1,
    criminal_record_details TEXT,
    credit_check BOOLEAN DEFAULT 0,
    credit_score INTEGER,
    credit_check_clear BOOLEAN DEFAULT 1,
    regulatory_actions_check BOOLEAN DEFAULT 0,
    regulatory_actions_found BOOLEAN DEFAULT 0,
    regulatory_actions_details TEXT,
    litigation_check BOOLEAN DEFAULT 0,
    active_litigation BOOLEAN DEFAULT 0,
    litigation_details TEXT,
    bankruptcy_check BOOLEAN DEFAULT 0,
    bankruptcy_history BOOLEAN DEFAULT 0,
    bankruptcy_details TEXT,
    references_checked BOOLEAN DEFAULT 0,
    references_satisfactory BOOLEAN DEFAULT 1,
    references_summary TEXT,
    qualifications_verified BOOLEAN DEFAULT 0,
    professional_licenses_valid BOOLEAN DEFAULT 1,
    relevant_experience_years INTEGER DEFAULT 0,
    board_experience_adequate BOOLEAN DEFAULT 1,
    total_score INTEGER,
    assessment_result VARCHAR(50) DEFAULT 'APPROVED',
    conditions_imposed TEXT,
    submitted_to_cbe BOOLEAN DEFAULT 0,
    cbe_submission_date DATE,
    cbe_reference_number VARCHAR(100),
    next_review_date DATE,
    assessment_report_path VARCHAR(500),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER,
    FOREIGN KEY (member_id) REFERENCES board_members(id),
    FOREIGN KEY (created_by) REFERENCES users(id)
);

-- =====================================================================
-- WHISTLEBLOWING MODULE
-- =====================================================================

CREATE TABLE IF NOT EXISTS whistleblowing_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_number VARCHAR(50) UNIQUE NOT NULL,
    receipt_code VARCHAR(20) UNIQUE NOT NULL,
    submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_anonymous BOOLEAN DEFAULT 1,
    reporter_name VARCHAR(255),
    reporter_email VARCHAR(255),
    reporter_phone VARCHAR(50),
    reporter_contact_method VARCHAR(50),
    category VARCHAR(100) NOT NULL CHECK (category IN ('FRAUD', 'CORRUPTION', 'CONFLICT_OF_INTEREST', 'HARASSMENT', 'DISCRIMINATION', 'SAFETY', 'DATA_BREACH', 'COMPLIANCE', 'OTHER')),
    description TEXT NOT NULL,
    persons_involved TEXT,
    evidence_files TEXT,
    assigned_investigator_id INTEGER,
    assignment_date DATE,
    investigation_notes TEXT,
    investigation_findings TEXT,
    outcome VARCHAR(50) CHECK (outcome IN ('SUBSTANTIATED', 'UNSUBSTANTIATED', 'INSUFFICIENT_INFO', 'REFERRED')),
    actions_taken TEXT,
    status VARCHAR(20) DEFAULT 'NEW' CHECK (status IN ('NEW', 'UNDER_INVESTIGATION', 'PENDING_DECISION', 'CLOSED_SUBSTANTIATED', 'CLOSED_UNSUBSTANTIATED', 'CLOSED_INSUFFICIENT_INFO')),
    closure_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assigned_investigator_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS whistleblowing_communications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    communication_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sender_type VARCHAR(20) CHECK (sender_type IN ('REPORTER', 'INVESTIGATOR')),
    message TEXT NOT NULL,
    attachment_file VARCHAR(500),
    is_read BOOLEAN DEFAULT 0,
    FOREIGN KEY (case_id) REFERENCES whistleblowing_cases(id)
);
-- Required Policies for Gap Analysis
CREATE TABLE IF NOT EXISTS required_policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_name_en VARCHAR(200) NOT NULL,
    policy_name_ar VARCHAR(200),
    regulatory_reference VARCHAR(200),
    is_mandatory BOOLEAN DEFAULT 1,
    description_en TEXT,
    description_ar TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_required_policies_name ON required_policies(policy_name_en);

-- Auto-Assignment Rules
CREATE TABLE IF NOT EXISTS training_requirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role VARCHAR(50),
    department VARCHAR(50),
    course_id INTEGER,
    policy_id INTEGER,
    is_mandatory BOOLEAN DEFAULT 1,
    deadline_days INTEGER DEFAULT 30,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (course_id) REFERENCES training_courses(id),
    FOREIGN KEY (policy_id) REFERENCES policies(id)
);


-- =====================================================================
-- PRODUCTION SCREENING MODULE TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS screening_watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id VARCHAR(100) UNIQUE,
    full_name TEXT NOT NULL,
    original_name TEXT,
    name_normalized TEXT,
    name_soundex VARCHAR(10),
    name_metaphone VARCHAR(10),
    list_type VARCHAR(50),
    dataset VARCHAR(100),
    source VARCHAR(100),
    source_url TEXT,
    risk_level VARCHAR(50),
    topics TEXT,
    countries TEXT,
    date_of_birth DATE,
    year_of_birth INTEGER,
    nationality VARCHAR(100),
    gender VARCHAR(10),
    aliases TEXT,
    details TEXT,
    entity_type VARCHAR(20) DEFAULT 'INDIVIDUAL', -- INDIVIDUAL, ENTITY
    is_active BOOLEAN DEFAULT 1,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_watchlist_normalized ON screening_watchlist(name_normalized);
CREATE INDEX IF NOT EXISTS idx_watchlist_soundex ON screening_watchlist(name_soundex);
CREATE INDEX IF NOT EXISTS idx_watchlist_metaphone ON screening_watchlist(name_metaphone);

CREATE TABLE IF NOT EXISTS screening_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    type VARCHAR(50) DEFAULT 'FTJSON',
    url TEXT,
    is_active BOOLEAN DEFAULT 1,
    last_updated_at TIMESTAMP,
    last_updated_by INTEGER
);

CREATE TABLE IF NOT EXISTS screening_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key VARCHAR(100) UNIQUE NOT NULL,
    config_value TEXT,
    category VARCHAR(50),
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS screening_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screening_type VARCHAR(50),
    screened_name TEXT,
    screened_dob DATE,
    screening_method VARCHAR(50),
    total_matches_found INTEGER,
    highest_match_score DECIMAL(5,2),
    screening_result VARCHAR(50),
    status VARCHAR(20) DEFAULT 'PENDING', -- PENDING, TRUE_HIT, FALSE_POSITIVE
    resolution_notes TEXT,
    resolved_by INTEGER,
    resolved_at TIMESTAMP,
    matches TEXT, -- JSON string in SQLite
    processing_time_ms INTEGER,
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- INITIAL SEED DATA FOR SCREENING
INSERT OR IGNORE INTO screening_config (config_key, config_value, category, description) VALUES
('fuzzy_ratio_weight', '0.40', 'weights', 'Weight for Levenshtein fuzzy ratio'),
('jaro_winkler_weight', '0.30', 'weights', 'Weight for Jaro-Winkler algorithm'),
('phonetic_weight', '0.20', 'weights', 'Weight for Soundex/Metaphone phonetic'),
('partial_ratio_weight', '0.10', 'weights', 'Weight for partial substring matching'),
('exact_match_favoritism', '25.0', 'bonus', 'Bonus for exact token matches'),
('dob_exact_match_bonus', '10.0', 'bonus', 'Bonus for exact DOB match'),
('dob_mismatch_penalty', '-10.0', 'penalty', 'Penalty for DOB mismatch'),
('nationality_bonus', '5.0', 'bonus', 'Bonus for nationality match'),
('confirmed_hit_threshold', '95.0', 'thresholds', 'Threshold for confirmed hit'),
('potential_match_threshold', '80.0', 'thresholds', 'Threshold for potential match'),
('low_match_threshold', '70.0', 'thresholds', 'Threshold for low match');

INSERT OR IGNORE INTO screening_sources (name, type, url) VALUES
('OpenSanctions (Baseline Aggregated)', 'FTJSON', 'https://data.opensanctions.org/datasets/latest/default/entities.ftm.json'),
('UN Consolidated List (Direct)', 'FTJSON', 'https://data.opensanctions.org/datasets/latest/un_sc_sanctions/entities.ftm.json'),
('US OFAC SDN (Direct)', 'FTJSON', 'https://data.opensanctions.org/datasets/latest/us_ofac_sdn/entities.ftm.json'),
('EU Financial Sanctions (Direct)', 'FTJSON', 'https://data.opensanctions.org/datasets/latest/eu_fsf/entities.ftm.json'),
('UK HMT Sanctions (Direct)', 'FTJSON', 'https://data.opensanctions.org/datasets/latest/gb_hmt/entities.ftm.json'),
('EMLCU Egypt Terrorist List', 'EMLCU_SCRAPER', NULL);

-- WHITELIST FOR FALSE POSITIVES
CREATE TABLE IF NOT EXISTS screening_whitelist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    normalized_name VARCHAR(255) UNIQUE NOT NULL,
    reason TEXT,
    added_by INTEGER,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- WATCHLIST SCREENING MODULE
-- ============================================================================

CREATE TABLE IF NOT EXISTS screening_watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Identity
    full_name VARCHAR(500) NOT NULL,
    original_name VARCHAR(500),  -- Arabic or non-Latin script
    aliases TEXT,  -- JSON Array of alternative names
    
    -- Entity Type
    entity_type VARCHAR(20),  -- 'PERSON', 'ORGANIZATION', 'VESSEL', 'AIRCRAFT'
    
    -- Classification
    list_type VARCHAR(50) NOT NULL,  -- 'SANCTIONS', 'PEP', 'WANTED', 'CRIME'
    dataset VARCHAR(100) NOT NULL,   -- Source dataset
    topics TEXT,  -- JSON Array
    
    -- Personal Information
    date_of_birth DATE,
    year_of_birth INTEGER,
    place_of_birth VARCHAR(200),
    gender VARCHAR(10),  -- 'MALE', 'FEMALE'
    
    -- Geographic
    countries TEXT, -- JSON Array
    nationality VARCHAR(100),
    
    -- Identifiers
    passport_numbers TEXT, -- JSON Array
    national_id_numbers TEXT, -- JSON Array
    
    -- Addresses
    addresses TEXT, -- JSON
    
    -- Source Information
    source VARCHAR(100) NOT NULL,  -- 'opensanctions', 'un', 'ofac', 'eu', 'hmt', 'emlcu'
    source_id VARCHAR(200),
    source_url TEXT,
    first_seen DATE,
    last_seen DATE,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Search Optimization
    name_normalized VARCHAR(500),  -- Uppercase, no special chars
    name_soundex VARCHAR(20),
    name_metaphone VARCHAR(20),
    name_tokens TEXT, -- JSON Array
    
    -- Risk
    risk_level VARCHAR(20),  -- 'EXTREME', 'HIGH', 'MEDIUM', 'LOW'
    
    -- Metadata
    properties TEXT, -- JSON
    
    -- System
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_watchlist_name_norm ON screening_watchlist(name_normalized);
CREATE INDEX IF NOT EXISTS idx_watchlist_soundex ON screening_watchlist(name_soundex);
CREATE INDEX IF NOT EXISTS idx_watchlist_metaphone ON screening_watchlist(name_metaphone);
CREATE INDEX IF NOT EXISTS idx_watchlist_source ON screening_watchlist(source);
CREATE INDEX IF NOT EXISTS idx_watchlist_dataset ON screening_watchlist(dataset);
CREATE INDEX IF NOT EXISTS idx_watchlist_list_type ON screening_watchlist(list_type);

CREATE TABLE IF NOT EXISTS screening_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_query VARCHAR(255) NOT NULL,
    screened_by INTEGER,
    screening_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    screening_result VARCHAR(20) CHECK (screening_result IN ('CLEAR', 'POTENTIAL_MATCH', 'CONFIRMED_HIT')),
    algorithm_config TEXT, -- JSON
    matches_found TEXT, -- JSON
    notes TEXT,
    status VARCHAR(20) DEFAULT 'NEW',
    FOREIGN KEY (screened_by) REFERENCES users(id)
);

 
 - -   = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =  
 - -   A U D I T   L O G   ( E n h a n c e m e n t )  
 - -   = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =  
 C R E A T E   T A B L E   I F   N O T   E X I S T S   d a t a _ u p d a t e _ a u d i t _ l o g   (  
         i d   I N T E G E R   P R I M A R Y   K E Y   A U T O I N C R E M E N T ,  
         u p d a t e _ t y p e   V A R C H A R ( 5 0 )   D E F A U L T   ' F U L L _ U P D A T E ' ,  
         i n i t i a t e d _ b y   I N T E G E R ,  
         t o t a l _ s o u r c e s   I N T E G E R ,  
         r e c o r d s _ a d d e d   I N T E G E R   D E F A U L T   0 ,  
         r e c o r d s _ u p d a t e d   I N T E G E R   D E F A U L T   0 ,  
         r e c o r d s _ u n c h a n g e d   I N T E G E R   D E F A U L T   0 ,  
         e r r o r s _ c o u n t   I N T E G E R   D E F A U L T   0 ,  
         s t a t u s   V A R C H A R ( 2 0 )   D E F A U L T   ' I N _ P R O G R E S S ' ,  
         s t a r t e d _ a t   T I M E S T A M P   D E F A U L T   C U R R E N T _ T I M E S T A M P ,  
         c o m p l e t e d _ a t   T I M E S T A M P   N U L L ,  
         d u r a t i o n _ s e c o n d s   I N T E G E R   N U L L ,  
         e r r o r _ m e s s a g e   T E X T   N U L L ,  
         F O R E I G N   K E Y   ( i n i t i a t e d _ b y )   R E F E R E N C E S   u s e r s ( i d )  
 ) ;  
  
 C R E A T E   I N D E X   I F   N O T   E X I S T S   i d x _ a u d i t _ l o g _ s t a t u s   O N   d a t a _ u p d a t e _ a u d i t _ l o g ( s t a t u s ) ;  
 C R E A T E   I N D E X   I F   N O T   E X I S T S   i d x _ a u d i t _ l o g _ s t a r t e d   O N   d a t a _ u p d a t e _ a u d i t _ l o g ( s t a r t e d _ a t   D E S C ) ;  
  
 - -   = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =  
 - -   W A T C H L I S T   S C R E E N I N G   ( E n h a n c e m e n t )  
 - -   = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =  
  
 C R E A T E   T A B L E   I F   N O T   E X I S T S   s c r e e n i n g _ d a t a _ s o u r c e s   (  
         i d   I N T E G E R   P R I M A R Y   K E Y   A U T O I N C R E M E N T ,  
         n a m e   V A R C H A R ( 1 0 0 )   N O T   N U L L ,  
         t y p e   V A R C H A R ( 2 0 )   N O T   N U L L ,  
         s o u r c e _ u r l   V A R C H A R ( 5 0 0 ) ,  
         i s _ a c t i v e   B O O L E A N   D E F A U L T   1 ,  
         p r i o r i t y   I N T E G E R   D E F A U L T   0 ,  
         l a s t _ s u c c e s s f u l _ u p d a t e   T I M E S T A M P  
 ) ;  
  
 C R E A T E   T A B L E   I F   N O T   E X I S T S   s c r e e n i n g _ w a t c h l i s t   (  
         i d   I N T E G E R   P R I M A R Y   K E Y   A U T O I N C R E M E N T ,  
         d a t a s e t   V A R C H A R ( 5 0 ) ,    
         n a m e   V A R C H A R ( 5 0 0 ) ,  
         a l i a s e s   T E X T ,  
         t y p e   V A R C H A R ( 5 0 ) ,  
         s o u r c e   V A R C H A R ( 5 0 ) ,  
         l i s t _ t y p e   V A R C H A R ( 5 0 ) ,  
         r e f e r e n c e _ n u m b e r   V A R C H A R ( 1 0 0 ) ,  
         l a s t _ u p d a t e d   T I M E S T A M P   D E F A U L T   C U R R E N T _ T I M E S T A M P  
 ) ;  
  
 C R E A T E   I N D E X   I F   N O T   E X I S T S   i d x _ w a t c h l i s t _ n a m e   O N   s c r e e n i n g _ w a t c h l i s t ( n a m e ) ;  
 C R E A T E   I N D E X   I F   N O T   E X I S T S   i d x _ w a t c h l i s t _ s o u r c e   O N   s c r e e n i n g _ w a t c h l i s t ( s o u r c e ) ;  
 