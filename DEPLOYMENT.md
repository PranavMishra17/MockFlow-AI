# MockFlow-AI Deployment Guide

Complete guide for deploying MockFlow-AI to Render with Supabase backend.

---

## Prerequisites

Before deploying, ensure you have:

1. **GitHub Repository**: Code pushed to GitHub (main branch)
2. **Supabase Project**: Created and configured
3. **Google Cloud OAuth**: Credentials configured
4. **Render Account**: Free tier account created

---

## Part 1: Supabase Configuration

### 1.1 Create Supabase Project

1. Go to [supabase.com](https://supabase.com)
2. Create new project
3. Wait for database provisioning (2-3 minutes)

### 1.2 Run Database Migrations

Execute these SQL commands in Supabase SQL Editor:

```sql
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table (managed by Supabase Auth)
-- No need to create - handled by Supabase

-- API Keys table (encrypted BYOK storage)
CREATE TABLE IF NOT EXISTS user_api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    livekit_url TEXT,
    livekit_api_key TEXT,
    livekit_api_secret TEXT,
    openai_key TEXT,
    deepgram_key TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);

-- Interviews table (database-only storage)
CREATE TABLE IF NOT EXISTS interviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    candidate_name TEXT NOT NULL,
    interview_date TIMESTAMP WITH TIME ZONE NOT NULL,
    room_name TEXT,
    job_role TEXT,
    experience_level TEXT,
    conversation JSONB,
    total_messages JSONB,
    skipped_stages TEXT[],
    final_stage TEXT,
    ended_by TEXT,
    has_resume BOOLEAN DEFAULT FALSE,
    has_jd BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Feedback table
CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    interview_id UUID NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    feedback_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(interview_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_interviews_user_date
ON interviews(user_id, interview_date DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_interview
ON feedback(interview_id);

CREATE INDEX IF NOT EXISTS idx_api_keys_user
ON user_api_keys(user_id);

-- Row Level Security (RLS)
ALTER TABLE user_api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE interviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;

-- RLS Policies for user_api_keys
CREATE POLICY "Users can view own API keys"
ON user_api_keys FOR SELECT
USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own API keys"
ON user_api_keys FOR INSERT
WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own API keys"
ON user_api_keys FOR UPDATE
USING (auth.uid() = user_id);

-- RLS Policies for interviews
CREATE POLICY "Users can view own interviews"
ON interviews FOR SELECT
USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own interviews"
ON interviews FOR INSERT
WITH CHECK (auth.uid() = user_id);

-- RLS Policies for feedback
CREATE POLICY "Users can view own feedback"
ON feedback FOR SELECT
USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own feedback"
ON feedback FOR INSERT
WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own feedback"
ON feedback FOR UPDATE
USING (auth.uid() = user_id);
```

### 1.3 Get Supabase Credentials

Navigate to **Project Settings → API**:

- **Supabase URL**: `https://your-project.supabase.co`
- **Anon Key**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` (public key)
- **Service Role Key**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` (secret key - NEVER commit to git)

---

## Part 2: Google Cloud OAuth Setup

### 2.1 Create OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create new project or select existing
3. Navigate to **APIs & Services → Credentials**
4. Click **Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Web application**
6. Name: `MockFlow-AI`

### 2.2 Configure Authorized Redirect URIs

Add these URIs (replace with your actual domains):

**For Supabase Auth callback:**
```
https://your-project.supabase.co/auth/v1/callback
```

**For local development:**
```
http://localhost:5000/auth/callback
```

**For production (Render):**
```
https://your-app-name.onrender.com/auth/callback
```

### 2.3 Get OAuth Credentials

Copy these values:
- **Client ID**: `123456789-abcdef.apps.googleusercontent.com`
- **Client Secret**: `GOCSPX-abcdef123456` (keep secret)

### 2.4 Configure Supabase Auth

1. Go to Supabase Dashboard → **Authentication → Providers**
2. Enable **Google** provider
3. Paste Client ID and Client Secret
4. Save

---

## Part 3: Generate Security Keys

### 3.1 Generate Encryption Key

This key encrypts user API keys in the database:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Example output: `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6==`

**IMPORTANT**: Save this key securely. Losing it means users can't decrypt their API keys.

### 3.2 Generate Flask Secret Key

Used for session management:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Example output: `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2`

---

## Part 4: Render Deployment

### 4.1 Connect GitHub Repository

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **New → Web Service**
3. Connect your GitHub account
4. Select `MockFlow-AI` repository
5. Click **Connect**

### 4.2 Configure Service

**Basic Settings:**
- **Name**: `mockflow-ai`
- **Region**: Oregon (US West) or closest to you
- **Branch**: `main`
- **Runtime**: Python 3
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn app:app --workers 1 --timeout 120`

**IMPORTANT**: Use `--workers 1` (single worker) because the BYOK model uses subprocess management for agent workers. Multiple gunicorn workers create separate memory spaces, preventing proper subprocess tracking across requests.

**Instance Type:**
- Select **Free** tier (512MB RAM, 0.1 CPU)

### 4.3 Set Environment Variables

Click **Advanced → Add Environment Variable** and add each of these:

#### Required Environment Variables

| Variable Name | Where to Get | Example Value |
|--------------|--------------|---------------|
| `SUPABASE_URL` | Supabase Project Settings → API | `https://abcdef123456.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Supabase Project Settings → API → service_role key | `eyJhbGciOiJIUzI1NiIsInR5cCI6...` |
| `SUPABASE_ANON_KEY` | Supabase Project Settings → API → anon key | `eyJhbGciOiJIUzI1NiIsInR5cCI6...` |
| `ENCRYPTION_KEY` | Generated in Part 3.1 | `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6...` |
| `SECRET_KEY` | Generated in Part 3.2 | `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6...` |
| `GOOGLE_CLIENT_ID` | Google Cloud Console OAuth | `123456789-abcdef.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | Google Cloud Console OAuth | `GOCSPX-abcdef123456` |

#### Optional Environment Variables

| Variable Name | Default | Description |
|--------------|---------|-------------|
| `MAX_CONCURRENT_WORKERS` | `3` | Maximum simultaneous interviews |
| `PYTHON_VERSION` | `3.12` | Python runtime version |

### 4.4 Deploy

1. Click **Create Web Service**
2. Wait for deployment (3-5 minutes)
3. Monitor logs for errors

---

## Part 5: Post-Deployment Verification

### 5.1 Check Health Endpoint

Visit your deployment URL + `/health`:

```bash
curl https://your-app-name.onrender.com/health
```

Expected response:
```json
{
  "status": "healthy",
  "database": "connected",
  "workers": {
    "active": 0,
    "max": 3
  }
}
```

### 5.2 Test Authentication

1. Visit `https://your-app-name.onrender.com`
2. Click **Sign In with Google**
3. Verify redirect to Google OAuth
4. After login, verify redirect to Dashboard

### 5.3 Test Interview Flow

1. Go to **Settings → API Keys**
2. Enter your LiveKit, OpenAI, and Deepgram keys
3. Save and test keys
4. Go to **Dashboard → Start Interview**
5. Fill form and start interview
6. Verify agent spawns and speaks
7. Complete interview
8. Check Past Interviews page
9. Generate feedback

---

## Important Notes

### About API Keys (BYOK Model)

- **LiveKit**, **OpenAI**, and **Deepgram** keys are **NOT** set in Render environment
- Each user provides their own keys via the Settings page
- Keys are encrypted in database using `ENCRYPTION_KEY`
- Workers spawn with user's decrypted keys as subprocess environment variables

### Security Best Practices

1. **Never commit** `.env` file to git
2. **Never expose** `SUPABASE_SERVICE_KEY` publicly
3. **Never expose** `ENCRYPTION_KEY` (losing this breaks all stored API keys)
4. **Rotate keys** periodically (SECRET_KEY, GOOGLE_CLIENT_SECRET)
5. **Use HTTPS** only in production (Render provides this automatically)

### Free Tier Limits

- **Render**: 512MB RAM, 0.1 CPU, sleeps after 15 min inactivity
- **Supabase**: 500MB database, 2GB bandwidth/month
- **Max Concurrent Interviews**: 3 (configurable via `MAX_CONCURRENT_WORKERS`)

### Troubleshooting

**Issue: Health check fails**
- Verify `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are correct
- Check Supabase project is not paused (free tier)

**Issue: OAuth fails**
- Verify Google OAuth redirect URI matches exactly
- Check `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in Render

**Issue: Worker spawn fails**
- Check Render logs for subprocess errors
- Verify user has entered API keys in Settings
- Check memory usage (may hit 512MB limit with multiple workers)

**Issue: Database queries slow**
- Verify indexes are created (Part 1.2)
- Check Supabase logs for slow queries
- Consider upgrading Supabase plan

---

## Monitoring

### Check Logs

**Render Dashboard:**
- Go to your service → **Logs** tab
- Filter by severity (Info, Warning, Error)

**Important Log Patterns:**
- `[WORKER] Spawning worker for room: interview-*` - Worker starting
- `[WORKER] Worker spawned (PID: *)` - Worker started successfully
- `[SESSION] Successfully connected to room: *` - Agent connected
- `[FINALIZE] Interview saved successfully: *` - Interview saved to database
- `[HEALTH] Health check passed` - System healthy

### Monitor Active Workers

Visit `/health` endpoint to see current worker count:
```bash
watch -n 5 'curl -s https://your-app-name.onrender.com/health | jq'
```

---

## Rollback Plan

If deployment fails:

1. **Revert to previous commit**:
   ```bash
   git revert HEAD
   git push origin main
   ```

2. **Check Render deployment logs** for specific errors

3. **Verify environment variables** in Render dashboard

4. **Test locally** with same environment variables:
   ```bash
   # Copy .env.example to .env
   # Fill in production values
   python app.py
   ```

---

## Support

- **GitHub Issues**: [Report bugs](https://github.com/yourusername/MockFlow-AI/issues)
- **Render Status**: [status.render.com](https://status.render.com)
- **Supabase Status**: [status.supabase.com](https://status.supabase.com)

---

## Summary Checklist

- [ ] Supabase project created and migrations run
- [ ] Google Cloud OAuth configured with correct redirect URIs
- [ ] Encryption key and secret key generated
- [ ] Render service created and connected to GitHub
- [ ] All 7 required environment variables set in Render
- [ ] Service deployed successfully (check logs)
- [ ] `/health` endpoint returns 200 OK
- [ ] Google OAuth login works
- [ ] Users can save API keys
- [ ] Interview flow works end-to-end (spawn worker, connect, save to DB)
- [ ] Feedback generation works
- [ ] Past interviews loads from database

**Deployment Complete!** 🎉
