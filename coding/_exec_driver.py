"""
Subprocess driver: reads a JSON payload from stdin, executes the candidate
source in a fresh namespace, runs the entrypoint against each case, and writes
per-case results as JSON to stdout.

Runs in a SEPARATE process so the parent can enforce a wall-clock timeout. This
is process isolation only — it is NOT a full sandbox for untrusted code (no
network/filesystem restriction here). See code_runner.run_python_tests and the
ARCHITECTURE notes for the hardening decision before enabling on candidate code.
"""

import json
import sys


def main() -> None:
    data = json.loads(sys.stdin.read())
    namespace: dict = {}
    # Intentional dynamic execution of the submitted solution (isolated process).
    exec(data["source"], namespace)  # noqa: S102
    fn = namespace.get(data["entrypoint"])
    results = []
    if not callable(fn):
        sys.stdout.write(json.dumps({"fatal": f"entrypoint {data['entrypoint']!r} not defined"}))
        return
    for case in data["cases"]:
        expected = case.get("expected")
        try:
            got = fn(*case.get("args", []))
            results.append({"ok": got == expected, "got": got, "expected": expected})
        except Exception as exc:  # noqa: BLE001 — report any candidate-code error per case
            results.append({"ok": False, "error": repr(exc), "expected": expected})
    sys.stdout.write(json.dumps(results))


if __name__ == "__main__":
    main()
