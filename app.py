"""
MockFlow-AI Flask Web Server

Provides web interface for the mock interview system.
Handles candidate registration and LiveKit token generation.
"""

import os
import time
import logging
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from livekit import api
from dotenv import load_dotenv

# Load environment variables from .env file in project root
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("flask-app")

# Create Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for API endpoints

# Configuration from environment (may be intentionally absent in production)
LIVEKIT_URL = os.getenv('LIVEKIT_URL')
LIVEKIT_API_KEY = os.getenv('LIVEKIT_API_KEY')
LIVEKIT_API_SECRET = os.getenv('LIVEKIT_API_SECRET')

# Do not fail at import time when LiveKit credentials are intentionally
# not provided (we support a deployment mode where clients supply keys).
if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
    logger.warning(
        "[CONFIG] LiveKit environment variables are not set. "
        "Token generation endpoint will be disabled."
    )
else:
    logger.info(f"[CONFIG] LiveKit URL: {LIVEKIT_URL}")


# Serve the site favicon from the `public` directory so browsers show the tab icon
@app.route('/favicon.ico')
def favicon():
    """Serve the ICO favicon at /favicon.ico (served from `public/favicon.ico`)."""
    try:
        public_dir = os.path.join(app.root_path, 'public')
        response = send_from_directory(public_dir, 'favicon.ico', mimetype='image/x-icon')
        # Add cache headers to ensure browser caches the favicon for 1 week
        response.headers['Cache-Control'] = 'public, max-age=604800'
        return response
    except Exception:
        # Fallback to 404 if not present
        return ('', 404)


@app.route('/')
def index():
    """Landing page."""
    logger.info("[ROUTE] / - Landing page accessed")
    return render_template('index.html')


@app.route('/healthz')
def healthz():
    """Simple health endpoint used by platform health checks."""
    return 'OK', 200


@app.route('/start')
def start_form():
    """Candidate registration form."""
    logger.info("[ROUTE] /start - Registration form accessed")
    return render_template('form.html')


@app.route('/interview')
def interview():
    """Interview room page."""
    name = request.args.get('name', 'Candidate')
    email = request.args.get('email', '')
    role = request.args.get('role', '')
    level = request.args.get('level', '')

    logger.info(
        f"[ROUTE] /interview - Interview room accessed by {name} "
        f"(role: {role}, level: {level})"
    )

    return render_template(
        'interview.html',
        name=name,
        email=email,
        role=role,
        level=level
    )


@app.route('/api/token', methods=['POST'])
def generate_token():
    """
    Generate LiveKit access token for candidate.

    Expected JSON body:
    {
        "name": "Candidate Name",
        "email": "email@example.com",
        "role": "Software Engineer",
        "level": "mid"
    }

    Returns:
    {
        "token": "jwt_token",
        "url": "wss://livekit.server.com",
        "room": "interview-name-timestamp"
    }
    """
    try:
        # If server-side LiveKit credentials are not configured, return a clear error
        # instead of raising at import time. The front-end deployment mode for this
        # project supports client-side keys, so server token generation is optional.
        if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
            return jsonify({
                'error': 'server_livekit_not_configured',
                'message': 'Server-side LiveKit credentials are not set. Token generation is disabled.'
            }), 501

        data = request.json
        name = data.get('name', 'Anonymous')
        email = data.get('email', '')
        role = data.get('role', '')
        level = data.get('level', '')

        # Create unique room name
        timestamp = int(time.time())
        room_name = f"interview-{name.lower().replace(' ', '-')}-{timestamp}"

        logger.info(
            f"[API] Token generation requested for {name} "
            f"(email: {email}, role: {role}, level: {level})"
        )

        # Create LiveKit access token
        token = api.AccessToken(
            LIVEKIT_API_KEY,
            LIVEKIT_API_SECRET
        )

        # Set identity and grants
        token.with_identity(name).with_name(name).with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )
        )

        # Generate JWT
        jwt_token = token.to_jwt()

        logger.info(f"[API] Token generated successfully for room: {room_name}")

        return jsonify({
            'token': jwt_token,
            'url': LIVEKIT_URL,
            'room': room_name,
            'candidate': {
                'name': name,
                'email': email,
                'role': role,
                'level': level
            }
        })

    except Exception as e:
        logger.error(f"[API] Token generation error: {e}", exc_info=True)
        return jsonify({
            'error': 'Failed to generate token',
            'message': str(e)
        }), 500


@app.route('/api/health')
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({
        'status': 'healthy',
        'service': 'MockFlow-AI',
        'livekit_configured': bool(LIVEKIT_URL and LIVEKIT_API_KEY)
    })


@app.route('/healthz')
def healthz():
    """Render health check endpoint."""
    return 'OK', 200


@app.errorhandler(404)
def not_found(e):
    """Custom 404 handler."""
    logger.warning(f"[ERROR] 404 - {request.path}")
    return render_template('error.html', error='Page not found'), 404


@app.errorhandler(500)
def internal_error(e):
    """Custom 500 handler."""
    logger.error(f"[ERROR] 500 - {str(e)}", exc_info=True)
    return render_template('error.html', error='Internal server error'), 500


if __name__ == '__main__':
    logger.info("[MAIN] Starting Flask web server")
    logger.info("[MAIN] Access the application at http://localhost:5000")

    # Run Flask app
    app.run(
        debug=True,
        port=5000,
        host='0.0.0.0'
    )
