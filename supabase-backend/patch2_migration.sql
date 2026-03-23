-- Patch 2 Migration: Add coding submissions table for Technical Coding Track
-- Run this on your Supabase project SQL editor.
-- All statements use IF NOT EXISTS guards for idempotency.

-- Coding submissions: stores each code submission per interview problem
-- Supports up to 3 attempts per problem with full evaluation results
CREATE TABLE IF NOT EXISTS coding_submissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    interview_id UUID NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    problem_title TEXT NOT NULL,
    problem_description TEXT,
    language VARCHAR NOT NULL,
    code_submitted TEXT NOT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    -- Stores structured evaluation JSON:
    -- {correctness, approach_quality, edge_cases_handled, edge_cases_missed,
    --  time_complexity, space_complexity, code_quality_notes, suggestions, brief_verbal_feedback}
    evaluation_result JSONB,
    time_spent_seconds INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for fetching all submissions for a given interview
CREATE INDEX IF NOT EXISTS idx_coding_submissions_interview
ON coding_submissions(interview_id);

-- Index for fetching all submissions by a user
CREATE INDEX IF NOT EXISTS idx_coding_submissions_user
ON coding_submissions(user_id);

-- Row Level Security: users can only view their own submissions
ALTER TABLE coding_submissions ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'coding_submissions' AND policyname = 'Users can view own submissions'
  ) THEN
    CREATE POLICY "Users can view own submissions"
    ON coding_submissions FOR SELECT
    USING (auth.uid() = user_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'coding_submissions' AND policyname = 'Service can insert submissions'
  ) THEN
    CREATE POLICY "Service can insert submissions"
    ON coding_submissions FOR INSERT
    WITH CHECK (auth.uid() = user_id);
  END IF;
END $$;
