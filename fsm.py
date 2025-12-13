"""
Finite State Machine for Mock Interview Agent

This module defines the interview stages and state management for the voice interview agent.
Implements explicit state transitions with timestamp tracking for fallback mechanisms.
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class InterviewStage(Enum):
    """Interview stages with explicit progression."""
    GREETING = "greeting"
    SELF_INTRO = "self_intro"
    PAST_EXPERIENCE = "past_experience"
    CLOSING = "closing"


# Stage time limits (seconds) - centralized configuration
STAGE_TIME_LIMITS = {
    InterviewStage.GREETING: 60,
    InterviewStage.SELF_INTRO: 120,
    InterviewStage.PAST_EXPERIENCE: 240,
    InterviewStage.CLOSING: 45,
}

# Minimum questions per stage
STAGE_MIN_QUESTIONS = {
    'greeting': 1,
    'self_intro': 2,
    'past_experience': 5,
    'closing': 1,
}


@dataclass
class InterviewState:
    """
    Mutable state tracked across interview stages.

    Design principles:
    - Explicit state transitions (not LLM-driven)
    - Timestamp-based verification every 30s
    - Future-ready for document context (RAG)
    - In-memory state (no database for demo)
    """

    # Current stage
    stage: InterviewStage = InterviewStage.GREETING

    # Candidate information
    candidate_name: str = ""
    candidate_email: str = ""
    job_role: str = ""
    experience_level: str = ""

    # Stage tracking
    stage_started_at: Optional[datetime] = None
    last_state_verification: Optional[datetime] = None

    # Conversation history
    self_intro_summary: str = ""
    experience_responses: list[str] = field(default_factory=list)
    questions_asked: list[str] = field(default_factory=list)
    questions_per_stage: dict[str, int] = field(default_factory=dict)

    # Document context (for future RAG implementation)
    uploaded_resume_text: Optional[str] = None
    job_description: Optional[str] = None

    # Transition tracking
    transition_count: int = 0
    forced_transitions: int = 0

    # Pending transition (for graceful hard timer)
    pending_transition: Optional[InterviewStage] = None
    pending_transition_reason: Optional[str] = None

    # Pending acknowledgement (queued when transition happens mid-user-speech)
    pending_acknowledgement: Optional[str] = None
    pending_ack_stage: Optional[str] = None
    transition_acknowledged: bool = False  # Only True after agent asks question in new stage
    
    # Closing stage tracking
    closing_initiated: bool = False
    closing_message_delivered: bool = False

    # Queued acknowledgement (to be spoken when user stops talking)
    pending_acknowledgement: Optional[str] = None
    pending_ack_stage: Optional[str] = None

    def transition_to(self, new_stage: InterviewStage, forced: bool = False) -> None:
        """
        Explicit state transition with timestamp tracking.

        Args:
            new_stage: The target stage to transition to
            forced: Whether this was a forced transition (timeout)
        """
        old_stage = self.stage
        self.stage = new_stage
        self.stage_started_at = datetime.now()
        self.last_state_verification = datetime.now()
        self.transition_count += 1

        # Clear pending transition
        self.pending_transition = None
        self.pending_transition_reason = None
        
        # Reset acknowledgement tracking for new transition
        self.transition_acknowledged = False
        
        # Reset closing flags (in case transitioning to a new stage)
        if new_stage != InterviewStage.CLOSING:
            self.closing_initiated = False
            self.closing_message_delivered = False

        if forced:
            self.forced_transitions += 1

        logger.info(
            f"[FSM] Stage transition: {old_stage.value} -> {new_stage.value} "
            f"(forced={forced}, total_transitions={self.transition_count})"
        )

    def verify_state(self) -> InterviewStage:
        """
        Update last verification timestamp.
        Called periodically to check if state is progressing.

        Returns:
            Current stage
        """
        self.last_state_verification = datetime.now()
        logger.debug(f"[FSM] State verified: {self.stage.value}")
        return self.stage

    def time_in_current_stage(self) -> float:
        """
        Calculate seconds since current stage started.

        Returns:
            Seconds in current stage, or 0.0 if not started
        """
        if not self.stage_started_at:
            return 0.0
        return (datetime.now() - self.stage_started_at).total_seconds()

    def time_since_verification(self) -> float:
        """
        Calculate seconds since last state verification.
        Used to detect if agent is stuck.

        Returns:
            Seconds since last verification, or 0.0 if never verified
        """
        if not self.last_state_verification:
            return 0.0
        return (datetime.now() - self.last_state_verification).total_seconds()

    def get_next_stage(self) -> Optional[InterviewStage]:
        """
        Get the next stage in the interview flow.

        Returns:
            Next stage, or None if at final stage
        """
        transitions = {
            InterviewStage.GREETING: InterviewStage.SELF_INTRO,
            InterviewStage.SELF_INTRO: InterviewStage.PAST_EXPERIENCE,
            InterviewStage.PAST_EXPERIENCE: InterviewStage.CLOSING,
            InterviewStage.CLOSING: None
        }
        return transitions.get(self.stage)

    def can_transition(self) -> bool:
        """
        Check if transition to next stage is possible.

        Returns:
            True if not at final stage
        """
        return self.get_next_stage() is not None

    def get_stage_time_limit(self) -> float:
        """Get the time limit for current stage in seconds."""
        return STAGE_TIME_LIMITS.get(self.stage, 600)

    def get_time_elapsed_pct(self) -> float:
        """
        Get percentage of time elapsed in current stage.

        Returns:
            Percentage (0-100) of time elapsed
        """
        limit = self.get_stage_time_limit()
        elapsed = self.time_in_current_stage()
        return min(100.0, (elapsed / limit) * 100)

    def get_time_remaining_pct(self) -> float:
        """
        Get percentage of time remaining in current stage.

        Returns:
            Percentage (0-100) of time remaining
        """
        return max(0.0, 100.0 - self.get_time_elapsed_pct())

    def get_time_status(self) -> dict:
        """
        Get comprehensive time status for current stage.

        Returns:
            Dict with elapsed, limit, remaining_pct, elapsed_pct, remaining_seconds
        """
        limit = self.get_stage_time_limit()
        elapsed = self.time_in_current_stage()
        remaining = max(0, limit - elapsed)

        return {
            'elapsed': elapsed,
            'limit': limit,
            'remaining_seconds': remaining,
            'remaining_pct': max(0.0, (remaining / limit) * 100),
            'elapsed_pct': min(100.0, (elapsed / limit) * 100),
            'is_overtime': elapsed > limit
        }

    def get_question_status(self) -> dict:
        """
        Get question count status for current stage.

        Returns:
            Dict with asked, minimum, met_minimum, remaining_to_min
        """
        stage_key = self.stage.value
        asked = self.questions_per_stage.get(stage_key, 0)
        minimum = STAGE_MIN_QUESTIONS.get(stage_key, 0)

        return {
            'asked': asked,
            'minimum': minimum,
            'met_minimum': asked >= minimum,
            'remaining_to_min': max(0, minimum - asked)
        }

    def get_progress_summary(self) -> str:
        """
        Get a formatted progress summary for agent context injection.

        Returns:
            Formatted string with time and question progress
        """
        time_status = self.get_time_status()
        q_status = self.get_question_status()

        time_remaining_pct = time_status['remaining_pct']
        remaining_sec = time_status['remaining_seconds']

        # Determine urgency level
        if time_remaining_pct <= 10:
            urgency = "CRITICAL"
        elif time_remaining_pct <= 25:
            urgency = "HIGH"
        elif time_remaining_pct <= 50:
            urgency = "MODERATE"
        else:
            urgency = "LOW"

        summary = (
            f"[PROGRESS] Stage: {self.stage.value} | "
            f"Questions: {q_status['asked']}/{q_status['minimum']} min | "
            f"Time: {time_remaining_pct:.0f}% remaining ({remaining_sec:.0f}s) | "
            f"Urgency: {urgency}"
        )

        return summary

    def should_transition_soon(self) -> bool:
        """
        Check if agent should consider transitioning soon based on progress.

        Returns:
            True if minimum questions met AND time is past 50%
        """
        q_status = self.get_question_status()
        time_status = self.get_time_status()

        return q_status['met_minimum'] and time_status['elapsed_pct'] >= 50

    def to_dict(self) -> dict:
        """
        Convert state to dictionary for logging/debugging.

        Returns:
            Dictionary representation of state
        """
        time_status = self.get_time_status()
        q_status = self.get_question_status()

        return {
            "stage": self.stage.value,
            "candidate_name": self.candidate_name,
            "job_role": self.job_role,
            "time_in_stage": time_status['elapsed'],
            "time_remaining_pct": time_status['remaining_pct'],
            "questions_asked": q_status['asked'],
            "questions_minimum": q_status['minimum'],
            "transition_count": self.transition_count,
            "forced_transitions": self.forced_transitions,
            "responses_recorded": len(self.experience_responses),
            "pending_transition": self.pending_transition.value if self.pending_transition else None
        }