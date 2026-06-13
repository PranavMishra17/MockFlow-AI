"""
Vetted coding problem bank.

Each problem keeps the shape the agent + frontend already consume
(title/description/examples/constraints/difficulty/time_limit_minutes/hints) and
ADDS what makes evaluation objective: an `entrypoint`, `starter_code`,
`test_cases` ({"args": [...], "expected": ...}), and a `reference_solution`.

tests/test_problem_bank.py executes every reference solution against its own
test cases, so the bank is provably self-consistent (no unsolvable/ambiguous
problems — the failure mode of LLM-invented problems).
"""

from typing import Any, Dict, List, Optional

# Map experience level -> default difficulty (mirrors the agent's prior logic).
LEVEL_DIFFICULTY = {
    "entry": "easy", "intern": "easy", "junior": "easy",
    "mid": "medium", "intermediate": "medium",
    "senior": "hard", "lead": "hard", "staff": "hard", "principal": "hard",
}


PROBLEMS: List[Dict[str, Any]] = [
    {
        "slug": "two-sum",
        "title": "Two Sum",
        "difficulty": "easy",
        "time_limit_minutes": 15,
        "description": (
            "Given an array of integers `nums` and an integer `target`, return the "
            "indices of the two numbers that add up to `target`. Exactly one solution "
            "exists and you may not use the same element twice. Return the indices in "
            "increasing order."
        ),
        "examples": [
            {"input": "nums = [2,7,11,15], target = 9", "output": "[0,1]", "explanation": "2 + 7 = 9"},
            {"input": "nums = [3,2,4], target = 6", "output": "[1,2]"},
        ],
        "constraints": ["2 <= len(nums) <= 10^4", "Exactly one valid answer exists"],
        "hints": ["For each number, what complement would complete the pair?", "A hash map of value->index gives O(n)."],
        "entrypoint": "two_sum",
        "starter_code": {"python": "def two_sum(nums, target):\n    # return [i, j] with i < j\n    pass\n"},
        "test_cases": [
            {"args": [[2, 7, 11, 15], 9], "expected": [0, 1]},
            {"args": [[3, 2, 4], 6], "expected": [1, 2]},
            {"args": [[3, 3], 6], "expected": [0, 1]},
            {"args": [[-1, -2, -3, -4, -5], -8], "expected": [2, 4]},
        ],
        "reference_solution": {
            "python": (
                "def two_sum(nums, target):\n"
                "    seen = {}\n"
                "    for i, n in enumerate(nums):\n"
                "        c = target - n\n"
                "        if c in seen:\n"
                "            return [seen[c], i]\n"
                "        seen[n] = i\n"
                "    return []\n"
            )
        },
    },
    {
        "slug": "valid-parentheses",
        "title": "Valid Parentheses",
        "difficulty": "easy",
        "time_limit_minutes": 15,
        "description": (
            "Given a string `s` of just '()[]{}' characters, return True if every "
            "bracket is closed by the same type in the correct order, else False."
        ),
        "examples": [
            {"input": "s = \"()[]{}\"", "output": "True"},
            {"input": "s = \"([)]\"", "output": "False"},
        ],
        "constraints": ["0 <= len(s) <= 10^4", "s contains only bracket characters"],
        "hints": ["A stack matches the most recent open bracket.", "Empty string is valid."],
        "entrypoint": "is_valid",
        "starter_code": {"python": "def is_valid(s):\n    pass\n"},
        "test_cases": [
            {"args": ["()"], "expected": True},
            {"args": ["()[]{}"], "expected": True},
            {"args": ["(]"], "expected": False},
            {"args": ["([)]"], "expected": False},
            {"args": ["{[]}"], "expected": True},
            {"args": [""], "expected": True},
        ],
        "reference_solution": {
            "python": (
                "def is_valid(s):\n"
                "    pairs = {')': '(', ']': '[', '}': '{'}\n"
                "    stack = []\n"
                "    for ch in s:\n"
                "        if ch in '([{':\n"
                "            stack.append(ch)\n"
                "        else:\n"
                "            if not stack or stack.pop() != pairs[ch]:\n"
                "                return False\n"
                "    return not stack\n"
            )
        },
    },
    {
        "slug": "binary-search",
        "title": "Binary Search",
        "difficulty": "easy",
        "time_limit_minutes": 12,
        "description": (
            "Given a sorted ascending array `nums` and a `target`, return the index of "
            "target, or -1 if it is not present. Aim for O(log n)."
        ),
        "examples": [
            {"input": "nums = [-1,0,3,5,9,12], target = 9", "output": "4"},
            {"input": "nums = [-1,0,3,5,9,12], target = 2", "output": "-1"},
        ],
        "constraints": ["nums is sorted ascending", "elements are unique"],
        "hints": ["Maintain lo/hi bounds.", "Compare against the midpoint each step."],
        "entrypoint": "search",
        "starter_code": {"python": "def search(nums, target):\n    pass\n"},
        "test_cases": [
            {"args": [[-1, 0, 3, 5, 9, 12], 9], "expected": 4},
            {"args": [[-1, 0, 3, 5, 9, 12], 2], "expected": -1},
            {"args": [[5], 5], "expected": 0},
            {"args": [[], 1], "expected": -1},
        ],
        "reference_solution": {
            "python": (
                "def search(nums, target):\n"
                "    lo, hi = 0, len(nums) - 1\n"
                "    while lo <= hi:\n"
                "        mid = (lo + hi) // 2\n"
                "        if nums[mid] == target:\n"
                "            return mid\n"
                "        if nums[mid] < target:\n"
                "            lo = mid + 1\n"
                "        else:\n"
                "            hi = mid - 1\n"
                "    return -1\n"
            )
        },
    },
    {
        "slug": "maximum-subarray",
        "title": "Maximum Subarray",
        "difficulty": "medium",
        "time_limit_minutes": 20,
        "description": (
            "Given an integer array `nums`, return the largest sum of any contiguous "
            "non-empty subarray."
        ),
        "examples": [
            {"input": "nums = [-2,1,-3,4,-1,2,1,-5,4]", "output": "6", "explanation": "[4,-1,2,1] sums to 6"},
            {"input": "nums = [5,4,-1,7,8]", "output": "23"},
        ],
        "constraints": ["1 <= len(nums) <= 10^5"],
        "hints": ["Track the best sum ending at each index.", "Kadane's algorithm is O(n)."],
        "entrypoint": "max_sub_array",
        "starter_code": {"python": "def max_sub_array(nums):\n    pass\n"},
        "test_cases": [
            {"args": [[-2, 1, -3, 4, -1, 2, 1, -5, 4]], "expected": 6},
            {"args": [[1]], "expected": 1},
            {"args": [[5, 4, -1, 7, 8]], "expected": 23},
            {"args": [[-1]], "expected": -1},
            {"args": [[-2, -1]], "expected": -1},
        ],
        "reference_solution": {
            "python": (
                "def max_sub_array(nums):\n"
                "    best = cur = nums[0]\n"
                "    for n in nums[1:]:\n"
                "        cur = max(n, cur + n)\n"
                "        best = max(best, cur)\n"
                "    return best\n"
            )
        },
    },
    {
        "slug": "longest-substring-no-repeat",
        "title": "Longest Substring Without Repeating Characters",
        "difficulty": "medium",
        "time_limit_minutes": 20,
        "description": (
            "Given a string `s`, return the length of the longest substring that "
            "contains no repeating characters."
        ),
        "examples": [
            {"input": "s = \"abcabcbb\"", "output": "3", "explanation": "\"abc\""},
            {"input": "s = \"pwwkew\"", "output": "3", "explanation": "\"wke\""},
        ],
        "constraints": ["0 <= len(s) <= 5*10^4"],
        "hints": ["Use a sliding window.", "Track the last index of each character."],
        "entrypoint": "length_of_longest_substring",
        "starter_code": {"python": "def length_of_longest_substring(s):\n    pass\n"},
        "test_cases": [
            {"args": ["abcabcbb"], "expected": 3},
            {"args": ["bbbbb"], "expected": 1},
            {"args": ["pwwkew"], "expected": 3},
            {"args": [""], "expected": 0},
            {"args": ["au"], "expected": 2},
            {"args": ["dvdf"], "expected": 3},
        ],
        "reference_solution": {
            "python": (
                "def length_of_longest_substring(s):\n"
                "    last = {}\n"
                "    start = 0\n"
                "    best = 0\n"
                "    for i, ch in enumerate(s):\n"
                "        if ch in last and last[ch] >= start:\n"
                "            start = last[ch] + 1\n"
                "        last[ch] = i\n"
                "        best = max(best, i - start + 1)\n"
                "    return best\n"
            )
        },
    },
    {
        "slug": "merge-intervals",
        "title": "Merge Intervals",
        "difficulty": "medium",
        "time_limit_minutes": 20,
        "description": (
            "Given a list of intervals `[start, end]`, merge all overlapping intervals "
            "and return them sorted by start."
        ),
        "examples": [
            {"input": "[[1,3],[2,6],[8,10],[15,18]]", "output": "[[1,6],[8,10],[15,18]]"},
            {"input": "[[1,4],[4,5]]", "output": "[[1,5]]"},
        ],
        "constraints": ["1 <= len(intervals) <= 10^4", "start <= end"],
        "hints": ["Sort by start first.", "Extend the last merged interval when it overlaps."],
        "entrypoint": "merge",
        "starter_code": {"python": "def merge(intervals):\n    pass\n"},
        "test_cases": [
            {"args": [[[1, 3], [2, 6], [8, 10], [15, 18]]], "expected": [[1, 6], [8, 10], [15, 18]]},
            {"args": [[[1, 4], [4, 5]]], "expected": [[1, 5]]},
            {"args": [[[1, 4], [2, 3]]], "expected": [[1, 4]]},
            {"args": [[[1, 4]]], "expected": [[1, 4]]},
        ],
        "reference_solution": {
            "python": (
                "def merge(intervals):\n"
                "    intervals = sorted(intervals, key=lambda x: x[0])\n"
                "    out = []\n"
                "    for s, e in intervals:\n"
                "        if out and s <= out[-1][1]:\n"
                "            out[-1][1] = max(out[-1][1], e)\n"
                "        else:\n"
                "            out.append([s, e])\n"
                "    return out\n"
            )
        },
    },
]


def difficulty_for_level(level: Optional[str]) -> str:
    """Map an experience level to a default difficulty (defaults to 'medium')."""
    return LEVEL_DIFFICULTY.get((level or "").strip().lower(), "medium")


def list_problems() -> List[Dict[str, Any]]:
    return PROBLEMS


def get_problem(slug: str) -> Optional[Dict[str, Any]]:
    for p in PROBLEMS:
        if p["slug"] == slug:
            return p
    return None


def select_problems(
    difficulty: Optional[str] = None,
    level: Optional[str] = None,
    count: int = 1,
    exclude_slugs: tuple = (),
) -> List[Dict[str, Any]]:
    """
    Pick up to `count` vetted problems. Prefers the given difficulty (or the one
    implied by `level`), falling back to any difficulty if the pool is too small.
    Deterministic ordering so interviews are reproducible.
    """
    diff = (difficulty or difficulty_for_level(level)).lower()
    pool = [p for p in PROBLEMS if p["difficulty"] == diff and p["slug"] not in exclude_slugs]
    if len(pool) < count:
        extra = [p for p in PROBLEMS if p["slug"] not in exclude_slugs and p not in pool]
        pool = pool + extra
    return pool[:count]
