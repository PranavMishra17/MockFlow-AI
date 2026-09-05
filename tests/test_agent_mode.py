"""
Tests for agent_mode — the pure decision layer shared by both agent transports.

The contract these lock down:

  1. `direct` stays the default, so an unconfigured deploy behaves exactly as it
     does today.
  2. Interview config parses IDENTICALLY whether it arrived as LiveKit
     participant attributes (direct mode) or as job metadata (dispatch mode).
     This is what "the webapp works the same" actually means — the defaults and
     the list-splitting rules are transcribed from the inline parser that lived
     in agent_worker.run_interview().
  3. Dispatch is refused when the interview's LiveKit credentials are not the
     ones the dispatch worker registered with (the BYOK collision).
"""

import json

import pytest

import agent_mode as am


# --------------------------------------------------------------------------
# Mode resolution
# --------------------------------------------------------------------------

def test_direct_is_the_default_when_unset():
    assert am.resolve_mode({}) == am.MODE_DIRECT


def test_blank_and_whitespace_fall_back_to_direct():
    assert am.resolve_mode({"AGENT_MODE": ""}) == am.MODE_DIRECT
    assert am.resolve_mode({"AGENT_MODE": "   "}) == am.MODE_DIRECT


def test_mode_is_case_and_space_insensitive():
    assert am.resolve_mode({"AGENT_MODE": " DisPatch "}) == am.MODE_DISPATCH
    assert am.resolve_mode({"AGENT_MODE": "DIRECT"}) == am.MODE_DIRECT


def test_unknown_mode_raises_rather_than_silently_guessing():
    # A typo'd AGENT_MODE must not quietly fall back to direct: an operator who
    # meant to run dispatch would get a subprocess-spawning box and never know.
    with pytest.raises(ValueError) as e:
        am.resolve_mode({"AGENT_MODE": "dispath"})
    assert "dispath" in str(e.value)


def test_dispatch_enabled_helper():
    assert am.dispatch_enabled({"AGENT_MODE": "dispatch"}) is True
    assert am.dispatch_enabled({}) is False


# --------------------------------------------------------------------------
# Config parsing — the "identical behavior" contract
# --------------------------------------------------------------------------

def test_empty_config_reproduces_the_legacy_defaults():
    cfg = am.normalize_config({})
    assert cfg == {
        "role": "this position",
        "level": "mid",
        "email": "",
        "resume_text": None,
        "job_description": None,
        "include_profile": True,
        "user_id": None,
        "track": "intro",
        "framework": "amazon",
        "depth": "medium",
        "custom_questions": [],
        "topics": [],
        "custom_topics": [],
    }


def test_none_config_is_treated_as_empty():
    assert am.normalize_config(None) == am.normalize_config({})


def test_scalar_fields_pass_through():
    cfg = am.normalize_config({
        "role": "Backend Engineer",
        "level": "senior",
        "email": "a@b.com",
        "user_id": "u-1",
        "track": "technical_coding",
        "framework": "star",
        "depth": "deep",
    })
    assert cfg["role"] == "Backend Engineer"
    assert cfg["level"] == "senior"
    assert cfg["email"] == "a@b.com"
    assert cfg["user_id"] == "u-1"
    assert cfg["track"] == "technical_coding"
    assert cfg["framework"] == "star"
    assert cfg["depth"] == "deep"


@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("TRUE", True), ("True", True),
    ("false", False), ("FALSE", False), ("no", False), ("0", False),
])
def test_include_profile_string_parsing_matches_legacy(raw, expected):
    # Legacy rule was exactly `attrs.get(...,'true').lower() == 'true'`.
    assert am.normalize_config({"include_profile": raw})["include_profile"] is expected


def test_include_profile_accepts_a_real_bool_from_json_metadata():
    # Attributes are always strings; JSON metadata can carry a real bool.
    assert am.normalize_config({"include_profile": False})["include_profile"] is False
    assert am.normalize_config({"include_profile": True})["include_profile"] is True


def test_custom_questions_split_on_newlines_and_stripped():
    cfg = am.normalize_config({"custom_questions": "  Q one \n\n Q two  \n"})
    assert cfg["custom_questions"] == ["Q one", "Q two"]


def test_topics_and_custom_topics_split_on_commas_and_stripped():
    cfg = am.normalize_config({
        "topics": " kafka , , redis ",
        "custom_topics": "graphs,,tries",
    })
    assert cfg["topics"] == ["kafka", "redis"]
    assert cfg["custom_topics"] == ["graphs", "tries"]


def test_empty_list_strings_produce_empty_lists_not_empty_strings():
    cfg = am.normalize_config({"topics": "", "custom_questions": "", "custom_topics": ""})
    assert cfg["topics"] == []
    assert cfg["custom_questions"] == []
    assert cfg["custom_topics"] == []


def test_lists_pass_through_untouched_from_json_metadata():
    # Metadata can carry real lists; they must not be re-split character-wise.
    cfg = am.normalize_config({
        "topics": ["kafka", "redis"],
        "custom_questions": ["Q one", "Q two"],
    })
    assert cfg["topics"] == ["kafka", "redis"]
    assert cfg["custom_questions"] == ["Q one", "Q two"]


def test_unknown_keys_are_dropped():
    cfg = am.normalize_config({"role": "PM", "injected": "nope"})
    assert "injected" not in cfg


# --------------------------------------------------------------------------
# The equivalence proof: attributes vs metadata
# --------------------------------------------------------------------------

def test_attributes_and_metadata_produce_the_same_config():
    """The core 'works the same' guarantee, asserted directly."""
    attributes = {
        "role": "Backend Engineer",
        "level": "senior",
        "email": "a@b.com",
        "user_id": "u-1",
        "track": "technical_voice",
        "framework": "star",
        "depth": "deep",
        "include_profile": "false",
        "topics": "kafka, redis",
        "custom_topics": "graphs",
        "custom_questions": "Q one\nQ two",
        "resume_text": "RESUME",
        "job_description": "JD",
    }
    metadata = am.encode_job_metadata(am.normalize_config(attributes))

    from_attrs = am.merge_config(metadata=None, attributes=attributes)
    from_meta = am.merge_config(metadata=am.decode_job_metadata(metadata), attributes=None)
    assert from_attrs == from_meta


def test_metadata_wins_over_attributes_when_both_present():
    merged = am.merge_config(metadata={"role": "PM"}, attributes={"role": "SWE", "level": "junior"})
    assert merged["role"] == "PM"
    # Attributes still fill fields metadata omitted.
    assert merged["level"] == "junior"


def test_merge_with_neither_source_yields_defaults():
    assert am.merge_config(metadata=None, attributes=None) == am.normalize_config({})


# --------------------------------------------------------------------------
# Metadata encode / decode
# --------------------------------------------------------------------------

def test_encoded_metadata_is_json_and_round_trips():
    cfg = am.normalize_config({"role": "PM", "topics": "a,b"})
    raw = am.encode_job_metadata(cfg)
    assert json.loads(raw)["role"] == "PM"
    assert am.decode_job_metadata(raw)["topics"] == ["a", "b"]


@pytest.mark.parametrize("bad", [None, "", "   ", "not json", "[1,2,3]", '"a string"', "null"])
def test_malformed_metadata_degrades_to_empty_not_a_crash(bad):
    # A dispatch job with junk metadata must still start an interview on
    # defaults rather than killing the worker.
    assert am.decode_job_metadata(bad) == {}


def test_decode_rejects_non_object_json_payloads():
    assert am.decode_job_metadata("[]") == {}


# --------------------------------------------------------------------------
# The BYOK collision guard
# --------------------------------------------------------------------------

SYS = {
    "livekit_url": "wss://sys.livekit.cloud",
    "livekit_api_key": "APIsys",
    "livekit_api_secret": "secretsys",
}


def test_dispatch_allowed_when_credentials_match_the_worker_project():
    assert am.can_dispatch(SYS, SYS) is True


def test_dispatch_refused_for_a_different_livekit_project():
    byok = dict(SYS, livekit_url="wss://user.livekit.cloud", livekit_api_key="APIuser")
    assert am.can_dispatch(byok, SYS) is False


def test_dispatch_refused_when_only_the_api_key_differs():
    # Same URL can still be a different project/key pair.
    assert am.can_dispatch(dict(SYS, livekit_api_key="APIother"), SYS) is False


def test_dispatch_refused_when_worker_credentials_are_absent():
    assert am.can_dispatch(SYS, None) is False
    assert am.can_dispatch(SYS, {}) is False


def test_dispatch_refused_when_interview_credentials_are_absent():
    assert am.can_dispatch(None, SYS) is False


def test_url_comparison_ignores_trailing_slash_and_case():
    a = dict(SYS, livekit_url="WSS://Sys.LiveKit.Cloud/")
    assert am.can_dispatch(a, SYS) is True


# --------------------------------------------------------------------------
# Regressions found by adversarial review
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [" true", "true ", "True\n", "\ttrue"])
def test_whitespace_padded_include_profile_matches_legacy_exactly(raw):
    """The legacy parser did NOT strip: `attrs.get(k,'true').lower()=='true'`.

    So " true" was False. An earlier version of _as_bool added .strip() and
    silently flipped this. The original differential sweep missed it because
    every sampled value was already clean.
    """
    legacy = raw.lower() == "true"
    assert am.normalize_config({"include_profile": raw})["include_profile"] is legacy


def test_include_profile_whitespace_is_false_not_true():
    assert am.normalize_config({"include_profile": " true"})["include_profile"] is False
