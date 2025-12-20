import os
from supabase import create_client, Client
from cryptography.fernet import Fernet
from typing import Optional, Dict, Any, List
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class SupabaseClient:
    def __init__(self):
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_KEY')

        if not url or not key:
            raise ValueError("Missing Supabase credentials in environment")

        self.client: Client = create_client(url, key)
        self.encryption_key = os.getenv('ENCRYPTION_KEY', '').encode()
        self.cipher = Fernet(self.encryption_key) if self.encryption_key else None

    def _encrypt(self, text: str) -> str:
        """Encrypt sensitive data"""
        if not self.cipher:
            raise ValueError("Encryption key not configured")
        return self.cipher.encrypt(text.encode()).decode()

    def _decrypt(self, encrypted_text: str) -> str:
        """Decrypt sensitive data"""
        if not self.cipher:
            raise ValueError("Encryption key not configured")
        return self.cipher.decrypt(encrypted_text.encode()).decode()

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        try:
            response = self.client.table('users').select('*').eq('id', user_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching user: {e}")
            return None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email"""
        try:
            response = self.client.table('users').select('*').eq('email', email).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching user by email: {e}")
            return None

    def create_user(self, email: str, name: str, google_id: str, picture_url: str = '') -> Optional[str]:
        """Create new user and return user ID"""
        try:
            response = self.client.table('users').insert({
                'email': email,
                'name': name,
                'google_id': google_id,
                'picture_url': picture_url
            }).execute()
            return response.data[0]['id'] if response.data else None
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return None

    def save_api_keys(self, user_id: str, livekit_url: str, livekit_api_key: str,
                      livekit_api_secret: str, openai_key: str, deepgram_key: str) -> bool:
        """Save or update encrypted API keys for user"""
        try:
            encrypted_livekit_url = self._encrypt(livekit_url)
            encrypted_livekit_key = self._encrypt(livekit_api_key)
            encrypted_livekit_secret = self._encrypt(livekit_api_secret)
            encrypted_openai = self._encrypt(openai_key)
            encrypted_deepgram = self._encrypt(deepgram_key)

            # Check if keys exist
            existing = self.client.table('user_api_keys').select('id').eq('user_id', user_id).execute()

            data = {
                'user_id': user_id,
                'livekit_url_encrypted': encrypted_livekit_url,
                'livekit_key_encrypted': encrypted_livekit_key,
                'livekit_secret_encrypted': encrypted_livekit_secret,
                'openai_key_encrypted': encrypted_openai,
                'deepgram_key_encrypted': encrypted_deepgram,
                'encryption_salt': 'salt_v1'
            }

            if existing.data:
                # Update existing
                self.client.table('user_api_keys').update(data).eq('user_id', user_id).execute()
            else:
                # Insert new
                self.client.table('user_api_keys').insert(data).execute()

            return True
        except Exception as e:
            logger.error(f"Error saving API keys: {e}")
            return False

    def get_api_keys(self, user_id: str) -> Optional[Dict[str, str]]:
        """Get decrypted API keys for user"""
        try:
            response = self.client.table('user_api_keys').select('*').eq('user_id', user_id).execute()

            if not response.data:
                return None

            keys = response.data[0]
            return {
                'livekit_url': self._decrypt(keys['livekit_url_encrypted']),
                'livekit_api_key': self._decrypt(keys['livekit_key_encrypted']),
                'livekit_api_secret': self._decrypt(keys['livekit_secret_encrypted']),
                'openai_key': self._decrypt(keys['openai_key_encrypted']),
                'deepgram_key': self._decrypt(keys['deepgram_key_encrypted'])
            }
        except Exception as e:
            logger.error(f"Error fetching API keys: {e}")
            return None

    def save_interview(self, user_id: str, interview_data: Dict[str, Any]) -> Optional[str]:
        """Save interview to database, returns interview_id"""
        try:
            # Handle both formats: JSON file format and frontend format
            data = {
                'user_id': user_id,
                'candidate_name': interview_data.get('candidate') or interview_data.get('candidateName'),
                'room_name': interview_data.get('room_name') or interview_data.get('roomName'),
                'job_role': interview_data.get('job_role') or interview_data.get('jobRole'),
                'experience_level': interview_data.get('experience_level') or interview_data.get('experienceLevel'),
                'final_stage': interview_data.get('final_stage') or interview_data.get('finalStage'),
                'ended_by': interview_data.get('ended_by') or interview_data.get('endedBy'),
                'skipped_stages': interview_data.get('skipped_stages') or interview_data.get('skippedStages', []),
                'has_resume': interview_data.get('has_resume', False) or interview_data.get('hasResume', False),
                'has_jd': interview_data.get('has_jd', False) or interview_data.get('hasJobDescription', False),
                'conversation': interview_data.get('conversation', {}),
                'total_messages': interview_data.get('total_messages') or interview_data.get('totalMessages', {}),
                'metadata': interview_data.get('metadata', {}),
                'interview_date': interview_data.get('interview_date')
            }

            response = self.client.table('interviews').insert(data).execute()
            return response.data[0]['id'] if response.data else None
        except Exception as e:
            logger.error(f"Error saving interview: {e}")
            return None

    def get_user_interviews(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all interviews for user"""
        try:
            response = self.client.table('interviews').select('*').eq('user_id', user_id).order('interview_date', desc=True).limit(limit).execute()
            return response.data
        except Exception as e:
            logger.error(f"Error fetching interviews: {e}")
            return []

    def get_interview_by_room(self, room_name: str) -> Optional[Dict[str, Any]]:
        """Get interview by room name"""
        try:
            response = self.client.table('interviews').select('*').eq('room_name', room_name).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching interview: {e}")
            return None

    def get_interview_by_room_name(self, user_id: str, room_name: str) -> Optional[Dict[str, Any]]:
        """Get interview by room name for specific user"""
        try:
            response = self.client.table('interviews').select('*').eq('user_id', user_id).eq('room_name', room_name).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching interview by room name: {e}")
            return None

    def save_feedback(self, user_id: str, interview_id: str, feedback_data: Dict[str, Any]) -> bool:
        """Save feedback for interview"""
        try:
            response = self.client.table('feedback').insert({
                'user_id': user_id,
                'interview_id': interview_id,
                'feedback_data': feedback_data
            }).execute()
            return True
        except Exception as e:
            logger.error(f"Error saving feedback: {e}")
            return False

    def get_feedback(self, interview_id: str) -> Optional[Dict[str, Any]]:
        """Get feedback for interview"""
        try:
            response = self.client.table('feedback').select('*').eq('interview_id', interview_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error fetching feedback: {e}")
            return None

supabase_client = SupabaseClient()
