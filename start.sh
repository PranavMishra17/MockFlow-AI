#!/bin/bash
# Start script for MockFlow-AI on Render
# Runs both Flask web server and LiveKit agent using supervisord

echo "Starting MockFlow-AI with supervisord..."
exec supervisord -c supervisord.conf
