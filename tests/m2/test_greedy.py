"""The greedy selection, the cell-by-cell curve and the best-of-both table, on stand-in mappings
(no Yosys needed). The broken case: a candidate that makes the area bigger must be rejected."""

import csv

from src.hd import best_of_both, curve, greedy


def cell(name, saving=1.0, buildable=True):
    return {"name": name, "area_um2": 5.0, "buildable": buildable, "saving_um2": {"total": saving}}


def trial_from(gain):
    """total = 1000 minus the gains of the cells in the set; a cell's gain is a number."""
    def trial(cells):
        total = 1000.0 - sum(gain[c["name"]] for c in cells)
        return {"total": total, "best": {"d": total}}
    return trial


def test_keeps_only_cells_that_lower_the_total():
    gain = {"a": 10, "b": -3, "c": 5}                       # b makes the area bigger: broken case
    chosen, trace, _ = greedy.greedy([cell("a"), cell("b"), cell("c")], trial_from(gain), log=lambda s: None)
    assert [c["name"] for c in chosen] == ["a", "c"]
    assert [r["decision"] for r in trace] == ["kept", "rejected", "kept"]


def test_stops_at_the_limit():
    gain = {n: 1 for n in "abcde"}
    chosen, trace, _ = greedy.greedy([cell(n) for n in "abcde"], trial_from(gain), limit=2, log=lambda s: None)
    assert [c["name"] for c in chosen] == ["a", "b"]
    assert len(trace) == 2


def test_nothing_helps_gives_an_empty_set():
    chosen, _, base = greedy.greedy([cell("a")], trial_from({"a": 0}), log=lambda s: None)
    assert chosen == [] and base["total"] == 1000.0


def test_a_failing_mapping_is_a_rejection_not_a_crash():
    def trial(cells):
        if any(c["name"] == "bad" for c in cells):
            raise RuntimeError("abc crashed\nmore")
        return {"total": 1000.0 - 5 * len(cells), "best": {}}
    chosen, trace, _ = greedy.greedy([cell("bad"), cell("ok")], trial, log=lambda s: None)
    assert [c["name"] for c in chosen] == ["ok"]
    assert trace[0]["decision"].startswith("error: abc crashed")


def test_retry_revisits_a_cell_that_only_helps_with_another():
    def trial(cells):
        names = {c["name"] for c in cells}
        total = 1000.0 - (10 if "a" in names else 0) - (4 if {"a", "b"} <= names else 0)
        total += 3 if names == {"b"} else 0                  # b alone is worse
        return {"total": total, "best": {}}
    pool = [cell("b"), cell("a")]
    assert [c["name"] for c in greedy.greedy(pool, trial, log=lambda s: None)[0]] == ["a"]
    assert [c["name"] for c in greedy.greedy(pool, trial, retry=True, log=lambda s: None)[0]] == ["a", "b"]


def test_pool_drops_unbuildable_and_unprofitable():
    ranked = [cell("a"), cell("b", buildable=False), cell("c", saving=-1), cell("d")]
    assert [c["name"] for c in greedy.pool_of(ranked, 10)] == ["a", "d"]
    assert [c["name"] for c in greedy.pool_of(ranked, 1)] == ["a"]


def test_curve_has_a_baseline_row_and_one_row_per_cell():
    gain = {"a": 10, "b": 5}
    rows = curve.rows_of([cell("a"), cell("b")], trial_from(gain))
    assert [r["step"] for r in rows] == [0, 1, 2]
    assert [r["total_best_um2"] for r in rows] == [1000.0, 990.0, 985.0]
    assert rows[2]["reduction_percent"] == 1.5 and rows[0]["cell"] == "(baseline)"


def test_best_of_both_takes_the_smaller_script_on_each_side(tmp_path):
    src = tmp_path / "t5.csv"
    src.write_text("design,script,baseline_um2,new_cells_um2,reduction_percent,new_cell_instances,equivalence\n"
                   "x,A,100,98,2,1,pass\nx,B,110,95,13,2,pass\n"      # best: 100 -> 95
                   "y,A,50,52,-4,1,pass\ny,B,60,55,8,1,pass\n")       # best: 50 -> 52 (a loss)
    rows = best_of_both.best_rows(list(csv.DictReader(src.open())))
    x, y, total = rows
    assert (x["reduction_percent"], x["baseline_script"], x["new_script"]) == ("5.00", "A", "B")
    assert y["reduction_percent"] == "-4.00"
    assert total["design"] == "total" and total["baseline_best_um2"] == "150.0000" and total["new_best_um2"] == "147.0000"


def test_best_of_both_reports_a_failed_equivalence(tmp_path):
    src = tmp_path / "t5.csv"
    src.write_text("design,script,baseline_um2,new_cells_um2,reduction_percent,new_cell_instances,equivalence\n"
                   "x,A,100,98,2,1,pass\nx,B,110,95,13,2,FAIL\n")
    rows = best_of_both.best_rows(list(csv.DictReader(src.open())))
    assert rows[0]["equivalence"] == "FAIL" and rows[-1]["equivalence"] == "FAIL"