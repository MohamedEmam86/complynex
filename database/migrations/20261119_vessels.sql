-- V1 vessel screening: listed ships (screening_watchlist.entity_type = 'VESSEL') materialised for the
-- vessel engine and the Vessels Database page, flag risk reference, vessel screenings, the analyst's
-- validation of each hit (reason + comment, audited), the vessel whitelist (keyed by IMO, re-opened when
-- the name / flag / owner changes) and the per-user permission users.perm_vessels.
-- Additive only: no existing column changes. The ships themselves stay in screening_watchlist.
-- Idempotent: safe to run twice.
BEGIN;
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS vessel_profile (
    watchlist_id    INTEGER PRIMARY KEY,                 -- screening_watchlist.id
    source          VARCHAR(60),
    imo             VARCHAR(10),
    imo_valid       BOOLEAN,
    mmsi            VARCHAR(12),
    call_sign       VARCHAR(20),
    vessel_type     TEXT,
    current_flag    TEXT,
    flag_history    TEXT,                                -- JSON list of former / other flags
    previous_names  TEXT,                                -- JSON list
    gross_tonnage   VARCHAR(40),
    year_built      VARCHAR(10),
    measures        TEXT,                                -- JSON list: asset_freeze, port_ban, deflag ...
    owners          TEXT,                                -- JSON list [{name, role, ref}] as listed
    group_key       VARCHAR(40),                         -- 'IMO:<n>' (same ship on several lists) or 'WL:<id>'
    risk_score      INTEGER NOT NULL DEFAULT 0,          -- risk indicators of the listed ship (0-100)
    risk_lines      TEXT,                                -- JSON list of indicator codes
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS group_key VARCHAR(40);
ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS risk_score INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS risk_lines TEXT;
CREATE INDEX IF NOT EXISTS idx_vessel_profile_group ON vessel_profile (group_key);
CREATE INDEX IF NOT EXISTS idx_vessel_profile_imo  ON vessel_profile (imo);
CREATE INDEX IF NOT EXISTS idx_vessel_profile_flag ON vessel_profile (lower(current_flag));

CREATE TABLE IF NOT EXISTS vessel_identifier (
    id            BIGSERIAL PRIMARY KEY,
    watchlist_id  INTEGER NOT NULL,
    kind          VARCHAR(10) NOT NULL,                  -- IMO | MMSI | CALLSIGN
    value_norm    VARCHAR(20) NOT NULL,
    is_current    BOOLEAN NOT NULL DEFAULT TRUE,
    check_ok      BOOLEAN,                               -- IMO check digit / MMSI ship MID
    source        VARCHAR(60),
    UNIQUE (watchlist_id, kind, value_norm)
);
CREATE INDEX IF NOT EXISTS idx_vessel_identifier_value ON vessel_identifier (kind, value_norm);

CREATE TABLE IF NOT EXISTS vessel_party_link (
    id                  BIGSERIAL PRIMARY KEY,
    watchlist_id        INTEGER NOT NULL,                -- the ship
    party_watchlist_id  INTEGER,                         -- the owner's own listed record, when known
    party_name          TEXT,
    role                VARCHAR(30) NOT NULL DEFAULT 'owner',
    source              VARCHAR(60)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_vessel_party_link
    ON vessel_party_link (watchlist_id, role, coalesce(party_name, ''), coalesce(party_watchlist_id, 0));

CREATE TABLE IF NOT EXISTS flag_risk (
    country              TEXT PRIMARY KEY,               -- flag state as lists write it (English)
    iso2                 CHAR(2),
    flag_of_convenience  BOOLEAN NOT NULL DEFAULT FALSE,
    high_risk            BOOLEAN NOT NULL DEFAULT FALSE,  -- e.g. registries used by sanctioned / dark-fleet ships
    note                 TEXT,
    updated_by           INTEGER,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE flag_risk ADD COLUMN IF NOT EXISTS high_risk BOOLEAN NOT NULL DEFAULT FALSE;
-- Reference seed: open registries commonly listed as flags of convenience (ITF list). A risk indicator only,
-- never a match; editable. TODO(compliance-review): confirm the list in force before relying on it.
INSERT INTO flag_risk (country, iso2, flag_of_convenience, note) VALUES
 ('Antigua and Barbuda','AG',TRUE,'open registry'), ('Bahamas','BS',TRUE,'open registry'),
 ('Barbados','BB',TRUE,'open registry'), ('Belize','BZ',TRUE,'open registry'),
 ('Bermuda','BM',TRUE,'open registry'), ('Bolivia','BO',TRUE,'open registry'),
 ('Cambodia','KH',TRUE,'open registry'), ('Cameroon','CM',TRUE,'open registry'),
 ('Cayman Islands','KY',TRUE,'open registry'), ('Comoros','KM',TRUE,'open registry'),
 ('Cook Islands','CK',TRUE,'open registry'), ('Cyprus','CY',TRUE,'open registry'),
 ('Equatorial Guinea','GQ',TRUE,'open registry'), ('Gabon','GA',TRUE,'open registry'),
 ('Georgia','GE',TRUE,'open registry'), ('Gibraltar','GI',TRUE,'open registry'),
 ('Honduras','HN',TRUE,'open registry'), ('Jamaica','JM',TRUE,'open registry'),
 ('Lebanon','LB',TRUE,'open registry'), ('Liberia','LR',TRUE,'open registry'),
 ('Malta','MT',TRUE,'open registry'), ('Marshall Islands','MH',TRUE,'open registry'),
 ('Mauritius','MU',TRUE,'open registry'), ('Moldova','MD',TRUE,'open registry'),
 ('Mongolia','MN',TRUE,'open registry'), ('Myanmar','MM',TRUE,'open registry'),
 ('North Korea','KP',TRUE,'open registry'), ('Palau','PW',TRUE,'open registry'),
 ('Panama','PA',TRUE,'open registry'), ('Saint Kitts and Nevis','KN',TRUE,'open registry'),
 ('Saint Vincent and the Grenadines','VC',TRUE,'open registry'),
 ('Sao Tome and Principe','ST',TRUE,'open registry'), ('Sierra Leone','SL',TRUE,'open registry'),
 ('Sri Lanka','LK',TRUE,'open registry'), ('Tanzania','TZ',TRUE,'open registry'),
 ('Togo','TG',TRUE,'open registry'), ('Tonga','TO',TRUE,'open registry'),
 ('Vanuatu','VU',TRUE,'open registry'), ('Eswatini','SZ',TRUE,'open registry')
ON CONFLICT (country) DO NOTHING;
-- flag states that raise risk without being open registries: comprehensively sanctioned states and registries
-- reported as used by sanctioned / shadow-fleet tankers. TODO(compliance-review): confirm before relying on it.
INSERT INTO flag_risk (country, iso2, flag_of_convenience, high_risk, note) VALUES
 ('Iran','IR',FALSE,TRUE,'comprehensively sanctioned state'), ('Syria','SY',FALSE,TRUE,'sanctioned state'),
 ('Guyana','GY',FALSE,TRUE,'registry used by sanctioned tankers'),
 ('Benin','BJ',FALSE,TRUE,'registry used by sanctioned tankers'),
 ('Gambia','GM',FALSE,TRUE,'registry used by sanctioned tankers'),
 ('Djibouti','DJ',FALSE,TRUE,'registry used by sanctioned tankers'),
 ('Malawi','MW',FALSE,TRUE,'registry used by sanctioned tankers')
ON CONFLICT (country) DO NOTHING;
UPDATE flag_risk SET high_risk = TRUE WHERE iso2 = 'KP' AND NOT high_risk;
-- an early draft of this file seeded these two as open registries
UPDATE flag_risk SET flag_of_convenience = FALSE, high_risk = TRUE
 WHERE iso2 IN ('GY', 'BJ') AND flag_of_convenience AND note = 'registry used by sanctioned tankers';

CREATE TABLE IF NOT EXISTS vessel_screenings (
    id            BIGSERIAL PRIMARY KEY,
    user_id       INTEGER,
    kind          VARCHAR(10) NOT NULL DEFAULT 'single',  -- single | bulk | api
    bulk_id       BIGINT,
    customer_ref  VARCHAR(200),
    query         JSONB NOT NULL,
    result        JSONB NOT NULL,
    tier          VARCHAR(20),
    hit_count     INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_vessel_screenings_user ON vessel_screenings (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_vessel_screenings_bulk ON vessel_screenings (bulk_id);

CREATE TABLE IF NOT EXISTS vessel_bulk_jobs (
    id          BIGSERIAL PRIMARY KEY,
    user_id     INTEGER,
    filename    TEXT,
    row_count   INTEGER NOT NULL DEFAULT 0,
    hit_rows    INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- the analyst validates each hit himself: true / false match, a reason and a comment (both required)
CREATE TABLE IF NOT EXISTS vessel_hit_decisions (
    id            BIGSERIAL PRIMARY KEY,
    screening_id  BIGINT NOT NULL,
    watchlist_id  INTEGER NOT NULL,
    decision      VARCHAR(20) NOT NULL CHECK (decision IN ('true_match', 'false_match')),
    reason        VARCHAR(80) NOT NULL,
    comment       TEXT NOT NULL CHECK (length(btrim(comment)) >= 5),
    query_key     TEXT,                                   -- IMO / MMSI / name + flag of the screened ship
    candidate_fp  CHAR(40),                               -- identity of the listed ship when decided
    decided_by    INTEGER NOT NULL,
    decided_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE vessel_hit_decisions ADD COLUMN IF NOT EXISTS listed_key VARCHAR(40);   -- IMO:<n> / WL:<id>
ALTER TABLE vessel_hit_decisions ADD COLUMN IF NOT EXISTS hit_kind VARCHAR(10) NOT NULL DEFAULT 'ship';  -- ship | owner
ALTER TABLE vessel_hit_decisions ALTER COLUMN watchlist_id DROP NOT NULL;
ALTER TABLE vessel_hit_decisions ADD COLUMN IF NOT EXISTS query_fp CHAR(40);        -- screened ship name/flag/owner

-- vessel whitelist: a false match cleared for a screened ship (IMO, else MMSI / name + flag) against one listed
-- ship. It suppresses that hit on later screenings only while both sides keep their name / flag / owner: any
-- change re-opens the hit (status 'reopened', with the reason) and it must be validated again.
CREATE TABLE IF NOT EXISTS vessel_whitelist (
    id              BIGSERIAL PRIMARY KEY,
    query_key       TEXT NOT NULL,
    listed_key      VARCHAR(40) NOT NULL,
    watchlist_id    INTEGER,
    listed_name     TEXT,
    listed_fp       CHAR(40) NOT NULL,
    query_fp        CHAR(40) NOT NULL,
    query_label     TEXT,
    decision_id     BIGINT,
    reason          VARCHAR(80) NOT NULL,
    comment         TEXT NOT NULL,
    status          VARCHAR(12) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'reopened', 'revoked')),
    created_by      INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    reopened_at     TIMESTAMPTZ,
    reopened_reason TEXT,
    revoked_by      INTEGER,
    revoked_at      TIMESTAMPTZ,
    revoke_reason   TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_vessel_whitelist_active
    ON vessel_whitelist (query_key, listed_key) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_vessel_whitelist_listed ON vessel_whitelist (listed_key);

-- per-user permission (none | view | edit): view = screen and browse, edit = validate hits, bulk files
ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_vessels VARCHAR(10) DEFAULT 'none';
CREATE INDEX IF NOT EXISTS idx_vessel_decisions_scr ON vessel_hit_decisions (screening_id);
CREATE INDEX IF NOT EXISTS idx_vessel_decisions_key ON vessel_hit_decisions (query_key, watchlist_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON vessel_profile, vessel_identifier, vessel_party_link, flag_risk,
      vessel_screenings, vessel_bulk_jobs, vessel_hit_decisions, vessel_whitelist TO complynex;
GRANT USAGE, SELECT ON SEQUENCE vessel_identifier_id_seq, vessel_party_link_id_seq, vessel_screenings_id_seq,
      vessel_bulk_jobs_id_seq, vessel_hit_decisions_id_seq, vessel_whitelist_id_seq TO complynex;
COMMIT;
