import os
from functools import wraps
from flask import session, redirect, url_for, request, jsonify
from supabase import create_client
import logging

logger = logging.getLogger(__name__)

url = os.getenv('SUPABASE_URL')
anon_key = os.getenv('SUPABASE_ANON_KEY')
supabase = create_client(url, anon_key)

def get_current_user():
    """Get current authenticated user from session"""
    try:
        access_token = session.get('access_token')
        if not access_token:
            return None

        user = supabase.auth.get_user(access_token)
        return user
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        return None

def require_auth(f):
    """Decorator to protect routes requiring authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_user_id():
    """Extract user_id from session"""
    user = get_current_user()
    return user.user.id if user else None

def is_authenticated():
    """Check if user is authenticated"""
    return get_current_user() is not None
