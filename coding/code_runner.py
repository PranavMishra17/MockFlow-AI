"""
Run candidate Python code against a problem's test cases in a subprocess with a
wall-clock timeout. Returns an objective pass/fail summary.

SECURITY NOTE: this isolates by process + timeout only. Before running UNTRUSTED
candidate code in production, harden it (resource limits, no network, ideally a
container or a hosted runner like Piston/Judge0). It is currently safe for the
vetted bank's own reference solutions (trusted) — see tests/test_problem_bank.py.
"""

import json
import os
import subprocess
import sys
from typing import Any, Dict, List

_DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_exec_driver.py")


def run_python_tests(
    source: str,
    entrypoint: str,
    cases: List[Dict[str, Any]],
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """
    Execute `source` (which must define `entrypoint`) against `cases`.

    Each case is {"args": [...positional...], "expected": <value>}.
    Returns {"passed": int, "total": int, "results": [...], "error": str|None}.
    """
    total = len(cases)
    payload = json.dumps({"source": source, "entrypoint": entrypoint, "cases": cases})
    try:
        proc = subprocess.run(
            [sys.executable, _DRIVER],
            input=payload,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"passed": 0, "total": total, "results": [], "error": "timeout"}

    if proc.returncode != 0:
        return {
            "passed": 0,
            "total": total,
            "results": [],
            "error": (proc.stderr or "runtime error").strip()[:500],
        }

    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"passed": 0, "total": total, "results": [], "error": f"bad output: {proc.stdout[:200]}"}

    if isinstance(parsed, dict) and parsed.get("fatal"):
        return {"passed": 0, "total": total, "results": [], "error": parsed["fatal"]}

    results = parsed if isinstance(parsed, list) else []
    passed = sum(1 for r in results if r.get("ok"))
    return {"passed": passed, "total": total, "results": results, "error": None}
