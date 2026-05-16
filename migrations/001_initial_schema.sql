-- MockFlow-AI Xata schema bootstrap (Phase 6 in MIGRATION.md)
-- Run once in Xata's SQL console (Project -> SQL editor).
-- Replaces Supabase's `auth.users`-backed schema with an app-managed `users` table,
-- drops Supabase RLS (we enforce user_id scoping in application code).

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- App-managed users (Authlib + Flask-Login, replaces Supabase auth.users)
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email       TEXT UNIQUE NOT NULL,
    name        TEXT,
    google_id   TEXT UNIQUE,
    picture_url TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email     ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);

-- Encrypted BYOK keys (one row per user). Column names match supabase_client.py.
CREATE TABLE IF NOT EXISTS user_api_keys (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                  UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    livekit_url_encrypted    TEXT,
    livekit_key_encrypted    TEXT,
    livekit_secret_encrypted TEXT,
    openai_key_encrypted     TEXT,
    deepgram_key_encrypted   TEXT,
    encryption_salt          TEXT DEFAULT 'salt_v1',
    created_at               TIMESTAMPTZ DEFAULT NOW(),
    updated_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user ON user_api_keys(user_id);

-- Interview sessions (one row per completed interview)
CREATE TABLE IF NOT EXISTS interviews (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    candidate_name   TEXT NOT NULL,
    interview_date   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    room_name        TEXT,
    job_role         TEXT,
    experience_level TEXT,
    conversation     JSONB DEFAULT '{}'::jsonb,
    total_messages   JSONB DEFAULT '{}'::jsonb,
    metadata         JSONB DEFAULT '{}'::jsonb,
    skipped_stages   TEXT[] DEFAULT '{}',
    final_stage      TEXT,
    ended_by         TEXT,
    has_resume       BOOLEAN DEFAULT FALSE,
    has_jd           BOOLEAN DEFAULT FALSE,
    track            VARCHAR DEFAULT 'intro',
    track_config     JSONB DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interviews_user_date  ON interviews(user_id, interview_date DESC);
CREATE INDEX IF NOT EXISTS idx_interviews_room       ON interviews(room_name);
CREATE INDEX IF NOT EXISTS idx_interviews_track      ON interviews(track);
CREATE INDEX IF NOT EXISTS idx_interviews_user_track ON interviews(user_id, track);

-- Generated feedback (one row per interview, upsert on interview_id)
CREATE TABLE IF NOT EXISTS feedback (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    interview_id  UUID NOT NULL UNIQUE REFERENCES interviews(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feedback_data JSONB NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_interview ON feedback(interview_id);

-- Coding-track submissions (up to 3 attempts per problem per interview)
CREATE TABLE IF NOT EXISTS coding_submissions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    interview_id        UUID NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem_title       TEXT NOT NULL,
    problem_description TEXT,
    language            VARCHAR NOT NULL,
    code_submitted      TEXT NOT NULL,
    attempt_number      INTEGER NOT NULL DEFAULT 1,
    evaluation_result   JSONB,
    time_spent_seconds  INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coding_submissions_interview ON coding_submissions(interview_id);
CREATE INDEX IF NOT EXISTS idx_coding_submissions_user      ON coding_submissions(user_id);
