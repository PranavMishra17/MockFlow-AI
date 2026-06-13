-- MockFlow-AI migration 002 — owner-funded free interview tier.
-- Run once against Neon (psql "$DATABASE_URL" -f migrations/002_free_tier_and_stats.sql).
-- Idempotent: safe to re-run.

-- Per-user free interview allowance (bounded by the UNIQUE email on users).
ALTER TABLE users ADD COLUMN IF NOT EXISTS free_calls_used    INT NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS free_calls_granted INT NOT NULL DEFAULT 2;

-- Global monthly counter for the kill-switch ceiling (one row per 'YYYY-MM').
CREATE TABLE IF NOT EXISTS free_tier_usage (
    month      CHAR(7) PRIMARY KEY,   -- 'YYYY-MM' (UTC)
    calls      INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
