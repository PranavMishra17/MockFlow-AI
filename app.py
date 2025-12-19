"""
MockFlow-AI Flask Web Server

Provides web interface for the mock interview system.
Handles candidate registration, LiveKit token generation, document upload,
interview history, and feedback endpoints.
"""

import os
import time
import logging
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, session
from flask_cors import CORS
from livekit import api
from dotenv import load_dotenv

from document_processor import doc_processor, DocumentMetadata
from postprocess import resequence_interview, list_interviews, get_interview_summary
from conversation_cache import conversation_cache, ConversationMetadata
from supabase_client import supabase_client
from auth_helpers import require_auth, get_current_user, get_user_id, is_authenticated

# In-memory feedback cache
feedback_cache = {}

# Load environment variables from .env file in project root
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-prod')
CORS(app)  # Enable CORS for API endpoints

# Configuration from environment
LIVEKIT_URL = os.getenv('LIVEKIT_URL')
LIVEKIT_API_KEY = os.getenv('LIVEKIT_API_KEY')
LIVEKIT_API_SECRET = os.getenv('LIVEKIT_API_SECRET')

# Validate configuration
if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
    logger.error("[CONFIG] Missing required LiveKit environment variables")
    raise ValueError(
        "Missing required environment variables. "
        "Please set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET"
    )

logger.info(f"[CONFIG] LiveKit URL: {LIVEKIT_URL}")


# ==================== AUTH ENDPOINTS ====================

@app.route('/auth/login')
def login():
    """Redirect to Supabase Google OAuth"""
    try:
        redirect_url = f"{request.host_url}auth/callback"
        auth_url = f"{os.getenv('SUPABASE_URL')}/auth/v1/authorize?provider=google&redirect_to={redirect_url}"
        logger.info(f"[AUTH] Redirecting to OAuth: {auth_url}")
        return redirect(auth_url)
    except Exception as e:
        logger.error(f"[AUTH] Login error: {e}")
        return "Login failed", 500

@app.route('/auth/callback')
def auth_callback():
    """
    Handle OAuth callback from Supabase.

    Supabase returns tokens in URL fragment (#access_token=...) not query params.
    We need to render a page that extracts tokens from fragment using JavaScript.
    """
    try:
        # Log all incoming parameters for debugging
        logger.info(f"[AUTH] Callback received - Query params: {dict(request.args)}")
        logger.info(f"[AUTH] Callback received - Full URL: {request.url}")

        # Render a page that will extract tokens from URL fragment using JavaScript
        return render_template('auth_callback.html')
    except Exception as e:
        logger.error(f"[AUTH] Auth callback error: {e}", exc_info=True)
        return "Authentication failed", 500

@app.route('/auth/session', methods=['POST'])
def set_session():
    """Set session from tokens extracted by JavaScript"""
    try:
        data = request.json or {}
        access_token = data.get('access_token')
        refresh_token = data.get('refresh_token')

        logger.info(f"[AUTH] Setting session - has access_token: {bool(access_token)}, has refresh_token: {bool(refresh_token)}")

        if not access_token:
            logger.error("[AUTH] No access token provided")
            return jsonify({'error': 'No access token'}), 400

        session['access_token'] = access_token
        if refresh_token:
            session['refresh_token'] = refresh_token

        logger.info("[AUTH] User authenticated successfully")
        return jsonify({
            'success': True,
            'redirect': url_for('dashboard')
        })
    except Exception as e:
        logger.error(f"[AUTH] Set session error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/auth/logout')
def logout():
    """Clear session and logout"""
    session.clear()
    logger.info("[AUTH] User logged out")
    return redirect(url_for('index'))

@app.route('/api/auth/status')
def auth_status():
    """Check authentication status"""
    try:
        access_token = session.get('access_token')
        logger.info(f"[AUTH] Status check - has session token: {bool(access_token)}")

        user = get_current_user()
        if user:
            logger.info(f"[AUTH] User authenticated: {user.user.email}")
            return jsonify({
                'authenticated': True,
                'user': {
                    'id': user.user.id,
                    'email': user.user.email,
                    'name': user.user.user_metadata.get('full_name'),
                    'avatar': user.user.user_metadata.get('avatar_url')
                }
            })
        logger.info("[AUTH] No authenticated user found")
        return jsonify({'authenticated': False})
    except Exception as e:
        logger.error(f"[AUTH] Auth status error: {e}", exc_info=True)
        return jsonify({'authenticated': False})


# ==================== USER API KEYS ENDPOINTS ====================

@app.route('/api/user/keys/status')
@require_auth
def get_keys_status():
    """Check if user has API keys configured"""
    try:
        user_id = get_user_id()
        keys = supabase_client.get_api_keys(user_id)

        if keys:
            return jsonify({
                'has_keys': True,
                'livekit_url_masked': f"wss://{keys['livekit_url'].split('//')[1][:15]}...",
                'livekit_key_masked': f"{keys['livekit_api_key'][:8]}...",
                'openai_masked': f"sk-...{keys['openai_key'][-4:]}",
                'deepgram_masked': f"...{keys['deepgram_key'][-4:]}"
            })

        return jsonify({'has_keys': False})
    except Exception as e:
        logger.error(f"[API] Failed to get keys status: {e}", exc_info=True)
        return jsonify({'has_keys': False})


@app.route('/api/user/keys', methods=['POST'])
@require_auth
def save_user_keys():
    """Save user's API keys (encrypted)"""
    try:
        user_id = get_user_id()
        data = request.json or {}

        livekit_url = data.get('livekit_url')
        livekit_api_key = data.get('livekit_api_key')
        livekit_api_secret = data.get('livekit_api_secret')
        openai_key = data.get('openai_key')
        deepgram_key = data.get('deepgram_key')

        if not all([livekit_url, livekit_api_key, livekit_api_secret, openai_key, deepgram_key]):
            return jsonify({'error': 'All API keys required'}), 400

        success = supabase_client.save_api_keys(
            user_id, livekit_url, livekit_api_key, livekit_api_secret,
            openai_key, deepgram_key
        )

        if success:
            logger.info(f"[API] API keys saved for user: {user_id}")
            return jsonify({'success': True, 'message': 'Keys saved successfully'})

        return jsonify({'error': 'Failed to save keys'}), 500

    except Exception as e:
        logger.error(f"[API] Failed to save keys: {e}", exc_info=True)
        return jsonify({'error': 'Internal error'}), 500


@app.route('/api/user/keys/validate', methods=['POST'])
@require_auth
def validate_keys():
    """Test API keys validity"""
    try:
        data = request.json or {}
        livekit_url = data.get('livekit_url')
        livekit_api_key = data.get('livekit_api_key')
        livekit_api_secret = data.get('livekit_api_secret')
        openai_key = data.get('openai_key')
        deepgram_key = data.get('deepgram_key')

        if not livekit_url or not (livekit_url.startswith('wss://') or livekit_url.startswith('ws://')):
            return jsonify({'valid': False, 'message': 'Invalid LiveKit URL format'})

        if not livekit_api_key or len(livekit_api_key) < 5:
            return jsonify({'valid': False, 'message': 'Invalid LiveKit API Key'})

        if not livekit_api_secret or len(livekit_api_secret) < 10:
            return jsonify({'valid': False, 'message': 'Invalid LiveKit API Secret'})

        if not openai_key or not openai_key.startswith('sk-'):
            return jsonify({'valid': False, 'message': 'Invalid OpenAI key format'})

        if not deepgram_key or len(deepgram_key) < 10:
            return jsonify({'valid': False, 'message': 'Invalid Deepgram key format'})

        return jsonify({'valid': True})
    except Exception as e:
        logger.error(f"[API] Key validation failed: {e}", exc_info=True)
        return jsonify({'valid': False, 'message': 'Validation error'}), 500


# ==================== STATIC FILES ====================

@app.route('/favicon.ico')
def favicon():
    """Serve the ICO favicon."""
    try:
        public_dir = os.path.join(app.root_path, 'public')
        response = send_from_directory(public_dir, 'favicon.ico', mimetype='image/x-icon')
        response.headers['Cache-Control'] = 'public, max-age=604800'
        return response
    except Exception:
        return ('', 404)


# ==================== PAGE ROUTES ====================

@app.route('/')
def index():
    """Landing page."""
    logger.info("[ROUTE] / - Landing page accessed")
    return render_template('index.html')


@app.route('/dashboard')
@require_auth
def dashboard():
    """User dashboard (protected)."""
    logger.info("[ROUTE] /dashboard - Dashboard accessed")
    return render_template('dashboard.html')


@app.route('/api-keys')
@require_auth
def api_keys_page():
    """API keys management page (protected)."""
    logger.info("[ROUTE] /api-keys - API keys page accessed")
    return render_template('api_keys.html')


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


@app.route('/past-calls')
def past_calls():
    """Past interviews list page."""
    logger.info("[ROUTE] /past-calls - Past interviews page accessed")
    return render_template('past_calls.html')


@app.route('/past_calls.html')
def past_calls_alias():
    """Legacy alias to support links pointing to past_calls.html."""
    logger.info("[ROUTE] /past_calls.html - Past calls alias accessed")
    return render_template('past_calls.html')


@app.route('/history')
def history_redirect():
    """Redirect older /history endpoint to the new past-calls page."""
    logger.info("[ROUTE] /history - Redirecting to /past-calls")
    return redirect(url_for('past_calls'))


@app.route('/feedback/<filename>')
def feedback_page(filename):
    """Feedback page for a specific interview."""
    logger.info(f"[ROUTE] /feedback/{filename} - Feedback page accessed")
    return render_template('feedback.html', filename=filename)


# ==================== TOKEN API ====================

@app.route('/api/token', methods=['POST'])
def generate_token():
    """
    Generate LiveKit access token for candidate.

    Expected JSON body:
    {
        "name": "Candidate Name",
        "email": "email@example.com",
        "role": "Software Engineer",
        "level": "mid",
        "resumeCacheKey": "optional_cache_key",
        "jobDescription": "optional_jd_text",
        "includeProfile": true
    }

    Returns:
    {
        "token": "jwt_token",
        "url": "wss://livekit.server.com",
        "room": "interview-name-timestamp"
    }
    """
    try:
        data = request.json
        name = data.get('name', 'Anonymous')
        email = data.get('email', '')
        role = data.get('role', '')
        level = data.get('level', '')
        resume_cache_key = data.get('resumeCacheKey', '')
        job_description = data.get('jobDescription', '')
        include_profile = data.get('includeProfile', True)

        # Create unique room name
        timestamp = int(time.time())
        room_name = f"interview-{name.lower().replace(' ', '-')}-{timestamp}"

        logger.info(
            f"[API] Token generation requested for {name} "
            f"(email: {email}, role: {role}, level: {level})"
        )

        # Build participant attributes
        attributes = {
            'role': role,
            'level': level,
            'email': email,
            'include_profile': str(include_profile).lower(),
        }

        # Add resume text if cached
        if resume_cache_key:
            resume_text = doc_processor.get_cached_text(resume_cache_key)
            if resume_text:
                # Truncate to fit in attributes (LiveKit has limits)
                attributes['resume_text'] = resume_text[:3000]
                logger.info(f"[API] Attached resume text ({len(resume_text)} chars)")

        # Add job description if provided
        if job_description:
            attributes['job_description'] = job_description[:2000]
            logger.info(f"[API] Attached job description ({len(job_description)} chars)")

        # Create LiveKit access token
        token = api.AccessToken(
            LIVEKIT_API_KEY,
            LIVEKIT_API_SECRET
        )

        # Set identity and grants with metadata
        token.with_identity(name).with_name(name).with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )
        ).with_attributes(attributes)

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


# ==================== DOCUMENT UPLOAD API ====================

@app.route('/api/upload-resume', methods=['POST'])
def upload_resume():
    """
    Upload and extract text from resume/portfolio/job description.
    
    Accepts multipart form with:
        - file: The document file (PDF, DOCX, MD, TXT)
        - document_type: 'resume' | 'job_description' | 'portfolio'
        - include_profile: boolean (optional, default true)
    
    Returns:
        - cache_key: Key to retrieve cached text
        - text_preview: First 500 chars of extracted text
        - char_count: Total character count
    """
    try:
        # Check for file
        if 'file' not in request.files:
            return jsonify({
                'error': 'No file provided',
                'message': 'Please upload a file'
            }), 400
            
        file = request.files['file']
        
        if not file.filename:
            return jsonify({
                'error': 'No file selected',
                'message': 'Please select a file to upload'
            }), 400
            
        # Get document type
        document_type = request.form.get('document_type', 'resume')
        if document_type not in ['resume', 'job_description', 'portfolio']:
            document_type = 'resume'
            
        include_profile = request.form.get('include_profile', 'true').lower() == 'true'
        
        logger.info(
            f"[API] Upload request: {file.filename} "
            f"(type: {document_type}, include_profile: {include_profile})"
        )
        
        # Extract text
        extracted_text = doc_processor.extract_text(file, filename=file.filename)
        
        if not extracted_text or extracted_text.startswith('['):
            # Extraction failed or returned error message
            return jsonify({
                'error': 'Extraction failed',
                'message': extracted_text or 'Could not extract text from file'
            }), 400
            
        # Create metadata
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset
        
        metadata = DocumentMetadata(
            filename=file.filename,
            document_type=document_type,
            uploaded_at=time.time(),
            file_size=file_size,
            extraction_method='auto',
            char_count=len(extracted_text)
        )
        
        # Cache the extracted text (NOT the file)
        cache_key = doc_processor.cache_document(extracted_text, metadata)
        
        logger.info(
            f"[API] Document cached: {cache_key} "
            f"({len(extracted_text)} chars from {file.filename})"
        )
        
        return jsonify({
            'success': True,
            'cache_key': cache_key,
            'filename': file.filename,
            'document_type': document_type,
            'char_count': len(extracted_text),
            'text_preview': extracted_text[:500] + ('...' if len(extracted_text) > 500 else ''),
            'include_profile': include_profile
        })
        
    except Exception as e:
        logger.error(f"[API] Upload error: {e}", exc_info=True)
        return jsonify({
            'error': 'Upload failed',
            'message': str(e)
        }), 500


# ==================== CONVERSATION CACHE API ====================

@app.route('/api/conversation/cache', methods=['POST'])
def cache_conversation():
    """
    Cache a conversation from the agent.
    
    Expected JSON body:
    {
        "conversation": {"agent": [...], "user": [...]},
        "candidate_name": "John Doe",
        "room_name": "interview-john-1234",
        "job_role": "Software Engineer",
        "experience_level": "mid",
        "final_stage": "closing",
        "ended_by": "natural_completion",
        "skipped_stages": []
    }
    
    Returns:
        - cache_key: Key to retrieve conversation
    """
    try:
        data = request.json or {}
        
        conversation = data.get('conversation', {})
        if not conversation:
            return jsonify({
                'error': 'No conversation provided',
                'message': 'Please provide conversation data'
            }), 400
        
        # Create metadata
        from datetime import datetime
        metadata = ConversationMetadata(
            candidate_name=data.get('candidate_name', 'Unknown'),
            interview_date=datetime.now().isoformat(),
            room_name=data.get('room_name', ''),
            job_role=data.get('job_role', ''),
            experience_level=data.get('experience_level', ''),
            final_stage=data.get('final_stage', ''),
            ended_by=data.get('ended_by', 'unknown'),
            skipped_stages=data.get('skipped_stages', []),
            has_resume=data.get('has_resume', False),
            has_jd=data.get('has_jd', False)
        )
        
        # Cache the conversation
        cache_key = conversation_cache.cache_conversation(conversation, metadata)
        
        if not cache_key:
            return jsonify({
                'error': 'Cache failed',
                'message': 'Failed to cache conversation'
            }), 500
        
        logger.info(f"[API] Conversation cached: {cache_key}")
        
        return jsonify({
            'success': True,
            'cache_key': cache_key,
            'message': 'Conversation cached successfully'
        })
        
    except Exception as e:
        logger.error(f"[API] Cache conversation error: {e}", exc_info=True)
        return jsonify({
            'error': 'Cache failed',
            'message': str(e)
        }), 500


@app.route('/api/conversation/<cache_key>')
def get_cached_conversation(cache_key):
    """Get a cached conversation by key."""
    try:
        conversation = conversation_cache.get_conversation(cache_key)
        
        if not conversation:
            return jsonify({
                'error': 'Conversation not found',
                'message': f'No conversation found with key: {cache_key}'
            }), 404
        
        return jsonify({
            'success': True,
            'conversation': conversation
        })
        
    except Exception as e:
        logger.error(f"[API] Get conversation error: {e}", exc_info=True)
        return jsonify({
            'error': 'Failed to get conversation',
            'message': str(e)
        }), 500


# ==================== INTERVIEW HISTORY API ====================

@app.route('/api/interviews')
def get_interviews():
    """
    List all saved interview files.
    
    Returns list of interview metadata from both cache and files.
    """
    try:
        interviews = list_interviews()
        logger.info(f"[API] Listed {len(interviews)} interviews")
        return jsonify({
            'success': True,
            'interviews': interviews,
            'count': len(interviews)
        })
    except Exception as e:
        logger.error(f"[API] List interviews error: {e}", exc_info=True)
        return jsonify({
            'error': 'Failed to list interviews',
            'message': str(e)
        }), 500


@app.route('/api/interview/<filename>')
def get_interview(filename):
    """
    Get re-sequenced interview transcript.
    
    Args:
        filename: Interview JSON filename or cache key
        
    Returns:
        Re-sequenced conversation with metadata.
    """
    try:
        # Security: Ensure filename is safe
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({
                'error': 'Invalid filename'
            }), 400
            
        result = resequence_interview(filename)
        
        if 'error' in result and result.get('error'):
            return jsonify(result), 404
            
        logger.info(f"[API] Resequenced interview: {filename}")
        return jsonify({
            'success': True,
            **result
        })
        
    except Exception as e:
        logger.error(f"[API] Get interview error: {e}", exc_info=True)
        return jsonify({
            'error': 'Failed to get interview',
            'message': str(e)
        }), 500


@app.route('/api/interview/<filename>/summary')
def get_interview_summary_api(filename):
    """Get interview summary without full transcript."""
    try:
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({'error': 'Invalid filename'}), 400
            
        summary = get_interview_summary(filename)
        
        if 'error' in summary:
            return jsonify(summary), 404
            
        return jsonify({
            'success': True,
            **summary
        })
        
    except Exception as e:
        logger.error(f"[API] Interview summary error: {e}", exc_info=True)
        return jsonify({
            'error': 'Failed to get summary',
            'message': str(e)
        }), 500


# ==================== FEEDBACK API ====================

# Feedback cache for storing generated feedback
_feedback_cache = {}


@app.route('/api/feedback/cached/<interview_id>')
def get_cached_feedback(interview_id):
    """
    Get cached feedback for an interview if available.
    
    Args:
        interview_id: Interview filename or cache key
        
    Returns:
        Cached feedback or 404 if not found.
    """
    try:
        if interview_id in _feedback_cache:
            cached = _feedback_cache[interview_id]
            logger.info(f"[API] Returning cached feedback for: {interview_id}")
            return jsonify({
                'success': True,
                'interview_id': interview_id,
                'feedback': cached.get('feedback'),
                'cached_at': cached.get('cached_at'),
                'from_cache': True
            })
        
        return jsonify({
            'error': 'No cached feedback',
            'message': f'No cached feedback found for: {interview_id}'
        }), 404
        
    except Exception as e:
        logger.error(f"[API] Get cached feedback error: {e}", exc_info=True)
        return jsonify({
            'error': 'Failed to get cached feedback',
            'message': str(e)
        }), 500

def _load_interview_context(interview_id):
    """
    Helper to load interview transcript and context for feedback generation.
    
    Returns:
        tuple: (interview_chat, candidate_profile, job_summary, meta, conversation, error)
    """
    import json as json_module
    
    # Load and resequence the interview transcript
    resequenced = resequence_interview(interview_id)
    if 'error' in resequenced and resequenced.get('error'):
        return None, None, None, None, None, f'Could not find interview: {interview_id}'
    
    # Build the interview chat transcript
    conversation = resequenced.get('ordered_conversation', [])
    meta = resequenced.get('meta', {})
    
    if not conversation:
        return None, None, None, None, None, 'No conversation found in this interview'
    
    # Format transcript for LLM
    transcript_lines = []
    for turn in conversation:
        role = "INTERVIEWER" if turn['role'] == 'agent' else "CANDIDATE"
        stage_info = f" [{turn['stage']}]" if turn.get('stage') else ""
        transcript_lines.append(f"{role}{stage_info}: {turn['text']}")
    
    interview_chat = "\n\n".join(transcript_lines)
    
    # Build candidate profile and job summary from metadata
    candidate_profile = f"Name: {meta.get('candidate', 'Unknown')}"
    job_summary = "Role: Not specified"
    
    # Try to get additional context
    if meta.get('job_role'):
        job_summary = f"Role: {meta.get('job_role', 'Not specified')}"
    if meta.get('experience_level'):
        candidate_profile += f"\nExperience Level: {meta.get('experience_level', 'Not specified')}"
    
    # If source is file, try to load raw data for more context
    if meta.get('source') == 'file':
        try:
            interview_path = Path("interviews") / interview_id
            with open(interview_path, 'r', encoding='utf-8') as f:
                raw_data = json_module.load(f)
                
            if raw_data.get('job_role'):
                job_summary = f"Role: {raw_data.get('job_role', 'Not specified')}"
            if raw_data.get('experience_level'):
                candidate_profile = f"Name: {meta.get('candidate', 'Unknown')}\nExperience Level: {raw_data.get('experience_level', 'Not specified')}"
        except Exception as e:
            logger.warning(f"[API] Could not load raw interview data: {e}")
    
    return interview_chat, candidate_profile, job_summary, meta, conversation, None


@app.route('/api/feedback/scores', methods=['POST'])
def generate_feedback_scores():
    """
    Stage 1: Extract structured competency scores from interview.
    
    Returns JSON with scores for visual display (charts, gauges).
    This is faster than full feedback and enables progressive loading.
    
    Expected JSON body:
        - interview_id: Interview filename or identifier
        
    Returns:
        Structured scores with competencies, overall score, and headline.
    """
    import json as json_module
    from openai import OpenAI
    from prompts import FEEDBACKSCORES
    
    try:
        data = request.json or {}
        interview_id = data.get('interview_id')
        
        if not interview_id:
            return jsonify({
                'error': 'Missing interview_id',
                'message': 'Please provide an interview_id'
            }), 400
            
        logger.info(f"[API] Feedback scores requested for: {interview_id}")
        
        # Load interview context
        interview_chat, candidate_profile, job_summary, meta, conversation, error = _load_interview_context(interview_id)
        
        if error:
            return jsonify({'error': 'Interview not found', 'message': error}), 404
        
        # Build scores extraction prompt
        user_prompt = FEEDBACKSCORES.user_template.format(
            candidate_profile=candidate_profile,
            job_summary=job_summary,
            interview_chat=interview_chat
        )
        
        # Call OpenAI API for scores extraction
        openai_api_key = os.getenv('OPENAI_API_KEY')
        if not openai_api_key:
            return jsonify({
                'error': 'Configuration error',
                'message': 'OpenAI API key not configured'
            }), 500
        
        logger.info(f"[API] Extracting scores via OpenAI for {interview_id}")
        
        client = OpenAI(api_key=openai_api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": FEEDBACKSCORES.system},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,  # Lower temperature for consistent structure
            max_tokens=800
        )
        
        scores_text = response.choices[0].message.content
        
        # Parse JSON response
        try:
            # Clean up response (remove markdown code blocks if present)
            cleaned = scores_text.strip()
            if cleaned.startswith('```'):
                # Remove ```json and closing ```
                lines = cleaned.split('\n')
                cleaned = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])
            
            scores_data = json_module.loads(cleaned)
        except json_module.JSONDecodeError as e:
            logger.error(f"[API] Failed to parse scores JSON: {e}")
            logger.error(f"[API] Raw response: {scores_text}")
            # Return a fallback structure
            scores_data = {
                'overall_score': 3.0,
                'summary_headline': 'Analysis complete',
                'competencies': [
                    {'name': 'Technical Skills', 'score': 3, 'max_score': 5, 'quick_take': 'Demonstrated relevant experience'},
                    {'name': 'Communication', 'score': 3, 'max_score': 5, 'quick_take': 'Room for clearer responses'},
                    {'name': 'Problem-Solving', 'score': 3, 'max_score': 5, 'quick_take': 'Showed analytical thinking'}
                ],
                'top_strength': 'Relevant project experience',
                'top_improvement': 'Structure answers more clearly',
                'filler_word_count': 0,
                'answer_structure_score': 3
            }
        
        logger.info(f"[API] Scores extracted successfully for {interview_id}")
        
        return jsonify({
            'success': True,
            'interview_id': interview_id,
            'scores': scores_data,
            'meta': {
                'candidate': meta.get('candidate'),
                'interview_date': meta.get('interview_date'),
                'total_turns': len(conversation),
                'model': 'gpt-4o-mini'
            }
        })
        
    except Exception as e:
        logger.error(f"[API] Scores extraction error: {e}", exc_info=True)
        return jsonify({
            'error': 'Scores extraction failed',
            'message': str(e)
        }), 500


@app.route('/api/feedback', methods=['POST'])
def generate_feedback():
    """
    Stage 2: Generate detailed AI-powered feedback using chain-of-thought analysis.
    
    Call this after /api/feedback/scores to get full descriptive feedback.
    
    Expected JSON body:
        - interview_id: Interview filename or identifier
        - scores: (optional) Pre-computed scores to include in response
        
    Returns:
        Structured feedback with strengths, improvements, and practice plan.
    """
    import json as json_module
    from openai import OpenAI
    from prompts import build_post_interview_feedback_prompt
    
    try:
        data = request.json or {}
        interview_id = data.get('interview_id')
        provided_scores = data.get('scores')  # Optional: pass scores from stage 1
        
        if not interview_id:
            return jsonify({
                'error': 'Missing interview_id',
                'message': 'Please provide an interview_id'
            }), 400
            
        logger.info(f"[API] Feedback requested for: {interview_id}")
        
        # Load interview context
        interview_chat, candidate_profile, job_summary, meta, conversation, error = _load_interview_context(interview_id)
        
        if error:
            return jsonify({'error': 'Interview not found', 'message': error}), 404
        
        # Build the feedback prompt using chain-of-thought approach
        system_prompt = build_post_interview_feedback_prompt()
        
        user_prompt = f"""Please analyze this mock interview and provide detailed feedback.

<CANDIDATE_PROFILE>
{candidate_profile}
</CANDIDATE_PROFILE>

<JOB_SUMMARY>
{job_summary}
</JOB_SUMMARY>

<INTERVIEW_CHAT>
{interview_chat}
</INTERVIEW_CHAT>

Provide your analysis and feedback following the output format specified."""

        # Call OpenAI API for feedback generation
        openai_api_key = os.getenv('OPENAI_API_KEY')
        if not openai_api_key:
            return jsonify({
                'error': 'Configuration error',
                'message': 'OpenAI API key not configured'
            }), 500
        
        logger.info(f"[API] Generating feedback via OpenAI for {interview_id}")
        
        client = OpenAI(api_key=openai_api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=3000  # Increased for comprehensive feedback
        )
        
        feedback_text = response.choices[0].message.content
        
        # Cache the feedback for future retrieval
        import time as time_module
        _feedback_cache[interview_id] = {
            'feedback': feedback_text,
            'cached_at': time_module.time(),
            'model': 'gpt-4o-mini'
        }
        
        logger.info(f"[API] Feedback generated and cached for {interview_id}")
        
        response_data = {
            'success': True,
            'interview_id': interview_id,
            'feedback': feedback_text,
            'meta': {
                'candidate': meta.get('candidate'),
                'interview_date': meta.get('interview_date'),
                'total_turns': len(conversation),
                'model': 'gpt-4o-mini'
            }
        }
        
        # Include scores if provided
        if provided_scores:
            response_data['scores'] = provided_scores
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"[API] Feedback error: {e}", exc_info=True)
        return jsonify({
            'error': 'Feedback generation failed',
            'message': str(e)
        }), 500


# ==================== SKIP STAGE API ====================

@app.route('/api/skip-stage', methods=['POST'])
def skip_stage():
    """
    Request to skip to a specific interview stage.
    
    Expected JSON body:
        - room_name: The LiveKit room name
        - target_stage: Stage to skip to (self_intro, past_experience, company_fit, closing)
        
    Note: This endpoint queues the skip request. The actual transition
    is handled by the agent via data channel messages.
    
    Returns:
        - success: Whether skip was queued
        - target_stage: Confirmed target stage
    """
    try:
        data = request.json or {}
        room_name = data.get('room_name')
        target_stage = data.get('target_stage')
        
        if not room_name:
            return jsonify({
                'error': 'Missing room_name',
                'message': 'Please provide the room name'
            }), 400
            
        if not target_stage:
            return jsonify({
                'error': 'Missing target_stage',
                'message': 'Please specify which stage to skip to'
            }), 400
            
        # Validate target stage
        valid_stages = ['self_intro', 'past_experience', 'company_fit', 'closing']
        if target_stage not in valid_stages:
            return jsonify({
                'error': 'Invalid target_stage',
                'message': f'Valid stages: {", ".join(valid_stages)}'
            }), 400
            
        logger.info(f"[API] Skip stage request: {room_name} -> {target_stage}")
        
        # The actual skip is communicated via LiveKit data channel
        # This endpoint just validates and logs the request
        # The frontend will send the skip message directly to the room
        
        return jsonify({
            'success': True,
            'room_name': room_name,
            'target_stage': target_stage,
            'message': f'Skip to {target_stage} queued. The agent will transition shortly.'
        })
        
    except Exception as e:
        logger.error(f"[API] Skip stage error: {e}", exc_info=True)
        return jsonify({
            'error': 'Skip request failed',
            'message': str(e)
        }), 500


# ==================== HEALTH CHECK ====================

@app.route('/api/health')
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({
        'status': 'healthy',
        'service': 'MockFlow-AI',
        'livekit_configured': bool(LIVEKIT_URL and LIVEKIT_API_KEY),
        'document_cache_stats': doc_processor.get_cache_stats(),
        'conversation_cache_stats': conversation_cache.get_cache_stats()
    })


# ==================== ERROR HANDLERS ====================

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

    # Ensure interviews directory exists
    os.makedirs("interviews", exist_ok=True)

    # Run Flask app
    app.run(
        debug=True,
        port=5000,
        host='0.0.0.0'
    )