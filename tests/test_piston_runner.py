"""Tests for the Piston execution client (HTTP mocked — no network)."""

import io
import json
from unittest.mock import patch

from coding.piston_runner import run_via_piston

CASES = [{"args": [2, 3], "expected": 5}, {"args": [0, 0], "expected": 0}]


def _fake_response(body: dict):
    """A context-manager stand-in for urllib.request.urlopen's return value."""
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp(json.dumps(body).encode("utf-8"))


def test_parses_passing_results():
    piston_stdout = json.dumps([
        {"ok": True, "got": 5, "expected": 5},
        {"ok": True, "got": 0, "expected": 0},
    ])
    with patch("urllib.request.urlopen", return_value=_fake_response({"run": {"stdout": piston_stdout, "code": 0}})):
        result = run_via_piston("def add(a, b): return a + b", "add", CASES)
    assert result["error"] is None
    assert result["passed"] == 2 and result["total"] == 2


def test_parses_failing_results():
    piston_stdout = json.dumps([
        {"ok": False, "got": -1, "expected": 5},
        {"ok": True, "got": 0, "expected": 0},
    ])
    with patch("urllib.request.urlopen", return_value=_fake_response({"run": {"stdout": piston_stdout}})):
        result = run_via_piston("def add(a, b): return a - b", "add", CASES)
    assert result["passed"] == 1 and result["total"] == 2


def test_network_error_is_caught():
    with patch("urllib.request.urlopen", side_effect=OSError("down")):
        result = run_via_piston("def add(a, b): return a + b", "add", CASES)
    assert result["passed"] == 0
    assert "piston unreachable" in result["error"]


def test_runtime_error_surfaces_stderr():
    with patch("urllib.request.urlopen", return_value=_fake_response({"run": {"stdout": "", "stderr": "Traceback..."}})):
        result = run_via_piston("def add(a, b): return a + b", "add", CASES)
    assert result["passed"] == 0
    assert result["error"]


def test_unsupported_language_short_circuits():
    result = run_via_piston("...", "main", CASES, language="rust")
    assert result["passed"] == 0
    assert "not supported" in result["error"]
