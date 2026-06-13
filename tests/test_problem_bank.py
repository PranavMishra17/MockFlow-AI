"""
Tests for the vetted coding problem bank + the sandboxed test runner.

The headline test executes every problem's reference solution against its own
test cases — proving the bank contains only solvable, correctly-specified
problems (the exact failure mode of LLM-invented problems).
"""

import pytest

from coding import (
    PROBLEMS,
    difficulty_for_level,
    get_problem,
    run_python_tests,
    select_problems,
)

REQUIRED_KEYS = {
    "slug", "title", "difficulty", "time_limit_minutes", "description",
    "examples", "constraints", "hints", "entrypoint", "starter_code",
    "test_cases", "reference_solution",
}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}


def test_bank_is_non_empty():
    assert len(PROBLEMS) >= 5


@pytest.mark.parametrize("p", PROBLEMS, ids=[p["slug"] for p in PROBLEMS])
def test_problem_shape(p):
    assert REQUIRED_KEYS <= set(p), f"{p['slug']} missing keys: {REQUIRED_KEYS - set(p)}"
    assert p["difficulty"] in VALID_DIFFICULTIES
    assert p["test_cases"], "must ship at least one test case"
    assert "python" in p["starter_code"]
    assert "python" in p["reference_solution"]
    assert p["entrypoint"]


def test_slugs_are_unique():
    slugs = [p["slug"] for p in PROBLEMS]
    assert len(slugs) == len(set(slugs))


@pytest.mark.parametrize("p", PROBLEMS, ids=[p["slug"] for p in PROBLEMS])
def test_reference_solution_passes_its_own_cases(p):
    """This is the integrity guarantee: the bank is provably solvable."""
    result = run_python_tests(
        p["reference_solution"]["python"], p["entrypoint"], p["test_cases"], timeout=5.0
    )
    assert result["error"] is None, f"{p['slug']} runner error: {result['error']}"
    assert result["passed"] == result["total"], (
        f"{p['slug']}: reference solution passed {result['passed']}/{result['total']}"
    )


# ---------- runner behavior ----------

def test_runner_flags_wrong_solution():
    wrong = "def f(a, b):\n    return a - b\n"
    result = run_python_tests(wrong, "f", [{"args": [2, 3], "expected": 5}])
    assert result["passed"] == 0 and result["total"] == 1


def test_runner_reports_timeout():
    looping = "def f():\n    while True:\n        pass\n"
    result = run_python_tests(looping, "f", [{"args": [], "expected": 1}], timeout=1.0)
    assert result["error"] == "timeout"


def test_runner_handles_missing_entrypoint():
    result = run_python_tests("x = 1\n", "does_not_exist", [{"args": [], "expected": 1}])
    assert result["passed"] == 0
    assert result["error"]


def test_runner_catches_candidate_exception():
    boom = "def f(n):\n    raise ValueError('nope')\n"
    result = run_python_tests(boom, "f", [{"args": [1], "expected": 1}])
    assert result["passed"] == 0
    assert result["results"][0]["error"]


# ---------- selector ----------

def test_difficulty_for_level():
    assert difficulty_for_level("junior") == "easy"
    assert difficulty_for_level("mid") == "medium"
    assert difficulty_for_level("senior") == "hard"
    assert difficulty_for_level(None) == "medium"
    assert difficulty_for_level("unknown-title") == "medium"


def test_select_by_difficulty_and_exclude():
    easy = select_problems(difficulty="easy", count=2)
    assert all(p["difficulty"] == "easy" for p in easy)
    assert len(easy) == 2
    first = easy[0]["slug"]
    again = select_problems(difficulty="easy", count=1, exclude_slugs=(first,))
    assert again[0]["slug"] != first


def test_select_falls_back_when_pool_small():
    # More than the number of 'hard' problems -> falls back to fill the count.
    picked = select_problems(difficulty="hard", count=3)
    assert len(picked) == 3


def test_get_problem():
    assert get_problem("two-sum")["title"] == "Two Sum"
    assert get_problem("nope") is None
