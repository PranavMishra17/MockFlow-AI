#!/bin/bash
# Start script for MockFlow-AI on Render
# Runs both Flask web server and LiveKit agent using supervisord

echo "Starting MockFlow-AI with supervisord..."
# Ensure entrypoint scripts are executable (Render build may only chmod start.sh)
chmod +x ./agent_entrypoint.sh || true

# Conditionally start the LiveKit agent in the background if explicitly enabled and
# all required LiveKit environment variables are present. This avoids managing the
# agent under supervisord by default while allowing operators to enable it later
# via environment variables without changing code.
if [ "${ENABLE_LIVEKIT_AGENT:-false}" = "true" ] && [ -n "$LIVEKIT_API_KEY" ] && [ -n "$LIVEKIT_API_SECRET" ] && [ -n "$LIVEKIT_URL" ]; then
	echo "ENABLE_LIVEKIT_AGENT=true and LiveKit credentials present — starting agent in background"
	nohup ./agent_entrypoint.sh >/dev/stdout 2>/dev/stderr &
else
	echo "LiveKit agent will not be started (either ENABLE_LIVEKIT_AGENT not set or credentials missing)"
fi

exec supervisord -c supervisord.conf
