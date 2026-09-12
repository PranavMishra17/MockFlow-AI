"""
The turn loop's decisions, without a model: ledger merge, progression policy,
move selection, the note the model reads, and the closing line.

Each test is one of the audit's failure modes stated as a rule
(docs/AGENT_AUDIT_2026-09.md): a STAR story told early is credited (F7/F8),
a repeat request repeats (F9), a rambler gets pinned to the result and a
terse candidate gets a narrow question (F8), the transition arrives with a
question (F2/F3), the closing is one utterance ending in the sentinel (F14).
"""

import pytest

import interview_turn as it
from interview_coverage import CoverageLedger, TurnAssessment


def read(**signals):
    """Shorthand: read(Ownership='demonstrated:I built it', **{'Impact & metrics': 'partial'})."""
    sigs = []
    for name, spec in signals.items():
        level, _, evidence = spec.partition(":")
        sigs.append({"name": name, "level": level, "evidence": evidence})
    return sigs


def assessment(signals=None, star=None, **kw):
    d = {"signals": signals or [], "star": star or {}}
    d.update(kw)
    return TurnAssessment.from_dict(d, words=kw.get("words", 60))


BANK_Q = {"main_question": "Tell me about a time you had to dive deep to solve a complex issue.",
          "competency": "Dive Deep",
          "follow_up_probes": ["What tools did you use to diagnose it?", "How did you make sure the fix stuck?"]}


def behavioral(stage="behavioral_q1", **kw):
    return it.TurnInputs(track="behavioral", stage=stage, bank_item=BANK_Q, next_stage="behavioral_q2",
                         next_bank_item={"main_question": "Describe a time you balanced customer needs against constraints.",
                                         "competency": "Customer Obsession", "follow_up_probes": []},
                         time_status={"is_overtime": False}, **kw)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def test_signal_names_used_here_all_exist_in_the_verdict_library():
    from evaluator import SIGNAL_LIBRARY
    used = {n for track in it._STAGE_SIGNALS.values() for names in track.values() for n in names}
    used |= {sig for _, sig in it._COMPETENCY_KEYWORDS} | {"Impact & metrics"}
    missing = used - set(SIGNAL_LIBRARY)
    assert not missing, missing


def test_ledger_levels_only_rise_and_evidence_accumulates():
    led = CoverageLedger()
    led.merge(assessment(read(Ownership="demonstrated:I made the call to ship")), "self_intro")
    led.merge(assessment(read(Ownership="absent")), "behavioral_q1")
    assert led.level_of("Ownership") == "demonstrated"
    assert led.evidence["Ownership"] == ["I made the call to ship"]


def test_a_star_story_told_in_self_intro_credits_the_behavioral_stage():
    """The owner's case: full story early -> Flow must not ask for it again."""
    led = CoverageLedger()
    led.merge(assessment(read(**{"Ownership": "demonstrated:I was the one on call", "Impact & metrics": "demonstrated:CTR recovered the next day"}),
                         star={"situation": "demonstrated", "task": "demonstrated", "action": "demonstrated", "result": "demonstrated"}),
              "self_intro")
    required = it.stage_required_signals("behavioral", "behavioral_q1", BANK_Q)
    assert led.missing(required) == []


def test_star_completeness_is_per_stage():
    led = CoverageLedger()
    led.merge(assessment(star={"situation": "demonstrated", "task": "demonstrated", "action": "demonstrated", "result": "demonstrated"}), "behavioral_q1")
    assert led.missing_star("behavioral_q1") == []
    assert led.missing_star("behavioral_q2") == ["situation", "task", "action", "result"]


def test_stale_assessment_does_not_count_as_a_weak_answer():
    led = CoverageLedger()
    led.merge(TurnAssessment.empty(words=40), "self_intro")
    assert led.absent_streak == 0
    assert led.turns_in_stage == 1


def test_best_evidence_prefers_the_strongest_signal():
    led = CoverageLedger()
    led.merge(assessment(read(**{"Communication & structure": "partial:I like the messy end of ML",
                                 "Impact & metrics": "demonstrated:cut p99 latency 40%"})), "self_intro")
    assert led.best_evidence() == ("Impact & metrics", "cut p99 latency 40%")


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------

def test_stage_advances_on_coverage_not_on_question_count():
    led = CoverageLedger()
    a = assessment(read(**{"Ownership": "demonstrated:I", "Impact & metrics": "demonstrated:8% drop fixed in six hours"}),
                   star={"situation": "demonstrated", "task": "demonstrated", "action": "demonstrated", "result": "demonstrated"})
    led.merge(a, "behavioral_q1")
    assert it.should_advance(behavioral(), led, a) == "coverage"


def test_behavioral_stage_waits_for_the_result_even_when_signals_are_covered():
    led = CoverageLedger()
    a = assessment(read(**{"Ownership": "demonstrated:I", "Impact & metrics": "demonstrated:x"}),
                   star={"situation": "demonstrated", "task": "demonstrated", "action": "demonstrated", "result": "absent"})
    led.merge(a, "behavioral_q1")
    assert it.should_advance(behavioral(), led, a) is None


def test_terse_candidate_with_no_signal_twice_is_moved_on():
    led = CoverageLedger()
    a = assessment(read(Ownership="absent"), answer_style="terse", words=4)
    led.merge(a, "self_intro")
    assert it.should_advance(behavioral("self_intro"), led, a) is None
    led.merge(a, "self_intro")
    assert it.should_advance(behavioral("self_intro"), led, a) == "terse_no_signal"


def test_turn_cap_follows_depth_setting():
    led = CoverageLedger()
    a = assessment(read(Ownership="partial:something"))
    for _ in range(2):
        led.merge(a, "behavioral_q1")
    assert it.should_advance(behavioral(depth="light"), led, a) == "turn_cap"
    assert it.should_advance(behavioral(depth="deep"), led, a) is None


def test_overtime_advances_regardless():
    led = CoverageLedger()
    a = assessment()
    led.merge(a, "behavioral_q1")
    inp = behavioral(); inp.time_status = {"is_overtime": True}
    assert it.should_advance(inp, led, a) == "overtime"


def test_coding_problem_stages_are_never_advanced_by_the_conversation():
    led = CoverageLedger()
    a = assessment(answer_style="terse")
    for _ in range(6):
        led.merge(a, "coding_problem_1")
    inp = it.TurnInputs(track="coding", stage="coding_problem_1", time_status={"is_overtime": True})
    assert it.should_advance(inp, led, a) is None


# ---------------------------------------------------------------------------
# Move selection
# ---------------------------------------------------------------------------

def test_repeat_request_repeats_the_last_question_verbatim():
    led = CoverageLedger()
    a = assessment(candidate_asked="repeat", words=9)
    inp = behavioral(last_question="Tell me about a time you had to dive deep to solve a complex issue.")
    m = it.choose_move(inp, led, a)
    assert m.kind == "repeat" and m.question == inp.last_question and m.preface == it.PREFACE_REPEAT


def test_company_question_gets_the_honest_line_and_still_moves_the_interview():
    led = CoverageLedger()
    a = assessment(candidate_asked="company")
    m = it.choose_move(behavioral(), led, a)
    assert m.preface == it.PREFACE_COMPANY
    assert m.question or m.focus


def test_feedback_request_is_declined_honestly():
    led = CoverageLedger()
    m = it.choose_move(behavioral(), led, assessment(candidate_asked="feedback"))
    assert m.preface == it.PREFACE_PROCESS


def test_dont_know_gets_one_scaffold_then_moves_on():
    led = CoverageLedger()
    a = assessment(said_dont_know=True, words=5)
    first = it.choose_move(behavioral(), led, a)
    assert first.kind == "scaffold" and first.question == it.SCAFFOLD
    second = it.choose_move(behavioral(), led, a)
    assert second.kind in ("ask", "focus") and second.preface == it.PREFACE_DONT_KNOW


def test_rambler_who_did_not_answer_is_pinned_to_the_result():
    led = CoverageLedger()
    a = assessment(read(Ownership="partial:so basically the booking flow"), answer_style="rambling", answered_question=False, words=220)
    m = it.choose_move(behavioral(), led, a)
    assert m.kind == "probe" and m.question == it.RAMBLE_PROBE


def test_terse_candidate_gets_a_narrow_question_about_the_one_thing_they_said():
    led = CoverageLedger()
    a = assessment(read(Ownership="partial:the claims batch pipeline"), answer_style="terse", words=7)
    m = it.choose_move(behavioral("self_intro"), led, a)
    assert m.kind == "focus" and "claims batch pipeline" in m.focus


def test_missing_result_uses_the_banks_specific_probe_not_the_template():
    led = CoverageLedger()
    a = assessment(read(Ownership="demonstrated:I led it"),
                   star={"situation": "demonstrated", "task": "demonstrated", "action": "demonstrated", "result": "absent"})
    led.merge(a, "behavioral_q1")
    inp = behavioral(questions_asked=[BANK_Q["main_question"]])
    m = it.choose_move(inp, led, a)
    assert m.kind == "probe"
    assert m.question in BANK_Q["follow_up_probes"]
    assert "Any metrics or concrete impact" not in m.question


def test_bank_probes_are_not_repeated():
    led = CoverageLedger()
    a = assessment(star={"situation": "demonstrated", "task": "demonstrated", "action": "demonstrated", "result": "absent"})
    led.merge(a, "behavioral_q1")
    inp = behavioral(questions_asked=[BANK_Q["main_question"]] + BANK_Q["follow_up_probes"])
    m = it.choose_move(inp, led, a)
    assert m.question == it.STAR_PROBES["result"]


def test_transition_arrives_with_the_next_stages_question_in_the_same_move():
    led = CoverageLedger()
    a = assessment(read(**{"Ownership": "demonstrated:I", "Impact & metrics": "demonstrated:30% faster"}),
                   star={k: "demonstrated" for k in ("situation", "task", "action", "result")})
    led.merge(a, "behavioral_q1")
    inp = behavioral()
    m = it.choose_move(inp, led, a, advance_reason="coverage")
    assert m.advanced_to == "behavioral_q2"
    assert m.question.startswith("Describe a time you balanced customer needs")
    assert m.ack_hint == "I"


def test_coding_problem_stage_replies_without_asking():
    inp = it.TurnInputs(track="coding", stage="coding_problem_1")
    m = it.choose_move(inp, CoverageLedger(), assessment(words=30))
    assert m.kind == "coding_reply" and not m.is_question
    assert "Ask nothing" in it.render_move_note(m)


# ---------------------------------------------------------------------------
# The note, and the closing
# ---------------------------------------------------------------------------

def test_note_carries_the_question_verbatim_and_the_voice_rules():
    m = it.Move(kind="ask", question="What broke first?", ack_hint="six hours to root cause", preface=it.PREFACE_COMPANY)
    note = it.render_move_note(m)
    assert note.startswith(it.MOVE_HEADER)
    assert 'First say exactly: "' + it.PREFACE_COMPANY + '"' in note
    assert 'ask exactly, word for word: "What broke first?"' in note
    assert "no praise adjectives" in note and "Do not say the candidate's name" in note
    assert "[" not in note.replace(it.MOVE_HEADER, "")   # no unreplaced placeholders


def test_focus_note_asks_for_one_concrete_question():
    note = it.render_move_note(it.Move(kind="focus", focus="the measurable outcome of something they built"))
    assert "ONE concrete question about: the measurable outcome" in note
    assert "word for word" not in note


def test_closing_is_one_utterance_quoting_their_own_words_and_ending_with_the_sentinel():
    led = CoverageLedger()
    led.merge(assessment(read(**{"Impact & metrics": "demonstrated:CTR recovered the next day"})), "behavioral_q1")
    line = it.build_closing_utterance(led, "Pranav", "behavioral")
    assert line.endswith(it.CLOSING_SENTINEL)
    assert "CTR recovered the next day" in line
    assert "dashboard" in line
    for banned in ("great", "excellent", "impressive", "email", "in touch"):
        assert banned not in line.lower()


def test_closing_without_evidence_still_ends_cleanly():
    line = it.build_closing_utterance(CoverageLedger(), "Ken", "intro")
    assert line.startswith("Thanks, Ken.") and line.endswith(it.CLOSING_SENTINEL)


def test_assessment_from_dict_tolerates_garbage():
    a = TurnAssessment.from_dict({"signals": [{"name": "Ownership", "level": "yes"}, "nonsense", {"level": "partial"}],
                                  "star": {"result": "strong"}, "answer_style": "shouty", "candidate_asked": 42})
    assert [s.name for s in a.signals] == ["Ownership"] and a.signals[0].level == "demonstrated"
    assert a.star["result"] == "demonstrated" and a.answer_style == "normal" and a.candidate_asked == "none"


@pytest.mark.parametrize("competency,signal", [
    ("Dive Deep", "Impact & metrics"), ("Earn Trust", "Conflict & collaboration"),
    ("Ownership", "Ownership"), ("Deliver Results", "Ownership"), ("Customer Obsession", "Impact & metrics"),
])
def test_competency_to_signal_mapping(competency, signal):
    assert it.competency_signal(competency) == signal
