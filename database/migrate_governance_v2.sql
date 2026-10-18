-- Migration script for Governance and User Access Enhancements

-- 1. Update board_members table
ALTER TABLE board_members ADD COLUMN document_path VARCHAR(500);

-- 2. Update users table with modular permissions
ALTER TABLE users ADD COLUMN perm_governance VARCHAR(20) DEFAULT 'none' CHECK (perm_governance IN ('none', 'view', 'edit'));
ALTER TABLE users ADD COLUMN perm_aml VARCHAR(20) DEFAULT 'none' CHECK (perm_aml IN ('none', 'view', 'edit'));
ALTER TABLE users ADD COLUMN perm_policies VARCHAR(20) DEFAULT 'none' CHECK (perm_policies IN ('none', 'view', 'edit'));
ALTER TABLE users ADD COLUMN perm_reports VARCHAR(20) DEFAULT 'none' CHECK (perm_reports IN ('none', 'view', 'edit'));
ALTER TABLE users ADD COLUMN perm_pdpl VARCHAR(20) DEFAULT 'none' CHECK (perm_pdpl IN ('none', 'view', 'edit'));
ALTER TABLE users ADD COLUMN perm_training VARCHAR(20) DEFAULT 'none' CHECK (perm_training IN ('none', 'view', 'edit'));

-- 3. Update board_meetings (Recreate to change CHECK constraint)
CREATE TABLE board_meetings_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_type VARCHAR(50) CHECK (meeting_type IN ('BOARD', 'AUDIT_COMMITTEE', 'RISK_COMMITTEE', 'COMPLIANCE_COMMITTEE', 'NOMREM_COMMITTEE', 'REGULAR', 'EXTRAORDINARY', 'EMERGENCY')),
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

INSERT INTO board_meetings_new (id, meeting_type, committee_id, meeting_date, meeting_time, location, agenda, minutes_file, quorum_met, status)
SELECT id, meeting_type, committee_id, meeting_date, meeting_time, location, agenda, minutes_file, quorum_met, status FROM board_meetings;

DROP TABLE board_meetings;
ALTER TABLE board_meetings_new RENAME TO board_meetings;

-- 4. Update board_committees (Recreate to remove restrictive CHECK constraint)
CREATE TABLE board_committees_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    committee_name VARCHAR(255) NOT NULL,
    committee_type VARCHAR(100), -- Removed CHECK constraint to allow dynamic types
    chairman_id INTEGER,
    charter_file VARCHAR(500),
    meeting_frequency VARCHAR(50),
    is_active BOOLEAN DEFAULT 1,
    FOREIGN KEY (chairman_id) REFERENCES board_members(id)
);

INSERT INTO board_committees_new (id, committee_name, committee_type, chairman_id, charter_file, meeting_frequency, is_active)
SELECT id, committee_name, committee_type, chairman_id, charter_file, meeting_frequency, is_active FROM board_committees;

DROP TABLE board_committees;
ALTER TABLE board_committees_new RENAME TO board_committees;
