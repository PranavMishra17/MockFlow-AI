"""
Post-Interview Processing Module

Re-sequences interview transcripts by merging partial transcripts and
interleaving agent/candidate turns by timestamp.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Union
from datetime import datetime

logger = logging.getLogger(__name__)

# Default interviews directory
INTERVIEWS_DIR = Path("interviews")


def resequence_interview(path_or_filename: Union[str, Path]) -> Dict:
    """
    Load and resequence an interview transcript.
    
    Merges candidate partial transcripts into full turns by grouping
    adjacent user partials by timestamp gap (<=1.0s).
    Interleaves agent and merged candidate turns by timestamp.
    
    Args:
        path_or_filename: Path to interview JSON file, or just filename
        
    Returns:
        Dict with:
            - ordered_conversation: List of {role, text, timestamp, stage?}
            - meta: Interview metadata
    """
    try:
        # Resolve path
        if isinstance(path_or_filename, str):
            path = Path(path_or_filename)
        else:
            path = path_or_filename
            
        # If just filename, look in interviews directory
        if not path.exists() and not path.is_absolute():
            path = INTERVIEWS_DIR / path
            
        if not path.exists():
            logger.error(f"[POSTPROCESS] Interview file not found: {path}")
            return {
                'error': f'Interview file not found: {path}',
                'ordered_conversation': [],
                'meta': {}
            }
            
        logger.info(f"[POSTPROCESS] Loading interview: {path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Extract conversation data
        conversation = data.get('conversation', {})
        agent_messages = conversation.get('agent', [])
        user_messages = conversation.get('user', [])
        
        # Merge user partials into complete turns
        merged_user = _merge_user_partials(user_messages, gap_threshold=1.0)
        
        # Prepare all turns with role labels
        all_turns = []
        
        for msg in agent_messages:
            all_turns.append({
                'role': 'agent',
                'text': msg.get('text', ''),
                'timestamp': msg.get('timestamp', 0),
                'stage': msg.get('stage'),
            })
            
        for msg in merged_user:
            all_turns.append({
                'role': 'candidate',
                'text': msg.get('text', ''),
                'timestamp': msg.get('timestamp', 0),
                'stage': None,
            })
        
        # Sort by timestamp
        all_turns.sort(key=lambda x: x['timestamp'])
        
        # Build metadata
        meta = {
            'candidate': data.get('candidate', 'Unknown'),
            'interview_date': data.get('interview_date'),
            'room_name': data.get('room_name'),
            'total_agent_messages': len(agent_messages),
            'total_user_messages': len(user_messages),
            'merged_user_turns': len(merged_user),
            'total_turns': len(all_turns),
            'source_file': str(path),
        }
        
        logger.info(
            f"[POSTPROCESS] Resequenced interview: {len(all_turns)} turns "
            f"({len(agent_messages)} agent, {len(merged_user)} candidate)"
        )
        
        return {
            'ordered_conversation': all_turns,
            'meta': meta
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"[POSTPROCESS] Invalid JSON in {path_or_filename}: {e}")
        return {
            'error': f'Invalid JSON: {str(e)}',
            'ordered_conversation': [],
            'meta': {}
        }
    except Exception as e:
        logger.error(f"[POSTPROCESS] Error processing {path_or_filename}: {e}", exc_info=True)
        return {
            'error': str(e),
            'ordered_conversation': [],
            'meta': {}
        }


def _merge_user_partials(
    user_messages: List[Dict],
    gap_threshold: float = 1.0
) -> List[Dict]:
    """
    Merge adjacent user partial transcripts into complete turns.
    
    Groups messages where timestamp gap is <= gap_threshold seconds.
    
    Args:
        user_messages: List of user message dicts with 'text' and 'timestamp'
        gap_threshold: Max seconds between messages to merge
        
    Returns:
        List of merged message dicts
    """
    if not user_messages:
        return []
        
    # Sort by timestamp first
    sorted_msgs = sorted(user_messages, key=lambda x: x.get('timestamp', 0))
    
    merged = []
    current_group = [sorted_msgs[0]]
    
    for msg in sorted_msgs[1:]:
        prev_ts = current_group[-1].get('timestamp', 0)
        curr_ts = msg.get('timestamp', 0)
        
        if curr_ts - prev_ts <= gap_threshold:
            # Same turn - add to group
            current_group.append(msg)
        else:
            # New turn - finalize current group and start new
            merged.append(_finalize_group(current_group))
            current_group = [msg]
    
    # Don't forget the last group
    if current_group:
        merged.append(_finalize_group(current_group))
    
    return merged


def _finalize_group(messages: List[Dict]) -> Dict:
    """Combine a group of messages into one turn."""
    texts = [m.get('text', '') for m in messages if m.get('text')]
    combined_text = ' '.join(texts)
    
    return {
        'text': combined_text,
        'timestamp': messages[0].get('timestamp', 0),
        'partial_count': len(messages),
    }


def list_interviews(directory: Union[str, Path] = None) -> List[Dict]:
    """
    List all saved interview files.
    
    Args:
        directory: Directory to search (defaults to INTERVIEWS_DIR)
        
    Returns:
        List of dicts with filename and basic metadata
    """
    dir_path = Path(directory) if directory else INTERVIEWS_DIR
    
    if not dir_path.exists():
        logger.warning(f"[POSTPROCESS] Interviews directory not found: {dir_path}")
        return []
        
    interviews = []
    
    for file_path in dir_path.glob("*.json"):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            interviews.append({
                'filename': file_path.name,
                'candidate': data.get('candidate', 'Unknown'),
                'interview_date': data.get('interview_date'),
                'room_name': data.get('room_name'),
                'message_count': data.get('total_messages', {}),
                'file_size': file_path.stat().st_size,
            })
        except Exception as e:
            logger.warning(f"[POSTPROCESS] Error reading {file_path}: {e}")
            interviews.append({
                'filename': file_path.name,
                'error': str(e),
            })
    
    # Sort by date descending
    interviews.sort(
        key=lambda x: x.get('interview_date', ''),
        reverse=True
    )
    
    return interviews


def get_interview_summary(path_or_filename: Union[str, Path]) -> Dict:
    """
    Get a summary of an interview without full re-sequencing.
    
    Args:
        path_or_filename: Path to interview JSON file
        
    Returns:
        Summary dict with metadata and stats
    """
    try:
        path = Path(path_or_filename)
        if not path.exists() and not path.is_absolute():
            path = INTERVIEWS_DIR / path
            
        if not path.exists():
            return {'error': f'File not found: {path}'}
            
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        conversation = data.get('conversation', {})
        agent_msgs = conversation.get('agent', [])
        user_msgs = conversation.get('user', [])
        
        # Calculate duration if timestamps available
        all_timestamps = (
            [m.get('timestamp', 0) for m in agent_msgs] +
            [m.get('timestamp', 0) for m in user_msgs]
        )
        
        duration = 0
        if all_timestamps:
            duration = max(all_timestamps) - min(all_timestamps)
            
        # Get stages covered
        stages = list(set(m.get('stage') for m in agent_msgs if m.get('stage')))
        
        return {
            'candidate': data.get('candidate'),
            'interview_date': data.get('interview_date'),
            'room_name': data.get('room_name'),
            'duration_seconds': duration,
            'agent_message_count': len(agent_msgs),
            'user_message_count': len(user_msgs),
            'stages_covered': stages,
            'filename': path.name,
        }
        
    except Exception as e:
        logger.error(f"[POSTPROCESS] Summary error: {e}", exc_info=True)
        return {'error': str(e)}


def format_conversation_text(resequenced: Dict) -> str:
    """
    Format a resequenced conversation as readable text.
    
    Args:
        resequenced: Output from resequence_interview
        
    Returns:
        Formatted text string
    """
    lines = []
    meta = resequenced.get('meta', {})
    
    # Header
    lines.append(f"Interview Transcript: {meta.get('candidate', 'Unknown')}")
    lines.append(f"Date: {meta.get('interview_date', 'Unknown')}")
    lines.append("-" * 60)
    lines.append("")
    
    # Conversation
    current_stage = None
    for turn in resequenced.get('ordered_conversation', []):
        # Stage header if changed
        if turn.get('stage') and turn['stage'] != current_stage:
            current_stage = turn['stage']
            lines.append(f"\n[Stage: {current_stage.upper()}]")
            lines.append("")
        
        role = turn['role'].upper()
        text = turn['text']
        
        lines.append(f"{role}: {text}")
        lines.append("")
    
    return "\n".join(lines)
