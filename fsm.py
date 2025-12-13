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
    questions_per_stage: dict[str, int] = field(default_factory=dict)  # Track questions per stage to enforce limits

    # Document context (for future RAG implementation)
    uploaded_resume_text: Optional[str] = None
    job_description: Optional[str] = None

    # Transition tracking
    transition_count: int = 0
    forced_transitions: int = 0

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

    def to_dict(self) -> dict:
        """
        Convert state to dictionary for logging/debugging.

        Returns:
            Dictionary representation of state
        """
        return {
            "stage": self.stage.value,
            "candidate_name": self.candidate_name,
            "job_role": self.job_role,
            "time_in_stage": self.time_in_current_stage(),
            "transition_count": self.transition_count,
            "forced_transitions": self.forced_transitions,
            "questions_asked_count": len(self.questions_asked),
            "responses_recorded": len(self.experience_responses)
        }
