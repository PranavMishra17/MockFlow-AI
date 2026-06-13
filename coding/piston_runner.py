"""
Execute untrusted candidate code on a hosted Piston instance (real isolation
off our box). Returns the same {passed, total, results, error} shape as the
local runner, so callers are interchangeable.

Opt-in: only used when PISTON_ENABLED=true. PISTON_URL defaults to the public
emkc instance; self-host Piston to remove the rate limit / third-party reliance.
The candidate code runs as a Piston job; we append a small driver that reads the
entrypoint + test cases from stdin and prints per-case JSON results.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List

PISTON_ENABLED = os.getenv("PISTON_ENABLED", "false").lower() == "true"
PISTON_URL = os.getenv("PISTON_URL", "https://emkc.org/api/v2/piston")
PISTON_PYTHON_VERSION = os.getenv("PISTON_PYTHON_VERSION", "3.10.0")

# Fixed driver appended after the candidate source. Reads {"entrypoint","cases"}
# from stdin and prints a JSON list of per-case results.
_DRIVER_TAIL = '''

import json as _json, sys as _sys
_cfg = _json.loads(_sys.stdin.read())
_fn = globals().get(_cfg["entrypoint"])
_out = []
if not callable(_fn):
    print(_json.dumps({"fatal": "entrypoint not defined"}))
else:
    for _c in _cfg["cases"]:
        try:
            _got = _fn(*_c.get("args", []))
            _out.append({"ok": _got == _c.get("expected"), "got": _got, "expected": _c.get("expected")})
        except Exception as _e:
            _out.append({"ok": False, "error": repr(_e), "expected": _c.get("expected")})
    print(_json.dumps(_out))
'''


def run_via_piston(
    source: str,
    entrypoint: str,
    cases: List[Dict[str, Any]],
    language: str = "python",
    timeout: float = 12.0,
) -> Dict[str, Any]:
    """Run `source` against `cases` on Piston. Returns {passed,total,results,error}."""
    total = len(cases)
    if not language.lower().startswith("py"):
        return {"passed": 0, "total": total, "results": [], "error": f"execution not supported for {language}"}

    body = json.dumps({
        "language": "python",
        "version": PISTON_PYTHON_VERSION,
        "files": [{"content": source + "\n" + _DRIVER_TAIL}],
        "stdin": json.dumps({"entrypoint": entrypoint, "cases": cases}),
    }).encode("utf-8")

    req = urllib.request.Request(
        PISTON_URL.rstrip("/") + "/execute",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"passed": 0, "total": total, "results": [], "error": f"piston unreachable: {exc}"}
    except json.JSONDecodeError:
        return {"passed": 0, "total": total, "results": [], "error": "piston: bad response"}

    run = payload.get("run") or {}
    stdout = (run.get("stdout") or "").strip()
    if not stdout:
        return {"passed": 0, "total": total, "results": [], "error": (run.get("stderr") or "no output").strip()[:300]}

    try:
        parsed = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError:
        return {"passed": 0, "total": total, "results": [], "error": f"unparseable: {stdout[:200]}"}

    if isinstance(parsed, dict) and parsed.get("fatal"):
        return {"passed": 0, "total": total, "results": [], "error": parsed["fatal"]}

    results = parsed if isinstance(parsed, list) else []
    passed = sum(1 for r in results if r.get("ok"))
    return {"passed": passed, "total": total, "results": results, "error": None}
