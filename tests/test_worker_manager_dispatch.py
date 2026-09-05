"""
Tests for WorkerManager's transport routing.

These cover the decision — direct spawn vs LiveKit dispatch vs BYOK fallback —
without touching LiveKit or spawning processes. Both the subprocess call and the
dispatch coroutine are stubbed, so what is asserted is *which* path was taken and
what state was recorded.
"""

from unittest.mock import MagicMock, patch

import pytest

from worker_manager import WorkerManager

SYS_ENV = {
    "SYSTEM_LIVEKIT_URL": "wss://sys.livekit.cloud",
    "SYSTEM_LIVEKIT_API_KEY": "APIsys",
    "SYSTEM_LIVEKIT_API_SECRET": "secretsys",
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
            self.active_dispatches.__setitem__(room, dispatch_id) or True
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
    assert wm.active_dispatches == {"r1": "D_123"}
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

def test_capacity_counts_both_transports(wm, monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "dispatch")
    for k, v in SYS_ENV.items():
        monkeypatch.setenv(k, v)
    wm.max_workers = 2
    wm.active_workers = {"already-running": MagicMock(poll=lambda: None)}

    with _dispatch_ok("D_1"):
        assert wm.spawn_worker(room_name="r2", **SYS_CALL) is True
    assert wm.total_active_count() == 2

    # At the cap, the next request is refused rather than over-subscribing.
    with patch("subprocess.Popen") as popen, patch.object(WorkerManager, "_create_dispatch") as d:
        assert wm.spawn_worker(room_name="r3", **SYS_CALL) is False
    popen.assert_not_called()
    d.assert_not_called()


def test_status_reports_running_for_a_dispatched_room(wm):
    wm.active_dispatches["r1"] = "D_1"
    assert wm.get_worker_status("r1") == "running"


def test_status_is_none_for_an_unknown_room(wm):
    assert wm.get_worker_status("nope") is None


def test_terminate_releases_a_dispatched_room_without_killing_anything(wm):
    wm.active_dispatches["r1"] = "D_1"
    wm.terminate_worker("r1")
    assert wm.active_dispatches == {}
    assert wm.get_worker_status("r1") is None


def test_cleanup_all_clears_both_transports(wm):
    proc = MagicMock()
    proc.poll.return_value = None
    wm.active_workers = {"a": proc}
    wm.active_dispatches = {"b": "D_1"}

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
