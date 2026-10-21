--
-- PostgreSQL database dump
--

\restrict l01wf1xteiRe6o2Chx0dhIKETw5FwhgmCwLfUUXLi4UuKya9juVRl9C9ampLjca

-- Dumped from database version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: fuzzystrmatch; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS fuzzystrmatch WITH SCHEMA public;


--
-- Name: EXTENSION fuzzystrmatch; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION fuzzystrmatch IS 'determine similarities and distance between strings';


--
-- Name: pg_stat_statements; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;


--
-- Name: EXTENSION pg_stat_statements; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_stat_statements IS 'track planning and execution statistics of all SQL statements executed';


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: audit_logs_chain(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.audit_logs_chain() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('audit_logs_chain'));
  NEW.id := nextval('audit_logs_id_seq');          -- allocated under the lock
  SELECT row_hash INTO NEW.prev_hash FROM audit_logs ORDER BY id DESC LIMIT 1;
  NEW.row_hash := audit_logs_row_digest(NEW.prev_hash, NEW);
  RETURN NEW;
END $$;


--
-- Name: audit_logs_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.audit_logs_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  RAISE EXCEPTION 'audit_logs is append-only (% refused)', TG_OP;
END $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    user_id integer,
    action text,
    module text,
    item_id integer,
    details text,
    ip_address text,
    created_at text,
    prev_hash text,
    row_hash text
);


--
-- Name: audit_logs_row_digest(text, public.audit_logs); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.audit_logs_row_digest(p_prev text, r public.audit_logs) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT encode(sha256(convert_to(concat_ws('|',
         COALESCE(p_prev, 'GENESIS'), r.id::text,
         COALESCE(r.user_id::text, '<null>'), COALESCE(r.action, '<null>'),
         COALESCE(r.module, '<null>'), COALESCE(r.item_id::text, '<null>'),
         COALESCE(r.details, '<null>'), COALESCE(r.ip_address, '<null>'),
         COALESCE(r.created_at, '<null>')), 'UTF8')), 'hex')
$$;


--
-- Name: audit_logs_verify(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.audit_logs_verify() RETURNS TABLE(broken_id integer, checked bigint)
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE rec audit_logs; prev TEXT := NULL; n BIGINT := 0;
BEGIN
  FOR rec IN SELECT * FROM audit_logs ORDER BY id LOOP
    n := n + 1;
    IF rec.row_hash IS DISTINCT FROM audit_logs_row_digest(prev, rec)
       OR rec.prev_hash IS DISTINCT FROM prev THEN
      broken_id := rec.id; checked := n; RETURN NEXT; RETURN;
    END IF;
    prev := rec.row_hash;
  END LOOP;
  broken_id := NULL; checked := n; RETURN NEXT;
END $$;


--
-- Name: cx_name_search(text, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cx_name_search(o text, f text, a text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
  SELECT translate(lower(coalesce(o, '') || ' ' || coalesce(f, '') || ' ' || coalesce(a, '')),
                   'أإآٱةى', 'اااايهي')
$$;


--
-- Name: fn_create_aml_alert(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_create_aml_alert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            v_alert_type    TEXT;
            v_risk_level    TEXT;
            v_creator       INTEGER;
            v_exists        INTEGER;
        BEGIN
            -- Only fire for hits that warrant an alert
            IF NEW.screening_result NOT IN (
                'CONFIRMED_HIT', 'POTENTIAL_MATCH',
                'confirmed_hit', 'potential_match',
                'HIT', 'MATCH'
            ) THEN
                RETURN NEW;
            END IF;

            -- Do not create duplicate alert for same screening_result row
            SELECT COUNT(*) INTO v_exists
            FROM aml_alerts
            WHERE screening_result_id = NEW.id;

            IF v_exists > 0 THEN
                RETURN NEW;
            END IF;

            -- Determine alert_type
            v_alert_type := CASE
                WHEN UPPER(NEW.screening_result) LIKE '%CONFIRMED%' THEN 'CONFIRMED_HIT'
                WHEN UPPER(NEW.screening_result) LIKE '%POTENTIAL%' THEN 'POTENTIAL_MATCH'
                ELSE 'POSSIBLE_MATCH'
            END;

            -- Determine risk level from score
            v_risk_level := CASE
                WHEN COALESCE(NEW.highest_match_score, 0) >= 95 THEN 'CRITICAL'
                WHEN COALESCE(NEW.highest_match_score, 0) >= 80 THEN 'HIGH'
                WHEN COALESCE(NEW.highest_match_score, 0) >= 70 THEN 'MEDIUM'
                ELSE 'LOW'
            END;

            -- Use creator only if it exists in users table, otherwise NULL
            SELECT id INTO v_creator FROM users WHERE id = NEW.created_by LIMIT 1;

            INSERT INTO aml_alerts (
                alert_type,
                alert_status,
                customer_id,
                screening_result_id,
                matched_name,
                match_score,
                source_list,
                alert_details,
                risk_level,
                false_positive,
                created_by,
                created_at
            ) VALUES (
                v_alert_type,
                'OPEN',
                NULL,
                NEW.id,
                NEW.screened_name,
                COALESCE(NEW.highest_match_score, 0),
                COALESCE(NEW.screening_method, 'WATCHLIST'),
                COALESCE(NEW.resolution_notes, 'Auto-generated from screening result'),
                v_risk_level,
                0,
                v_creator,
                COALESCE(NEW.created_at, to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'))
            );

            RETURN NEW;
        EXCEPTION WHEN OTHERS THEN
            -- Never let trigger failure break the screening insert
            RAISE WARNING 'fn_create_aml_alert failed: %', SQLERRM;
            RETURN NEW;
        END;
        $$;


--
-- Name: org_units_cascade_path(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.org_units_cascade_path() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.path IS DISTINCT FROM OLD.path THEN
        UPDATE org_units
           SET path  = NEW.path || substring(path from length(OLD.path) + 1),
               depth = NEW.depth + (depth - OLD.depth)
         WHERE path LIKE OLD.path || '_%';
    END IF;
    RETURN NULL;
END $$;


--
-- Name: org_units_set_path(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.org_units_set_path() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE ppath TEXT; pdepth INTEGER;
BEGIN
    IF NEW.parent_id IS NULL THEN
        NEW.path  := '/' || NEW.id || '/';
        NEW.depth := 0;
    ELSE
        SELECT path, depth INTO ppath, pdepth FROM org_units WHERE id = NEW.parent_id;
        IF ppath IS NULL THEN
            RAISE EXCEPTION 'parent % has no path', NEW.parent_id;
        END IF;
        IF ppath LIKE '%/' || NEW.id || '/%' THEN
            RAISE EXCEPTION 'cycle: unit % cannot be a descendant of itself', NEW.id;
        END IF;
        NEW.path  := ppath || NEW.id || '/';
        NEW.depth := pdepth + 1;
    END IF;
    NEW.updated_at := NOW();
    RETURN NEW;
END $$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;


--
-- Name: academy_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_attempts (
    id integer NOT NULL,
    enrollment_id integer NOT NULL,
    question_ids jsonb NOT NULL,
    answers jsonb,
    score integer,
    passed boolean,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    submitted_at timestamp with time zone,
    request_ip text
);


--
-- Name: academy_attempts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.academy_attempts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: academy_attempts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.academy_attempts_id_seq OWNED BY public.academy_attempts.id;


--
-- Name: academy_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_audit (
    id integer NOT NULL,
    learner_id integer,
    actor_user_id integer,
    action text NOT NULL,
    detail text,
    ip text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: academy_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.academy_audit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: academy_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.academy_audit_id_seq OWNED BY public.academy_audit.id;


--
-- Name: academy_certificates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_certificates (
    id integer NOT NULL,
    cert_number text NOT NULL,
    learner_id integer,
    course_id integer NOT NULL,
    enrollment_id integer,
    attempt_id integer,
    holder_name text,
    course_title text NOT NULL,
    score integer NOT NULL,
    issued_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone,
    sha256 text NOT NULL,
    status text DEFAULT 'valid'::text NOT NULL,
    status_reason text,
    status_changed_by integer,
    status_changed_at timestamp with time zone,
    provider text DEFAULT 'integrys'::text NOT NULL
);


--
-- Name: academy_certificates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.academy_certificates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: academy_certificates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.academy_certificates_id_seq OWNED BY public.academy_certificates.id;


--
-- Name: academy_courses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_courses (
    id integer NOT NULL,
    slug text NOT NULL,
    title_en text NOT NULL,
    title_ar text,
    summary_en text,
    summary_ar text,
    level text DEFAULT 'Foundation'::text,
    duration_minutes integer DEFAULT 45,
    pass_mark integer DEFAULT 70 NOT NULL,
    questions_per_attempt integer DEFAULT 10 NOT NULL,
    retry_cooldown_minutes integer DEFAULT 30 NOT NULL,
    validity_months integer DEFAULT 24 NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    approved_by integer,
    approved_at timestamp with time zone,
    approval_note text,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    provider text DEFAULT 'integrys'::text NOT NULL
);


--
-- Name: academy_courses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.academy_courses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: academy_courses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.academy_courses_id_seq OWNED BY public.academy_courses.id;


--
-- Name: academy_enrollments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_enrollments (
    id integer NOT NULL,
    learner_id integer NOT NULL,
    course_id integer NOT NULL,
    status text DEFAULT 'in_progress'::text NOT NULL,
    lessons_done jsonb DEFAULT '[]'::jsonb NOT NULL,
    best_score integer,
    attempts_count integer DEFAULT 0 NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone
);


--
-- Name: academy_enrollments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.academy_enrollments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: academy_enrollments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.academy_enrollments_id_seq OWNED BY public.academy_enrollments.id;


--
-- Name: academy_learners; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_learners (
    id integer NOT NULL,
    full_name text NOT NULL,
    certificate_name text,
    email text NOT NULL,
    email_domain text NOT NULL,
    company text,
    job_title text,
    country text,
    source text,
    utm_source text,
    utm_medium text,
    utm_campaign text,
    free_provider boolean DEFAULT false,
    consent_training_at timestamp with time zone NOT NULL,
    consent_marketing boolean DEFAULT false NOT NULL,
    consent_marketing_at timestamp with time zone,
    privacy_version text,
    email_verified_at timestamp with time zone,
    status text DEFAULT 'pending'::text NOT NULL,
    registered_ip text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_login_at timestamp with time zone,
    last_activity_at timestamp with time zone,
    erased_at timestamp with time zone,
    erased_by integer
);


--
-- Name: academy_learners_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.academy_learners_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: academy_learners_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.academy_learners_id_seq OWNED BY public.academy_learners.id;


--
-- Name: academy_lessons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_lessons (
    id integer NOT NULL,
    course_id integer NOT NULL,
    "position" integer NOT NULL,
    title_en text NOT NULL,
    title_ar text,
    body_en text,
    body_ar text,
    video_url text,
    video_file text,
    presentation_file text,
    presentation_name text,
    material_file text,
    material_name text,
    video_name text,
    video_seconds integer,
    intro_en text,
    intro_ar text
);


--
-- Name: academy_lessons_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.academy_lessons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: academy_lessons_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.academy_lessons_id_seq OWNED BY public.academy_lessons.id;


--
-- Name: academy_otp; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_otp (
    id integer NOT NULL,
    learner_id integer NOT NULL,
    purpose text NOT NULL,
    code_hash text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    consumed_at timestamp with time zone,
    request_ip text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: academy_otp_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.academy_otp_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: academy_otp_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.academy_otp_id_seq OWNED BY public.academy_otp.id;


--
-- Name: academy_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_questions (
    id integer NOT NULL,
    course_id integer NOT NULL,
    text_en text NOT NULL,
    text_ar text,
    options_en jsonb NOT NULL,
    options_ar jsonb,
    correct_index integer NOT NULL,
    explanation_en text,
    explanation_ar text,
    is_active boolean DEFAULT true NOT NULL
);


--
-- Name: academy_questions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.academy_questions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: academy_questions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.academy_questions_id_seq OWNED BY public.academy_questions.id;


--
-- Name: academy_rejected_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_rejected_domains (
    domain text NOT NULL,
    reason text NOT NULL,
    hits integer DEFAULT 1 NOT NULL,
    first_seen timestamp with time zone DEFAULT now() NOT NULL,
    last_seen timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: academy_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_settings (
    key text NOT NULL,
    value text,
    updated_by integer,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: academy_video_progress; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.academy_video_progress (
    enrollment_id integer NOT NULL,
    lesson_id integer NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    last_update_at timestamp with time zone DEFAULT now() NOT NULL,
    max_position real DEFAULT 0 NOT NULL,
    completed_at timestamp with time zone
);


--
-- Name: adverse_media_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.adverse_media_results (
    id integer NOT NULL,
    screening_result_id integer,
    person_name text,
    risk_level text,
    risk_score numeric,
    total_hits integer,
    high_risk_hits integer,
    medium_risk_hits integer,
    low_risk_hits integer,
    sources_checked text,
    top_hits text,
    all_hits text,
    recommendation text,
    screened_at text,
    screened_by integer
);


--
-- Name: adverse_media_results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.adverse_media_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: adverse_media_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.adverse_media_results_id_seq OWNED BY public.adverse_media_results.id;


--
-- Name: ai_intake_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_intake_items (
    id integer NOT NULL,
    channel character varying(20) DEFAULT 'text'::character varying NOT NULL,
    subject character varying(300),
    body text,
    status character varying(12) DEFAULT 'new'::character varying NOT NULL,
    proposal jsonb,
    final jsonb,
    created_refs jsonb DEFAULT '[]'::jsonb NOT NULL,
    suggestion_id integer,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    decided_by integer,
    decided_at timestamp without time zone,
    CONSTRAINT ai_intake_items_channel_check CHECK (((channel)::text = ANY ((ARRAY['text'::character varying, 'document'::character varying, 'email'::character varying, 'alert'::character varying, 'circular'::character varying])::text[]))),
    CONSTRAINT ai_intake_items_status_check CHECK (((status)::text = ANY ((ARRAY['new'::character varying, 'proposed'::character varying, 'confirmed'::character varying, 'rejected'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: ai_intake_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_intake_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_intake_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_intake_items_id_seq OWNED BY public.ai_intake_items.id;


--
-- Name: ai_intents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_intents (
    code character varying(60) NOT NULL,
    name_en character varying(200) NOT NULL,
    name_ar character varying(200),
    description text,
    keywords text[] DEFAULT '{}'::text[] NOT NULL,
    examples text[] DEFAULT '{}'::text[] NOT NULL,
    fields jsonb DEFAULT '[]'::jsonb NOT NULL,
    handler character varying(60) DEFAULT 'manual'::character varying NOT NULL,
    handler_params jsonb DEFAULT '{}'::jsonb NOT NULL,
    control_codes text[] DEFAULT '{}'::text[] NOT NULL,
    owner_role character varying(40),
    priority character varying(10) DEFAULT 'medium'::character varying NOT NULL,
    deadline_hours integer,
    is_active boolean DEFAULT true NOT NULL,
    pack_code character varying(40),
    updated_by integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ai_intents_priority_check CHECK (((priority)::text = ANY ((ARRAY['critical'::character varying, 'high'::character varying, 'medium'::character varying, 'low'::character varying])::text[])))
);


--
-- Name: ai_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_jobs (
    id character varying(36) NOT NULL,
    feature character varying(30) NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(10) DEFAULT 'queued'::character varying NOT NULL,
    result jsonb,
    error text,
    suggestion_id integer,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    finished_at timestamp without time zone,
    CONSTRAINT ai_jobs_status_check CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'done'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: ai_playbook_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_playbook_runs (
    id integer NOT NULL,
    playbook_code character varying(60) NOT NULL,
    title character varying(300) NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    start_date date DEFAULT CURRENT_DATE NOT NULL,
    finding_id integer,
    suggestion_id integer,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: ai_playbook_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_playbook_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_playbook_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_playbook_runs_id_seq OWNED BY public.ai_playbook_runs.id;


--
-- Name: ai_playbook_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_playbook_steps (
    id integer NOT NULL,
    playbook_code character varying(60) NOT NULL,
    step_key character varying(60) NOT NULL,
    seq integer DEFAULT 100 NOT NULL,
    step_type character varying(12) DEFAULT 'task'::character varying NOT NULL,
    title_en character varying(300) NOT NULL,
    title_ar character varying(300),
    control_code character varying(30),
    owner_role character varying(40),
    due_days integer DEFAULT 14 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    pack_code character varying(40),
    CONSTRAINT ai_playbook_steps_step_type_check CHECK (((step_type)::text = ANY ((ARRAY['task'::character varying, 'evidence'::character varying, 'approval'::character varying, 'control'::character varying])::text[])))
);


--
-- Name: ai_playbook_steps_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_playbook_steps_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_playbook_steps_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_playbook_steps_id_seq OWNED BY public.ai_playbook_steps.id;


--
-- Name: ai_playbooks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_playbooks (
    code character varying(60) NOT NULL,
    name_en character varying(200) NOT NULL,
    name_ar character varying(200),
    description text,
    keywords text[] DEFAULT '{}'::text[] NOT NULL,
    examples text[] DEFAULT '{}'::text[] NOT NULL,
    parameters jsonb DEFAULT '[]'::jsonb NOT NULL,
    severity character varying(10) DEFAULT 'medium'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    pack_code character varying(40),
    updated_by integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: ai_suggestions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_suggestions (
    id integer NOT NULL,
    feature character varying(30) NOT NULL,
    object_type character varying(40),
    object_id integer,
    input_hash character(64) NOT NULL,
    provider character varying(30) NOT NULL,
    model character varying(120),
    prompt_version character varying(30) NOT NULL,
    prompt_text text,
    output jsonb,
    status character varying(12) DEFAULT 'ok'::character varying NOT NULL,
    error text,
    latency_ms integer,
    decision character varying(10),
    decided_by integer,
    decided_at timestamp without time zone,
    user_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    purged_at timestamp without time zone,
    CONSTRAINT ai_suggestions_decision_check CHECK (((decision)::text = ANY ((ARRAY['accept'::character varying, 'edit'::character varying, 'reject'::character varying])::text[]))),
    CONSTRAINT ai_suggestions_status_check CHECK (((status)::text = ANY ((ARRAY['ok'::character varying, 'repaired'::character varying, 'fallback'::character varying, 'error'::character varying])::text[])))
);


--
-- Name: ai_suggestions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ai_suggestions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ai_suggestions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ai_suggestions_id_seq OWNED BY public.ai_suggestions.id;


--
-- Name: aml_alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aml_alerts (
    id integer NOT NULL,
    alert_type text,
    alert_status text DEFAULT 'OPEN'::text,
    customer_id integer,
    screening_result_id integer,
    matched_name text,
    match_score double precision,
    source_list text,
    alert_details text,
    risk_level text DEFAULT 'MEDIUM'::text,
    assigned_to integer,
    notes text,
    false_positive integer DEFAULT 0,
    resolved_by integer,
    resolved_at text,
    resolution_notes text,
    created_by integer,
    created_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text),
    updated_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text)
);


--
-- Name: aml_alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.aml_alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: aml_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.aml_alerts_id_seq OWNED BY public.aml_alerts.id;


--
-- Name: aml_annual_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aml_annual_reports (
    id integer NOT NULL,
    report_year integer NOT NULL,
    role_code character varying(40) DEFAULT 'mlro'::character varying NOT NULL,
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    data jsonb DEFAULT '{}'::jsonb NOT NULL,
    narrative text,
    generated_at timestamp without time zone,
    generated_by integer,
    submitted_at timestamp without time zone,
    board_meeting_ref character varying(200),
    board_approved_on date,
    approval_recorded_by integer,
    CONSTRAINT aml_annual_reports_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying, 'approved'::character varying])::text[])))
);


--
-- Name: aml_annual_reports_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.aml_annual_reports_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: aml_annual_reports_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.aml_annual_reports_id_seq OWNED BY public.aml_annual_reports.id;


--
-- Name: aml_key_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aml_key_roles (
    id integer NOT NULL,
    role_code character varying(40) NOT NULL,
    title character varying(200),
    holder_user_id integer,
    holder_name character varying(200),
    reports_to_title character varying(200),
    reports_to_user_id integer,
    reports_to_board boolean DEFAULT false NOT NULL,
    other_positions text,
    combined_role_approval_ref character varying(120),
    combined_role_approved_on date,
    appointed_on date,
    regulator_notified_on date,
    regulator_ref character varying(120),
    org_unit_id integer,
    is_active boolean DEFAULT true NOT NULL,
    notes text,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: aml_key_roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.aml_key_roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: aml_key_roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.aml_key_roles_id_seq OWNED BY public.aml_key_roles.id;


--
-- Name: aml_monitoring_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aml_monitoring_plans (
    id integer NOT NULL,
    plan_year integer NOT NULL,
    title character varying(300),
    approved_on date,
    notes text,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: aml_monitoring_plans_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.aml_monitoring_plans_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: aml_monitoring_plans_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.aml_monitoring_plans_id_seq OWNED BY public.aml_monitoring_plans.id;


--
-- Name: aml_monitoring_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aml_monitoring_reviews (
    id integer NOT NULL,
    plan_id integer NOT NULL,
    unit_label character varying(200) NOT NULL,
    org_unit_id integer,
    review_type character varying(10) DEFAULT 'offsite'::character varying NOT NULL,
    planned_date date NOT NULL,
    performed_date date,
    reviewer_id integer,
    checklist jsonb DEFAULT '[]'::jsonb NOT NULL,
    conclusion text,
    status character varying(12) DEFAULT 'planned'::character varying NOT NULL,
    finding_id integer,
    CONSTRAINT aml_monitoring_reviews_review_type_check CHECK (((review_type)::text = ANY ((ARRAY['offsite'::character varying, 'onsite'::character varying])::text[]))),
    CONSTRAINT aml_monitoring_reviews_status_check CHECK (((status)::text = ANY ((ARRAY['planned'::character varying, 'done'::character varying, 'cancelled'::character varying])::text[])))
);


--
-- Name: aml_monitoring_reviews_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.aml_monitoring_reviews_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: aml_monitoring_reviews_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.aml_monitoring_reviews_id_seq OWNED BY public.aml_monitoring_reviews.id;


--
-- Name: aml_role_conflict_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aml_role_conflict_rules (
    id integer NOT NULL,
    role_code character varying(40) NOT NULL,
    rule_type character varying(20) NOT NULL,
    keyword character varying(120) NOT NULL,
    reason_en text,
    reason_ar text,
    is_active boolean DEFAULT true NOT NULL,
    CONSTRAINT aml_role_conflict_rules_rule_type_check CHECK (((rule_type)::text = ANY ((ARRAY['holds'::character varying, 'reports_to'::character varying])::text[])))
);


--
-- Name: aml_role_conflict_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.aml_role_conflict_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: aml_role_conflict_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.aml_role_conflict_rules_id_seq OWNED BY public.aml_role_conflict_rules.id;


--
-- Name: aml_unusual_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aml_unusual_transactions (
    id integer NOT NULL,
    reference character varying(30),
    source_module character varying(40) NOT NULL,
    source_table character varying(60),
    source_record_id integer,
    detection_rule character varying(60) NOT NULL,
    party_id integer,
    subject_name character varying(255),
    subject_ref character varying(80),
    amount numeric(18,2),
    description text,
    detected_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    status character varying(20) DEFAULT 'candidate'::character varying NOT NULL,
    study_due_date date,
    analysis text,
    decision character varying(10),
    decision_by integer,
    decision_at timestamp without time zone,
    str_reference character varying(80),
    org_unit_id integer,
    created_by integer,
    CONSTRAINT aml_unusual_transactions_decision_check CHECK (((decision)::text = ANY ((ARRAY['str'::character varying, 'no_str'::character varying])::text[]))),
    CONSTRAINT aml_unusual_transactions_status_check CHECK (((status)::text = ANY ((ARRAY['candidate'::character varying, 'under_study'::character varying, 'str_filed'::character varying, 'no_str'::character varying, 'dismissed'::character varying])::text[])))
);


--
-- Name: aml_unusual_transactions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.aml_unusual_transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: aml_unusual_transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.aml_unusual_transactions_id_seq OWNED BY public.aml_unusual_transactions.id;


--
-- Name: annual_audit_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.annual_audit_plans (
    id integer NOT NULL,
    plan_year integer NOT NULL,
    plan_name character varying(255),
    status character varying(20) DEFAULT 'DRAFT'::character varying NOT NULL,
    approved_date date,
    approved_by integer,
    approved_by_meeting_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT annual_audit_plans_status_check CHECK (((status)::text = ANY (ARRAY[('DRAFT'::character varying)::text, ('APPROVED'::character varying)::text, ('IN_PROGRESS'::character varying)::text, ('CLOSED'::character varying)::text])))
);


--
-- Name: annual_audit_plans_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.annual_audit_plans_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: annual_audit_plans_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.annual_audit_plans_id_seq OWNED BY public.annual_audit_plans.id;


--
-- Name: api_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_audit_log (
    id bigint NOT NULL,
    key_id integer,
    key_prefix character varying(8),
    endpoint character varying(200) NOT NULL,
    method character varying(10) NOT NULL,
    status_code integer,
    request_ip character varying(45),
    request_body text,
    response_ms integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: api_audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.api_audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: api_audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.api_audit_log_id_seq OWNED BY public.api_audit_log.id;


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    id integer NOT NULL,
    name character varying(120) NOT NULL,
    key_hash character varying(64) NOT NULL,
    key_prefix character varying(8) NOT NULL,
    owner_id integer,
    scopes text DEFAULT 'screening:read,aml:read,kyc:read'::text NOT NULL,
    rate_limit integer DEFAULT 100 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    last_used_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    expires_at timestamp without time zone,
    created_by integer
);


--
-- Name: api_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: api_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.api_keys_id_seq OWNED BY public.api_keys.id;


--
-- Name: approval_workflow_stages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_workflow_stages (
    id integer NOT NULL,
    workflow_id integer NOT NULL,
    stage_order integer NOT NULL,
    stage_name text NOT NULL,
    approver_mode text DEFAULT 'role'::text NOT NULL,
    approver_user_id integer,
    approver_role text,
    approver_org_unit_id integer,
    is_mandatory boolean DEFAULT true NOT NULL,
    is_enabled boolean DEFAULT true NOT NULL,
    sla_days integer DEFAULT 7,
    CONSTRAINT aws_mode_ck CHECK ((approver_mode = ANY (ARRAY['user'::text, 'role'::text, 'org_unit_head'::text, 'parent_unit_head'::text])))
);


--
-- Name: approval_workflow_stages_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.approval_workflow_stages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_workflow_stages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.approval_workflow_stages_id_seq OWNED BY public.approval_workflow_stages.id;


--
-- Name: approval_workflows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_workflows (
    id integer NOT NULL,
    document_type_id integer,
    name text NOT NULL,
    description text,
    org_unit_id integer,
    is_default boolean DEFAULT true NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: approval_workflows_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.approval_workflows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_workflows_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.approval_workflows_id_seq OWNED BY public.approval_workflows.id;


--
-- Name: audit_findings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_findings (
    id integer NOT NULL,
    project_id integer NOT NULL,
    finding_number character varying(50) NOT NULL,
    finding_title character varying(255) NOT NULL,
    finding_description text,
    severity character varying(20) NOT NULL,
    root_cause text,
    recommendation text,
    management_response text,
    agreed_action text,
    responsible_person_id integer,
    target_date date,
    status character varying(40) DEFAULT 'OPEN'::character varying NOT NULL,
    verified_by integer,
    verified_at timestamp without time zone,
    verification_notes text,
    linked_risk_id integer,
    linked_control_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    aml_red_flag boolean DEFAULT false NOT NULL,
    CONSTRAINT audit_findings_severity_check CHECK (((severity)::text = ANY (ARRAY[('CRITICAL'::character varying)::text, ('HIGH'::character varying)::text, ('MEDIUM'::character varying)::text, ('LOW'::character varying)::text]))),
    CONSTRAINT audit_findings_status_check CHECK (((status)::text = ANY (ARRAY[('OPEN'::character varying)::text, ('MANAGEMENT_RESPONSE_RECEIVED'::character varying)::text, ('REMEDIATION_IN_PROGRESS'::character varying)::text, ('REMEDIATED_PENDING_VERIFICATION'::character varying)::text, ('VERIFIED_CLOSED'::character varying)::text])))
);


--
-- Name: audit_findings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_findings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_findings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_findings_id_seq OWNED BY public.audit_findings.id;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: audit_programs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_programs (
    id integer NOT NULL,
    project_id integer NOT NULL,
    step_number integer NOT NULL,
    procedure_description text NOT NULL,
    control_id integer,
    test_result character varying(20),
    workpaper_reference character varying(100),
    performed_by integer,
    performed_at timestamp without time zone,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    CONSTRAINT audit_programs_test_result_check CHECK (((test_result)::text = ANY (ARRAY[('EFFECTIVE'::character varying)::text, ('PARTIALLY_EFFECTIVE'::character varying)::text, ('INEFFECTIVE'::character varying)::text, ('N/A'::character varying)::text, ('NOT_TESTED'::character varying)::text])))
);


--
-- Name: audit_programs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_programs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_programs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_programs_id_seq OWNED BY public.audit_programs.id;


--
-- Name: audit_projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_projects (
    id integer NOT NULL,
    plan_id integer,
    audit_number character varying(50) NOT NULL,
    audit_name character varying(255) NOT NULL,
    auditable_area_id integer,
    audit_type character varying(50) DEFAULT 'INTERNAL'::character varying NOT NULL,
    audit_scope text,
    planned_start_date date,
    planned_end_date date,
    actual_start_date date,
    actual_end_date date,
    lead_auditor_id integer,
    status character varying(20) DEFAULT 'PLANNED'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT audit_projects_audit_type_check CHECK (((audit_type)::text = ANY (ARRAY[('INTERNAL'::character varying)::text, ('EXTERNAL'::character varying)::text, ('REGULATORY'::character varying)::text, ('SPECIAL'::character varying)::text]))),
    CONSTRAINT audit_projects_status_check CHECK (((status)::text = ANY (ARRAY[('PLANNED'::character varying)::text, ('FIELDWORK'::character varying)::text, ('REPORTING'::character varying)::text, ('MANAGEMENT_RESPONSE'::character varying)::text, ('FOLLOW_UP'::character varying)::text, ('CLOSED'::character varying)::text])))
);


--
-- Name: audit_projects_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_projects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_projects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_projects_id_seq OWNED BY public.audit_projects.id;


--
-- Name: audit_team_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_team_members (
    id integer NOT NULL,
    project_id integer NOT NULL,
    user_id integer NOT NULL,
    role_on_engagement character varying(30) DEFAULT 'AUDITOR'::character varying NOT NULL,
    allocated_hours numeric(6,1),
    CONSTRAINT audit_team_members_role_on_engagement_check CHECK (((role_on_engagement)::text = ANY (ARRAY[('LEAD'::character varying)::text, ('AUDITOR'::character varying)::text, ('REVIEWER'::character varying)::text, ('OBSERVER'::character varying)::text])))
);


--
-- Name: audit_team_members_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_team_members_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_team_members_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_team_members_id_seq OWNED BY public.audit_team_members.id;


--
-- Name: audit_universe; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_universe (
    id integer NOT NULL,
    auditable_area character varying(255) NOT NULL,
    area_description text,
    risk_level character varying(20) DEFAULT 'MEDIUM'::character varying NOT NULL,
    department_id integer,
    last_audit_date date,
    audit_frequency character varying(20) DEFAULT 'ANNUAL'::character varying NOT NULL,
    next_audit_due date,
    responsible_department character varying(100),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT audit_universe_audit_frequency_check CHECK (((audit_frequency)::text = ANY (ARRAY[('QUARTERLY'::character varying)::text, ('SEMI_ANNUAL'::character varying)::text, ('ANNUAL'::character varying)::text, ('BIENNIAL'::character varying)::text]))),
    CONSTRAINT audit_universe_risk_level_check CHECK (((risk_level)::text = ANY (ARRAY[('LOW'::character varying)::text, ('MEDIUM'::character varying)::text, ('HIGH'::character varying)::text, ('CRITICAL'::character varying)::text])))
);


--
-- Name: audit_universe_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_universe_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_universe_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_universe_id_seq OWNED BY public.audit_universe.id;


--
-- Name: audit_universe_risks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_universe_risks (
    id integer NOT NULL,
    universe_id integer NOT NULL,
    risk_id integer NOT NULL
);


--
-- Name: audit_universe_risks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_universe_risks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_universe_risks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_universe_risks_id_seq OWNED BY public.audit_universe_risks.id;


--
-- Name: audit_working_papers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_working_papers (
    id integer NOT NULL,
    project_id integer NOT NULL,
    program_step_id integer,
    finding_id integer,
    file_path character varying(500) NOT NULL,
    description character varying(255),
    uploaded_by integer,
    uploaded_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: audit_working_papers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_working_papers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_working_papers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_working_papers_id_seq OWNED BY public.audit_working_papers.id;


--
-- Name: beneficial_owners; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.beneficial_owners (
    id integer NOT NULL,
    customer_id integer,
    owner_type text,
    full_name text,
    date_of_birth text,
    nationality text,
    id_type text,
    id_number text,
    address text,
    ownership_percentage numeric,
    ownership_type text,
    ownership_description text,
    is_pep integer,
    pep_category text,
    pep_position text,
    pep_notes text,
    id_document_path text,
    verified integer,
    verified_by integer,
    verification_date text,
    verification_notes text,
    created_at text,
    created_by integer
);


--
-- Name: beneficial_owners_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.beneficial_owners_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: beneficial_owners_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.beneficial_owners_id_seq OWNED BY public.beneficial_owners.id;


--
-- Name: blacklist_bulk_imports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.blacklist_bulk_imports (
    id integer NOT NULL,
    filename text,
    total_records integer,
    successful_imports integer,
    failed_imports integer,
    imported_by integer,
    import_date text,
    error_log text
);


--
-- Name: blacklist_bulk_imports_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.blacklist_bulk_imports_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: blacklist_bulk_imports_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.blacklist_bulk_imports_id_seq OWNED BY public.blacklist_bulk_imports.id;


--
-- Name: board_committees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_committees (
    id integer NOT NULL,
    committee_name text,
    committee_name_arabic text,
    committee_type text,
    is_mandatory integer,
    regulatory_requirement text,
    chairman_id integer,
    secretary_id integer,
    min_members integer,
    max_members integer,
    independence_requirement text,
    min_independent_members integer,
    requires_financial_expert integer,
    charter_file text,
    charter_version text,
    charter_last_review text,
    charter_next_review text,
    terms_of_reference text,
    meeting_frequency text,
    min_meetings_per_year integer,
    quorum_requirement text,
    quorum_number integer,
    last_evaluation_date text,
    evaluation_score double precision,
    effectiveness_rating text,
    reports_to text,
    reporting_frequency text,
    last_report_date text,
    next_report_due text,
    is_active integer,
    activation_date text,
    deactivation_date text,
    deactivation_reason text,
    created_at text,
    created_by integer,
    updated_at text
);


--
-- Name: board_committees_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.board_committees_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: board_committees_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.board_committees_id_seq OWNED BY public.board_committees.id;


--
-- Name: board_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_decisions (
    id integer NOT NULL,
    meeting_id integer,
    decision_reference text,
    decision_date text,
    decision_title text,
    decision_description text,
    vote_type text,
    votes_for integer,
    votes_against integer,
    votes_abstain integer,
    dissenting_members text,
    dissenting_reasons text,
    action_required text,
    responsible_person text,
    implementation_deadline text,
    implemented integer,
    implementation_date text,
    created_at text,
    decision_number text,
    decision_text text,
    deadline text,
    status text,
    completion_date text
);


--
-- Name: board_decisions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.board_decisions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: board_decisions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.board_decisions_id_seq OWNED BY public.board_decisions.id;


--
-- Name: board_evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_evaluations (
    id integer NOT NULL,
    evaluation_period text,
    evaluation_type text,
    board_committee_id integer,
    member_id integer,
    methodology text,
    evaluator text,
    is_external integer,
    strategy_effectiveness_score integer,
    risk_oversight_score integer,
    financial_oversight_score integer,
    compliance_oversight_score integer,
    stakeholder_engagement_score integer,
    decision_quality_score integer,
    meeting_effectiveness_score integer,
    board_dynamics_score integer,
    independence_score integer,
    diversity_score integer,
    individual_contribution_score integer,
    individual_expertise_score integer,
    individual_commitment_score integer,
    individual_integrity_score integer,
    total_score integer,
    overall_rating text,
    strengths text,
    areas_for_improvement text,
    recommendations text,
    action_plan text,
    action_items_created integer,
    improvement_deadline text,
    progress_review_date text,
    improvements_implemented integer,
    evaluation_report_path text,
    evaluation_completed integer,
    completion_date text,
    presented_to_board integer,
    presentation_date text,
    created_at text,
    conducted_by integer
);


--
-- Name: board_evaluations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.board_evaluations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: board_evaluations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.board_evaluations_id_seq OWNED BY public.board_evaluations.id;


--
-- Name: board_meeting_attendance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_meeting_attendance (
    id integer NOT NULL,
    meeting_id integer,
    member_id integer,
    attended integer,
    attendance_mode text,
    apology_sent integer,
    apology_reason text,
    created_at text
);


--
-- Name: board_meeting_attendance_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.board_meeting_attendance_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: board_meeting_attendance_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.board_meeting_attendance_id_seq OWNED BY public.board_meeting_attendance.id;


--
-- Name: board_meetings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_meetings (
    id integer NOT NULL,
    meeting_type text,
    committee_id integer,
    meeting_date text,
    meeting_time text,
    location text,
    agenda text,
    minutes_file text,
    quorum_met integer,
    status text,
    meeting_reference text
);


--
-- Name: board_meetings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.board_meetings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: board_meetings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.board_meetings_id_seq OWNED BY public.board_meetings.id;


--
-- Name: board_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_members (
    id integer NOT NULL,
    member_name text,
    member_name_arabic text,
    national_id text,
    passport_number text,
    date_of_birth text,
    nationality text,
    "position" text,
    role text,
    member_type text,
    is_independent integer,
    is_executive integer,
    independence_criteria_met text,
    independence_declaration_date text,
    independence_confirmed_by text,
    fit_proper_assessment_date text,
    fit_proper_status text,
    fit_proper_score double precision,
    fit_proper_approved_by text,
    fit_proper_approval_date text,
    fit_proper_next_review text,
    cbe_approval_reference text,
    cbe_approval_date text,
    highest_qualification text,
    professional_certifications text,
    years_of_experience integer,
    expertise_areas text,
    industry_experience text,
    board_experience text,
    skills_financial integer,
    skills_risk_management integer,
    skills_compliance integer,
    skills_technology integer,
    skills_strategy integer,
    skills_hr integer,
    skills_legal integer,
    skills_audit integer,
    skills_marketing integer,
    skills_operations integer,
    appointment_date text,
    appointment_type text,
    term_start_date text,
    term_end_date text,
    term_duration_months integer,
    term_number integer,
    max_consecutive_terms integer,
    email text,
    phone text,
    alternative_phone text,
    address text,
    emergency_contact text,
    cv_document_path text,
    id_document_path text,
    fit_proper_document_path text,
    declaration_document_path text,
    photo_path text,
    has_conflicts integer,
    conflict_details text,
    last_coi_declaration_date text,
    onboarding_completed integer,
    onboarding_date text,
    training_hours_ytd double precision,
    last_training_date text,
    last_evaluation_date text,
    last_evaluation_score double precision,
    evaluation_status text,
    meetings_attended_ytd integer,
    meetings_scheduled_ytd integer,
    attendance_rate double precision,
    annual_fee double precision,
    meeting_fee double precision,
    committee_fee double precision,
    stock_options integer,
    other_benefits text,
    last_remuneration_review text,
    status text,
    resignation_date text,
    resignation_reason text,
    replacement_required integer,
    bio text,
    linkedin_profile text,
    created_at text,
    created_by integer,
    updated_at text,
    updated_by integer,
    is_deleted integer,
    deleted_at text,
    deleted_by integer,
    document_path text
);


--
-- Name: board_members_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.board_members_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: board_members_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.board_members_id_seq OWNED BY public.board_members.id;


--
-- Name: board_members_v1; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_members_v1 (
    id integer NOT NULL,
    member_name text,
    member_type text,
    "position" text,
    qualifications text,
    professional_experience text,
    other_board_positions text,
    appointment_date text,
    appointed_by text,
    term_start_date text,
    term_end_date text,
    term_number integer,
    independence_criteria_met integer,
    independence_assessment_date text,
    independence_notes text,
    fit_and_proper_approved integer,
    cbe_approval_reference text,
    cbe_approval_date text,
    cbe_approval_file_path text,
    background_check_completed integer,
    background_check_date text,
    background_check_clear integer,
    coi_declared integer,
    coi_description text,
    coi_mitigation text,
    is_active integer,
    resignation_date text,
    resignation_reason text,
    email text,
    phone text,
    address text,
    created_at text,
    updated_at text,
    member_name_arabic text,
    role text,
    is_independent integer,
    is_executive integer,
    expertise_areas text,
    bio text,
    status text,
    document_path text
);


--
-- Name: board_members_v1_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.board_members_v1_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: board_members_v1_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.board_members_v1_id_seq OWNED BY public.board_members_v1.id;


--
-- Name: board_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_roles (
    id integer NOT NULL,
    role_name text,
    description text,
    created_at text
);


--
-- Name: board_roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.board_roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: board_roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.board_roles_id_seq OWNED BY public.board_roles.id;


--
-- Name: board_skills_matrix; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_skills_matrix (
    id integer NOT NULL,
    member_id integer,
    assessment_date text,
    assessment_period text,
    financial_expertise integer,
    risk_management integer,
    compliance_regulatory integer,
    technology_digital integer,
    strategy_business integer,
    human_resources integer,
    legal integer,
    audit integer,
    marketing_sales integer,
    operations integer,
    banking_finance integer,
    payments_fintech integer,
    technology integer,
    retail integer,
    board_experience integer,
    committee_chair_experience integer,
    crisis_management integer,
    stakeholder_management integer,
    arabic_proficiency integer,
    english_proficiency integer,
    other_languages text,
    has_professional_certifications integer,
    certifications_list text,
    total_skill_score integer,
    skill_level text,
    skill_gaps text,
    development_plan text,
    assessed_by integer
);


--
-- Name: board_skills_matrix_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.board_skills_matrix_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: board_skills_matrix_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.board_skills_matrix_id_seq OWNED BY public.board_skills_matrix.id;


--
-- Name: board_training; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_training (
    id integer NOT NULL,
    training_title text,
    training_type text,
    training_category text,
    training_date text,
    training_time text,
    duration_hours double precision,
    location text,
    delivery_method text,
    provider_name text,
    provider_type text,
    provider_contact text,
    trainer_name text,
    mandatory integer,
    target_audience text,
    target_members text,
    assessment_required integer,
    min_pass_score integer,
    certificate_provided integer,
    training_objectives text,
    training_materials_path text,
    status text,
    completion_date text,
    created_at text,
    created_by integer,
    updated_at text
);


--
-- Name: board_training_attendance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_training_attendance (
    id integer NOT NULL,
    training_id integer,
    member_id integer,
    attended integer,
    attendance_duration integer,
    completion_status text,
    completion_date text,
    assessment_score integer,
    passed integer,
    certificate_issued integer,
    certificate_path text,
    feedback_rating integer,
    feedback_comments text,
    updated_at text
);


--
-- Name: board_training_attendance_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.board_training_attendance_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: board_training_attendance_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.board_training_attendance_id_seq OWNED BY public.board_training_attendance.id;


--
-- Name: board_training_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.board_training_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: board_training_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.board_training_id_seq OWNED BY public.board_training.id;


--
-- Name: breach_remediation_actions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.breach_remediation_actions (
    id integer NOT NULL,
    breach_id integer,
    action_description text,
    action_owner integer,
    target_date text,
    completion_date text,
    status text,
    evidence_file text,
    notes text
);


--
-- Name: breach_remediation_actions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.breach_remediation_actions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: breach_remediation_actions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.breach_remediation_actions_id_seq OWNED BY public.breach_remediation_actions.id;


--
-- Name: carbon_activity_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_activity_entries (
    id integer NOT NULL,
    reporting_period_id integer NOT NULL,
    site_id integer,
    scope character varying(10) NOT NULL,
    category character varying(80) NOT NULL,
    ghg_category_no integer,
    activity character varying(150) NOT NULL,
    calc_method character varying(20) DEFAULT 'activity_based'::character varying NOT NULL,
    quantity double precision DEFAULT 0 NOT NULL,
    unit character varying(30) NOT NULL,
    factor_id integer,
    tco2e double precision,
    basis character varying(20) DEFAULT 'location'::character varying,
    notes text,
    evidence_path text,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    entity_id integer,
    activity_month date,
    factor_code character varying(60),
    factor_kgco2e_used numeric(18,6),
    factor_source_used character varying(255),
    factor_vintage_used integer,
    gross_tco2e numeric(18,6),
    boundary_share numeric(6,4),
    instrument_type character varying(30),
    instrument_ref character varying(200),
    helper_inputs jsonb
);


--
-- Name: carbon_activity_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_activity_entries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_activity_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_activity_entries_id_seq OWNED BY public.carbon_activity_entries.id;


--
-- Name: carbon_emission_factors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_emission_factors (
    id integer NOT NULL,
    scope character varying(10) NOT NULL,
    category character varying(80) NOT NULL,
    ghg_category_no integer,
    activity character varying(150) NOT NULL,
    unit character varying(30) NOT NULL,
    factor_kgco2e double precision NOT NULL,
    ghg_gas character varying(20) DEFAULT 'CO2'::character varying,
    source character varying(60) NOT NULL,
    vintage_year integer NOT NULL,
    effective_from date NOT NULL,
    effective_to date,
    is_client_override boolean DEFAULT false NOT NULL,
    notes text,
    citation text,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    factor_code character varying(60),
    version_label character varying(40),
    region character varying(10) DEFAULT 'EG'::character varying,
    source_url character varying(500),
    activity_ar character varying(300)
);


--
-- Name: carbon_emission_factors_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_emission_factors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_emission_factors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_emission_factors_id_seq OWNED BY public.carbon_emission_factors.id;


--
-- Name: carbon_entities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_entities (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    name_ar character varying(255),
    ownership_pct numeric(6,2) DEFAULT 100,
    operational_control boolean DEFAULT true,
    financial_control boolean DEFAULT true,
    included boolean DEFAULT true,
    note text
);


--
-- Name: carbon_entities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_entities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_entities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_entities_id_seq OWNED BY public.carbon_entities.id;


--
-- Name: carbon_financed_exposures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_financed_exposures (
    id integer NOT NULL,
    reporting_period_id integer NOT NULL,
    reference character varying(100),
    borrower character varying(255),
    asset_class character varying(30) DEFAULT 'business_loans'::character varying,
    sector character varying(100),
    outstanding numeric(18,2) DEFAULT 0 NOT NULL,
    attribution_base numeric(18,2),
    method character varying(20) DEFAULT 'asset'::character varying NOT NULL,
    borrower_emissions_tco2e numeric(18,6),
    borrower_revenue_egp numeric(18,2),
    factor_id integer,
    factor_kgco2e_used numeric(18,6),
    attribution numeric(10,6),
    financed_tco2e numeric(18,6),
    data_quality_score integer,
    error character varying(200),
    source character varying(10) DEFAULT 'manual'::character varying,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: carbon_financed_exposures_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_financed_exposures_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_financed_exposures_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_financed_exposures_id_seq OWNED BY public.carbon_financed_exposures.id;


--
-- Name: carbon_initiatives; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_initiatives (
    id integer NOT NULL,
    title character varying(255) NOT NULL,
    scope character varying(10),
    owner_user_id integer,
    start_date date,
    target_date date,
    expected_reduction_tco2e numeric(18,3),
    achieved_reduction_tco2e numeric(18,3),
    cost_egp numeric(18,2),
    status character varying(12) DEFAULT 'planned'::character varying,
    note text,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: carbon_initiatives_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_initiatives_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_initiatives_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_initiatives_id_seq OWNED BY public.carbon_initiatives.id;


--
-- Name: carbon_offset_obligations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_offset_obligations (
    id integer NOT NULL,
    reporting_period_id integer NOT NULL,
    total_emissions_tco2e numeric NOT NULL,
    offset_pct numeric DEFAULT 20 NOT NULL,
    required_tco2e numeric NOT NULL,
    report_submitted_date date NOT NULL,
    deadline_date date NOT NULL,
    status character varying(20) DEFAULT 'OPEN'::character varying NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: carbon_offset_obligations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_offset_obligations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_offset_obligations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_offset_obligations_id_seq OWNED BY public.carbon_offset_obligations.id;


--
-- Name: carbon_offset_purchases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_offset_purchases (
    id integer NOT NULL,
    obligation_id integer NOT NULL,
    project_name character varying(250) NOT NULL,
    registry_reference character varying(150),
    quantity_tco2e numeric NOT NULL,
    purchase_date date NOT NULL,
    cost_egp numeric,
    notes text,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    retired_on date,
    serial_numbers text,
    standard character varying(60),
    vintage_year integer,
    fra_project_id character varying(100)
);


--
-- Name: carbon_offset_purchases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_offset_purchases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_offset_purchases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_offset_purchases_id_seq OWNED BY public.carbon_offset_purchases.id;


--
-- Name: carbon_period_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_period_metrics (
    id integer NOT NULL,
    reporting_period_id integer NOT NULL,
    revenue_egp numeric(18,2),
    headcount integer,
    floor_area_m2 numeric(12,2),
    financed_portfolio_egp numeric(18,2),
    updated_by integer,
    updated_at timestamp without time zone
);


--
-- Name: carbon_period_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_period_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_period_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_period_metrics_id_seq OWNED BY public.carbon_period_metrics.id;


--
-- Name: carbon_period_workflow; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_period_workflow (
    id integer NOT NULL,
    reporting_period_id integer NOT NULL,
    status character varying(12) DEFAULT 'preparing'::character varying NOT NULL,
    prepared_by integer,
    prepared_at timestamp without time zone,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    approved_by integer,
    approved_at timestamp without time zone,
    note text
);


--
-- Name: carbon_period_workflow_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_period_workflow_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_period_workflow_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_period_workflow_id_seq OWNED BY public.carbon_period_workflow.id;


--
-- Name: carbon_scope_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_scope_config (
    id integer NOT NULL,
    company_label character varying(120) NOT NULL,
    scope1_enabled boolean DEFAULT true NOT NULL,
    scope2_enabled boolean DEFAULT true NOT NULL,
    scope3_enabled boolean DEFAULT false NOT NULL,
    issued_capital_egp numeric,
    net_equity_egp numeric,
    fiscal_year_end date,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    consolidation_approach character varying(20) DEFAULT 'operational_control'::character varying,
    base_year integer,
    base_year_tco2e numeric(18,3),
    recalculation_threshold_pct numeric(6,2),
    recalculation_policy text
);


--
-- Name: carbon_scope_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_scope_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_scope_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_scope_config_id_seq OWNED BY public.carbon_scope_config.id;


--
-- Name: carbon_sites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_sites (
    id integer NOT NULL,
    entity_id integer,
    name character varying(255),
    site_type character varying(20) DEFAULT 'office'::character varying,
    city character varying(100),
    floor_area_m2 numeric(12,2),
    headcount integer,
    is_active boolean DEFAULT true,
    opened_on date,
    closed_on date
);


--
-- Name: carbon_sites_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_sites_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_sites_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_sites_id_seq OWNED BY public.carbon_sites.id;


--
-- Name: carbon_targets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_targets (
    id integer NOT NULL,
    baseline_year integer NOT NULL,
    baseline_tco2e double precision DEFAULT 0 NOT NULL,
    target_2030_pct double precision DEFAULT 50,
    target_2035_pct double precision DEFAULT 70,
    sbti_aligned boolean DEFAULT false,
    notes text,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: carbon_targets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_targets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_targets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_targets_id_seq OWNED BY public.carbon_targets.id;


--
-- Name: carbon_workflow_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.carbon_workflow_events (
    id integer NOT NULL,
    reporting_period_id integer NOT NULL,
    action character varying(20) NOT NULL,
    from_status character varying(12),
    to_status character varying(12),
    user_id integer,
    note text,
    at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: carbon_workflow_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.carbon_workflow_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: carbon_workflow_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.carbon_workflow_events_id_seq OWNED BY public.carbon_workflow_events.id;


--
-- Name: case_escalation_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_escalation_settings (
    id integer DEFAULT 1 NOT NULL,
    cutover_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT case_escalation_settings_id_check CHECK ((id = 1))
);


--
-- Name: case_reminders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_reminders (
    id integer NOT NULL,
    case_id integer NOT NULL,
    case_type text DEFAULT 'whistleblowing'::text NOT NULL,
    sent_to integer,
    sent_by integer,
    reminder_type text DEFAULT 'assignee'::text NOT NULL,
    channel text DEFAULT 'inapp'::text NOT NULL,
    message text,
    is_bulk boolean DEFAULT false NOT NULL,
    sent_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: case_reminders_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.case_reminders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: case_reminders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.case_reminders_id_seq OWNED BY public.case_reminders.id;


--
-- Name: case_sla_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_sla_config (
    case_type character varying(30) NOT NULL,
    sla_days integer NOT NULL,
    description text
);


--
-- Name: cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cases (
    id integer NOT NULL,
    case_type character varying(30) NOT NULL,
    source_table character varying(60) NOT NULL,
    source_record_id integer NOT NULL,
    reference character varying(60),
    title text,
    status character varying(30) NOT NULL,
    priority character varying(20),
    party_id integer,
    assigned_to integer,
    opened_at timestamp without time zone DEFAULT now() NOT NULL,
    due_date timestamp without time zone,
    resolved_at timestamp without time zone,
    last_synced_at timestamp without time zone DEFAULT now()
);


--
-- Name: cases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cases_id_seq OWNED BY public.cases.id;


--
-- Name: cdd_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cdd_documents (
    id integer NOT NULL,
    customer_id integer,
    document_type text,
    document_name text,
    file_path text,
    file_size integer,
    mime_type text,
    uploaded_by integer,
    upload_date text,
    verified integer,
    verified_by integer,
    verification_date text,
    verification_notes text,
    expiry_date text,
    is_expired integer,
    created_at text
);


--
-- Name: cdd_documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cdd_documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cdd_documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cdd_documents_id_seq OWNED BY public.cdd_documents.id;


--
-- Name: cdd_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cdd_reviews (
    id integer NOT NULL,
    customer_id integer,
    review_date text,
    review_type text,
    reviewed_by integer,
    review_notes text,
    documents_reviewed text,
    risk_classification_changed integer,
    previous_risk_classification text,
    new_risk_classification text,
    reclassification_reason text,
    actions_required text,
    actions_completed integer,
    actions_completed_date text,
    next_review_date text,
    created_at text
);


--
-- Name: cdd_reviews_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cdd_reviews_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cdd_reviews_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cdd_reviews_id_seq OWNED BY public.cdd_reviews.id;


--
-- Name: cdd_risk_factors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cdd_risk_factors (
    id integer NOT NULL,
    factor_category text,
    factor_name text,
    factor_description text,
    risk_weight integer,
    is_edd_trigger integer,
    is_active integer
);


--
-- Name: cdd_risk_factors_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cdd_risk_factors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cdd_risk_factors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cdd_risk_factors_id_seq OWNED BY public.cdd_risk_factors.id;


--
-- Name: cobec_declarations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cobec_declarations (
    id integer NOT NULL,
    employee_id integer,
    declaration_year integer,
    has_read_code integer,
    understands_responsibilities integer,
    commits_to_compliance integer,
    will_report_violations integer,
    has_known_violations integer,
    violation_details text,
    has_prior_misconduct integer,
    misconduct_details text,
    digital_signature text,
    status text,
    reviewer_id integer,
    review_date text,
    review_comments text,
    created_at text,
    updated_at text
);


--
-- Name: cobec_declarations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cobec_declarations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cobec_declarations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cobec_declarations_id_seq OWNED BY public.cobec_declarations.id;


--
-- Name: coi_campaign_employees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.coi_campaign_employees (
    id integer NOT NULL,
    campaign_id integer,
    employee_id integer,
    status text,
    reminder_sent integer,
    reminder_date text,
    completed_date text
);


--
-- Name: coi_campaign_employees_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.coi_campaign_employees_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: coi_campaign_employees_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.coi_campaign_employees_id_seq OWNED BY public.coi_campaign_employees.id;


--
-- Name: coi_campaigns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.coi_campaigns (
    id integer NOT NULL,
    campaign_name text,
    campaign_year integer,
    start_date text,
    end_date text,
    is_active integer,
    description text,
    status text,
    campaign_type text,
    created_by integer,
    created_at text
);


--
-- Name: coi_campaigns_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.coi_campaigns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: coi_campaigns_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.coi_campaigns_id_seq OWNED BY public.coi_campaigns.id;


--
-- Name: coi_declaration_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.coi_declaration_history (
    id integer NOT NULL,
    declaration_id integer,
    action text,
    performer_id integer,
    status_before text,
    status_after text,
    comments text,
    created_at text
);


--
-- Name: coi_declaration_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.coi_declaration_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: coi_declaration_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.coi_declaration_history_id_seq OWNED BY public.coi_declaration_history.id;


--
-- Name: coi_declarations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.coi_declarations (
    id integer NOT NULL,
    employee_id integer,
    campaign_id integer,
    declaration_date text,
    has_conflict integer,
    details text,
    status text,
    mitigation_plan text,
    reviewed_by integer,
    review_date text,
    review_comments text,
    created_at text,
    updated_at text,
    has_financial_interests integer,
    financial_interests_details text,
    has_family_in_competitor integer,
    family_competitor_details text,
    has_family_in_supplier integer,
    family_supplier_details text,
    has_outside_employment integer,
    outside_employment_details text,
    has_received_gifts integer,
    gifts_details text,
    has_other_conflicts integer,
    other_conflicts_details text,
    declaration_statement text,
    digital_signature text,
    pin_code text,
    reviewer_id integer,
    mitigation_plan_id integer
);


--
-- Name: coi_declarations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.coi_declarations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: coi_declarations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.coi_declarations_id_seq OWNED BY public.coi_declarations.id;


--
-- Name: coi_disclosures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.coi_disclosures (
    id integer NOT NULL,
    employee_id integer,
    disclosure_type text,
    description text,
    related_party text,
    relationship_type text,
    financial_interest text,
    disclosed_date text,
    review_status text DEFAULT 'PENDING'::text,
    reviewed_by integer,
    reviewed_at text,
    review_notes text,
    risk_assessment text,
    mitigation_action text,
    department_id integer,
    created_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text),
    updated_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text)
);


--
-- Name: coi_disclosures_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.coi_disclosures_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: coi_disclosures_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.coi_disclosures_id_seq OWNED BY public.coi_disclosures.id;


--
-- Name: coi_mitigation_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.coi_mitigation_history (
    id integer NOT NULL,
    mitigation_plan_id integer,
    action text,
    action_by integer,
    action_date text,
    old_status text,
    new_status text,
    comments text
);


--
-- Name: coi_mitigation_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.coi_mitigation_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: coi_mitigation_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.coi_mitigation_history_id_seq OWNED BY public.coi_mitigation_history.id;


--
-- Name: coi_mitigation_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.coi_mitigation_plans (
    id integer NOT NULL,
    declaration_id integer,
    mitigation_strategy text,
    plan_details text,
    assigned_to integer,
    target_date text,
    status text,
    reviewer_comments text,
    created_at text,
    updated_at text,
    created_by integer
);


--
-- Name: coi_mitigation_plans_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.coi_mitigation_plans_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: coi_mitigation_plans_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.coi_mitigation_plans_id_seq OWNED BY public.coi_mitigation_plans.id;


--
-- Name: committee_meetings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.committee_meetings (
    id integer NOT NULL,
    committee_id integer,
    meeting_reference text,
    meeting_date text,
    agenda text,
    minutes_file_path text,
    quorum_met integer,
    created_at text
);


--
-- Name: committee_meetings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.committee_meetings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: committee_meetings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.committee_meetings_id_seq OWNED BY public.committee_meetings.id;


--
-- Name: committee_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.committee_members (
    id integer NOT NULL,
    committee_id integer,
    board_member_id integer,
    role text,
    appointment_date text,
    term_end_date text,
    is_active integer,
    created_at text
);


--
-- Name: committee_members_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.committee_members_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: committee_members_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.committee_members_id_seq OWNED BY public.committee_members.id;


--
-- Name: committee_memberships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.committee_memberships (
    id integer NOT NULL,
    committee_id integer,
    member_id integer,
    role text,
    meets_requirements integer,
    independence_status text,
    has_required_expertise integer,
    expertise_verified_by text,
    expertise_verified_date text,
    joined_date text,
    term_start text,
    term_end text,
    meetings_attended integer,
    meetings_scheduled integer,
    attendance_rate double precision,
    contribution_score double precision,
    last_evaluation_date text,
    is_active integer,
    departure_date text,
    departure_reason text,
    created_at text
);


--
-- Name: committee_memberships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.committee_memberships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: committee_memberships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.committee_memberships_id_seq OWNED BY public.committee_memberships.id;


--
-- Name: committees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.committees (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    committee_type character varying(100),
    is_active integer DEFAULT 1,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: committees_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.committees_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: committees_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.committees_id_seq OWNED BY public.committees.id;


--
-- Name: complaint_activity_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.complaint_activity_log (
    id integer NOT NULL,
    complaint_id integer,
    activity_type text,
    activity_description text,
    new_status text,
    performed_by integer,
    activity_timestamp text
);


--
-- Name: complaint_activity_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.complaint_activity_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: complaint_activity_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.complaint_activity_log_id_seq OWNED BY public.complaint_activity_log.id;


--
-- Name: complaint_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.complaint_categories (
    id integer NOT NULL,
    category_code text,
    category_name_en text,
    category_name_ar text,
    display_order integer
);


--
-- Name: complaint_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.complaint_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: complaint_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.complaint_categories_id_seq OWNED BY public.complaint_categories.id;


--
-- Name: complaint_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.complaint_documents (
    id integer NOT NULL,
    complaint_id integer,
    file_name text,
    file_path text,
    uploaded_by text,
    uploaded_at text
);


--
-- Name: complaint_documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.complaint_documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: complaint_documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.complaint_documents_id_seq OWNED BY public.complaint_documents.id;


--
-- Name: compliance_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.compliance_events (
    id integer NOT NULL,
    event_type character varying(100) NOT NULL,
    source_module character varying(60),
    source_table character varying(60),
    source_record_id integer,
    entity_type character varying(30),
    entity_id integer,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    error_message text,
    created_by integer,
    created_at timestamp without time zone DEFAULT now(),
    processed_at timestamp without time zone
);


--
-- Name: compliance_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.compliance_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: compliance_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.compliance_events_id_seq OWNED BY public.compliance_events.id;


--
-- Name: conduct_declarations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conduct_declarations (
    id integer NOT NULL,
    employee_id integer,
    declaration_type text,
    period_year integer,
    period_quarter integer,
    declaration_text text,
    has_violations integer DEFAULT 0,
    violation_details text,
    signed_at text,
    review_status text DEFAULT 'PENDING'::text,
    reviewed_by integer,
    reviewed_at text,
    review_notes text,
    department_id integer,
    created_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text),
    updated_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text)
);


--
-- Name: conduct_declarations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.conduct_declarations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: conduct_declarations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.conduct_declarations_id_seq OWNED BY public.conduct_declarations.id;


--
-- Name: confirmed_matches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.confirmed_matches (
    id integer NOT NULL,
    entity_name text NOT NULL,
    normalized_name text,
    entity_type text,
    matched_entity_id integer,
    matched_name text,
    list_source text,
    list_type text,
    match_score double precision,
    screening_history_id integer,
    queue_id integer,
    source_module text,
    source_record_id integer,
    customer_id integer,
    confirmed_by integer,
    confirmed_at timestamp without time zone DEFAULT now() NOT NULL,
    confirmation_reason text,
    action_taken text,
    str_reference text,
    str_filed_at timestamp without time zone,
    str_filed_by integer,
    reported_to_emlcu boolean DEFAULT false NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    closed_at timestamp without time zone,
    closed_by integer,
    closure_reason text,
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: confirmed_matches_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.confirmed_matches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: confirmed_matches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.confirmed_matches_id_seq OWNED BY public.confirmed_matches.id;


--
-- Name: conflict_of_interest; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conflict_of_interest (
    id integer NOT NULL,
    member_id integer,
    declaration_date text,
    declaration_type text,
    has_conflict integer,
    conflict_category text,
    conflict_description text,
    related_entity_name text,
    related_entity_type text,
    nature_of_relationship text,
    financial_value double precision,
    transaction_date text,
    transaction_description text,
    transaction_value double precision,
    transaction_approved integer,
    mitigation_action text,
    mitigation_implemented integer,
    mitigation_date text,
    recusal_required integer,
    recused_from_decisions text,
    reviewed_by text,
    review_date text,
    approval_status text,
    approval_conditions text,
    is_active integer,
    resolved_date text,
    resolution_notes text,
    created_at text,
    updated_at text
);


--
-- Name: conflict_of_interest_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.conflict_of_interest_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: conflict_of_interest_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.conflict_of_interest_id_seq OWNED BY public.conflict_of_interest.id;


--
-- Name: consent_purposes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consent_purposes (
    id integer NOT NULL,
    purpose_code text,
    purpose_name_en text,
    purpose_name_ar text,
    purpose_description_en text,
    purpose_description_ar text,
    legal_basis text,
    is_required integer,
    data_categories text,
    recipients text,
    retention_period text,
    version integer,
    active integer,
    created_at text
);


--
-- Name: consent_purposes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.consent_purposes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: consent_purposes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.consent_purposes_id_seq OWNED BY public.consent_purposes.id;


--
-- Name: consents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consents (
    id integer NOT NULL,
    data_subject_id text,
    data_subject_identifier text,
    purpose_id integer,
    consent_given integer,
    consent_date text,
    consent_method text,
    consent_text text,
    ip_address text,
    user_agent text,
    withdrawn integer,
    withdrawal_date text,
    withdrawal_method text,
    withdrawal_reason text,
    created_at text
);


--
-- Name: consents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.consents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: consents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.consents_id_seq OWNED BY public.consents.id;


--
-- Name: consumer_complaints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consumer_complaints (
    id integer NOT NULL,
    complaint_pin text,
    customer_name text,
    customer_email text,
    customer_phone text,
    customer_id_number text,
    customer_type text,
    complaint_channel text,
    complaint_category text,
    complaint_subject text,
    complaint_description text,
    statutory_deadline_date text,
    days_remaining_to_deadline integer,
    status text,
    priority text,
    assigned_to_user_id integer,
    resolution_summary text,
    created_at text,
    updated_at text
);


--
-- Name: consumer_complaints_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.consumer_complaints_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: consumer_complaints_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.consumer_complaints_id_seq OWNED BY public.consumer_complaints.id;


--
-- Name: control_test_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.control_test_results (
    id integer NOT NULL,
    control_id integer NOT NULL,
    tested_by integer,
    test_date date NOT NULL,
    test_procedure text,
    result character varying(20) NOT NULL,
    exceptions_noted text,
    evidence_file character varying(500),
    audit_project_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT control_test_results_result_check CHECK (((result)::text = ANY (ARRAY[('EFFECTIVE'::character varying)::text, ('PARTIALLY_EFFECTIVE'::character varying)::text, ('INEFFECTIVE'::character varying)::text])))
);


--
-- Name: control_test_results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.control_test_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: control_test_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.control_test_results_id_seq OWNED BY public.control_test_results.id;


--
-- Name: controls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.controls (
    id integer NOT NULL,
    control_code character varying(30) NOT NULL,
    control_name character varying(255) NOT NULL,
    control_description text,
    control_type character varying(20) NOT NULL,
    control_nature character varying(20) DEFAULT 'MANUAL'::character varying NOT NULL,
    control_owner_id integer,
    department_id integer,
    testing_frequency character varying(20) DEFAULT 'ANNUAL'::character varying NOT NULL,
    last_tested_date date,
    last_test_result character varying(20),
    next_test_due_date date,
    status character varying(20) DEFAULT 'ACTIVE'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT controls_control_nature_check CHECK (((control_nature)::text = ANY (ARRAY[('MANUAL'::character varying)::text, ('AUTOMATED'::character varying)::text, ('IT_DEPENDENT'::character varying)::text]))),
    CONSTRAINT controls_control_type_check CHECK (((control_type)::text = ANY (ARRAY[('PREVENTIVE'::character varying)::text, ('DETECTIVE'::character varying)::text, ('CORRECTIVE'::character varying)::text]))),
    CONSTRAINT controls_last_test_result_check CHECK (((last_test_result)::text = ANY (ARRAY[('EFFECTIVE'::character varying)::text, ('PARTIALLY_EFFECTIVE'::character varying)::text, ('INEFFECTIVE'::character varying)::text, ('NOT_TESTED'::character varying)::text]))),
    CONSTRAINT controls_status_check CHECK (((status)::text = ANY (ARRAY[('ACTIVE'::character varying)::text, ('RETIRED'::character varying)::text]))),
    CONSTRAINT controls_testing_frequency_check CHECK (((testing_frequency)::text = ANY (ARRAY[('MONTHLY'::character varying)::text, ('QUARTERLY'::character varying)::text, ('SEMI_ANNUAL'::character varying)::text, ('ANNUAL'::character varying)::text, ('AD_HOC'::character varying)::text])))
);


--
-- Name: controls_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.controls_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: controls_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.controls_id_seq OWNED BY public.controls.id;


--
-- Name: corp_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.corp_profile (
    id integer DEFAULT 1 NOT NULL,
    legal_name_en character varying(255),
    legal_name_ar character varying(255),
    registered_address_en text,
    registered_address_ar text,
    address_aliases text[] DEFAULT '{}'::text[] NOT NULL,
    commercial_register_no character varying(100),
    tax_card_no character varying(100),
    licence_number character varying(100),
    licence_type character varying(40),
    regulator_id integer,
    phone character varying(60),
    email character varying(200),
    website character varying(200),
    updated_by integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT corp_profile_id_check CHECK ((id = 1))
);


--
-- Name: customer_complaints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_complaints (
    id integer NOT NULL,
    complaint_reference text,
    customer_id integer,
    customer_name text,
    customer_email text,
    customer_phone text,
    complaint_date text,
    intake_channel text,
    complaint_category text,
    severity text,
    complaint_description text,
    acknowledgment_due_date text,
    acknowledgment_sent integer,
    acknowledgment_date text,
    acknowledgment_sent_by integer,
    resolution_due_date text,
    resolution_overdue integer,
    extension_requested integer,
    extension_reason text,
    revised_due_date text,
    assigned_to integer,
    assigned_date text,
    investigation_notes text,
    evidence_collected text,
    related_transaction_ids text,
    resolution_status text,
    resolution_outcome text,
    resolution_description text,
    resolution_date text,
    resolved_by integer,
    compensation_provided integer,
    compensation_type text,
    compensation_amount numeric,
    compensation_currency text,
    customer_notified integer,
    customer_notification_date text,
    customer_satisfaction text,
    escalated_to_cbe integer,
    cbe_escalation_date text,
    cbe_reference_number text,
    cbe_outcome text,
    root_cause text,
    preventive_action_taken text,
    closed integer,
    closed_date text,
    created_at text,
    updated_at text
);


--
-- Name: customer_complaints_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.customer_complaints_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: customer_complaints_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.customer_complaints_id_seq OWNED BY public.customer_complaints.id;


--
-- Name: customer_consents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_consents (
    id integer NOT NULL,
    customer_id integer,
    purpose_id integer,
    purpose_version integer,
    consent_given integer,
    consent_date text,
    consent_method text,
    consent_ip_address text,
    consent_user_agent text,
    consent_text_shown text,
    consent_withdrawn integer,
    withdrawal_date text,
    withdrawal_method text,
    is_active integer,
    created_at text
);


--
-- Name: customer_consents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.customer_consents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: customer_consents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.customer_consents_id_seq OWNED BY public.customer_consents.id;


--
-- Name: customer_risk_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_risk_scores (
    id integer NOT NULL,
    customer_id integer,
    factor_id integer,
    factor_value text,
    score_contribution integer,
    assessment_date text,
    assessed_by integer
);


--
-- Name: customer_risk_scores_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.customer_risk_scores_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: customer_risk_scores_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.customer_risk_scores_id_seq OWNED BY public.customer_risk_scores.id;


--
-- Name: customer_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_transactions (
    id text NOT NULL,
    customer_id text,
    amount numeric,
    currency text,
    transaction_type text,
    "timestamp" text,
    description text,
    status text
);


--
-- Name: customers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customers (
    id integer NOT NULL,
    customer_reference text,
    customer_type text,
    full_name text,
    date_of_birth text,
    nationality text,
    id_type text,
    id_number text,
    id_expiry_date text,
    company_name text,
    registration_number text,
    registration_country text,
    incorporation_date text,
    business_activity text,
    address_line1 text,
    address_line2 text,
    city text,
    country text,
    postal_code text,
    phone text,
    email text,
    occupation text,
    employer text,
    source_of_income text,
    annual_income_range text,
    purpose_of_relationship text,
    expected_transaction_volume text,
    risk_classification text,
    risk_classification_date text,
    risk_classification_reason text,
    risk_score integer,
    is_pep integer,
    pep_category text,
    pep_position text,
    pep_screening_date text,
    pep_approved_by integer,
    pep_approval_date text,
    pep_approval_notes text,
    onboarding_date text,
    cdd_completed integer,
    cdd_completed_by integer,
    cdd_completed_date text,
    last_review_date text,
    next_review_date text,
    status text,
    status_reason text,
    approved_by integer,
    approval_date text,
    closed_date text,
    closed_reason text,
    created_at text,
    created_by integer,
    updated_at text,
    updated_by integer,
    full_name_arabic text,
    customer_number text,
    email_encrypted text,
    phone_encrypted text,
    national_id_hash text,
    is_encrypted integer,
    is_sanctioned integer,
    is_high_risk_country integer,
    requires_edd integer,
    edd_completed integer,
    risk_classified_by integer,
    risk_override_reason text,
    edd_approved_by integer,
    edd_approval_date text,
    screening_status text,
    last_screening_date text,
    last_screened_by integer,
    screening_notes text
);


--
-- Name: customers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.customers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: customers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.customers_id_seq OWNED BY public.customers.id;


--
-- Name: cy_assessments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cy_assessments (
    id integer NOT NULL,
    assessment_type character varying(30) NOT NULL,
    title character varying(255) NOT NULL,
    provider character varying(200),
    provider_qualification character varying(255),
    performed_on date NOT NULL,
    valid_until date,
    scope text,
    critical_open integer DEFAULT 0 NOT NULL,
    high_open integer DEFAULT 0 NOT NULL,
    status character varying(10) DEFAULT 'draft'::character varying NOT NULL,
    accepted_by integer,
    accepted_at timestamp without time zone,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT cy_assessments_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'accepted'::character varying])::text[])))
);


--
-- Name: cy_assessments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cy_assessments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cy_assessments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cy_assessments_id_seq OWNED BY public.cy_assessments.id;


--
-- Name: cy_backups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cy_backups (
    id integer NOT NULL,
    system_name character varying(200) NOT NULL,
    backup_type character varying(12) DEFAULT 'full'::character varying NOT NULL,
    location_type character varying(10) DEFAULT 'offsite'::character varying NOT NULL,
    location_detail character varying(255),
    encrypted boolean DEFAULT false NOT NULL,
    last_success_at timestamp without time zone,
    last_status character varying(10),
    last_message text,
    last_restore_test date,
    is_active boolean DEFAULT true NOT NULL,
    source character varying(10) DEFAULT 'manual'::character varying NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT cy_backups_backup_type_check CHECK (((backup_type)::text = ANY ((ARRAY['full'::character varying, 'incremental'::character varying, 'snapshot'::character varying, 'replication'::character varying])::text[]))),
    CONSTRAINT cy_backups_last_status_check CHECK (((last_status)::text = ANY ((ARRAY['success'::character varying, 'failed'::character varying, 'partial'::character varying])::text[]))),
    CONSTRAINT cy_backups_location_type_check CHECK (((location_type)::text = ANY ((ARRAY['onsite'::character varying, 'offsite'::character varying, 'cloud'::character varying])::text[]))),
    CONSTRAINT cy_backups_source_check CHECK (((source)::text = ANY ((ARRAY['manual'::character varying, 'api'::character varying])::text[])))
);


--
-- Name: cy_backups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cy_backups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cy_backups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cy_backups_id_seq OWNED BY public.cy_backups.id;


--
-- Name: cy_bcp_sites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cy_bcp_sites (
    id integer NOT NULL,
    name character varying(200) NOT NULL,
    site_type character varying(12) DEFAULT 'dr'::character varying NOT NULL,
    location character varying(255),
    provider character varying(200),
    rto_hours numeric(8,2),
    rpo_hours numeric(8,2),
    is_active boolean DEFAULT true NOT NULL,
    note text,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT cy_bcp_sites_site_type_check CHECK (((site_type)::text = ANY ((ARRAY['primary'::character varying, 'dr'::character varying, 'backup'::character varying, 'cloud'::character varying])::text[])))
);


--
-- Name: cy_bcp_sites_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cy_bcp_sites_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cy_bcp_sites_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cy_bcp_sites_id_seq OWNED BY public.cy_bcp_sites.id;


--
-- Name: cy_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cy_domains (
    id integer NOT NULL,
    domain character varying(255) NOT NULL,
    port integer DEFAULT 443 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    last_checked_at timestamp without time zone,
    cert_subject character varying(500),
    cert_issuer character varying(500),
    cert_not_after timestamp without time zone,
    last_error text,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: cy_domains_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cy_domains_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cy_domains_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cy_domains_id_seq OWNED BY public.cy_domains.id;


--
-- Name: cy_dr_tests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cy_dr_tests (
    id integer NOT NULL,
    site_id integer,
    test_date date NOT NULL,
    scope text,
    result character varying(10) NOT NULL,
    rto_achieved_hours numeric(8,2),
    rpo_achieved_hours numeric(8,2),
    issues text,
    finding_id integer,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT cy_dr_tests_result_check CHECK (((result)::text = ANY ((ARRAY['pass'::character varying, 'partial'::character varying, 'fail'::character varying])::text[])))
);


--
-- Name: cy_dr_tests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cy_dr_tests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cy_dr_tests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cy_dr_tests_id_seq OWNED BY public.cy_dr_tests.id;


--
-- Name: cy_integrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cy_integrations (
    id integer NOT NULL,
    code character varying(40) NOT NULL,
    name character varying(200) NOT NULL,
    counterparty character varying(200),
    purpose text,
    integration_type character varying(10) DEFAULT 'api'::character varying NOT NULL,
    status character varying(14) DEFAULT 'not_connected'::character varying NOT NULL,
    last_success_at timestamp without time zone,
    last_checked_at timestamp without time zone,
    note text,
    pack_code character varying(40),
    updated_by integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT cy_integrations_integration_type_check CHECK (((integration_type)::text = ANY ((ARRAY['api'::character varying, 'sftp'::character varying, 'portal'::character varying, 'email'::character varying, 'manual'::character varying])::text[]))),
    CONSTRAINT cy_integrations_status_check CHECK (((status)::text = ANY ((ARRAY['live'::character varying, 'testing'::character varying, 'down'::character varying, 'not_connected'::character varying])::text[])))
);


--
-- Name: cy_integrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cy_integrations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cy_integrations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cy_integrations_id_seq OWNED BY public.cy_integrations.id;


--
-- Name: cy_maturity_assessments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cy_maturity_assessments (
    id integer NOT NULL,
    framework_id integer NOT NULL,
    title character varying(255) NOT NULL,
    assessed_on date DEFAULT CURRENT_DATE NOT NULL,
    status character varying(10) DEFAULT 'draft'::character varying NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT cy_maturity_assessments_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'final'::character varying])::text[])))
);


--
-- Name: cy_maturity_assessments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cy_maturity_assessments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cy_maturity_assessments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cy_maturity_assessments_id_seq OWNED BY public.cy_maturity_assessments.id;


--
-- Name: cy_maturity_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cy_maturity_scores (
    assessment_id integer NOT NULL,
    requirement_id integer NOT NULL,
    current_level integer,
    target_level integer,
    note text,
    CONSTRAINT cy_maturity_scores_current_level_check CHECK (((current_level >= 0) AND (current_level <= 5))),
    CONSTRAINT cy_maturity_scores_target_level_check CHECK (((target_level >= 0) AND (target_level <= 5)))
);


--
-- Name: cy_security_assets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cy_security_assets (
    id integer NOT NULL,
    asset_type character varying(20) NOT NULL,
    product character varying(200) NOT NULL,
    vendor character varying(200),
    licence_ref character varying(200),
    licence_expiry date,
    coverage_note character varying(255),
    is_active boolean DEFAULT true NOT NULL,
    sends_data_abroad boolean,
    data_location character varying(200),
    residency_attested_on date,
    residency_attested_by character varying(200),
    updated_by integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: cy_security_assets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cy_security_assets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cy_security_assets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cy_security_assets_id_seq OWNED BY public.cy_security_assets.id;


--
-- Name: cyber_incidents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cyber_incidents (
    id integer NOT NULL,
    incident_number text,
    incident_date text,
    discovery_date text,
    reported_by text,
    incident_type text,
    incident_description text,
    affected_systems text,
    affected_users_count integer,
    severity text,
    cbe_notification_required integer,
    cbe_notification_deadline text,
    cbe_notified integer,
    cbe_notification_date text,
    cbe_reference text,
    containment_actions text,
    containment_date text,
    eradication_actions text,
    eradication_date text,
    recovery_actions text,
    recovery_date text,
    root_cause text,
    attack_vector text,
    indicators_of_compromise text,
    lessons_learned text,
    preventive_measures text,
    status text,
    created_at text,
    created_by integer,
    closed_date text,
    closed_by integer
);


--
-- Name: cyber_incidents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cyber_incidents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cyber_incidents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cyber_incidents_id_seq OWNED BY public.cyber_incidents.id;


--
-- Name: cybersecurity_incidents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cybersecurity_incidents (
    id integer NOT NULL,
    incident_reference text,
    detection_date text,
    detection_method text,
    detected_by text,
    incident_type text,
    severity text,
    classification_date text,
    classified_by integer,
    incident_description text,
    affected_systems text,
    affected_data text,
    estimated_impact text,
    containment_actions text,
    containment_completed integer,
    containment_date text,
    cbe_notification_required integer,
    cbe_notification_deadline text,
    cbe_notified integer,
    cbe_notification_date text,
    cbe_reference_number text,
    cbe_detailed_report_sent integer,
    cbe_detailed_report_date text,
    eradication_actions text,
    eradication_completed integer,
    eradication_date text,
    recovery_actions text,
    recovery_completed integer,
    recovery_date text,
    systems_restored integer,
    root_cause text,
    lessons_learned text,
    preventive_measures text,
    policies_updated integer,
    board_notified integer,
    board_notification_date text,
    status text,
    closed_date text,
    assigned_to integer,
    ciso_notified integer,
    ciso_notification_date text,
    created_at text,
    updated_at text
);


--
-- Name: cybersecurity_incidents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cybersecurity_incidents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cybersecurity_incidents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cybersecurity_incidents_id_seq OWNED BY public.cybersecurity_incidents.id;


--
-- Name: data_breaches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_breaches (
    id integer NOT NULL,
    breach_number text,
    breach_date text,
    discovery_date text,
    discovered_by text,
    discovery_method text,
    breach_type text,
    breach_description text,
    affected_systems text,
    affected_individuals_count integer,
    data_types_affected text,
    includes_sensitive_data integer,
    sensitive_data_types text,
    potential_harm text,
    severity text,
    severity_score integer,
    pdpc_notification_required integer,
    pdpc_notification_deadline text,
    pdpc_notified integer,
    pdpc_notification_date text,
    pdpc_reference text,
    pdpc_notification_file text,
    individuals_notification_required integer,
    individuals_notified integer,
    individuals_notification_date text,
    individuals_notification_method text,
    individuals_notification_count integer,
    root_cause text,
    investigation_findings text,
    containment_actions text,
    containment_date text,
    remediation_actions text,
    remediation_status text,
    remediation_completion_date text,
    lessons_learned text,
    policy_changes text,
    status text,
    created_at text,
    created_by integer,
    updated_at text,
    closed_date text,
    closed_by integer
);


--
-- Name: data_breaches_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_breaches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_breaches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_breaches_id_seq OWNED BY public.data_breaches.id;


--
-- Name: data_processing_activities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_processing_activities (
    id integer NOT NULL,
    activity_code text,
    activity_name text,
    activity_description text,
    processing_purpose text,
    legal_basis text,
    data_categories text,
    data_subject_categories text,
    recipients text,
    international_transfer integer,
    transfer_countries text,
    transfer_safeguards text,
    retention_period text,
    retention_justification text,
    security_measures text,
    data_owner integer,
    system_name text,
    last_review_date text,
    next_review_date text,
    is_active integer,
    created_at text,
    updated_at text
);


--
-- Name: data_processing_activities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_processing_activities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_processing_activities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_processing_activities_id_seq OWNED BY public.data_processing_activities.id;


--
-- Name: data_source_urls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_source_urls (
    id integer NOT NULL,
    source_id integer,
    url text,
    is_current integer,
    valid_from text,
    valid_until text,
    verified_at text,
    verification_status text,
    verification_error text,
    created_by integer,
    created_at text,
    notes text
);


--
-- Name: data_source_urls_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_source_urls_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_source_urls_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_source_urls_id_seq OWNED BY public.data_source_urls.id;


--
-- Name: data_subject_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_subject_requests (
    id integer NOT NULL,
    request_reference text,
    data_subject_name text,
    data_subject_email text,
    data_subject_phone text,
    customer_id integer,
    request_type text,
    request_date text,
    request_channel text,
    request_description text,
    specific_data_requested text,
    identity_verified integer,
    verification_method text,
    verification_date text,
    verified_by integer,
    assigned_to integer,
    status text,
    due_date text,
    days_remaining integer,
    overdue integer,
    data_inventory_completed integer,
    legal_review_completed integer,
    legal_exceptions text,
    decision text,
    decision_date text,
    decision_by integer,
    decision_rationale text,
    fulfilled integer,
    fulfillment_date text,
    fulfillment_method text,
    data_provided_path text,
    response_sent integer,
    response_date text,
    response_method text,
    closed integer,
    closed_date text,
    escalated_to_pdpc integer,
    pdpc_complaint_date text,
    pdpc_reference_number text,
    created_at text,
    created_by integer
);


--
-- Name: data_subject_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_subject_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_subject_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_subject_requests_id_seq OWNED BY public.data_subject_requests.id;


--
-- Name: data_update_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_update_audit_log (
    id integer NOT NULL,
    update_type text,
    initiated_by integer,
    total_sources integer,
    records_added integer,
    records_updated integer,
    records_unchanged integer,
    errors_count integer,
    status text,
    started_at text,
    completed_at text,
    duration_seconds integer,
    error_message text,
    notes text
);


--
-- Name: data_update_audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_update_audit_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_update_audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_update_audit_log_id_seq OWNED BY public.data_update_audit_log.id;


--
-- Name: declaration_campaign_targets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.declaration_campaign_targets (
    id integer NOT NULL,
    campaign_id integer NOT NULL,
    user_id integer NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    submitted_at timestamp without time zone,
    declaration_id integer,
    last_reminder_at timestamp without time zone,
    reminder_count integer DEFAULT 0 NOT NULL,
    exempt_reason text
);


--
-- Name: declaration_campaign_targets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.declaration_campaign_targets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: declaration_campaign_targets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.declaration_campaign_targets_id_seq OWNED BY public.declaration_campaign_targets.id;


--
-- Name: declaration_campaigns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.declaration_campaigns (
    id integer NOT NULL,
    module text NOT NULL,
    name text NOT NULL,
    cycle_year integer NOT NULL,
    opens_at date,
    due_at date,
    org_scope_unit_id integer,
    include_descendants boolean DEFAULT true NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT dc_module_ck CHECK ((module = ANY (ARRAY['ghe'::text, 'coi'::text, 'cobec'::text])))
);


--
-- Name: declaration_campaigns_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.declaration_campaigns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: declaration_campaigns_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.declaration_campaigns_id_seq OWNED BY public.declaration_campaigns.id;


--
-- Name: departments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.departments (
    id integer NOT NULL,
    name text,
    code text,
    description text,
    created_at text,
    unit_type text DEFAULT 'department'::text NOT NULL,
    parent_id integer,
    is_active boolean DEFAULT true NOT NULL,
    CONSTRAINT departments_unit_type_check CHECK ((unit_type = ANY (ARRAY['department'::text, 'business_unit'::text, 'branch'::text])))
);


--
-- Name: departments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.departments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: departments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.departments_id_seq OWNED BY public.departments.id;


--
-- Name: document_approvals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_approvals (
    id integer NOT NULL,
    policy_id integer NOT NULL,
    workflow_id integer,
    stage_order integer NOT NULL,
    stage_name text NOT NULL,
    approver_user_id integer,
    approver_role text,
    status text DEFAULT 'pending'::text NOT NULL,
    decision_at timestamp without time zone,
    decided_by integer,
    comments text,
    sla_due_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: document_approvals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.document_approvals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: document_approvals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.document_approvals_id_seq OWNED BY public.document_approvals.id;


--
-- Name: document_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_types (
    id integer NOT NULL,
    code text NOT NULL,
    name_en text NOT NULL,
    name_ar text,
    description text,
    icon text DEFAULT 'bi bi-file-earmark-text'::text,
    numbering_prefix text,
    requires_approval boolean DEFAULT true NOT NULL,
    default_review_months integer DEFAULT 12,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: document_types_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.document_types_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: document_types_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.document_types_id_seq OWNED BY public.document_types.id;


--
-- Name: dpias; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dpias (
    id integer NOT NULL,
    assessment_reference text,
    system_name text,
    processing_description text,
    data_categories text,
    purposes text,
    data_subjects_affected text,
    data_retention_period text,
    data_security_measures text,
    risk_likelihood integer,
    risk_impact integer,
    overall_risk_score integer,
    risk_level text,
    mitigation_measures text,
    residual_risk_acceptable integer,
    dpo_advice text,
    dpo_consulted integer,
    dpo_consultation_date text,
    senior_management_approval integer,
    approval_date text,
    review_date text,
    status text,
    created_at text,
    created_by integer
);


--
-- Name: dpias_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dpias_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dpias_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dpias_id_seq OWNED BY public.dpias.id;


--
-- Name: dpo_activities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dpo_activities (
    id integer NOT NULL,
    activity_date text,
    activity_type text,
    activity_description text,
    outcome text,
    follow_up_required integer,
    follow_up_date text,
    logged_by integer,
    created_at text
);


--
-- Name: dpo_activities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dpo_activities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dpo_activities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dpo_activities_id_seq OWNED BY public.dpo_activities.id;


--
-- Name: dpo_appointments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dpo_appointments (
    id integer NOT NULL,
    dpo_name text,
    dpo_email text,
    dpo_phone text,
    dpo_office_address text,
    qualifications text,
    certifications text,
    appointment_date text,
    appointed_by text,
    board_resolution_reference text,
    board_resolution_file_path text,
    registered_with_pdpc integer,
    pdpc_registration_date text,
    pdpc_dpo_id text,
    published_on_website integer,
    website_publication_date text,
    is_active integer,
    termination_date text,
    termination_reason text,
    backup_dpo_name text,
    backup_dpo_email text,
    backup_dpo_phone text,
    created_at text,
    updated_at text
);


--
-- Name: dpo_appointments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dpo_appointments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dpo_appointments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dpo_appointments_id_seq OWNED BY public.dpo_appointments.id;


--
-- Name: dsr_timeline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dsr_timeline (
    id integer NOT NULL,
    request_id integer,
    action_date text,
    action_type text,
    action_description text,
    action_by integer
);


--
-- Name: dsr_timeline_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dsr_timeline_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dsr_timeline_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dsr_timeline_id_seq OWNED BY public.dsr_timeline.id;


--
-- Name: edd_cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.edd_cases (
    id integer NOT NULL,
    case_reference text,
    customer_id integer,
    edd_trigger text,
    trigger_description text,
    trigger_date text,
    assigned_to integer,
    priority text,
    status text,
    status_notes text,
    investigation_notes text,
    additional_documents_required text,
    additional_documents_received integer,
    received_date text,
    compliance_reviewed integer,
    compliance_reviewed_by integer,
    compliance_review_date text,
    compliance_review_notes text,
    senior_management_approval integer,
    approved_by integer,
    approval_date text,
    approval_notes text,
    completion_date text,
    outcome text,
    outcome_notes text,
    relationship_continued integer,
    monitoring_enhanced integer,
    enhanced_monitoring_frequency text,
    created_at text,
    created_by integer,
    updated_at text
);


--
-- Name: edd_cases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.edd_cases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: edd_cases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.edd_cases_id_seq OWNED BY public.edd_cases.id;


--
-- Name: ekyc_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ekyc_audit_log (
    id integer NOT NULL,
    session_id integer,
    user_id integer,
    action character varying(100) NOT NULL,
    details text,
    ip_address character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: ekyc_audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ekyc_audit_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ekyc_audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ekyc_audit_log_id_seq OWNED BY public.ekyc_audit_log.id;


--
-- Name: ekyc_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ekyc_config (
    config_key character varying(100) NOT NULL,
    config_value text NOT NULL,
    description text,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: ekyc_document; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ekyc_document (
    id integer NOT NULL,
    session_id integer NOT NULL,
    doc_role character varying(20) NOT NULL,
    stored_path character varying(500) NOT NULL,
    encryption_key_id character varying(100) NOT NULL,
    checksum_sha256 character varying(64),
    file_size bigint,
    mime_type character varying(50),
    captured_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    purged_at timestamp without time zone,
    client_ocr_hint jsonb,
    CONSTRAINT ekyc_document_doc_role_check CHECK (((doc_role)::text = ANY (ARRAY[('ID_FRONT_VIDEO'::character varying)::text, ('ID_BACK_VIDEO'::character varying)::text, ('SELFIE_VIDEO'::character varying)::text])))
);


--
-- Name: ekyc_document_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ekyc_document_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ekyc_document_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ekyc_document_id_seq OWNED BY public.ekyc_document.id;


--
-- Name: ekyc_result; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ekyc_result (
    id integer NOT NULL,
    session_id integer NOT NULL,
    extracted_full_name_ar character varying(300),
    extracted_full_name_en character varying(300),
    national_id character varying(14),
    national_id_valid boolean,
    dob date,
    gender character varying(10),
    governorate_code character varying(5),
    governorate_name character varying(100),
    ocr_confidence numeric(5,2),
    ocr_engine_used character varying(20),
    face_match_score numeric(5,2),
    face_match_engine character varying(20),
    passive_liveness_score numeric(5,2),
    passive_liveness_pass boolean,
    active_liveness_pass boolean,
    active_liveness_challenge character varying(50),
    document_pad_score numeric(5,2),
    document_pad_pass boolean,
    duplicate_of_session_id integer,
    risk_score numeric(5,2),
    decision character varying(10),
    decision_reasons jsonb,
    screening_history_id integer,
    screening_result character varying(30),
    raw_signals jsonb,
    processed_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    back_card_detected boolean,
    back_ocr_confidence numeric(5,2),
    extracted_occupation character varying(200),
    extracted_marital_status character varying(50),
    id_expiry_raw character varying(50),
    field_sources jsonb,
    extracted_address text,
    final_national_id character varying(20),
    final_name text,
    final_address text,
    CONSTRAINT ekyc_result_decision_check CHECK (((decision)::text = ANY (ARRAY[('PASS'::character varying)::text, ('REVIEW'::character varying)::text, ('FAIL'::character varying)::text])))
);


--
-- Name: ekyc_result_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ekyc_result_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ekyc_result_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ekyc_result_id_seq OWNED BY public.ekyc_result.id;


--
-- Name: ekyc_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ekyc_session (
    id integer NOT NULL,
    session_token character varying(64) NOT NULL,
    customer_reference character varying(200),
    document_type character varying(30) DEFAULT 'NATIONAL_ID'::character varying NOT NULL,
    status character varying(20) DEFAULT 'CREATED'::character varying NOT NULL,
    consent_given boolean DEFAULT false NOT NULL,
    consent_text text,
    consent_given_at timestamp without time zone,
    consent_ip character varying(50),
    locale character varying(5) DEFAULT 'ar'::character varying NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at timestamp without time zone,
    retention_expires_at timestamp without time zone,
    error_message text,
    assigned_to integer,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    final_decision character varying(10),
    decision_by integer,
    decided_at timestamp without time zone,
    decision_notes text,
    onboarded_customer_id integer,
    CONSTRAINT ekyc_session_decision_check CHECK (((final_decision)::text = ANY (ARRAY[('APPROVED'::character varying)::text, ('REJECTED'::character varying)::text]))),
    CONSTRAINT ekyc_session_document_type_check CHECK (((document_type)::text = ANY (ARRAY[('NATIONAL_ID'::character varying)::text, ('PASSPORT'::character varying)::text, ('DRIVING_LICENSE'::character varying)::text, ('COMMERCIAL_REGISTER'::character varying)::text, ('TAX_ID'::character varying)::text]))),
    CONSTRAINT ekyc_session_status_check CHECK (((status)::text = ANY (ARRAY[('CREATED'::character varying)::text, ('CONSENT_GIVEN'::character varying)::text, ('CAPTURED'::character varying)::text, ('QUEUED'::character varying)::text, ('PROCESSING'::character varying)::text, ('NEEDS_REVIEW'::character varying)::text, ('DECISION_PENDING'::character varying)::text, ('APPROVED'::character varying)::text, ('ONBOARDED'::character varying)::text, ('REJECTED'::character varying)::text, ('COMPLETED'::character varying)::text, ('FAILED'::character varying)::text, ('EXPIRED'::character varying)::text])))
);


--
-- Name: ekyc_session_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ekyc_session_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ekyc_session_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ekyc_session_id_seq OWNED BY public.ekyc_session.id;


--
-- Name: email_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_templates (
    id integer NOT NULL,
    template_key text NOT NULL,
    subject text NOT NULL,
    body_html text,
    body_text text,
    is_active boolean DEFAULT true NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_by integer
);


--
-- Name: email_templates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.email_templates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: email_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.email_templates_id_seq OWNED BY public.email_templates.id;


--
-- Name: employee_screenings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.employee_screenings (
    id integer NOT NULL,
    user_id integer NOT NULL,
    screened_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    trigger character varying(20) DEFAULT 'periodic'::character varying NOT NULL,
    history_id integer,
    status character varying(30),
    high_risk_matches integer DEFAULT 0 NOT NULL,
    screened_by integer,
    CONSTRAINT employee_screenings_trigger_check CHECK (((trigger)::text = ANY ((ARRAY['hiring'::character varying, 'periodic'::character varying, 'manual'::character varying])::text[])))
);


--
-- Name: employee_screenings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.employee_screenings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: employee_screenings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.employee_screenings_id_seq OWNED BY public.employee_screenings.id;


--
-- Name: esg_disclosure_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.esg_disclosure_items (
    id integer NOT NULL,
    reporting_period_id integer NOT NULL,
    framework character varying(20) NOT NULL,
    ref_code character varying(20) NOT NULL,
    title character varying(250) NOT NULL,
    requirement text,
    status character varying(20) DEFAULT 'not_started'::character varying NOT NULL,
    owner_id integer,
    evidence_notes text,
    evidence_path text,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    carbon_metric character varying(30),
    title_ar character varying(300),
    requirement_ar text
);


--
-- Name: esg_disclosure_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.esg_disclosure_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: esg_disclosure_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.esg_disclosure_items_id_seq OWNED BY public.esg_disclosure_items.id;


--
-- Name: esg_frameworks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.esg_frameworks (
    id integer NOT NULL,
    code character varying(30) NOT NULL,
    name character varying(150) NOT NULL,
    description text,
    is_default boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    name_ar character varying(300)
);


--
-- Name: esg_frameworks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.esg_frameworks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: esg_frameworks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.esg_frameworks_id_seq OWNED BY public.esg_frameworks.id;


--
-- Name: esg_indicator_responses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.esg_indicator_responses (
    id integer NOT NULL,
    reporting_period_id integer NOT NULL,
    indicator_id integer NOT NULL,
    score double precision,
    raw_value double precision,
    is_auto_computed boolean DEFAULT false,
    evidence_notes text,
    evidence_path text,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: esg_indicator_responses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.esg_indicator_responses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: esg_indicator_responses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.esg_indicator_responses_id_seq OWNED BY public.esg_indicator_responses.id;


--
-- Name: esg_indicators; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.esg_indicators (
    id integer NOT NULL,
    pillar_id integer NOT NULL,
    code character varying(10) NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    weight double precision NOT NULL,
    input_type character varying(20) DEFAULT 'maturity'::character varying NOT NULL,
    integration_source character varying(50),
    display_order integer DEFAULT 0,
    carbon_metric character varying(30),
    name_ar character varying(300),
    description_ar text
);


--
-- Name: esg_indicators_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.esg_indicators_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: esg_indicators_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.esg_indicators_id_seq OWNED BY public.esg_indicators.id;


--
-- Name: esg_materiality_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.esg_materiality_scores (
    id integer NOT NULL,
    reporting_period_id integer NOT NULL,
    topic_id integer NOT NULL,
    stakeholder_importance double precision,
    business_impact double precision,
    notes text,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: esg_materiality_scores_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.esg_materiality_scores_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: esg_materiality_scores_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.esg_materiality_scores_id_seq OWNED BY public.esg_materiality_scores.id;


--
-- Name: esg_materiality_topics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.esg_materiality_topics (
    id integer NOT NULL,
    category character varying(5) NOT NULL,
    name character varying(200) NOT NULL,
    gri_reference character varying(50),
    is_active boolean DEFAULT true,
    display_order integer DEFAULT 0,
    name_ar character varying(300)
);


--
-- Name: esg_materiality_topics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.esg_materiality_topics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: esg_materiality_topics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.esg_materiality_topics_id_seq OWNED BY public.esg_materiality_topics.id;


--
-- Name: esg_pillars; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.esg_pillars (
    id integer NOT NULL,
    framework_id integer NOT NULL,
    code character varying(5) NOT NULL,
    name character varying(100) NOT NULL,
    weight double precision NOT NULL,
    display_order integer DEFAULT 0,
    name_ar character varying(200)
);


--
-- Name: esg_pillars_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.esg_pillars_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: esg_pillars_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.esg_pillars_id_seq OWNED BY public.esg_pillars.id;


--
-- Name: esg_reporting_periods; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.esg_reporting_periods (
    id integer NOT NULL,
    label character varying(50) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    fra_status character varying(30) DEFAULT 'Draft'::character varying NOT NULL,
    verifier_name character varying(200),
    verifier_contact character varying(200),
    sent_to_verifier_at date,
    certified_at date,
    submitted_to_fra_at date,
    verification_notes text
);


--
-- Name: esg_reporting_periods_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.esg_reporting_periods_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: esg_reporting_periods_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.esg_reporting_periods_id_seq OWNED BY public.esg_reporting_periods.id;


--
-- Name: esg_sites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.esg_sites (
    id integer NOT NULL,
    name character varying(150) NOT NULL,
    department_id integer,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: esg_sites_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.esg_sites_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: esg_sites_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.esg_sites_id_seq OWNED BY public.esg_sites.id;


--
-- Name: event_routing_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_routing_rules (
    id integer NOT NULL,
    name character varying(120) NOT NULL,
    event_type_pattern character varying(100) NOT NULL,
    action_type character varying(20) NOT NULL,
    action_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    priority integer DEFAULT 100 NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    description text,
    created_by integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT event_routing_rules_action_type_check CHECK (((action_type)::text = ANY (ARRAY[('notify'::character varying)::text, ('screen'::character varying)::text])))
);


--
-- Name: event_routing_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.event_routing_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: event_routing_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.event_routing_rules_id_seq OWNED BY public.event_routing_rules.id;


--
-- Name: fit_proper_assessments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fit_proper_assessments (
    id integer NOT NULL,
    member_id integer,
    assessment_date text,
    assessment_type text,
    assessment_period text,
    honesty_integrity_score integer,
    competence_capability_score integer,
    financial_soundness_score integer,
    reputation_score integer,
    time_commitment_score integer,
    criminal_record_check integer,
    criminal_record_clear integer,
    criminal_record_details text,
    credit_check integer,
    credit_score integer,
    credit_check_clear integer,
    credit_issues text,
    regulatory_actions_check integer,
    regulatory_actions_found integer,
    regulatory_actions_details text,
    litigation_check integer,
    active_litigation integer,
    litigation_details text,
    bankruptcy_check integer,
    bankruptcy_history integer,
    bankruptcy_details text,
    references_checked integer,
    references_satisfactory integer,
    references_summary text,
    qualifications_verified integer,
    qualification_documents text,
    professional_licenses_valid integer,
    relevant_experience_years integer,
    board_experience_adequate integer,
    industry_knowledge_adequate integer,
    total_score integer,
    assessment_result text,
    conditions_imposed text,
    rejection_reasons text,
    submitted_to_cbe integer,
    cbe_submission_date text,
    cbe_reference_number text,
    cbe_approval_date text,
    cbe_approval_status text,
    cbe_feedback text,
    next_review_date text,
    review_frequency_months integer,
    assessment_report_path text,
    supporting_documents text,
    assessed_by text,
    approved_by text,
    created_at text,
    created_by integer,
    regulator_id integer,
    submitted_to_regulator integer,
    regulator_submission_date text,
    regulator_reference_number text,
    regulator_approval_date text,
    regulator_approval_status text,
    regulator_feedback text
);


--
-- Name: fit_proper_assessments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fit_proper_assessments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fit_proper_assessments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fit_proper_assessments_id_seq OWNED BY public.fit_proper_assessments.id;


--
-- Name: fra_verifiers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fra_verifiers (
    id integer NOT NULL,
    name character varying(250) NOT NULL,
    contact_info text,
    is_active boolean DEFAULT true NOT NULL,
    notes text,
    registration_no character varying(50),
    registered_on date
);


--
-- Name: fra_verifiers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fra_verifiers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fra_verifiers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fra_verifiers_id_seq OWNED BY public.fra_verifiers.id;


--
-- Name: generic_attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.generic_attachments (
    id integer NOT NULL,
    module text NOT NULL,
    record_type text NOT NULL,
    record_id integer NOT NULL,
    filename text NOT NULL,
    file_path text NOT NULL,
    file_size integer,
    description text,
    uploaded_by integer,
    uploaded_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text),
    is_deleted integer DEFAULT 0 NOT NULL,
    deleted_by integer,
    deleted_at text
);


--
-- Name: generic_attachments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.generic_attachments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: generic_attachments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.generic_attachments_id_seq OWNED BY public.generic_attachments.id;


--
-- Name: ghe_approval_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ghe_approval_history (
    id integer NOT NULL,
    ghe_declaration_id integer,
    action text,
    action_by integer,
    action_date text,
    comments text,
    old_status text,
    new_status text
);


--
-- Name: ghe_approval_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ghe_approval_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ghe_approval_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ghe_approval_history_id_seq OWNED BY public.ghe_approval_history.id;


--
-- Name: ghe_declaration_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ghe_declaration_history (
    id integer NOT NULL,
    declaration_id integer,
    action text,
    performer_id integer,
    status_before text,
    status_after text,
    comments text,
    created_at text
);


--
-- Name: ghe_declaration_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ghe_declaration_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ghe_declaration_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ghe_declaration_history_id_seq OWNED BY public.ghe_declaration_history.id;


--
-- Name: ghe_declarations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ghe_declarations (
    id integer NOT NULL,
    declaration_number text,
    employee_id integer,
    declaration_date text,
    ghe_type text,
    direction text,
    event_date text,
    estimated_value_egp numeric,
    currency text,
    description text,
    provider_recipient_name text,
    provider_recipient_company text,
    business_purpose text,
    is_government_official integer,
    government_official_details text,
    government_official_position text,
    status text,
    auto_approved integer,
    manager_id integer,
    manager_approval_date text,
    manager_comments text,
    compliance_officer_id integer,
    compliance_approval_date text,
    compliance_comments text,
    is_public_submission integer,
    submitter_name text,
    submitter_email text,
    submitter_department text,
    tracking_id text,
    needs_more_info integer,
    info_request_message text,
    info_request_date text,
    info_response text,
    info_response_date text,
    attachment_path text,
    created_at text,
    updated_at text,
    created_by integer,
    updated_by integer
);


--
-- Name: ghe_declarations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ghe_declarations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ghe_declarations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ghe_declarations_id_seq OWNED BY public.ghe_declarations.id;


--
-- Name: ghe_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ghe_records (
    id integer NOT NULL,
    employee_id integer,
    gift_type text,
    description text,
    estimated_value numeric(12,2),
    currency text DEFAULT 'EGP'::text,
    giver_receiver_name text,
    giver_receiver_org text,
    direction text,
    event_date text,
    approval_status text DEFAULT 'PENDING'::text,
    approval_level text,
    approved_by integer,
    approved_at text,
    approval_notes text,
    rejection_reason text,
    department_id integer,
    created_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text),
    updated_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text),
    CONSTRAINT ghe_records_direction_check CHECK ((direction = ANY (ARRAY['GIVEN'::text, 'RECEIVED'::text])))
);


--
-- Name: ghe_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ghe_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ghe_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ghe_records_id_seq OWNED BY public.ghe_records.id;


--
-- Name: governance_compliance_tracker; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.governance_compliance_tracker (
    id integer NOT NULL,
    requirement_code text,
    requirement_description text,
    compliance_area text,
    regulatory_source text,
    compliance_status text,
    evidence_description text,
    evidence_document_path text,
    last_audit_date text,
    due_date text,
    completion_date text,
    updated_at text,
    notes text,
    regulator_id integer,
    is_active integer DEFAULT 1 NOT NULL
);


--
-- Name: governance_compliance_tracker_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.governance_compliance_tracker_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: governance_compliance_tracker_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.governance_compliance_tracker_id_seq OWNED BY public.governance_compliance_tracker.id;


--
-- Name: high_risk_countries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.high_risk_countries (
    id integer NOT NULL,
    country_code text,
    country_name text,
    risk_category text,
    source text,
    effective_date text,
    is_active integer
);


--
-- Name: high_risk_countries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.high_risk_countries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: high_risk_countries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.high_risk_countries_id_seq OWNED BY public.high_risk_countries.id;


--
-- Name: ia_area_controls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ia_area_controls (
    universe_id integer NOT NULL,
    control_id integer NOT NULL
);


--
-- Name: incident_response_team; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incident_response_team (
    id integer NOT NULL,
    incident_id integer,
    user_id integer,
    role text,
    assigned_date text
);


--
-- Name: incident_response_team_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.incident_response_team_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: incident_response_team_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.incident_response_team_id_seq OWNED BY public.incident_response_team.id;


--
-- Name: incident_timeline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.incident_timeline (
    id integer NOT NULL,
    incident_id integer,
    event_date text,
    event_type text,
    event_description text,
    action_taken text,
    recorded_by integer
);


--
-- Name: incident_timeline_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.incident_timeline_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: incident_timeline_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.incident_timeline_id_seq OWNED BY public.incident_timeline.id;


--
-- Name: independence_declarations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.independence_declarations (
    id integer NOT NULL,
    member_id integer,
    declaration_date text,
    declaration_type text,
    declaration_period text,
    no_material_interest integer,
    no_employment_5years integer,
    no_relative_employment integer,
    no_professional_relationship integer,
    no_significant_business integer,
    no_remuneration_except_fees integer,
    no_other_directorships integer,
    served_less_than_9years integer,
    criteria_not_met text,
    explanation text,
    independence_status text,
    reviewed_by integer,
    review_date text,
    next_declaration_due text,
    declaration_document_path text
);


--
-- Name: independence_declarations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.independence_declarations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: independence_declarations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.independence_declarations_id_seq OWNED BY public.independence_declarations.id;


--
-- Name: internal_blacklist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.internal_blacklist (
    id integer NOT NULL,
    full_name text,
    original_name text,
    entity_type text,
    national_id text,
    passport_number text,
    date_of_birth text,
    place_of_birth text,
    nationality text,
    registration_number text,
    address text,
    city text,
    country text,
    reason text,
    risk_level text,
    category text,
    aliases text,
    notes text,
    phone_number text,
    email text,
    source text,
    source_id text,
    added_by integer,
    added_date text,
    modified_by integer,
    modified_date text,
    is_active integer,
    expiry_date text,
    created_at text,
    updated_at text,
    confirmation_type text,
    name_search text GENERATED ALWAYS AS (public.cx_name_search(original_name, full_name, aliases)) STORED
);


--
-- Name: internal_blacklist_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.internal_blacklist_audit (
    id integer NOT NULL,
    blacklist_id integer,
    action text,
    field_changed text,
    old_value text,
    new_value text,
    changed_by integer,
    changed_at text,
    reason text
);


--
-- Name: internal_blacklist_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.internal_blacklist_audit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: internal_blacklist_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.internal_blacklist_audit_id_seq OWNED BY public.internal_blacklist_audit.id;


--
-- Name: internal_blacklist_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.internal_blacklist_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: internal_blacklist_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.internal_blacklist_id_seq OWNED BY public.internal_blacklist.id;


--
-- Name: internal_pep; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.internal_pep (
    id integer NOT NULL,
    full_name text,
    original_name text,
    entity_type text,
    national_id text,
    passport_number text,
    date_of_birth text,
    place_of_birth text,
    nationality text,
    registration_number text,
    address text,
    city text,
    country text,
    reason text,
    risk_level text,
    category text,
    "position" text,
    aliases text,
    notes text,
    phone_number text,
    email text,
    source text,
    source_id text,
    added_by integer,
    added_date text,
    modified_by integer,
    modified_date text,
    is_active integer,
    expiry_date text,
    created_at text,
    updated_at text,
    name_search text GENERATED ALWAYS AS (public.cx_name_search(original_name, full_name, aliases)) STORED
);


--
-- Name: internal_pep_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.internal_pep_audit (
    id integer NOT NULL,
    blacklist_id integer,
    action text,
    field_changed text,
    old_value text,
    new_value text,
    changed_by integer,
    changed_at text,
    reason text
);


--
-- Name: internal_pep_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.internal_pep_audit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: internal_pep_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.internal_pep_audit_id_seq OWNED BY public.internal_pep_audit.id;


--
-- Name: internal_pep_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.internal_pep_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: internal_pep_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.internal_pep_id_seq OWNED BY public.internal_pep.id;


--
-- Name: kri_measurements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kri_measurements (
    id integer NOT NULL,
    kri_id integer NOT NULL,
    measurement_date date NOT NULL,
    actual_value numeric(15,2) NOT NULL,
    status character varying(10) NOT NULL,
    notes text,
    recorded_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT kri_measurements_status_check CHECK (((status)::text = ANY (ARRAY[('GREEN'::character varying)::text, ('AMBER'::character varying)::text, ('RED'::character varying)::text])))
);


--
-- Name: kri_measurements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.kri_measurements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: kri_measurements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.kri_measurements_id_seq OWNED BY public.kri_measurements.id;


--
-- Name: kris; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kris (
    id integer NOT NULL,
    risk_id integer,
    kri_name character varying(255) NOT NULL,
    kri_description text,
    unit_of_measure character varying(50),
    measurement_frequency character varying(20) DEFAULT 'MONTHLY'::character varying NOT NULL,
    target_value numeric(15,2),
    warning_threshold numeric(15,2),
    breach_threshold numeric(15,2),
    direction character varying(10) DEFAULT 'UPPER'::character varying NOT NULL,
    owner_id integer,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT kris_direction_check CHECK (((direction)::text = ANY (ARRAY[('UPPER'::character varying)::text, ('LOWER'::character varying)::text]))),
    CONSTRAINT kris_measurement_frequency_check CHECK (((measurement_frequency)::text = ANY (ARRAY[('DAILY'::character varying)::text, ('WEEKLY'::character varying)::text, ('MONTHLY'::character varying)::text, ('QUARTERLY'::character varying)::text])))
);


--
-- Name: kris_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.kris_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: kris_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.kris_id_seq OWNED BY public.kris.id;


--
-- Name: kyc_beneficial_owners; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kyc_beneficial_owners (
    id integer NOT NULL,
    subject character varying(30) NOT NULL,
    subject_id integer NOT NULL,
    full_name character varying(255) NOT NULL,
    nationality character varying(100),
    ownership_pct numeric(6,2),
    control_type character varying(30) DEFAULT 'ownership'::character varying NOT NULL,
    is_pep boolean DEFAULT false NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT kyc_beneficial_owners_control_type_check CHECK (((control_type)::text = ANY ((ARRAY['ownership'::character varying, 'control'::character varying, 'senior_manager'::character varying])::text[])))
);


--
-- Name: kyc_beneficial_owners_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.kyc_beneficial_owners_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: kyc_beneficial_owners_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.kyc_beneficial_owners_id_seq OWNED BY public.kyc_beneficial_owners.id;


--
-- Name: kyc_bo_declarations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kyc_bo_declarations (
    id integer NOT NULL,
    subject character varying(30) NOT NULL,
    subject_id integer NOT NULL,
    declaration_type character varying(10) NOT NULL,
    bo_name character varying(255),
    signed_on date NOT NULL,
    recorded_by integer,
    recorded_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT kyc_bo_declarations_declaration_type_check CHECK (((declaration_type)::text = ANY ((ARRAY['self'::character varying, 'other'::character varying])::text[])))
);


--
-- Name: kyc_bo_declarations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.kyc_bo_declarations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: kyc_bo_declarations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.kyc_bo_declarations_id_seq OWNED BY public.kyc_bo_declarations.id;


--
-- Name: kyc_fields; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kyc_fields (
    field_key character varying(60) NOT NULL,
    subject character varying(30) NOT NULL,
    label_en character varying(200) NOT NULL,
    label_ar character varying(200),
    source character varying(10) DEFAULT 'column'::character varying NOT NULL,
    column_names text[] DEFAULT '{}'::text[] NOT NULL,
    applies_to character varying(12) DEFAULT 'all'::character varying NOT NULL,
    is_required boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 100 NOT NULL,
    pack_code character varying(40),
    CONSTRAINT kyc_fields_applies_to_check CHECK (((applies_to)::text = ANY ((ARRAY['individual'::character varying, 'entity'::character varying, 'all'::character varying])::text[]))),
    CONSTRAINT kyc_fields_source_check CHECK (((source)::text = ANY ((ARRAY['column'::character varying, 'profile'::character varying])::text[])))
);


--
-- Name: kyc_onboarding; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kyc_onboarding (
    subject character varying(30) NOT NULL,
    subject_id integer NOT NULL,
    status character varying(12) DEFAULT 'pending'::character varying NOT NULL,
    edd_checklist jsonb DEFAULT '[]'::jsonb NOT NULL,
    edd_completed boolean DEFAULT false NOT NULL,
    senior_approved_by integer,
    senior_approved_at timestamp without time zone,
    approved_by integer,
    approved_at timestamp without time zone,
    note text,
    CONSTRAINT kyc_onboarding_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[])))
);


--
-- Name: kyc_profile_values; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kyc_profile_values (
    subject character varying(30) NOT NULL,
    subject_id integer NOT NULL,
    field_key character varying(60) NOT NULL,
    value text,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: kyc_risk_bands; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kyc_risk_bands (
    band character varying(10) NOT NULL,
    min_score numeric(6,2) NOT NULL,
    refresh_param_key character varying(120),
    label_en character varying(40),
    label_ar character varying(40),
    CONSTRAINT kyc_risk_bands_band_check CHECK (((band)::text = ANY ((ARRAY['low'::character varying, 'medium'::character varying, 'high'::character varying])::text[])))
);


--
-- Name: kyc_risk_factors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kyc_risk_factors (
    id integer NOT NULL,
    factor_key character varying(60) NOT NULL,
    category character varying(20) NOT NULL,
    label_en character varying(200) NOT NULL,
    label_ar character varying(200),
    field_key character varying(60) NOT NULL,
    weight numeric(6,2) DEFAULT 1 NOT NULL,
    scoring jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    pack_code character varying(40),
    CONSTRAINT kyc_risk_factors_category_check CHECK (((category)::text = ANY ((ARRAY['customer'::character varying, 'geography'::character varying, 'product'::character varying, 'channel'::character varying, 'pep'::character varying, 'behaviour'::character varying])::text[])))
);


--
-- Name: kyc_risk_factors_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.kyc_risk_factors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: kyc_risk_factors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.kyc_risk_factors_id_seq OWNED BY public.kyc_risk_factors.id;


--
-- Name: kyc_risk_ratings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kyc_risk_ratings (
    id integer NOT NULL,
    subject character varying(30) NOT NULL,
    subject_id integer NOT NULL,
    score numeric(6,2) NOT NULL,
    band character varying(10) NOT NULL,
    factors jsonb DEFAULT '[]'::jsonb NOT NULL,
    trigger character varying(30) DEFAULT 'manual'::character varying NOT NULL,
    rated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    rated_by integer,
    next_review_date date,
    is_current boolean DEFAULT true NOT NULL
);


--
-- Name: kyc_risk_ratings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.kyc_risk_ratings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: kyc_risk_ratings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.kyc_risk_ratings_id_seq OWNED BY public.kyc_risk_ratings.id;


--
-- Name: ln_clients; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_clients (
    id integer NOT NULL,
    client_ref character varying(60) NOT NULL,
    party_id integer,
    client_type character varying(12) DEFAULT 'individual'::character varying NOT NULL,
    full_name character varying(255) NOT NULL,
    national_id_hash text,
    gender character varying(10),
    phone character varying(40),
    address text,
    governorate character varying(80),
    business_activity character varying(200),
    monthly_revenue numeric(16,2),
    project_size numeric(16,2),
    org_unit_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ln_clients_client_type_check CHECK (((client_type)::text = ANY ((ARRAY['individual'::character varying, 'entity'::character varying])::text[])))
);


--
-- Name: ln_clients_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_clients_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_clients_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_clients_id_seq OWNED BY public.ln_clients.id;


--
-- Name: ln_contracts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_contracts (
    id integer NOT NULL,
    loan_id integer NOT NULL,
    contract_no character varying(60),
    contract_date date,
    signed_by_lender boolean DEFAULT false NOT NULL,
    lender_signed_at date,
    signed_by_client boolean DEFAULT false NOT NULL,
    client_signed_at date,
    penalty_clause_rate_pct numeric(8,4),
    penalty_clause_cap_pct numeric(8,4)
);


--
-- Name: ln_contracts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_contracts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_contracts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_contracts_id_seq OWNED BY public.ln_contracts.id;


--
-- Name: ln_credit_studies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_credit_studies (
    id integer NOT NULL,
    loan_id integer NOT NULL,
    study_date date,
    officer_code character varying(40),
    monthly_revenue numeric(16,2),
    monthly_costs_total numeric(16,2),
    cost_lines jsonb DEFAULT '[]'::jsonb NOT NULL,
    household_expenses numeric(16,2),
    other_debt_service numeric(16,2),
    net_income numeric(16,2),
    dsr_pct numeric(8,2)
);


--
-- Name: ln_credit_studies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_credit_studies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_credit_studies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_credit_studies_id_seq OWNED BY public.ln_credit_studies.id;


--
-- Name: ln_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_documents (
    id integer NOT NULL,
    loan_id integer,
    client_id integer,
    doc_type character varying(40) NOT NULL,
    received_date date,
    reference_no character varying(120),
    notes text,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: ln_documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_documents_id_seq OWNED BY public.ln_documents.id;


--
-- Name: ln_early_repayments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_early_repayments (
    id integer NOT NULL,
    loan_id integer NOT NULL,
    request_date date DEFAULT CURRENT_DATE NOT NULL,
    settlement_amount numeric(16,2),
    prepayment_fee numeric(16,2) DEFAULT 0 NOT NULL,
    original_remaining_cost numeric(16,2),
    new_total_cost numeric(16,2),
    disclosure_text_en text,
    disclosure_text_ar text,
    disclosed_at timestamp without time zone,
    consent_signed boolean DEFAULT false NOT NULL,
    consent_date date,
    cost_acknowledged boolean DEFAULT false NOT NULL,
    status character varying(12) DEFAULT 'requested'::character varying NOT NULL,
    executed_at timestamp without time zone,
    executed_by integer,
    source character varying(10) DEFAULT 'manual'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ln_early_repayments_status_check CHECK (((status)::text = ANY ((ARRAY['requested'::character varying, 'disclosed'::character varying, 'consented'::character varying, 'executed'::character varying, 'cancelled'::character varying])::text[])))
);


--
-- Name: ln_early_repayments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_early_repayments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_early_repayments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_early_repayments_id_seq OWNED BY public.ln_early_repayments.id;


--
-- Name: ln_exceptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_exceptions (
    id integer NOT NULL,
    loan_id integer NOT NULL,
    exception_type character varying(20) NOT NULL,
    reason text NOT NULL,
    status character varying(12) DEFAULT 'pending'::character varying NOT NULL,
    requested_by integer,
    requested_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    decided_by integer,
    decided_at timestamp without time zone,
    decision_comment text,
    CONSTRAINT ln_exceptions_exception_type_check CHECK (((exception_type)::text = ANY ((ARRAY['eligibility'::character varying, 'file_incomplete'::character varying])::text[]))),
    CONSTRAINT ln_exceptions_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[])))
);


--
-- Name: ln_exceptions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_exceptions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_exceptions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_exceptions_id_seq OWNED BY public.ln_exceptions.id;


--
-- Name: ln_import_batches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_import_batches (
    id integer NOT NULL,
    kind character varying(30) NOT NULL,
    source character varying(10) DEFAULT 'file'::character varying NOT NULL,
    filename character varying(255),
    rows_total integer DEFAULT 0 NOT NULL,
    rows_ok integer DEFAULT 0 NOT NULL,
    rows_failed integer DEFAULT 0 NOT NULL,
    errors jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ln_import_batches_source_check CHECK (((source)::text = ANY ((ARRAY['file'::character varying, 'api'::character varying, 'manual'::character varying, 'demo'::character varying])::text[])))
);


--
-- Name: ln_import_batches_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_import_batches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_import_batches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_import_batches_id_seq OWNED BY public.ln_import_batches.id;


--
-- Name: ln_instalments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_instalments (
    id integer NOT NULL,
    loan_id integer NOT NULL,
    seq integer NOT NULL,
    due_date date NOT NULL,
    principal_due numeric(16,2) DEFAULT 0 NOT NULL,
    interest_due numeric(16,2) DEFAULT 0 NOT NULL,
    fees_due numeric(16,2) DEFAULT 0 NOT NULL,
    paid_amount numeric(16,2) DEFAULT 0 NOT NULL,
    paid_date date,
    penalty_charged numeric(16,2) DEFAULT 0 NOT NULL,
    status character varying(12) DEFAULT 'due'::character varying NOT NULL,
    CONSTRAINT ln_instalments_status_check CHECK (((status)::text = ANY ((ARRAY['due'::character varying, 'partial'::character varying, 'paid'::character varying, 'waived'::character varying])::text[])))
);


--
-- Name: ln_instalments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_instalments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_instalments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_instalments_id_seq OWNED BY public.ln_instalments.id;


--
-- Name: ln_loans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_loans (
    id integer NOT NULL,
    loan_ref character varying(60) NOT NULL,
    client_id integer NOT NULL,
    product_code character varying(40),
    amount numeric(16,2) NOT NULL,
    tenor_months integer,
    interest_rate_pct numeric(8,4),
    apr_pct numeric(8,4),
    admin_fee_amount numeric(16,2) DEFAULT 0 NOT NULL,
    other_fees_amount numeric(16,2) DEFAULT 0 NOT NULL,
    branch_code character varying(40),
    officer_code character varying(40),
    status character varying(20) DEFAULT 'application'::character varying NOT NULL,
    application_date date,
    approval_date date,
    disbursement_date date,
    maturity_date date,
    outstanding_principal numeric(16,2) DEFAULT 0 NOT NULL,
    days_past_due integer DEFAULT 0 NOT NULL,
    gps_lat numeric(10,7),
    gps_lng numeric(10,7),
    purpose text,
    file_complete boolean DEFAULT false NOT NULL,
    file_gaps jsonb DEFAULT '[]'::jsonb NOT NULL,
    source character varying(10) DEFAULT 'manual'::character varying NOT NULL,
    import_batch_id integer,
    org_unit_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ln_loans_source_check CHECK (((source)::text = ANY ((ARRAY['file'::character varying, 'api'::character varying, 'manual'::character varying, 'demo'::character varying])::text[]))),
    CONSTRAINT ln_loans_status_check CHECK (((status)::text = ANY ((ARRAY['application'::character varying, 'approved'::character varying, 'disbursed'::character varying, 'closed'::character varying, 'written_off'::character varying, 'rejected'::character varying])::text[])))
);


--
-- Name: ln_loans_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_loans_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_loans_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_loans_id_seq OWNED BY public.ln_loans.id;


--
-- Name: ln_par_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_par_snapshots (
    id integer NOT NULL,
    period date NOT NULL,
    dimension character varying(12) NOT NULL,
    dim_value character varying(60) NOT NULL,
    loans integer NOT NULL,
    outstanding numeric(18,2) NOT NULL,
    par30 numeric(8,2) NOT NULL,
    par60 numeric(8,2) NOT NULL,
    par90 numeric(8,2) NOT NULL,
    par120 numeric(8,2) NOT NULL,
    computed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ln_par_snapshots_dimension_check CHECK (((dimension)::text = ANY ((ARRAY['company'::character varying, 'branch'::character varying, 'officer'::character varying, 'product'::character varying])::text[])))
);


--
-- Name: ln_par_snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_par_snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_par_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_par_snapshots_id_seq OWNED BY public.ln_par_snapshots.id;


--
-- Name: ln_products; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_products (
    id integer NOT NULL,
    code character varying(40) NOT NULL,
    name_en character varying(200) NOT NULL,
    name_ar character varying(200),
    licence_type character varying(40) DEFAULT 'all'::character varying NOT NULL,
    required_docs text[] DEFAULT '{national_id}'::text[] NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: ln_products_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_products_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_products_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_products_id_seq OWNED BY public.ln_products.id;


--
-- Name: ln_qa_flags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_qa_flags (
    id integer NOT NULL,
    loan_id integer NOT NULL,
    flag_type character varying(30) NOT NULL,
    detail text,
    status character varying(12) DEFAULT 'open'::character varying NOT NULL,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    review_note text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ln_qa_flags_status_check CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'cleared'::character varying, 'confirmed'::character varying])::text[])))
);


--
-- Name: ln_qa_flags_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_qa_flags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_qa_flags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_qa_flags_id_seq OWNED BY public.ln_qa_flags.id;


--
-- Name: ln_reschedulings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_reschedulings (
    id integer NOT NULL,
    loan_id integer NOT NULL,
    resched_date date NOT NULL,
    fee_amount numeric(16,2) DEFAULT 0 NOT NULL,
    old_tenor integer,
    new_tenor integer,
    reason text
);


--
-- Name: ln_reschedulings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_reschedulings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_reschedulings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_reschedulings_id_seq OWNED BY public.ln_reschedulings.id;


--
-- Name: ln_transfers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_transfers (
    id integer NOT NULL,
    loan_id integer NOT NULL,
    transfer_date date NOT NULL,
    instalments_moved integer,
    fee_amount numeric(16,2) DEFAULT 0 NOT NULL
);


--
-- Name: ln_transfers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_transfers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_transfers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_transfers_id_seq OWNED BY public.ln_transfers.id;


--
-- Name: ln_visits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ln_visits (
    id integer NOT NULL,
    loan_id integer NOT NULL,
    planned_date date,
    visit_date date,
    officer_code character varying(40),
    outcome character varying(40),
    notes text
);


--
-- Name: ln_visits_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ln_visits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ln_visits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ln_visits_id_seq OWNED BY public.ln_visits.id;


--
-- Name: meeting_action_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.meeting_action_items (
    id integer NOT NULL,
    meeting_id integer,
    agenda_item_id integer,
    action_number integer,
    action_description text,
    action_category text,
    responsible_person text,
    responsible_department text,
    responsible_committee_id integer,
    due_date text,
    priority text,
    status text,
    completion_date text,
    completion_notes text
);


--
-- Name: meeting_action_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.meeting_action_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: meeting_action_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.meeting_action_items_id_seq OWNED BY public.meeting_action_items.id;


--
-- Name: meeting_agenda_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.meeting_agenda_items (
    id integer NOT NULL,
    meeting_id integer,
    item_number integer,
    item_title text,
    item_description text,
    item_type text,
    presenter_name text,
    presenter_member_id integer,
    estimated_duration integer,
    background_paper_path text,
    presentation_path text,
    display_order integer
);


--
-- Name: meeting_agenda_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.meeting_agenda_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: meeting_agenda_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.meeting_agenda_items_id_seq OWNED BY public.meeting_agenda_items.id;


--
-- Name: meeting_attendance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.meeting_attendance (
    id integer NOT NULL,
    meeting_id integer,
    member_id integer,
    attendance_status text,
    attended integer,
    apology_received integer,
    apology_date text,
    apology_reason text,
    absence_authorized integer,
    proxy_name text,
    proxy_authorization text,
    proxy_valid integer,
    arrival_time text,
    departure_time text,
    duration_present integer,
    spoke_in_meeting integer,
    contributions_count integer,
    questions_asked integer,
    attended_remotely integer,
    remote_platform text,
    technical_issues integer,
    attendance_notes text,
    recorded_at text,
    recorded_by integer
);


--
-- Name: meeting_attendance_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.meeting_attendance_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: meeting_attendance_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.meeting_attendance_id_seq OWNED BY public.meeting_attendance.id;


--
-- Name: merchant_kyc_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.merchant_kyc_documents (
    id integer NOT NULL,
    merchant_id integer,
    doc_type text,
    original_filename text,
    stored_filename text,
    file_size integer,
    uploaded_at text,
    uploaded_by text
);


--
-- Name: merchant_kyc_documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.merchant_kyc_documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: merchant_kyc_documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.merchant_kyc_documents_id_seq OWNED BY public.merchant_kyc_documents.id;


--
-- Name: merchants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.merchants (
    id integer NOT NULL,
    merchant_name text,
    trade_name text,
    cr_number text,
    tax_id text,
    business_type text,
    industry text,
    website text,
    contact_person text,
    contact_email text,
    contact_phone text,
    address text,
    city text,
    country text,
    ubo_name text,
    ubo_nationality text,
    ubo_id_type text,
    ubo_id_number text,
    ubo_dob text,
    ownership_percentage double precision,
    bank_name text,
    bank_account_number text,
    iban text,
    kyc_status text,
    kyc_token text,
    kyc_sent_at text,
    kyc_submitted_at text,
    kyc_reviewed_by integer,
    kyc_reviewed_at text,
    kyc_rejection_reason text,
    risk_level text,
    sanctions_checked integer,
    pep_checked integer,
    risk_notes text,
    created_at text,
    created_by integer,
    updated_at text,
    updated_by integer,
    internal_reference_number text,
    internal_account_number text,
    screening_status text,
    last_screening_date text,
    last_screened_by integer,
    risk_rating text,
    pep_status integer,
    screening_notes text,
    onboarding_status text,
    gps_latitude double precision,
    gps_longitude double precision,
    gps_accuracy double precision,
    gps_captured_at text,
    gps_address text,
    merchant_type text DEFAULT 'CARD_ACCEPTANCE'::text,
    pos_wallet_limit numeric,
    kyb_link_sent_via text
);


--
-- Name: merchants_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.merchants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: merchants_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.merchants_id_seq OWNED BY public.merchants.id;


--
-- Name: mfa_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mfa_audit (
    id integer NOT NULL,
    user_id integer NOT NULL,
    action text NOT NULL,
    performed_by integer,
    reason text,
    ip_address text,
    performed_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: mfa_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.mfa_audit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mfa_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.mfa_audit_id_seq OWNED BY public.mfa_audit.id;


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id integer NOT NULL,
    user_id integer,
    title text,
    message text,
    type text,
    is_read integer,
    link text,
    created_at text
);


--
-- Name: notifications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.notifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.notifications_id_seq OWNED BY public.notifications.id;


--
-- Name: numbering_sequences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.numbering_sequences (
    id integer NOT NULL,
    sequence_key text NOT NULL,
    prefix text NOT NULL,
    padding integer DEFAULT 4 NOT NULL,
    description text,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: numbering_sequences_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.numbering_sequences_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: numbering_sequences_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.numbering_sequences_id_seq OWNED BY public.numbering_sequences.id;


--
-- Name: ongoing_screening_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ongoing_screening_config (
    id integer NOT NULL,
    scope_name text NOT NULL,
    risk_band text,
    frequency text,
    is_active boolean DEFAULT true NOT NULL,
    rescreen_on_list_update boolean DEFAULT true NOT NULL,
    alert_on_new_entity boolean DEFAULT true NOT NULL,
    alert_on_entity_change boolean DEFAULT true NOT NULL,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    is_configured boolean DEFAULT false NOT NULL,
    configured_by integer,
    configured_at timestamp without time zone,
    rationale text,
    CONSTRAINT osc_freq_ck CHECK ((frequency = ANY (ARRAY['daily'::text, 'weekly'::text, 'monthly'::text, 'quarterly'::text, 'yearly'::text, 'manual'::text])))
);


--
-- Name: ongoing_screening_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ongoing_screening_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ongoing_screening_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ongoing_screening_config_id_seq OWNED BY public.ongoing_screening_config.id;


--
-- Name: ongoing_screening_findings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ongoing_screening_findings (
    id integer NOT NULL,
    run_id integer NOT NULL,
    whitelist_id integer,
    screened_name text NOT NULL,
    finding_type text NOT NULL,
    entity_id integer,
    entity_name text,
    entity_source text,
    match_score double precision,
    old_fingerprint text,
    new_fingerprint text,
    status text DEFAULT 'open'::text NOT NULL,
    alert_id integer,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: ongoing_screening_findings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ongoing_screening_findings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ongoing_screening_findings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ongoing_screening_findings_id_seq OWNED BY public.ongoing_screening_findings.id;


--
-- Name: ongoing_screening_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ongoing_screening_runs (
    id integer NOT NULL,
    run_type text DEFAULT 'scheduled'::text NOT NULL,
    started_at timestamp without time zone DEFAULT now() NOT NULL,
    finished_at timestamp without time zone,
    names_screened integer DEFAULT 0 NOT NULL,
    unchanged integer DEFAULT 0 NOT NULL,
    new_matches integer DEFAULT 0 NOT NULL,
    changed_listings integer DEFAULT 0 NOT NULL,
    delisted integer DEFAULT 0 NOT NULL,
    errors integer DEFAULT 0 NOT NULL,
    triggered_by integer,
    notes text
);


--
-- Name: ongoing_screening_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ongoing_screening_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ongoing_screening_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ongoing_screening_runs_id_seq OWNED BY public.ongoing_screening_runs.id;


--
-- Name: org_unit_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.org_unit_types (
    id integer NOT NULL,
    code text NOT NULL,
    name_en text NOT NULL,
    name_ar text,
    icon text DEFAULT 'bi bi-diagram-3'::text,
    rank_hint integer DEFAULT 50 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: org_unit_types_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.org_unit_types_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: org_unit_types_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.org_unit_types_id_seq OWNED BY public.org_unit_types.id;


--
-- Name: org_units; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.org_units (
    id integer NOT NULL,
    parent_id integer,
    unit_type_id integer NOT NULL,
    code text NOT NULL,
    name_en text NOT NULL,
    name_ar text,
    path text,
    depth integer DEFAULT 0 NOT NULL,
    is_legal_entity boolean DEFAULT false NOT NULL,
    country text,
    registration_no text,
    head_user_id integer,
    legacy_department_id integer,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: org_units_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.org_units_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: org_units_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.org_units_id_seq OWNED BY public.org_units.id;


--
-- Name: parties; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parties (
    id integer NOT NULL,
    party_type character varying(20) NOT NULL,
    full_name character varying(255) NOT NULL,
    full_name_arabic character varying(255),
    date_of_birth date,
    nationality character varying(100),
    id_type character varying(50),
    id_number_hash text,
    cr_number_hash text,
    email character varying(255),
    phone character varying(50),
    risk_rating character varying(20),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT parties_party_type_check CHECK (((party_type)::text = ANY (ARRAY[('INDIVIDUAL'::character varying)::text, ('ENTITY'::character varying)::text])))
);


--
-- Name: parties_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.parties_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: parties_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.parties_id_seq OWNED BY public.parties.id;


--
-- Name: party_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.party_links (
    id integer NOT NULL,
    party_id integer NOT NULL,
    source_module character varying(60) NOT NULL,
    source_table character varying(60) NOT NULL,
    source_record_id integer NOT NULL,
    link_role character varying(30) NOT NULL,
    linked_at timestamp without time zone DEFAULT now()
);


--
-- Name: party_links_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.party_links_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: party_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.party_links_id_seq OWNED BY public.party_links.id;


--
-- Name: pep_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pep_aliases (
    id integer NOT NULL,
    pep_id integer,
    alias_name character varying(255) NOT NULL,
    alias_language character varying(10),
    alias_type character varying(50),
    source character varying(100),
    source_url text,
    verified boolean DEFAULT false,
    added_at timestamp without time zone DEFAULT now()
);


--
-- Name: pep_aliases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pep_aliases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pep_aliases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pep_aliases_id_seq OWNED BY public.pep_aliases.id;


--
-- Name: pep_corporate_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pep_corporate_links (
    id integer NOT NULL,
    pep_id integer,
    company_name character varying(255) NOT NULL,
    company_jurisdiction character varying(10),
    company_number character varying(100),
    role character varying(100),
    ownership_percentage double precision,
    start_date date,
    end_date date,
    is_current boolean GENERATED ALWAYS AS ((end_date IS NULL)) STORED,
    source character varying(100) DEFAULT 'OpenCorporates'::character varying,
    source_url text,
    opencorporates_url text,
    added_at timestamp without time zone DEFAULT now(),
    last_verified timestamp without time zone
);


--
-- Name: pep_corporate_links_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pep_corporate_links_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pep_corporate_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pep_corporate_links_id_seq OWNED BY public.pep_corporate_links.id;


--
-- Name: pep_database; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pep_database (
    id integer NOT NULL,
    full_name text,
    alternative_names text,
    date_of_birth text,
    nationality text,
    "position" text,
    organization text,
    country text,
    pep_category text,
    risk_level text,
    source_list text,
    last_updated text,
    is_active integer,
    created_at text,
    updated_at text
);


--
-- Name: pep_database_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pep_database_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pep_database_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pep_database_id_seq OWNED BY public.pep_database.id;


--
-- Name: pep_duplicate_candidates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pep_duplicate_candidates (
    id integer NOT NULL,
    pep_id_1 integer,
    pep_id_2 integer,
    match_score double precision NOT NULL,
    match_reason character varying(255),
    status character varying(50) DEFAULT 'pending'::character varying,
    reviewed_by character varying(100),
    reviewed_at timestamp without time zone,
    merged_into integer,
    detected_at timestamp without time zone DEFAULT now()
);


--
-- Name: pep_duplicate_candidates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pep_duplicate_candidates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pep_duplicate_candidates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pep_duplicate_candidates_id_seq OWNED BY public.pep_duplicate_candidates.id;


--
-- Name: pep_master; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pep_master (
    id integer NOT NULL,
    canonical_name_en character varying(255) NOT NULL,
    canonical_name_ar character varying(255),
    date_of_birth date,
    place_of_birth character varying(255),
    nationality character varying(10) DEFAULT 'EG'::character varying,
    gender character varying(10),
    is_active boolean DEFAULT true,
    pep_level character varying(50),
    pep_category character varying(50),
    risk_level character varying(20),
    first_seen timestamp without time zone DEFAULT now(),
    last_updated timestamp without time zone DEFAULT now(),
    last_verified timestamp without time zone,
    source_count integer DEFAULT 0,
    confidence_score double precision DEFAULT 0.0,
    search_vector tsvector
);


--
-- Name: pep_master_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pep_master_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pep_master_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pep_master_id_seq OWNED BY public.pep_master.id;


--
-- Name: pep_matches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pep_matches (
    id integer NOT NULL,
    screening_id integer,
    pep_name text,
    pep_position text,
    pep_country text,
    pep_category text,
    match_score numeric,
    match_details text,
    investigation_status text,
    investigated_by integer,
    investigation_date text,
    investigation_notes text,
    is_false_positive integer,
    false_positive_reason text,
    senior_approval_required integer,
    approved_by integer,
    approval_date text,
    approval_notes text
);


--
-- Name: pep_matches_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pep_matches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pep_matches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pep_matches_id_seq OWNED BY public.pep_matches.id;


--
-- Name: pep_positions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pep_positions (
    id integer NOT NULL,
    pep_id integer,
    position_title_en character varying(255),
    position_title_ar character varying(255),
    organization_en character varying(255),
    organization_ar character varying(255),
    start_date date,
    end_date date,
    is_current boolean GENERATED ALWAYS AS ((end_date IS NULL)) STORED,
    position_type character varying(50),
    ministry character varying(100),
    political_party character varying(100),
    source character varying(100),
    source_url text,
    verified boolean DEFAULT false,
    confidence double precision DEFAULT 0.5,
    added_at timestamp without time zone DEFAULT now(),
    last_updated timestamp without time zone DEFAULT now()
);


--
-- Name: pep_positions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pep_positions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pep_positions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pep_positions_id_seq OWNED BY public.pep_positions.id;


--
-- Name: pep_screenings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pep_screenings (
    id integer NOT NULL,
    screening_reference text,
    entity_type text,
    entity_id integer,
    entity_name text,
    date_of_birth text,
    nationality text,
    screening_date text,
    screened_by integer,
    screening_source text,
    matches_found integer,
    status text
);


--
-- Name: pep_screenings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pep_screenings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pep_screenings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pep_screenings_id_seq OWNED BY public.pep_screenings.id;


--
-- Name: pep_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pep_sources (
    id integer NOT NULL,
    pep_id integer,
    source_name character varying(100) NOT NULL,
    source_type character varying(50),
    source_url text,
    source_record_id character varying(255),
    raw_data jsonb,
    first_retrieved timestamp without time zone DEFAULT now(),
    last_updated timestamp without time zone DEFAULT now(),
    last_verified timestamp without time zone,
    is_active boolean DEFAULT true,
    confidence double precision DEFAULT 0.5
);


--
-- Name: pep_sources_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pep_sources_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pep_sources_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pep_sources_id_seq OWNED BY public.pep_sources.id;


--
-- Name: pep_update_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pep_update_logs (
    id integer NOT NULL,
    source_name character varying(100) NOT NULL,
    update_type character varying(50),
    records_fetched integer DEFAULT 0,
    records_added integer DEFAULT 0,
    records_updated integer DEFAULT 0,
    records_merged integer DEFAULT 0,
    records_failed integer DEFAULT 0,
    status character varying(50),
    error_message text,
    started_at timestamp without time zone DEFAULT now(),
    completed_at timestamp without time zone,
    duration_seconds integer GENERATED ALWAYS AS (EXTRACT(epoch FROM (completed_at - started_at))) STORED
);


--
-- Name: pep_update_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pep_update_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pep_update_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pep_update_logs_id_seq OWNED BY public.pep_update_logs.id;


--
-- Name: phishing_campaigns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.phishing_campaigns (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    sender_display character varying(255) DEFAULT 'Carrefour Egypt'::character varying NOT NULL,
    email_subject character varying(500) NOT NULL,
    offer_title character varying(500),
    offer_body text,
    expiry_text character varying(255),
    cta_text character varying(255),
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    sent_at timestamp without time zone,
    custom_html text,
    scenario_type character varying(50),
    company_name character varying(255),
    logo_url character varying(500),
    custom_landing_html text
);


--
-- Name: phishing_campaigns_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.phishing_campaigns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: phishing_campaigns_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.phishing_campaigns_id_seq OWNED BY public.phishing_campaigns.id;


--
-- Name: phishing_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.phishing_events (
    id integer NOT NULL,
    campaign_id integer NOT NULL,
    recipient_id integer NOT NULL,
    event_type character varying(20) NOT NULL,
    ip_address character varying(100),
    user_agent character varying(500),
    extra_data text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: phishing_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.phishing_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: phishing_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.phishing_events_id_seq OWNED BY public.phishing_events.id;


--
-- Name: phishing_recipients; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.phishing_recipients (
    id integer NOT NULL,
    campaign_id integer NOT NULL,
    recipient_name character varying(255) NOT NULL,
    recipient_email character varying(255) NOT NULL,
    token character varying(64) NOT NULL,
    sent_at timestamp without time zone,
    clicked_at timestamp without time zone,
    submitted_at timestamp without time zone,
    submitted_email character varying(255),
    submitted_card character varying(255),
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: phishing_recipients_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.phishing_recipients_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: phishing_recipients_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.phishing_recipients_id_seq OWNED BY public.phishing_recipients.id;


--
-- Name: policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policies (
    id integer NOT NULL,
    policy_number text,
    policy_name text,
    category_id integer,
    version text,
    effective_date text,
    review_date text,
    next_review_date text,
    owner_id integer,
    owner_function text,
    description text,
    content text,
    attachment_path text,
    status text,
    regulatory_reference text,
    cbe_requirement text,
    is_public integer,
    issuing_date text,
    approval_cycle text,
    approved_by integer,
    approval_date text,
    created_by integer,
    created_at text,
    updated_by integer,
    updated_at text,
    is_mandatory integer,
    department_id integer,
    is_internal integer,
    document_type_id integer,
    org_unit_id integer,
    requires_board_approval boolean DEFAULT false NOT NULL
);


--
-- Name: policies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.policies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: policies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.policies_id_seq OWNED BY public.policies.id;


--
-- Name: policy_acknowledgments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policy_acknowledgments (
    id integer NOT NULL,
    policy_id integer,
    employee_id integer,
    acknowledgment_date text,
    ip_address text,
    digital_signature text
);


--
-- Name: policy_acknowledgments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.policy_acknowledgments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: policy_acknowledgments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.policy_acknowledgments_id_seq OWNED BY public.policy_acknowledgments.id;


--
-- Name: policy_applicability; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policy_applicability (
    id integer NOT NULL,
    policy_id integer NOT NULL,
    org_unit_id integer,
    include_descendants boolean DEFAULT true NOT NULL,
    is_exclusion boolean DEFAULT false NOT NULL,
    match_code text,
    match_type_id integer,
    root_unit_id integer,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: policy_applicability_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.policy_applicability_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: policy_applicability_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.policy_applicability_id_seq OWNED BY public.policy_applicability.id;


--
-- Name: policy_attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policy_attachments (
    id integer NOT NULL,
    policy_id integer,
    filename text,
    file_path text,
    file_size integer,
    uploaded_by integer,
    uploaded_at text
);


--
-- Name: policy_attachments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.policy_attachments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: policy_attachments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.policy_attachments_id_seq OWNED BY public.policy_attachments.id;


--
-- Name: policy_board_approvals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policy_board_approvals (
    id integer NOT NULL,
    policy_id integer NOT NULL,
    policy_version character varying(40),
    approved_on date NOT NULL,
    board_ref character varying(200),
    notes text,
    recorded_by integer,
    recorded_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: policy_board_approvals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.policy_board_approvals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: policy_board_approvals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.policy_board_approvals_id_seq OWNED BY public.policy_board_approvals.id;


--
-- Name: policy_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policy_categories (
    id integer NOT NULL,
    name_en text,
    name_ar text,
    description_en text,
    description_ar text,
    icon text,
    created_at text,
    department_id integer
);


--
-- Name: policy_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.policy_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: policy_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.policy_categories_id_seq OWNED BY public.policy_categories.id;


--
-- Name: policy_review_workflow; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policy_review_workflow (
    id integer NOT NULL,
    policy_id integer,
    reviewer_id integer,
    stage_name text,
    status text,
    comments text,
    review_date text,
    created_at text
);


--
-- Name: policy_review_workflow_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.policy_review_workflow_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: policy_review_workflow_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.policy_review_workflow_id_seq OWNED BY public.policy_review_workflow.id;


--
-- Name: policy_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policy_versions (
    id integer NOT NULL,
    policy_id integer,
    version text,
    change_summary text,
    content text,
    effective_date text,
    created_by integer,
    created_at text
);


--
-- Name: policy_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.policy_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: policy_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.policy_versions_id_seq OWNED BY public.policy_versions.id;


--
-- Name: pr_branch_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_branch_roles (
    code character varying(40) NOT NULL,
    name_en character varying(200) NOT NULL,
    name_ar character varying(200),
    min_count integer,
    param_key character varying(120),
    is_active boolean DEFAULT true NOT NULL,
    pack_code character varying(40)
);


--
-- Name: pr_branch_staffing; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_branch_staffing (
    branch_id integer NOT NULL,
    role_code character varying(40) NOT NULL,
    headcount integer DEFAULT 0 NOT NULL,
    as_of date DEFAULT CURRENT_DATE NOT NULL,
    CONSTRAINT pr_branch_staffing_headcount_check CHECK ((headcount >= 0))
);


--
-- Name: pr_branches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_branches (
    id integer NOT NULL,
    code character varying(40) NOT NULL,
    name_en character varying(200) NOT NULL,
    name_ar character varying(200),
    address text,
    org_unit_id integer,
    status character varying(10) DEFAULT 'planned'::character varying NOT NULL,
    opened_on date,
    manager_name character varying(255),
    manager_user_id integer,
    manager_no_objection character varying(12) DEFAULT 'pending'::character varying NOT NULL,
    manager_no_objection_ref character varying(200),
    manager_no_objection_on date,
    manager_vacant_since date,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pr_branches_manager_no_objection_check CHECK (((manager_no_objection)::text = ANY ((ARRAY['not_required'::character varying, 'pending'::character varying, 'granted'::character varying, 'refused'::character varying])::text[]))),
    CONSTRAINT pr_branches_status_check CHECK (((status)::text = ANY ((ARRAY['planned'::character varying, 'active'::character varying, 'closed'::character varying])::text[])))
);


--
-- Name: pr_branches_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pr_branches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pr_branches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pr_branches_id_seq OWNED BY public.pr_branches.id;


--
-- Name: pr_capital_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_capital_events (
    id integer NOT NULL,
    capital_type character varying(12) NOT NULL,
    amount numeric(18,2) NOT NULL,
    currency character varying(3) DEFAULT 'EGP'::character varying NOT NULL,
    effective_date date NOT NULL,
    reference character varying(200),
    note text,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pr_capital_events_amount_check CHECK ((amount >= (0)::numeric)),
    CONSTRAINT pr_capital_events_capital_type_check CHECK (((capital_type)::text = ANY ((ARRAY['authorised'::character varying, 'issued'::character varying, 'paid_up'::character varying, 'registered'::character varying])::text[])))
);


--
-- Name: pr_capital_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pr_capital_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pr_capital_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pr_capital_events_id_seq OWNED BY public.pr_capital_events.id;


--
-- Name: pr_deadline_extensions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_deadline_extensions (
    id integer NOT NULL,
    deadline_id integer NOT NULL,
    extension_type character varying(10) DEFAULT 'special'::character varying NOT NULL,
    granted_on date NOT NULL,
    new_due_date date NOT NULL,
    letter_ref character varying(200),
    note text,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pr_deadline_extensions_extension_type_check CHECK (((extension_type)::text = ANY ((ARRAY['general'::character varying, 'special'::character varying])::text[])))
);


--
-- Name: pr_deadline_extensions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pr_deadline_extensions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pr_deadline_extensions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pr_deadline_extensions_id_seq OWNED BY public.pr_deadline_extensions.id;


--
-- Name: pr_deadlines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_deadlines (
    id integer NOT NULL,
    title character varying(255) NOT NULL,
    category character varying(30) DEFAULT 'other'::character varying NOT NULL,
    regulator_id integer,
    original_due_date date NOT NULL,
    due_date date NOT NULL,
    status character varying(10) DEFAULT 'open'::character varying NOT NULL,
    met_on date,
    owner_user_id integer,
    notified_thresholds integer[] DEFAULT '{}'::integer[] NOT NULL,
    board_escalated_at timestamp without time zone,
    finding_id integer,
    note text,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pr_deadlines_category_check CHECK (((category)::text = ANY ((ARRAY['capital_increase'::character varying, 'licence'::character varying, 'remediation'::character varying, 'submission'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT pr_deadlines_status_check CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'met'::character varying, 'missed'::character varying, 'cancelled'::character varying])::text[])))
);


--
-- Name: pr_deadlines_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pr_deadlines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pr_deadlines_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pr_deadlines_id_seq OWNED BY public.pr_deadlines.id;


--
-- Name: pr_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_documents (
    id integer NOT NULL,
    doc_type character varying(30) DEFAULT 'letter'::character varying NOT NULL,
    title character varying(255) NOT NULL,
    doc_date date,
    address_on_document text,
    source_module character varying(40),
    source_record_id integer,
    reviewed_ok boolean,
    review_note text,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pr_documents_doc_type_check CHECK (((doc_type)::text = ANY ((ARRAY['board_minutes'::character varying, 'letter'::character varying, 'contract'::character varying, 'form'::character varying, 'other'::character varying])::text[])))
);


--
-- Name: pr_documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pr_documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pr_documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pr_documents_id_seq OWNED BY public.pr_documents.id;


--
-- Name: pr_facilities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_facilities (
    id integer NOT NULL,
    reference character varying(60) NOT NULL,
    lender_name character varying(255) NOT NULL,
    party_id integer,
    facility_type character varying(20) DEFAULT 'loan'::character varying NOT NULL,
    currency character varying(3) DEFAULT 'EGP'::character varying NOT NULL,
    limit_amount numeric(18,2),
    balance numeric(18,2) DEFAULT 0 NOT NULL,
    interest_rate_pct numeric(8,4),
    start_date date,
    maturity_date date,
    status character varying(12) DEFAULT 'performing'::character varying NOT NULL,
    covenant_breach boolean DEFAULT false NOT NULL,
    last_confirmation_date date,
    confirmation_balance numeric(18,2),
    accrual_from date,
    accrued_booked numeric(18,2),
    booked_as_of date,
    rescheduled_on date,
    rescheduling_approval_ref character varying(200),
    board_escalated_on date,
    board_escalation_ref character varying(200),
    source character varying(10) DEFAULT 'manual'::character varying NOT NULL,
    note text,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pr_facilities_facility_type_check CHECK (((facility_type)::text = ANY ((ARRAY['loan'::character varying, 'overdraft'::character varying, 'bond'::character varying, 'securitisation'::character varying, 'related_party'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT pr_facilities_source_check CHECK (((source)::text = ANY ((ARRAY['manual'::character varying, 'import'::character varying, 'erp'::character varying])::text[]))),
    CONSTRAINT pr_facilities_status_check CHECK (((status)::text = ANY ((ARRAY['performing'::character varying, 'default'::character varying, 'rescheduled'::character varying, 'closed'::character varying])::text[])))
);


--
-- Name: pr_facilities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pr_facilities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pr_facilities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pr_facilities_id_seq OWNED BY public.pr_facilities.id;


--
-- Name: pr_financial_periods; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_financial_periods (
    id integer NOT NULL,
    period_end date NOT NULL,
    period_type character varying(10) DEFAULT 'quarter'::character varying NOT NULL,
    total_assets numeric(18,2),
    total_liabilities numeric(18,2),
    equity numeric(18,2),
    paid_up_capital numeric(18,2),
    capital_base numeric(18,2),
    revenue numeric(18,2),
    net_profit numeric(18,2),
    loan_portfolio numeric(18,2),
    extra jsonb DEFAULT '{}'::jsonb NOT NULL,
    source character varying(10) DEFAULT 'manual'::character varying NOT NULL,
    status character varying(10) DEFAULT 'draft'::character varying NOT NULL,
    approved_by integer,
    approved_at timestamp without time zone,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pr_financial_periods_period_type_check CHECK (((period_type)::text = ANY ((ARRAY['month'::character varying, 'quarter'::character varying, 'half'::character varying, 'year'::character varying])::text[]))),
    CONSTRAINT pr_financial_periods_source_check CHECK (((source)::text = ANY ((ARRAY['manual'::character varying, 'import'::character varying, 'erp'::character varying])::text[]))),
    CONSTRAINT pr_financial_periods_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'approved'::character varying])::text[])))
);


--
-- Name: pr_financial_periods_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pr_financial_periods_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pr_financial_periods_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pr_financial_periods_id_seq OWNED BY public.pr_financial_periods.id;


--
-- Name: pr_key_function_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_key_function_types (
    code character varying(40) NOT NULL,
    name_en character varying(200) NOT NULL,
    name_ar character varying(200),
    is_required boolean DEFAULT true NOT NULL,
    notify_regulator boolean DEFAULT true NOT NULL,
    needs_no_objection boolean DEFAULT false NOT NULL,
    sort_order integer DEFAULT 100 NOT NULL,
    pack_code character varying(40)
);


--
-- Name: pr_key_functions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_key_functions (
    id integer NOT NULL,
    function_code character varying(40) NOT NULL,
    holder_user_id integer,
    holder_name character varying(255),
    board_member_id integer,
    appointed_on date,
    vacated_on date,
    fit_proper_status character varying(10) DEFAULT 'pending'::character varying NOT NULL,
    fit_proper_date date,
    regulator_notified_on date,
    regulator_ref character varying(200),
    no_objection_status character varying(12) DEFAULT 'not_required'::character varying NOT NULL,
    no_objection_on date,
    note text,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pr_key_functions_fit_proper_status_check CHECK (((fit_proper_status)::text = ANY ((ARRAY['pending'::character varying, 'passed'::character varying, 'failed'::character varying, 'na'::character varying])::text[]))),
    CONSTRAINT pr_key_functions_no_objection_status_check CHECK (((no_objection_status)::text = ANY ((ARRAY['not_required'::character varying, 'pending'::character varying, 'granted'::character varying, 'refused'::character varying])::text[])))
);


--
-- Name: pr_key_functions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pr_key_functions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pr_key_functions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pr_key_functions_id_seq OWNED BY public.pr_key_functions.id;


--
-- Name: pr_related_parties; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_related_parties (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    relation character varying(30) DEFAULT 'shareholder'::character varying NOT NULL,
    party_id integer,
    ownership_pct numeric(6,2),
    exited_on date,
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pr_related_parties_relation_check CHECK (((relation)::text = ANY ((ARRAY['shareholder'::character varying, 'exiting_shareholder'::character varying, 'director'::character varying, 'affiliate'::character varying, 'key_person'::character varying, 'other'::character varying])::text[])))
);


--
-- Name: pr_related_parties_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pr_related_parties_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pr_related_parties_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pr_related_parties_id_seq OWNED BY public.pr_related_parties.id;


--
-- Name: pr_rp_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_rp_items (
    id integer NOT NULL,
    related_party_id integer NOT NULL,
    item_type character varying(30) NOT NULL,
    amount numeric(18,2) NOT NULL,
    item_date date NOT NULL,
    payer_name character varying(255),
    classification character varying(20),
    explanation text,
    source character varying(10) DEFAULT 'manual'::character varying NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pr_rp_items_classification_check CHECK (((classification)::text = ANY ((ARRAY['liability'::character varying, 'equity'::character varying, 'receivable'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT pr_rp_items_item_type_check CHECK (((item_type)::text = ANY ((ARRAY['capital_contribution'::character varying, 'loan_from'::character varying, 'loan_to'::character varying, 'current_account'::character varying, 'dues'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT pr_rp_items_source_check CHECK (((source)::text = ANY ((ARRAY['manual'::character varying, 'import'::character varying, 'erp'::character varying])::text[])))
);


--
-- Name: pr_rp_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pr_rp_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pr_rp_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pr_rp_items_id_seq OWNED BY public.pr_rp_items.id;


--
-- Name: pr_studies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pr_studies (
    id integer NOT NULL,
    study_type character varying(30) NOT NULL,
    title character varying(255) NOT NULL,
    period_end date,
    prepared_by character varying(255),
    approved_on date,
    approved_by_body character varying(200),
    next_refresh_date date,
    status character varying(10) DEFAULT 'draft'::character varying NOT NULL,
    note text,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pr_studies_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'approved'::character varying, 'superseded'::character varying])::text[])))
);


--
-- Name: pr_studies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pr_studies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pr_studies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pr_studies_id_seq OWNED BY public.pr_studies.id;


--
-- Name: rc_alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_alerts (
    id integer NOT NULL,
    alert_type character varying(30) NOT NULL,
    severity character varying(10) DEFAULT 'high'::character varying NOT NULL,
    control_id integer,
    evidence_id integer,
    finding_id integer,
    run_id integer,
    org_unit_id integer,
    title character varying(300) NOT NULL,
    message text,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    owner_user_id integer,
    raised_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_notified_at timestamp without time zone,
    notify_count integer DEFAULT 0 NOT NULL,
    escalated_at timestamp without time zone,
    escalated_to integer[],
    case_id integer,
    acknowledged_by integer,
    acknowledged_at timestamp without time zone,
    resolved_at timestamp without time zone,
    resolution_note text,
    CONSTRAINT rc_alerts_alert_type_check CHECK (((alert_type)::text = ANY ((ARRAY['control_failed'::character varying, 'evidence_expiring'::character varying, 'evidence_expired'::character varying, 'finding_overdue'::character varying, 'repeated_violation'::character varying])::text[]))),
    CONSTRAINT rc_alerts_severity_check CHECK (((severity)::text = ANY ((ARRAY['critical'::character varying, 'high'::character varying, 'medium'::character varying, 'low'::character varying])::text[]))),
    CONSTRAINT rc_alerts_status_check CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'acknowledged'::character varying, 'resolved'::character varying])::text[])))
);


--
-- Name: rc_alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_alerts_id_seq OWNED BY public.rc_alerts.id;


--
-- Name: rc_areas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_areas (
    code character varying(40) NOT NULL,
    name_en character varying(200) NOT NULL,
    name_ar character varying(200),
    sort_order integer DEFAULT 100 NOT NULL,
    pack_code character varying(40)
);


--
-- Name: rc_calendar_reminders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_calendar_reminders (
    item_key character varying(120) NOT NULL,
    days_before integer NOT NULL,
    sent_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: rc_control_requirements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_control_requirements (
    control_id integer NOT NULL,
    requirement_id integer NOT NULL
);


--
-- Name: rc_control_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_control_runs (
    id integer NOT NULL,
    control_id integer NOT NULL,
    org_unit_id integer,
    status character varying(20) NOT NULL,
    summary text,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    affected_count integer DEFAULT 0 NOT NULL,
    affected_records jsonb DEFAULT '[]'::jsonb NOT NULL,
    check_name character varying(200),
    triggered_by character varying(20) DEFAULT 'schedule'::character varying NOT NULL,
    run_by integer,
    finding_id integer,
    started_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    finished_at timestamp without time zone,
    duration_ms integer,
    CONSTRAINT rc_control_runs_status_check CHECK (((status)::text = ANY ((ARRAY['pass'::character varying, 'warning'::character varying, 'fail'::character varying, 'error'::character varying, 'no_check'::character varying, 'not_applicable'::character varying])::text[]))),
    CONSTRAINT rc_control_runs_triggered_by_check CHECK (((triggered_by)::text = ANY ((ARRAY['schedule'::character varying, 'manual'::character varying, 'verification'::character varying, 'api'::character varying, 'event'::character varying, 'manual_test'::character varying])::text[])))
);


--
-- Name: rc_control_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_control_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_control_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_control_runs_id_seq OWNED BY public.rc_control_runs.id;


--
-- Name: rc_controls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_controls (
    id integer NOT NULL,
    control_code character varying(40) NOT NULL,
    area character varying(40),
    title_en character varying(300) NOT NULL,
    title_ar character varying(300),
    requirement_en text,
    requirement_ar text,
    control_type character varying(20) NOT NULL,
    type_codes character varying(10),
    frequency character varying(20) DEFAULT 'monthly'::character varying NOT NULL,
    criticality character varying(10) DEFAULT 'high'::character varying NOT NULL,
    owner_role character varying(40),
    owner_user_id integer,
    linked_module character varying(40),
    linked_params text[] DEFAULT '{}'::text[] NOT NULL,
    licence_types text[] DEFAULT '{all}'::text[] NOT NULL,
    check_key character varying(120),
    test_procedure_en text,
    test_procedure_ar text,
    erm_control_id integer,
    auto_create_case boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    pack_code character varying(40),
    last_run_id integer,
    last_run_at timestamp without time zone,
    last_status character varying(20),
    next_run_due timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    check_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT rc_controls_control_type_check CHECK (((control_type)::text = ANY ((ARRAY['automated'::character varying, 'evidence'::character varying, 'workflow'::character varying, 'metric'::character varying])::text[]))),
    CONSTRAINT rc_controls_criticality_check CHECK (((criticality)::text = ANY ((ARRAY['critical'::character varying, 'high'::character varying, 'medium'::character varying, 'low'::character varying])::text[]))),
    CONSTRAINT rc_controls_frequency_check CHECK (((frequency)::text = ANY ((ARRAY['daily'::character varying, 'weekly'::character varying, 'monthly'::character varying, 'quarterly'::character varying, 'semi_annual'::character varying, 'annual'::character varying, 'event'::character varying, 'on_demand'::character varying])::text[])))
);


--
-- Name: rc_controls_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_controls_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_controls_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_controls_id_seq OWNED BY public.rc_controls.id;


--
-- Name: rc_corrective_actions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_corrective_actions (
    id integer NOT NULL,
    finding_id integer NOT NULL,
    description text NOT NULL,
    owner_user_id integer,
    due_date date,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    completion_note text,
    completed_at timestamp without time zone,
    completed_by integer,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT rc_corrective_actions_status_check CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'in_progress'::character varying, 'done'::character varying, 'cancelled'::character varying])::text[])))
);


--
-- Name: rc_corrective_actions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_corrective_actions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_corrective_actions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_corrective_actions_id_seq OWNED BY public.rc_corrective_actions.id;


--
-- Name: rc_evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_evidence (
    id integer NOT NULL,
    control_id integer NOT NULL,
    org_unit_id integer,
    title character varying(300) NOT NULL,
    description text,
    reference_no character varying(120),
    valid_from date,
    valid_to date,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    source character varying(20) DEFAULT 'manual'::character varying NOT NULL,
    source_module character varying(40),
    submitted_by integer,
    submitted_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    review_comment text,
    CONSTRAINT rc_evidence_dates_chk CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT rc_evidence_source_check CHECK (((source)::text = ANY ((ARRAY['manual'::character varying, 'api'::character varying, 'system'::character varying])::text[]))),
    CONSTRAINT rc_evidence_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'expired'::character varying])::text[])))
);


--
-- Name: rc_evidence_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_evidence_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_evidence_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_evidence_id_seq OWNED BY public.rc_evidence.id;


--
-- Name: rc_finding_controls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_finding_controls (
    finding_id integer NOT NULL,
    control_id integer NOT NULL
);


--
-- Name: rc_finding_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_finding_events (
    id integer NOT NULL,
    finding_id integer NOT NULL,
    event_type character varying(40) NOT NULL,
    note text,
    run_id integer,
    user_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: rc_finding_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_finding_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_finding_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_finding_events_id_seq OWNED BY public.rc_finding_events.id;


--
-- Name: rc_findings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_findings (
    id integer NOT NULL,
    reference character varying(30),
    source character varying(30) DEFAULT 'regulator'::character varying NOT NULL,
    source_ref character varying(200),
    regulator_id integer,
    framework_id integer,
    title character varying(400) NOT NULL,
    description text,
    severity character varying(10) DEFAULT 'medium'::character varying NOT NULL,
    area character varying(40),
    org_unit_id integer,
    owner_user_id integer,
    identified_date date DEFAULT CURRENT_DATE NOT NULL,
    due_date date,
    status character varying(30) DEFAULT 'open'::character varying NOT NULL,
    closure_type character varying(20),
    is_repeated boolean DEFAULT false NOT NULL,
    repeat_count integer DEFAULT 0 NOT NULL,
    last_repeat_at timestamp without time zone,
    verified_at timestamp without time zone,
    verified_by integer,
    verification_note text,
    closed_at timestamp without time zone,
    closed_by integer,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT rc_findings_closure_type_check CHECK (((closure_type)::text = ANY ((ARRAY['remediated'::character varying, 'not_applicable'::character varying, 'risk_accepted'::character varying])::text[]))),
    CONSTRAINT rc_findings_severity_check CHECK (((severity)::text = ANY ((ARRAY['critical'::character varying, 'high'::character varying, 'medium'::character varying, 'low'::character varying])::text[]))),
    CONSTRAINT rc_findings_source_check CHECK (((source)::text = ANY ((ARRAY['regulator'::character varying, 'internal_audit'::character varying, 'self_identified'::character varying, 'external_audit'::character varying, 'control_failure'::character varying])::text[]))),
    CONSTRAINT rc_findings_status_check CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'action_plan'::character varying, 'in_progress'::character varying, 'pending_verification'::character varying, 'closed'::character varying, 'reopened'::character varying])::text[])))
);


--
-- Name: rc_findings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_findings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_findings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_findings_id_seq OWNED BY public.rc_findings.id;


--
-- Name: rc_frameworks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_frameworks (
    id integer NOT NULL,
    code character varying(40) NOT NULL,
    name_en character varying(300) NOT NULL,
    name_ar character varying(300),
    regulator_id integer,
    jurisdiction character varying(10),
    version character varying(40),
    description text,
    source_document text,
    pack_code character varying(40),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: rc_frameworks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_frameworks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_frameworks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_frameworks_id_seq OWNED BY public.rc_frameworks.id;


--
-- Name: rc_licence_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_licence_types (
    code character varying(40) NOT NULL,
    name_en character varying(200) NOT NULL,
    name_ar character varying(200),
    regulator_id integer,
    jurisdiction character varying(10),
    pack_code character varying(40),
    is_active boolean DEFAULT true NOT NULL
);


--
-- Name: rc_owner_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_owner_roles (
    code character varying(40) NOT NULL,
    name_en character varying(200) NOT NULL,
    name_ar character varying(200),
    pack_code character varying(40)
);


--
-- Name: rc_packs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_packs (
    code character varying(40) NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    installed_version character varying(20),
    installed_at timestamp without time zone,
    deactivated_controls integer[] DEFAULT '{}'::integer[] NOT NULL,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: rc_parameter_changes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_parameter_changes (
    id integer NOT NULL,
    parameter_id integer,
    param_key character varying(120) NOT NULL,
    licence_type character varying(40) DEFAULT 'all'::character varying NOT NULL,
    change_type character varying(20) NOT NULL,
    old_value text,
    new_value text,
    value_type character varying(20),
    unit character varying(30),
    effective_from date,
    effective_to date,
    legal_reference text,
    description_en text,
    description_ar text,
    needs_review boolean,
    review_note text,
    reason text NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    requested_by integer,
    requested_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    decided_by integer,
    decided_at timestamp without time zone,
    decision_comment text,
    applied_parameter_id integer,
    CONSTRAINT rc_parameter_changes_change_type_check CHECK (((change_type)::text = ANY ((ARRAY['create'::character varying, 'update'::character varying, 'new_version'::character varying, 'retire'::character varying, 'review'::character varying])::text[]))),
    CONSTRAINT rc_parameter_changes_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[])))
);


--
-- Name: rc_parameter_changes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_parameter_changes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_parameter_changes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_parameter_changes_id_seq OWNED BY public.rc_parameter_changes.id;


--
-- Name: rc_parameters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_parameters (
    id integer NOT NULL,
    param_key character varying(120) NOT NULL,
    licence_type character varying(40) DEFAULT 'all'::character varying NOT NULL,
    value_text text,
    value_type character varying(20) DEFAULT 'number'::character varying NOT NULL,
    unit character varying(30),
    effective_from date DEFAULT '2020-01-01'::date NOT NULL,
    effective_to date,
    framework_id integer,
    legal_reference text,
    description_en text,
    description_ar text,
    needs_review boolean DEFAULT false NOT NULL,
    review_note text,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    pack_code character varying(40),
    created_by integer,
    approved_by integer,
    approved_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT rc_parameters_dates_chk CHECK (((effective_to IS NULL) OR (effective_to >= effective_from))),
    CONSTRAINT rc_parameters_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'retired'::character varying])::text[]))),
    CONSTRAINT rc_parameters_value_type_check CHECK (((value_type)::text = ANY ((ARRAY['number'::character varying, 'integer'::character varying, 'amount'::character varying, 'percent'::character varying, 'boolean'::character varying, 'text'::character varying, 'json'::character varying, 'date'::character varying])::text[])))
);


--
-- Name: rc_parameters_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_parameters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_parameters_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_parameters_id_seq OWNED BY public.rc_parameters.id;


--
-- Name: rc_readiness_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_readiness_snapshots (
    id integer NOT NULL,
    snapshot_date date NOT NULL,
    framework_id integer,
    area_code character varying(40),
    score numeric(5,1),
    controls integer DEFAULT 0 NOT NULL,
    failing integer DEFAULT 0 NOT NULL,
    open_findings integer DEFAULT 0 NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: rc_readiness_snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_readiness_snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_readiness_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_readiness_snapshots_id_seq OWNED BY public.rc_readiness_snapshots.id;


--
-- Name: rc_requirements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rc_requirements (
    id integer NOT NULL,
    framework_id integer NOT NULL,
    ref_code character varying(40) NOT NULL,
    title_en character varying(400) NOT NULL,
    title_ar character varying(400),
    text_en text,
    text_ar text,
    legal_reference text,
    area_code character varying(40),
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: rc_requirements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rc_requirements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rc_requirements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rc_requirements_id_seq OWNED BY public.rc_requirements.id;


--
-- Name: red_flags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.red_flags (
    id integer NOT NULL,
    flag_code text,
    flag_name text,
    flag_description text,
    flag_category text,
    severity text,
    is_active integer
);


--
-- Name: red_flags_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.red_flags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: red_flags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.red_flags_id_seq OWNED BY public.red_flags.id;


--
-- Name: regulators; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.regulators (
    id integer NOT NULL,
    regulator_name text,
    regulator_code text,
    contact_email text,
    contact_phone text,
    website text,
    description text,
    is_active integer,
    name_ar character varying(200),
    jurisdiction character varying(10)
);


--
-- Name: regulators_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.regulators_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: regulators_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.regulators_id_seq OWNED BY public.regulators.id;


--
-- Name: regulatory_report_submissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.regulatory_report_submissions (
    id integer NOT NULL,
    report_id integer,
    reporting_period_start text,
    reporting_period_end text,
    due_date text,
    submission_date text,
    status text,
    notes text,
    submission_reference text,
    attachment_path text,
    prepared_by integer,
    reviewed_by integer,
    approved_by integer,
    reminder_sent integer,
    reminder_date text,
    created_at text,
    updated_at text
);


--
-- Name: regulatory_report_submissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.regulatory_report_submissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: regulatory_report_submissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.regulatory_report_submissions_id_seq OWNED BY public.regulatory_report_submissions.id;


--
-- Name: regulatory_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.regulatory_reports (
    id integer NOT NULL,
    report_code text,
    report_name text,
    regulator_id integer,
    frequency text,
    due_day integer,
    due_month integer,
    description text,
    submission_method text,
    responsible_department text,
    cbe_circular_reference text,
    is_active integer,
    created_at text,
    regulatory_reference text
);


--
-- Name: regulatory_reports_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.regulatory_reports_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: regulatory_reports_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.regulatory_reports_id_seq OWNED BY public.regulatory_reports.id;


--
-- Name: reminder_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reminder_log (
    id integer NOT NULL,
    campaign_id integer,
    sent_by integer,
    recipients integer DEFAULT 0 NOT NULL,
    channel text DEFAULT 'inapp'::text NOT NULL,
    subject text,
    message text,
    target_filter text,
    sent_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: reminder_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reminder_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reminder_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reminder_log_id_seq OWNED BY public.reminder_log.id;


--
-- Name: required_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.required_policies (
    id integer NOT NULL,
    policy_name_en text,
    policy_name_ar text,
    regulatory_reference text,
    is_mandatory integer,
    description_en text,
    description_ar text,
    created_at text
);


--
-- Name: required_policies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.required_policies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: required_policies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.required_policies_id_seq OWNED BY public.required_policies.id;


--
-- Name: risk_appetite_statements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_appetite_statements (
    id integer NOT NULL,
    category_id integer,
    statement_text text NOT NULL,
    appetite_level character varying(20) NOT NULL,
    max_acceptable_inherent_score integer,
    max_acceptable_residual_score integer NOT NULL,
    effective_from date NOT NULL,
    effective_to date,
    approved_by_meeting_id integer,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT risk_appetite_statements_appetite_level_check CHECK (((appetite_level)::text = ANY (ARRAY[('AVERSE'::character varying)::text, ('MINIMAL'::character varying)::text, ('CAUTIOUS'::character varying)::text, ('OPEN'::character varying)::text, ('HUNGRY'::character varying)::text])))
);


--
-- Name: risk_appetite_statements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.risk_appetite_statements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_appetite_statements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.risk_appetite_statements_id_seq OWNED BY public.risk_appetite_statements.id;


--
-- Name: risk_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_categories (
    id integer NOT NULL,
    category_code character varying(10) NOT NULL,
    parent_category_id integer,
    category_name character varying(100) NOT NULL,
    category_description text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: risk_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.risk_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.risk_categories_id_seq OWNED BY public.risk_categories.id;


--
-- Name: risk_controls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_controls (
    id integer NOT NULL,
    risk_id integer NOT NULL,
    control_id integer NOT NULL,
    reliance_level character varying(20) DEFAULT 'PRIMARY'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT risk_controls_reliance_level_check CHECK (((reliance_level)::text = ANY (ARRAY[('PRIMARY'::character varying)::text, ('SECONDARY'::character varying)::text])))
);


--
-- Name: risk_controls_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.risk_controls_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_controls_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.risk_controls_id_seq OWNED BY public.risk_controls.id;


--
-- Name: risk_register; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_register (
    id integer NOT NULL,
    risk_reference text,
    risk_title text,
    risk_description text,
    risk_category text,
    risk_sub_category text,
    inherent_likelihood integer,
    inherent_impact integer,
    inherent_score integer,
    inherent_level text,
    existing_controls text,
    residual_likelihood integer,
    residual_impact integer,
    residual_score integer,
    residual_level text,
    treatment_strategy text,
    treatment_plan text,
    treatment_owner_id integer,
    treatment_deadline text,
    treatment_status text,
    target_likelihood integer,
    target_impact integer,
    target_score integer,
    target_level text,
    risk_owner_id integer,
    risk_identified_by integer,
    identification_date text,
    last_review_date text,
    next_review_date text,
    review_frequency_months integer,
    status text,
    created_at text,
    updated_at text
);


--
-- Name: risk_register_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.risk_register_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_register_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.risk_register_id_seq OWNED BY public.risk_register.id;


--
-- Name: risk_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_reviews (
    id integer NOT NULL,
    risk_id integer,
    review_date text,
    reviewed_by integer,
    new_likelihood integer,
    new_impact integer,
    new_score integer,
    new_level text,
    risk_changed integer,
    change_reason text,
    treatment_progress text,
    treatment_effectiveness text,
    additional_actions_required text,
    review_notes text,
    created_at text
);


--
-- Name: risk_reviews_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.risk_reviews_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_reviews_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.risk_reviews_id_seq OWNED BY public.risk_reviews.id;


--
-- Name: risk_score_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_score_history (
    id integer NOT NULL,
    risk_id integer NOT NULL,
    likelihood integer NOT NULL,
    impact integer NOT NULL,
    inherent_risk_score integer NOT NULL,
    residual_likelihood integer,
    residual_impact integer,
    residual_risk_score integer,
    control_effectiveness character varying(20),
    changed_by integer,
    change_reason text,
    recorded_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: risk_score_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.risk_score_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_score_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.risk_score_history_id_seq OWNED BY public.risk_score_history.id;


--
-- Name: risk_scoring_bands; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_scoring_bands (
    id integer NOT NULL,
    band_name character varying(30) NOT NULL,
    min_score integer NOT NULL,
    max_score integer NOT NULL,
    color_hex character varying(7) DEFAULT '#6c757d'::character varying NOT NULL,
    display_order integer NOT NULL,
    requires_board_notification boolean DEFAULT false NOT NULL
);


--
-- Name: risk_scoring_bands_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.risk_scoring_bands_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_scoring_bands_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.risk_scoring_bands_id_seq OWNED BY public.risk_scoring_bands.id;


--
-- Name: risk_source_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_source_links (
    id integer NOT NULL,
    risk_id integer NOT NULL,
    source_module character varying(40) NOT NULL,
    source_table character varying(60) NOT NULL,
    source_record_id integer NOT NULL,
    link_type character varying(20) DEFAULT 'EVIDENCE'::character varying NOT NULL,
    linked_by integer,
    linked_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    notes text,
    CONSTRAINT risk_source_links_link_type_check CHECK (((link_type)::text = ANY (ARRAY[('TRIGGER'::character varying)::text, ('EVIDENCE'::character varying)::text, ('RELATED'::character varying)::text])))
);


--
-- Name: risk_source_links_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.risk_source_links_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_source_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.risk_source_links_id_seq OWNED BY public.risk_source_links.id;


--
-- Name: risk_treatments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_treatments (
    id integer NOT NULL,
    risk_id integer NOT NULL,
    treatment_description text NOT NULL,
    treatment_type character varying(20),
    treatment_owner_id integer NOT NULL,
    estimated_cost numeric(15,2),
    budget_approved boolean DEFAULT false NOT NULL,
    target_date date NOT NULL,
    completion_date date,
    status character varying(20) DEFAULT 'PROPOSED'::character varying NOT NULL,
    verified_by integer,
    verified_at timestamp without time zone,
    verification_notes text,
    evidence_file character varying(500),
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT risk_treatments_status_check CHECK (((status)::text = ANY (ARRAY[('PROPOSED'::character varying)::text, ('APPROVED'::character varying)::text, ('IN_PROGRESS'::character varying)::text, ('COMPLETED'::character varying)::text, ('VERIFIED'::character varying)::text, ('CLOSED'::character varying)::text, ('REJECTED'::character varying)::text]))),
    CONSTRAINT risk_treatments_treatment_type_check CHECK (((treatment_type)::text = ANY (ARRAY[('ACCEPT'::character varying)::text, ('MITIGATE'::character varying)::text, ('TRANSFER'::character varying)::text, ('AVOID'::character varying)::text])))
);


--
-- Name: risk_treatments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.risk_treatments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_treatments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.risk_treatments_id_seq OWNED BY public.risk_treatments.id;


--
-- Name: risks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risks (
    id integer NOT NULL,
    risk_id character varying(50) NOT NULL,
    risk_title character varying(255) NOT NULL,
    risk_description text,
    category_id integer NOT NULL,
    secondary_tags text[],
    department_id integer,
    parent_risk_id integer,
    likelihood integer NOT NULL,
    impact integer NOT NULL,
    inherent_risk_score integer NOT NULL,
    existing_controls text,
    control_effectiveness character varying(20),
    residual_likelihood integer,
    residual_impact integer,
    residual_risk_score integer,
    risk_response character varying(20),
    risk_owner_id integer,
    review_frequency character varying(20) DEFAULT 'QUARTERLY'::character varying NOT NULL,
    last_review_date date,
    next_review_date date,
    risk_appetite_aligned boolean,
    status character varying(20) DEFAULT 'ACTIVE'::character varying NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT risks_control_effectiveness_check CHECK (((control_effectiveness)::text = ANY (ARRAY[('EFFECTIVE'::character varying)::text, ('PARTIALLY_EFFECTIVE'::character varying)::text, ('INEFFECTIVE'::character varying)::text, ('NOT_ASSESSED'::character varying)::text]))),
    CONSTRAINT risks_impact_check CHECK (((impact >= 1) AND (impact <= 5))),
    CONSTRAINT risks_likelihood_check CHECK (((likelihood >= 1) AND (likelihood <= 5))),
    CONSTRAINT risks_residual_impact_check CHECK (((residual_impact >= 1) AND (residual_impact <= 5))),
    CONSTRAINT risks_residual_likelihood_check CHECK (((residual_likelihood >= 1) AND (residual_likelihood <= 5))),
    CONSTRAINT risks_review_frequency_check CHECK (((review_frequency)::text = ANY (ARRAY[('MONTHLY'::character varying)::text, ('QUARTERLY'::character varying)::text, ('SEMI_ANNUAL'::character varying)::text, ('ANNUAL'::character varying)::text]))),
    CONSTRAINT risks_risk_response_check CHECK (((risk_response)::text = ANY (ARRAY[('ACCEPT'::character varying)::text, ('MITIGATE'::character varying)::text, ('TRANSFER'::character varying)::text, ('AVOID'::character varying)::text]))),
    CONSTRAINT risks_status_check CHECK (((status)::text = ANY (ARRAY[('DRAFT'::character varying)::text, ('ACTIVE'::character varying)::text, ('CLOSED'::character varying)::text, ('ACCEPTED'::character varying)::text])))
);


--
-- Name: risks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.risks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.risks_id_seq OWNED BY public.risks.id;


--
-- Name: sanctions_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sanctions_entries (
    id integer NOT NULL,
    list_id integer,
    entry_id text,
    entry_type text,
    name text,
    aliases text,
    date_of_birth text,
    nationality text,
    addresses text,
    identifications text,
    programs text,
    remarks text,
    listed_date text
);


--
-- Name: sanctions_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sanctions_entries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sanctions_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sanctions_entries_id_seq OWNED BY public.sanctions_entries.id;


--
-- Name: sanctions_lists; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sanctions_lists (
    id integer NOT NULL,
    list_code text,
    list_name text,
    source_url text,
    last_download_date text,
    record_count integer,
    is_active integer
);


--
-- Name: sanctions_lists_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sanctions_lists_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sanctions_lists_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sanctions_lists_id_seq OWNED BY public.sanctions_lists.id;


--
-- Name: sanctions_matches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sanctions_matches (
    id integer NOT NULL,
    screening_id integer,
    sanctioned_name text,
    sanctions_list text,
    list_id text,
    match_score numeric,
    match_details text,
    investigation_status text,
    investigated_by integer,
    investigation_date text,
    investigation_notes text,
    is_false_positive integer,
    false_positive_reason text,
    is_blocked integer,
    blocked_date text,
    emlcu_notified integer,
    emlcu_notification_date text,
    emlcu_reference text
);


--
-- Name: sanctions_matches_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sanctions_matches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sanctions_matches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sanctions_matches_id_seq OWNED BY public.sanctions_matches.id;


--
-- Name: sanctions_screening_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sanctions_screening_log (
    id integer NOT NULL,
    screening_type text,
    customer_id integer,
    transaction_id integer,
    screened_name text,
    screening_date text,
    match_found integer,
    match_score numeric,
    matched_list text,
    matched_entity_name text,
    status text,
    reviewed_by integer,
    review_date text,
    review_notes text,
    action_taken text
);


--
-- Name: sanctions_screening_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sanctions_screening_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sanctions_screening_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sanctions_screening_log_id_seq OWNED BY public.sanctions_screening_log.id;


--
-- Name: sanctions_screenings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sanctions_screenings (
    id integer NOT NULL,
    screening_reference text,
    entity_type text,
    entity_id integer,
    entity_name text,
    screening_date text,
    screened_by integer,
    lists_checked text,
    matches_found integer,
    status text
);


--
-- Name: sanctions_screenings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sanctions_screenings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sanctions_screenings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sanctions_screenings_id_seq OWNED BY public.sanctions_screenings.id;


--
-- Name: sar_red_flags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sar_red_flags (
    id integer NOT NULL,
    sar_id integer,
    red_flag_id integer,
    notes text
);


--
-- Name: sar_red_flags_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sar_red_flags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sar_red_flags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sar_red_flags_id_seq OWNED BY public.sar_red_flags.id;


--
-- Name: sar_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sar_reports (
    id integer NOT NULL,
    sar_reference text,
    customer_id integer,
    detection_date text,
    detected_by integer,
    detection_method text,
    activity_description text,
    red_flags text,
    transaction_ids text,
    total_amount numeric,
    currency text,
    activity_period_start text,
    activity_period_end text,
    assigned_to integer,
    investigation_notes text,
    investigation_completed integer,
    investigation_completed_date text,
    decision text,
    decision_by integer,
    decision_date text,
    decision_rationale text,
    filed_to_emlcu integer,
    emlcu_filing_date text,
    emlcu_reference_number text,
    goaml_submission_id text,
    filed_to_cbe integer,
    cbe_filing_date text,
    emlcu_feedback text,
    emlcu_feedback_date text,
    case_closed integer,
    case_closed_date text,
    access_restricted integer,
    created_at text,
    created_by integer
);


--
-- Name: sar_reports_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sar_reports_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sar_reports_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sar_reports_id_seq OWNED BY public.sar_reports.id;


--
-- Name: screening_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_config (
    id integer NOT NULL,
    config_key text,
    config_value text,
    category text,
    description text,
    updated_at text
);


--
-- Name: screening_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_config_id_seq OWNED BY public.screening_config.id;


--
-- Name: screening_data_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_data_sources (
    id integer NOT NULL,
    source_name text,
    source_display_name text,
    source_url text,
    source_type text,
    is_official integer,
    is_active integer,
    update_frequency_hours integer,
    last_successful_update text,
    total_records integer,
    last_updated_by integer,
    last_update_attempt text,
    next_scheduled_update text,
    records_added_last_update integer,
    records_updated_last_update integer,
    consecutive_failures integer,
    last_error_message text,
    updated_at text,
    updated_by integer,
    last_update_records_added integer,
    last_update_records_updated integer,
    last_update_duration_seconds integer,
    last_update_error text,
    priority integer
);


--
-- Name: screening_data_sources_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_data_sources_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_data_sources_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_data_sources_id_seq OWNED BY public.screening_data_sources.id;


--
-- Name: screening_delta_hits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_delta_hits (
    id integer NOT NULL,
    run_id integer,
    found_at timestamp with time zone DEFAULT now() NOT NULL,
    subject_table text NOT NULL,
    subject_id integer NOT NULL,
    subject_name text,
    list_table text NOT NULL,
    list_record_id bigint NOT NULL,
    listed_name text,
    list_source text,
    category text,
    score numeric,
    tier text,
    decision jsonb,
    status text DEFAULT 'open'::text NOT NULL,
    reviewed_by integer,
    reviewed_at timestamp with time zone,
    review_note text
);


--
-- Name: screening_delta_hits_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_delta_hits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_delta_hits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_delta_hits_id_seq OWNED BY public.screening_delta_hits.id;


--
-- Name: screening_delta_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_delta_runs (
    id integer NOT NULL,
    run_at timestamp with time zone DEFAULT now() NOT NULL,
    from_bl_id bigint,
    to_bl_id bigint,
    from_pep_id bigint,
    to_pep_id bigint,
    from_wl_id bigint,
    to_wl_id bigint,
    new_names integer DEFAULT 0,
    subjects integer DEFAULT 0,
    hits integer DEFAULT 0,
    duration_s numeric,
    note text
);


--
-- Name: screening_delta_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_delta_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_delta_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_delta_runs_id_seq OWNED BY public.screening_delta_runs.id;


--
-- Name: screening_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_history (
    id integer NOT NULL,
    entity_name text,
    entity_type text,
    screening_date text,
    screening_type text,
    initiated_by integer,
    source_module text,
    source_record_id integer,
    total_matches_found integer,
    high_risk_matches integer,
    auto_cleared_matches integer,
    highest_score double precision,
    screening_result text,
    matches_json text,
    status text,
    resolution_date text,
    resolved_by integer,
    notes text,
    processing_time_ms integer,
    created_at timestamp without time zone,
    screening_result_id integer
);


--
-- Name: screening_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_history_id_seq OWNED BY public.screening_history.id;


--
-- Name: screening_list_update_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_list_update_log (
    id integer NOT NULL,
    run_at timestamp with time zone DEFAULT now() NOT NULL,
    source text NOT NULL,
    status text NOT NULL,
    added integer DEFAULT 0,
    updated integer DEFAULT 0,
    unchanged integer DEFAULT 0,
    delisted integer DEFAULT 0,
    relisted integer DEFAULT 0,
    errors integer DEFAULT 0,
    error text,
    duration_s numeric
);


--
-- Name: screening_list_update_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_list_update_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_list_update_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_list_update_log_id_seq OWNED BY public.screening_list_update_log.id;


--
-- Name: screening_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_metrics (
    id integer NOT NULL,
    "timestamp" text,
    processing_time_ms double precision,
    total_candidates integer,
    total_matches integer,
    highest_score double precision,
    cache_hit integer,
    screened_name text,
    entity_type text,
    match_status text
);


--
-- Name: screening_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_metrics_id_seq OWNED BY public.screening_metrics.id;


--
-- Name: screening_qa_cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_qa_cases (
    id integer NOT NULL,
    query_name character varying(300) NOT NULL,
    expected_name character varying(300),
    variant_type character varying(40) DEFAULT 'exact'::character varying NOT NULL,
    expect_match boolean DEFAULT true NOT NULL,
    list_label character varying(120),
    entity_type character varying(20) DEFAULT 'INDIVIDUAL'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: screening_qa_cases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_qa_cases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_qa_cases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_qa_cases_id_seq OWNED BY public.screening_qa_cases.id;


--
-- Name: screening_qa_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_qa_runs (
    id integer NOT NULL,
    run_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    run_by integer,
    cases integer DEFAULT 0 NOT NULL,
    positives integer DEFAULT 0 NOT NULL,
    hits integer DEFAULT 0 NOT NULL,
    misses integer DEFAULT 0 NOT NULL,
    false_positives integer DEFAULT 0 NOT NULL,
    recall_pct numeric(6,2),
    precision_pct numeric(6,2),
    details jsonb DEFAULT '[]'::jsonb NOT NULL,
    error text
);


--
-- Name: screening_qa_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_qa_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_qa_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_qa_runs_id_seq OWNED BY public.screening_qa_runs.id;


--
-- Name: screening_quality_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_quality_runs (
    id integer NOT NULL,
    run_at timestamp with time zone DEFAULT now() NOT NULL,
    kind text DEFAULT 'scheduled'::text NOT NULL,
    summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    cases jsonb DEFAULT '[]'::jsonb NOT NULL,
    duration_s numeric
);


--
-- Name: screening_quality_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_quality_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_quality_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_quality_runs_id_seq OWNED BY public.screening_quality_runs.id;


--
-- Name: screening_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_queue (
    id integer NOT NULL,
    screening_history_id integer,
    entity_name text,
    entity_type text,
    match_name text,
    match_score double precision,
    list_source text,
    match_details text,
    assigned_to integer,
    priority text,
    status text,
    resolution text,
    resolution_notes text,
    resolved_by integer,
    resolved_date text,
    escalated integer,
    escalation_reason text,
    source_module text,
    source_record_id integer,
    created_at timestamp without time zone
);


--
-- Name: screening_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_queue_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_queue_id_seq OWNED BY public.screening_queue.id;


--
-- Name: screening_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_results (
    id integer NOT NULL,
    screening_type text,
    screened_name text,
    screened_dob text,
    screening_method text,
    total_matches_found integer,
    highest_match_score double precision,
    screening_result text,
    matches text,
    processing_time_ms integer,
    created_by integer,
    created_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text),
    status text,
    resolution_notes text,
    resolved_by integer,
    resolved_at text,
    adverse_media text,
    adverse_media_summary text,
    adverse_media_count integer,
    match_details text,
    risk_score double precision,
    reviewed_by integer,
    reviewed_at text,
    false_positive integer,
    search_degraded integer DEFAULT 0
);


--
-- Name: screening_results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_results_id_seq OWNED BY public.screening_results.id;


--
-- Name: screening_risk_criteria; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_risk_criteria (
    id integer NOT NULL,
    band text NOT NULL,
    factor text NOT NULL,
    operator text DEFAULT 'equals'::text NOT NULL,
    value text,
    weight integer DEFAULT 1 NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_by integer,
    updated_at timestamp without time zone
);


--
-- Name: screening_risk_criteria_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_risk_criteria_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_risk_criteria_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_risk_criteria_id_seq OWNED BY public.screening_risk_criteria.id;


--
-- Name: screening_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_settings (
    id integer NOT NULL,
    key text,
    value text,
    category text,
    description text,
    updated_at text
);


--
-- Name: screening_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_settings_id_seq OWNED BY public.screening_settings.id;


--
-- Name: screening_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_tasks (
    task_id character varying(36) NOT NULL,
    status character varying(20) DEFAULT 'processing'::character varying NOT NULL,
    message text,
    progress integer DEFAULT 0,
    total integer DEFAULT 100,
    result jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: screening_update_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_update_log (
    id integer NOT NULL,
    source_name text,
    update_type text,
    records_added integer,
    records_updated integer,
    records_skipped integer,
    records_failed integer,
    update_date text,
    status text,
    error_message text,
    execution_time_seconds double precision,
    file_hash text
);


--
-- Name: screening_update_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_update_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_update_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_update_log_id_seq OWNED BY public.screening_update_log.id;


--
-- Name: screening_update_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_update_logs (
    id integer NOT NULL,
    source_name text,
    update_started_at text,
    update_completed_at text,
    duration_seconds integer,
    records_added integer,
    records_updated integer,
    update_status text,
    triggered_by text,
    error_message text,
    created_at text
);


--
-- Name: screening_update_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_update_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_update_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_update_logs_id_seq OWNED BY public.screening_update_logs.id;


--
-- Name: screening_watchlist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_watchlist (
    id integer NOT NULL,
    full_name text,
    original_name text,
    aliases text,
    entity_type text,
    list_type text,
    dataset text,
    topics text,
    date_of_birth text,
    year_of_birth integer,
    place_of_birth text,
    gender text,
    countries text,
    nationality text,
    passport_numbers text,
    national_id_numbers text,
    addresses text,
    source text,
    source_id text,
    source_url text,
    first_seen text,
    last_seen text,
    last_updated text,
    name_normalized text,
    name_soundex text,
    name_metaphone text,
    name_tokens text,
    risk_level text,
    properties text,
    created_at text,
    updated_at text,
    is_active integer,
    full_name_arabic text,
    aliases_arabic text,
    original_script text,
    risk_score integer,
    risk_category text,
    active integer,
    country text,
    country_code text,
    details text
);


--
-- Name: screening_watchlist_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_watchlist_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_watchlist_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_watchlist_id_seq OWNED BY public.screening_watchlist.id;


--
-- Name: screening_whitelist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_whitelist (
    id integer NOT NULL,
    name text,
    normalized_name text,
    reason text,
    added_by integer,
    added_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text),
    whitelisted_name text,
    entity_type text,
    national_id text,
    commercial_registry text,
    date_of_birth text,
    nationality text,
    original_match_name text,
    original_match_score double precision,
    original_list_source text,
    approved_by integer,
    approval_date text,
    review_date text,
    status text,
    notes text,
    matched_entity_id integer,
    matched_entity_source text,
    matched_entity_name text,
    matched_fingerprint text,
    scope text DEFAULT 'entity'::text,
    screening_frequency text DEFAULT 'monthly'::text,
    last_screened_at timestamp without time zone,
    next_screening_at timestamp without time zone,
    source_alert_id integer,
    customer_id integer,
    cleared_match_count integer DEFAULT 0,
    match_set_fingerprint text,
    risk_band text,
    risk_band_by integer,
    risk_band_at timestamp without time zone,
    risk_band_reason text
);


--
-- Name: screening_whitelist_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_whitelist_audit (
    id integer NOT NULL,
    whitelist_id integer,
    entry_name text,
    action text NOT NULL,
    previous_status text,
    new_status text,
    reason text,
    performed_by integer,
    performed_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: screening_whitelist_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_whitelist_audit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_whitelist_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_whitelist_audit_id_seq OWNED BY public.screening_whitelist_audit.id;


--
-- Name: screening_whitelist_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_whitelist_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_whitelist_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_whitelist_id_seq OWNED BY public.screening_whitelist.id;


--
-- Name: screening_whitelist_matches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_whitelist_matches (
    id integer NOT NULL,
    whitelist_id integer NOT NULL,
    entity_id integer NOT NULL,
    entity_name text,
    entity_source text,
    match_score double precision,
    fingerprint text,
    cleared_at timestamp without time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT true NOT NULL
);


--
-- Name: screening_whitelist_matches_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_whitelist_matches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_whitelist_matches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_whitelist_matches_id_seq OWNED BY public.screening_whitelist_matches.id;


--
-- Name: screening_workflow; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_workflow (
    id integer NOT NULL,
    screening_result_id integer,
    workflow_status text DEFAULT 'PENDING'::text,
    assigned_to integer,
    priority text DEFAULT 'NORMAL'::text,
    due_date text,
    action_taken text,
    action_notes text,
    escalated_to integer,
    escalation_reason text,
    completed_by integer,
    completed_at text,
    created_by integer,
    created_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text),
    updated_at text DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'::text)
);


--
-- Name: screening_workflow_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_workflow_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_workflow_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_workflow_id_seq OWNED BY public.screening_workflow.id;


--
-- Name: str_report_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.str_report_templates (
    id integer NOT NULL,
    sector_code text NOT NULL,
    name_en text NOT NULL,
    name_ar text NOT NULL,
    template_url text,
    template_file text,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    notes text
);


--
-- Name: str_report_templates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.str_report_templates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: str_report_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.str_report_templates_id_seq OWNED BY public.str_report_templates.id;


--
-- Name: succession_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.succession_plans (
    id integer NOT NULL,
    position_title text,
    position_type text,
    current_holder_id integer,
    succession_risk text,
    vacancy_risk text,
    critical_position integer,
    expected_vacancy_date text,
    notice_period_months integer,
    search_timeline_months integer,
    transition_period_months integer,
    internal_candidates text,
    external_search_required integer,
    recruitment_firm text,
    interim_successor_id integer,
    interim_plan text,
    acting_arrangements text,
    development_programs text,
    mentorship_arrangements text,
    plan_status text,
    last_review_date text,
    next_review_date text,
    plan_document_path text,
    created_at text,
    updated_at text
);


--
-- Name: succession_plans_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.succession_plans_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: succession_plans_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.succession_plans_id_seq OWNED BY public.succession_plans.id;


--
-- Name: suspicious_activities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.suspicious_activities (
    id integer NOT NULL,
    sar_reference text,
    activity_date text,
    discovery_date text,
    customer_id integer,
    customer_name text,
    activity_description text,
    amount_involved numeric,
    currency text,
    transaction_ids text,
    red_flags_identified text,
    reported_by integer,
    report_date text,
    assigned_to integer,
    assignment_date text,
    investigation_status text,
    investigation_notes text,
    investigation_findings text,
    decision text,
    decision_by integer,
    decision_date text,
    decision_rationale text,
    sar_filed integer,
    sar_filing_date text,
    sar_deadline text,
    sar_days_remaining integer,
    sar_file_path text,
    emlcu_reference text,
    emlcu_acknowledgment_date text,
    emlcu_feedback text,
    created_at text,
    updated_at text
);


--
-- Name: suspicious_activities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.suspicious_activities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: suspicious_activities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.suspicious_activities_id_seq OWNED BY public.suspicious_activities.id;


--
-- Name: system_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_settings (
    setting_key text NOT NULL,
    setting_value text,
    description text,
    updated_at text
);


--
-- Name: three_lines_functions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.three_lines_functions (
    id integer NOT NULL,
    function_name text,
    line_of_defense integer,
    department text,
    function_head_id integer,
    reporting_to text,
    independence_charter_path text,
    independence_confirmed integer,
    independence_confirmation_date text,
    key_responsibilities text,
    created_at text
);


--
-- Name: three_lines_functions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.three_lines_functions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: three_lines_functions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.three_lines_functions_id_seq OWNED BY public.three_lines_functions.id;


--
-- Name: three_lines_raci_matrix; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.three_lines_raci_matrix (
    id integer NOT NULL,
    process_area text,
    first_line_role text,
    second_line_role text,
    third_line_role text,
    description text,
    created_at text
);


--
-- Name: three_lines_raci_matrix_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.three_lines_raci_matrix_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: three_lines_raci_matrix_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.three_lines_raci_matrix_id_seq OWNED BY public.three_lines_raci_matrix.id;


--
-- Name: tm_alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tm_alerts (
    id integer NOT NULL,
    alert_reference text,
    rule_id integer,
    customer_id integer,
    alert_date text,
    alert_description text,
    triggered_transactions text,
    alert_severity text,
    assigned_to integer,
    status text,
    investigation_notes text,
    disposition text,
    disposition_by integer,
    disposition_date text,
    sar_id integer
);


--
-- Name: tm_alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tm_alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tm_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tm_alerts_id_seq OWNED BY public.tm_alerts.id;


--
-- Name: tm_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tm_rules (
    id integer NOT NULL,
    rule_code text,
    rule_name text,
    rule_description text,
    rule_category text,
    rule_type text,
    threshold_value numeric,
    threshold_currency text,
    time_period_days integer,
    is_active integer,
    severity text,
    created_at text,
    created_by integer,
    updated_by integer,
    approved_by integer,
    approved_at timestamp without time zone,
    status character varying(20) DEFAULT 'ACTIVE'::character varying NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    previous_id integer,
    updated_at timestamp without time zone,
    CONSTRAINT tm_rules_status_check CHECK (((status)::text = ANY (ARRAY[('PENDING'::character varying)::text, ('ACTIVE'::character varying)::text, ('DISABLED'::character varying)::text])))
);


--
-- Name: tm_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tm_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tm_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tm_rules_id_seq OWNED BY public.tm_rules.id;


--
-- Name: tracker_declarations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tracker_declarations (
    id integer NOT NULL,
    employee_id integer,
    type text,
    description text,
    start_date text,
    end_date text,
    status text,
    reviewed_by integer,
    review_date text,
    created_at text
);


--
-- Name: tracker_declarations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tracker_declarations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tracker_declarations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tracker_declarations_id_seq OWNED BY public.tracker_declarations.id;


--
-- Name: training_certificates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_certificates (
    id integer NOT NULL,
    certificate_number text,
    enrollment_id integer,
    employee_id integer,
    course_id integer,
    issue_date text,
    score integer
);


--
-- Name: training_certificates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_certificates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_certificates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_certificates_id_seq OWNED BY public.training_certificates.id;


--
-- Name: training_courses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_courses (
    id integer NOT NULL,
    course_code text,
    course_name text,
    description text,
    category text,
    duration_minutes integer,
    content text,
    video_url text,
    document_path text,
    presentation_path text,
    video_file_path text,
    external_link text,
    passing_score integer,
    is_mandatory integer,
    is_active integer,
    content_type text,
    created_by integer,
    created_at text
);


--
-- Name: training_courses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_courses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_courses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_courses_id_seq OWNED BY public.training_courses.id;


--
-- Name: training_enrollments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_enrollments (
    id integer NOT NULL,
    employee_id integer,
    course_id integer,
    course_name text,
    enrolled_date text,
    enrolled_by integer,
    due_date text,
    completion_date text,
    status text,
    score integer,
    video_progress integer,
    video_completed integer,
    created_at text
);


--
-- Name: training_enrollments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_enrollments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_enrollments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_enrollments_id_seq OWNED BY public.training_enrollments.id;


--
-- Name: training_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_questions (
    id integer NOT NULL,
    course_id integer,
    question_text text,
    question_text_ar text,
    options text,
    options_ar text,
    correct_answer text,
    points integer
);


--
-- Name: training_questions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_questions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_questions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_questions_id_seq OWNED BY public.training_questions.id;


--
-- Name: training_requirements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.training_requirements (
    id integer NOT NULL,
    role text,
    department text,
    course_id integer,
    policy_id integer,
    is_mandatory integer,
    deadline_days integer,
    created_at text
);


--
-- Name: training_requirements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.training_requirements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: training_requirements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.training_requirements_id_seq OWNED BY public.training_requirements.id;


--
-- Name: transaction_monitoring_alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transaction_monitoring_alerts (
    id integer NOT NULL,
    alert_reference text,
    customer_id integer,
    transaction_id integer,
    alert_date text,
    rule_triggered text,
    rule_description text,
    severity text,
    transaction_amount numeric,
    transaction_currency text,
    transaction_date text,
    transaction_type text,
    assigned_to integer,
    status text,
    investigation_notes text,
    customer_contacted integer,
    customer_explanation text,
    outcome text,
    outcome_date text,
    outcome_rationale text,
    sar_id integer,
    closed_by integer,
    closed_date text,
    created_at text
);


--
-- Name: transaction_monitoring_alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.transaction_monitoring_alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: transaction_monitoring_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.transaction_monitoring_alerts_id_seq OWNED BY public.transaction_monitoring_alerts.id;


--
-- Name: transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transactions (
    id integer NOT NULL,
    transaction_reference text,
    customer_id integer,
    transaction_date text,
    transaction_type text,
    amount numeric,
    currency text,
    counterparty_name text,
    counterparty_account text,
    counterparty_country text,
    purpose_of_transaction text,
    remittance_information text,
    sanctions_hit integer,
    sanctions_list text,
    pep_involvement integer,
    pep_name text,
    rule_triggered text,
    risk_score integer,
    alert_raised integer,
    alert_id text,
    alert_status text,
    investigation_notes text,
    investigated_by integer,
    investigation_date text,
    sar_filed integer,
    sar_id integer,
    created_at text,
    created_by integer
);


--
-- Name: transactions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.transactions_id_seq OWNED BY public.transactions.id;


--
-- Name: user_departments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_departments (
    user_id integer NOT NULL,
    department_id integer NOT NULL,
    created_at text
);


--
-- Name: user_module_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_module_permissions (
    user_id integer NOT NULL,
    module character varying(60) NOT NULL,
    level character varying(10) DEFAULT 'none'::character varying NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT user_module_permissions_level_check CHECK (((level)::text = ANY ((ARRAY['none'::character varying, 'view'::character varying, 'edit'::character varying, 'admin'::character varying])::text[])))
);


--
-- Name: user_org_scope_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_org_scope_rules (
    id integer NOT NULL,
    user_id integer NOT NULL,
    rule_type text NOT NULL,
    org_unit_id integer,
    root_unit_id integer,
    match_code text,
    match_type_id integer,
    is_exclusion boolean DEFAULT false NOT NULL,
    granted_by integer,
    granted_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT uosr_type_ck CHECK ((rule_type = ANY (ARRAY['subtree'::text, 'unit_only'::text, 'by_code'::text, 'by_type'::text])))
);


--
-- Name: user_org_scope_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_org_scope_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_org_scope_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_org_scope_rules_id_seq OWNED BY public.user_org_scope_rules.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email text,
    password_hash text,
    first_name text,
    last_name text,
    role text,
    employee_id text,
    department text,
    job_title text,
    manager_id integer,
    cms_access_level text,
    profile_picture text,
    is_active integer,
    last_login timestamp with time zone,
    created_at text,
    updated_at text,
    perm_governance text,
    perm_aml text,
    perm_policies text,
    perm_reports text,
    perm_pdpl text,
    perm_training text,
    perm_screening text,
    perm_config text,
    perm_cyber text,
    perm_consumer_protection text,
    perm_whistleblowing text,
    department_id integer,
    is_temporary integer,
    expires_at timestamp with time zone,
    perm_ghe text,
    perm_coi text,
    perm_cobec text,
    perm_merchant_kyc text,
    perm_tm text,
    perm_ekyc character varying(10) DEFAULT 'none'::character varying,
    perm_phishing character varying(10) DEFAULT 'none'::character varying NOT NULL,
    can_assign_training boolean DEFAULT false,
    mfa_secret text,
    mfa_enabled boolean DEFAULT false NOT NULL,
    mfa_backup_codes text,
    perm_risk_management character varying(10) DEFAULT 'none'::character varying,
    perm_internal_audit character varying(10) DEFAULT 'none'::character varying,
    perm_esg character varying(10) DEFAULT 'none'::character varying,
    perm_carbon character varying(10) DEFAULT 'none'::character varying,
    org_unit_id integer,
    authority_level text DEFAULT 'group'::text,
    authority_unit_id integer,
    perm_ongoing_screening character varying(10) DEFAULT 'none'::character varying,
    mfa_required_override boolean,
    mfa_enrolled_at timestamp without time zone,
    mfa_last_reset_at timestamp without time zone,
    mfa_last_reset_by integer,
    perm_academy character varying DEFAULT 'none'::character varying,
    perm_regcontrols character varying(10) DEFAULT 'none'::character varying,
    perm_prudential character varying(10) DEFAULT 'none'::character varying,
    perm_ai character varying(10) DEFAULT 'none'::character varying,
    failed_login_count integer DEFAULT 0 NOT NULL,
    locked_until timestamp with time zone,
    auth_version integer DEFAULT 0 NOT NULL
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: whistleblowing_anonymous_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.whistleblowing_anonymous_tokens (
    id integer NOT NULL,
    case_id integer,
    access_token text,
    access_code text,
    created_at text,
    last_accessed text,
    access_count integer,
    expires_at text,
    is_active integer
);


--
-- Name: whistleblowing_anonymous_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.whistleblowing_anonymous_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: whistleblowing_anonymous_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.whistleblowing_anonymous_tokens_id_seq OWNED BY public.whistleblowing_anonymous_tokens.id;


--
-- Name: whistleblowing_assignments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.whistleblowing_assignments (
    id integer NOT NULL,
    case_id integer,
    assigned_to integer,
    assigned_by integer,
    assigned_at text,
    assignment_note text,
    unassigned_at text,
    unassigned_by integer,
    action_type text DEFAULT 'assign'::text,
    previous_owner_id integer,
    from_org_unit_id integer,
    to_org_unit_id integer,
    assignment_reason text,
    comments text,
    status_at_assignment text,
    sla_due_at timestamp without time zone,
    is_current boolean DEFAULT true,
    assigned_at_ts timestamp without time zone
);


--
-- Name: whistleblowing_assignments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.whistleblowing_assignments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: whistleblowing_assignments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.whistleblowing_assignments_id_seq OWNED BY public.whistleblowing_assignments.id;


--
-- Name: whistleblowing_attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.whistleblowing_attachments (
    id integer NOT NULL,
    case_id integer,
    filename text,
    original_filename text,
    file_path text,
    file_size integer,
    file_type text,
    uploaded_by integer,
    uploaded_at text,
    is_encrypted integer,
    encryption_key text,
    description text
);


--
-- Name: whistleblowing_attachments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.whistleblowing_attachments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: whistleblowing_attachments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.whistleblowing_attachments_id_seq OWNED BY public.whistleblowing_attachments.id;


--
-- Name: whistleblowing_cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.whistleblowing_cases (
    id integer NOT NULL,
    case_number text,
    submitted_at text,
    is_anonymous integer,
    submitter_id integer,
    submitter_name text,
    submitter_email text,
    submitter_phone text,
    submitter_department text,
    incident_type text,
    incident_category text,
    severity text,
    incident_date text,
    incident_location text,
    title text,
    description text,
    evidence_description text,
    witnesses text,
    suspected_individuals text,
    status text,
    priority text,
    assigned_to integer,
    assigned_at text,
    reviewed_by integer,
    reviewed_at text,
    resolution_summary text,
    resolution_action text,
    resolved_at text,
    resolved_by integer,
    anonymous_code text,
    encryption_key text,
    is_confidential integer,
    requires_investigation integer,
    is_urgent integer,
    updated_at text
);


--
-- Name: whistleblowing_cases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.whistleblowing_cases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: whistleblowing_cases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.whistleblowing_cases_id_seq OWNED BY public.whistleblowing_cases.id;


--
-- Name: whistleblowing_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.whistleblowing_categories (
    id integer NOT NULL,
    category_code text,
    category_name_en text,
    category_name_ar text,
    parent_category_id integer,
    severity_default text,
    requires_immediate_action integer,
    description_en text,
    description_ar text,
    is_active integer,
    display_order integer
);


--
-- Name: whistleblowing_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.whistleblowing_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: whistleblowing_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.whistleblowing_categories_id_seq OWNED BY public.whistleblowing_categories.id;


--
-- Name: whistleblowing_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.whistleblowing_stats (
    id integer NOT NULL,
    stat_date text,
    total_cases integer,
    anonymous_cases integer,
    resolved_cases integer,
    avg_resolution_days double precision,
    cases_by_type text,
    cases_by_severity text,
    cases_by_status text
);


--
-- Name: whistleblowing_stats_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.whistleblowing_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: whistleblowing_stats_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.whistleblowing_stats_id_seq OWNED BY public.whistleblowing_stats.id;


--
-- Name: whistleblowing_updates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.whistleblowing_updates (
    id integer NOT NULL,
    case_id integer,
    update_type text,
    update_text text,
    old_value text,
    new_value text,
    created_by integer,
    created_at text,
    is_visible_to_submitter integer
);


--
-- Name: whistleblowing_updates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.whistleblowing_updates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: whistleblowing_updates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.whistleblowing_updates_id_seq OWNED BY public.whistleblowing_updates.id;


--
-- Name: academy_attempts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_attempts ALTER COLUMN id SET DEFAULT nextval('public.academy_attempts_id_seq'::regclass);


--
-- Name: academy_audit id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_audit ALTER COLUMN id SET DEFAULT nextval('public.academy_audit_id_seq'::regclass);


--
-- Name: academy_certificates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_certificates ALTER COLUMN id SET DEFAULT nextval('public.academy_certificates_id_seq'::regclass);


--
-- Name: academy_courses id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_courses ALTER COLUMN id SET DEFAULT nextval('public.academy_courses_id_seq'::regclass);


--
-- Name: academy_enrollments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_enrollments ALTER COLUMN id SET DEFAULT nextval('public.academy_enrollments_id_seq'::regclass);


--
-- Name: academy_learners id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_learners ALTER COLUMN id SET DEFAULT nextval('public.academy_learners_id_seq'::regclass);


--
-- Name: academy_lessons id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_lessons ALTER COLUMN id SET DEFAULT nextval('public.academy_lessons_id_seq'::regclass);


--
-- Name: academy_otp id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_otp ALTER COLUMN id SET DEFAULT nextval('public.academy_otp_id_seq'::regclass);


--
-- Name: academy_questions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_questions ALTER COLUMN id SET DEFAULT nextval('public.academy_questions_id_seq'::regclass);


--
-- Name: adverse_media_results id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.adverse_media_results ALTER COLUMN id SET DEFAULT nextval('public.adverse_media_results_id_seq'::regclass);


--
-- Name: ai_intake_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_intake_items ALTER COLUMN id SET DEFAULT nextval('public.ai_intake_items_id_seq'::regclass);


--
-- Name: ai_playbook_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_playbook_runs ALTER COLUMN id SET DEFAULT nextval('public.ai_playbook_runs_id_seq'::regclass);


--
-- Name: ai_playbook_steps id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_playbook_steps ALTER COLUMN id SET DEFAULT nextval('public.ai_playbook_steps_id_seq'::regclass);


--
-- Name: ai_suggestions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_suggestions ALTER COLUMN id SET DEFAULT nextval('public.ai_suggestions_id_seq'::regclass);


--
-- Name: aml_alerts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_alerts ALTER COLUMN id SET DEFAULT nextval('public.aml_alerts_id_seq'::regclass);


--
-- Name: aml_annual_reports id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_annual_reports ALTER COLUMN id SET DEFAULT nextval('public.aml_annual_reports_id_seq'::regclass);


--
-- Name: aml_key_roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_key_roles ALTER COLUMN id SET DEFAULT nextval('public.aml_key_roles_id_seq'::regclass);


--
-- Name: aml_monitoring_plans id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_monitoring_plans ALTER COLUMN id SET DEFAULT nextval('public.aml_monitoring_plans_id_seq'::regclass);


--
-- Name: aml_monitoring_reviews id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_monitoring_reviews ALTER COLUMN id SET DEFAULT nextval('public.aml_monitoring_reviews_id_seq'::regclass);


--
-- Name: aml_role_conflict_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_role_conflict_rules ALTER COLUMN id SET DEFAULT nextval('public.aml_role_conflict_rules_id_seq'::regclass);


--
-- Name: aml_unusual_transactions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_unusual_transactions ALTER COLUMN id SET DEFAULT nextval('public.aml_unusual_transactions_id_seq'::regclass);


--
-- Name: annual_audit_plans id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annual_audit_plans ALTER COLUMN id SET DEFAULT nextval('public.annual_audit_plans_id_seq'::regclass);


--
-- Name: api_audit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_audit_log ALTER COLUMN id SET DEFAULT nextval('public.api_audit_log_id_seq'::regclass);


--
-- Name: api_keys id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys ALTER COLUMN id SET DEFAULT nextval('public.api_keys_id_seq'::regclass);


--
-- Name: approval_workflow_stages id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_stages ALTER COLUMN id SET DEFAULT nextval('public.approval_workflow_stages_id_seq'::regclass);


--
-- Name: approval_workflows id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflows ALTER COLUMN id SET DEFAULT nextval('public.approval_workflows_id_seq'::regclass);


--
-- Name: audit_findings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_findings ALTER COLUMN id SET DEFAULT nextval('public.audit_findings_id_seq'::regclass);


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: audit_programs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_programs ALTER COLUMN id SET DEFAULT nextval('public.audit_programs_id_seq'::regclass);


--
-- Name: audit_projects id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_projects ALTER COLUMN id SET DEFAULT nextval('public.audit_projects_id_seq'::regclass);


--
-- Name: audit_team_members id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_team_members ALTER COLUMN id SET DEFAULT nextval('public.audit_team_members_id_seq'::regclass);


--
-- Name: audit_universe id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_universe ALTER COLUMN id SET DEFAULT nextval('public.audit_universe_id_seq'::regclass);


--
-- Name: audit_universe_risks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_universe_risks ALTER COLUMN id SET DEFAULT nextval('public.audit_universe_risks_id_seq'::regclass);


--
-- Name: audit_working_papers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_working_papers ALTER COLUMN id SET DEFAULT nextval('public.audit_working_papers_id_seq'::regclass);


--
-- Name: beneficial_owners id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beneficial_owners ALTER COLUMN id SET DEFAULT nextval('public.beneficial_owners_id_seq'::regclass);


--
-- Name: blacklist_bulk_imports id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blacklist_bulk_imports ALTER COLUMN id SET DEFAULT nextval('public.blacklist_bulk_imports_id_seq'::regclass);


--
-- Name: board_committees id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_committees ALTER COLUMN id SET DEFAULT nextval('public.board_committees_id_seq'::regclass);


--
-- Name: board_decisions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_decisions ALTER COLUMN id SET DEFAULT nextval('public.board_decisions_id_seq'::regclass);


--
-- Name: board_evaluations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_evaluations ALTER COLUMN id SET DEFAULT nextval('public.board_evaluations_id_seq'::regclass);


--
-- Name: board_meeting_attendance id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_meeting_attendance ALTER COLUMN id SET DEFAULT nextval('public.board_meeting_attendance_id_seq'::regclass);


--
-- Name: board_meetings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_meetings ALTER COLUMN id SET DEFAULT nextval('public.board_meetings_id_seq'::regclass);


--
-- Name: board_members id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_members ALTER COLUMN id SET DEFAULT nextval('public.board_members_id_seq'::regclass);


--
-- Name: board_members_v1 id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_members_v1 ALTER COLUMN id SET DEFAULT nextval('public.board_members_v1_id_seq'::regclass);


--
-- Name: board_roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_roles ALTER COLUMN id SET DEFAULT nextval('public.board_roles_id_seq'::regclass);


--
-- Name: board_skills_matrix id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_skills_matrix ALTER COLUMN id SET DEFAULT nextval('public.board_skills_matrix_id_seq'::regclass);


--
-- Name: board_training id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_training ALTER COLUMN id SET DEFAULT nextval('public.board_training_id_seq'::regclass);


--
-- Name: board_training_attendance id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_training_attendance ALTER COLUMN id SET DEFAULT nextval('public.board_training_attendance_id_seq'::regclass);


--
-- Name: breach_remediation_actions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.breach_remediation_actions ALTER COLUMN id SET DEFAULT nextval('public.breach_remediation_actions_id_seq'::regclass);


--
-- Name: carbon_activity_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_activity_entries ALTER COLUMN id SET DEFAULT nextval('public.carbon_activity_entries_id_seq'::regclass);


--
-- Name: carbon_emission_factors id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_emission_factors ALTER COLUMN id SET DEFAULT nextval('public.carbon_emission_factors_id_seq'::regclass);


--
-- Name: carbon_entities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_entities ALTER COLUMN id SET DEFAULT nextval('public.carbon_entities_id_seq'::regclass);


--
-- Name: carbon_financed_exposures id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_financed_exposures ALTER COLUMN id SET DEFAULT nextval('public.carbon_financed_exposures_id_seq'::regclass);


--
-- Name: carbon_initiatives id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_initiatives ALTER COLUMN id SET DEFAULT nextval('public.carbon_initiatives_id_seq'::regclass);


--
-- Name: carbon_offset_obligations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_offset_obligations ALTER COLUMN id SET DEFAULT nextval('public.carbon_offset_obligations_id_seq'::regclass);


--
-- Name: carbon_offset_purchases id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_offset_purchases ALTER COLUMN id SET DEFAULT nextval('public.carbon_offset_purchases_id_seq'::regclass);


--
-- Name: carbon_period_metrics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_period_metrics ALTER COLUMN id SET DEFAULT nextval('public.carbon_period_metrics_id_seq'::regclass);


--
-- Name: carbon_period_workflow id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_period_workflow ALTER COLUMN id SET DEFAULT nextval('public.carbon_period_workflow_id_seq'::regclass);


--
-- Name: carbon_scope_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_scope_config ALTER COLUMN id SET DEFAULT nextval('public.carbon_scope_config_id_seq'::regclass);


--
-- Name: carbon_sites id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_sites ALTER COLUMN id SET DEFAULT nextval('public.carbon_sites_id_seq'::regclass);


--
-- Name: carbon_targets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_targets ALTER COLUMN id SET DEFAULT nextval('public.carbon_targets_id_seq'::regclass);


--
-- Name: carbon_workflow_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_workflow_events ALTER COLUMN id SET DEFAULT nextval('public.carbon_workflow_events_id_seq'::regclass);


--
-- Name: case_reminders id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_reminders ALTER COLUMN id SET DEFAULT nextval('public.case_reminders_id_seq'::regclass);


--
-- Name: cases id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases ALTER COLUMN id SET DEFAULT nextval('public.cases_id_seq'::regclass);


--
-- Name: cdd_documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cdd_documents ALTER COLUMN id SET DEFAULT nextval('public.cdd_documents_id_seq'::regclass);


--
-- Name: cdd_reviews id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cdd_reviews ALTER COLUMN id SET DEFAULT nextval('public.cdd_reviews_id_seq'::regclass);


--
-- Name: cdd_risk_factors id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cdd_risk_factors ALTER COLUMN id SET DEFAULT nextval('public.cdd_risk_factors_id_seq'::regclass);


--
-- Name: cobec_declarations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cobec_declarations ALTER COLUMN id SET DEFAULT nextval('public.cobec_declarations_id_seq'::regclass);


--
-- Name: coi_campaign_employees id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_campaign_employees ALTER COLUMN id SET DEFAULT nextval('public.coi_campaign_employees_id_seq'::regclass);


--
-- Name: coi_campaigns id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_campaigns ALTER COLUMN id SET DEFAULT nextval('public.coi_campaigns_id_seq'::regclass);


--
-- Name: coi_declaration_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_declaration_history ALTER COLUMN id SET DEFAULT nextval('public.coi_declaration_history_id_seq'::regclass);


--
-- Name: coi_declarations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_declarations ALTER COLUMN id SET DEFAULT nextval('public.coi_declarations_id_seq'::regclass);


--
-- Name: coi_disclosures id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_disclosures ALTER COLUMN id SET DEFAULT nextval('public.coi_disclosures_id_seq'::regclass);


--
-- Name: coi_mitigation_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_mitigation_history ALTER COLUMN id SET DEFAULT nextval('public.coi_mitigation_history_id_seq'::regclass);


--
-- Name: coi_mitigation_plans id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_mitigation_plans ALTER COLUMN id SET DEFAULT nextval('public.coi_mitigation_plans_id_seq'::regclass);


--
-- Name: committee_meetings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_meetings ALTER COLUMN id SET DEFAULT nextval('public.committee_meetings_id_seq'::regclass);


--
-- Name: committee_members id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_members ALTER COLUMN id SET DEFAULT nextval('public.committee_members_id_seq'::regclass);


--
-- Name: committee_memberships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_memberships ALTER COLUMN id SET DEFAULT nextval('public.committee_memberships_id_seq'::regclass);


--
-- Name: committees id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committees ALTER COLUMN id SET DEFAULT nextval('public.committees_id_seq'::regclass);


--
-- Name: complaint_activity_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.complaint_activity_log ALTER COLUMN id SET DEFAULT nextval('public.complaint_activity_log_id_seq'::regclass);


--
-- Name: complaint_categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.complaint_categories ALTER COLUMN id SET DEFAULT nextval('public.complaint_categories_id_seq'::regclass);


--
-- Name: complaint_documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.complaint_documents ALTER COLUMN id SET DEFAULT nextval('public.complaint_documents_id_seq'::regclass);


--
-- Name: compliance_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compliance_events ALTER COLUMN id SET DEFAULT nextval('public.compliance_events_id_seq'::regclass);


--
-- Name: conduct_declarations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conduct_declarations ALTER COLUMN id SET DEFAULT nextval('public.conduct_declarations_id_seq'::regclass);


--
-- Name: confirmed_matches id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confirmed_matches ALTER COLUMN id SET DEFAULT nextval('public.confirmed_matches_id_seq'::regclass);


--
-- Name: conflict_of_interest id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conflict_of_interest ALTER COLUMN id SET DEFAULT nextval('public.conflict_of_interest_id_seq'::regclass);


--
-- Name: consent_purposes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consent_purposes ALTER COLUMN id SET DEFAULT nextval('public.consent_purposes_id_seq'::regclass);


--
-- Name: consents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consents ALTER COLUMN id SET DEFAULT nextval('public.consents_id_seq'::regclass);


--
-- Name: consumer_complaints id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumer_complaints ALTER COLUMN id SET DEFAULT nextval('public.consumer_complaints_id_seq'::regclass);


--
-- Name: control_test_results id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.control_test_results ALTER COLUMN id SET DEFAULT nextval('public.control_test_results_id_seq'::regclass);


--
-- Name: controls id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.controls ALTER COLUMN id SET DEFAULT nextval('public.controls_id_seq'::regclass);


--
-- Name: customer_complaints id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_complaints ALTER COLUMN id SET DEFAULT nextval('public.customer_complaints_id_seq'::regclass);


--
-- Name: customer_consents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_consents ALTER COLUMN id SET DEFAULT nextval('public.customer_consents_id_seq'::regclass);


--
-- Name: customer_risk_scores id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_risk_scores ALTER COLUMN id SET DEFAULT nextval('public.customer_risk_scores_id_seq'::regclass);


--
-- Name: customers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers ALTER COLUMN id SET DEFAULT nextval('public.customers_id_seq'::regclass);


--
-- Name: cy_assessments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_assessments ALTER COLUMN id SET DEFAULT nextval('public.cy_assessments_id_seq'::regclass);


--
-- Name: cy_backups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_backups ALTER COLUMN id SET DEFAULT nextval('public.cy_backups_id_seq'::regclass);


--
-- Name: cy_bcp_sites id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_bcp_sites ALTER COLUMN id SET DEFAULT nextval('public.cy_bcp_sites_id_seq'::regclass);


--
-- Name: cy_domains id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_domains ALTER COLUMN id SET DEFAULT nextval('public.cy_domains_id_seq'::regclass);


--
-- Name: cy_dr_tests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_dr_tests ALTER COLUMN id SET DEFAULT nextval('public.cy_dr_tests_id_seq'::regclass);


--
-- Name: cy_integrations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_integrations ALTER COLUMN id SET DEFAULT nextval('public.cy_integrations_id_seq'::regclass);


--
-- Name: cy_maturity_assessments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_maturity_assessments ALTER COLUMN id SET DEFAULT nextval('public.cy_maturity_assessments_id_seq'::regclass);


--
-- Name: cy_security_assets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_security_assets ALTER COLUMN id SET DEFAULT nextval('public.cy_security_assets_id_seq'::regclass);


--
-- Name: cyber_incidents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cyber_incidents ALTER COLUMN id SET DEFAULT nextval('public.cyber_incidents_id_seq'::regclass);


--
-- Name: cybersecurity_incidents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cybersecurity_incidents ALTER COLUMN id SET DEFAULT nextval('public.cybersecurity_incidents_id_seq'::regclass);


--
-- Name: data_breaches id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_breaches ALTER COLUMN id SET DEFAULT nextval('public.data_breaches_id_seq'::regclass);


--
-- Name: data_processing_activities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_processing_activities ALTER COLUMN id SET DEFAULT nextval('public.data_processing_activities_id_seq'::regclass);


--
-- Name: data_source_urls id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_source_urls ALTER COLUMN id SET DEFAULT nextval('public.data_source_urls_id_seq'::regclass);


--
-- Name: data_subject_requests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_subject_requests ALTER COLUMN id SET DEFAULT nextval('public.data_subject_requests_id_seq'::regclass);


--
-- Name: data_update_audit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_update_audit_log ALTER COLUMN id SET DEFAULT nextval('public.data_update_audit_log_id_seq'::regclass);


--
-- Name: declaration_campaign_targets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.declaration_campaign_targets ALTER COLUMN id SET DEFAULT nextval('public.declaration_campaign_targets_id_seq'::regclass);


--
-- Name: declaration_campaigns id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.declaration_campaigns ALTER COLUMN id SET DEFAULT nextval('public.declaration_campaigns_id_seq'::regclass);


--
-- Name: departments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments ALTER COLUMN id SET DEFAULT nextval('public.departments_id_seq'::regclass);


--
-- Name: document_approvals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_approvals ALTER COLUMN id SET DEFAULT nextval('public.document_approvals_id_seq'::regclass);


--
-- Name: document_types id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_types ALTER COLUMN id SET DEFAULT nextval('public.document_types_id_seq'::regclass);


--
-- Name: dpias id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dpias ALTER COLUMN id SET DEFAULT nextval('public.dpias_id_seq'::regclass);


--
-- Name: dpo_activities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dpo_activities ALTER COLUMN id SET DEFAULT nextval('public.dpo_activities_id_seq'::regclass);


--
-- Name: dpo_appointments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dpo_appointments ALTER COLUMN id SET DEFAULT nextval('public.dpo_appointments_id_seq'::regclass);


--
-- Name: dsr_timeline id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dsr_timeline ALTER COLUMN id SET DEFAULT nextval('public.dsr_timeline_id_seq'::regclass);


--
-- Name: edd_cases id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.edd_cases ALTER COLUMN id SET DEFAULT nextval('public.edd_cases_id_seq'::regclass);


--
-- Name: ekyc_audit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_audit_log ALTER COLUMN id SET DEFAULT nextval('public.ekyc_audit_log_id_seq'::regclass);


--
-- Name: ekyc_document id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_document ALTER COLUMN id SET DEFAULT nextval('public.ekyc_document_id_seq'::regclass);


--
-- Name: ekyc_result id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_result ALTER COLUMN id SET DEFAULT nextval('public.ekyc_result_id_seq'::regclass);


--
-- Name: ekyc_session id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_session ALTER COLUMN id SET DEFAULT nextval('public.ekyc_session_id_seq'::regclass);


--
-- Name: email_templates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_templates ALTER COLUMN id SET DEFAULT nextval('public.email_templates_id_seq'::regclass);


--
-- Name: employee_screenings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_screenings ALTER COLUMN id SET DEFAULT nextval('public.employee_screenings_id_seq'::regclass);


--
-- Name: esg_disclosure_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_disclosure_items ALTER COLUMN id SET DEFAULT nextval('public.esg_disclosure_items_id_seq'::regclass);


--
-- Name: esg_frameworks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_frameworks ALTER COLUMN id SET DEFAULT nextval('public.esg_frameworks_id_seq'::regclass);


--
-- Name: esg_indicator_responses id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_indicator_responses ALTER COLUMN id SET DEFAULT nextval('public.esg_indicator_responses_id_seq'::regclass);


--
-- Name: esg_indicators id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_indicators ALTER COLUMN id SET DEFAULT nextval('public.esg_indicators_id_seq'::regclass);


--
-- Name: esg_materiality_scores id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_materiality_scores ALTER COLUMN id SET DEFAULT nextval('public.esg_materiality_scores_id_seq'::regclass);


--
-- Name: esg_materiality_topics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_materiality_topics ALTER COLUMN id SET DEFAULT nextval('public.esg_materiality_topics_id_seq'::regclass);


--
-- Name: esg_pillars id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_pillars ALTER COLUMN id SET DEFAULT nextval('public.esg_pillars_id_seq'::regclass);


--
-- Name: esg_reporting_periods id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_reporting_periods ALTER COLUMN id SET DEFAULT nextval('public.esg_reporting_periods_id_seq'::regclass);


--
-- Name: esg_sites id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_sites ALTER COLUMN id SET DEFAULT nextval('public.esg_sites_id_seq'::regclass);


--
-- Name: event_routing_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_routing_rules ALTER COLUMN id SET DEFAULT nextval('public.event_routing_rules_id_seq'::regclass);


--
-- Name: fit_proper_assessments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fit_proper_assessments ALTER COLUMN id SET DEFAULT nextval('public.fit_proper_assessments_id_seq'::regclass);


--
-- Name: fra_verifiers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fra_verifiers ALTER COLUMN id SET DEFAULT nextval('public.fra_verifiers_id_seq'::regclass);


--
-- Name: generic_attachments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.generic_attachments ALTER COLUMN id SET DEFAULT nextval('public.generic_attachments_id_seq'::regclass);


--
-- Name: ghe_approval_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ghe_approval_history ALTER COLUMN id SET DEFAULT nextval('public.ghe_approval_history_id_seq'::regclass);


--
-- Name: ghe_declaration_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ghe_declaration_history ALTER COLUMN id SET DEFAULT nextval('public.ghe_declaration_history_id_seq'::regclass);


--
-- Name: ghe_declarations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ghe_declarations ALTER COLUMN id SET DEFAULT nextval('public.ghe_declarations_id_seq'::regclass);


--
-- Name: ghe_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ghe_records ALTER COLUMN id SET DEFAULT nextval('public.ghe_records_id_seq'::regclass);


--
-- Name: governance_compliance_tracker id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.governance_compliance_tracker ALTER COLUMN id SET DEFAULT nextval('public.governance_compliance_tracker_id_seq'::regclass);


--
-- Name: high_risk_countries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.high_risk_countries ALTER COLUMN id SET DEFAULT nextval('public.high_risk_countries_id_seq'::regclass);


--
-- Name: incident_response_team id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incident_response_team ALTER COLUMN id SET DEFAULT nextval('public.incident_response_team_id_seq'::regclass);


--
-- Name: incident_timeline id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incident_timeline ALTER COLUMN id SET DEFAULT nextval('public.incident_timeline_id_seq'::regclass);


--
-- Name: independence_declarations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.independence_declarations ALTER COLUMN id SET DEFAULT nextval('public.independence_declarations_id_seq'::regclass);


--
-- Name: internal_blacklist id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.internal_blacklist ALTER COLUMN id SET DEFAULT nextval('public.internal_blacklist_id_seq'::regclass);


--
-- Name: internal_blacklist_audit id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.internal_blacklist_audit ALTER COLUMN id SET DEFAULT nextval('public.internal_blacklist_audit_id_seq'::regclass);


--
-- Name: internal_pep id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.internal_pep ALTER COLUMN id SET DEFAULT nextval('public.internal_pep_id_seq'::regclass);


--
-- Name: internal_pep_audit id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.internal_pep_audit ALTER COLUMN id SET DEFAULT nextval('public.internal_pep_audit_id_seq'::regclass);


--
-- Name: kri_measurements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kri_measurements ALTER COLUMN id SET DEFAULT nextval('public.kri_measurements_id_seq'::regclass);


--
-- Name: kris id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kris ALTER COLUMN id SET DEFAULT nextval('public.kris_id_seq'::regclass);


--
-- Name: kyc_beneficial_owners id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_beneficial_owners ALTER COLUMN id SET DEFAULT nextval('public.kyc_beneficial_owners_id_seq'::regclass);


--
-- Name: kyc_bo_declarations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_bo_declarations ALTER COLUMN id SET DEFAULT nextval('public.kyc_bo_declarations_id_seq'::regclass);


--
-- Name: kyc_risk_factors id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_risk_factors ALTER COLUMN id SET DEFAULT nextval('public.kyc_risk_factors_id_seq'::regclass);


--
-- Name: kyc_risk_ratings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_risk_ratings ALTER COLUMN id SET DEFAULT nextval('public.kyc_risk_ratings_id_seq'::regclass);


--
-- Name: ln_clients id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_clients ALTER COLUMN id SET DEFAULT nextval('public.ln_clients_id_seq'::regclass);


--
-- Name: ln_contracts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_contracts ALTER COLUMN id SET DEFAULT nextval('public.ln_contracts_id_seq'::regclass);


--
-- Name: ln_credit_studies id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_credit_studies ALTER COLUMN id SET DEFAULT nextval('public.ln_credit_studies_id_seq'::regclass);


--
-- Name: ln_documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_documents ALTER COLUMN id SET DEFAULT nextval('public.ln_documents_id_seq'::regclass);


--
-- Name: ln_early_repayments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_early_repayments ALTER COLUMN id SET DEFAULT nextval('public.ln_early_repayments_id_seq'::regclass);


--
-- Name: ln_exceptions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_exceptions ALTER COLUMN id SET DEFAULT nextval('public.ln_exceptions_id_seq'::regclass);


--
-- Name: ln_import_batches id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_import_batches ALTER COLUMN id SET DEFAULT nextval('public.ln_import_batches_id_seq'::regclass);


--
-- Name: ln_instalments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_instalments ALTER COLUMN id SET DEFAULT nextval('public.ln_instalments_id_seq'::regclass);


--
-- Name: ln_loans id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_loans ALTER COLUMN id SET DEFAULT nextval('public.ln_loans_id_seq'::regclass);


--
-- Name: ln_par_snapshots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_par_snapshots ALTER COLUMN id SET DEFAULT nextval('public.ln_par_snapshots_id_seq'::regclass);


--
-- Name: ln_products id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_products ALTER COLUMN id SET DEFAULT nextval('public.ln_products_id_seq'::regclass);


--
-- Name: ln_qa_flags id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_qa_flags ALTER COLUMN id SET DEFAULT nextval('public.ln_qa_flags_id_seq'::regclass);


--
-- Name: ln_reschedulings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_reschedulings ALTER COLUMN id SET DEFAULT nextval('public.ln_reschedulings_id_seq'::regclass);


--
-- Name: ln_transfers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_transfers ALTER COLUMN id SET DEFAULT nextval('public.ln_transfers_id_seq'::regclass);


--
-- Name: ln_visits id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_visits ALTER COLUMN id SET DEFAULT nextval('public.ln_visits_id_seq'::regclass);


--
-- Name: meeting_action_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_action_items ALTER COLUMN id SET DEFAULT nextval('public.meeting_action_items_id_seq'::regclass);


--
-- Name: meeting_agenda_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_agenda_items ALTER COLUMN id SET DEFAULT nextval('public.meeting_agenda_items_id_seq'::regclass);


--
-- Name: meeting_attendance id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_attendance ALTER COLUMN id SET DEFAULT nextval('public.meeting_attendance_id_seq'::regclass);


--
-- Name: merchant_kyc_documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merchant_kyc_documents ALTER COLUMN id SET DEFAULT nextval('public.merchant_kyc_documents_id_seq'::regclass);


--
-- Name: merchants id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merchants ALTER COLUMN id SET DEFAULT nextval('public.merchants_id_seq'::regclass);


--
-- Name: mfa_audit id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mfa_audit ALTER COLUMN id SET DEFAULT nextval('public.mfa_audit_id_seq'::regclass);


--
-- Name: notifications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications ALTER COLUMN id SET DEFAULT nextval('public.notifications_id_seq'::regclass);


--
-- Name: numbering_sequences id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.numbering_sequences ALTER COLUMN id SET DEFAULT nextval('public.numbering_sequences_id_seq'::regclass);


--
-- Name: ongoing_screening_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_config ALTER COLUMN id SET DEFAULT nextval('public.ongoing_screening_config_id_seq'::regclass);


--
-- Name: ongoing_screening_findings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_findings ALTER COLUMN id SET DEFAULT nextval('public.ongoing_screening_findings_id_seq'::regclass);


--
-- Name: ongoing_screening_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_runs ALTER COLUMN id SET DEFAULT nextval('public.ongoing_screening_runs_id_seq'::regclass);


--
-- Name: org_unit_types id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_unit_types ALTER COLUMN id SET DEFAULT nextval('public.org_unit_types_id_seq'::regclass);


--
-- Name: org_units id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_units ALTER COLUMN id SET DEFAULT nextval('public.org_units_id_seq'::regclass);


--
-- Name: parties id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parties ALTER COLUMN id SET DEFAULT nextval('public.parties_id_seq'::regclass);


--
-- Name: party_links id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.party_links ALTER COLUMN id SET DEFAULT nextval('public.party_links_id_seq'::regclass);


--
-- Name: pep_aliases id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_aliases ALTER COLUMN id SET DEFAULT nextval('public.pep_aliases_id_seq'::regclass);


--
-- Name: pep_corporate_links id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_corporate_links ALTER COLUMN id SET DEFAULT nextval('public.pep_corporate_links_id_seq'::regclass);


--
-- Name: pep_database id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_database ALTER COLUMN id SET DEFAULT nextval('public.pep_database_id_seq'::regclass);


--
-- Name: pep_duplicate_candidates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_duplicate_candidates ALTER COLUMN id SET DEFAULT nextval('public.pep_duplicate_candidates_id_seq'::regclass);


--
-- Name: pep_master id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_master ALTER COLUMN id SET DEFAULT nextval('public.pep_master_id_seq'::regclass);


--
-- Name: pep_matches id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_matches ALTER COLUMN id SET DEFAULT nextval('public.pep_matches_id_seq'::regclass);


--
-- Name: pep_positions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_positions ALTER COLUMN id SET DEFAULT nextval('public.pep_positions_id_seq'::regclass);


--
-- Name: pep_screenings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_screenings ALTER COLUMN id SET DEFAULT nextval('public.pep_screenings_id_seq'::regclass);


--
-- Name: pep_sources id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_sources ALTER COLUMN id SET DEFAULT nextval('public.pep_sources_id_seq'::regclass);


--
-- Name: pep_update_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_update_logs ALTER COLUMN id SET DEFAULT nextval('public.pep_update_logs_id_seq'::regclass);


--
-- Name: phishing_campaigns id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phishing_campaigns ALTER COLUMN id SET DEFAULT nextval('public.phishing_campaigns_id_seq'::regclass);


--
-- Name: phishing_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phishing_events ALTER COLUMN id SET DEFAULT nextval('public.phishing_events_id_seq'::regclass);


--
-- Name: phishing_recipients id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phishing_recipients ALTER COLUMN id SET DEFAULT nextval('public.phishing_recipients_id_seq'::regclass);


--
-- Name: policies id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policies ALTER COLUMN id SET DEFAULT nextval('public.policies_id_seq'::regclass);


--
-- Name: policy_acknowledgments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_acknowledgments ALTER COLUMN id SET DEFAULT nextval('public.policy_acknowledgments_id_seq'::regclass);


--
-- Name: policy_applicability id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_applicability ALTER COLUMN id SET DEFAULT nextval('public.policy_applicability_id_seq'::regclass);


--
-- Name: policy_attachments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_attachments ALTER COLUMN id SET DEFAULT nextval('public.policy_attachments_id_seq'::regclass);


--
-- Name: policy_board_approvals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_board_approvals ALTER COLUMN id SET DEFAULT nextval('public.policy_board_approvals_id_seq'::regclass);


--
-- Name: policy_categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_categories ALTER COLUMN id SET DEFAULT nextval('public.policy_categories_id_seq'::regclass);


--
-- Name: policy_review_workflow id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_review_workflow ALTER COLUMN id SET DEFAULT nextval('public.policy_review_workflow_id_seq'::regclass);


--
-- Name: policy_versions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_versions ALTER COLUMN id SET DEFAULT nextval('public.policy_versions_id_seq'::regclass);


--
-- Name: pr_branches id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_branches ALTER COLUMN id SET DEFAULT nextval('public.pr_branches_id_seq'::regclass);


--
-- Name: pr_capital_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_capital_events ALTER COLUMN id SET DEFAULT nextval('public.pr_capital_events_id_seq'::regclass);


--
-- Name: pr_deadline_extensions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_deadline_extensions ALTER COLUMN id SET DEFAULT nextval('public.pr_deadline_extensions_id_seq'::regclass);


--
-- Name: pr_deadlines id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_deadlines ALTER COLUMN id SET DEFAULT nextval('public.pr_deadlines_id_seq'::regclass);


--
-- Name: pr_documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_documents ALTER COLUMN id SET DEFAULT nextval('public.pr_documents_id_seq'::regclass);


--
-- Name: pr_facilities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_facilities ALTER COLUMN id SET DEFAULT nextval('public.pr_facilities_id_seq'::regclass);


--
-- Name: pr_financial_periods id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_financial_periods ALTER COLUMN id SET DEFAULT nextval('public.pr_financial_periods_id_seq'::regclass);


--
-- Name: pr_key_functions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_key_functions ALTER COLUMN id SET DEFAULT nextval('public.pr_key_functions_id_seq'::regclass);


--
-- Name: pr_related_parties id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_related_parties ALTER COLUMN id SET DEFAULT nextval('public.pr_related_parties_id_seq'::regclass);


--
-- Name: pr_rp_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_rp_items ALTER COLUMN id SET DEFAULT nextval('public.pr_rp_items_id_seq'::regclass);


--
-- Name: pr_studies id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_studies ALTER COLUMN id SET DEFAULT nextval('public.pr_studies_id_seq'::regclass);


--
-- Name: rc_alerts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_alerts ALTER COLUMN id SET DEFAULT nextval('public.rc_alerts_id_seq'::regclass);


--
-- Name: rc_control_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_control_runs ALTER COLUMN id SET DEFAULT nextval('public.rc_control_runs_id_seq'::regclass);


--
-- Name: rc_controls id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_controls ALTER COLUMN id SET DEFAULT nextval('public.rc_controls_id_seq'::regclass);


--
-- Name: rc_corrective_actions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_corrective_actions ALTER COLUMN id SET DEFAULT nextval('public.rc_corrective_actions_id_seq'::regclass);


--
-- Name: rc_evidence id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_evidence ALTER COLUMN id SET DEFAULT nextval('public.rc_evidence_id_seq'::regclass);


--
-- Name: rc_finding_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_finding_events ALTER COLUMN id SET DEFAULT nextval('public.rc_finding_events_id_seq'::regclass);


--
-- Name: rc_findings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_findings ALTER COLUMN id SET DEFAULT nextval('public.rc_findings_id_seq'::regclass);


--
-- Name: rc_frameworks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_frameworks ALTER COLUMN id SET DEFAULT nextval('public.rc_frameworks_id_seq'::regclass);


--
-- Name: rc_parameter_changes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameter_changes ALTER COLUMN id SET DEFAULT nextval('public.rc_parameter_changes_id_seq'::regclass);


--
-- Name: rc_parameters id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameters ALTER COLUMN id SET DEFAULT nextval('public.rc_parameters_id_seq'::regclass);


--
-- Name: rc_readiness_snapshots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_readiness_snapshots ALTER COLUMN id SET DEFAULT nextval('public.rc_readiness_snapshots_id_seq'::regclass);


--
-- Name: rc_requirements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_requirements ALTER COLUMN id SET DEFAULT nextval('public.rc_requirements_id_seq'::regclass);


--
-- Name: red_flags id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.red_flags ALTER COLUMN id SET DEFAULT nextval('public.red_flags_id_seq'::regclass);


--
-- Name: regulators id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regulators ALTER COLUMN id SET DEFAULT nextval('public.regulators_id_seq'::regclass);


--
-- Name: regulatory_report_submissions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regulatory_report_submissions ALTER COLUMN id SET DEFAULT nextval('public.regulatory_report_submissions_id_seq'::regclass);


--
-- Name: regulatory_reports id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regulatory_reports ALTER COLUMN id SET DEFAULT nextval('public.regulatory_reports_id_seq'::regclass);


--
-- Name: reminder_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reminder_log ALTER COLUMN id SET DEFAULT nextval('public.reminder_log_id_seq'::regclass);


--
-- Name: required_policies id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.required_policies ALTER COLUMN id SET DEFAULT nextval('public.required_policies_id_seq'::regclass);


--
-- Name: risk_appetite_statements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_appetite_statements ALTER COLUMN id SET DEFAULT nextval('public.risk_appetite_statements_id_seq'::regclass);


--
-- Name: risk_categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_categories ALTER COLUMN id SET DEFAULT nextval('public.risk_categories_id_seq'::regclass);


--
-- Name: risk_controls id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_controls ALTER COLUMN id SET DEFAULT nextval('public.risk_controls_id_seq'::regclass);


--
-- Name: risk_register id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_register ALTER COLUMN id SET DEFAULT nextval('public.risk_register_id_seq'::regclass);


--
-- Name: risk_reviews id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_reviews ALTER COLUMN id SET DEFAULT nextval('public.risk_reviews_id_seq'::regclass);


--
-- Name: risk_score_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_score_history ALTER COLUMN id SET DEFAULT nextval('public.risk_score_history_id_seq'::regclass);


--
-- Name: risk_scoring_bands id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_scoring_bands ALTER COLUMN id SET DEFAULT nextval('public.risk_scoring_bands_id_seq'::regclass);


--
-- Name: risk_source_links id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_source_links ALTER COLUMN id SET DEFAULT nextval('public.risk_source_links_id_seq'::regclass);


--
-- Name: risk_treatments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_treatments ALTER COLUMN id SET DEFAULT nextval('public.risk_treatments_id_seq'::regclass);


--
-- Name: risks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risks ALTER COLUMN id SET DEFAULT nextval('public.risks_id_seq'::regclass);


--
-- Name: sanctions_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sanctions_entries ALTER COLUMN id SET DEFAULT nextval('public.sanctions_entries_id_seq'::regclass);


--
-- Name: sanctions_lists id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sanctions_lists ALTER COLUMN id SET DEFAULT nextval('public.sanctions_lists_id_seq'::regclass);


--
-- Name: sanctions_matches id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sanctions_matches ALTER COLUMN id SET DEFAULT nextval('public.sanctions_matches_id_seq'::regclass);


--
-- Name: sanctions_screening_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sanctions_screening_log ALTER COLUMN id SET DEFAULT nextval('public.sanctions_screening_log_id_seq'::regclass);


--
-- Name: sanctions_screenings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sanctions_screenings ALTER COLUMN id SET DEFAULT nextval('public.sanctions_screenings_id_seq'::regclass);


--
-- Name: sar_red_flags id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sar_red_flags ALTER COLUMN id SET DEFAULT nextval('public.sar_red_flags_id_seq'::regclass);


--
-- Name: sar_reports id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sar_reports ALTER COLUMN id SET DEFAULT nextval('public.sar_reports_id_seq'::regclass);


--
-- Name: screening_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_config ALTER COLUMN id SET DEFAULT nextval('public.screening_config_id_seq'::regclass);


--
-- Name: screening_data_sources id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_data_sources ALTER COLUMN id SET DEFAULT nextval('public.screening_data_sources_id_seq'::regclass);


--
-- Name: screening_delta_hits id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_delta_hits ALTER COLUMN id SET DEFAULT nextval('public.screening_delta_hits_id_seq'::regclass);


--
-- Name: screening_delta_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_delta_runs ALTER COLUMN id SET DEFAULT nextval('public.screening_delta_runs_id_seq'::regclass);


--
-- Name: screening_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_history ALTER COLUMN id SET DEFAULT nextval('public.screening_history_id_seq'::regclass);


--
-- Name: screening_list_update_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_list_update_log ALTER COLUMN id SET DEFAULT nextval('public.screening_list_update_log_id_seq'::regclass);


--
-- Name: screening_metrics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_metrics ALTER COLUMN id SET DEFAULT nextval('public.screening_metrics_id_seq'::regclass);


--
-- Name: screening_qa_cases id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_qa_cases ALTER COLUMN id SET DEFAULT nextval('public.screening_qa_cases_id_seq'::regclass);


--
-- Name: screening_qa_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_qa_runs ALTER COLUMN id SET DEFAULT nextval('public.screening_qa_runs_id_seq'::regclass);


--
-- Name: screening_quality_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_quality_runs ALTER COLUMN id SET DEFAULT nextval('public.screening_quality_runs_id_seq'::regclass);


--
-- Name: screening_queue id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_queue ALTER COLUMN id SET DEFAULT nextval('public.screening_queue_id_seq'::regclass);


--
-- Name: screening_results id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_results ALTER COLUMN id SET DEFAULT nextval('public.screening_results_id_seq'::regclass);


--
-- Name: screening_risk_criteria id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_risk_criteria ALTER COLUMN id SET DEFAULT nextval('public.screening_risk_criteria_id_seq'::regclass);


--
-- Name: screening_settings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_settings ALTER COLUMN id SET DEFAULT nextval('public.screening_settings_id_seq'::regclass);


--
-- Name: screening_update_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_update_log ALTER COLUMN id SET DEFAULT nextval('public.screening_update_log_id_seq'::regclass);


--
-- Name: screening_update_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_update_logs ALTER COLUMN id SET DEFAULT nextval('public.screening_update_logs_id_seq'::regclass);


--
-- Name: screening_watchlist id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_watchlist ALTER COLUMN id SET DEFAULT nextval('public.screening_watchlist_id_seq'::regclass);


--
-- Name: screening_whitelist id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_whitelist ALTER COLUMN id SET DEFAULT nextval('public.screening_whitelist_id_seq'::regclass);


--
-- Name: screening_whitelist_audit id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_whitelist_audit ALTER COLUMN id SET DEFAULT nextval('public.screening_whitelist_audit_id_seq'::regclass);


--
-- Name: screening_whitelist_matches id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_whitelist_matches ALTER COLUMN id SET DEFAULT nextval('public.screening_whitelist_matches_id_seq'::regclass);


--
-- Name: screening_workflow id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_workflow ALTER COLUMN id SET DEFAULT nextval('public.screening_workflow_id_seq'::regclass);


--
-- Name: str_report_templates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.str_report_templates ALTER COLUMN id SET DEFAULT nextval('public.str_report_templates_id_seq'::regclass);


--
-- Name: succession_plans id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.succession_plans ALTER COLUMN id SET DEFAULT nextval('public.succession_plans_id_seq'::regclass);


--
-- Name: suspicious_activities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.suspicious_activities ALTER COLUMN id SET DEFAULT nextval('public.suspicious_activities_id_seq'::regclass);


--
-- Name: three_lines_functions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.three_lines_functions ALTER COLUMN id SET DEFAULT nextval('public.three_lines_functions_id_seq'::regclass);


--
-- Name: three_lines_raci_matrix id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.three_lines_raci_matrix ALTER COLUMN id SET DEFAULT nextval('public.three_lines_raci_matrix_id_seq'::regclass);


--
-- Name: tm_alerts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tm_alerts ALTER COLUMN id SET DEFAULT nextval('public.tm_alerts_id_seq'::regclass);


--
-- Name: tm_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tm_rules ALTER COLUMN id SET DEFAULT nextval('public.tm_rules_id_seq'::regclass);


--
-- Name: tracker_declarations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tracker_declarations ALTER COLUMN id SET DEFAULT nextval('public.tracker_declarations_id_seq'::regclass);


--
-- Name: training_certificates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_certificates ALTER COLUMN id SET DEFAULT nextval('public.training_certificates_id_seq'::regclass);


--
-- Name: training_courses id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_courses ALTER COLUMN id SET DEFAULT nextval('public.training_courses_id_seq'::regclass);


--
-- Name: training_enrollments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_enrollments ALTER COLUMN id SET DEFAULT nextval('public.training_enrollments_id_seq'::regclass);


--
-- Name: training_questions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_questions ALTER COLUMN id SET DEFAULT nextval('public.training_questions_id_seq'::regclass);


--
-- Name: training_requirements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_requirements ALTER COLUMN id SET DEFAULT nextval('public.training_requirements_id_seq'::regclass);


--
-- Name: transaction_monitoring_alerts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction_monitoring_alerts ALTER COLUMN id SET DEFAULT nextval('public.transaction_monitoring_alerts_id_seq'::regclass);


--
-- Name: transactions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions ALTER COLUMN id SET DEFAULT nextval('public.transactions_id_seq'::regclass);


--
-- Name: user_org_scope_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_org_scope_rules ALTER COLUMN id SET DEFAULT nextval('public.user_org_scope_rules_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: whistleblowing_anonymous_tokens id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_anonymous_tokens ALTER COLUMN id SET DEFAULT nextval('public.whistleblowing_anonymous_tokens_id_seq'::regclass);


--
-- Name: whistleblowing_assignments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_assignments ALTER COLUMN id SET DEFAULT nextval('public.whistleblowing_assignments_id_seq'::regclass);


--
-- Name: whistleblowing_attachments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_attachments ALTER COLUMN id SET DEFAULT nextval('public.whistleblowing_attachments_id_seq'::regclass);


--
-- Name: whistleblowing_cases id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_cases ALTER COLUMN id SET DEFAULT nextval('public.whistleblowing_cases_id_seq'::regclass);


--
-- Name: whistleblowing_categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_categories ALTER COLUMN id SET DEFAULT nextval('public.whistleblowing_categories_id_seq'::regclass);


--
-- Name: whistleblowing_stats id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_stats ALTER COLUMN id SET DEFAULT nextval('public.whistleblowing_stats_id_seq'::regclass);


--
-- Name: whistleblowing_updates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_updates ALTER COLUMN id SET DEFAULT nextval('public.whistleblowing_updates_id_seq'::regclass);


--
-- Name: academy_attempts academy_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_attempts
    ADD CONSTRAINT academy_attempts_pkey PRIMARY KEY (id);


--
-- Name: academy_audit academy_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_audit
    ADD CONSTRAINT academy_audit_pkey PRIMARY KEY (id);


--
-- Name: academy_certificates academy_certificates_cert_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_certificates
    ADD CONSTRAINT academy_certificates_cert_number_key UNIQUE (cert_number);


--
-- Name: academy_certificates academy_certificates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_certificates
    ADD CONSTRAINT academy_certificates_pkey PRIMARY KEY (id);


--
-- Name: academy_courses academy_courses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_courses
    ADD CONSTRAINT academy_courses_pkey PRIMARY KEY (id);


--
-- Name: academy_courses academy_courses_provider_chk; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.academy_courses
    ADD CONSTRAINT academy_courses_provider_chk CHECK ((provider = ANY (ARRAY['integrys'::text, 'complynex'::text]))) NOT VALID;


--
-- Name: academy_courses academy_courses_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_courses
    ADD CONSTRAINT academy_courses_slug_key UNIQUE (slug);


--
-- Name: academy_enrollments academy_enrollments_learner_id_course_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_enrollments
    ADD CONSTRAINT academy_enrollments_learner_id_course_id_key UNIQUE (learner_id, course_id);


--
-- Name: academy_enrollments academy_enrollments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_enrollments
    ADD CONSTRAINT academy_enrollments_pkey PRIMARY KEY (id);


--
-- Name: academy_learners academy_learners_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_learners
    ADD CONSTRAINT academy_learners_pkey PRIMARY KEY (id);


--
-- Name: academy_lessons academy_lessons_course_id_position_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_lessons
    ADD CONSTRAINT academy_lessons_course_id_position_key UNIQUE (course_id, "position");


--
-- Name: academy_lessons academy_lessons_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_lessons
    ADD CONSTRAINT academy_lessons_pkey PRIMARY KEY (id);


--
-- Name: academy_otp academy_otp_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_otp
    ADD CONSTRAINT academy_otp_pkey PRIMARY KEY (id);


--
-- Name: academy_questions academy_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_questions
    ADD CONSTRAINT academy_questions_pkey PRIMARY KEY (id);


--
-- Name: academy_rejected_domains academy_rejected_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_rejected_domains
    ADD CONSTRAINT academy_rejected_domains_pkey PRIMARY KEY (domain, reason);


--
-- Name: academy_settings academy_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_settings
    ADD CONSTRAINT academy_settings_pkey PRIMARY KEY (key);


--
-- Name: academy_video_progress academy_video_progress_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_video_progress
    ADD CONSTRAINT academy_video_progress_pkey PRIMARY KEY (enrollment_id, lesson_id);


--
-- Name: adverse_media_results adverse_media_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.adverse_media_results
    ADD CONSTRAINT adverse_media_results_pkey PRIMARY KEY (id);


--
-- Name: ai_intake_items ai_intake_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_intake_items
    ADD CONSTRAINT ai_intake_items_pkey PRIMARY KEY (id);


--
-- Name: ai_intents ai_intents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_intents
    ADD CONSTRAINT ai_intents_pkey PRIMARY KEY (code);


--
-- Name: ai_jobs ai_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_jobs
    ADD CONSTRAINT ai_jobs_pkey PRIMARY KEY (id);


--
-- Name: ai_playbook_runs ai_playbook_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_playbook_runs
    ADD CONSTRAINT ai_playbook_runs_pkey PRIMARY KEY (id);


--
-- Name: ai_playbook_steps ai_playbook_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_playbook_steps
    ADD CONSTRAINT ai_playbook_steps_pkey PRIMARY KEY (id);


--
-- Name: ai_playbook_steps ai_playbook_steps_playbook_code_step_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_playbook_steps
    ADD CONSTRAINT ai_playbook_steps_playbook_code_step_key_key UNIQUE (playbook_code, step_key);


--
-- Name: ai_playbooks ai_playbooks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_playbooks
    ADD CONSTRAINT ai_playbooks_pkey PRIMARY KEY (code);


--
-- Name: ai_suggestions ai_suggestions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_suggestions
    ADD CONSTRAINT ai_suggestions_pkey PRIMARY KEY (id);


--
-- Name: aml_alerts aml_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_alerts
    ADD CONSTRAINT aml_alerts_pkey PRIMARY KEY (id);


--
-- Name: aml_annual_reports aml_annual_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_annual_reports
    ADD CONSTRAINT aml_annual_reports_pkey PRIMARY KEY (id);


--
-- Name: aml_annual_reports aml_annual_reports_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_annual_reports
    ADD CONSTRAINT aml_annual_reports_uniq UNIQUE (report_year, role_code);


--
-- Name: aml_key_roles aml_key_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_key_roles
    ADD CONSTRAINT aml_key_roles_pkey PRIMARY KEY (id);


--
-- Name: aml_monitoring_plans aml_monitoring_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_monitoring_plans
    ADD CONSTRAINT aml_monitoring_plans_pkey PRIMARY KEY (id);


--
-- Name: aml_monitoring_plans aml_monitoring_plans_plan_year_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_monitoring_plans
    ADD CONSTRAINT aml_monitoring_plans_plan_year_key UNIQUE (plan_year);


--
-- Name: aml_monitoring_reviews aml_monitoring_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_monitoring_reviews
    ADD CONSTRAINT aml_monitoring_reviews_pkey PRIMARY KEY (id);


--
-- Name: aml_role_conflict_rules aml_role_conflict_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_role_conflict_rules
    ADD CONSTRAINT aml_role_conflict_rules_pkey PRIMARY KEY (id);


--
-- Name: aml_role_conflict_rules aml_role_conflict_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_role_conflict_rules
    ADD CONSTRAINT aml_role_conflict_uniq UNIQUE (role_code, rule_type, keyword);


--
-- Name: aml_unusual_transactions aml_unusual_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_unusual_transactions
    ADD CONSTRAINT aml_unusual_transactions_pkey PRIMARY KEY (id);


--
-- Name: aml_unusual_transactions aml_unusual_transactions_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_unusual_transactions
    ADD CONSTRAINT aml_unusual_transactions_reference_key UNIQUE (reference);


--
-- Name: aml_unusual_transactions aml_unusual_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_unusual_transactions
    ADD CONSTRAINT aml_unusual_uniq UNIQUE (source_table, source_record_id, detection_rule);


--
-- Name: annual_audit_plans annual_audit_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annual_audit_plans
    ADD CONSTRAINT annual_audit_plans_pkey PRIMARY KEY (id);


--
-- Name: api_audit_log api_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_audit_log
    ADD CONSTRAINT api_audit_log_pkey PRIMARY KEY (id);


--
-- Name: api_keys api_keys_key_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_key_hash_key UNIQUE (key_hash);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: approval_workflow_stages approval_workflow_stages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_stages
    ADD CONSTRAINT approval_workflow_stages_pkey PRIMARY KEY (id);


--
-- Name: approval_workflows approval_workflows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflows
    ADD CONSTRAINT approval_workflows_pkey PRIMARY KEY (id);


--
-- Name: audit_findings audit_findings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_findings
    ADD CONSTRAINT audit_findings_pkey PRIMARY KEY (id);


--
-- Name: audit_findings audit_findings_project_id_finding_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_findings
    ADD CONSTRAINT audit_findings_project_id_finding_number_key UNIQUE (project_id, finding_number);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: audit_programs audit_programs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_programs
    ADD CONSTRAINT audit_programs_pkey PRIMARY KEY (id);


--
-- Name: audit_programs audit_programs_project_id_step_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_programs
    ADD CONSTRAINT audit_programs_project_id_step_number_key UNIQUE (project_id, step_number);


--
-- Name: audit_projects audit_projects_audit_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_projects
    ADD CONSTRAINT audit_projects_audit_number_key UNIQUE (audit_number);


--
-- Name: audit_projects audit_projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_projects
    ADD CONSTRAINT audit_projects_pkey PRIMARY KEY (id);


--
-- Name: audit_team_members audit_team_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_team_members
    ADD CONSTRAINT audit_team_members_pkey PRIMARY KEY (id);


--
-- Name: audit_team_members audit_team_members_project_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_team_members
    ADD CONSTRAINT audit_team_members_project_id_user_id_key UNIQUE (project_id, user_id);


--
-- Name: audit_universe audit_universe_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_universe
    ADD CONSTRAINT audit_universe_pkey PRIMARY KEY (id);


--
-- Name: audit_universe_risks audit_universe_risks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_universe_risks
    ADD CONSTRAINT audit_universe_risks_pkey PRIMARY KEY (id);


--
-- Name: audit_universe_risks audit_universe_risks_universe_id_risk_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_universe_risks
    ADD CONSTRAINT audit_universe_risks_universe_id_risk_id_key UNIQUE (universe_id, risk_id);


--
-- Name: audit_working_papers audit_working_papers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_working_papers
    ADD CONSTRAINT audit_working_papers_pkey PRIMARY KEY (id);


--
-- Name: beneficial_owners beneficial_owners_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.beneficial_owners
    ADD CONSTRAINT beneficial_owners_pkey PRIMARY KEY (id);


--
-- Name: blacklist_bulk_imports blacklist_bulk_imports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blacklist_bulk_imports
    ADD CONSTRAINT blacklist_bulk_imports_pkey PRIMARY KEY (id);


--
-- Name: board_committees board_committees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_committees
    ADD CONSTRAINT board_committees_pkey PRIMARY KEY (id);


--
-- Name: board_decisions board_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_decisions
    ADD CONSTRAINT board_decisions_pkey PRIMARY KEY (id);


--
-- Name: board_evaluations board_evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_evaluations
    ADD CONSTRAINT board_evaluations_pkey PRIMARY KEY (id);


--
-- Name: board_meeting_attendance board_meeting_attendance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_meeting_attendance
    ADD CONSTRAINT board_meeting_attendance_pkey PRIMARY KEY (id);


--
-- Name: board_meetings board_meetings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_meetings
    ADD CONSTRAINT board_meetings_pkey PRIMARY KEY (id);


--
-- Name: board_members board_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_members
    ADD CONSTRAINT board_members_pkey PRIMARY KEY (id);


--
-- Name: board_members_v1 board_members_v1_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_members_v1
    ADD CONSTRAINT board_members_v1_pkey PRIMARY KEY (id);


--
-- Name: board_roles board_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_roles
    ADD CONSTRAINT board_roles_pkey PRIMARY KEY (id);


--
-- Name: board_skills_matrix board_skills_matrix_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_skills_matrix
    ADD CONSTRAINT board_skills_matrix_pkey PRIMARY KEY (id);


--
-- Name: board_training_attendance board_training_attendance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_training_attendance
    ADD CONSTRAINT board_training_attendance_pkey PRIMARY KEY (id);


--
-- Name: board_training board_training_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_training
    ADD CONSTRAINT board_training_pkey PRIMARY KEY (id);


--
-- Name: breach_remediation_actions breach_remediation_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.breach_remediation_actions
    ADD CONSTRAINT breach_remediation_actions_pkey PRIMARY KEY (id);


--
-- Name: carbon_activity_entries carbon_activity_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_activity_entries
    ADD CONSTRAINT carbon_activity_entries_pkey PRIMARY KEY (id);


--
-- Name: carbon_emission_factors carbon_emission_factors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_emission_factors
    ADD CONSTRAINT carbon_emission_factors_pkey PRIMARY KEY (id);


--
-- Name: carbon_entities carbon_entities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_entities
    ADD CONSTRAINT carbon_entities_pkey PRIMARY KEY (id);


--
-- Name: carbon_financed_exposures carbon_financed_exposures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_financed_exposures
    ADD CONSTRAINT carbon_financed_exposures_pkey PRIMARY KEY (id);


--
-- Name: carbon_initiatives carbon_initiatives_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_initiatives
    ADD CONSTRAINT carbon_initiatives_pkey PRIMARY KEY (id);


--
-- Name: carbon_offset_obligations carbon_offset_obligations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_offset_obligations
    ADD CONSTRAINT carbon_offset_obligations_pkey PRIMARY KEY (id);


--
-- Name: carbon_offset_obligations carbon_offset_obligations_reporting_period_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_offset_obligations
    ADD CONSTRAINT carbon_offset_obligations_reporting_period_id_key UNIQUE (reporting_period_id);


--
-- Name: carbon_offset_purchases carbon_offset_purchases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_offset_purchases
    ADD CONSTRAINT carbon_offset_purchases_pkey PRIMARY KEY (id);


--
-- Name: carbon_period_metrics carbon_period_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_period_metrics
    ADD CONSTRAINT carbon_period_metrics_pkey PRIMARY KEY (id);


--
-- Name: carbon_period_workflow carbon_period_workflow_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_period_workflow
    ADD CONSTRAINT carbon_period_workflow_pkey PRIMARY KEY (id);


--
-- Name: carbon_scope_config carbon_scope_config_company_label_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_scope_config
    ADD CONSTRAINT carbon_scope_config_company_label_key UNIQUE (company_label);


--
-- Name: carbon_scope_config carbon_scope_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_scope_config
    ADD CONSTRAINT carbon_scope_config_pkey PRIMARY KEY (id);


--
-- Name: carbon_sites carbon_sites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_sites
    ADD CONSTRAINT carbon_sites_pkey PRIMARY KEY (id);


--
-- Name: carbon_targets carbon_targets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_targets
    ADD CONSTRAINT carbon_targets_pkey PRIMARY KEY (id);


--
-- Name: carbon_workflow_events carbon_workflow_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_workflow_events
    ADD CONSTRAINT carbon_workflow_events_pkey PRIMARY KEY (id);


--
-- Name: case_escalation_settings case_escalation_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_escalation_settings
    ADD CONSTRAINT case_escalation_settings_pkey PRIMARY KEY (id);


--
-- Name: case_reminders case_reminders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_reminders
    ADD CONSTRAINT case_reminders_pkey PRIMARY KEY (id);


--
-- Name: case_sla_config case_sla_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_sla_config
    ADD CONSTRAINT case_sla_config_pkey PRIMARY KEY (case_type);


--
-- Name: cases cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_pkey PRIMARY KEY (id);


--
-- Name: cases cases_source_table_source_record_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_source_table_source_record_id_key UNIQUE (source_table, source_record_id);


--
-- Name: cdd_documents cdd_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cdd_documents
    ADD CONSTRAINT cdd_documents_pkey PRIMARY KEY (id);


--
-- Name: cdd_reviews cdd_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cdd_reviews
    ADD CONSTRAINT cdd_reviews_pkey PRIMARY KEY (id);


--
-- Name: cdd_risk_factors cdd_risk_factors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cdd_risk_factors
    ADD CONSTRAINT cdd_risk_factors_pkey PRIMARY KEY (id);


--
-- Name: cobec_declarations cobec_declarations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cobec_declarations
    ADD CONSTRAINT cobec_declarations_pkey PRIMARY KEY (id);


--
-- Name: coi_campaign_employees coi_campaign_employees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_campaign_employees
    ADD CONSTRAINT coi_campaign_employees_pkey PRIMARY KEY (id);


--
-- Name: coi_campaigns coi_campaigns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_campaigns
    ADD CONSTRAINT coi_campaigns_pkey PRIMARY KEY (id);


--
-- Name: coi_declaration_history coi_declaration_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_declaration_history
    ADD CONSTRAINT coi_declaration_history_pkey PRIMARY KEY (id);


--
-- Name: coi_declarations coi_declarations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_declarations
    ADD CONSTRAINT coi_declarations_pkey PRIMARY KEY (id);


--
-- Name: coi_disclosures coi_disclosures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_disclosures
    ADD CONSTRAINT coi_disclosures_pkey PRIMARY KEY (id);


--
-- Name: coi_mitigation_history coi_mitigation_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_mitigation_history
    ADD CONSTRAINT coi_mitigation_history_pkey PRIMARY KEY (id);


--
-- Name: coi_mitigation_plans coi_mitigation_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_mitigation_plans
    ADD CONSTRAINT coi_mitigation_plans_pkey PRIMARY KEY (id);


--
-- Name: committee_meetings committee_meetings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_meetings
    ADD CONSTRAINT committee_meetings_pkey PRIMARY KEY (id);


--
-- Name: committee_members committee_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_members
    ADD CONSTRAINT committee_members_pkey PRIMARY KEY (id);


--
-- Name: committee_memberships committee_memberships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committee_memberships
    ADD CONSTRAINT committee_memberships_pkey PRIMARY KEY (id);


--
-- Name: committees committees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.committees
    ADD CONSTRAINT committees_pkey PRIMARY KEY (id);


--
-- Name: complaint_activity_log complaint_activity_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.complaint_activity_log
    ADD CONSTRAINT complaint_activity_log_pkey PRIMARY KEY (id);


--
-- Name: complaint_categories complaint_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.complaint_categories
    ADD CONSTRAINT complaint_categories_pkey PRIMARY KEY (id);


--
-- Name: complaint_documents complaint_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.complaint_documents
    ADD CONSTRAINT complaint_documents_pkey PRIMARY KEY (id);


--
-- Name: compliance_events compliance_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compliance_events
    ADD CONSTRAINT compliance_events_pkey PRIMARY KEY (id);


--
-- Name: conduct_declarations conduct_declarations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conduct_declarations
    ADD CONSTRAINT conduct_declarations_pkey PRIMARY KEY (id);


--
-- Name: confirmed_matches confirmed_matches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confirmed_matches
    ADD CONSTRAINT confirmed_matches_pkey PRIMARY KEY (id);


--
-- Name: conflict_of_interest conflict_of_interest_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conflict_of_interest
    ADD CONSTRAINT conflict_of_interest_pkey PRIMARY KEY (id);


--
-- Name: consent_purposes consent_purposes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consent_purposes
    ADD CONSTRAINT consent_purposes_pkey PRIMARY KEY (id);


--
-- Name: consents consents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consents
    ADD CONSTRAINT consents_pkey PRIMARY KEY (id);


--
-- Name: consumer_complaints consumer_complaints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumer_complaints
    ADD CONSTRAINT consumer_complaints_pkey PRIMARY KEY (id);


--
-- Name: control_test_results control_test_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.control_test_results
    ADD CONSTRAINT control_test_results_pkey PRIMARY KEY (id);


--
-- Name: controls controls_control_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.controls
    ADD CONSTRAINT controls_control_code_key UNIQUE (control_code);


--
-- Name: controls controls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.controls
    ADD CONSTRAINT controls_pkey PRIMARY KEY (id);


--
-- Name: corp_profile corp_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corp_profile
    ADD CONSTRAINT corp_profile_pkey PRIMARY KEY (id);


--
-- Name: customer_complaints customer_complaints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_complaints
    ADD CONSTRAINT customer_complaints_pkey PRIMARY KEY (id);


--
-- Name: customer_consents customer_consents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_consents
    ADD CONSTRAINT customer_consents_pkey PRIMARY KEY (id);


--
-- Name: customer_risk_scores customer_risk_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_risk_scores
    ADD CONSTRAINT customer_risk_scores_pkey PRIMARY KEY (id);


--
-- Name: customer_transactions customer_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transactions
    ADD CONSTRAINT customer_transactions_pkey PRIMARY KEY (id);


--
-- Name: customers customers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (id);


--
-- Name: cy_assessments cy_assessments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_assessments
    ADD CONSTRAINT cy_assessments_pkey PRIMARY KEY (id);


--
-- Name: cy_backups cy_backups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_backups
    ADD CONSTRAINT cy_backups_pkey PRIMARY KEY (id);


--
-- Name: cy_backups cy_backups_system_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_backups
    ADD CONSTRAINT cy_backups_system_name_key UNIQUE (system_name);


--
-- Name: cy_bcp_sites cy_bcp_sites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_bcp_sites
    ADD CONSTRAINT cy_bcp_sites_pkey PRIMARY KEY (id);


--
-- Name: cy_domains cy_domains_domain_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_domains
    ADD CONSTRAINT cy_domains_domain_key UNIQUE (domain);


--
-- Name: cy_domains cy_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_domains
    ADD CONSTRAINT cy_domains_pkey PRIMARY KEY (id);


--
-- Name: cy_dr_tests cy_dr_tests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_dr_tests
    ADD CONSTRAINT cy_dr_tests_pkey PRIMARY KEY (id);


--
-- Name: cy_integrations cy_integrations_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_integrations
    ADD CONSTRAINT cy_integrations_code_key UNIQUE (code);


--
-- Name: cy_integrations cy_integrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_integrations
    ADD CONSTRAINT cy_integrations_pkey PRIMARY KEY (id);


--
-- Name: cy_maturity_assessments cy_maturity_assessments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_maturity_assessments
    ADD CONSTRAINT cy_maturity_assessments_pkey PRIMARY KEY (id);


--
-- Name: cy_maturity_scores cy_maturity_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_maturity_scores
    ADD CONSTRAINT cy_maturity_scores_pkey PRIMARY KEY (assessment_id, requirement_id);


--
-- Name: cy_security_assets cy_security_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_security_assets
    ADD CONSTRAINT cy_security_assets_pkey PRIMARY KEY (id);


--
-- Name: cyber_incidents cyber_incidents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cyber_incidents
    ADD CONSTRAINT cyber_incidents_pkey PRIMARY KEY (id);


--
-- Name: cybersecurity_incidents cybersecurity_incidents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cybersecurity_incidents
    ADD CONSTRAINT cybersecurity_incidents_pkey PRIMARY KEY (id);


--
-- Name: data_breaches data_breaches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_breaches
    ADD CONSTRAINT data_breaches_pkey PRIMARY KEY (id);


--
-- Name: data_processing_activities data_processing_activities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_processing_activities
    ADD CONSTRAINT data_processing_activities_pkey PRIMARY KEY (id);


--
-- Name: data_source_urls data_source_urls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_source_urls
    ADD CONSTRAINT data_source_urls_pkey PRIMARY KEY (id);


--
-- Name: data_subject_requests data_subject_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_subject_requests
    ADD CONSTRAINT data_subject_requests_pkey PRIMARY KEY (id);


--
-- Name: data_update_audit_log data_update_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_update_audit_log
    ADD CONSTRAINT data_update_audit_log_pkey PRIMARY KEY (id);


--
-- Name: declaration_campaign_targets declaration_campaign_targets_campaign_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.declaration_campaign_targets
    ADD CONSTRAINT declaration_campaign_targets_campaign_id_user_id_key UNIQUE (campaign_id, user_id);


--
-- Name: declaration_campaign_targets declaration_campaign_targets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.declaration_campaign_targets
    ADD CONSTRAINT declaration_campaign_targets_pkey PRIMARY KEY (id);


--
-- Name: declaration_campaigns declaration_campaigns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.declaration_campaigns
    ADD CONSTRAINT declaration_campaigns_pkey PRIMARY KEY (id);


--
-- Name: departments departments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_pkey PRIMARY KEY (id);


--
-- Name: document_approvals document_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_approvals
    ADD CONSTRAINT document_approvals_pkey PRIMARY KEY (id);


--
-- Name: document_types document_types_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_types
    ADD CONSTRAINT document_types_code_key UNIQUE (code);


--
-- Name: document_types document_types_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_types
    ADD CONSTRAINT document_types_pkey PRIMARY KEY (id);


--
-- Name: dpias dpias_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dpias
    ADD CONSTRAINT dpias_pkey PRIMARY KEY (id);


--
-- Name: dpo_activities dpo_activities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dpo_activities
    ADD CONSTRAINT dpo_activities_pkey PRIMARY KEY (id);


--
-- Name: dpo_appointments dpo_appointments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dpo_appointments
    ADD CONSTRAINT dpo_appointments_pkey PRIMARY KEY (id);


--
-- Name: dsr_timeline dsr_timeline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dsr_timeline
    ADD CONSTRAINT dsr_timeline_pkey PRIMARY KEY (id);


--
-- Name: edd_cases edd_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.edd_cases
    ADD CONSTRAINT edd_cases_pkey PRIMARY KEY (id);


--
-- Name: ekyc_audit_log ekyc_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_audit_log
    ADD CONSTRAINT ekyc_audit_log_pkey PRIMARY KEY (id);


--
-- Name: ekyc_config ekyc_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_config
    ADD CONSTRAINT ekyc_config_pkey PRIMARY KEY (config_key);


--
-- Name: ekyc_document ekyc_document_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_document
    ADD CONSTRAINT ekyc_document_pkey PRIMARY KEY (id);


--
-- Name: ekyc_result ekyc_result_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_result
    ADD CONSTRAINT ekyc_result_pkey PRIMARY KEY (id);


--
-- Name: ekyc_result ekyc_result_session_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_result
    ADD CONSTRAINT ekyc_result_session_id_key UNIQUE (session_id);


--
-- Name: ekyc_session ekyc_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_session
    ADD CONSTRAINT ekyc_session_pkey PRIMARY KEY (id);


--
-- Name: ekyc_session ekyc_session_session_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_session
    ADD CONSTRAINT ekyc_session_session_token_key UNIQUE (session_token);


--
-- Name: email_templates email_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_templates
    ADD CONSTRAINT email_templates_pkey PRIMARY KEY (id);


--
-- Name: email_templates email_templates_template_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_templates
    ADD CONSTRAINT email_templates_template_key_key UNIQUE (template_key);


--
-- Name: employee_screenings employee_screenings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_screenings
    ADD CONSTRAINT employee_screenings_pkey PRIMARY KEY (id);


--
-- Name: esg_disclosure_items esg_disclosure_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_disclosure_items
    ADD CONSTRAINT esg_disclosure_items_pkey PRIMARY KEY (id);


--
-- Name: esg_frameworks esg_frameworks_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_frameworks
    ADD CONSTRAINT esg_frameworks_code_key UNIQUE (code);


--
-- Name: esg_frameworks esg_frameworks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_frameworks
    ADD CONSTRAINT esg_frameworks_pkey PRIMARY KEY (id);


--
-- Name: esg_indicator_responses esg_indicator_responses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_indicator_responses
    ADD CONSTRAINT esg_indicator_responses_pkey PRIMARY KEY (id);


--
-- Name: esg_indicator_responses esg_indicator_responses_reporting_period_id_indicator_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_indicator_responses
    ADD CONSTRAINT esg_indicator_responses_reporting_period_id_indicator_id_key UNIQUE (reporting_period_id, indicator_id);


--
-- Name: esg_indicators esg_indicators_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_indicators
    ADD CONSTRAINT esg_indicators_pkey PRIMARY KEY (id);


--
-- Name: esg_materiality_scores esg_materiality_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_materiality_scores
    ADD CONSTRAINT esg_materiality_scores_pkey PRIMARY KEY (id);


--
-- Name: esg_materiality_scores esg_materiality_scores_reporting_period_id_topic_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_materiality_scores
    ADD CONSTRAINT esg_materiality_scores_reporting_period_id_topic_id_key UNIQUE (reporting_period_id, topic_id);


--
-- Name: esg_materiality_topics esg_materiality_topics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_materiality_topics
    ADD CONSTRAINT esg_materiality_topics_pkey PRIMARY KEY (id);


--
-- Name: esg_pillars esg_pillars_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_pillars
    ADD CONSTRAINT esg_pillars_pkey PRIMARY KEY (id);


--
-- Name: esg_reporting_periods esg_reporting_periods_label_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_reporting_periods
    ADD CONSTRAINT esg_reporting_periods_label_key UNIQUE (label);


--
-- Name: esg_reporting_periods esg_reporting_periods_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_reporting_periods
    ADD CONSTRAINT esg_reporting_periods_pkey PRIMARY KEY (id);


--
-- Name: esg_sites esg_sites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_sites
    ADD CONSTRAINT esg_sites_pkey PRIMARY KEY (id);


--
-- Name: event_routing_rules event_routing_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_routing_rules
    ADD CONSTRAINT event_routing_rules_pkey PRIMARY KEY (id);


--
-- Name: fit_proper_assessments fit_proper_assessments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fit_proper_assessments
    ADD CONSTRAINT fit_proper_assessments_pkey PRIMARY KEY (id);


--
-- Name: fra_verifiers fra_verifiers_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fra_verifiers
    ADD CONSTRAINT fra_verifiers_name_key UNIQUE (name);


--
-- Name: fra_verifiers fra_verifiers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fra_verifiers
    ADD CONSTRAINT fra_verifiers_pkey PRIMARY KEY (id);


--
-- Name: generic_attachments generic_attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.generic_attachments
    ADD CONSTRAINT generic_attachments_pkey PRIMARY KEY (id);


--
-- Name: ghe_approval_history ghe_approval_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ghe_approval_history
    ADD CONSTRAINT ghe_approval_history_pkey PRIMARY KEY (id);


--
-- Name: ghe_declaration_history ghe_declaration_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ghe_declaration_history
    ADD CONSTRAINT ghe_declaration_history_pkey PRIMARY KEY (id);


--
-- Name: ghe_declarations ghe_declarations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ghe_declarations
    ADD CONSTRAINT ghe_declarations_pkey PRIMARY KEY (id);


--
-- Name: ghe_records ghe_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ghe_records
    ADD CONSTRAINT ghe_records_pkey PRIMARY KEY (id);


--
-- Name: governance_compliance_tracker governance_compliance_tracker_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.governance_compliance_tracker
    ADD CONSTRAINT governance_compliance_tracker_pkey PRIMARY KEY (id);


--
-- Name: high_risk_countries high_risk_countries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.high_risk_countries
    ADD CONSTRAINT high_risk_countries_pkey PRIMARY KEY (id);


--
-- Name: ia_area_controls ia_area_controls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ia_area_controls
    ADD CONSTRAINT ia_area_controls_pkey PRIMARY KEY (universe_id, control_id);


--
-- Name: incident_response_team incident_response_team_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incident_response_team
    ADD CONSTRAINT incident_response_team_pkey PRIMARY KEY (id);


--
-- Name: incident_timeline incident_timeline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incident_timeline
    ADD CONSTRAINT incident_timeline_pkey PRIMARY KEY (id);


--
-- Name: independence_declarations independence_declarations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.independence_declarations
    ADD CONSTRAINT independence_declarations_pkey PRIMARY KEY (id);


--
-- Name: internal_blacklist_audit internal_blacklist_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.internal_blacklist_audit
    ADD CONSTRAINT internal_blacklist_audit_pkey PRIMARY KEY (id);


--
-- Name: internal_blacklist internal_blacklist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.internal_blacklist
    ADD CONSTRAINT internal_blacklist_pkey PRIMARY KEY (id);


--
-- Name: internal_pep_audit internal_pep_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.internal_pep_audit
    ADD CONSTRAINT internal_pep_audit_pkey PRIMARY KEY (id);


--
-- Name: internal_pep internal_pep_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.internal_pep
    ADD CONSTRAINT internal_pep_pkey PRIMARY KEY (id);


--
-- Name: internal_pep internal_pep_source_id_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.internal_pep
    ADD CONSTRAINT internal_pep_source_id_unique UNIQUE (source_id);


--
-- Name: kri_measurements kri_measurements_kri_id_measurement_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kri_measurements
    ADD CONSTRAINT kri_measurements_kri_id_measurement_date_key UNIQUE (kri_id, measurement_date);


--
-- Name: kri_measurements kri_measurements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kri_measurements
    ADD CONSTRAINT kri_measurements_pkey PRIMARY KEY (id);


--
-- Name: kris kris_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kris
    ADD CONSTRAINT kris_pkey PRIMARY KEY (id);


--
-- Name: kyc_beneficial_owners kyc_beneficial_owners_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_beneficial_owners
    ADD CONSTRAINT kyc_beneficial_owners_pkey PRIMARY KEY (id);


--
-- Name: kyc_bo_declarations kyc_bo_declarations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_bo_declarations
    ADD CONSTRAINT kyc_bo_declarations_pkey PRIMARY KEY (id);


--
-- Name: kyc_fields kyc_fields_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_fields
    ADD CONSTRAINT kyc_fields_pkey PRIMARY KEY (subject, field_key);


--
-- Name: kyc_onboarding kyc_onboarding_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_onboarding
    ADD CONSTRAINT kyc_onboarding_pkey PRIMARY KEY (subject, subject_id);


--
-- Name: kyc_profile_values kyc_profile_values_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_profile_values
    ADD CONSTRAINT kyc_profile_values_pkey PRIMARY KEY (subject, subject_id, field_key);


--
-- Name: kyc_risk_bands kyc_risk_bands_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_risk_bands
    ADD CONSTRAINT kyc_risk_bands_pkey PRIMARY KEY (band);


--
-- Name: kyc_risk_factors kyc_risk_factors_factor_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_risk_factors
    ADD CONSTRAINT kyc_risk_factors_factor_key_key UNIQUE (factor_key);


--
-- Name: kyc_risk_factors kyc_risk_factors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_risk_factors
    ADD CONSTRAINT kyc_risk_factors_pkey PRIMARY KEY (id);


--
-- Name: kyc_risk_ratings kyc_risk_ratings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_risk_ratings
    ADD CONSTRAINT kyc_risk_ratings_pkey PRIMARY KEY (id);


--
-- Name: ln_clients ln_clients_client_ref_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_clients
    ADD CONSTRAINT ln_clients_client_ref_key UNIQUE (client_ref);


--
-- Name: ln_clients ln_clients_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_clients
    ADD CONSTRAINT ln_clients_pkey PRIMARY KEY (id);


--
-- Name: ln_contracts ln_contracts_loan_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_contracts
    ADD CONSTRAINT ln_contracts_loan_id_key UNIQUE (loan_id);


--
-- Name: ln_contracts ln_contracts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_contracts
    ADD CONSTRAINT ln_contracts_pkey PRIMARY KEY (id);


--
-- Name: ln_credit_studies ln_credit_studies_loan_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_credit_studies
    ADD CONSTRAINT ln_credit_studies_loan_id_key UNIQUE (loan_id);


--
-- Name: ln_credit_studies ln_credit_studies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_credit_studies
    ADD CONSTRAINT ln_credit_studies_pkey PRIMARY KEY (id);


--
-- Name: ln_documents ln_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_documents
    ADD CONSTRAINT ln_documents_pkey PRIMARY KEY (id);


--
-- Name: ln_early_repayments ln_early_repayments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_early_repayments
    ADD CONSTRAINT ln_early_repayments_pkey PRIMARY KEY (id);


--
-- Name: ln_exceptions ln_exceptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_exceptions
    ADD CONSTRAINT ln_exceptions_pkey PRIMARY KEY (id);


--
-- Name: ln_import_batches ln_import_batches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_import_batches
    ADD CONSTRAINT ln_import_batches_pkey PRIMARY KEY (id);


--
-- Name: ln_instalments ln_instalments_loan_id_seq_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_instalments
    ADD CONSTRAINT ln_instalments_loan_id_seq_key UNIQUE (loan_id, seq);


--
-- Name: ln_instalments ln_instalments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_instalments
    ADD CONSTRAINT ln_instalments_pkey PRIMARY KEY (id);


--
-- Name: ln_loans ln_loans_loan_ref_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_loans
    ADD CONSTRAINT ln_loans_loan_ref_key UNIQUE (loan_ref);


--
-- Name: ln_loans ln_loans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_loans
    ADD CONSTRAINT ln_loans_pkey PRIMARY KEY (id);


--
-- Name: ln_par_snapshots ln_par_snapshots_period_dimension_dim_value_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_par_snapshots
    ADD CONSTRAINT ln_par_snapshots_period_dimension_dim_value_key UNIQUE (period, dimension, dim_value);


--
-- Name: ln_par_snapshots ln_par_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_par_snapshots
    ADD CONSTRAINT ln_par_snapshots_pkey PRIMARY KEY (id);


--
-- Name: ln_products ln_products_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_products
    ADD CONSTRAINT ln_products_code_key UNIQUE (code);


--
-- Name: ln_products ln_products_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_products
    ADD CONSTRAINT ln_products_pkey PRIMARY KEY (id);


--
-- Name: ln_qa_flags ln_qa_flags_loan_id_flag_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_qa_flags
    ADD CONSTRAINT ln_qa_flags_loan_id_flag_type_key UNIQUE (loan_id, flag_type);


--
-- Name: ln_qa_flags ln_qa_flags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_qa_flags
    ADD CONSTRAINT ln_qa_flags_pkey PRIMARY KEY (id);


--
-- Name: ln_reschedulings ln_reschedulings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_reschedulings
    ADD CONSTRAINT ln_reschedulings_pkey PRIMARY KEY (id);


--
-- Name: ln_transfers ln_transfers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_transfers
    ADD CONSTRAINT ln_transfers_pkey PRIMARY KEY (id);


--
-- Name: ln_visits ln_visits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_visits
    ADD CONSTRAINT ln_visits_pkey PRIMARY KEY (id);


--
-- Name: meeting_action_items meeting_action_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_action_items
    ADD CONSTRAINT meeting_action_items_pkey PRIMARY KEY (id);


--
-- Name: meeting_agenda_items meeting_agenda_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_agenda_items
    ADD CONSTRAINT meeting_agenda_items_pkey PRIMARY KEY (id);


--
-- Name: meeting_attendance meeting_attendance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_attendance
    ADD CONSTRAINT meeting_attendance_pkey PRIMARY KEY (id);


--
-- Name: merchant_kyc_documents merchant_kyc_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merchant_kyc_documents
    ADD CONSTRAINT merchant_kyc_documents_pkey PRIMARY KEY (id);


--
-- Name: merchants merchants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merchants
    ADD CONSTRAINT merchants_pkey PRIMARY KEY (id);


--
-- Name: mfa_audit mfa_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mfa_audit
    ADD CONSTRAINT mfa_audit_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: numbering_sequences numbering_sequences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.numbering_sequences
    ADD CONSTRAINT numbering_sequences_pkey PRIMARY KEY (id);


--
-- Name: numbering_sequences numbering_sequences_sequence_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.numbering_sequences
    ADD CONSTRAINT numbering_sequences_sequence_key_key UNIQUE (sequence_key);


--
-- Name: ongoing_screening_config ongoing_screening_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_config
    ADD CONSTRAINT ongoing_screening_config_pkey PRIMARY KEY (id);


--
-- Name: ongoing_screening_config ongoing_screening_config_scope_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_config
    ADD CONSTRAINT ongoing_screening_config_scope_name_key UNIQUE (scope_name);


--
-- Name: ongoing_screening_findings ongoing_screening_findings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_findings
    ADD CONSTRAINT ongoing_screening_findings_pkey PRIMARY KEY (id);


--
-- Name: ongoing_screening_runs ongoing_screening_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_runs
    ADD CONSTRAINT ongoing_screening_runs_pkey PRIMARY KEY (id);


--
-- Name: org_unit_types org_unit_types_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_unit_types
    ADD CONSTRAINT org_unit_types_code_key UNIQUE (code);


--
-- Name: org_unit_types org_unit_types_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_unit_types
    ADD CONSTRAINT org_unit_types_pkey PRIMARY KEY (id);


--
-- Name: org_units org_units_code_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_units
    ADD CONSTRAINT org_units_code_uniq UNIQUE (code);


--
-- Name: org_units org_units_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_units
    ADD CONSTRAINT org_units_pkey PRIMARY KEY (id);


--
-- Name: parties parties_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parties
    ADD CONSTRAINT parties_pkey PRIMARY KEY (id);


--
-- Name: party_links party_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.party_links
    ADD CONSTRAINT party_links_pkey PRIMARY KEY (id);


--
-- Name: party_links party_links_source_table_source_record_id_link_role_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.party_links
    ADD CONSTRAINT party_links_source_table_source_record_id_link_role_key UNIQUE (source_table, source_record_id, link_role);


--
-- Name: pep_aliases pep_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_aliases
    ADD CONSTRAINT pep_aliases_pkey PRIMARY KEY (id);


--
-- Name: pep_corporate_links pep_corporate_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_corporate_links
    ADD CONSTRAINT pep_corporate_links_pkey PRIMARY KEY (id);


--
-- Name: pep_database pep_database_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_database
    ADD CONSTRAINT pep_database_pkey PRIMARY KEY (id);


--
-- Name: pep_duplicate_candidates pep_duplicate_candidates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_duplicate_candidates
    ADD CONSTRAINT pep_duplicate_candidates_pkey PRIMARY KEY (id);


--
-- Name: pep_master pep_master_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_master
    ADD CONSTRAINT pep_master_pkey PRIMARY KEY (id);


--
-- Name: pep_matches pep_matches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_matches
    ADD CONSTRAINT pep_matches_pkey PRIMARY KEY (id);


--
-- Name: pep_positions pep_positions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_positions
    ADD CONSTRAINT pep_positions_pkey PRIMARY KEY (id);


--
-- Name: pep_screenings pep_screenings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_screenings
    ADD CONSTRAINT pep_screenings_pkey PRIMARY KEY (id);


--
-- Name: pep_sources pep_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_sources
    ADD CONSTRAINT pep_sources_pkey PRIMARY KEY (id);


--
-- Name: pep_update_logs pep_update_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_update_logs
    ADD CONSTRAINT pep_update_logs_pkey PRIMARY KEY (id);


--
-- Name: phishing_campaigns phishing_campaigns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phishing_campaigns
    ADD CONSTRAINT phishing_campaigns_pkey PRIMARY KEY (id);


--
-- Name: phishing_events phishing_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phishing_events
    ADD CONSTRAINT phishing_events_pkey PRIMARY KEY (id);


--
-- Name: phishing_recipients phishing_recipients_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phishing_recipients
    ADD CONSTRAINT phishing_recipients_pkey PRIMARY KEY (id);


--
-- Name: phishing_recipients phishing_recipients_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phishing_recipients
    ADD CONSTRAINT phishing_recipients_token_key UNIQUE (token);


--
-- Name: policies policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policies
    ADD CONSTRAINT policies_pkey PRIMARY KEY (id);


--
-- Name: policy_acknowledgments policy_acknowledgments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_acknowledgments
    ADD CONSTRAINT policy_acknowledgments_pkey PRIMARY KEY (id);


--
-- Name: policy_applicability policy_applicability_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_applicability
    ADD CONSTRAINT policy_applicability_pkey PRIMARY KEY (id);


--
-- Name: policy_attachments policy_attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_attachments
    ADD CONSTRAINT policy_attachments_pkey PRIMARY KEY (id);


--
-- Name: policy_board_approvals policy_board_approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_board_approvals
    ADD CONSTRAINT policy_board_approvals_pkey PRIMARY KEY (id);


--
-- Name: policy_categories policy_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_categories
    ADD CONSTRAINT policy_categories_pkey PRIMARY KEY (id);


--
-- Name: policy_review_workflow policy_review_workflow_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_review_workflow
    ADD CONSTRAINT policy_review_workflow_pkey PRIMARY KEY (id);


--
-- Name: policy_versions policy_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_versions
    ADD CONSTRAINT policy_versions_pkey PRIMARY KEY (id);


--
-- Name: pr_branch_roles pr_branch_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_branch_roles
    ADD CONSTRAINT pr_branch_roles_pkey PRIMARY KEY (code);


--
-- Name: pr_branch_staffing pr_branch_staffing_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_branch_staffing
    ADD CONSTRAINT pr_branch_staffing_pkey PRIMARY KEY (branch_id, role_code);


--
-- Name: pr_branches pr_branches_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_branches
    ADD CONSTRAINT pr_branches_code_key UNIQUE (code);


--
-- Name: pr_branches pr_branches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_branches
    ADD CONSTRAINT pr_branches_pkey PRIMARY KEY (id);


--
-- Name: pr_capital_events pr_capital_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_capital_events
    ADD CONSTRAINT pr_capital_events_pkey PRIMARY KEY (id);


--
-- Name: pr_deadline_extensions pr_deadline_extensions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_deadline_extensions
    ADD CONSTRAINT pr_deadline_extensions_pkey PRIMARY KEY (id);


--
-- Name: pr_deadlines pr_deadlines_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_deadlines
    ADD CONSTRAINT pr_deadlines_pkey PRIMARY KEY (id);


--
-- Name: pr_documents pr_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_documents
    ADD CONSTRAINT pr_documents_pkey PRIMARY KEY (id);


--
-- Name: pr_facilities pr_facilities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_facilities
    ADD CONSTRAINT pr_facilities_pkey PRIMARY KEY (id);


--
-- Name: pr_facilities pr_facilities_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_facilities
    ADD CONSTRAINT pr_facilities_reference_key UNIQUE (reference);


--
-- Name: pr_financial_periods pr_financial_periods_period_end_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_financial_periods
    ADD CONSTRAINT pr_financial_periods_period_end_key UNIQUE (period_end);


--
-- Name: pr_financial_periods pr_financial_periods_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_financial_periods
    ADD CONSTRAINT pr_financial_periods_pkey PRIMARY KEY (id);


--
-- Name: pr_key_function_types pr_key_function_types_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_key_function_types
    ADD CONSTRAINT pr_key_function_types_pkey PRIMARY KEY (code);


--
-- Name: pr_key_functions pr_key_functions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_key_functions
    ADD CONSTRAINT pr_key_functions_pkey PRIMARY KEY (id);


--
-- Name: pr_related_parties pr_related_parties_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_related_parties
    ADD CONSTRAINT pr_related_parties_pkey PRIMARY KEY (id);


--
-- Name: pr_rp_items pr_rp_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_rp_items
    ADD CONSTRAINT pr_rp_items_pkey PRIMARY KEY (id);


--
-- Name: pr_studies pr_studies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_studies
    ADD CONSTRAINT pr_studies_pkey PRIMARY KEY (id);


--
-- Name: rc_alerts rc_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_alerts
    ADD CONSTRAINT rc_alerts_pkey PRIMARY KEY (id);


--
-- Name: rc_areas rc_areas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_areas
    ADD CONSTRAINT rc_areas_pkey PRIMARY KEY (code);


--
-- Name: rc_calendar_reminders rc_calendar_reminders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_calendar_reminders
    ADD CONSTRAINT rc_calendar_reminders_pkey PRIMARY KEY (item_key, days_before);


--
-- Name: rc_control_requirements rc_control_requirements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_control_requirements
    ADD CONSTRAINT rc_control_requirements_pkey PRIMARY KEY (control_id, requirement_id);


--
-- Name: rc_control_runs rc_control_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_control_runs
    ADD CONSTRAINT rc_control_runs_pkey PRIMARY KEY (id);


--
-- Name: rc_controls rc_controls_control_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_controls
    ADD CONSTRAINT rc_controls_control_code_key UNIQUE (control_code);


--
-- Name: rc_controls rc_controls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_controls
    ADD CONSTRAINT rc_controls_pkey PRIMARY KEY (id);


--
-- Name: rc_corrective_actions rc_corrective_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_corrective_actions
    ADD CONSTRAINT rc_corrective_actions_pkey PRIMARY KEY (id);


--
-- Name: rc_evidence rc_evidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_evidence
    ADD CONSTRAINT rc_evidence_pkey PRIMARY KEY (id);


--
-- Name: rc_finding_controls rc_finding_controls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_finding_controls
    ADD CONSTRAINT rc_finding_controls_pkey PRIMARY KEY (finding_id, control_id);


--
-- Name: rc_finding_events rc_finding_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_finding_events
    ADD CONSTRAINT rc_finding_events_pkey PRIMARY KEY (id);


--
-- Name: rc_findings rc_findings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_findings
    ADD CONSTRAINT rc_findings_pkey PRIMARY KEY (id);


--
-- Name: rc_findings rc_findings_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_findings
    ADD CONSTRAINT rc_findings_reference_key UNIQUE (reference);


--
-- Name: rc_frameworks rc_frameworks_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_frameworks
    ADD CONSTRAINT rc_frameworks_code_key UNIQUE (code);


--
-- Name: rc_frameworks rc_frameworks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_frameworks
    ADD CONSTRAINT rc_frameworks_pkey PRIMARY KEY (id);


--
-- Name: rc_licence_types rc_licence_types_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_licence_types
    ADD CONSTRAINT rc_licence_types_pkey PRIMARY KEY (code);


--
-- Name: rc_owner_roles rc_owner_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_owner_roles
    ADD CONSTRAINT rc_owner_roles_pkey PRIMARY KEY (code);


--
-- Name: rc_packs rc_packs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_packs
    ADD CONSTRAINT rc_packs_pkey PRIMARY KEY (code);


--
-- Name: rc_parameter_changes rc_parameter_changes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameter_changes
    ADD CONSTRAINT rc_parameter_changes_pkey PRIMARY KEY (id);


--
-- Name: rc_parameters rc_parameters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameters
    ADD CONSTRAINT rc_parameters_pkey PRIMARY KEY (id);


--
-- Name: rc_parameters rc_parameters_version_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameters
    ADD CONSTRAINT rc_parameters_version_uniq UNIQUE (param_key, licence_type, effective_from);


--
-- Name: rc_readiness_snapshots rc_readiness_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_readiness_snapshots
    ADD CONSTRAINT rc_readiness_snapshots_pkey PRIMARY KEY (id);


--
-- Name: rc_requirements rc_requirements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_requirements
    ADD CONSTRAINT rc_requirements_pkey PRIMARY KEY (id);


--
-- Name: rc_requirements rc_requirements_ref_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_requirements
    ADD CONSTRAINT rc_requirements_ref_uniq UNIQUE (framework_id, ref_code);


--
-- Name: red_flags red_flags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.red_flags
    ADD CONSTRAINT red_flags_pkey PRIMARY KEY (id);


--
-- Name: regulators regulators_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regulators
    ADD CONSTRAINT regulators_pkey PRIMARY KEY (id);


--
-- Name: regulatory_report_submissions regulatory_report_submissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regulatory_report_submissions
    ADD CONSTRAINT regulatory_report_submissions_pkey PRIMARY KEY (id);


--
-- Name: regulatory_reports regulatory_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regulatory_reports
    ADD CONSTRAINT regulatory_reports_pkey PRIMARY KEY (id);


--
-- Name: reminder_log reminder_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reminder_log
    ADD CONSTRAINT reminder_log_pkey PRIMARY KEY (id);


--
-- Name: required_policies required_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.required_policies
    ADD CONSTRAINT required_policies_pkey PRIMARY KEY (id);


--
-- Name: risk_appetite_statements risk_appetite_statements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_appetite_statements
    ADD CONSTRAINT risk_appetite_statements_pkey PRIMARY KEY (id);


--
-- Name: risk_categories risk_categories_category_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_categories
    ADD CONSTRAINT risk_categories_category_code_key UNIQUE (category_code);


--
-- Name: risk_categories risk_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_categories
    ADD CONSTRAINT risk_categories_pkey PRIMARY KEY (id);


--
-- Name: risk_controls risk_controls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_controls
    ADD CONSTRAINT risk_controls_pkey PRIMARY KEY (id);


--
-- Name: risk_controls risk_controls_risk_id_control_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_controls
    ADD CONSTRAINT risk_controls_risk_id_control_id_key UNIQUE (risk_id, control_id);


--
-- Name: risk_register risk_register_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_register
    ADD CONSTRAINT risk_register_pkey PRIMARY KEY (id);


--
-- Name: risk_reviews risk_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_reviews
    ADD CONSTRAINT risk_reviews_pkey PRIMARY KEY (id);


--
-- Name: risk_score_history risk_score_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_score_history
    ADD CONSTRAINT risk_score_history_pkey PRIMARY KEY (id);


--
-- Name: risk_scoring_bands risk_scoring_bands_min_score_max_score_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_scoring_bands
    ADD CONSTRAINT risk_scoring_bands_min_score_max_score_key UNIQUE (min_score, max_score);


--
-- Name: risk_scoring_bands risk_scoring_bands_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_scoring_bands
    ADD CONSTRAINT risk_scoring_bands_pkey PRIMARY KEY (id);


--
-- Name: risk_source_links risk_source_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_source_links
    ADD CONSTRAINT risk_source_links_pkey PRIMARY KEY (id);


--
-- Name: risk_source_links risk_source_links_risk_id_source_module_source_table_source_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_source_links
    ADD CONSTRAINT risk_source_links_risk_id_source_module_source_table_source_key UNIQUE (risk_id, source_module, source_table, source_record_id, link_type);


--
-- Name: risk_treatments risk_treatments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_treatments
    ADD CONSTRAINT risk_treatments_pkey PRIMARY KEY (id);


--
-- Name: risks risks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risks
    ADD CONSTRAINT risks_pkey PRIMARY KEY (id);


--
-- Name: risks risks_risk_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risks
    ADD CONSTRAINT risks_risk_id_key UNIQUE (risk_id);


--
-- Name: sanctions_entries sanctions_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sanctions_entries
    ADD CONSTRAINT sanctions_entries_pkey PRIMARY KEY (id);


--
-- Name: sanctions_lists sanctions_lists_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sanctions_lists
    ADD CONSTRAINT sanctions_lists_pkey PRIMARY KEY (id);


--
-- Name: sanctions_matches sanctions_matches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sanctions_matches
    ADD CONSTRAINT sanctions_matches_pkey PRIMARY KEY (id);


--
-- Name: sanctions_screening_log sanctions_screening_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sanctions_screening_log
    ADD CONSTRAINT sanctions_screening_log_pkey PRIMARY KEY (id);


--
-- Name: sanctions_screenings sanctions_screenings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sanctions_screenings
    ADD CONSTRAINT sanctions_screenings_pkey PRIMARY KEY (id);


--
-- Name: sar_red_flags sar_red_flags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sar_red_flags
    ADD CONSTRAINT sar_red_flags_pkey PRIMARY KEY (id);


--
-- Name: sar_reports sar_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sar_reports
    ADD CONSTRAINT sar_reports_pkey PRIMARY KEY (id);


--
-- Name: screening_config screening_config_key_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_config
    ADD CONSTRAINT screening_config_key_unique UNIQUE (config_key);


--
-- Name: screening_config screening_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_config
    ADD CONSTRAINT screening_config_pkey PRIMARY KEY (id);


--
-- Name: screening_data_sources screening_data_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_data_sources
    ADD CONSTRAINT screening_data_sources_pkey PRIMARY KEY (id);


--
-- Name: screening_delta_hits screening_delta_hits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_delta_hits
    ADD CONSTRAINT screening_delta_hits_pkey PRIMARY KEY (id);


--
-- Name: screening_delta_hits screening_delta_hits_subject_table_subject_id_list_table_li_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_delta_hits
    ADD CONSTRAINT screening_delta_hits_subject_table_subject_id_list_table_li_key UNIQUE (subject_table, subject_id, list_table, list_record_id);


--
-- Name: screening_delta_runs screening_delta_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_delta_runs
    ADD CONSTRAINT screening_delta_runs_pkey PRIMARY KEY (id);


--
-- Name: screening_history screening_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_history
    ADD CONSTRAINT screening_history_pkey PRIMARY KEY (id);


--
-- Name: screening_list_update_log screening_list_update_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_list_update_log
    ADD CONSTRAINT screening_list_update_log_pkey PRIMARY KEY (id);


--
-- Name: screening_metrics screening_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_metrics
    ADD CONSTRAINT screening_metrics_pkey PRIMARY KEY (id);


--
-- Name: screening_qa_cases screening_qa_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_qa_cases
    ADD CONSTRAINT screening_qa_cases_pkey PRIMARY KEY (id);


--
-- Name: screening_qa_cases screening_qa_cases_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_qa_cases
    ADD CONSTRAINT screening_qa_cases_uniq UNIQUE (query_name, expected_name);


--
-- Name: screening_qa_runs screening_qa_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_qa_runs
    ADD CONSTRAINT screening_qa_runs_pkey PRIMARY KEY (id);


--
-- Name: screening_quality_runs screening_quality_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_quality_runs
    ADD CONSTRAINT screening_quality_runs_pkey PRIMARY KEY (id);


--
-- Name: screening_queue screening_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_queue
    ADD CONSTRAINT screening_queue_pkey PRIMARY KEY (id);


--
-- Name: screening_results screening_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_results
    ADD CONSTRAINT screening_results_pkey PRIMARY KEY (id);


--
-- Name: screening_risk_criteria screening_risk_criteria_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_risk_criteria
    ADD CONSTRAINT screening_risk_criteria_pkey PRIMARY KEY (id);


--
-- Name: screening_settings screening_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_settings
    ADD CONSTRAINT screening_settings_pkey PRIMARY KEY (id);


--
-- Name: screening_tasks screening_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_tasks
    ADD CONSTRAINT screening_tasks_pkey PRIMARY KEY (task_id);


--
-- Name: screening_update_log screening_update_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_update_log
    ADD CONSTRAINT screening_update_log_pkey PRIMARY KEY (id);


--
-- Name: screening_update_logs screening_update_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_update_logs
    ADD CONSTRAINT screening_update_logs_pkey PRIMARY KEY (id);


--
-- Name: screening_watchlist screening_watchlist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_watchlist
    ADD CONSTRAINT screening_watchlist_pkey PRIMARY KEY (id);


--
-- Name: screening_whitelist_audit screening_whitelist_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_whitelist_audit
    ADD CONSTRAINT screening_whitelist_audit_pkey PRIMARY KEY (id);


--
-- Name: screening_whitelist_matches screening_whitelist_matches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_whitelist_matches
    ADD CONSTRAINT screening_whitelist_matches_pkey PRIMARY KEY (id);


--
-- Name: screening_whitelist_matches screening_whitelist_matches_whitelist_id_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_whitelist_matches
    ADD CONSTRAINT screening_whitelist_matches_whitelist_id_entity_id_key UNIQUE (whitelist_id, entity_id);


--
-- Name: screening_whitelist screening_whitelist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_whitelist
    ADD CONSTRAINT screening_whitelist_pkey PRIMARY KEY (id);


--
-- Name: screening_workflow screening_workflow_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_workflow
    ADD CONSTRAINT screening_workflow_pkey PRIMARY KEY (id);


--
-- Name: str_report_templates str_report_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.str_report_templates
    ADD CONSTRAINT str_report_templates_pkey PRIMARY KEY (id);


--
-- Name: str_report_templates str_report_templates_sector_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.str_report_templates
    ADD CONSTRAINT str_report_templates_sector_code_key UNIQUE (sector_code);


--
-- Name: succession_plans succession_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.succession_plans
    ADD CONSTRAINT succession_plans_pkey PRIMARY KEY (id);


--
-- Name: suspicious_activities suspicious_activities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.suspicious_activities
    ADD CONSTRAINT suspicious_activities_pkey PRIMARY KEY (id);


--
-- Name: system_settings system_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_pkey PRIMARY KEY (setting_key);


--
-- Name: three_lines_functions three_lines_functions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.three_lines_functions
    ADD CONSTRAINT three_lines_functions_pkey PRIMARY KEY (id);


--
-- Name: three_lines_raci_matrix three_lines_raci_matrix_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.three_lines_raci_matrix
    ADD CONSTRAINT three_lines_raci_matrix_pkey PRIMARY KEY (id);


--
-- Name: tm_alerts tm_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tm_alerts
    ADD CONSTRAINT tm_alerts_pkey PRIMARY KEY (id);


--
-- Name: tm_rules tm_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tm_rules
    ADD CONSTRAINT tm_rules_pkey PRIMARY KEY (id);


--
-- Name: tracker_declarations tracker_declarations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tracker_declarations
    ADD CONSTRAINT tracker_declarations_pkey PRIMARY KEY (id);


--
-- Name: training_certificates training_certificates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_certificates
    ADD CONSTRAINT training_certificates_pkey PRIMARY KEY (id);


--
-- Name: training_courses training_courses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_courses
    ADD CONSTRAINT training_courses_pkey PRIMARY KEY (id);


--
-- Name: training_enrollments training_enrollments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_enrollments
    ADD CONSTRAINT training_enrollments_pkey PRIMARY KEY (id);


--
-- Name: training_questions training_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_questions
    ADD CONSTRAINT training_questions_pkey PRIMARY KEY (id);


--
-- Name: training_requirements training_requirements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.training_requirements
    ADD CONSTRAINT training_requirements_pkey PRIMARY KEY (id);


--
-- Name: transaction_monitoring_alerts transaction_monitoring_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction_monitoring_alerts
    ADD CONSTRAINT transaction_monitoring_alerts_pkey PRIMARY KEY (id);


--
-- Name: transactions transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (id);


--
-- Name: pep_master unique_canonical_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_master
    ADD CONSTRAINT unique_canonical_name UNIQUE (canonical_name_en, date_of_birth);


--
-- Name: coi_campaign_employees uq_coi_campaign_employee; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_campaign_employees
    ADD CONSTRAINT uq_coi_campaign_employee UNIQUE (campaign_id, employee_id);


--
-- Name: meeting_attendance uq_meeting_member; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_attendance
    ADD CONSTRAINT uq_meeting_member UNIQUE (meeting_id, member_id);


--
-- Name: policy_acknowledgments uq_policy_acknowledgment; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_acknowledgments
    ADD CONSTRAINT uq_policy_acknowledgment UNIQUE (policy_id, employee_id);


--
-- Name: policy_acknowledgments uq_policy_employee; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_acknowledgments
    ADD CONSTRAINT uq_policy_employee UNIQUE (policy_id, employee_id);


--
-- Name: board_training_attendance uq_training_member; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_training_attendance
    ADD CONSTRAINT uq_training_member UNIQUE (training_id, member_id);


--
-- Name: user_departments user_departments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_departments
    ADD CONSTRAINT user_departments_pkey PRIMARY KEY (user_id, department_id);


--
-- Name: user_module_permissions user_module_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_module_permissions
    ADD CONSTRAINT user_module_permissions_pkey PRIMARY KEY (user_id, module);


--
-- Name: user_org_scope_rules user_org_scope_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_org_scope_rules
    ADD CONSTRAINT user_org_scope_rules_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: whistleblowing_anonymous_tokens whistleblowing_anonymous_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_anonymous_tokens
    ADD CONSTRAINT whistleblowing_anonymous_tokens_pkey PRIMARY KEY (id);


--
-- Name: whistleblowing_assignments whistleblowing_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_assignments
    ADD CONSTRAINT whistleblowing_assignments_pkey PRIMARY KEY (id);


--
-- Name: whistleblowing_attachments whistleblowing_attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_attachments
    ADD CONSTRAINT whistleblowing_attachments_pkey PRIMARY KEY (id);


--
-- Name: whistleblowing_cases whistleblowing_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_cases
    ADD CONSTRAINT whistleblowing_cases_pkey PRIMARY KEY (id);


--
-- Name: whistleblowing_categories whistleblowing_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_categories
    ADD CONSTRAINT whistleblowing_categories_pkey PRIMARY KEY (id);


--
-- Name: whistleblowing_stats whistleblowing_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_stats
    ADD CONSTRAINT whistleblowing_stats_pkey PRIMARY KEY (id);


--
-- Name: whistleblowing_updates whistleblowing_updates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_updates
    ADD CONSTRAINT whistleblowing_updates_pkey PRIMARY KEY (id);


--
-- Name: idx_ai_suggestions_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ai_suggestions_created ON public.ai_suggestions USING btree (created_at);


--
-- Name: idx_ai_suggestions_object; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ai_suggestions_object ON public.ai_suggestions USING btree (object_type, object_id);


--
-- Name: idx_alerts_customer; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alerts_customer ON public.tm_alerts USING btree (customer_id);


--
-- Name: idx_alerts_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alerts_date ON public.tm_alerts USING btree (alert_date DESC);


--
-- Name: idx_alerts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alerts_status ON public.tm_alerts USING btree (status);


--
-- Name: idx_aliases_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aliases_name ON public.pep_aliases USING gin (alias_name public.gin_trgm_ops);


--
-- Name: idx_aliases_pep_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aliases_pep_id ON public.pep_aliases USING btree (pep_id);


--
-- Name: idx_aml_alerts_assigned; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aml_alerts_assigned ON public.aml_alerts USING btree (assigned_to);


--
-- Name: idx_aml_alerts_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aml_alerts_created ON public.aml_alerts USING btree (created_at);


--
-- Name: idx_aml_alerts_customer; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aml_alerts_customer ON public.aml_alerts USING btree (customer_id);


--
-- Name: idx_aml_alerts_resolved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aml_alerts_resolved ON public.aml_alerts USING btree (resolved_by);


--
-- Name: idx_aml_alerts_scrres; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aml_alerts_scrres ON public.aml_alerts USING btree (screening_result_id);


--
-- Name: idx_aml_alerts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aml_alerts_status ON public.aml_alerts USING btree (alert_status);


--
-- Name: idx_aml_mon_reviews_plan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aml_mon_reviews_plan ON public.aml_monitoring_reviews USING btree (plan_id);


--
-- Name: idx_aml_unusual_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aml_unusual_status ON public.aml_unusual_transactions USING btree (status);


--
-- Name: idx_api_audit_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_audit_key ON public.api_audit_log USING btree (key_id, created_at DESC);


--
-- Name: idx_api_audit_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_audit_time ON public.api_audit_log USING btree (created_at DESC);


--
-- Name: idx_appetite_category_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_appetite_category_active ON public.risk_appetite_statements USING btree (category_id, effective_to);


--
-- Name: idx_audit_findings_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_findings_project ON public.audit_findings USING btree (project_id);


--
-- Name: idx_audit_findings_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_findings_severity ON public.audit_findings USING btree (severity);


--
-- Name: idx_audit_findings_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_findings_status ON public.audit_findings USING btree (status);


--
-- Name: idx_audit_logs_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_logs_created ON public.audit_logs USING btree (created_at DESC);


--
-- Name: idx_audit_logs_module; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_logs_module ON public.audit_logs USING btree (module);


--
-- Name: idx_audit_logs_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_logs_user ON public.audit_logs USING btree (user_id);


--
-- Name: idx_audit_projects_plan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_projects_plan ON public.audit_projects USING btree (plan_id);


--
-- Name: idx_audit_projects_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_projects_status ON public.audit_projects USING btree (status);


--
-- Name: idx_audit_working_papers_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_working_papers_project ON public.audit_working_papers USING btree (project_id);


--
-- Name: idx_aws_approver; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aws_approver ON public.approval_workflow_stages USING btree (approver_user_id);


--
-- Name: idx_aws_wf; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aws_wf ON public.approval_workflow_stages USING btree (workflow_id, stage_order);


--
-- Name: idx_carbon_activity_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_carbon_activity_period ON public.carbon_activity_entries USING btree (reporting_period_id, scope);


--
-- Name: idx_carbon_entries_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_carbon_entries_period ON public.carbon_activity_entries USING btree (reporting_period_id);


--
-- Name: idx_carbon_factors_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_carbon_factors_code ON public.carbon_emission_factors USING btree (factor_code, effective_from);


--
-- Name: idx_carbon_factors_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_carbon_factors_lookup ON public.carbon_emission_factors USING btree (scope, category, activity, unit, effective_from);


--
-- Name: idx_carbon_financed_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_carbon_financed_period ON public.carbon_financed_exposures USING btree (reporting_period_id);


--
-- Name: idx_case_reminders; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_reminders ON public.case_reminders USING btree (case_id, sent_at DESC);


--
-- Name: idx_cases_assigned; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_assigned ON public.cases USING btree (assigned_to);


--
-- Name: idx_cases_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_due ON public.cases USING btree (due_date);


--
-- Name: idx_cases_party; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_party ON public.cases USING btree (party_id);


--
-- Name: idx_cases_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_status ON public.cases USING btree (status);


--
-- Name: idx_cases_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_type ON public.cases USING btree (case_type);


--
-- Name: idx_cd_employee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cd_employee ON public.conduct_declarations USING btree (employee_id);


--
-- Name: idx_cd_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cd_period ON public.conduct_declarations USING btree (period_year, period_quarter);


--
-- Name: idx_cd_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cd_status ON public.conduct_declarations USING btree (review_status);


--
-- Name: idx_cm_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cm_name ON public.confirmed_matches USING btree (normalized_name);


--
-- Name: idx_cm_queue; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cm_queue ON public.confirmed_matches USING btree (queue_id);


--
-- Name: idx_cm_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cm_score ON public.confirmed_matches USING btree (match_score DESC);


--
-- Name: idx_cm_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cm_source ON public.confirmed_matches USING btree (list_source);


--
-- Name: idx_cm_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cm_status ON public.confirmed_matches USING btree (status, confirmed_at DESC);


--
-- Name: idx_coi_employee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_coi_employee ON public.coi_disclosures USING btree (employee_id);


--
-- Name: idx_coi_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_coi_status ON public.coi_disclosures USING btree (review_status);


--
-- Name: idx_committees_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_committees_active ON public.committees USING btree (is_active);


--
-- Name: idx_compliance_events_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_compliance_events_created ON public.compliance_events USING btree (created_at DESC);


--
-- Name: idx_compliance_events_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_compliance_events_source ON public.compliance_events USING btree (source_module, source_table, source_record_id);


--
-- Name: idx_compliance_events_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_compliance_events_status ON public.compliance_events USING btree (status);


--
-- Name: idx_compliance_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_compliance_events_type ON public.compliance_events USING btree (event_type);


--
-- Name: idx_control_test_results_control; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_control_test_results_control ON public.control_test_results USING btree (control_id);


--
-- Name: idx_corporate_company; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_corporate_company ON public.pep_corporate_links USING btree (company_name);


--
-- Name: idx_corporate_current; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_corporate_current ON public.pep_corporate_links USING btree (is_current);


--
-- Name: idx_corporate_pep_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_corporate_pep_id ON public.pep_corporate_links USING btree (pep_id);


--
-- Name: idx_cust_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cust_ref ON public.customers USING btree (customer_reference);


--
-- Name: idx_cust_risk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cust_risk ON public.customers USING btree (risk_classification);


--
-- Name: idx_dct_campaign; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dct_campaign ON public.declaration_campaign_targets USING btree (campaign_id, status);


--
-- Name: idx_dct_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dct_user ON public.declaration_campaign_targets USING btree (user_id);


--
-- Name: idx_docappr_policy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_docappr_policy ON public.document_approvals USING btree (policy_id, stage_order);


--
-- Name: idx_docappr_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_docappr_user ON public.document_approvals USING btree (approver_user_id, status);


--
-- Name: idx_duplicates_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_duplicates_score ON public.pep_duplicate_candidates USING btree (match_score DESC);


--
-- Name: idx_duplicates_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_duplicates_status ON public.pep_duplicate_candidates USING btree (status);


--
-- Name: idx_ekyc_audit_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ekyc_audit_created ON public.ekyc_audit_log USING btree (created_at);


--
-- Name: idx_ekyc_audit_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ekyc_audit_session ON public.ekyc_audit_log USING btree (session_id);


--
-- Name: idx_ekyc_audit_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ekyc_audit_user ON public.ekyc_audit_log USING btree (user_id);


--
-- Name: idx_ekyc_document_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ekyc_document_session ON public.ekyc_document USING btree (session_id);


--
-- Name: idx_ekyc_result_decision; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ekyc_result_decision ON public.ekyc_result USING btree (decision);


--
-- Name: idx_ekyc_result_national_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ekyc_result_national_id ON public.ekyc_result USING btree (national_id);


--
-- Name: idx_ekyc_session_assigned_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ekyc_session_assigned_to ON public.ekyc_session USING btree (assigned_to);


--
-- Name: idx_ekyc_session_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ekyc_session_status ON public.ekyc_session USING btree (status);


--
-- Name: idx_ekyc_session_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ekyc_session_token ON public.ekyc_session USING btree (session_token);


--
-- Name: idx_employee_screenings_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_employee_screenings_user ON public.employee_screenings USING btree (user_id, screened_at DESC);


--
-- Name: idx_esg_disclosure_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_esg_disclosure_period ON public.esg_disclosure_items USING btree (reporting_period_id, framework);


--
-- Name: idx_event_routing_rules_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_routing_rules_enabled ON public.event_routing_rules USING btree (enabled);


--
-- Name: idx_event_routing_rules_pattern; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_routing_rules_pattern ON public.event_routing_rules USING btree (event_type_pattern);


--
-- Name: idx_generic_attachments_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_generic_attachments_parent ON public.generic_attachments USING btree (module, record_type, record_id) WHERE (is_deleted = 0);


--
-- Name: idx_ghe_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ghe_date ON public.ghe_records USING btree (event_date);


--
-- Name: idx_ghe_employee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ghe_employee ON public.ghe_records USING btree (employee_id);


--
-- Name: idx_ghe_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ghe_status ON public.ghe_records USING btree (approval_status);


--
-- Name: idx_hist_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hist_date ON public.screening_history USING btree (screening_date DESC);


--
-- Name: idx_hist_module; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hist_module ON public.screening_history USING btree (source_module);


--
-- Name: idx_hist_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hist_name ON public.screening_history USING btree (entity_name);


--
-- Name: idx_hist_result; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hist_result ON public.screening_history USING btree (screening_result_id);


--
-- Name: idx_hist_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hist_score ON public.screening_history USING btree (highest_score DESC);


--
-- Name: idx_ibl_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ibl_active ON public.internal_blacklist USING btree (is_active);


--
-- Name: idx_ibl_fullname; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ibl_fullname ON public.internal_blacklist USING gin (full_name public.gin_trgm_ops);


--
-- Name: idx_ibl_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_ibl_source_id ON public.internal_blacklist USING btree (source_id);


--
-- Name: idx_internal_blacklist_name_search_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_internal_blacklist_name_search_trgm ON public.internal_blacklist USING gin (name_search public.gin_trgm_ops);


--
-- Name: idx_internal_pep_name_search_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_internal_pep_name_search_trgm ON public.internal_pep USING gin (name_search public.gin_trgm_ops);


--
-- Name: idx_kri_measurements_kri_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_kri_measurements_kri_date ON public.kri_measurements USING btree (kri_id, measurement_date DESC);


--
-- Name: idx_kyc_bo_decl_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_kyc_bo_decl_subject ON public.kyc_bo_declarations USING btree (subject, subject_id);


--
-- Name: idx_kyc_bo_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_kyc_bo_subject ON public.kyc_beneficial_owners USING btree (subject, subject_id);


--
-- Name: idx_kyc_ratings_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_kyc_ratings_subject ON public.kyc_risk_ratings USING btree (subject, subject_id, is_current);


--
-- Name: idx_ln_documents_loan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ln_documents_loan ON public.ln_documents USING btree (loan_id);


--
-- Name: idx_ln_documents_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_ln_documents_uniq ON public.ln_documents USING btree (loan_id, doc_type) WHERE (loan_id IS NOT NULL);


--
-- Name: idx_ln_er_loan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ln_er_loan ON public.ln_early_repayments USING btree (loan_id);


--
-- Name: idx_ln_loans_branch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ln_loans_branch ON public.ln_loans USING btree (branch_code);


--
-- Name: idx_ln_loans_client; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ln_loans_client ON public.ln_loans USING btree (client_id);


--
-- Name: idx_ln_loans_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ln_loans_status ON public.ln_loans USING btree (status);


--
-- Name: idx_ln_visits_loan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ln_visits_loan ON public.ln_visits USING btree (loan_id);


--
-- Name: idx_mfa_audit_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mfa_audit_user ON public.mfa_audit USING btree (user_id, performed_at DESC);


--
-- Name: idx_notifications_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notifications_created ON public.notifications USING btree (created_at DESC);


--
-- Name: idx_notifications_user_unread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notifications_user_unread ON public.notifications USING btree (user_id, is_read);


--
-- Name: idx_org_units_legacy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_units_legacy ON public.org_units USING btree (legacy_department_id);


--
-- Name: idx_org_units_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_units_parent ON public.org_units USING btree (parent_id);


--
-- Name: idx_org_units_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_units_path ON public.org_units USING btree (path text_pattern_ops);


--
-- Name: idx_org_units_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_units_type ON public.org_units USING btree (unit_type_id);


--
-- Name: idx_osf_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_osf_run ON public.ongoing_screening_findings USING btree (run_id);


--
-- Name: idx_osf_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_osf_status ON public.ongoing_screening_findings USING btree (status, created_at DESC);


--
-- Name: idx_parties_cr_number_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parties_cr_number_hash ON public.parties USING btree (cr_number_hash);


--
-- Name: idx_parties_id_number_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parties_id_number_hash ON public.parties USING btree (id_number_hash);


--
-- Name: idx_parties_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parties_name ON public.parties USING gin (full_name public.gin_trgm_ops);


--
-- Name: idx_party_links_party; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_party_links_party ON public.party_links USING btree (party_id);


--
-- Name: idx_party_links_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_party_links_source ON public.party_links USING btree (source_table, source_record_id);


--
-- Name: idx_pep_master_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pep_master_active ON public.pep_master USING btree (is_active);


--
-- Name: idx_pep_master_dob; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pep_master_dob ON public.pep_master USING btree (date_of_birth);


--
-- Name: idx_pep_master_name_ar; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pep_master_name_ar ON public.pep_master USING gin (canonical_name_ar public.gin_trgm_ops);


--
-- Name: idx_pep_master_name_en; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pep_master_name_en ON public.pep_master USING gin (canonical_name_en public.gin_trgm_ops);


--
-- Name: idx_pep_master_search; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pep_master_search ON public.pep_master USING gin (search_vector);


--
-- Name: idx_phishing_events_campaign; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_phishing_events_campaign ON public.phishing_events USING btree (campaign_id);


--
-- Name: idx_phishing_recipients_campaign; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_phishing_recipients_campaign ON public.phishing_recipients USING btree (campaign_id);


--
-- Name: idx_phishing_recipients_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_phishing_recipients_token ON public.phishing_recipients USING btree (token);


--
-- Name: idx_polapp_policy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_polapp_policy ON public.policy_applicability USING btree (policy_id);


--
-- Name: idx_polapp_unit; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_polapp_unit ON public.policy_applicability USING btree (org_unit_id);


--
-- Name: idx_policies_doctype; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_policies_doctype ON public.policies USING btree (document_type_id);


--
-- Name: idx_policies_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_policies_org ON public.policies USING btree (org_unit_id);


--
-- Name: idx_policy_board_approvals_policy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_policy_board_approvals_policy ON public.policy_board_approvals USING btree (policy_id);


--
-- Name: idx_positions_current; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_current ON public.pep_positions USING btree (is_current);


--
-- Name: idx_positions_dates; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_dates ON public.pep_positions USING btree (start_date, end_date);


--
-- Name: idx_positions_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_org ON public.pep_positions USING btree (organization_en);


--
-- Name: idx_positions_pep_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_pep_id ON public.pep_positions USING btree (pep_id);


--
-- Name: idx_pr_capital_type_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_capital_type_date ON public.pr_capital_events USING btree (capital_type, effective_date);


--
-- Name: idx_pr_key_functions_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pr_key_functions_code ON public.pr_key_functions USING btree (function_code);


--
-- Name: idx_rc_actions_finding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_actions_finding ON public.rc_corrective_actions USING btree (finding_id);


--
-- Name: idx_rc_alerts_live_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_rc_alerts_live_uniq ON public.rc_alerts USING btree (alert_type, COALESCE(control_id, 0), COALESCE(evidence_id, 0), COALESCE(finding_id, 0)) WHERE ((status)::text = ANY ((ARRAY['open'::character varying, 'acknowledged'::character varying])::text[]));


--
-- Name: idx_rc_alerts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_alerts_status ON public.rc_alerts USING btree (status);


--
-- Name: idx_rc_control_reqs_req; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_control_reqs_req ON public.rc_control_requirements USING btree (requirement_id);


--
-- Name: idx_rc_controls_area; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_controls_area ON public.rc_controls USING btree (area);


--
-- Name: idx_rc_controls_pack; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_controls_pack ON public.rc_controls USING btree (pack_code);


--
-- Name: idx_rc_controls_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_controls_status ON public.rc_controls USING btree (last_status);


--
-- Name: idx_rc_evidence_control; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_evidence_control ON public.rc_evidence USING btree (control_id);


--
-- Name: idx_rc_evidence_valid_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_evidence_valid_to ON public.rc_evidence USING btree (valid_to);


--
-- Name: idx_rc_finding_controls_control; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_finding_controls_control ON public.rc_finding_controls USING btree (control_id);


--
-- Name: idx_rc_finding_events_finding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_finding_events_finding ON public.rc_finding_events USING btree (finding_id, created_at);


--
-- Name: idx_rc_findings_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_findings_due ON public.rc_findings USING btree (due_date);


--
-- Name: idx_rc_findings_source_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_rc_findings_source_ref ON public.rc_findings USING btree (source, source_ref) WHERE (source_ref IS NOT NULL);


--
-- Name: idx_rc_findings_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_findings_status ON public.rc_findings USING btree (status);


--
-- Name: idx_rc_param_changes_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_param_changes_key ON public.rc_parameter_changes USING btree (param_key);


--
-- Name: idx_rc_param_changes_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_param_changes_status ON public.rc_parameter_changes USING btree (status);


--
-- Name: idx_rc_parameters_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_parameters_key ON public.rc_parameters USING btree (param_key);


--
-- Name: idx_rc_runs_control; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_runs_control ON public.rc_control_runs USING btree (control_id, started_at DESC);


--
-- Name: idx_rc_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rc_runs_status ON public.rc_control_runs USING btree (status);


--
-- Name: idx_reminder_log; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reminder_log ON public.reminder_log USING btree (campaign_id, sent_at DESC);


--
-- Name: idx_risk_score_history_risk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_score_history_risk ON public.risk_score_history USING btree (risk_id, recorded_at);


--
-- Name: idx_risk_source_links_risk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_source_links_risk ON public.risk_source_links USING btree (risk_id);


--
-- Name: idx_risk_source_links_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_source_links_source ON public.risk_source_links USING btree (source_module, source_table, source_record_id);


--
-- Name: idx_risk_treatments_owner_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_treatments_owner_status ON public.risk_treatments USING btree (treatment_owner_id, status);


--
-- Name: idx_risk_treatments_risk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_treatments_risk ON public.risk_treatments USING btree (risk_id);


--
-- Name: idx_risks_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risks_category ON public.risks USING btree (category_id);


--
-- Name: idx_risks_next_review; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risks_next_review ON public.risks USING btree (next_review_date);


--
-- Name: idx_risks_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risks_owner ON public.risks USING btree (risk_owner_id);


--
-- Name: idx_risks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risks_status ON public.risks USING btree (status);


--
-- Name: idx_sclu_source_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sclu_source_run ON public.screening_list_update_log USING btree (source, run_at DESC);


--
-- Name: idx_screening_whitelist_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_screening_whitelist_norm ON public.screening_whitelist USING btree (normalized_name) WHERE (normalized_name IS NOT NULL);


--
-- Name: idx_sdh_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sdh_status ON public.screening_delta_hits USING btree (status, found_at DESC);


--
-- Name: idx_sh_result_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sh_result_id ON public.screening_history USING btree (screening_result_id);


--
-- Name: idx_sources_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sources_active ON public.pep_sources USING btree (is_active);


--
-- Name: idx_sources_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sources_name ON public.pep_sources USING btree (source_name);


--
-- Name: idx_sources_pep_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sources_pep_id ON public.pep_sources USING btree (pep_id);


--
-- Name: idx_sqr_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sqr_run ON public.screening_quality_runs USING btree (run_at DESC);


--
-- Name: idx_src_band; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_src_band ON public.screening_risk_criteria USING btree (band, is_active);


--
-- Name: idx_sw_assigned; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sw_assigned ON public.screening_workflow USING btree (assigned_to);


--
-- Name: idx_sw_result; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sw_result ON public.screening_workflow USING btree (screening_result_id);


--
-- Name: idx_sw_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sw_status ON public.screening_workflow USING btree (workflow_status);


--
-- Name: idx_tx_alert; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tx_alert ON public.transactions USING btree (alert_raised) WHERE (alert_raised = 1);


--
-- Name: idx_tx_amount; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tx_amount ON public.transactions USING btree (amount DESC);


--
-- Name: idx_tx_customer_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tx_customer_date ON public.transactions USING btree (customer_id, transaction_date DESC);


--
-- Name: idx_tx_customer_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tx_customer_id ON public.transactions USING btree (customer_id);


--
-- Name: idx_tx_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tx_date ON public.transactions USING btree (transaction_date DESC);


--
-- Name: idx_tx_pan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tx_pan ON public.transactions USING btree (counterparty_account) WHERE (counterparty_account IS NOT NULL);


--
-- Name: idx_tx_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tx_ref ON public.transactions USING btree (transaction_reference);


--
-- Name: idx_tx_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tx_type ON public.transactions USING btree (transaction_type);


--
-- Name: idx_uosr_root; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_uosr_root ON public.user_org_scope_rules USING btree (root_unit_id);


--
-- Name: idx_uosr_unit; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_uosr_unit ON public.user_org_scope_rules USING btree (org_unit_id);


--
-- Name: idx_uosr_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_uosr_user ON public.user_org_scope_rules USING btree (user_id);


--
-- Name: idx_update_logs_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_update_logs_source ON public.pep_update_logs USING btree (source_name);


--
-- Name: idx_update_logs_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_update_logs_started ON public.pep_update_logs USING btree (started_at DESC);


--
-- Name: idx_users_org_unit; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_org_unit ON public.users USING btree (org_unit_id);


--
-- Name: idx_watchlist_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_watchlist_source_id ON public.screening_watchlist USING btree (source, source_id);


--
-- Name: idx_watchlist_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_updated_at ON public.screening_watchlist USING btree (updated_at);


--
-- Name: idx_wba_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wba_case ON public.whistleblowing_assignments USING btree (case_id, assigned_at_ts DESC);


--
-- Name: idx_wba_current; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wba_current ON public.whistleblowing_assignments USING btree (case_id) WHERE is_current;


--
-- Name: idx_wl_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_active ON public.screening_watchlist USING btree (is_active);


--
-- Name: idx_wl_audit_entry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_audit_entry ON public.screening_whitelist_audit USING btree (whitelist_id, performed_at DESC);


--
-- Name: idx_wl_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_due ON public.screening_whitelist USING btree (next_screening_at) WHERE (status = 'Active'::text);


--
-- Name: idx_wl_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_entity ON public.screening_whitelist USING btree (matched_entity_id);


--
-- Name: idx_wl_last_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_last_updated ON public.screening_watchlist USING btree (last_updated DESC);


--
-- Name: idx_wl_metaphone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_metaphone ON public.screening_watchlist USING btree (name_metaphone);


--
-- Name: idx_wl_original_lower; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_original_lower ON public.screening_watchlist USING btree (lower(original_name));


--
-- Name: idx_wl_soundex; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_soundex ON public.screening_watchlist USING btree (name_soundex);


--
-- Name: idx_wl_trgm_aliases; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_trgm_aliases ON public.screening_watchlist USING gin (aliases public.gin_trgm_ops);


--
-- Name: idx_wl_trgm_aliases_ar; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_trgm_aliases_ar ON public.screening_watchlist USING gin (aliases_arabic public.gin_trgm_ops);


--
-- Name: idx_wl_trgm_full; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_trgm_full ON public.screening_watchlist USING gin (full_name public.gin_trgm_ops);


--
-- Name: idx_wl_trgm_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_trgm_norm ON public.screening_watchlist USING gin (name_normalized public.gin_trgm_ops);


--
-- Name: idx_wl_trgm_original; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wl_trgm_original ON public.screening_watchlist USING gin (original_name public.gin_trgm_ops);


--
-- Name: idx_wlaudit_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wlaudit_by ON public.screening_whitelist_audit USING btree (performed_by);


--
-- Name: idx_wlm_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wlm_entity ON public.screening_whitelist_matches USING btree (entity_id);


--
-- Name: idx_wlm_wl; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wlm_wl ON public.screening_whitelist_matches USING btree (whitelist_id);


--
-- Name: ix_academy_audit_learner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_academy_audit_learner ON public.academy_audit USING btree (learner_id, created_at DESC);


--
-- Name: ix_academy_learners_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_academy_learners_created ON public.academy_learners USING btree (created_at);


--
-- Name: ix_academy_learners_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_academy_learners_domain ON public.academy_learners USING btree (email_domain);


--
-- Name: ix_academy_otp_learner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_academy_otp_learner ON public.academy_otp USING btree (learner_id, created_at DESC);


--
-- Name: uq_carbon_period_metrics; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_carbon_period_metrics ON public.carbon_period_metrics USING btree (reporting_period_id);


--
-- Name: uq_carbon_period_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_carbon_period_workflow ON public.carbon_period_workflow USING btree (reporting_period_id);


--
-- Name: uq_carbon_scope_config_label; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_carbon_scope_config_label ON public.carbon_scope_config USING btree (company_label);


--
-- Name: uq_fra_verifiers_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_fra_verifiers_name ON public.fra_verifiers USING btree (name);


--
-- Name: uq_rc_readiness_snapshot; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_rc_readiness_snapshot ON public.rc_readiness_snapshots USING btree (snapshot_date, COALESCE(framework_id, 0), COALESCE(area_code, ''::character varying));


--
-- Name: ux_academy_learners_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_academy_learners_email ON public.academy_learners USING btree (lower(email)) WHERE (status <> 'erased'::text);


--
-- Name: screening_results trg_aml_alert_on_screening; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_aml_alert_on_screening AFTER INSERT ON public.screening_results FOR EACH ROW EXECUTE FUNCTION public.fn_create_aml_alert();


--
-- Name: audit_logs trg_audit_logs_chain; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_logs_chain BEFORE INSERT ON public.audit_logs FOR EACH ROW EXECUTE FUNCTION public.audit_logs_chain();


--
-- Name: audit_logs trg_audit_logs_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_logs_immutable BEFORE DELETE OR UPDATE ON public.audit_logs FOR EACH ROW EXECUTE FUNCTION public.audit_logs_immutable();


--
-- Name: org_units trg_org_units_cascade; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_org_units_cascade AFTER UPDATE OF path ON public.org_units FOR EACH ROW EXECUTE FUNCTION public.org_units_cascade_path();


--
-- Name: org_units trg_org_units_path; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_org_units_path BEFORE INSERT OR UPDATE OF parent_id ON public.org_units FOR EACH ROW EXECUTE FUNCTION public.org_units_set_path();


--
-- Name: screening_watchlist trg_watchlist_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_watchlist_updated_at BEFORE UPDATE ON public.screening_watchlist FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: academy_attempts academy_attempts_enrollment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_attempts
    ADD CONSTRAINT academy_attempts_enrollment_id_fkey FOREIGN KEY (enrollment_id) REFERENCES public.academy_enrollments(id) ON DELETE CASCADE;


--
-- Name: academy_certificates academy_certificates_course_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_certificates
    ADD CONSTRAINT academy_certificates_course_id_fkey FOREIGN KEY (course_id) REFERENCES public.academy_courses(id);


--
-- Name: academy_certificates academy_certificates_learner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_certificates
    ADD CONSTRAINT academy_certificates_learner_id_fkey FOREIGN KEY (learner_id) REFERENCES public.academy_learners(id) ON DELETE SET NULL;


--
-- Name: academy_enrollments academy_enrollments_course_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_enrollments
    ADD CONSTRAINT academy_enrollments_course_id_fkey FOREIGN KEY (course_id) REFERENCES public.academy_courses(id);


--
-- Name: academy_enrollments academy_enrollments_learner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_enrollments
    ADD CONSTRAINT academy_enrollments_learner_id_fkey FOREIGN KEY (learner_id) REFERENCES public.academy_learners(id) ON DELETE CASCADE;


--
-- Name: academy_lessons academy_lessons_course_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_lessons
    ADD CONSTRAINT academy_lessons_course_id_fkey FOREIGN KEY (course_id) REFERENCES public.academy_courses(id) ON DELETE CASCADE;


--
-- Name: academy_otp academy_otp_learner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_otp
    ADD CONSTRAINT academy_otp_learner_id_fkey FOREIGN KEY (learner_id) REFERENCES public.academy_learners(id) ON DELETE CASCADE;


--
-- Name: academy_questions academy_questions_course_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_questions
    ADD CONSTRAINT academy_questions_course_id_fkey FOREIGN KEY (course_id) REFERENCES public.academy_courses(id) ON DELETE CASCADE;


--
-- Name: academy_video_progress academy_video_progress_enrollment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_video_progress
    ADD CONSTRAINT academy_video_progress_enrollment_id_fkey FOREIGN KEY (enrollment_id) REFERENCES public.academy_enrollments(id) ON DELETE CASCADE;


--
-- Name: academy_video_progress academy_video_progress_lesson_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.academy_video_progress
    ADD CONSTRAINT academy_video_progress_lesson_id_fkey FOREIGN KEY (lesson_id) REFERENCES public.academy_lessons(id) ON DELETE CASCADE;


--
-- Name: ai_intake_items ai_intake_items_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_intake_items
    ADD CONSTRAINT ai_intake_items_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: ai_intake_items ai_intake_items_decided_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_intake_items
    ADD CONSTRAINT ai_intake_items_decided_by_fkey FOREIGN KEY (decided_by) REFERENCES public.users(id);


--
-- Name: ai_intents ai_intents_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_intents
    ADD CONSTRAINT ai_intents_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: ai_jobs ai_jobs_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_jobs
    ADD CONSTRAINT ai_jobs_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: ai_playbook_runs ai_playbook_runs_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_playbook_runs
    ADD CONSTRAINT ai_playbook_runs_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: ai_playbook_runs ai_playbook_runs_finding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_playbook_runs
    ADD CONSTRAINT ai_playbook_runs_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.rc_findings(id) ON DELETE SET NULL;


--
-- Name: ai_playbook_steps ai_playbook_steps_playbook_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_playbook_steps
    ADD CONSTRAINT ai_playbook_steps_playbook_code_fkey FOREIGN KEY (playbook_code) REFERENCES public.ai_playbooks(code) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ai_playbooks ai_playbooks_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_playbooks
    ADD CONSTRAINT ai_playbooks_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: ai_suggestions ai_suggestions_decided_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_suggestions
    ADD CONSTRAINT ai_suggestions_decided_by_fkey FOREIGN KEY (decided_by) REFERENCES public.users(id);


--
-- Name: ai_suggestions ai_suggestions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_suggestions
    ADD CONSTRAINT ai_suggestions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: aml_alerts aml_alerts_assigned_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_alerts
    ADD CONSTRAINT aml_alerts_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: aml_alerts aml_alerts_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_alerts
    ADD CONSTRAINT aml_alerts_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: aml_alerts aml_alerts_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_alerts
    ADD CONSTRAINT aml_alerts_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE SET NULL;


--
-- Name: aml_alerts aml_alerts_resolved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_alerts
    ADD CONSTRAINT aml_alerts_resolved_by_fkey FOREIGN KEY (resolved_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: aml_alerts aml_alerts_screening_result_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_alerts
    ADD CONSTRAINT aml_alerts_screening_result_id_fkey FOREIGN KEY (screening_result_id) REFERENCES public.screening_results(id) ON DELETE SET NULL;


--
-- Name: aml_annual_reports aml_annual_reports_approval_recorded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_annual_reports
    ADD CONSTRAINT aml_annual_reports_approval_recorded_by_fkey FOREIGN KEY (approval_recorded_by) REFERENCES public.users(id);


--
-- Name: aml_annual_reports aml_annual_reports_generated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_annual_reports
    ADD CONSTRAINT aml_annual_reports_generated_by_fkey FOREIGN KEY (generated_by) REFERENCES public.users(id);


--
-- Name: aml_key_roles aml_key_roles_holder_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_key_roles
    ADD CONSTRAINT aml_key_roles_holder_user_id_fkey FOREIGN KEY (holder_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: aml_key_roles aml_key_roles_reports_to_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_key_roles
    ADD CONSTRAINT aml_key_roles_reports_to_user_id_fkey FOREIGN KEY (reports_to_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: aml_key_roles aml_key_roles_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_key_roles
    ADD CONSTRAINT aml_key_roles_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: aml_monitoring_plans aml_monitoring_plans_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_monitoring_plans
    ADD CONSTRAINT aml_monitoring_plans_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: aml_monitoring_reviews aml_monitoring_reviews_finding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_monitoring_reviews
    ADD CONSTRAINT aml_monitoring_reviews_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.rc_findings(id) ON DELETE SET NULL;


--
-- Name: aml_monitoring_reviews aml_monitoring_reviews_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_monitoring_reviews
    ADD CONSTRAINT aml_monitoring_reviews_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.aml_monitoring_plans(id) ON DELETE CASCADE;


--
-- Name: aml_monitoring_reviews aml_monitoring_reviews_reviewer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_monitoring_reviews
    ADD CONSTRAINT aml_monitoring_reviews_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES public.users(id);


--
-- Name: aml_unusual_transactions aml_unusual_transactions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_unusual_transactions
    ADD CONSTRAINT aml_unusual_transactions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: aml_unusual_transactions aml_unusual_transactions_decision_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_unusual_transactions
    ADD CONSTRAINT aml_unusual_transactions_decision_by_fkey FOREIGN KEY (decision_by) REFERENCES public.users(id);


--
-- Name: aml_unusual_transactions aml_unusual_transactions_party_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aml_unusual_transactions
    ADD CONSTRAINT aml_unusual_transactions_party_id_fkey FOREIGN KEY (party_id) REFERENCES public.parties(id) ON DELETE SET NULL;


--
-- Name: annual_audit_plans annual_audit_plans_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annual_audit_plans
    ADD CONSTRAINT annual_audit_plans_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id);


--
-- Name: annual_audit_plans annual_audit_plans_approved_by_meeting_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annual_audit_plans
    ADD CONSTRAINT annual_audit_plans_approved_by_meeting_id_fkey FOREIGN KEY (approved_by_meeting_id) REFERENCES public.board_meetings(id);


--
-- Name: api_audit_log api_audit_log_key_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_audit_log
    ADD CONSTRAINT api_audit_log_key_id_fkey FOREIGN KEY (key_id) REFERENCES public.api_keys(id) ON DELETE SET NULL;


--
-- Name: api_keys api_keys_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: api_keys api_keys_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: approval_workflow_stages approval_workflow_stages_approver_org_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_stages
    ADD CONSTRAINT approval_workflow_stages_approver_org_unit_id_fkey FOREIGN KEY (approver_org_unit_id) REFERENCES public.org_units(id) ON DELETE SET NULL;


--
-- Name: approval_workflow_stages approval_workflow_stages_approver_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_stages
    ADD CONSTRAINT approval_workflow_stages_approver_user_id_fkey FOREIGN KEY (approver_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: approval_workflow_stages approval_workflow_stages_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_stages
    ADD CONSTRAINT approval_workflow_stages_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.approval_workflows(id) ON DELETE CASCADE;


--
-- Name: approval_workflows approval_workflows_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflows
    ADD CONSTRAINT approval_workflows_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: approval_workflows approval_workflows_document_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflows
    ADD CONSTRAINT approval_workflows_document_type_id_fkey FOREIGN KEY (document_type_id) REFERENCES public.document_types(id) ON DELETE CASCADE;


--
-- Name: approval_workflows approval_workflows_org_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflows
    ADD CONSTRAINT approval_workflows_org_unit_id_fkey FOREIGN KEY (org_unit_id) REFERENCES public.org_units(id) ON DELETE SET NULL;


--
-- Name: audit_findings audit_findings_linked_control_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_findings
    ADD CONSTRAINT audit_findings_linked_control_id_fkey FOREIGN KEY (linked_control_id) REFERENCES public.controls(id);


--
-- Name: audit_findings audit_findings_linked_risk_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_findings
    ADD CONSTRAINT audit_findings_linked_risk_id_fkey FOREIGN KEY (linked_risk_id) REFERENCES public.risks(id);


--
-- Name: audit_findings audit_findings_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_findings
    ADD CONSTRAINT audit_findings_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.audit_projects(id) ON DELETE CASCADE;


--
-- Name: audit_findings audit_findings_responsible_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_findings
    ADD CONSTRAINT audit_findings_responsible_person_id_fkey FOREIGN KEY (responsible_person_id) REFERENCES public.users(id);


--
-- Name: audit_findings audit_findings_verified_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_findings
    ADD CONSTRAINT audit_findings_verified_by_fkey FOREIGN KEY (verified_by) REFERENCES public.users(id);


--
-- Name: audit_programs audit_programs_control_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_programs
    ADD CONSTRAINT audit_programs_control_id_fkey FOREIGN KEY (control_id) REFERENCES public.controls(id);


--
-- Name: audit_programs audit_programs_performed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_programs
    ADD CONSTRAINT audit_programs_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(id);


--
-- Name: audit_programs audit_programs_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_programs
    ADD CONSTRAINT audit_programs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.audit_projects(id) ON DELETE CASCADE;


--
-- Name: audit_programs audit_programs_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_programs
    ADD CONSTRAINT audit_programs_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id);


--
-- Name: audit_projects audit_projects_auditable_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_projects
    ADD CONSTRAINT audit_projects_auditable_area_id_fkey FOREIGN KEY (auditable_area_id) REFERENCES public.audit_universe(id);


--
-- Name: audit_projects audit_projects_lead_auditor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_projects
    ADD CONSTRAINT audit_projects_lead_auditor_id_fkey FOREIGN KEY (lead_auditor_id) REFERENCES public.users(id);


--
-- Name: audit_projects audit_projects_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_projects
    ADD CONSTRAINT audit_projects_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.annual_audit_plans(id);


--
-- Name: audit_team_members audit_team_members_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_team_members
    ADD CONSTRAINT audit_team_members_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.audit_projects(id) ON DELETE CASCADE;


--
-- Name: audit_team_members audit_team_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_team_members
    ADD CONSTRAINT audit_team_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: audit_universe audit_universe_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_universe
    ADD CONSTRAINT audit_universe_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id);


--
-- Name: audit_universe_risks audit_universe_risks_risk_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_universe_risks
    ADD CONSTRAINT audit_universe_risks_risk_id_fkey FOREIGN KEY (risk_id) REFERENCES public.risks(id) ON DELETE CASCADE;


--
-- Name: audit_universe_risks audit_universe_risks_universe_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_universe_risks
    ADD CONSTRAINT audit_universe_risks_universe_id_fkey FOREIGN KEY (universe_id) REFERENCES public.audit_universe(id) ON DELETE CASCADE;


--
-- Name: audit_working_papers audit_working_papers_finding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_working_papers
    ADD CONSTRAINT audit_working_papers_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.audit_findings(id);


--
-- Name: audit_working_papers audit_working_papers_program_step_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_working_papers
    ADD CONSTRAINT audit_working_papers_program_step_id_fkey FOREIGN KEY (program_step_id) REFERENCES public.audit_programs(id);


--
-- Name: audit_working_papers audit_working_papers_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_working_papers
    ADD CONSTRAINT audit_working_papers_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.audit_projects(id) ON DELETE CASCADE;


--
-- Name: audit_working_papers audit_working_papers_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_working_papers
    ADD CONSTRAINT audit_working_papers_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id);


--
-- Name: carbon_activity_entries carbon_activity_entries_carbon_site_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_activity_entries
    ADD CONSTRAINT carbon_activity_entries_carbon_site_fkey FOREIGN KEY (site_id) REFERENCES public.carbon_sites(id);


--
-- Name: carbon_activity_entries carbon_activity_entries_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_activity_entries
    ADD CONSTRAINT carbon_activity_entries_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: carbon_activity_entries carbon_activity_entries_factor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_activity_entries
    ADD CONSTRAINT carbon_activity_entries_factor_id_fkey FOREIGN KEY (factor_id) REFERENCES public.carbon_emission_factors(id);


--
-- Name: carbon_activity_entries carbon_activity_entries_reporting_period_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_activity_entries
    ADD CONSTRAINT carbon_activity_entries_reporting_period_id_fkey FOREIGN KEY (reporting_period_id) REFERENCES public.esg_reporting_periods(id);


--
-- Name: carbon_activity_entries carbon_activity_entries_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_activity_entries
    ADD CONSTRAINT carbon_activity_entries_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id);


--
-- Name: carbon_emission_factors carbon_emission_factors_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_emission_factors
    ADD CONSTRAINT carbon_emission_factors_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: carbon_offset_obligations carbon_offset_obligations_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_offset_obligations
    ADD CONSTRAINT carbon_offset_obligations_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: carbon_offset_obligations carbon_offset_obligations_reporting_period_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_offset_obligations
    ADD CONSTRAINT carbon_offset_obligations_reporting_period_id_fkey FOREIGN KEY (reporting_period_id) REFERENCES public.esg_reporting_periods(id);


--
-- Name: carbon_offset_purchases carbon_offset_purchases_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_offset_purchases
    ADD CONSTRAINT carbon_offset_purchases_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: carbon_offset_purchases carbon_offset_purchases_obligation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_offset_purchases
    ADD CONSTRAINT carbon_offset_purchases_obligation_id_fkey FOREIGN KEY (obligation_id) REFERENCES public.carbon_offset_obligations(id) ON DELETE CASCADE;


--
-- Name: carbon_scope_config carbon_scope_config_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_scope_config
    ADD CONSTRAINT carbon_scope_config_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: carbon_targets carbon_targets_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.carbon_targets
    ADD CONSTRAINT carbon_targets_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: case_reminders case_reminders_sent_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_reminders
    ADD CONSTRAINT case_reminders_sent_by_fkey FOREIGN KEY (sent_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: case_reminders case_reminders_sent_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_reminders
    ADD CONSTRAINT case_reminders_sent_to_fkey FOREIGN KEY (sent_to) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: cases cases_assigned_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES public.users(id);


--
-- Name: cases cases_case_type_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_case_type_fkey FOREIGN KEY (case_type) REFERENCES public.case_sla_config(case_type);


--
-- Name: cases cases_party_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_party_id_fkey FOREIGN KEY (party_id) REFERENCES public.parties(id);


--
-- Name: coi_disclosures coi_disclosures_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_disclosures
    ADD CONSTRAINT coi_disclosures_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: coi_disclosures coi_disclosures_employee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_disclosures
    ADD CONSTRAINT coi_disclosures_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: coi_disclosures coi_disclosures_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coi_disclosures
    ADD CONSTRAINT coi_disclosures_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: compliance_events compliance_events_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compliance_events
    ADD CONSTRAINT compliance_events_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: conduct_declarations conduct_declarations_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conduct_declarations
    ADD CONSTRAINT conduct_declarations_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: conduct_declarations conduct_declarations_employee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conduct_declarations
    ADD CONSTRAINT conduct_declarations_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: conduct_declarations conduct_declarations_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conduct_declarations
    ADD CONSTRAINT conduct_declarations_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: confirmed_matches confirmed_matches_closed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confirmed_matches
    ADD CONSTRAINT confirmed_matches_closed_by_fkey FOREIGN KEY (closed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: confirmed_matches confirmed_matches_confirmed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confirmed_matches
    ADD CONSTRAINT confirmed_matches_confirmed_by_fkey FOREIGN KEY (confirmed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: confirmed_matches confirmed_matches_str_filed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confirmed_matches
    ADD CONSTRAINT confirmed_matches_str_filed_by_fkey FOREIGN KEY (str_filed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: control_test_results control_test_results_audit_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.control_test_results
    ADD CONSTRAINT control_test_results_audit_project_id_fkey FOREIGN KEY (audit_project_id) REFERENCES public.audit_projects(id);


--
-- Name: control_test_results control_test_results_control_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.control_test_results
    ADD CONSTRAINT control_test_results_control_id_fkey FOREIGN KEY (control_id) REFERENCES public.controls(id) ON DELETE CASCADE;


--
-- Name: control_test_results control_test_results_tested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.control_test_results
    ADD CONSTRAINT control_test_results_tested_by_fkey FOREIGN KEY (tested_by) REFERENCES public.users(id);


--
-- Name: controls controls_control_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.controls
    ADD CONSTRAINT controls_control_owner_id_fkey FOREIGN KEY (control_owner_id) REFERENCES public.users(id);


--
-- Name: controls controls_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.controls
    ADD CONSTRAINT controls_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id);


--
-- Name: corp_profile corp_profile_regulator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corp_profile
    ADD CONSTRAINT corp_profile_regulator_id_fkey FOREIGN KEY (regulator_id) REFERENCES public.regulators(id);


--
-- Name: corp_profile corp_profile_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corp_profile
    ADD CONSTRAINT corp_profile_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: cy_assessments cy_assessments_accepted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_assessments
    ADD CONSTRAINT cy_assessments_accepted_by_fkey FOREIGN KEY (accepted_by) REFERENCES public.users(id);


--
-- Name: cy_assessments cy_assessments_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_assessments
    ADD CONSTRAINT cy_assessments_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: cy_bcp_sites cy_bcp_sites_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_bcp_sites
    ADD CONSTRAINT cy_bcp_sites_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: cy_domains cy_domains_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_domains
    ADD CONSTRAINT cy_domains_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: cy_dr_tests cy_dr_tests_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_dr_tests
    ADD CONSTRAINT cy_dr_tests_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: cy_dr_tests cy_dr_tests_finding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_dr_tests
    ADD CONSTRAINT cy_dr_tests_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.rc_findings(id) ON DELETE SET NULL;


--
-- Name: cy_dr_tests cy_dr_tests_site_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_dr_tests
    ADD CONSTRAINT cy_dr_tests_site_id_fkey FOREIGN KEY (site_id) REFERENCES public.cy_bcp_sites(id) ON DELETE SET NULL;


--
-- Name: cy_integrations cy_integrations_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_integrations
    ADD CONSTRAINT cy_integrations_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: cy_maturity_assessments cy_maturity_assessments_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_maturity_assessments
    ADD CONSTRAINT cy_maturity_assessments_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: cy_maturity_assessments cy_maturity_assessments_framework_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_maturity_assessments
    ADD CONSTRAINT cy_maturity_assessments_framework_id_fkey FOREIGN KEY (framework_id) REFERENCES public.rc_frameworks(id) ON DELETE CASCADE;


--
-- Name: cy_maturity_scores cy_maturity_scores_assessment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_maturity_scores
    ADD CONSTRAINT cy_maturity_scores_assessment_id_fkey FOREIGN KEY (assessment_id) REFERENCES public.cy_maturity_assessments(id) ON DELETE CASCADE;


--
-- Name: cy_maturity_scores cy_maturity_scores_requirement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_maturity_scores
    ADD CONSTRAINT cy_maturity_scores_requirement_id_fkey FOREIGN KEY (requirement_id) REFERENCES public.rc_requirements(id) ON DELETE CASCADE;


--
-- Name: cy_security_assets cy_security_assets_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cy_security_assets
    ADD CONSTRAINT cy_security_assets_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: declaration_campaign_targets declaration_campaign_targets_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.declaration_campaign_targets
    ADD CONSTRAINT declaration_campaign_targets_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.declaration_campaigns(id) ON DELETE CASCADE;


--
-- Name: declaration_campaign_targets declaration_campaign_targets_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.declaration_campaign_targets
    ADD CONSTRAINT declaration_campaign_targets_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: declaration_campaigns declaration_campaigns_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.declaration_campaigns
    ADD CONSTRAINT declaration_campaigns_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: declaration_campaigns declaration_campaigns_org_scope_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.declaration_campaigns
    ADD CONSTRAINT declaration_campaigns_org_scope_unit_id_fkey FOREIGN KEY (org_scope_unit_id) REFERENCES public.org_units(id) ON DELETE SET NULL;


--
-- Name: departments departments_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: document_approvals document_approvals_approver_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_approvals
    ADD CONSTRAINT document_approvals_approver_user_id_fkey FOREIGN KEY (approver_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: document_approvals document_approvals_decided_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_approvals
    ADD CONSTRAINT document_approvals_decided_by_fkey FOREIGN KEY (decided_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: document_approvals document_approvals_policy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_approvals
    ADD CONSTRAINT document_approvals_policy_id_fkey FOREIGN KEY (policy_id) REFERENCES public.policies(id) ON DELETE CASCADE;


--
-- Name: document_approvals document_approvals_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_approvals
    ADD CONSTRAINT document_approvals_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.approval_workflows(id) ON DELETE SET NULL;


--
-- Name: document_types document_types_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_types
    ADD CONSTRAINT document_types_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: ekyc_audit_log ekyc_audit_log_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_audit_log
    ADD CONSTRAINT ekyc_audit_log_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.ekyc_session(id) ON DELETE CASCADE;


--
-- Name: ekyc_audit_log ekyc_audit_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_audit_log
    ADD CONSTRAINT ekyc_audit_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: ekyc_document ekyc_document_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_document
    ADD CONSTRAINT ekyc_document_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.ekyc_session(id) ON DELETE CASCADE;


--
-- Name: ekyc_result ekyc_result_duplicate_of_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_result
    ADD CONSTRAINT ekyc_result_duplicate_of_session_id_fkey FOREIGN KEY (duplicate_of_session_id) REFERENCES public.ekyc_session(id);


--
-- Name: ekyc_result ekyc_result_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_result
    ADD CONSTRAINT ekyc_result_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.ekyc_session(id) ON DELETE CASCADE;


--
-- Name: ekyc_session ekyc_session_assigned_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_session
    ADD CONSTRAINT ekyc_session_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES public.users(id);


--
-- Name: ekyc_session ekyc_session_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_session
    ADD CONSTRAINT ekyc_session_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: ekyc_session ekyc_session_decision_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_session
    ADD CONSTRAINT ekyc_session_decision_by_fkey FOREIGN KEY (decision_by) REFERENCES public.users(id);


--
-- Name: ekyc_session ekyc_session_onboarded_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_session
    ADD CONSTRAINT ekyc_session_onboarded_customer_id_fkey FOREIGN KEY (onboarded_customer_id) REFERENCES public.customers(id);


--
-- Name: ekyc_session ekyc_session_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ekyc_session
    ADD CONSTRAINT ekyc_session_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id);


--
-- Name: email_templates email_templates_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_templates
    ADD CONSTRAINT email_templates_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: employee_screenings employee_screenings_screened_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_screenings
    ADD CONSTRAINT employee_screenings_screened_by_fkey FOREIGN KEY (screened_by) REFERENCES public.users(id);


--
-- Name: employee_screenings employee_screenings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_screenings
    ADD CONSTRAINT employee_screenings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: esg_disclosure_items esg_disclosure_items_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_disclosure_items
    ADD CONSTRAINT esg_disclosure_items_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.users(id);


--
-- Name: esg_disclosure_items esg_disclosure_items_reporting_period_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_disclosure_items
    ADD CONSTRAINT esg_disclosure_items_reporting_period_id_fkey FOREIGN KEY (reporting_period_id) REFERENCES public.esg_reporting_periods(id);


--
-- Name: esg_disclosure_items esg_disclosure_items_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_disclosure_items
    ADD CONSTRAINT esg_disclosure_items_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: esg_indicator_responses esg_indicator_responses_indicator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_indicator_responses
    ADD CONSTRAINT esg_indicator_responses_indicator_id_fkey FOREIGN KEY (indicator_id) REFERENCES public.esg_indicators(id);


--
-- Name: esg_indicator_responses esg_indicator_responses_reporting_period_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_indicator_responses
    ADD CONSTRAINT esg_indicator_responses_reporting_period_id_fkey FOREIGN KEY (reporting_period_id) REFERENCES public.esg_reporting_periods(id);


--
-- Name: esg_indicator_responses esg_indicator_responses_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_indicator_responses
    ADD CONSTRAINT esg_indicator_responses_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: esg_indicators esg_indicators_pillar_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_indicators
    ADD CONSTRAINT esg_indicators_pillar_id_fkey FOREIGN KEY (pillar_id) REFERENCES public.esg_pillars(id) ON DELETE CASCADE;


--
-- Name: esg_materiality_scores esg_materiality_scores_reporting_period_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_materiality_scores
    ADD CONSTRAINT esg_materiality_scores_reporting_period_id_fkey FOREIGN KEY (reporting_period_id) REFERENCES public.esg_reporting_periods(id);


--
-- Name: esg_materiality_scores esg_materiality_scores_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_materiality_scores
    ADD CONSTRAINT esg_materiality_scores_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.esg_materiality_topics(id);


--
-- Name: esg_materiality_scores esg_materiality_scores_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_materiality_scores
    ADD CONSTRAINT esg_materiality_scores_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: esg_pillars esg_pillars_framework_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_pillars
    ADD CONSTRAINT esg_pillars_framework_id_fkey FOREIGN KEY (framework_id) REFERENCES public.esg_frameworks(id) ON DELETE CASCADE;


--
-- Name: esg_reporting_periods esg_reporting_periods_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_reporting_periods
    ADD CONSTRAINT esg_reporting_periods_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: esg_sites esg_sites_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.esg_sites
    ADD CONSTRAINT esg_sites_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id);


--
-- Name: event_routing_rules event_routing_rules_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_routing_rules
    ADD CONSTRAINT event_routing_rules_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: fit_proper_assessments fit_proper_assessments_regulator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fit_proper_assessments
    ADD CONSTRAINT fit_proper_assessments_regulator_id_fkey FOREIGN KEY (regulator_id) REFERENCES public.regulators(id) ON DELETE SET NULL;


--
-- Name: ghe_records ghe_records_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ghe_records
    ADD CONSTRAINT ghe_records_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: ghe_records ghe_records_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ghe_records
    ADD CONSTRAINT ghe_records_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: ghe_records ghe_records_employee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ghe_records
    ADD CONSTRAINT ghe_records_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: governance_compliance_tracker governance_compliance_tracker_regulator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.governance_compliance_tracker
    ADD CONSTRAINT governance_compliance_tracker_regulator_id_fkey FOREIGN KEY (regulator_id) REFERENCES public.regulators(id) ON DELETE SET NULL;


--
-- Name: ia_area_controls ia_area_controls_control_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ia_area_controls
    ADD CONSTRAINT ia_area_controls_control_id_fkey FOREIGN KEY (control_id) REFERENCES public.rc_controls(id) ON DELETE CASCADE;


--
-- Name: ia_area_controls ia_area_controls_universe_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ia_area_controls
    ADD CONSTRAINT ia_area_controls_universe_id_fkey FOREIGN KEY (universe_id) REFERENCES public.audit_universe(id) ON DELETE CASCADE;


--
-- Name: kri_measurements kri_measurements_kri_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kri_measurements
    ADD CONSTRAINT kri_measurements_kri_id_fkey FOREIGN KEY (kri_id) REFERENCES public.kris(id) ON DELETE CASCADE;


--
-- Name: kri_measurements kri_measurements_recorded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kri_measurements
    ADD CONSTRAINT kri_measurements_recorded_by_fkey FOREIGN KEY (recorded_by) REFERENCES public.users(id);


--
-- Name: kris kris_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kris
    ADD CONSTRAINT kris_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.users(id);


--
-- Name: kris kris_risk_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kris
    ADD CONSTRAINT kris_risk_id_fkey FOREIGN KEY (risk_id) REFERENCES public.risks(id) ON DELETE CASCADE;


--
-- Name: kyc_beneficial_owners kyc_beneficial_owners_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_beneficial_owners
    ADD CONSTRAINT kyc_beneficial_owners_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: kyc_bo_declarations kyc_bo_declarations_recorded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_bo_declarations
    ADD CONSTRAINT kyc_bo_declarations_recorded_by_fkey FOREIGN KEY (recorded_by) REFERENCES public.users(id);


--
-- Name: kyc_onboarding kyc_onboarding_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_onboarding
    ADD CONSTRAINT kyc_onboarding_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id);


--
-- Name: kyc_onboarding kyc_onboarding_senior_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_onboarding
    ADD CONSTRAINT kyc_onboarding_senior_approved_by_fkey FOREIGN KEY (senior_approved_by) REFERENCES public.users(id);


--
-- Name: kyc_profile_values kyc_profile_values_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_profile_values
    ADD CONSTRAINT kyc_profile_values_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: kyc_risk_ratings kyc_risk_ratings_rated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_risk_ratings
    ADD CONSTRAINT kyc_risk_ratings_rated_by_fkey FOREIGN KEY (rated_by) REFERENCES public.users(id);


--
-- Name: ln_clients ln_clients_party_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_clients
    ADD CONSTRAINT ln_clients_party_id_fkey FOREIGN KEY (party_id) REFERENCES public.parties(id) ON DELETE SET NULL;


--
-- Name: ln_contracts ln_contracts_loan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_contracts
    ADD CONSTRAINT ln_contracts_loan_id_fkey FOREIGN KEY (loan_id) REFERENCES public.ln_loans(id) ON DELETE CASCADE;


--
-- Name: ln_credit_studies ln_credit_studies_loan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_credit_studies
    ADD CONSTRAINT ln_credit_studies_loan_id_fkey FOREIGN KEY (loan_id) REFERENCES public.ln_loans(id) ON DELETE CASCADE;


--
-- Name: ln_documents ln_documents_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_documents
    ADD CONSTRAINT ln_documents_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.ln_clients(id) ON DELETE CASCADE;


--
-- Name: ln_documents ln_documents_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_documents
    ADD CONSTRAINT ln_documents_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: ln_documents ln_documents_loan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_documents
    ADD CONSTRAINT ln_documents_loan_id_fkey FOREIGN KEY (loan_id) REFERENCES public.ln_loans(id) ON DELETE CASCADE;


--
-- Name: ln_early_repayments ln_early_repayments_executed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_early_repayments
    ADD CONSTRAINT ln_early_repayments_executed_by_fkey FOREIGN KEY (executed_by) REFERENCES public.users(id);


--
-- Name: ln_early_repayments ln_early_repayments_loan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_early_repayments
    ADD CONSTRAINT ln_early_repayments_loan_id_fkey FOREIGN KEY (loan_id) REFERENCES public.ln_loans(id) ON DELETE CASCADE;


--
-- Name: ln_exceptions ln_exceptions_decided_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_exceptions
    ADD CONSTRAINT ln_exceptions_decided_by_fkey FOREIGN KEY (decided_by) REFERENCES public.users(id);


--
-- Name: ln_exceptions ln_exceptions_loan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_exceptions
    ADD CONSTRAINT ln_exceptions_loan_id_fkey FOREIGN KEY (loan_id) REFERENCES public.ln_loans(id) ON DELETE CASCADE;


--
-- Name: ln_exceptions ln_exceptions_requested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_exceptions
    ADD CONSTRAINT ln_exceptions_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id);


--
-- Name: ln_import_batches ln_import_batches_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_import_batches
    ADD CONSTRAINT ln_import_batches_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: ln_instalments ln_instalments_loan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_instalments
    ADD CONSTRAINT ln_instalments_loan_id_fkey FOREIGN KEY (loan_id) REFERENCES public.ln_loans(id) ON DELETE CASCADE;


--
-- Name: ln_loans ln_loans_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_loans
    ADD CONSTRAINT ln_loans_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.ln_clients(id) ON DELETE CASCADE;


--
-- Name: ln_loans ln_loans_import_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_loans
    ADD CONSTRAINT ln_loans_import_batch_id_fkey FOREIGN KEY (import_batch_id) REFERENCES public.ln_import_batches(id) ON DELETE SET NULL;


--
-- Name: ln_qa_flags ln_qa_flags_loan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_qa_flags
    ADD CONSTRAINT ln_qa_flags_loan_id_fkey FOREIGN KEY (loan_id) REFERENCES public.ln_loans(id) ON DELETE CASCADE;


--
-- Name: ln_qa_flags ln_qa_flags_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_qa_flags
    ADD CONSTRAINT ln_qa_flags_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id);


--
-- Name: ln_reschedulings ln_reschedulings_loan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_reschedulings
    ADD CONSTRAINT ln_reschedulings_loan_id_fkey FOREIGN KEY (loan_id) REFERENCES public.ln_loans(id) ON DELETE CASCADE;


--
-- Name: ln_transfers ln_transfers_loan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_transfers
    ADD CONSTRAINT ln_transfers_loan_id_fkey FOREIGN KEY (loan_id) REFERENCES public.ln_loans(id) ON DELETE CASCADE;


--
-- Name: ln_visits ln_visits_loan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ln_visits
    ADD CONSTRAINT ln_visits_loan_id_fkey FOREIGN KEY (loan_id) REFERENCES public.ln_loans(id) ON DELETE CASCADE;


--
-- Name: mfa_audit mfa_audit_performed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mfa_audit
    ADD CONSTRAINT mfa_audit_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: mfa_audit mfa_audit_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mfa_audit
    ADD CONSTRAINT mfa_audit_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: ongoing_screening_config ongoing_screening_config_configured_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_config
    ADD CONSTRAINT ongoing_screening_config_configured_by_fkey FOREIGN KEY (configured_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: ongoing_screening_config ongoing_screening_config_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_config
    ADD CONSTRAINT ongoing_screening_config_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: ongoing_screening_findings ongoing_screening_findings_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_findings
    ADD CONSTRAINT ongoing_screening_findings_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: ongoing_screening_findings ongoing_screening_findings_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_findings
    ADD CONSTRAINT ongoing_screening_findings_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.ongoing_screening_runs(id) ON DELETE CASCADE;


--
-- Name: ongoing_screening_runs ongoing_screening_runs_triggered_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ongoing_screening_runs
    ADD CONSTRAINT ongoing_screening_runs_triggered_by_fkey FOREIGN KEY (triggered_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: org_units org_units_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_units
    ADD CONSTRAINT org_units_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: org_units org_units_head_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_units
    ADD CONSTRAINT org_units_head_user_id_fkey FOREIGN KEY (head_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: org_units org_units_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_units
    ADD CONSTRAINT org_units_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.org_units(id) ON DELETE RESTRICT;


--
-- Name: org_units org_units_unit_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_units
    ADD CONSTRAINT org_units_unit_type_id_fkey FOREIGN KEY (unit_type_id) REFERENCES public.org_unit_types(id);


--
-- Name: party_links party_links_party_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.party_links
    ADD CONSTRAINT party_links_party_id_fkey FOREIGN KEY (party_id) REFERENCES public.parties(id) ON DELETE CASCADE;


--
-- Name: pep_aliases pep_aliases_pep_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_aliases
    ADD CONSTRAINT pep_aliases_pep_id_fkey FOREIGN KEY (pep_id) REFERENCES public.pep_master(id) ON DELETE CASCADE;


--
-- Name: pep_corporate_links pep_corporate_links_pep_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_corporate_links
    ADD CONSTRAINT pep_corporate_links_pep_id_fkey FOREIGN KEY (pep_id) REFERENCES public.pep_master(id) ON DELETE CASCADE;


--
-- Name: pep_duplicate_candidates pep_duplicate_candidates_merged_into_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_duplicate_candidates
    ADD CONSTRAINT pep_duplicate_candidates_merged_into_fkey FOREIGN KEY (merged_into) REFERENCES public.pep_master(id);


--
-- Name: pep_duplicate_candidates pep_duplicate_candidates_pep_id_1_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_duplicate_candidates
    ADD CONSTRAINT pep_duplicate_candidates_pep_id_1_fkey FOREIGN KEY (pep_id_1) REFERENCES public.pep_master(id) ON DELETE CASCADE;


--
-- Name: pep_duplicate_candidates pep_duplicate_candidates_pep_id_2_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_duplicate_candidates
    ADD CONSTRAINT pep_duplicate_candidates_pep_id_2_fkey FOREIGN KEY (pep_id_2) REFERENCES public.pep_master(id) ON DELETE CASCADE;


--
-- Name: pep_positions pep_positions_pep_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_positions
    ADD CONSTRAINT pep_positions_pep_id_fkey FOREIGN KEY (pep_id) REFERENCES public.pep_master(id) ON DELETE CASCADE;


--
-- Name: pep_sources pep_sources_pep_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pep_sources
    ADD CONSTRAINT pep_sources_pep_id_fkey FOREIGN KEY (pep_id) REFERENCES public.pep_master(id) ON DELETE CASCADE;


--
-- Name: phishing_campaigns phishing_campaigns_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phishing_campaigns
    ADD CONSTRAINT phishing_campaigns_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: phishing_events phishing_events_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phishing_events
    ADD CONSTRAINT phishing_events_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.phishing_campaigns(id) ON DELETE CASCADE;


--
-- Name: phishing_events phishing_events_recipient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phishing_events
    ADD CONSTRAINT phishing_events_recipient_id_fkey FOREIGN KEY (recipient_id) REFERENCES public.phishing_recipients(id) ON DELETE CASCADE;


--
-- Name: phishing_recipients phishing_recipients_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phishing_recipients
    ADD CONSTRAINT phishing_recipients_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.phishing_campaigns(id) ON DELETE CASCADE;


--
-- Name: policies policies_document_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policies
    ADD CONSTRAINT policies_document_type_id_fkey FOREIGN KEY (document_type_id) REFERENCES public.document_types(id);


--
-- Name: policies policies_org_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policies
    ADD CONSTRAINT policies_org_unit_id_fkey FOREIGN KEY (org_unit_id) REFERENCES public.org_units(id) ON DELETE SET NULL;


--
-- Name: policy_applicability policy_applicability_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_applicability
    ADD CONSTRAINT policy_applicability_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: policy_applicability policy_applicability_match_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_applicability
    ADD CONSTRAINT policy_applicability_match_type_id_fkey FOREIGN KEY (match_type_id) REFERENCES public.org_unit_types(id) ON DELETE CASCADE;


--
-- Name: policy_applicability policy_applicability_org_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_applicability
    ADD CONSTRAINT policy_applicability_org_unit_id_fkey FOREIGN KEY (org_unit_id) REFERENCES public.org_units(id) ON DELETE CASCADE;


--
-- Name: policy_applicability policy_applicability_policy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_applicability
    ADD CONSTRAINT policy_applicability_policy_id_fkey FOREIGN KEY (policy_id) REFERENCES public.policies(id) ON DELETE CASCADE;


--
-- Name: policy_applicability policy_applicability_root_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_applicability
    ADD CONSTRAINT policy_applicability_root_unit_id_fkey FOREIGN KEY (root_unit_id) REFERENCES public.org_units(id) ON DELETE CASCADE;


--
-- Name: policy_board_approvals policy_board_approvals_recorded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policy_board_approvals
    ADD CONSTRAINT policy_board_approvals_recorded_by_fkey FOREIGN KEY (recorded_by) REFERENCES public.users(id);


--
-- Name: pr_branch_staffing pr_branch_staffing_branch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_branch_staffing
    ADD CONSTRAINT pr_branch_staffing_branch_id_fkey FOREIGN KEY (branch_id) REFERENCES public.pr_branches(id) ON DELETE CASCADE;


--
-- Name: pr_branch_staffing pr_branch_staffing_role_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_branch_staffing
    ADD CONSTRAINT pr_branch_staffing_role_code_fkey FOREIGN KEY (role_code) REFERENCES public.pr_branch_roles(code) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: pr_branches pr_branches_manager_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_branches
    ADD CONSTRAINT pr_branches_manager_user_id_fkey FOREIGN KEY (manager_user_id) REFERENCES public.users(id);


--
-- Name: pr_branches pr_branches_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_branches
    ADD CONSTRAINT pr_branches_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: pr_capital_events pr_capital_events_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_capital_events
    ADD CONSTRAINT pr_capital_events_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: pr_deadline_extensions pr_deadline_extensions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_deadline_extensions
    ADD CONSTRAINT pr_deadline_extensions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: pr_deadline_extensions pr_deadline_extensions_deadline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_deadline_extensions
    ADD CONSTRAINT pr_deadline_extensions_deadline_id_fkey FOREIGN KEY (deadline_id) REFERENCES public.pr_deadlines(id) ON DELETE CASCADE;


--
-- Name: pr_deadlines pr_deadlines_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_deadlines
    ADD CONSTRAINT pr_deadlines_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: pr_deadlines pr_deadlines_finding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_deadlines
    ADD CONSTRAINT pr_deadlines_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.rc_findings(id) ON DELETE SET NULL;


--
-- Name: pr_deadlines pr_deadlines_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_deadlines
    ADD CONSTRAINT pr_deadlines_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: pr_deadlines pr_deadlines_regulator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_deadlines
    ADD CONSTRAINT pr_deadlines_regulator_id_fkey FOREIGN KEY (regulator_id) REFERENCES public.regulators(id);


--
-- Name: pr_documents pr_documents_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_documents
    ADD CONSTRAINT pr_documents_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: pr_facilities pr_facilities_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_facilities
    ADD CONSTRAINT pr_facilities_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: pr_financial_periods pr_financial_periods_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_financial_periods
    ADD CONSTRAINT pr_financial_periods_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id);


--
-- Name: pr_financial_periods pr_financial_periods_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_financial_periods
    ADD CONSTRAINT pr_financial_periods_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: pr_key_functions pr_key_functions_function_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_key_functions
    ADD CONSTRAINT pr_key_functions_function_code_fkey FOREIGN KEY (function_code) REFERENCES public.pr_key_function_types(code) ON UPDATE CASCADE;


--
-- Name: pr_key_functions pr_key_functions_holder_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_key_functions
    ADD CONSTRAINT pr_key_functions_holder_user_id_fkey FOREIGN KEY (holder_user_id) REFERENCES public.users(id);


--
-- Name: pr_key_functions pr_key_functions_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_key_functions
    ADD CONSTRAINT pr_key_functions_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: pr_related_parties pr_related_parties_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_related_parties
    ADD CONSTRAINT pr_related_parties_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: pr_rp_items pr_rp_items_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_rp_items
    ADD CONSTRAINT pr_rp_items_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: pr_rp_items pr_rp_items_related_party_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_rp_items
    ADD CONSTRAINT pr_rp_items_related_party_id_fkey FOREIGN KEY (related_party_id) REFERENCES public.pr_related_parties(id) ON DELETE CASCADE;


--
-- Name: pr_studies pr_studies_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pr_studies
    ADD CONSTRAINT pr_studies_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: rc_alerts rc_alerts_acknowledged_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_alerts
    ADD CONSTRAINT rc_alerts_acknowledged_by_fkey FOREIGN KEY (acknowledged_by) REFERENCES public.users(id);


--
-- Name: rc_alerts rc_alerts_control_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_alerts
    ADD CONSTRAINT rc_alerts_control_id_fkey FOREIGN KEY (control_id) REFERENCES public.rc_controls(id) ON DELETE CASCADE;


--
-- Name: rc_alerts rc_alerts_evidence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_alerts
    ADD CONSTRAINT rc_alerts_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES public.rc_evidence(id) ON DELETE CASCADE;


--
-- Name: rc_alerts rc_alerts_finding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_alerts
    ADD CONSTRAINT rc_alerts_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.rc_findings(id) ON DELETE CASCADE;


--
-- Name: rc_alerts rc_alerts_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_alerts
    ADD CONSTRAINT rc_alerts_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: rc_alerts rc_alerts_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_alerts
    ADD CONSTRAINT rc_alerts_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.rc_control_runs(id) ON DELETE SET NULL;


--
-- Name: rc_control_requirements rc_control_requirements_control_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_control_requirements
    ADD CONSTRAINT rc_control_requirements_control_id_fkey FOREIGN KEY (control_id) REFERENCES public.rc_controls(id) ON DELETE CASCADE;


--
-- Name: rc_control_requirements rc_control_requirements_requirement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_control_requirements
    ADD CONSTRAINT rc_control_requirements_requirement_id_fkey FOREIGN KEY (requirement_id) REFERENCES public.rc_requirements(id) ON DELETE CASCADE;


--
-- Name: rc_control_runs rc_control_runs_control_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_control_runs
    ADD CONSTRAINT rc_control_runs_control_id_fkey FOREIGN KEY (control_id) REFERENCES public.rc_controls(id) ON DELETE CASCADE;


--
-- Name: rc_control_runs rc_control_runs_run_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_control_runs
    ADD CONSTRAINT rc_control_runs_run_by_fkey FOREIGN KEY (run_by) REFERENCES public.users(id);


--
-- Name: rc_controls rc_controls_erm_control_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_controls
    ADD CONSTRAINT rc_controls_erm_control_id_fkey FOREIGN KEY (erm_control_id) REFERENCES public.controls(id) ON DELETE SET NULL;


--
-- Name: rc_controls rc_controls_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_controls
    ADD CONSTRAINT rc_controls_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: rc_corrective_actions rc_corrective_actions_completed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_corrective_actions
    ADD CONSTRAINT rc_corrective_actions_completed_by_fkey FOREIGN KEY (completed_by) REFERENCES public.users(id);


--
-- Name: rc_corrective_actions rc_corrective_actions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_corrective_actions
    ADD CONSTRAINT rc_corrective_actions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: rc_corrective_actions rc_corrective_actions_finding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_corrective_actions
    ADD CONSTRAINT rc_corrective_actions_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.rc_findings(id) ON DELETE CASCADE;


--
-- Name: rc_corrective_actions rc_corrective_actions_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_corrective_actions
    ADD CONSTRAINT rc_corrective_actions_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: rc_evidence rc_evidence_control_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_evidence
    ADD CONSTRAINT rc_evidence_control_id_fkey FOREIGN KEY (control_id) REFERENCES public.rc_controls(id) ON DELETE CASCADE;


--
-- Name: rc_evidence rc_evidence_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_evidence
    ADD CONSTRAINT rc_evidence_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id);


--
-- Name: rc_evidence rc_evidence_submitted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_evidence
    ADD CONSTRAINT rc_evidence_submitted_by_fkey FOREIGN KEY (submitted_by) REFERENCES public.users(id);


--
-- Name: rc_finding_controls rc_finding_controls_control_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_finding_controls
    ADD CONSTRAINT rc_finding_controls_control_id_fkey FOREIGN KEY (control_id) REFERENCES public.rc_controls(id) ON DELETE CASCADE;


--
-- Name: rc_finding_controls rc_finding_controls_finding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_finding_controls
    ADD CONSTRAINT rc_finding_controls_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.rc_findings(id) ON DELETE CASCADE;


--
-- Name: rc_finding_events rc_finding_events_finding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_finding_events
    ADD CONSTRAINT rc_finding_events_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.rc_findings(id) ON DELETE CASCADE;


--
-- Name: rc_finding_events rc_finding_events_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_finding_events
    ADD CONSTRAINT rc_finding_events_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.rc_control_runs(id) ON DELETE SET NULL;


--
-- Name: rc_finding_events rc_finding_events_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_finding_events
    ADD CONSTRAINT rc_finding_events_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: rc_findings rc_findings_closed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_findings
    ADD CONSTRAINT rc_findings_closed_by_fkey FOREIGN KEY (closed_by) REFERENCES public.users(id);


--
-- Name: rc_findings rc_findings_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_findings
    ADD CONSTRAINT rc_findings_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: rc_findings rc_findings_framework_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_findings
    ADD CONSTRAINT rc_findings_framework_id_fkey FOREIGN KEY (framework_id) REFERENCES public.rc_frameworks(id) ON DELETE SET NULL;


--
-- Name: rc_findings rc_findings_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_findings
    ADD CONSTRAINT rc_findings_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- Name: rc_findings rc_findings_regulator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_findings
    ADD CONSTRAINT rc_findings_regulator_id_fkey FOREIGN KEY (regulator_id) REFERENCES public.regulators(id) ON DELETE SET NULL;


--
-- Name: rc_findings rc_findings_verified_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_findings
    ADD CONSTRAINT rc_findings_verified_by_fkey FOREIGN KEY (verified_by) REFERENCES public.users(id);


--
-- Name: rc_frameworks rc_frameworks_regulator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_frameworks
    ADD CONSTRAINT rc_frameworks_regulator_id_fkey FOREIGN KEY (regulator_id) REFERENCES public.regulators(id) ON DELETE SET NULL;


--
-- Name: rc_licence_types rc_licence_types_regulator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_licence_types
    ADD CONSTRAINT rc_licence_types_regulator_id_fkey FOREIGN KEY (regulator_id) REFERENCES public.regulators(id) ON DELETE SET NULL;


--
-- Name: rc_packs rc_packs_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_packs
    ADD CONSTRAINT rc_packs_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: rc_parameter_changes rc_parameter_changes_applied_parameter_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameter_changes
    ADD CONSTRAINT rc_parameter_changes_applied_parameter_id_fkey FOREIGN KEY (applied_parameter_id) REFERENCES public.rc_parameters(id) ON DELETE SET NULL;


--
-- Name: rc_parameter_changes rc_parameter_changes_decided_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameter_changes
    ADD CONSTRAINT rc_parameter_changes_decided_by_fkey FOREIGN KEY (decided_by) REFERENCES public.users(id);


--
-- Name: rc_parameter_changes rc_parameter_changes_parameter_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameter_changes
    ADD CONSTRAINT rc_parameter_changes_parameter_id_fkey FOREIGN KEY (parameter_id) REFERENCES public.rc_parameters(id) ON DELETE SET NULL;


--
-- Name: rc_parameter_changes rc_parameter_changes_requested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameter_changes
    ADD CONSTRAINT rc_parameter_changes_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id);


--
-- Name: rc_parameters rc_parameters_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameters
    ADD CONSTRAINT rc_parameters_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id);


--
-- Name: rc_parameters rc_parameters_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameters
    ADD CONSTRAINT rc_parameters_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: rc_parameters rc_parameters_framework_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_parameters
    ADD CONSTRAINT rc_parameters_framework_id_fkey FOREIGN KEY (framework_id) REFERENCES public.rc_frameworks(id) ON DELETE SET NULL;


--
-- Name: rc_readiness_snapshots rc_readiness_snapshots_framework_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_readiness_snapshots
    ADD CONSTRAINT rc_readiness_snapshots_framework_id_fkey FOREIGN KEY (framework_id) REFERENCES public.rc_frameworks(id) ON DELETE CASCADE;


--
-- Name: rc_requirements rc_requirements_framework_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rc_requirements
    ADD CONSTRAINT rc_requirements_framework_id_fkey FOREIGN KEY (framework_id) REFERENCES public.rc_frameworks(id) ON DELETE CASCADE;


--
-- Name: reminder_log reminder_log_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reminder_log
    ADD CONSTRAINT reminder_log_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.declaration_campaigns(id) ON DELETE CASCADE;


--
-- Name: reminder_log reminder_log_sent_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reminder_log
    ADD CONSTRAINT reminder_log_sent_by_fkey FOREIGN KEY (sent_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: risk_appetite_statements risk_appetite_statements_approved_by_meeting_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_appetite_statements
    ADD CONSTRAINT risk_appetite_statements_approved_by_meeting_id_fkey FOREIGN KEY (approved_by_meeting_id) REFERENCES public.board_meetings(id);


--
-- Name: risk_appetite_statements risk_appetite_statements_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_appetite_statements
    ADD CONSTRAINT risk_appetite_statements_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.risk_categories(id);


--
-- Name: risk_appetite_statements risk_appetite_statements_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_appetite_statements
    ADD CONSTRAINT risk_appetite_statements_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: risk_categories risk_categories_parent_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_categories
    ADD CONSTRAINT risk_categories_parent_category_id_fkey FOREIGN KEY (parent_category_id) REFERENCES public.risk_categories(id);


--
-- Name: risk_controls risk_controls_control_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_controls
    ADD CONSTRAINT risk_controls_control_id_fkey FOREIGN KEY (control_id) REFERENCES public.controls(id) ON DELETE CASCADE;


--
-- Name: risk_controls risk_controls_risk_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_controls
    ADD CONSTRAINT risk_controls_risk_id_fkey FOREIGN KEY (risk_id) REFERENCES public.risks(id) ON DELETE CASCADE;


--
-- Name: risk_score_history risk_score_history_changed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_score_history
    ADD CONSTRAINT risk_score_history_changed_by_fkey FOREIGN KEY (changed_by) REFERENCES public.users(id);


--
-- Name: risk_score_history risk_score_history_risk_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_score_history
    ADD CONSTRAINT risk_score_history_risk_id_fkey FOREIGN KEY (risk_id) REFERENCES public.risks(id) ON DELETE CASCADE;


--
-- Name: risk_source_links risk_source_links_linked_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_source_links
    ADD CONSTRAINT risk_source_links_linked_by_fkey FOREIGN KEY (linked_by) REFERENCES public.users(id);


--
-- Name: risk_source_links risk_source_links_risk_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_source_links
    ADD CONSTRAINT risk_source_links_risk_id_fkey FOREIGN KEY (risk_id) REFERENCES public.risks(id) ON DELETE CASCADE;


--
-- Name: risk_treatments risk_treatments_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_treatments
    ADD CONSTRAINT risk_treatments_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: risk_treatments risk_treatments_risk_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_treatments
    ADD CONSTRAINT risk_treatments_risk_id_fkey FOREIGN KEY (risk_id) REFERENCES public.risks(id) ON DELETE CASCADE;


--
-- Name: risk_treatments risk_treatments_treatment_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_treatments
    ADD CONSTRAINT risk_treatments_treatment_owner_id_fkey FOREIGN KEY (treatment_owner_id) REFERENCES public.users(id);


--
-- Name: risk_treatments risk_treatments_verified_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_treatments
    ADD CONSTRAINT risk_treatments_verified_by_fkey FOREIGN KEY (verified_by) REFERENCES public.users(id);


--
-- Name: risks risks_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risks
    ADD CONSTRAINT risks_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.risk_categories(id);


--
-- Name: risks risks_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risks
    ADD CONSTRAINT risks_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: risks risks_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risks
    ADD CONSTRAINT risks_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id);


--
-- Name: risks risks_parent_risk_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risks
    ADD CONSTRAINT risks_parent_risk_id_fkey FOREIGN KEY (parent_risk_id) REFERENCES public.risks(id);


--
-- Name: risks risks_risk_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risks
    ADD CONSTRAINT risks_risk_owner_id_fkey FOREIGN KEY (risk_owner_id) REFERENCES public.users(id);


--
-- Name: screening_delta_hits screening_delta_hits_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_delta_hits
    ADD CONSTRAINT screening_delta_hits_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.screening_delta_runs(id) ON DELETE CASCADE;


--
-- Name: screening_qa_cases screening_qa_cases_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_qa_cases
    ADD CONSTRAINT screening_qa_cases_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: screening_qa_runs screening_qa_runs_run_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_qa_runs
    ADD CONSTRAINT screening_qa_runs_run_by_fkey FOREIGN KEY (run_by) REFERENCES public.users(id);


--
-- Name: screening_risk_criteria screening_risk_criteria_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_risk_criteria
    ADD CONSTRAINT screening_risk_criteria_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: screening_risk_criteria screening_risk_criteria_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_risk_criteria
    ADD CONSTRAINT screening_risk_criteria_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: screening_whitelist_audit screening_whitelist_audit_performed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_whitelist_audit
    ADD CONSTRAINT screening_whitelist_audit_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: screening_whitelist_matches screening_whitelist_matches_whitelist_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_whitelist_matches
    ADD CONSTRAINT screening_whitelist_matches_whitelist_id_fkey FOREIGN KEY (whitelist_id) REFERENCES public.screening_whitelist(id) ON DELETE CASCADE;


--
-- Name: screening_whitelist screening_whitelist_risk_band_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_whitelist
    ADD CONSTRAINT screening_whitelist_risk_band_by_fkey FOREIGN KEY (risk_band_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: screening_workflow screening_workflow_assigned_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_workflow
    ADD CONSTRAINT screening_workflow_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: screening_workflow screening_workflow_completed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_workflow
    ADD CONSTRAINT screening_workflow_completed_by_fkey FOREIGN KEY (completed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: screening_workflow screening_workflow_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_workflow
    ADD CONSTRAINT screening_workflow_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: screening_workflow screening_workflow_escalated_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_workflow
    ADD CONSTRAINT screening_workflow_escalated_to_fkey FOREIGN KEY (escalated_to) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: screening_workflow screening_workflow_screening_result_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_workflow
    ADD CONSTRAINT screening_workflow_screening_result_id_fkey FOREIGN KEY (screening_result_id) REFERENCES public.screening_results(id) ON DELETE CASCADE;


--
-- Name: tm_rules tm_rules_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tm_rules
    ADD CONSTRAINT tm_rules_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: tm_rules tm_rules_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tm_rules
    ADD CONSTRAINT tm_rules_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: tm_rules tm_rules_previous_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tm_rules
    ADD CONSTRAINT tm_rules_previous_id_fkey FOREIGN KEY (previous_id) REFERENCES public.tm_rules(id) ON DELETE SET NULL;


--
-- Name: tm_rules tm_rules_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tm_rules
    ADD CONSTRAINT tm_rules_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: user_module_permissions user_module_permissions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_module_permissions
    ADD CONSTRAINT user_module_permissions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_org_scope_rules user_org_scope_rules_granted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_org_scope_rules
    ADD CONSTRAINT user_org_scope_rules_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: user_org_scope_rules user_org_scope_rules_match_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_org_scope_rules
    ADD CONSTRAINT user_org_scope_rules_match_type_id_fkey FOREIGN KEY (match_type_id) REFERENCES public.org_unit_types(id) ON DELETE CASCADE;


--
-- Name: user_org_scope_rules user_org_scope_rules_org_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_org_scope_rules
    ADD CONSTRAINT user_org_scope_rules_org_unit_id_fkey FOREIGN KEY (org_unit_id) REFERENCES public.org_units(id) ON DELETE CASCADE;


--
-- Name: user_org_scope_rules user_org_scope_rules_root_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_org_scope_rules
    ADD CONSTRAINT user_org_scope_rules_root_unit_id_fkey FOREIGN KEY (root_unit_id) REFERENCES public.org_units(id) ON DELETE CASCADE;


--
-- Name: user_org_scope_rules user_org_scope_rules_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_org_scope_rules
    ADD CONSTRAINT user_org_scope_rules_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: users users_authority_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_authority_unit_id_fkey FOREIGN KEY (authority_unit_id) REFERENCES public.org_units(id) ON DELETE SET NULL;


--
-- Name: users users_mfa_last_reset_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_mfa_last_reset_by_fkey FOREIGN KEY (mfa_last_reset_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: users users_org_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_org_unit_id_fkey FOREIGN KEY (org_unit_id) REFERENCES public.org_units(id) ON DELETE SET NULL;


--
-- Name: whistleblowing_assignments whistleblowing_assignments_from_org_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_assignments
    ADD CONSTRAINT whistleblowing_assignments_from_org_unit_id_fkey FOREIGN KEY (from_org_unit_id) REFERENCES public.org_units(id) ON DELETE SET NULL;


--
-- Name: whistleblowing_assignments whistleblowing_assignments_to_org_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.whistleblowing_assignments
    ADD CONSTRAINT whistleblowing_assignments_to_org_unit_id_fkey FOREIGN KEY (to_org_unit_id) REFERENCES public.org_units(id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--

\unrestrict l01wf1xteiRe6o2Chx0dhIKETw5FwhgmCwLfUUXLi4UuKya9juVRl9C9ampLjca

