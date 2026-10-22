-- Fit & proper: regulator forms (data-driven), key officials registry, committee
-- links for non-board committee members, signed copies and the regulator decision.
BEGIN;

CREATE TABLE IF NOT EXISTS fp_officials (
    id              SERIAL PRIMARY KEY,
    full_name       VARCHAR(200) NOT NULL,
    full_name_ar    VARCHAR(200),
    official_type   VARCHAR(20)  NOT NULL DEFAULT 'executive'
                    CHECK (official_type IN ('board', 'executive', 'committee_external')),
    board_member_id INTEGER REFERENCES board_members(id) ON DELETE SET NULL,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    key_function    VARCHAR(60),
    position_title  VARCHAR(200),
    email           VARCHAR(200),
    phone           VARCHAR(60),
    nationality     VARCHAR(100),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS fp_officials_board_uniq ON fp_officials(board_member_id) WHERE board_member_id IS NOT NULL;

-- committee seats of officials who are not board members (board members keep using committee_memberships)
CREATE TABLE IF NOT EXISTS fp_official_committees (
    id           SERIAL PRIMARY KEY,
    official_id  INTEGER NOT NULL REFERENCES fp_officials(id) ON DELETE CASCADE,
    committee_id INTEGER NOT NULL REFERENCES board_committees(id) ON DELETE CASCADE,
    role         VARCHAR(30) NOT NULL DEFAULT 'MEMBER',
    joined_on    DATE,
    left_on      DATE,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (official_id, committee_id)
);

CREATE TABLE IF NOT EXISTS fp_forms (
    id                  SERIAL PRIMARY KEY,
    reference           VARCHAR(30) UNIQUE,
    template_code       VARCHAR(60) NOT NULL,
    official_id         INTEGER NOT NULL REFERENCES fp_officials(id) ON DELETE CASCADE,
    purpose             VARCHAR(30) NOT NULL DEFAULT 'new_nomination'
                        CHECK (purpose IN ('licensing', 'new_nomination', 'change', 'annual_review', 'committee')),
    committee_id        INTEGER REFERENCES board_committees(id) ON DELETE SET NULL,
    status              VARCHAR(30) NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'candidate_completed', 'under_review', 'approved_internal',
                                          'signed', 'submitted', 'regulator_approved', 'regulator_rejected',
                                          'withdrawn')),
    answers             JSONB NOT NULL DEFAULT '{}'::jsonb,
    assessment          JSONB NOT NULL DEFAULT '{}'::jsonb,
    assessment_score    NUMERIC(4,2),
    assessment_result   VARCHAR(30) CHECK (assessment_result IS NULL OR assessment_result IN
                                           ('fit', 'fit_with_conditions', 'not_fit')),
    conditions          TEXT,
    reviewed_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at         TIMESTAMP,
    approved_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_at         TIMESTAMP,
    signed_attachment_id INTEGER,
    signed_at           TIMESTAMP,
    submitted_at        TIMESTAMP,
    regulator_reference VARCHAR(100),
    regulator_decision_on DATE,
    regulator_notes     TEXT,
    next_review_date    DATE,
    created_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fp_forms_official_idx ON fp_forms(official_id);

CREATE TABLE IF NOT EXISTS fp_form_events (
    id          SERIAL PRIMARY KEY,
    form_id     INTEGER NOT NULL REFERENCES fp_forms(id) ON DELETE CASCADE,
    action      VARCHAR(40) NOT NULL,
    status_from VARCHAR(30),
    status_to   VARCHAR(30),
    note        TEXT,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT now()
);

ALTER TABLE board_committees ADD COLUMN IF NOT EXISTS requires_fit_proper BOOLEAN NOT NULL DEFAULT TRUE;

GRANT SELECT, INSERT, UPDATE, DELETE ON fp_officials, fp_official_committees, fp_forms, fp_form_events TO complynex;
GRANT USAGE, SELECT ON SEQUENCE fp_officials_id_seq, fp_official_committees_id_seq, fp_forms_id_seq, fp_form_events_id_seq TO complynex;
COMMIT;
