# Supabase Backend Schema Documentation

## Table Structure & Relations

### 1. `public.users`
**Purpose:** Core user profiles synced with Supabase Auth

**Structure:**
- `id` (UUID, PK) → References `auth.users(id)`
- `email` (VARCHAR, UNIQUE, NOT NULL)
- `full_name` (VARCHAR)
- `avatar_url` (TEXT)
- `created_at`, `updated_at` (TIMESTAMPTZ)

**Relations:** 
- Parent to: `user_api_keys`, `interviews`, `feedback`
- Auto-populated via trigger on `auth.users` insert

**Access:** Users can read/update own profile only

---

### 2. `user_api_keys`
**Purpose:** Encrypted BYOK (Bring Your Own Keys) credential storage

**Structure:**
- `id` (UUID, PK)
- `user_id` (UUID, UNIQUE FK → `users.id`)
- `openai_key_encrypted` (TEXT)
- `deepgram_key_encrypted` (TEXT)
- `livekit_url_encrypted` (TEXT)
- `livekit_key_encrypted` (TEXT)
- `livekit_secret_encrypted` (TEXT)
- `encryption_salt` (TEXT, NOT NULL)
- `updated_at` (TIMESTAMPTZ)

**Relations:** 
- 1:1 with `users` (one API key set per user)
- CASCADE delete when user deleted

**Access:** Users manage own keys; service role has full access for encryption/decryption

**Index:** `user_id`

---

### 3. `interviews`
**Purpose:** Interview session records and metadata

**Structure:**
- `id` (UUID, PK)
- `user_id` (UUID, FK → `users.id`)
- `candidate_name` (VARCHAR)
- `interview_date` (TIMESTAMPTZ)
- `room_name` (VARCHAR, UNIQUE)
- `job_role` (VARCHAR)
- `experience_level` (VARCHAR)
- `final_stage` (VARCHAR)
- `ended_by` (VARCHAR)
- `skipped_stages` (JSONB, default `[]`)
- `has_resume`, `has_jd` (BOOLEAN)
- `conversation` (JSONB)
- `total_messages` (JSONB)
- `metadata` (JSONB, default `{}`)
- `created_at` (TIMESTAMPTZ)

**Relations:** 
- Many:1 with `users`
- Parent to: `feedback`
- CASCADE delete when user deleted

**Access:** Users read own interviews; service role inserts/updates

**Indexes:** `user_id`, `interview_date DESC`, `room_name`

---

### 4. `feedback`
**Purpose:** Interview feedback and analysis results

**Structure:**
- `id` (UUID, PK)
- `user_id` (UUID, FK → `users.id`)
- `interview_id` (UUID, UNIQUE FK → `interviews.id`)
- `feedback_data` (JSONB, NOT NULL)
- `created_at` (TIMESTAMPTZ)

**Relations:** 
- 1:1 with `interviews` (one feedback per interview)
- Many:1 with `users`
- CASCADE delete when user or interview deleted

**Access:** Users read own feedback; service role inserts/updates

**Indexes:** `interview_id`, `user_id`

---

## Relationship Summary
```
users (1) ──┬─→ (1) user_api_keys
            ├─→ (*) interviews ──→ (1) feedback
            └─→ (*) feedback
```

## Key Design Patterns

**BYOK Model:** All external API credentials stored encrypted in `user_api_keys`

**Service Role Operations:** Agent backend uses service key for insert/update operations on `interviews` and `feedback`

**User Isolation:** All tables use RLS policies ensuring users only access their own data

**Cascade Deletes:** User deletion automatically removes all associated records

**JSONB Storage:** Flexible schema for `conversation`, `total_messages`, `metadata`, and `feedback_data`