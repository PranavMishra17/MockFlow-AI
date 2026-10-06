"""
Marketing copy must describe what the code does.

Code reaches the agent only when the candidate presses Submit; nothing reads
the editor while they type. Hidden tests run only with PISTON_ENABLED, which
is off in production, and only for Python.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UNTRUE = ["as you type", "every keystroke", "as you write it", "Runs against real test cases"]


@pytest.mark.parametrize("path", ["templates/index.html", "README.md"])
def test_copy_makes_no_live_review_or_always_executed_claims(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    found = [phrase for phrase in UNTRUE if phrase.lower() in text.lower()]
    assert not found, f"{path} claims {found}"


def test_readme_says_only_python_is_executed():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Monaco code editor (Python, JavaScript, Java, C++, Go)." not in text
    assert "only Python" in text
