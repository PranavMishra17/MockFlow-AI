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
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
from flask_cors import CORS
from livekit import api
from dotenv import load_dotenv

from document_processor import doc_processor, DocumentMetadata
from postprocess import resequence_interview, list_interviews, get_interview_summary

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


# ==================== INTERVIEW HISTORY API ====================

@app.route('/api/interviews')
def get_interviews():
    """
    List all saved interview files.
    
    Returns list of interview metadata.
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
        filename: Interview JSON filename
        
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


# ==================== FEEDBACK API (SKELETON) ====================

@app.route('/api/feedback', methods=['POST'])
def generate_feedback():
    """
    Generate feedback for an interview (SKELETON - future implementation).
    
    Expected JSON body:
        - interview_id: Interview filename or identifier
        
    Returns:
        Queued status with placeholder for future LLM-driven feedback.
        
    TODO: Implement LLM-driven feedback analysis with:
        - strengths: List of candidate strengths
        - improvements: List of areas for improvement
        - question_feedback: Per-question analysis
        - overall_score: Numerical rating
        - recommendations: Next steps
    """
    try:
        data = request.json or {}
        interview_id = data.get('interview_id')
        
        if not interview_id:
            return jsonify({
                'error': 'Missing interview_id',
                'message': 'Please provide an interview_id'
            }), 400
            
        logger.info(f"[API] Feedback requested for: {interview_id}")
        
        # Verify interview exists
        summary = get_interview_summary(interview_id)
        if 'error' in summary:
            return jsonify({
                'error': 'Interview not found',
                'message': f'Could not find interview: {interview_id}'
            }), 404
        
        # TODO: Implement actual feedback generation
        # Future implementation will:
        # 1. Load the interview transcript
        # 2. Send to LLM with structured prompt
        # 3. Parse and return feedback in structured format
        
        # Skeleton response
        return jsonify({
            'interview_id': interview_id,
            'status': 'queued',
            'message': 'Feedback generation will be implemented in a future release.',
            
            # Placeholder structure for future implementation
            'feedback_schema': {
                'strengths': ['(Coming soon) List of identified strengths'],
                'improvements': ['(Coming soon) Areas for improvement with actionable tips'],
                'question_feedback': [
                    {
                        'question': '(Coming soon) Specific question asked',
                        'response_quality': '(Coming soon) Assessment of response',
                        'suggestions': '(Coming soon) How to improve'
                    }
                ],
                'overall_score': None,
                'recommendations': ['(Coming soon) Next steps for interview prep']
            },
            
            # Interview summary for reference
            'interview_summary': summary
        })
        
    except Exception as e:
        logger.error(f"[API] Feedback error: {e}", exc_info=True)
        return jsonify({
            'error': 'Feedback request failed',
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
        'cache_stats': doc_processor.get_cache_stats()
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