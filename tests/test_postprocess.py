"""Characterization tests for transcript re-sequencing (pure logic)."""

import json

from postprocess import (
    merge_by_agent_turns,
    _merge_user_partials,
    resequence_interview,
)


def test_merge_empty_returns_empty():
    assert merge_by_agent_turns([], []) == []


def test_user_partials_interleave_before_agent_turns():
    agent = [
        {"text": "A1", "timestamp": 1.0, "stage": "intro"},
        {"text": "A2", "timestamp": 3.0, "stage": "intro"},
    ]
    user = [
        {"text": "u1", "timestamp": 0.5},
        {"text": "u2a", "timestamp": 2.0},
        {"text": "u2b", "timestamp": 2.5},
    ]
    turns = merge_by_agent_turns(agent, user)
    assert [t["role"] for t in turns] == ["candidate", "agent", "candidate", "agent"]
    # Adjacent user partials before the second agent turn are merged into one.
    assert turns[2]["text"] == "u2a u2b"
    assert turns[2]["partial_count"] == 2


def test_trailing_user_messages_after_last_agent_are_kept():
    agent = [{"text": "A1", "timestamp": 1.0}]
    user = [{"text": "later", "timestamp": 9.0}]
    turns = merge_by_agent_turns(agent, user)
    assert turns[-1]["role"] == "candidate"
    assert turns[-1]["text"] == "later"


def test_merge_user_partials_splits_on_large_gap():
    msgs = [
        {"text": "a", "timestamp": 0.0},
        {"text": "b", "timestamp": 1.0},  # gap 1s -> same turn
        {"text": "c", "timestamp": 20.0},  # gap 19s -> new turn
    ]
    merged = _merge_user_partials(msgs, gap_threshold=5.0)
    assert len(merged) == 2
    assert merged[0]["text"] == "a b"
    assert merged[0]["partial_count"] == 2


def test_resequence_interview_from_file(tmp_path):
    interview = {
        "candidate": "Synthetic Candidate",
        "interview_date": "2026-01-01T10:00:00",
        "room_name": "interview-test-1",
        "job_role": "Backend Engineer",
        "experience_level": "mid",
        "conversation": {
            "agent": [{"text": "Tell me about yourself.", "timestamp": 1.0, "stage": "self_intro"}],
            "user": [{"text": "I am an engineer.", "timestamp": 2.0}],
        },
    }
    path = tmp_path / "interview.json"
    path.write_text(json.dumps(interview), encoding="utf-8")

    result = resequence_interview(str(path))
    assert "error" not in result
    assert result["meta"]["candidate"] == "Synthetic Candidate"
    assert result["meta"]["total_agent_messages"] == 1
    roles = [t["role"] for t in result["ordered_conversation"]]
    assert "agent" in roles and "candidate" in roles
