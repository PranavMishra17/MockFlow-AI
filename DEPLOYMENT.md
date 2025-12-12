# MockFlow-AI Deployment Guide

This guide will help you deploy MockFlow-AI to Render.

## Prerequisites

1. A [Render account](https://render.com/) (free tier available)
2. A [GitHub account](https://github.com/) with this repository

## API Key Configuration

**IMPORTANT**: MockFlow-AI uses **client-side API key storage** for security and cost management. This means:

- **No API keys are stored on the server** (Render)
- Each user configures their own API keys through the browser-based Settings modal
- API keys are stored securely in the user's browser localStorage with obfuscation
- Keys never leave the user's browser or get sent to the server

### Users Need API Keys From:
- [LiveKit Cloud](https://cloud.livekit.io/) - Real-time voice communication
- [OpenAI](https://platform.openai.com/api-keys) - LLM and TTS
- [Deepgram](https://console.deepgram.com/) - Speech-to-Text

## Deployment Steps

### 1. Deploy to Render

No environment variables are required on Render! The application will run without any API keys configured on the server.

### 2. Configure Render Service

Use these settings in your Render web service:

| Setting | Value |
|---------|-------|
| **Language** | Python 3 |
| **Build Command** | `pip install -r requirements.txt && chmod +x start.sh` |
| **Start Command** | `./start.sh` |
| **Health Check Path** | `/healthz` |
| **Auto-Deploy** | On Commit (recommended) |

### 3. Deploy

Render will automatically:
1. Pull your code from GitHub
2. Install dependencies from `requirements.txt`
3. Run both Flask server and LiveKit agent using supervisord
4. Health check on `/healthz`

## User Setup (After Deployment)

When users first visit your deployed MockFlow-AI application:

1. **Homepage**: Users will see three action buttons in the top-right:
   - **GitHub** (center) - Link to the project repository
   - **Settings** (gear icon) - Configure API keys
   - **About** (info icon) - Developer information

2. **First-Time Setup**: When users click "Begin Interview" without configured keys, the Settings modal will automatically open prompting them to enter their API keys.

3. **API Key Configuration**:
   - Users enter their own API keys from LiveKit, OpenAI, and Deepgram
   - Keys are validated (format checks)
   - Keys are obfuscated using XOR cipher
   - Keys are stored in browser localStorage
   - Keys persist across sessions on the same device/browser

4. **Starting Interviews**: Once keys are configured, users can start mock interviews that use their own API credentials.

## Architecture

The app runs **two processes** simultaneously:
- **Flask Web Server** (port assigned by Render) - Serves the web interface
- **LiveKit Agent** - Handles real-time voice interviews

Both processes are managed by `supervisord` via the `start.sh` script.

## Monitoring

- **Health Check**: `GET /healthz` returns `OK 200` when healthy
- **Logs**: View in Render Dashboard → Your Service → Logs
- **Both processes** log to stdout/stderr for centralized logging

## Troubleshooting

### Service Won't Start
- View logs in Render dashboard
- Check build command completed successfully
- Verify supervisord is running both processes

### Health Check Failing
- Ensure Flask server is running (check logs)
- Test `/healthz` endpoint manually

### API Key Issues
- Users should verify their API keys are correct
- Check browser console for API key validation errors
- Keys must follow format requirements:
  - LiveKit URL: Must start with `wss://`
  - OpenAI Key: Must start with `sk-`
  - All keys: Minimum 10 characters

### Interview Won't Start
- User must configure API keys first via Settings modal
- If modal doesn't auto-open, click Settings button (gear icon)
- Clear browser localStorage and reconfigure keys if issues persist

## Cost Management

**Important**: Since users provide their own API keys:
- **You don't pay for API usage** - each user uses their own credentials
- Users should monitor their own usage in provider dashboards
- Recommend users set up billing alerts with their providers
- Users can take advantage of free tiers from LiveKit, OpenAI, and Deepgram

## Local Development

For local development, you have two options:

### Option 1: Browser-based Keys (Recommended)
1. Run the application locally
2. Configure API keys through the Settings modal in your browser
3. Keys will persist in your browser's localStorage

### Option 2: Environment Variables (Optional)
Create a `.env` file for local development only:

```bash
cp .env.example .env
# Edit .env with your actual API keys (OPTIONAL)
```

**Note**: Server-side environment variables are optional. The app will fall back to browser-stored keys if server keys are not present.

Run locally:
```bash
# Terminal 1: Flask server
python app.py

# Terminal 2: LiveKit agent
python agent.py dev
```

## GitHub Actions

The project includes CI/CD via GitHub Actions:
- Runs tests on pull requests
- Auto-deploys to Render on push to `main`

## Support

For issues or questions:
- Check [Render Documentation](https://render.com/docs)
- Review [LiveKit Agents SDK](https://docs.livekit.io/agents)
