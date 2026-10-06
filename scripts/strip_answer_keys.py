"""
One-off: remove the coding answer key from interview rows saved before PR #16.

Those rows hold the full problem-bank entries (test_cases, reference_solution)
in interviews.track_config.generated_problems, and GET /api/user/interviews
returns them to the browser. Each problem is reduced to the same client-safe
view the editor gets.

    DATABASE_URL=... python scripts/strip_answer_keys.py            # dry run: counts only
    DATABASE_URL=... python scripts/strip_answer_keys.py --apply    # rewrite, one transaction

Idempotent: a second run finds nothing to change.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from psycopg.types.json import Jsonb  # noqa: E402

from interview_runtime import client_problem_view  # noqa: E402


def stripped(track_config):
    problems = (track_config or {}).get("generated_problems")
    if not isinstance(problems, list):
        return None
    clean = [client_problem_view(p) if isinstance(p, dict) else p for p in problems]
    if clean == problems:
        return None
    return {**track_config, "generated_problems": clean}


def run(conn, *, apply: bool) -> int:
    rows = conn.execute(
        "SELECT id, track_config FROM interviews WHERE track_config ? 'generated_problems'"
    ).fetchall()
    dirty = 0
    for row in rows:
        new = stripped(row["track_config"])
        if new is None:
            continue
        dirty += 1
        if apply:
            conn.execute("UPDATE interviews SET track_config = %s WHERE id = %s", (Jsonb(new), row["id"]))
    if apply:
        conn.commit()
    else:
        conn.rollback()
    print(f"{len(rows)} rows with generated problems, {dirty} still holding the answer key"
          f"{' - rewritten' if apply else ' (dry run, nothing written)'}")
    return dirty


def main() -> int:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        run(conn, apply="--apply" in sys.argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
