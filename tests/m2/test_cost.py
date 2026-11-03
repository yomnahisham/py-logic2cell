"""The cost function (src/hd/cost.py): stages, inverters, transistors, at most 3 in series."""

import os

import pytest

from src.common.stage import FULL
from src.hd.cost import cost, evaluate, expression, gated
from src.hd.liberty import truth_table
from src.paths import SPICE, ROOT


def test_maj4n_is_one_stage_of_12():
    c = cost(0x077F, 4)
    assert (c.stages, c.inverters, c.transistors) == (1, 0, 12)
    assert c.series <= 3


def test_nand2_and_and2():
    assert cost(0x7, 2).transistors == 4
    c = cost(0x8, 2)
    assert (c.stages, c.transistors, c.out_inverter) == (2, 6, True)


def test_xor2_needs_input_inverters():
    c = cost(0x6, 2)
    assert c.inverters >= 2 and all(evaluate(c, i) == (0x6666 >> i & 1) for i in range(16))


def test_not_buildable():
    assert cost(0x96, 3) is None          # xor3: six signals for the complex stage
    assert cost(0x7FFF, 4) is None        # nand4: four transistors in series
    assert cost(0, 4) is None and cost(FULL, 4) is None


def test_every_buildable_function_is_right():
    """The network computes the table, and its expression gives the same table back."""
    for t in range(1, FULL):
        c = cost(t, 4)
        if c is None:
            continue
        assert c.series <= 3
        assert all(evaluate(c, i) == (t >> i & 1) for i in range(16)), hex(t)
        names, table = truth_table(expression(c, list("ABCD")))
        back = sum(1 << i for i in range(16)
                   if table >> sum((i >> "ABCD".index(x) & 1) << j for j, x in enumerate(names)) & 1)
        assert back == t, hex(t)


def test_gated_counts_both_networks():
    c = cost(0x077F, 4)                   # !((C&D) | (A&B&(C|D))): C and D drive 4 transistors each
    assert [gated(c, k) for k in range(4)] == [2, 2, 4, 4]


@pytest.mark.skipif(not SPICE.exists() or not (ROOT / "given").exists(), reason="needs make setup")
def test_single_stage_hd_cells_match_spice():
    """On HD's x1 one-stage cells the cost function gives the transistor count of the PDK netlist."""
    from src.hd.area_model import training_rows
    rows = [r for r in training_rows() if r["stages"] == "single" and r["cost_transistors"] != ""]
    assert rows
    assert [(r["cell"], r["cost_transistors"]) for r in rows] == [(r["cell"], r["transistors"]) for r in rows]
