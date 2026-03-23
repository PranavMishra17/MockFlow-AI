-- Patch 1 Migration: Add multi-track interview support
-- Run this on your Supabase project SQL editor.
-- All statements use IF NOT EXISTS / default guards for idempotency.

-- Add track type column to interviews table
-- Stores which interview track was used: 'intro', 'behavioral', 'technical_voice', 'coding'
ALTER TABLE interviews ADD COLUMN IF NOT EXISTS track VARCHAR DEFAULT 'intro';

-- Add track-specific configuration snapshot
-- Stores: framework (behavioral), topics (technical_voice), depth, custom_questions, generated_questions
ALTER TABLE interviews ADD COLUMN IF NOT EXISTS track_config JSONB DEFAULT '{}';

-- Index for filtering interviews by track type
CREATE INDEX IF NOT EXISTS idx_interviews_track ON interviews(track);

-- Index for filtering interviews by user and track
CREATE INDEX IF NOT EXISTS idx_interviews_user_track ON interviews(user_id, track);
