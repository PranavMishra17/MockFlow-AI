"""
What the candidate has demonstrated so far — the ledger Flow interviews from.

The old runtime counted questions per stage. That is how a full STAR story
given in self_intro got no credit, and how a terse candidate got four generic
questions in a row: the count was the only thing the agent could see. This
ledger tracks *coverage* instead, in the vocabulary the verdict grades with
(`evaluator.SIGNAL_LIBRARY` names such as "Ownership", "Impact & metrics",
"Trade-off reasoning"). Room and report speak one language, so "enough
interview" can mean "the signals this stage exists to surface have been
demonstrated", wherever in the conversation that happened.

One `TurnAssessment` is produced per candidate turn (by a small structured
LLM call in production, by a fake in tests) and merged here. Merging is
monotone: a level never drops, evidence only accumulates. The evidence strings
are verbatim fragments of what the candidate said; the closing utterance and
the verdict both quote them.

No fsm import, no I/O: this module is the part of the turn loop that can be
unit-tested exhaustively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

LEVELS = ("absent", "partial", "demonstrated")
_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

STAR_ELEMENTS = ("situation", "task", "action", "result")
ANSWER_STYLES = ("terse", "normal", "rambling")
CANDIDATE_ASKS = ("none", "repeat", "process", "feedback", "company")

MAX_EVIDENCE_PER_SIGNAL = 5


def _level(value: Any) -> str:
    """Coerce anything the model might emit to one of LEVELS ('absent' if unsure)."""
    v = str(value or "").strip().lower()
    if v in _RANK:
        return v
    if v in ("yes", "true", "present", "full", "strong"):
        return "demonstrated"
    if v in ("weak", "some", "partially", "implied"):
        return "partial"
    return "absent"


def _higher(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


@dataclass
class SignalRead:
    """One signal as read from one answer."""

    name: str
    level: str = "absent"
    evidence: str = ""

    def __post_init__(self) -> None:
        self.level = _level(self.level)
        self.evidence = (self.evidence or "").strip()


@dataclass
class TurnAssessment:
    """Everything the turn loop wants to know about the answer just given.

    `stale` marks an assessment that did not arrive in time and was replaced by
    a neutral one; the loop still gets to speak, it just does not learn.
    """

    signals: List[SignalRead] = field(default_factory=list)
    star: Dict[str, str] = field(default_factory=dict)
    answered_question: bool = True
    answer_style: str = "normal"
    candidate_asked: str = "none"
    said_dont_know: bool = False
    words: int = 0
    stale: bool = False

    def __post_init__(self) -> None:
        self.star = {el: _level(self.star.get(el)) for el in STAR_ELEMENTS}
        if self.answer_style not in ANSWER_STYLES:
            self.answer_style = "normal"
        if self.candidate_asked not in CANDIDATE_ASKS:
            self.candidate_asked = "none"
        self.words = max(0, int(self.words or 0))

    @classmethod
    def empty(cls, words: int = 0, *, stale: bool = True) -> "TurnAssessment":
        """The assessment used when none arrived: says nothing about coverage."""
        return cls(signals=[], star={}, answered_question=True, answer_style="normal",
                   candidate_asked="none", said_dont_know=False, words=words, stale=stale)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any], *, words: Optional[int] = None) -> "TurnAssessment":
        """Build from the structured-output JSON. Tolerant: bad fields degrade, never raise."""
        sigs = []
        for raw in d.get("signals") or []:
            if not isinstance(raw, Mapping) or not raw.get("name"):
                continue
            sigs.append(SignalRead(name=str(raw["name"]).strip(), level=raw.get("level"),
                                   evidence=str(raw.get("evidence") or "")))
        star = d.get("star") if isinstance(d.get("star"), Mapping) else {}
        return cls(
            signals=sigs,
            star=dict(star),
            answered_question=bool(d.get("answered_question", True)),
            answer_style=str(d.get("answer_style") or "normal").lower(),
            candidate_asked=str(d.get("candidate_asked") or "none").lower(),
            said_dont_know=bool(d.get("said_dont_know", False)),
            words=int(words if words is not None else d.get("words") or 0),
            stale=False,
        )

    @property
    def all_absent(self) -> bool:
        return not any(s.level != "absent" for s in self.signals)


@dataclass
class CoverageLedger:
    """Running coverage across the whole interview. Monotone by construction."""

    level: Dict[str, str] = field(default_factory=dict)
    evidence: Dict[str, List[str]] = field(default_factory=dict)
    # STAR completeness is per stage: the story told for question 2 does not
    # complete the story for question 3.
    star_by_stage: Dict[str, Dict[str, str]] = field(default_factory=dict)
    absent_streak: int = 0
    turns_in_stage: int = 0
    probes_used: int = 0
    turns_total: int = 0
    last_assessment: Optional[TurnAssessment] = None

    # -- writing ------------------------------------------------------------

    def merge(self, assessment: TurnAssessment, stage: str) -> None:
        """Fold one turn in. Levels only rise; evidence only accumulates."""
        for read in assessment.signals:
            cur = self.level.get(read.name, "absent")
            self.level[read.name] = _higher(cur, read.level)
            if read.evidence and read.level != "absent":
                bucket = self.evidence.setdefault(read.name, [])
                if read.evidence not in bucket and len(bucket) < MAX_EVIDENCE_PER_SIGNAL:
                    bucket.append(read.evidence)

        stage_star = self.star_by_stage.setdefault(stage, {el: "absent" for el in STAR_ELEMENTS})
        for el in STAR_ELEMENTS:
            stage_star[el] = _higher(stage_star[el], assessment.star.get(el, "absent"))

        if assessment.stale:
            # A missing assessment is not evidence of a weak answer.
            pass
        elif assessment.all_absent:
            self.absent_streak += 1
        else:
            self.absent_streak = 0

        self.turns_in_stage += 1
        self.turns_total += 1
        self.last_assessment = assessment

    def note_probe(self) -> None:
        self.probes_used += 1

    def reset_stage_counters(self) -> None:
        """Called on every stage change. Coverage itself is never reset."""
        self.turns_in_stage = 0
        self.probes_used = 0
        self.absent_streak = 0

    # -- reading ------------------------------------------------------------

    def level_of(self, name: str) -> str:
        return self.level.get(name, "absent")

    def demonstrated(self) -> set:
        return {n for n, lvl in self.level.items() if lvl == "demonstrated"}

    def missing(self, required: Iterable[str]) -> List[str]:
        """Required signals not yet demonstrated, in the order given (absent first)."""
        req = list(required)
        absent = [n for n in req if self.level_of(n) == "absent"]
        partial = [n for n in req if self.level_of(n) == "partial"]
        return absent + partial

    def covered(self, required: Iterable[str]) -> bool:
        return not self.missing(required)

    def star_for(self, stage: str) -> Dict[str, str]:
        return dict(self.star_by_stage.get(stage) or {el: "absent" for el in STAR_ELEMENTS})

    def missing_star(self, stage: str) -> List[str]:
        """STAR elements below 'partial' for this stage, in S-T-A-R order."""
        star = self.star_for(stage)
        return [el for el in STAR_ELEMENTS if _RANK[star[el]] < _RANK["partial"]]

    def result_told(self, stage: str) -> bool:
        return _RANK[self.star_for(stage)["result"]] >= _RANK["partial"]

    def best_evidence(self) -> Optional[Tuple[str, str]]:
        """The strongest thing they said: (signal, verbatim evidence), or None."""
        best: Optional[Tuple[int, str, str]] = None
        for name, quotes in self.evidence.items():
            if not quotes:
                continue
            score = _RANK[self.level_of(name)]
            # Prefer the longer quote at equal level: it reads better spoken.
            quote = max(quotes, key=len)
            if best is None or (score, len(quote)) > (best[0], len(best[2])):
                best = (score, name, quote)
        return (best[1], best[2]) if best else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": dict(self.level),
            "evidence": {k: list(v) for k, v in self.evidence.items()},
            "star_by_stage": {k: dict(v) for k, v in self.star_by_stage.items()},
            "turns_total": self.turns_total,
        }
