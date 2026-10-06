import importlib.util
from pathlib import Path

from coding import get_problem

_spec = importlib.util.spec_from_file_location(
    "strip_answer_keys", Path(__file__).resolve().parents[1] / "scripts" / "strip_answer_keys.py")
sak = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sak)


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []
        self.committed = self.rolled_back = False

    def execute(self, sql, params=()):
        if sql.lstrip().upper().startswith("UPDATE"):
            self.updates.append(params)
        return self

    def fetchall(self):
        return self.rows

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _old_row(iid="a"):
    legacy = {"title": "LLM problem", "description": "d", "solution": "spoiler"}
    return {"id": iid, "track_config": {"generated_problems": [get_problem("two-sum"), legacy],
                                        "submissions": [{"code": "x"}]}}


def test_stripped_keeps_only_the_client_view():
    new = sak.stripped(_old_row()["track_config"])
    bank, legacy = new["generated_problems"]
    assert "test_cases" not in bank and "reference_solution" not in bank
    assert bank["slug"] == "two-sum" and bank["starter_code"]
    assert legacy == {"title": "LLM problem", "description": "d"}
    assert new["submissions"] == [{"code": "x"}]


def test_already_clean_rows_are_left_alone():
    clean = {"generated_problems": [sak.client_problem_view(get_problem("two-sum"))]}
    assert sak.stripped(clean) is None
    assert sak.stripped({}) is None
    assert sak.stripped({"generated_problems": "not a list"}) is None


def test_dry_run_counts_and_writes_nothing():
    conn = FakeConn([_old_row("a"), {"id": "b", "track_config": {}}])
    assert sak.run(conn, apply=False) == 1
    assert conn.updates == [] and conn.rolled_back and not conn.committed


def test_apply_rewrites_only_dirty_rows_in_one_transaction():
    conn = FakeConn([_old_row("a"), {"id": "b", "track_config": {}}, _old_row("c")])
    assert sak.run(conn, apply=True) == 2
    assert [p[1] for p in conn.updates] == ["a", "c"]
    assert "test_cases" not in conn.updates[0][0].obj["generated_problems"][0]
    assert conn.committed
