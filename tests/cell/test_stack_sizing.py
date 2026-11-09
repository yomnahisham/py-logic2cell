"""The Tutorial 3 sizing (option 1 handout, section 4 step 3): widths times the stack depth, folded to fit."""

from src.cell.build import stacked
from src.cell.network import Cell, build_stage, cell_check, euler_orders, stack_depths
from src.common.request import truth_table


def test_stack_depths():
    s = build_stage(("A", "B", "C"), "Y", "!((A & B) | C)")
    assert sorted((f.kind, f.gate, stack_depths(s)[i]) for i, f in enumerate(s.fets)) == [
        ("n", "A", 2), ("n", "B", 2), ("n", "C", 1), ("p", "A", 2), ("p", "B", 2), ("p", "C", 2)]


def test_nor3_folds_unequally():
    s = build_stage(("A", "B", "C"), "Y", "!(A | B | C)")
    cell = stacked(Cell((s,), s), 0.65, 1.0, lambda *a: None)
    p = [f for f in cell.flat.fets if f.kind == "p"]
    n = [f for f in cell.flat.fets if f.kind == "n"]
    assert (len(n), len(p)) == (3, 9)                    # NMOS 0.65 um fits its row; PMOS 3 x 3 um does not
    assert {f.w for f in p} == {1.0} and {f.w for f in n} == {0.65}
    assert cell_check(cell, truth_table("!(A | B | C)", ("A", "B", "C"))) == []
    orders = euler_orders(cell.flat)
    assert orders                                        # the PMOS row has columns of its own
    assert any(o.gates == ("C", "C", "C", "B", "B", "B", "A", "A", "A") for o in orders)


def test_broken_unequal_counts_without_passes():
    # a network whose rows differ in finger count has no common path unless one row passes under the
    # other's extra fingers; with an input missing from one row there is nothing to pass under
    from src.cell.network import Fet, Stage
    s = Stage(("A",), "Y", (Fet("n", "A", "Y", "VGND"), Fet("p", "B", "Y", "VPWR")))
    assert euler_orders(s) == []
