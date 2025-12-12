#!/bin/bash
# Entrypoint for the LiveKit agent used by supervisord.
# If LiveKit credentials are not present, keep this process alive
# but do not start the agent to avoid crashing supervisord.

echo "Agent entrypoint starting..."

if [ -z "$LIVEKIT_API_KEY" ] || [ -z "$LIVEKIT_API_SECRET" ] || [ -z "$LIVEKIT_URL" ]; then
  echo "LiveKit environment variables not set. Agent will not start. Sleeping to stay alive."
  # Keep the process alive so supervisord doesn't repeatedly try to restart a failing process
  tail -f /dev/null
else
  echo "LiveKit environment variables present — starting agent"
  exec python agent.py start
fi
