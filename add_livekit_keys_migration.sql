-- Migration: Add LiveKit credentials to user_api_keys table
-- This adds three new encrypted fields for LiveKit URL, API Key, and API Secret

-- Add LiveKit URL encrypted column
ALTER TABLE user_api_keys
ADD COLUMN IF NOT EXISTS livekit_url_encrypted TEXT;

-- Add LiveKit API Key encrypted column
ALTER TABLE user_api_keys
ADD COLUMN IF NOT EXISTS livekit_key_encrypted TEXT;

-- Add LiveKit API Secret encrypted column
ALTER TABLE user_api_keys
ADD COLUMN IF NOT EXISTS livekit_secret_encrypted TEXT;

-- Add comment to table
COMMENT ON TABLE user_api_keys IS 'Stores encrypted API keys for users (BYOK model): LiveKit, OpenAI, and Deepgram';

-- Add comments to columns
COMMENT ON COLUMN user_api_keys.livekit_url_encrypted IS 'Encrypted LiveKit WebSocket URL (wss://...)';
COMMENT ON COLUMN user_api_keys.livekit_key_encrypted IS 'Encrypted LiveKit API Key';
COMMENT ON COLUMN user_api_keys.livekit_secret_encrypted IS 'Encrypted LiveKit API Secret';
COMMENT ON COLUMN user_api_keys.openai_key_encrypted IS 'Encrypted OpenAI API Key';
COMMENT ON COLUMN user_api_keys.deepgram_key_encrypted IS 'Encrypted Deepgram API Key';
