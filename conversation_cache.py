"""
Conversation Cache Module

Caches interview conversation history in-memory for quick retrieval.
Similar pattern to document_processor.py for consistency.
"""

import hashlib
import logging
import time
from typing import Optional, Dict, List, Union
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ConversationMetadata:
    """Metadata for cached conversations."""
    candidate_name: str
    interview_date: str
    room_name: str
    job_role: str = ""
    experience_level: str = ""
    final_stage: str = ""
    ended_by: str = "unknown"
    skipped_stages: List[str] = None
    has_resume: bool = False
    has_jd: bool = False
    
    def __post_init__(self):
        if self.skipped_stages is None:
            self.skipped_stages = []
    
    def to_dict(self) -> dict:
        return asdict(self)


class ConversationCache:
    """
    Handles conversation history caching for interviews.
    
    Privacy-first: Stores only conversation data, not audio/video.
    Uses MD5 hash of room_name + timestamp as cache key.
    """

    def __init__(self):
        """Initialize conversation cache with in-memory storage."""
        self.cache: Dict[str, dict] = {}
        logger.info("[CONV_CACHE] Conversation cache initialized")

    def generate_cache_key(self, room_name: str, timestamp: float = None) -> str:
        """
        Generate a unique cache key for a conversation.
        
        Args:
            room_name: LiveKit room name
            timestamp: Optional timestamp (defaults to current time)
            
        Returns:
            Cache key (MD5 hash)
        """
        if timestamp is None:
            timestamp = time.time()
        
        key_string = f"{room_name}_{timestamp}"
        return hashlib.md5(key_string.encode()).hexdigest()[:16]

    def cache_conversation(
        self,
        conversation: dict,
        metadata: ConversationMetadata,
        cache_key: str = None
    ) -> str:
        """
        Cache a conversation with metadata.
        
        Args:
            conversation: Dict with 'agent' and 'user' message lists
            metadata: Conversation metadata
            cache_key: Optional pre-generated cache key
            
        Returns:
            Cache key for retrieval
        """
        try:
            if cache_key is None:
                cache_key = self.generate_cache_key(metadata.room_name)
            
            # Calculate message counts
            agent_msgs = conversation.get('agent', [])
            user_msgs = conversation.get('user', [])
            
            # Store in cache
            self.cache[cache_key] = {
                'conversation': conversation,
                'metadata': metadata.to_dict() if isinstance(metadata, ConversationMetadata) else metadata,
                'total_messages': {
                    'agent': len(agent_msgs),
                    'user': len(user_msgs)
                },
                'cached_at': time.time(),
                'cache_key': cache_key
            }
            
            logger.info(
                f"[CONV_CACHE] Cached conversation: {cache_key} "
                f"(candidate: {metadata.candidate_name}, "
                f"messages: {len(agent_msgs)} agent, {len(user_msgs)} user)"
            )
            
            return cache_key
            
        except Exception as e:
            logger.error(f"[CONV_CACHE] Cache error: {e}", exc_info=True)
            return ""

    def get_conversation(self, cache_key: str) -> Optional[dict]:
        """
        Retrieve a cached conversation by key.
        
        Args:
            cache_key: The cache key from cache_conversation
            
        Returns:
            Cached conversation dict or None
        """
        return self.cache.get(cache_key)

    def get_conversation_data(self, cache_key: str) -> Optional[dict]:
        """
        Retrieve just the conversation messages from cache.
        
        Args:
            cache_key: The cache key
            
        Returns:
            Conversation dict with 'agent' and 'user' keys, or None
        """
        cached = self.cache.get(cache_key)
        if cached:
            return cached.get('conversation')
        return None

    def get_metadata(self, cache_key: str) -> Optional[dict]:
        """
        Retrieve metadata for a cached conversation.
        
        Args:
            cache_key: The cache key
            
        Returns:
            Metadata dict or None
        """
        cached = self.cache.get(cache_key)
        if cached:
            return cached.get('metadata')
        return None

    def list_conversations(self) -> List[dict]:
        """
        List all cached conversations with metadata.
        
        Returns:
            List of conversation summaries sorted by date (newest first)
        """
        conversations = []
        
        for cache_key, data in self.cache.items():
            metadata = data.get('metadata', {})
            total_msgs = data.get('total_messages', {})
            
            # Get stages covered from agent messages
            agent_msgs = data.get('conversation', {}).get('agent', [])
            stages_covered = list(set(
                m.get('stage') for m in agent_msgs if m.get('stage')
            ))
            
            conversations.append({
                'cache_key': cache_key,
                'filename': cache_key,  # For compatibility with existing UI
                'candidate': metadata.get('candidate_name', 'Unknown'),
                'interview_date': metadata.get('interview_date'),
                'room_name': metadata.get('room_name'),
                'job_role': metadata.get('job_role', ''),
                'experience_level': metadata.get('experience_level', ''),
                'final_stage': metadata.get('final_stage', ''),
                'ended_by': metadata.get('ended_by', 'unknown'),
                'stages_covered': stages_covered,
                'message_count': total_msgs,
                'has_resume': metadata.get('has_resume', False),
                'has_jd': metadata.get('has_jd', False),
                'cached_at': data.get('cached_at', 0)
            })
        
        # Sort by interview date (newest first)
        conversations.sort(
            key=lambda x: x.get('interview_date', '') or '',
            reverse=True
        )
        
        return conversations

    def update_conversation(
        self,
        cache_key: str,
        conversation: dict = None,
        metadata: dict = None
    ) -> bool:
        """
        Update an existing cached conversation.
        
        Args:
            cache_key: The cache key
            conversation: New conversation data (optional)
            metadata: New metadata (optional)
            
        Returns:
            True if updated, False if not found
        """
        if cache_key not in self.cache:
            return False
        
        if conversation is not None:
            self.cache[cache_key]['conversation'] = conversation
            agent_msgs = conversation.get('agent', [])
            user_msgs = conversation.get('user', [])
            self.cache[cache_key]['total_messages'] = {
                'agent': len(agent_msgs),
                'user': len(user_msgs)
            }
        
        if metadata is not None:
            self.cache[cache_key]['metadata'].update(metadata)
        
        logger.info(f"[CONV_CACHE] Updated conversation: {cache_key}")
        return True

    def remove_conversation(self, cache_key: str) -> bool:
        """
        Remove a conversation from cache.
        
        Args:
            cache_key: The cache key
            
        Returns:
            True if removed, False if not found
        """
        if cache_key in self.cache:
            del self.cache[cache_key]
            logger.info(f"[CONV_CACHE] Removed conversation: {cache_key}")
            return True
        return False

    def get_cache_stats(self) -> dict:
        """Get statistics about cached conversations."""
        total_convos = len(self.cache)
        total_messages = sum(
            data.get('total_messages', {}).get('agent', 0) +
            data.get('total_messages', {}).get('user', 0)
            for data in self.cache.values()
        )
        
        by_level = {}
        for data in self.cache.values():
            level = data.get('metadata', {}).get('experience_level', 'unknown')
            by_level[level] = by_level.get(level, 0) + 1
        
        return {
            'total_conversations': total_convos,
            'total_messages': total_messages,
            'by_experience_level': by_level,
            'cache_keys': list(self.cache.keys())
        }

    def clear_cache(self):
        """Clear all cached conversations."""
        count = len(self.cache)
        self.cache.clear()
        logger.info(f"[CONV_CACHE] Cache cleared ({count} conversations removed)")

    def export_to_dict(self, cache_key: str) -> Optional[dict]:
        """
        Export a conversation in the format expected by postprocess.py
        
        Args:
            cache_key: The cache key
            
        Returns:
            Dict in the same format as saved JSON files
        """
        cached = self.cache.get(cache_key)
        if not cached:
            return None
        
        metadata = cached.get('metadata', {})
        
        return {
            'candidate': metadata.get('candidate_name', 'Unknown'),
            'interview_date': metadata.get('interview_date'),
            'room_name': metadata.get('room_name'),
            'job_role': metadata.get('job_role', ''),
            'experience_level': metadata.get('experience_level', ''),
            'conversation': cached.get('conversation', {}),
            'total_messages': cached.get('total_messages', {}),
            'skipped_stages': metadata.get('skipped_stages', []),
            'final_stage': metadata.get('final_stage', ''),
            'ended_by': metadata.get('ended_by', 'unknown')
        }


# Global instance for easy access
conversation_cache = ConversationCache()