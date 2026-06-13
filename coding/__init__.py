"""Coding-track integrity: a vetted problem bank + a sandboxed test runner.

Replaces LLM-invented, unvetted problems and LLM-only "evaluation" with curated
problems that ship their own test cases and reference solutions, plus a runner
that executes candidate code against those tests for an objective pass/fail.
"""

from .problem_bank import (  # noqa: F401
    PROBLEMS,
    difficulty_for_level,
    get_problem,
    list_problems,
    select_problems,
)
from .code_runner import run_python_tests  # noqa: F401
