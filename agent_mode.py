"""
Agent transport mode — the pure decision layer shared by both ways of getting an
interview agent into a LiveKit room.

MockFlow-AI historically used ONE transport: the web process spawns
`agent_worker.py` as a subprocess that connects directly to a named room
("direct room connection"). This module adds a second, LiveKit-native transport
("dispatch"), where a long-lived worker registers with a LiveKit project under an
`agent_name` and the server hands it jobs.

## Status on this branch (read this first)

The config layer — `normalize_config` / `merge_config` / `CONFIG_FIELDS` — is the
shared interview-config contract and is also on `main`, where it is the piece
other work should build on.

The dispatch transport IS present on this branch (`worker_manager` routing,
`agent_worker`'s dispatch entrypoint) but **must not be enabled**: see the open
blocking defects at the top of `docs/AGENT_DISPATCH.md`. `AGENT_MODE` defaults to
`direct`, and the direct path on this branch has not yet been run against a live
LiveKit room.

Everything here is pure: no LiveKit calls, no I/O, no environment reads beyond an
explicitly passed mapping. The transports differ only in HOW the room and the
interview config arrive; the interview itself must behave identically. That
equivalence is enforced by `normalize_config` being the single parser for both
participant attributes (direct) and job metadata (dispatch).

    direct    app.py -> worker_manager.Popen(agent_worker.py) -> room.connect()
              config arrives as LiveKit *participant attributes* (all strings)

    dispatch  app.py -> AgentDispatchService.create_dispatch(room, metadata)
              LiveKit -> resident worker -> entrypoint(ctx); ctx.room is connected
              config arrives as *job metadata* (JSON, native types)

## The BYOK collision (read before enabling dispatch)

A dispatch worker registers with exactly ONE LiveKit project. But this app is
BYOK: `resolve_interview_keys()` may hand an interview the *user's own* LiveKit
URL/key/secret. A worker registered against the owner's project will never
receive a job for a room that lives in some user's project — the room is not even
visible to it.

So dispatch is only viable for interviews funded by the SAME credentials the
worker registered with (in practice: the owner-funded free tier / system keys).
`can_dispatch()` is that guard, and callers must fall back to direct spawn when
it returns False. This is a property of BYOK, not a bug to fix here.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

MODE_DIRECT = "direct"
MODE_DISPATCH = "dispatch"
VALID_MODES = (MODE_DIRECT, MODE_DISPATCH)

#: `agent_name` the dispatch worker registers under. Explicit dispatch only
#: routes jobs to workers whose agent_name matches the dispatch request, so this
#: string must agree on both sides.
DEFAULT_AGENT_NAME = "mockflow-interviewer"

#: Every credential that must match for a dispatch to be both ROUTABLE and
#: correctly BILLED. LiveKit decides routability; OpenAI/Deepgram decide whose
#: account pays. Comparing only LiveKit would let a user whose project happens to
#: equal the system one be dispatched onto a worker billing the owner's keys.
_CREDENTIAL_FIELDS = (
    "livekit_url", "livekit_api_key", "livekit_api_secret",
    "openai_key", "deepgram_key",
)

#: env var per credential field. BOTH the web process and the resident worker
#: read these, so "the interview's keys equal the worker's keys" is a claim that
#: can actually be true — the guard previously compared SYSTEM_LIVEKIT_* against
#: a worker registered with unrelated LIVEKIT_* vars.
_SYSTEM_ENV = (
    ("livekit_url", "SYSTEM_LIVEKIT_URL"),
    ("livekit_api_key", "SYSTEM_LIVEKIT_API_KEY"),
    ("livekit_api_secret", "SYSTEM_LIVEKIT_API_SECRET"),
    ("openai_key", "SYSTEM_OPENAI_KEY"),
    ("deepgram_key", "SYSTEM_DEEPGRAM_KEY"),
)


def system_keys_from_env(env: Optional[Mapping[str, str]]) -> Optional[dict]:
    """The owner-funded key set, or None if any part is missing.

    This is the single source of truth for the dispatch worker's identity: the
    worker runs on these keys and the web process compares against these keys.
    """
    env = env or {}
    keys = {field: env.get(var) for field, var in _SYSTEM_ENV}
    return keys if all(keys.values()) else None


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------

def resolve_mode(env: Optional[Mapping[str, str]]) -> str:
    """Resolve AGENT_MODE from an env mapping. Defaults to `direct`.

    Raises ValueError on an unrecognised value rather than falling back: a
    typo'd AGENT_MODE would otherwise silently run the old transport, and the
    operator would have no signal that dispatch never came up.
    """
    raw = ((env or {}).get("AGENT_MODE") or "").strip().lower()
    if not raw:
        return MODE_DIRECT
    if raw not in VALID_MODES:
        raise ValueError(
            f"Unknown AGENT_MODE {raw!r}. Expected one of {', '.join(VALID_MODES)}."
        )
    return raw


def dispatch_enabled(env: Optional[Mapping[str, str]]) -> bool:
    """True when this process is configured for the dispatch transport."""
    return resolve_mode(env) == MODE_DISPATCH


def agent_name(env: Optional[Mapping[str, str]] = None) -> str:
    """The dispatch `agent_name`, overridable so two deploys can share a project."""
    return ((env or {}).get("AGENT_NAME") or "").strip() or DEFAULT_AGENT_NAME


# ---------------------------------------------------------------------------
# Interview config — one parser for both transports
# ---------------------------------------------------------------------------

# Defaults transcribed from the inline parser that lived in
# agent_worker.run_interview(). Changing one changes interview behavior, so they
# are pinned by tests/test_agent_mode.py.
_SCALAR_DEFAULTS: dict[str, Any] = {
    "role": "this position",
    "level": "mid",
    "email": "",
    "resume_text": None,
    "job_description": None,
    "user_id": None,
    "track": "intro",
    "framework": "amazon",
    "depth": "medium",
    # Coding-track settings. These used to be read straight off participant
    # attributes, which meant (a) a metadata-only dispatch silently lost them and
    # (b) the read was guarded by `'attrs' in dir()`, a check that broke once
    # `attrs` was always bound. Routing them through the shared parser fixes both.
    "preferred_language": "python",
    "problem_count": "2",
}

#: field -> separator used when the value arrives as a flat string (attributes
#: are always strings, so lists have to be encoded somehow).
_LIST_SEPARATORS = {
    "custom_questions": "\n",
    "topics": ",",
    "custom_topics": ",",
}

CONFIG_FIELDS = tuple(_SCALAR_DEFAULTS) + ("include_profile",) + tuple(_LIST_SEPARATORS)


def _as_list(value: Any, separator: str) -> list[str]:
    """Split a separator-joined string, or accept an already-native list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(separator) if part.strip()]


def _as_bool(value: Any) -> bool:
    """Legacy rule, preserved exactly: `attrs.get(k, 'true').lower() == 'true'`.

    Note the absence of `.strip()`. That is deliberate, not an oversight: the
    original parser did not strip, so " true" evaluated to False. Adding a strip
    here would silently flip that one case and break the equivalence this module
    exists to guarantee. A real JSON bool from job metadata is honoured directly.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return True  # legacy default was 'true'
    return str(value).lower() == "true"


def normalize_config(raw: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Parse an interview-config mapping from EITHER transport into one shape.

    Accepts LiveKit participant attributes (str -> str) or decoded job metadata
    (str -> native JSON). Unknown keys are dropped so neither transport can
    inject fields the interview code does not expect.
    """
    raw = raw or {}
    cfg: dict[str, Any] = {}
    for field, default in _SCALAR_DEFAULTS.items():
        value = raw.get(field, default)
        cfg[field] = default if value is None else value
    cfg["include_profile"] = _as_bool(raw.get("include_profile"))
    for field, separator in _LIST_SEPARATORS.items():
        cfg[field] = _as_list(raw.get(field), separator)
    return cfg


def merge_config(
    metadata: Optional[Mapping[str, Any]],
    attributes: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    """Combine both transports, metadata winning field-by-field.

    Dispatch jobs carry metadata; the participant may *also* carry attributes
    (the web client sets them regardless of mode). Preferring metadata keeps
    dispatch authoritative while letting attributes fill anything it omitted, so
    a half-populated job still starts a sane interview.
    """
    combined: dict[str, Any] = {}
    for source in (attributes or {}, metadata or {}):
        for field in CONFIG_FIELDS:
            if field in source and source[field] is not None:
                combined[field] = source[field]
    return normalize_config(combined)


# ---------------------------------------------------------------------------
# Job metadata transport
# ---------------------------------------------------------------------------

def encode_job_metadata(config: Mapping[str, Any]) -> str:
    """Serialize interview config for CreateAgentDispatchRequest.metadata."""
    return json.dumps({k: v for k, v in config.items() if k in CONFIG_FIELDS})


def decode_job_metadata(raw: Optional[str]) -> dict[str, Any]:
    """Parse job metadata, degrading to {} on anything malformed.

    A dispatch job with unparseable metadata should still run an interview on
    defaults rather than take the resident worker down.
    """
    if not raw or not str(raw).strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# The BYOK guard
# ---------------------------------------------------------------------------

def _same_url(a: str, b: str) -> bool:
    return str(a).strip().rstrip("/").lower() == str(b).strip().rstrip("/").lower()


def can_dispatch(
    interview_keys: Optional[Mapping[str, str]],
    worker_keys: Optional[Mapping[str, str]],
) -> bool:
    """True only if this interview's LiveKit project IS the worker's project.

    A dispatch request is addressed to a room inside the project identified by
    the API key it is signed with. A worker registered elsewhere will never see
    it, and the candidate would wait out the join timeout with no agent. When
    this is False the caller MUST fall back to direct spawn.
    """
    if not interview_keys or not worker_keys:
        return False
    if not all(interview_keys.get(f) for f in _CREDENTIAL_FIELDS):
        return False
    if not all(worker_keys.get(f) for f in _CREDENTIAL_FIELDS):
        return False
    if not _same_url(interview_keys["livekit_url"], worker_keys["livekit_url"]):
        return False
    return all(
        interview_keys[f] == worker_keys[f]
        for f in _CREDENTIAL_FIELDS if f != "livekit_url"
    )
