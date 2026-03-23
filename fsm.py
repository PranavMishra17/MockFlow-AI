"""
Finite State Machine for Mock Interview Agent

This module defines the interview stages and state management for the voice interview agent.
Implements explicit state transitions with timestamp tracking for fallback mechanisms.

Stage Flow: WELCOME -> SELF_INTRO -> PAST_EXPERIENCE -> COMPANY_FIT -> CLOSING
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Any
import logging

logger = logging.getLogger(__name__)


class InterviewStage(Enum):
    """Interview stages with explicit progression."""
    WELCOME = "welcome"
    SELF_INTRO = "self_intro"
    PAST_EXPERIENCE = "past_experience"
    COMPANY_FIT = "company_fit"
    CLOSING = "closing"


# Stage time limits (seconds) - centralized configuration
STAGE_TIME_LIMITS = {
    InterviewStage.WELCOME: 60,
    InterviewStage.SELF_INTRO: 120,
    InterviewStage.PAST_EXPERIENCE: 240,
    InterviewStage.COMPANY_FIT: 240,
    InterviewStage.CLOSING: 45,
}

# Minimum questions per stage
STAGE_MIN_QUESTIONS = {
    'welcome': 1,
    'self_intro': 2,
    'past_experience': 5,
    'company_fit': 3,
    'closing': 1,
}

# Stage display names for UI
STAGE_DISPLAY_NAMES = {
    InterviewStage.WELCOME: "Welcome",
    InterviewStage.SELF_INTRO: "Introduction",
    InterviewStage.PAST_EXPERIENCE: "Experience",
    InterviewStage.COMPANY_FIT: "Company Fit",
    InterviewStage.CLOSING: "Closing",
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

    # Current stage - defaults to WELCOME
    stage: InterviewStage = InterviewStage.WELCOME

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
    experience_responses: List[str] = field(default_factory=list)
    questions_asked: List[str] = field(default_factory=list)
    questions_per_stage: dict = field(default_factory=dict)

    # Document context for RAG
    uploaded_resume_text: Optional[str] = None
    job_description: Optional[str] = None
    portfolio_text: Optional[str] = None
    include_profile: bool = True

    # Transition tracking
    transition_count: int = 0
    forced_transitions: int = 0
    skipped_stages: List[str] = field(default_factory=list)

    # Pending transition (for graceful hard timer)
    pending_transition: Optional[InterviewStage] = None
    pending_transition_reason: Optional[str] = None

    # Pending acknowledgement (queued when transition happens mid-user-speech)
    pending_acknowledgement: Optional[str] = None
    pending_ack_stage: Optional[str] = None
    transition_acknowledged: bool = False

    # Closing stage tracking
    closing_initiated: bool = False
    closing_message_delivered: bool = False

    # Skip stage queue - stages requested to skip to
    skip_stage_queue: List[InterviewStage] = field(default_factory=list)

    def transition_to(self, new_stage: InterviewStage, forced: bool = False, skipped: bool = False) -> None:
        """
        Explicit state transition with timestamp tracking.

        Args:
            new_stage: The target stage to transition to
            forced: Whether this was a forced transition (timeout)
            skipped: Whether this transition was due to user skip request
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

        if skipped:
            self.skipped_stages.append(old_stage.value)

        logger.info(
            f"[FSM] Stage transition: {old_stage.value} -> {new_stage.value} "
            f"(forced={forced}, skipped={skipped}, total_transitions={self.transition_count})"
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
        Flow: WELCOME -> SELF_INTRO -> PAST_EXPERIENCE -> COMPANY_FIT -> CLOSING

        Returns:
            Next stage, or None if at final stage
        """
        transitions = {
            InterviewStage.WELCOME: InterviewStage.SELF_INTRO,
            InterviewStage.SELF_INTRO: InterviewStage.PAST_EXPERIENCE,
            InterviewStage.PAST_EXPERIENCE: InterviewStage.COMPANY_FIT,
            InterviewStage.COMPANY_FIT: InterviewStage.CLOSING,
            InterviewStage.CLOSING: None
        }
        return transitions.get(self.stage)

    def get_stage_by_name(self, stage_name: str) -> Optional[InterviewStage]:
        """
        Get InterviewStage enum by string name.

        Args:
            stage_name: The stage name as string

        Returns:
            InterviewStage enum or None if not found
        """
        stage_map = {
            'welcome': InterviewStage.WELCOME,
            'self_intro': InterviewStage.SELF_INTRO,
            'past_experience': InterviewStage.PAST_EXPERIENCE,
            'company_fit': InterviewStage.COMPANY_FIT,
            'closing': InterviewStage.CLOSING,
        }
        return stage_map.get(stage_name.lower())

    def can_skip_to(self, target_stage: InterviewStage) -> bool:
        """
        Check if we can skip to a target stage.
        Can only skip forward, not backward.

        Args:
            target_stage: The stage to skip to

        Returns:
            True if skip is allowed
        """
        stage_order = [
            InterviewStage.WELCOME,
            InterviewStage.SELF_INTRO,
            InterviewStage.PAST_EXPERIENCE,
            InterviewStage.COMPANY_FIT,
            InterviewStage.CLOSING,
        ]

        current_index = stage_order.index(self.stage)
        target_index = stage_order.index(target_stage)

        return target_index > current_index

    def queue_skip_to(self, target_stage: InterviewStage) -> bool:
        """
        Queue a skip request to a target stage.

        Args:
            target_stage: The stage to skip to

        Returns:
            True if skip was queued successfully
        """
        if not self.can_skip_to(target_stage):
            logger.warning(f"[FSM] Cannot skip to {target_stage.value} from {self.stage.value}")
            return False

        self.skip_stage_queue.append(target_stage)
        logger.info(f"[FSM] Queued skip to {target_stage.value}")
        return True

    def process_skip_queue(self) -> Optional[InterviewStage]:
        """
        Process the skip queue and return the target stage if any.

        Returns:
            Target stage to skip to, or None
        """
        if not self.skip_stage_queue:
            return None

        target = self.skip_stage_queue.pop(0)
        if self.can_skip_to(target):
            return target

        return None

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

    def get_document_context(self, stage: Optional[InterviewStage] = None) -> str:
        """
        Get formatted document context for agent prompt injection.

        Stage-specific rules:
        - PAST_EXPERIENCE: Resume only
        - COMPANY_FIT: Job description only
        - Other stages: No document context

        Args:
            stage: The interview stage to get context for

        Returns:
            Formatted string with stage-appropriate document highlights
        """
        if not self.include_profile:
            return ""

        context_parts = []

        # Resume context: PAST_EXPERIENCE stage only
        if stage == InterviewStage.PAST_EXPERIENCE and self.uploaded_resume_text:
            resume_snippet = self.uploaded_resume_text[:1500]
            if len(self.uploaded_resume_text) > 1500:
                resume_snippet += "..."
            context_parts.append(
                f"CANDIDATE RESUME HIGHLIGHTS:\n{resume_snippet}\n\n"
                f"INSTRUCTION: Reference specific projects, skills, and experiences "
                f"from the resume when asking follow-up questions. Ask about gaps, "
                f"challenges faced, and technical details mentioned."
            )

        # Job description context: COMPANY_FIT stage only
        if stage == InterviewStage.COMPANY_FIT and self.job_description:
            jd_snippet = self.job_description[:1000]
            if len(self.job_description) > 1000:
                jd_snippet += "..."
            context_parts.append(
                f"JOB DESCRIPTION:\n{jd_snippet}\n\n"
                f"INSTRUCTION: Assess how the candidate's background and interests "
                f"align with this role's requirements. Ask about their understanding "
                f"of the position and why they're interested in this specific role."
            )

        if context_parts:
            return "\n\n".join(context_parts)

        return ""

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
            "skipped_stages": self.skipped_stages,
            "responses_recorded": len(self.experience_responses),
            "pending_transition": self.pending_transition.value if self.pending_transition else None,
            "has_resume": bool(self.uploaded_resume_text),
            "has_job_description": bool(self.job_description),
            "include_profile": self.include_profile,
        }


# ============================================================================
# Multi-Track Interview System - New Stage Enums and State Classes
# ============================================================================


class BehavioralStage(Enum):
    """Behavioral interview stages with STAR-based questioning."""
    GREETING = "greeting"
    SELF_INTRO = "self_intro"
    BEHAVIORAL_Q1 = "behavioral_q1"
    BEHAVIORAL_Q2 = "behavioral_q2"
    BEHAVIORAL_Q3 = "behavioral_q3"
    CLOSING = "closing"


class TechnicalVoiceStage(Enum):
    """Technical voice interview stages with concept-based discussion."""
    GREETING = "greeting"
    SELF_INTRO = "self_intro"
    EXPERIENCE_DISCUSSION = "experience_discussion"
    TECHNICAL_CONCEPTS_1 = "technical_concepts_1"
    TECHNICAL_CONCEPTS_2 = "technical_concepts_2"
    TECHNICAL_CONCEPTS_3 = "technical_concepts_3"
    CLOSING = "closing"


class CodingStage(Enum):
    """Coding interview stages with problem-solving focus."""
    GREETING = "greeting"
    SELF_INTRO = "self_intro"
    WARM_UP = "warm_up"
    CODING_PROBLEM_1 = "coding_problem_1"
    CODING_PROBLEM_2 = "coding_problem_2"
    CLOSING = "closing"


# Behavioral interview stage configurations
BEHAVIORAL_STAGE_TIME_LIMITS = {
    BehavioralStage.GREETING: 30,
    BehavioralStage.SELF_INTRO: 120,
    BehavioralStage.BEHAVIORAL_Q1: 300,
    BehavioralStage.BEHAVIORAL_Q2: 300,
    BehavioralStage.BEHAVIORAL_Q3: 300,
    BehavioralStage.CLOSING: 45,
}

BEHAVIORAL_STAGE_MIN_QUESTIONS = {
    'greeting': 0,
    'self_intro': 1,
    'behavioral_q1': 2,
    'behavioral_q2': 2,
    'behavioral_q3': 2,
    'closing': 0,
}

# Technical voice interview stage configurations
TECHNICAL_VOICE_STAGE_TIME_LIMITS = {
    TechnicalVoiceStage.GREETING: 30,
    TechnicalVoiceStage.SELF_INTRO: 120,
    TechnicalVoiceStage.EXPERIENCE_DISCUSSION: 180,
    TechnicalVoiceStage.TECHNICAL_CONCEPTS_1: 240,
    TechnicalVoiceStage.TECHNICAL_CONCEPTS_2: 240,
    TechnicalVoiceStage.TECHNICAL_CONCEPTS_3: 240,
    TechnicalVoiceStage.CLOSING: 45,
}

TECHNICAL_VOICE_STAGE_MIN_QUESTIONS = {
    'greeting': 0,
    'self_intro': 1,
    'experience_discussion': 2,
    'technical_concepts_1': 2,
    'technical_concepts_2': 2,
    'technical_concepts_3': 2,
    'closing': 0,
}


@dataclass
class BehavioralInterviewState(InterviewState):
    """
    State management for behavioral interviews with STAR framework.

    Supports dynamic question count (2 or 3 behavioral questions) and
    multiple competency frameworks (Amazon, Google, Meta, Generic).
    """

    # Override stage with behavioral default
    stage: Any = field(default=BehavioralStage.GREETING)

    # Track type identifier
    track_type: str = "behavioral"

    # Framework selection
    framework: str = "amazon"  # amazon|google|meta|generic

    # Depth setting for follow-up questions
    depth_setting: str = "medium"  # light|medium|deep

    # Custom questions provided by user
    custom_questions: List[str] = field(default_factory=list)

    # LLM-generated questions with metadata
    generated_questions: List[dict] = field(default_factory=list)

    # Active question count (determines stage sequence)
    active_question_count: int = 2

    # Current question index
    current_question_index: int = 0

    # Per-question STAR assessments
    question_assessments: List[dict] = field(default_factory=list)

    # Override pending transition to allow any stage type
    pending_transition: Optional[Any] = None

    # Override skip queue to allow any stage type
    skip_stage_queue: List = field(default_factory=list)

    def get_active_stages(self) -> List[BehavioralStage]:
        """
        Get the active stage sequence based on question count.

        Returns:
            List of active BehavioralStage enums in order
        """
        base_stages = [
            BehavioralStage.GREETING,
            BehavioralStage.SELF_INTRO,
            BehavioralStage.BEHAVIORAL_Q1,
            BehavioralStage.BEHAVIORAL_Q2,
        ]

        if self.active_question_count >= 3:
            base_stages.append(BehavioralStage.BEHAVIORAL_Q3)

        base_stages.append(BehavioralStage.CLOSING)

        logger.debug(f"[FSM] Behavioral active stages: {[s.value for s in base_stages]}")
        return base_stages

    def get_next_behavioral_stage(self) -> Optional[BehavioralStage]:
        """
        Get the next stage in behavioral interview flow.

        Returns:
            Next BehavioralStage, or None if at CLOSING
        """
        active_stages = self.get_active_stages()

        try:
            current_index = active_stages.index(self.stage)
            if current_index < len(active_stages) - 1:
                next_stage = active_stages[current_index + 1]
                logger.debug(f"[FSM] Next behavioral stage: {self.stage.value} -> {next_stage.value}")
                return next_stage
        except (ValueError, AttributeError):
            logger.warning(f"[FSM] Current stage {self.stage} not in active stages")

        return None

    def get_stage_time_limit(self) -> float:
        """Get the time limit for current stage in seconds."""
        if isinstance(self.stage, BehavioralStage):
            limit = BEHAVIORAL_STAGE_TIME_LIMITS.get(self.stage, 300)
            logger.debug(f"[FSM] Behavioral stage {self.stage.value} time limit: {limit}s")
            return limit
        return super().get_stage_time_limit()

    def get_question_status(self) -> dict:
        """
        Get question count status for current stage.

        Returns:
            Dict with asked, minimum, met_minimum, remaining_to_min
        """
        if isinstance(self.stage, BehavioralStage):
            stage_key = self.stage.value
            asked = self.questions_per_stage.get(stage_key, 0)
            minimum = BEHAVIORAL_STAGE_MIN_QUESTIONS.get(stage_key, 0)

            return {
                'asked': asked,
                'minimum': minimum,
                'met_minimum': asked >= minimum,
                'remaining_to_min': max(0, minimum - asked)
            }
        return super().get_question_status()

    def get_document_context(self, stage: Optional[Any] = None) -> str:
        """
        Get formatted document context for agent prompt injection.

        Behavioral stages: Inject resume and JD for all question stages.

        Args:
            stage: The interview stage to get context for

        Returns:
            Formatted string with stage-appropriate document highlights
        """
        if not self.include_profile:
            return ""

        context_parts = []

        # Check if this is a behavioral question stage
        is_question_stage = False
        if isinstance(stage, BehavioralStage):
            is_question_stage = stage in [
                BehavioralStage.BEHAVIORAL_Q1,
                BehavioralStage.BEHAVIORAL_Q2,
                BehavioralStage.BEHAVIORAL_Q3
            ]

        if is_question_stage:
            # Resume context for behavioral questions
            if self.uploaded_resume_text:
                resume_snippet = self.uploaded_resume_text[:1500]
                if len(self.uploaded_resume_text) > 1500:
                    resume_snippet += "..."
                context_parts.append(
                    f"CANDIDATE RESUME HIGHLIGHTS:\n{resume_snippet}\n\n"
                    f"INSTRUCTION: Use the resume to identify relevant experiences "
                    f"for behavioral questions. Reference specific projects and roles."
                )

            # Job description context for behavioral questions
            if self.job_description:
                jd_snippet = self.job_description[:1000]
                if len(self.job_description) > 1000:
                    jd_snippet += "..."
                context_parts.append(
                    f"JOB DESCRIPTION:\n{jd_snippet}\n\n"
                    f"INSTRUCTION: Align behavioral questions with role requirements "
                    f"and competencies needed for this position."
                )

        if context_parts:
            return "\n\n".join(context_parts)

        return ""


@dataclass
class TechnicalVoiceInterviewState(InterviewState):
    """
    State management for technical voice interviews.

    Supports dynamic topic count (1-3 technical concept stages) and
    custom topic selection.
    """

    # Override stage with technical default
    stage: Any = field(default=TechnicalVoiceStage.GREETING)

    # Track type identifier
    track_type: str = "technical_voice"

    # Selected topics for discussion
    selected_topics: List[str] = field(default_factory=list)

    # Custom topics provided by user
    custom_topics: List[str] = field(default_factory=list)

    # Active topic count (determines stage sequence)
    active_topic_count: int = 1

    # Per-topic assessments
    topic_assessments: List[dict] = field(default_factory=list)

    # Override pending transition to allow any stage type
    pending_transition: Optional[Any] = None

    # Override skip queue to allow any stage type
    skip_stage_queue: List = field(default_factory=list)

    def get_active_stages(self) -> List[TechnicalVoiceStage]:
        """
        Get the active stage sequence based on topic count.

        Returns:
            List of active TechnicalVoiceStage enums in order
        """
        stages = [
            TechnicalVoiceStage.GREETING,
            TechnicalVoiceStage.SELF_INTRO,
            TechnicalVoiceStage.EXPERIENCE_DISCUSSION,
            TechnicalVoiceStage.TECHNICAL_CONCEPTS_1,
        ]

        if self.active_topic_count >= 2:
            stages.append(TechnicalVoiceStage.TECHNICAL_CONCEPTS_2)

        if self.active_topic_count >= 3:
            stages.append(TechnicalVoiceStage.TECHNICAL_CONCEPTS_3)

        stages.append(TechnicalVoiceStage.CLOSING)

        logger.debug(f"[FSM] Technical voice active stages: {[s.value for s in stages]}")
        return stages

    def get_next_technical_voice_stage(self) -> Optional[TechnicalVoiceStage]:
        """
        Get the next stage in technical voice interview flow.

        Returns:
            Next TechnicalVoiceStage, or None if at CLOSING
        """
        active_stages = self.get_active_stages()

        try:
            current_index = active_stages.index(self.stage)
            if current_index < len(active_stages) - 1:
                next_stage = active_stages[current_index + 1]
                logger.debug(f"[FSM] Next technical stage: {self.stage.value} -> {next_stage.value}")
                return next_stage
        except (ValueError, AttributeError):
            logger.warning(f"[FSM] Current stage {self.stage} not in active stages")

        return None

    def get_stage_time_limit(self) -> float:
        """Get the time limit for current stage in seconds."""
        if isinstance(self.stage, TechnicalVoiceStage):
            limit = TECHNICAL_VOICE_STAGE_TIME_LIMITS.get(self.stage, 240)
            logger.debug(f"[FSM] Technical stage {self.stage.value} time limit: {limit}s")
            return limit
        return super().get_stage_time_limit()

    def get_question_status(self) -> dict:
        """
        Get question count status for current stage.

        Returns:
            Dict with asked, minimum, met_minimum, remaining_to_min
        """
        if isinstance(self.stage, TechnicalVoiceStage):
            stage_key = self.stage.value
            asked = self.questions_per_stage.get(stage_key, 0)
            minimum = TECHNICAL_VOICE_STAGE_MIN_QUESTIONS.get(stage_key, 0)

            return {
                'asked': asked,
                'minimum': minimum,
                'met_minimum': asked >= minimum,
                'remaining_to_min': max(0, minimum - asked)
            }
        return super().get_question_status()

    def get_document_context(self, stage: Optional[Any] = None) -> str:
        """
        Get formatted document context for agent prompt injection.

        Technical stages: Inject resume and JD for experience and concept stages.

        Args:
            stage: The interview stage to get context for

        Returns:
            Formatted string with stage-appropriate document highlights
        """
        if not self.include_profile:
            return ""

        context_parts = []

        # Check if this is a technical discussion stage
        is_technical_stage = False
        if isinstance(stage, TechnicalVoiceStage):
            is_technical_stage = stage in [
                TechnicalVoiceStage.EXPERIENCE_DISCUSSION,
                TechnicalVoiceStage.TECHNICAL_CONCEPTS_1,
                TechnicalVoiceStage.TECHNICAL_CONCEPTS_2,
                TechnicalVoiceStage.TECHNICAL_CONCEPTS_3
            ]

        if is_technical_stage:
            # Resume context for technical stages
            if self.uploaded_resume_text:
                resume_snippet = self.uploaded_resume_text[:1500]
                if len(self.uploaded_resume_text) > 1500:
                    resume_snippet += "..."
                context_parts.append(
                    f"CANDIDATE RESUME HIGHLIGHTS:\n{resume_snippet}\n\n"
                    f"INSTRUCTION: Reference technical skills, projects, and experience "
                    f"from the resume when discussing concepts and asking follow-ups."
                )

            # Job description context for technical stages
            if self.job_description:
                jd_snippet = self.job_description[:1000]
                if len(self.job_description) > 1000:
                    jd_snippet += "..."
                context_parts.append(
                    f"JOB DESCRIPTION:\n{jd_snippet}\n\n"
                    f"INSTRUCTION: Align technical discussions with role requirements "
                    f"and technologies mentioned in the job description."
                )

        if context_parts:
            return "\n\n".join(context_parts)

        return ""


# ============================================================================
# Coding Track - Stage Configuration
# ============================================================================

CODING_STAGE_TIME_LIMITS = {
    CodingStage.GREETING: 30,
    CodingStage.SELF_INTRO: 120,
    CodingStage.WARM_UP: 300,
    CodingStage.CODING_PROBLEM_1: 900,
    CodingStage.CODING_PROBLEM_2: 900,
    CodingStage.CLOSING: 45,
}

CODING_STAGE_MIN_QUESTIONS = {
    'greeting': 0,
    'self_intro': 1,
    'warm_up': 2,
    'coding_problem_1': 0,
    'coding_problem_2': 0,
    'closing': 0,
}


@dataclass
class CodingInterviewState(InterviewState):
    """
    State management for coding interviews with Monaco editor integration.

    Supports dynamic problem count (1 or 2 problems) and tracks code
    submissions per problem with retry limits.
    """

    # Override stage with coding default
    stage: Any = field(default=CodingStage.GREETING)

    # Track type identifier
    track_type: str = "coding"

    # Candidate's preferred language (set from form, confirmed during self-intro)
    preferred_language: str = "python"  # python|javascript|java|cpp|go

    # Number of coding problems to present (1 or 2)
    active_problem_count: int = 2

    # LLM-generated problems: [{title, description, examples, constraints, difficulty, time_limit_minutes, hints}]
    generated_problems: List[dict] = field(default_factory=list)

    # Which problem we're currently on (0-based index)
    current_problem_index: int = 0

    # All code submissions: [{problem_index, attempt, code, language, evaluation, timestamp}]
    submissions: List[dict] = field(default_factory=list)

    # Submission count per problem: {problem_index_str: attempt_count}
    submissions_per_problem: dict = field(default_factory=dict)

    # When each problem was started: {problem_index_str: ISO timestamp string}
    problem_start_times: dict = field(default_factory=dict)

    # True when agent should stay silent (user is actively coding)
    coding_stage_active: bool = False

    # Track skipped problems
    skipped_problems: List[int] = field(default_factory=list)

    def get_active_stages(self) -> list:
        """
        Return the active stage sequence based on active_problem_count.

        Returns:
            List of CodingStage members in order
        """
        base = [CodingStage.GREETING, CodingStage.SELF_INTRO, CodingStage.WARM_UP]
        problems = [CodingStage.CODING_PROBLEM_1]
        if self.active_problem_count >= 2:
            problems.append(CodingStage.CODING_PROBLEM_2)
        return base + problems + [CodingStage.CLOSING]

    def get_next_coding_stage(self) -> Optional[CodingStage]:
        """
        Get next stage in the coding interview flow, skipping inactive problem stages.

        Returns:
            Next CodingStage or None if at CLOSING
        """
        active = self.get_active_stages()
        if self.stage not in active:
            logger.warning(f"[FSM] Current coding stage {self.stage} not in active stages")
            return None

        current_idx = active.index(self.stage)
        if current_idx + 1 < len(active):
            return active[current_idx + 1]
        return None

    def get_attempts_for_problem(self, problem_index: int) -> int:
        """
        Return how many submissions have been made for a given problem.

        Args:
            problem_index: 0-based problem index

        Returns:
            Number of submissions attempted
        """
        return self.submissions_per_problem.get(str(problem_index), 0)

    def record_submission(self, problem_index: int, code: str, language: str, evaluation: dict) -> int:
        """
        Record a code submission for a problem.

        Args:
            problem_index: 0-based problem index
            code: Submitted code string
            language: Programming language used
            evaluation: Evaluation result dict from code evaluator

        Returns:
            Attempt number (1-based)
        """
        from datetime import datetime
        key = str(problem_index)
        attempt = self.submissions_per_problem.get(key, 0) + 1
        self.submissions_per_problem[key] = attempt

        self.submissions.append({
            'problem_index': problem_index,
            'attempt': attempt,
            'code': code,
            'language': language,
            'evaluation': evaluation,
            'timestamp': datetime.now().isoformat(),
        })
        logger.info(f"[FSM] Recorded submission for problem {problem_index}, attempt {attempt}")
        return attempt

    def get_stage_time_limit(self) -> float:
        """Override to use coding-specific time limits."""
        if isinstance(self.stage, CodingStage):
            return CODING_STAGE_TIME_LIMITS.get(self.stage, 600)
        return super().get_stage_time_limit()

    def get_question_status(self) -> dict:
        """Override to use coding-specific min questions."""
        stage_key = self.stage.value if hasattr(self.stage, 'value') else str(self.stage)
        asked = self.questions_per_stage.get(stage_key, 0)
        minimum = CODING_STAGE_MIN_QUESTIONS.get(stage_key, 0)
        return {
            'asked': asked,
            'minimum': minimum,
            'met_minimum': asked >= minimum,
            'remaining_to_min': max(0, minimum - asked),
        }

    def get_document_context(self, stage: Optional[Any] = None) -> str:
        """
        Inject resume context only for WARM_UP stage.
        No document context during coding problem stages.
        """
        if not self.include_profile:
            return ""

        context_parts = []

        if stage == CodingStage.WARM_UP:
            if self.uploaded_resume_text:
                snippet = self.uploaded_resume_text[:1500]
                if len(self.uploaded_resume_text) > 1500:
                    snippet += "..."
                context_parts.append(
                    f"CANDIDATE RESUME HIGHLIGHTS:\n{snippet}\n\n"
                    f"INSTRUCTION: Reference their programming experience and projects "
                    f"when discussing warm-up topics and confirming language preference."
                )

        if context_parts:
            return "\n\n".join(context_parts)
        return ""