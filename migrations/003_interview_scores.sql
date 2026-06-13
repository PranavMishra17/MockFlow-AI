-- Wing D Phase 0 — per-session structured scores, queryable for longitudinal
-- trends and cross-track comparison (docs/EPIC_wingD_feedback_moat.md §4).
-- One row per interview; the full finalized scores object lives in `scores`
-- (JSONB), with overall_score denormalized for cheap trend queries.

CREATE TABLE IF NOT EXISTS interview_scores (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    interview_id  UUID NOT NULL UNIQUE REFERENCES interviews(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    track         TEXT NOT NULL DEFAULT 'intro',
    overall_score NUMERIC,
    scores        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interview_scores_user       ON interview_scores(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_interview_scores_user_track ON interview_scores(user_id, track);
