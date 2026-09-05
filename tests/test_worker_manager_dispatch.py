"""
Tests for WorkerManager's transport routing.

These cover the decision — direct spawn vs LiveKit dispatch vs BYOK fallback —
without touching LiveKit or spawning processes. Both the subprocess call and the
dispatch coroutine are stubbed, so what is asserted is *which* path was taken and
what state was recorded.
"""

import time

from unittest.mock import MagicMock, patch

import pytest

from worker_manager import WorkerManager

SYS_ENV = {
    "SYSTEM_LIVEKIT_URL": "wss://sys.livekit.cloud",
    "SYSTEM_LIVEKIT_API_KEY": "APIsys",
    "SYSTEM_LIVEKIT_API_SECRET": "secretsys",
    "SYSTEM_OPENAI_KEY": "sk-x",
    "SYSTEM_DEEPGRAM_KEY": "dg-x",
}

SYS_CALL = dict(
    livekit_url="wss://sys.livekit.cloud",
    livekit_api_key="APIsys",
    livekit_api_secret="secretsys",
    openai_api_key="sk-x",
    deepgram_api_key="dg-x",
)

BYOK_CALL = dict(
    SYS_CALL,
    livekit_url="wss://user.livekit.cloud",
    livekit_api_key="APIuser",
    livekit_api_secret="secretuser",
)


@pytest.fixture
def wm():
    return WorkerManager()


@pytest.fixture
def no_spawn():
    """Stub the subprocess path so 'direct' is observable without a real process."""
    with patch.object(WorkerManager, "_spawn_subprocess_for_test", create=True):
        yield


def _dispatch_ok(dispatch_id="D_123"):
    return patch.object(
        WorkerManager, "_create_dispatch",
        autospec=True,
        side_effect=lambda self, room, keys, cfg=None: (
            self.active_dispatches.__setitem__(
                room, {"dispatch_id": dispatch_id, "created_at": time.time()}
            ) or True
        ),
    )


# --------------------------------------------------------------------------
# Mode routing
# --------------------------------------------------------------------------

def test_default_mode_spawns_a_subprocess_and_never_dispatches(wm, monkeypatch):
    monkeypatch.delenv("AGENT_MODE", raising=False)
    for k, v in SYS_ENV.items():
        monkeypatch.setenv(k, v)

    with patch("subprocess.Popen") as popen, \
         patch.object(WorkerManager, "_wait_for_worker_ready", return_value=True), \
         patch.object(WorkerManager, "_create_dispatch") as dispatch:
        assert wm.spawn_worker(room_name="r1", **SYS_CALL) is True

    popen.assert_called_once()
    dispatch.assert_not_called()
    assert "r1" in wm.active_workers
    assert wm.active_dispatches == {}


def test_dispatch_mode_with_system_keys_dispatches_and_never_spawns(wm, monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "dispatch")
    for k, v in SYS_ENV.items():
        monkeypatch.setenv(k, v)

    with patch("subprocess.Popen") as popen, _dispatch_ok():
        assert wm.spawn_worker(room_name="r1", **SYS_CALL) is True

    popen.assert_not_called()
    assert wm.active_dispatches["r1"]["dispatch_id"] == "D_123"
    assert wm.active_workers == {}


def test_byok_credentials_fall_back_to_direct_spawn_even_in_dispatch_mode(wm, monkeypatch):
    """The BYOK collision: a user's own LiveKit project is invisible to the
    resident worker, so dispatching would hang the candidate forever."""
    monkeypatch.setenv("AGENT_MODE", "dispatch")
    for k, v in SYS_ENV.items():
        monkeypatch.setenv(k, v)

    with patch("subprocess.Popen") as popen, \
         patch.object(WorkerManager, "_wait_for_worker_ready", return_value=True), \
         patch.object(WorkerManager, "_create_dispatch") as dispatch:
        assert wm.spawn_worker(room_name="r1", **BYOK_CALL) is True

    dispatch.assert_not_called()
    popen.assert_called_once()
    assert "r1" in wm.active_workers


def test_dispatch_mode_without_system_keys_falls_back_to_direct(wm, monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "dispatch")
    for k in SYS_ENV:
        monkeypatch.delenv(k, raising=False)

    with patch("subprocess.Popen") as popen, \
         patch.object(WorkerManager, "_wait_for_worker_ready", return_value=True), \
         patch.object(WorkerManager, "_create_dispatch") as dispatch:
        assert wm.spawn_worker(room_name="r1", **SYS_CALL) is True

    dispatch.assert_not_called()
    popen.assert_called_once()


def test_invalid_agent_mode_refuses_the_interview_instead_of_guessing(wm, monkeypatch):
    """A typo'd AGENT_MODE must not quietly serve traffic on the other transport.

    Startup catches this first (worker_manager validates at import), but if a
    process is somehow running with a bad value, the request path still refuses
    rather than silently spawning direct.
    """
    monkeypatch.setenv("AGENT_MODE", "dispath")
    with patch("subprocess.Popen") as popen, \
         patch.object(WorkerManager, "_create_dispatch") as dispatch:
        assert wm.spawn_worker(room_name="r1", **SYS_CALL) is False
    popen.assert_not_called()
    dispatch.assert_not_called()
    assert wm.total_active_count() == 0


def test_import_time_validation_rejects_a_bad_mode(monkeypatch):
    import agent_mode
    monkeypatch.setenv("AGENT_MODE", "nonsense")
    with pytest.raises(ValueError):
        agent_mode.resolve_mode(dict(__import__("os").environ))


# --------------------------------------------------------------------------
# Capacity, status, teardown across both transports
# --------------------------------------------------------------------------

def test_dispatched_interviews_do_not_consume_local_capacity(wm, monkeypatch):
    """MAX_CONCURRENT_WORKERS bounds THIS box's memory.

    A dispatched interview runs on the resident worker and costs this process
    nothing, so counting it against the local cap made dispatch *reduce* the
    app's capacity. Combined with nothing ever releasing a dispatch record, the
    cap was reached permanently and every interview on BOTH transports was
    refused until restart.
    """
    monkeypatch.setenv("AGENT_MODE", "dispatch")
    for k, v in SYS_ENV.items():
        monkeypatch.setenv(k, v)
    wm.max_workers = 1
    wm.active_workers = {"local-one": MagicMock(poll=lambda: None)}

    # Local cap is full, but a dispatch needs none of it.
    with _dispatch_ok("D_1"):
        assert wm.spawn_worker(room_name="r2", **SYS_CALL) is True
    with _dispatch_ok("D_2"):
        assert wm.spawn_worker(room_name="r3", **SYS_CALL) is True

    assert wm.local_capacity_used() == 1
    assert wm.total_active_count() == 3


def test_local_cap_still_refuses_a_direct_spawn_when_full(wm, monkeypatch):
    monkeypatch.delenv("AGENT_MODE", raising=False)
    wm.max_workers = 1
    wm.active_workers = {"local-one": MagicMock(poll=lambda: None)}
    with patch("subprocess.Popen") as popen:
        assert wm.spawn_worker(room_name="r2", **SYS_CALL) is False
    popen.assert_not_called()


def test_stale_dispatch_records_age_out_instead_of_leaking(wm):
    """Nothing tells this process a dispatched interview ended, so records must
    expire — otherwise /health reports phantom load forever."""
    now = time.time()
    wm.active_dispatches = {
        "old": {"dispatch_id": "D_old", "created_at": now - (wm.DISPATCH_TTL_SECONDS + 60)},
        "recent": {"dispatch_id": "D_new", "created_at": now},
    }
    assert wm.total_active_count() == 1
    assert "old" not in wm.active_dispatches
    assert "recent" in wm.active_dispatches


def test_status_reports_running_for_a_dispatched_room(wm):
    wm.active_dispatches["r1"] = {"dispatch_id": "D_1", "created_at": time.time()}
    assert wm.get_worker_status("r1") == "running"


def test_status_is_none_for_an_unknown_room(wm):
    assert wm.get_worker_status("nope") is None


def test_terminate_releases_a_dispatched_room_without_killing_anything(wm):
    wm.active_dispatches["r1"] = {"dispatch_id": "D_1", "created_at": time.time()}
    wm.terminate_worker("r1")
    assert wm.active_dispatches == {}
    assert wm.get_worker_status("r1") is None


def test_cleanup_all_clears_both_transports(wm):
    proc = MagicMock()
    proc.poll.return_value = None
    wm.active_workers = {"a": proc}
    wm.active_dispatches = {"b": {"dispatch_id": "D_1", "created_at": time.time()}}

    wm.cleanup_all_workers()

    assert wm.active_workers == {}
    assert wm.active_dispatches == {}
    proc.terminate.assert_called_once()


def test_a_failed_dispatch_is_not_recorded_as_active(wm, monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "dispatch")
    for k, v in SYS_ENV.items():
        monkeypatch.setenv(k, v)

    with patch.object(WorkerManager, "_create_dispatch", return_value=False):
        assert wm.spawn_worker(room_name="r1", **SYS_CALL) is False
    assert wm.total_active_count() == 0


# --------------------------------------------------------------------------
# Regression: the child env, which the original tests never inspected
# --------------------------------------------------------------------------

def test_byok_fallback_child_is_forced_into_direct_mode(wm, monkeypatch):
    """CRITICAL regression guard.

    The fallback subprocess inherits this process's environment. In dispatch
    mode it would inherit AGENT_MODE=dispatch, route __main__ to cli.run_app()
    with no subcommand, and exit 2 ("Missing command.") — so EVERY BYOK user
    would get a 500. spawn_worker must force AGENT_MODE=direct for the child.
    """
    monkeypatch.setenv("AGENT_MODE", "dispatch")
    for k, v in SYS_ENV.items():
        monkeypatch.setenv(k, v)

    with patch("subprocess.Popen") as popen, \
         patch.object(WorkerManager, "_wait_for_worker_ready", return_value=True):
        assert wm.spawn_worker(room_name="r1", **BYOK_CALL) is True

    child_env = popen.call_args.kwargs["env"]
    assert child_env["AGENT_MODE"] == "direct", (
        "fallback child inherited dispatch mode; it would exit 2 on startup"
    )
    assert child_env["INTERVIEW_ROOM_NAME"] == "r1"


def test_direct_mode_child_also_gets_an_explicit_direct_agent_mode(wm, monkeypatch):
    monkeypatch.delenv("AGENT_MODE", raising=False)
    with patch("subprocess.Popen") as popen, \
         patch.object(WorkerManager, "_wait_for_worker_ready", return_value=True):
        assert wm.spawn_worker(room_name="r1", **SYS_CALL) is True
    assert popen.call_args.kwargs["env"]["AGENT_MODE"] == "direct"


# --------------------------------------------------------------------------
# The join confirmation — previously no test touched the real dispatch path
# --------------------------------------------------------------------------

class _FakeParticipant:
    def __init__(self, identity):
        self.identity = identity


class _FakeRoomService:
    def __init__(self, sequence):
        self._sequence = list(sequence)
        self.calls = 0

    async def list_participants(self, _req):
        self.calls += 1
        idents = self._sequence.pop(0) if self._sequence else []
        return MagicMock(participants=[_FakeParticipant(i) for i in idents])


class _FakeClient:
    def __init__(self, sequence):
        self.room = _FakeRoomService(sequence)


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_join_confirmation_succeeds_once_the_agent_appears(wm):
    client = _FakeClient([[], ["candidate"], ["candidate", "interview-agent"]])
    assert _run(wm._await_agent_join(client, "r1")) is True


def test_join_confirmation_ignores_the_candidate_alone(wm, monkeypatch):
    monkeypatch.setattr(WorkerManager, "DISPATCH_JOIN_TIMEOUT", 2)
    client = _FakeClient([["candidate"], ["candidate"], ["candidate"]])
    assert _run(wm._await_agent_join(client, "r1")) is False


def test_join_confirmation_survives_a_room_that_does_not_exist_yet(wm, monkeypatch):
    """list_participants raises until the room exists; that must not abort the wait."""
    monkeypatch.setattr(WorkerManager, "DISPATCH_JOIN_TIMEOUT", 4)

    class Flaky(_FakeClient):
        def __init__(self):
            super().__init__([])
            self.n = 0

            async def lp(_req):
                self.n += 1
                if self.n < 2:
                    raise RuntimeError("room not found")
                return MagicMock(participants=[_FakeParticipant("interview-agent")])

            self.room = MagicMock()
            self.room.list_participants = lp

    assert _run(wm._await_agent_join(Flaky(), "r1")) is True


def test_dispatch_returns_false_when_no_agent_ever_joins(wm, monkeypatch):
    """The core fix: 'LiveKit accepted the request' is NOT 'an agent arrived'.

    spawn_worker returning True is what claims the caller's free-tier credit, so
    it must mean the same thing on both transports.
    """
    monkeypatch.setenv("AGENT_MODE", "dispatch")
    for k, v in SYS_ENV.items():
        monkeypatch.setenv(k, v)

    with patch.object(WorkerManager, "_await_agent_join", return_value=False), \
         patch("livekit.api.LiveKitAPI"):
        assert wm.spawn_worker(room_name="r1", **SYS_CALL) is False
    assert wm.active_dispatches == {}
